# -*- coding: utf-8 -*-
"""
Executa em lote as POCs pendentes de "Arquivos Json/".

O JSON de entrada e escrito no Claude Cowork, que tem navegador para visitar o
site do cliente e conferir imagem por imagem. A execucao contra a API da Zydon e
feita aqui. Este script fecha a ponta de ca: em vez de abrir o terminal e rodar
`criar_poc.py` uma vez por arquivo, roda todos os que faltam.

QUEM E PENDENTE
    Uma POC ja rodou quando existe "saidas/{base}_ids.json" — o `criar_poc.py`
    so grava esse arquivo depois de falar com a API. Nao ha pasta "rodados" nem
    indice paralelo: o estado vem do que esta em disco, entao nao ha o que
    dessincronizar.

    Como o acervo tem centenas de POCs anteriores a este script (muitas rodadas
    antes de existir a pasta saidas/, e portanto sem _ids.json), vale tambem um
    CORTE POR DATA: so entra no lote o JSON modificado a partir de DATA_CORTE.
    Sem isso, o primeiro lote tentaria recriar todo o historico.

USO
    python executar_lote.py [organizacao] [--dry-run] [--desde AAAA-MM-DD]
                            [--tudo] [--so ARQUIVO ...]

    --dry-run   lista o que faria, sem chamar a API nem validar
    --desde     sobrepoe a DATA_CORTE nesta execucao
    --tudo      ignora o corte por data (varre o acervo inteiro) — cuidado
    --so        roda apenas os arquivos nomeados, ignorando o corte

Uma POC que nao passa no `validar_poc.py` nao vai para a API: fica pendente e
aparece no relatorio final com os erros, para correcao no Cowork. Uma POC que
falha na API tem rollback proprio (feito pelo `criar_poc.py`) e o lote segue
para a proxima — POCs nao dependem umas das outras.
"""

import argparse
import datetime as dt
import os
import subprocess
import sys

# O console do Windows e cp1252 e levanta UnicodeEncodeError ao ecoar a saida dos
# scripts filhos (acentos, e o U+FFFD que a propria decodificacao deles produz).
# Sem isto, uma POC com acento no nome derruba o lote inteiro no print.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

AQUI = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.abspath(os.path.join(AQUI, "..", "Arquivos Json"))
SAIDAS = os.path.join(ENTRADA, "saidas")

# Marco zero do lote automatico. JSON anterior a esta data e acervo historico:
# ja foi rodado no terminal, uma POC por vez, e nao deve ser recriado.
DATA_CORTE = dt.date(2026, 8, 18)

# Derivados e insumos que moram na pasta de entrada mas nao sao POC.
NAO_SAO_POC = {"imagens.json", "nevescar.json"}
SUFIXOS_DERIVADOS = ("_ids.json", "_images_skeleton.json", "_criados.json")


def base_da_poc(caminho):
    """Nome base usado pelos derivados. Espelha `caminho_saida` do criar_poc.py:
    o sufixo `_poc` cai, entao 'cosamo_poc.json' -> 'cosamo' -> 'cosamo_ids.json'."""
    base = os.path.splitext(os.path.basename(caminho))[0]
    if base.endswith("_poc"):
        base = base[:-4]
    return base


def ja_rodou(caminho):
    return os.path.exists(os.path.join(SAIDAS, f"{base_da_poc(caminho)}_ids.json"))


def eh_poc(nome):
    if not nome.endswith(".json") or nome in NAO_SAO_POC:
        return False
    return not nome.endswith(SUFIXOS_DERIVADOS)


def listar_pendentes(desde, ignorar_corte=False):
    """POCs de entrada sem _ids.json. Devolve (pendentes, ignoradas_por_data)."""
    pendentes, por_data = [], []
    for nome in sorted(os.listdir(ENTRADA)):
        caminho = os.path.join(ENTRADA, nome)
        if not os.path.isfile(caminho) or not eh_poc(nome):
            continue
        if ja_rodou(caminho):
            continue
        mtime = dt.date.fromtimestamp(os.path.getmtime(caminho))
        if not ignorar_corte and mtime < desde:
            por_data.append((nome, mtime))
            continue
        pendentes.append(caminho)
    return pendentes, por_data


def _rodar(script, args):
    """Executa um script irmao e devolve (ok, saida_combinada)."""
    proc = subprocess.run(
        [sys.executable, os.path.join(AQUI, script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=AQUI,
    )
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def validar(caminho):
    return _rodar("validar_poc.py", [caminho])


def executar(caminho, org):
    return _rodar("criar_poc.py", [caminho, org])


def portal_criado(saida):
    """Extrai o ID do portal da saida do criar_poc.py, para o relatorio."""
    for linha in saida.splitlines():
        if "Portal novo" in linha and ":" in linha:
            return linha.split(":", 1)[1].strip()
    return None


def main():
    p = argparse.ArgumentParser(description="Executa em lote as POCs pendentes.")
    p.add_argument("organizacao", nargs="?", default="pocs")
    p.add_argument("--dry-run", action="store_true", help="so lista o que faria")
    p.add_argument("--desde", metavar="AAAA-MM-DD", help="sobrepoe a data de corte")
    p.add_argument("--tudo", action="store_true", help="ignora o corte por data")
    p.add_argument("--so", nargs="+", metavar="ARQUIVO", help="roda apenas estes arquivos")
    args = p.parse_args()

    if not os.path.isdir(ENTRADA):
        print(f"[ERRO] Pasta de entrada nao encontrada: {ENTRADA}")
        return 2

    desde = DATA_CORTE
    if args.desde:
        try:
            desde = dt.date.fromisoformat(args.desde)
        except ValueError:
            print(f"[ERRO] Data invalida em --desde: '{args.desde}' (use AAAA-MM-DD)")
            return 2

    if args.so:
        pendentes, por_data = [], []
        for nome in args.so:
            caminho = nome if os.path.isabs(nome) else os.path.join(ENTRADA, nome)
            if not os.path.isfile(caminho):
                print(f"[ERRO] Arquivo nao encontrado: {caminho}")
                return 2
            pendentes.append(caminho)
    else:
        pendentes, por_data = listar_pendentes(desde, ignorar_corte=args.tudo)

    print("=" * 60)
    print(f"Entrada     : {ENTRADA}")
    print(f"Organizacao : {args.organizacao}")
    if args.so:
        print("Selecao     : --so (corte por data ignorado)")
    elif args.tudo:
        print("Selecao     : --tudo (acervo inteiro, sem corte por data)")
    else:
        print(f"Corte       : modificados a partir de {desde.isoformat()}")
    print("=" * 60)

    if por_data:
        print(f"\n{len(por_data)} POC(s) sem _ids.json ficaram fora pelo corte de data.")
        print("  (acervo historico — use --tudo ou --so para incluir)")

    if not pendentes:
        print("\nNenhuma POC pendente. Nada a fazer.")
        return 0

    print(f"\n{len(pendentes)} POC(s) pendente(s):")
    for c in pendentes:
        print(f"  - {os.path.basename(c)}")

    if args.dry_run:
        print("\n[DRY-RUN] Nada foi validado nem executado.")
        return 0

    criadas, invalidas, falhas = [], [], []

    for i, caminho in enumerate(pendentes, 1):
        nome = os.path.basename(caminho)
        print(f"\n{'=' * 60}\n[{i}/{len(pendentes)}] {nome}\n{'=' * 60}")

        ok, saida = validar(caminho)
        if not ok:
            # Os erros que o validador pega sao justamente os que viram 400/500
            # na Zydon. Nao adianta mandar assim.
            print("[INVALIDA] Nao foi executada. Erros:")
            print(saida.strip())
            invalidas.append((nome, saida.strip()))
            continue
        print("[OK] Validacao passou. Executando...")

        ok, saida = executar(caminho, args.organizacao)
        print(saida.strip())
        if ok:
            criadas.append((nome, portal_criado(saida)))
        else:
            # O criar_poc.py ja desfez o que criou. Seguimos para a proxima.
            falhas.append((nome, saida.strip().splitlines()[-1] if saida.strip() else "sem saida"))

    print(f"\n{'=' * 60}\nRELATORIO DO LOTE\n{'=' * 60}")
    print(f"  Criadas   : {len(criadas)}")
    print(f"  Invalidas : {len(invalidas)}")
    print(f"  Falharam  : {len(falhas)}")

    if criadas:
        print("\nCriadas:")
        for nome, portal in criadas:
            print(f"  + {nome}" + (f"  (portal {portal})" if portal else ""))
    if invalidas:
        print("\nInvalidas (corrija no Cowork e mande de novo — seguem pendentes):")
        for nome, _ in invalidas:
            print(f"  ! {nome}")
    if falhas:
        print("\nFalharam na API (com rollback — seguem pendentes):")
        for nome, ultima in falhas:
            print(f"  x {nome}: {ultima}")

    return 0 if not (invalidas or falhas) else 1


if __name__ == "__main__":
    sys.exit(main())
