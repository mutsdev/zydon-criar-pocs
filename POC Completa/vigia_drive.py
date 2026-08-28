"""Vigia uma pasta do Drive e cria a POC assim que o JSON curado cai la.

    python "POC Completa/vigia_drive.py" --pasta <id_da_pasta> --uma-vez --simular
    python "POC Completa/vigia_drive.py" --pasta <id_da_pasta> --gravar

O contrato: o Mitra grava `<cliente>_poc.json` na pasta quando o executivo
clica em salvar curadoria. O vigia enxerga em segundos, roda o pipeline
completo (catalogo + portal + identidade), descobre o endereco publico e
devolve `{pedido_id, portal_id, url}` para o callback do Mitra.

SOBRE "TEMPO REAL": isto e polling, e nao tem como nao ser. O Drive so empurra
evento para um endpoint HTTPS publico, que e exatamente o que esta maquina nao
tem — foi por isso que a pasta entrou no lugar de uma chamada direta. O que da
para fazer e o intervalo curto: 5s de latencia para enxergar, e a criacao em si
leva minutos. Perto disso, o polling nao e o gargalo.

A LOGO. O JSON da POC nao carrega logo. O vigia procura, nesta ordem:

  1. `logo_url` dentro do JSON, se o Mitra puser
  2. um arquivo irmao na mesma pasta com o mesmo prefixo (`<cliente>_logo.png`)

Sem nenhum dos dois, a POC e criada assim mesmo, **sem identidade visual**, e o
callback diz isso em `observacoes`. Portal sem logo se conserta com um comando;
portal nao criado obriga a rodar tudo de novo.

O TOKEN e o do Sales Ops (`token_drive.json`, escopo `drive.readonly`) — o
mesmo que o `baixar.py` usa. Leitura basta: o registro de "ja rodou" e local, em
`pedidos-executados.jsonl`, e nao no nome do arquivo do Drive. Isso importa
porque o Drive nao e nosso: se alguem renomear ou mover o arquivo la, o
controle de idempotencia continua valendo aqui.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
PORTAIS = RAIZ / "Criar Portais"
IDENTIDADE = RAIZ / "Identidade Visual"

for _caminho in (str(AQUI), str(RAIZ), str(PORTAIS), str(IDENTIDADE)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import requests  # noqa: E402

import descobrir_url  # noqa: E402

# Mesmo caminho que o subir_identidade usa para achar o .env: as credenciais do
# Google moram no Sales Ops e nao vao ser duplicadas aqui.
SALES_OPS = Path(os.environ.get(
    "CAMINHO_SALES_OPS",
    r"C:\Users\joaop\OneDrive\Códigos\Automação POCs"))

ESCOPO_DRIVE = ["https://www.googleapis.com/auth/drive.readonly"]
REGISTRO = RAIZ / "pedidos-executados.jsonl"
DESTINO_JSON = RAIZ / "Arquivos Json"
DESTINO_LOGO = IDENTIDADE / "saidas"
INTERVALO_PADRAO = 5
EXTENSOES_LOGO = (".png", ".jpg", ".jpeg", ".webp", ".svg")


# --------------------------------------------------------------------- Drive
def servico_drive():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token = SALES_OPS / "token_drive.json"
    if not token.exists():
        raise SystemExit(
            f"[ERRO] {token} nao existe. Rode `python scripts/baixar.py` uma vez\n"
            f"       no Sales Ops para negociar o token do Drive, ou aponte\n"
            f"       CAMINHO_SALES_OPS para o repositorio certo.")
    creds = Credentials.from_authorized_user_file(str(token), ESCOPO_DRIVE)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise SystemExit(f"[ERRO] Token do Drive invalido e sem refresh: {token}")
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def listar(service, pasta):
    """Arquivos da pasta, mais novos primeiro. So o que e desta pasta."""
    resultado = service.files().list(
        q=f"'{pasta}' in parents and trashed = false",
        fields="files(id, name, mimeType, createdTime, size)",
        orderBy="createdTime desc",
        pageSize=200,
    ).execute()
    return resultado.get("files", [])


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


# ----------------------------------------------------------------- registro
def ja_rodou():
    """Devolve (ids_de_arquivo, pedidos) do que ja foi executado.

    Duas chaves de proposito: o id do arquivo pega o mesmo arquivo relido, e o
    pedido_id pega o mesmo pedido reenviado como arquivo novo — que e o caso
    quando alguem apaga e sobe de novo achando que 'nao pegou'."""
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
        if reg.get("drive_file_id"):
            ids.add(reg["drive_file_id"])
        if reg.get("pedido_id"):
            pedidos.add(reg["pedido_id"])
    return ids, pedidos


def anotar(registro):
    with open(REGISTRO, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ execucao
def prefixo(nome):
    """'uze_nails_poc.json' -> 'uze_nails'."""
    base = re.sub(r"\.json$", "", nome, flags=re.I)
    return re.sub(r"_poc$", "", base, flags=re.I)


def achar_logo(service, item, arquivos, pasta_local, poc):
    """Baixa a logo e devolve o caminho, ou None."""
    url = poc.get("logo_url")
    if url:
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            extensao = Path(url.split("?")[0]).suffix.lower() or ".png"
            alvo = pasta_local / f"{prefixo(item['name'])}_logo{extensao}"
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(r.content)
            return alvo
        except requests.RequestException as e:
            print(f"  [AVISO] logo_url falhou ({type(e).__name__}); tento o arquivo irmao.")

    pref = prefixo(item["name"]).lower()
    for outro in arquivos:
        nome = outro["name"].lower()
        if outro["id"] == item["id"] or not nome.startswith(pref):
            continue
        if nome.endswith(EXTENSOES_LOGO):
            return baixar(service, outro, pasta_local / outro["name"])
    return None


def executar(caminho_json, logo, org, nome_cliente, gravar):
    """Roda o pipeline completo como subprocesso e devolve (codigo, saida)."""
    comando = [sys.executable, str(AQUI / "criar_poc_completo.py"),
               str(caminho_json), org]
    if logo:
        comando += ["--logo", str(logo), "--nome", nome_cliente]
        if gravar:
            comando.append("--gravar")
    else:
        # Sem logo o criar_poc_completo nem comeca (--logo e obrigatorio la, e
        # com razao: o caso normal tem logo). Cai no runner puro.
        comando = [sys.executable, str(AQUI / "criar_poc.py"), str(caminho_json), org]

    ambiente = dict(os.environ, PYTHONIOENCODING="utf-8")
    processo = subprocess.run(comando, cwd=str(RAIZ), env=ambiente,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    return processo.returncode, (processo.stdout or "") + (processo.stderr or "")


def uuid_da_saida(texto):
    achado = re.search(r"\[OK\] Portal novo: ([0-9a-f-]{36})", texto)
    return achado.group(1) if achado else None


def avisar_mitra(callback_url, token, corpo):
    """Devolve (ok, detalhe). Nunca levanta: callback nao e a entrega."""
    if not callback_url:
        return False, "sem callback_url"
    try:
        r = requests.post(callback_url, json=dict(corpo, callback_token=token), timeout=60)
    except requests.RequestException as e:
        return False, f"{type(e).__name__}"
    # 2xx nao quer dizer entregue — a funcao do Mitra responde 2xx ate quando
    # rejeita, de proposito. Ver ENTREGA.md: confira o efeito, nao a resposta.
    try:
        dados = r.json()
    except ValueError:
        return False, f"HTTP {r.status_code}, corpo nao-JSON"
    return bool(dados.get("ok")), f"HTTP {r.status_code} {dados}"


def atender(service, item, arquivos, args):
    print(f"\n{'=' * 62}\n  PEDIDO: {item['name']}  ({item['createdTime']})\n{'=' * 62}")

    bruto = baixar(service, item, DESTINO_JSON / item["name"])
    try:
        poc = json.loads(bruto.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        print(f"  [FALHA] JSON invalido: {e}")
        return {"status": "falhou", "observacoes": f"JSON invalido: {e}"}

    pedido_id = poc.get("pedido_id") or f"drive-{item['id'][:12]}"
    nome_portal = poc.get("portal_name") or poc.get("empresa") or ""
    print(f"  cliente: {poc.get('empresa')}  |  portal: {nome_portal}")

    validacao = subprocess.run(
        [sys.executable, str(PORTAIS / "validar_poc.py"), str(bruto)],
        cwd=str(RAIZ), env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if validacao.returncode != 0:
        print(validacao.stdout[-2000:])
        return {"pedido_id": pedido_id, "status": "falhou",
                "observacoes": "reprovado no validar_poc.py — nada foi criado"}

    logo = achar_logo(service, item, arquivos, DESTINO_LOGO, poc)
    print(f"  logo   : {logo if logo else 'nao encontrada — portal sem identidade'}")

    if args.simular:
        print("  [SIMULACAO] Pararia aqui. Nada foi criado.")
        return {"pedido_id": pedido_id, "status": "simulado",
                "observacoes": "modo --simular"}

    codigo, saida = executar(bruto, logo, args.org, poc.get("empresa", ""), args.gravar)
    print(saida[-3000:])

    portal_id = uuid_da_saida(saida)
    url, _ = descobrir_url.descobrir(nome_portal) if nome_portal else (None, [])

    # O criar_poc pode sair 0 com o portal criado e a identidade falhando. O que
    # decide se o executivo tem o que mostrar e a URL responder, nao o codigo.
    resultado = {
        "pedido_id": pedido_id,
        "status": "concluido" if url else "falhou",
        "portal_id": portal_id,
        "url": url,
        "drive_file_id": item["id"],
        "arquivo": item["name"],
        "observacoes": ("" if logo else "portal criado sem identidade visual: "
                                        "nenhuma logo veio no pedido"),
    }
    if not url:
        resultado["observacoes"] = (
            f"o pipeline saiu com codigo {codigo} e nenhum portal chamado "
            f"'{nome_portal}' responde. Ver a saida da execucao.")
    return resultado


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pasta", default=os.environ.get("DRIVE_PASTA_PEDIDOS"),
                   help="id da pasta do Drive (ou env DRIVE_PASTA_PEDIDOS)")
    p.add_argument("--org", default="pocs")
    p.add_argument("--intervalo", type=int, default=INTERVALO_PADRAO,
                   help=f"segundos entre duas olhadas (padrao: {INTERVALO_PADRAO})")
    p.add_argument("--uma-vez", action="store_true",
                   help="atende o que estiver pendente e sai")
    p.add_argument("--simular", action="store_true",
                   help="baixa e valida, mas NAO cria nada")
    p.add_argument("--gravar", action="store_true",
                   help="grava a identidade visual (o catalogo e o portal sao "
                        "criados de qualquer jeito quando nao ha --simular)")
    p.add_argument("--callback", default=os.environ.get("MITRA_CALLBACK_URL"))
    p.add_argument("--callback-token", default=os.environ.get("MITRA_CALLBACK_TOKEN"))
    p.add_argument("--desde-agora", action="store_true",
                   help="ignora o que ja esta na pasta; atende so o que chegar "
                        "daqui para frente")
    args = p.parse_args(argv)

    if not args.pasta:
        p.error("passe --pasta <id> ou defina DRIVE_PASTA_PEDIDOS")

    service = servico_drive()
    ids_vistos, pedidos_vistos = ja_rodou()

    if args.desde_agora:
        for item in listar(service, args.pasta):
            ids_vistos.add(item["id"])
        print(f"[INFO] {len(ids_vistos)} arquivo(s) ja na pasta foram marcados "
              f"como vistos (--desde-agora).")

    print(f"[INFO] Vigiando a pasta {args.pasta} a cada {args.intervalo}s. "
          f"Ctrl+C para parar.")
    if args.simular:
        print("[INFO] Modo --simular: nada sera criado.")

    while True:
        try:
            arquivos = listar(service, args.pasta)
        except Exception as e:
            print(f"[AVISO] Falha ao listar o Drive ({type(e).__name__}: {e}). "
                  f"Tento de novo em {args.intervalo}s.")
            if args.uma_vez:
                return 1
            time.sleep(args.intervalo)
            continue

        # Do mais antigo para o mais novo: a fila e por ordem de chegada.
        novos = [a for a in reversed(arquivos)
                 if a["name"].lower().endswith(".json")
                 and not a["name"].lower().endswith(".resumo.json")
                 and a["id"] not in ids_vistos]

        for item in novos:
            ids_vistos.add(item["id"])
            try:
                resultado = atender(service, item, arquivos, args)
            except Exception as e:
                resultado = {"pedido_id": f"drive-{item['id'][:12]}",
                             "status": "falhou", "drive_file_id": item["id"],
                             "observacoes": f"{type(e).__name__}: {e}"}

            if resultado.get("pedido_id") in pedidos_vistos:
                print(f"  [INFO] pedido {resultado['pedido_id']} ja foi atendido "
                      f"antes. Nao reenvio o callback.")
                continue
            pedidos_vistos.add(resultado.get("pedido_id"))
            resultado.setdefault("drive_file_id", item["id"])

            if resultado["status"] != "simulado":
                anotar(resultado)
                ok, detalhe = avisar_mitra(args.callback, args.callback_token, resultado)
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
