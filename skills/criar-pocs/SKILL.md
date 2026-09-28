---
name: criar-pocs
description: Monta o JSON declarativo de uma POC de portal B2B Zydon a partir do site do cliente — coleta de produtos e imagens, regras de negócio (categorias, tabelas de preço, descontos, grade de variações) e ciclo de validação. Use quando o usuário mandar o site de uma empresa para criar uma POC, ou pedir para montar/corrigir um {empresa}_poc.json.
---

# Criar POC de portal Zydon

Entrega: `Arquivos Json/{empresa}_poc.json` que passa no `validar_poc.py` com
**0 erros**, e em seguida a POC criada na API (passo 6) — **só na máquina com
credencial** (existe `.env` na raiz com `ZYDON_POCS_TOKEN`). Sem `.env` (rotina
na nuvem, `ROTINA.md`), a entrega para no JSON validado: não execute nem tente
obter credencial. Naming: `{empresa}_poc.json` (nunca `poc_{empresa}.json`).

Fonte da estrutura: **`Criar Portais/template_poc.json`** — copiar e adaptar,
nunca recriar. Grade: `Criar Portais/template_variacoes.json`. Formato:
`ESTRUTURA-JSON.md`. Na dúvida, o `validar_poc.py` decide — **não leia o
validador nem POCs antigas**; rode e corrija.

Tarefa mecânica: em subagente, rode em **Sonnet** (`model: sonnet`).

## Fluxo — 7 passos, nesta ordem

1. **Coletar** (uma ida):
   ```
   python "Criar Portais/coletar_site.py" https://site.do.cliente/ --saida "<scratch>/coleta.json"
   ```
   Detecta Shopify / WooCommerce (centavos já convertidos) / VTEX / sitemap
   (Irroba, Loja Virtual, Wix…) / imagens da home, e devolve nome, preço,
   categoria, imagem e variantes por item. Leia esse arquivo e escolha.
   Só abra Playwright se ele voltar `nenhuma` ou vazio (site JS-rendered);
   aí uma aba nova, e feche ao terminar. **Ramo real sai do site, nunca do
   nome.** Site institucional + "loja online" em outro domínio: colete da loja.
2. **Escolher 5–12 produtos** cobrindo **3 categorias** (ver regras). Foto do
   próprio site: pode ir a 12. Foto caçada fora: fique perto de 5.
   Sem foto no site → catálogo VTEX público de varejista do setor
   (`/api/catalog_system/pub/products/search?ft=<codigo>`) → Mercado Livre por
   último e uma tentativa só (`lista.mercadolivre.com.br/NOME`, `-E.webp` /
   `-V.webp`; nunca `-OO`/`-A`). CDN que serve `application/octet-stream`
   reprova: troque de fonte.
3. **Olhar as imagens num mosaico só** e trocar as erradas:
   ```
   python "Criar Portais/mosaico_imagens.py" --urls <u1> <u2> ... --rotulos <r1> <r2> ...
   ```
   Sai em `Identidade Visual/saidas/mosaico.png`. Abra uma vez, decida todas.
4. **Montar o JSON** — o script escreve, você só decide:
   ```
   python "Criar Portais/montar_poc.py" --coleta "<scratch>/coleta.json" \
       --empresa "Nome" --setor "Setor — Sub" --descricao "Uma frase do site" \
       --cats "Cat A;Cat B;Cat C" --itens "3:0,7:0,12:1,15:1,18:2,22:2" \
       --core 4 [--grade "15:Tamanho=P,M,G"]
   ```
   `--itens` = `idx:cat[:Nome[:preco]]` — índice na coleta, índice da
   categoria; Nome e preço só quando a coleta veio sem (landing sem `alt`,
   site sem preço público — aí você estima um preço plausível por item, nunca
   deixe todos iguais). `--core` = perfil com maior desconto (2 Indústria,
   3 Distribuidor, 4 Varejo). Preço ausente na coleta fica marcado
   `_preco_estimado: true` no request. Se a coleta voltar `plataforma: home`
   (imagens cruas, sem nome), o mosaico é quem nomeia: rótulo = índice.
   `lojas_externas` na coleta (ex.: loja no Mercado Livre) é fonte de preço
   se precisar. Ele já roda o
   validador; depois:
   ```
   python "Criar Portais/verificar_imagens.py" "Arquivos Json/{empresa}_poc.json"
   ```
   Até 100% das imagens OK e 0 erros. Só edite o JSON à mão para descrição
   comercial melhor ou item que a coleta não trouxe.
5. **Achar a logo**: `python "Identidade Visual/achar_logo.py" <site> --json`
   (`--extra url…` se voltar vazio). Wix: tire o `/v1/fill/...` da URL para
   pegar o original. **Olhe a escolhida** — ele já pegou logo do grupo
   controlador em vez da do cliente. Salve em `Identidade Visual/<empresa>_logo.png`.
6. **Executar** — só com JSON em 0 erros, 100% das imagens OK e `.env`
   presente:
   ```
   PYTHONIOENCODING=utf-8 python "POC Completa/criar_poc_completo.py" \
       "Arquivos Json/{empresa}_poc.json" pocs \
       --logo "Identidade Visual/{empresa}_logo.png" --nome "Empresa" --gravar
   ```
   Falha na API tem rollback automático: leia o erro, corrija o JSON,
   revalide e rode de novo. Sem logo aprovada, não execute: pare e pergunte.
   Esse script sobe logo, favicon e cor — **não sobe banner**. Emende o 6b.
6b. **Banners** (login + cabeçalho):
   ```
   python "Identidade Visual/gerar_banners.py" auto --logo <logo> --nome "Empresa" \
       --segmento "<setor>" --catalogo "Arquivos Json/{empresa}_poc.json"
   ```
   Abra `aprovados/` e olhe — o juiz aprova ferramenta usada/suja, objeto
   derretido e texto desenhado. Destaque derivado (`origem_destaque:
   derivado` no `contexto.json`) sai em cor fora da marca: troque por
   `#FFFFFF` em `paleta.json` e `contexto.json` e rode `montar <pasta>`.
   Cena ruim: `regerar <pasta> --formatos login,cabecalho --feedback
   "login=..."`, mova as reprovadas de `cenas/` e `montar`. Crítica
   obrigatória (`/impeccable critique`) antes de subir:
   ```
   python "Identidade Visual/subir_banners.py" --portal <portal_id> \
       --pasta "Identidade Visual/saidas/<empresa>/<carimbo>" --gravar
   ```
7. **Entregar**: URL do portal, nº de produtos, preços públicos ou
   **estimados** (dizer explicitamente), avisos da identidade (favicon por
   inicial etc.), pendências. Nada movido.

Alvo: menos de 5 min por POC. Quem manda no tempo é o número de idas: junte
buscas num comando (`xargs -P`, laço), nunca uma página por chamada.

## Instagram (cliente sem site)

Não precisa de login nem Playwright para a imagem:
`https://www.instagram.com/p/<code>/embed/captioned/` serve `img.EmbeddedMediaImage`
e a legenda via curl. Use Playwright só para listar os códigos dos posts do
perfil. Foto de perfil vem em 150px (pequena para o pipeline, mínimo 200 no
menor lado): recorte a logo de um post limpo. URLs do CDN expiram em semanas —
rodar o lote logo. Segmento pelo que os posts mostram, nunca pelo nome.

## Regras que o template não expressa sozinho

### Produtos
- `sku` obrigatório e único; `standard_unit_id: 2`; `stock: 100`;
  `minimum_stock: 0`; `active: true`; `images: []` sempre.
- `temp_image_url` **no nível do request** (fora do payload), em todo produto.
  URL em `payload.images` causa 500.
- `price` em **reais decimais** (`219.90`) — nunca centavos. Store API do
  WooCommerce devolve centavos (o `coletar_site.py` já divide).
- `minimum_for_sale`/`multiple_for_sale` variados e coerentes com a
  embalagem; ~30% em 1/1; `multiple >= minimum`.
- `highlight: true` só nos principais.

### Critérios — um por finalidade, nunca compartilhado
- `criteria_preco_id` — marca (`config.brands`, `this.CODIGOMARCA`) → tabelas;
- `criteria_listagem_id` — marca → `portal_listing_rule_id`;
- `criteria_cat_<slug>_id` — categoria (`config.categories`,
  `this.CODCATEGORIA` = `{{cat_ids_N}}`), um por categoria com desconto.
  `salvar_id_como` sem colchetes (`cat_ids_0`).

### Descontos — sempre por categoria
Cada um com seu `criteria_cat_<slug>_id`. Mínimo 1 progressivo
(`is_profile: true`, 1 segmento) + 1 fixo (`is_profile: false`,
`minimum_quantity: 0`). Endpoint `discounts` usa `is_profile`/`is_partner`
(sem `_specific`).

### Tabelas de preço
Perfis são **tipos de comprador**, iguais em toda POC: `2` Indústria, `3`
Distribuidor, `4` Varejo — sempre 3 TPs, nomes "Tabela 1/2/3 | Empresa".
Desconto em `criteria[0].value` (nunca `discount_percentage`), `profiles`
como `{"profile_id": "N"}`, `end_date: "2060-01-01"`. Maior desconto no perfil
mais aderente ao core do cliente; spread agressivo, ≥15 pontos entre menor e
maior (5/15/30 ✅, 8/10/12 ❌).

### Variações (opcional — decida no passo 1)
Grade quando o eixo é escolha do comprador sobre o MESMO produto (cor,
tamanho, voltagem, sabor, volume). Não é grade quando o "eixo" é outro produto
(peça por aplicação, código de fabricante). Na dúvida, sem grade.
2–4 produtos com grade, máx. 2 eixos, grade completa, até ~24 variantes.
Etapa `variations` **antes** de `products` (renumerar as seguintes); array
`variations` no payload com SKU derivado (`KRI-CAM-001-BRA-P`), `price`,
`stock`, `images: []`, dimensões e `values` com `{{variation_*_id}}`.
Eixo Cor: copiar o bloco `variacao_cor` inteiro (hex + `display_type: "COLOR"`).

## Erros conhecidos da API

| Erro | Causa | Solução |
|---|---|---|
| 500 NPE `LocalDate` | `end_date` ausente | `"2060-01-01"` |
| 500 NPE em produto | URL em `images[]` | `temp_image_url` |
| 400 em TP | `discount_percentage` / profiles inteiros | `criteria[0].value`; profiles objetos |
| 404 categoria | `salvar_id_como` com colchetes | `cat_ids_0` |
| 404 em `units` | tentar criar unidade | `standard_unit_id: 2` |
| TP sem critério ao apagar desconto | critério compartilhado | `criteria_cat_<slug>_id` próprio |
| Cor sem swatch | falta `display_type`/`variant_options` | copiar `variacao_cor` |
| Grade não aparece | `variations` depois de `products` | etapa antes; validar |

Exemplos que validam: `exemplos/benenutri_poc.json` (sem grade),
`exemplos/studiodasfestas_poc.json` (com grade de cor).
