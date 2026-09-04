"""Monta a peca final: painel do Pillow + cena, com borda reta entre os dois.

O layout e o do GEM, mas a responsabilidade e partida. O painel e escrito com
fonte de verdade e a logo em PNG real; a cena e so fotografia. Nenhum pixel de
texto vem de modelo generativo — e por isso que "texto embolado" deixa de ser
um risco a validar e passa a ser impossivel.

Toda peca devolve um **relato**: as caixas de texto, a caixa da logo e se algo
truncou. O degrau 1 valida em cima do relato, e nao por adivinhacao sobre a
imagem pronta.
"""

from PIL import Image, ImageDraw

import cor
import formatos
import logo as mod_logo
import tipografia as tipo


def _icone(desenho, caixa, tinta, tipo_icone):
    """Glifos geometricos. Sao formas, nao fonte de icone: dependencia a menos,
    e nenhuma chance de o glifo faltar e virar retangulo vazio.

    As chaves em CAIXA ALTA sao as do layout antigo, ainda usadas pelo
    `fallback.py`. As minusculas sao as de `formatos.RECURSOS` e
    `formatos.SELOS_RODAPE`. Chave desconhecida cai num quadrado — visivel, e
    nao invisivel, porque glifo faltando tem que aparecer na revisao.
    """
    x0, y0, x1, y1 = caixa
    largura, altura = x1 - x0, y1 - y0
    traco = max(2, int(altura * 0.09))

    if tipo_icone in ("pedido", "PEDIDOS"):
        # Prancheta: retangulo com pauta e uma presilha no topo.
        desenho.rounded_rectangle([x0 + largura * .18, y0 + altura * .08,
                                   x1 - largura * .18, y1],
                                  radius=traco * 2, outline=tinta, width=traco)
        desenho.rounded_rectangle([x0 + largura * .36, y0, x1 - largura * .36,
                                   y0 + altura * .16],
                                  radius=traco, fill=tinta)
        for i in range(3):
            y = y0 + altura * (0.40 + i * 0.18)
            desenho.line([x0 + largura * .32, y, x1 - largura * .32, y],
                         fill=tinta, width=max(1, traco - 1))

    elif tipo_icone == "estoque":
        # Barras de nivel sobre uma base: estoque e quantidade, nao caixa.
        for i, fracao in enumerate((0.45, 0.72, 1.0)):
            cx = x0 + largura * (0.14 + i * 0.30)
            desenho.rectangle([cx, y1 - altura * .12 - (altura * .76) * fracao,
                               cx + largura * .18, y1 - altura * .12], fill=tinta)
        desenho.line([x0, y1 - altura * .06, x1, y1 - altura * .06],
                     fill=tinta, width=traco)

    elif tipo_icone == "nota":
        # Documento com o canto dobrado.
        dobra = largura * .28
        desenho.polygon([(x0 + largura * .16, y0), (x1 - largura * .16 - dobra, y0),
                         (x1 - largura * .16, y0 + dobra), (x1 - largura * .16, y1),
                         (x0 + largura * .16, y1)], outline=tinta, width=traco)
        for i in range(3):
            y = y0 + altura * (0.48 + i * 0.16)
            desenho.line([x0 + largura * .30, y, x1 - largura * .30, y],
                         fill=tinta, width=max(1, traco - 1))

    elif tipo_icone == "boleto":
        # Codigo de barras: e o que o cliente reconhece de longe num boleto.
        larguras = (0.06, 0.03, 0.09, 0.04, 0.06, 0.03, 0.08)
        x = x0 + largura * .12
        for i, fatia in enumerate(larguras):
            passo = largura * fatia
            if i % 2 == 0:
                desenho.rectangle([x, y0 + altura * .12, x + passo, y1 - altura * .12],
                                  fill=tinta)
            x += passo * 1.5

    elif tipo_icone == "escudo":
        meio = x0 + largura / 2
        desenho.polygon([(meio, y0), (x1 - largura * .12, y0 + altura * .20),
                         (x1 - largura * .12, y0 + altura * .58),
                         (meio, y1), (x0 + largura * .12, y0 + altura * .58),
                         (x0 + largura * .12, y0 + altura * .20)],
                        outline=tinta, width=traco)

    elif tipo_icone == "entrega":
        # Caminhao: bau, cabine e duas rodas.
        desenho.rectangle([x0 + largura * .04, y0 + altura * .24,
                           x0 + largura * .56, y1 - altura * .26],
                          outline=tinta, width=traco)
        desenho.polygon([(x0 + largura * .60, y0 + altura * .44),
                         (x0 + largura * .82, y0 + altura * .44),
                         (x1 - largura * .04, y0 + altura * .66),
                         (x1 - largura * .04, y1 - altura * .26),
                         (x0 + largura * .60, y1 - altura * .26)],
                        outline=tinta, width=traco)
        raio = altura * .13
        for cx in (x0 + largura * .24, x1 - largura * .22):
            desenho.ellipse([cx - raio, y1 - raio * 2, cx + raio, y1],
                            outline=tinta, width=traco)

    elif tipo_icone in ("atendimento", "FINANCEIRO"):
        # Headset: arco por cima e uma concha de cada lado.
        desenho.arc([x0 + largura * .10, y0 + altura * .06,
                     x1 - largura * .10, y0 + altura * .96],
                    start=180, end=360, fill=tinta, width=traco)
        for cx in (x0 + largura * .10, x1 - largura * .10 - largura * .18):
            desenho.rounded_rectangle([cx, y0 + altura * .48,
                                       cx + largura * .18, y1 - altura * .10],
                                      radius=traco * 2, fill=tinta)

    else:  # CATALOGO e qualquer chave nova ainda sem glifo
        for coluna in range(2):
            for linha in range(2):
                cx = x0 + largura * (0.12 + coluna * 0.46)
                cy = y0 + altura * (0.12 + linha * 0.46)
                desenho.rounded_rectangle([cx, cy, cx + largura * .30, cy + altura * .30],
                                          radius=traco, outline=tinta, width=traco)


def _selo_cupom(desenho, x, y, paleta, relato):
    """A etiqueta do cupom: e o unico elemento de destaque do cabecalho."""
    destaque = cor.de_hex(paleta["destaque"])
    tinta = cor.texto_sobre(destaque)
    f_codigo = tipo.fonte(26, "Bold")
    f_texto = tipo.fonte(19, "Medium")
    codigo, promessa = formatos.CUPOM
    largura = max(tipo.largura(desenho, codigo, f_codigo),
                  tipo.largura(desenho, promessa, f_texto)) + 44
    altura = 84
    desenho.rounded_rectangle([x, y, x + largura, y + altura], radius=12, fill=destaque)
    desenho.text((x + 22, y + 14), codigo, font=f_codigo, fill=tinta)
    desenho.text((x + 22, y + 50), promessa, font=f_texto, fill=tinta)
    relato["caixas"].append({"tipo": "cupom", "caixa": [x, y, x + largura, y + altura],
                             "fundo": paleta["destaque"], "tinta": cor.para_hex(tinta),
                             "coube": True})
    return largura


def _colar_logo(peca, logo_img, x, y, largura_max, altura_max, relato,
                fundo=None, limiares=None):
    # Sobre painel colorido a logo pode sumir — ver logo.preparar_para_fundo.
    if fundo is not None and limiares is not None:
        logo_img, modo = mod_logo.preparar_para_fundo(logo_img, fundo, limiares)
        relato["logo_modo"] = modo
    encaixada = mod_logo.encaixar(logo_img, largura_max, altura_max)
    peca.paste(encaixada, (int(x), int(y)), encaixada)
    original = logo_img.size[0] / logo_img.size[1]
    final = encaixada.size[0] / encaixada.size[1]
    relato["logo"] = {
        "caixa": [int(x), int(y), int(x) + encaixada.size[0], int(y) + encaixada.size[1]],
        "aspecto_original": round(original, 5),
        "aspecto_final": round(final, 5),
        "desvio_aspecto": round(abs(final - original) / original, 6),
    }


def _bloco(desenho, texto, x, y, largura_max, corpo, corpo_min, peso, tinta,
           relato, marca, linhas_max=2, entrelinha=1.16):
    f, linhas, coube = tipo.ajustar(desenho, texto, largura_max, corpo, corpo_min,
                                    peso=peso, linhas_max=linhas_max)
    passo = int(f.size * entrelinha)
    for i, linha in enumerate(linhas):
        desenho.text((x, y + i * passo), linha, font=f, fill=tinta)
    altura_total = passo * len(linhas)
    relato["caixas"].append({
        "tipo": marca, "caixa": [x, y, x + largura_max, y + altura_total],
        "tinta": cor.para_hex(tinta), "corpo": f.size, "coube": coube,
        "linhas": len(linhas)})
    return y + altura_total


def _item_com_icone(desenho, chave, titulo, apoio, x, y, largura_max, lado,
                    corpo_titulo, corpo_apoio, tinta, destaque, relato, marca):
    """Uma linha 'icone + titulo + apoio'. Devolve o y logo abaixo dela.

    E a unidade que se repete nos quatro recursos e nos tres selos — a mesma
    funcao nos dois lugares para que eles nao possam divergir de layout.
    """
    _icone(desenho, [x, y, x + lado, y + lado], destaque, chave)
    recuo = x + lado + int(lado * 0.46)
    largura_texto = largura_max - (recuo - x)

    f, linhas, coube = tipo.ajustar(desenho, titulo, largura_texto, corpo_titulo,
                                    max(13, int(corpo_titulo * 0.62)),
                                    peso="Bold", linhas_max=1)
    desenho.text((recuo, y), linhas[0], font=f, fill=tinta)
    relato["caixas"].append({
        "tipo": f"{marca}_titulo", "caixa": [recuo, y, recuo + largura_texto,
                                             y + int(f.size * 1.2)],
        "tinta": cor.para_hex(tinta), "corpo": f.size, "coube": coube})

    y_apoio = y + int(f.size * 1.34)
    fa, linhas_a, coube_a = tipo.ajustar(desenho, apoio, largura_texto, corpo_apoio,
                                         max(12, int(corpo_apoio * 0.65)),
                                         peso="Regular", linhas_max=1)
    desenho.text((recuo, y_apoio), linhas_a[0], font=fa, fill=tinta)
    relato["caixas"].append({
        "tipo": f"{marca}_apoio", "caixa": [recuo, y_apoio, recuo + largura_texto,
                                            y_apoio + int(fa.size * 1.2)],
        "tinta": cor.para_hex(tinta), "corpo": fa.size, "coube": coube_a})

    return max(y + lado, y_apoio + int(fa.size * 1.2))


def painel_login(peca, formato, paleta, logo_img, relato, limiares=None):
    """O painel da tela de login, no padrao dos portais Zydon no ar.

    Levantado de cinco portais em 03/09/2026: logo, manchete "PORTAL DO
    CLIENTE" em caixa alta, quatro recursos com icone e uma faixa de selos na
    base. Ver o comentario em `formatos.MANCHETE`.

    **Todas as posicoes sao fracoes da altura da peca, e nenhuma e pixel fixo.**
    O layout anterior tinha 72, 118, 400, 138 codificados para uma peca de 1440
    de altura; quando ela virou 1800 o painel ficou empilhado no topo com um
    terco vazio embaixo. Em fracao, mudar a dimensao em `formatos.py` nao pede
    nenhuma outra edicao.
    """
    desenho = ImageDraw.Draw(peca)
    # O painel usa a cor da marca AJUSTADA para o texto caber na regua — ver
    # `cor.fundo_legivel`. O matiz fica; so o brilho muda, e so quando precisa.
    # Sem isso, marca de brilho medio poe as dez caixas miudas deste painel
    # exatamente no piso da WCAG e reprova a peca inteira de uma vez.
    fundo, laudo_fundo = cor.fundo_legivel(cor.de_hex(paleta["principal"]))
    destaque = cor.de_hex(paleta["destaque"])
    tinta = cor.texto_sobre(fundo)
    desenho.rectangle([0, 0, formato.painel, formato.altura], fill=fundo)
    relato["painel"] = {"fundo": cor.para_hex(fundo), "tinta": cor.para_hex(tinta),
                        "largura": formato.painel, "ajuste": laudo_fundo}

    altura = formato.altura
    margem = int(formato.painel * 0.085)
    util = formato.painel - margem * 2

    def h(fracao):
        return int(altura * fracao)

    _colar_logo(peca, logo_img, margem, h(0.052), util, h(0.098), relato,
                fundo, limiares)

    # Manchete: duas linhas em caixa alta, corpo grande. A segunda vai no
    # destaque — e a unica cor de marca em texto, e por ser corpo grande o piso
    # de contraste da WCAG e 3:1, que quase toda paleta cumpre.
    corpo_manchete, minimo_manchete = h(0.053), h(0.031)
    y = h(0.212)
    linha1, linha2 = formatos.MANCHETE
    y = _bloco(desenho, linha1, margem, y, util, corpo_manchete, minimo_manchete,
               "Black", tinta, relato, "titulo_1", linhas_max=1, entrelinha=1.06)
    y = _bloco(desenho, linha2, margem, y, util, corpo_manchete, minimo_manchete,
               "Black", destaque, relato, "titulo_2", linhas_max=1, entrelinha=1.06)
    y = _bloco(desenho, formatos.SUBTITULO, margem, y + h(0.022), util,
               h(0.0165), h(0.0115), "Regular", tinta, relato, "subtitulo",
               linhas_max=3, entrelinha=1.42)

    # Os quatro recursos. O passo sai do espaco que sobra entre o subtitulo e a
    # faixa de selos, dividido igualmente — assim o bloco respira quando o
    # subtitulo quebra em duas linhas em vez de tres.
    faixa = altura - h(0.245)
    topo = y + h(0.038)
    lado = h(0.036)
    passo = max(lado + h(0.014), (faixa - h(0.030) - topo) // len(formatos.RECURSOS))
    for i, (chave, titulo, apoio) in enumerate(formatos.RECURSOS):
        _item_com_icone(desenho, chave, titulo, apoio, margem, topo + i * passo,
                        util, lado, h(0.0165), h(0.0122), tinta, destaque,
                        relato, f"recurso_{i + 1}")

    # Faixa de selos, ancorada na base: e o unico bloco que nao acompanha o
    # texto acima, porque a ancora dele e a borda de baixo da peca.
    desenho.line([margem, faixa, margem + util, faixa], fill=destaque, width=3)
    lado_selo = h(0.028)
    passo_selo = h(0.061)
    for i, (chave, titulo, apoio) in enumerate(formatos.SELOS_RODAPE):
        _item_com_icone(desenho, chave, titulo, apoio, margem,
                        faixa + h(0.028) + i * passo_selo, util, lado_selo,
                        h(0.0125), h(0.0105), tinta, destaque, relato,
                        f"selo_{i + 1}")


def painel_cabecalho(peca, formato, paleta, logo_img, relato, limiares=None):
    desenho = ImageDraw.Draw(peca)
    # Mesmo ajuste do login: o cabecalho tem menos texto, mas a frase e miuda e
    # cai na mesma regua. Duas pecas da mesma leva com fundos diferentes seriam
    # pior que qualquer uma das duas.
    fundo, laudo_fundo = cor.fundo_legivel(cor.de_hex(paleta["principal"]))
    tinta = cor.texto_sobre(fundo)
    desenho.rectangle([0, 0, formato.painel, formato.altura], fill=fundo)
    relato["painel"] = {"fundo": cor.para_hex(fundo), "tinta": cor.para_hex(tinta),
                        "largura": formato.painel, "ajuste": laudo_fundo}

    margem = 48
    _colar_logo(peca, logo_img, margem, 46, 260, 74, relato, fundo, limiares)
    _bloco(desenho, formatos.FRASE_CABECALHO, margem, 152, 292, 25, 17, "Medium",
           tinta, relato, "frase", linhas_max=3, entrelinha=1.35)
    _selo_cupom(desenho, margem + 330, 112, paleta, relato)


def montar(formato, paleta, logo_img, cena=None, limiares=None):
    """Peca final + relato. `cena` ja vem no tamanho exato de `formato.cena`."""
    peca = Image.new("RGB", (formato.largura, formato.altura),
                     cor.de_hex(paleta["neutra"]))
    relato = {"formato": formato.chave, "caixas": [], "logo": None, "painel": None,
              "tem_cena": cena is not None}

    if cena is not None:
        if cena.size != formato.cena:
            raise ValueError(
                f"cena {cena.size} != esperado {formato.cena} para {formato.chave}")
        peca.paste(cena.convert("RGB"), (formato.painel, 0))

    if formato.chave == "login":
        painel_login(peca, formato, paleta, logo_img, relato, limiares)
    elif formato.chave == "cabecalho":
        painel_cabecalho(peca, formato, paleta, logo_img, relato, limiares)
    else:
        raise ValueError(f"montar() nao cobre {formato.chave} — use fallback.py")
    return peca, relato
