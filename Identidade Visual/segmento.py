"""Segmento do cliente -> objetos concretos e ambiente para a cena.

Era a "Etapa 0" do GEM, feita pelo proprio modelo de imagem. Aqui e uma chamada
de texto separada, e o resultado fica **em cache por segmento**: dois clientes
de autopecas recebem a mesma lista, o que torna a peca reproduzivel e nao gasta
chamada a toa. O cache tambem e o lugar onde o Joao Pedro corrige a mao quando
a lista sai ruim — e ai ela fica corrigida para sempre.

Sem chave, ou sem rede, cai numa heuristica local. Nao poder falar com a API
nunca pode ser motivo para o pipeline parar.
"""

import json
import re
import unicodedata
from pathlib import Path

import requests

import juiz

AQUI = Path(__file__).resolve().parent
CACHE = AQUI / "cache_segmentos.json"

GENERICO = {
    "objetos": ["caixas de papelao kraft empilhadas", "paletes de madeira",
                "engradados plasticos", "rolos de fita e material de expedicao"],
    "ambiente": "galpao de distribuicao amplo, prateleiras ao fundo",
    "origem": "generico",
}

INSTRUCAO = """Um portal de compras B2B vai receber um banner fotografico para
um cliente do segmento abaixo. Preciso saber o que fotografar.

Segmento: {segmento}

Responda SOMENTE JSON com duas chaves:
- objetos: lista de 4 a 6 objetos FISICOS e CONCRETOS daquele ramo, que
  apareceriam em primeiro plano numa foto de campanha. Coisas, nao conceitos.
  Nada que tenha texto, rotulo ou marca visivel.
- ambiente: uma frase curta descrevendo o local de trabalho tipico do ramo,
  para ficar desfocado ao fundo.

Tudo em portugues do Brasil."""


def _chave(segmento):
    texto = unicodedata.normalize("NFKD", segmento.strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-") or "generico"


def _ler_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Cache corrompido nao pode derrubar o pipeline: vale menos que ele.
            return {}
    return {}


def _gravar_cache(dados):
    CACHE.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")


def resolver(segmento, modelo, usar_rede=True):
    """Devolve {'objetos': [...], 'ambiente': str, 'origem': str}."""
    chave = _chave(segmento)
    cache = _ler_cache()
    if chave in cache:
        registro = dict(cache[chave])
        registro["origem"] = "cache"
        return registro

    if not usar_rede:
        return dict(GENERICO)

    try:
        corpo = {
            "contents": [{"role": "user", "parts": [
                {"text": INSTRUCAO.format(segmento=segmento)}]}],
            "generationConfig": {"response_mime_type": "application/json",
                                 "temperature": 0},
        }
        resposta = requests.post(f"{juiz.BASE}/models/{modelo}:generateContent",
                                 params={"key": juiz.chave()}, json=corpo, timeout=120)
        resposta.raise_for_status()
        texto = "".join(p.get("text", "") for p in
                        resposta.json()["candidates"][0]["content"]["parts"])
        dados = json.loads(texto)
        objetos = [str(o) for o in dados.get("objetos", [])][:6]
        ambiente = str(dados.get("ambiente", "")).strip()
        if len(objetos) < 3 or not ambiente:
            raise ValueError(f"resposta magra: {dados}")
    except (requests.RequestException, juiz.SemChave, KeyError, ValueError,
            json.JSONDecodeError) as erro:
        registro = dict(GENERICO)
        registro["erro"] = f"{type(erro).__name__}: {erro}"
        return registro

    registro = {"objetos": objetos, "ambiente": ambiente}
    cache[chave] = registro
    _gravar_cache(cache)
    saida = dict(registro)
    saida["origem"] = "consultado"
    return saida
