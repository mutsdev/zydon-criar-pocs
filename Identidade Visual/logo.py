"""Degrau 0: normalização da logo, e o único ponto que aborta o cliente inteiro.

Logo ruim produz banner ruim por qualquer caminho — gerado ou determinístico.
Falhar aqui, alto e cedo, é mais barato do que descobrir na frente do cliente.
Também é onde se resolve o caso mais comum na prática: o PNG "com fundo
transparente" que na verdade tem um retângulo branco chapado atrás.
"""

import numpy as np
from PIL import Image

import cor as _cor


class LogoInvalida(ValueError):
    """A logo não serve. A mensagem diz o quê, para o executivo poder trocar."""


def _alfa_de_fundo_chapado(img, tolerancia):
    """Deriva transparência de um fundo sólido, decidido pelos quatro cantos.

    Só age quando os quatro cantos concordam: se discordam, o fundo não é
    chapado e apagar por cor destruiria a arte. Preferir não agir a agir errado.
    """
    dados = np.asarray(img.convert("RGB"), dtype=np.int16)
    altura, largura = dados.shape[:2]
    cantos = np.array([dados[0, 0], dados[0, largura - 1],
                       dados[altura - 1, 0], dados[altura - 1, largura - 1]],
                      dtype=np.int16)
    if np.abs(cantos - cantos[0]).max() > tolerancia:
        return None
    distancia = np.abs(dados - cantos[0]).max(axis=2)
    return Image.fromarray(np.where(distancia > tolerancia, 255, 0).astype(np.uint8), "L")


def normalizar(caminho, limiares):
    """Abre, recorta a moldura vazia e valida. Devolve (RGBA recortada, laudo)."""
    try:
        img = Image.open(caminho)
        img.load()
    except Exception as erro:
        raise LogoInvalida(f"nao consegui abrir a logo: {erro}") from erro

    largura_original, altura_original = img.size
    if min(img.size) < limiares["lado_minimo_px"]:
        raise LogoInvalida(
            f"logo pequena demais: {largura_original}x{altura_original}, "
            f"minimo {limiares['lado_minimo_px']}px no menor lado. "
            "Peca o arquivo vetorial ou uma exportacao maior.")

    img = img.convert("RGBA")
    canal_alfa = img.getchannel("A")

    # Alfa inexistente na prática (tudo opaco) → o fundo pode ser chapado.
    fundo_removido = False
    if canal_alfa.getextrema()[0] >= 250:
        derivado = _alfa_de_fundo_chapado(img, limiares["tolerancia_fundo_chapado"])
        if derivado is not None:
            img.putalpha(derivado)
            canal_alfa = derivado
            fundo_removido = True

    caixa = canal_alfa.point(lambda v: 255 if v > 16 else 0).getbbox()
    if caixa is None:
        raise LogoInvalida("a logo ficou vazia depois de remover o fundo — "
                           "provavelmente e uma imagem de uma cor so.")
    recortada = img.crop(caixa)

    alfa = np.asarray(recortada.getchannel("A"), dtype=np.uint8)
    razao_opaca = float((alfa > 16).mean())
    if razao_opaca < limiares["razao_opaca_minima"]:
        raise LogoInvalida(
            f"quase nada de logo na imagem ({razao_opaca:.1%} de pixels opacos). "
            "O arquivo provavelmente esta corrompido ou e uma marca d'agua.")

    largura, altura = recortada.size
    aspecto = max(largura / altura, altura / largura)
    if aspecto > limiares["aspecto_maximo"]:
        raise LogoInvalida(
            f"logo desproporcional demais ({largura}x{altura}, {aspecto:.1f}:1). "
            "Acima de 6:1 ela fica ilegivel em qualquer painel.")

    laudo = {
        "arquivo": str(caminho),
        "original": [largura_original, altura_original],
        "recortada": [largura, altura],
        "aspecto": round(largura / altura, 4),
        "razao_opaca": round(razao_opaca, 4),
        "fundo_chapado_removido": fundo_removido,
    }
    return recortada, laudo


def encaixar(logo, largura_max, altura_max):
    """Escala para caber na caixa **preservando o aspecto**, e nunca ampliando.

    E o unico lugar do sistema que redimensiona a logo. Por isso a garantia de
    "logo nao esticada" e estrutural: nao existe caminho que a distorca.
    """
    largura, altura = logo.size
    fator = min(largura_max / largura, altura_max / altura, 1.0)
    novo = (max(1, int(round(largura * fator))), max(1, int(round(altura * fator))))
    return logo.resize(novo, Image.LANCZOS)


def visibilidade(logo, fundo, contraste_minimo):
    """Fracao dos pixels da logo que se destacam deste fundo.

    Uma logo com simbolo vermelho e texto branco fica legivel sobre vermelho —
    a parte branca sustenta. Por isso a conta e por pixel, e nao pela cor media,
    que diria "vermelho sobre vermelho" e jogaria fora o texto que salva a peca.
    """
    dados = np.asarray(logo.convert("RGBA"), dtype=np.uint8).reshape(-1, 4)
    opacos = dados[dados[:, 3] > 128][:, :3]
    if len(opacos) == 0:
        return 0.0
    # Amostra: 20k pixels bastam e evitam varrer logo de 4000px a cada peca.
    if len(opacos) > 20000:
        passo = len(opacos) // 20000
        opacos = opacos[::passo]
    linear = _cor.luminancia(opacos)
    fundo_lum = float(_cor.luminancia(np.asarray(fundo, dtype=np.float64)))
    claro = np.maximum(linear, fundo_lum)
    escuro = np.minimum(linear, fundo_lum)
    razoes = (claro + 0.05) / (escuro + 0.05)
    return float((razoes >= contraste_minimo).mean())


def preparar_para_fundo(logo, fundo, limiares):
    """Devolve (logo pronta, modo). Garante que a logo apareca sobre o fundo.

    Quando a marca e de cor forte, a paleta extrai essa cor como principal e o
    painel nasce da mesma cor da logo — a logo desaparece. A saida e o
    **knockout**: a silhueta da logo pintada na cor do texto do painel, que e
    exatamente a versao monocromatica que toda marca tem para fundo colorido.
    Perde-se a policromia; ganha-se existir. Legibilidade ganha da fidelidade.
    """
    visivel = visibilidade(logo, fundo, limiares["contraste_logo_minimo"])
    if visivel >= limiares["fracao_logo_visivel_minima"]:
        return logo, {"modo": "original", "fracao_visivel": round(visivel, 4)}

    tinta = _cor.texto_sobre(fundo)
    chapada = Image.new("RGBA", logo.size, tuple(list(tinta) + [0]))
    chapada.putalpha(logo.getchannel("A"))
    return chapada, {"modo": "knockout", "fracao_visivel": round(visivel, 4),
                     "tinta": _cor.para_hex(tinta)}
