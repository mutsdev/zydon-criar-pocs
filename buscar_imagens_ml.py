"""
buscar_imagens_ml.py - Preenche image_url do skeleton buscando no Mercado Livre.

Le um {empresa}_images_skeleton.json (gerado pelo criar_poc.py/scriptTeste.py),
busca cada produto em lista.mercadolivre.com.br e preenche image_url com a
primeira imagem de card valida (-E.webp, fallback -V.webp). Nunca usa
-OO.webp/-A.webp (banners). Valida que a URL baixa de verdade (>1KB).

Uso:
  python buscar_imagens_ml.py empresa_images_skeleton.json
  python buscar_imagens_ml.py empresa_images_skeleton.json --forcar    (re-busca tambem as ja preenchidas)
  python buscar_imagens_ml.py empresa_images.json --validar            (so valida as URLs existentes, 1 a 1; limpa as quebradas)

Saida: atualiza o proprio arquivo. Produtos nao encontrados ficam com
image_url "" — preencher manualmente so esses.
"""

import json
import re
import sys
import time
import unicodedata

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
IMG_HEADERS = {**HEADERS, "Accept": "image/webp,image/*,*/*;q=0.8",
               "Referer": "https://www.mercadolivre.com.br/"}

# URLs de imagem de card do ML. Grupo do sufixo p/ priorizar -E sobre -V.
RE_IMG = re.compile(r"https://http2\.mlstatic\.com/D_(?:NQ_)?NP_(?:2X_)?[\w.\-]+?-([EV])\.webp")


def slug(texto):
    """Nome do produto -> slug de busca do ML (sem acentos/simbolos)."""
    # remove prefixo de SKU do label ("ABC-001 — Nome do Produto")
    if "—" in texto:
        texto = texto.split("—", 1)[1]
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^A-Za-z0-9 ]+", " ", texto)
    return "-".join(texto.split())


def url_valida(url):
    """Confere que a imagem baixa de verdade (nem todo match esta no ar)."""
    try:
        r = requests.get(url, headers=IMG_HEADERS, timeout=15)
        return r.status_code == 200 and len(r.content) > 1000
    except Exception:
        return False


def buscar_imagem(nome_produto):
    """Busca no ML e retorna a melhor URL de imagem, ou None."""
    termo = slug(nome_produto)
    if not termo:
        return None
    try:
        res = requests.get(f"https://lista.mercadolivre.com.br/{termo}",
                           headers=HEADERS, timeout=20)
    except Exception as e:
        print(f"    [ERRO] busca falhou: {e}")
        return None
    if res.status_code != 200:
        print(f"    [AVISO] busca status={res.status_code}")
        return None
    urls = [m.group(0) for m in RE_IMG.finditer(res.text)]
    # ordena: -E primeiro, mantendo a ordem da pagina
    candidatos = [u for u in urls if u.endswith("-E.webp")] + \
                 [u for u in urls if u.endswith("-V.webp")]
    vistos = set()
    for u in candidatos:
        if u in vistos:
            continue
        vistos.add(u)
        if url_valida(u):
            return u
    return None


def so_validar(path, itens):
    """Modo --validar: testa cada image_url preenchida; limpa as quebradas."""
    quebradas = []
    for item in itens:
        url = item.get("image_url")
        if not url:
            continue
        nome = item.get("_label") or item.get("product_id")
        if url_valida(url):
            print(f"[OK]      {nome}")
        else:
            print(f"[QUEBRADA] {nome} -> {url}")
            item["image_url"] = ""
            quebradas.append(nome)
        time.sleep(0.5)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(itens, f, indent=2, ensure_ascii=False)
    print(f"\n{len(quebradas)} URL(s) quebrada(s) foram limpas — preencher de novo so essas.")
    sys.exit(1 if quebradas else 0)


def main():
    if len(sys.argv) < 2:
        print("Uso: python buscar_imagens_ml.py arquivo.json [--forcar | --validar]")
        sys.exit(2)
    path = sys.argv[1]
    forcar = "--forcar" in sys.argv
    itens = json.load(open(path, encoding="utf-8"))
    if "--validar" in sys.argv:
        so_validar(path, itens)

    achou, faltou = 0, []
    for item in itens:
        nome = item.get("_label") or ""
        if item.get("image_url") and not forcar:
            continue
        print(f"Buscando: {nome}")
        url = buscar_imagem(nome)
        if url:
            item["image_url"] = url
            achou += 1
            print(f"    [OK] {url}")
        else:
            faltou.append(nome)
            print("    [NAO ENCONTRADO]")
        time.sleep(1.5)  # educado com o ML

    with open(path, "w", encoding="utf-8") as f:
        json.dump(itens, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 52)
    print(f"Preenchidos: {achou}  |  Sem imagem: {len(faltou)}")
    for n in faltou:
        print(f"  - {n}")
    if faltou:
        print("\nPreencher os faltantes manualmente e rodar update_imagens.py.")
    else:
        print("\nPronto: renomear para {empresa}_images.json e rodar update_imagens.py.")


if __name__ == "__main__":
    main()
