"""
validar_poc.py - Valida um {empresa}_poc.json contra o checklist pre-entrega.

Roda TODO o checklist do CLAUDE.md automaticamente (padrao vigente desde 2026-07-02):
estrutura das 6 etapas, criterios separados, TPs 2/3/4 "Tabela 1/2/3",
campos obrigatorios de produto, imagens inline, placeholders, campos proibidos, etc.

Uso:
  python validar_poc.py empresa_poc.json
Saida:
  [ERRO]  -> bloqueia entrega (exit code 1)
  [AVISO] -> conferir manualmente (nao bloqueia)
"""

import json
import os
import re
import sys

DATABASE_ID_POCS = "5ba882ff-ba29-4599-b583-0bf9b8913b19"
# database_id da base "Produtos" e POR ORGANIZACAO. Descobrir numa org nova com:
#   GET https://api.zydon.com.br/api/database/databases  -> item "Produtos"
DATABASE_IDS_CONHECIDOS = {
    "5ba882ff-ba29-4599-b583-0bf9b8913b19": "orgs de POC (zydon/poc/pocs)",
    "20ac282d-5a30-4f4d-aac4-1e625fd0e814": "org 019ec802 'integracoes' (Sankhya B2B - AGROMINAS/Portal Base)",
    "1c406da5-e74a-43c3-a80c-8ece65ba804f": "org 019e6f55 'integracoes' (chaves antigas - NAO usar)",
}
# Perfis sao TIPOS DE COMPRADOR, e sao POR ORGANIZACAO (como database_id e
# portal_origem_id). Na org de POC: 2=Industria/Manufatura, 3=Distribuidor,
# 4=Varejo — uma tabela de preco para cada. NAO sao faixas de preco nem o
# segmento do cliente; ja confundiram com os dois. Listar numa org nova:
#   GET https://api.zydon.com.br/api/sales/profiles?perPage=100
TP_PROFILES_PADRAO = ["2", "3", "4"]

erros, avisos = [], []


def erro(msg):
    erros.append(msg)


def aviso(msg):
    avisos.append(msg)


def etapa_por_endpoint(poc, endpoint):
    return [e for e in poc.get("etapas", []) if e.get("endpoint") == endpoint]


def validar(path):
    # --- arquivo / naming ---
    nome_arq = os.path.basename(path)
    if not nome_arq.endswith("_poc.json"):
        aviso(f"Naming: '{nome_arq}' fora do padrao '{{empresa}}_poc.json'")
    if nome_arq.startswith("poc_"):
        erro(f"Naming: '{nome_arq}' usa padrao antigo abandonado 'poc_{{empresa}}.json'")

    try:
        poc = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        erro(f"JSON invalido: {e}")
        return

    # --- campos raiz ---
    for campo in ("empresa", "descricao_empresa", "gerado_em", "setor", "portal_name"):
        if not poc.get(campo):
            erro(f"Campo raiz ausente/vazio: '{campo}'")
    if poc.get("portal_listing_rule_id") != "{{criteria_listagem_id}}":
        erro(f"portal_listing_rule_id deve ser '{{{{criteria_listagem_id}}}}' "
             f"(atual: {poc.get('portal_listing_rule_id')!r})")

    # --- etapas presentes ---
    esperados = ["brands", "categories", "products", "criteria", "price-tables", "discounts"]
    endpoints = [e.get("endpoint") for e in poc.get("etapas", [])]
    for ep in esperados:
        if ep not in endpoints:
            erro(f"Etapa ausente: endpoint '{ep}'")
    if [e for e in endpoints if e in esperados] != [e for e in esperados if e in endpoints]:
        aviso(f"Ordem das etapas difere do padrao {esperados}: {endpoints}")

    ids_definidos = {"run_ts"}
    ids_usados = set()
    criterios_ids = set()  # todos os salvar_id_como da etapa criteria (marca e categoria)
    criterios_categoria = set()  # apenas os criterios por categoria (config.categories) — usados nos descontos

    def registrar_placeholders(obj):
        for m in re.findall(r"\{\{(\w+)\}\}", json.dumps(obj, ensure_ascii=False)):
            ids_usados.add(m)

    # --- 1. MARCA ---
    for e in etapa_por_endpoint(poc, "brands"):
        reqs = e.get("requests", [])
        if len(reqs) != 1:
            aviso(f"MARCA: esperado 1 request, encontrado {len(reqs)}")
        for r in reqs:
            if r.get("salvar_id_como") != "brand_id":
                erro(f"MARCA: salvar_id_como deve ser 'brand_id' (atual: {r.get('salvar_id_como')!r})")
            if r.get("payload", {}).get("images") != []:
                erro("MARCA: payload.images deve ser []")
            ids_definidos.add(r.get("salvar_id_como") or "")

    # --- 2. CATEGORIAS ---
    for e in etapa_por_endpoint(poc, "categories"):
        reqs = e.get("requests", [])
        if len(reqs) != 3:
            erro(f"CATEGORIAS: esperado 3, encontrado {len(reqs)}")
        for i, r in enumerate(reqs):
            sid = r.get("salvar_id_como", "")
            if "[" in sid or "]" in sid:
                erro(f"CATEGORIAS: salvar_id_como com colchetes ('{sid}') — usar underscore (cat_ids_{i})")
            elif sid != f"cat_ids_{i}":
                aviso(f"CATEGORIAS: salvar_id_como '{sid}' (esperado 'cat_ids_{i}')")
            if r.get("payload", {}).get("images") != []:
                erro(f"CATEGORIAS: '{r.get('label')}' payload.images deve ser []")
            ids_definidos.add(sid)

    # --- 2b. VARIACOES (opcional — so quando a POC usa grade de variantes) ---
    variacoes_valores = {}  # salvar_id_como -> {"name": ..., "values": [...]}
    for e in etapa_por_endpoint(poc, "variations"):
        idx_var = endpoints.index("variations")
        if "products" in endpoints and idx_var > endpoints.index("products"):
            erro("VARIACOES: a etapa 'variations' deve vir ANTES de 'products' "
                 "(os produtos referenciam {{variation_*_id}})")
        for r in e.get("requests", []):
            lbl = r.get("label", "?")
            p = r.get("payload", {})
            sid = r.get("salvar_id_como") or ""
            if not sid:
                erro(f"VARIACAO '{lbl}': falta 'salvar_id_como' (ex.: variation_cor_id)")
            elif not re.fullmatch(r"variation_\w+_id", sid):
                aviso(f"VARIACAO '{lbl}': salvar_id_como '{sid}' fora do padrao 'variation_<slug>_id'")
            ids_definidos.add(sid)
            if not str(p.get("name") or "").strip():
                erro(f"VARIACAO '{lbl}': payload.name obrigatorio")
            if p.get("active") is not True:
                erro(f"VARIACAO '{lbl}': active deve ser true")
            vals = p.get("values")
            if not isinstance(vals, list) or len(vals) < 2:
                erro(f"VARIACAO '{lbl}': 'values' deve ser lista com 2+ valores")
            elif len(set(vals)) != len(vals):
                erro(f"VARIACAO '{lbl}': valores duplicados em 'values'")
            else:
                variacoes_valores[sid] = {"name": p.get("name"), "values": [str(v) for v in vals]}
            # --- eixo de COR: swatch com hex ---
            eh_cor = "cor" in str(p.get("name") or "").strip().lower()
            dt, vopts = p.get("display_type"), p.get("variant_options")
            if eh_cor:
                if dt != "COLOR":
                    erro(f"VARIACAO '{lbl}': eixo de cor precisa de display_type 'COLOR' "
                         f"(atual: {dt!r}) — sem isso a loja mostra texto, nao o swatch")
                if not isinstance(vopts, list) or not vopts:
                    erro(f"VARIACAO '{lbl}': eixo de cor sem 'variant_options' "
                         f"(copiar 'variacao_cor' de template_variacoes.json)")
            elif dt is not None:
                erro(f"VARIACAO '{lbl}': display_type so vale para eixo de cor (atual: {dt!r})")
            if isinstance(vopts, list) and vopts:
                nomes_opt = [o.get("name") for o in vopts]
                if isinstance(vals, list) and nomes_opt != [str(v) for v in vals]:
                    erro(f"VARIACAO '{lbl}': 'variant_options' e 'values' divergem "
                         f"(mesmos nomes, mesma ordem)")
                for o in vopts:
                    hexv = o.get("display_value")
                    if (dt == "COLOR" or hexv is not None) and \
                            not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(hexv or "")):
                        erro(f"VARIACAO '{lbl}' / cor '{o.get('name')}': display_value "
                             f"{hexv!r} nao e hex #RRGGBB")
                dups_h = sorted({str(o.get("display_value")) for o in vopts
                                 if [x.get("display_value") for x in vopts].count(o.get("display_value")) > 1})
                if dt == "COLOR" and dups_h:
                    aviso(f"VARIACAO '{lbl}': hex repetido em cores diferentes: {dups_h}")

    # --- 3. PRODUTOS ---
    minmults = []
    skus_vistos = []
    precos = []
    for e in etapa_por_endpoint(poc, "products"):
        reqs = e.get("requests", [])
        # 5 a 12 e RECOMENDACAO para quem monta a POC, e nao portao de entrada.
        # O que manda no tempo de montagem nao e escrever o produto: e a imagem
        # dele — a Danda Pecas levou 20 minutos para 14, e o Tudo do Mar 12
        # para 13. Doze bem escolhidos demonstram tanto quanto quinze.
        #
        # Mas teto duro aqui BARRA EXECUCAO, e isso e outra coisa. Em
        # 28/08/2026 um pedido curado voltou reprovado no receptor por passar de
        # 12: catalogo pronto, executivo esperando, e nada criado por uma regra
        # que existe para economizar tempo de montagem. Se o catalogo ja existe
        # — 90 produtos vindos de um ERP, por exemplo —, o custo que a regra
        # evitava ja foi pago. Avisa e deixa passar.
        if len(reqs) < 5:
            aviso(f"PRODUTOS: apenas {len(reqs)} produtos (recomendado: 5-12)")
        if len(reqs) > 12:
            aviso(f"PRODUTOS: {len(reqs)} produtos (recomendado: 5-12). "
                  f"Passa, mas cada imagem custa tempo na montagem.")
        for r in reqs:
            lbl = r.get("label", "?")
            p = r.get("payload", {})
            registrar_placeholders(p)
            if r.get("salvar_id_como"):
                ids_definidos.add(r["salvar_id_como"])
            sku = p.get("sku")
            if not str(sku or "").strip():
                erro(f"PRODUTO '{lbl}': sem 'sku' no payload — campo Codigo/SKU e "
                     f"obrigatorio na plataforma (senao o produto entra sem codigo)")
            else:
                skus_vistos.append(str(sku).strip())
            if p.get("active") is not True:
                erro(f"PRODUTO '{lbl}': active deve ser true")
            if p.get("stock") != 100:
                aviso(f"PRODUTO '{lbl}': stock={p.get('stock')} (padrao: 100)")
            if p.get("minimum_stock") != 0:
                aviso(f"PRODUTO '{lbl}': minimum_stock={p.get('minimum_stock')} (padrao: 0)")
            if "standard_unit_id" not in p:
                erro(f"PRODUTO '{lbl}': sem standard_unit_id (usar 2; o script forca o valor)")
            if p.get("images") != []:
                erro(f"PRODUTO '{lbl}': payload.images deve ser [] — imagem vai em "
                     f"'temp_image_url' FORA do payload (URL direta causa 500 NPE)")
            if "temp_image_url" in p:
                erro(f"PRODUTO '{lbl}': temp_image_url esta DENTRO do payload — deve ficar no request")
            if not str(r.get("temp_image_url") or "").startswith("http"):
                erro(f"PRODUTO '{lbl}': sem temp_image_url — TODO produto deve ter imagem "
                     f"inline (site da marca > Mercado Livre) antes da entrega")
            preco = p.get("price")
            if isinstance(preco, (int, float)) and not isinstance(preco, bool):
                precos.append(preco)
            mn, ml = p.get("minimum_for_sale"), p.get("multiple_for_sale")
            if mn is None or ml is None:
                erro(f"PRODUTO '{lbl}': minimum_for_sale/multiple_for_sale ausentes")
            elif ml < mn:
                erro(f"PRODUTO '{lbl}': multiple_for_sale ({ml}) < minimum_for_sale ({mn})")
            else:
                minmults.append((mn, ml))
            if not str(p.get("category_id", "")).startswith("{{cat_ids_"):
                erro(f"PRODUTO '{lbl}': category_id deve ser '{{{{cat_ids_N}}}}' (atual: {p.get('category_id')!r})")
            if p.get("brand_id") != "{{brand_id}}":
                erro(f"PRODUTO '{lbl}': brand_id deve ser '{{{{brand_id}}}}'")
            for campo in ("ean_gtin", "video_url"):
                if campo not in p:
                    aviso(f"PRODUTO '{lbl}': campo '{campo}' ausente (padrao: \"\")")
            # --- grade de variacoes do produto (opcional) ---
            variacoes = p.get("variations")
            if variacoes is not None:
                if not isinstance(variacoes, list) or not variacoes:
                    erro(f"PRODUTO '{lbl}': 'variations' presente mas vazio — remover ou preencher")
                    variacoes = []
                if not variacoes_valores and variacoes:
                    erro(f"PRODUTO '{lbl}': usa 'variations' mas nao existe etapa 'variations' "
                         f"criando os eixos (Cor/Tamanho)")
                combos, skus_var = [], []
                for v in variacoes:
                    vsku = str(v.get("sku") or "").strip()
                    if not vsku:
                        erro(f"PRODUTO '{lbl}': variante sem 'sku'")
                    else:
                        skus_var.append(vsku)
                        skus_vistos.append(vsku)
                    if not isinstance(v.get("price"), (int, float)) or v.get("price") <= 0:
                        erro(f"PRODUTO '{lbl}' / variante '{vsku}': 'price' ausente ou <= 0")
                    if v.get("stock") is None:
                        erro(f"PRODUTO '{lbl}' / variante '{vsku}': 'stock' ausente")
                    if v.get("images") != []:
                        erro(f"PRODUTO '{lbl}' / variante '{vsku}': 'images' deve ser [] "
                             f"(URL direta causa 500 NPE)")
                    vals = v.get("values")
                    if not isinstance(vals, list) or not vals:
                        erro(f"PRODUTO '{lbl}' / variante '{vsku}': 'values' obrigatorio "
                             f"(um item por eixo de variacao)")
                        continue
                    chave = []
                    for val in vals:
                        vid = str(val.get("variation_id") or "")
                        m = re.fullmatch(r"\{\{(\w+)\}\}", vid)
                        if not m:
                            erro(f"PRODUTO '{lbl}' / variante '{vsku}': variation_id deve ser "
                                 f"placeholder '{{{{variation_*_id}}}}' (atual: {vid!r})")
                            continue
                        sid = m.group(1)
                        eixo = variacoes_valores.get(sid)
                        if eixo is None:
                            erro(f"PRODUTO '{lbl}' / variante '{vsku}': variation_id "
                                 f"'{{{{{sid}}}}}' nao foi criado na etapa 'variations'")
                            continue
                        if val.get("name") != eixo["name"]:
                            erro(f"PRODUTO '{lbl}' / variante '{vsku}': 'name' e "
                                 f"{val.get('name')!r}, mas a variacao '{sid}' chama-se {eixo['name']!r}")
                        if str(val.get("value")) not in eixo["values"]:
                            erro(f"PRODUTO '{lbl}' / variante '{vsku}': valor "
                                 f"{val.get('value')!r} nao esta em values de '{sid}' {eixo['values']}")
                        chave.append((sid, str(val.get("value"))))
                    if len(chave) != len(vals):
                        continue
                    eixos = [c[0] for c in chave]
                    if len(set(eixos)) != len(eixos):
                        erro(f"PRODUTO '{lbl}' / variante '{vsku}': eixo de variacao repetido")
                    combos.append(tuple(sorted(chave)))
                dups_c = sorted({c for c in combos if combos.count(c) > 1})
                if dups_c:
                    erro(f"PRODUTO '{lbl}': combinacao de variacao duplicada: {dups_c[:3]}")
                dups_s = sorted({s for s in skus_var if skus_var.count(s) > 1})
                if dups_s:
                    erro(f"PRODUTO '{lbl}': sku de variante repetido {dups_s}")
                eixos_usados = {c[0] for combo in combos for c in combo}
                if combos and len(eixos_usados) > 1:
                    esperado = 1
                    for sid in eixos_usados:
                        esperado *= len({c[1] for combo in combos for c in combo if c[0] == sid})
                    if len(combos) != esperado:
                        aviso(f"PRODUTO '{lbl}': {len(combos)} variantes para uma grade "
                              f"de {esperado} combinacoes — grade incompleta (ok se intencional)")
        if minmults and all(m == (1, 1) for m in minmults):
            aviso("PRODUTOS: todos com min/mult 1/1 — variar valores (POC fica pobre no painel)")
        dups = sorted({s for s in skus_vistos if skus_vistos.count(s) > 1})
        if dups:
            erro(f"PRODUTOS: sku(s) repetido(s) {dups} — cada produto deve ter um Codigo/SKU unico")
        # `price` vai DIRETO para a API (o criar_poc.py nao converte). POCs antigas
        # usavam centavos; o padrao hoje e reais decimais. Um catalogo inteiro de
        # inteiros com mediana alta e a assinatura do formato antigo — e o erro so
        # apareceria na frente do cliente, com preco 100x maior.
        if len(precos) >= 5:
            mediana = sorted(precos)[len(precos) // 2]
            if mediana >= 5000 and all(float(v).is_integer() for v in precos):
                erro(f"PRODUTOS: precos parecem estar em CENTAVOS (todos inteiros, "
                     f"mediana {mediana:.0f}). O padrao e REAIS decimais — 219.90 = R$ 219,90. "
                     f"O criar_poc.py nao converte: iria assim para a API. "
                     f"Se estiver certo mesmo (catalogo caro, precos redondos), "
                     f"basta uma casa decimal em qualquer produto para liberar.")

    # --- 4. CRITERIOS ---
    db_ids_vistos = set()
    for e in etapa_por_endpoint(poc, "criteria"):
        if e.get("base_url") != "https://api.zydon.com.br/api/database":
            erro("CRITERIOS: base_url deve ser 'https://api.zydon.com.br/api/database'")
        sids = [r.get("salvar_id_como") for r in e.get("requests", [])]
        for esperado in ("criteria_preco_id", "criteria_listagem_id"):
            if esperado not in sids:
                erro(f"CRITERIOS: falta criterio '{esperado}' (devem ser SEMPRE separados)")
        for r in e.get("requests", []):
            p = r.get("payload", {})
            lbl = r.get("label")
            registrar_placeholders(p)
            sid = r.get("salvar_id_como") or ""
            ids_definidos.add(sid)
            criterios_ids.add(sid)
            db_id = p.get("database_id")
            if db_id not in DATABASE_IDS_CONHECIDOS:
                erro(f"CRITERIOS '{lbl}': database_id {db_id!r} desconhecido — deve ser a base "
                     f"'Produtos' DA ORG onde a POC vai rodar. Conhecidos: "
                     + "; ".join(f"{k} = {v}" for k, v in DATABASE_IDS_CONHECIDOS.items()))
            elif db_ids_vistos and db_id not in db_ids_vistos:
                erro(f"CRITERIOS '{lbl}': database_id {db_id} difere dos outros criterios "
                     f"({', '.join(sorted(db_ids_vistos))}) — todos devem ser da mesma org")
            db_ids_vistos.add(db_id)
            cfg = p.get("config", {})
            # criteria_preco_id e criteria_listagem_id sao SEMPRE por marca;
            # criterios extras podem ser por categoria (usados em descontos por categoria).
            if sid in ("criteria_preco_id", "criteria_listagem_id"):
                b = cfg.get("brands", {})
                if b.get("key") != "this.CODIGOMARCA":
                    erro(f"CRITERIOS '{lbl}': config.brands.key deve ser 'this.CODIGOMARCA'")
                if b.get("values") != ["{{brand_id}}"]:
                    erro(f"CRITERIOS '{lbl}': config.brands.values deve ser ['{{{{brand_id}}}}']")
            elif "brands" in cfg:
                b = cfg["brands"]
                if b.get("key") != "this.CODIGOMARCA":
                    erro(f"CRITERIOS '{lbl}': config.brands.key deve ser 'this.CODIGOMARCA'")
                if b.get("values") != ["{{brand_id}}"]:
                    erro(f"CRITERIOS '{lbl}': config.brands.values deve ser ['{{{{brand_id}}}}']")
            elif "categories" in cfg:
                c = cfg["categories"]
                if c.get("key") != "this.CODCATEGORIA":
                    erro(f"CRITERIOS '{lbl}': config.categories.key deve ser 'this.CODCATEGORIA'")
                vals = c.get("values")
                if not (isinstance(vals, list) and len(vals) == 1
                        and str(vals[0]).startswith("{{cat_ids_")):
                    erro(f"CRITERIOS '{lbl}': config.categories.values deve ser ['{{{{cat_ids_N}}}}']")
                else:
                    criterios_categoria.add(sid)
            else:
                erro(f"CRITERIOS '{lbl}': config deve conter 'brands' (marca) ou 'categories' (categoria)")

    # --- 5. TABELAS DE PRECO ---
    for e in etapa_por_endpoint(poc, "price-tables"):
        reqs = e.get("requests", [])
        if len(reqs) != 3:
            erro(f"TPs: esperado exatamente 3, encontrado {len(reqs)}")
        profiles_vistos = []
        descontos_tp = []
        for i, r in enumerate(reqs, 1):
            p = r.get("payload", {})
            registrar_placeholders(p)
            ids_definidos.add(r.get("salvar_id_como") or "")
            nome = p.get("name", "")
            if not re.match(rf"^Tabela {i}\b", nome):
                erro(f"TP {i}: name deve comecar com 'Tabela {i}' (atual: {nome!r}) — "
                     f"sem nomes de segmento (padrao desde 2026-07-02)")
            for proibido in ("discount_percentage", "minimum_order_value"):
                if proibido in p:
                    erro(f"TP {i}: campo proibido '{proibido}' (causa 400) — desconto vai em criteria[0].value")
            crits = p.get("criteria", [])
            if not crits:
                erro(f"TP {i}: sem 'criteria' — obrigatorio, com o desconto em value")
            for c in crits:
                if c.get("criteria_id") != "{{criteria_preco_id}}":
                    erro(f"TP {i}: criteria_id deve ser '{{{{criteria_preco_id}}}}'")
                if c.get("rate_type") != "DECREASE" or c.get("value_type") != "PERCENTAGE" \
                        or c.get("criteria_type") != "FILTER":
                    erro(f"TP {i}: rate_type/value_type/criteria_type devem ser DECREASE/PERCENTAGE/FILTER")
                if not isinstance(c.get("value"), (int, float)):
                    erro(f"TP {i}: criteria.value deve ser numerico (desconto %)")
                else:
                    descontos_tp.append(c["value"])
            if not p.get("end_date"):
                erro(f"TP {i}: end_date obrigatorio (usar '2060-01-01')")
            if p.get("is_profile_specific") is not True:
                erro(f"TP {i}: is_profile_specific deve ser true")
            profs = p.get("profiles", [])
            if not all(isinstance(x, dict) and "profile_id" in x for x in profs):
                erro(f"TP {i}: profiles deve ser lista de objetos {{'profile_id': 'N'}} (nunca inteiros)")
            else:
                profiles_vistos.extend(x["profile_id"] for x in profs)
            for campo in ("is_partner_specific", "is_company_specific", "is_payment_method_specific"):
                if p.get(campo) is not False:
                    erro(f"TP {i}: {campo} deve ser false")
        if reqs and sorted(profiles_vistos) != TP_PROFILES_PADRAO:
            erro(f"TPs: profiles devem ser exatamente {TP_PROFILES_PADRAO} "
                 f"(um por TP; encontrado: {sorted(profiles_vistos)})")
        if len(descontos_tp) == 3:
            if len(set(descontos_tp)) < 3:
                erro(f"TPs: descontos repetidos ({sorted(descontos_tp)}) — os 3 devem ser distintos")
            if max(descontos_tp) - min(descontos_tp) < 15:
                erro(f"TPs: variacao de desconto muito timida ({sorted(descontos_tp)}) — "
                     f"usar spread agressivo, diferenca >= 15 pontos entre menor e maior (ex: 5/15/30)")

    # --- 6. DESCONTOS ---
    # Descontos SEMPRE por categoria (nunca por marca/todos os produtos): cada desconto
    # deve referenciar um criterio de categoria proprio, separado do criterio de preco.
    # Isso evita o efeito cascata (apagar desconto derrubava o criterio da tabela de preco)
    # e mantem o desconto restrito as categorias escolhidas.
    if etapa_por_endpoint(poc, "discounts") and not criterios_categoria:
        erro("DESCONTOS: nenhum criterio de CATEGORIA definido na etapa criteria — "
             "descontos devem ser por categoria (criar criteria_cat_<slug>_id com config.categories)")
    for e in etapa_por_endpoint(poc, "discounts"):
        tipos = []
        for r in e.get("requests", []):
            p = r.get("payload", {})
            registrar_placeholders(p)
            ids_definidos.add(r.get("salvar_id_como") or "")
            lbl = r.get("label", "?")
            if "is_profile_specific" in p:
                erro(f"DESCONTO '{lbl}': usa 'is_profile_specific' — endpoint discounts usa "
                     f"'is_profile' (sem _specific)")
            if "is_profile" not in p:
                erro(f"DESCONTO '{lbl}': campo 'is_profile' ausente")
            if not p.get("end_date"):
                erro(f"DESCONTO '{lbl}': end_date obrigatorio")
            for c in p.get("criteria", []):
                tipos.append(c.get("type"))
                cid = c.get("criteria_id", "")
                m = re.match(r"\{\{(\w+)\}\}$", str(cid))
                if not m or (criterios_ids and m.group(1) not in criterios_ids):
                    erro(f"DESCONTO '{lbl}': criteria_id deve referenciar um criterio definido na "
                         f"etapa criteria (um criterio de CATEGORIA, ex.: "
                         f"'{{{{criteria_cat_<slug>_id}}}}'); atual: {cid!r}")
                elif m.group(1) in ("criteria_preco_id", "criteria_listagem_id"):
                    erro(f"DESCONTO '{lbl}': criteria_id aponta para '{m.group(1)}' (marca/todos os "
                         f"produtos) — desconto deve usar um criterio de CATEGORIA proprio. "
                         f"Compartilhar o criterio de preco causa efeito cascata ao excluir o desconto")
                elif criterios_categoria and m.group(1) not in criterios_categoria:
                    erro(f"DESCONTO '{lbl}': criteria_id '{m.group(1)}' nao e um criterio de "
                         f"CATEGORIA (config.categories) — descontos devem ser por categoria")
                rngs = c.get("ranges", [])
                if not rngs:
                    erro(f"DESCONTO '{lbl}': sem ranges")
                qts = [x.get("minimum_quantity") for x in rngs]
                if qts != sorted(qts):
                    aviso(f"DESCONTO '{lbl}': ranges fora de ordem crescente")
                # Desconto FIXED vale a partir de qualquer quantidade: 1o range comeca em 0 (nunca 1)
                if c.get("type") == "FIXED" and rngs and rngs[0].get("minimum_quantity") != 0:
                    erro(f"DESCONTO '{lbl}': desconto FIXED deve comecar em minimum_quantity 0 "
                         f"(nao {rngs[0].get('minimum_quantity')}) — vale a partir de qualquer quantidade")
        if "PROGRESSIVE" not in tipos:
            erro("DESCONTOS: falta pelo menos 1 desconto PROGRESSIVE")
        if "FIXED" not in tipos:
            erro("DESCONTOS: falta pelo menos 1 desconto FIXED")

    # --- placeholders ---
    registrar_placeholders(poc.get("portal_listing_rule_id", ""))
    ids_definidos.discard("")
    nao_definidos = ids_usados - ids_definidos
    if nao_definidos:
        erro(f"Placeholders usados mas nunca definidos via salvar_id_como: {sorted(nao_definidos)}")


def main():
    if len(sys.argv) < 2:
        print("Uso: python validar_poc.py empresa_poc.json")
        sys.exit(2)
    path = sys.argv[1]
    validar(path)
    print(f"\n=== Validacao: {os.path.basename(path)} ===")
    for m in erros:
        print(f"  [ERRO]  {m}")
    for m in avisos:
        print(f"  [AVISO] {m}")
    if not erros and not avisos:
        print("  Tudo OK — pronto para entregar.")
    elif not erros:
        print(f"\n  0 erros, {len(avisos)} aviso(s) — pode entregar, mas confira os avisos.")
    else:
        print(f"\n  {len(erros)} erro(s), {len(avisos)} aviso(s) — NAO entregar ainda.")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
