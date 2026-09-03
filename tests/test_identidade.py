"""
Testes do gerador de banners (`Identidade Visual/`).

Existem para travar as duas promessas que o pipeline faz, e que sao a razao de
ele existir:

  1. **Banner ruim nao sobe.** Cada checagem do degrau 1 tem aqui um caso que
     ela reprova e um que ela aprova. Checagem que nao reprova nada e checagem
     que nao serve.
  2. **O pipeline nunca trava.** O fallback deterministico passa na propria
     regua nos tres formatos — se um dia parar de passar, e bug nosso, e o teste
     avisa antes do cliente.

E a garantia estrutural que sustenta as duas: nenhum caminho **amplia** ou
**distorce** imagem. Distorcer deformaria a logo; ampliar inventaria pixel.

Nada aqui toca a rede: o degrau 2 (juiz de visao) e testado so na regra de
decisao, com veredito de mentira.
"""

import json
import os
import sys

import pytest
from PIL import Image, ImageDraw, ImageFilter

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACOTE = os.path.join(RAIZ, "Identidade Visual")
if PACOTE not in sys.path:
    sys.path.insert(0, PACOTE)

import cenas  # noqa: E402
import compor  # noqa: E402
import cor  # noqa: E402
import fallback  # noqa: E402
import formatos  # noqa: E402
import juiz  # noqa: E402
import logo as mod_logo  # noqa: E402
import paleta as mod_paleta  # noqa: E402
import regua as mod_regua  # noqa: E402
import favicon as mod_favicon  # noqa: E402
import portal  # noqa: E402
import salvar  # noqa: E402
import tipografia as tipo  # noqa: E402
import validar  # noqa: E402


@pytest.fixture(scope="module")
def limiares():
    return mod_regua.carregar()


@pytest.fixture(scope="module")
def logo_colorida():
    """Logo com duas cores sobre fundo branco chapado — o caso mais comum."""
    img = Image.new("RGB", (600, 400), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([150, 80, 330, 300], fill=(200, 30, 40))
    d.rectangle([350, 170, 470, 215], fill=(250, 190, 20))
    return img


@pytest.fixture(scope="module")
def logo_normalizada(logo_colorida, limiares, tmp_path_factory):
    caminho = tmp_path_factory.mktemp("logo") / "marca.png"
    logo_colorida.save(caminho)
    recortada, _ = mod_logo.normalizar(caminho, limiares["logo"])
    return recortada


@pytest.fixture(scope="module")
def paleta(logo_normalizada):
    return mod_paleta.extrair(logo_normalizada)


def cena_fotografica(tamanho, ruido=True):
    """Uma cena que passa no degrau 1: tem luz variada, foco e respiro."""
    largura, altura = tamanho
    img = Image.new("RGB", tamanho, (140, 90, 60))
    d = ImageDraw.Draw(img)
    # Metade calma (respiro) e metade com objetos (foco e variacao de luz).
    for i in range(altura):
        d.line([0, i, largura, i], fill=(120 + i % 40, 84 + i % 30, 58 + i % 24))
    for k in range(3):
        x = largura * (0.45 + k * 0.16)
        d.rectangle([x, altura * 0.35, x + largura * 0.11, altura * 0.8],
                    fill=(190 - k * 30, 60 + k * 20, 40), outline=(30, 20, 15), width=3)
    if ruido:
        img = img.filter(ImageFilter.SHARPEN)
    return img


# ---------------------------------------------------------------------------
# A garantia estrutural: nunca ampliar, nunca distorcer
# ---------------------------------------------------------------------------

def test_encaixar_preserva_aspecto_dentro_de_um_pixel(logo_normalizada):
    original = logo_normalizada.size[0] / logo_normalizada.size[1]
    for caixa in [(300, 120), (624, 168), (260, 74), (80, 80), (1000, 1000)]:
        encaixada = mod_logo.encaixar(logo_normalizada, *caixa)
        largura, altura = encaixada.size
        assert abs(largura - altura * original) <= 1.0, caixa


def test_encaixar_nunca_amplia(logo_normalizada):
    grande = mod_logo.encaixar(logo_normalizada, 5000, 5000)
    assert grande.size == logo_normalizada.size


@pytest.mark.parametrize("formato", formatos.COM_CENA, ids=lambda f: f.chave)
def test_ajustar_cena_da_dimensao_exata_sem_ampliar(formato):
    largura, altura = formato.cena
    # Fonte generosa e com outro aspecto: forca recorte E reducao.
    fonte = Image.new("RGB", (int(largura * 1.6), int(altura * 1.9)), (10, 20, 30))
    ajustada, laudo = cenas.ajustar(fonte, formato)
    assert ajustada.size == formato.cena
    assert laudo["fator"] <= 1.0
    assert not laudo["ampliou"]


@pytest.mark.parametrize("formato", formatos.COM_CENA, ids=lambda f: f.chave)
def test_cena_pequena_e_recusada_em_vez_de_ampliada(formato):
    largura, altura = formato.cena
    minuscula = Image.new("RGB", (largura // 3, altura // 3), (10, 20, 30))
    with pytest.raises(cenas.CenaPequena) as erro:
        cenas.ajustar(minuscula, formato)
    # A mensagem tem que dizer o tamanho necessario: e um pedido acionavel.
    assert str(largura) in str(erro.value)


# ---------------------------------------------------------------------------
# Degrau 0: a logo
# ---------------------------------------------------------------------------

def test_normalizar_remove_fundo_branco_chapado(logo_colorida, limiares, tmp_path):
    caminho = tmp_path / "marca.png"
    logo_colorida.save(caminho)
    recortada, laudo = mod_logo.normalizar(caminho, limiares["logo"])
    assert laudo["fundo_chapado_removido"]
    assert recortada.size[0] < 600 and recortada.size[1] < 400


def test_normalizar_nao_apaga_fundo_quando_os_cantos_discordam(limiares, tmp_path):
    """Fundo nao chapado nao pode ser removido por cor — destruiria a arte."""
    img = Image.new("RGB", (400, 400), (255, 255, 255))
    ImageDraw.Draw(img).rectangle([0, 0, 200, 400], fill=(20, 20, 20))
    caminho = tmp_path / "meio-a-meio.png"
    img.save(caminho)
    _, laudo = mod_logo.normalizar(caminho, limiares["logo"])
    assert not laudo["fundo_chapado_removido"]


def test_logo_pequena_demais_aborta(limiares, tmp_path):
    caminho = tmp_path / "mini.png"
    Image.new("RGB", (80, 80), (10, 10, 10)).save(caminho)
    with pytest.raises(mod_logo.LogoInvalida):
        mod_logo.normalizar(caminho, limiares["logo"])


def test_logo_desproporcional_aborta(limiares, tmp_path):
    caminho = tmp_path / "faixa.png"
    img = Image.new("RGBA", (2400, 220), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([0, 60, 2399, 160], fill=(10, 90, 200, 255))
    img.save(caminho)
    with pytest.raises(mod_logo.LogoInvalida):
        mod_logo.normalizar(caminho, limiares["logo"])


# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------

def test_cor_informada_manda_sobre_a_extraida(logo_normalizada):
    resultado = mod_paleta.extrair(logo_normalizada, "#0055AA")
    assert resultado["principal"] == "#0055AA"
    assert resultado["diagnostico"]["origem_principal"] == "informada"


def test_logo_monocromatica_ainda_recebe_destaque(limiares, tmp_path):
    img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([80, 80, 320, 240], fill=(20, 20, 20, 255))
    caminho = tmp_path / "mono.png"
    img.save(caminho)
    recortada, _ = mod_logo.normalizar(caminho, limiares["logo"])
    resultado = mod_paleta.extrair(recortada)
    assert resultado["diagnostico"]["logo_monocromatica"]
    assert resultado["diagnostico"]["origem_destaque"] == "derivado"
    # O destaque tem que ser legivel sobre a principal: e cor de titulo e de selo.
    assert cor.contraste(cor.de_hex(resultado["destaque"]),
                         cor.de_hex(resultado["principal"])) >= 3.0


def test_destaque_e_legivel_tambem_sobre_marca_clara():
    """A correcao de contraste tem que andar para o lado que o fundo pede.

    Ate 03/09/2026 ela clareava sempre: sobre o verde claro da Aroca Mercearia
    as oito tentativas terminavam com MENOS contraste, e a manchete saia quase
    invisivel. Um caso claro e um escuro travam as duas direcoes.
    """
    for principal in ("#4CAF25", "#F2C230", "#1A4FA0", "#101418", "#7A7A7A"):
        resultado = mod_paleta.extrair(
            Image.new("RGBA", (300, 300), (0, 0, 0, 0)), principal)
        assert cor.contraste(cor.de_hex(resultado["destaque"]),
                             cor.de_hex(principal)) >= 3.0, principal


def test_neutra_sempre_contrasta_com_a_principal(logo_normalizada):
    for informada in ("#FFFFFF", "#000000", "#C81828", "#7A7A7A"):
        resultado = mod_paleta.extrair(logo_normalizada, informada)
        assert cor.contraste(cor.de_hex(resultado["neutra"]),
                             cor.de_hex(resultado["principal"])) >= 3.0, informada


# ---------------------------------------------------------------------------
# A logo tem que APARECER sobre o painel
# ---------------------------------------------------------------------------

def test_logo_da_cor_do_painel_vira_knockout(logo_normalizada, limiares):
    """A cor principal sai da propria logo: sem knockout, ela some no painel."""
    _, modo = mod_logo.preparar_para_fundo(logo_normalizada, (200, 30, 40),
                                           limiares["logo"])
    assert modo["modo"] == "knockout"


def test_logo_contrastante_fica_original(logo_normalizada, limiares):
    _, modo = mod_logo.preparar_para_fundo(logo_normalizada, (250, 250, 250),
                                           limiares["logo"])
    assert modo["modo"] == "original"


# ---------------------------------------------------------------------------
# Degrau 1: cada checagem reprova o seu caso e aprova o bom
# ---------------------------------------------------------------------------

def _checagens(falhas):
    return {f["checagem"] for f in falhas}


def test_cena_boa_passa(paleta, limiares):
    formato = formatos.CABECALHO
    falhas = validar.checar_cena(cena_fotografica(formato.cena), paleta, formato,
                                 limiares["mecanico"], tamanho_kb=180)
    assert "degeneracao" not in _checagens(falhas)
    assert "foco" not in _checagens(falhas)


def test_dimensao_errada_reprova(paleta, limiares):
    formato = formatos.CABECALHO
    errada = Image.new("RGB", (800, 320), (120, 90, 60))
    falhas = validar.checar_cena(errada, paleta, formato, limiares["mecanico"])
    assert "dimensao" in _checagens(falhas)


def test_imagem_chapada_reprova_por_degeneracao(paleta, limiares):
    formato = formatos.CABECALHO
    chapada = Image.new("RGB", formato.cena, (128, 128, 128))
    falhas = validar.checar_cena(chapada, paleta, formato, limiares["mecanico"])
    assert "degeneracao" in _checagens(falhas)


def test_imagem_borrada_reprova_por_foco(paleta, limiares):
    formato = formatos.CABECALHO
    borrada = cena_fotografica(formato.cena).filter(ImageFilter.GaussianBlur(14))
    falhas = validar.checar_cena(borrada, paleta, formato, limiares["mecanico"])
    assert "foco" in _checagens(falhas)


def test_peso_do_arquivo_de_entrada_nao_reprova_a_cena(paleta, limiares):
    """PNG arrastado do navegador tem varios MB e isso nao diz nada sobre a
    cena. Medir a entrada reprovava toda cena real — foi um bug de verdade."""
    formato = formatos.CABECALHO
    falhas = validar.checar_cena(cena_fotografica(formato.cena), paleta, formato,
                                 limiares["mecanico"], tamanho_kb=9000)
    assert "peso" not in _checagens(falhas)


def test_peca_pesada_depois_de_comprimir_reprova(limiares):
    """O peso que importa e o do arquivo que realmente foi gravado."""
    formato = formatos.CABECALHO
    relato = {"formato": "cabecalho", "tem_cena": True, "logo": None,
              "painel": {"fundo": "#C81828", "tinta": "#FFFFFF"}, "caixas": []}
    peca = Image.new("RGB", (formato.largura, formato.altura))
    assert "peso" in _checagens(validar.checar_peca(
        peca, relato, formato, limiares["mecanico"], kb_gravado=9000))
    assert "peso" not in _checagens(validar.checar_peca(
        peca, relato, formato, limiares["mecanico"], kb_gravado=200))


# ---------------------------------------------------------------------------
# Gravacao: formato e peso sao decisao nossa, nao motivo de reprovacao
# ---------------------------------------------------------------------------

def test_peca_com_foto_vira_jpeg_dentro_do_limite(paleta, logo_normalizada,
                                                  limiares, tmp_path):
    formato = formatos.LOGIN
    peca, relato = compor.montar(formato, paleta, logo_normalizada,
                                 cena_fotografica(formato.cena), limiares["logo"])
    caminho, laudo = salvar.gravar(peca, tmp_path / "login", relato["tem_cena"],
                                   limiares["mecanico"]["peso_maximo_kb"])
    assert caminho.endswith(".jpg")
    assert laudo["coube"] and laudo["kb"] <= limiares["mecanico"]["peso_maximo_kb"]
    assert Image.open(caminho).size == (formato.largura, formato.altura)


def test_peca_chapada_vira_png(paleta, logo_normalizada, limiares, tmp_path):
    """JPEG poe halo em borda dura de cor solida, e o minimalista so tem isso."""
    formato = formatos.MINIMALISTA
    peca, relato = fallback.montar(formato, paleta, logo_normalizada, "X",
                                   limiares["logo"])
    caminho, laudo = salvar.gravar(peca, tmp_path / "minimalista",
                                   relato["tem_cena"],
                                   limiares["mecanico"]["peso_maximo_kb"])
    assert caminho.endswith(".png")
    assert laudo["coube"]


def test_limite_apertado_derruba_a_qualidade_em_vez_de_falhar(paleta,
                                                              logo_normalizada,
                                                              limiares, tmp_path):
    """Peca pesada e problema de gravacao, e a resposta e gravar melhor."""
    formato = formatos.LOGIN
    peca, relato = compor.montar(formato, paleta, logo_normalizada,
                                 cena_fotografica(formato.cena), limiares["logo"])
    _, folgado = salvar.gravar(peca, tmp_path / "folgado", True, 700)
    _, apertado = salvar.gravar(peca, tmp_path / "apertado", True, 40)
    assert apertado["qualidade"] < folgado["qualidade"]
    assert apertado["kb"] < folgado["kb"]


def test_cor_fora_da_paleta_reprova(limiares):
    """O 'azul generico' que o GEM proibia em palavras, virado numero."""
    formato = formatos.CABECALHO
    paleta_vermelha = {"principal": "#C81828", "destaque": "#F8B810",
                       "neutra": "#F7F8FA"}
    azul = Image.new("RGB", formato.cena, (20, 60, 200))
    d = ImageDraw.Draw(azul)
    for i in range(formato.cena[1]):
        d.line([0, i, formato.cena[0], i], fill=(18 + i % 30, 55 + i % 40, 190 + i % 20))
    falhas = _checagens(validar.checar_cena(azul, paleta_vermelha, formato,
                                            limiares["mecanico"]))
    assert "banda_de_cor" in falhas or "matiz_intruso" in falhas


# ---------------------------------------------------------------------------
# Degrau 1 sobre a peca montada
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("formato", formatos.TODOS, ids=lambda f: f.chave)
def test_fallback_passa_na_propria_regua(formato, paleta, logo_normalizada, limiares):
    """A promessa de 'nunca trava': se isto quebra, o piso do pipeline afundou."""
    peca, relato = fallback.montar(formato, paleta, logo_normalizada, "Cliente",
                                   limiares["logo"])
    assert peca.size == (formato.largura, formato.altura)
    falhas = validar.checar_peca(peca, relato, formato, limiares["mecanico"])
    assert falhas == [], validar.resumir(falhas)


@pytest.mark.parametrize("formato", formatos.COM_CENA, ids=lambda f: f.chave)
def test_peca_composta_passa_e_tem_dimensao_exata(formato, paleta, logo_normalizada,
                                                  limiares):
    peca, relato = compor.montar(formato, paleta, logo_normalizada,
                                 cena_fotografica(formato.cena), limiares["logo"])
    assert peca.size == (formato.largura, formato.altura)
    falhas = validar.checar_peca(peca, relato, formato, limiares["mecanico"])
    assert falhas == [], validar.resumir(falhas)


def test_painel_de_login_ocupa_a_altura_toda(paleta, logo_normalizada, limiares):
    """O painel e escrito em fracao da altura, nao em pixel fixo.

    Quando o login foi de 1440 para 1800 de altura, as constantes codificadas
    empilhavam tudo no topo e deixavam o terco de baixo vazio — a peca passava
    em toda checagem e ficava feia, que e o pior tipo de falha. Isto ancora as
    duas pontas: algo perto do topo, algo perto da base.
    """
    formato = formatos.LOGIN
    _, relato = compor.montar(formato, paleta, logo_normalizada,
                              cena_fotografica(formato.cena), limiares["logo"])
    topos = [c["caixa"][1] for c in relato["caixas"]] + [relato["logo"]["caixa"][1]]
    bases = [c["caixa"][3] for c in relato["caixas"]]
    assert min(topos) < formato.altura * 0.12
    assert formato.altura * 0.85 < max(bases) < formato.altura


def test_login_traz_os_quatro_recursos_e_os_selos(paleta, logo_normalizada, limiares):
    """O padrao dos portais no ar: manchete, quatro recursos, faixa de selos."""
    formato = formatos.LOGIN
    _, relato = compor.montar(formato, paleta, logo_normalizada,
                              cena_fotografica(formato.cena), limiares["logo"])
    tipos = {c["tipo"] for c in relato["caixas"]}
    for i in range(1, len(formatos.RECURSOS) + 1):
        assert f"recurso_{i}_titulo" in tipos
    for i in range(1, len(formatos.SELOS_RODAPE) + 1):
        assert f"selo_{i}_titulo" in tipos


@pytest.mark.parametrize("formato", formatos.COM_CENA, ids=lambda f: f.chave)
def test_compor_recusa_cena_de_tamanho_errado(formato, paleta, logo_normalizada):
    errada = Image.new("RGB", (100, 100), (0, 0, 0))
    with pytest.raises(ValueError):
        compor.montar(formato, paleta, logo_normalizada, errada)


def test_texto_truncado_e_reprovado(paleta, limiares):
    """Texto que nao cabe nem no corpo minimo nasce reprovado, nao espremido."""
    formato = formatos.LOGIN
    relato = {"formato": "login", "tem_cena": True, "logo": None,
              "painel": {"fundo": paleta["principal"], "tinta": "#FFFFFF"},
              "caixas": [{"tipo": "titulo_1", "caixa": [72, 400, 696, 470],
                          "tinta": "#FFFFFF", "corpo": 40, "coube": False}]}
    peca = Image.new("RGB", (formato.largura, formato.altura))
    falhas = validar.checar_peca(peca, relato, formato, limiares["mecanico"])
    assert "texto_truncado" in _checagens(falhas)


def test_texto_ilegivel_e_reprovado(limiares):
    formato = formatos.LOGIN
    relato = {"formato": "login", "tem_cena": True, "logo": None,
              "painel": {"fundo": "#C81828", "tinta": "#C02030"},
              "caixas": [{"tipo": "subtitulo", "caixa": [72, 400, 696, 440],
                          "tinta": "#C02030", "corpo": 20, "coube": True}]}
    peca = Image.new("RGB", (formato.largura, formato.altura))
    falhas = validar.checar_peca(peca, relato, formato, limiares["mecanico"])
    assert "contraste" in _checagens(falhas)


def test_titulo_grande_usa_o_piso_de_texto_grande(limiares):
    """WCAG: 3:1 vale para texto grande. Cobrar 4,5 reprovaria a cor de destaque
    de metade das marcas — foi o que aconteceu na primeira rodada."""
    formato = formatos.LOGIN
    base = {"formato": "login", "tem_cena": True, "logo": None,
            "painel": {"fundo": "#C81828", "tinta": "#FFFFFF"}}
    grande = dict(base, caixas=[{"tipo": "titulo_2", "caixa": [72, 400, 696, 470],
                                 "tinta": "#F8B810", "corpo": 66, "coube": True}])
    miudo = dict(base, caixas=[{"tipo": "rodape", "caixa": [72, 400, 696, 430],
                                "tinta": "#F8B810", "corpo": 17, "coube": True}])
    peca = Image.new("RGB", (formato.largura, formato.altura))
    assert "contraste" not in _checagens(
        validar.checar_peca(peca, grande, formato, limiares["mecanico"]))
    assert "contraste" in _checagens(
        validar.checar_peca(peca, miudo, formato, limiares["mecanico"]))


# ---------------------------------------------------------------------------
# Degrau 2: so a regra de decisao (nada de rede)
# ---------------------------------------------------------------------------

def _veredito_limpo(**ajustes):
    base = {c: False for c in juiz.CHAVES_ESPERADAS if c.startswith("tem_")
            or c.startswith("composicao") or c.startswith("cor_")
            or c.startswith("parece_")}
    base["cena_condiz_com_o_segmento"] = True
    base["nota_estetica"] = 5
    base["defeito_principal"] = ""
    base.update(ajustes)
    return base


def test_veredito_limpo_aprova(limiares):
    aprovado, motivos = juiz.decidir(_veredito_limpo(), limiares["juiz"])
    assert aprovado and motivos == []


@pytest.mark.parametrize("defeito", ["tem_texto_ou_letras", "tem_logotipo_ou_marca",
                                     "tem_artefato", "composicao_entulhada",
                                     "cor_destoa_da_paleta"])
def test_qualquer_defeito_fatal_reprova(defeito, limiares):
    aprovado, motivos = juiz.decidir(_veredito_limpo(**{defeito: True}),
                                     limiares["juiz"])
    assert not aprovado and defeito in motivos


def test_cena_fora_do_segmento_reprova(limiares):
    aprovado, _ = juiz.decidir(
        _veredito_limpo(cena_condiz_com_o_segmento=False), limiares["juiz"])
    assert not aprovado


def test_nota_baixa_reprova_mesmo_sem_defeito_apontado(limiares):
    aprovado, motivos = juiz.decidir(_veredito_limpo(nota_estetica=3),
                                     limiares["juiz"])
    assert not aprovado and any("nota_3" in m for m in motivos)


# ---------------------------------------------------------------------------
# Tipografia e cor
# ---------------------------------------------------------------------------

def test_texto_longo_demais_reporta_que_nao_coube():
    peca = Image.new("RGB", (400, 200))
    desenho = ImageDraw.Draw(peca)
    _, _, coube = tipo.ajustar(desenho, "palavra " * 60, 200, 40, 18, linhas_max=2)
    assert not coube


def test_texto_normal_cabe():
    peca = Image.new("RGB", (900, 200))
    desenho = ImageDraw.Draw(peca)
    _, linhas, coube = tipo.ajustar(desenho, formatos.SUBTITULO, 600, 27, 19,
                                    linhas_max=3)
    assert coube and 1 <= len(linhas) <= 3


def test_hex_ida_e_volta():
    for texto in ("#000000", "#FFFFFF", "#1A4FA0", "#C81828"):
        assert cor.para_hex(cor.de_hex(texto)) == texto


def test_contraste_conhecido():
    assert cor.contraste((255, 255, 255), (0, 0, 0)) == pytest.approx(21.0, abs=0.01)
    assert cor.contraste((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)


def test_texto_sobre_escolhe_o_legivel():
    assert cor.texto_sobre((10, 10, 10)) == cor.BRANCO
    assert cor.texto_sobre((250, 250, 250)) == cor.PRETO


# ---------------------------------------------------------------------------
# Arrastar do navegador: o nome do arquivo nao pode importar
# ---------------------------------------------------------------------------

def _gravar(pasta, nome, tamanho):
    caminho = pasta / nome
    Image.new("RGB", tamanho, (90, 100, 110)).save(caminho)
    return caminho


def test_cena_sem_prefixo_e_classificada_pelo_aspecto(tmp_path):
    """O fluxo real e arrastar a imagem do Gemini para a pasta, com o nome que
    o navegador deu. Exigir renomear seria atrito por nada."""
    _gravar(tmp_path, "Gemini_Generated_Image_9x2k4a.png", (1440, 1800))   # 4:5
    _gravar(tmp_path, "Gemini_Generated_Image_7bq1zz.png", (2432, 1042))   # 21:9

    login = cenas.procurar(tmp_path, formatos.LOGIN, formatos.COM_CENA)
    cabecalho = cenas.procurar(tmp_path, formatos.CABECALHO, formatos.COM_CENA)

    assert [c.name for c in login] == ["Gemini_Generated_Image_9x2k4a.png"]
    assert [c.name for c in cabecalho] == ["Gemini_Generated_Image_7bq1zz.png"]


def test_nome_explicito_manda_sobre_o_aspecto(tmp_path):
    """Quem renomeia esta dando uma ordem, e ordem vence heuristica — mesmo
    quando o aspecto discorda."""
    _gravar(tmp_path, "login-1.png", (2432, 1042))  # panoramico, mas nomeado login
    assert [c.name for c in cenas.procurar(tmp_path, formatos.LOGIN,
                                           formatos.COM_CENA)] == ["login-1.png"]
    assert cenas.procurar(tmp_path, formatos.CABECALHO, formatos.COM_CENA) == []


def test_imagem_de_aspecto_absurdo_nao_e_chutada_em_nenhum_formato(tmp_path):
    """Arquivo muito fora e engano do usuario, nao candidato.

    'Muito fora' e um fator 1,8 — nao qualquer diferenca. Um quadrado 1:1 fica
    a 1,25x de 4:5 e **e** aceito como login: recortar 20% da largura de um
    quadrado e enquadramento normal, nao deformacao. O que nao entra e a faixa
    de 20:1 que alguem arrastou por engano.
    """
    _gravar(tmp_path, "faixa_absurda.png", (4000, 200))     # 20:1
    _gravar(tmp_path, "coluna_absurda.png", (200, 4000))    # 1:20
    assert cenas.classificar(tmp_path / "faixa_absurda.png", formatos.COM_CENA) is None
    assert cenas.classificar(tmp_path / "coluna_absurda.png", formatos.COM_CENA) is None
    assert cenas.procurar(tmp_path, formatos.LOGIN, formatos.COM_CENA) == []
    assert cenas.procurar(tmp_path, formatos.CABECALHO, formatos.COM_CENA) == []


def test_quadrado_vira_login_e_e_recortado(tmp_path):
    """Documenta a decisao acima: quadrado e cena de login valida.

    O lado sai da propria cena do formato para o caso nao envelhecer junto com
    a dimensao: quando o login foi de 1440 para 1800 de altura, o quadrado de
    1600 fixo passou a ser pequeno demais e o teste quebrou por um motivo que
    nao era o que ele mede.
    """
    lado = max(formatos.LOGIN.cena) + 200
    _gravar(tmp_path, "Gemini_Generated_Image_quadrada.png", (lado, lado))
    achadas = cenas.procurar(tmp_path, formatos.LOGIN, formatos.COM_CENA)
    assert len(achadas) == 1
    ajustada, laudo = cenas.carregar(achadas[0], formatos.LOGIN)
    assert ajustada.size == formatos.LOGIN.cena
    assert laudo["descartado"] > 0


def test_arquivo_que_nao_e_imagem_e_ignorado(tmp_path):
    (tmp_path / "anotacoes.txt").write_text("nao sou imagem", encoding="utf-8")
    (tmp_path / "quebrada.png").write_bytes(b"isto nao e um png")
    assert cenas.procurar(tmp_path, formatos.LOGIN, formatos.COM_CENA) == []


# ---------------------------------------------------------------------------
# Aparencia do portal: a fusao do PUT e a parte perigosa
# ---------------------------------------------------------------------------

APARENCIA = {
    "title": "Cliente X", "billing_name": "RAZAO SOCIAL LTDA",
    "fiscal_registration_number": "00000000000191", "color": "4A90D9",
    "brand_image": "antigo-logo", "favicon_image": "antigo-favicon",
    "login_image": "antigo-login", "extend_screen": True,
    "menu_guidance": "VERTICAL", "display_watermark": True,
    "floating_button": {"active": True, "type": "WHATSAPP"},
    "tag_manager": {}, "use_main_seller_phone_as_whatsapp_number": False,
    "is_open_to_public": True,
    # devolvidos pelo GET e recusados pelo PUT:
    "updated_at": "2026-01-01T00:00:00Z", "has_shop": True,
    "is_suspended": False, "enable_access_request": True,
}


def test_put_preserva_tudo_que_nao_foi_pedido_para_mudar():
    """O PUT leva o corpo inteiro. Trocar so a logo nao pode zerar o CNPJ."""
    corpo = portal.corpo_do_put(APARENCIA, {"brand_image": "novo"})
    assert corpo["brand_image"] == "novo"
    for campo in ("title", "billing_name", "fiscal_registration_number", "color",
                  "favicon_image", "login_image", "menu_guidance",
                  "floating_button", "is_open_to_public"):
        assert corpo[campo] == APARENCIA[campo], campo


def test_put_descarta_campos_que_a_api_nao_aceita():
    """updated_at e has_shop vem no GET e o PUT recusa — mandar da 400."""
    corpo = portal.corpo_do_put(APARENCIA, {})
    for intruso in ("updated_at", "has_shop", "is_suspended",
                    "enable_access_request"):
        assert intruso not in corpo


def test_campo_inventado_falha_antes_de_chamar_a_api():
    """Errar o nome do campo tem que doer aqui, e nao virar gravacao silenciosa."""
    with pytest.raises(ValueError, match="nao aceita"):
        portal.corpo_do_put(APARENCIA, {"logo_image": "x"})


# ---------------------------------------------------------------------------
# Banner da home: o mesmo cuidado do PUT da aparencia, noutro endpoint
# ---------------------------------------------------------------------------

# Copiado do que a API devolveu de verdade em 03/09/2026, para o portal da
# Fornello (`GET /api/b2b/banners/banners` -> envelope com `items`). Os dois
# campos do fim vem do GET e nao existem no PUT.
BANNER = {
    "id": "b-1", "title": "Banner principal", "type": "LARGE",
    "durationType": "LIFETIME", "active": True,
    "profile_partner": True, "profile_seller": True,
    "images": [{"id": "img-1", "description": "Banner principal",
                "imageSmall": "peq-antigo", "imageLarge": "grd-antigo",
                "link": "https://zydon.com.br", "order": 1, "active": True}],
    "group": [],
    "created_at": "2026-01-01T00:00:00Z", "portal_id": "p-1",
}


def test_banner_troca_a_imagem_e_preserva_o_resto():
    corpo = portal.corpo_do_banner(BANNER, {"imageLarge": "grd-novo"})
    assert corpo["images"][0]["imageLarge"] == "grd-novo"
    # O que nao foi pedido nao muda: link, ordem e a imagem mobile.
    assert corpo["images"][0]["imageSmall"] == "peq-antigo"
    assert corpo["images"][0]["link"] == "https://zydon.com.br"
    # O id da imagem tem que voltar: e ele que diz "atualize esta", e nao
    # "crie outra". Sem ele o slide duplicaria em silencio.
    assert corpo["images"][0]["id"] == "img-1"
    for campo in ("title", "type", "durationType", "active", "profile_partner"):
        assert corpo[campo] == BANNER[campo], campo


def test_envelope_paginado_do_banner_e_lido_pelo_items(monkeypatch):
    """A lista vem em `items`, e nao em `content`. Ler a chave errada devolve
    lista vazia, que le como 'o portal nao tem banner' — uma mentira dificil de
    desconfiar, porque nao ha erro nenhum."""
    class Resposta:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"currentPage": 0, "perPage": 25, "total": 1,
                    "items": [BANNER]}

    monkeypatch.setattr(portal.requests, "get", lambda *a, **k: Resposta())
    assert portal.listar_banners("jwt-falso") == [BANNER]


def test_banner_descarta_campos_que_o_put_nao_aceita():
    corpo = portal.corpo_do_banner(BANNER, {"imageLarge": "x"})
    for intruso in ("created_at", "portal_id", "id"):
        assert intruso not in corpo


def test_banner_com_campo_de_imagem_inventado_falha_antes_da_api():
    with pytest.raises(ValueError, match="nao aceita"):
        portal.corpo_do_banner(BANNER, {"imagemGrande": "x"})


def test_banner_sem_imagem_nenhuma_ganha_a_primeira():
    """Alguem pode ter apagado a imagem do portal base. Falhar ali seria pior:
    o resto do corpo ja e valido e o unico que falta e o que vamos por."""
    vazio = dict(BANNER, images=[])
    corpo = portal.corpo_do_banner(vazio, {"imageLarge": "grd-novo"})
    assert len(corpo["images"]) == 1
    assert corpo["images"][0]["imageLarge"] == "grd-novo"


def test_banner_nao_mexe_nos_slides_seguintes():
    """Slide dois em diante foi alguem que pos a mao — sobrescrever seria
    decidir por essa pessoa."""
    dois = dict(BANNER, images=BANNER["images"] + [
        {"description": "segundo", "imageLarge": "outro", "order": 2,
         "active": True}])
    corpo = portal.corpo_do_banner(dois, {"imageLarge": "grd-novo"})
    assert corpo["images"][1]["imageLarge"] == "outro"


def test_pecas_da_pasta_saem_do_manifesto_e_nao_de_um_glob(tmp_path):
    """Um glob em aprovados/ pegaria peca que ficou para tras numa remontagem.
    O manifesto e quem sabe qual arquivo foi o escolhido de cada formato."""
    import subir_banners

    (tmp_path / "aprovados").mkdir()
    for nome in ("login.jpg", "cabecalho.jpg", "minimalista.png", "orfa.jpg"):
        (tmp_path / "aprovados" / nome).write_bytes(b"x")
    (tmp_path / "manifesto.json").write_text(json.dumps({
        "cliente": "Teste", "pecas": {
            "login": {"arquivo": "login.jpg"},
            "cabecalho": {"arquivo": "cabecalho.jpg"},
            "minimalista": {"arquivo": "minimalista.png"}}}), encoding="utf-8")

    pecas, _ = subir_banners.pecas_da_pasta(tmp_path)
    # O minimalista nao tem destino no portal, e a orfa nao esta no manifesto.
    assert set(pecas) == {"login", "cabecalho"}

    so_login, _ = subir_banners.pecas_da_pasta(tmp_path, {"login"})
    assert set(so_login) == {"login"}


def test_manifesto_apontando_arquivo_que_sumiu_falha_claro(tmp_path):
    import subir_banners

    (tmp_path / "aprovados").mkdir()
    (tmp_path / "manifesto.json").write_text(json.dumps({
        "pecas": {"login": {"arquivo": "login.jpg"}}}), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="aprovados"):
        subir_banners.pecas_da_pasta(tmp_path)


def test_login_sem_portal_e_recusado():
    """Sem solution_id o JWT nasce sem portal e a aparencia responde 404 sem
    dizer por que — falhar aqui e mais barato que depurar aquilo."""
    with pytest.raises(ValueError, match="portal_id"):
        portal.entrar("code", "token", None)


def test_favicon_de_logo_larga_cai_na_inicial(logo_normalizada, limiares):
    """Logo que e so palavra nao tem simbolo recortavel: usa a inicial."""
    _, laudo = mod_favicon.gerar(logo_normalizada, {"principal": "#C81828",
                                                    "destaque": "#F8B810",
                                                    "neutra": "#F7F8FA"},
                                 "Krindges", limiares["logo"])
    assert laudo["lado"] == mod_favicon.LADO


def test_favicon_sai_quadrado_em_todos_os_caminhos(limiares, tmp_path):
    pal = {"principal": "#1A4FA0", "destaque": "#F5A623", "neutra": "#F7F8FA"}
    casos = {}
    quadrada = Image.new("RGBA", (400, 380), (0, 0, 0, 0))
    ImageDraw.Draw(quadrada).ellipse([30, 30, 370, 350], fill=(10, 90, 200, 255))
    casos["quadrada"] = quadrada

    lockup = Image.new("RGBA", (900, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(lockup)
    d.ellipse([20, 60, 200, 240], fill=(200, 30, 40, 255))
    d.rectangle([340, 120, 860, 180], fill=(20, 20, 20, 255))
    casos["lockup"] = lockup

    # 3,9:1 — larga como um logotipo de palavra, mas dentro do limite do
    # degrau 0 (acima de 6:1 a logo e recusada antes de chegar aqui).
    palavra = Image.new("RGBA", (900, 300), (0, 0, 0, 0))
    ImageDraw.Draw(palavra).rectangle([20, 40, 880, 260], fill=(20, 20, 20, 255))
    casos["palavra"] = palavra

    caminhos = {}
    for nome, img in casos.items():
        caminho = tmp_path / f"{nome}.png"
        img.save(caminho)
        recortada, _ = mod_logo.normalizar(caminho, limiares["logo"])
        icone, laudo = mod_favicon.gerar(recortada, pal, "Teste", limiares["logo"])
        assert icone.size == (mod_favicon.LADO, mod_favicon.LADO), nome
        caminhos[nome] = laudo["caminho"]

    # Cada forma de logo tem que cair no caminho que lhe corresponde.
    assert caminhos["quadrada"] == "logo-inteira"
    assert caminhos["lockup"] == "simbolo-destacado"
    assert caminhos["palavra"] == "inicial"


# ==========================================
# gerador: o tamanho pedido tem que caber
# ==========================================

def test_dimensao_gerada_nunca_obriga_a_ampliar():
    """O `cenas.ajustar` proibe ampliar. Se o gerador pedir pequeno demais, a
    cena morre em CenaPequena DEPOIS de ja ter custado neurons — o erro mais
    caro possivel. Esta e a conta que impede isso."""
    import gerador

    for formato in formatos.COM_CENA:
        largura, altura = gerador.dimensao(formato)
        _, laudo = cenas.ajustar(Image.new("RGB", (largura, altura)), formato)
        assert not laudo["ampliou"], f"{formato.chave} obrigaria a ampliar"


def test_dimensao_respeita_o_contrato_da_api():
    """256-1920 e multiplo de 16. O modelo arredonda sozinho para 16, e pedir
    823 para receber 816 e a diferenca que um dia vira bug."""
    import gerador
    for formato in formatos.COM_CENA:
        for lado in gerador.dimensao(formato):
            assert 256 <= lado <= gerador.LADO_MAXIMO
            assert lado % gerador.MULTIPLO == 0


def test_orcamento_de_um_formato_so_e_menor_que_o_dos_dois():
    """Recusar uma peca tem que custar uma peca, e nao as duas."""
    import gerador
    _, tudo = gerador.orcamento(1)
    _, so_login = gerador.orcamento(1, ["login"])
    assert 0 < so_login < tudo


def test_formato_desconhecido_levanta_antes_de_gastar_neuron():
    import gerador
    with pytest.raises(ValueError, match="desconhecido"):
        gerador.alvos_validos(["logim"])
    # O minimalista existe, mas nao tem cena: gerar para ele seria gasto puro.
    with pytest.raises(ValueError, match="nao tem cena"):
        gerador.alvos_validos(["minimalista"])


def test_regerar_acrescenta_em_vez_de_sobrescrever(tmp_path):
    """A cena recusada continua em disco: o executivo pode mudar de ideia."""
    import gerador
    for nome in ("login-1.png", "login-2.png", "cabecalho-1.png"):
        Image.new("RGB", (40, 40)).save(tmp_path / nome)
    assert gerador.proximo_indice(tmp_path, formatos.LOGIN) == 3
    assert gerador.proximo_indice(tmp_path, formatos.CABECALHO) == 2
    assert gerador.proximo_indice(tmp_path / "vazia", formatos.LOGIN) == 1


def test_manifesto_preserva_o_formato_que_nao_foi_remontado(tmp_path, paleta,
                                                            logo_normalizada):
    """Remontar so o login nao pode sumir com o cabecalho do manifesto.

    O arquivo continuaria em `aprovados/` e desapareceria para todo consumidor
    — a pior forma de perder uma peca, porque nada acusa.
    """
    import gerar_banners

    logo_normalizada.save(tmp_path / "logo-normalizada.png")
    (tmp_path / "cenas").mkdir()
    (tmp_path / "contexto.json").write_text(json.dumps({
        "cliente": "Teste", "paleta": paleta,
        "contexto": {"segmento": "Alimentos", "objetos": ["Queijo"],
                     "ambiente": "cozinha", "origem": "catalogo"}}),
        encoding="utf-8")
    (tmp_path / "manifesto.json").write_text(json.dumps({
        "cliente": "Teste", "pecas": {
            "cabecalho": {"origem": "aprovado", "arquivo": "cabecalho.jpg"}}}),
        encoding="utf-8")

    class Args:
        pasta = str(tmp_path)
        regua = None
        sem_juiz = True
        so_fallback = True
        tentativas = None
        formatos = "login"

    assert gerar_banners.montar(Args()) == 0
    pecas = json.loads((tmp_path / "manifesto.json").read_text(
        encoding="utf-8"))["pecas"]
    assert pecas["cabecalho"]["arquivo"] == "cabecalho.jpg"
    assert "login" in pecas


def test_gerador_sem_chave_levanta_o_erro_proprio(monkeypatch):
    """SemChave e o que faz o chamador cair no GEM manual em vez de estourar."""
    import gerador
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    with pytest.raises(gerador.SemChave):
        gerador.credenciais()


# ==========================================
# catalogo: o que a cena mostra
# ==========================================

def test_tira_marcas_mantendo_o_tipo():
    """Marca no nome faz o modelo DESENHAR o rotulo, torto. Em 02/09/2026 a
    cena da Aroca saiu com potes escritos "Bousin" e "DIAMIANT DA SERA"."""
    import segmento
    tipos = segmento.tirar_marcas([
        "Queijo de Cabra Boursin", "Queijo de Cabra Buchette",
        "Queijo de Cabra Petit", "Cafe Torrado Diamante da Serra"])
    assert "Queijo de Cabra" in tipos
    assert not any("Boursin" in t or "Buchette" in t for t in tipos)


def test_palavra_de_embalagem_nao_vira_objeto_da_cena():
    """"Champignon Inteiro Balde" pediria um balde, e balde tem rotulo."""
    import segmento
    tipos = segmento.tirar_marcas(["Champignon Inteiro Balde",
                                   "Champignon Inteiro Pote",
                                   "Champignon Fatiado Vidro"])
    assert all("Balde" not in t and "Pote" not in t and "Vidro" not in t
               for t in tipos), tipos


def test_catalogo_manda_sobre_a_inferencia_de_setor(tmp_path):
    """Produto que o cliente vende ganha de palpite sobre o setor — e nao
    depende de cota: foi um 429 que fez a mercearia virar galpao de caixas."""
    import segmento
    poc = tmp_path / "x_poc.json"
    poc.write_text(json.dumps({"empresa": "X", "etapas": [
        {"endpoint": "categories", "requests": [
            {"payload": {"name": "Queijos de Cabra"}}]},
        {"endpoint": "products", "requests": [
            {"payload": {"name": "Queijo de Cabra Um"}},
            {"payload": {"name": "Queijo de Cabra Dois"}},
            {"payload": {"name": "Queijo de Cabra Tres"}}]}]},
        ensure_ascii=False), encoding="utf-8")
    contexto = segmento.resolver("Alimentos", "modelo", usar_rede=False,
                                 catalogo=str(poc))
    assert contexto["origem"] == "catalogo"
    assert any("Queijo" in o for o in contexto["objetos"])


def test_regra_zero_abre_o_prompt():
    """Instrucao no topo pesa mais. No meio do bloco ela era ignorada."""
    import prompt_gem
    assert prompt_gem.FIXO.lstrip().startswith("REGRA ZERO")
