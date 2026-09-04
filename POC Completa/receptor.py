"""Recebe o pedido do Mitra por POST e cria a POC. E a ponta local do tunel.

    python "POC Completa/receptor.py" --novo-token      # gera um segredo e sai
    python "POC Completa/receptor.py" --gravar          # sobe o receptor

    cloudflared tunnel --url http://127.0.0.1:8787      # noutro terminal

Existe porque tempo real so sai de um jeito: o Mitra chamando esta maquina no
instante em que o executivo salva a curadoria. A pasta do Drive nao serve — o
acesso do Mitra ao Google vive na conversa, entao "sempre que confirmar" viraria
"sempre que confirmar e pedir no chat". Saida HTTPS o Mitra tem: ele le a API do
GitHub todo dia.

TRES DECISOES QUE VALE ENTENDER ANTES DE MEXER:

1. **Responde 202 na hora, nao espera a POC ficar pronta.** Criar leva minutos e
   nenhum cliente HTTP espera isso — a conexao cairia no meio e o Mitra ficaria
   sem saber se pegou. Entao o POST so enfileira, e o resultado volta depois
   pelo callback dele, com `{pedido_id, portal_id, url}`.

2. **Escuta so em 127.0.0.1.** Quem expoe para fora e o tunel, que conecta
   localmente. Subir em 0.0.0.0 abriria a porta para a rede inteira em que a
   maquina estiver — inclusive o WiFi de um cliente — sem nada a ganhar.

3. **Um pedido por vez, numa fila.** Duas POCs simultaneas disputam
   `Arquivos Json/saidas/` e a mesma org na API da Zydon. A fila custa espera e
   evita corrida; paralelizar aqui economizaria minutos e criaria bug de
   madrugada.

O CICLO DE BANNER, que acontece depois. Enquanto a POC e criada, as pecas de
identidade sao geradas **em paralelo** — elas so dependem da logo e do catalogo,
que ja estao em disco. Prontas as duas coisas, cada peca sobe como resource-file
(o que **nao muda o portal**) e as URLs vao no callback para o executivo curar:

    POST /banner  {"pedido_id","acao":"regerar",  "pecas":["login"]}
    POST /banner  {"pedido_id","acao":"aplicar",  "escolhas":{"login":"<id>"}}
    POST /banner  {"pedido_id","acao":"dispensar"}

`regerar` gera outra cena SO do formato pedido — e o "nao gostei do 4:3, mantem
o 1920x320". `aplicar` grava. `dispensar` nao sobe nada, e fica registrado: sem
isso, "ele nunca respondeu" e "ele disse que nao" viram o mesmo estado.

SEGREDO. O cabecalho `X-Token` tem que bater com o token do receptor, comparado
com `compare_digest`. Sem ele, qualquer um que descubra a URL do tunel cria
objeto em producao. Gere com `--novo-token`, guarde no cofre do Mitra e **nunca
cole em chat**.
"""

import argparse
import hmac
import json
import os
import queue
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import atendimento  # noqa: E402

PORTA_PADRAO = 8787
TAMANHO_MAXIMO = 8 * 1024 * 1024   # catalogo grande com imagens inline cabe folgado
FILA = queue.Queue()

# Fila propria para a curadoria de banner, com um trabalhador so.
#
# Separada da FILA de POC de proposito. A fila de POC existe para duas POCs nao
# disputarem `Arquivos Json/saidas/` e a mesma org na Zydon; regerar uma cena
# nao toca em nenhum dos dois — e uma chamada a Cloudflare e um subir de arquivo
# escopado num portal. Enfileirar a regeracao atras de uma POC de 90 minutos
# faria o executivo esperar por uma corrida que nao existe.
#
# Um trabalhador, e nao varios: duas regeracoes do mesmo pedido escreveriam na
# mesma pasta ao mesmo tempo.
FILA_BANNER = queue.Queue()

# A previa roda antes do disparo: o executivo esta OLHANDO a tela esperando as
# duas imagens. Ela nao pode ficar atras de uma POC de 90 minutos nem de uma
# regeracao, e nao disputa nada com nenhuma das duas — nao toca a Zydon.
FILA_PREVIA = queue.Queue()

# O que esta sendo criado AGORA. Sem isto o /saude diz "fila: 0" enquanto uma
# execucao trava ha horas — foi o que aconteceu em 01/09/2026 com a Witop: o
# item ja tinha saido da fila, o Mitra mostrava "na fila ha 2h20" e nada, de
# nenhum dos dois lados, sabia dizer se estava vivo.
EM_CURSO = {"pedido_id": None, "desde": None}


def _nome_arquivo(poc, pedido_id):
    """<cliente>_poc.json, no padrao que o validador exige."""
    empresa = (poc.get("empresa") or pedido_id or "cliente").lower()
    limpo = "".join(c if c.isalnum() else "_" for c in empresa).strip("_")
    limpo = "_".join(p for p in limpo.split("_") if p) or "cliente"
    return f"{limpo}_poc.json"


def trabalhar(args):
    """Consome a fila, um pedido por vez, para sempre."""
    while True:
        pedido = FILA.get()
        if pedido is None:
            return
        EM_CURSO.update(pedido_id=pedido.get("pedido_id"), desde=time.time())
        try:
            processar(pedido, args)
        except Exception as e:
            print(f"  [ERRO] {type(e).__name__}: {e}")
        finally:
            EM_CURSO.update(pedido_id=None, desde=None)
            FILA.task_done()


def processar(pedido, args):
    pedido_id = pedido.get("pedido_id")
    poc = pedido.get("catalogo") or pedido.get("poc")
    print(f"\n{'=' * 62}\n  PEDIDO {pedido_id}\n{'=' * 62}")

    caminho = atendimento.DESTINO_JSON / _nome_arquivo(poc, pedido_id)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(poc, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    logo = atendimento.baixar_logo(pedido.get("logo_url"),
                                   atendimento.prefixo(caminho.name))

    # As pecas sao geradas EM PARALELO com a criacao do portal. Elas nao
    # dependem dele — so da logo e do catalogo, que ja estao em disco — e
    # encadear os dois somaria os tempos sem motivo. O que espera o portal e a
    # publicacao, la embaixo, porque subir arquivo usa o JWT dele.
    banner = {}
    linha = None

    # Se a previa ja gerou as pecas deste pedido, elas sao REAPROVEITADAS. Gerar
    # de novo custaria neuron para produzir uma arte diferente da que o
    # executivo acabou de aprovar na curadoria — o pior resultado possivel, pior
    # que nao gerar.
    anterior = atendimento.estado_do_pedido(pedido_id) or {}
    ja_geradas = anterior.get("pasta_banners")
    if ja_geradas and Path(ja_geradas).exists() and not args.sem_banner:
        banner["pasta"] = Path(ja_geradas)
        print(f"  banners: reaproveitando a previa — {ja_geradas}")
    elif not args.sem_banner and not args.simular:
        def _gerar():
            banner["pasta"], banner["saida"] = atendimento.gerar_pecas(
                caminho, logo, poc.get("empresa", ""), pedido.get("segmento"),
                candidatas=args.candidatas)
        linha = threading.Thread(target=_gerar, daemon=True)
        linha.start()
        print("  banners: gerando em paralelo...")

    resultado = atendimento.atender(
        caminho, logo, args.org, args.gravar,
        pedido_id=pedido_id, origem_id=pedido_id, simular=args.simular)

    if linha is not None:
        linha.join()
        pasta = banner.get("pasta")
        if pasta:
            print(f"  banners: {pasta}")
            resultado["pasta_banners"] = str(pasta)
        else:
            print(f"  banners: nao saiu — {str(banner.get('saida'))[-300:]}")

    resultado.update(_publicar_para_curadoria(
        resultado, banner.get("pasta"), args,
        motivo=None if banner.get("pasta") else banner.get("saida")))

    url_callback = pedido.get("callback_url") or args.callback
    token_callback = pedido.get("callback_token") or args.callback_token

    if resultado["status"] != "simulado":
        # O par do callback fica gravado para o `--reenviar` funcionar. E por
        # isso que este arquivo nao e versionado: o callback_token e segredo.
        atendimento.anotar(dict(resultado, callback_url=url_callback,
                                callback_token=token_callback, org=args.org))

    ok, detalhe = atendimento.avisar_mitra(url_callback, token_callback, resultado)
    print(f"  callback: {'entregue' if ok else 'NAO entregue'} — {detalhe}")
    if not ok and resultado.get("url"):
        print(f"  O portal existe e o Mitra nao sabe. Reenvie com:\n"
              f'    python "POC Completa/receptor.py" --reenviar {pedido_id}')
    print(f"  RESULTADO: {resultado['status']}  {resultado.get('url') or ''}")


def _publicar_para_curadoria(resultado, pasta, args, quais=None, motivo=None):
    """Sobe as pecas e devolve os campos de banner do callback.

    Publicar **nao muda o portal**: e so upload de arquivo, para o executivo
    poder ver a peca antes de decidir. Nada aqui pode derrubar o pedido — o
    portal e a entrega, o banner e o acessorio.
    """
    if not pasta or resultado.get("status") != "concluido":
        # O MOTIVO viaja. Sem ele o Mitra so ve a secao de identidade sumir, e
        # "nao gerou" e indistinguivel de "nao tentou" — foi o que aconteceu
        # com a Rema Tip Top em 04/09/2026, cuja logo de 376x70 foi recusada
        # por uma regua que nem se aplicava.
        recado = {"fase": resultado.get("status", "falhou"), "banners": {}}
        if motivo:
            recado["banners_erro"] = str(motivo)[-500:]
        return recado
    if not resultado.get("portal_id"):
        # Sem portal_id nao ha JWT, e sem JWT nao ha upload. Acontece quando o
        # runner cria o portal e a linha de [OK] nao sai como esperado.
        return {"fase": "concluido", "banners": {},
                "banners_erro": "o pedido nao capturou o portal_id"}
    try:
        publicadas = atendimento.publicar_pecas(args.org, resultado["portal_id"],
                                                pasta, quais)
    except Exception as e:  # noqa: BLE001 — banner nunca derruba o pedido
        print(f"  [AVISO] as pecas nao subiram: {type(e).__name__}: {e}")
        return {"fase": "concluido", "banners": {},
                "banners_erro": f"{type(e).__name__}: {e}"}
    if not publicadas:
        return {"fase": "concluido", "banners": {}}
    print(f"  banners: {len(publicadas)} peca(s) publicada(s) para curadoria")
    return {"fase": "curadoria", "banners": publicadas}


def trabalhar_previa():
    """Gera as pecas ANTES de o pedido virar POC.

    Existe porque a identidade e parte da curadoria, e nao um segundo momento:
    o executivo escolhe produtos e arte na mesma tela. Nada aqui toca a Zydon —
    so precisa da logo e do catalogo, que o Mitra ja tem antes do disparo.
    """
    while True:
        tarefa = FILA_PREVIA.get()
        if tarefa is None:
            return
        try:
            _previa(tarefa)
        except Exception as e:
            print(f"  [ERRO] previa: {type(e).__name__}: {e}")
        finally:
            FILA_PREVIA.task_done()


def _previa(pedido, args):
    pedido_id = pedido.get("pedido_id")
    poc = pedido.get("catalogo") or pedido.get("poc") or {}
    print(f"\n  PREVIA {pedido_id}")

    caminho = atendimento.DESTINO_JSON / _nome_arquivo(poc, pedido_id)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(poc, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    logo = atendimento.baixar_logo(pedido.get("logo_url"),
                                   atendimento.prefixo(caminho.name))

    pasta, saida = atendimento.gerar_pecas(
        caminho, logo, poc.get("empresa", ""), pedido.get("segmento"),
        candidatas=args.candidatas)

    token = secrets.token_urlsafe(16)
    corpo = {"pedido_id": pedido_id, "acao": "previa"}
    if pasta:
        atendimento.anotar({"pedido_id": pedido_id, "fase": "previa",
                            "pasta_banners": str(pasta), "token_peca": token})
        corpo["fase"] = "previa"
        corpo["banners"] = atendimento.urls_da_previa(pedido_id, token, pasta)
        print(f"  previa: {len(corpo['banners'])} peca(s) em {pasta}")
    else:
        corpo["fase"] = "previa"
        corpo["banners"] = {}
        corpo["banners_erro"] = str(saida)[-500:]
        print(f"  previa: nao saiu — {str(saida)[-200:]}")

    ok, detalhe = atendimento.avisar_mitra(
        pedido.get("callback_url") or args.callback,
        pedido.get("callback_token") or args.callback_token, corpo)
    print(f"  callback: {'entregue' if ok else 'NAO entregue'} — {detalhe}")


# --------------------------------------------------------------------- banner
ACOES = ("regerar", "aplicar", "dispensar", "urls")


def trabalhar_banner():
    """Consome a fila de curadoria. So `regerar` passa por aqui: `aplicar` e
    `dispensar` sao rapidos e respondem na propria chamada."""
    while True:
        tarefa = FILA_BANNER.get()
        if tarefa is None:
            return
        try:
            _regerar(tarefa)
        except Exception as e:
            print(f"  [ERRO] regeracao: {type(e).__name__}: {e}")
        finally:
            FILA_BANNER.task_done()


def _regerar(tarefa):
    """Gera cenas novas dos formatos pedidos e avisa o Mitra com as URLs."""
    estado, pecas, args = tarefa["estado"], tarefa["pecas"], tarefa["args"]
    pedido_id = estado["pedido_id"]
    print(f"\n  REGERAR {pedido_id}: {', '.join(pecas)}")

    pasta, saida = atendimento.regerar_pecas(estado["pasta_banners"], pecas,
                                             candidatas=args.candidatas)

    # `url` e `status` viajam de novo, embora este callback nao seja sobre o
    # portal. Sem eles o outro lado recebe um callback sem URL e pode concluir
    # que o portal perdeu a dele — o time do Mitra gravava PORTAL_SEM_URL, um
    # erro inventado em cima de um callback correto. Repetir dois campos e mais
    # barato que depender de o consumidor distinguir os eventos.
    corpo = {"pedido_id": pedido_id, "acao": "regerar", "pecas": pecas,
             "status": estado.get("status"), "url": estado.get("url"),
             "portal_id": estado.get("portal_id")}
    if not pasta:
        corpo.update(fase="curadoria", erro=str(saida)[-500:])
        print(f"  [ERRO] regeracao falhou: {str(saida)[-300:]}")
    else:
        # So os formatos regerados sobem: os outros ja estao com o Mitra, e
        # republica-los daria ao executivo uma URL nova para uma peca que ele
        # ja aprovou — que le como "mudou".
        corpo.update(_publicar_para_curadoria(
            {"status": "concluido", "portal_id": estado.get("portal_id")},
            pasta, args, quais=set(pecas)))

    atendimento.anotar({"pedido_id": pedido_id, "fase": corpo.get("fase"),
                        "banners": corpo.get("banners")})
    ok, detalhe = atendimento.avisar_mitra(estado.get("callback_url"),
                                           estado.get("callback_token"), corpo)
    print(f"  callback: {'entregue' if ok else 'NAO entregue'} — {detalhe}")


# Capturada no import, e nao a cada /saude: o valor que interessa e o do codigo
# que este processo carregou, nao o que esta no disco agora.
VERSAO = atendimento.versao_do_codigo()


class Manipulador(BaseHTTPRequestHandler):
    server_version = "receptor-poc"
    args = None

    def _responder(self, codigo, corpo):
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, formato, *a):
        print(f"  [http] {self.address_string()} {formato % a}")

    def do_GET(self):
        # Serve para o tunel e para o Mitra conferirem que a ponta esta viva
        # sem disparar criacao nenhuma.
        if self.path.rstrip("/") in ("/saude", "/health"):
            corpo = {"ok": True, "fila": FILA.qsize(),
                     "fila_banner": FILA_BANNER.qsize(),
                     "fila_previa": FILA_PREVIA.qsize(),
                     "criando": EM_CURSO["pedido_id"],
                     # O commit que ESTE processo carregou, capturado na
                     # subida. Comparado com o HEAD do disco, denuncia
                     # receptor rodando codigo velho — que falha de um jeito
                     # que nao parece codigo velho.
                     "versao": VERSAO}
            if EM_CURSO["desde"]:
                corpo["criando_ha_segundos"] = int(time.time() - EM_CURSO["desde"])
            return self._responder(200, corpo)
        if self.path.startswith("/peca/"):
            return self.servir_peca()
        self._responder(404, {"ok": False, "erro": "ROTA_DESCONHECIDA"})

    def servir_peca(self):
        """GET /peca/<pedido_id>/<token>/<formato> — a imagem da previa.

        O token vai no CAMINHO, e nao num cabecalho: a URL entra num `<img>` do
        outro lado, e tag de imagem nao manda cabecalho. Ele e comparado com
        `compare_digest`, como o X-Token.
        """
        partes = self.path.strip("/").split("/")
        if len(partes) != 4:
            return self._responder(404, {"ok": False, "erro": "CAMINHO_INVALIDO"})
        _, pedido_id, token, chave = partes
        caminho = atendimento.caminho_da_peca(pedido_id, token, chave)
        if caminho is None:
            # Mesma resposta para token errado e peca inexistente: distinguir os
            # dois ajuda quem estiver tentando adivinhar.
            return self._responder(404, {"ok": False, "erro": "NAO_ENCONTRADO"})
        dados = Path(caminho).read_bytes()
        mime = "image/png" if str(caminho).lower().endswith(".png") else "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(dados)))
        # A peca muda quando o executivo pede outra e o nome do arquivo nao muda
        # junto: cache aqui mostraria a imagem velha depois do "Gerar outra",
        # que le como "o botao nao fez nada".
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _corpo(self):
        """(corpo, erro). Autentica, mede e decodifica. `erro` ja foi respondido."""
        enviado = self.headers.get("X-Token", "")
        if not hmac.compare_digest(enviado, self.args.token):
            # Sem detalhe no corpo: dizer "token errado" versus "faltou token"
            # ajuda quem estiver tentando adivinhar.
            print("  [RECUSADO] X-Token nao confere.")
            self._responder(401, {"ok": False, "erro": "NAO_AUTORIZADO"})
            return None, True

        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = 0
        if tamanho <= 0 or tamanho > TAMANHO_MAXIMO:
            self._responder(413, {"ok": False, "erro": "TAMANHO_INVALIDO"})
            return None, True

        try:
            return json.loads(self.rfile.read(tamanho).decode("utf-8")), False
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._responder(400, {"ok": False, "erro": "JSON_INVALIDO",
                                  "detalhe": str(e)})
            return None, True

    def do_POST(self):
        rota = self.path.rstrip("/")
        if rota == "/banner":
            return self.banner()
        if rota == "/previa":
            return self.previa()
        if rota not in ("/pedido", ""):
            return self._responder(404, {"ok": False, "erro": "ROTA_DESCONHECIDA"})

        pedido, erro = self._corpo()
        if erro:
            return

        pedido_id = pedido.get("pedido_id")
        catalogo = pedido.get("catalogo") or pedido.get("poc")
        if not pedido_id or not isinstance(catalogo, dict):
            return self._responder(400, {"ok": False, "erro": "CAMPOS_FALTANDO",
                                         "detalhe": "exijo pedido_id e catalogo{}"})
        if not catalogo.get("etapas"):
            # O formato importa: o runner le catalogo.etapas[]. Recusar aqui e
            # muito melhor que criar um portal vazio sem erro nenhum.
            return self._responder(400, {"ok": False, "erro": "CATALOGO_SEM_ETAPAS"})

        anterior = atendimento.buscar(pedido_id)
        if anterior:
            # A resposta carrega o resultado, e nao so "ja foi feito". E o
            # caminho de recuperacao quando o callback se perde: em 28/08/2026
            # o -004 criou o portal e o aviso morreu em ReadTimeout, deixando o
            # Mitra sem saber de um portal que existia. Reenviar o mesmo pedido
            # devolve a URL na hora, sem callback nenhum no meio.
            print(f"  [DUPLICADO] {pedido_id} — devolvo o resultado guardado.")
            return self._responder(200, {
                "ok": True, "duplicado": True, "pedido_id": pedido_id,
                "status": anterior.get("status"),
                "portal_id": anterior.get("portal_id"),
                "url": anterior.get("url"),
                "observacoes": anterior.get("observacoes", "")})

        FILA.put(pedido)
        print(f"  [ACEITO] {pedido_id} — {FILA.qsize()} na fila.")
        # 202: aceito, ainda nao feito. O resultado vai pelo callback.
        self._responder(202, {"ok": True, "aceito": True, "pedido_id": pedido_id,
                              "fila": FILA.qsize()})

    def previa(self):
        """Gera as pecas ANTES do disparo, para elas entrarem na curadoria.

            POST /previa  {"pedido_id","catalogo":{...},"logo_url","segmento"?}

        Responde 202; as URLs voltam pelo callback com `acao: "previa"`. Elas
        sao servidas por ESTE receptor (`/peca/...`), porque antes do disparo
        nao existe portal — e sem portal nao ha resource-file, ja que o arquivo
        nasce preso a um `solution_id`. Sao efemeras, o que basta para a
        curadoria da hora; depois do `/pedido` as mesmas pecas ganham URL de
        CDN e `file_id` de verdade.
        """
        corpo, erro = self._corpo()
        if erro:
            return
        pedido_id = corpo.get("pedido_id")
        catalogo = corpo.get("catalogo") or corpo.get("poc")
        if not pedido_id or not isinstance(catalogo, dict):
            return self._responder(400, {"ok": False, "erro": "CAMPOS_FALTANDO",
                                         "detalhe": "exijo pedido_id e catalogo{}"})
        if not atendimento.base_publica():
            # Sem tunel publicado nao ha endereco que o Mitra consiga abrir, e
            # gerar para devolver URL quebrada seria gastar cota a toa.
            return self._responder(503, {
                "ok": False, "erro": "SEM_ENDERECO_PUBLICO",
                "detalhe": "o tunel nao esta publicado; a previa nao teria de "
                           "onde servir as imagens"})
        FILA_PREVIA.put((corpo, self.args))
        print(f"  [PREVIA] {pedido_id} — {FILA_PREVIA.qsize()} na fila.")
        return self._responder(202, {"ok": True, "aceito": True,
                                     "pedido_id": pedido_id, "acao": "previa",
                                     "fila": FILA_PREVIA.qsize()})

    # ---------------------------------------------------------------- banner
    def banner(self):
        """A curadoria do executivo, depois que o portal ja existe.

            {"pedido_id":"...", "acao":"regerar",   "pecas":["login"]}
            {"pedido_id":"...", "acao":"aplicar",   "escolhas":{"login":"<id>"}}
            {"pedido_id":"...", "acao":"dispensar"}

        `regerar` responde 202 e avisa pelo callback, porque gerar cena leva
        minutos. `aplicar` e `dispensar` respondem na hora: sao segundos, e o
        executivo acabou de clicar — mandar ele esperar um callback para saber
        se o proprio clique funcionou seria pior de usar e mais dificil de
        depurar.
        """
        corpo, erro = self._corpo()
        if erro:
            return

        pedido_id = corpo.get("pedido_id")
        acao = corpo.get("acao")
        if not pedido_id or acao not in ACOES:
            return self._responder(400, {
                "ok": False, "erro": "CAMPOS_FALTANDO",
                "detalhe": f"exijo pedido_id e acao em {list(ACOES)}"})

        estado = atendimento.estado_do_pedido(pedido_id)
        if not estado:
            return self._responder(404, {"ok": False, "erro": "PEDIDO_DESCONHECIDO",
                                         "pedido_id": pedido_id})
        if not estado.get("portal_id"):
            return self._responder(409, {
                "ok": False, "erro": "SEM_PORTAL", "pedido_id": pedido_id,
                "detalhe": "este pedido nao criou portal; nao ha onde aplicar"})

        if acao == "urls":
            # URLs novas para as MESMAS pecas. Existe porque a URL assinada
            # vale ~2h e o file_id e para sempre: tela reaberta no dia seguinte
            # precisa de assinatura, nao de peca nova. Regerar ali gastaria
            # neuron para resolver um problema de validade.
            # Peca a peca, e nao o `banners` do ultimo registro: aquele traz
            # so o que a regeracao mais recente tocou, e a outra peca — que
            # continua aplicada no portal — ficava sem como ser renovada.
            estado_banners = atendimento.banners_publicados(pedido_id)
            if not estado_banners:
                return self._responder(409, {
                    "ok": False, "erro": "SEM_PECAS", "pedido_id": pedido_id})
            try:
                renovadas = atendimento.renovar_urls(
                    estado.get("org") or self.args.org, estado["portal_id"],
                    estado_banners)
            except Exception as e:  # noqa: BLE001
                return self._responder(502, {
                    "ok": False, "erro": "ZYDON_RECUSOU",
                    "detalhe": f"{type(e).__name__}: {e}"})
            print(f"  [BANNER] {pedido_id} URLs renovadas: "
                  f"{', '.join(sorted(renovadas))}")
            return self._responder(200, {"ok": True, "pedido_id": pedido_id,
                                         "fase": estado.get("fase"),
                                         "banners": renovadas})

        if acao == "dispensar":
            # Nao subir nada e uma decisao legitima, e precisa ficar gravada:
            # sem isto, "ele nunca respondeu" e "ele disse que nao" viram o
            # mesmo estado, e alguem vai perguntar de novo.
            atendimento.anotar({"pedido_id": pedido_id, "fase": "dispensado"})
            print(f"  [BANNER] {pedido_id} dispensado — o portal fica com a "
                  f"aparencia padrao.")
            return self._responder(200, {"ok": True, "pedido_id": pedido_id,
                                         "fase": "dispensado"})

        if acao == "regerar":
            pecas = [p for p in (corpo.get("pecas") or []) if isinstance(p, str)]
            if not pecas:
                return self._responder(400, {
                    "ok": False, "erro": "PECAS_FALTANDO",
                    "detalhe": "regerar sem 'pecas' seria refazer tudo, "
                               "inclusive o que o executivo aprovou"})
            if not estado.get("pasta_banners"):
                return self._responder(409, {
                    "ok": False, "erro": "SEM_PECAS",
                    "detalhe": "este pedido nao gerou banner nenhum"})
            FILA_BANNER.put({"estado": estado, "pecas": pecas, "args": self.args})
            print(f"  [BANNER] {pedido_id} regerar {pecas} — "
                  f"{FILA_BANNER.qsize()} na fila.")
            return self._responder(202, {"ok": True, "aceito": True,
                                         "pedido_id": pedido_id, "acao": "regerar",
                                         "pecas": pecas,
                                         "fila": FILA_BANNER.qsize()})

        # aplicar
        escolhas = corpo.get("escolhas") or {}
        conhecidas = set(atendimento.DESTINOS_BANNER)
        if not escolhas or not set(escolhas) <= conhecidas:
            return self._responder(400, {
                "ok": False, "erro": "ESCOLHAS_INVALIDAS",
                "detalhe": f"escolhas e {{peca: file_id}} com peca em "
                           f"{sorted(conhecidas)}"})

        # O file_id tambem e conferido, contra tudo que ja foi publicado para
        # este pedido — a uniao das geracoes, para o contrato de "aplicar a
        # segunda depois de ver a terceira" continuar valendo. Sem isto o id
        # inventado atravessa e volta como `HTTP 500 — Invalid UUID string`,
        # que le como falha da Zydon quando e erro de quem chamou.
        publicados = atendimento.ids_publicados(pedido_id)
        if not publicados:
            return self._responder(409, {
                "ok": False, "erro": "SEM_PECAS", "pedido_id": pedido_id,
                "detalhe": "nenhuma peca foi publicada para este pedido; "
                           "nao ha file_id que se possa aplicar"})
        intrusos = {p: i for p, i in escolhas.items() if i not in publicados}
        if intrusos:
            return self._responder(400, {
                "ok": False, "erro": "ESCOLHAS_INVALIDAS",
                "pedido_id": pedido_id, "desconhecidos": intrusos,
                "detalhe": "estes file_id nunca foram publicados para este "
                           "pedido. Use os que vieram no callback.",
                "publicados": publicados})
        if self.args.simular:
            print(f"  [SIMULACAO] aplicaria {escolhas} em {estado['portal_id']}")
            return self._responder(200, {"ok": True, "simulado": True,
                                         "pedido_id": pedido_id,
                                         "escolhas": escolhas})
        try:
            relato = atendimento.aplicar_pecas(
                estado.get("org") or self.args.org, estado["portal_id"], escolhas)
        except atendimento.GravacaoPelaMetade as e:
            # O estado real do portal e a informacao que importa aqui, e ela
            # nao esta na mensagem da API: uma peca ficou no ar e a outra nao.
            atendimento.anotar({"pedido_id": pedido_id, "fase": "aplicado_parcial",
                                "aplicado": e.gravados})
            print(f"  [BANNER] {pedido_id} PELA METADE: gravou {e.gravados}, "
                  f"faltou {e.faltou}")
            return self._responder(409, {
                "ok": False, "erro": "GRAVACAO_PELA_METADE",
                "pedido_id": pedido_id, "gravados": e.gravados,
                "faltou": e.faltou, "detalhe": str(e)})
        except Exception as e:  # noqa: BLE001
            print(f"  [BANNER] {pedido_id} falhou: {type(e).__name__}: {e}")
            # `gravados` vazio vai explicito, e no mesmo formato do 409: a tela
            # do outro lado decide o que dizer olhando esse campo, e um corpo
            # com forma diferente a obrigaria a tratar dois casos.
            return self._responder(502, {
                "ok": False, "erro": "ZYDON_RECUSOU", "pedido_id": pedido_id,
                "gravados": [], "faltou": sorted(escolhas),
                "detalhe": str(e)})

        atendimento.anotar({"pedido_id": pedido_id, "fase": "aplicado",
                            "aplicado": relato["gravados"]})
        print(f"  [BANNER] {pedido_id} aplicado: {relato['gravados']}")
        # `confere` sai do GET, e nao do status do PUT. Vai no corpo de
        # proposito: e a unica prova de que o portal realmente mudou.
        return self._responder(200, {"ok": True, "pedido_id": pedido_id,
                                     "fase": "aplicado", **relato})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--porta", type=int, default=PORTA_PADRAO)
    p.add_argument("--org", default="pocs")
    p.add_argument("--token", help="segredo do X-Token (ou env RECEPTOR_TOKEN)")
    p.add_argument("--novo-token", action="store_true",
                   help="gera um segredo, imprime e sai")
    p.add_argument("--reenviar", metavar="PEDIDO_ID",
                   help="reenvia o callback de um pedido ja concluido e sai. "
                        "Para quando o portal foi criado e o aviso se perdeu.")
    p.add_argument("--gravar", action="store_true",
                   help="grava a identidade visual (o portal e criado de "
                        "qualquer jeito quando nao ha --simular)")
    p.add_argument("--simular", action="store_true",
                   help="valida e para; NAO cria nada")
    p.add_argument("--sem-banner", action="store_true",
                   help="nao gera nem publica banner; so cria o portal")
    p.add_argument("--candidatas", type=int, default=2,
                   help="cenas geradas por formato (padrao: 2). Cada cliente "
                        "custa ~940 neurons com 2, de 10.000 por dia.")
    # Os defaults saem do .env, que o `atendimento` ja carregou no import.
    p.add_argument("--callback", default=os.environ.get("MITRA_CALLBACK_URL"),
                   help="callback padrao, se o pedido nao trouxer")
    p.add_argument("--callback-token", default=os.environ.get("MITRA_CALLBACK_TOKEN"))
    args = p.parse_args(argv)

    if args.novo_token:
        print(secrets.token_urlsafe(32))
        print("\nGuarde no cofre do Mitra e passe em RECEPTOR_TOKEN aqui.\n"
              "Nao cole em chat: quem tiver este token cria POC em producao.")
        return 0

    if args.reenviar:
        registro = atendimento.buscar(args.reenviar)
        if not registro:
            print(f"[ERRO] Nenhum pedido concluido com id {args.reenviar}.",
                  file=sys.stderr)
            return 1
        url = registro.get("callback_url") or args.callback
        token = registro.get("callback_token") or args.callback_token
        if not url:
            print(f"[ERRO] O registro de {args.reenviar} nao guardou "
                  f"callback_url — ele e anterior a este recurso. O portal e "
                  f"{registro.get('url')}; passe a mao.", file=sys.stderr)
            return 1
        limpo = {c: v for c, v in registro.items()
                 if c not in ("callback_url", "callback_token")}
        ok, detalhe = atendimento.avisar_mitra(url, token, limpo)
        print(f"callback: {'entregue' if ok else 'NAO entregue'} — {detalhe}")
        return 0 if ok else 1

    args.token = args.token or os.environ.get("RECEPTOR_TOKEN")
    if not args.token:
        print("[ERRO] Falta o segredo. Rode --novo-token, guarde o valor e "
              "ponha RECEPTOR_TOKEN no .env do Sales Ops (ou passe --token).",
              file=sys.stderr)
        return 1

    # Antes de abrir a porta, e nao no meio de um pedido do cliente.
    atendimento.conferir_instalacao()

    Manipulador.args = args
    threading.Thread(target=trabalhar, args=(args,), daemon=True).start()
    threading.Thread(target=trabalhar_banner, daemon=True).start()
    threading.Thread(target=trabalhar_previa, daemon=True).start()

    servidor = ThreadingHTTPServer(("127.0.0.1", args.porta), Manipulador)
    print(f"[INFO] Receptor em http://127.0.0.1:{args.porta}  "
          f"(POST /pedido, POST /previa, POST /banner, GET /saude)")
    atual = atendimento.versao_do_codigo()
    print(f"[INFO] codigo: {VERSAO or 'fora de um clone git'}")
    if atual and VERSAO and atual != VERSAO:
        print(f"[AVISO] o disco ja esta em {atual}. Reinicie para carregar.")
    print(f"[INFO] org={args.org}  identidade={'grava' if args.gravar else 'simula'}"
          f"  banner={'nao' if args.sem_banner else args.candidatas}"
          f"{'  MODO SIMULACAO: nada sera criado' if args.simular else ''}")
    print("[INFO] Agora suba o tunel noutro terminal:")
    print(f"         cloudflared tunnel --url http://127.0.0.1:{args.porta}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Parado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
