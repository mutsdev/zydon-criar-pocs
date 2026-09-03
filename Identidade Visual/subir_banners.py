"""Sobe as pecas geradas para o portal: tela de login e banner da home.

    python "Identidade Visual/subir_banners.py" --org pocs \
        --portal <uuid> --pasta "Identidade Visual/saidas/<cliente>/<carimbo>"

Por padrao roda em **simulacao**: mostra o que faria e nao grava. So grava com
`--gravar`. Isto escreve num portal que alguem pode estar apresentando.

## Onde cada peca vai parar

    login      2400x1800   ->  login_image  da aparencia   (PUT .../appearance)
    cabecalho  1920x320    ->  imageLarge   do banner      (PUT .../banners/{id})

Sao **dois PUTs em endpoints diferentes**, e nao existe transacao entre eles: da
para terminar com a tela de login nova e o banner velho. Por isso a gravacao
acontece em ordem, cada passo e relatado, e a falha do segundo diz em voz alta o
que ja ficou gravado e como repetir so o que faltou. Silenciar isso deixaria o
portal num estado que ninguem sabe qual e.

## O que este script NAO faz

Nao cria banner novo. O portal duplicado ja nasce com o "Banner principal" do
portal base; criar um segundo deixaria dois girando no carrossel, um com a arte
do cliente e outro com a da demonstracao. Ele le o que existe e troca a imagem.
"""

import argparse
import json
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

import formatos  # noqa: E402
import portal as mod_portal  # noqa: E402
from subir_identidade import _carregar_env  # noqa: E402

# Para onde cada peca vai. O `minimalista` nao aparece: ele nao tem destino no
# portal — e a peca de reserva, para quando nenhuma cena presta.
DESTINOS = {
    "login": {"onde": "aparencia", "campo": "login_image",
              "dimensao": (2400, 1800)},
    "cabecalho": {"onde": "banner", "campo": "imageLarge",
                  "dimensao": (1920, 320)},
}

MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}


def pecas_da_pasta(pasta, quais=None):
    """{chave: caminho} das pecas que tem destino no portal.

    Sai do `manifesto.json`, e nao de um `glob` em `aprovados/`: o manifesto e
    quem sabe qual arquivo foi o escolhido de cada formato, e um glob pegaria
    tambem a peca que ficou para tras numa remontagem.
    """
    pasta = Path(pasta)
    arquivo = pasta / "manifesto.json"
    if not arquivo.exists():
        raise FileNotFoundError(
            f"{arquivo} nao existe. Rode 'gerar_banners.py auto' ou 'montar' "
            f"nesta pasta antes de subir.")
    manifesto = json.loads(arquivo.read_text(encoding="utf-8"))

    achadas = {}
    for chave, dados in (manifesto.get("pecas") or {}).items():
        if chave not in DESTINOS:
            continue
        if quais and chave not in quais:
            continue
        caminho = pasta / "aprovados" / dados["arquivo"]
        if not caminho.exists():
            raise FileNotFoundError(
                f"o manifesto aponta {caminho.name}, que nao esta em "
                f"aprovados/. A pasta foi mexida a mao?")
        achadas[chave] = caminho
    return achadas, manifesto


def _mime(caminho):
    return MIMES.get(Path(caminho).suffix.lower(), "image/png")


def _banner_alvo(jwt, banner_id=None):
    """O banner que vamos trocar: o pedido, ou o primeiro que existir."""
    if banner_id:
        return mod_portal.obter_banner(jwt, banner_id)
    lista = mod_portal.listar_banners(jwt)
    if not lista:
        return None
    # O `id` as vezes chega como `bannerId`, dependendo do DTO.
    escolhido = lista[0]
    identificador = escolhido.get("id") or escolhido.get("bannerId")
    return mod_portal.obter_banner(jwt, identificador) if identificador else escolhido


def main(argv=None):
    _carregar_env()
    import credenciais

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--org", default="pocs")
    p.add_argument("--portal", required=True, help="UUID do portal (solution_id)")
    p.add_argument("--pasta", required=True,
                   help="a pasta do cliente, com manifesto.json e aprovados/")
    p.add_argument("--so", help="so estas pecas, separadas por virgula "
                                "(login,cabecalho). E como o executivo aplica "
                                "uma peca e descarta a outra.")
    p.add_argument("--banner-id", help="qual banner trocar; sem isto, o primeiro")
    p.add_argument("--gravar", action="store_true",
                   help="GRAVA de verdade. Sem isto, so simula.")
    args = p.parse_args(argv)

    quais = {c.strip() for c in args.so.split(",")} if args.so else None
    if quais and not quais <= set(DESTINOS):
        print(f"[ERRO] --so aceita {', '.join(sorted(DESTINOS))}; "
              f"recebi {sorted(quais)}.", file=sys.stderr)
        return 2

    pecas, manifesto = pecas_da_pasta(args.pasta, quais)
    if not pecas:
        print("[ERRO] nenhuma peca com destino no portal nesta pasta.",
              file=sys.stderr)
        return 1

    headers, _ = credenciais.carregar(args.org)
    jwt = mod_portal.entrar(headers["X-Zydon-Access-Key-Code"],
                            headers["X-Zydon-Access-Key-Token"], args.portal)

    aparencia = mod_portal.obter_aparencia(jwt)
    print(f"Portal:  {aparencia.get('title')}  ({args.portal})")
    print(f"Cliente: {manifesto.get('cliente')}")

    banner = None
    if "cabecalho" in pecas:
        banner = _banner_alvo(jwt, args.banner_id)
        if banner is None:
            print("  [AVISO] o portal nao tem banner nenhum. O cabecalho nao "
                  "tem onde entrar; sigo so com a tela de login.")
            pecas.pop("cabecalho")

    print("\nPecas:")
    for chave, caminho in pecas.items():
        destino = DESTINOS[chave]
        alvo = (f"aparencia.{destino['campo']}" if destino["onde"] == "aparencia"
                else f"banner['{banner.get('title')}'].{destino['campo']}")
        print(f"  {chave:10s} {caminho.name:22s} "
              f"{destino['dimensao'][0]}x{destino['dimensao'][1]}  ->  {alvo}")

    if not args.gravar:
        print("\n=== SIMULACAO — nada foi gravado ===")
        print("Faria, nesta ordem:")
        for chave in pecas:
            print(f"  POST /sales/resource-files   <- {pecas[chave].name}")
        if "login" in pecas:
            print("  PUT  /b2b/portals/appearance login_image")
        if "cabecalho" in pecas:
            print("  PUT  /b2b/banners/{id}       images[0].imageLarge")
        print("\nPara gravar, repita com --gravar.")
        return 0

    trabalho = Path(args.pasta)
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    mod_portal.salvar_backup(aparencia, trabalho / f"aparencia-antes-{carimbo}.json")
    if banner:
        mod_portal.salvar_backup(banner, trabalho / f"banner-antes-{carimbo}.json")
    print(f"\nBackup do estado anterior em: {trabalho}")

    # Passo 1: subir os arquivos. Nada muda no portal ainda — se algo falhar
    # aqui, o portal continua exatamente como estava.
    print("Subindo arquivos...")
    ids = {}
    for chave, caminho in pecas.items():
        ids[chave] = mod_portal.subir_arquivo(headers, caminho, _mime(caminho))
        print(f"  {chave:10s} -> {ids[chave]}")

    # Passo 2: conferir o BYTE servido antes de apontar o portal para ele. O
    # endpoint dedicado de logo do spec ja respondeu 200 sem trocar nada; o
    # unico teste honesto e baixar e comparar.
    print("Conferindo o byte servido...")
    for chave, caminho in pecas.items():
        laudo = mod_portal.conferir_no_ar(jwt, ids[chave], caminho)
        print(f"  {chave:10s} {laudo['bytes']:>8} bytes  "
              f"identico ao enviado: {laudo['identico']}")
        if not laudo["identico"]:
            print(f"\n[ERRO] o arquivo de '{chave}' servido nao e o que subiu. "
                  f"Nada foi apontado no portal; nenhuma gravacao aconteceu.",
                  file=sys.stderr)
            return 1

    # Passo 3: os dois PUTs. Sem transacao entre eles — o relato importa.
    gravados = []
    try:
        if "login" in pecas:
            mod_portal.atualizar_aparencia(jwt, aparencia,
                                           {"login_image": ids["login"]})
            gravados.append("login")
            print("  [OK] aparencia.login_image")

        if "cabecalho" in pecas:
            identificador = banner.get("id") or banner.get("bannerId")
            mod_portal.atualizar_banner(jwt, identificador, banner,
                                        {"imageLarge": ids["cabecalho"]})
            gravados.append("cabecalho")
            print("  [OK] banner.images[0].imageLarge")
    except mod_portal.ErroDoPortal as erro:
        print(f"\n[ERRO] {erro}")
        faltou = [c for c in pecas if c not in gravados]
        if gravados:
            print(f"[ATENCAO] ISTO JA FICOU GRAVADO: {', '.join(gravados)}.")
            print("          O portal esta pela metade — a peca gravada esta no "
                  "ar e a outra nao.")
            print("          Repita so o que faltou:")
            print(f'            python "Identidade Visual/subir_banners.py" '
                  f'--org {args.org} --portal {args.portal} \\\n'
                  f'                --pasta "{args.pasta}" '
                  f'--so {",".join(faltou)} --gravar')
        else:
            print("[INFO] Nada ficou gravado: o portal esta como estava.")
        return 1

    # Passo 4: conferir pelo GET, nunca pela resposta do PUT.
    print("\n=== conferencia, pelo GET ===")
    depois = mod_portal.obter_aparencia(jwt)
    if "login" in pecas:
        certo = depois.get("login_image") == ids["login"]
        print(f"  login_image  {aparencia.get('login_image')} -> "
              f"{depois.get('login_image')}  {'OK' if certo else 'NAO BATE'}")
    if "cabecalho" in pecas:
        identificador = banner.get("id") or banner.get("bannerId")
        agora = mod_portal.obter_banner(jwt, identificador)
        servido = ((agora.get("images") or [{}])[0]).get("imageLarge")
        certo = servido == ids["cabecalho"]
        print(f"  imageLarge   {servido}  {'OK' if certo else 'NAO BATE'}")

    print("\nPronto. Confira no portal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
