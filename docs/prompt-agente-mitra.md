# Prompt — agente do Mitra: aplicação de POCs para executivos

Você vai construir, neste projeto Mitra, a aplicação que os executivos
comerciais da Zydon usam para pedir um portal de POC. Quem pediu é o João Pedro
(pré-vendas). Fale com ele em português.

## A divisão de trabalho

**O backend já existe e funciona. Você não vai reescrevê-lo.** Ele roda na
máquina do João Pedro (onde estão as credenciais da Zydon) e é exposto por um
túnel HTTPS. Ele coleta os produtos do site, gera os banners, cria o portal na
API da Zydon e devolve o link.

**O seu trabalho é o lado do Mitra:** telas, tabelas, as chamadas ao backend,
as funções que recebem os callbacks e os relatórios.

Código e contrato, público, para leitura:
https://github.com/mutsdev/zydon-criar-pocs

Leia antes de começar, nesta ordem:

1. `ENTREGA.md` — **o contrato completo**: rotas, corpos, callbacks, erros.
   https://raw.githubusercontent.com/mutsdev/zydon-criar-pocs/main/ENTREGA.md
2. `POC Completa/receptor.py` — o docstring do topo e as funções `extracao`,
   `previa`, `banner` e `do_POST` (rota `/pedido`).
3. `ESTRUTURA-JSON.md` — o formato do catálogo (`etapas[]`).

Ignore `ROTINA.md`: descreve uma routine que não existe mais.

## Onde o backend está

O endereço do túnel é **efêmero**. Ele fica publicado em:
https://raw.githubusercontent.com/mutsdev/zydon-criar-pocs/main/endereco-receptor.json

Leia esse arquivo **antes de cada chamada**. Nunca guarde a URL. Se a chamada
der erro de conexão, confira `GET <url>/saude`; se não responder, a mensagem
certa para o executivo é "o gerador de POCs está fora do ar, avise o João
Pedro", e não uma retentativa em loop.

Toda chamada leva o header `X-Token`. O valor é um segredo que o João Pedro
cadastra no cofre/variável segura do Mitra. **Não peça o token no chat e não o
grave em tabela, código ou log.**

## O fluxo que o executivo vive

1. **Pedido.** Ele escolhe o próprio nome, digita o nome do cliente e o site.
   Segmento é opcional. Anexo (catálogo em PDF/planilha) é opcional.
2. **Extração.** O Mitra gera um `pedido_id` (`mitra-AAAA-MM-DD-NNN`) e um
   `callback_token` novo **por pedido**, e chama `POST /extracao`. Resposta 202.
   Em paralelo, assim que houver logo, `POST /previa` para a arte aparecer junto
   com os produtos.
3. **Callback da extração.** Uma função do Mitra recebe `fase: "extracao"` com o
   `catalogo` inteiro, o `resumo` e a `logo_url`. Confira o `callback_token`
   contra o do pedido; se não bater, rejeite.
4. **Curadoria.** Tela com os produtos (nome, imagem, preço, categoria) e a
   prévia dos banners. O executivo remove ou edita produtos. **Destaque quando
   `resumo.preco` for `estimado` ou `ausente`**: preço inventado na frente do
   cliente é o pior erro possível.
5. **Criação.** Ao salvar, `POST /pedido` com o `catalogo` **inteiro, com
   `etapas[]`, sem reformatar**. Formato diferente cria portal com zero produtos
   e sem erro.
6. **Callback da criação.** Chega `{pedido_id, portal_id, url}` e, se houver,
   `fase: "curadoria"` com as peças `login` e `cabecalho`.
7. **Banners.** Por peça: "Gerar outra" (`POST /banner` `acao: regerar`,
   `pecas: [...]`), "Aplicar" (`acao: aplicar`, `escolhas` com o `file_id`),
   "Seguir sem banner" (`acao: dispensar`).
8. **Fim.** O executivo vê o **link do portal**, clicável, e o pedido fica no
   histórico dele.

## Regras que o contrato impõe

- **2xx não prova nada.** Leia o corpo. `ok: false` com status 200 é falha.
- **Idempotência pelo `pedido_id`.** Reenviar o mesmo pedido devolve
  `duplicado: true` com o resultado; nunca gere `pedido_id` novo num retry.
  Botão de enviar desabilita depois do primeiro clique.
- **Callback pode não chegar.** Pedido parado há mais de 2 horas sem callback
  aparece como "sem resposta" na tela, não como "em andamento" para sempre.
- **Erros do `/banner`** (`GRAVACAO_PELA_METADE`, `ZYDON_RECUSOU` etc.) vêm com
  `gravados` e `faltou`. Mostre ao executivo o que entrou e o que não entrou.

## Dados e relatórios (ficam no Mitra)

Tabelas mínimas:

- **executivos**: lista fixa de nomes, ativa/inativa. O executivo **escolhe**
  o nome, não digita — "João" e "joao" não podem virar duas pessoas. O João
  Pedro mantém essa lista.
- **pedidos**: `pedido_id`, executivo, cliente, site, segmento (informado ou
  o que veio do backend), status (`extraindo`, `curadoria`, `criando`,
  `concluido`, `falhou`, `sem_resposta`), datas de cada etapa, quantidade de
  produtos e categorias, `fonte`, `preco`, `portal_id`, `url` do portal,
  banners aplicados ou dispensados, observações e erro.

Guarde o `catalogo` só enquanto o pedido está em curadoria; depois basta o
resumo.

Relatórios, com filtros por **executivo, segmento, período e status**:

- portais criados por executivo e por período;
- distribuição por segmento;
- taxa de sucesso e falhas com o motivo;
- tempo médio do pedido até o link;
- média de produtos por portal, fonte do catálogo e situação do preço;
- lista de portais com link, filtrável.

Cada executivo vê por padrão os próprios pedidos; o João Pedro vê todos.

## O que não fazer

- Não reimplemente coleta, geração de banner nem chamada à API da Zydon no
  Mitra. Isso é do backend.
- Não peça credencial da Zydon. O Mitra nunca fala com a Zydon diretamente.
- Não mude o contrato. Se precisar de campo ou rota nova no backend, escreva o
  pedido para o João Pedro com o formato exato, e siga com o resto.

## Como provar que terminou

Com o backend no ar, um pedido real de ponta a ponta: executivo escolhe o
nome, informa cliente e site, vê produtos e prévia, aprova, aplica um banner e
recebe o link do portal abrindo. Depois, o pedido aparece nos relatórios com o
filtro do executivo dele. Mande ao João Pedro o link do portal de teste e a
lista do que ficou de fora.
