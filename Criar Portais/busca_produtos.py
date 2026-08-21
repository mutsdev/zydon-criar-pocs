"""
busca_produtos.py - Varre uma faixa de IDs de produto e reporta os que existem.

Uso:
  python busca_produtos.py [organizacao] [id_inicial] [id_final]
  Ex.: python busca_produtos.py pocs 421 432

Antes a org se escolhia descomentando um bloco de HEADERS aqui no topo, e a
faixa de IDs estava fixa no __main__; agora ambos vem por argumento.
"""

import os
import sys

import requests
import time
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from credenciais import BASE_URL, selecionar  # noqa: E402

HEADERS, _ORG = selecionar(sys.argv[1] if len(sys.argv) > 1 else None)


def criar_session():
    """Cria uma session com retry automático para falhas de conexão."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,          # espera 2s, 4s, 8s entre tentativas
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def buscar_produto(session, p_id, tentativa=1, max_tentativas=4):
    """Busca um produto por ID com retry manual para 429 e erros de SSL."""
    url = f"{BASE_URL}/products/{p_id}"
    horario = datetime.now().strftime("%H:%M:%S")

    try:
        response = session.get(url, headers=HEADERS, timeout=15)

        if response.status_code == 200:
            p = response.json()
            sku = p.get("sku", "S/SKU")
            nome = p.get("name", "S/Nome")
            print(f"[{horario}] ✅ {sku} — {nome} → OK (ID: {p_id})")

        elif response.status_code == 429:
            espera = 2 ** tentativa  # backoff: 2s, 4s, 8s...
            print(f"[{horario}] ⚠️  Rate limit no ID {p_id}. Tentativa {tentativa}/{max_tentativas}. Aguardando {espera}s...")
            if tentativa < max_tentativas:
                time.sleep(espera)
                return buscar_produto(session, p_id, tentativa + 1, max_tentativas)
            else:
                print(f"[{horario}] ❌ ID {p_id} — rate limit persistente, pulando.")

        elif response.status_code == 404:
            pass  # ID não existe, ignora silenciosamente

        else:
            print(f"[{horario}] [!] ID {p_id} retornou erro {response.status_code}")

    except (requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ReadTimeout) as e:
        espera = 2 ** tentativa
        print(f"[{horario}] 🔌 Erro de conexão no ID {p_id} (tentativa {tentativa}/{max_tentativas}): {type(e).__name__}")
        if tentativa < max_tentativas:
            print(f"           Aguardando {espera}s antes de tentar novamente...")
            time.sleep(espera)
            return buscar_produto(session, p_id, tentativa + 1, max_tentativas)
        else:
            print(f"           ❌ ID {p_id} — falha após {max_tentativas} tentativas, pulando.")

    except Exception as e:
        print(f"[{horario}] [ERRO inesperado] ID {p_id}: {e}")

def busca_direta_por_id(inicio, fim):
    print(f"--- Iniciando busca direta de IDs ({inicio} até {fim}) ---\n")
    session = criar_session()
    pausa = 0.6

    for p_id in range(inicio, fim + 1):
        buscar_produto(session, p_id)
        time.sleep(pausa)  # pausa entre requisições

    print("\n--- Busca Finalizada ---")

if __name__ == "__main__":
    inicio = int(sys.argv[2]) if len(sys.argv) > 2 else 421
    fim = int(sys.argv[3]) if len(sys.argv) > 3 else 432
    busca_direta_por_id(inicio, fim)