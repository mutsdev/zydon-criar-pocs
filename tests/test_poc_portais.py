"""
Testes da POC de portais.

Existem por causa de um prejuízo concreto: os quatro pares de chaves viviam
copiados em sete arquivos .py, as cópias divergiram, e as chaves antigas de
"sankhya" — que ainda estavam em seis deles — apontavam para outra organização.
Uma POC da Amet foi criada lá e ficou invisível no front. Nada no código
detectava isso.

O que fica travado aqui:
  1. credencial nenhuma volta a ser escrita no código (a regressão que dói);
  2. falta de chave falha alto, e não com header vazio e 401 no meio da POC;
  3. os arquivos gerados vão para saidas/, sem se misturar com as fontes;
  4. o --limpar ainda acha os registros de POCs criadas antes dessa separação.

Nada aqui toca a rede.
"""

import importlib.util
import json
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Até 20/08/2026 estes testes viviam no repositório de Sales Ops e o código
# ficava em `poc-portais/`, uma pasta gitignored — testavam algo que não existia
# num clone limpo. Aqui o código É a raiz, e por isso as duas variáveis
# coincidem. `POC_PORTAIS` fica como nome porque é usado em vinte lugares.
POC_PORTAIS = RAIZ

# Os scripts não moram em src/, então não entram pelo pythonpath do pytest.
sys.path.insert(0, POC_PORTAIS)

credenciais = pytest.importorskip(
    "credenciais", reason="credenciais.py não encontrado na raiz"
)


def _carregar_criar_poc():
    """Importa 'Criar Portais/criar_poc.py', cujo nome de pasta tem espaço."""
    caminho = os.path.join(POC_PORTAIS, "Criar Portais", "criar_poc.py")
    spec = importlib.util.spec_from_file_location("criar_poc", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ==========================================
# 1. Nenhuma credencial no código
# ==========================================

# Chaves que já estiveram hardcoded, incluindo as que apontavam para a org
# errada. Nenhuma pode reaparecer em arquivo versionado.
CREDENCIAIS_CONHECIDAS = [
    "923f941d-40cc-482a-8bf8-a5ffd8da4ab7", "6a79405b-ec0e-4e98-a3a1-11ed453ec198",
    "96f3a6b2-4b4c-48b4-ad47-109803d2e27a", "5b9f12f3-5540-413e-a69f-6049bc65f45d",
    "f62a7b30-2eff-4d4a-95ee-dc27fb725fc9", "6953ac61-e6a6-4055-9f02-64d0b5eb814b",
    "0e5830f0-d138-4f20-8c26-7a17e2ef1122", "04bb2575-ce27-4532-bd2f-8baf6140ad14",
    "88bdd07d-38ac-4650-aeae-fe0d0269d866", "5dd6db04-fc12-4f7b-a709-89f47cb85422",
    "d6d5a7e2-63e5-4983-856d-156c98556e6b", "8fa65258-1d89-4ae7-ba87-4606b0668ac2",
]


def _arquivos_py():
    """
    Os .py do projeto, sem `tests/`.

    A exclusão não é comodidade: a lista `CREDENCIAIS_CONHECIDAS` vive neste
    arquivo, então varrer `tests/` faria o teste acusar a si mesmo. Antes de
    20/08/2026 o código ficava em `poc-portais/` e os testes num repositório
    separado, e a colisão não existia.
    """
    for pasta, _, arquivos in os.walk(POC_PORTAIS):
        if "__pycache__" in pasta or os.path.basename(pasta) == "tests":
            continue
        for nome in arquivos:
            if nome.endswith(".py"):
                yield os.path.join(pasta, nome)


def test_nenhuma_credencial_hardcoded():
    """A regressão que este trabalho todo existe para impedir."""
    encontradas = []
    for caminho in _arquivos_py():
        with open(caminho, encoding="utf-8") as f:
            texto = f.read()
        for segredo in CREDENCIAIS_CONHECIDAS:
            if segredo in texto:
                encontradas.append(f"{os.path.relpath(caminho, RAIZ)}: {segredo[:8]}...")
    assert not encontradas, (
        "Credencial de volta no código — ela deve sair do .env via credenciais.py:\n  "
        + "\n  ".join(encontradas)
    )


def test_env_example_nao_tem_valor_preenchido():
    """O modelo é versionado; se alguém colar a chave real nele, o segredo vaza."""
    caminho = os.path.join(POC_PORTAIS, ".env.example")
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha.startswith("ZYDON_") and "=" in linha:
                chave, _, valor = linha.partition("=")
                assert valor == "", f"{chave} preenchido no .env.example"


# ==========================================
# 2. Falha alto quando falta chave
# ==========================================

def test_carregar_monta_headers_da_env(monkeypatch):
    monkeypatch.setenv("ZYDON_POCS_CODE", "code-de-teste")
    monkeypatch.setenv("ZYDON_POCS_TOKEN", "token-de-teste")
    headers, org = credenciais.carregar("pocs")
    assert headers["X-Zydon-Access-Key-Code"] == "code-de-teste"
    assert headers["X-Zydon-Access-Key-Token"] == "token-de-teste"
    assert headers["Content-Type"] == "application/json"
    assert org["nome"] == "Apresentação POCs"


def test_org_desconhecida_falha():
    with pytest.raises(credenciais.CredencialAusente):
        credenciais.carregar("organizacao-que-nao-existe")


def test_chave_faltando_falha_com_nome_da_variavel(monkeypatch):
    """Sem isto, o script seguia com header vazio e tomava 401 no meio da POC."""
    monkeypatch.delenv("ZYDON_POCS_CODE", raising=False)
    monkeypatch.setenv("ZYDON_POCS_TOKEN", "token-de-teste")
    with pytest.raises(credenciais.CredencialAusente) as erro:
        credenciais.carregar("pocs")
    assert "ZYDON_POCS_CODE" in str(erro.value)


def test_toda_org_do_dict_tem_nome_de_variavel_derivavel():
    """`carregar` deriva a variável do nome da org; nome estranho quebraria isso."""
    for chave in credenciais.ORGANIZACOES:
        assert chave.isidentifier(), f"org '{chave}' não vira nome de variável"
        assert chave == chave.lower()


# ==========================================
# 3. Gerado separado de fonte
# ==========================================

def test_caminho_saida_vai_para_saidas_e_tira_sufixo_poc(tmp_path):
    criar_poc = _carregar_criar_poc()
    entrada = tmp_path / "poc_acme_poc.json"
    entrada.write_text("{}", encoding="utf-8")

    destino = criar_poc.caminho_saida(str(entrada), "_ids")
    assert os.path.basename(destino) == "poc_acme_ids.json"
    assert os.path.basename(os.path.dirname(destino)) == "saidas"


def test_salvar_saidas_grava_os_tres_derivados(tmp_path):
    criar_poc = _carregar_criar_poc()
    entrada = tmp_path / "poc_acme.json"
    entrada.write_text("{}", encoding="utf-8")

    criar_poc.salvar_saidas_pos_execucao(
        str(entrada),
        id_map={"marca_id": 7},
        produtos_criados=[("Produto A", 42)],
        criados=[("sales", "products", "42", "Produto A")],
    )

    saidas = tmp_path / "saidas"
    assert sorted(p.name for p in saidas.iterdir()) == [
        "poc_acme_criados.json",
        "poc_acme_ids.json",
        "poc_acme_images_skeleton.json",
    ]
    assert json.loads((saidas / "poc_acme_ids.json").read_text(encoding="utf-8")) == {
        "marca_id": 7
    }
    skeleton = json.loads(
        (saidas / "poc_acme_images_skeleton.json").read_text(encoding="utf-8")
    )
    assert skeleton == [{"product_id": "42", "image_url": "", "_label": "Produto A"}]


def test_pasta_de_fontes_nao_tem_mais_arquivo_gerado():
    """Se um derivado reaparecer entre as fontes, a separação regrediu."""
    pasta = os.path.join(POC_PORTAIS, "Arquivos Json")
    if not os.path.isdir(pasta):
        pytest.skip("Arquivos Json/ não existe nesta cópia")
    intrusos = [
        nome for nome in os.listdir(pasta)
        if nome.endswith(("_ids.json", "_images_skeleton.json", "_criados.json"))
    ]
    assert not intrusos, f"arquivo gerado fora de saidas/: {intrusos[:5]}"


# ==========================================
# 4. --limpar ainda acha as POCs antigas
# ==========================================

def test_limpar_usa_registro_antigo_ao_lado_da_entrada(tmp_path, monkeypatch):
    """POCs criadas antes de saidas/ têm o _criados.json ao lado do JSON de
    entrada. Sem o fallback, o rollback delas fica órfão."""
    criar_poc = _carregar_criar_poc()
    entrada = tmp_path / "poc_antiga.json"
    entrada.write_text("{}", encoding="utf-8")
    (tmp_path / "poc_antiga_criados.json").write_text(
        json.dumps([["sales", "products", "42", "Produto A"]]), encoding="utf-8"
    )

    vistos = {}

    def _rollback_falso(criados, headers):
        vistos["criados"] = criados
        return []

    monkeypatch.setattr(criar_poc, "rollback", _rollback_falso)
    assert criar_poc.limpar_de_arquivo(str(entrada), {}) is True
    assert vistos["criados"] == [("sales", "products", "42", "Produto A")]


def test_limpar_sem_registro_nenhum_nao_explode(tmp_path):
    criar_poc = _carregar_criar_poc()
    entrada = tmp_path / "poc_sem_registro.json"
    entrada.write_text("{}", encoding="utf-8")
    assert criar_poc.limpar_de_arquivo(str(entrada), {}) is False


# ==========================================
# 5. Rede não pendura mais
# ==========================================

def test_request_with_retry_tem_timeout_padrao(monkeypatch):
    """Sem timeout, uma conexão pendurada travava a POC sem imprimir nada."""
    criar_poc = _carregar_criar_poc()
    capturado = {}

    class _Resposta:
        status_code = 200

    def _request_falso(method, url, **kwargs):
        capturado.update(kwargs)
        return _Resposta()

    monkeypatch.setattr(criar_poc.requests, "request", _request_falso)
    criar_poc.request_with_retry("GET", "https://exemplo.invalido/x")
    assert capturado["timeout"] == criar_poc.TIMEOUT_PADRAO


def test_obter_jwt_portal_le_credencial_dos_headers(monkeypatch):
    """
    O login do portal manda code/token no CORPO do POST, não no cabeçalho — é o
    único ponto assim. Ele lia do dict `org`, que deixou de guardar segredo
    quando as chaves foram para o .env, e quebrou com KeyError depois de já ter
    criado catálogo e portal na API. Os testes anteriores não pegaram porque
    nenhum exercitava esse caminho.
    """
    criar_poc = _carregar_criar_poc()
    capturado = {}

    class _Resposta:
        status_code = 200

        @staticmethod
        def json():
            return {"accessToken": "jwt-de-teste"}

    def _request_falso(method, url, **kwargs):
        capturado.update(kwargs.get("json") or {})
        return _Resposta()

    monkeypatch.setattr(criar_poc.requests, "request", _request_falso)
    headers = {
        "Content-Type": "application/json",
        "X-Zydon-Access-Key-Code": "code-de-teste",
        "X-Zydon-Access-Key-Token": "token-de-teste",
    }
    jwt = criar_poc.obter_jwt_portal(headers, "portal-123")

    assert jwt == "jwt-de-teste"
    assert capturado["code"] == "code-de-teste"
    assert capturado["token"] == "token-de-teste"
    assert capturado["solution_id"] == "portal-123"


def test_nenhuma_funcao_busca_credencial_no_dict_org():
    """`org` carrega só o que não é segredo; credencial vem do .env."""
    caminho = os.path.join(POC_PORTAIS, "Criar Portais", "criar_poc.py")
    with open(caminho, encoding="utf-8") as f:
        codigo = f.read()
    assert 'org["X-Zydon' not in codigo
    assert "org.get(\"X-Zydon" not in codigo


def test_request_with_retry_respeita_timeout_explicito(monkeypatch):
    criar_poc = _carregar_criar_poc()
    capturado = {}

    class _Resposta:
        status_code = 200

    monkeypatch.setattr(
        criar_poc.requests, "request",
        lambda method, url, **kw: (capturado.update(kw), _Resposta())[1],
    )
    criar_poc.request_with_retry("GET", "https://exemplo.invalido/x", timeout=5)
    assert capturado["timeout"] == 5
