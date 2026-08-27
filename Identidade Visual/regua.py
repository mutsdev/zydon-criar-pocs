"""Carrega `regua.json`. Os limiares moram fora do código de propósito.

Quando o João Pedro olha a folha de contato e discorda do veredito, o conserto
é editar um número aqui — não caçar constante espalhada. É essa separação que
faz o julgamento humano virar ajuste na iteração seguinte (plano, §5).
"""

import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CAMINHO = AQUI / "regua.json"


def carregar(caminho=None):
    alvo = Path(caminho) if caminho else CAMINHO
    if not alvo.exists():
        raise FileNotFoundError(f"régua não encontrada: {alvo}")
    return json.loads(alvo.read_text(encoding="utf-8"))
