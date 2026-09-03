"""Segmento do cliente -> objetos concretos e ambiente para a cena.

Era a "Etapa 0" do GEM, feita pelo proprio modelo de imagem. Aqui e uma chamada
de texto separada, e o resultado fica **em cache por segmento**: dois clientes
de autopecas recebem a mesma lista, o que torna a peca reproduzivel e nao gasta
chamada a toa. O cache tambem e o lugar onde o Joao Pedro corrige a mao quando
a lista sai ruim — e ai ela fica corrigida para sempre.

Sem chave, ou sem rede, cai numa heuristica local. Nao poder falar com a API
nunca pode ser motivo para o pipeline parar.
"""

import json
import re
import unicodedata
from pathlib import Path

import requests

import juiz

AQUI = Path(__file__).resolve().parent
CACHE = AQUI / "cache_segmentos.json"

GENERICO = {
    "objetos": ["caixas de papelao kraft empilhadas", "paletes de madeira",
                "engradados plasticos", "rolos de fita e material de expedicao"],
    "ambiente": "galpao de distribuicao amplo, prateleiras ao fundo",
    "origem": "generico",
}

INSTRUCAO = """Um portal de compras B2B vai receber um banner fotografico para
um cliente do segmento abaixo. Preciso saber o que fotografar.

Segmento: {segmento}

Responda SOMENTE JSON com duas chaves:
- objetos: lista de 4 a 6 objetos FISICOS e CONCRETOS daquele ramo, que
  apareceriam em primeiro plano numa foto de campanha. Coisas, nao conceitos.
  Nada que tenha texto, rotulo ou marca visivel.
- ambiente: uma frase curta descrevendo o local de trabalho tipico do ramo,
  para ficar desfocado ao fundo.

Tudo em portugues do Brasil."""


# Ambiente por palavra-chave do setor. Existe porque a consulta ao modelo e a
# primeira coisa a morrer quando a cota do dia acaba (429), e ai a cena inteira
# virava "galpao de distribuicao" — foi o que o Joao Pedro reprovou na Aroca
# Mercearia em 02/09/2026: mercearia fina fotografada como estoque de caixas.
# Errar o ambiente por palavra-chave e muito melhor que errar por padrao.
AMBIENTES = (
    (("aliment", "mercearia", "queijo", "conserva", "pescado", "congelad",
      "trigo", "farinha", "bebida", "hortifruti"),
     "cozinha profissional clara, bancada de madeira e utensilios ao fundo"),
    (("autopec", "automotiv", "pelicula", "pneu", "motopec", "arrefec"),
     "oficina automotiva limpa e bem iluminada, elevador ao fundo"),
    (("eletric", "painel", "industri", "component", "transmiss", "fabricante"),
     "chao de fabrica limpo e organizado, maquinario ao fundo"),
    (("saude", "medico", "hospital", "nutric", "farmac", "veterin", "animal"),
     "sala clinica clara, bancada e armarios ao fundo"),
    (("cosmetic", "beleza", "unha", "cabelo"),
     "estudio de beleza claro, bancada com espelho ao fundo"),
    (("construcao", "vidro", "revestiment", "tinta", "acabament"),
     "ambiente recem-acabado e iluminado, parede e piso ao fundo"),
    (("tecnolog", "computac", "eletronic", "informatic"),
     "bancada de laboratorio de eletronica, racks ao fundo"),
    (("seguranca", "monitorament", "vigilan"),
     "central de monitoramento, telas ao fundo"),
    (("equipament", "movimentac", "logistic", "atacad", "distribui"),
     "centro de distribuicao amplo e organizado, empilhadeira ao fundo"),
)


def ambiente_por_palavra(segmento):
    """Ambiente provavel do ramo, sem rede. None quando nada bate."""
    texto = _chave(segmento).replace("-", " ")
    for palavras, ambiente in AMBIENTES:
        if any(p in texto for p in palavras):
            return ambiente
    return None


# Peso, volume, embalagem e codigo nao sao coisas de fotografar: "Queijo
# Parmesao Ralado 500g" vira "Queijo Parmesao Ralado". Sem isto o modelo tenta
# desenhar o rotulo com o numero, que e justamente o que o prompt proibe.
_MEDIDA = re.compile(
    r"\b\d+[.,]?\d*\s*(kg|g|gr|mg|ml|l|lt|litros?|un|und|unid|pcs?|pecas?|"
    r"cx|caixas?|pacotes?|fardos?|cm|mm|m|polegadas?|\"|')\b|"
    r"\b\d+\s*x\s*\d+\S*|\(.*?\)|\b\d{3,}\b", re.I)


def _limpar_nome(nome):
    nome = _MEDIDA.sub(" ", str(nome))
    nome = re.sub(r"\s*[-–—]\s*$", "", re.sub(r"\s{2,}", " ", nome)).strip(" -–—,")
    return nome[:58].strip()


_LIGACAO = {"de", "da", "do", "das", "dos", "e", "com", "para", "em", "a", "o",
            "sem", "por", "no", "na", "tipo"}

# Palavra de EMBALAGEM sai do nome do produto. "Champignon Inteiro Balde" pede
# um balde, e balde tem rotulo — o rotulo sai escrito em letra torta, que e o
# defeito que estamos caçando. O produto e o champignon; o balde e como ele
# viaja, e nao interessa a foto.
_EMBALAGEM = {"balde", "pote", "vidro", "pouch", "stand", "pacote", "caixa",
              "sache", "lata", "garrafa", "frasco", "bisnaga", "bandeja",
              "fardo", "saco", "embalagem", "refil", "display", "cartucho"}


def _sem_acento(palavra):
    forma = unicodedata.normalize("NFKD", palavra.lower())
    return "".join(c for c in forma if not unicodedata.combining(c))


def tirar_marcas(nomes):
    """"Queijo de Cabra Boursin" -> "Queijo de Cabra". Sem lista de marcas.

    Nome de produto e <tipo> + <marca ou variante>, e o tipo se repete pelo
    catalogo enquanto a marca e quase sempre unica. Entao palavra que aparece
    em dois ou mais produtos e tipo; palavra que aparece uma vez so cai.

    Isto nao e capricho. Em 02/09/2026 a cena da Aroca saiu com potes escritos
    "Bousin", "DIAMIANT DA SERA" e "Le t Madre": passar o nome da marca faz o
    modelo desenhar o rotulo dela, em letra torta, que e exatamente o que o
    prompt proibe. O modelo nao escreve o que nao lhe foi dito.
    """
    contagem = {}
    for nome in nomes:
        for palavra in {_sem_acento(p) for p in re.findall(r"[^\W\d_]{2,}", nome)}:
            contagem[palavra] = contagem.get(palavra, 0) + 1

    tipos, vistos = [], set()
    for nome in nomes:
        mantidas = []
        for palavra in nome.split():
            limpa = _sem_acento(re.sub(r"[^\w]", "", palavra, flags=re.UNICODE))
            if limpa in _EMBALAGEM:
                break  # dali para a frente e como o produto viaja, nao o produto
            if limpa in _LIGACAO or contagem.get(limpa, 0) >= 2:
                mantidas.append(palavra)
            else:
                break  # chegou na marca: o resto do nome e dela
        # Tirar as ligacoes soltas do fim ("Queijo de" nao e coisa nenhuma).
        while mantidas and _sem_acento(mantidas[-1].strip(",.-")) in _LIGACAO:
            mantidas.pop()
        tipo = " ".join(mantidas).strip(" -–—,")
        chave = _sem_acento(tipo)
        if len(tipo) >= 4 and chave not in vistos:
            vistos.add(chave)
            tipos.append(tipo)

    # Fica a forma mais CURTA de cada familia. "Kit PPF Interno Ford Ranger"
    # sobreviveu ao corte por frequencia (a Ford aparece em varios kits), mas
    # "Kit PPF Interno" tambem esta na lista — e a curta e a generica, que e a
    # que nao vira rotulo desenhado. De quebra some a redundancia de listar
    # "Queijo", "Queijo de Cabra" e "Queijo de Cabra Petit Formage" juntos.
    curtos = sorted(tipos, key=len)
    fora = set()
    for i, curto in enumerate(curtos):
        base = _sem_acento(curto) + " "
        for longo in curtos[i + 1:]:
            if (_sem_acento(longo) + " ").startswith(base):
                fora.add(longo)
    return [t for t in tipos if t not in fora]


def do_catalogo(caminho, maximo=8):
    """Objetos e categorias a partir do catalogo REAL que a rotina montou.

    E a correcao do defeito mais caro do gerador: a cena nao mostrava o que o
    cliente vende. Inferir do setor sempre foi um palpite — o catalogo nao e.
    Ninguem precisa adivinhar que uma mercearia fina vende queijo de cabra
    quando existe um arquivo dizendo exatamente isso.

    Devolve {} quando o arquivo nao existe ou nao tem produto: o chamador
    continua no caminho antigo, e nao ha regressao para quem nao tem catalogo.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        return {}
    try:
        poc = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    produtos, categorias = [], []
    for etapa in poc.get("etapas", []):
        alvo = {"products": produtos, "categories": categorias}.get(etapa.get("endpoint"))
        if alvo is None:
            continue
        for pedido in etapa.get("requests", []):
            nome = (pedido.get("payload") or {}).get("name") or pedido.get("label")
            if nome:
                alvo.append(_limpar_nome(nome))

    limpos = tirar_marcas([n for n in produtos if n])
    # As categorias entram no fim porque sao genericas por natureza ("Queijos
    # de Cabra", "Correntes Transportadoras") — sao o tipo puro, sem marca —
    # e cobrem a loja toda quando o catalogo e de um nicho so.
    for categoria in categorias:
        if categoria and _sem_acento(categoria) not in {_sem_acento(x) for x in limpos}:
            limpos.append(categoria)
    # Dois bastam. Tirar marca e embalagem colapsa quinze variacoes num tipo so
    # ("Queijo de Cabra"), e isso e acerto, nao falta de dado: dois tipos reais
    # do cliente valem mais que os quatro objetos genericos de galpao.
    if len(limpos) < 2:
        return {}

    # Passo largo em vez das primeiras N: o catalogo vem agrupado por
    # categoria, entao pegar do topo devolveria oito variacoes de queijo de
    # cabra e a cena sairia com um produto so. Espalhar cobre a loja inteira.
    if len(limpos) > maximo:
        passo = len(limpos) / maximo
        limpos = [limpos[int(i * passo)] for i in range(maximo)]

    return {"objetos": limpos, "categorias": categorias,
            "empresa": poc.get("empresa", ""), "setor": poc.get("setor", "")}


def _chave(segmento):
    texto = unicodedata.normalize("NFKD", segmento.strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-") or "generico"


def _ler_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Cache corrompido nao pode derrubar o pipeline: vale menos que ele.
            return {}
    return {}


def _gravar_cache(dados):
    CACHE.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")


def resolver(segmento, modelo, usar_rede=True, catalogo=None):
    """Devolve {'objetos': [...], 'ambiente': str, 'origem': str}.

    `catalogo` — caminho de um `<cliente>_poc.json` — manda sobre tudo. Produto
    que o cliente de fato vende ganha de qualquer inferencia, e de quebra nao
    depende de cota: foi um 429 do Gemini que fez a Aroca Mercearia virar um
    galpao de caixas na primeira rodada do estudio.
    """
    chave = _chave(segmento)
    cache = _ler_cache()

    if catalogo:
        do_arquivo = do_catalogo(catalogo)
        if do_arquivo:
            ambiente = ((cache.get(chave) or {}).get("ambiente")
                        or ambiente_por_palavra(segmento)
                        or GENERICO["ambiente"])
            return {"objetos": do_arquivo["objetos"], "ambiente": ambiente,
                    "origem": "catalogo",
                    "categorias": do_arquivo.get("categorias", [])}

    if chave in cache:
        registro = dict(cache[chave])
        registro["origem"] = "cache"
        return registro

    if not usar_rede:
        registro = dict(GENERICO)
        registro["ambiente"] = ambiente_por_palavra(segmento) or GENERICO["ambiente"]
        return registro

    try:
        corpo = {
            "contents": [{"role": "user", "parts": [
                {"text": INSTRUCAO.format(segmento=segmento)}]}],
            "generationConfig": {"response_mime_type": "application/json",
                                 "temperature": 0},
        }
        resposta = requests.post(f"{juiz.BASE}/models/{modelo}:generateContent",
                                 params={"key": juiz.chave()}, json=corpo, timeout=120)
        resposta.raise_for_status()
        texto = "".join(p.get("text", "") for p in
                        resposta.json()["candidates"][0]["content"]["parts"])
        dados = json.loads(texto)
        objetos = [str(o) for o in dados.get("objetos", [])][:6]
        ambiente = str(dados.get("ambiente", "")).strip()
        if len(objetos) < 3 or not ambiente:
            raise ValueError(f"resposta magra: {dados}")
    except (requests.RequestException, juiz.SemChave, KeyError, ValueError,
            json.JSONDecodeError) as erro:
        registro = dict(GENERICO)
        # Cota estourada (429) e o caso comum, e ate 02/09/2026 ele derrubava
        # o ambiente junto com os objetos. O ambiente por palavra-chave nao
        # precisa de rede e acerta o ramo na maioria das vezes.
        registro["ambiente"] = ambiente_por_palavra(segmento) or GENERICO["ambiente"]
        registro["erro"] = f"{type(erro).__name__}: {erro}"
        return registro

    registro = {"objetos": objetos, "ambiente": ambiente}
    cache[chave] = registro
    _gravar_cache(cache)
    saida = dict(registro)
    saida["origem"] = "consultado"
    return saida
