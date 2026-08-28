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
        try:
            processar(pedido, args)
        except Exception as e:
            print(f"  [ERRO] {type(e).__name__}: {e}")
        finally:
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

    resultado = atendimento.atender(
        caminho, logo, args.org, args.gravar,
        pedido_id=pedido_id, origem_id=pedido_id, simular=args.simular)

    url_callback = pedido.get("callback_url") or args.callback
    token_callback = pedido.get("callback_token") or args.callback_token

    if resultado["status"] != "simulado":
        # O par do callback fica gravado para o `--reenviar` funcionar. E por
        # isso que este arquivo nao e versionado: o callback_token e segredo.
        atendimento.anotar(dict(resultado, callback_url=url_callback,
                                callback_token=token_callback))

    ok, detalhe = atendimento.avisar_mitra(url_callback, token_callback, resultado)
    print(f"  callback: {'entregue' if ok else 'NAO entregue'} — {detalhe}")
    if not ok and resultado.get("url"):
        print(f"  O portal existe e o Mitra nao sabe. Reenvie com:\n"
              f'    python "POC Completa/receptor.py" --reenviar {pedido_id}')
    print(f"  RESULTADO: {resultado['status']}  {resultado.get('url') or ''}")


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
            return self._responder(200, {"ok": True, "fila": FILA.qsize()})
        self._responder(404, {"ok": False, "erro": "ROTA_DESCONHECIDA"})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/pedido", ""):
            return self._responder(404, {"ok": False, "erro": "ROTA_DESCONHECIDA"})

        enviado = self.headers.get("X-Token", "")
        if not hmac.compare_digest(enviado, self.args.token):
            # Sem detalhe no corpo: dizer "token errado" versus "faltou token"
            # ajuda quem estiver tentando adivinhar.
            print("  [RECUSADO] X-Token nao confere.")
            return self._responder(401, {"ok": False, "erro": "NAO_AUTORIZADO"})

        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = 0
        if tamanho <= 0 or tamanho > TAMANHO_MAXIMO:
            return self._responder(413, {"ok": False, "erro": "TAMANHO_INVALIDO"})

        try:
            pedido = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return self._responder(400, {"ok": False, "erro": "JSON_INVALIDO",
                                         "detalhe": str(e)})

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

    Manipulador.args = args
    threading.Thread(target=trabalhar, args=(args,), daemon=True).start()

    servidor = ThreadingHTTPServer(("127.0.0.1", args.porta), Manipulador)
    print(f"[INFO] Receptor em http://127.0.0.1:{args.porta}  "
          f"(POST /pedido, GET /saude)")
    print(f"[INFO] org={args.org}  identidade={'grava' if args.gravar else 'simula'}"
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
