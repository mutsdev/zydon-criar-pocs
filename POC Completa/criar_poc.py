"""
criar_poc.py - Automacao de POCs Zydon B2B.

Fluxo:
  1. Cria marca(s), categoria(s), produto(s) e criterio(s) a partir do JSON (etapas).
  2. Duplica o portal de origem da org (identifica o portal novo por DIFF - deterministico,
     funciona mesmo com varios portais de mesmo nome).
  3. Associa as categorias criadas ao portal novo.
  4. Aplica a Regra de Listagem nos 3 contextos do portal: Cliente, Vendedor e Vitrine.
  5. Salva {empresa}_ids.json (IDs capturados) e {empresa}_images_skeleton.json
     (esqueleto pronto p/ atualizar imagens depois, sem precisar anotar IDs manualmente).

Uso:
  python criar_poc.py arquivo.json [organizacao]
  Ex.: python criar_poc.py exemplo_poc.json pocs

JSON: ver template_poc.json. Placeholders {{chave}} sao resolvidos com os IDs
capturados via "salvar_id_como" e com {{run_ts}} (timestamp unico por execucao,
para nao empilhar objetos de mesmo nome). A regra de listagem e definida pela
chave top-level "portal_listing_rule_id" (ex.: "{{criteria_listagem_id}}", apontando
para o criterio criado numa etapa).

ATENCAO - IDs POR ORGANIZACAO (2026-08-11): standard_unit_id, database_id e
portal_origem_id NAO sao globais. Cada org tem os seus. Use descobrir_ids.py
numa org nova antes de rodar a POC.
"""

import json
import os
import sys
import time
from io import BytesIO
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from credenciais import (  # noqa: E402
    ACCOUNT_BASE_URL,
    APPCENTER_BASE_URL,
    BASE_URL,
    ORGANIZACOES,
    PORTALADMIN_BASE_URL,
    SOLUTIONS_URL,
    STANDARD_UNIT_ID_PADRAO,
    selecionar as selecionar_organizacao,
)

# ===========================================================================
# Configuracao
# ===========================================================================

# Sem User-Agent alguns CDNs bloqueiam o download da imagem.
IMG_DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "image/webp,image/avif,image/*,*/*;q=0.8",
}
CONVERTER_PARA_JPEG = True  # converte webp/png/etc para JPEG antes do upload


# ===========================================================================
# Infra
# ===========================================================================

# Sem timeout o requests espera para sempre: uma conexao pendurada travava a
# criacao da POC sem imprimir nada, e a unica saida era Ctrl+C.
TIMEOUT_PADRAO = 30


def request_with_retry(method, url, **kwargs):
    """Requisicao com retry/backoff no 429 (rate limit) e em falha de conexao."""
    kwargs.setdefault("timeout", TIMEOUT_PADRAO)
    wait = 15
    res = None
    for tentativa in range(5):
        try:
            res = requests.request(method, url, **kwargs)
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            # Rede oscilando as vesperas de uma demo nao pode derrubar a POC
            # inteira; tenta de novo antes de desistir.
            if tentativa == 4:
                raise
            print(f"[AVISO] {type(e).__name__} em {method} {url} — "
                  f"tentativa {tentativa + 1}/5, aguardando {wait}s...")
            time.sleep(wait)
            wait *= 2
            continue
        if res.status_code == 429:
            print(f"[AVISO] Rate limit. Aguardando {wait}s...")
            time.sleep(wait)
            wait *= 2
            continue
        return res
    return res


def resolve_placeholders(data, id_map):
    """Substitui {{chave}} pelos valores de id_map, recursivamente."""
    if isinstance(data, str):
        for key, value in id_map.items():
            data = data.replace(f"{{{{{key}}}}}", str(value))
        return data
    if isinstance(data, dict):
        return {k: resolve_placeholders(v, id_map) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_placeholders(i, id_map) for i in data]
    return data


def aplicar_unidade_padrao(data, unit_id):
    """Forca standard_unit_id = unit_id (o da ORG escolhida) em qualquer ponto
    do payload, ignorando o que estiver no JSON."""
    if isinstance(data, dict):
        return {k: (unit_id if k == "standard_unit_id" else aplicar_unidade_padrao(v, unit_id))
                for k, v in data.items()}
    if isinstance(data, list):
        return [aplicar_unidade_padrao(i, unit_id) for i in data]
    return data


def checar_database_ids(poc, headers):
    """Confere ANTES de criar qualquer coisa se o database_id dos criterios existe
    na org atual. Retorna False se algum for invalido — nesse caso a execucao e
    abortada sem criar nada (evita 403 nos criterios e a cascata de 400 em
    tabelas de preco/descontos, que deixaria lixo na org)."""
    ids = {r.get("payload", {}).get("database_id")
           for e in poc.get("etapas", [])
           for r in e.get("requests", [])
           if r.get("payload", {}).get("database_id")}
    if not ids:
        return True
    res = request_with_retry("GET", "https://api.zydon.com.br/api/database/databases",
                             headers=headers, params={"page": 0, "perPage": 200})
    if res.status_code != 200:
        print(f"[AVISO] Nao foi possivel listar databases ({res.status_code}) - seguindo mesmo assim.")
        return True
    validos = {d.get("id"): d.get("name") for d in res.json().get("items", [])}
    ok = True
    for db_id in sorted(ids):
        if db_id in validos:
            print(f"[INFO] database_id OK: {db_id} ('{validos[db_id]}')")
            continue
        ok = False
        produtos = next((i for i, n in validos.items() if n == "Produtos"), None)
        print(f"[ERRO] database_id {db_id} NAO pertence a esta organizacao.")
        if produtos:
            print(f"       A base 'Produtos' desta org e: {produtos}")
            print(f"       Troque no JSON: \"database_id\": \"{produtos}\"")
    if not ok:
        print("[ABORTADO] Nada foi criado. Corrija o JSON e rode de novo.")
    return ok



# ===========================================================================
# Rollback (desfaz o que a execucao criou)
# ===========================================================================
# Cada criacao bem-sucedida e registrada em `criados` como
# (base_url, endpoint, id, label). O rollback apaga em ordem INVERSA, porque
# ha dependencia: produto referencia categoria/marca, tabela de preco
# referencia criterio, etc.

def deletar_objeto(base_url, endpoint, obj_id, headers):
    """DELETE {base_url}/{endpoint}/{id}. Retorna True se apagou (ou se ja nao existia)."""
    res = request_with_retry("DELETE", f"{base_url}/{endpoint}/{obj_id}", headers=headers)
    if res.status_code in (200, 202, 204):
        return True
    if res.status_code == 404:
        return True  # ja nao existe — objetivo cumprido
    print(f"    [FALHA] DELETE {endpoint}/{obj_id}: {res.status_code} - {res.text[:150]}")
    return False


def rollback(criados, headers):
    """Apaga tudo que foi criado nesta execucao, em ordem inversa.
    Retorna a lista do que NAO deu para apagar (para o usuario limpar a mao)."""
    if not criados:
        print("\n[ROLLBACK] Nada foi criado — nada a desfazer.")
        return []
    print(f"\n{'=' * 52}\n[ROLLBACK] Desfazendo {len(criados)} objeto(s) criado(s)...")
    restaram = []
    for base_url, endpoint, obj_id, label in reversed(criados):
        if deletar_objeto(base_url, endpoint, obj_id, headers):
            print(f"  [OK] apagado {endpoint}/{obj_id} — {label}")
        else:
            restaram.append((base_url, endpoint, obj_id, label))
        time.sleep(0.3)
    if restaram:
        print(f"\n[ROLLBACK] {len(restaram)} objeto(s) NAO foram apagados — remova a mao:")
        for _, endpoint, obj_id, label in restaram:
            print(f"  - {endpoint} ID {obj_id} ({label})")
    else:
        print("[ROLLBACK] Concluido - a organizacao ficou limpa.")
    return restaram


def caminho_saida(file_path, sufixo):
    """
    Devolve o caminho de um arquivo DERIVADO da POC `file_path`.

    Os derivados (_ids, _images_skeleton, _criados) sao gerados pelo script, nao
    escritos a mao — vao para "Arquivos Json/saidas/" em vez de se misturarem com
    os JSONs de entrada. Antes eram gravados ao lado da fonte, e as duas coisas
    ficaram indistinguiveis numa pasta de 400 arquivos.

    A pasta e criada sob demanda; se a criacao falhar, cai de volta para o lado
    do arquivo de entrada, que e o comportamento antigo — salvar no lugar
    subotimo e melhor que perder os IDs de uma POC ja criada na API.
    """
    base = os.path.splitext(os.path.basename(file_path))[0]
    if base.endswith("_poc"):
        base = base[:-4]
    destino = os.path.join(os.path.dirname(os.path.abspath(file_path)), "saidas")
    try:
        os.makedirs(destino, exist_ok=True)
    except OSError as e:
        print(f"[AVISO] Nao foi possivel criar '{destino}' ({e}) — "
              f"gravando ao lado do JSON de entrada.")
        destino = os.path.dirname(os.path.abspath(file_path))
    return os.path.join(destino, f"{base}{sufixo}.json")


def limpar_de_arquivo(file_path, headers):
    """Modo --limpar: apaga o que ficou de uma execucao anterior, lendo o
    {base}_criados.json gravado por ela."""
    caminho = caminho_saida(file_path, "_criados")
    if not os.path.exists(caminho):
        # POCs criadas antes da pasta saidas/ gravavam o registro ao lado do
        # JSON de entrada. Sem este fallback, --limpar nao acha o que apagar.
        base = os.path.splitext(os.path.abspath(file_path))[0]
        if base.endswith("_poc"):
            base = base[:-4]
        antigo = f"{base}_criados.json"
        if os.path.exists(antigo):
            print(f"[INFO] Usando registro antigo em '{antigo}'.")
            caminho = antigo
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            criados = [tuple(x) for x in json.load(f)]
    except FileNotFoundError:
        print(f"[ERRO] '{caminho}' nao encontrado — nao ha registro do que apagar.")
        return False
    except Exception as e:
        print(f"[ERRO] Nao foi possivel ler '{caminho}': {e}")
        return False
    print(f"[INFO] {len(criados)} objeto(s) registrados em {caminho}")
    restaram = rollback(criados, headers)
    try:
        if restaram:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump([list(x) for x in restaram], f, indent=2, ensure_ascii=False)
        else:
            os.remove(caminho)
    except Exception as e:
        print(f"[AVISO] Falha ao atualizar '{caminho}': {e}")
    return not restaram


def salvar_saidas_pos_execucao(file_path, id_map, produtos_criados, criados=None):
    """Grava {base}_ids.json (todos os IDs capturados) e {base}_images_skeleton.json
    (product_id + _label prontos p/ preencher image_url) em Arquivos Json/saidas/."""
    caminho_ids = caminho_saida(file_path, "_ids")
    try:
        with open(caminho_ids, "w", encoding="utf-8") as f:
            json.dump(id_map, f, indent=2, ensure_ascii=False)
        print(f"[INFO] IDs salvos em {caminho_ids}")
    except Exception as e:
        print(f"[AVISO] Falha ao salvar {caminho_ids}: {e}")
    if produtos_criados:
        skeleton = [{"product_id": str(pid), "image_url": "", "_label": label}
                    for label, pid in produtos_criados]
        caminho_skeleton = caminho_saida(file_path, "_images_skeleton")
        try:
            with open(caminho_skeleton, "w", encoding="utf-8") as f:
                json.dump(skeleton, f, indent=2, ensure_ascii=False)
            print(f"[INFO] Esqueleto de imagens salvo em {caminho_skeleton}")
        except Exception as e:
            print(f"[AVISO] Falha ao salvar esqueleto de imagens: {e}")
    if criados:
        # registro para o modo --limpar (rollback manual depois)
        caminho_criados = caminho_saida(file_path, "_criados")
        try:
            with open(caminho_criados, "w", encoding="utf-8") as f:
                json.dump([list(x) for x in criados], f, indent=2, ensure_ascii=False)
            print(f"[INFO] Registro de objetos criados em {caminho_criados}")
        except Exception as e:
            print(f"[AVISO] Falha ao salvar registro de criados: {e}")


# ===========================================================================
# Imagens
# ===========================================================================

def baixar_imagem(image_url):
    """Baixa a imagem (com User-Agent) e valida. Retorna (bytes, mime, fname)."""
    parsed = urlparse(image_url)
    headers = {**IMG_DOWNLOAD_HEADERS, "Referer": f"{parsed.scheme}://{parsed.netloc}/"}
    resp = requests.get(image_url, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"download status={resp.status_code}")
    if len(resp.content) < 1000:
        raise RuntimeError(f"download retornou {len(resp.content)} bytes (provavel bloqueio)")
    content = resp.content
    url_clean = image_url.lower().split("?")[0]
    if url_clean.endswith(".webp"):
        fname, mime = "image.webp", "image/webp"
    elif url_clean.endswith(".png"):
        fname, mime = "image.png", "image/png"
    elif url_clean.endswith(".gif"):
        fname, mime = "image.gif", "image/gif"
    else:
        fname, mime = "image.jpg", "image/jpeg"
    if CONVERTER_PARA_JPEG and mime != "image/jpeg":
        try:
            from PIL import Image
            img = Image.open(BytesIO(content)).convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=90)
            content, fname, mime = buf.getvalue(), "image.jpg", "image/jpeg"
        except ImportError:
            print("  [AVISO] Pillow nao instalado - enviando original. (pip install Pillow)")
        except Exception as e:
            print(f"  [AVISO] Falha ao converter para JPEG ({e}) - enviando original.")
    return content, mime, fname


def upload_image_from_url(url, headers):
    """Baixa a imagem de uma URL e sobe para o Zydon. Retorna o resource_file_id ou None."""
    try:
        img_data, mime, fname = baixar_imagem(url)
        files = {"files": (fname, img_data, mime)}
        upload_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        res = request_with_retry("POST", f"{BASE_URL}/resource-files",
                                 headers=upload_headers, files=files)
        if res.status_code in (200, 201):
            return res.json()["resourceFiles"][0]["id"]
        print(f"  [FALHA] Upload de imagem: {res.status_code} - {res.text[:200]}")
    except Exception as e:
        print(f"  [ERRO] Upload de imagem: {e}")
    return None


# ===========================================================================
# Portal: duplicacao + categorias
# ===========================================================================

def listar_solution_ids(headers):
    """Conjunto de IDs de todos os portais (solutions) da org."""
    res = request_with_retry("GET", SOLUTIONS_URL, headers=headers)
    if res.status_code != 200:
        print(f"  [AVISO] Nao foi possivel listar portais: {res.status_code}")
        return set()
    return {s.get("id") for s in res.json().get("items", [])}


def duplicar_portal(portal_origem_id, nome, cor, headers):
    """Duplica o portal de origem e retorna o UUID do portal novo (ou None).
    Identifica o novo portal por DIFF da lista de solutions (antes vs depois),
    o que e deterministico mesmo havendo varios portais com o mesmo nome."""
    ids_antes = listar_solution_ids(headers)
    if portal_origem_id not in ids_antes and ids_antes:
        print(f"  [AVISO] portal_origem_id {portal_origem_id} nao esta entre os portais "
              f"desta org ({len(ids_antes)} encontrado(s)). Confira com descobrir_ids.py — "
              f"o valor tem que vir de /api/account/solutions, NAO e o organization_id.")
    url = f"{APPCENTER_BASE_URL}/solutions/{portal_origem_id}/duplicate-async"
    res = request_with_retry("POST", url, headers=headers, json={"name": nome, "color": cor})
    if res.status_code not in (200, 201):
        print(f"  [FALHA] Duplicar portal: {res.status_code} - {res.text[:200]}")
        return None
    print("  [INFO] Duplicacao iniciada - aguardando conclusao...")
    status_url = f"{APPCENTER_BASE_URL}/solutions/{portal_origem_id}/duplicate-async/status"
    for _ in range(30):  # ~90s
        time.sleep(3)
        st = request_with_retry("GET", status_url, headers=headers)
        if st.status_code != 200:
            continue
        status = st.json().get("status", "").upper()
        if status in ("COMPLETED", "SUCCEEDED"):
            time.sleep(2)  # tempo para o portal novo aparecer na listagem
            novos = listar_solution_ids(headers) - ids_antes
            if len(novos) == 1:
                novo = next(iter(novos))
                print(f"  [OK] Portal novo: {novo}")
                return novo
            print(f"  [FALHA] Diff retornou {len(novos)} portais novos ({novos}) - "
                  f"nao da para identificar com seguranca.")
            return None
        if status in ("FAILED", "ERROR"):
            print(f"  [FALHA] Duplicacao falhou: {st.json()}")
            return None
    print("  [FALHA] Timeout aguardando duplicacao (90s).")
    return None


def associar_categorias_ao_portal(categorias_criadas, portal_id, headers):
    """Inclui o portal novo em 'solutions' de cada categoria criada."""
    print(f"  Associando {len(categorias_criadas)} categoria(s) ao portal...")
    for cat_id, cat_payload in categorias_criadas:
        put_payload = {
            "name": cat_payload["name"],
            "root_id": cat_payload.get("root_id") or "",
            "active": cat_payload.get("active", True),
            "is_solution_specific": True,
            "solutions": [portal_id],
        }
        res = request_with_retry("PUT", f"{BASE_URL}/categories/{cat_id}",
                                 headers=headers, json=put_payload)
        if res.status_code in (200, 201):
            print(f"  [OK] Categoria '{cat_payload['name']}' associada")
        else:
            print(f"  [FALHA] Associar '{cat_payload['name']}': "
                  f"{res.status_code} - {res.text[:200]}")
        time.sleep(0.5)


# ===========================================================================
# Regra de listagem (Cliente, Vendedor, Vitrine)
# ===========================================================================
# Para cada portal, cada contexto tem seu proprio modelo de pedido:
#   Cliente  : GET /portaladmin/new-orders/partners -> [ativo].id
#   Vendedor : GET /portaladmin/new-orders/sellers  -> [ativo].id
#   Vitrine  : GET /portaladmin/portals/shop        -> shop_new_order_id
# O save e identico nos 3 (read-modify-write):
#   GET  /portaladmin/new-orders/{model}              -> config = model.product.list
#   PUT  /portaladmin/new-orders/{model}/product-list -> config com listing_rule_id trocado

def obter_jwt_portal(headers, portal_id):
    """access-key/login -> Bearer JWT escopado no portal (solution_id=portal_id).

    Recebe `headers` (e nao `org`) porque este e o unico ponto em que code/token
    vao no CORPO do POST, e nao no cabecalho: desde que as credenciais passaram a
    sair do .env, o dict `org` guarda so o que nao e segredo.
    """
    res = request_with_retry(
        "POST", f"{ACCOUNT_BASE_URL}/access-key/login",
        headers={"Content-Type": "application/json"},
        json={"code": headers["X-Zydon-Access-Key-Code"],
              "token": headers["X-Zydon-Access-Key-Token"],
              "solution_id": portal_id},
    )
    if res.status_code != 200:
        print(f"  [FALHA] Login do portal: {res.status_code} - {res.text[:200]}")
        return None
    return res.json().get("accessToken")


def _model_de_endpoint(jwt, endpoint):
    """GET /new-orders/{endpoint} (partners=Cliente, sellers=Vendedor) -> id do model ativo."""
    res = request_with_retry("GET", f"{PORTALADMIN_BASE_URL}/new-orders/{endpoint}",
                             headers={"Authorization": f"Bearer {jwt}"})
    if res.status_code != 200 or not res.json():
        return None
    modelos = res.json()
    return (next((m for m in modelos if m.get("active")), None) or modelos[0]).get("id")


def obter_models_contextos(jwt):
    """{Cliente, Vendedor, Vitrine} -> model_id (cada um pode ser None)."""
    H = {"Authorization": f"Bearer {jwt}"}
    vit = None
    rs = request_with_retry("GET", f"{PORTALADMIN_BASE_URL}/portals/shop", headers=H)
    if rs.status_code == 200:
        vit = rs.json().get("shop_new_order_id")
    return {
        "Cliente": _model_de_endpoint(jwt, "partners"),
        "Vendedor": _model_de_endpoint(jwt, "sellers"),
        "Vitrine": vit,
    }


def aplicar_regra_no_model(H, model_id, criterio_id, contexto=""):
    """Read-modify-write da regra em UM model. Retorna True se aplicou e verificou."""
    pre = f"  [{contexto}]"
    res = request_with_retry("GET", f"{PORTALADMIN_BASE_URL}/new-orders/{model_id}", headers=H)
    if res.status_code != 200:
        print(f"{pre} [FALHA] GET modelo: {res.status_code} - {res.text[:150]}")
        return False
    try:
        config = res.json()["product"]["list"]
    except (KeyError, TypeError, ValueError):
        print(f"{pre} [FALHA] model.product.list nao encontrado.")
        return False

    config["listing_rule_id"] = criterio_id  # criterio_id=None limpa a regra

    res = request_with_retry("PUT", f"{PORTALADMIN_BASE_URL}/new-orders/{model_id}/product-list",
                             headers=H, json=config)
    if res.status_code not in (200, 201):
        print(f"{pre} [FALHA] PUT product-list: {res.status_code} - {res.text[:150]}")
        return False

    res = request_with_retry("GET", f"{PORTALADMIN_BASE_URL}/new-orders/{model_id}", headers=H)
    atual = res.json().get("product", {}).get("list", {}).get("listing_rule_id") \
        if res.status_code == 200 else None
    if atual == criterio_id:
        print(f"{pre} [OK] Regra aplicada (criterio: {criterio_id or '(limpa)'})")
        return True
    print(f"{pre} [AVISO] PUT OK mas verificacao nao bateu (atual={atual}).")
    return False


def configurar_regra_listagem(headers, portal_id, criterio_id):
    """Aplica a regra de listagem nos 3 contextos do portal.
    Retorna True se todos os contextos existentes aplicaram."""
    jwt = obter_jwt_portal(headers, portal_id)
    if not jwt:
        return False
    H = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    models = obter_models_contextos(jwt)
    algum, ok = False, True
    for ctx in ("Cliente", "Vendedor", "Vitrine"):
        mid = models.get(ctx)
        if not mid:
            print(f"  [{ctx}] [INFO] contexto nao encontrado - pulando.")
            continue
        algum = True
        if not aplicar_regra_no_model(H, mid, criterio_id, ctx):
            ok = False
    if not algum:
        print("  [FALHA] Nenhum contexto de model encontrado no portal.")
        return False
    return ok


# ===========================================================================
# Fluxo principal
# ===========================================================================

def run_poc(file_path, headers, org, rollback_on_error=True, saida=None):
    """Executa a POC inteira. Retorna True se tudo concluiu sem falhas.
    Em caso de falha, apaga tudo que criou (a menos que rollback_on_error=False).

    `saida`, se vier, recebe o UUID do portal novo em saida['portal_id'].
    UNICA diferenca desta copia para 'Criar Portais/criar_poc.py'.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            poc = json.load(f)
    except Exception as e:
        print(f"[ERRO] Nao foi possivel ler '{file_path}': {e}")
        return False

    # {{run_ts}}: sufixo unico por execucao, p/ nomes nao colidirem entre rodadas.
    id_map = {"run_ts": time.strftime("%Y%m%d-%H%M%S")}
    unit_id = org.get("standard_unit_id", STANDARD_UNIT_ID_PADRAO)
    categorias_criadas = []
    produtos_criados = []
    criados = []  # (base_url, endpoint, id, label) — para o rollback
    falhas = 0

    empresa = resolve_placeholders(poc.get("empresa", "(sem nome)"), id_map)
    print(f"Iniciando POC: {empresa}  [run_ts={id_map['run_ts']}]")
    print(f"[INFO] standard_unit_id desta org: {unit_id}")
    if not checar_database_ids(poc, headers):
        return False

    # 1) Etapas (marca, categorias, produtos, criterios, ...)
    for etapa in poc.get("etapas", []):
        endpoint = etapa.get("endpoint")
        print(f"\nEtapa: {etapa.get('nome', endpoint)}")
        base_url = etapa.get("base_url", BASE_URL)
        for req in etapa.get("requests", []):
            label = req.get("label", "Requisicao")
            payload = aplicar_unidade_padrao(
                resolve_placeholders(req["payload"], id_map), unit_id)
            if req.get("temp_image_url") and endpoint == "products":
                file_id = upload_image_from_url(req["temp_image_url"], headers)
                if file_id:
                    payload["images"] = [{"resource_file_id": file_id, "main": True}]
            res = request_with_retry("POST", f"{base_url}/{endpoint}",
                                     headers={**headers, "Content-Type": "application/json"},
                                     json=payload)
            if res.status_code in (200, 201):
                new_id = res.json().get("id")
                print(f"  [OK] {label} (ID: {new_id})")
                if new_id:
                    criados.append((base_url, endpoint, new_id, label))
                if req.get("salvar_id_como"):
                    id_map[req["salvar_id_como"]] = new_id
                if endpoint == "categories" and new_id:
                    categorias_criadas.append((new_id, payload))
                if endpoint == "products" and new_id:
                    produtos_criados.append((label, new_id))
            else:
                falhas += 1
                print(f"  [FALHA] {label}: {res.status_code} - {res.text[:200]}")
                if rollback_on_error:
                    # Parar aqui: os proximos requests dependem deste ID e so
                    # produziriam erros em cascata (400 de placeholder nao resolvido).
                    print("  [INFO] Interrompendo — os proximos passos dependem deste objeto.")
                    salvar_saidas_pos_execucao(file_path, id_map, produtos_criados, criados)
                    rollback(criados, headers)
                    return False
            time.sleep(1)

    # Salva IDs + esqueleto de imagens (mesmo com falhas parciais / falha no portal).
    salvar_saidas_pos_execucao(file_path, id_map, produtos_criados, criados)

    if falhas and rollback_on_error:
        print(f"\n[AVISO] {falhas} falha(s) nas etapas acima.")
        rollback(criados, headers)
        return False

    # 2) Duplicacao do portal
    portal_origem_id = org.get("portal_origem_id")
    if not portal_origem_id:
        print("\n[INFO] portal_origem_id nao configurado - pulando portal e regra de listagem.")
        return falhas == 0

    if falhas:
        print(f"\n[AVISO] {falhas} falha(s) nas etapas acima - duplicar o portal agora "
              f"criaria um portal incompleto. Corrija e rode de novo.")
        return False

    portal_nome = resolve_placeholders(poc.get("portal_name") or poc.get("empresa", "Novo Portal"), id_map)
    portal_cor = poc.get("portal_color") or org.get("portal_cor", "#4A90D9")
    print(f"\nEtapa: Duplicar portal '{portal_nome}'")
    novo_portal_id = duplicar_portal(portal_origem_id, portal_nome, portal_cor, headers)
    if not novo_portal_id:
        print("[AVISO] Duplicacao falhou - categorias e regra de listagem nao aplicadas.")
        if rollback_on_error:
            rollback(criados, headers)
        return False

    # O id precisa sobreviver a chamada: quem sobe a identidade visual depois
    # so tem este caminho. O _ids.json ja foi gravado antes desta etapa, e o
    # id do portal nao esta nele.
    if saida is not None:
        saida["portal_id"] = novo_portal_id

    # 3) Associar categorias
    if categorias_criadas:
        print("\nEtapa: Associar categorias ao portal")
        associar_categorias_ao_portal(categorias_criadas, novo_portal_id, headers)

    # 4) Regra de listagem (Cliente, Vendedor, Vitrine)
    print("\nEtapa: Configurar regra de listagem (Cliente, Vendedor, Vitrine)")
    regra_ok = configurar_regra_da_poc(poc, novo_portal_id, headers, id_map)

    print("\n" + "=" * 52)
    print("CONCLUIDO")
    print(f"  Portal novo    : {novo_portal_id}")
    print(f"  Etapas         : {'todas OK' if falhas == 0 else str(falhas) + ' falha(s)'}")
    print(f"  Regra listagem : {'OK' if regra_ok else 'FALHOU/parcial'}")
    return falhas == 0 and regra_ok


def configurar_regra_da_poc(poc, portal_id, headers, id_map):
    """Le o criterio de poc['portal_listing_rule_id'] (aceita {{placeholders}}) e
    aplica a regra nos 3 contextos. Retorna True se aplicou (ou se nao ha regra
    definida); False se foi definida mas nao pode ser resolvida/aplicada."""
    raw = poc.get("portal_listing_rule_id")
    if not raw:
        print("  [INFO] Sem 'portal_listing_rule_id' no JSON - regra de listagem ignorada.")
        return True
    criterio_id = resolve_placeholders(raw, id_map)
    if not criterio_id or "{{" in str(criterio_id):
        print(f"  [FALHA] 'portal_listing_rule_id' nao resolvido ('{raw}'). "
              f"O criterio referenciado foi criado numa etapa (salvar_id_como)?")
        return False
    print(f"  [INFO] Criterio: {criterio_id}")
    return configurar_regra_listagem(headers, portal_id, criterio_id)


def _uso():
    print("Uso:")
    print("  python criar_poc.py arquivo.json [organizacao]")
    print("  python criar_poc.py --limpar arquivo.json [organizacao]   # apaga o que")
    print("      uma execucao anterior criou (le o {base}_criados.json)")
    print()
    print("Flags:")
    print("  --sem-rollback   nao apaga nada em caso de erro (comportamento antigo)")
    print(f"\nOrganizacoes: {', '.join(ORGANIZACOES.keys())}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    modo_limpar = "--limpar" in argv
    rollback_on_error = "--sem-rollback" not in argv
    posicionais = [a for a in argv if not a.startswith("--")]

    if not posicionais:
        _uso()
        sys.exit(1)

    arquivo = posicionais[0]
    org_chave = posicionais[1] if len(posicionais) > 1 else None
    headers_, org_ = selecionar_organizacao(org_chave)

    if modo_limpar:
        sys.exit(0 if limpar_de_arquivo(arquivo, headers_) else 1)
    sys.exit(0 if run_poc(arquivo, headers_, org_, rollback_on_error) else 1)