"""
descobrir_ids.py - Descobre os IDs que sao ESPECIFICOS de cada organizacao Zydon.

Motivo: standard_unit_id=2 e o database_id 5ba882ff-... sao validos nas orgs de
POC, mas nem sempre em org integrada a ERP (erros 404 MeasureUnit / 403 Database
doesn't belong to current organization). Rode isto ao configurar uma org nova e
transcreva o resultado para o dict ORGANIZACOES em `credenciais.py`.

Uso:
  python descobrir_ids.py sankhya
  python descobrir_ids.py            # usa 'sankhya' por padrao
"""

import os
import sys
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from credenciais import (  # noqa: E402
    ACCOUNT_BASE_URL,
    BASE_URL,
    DATABASE_BASE_URL,
    ORGANIZACOES,
    CredencialAusente,
    carregar,
)

# Os endpoints abaixo ja foram confirmados 200 — a lista de candidatos que este
# script varria virou constante. Se a API mudar e algum voltar 404, o probe
# reporta e ai vale procurar o novo caminho.
CANDIDATOS_UNIDADES = [f"{BASE_URL}/measure-units"]
CANDIDATOS_DATABASES = [f"{DATABASE_BASE_URL}/databases"]
CANDIDATOS_SOLUTIONS = [f"{ACCOUNT_BASE_URL}/solutions"]


def probe(nome, urls, headers):
    print(f"\n{'=' * 60}\n{nome}\n{'=' * 60}")
    achou = False
    for url in urls:
        try:
            r = requests.get(url, headers=headers,
                             params={"page": 0, "perPage": 200}, timeout=25)
        except Exception as e:
            print(f"  [ERR ] {url} -> {e}")
            continue
        if r.status_code != 200:
            print(f"  [{r.status_code}] {url}")
            continue
        achou = True
        print(f"  [200 ] {url}")
        try:
            data = r.json()
        except ValueError:
            print(f"        (resposta nao-JSON) {r.text[:200]}")
            continue
        itens = data.get("items", data) if isinstance(data, dict) else data
        if not isinstance(itens, list):
            print("        " + json.dumps(data, ensure_ascii=False)[:800])
            continue
        print(f"        {len(itens)} item(ns):")
        for it in itens[:40]:
            if isinstance(it, dict):
                resumo = {k: it[k] for k in
                          ("id", "name", "description", "abbreviation", "acronym", "code", "active")
                          if k in it}
                print("          " + json.dumps(resumo, ensure_ascii=False))
            else:
                print("          " + str(it))
    if not achou:
        print("  Nenhum endpoint respondeu 200 — me avise que eu procuro outro caminho.")


def main():
    chave = (sys.argv[1] if len(sys.argv) > 1 else "sankhya").lower()
    try:
        headers, _ = carregar(chave)
    except CredencialAusente as e:
        print(f"[ERRO] {e}")
        sys.exit(1)
    print(f"Organizacao: {chave}")
    probe("UNIDADES DE MEDIDA (para standard_unit_id)", CANDIDATOS_UNIDADES, headers)
    probe("DATABASES (para database_id dos criterios)", CANDIDATOS_DATABASES, headers)
    probe("SOLUTIONS / PORTAIS (para portal_origem_id)", CANDIDATOS_SOLUTIONS, headers)


if __name__ == "__main__":
    main()