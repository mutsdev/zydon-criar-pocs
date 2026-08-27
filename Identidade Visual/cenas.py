"""Carrega as cenas que o Joao Pedro gerou no GEM e as encaixa no formato.

O caminho e semiautomatico por um motivo medido: o free tier de geracao de
imagem do Gemini e `limit: 0` em todos os modelos. O GEM no aplicativo continua
gratuito, entao a geracao fica com ele e o resto — paleta, recorte, composicao,
validacao e fallback — fica com o script.

**Duas operacoes, e so duas: recortar e reduzir.** Nunca esticar (deformaria a
cena) e nunca ampliar (inventaria pixel que nao existe e o degrau 1 reprovaria
por foco). Se a cena for pequena demais, isto falha e diz exatamente o tamanho
que faltou — e um pedido acionavel para a proxima exportacao do GEM.
"""

import math
from pathlib import Path

from PIL import Image

# Tolerancia de ampliacao: so o arredondamento, nada de "quase cabe".
AMPLIACAO_MAXIMA = 1.02

EXTENSOES = (".png", ".jpg", ".jpeg", ".webp")


class CenaPequena(ValueError):
    """A cena nao tem pixels suficientes. A mensagem diz o minimo exigido."""


def classificar(caminho, candidatos):
    """A que formato esta cena pertence, julgando pelo ASPECTO dela.

    Existe para o arquivo poder ser arrastado do navegador direto para a pasta,
    com o nome que o Gemini deu (`Gemini_Generated_Image_a1b2c3.png`). Exigir
    renomear a mao seria atrito por nada: as duas cenas tem formatos que nao se
    confundem — login e 4:5 retrato (0,80) e cabecalho e 3,3:1 panoramico.

    A comparacao e em log para ser simetrica: 2x mais largo e 2x mais alto
    devem estar a mesma distancia do alvo. Devolve None se nenhum candidato
    estiver dentro de um fator 1,8 — arquivo muito fora nao e chute, e erro.
    """
    try:
        with Image.open(caminho) as img:
            largura, altura = img.size
    except Exception:
        return None
    if not altura:
        return None

    aspecto = largura / altura
    melhor, menor = None, None
    for formato in candidatos:
        distancia = abs(math.log(aspecto / formato.aspecto_cena))
        if menor is None or distancia < menor:
            melhor, menor = formato, distancia
    return melhor if menor is not None and menor <= math.log(1.8) else None


def procurar(pasta, formato, candidatos=None):
    """Todas as cenas daquele formato, em ordem estavel.

    Duas formas de indicar o formato, nesta ordem de precedencia:

      1. **Pelo nome** — `login-1.png`, `cabecalho-a.jpg`. Explicito manda.
      2. **Pelo aspecto** — qualquer outro nome e classificado por `classificar`.
         E o caminho de quem arrasta a imagem do Gemini direto para a pasta.

    Ordem alfabetica vira ordem de tentativa, entao "a tentativa 2" e uma coisa
    reproduzivel entre execucoes.
    """
    pasta = Path(pasta)
    if not pasta.exists():
        return []
    candidatos = list(candidatos) if candidatos else [formato]
    chaves = {f.chave for f in candidatos}

    nomeados, avulsos = [], []
    for caminho in sorted(pasta.iterdir()):
        if caminho.suffix.lower() not in EXTENSOES:
            continue
        stem = caminho.stem.lower()
        if stem.startswith(formato.chave):
            nomeados.append(caminho)
        elif not any(stem.startswith(c) for c in chaves):
            if classificar(caminho, candidatos) is formato:
                avulsos.append(caminho)
    return nomeados + avulsos


def ajustar(img, formato):
    """Recorta ao aspecto da cena e reduz ao tamanho exato. Devolve (img, laudo).

    O recorte e centralizado: o prompt entregue ao GEM ja pede que o assunto
    viva no centro e que as margens sejam descartaveis, entao cortar pelo centro
    e cumprir o enquadramento combinado, nao mutilar.
    """
    alvo_largura, alvo_altura = formato.cena
    original = img.size
    largura, altura = img.size
    aspecto_alvo = alvo_largura / alvo_altura

    if largura / altura > aspecto_alvo:
        nova_largura = int(round(altura * aspecto_alvo))
        esquerda = (largura - nova_largura) // 2
        caixa = (esquerda, 0, esquerda + nova_largura, altura)
    else:
        nova_altura = int(round(largura / aspecto_alvo))
        topo = (altura - nova_altura) // 2
        caixa = (0, topo, largura, topo + nova_altura)

    recortada = img.crop(caixa)
    fator = alvo_largura / recortada.size[0]
    if fator > AMPLIACAO_MAXIMA:
        raise CenaPequena(
            f"cena de {original[0]}x{original[1]} e pequena demais para "
            f"{formato.chave}: depois do recorte sobram {recortada.size[0]}x"
            f"{recortada.size[1]}, e sao necessarios {alvo_largura}x{alvo_altura}. "
            f"Peca ao GEM a mesma cena em 2K — ampliar aqui inventaria pixel e "
            f"seria reprovado por foco no degrau 1.")

    final = recortada.resize((alvo_largura, alvo_altura), Image.LANCZOS)
    laudo = {
        "original": list(original),
        "recorte": list(caixa),
        "recortada": list(recortada.size),
        "final": list(final.size),
        "fator": round(fator, 4),
        "ampliou": fator > 1.0,
        "descartado": round(1 - (recortada.size[0] * recortada.size[1])
                            / (original[0] * original[1]), 4),
    }
    return final, laudo


def carregar(caminho, formato):
    """Abre um arquivo de cena e o encaixa. Devolve (img, laudo)."""
    img = Image.open(caminho)
    img.load()
    ajustada, laudo = ajustar(img.convert("RGB"), formato)
    laudo["arquivo"] = str(caminho)
    return ajustada, laudo
