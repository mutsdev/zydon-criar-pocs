"""Degrau 1: as checagens mecanicas. Sem rede, sem modelo, milissegundos.

Roda antes do juiz de visao de proposito — o degrau seguinte custa cota, e nao
faz sentido pedir opiniao sobre uma imagem que ja falhou na regua. Tudo aqui e
numero reprodutivel: a mesma imagem sempre da o mesmo veredito.

Duas superficies: `checar_cena` (o que veio de fora, e pode ser qualquer coisa)
e `checar_peca` (o que o Pillow montou, onde o erro possivel e de layout).
"""

import numpy as np
from PIL import Image, ImageFilter

import cor


def _falha(checagem, detalhe, valor=None, limite=None):
    return {"checagem": checagem, "detalhe": detalhe, "valor": valor, "limite": limite}


def _luminancia_8bits(img):
    return np.asarray(img.convert("L"), dtype=np.float64)


def _blocos(matriz, lado):
    """Fatia em blocos lado x lado e devolve o desvio padrao de cada um.

    Usado para 'respiro' e 'costura': ambos perguntam onde a imagem e calma e
    onde e agitada, e nenhum dos dois se responde com estatistica global.
    """
    altura, largura = matriz.shape
    linhas, colunas = altura // lado, largura // lado
    if linhas == 0 or colunas == 0:
        return np.zeros((0,))
    corte = matriz[:linhas * lado, :colunas * lado]
    janelas = corte.reshape(linhas, lado, colunas, lado).transpose(0, 2, 1, 3)
    return janelas.reshape(linhas, colunas, -1).std(axis=2)


def checar_cena(img, paleta, formato, limiares, tamanho_kb=None):
    """As checagens sobre a cena crua. Devolve lista de falhas (vazia = passou).

    `tamanho_kb` e aceito e ignorado: ver o comentario sobre peso abaixo.
    """
    falhas = []
    esperado = formato.cena

    if img.size != esperado:
        falhas.append(_falha("dimensao", f"cena {img.size}, esperado {esperado}",
                             list(img.size), list(esperado)))
        return falhas  # sem a dimensao certa, o resto mede outra coisa

    # O peso do arquivo de ENTRADA nao reprova nada, de proposito. PNG arrastado
    # do navegador tem varios MB e isso nao diz se a cena presta; o peso que
    # importa e o da peca de saida, que e nossa e se resolve gravando melhor
    # (ver salvar.py). Imagem degenerada ja e pega por `degeneracao`, em pixel.

    lum = _luminancia_8bits(img)
    desvio = float(lum.std())
    if desvio < limiares["desvio_luminancia_minimo"]:
        falhas.append(_falha("degeneracao", "imagem chapada, sem variacao de luz",
                             round(desvio, 2), limiares["desvio_luminancia_minimo"]))

    # Barras e molduras: bordas quase uniformes sao o artefato classico de
    # geracao fora de proporcao, e denunciam que alguem esticou ou preencheu.
    for nome, faixa in (("topo", lum[:max(1, int(lum.shape[0] * .04))]),
                        ("base", lum[-max(1, int(lum.shape[0] * .04)):]),
                        ("esquerda", lum[:, :max(1, int(lum.shape[1] * .04))]),
                        ("direita", lum[:, -max(1, int(lum.shape[1] * .04)):])):
        media = float(faixa.mean())
        if float(faixa.std()) < 2.0 and (media < 20 or media > 235):
            falhas.append(_falha("barra", f"borda {nome} uniforme e chapada — "
                                 f"barra ou moldura", round(float(faixa.std()), 2), 2.0))

    energia = float(np.asarray(img.convert("L").filter(ImageFilter.FIND_EDGES),
                               dtype=np.float64).mean())
    if energia < limiares["energia_borda_minima"]:
        falhas.append(_falha("foco", "pouca definicao — imagem borrada",
                             round(energia, 2), limiares["energia_borda_minima"]))

    # Banda de cor: e o "nada de azul generico" do GEM, virado numero.
    amostra = np.asarray(img.convert("RGB").resize((160, 160), Image.BILINEAR),
                         dtype=np.float64).reshape(-1, 3)
    labs_amostra = cor.para_lab(amostra)
    hexes = [paleta["principal"], paleta["destaque"], paleta["neutra"]]
    labs_paleta = np.stack([cor.para_lab(cor.de_hex(h)) for h in hexes])
    distancias = np.stack([cor.delta_e(labs_amostra, lab) for lab in labs_paleta])
    cobertura = float((distancias.min(axis=0) <= limiares["delta_e_paleta"]).mean())
    if cobertura < limiares["cobertura_paleta_minima"]:
        falhas.append(_falha("banda_de_cor", "cena pouco alinhada a paleta da marca",
                             round(cobertura, 3), limiares["cobertura_paleta_minima"]))

    # Matiz intruso: uma cor forte que nao e da marca e dominante na cena.
    matizes_paleta = [cor.matiz(cor.de_hex(h)) for h in (paleta["principal"],
                                                         paleta["destaque"])]
    alto = amostra.max(axis=1)
    baixo = amostra.min(axis=1)
    saturados = amostra[(alto - baixo) / np.maximum(alto, 1e-6) > 0.30]
    if len(saturados) > 0:
        graus = np.array([cor.matiz(tuple(p)) for p in saturados])
        distancia_min = np.full(len(graus), 180.0)
        for mp in matizes_paleta:
            d = np.abs(graus - mp) % 360
            distancia_min = np.minimum(distancia_min, np.minimum(d, 360 - d))
        intrusos = float((distancia_min > 50).mean() * (len(saturados) / len(amostra)))
        if intrusos > limiares["matiz_intruso_maximo"]:
            falhas.append(_falha("matiz_intruso",
                                 "cor forte fora da paleta domina a cena",
                                 round(intrusos, 3), limiares["matiz_intruso_maximo"]))

    # Respiro: alguma regiao calma onde o olho descansa. Sem isso a peca fica
    # entulhada, que e o defeito mais comum de cena gerada.
    desvios = _blocos(lum, 48)
    if desvios.size:
        respiro = float((desvios < limiares["variancia_respiro"]).mean())
        if respiro < limiares["respiro_minimo"]:
            falhas.append(_falha("respiro", "composicao entulhada, sem espaco negativo",
                                 round(respiro, 3), limiares["respiro_minimo"]))

    # Costura: a coluna que encosta no painel nao pode ter objeto cortado ao meio.
    if formato.painel > 0:
        faixa = lum[:, :60]
        agitacao = float(faixa.std())
        if agitacao > limiares["costura_variancia_maxima"]:
            falhas.append(_falha("costura",
                                 "detalhe demais na borda que encosta no painel",
                                 round(agitacao, 2), limiares["costura_variancia_maxima"]))

    return falhas


def checar_peca(img, relato, formato, limiares, kb_gravado=None):
    """As checagens sobre a peca montada. Falha aqui e bug de layout, nao de arte.

    `kb_gravado` e o peso do arquivo que foi realmente escrito. So reprova se
    nem na qualidade mais baixa a peca coube — o que e problema de verdade para
    um portal.
    """
    falhas = []

    if kb_gravado is not None and kb_gravado > limiares["peso_maximo_kb"]:
        falhas.append(_falha("peso", "peca pesada demais mesmo apos comprimir",
                             round(kb_gravado, 1), limiares["peso_maximo_kb"]))

    if img.size != (formato.largura, formato.altura):
        falhas.append(_falha("dimensao", f"peca {img.size}, exigido "
                             f"{(formato.largura, formato.altura)}",
                             list(img.size), [formato.largura, formato.altura]))

    logo = relato.get("logo")
    if logo:
        x0, y0, x1, y1 = logo["caixa"]
        largura, altura = x1 - x0, y1 - y0
        # Aspecto se mede em pixel de arredondamento: uma logo de 74px de altura
        # nao consegue aspecto melhor que ~0,7% por construcao, e cobrar
        # porcentagem reprovaria logo pequena que esta perfeita.
        desvio_px = abs(largura - altura * logo["aspecto_original"])
        # A folga cresce com o ASPECTO, e nao e um numero fixo. Arredondar a
        # altura para inteiro move a largura em ate `aspecto/2` px: uma marca de
        # 5,4:1 nao consegue ficar abaixo de ~2,7px por construcao, e cobrar
        # 1,0px dela reprova uma logo que esta perfeita. Foi o que aconteceu com
        # o cabecalho da Rema Tip Top (376x70) em 04/09/2026 — a peca inteira
        # caiu no fallback por um arredondamento inevitavel.
        folga = max(limiares["folga_arredondamento_logo_px"],
                    logo["aspecto_original"] / 2 + 0.5)
        if desvio_px > folga:
            falhas.append(_falha("logo_esticada",
                                 "a logo foi distorcida ao ser encaixada",
                                 round(desvio_px, 3), round(folga, 3)))
        if x0 < 0 or y0 < 0 or x1 > formato.largura or y1 > formato.altura:
            falhas.append(_falha("logo_fora", "a logo saiu da area da peca",
                                 logo["caixa"], None))
        if relato.get("tem_cena") and x1 > formato.painel:
            falhas.append(_falha("logo_invade_cena",
                                 "a logo passou por cima da cena", x1, formato.painel))

    painel = relato.get("painel") or {}
    fundo = cor.de_hex(painel["fundo"]) if painel.get("fundo") else None

    # So ha "cena a invadir" quando a peca tem cena. O fallback ocupa a largura
    # inteira por desenho, e cobrar dele o limite do painel reprovaria a peca
    # que existe justamente para nunca reprovar.
    limite_painel = formato.painel if relato.get("tem_cena") else formato.largura

    for caixa in relato.get("caixas", []):
        if not caixa.get("coube", True):
            falhas.append(_falha("texto_truncado",
                                 f"'{caixa['tipo']}' nao coube nem no corpo minimo",
                                 caixa.get("corpo"), None))
        x0, y0, x1, y1 = caixa["caixa"]
        if y1 > formato.altura or x0 < 0 or y0 < 0:
            falhas.append(_falha("texto_fora",
                                 f"'{caixa['tipo']}' vazou da peca", caixa["caixa"], None))
        if x1 > limite_painel + 1:
            falhas.append(_falha("texto_invade_cena",
                                 f"'{caixa['tipo']}' passou por cima da cena",
                                 x1, limite_painel))

        # Contraste: valida a escolha automatica do neutro e do destaque, que e
        # onde a paleta erra quando a marca tem cor clara.
        atras = cor.de_hex(caixa["fundo"]) if caixa.get("fundo") else fundo
        if atras is not None and caixa.get("tinta"):
            razao = cor.contraste(cor.de_hex(caixa["tinta"]), atras)
            # Texto grande tem piso 3:1 na WCAG; corrido, 4,5:1.
            grande = (caixa.get("corpo") or 0) >= limiares["corpo_considerado_grande"]
            piso = (limiares["contraste_wcag_minimo_grande"] if grande
                    else limiares["contraste_wcag_minimo"])
            if razao < piso:
                falhas.append(_falha("contraste",
                                     f"'{caixa['tipo']}' com contraste abaixo do legivel",
                                     round(razao, 2), piso))

    return falhas


def resumir(falhas):
    """Uma linha para a folha de contato e para o log. Vazio = aprovado."""
    if not falhas:
        return "passou"
    return "; ".join(f"{f['checagem']}: {f['detalhe']}" for f in falhas)
