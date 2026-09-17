"""Verifica todas as temp_image_url de uma POC de uma vez, em paralelo.

    python "Criar Portais/verificar_imagens.py" "Arquivos Json/<cliente>_poc.json"
    python "Criar Portais/verificar_imagens.py" --urls url1 url2 url3

Existe por causa do tempo: a verificacao feita uma URL por vez custa uma ida a
rede E uma volta do modelo para cada produto. Em 28/08/2026, 13 imagens
verificadas assim foram parte visivel dos 11 minutos de uma execucao. Aqui sao
todas juntas, num comando so.

O que reprova, e por que cada um ja aconteceu de verdade:

  - status != 200                  link que morreu depois que o site mudou
  - Content-Type nao e image/*     pagina de erro HTML respondendo 200, e o CDN
                                   que serve JPEG como application/octet-stream
  - corpo menor que 1 KB           placeholder ou resposta vazia

Sai com codigo 1 se qualquer uma reprovar, para servir de portao.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

# Sem User-Agent alguns CDNs bloqueiam o download — mesma razao do criar_poc.py.
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "image/webp,image/avif,image/*,*/*;q=0.8",
}
BYTES_MINIMOS = 1024
PARALELISMO = 12


def obter(url, **kw):
    """GET com os cabecalhos da casa. Seam unico para mosaico e verificador.

    Ja teve retry com backoff aqui (14/09/2026) por "CDN recusa rajada":
    diagnostico errado. O 400/404 vinha de URL com \r no fim — arquivo
    gravado em modo texto no Windows e lido com $(cat) no bash. Sequencial
    "funcionava" porque o teste em processo fazia .split(). Nao e o CDN.
    """
    return requests.get(url, headers=CABECALHOS, timeout=30, **kw)


def urls_do_json(caminho):
    """Devolve [(rotulo, url)] de todo produto com temp_image_url."""
    with open(caminho, encoding="utf-8") as f:
        poc = json.load(f)
    achados = []
    for etapa in poc.get("etapas", []):
        if etapa.get("endpoint") != "products":
            continue
        for req in etapa.get("requests", []):
            url = req.get("temp_image_url")
            rotulo = req.get("payload", {}).get("name") or req.get("label", "?")
            if url:
                achados.append((rotulo, url))
    return achados


def _tipo_pelos_bytes(b):
    if b[:3] == bytes.fromhex("ffd8ff"):
        return "image/jpeg"
    if b[:8] == bytes.fromhex("89504e470d0a1a0a"):
        return "image/png"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return None


def conferir(par):
    rotulo, url = par
    try:
        # stream=True: le o cabecalho e so o comeco do corpo. Baixar a imagem
        # inteira so para saber se ela existe seria desperdicio numa POC de 15.
        with obter(url, stream=True) as r:
            tipo = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            tamanho = int(r.headers.get("Content-Length") or 0)
            inicio = next(r.iter_content(BYTES_MINIMOS + 1), b"")
            if not tamanho:
                tamanho = len(inicio)
            if r.status_code != 200:
                return (rotulo, url, False, f"HTTP {r.status_code}")
            if not tipo.startswith("image/"):
                # Header ausente ou octet-stream: o que vale e o byte. O runner
                # decide o MIME pela extensao e converte para JPEG, entao um
                # webp real sem Content-Type (Roto Fermax, 17/09/2026) sobe bem.
                farejado = _tipo_pelos_bytes(inicio)
                if not farejado:
                    return (rotulo, url, False, f"Content-Type '{tipo or 'ausente'}' e bytes nao sao imagem")
                tipo = f"{farejado} (farejado; header '{tipo or 'ausente'}')"
            if tamanho < BYTES_MINIMOS:
                return (rotulo, url, False, f"so {tamanho} bytes")
            return (rotulo, url, True, f"{tipo}  {tamanho} bytes")
    except requests.RequestException as e:
        return (rotulo, url, False, type(e).__name__)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("arquivo", nargs="?", help="o <cliente>_poc.json")
    p.add_argument("--urls", nargs="+", help="conferir estas URLs em vez do JSON")
    args = p.parse_args(argv)

    if args.urls:
        pares = [(f"url {i + 1}", u) for i, u in enumerate(args.urls)]
    elif args.arquivo:
        pares = urls_do_json(args.arquivo)
    else:
        p.error("passe o JSON da POC ou --urls")

    if not pares:
        print("[ERRO] Nenhuma temp_image_url encontrada.")
        return 1

    with ThreadPoolExecutor(max_workers=PARALELISMO) as executor:
        resultados = list(executor.map(conferir, pares))

    reprovadas = [r for r in resultados if not r[2]]
    for rotulo, url, ok, detalhe in resultados:
        if not ok:
            print(f"  [FALHA] {rotulo[:48]}\n          {detalhe} — {url}")

    print(f"\n{len(resultados) - len(reprovadas)}/{len(resultados)} imagens OK")
    if reprovadas:
        print(f"{len(reprovadas)} reprovada(s): troque a fonte destas antes de entregar.")
        return 1
    print("Todas passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
