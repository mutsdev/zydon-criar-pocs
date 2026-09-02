"""Entrypoint do gerador de banners de portal.

Dois passos, porque a geracao da cena e humana (o GEM no aplicativo) e o resto
e mecanico:

    preparar  logo -> paleta, prompt do GEM e a pasta cenas/ onde largar os PNGs
    montar    cenas/ -> peca composta, validada, julgada, e a folha de contato

Sem cena nenhuma, `montar` ainda entrega os tres formatos pelo fallback
deterministico. O pipeline nunca trava e nunca publica coisa feia: essas duas
propriedades sao o requisito, e nao um efeito colateral.
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
if str(AQUI) not in sys.path:
    sys.path.insert(0, str(AQUI))

# O console do Windows e cp1252 e um print com acento estoura no meio da
# execucao — a lista de objetos do segmento vem cheia deles ("Filtro de oleo").
# Resolver aqui, e nao pedir PYTHONIOENCODING na linha de comando, porque quem
# vai rodar isto e o executivo comercial, nao quem escreveu o script.
for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from PIL import Image  # noqa: E402

import cenas  # noqa: E402
import compor  # noqa: E402
import contato  # noqa: E402
import fallback  # noqa: E402
import formatos  # noqa: E402
import juiz  # noqa: E402
import logo as mod_logo  # noqa: E402
import paleta as mod_paleta  # noqa: E402
import prompt_gem  # noqa: E402
import regua as mod_regua  # noqa: E402
import salvar  # noqa: E402
import segmento as mod_segmento  # noqa: E402
import validar  # noqa: E402

SAIDAS = AQUI / "saidas"


def _carregar_env():
    """Le o .env da pasta de execucao, como o resto do repo faz.

    Sem python-dotenv obrigatorio: o parse e trivial e uma dependencia a menos
    e uma forma a menos de o script nao rodar na maquina do executivo.
    """
    for raiz in (Path.cwd(), AQUI, AQUI.parent):
        alvo = raiz / ".env"
        if not alvo.exists():
            continue
        for linha in alvo.read_text(encoding="utf-8-sig").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            nome, valor = linha.split("=", 1)
            os.environ.setdefault(nome.strip(), valor.strip().strip('"').strip("'"))
        return alvo
    return None


def _abrir(pasta):
    """Abre a pasta no gerenciador de arquivos.

    O fluxo e arrastar a imagem do navegador para ca, entao deixar a janela
    aberta ao lado do Gemini poupa procurar o caminho a cada cliente.
    Best-effort: falhar em abrir nao pode derrubar o passo que ja deu certo.
    """
    import subprocess
    try:
        if sys.platform == "win32":
            os.startfile(pasta)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(pasta)], check=False)
        else:
            subprocess.run(["xdg-open", str(pasta)], check=False)
    except Exception:
        pass


def _pasta_cliente(nome, carimbo=None):
    seguro = mod_segmento._chave(nome)
    carimbo = carimbo or datetime.now().strftime("%Y-%m-%d_%H%M")
    return SAIDAS / seguro / carimbo


# --------------------------------------------------------------------------
# preparar
# --------------------------------------------------------------------------

def _limiares_logo(limiares, regua_logo):
    """Qual das duas reguas de tamanho vale nesta execucao.

    `banner` e a de casa: a logo e composta num painel de 768px, entao 200px no
    MENOR lado e o minimo honesto. `portal` e a do cabecalho (200 no maior, 48
    no menor), mais frouxa, e existe para o estudo poder gerar peca de marca
    horizontal — Cobra 205x58, Benenutri 598x173 — e mostrar o resultado em vez
    de barrar antes. Ver a peca ruim e o que decide se a regua dura procede.
    """
    if regua_logo == "portal":
        return {**limiares["logo"], **limiares.get("logo_portal", {})}
    return limiares["logo"]


def _preparar(logo, nome, segmento, cor, sem_rede, limiares, regua_logo="banner"):
    """O miolo do `preparar`, sem argparse e sem imprimir instrucao de GEM.

    Separado porque o `auto` precisa exatamente disto e mais nada: a diferenca
    entre os dois comandos e quem enche a pasta `cenas/` depois.
    """
    logo_img, laudo = mod_logo.normalizar(logo, _limiares_logo(limiares, regua_logo))
    pal = mod_paleta.extrair(logo_img, cor)

    pasta = _pasta_cliente(nome)
    (pasta / "cenas").mkdir(parents=True, exist_ok=True)
    logo_img.save(pasta / "logo-normalizada.png")

    contexto = mod_segmento.resolver(segmento, limiares["juiz"]["modelo"],
                                     usar_rede=not sem_rede)
    contexto["segmento"] = segmento

    (pasta / "paleta.json").write_text(
        json.dumps({k: pal[k] for k in ("principal", "destaque", "neutra")},
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (pasta / "prompt-gem.txt").write_text(
        prompt_gem.folha(pal, contexto), encoding="utf-8")
    (pasta / "contexto.json").write_text(
        json.dumps({"cliente": nome, "logo": laudo, "paleta": pal,
                    "contexto": contexto}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return pasta, pal, contexto, laudo


def preparar(args):
    limiares = mod_regua.carregar(args.regua)
    pasta, pal, contexto, _ = _preparar(
        args.logo, args.nome, args.segmento, args.cor, args.sem_rede, limiares)

    print(f"\nPasta:   {pasta}")
    print(f"Paleta:  {pal['principal']}  {pal['destaque']}  {pal['neutra']}"
          f"   ({pal['diagnostico']['origem_principal']}/"
          f"{pal['diagnostico']['origem_destaque']})")
    print(f"Objetos: {', '.join(contexto['objetos'][:4])}"
          f"   (origem: {contexto['origem']})")
    if contexto.get("erro"):
        print(f"  [AVISO] segmento caiu no generico — {contexto['erro']}")
    print(f"\n1. Cole em prompt-gem.txt no GEM, com a logo.")
    print(f"2. ARRASTE as imagens do navegador para: {pasta / 'cenas'}")
    print("   O nome nao importa — o script separa as cenas pelo formato delas.")
    print(f"3. python \"{Path(__file__).name}\" montar \"{pasta}\"")

    if not args.nao_abrir:
        _abrir(pasta / "cenas")
    return 0


# --------------------------------------------------------------------------
# montar
# --------------------------------------------------------------------------

def _julgar(imagem, contexto_juiz, config, sem_juiz):
    """Chama o degrau 2. Devolve (aprovado, motivos, veredito, aviso)."""
    if sem_juiz:
        return True, [], None, "juiz desligado (--sem-juiz)"
    try:
        veredito = juiz.avaliar(imagem, contexto_juiz, config)
    except juiz.SemChave as erro:
        return True, [], None, f"juiz nao rodou: {erro}"
    except juiz.LimiteDiarioEsgotado as erro:
        return True, [], None, f"juiz nao rodou: {erro}"
    except Exception as erro:  # rede, JSON torto, resposta incompleta
        return True, [], None, f"juiz falhou ({type(erro).__name__}: {erro})"
    aprovado, motivos = juiz.decidir(veredito, config)
    return aprovado, motivos, veredito, None


def montar(args):
    pasta = Path(args.pasta)
    contexto_arquivo = pasta / "contexto.json"
    if not contexto_arquivo.exists():
        print(f"[ERRO] {contexto_arquivo} nao existe. Rode 'preparar' antes.")
        return 1

    dados = json.loads(contexto_arquivo.read_text(encoding="utf-8"))
    limiares = mod_regua.carregar(args.regua)
    pal = dados["paleta"]
    contexto = dados["contexto"]
    cliente = dados["cliente"]
    logo_img = Image.open(pasta / "logo-normalizada.png")
    logo_img.load()

    aprovados = pasta / "aprovados"
    aprovados.mkdir(exist_ok=True)
    manifesto = {"cliente": cliente, "paleta": {k: pal[k] for k in
                 ("principal", "destaque", "neutra")}, "pecas": {}}
    secoes = []

    for formato in formatos.TODOS:
        itens = []
        escolhida = None

        if formato in formatos.COM_CENA and not args.so_fallback:
            candidatas = cenas.procurar(pasta / "cenas", formato,
                                        formatos.COM_CENA)
            if args.tentativas:
                candidatas = candidatas[:args.tentativas]
            for indice, arquivo in enumerate(candidatas, start=1):
                item = _tentativa(arquivo, indice, formato, pal, contexto,
                                  logo_img, limiares, pasta, args)
                itens.append(item)
                if item["estado"] == "aprovado" and escolhida is None:
                    escolhida = item

        if escolhida is None:
            peca, relato = fallback.montar(formato, pal, logo_img, cliente,
                                           limiares["logo"])
            destino, laudo_arquivo = salvar.gravar(
                peca, pasta / f"{formato.chave}-fallback", relato["tem_cena"],
                limiares["mecanico"]["peso_maximo_kb"])
            falhas = validar.checar_peca(peca, relato, formato, limiares["mecanico"],
                                         laudo_arquivo["kb"])
            # Fallback que falha no degrau 1 e bug NOSSO, e tem que gritar.
            if falhas:
                print(f"[BUG] o fallback de '{formato.chave}' falhou na propria "
                      f"regua: {validar.resumir(falhas)}")
            item = {"titulo": f"{formato.chave} — fallback deterministico",
                    "imagem": str(destino), "estado": "fallback",
                    "motivos": [f["checagem"] for f in falhas] or None,
                    "observacao": "sempre apresentavel; entrou porque nao houve "
                                  "cena aprovada",
                    "detalhe": {"relato": relato, "falhas": falhas,
                                "arquivo": laudo_arquivo}}
            itens.append(item)
            escolhida = item

        origem = Path(escolhida["imagem"])
        final = aprovados / f"{formato.chave}{origem.suffix}"
        final.write_bytes(origem.read_bytes())  # copia byte a byte: recomprimir
                                                # aqui perderia qualidade de novo
        manifesto["pecas"][formato.chave] = {
            "origem": escolhida["estado"],
            "arquivo": final.name,
            "tentativas": len([i for i in itens if i["estado"] != "fallback"]),
            "dimensao": [formato.largura, formato.altura],
        }
        secoes.append((f"{formato.chave} — {formato.largura}x{formato.altura}", itens))
        marca = "fallback" if escolhida["estado"] == "fallback" else "cena aprovada"
        print(f"  {formato.chave:12s} {marca}")

    (pasta / "manifesto.json").write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    folha = contato.escrever(pasta / "contato.html", cliente, pal, secoes)

    print(f"\nPecas:   {aprovados}")
    print(f"Revisar: {folha}")
    return 0


# --------------------------------------------------------------------------
# auto — preparar + gerar as cenas + montar, sem humano no meio
# --------------------------------------------------------------------------

def auto(args):
    """O caminho fechado: logo -> pecas, sem passar pelo GEM.

    E o `preparar` e o `montar` com o gerador no meio. Existe separado dos dois
    porque o caminho manual continua valendo: sem chave da Cloudflare, ou com a
    API fora do ar, o certo e cair nele em vez de entregar peca pior.
    """
    import gerador

    limiares = mod_regua.carregar(args.regua)
    pasta, pal, contexto, laudo_logo = _preparar(
        args.logo, args.nome, args.segmento, args.cor, args.sem_rede,
        limiares, args.regua_logo)

    print(f"Pasta:   {pasta}")
    print(f"Logo:    {laudo_logo['original'][0]}x{laudo_logo['original'][1]} -> "
          f"{laudo_logo['recortada'][0]}x{laudo_logo['recortada'][1]}"
          f"   (regua: {args.regua_logo})")
    print(f"Paleta:  {pal['principal']}  {pal['destaque']}  {pal['neutra']}")
    print(f"Objetos: {', '.join(contexto['objetos'][:4])}"
          f"   (origem: {contexto['origem']})")
    if contexto.get("erro"):
        print(f"  [AVISO] segmento caiu no generico — {contexto['erro']}")

    linhas, total = gerador.orcamento(args.candidatas)
    print(f"\nEtapa: gerar {args.candidatas} cena(s) por formato  "
          f"(~{total} neurons dos {gerador.NEURONS_POR_DIA} do dia)")
    try:
        laudos = gerador.encher(pasta / "cenas", pal, contexto,
                                quantas=args.candidatas, ecoar=print)
    except gerador.SemChave as erro:
        print(f"[ERRO] {erro}")
        print("       Sem gerador, use o caminho manual: 'preparar' e o GEM.")
        return 2

    geradas = [l for l in laudos if l.get("ok")]
    print(f"  {len(geradas)}/{len(laudos)} cena(s) geradas")
    if not geradas:
        print("  [AVISO] nenhuma cena saiu. As pecas vao sair pelo fallback "
              "deterministico, que e o piso e nunca fica feio — mas e o piso.")

    print("\nEtapa: montar as pecas")
    args.pasta = str(pasta)
    codigo = montar(args)
    print(f"\nPASTA={pasta}")  # a ultima linha e o que o estudio le
    return codigo


def _tentativa(arquivo, indice, formato, pal, contexto, logo_img, limiares,
               pasta, args):
    """Uma cena: encaixa, valida, compoe, valida de novo e julga."""
    titulo = f"{formato.chave} — tentativa {indice} ({arquivo.name})"
    try:
        cena, laudo = cenas.carregar(arquivo, formato)
    except cenas.CenaPequena as erro:
        return {"titulo": titulo, "imagem": str(arquivo), "estado": "reprovado",
                "motivos": ["cena_pequena"], "observacao": str(erro)}

    falhas = validar.checar_cena(cena, pal, formato, limiares["mecanico"])
    peca, relato = compor.montar(formato, pal, logo_img, cena, limiares["logo"])

    destino, laudo_arquivo = salvar.gravar(
        peca, pasta / f"{formato.chave}-{indice}", relato["tem_cena"],
        limiares["mecanico"]["peso_maximo_kb"])
    falhas += validar.checar_peca(peca, relato, formato, limiares["mecanico"],
                                  laudo_arquivo["kb"])

    item = {"titulo": titulo, "imagem": str(destino),
            "detalhe": {"cena": laudo, "relato": relato, "falhas": falhas,
                        "arquivo": laudo_arquivo}}

    # Degrau 1 reprovou: nao gasta cota do degrau 2 com o que ja caiu.
    if falhas:
        item["estado"] = "reprovado"
        item["motivos"] = [f["checagem"] for f in falhas]
        item["observacao"] = validar.resumir(falhas)
        return item

    # O juiz julga a CENA, nunca a peca montada. A peca contem o painel do
    # Pillow, que tem texto por construcao — perguntar "tem texto?" sobre ela
    # reprovaria 100% das tentativas. Os riscos da peca (truncamento, contraste,
    # costura, dimensao) sao deterministicos e ja morreram no degrau 1; o que
    # sobra de imprevisivel mora na cena, e e la que a opiniao vale a cota.
    contexto_juiz = {
        "descricao": ("uma fotografia de campanha que sera a metade direita de "
                      "um banner de portal B2B. Ela deve ser SO fotografia: o "
                      "texto e a logo entram depois, fora dela"),
        "segmento": contexto["segmento"],
        "principal": pal["principal"], "destaque": pal["destaque"],
    }
    aprovado, motivos, veredito, aviso = _julgar(cena, contexto_juiz,
                                                 limiares["juiz"], args.sem_juiz)
    item["detalhe"]["veredito"] = veredito
    if veredito:
        item["nota"] = veredito.get("nota_estetica")
    item["estado"] = "aprovado" if aprovado else "reprovado"
    item["motivos"] = motivos or None
    item["observacao"] = aviso or (veredito or {}).get("defeito_principal") or None
    return item


def main(argv=None):
    _carregar_env()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--regua", help="regua.json alternativa")
    sub = p.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("preparar", help="logo -> paleta + prompt do GEM")
    a.add_argument("--logo", required=True)
    a.add_argument("--nome", required=True)
    a.add_argument("--segmento", required=True)
    a.add_argument("--cor", help="cor primaria em hex; manda sobre a extraida")
    a.add_argument("--sem-rede", action="store_true",
                   help="nao consulta o segmento; usa a lista generica")
    a.add_argument("--nao-abrir", action="store_true",
                   help="nao abre a pasta cenas/ no fim")
    a.set_defaults(func=preparar)

    b = sub.add_parser("montar", help="cenas/ -> pecas validadas")
    b.add_argument("pasta")
    b.add_argument("--sem-juiz", action="store_true",
                   help="so o degrau 1; itera a regua sem gastar cota")
    b.add_argument("--so-fallback", action="store_true",
                   help="ignora as cenas; mostra o piso de qualidade")
    b.add_argument("--tentativas", type=int,
                   help="limita quantas cenas por formato sao julgadas")
    b.set_defaults(func=montar)

    c = sub.add_parser("auto", help="logo -> pecas, gerando as cenas sozinho")
    c.add_argument("--logo", required=True)
    c.add_argument("--nome", required=True)
    c.add_argument("--segmento", required=True)
    c.add_argument("--cor", help="cor primaria em hex; manda sobre a extraida")
    c.add_argument("--candidatas", type=int, default=2,
                   help="cenas geradas por formato (padrao: 2). Cada cliente "
                        "custa ~784 neurons com 2, de 10.000 por dia.")
    c.add_argument("--regua-logo", default="banner", choices=("banner", "portal"),
                   help="banner: 200px no menor lado (o padrao, e o que o "
                        "painel de 768px pede). portal: 200 no maior e 48 no "
                        "menor, para nao barrar marca horizontal.")
    c.add_argument("--sem-rede", action="store_true",
                   help="nao consulta o segmento; usa a lista generica")
    c.add_argument("--sem-juiz", action="store_true",
                   help="so o degrau 1; itera a regua sem gastar cota")
    c.add_argument("--so-fallback", action="store_true",
                   help="ignora as cenas; mostra o piso de qualidade")
    c.add_argument("--tentativas", type=int,
                   help="limita quantas cenas por formato sao julgadas")
    c.set_defaults(func=auto)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except mod_logo.LogoInvalida as erro:
        print(f"[ERRO] logo recusada: {erro}")
        return 2
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
