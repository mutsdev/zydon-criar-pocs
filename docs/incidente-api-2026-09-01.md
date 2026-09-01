# Upload de imagem da API lento — medições de 01/09/2026

Relatório para o time da plataforma. Tudo abaixo foi medido, não inferido, da
máquina do João Pedro contra `api.zydon.com.br`, org **pocs**.

**Resumo:** `POST /api/sales/resource-files` passou a responder em **~26
segundos**. Na semana anterior o mesmo fluxo criava uma POC inteira em cerca de
um minuto. As leituras da mesma API continuam em ~0,3s, então não é lentidão
geral: está isolado no upload.

## O que mudou, com uma linha de base

| | 28/08 (sexta) | 01/09 (hoje) |
|---|---|---|
| POC de 12 produtos com imagem | concluída, **12/12 com foto** | 6 produtos em 5 min, e falhou |
| `POST /resource-files` | não instrumentado, mas o total era ~1 min | **mediana 26s por imagem** |
| `GET` na mesma API | — | 0,29s, saudável |

A POC da **Fornello Conservas**, criada em 28/08 pelo mesmo código e pela mesma
máquina, terminou com **12 de 12 produtos com imagem**. Foi verificado hoje pela
API, produto por produto. É a linha de base de que o fluxo funcionava.

## Medição 1 — o upload está lento, e o tamanho não importa

`POST https://api.zydon.com.br/api/sales/resource-files`
multipart, campo `files`, `Content-Type: image/png`, headers de autenticação da
org. Timeout do cliente: 150s (folgado de propósito, para medir em vez de
estourar).

| corpo | amostras | tempos | mediana |
|---|---|---|---|
| PNG 64×64, **~300 bytes** | 4 | 27,8s / 24,9s / 24,5s / 33,9s | **26,3s** |
| PNG 1200×1200, **~30 KB** | 2 | 32,8s / 21,9s | **27,4s** |

Todas responderam **HTTP 200** com o `resourceFiles[0].id` correto. Nenhuma
falhou.

**O achado principal está na comparação das duas linhas:** um corpo de 300 bytes
custa o mesmo que um de 30 KB — 100× maior. O tempo não acompanha o tamanho,
então não é banda nem upload de rede. É tempo gasto depois que o corpo chegou.

## Medição 1b — JSONs antigos dão o mesmo resultado

Para descartar que fosse algo nos catálogos montados recentemente, o mesmo
caminho de código (`upload_image_from_url`: baixa do site do cliente e sobe)
rodou com imagens de POCs antigas. Nenhum produto foi criado — só o
`resource-file`.

| catálogo | data do arquivo | tempo |
|---|---|---|
| worldseg | **30/04/2026** | 38,1s e 33,9s |
| cobra | **24/08/2026** | 44,0s e 50,1s |

Quatro de quatro com sucesso, todas lentas. Os tempos aqui incluem baixar a
imagem do site do cliente; a medição 1, sintética, isola o upload em ~26s.

Vale registrar que estes números foram colhidos cerca de uma hora depois da
medição 1 e são **piores** — 34 a 50s contra 26s.

## Medição 2 — a leitura da mesma API está saudável

`GET https://api.zydon.com.br/api/sales/categories/440`, 30 chamadas seguidas:

- **30 de 30 responderam HTTP 200**
- mínimo 0,23s · **mediana 0,29s** · máximo 0,35s

Mesma máquina, mesmo momento, mesma autenticação. Descarta rede do cliente,
DNS e credencial.

## Medição 3 — a rede da máquina está boa

Quatro requisições para cada destino, do mesmo terminal:

| destino | resultado |
|---|---|
| `api.zydon.com.br` | 4/4 OK, média **0,25s** |
| site do cliente (`multisegdistribuidora.com.br`) | 4/4 OK, média 0,74s |
| `api.github.com` | 4/4 OK, média 0,28s |
| `1.1.1.1` | 4/4 OK, média 0,56s |

## O efeito prático

O runner tinha timeout de **30 segundos** para o upload. Com o endpoint
respondendo em ~26s, virou cara ou coroa:

- passa raspando → produto criado **com** foto
- estoura em 30s → o retry espera 15s, 30s, 60s, 120s e desiste → produto criado
  **sem** foto, e a execução segue (falha de imagem não derruba a POC, por
  desenho)

Assim, cada produto custava até **~345 segundos**: quatro tentativas de 30s de
timeout mais 225s de espera acumulada.

Isso é visível na POC da **Witop Decor** (portal `ed0b221d-…`), criada hoje de
manhã:

| produtos | imagem |
|---|---|
| 1405, 1406, 1407, 1408, 1409 | **com** foto |
| 1410 a 1416 | **sem** foto |

Cinco passaram enquanto o endpoint ainda cabia nos 30s; do sexto em diante,
nenhum. A execução inteira levou **5h30** e o portal ficou com 7 de 12 produtos
sem imagem.

**Do nosso lado já mitigamos:** o upload passou a ter timeout próprio de 180s.
Com isso as imagens voltaram a subir, mas cada uma ainda custa ~26 segundos —
uma POC de 12 produtos leva ~6 minutos em vez de ~1.

## Um segundo sintoma, provavelmente relacionado: 404 em categoria existente

Na execução de `run_ts=20260901-163026`:

1. `POST /categories` cria **"Redes e Fibra Óptica", ID 450** — resposta OK.
2. Produtos **5 e 6** são criados referenciando a categoria **450** — OK.
3. Produto **7**, referenciando a **mesma** categoria 450, recebe:

```json
{"origin":"sales","timestamp":"2026-09-01 16:36:22.037100","status":404,
 "statusMessage":"Not Found","exception":"NotFoundException",
 "message":"Category com ID 450 não foi encontrado!"}
```

4. O rollback seguinte executa `DELETE /categories/450` e ele **funciona**.

O passo 4 é o que fecha o caso: não se apaga o que não existe. A categoria
estava lá o tempo todo, e os passos 2 e 3 provam que a mesma referência funcionou
e depois não funcionou, minutos depois, no mesmo processo.

Ocorrência única até agora — 30 `GET` na categoria 440 não reproduziram nenhum
404. Registrado por ser da mesma janela e do mesmo serviço (`origin: sales`).

## Como reproduzir

```python
import requests, io
from PIL import Image
buf = io.BytesIO(); Image.new("RGB", (64, 64), (90, 90, 200)).save(buf, "PNG")
cabecalhos = {...}  # os mesmos da org, sem Content-Type
resposta = requests.post(
    "https://api.zydon.com.br/api/sales/resource-files",
    headers=cabecalhos,
    files={"files": ("probe.png", buf.getvalue(), "image/png")},
    timeout=(10, 150))
# esperado hoje: HTTP 200 em ~26s
```

Com timeout menor que ~30s, a mesma chamada estoura em `ReadTimeout` — foi o que
mascarou o problema como "rede instável" durante boa parte do dia.

## O que pedimos

Olhar o que `POST /api/sales/resource-files` faz **depois** de receber o corpo.
O tempo não escala com o tamanho, o que sugere fila, processamento síncrono ou
espera por um recurso externo, e não transferência.

O `trace_id` das respostas está nos logs desta máquina, em `logs/`, e pode ser
enviado sob demanda.
