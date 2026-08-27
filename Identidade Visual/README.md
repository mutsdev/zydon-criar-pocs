# Identidade visual do portal

Gera as três peças de um portal Zydon a partir da logo do cliente:

| Peça | Dimensão | Onde entra |
|---|---|---|
| `login.jpg` | 1920x1440 (4:3) | tela de login |
| `cabecalho.jpg` | 1920x320 (6:1) | cabeçalho, com o selo do cupom |
| `minimalista.png` | 1920x320 (6:1) | faixa interna, sem texto |

A extensão sai da peça: JPEG quando tem fotografia, PNG quando é arte chapada.

Mais `paleta.json` com os três hexadecimais que o portal usa.

**O requisito que manda no desenho: banner ruim não sobe.** A peça aparece na
frente do cliente numa demonstração comercial, então é preferível não gerar do
que gerar feio. Por isso a validação não é o passo final — é a espinha — e por
isso existe um fallback determinístico que sempre sai apresentável.

## Como rodar

```bash
# 1. logo -> paleta + prompt do GEM (abre a pasta cenas/ no fim)
python "Identidade Visual/gerar_banners.py" preparar \
    --logo caminho/da/logo.png --nome "Cliente" --segmento "autopeças"

# 2. cole prompt-gem.txt no GEM e ARRASTE as imagens da página para cenas/

# 3. cenas -> peças validadas + folha de contato
python "Identidade Visual/gerar_banners.py" montar "<pasta>"
```

Modos para iterar barato:

```
--sem-juiz         só o degrau 1; ajusta a régua sem gastar cota
--so-fallback      ignora as cenas; mostra o piso de qualidade
--tentativas N     limita quantas cenas por formato são julgadas
--sem-rede         (no preparar) não consulta o segmento
--regua outra.json testa limiares sem mexer no arquivo bom
```

Sem cena nenhuma, `montar` ainda entrega as três peças pelo fallback. O
pipeline nunca trava.

### Não precisa baixar nem renomear

No Windows, o Chrome e o Edge deixam arrastar a imagem da página do Gemini
direto para uma pasta do Explorer — e o `preparar` já abre `cenas/` para isso.

O nome que o navegador dá (`Gemini_Generated_Image_a1b2c3.png`) não importa: as
duas cenas têm formatos que não se confundem — login é 4:5 retrato, cabeçalho é
3,3:1 panorâmico — e `cenas.classificar` separa uma da outra por aí. Renomear
para `login-1.png` continua funcionando e **manda** sobre o palpite, para quando
você quiser forçar.

Arraste quantas quiser: todas são julgadas, em ordem alfabética, e aparecem lado
a lado na folha de contato com o motivo de cada reprovação. Arquivo de aspecto
absurdo (mais de 1,8x fora) é ignorado em vez de chutado num formato.

### Formato e peso são decisão de gravação, não de reprovação

Peça com fotografia sai em **JPEG**, com a qualidade baixando até caber no
limite; peça chapada sai em **PNG**, porque JPEG põe halo em borda dura de cor
sólida e o minimalista só tem isso. Na prática: ~330 KB o login, ~95 KB o
cabeçalho, ~12 KB o minimalista.

A primeira versão media o peso do **arquivo de entrada** e reprovava a cena por
isso — o que teria reprovado toda cena real, já que imagem arrastada do Gemini
tem vários MB e isso não diz nada sobre ela ser boa. O arquivo de saída é nosso:
se ficou pesado, a resposta é gravar melhor (`salvar.py`).

## Subir logo e favicon para o portal

```bash
python "Identidade Visual/subir_identidade.py" --org pocs     --portal <uuid-do-portal> --logo caminho/logo.png --nome "Cliente"
```

**Simulação é o padrão.** Sem `--gravar` ele prepara tudo, mostra o que faria e
não escreve. Isso grava num portal de produção que alguém pode estar
apresentando — o padrão seguro é não escrever. A aparência anterior vai para
disco antes de qualquer gravação, e é o único caminho de volta.

### A rota que funciona, e a que mente

O OpenAPI do Zydon anuncia dois endpoints dedicados:

```
POST /api/b2b/portals/appearance/logo      campo `logo`
POST /api/b2b/portals/appearance/favicon   campo `favicon`
```

**Eles não funcionam.** Medido em 26/08/2026 contra um portal real: devolvem
HTTP 200 com corpo vazio e não mudam nada — nem o `brand_image`, nem o conteúdo
do arquivo apontado por ele. O nome do campo está certo (mandar `file` ou
`image` responde *"Required part 'logo' is not present"*), então não é erro de
chamada: o endpoint aceita e ignora.

A rota que funciona é a mesma que o `criar_poc.py` já usa para imagem de
produto, em dois passos e **com credenciais diferentes em cada um**:

```
1. POST /api/sales/resource-files    chaves da ORG no cabeçalho  -> file id
2. PUT  /api/b2b/portals/appearance  Bearer JWT do portal        -> aplica o id
```

O portal não vai na URL: vem do escopo do JWT. Errar o `solution_id` é escrever
no portal errado, então ele nunca tem valor padrão.

### Duas armadilhas do PUT

**Ele leva o corpo inteiro** — título, razão social, CNPJ, cor, botão flutuante.
Mandar só o campo que mudou apaga o resto. Não existe função neste módulo que
monte um corpo do zero: `atualizar_aparencia` exige a aparência atual e funde.

**A resposta do PUT mente sobre dois campos**: devolve `has_shop` e
`enable_access_request` como `false` mesmo quando estão `true`. É o DTO de
resposta deles que não reflete esses campos; um GET depois mostra que o estado
real não mudou. Confira pelo GET, nunca pela resposta do PUT.

### Por que o script baixa de volta o que subiu

Depois de gravar, ele busca o arquivo que o portal está servindo e compara o
SHA-256 com o que enviou. Foi essa checagem que pegou o endpoint dedicado
mentindo — status 200 não é prova de nada quando existe um caminho que responde
OK sem fazer o trabalho.

### O favicon

Derivado da logo, em três caminhos, e ele diz qual usou:

| Logo | Caminho |
|---|---|
| já quase quadrada (≤1,4:1) | usa ela inteira |
| símbolo + palavra separados por um vão | recorta só o símbolo |
| só palavra | a inicial do cliente na cor da marca |

O terceiro é palpite e sai com aviso — nesse caso passe `--favicon` com um
arquivo seu. O ícone sempre tem fundo sólido: aba de navegador tem tema claro e
escuro, e PNG transparente some em um dos dois.


## Por que é semiautomático

**Nenhum modelo de imagem do Gemini tem free tier.** Medido em 26/08/2026, com
uma chave real, em quatro modelos:

| Modelo | Free tier |
|---|---|
| `gemini-3.1-flash-image` | `limit: 0` |
| `gemini-3.1-flash-lite-image` | `limit: 0` |
| `gemini-3.1-flash-image-preview` | `limit: 0` |
| `gemini-2.5-flash-image` | `limit: 0` |

O erro é `RESOURCE_EXHAUSTED` em
`GenerateRequestsPerDayPerProjectPerModel-FreeTier` com **limite zero** — não é
cota esgotada por uso, é cota que não existe. A mesma chave responde 200 em
`gemini-3.6-flash` (texto e visão).

Então a geração da cena fica no GEM do aplicativo, que continua gratuito, e o
script faz todo o resto. O que o script perde é o clique de gerar; o que ele
ganha é nunca deixar subir peça ruim.

## O desenho: a costura reta

O prompt original do GEM pedia que o modelo **desenhasse as letras** ("Bem-vindo
ao Portal do Cliente", "Cupom PRIMEIRACOMPRA") e **redesenhasse a logo** dentro
da cena. São exatamente os dois defeitos que reprovam banner de IA, e nenhum
prompt os resolve de forma confiável — é falha de amostragem, não de instrução.

Aqui as duas responsabilidades nunca se misturam no mesmo pixel:

```
┌────────────┬────────────────┐
│  PILLOW    │    A CENA      │   painel: logo em PNG real, fonte de verdade
│ [logo PNG] │  só fotografia │   cena:   sem texto, sem logo
│ Bem-vindo  │  SEM texto     │
│ ■ ■ ■      │  SEM logo      │   junção: borda reta, sem fusão
└────────────┴────────────────┘
```

Consequências que pagam o custo:

- Erro de ortografia e logo deformada viram **impossíveis por construção**.
- "Apareceu texto na cena" vira reprovação binária, muito mais confiável que
  julgar se um texto está bonito.
- Regerar custa só a cena, não a peça inteira.

### As proporções, e a armadilha nelas

A **peça** de login é 4:3, mas a **cena** dela não é: descontado o painel de
768px sobram 1152x1440, que é 4:5 retrato. Pedir 4:3 e encaixar em 4:5 custaria
27% da imagem em recorte. `formatos.py` é a fonte única disso.

O cabeçalho é pior: 6:1 **não existe** em gerador nenhum (o teto é 21:9 ≈
2,33:1). A cena dele, 3,3:1, sai de um 21:9 recortado na altura — por isso o
prompt avisa que as margens de cima e de baixo serão descartadas.

**Duas operações, e só duas: recortar e reduzir.** Nunca esticar, nunca ampliar.
Cena pequena demais é recusada com o tamanho exato que faltou, em vez de
ampliada — ampliar inventaria pixel e cairia no degrau 1 por foco.

## A validação, em degraus

Do mais barato ao mais caro. Falhou num degrau, não sobe para o próximo — o
seguinte custa cota.

**Degrau 0 — a logo** (`logo.py`). Recorta a moldura vazia, remove fundo chapado
quando os quatro cantos concordam, e aborta o cliente se a logo for pequena
demais, desproporcional ou vazia. É o único ponto que aborta.

**Degrau 1 — mecânico** (`validar.py`), sem rede, milissegundos. Na cena:
dimensão exata, degeneração, barras, foco, banda de cor, matiz intruso, respiro,
costura. Na peça montada: logo não esticada, texto não truncado, nada invadindo
a cena, contraste WCAG e o peso do arquivo já gravado.

**Degrau 2 — juiz de visão** (`juiz.py`), em `gemini-3.6-flash` com JSON
estruturado. Ele julga **a cena, nunca a peça montada** — a peça contém o painel
do Pillow, que tem texto por construção, e perguntar "tem texto?" sobre ela
reprovaria 100% das tentativas. Os riscos da peça são determinísticos e já
morreram no degrau 1.

Regra de decisão sem margem: qualquer defeito fatal reprova, cena fora do
segmento reprova, nota abaixo de 4 reprova. O viés é empurrado para o lado
seguro — *na dúvida, marque o defeito como presente*.

**O fallback** (`fallback.py`) entra quando não há cena aprovada, quando a cota
acaba, quando a chave falta ou quando a rede cai. Ele passa no degrau 1 nos três
formatos, e isso é travado em teste: se um dia parar de passar, é bug nosso.

## A régua se ajusta em `regua.json`, não no código

Discordou do veredito olhando a folha de contato? O conserto é um número ali.
Dois deles **foram medidos, não chutados** (26/08/2026, contra 6 fotografias
reais):

- `energia_borda_minima = 3.0` — fotos nítidas ficam entre 4,0 e 32,2; as mesmas
  desfocadas caem para 1,6–2,6. Com o 6,0 inicial, metade das fotos boas
  reprovava.
- `delta_e_paleta = 45.0` — com 34 a métrica não separava nada (foto que casa
  com a paleta dava 0,244; foto alheia, 0,224). Com 45: casa = 0,53–0,96,
  alheia = 0,02–0,11. Com 55 ela volta a não discriminar.

O resto continua sendo chute calibrável. **A calibração de verdade precisa de
3–5 logos de clientes reais com banners que você já aprovou** — sem esse
conjunto em `casos/`, os outros limiares são palpite.

## O que fica salvo

```
saidas/<cliente>/<carimbo>/
  logo-normalizada.png   paleta.json   prompt-gem.txt   contexto.json
  cenas/                 ← você larga os PNGs do GEM aqui
  login-1.png  login-2.png  …          ← toda tentativa, inclusive reprovada
  login-fallback.png  …
  aprovados/             ← o que sobe
  manifesto.json         ← peça → origem, tentativas, motivos
  contato.html           ← abra com duplo clique
```

Nada é apagado: a tentativa reprovada é o dado mais valioso que o sistema
produz, porque é ela que diz se a régua concorda com você.

`saidas/` é gitignored — é logo e material de cliente, mesma regra de
`Arquivos Json/saidas`.

## Limites conhecidos

- A logo aplicada na fachada ao fundo — o detalhe mais bonito do GEM original —
  se perde. O prompt pede uma forma sólida sem letras no lugar. Avalie na folha
  de contato se compensa.
- O juiz é um modelo julgando saída de modelo, e modelos são complacentes. Se a
  calibração mostrar leniência, o próximo passo é uma pergunta adversarial
  ("aponte o pior defeito desta imagem") ou dois juízes com recortes diferentes.
- Quando a logo é de cor forte, a paleta extrai essa cor como principal e a logo
  sumiria dentro do painel. A saída é o **knockout** (silhueta na cor do texto),
  que é a versão monocromática que toda marca tem. Perde-se a policromia; ganha-
  se existir.
- `cache_segmentos.json` é versionado de propósito: é conhecimento compartilhado
  entre clientes e não tem dado de ninguém. Corrija à mão quando a lista sair
  ruim — a correção vale para sempre.
