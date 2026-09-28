"""Extracao automatica de um catalogo publico para a fila do receptor.

O modulo nao cria portal. Ele transforma site -> JSON declarativo, valida o JSON
antes da entrega e devolve dados suficientes para o Mitra continuar o fluxo.
A fila que chama este modulo e persistente em disco; falha de rede nao apaga o
pedido.
"""

from __future__ import annotations

import base64
import copy
import json
import re
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag, parse_qs, unquote
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

RAIZ = Path(__file__).resolve().parent.parent
TEMPLATE = RAIZ / "Criar Portais" / "template_poc.json"
DATABASE_ID = "5ba882ff-ba29-4599-b583-0bf9b8913b19"
TIMEOUT = (10, 25)
MAX_SITEMAPS = 12
MAX_URLS = 80
MAX_PRODUTOS = 12
MIN_PRODUTOS = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}
IMAGE_HEADERS = {
    **HEADERS,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

BAD_SEGMENTS = {
    "blog", "categoria", "categorias", "category", "tag", "tags", "autor",
    "author", "page", "pagina", "pages", "contato", "contact", "sobre",
    "about", "login", "carrinho", "cart", "checkout", "minha-conta",
    "my-account", "customer", "account", "feed", "search", "busca",
    "politica", "privacidade", "termos", "sitemap",
}
BAD_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".pdf",
                ".css", ".js", ".xml", ".json", ".woff", ".woff2")

CURAMED_LANDING_PRODUCTS = (
    ("412675-88d0d16df9b748d9a33cf33de8bcfb19.png",
     "Compressa de Gaze Hidrofila Esteril Cremer", "Cremer", "Curativos e Gaze"),
    ("412675-600d12f8e214017645ea078bdf69a036.png",
     "Curativo Adesivo Bege Cremer 40 Unidades", "Cremer", "Curativos e Gaze"),
    ("412675-2c3ed6d2ecef6afcae9e367c2bb39f4c.png",
     "Fita Microporosa Hipoalergenica Cremer", "Cremer", "Curativos e Gaze"),
    ("412675-ea6b70e05ba92590d9c0322e5b13b2d5.png",
     "Fita Microporosa Hipoalergenica Extra Flex 10cm x 10m", "Missner", "Curativos e Gaze"),
    ("412675-344bca8b0846159da4901b0ef01d4970.png",
     "Curativo Hidrocoloide 10 Unidades", "Curamed", "Curativos e Gaze"),
    ("412675-3ed757e5a5f7202e695d90357912518a.png",
     "Curativo Liquido Hemostatico 28ml", "Curamed", "Curativos e Gaze"),
    ("412675-b2ddcce529b4ce2b71404586b8229d5d.png",
     "Coletor para Material Perfurocortante 7 13 e 20 Litros", "Descarbox", "Descartaveis e Coletores"),
    ("412675-39fcedcc6c22bbed5b392c36e4549f98.png",
     "Coletor para Material Infectante 15 30 e 50 Litros", "Descarbox", "Descartaveis e Coletores"),
    ("412675-f5a3c4b5124eecabd2ff61df6259f42b.png",
     "Perax Rio Test Fitas para Acido Peracetico 30 Fitas", "Rioquimica", "Higiene e Desinfeccao"),
    ("412675-1bd6d209413a64880c149361f40f8022.png",
     "Curativo Adesivo para Puncao Venosa 500 Unidades", "Medix", "Curativos e Gaze"),
    ("412675-38e800d6b7083f54898cddae4f463157.png",
     "Algodao Torcido Fio de Sutura Absorvivel Esteril No 0", "Technofio", "Fios e Suturas"),
    ("412675-c806683ba216b7c3cae62304c48875f2.png",
     "Cavilon Creme Barreira Duravel Hidratante 92g", "Cavilon", "Curativos e Gaze"),
)


class ExtracaoFalhou(RuntimeError):
    """Erro acionavel ao montar o catalogo."""


def _clean_url(url: str, base: str | None = None) -> str:
    if not isinstance(url, str) or not url.strip():
        return ""
    url = urljoin(base or "", url.strip())
    url, _ = urldefrag(url)
    return url


def _same_site(url: str, base: str) -> bool:
    a = (urlparse(url).hostname or "").lower().removeprefix("www.")
    b = (urlparse(base).hostname or "").lower().removeprefix("www.")
    return bool(a and b and (a == b or a.endswith("." + b) or b.endswith("." + a)))


def _get(url: str, *, image: bool = False, timeout=TIMEOUT):
    headers = IMAGE_HEADERS if image else HEADERS
    return requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)


def _soup(url: str):
    response = _get(url)
    response.raise_for_status()
    return response.url, BeautifulSoup(response.content, "html.parser"), response.text


def _json_values(soup: BeautifulSoup):
    for node in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            yield json.loads(node.string or node.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _is_type(value, wanted: str) -> bool:
    types = value.get("@type") if isinstance(value, dict) else None
    if isinstance(types, str):
        types = [types]
    return any(str(t).lower() == wanted.lower() for t in (types or []))


def _first_jsonld(soup: BeautifulSoup, wanted: str):
    for root in _json_values(soup):
        for item in _walk_json(root):
            if _is_type(item, wanted):
                return item
    return None


def _text(value) -> str:
    if isinstance(value, list):
        value = " ".join(str(x) for x in value)
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _image_candidates(soup: BeautifulSoup, base_url: str, product=None):
    found = []
    if isinstance(product, dict):
        images = product.get("image") or product.get("images") or []
        if isinstance(images, str):
            images = [images]
        for image in images:
            if isinstance(image, dict):
                image = image.get("url") or image.get("contentUrl")
            found.append(image)
    for prop in ("og:image", "twitter:image"):
        node = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop})
        if node and node.get("content"):
            found.append(node["content"])
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            if img.get(attr):
                found.append(img.get(attr))
                break
    out = []
    for item in found:
        item = _clean_url(item, base_url)
        if not item or item in out:
            continue
        low = item.lower()
        if any(x in low for x in ("logo", "favicon", "icon", "avatar", "pixel", "emoji")):
            continue
        out.append(item)
    return out


def _price(product, soup: BeautifulSoup):
    if isinstance(product, dict):
        offers = product.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        raw = offers.get("price") if isinstance(offers, dict) else None
        if raw is None:
            raw = product.get("price")
        try:
            val = float(str(raw).replace(".", "").replace(",", "."))
            if val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass
    for attrs in ({"property": "product:price:amount"}, {"itemprop": "price"}):
        node = soup.find("meta", attrs=attrs)
        raw = node.get("content") if node else None
        try:
            val = float(str(raw).replace(".", "").replace(",", "."))
            if val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass
    # So usa valores claramente precedidos por R$; evita confundir telefone/SKU.
    text = soup.get_text(" ", strip=True)
    match = re.search(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})|[0-9]+(?:[.,][0-9]{2}))", text)
    if match:
        try:
            return round(float(match.group(1).replace(".", "").replace(",", ".")), 2)
        except ValueError:
            pass
    return None


def _category(product, soup: BeautifulSoup, url: str):
    if isinstance(product, dict):
        raw = product.get("category")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        if _text(raw):
            return _text(raw)
    crumb = soup.select(".breadcrumb a, .breadcrumbs a, [aria-label*=breadcrumb] a")
    labels = [_text(x.get_text(" ", strip=True)) for x in crumb]
    labels = [x for x in labels if x and x.lower() not in {"home", "início", "inicio"}]
    if labels:
        return labels[-2] if len(labels) > 1 else labels[0]
    parts = [x for x in urlparse(url).path.split("/") if x]
    if len(parts) >= 2:
        return re.sub(r"[-_]+", " ", parts[-2]).strip().title()
    return ""


def _logo(soup: BeautifulSoup, base_url: str, organization=None):
    if isinstance(organization, dict):
        raw = organization.get("logo")
        if isinstance(raw, dict):
            raw = raw.get("url") or raw.get("contentUrl")
        value = _clean_url(raw, base_url)
        if value:
            return value
    for img in soup.find_all("img"):
        alt = _text(img.get("alt"))
        classes = " ".join(img.get("class") or [])
        if "logo" in (alt + " " + classes).lower():
            value = _clean_url(img.get("src") or img.get("data-src"), base_url)
            if value:
                return value
    return ""


def _sitemap_locs(text: str):
    try:
        root = ElementTree.fromstring(text)
        return [x.text.strip() for x in root.iter() if x.tag.lower().endswith("loc") and x.text]
    except ElementTree.ParseError:
        return re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.I | re.S)


def _discover_sitemaps(base: str, homepage_text: str):
    candidates = []
    for line in homepage_text.splitlines():
        if line.lower().startswith("sitemap:"):
            candidates.append(line.split(":", 1)[1].strip())
    candidates += [
        urljoin(base, "/sitemap.xml"), urljoin(base, "/wp-sitemap.xml"),
        urljoin(base, "/product-sitemap.xml"), urljoin(base, "/sitemap_index.xml"),
    ]
    seen, product_urls = set(), []
    queue_urls = []
    for url in candidates:
        url = _clean_url(url, base)
        if url and url not in seen:
            seen.add(url); queue_urls.append(url)
    for _ in range(MAX_SITEMAPS):
        if not queue_urls:
            break
        url = queue_urls.pop(0)
        try:
            response = _get(url)
            if response.status_code >= 400:
                continue
            locs = _sitemap_locs(response.text)
        except requests.RequestException:
            continue
        for loc in locs:
            loc = _clean_url(loc, base)
            if not loc or not _same_site(loc, base):
                continue
            if loc.lower().endswith((".xml", "sitemap.xml")) and len(queue_urls) < MAX_SITEMAPS:
                if loc not in seen:
                    seen.add(loc); queue_urls.append(loc)
            else:
                product_urls.append(loc)
    return list(dict.fromkeys(product_urls))


def _is_product_candidate(url: str):
    """Aceita detalhe Magento/loja, inclusive /slug.html, sem assets."""
    parsed = urlparse(url)
    path = parsed.path.lower().strip("/")
    if not path or path.endswith(BAD_SUFFIXES):
        return False
    segments = [x for x in path.split("/") if x]
    if any(x in BAD_SEGMENTS for x in segments):
        return False
    # Magento e varias lojas B2B publicam o produto como /produto-slug.html.
    if path.endswith(".html"):
        return True
    markers = ("produto", "product", "item", "shop", "catalogo", "catalog")
    return any(marker in path for marker in markers) or len(segments) >= 2


def _record_from_page(url: str):
    try:
        final, soup, _ = _soup(url)
    except (requests.RequestException, ValueError):
        return None
    product = _first_jsonld(soup, "Product") or {}
    # Category pages also have h1 and many images. Only detail pages may become
    # products; this prevents a category page from becoming one fake SKU.
    body = soup.find("body")
    body_classes = set(body.get("class") or []) if body else set()
    is_listing = bool(soup.select(".product-item, .products-grid, .category-products"))
    is_detail = bool({"catalog-product-view", "product-info-main", "product-main-column"} & body_classes)
    is_detail = is_detail or bool(soup.select(".product-info-main, .product-main-column"))
    if is_listing and not is_detail:
        return None
    title_node = soup.find("h1") or soup.find("meta", attrs={"property": "og:title"})
    if hasattr(title_node, "get_text"):
        name = _text(title_node.get_text(" ", strip=True))
    else:
        name = _text(title_node.get("content")) if title_node else ""
    name = _text(product.get("name")) or name
    if not name or len(name) < 3:
        return None
    if any(x in name.lower() for x in ("contato", "política", "privacidade", "home", "início")):
        return None
    desc_node = soup.find("meta", attrs={"name": "description"})
    desc = _text(product.get("description")) or _text(desc_node.get("content") if desc_node else "")
    image = _image_candidates(soup, final, product)[0] if _image_candidates(soup, final, product) else ""
    if not image:
        return None
    return {
        "name": name[:160], "description": desc[:700] or f"{name} — produto apresentado no site da empresa.",
        "image": image, "category": _category(product, soup, final),
        "price": _price(product, soup), "url": final,
        "sku": _text(product.get("sku")),
    }


def _image_ok(url: str):
    try:
        response = _get(url, image=True, timeout=(8, 20))
        content_type = (response.headers.get("Content-Type") or "").lower()
        chunk = next(response.iter_content(2048), b"")
        return response.status_code == 200 and (content_type.startswith("image/") or len(chunk) > 1024)
    except requests.RequestException:
        return False


def _css_background_urls(soup: BeautifulSoup, base_url: str):
    """Extract remote background-image assets from inline CSS/GreatPages."""
    css = "\n".join(node.get_text(" ", strip=False) for node in soup.find_all("style"))
    urls = []
    for raw in re.findall(r"url\s*\(\s*[\"']?([^\)\"']+)", css, re.I):
        url = _clean_url(raw, base_url)
        if not url or url.startswith("data:") or url in urls:
            continue
        if re.search(r"\.(?:png|jpg|jpeg|webp)(?:\?|$)", url, re.I):
            urls.append(url)
    return urls


def _curamed_landing_records(soup: BeautifulSoup, base_url: str):
    """Products visibly displayed by Curamed's landing page.

    The page has no product URLs/JSON-LD; the cards are CSS backgrounds. The
    names below are transcribed from the product cards themselves and the image
    URL remains the original Curamed page asset.
    """
    host = (urlparse(base_url).hostname or "").lower()
    if "curamedph.com.br" not in host:
        return []
    assets = _css_background_urls(soup, base_url)
    by_name = {url.rsplit("/", 1)[-1]: url for url in assets}
    records = []
    for filename, name, brand, category in CURAMED_LANDING_PRODUCTS:
        image = by_name.get(filename)
        if not image:
            continue
        records.append({
            "name": name,
            "description": f"{name}, item exibido na pagina publica da Curamed; marca {brand}.",
            "image": image, "category": category, "price": None, "url": base_url,
            "sku": "", "source": "site", "similar": False,
        })
    return records


def _norm(value):
    raw = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def _title_case(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().title()[:80]


def _safe_slug(value):
    return re.sub(r"[^a-z0-9]+", "_", _norm(value)).strip("_") or "cliente"


KNOWN_HEALTH_BRANDS = (
    "CREMER", "MISSNER", "DESCARBOX", "RIOQUIMICA", "RIOQU?MICA",
    "MEDIX", "TECHNOFIO", "CAVILON", "3M", "MASCARO", "VIC PHARMA",
    "POLAR FIX", "MISSNER", "PROLINK", "KOLPLAST", "BIOLAND",
)


def _decode_search_href(href: str):
    """Unwrap Google/Bing result links without treating the search engine as source."""
    href = unescape(href)
    if href.startswith("/url?"):
        query = parse_qs(urlparse(href).query)
        return (query.get("q") or query.get("url") or [""])[0]
    if "bing.com/ck/a" in href:
        query = parse_qs(urlparse(href).query)
        encoded = unquote((query.get("u") or [""])[0])
        if encoded.startswith("a1"):
            try:
                raw = encoded[2:] + "=" * (-len(encoded[2:]) % 4)
                return base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
            except Exception:
                return ""
        return encoded
    return href


def _search_web(query: str, limite=12):
    """Busca URLs candidatas; o produto s? entra depois de ler a p?gina e a imagem."""
    encontrados = []
    engines = (
        "https://www.google.com/search?q=" + requests.utils.quote(query),
        "https://www.bing.com/search?q=" + requests.utils.quote(query),
    )
    for endpoint in engines:
        try:
            response = _get(endpoint, timeout=(10, 20))
            soup = BeautifulSoup(response.content, "html.parser")
            anchors = soup.select("li.b_algo h2 a") or soup.find_all("a", href=True)
            for anchor in anchors:
                href = _decode_search_href(anchor.get("href", ""))
                if not href.startswith(("http://", "https://")):
                    continue
                host = (urlparse(href).hostname or "").lower()
                if any(x in host for x in ("google.", "bing.", "duckduckgo.", "facebook.", "instagram.", "youtube.")):
                    continue
                href = _clean_url(href)
                if href and href not in encontrados:
                    encontrados.append(href)
                if len(encontrados) >= limite:
                    return encontrados
        except requests.RequestException:
            continue
    return encontrados


def _marcas_do_site(texto: str):
    upper = _norm(texto).upper()
    return [marca for marca in KNOWN_HEALTH_BRANDS if _norm(marca).upper() in upper]


def _search_fallback_products(pedido, data):
    """Busca primeiro produtos da marca; depois similares do segmento.

    Cada registro carrega `similar` e `source_note`; o resumo/callback avisa o
    Mitra. Nenhum nome ou imagem ? fabricado: s? entram p?ginas que responderam
    e cuja imagem foi validada.
    """
    cliente = _text(pedido.get("cliente"))
    segmento = _text(pedido.get("segmento")) or _text(data.get("title")) or _text(data.get("description")) or "produtos hospitalares"
    marcas = data.get("brands") or _marcas_do_site(data.get("page_text", ""))
    queries = [f'"{cliente}" produtos {segmento}']
    queries.extend(f'"{marca}" produtos {segmento}' for marca in marcas[:6])
    exatos, vistos = [], set()
    for query in queries:
        for url in _search_web(query, limite=12):
            if url in vistos:
                continue
            vistos.add(url)
            record = _record_from_page(url)
            if not record:
                continue
            text = _norm(record["name"] + " " + url).upper()
            is_brand = any(_norm(m).upper() in text for m in marcas)
            if is_brand:
                record["similar"] = False
                record["source_note"] = "produto encontrado em busca de marca/fonte externa"
                exatos.append(record)
            if len(exatos) >= MAX_PRODUTOS:
                return exatos[:MAX_PRODUTOS]
    similares = []
    for query in (
        f'"{segmento}" produtos hospitalares catalogo',
        f'{segmento} produtos para clinicas hospitais',
    ):
        for url in _search_web(query, limite=15):
            if url in vistos:
                continue
            vistos.add(url)
            record = _record_from_page(url)
            if not record:
                continue
            record["similar"] = True
            record["source_note"] = "produto similar do segmento; nao confirmado no catalogo da Curamed"
            similares.append(record)
            if len(similares) >= MAX_PRODUTOS:
                return similares[:MAX_PRODUTOS]
    return (exatos + similares)[:MAX_PRODUTOS]


def _site_data(site: str, pedido=None):
    site = _clean_url(site)
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    final, soup, home_text = _soup(site)
    base = f"{urlparse(final).scheme}://{urlparse(final).netloc}/"
    title = _text(soup.title.get_text(" ", strip=True) if soup.title else "")
    desc_node = soup.find("meta", attrs={"name": "description"})
    description = _text(desc_node.get("content") if desc_node else "")
    organization = _first_jsonld(soup, "Organization")
    logo = _logo(soup, final, organization)
    urls = _discover_sitemaps(base, home_text)
    links = []
    for a in soup.find_all("a", href=True):
        link = _clean_url(a.get("href"), final)
        if link and _same_site(link, base) and _is_product_candidate(link):
            links.append(link)
    ordered = list(dict.fromkeys([u for u in urls if _is_product_candidate(u)] + links))[:MAX_URLS]
    records = []
    if _first_jsonld(soup, "Product"):
        home_record = _record_from_page(final)
        if home_record:
            records.append(home_record)
    landing_records = _curamed_landing_records(soup, final)
    records.extend(landing_records)
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_record_from_page, url) for url in ordered]
        for future in as_completed(futures):
            try:
                record = future.result()
            except Exception:
                record = None
            if record:
                records.append(record)
    unique = []
    seen_names = set()
    for record in records:
        key = _norm(record["name"])
        if key and key not in seen_names:
            seen_names.add(key); unique.append(record)
    # Confere as imagens em paralelo e só entrega links que realmente existem.
    valid = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        checks = {pool.submit(_image_ok, r["image"]): r for r in unique}
        for future in as_completed(checks):
            if future.result():
                valid.append(checks[future])
    valid.sort(key=lambda r: unique.index(r))
    similar = False
    source_note = (
        "Produtos identificados nas imagens e textos da landing page publica da Curamed; "
        "precos nao estavam publicados." if landing_records else
        f"Catalogo extraido de {final}.")
    if len(valid) < MIN_PRODUTOS:
        fallback = _search_fallback_products(
            pedido or {"cliente": "", "site": final, "segmento": title},
            {"title": title, "description": description, "page_text": soup.get_text(" ", strip=True), "brands": _marcas_do_site(soup.get_text(" ", strip=True))})
        fallback_valid = []
        with ThreadPoolExecutor(max_workers=12) as pool:
            checks = {pool.submit(_image_ok, r["image"]): r for r in fallback}
            for future in as_completed(checks):
                if future.result():
                    fallback_valid.append(checks[future])
        fallback_valid.sort(key=lambda r: fallback.index(r))
        if fallback_valid:
            valid = (valid + fallback_valid)[:MAX_PRODUTOS]
            similar = any(r.get("similar") for r in valid)
            source_note = "Busca de fontes oficiais/marcas e, quando necess?rio, produtos similares do segmento."
    if len(valid) < MIN_PRODUTOS:
        raise ExtracaoFalhou(
            f"o site respondeu, mas so encontrei {len(valid)} produtos com imagem valida "
            f"(minimo {MIN_PRODUTOS}); nao vou inventar catalogo")
    return {
        "base": base, "final": final, "title": title, "description": description,
        "logo": logo, "products": valid[:MAX_PRODUTOS], "home": soup,
        "similar": similar,
        "brands": _marcas_do_site(soup.get_text(" ", strip=True)),
        "source_note": source_note,
    }


def _category_names(data):
    counts = Counter(_title_case(r.get("category")) for r in data["products"] if r.get("category"))
    names = [name for name, _ in counts.most_common() if _norm(name) not in {"produto", "produtos", "uncategorized"}]
    # Links de menu ajudam quando o JSON-LD nao declara category.
    for a in data["home"].find_all("a", href=True):
        text = _title_case(a.get_text(" ", strip=True))
        if 3 <= len(text) <= 60 and text not in names and _is_product_candidate(_clean_url(a.get("href"), data["final"])):
            names.append(text)
    lower = _norm(data["title"] + " " + data["description"] + " " + " ".join(r["name"] for r in data["products"]))
    if any(x in lower for x in ("farmacia", "medicamento", "hospital", "clinica", "saude")):
        fallback = ["Medicamentos e Produtos de Saude", "Higiene e Cuidados", "Suplementos e Nutricao"]
    elif any(x in lower for x in ("autopeca", "automotivo", "motor", "oficina")):
        fallback = ["Pecas e Componentes", "Manutencao Automotiva", "Ferramentas e Acessorios"]
    else:
        fallback = ["Produtos em Destaque", "Suprimentos e Acessorios", "Kits e Solucoes"]
    for name in fallback:
        if name not in names:
            names.append(name)
    return names[:3]


def _build_catalog(pedido, data):
    cliente = _text(pedido.get("cliente"))
    categories = _category_names(data)
    category_norm = {_norm(name): i for i, name in enumerate(categories)}
    products = []
    public_prices = 0
    for index, raw in enumerate(data["products"][:MAX_PRODUTOS], 1):
        cat = _norm(raw.get("category"))
        cat_idx = category_norm.get(cat, (index - 1) % 3)
        price = raw.get("price")
        if isinstance(price, (int, float)) and price > 0:
            public_prices += 1
        else:
            price = round(39.90 + index * 17.5, 2)
        sku = _safe_slug(raw.get("sku"))[:24].upper() if raw.get("sku") else f"{_safe_slug(cliente)[:10].upper()}-{index:03d}"
        if not sku or sku == "CLIENTE":
            sku = f"POC-{index:03d}"
        if (index - 1) % 4 == 0:
            minimum, multiple = 1, 1
        elif index % 3 == 0:
            minimum, multiple = 3, 6
        else:
            minimum, multiple = 10, 10
        name = raw["name"]
        products.append({
            "label": f"{sku} — {name}", "temp_image_url": raw["image"],
            "payload": {
                "name": name, "sku": sku, "description": raw["description"], "active": True,
                "stock": 100, "minimum_stock": 0, "standard_unit_id": 2, "images": [],
                "category_id": f"{{{{cat_ids_{cat_idx}}}}}", "brand_id": "{{brand_id}}",
                "ean_gtin": "", "video_url": "", "highlight": index in (1, 4, 7, 10),
                "price": price, "minimum_for_sale": minimum, "multiple_for_sale": multiple,
            },
        })

    today = date.today().isoformat()
    catalog = {
        "empresa": cliente, "descricao_empresa": data["description"] or data["title"] or f"{cliente} — catalogo B2B",
        "gerado_em": today, "setor": (data["title"] or "Comercio B2B")[:120],
        "portal_name": f"{cliente.upper()} POC", "portal_listing_rule_id": "{{criteria_listagem_id}}",
        "etapas": [
            {"nome": "1. MARCA", "endpoint": "brands", "requests": [{"label": f"Criar Marca {cliente}", "salvar_id_como": "brand_id", "payload": {"name": cliente, "active": True, "images": []}}]},
            {"nome": "2. CATEGORIAS", "endpoint": "categories", "requests": [
                {"label": name, "salvar_id_como": f"cat_ids_{i}", "payload": {"name": name, "active": True, "images": []}}
                for i, name in enumerate(categories)
            ]},
            {"nome": "3. PRODUTOS", "endpoint": "products", "requests": products},
        ],
    }
    criteria = [
        ("Criterio Marca (TABELA DE PRECO)", "criteria_preco_id", {"brands": {"config": None, "key": "this.CODIGOMARCA", "type": "FIELD", "values": ["{{brand_id}}"]}}),
        ("Criterio Marca (REGRA DE LISTAGEM)", "criteria_listagem_id", {"brands": {"config": None, "key": "this.CODIGOMARCA", "type": "FIELD", "values": ["{{brand_id}}"]}}),
    ]
    for i, name in enumerate(categories):
        criteria.append((f"Criterio Categoria (DESCONTO) - {name}", f"criteria_cat_{i}_id", {"categories": {"config": None, "key": "this.CODCATEGORIA", "type": "FIELD", "values": [f"{{{{cat_ids_{i}}}}}"]}}))
    catalog["etapas"].append({"nome": "4. CRITERIOS (separados: preco x listagem x desconto por categoria)", "endpoint": "criteria", "base_url": "https://api.zydon.com.br/api/database", "requests": [
        {"label": label + f" - {cliente}", "salvar_id_como": sid, "payload": {"name": f"{cliente} — {label.replace('Criterio ', '')}", "database_id": DATABASE_ID, "config": config}}
        for label, sid, config in criteria
    ]})
    catalog["etapas"].append({"nome": "5. TABELAS DE PRECO (usam o criterio de PRECO)", "endpoint": "price-tables", "requests": [
        {"label": f"Tabela {i} | {cliente}", "salvar_id_como": f"tp_{i}_id", "payload": {
            "name": f"Tabela {i} | {cliente}", "start_date": today, "end_date": "2060-01-01",
            "criteria": [{"criteria_id": "{{criteria_preco_id}}", "rate_type": "DECREASE", "value_type": "PERCENTAGE", "criteria_type": "FILTER", "value": value}],
            "is_profile_specific": True, "profiles": [{"profile_id": str(i + 1)}],
            "is_partner_specific": False, "partners": [], "is_company_specific": False, "companies": [],
            "is_payment_method_specific": False, "payment_methods": [],
        }} for i, value in enumerate((5, 20, 35), 1)
    ]})
    catalog["etapas"].append({"nome": "6. DESCONTOS", "endpoint": "discounts", "requests": [
        {"label": f"Desconto Progressivo — Volume {categories[0]}", "salvar_id_como": "desconto_progressivo_id", "payload": {
            "name": f"Progressivo Volume | {cliente} — {categories[0]}", "start_date": today, "end_date": "2060-01-01", "is_discount_over_discount": False, "is_active": True,
            "criteria": [{"name": f"Progressivo Volume {categories[0]}", "criteria_id": "{{criteria_cat_0_id}}", "type": "PROGRESSIVE", "criteria_type": "FILTER", "ranges": [
                {"minimum_quantity": 10, "type": "PERCENTAGE", "value": 5, "is_product_value": False}, {"minimum_quantity": 30, "type": "PERCENTAGE", "value": 9, "is_product_value": False}, {"minimum_quantity": 60, "type": "PERCENTAGE", "value": 14, "is_product_value": False}],
            }], "is_profile": True, "profiles": [{"profile_id": "4"}], "is_partner": False, "partners": [], "is_company": False, "companies": [], "is_payment_method": False, "payment_methods": [],
        }},
        {"label": f"Desconto Fixo 8% — {categories[1]} | {cliente}", "salvar_id_como": "desconto_fixo_id", "payload": {
            "name": f"8% OFF {cliente} — {categories[1]}", "start_date": today, "end_date": "2060-01-01", "is_discount_over_discount": False, "is_active": True,
            "criteria": [{"name": f"8% OFF {categories[1]}", "criteria_id": "{{criteria_cat_1_id}}", "type": "FIXED", "criteria_type": "FILTER", "ranges": [{"minimum_quantity": 0, "type": "PERCENTAGE", "value": 8, "is_product_value": False}]}],
            "is_profile": False, "profiles": [], "is_partner": False, "partners": [], "is_company": False, "companies": [], "is_payment_method": False, "payment_methods": [],
        }},
    ]})
    note = data.get("source_note") or f"Catalogo extraido de {data['final']}."
    if data.get("similar"):
        note += " Produtos similares ao segmento, nao confirmados no catalogo do cliente."
    summary = {
        "produtos": len(products), "categorias": 3, "fonte": "site",
        "preco": "publico" if public_prices == len(products) else "estimado",
        "imagens_substituidas": 0, "produtos_similares": bool(data.get("similar")),
        "observacoes": note,
    }
    return catalog, summary, data.get("logo") or None


def extrair(pedido):
    """Retorna (catalogo, resumo, logo_url) ou levanta ExtracaoFalhou."""
    data = _site_data(pedido.get("site", ""), pedido)
    return _build_catalog(pedido, data)
