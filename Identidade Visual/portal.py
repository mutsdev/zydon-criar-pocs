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


# A URL de um resource-file e ASSINADA (CloudFront: Expires + Signature +
# Key-Pair-Id na query). Duas consequencias que custaram uma tela quebrada em
# 03/09/2026, quando eu guardava so a parte antes do "?":
#
#   1. **Sem a query ela responde 403.** A assinatura E a autorizacao. Cortar o
#      "?" para deixar a URL "limpa" e cortar justamente o que faz ela abrir.
#   2. **Ela expira.** Medido: ~2h10 de validade. Serve para a curadoria da
#      sessao; nao serve para a tela ser reaberta amanha. Por isso o `expira_em`
#      viaja junto, e existe uma acao para pedir URL nova.
def _expira_em(url):
    """O `Expires` da URL assinada, em epoch. None se nao houver."""
    from urllib.parse import parse_qsl, urlparse
    for chave, valor in parse_qsl(urlparse(url).query):
        if chave == "Expires" and valor.isdigit():
            return int(valor)
    return None


def metadados_do_arquivo(jwt, file_id):
    """Os metadados do resource-file, com a URL assinada INTEIRA."""
    meta = requests.get(f"{BASE_FILES}/{file_id}", headers=_cabecalho(jwt),
                        timeout=60)
    _levantar(meta, "ler metadados do arquivo")
    return meta.json()


def conferir_no_ar(jwt, file_id, caminho_local):
    """Baixa o arquivo que o portal aponta e compara com o que foi enviado.

    E a checagem que pegou o endpoint dedicado mentindo: ele respondia 200 e
    nao trocava nada. Confiar no status da resposta nao basta — o unico teste
    honesto e buscar o byte que esta servido e comparar.
    """
    dados = metadados_do_arquivo(jwt, file_id)
    baixado = requests.get(dados["url"], timeout=120)
    _levantar(baixado, "baixar arquivo servido")
    local = Path(caminho_local).read_bytes()
    return {
        "identico": (hashlib.sha256(baixado.content).hexdigest()
                     == hashlib.sha256(local).hexdigest()),
        "content_type": dados.get("content_type"),
        "bytes": dados.get("content_length"),
        # `url` e a assinada, que ABRE. A outra fica ao lado, sem assinatura,
        # para log e comparacao — ela e estavel e a assinada muda a cada leitura.
        "url": dados.get("url", ""),
        "url_sem_assinatura": dados.get("url", "").split("?")[0],
        "expira_em": _expira_em(dados.get("url", "")),
    }


# ---------------------------------------------------------------------------
# Banners da home
# ---------------------------------------------------------------------------
# A aparencia expoe so tres campos de imagem — brand_image, favicon_image e
# login_image. A peca de 1920x320 nao cabe em nenhum deles: ela mora noutro
# recurso, `/api/b2b/banners`, que nao estava no modulo nem nas rotas que
# chutamos. Descoberto em 03/09/2026 lendo o spec `b2b - admin`.
#
# Medindo o byte que a plataforma serve hoje:
#     imageLarge  1920x320   desktop  <- o nosso cabecalho, encaixe exato
#     imageSmall   960x360   mobile
# Os dois sao **ids de resource-file**, os mesmos que `subir_arquivo` devolve.
#
# O portal novo nasce duplicado do base, entao ele JA TEM um "Banner principal".
# O certo e ler esse banner e devolver o corpo inteiro com as imagens trocadas
# — criar um segundo deixaria dois banners girando no carrossel, um com a arte
# do cliente e outro com a do portal de demonstracao.
CAMPOS_DO_PUT_BANNER = (
    "title", "type", "durationType", "start_date", "end_date", "active",
    "profile_partner", "profile_seller", "images", "group",
)

# O `id` da imagem entra de proposito: ele volta no GET, e devolve-lo no PUT e
# o que diz "atualize esta imagem" em vez de "crie outra". Omiti-lo na primeira
# versao teria sido a forma silenciosa de duplicar o slide.
CAMPOS_DA_IMAGEM = ("id", "description", "imageSmall", "imageLarge", "link",
                    "order", "active")


def listar_banners(jwt):
    """Os banners do portal do JWT.

    A resposta e um envelope paginado com a lista em **`items`** — medido em
    03/09/2026 contra o portal da Fornello:

        {"currentPage":0,"perPage":25,"total":1,"items":[{...}]}

    Cada item ja vem completo, com `images` dentro; nao e preciso um GET por
    banner so para ver o conteudo. As outras chaves ficam aceitas porque custam
    uma linha e um envelope diferente aqui viraria "o portal nao tem banner",
    que e uma mentira dificil de desconfiar.
    """
    resposta = requests.get(f"{BASE_B2B}/banners/banners", headers=_cabecalho(jwt),
                            timeout=60)
    _levantar(resposta, "listar banners")
    dados = resposta.json()
    if isinstance(dados, dict):
        for chave in ("items", "content", "banners"):
            if isinstance(dados.get(chave), list):
                return dados[chave]
        return []
    return dados or []


def obter_banner(jwt, banner_id):
    resposta = requests.get(f"{BASE_B2B}/banners/{banner_id}",
                            headers=_cabecalho(jwt), timeout=60)
    _levantar(resposta, f"ler banner {banner_id}")
    return resposta.json()


def corpo_do_banner(banner_atual, imagens):
    """Funde o banner atual com os ids novos e devolve o corpo do PUT.

    `imagens` e {"imageLarge": id, "imageSmall": id} — qualquer um dos dois
    pode faltar, e o que faltar fica como esta. Trocar so o desktop e o caso
    normal enquanto nao existe peca de 960x360.

    Como o PUT da aparencia, este leva o corpo inteiro: mandar so `images`
    zeraria titulo, periodo e perfis. E, como la, campo desconhecido levanta
    aqui em vez de virar 400 no meio de uma gravacao.
    """
    desconhecidos = set(imagens) - {"imageSmall", "imageLarge"}
    if desconhecidos:
        raise ValueError(f"campos que a imagem do banner nao aceita: "
                         f"{sorted(desconhecidos)}")

    corpo = {c: banner_atual[c] for c in CAMPOS_DO_PUT_BANNER
             if c in banner_atual}
    corpo.setdefault("group", [])

    atuais = list(banner_atual.get("images") or [])
    if not atuais:
        # Banner sem imagem nenhuma existe (alguem apagou a do portal base).
        # Criar a primeira e melhor que falhar: o resto do corpo ja e valido.
        atuais = [{"description": banner_atual.get("title", ""), "link": "",
                   "order": 1, "active": True}]

    # So a PRIMEIRA imagem e trocada. As outras sao slides que alguem pos a
    # mao, e sobrescreve-las seria decidir por essa pessoa.
    primeira = {c: atuais[0].get(c) for c in CAMPOS_DA_IMAGEM if c in atuais[0]}
    primeira.update({c: v for c, v in imagens.items() if v})
    corpo["images"] = [primeira] + [dict(i) for i in atuais[1:]]
    return corpo


def atualizar_banner(jwt, banner_id, banner_atual, imagens):
    """PUT com o corpo completo. Nunca monta corpo do zero — ver o modulo."""
    corpo = corpo_do_banner(banner_atual, imagens)
    resposta = requests.put(f"{BASE_B2B}/banners/{banner_id}",
                            headers={**_cabecalho(jwt),
                                     "Content-Type": "application/json"},
                            json=corpo, timeout=120)
    _levantar(resposta, f"gravar banner {banner_id}")
    return corpo


def url_do_arquivo(jwt, file_id):
    """(url_assinada, expira_em) de um resource-file.

    E o que o Mitra exibe na tela de curadoria. Servir a peca pelo tunel nao
    serve: o endereco do cloudflared e efemero e morre junto com o processo.

    A URL vem **inteira, com a assinatura** — ver o comentario acima. Ela vale
    ~2h; peca outra por aqui quando vencer, que o arquivo continua o mesmo.
    """
    dados = metadados_do_arquivo(jwt, file_id)
    url = dados.get("url") or ""
    return url, _expira_em(url)


def salvar_backup(aparencia, destino):
    """Grava a aparencia anterior. E o unico caminho de volta se algo sair torto."""
    destino = Path(destino)
    destino.write_text(json.dumps(aparencia, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    return destino
