import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cronometro  # noqa: E402
import relatorio_pocs as rel  # noqa: E402


def _linha(tipo, ts, sessao="s1", **msg):
    return json.dumps({"type": tipo, "timestamp": ts, "sessionId": sessao, "message": msg})


def _uso(n):
    return {"input_tokens": n, "output_tokens": n, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0}


def _bash(ts, id_, cmd, msg_id):
    return _linha("assistant", ts, id=msg_id, model="m", usage=_uso(1),
                  content=[{"type": "tool_use", "id": id_, "name": "Bash",
                            "input": {"command": cmd}}])


def _resultado(ts, id_):
    return _linha("user", ts, content=[{"type": "tool_result", "tool_use_id": id_}])


def test_mensagem_partida_conta_uma_vez_e_janelas_separam_clientes(tmp_path):
    linhas = [
        _linha("user", "2026-09-28T10:00:00Z", content="crie a Alfa"),
        _linha("assistant", "2026-09-28T10:01:00Z", id="a1", model="m", usage=_uso(100), content=[]),
        _linha("assistant", "2026-09-28T10:01:01Z", id="a1", model="m", usage=_uso(100), content=[]),
        _bash("2026-09-28T10:02:00Z", "t1", 'python montar_poc.py --empresa "Alfa"', "a2"),
        _resultado("2026-09-28T10:05:00Z", "t1"),
        _linha("user", "2026-09-28T11:00:00Z", content="crie a Beta"),
        _linha("assistant", "2026-09-28T11:01:00Z", id="b1", model="m", usage=_uso(7), content=[]),
        _bash("2026-09-28T11:02:00Z", "t2", 'python gerar_banners.py auto --nome "Beta"', "b2"),
        _resultado("2026-09-28T11:03:00Z", "t2"),
    ]
    (tmp_path / "x.jsonl").write_text("\n".join(linhas), encoding="utf-8")

    msgs, cmds, pedidos = rel.ler_transcripts(tmp_path)
    jans = rel.janelas(cmds, pedidos)
    tokens = rel.atribuir_tokens(msgs, jans)

    assert tokens["alfa"]["input_tokens"] == 101   # a1 uma vez + a2
    assert tokens["beta"]["input_tokens"] == 8
    assert (jans["alfa"]["fim"] - jans["alfa"]["inicio"]).total_seconds() == 300


def test_cliente_pela_pasta_de_banners():
    cmd = 'python subir_banners.py --pasta "Identidade Visual/saidas/master-foods-mix/2026-09-28_0903"'
    assert rel.chave(rel.cliente_do_comando(cmd)) == rel.chave("Master Foods Mix")


def test_etapa_com_erro_anota_falha_e_repassa(tmp_path):
    destino = tmp_path / "tempos.jsonl"
    with pytest.raises(RuntimeError):
        with cronometro.etapa("Alfa", "Banners", arquivo=destino):
            raise RuntimeError("x")
    linha = json.loads(destino.read_text(encoding="utf-8"))
    assert linha["ok"] is False and linha["cliente"] == "Alfa"
