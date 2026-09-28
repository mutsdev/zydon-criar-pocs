"""Relatorio de quanto cada POC custou: tempo, tokens e etapa mais lenta.

    python relatorio_pocs.py
    python relatorio_pocs.py --desde 2026-09-23 --cliente "Master Foods Mix"

Duas fontes:
  - logs/tempos.jsonl (cronometro.py): segundos por etapa dos scripts. Exato,
    mas so existe para POCs rodadas depois de 28/09/2026.
  - transcripts do Claude Code (~/.claude/projects): tokens e a janela da
    conversa. A janela de um cliente vai do pedido do usuario que antecede o
    primeiro comando dele (montar_poc, criar_poc_completo, gerar_banners...) ate
    o ultimo resultado desses comandos. Isso inclui a coleta, que nao e script.

Le so timestamp, usage, model e o texto dos comandos Bash. Nunca imprime o
conteudo das mensagens.
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
TEMPOS = AQUI / "logs" / "tempos.jsonl"
SAIDA = AQUI / "relatorios" / "pocs.md"
PROJETOS = Path.home() / ".claude" / "projects"

SCRIPTS = ("montar_poc.py", "criar_poc_completo.py", "gerar_banners.py",
           "subir_banners.py", "subir_identidade.py")
NOME = re.compile(r"--(?:empresa|nome)\s+(?:\"([^\"]+)\"|'([^']+)')")
PASTA_CLIENTE = re.compile(r"saidas/([^/\"']+)/\d{4}-\d{2}-\d{2}_\d{4}")
CAMPOS = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
          "cache_read_input_tokens")

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def chave(nome):
    """'Master Foods Mix', 'master-foods-mix' e 'master_foods_mix' sao o mesmo cliente."""
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _ts(texto):
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def cliente_do_comando(comando):
    if not any(s in comando for s in SCRIPTS):
        return None
    m = NOME.search(comando)
    if m:
        return m.group(1) or m.group(2)
    m = PASTA_CLIENTE.search(comando.replace("\\", "/"))
    return m.group(1) if m else None


def ler_transcripts(raiz=PROJETOS):
    """Devolve (mensagens, comandos, pedidos) de todos os .jsonl sob `raiz`.

    mensagens: {message.id: (ts, sessao, usage)} — uma resposta vem partida em
    varias linhas com o mesmo usage repetido; somar por linha contaria 1,5x.
    comandos:  [(ts_inicio, ts_fim, sessao, cliente)]
    pedidos:   {sessao: [ts]} das mensagens que o usuario digitou.
    """
    mensagens, usos, resultados, pedidos = {}, [], {}, defaultdict(list)
    for arq in raiz.rglob("*.jsonl"):
        try:
            linhas = arq.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for linha in linhas:
            try:
                d = json.loads(linha)
            except ValueError:
                continue
            ts, sessao, msg = d.get("timestamp"), d.get("sessionId"), d.get("message")
            if not ts or not isinstance(msg, dict):
                continue
            conteudo = msg.get("content")
            itens = conteudo if isinstance(conteudo, list) else []
            if d.get("type") == "assistant":
                if msg.get("model") != "<synthetic>" and msg.get("id") and msg.get("usage"):
                    mensagens.setdefault(msg["id"], (_ts(ts), sessao, msg["usage"]))
                for it in itens:
                    if it.get("type") == "tool_use" and it.get("name") == "Bash":
                        cli = cliente_do_comando(str((it.get("input") or {}).get("command", "")))
                        if cli:
                            usos.append((it.get("id"), _ts(ts), sessao, cli))
            elif d.get("type") == "user":
                ids = [it.get("tool_use_id") for it in itens if it.get("type") == "tool_result"]
                for i in ids:
                    resultados[i] = _ts(ts)
                if not ids and not d.get("isSidechain") and not d.get("isMeta"):
                    pedidos[sessao].append(_ts(ts))
    comandos = [(ini, resultados.get(i, ini), s, c) for i, ini, s, c in usos]
    return mensagens, comandos, pedidos


def ler_tempos(arquivo=TEMPOS):
    linhas = []
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            try:
                linhas.append(json.loads(linha))
            except ValueError:
                pass
    return linhas


PAUSA = timedelta(minutes=30)


def janelas(comandos, pedidos):
    """{chave: {nome, sessao, inicio, fim}} — uma janela por rodada de cliente.

    Um cliente mexido de novo horas depois (trocar banner, renomear) vira outra
    rodada, com chave "<cliente>#2". Sem isso a janela engole a tarde inteira.
    """
    por, atual = {}, {}
    for ini, fim, sessao, nome in sorted(comandos, key=lambda c: c[0]):
        base = chave(nome)
        k = atual.get(base)
        if k is None or ini - por[k]["fim"] > PAUSA or por[k]["sessao"] != sessao:
            n = sum(1 for x in por if x.split("#")[0] == base) + 1
            k = base if n == 1 else f"{base}#{n}"
            rotulo = nome if n == 1 else f"{por[base]['nome']} ({n}ª rodada)"
            por[k] = {"nome": rotulo, "sessao": sessao, "primeiro": ini, "fim": fim}
            atual[base] = k
        j = por[k]
        j["fim"] = max(j["fim"], fim)
        if " " in nome and " " not in j["nome"] and "#" not in k:
            j["nome"] = nome  # prefere "Master Foods Mix" a "master-foods-mix"
    for j in por.values():
        antes = [t for t in pedidos.get(j["sessao"], []) if t <= j["primeiro"]]
        j["inicio"] = max(antes) if antes else j["primeiro"]
    return por


def atribuir_tokens(mensagens, jans):
    """Soma o usage de cada mensagem na janela do cliente.

    # ponytail: duas POCs intercaladas na mesma sessao — a mensagem vai para o
    # cliente cuja janela comecou por ultimo. Imprecisao aceita; marcacao
    # manual de inicio/fim resolveria.
    """
    soma = {k: dict.fromkeys(CAMPOS, 0) for k in jans}
    ordem = sorted(jans.items(), key=lambda kv: kv[1]["inicio"], reverse=True)
    for ts, sessao, uso in mensagens.values():
        for k, j in ordem:
            if j["sessao"] == sessao and j["inicio"] <= ts <= j["fim"]:
                for c in CAMPOS:
                    soma[k][c] += int(uso.get(c) or 0)
                break
    return soma


def _dur(seg):
    seg = int(seg)
    return f"{seg // 60}min{seg % 60:02d}s" if seg >= 60 else f"{seg}s"


def _k(n):
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


def montar(jans, tokens, tempos, desde=None, cliente=None):
    etapas = defaultdict(list)
    for t in tempos:
        etapas[chave(t["cliente"])].append(t)
    linhas_portal, por_etapa = [], defaultdict(list)
    for k, j in sorted(jans.items(), key=lambda kv: kv[1]["inicio"]):
        if desde and j["inicio"].date().isoformat() < desde:
            continue
        base = k.split("#")[0]
        if cliente and chave(cliente) != base:
            continue
        tk = tokens[k]
        mais_lenta = "—"
        daqui = [t for t in etapas[base] if j["inicio"] <= _ts(t["ts"]) <= j["fim"] + PAUSA]
        if daqui:
            e = max(daqui, key=lambda t: t["segundos"])
            mais_lenta = f"{e['etapa']} ({_dur(e['segundos'])})"
            for t in daqui:
                por_etapa[t["etapa"]].append(t["segundos"])
        linhas_portal.append(
            f"| {j['nome']} | {j['inicio']:%d/%m %H:%M} | {_dur((j['fim'] - j['inicio']).total_seconds())} "
            f"| {_k(tk['input_tokens'] + tk['cache_creation_input_tokens'])} | {_k(tk['output_tokens'])} "
            f"| {_k(tk['cache_read_input_tokens'])} | {mais_lenta} |")

    md = ["# Relatório de POCs", "",
          f"Gerado em {datetime.now():%d/%m/%Y %H:%M}.", "",
          "## Por portal", "",
          "| Cliente | Início (UTC) | Duração | Tokens entrada | Tokens saída | Cache lido | Etapa mais lenta |",
          "|---|---|---:|---:|---:|---:|---|", *linhas_portal, "",
          "Duração = do seu pedido até o último script do cliente terminar (inclui coleta). "
          "Cache lido custa ~10% do token de entrada.", ""]
    if por_etapa:
        md += ["## Por etapa (média entre portais)", "",
               "| Etapa | Execuções | Média | Máximo |", "|---|---:|---:|---:|"]
        for nome, seg in sorted(por_etapa.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
            md.append(f"| {nome} | {len(seg)} | {_dur(sum(seg) / len(seg))} | {_dur(max(seg))} |")
    else:
        md += ["_Sem tempos por etapa ainda: logs/tempos.jsonl nasce na próxima POC._"]
    return "\n".join(md) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--desde", help="AAAA-MM-DD")
    p.add_argument("--cliente")
    a = p.parse_args(argv)
    mensagens, comandos, pedidos = ler_transcripts()
    jans = janelas(comandos, pedidos)
    md = montar(jans, atribuir_tokens(mensagens, jans), ler_tempos(), a.desde, a.cliente)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(md, encoding="utf-8")
    print(md)
    print(f"Salvo em {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
