# Telufia: como ativar a consultora de IA num portal de POC

A Telufia é a Zoe (a IA da Zydon) configurada como consultora comercial de
uma POC. Ela conhece os produtos do portal, faz perguntas antes de
recomendar, sugere combos e consulta preço e estoque pelas ferramentas da
Zoe.

Foi testada em 2026-09-29 nos portais Guaracamp e Politintas, da org
`pocs`.

## Como funciona

- A configuração da Zoe é **por portal**. Para gravar, é preciso fazer
  login com o `solution_id` do portal. A chave da org sozinha grava no
  portal base ("Apresentações POCS"), não no portal da POC.
- Tudo vai numa única chamada: `PUT /api/ai/zoe/configurations` com nome,
  personalidade e prompt.
- O conhecimento dos produtos vai **resumido dentro do prompt**. A base de
  conhecimento (`knowledge-resources`) não é usada.
- O modelo, `GEMINI_2_5_FLASH`, é escolhido pela Zydon. Não precisa enviar.

## Passo a passo

### 1. Achar o `solution_id` do portal

```python
import requests, credenciais as c

h, _ = c.carregar("pocs")
sols = requests.get(c.SOLUTIONS_URL, headers=h, timeout=20).json()["items"]
for s in sols:
    if "politintas" in s["name"].lower():
        print(s["id"], s["name"])
```

Se aparecerem dois portais com o mesmo nome (duplicação repetida), ative
nos dois.

### 2. Fazer login no portal

```python
r = requests.post(
    f"{c.ACCOUNT_BASE_URL}/access-key/login",
    json={
        "code": h["X-Zydon-Access-Key-Code"],
        "token": h["X-Zydon-Access-Key-Token"],
        "solution_id": SOLUTION_ID,
    },
    timeout=20,
)
B = {"Authorization": "Bearer " + r.json()["accessToken"]}
```

É o mesmo login que o `obter_jwt_portal` do `criar_poc.py` já faz.

### 3. Ver se o portal já tem Zoe

```python
z = requests.get("https://api.zydon.com.br/api/ai/zoe/configurations", headers=B, timeout=20)
```

- `204`: ainda não tem configuração.
- `200`: já tem. O `PUT` do passo 5 substitui a configuração atual.

### 4. Montar o prompt

Use o modelo da seção abaixo. Os dados de cada produto (nome, SKU, preço,
mínimo, categoria) vêm do JSON da POC. As etapas `products` e
`categories` têm tudo. Escreva a consultoria com base no site do cliente.

### 5. Ativar

```python
body = {
    "assistant_name": "Telufia",
    "assistant_personality": PERSONALIDADE,
    "assistant_prompt": PROMPT,
}
p = requests.put("https://api.zydon.com.br/api/ai/zoe/configurations",
                 headers=B, json=body, timeout=30)
print(p.status_code)  # 200 = ativada
```

Confira com um `GET` na mesma rota: `assistant_name` deve vir `Telufia`.

### 6. Testar

Abra o portal (a URL está em `GET /api/b2b/portals/info`, campo `url`),
entre e abra o chat da Zoe. Faça uma pergunta de consultoria, por exemplo:
"Tenho uma lanchonete pequena, o que você me recomenda?". Ela deve
perguntar sobre o ponto de venda e terminar sugerindo um combo.

## Modelo do prompt

Troque o que está entre chaves.

**Personalidade**

```text
Oi, sou a Telufia, consultora comercial da {EMPRESA}. {Uma frase sobre o que ela faz pelo cliente}.
```

**Prompt**

```text
Você é a Telufia, consultora comercial da {EMPRESA}. {Descrição da empresa: o que vende, marcas, para quem}.

Objetivo: ajudar o cliente a montar o pedido certo ({critérios do segmento, ex.: giro, margem, formato}). Antes de recomendar, pergunte {as 2 ou 3 perguntas que definem a recomendação no segmento}.

Catálogo de referência (valores da POC; confirme preço e estoque atuais pelas ferramentas, nunca use estes valores como final):

{CATEGORIA EM MAIÚSCULAS}
- {Nome do produto} ({SKU}) · R$ {preço} · mín. {mínimo}. {2 a 4 frases: uso, público, argumento de venda, combo}.

Regras:
- Recomende só itens deste catálogo. Nunca invente preço, estoque, sabor, cor ou embalagem.
- Se o preço vier nulo ou o item estiver indisponível, diga "Preço indisponível", nunca "R$ 0,00". Sem estoque, diga "Estoque indisponível".
- Para dados atualizados, use: [Ver detalhes do produto](TOOL:get_product_details), [Buscar produtos](TOOL:search_products), [Encontrar variações de um produto](TOOL:find_product_variations), [Buscar produtos similares](TOOL:get_similar_products), [Buscar produtos recomendados](TOOL:get_recommended_products), [Ver descontos por quantidade do produto](TOOL:get_quantity_discounts), [Listar categorias](TOOL:list_categories).
- Para montar o pedido, use: [Adicionar itens ao carrinho](TOOL:add_cart_item), [Ver carrinho](TOOL:get_cart), [Finalizar compra](TOOL:create_order).
- O catálogo acima serve para a consultoria (uso, público, combo). Preço e estoque final vêm sempre das ferramentas.
- Respostas curtas e consultivas. Termine sempre com um próximo passo ou um combo sugerido.
```

Exemplo de linha do catálogo (Guaracamp):

```text
- Guaracamp Concentrado 1L (GRC-CON-001) · R$ 8,90 · mín. 12. Carro-chefe, rende até 10 L de refresco. Uso: família que dilui em casa. Argumento: menor custo por litro. Combo: Uvacamp e Groselhacamp.
```

### Boas práticas para a consultoria

- Escreva a partir do site do cliente. Não invente característica técnica
  que o site não mostra.
- Cada ficha responde: para que serve, para quem, por que comprar e o que
  vender junto.
- As perguntas iniciais mudam por segmento. Bebidas: tipo de ponto de
  venda e volume. Tintas: superfície, área e se é interna ou externa.
- Com 12 a 14 produtos, o prompt fica com cerca de 3,5 mil caracteres e
  funcionou bem. O limite de tamanho ainda não foi medido.

## Ferramentas disponíveis

Para citar uma ferramenta, escreva `[título](TOOL:id)` no prompt. A lista
completa (39 ferramentas) vem de:

```
GET https://api.zydon.com.br/api/ai/zoe/configurations/tools?page=0&perPage=100
```

As que a Telufia usa:

| id | Para quê |
|---|---|
| `get_product_details` | Preço, estoque e detalhes atualizados |
| `search_products` | Buscar no catálogo |
| `find_product_variations` | Cor, tamanho, código |
| `get_similar_products` / `get_recommended_products` | Alternativas e combos |
| `get_quantity_discounts` | Desconto por quantidade |
| `list_categories` | Categorias do portal |
| `add_cart_item` / `get_cart` / `create_order` | Montar e fechar o pedido |

## Rotas da Zoe

Base: `https://api.zydon.com.br/api/ai/zoe`. Autenticação com o
`Authorization: Bearer` do login do portal.

| Rota | Uso |
|---|---|
| `GET /configurations` | Ler a configuração (`204` = não configurada) |
| `PUT /configurations` | Criar ou atualizar |
| `GET /configurations/tools` | Listar ferramentas |
| `GET /configurations/knowledge-resources` | Base de conhecimento (não usada) |
| `GET /chats` | Conversas do portal |

Essas rotas não estão na documentação pública (docs.zydon.com.br). Foram
descobertas gravando o painel admin com o DevTools aberto. Se a Zydon
mudar alguma coisa, repita a gravação: DevTools, aba Network, Fetch/XHR,
ativar a Zoe e exportar o HAR.

**Segurança:** o HAR contém cookies e tokens de sessão. Não versione esse
arquivo e apague depois de usar.

## Próximo passo

Automatizar: um bloco `telufia` no JSON da POC e a ativação como última
etapa do `criar_poc.py`. O desenho está em
[specs/2026-09-29-telufia-design.md](superpowers/specs/2026-09-29-telufia-design.md).
