# Prompt — agente do Mitra: aplicação de POCs para executivos, de ponta a ponta

Você vai construir e operar, neste projeto Mitra, a aplicação que os executivos
comerciais da Zydon usam para criar um portal de POC. Quem pediu é o João Pedro
(pré-vendas). Fale com ele em português.

Tudo roda do seu lado: coleta dos produtos, banners, curadoria, criação do
portal na API da Zydon, link de volta e relatórios. Não há mais máquina local
nem túnel no fluxo.

## O código que já existe

Repositório público, com o fluxo inteiro já funcionando em Python:
https://github.com/mutsdev/zydon-criar-pocs

Clone e **reaproveite**. Não reescreva o que já funciona: a coleta, o gerador de
banners e o runner da Zydon carregam correções de incidentes reais. Leia antes,
nesta ordem:

1. `README.md` e `CLAUDE.md` — o que o projeto é.
2. `ENTREGA.md` — o contrato do fluxo: fases, formatos, erros, ciclo de banner.
3. `ESTRUTURA-JSON.md` e `skills/criar-pocs/SKILL.md` — o formato do catálogo
   (`etapas[]`).
4. `POC Completa/receptor.py` e `POC Completa/extracao.py` — o orquestrador
   atual (extração, prévia, criação, banner). É o fluxo que você vai trazer
   para o Mitra.
5. `Identidade Visual/README.md` e `PRODUCT.md` — geração e validação dos
   banners.

Ignore `ROTINA.md` (routine que não existe mais) e as partes de túnel
(`tunel.py`, `endereco-receptor.json`): eram para expor a máquina do João Pedro.

## Credenciais

As variáveis estão nomeadas no `.env.example` do repositório. **O João Pedro
cadastra os valores direto no cofre / variáveis seguras do Mitra.** Nunca peça
chave no chat, nunca grave em tabela, código, log ou commit. A chave da Zydon é
de escrita e cria portal em produção.

Use sempre a org `pocs`, que é a de demonstração.

## O fluxo que o executivo vive

1. **Pedido.** Escolhe o próprio nome numa lista, informa nome do cliente e
   site. Segmento e anexo (catálogo em PDF/planilha) são opcionais.
2. **Extração.** Gere um `pedido_id` (`mitra-AAAA-MM-DD-NNN`). Colete os
   produtos (site primeiro; busca na web quando o site não tem catálogo), ache
   a logo e monte o catálogo. Rode o `validar_poc.py`: só segue com 0 erros.
   Em paralelo, assim que houver logo, gere a prévia dos banners.
3. **Curadoria.** Tela com os produtos (nome, imagem, preço, categoria) e os
   banners. O executivo remove ou edita produtos. **Destaque quando o preço for
   `estimado` ou `ausente`**: preço inventado na frente do cliente é o pior
   erro possível.
4. **Criação.** Ao aprovar, crie o portal com o catálogo inteiro (`etapas[]`,
   sem reformatar — formato diferente cria portal com zero produtos e sem erro).
5. **Banners.** Por peça (`login`, `cabecalho`): gerar outra, aplicar, ou
   seguir sem banner. Aplicar é conferido por GET.
6. **Fim.** O executivo vê o **link do portal**, clicável, e o pedido fica no
   histórico dele.

## Regras que vieram de incidentes — não quebre

- **2xx não prova nada.** A Zydon já respondeu 200 sem trocar a logo. Confira o
  efeito com um GET.
- **Idempotência pelo `pedido_id`.** Clique duplo ou retry nunca cria segundo
  portal (incidente Disflex, 11/09/2026: três portais para um pedido). Um
  portal sendo criado por vez.
- **Banner ruim não sobe.** A régua em `Identidade Visual/regua.json` e o
  `juiz.py` decidem; o fallback garante peça apresentável. A marca é sempre a
  do cliente, nunca a da Zydon.
- **`preco` no resumo** é `publico`, `estimado` ou `ausente`, e tem que bater
  com o catálogo.

## Dados e relatórios

Tabelas mínimas:

- **executivos**: lista fixa de nomes, ativa/inativa. O executivo **escolhe**,
  não digita — "João" e "joao" não podem virar duas pessoas. O João Pedro
  mantém a lista.
- **pedidos**: `pedido_id`, executivo, cliente, site, segmento (informado ou
  inferido, marcado qual), status (`extraindo`, `curadoria`, `criando`,
  `concluido`, `falhou`), data de cada etapa, produtos, categorias, `fonte`,
  `preco`, `portal_id`, link do portal, banners aplicados ou dispensados,
  observações e erro.

Relatórios, com filtros por **executivo, segmento, período e status**:

- portais criados por executivo e por período;
- distribuição por segmento;
- taxa de sucesso e falhas com o motivo;
- tempo médio do pedido até o link;
- média de produtos por portal, fonte do catálogo e situação do preço;
- lista de portais com link, filtrável.

Cada executivo vê por padrão os próprios pedidos; o João Pedro vê todos.

## Como provar que terminou

Um pedido real de ponta a ponta na org `pocs`: executivo escolhe o nome,
informa cliente e site, vê produtos e banners, aprova, aplica um banner
(conferido por GET) e recebe o link do portal abrindo. O pedido aparece nos
relatórios com o filtro do executivo. Mande ao João Pedro o link do portal de
teste e a lista do que ficou de fora e por quê.
