"""Junta imagens candidatas num mosaico unico, para olhar todas de uma vez.

    python "Criar Portais/mosaico_imagens.py" --urls u1 u2 u3 ... [--saida m.png]
    python "Criar Portais/mosaico_imagens.py" "Arquivos Json/<cliente>_poc.json"

Existe por causa do tempo, e o custo e maior do que parece. Olhar imagem e a
unica parte da montagem que precisa de olho — e o que decide se a foto tem marca
de concorrente, embalagem errada ou produto trocado. O `verificar_imagens.py`
nao substitui isso: ele confere Content-Type e tamanho, nao o que esta na foto.

O problema e que cada imagem aberta separadamente e uma ida e volta inteira. Na
POC do Tudo do Mar (28/08/2026) foram sete, em quatro rodadas, e essa caca por
foto foi a maior fatia dos 12 minutos. Aqui as N viram uma imagem so, numerada:
uma ida, uma olhada, uma decisao sobre todas.

Cada celula leva o numero e o rotulo. Reprovada na conferencia mecanica (status,
Content-Type, tamanho) entra como celula vermelha com o motivo escrito — some do
mosaico seria pior, porque a numeracao deixaria de bater com a lista impressa.

Depois de escolher, rode o `verificar_imagens.py` no JSON pronto: ele e o portao
mecanico, este aqui e o olho.
"""

import argparse
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verificar_imagens import obter, urls_do_json  # noqa: E402

CELULA = 320
COLUNAS = 4
RODAPE = 34          # faixa do rotulo, embaixo de cada celula
PARALELISMO = 12
FUNDO = (250, 250, 250)
FUNDO_ERRO = (250, 226, 226)


def _fonte(tamanho):
    for nome in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def baixar(par):
    """(rotulo, url) -> (rotulo, url, Image|None, motivo)."""
    rotulo, url = par
    try:
        r = obter(url)
    except requests.RequestException as e:
        return rotulo, url, None, type(e).__name__
    if r.status_code != 200:
        return rotulo, url, None, f"HTTP {r.status_code}"
    tipo = (r.headers.get("Content-Type") or "").split(";")[0].strip()
    if len(r.content) < 1024:
        return rotulo, url, None, f"so {len(r.content)} bytes"
    try:
        # Abre pelos bytes, e nao pelo Content-Type: ha CDN que serve JPEG bom
        # como application/octet-stream. Aqui o que vale e o pixel — o MIME
        # errado e problema do upload, e quem acusa isso e o verificar_imagens.
        img = Image.open(io.BytesIO(r.content))
        img.load()
    except Exception as e:
        return rotulo, url, None, f"nao e imagem ({type(e).__name__}) [{tipo}]"
    return rotulo, url, img.convert("RGB"), ""


def montar(resultados, saida):
    total = len(resultados)
    colunas = min(COLUNAS, total)
    linhas = (total + colunas - 1) // colunas
    largura = colunas * CELULA
    altura = linhas * (CELULA + RODAPE)

    folha = Image.new("RGB", (largura, altura), (255, 255, 255))
    pincel = ImageDraw.Draw(folha)
    fonte = _fonte(15)

    for i, (rotulo, url, img, motivo) in enumerate(resultados):
        cx = (i % colunas) * CELULA
        cy = (i // colunas) * (CELULA + RODAPE)
        pincel.rectangle([cx, cy, cx + CELULA - 1, cy + CELULA - 1],
                         fill=FUNDO_ERRO if img is None else FUNDO)

        if img is not None:
            copia = img.copy()
            copia.thumbnail((CELULA - 12, CELULA - 12))
            folha.paste(copia, (cx + (CELULA - copia.width) // 2,
                                cy + (CELULA - copia.height) // 2))
        else:
            pincel.text((cx + 10, cy + CELULA // 2 - 8), motivo[:38],
                        fill=(150, 20, 20), font=fonte)

        pincel.rectangle([cx, cy + CELULA, cx + CELULA - 1, cy + CELULA + RODAPE - 1],
                         fill=(235, 235, 235))
        etiqueta = f"{i + 1}. {rotulo}"
        pincel.text((cx + 8, cy + CELULA + 9), etiqueta[:36],
                    fill=(20, 20, 20), font=fonte)
        pincel.rectangle([cx, cy, cx + CELULA - 1, cy + CELULA + RODAPE - 1],
                         outline=(200, 200, 200))

    saida.parent.mkdir(parents=True, exist_ok=True)
    folha.save(saida, "PNG", optimize=True)
    return folha.size


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("arquivo", nargs="?", help="o <cliente>_poc.json")
    p.add_argument("--urls", nargs="+", help="candidatas a olhar")
    p.add_argument("--rotulos", nargs="+",
                   help="nomes das candidatas, na mesma ordem de --urls")
    p.add_argument("--saida", default="Identidade Visual/saidas/mosaico.png")
    args = p.parse_args(argv)

    if args.urls:
        rotulos = args.rotulos or []
        pares = [(rotulos[i] if i < len(rotulos) else f"cand {i + 1}", u)
                 for i, u in enumerate(args.urls)]
    elif args.arquivo:
        pares = urls_do_json(args.arquivo)
    else:
        p.error("passe o JSON da POC ou --urls")

    if not pares:
        print("[ERRO] Nenhuma imagem para montar.")
        return 1

    with ThreadPoolExecutor(max_workers=PARALELISMO) as executor:
        resultados = list(executor.map(baixar, pares))

    saida = Path(args.saida)
    largura, altura = montar(resultados, saida)

    print(f"Mosaico: {saida}  ({largura}x{altura}, {len(resultados)} celulas)\n")
    for i, (rotulo, url, img, motivo) in enumerate(resultados, 1):
        marca = "  " if img is not None else "X "
        detalhe = f"{img.width}x{img.height}" if img is not None else motivo
        print(f"{marca}{i:2}. {rotulo[:38]:38} {detalhe:22} {url}")

    reprovadas = sum(1 for r in resultados if r[2] is None)
    if reprovadas:
        print(f"\n{reprovadas} nao abriram (celulas vermelhas).")
    print("\nAbra o mosaico UMA vez e decida todas de uma vez.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
