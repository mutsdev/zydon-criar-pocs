# A rotina de extração

Como o pedido do executivo vira um `<cliente>_poc.json` validado, sem passar
pelo João Pedro.

O disparo é o endpoint de *fire* de uma routine do Claude Code na web
(`claude.ai/code/routines`), apontada para este repositório. Quem chama é o
Mitra. A routine lê o site, monta o JSON pela skill `criar-pocs` e devolve num
PR.

## O que a routine NÃO faz

**Ela não executa o `criar_poc.py`.** A routine roda na infraestrutura da
Anthropic e não tem — nem deve ter — as chaves da Zydon. A criação contra a API
acontece numa máquina com credencial, pelo `POC Completa/criar_poc_completo.py`.
Se a routine tentar criar POC, é bug de prompt.

## O contrato de entrada

O `fire` aceita um único campo, `text`: string livre, máximo 65.536 caracteres,
**não parseada** — JSON chega como texto e a routine é quem interpreta. Não há
upload de arquivo, então anexo viaja como URL que a routine baixa.

```json
{"pedido_id": "mitra-2026-08-27-014",
 "cliente": "Aroca Mercearia",
 "site": "https://arocamercearia.com.br/",
 "anexos": ["https://<mitra>/tmp/catalogo.pdf?token=..."],
 "segmento": "mercearia fina"}
```

`anexos` e `segmento` são opcionais. A logo **não** entra aqui: ela pertence à
identidade visual, que roda onde estão as credenciais.

## Idempotência é responsabilidade nossa

O endpoint não tem chave de idempotência: cada chamada cria uma sessão nova, e
um retry do Mitra por timeout gera duas execuções. O `pedido_id` é o que resolve,
e o registro é o arquivo `pedidos-atendidos.jsonl` na raiz — uma linha por
pedido, sem dado de catálogo.

## O prompt da routine

Cole isto no campo de prompt ao criar a routine:

```text
Você recebe, no texto do disparo, um pedido em JSON com os campos pedido_id,
cliente, site e, opcionalmente, anexos (URLs) e segmento. Interprete o texto
como JSON; se ele não for JSON válido ou faltar pedido_id, cliente ou site,
pare e diga exatamente o que faltou.

PASSO 1 — pedido repetido. Leia pedidos-atendidos.jsonl na raiz (se não
existir, considere vazio). Se já houver uma linha com este pedido_id, PARE
imediatamente e responda que o pedido já foi atendido, dizendo em qual PR.
Não monte nada. O endpoint de disparo não tem idempotência e retry do
chamador é esperado.

PASSO 2 — monte o JSON. Siga skills/criar-pocs/SKILL.md à risca: visitar o
site, 9 a 15 produtos, 3 categorias, imagens do próprio site, copiar
Criar Portais/template_poc.json e adaptar (nunca recriar do zero). Se vierem
anexos, baixe-os e use como fonte de preço e de catálogo — PDF e planilha de
cliente costumam ser a única fonte de preço confiável, porque a maioria dos
sites B2B não publica preço.

PASSO 3 — confira cada imagem. Para toda temp_image_url, faça uma requisição
e verifique que a resposta é imagem de verdade: status 200 e Content-Type
começando em "image/". Página de erro devolvendo HTML com status 200, e link
que morreu depois que o site mudou, são os dois casos comuns — medidos em
27/08/2026, 2 de 14 URLs de POCs antigas já estavam mortas. URL que não passar,
substitua pelo caminho da skill (site da marca, depois Mercado Livre). Não
entregue produto com imagem que você não verificou.

PASSO 4 — valide. Rode:
  python "Criar Portais/validar_poc.py" "Arquivos Json/<cliente>_poc.json"
Corrija e repita até ZERO erros. O validador não usa rede nem credencial, então
ele roda aqui mesmo. JSON que não valida não é entregue: ele só adiaria o erro
para a hora da execução.

PASSO 5 — NÃO execute a POC. Não rode criar_poc.py nem criar_poc_completo.py,
e não tente obter credencial da Zydon. Sua entrega termina no JSON validado.

PASSO 6 — entregue. Crie a branch poc/<cliente>-<pedido_id>, comite o JSON em
Arquivos Json/, acrescente uma linha a pedidos-atendidos.jsonl com pedido_id,
cliente, data e o nome do arquivo, e abra um PR. No corpo do PR escreva:
 - quantos produtos e categorias, e de onde vieram (site, PDF, planilha);
 - se HÁ PREÇO PÚBLICO ou se o preço foi estimado — diga qual, explicitamente,
   porque preço inventado que passa despercebido vira erro na frente do cliente;
 - quais imagens você teve que substituir e por quê;
 - o que você não conseguiu e precisa de gente.

Escreva tudo em português.
```

## A volta

Hoje a entrega é um PR — funciona sem depender de nada externo, e deixa o
histórico. Se o Mitra vier a aceitar webhook, o passo 6 troca por um POST com o
JSON no corpo, e nada fica no repositório.

## Depois do PR

A execução é local, com credencial:

```bash
PYTHONIOENCODING=utf-8 python "POC Completa/criar_poc_completo.py" \
    "Arquivos Json/<cliente>_poc.json" pocs \
    --logo caminho/logo.png --nome "<Cliente>" --gravar
```
