"""Acha os produtos de uma POC que ficaram sem imagem e repara so esses.

    python "Criar Portais/reparar_imagens.py" "Arquivos Json/<cliente>_poc.json"
    python "Criar Portais/reparar_imagens.py" "Arquivos Json/<cliente>_poc.json" pocs --gravar

Sem `--gravar` ele so lista. E de proposito: a lista e util sozinha, e o reparo
escreve em producao.

POR QUE ISTO PRECISA EXISTIR. Falha ao baixar a imagem **nao derruba a criacao**
— o produto e criado sem foto e a execucao segue. Foi decisao certa (perder o
catalogo inteiro por uma imagem seria pior), mas cria um buraco: o resumo final
diz "todas OK" e ninguem fica sabendo. Na Witop (01/09/2026), 7 de 12 produtos
nasceram sem imagem porque a rede da maquina oscilou no meio de uma execucao de
5h30 — e isso so apareceu quando alguem abriu o portal e olhou.

**NAO DEDUZA QUAIS CAIRAM PELO LOG.** O erro de imagem e impresso antes do [OK]
do produto afetado, entao a leitura pela ordem engana. Quem sabe e a API: este
script pergunta produto por produto se o campo `images` esta vazio.

A URL de reparo e a `temp_image_url` que ja esta no JSON da POC — casada pelo
NOME do produto, e nao pela posicao, porque a ordem de criacao nao e garantida.
"""

import argparse
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
COMPLETA = RAIZ / "POC Completa"
IDENTIDADE = RAIZ / "Identidade Visual"

for _caminho in (str(RAIZ), str(COMPLETA), str(IDENTIDADE)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Antes de `credenciais`: o .env com as chaves Zydon mora no Sales Ops.
import subir_identidade as _identidade  # noqa: E402

_identidade._carregar_env()

import credenciais  # noqa: E402
import criar_poc  # noqa: E402


def urls_por_nome(caminho_poc):
    """{nome do produto: temp_image_url} do JSON da POC."""
    poc = json.loads(Path(caminho_poc).read_text(encoding="utf-8-sig"))
    mapa = {}
    for etapa in poc.get("etapas", []):
        if etapa.get("endpoint") != "products":
            continue
        for req in etapa.get("requests", []):
            nome = (req.get("payload") or {}).get("name")
            if nome and req.get("temp_image_url"):
                mapa[nome] = req["temp_image_url"]
    return mapa


def produtos_criados(caminho_poc):
    """[(id, rotulo)] do <base>_criados.json, que o runner grava."""
    base = Path(caminho_poc).stem
    registro = Path(caminho_poc).parent / "saidas" / f"{base.replace('_poc', '')}_criados.json"
    if not registro.exists():
        raise SystemExit(
            f"[ERRO] Nao achei {registro}.\n"
            f"       Sem ele nao da para saber quais produtos esta POC criou —"
            f" e adivinhar pelo nome pegaria produto de outra execucao.")
    criados = json.loads(registro.read_text(encoding="utf-8"))
    return [(c[2], c[3]) for c in criados if len(c) > 3 and c[1] == "products"]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("arquivo", help="o <cliente>_poc.json")
    p.add_argument("org", nargs="?", default="pocs")
    p.add_argument("--gravar", action="store_true",
                   help="sobe as imagens que faltam. Sem isto, so lista.")
    args = p.parse_args(argv)

    try:
        headers, _ = credenciais.carregar(args.org)
    except credenciais.CredencialAusente as e:
        print(f"[ERRO] {e}")
        return 1

    mapa = urls_por_nome(args.arquivo)
    produtos = produtos_criados(args.arquivo)
    if not produtos:
        print("[ERRO] Nenhum produto criado registrado para esta POC.")
        return 1

    print(f"Conferindo {len(produtos)} produto(s) pela API...\n")
    faltando, nao_conferidos = [], []
    for pid, rotulo in produtos:
        res = criar_poc.request_with_retry(
            "GET", f"{criar_poc.BASE_URL}/products/{pid}", headers=headers)
        if res.status_code != 200:
            # "Nao consegui conferir" nao e "esta OK". Se essa linha se perde no
            # meio da lista, alguem conclui 6 quando sao 7 — entao ela volta a
            # aparecer no resumo. Aconteceu na Witop, com um 503 da API sob
            # carga de outra POC rodando ao mesmo tempo.
            print(f"  [?]   {pid}  HTTP {res.status_code} — nao consegui conferir")
            nao_conferidos.append((pid, rotulo))
            continue
        dados = res.json()
        nome = dados.get("name") or rotulo
        if dados.get("images"):
            print(f"  [OK]  {pid}  {nome[:58]}")
            continue
        url = mapa.get(nome)
        print(f"  [SEM] {pid}  {nome[:58]}"
              f"{'' if url else '   <- e nao ha temp_image_url no JSON'}")
        if url:
            faltando.append((pid, nome, url, dados))

    def avisar_nao_conferidos():
        if not nao_conferidos:
            return
        print(f"\n[ATENCAO] {len(nao_conferidos)} produto(s) nao pude conferir. "
              f"Rode de novo depois — isto nao quer dizer que estao OK:")
        for pid, rotulo in nao_conferidos:
            print(f"   {pid}  {rotulo[:58]}")

    if not faltando:
        print("\nNada a reparar.")
        avisar_nao_conferidos()
        return 1 if nao_conferidos else 0

    print(f"\n{len(faltando)} produto(s) sem imagem, todos com URL no JSON.")
    avisar_nao_conferidos()
    if not args.gravar:
        print("Rode de novo com --gravar para subir.")
        return 0

    reparados = 0
    for pid, nome, url, dados in faltando:
        print(f"\n  {nome[:60]}")
        file_id = criar_poc.upload_image_from_url(url, headers)
        if not file_id:
            print("    [FALHA] nao consegui subir a imagem — deixei como estava.")
            continue
        dados["images"] = [{"resource_file_id": file_id, "main": True}]
        # A API devolve estes campos no GET e recusa no PUT.
        for campo in ("id", "created_at", "updated_at", "brand", "category"):
            dados.pop(campo, None)
        res = criar_poc.request_with_retry(
            "PUT", f"{criar_poc.BASE_URL}/products/{pid}",
            headers={**headers, "Content-Type": "application/json"}, json=dados)
        if res.status_code in (200, 204):
            print("    [OK] imagem gravada.")
            reparados += 1
        else:
            print(f"    [FALHA] PUT {res.status_code}: {res.text[:180]}")

    print(f"\n{reparados}/{len(faltando)} reparado(s).")
    if reparados:
        print("Confira o efeito no portal, nao a resposta: abra e olhe.")
    return 0 if reparados == len(faltando) else 1


if __name__ == "__main__":
    raise SystemExit(main())
