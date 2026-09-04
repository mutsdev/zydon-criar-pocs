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
    # O mesmo ajuste de legibilidade do `compor` — ver `cor.fundo_legivel`. O
    # fallback e o piso do pipeline: ele nao pode ser o unico caminho que
    # reprova na propria regua por causa da cor da marca.
    fundo, laudo_fundo = cor.fundo_legivel(cor.de_hex(paleta["principal"]))
    destaque = cor.de_hex(paleta["destaque"])
    tinta = cor.texto_sobre(fundo)

    relato = {"formato": formato.chave, "caixas": [], "logo": None,
              "painel": {"fundo": cor.para_hex(fundo), "tinta": cor.para_hex(tinta),
                         "largura": formato.largura, "ajuste": laudo_fundo},
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
        # O MESMO layout do `compor`, ocupando a peca inteira em vez de um
        # painel de 960px. Ate 04/09/2026 o fallback tinha desenho proprio, do
        # tempo em que o login era "Bem-vindo ao Portal do Cliente" — e ele
        # ficou para tras quando o painel foi refeito no padrao dos portais no
        # ar. O resultado e o que mais aparece na tela do executivo, porque
        # fallback e o que sai sempre que a cena reprova, e estava feio.
        #
        # Layout duplicado nao sobrevive a uma segunda mudanca de design. Aqui
        # nao ha duplicata: e a mesma funcao, com o painel do tamanho da peca.
        import dataclasses

        import compor
        # 58% e nao 100%: o `painel_login` pinta um retangulo solido ate a
        # largura do painel, e cobrir a peca inteira apagaria a marca d'agua
        # desenhada logo acima — a peca ficava com metade direita vazia. Com
        # 58%, o texto ocupa a esquerda e a silhueta da logo continua visivel a
        # direita, que e a composicao das referencias.
        cheio = dataclasses.replace(formato, painel=int(formato.largura * 0.58))
        compor.painel_login(peca, cheio, paleta, logo_img, relato, limiares)
        relato["painel"]["largura"] = formato.largura
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
