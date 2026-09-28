"""montar_poc.py - Escreve o {empresa}_poc.json a partir da coleta e das decisoes.

    python "Criar Portais/montar_poc.py" --coleta coleta.json --empresa "Bob Center" \
        --setor "Suprimentos — Bobinas" --descricao "Distribuidora de..." \
        --cats "Bobinas de Papel;Etiquetas Adesivas;Etiquetadoras" \
        --itens "3:0,7:0,12:1,15:1,18:2,22:2" [--core 4] [--tps "2:30,3:15,4:5"] \
        [--grade "15:Tamanho=P,M,G"] [--saida "Arquivos Json/bobcenter_poc.json"]

O agente decide (quais itens, quais categorias, ramo); o script escreve o
boilerplate — SKU, min/mult, criterios por categoria, TPs, descontos, grade —
e ja roda o validador. Existe porque escrever o JSON a mao era a maior fatia
de output de cada POC (14/09/2026) e a origem dos erros repetidos: sku
faltando, preco em centavos, colchete no salvar_id_como.

`--itens` = "indice_na_coleta:categoria[:Nome[:preco]]" (categoria e o indice
em --cats; Nome e preco so quando a coleta veio sem — landing sem <img alt>,
site sem preco publico). Preco passado aqui e estimativa do agente e continua
marcado como `_preco_estimado`.
Preco null na coleta vira estimativa (mediana dos que existem, ou 100.00) e
o item ganha `_preco_estimado: true` no request, para a entrega dizer isso.
"""

import argparse
import copy
import json
import re
import statistics
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
TEMPLATE = AQUI / "template_poc.json"
VARIACOES = AQUI / "template_variacoes.json"
DB_ID = "5ba882ff-ba29-4599-b583-0bf9b8913b19"
# ~30% em 1/1; o resto coerente com caixa/pacote. Ciclico para ser reproduzivel.
MIN_MULT = [(1, 1), (6, 6), (1, 1), (10, 10), (2, 2), (12, 12), (1, 1), (5, 5), (3, 6), (4, 4)]


def slug(txt):
    s = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def prefixo(empresa):
    letras = re.sub(r"[^A-Z]", "", unicodedata.normalize("NFKD", empresa).encode("ascii", "ignore").decode().upper())
    return (letras[:3] or "SKU").ljust(3, "X")


def _criterio(nome, chave, campo, valor):
    return {"name": nome, "database_id": DB_ID,
            "config": {campo: {"key": chave, "values": [valor], "type": "FIELD", "config": None}}}


def montar(coleta, empresa, setor, descricao, cats, itens, core=4, tps=None, grade=None, hoje=None):
    hoje = hoje or date.today().isoformat()
    tps = tps or {2: 5, 3: 15, 4: 30}
    grade = grade or {}
    if core in tps and tps[core] != max(tps.values()):
        # maior desconto vai no perfil mais aderente: troca com quem tinha o maior
        alvo = max(tps, key=tps.get)
        tps[core], tps[alvo] = tps[alvo], tps[core]

    T = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    J = json.loads(json.dumps(T, ensure_ascii=False).replace("EMPRESA", empresa).replace("YYYY-MM-DD", hoje))
    J["_instrucoes"] = f"Gerado por montar_poc.py em {hoje} a partir de {coleta.get('site', '?')} ({coleta.get('plataforma', '?')})."
    J["descricao_empresa"], J["setor"] = descricao, setor
    etapas = {e["endpoint"]: e for e in J["etapas"]}

    # categorias
    etapas["categories"]["requests"] = [
        {"label": c, "salvar_id_como": f"cat_ids_{i}", "payload": {"name": c, "active": True, "images": []}}
        for i, c in enumerate(cats)]

    # produtos
    base = etapas["products"]["requests"][0]["payload"]
    pre = prefixo(empresa)
    precos = [coleta["itens"][t[0]]["preco"] for t in itens if coleta["itens"][t[0]].get("preco")]
    estimado = round(statistics.median(precos), 2) if precos else 100.0
    reqs = []
    for n, item in enumerate(itens, 1):
        idx, ci = item[0], item[1]
        it = dict(coleta["itens"][idx])
        if len(item) > 2 and item[2]:
            it["nome"] = item[2]
        preco_agente = item[3] if len(item) > 3 else None
        if preco_agente:
            it["preco"] = preco_agente
        if not it.get("nome"):
            raise SystemExit(f"[ERRO] item {idx} sem nome na coleta — passe 'idx:cat:Nome' em --itens")
        if not it.get("imagem"):
            raise SystemExit(f"[ERRO] item {idx} ({it.get('nome')}) sem imagem — todo produto precisa de temp_image_url")
        if not 0 <= ci < len(cats):
            raise SystemExit(f"[ERRO] item {idx}: categoria {ci} fora de --cats (0..{len(cats) - 1})")
        p = copy.deepcopy(base)
        mn, ml = MIN_MULT[(n - 1) % len(MIN_MULT)]
        sku = f"{pre}-{n:03d}"
        p.update(name=it["nome"], description=it.get("descricao") or f"{it['nome']} — {cats[ci]}.",
                 category_id=f"{{{{cat_ids_{ci}}}}}", highlight=n <= 3,
                 price=float(it["preco"] or estimado), minimum_for_sale=mn, multiple_for_sale=ml)
        p["sku"] = sku
        if it.get("video"):
            p["video_url"] = it["video"]
        r = {"label": f"{sku} — {it['nome']}", "temp_image_url": it["imagem"], "payload": p}
        if not coleta["itens"][idx].get("preco"):
            r["_preco_estimado"] = True
        if idx in grade:
            eixo, valores = grade[idx]
            p["variations"] = [{
                "sku": f"{sku}-{slug(v).upper()[:6]}", "price": p["price"], "stock": 100,
                "variation_weight": 0.5, "variation_width": 20.0, "variation_height": 10.0, "variation_depth": 15.0,
                "packaging_weight": 0.6, "packaging_width": 22.0, "packaging_height": 12.0, "packaging_depth": 17.0,
                "images": [], "values": [{"variation_id": f"{{{{variation_{slug(eixo)}_id}}}}", "name": eixo, "value": v}],
            } for v in valores]
        reqs.append(r)
    etapas["products"]["requests"] = reqs

    # grade: etapa variations antes de products, um eixo por nome
    eixos = {}
    for eixo, valores in grade.values():
        eixos.setdefault(eixo, [])
        eixos[eixo] += [v for v in valores if v not in eixos[eixo]]
    if eixos:
        V = json.loads(VARIACOES.read_text(encoding="utf-8"))
        cor = V["etapa_variations"]["requests"][0]["payload"]
        vreqs = []
        for eixo, valores in eixos.items():
            payload = {"name": eixo, "active": True, "values": valores}
            if slug(eixo) == "cor":
                payload = copy.deepcopy(cor)
                faltam = [v for v in valores if v not in payload["values"]]
                if faltam:
                    raise SystemExit(f"[ERRO] cores fora da paleta do template: {faltam} — acrescente em template_variacoes.json")
            vreqs.append({"label": f"Criar Variacao: {eixo}", "salvar_id_como": f"variation_{slug(eixo)}_id", "payload": payload})
        pos = J["etapas"].index(etapas["products"])
        J["etapas"].insert(pos, {"nome": "VARIACOES", "endpoint": "variations", "requests": vreqs})

    # criterios: marca x2 + um por categoria
    creqs = etapas["criteria"]["requests"][:2]
    for i, c in enumerate(cats):
        creqs.append({"label": f"Criterio Categoria (DESCONTO) - {c}", "salvar_id_como": f"criteria_cat_{slug(c)}_id",
                      "payload": _criterio(f"{empresa} — {c} (Desconto)", "this.CODCATEGORIA", "categories", f"{{{{cat_ids_{i}}}}}")})
    etapas["criteria"]["requests"] = creqs

    # tabelas de preco
    tp0 = etapas["price-tables"]["requests"][0]
    treqs = []
    for n, (perfil, desc) in enumerate(sorted(tps.items()), 1):
        t = copy.deepcopy(tp0)
        t["label"] = t["payload"]["name"] = f"Tabela {n} | {empresa}"
        t["salvar_id_como"] = f"tp_{n}_id"
        t["payload"]["criteria"][0]["value"] = desc
        t["payload"]["profiles"] = [{"profile_id": str(perfil)}]
        treqs.append(t)
    etapas["price-tables"]["requests"] = treqs

    # descontos: progressivo na cat 0, fixo na cat 1 (ou na 0 se so ha uma)
    d0, d1 = etapas["discounts"]["requests"]
    d0["payload"]["criteria"][0]["criteria_id"] = f"{{{{criteria_cat_{slug(cats[0])}_id}}}}"
    d0["payload"]["profiles"] = [{"profile_id": str(core)}]
    c1 = cats[1] if len(cats) > 1 else cats[0]
    d1["label"] = f"Desconto Fixo 7% — {c1} | {empresa}"
    d1["payload"]["name"] = f"7% OFF {empresa} — {c1}"
    d1["payload"]["criteria"][0]["criteria_id"] = f"{{{{criteria_cat_{slug(c1)}_id}}}}"

    # renumera as etapas
    for n, e in enumerate(J["etapas"], 1):
        e["nome"] = f"{n}. " + re.sub(r"^\d+\.\s*", "", e["nome"])
    return J


def _parse_itens(s):
    out = []
    for tok in s.split(","):
        i, c, *resto = tok.split(":", 3)
        nome = resto[0].strip() if resto else ""
        preco = float(resto[1]) if len(resto) > 1 and resto[1].strip() else None
        out.append((int(i), int(c), nome, preco))
    return out


def _parse_tps(s):
    return {int(k): float(v) if "." in v else int(v) for k, v in (t.split(":") for t in s.split(","))}


def _parse_grade(lista):
    g = {}
    for s in lista or []:
        idx, resto = s.split(":", 1)
        eixo, valores = resto.split("=", 1)
        g[int(idx)] = (eixo.strip(), [v.strip() for v in valores.split(",")])
    return g


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--coleta", required=True, help="JSON do coletar_site.py")
    p.add_argument("--empresa", required=True)
    p.add_argument("--setor", required=True)
    p.add_argument("--descricao", required=True)
    p.add_argument("--cats", required=True, help="categorias separadas por ';'")
    p.add_argument("--itens", required=True, help="'idx:cat[:Nome[:preco]],...'")
    p.add_argument("--core", type=int, default=4, help="perfil com maior desconto (2 Industria, 3 Distribuidor, 4 Varejo)")
    p.add_argument("--tps", default="2:5,3:15,4:30", help="'perfil:desconto,...'")
    p.add_argument("--grade", action="append", help="'idx:Eixo=v1,v2' (repetir por produto)")
    p.add_argument("--saida", help="padrao: Arquivos Json/<slug>_poc.json")
    p.add_argument("--sem-validar", action="store_true")
    a = p.parse_args(argv)

    coleta = json.loads(Path(a.coleta).read_text(encoding="utf-8"))
    J = montar(coleta, a.empresa, a.setor, a.descricao, [c.strip() for c in a.cats.split(";")],
               _parse_itens(a.itens), a.core, _parse_tps(a.tps), _parse_grade(a.grade))
    saida = Path(a.saida) if a.saida else RAIZ / "Arquivos Json" / f"{slug(a.empresa)}_poc.json"
    saida.write_text(json.dumps(J, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n_est = sum(1 for r in J["etapas"][[e["endpoint"] for e in J["etapas"]].index("products")]["requests"] if r.get("_preco_estimado"))
    print(f"{saida}  ({len(_parse_itens(a.itens))} produtos, {n_est} com preco estimado)")
    if a.sem_validar:
        return 0
    return subprocess.call([sys.executable, str(AQUI / "validar_poc.py"), str(saida)])


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ))
    import cronometro
    with cronometro.etapa(cronometro.do_argv("--empresa", sys.argv), "Montar JSON"):
        codigo = main()
    sys.exit(codigo)
