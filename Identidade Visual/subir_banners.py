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

from PIL import Image  # noqa: E402

import formatos  # noqa: E402
import portal as mod_portal  # noqa: E402
from subir_identidade import _carregar_env  # noqa: E402

# Para onde cada peca vai. O `minimalista` nao aparece: ele nao tem destino no
# portal — e a peca de reserva, para quando nenhuma cena presta.
#
# A dimensao NAO e escrita aqui, e sai de `formatos.py`. Escreve-la a mao ja
# mentiu uma vez: em 03/09/2026 a simulacao anunciou "2400x1800" para um
# `login.png` que tinha 1920x1440, gerado antes da mudanca de formato. Com
# `--gravar` teria subido a peca velha e informado ao Mitra a dimensao errada.
DESTINOS = {
    "login": {"onde": "aparencia", "campo": "login_image"},
    "cabecalho": {"onde": "banner", "campo": "imageLarge"},
}
for _chave, _dados in DESTINOS.items():
    _formato = formatos.POR_CHAVE[_chave]
    _dados["dimensao"] = (_formato.largura, _formato.altura)

MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}


class PecaDesatualizada(ValueError):
    """A peca em disco nao tem mais a dimensao que o formato pede."""


def conferir_dimensao(chave, caminho):
    """Levanta se o arquivo nao tem a dimensao do formato.

    Peca gerada antes de uma mudanca de formato continua em `aprovados/` e
    parece boa: mesmo nome, mesma pasta, abre no visualizador. Foi o caso em
    03/09/2026, quando o login foi de 1920x1440 para 2400x1800 — sem esta
    checagem, o portal receberia a peca velha e o Mitra ouviria a dimensao
    nova. O certo e recusar e dizer como regerar.
    """
    formato = formatos.POR_CHAVE[chave]
    esperado = (formato.largura, formato.altura)
    with Image.open(caminho) as img:
        real = img.size
    if real != esperado:
        raise PecaDesatualizada(
            f"'{chave}' em disco tem {real[0]}x{real[1]}, e o formato pede "
            f"{esperado[0]}x{esperado[1]}. A peca e anterior a uma mudanca de "
            f"formato. Regere:\n"
            f'  python "Identidade Visual/gerar_banners.py" regerar '
            f'"{Path(caminho).parent.parent}" --formatos {chave}')


def pecas_da_pasta(pasta, quais=None):
    """{chave: caminho} das pecas que tem destino no portal.

    Sai do `manifesto.json`, e nao de um `glob` em `aprovados/`: o manifesto e
    quem sabe qual arquivo foi o escolhido de cada formato, e um glob pegaria
    tambem a peca que ficou para tras numa remontagem.

    Confere a dimensao de cada uma antes de devolver — ver `conferir_dimensao`.
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
        conferir_dimensao(chave, caminho)
        achadas[chave] = caminho
    return achadas, manifesto


def _mime(caminho):
    return MIMES.get(Path(caminho).suffix.lower(), "image/png")


class ByteDiferente(RuntimeError):
    """O arquivo servido nao e o que subiu. Nada foi apontado no portal."""


def publicar(headers_org, jwt, pecas, ecoar=None):
    """Sobe as pecas e devolve {chave: {file_id, url, dimensao}}.

    **Isto nao muda o portal.** Sobe arquivo e colhe a URL publica — que e o
    que o Mitra consegue exibir na tela de curadoria. Servir a peca pelo tunel
    nao serviria: o endereco do cloudflared morre com o processo, e o executivo
    abriria a tela no dia seguinte com tres imagens quebradas.

    Confere o byte servido antes de devolver. O endpoint dedicado de logo do
    spec ja respondeu 200 sem trocar nada; o unico teste honesto e baixar e
    comparar.
    """
    publicadas = {}
    for chave, caminho in pecas.items():
        file_id = mod_portal.subir_arquivo(headers_org, caminho, _mime(caminho))
        laudo = mod_portal.conferir_no_ar(jwt, file_id, caminho)
        if not laudo["identico"]:
            raise ByteDiferente(
                f"o arquivo de '{chave}' servido nao e o que subiu "
                f"({laudo['bytes']} bytes). Nada foi apontado no portal.")
        publicadas[chave] = {
            "file_id": file_id,
            # A URL vai ASSINADA e inteira: sem a query ela responde 403, e foi
            # assim que a tela de curadoria do Mitra nasceu com as duas imagens
            # quebradas em 03/09/2026. `expira_em` viaja junto porque ela vale
            # ~2h — o file_id e que e para sempre.
            "url": laudo["url"],
            "expira_em": laudo.get("expira_em"),
            "dimensao": list(DESTINOS[chave]["dimensao"]),
            "arquivo": Path(caminho).name,
        }
        if ecoar:
            ecoar(f"  {chave:10s} -> {file_id}  ({laudo['bytes']} bytes)")
    return publicadas


class GravacaoPelaMetade(RuntimeError):
    """Um dos PUTs falhou **depois** de o outro ter gravado.

    Carrega `gravados` e `faltou` porque o estado real do portal e a unica
    informacao que importa nesse momento — e ela nao esta na mensagem da API.

    So e levantada com `gravados` NAO vazio. Ate 03/09/2026 ela saia tambem
    quando nada tinha entrado, e o nome mentia: o time do Mitra sondou a rota
    com um file_id invalido, recebeu "pela metade" com `gravados: []`, e o lado
    deles reenviava por reflexo — duas viagens condenadas para ouvir o mesmo
    nao. Falha no primeiro PUT nao e meia gravacao, e agora sobe como
    `ErroDoPortal` puro.
    """

    def __init__(self, causa, gravados, faltou):
        super().__init__(str(causa))
        self.gravados = gravados
        self.faltou = faltou


def aplicar(jwt, ids, aparencia=None, banner=None, ecoar=None, cor=None):
    """Aponta o portal para os ids ja publicados. Devolve o relato do GET.

    `cor` e a principal com que as pecas foram PINTADAS, e vai junto na
    aparencia. Sem ela o executivo troca a cor base na curadoria, ve os banners
    mudarem e o portal continuar na cor antiga — duas identidades no mesmo lugar,
    e a que o cliente ve primeiro nao e a que ele escolheu. Como a cor sai do
    `paleta.json` da propria pasta, mandar sempre e idempotente: quem nao trocou
    nada regrava o valor que ja estava la.

    `ids` e {"login": file_id, "cabecalho": file_id} — qualquer um dos dois
    pode faltar, e o que faltar nao e tocado. E assim que o executivo aplica
    uma peca e descarta a outra.

    Sao dois PUTs em endpoints diferentes e **nao ha transacao entre eles**: da
    para terminar com a tela de login nova e o banner velho. Quando o segundo
    falha, isto levanta `GravacaoPelaMetade` dizendo o que ja ficou gravado,
    em vez de deixar o portal num estado que ninguem sabe qual e.
    """
    if aparencia is None and ("login" in ids or cor):
        aparencia = mod_portal.obter_aparencia(jwt)
    if banner is None and "cabecalho" in ids:
        banner = _banner_alvo(jwt)

    gravados = []
    try:
        # Um PUT so com os dois campos: dois seriam duas chances de deixar a
        # aparencia pela metade. O GET devolve a cor SEM "#", e mandar com ele
        # gravaria um formato diferente do que o portal ja usa.
        mudancas = {}
        if ids.get("login"):
            mudancas["login_image"] = ids["login"]
        if cor:
            mudancas["color"] = str(cor).lstrip("#").upper()
        if mudancas:
            mod_portal.atualizar_aparencia(jwt, aparencia, mudancas)
            gravados.append("login" if ids.get("login") else "cor")
            if ecoar:
                ecoar("  [OK] aparencia: " + ", ".join(sorted(mudancas)))
        if ids.get("cabecalho") and banner:
            identificador = banner.get("id") or banner.get("bannerId")
            mod_portal.atualizar_banner(jwt, identificador, banner,
                                        {"imageLarge": ids["cabecalho"]})
            gravados.append("cabecalho")
            if ecoar:
                ecoar("  [OK] banner.images[0].imageLarge")
    except mod_portal.ErroDoPortal as erro:
        # Nada gravado nao e meia gravacao: o portal esta como estava, e quem
        # recebe isso nao tem o que reenviar. Sobe puro, para virar "a Zydon
        # recusou" com o motivo — que e a unica coisa que conserta.
        if not gravados:
            raise
        raise GravacaoPelaMetade(
            erro, gravados, [c for c in ids if c not in gravados]) from erro

    # Conferencia pelo GET, nunca pela resposta do PUT.
    relato = {"gravados": gravados, "confere": {}}
    if "login" in gravados or "cor" in gravados:
        depois = mod_portal.obter_aparencia(jwt)
        if ids.get("login"):
            relato["confere"]["login"] = depois.get("login_image") == ids["login"]
        if cor:
            relato["confere"]["cor"] = (
                str(depois.get("color") or "").lstrip("#").upper()
                == str(cor).lstrip("#").upper())
    if "cabecalho" in gravados:
        identificador = banner.get("id") or banner.get("bannerId")
        agora = mod_portal.obter_banner(jwt, identificador)
        servido = ((agora.get("images") or [{}])[0]).get("imageLarge")
        relato["confere"]["cabecalho"] = servido == ids["cabecalho"]
    return relato


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

    try:
        pecas, manifesto = pecas_da_pasta(args.pasta, quais)
    except (PecaDesatualizada, FileNotFoundError) as erro:
        print(f"[ERRO] {erro}", file=sys.stderr)
        return 2
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

    # Passo 1: subir e conferir o byte. Nada muda no portal ainda — se algo
    # falhar aqui, ele continua exatamente como estava.
    print("Subindo arquivos...")
    try:
        publicadas = publicar(headers, jwt, pecas, ecoar=print)
    except ByteDiferente as erro:
        print(f"\n[ERRO] {erro}", file=sys.stderr)
        return 1

    # Passo 2: os dois PUTs. Sem transacao entre eles — o relato importa.
    print("Gravando...")
    ids = {c: dados["file_id"] for c, dados in publicadas.items()}
    try:
        relato = aplicar(jwt, ids, aparencia, banner, ecoar=print)
    except GravacaoPelaMetade as erro:
        print(f"\n[ERRO] {erro}")
        if erro.gravados:
            print(f"[ATENCAO] ISTO JA FICOU GRAVADO: {', '.join(erro.gravados)}.")
            print("          O portal esta pela metade — a peca gravada esta no "
                  "ar e a outra nao.")
            print("          Repita so o que faltou:")
            print(f'            python "Identidade Visual/subir_banners.py" '
                  f'--org {args.org} --portal {args.portal} \\\n'
                  f'                --pasta "{args.pasta}" '
                  f'--so {",".join(erro.faltou)} --gravar')
        else:
            print("[INFO] Nada ficou gravado: o portal esta como estava.")
        return 1

    print("\n=== conferencia, pelo GET ===")
    for chave, certo in relato["confere"].items():
        print(f"  {chave:10s} {ids[chave]}  {'OK' if certo else 'NAO BATE'}")
    if not all(relato["confere"].values()):
        print("\n[ERRO] o portal nao esta apontando para o que foi gravado. "
              "Nao confie nesta gravacao; confira no painel.", file=sys.stderr)
        return 1

    print("\nPronto. Confira no portal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
