"""Degrau 0,5: a cena, gerada em vez de pedida a mao no GEM.

Ate 02/09/2026 este passo era humano — o Joao Pedro colava o `prompt-gem.txt`
no GEM e arrastava as imagens para `cenas/`. Funcionava, mas era o unico ponto
do pipeline que exigia uma pessoa, e por isso o unico que nao podia rodar
sozinho quando o receptor recebe um pedido.

**Por que Cloudflare Workers AI e nao Gemini.** A geracao de imagem do Gemini
tem free tier `limit: 0` — conferido de novo em 02/09/2026 contra a pagina de
precos, com todos os modelos de imagem marcando "Not available". O Workers AI da
10.000 neurons/dia sem cartao, e o `flux-2-klein-4b` aceita `width`/`height` de
256 a 1920, que e o que nos salva: o `cenas.ajustar` PROIBE ampliar, entao
gerador que so entrega 1024x1024 nao serve para a cena de login (1152x1440).

Medido no dia, contra a API de verdade:

  - o corpo TEM que ser multipart/form-data. JSON volta 400 com
    "required properties at '/' are 'multipart'".
  - a altura e arredondada para multiplo de 16 (pedi 823, vieram 816). Pedimos
    multiplo de 16 de proposito, senao a diferenca reaparece como bug um dia.
  - o prompt de ~2.000 caracteres passa inteiro; nao ha corte silencioso.
  - 20 a 41s por imagem.

Nada aqui e obrigatorio: sem chave, ou com a API fora do ar, o chamador cai no
caminho manual do GEM, que continua existindo. Geracao e conveniencia; o
fallback deterministico e que e a garantia.
"""

import base64
import io
import math
import os
import time
from pathlib import Path

import requests
from PIL import Image

import formatos
import prompt_gem

MODELO = "@cf/black-forest-labs/flux-2-klein-4b"
BASE = "https://api.cloudflare.com/client/v4/accounts/{conta}/ai/run/{modelo}"

# O modelo aceita ate 1920 e arredonda para multiplo de 16. Os dois numeros
# vivem aqui porque sao contrato da API, nao gosto nosso.
LADO_MAXIMO = 1920
MULTIPLO = 16

# Lado maior que pedimos. Nao e o maximo de proposito: a cena de login e
# consumida a 1152x1440, entao gerar maior so gastaria neuron para o
# `cenas.ajustar` jogar fora na reducao. 1440 e o ponto em que o login sai no
# tamanho exato e o cabecalho ainda sobra margem para o recorte na altura.
LADO_ALVO = 1440

TEMPO_LIMITE = 300
TENTATIVAS = 3

# $0,000287 por tile 512x512 de saida, $0,011 por 1.000 neurons (tabela do
# Workers AI). Serve para dizer quanto resta do dia ANTES de gastar.
NEURONS_POR_TILE = 0.000287 / 0.011 * 1000
NEURONS_POR_DIA = 10000


class SemChave(RuntimeError):
    """Falta CLOUDFLARE_ACCOUNT_ID ou CLOUDFLARE_API_TOKEN.

    Erro proprio, e nao ValueError, para o chamador poder cair no caminho
    manual sem engolir erro de verdade junto.
    """


class GeracaoFalhou(RuntimeError):
    """A API respondeu, mas nao com uma imagem. A mensagem traz o corpo."""


def credenciais():
    conta = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not conta or not token:
        raise SemChave(
            "CLOUDFLARE_ACCOUNT_ID e CLOUDFLARE_API_TOKEN precisam estar no "
            ".env. O token sai do template 'Workers AI' (Read + Edit) em "
            "dash.cloudflare.com — Read sozinho nao roda inferencia.")
    return conta, token


def _redondo(valor):
    """Multiplo de 16 mais proximo, nunca abaixo de 256 nem acima de 1920."""
    valor = int(round(valor / MULTIPLO)) * MULTIPLO
    return max(256, min(LADO_MAXIMO, valor))


def dimensao(formato):
    """(largura, altura) a pedir para este formato.

    Sai da PROPORCAO pedida no prompt, e nao da dimensao final da cena: o
    cabecalho e gerado panoramico de proposito, com topo e base descartaveis,
    porque e isso que o prompt combina com o modelo. O piso e a cena final —
    abaixo dela o `cenas.ajustar` levanta CenaPequena, com razao.
    """
    a, b = (int(n) for n in formato.proporcao_pedida.split(":"))
    aspecto = a / b
    alvo_largura, alvo_altura = formato.cena

    # O menor retangulo neste aspecto que ainda cobre a cena depois do recorte
    # central. Qual lado limita depende de quem e mais largo.
    if aspecto >= alvo_largura / alvo_altura:
        altura = alvo_altura
        largura = altura * aspecto
    else:
        largura = alvo_largura
        altura = largura / aspecto

    # Sobe ate LADO_ALVO no lado maior, sem nunca encolher abaixo do piso.
    fator = max(1.0, LADO_ALVO / max(largura, altura))
    largura, altura = _redondo(largura * fator), _redondo(altura * fator)

    # O arredondamento pode ter comido um pixel do piso. Devolve o degrau.
    if largura < alvo_largura:
        largura += MULTIPLO
    if altura < alvo_altura:
        altura += MULTIPLO
    return largura, altura


def custo_neurons(largura, altura):
    """Quantos neurons uma imagem deste tamanho consome, pela tabela deles."""
    tiles = math.ceil(largura / 512) * math.ceil(altura / 512)
    return int(round(tiles * NEURONS_POR_TILE))


def orcamento(quantas=1):
    """[(formato, largura, altura, neurons)] e o total, sem gerar nada.

    Existe para a decisao de gastar vir ANTES do gasto: sao 10.000 neurons por
    dia e um cliente inteiro consome uma fatia visivel deles.
    """
    linhas, total = [], 0
    for formato in formatos.COM_CENA:
        largura, altura = dimensao(formato)
        custo = custo_neurons(largura, altura) * quantas
        linhas.append((formato.chave, largura, altura, custo))
        total += custo
    return linhas, total


def gerar(prompt, largura, altura, semente=None, tempo_limite=TEMPO_LIMITE):
    """Um prompt -> uma PIL.Image no tamanho pedido. Levanta em vez de mentir."""
    conta, token = credenciais()
    url = BASE.format(conta=conta, modelo=MODELO)
    campos = {"prompt": (None, prompt), "width": (None, str(largura)),
              "height": (None, str(altura))}
    if semente is not None:
        campos["seed"] = (None, str(semente))

    ultimo = ""
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                              files=campos, timeout=tempo_limite)
        except requests.RequestException as erro:
            ultimo = f"{type(erro).__name__}: {erro}"
        else:
            if r.status_code == 200:
                return _imagem_da_resposta(r)
            ultimo = f"http {r.status_code}: {r.text[:300]}"
            # 4xx que nao seja 429 e erro de pedido: repetir so gasta tempo.
            if 400 <= r.status_code < 500 and r.status_code != 429:
                break
        if tentativa < TENTATIVAS:
            time.sleep(2 ** tentativa)
    raise GeracaoFalhou(f"{MODELO} nao devolveu imagem ({ultimo})")


def _imagem_da_resposta(r):
    dados = r.json()
    if not dados.get("success", True):
        raise GeracaoFalhou(f"erros: {dados.get('errors')}")
    b64 = (dados.get("result") or {}).get("image")
    if not b64:
        raise GeracaoFalhou(f"resposta sem result.image: {str(dados)[:300]}")
    img = Image.open(io.BytesIO(base64.b64decode(b64)))
    img.load()
    return img


def encher(pasta_cenas, paleta, contexto, quantas=2, semente=1, ecoar=None):
    """Gera `quantas` cenas de cada formato dentro de `pasta_cenas`.

    Grava como `login-1.png` / `cabecalho-1.png`: o `cenas.procurar` da
    precedencia ao nome sobre o aspecto, entao nomear elimina o palpite.

    Devolve a lista de laudos. **Uma falha nao derruba as outras**: cada cena e
    independente, e uma cena a menos so significa uma candidata a menos para o
    juiz — enquanto sobrar uma, a peca sai; se nao sobrar nenhuma, o fallback
    deterministico entrega assim mesmo.
    """
    pasta_cenas = Path(pasta_cenas)
    pasta_cenas.mkdir(parents=True, exist_ok=True)
    laudos = []

    for formato in formatos.COM_CENA:
        largura, altura = dimensao(formato)
        prompt = prompt_gem.montar(formato, paleta, contexto)
        for indice in range(1, quantas + 1):
            nome = f"{formato.chave}-{indice}.png"
            laudo = {"formato": formato.chave, "arquivo": nome,
                     "pedido": [largura, altura], "neurons": custo_neurons(largura, altura)}
            if ecoar:
                ecoar(f"  gerando {nome}  {largura}x{altura} "
                      f"(~{laudo['neurons']} neurons)")
            inicio = time.time()
            try:
                img = gerar(prompt, largura, altura, semente=semente + indice)
            except (SemChave, GeracaoFalhou) as erro:
                laudo.update(ok=False, erro=str(erro))
                if ecoar:
                    ecoar(f"    [FALHOU] {erro}")
                if isinstance(erro, SemChave):
                    laudos.append(laudo)
                    return laudos  # sem chave nao adianta tentar os outros
            else:
                caminho = pasta_cenas / nome
                img.save(caminho)
                laudo.update(ok=True, entregue=list(img.size),
                             segundos=round(time.time() - inicio, 1))
                if ecoar:
                    ecoar(f"    [OK] {img.size[0]}x{img.size[1]} em "
                          f"{laudo['segundos']}s")
            laudos.append(laudo)
    return laudos
