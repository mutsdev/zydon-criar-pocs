"""O miolo de atender um pedido, seja de onde ele vier.

Nasceu de dentro do `vigia_drive.py` quando o receptor HTTP apareceu: as duas
portas de entrada — pasta do Drive e POST — fazem exatamente a mesma coisa
depois que o JSON esta em disco. Validar, achar a logo, criar, descobrir o
endereco e avisar o Mitra nao tem nada a ver com por onde o pedido chegou.

Quem chama entrega um caminho de arquivo. Quem devolve resposta ao Mitra e o
`avisar_mitra`, e ele nunca levanta excecao: callback nao e a entrega.
"""

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import requests

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
PORTAIS = RAIZ / "Criar Portais"
IDENTIDADE = RAIZ / "Identidade Visual"

# RAIZ entra por causa do `credenciais.py`, que mora na raiz do repo e e quem
# tem as chaves da organizacao — sem ele, publicar peca nenhuma sai do lugar.
for _caminho in (str(AQUI), str(PORTAIS), str(IDENTIDADE), str(RAIZ)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

import descobrir_url  # noqa: E402
import subir_identidade as _identidade  # noqa: E402

# O .env mora no Sales Ops, nao neste repo, e quem sabe achar os dois lugares e
# o _carregar_env. Fica aqui, no miolo, porque tanto o receptor quanto o vigia
# leem segredo de la — RECEPTOR_TOKEN e o par de callback do Mitra. Sem isto o
# receptor so enxerga variavel exportada na mao, e a mensagem de erro fala de
# um token que esta escrito no .env: parece bug, e e so o arquivo nao lido.
_identidade._carregar_env()

REGISTRO = RAIZ / "pedidos-executados.jsonl"
DESTINO_JSON = RAIZ / "Arquivos Json"
DESTINO_LOGO = IDENTIDADE / "saidas"
EXTENSOES_LOGO = (".png", ".jpg", ".jpeg", ".webp", ".svg")


# ------------------------------------------------------------------ registro
def criou_algo(registro):
    """A linha do registro representa portal criado?

    O que bloqueia o reenvio e ter criado, nao ter tentado. Pedido que
    reprovou na validacao ou morreu na rede nao criou nada — se ele bloqueasse,
    um erro de catalogo envenenaria o pedido_id para sempre e a unica saida
    seria editar o JSONL na mao. Medido em 28/08/2026, com uma POC de 13
    produtos contra o teto de 12."""
    return registro.get("status") == "concluido" or bool(registro.get("portal_id"))


def ja_rodou():
    """(ids_de_origem, pedidos) do que ja CRIOU portal.

    Duas chaves de proposito: o id de origem pega o mesmo arquivo relido, e o
    pedido_id pega o mesmo pedido reenviado por outro caminho — que e o caso
    quando alguem apaga e manda de novo achando que 'nao pegou'."""
    ids, pedidos = set(), set()
    if not REGISTRO.exists():
        return ids, pedidos
    for linha in REGISTRO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            reg = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if not criou_algo(reg):
            continue  # tentativa falha fica no historico, mas nao bloqueia
        if reg.get("origem_id"):
            ids.add(reg["origem_id"])
        if reg.get("pedido_id"):
            pedidos.add(reg["pedido_id"])
    return ids, pedidos


def anotar(registro):
    with open(REGISTRO, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def buscar(pedido_id):
    """O ultimo registro deste pedido que criou portal, ou None.

    Serve a duas coisas: responder ao reenvio com o resultado em vez de um
    "duplicado" seco, e reenviar o callback que se perdeu."""
    achado = None
    if not REGISTRO.exists():
        return None
    for linha in REGISTRO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            reg = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if reg.get("pedido_id") == pedido_id and criou_algo(reg):
            achado = reg
    return achado


# ------------------------------------------------------------------ execucao
def prefixo(nome):
    """'uze_nails_poc.json' -> 'uze_nails'."""
    base = re.sub(r"\.json$", "", str(nome), flags=re.I)
    return re.sub(r"_poc$", "", base, flags=re.I)


# Sem User-Agent de navegador, servidor de cliente devolve 403. Medido em
# 01/09/2026: a logo da Aroca — a mesma que o achar_logo.py aprova, porque ELE
# manda estes cabecalhos — falhava aqui com HTTPError. O efeito seria calado e
# caro: a rotina acha a logo, o Mitra manda a URL, e o portal nasce sem
# identidade com um [AVISO] que ninguem le.
CABECALHOS_LOGO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "image/webp,image/avif,image/*,*/*;q=0.8",
}


def baixar_logo(url, nome_base):
    """Devolve o caminho local da logo, ou None."""
    if not url:
        return None
    try:
        r = requests.get(url, headers=CABECALHOS_LOGO, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [AVISO] logo_url falhou: {type(e).__name__} — {url}")
        return None
    extensao = Path(url.split("?")[0]).suffix.lower()
    if extensao not in EXTENSOES_LOGO:
        extensao = ".png"
    alvo = DESTINO_LOGO / f"{nome_base}_logo{extensao}"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(r.content)
    return alvo


# Uma execucao nao pode prender a fila para sempre. Em 01/09/2026 a criacao da
# Witop levou 5h30 — a rede da maquina oscilou no meio e cada chamada gastou o
# backoff inteiro. O portal saiu, mas nada mais rodou nesse tempo e o /saude
# dizia "fila: 0", porque o item ja tinha saido da fila. O limite e generoso de
# proposito: matar no meio deixa objeto orfao na Zydon, entao ele existe para o
# caso travado, nao para o caso lento.
LIMITE_EXECUCAO = 90 * 60


DIARIO = RAIZ / "logs"


def _rodar(comando, limite=None, diario=None, ecoar=False):
    """Roda o comando. Com `ecoar`, imprime cada linha assim que ela sai.

    O ao vivo nao e conforto. Sem ele a saida so aparece quando o processo
    termina, e numa execucao de horas ninguem — nem quem esta na frente da
    maquina — sabe dizer se ela avancou. Em 01/09/2026 gastamos meia hora
    deduzindo o progresso da Multiseg por consulta a API, produto por produto,
    porque a unica fonte de verdade estava presa num cano ate o fim.

    PYTHONUNBUFFERED e o que faz isso funcionar de verdade. O filho e Python e,
    escrevendo para um cano em vez de um terminal, ele passa a bufferizar por
    bloco: as linhas so apareceriam de 8 KB em 8 KB, o que numa POC inteira
    significa "no fim". A variavel desliga isso.
    """
    ambiente = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    if not ecoar and diario is None:
        return subprocess.run(comando, cwd=str(RAIZ), env=ambiente,
                              capture_output=True, text=True, timeout=limite,
                              encoding="utf-8", errors="replace")

    arquivo = None
    if diario is not None:
        diario.parent.mkdir(parents=True, exist_ok=True)
        arquivo = open(diario, "w", encoding="utf-8", errors="replace")

    processo = subprocess.Popen(comando, cwd=str(RAIZ), env=ambiente,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                bufsize=1)

    # O limite vive num despertador proprio: ler linha bloqueia, e um processo
    # calado (dormindo num backoff de 120s) nunca voltaria para o laco conferir
    # o relogio. Sem o despertador, o teto so valeria para processo falante.
    estourou = {"sim": False}

    def _matar():
        estourou["sim"] = True
        processo.kill()

    despertador = threading.Timer(limite, _matar) if limite else None
    if despertador:
        despertador.daemon = True
        despertador.start()

    linhas = []
    try:
        for linha in processo.stdout:
            linhas.append(linha)
            if arquivo:
                arquivo.write(linha)
                arquivo.flush()
            if ecoar:
                print(f"  | {linha.rstrip()}", flush=True)
        processo.wait()
    finally:
        if despertador:
            despertador.cancel()
        if arquivo:
            arquivo.close()

    texto = "".join(linhas)
    if estourou["sim"]:
        raise subprocess.TimeoutExpired(comando, limite, output=texto)
    return subprocess.CompletedProcess(comando, processo.returncode, texto, "")


def validar(caminho_json):
    """(ok, saida) do validar_poc.py."""
    p = _rodar([sys.executable, str(VALIDADOR), str(caminho_json)])
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


# Os scripts que o `executar` dispara por subprocesso. Ficam nomeados aqui, e
# nao soltos no meio da funcao, porque e esta lista que o `conferir_instalacao`
# checa antes de o receptor abrir a porta.
RUNNER = PORTAIS / "criar_poc.py"
RUNNER_COMPLETO = AQUI / "criar_poc_completo.py"
VALIDADOR = PORTAIS / "validar_poc.py"


def versao_do_codigo():
    """O commit que este processo carregou na memoria. None fora de um clone.

    Serve para comparar com o HEAD do disco: processo velho e invisivel, e foi
    exatamente o que aconteceu em 03/09/2026 — o receptor rodava desde a
    vespera, o commit e63d723 tinha apagado a copia do runner, e a falha
    chegou como "can't open file", que parece problema de caminho e nao de
    processo desatualizado.
    """
    try:
        pronto = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=str(RAIZ), capture_output=True, text=True,
                                timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return pronto.stdout.strip() or None if pronto.returncode == 0 else None


def conferir_instalacao():
    """Levanta se algum script que vamos disparar nao existir.

    Barato, e evita a pior forma de falhar: descobrir que o caminho mudou
    depois que o cliente ja mandou o pedido, com o erro saindo no log de uma
    execucao em vez de na subida do processo.
    """
    faltando = [c for c in (RUNNER, RUNNER_COMPLETO, VALIDADOR, GERADOR)
                if not c.exists()]
    if faltando:
        recado = ["[ERRO] Estes scripts nao existem:"]
        recado += [f"         {c}" for c in faltando]
        recado.append("       Se o repositorio mudou desde que este processo "
                      "subiu, reinicie-o: o Python carrega o modulo na "
                      "memoria e nao rele o disco sozinho.")
        raise SystemExit(chr(10).join(recado))


def executar(caminho_json, logo, org, nome_cliente, gravar):
    """(codigo, saida) do pipeline completo."""
    if logo:
        comando = [sys.executable, str(RUNNER_COMPLETO),
                   str(caminho_json), org, "--logo", str(logo),
                   "--nome", nome_cliente]
        if gravar:
            comando.append("--gravar")
    else:
        # Sem logo o criar_poc_completo nem comeca (--logo e obrigatorio la, e
        # com razao: o caso normal tem logo). Cai no runner puro.
        comando = [sys.executable, str(RUNNER), str(caminho_json), org]
    diario = DIARIO / f"{prefixo(Path(caminho_json).name)}.log"
    print(f"  acompanhe ao vivo:  Get-Content -Wait '{diario}'")
    try:
        p = _rodar(comando, limite=LIMITE_EXECUCAO, diario=diario, ecoar=True)
    except subprocess.TimeoutExpired:
        # A saida parcial esta no arquivo, e nao no `e.stdout`: quem escreveu
        # foi o proprio processo, direto no diario. Perder isso justo no caso
        # que mais precisa de explicacao seria o pior momento possivel.
        parcial = (diario.read_text(encoding="utf-8", errors="replace")
                   if diario.exists() else "")
        return 1, parcial + (
            f"\n[PARADO] A execucao passou de {LIMITE_EXECUCAO // 60} minutos e "
            f"foi interrompida para nao prender a fila. PODE TER DEIXADO OBJETO "
            f"PELA METADE na Zydon — confira antes de rodar de novo.")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def uuid_da_saida(texto):
    achado = re.search(r"\[OK\] Portal novo: ([0-9a-f-]{36})", texto)
    return achado.group(1) if achado else None


def atender(caminho_json, logo, org, gravar, pedido_id=None, origem_id=None,
            simular=False):
    """Valida, cria e devolve o dicionario de resultado. Nao avisa o Mitra."""
    caminho_json = Path(caminho_json)
    try:
        poc = json.loads(caminho_json.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        return {"pedido_id": pedido_id, "status": "falhou", "origem_id": origem_id,
                "observacoes": f"JSON ilegivel: {e}"}

    nome_portal = poc.get("portal_name") or poc.get("empresa") or ""
    base = {"pedido_id": pedido_id, "origem_id": origem_id,
            "arquivo": caminho_json.name, "cliente": poc.get("empresa")}
    print(f"  cliente: {poc.get('empresa')}  |  portal: {nome_portal}")

    ok, saida_validacao = validar(caminho_json)
    if not ok:
        print(saida_validacao[-2000:])
        return dict(base, status="falhou",
                    observacoes="reprovado no validar_poc.py — nada foi criado")

    if simular:
        print("  [SIMULACAO] Pararia aqui. Nada foi criado.")
        return dict(base, status="simulado", observacoes="modo simulacao")

    print(f"  logo   : {logo if logo else 'nao encontrada — portal sem identidade'}")
    # A saida ja foi ecoada linha a linha durante a execucao; reimprimir o fim
    # aqui duplicaria tudo que voce acabou de ler.
    codigo, saida = executar(caminho_json, logo, org, poc.get("empresa", ""), gravar)

    portal_id = uuid_da_saida(saida)
    url, _ = descobrir_url.descobrir(nome_portal) if nome_portal else (None, [])

    # O criar_poc pode sair 0 com o portal criado e a identidade falhando. Quem
    # decide se o executivo tem o que mostrar e a URL responder, nao o codigo.
    if not url:
        return dict(base, status="falhou", portal_id=portal_id, url=None,
                    observacoes=(f"o pipeline saiu com codigo {codigo} e nenhum "
                                 f"portal chamado '{nome_portal}' responde. "
                                 f"Ver a saida da execucao."))
    return dict(base, status="concluido", portal_id=portal_id, url=url,
                observacoes=("" if logo else "portal criado sem identidade visual: "
                                             "nenhuma logo veio no pedido"))


# ------------------------------------------------------------------- banners
# A geracao das pecas roda EM PARALELO com a criacao do portal, e nao depois.
# Criar uma POC leva minutos e nao depende de banner nenhum; gerar as cenas leva
# um a dois minutos e nao toca a Zydon. Encadear os dois so somaria os tempos.
#
# O que precisa esperar e a PUBLICACAO: subir a peca como resource-file usa o
# JWT do portal, e o portal so existe no fim. Por isso a divisao e gerar ->
# (esperar o portal) -> publicar -> callback.
GERADOR = IDENTIDADE / "gerar_banners.py"

# Rotulo de segmento quando o pedido nao traz um. Nao e o nome da empresa de
# proposito: ele entra no prompt como "empresa do segmento de {X}", e "empresa
# do segmento de Fornello Aperitivos" nao dirige arte nenhuma. Os objetos da
# cena saem do catalogo, que manda sobre isto.
SEGMENTO_PADRAO = "distribuicao B2B"

LIMITE_BANNERS = 15 * 60


def _pasta_da_saida(texto):
    """A ultima linha 'PASTA=' que o gerar_banners imprime."""
    achado = re.findall(r"^PASTA=(.+)$", texto or "", flags=re.M)
    return Path(achado[-1].strip()) if achado else None


def _rodar_gerador(comando, rotulo):
    """Roda o gerar_banners e devolve (pasta, saida). Nunca levanta.

    Banner e o acessorio; o portal e a entrega. Uma POC sem banner continua
    sendo uma POC, e uma excecao aqui derrubaria o pedido inteiro por causa
    dele.
    """
    try:
        diario = DIARIO / f"{rotulo}-banners.log"
        p = _rodar(comando, limite=LIMITE_BANNERS, diario=diario)
    except subprocess.TimeoutExpired:
        return None, f"a geracao passou de {LIMITE_BANNERS // 60} minutos"
    except Exception as e:  # noqa: BLE001 — ver a docstring
        return None, f"{type(e).__name__}: {e}"

    saida = (p.stdout or "") + (p.stderr or "")
    achada = _pasta_da_saida(saida)
    if p.returncode != 0 or not achada or not achada.exists():
        return None, saida[-1500:]
    return achada, saida


def gerar_pecas(caminho_json, logo, nome_cliente, segmento=None, candidatas=2,
                quais=None):
    """Gera as pecas de um cliente novo. Devolve (pasta, saida)."""
    if not logo:
        return None, "sem logo: nao ha de onde tirar a paleta nem a marca"
    # A regua `portal` (200 no MAIOR lado, 48 no menor), e nao a `banner` (200
    # no menor). Marca horizontal e comum — Rema Tip Top 376x70, Cobra 205x58,
    # Benenutri 598x173 — e a regua dura recusa a logo, o que aqui nao gera uma
    # peca pior: gera **zero** pecas, e o executivo abre a tela sem secao de
    # identidade nenhuma. Em 04/09/2026 foi exatamente isso que aconteceu.
    #
    # Logo pequena num painel de 960px fica discreta; o `encaixar` nunca amplia,
    # entao ela nao deforma. Discreta e melhor que ausente.
    comando = [sys.executable, str(GERADOR), "auto",
               "--logo", str(logo), "--nome", nome_cliente,
               "--segmento", segmento or SEGMENTO_PADRAO,
               "--catalogo", str(caminho_json),
               "--regua-logo", "portal",
               "--candidatas", str(candidatas)]
    if quais:
        comando += ["--formatos", ",".join(quais)]
    return _rodar_gerador(comando, prefixo(Path(caminho_json).name))


def regerar_pecas(pasta, quais, candidatas=2):
    """Gera cenas NOVAS dos formatos pedidos, dentro de uma pasta que existe.

    E a curadoria do executivo: "nao gostei do 4:3, gera outro e mantem o
    1920x320". Nao precisa de logo nem de catalogo — os dois ja estao gravados
    na pasta desde o `gerar_pecas`, e reabri-los daria a chance de divergirem.
    """
    if not quais:
        return None, "regerar sem dizer o que: seria refazer tudo"
    comando = [sys.executable, str(GERADOR), "regerar", str(pasta),
               "--formatos", ",".join(quais), "--candidatas", str(candidatas)]
    return _rodar_gerador(comando, Path(pasta).parent.name)


# As pecas que tem destino no portal. Espelha `subir_banners.DESTINOS`, e o
# teste trava as duas juntas — o receptor precisa validar a escolha do Mitra
# ANTES de importar o modulo pesado, e a lista nao pode divergir em silencio.
DESTINOS_BANNER = ("login", "cabecalho")


class GravacaoPelaMetade(RuntimeError):
    """Um PUT gravou e o outro falhou: o portal esta com uma peca so.

    Existe aqui, e nao so em `subir_banners`, porque o receptor precisa
    captura-la sem importar o modulo de imagem inteiro. O `aplicar_pecas`
    traduz uma na outra — herdar nao serviria, ja que quem levanta e o outro
    modulo.
    """

    def __init__(self, causa, gravados, faltou):
        super().__init__(str(causa))
        self.gravados = gravados
        self.faltou = faltou


def _abrir_portal(org, portal_id):
    """(headers_da_org, jwt_do_portal). Os dois sao credenciais diferentes."""
    import credenciais
    import portal as mod_portal
    headers, _ = credenciais.carregar(org)
    jwt = mod_portal.entrar(headers["X-Zydon-Access-Key-Code"],
                            headers["X-Zydon-Access-Key-Token"], portal_id)
    return headers, jwt


def publicar_pecas(org, portal_id, pasta, quais=None):
    """Sobe as pecas e devolve {chave: {file_id, url, dimensao}}.

    **Nao muda o portal.** O executivo precisa VER as pecas antes de decidir, e
    a URL de resource-file e permanente — servir pelo tunel daria um endereco
    que morre junto com o processo.
    """
    import subir_banners
    pecas, _ = subir_banners.pecas_da_pasta(pasta, quais)
    if not pecas:
        return {}
    headers, jwt = _abrir_portal(org, portal_id)
    return subir_banners.publicar(headers, jwt, pecas, ecoar=print)


def renovar_urls(org, portal_id, banners):
    """URLs assinadas novas para pecas JA publicadas. Nao sobe nada.

    A URL de resource-file vale ~2h; o `file_id` e para sempre. Quando o
    executivo reabre a tela no dia seguinte, o que falta e assinatura, e nao
    arquivo — regerar ali seria gastar neuron para resolver um problema de
    validade.
    """
    import portal as mod_portal
    _, jwt = _abrir_portal(org, portal_id)
    renovadas = {}
    for peca, dados in (banners or {}).items():
        file_id = (dados or {}).get("file_id")
        if not file_id:
            continue
        url, expira = mod_portal.url_do_arquivo(jwt, file_id)
        renovadas[peca] = dict(dados, url=url, expira_em=expira)
    return renovadas


def aplicar_pecas(org, portal_id, ids):
    """Aponta o portal para os ids escolhidos. Devolve o relato do GET."""
    import subir_banners
    _, jwt = _abrir_portal(org, portal_id)
    try:
        return subir_banners.aplicar(jwt, ids, ecoar=print)
    except subir_banners.GravacaoPelaMetade as erro:
        raise GravacaoPelaMetade(erro, erro.gravados, erro.faltou) from erro


def ids_publicados(pedido_id):
    """{file_id: peca} de TUDO que ja foi publicado para este pedido.

    A uniao de todos os registros, e nao so o ultimo: o contrato promete que o
    executivo pode aplicar a segunda cena de login depois de ter visto a
    terceira, e o `estado_do_pedido` funde por substituicao — a geracao antiga
    sumiria dele. Aqui elas se somam.

    Existe para o file_id desconhecido morrer aqui, e nao na Zydon. Sondado
    pelo time do Mitra em 03/09/2026: um id inventado atravessava tudo e
    voltava como `HTTP 500 — Invalid UUID string`, que le como falha da
    plataforma quando e erro de quem chamou.
    """
    conhecidos = {}
    if not REGISTRO.exists():
        return conhecidos
    for linha in REGISTRO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            reg = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if reg.get("pedido_id") != pedido_id:
            continue
        for peca, dados in (reg.get("banners") or {}).items():
            if isinstance(dados, dict) and dados.get("file_id"):
                conhecidos[dados["file_id"]] = peca
    return conhecidos


def banners_publicados(pedido_id):
    """{peca: dados} de todas as pecas publicadas, a MAIS NOVA de cada uma.

    O `estado_do_pedido` funde por substituicao: o `banners` de um registro
    novo troca o anterior inteiro. Como a regeracao publica so o formato
    pedido, o registro seguinte carrega uma peca so — e a outra, que continua
    aplicada no portal, sumia do estado.

    O efeito, achado pelo time do Mitra em 04/09/2026: `acao: "urls"` devolvia
    uma peca so. A URL da outra vencia sem ninguem conseguir renova-la, e a
    unica saida aparente virava regerar — trocar a peca aprovada para resolver
    um problema de validade, que e exatamente o que nao se deve fazer.

    Aqui a fusao e PECA A PECA, na ordem do arquivo: cada formato fica com a
    ultima publicacao dele, e nenhum desaparece porque o outro foi mexido.
    """
    achados = {}
    if not REGISTRO.exists():
        return achados
    for linha in REGISTRO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            reg = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if reg.get("pedido_id") != pedido_id:
            continue
        for peca, dados in (reg.get("banners") or {}).items():
            if isinstance(dados, dict) and dados.get("file_id"):
                achados[peca] = dados
    return achados


def estado_do_pedido(pedido_id):
    """O estado acumulado de um pedido: todos os registros dele, fundidos.

    O `buscar` responde "o que este pedido criou"; este responde "onde ele
    esta". Sao perguntas diferentes desde que existe a fase de curadoria: entre
    o portal ficar pronto e o executivo decidir, o pedido tem estado e nao
    terminou.

    A fusao e na ordem do arquivo, entao o registro mais novo manda — que e o
    comportamento certo para `fase`, e o motivo de a regeracao poder acontecer
    varias vezes sem perder a pasta nem o portal_id.
    """
    if not REGISTRO.exists():
        return None
    estado = None
    for linha in REGISTRO.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        try:
            reg = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if reg.get("pedido_id") != pedido_id:
            continue
        estado = dict(estado or {}, **{c: v for c, v in reg.items()
                                       if v is not None})
    return estado


# ------------------------------------------------------------------ callback
# Conectar e rapido; processar do outro lado nao e. Em 28/08/2026 o callback do
# pedido -004 morreu em ReadTimeout com 60s — conexao aberta, resposta nao veio.
TEMPO_CALLBACK = (10, 180)   # (conectar, ler)


def avisar_mitra(callback_url, token, corpo, tentativas=2):
    """(ok, detalhe). Nunca levanta: callback nao e a entrega."""
    if not callback_url:
        return False, "sem callback_url"

    ultimo = ""
    for tentativa in range(1, tentativas + 1):
        try:
            r = requests.post(callback_url, json=dict(corpo, callback_token=token),
                              timeout=TEMPO_CALLBACK)
        except requests.RequestException as e:
            # Retentar depois de um timeout de leitura pode entregar duas vezes,
            # porque o outro lado talvez tenha processado. E seguro: a rota do
            # Mitra e idempotente pelo callback_token e responde `duplicado`.
            ultimo = type(e).__name__
            print(f"  [callback] tentativa {tentativa}/{tentativas}: {ultimo}")
            continue
        # 2xx nao quer dizer entregue — a funcao do Mitra responde 2xx ate
        # quando rejeita, de proposito. Ver ENTREGA.md: confira o efeito.
        try:
            dados = r.json()
        except ValueError:
            return False, f"HTTP {r.status_code}, corpo nao-JSON"
        resposta = _desembrulhar(dados)
        # `duplicado` conta como entregue: quer dizer que ele ja sabia.
        ok = bool(resposta.get("ok")) and not dados.get("error")
        return ok, f"HTTP {r.status_code} {resposta}"
    return False, f"{ultimo} nas {tentativas} tentativas"


def _desembrulhar(dados):
    """A resposta do Mitra vem dentro de um envelope da plataforma dele:

        {"output": "{\\"ok\\":true,\\"duplicado\\":true}",
         "status": "COMPLETED", "error": null, "executionId": "..."}

    O `ok` que interessa esta **dentro de `output`, como string**. Ler o
    envelope de fora nao acha `ok` nenhum e devolve "nao entregue" para uma
    entrega que funcionou — foi o que aconteceu em 01/09/2026, e por causa
    disso passamos dias achando que o canal estava quebrado. Este projeto ja
    caiu nessa com outra roupa: confira o efeito, nao a resposta.
    """
    if not isinstance(dados, dict):
        return {}
    saida = dados.get("output")
    if isinstance(saida, str):
        try:
            interno = json.loads(saida)
        except json.JSONDecodeError:
            return dados
        return interno if isinstance(interno, dict) else dados
    if isinstance(saida, dict):
        return saida
    return dados
