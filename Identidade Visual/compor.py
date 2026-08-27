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
    """Tres glifos geometricos. Sao formas, nao fonte de icone: dependencia a
    menos, e nenhuma chance de o glifo faltar e virar retangulo vazio."""
    x0, y0, x1, y1 = caixa
    largura, altura = x1 - x0, y1 - y0
    traco = max(2, int(altura * 0.09))
    if tipo_icone == "PEDIDOS":
        desenho.rounded_rectangle([x0 + largura * .18, y0, x1 - largura * .18, y1],
                                  radius=traco * 2, outline=tinta, width=traco)
        for i in range(3):
            y = y0 + altura * (0.32 + i * 0.18)
            desenho.line([x0 + largura * .34, y, x1 - largura * .34, y],
                         fill=tinta, width=max(1, traco - 1))
    elif tipo_icone == "FINANCEIRO":
        desenho.ellipse([x0 + largura * .08, y0 + altura * .08,
                         x1 - largura * .08, y1 - altura * .08],
                        outline=tinta, width=traco)
        desenho.line([x0 + largura * .5, y0 + altura * .24,
                      x0 + largura * .5, y1 - altura * .24], fill=tinta, width=traco)
    else:  # CATALOGO
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


def painel_login(peca, formato, paleta, logo_img, relato, limiares=None):
    desenho = ImageDraw.Draw(peca)
    fundo = cor.de_hex(paleta["principal"])
    destaque = cor.de_hex(paleta["destaque"])
    tinta = cor.texto_sobre(fundo)
    desenho.rectangle([0, 0, formato.painel, formato.altura], fill=fundo)
    relato["painel"] = {"fundo": paleta["principal"], "tinta": cor.para_hex(tinta),
                        "largura": formato.painel}

    margem = 72
    util = formato.painel - margem * 2
    _colar_logo(peca, logo_img, margem, 118, util, 168, relato, fundo, limiares)

    y = 400
    linha1, linha2 = formatos.TITULO
    y = _bloco(desenho, linha1, margem, y, util, 66, 40, "Bold", tinta, relato,
               "titulo_1", linhas_max=1)
    y = _bloco(desenho, linha2, margem, y + 4, util, 66, 40, "Bold", destaque, relato,
               "titulo_2", linhas_max=1)
    y = _bloco(desenho, formatos.SUBTITULO, margem, y + 34, util, 27, 19, "Regular",
               tinta, relato, "subtitulo", linhas_max=3, entrelinha=1.42)

    # Fileira de atalhos: tres colunas iguais dentro da area util.
    topo = y + 86
    coluna = util / 3
    for i, rotulo in enumerate(formatos.ATALHOS):
        centro = margem + coluna * i + coluna / 2
        _icone(desenho, [centro - 30, topo, centro + 30, topo + 60], destaque, rotulo)
        f = tipo.fonte(17, "SemiBold")
        largura_rotulo = tipo.largura(desenho, rotulo, f)
        desenho.text((centro - largura_rotulo / 2, topo + 78), rotulo, font=f, fill=tinta)
    relato["caixas"].append({"tipo": "atalhos",
                             "caixa": [margem, topo, margem + util, topo + 104],
                             "tinta": cor.para_hex(tinta), "coube": True})

    # Faixa de selos, ancorada na base.
    faixa = formato.altura - 138
    desenho.line([margem, faixa, margem + util, faixa], fill=destaque, width=2)
    f = tipo.fonte(17, "Regular")
    for i, selo in enumerate(formatos.SELOS):
        linha = tipo.quebrar(desenho, selo, f, util)[0]
        desenho.text((margem, faixa + 28 + i * 42), linha, font=f, fill=tinta)
    relato["caixas"].append({"tipo": "selos",
                             "caixa": [margem, faixa, margem + util, formato.altura - 30],
                             "tinta": cor.para_hex(tinta), "coube": True})


def painel_cabecalho(peca, formato, paleta, logo_img, relato, limiares=None):
    desenho = ImageDraw.Draw(peca)
    fundo = cor.de_hex(paleta["principal"])
    tinta = cor.texto_sobre(fundo)
    desenho.rectangle([0, 0, formato.painel, formato.altura], fill=fundo)
    relato["painel"] = {"fundo": paleta["principal"], "tinta": cor.para_hex(tinta),
                        "largura": formato.painel}

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
