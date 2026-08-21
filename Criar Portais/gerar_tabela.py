"""
gerar_tabela.py - Cria um criterio de marca + a tabela de preco que o usa.

Avulso: serve para acrescentar uma tabela de preco a uma POC que ja existe. Para
POC nova, isso ja sai da etapa 5 do criar_poc.py.

Uso:
  python gerar_tabela.py [organizacao]

Os parametros da tabela (empresa, marca, perfil, desconto, database) sao as
constantes abaixo — edite-as antes de rodar. Ficaram como constantes, e nao como
argumento, porque este script e de uso pontual e sempre foi assim; o que mudou e
que as chaves agora vem do .env e ele nao dispara mais no import.
"""

import os
import sys

import requests
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from credenciais import DATABASE_BASE_URL as DB_URL  # noqa: E402
from credenciais import BASE_URL as SALE_URL  # noqa: E402
from credenciais import selecionar  # noqa: E402

EMPRESA      = "Refrigeração Mota"
MARCA_ID     = "74"          # CODIGOMARCA
PERFIL_ID    = "2"           # Distribuidor
DESCONTO_PCT = 20
DATABASE_ID  = "d1f1222b-367b-4cc1-93f9-e32d5c511f70"

def log(msg, ok=True):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = "✅" if ok else "❌"
    print(f"[{ts}] {icon} {msg}")

def main(headers):
    # ─── ETAPA 1: Criar Criteria ───────────────────────────────────────────
    print("\n🔧 ETAPA 1 — Criando Criteria (Database API)")
    criteria_payload = {
        "name": EMPRESA,
        "database_id": DATABASE_ID,
        "config": {
            "brands": {
                "key": "this.CODIGOMARCA",
                "values": [MARCA_ID],
                "type": "FIELD",
                "config": None
            }
        }
    }

    resp = requests.post(f"{DB_URL}/criteria", headers=headers,
                         json=criteria_payload, timeout=20)

    if resp.status_code not in (200, 201):
        log(f"Erro ao criar criteria: {resp.status_code} — {resp.text[:200]}", ok=False)
        sys.exit(1)

    criteria_id = resp.json().get("id")
    log(f"Criteria criada — ID: {criteria_id}")

    # ─── ETAPA 2: Criar Tabela de Preço ───────────────────────────────────
    print("\n💰 ETAPA 2 — Criando Tabela de Preço (Sales API)")
    tp_payload = {
        "name": f"TP p/Seg. Distribuidor | {EMPRESA}",
        "start_date": "2026-01-01",
        "end_date": "2060-01-01",
        "criteria": [
            {
                "criteria_id": criteria_id,
                "rate_type": "DECREASE",
                "value_type": "PERCENTAGE",
                "criteria_type": "FILTER",
                "value": DESCONTO_PCT
            }
        ],
        "is_profile_specific": True,
        "profiles": [{"profile_id": PERFIL_ID}],
        "is_partner_specific": False,
        "partners": [],
        "is_company_specific": False,
        "companies": [],
        "is_payment_method_specific": False,
        "payment_methods": []
    }

    resp2 = requests.post(f"{SALE_URL}/price-tables", headers=headers,
                          json=tp_payload, timeout=20)

    if resp2.status_code not in (200, 201):
        log(f"Erro ao criar tabela: {resp2.status_code} — {resp2.text[:200]}", ok=False)
        sys.exit(1)

    tp_id = resp2.json().get("id")
    log(f"Tabela de preço criada — ID: {tp_id}")

    print(f"\n{'═'*55}")
    print(f"  Empresa   : {EMPRESA}")
    print(f"  Marca ID  : {MARCA_ID}")
    print(f"  Segmento  : Distribuidor (profile_id={PERFIL_ID})")
    print(f"  Desconto  : {DESCONTO_PCT}%")
    print(f"  criteria_id : {criteria_id}")
    print(f"  tp_id       : {tp_id}")
    print(f"{'═'*55}\n")


if __name__ == "__main__":
    HEADERS, _ORG = selecionar(sys.argv[1] if len(sys.argv) > 1 else None)
    main(HEADERS)