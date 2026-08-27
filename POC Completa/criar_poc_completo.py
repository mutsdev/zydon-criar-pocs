"""Cria a POC e sobe a identidade visual do cliente numa passada so.

    python "POC Completa/criar_poc_completo.py" "Arquivos Json/<cliente>_poc.json" pocs \
        --logo caminho/logo.png --nome "Cliente" [--gravar]

Costura duas coisas que ja existiam separadas:

  1. `criar_poc.py` desta pasta  - catalogo + portal + regra de listagem
  2. `Identidade Visual/subir_identidade.py` - logo e favicon no portal criado

O que a costura resolve: o portal so ganha UUID no meio da execucao do runner, e
ate agora esse id so era impresso. Sem ele nao da para subir a identidade sem o
humano copiar o UUID da tela e colar no segundo comando.

ATENCAO AO `--gravar`: ele vale SO para a identidade visual, porque e o contrato
do `subir_identidade` (o padrao dele e simular). A criacao do catalogo e do
portal NAO tem simulacao e acontece de verdade em toda execucao. Ou seja: sem
`--gravar` voce termina com o portal criado e a identidade apenas simulada.
"""

import argparse
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
IDENTIDADE = RAIZ / "Identidade Visual"

for _caminho in (str(AQUI), str(RAIZ), str(IDENTIDADE)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Antes de `credenciais`: o .env com as chaves Zydon mora no Sales Ops, nao neste
# repo, e quem sabe achar os dois lugares e o _carregar_env do subir_identidade.
import subir_identidade as mod_identidade  # noqa: E402

mod_identidade._carregar_env()

import credenciais  # noqa: E402
import criar_poc  # noqa: E402  (a copia desta pasta, com o parametro `saida`)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("arquivo", help="o <cliente>_poc.json")
    p.add_argument("org", nargs="?", default="pocs",
                   help=f"organizacao Zydon (padrao: pocs). "
                        f"Disponiveis: {', '.join(credenciais.ORGANIZACOES)}")
    p.add_argument("--logo", required=True, help="arquivo da logo do cliente")
    p.add_argument("--nome", default="",
                   help="nome do cliente (usado se o favicon cair na inicial)")
    p.add_argument("--favicon", help="favicon pronto; sem isto sai da logo")
    p.add_argument("--favicon-modo", default="auto",
                   help="auto | inteira | inicial (ver subir_identidade)")
    p.add_argument("--cor", help="cor primaria em hex; manda sobre a extraida")
    p.add_argument("--regua", help="regua.json alternativa")
    p.add_argument("--gravar", action="store_true",
                   help="GRAVA a identidade visual. Sem isto ela so e simulada "
                        "— mas o catalogo e o portal sao criados de qualquer jeito.")
    p.add_argument("--sem-rollback", action="store_true",
                   help="nao apaga o que criou em caso de erro")
    args = p.parse_args(argv)

    if not Path(args.arquivo).exists():
        print(f"[ERRO] JSON nao encontrado: {args.arquivo}")
        return 1
    if not Path(args.logo).exists():
        print(f"[ERRO] Logo nao encontrada: {args.logo}")
        return 1

    try:
        headers, org = credenciais.carregar(args.org)
    except credenciais.CredencialAusente as e:
        print(f"[ERRO] {e}")
        return 1

    if not args.gravar:
        print("=" * 62)
        print("  A identidade visual sera apenas SIMULADA (falta --gravar).")
        print("  O catalogo e o portal serao criados de verdade mesmo assim.")
        print("=" * 62 + "\n")

    # ---------------------------------------------------------------- catalogo
    saida = {}
    ok = criar_poc.run_poc(args.arquivo, headers, org,
                           rollback_on_error=not args.sem_rollback,
                           saida=saida)
    if not ok:
        print("\n[PARADO] A POC falhou. A identidade visual nao foi tocada — "
              "subir logo num portal incompleto so criaria trabalho de limpeza.")
        return 1

    portal_id = saida.get("portal_id")
    if not portal_id:
        print("\n[PARADO] A POC concluiu mas nenhum portal foi criado "
              "(portal_origem_id nao configurado nesta org?). Sem portal nao ha "
              "onde subir a identidade.")
        return 1

    # ------------------------------------------------------------- identidade
    print("\n" + "=" * 62)
    print(f"IDENTIDADE VISUAL  ->  portal {portal_id}")
    print("=" * 62)

    argv_identidade = ["--org", args.org, "--portal", portal_id,
                       "--logo", args.logo, "--favicon-modo", args.favicon_modo]
    for bandeira, valor in (("--nome", args.nome), ("--favicon", args.favicon),
                            ("--cor", args.cor), ("--regua", args.regua)):
        if valor:
            argv_identidade += [bandeira, valor]
    if args.gravar:
        argv_identidade.append("--gravar")

    codigo = mod_identidade.main(argv_identidade)

    print("\n" + "=" * 62)
    print(f"  Portal     : {portal_id}")
    print(f"  Catalogo   : criado")
    print(f"  Identidade : {'gravada' if args.gravar and codigo == 0 else 'simulada' if not args.gravar else 'FALHOU'}")
    if not args.gravar:
        print("\n  Para gravar a identidade neste portal, sem recriar a POC:")
        print('    python "Identidade Visual/subir_identidade.py"'
              f' --org {args.org} --portal {portal_id}'
              f' --logo {args.logo} --gravar')
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
