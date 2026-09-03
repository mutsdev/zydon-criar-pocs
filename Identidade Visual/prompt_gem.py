"""Monta o texto que o Joao Pedro cola no GEM para gerar SO as cenas.

E o prompt do GEM original, partido: a direcao de arte e a cena continuam; o
painel, o titulo, os icones, o cupom e a paleta saem — quem faz isso e o Pillow,
com fonte de verdade e a logo em PNG. O que o modelo nao desenha, o modelo nao
erra.

Tres camadas, deliberadamente separadas para que a iteracao seja rastreavel:

  FIXO      direcao de arte e proibicoes. Muda quando um defeito se repete
            em varios clientes.
  DERIVADO  paleta e enquadramento, calculados — nunca pedidos ao modelo.
  CLIENTE   segmento, objetos e ambiente.

Cada prompt montado e gravado ao lado da imagem. Sem isso, o julgamento humano
nao tem como virar ajuste na iteracao seguinte.
"""

import formatos

# A REGRA ZERO abre o prompt de proposito. Ate 03/09/2026 a proibicao de texto
# vivia no meio do bloco de direcao de arte e era ignorada: as cenas de
# mercearia saiam com potes escritos "Bousin" e "Parbolules" em letra torta.
# Instrucao no topo pesa mais para o modelo, e esta e a que nao pode falhar —
# texto na imagem e o unico defeito que o cliente enxerga de longe.
FIXO = """REGRA ZERO, acima de todas as outras: a imagem nao pode conter
NENHUMA letra, palavra, numero, rotulo, etiqueta ou embalagem impressa. Zero
caracteres. Se um objeto normalmente teria rotulo, mostre-o SEM rotulo, ou nao
mostre o objeto.

Voce e um diretor de arte senior de campanhas B2B. Gere FOTOGRAFIA
DE CAMPANHA, nao um banner diagramado: a diagramacao e feita depois, fora daqui.

Direcao de arte, obrigatoria em todas as imagens:
- Fotorrealismo de campanha paga: iluminacao profissional, sombra suave e
  direcional, profundidade de campo, materiais com textura real.
- Composicao editorial com respiro: no maximo 3 objetos em primeiro plano e uma
  area calma onde o olho descansa. Nada de vitrine cheia.
- As imagens da mesma leva sao a mesma campanha: mesma paleta, mesma luz, mesma
  hora do dia.

PROIBIDO, e isto e o mais importante do pedido:
- Nenhum texto, letra, numero, palavra, rotulo, placa escrita, embalagem com
  dizeres, tela de software com menu, marca d'agua ou pseudo-texto. Nenhum
  caractere legivel em lugar nenhum da imagem.
- Nenhum logotipo. Se a cena pedir uma fachada, uma placa ou um uniforme, use
  uma FORMA SOLIDA e lisa na cor principal, sem nada escrito dentro.
- Nada de colagem, moldura, borda decorativa ou faixa de cor sobreposta.
- Nenhum elemento importante cortado pela margem.
- Nada de foto de banco de imagens com filtro de cor por cima."""


def _bloco_cor(paleta):
    return f"""Paleta, obrigatoria (use os valores, nao a descricao):
- Cor dominante da cena: {paleta['principal']}
- Acentos e detalhes: {paleta['destaque']}
- A cena deve LER como sendo dessas cores. Nada de azul generico se a marca
  nao for azul."""


def _bloco_enquadramento(formato):
    if formato.chave == "login":
        return f"""Enquadramento: proporcao {formato.proporcao_pedida} (retrato).
Composicao vertical, com o assunto no terco central. Peca em 2K.
A imagem sera usada inteira, sem recorte — enquadre para o formato retrato."""
    return f"""Enquadramento: proporcao {formato.proporcao_pedida} (panoramico).
Peca em 2K. IMPORTANTE: a imagem sera RECORTADA numa faixa horizontal central,
mais estreita que o que voce vai gerar. Ponha tudo que importa na faixa central
da altura; o topo e a base serao descartados e devem conter so ambiente."""


def _bloco_cliente(contexto):
    objetos = ", ".join(contexto["objetos"])
    linhas = [f"Cliente: empresa do segmento de {contexto['segmento']}."]

    # Quando os objetos vem do catalogo real, dizer isso muda o pedido: nao sao
    # sugestoes de ambientacao, sao os produtos que a empresa vende, e a cena
    # existe para mostra-los. O contrario foi o defeito da Aroca Mercearia —
    # cena bonita de galpao para quem vende queijo.
    if contexto.get("origem") == "catalogo":
        linhas.append(
            f"O que ela vende de verdade, tirado do catalogo dela: {objetos}.\n"
            f"Escolha 2 ou 3 e ponha em primeiro plano. A cena SO presta se "
            f"mostrar este tipo de produto — cenario de galpao, caixas ou "
            f"paletes no lugar do produto e recusado.")
        # Segunda linha de defesa contra o defeito do dia 02/09/2026: os potes
        # da Aroca sairam escritos "Bousin" e "DIAMIANT DA SERA". A lista acima
        # ja foi limpa de marcas, mas alguma escapa quando nao ha forma
        # generica dela no catalogo, e ai so o pedido explicito segura.
        # Pedir "embalagem lisa" nao funciona: o modelo foi treinado em foto de
        # produto embalado e desenha rotulo de qualquer jeito — na Aroca saiu
        # "Bousin" e "cohbbe" em letra torta. O que funciona e tirar a
        # embalagem do pedido: queijo cortado na tabua nao tem onde escrever.
        linhas.append(
            "COMO FOTOGRAFAR: o produto FORA da embalagem. Alimento, cortado "
            "ou servido, sobre tabua, prato ou bancada; peca ou ferramenta, a "
            "peca nua. NADA de caixa, pote, saco, lata, garrafa, rotulo, "
            "etiqueta ou embalagem fechada — nem ao fundo. Estes nomes sao "
            "TIPOS de produto e nao marcas: nao escreva nenhum deles na "
            "imagem.")
    else:
        linhas.append(f"Objetos em primeiro plano (escolha 2 ou 3 destes): "
                      f"{objetos}.")

    linhas.append(f"Ambiente ao fundo, desfocado: {contexto['ambiente']}.")
    return "\n".join(linhas)


def montar(formato, paleta, contexto):
    """O prompt de uma cena. `contexto` traz segmento, objetos e ambiente."""
    if formato.chave == "minimalista":
        raise ValueError("o minimalista e 100% Pillow — nao tem prompt de cena")
    return "\n\n".join([
        FIXO,
        _bloco_cor(paleta),
        _bloco_enquadramento(formato),
        _bloco_cliente(contexto),
        "Gere UMA imagem. Pode arrastar direto para a pasta cenas/ com o "
        "nome que vier — o script identifica a cena pelo formato dela.",
    ])


def folha(paleta, contexto):
    """O texto unico que o executivo cola no GEM, cobrindo as duas cenas.

    Sai com o passo a passo junto porque o arquivo e lido fora de contexto,
    dias depois, por quem nao acompanhou a montagem.
    """
    partes = [
        "=" * 72,
        "COMO USAR",
        "=" * 72,
        "1. Abra o GEM no Gemini e mande a logo do cliente junto com o BLOCO 1.",
        "2. ARRASTE a imagem da pagina direto para a pasta cenas/ desta POC.",
        "   Nao precisa baixar nem renomear: o script sabe qual cena e qual",
        "   pelo formato dela (login e retrato, cabecalho e panoramico).",
        "3. Repita com o BLOCO 2.",
        "4. Rode:  python \"Identidade Visual/gerar_banners.py\" montar <pasta>",
        "",
        "Peca 2K. Cena pequena e recusada — ampliar inventaria pixel.",
        "Quer comparar tentativas? Arraste varias: o script julga todas e mostra",
        "lado a lado em contato.html, com o motivo de cada reprovacao.",
        "",
        f"Paleta calculada da logo: principal {paleta['principal']}, "
        f"destaque {paleta['destaque']}, neutra {paleta['neutra']}.",
        "",
    ]
    for i, formato in enumerate(formatos.COM_CENA, start=1):
        partes += ["=" * 72,
                   f"BLOCO {i} — cena de '{formato.chave}'",
                   "=" * 72, "",
                   montar(formato, paleta, contexto), ""]
    return "\n".join(partes)
