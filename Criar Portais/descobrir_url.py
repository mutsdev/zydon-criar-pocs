"""Descobre o endereco publico de um portal a partir do nome dele.

    python "Criar Portais/descobrir_url.py" "Aroca Mercearia POC"
    python "Criar Portais/descobrir_url.py" --json "Arquivos Json/<cliente>_poc.json"

Existe porque a API nao entrega o dominio: `/account/solutions` devolve so
`{id, name, type}`, a aparencia do portal traz cor e imagens mas nenhum
endereco, e `/portals/config` e `/portals/domains` nao existem. O que a
execucao devolve e o UUID — e UUID nao serve para o executivo comercial.

A regra e `<slug>.zydon.com.br`, com o slug sendo o nome sem acento, sem
espaco e sem pontuacao. Havendo colisao, entra um sufixo `-N`.

O QUE NAO SERVE DE PROVA: status HTTP e tamanho. O DNS e curinga, entao
`naoexisteportalzzz9.zydon.com.br` responde **200** igual a um portal de
verdade. Quem separa e o `<title>`:

  - portal que existe  -> o titulo e o nome exato do portal
  - subdominio livre   -> o titulo e "Portal do cliente" (a tela generica)

Medido em 28/08/2026: `arocamerceariapoc` estava ocupado por "A Roca
Mercearia POC" — nome diferente, mesmo slug — e por isso o portal do Aroca
nasceu em `arocamerceariapoc-2`. E o motivo de conferir o titulo, e nao so a
existencia: o vizinho de slug e outro cliente.

Sai com codigo 1 se nada casar em 6 tentativas (base + `-1` a `-5`). Nesse
caso o provavel e que o portal nao tenha sido criado.
"""

import argparse
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests

DOMINIO = "zydon.com.br"
TITULO_VAZIO = "Portal do cliente"
SUFIXOS_MAXIMOS = 5
TEMPO_LIMITE = 20


def slug(nome):
    """'Danda Auto Pecas POC' -> 'dandaautopecaspoc'."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


def titulo_de(subdominio):
    url = f"https://{subdominio}.{DOMINIO}/"
    try:
        html = requests.get(url, timeout=TEMPO_LIMITE).text
    except requests.RequestException as e:
        return url, f"[erro] {type(e).__name__}"
    achado = re.search(r"<title>(.*?)</title>", html, re.S)
    return url, (achado.group(1).strip() if achado else "")


def descobrir(nome_portal):
    """Devolve (url, ocupados) — url e None se nenhum candidato casar."""
    base = slug(nome_portal)
    candidatos = [base] + [f"{base}-{i}" for i in range(1, SUFIXOS_MAXIMOS + 1)]
    with ThreadPoolExecutor(max_workers=len(candidatos)) as executor:
        resultados = list(executor.map(titulo_de, candidatos))

    ocupados = []
    encontrados = []
    for (url, titulo), sub in zip(resultados, candidatos):
        if titulo == nome_portal:
            encontrados.append(url)
        elif titulo and titulo != TITULO_VAZIO and not titulo.startswith("[erro]"):
            ocupados.append((sub, titulo))

    if len(encontrados) > 1:
        # Dois portais com o mesmo nome. O chute pelo dominio nao resolve; quem
        # decide e quem olhar o catalogo dos dois.
        print(f"[AVISO] {len(encontrados)} portais com o nome '{nome_portal}': "
              + ", ".join(encontrados))
    return (encontrados[0] if encontrados else None), ocupados


def nome_do_json(caminho):
    with open(caminho, encoding="utf-8") as f:
        poc = json.load(f)
    return poc.get("portal_name") or poc.get("empresa")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("nome", nargs="?", help="o portal_name, exatamente como foi criado")
    p.add_argument("--json", dest="arquivo", help="le o portal_name do <cliente>_poc.json")
    p.add_argument("--silencioso", action="store_true",
                   help="imprime so a URL, para usar em script")
    args = p.parse_args(argv)

    nome = args.nome or (nome_do_json(args.arquivo) if args.arquivo else None)
    if not nome:
        p.error("passe o nome do portal ou --json <arquivo>")

    url, ocupados = descobrir(nome)

    if url:
        if args.silencioso:
            print(url)
        else:
            print(f"  Portal : {nome}")
            print(f"  URL    : {url}")
            for sub, titulo in ocupados:
                print(f"  (o slug '{sub}' e de outro portal: '{titulo}')")
        return 0

    print(f"[FALHA] Nenhum portal chamado '{nome}' em {slug(nome)}[-1..-{SUFIXOS_MAXIMOS}]."
          f"\n        O provavel e que a criacao tenha falhado — confira a execucao"
          f"\n        antes de procurar dominio.", file=sys.stderr)
    for sub, titulo in ocupados:
        print(f"        ('{sub}' esta ocupado por '{titulo}')", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
