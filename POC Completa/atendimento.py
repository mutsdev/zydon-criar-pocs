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
from pathlib import Path

import requests

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
PORTAIS = RAIZ / "Criar Portais"
IDENTIDADE = RAIZ / "Identidade Visual"

for _caminho in (str(AQUI), str(PORTAIS)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

import descobrir_url  # noqa: E402

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


# ------------------------------------------------------------------ execucao
def prefixo(nome):
    """'uze_nails_poc.json' -> 'uze_nails'."""
    base = re.sub(r"\.json$", "", str(nome), flags=re.I)
    return re.sub(r"_poc$", "", base, flags=re.I)


def baixar_logo(url, nome_base):
    """Devolve o caminho local da logo, ou None."""
    if not url:
        return None
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [AVISO] logo_url falhou: {type(e).__name__}")
        return None
    extensao = Path(url.split("?")[0]).suffix.lower()
    if extensao not in EXTENSOES_LOGO:
        extensao = ".png"
    alvo = DESTINO_LOGO / f"{nome_base}_logo{extensao}"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(r.content)
    return alvo


def _rodar(comando):
    return subprocess.run(comando, cwd=str(RAIZ),
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def validar(caminho_json):
    """(ok, saida) do validar_poc.py."""
    p = _rodar([sys.executable, str(PORTAIS / "validar_poc.py"), str(caminho_json)])
    return p.returncode == 0, (p.stdout or "") + (p.stderr or "")


def executar(caminho_json, logo, org, nome_cliente, gravar):
    """(codigo, saida) do pipeline completo."""
    if logo:
        comando = [sys.executable, str(AQUI / "criar_poc_completo.py"),
                   str(caminho_json), org, "--logo", str(logo),
                   "--nome", nome_cliente]
        if gravar:
            comando.append("--gravar")
    else:
        # Sem logo o criar_poc_completo nem comeca (--logo e obrigatorio la, e
        # com razao: o caso normal tem logo). Cai no runner puro.
        comando = [sys.executable, str(AQUI / "criar_poc.py"), str(caminho_json), org]
    p = _rodar(comando)
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
    codigo, saida = executar(caminho_json, logo, org, poc.get("empresa", ""), gravar)
    print(saida[-3000:])

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


# ------------------------------------------------------------------ callback
def avisar_mitra(callback_url, token, corpo):
    """(ok, detalhe). Nunca levanta: callback nao e a entrega."""
    if not callback_url:
        return False, "sem callback_url"
    try:
        r = requests.post(callback_url, json=dict(corpo, callback_token=token),
                          timeout=60)
    except requests.RequestException as e:
        return False, type(e).__name__
    # 2xx nao quer dizer entregue — a funcao do Mitra responde 2xx ate quando
    # rejeita, de proposito. Ver ENTREGA.md: confira o efeito, nao a resposta.
    try:
        dados = r.json()
    except ValueError:
        return False, f"HTTP {r.status_code}, corpo nao-JSON"
    return bool(dados.get("ok")), f"HTTP {r.status_code} {dados}"
