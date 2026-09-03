"""Extrai a paleta da logo: principal, destaque e neutra.

O GEM fazia isso como "Etapa 0 — analise a logo". Aqui vira aritmetica: a
mesma logo devolve sempre os mesmos tres hexadecimais, o que torna a peca
reprodutivel e permite comparar duas tentativas sem a paleta ser variavel.

A neutra nao e extraida — e **escolhida** entre uma clara e uma escura, pela
que tiver mais contraste com a principal. E o que o GEM pedia em palavras
("escolha o que der mais contraste") e aqui e uma conta.
"""

import numpy as np

import cor


def _pixels_de_marca(logo):
    """Os pixels que dizem algo sobre a marca: opacos, coloridos, nao extremos.

    Descarta transparente (fundo), quase-branco e quase-preto (moldura e
    contorno, presentes em qualquer logo e sem informacao de marca) e cinza.
    Se sobrar pouco, o descarte e afrouxado em vez de falhar — logo preto-e-
    branco e comum e precisa de resposta.
    """
    dados = np.asarray(logo.convert("RGBA"), dtype=np.int16).reshape(-1, 4)
    opacos = dados[dados[:, 3] > 128][:, :3]
    if len(opacos) == 0:
        return np.empty((0, 3), dtype=np.int16), True

    alto = opacos.max(axis=1).astype(np.float64)
    baixo = opacos.min(axis=1).astype(np.float64)
    saturacao = np.divide(alto - baixo, np.maximum(alto, 1e-6))
    coloridos = opacos[(saturacao > 0.18) & (alto > 28) & (baixo < 246)]

    # Menos de 0,5% de pixel colorido = logo monocromatica de fato.
    if len(coloridos) < max(24, 0.005 * len(opacos)):
        return opacos, True
    return coloridos, False


def _agrupar(pixels, delta_minimo):
    """Agrupa cores proximas em Lab e ordena por presenca ponderada por saturacao.

    A ponderacao existe porque um cinza de fundo pode ter mais pixels que o
    vermelho da marca — e e o vermelho que e a marca.
    """
    quantizado = (pixels >> 3) << 3
    unicos, contagens = np.unique(quantizado, axis=0, return_counts=True)
    labs = cor.para_lab(unicos)

    saturacoes = np.array([cor.saturacao(tuple(u)) for u in unicos])
    pesos = contagens * (0.35 + saturacoes)
    ordem = np.argsort(-pesos)

    grupos = []
    for i in ordem:
        for grupo in grupos:
            if cor.delta_e(labs[i], grupo["lab"]) < delta_minimo:
                grupo["peso"] += float(pesos[i])
                break
        else:
            grupos.append({"rgb": tuple(int(v) for v in unicos[i]),
                           "lab": labs[i], "peso": float(pesos[i])})
    grupos.sort(key=lambda g: -g["peso"])
    return grupos


def extrair(logo, cor_informada=None):
    """Devolve dict com principal/destaque/neutra em hex, mais o diagnostico.

    `cor_informada` e a cor primaria que o executivo digitou: quando vem, ela
    manda — a pessoa sabe a cor da marca melhor que a quantizacao, e discordar
    dela em silencio seria pior que qualquer erro de extracao.
    """
    pixels, monocromatica = _pixels_de_marca(logo)
    grupos = _agrupar(pixels, delta_minimo=22.0) if len(pixels) else []

    if cor_informada:
        principal = cor.de_hex(cor_informada)
        origem = "informada"
    elif grupos:
        principal = grupos[0]["rgb"]
        origem = "extraida"
    else:
        principal = (26, 79, 160)
        origem = "padrao"

    # Destaque: a cor mais presente que seja distante em matiz da principal.
    # Sem candidato (logo de uma cor so), gira o matiz — sempre ha um destaque.
    matiz_principal = cor.matiz(principal)
    destaque = None
    for grupo in grupos:
        if cor.distancia_matiz(cor.matiz(grupo["rgb"]), matiz_principal) >= 40 \
           and cor.saturacao(grupo["rgb"]) > 0.25:
            destaque = grupo["rgb"]
            break
    destaque_origem = "extraido" if destaque is not None else "derivado"
    if destaque is None:
        destaque = cor.girar_matiz(principal, 160)

    # O destaque precisa ser legivel *sobre a principal*: e a cor da segunda
    # linha da manchete e do selo do cupom.
    #
    # A direcao importa, e ate 03/09/2026 estava errada: clareava sempre. Sobre
    # marca CLARA — o verde da Aroca Mercearia — clarear APROXIMA o destaque do
    # fundo, e as oito tentativas terminavam com menos contraste do que
    # comecaram. A peca saia com "CLIENTE" quase invisivel e reprovada por
    # contraste no degrau 1. Agora anda para o lado que o fundo pede.
    passo = 26 if cor.texto_sobre(principal) == cor.BRANCO else -26
    tentativas = 0
    while cor.contraste(destaque, principal) < 3.0 and tentativas < 12:
        destaque = tuple(max(0, min(255, int(c + passo))) for c in destaque)
        tentativas += 1

    # Marca de baixo contraste em qualquer direcao (cinza medio, por exemplo)
    # existe. Ali o destaque abre mao da cor para nao abrir mao da leitura.
    if cor.contraste(destaque, principal) < 3.0:
        destaque = cor.texto_sobre(principal)
        destaque_origem = "legibilidade"

    clara, escura = cor.NEUTRA_CLARA, cor.NEUTRA_ESCURA
    neutra = clara if cor.contraste(clara, principal) >= cor.contraste(escura, principal) else escura

    return {
        "principal": cor.para_hex(principal),
        "destaque": cor.para_hex(destaque),
        "neutra": cor.para_hex(neutra),
        "diagnostico": {
            "origem_principal": origem,
            "origem_destaque": destaque_origem,
            "logo_monocromatica": bool(monocromatica),
            "grupos_encontrados": len(grupos),
            "contraste_destaque_principal": round(cor.contraste(destaque, principal), 2),
            "contraste_neutra_principal": round(cor.contraste(neutra, principal), 2),
        },
    }
