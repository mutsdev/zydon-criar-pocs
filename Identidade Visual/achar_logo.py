"""Acha a logo no site do cliente e diz se ela serve, antes de alguem subir.

    python "Identidade Visual/achar_logo.py" https://site-do-cliente.com.br
    python "Identidade Visual/achar_logo.py" <site> --mosaico  # para olhar

Por que existe: a rotina ja pega e valida imagem de produto do site do cliente.
Achar a logo e o mesmo trabalho, e **nao precisa de credencial nenhuma** — o
`ROTINA.md` dizia que "a logo nao entra aqui, ela pertence a identidade visual,
que roda onde estao as credenciais", e isso valia para SUBIR, nao para achar.
A distincao custou quatro POCs com logo passada a mao.

O que ele reprova e por que cada regra existe (as mesmas do `logo.py`, para nao
haver duas reguas):

  - menor lado < 200px      a do Poupa Agora tinha 330x100 e foi barrada la na
                            frente, com o portal ja criado
  - proporcao acima de 6:1  fica ilegivel em qualquer painel
  - quase nada opaco        marca d'agua ou arquivo corrompido
  - some no cabecalho       a do Uze Nails media 0,000 de fracao visivel sobre
                            branco: subiu e o cabecalho ficou vazio

A ultima **nao reprova o candidato**: o `subir_identidade` conserta sozinho com
knockout. Ela e reportada porque muda o que o cliente vai ver, e quem estiver
montando a POC merece saber antes.

A saida traz `logo_url` pronta para entrar no pedido. Codigo 1 quando nenhum
candidato passa — e ai o certo e pedir o arquivo ao cliente, nao insistir.
"""

import argparse
import json
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))

import cor as mod_cor  # noqa: E402
import logo as mod_logo  # noqa: E402
import regua as mod_regua  # noqa: E402

CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,image/webp,image/*,*/*;q=0.8",
}
PARALELISMO = 10
FUNDO_PORTAL = (255, 255, 255)

# SVG nao passa pelo Pillow. Ficaria melhor que qualquer PNG, entao vale
# apontar em vez de ignorar em silencio.
EXTENSOES_RASTER = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def _absoluta(base, referencia):
    try:
        return urljoin(base, referencia.strip())
    except ValueError:
        return None


def candidatos(html, base):
    """URLs candidatas, das mais promissoras para as menos. Sem repetir."""
    achados = []

    def juntar(url, origem):
        url = _absoluta(base, url or "")
        if url and url.startswith(("http://", "https://")):
            achados.append((url, origem))

    # 1. JSON-LD: quando existe, "logo" e declaracao do proprio site — a fonte
    # mais confiavel que ha, porque nao depende de adivinhar marcacao.
    for bloco in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                            html, re.S | re.I):
        try:
            dados = json.loads(bloco)
        except json.JSONDecodeError:
            continue
        for no in (dados if isinstance(dados, list) else [dados]):
            if not isinstance(no, dict):
                continue
            valor = no.get("logo")
            if isinstance(valor, dict):
                valor = valor.get("url")
            if isinstance(valor, str):
                juntar(valor, "json-ld")

    # 2. <img> com "logo" no src, na classe, no id ou no alt.
    for tag in re.findall(r"<img\b[^>]*>", html, re.I):
        if not re.search(r"logo|marca|brand", tag, re.I):
            continue
        fonte = re.search(r'\bsrc\s*=\s*["\']([^"\']+)', tag, re.I)
        if fonte:
            juntar(fonte.group(1), "img[logo]")

    # 3. Apple touch icon: quadrado e grande (180px), costuma ser o simbolo.
    for rel, atributos in re.findall(r'<link\b([^>]*rel\s*=\s*["\'][^"\']*)([^>]*)>',
                                     html, re.I):
        tag = rel + atributos
        if not re.search(r'apple-touch-icon|["\']icon', tag, re.I):
            continue
        href = re.search(r'\bhref\s*=\s*["\']([^"\']+)', tag, re.I)
        if href:
            juntar(href.group(1), "link[icon]")

    # 4. og:image por ultimo: costuma ser banner ou foto, nao logo. O `["\']`
    # no fim do padrao e o que corta og:image:width e og:image:height — sem
    # ele, "1848" e "1516" viram candidatas e o relatorio enche de lixo.
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        if not re.search(r'(og|twitter):image["\']', tag, re.I):
            continue
        conteudo = re.search(r'\bcontent\s*=\s*["\']([^"\']+)', tag, re.I)
        if conteudo:
            juntar(conteudo.group(1), "og:image")

    vistos, unicos = set(), []
    for url, origem in achados:
        if url in vistos:
            continue
        vistos.add(url)
        unicos.append((url, origem))
    return unicos


def avaliar(par, limiares, pasta):
    """(url, origem) -> dicionario de laudo. Nunca levanta."""
    url, origem = par
    laudo = {"url": url, "origem": origem, "serve": False, "motivo": "",
             "visivel_no_branco": None}

    caminho = urlparse(url).path.lower()
    # Placeholder de tema passa em todas as regras mecanicas — o do WooCommerce
    # tem 205x206 e 7% de visibilidade — e e uma caixa cinza. So o nome denuncia.
    if re.search(r"placeholder|no-image|sem-imagem", caminho):
        laudo["motivo"] = "placeholder do tema, nao e a logo"
        return laudo
    if caminho.endswith(".svg"):
        laudo["motivo"] = ("SVG — nao da para medir aqui, mas vetor e a melhor "
                           "fonte que existe: baixe e converta")
        laudo["svg"] = True
        return laudo

    try:
        r = requests.get(url, headers=CABECALHOS, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        laudo["motivo"] = f"nao baixou ({type(e).__name__})"
        return laudo

    if len(r.content) < 512:
        laudo["motivo"] = f"so {len(r.content)} bytes"
        return laudo

    alvo = pasta / (re.sub(r"[^a-zA-Z0-9]", "_", url)[-60:] or "cand")
    alvo.write_bytes(r.content)

    try:
        imagem, detalhe = mod_logo.normalizar(alvo, limiares)
    except mod_logo.LogoInvalida as e:
        laudo["motivo"] = str(e)
        return laudo
    except Exception as e:
        laudo["motivo"] = f"nao abriu ({type(e).__name__})"
        return laudo

    visivel = mod_logo.visibilidade(imagem, FUNDO_PORTAL,
                                   limiares["contraste_logo_minimo"])
    laudo.update(serve=True, tamanho=detalhe["recortada"],
                 aspecto=detalhe["aspecto"],
                 fundo_chapado_removido=detalhe["fundo_chapado_removido"],
                 visivel_no_branco=round(visivel, 4),
                 arquivo=str(alvo))
    return laudo


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("site", help="a home do cliente")
    p.add_argument("--extra", nargs="*", default=[],
                   help="URLs candidatas a mais, se voce ja tiver alguma")
    p.add_argument("--regua", help="regua.json alternativa")
    p.add_argument("--mosaico", action="store_true",
                   help="monta um mosaico das candidatas, para olhar")
    p.add_argument("--json", action="store_true",
                   help="imprime so o laudo em JSON, para script")
    args = p.parse_args(argv)

    limiares = mod_regua.carregar(args.regua)["logo"]

    try:
        pagina = requests.get(args.site, headers=CABECALHOS, timeout=30)
        pagina.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERRO] Nao consegui abrir {args.site}: {type(e).__name__}",
              file=sys.stderr)
        return 1

    base = pagina.url  # depois dos redirecionamentos, senao a relativa quebra
    pares = candidatos(pagina.text, base) + [(u, "manual") for u in args.extra]
    if not pares:
        print("[FALHA] Nenhuma candidata a logo no HTML. Peca o arquivo ao "
              "cliente — vetor, de preferencia.", file=sys.stderr)
        return 1

    pasta = Path(tempfile.mkdtemp(prefix="logo_"))
    with ThreadPoolExecutor(max_workers=PARALELISMO) as executor:
        laudos = list(executor.map(lambda par: avaliar(par, limiares, pasta), pares))

    # Visivel primeiro, tamanho depois — e nessa ordem por um motivo medido.
    # Muita marca publica duas versoes: a normal e a "light", clara, feita para
    # fundo escuro. Na Aroca as duas tinham 1848x1516, e ordenar so por pixel
    # escolheu a `logo-ligth.png`, que some no cabecalho branco — com o
    # knockout depois mascarando a escolha errada. Logo que ja aparece ganha de
    # logo que precisa ser consertada, do mesmo tamanho ou nao.
    def ordem(laudo):
        aparece = laudo["visivel_no_branco"] >= limiares["fracao_logo_visivel_minima"]
        return (aparece, laudo["tamanho"][0] * laudo["tamanho"][1])

    aprovadas = sorted([l for l in laudos if l["serve"]], key=ordem, reverse=True)

    if args.json:
        print(json.dumps({"logo_url": aprovadas[0]["url"] if aprovadas else None,
                          "candidatas": laudos}, ensure_ascii=False, indent=2))
        return 0 if aprovadas else 1

    print(f"\n{len(pares)} candidata(s) em {base}\n")
    for laudo in laudos:
        if laudo["serve"]:
            largura, altura = laudo["tamanho"]
            aviso = ("  [SOME NO CABECALHO — sobe em knockout]"
                     if laudo["visivel_no_branco"] < limiares["fracao_logo_visivel_minima"]
                     else "")
            print(f"  [OK]    {largura}x{altura}  visivel no branco "
                  f"{laudo['visivel_no_branco']:.0%}{aviso}\n"
                  f"          ({laudo['origem']}) {laudo['url']}")
        else:
            print(f"  [NAO]   {laudo['motivo'][:88]}\n"
                  f"          ({laudo['origem']}) {laudo['url']}")

    if args.mosaico:
        import subprocess
        urls = [l["url"] for l in laudos]
        subprocess.run([sys.executable,
                        str(AQUI.parent / "Criar Portais" / "mosaico_imagens.py"),
                        "--urls", *urls, "--saida",
                        str(AQUI / "saidas" / "mosaico_logo.png")])

    if not aprovadas:
        print("\n[FALHA] Nenhuma candidata passa. Peca o arquivo ao cliente — "
              "vetor, de preferencia.\n        Nao suba uma logo reprovada: "
              "logo ruim aparece em toda tela da demonstracao.", file=sys.stderr)
        return 1

    escolhida = aprovadas[0]
    print(f'\n  logo_url: {escolhida["url"]}')
    if escolhida["visivel_no_branco"] < limiares["fracao_logo_visivel_minima"]:
        print("  Ela some no cabecalho branco; o subir_identidade resolve com "
              "knockout, sozinho.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
