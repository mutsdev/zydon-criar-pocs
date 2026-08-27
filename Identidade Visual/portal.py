"""Cliente da API de aparencia do portal Zydon: logo e favicon.

## A rota que funciona, e a que nao funciona

O OpenAPI do Zydon (`Zydon - B2B Admin`) anuncia dois endpoints dedicados:

    POST /api/b2b/portals/appearance/logo      campo `logo`
    POST /api/b2b/portals/appearance/favicon   campo `favicon`

**Eles nao funcionam.** Testado em 26/08/2026 contra um portal real: devolvem
HTTP 200 com corpo vazio e **nao mudam nada** — nem o `brand_image` da
aparencia, nem o conteudo do arquivo apontado por ele. O nome do campo esta
certo (mandar `file` ou `image` responde "Required part 'logo' is not
present"), entao nao e erro de chamada: o endpoint aceita e ignora.

A rota que funciona e a mesma que o `criar_poc.py` ja usa para imagem de
produto, em dois passos:

    1. POST /api/sales/resource-files   (campo `files`, chaves da ORG) -> file id
    2. PUT  /api/b2b/portals/appearance (JWT do portal) com o id no campo

Repare que os dois passos usam **credenciais diferentes**: o upload vai com as
chaves de acesso da organizacao no cabecalho; o PUT vai com o Bearer JWT
escopado no portal. Misturar os dois da 401 ou escreve no portal errado.

## Sobre o PUT

Ele leva o corpo inteiro (titulo, razao social, CNPJ, cor, botao flutuante...).
Mandar so o campo que mudou apaga o resto. Por isso `atualizar_aparencia`
obriga a passar a aparencia atual e faz a fusao aqui — nao ha caminho neste
modulo que monte um corpo do zero.

Detalhe que assusta e nao e problema: a **resposta** do PUT traz `has_shop` e
`enable_access_request` como `false` mesmo quando estao `true`. E o DTO de
resposta deles que nao reflete esses campos; um GET depois mostra que o estado
real nao mudou. Confira pelo GET, nunca pela resposta do PUT.
"""

import hashlib
import json
import time
from pathlib import Path

import requests

BASE_B2B = "https://api.zydon.com.br/api/b2b"
BASE_ACCOUNT = "https://api.zydon.com.br/api/account"
BASE_SALES = "https://api.zydon.com.br/api/sales"
BASE_FILES = "https://api.zydon.com.br/api/files/files"

# Campos que o PUT aceita. Serve para descartar o que o GET devolve e o PUT nao
# entende (`updated_at`, `has_shop`, `is_suspended`...) — mandar campo estranho
# e um 400 no meio de uma gravacao.
CAMPOS_DO_PUT = (
    "title", "billing_name", "fiscal_registration_number", "color",
    "brand_image", "favicon_image", "login_image", "extend_screen",
    "menu_guidance", "display_watermark", "floating_button", "tag_manager",
    "use_main_seller_phone_as_whatsapp_number", "is_open_to_public",
)


class ErroDoPortal(RuntimeError):
    """A API recusou. A mensagem carrega status e corpo, para dar para agir."""


def _levantar(resposta, acao):
    if resposta.status_code not in (200, 201, 204):
        raise ErroDoPortal(f"{acao}: HTTP {resposta.status_code} — "
                           f"{resposta.text[:300]}")
    return resposta


def entrar(code, token, portal_id, tentativas=3):
    """access-key/login escopado num portal. Devolve o Bearer JWT.

    `portal_id` e obrigatorio de proposito: sem ele o token nasce sem portal e
    as chamadas de aparencia respondem 404 sem dizer por que.
    """
    if not portal_id:
        raise ValueError("portal_id e obrigatorio — o JWT define em QUAL portal "
                         "a gravacao acontece.")
    for tentativa in range(1, tentativas + 1):
        resposta = requests.post(
            f"{BASE_ACCOUNT}/access-key/login",
            headers={"Content-Type": "application/json"},
            json={"code": code, "token": token, "solution_id": portal_id},
            timeout=60)
        if resposta.status_code >= 500 and tentativa < tentativas:
            time.sleep(3 * tentativa)
            continue
        _levantar(resposta, "login do portal")
        return resposta.json()["accessToken"]
    raise ErroDoPortal("login do portal: inalcancavel")


def _cabecalho(jwt):
    return {"Authorization": f"Bearer {jwt}"}


def obter_aparencia(jwt):
    """A aparencia atual do portal do JWT. E o ponto de partida de tudo."""
    resposta = requests.get(f"{BASE_B2B}/portals/appearance",
                            headers=_cabecalho(jwt), timeout=60)
    _levantar(resposta, "ler aparencia")
    return resposta.json()


def subir_arquivo(headers_org, caminho, mime="image/png"):
    """Sobe um arquivo e devolve o id do resource file.

    Usa as **chaves da organizacao**, nao o JWT do portal — e a mesma chamada
    que o criar_poc.py faz para imagem de produto. O Content-Type sai do
    cabecalho de proposito: o requests precisa definir o boundary do multipart.
    """
    caminho = Path(caminho)
    dados = caminho.read_bytes()
    sem_content_type = {k: v for k, v in headers_org.items()
                        if k.lower() != "content-type"}
    resposta = requests.post(f"{BASE_SALES}/resource-files",
                             headers=sem_content_type,
                             files={"files": (caminho.name, dados, mime)},
                             timeout=180)
    _levantar(resposta, f"subir {caminho.name}")
    arquivos = resposta.json().get("resourceFiles") or []
    if not arquivos:
        raise ErroDoPortal(f"subir {caminho.name}: resposta sem resourceFiles — "
                           f"{resposta.text[:200]}")
    return arquivos[0]["id"]


def corpo_do_put(aparencia_atual, mudancas):
    """Funde a aparencia atual com as mudancas e devolve o corpo do PUT.

    Existe separado para dar para INSPECIONAR antes de gravar (`--dry-run`) e
    para ser testavel sem rede. Descarta os campos que o GET devolve e o PUT
    nao aceita.
    """
    corpo = {c: aparencia_atual[c] for c in CAMPOS_DO_PUT if c in aparencia_atual}
    desconhecidos = set(mudancas) - set(CAMPOS_DO_PUT)
    if desconhecidos:
        raise ValueError(f"campos que o PUT nao aceita: {sorted(desconhecidos)}")
    corpo.update(mudancas)
    return corpo


def atualizar_aparencia(jwt, aparencia_atual, mudancas):
    """PUT com o corpo completo. Nunca monta corpo do zero — ver o modulo."""
    corpo = corpo_do_put(aparencia_atual, mudancas)
    resposta = requests.put(f"{BASE_B2B}/portals/appearance",
                            headers={**_cabecalho(jwt),
                                     "Content-Type": "application/json"},
                            json=corpo, timeout=120)
    _levantar(resposta, "gravar aparencia")
    return corpo


def conferir_no_ar(jwt, file_id, caminho_local):
    """Baixa o arquivo que o portal aponta e compara com o que foi enviado.

    E a checagem que pegou o endpoint dedicado mentindo: ele respondia 200 e
    nao trocava nada. Confiar no status da resposta nao basta — o unico teste
    honesto e buscar o byte que esta servido e comparar.
    """
    meta = requests.get(f"{BASE_FILES}/{file_id}", headers=_cabecalho(jwt),
                        timeout=60)
    _levantar(meta, "ler metadados do arquivo")
    dados = meta.json()
    baixado = requests.get(dados["url"], timeout=120)
    _levantar(baixado, "baixar arquivo servido")
    local = Path(caminho_local).read_bytes()
    return {
        "identico": (hashlib.sha256(baixado.content).hexdigest()
                     == hashlib.sha256(local).hexdigest()),
        "content_type": dados.get("content_type"),
        "bytes": dados.get("content_length"),
        "url": dados.get("url", "").split("?")[0],
    }


def salvar_backup(aparencia, destino):
    """Grava a aparencia anterior. E o unico caminho de volta se algo sair torto."""
    destino = Path(destino)
    destino.write_text(json.dumps(aparencia, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    return destino
