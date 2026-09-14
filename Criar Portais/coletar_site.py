"""coletar_site.py - Descobre a plataforma do site do cliente e cospe os
candidatos a produto (nome, preco, categoria, imagem, url) num JSON, numa ida so.

    python "Criar Portais/coletar_site.py" https://www.cliente.com.br/ [--saida arq.json] [--max 60]

Existe porque a coleta a mao custava metade das tool calls de cada POC
(15-32 por cliente em 14/09/2026): sondar Store API, VTEX, sitemap, abrir
paginas de produto uma a uma. Aqui todas as sondas saem juntas e a saida ja
esta no formato que o {empresa}_poc.json precisa. O agente le UM arquivo,
escolhe 5-12 e monta o JSON.

Plataformas: Shopify (/products.json), WooCommerce (Store API, preco em
centavos ja convertido), VTEX (catalog_system), Irroba / Loja Virtual / Wix /
qualquer outra (sitemap de produtos + og:image e preco da pagina ao vivo).
Sitemap de imagens do Irroba tem hash velho: a imagem sai da pagina, nunca do
sitemap.

Preco ausente vira null — quem monta a POC estima e diz isso na entrega.
"""

import argparse
import html as html_mod
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128 Safari/537.36"}
TIMEOUT = 20


def _get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
        return r if r.status_code == 200 else None
    except requests.RequestException:
        return None


def _json(url):
    r = _get(url)
    if not r:
        return None
    try:
        return r.json()
    except ValueError:
        return None


# ----------------------------------------------------------------- sondas

def shopify(base):
    d = _json(urljoin(base, "/products.json?limit=250"))
    if not d or "products" not in d:
        return None
    out = []
    for p in d["products"]:
        v = (p.get("variants") or [{}])[0]
        img = (p.get("images") or [{}])[0].get("src")
        preco = float(v.get("price") or 0) or None
        out.append(_item(p["title"], preco, p.get("product_type"), img,
                         urljoin(base, f"/products/{p['handle']}"),
                         variantes=[x.get("title") for x in p.get("variants", [])
                                    if x.get("title") not in (None, "Default Title")]))
    return "shopify", out


def woocommerce(base):
    d = _json(urljoin(base, "/wp-json/wc/store/v1/products?per_page=100"))
    if not isinstance(d, list) or not d:
        return None
    out = []
    for p in d:
        pr = p.get("prices") or {}
        div = 10 ** int(pr.get("currency_minor_unit", 2))
        preco = float(pr.get("price") or 0) / div or None
        cat = (p.get("categories") or [{}])[0].get("name")
        img = (p.get("images") or [{}])[0].get("src")
        out.append(_item(p["name"], preco, cat, img, p.get("permalink"),
                         variantes=[a.get("name") for a in p.get("attributes", [])
                                    if a.get("has_variations")]))
    return "woocommerce", out


def vtex(base):
    d = _json(urljoin(base, "/api/catalog_system/pub/products/search?_from=0&_to=49"))
    if not isinstance(d, list) or not d:
        return None
    out = []
    for p in d:
        it = (p.get("items") or [{}])[0]
        img = (it.get("images") or [{}])[0].get("imageUrl")
        offer = ((it.get("sellers") or [{}])[0].get("commertialOffer") or {})
        preco = offer.get("Price") or None
        cats = p.get("categories") or [""]
        out.append(_item(p.get("productName"), preco, cats[0].strip("/").split("/")[-1],
                         img, p.get("link")))
    return "vtex", out


_RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_RE_SITEMAP = re.compile(r"<sitemap>.*?<loc>\s*([^<\s]+)\s*</loc>", re.S)


def _urls_sitemap(base, limite):
    """Lista URLs de produto: segue o indice de sitemaps e filtra pelo caminho."""
    raiz = _get(urljoin(base, "/sitemap.xml"))
    if not raiz:
        return []
    filhos = _RE_SITEMAP.findall(raiz.text) or [urljoin(base, "/sitemap.xml")]
    filhos = [f for f in filhos if not re.search(r"blog|categor|pages|image|post", f, re.I)] or filhos
    urls = []
    for f in filhos:
        r = _get(f)
        if r:
            urls += _RE_LOC.findall(r.text)
    # produto costuma ter slug longo com hifens e nao ser pagina institucional
    prod = [u for u in urls if u.count("-") >= 2
            and not re.search(r"/(blog|categor|sobre|contato|tag|page|institucional)", u, re.I)]
    return prod[:limite]


def _pagina_produto(url):
    r = _get(url)
    if not r:
        return None
    h = r.text
    def meta(prop):
        m = re.search(r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]+)"' % prop, h) \
            or re.search(r'<meta[^>]+content="([^"]+)"[^>]+(?:property|name)="%s"' % prop, h)
        return html_mod.unescape(m.group(1)) if m else None
    nome = meta("og:title") or (re.search(r"<title>([^<]+)", h) or [None, None])[1]
    nome = re.split(r"\s[|\-–]\s", nome or "", 1)[0]  # "PRODUTO | Loja X" -> "PRODUTO"
    # imagem: a principal da pagina antes da og:image (Irroba serve a logo no og)
    m = re.search(r'class="[^"]*product-image-area[^"]*"[^>]*src="([^"]+)"', h)
    img = m.group(1) if m else meta("og:image")
    if img:
        img = re.sub(r"fit-in/\d+x\d+/", "fit-in/1000x1000/", img)
    m = re.search(r'"price"\s*:\s*"?(\d+(?:\.\d+)?)"?', h) or \
        re.search(r"R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})", h)
    preco = None
    if m:
        preco = float(m.group(1).replace(".", "").replace(",", ".")) if "," in m.group(1) else float(m.group(1))
    m = re.search(r'data-option-name="([^"]+)"', h)
    variantes = [html_mod.unescape(m.group(1))] if m else []
    variantes = [v for v in variantes if v.lower() not in ("único", "unico")]
    return _item(nome, preco, None, img, url, variantes=variantes)


def sitemap_generico(base, limite):
    urls = _urls_sitemap(base, limite)
    if not urls:
        return None
    with ThreadPoolExecutor(8) as ex:
        itens = [i for i in ex.map(_pagina_produto, urls) if i and i["imagem"]]
    return "sitemap", itens


def imagens_home(base, home):
    """Ultimo recurso: site institucional sem catalogo. Lista as imagens da home
    com alt/nome de arquivo para o agente escolher — e o que sobrou na American
    Rolamentos (produtoN.png na capa, sem pagina de produto)."""
    if not home:
        return None
    out, vistos = [], set()
    for m in re.finditer(r'<img[^>]+src="([^"]+)"[^>]*>', home.text):
        src = urljoin(base, m.group(1))
        if re.search(r"logo|icon|favicon|banner|bandeira|flag|\.svg", src, re.I):
            continue
        alt = re.search(r'alt="([^"]*)"', m.group(0))
        nome = (alt.group(1) if alt and alt.group(1).strip(".") else
                re.sub(r"[-_]", " ", src.rsplit("/", 1)[-1].rsplit(".", 1)[0]))
        vistos.add(src)
        out.append(_item(nome, None, None, src, base))
    # Construtor de landing (GreatPages, Wix) poe as imagens em JSON/CSS, sem
    # <img>: sobra a URL crua, sem nome. O mosaico e quem nomeia.
    for src in re.findall(r"https?://[^\"'\s)]+\.(?:png|jpe?g|webp)", home.text):
        if src in vistos or re.search(r"logo|icon|favicon|\.svg", src, re.I):
            continue
        vistos.add(src)
        out.append(_item("", None, None, src, base))
    return ("home", out) if out else None


def _item(nome, preco, categoria, imagem, url, variantes=None):
    return {"nome": (nome or "").strip(), "preco": preco, "categoria": categoria,
            "imagem": imagem, "url": url, "variantes": variantes or []}


# ------------------------------------------------------------------- main

def coletar(base, limite):
    home = _get(base)
    gerador = ""
    if home:
        m = re.search(r'<meta name="generator" content="([^"]+)"', home.text)
        gerador = m.group(1) if m else ""
    with ThreadPoolExecutor(3) as ex:
        sondas = list(ex.map(lambda f: f(base), (shopify, woocommerce, vtex)))
    achado = (next((s for s in sondas if s), None) or sitemap_generico(base, limite)
              or imagens_home(base, home))
    plataforma, itens = achado if achado else ("nenhuma", [])
    lojas = sorted(set(re.findall(
        r'href="(https?://(?:lista\.mercadolivre|www\.mercadolivre|[^"/]+\.lojaintegrada|[^"/]+\.nuvemshop|loja\.[^"/]+)[^"]*)"',
        home.text))) if home else []
    return {"site": base, "gerador": gerador, "plataforma": plataforma,
            "lojas_externas": lojas, "total": len(itens), "itens": itens[:limite]}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("site")
    p.add_argument("--saida", help="JSON de saida (padrao: imprime)")
    p.add_argument("--max", type=int, default=60)
    a = p.parse_args()
    base = a.site if a.site.startswith("http") else "https://" + a.site
    base = f"{urlparse(base).scheme}://{urlparse(base).netloc}/"
    d = coletar(base, a.max)
    txt = json.dumps(d, ensure_ascii=False, indent=1)
    if a.saida:
        open(a.saida, "w", encoding="utf-8").write(txt)
        print(f"{d['plataforma']}: {d['total']} itens -> {a.saida}")
    else:
        print(txt)
    return 0 if d["itens"] else 1


if __name__ == "__main__":
    sys.exit(main())
