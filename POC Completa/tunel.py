"""Sobe o tunel e publica o endereco no repositorio, para o Mitra achar.

    python "POC Completa/tunel.py"                 # sobe, confere e publica
    python "POC Completa/tunel.py" --sem-publicar  # so sobe e mostra

Existe porque o tunel rapido e descartavel por definicao: sem conta na
Cloudflare nao ha garantia nenhuma, e o nome e recolhido quando eles quiserem.
Em 01/09/2026 o `press-dropped-casa-jelsoft` de sexta simplesmente sumiu — o
DNS nem resolvia mais. O receptor estava vivo o tempo todo, respondendo em
0,04s, e o Mitra reportava "504, a API nao respondeu": o erro apontava para a
maquina errada.

A saida e parar de tratar o endereco como constante. Este script captura a URL
que o `cloudflared` imprime e grava em `endereco-receptor.json`, na raiz. O
Mitra le esse arquivo pela API do GitHub — o mesmo canal que ele ja usa para os
PRs — antes de cada POST. Endereco novo se propaga sozinho.

**So publica depois de o endereco funcionar de verdade.** Publicar um endereco
que nao responde e pior que nao publicar: o Mitra passa a falhar contra um alvo
que parece configurado. Aqui o `/saude` e chamado atraves do tunel, de fora,
antes de qualquer commit — confira o efeito, nao a resposta.
"""

import argparse
import json
import re
import subprocess
import threading
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
ARQUIVO = RAIZ / "endereco-receptor.json"

CLOUDFLARED = Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
GIT = Path(r"C:\Program Files\Git\cmd\git.exe")
PADRAO_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
PADRAO_PRONTO = "Registered tunnel connection"

# O DNS de um nome recem-criado leva de 10 segundos a mais de dois minutos para
# propagar. Medido em 01/09/2026, na mesma tarde: uma subida passou na terceira
# sondagem e outra na vigesima quarta — exatamente no limite de uma janela de
# 24. Janela curta aqui reprova um tunel que estava subindo bem, e o custo de
# esperar e so tempo, entao ela e folgada de proposito: 3 minutos.
TENTATIVAS_SAUDE = 36
ESPERA_SAUDE = 5

# De quanto em quanto tempo o tunel confere a si mesmo, e quantas falhas
# seguidas ate trocar de endereco. Tres minutos de silencio antes de trocar:
# oscilacao de rede se resolve sozinha em segundos, e trocar de endereco a cada
# tossida geraria commit atras de commit.
INTERVALO_VIGIA = 60
FALHAS_PARA_TROCAR = 3


def _agora():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def esperar_url(processo, limite=90):
    """Le a saida ate a URL aparecer E a conexao registrar. None se falhar.

    Esperar so a URL nao basta: o cloudflared a imprime antes de registrar a
    conexao com a borda, e sondar nesse intervalo da erro num tunel que estava
    subindo normalmente.
    """
    inicio, url = time.time(), None
    while time.time() - inicio < limite:
        linha = processo.stdout.readline()
        if not linha:
            if processo.poll() is not None:
                return None
            continue
        achado = PADRAO_URL.search(linha)
        if achado:
            url = achado.group(0)
            print(f"[INFO] Tunel: {url}")
        if url and PADRAO_PRONTO in linha:
            print("[INFO] Conexao registrada; esperando o DNS propagar.")
            return url
    return url


def conferir(url):
    """O /saude responde atraves do tunel? Devolve (ok, detalhe)."""
    for tentativa in range(1, TENTATIVAS_SAUDE + 1):
        try:
            r = requests.get(f"{url}/saude", timeout=20)
            if r.status_code == 200 and r.json().get("ok"):
                return True, f"{r.json()} na tentativa {tentativa}"
            detalhe = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            detalhe = type(e).__name__
        print(f"  [saude] tentativa {tentativa}/{TENTATIVAS_SAUDE}: {detalhe}")
        time.sleep(ESPERA_SAUDE)
    return False, detalhe


def publicar(url, porta):
    ARQUIVO.write_text(json.dumps({
        "url": url,
        "pedido": f"{url}/pedido",
        "saude": f"{url}/saude",
        "porta_local": porta,
        "atualizado_em": _agora(),
        "aviso": ("Tunel efemero: este endereco muda quando o tunel reinicia. "
                  "Leia este arquivo antes de cada POST, e confira /saude se "
                  "der erro de conexao — nao guarde a URL."),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def git(*a):
        return subprocess.run([str(GIT), *a], cwd=str(RAIZ),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    # `git diff --quiet` diz "sem diferenca" para arquivo NAO RASTREADO, e na
    # primeira publicacao e exatamente esse o caso: o endereco ficava so em
    # disco e o Mitra nunca via. `status --porcelain` enxerga o `??` tambem.
    if not git("status", "--porcelain", "--", ARQUIVO.name).stdout.strip():
        print("  [git] endereco igual ao publicado; nada a fazer.")
        return True

    git("add", ARQUIVO.name)
    feito = git("commit", "-m", f"Endereco do receptor: {url}", "--", ARQUIVO.name)
    if feito.returncode:
        print(f"  [git] commit falhou: {feito.stdout}{feito.stderr}")
        return False
    enviado = git("push", "origin", "HEAD")
    if enviado.returncode:
        print(f"  [git] push falhou: {enviado.stderr[-400:]}\n"
              f"        O arquivo esta gravado; publique quando a rede voltar.")
        return False
    print(f"  [git] publicado em {ARQUIVO.name}")
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--porta", type=int, default=8787)
    p.add_argument("--sem-publicar", action="store_true",
                   help="sobe e mostra a URL, sem commitar")
    p.add_argument("--cloudflared", default=str(CLOUDFLARED))
    args = p.parse_args(argv)

    binario = Path(args.cloudflared)
    if not binario.exists():
        print(f"[ERRO] cloudflared nao esta em {binario}.\n"
              f"       Instale com: winget install --id Cloudflare.cloudflared",
              file=sys.stderr)
        return 1

    # O receptor precisa estar de pe ANTES: tunel para porta vazia sobe do mesmo
    # jeito e publica um endereco que devolve 502.
    try:
        requests.get(f"http://127.0.0.1:{args.porta}/saude", timeout=5)
    except requests.RequestException:
        print(f"[ERRO] Nada respondendo em 127.0.0.1:{args.porta}. Suba o "
              f"receptor primeiro:\n"
              f'       python "POC Completa/receptor.py" --gravar', file=sys.stderr)
        return 1

    print(f"[INFO] Subindo o tunel para 127.0.0.1:{args.porta}...")
    processo = subprocess.Popen(
        [str(binario), "tunnel", "--url", f"http://127.0.0.1:{args.porta}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1)

    url = esperar_url(processo)
    if not url:
        print("[ERRO] O cloudflared nao imprimiu nenhuma URL.", file=sys.stderr)
        processo.terminate()
        return 1

    ok, detalhe = conferir(url)
    if not ok:
        print(f"[ERRO] O tunel subiu mas o /saude nao respondeu ({detalhe}). "
              f"NAO publiquei: endereco que nao responde e pior que nenhum.",
              file=sys.stderr)
        processo.terminate()
        return 1
    print(f"[OK] /saude atraves do tunel: {detalhe}")

    if args.sem_publicar:
        print(f"\n  {url}/pedido\n")
    else:
        publicar(url, args.porta)

    print(f"\n[INFO] Tunel no ar. Confiro a cada {INTERVALO_VIGIA}s. Ctrl+C para parar.\n")
    return vigiar(processo, url, binario, args)


def _drenar(processo):
    """Consome a saida do cloudflared num fio proprio.

    Nao e so higiene: o cano de stdout enche e o processo TRAVA se ninguem ler.
    Como o laco principal agora fica sondando o /saude em vez de ler linha a
    linha, alguem tem que esvaziar isto.
    """
    for linha in processo.stdout:
        if " ERR " in linha and "no recent network activity" not in linha:
            print(f"  [cloudflared] {linha.rstrip()[:150]}")


def vigiar(processo, url, binario, args):
    """Sonda o proprio endereco e levanta um tunel novo quando ele morre.

    Existe por causa de 01/09/2026, a segunda morte em quatro dias: o
    `cloudflared` continuava rodando, reconectando a um tunel que a Cloudflare
    ja tinha recolhido, e nunca pedia um nome novo. Do lado de fora o DNS nem
    resolvia; do lado de dentro parecia tudo bem. O Mitra levou 300s de timeout
    contra um endereco publicado que ja nao existia.

    Reiniciar da um nome novo, e o nome novo e publicado — que e o motivo de o
    endereco morar num arquivo, e nao na configuracao do Mitra.
    """
    threading.Thread(target=_drenar, args=(processo,), daemon=True).start()
    falhas = 0
    try:
        while True:
            time.sleep(INTERVALO_VIGIA)
            try:
                r = requests.get(f"{url}/saude", timeout=25)
                viva = r.status_code == 200 and r.json().get("ok")
            except (requests.RequestException, ValueError):
                viva = False

            if viva:
                falhas = 0
                continue

            falhas += 1
            print(f"[AVISO] O tunel nao respondeu ({falhas}/{FALHAS_PARA_TROCAR}).")
            if falhas < FALHAS_PARA_TROCAR:
                continue

            # Antes de culpar o tunel: se o receptor caiu, trocar de tunel nao
            # resolve nada e ainda queima um endereco novo a toa.
            try:
                requests.get(f"http://127.0.0.1:{args.porta}/saude", timeout=10)
            except requests.RequestException:
                print("[AVISO] O receptor local tambem nao responde. O problema "
                      "nao e o tunel — nao vou trocar de endereco.")
                falhas = 0
                continue

            print("[INFO] Levantando um tunel novo.")
            processo.terminate()
            processo = subprocess.Popen(
                [str(binario), "tunnel", "--url", f"http://127.0.0.1:{args.porta}"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
            novo = esperar_url(processo)
            if not novo:
                print("[ERRO] O tunel novo nao subiu. Tento de novo na proxima volta.")
                falhas = 0
                continue
            ok, detalhe = conferir(novo)
            if not ok:
                print(f"[ERRO] O tunel novo nao respondeu ({detalhe}). Nao publiquei.")
                falhas = 0
                continue
            url = novo
            falhas = 0
            print(f"[OK] Endereco novo: {url}")
            if not args.sem_publicar:
                publicar(url, args.porta)
            threading.Thread(target=_drenar, args=(processo,), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[INFO] Parando o tunel.")
    finally:
        processo.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
