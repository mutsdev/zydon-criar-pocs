"""Gera contato.html: todas as tentativas lado a lado, com o veredito embaixo.

E aqui que o julgamento humano acontece, e por isso a folha mostra tambem o que
REPROVOU — a tentativa descartada e o dado mais valioso que o sistema produz,
porque e ela que diz se a regua concorda com o Joao Pedro.

HTML estatico com caminhos relativos: abre com duplo clique, sem servidor.
"""

import html
import json
from pathlib import Path

ESTILO = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px; background: #12141a; color: #e8eaf0;
       font: 15px/1.55 ui-sans-serif, system-ui, "Segoe UI", sans-serif; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -.01em; }
.sub { color: #8b93a7; margin-bottom: 28px; font-size: 14px; }
.paleta { display: flex; gap: 8px; margin: 12px 0 30px; align-items: center; }
.chip { width: 26px; height: 26px; border-radius: 6px; border: 1px solid #333a4a; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: .08em;
     color: #8b93a7; margin: 34px 0 12px; border-top: 1px solid #262b38;
     padding-top: 16px; }
.grade { display: grid; gap: 18px;
         grid-template-columns: repeat(auto-fill, minmax(430px, 1fr)); }
.cartao { background: #191c25; border: 1px solid #262b38; border-radius: 10px;
          overflow: hidden; display: flex; flex-direction: column; }
.cartao.aprovado { border-color: #2f7d55; }
.cartao.reprovado { border-color: #7d3a3a; }
.cartao.fallback { border-color: #6b5a2a; }
.cartao img { width: 100%; display: block; background: #0c0e13; }
.corpo { padding: 12px 14px 14px; }
.rotulo { display: inline-block; font-size: 11px; font-weight: 700;
          letter-spacing: .06em; padding: 3px 8px; border-radius: 20px;
          text-transform: uppercase; }
.aprovado .rotulo { background: #1d3d2b; color: #7ee2a8; }
.reprovado .rotulo { background: #3d1d1d; color: #f0a0a0; }
.fallback .rotulo { background: #3a3018; color: #e7c579; }
.motivo { margin-top: 9px; font-size: 13px; color: #c7ccd9; }
.motivo b { color: #f0a0a0; font-weight: 600; }
.nota { float: right; font-size: 13px; color: #8b93a7; }
details { margin-top: 10px; }
summary { cursor: pointer; font-size: 12px; color: #7b86a0; }
pre { white-space: pre-wrap; word-break: break-word; font-size: 11.5px;
      color: #9aa3b8; background: #0f1219; padding: 10px; border-radius: 6px;
      max-height: 260px; overflow: auto; margin: 8px 0 0; }
.vazio { color: #6b7488; font-style: italic; }
"""


def _cartao(item, raiz):
    estado = item["estado"]  # aprovado | reprovado | fallback
    caminho = Path(item["imagem"])
    try:
        rel = caminho.relative_to(raiz).as_posix()
    except ValueError:
        rel = caminho.as_posix()

    motivos = item.get("motivos") or []
    nota = item.get("nota")
    partes = [f'<div class="cartao {estado}">',
              f'<img src="{html.escape(rel)}" alt="{html.escape(item["titulo"])}" '
              f'loading="lazy">', '<div class="corpo">']
    if nota is not None:
        partes.append(f'<span class="nota">estetica {nota}/5</span>')
    partes.append(f'<span class="rotulo">{estado}</span> '
                  f'{html.escape(item["titulo"])}')
    if motivos:
        lista = ", ".join(html.escape(str(m)) for m in motivos)
        partes.append(f'<div class="motivo"><b>{lista}</b></div>')
    elif item.get("observacao"):
        partes.append(f'<div class="motivo">{html.escape(item["observacao"])}</div>')

    for titulo, conteudo in (("prompt usado", item.get("prompt")),
                             ("veredito completo", item.get("detalhe"))):
        if conteudo:
            texto = conteudo if isinstance(conteudo, str) else json.dumps(
                conteudo, indent=2, ensure_ascii=False)
            partes.append(f'<details><summary>{titulo}</summary>'
                          f'<pre>{html.escape(texto)}</pre></details>')
    partes.append("</div></div>")
    return "".join(partes)


def escrever(destino, cliente, paleta, secoes):
    """`secoes` e uma lista de (titulo, [item, ...]). Devolve o caminho gravado."""
    destino = Path(destino)
    raiz = destino.parent

    chips = "".join(
        f'<span class="chip" style="background:{html.escape(paleta[c])}" '
        f'title="{c}: {html.escape(paleta[c])}"></span>'
        f'<code style="color:#8b93a7;font-size:12px">{html.escape(paleta[c])}</code>'
        for c in ("principal", "destaque", "neutra"))

    corpo = [f"<h1>{html.escape(cliente)}</h1>",
             '<div class="sub">Folha de contato — todas as tentativas, '
             'inclusive as reprovadas. Discordou do veredito? '
             "Ajuste <code>regua.json</code>.</div>",
             f'<div class="paleta">{chips}</div>']

    for titulo, itens in secoes:
        corpo.append(f"<h2>{html.escape(titulo)}</h2>")
        if not itens:
            corpo.append('<p class="vazio">nenhuma tentativa</p>')
            continue
        corpo.append('<div class="grade">')
        corpo.extend(_cartao(i, raiz) for i in itens)
        corpo.append("</div>")

    destino.write_text(
        "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
        f"<title>Banners — {html.escape(cliente)}</title>"
        f"<style>{ESTILO}</style></head><body>{''.join(corpo)}</body></html>",
        encoding="utf-8")
    return destino
