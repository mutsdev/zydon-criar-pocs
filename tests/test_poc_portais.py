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
import inspect
import json
import os
import pathlib
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

try:
    import credenciais
except ImportError as _erro:
    # `importorskip` dizia "credenciais.py não encontrado na raiz", mas o import
    # falha também quando falta uma DEPENDÊNCIA dele — python-dotenv, na prática.
    # A mensagem mandava procurar um arquivo que estava lá o tempo todo.
    pytest.skip(f"credenciais não importável ({_erro}). Se for dependência "
                f"faltando, instale o requirements.txt.",
                allow_module_level=True)


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


# ==========================================
# 6. O runner é um só
# ==========================================

def test_run_poc_devolve_o_id_do_portal_por_saida():
    """Sem isto o `criar_poc_completo` não tem como subir a identidade.

    O UUID do portal nasce no meio da execução e não entra no `_ids.json`,
    que é gravado antes dessa etapa. `saida` é o único caminho de volta.
    """
    criar_poc = _carregar_criar_poc()
    assert "saida" in inspect.signature(criar_poc.run_poc).parameters


def test_nao_existe_segunda_copia_do_runner():
    """Duas pastas do sys.path com `criar_poc.py` = import por sorte.

    Em 02/09/2026 havia uma cópia em 'POC Completa/'. O `criar_poc_completo`
    montava o sys.path com `insert(0)` numa ordem que punha 'Criar Portais' na
    frente, importava o original — sem `saida` — e morria em TypeError antes de
    criar coisa alguma. A primeira POC com logo foi a que descobriu.
    """
    copias = [pasta for pasta in ("Criar Portais", "POC Completa",
                                  "Identidade Visual", ".")
              if os.path.exists(os.path.join(POC_PORTAIS, pasta, "criar_poc.py"))]
    assert copias == ["Criar Portais"], f"runner duplicado em {copias}"


# ==========================================
# 7. Receptor rodando codigo velho
# ==========================================

def _carregar_atendimento():
    """Importa 'POC Completa/atendimento.py' (pasta com espaco, nao e pacote)."""
    caminho = os.path.join(POC_PORTAIS, "POC Completa", "atendimento.py")
    spec = importlib.util.spec_from_file_location("atendimento", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_os_scripts_que_o_receptor_dispara_existem():
    """O guarda que o receptor roda antes de abrir a porta.

    Em 03/09/2026 o receptor estava no ar desde a vespera e o commit e63d723
    tinha apagado 'POC Completa/criar_poc.py'. O pedido da Fornello — o
    primeiro SEM logo desde entao, e por isso o primeiro a usar o runner puro —
    morreu com "can't open file", que le como erro de caminho e nao como
    processo desatualizado. Este teste pega a mesma quebra no CI.
    """
    atendimento = _carregar_atendimento()
    atendimento.conferir_instalacao()  # levanta SystemExit se faltar algum


def test_conferir_instalacao_acusa_script_ausente(tmp_path):
    """Falhar alto, e com a instrucao certa: reinicie o processo."""
    atendimento = _carregar_atendimento()
    atendimento.RUNNER = tmp_path / "nao-existe.py"
    with pytest.raises(SystemExit) as erro:
        atendimento.conferir_instalacao()
    assert "reinicie-o" in str(erro.value)


# ==========================================
# 8. O ciclo de banner: gerar, curar, aplicar
# ==========================================

def _carregar(nome, pasta="POC Completa"):
    caminho = os.path.join(POC_PORTAIS, pasta, nome + ".py")
    spec = importlib.util.spec_from_file_location(nome, caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_as_pecas_com_destino_no_portal_nao_divergem():
    """`atendimento.DESTINOS_BANNER` existe para o receptor validar a escolha do
    Mitra sem importar o modulo de imagem. Duas listas separadas divergem em
    silencio, e o efeito seria o receptor recusar uma peca que sobe bem."""
    atendimento = _carregar_atendimento()
    sys.path.insert(0, os.path.join(POC_PORTAIS, "Identidade Visual"))
    import subir_banners
    assert set(atendimento.DESTINOS_BANNER) == set(subir_banners.DESTINOS)


def test_pasta_da_saida_le_a_ultima_linha_do_gerador():
    """O `gerar_banners` imprime `PASTA=` por ultimo, e e assim que o
    atendimento sabe onde as pecas foram parar."""
    atendimento = _carregar_atendimento()
    saida = ("Etapa: montar as pecas\n"
             "  login        cena aprovada\n"
             "PASTA=C:\\saidas\\cliente\\2026-09-03_1700\n")
    assert atendimento._pasta_da_saida(saida).name == "2026-09-03_1700"
    assert atendimento._pasta_da_saida("nada aqui") is None


def test_regerar_sem_dizer_o_que_e_recusado():
    """Regerar tudo mudaria tambem o formato que o executivo aprovou."""
    atendimento = _carregar_atendimento()
    pasta, motivo = atendimento.regerar_pecas("/qualquer", [])
    assert pasta is None and "refazer tudo" in motivo


def test_estado_do_pedido_funde_os_registros_em_ordem(tmp_path):
    """O `buscar` responde 'o que este pedido criou'; o `estado_do_pedido`
    responde 'onde ele esta'. Sao perguntas diferentes desde que existe
    curadoria: entre o portal ficar pronto e o executivo decidir, o pedido tem
    estado e nao terminou."""
    atendimento = _carregar_atendimento()
    atendimento.REGISTRO = tmp_path / "pedidos.jsonl"
    for reg in ({"pedido_id": "p1", "status": "concluido",
                 "portal_id": "uuid-1", "fase": "curadoria",
                 "pasta_banners": "/pasta"},
                {"pedido_id": "outro", "portal_id": "uuid-9"},
                {"pedido_id": "p1", "fase": "aplicado"}):
        atendimento.anotar(reg)

    estado = atendimento.estado_do_pedido("p1")
    assert estado["fase"] == "aplicado"          # o mais novo manda
    assert estado["portal_id"] == "uuid-1"       # e o antigo nao se perde
    assert estado["pasta_banners"] == "/pasta"
    assert atendimento.estado_do_pedido("nunca-visto") is None


@pytest.fixture()
def receptor_no_ar(tmp_path):
    """Um receptor de verdade, em --simular, numa porta efemera.

    HTTP de verdade e nao chamada direta ao manipulador: o que quebra nessa
    rota e autenticacao, codigo de status e forma do corpo, e nada disso
    aparece chamando o metodo Python. A Zydon nao e tocada — `--simular` para
    antes de qualquer PUT — e o registro vai para tmp_path, para nao escrever
    no `pedidos-executados.jsonl` de verdade.
    """
    import argparse
    import threading
    from http.server import ThreadingHTTPServer

    for pasta in ("POC Completa", "Identidade Visual", "."):
        caminho = os.path.join(POC_PORTAIS, pasta)
        if caminho not in sys.path:
            sys.path.insert(0, caminho)
    import receptor as mod

    # ENDERECO e FILA_PREVIA.put sao de modulo: sem restaurar, um teste que os
    # troca contamina os seguintes.
    antes = {"ENDERECO": mod.atendimento.ENDERECO,
             "_rodar_gerador": mod.atendimento._rodar_gerador,
             "previa": mod.FILA_PREVIA.put, "banner": mod.FILA_BANNER.put}
    mod.atendimento.REGISTRO = tmp_path / "pedidos.jsonl"
    mod.Manipulador.args = argparse.Namespace(
        token="segredo-de-teste", org="pocs", gravar=False, simular=True,
        sem_banner=False, candidatas=1, callback=None, callback_token=None)

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), mod.Manipulador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield servidor.server_address[1], mod
    servidor.shutdown()
    mod.atendimento.ENDERECO = antes["ENDERECO"]
    mod.atendimento._rodar_gerador = antes["_rodar_gerador"]
    mod.FILA_PREVIA.put, mod.FILA_BANNER.put = antes["previa"], antes["banner"]


def _postar(porta, rota, corpo, token="segredo-de-teste"):
    import http.client
    conexao = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
    cabecalhos = {"Content-Type": "application/json"}
    if token is not None:
        cabecalhos["X-Token"] = token
    conexao.request("POST", rota, json.dumps(corpo), cabecalhos)
    resposta = conexao.getresponse()
    dados = json.loads(resposta.read().decode("utf-8"))
    conexao.close()
    return resposta.status, dados


def test_banner_sem_token_e_recusado(receptor_no_ar):
    porta, _ = receptor_no_ar
    status, corpo = _postar(porta, "/banner", {"pedido_id": "p1",
                                               "acao": "dispensar"}, token=None)
    assert status == 401 and corpo["erro"] == "NAO_AUTORIZADO"


def test_banner_de_pedido_que_nao_existe_da_404(receptor_no_ar):
    porta, _ = receptor_no_ar
    status, corpo = _postar(porta, "/banner", {"pedido_id": "fantasma",
                                               "acao": "dispensar"})
    assert status == 404 and corpo["erro"] == "PEDIDO_DESCONHECIDO"


def test_banner_recusa_acao_inventada(receptor_no_ar):
    porta, _ = receptor_no_ar
    status, corpo = _postar(porta, "/banner", {"pedido_id": "p1",
                                               "acao": "apagar_tudo"})
    assert status == 400 and corpo["erro"] == "CAMPOS_FALTANDO"


def test_ciclo_de_curadoria(receptor_no_ar):
    """As tres acoes contra um pedido que ja criou portal."""
    porta, mod = receptor_no_ar
    mod.atendimento.anotar({
        "pedido_id": "p1", "status": "concluido", "portal_id": "uuid-1",
        "fase": "curadoria", "pasta_banners": "/pasta", "org": "pocs",
        "banners": {"login": {"file_id": "file-1", "url": "http://x"},
                    "cabecalho": {"file_id": "file-2", "url": "http://y"}}})

    # regerar sem dizer o que refaria tambem a peca aprovada.
    status, corpo = _postar(porta, "/banner", {"pedido_id": "p1",
                                               "acao": "regerar"})
    assert status == 400 and corpo["erro"] == "PECAS_FALTANDO"

    # regerar um formato so entra na fila propria, e nao na fila de POC.
    status, corpo = _postar(porta, "/banner", {"pedido_id": "p1",
                                               "acao": "regerar",
                                               "pecas": ["login"]})
    assert status == 202 and corpo["pecas"] == ["login"]
    assert mod.FILA_BANNER.qsize() == 1 and mod.FILA.qsize() == 0
    mod.FILA_BANNER.get()  # tira da fila: o trabalhador nao esta rodando aqui

    # peca que nao existe nao chega a virar chamada para a Zydon.
    status, corpo = _postar(porta, "/banner", {
        "pedido_id": "p1", "acao": "aplicar", "escolhas": {"rodape": "x"}})
    assert status == 400 and corpo["erro"] == "ESCOLHAS_INVALIDAS"

    # em --simular, aplicar responde sem tocar na Zydon.
    status, corpo = _postar(porta, "/banner", {
        "pedido_id": "p1", "acao": "aplicar",
        "escolhas": {"login": "file-1", "cabecalho": "file-2"}})
    assert status == 200 and corpo["simulado"] is True

    # dispensar fica GRAVADO: sem isto, "nunca respondeu" e "disse que nao"
    # viram o mesmo estado e alguem pergunta de novo.
    status, corpo = _postar(porta, "/banner", {"pedido_id": "p1",
                                               "acao": "dispensar"})
    assert status == 200 and corpo["fase"] == "dispensado"
    assert mod.atendimento.estado_do_pedido("p1")["fase"] == "dispensado"


def test_file_id_desconhecido_morre_aqui_e_nao_na_zydon(receptor_no_ar):
    """Sondado pelo time do Mitra em 03/09/2026: um id inventado atravessava
    tudo e voltava como `HTTP 500 — Invalid UUID string`, que le como falha da
    plataforma quando e erro de quem chamou."""
    porta, mod = receptor_no_ar
    mod.atendimento.anotar({
        "pedido_id": "p4", "status": "concluido", "portal_id": "uuid-4",
        "fase": "curadoria", "pasta_banners": "/pasta", "org": "pocs",
        "banners": {"login": {"file_id": "real-login-1", "url": "http://x"},
                    "cabecalho": {"file_id": "real-cab-1", "url": "http://y"}}})

    status, corpo = _postar(porta, "/banner", {
        "pedido_id": "p4", "acao": "aplicar",
        "escolhas": {"login": "TESTE-login-B"}})
    assert status == 400 and corpo["erro"] == "ESCOLHAS_INVALIDAS"
    assert corpo["desconhecidos"] == {"login": "TESTE-login-B"}
    # A resposta diz quais valem, para o outro lado nao ter que adivinhar.
    assert "real-login-1" in corpo["publicados"]


def test_geracao_antiga_continua_aplicavel_depois_de_regerar(receptor_no_ar):
    """O contrato promete aplicar a SEGUNDA cena depois de ver a terceira.

    O `estado_do_pedido` funde por substituicao, entao a geracao antiga sumiria
    dele; a conferencia do file_id usa a uniao dos registros justamente por
    isso. Era aqui que o 1920x320 aprovado se perderia.
    """
    porta, mod = receptor_no_ar
    mod.atendimento.anotar({
        "pedido_id": "p5", "status": "concluido", "portal_id": "uuid-5",
        "fase": "curadoria", "pasta_banners": "/pasta", "org": "pocs",
        "banners": {"login": {"file_id": "login-ger1"},
                    "cabecalho": {"file_id": "cab-ger1"}}})
    # A regeracao publica so o login, e so ele entra no registro novo.
    mod.atendimento.anotar({"pedido_id": "p5", "fase": "curadoria",
                            "banners": {"login": {"file_id": "login-ger2"}}})

    publicados = mod.atendimento.ids_publicados("p5")
    assert publicados == {"login-ger1": "login", "cab-ger1": "cabecalho",
                          "login-ger2": "login"}

    # Aplicar a geracao ANTIGA do login junto com o cabecalho de sempre passa
    # pela validacao — em --simular nao chega a tocar a Zydon.
    status, corpo = _postar(porta, "/banner", {
        "pedido_id": "p5", "acao": "aplicar",
        "escolhas": {"login": "login-ger1", "cabecalho": "cab-ger1"}})
    assert status == 200 and corpo["simulado"] is True


def test_aplicar_sem_nada_publicado_diz_sem_pecas(receptor_no_ar):
    """Antes isto viajava ate a Zydon para voltar como erro dela."""
    porta, mod = receptor_no_ar
    mod.atendimento.anotar({"pedido_id": "p6", "status": "concluido",
                            "portal_id": "uuid-6"})
    status, corpo = _postar(porta, "/banner", {
        "pedido_id": "p6", "acao": "aplicar", "escolhas": {"login": "qualquer"}})
    assert status == 409 and corpo["erro"] == "SEM_PECAS"


def test_pedido_sem_portal_nao_aceita_curadoria(receptor_no_ar):
    """Sem portal_id nao ha JWT, e sem JWT nao ha onde aplicar."""
    porta, mod = receptor_no_ar
    mod.atendimento.anotar({"pedido_id": "p3", "status": "falhou"})
    status, corpo = _postar(porta, "/banner", {"pedido_id": "p3",
                                               "acao": "dispensar"})
    assert status == 409 and corpo["erro"] == "SEM_PORTAL"


def test_cor_das_pecas_sai_do_paleta_json(tmp_path):
    """A cor do portal tem que ser a MESMA com que as pecas foram pintadas.

    Sai do paleta.json — que o `regerar --cor` reescreve — e nao de um campo
    guardado a parte, que poderia divergir da arte que o executivo esta vendo.
    """
    atendimento = _carregar_atendimento()
    assert atendimento.cor_das_pecas(None) is None
    assert atendimento.cor_das_pecas(tmp_path) is None       # sem paleta.json
    (tmp_path / "paleta.json").write_text(
        json.dumps({"principal": "#33415B", "destaque": "#FFF"}), encoding="utf-8")
    assert atendimento.cor_das_pecas(tmp_path) == "#33415B"


def test_aplicar_grava_a_cor_junto_da_tela_de_login(monkeypatch):
    """Um PUT so com os dois campos, e a cor sem '#'.

    Sem isto o executivo troca a cor base na curadoria, ve os banners mudarem e
    o portal continuar na cor antiga.
    """
    import importlib.util
    caminho = os.path.join(POC_PORTAIS, "Identidade Visual", "subir_banners.py")
    spec = importlib.util.spec_from_file_location("subir_banners_teste", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    enviados = []
    monkeypatch.setattr(mod.mod_portal, "obter_aparencia",
                        lambda jwt: {"color": "AABBCC", "login_image": "velho"})
    monkeypatch.setattr(mod.mod_portal, "atualizar_aparencia",
                        lambda jwt, antes, mudancas: enviados.append(mudancas))
    relato = mod.aplicar("jwt", {"login": "id-novo"}, cor="#33415b")

    assert len(enviados) == 1, "dois PUTs seriam duas chances de meia gravacao"
    assert enviados[0] == {"login_image": "id-novo", "color": "33415B"}
    assert relato["gravados"] == ["login"]


def test_pedido_sem_segmento_avisa_em_vez_de_substituir_calado():
    """A arte generica e a dirigida chegam identicas ao executivo sem isto.

    Em 04/09/2026 os tres pedidos de rede social vieram sem segmento — o campo
    era opcional na tela do Mitra — e as cenas foram desenhadas para
    "distribuicao B2B" em vez do ramo do cliente, sem nada dizendo isso.
    """
    atendimento = _carregar_atendimento()
    assert atendimento.aviso_de_segmento("conservas artesanais") is None
    for vazio in (None, "", "   "):
        aviso = atendimento.aviso_de_segmento(vazio)
        assert aviso and atendimento.SEGMENTO_PADRAO in aviso


def test_versao_ignora_o_commit_de_endereco(monkeypatch):
    """`versao` diz que CODIGO esta rodando, e nao pode andar sozinha.

    O `tunel.py` commita o endereco-receptor.json a cada rotacao, varias vezes
    por dia. Em 04/09/2026 o time do Mitra leu `versao: 9ef1eba` num /saude e
    reportou como versao nova — era commit de endereco, e o codigo continuava
    no 05098b5.
    """
    import subprocess
    atendimento = _carregar_atendimento()
    visto = {}

    def falso(comando, **kw):
        visto["comando"] = comando
        return subprocess.CompletedProcess(comando, 0, "05098b5\n", "")

    monkeypatch.setattr(atendimento.subprocess, "run", falso)
    assert atendimento.versao_do_codigo() == "05098b5"
    assert f":(exclude){atendimento.ENDERECO.name}" in visto["comando"]
    assert "rev-parse" not in visto["comando"]


def test_feedback_viaja_ate_a_regeracao(receptor_no_ar):
    """O feedback do executivo tem que chegar no comando do gerador.

    Ele e a unica parte do pedido escrita por alguem que VIU a peca; se parasse
    no receptor, a regeracao seria mais um chute — que e exatamente a queixa que
    fez a rota ganhar este campo.
    """
    porta, mod = receptor_no_ar
    mod.atendimento.anotar({"pedido_id": "fb1", "status": "concluido",
                            "portal_id": "uuid-fb", "pasta_banners": "/pasta"})
    recebidas = []
    mod.FILA_BANNER.put = lambda tarefa: recebidas.append(tarefa)

    status, _ = _postar(porta, "/banner", {
        "pedido_id": "fb1", "acao": "regerar", "pecas": ["login"],
        "feedback": {"login": "odiei a paleta",
                     "cabecalho": "esse ficou otimo, mantem a pegada"}})

    assert status == 202
    tarefa = recebidas[0]
    assert tarefa["pecas"] == ["login"]
    # O elogio ao cabecalho viaja mesmo sem ele estar em `pecas`: e assim que
    # "faz o login parecido com aquele" chega ao prompt.
    assert tarefa["feedback"]["cabecalho"].startswith("esse ficou otimo")

    comando = []
    mod.atendimento._rodar_gerador = lambda c, r: (comando.extend(c), (None, "x"))[1]
    mod.atendimento.regerar_pecas("/pasta", ["login"],
                                  feedback=tarefa["feedback"], cor="#123456")
    assert "--feedback" in comando and "login=odiei a paleta" in comando
    assert "cabecalho=esse ficou otimo, mantem a pegada" in comando
    assert comando[comando.index("--cor") + 1] == "#123456"


def test_feedback_de_peca_inventada_e_recusado(receptor_no_ar):
    porta, mod = receptor_no_ar
    mod.atendimento.anotar({"pedido_id": "fb2", "status": "concluido",
                            "portal_id": "uuid-fb2", "pasta_banners": "/pasta"})
    status, corpo = _postar(porta, "/banner", {
        "pedido_id": "fb2", "acao": "regerar", "pecas": ["login"],
        "feedback": {"logim": "texto"}})
    assert status == 400 and corpo["erro"] == "FEEDBACK_INVALIDO"


def test_cor_precisa_ser_hex(receptor_no_ar):
    """A cor vira paleta do Pillow; um valor torto sujaria a pasta inteira."""
    porta, mod = receptor_no_ar
    mod.atendimento.anotar({"pedido_id": "fb3", "status": "concluido",
                            "portal_id": "uuid-fb3", "pasta_banners": "/pasta"})
    status, corpo = _postar(porta, "/banner", {
        "pedido_id": "fb3", "acao": "regerar", "pecas": ["login"],
        "cor": "vermelho"})
    assert status == 400 and corpo["erro"] == "COR_INVALIDA"


def test_previa_sem_tunel_avisa_em_vez_de_gerar(receptor_no_ar):
    """Gerar para devolver URL que o Mitra nao abre e gastar cota a toa."""
    porta, mod = receptor_no_ar
    mod.atendimento.ENDERECO = pathlib.Path("nao-existe-endereco.json")
    status, corpo = _postar(porta, "/previa", {"pedido_id": "pv0",
                                               "logo_url": "http://x/l.png"})
    assert status == 503 and corpo["erro"] == "SEM_ENDERECO_PUBLICO"


def test_previa_aceita_pedido_sem_catalogo(receptor_no_ar, tmp_path):
    """A razao de ser da rota: a arte so precisa da logo.

    Se a previa exigisse o catalogo, ela teria de esperar a varredura de
    produtos — que e exatamente o encadeamento que ela desfaz.
    """
    porta, mod = receptor_no_ar
    endereco = tmp_path / "endereco.json"
    endereco.write_text(json.dumps({"url": "https://a-b-c.trycloudflare.com"}),
                        encoding="utf-8")
    mod.atendimento.ENDERECO = endereco

    recebidas = []
    mod.FILA_PREVIA.put = lambda tarefa: recebidas.append(tarefa)
    status, corpo = _postar(porta, "/previa", {
        "pedido_id": "pv1", "logo_url": "http://x/l.png", "empresa": "Acme"})

    assert status == 202 and corpo["acao"] == "previa"
    # A tarefa e uma TUPLA (corpo, args), e o trabalhador desempacota com *.
    # Sem isso a rota respondia 202 e a linha morria com TypeError, sem
    # callback nenhum — a previa parecia aceita e nunca voltava.
    assert len(recebidas[0]) == 2 and recebidas[0][0]["pedido_id"] == "pv1"


def test_previa_sem_logo_e_recusada(receptor_no_ar, tmp_path):
    porta, mod = receptor_no_ar
    endereco = tmp_path / "endereco.json"
    endereco.write_text(json.dumps({"url": "https://a-b-c.trycloudflare.com"}),
                        encoding="utf-8")
    mod.atendimento.ENDERECO = endereco
    status, corpo = _postar(porta, "/previa", {"pedido_id": "pv2"})
    assert status == 400 and corpo["erro"] == "CAMPOS_FALTANDO"


def test_registro_de_fase_nao_envenena_o_pedido_id(tmp_path):
    """A fase de banner nao pode fazer o `ja_rodou` bloquear um pedido que nao
    criou portal: um erro de catalogo envenenaria o id para sempre."""
    atendimento = _carregar_atendimento()
    atendimento.REGISTRO = tmp_path / "pedidos.jsonl"
    atendimento.anotar({"pedido_id": "p2", "fase": "dispensado"})
    _, pedidos = atendimento.ja_rodou()
    assert "p2" not in pedidos
