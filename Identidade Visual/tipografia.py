"""Fonte e ajuste de texto. Nada aqui pode falhar em silencio.

Texto que nao cabe e a falha classica do banner montado por script: ou vaza
por cima da arte, ou e cortado no meio da palavra. Aqui ele **sempre** cabe,
por reducao de corpo e quebra de linha, e quando nem assim couber o fato e
**reportado** para o degrau 1 reprovar a peca. Espremer letra, nunca.
"""

from pathlib import Path

from PIL import ImageFont

AQUI = Path(__file__).resolve().parent
ARQUIVO = AQUI / "fontes" / "Inter.ttf"

PESOS = ("Regular", "Medium", "SemiBold", "Bold", "Black")


def fonte(corpo, peso="Regular"):
    """Inter no corpo e peso pedidos. Levanta se a fonte sumiu do repo."""
    if not ARQUIVO.exists():
        raise FileNotFoundError(
            f"fonte ausente: {ARQUIVO}. Ela e versionada de proposito — sem ela "
            "o banner sai com metrica errada. Ver fontes/LEIA-ME.md.")
    f = ImageFont.truetype(str(ARQUIVO), corpo)
    if peso not in PESOS:
        raise ValueError(f"peso desconhecido: {peso}")
    f.set_variation_by_name(peso)
    return f


def largura(desenho, texto, f):
    caixa = desenho.textbbox((0, 0), texto, font=f)
    return caixa[2] - caixa[0]


def altura(desenho, texto, f):
    caixa = desenho.textbbox((0, 0), texto, font=f)
    return caixa[3] - caixa[1]


def quebrar(desenho, texto, f, largura_max):
    """Quebra por palavra. Palavra que sozinha nao cabe fica na linha, inteira —
    e o excesso vira `truncado` no relato, para o degrau 1 reprovar."""
    palavras = texto.split()
    linhas, atual = [], ""
    for palavra in palavras:
        tentativa = f"{atual} {palavra}".strip()
        if largura(desenho, tentativa, f) <= largura_max or not atual:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def ajustar(desenho, texto, largura_max, corpo_inicial, corpo_minimo,
            peso="Regular", linhas_max=2):
    """Encontra o maior corpo em que o texto cabe em ate `linhas_max` linhas.

    Devolve (fonte, linhas, coube). `coube=False` significa que nem no corpo
    minimo deu — a peca segue sendo montada, mas nasce reprovada.
    """
    corpo = corpo_inicial
    while corpo >= corpo_minimo:
        f = fonte(corpo, peso)
        linhas = quebrar(desenho, texto, f, largura_max)
        if len(linhas) <= linhas_max and all(
                largura(desenho, l, f) <= largura_max for l in linhas):
            return f, linhas, True
        corpo -= 2
    f = fonte(corpo_minimo, peso)
    linhas = quebrar(desenho, texto, f, largura_max)[:linhas_max]
    return f, linhas, False
