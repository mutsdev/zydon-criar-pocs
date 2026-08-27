"""A peca que sempre sai, e sempre sai apresentavel.

E o Item 3 do GEM — fundo chapado, uma forma derivada do simbolo da logo, muito
espaco negativo — generalizado para os tres formatos. Vira a saida quando nao ha
cena, quando a cena reprova, ou quando o gerador some.

Por que nunca fica feio: nao ha nada aqui que possa dar errado. Cor solida,
geometria, uma logo real e tipografia com metrica conhecida. E o mesmo motivo
pelo qual slide corporativo minimalista nunca parece amador — ele nao tenta.

Este modulo nao chama rede, nao le modelo e nao tem aleatoriedade: a mesma
entrada devolve o mesmo arquivo, byte a byte.
"""

from PIL import Image, ImageDraw, ImageFilter

import cor
import formatos
import logo as mod_logo
import tipografia as tipo


def _marca_dagua(peca, formato, logo_img, tinta_forma):
    """A silhueta da logo, ampliada e sangrando pela borda direita.

    Usa o **alfa** da logo, nao os pixels: vira forma pura, na cor da peca, sem
    reintroduzir a marca colorida por cima do fundo colorido. E o "elemento
    grafico conceitual derivado do simbolo da logo" que o GEM pedia.
    """
    alfa = logo_img.getchannel("A")
    largura, altura = alfa.size

    # Escala pela ALTURA da peca para a silhueta sangrar, e nunca flutuar
    # solta no meio — flutuar e o que faz parecer logo colada.
    fator = (formato.altura * 1.55) / altura
    novo = (max(1, int(largura * fator)), max(1, int(altura * fator)))
    silhueta = alfa.resize(novo, Image.LANCZOS)

    # Suaviza a borda: silhueta ampliada tem serrilha, e serrilha denuncia script.
    silhueta = silhueta.filter(ImageFilter.GaussianBlur(radius=max(1, novo[1] // 220)))

    forma = Image.new("RGBA", peca.size, (0, 0, 0, 0))
    camada = Image.new("RGBA", novo, tuple(list(tinta_forma) + [255]))
    forma.paste(camada, (int(formato.largura - novo[0] * 0.62),
                         int(-novo[1] * 0.24)), silhueta)

    # Opacidade baixa: e textura de fundo, nao um segundo logotipo na peca.
    forma.putalpha(forma.getchannel("A").point(lambda v: int(v * 0.16)))
    peca.alpha_composite(forma)


def _tinta_da_forma(fundo_rgb):
    """A forma tem que aparecer sem competir: branco sobre fundo escuro, preto
    sobre fundo claro — o mesmo criterio do texto, com opacidade menor."""
    return cor.texto_sobre(fundo_rgb)[:3]


def _registrar_logo(relato, encaixada, logo_img, x, y):
    relato["logo"] = {
        "caixa": [int(x), int(y), int(x) + encaixada.size[0], int(y) + encaixada.size[1]],
        "aspecto_original": round(logo_img.size[0] / logo_img.size[1], 5),
        "aspecto_final": round(encaixada.size[0] / encaixada.size[1], 5),
        "desvio_aspecto": round(
            abs(encaixada.size[0] / encaixada.size[1]
                - logo_img.size[0] / logo_img.size[1])
            / (logo_img.size[0] / logo_img.size[1]), 6),
    }


def montar(formato, paleta, logo_img, nome_cliente="", limiares=None):
    """Devolve (peca RGB, relato) no formato pedido. Nunca levanta por conteudo."""
    fundo = cor.de_hex(paleta["principal"])
    destaque = cor.de_hex(paleta["destaque"])
    tinta = cor.texto_sobre(fundo)

    relato = {"formato": formato.chave, "caixas": [], "logo": None,
              "painel": {"fundo": paleta["principal"], "tinta": cor.para_hex(tinta),
                         "largura": formato.largura},
              "tem_cena": False, "origem": "fallback"}

    # O fundo aqui e a cor principal, quase sempre extraida da propria logo:
    # sem isto a logo desaparece dentro dela mesma.
    if limiares is not None:
        logo_img, modo = mod_logo.preparar_para_fundo(logo_img, fundo, limiares)
        relato["logo_modo"] = modo

    peca = Image.new("RGBA", (formato.largura, formato.altura), tuple(list(fundo) + [255]))
    _marca_dagua(peca, formato, logo_img, _tinta_da_forma(fundo))
    peca = peca.convert("RGB")
    desenho = ImageDraw.Draw(peca)

    if formato.chave == "login":
        margem = 96
        util = int(formato.largura * 0.52)
        encaixada = mod_logo.encaixar(logo_img, util, 220)
        peca.paste(encaixada, (margem, 300), encaixada)
        _registrar_logo(relato, encaixada, logo_img, margem, 300)

        y = 640
        linha1, linha2 = formatos.TITULO
        f, linhas, coube = tipo.ajustar(desenho, linha1, util, 72, 44, "Bold", 1)
        desenho.text((margem, y), linhas[0], font=f, fill=tinta)
        relato["caixas"].append({"tipo": "titulo_1", "corpo": f.size, "coube": coube,
                                 "caixa": [margem, y, margem + util, y + int(f.size * 1.2)],
                                 "tinta": cor.para_hex(tinta)})
        y += int(f.size * 1.18)
        f, linhas, coube = tipo.ajustar(desenho, linha2, util, 72, 44, "Bold", 1)
        desenho.text((margem, y), linhas[0], font=f, fill=destaque)
        relato["caixas"].append({"tipo": "titulo_2", "corpo": f.size, "coube": coube,
                                 "caixa": [margem, y, margem + util, y + int(f.size * 1.2)],
                                 "tinta": cor.para_hex(destaque)})
        y += int(f.size * 1.5)

        f, linhas, coube = tipo.ajustar(desenho, formatos.SUBTITULO, util, 28, 19,
                                        "Regular", 3)
        for i, linha in enumerate(linhas):
            desenho.text((margem, y + i * int(f.size * 1.45)), linha, font=f, fill=tinta)
        relato["caixas"].append({"tipo": "subtitulo", "corpo": f.size, "coube": coube,
                                 "caixa": [margem, y, margem + util,
                                           y + int(f.size * 1.45) * len(linhas)],
                                 "tinta": cor.para_hex(tinta)})
        desenho.line([margem, formato.altura - 150, margem + 160, formato.altura - 150],
                     fill=destaque, width=5)
        return peca, relato

    # Faixas 1920x320: cabecalho e minimalista partilham a pauta e divergem no
    # conteudo. O minimalista e mudo por definicao do GEM ("sem texto e sem
    # fotografia") — e sem frase, uma regua vertical ficaria pendurada no vazio.
    margem = 64
    encaixada = mod_logo.encaixar(logo_img, 300, 84)
    topo = (formato.altura - encaixada.size[1]) // 2

    if formato.chave == "minimalista":
        centro = (formato.largura - encaixada.size[0]) // 2
        peca.paste(encaixada, (centro, topo), encaixada)
        _registrar_logo(relato, encaixada, logo_img, centro, topo)
        return peca, relato

    peca.paste(encaixada, (margem, topo), encaixada)
    _registrar_logo(relato, encaixada, logo_img, margem, topo)

    x = margem + encaixada.size[0] + 48
    desenho.line([x - 24, topo, x - 24, topo + encaixada.size[1]], fill=destaque, width=4)
    f, linhas, coube = tipo.ajustar(desenho, formatos.FRASE_CABECALHO,
                                    formato.largura - x - margem, 30, 20, "Medium", 2)
    altura_texto = int(f.size * 1.3) * len(linhas)
    y = (formato.altura - altura_texto) // 2
    for i, linha in enumerate(linhas):
        desenho.text((x, y + i * int(f.size * 1.3)), linha, font=f, fill=tinta)
    relato["caixas"].append({"tipo": "frase", "corpo": f.size, "coube": coube,
                             "caixa": [x, y, formato.largura - margem, y + altura_texto],
                             "tinta": cor.para_hex(tinta)})
    return peca, relato
