# Prompt — agente de ponta a ponta das POCs para executivos

Você vai assumir, de ponta a ponta, o fluxo que cria portais de POC na Zydon
para os executivos comerciais. O código já existe e funciona em boa parte; o
seu trabalho é fechar o fluxo inteiro, acrescentar a identificação do executivo
e os relatórios, e deixar tudo testado e documentado.

Quem te pediu é o João Pedro (pré-vendas da Zydon). Fale com ele em português.

## O resultado que ele quer

O executivo informa **o nome dele, o nome do cliente e o site**. Sem mais
nenhuma intervenção técnica, o sistema:

1. busca na internet os produtos do cliente (site dele primeiro; busca na web
   quando o site não tem catálogo);
2. gera os banners de identidade visual a partir da logo;
3. leva o executivo pela curadoria (produtos e banners) até ele aprovar;
4. sobe o JSON para a API da Zydon e cria o portal;
5. devolve o **link do portal**.

Além disso:

- todo pedido carrega o **nome do executivo**, gravado e consultável;
- existem **filtros por executivo** e **relatórios gerais**: portais criados por
  período, por executivo, por segmento, status (concluído / falhou / em
  curadoria), tempo de criação, quantidade de produtos, fonte do catálogo
  (site / pdf / planilha / busca) e situação do preço (público / estimado /
  ausente).

## Onde está o projeto

Repositório: `C:\Users\joaop\OneDrive\Códigos\zydon-criar-pocs` (git, remoto no
GitHub). Leia nesta ordem antes de mudar qualquer coisa:

1. `CLAUDE.md` e `README.md` — o que o projeto é e as regras da sessão.
2. `ENTREGA.md` — **fonte da verdade do contrato com o Mitra** (rotas, callbacks,
   formatos, erros). Mudança de contrato vira commit neste arquivo.
3. `ESTRUTURA-JSON.md` e `skills/criar-pocs/SKILL.md` — o formato do JSON da POC.
4. `POC Completa/README.md` e `POC Completa/receptor.py` — o servidor que recebe
   os pedidos.
5. `Identidade Visual/README.md` e `PRODUCT.md` — geração e validação de banners.
6. `ROTINA.md` — **histórico**. A routine do Claude Code na web descrita ali
   **não existe mais** (desde 10/09/2026). Não tente recriá-la.

## Como o fluxo funciona hoje

A interface do executivo é o **Mitra** (plataforma low-code, `newmitra.mitrasheet.com`).
A execução é **local, na máquina do João Pedro**, onde estão as credenciais:

- `POC Completa/receptor.py --gravar` escuta em `127.0.0.1:8787`.
- `POC Completa/tunel.py` sobe um `cloudflared` com endereço efêmero, confere
  `/saude` pelo túnel e publica o endereço em `endereco-receptor.json` (commit +
  push). O Mitra lê esse arquivo antes de cada POST.

Rotas do receptor (todas com `X-Token`):

| rota | o que faz |
|---|---|
| `POST /extracao` | recebe `{pedido_id, cliente, site, anexos?, segmento?, callback_url?, callback_token?}`, responde 202, monta o catálogo (`extracao.py`, `Criar Portais/coletar_site.py`, `montar_poc.py`), valida com `validar_poc.py` e devolve o `catalogo` inteiro no callback SF3 |
| `POST /previa` | gera a arte do banner só com a logo, em paralelo com os produtos; 202 e resultado no callback |
| `POST /pedido` | recebe o catálogo curado, cria o portal (`criar_poc_completo.py`), devolve `{pedido_id, portal_id, url}` e os banners em `fase: curadoria` |
| `POST /banner` | `regerar` (por peça), `aplicar` (por `file_id`), `dispensar` |
| `GET /saude` | estado das filas |

Registros em disco: `pedidos-atendidos.jsonl` (idempotência da extração),
`pedidos-executados.jsonl` (criação e banners), `logs/tempos.jsonl` (tempo por
etapa, via `cronometro.py`). `relatorio_pocs.py` já gera um relatório de custo
(tempo e tokens) em `relatorios/pocs.md`.

## O que falta — o seu escopo

1. **Nome do executivo.** Campo `executivo` obrigatório em `/extracao` e
   `/pedido`. Recuse sem ele, com erro no mesmo formato das outras rotas
   (`{"ok": false, "erro": "CAMPOS_FALTANDO", ...}`). Grave o campo nos registros
   e no `resumo.json`. Registros antigos sem o campo aparecem como
   `"não informado"` nos relatórios; não reescreva o histórico.
2. **Segmento sempre preenchido.** Hoje é opcional no pedido. Quando o executivo
   não mandar, infira (já existe `Identidade Visual/segmento.py` e
   `cache_segmentos.json`) e grave o valor inferido, marcado como inferido.
3. **Relatórios e filtros.** Estenda `relatorio_pocs.py` em vez de criar outro
   script. Ele deve cruzar os registros acima e responder: por executivo, por
   segmento, por período, por status, com os indicadores da seção anterior.
   Exponha o resultado também por uma rota `GET /relatorio` no receptor (com
   `X-Token`, filtros por query string: `executivo`, `segmento`, `desde`,
   `ate`, `status`), para o Mitra montar a tela.
4. **Fluxo completo sem buracos.** Confira, com um cliente real na org `pocs`,
   que um pedido sai de `/extracao` e chega no link do portal, passando por
   `/previa`, `/pedido` e `/banner`. Tudo que quebrar no caminho é seu.
5. **Documentação.** Atualize `ENTREGA.md` com os campos e a rota novos, e
   marque `ROTINA.md` como histórico no topo.

A tela do Mitra é feita do lado do Mitra. Você entrega o contrato
(`ENTREGA.md`) e as rotas; não presuma acesso ao Mitra.

## Regras que não se quebram

- **2xx não prova nada.** A Zydon já respondeu 200 sem trocar a logo, e o Mitra
  responde 2xx até quando rejeita. Confira o efeito com um GET ou lendo o corpo.
- **Idempotência pelo `pedido_id`.** O Mitra reenvia; reenvio nunca pode criar
  segundo portal (incidente Disflex, 11/09/2026 — veja o código de `/pedido`).
- **Um portal por vez**, numa fila. Não paralelize a criação.
- **Receptor só em `127.0.0.1`.** Quem expõe é o túnel.
- **Credenciais só no `.env`** (o `atendimento.py` diz onde ele mora). Nunca em
  código, log, commit ou chat. Chave de escrita cria coisa em produção.
- **O catálogo vai inteiro**, com `etapas[]`. Formato diferente entra com zero
  produtos e sem erro.
- **Preço estimado nunca passa despercebido.** `preco` no resumo é
  `publico`, `estimado` ou `ausente`, e tem que bater com o catálogo.
- **Banner ruim não sobe.** Rode `/impeccable critique "Identidade Visual/saidas/<cliente>"`
  antes de publicar peça. A marca é sempre a do cliente, nunca a da Zydon.
- **A árvore tem mudanças sem commit do João Pedro.** Não descarte, não
  reverta, não faça `git add -A`. Commite só o que você mudou, em commits
  pequenos.
- Não crie Artifacts do claude.ai: o João Pedro não consegue abri-los. Entregue
  em arquivo local ou no terminal.

## Decisões que são dele — pergunte antes

Use `AskUserQuestion` com três opções quando travar numa destas; não escolha
sozinho:

1. **Onde o executivo vê os relatórios**: tela no Mitra consumindo
   `GET /relatorio`, página local servida pelo receptor, ou ambos.
2. **Como o executivo se identifica**: texto livre, lista fixa de nomes, ou
   e-mail. Lista fixa evita "João" e "joao" virarem duas pessoas.
3. Qualquer mudança que quebre o contrato atual com o Mitra.

## Como provar que terminou

- `pytest tests/` passa, com testes novos para: recusa sem `executivo`,
  gravação do campo, filtros do relatório e registro antigo sem executivo.
- Um pedido real, feito com `--simular` e depois com `--gravar` na org `pocs`,
  sai de `/extracao` e termina com a URL do portal abrindo, banner aplicado
  conferido por GET, e aparecendo no `GET /relatorio` filtrado pelo executivo.
- `ENTREGA.md` descreve exatamente o que o código faz.

Ao terminar, mande ao João Pedro: o link do portal de teste, o relatório
gerado, a lista de commits e o que ficou de fora e por quê.
