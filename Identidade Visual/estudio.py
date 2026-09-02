"""Estudio: gerar banner de cliente real e pontuar, cliente a cliente.

    python "Identidade Visual/estudio.py"        # abre em 127.0.0.1:8790

Existe para responder uma pergunta que so o Joao Pedro pode responder: **o
banner gerado presta?** O juiz de visao ja opina, mas na primeira rodada de
verdade (Pelicula da Vida, 02/09/2026) ele reprovou duas cenas que estavam
boas — `nota_estetica 3` e `parece_banco_de_imagens_generico` numa peca
apresentavel. Enquanto a opiniao dele nao for conferida contra a de uma pessoa,
nao da para saber se o gerador e fraco ou se a regua e que esta torta.

Por isso a tela mostra TODAS as candidatas, inclusive as reprovadas, com o
veredito do juiz ao lado. O que se colhe em `estudo/notas.jsonl` e um par:
o que a pessoa achou e o que a maquina achou da mesma imagem. E esse par que
permite mexer na regua com dado em vez de com gosto.

Roda so em 127.0.0.1, como o receptor: nada aqui precisa estar exposto.
"""

import html
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
for _caminho in (str(AQUI), str(RAIZ)):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ESTUDO = AQUI / "estudo"
LOGOS = ESTUDO / "logos"
SAIDAS = AQUI / "saidas"
NOTAS = ESTUDO / "notas.jsonl"
ELENCO = ESTUDO / "elenco.json"
PORTA = 8790

# slug -> {"estado","log","pasta","erro","comeco"}. Um trabalho por cliente.
TRABALHOS = {}
TRAVA = threading.Lock()


def agora():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def elenco():
    if not ELENCO.exists():
        return []
    return json.loads(ELENCO.read_text(encoding="utf-8"))


def notas():
    """slug -> ultima nota gravada. O arquivo e append-only; vence a ultima."""
    fora = {}
    if NOTAS.exists():
        for linha in NOTAS.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                registro = json.loads(linha)
            except json.JSONDecodeError:
                continue
            fora[registro.get("slug")] = registro
    return fora


def ultima_pasta(slug):
    """A execucao mais recente deste cliente, ou None."""
    raiz = SAIDAS / slug
    if not raiz.is_dir():
        return None
    corridas = sorted((p for p in raiz.iterdir()
                       if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}_\d{4}", p.name)),
                      key=lambda p: p.name)
    return corridas[-1] if corridas else None


# --------------------------------------------------------------------------
# a execucao
# --------------------------------------------------------------------------

def rodar(slug, cliente, setor, logo, candidatas, regua_logo):
    """Roda o `gerar_banners.py auto` e vai anotando a saida linha a linha."""
    comando = [sys.executable, str(AQUI / "gerar_banners.py"), "auto",
               "--logo", str(logo), "--nome", cliente, "--segmento", setor,
               "--candidatas", str(candidatas), "--regua-logo", regua_logo]
    ambiente = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")

    with TRAVA:
        TRABALHOS[slug] = {"estado": "rodando", "log": [], "pasta": None,
                           "erro": None, "comeco": agora()}

    def anotar(linha):
        with TRAVA:
            TRABALHOS[slug]["log"].append(linha.rstrip())
        print(f"  [{slug}] {linha.rstrip()}", flush=True)

    anotar(f"$ gerar_banners.py auto --candidatas {candidatas} "
           f"--regua-logo {regua_logo}")
    try:
        processo = subprocess.Popen(
            comando, cwd=str(RAIZ), env=ambiente, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1)
        for linha in processo.stdout:
            anotar(linha)
            # O `auto` imprime PASTA=... na ultima linha justamente para isto.
            if linha.startswith("PASTA="):
                with TRAVA:
                    TRABALHOS[slug]["pasta"] = linha.split("=", 1)[1].strip()
        processo.wait()
        codigo = processo.returncode
    except Exception as erro:  # noqa: BLE001 - qualquer falha vira estado, nao stack
        with TRAVA:
            TRABALHOS[slug].update(estado="erro", erro=f"{type(erro).__name__}: {erro}")
        return

    with TRAVA:
        TRABALHOS[slug]["estado"] = "pronto" if codigo == 0 else "erro"
        if codigo != 0 and not TRABALHOS[slug]["erro"]:
            TRABALHOS[slug]["erro"] = f"o script saiu com codigo {codigo}"


def candidatas_da_pasta(pasta):
    """As pecas montadas daquela execucao, agrupadas por formato.

    Le do disco em vez de guardar em memoria: assim uma execucao de ontem
    continua pontuavel depois de reiniciar o estudio.
    """
    import formatos as mod_formatos

    pasta = Path(pasta)
    manifesto = {}
    arquivo = pasta / "manifesto.json"
    if arquivo.exists():
        manifesto = json.loads(arquivo.read_text(encoding="utf-8"))

    grupos = []
    for formato in mod_formatos.TODOS:
        itens = []
        for caminho in sorted(pasta.glob(f"{formato.chave}-*")):
            if caminho.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            itens.append({"arquivo": caminho.name,
                          "rotulo": ("fallback deterministico"
                                     if "fallback" in caminho.stem
                                     else f"cena {caminho.stem.rsplit('-', 1)[-1]}"),
                          "fallback": "fallback" in caminho.stem})
        escolhida = (manifesto.get("pecas", {}).get(formato.chave) or {})
        grupos.append({"formato": formato.chave,
                       "dimensao": f"{formato.largura}x{formato.altura}",
                       "origem": escolhida.get("origem", "?"),
                       "itens": itens})
    return grupos, manifesto


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

ESTILO = """
*{box-sizing:border-box} body{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
background:#0f1115;color:#e6e8eb}
a{color:#7bd3b0;text-decoration:none} a:hover{text-decoration:underline}
header{padding:18px 24px;border-bottom:1px solid #242833;display:flex;
gap:18px;align-items:baseline;flex-wrap:wrap;position:sticky;top:0;background:#0f1115;z-index:5}
h1{font-size:17px;margin:0;font-weight:650}
.sub{color:#8b93a1;font-size:13px}
main{padding:22px 24px;max-width:1500px}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.cartao{background:#171a21;border:1px solid #242833;border-radius:10px;padding:14px;
display:flex;flex-direction:column;gap:10px}
.logo{height:64px;display:flex;align-items:center;justify-content:center;
background:#fff;border-radius:6px;padding:8px}
.logo img{max-height:100%;max-width:100%;object-fit:contain}
.nome{font-weight:620} .setor{color:#8b93a1;font-size:12px;min-height:32px}
.linha{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button{font:inherit;padding:7px 13px;border-radius:7px;border:1px solid #2f4f42;
background:#1d3a2f;color:#9fe3c4;cursor:pointer}
button:hover{background:#25493b} button:disabled{opacity:.45;cursor:default}
.selo{font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid #2c3140;color:#98a1b0}
.selo.ok{border-color:#2f5f47;color:#8fdcb4} .selo.erro{border-color:#6b3535;color:#e39c9c}
.selo.rodando{border-color:#5a5330;color:#dfd08a}
.log{font:12px/1.45 ui-monospace,Consolas,monospace;background:#0b0d11;border:1px solid #222633;
border-radius:8px;padding:10px;max-height:220px;overflow:auto;white-space:pre-wrap;color:#a9b2c0}
.peca{background:#171a21;border:1px solid #242833;border-radius:10px;padding:14px;margin:0 0 18px}
.peca img{width:100%;display:block;border-radius:6px;background:#fff}
.tira{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;margin-top:10px}
.veredito{font-size:12px;color:#8b93a1;margin-top:6px}
.mal{color:#e39c9c}
.notas{display:flex;gap:6px;flex-wrap:wrap}
.notas label{border:1px solid #2c3140;border-radius:7px;padding:6px 11px;cursor:pointer}
.notas input{display:none}
.notas input:checked+span{color:#0f1115}
.notas label:has(input:checked){background:#7bd3b0;border-color:#7bd3b0;color:#0f1115}
textarea{width:100%;background:#0b0d11;color:#e6e8eb;border:1px solid #242833;
border-radius:8px;padding:9px;font:inherit;min-height:64px}
.aviso{background:#1d1a12;border:1px solid #4a4225;color:#e0d3a3;padding:10px 12px;
border-radius:8px;margin-bottom:16px}
"""


def pagina(titulo, corpo):
    return f"""<!doctype html><html lang="pt-br"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title><style>{ESTILO}</style>{corpo}"""


def tela_inicial():
    import gerador

    registros = elenco()
    marcadas = notas()
    _, custo_um = gerador.orcamento(2)
    cartoes = []
    for r in registros:
        slug = r["slug"]
        with TRAVA:
            trabalho = dict(TRABALHOS.get(slug) or {})
        estado = trabalho.get("estado")
        pasta = trabalho.get("pasta") or ultima_pasta(slug)
        nota = marcadas.get(slug)
        if estado == "rodando":
            selo = '<span class="selo rodando">gerando…</span>'
        elif estado == "erro":
            selo = '<span class="selo erro">erro</span>'
        elif nota:
            selo = f'<span class="selo ok">nota {html.escape(str(nota.get("media","?")))}</span>'
        elif pasta:
            selo = '<span class="selo ok">gerado</span>'
        else:
            selo = '<span class="selo">nao gerado</span>'

        acoes = [f'<button onclick="gerar(\'{slug}\')">Gerar banners</button>']
        if pasta:
            acoes.append(f'<a href="/cliente?slug={slug}"><button>Ver e pontuar</button></a>')
        logo = (f'<img src="/logo?slug={slug}" alt="">' if r.get("logo")
                else '<span class="sub">sem logo</span>')
        cartoes.append(f"""<div class="cartao" id="c-{slug}">
<div class="logo">{logo}</div>
<div class="nome">{html.escape(r['cliente'])}</div>
<div class="setor">{html.escape(r.get('setor',''))}</div>
<div class="linha">{selo}<span class="selo">{r.get('tamanho') and
    f"{r['tamanho'][0]}x{r['tamanho'][1]}" or '?'}</span></div>
<div class="linha">{''.join(acoes)}</div>
<div class="log" id="l-{slug}" style="display:none"></div></div>""")

    aviso = ""
    if len(registros) * custo_um > gerador.NEURONS_POR_DIA:
        aviso = (f'<div class="aviso">Os {len(registros)} clientes com 2 candidatas '
                 f'custam ~{len(registros) * custo_um} neurons, e o dia tem '
                 f'{gerador.NEURONS_POR_DIA}. Da para fazer uns '
                 f'{gerador.NEURONS_POR_DIA // custo_um} hoje — o resto amanha, '
                 f'ou baixe para 1 candidata.</div>')

    return pagina("Estudio de banners", f"""
<header><h1>Estudio de banners</h1>
<span class="sub">{len(registros)} clientes reais &middot; ~{custo_um} neurons por
cliente (2 candidatas) &middot; {gerador.NEURONS_POR_DIA}/dia gratis</span></header>
<main>{aviso}<div class="grade">{''.join(cartoes)}</div></main>
<script>
const emCurso = new Set();
function gerar(slug){{
  const cx = document.getElementById('l-'+slug); cx.style.display='block';
  cx.textContent = 'iniciando...';
  fetch('/gerar', {{method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{slug: slug, candidatas: 2}})}})
   .then(r=>r.json()).then(()=>{{ emCurso.add(slug); acompanhar(slug); }});
}}
function acompanhar(slug){{
  fetch('/estado?slug='+slug).then(r=>r.json()).then(d=>{{
    const cx = document.getElementById('l-'+slug);
    cx.textContent = (d.log||[]).slice(-14).join('\\n');
    cx.scrollTop = cx.scrollHeight;
    if(d.estado === 'rodando'){{ setTimeout(()=>acompanhar(slug), 1500); }}
    else {{ location.reload(); }}
  }});
}}
</script>""")


def tela_cliente(slug):
    registros = {r["slug"]: r for r in elenco()}
    r = registros.get(slug)
    if not r:
        return None
    with TRAVA:
        pasta = (TRABALHOS.get(slug) or {}).get("pasta")
    pasta = Path(pasta) if pasta else ultima_pasta(slug)
    if not pasta or not pasta.exists():
        return pagina("sem execucao", "<main>Este cliente ainda nao foi gerado. "
                                      "<a href='/'>voltar</a></main>")

    grupos, manifesto = candidatas_da_pasta(pasta)
    contexto = {}
    arquivo = pasta / "contexto.json"
    if arquivo.exists():
        contexto = json.loads(arquivo.read_text(encoding="utf-8"))
    pal = contexto.get("paleta", {})
    marcada = notas().get(slug, {})

    blocos = []
    for grupo in grupos:
        tiras = []
        for item in grupo["itens"]:
            src = (f"/arquivo?pasta={urllib.parse.quote(str(pasta))}"
                   f"&nome={urllib.parse.quote(item['arquivo'])}")
            escolhido = ("&nbsp;<b>← foi esta que o pipeline escolheu</b>"
                         if (grupo["origem"] == "fallback") == item["fallback"] else "")
            tiras.append(f"""<div><img src="{src}" alt="">
<div class="veredito">{html.escape(item['rotulo'])}{escolhido}</div></div>""")
        nome = grupo["formato"]
        atual = marcada.get("pecas", {}).get(nome, {})
        opcoes = "".join(
            f'<label><input type="radio" name="nota-{nome}" value="{n}"'
            f'{" checked" if str(atual.get("nota")) == str(n) else ""}>'
            f'<span>{n}</span></label>' for n in range(1, 6))
        blocos.append(f"""<div class="peca">
<div class="linha"><b>{nome}</b><span class="selo">{grupo['dimensao']}</span>
<span class="selo">saiu por: {html.escape(grupo['origem'])}</span></div>
<div class="tira">{''.join(tiras)}</div>
<div class="linha" style="margin-top:12px">
  <span class="sub">nota 1 a 5:</span><div class="notas">{opcoes}</div></div>
<textarea name="obs-{nome}" placeholder="o que estragou, ou o que ficou bom"
>{html.escape(str(atual.get('obs','')))}</textarea></div>""")

    return pagina(r["cliente"], f"""
<header><h1>{html.escape(r['cliente'])}</h1>
<span class="sub">{html.escape(r.get('setor',''))} &middot;
paleta {html.escape(pal.get('principal',''))} {html.escape(pal.get('destaque',''))}
&middot; <a href="/">todos os clientes</a></span></header>
<main><form id="f">{''.join(blocos)}
<div class="linha"><button type="button" onclick="salvar()">Salvar notas</button>
<span id="ok" class="sub"></span></div></form></main>
<script>
function salvar(){{
  const pecas = {{}};
  document.querySelectorAll('textarea').forEach(t=>{{
    const nome = t.name.replace('obs-','');
    const marcado = document.querySelector(`input[name="nota-${{nome}}"]:checked`);
    pecas[nome] = {{nota: marcado ? Number(marcado.value) : null, obs: t.value}};
  }});
  fetch('/nota', {{method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{slug:'{slug}', pasta:{json.dumps(str(pasta))}, pecas:pecas}})}})
   .then(r=>r.json()).then(d=>{{
     document.getElementById('ok').textContent = 'salvo — media '+d.media;
   }});
}}
</script>""")


# --------------------------------------------------------------------------
# servidor
# --------------------------------------------------------------------------

class Manipulador(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):
        pass  # o log util e o do subprocesso, nao o de cada GET de imagem

    def _responder(self, codigo, corpo, tipo="text/html; charset=utf-8"):
        dados = corpo if isinstance(corpo, bytes) else corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _json(self, codigo, dados):
        self._responder(codigo, json.dumps(dados, ensure_ascii=False),
                        "application/json; charset=utf-8")

    def _servir_arquivo(self, caminho):
        """Serve um arquivo, mas so de dentro de saidas/ ou estudo/.

        A checagem e no caminho RESOLVIDO: sem ela, `nome=../../.env` sairia
        pela porta 8790. Bind em 127.0.0.1 nao dispensa isso — o navegador do
        proprio usuario e um cliente local.
        """
        try:
            alvo = Path(caminho).resolve()
        except OSError:
            return self._responder(400, "caminho invalido")
        if not any(alvo.is_relative_to(p.resolve()) for p in (SAIDAS, ESTUDO)):
            return self._responder(403, "fora das pastas do estudo")
        if not alvo.is_file():
            return self._responder(404, "nao encontrado")
        tipo = mimetypes.guess_type(alvo.name)[0] or "application/octet-stream"
        self._responder(200, alvo.read_bytes(), tipo)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        campos = urllib.parse.parse_qs(url.query)
        slug = (campos.get("slug") or [""])[0]

        if url.path == "/":
            return self._responder(200, tela_inicial())
        if url.path == "/cliente":
            tela = tela_cliente(slug)
            return self._responder(200 if tela else 404, tela or "cliente desconhecido")
        if url.path == "/estado":
            with TRAVA:
                return self._json(200, dict(TRABALHOS.get(slug) or {"estado": "parado"}))
        if url.path == "/logo":
            r = {x["slug"]: x for x in elenco()}.get(slug)
            if not r or not r.get("logo"):
                return self._responder(404, "sem logo")
            return self._servir_arquivo(LOGOS / r["logo"])
        if url.path == "/arquivo":
            pasta = (campos.get("pasta") or [""])[0]
            nome = (campos.get("nome") or [""])[0]
            return self._servir_arquivo(Path(pasta) / nome)
        return self._responder(404, "nao encontrado")

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"erro": "json invalido"})
        url = urllib.parse.urlparse(self.path)

        if url.path == "/gerar":
            slug = corpo.get("slug")
            r = {x["slug"]: x for x in elenco()}.get(slug)
            if not r:
                return self._json(404, {"erro": "cliente desconhecido"})
            if not r.get("logo"):
                return self._json(400, {"erro": "cliente sem logo"})
            with TRAVA:
                if (TRABALHOS.get(slug) or {}).get("estado") == "rodando":
                    return self._json(202, {"estado": "ja rodando"})
            threading.Thread(target=rodar, daemon=True, args=(
                slug, r["cliente"], r.get("setor", ""), LOGOS / r["logo"],
                int(corpo.get("candidatas") or 2),
                # Marca horizontal (Cobra 205x58) reprova na regua do banner. No
                # estudo ela entra assim mesmo: ver a peca ruim e o dado que
                # decide se aquela regua procede.
                "portal")).start()
            return self._json(202, {"estado": "rodando"})

        if url.path == "/nota":
            pecas = corpo.get("pecas") or {}
            dadas = [p["nota"] for p in pecas.values() if p.get("nota")]
            media = round(sum(dadas) / len(dadas), 2) if dadas else None
            registro = {"slug": corpo.get("slug"), "pasta": corpo.get("pasta"),
                        "pecas": pecas, "media": media, "em": agora()}
            with NOTAS.open("a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
            print(f"  [nota] {registro['slug']}: media {media}", flush=True)
            return self._json(200, {"ok": True, "media": media})

        return self._json(404, {"erro": "rota desconhecida"})


def main():
    import gerar_banners
    gerar_banners._carregar_env()
    ESTUDO.mkdir(parents=True, exist_ok=True)
    if not ELENCO.exists():
        print(f"[ERRO] {ELENCO} nao existe — nao ha elenco para estudar.")
        return 1
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Manipulador)
    print("=" * 62)
    print(f"  ESTUDIO DE BANNERS   http://127.0.0.1:{PORTA}")
    print(f"  {len(elenco())} clientes  |  notas em {NOTAS}")
    print("  Ctrl+C encerra.")
    print("=" * 62, flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
