# Como a rotina entrega o resultado

Este arquivo é a **fonte da verdade da entrega**. O prompt da rotina aponta para
cá de propósito: mudança de contrato com o Mitra vira um commit, e não uma ida à
interface para recolar o prompt.

## O caminho normal: callback no Mitra

O pedido traz `callback_url` e `callback_token`. Quando o JSON estiver validado,
faça um POST no `callback_url` com este corpo:

```json
{"pedido_id": "...",
 "callback_token": "...",
 "status": "concluido",
 "arquivo": "<cliente>_poc.json",
 "catalogo": { "...o JSON completo da POC..." },
 "resumo": {
   "produtos": 15,
   "categorias": 3,
   "fonte": "site",
   "preco": "publico",
   "imagens_substituidas": 0,
   "observacoes": "texto livre, quando algo precisa de gente"
 },
 "sessao_url": "https://claude.ai/code/session_..."}
```

`fonte` é `site`, `pdf` ou `planilha`. **`preco` só assume `publico`, `estimado`
ou `ausente`** — e é o campo mais importante do resumo: preço estimado que passa
despercebido vira erro na frente do cliente. O Mitra confere `preco` contra os
valores que vieram no catálogo e acusa contradição, então não afirme `ausente`
com produto precificado, nem o contrário.

**`catalogo` vai como está** — o JSON da POC inteiro, com `etapas[]`, do jeito
que o `validar_poc.py` aprovou. Não reformate, não resuma, não mande só a lista
de produtos: o Mitra lê `catalogo.etapas[]` procurando `endpoint === "products"`,
e um formato diferente entra com **zero produtos e sem erro**. Confira
`produtos_recebidos` na resposta: se vier `0`, o catálogo não foi lido, mesmo com
`ok: true`.

`sessao_url` é o campo `claude_code_session_url` da resposta do disparo.

Falhou a extração? Mande `status: "falhou"`, com o motivo em `observacoes` e
**sem** o campo `catalogo`.

## Status 200 não quer dizer que deu certo

A função do Mitra responde **2xx sempre**, inclusive quando rejeita — de
propósito, para não provocar retentativa inútil. **Leia o corpo**, nunca só o
status:

| Corpo | Significado | O que fazer |
|---|---|---|
| `{"ok": true}` | entregue | pronto |
| `{"ok": true, "duplicado": true}` | já tinha sido entregue | pronto, **não repita** |
| `{"ok": false, "erro": "TOKEN_INVALIDO"}` | o par pedido/token não bate | **não retente** — retentar não conserta; caia no plano B |
| HTTP não-2xx, timeout, erro de rede | indisponível | retente até 3 vezes com espera crescente; depois, plano B |

É a segunda vez neste projeto que um 200 não significa nada — a primeira foi o
endpoint de logo do portal, que respondia 200 e não trocava a imagem. Confira o
efeito, não a resposta.

## O plano B: Pull Request

Se o callback não passar — ou se o pedido vier **sem** `callback_url` —, entregue
como antes: branch `claude/poc-<cliente>-<pedido_id>`, o JSON em `Arquivos Json/`,
uma linha em `pedidos-atendidos.jsonl` e um PR cujo corpo diz produtos,
categorias, fonte, se o preço é público ou estimado, imagens substituídas e o que
precisa de gente.

Diga na sessão que caiu no plano B **e por quê**. Nesse caso o pedido fica
pendurado no Mitra esperando alguém — o trabalho não se perde, mas ninguém é
avisado sozinho.

## Registre sempre no repositório

Mesmo quando o callback dá certo, acrescente a linha em `pedidos-atendidos.jsonl`
e comite. É o registro de idempotência do **disparo**, e é o que faz o PASSO 1
reconhecer um pedido repetido. O token do callback cuida da idempotência do
**retorno**; são coisas diferentes e as duas precisam existir.

## Anotar: o certificado vence em 11/11/2026

O callback é `https` na **porta 8080**. A renovação é automática, mas quem serve
a 8080 precisa recarregar o certificado — se a 443 renovar e a 8080 ficar com a
cópia velha, o POST passa a falhar na verificação de TLS e **o erro vai parecer
problema do agente**. Se em novembro o callback começar a falhar sem mudança
nossa, é o primeiro lugar a olhar.
