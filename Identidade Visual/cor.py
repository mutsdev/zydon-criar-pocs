"""Matemática de cor: hex, Lab, ΔE e contraste WCAG.

Existe separado porque quatro módulos precisam das mesmas contas e elas
precisam concordar. "A cor destoa da marca" e "o texto tem contraste" são
afirmações que o sistema faz para reprovar uma peça — então têm que ser
números reprodutíveis, não impressão.
"""

import numpy as np

BRANCO = (255, 255, 255)
PRETO = (16, 20, 24)
NEUTRA_CLARA = (247, 248, 250)
NEUTRA_ESCURA = (16, 20, 24)


def para_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*(int(round(c)) for c in rgb[:3]))


def de_hex(texto):
    t = texto.strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        raise ValueError(f"hex inválido: {texto!r}")
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def _srgb_linear(canal):
    """Descompressão de gama sRGB. Vetorizada: aceita escalar ou array."""
    c = np.asarray(canal, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def para_lab(rgb):
    """sRGB (0-255) → CIE L*a*b*, D65. Aceita (3,) ou (..., 3)."""
    linear = _srgb_linear(np.asarray(rgb, dtype=np.float64))
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = linear @ m.T
    branco = np.array([0.95047, 1.00000, 1.08883])
    t = xyz / branco
    eps = 216 / 24389
    kappa = 24389 / 27
    f = np.where(t > eps, np.cbrt(t), (kappa * t + 16) / 116)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)


def delta_e(lab_a, lab_b):
    """CIE76. Basta para 'esta cor pertence à paleta?' e é barato em massa."""
    return np.sqrt(np.sum((np.asarray(lab_a) - np.asarray(lab_b)) ** 2, axis=-1))


def luminancia(rgb):
    linear = _srgb_linear(np.asarray(rgb, dtype=np.float64)[..., :3])
    return linear @ np.array([0.2126, 0.7152, 0.0722])


def contraste(rgb_a, rgb_b):
    """Razão de contraste WCAG 2.1, de 1:1 a 21:1. O piso de texto é 4,5."""
    a, b = float(luminancia(rgb_a)), float(luminancia(rgb_b))
    claro, escuro = max(a, b), min(a, b)
    return (claro + 0.05) / (escuro + 0.05)


def texto_sobre(fundo):
    """O tom de texto legível sobre este fundo — o que tiver mais contraste."""
    return BRANCO if contraste(BRANCO, fundo) >= contraste(PRETO, fundo) else PRETO


def matiz(rgb):
    """Matiz em graus (0-360). -1 quando a cor é acromática demais para ter uma."""
    r, g, b = (c / 255.0 for c in rgb[:3])
    alto, baixo = max(r, g, b), min(r, g, b)
    d = alto - baixo
    if d < 1e-6:
        return -1.0
    if alto == r:
        h = ((g - b) / d) % 6
    elif alto == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60.0


def saturacao(rgb):
    r, g, b = (c / 255.0 for c in rgb[:3])
    alto, baixo = max(r, g, b), min(r, g, b)
    return 0.0 if alto <= 1e-6 else (alto - baixo) / alto


def distancia_matiz(a, b):
    """Menor arco entre dois matizes. -1 em qualquer um significa incomparável."""
    if a < 0 or b < 0:
        return 180.0
    d = abs(a - b) % 360
    return min(d, 360 - d)


def girar_matiz(rgb, graus):
    """Roda o matiz mantendo saturação e valor — usado quando a logo é de uma
    cor só e não há segunda cor para virar destaque."""
    import colorsys
    r, g, b = (c / 255.0 for c in rgb[:3])
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + graus / 360.0) % 1.0
    s = min(1.0, max(s, 0.65))
    v = min(1.0, max(v, 0.75))
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(h, s, v))


def fundo_legivel(fundo, alvo=5.2, passos=40):
    """Ajusta o fundo — mantendo o MATIZ — ate o texto sobre ele ser legivel.

    Devolve (rgb, laudo). O matiz da marca fica; o que muda e o brilho.

    Existe porque cor de marca de brilho medio poe o texto exatamente no piso
    da WCAG. Medido em 04/09/2026 com o vermelho da Rema Tip Top (#E82028):
    branco da 4,50 e preto da 4,20 — o piso de texto pequeno e 4,5, entao
    **nenhuma das duas tintas passa**, e as dez caixas miudas do painel de
    login foram reprovadas de uma vez. Nao e caso raro: todo vermelho, laranja
    e verde-medio de marca cai nessa faixa.

    O alvo e 5,2 e nao 4,5 de proposito: parar no piso deixa a peca a um
    arredondamento de reprovar, e foi assim que ela reprovou.

    Escurecer ou clarear sai de qual lado ja esta mais longe — marca escura vai
    para o escuro, marca clara vai para o claro. Empurrar para o lado errado
    atravessaria o meio, onde nao ha contraste nenhum.
    """
    fundo = tuple(int(c) for c in fundo[:3])
    if contraste(texto_sobre(fundo), fundo) >= alvo:
        return fundo, {"ajustado": False, "razao": round(
            contraste(texto_sobre(fundo), fundo), 2)}

    # Para o lado que ja e o dele: se o texto legivel e branco, o fundo e
    # escuro, e escurecer mais e o caminho curto.
    escurecer = texto_sobre(fundo) == BRANCO
    atual = fundo
    for _ in range(passos):
        if escurecer:
            atual = tuple(max(0, int(c * 0.92)) for c in atual)
        else:
            atual = tuple(min(255, int(c + (255 - c) * 0.10) + 1) for c in atual)
        if contraste(texto_sobre(atual), atual) >= alvo:
            break
    return atual, {"ajustado": True, "de": para_hex(fundo), "para": para_hex(atual),
                   "razao": round(contraste(texto_sobre(atual), atual), 2)}


# Piso de contraste do BRANCO sobre a cor primaria do portal. A plataforma
# escreve em branco por cima dela (botao, cabecalho), entao cor clara demais
# deixa o texto ilegivel — e o portal "fica horrivel", que foi o relato de
# 04/09/2026. 3.0 e o piso WCAG de texto grande: linha principiada, e nao gosto.
CONTRASTE_MINIMO_COR_PORTAL = 3.0


def cor_de_portal(hexa, contraste_minimo=CONTRASTE_MINIMO_COR_PORTAL):
    """(hex_final, motivo) para a cor primaria do portal.

    Cor clara demais vira PRETO, e nao uma versao escurecida da marca. Escurecer
    preservando matiz seria mais bonito, mas devolveria um tom que a marca nao
    tem — e quem olha nao sabe se aquilo e a cor do cliente ou invencao nossa.
    Preto le como decisao; verde-escuro inventado le como erro.

    Medido nas 17 paletas em disco: `#F8F8F8` (jf-distribuidora) da contraste
    1.06 com o branco — e um portal branco no branco.
    """
    rgb = de_hex(hexa)
    achado = contraste(BRANCO, rgb)
    if achado >= contraste_minimo:
        return para_hex(rgb), None
    return para_hex(PRETO), (
        f"a cor {para_hex(rgb)} deixa o branco em {achado:.2f} de contraste, "
        f"abaixo de {contraste_minimo:.1f}: o portal vai de preto")
