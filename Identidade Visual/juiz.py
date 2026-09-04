"""Degrau 2: o juiz de visao.

Roda num modelo de TEXTO com imagem de entrada, e nao num modelo de imagem: o
free tier de geracao de imagem do Gemini e `limit: 0`, mas o de texto com visao
funciona. Foi medido, nao suposto — ver o README.

**A escolha do provedor vem da regua (`provedores`), e hoje so o Gemini esta
la.** O suporte a mais de um existe porque o Gemini tem dois defeitos medidos:
cai em 429 de cota diaria, e — pior — APROVOU a `cabecalho-1` da Aroca (03/09),
uma cena com "MOZZI CUUDLA" e "IUEZGAILS" escritos nas embalagens. Confirmado a
olho. Ele rodou e nao viu o texto.

O substituto obvio nao serviu, e vale registrar para ninguem repetir: o
`@cf/meta/llama-3.2-11b-vision-instruct` (mesma conta que gera as cenas, sem
cadastro novo, ~15 neurons por julgamento) respondeu `has_text: true` em 10 de
10 chamadas, incluindo um controle de formas geometricas sem um caractere — no
qual ele mesmo listou "square, circle, oval" e ainda assim marcou verdadeiro. No
checklist de 12 criterios marcou tudo verdadeiro, inclusive "elemento cortado".
Ele carimba, nao julga; o `llava-1.5-7b` reprova ate um retangulo cinza. A
PRIMEIRA amostra dos dois parecia boa — foi repetir que derrubou.

O juiz recebe a paleta e o segmento junto com a imagem. Sem esse contexto ele
julga no vacuo e nao tem como responder "a cor destoa da marca".

O vies e empurrado para o lado seguro: na duvida, marcar o defeito como
presente. Falso positivo custa uma regeracao; falso negativo custa a reuniao.
"""

import base64
import io
import json
import os
import time
from pathlib import Path

import requests
from PIL import Image

BASE = "https://generativelanguage.googleapis.com/v1beta"
BASE_CLOUDFLARE = "https://api.cloudflare.com/client/v4"
MODELO_CLOUDFLARE = "@cf/meta/llama-3.2-11b-vision-instruct"

CHAVES_ESPERADAS = (
    "tem_texto_ou_letras", "tem_logotipo_ou_marca", "tem_deformacao_anatomica",
    "tem_objeto_duplicado", "tem_artefato", "tem_elemento_cortado",
    "composicao_entulhada", "cor_destoa_da_paleta", "cena_condiz_com_o_segmento",
    "parece_banco_de_imagens_generico", "nota_estetica", "defeito_principal",
)


class SemChave(RuntimeError):
    """GEMINI_API_KEY ausente. O laco cai no fallback em vez de travar."""


class LimiteDiarioEsgotado(RuntimeError):
    """429 que nao passa com backoff: a cota diaria do free tier acabou hoje.

    Distinto do 429 de rajada de proposito — um pede espera, o outro pede que
    o lote pare de martelar e caia no fallback.
    """


def chave():
    valor = os.getenv("GEMINI_API_KEY", "").strip().strip('"').strip("'")
    if not valor:
        raise SemChave(
            "GEMINI_API_KEY nao esta no ambiente. Sem ela o degrau 2 nao roda e "
            "toda cena vira fallback. Ver .env.example.")
    return valor


def _instrucao(contexto):
    return f"""Voce e um diretor de arte avaliando material que vai ser exibido
numa demonstracao comercial B2B, na frente do cliente. Reprovar por engano custa
uma nova tentativa; aprovar algo defeituoso custa a reuniao. **Na duvida, marque
o defeito como presente.**

O que esta imagem deveria ser: {contexto['descricao']}
Segmento do cliente: {contexto['segmento']}
Paleta da marca: {contexto['principal']} (principal), {contexto['destaque']} (destaque).

Responda SOMENTE um objeto JSON com exatamente estas chaves:

- tem_texto_ou_letras: true se houver qualquer caractere, palavra, numero,
  rotulo, marca d'agua ou pseudo-texto legivel em qualquer parte da imagem.
- tem_logotipo_ou_marca: true se houver um logotipo desenhado dentro da cena.
- tem_deformacao_anatomica: true se houver mao, dedo, rosto ou objeto com
  geometria impossivel.
- tem_objeto_duplicado: true se algo aparecer repetido de forma nao intencional.
- tem_artefato: true se houver borrao, mancha, textura derretida ou ruido.
- tem_elemento_cortado: true se o assunto principal for decepado pela margem.
- composicao_entulhada: true se nao houver espaco negativo nem hierarquia clara.
- cor_destoa_da_paleta: true se a cor dominante estiver fora da paleta informada.
- cena_condiz_com_o_segmento: true se a cena mostra mesmo aquele ramo de negocio.
- parece_banco_de_imagens_generico: true se parece foto de banco com filtro.
- nota_estetica: inteiro de 0 a 5. Pergunte-se "isto serviria numa campanha B2B
  paga?" — 5 e sim sem ressalva, 0 e inutilizavel.
- defeito_principal: uma frase curta com o pior problema, ou "" se nao houver."""


def credenciais_cloudflare():
    conta = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip().strip('"').strip("'")
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip().strip('"').strip("'")
    if not conta or not token:
        raise SemChave(
            "CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN nao estao no ambiente. "
            "Sao as mesmas que geram as cenas — se a geracao roda, o juiz roda.")
    return conta, token


def _jpeg(imagem, lado):
    """JPEG reduzido, para o payload caber e a leitura nao piorar.

    896px no lado maior: o texto que interessa e rotulo em embalagem, que
    continua legivel nessa escala, e a cena de 1440px em base64 so engorda o
    corpo da requisicao.
    """
    img = imagem.convert("RGB")
    if max(img.size) > lado:
        escala = lado / max(img.size)
        img = img.resize((int(img.width * escala), int(img.height * escala)),
                         Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def _texto_para_json(texto):
    """O JSON do veredito, mesmo vindo cercado de prosa ou de crases.

    O Gemini responde com `response_mime_type` e devolve JSON puro; o llama nao
    tem esse controle e as vezes embrulha o objeto. Recortar entre a primeira
    chave e a ultima e mais barato que exigir obediencia do modelo.
    """
    texto = (texto or "").strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio < 0 or fim <= inicio:
            raise
        return json.loads(texto[inicio:fim + 1])


def _conferir(veredito):
    faltando = [c for c in CHAVES_ESPERADAS if c not in veredito]
    if faltando:
        raise RuntimeError(f"juiz devolveu JSON incompleto, faltou: {faltando}")
    return veredito


def _avaliar_cloudflare(imagem, contexto, config, tentativas):
    """Julga pelo Workers AI, na mesma conta que gera as cenas."""
    conta, token = credenciais_cloudflare()
    modelo = config.get("modelo_cloudflare", MODELO_CLOUDFLARE)
    b64 = base64.b64encode(_jpeg(imagem, config.get("lado_maximo_px", 896))).decode()
    corpo = {
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": _instrucao(contexto)},
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        "max_tokens": 700,
        "temperature": 0,
    }
    url = f"{BASE_CLOUDFLARE}/accounts/{conta}/ai/run/{modelo}"
    ultimo = ""
    for tentativa in range(1, tentativas + 1):
        resposta = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                                 json=corpo, timeout=240)
        if resposta.status_code == 429 or resposta.status_code >= 500:
            ultimo = f"HTTP {resposta.status_code}"
            if tentativa < tentativas:
                time.sleep(4 * tentativa)
                continue
            raise RuntimeError(f"{ultimo} persistente no juiz da Cloudflare.")
        resposta.raise_for_status()
        dados = resposta.json()
        if not dados.get("success"):
            raise RuntimeError(f"juiz da Cloudflare recusou: "
                               f"{str(dados.get('errors'))[:200]}")
        return _conferir(_texto_para_json(dados["result"].get("response")))
    raise RuntimeError(f"juiz da Cloudflare nao respondeu ({ultimo})")


def avaliar(imagem, contexto, config, tentativas=4):
    """Um julgamento, no primeiro provedor que responder.

    A ordem vem da regua (`provedores`). Cair para o proximo e o ponto: uma cota
    diaria estourada num deles nao pode virar peca nao julgada — foi assim que
    arte com texto inventado saiu como "cena aprovada" em 04/09/2026.
    """
    erros = []
    for nome in config.get("provedores", ("cloudflare", "gemini")):
        try:
            if nome == "cloudflare":
                return _avaliar_cloudflare(imagem, contexto, config, tentativas)
            if nome == "gemini":
                return _avaliar_gemini(imagem, contexto, config, tentativas)
            raise RuntimeError(f"provedor de juiz desconhecido: {nome!r}")
        except (SemChave, LimiteDiarioEsgotado, RuntimeError,
                requests.RequestException, json.JSONDecodeError, KeyError) as erro:
            erros.append(f"{nome}: {type(erro).__name__}: {erro}")
    if all("LimiteDiarioEsgotado" in e or "SemChave" in e for e in erros):
        raise LimiteDiarioEsgotado(" | ".join(erros))
    raise RuntimeError(" | ".join(erros) or "nenhum provedor de juiz configurado")


def _avaliar_gemini(imagem, contexto, config, tentativas=4):
    """Uma chamada de julgamento. Devolve o dict do veredito.

    `imagem` e um PIL.Image; vai inline em PNG. Nao usa a File API: banner cabe
    folgado no limite de payload, e a File API acrescenta upload e poll por nada.
    """
    buffer = io.BytesIO()
    imagem.convert("RGB").save(buffer, format="PNG", optimize=True)

    corpo = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "image/png",
                             "data": base64.b64encode(buffer.getvalue()).decode()}},
            {"text": _instrucao(contexto)},
        ]}],
        "generationConfig": {"response_mime_type": "application/json",
                             "temperature": 0},
    }

    modelo = config["modelo"]
    for tentativa in range(1, tentativas + 1):
        resposta = requests.post(f"{BASE}/models/{modelo}:generateContent",
                                 params={"key": chave()}, json=corpo, timeout=240)

        # 429 de rajada passa com espera; 429 de cota nao passa hoje. Insistir
        # no segundo caso so queima tempo — o laco cai no fallback.
        if resposta.status_code == 429:
            if tentativa < tentativas:
                time.sleep(15 * tentativa)
                continue
            raise LimiteDiarioEsgotado(
                "429 persistente no juiz — provavelmente a cota diaria do free "
                "tier. As pecas desta rodada vao para o fallback.")

        # 5xx e indisponibilidade momentanea do lado do Google — vista de
        # verdade num 503 durante o desenvolvimento. Passa com espera curta, e
        # deixar estourar aqui jogaria uma peca boa no fallback por nada.
        if resposta.status_code >= 500:
            if tentativa < tentativas:
                time.sleep(4 * tentativa)
                continue
            raise RuntimeError(
                f"{resposta.status_code} persistente no juiz — servico "
                f"indisponivel. A peca vai para o fallback.")

        resposta.raise_for_status()
        dados = resposta.json()
        candidatos = dados.get("candidates")
        if not candidatos:
            raise RuntimeError(f"juiz sem resposta: {dados.get('promptFeedback', dados)}")
        texto = "".join(p.get("text", "")
                        for p in candidatos[0]["content"]["parts"])
        return _conferir(_texto_para_json(texto))

    raise RuntimeError("inalcancavel")


def decidir(veredito, config):
    """Aplica a regra, sem margem. Devolve (aprovado, motivos)."""
    motivos = []
    for chave_fatal in config["fatais"]:
        if veredito.get(chave_fatal):
            motivos.append(chave_fatal)
    for chave_exigida in config["exigidos_verdadeiros"]:
        if not veredito.get(chave_exigida):
            motivos.append(f"nao_{chave_exigida}")
    nota = veredito.get("nota_estetica", 0)
    if nota < config["nota_minima"]:
        motivos.append(f"nota_{nota}_abaixo_de_{config['nota_minima']}")
    return (not motivos), motivos
