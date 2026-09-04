"""Sobe a logo e o favicon do cliente para um portal Zydon.

    python "Identidade Visual/subir_identidade.py" --org pocs \
        --portal <uuid> --logo caminho/logo.png --nome "Cliente"

Por padrao roda em **simulacao**: prepara tudo, mostra o que faria e nao grava.
So grava com `--gravar`. Isto escreve num portal de producao que alguem pode
estar apresentando — o padrao seguro e nao escrever.

A aparencia anterior e sempre salva em disco antes da gravacao. E o caminho de
volta, e nao existe outro.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
for _caminho in (str(AQUI), str(RAIZ)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import cor as mod_cor  # noqa: E402
import favicon as mod_favicon  # noqa: E402
import logo as mod_logo  # noqa: E402
import paleta as mod_paleta  # noqa: E402
import portal as mod_portal  # noqa: E402
import regua as mod_regua  # noqa: E402


def _carregar_env():
    """Le o .env da raiz do repo, e cai no do Sales Ops enquanto as chaves
    Zydon ainda moram la (ver CLAUDE.md: poc-portais e a pasta de execucao)."""
    candidatos = [RAIZ / ".env", Path.cwd() / ".env",
                  Path(r"C:\Users\joaop\OneDrive\Códigos\Automação POCs\.env")]
    achou = []
    for alvo in candidatos:
        if not alvo.exists():
            continue
        for linha in alvo.read_text(encoding="utf-8-sig").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            nome, valor = linha.split("=", 1)
            os.environ.setdefault(nome.strip(),
                                  valor.strip().strip('"').strip("'"))
        achou.append(alvo)
    return achou


def main(argv=None):
    _carregar_env()
    import credenciais  # depois do .env: ele le os.environ na chamada

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--org", default="pocs", help="organizacao Zydon (padrao: pocs)")
    p.add_argument("--portal", required=True, help="UUID do portal (solution_id)")
    p.add_argument("--logo", required=True, help="arquivo da logo do cliente")
    p.add_argument("--nome", default="", help="nome do cliente (usado se o "
                                              "favicon precisar cair na inicial)")
    p.add_argument("--favicon", help="favicon pronto; sem isto ele e derivado da logo")
    p.add_argument("--favicon-modo", default="auto", choices=mod_favicon.MODOS,
                   help="auto: simbolo se houver, senao a inicial. "
                        "inteira: encaixa a logo toda (some na aba a 16px se a "
                        "logo for larga). inicial: sempre a letra.")
    p.add_argument("--cor", help="cor primaria em hex; manda sobre a extraida")
    p.add_argument("--cor-portal", default="auto",
                   help="cor primaria do portal. Padrao 'auto': a PRINCIPAL da "
                        "paleta extraida da logo, a mesma que pinta o painel "
                        "dos banners. Aceita um hex para forcar, ou '' para "
                        "nao mexer na cor.")
    p.add_argument("--fundo-portal", default="#FFFFFF",
                   help="cor do fundo do cabecalho, onde a logo aparece. "
                        "Padrao: #FFFFFF. Nao e a --cor-portal: aquela e a cor "
                        "primaria da marca no portal, esta e o fundo contra o "
                        "qual a logo precisa ter contraste.")
    p.add_argument("--gravar", action="store_true",
                   help="GRAVA de verdade. Sem isto, so simula.")
    p.add_argument("--regua", help="regua.json alternativa")
    args = p.parse_args(argv)

    limiares = mod_regua.carregar(args.regua)
    headers, org = credenciais.carregar(args.org)

    # 1. Logo: normaliza e extrai a paleta (o favicon precisa das cores).
    # A regua do portal por cima da do banner: o destino aqui e o cabecalho, que
    # mostra a logo com ~120x29. Sem isto, marca horizontal legitima (Brava
    # 250x60, Poupa Agora 330x100) e reprovada por uma regra que nao e dela.
    limiares_logo = {**limiares["logo"], **limiares.get("logo_portal", {})}
    logo_img, laudo_logo = mod_logo.normalizar(args.logo, limiares_logo)
    pal = mod_paleta.extrair(logo_img, args.cor)
    print(f"Logo:    {laudo_logo['original'][0]}x{laudo_logo['original'][1]} -> "
          f"{laudo_logo['recortada'][0]}x{laudo_logo['recortada'][1]}"
          f"{'  (fundo chapado removido)' if laudo_logo['fundo_chapado_removido'] else ''}")
    print(f"Paleta:  {pal['principal']}  {pal['destaque']}  {pal['neutra']}")

    # Ao lado da logo seria sujar a pasta de onde ela veio (Downloads, em
    # geral). Fica em saidas/, junto do resto do que o modulo produz.
    import segmento as mod_segmento
    rotulo = mod_segmento._chave(args.nome or args.portal[:8])
    trabalho = AQUI / "saidas" / rotulo / "identidade"
    trabalho.mkdir(parents=True, exist_ok=True)
    # A logo do cabecalho tem que aparecer sobre o fundo do portal, que e
    # branco. Marca de logo branca some por completo ali: a do Uze Nails mediu
    # **0,000** de fracao visivel sobre branco, e o portal subiu com um
    # cabecalho vazio que so da para notar olhando. Quando nao passa, vai o
    # knockout — a silhueta pintada na cor legivel, que e a versao monocromatica
    # que toda marca tem. Perde-se a policromia; ganha-se existir.
    fundo_portal = mod_cor.de_hex(args.fundo_portal)
    logo_portal, laudo_visivel = mod_logo.preparar_para_fundo(
        logo_img, fundo_portal, limiares["logo"])
    if laudo_visivel["modo"] == "original":
        print(f"Cabecalho: logo visivel sobre {args.fundo_portal} "
              f"({laudo_visivel['fracao_visivel']:.0%} dos pixels)")
    else:
        print(f"Cabecalho: [CORRIGIDO] so {laudo_visivel['fracao_visivel']:.0%} "
              f"dos pixels apareciam sobre {args.fundo_portal}. Subindo em "
              f"knockout {laudo_visivel['tinta']}.")

    caminho_logo = trabalho / "logo.png"
    logo_portal.save(caminho_logo)

    # 2. Favicon: derivado, salvo em disco para dar para olhar antes de subir.
    if args.favicon:
        caminho_favicon = Path(args.favicon)
        print(f"Favicon: fornecido ({caminho_favicon.name})")
    else:
        icone, laudo_icone = mod_favicon.gerar(logo_img, pal, args.nome,
                                               limiares["logo"], args.favicon_modo)
        caminho_favicon = trabalho / "favicon.png"
        icone.save(caminho_favicon)
        detalhe = (f"inicial '{laudo_icone['inicial']}'"
                   if laudo_icone["caminho"] == "inicial"
                   else laudo_icone["caminho"])
        print(f"Favicon: {laudo_icone['lado']}x{laudo_icone['lado']} por "
              f"'{detalhe}', fundo {laudo_icone['fundo']}")
        if laudo_icone["caminho"] == "inicial" and args.favicon_modo == "auto":
            print("         [ATENCAO] nao achei simbolo separavel na logo, entao "
                  "o icone e a inicial.\n         Se ficar ruim, passe --favicon "
                  "com um arquivo seu.")
        if (laudo_icone["caminho"] == "logo-inteira"
                and logo_img.size[0] / logo_img.size[1] > 2.0):
            print("         [ATENCAO] logo larga encaixada num quadrado. Na aba "
                  "do navegador (16 e 32px)")
            print("         ela vira uma mancha; a 65px do painel ainda se le. "
                  "Confira o arquivo.")
    print(f"Arquivos em: {trabalho}")

    # 3. Portal: le a aparencia ANTES de qualquer coisa.
    jwt = mod_portal.entrar(headers["X-Zydon-Access-Key-Code"],
                            headers["X-Zydon-Access-Key-Token"], args.portal)
    antes = mod_portal.obter_aparencia(jwt)
    print(f"\nPortal:  {antes.get('title')}  ({args.portal})")
    print(f"  brand_image    {antes.get('brand_image')}")
    print(f"  favicon_image  {antes.get('favicon_image')}")
    print(f"  color          {antes.get('color')}")

    if not args.gravar:
        print("\n=== SIMULACAO — nada foi gravado ===")
        print("Faria, nesta ordem:")
        print(f"  POST /sales/resource-files      <- {caminho_logo.name}")
        print(f"  POST /sales/resource-files      <- {caminho_favicon.name}")
        print("  PUT  /b2b/portals/appearance    brand_image + favicon_image"
              + (f" + color {pal['principal'] if args.cor_portal == 'auto' else args.cor_portal}"
                 if args.cor_portal else ""))
        print("\nOlhe os dois arquivos acima. Para gravar, repita com --gravar.")
        return 0

    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = mod_portal.salvar_backup(antes, trabalho / f"aparencia-antes-{carimbo}.json")
    print(f"\nBackup da aparencia anterior: {backup}")

    # Passo 1: sobe os arquivos com as chaves da ORG e colhe os ids.
    print("Subindo arquivos...")
    id_logo = mod_portal.subir_arquivo(headers, caminho_logo)
    print(f"  logo    -> {id_logo}")
    id_favicon = mod_portal.subir_arquivo(headers, caminho_favicon)
    print(f"  favicon -> {id_favicon}")

    # Passo 2: um PUT so, com os dois campos. Dois PUTs seriam duas chances de
    # deixar a aparencia pela metade se o segundo falhasse.
    print("Gravando a aparencia...")
    mudancas = {"brand_image": id_logo, "favicon_image": id_favicon}
    if args.cor_portal:
        # 'auto' e o padrao desde 04/09/2026: a cor primaria do portal passa a
        # ser a MESMA principal que pinta o painel dos banners. Com #000000
        # fixo, o portal saia preto ao lado de uma tela de login verde ou
        # vermelha — duas identidades no mesmo lugar, e a que o cliente ve
        # primeiro era a que nao era dele.
        escolhida = pal["principal"] if args.cor_portal == "auto" else args.cor_portal
        escolhida, motivo = mod_cor.cor_de_portal(
            escolhida, limiares.get("portal", {}).get(
                "contraste_minimo_cor", mod_cor.CONTRASTE_MINIMO_COR_PORTAL))
        # O GET devolve a cor SEM "#" (ex.: "4A90D9"). Mandar com # gravaria um
        # valor de formato diferente do que o portal ja usa.
        mudancas["color"] = escolhida.lstrip("#").upper()
        print(f"Cor do portal: {escolhida}"
              f"{'  (da paleta da logo)' if args.cor_portal == 'auto' else ''}")
        if motivo:
            print(f"  [AVISO] {motivo}")
    mod_portal.atualizar_aparencia(jwt, antes, mudancas)

    # Passo 3: conferir o que ficou NO AR. O status da resposta nao basta — o
    # endpoint dedicado do spec respondia 200 sem trocar nada.
    depois = mod_portal.obter_aparencia(jwt)
    print("\n=== antes -> depois ===")
    for campo in ("brand_image", "favicon_image", "login_image", "color", "title"):
        a, b = antes.get(campo), depois.get(campo)
        print(f"  {campo:15s} {a} -> {b}" if a != b
              else f"  {campo:15s} (sem mudanca)")

    print("\n=== conferencia do byte servido ===")
    tudo_certo = True
    for campo, caminho in (("brand_image", caminho_logo),
                           ("favicon_image", caminho_favicon)):
        laudo = mod_portal.conferir_no_ar(jwt, depois[campo], caminho)
        tudo_certo &= laudo["identico"]
        print(f"  {campo:15s} {laudo['content_type']:12s} "
              f"{laudo['bytes']:>7} bytes  identico ao enviado: {laudo['identico']}")

    if not tudo_certo:
        print("\n[ERRO] O arquivo servido NAO e o que foi enviado. Nao confie "
              "nesta gravacao; confira no painel.")
        return 1
    print("\nPronto. Confira no portal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
