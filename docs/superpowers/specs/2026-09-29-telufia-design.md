# Telufia: agente consultor ativado junto com a POC

Data: 2026-09-29

## Objetivo

Toda POC criada pelo `criar_poc.py` sai com a Zoe ativada no portal da POC,
com o nome **Telufia** e um perfil de consultora comercial. Ela responde
sobre os produtos do JSON da POC: indicação de uso, público, argumento de
venda e combos. Preço e estoque ela consulta sempre pelas ferramentas.

## Decisões tomadas

- O conhecimento dos produtos vai resumido dentro do `assistant_prompt`. A
  base de conhecimento (`knowledge-resources`) não é usada.
- As fichas de consultoria são escritas junto com o JSON, pela skill
  `criar-pocs`, a partir do site do cliente.
- A ativação é a última etapa do `criar_poc.py`, no portal recém-duplicado.
- Se a ativação falhar, a POC não é desfeita. O processo só avisa, como
  já acontece com a identidade visual.
- O nome é sempre `Telufia`.

## Escopo da configuração: por portal

A configuração da Zoe vale **por portal**. Testado em 2026-09-29: com a
chave da org, o `PUT` grava no portal base ("Apresentações POCS"). Com o
JWT do login `access-key/login` + `solution_id`, grava no portal da POC.
Cada POC tem a sua Telufia, sem sobrescrever as outras.

## API

Base: `https://api.zydon.com.br/api/ai/zoe`. Autenticação com os mesmos
headers do `credenciais.carregar()` (`X-Zydon-Access-Key-Code` e
`X-Zydon-Access-Key-Token`). Testado na org `pocs`: `GET /configurations`
devolveu `204` e `GET /configurations/tools` devolveu `200`.

- `PUT /configurations` com
  `{"assistant_name", "assistant_personality", "assistant_prompt"}` cria ou
  atualiza a configuração. A resposta traz `id` e
  `assistant_model: GEMINI`.
- Ferramentas são citadas no prompt como `[título](TOOL:id)`. Os IDs vêm
  de `GET /configurations/tools`.

## Formato no JSON

Bloco opcional na raiz:

```json
"telufia": {
  "contexto": "O que a empresa vende, para quem e qual o diferencial.",
  "produtos": [
    {"sku": "GRC-CON-001", "consultoria": "2 a 4 frases: uso, público, argumento, combo."}
  ]
}
```

Nome, preço, mínimo de venda e categoria de cada produto são lidos das
etapas `products` e `categories`, sem repetir no bloco. Sem o bloco
`telufia`, a ativação é pulada.

## Componentes

**`Criar Portais/telufia.py`** (novo)

- `montar_prompt(poc) -> (personalidade, prompt)`: junta o modelo fixo com
  o `contexto` e um catálogo agrupado por categoria, com uma linha por
  produto: nome, SKU, preço, mínimo e consultoria. Não faz chamadas de rede.
- `ativar(poc, headers, portal_id) -> bool`: faz login no portal com
  `obter_jwt_portal`, depois o `PUT /configurations` com
  `Authorization: Bearer`, e devolve `True` quando a resposta é 2xx.
- Modo `__main__`: `python telufia.py arquivo.json [org] [--dry-run]`.
  Serve para reativar ou só imprimir o prompt.

O modelo fixo do prompt tem estas seções:

- **Papel:** consultora da {empresa}.
- **Objetivo:** montar o pedido certo, perguntando antes o tipo de ponto de
  venda e o volume.
- **Catálogo:** os valores da POC servem só de referência.
- **Regras:**
  - só recomenda itens do catálogo;
  - nunca inventa preço nem estoque;
  - quando o preço é nulo, diz "Preço indisponível", nunca R$ 0,00;
  - sem estoque, diz "Estoque indisponível".
- **Ferramentas de consulta:** `get_product_details`, `search_products`,
  `find_product_variations`, `get_similar_products`,
  `get_recommended_products`, `get_quantity_discounts` e `list_categories`.
- **Ferramentas de pedido:** `add_cart_item`, `get_cart` e `create_order`.
- **Estilo:** respostas curtas, sempre terminando com um próximo passo ou
  um combo sugerido.

**`Criar Portais/criar_poc.py`**: depois da regra de listagem, se o bloco
`telufia` existir, chama `telufia.ativar`. O resumo final ganha a linha
`Telufia : OK / FALHOU / sem bloco`. O valor de retorno do `run_poc` não
muda.

**`Criar Portais/validar_poc.py`**: se o bloco existir, confere três
coisas:

- o `contexto` não está vazio;
- cada `sku` existe nas etapas `products`;
- cada `consultoria` não está vazia.

Produtos sem ficha só geram aviso: eles entram no catálogo com a
descrição do produto.

**Skill `criar-pocs` e `ESTRUTURA-JSON.md`**: uma seção nova explicando
como escrever o bloco `telufia`, com fichas baseadas no site e nunca
inventadas. `template_poc.json` recebe um bloco de exemplo.

## Testes

`tests/test_telufia.py`, sem chamadas de rede:

- o prompt contém cada SKU, preço e consultoria de um JSON de exemplo;
- produto sem ficha usa a `description` do produto;
- as citações de ferramenta estão no formato `(TOOL:id)`;
- sem o bloco, `ativar` não é chamado. O teste usa um mock de `requests`.

Validação manual: rodar `telufia.py guaracamp_poc.json pocs --dry-run`,
depois rodar sem `--dry-run` na org `pocs` e fazer uma pergunta de
consultoria no chat do portal.

## Fora de escopo

Base de conhecimento, `assistant_keywords` e troca de modelo. Entram só
se o prompt ficar grande demais.
