# Como a rotina entrega o resultado

Este arquivo é a **fonte da verdade da entrega**. O prompt da rotina aponta para
cá de propósito: mudança de contrato com o Mitra vira um commit, e não uma ida à
interface para recolar o prompt.

## O caminho normal: entregar no repositório

**O Mitra vem buscar.** Ele lê os PRs abertos pela API do GitHub, de dentro da
rede dele. Não somos nós que chamamos ele.

Isso é resposta a um problema medido em 28/08/2026: o callback do Mitra vive numa
porta alta (8080), e o egresso do ambiente da rotina reseta o TLS antes do
certificado — é proxy de saída que só aceita CONNECT na 443. A 443 daquele host
existe, mas é **outro deployment**, com outro banco; mandar o `callback_token`
para lá seria entregar um segredo nosso a um sistema que não é o deles. Invertendo
o sentido, a dependência de egresso some e nenhum segredo viaja.

Entregue quatro coisas, na branch `claude/poc-<cliente>-<pedido_id>`:

1. **`Arquivos Json/<cliente>_poc.json`** — o catálogo, como o `validar_poc.py`
   aprovou.
2. **`Arquivos Json/<cliente>_poc.resumo.json`** — o resumo legível por máquina
   (formato abaixo). É o que o Mitra consome; **não deixe essa informação só na
   prosa do PR**, porque prosa obriga o outro lado a adivinhar.
3. **Uma linha em `pedidos-atendidos.jsonl`** com `pedido_id`, `cliente`, `data`
   e o caminho do arquivo. É o registro de idempotência do disparo, e é o que faz
   o PASSO 1 reconhecer pedido repetido.
4. **Um PR**, cujo corpo repete o resumo em português, para quem for ler com
   olhos humanos.

### A correlação é pelo `resumo.json`, não pelo nome da branch

**O `pedido_id` que vale é o de dentro do `resumo.json`.** O nome da branch é
conveniência para quem lê com olhos, e não dá para confiar nele: na entrega do
`mitra-2026-08-28-002` a rotina usou a branch automática da sessão
(`claude/zen-bohr-2jn757`) em vez da nomeada, e o `pedido_id` sumiu do nome.

Ainda assim, **nomeie a branch `claude/poc-<cliente>-<pedido_id>`** — ajuda quem
for olhar. Só não a deixe carregando o contrato sozinha.

### O resumo

```json
{"pedido_id": "mitra-2026-08-28-003",
 "status": "concluido",
 "arquivo": "Arquivos Json/<cliente>_poc.json",
 "resumo": {
   "produtos": 13,
   "categorias": 3,
   "fonte": "site",
   "preco": "publico",
   "imagens_substituidas": 0,
   "observacoes": "texto livre, quando algo precisa de gente"
 },
 "sessao_url": "https://claude.ai/code/session_..."}
```

`fonte` é `site`, `pdf` ou `planilha`. **`preco` só assume `publico`, `estimado`
ou `ausente`** — é o campo mais importante do resumo, porque preço estimado que
passa despercebido vira erro na frente do cliente. O Mitra confere `preco` contra
os valores do catálogo e acusa contradição: não afirme `ausente` com produto
precificado, nem o contrário.

`sessao_url` é o campo `claude_code_session_url` da resposta do disparo.

Falhou a extração? Entregue mesmo assim o `resumo.json` com `status: "falhou"` e
o motivo em `observacoes`, e **não** comite catálogo nenhum. Pedido que fracassa
em silêncio é pior que pedido que fracassa.

## Quando o pedido trouxer `callback_url`

Aí o Mitra alcançou a rotina e quer ser avisado: faça o POST, **além** de
entregar no repositório. O corpo é o resumo acima mais `callback_token` e
`catalogo` com o JSON inteiro.

**`catalogo` vai como está**, com `etapas[]`. Não reformate nem resuma: o Mitra
lê `catalogo.etapas[]` procurando `endpoint === "products"`, e formato diferente
entra com **zero produtos e sem erro**. Confira `produtos_recebidos` na resposta.

### Status 200 não quer dizer que deu certo

A função do Mitra responde **2xx sempre**, inclusive quando rejeita — de
propósito, para não provocar retentativa inútil. **Leia o corpo**, nunca só o
status:

| Corpo | Significado | O que fazer |
|---|---|---|
| `{"ok": true}` | entregue | pronto |
| `{"ok": true, "duplicado": true}` | já tinha sido entregue | pronto, **não repita** |
| `{"ok": false, "erro": "TOKEN_INVALIDO"}` | o par pedido/token não bate | **não retente** — retentar não conserta |
| HTTP não-2xx, timeout, erro de rede | indisponível | retente **uma** vez e desista |

Falhar o callback **não é falhar a entrega**: o repositório já tem tudo, e o
Mitra vem buscar. Diga na sessão que o callback não passou e siga — não gaste
minutos em retentativa, porque o tempo da rotina é o recurso escasso.

É a segunda vez neste projeto que um 200 não significa nada — a primeira foi o
endpoint de logo do portal, que respondia 200 e não trocava a imagem. Confira o
efeito, não a resposta.

## Nunca mande o callback para outro endereço

Se o `callback_url` não responder, **não tente outra porta nem outro host**. Em
28/08/2026 a 443 do mesmo nome era outro deployment: o `callback_token` teria ido
para um sistema de terceiro. Endereço fora do contrato é vazamento, não
alternativa.

## Anotar: o certificado vence em 11/11/2026

Enquanto o callback existir na porta 8080, esse vencimento importa. A renovação é
automática, mas quem serve a 8080 precisa recarregar o certificado — se a 443
renovar e a 8080 ficar com a cópia velha, o POST passa a falhar na verificação de
TLS e **o erro vai parecer problema do agente**. Sintoma diferente do de hoje: o
reset atual acontece *antes* de qualquer certificado. Não confunda os dois.
