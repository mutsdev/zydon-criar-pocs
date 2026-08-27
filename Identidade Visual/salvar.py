"""Grava a peca no formato e no peso certos para um portal web.

Existe separado porque peso de arquivo e **decisao de gravacao**, nao criterio
de reprovacao. A primeira versao media o peso do PNG que vinha do navegador e
reprovava a cena por isso — o que teria reprovado toda cena real, ja que imagem
arrastada do Gemini tem varios MB e isso nao diz nada sobre ela ser boa.

O arquivo de saida e nosso. Se ficou pesado, a resposta e gravar melhor.

Escolha de formato:
  peca com fotografia  -> JPEG. Foto em PNG fica 5 a 10x maior sem ganho visivel.
  peca chapada         -> PNG. JPEG poe halo em borda dura de cor solida, e o
                          minimalista e so borda dura de cor solida.
"""

import io

QUALIDADES = (90, 84, 78, 70)


def _bytes_jpeg(img, qualidade):
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=qualidade,
                            optimize=True, progressive=True)
    return buffer.getvalue()


def _bytes_png(img):
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def gravar(img, destino_sem_extensao, tem_cena, limite_kb):
    """Grava e devolve (caminho, laudo). O caminho traz a extensao escolhida.

    Desce a qualidade do JPEG ate caber no limite. Se nem na qualidade mais
    baixa couber, grava assim mesmo e **reporta** — o degrau 1 decide o que
    fazer com isso. Gravar um arquivo pesado e um problema; nao gravar nada
    seria pior.
    """
    destino_sem_extensao = str(destino_sem_extensao)

    if not tem_cena:
        dados = _bytes_png(img)
        caminho = destino_sem_extensao + ".png"
        # PNG de arte chapada e pequeno por natureza; se estourar, e porque a
        # peca tem foto e alguem chamou isto errado.
        if len(dados) / 1024 > limite_kb:
            dados = _bytes_jpeg(img, QUALIDADES[0])
            caminho = destino_sem_extensao + ".jpg"
        with open(caminho, "wb") as saida:
            saida.write(dados)
        return caminho, {"formato": caminho.rsplit(".", 1)[1], "kb": round(len(dados) / 1024, 1),
                         "qualidade": None, "coube": len(dados) / 1024 <= limite_kb}

    escolhido, usada = None, None
    for qualidade in QUALIDADES:
        dados = _bytes_jpeg(img, qualidade)
        escolhido, usada = dados, qualidade
        if len(dados) / 1024 <= limite_kb:
            break

    caminho = destino_sem_extensao + ".jpg"
    with open(caminho, "wb") as saida:
        saida.write(escolhido)
    return caminho, {"formato": "jpg", "kb": round(len(escolhido) / 1024, 1),
                     "qualidade": usada,
                     "coube": len(escolhido) / 1024 <= limite_kb}
