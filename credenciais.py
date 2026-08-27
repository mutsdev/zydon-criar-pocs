"""
Fonte única das credenciais e dos IDs por organização Zydon.

Antes disso, os quatro pares de chaves viviam copiados em sete arquivos .py.
Não era só feio: as cópias **divergiram**. O `criar_poc.py` foi atualizado com
as chaves novas de `zydon` e `sankhya`, e os outros seis arquivos continuaram
com as antigas — que pertencem a outra organização
(019e6f55-6cf3-7354-b8d6-de0753c2f186) e criaram uma POC da Amet invisível no
front, em 11/08/2026. Rodar o script errado escrevia na org errada, em silêncio.

Aqui as chaves saem de um `.env` que NUNCA é versionado, com nomes
ZYDON_<ORG>_CODE / ZYDON_<ORG>_TOKEN. O que **não** é segredo — portal de
origem, unidade de medida, cor — fica versionado aqui em claro, porque é
configuração e muda junto com o código que a usa.

Caminho absoluto, derivado do arquivo: nenhum script daqui deve montar caminho
relativo nem depender de onde foi chamado.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# O .env mora AO LADO deste arquivo (pasta autocontida). Se não existir,
# tenta um nível acima — layout de quando a pasta vive dentro de um repositório
# maior que centraliza o .env na raiz.
AQUI = Path(__file__).resolve().parent
RAIZ = AQUI if (AQUI / ".env").exists() else AQUI.parent

load_dotenv(RAIZ / ".env")


# ==========================================
# Organizações
# ==========================================
# Só o que não é segredo mora aqui. As chaves entram em `carregar()`, do .env.
#
#   portal_origem_id : UUID do portal (solution) base p/ duplicação.
#                      None = pula duplicação + regra de listagem.
#                      Descobrir com: GET /api/account/solutions
#   standard_unit_id : unidade de medida padrão dos produtos. Orgs de POC usam o
#                      inteiro 2; orgs integradas a ERP usam UUID próprio.
#                      Descobrir com: GET /api/sales/measure-units
#   (o database_id dos critérios também é por org, mas vem no JSON da POC:
#    GET /api/database/databases -> base "Produtos")
ORGANIZACOES = {
    "zydon": {
        "nome": "Apresentação Zydon",
        "portal_origem_id": None,
        "portal_cor": "#000000",
        "standard_unit_id": 2,
    },
    "poc": {
        "nome": "Apresentação POC",
        "portal_origem_id": None,
        "portal_cor": "#000000",
        "standard_unit_id": 2,
    },
    "pocs": {
        "nome": "Apresentação POCs",
        "portal_origem_id": "3b5403e6-de03-4ff5-a1d3-ad91f3875928",
        "portal_cor": "#000000",
        "standard_unit_id": 2,
    },
    # Org 019ec802-8eb8-7f1e-9dfd-87440804b3e1 ("integracoes") — a que aparece no
    # front do Sankhya B2B: lojas AGROMINAS (integracoes-2) e Portal Base.
    # Confirmado em 2026-08-11 decodificando o JWT do access-key/login.
    "sankhya": {
        "nome": "Sankhya B2B",
        # Loja "Portal Base" (portalbase.zydon.com.br) — o portal base p/ duplicação.
        # A outra loja da org é "integracoes" = a4b3e043-1110-4921-922b-af409807e1be.
        # Deixe None se quiser rodar SÓ o catálogo, sem duplicar portal.
        "portal_origem_id": "8bc03a66-7415-47ab-a8fd-cc7dcd0086e1",
        "portal_cor": "#000000",
        # Aqui o inteiro 2 EXISTE ("Unidade (UN) = 2"), então vale o padrão.
        # Outras: CX=a23e921e-03e2-4f3b-8082-fe6efb8048a6,
        #         KG=44609356-2d4d-4a10-89ab-368349d5ba11,
        #         PLT=723c1f20-c476-4cc2-a0e4-7c7cd92976bd
        "standard_unit_id": 2,
    },
}

# Fallback para org sem "standard_unit_id" configurado (orgs de POC).
STANDARD_UNIT_ID_PADRAO = 2

# ==========================================
# Endpoints
# ==========================================
BASE_URL = "https://api.zydon.com.br/api/sales"
APPCENTER_BASE_URL = "https://api.zydon.com.br/api/appcenter"
ACCOUNT_BASE_URL = "https://api.zydon.com.br/api/account"
DATABASE_BASE_URL = "https://api.zydon.com.br/api/database"
PORTALADMIN_BASE_URL = "https://api.zydon.com.br/api/portaladmin"
SOLUTIONS_URL = f"{ACCOUNT_BASE_URL}/solutions?page=0&perPage=500"


class CredencialAusente(RuntimeError):
    """Faltou chave no .env. A mensagem diz qual variável definir."""


def carregar(chave):
    """
    Devolve (headers, org) para a organização `chave`.

    `headers` já vem com Content-Type: application/json — para upload de arquivo,
    remova-o (o requests precisa definir o boundary do multipart).

    Levanta CredencialAusente se a org não existe ou se falta chave no .env.
    Falhar aqui é melhor que sair com header vazio e receber 401 no meio de uma
    POC pela metade.
    """
    if chave not in ORGANIZACOES:
        disponiveis = ", ".join(ORGANIZACOES)
        raise CredencialAusente(
            f"Organização '{chave}' não existe. Disponíveis: {disponiveis}"
        )

    org = ORGANIZACOES[chave]
    var_code = f"ZYDON_{chave.upper()}_CODE"
    var_token = f"ZYDON_{chave.upper()}_TOKEN"
    code = os.getenv(var_code)
    token = os.getenv(var_token)

    faltando = [v for v, valor in ((var_code, code), (var_token, token)) if not valor]
    if faltando:
        raise CredencialAusente(
            f"Faltam variáveis no .env para a org '{chave}': {', '.join(faltando)}.\n"
            f"O arquivo é {RAIZ / '.env'} — veja poc-portais/.env.example."
        )

    headers = {
        "Content-Type": "application/json",
        "X-Zydon-Access-Key-Code": code,
        "X-Zydon-Access-Key-Token": token,
    }
    return headers, org


def selecionar(chave=None):
    """
    Como `carregar`, mas pergunta a org no terminal quando `chave` não veio.

    Usada pelos entrypoints que aceitam a org como argumento opcional. Sai com
    código 1 em vez de propagar exceção: quem chama é o `__main__` de um script.
    """
    if chave not in ORGANIZACOES:
        if chave:
            print(f"[AVISO] Organização '{chave}' não encontrada.")
        print("\nOrganizações disponíveis:")
        for k, v in ORGANIZACOES.items():
            print(f"  {k:12} → {v['nome']}")
        chave = input("\nEscolha a organização: ").strip().lower()

    try:
        headers, org = carregar(chave)
    except CredencialAusente as e:
        print(f"[ERRO] {e}")
        sys.exit(1)

    print(f"[INFO] Usando: {org['nome']}")
    return headers, org
