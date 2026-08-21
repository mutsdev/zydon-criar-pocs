# Estrutura do JSON de POC

O JSON de POC é **declarativo**: descreve tudo que a POC precisa (marca,
categorias, produtos, critérios, tabelas de preço, descontos) e o
`criar_poc.py` executa etapa por etapa contra a API da Zydon, resolvendo as
dependências entre as entidades por meio de placeholders.

**Fonte da verdade: `Criar Portais/template_poc.json`** — copie e adapte, não
recrie do zero. O `Criar Portais/validar_poc.py` verifica automaticamente
tudo que está descrito aqui; um JSON só está pronto quando valida com 0 erros.

## Visão geral

```json
{
  "empresa": "EMPRESA",
  "descricao_empresa": "Descrição curta da empresa.",
  "gerado_em": "AAAA-MM-DD",
  "setor": "Setor — Subsetor",
  "portal_name": "EMPRESA POC",
  "portal_listing_rule_id": "{{criteria_listagem_id}}",
  "etapas": [ ... ]
}
```

| Campo raiz | Obrigatório | O que é |
|---|---|---|
| `empresa` | sim | Nome da empresa |
| `descricao_empresa` | sim | Uma frase sobre a empresa |
| `gerado_em` | sim | Data de geração (AAAA-MM-DD) |
| `setor` | sim | Setor real, visto no site (nunca inferido pelo nome) |
| `portal_name` | sim | Nome do portal criado |
| `portal_listing_rule_id` | sim | Sempre o literal `"{{criteria_listagem_id}}"` |
| `etapas` | sim | Lista de etapas, na ordem de execução |

## O mecanismo: etapas, requests e placeholders

Cada etapa tem `nome` (só exibição), `endpoint` e uma lista de `requests`.
Cada request tem:

- `label` — identificação no log e no relatório;
- `payload` — o corpo do POST enviado à API;
- `salvar_id_como` (opcional) — nome sob o qual o ID retornado pela API fica
  guardado para as etapas seguintes;
- `temp_image_url` (opcional, produtos) — URL da imagem, **no nível do
  request, fora do payload**.

Um ID salvo em uma etapa é referenciado nas seguintes como `{{nome}}`. O
`criar_poc.py` resolve os placeholders recursivamente em qualquer
profundidade do payload. Exemplo: a marca salva `brand_id`, e todo produto usa
`"brand_id": "{{brand_id}}"`.

Regras dos placeholders:
- `salvar_id_como` só com letras/números/underscore — **nunca colchetes**
  (`cat_ids[0]` quebra a resolução; use `cat_ids_0`);
- todo placeholder usado precisa ter sido definido em etapa anterior — o
  validador bloqueia referência a ID inexistente.

## As etapas, na ordem

### 1. MARCA (`endpoint: brands`)
Um request. `salvar_id_como: "brand_id"`. Payload:
`{"name": "EMPRESA", "active": true, "images": []}`.

### 2. CATEGORIAS (`endpoint: categories`)
Exatamente **3 requests**, com `salvar_id_como` `cat_ids_0`, `cat_ids_1`,
`cat_ids_2`. Mesmo formato de payload da marca.

### 3. VARIAÇÕES (`endpoint: variations`) — opcional
Só quando a POC tem produtos com grade (cor, tamanho, voltagem…). **Sempre
antes de PRODUTOS** — os produtos referenciam `{{variation_*_id}}`. Bloco
pronto em `Criar Portais/template_variacoes.json`; detalhes na seção
"Variações" abaixo.

### 4. PRODUTOS (`endpoint: products`)
De **9 a 15** requests (máximo 15). Cada request:

```json
{
  "label": "SKU-001 — Nome do Produto",
  "temp_image_url": "https://.../imagem.jpg",
  "payload": {
    "sku": "SKU-001",
    "name": "Nome do Produto",
    "description": "Descrição comercial.",
    "active": true,
    "stock": 100,
    "minimum_stock": 0,
    "standard_unit_id": 2,
    "images": [],
    "category_id": "{{cat_ids_0}}",
    "brand_id": "{{brand_id}}",
    "ean_gtin": "",
    "video_url": "",
    "highlight": true,
    "price": 219.90,
    "minimum_for_sale": 3,
    "multiple_for_sale": 6
  }
}
```

Regras que o validador cobra:
- `sku` obrigatório e **único** (inclusive entre variantes);
- `price` em **reais decimais** (`219.90` = R$ 219,90) — **nunca centavos**;
  o script não converte, o valor vai direto para a API;
- `temp_image_url` obrigatório em **todo** produto, no request (URL direta em
  `payload.images` causa 500 NPE na API);
- `stock: 100`, `minimum_stock: 0`, `active: true`, `images: []` sempre;
- `standard_unit_id: 2` — o script sobrescreve com o valor da organização,
  mas o campo precisa existir;
- `minimum_for_sale`/`multiple_for_sale` **variados** entre produtos e
  coerentes com a embalagem (caixa, fardo, unidade); ~30% podem ser 1/1;
  sempre `multiple >= minimum`;
- `highlight: true` só nos produtos principais.

### 5. CRITÉRIOS (`endpoint: criteria`)
Etapa com `base_url` próprio: `"https://api.zydon.com.br/api/database"`.
Critérios são filtros reutilizáveis; **um critério por finalidade, nunca
compartilhado** — apagar uma entidade (ex.: um desconto) apaga o critério
vinculado e deixa as demais sem filtro (efeito cascata).

| `salvar_id_como` | Filtro | Usado por |
|---|---|---|
| `criteria_preco_id` | por **marca** | as 3 tabelas de preço |
| `criteria_listagem_id` | por **marca** | `portal_listing_rule_id` |
| `criteria_cat_<slug>_id` | por **categoria** (um por categoria com desconto) | exclusivamente os descontos |

Filtro por marca: `config.brands` com `key: "this.CODIGOMARCA"` e
`values: ["{{brand_id}}"]`. Filtro por categoria: `config.categories` com
`key: "this.CODCATEGORIA"` e `values: ["{{cat_ids_N}}"]`.

`database_id` é o da base "Produtos" **da organização onde a POC vai rodar**
(orgs de POC: `5ba882ff-ba29-4599-b583-0bf9b8913b19`). Em org nova, descubra
com `GET /api/database/databases`.

### 6. TABELAS DE PREÇO (`endpoint: price-tables`)
Sempre **3 tabelas**, perfis (segmentos) **2, 3 e 4**, nomeadas
`"Tabela 1 | EMPRESA"`, `"Tabela 2 | EMPRESA"`, `"Tabela 3 | EMPRESA"` — sem
nome de segmento. O desconto vai em `criteria[0].value`
(`rate_type: DECREASE`, `value_type: PERCENTAGE`, `criteria_type: FILTER`,
`criteria_id: "{{criteria_preco_id}}"`).

- **Nunca** usar `discount_percentage` nem `minimum_order_value` (causam 400).
- `profiles` sempre lista de objetos: `[{"profile_id": "2"}]` — nunca inteiros.
- `is_profile_specific: true`; os outros `is_*_specific` false, listas vazias.
- `end_date` obrigatório: `"2060-01-01"` (ausente causa 500 NPE `LocalDate`).
- Descontos das 3 tabelas **distintos e com spread agressivo**: diferença
  mínima de 15 pontos entre o menor e o maior (ex.: 5/15/30 ✅, 8/10/12 ❌).
  O segmento mais aderente ao core da empresa recebe o maior desconto.

Segmentos da org pocs: 2 Material de Construção · 3 Indústria/Manufatura ·
4 Suprimentos Industriais · 5 Autopeças · 6 Saúde · 7 Agronegócio ·
8 Alimentos · 9 Equipamentos · 10 Embalagens · 11 Tecnologia.

### 7. DESCONTOS (`endpoint: discounts`)
Pelo menos **1 progressivo** (`type: PROGRESSIVE`, `is_profile: true`, 1
segmento) e **1 fixo** (`type: FIXED`, `is_profile: false`).

- `criteria[].criteria_id` **sempre** um `criteria_cat_<slug>_id` (categoria)
  — nunca `criteria_preco_id`/`criteria_listagem_id`. O validador bloqueia.
- O desconto fixo começa em `minimum_quantity: 0` (nunca 1) — vale a partir
  de qualquer quantidade.
- Atenção aos nomes de campo: o endpoint `discounts` usa
  `is_profile`/`is_partner`/… (**sem** `_specific`), diferente de
  `price-tables`.
- `end_date` obrigatório: `"2060-01-01"`.

## Variações (grade de variantes)

Usar quando o site do cliente tem seletor de cor/tamanho/voltagem/sabor/
volume na página de produto — o eixo é uma **escolha do comprador sobre o
mesmo produto**. Não usar quando o "eixo" é na verdade outro produto (peça
por aplicação, medida com código próprio). Na dúvida, sem grade.

Dosagem: 2 a 4 produtos com grade por POC, no máximo 2 eixos por produto,
grade completa (produto cartesiano dos eixos); acima de ~24 variantes por
produto o painel fica pesado.

Dois níveis, ambos em `Criar Portais/template_variacoes.json`:

**1) Etapa `variations` (antes de `products`)** — cria os eixos:

```json
{"nome": "3. VARIACOES", "endpoint": "variations", "requests": [
  {"label": "Criar Variacao: Tamanho", "salvar_id_como": "variation_tamanho_id",
   "payload": {"name": "Tamanho", "active": true, "values": ["P","M","G","GG"]}}]}
```

O eixo **Cor** é especial: usa `display_type: "COLOR"` e
`variant_options: [{name, display_value}]` com `display_value` em hex
`#RRGGBB` — é o que mostra a bolinha colorida na loja. **Copie o bloco
`variacao_cor` inteiro do template** (paleta de 27 cores com hex padrão) e use
nos produtos só os nomes necessários; sobra de cor no eixo não atrapalha.
Eixos que não são cor vão **sem** `display_type` e **sem** `variant_options`.

**2) Array `variations` dentro do `payload` do produto** — as variantes:

```json
"variations": [{
  "sku": "SKU-001-BRA-P", "price": 219.90, "stock": 100, "images": [],
  "variation_weight": 0.3, "variation_width": 30.0,
  "variation_height": 4.0, "variation_depth": 22.0,
  "packaging_weight": 0.35, "packaging_width": 32.0,
  "packaging_height": 5.0, "packaging_depth": 24.0,
  "values": [
    {"variation_id": "{{variation_cor_id}}", "name": "Cor", "value": "Branco"},
    {"variation_id": "{{variation_tamanho_id}}", "name": "Tamanho", "value": "P"}]}]
```

Regras: `name` do value igual ao `name` do eixo; `value` existente no
`values[]` do eixo; `images` da variante sempre `[]`; SKU único por variante e
distinto do pai (derivado dele: `SKU-001-BRA-P`).

## Erros conhecidos da API (e como o formato os evita)

| Erro | Causa | Solução |
|---|---|---|
| 500 NPE `LocalDate` | `end_date` ausente | sempre `"2060-01-01"` |
| 500 NPE em produto | URL em `payload.images` | usar `temp_image_url` no request |
| 400 `HttpMessageNotReadable` em TP | `discount_percentage` / profiles como inteiros | desconto em `criteria[0].value`; profiles como objetos |
| 404 categoria `{{cat_ids_0}}` | `salvar_id_como` com colchetes | usar underscore (`cat_ids_0`) |
| 404 em `units` | tentar criar unidade de medida | não criar; `standard_unit_id: 2` |
| TP fica sem critério ao apagar um desconto | desconto e TP compartilhavam critério (cascata) | desconto usa `criteria_cat_<slug>_id` próprio |
| Cor aparece como texto, sem swatch | falta `display_type: "COLOR"` + `variant_options[].display_value` | copiar `variacao_cor` do template |
| Produto sem grade apesar do JSON ter `variations` | etapa `variations` depois de `products`, ou `value` fora do eixo | etapa antes de `products`; rodar `validar_poc.py` |

## Exemplos nesta pasta

- `exemplos/benenutri_poc.json` — POC completa **sem** variações.
- `exemplos/studiodasfestas_poc.json` — POC completa **com** grade de
  variações (eixo Cor com swatch).

Ambos validam com 0 erros no `validar_poc.py` desta pasta.
