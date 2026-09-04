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

### Aviso a quem for consumir: os caminhos têm espaço

`Arquivos Json`, `Criar Portais`, `Identidade Visual`, `POC Completa` — todas as
pastas deste repositório têm espaço no nome, e isso já custou tempo três vezes.
Em 28/08/2026, na API do GitHub, o espaço codificado duas vezes
(`Arquivos%2520Json`) devolvia `404` com a pasta existindo — e `404` de pasta
lê como "ainda não tem entrega". Só o espaço cru responde `200`.

O mesmo cuidado vale no shell (aspas) e no import de Python (a pasta com espaço
não é pacote importável — ver `_carregar_criar_poc` nos testes).

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
 "logo_url": "https://site-do-cliente/.../logo.png",
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

`logo_url` é o que o `achar_logo.py` escolheu (PASSO 3B), ou `null` quando
nenhuma candidata passou. **O Mitra repassa esse campo no POST para o receptor**,
e é assim que o portal nasce com a identidade certa. `null` não é falha: a POC é
criada sem logo e isso vai em `observacoes`.

Quando vier `null`, acrescente **`logo_motivo`**: uma frase dizendo o que foi
achado e por que reprovou, em português, para o executivo saber o que pedir ao
cliente. Ex.: `"as 3 candidatas do site têm no máximo 250x60; peça o vetor ou
uma exportação com pelo menos 200px no maior lado"`. Sem isso o executivo vê
"sem logo" e não sabe o que fazer com a informação.

`sessao_url` é o campo `claude_code_session_url` da resposta do disparo.

Falhou a extração? Entregue mesmo assim o `resumo.json` com `status: "falhou"` e
o motivo em `observacoes`, e **não** comite catálogo nenhum. Pedido que fracassa
em silêncio é pior que pedido que fracassa.

## Quando o pedido trouxer `callback_url`

**Se você é a rotina rodando na nuvem, não faça o POST.** Ele não vai passar, e
tentar custa caro: em 28/08/2026 foram três pedidos seguidos com o mesmo
resultado — duas tentativas, duas falhas, minutos gastos, e a entrega saindo pelo
repositório de qualquer jeito. O egresso do ambiente só aceita CONNECT na 443 e o
Mitra atende na 8080. Isso não é intermitência, é topologia: **não melhora com
retentativa e não vai melhorar amanhã.** Registre no resumo que o callback foi
pulado e siga.

O callback continua valendo **para quem roda na máquina do João Pedro** — de lá
a 8080 responde, medido no mesmo dia. É o caso do `vigia_drive.py`, e é ele que
devolve `url` do portal depois da criação.

Quem for fazer o POST: o corpo é o resumo acima mais `callback_token` e
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

## `POST /previa`: a arte na mesma tela dos produtos

**A arte só precisa da logo.** Não precisa dos produtos, não precisa do portal,
não precisa da Zydon. Quem espera a varredura de produtos terminar para só então
pensar em banner está encadeando duas coisas independentes — e é por isso que,
até 04/09/2026, o executivo chegava na tela de curadoria com produtos e sem arte.

Chame esta rota **assim que a logo estiver resolvida**, em paralelo com a
varredura de produtos:

```
POST /previa   (X-Token, igual ao /pedido)
{"pedido_id": "...", "logo_url": "https://...", "empresa": "Acme",
 "segmento": "distribuição de autopeças",   // opcional
 "catalogo": {...}}                          // OPCIONAL: mande se já tiver
```

Responde **202** na hora; a arte leva de um a dois minutos e volta pelo callback:

```json
{"pedido_id": "...", "acao": "previa", "fase": "previa",
 "banners": {"login": {"url": "https://<túnel>/peca/...", "dimensao": [2400,1800]}}}
```

Sem arte, vem `"banners": {}` e `banners_erro` dizendo por quê — a seção some da
tela **com motivo**, que é diferente de sumir em silêncio.

Duas coisas para não tropeçar:

* **As URLs da prévia são efêmeras**, servidas por este receptor pelo túnel.
  Antes do disparo não existe portal, e sem portal não há resource-file — o
  arquivo nasce preso ao `solution_id`. Exiba, não guarde. Depois do `/pedido`
  as **mesmas peças** ganham URL de CDN e `file_id` de verdade.
* **`503 SEM_ENDERECO_PUBLICO`** quer dizer que o túnel não está no ar. Não é
  erro do seu lado, e a resposta certa é avisar o João Pedro, não repetir.

A peça gerada na prévia é **reaproveitada** pelo `/pedido` do mesmo `pedido_id`.
Gerar de novo produziria arte diferente da que o executivo acabou de aprovar —
o pior resultado possível, pior que não gerar.

## O ciclo de banner: gerar, curar, aplicar

Depois que o portal existe, ele ainda está com a **arte do portal de
demonstração** — a tela de login e o banner da home nascem duplicados do portal
base, e nenhuma POC jamais os trocou. Medido em 03/09/2026: o `login_image` e o
`imageLarge` da Fornello são os **mesmos ids** do portal base da org `pocs`.

O ciclo fecha isso, e ele tem uma pessoa no meio de propósito: quem decide se a
peça presta é o executivo, não a régua.

### O que a máquina faz sozinha

Enquanto a POC é criada, as peças são geradas **em paralelo** — elas só dependem
da logo e do catálogo, que já estão em disco quando a criação começa. Encadear os
dois só somaria os tempos.

Prontas as duas coisas, cada peça sobe como **resource-file**. Isso **não muda o
portal**: é só upload, e a URL que ele devolve é permanente. É essa URL que vai
no callback, e é ela que o Mitra exibe. Servir a peça pelo túnel não serviria —
o endereço do `cloudflared` morre junto com o processo, e o executivo abriria a
tela no dia seguinte com as imagens quebradas.

O callback do `/pedido` ganha dois campos:

```json
{"fase": "curadoria",
 "banners": {
   "login":     {"file_id": "...", "url": "https://...", "dimensao": [2400, 1800]},
   "cabecalho": {"file_id": "...", "url": "https://...", "dimensao": [1920, 320]}
 }}
```

`fase` é `curadoria` quando há peça esperando decisão, e `concluido` quando não
há — sem logo, sem chave do gerador, ou com `--sem-banner`. **`concluido` sem
`banners` não é erro**: o portal está pronto e fica com a aparência padrão.

Quando a geração sai mas a publicação falha, vem `banners_erro` com o motivo, e
`fase` continua `concluido`. Banner é o acessório; o portal é a entrega.

### A tela que o executivo vê

Duas peças, cada uma com a sua dimensão declarada, e três botões:

| botão | o que manda |
|---|---|
| **Gerar outra** (por peça) | `{"acao": "regerar", "pecas": ["login"]}` |
| **Aplicar** | `{"acao": "aplicar", "escolhas": {"login": "<file_id>"}}` |
| **Seguir sem banner** | `{"acao": "dispensar"}` |

O "Gerar outra" é **por peça**, e essa é a razão de a rota existir: recusar o 4:3
não pode custar o 1920x320 que ele aprovou. Regerar sem `pecas` é recusado com
`PECAS_FALTANDO` justamente por isso.

Em `escolhas` vai o `file_id` da peça que ele escolheu — não a chave dela. É o
que permite aplicar a **segunda** cena de login depois de ter visto a terceira:
todas continuam publicadas, cada uma com o seu id.

### A rota

```
POST /banner        (X-Token, o mesmo do /pedido)
{"pedido_id": "...", "acao": "regerar" | "aplicar" | "dispensar", ...}
```

| ação | resposta | por quê |
|---|---|---|
| `regerar` | **202**, e o resultado vem pelo callback | gerar cena leva minutos |
| `aplicar` | **200** com `gravados` e `confere` | são segundos; ele acabou de clicar |
| `dispensar` | **200** | idem |

`aplicar` e `dispensar` respondem na hora de propósito. Mandar o executivo
esperar um callback para saber se o próprio clique funcionou seria pior de usar
e mais difícil de depurar.

O `confere` da resposta do `aplicar` **sai de um GET**, e não do status do PUT.
É a única prova de que o portal mudou — pela terceira vez neste projeto, 2xx não
significa nada.

### Os erros que a rota devolve

| status | erro | o que aconteceu |
|---|---|---|
| 401 | `NAO_AUTORIZADO` | `X-Token` não confere |
| 404 | `PEDIDO_DESCONHECIDO` | esse `pedido_id` nunca passou por aqui |
| 409 | `SEM_PORTAL` | o pedido não criou portal; não há onde aplicar |
| 409 | `SEM_PECAS` | nada foi publicado para esse pedido |
| 400 | `PECAS_FALTANDO` | `regerar` sem dizer o quê |
| 400 | `ESCOLHAS_INVALIDAS` | peça fora de `login`/`cabecalho`, **ou `file_id` que nunca foi publicado** |
| 409 | `GRAVACAO_PELA_METADE` | gravou uma peça e a outra não — **leia abaixo** |
| 502 | `ZYDON_RECUSOU` | a Zydon recusou e **nada** foi gravado |

O `ESCOLHAS_INVALIDAS` de `file_id` desconhecido traz `desconhecidos` e
`publicados`, para o outro lado não ter que adivinhar quais valem. Ele é
conferido contra a **união de todas as gerações** do pedido, e não só a última —
é isso que sustenta a promessa de aplicar a segunda cena depois de ver a
terceira.

Isto existe porque um `file_id` inventado atravessava tudo e voltava como
`HTTP 500 — Invalid UUID string`, que lê como falha da plataforma quando é erro
de quem chamou. Achado por sondagem do time do Mitra em 03/09/2026.

### `gravados` diz o que fazer, e os dois erros têm a mesma forma

A tela de login e o banner moram em **endpoints diferentes**, e são dois PUTs sem
transação entre eles. Dá para terminar com a tela de login nova e o banner velho.

`GRAVACAO_PELA_METADE` e `ZYDON_RECUSOU` respondem no mesmo formato, e o que
separa os dois é o `gravados`:

```json
{"ok": false, "erro": "GRAVACAO_PELA_METADE",
 "gravados": ["login"], "faltou": ["cabecalho"], "detalhe": "..."}

{"ok": false, "erro": "ZYDON_RECUSOU",
 "gravados": [], "faltou": ["login"], "detalhe": "gravar aparencia: HTTP 500 — ..."}
```

**`gravados` vazio não é meia gravação.** O portal está como estava, e não há o
que reenviar — reenviar é uma segunda viagem condenada. Só reenvie quando
`gravados` tiver algo, e mande só o que está em `faltou`.

O `detalhe` é a única coisa que explica o quê. "Não gravou o login" não conserta
nada; `Invalid UUID string` conserta. Ele vem preenchido nos dois casos.

### Um callback de `regerar` não é um callback de portal

Ele traz `url`, `status` e `portal_id` repetidos, embora o evento não seja sobre
o portal. É defensivo de propósito: sem eles, um consumidor que trate todo
callback como "resultado da POC" conclui que o portal perdeu a URL. Distinga
pelo campo `acao`, que só existe nos callbacks de banner.

### O orçamento

O gerador é gratuito com teto: **10.000 neurons por dia**. Um cliente custa ~940
com duas candidatas por formato (login 313, cabeçalho 157, vezes duas). Cada
"Gerar outra" de login custa mais 313.

Dá para uns dez clientes por dia contando as regerações. Passou disso, a geração
falha e a peça sai pelo fallback determinístico — que é o piso e nunca fica feio,
mas é o piso.

## O feedback do executivo: dizer o que está errado, e não torcer

`regerar` sem feedback é a máquina chutando de novo. A ação aceita dois campos
opcionais, e eles mudam coisas diferentes:

```json
{"pedido_id": "...", "acao": "regerar", "pecas": ["login"],
 "feedback": {"login": "odiei essa paleta, muito escura",
              "cabecalho": "esse ficou ótimo, mantém a pegada"},
 "cor": "#1F6FEB"}
```

**O `feedback` pode falar de peça que não está em `pecas`, e isso é o ponto.**
Elogiar a peça aprovada é a forma de dirigir a que vai ser refeita — as duas vão
para o mesmo portal e precisam parecer da mesma leva. Quando cada peça só via o
próprio comentário, a instrução mais útil das duas se perdia inteira.

O texto vai **cru** para o prompt, sem classificação de humor: "odiei a paleta"
e "pode manter essa pegada" são a mesma frase para nós, e adivinhar qual é qual
erraria mais do que passar a frase e deixar o modelo ler.

**`cor` é um caso à parte, e o mais importante de entender.** A paleta sai da
**logo**, e quem pinta o painel, o título e os ícones é o Pillow — não a IA.
Regerar a cena com "odiei a paleta" no prompt muda a foto e devolve **o mesmo
painel na mesma cor**: o executivo pede de novo, e de novo, sem nunca chegar lá.
Queixa de cor só tem efeito com um hex em `cor`. Por isso o campo de feedback na
tela devia vir acompanhado de um **seletor de cor**.

Consequência a não estranhar: trocar a cor de uma peça deixa **a outra com a
paleta anterior**. Duas cores no mesmo portal é pior que a cor errada, então
mande as duas em `pecas` quando mudar `cor`.

Erros próprios da ação: `400 FEEDBACK_INVALIDO` (peça que não existe — recusar é
melhor que rodar sem o único dado que a pessoa se deu ao trabalho de escrever) e
`400 COR_INVALIDA` (não é `#RRGGBB`).

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
