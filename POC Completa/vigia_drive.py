"""Vigia uma pasta do Drive e cria a POC quando um JSON curado cai la.

    python "POC Completa/vigia_drive.py" --pasta <id_da_pasta> --uma-vez --simular
    python "POC Completa/vigia_drive.py" --pasta <id_da_pasta> --gravar

NAO E MAIS O CAMINHO PRINCIPAL. O caminho e o `receptor.py`: o Mitra faz POST
quando o executivo salva a curadoria. A pasta caiu porque o acesso do Mitra ao
Google **vive na conversa** — o botao dele e o cron nao tem esse acesso, entao
"sempre que confirmar" viraria "sempre que confirmar e pedir no chat".

Isto fica como plano B de mao: com o tunel fora do ar, da para pedir ao Mitra
que suba o JSON numa pasta e ligar o vigia. Nao e automatico, e nao finja que e.

O TOKEN e o do Sales Ops (`token_drive.json`, escopo `drive.readonly`), o mesmo
que o `baixar.py` usa. Leitura basta: o registro de "ja rodou" e local, entao
renomear ou mover arquivo la nao fura a idempotencia.

A LOGO vem de `logo_url` dentro do JSON ou de um arquivo irmao com o mesmo
prefixo na pasta (`<cliente>_logo.png`). Sem nenhum dos dois a POC e criada
**sem identidade**, e o callback diz isso: portal sem logo se conserta com um
comando, portal nao criado obriga a rodar tudo de novo.
"""

import argparse
import os
import sys
import time
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

# As credenciais do Google moram no Sales Ops e nao vao ser duplicadas aqui —
# mesmo caminho que o subir_identidade usa para achar o .env.
SALES_OPS = Path(os.environ.get(
    "CAMINHO_SALES_OPS",
    r"C:\Users\joaop\OneDrive\Códigos\Automação POCs"))
ESCOPO_DRIVE = ["https://www.googleapis.com/auth/drive.readonly"]
INTERVALO_PADRAO = 5


def servico_drive():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token = SALES_OPS / "token_drive.json"
    if not token.exists():
        raise SystemExit(
            f"[ERRO] {token} nao existe. Rode `python scripts/baixar.py` uma vez\n"
            f"       no Sales Ops, ou aponte CAMINHO_SALES_OPS para o repo certo.")
    creds = Credentials.from_authorized_user_file(str(token), ESCOPO_DRIVE)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise SystemExit(f"[ERRO] Token do Drive invalido e sem refresh: {token}")
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def listar(service, pasta):
    return service.files().list(
        q=f"'{pasta}' in parents and trashed = false",
        fields="files(id, name, mimeType, createdTime, size)",
        orderBy="createdTime desc",
        pageSize=200,
    ).execute().get("files", [])


def baixar(service, item, destino):
    import io
    from googleapiclient.http import MediaIoBaseDownload

    buffer = io.BytesIO()
    baixador = MediaIoBaseDownload(buffer, service.files().get_media(fileId=item["id"]))
    concluido = False
    while not concluido:
        _, concluido = baixador.next_chunk()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(buffer.getvalue())
    return destino


def achar_logo(service, item, arquivos, poc):
    """logo_url do JSON, senao o arquivo irmao de mesmo prefixo. Ou None."""
    pref = atendimento.prefixo(item["name"])
    logo = atendimento.baixar_logo(poc.get("logo_url"), pref)
    if logo:
        return logo
    for outro in arquivos:
        nome = outro["name"].lower()
        if outro["id"] == item["id"] or not nome.startswith(pref.lower()):
            continue
        if nome.endswith(atendimento.EXTENSOES_LOGO):
            return baixar(service, outro, atendimento.DESTINO_LOGO / outro["name"])
    return None


def atender_arquivo(service, item, arquivos, args):
    import json

    print(f"\n{'=' * 62}\n  PEDIDO: {item['name']}  ({item['createdTime']})\n{'=' * 62}")
    bruto = baixar(service, item, atendimento.DESTINO_JSON / item["name"])
    try:
        poc = json.loads(bruto.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        return {"pedido_id": f"drive-{item['id'][:12]}", "status": "falhou",
                "origem_id": item["id"], "observacoes": f"JSON invalido: {e}"}

    pedido_id = poc.get("pedido_id") or f"drive-{item['id'][:12]}"
    logo = achar_logo(service, item, arquivos, poc)
    return atendimento.atender(bruto, logo, args.org, args.gravar,
                               pedido_id=pedido_id, origem_id=item["id"],
                               simular=args.simular)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pasta", default=os.environ.get("DRIVE_PASTA_PEDIDOS"),
                   help="id da pasta do Drive (ou env DRIVE_PASTA_PEDIDOS)")
    p.add_argument("--org", default="pocs")
    p.add_argument("--intervalo", type=int, default=INTERVALO_PADRAO)
    p.add_argument("--uma-vez", action="store_true",
                   help="atende o que estiver pendente e sai")
    p.add_argument("--simular", action="store_true", help="valida e para")
    p.add_argument("--gravar", action="store_true",
                   help="grava a identidade visual")
    p.add_argument("--callback", default=os.environ.get("MITRA_CALLBACK_URL"))
    p.add_argument("--callback-token", default=os.environ.get("MITRA_CALLBACK_TOKEN"))
    p.add_argument("--desde-agora", action="store_true",
                   help="ignora o que ja esta na pasta")
    args = p.parse_args(argv)

    if not args.pasta:
        p.error("passe --pasta <id> ou defina DRIVE_PASTA_PEDIDOS")

    service = servico_drive()
    vistos, pedidos_vistos = atendimento.ja_rodou()

    if args.desde_agora:
        for item in listar(service, args.pasta):
            vistos.add(item["id"])
        print(f"[INFO] {len(vistos)} arquivo(s) marcados como vistos.")

    print(f"[INFO] Vigiando {args.pasta} a cada {args.intervalo}s. Ctrl+C para parar.")
    if args.simular:
        print("[INFO] Modo --simular: nada sera criado.")

    while True:
        try:
            arquivos = listar(service, args.pasta)
        except Exception as e:
            print(f"[AVISO] Falha ao listar ({type(e).__name__}: {e}).")
            if args.uma_vez:
                return 1
            time.sleep(args.intervalo)
            continue

        # Do mais antigo para o mais novo: a fila e por ordem de chegada.
        novos = [a for a in reversed(arquivos)
                 if a["name"].lower().endswith(".json")
                 and not a["name"].lower().endswith(".resumo.json")
                 and a["id"] not in vistos]

        for item in novos:
            vistos.add(item["id"])
            try:
                resultado = atender_arquivo(service, item, arquivos, args)
            except Exception as e:
                resultado = {"pedido_id": f"drive-{item['id'][:12]}",
                             "status": "falhou", "origem_id": item["id"],
                             "observacoes": f"{type(e).__name__}: {e}"}

            if resultado.get("pedido_id") in pedidos_vistos:
                print(f"  [INFO] {resultado['pedido_id']} ja atendido; sem callback.")
                continue
            pedidos_vistos.add(resultado.get("pedido_id"))

            if resultado["status"] != "simulado":
                atendimento.anotar(resultado)
                ok, detalhe = atendimento.avisar_mitra(
                    args.callback, args.callback_token, resultado)
                print(f"  callback: {'entregue' if ok else 'NAO entregue'} — {detalhe}")
            print(f"  RESULTADO: {resultado['status']}  {resultado.get('url') or ''}")

        if args.uma_vez:
            if not novos:
                print("[INFO] Nada pendente.")
            return 0
        time.sleep(args.intervalo)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[INFO] Parado.")
