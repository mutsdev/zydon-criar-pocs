"""Checa o parser de pagina de produto sem rede (Irroba: imagem da pagina, nao og)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Criar Portais"))
import coletar_site  # noqa: E402

HTML = """<title>ÓCULOS PIGEON | Loja X</title>
<meta property="og:image" content="https://img/logo.png">
<img class="img-fluid product-image-area" src="https://img.irroba.com.br/fit-in/600x600/a.jpg">
<span>R$ 1.234,50</span>
<ul data-option-name="ESCOLHA O TAMANHO"></ul>"""


class _R:
    text = HTML


def test_pagina_produto(monkeypatch):
    monkeypatch.setattr(coletar_site, "_get", lambda url, **k: _R())
    i = coletar_site._pagina_produto("https://x/p")
    assert i["nome"] == "ÓCULOS PIGEON"
    assert i["imagem"] == "https://img.irroba.com.br/fit-in/1000x1000/a.jpg"
    assert i["preco"] == 1234.5
    assert i["variantes"] == ["ESCOLHA O TAMANHO"]
