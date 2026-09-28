"""Mede quanto cada etapa de uma POC demora e anota em logs/tempos.jsonl.

    with cronometro.etapa("Master Foods Mix", "banners"):
        ...

Uma linha por etapa: {ts, cliente, etapa, segundos, ok}. O relatorio_pocs.py
le esse arquivo. Anotar e acessorio: se o disco falhar, a POC segue.
"""

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent / "logs" / "tempos.jsonl"


def anotar(cliente, nome, segundos, ok=True, arquivo=None):
    linha = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "cliente": cliente, "etapa": nome, "segundos": round(segundos, 1), "ok": ok}
    try:
        destino = Path(arquivo) if arquivo else ARQUIVO
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError:
        pass


def do_argv(bandeira, argv, padrao="?"):
    """Valor de `--bandeira X` na linha de comando; quem chama e um __main__."""
    try:
        return argv[argv.index(bandeira) + 1]
    except (ValueError, IndexError):
        return padrao


@contextmanager
def etapa(cliente, nome, arquivo=None):
    inicio = time.perf_counter()
    ok = False
    try:
        yield
        ok = True
    finally:
        anotar(cliente, nome, time.perf_counter() - inicio, ok, arquivo)
