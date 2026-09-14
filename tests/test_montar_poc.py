"""montar_poc.py contra o validar_poc.py: o que passa e o que o validador barra.

Cada caso monta um JSON de verdade, grava em tmp e roda o validador como
subprocesso — e o mesmo portao que o lote usa.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "Criar Portais"))
import montar_poc  # noqa: E402

VALIDADOR = RAIZ / "Criar Portais" / "validar_poc.py"


def coleta(n=24, preco=True):
    return {"site": "https://x/", "plataforma": "teste", "itens": [
        {"nome": f"Produto {i}", "preco": (10.0 + i) if preco else None,
         "imagem": f"https://img/{i}.jpg", "url": "https://x/p"} for i in range(n)]}


def validar(J, tmp_path):
    arq = tmp_path / "acme_poc.json"
    arq.write_text(json.dumps(J, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(VALIDADOR), str(arq)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def _montar(**kw):
    base = dict(coleta=coleta(), empresa="Acme Ltda", setor="Setor — Sub", descricao="Desc.",
                cats=["Cat A", "Cat B", "Cat C"], itens=[(i, i % 3) for i in range(9)])
    base.update(kw)
    return montar_poc.montar(**base)


def test_padrao_9_produtos_3_cats(tmp_path):
    J = _montar()
    code, out = validar(J, tmp_path)
    assert code == 0, out
    prods = [e for e in J["etapas"] if e["endpoint"] == "products"][0]["requests"]
    assert [r["payload"]["sku"] for r in prods][:2] == ["ACM-001", "ACM-002"]
    assert sum(r["payload"]["highlight"] for r in prods) == 3
    assert all(r["temp_image_url"] for r in prods)
    assert any(r["payload"]["minimum_for_sale"] > 1 for r in prods)


def test_core_recebe_maior_desconto(tmp_path):
    J = _montar(core=2)
    tps = [e for e in J["etapas"] if e["endpoint"] == "price-tables"][0]["requests"]
    por_perfil = {t["payload"]["profiles"][0]["profile_id"]: t["payload"]["criteria"][0]["value"] for t in tps}
    assert por_perfil["2"] == 30 and por_perfil["4"] == 5
    assert validar(J, tmp_path)[0] == 0


def test_preco_estimado_marcado(tmp_path):
    J = _montar(coleta=coleta(preco=False))
    prods = [e for e in J["etapas"] if e["endpoint"] == "products"][0]["requests"]
    assert all(r.get("_preco_estimado") for r in prods)
    assert all(r["payload"]["price"] == 100.0 for r in prods)
    assert validar(J, tmp_path)[0] == 0


def test_grade_tamanho_e_cor(tmp_path):
    J = _montar(grade={0: ("Tamanho", ["P", "M", "G"]), 4: ("Cor", ["Preto", "Vermelho"])})
    endpoints = [e["endpoint"] for e in J["etapas"]]
    assert endpoints.index("variations") < endpoints.index("products")
    var = [e for e in J["etapas"] if e["endpoint"] == "variations"][0]["requests"]
    cor = [v for v in var if v["payload"]["name"] == "Cor"][0]["payload"]
    assert cor["display_type"] == "COLOR" and cor["variant_options"]
    prods = [e for e in J["etapas"] if e["endpoint"] == "products"][0]["requests"]
    assert len(prods[0]["payload"]["variations"]) == 3
    assert prods[0]["payload"]["variations"][0]["sku"] == "ACM-001-P"
    code, out = validar(J, tmp_path)
    assert code == 0, out


def test_cor_fora_da_paleta_barra():
    with pytest.raises(SystemExit, match="fora da paleta"):
        _montar(grade={0: ("Cor", ["Magenta Neon"])})


def test_20_produtos_passa_com_aviso(tmp_path):
    J = _montar(itens=[(i, i % 3) for i in range(20)])
    code, out = validar(J, tmp_path)
    assert code == 0, out
    assert "20 produtos" in out


def test_1_categoria_validador_barra(tmp_path):
    J = _montar(cats=["Unica"], itens=[(i, 0) for i in range(6)])
    code, out = validar(J, tmp_path)
    assert code != 0 and "CATEGORIAS: esperado 3" in out


def test_1_tabela_de_preco_validador_barra(tmp_path):
    J = _montar(tps={2: 10})
    code, out = validar(J, tmp_path)
    assert code != 0 and "TPs: esperado exatamente 3" in out


def test_spread_timido_validador_barra(tmp_path):
    J = _montar(tps={2: 8, 3: 10, 4: 12})
    code, out = validar(J, tmp_path)
    assert code != 0 and "timida" in out


def test_item_sem_imagem_barra():
    c = coleta()
    c["itens"][2]["imagem"] = None
    with pytest.raises(SystemExit, match="sem imagem"):
        _montar(coleta=c)


def test_categoria_fora_da_lista_barra():
    with pytest.raises(SystemExit, match="fora de --cats"):
        _montar(itens=[(0, 5)])


def test_cli_grava_e_valida(tmp_path):
    arq = tmp_path / "coleta.json"
    arq.write_text(json.dumps(coleta()), encoding="utf-8")
    saida = tmp_path / "acme_poc.json"
    code = montar_poc.main(["--coleta", str(arq), "--empresa", "Acme", "--setor", "S", "--descricao", "D",
                            "--cats", "A;B;C", "--itens", "0:0,1:0,2:1,3:1,4:2,5:2",
                            "--grade", "0:Tamanho=P,M", "--saida", str(saida)])
    assert code == 0 and saida.exists()


def test_nome_no_itens_quando_coleta_sem_nome(tmp_path):
    c = coleta()
    for i in c["itens"]:
        i["nome"] = ""
    with pytest.raises(SystemExit, match="sem nome"):
        _montar(coleta=c)
    J = _montar(coleta=c, itens=[(i, i % 3, f"Nome {i}") for i in range(6)])
    prods = [e for e in J["etapas"] if e["endpoint"] == "products"][0]["requests"]
    assert prods[0]["payload"]["name"] == "Nome 0"
    assert montar_poc._parse_itens("3:0:Fio Nylon 3-0:12.5,4:1")[0] == (3, 0, "Fio Nylon 3-0", 12.5)
    assert validar(J, tmp_path)[0] == 0


def test_preco_do_agente_entra_e_segue_marcado(tmp_path):
    J = _montar(coleta=coleta(preco=False), itens=[(i, 0, "", 5.0 + i) for i in range(6)])
    prods = [e for e in J["etapas"] if e["endpoint"] == "products"][0]["requests"]
    assert [r["payload"]["price"] for r in prods] == [5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert all(r.get("_preco_estimado") for r in prods)
    assert validar(J, tmp_path)[0] == 0
