"""Fonte única das dimensões e do layout das peças.

Todo pixel de todo formato sai daqui. Se um número de tamanho aparecer
codificado em outro módulo, é bug — foi assim que o layout do GEM se perdeu
entre uma iteração e outra quando isso era manual.

A divisão painel/cena é o coração do desenho: o painel é território do Pillow
(logo real, texto de verdade) e a cena é território da imagem gerada. A junção
é borda reta, sem fusão — é o que torna impossível o texto embolado.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Formato:
    chave: str
    largura: int
    altura: int
    painel: int          # largura do painel de Pillow, em px (0 = sem painel)
    proporcao_pedida: str  # proporção da CENA (não da peça) a pedir ao gerador

    @property
    def cena(self):
        """Dimensão exata da região que a cena ocupa, já descontado o painel."""
        return (self.largura - self.painel, self.altura)

    @property
    def aspecto_cena(self):
        largura, altura = self.cena
        return largura / altura


# A PEÇA é 4:3 (1920x1440), mas a CENA não: descontado o painel de 768px,
# sobram 1152x1440, que é 4:5 retrato. Confundir as duas é o erro fácil aqui —
# pedir 4:3 ao gerador e encaixar em 4:5 custaria 27% da imagem em recorte.
# 4:5 é proporção nativa da lista suportada, então não se perde nada.
LOGIN = Formato("login", 1920, 1440, painel=768, proporcao_pedida="4:5")

# A PEÇA é 6:1, e 6:1 NÃO existe em gerador nenhum (o teto é 21:9 ≈ 2,33:1).
# Descontado o painel, a cena é 1056x320 = 3,3:1 — ainda mais largo que 21:9,
# então ela sai de um 21:9 recortado na altura. Recortar 30% da altura de uma
# peça enquadrada para isso é barato; espremer 21:9 em 6:1 destruiria a imagem.
CABECALHO = Formato("cabecalho", 1920, 320, painel=864, proporcao_pedida="21:9")

# Minimalista é 100% determinístico: sem cena, sem IA, sem o que dar errado.
MINIMALISTA = Formato("minimalista", 1920, 320, painel=1920, proporcao_pedida="")

TODOS = (LOGIN, CABECALHO, MINIMALISTA)
COM_CENA = (LOGIN, CABECALHO)
POR_CHAVE = {f.chave: f for f in TODOS}

# Os textos fixos, iguais aos do GEM. Ficam aqui porque são conteúdo de layout,
# e porque texto que o Pillow desenha nunca pode ser gerado por modelo nenhum.
TITULO = ("Bem-vindo ao", "Portal do Cliente")
SUBTITULO = "Compre com agilidade e segurança, direto do seu fornecedor."
ATALHOS = ("PEDIDOS", "FINANCEIRO", "CATÁLOGO")
SELOS = ("Compra segura — seus dados protegidos", "Entrega para todo o Brasil")
CUPOM = ("PRIMEIRACOMPRA", "10% OFF na primeira compra")
FRASE_CABECALHO = "Seu catálogo completo, sempre à mão."
