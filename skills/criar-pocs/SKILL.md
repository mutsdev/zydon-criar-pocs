---
name: criar-pocs
description: Monta o JSON declarativo de uma POC de portal B2B Zydon a partir do site do cliente — coleta de produtos e imagens, regras de negócio (categorias, tabelas de preço, descontos, grade de variações) e ciclo de validação. Use quando o usuário mandar o site de uma empresa para criar uma POC, ou pedir para montar/corrigir um {empresa}_poc.json.
---

# Criar POC de portal Zydon

Você monta o **JSON declarativo** que o `criar_poc.py` executa contra a API da
Zydon. Sua entrega é um `{empresa}_poc.json` salvo em `Arquivos Json/` que
passa no `validar_poc.py` com **0 erros**. Quem executa contra a API é o
usuário, em lote (`executar_lote.py`) — **você não entrega comando de
execução**, só avisa que a POC está pronta para o próximo lote.

Fonte da verdade da estrutura: **`Criar Portais/template_poc.json`** — copiar
e adaptar, NUNCA recriar do zero. Grade de variações: bloco pronto em
**`Criar Portais/template_variacoes.json`**. Formato documentado em
**`ESTRUTURA-JSON.md`** (na raiz desta pasta); o que estiver em dúvida, o
`validar_poc.py` decide.

## Fluxo (nesta ordem)

**Gatilho: o usuário manda o site da empresa.** Daí você faz tudo sozinho:

1. **Visitar o site** (navegador) — nunca inferir setor/segmento pelo nome da
   empresa. Coletar: ramo real, **9 a 15 produtos** (máximo 15), **3
   categorias** e as **URLs das imagens de produto do próprio site** (extrair
   o `src` enquanto navega; se renderizam na página, são válidas). No mesmo
   passo, decidir se a POC pede **grade de variações** (ver abaixo) — o sinal
   é seletor de cor/tamanho/voltagem/sabor/volume na página de produto.
2. **Completar as imagens que faltaram ANTES de entregar** — TODO produto
   deve ter `temp_image_url`. Ordem de preferência: site da marca → Mercado
   Livre (`https://lista.mercadolivre.com.br/NOME-DO-PRODUTO`, pegar URLs
   `-E.webp` dos cards ou `-V.webp` das thumbs; nunca `-OO.webp`/`-A.webp`,
   que são banners).
3. **Copiar `template_poc.json` → `{empresa}_poc.json`** e preencher, com
   todas as imagens inline via `temp_image_url`.
4. **Validar**: `python "Criar Portais/validar_poc.py" "Arquivos Json/{empresa}_poc.json"`
   — corrigir até **0 erros**. O lote não executa POC que não valida: ela
   fica parada e volta para você. Entregar sem validar só adia o erro.
5. **Entregar**: JSON salvo em `Arquivos Json/`, avisar que está pronto.
   **Não mover arquivos, não inventar pasta "rodados", sem comando de
   execução.** O estado "já rodou" é a existência de
   `Arquivos Json/saidas/{base}_ids.json`, gerada pelo runner.

## Naming — obrigatório

`{empresa}_poc.json` (ex.: `florese_poc.json`). **Nunca** `poc_{empresa}.json`
(padrão antigo, o validador bloqueia).

## Coletar do site: procure a API antes de ler a página

**Se o site for WordPress, teste a Store API do WooCommerce antes de raspar
HTML:**

```
GET https://<site>/wp-json/wc/store/v1/products?per_page=100
```

Ela é pública e devolve o catálogo estruturado — nome, descrição, preço,
categoria e imagem — sem depender de como a página foi marcada. Na Aroca
Mercearia (27/08/2026) trouxe os 38 produtos de uma vez. Vale o teste sempre:
muito cliente B2B roda WooCommerce.

**A armadilha: a Store API devolve preço em CENTAVOS.** Confira
`prices.currency_minor_unit` (vale `2`) e divida por 100 antes de escrever no
JSON. O balde de Petit Fromage chega como `24600` e vale R$ 246,00. O validador
tenta pegar isso pela mediana dos preços, mas **a mediana não dispara quando o
catálogo tem muito item barato** — foi o caso ali. Converta na origem; não
conte com a rede de proteção.

Se o preço não for público — o caso mais comum em B2B — diga isso
explicitamente na entrega, em vez de estimar em silêncio.

## Regras que o template não expressa sozinho

### Produtos (9–15, nunca mais de 15)
- `sku` obrigatório e único; `standard_unit_id: 2`; `stock: 100`;
  `minimum_stock: 0`; `active: true`; `images: []` sempre.
- `price` em **reais decimais** (`219.90` = R$ 219,90) — **NUNCA centavos**.
  O runner não converte: o valor vai direto para a API.
- `minimum_for_sale`/`multiple_for_sale` **variados** entre produtos e
  coerentes com a embalagem; ~30% podem ser 1/1; sempre `multiple >= minimum`;
  consumíveis podem ter múltiplo alto (50/100).
- `highlight: true` só nos principais.

### Critérios — sempre separados por finalidade
Nunca compartilhar critério entre finalidades: apagar uma entidade apaga o
critério vinculado e deixa as outras sem filtro (efeito cascata). Um critério
por finalidade:
- `criteria_preco_id` — por **marca** (`config.brands`,
  `this.CODIGOMARCA` = `{{brand_id}}`) → tabelas de preço;
- `criteria_listagem_id` — por **marca** → `portal_listing_rule_id`;
- `criteria_cat_<slug>_id` — por **categoria** (`config.categories`,
  `this.CODCATEGORIA` = `{{cat_ids_N}}`), um por categoria com desconto →
  usados exclusivamente pelos descontos.

### Descontos — sempre por categoria
Cada desconto referencia um `criteria_cat_<slug>_id` próprio — **nunca**
`criteria_preco_id`/`criteria_listagem_id`. Pelo menos 1 progressivo
(`is_profile: true`, 1 segmento) + 1 fixo (`is_profile: false`). O fixo
começa em `minimum_quantity: 0` (nunca 1). Atenção: o endpoint `discounts`
usa `is_profile`/`is_partner`/… (**sem** `_specific`), diferente de
`price-tables`.

### Tabelas de preço

**Os perfis são tipos de COMPRADOR, não segmentos do cliente.** Na org de POC:
`2` = Indústria/Manufatura, `3` = Distribuidor, `4` = Varejo — uma tabela para
cada, e é isso que o validador exige. Não procure um perfil "do ramo do
cliente": ele não existe, e uma mercearia fina vende para varejo e distribuidor
como qualquer outra empresa. Perfis são **por organização**, como `database_id`
e `portal_origem_id`; listar numa org nova:
`GET /api/sales/profiles?perPage=100`.

Sempre **3 TPs, segmentos 2, 3 e 4**, nomeadas "Tabela 1/2/3 | Empresa" (sem
nome de segmento). Desconto em `criteria[0].value` — **nunca**
`discount_percentage` ou `minimum_order_value` (400). `profiles` sempre
objetos `{"profile_id": "N"}`. O segmento mais aderente ao core da empresa
recebe o maior desconto, e o spread é **agressivo**: valores distintos com
diferença ≥ 15 pontos entre menor e maior (5/15/30 ✅, 8/10/12 ❌).

Segmentos da org pocs: 2 Material de Construção · 3 Indústria/Manufatura ·
4 Suprimentos Industriais · 5 Autopeças · 6 Saúde · 7 Agronegócio ·
8 Alimentos · 9 Equipamentos · 10 Embalagens · 11 Tecnologia.

### Variações (etapa opcional — você decide sozinho, no passo 1)
**Usar grade quando** o eixo é uma escolha do comprador sobre o MESMO produto
(cor, tamanho, voltagem, sabor, volume, medida de confecção). **Não usar**
quando o "eixo" é outro produto: peça por aplicação, SKU de fabricante,
medida com código próprio. Na dúvida, **sem grade**.

Dosagem: 2–4 produtos com grade por POC, máximo 2 eixos, grade completa
(produto cartesiano); acima de ~24 variantes por produto o painel pesa.

Estrutura em dois níveis (copiar de `template_variacoes.json`):
1. Etapa `variations` **antes** de `products` (renumerar os `nome` das
   etapas seguintes) — cria os eixos com `salvar_id_como: variation_<slug>_id`;
2. Array `variations` dentro do `payload` de cada produto com grade — cada
   variante com SKU próprio derivado do pai (`KRI-CAM-001-BRA-P`), `price`,
   `stock`, `images: []`, dimensões, e `values` referenciando
   `{{variation_*_id}}` com `name` igual ao do eixo e `value` existente no
   `values[]` do eixo.

**Eixo Cor**: copiar o bloco `variacao_cor` **inteiro** do template (27 cores
com hex) — `display_type: "COLOR"` + `variant_options[].display_value` em
`#RRGGBB` é o que faz o swatch aparecer. Não inventar paleta nova; cor que
faltar, acrescentar ao template (nome + hex). Eixos que não são cor vão sem
`display_type` e sem `variant_options`.

### Imagens
URL em `temp_image_url` **no nível do request** (fora do payload);
`payload.images` sempre `[]` — URL direta em `images` causa 500 NPE.

## Erros conhecidos da API

| Erro | Causa | Solução |
|---|---|---|
| 500 NPE `LocalDate` | `end_date` ausente | sempre `"2060-01-01"` |
| 500 NPE em produto | URL em `images[]` | usar `temp_image_url` |
| 400 em TP | `discount_percentage` / profiles inteiros | desconto em `criteria[0].value`; profiles objetos |
| 404 categoria | `salvar_id_como` com colchetes | underscore: `cat_ids_0` |
| 404 em `units` | tentar criar unidade | não criar; `standard_unit_id: 2` |
| TP sem critério ao apagar desconto | critério compartilhado (cascata) | desconto com `criteria_cat_<slug>_id` próprio |
| Cor sem swatch | falta `display_type`/`variant_options` | copiar `variacao_cor` do template |
| Grade não aparece | etapa `variations` depois de `products` | etapa antes; rodar o validador |

## Pré-entrega

`python "Criar Portais/validar_poc.py" "Arquivos Json/{empresa}_poc.json"` →
**0 erros**. JSON salvo em `Arquivos Json/`, nada movido, nenhum comando de
execução entregue. Só isso.

Exemplos de referência que validam: `exemplos/benenutri_poc.json` (sem
variações) e `exemplos/studiodasfestas_poc.json` (com grade de cor).
