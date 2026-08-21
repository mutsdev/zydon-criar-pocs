"""
listar.py - Lista perfis, categorias e tabelas de preco de uma organizacao.

Uso:
  python listar.py [organizacao]     # ex.: python listar.py pocs

Antes a org se escolhia descomentando um bloco de HEADERS aqui no topo; agora
vem do argumento e as chaves saem do .env via credenciais.py.
"""

import os
import sys

import requests
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from credenciais import BASE_URL, selecionar  # noqa: E402

HEADERS, _ORG = selecionar(sys.argv[1] if len(sys.argv) > 1 else None)


def listar_perfis():
    print("\n====== PERFIS (Segmentos) ======")
    resp = requests.get(f"{BASE_URL}/profiles?perPage=100", headers=HEADERS)
    data = resp.json()
    items = data.get("items", data if isinstance(data, list) else [])
    for p in items:
        print(f"  ID: {p.get('id')}  |  Nome: {p.get('name')}  |  Ativo: {p.get('active')}")
    return items

def listar_categorias():
    print("\n====== CATEGORIAS ======")
    resp = requests.get(f"{BASE_URL}/categories?perPage=100", headers=HEADERS)
    data = resp.json()
    items = data.get("items", data if isinstance(data, list) else [])
    for p in items:
        print(f"  ID: {p.get('id')}  |  Nome: {p.get('name')}")
    return items

def listar_tabelas():
    print("\n====== TABELAS DE PREÇO ======")
    resp = requests.get(f"{BASE_URL}/price-tables?perPage=50", headers=HEADERS)
    data = resp.json()
    items = data.get("items", [])
    for t in items:
        print(f"  ID: {t.get('id')}  |  Nome: {t.get('name')}  |  Início: {t.get('start_date', '')[:10]}")
    return items

def detalhar_tabela(tabela_id):
    print(f"\n====== DETALHE TABELA {tabela_id} ======")
    resp = requests.get(f"{BASE_URL}/price-tables/{tabela_id}", headers=HEADERS)
    data = resp.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    perfis = listar_perfis()
    tabelas = listar_tabelas()
    categorias = listar_categorias()

    # Se houver tabelas, detalha a primeira pra ver a estrutura dos critérios
    if tabelas:
        detalhar_tabela(52)