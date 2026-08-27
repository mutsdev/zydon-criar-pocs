"""Deriva o favicon a partir da logo do cliente.

Favicon e um quadrado de 32px na aba do navegador. Logo de portal B2B quase
sempre e um lockup largo — simbolo + palavra — e enfiar isso num quadrado
produz um borrao ilegivel. Entao aqui nao se "redimensiona a logo": escolhe-se
**o que da logo vira o icone**, em tres caminhos, do melhor para o pior:

  1. A logo ja e quase quadrada  -> usa ela inteira.
  2. Ha um simbolo destacado do texto por uma faixa vazia -> usa so o simbolo.
     E o caso do lockup classico (bolinha + nome).
  3. Nao ha simbolo separavel (logo que e so palavra) -> desenha a inicial do
     cliente na tipografia da marca.

O caminho escolhido e **reportado**, porque o 3 e um palpite e voce precisa
saber quando ele foi usado para poder discordar.
"""

import numpy as np
from PIL import Image, ImageDraw

import cor
import logo as mod_logo
import tipografia as tipo

LADO = 256  # 256 cobre todos os tamanhos que o navegador pede a partir de um PNG


def _colunas_ocupadas(logo_img):
    """Quais colunas tem pixel opaco. E o que revela o vao entre simbolo e texto."""
    alfa = np.asarray(logo_img.convert("RGBA").getchannel("A"), dtype=np.uint8)
    return (alfa > 24).sum(axis=0)


def _simbolo_a_esquerda(logo_img, folga_minima=0.04):
    """Recorta o bloco inicial da logo se houver um vao vazio depois dele.

    Procura a primeira sequencia de colunas totalmente vazias com largura
    razoavel: e o espaco entre o simbolo e o nome. Sem esse vao, nao ha simbolo
    separavel e devolve None — melhor admitir que nao achou do que cortar a
    palavra ao meio.
    """
    ocupadas = _colunas_ocupadas(logo_img)
    largura = len(ocupadas)
    minimo = max(3, int(largura * folga_minima))

    inicio_vao = None
    for x in range(largura):
        if ocupadas[x] == 0:
            if inicio_vao is None:
                inicio_vao = x
        else:
            if inicio_vao is not None and x - inicio_vao >= minimo and inicio_vao > 0:
                bloco = logo_img.crop((0, 0, inicio_vao, logo_img.size[1]))
                caixa = bloco.convert("RGBA").getchannel("A").point(
                    lambda v: 255 if v > 24 else 0).getbbox()
                if caixa is None:
                    return None
                bloco = bloco.crop(caixa)
                # So vale como simbolo se for compacto: bloco largo e outra
                # palavra, nao um icone.
                proporcao = bloco.size[0] / bloco.size[1]
                if 0.55 <= proporcao <= 1.8:
                    return bloco
                return None
            inicio_vao = None
    return None


def _fundo_do_icone(paleta, conteudo, limiares):
    """A cor de fundo do quadrado, e se o conteudo precisa virar knockout.

    Aba de navegador tem fundo claro ou escuro conforme o tema, entao icone com
    fundo transparente some em um dos dois. Sempre pinta um fundo.
    """
    neutra = cor.de_hex(paleta["neutra"])
    principal = cor.de_hex(paleta["principal"])

    if conteudo is not None:
        # Se a marca aparece bem sobre a neutra, fundo claro e mais discreto.
        visivel = mod_logo.visibilidade(conteudo, neutra,
                                        limiares["contraste_logo_minimo"])
        if visivel >= limiares["fracao_logo_visivel_minima"]:
            return neutra, False
    return principal, True


MODOS = ("auto", "inteira", "inicial")


def gerar(logo_img, paleta, nome_cliente, limiares, modo="auto"):
    """Devolve (imagem quadrada RGBA, laudo). Nunca levanta.

    `modo` escolhe a estrategia:
      auto     a heuristica dos tres caminhos descrita no topo do modulo.
      inteira  encaixa a logo toda no quadrado, sempre.
      inicial  desenha a inicial do cliente, sempre.

    Sobre `inteira`: e o que a intuicao pede ao olhar o preview do painel, que
    mostra o icone grande. Medido em 26/08/2026 com um logotipo de palavra de
    3,7:1, a logo encaixada ocupa 206x56 dentro de 256 — a 32px isso vira uma
    faixa de 26x7px, e a 16px uma mancha. A aba do navegador usa 16 e 32.
    Continua sendo a escolha certa para logo com simbolo compacto; para
    logotipo que e so palavra, nao.
    """
    if modo not in MODOS:
        raise ValueError(f"modo desconhecido: {modo}. Use um de {MODOS}.")

    largura, altura = logo_img.size
    proporcao = largura / altura

    if modo == "inteira":
        conteudo, caminho = logo_img, "logo-inteira"
    elif modo == "inicial":
        conteudo, caminho = None, "inicial"
    elif proporcao <= 1.4:
        conteudo, caminho = logo_img, "logo-inteira"
    else:
        simbolo = _simbolo_a_esquerda(logo_img)
        if simbolo is not None:
            conteudo, caminho = simbolo, "simbolo-destacado"
        else:
            conteudo, caminho = None, "inicial"

    fundo, precisa_knockout = _fundo_do_icone(paleta, conteudo, limiares)
    icone = Image.new("RGBA", (LADO, LADO), tuple(list(fundo) + [255]))

    if conteudo is None:
        # Logo que e so palavra: a inicial do cliente e o unico simbolo honesto.
        inicial = (nome_cliente.strip()[:1] or "?").upper()
        tinta = cor.texto_sobre(fundo)
        desenho = ImageDraw.Draw(icone)
        f = tipo.fonte(int(LADO * 0.62), "Bold")
        caixa = desenho.textbbox((0, 0), inicial, font=f)
        desenho.text(((LADO - (caixa[2] - caixa[0])) / 2 - caixa[0],
                      (LADO - (caixa[3] - caixa[1])) / 2 - caixa[1]),
                     inicial, font=f, fill=tinta)
        laudo = {"caminho": caminho, "inicial": inicial,
                 "fundo": cor.para_hex(fundo), "knockout": False}
    else:
        if precisa_knockout:
            conteudo, _ = mod_logo.preparar_para_fundo(conteudo, fundo, limiares)
        # Respiro para o icone nao parecer cortado — mas conteudo largo ja perde
        # altura demais no encaixe, entao a margem aperta em vez de somar perda.
        folga = 0.10 if (conteudo.size[0] / conteudo.size[1]) > 2.0 else 0.16
        margem = int(LADO * folga)
        encaixado = mod_logo.encaixar(conteudo, LADO - margem * 2, LADO - margem * 2)
        icone.paste(encaixado,
                    ((LADO - encaixado.size[0]) // 2, (LADO - encaixado.size[1]) // 2),
                    encaixado)
        laudo = {"caminho": caminho, "fundo": cor.para_hex(fundo),
                 "knockout": bool(precisa_knockout),
                 "conteudo": list(conteudo.size)}

    laudo["lado"] = LADO
    return icone, laudo
