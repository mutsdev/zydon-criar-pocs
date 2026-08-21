# Criador de POCs — export para implantação

Fabrica um portal B2B de demonstração na plataforma Zydon a partir de um
**JSON declarativo**: cria marca, categorias, variações, produtos (com
imagens), critérios, tabelas de preço e descontos; duplica o portal de origem
da organização, associa as categorias e aplica a regra de listagem nos três
contextos (Cliente, Vendedor, Vitrine). Uma POC completa sai em minutos, sem
tocar no painel.

Esta pasta é o **export autocontido** do fluxo usado pelo time de
pré-vendas, preparado para servir de base ao fluxo de implantação de novos
clientes. Contém os scripts, o template do JSON, dois exemplos reais
validados, a documentação do formato e uma skill para agentes de IA
(`skills/criar-pocs/`).

## O fluxo em uma frase

**Um agente (ou uma pessoa) escreve o JSON da POC a partir do site do
cliente → `validar_poc.py` confere tudo → `executar_lote.py` valida e executa
os pendentes contra a API → o portal nasce pronto.**

A divisão de trabalho importa: montar o JSON exige navegador e olho (escolher
produtos, conferir imagem por imagem); executar é mecânico e idempotente. Por
isso as duas pontas são separadas — o JSON validado é o contrato entre elas.

## Estrutura da pasta

```
criar-pocs-export/
  README.md                 ← este arquivo
  ESTRUTURA-JSON.md         ← documentação completa do formato do JSON
  .env.example              ← modelo das variáveis de credencial
  requirements.txt          ← requests + python-dotenv
  credenciais.py            ← fonte ÚNICA de chaves, IDs por org e endpoints
  update_imagens.py         ← reparo de imagens a partir do skeleton
  buscar_imagens_ml.py      ← busca imagens no Mercado Livre em lote
  Criar Portais/
    criar_poc.py            ← o runner: cria catálogo + portal + regra
    validar_poc.py          ← checklist pré-entrega (fonte da verdade do formato)
    executar_lote.py        ← valida e executa todas as POCs pendentes
    template_poc.json       ← modelo do JSON de entrada (copiar e adaptar)
    template_variacoes.json ← bloco opcional de grade de variações
    listar.py               ← perfis, categorias e TPs de uma org
    descobrir_ids.py        ← IDs específicos de uma org nova
    busca_produtos.py       ← varre uma faixa de IDs de produto
    gerar_tabela.py         ← tabela de preço avulsa
  Arquivos Json/            ← entrada: os JSONs de POC a executar
    saidas/                 ← derivados gerados pelo runner (não editar à mão)
  exemplos/
    benenutri_poc.json      ← exemplo real, sem variações
    studiodasfestas_poc.json← exemplo real, com grade de variações
                              (fora de Arquivos Json/ de propósito — o lote
                              executaria os exemplos como POCs pendentes)
  skills/
    criar-pocs/SKILL.md     ← skill para o agente que escreve os JSONs
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # e preencha as chaves
```

As chaves saem do painel da Zydon (Configurações → Chaves de acesso) e são de
**escrita** — criam produto, tabela de preço e portal na organização. Elas
moram **só** no `.env` (nunca no código, nunca versionadas): `credenciais.py`
lê `ZYDON_<ORG>_CODE` / `ZYDON_<ORG>_TOKEN` para cada organização do dict
`ORGANIZACOES`.

> Histórico que justifica a regra: as chaves já viveram copiadas em sete
> arquivos .py, as cópias divergiram, e uma POC foi criada silenciosamente na
> organização errada — invisível no front. Fonte única, sempre.

**Organização nova:** acrescente a entrada em `ORGANIZACOES` no
`credenciais.py` (só o que não é segredo: portal de origem, unidade de
medida, cor), as duas variáveis no `.env`, e descubra os IDs específicos com
`python descobrir_ids.py <org>`. O `database_id` da base "Produtos" da org
nova também entra em `DATABASE_IDS_CONHECIDOS` no `validar_poc.py`.

## Como rodar

```bash
cd "Criar Portais"

# ciclo normal (lote)
python executar_lote.py --dry-run          # o que está pendente, sem tocar na API
python executar_lote.py pocs               # valida e executa tudo que falta

# uma POC por vez
python validar_poc.py "../Arquivos Json/empresa_poc.json"     # 0 erros = pronta
python criar_poc.py "../Arquivos Json/empresa_poc.json" pocs
python criar_poc.py --limpar "../Arquivos Json/empresa_poc.json" pocs   # rollback

# apoio
python listar.py pocs                # perfis, categorias, tabelas de preço
python descobrir_ids.py <org>        # IDs específicos de uma org
cd .. && python update_imagens.py "Arquivos Json/saidas/empresa_images_skeleton.json" pocs
python buscar_imagens_ml.py arquivo_images_skeleton.json      # busca ML em lote
```

A organização é sempre o último argumento; sem ela, o script pergunta.

## O contrato: JSON declarativo

O formato completo está em **`ESTRUTURA-JSON.md`**. O essencial:

- O JSON descreve **etapas** (marca → categorias → [variações] → produtos →
  critérios → tabelas de preço → descontos), cada uma com seus `requests`.
- IDs criados numa etapa são salvos com `salvar_id_como` e referenciados nas
  seguintes como `{{placeholder}}` — o runner resolve recursivamente.
- Imagem de produto vai em `temp_image_url` no nível do request; o runner faz
  o upload. URL direta em `payload.images` derruba a API (500).
- **Copie `Criar Portais/template_poc.json` e adapte** — não recrie do zero.
  Grade de variações: bloco pronto em `template_variacoes.json`.

## Validação: o portão de entrada

`validar_poc.py` roda todo o checklist automaticamente: estrutura das
etapas, campos obrigatórios, placeholders, campos que causam 400/500 na API,
regras de negócio (3 TPs com spread agressivo, descontos por categoria,
grade de variações consistente). Os erros que ele pega são exatamente os que
virariam falha na API — **POC que não valida não executa**: no lote ela fica
pendente e aparece no relatório com os erros.

Saída com código 1 quando há `[ERRO]`; `[AVISO]` não bloqueia, mas confira.

## Execução em lote e estado

`executar_lote.py` varre `Arquivos Json/`, valida cada pendente, executa as
que passam e imprime um relatório (criadas / inválidas / falharam).

O estado "já rodou" **vem do disco**: uma POC já rodou quando existe
`saidas/{base}_ids.json`, que o `criar_poc.py` só grava depois de falar com a
API. Não existe pasta "rodados" nem índice paralelo — e **não mova os JSONs
de entrada**: o rollback (`--limpar`) procura o `_criados.json` por caminho
relativo à fonte.

Há um corte por data (`DATA_CORTE` no `executar_lote.py`) para o lote não
tentar recriar acervo histórico; num deployment novo ele é inofensivo, mas
pode ser ajustado. `--so arquivo.json` roda um arquivo específico ignorando o
corte; `--tudo` varre o acervo inteiro.

POC que falha na API tem **rollback automático** (o runner desfaz o que
criou) e o lote segue para a próxima — POCs não dependem umas das outras.

## Saídas geradas (em `Arquivos Json/saidas/`)

| Arquivo | O que é |
|---|---|
| `{empresa}_ids.json` | IDs de tudo que foi criado (marca o estado "já rodou") |
| `{empresa}_images_skeleton.json` | esqueleto para reparo de imagens que falharam |
| `{empresa}_criados.json` | trilha para o rollback `--limpar` |

Reparo de imagens: preencha `image_url` no skeleton só dos produtos afetados
e rode `python update_imagens.py <skeleton> pocs`. O `buscar_imagens_ml.py`
preenche o skeleton buscando no Mercado Livre (e `--validar` testa as URLs
uma a uma, limpando as quebradas).

## A skill (para agentes de IA)

`skills/criar-pocs/SKILL.md` ensina um agente a montar o JSON de POC do zero
a partir do site do cliente — fluxo de coleta, regras de negócio, decisão
sobre grade de variações e o ciclo validar-corrigir. Instale no diretório de
skills do seu agente (ex.: `.claude/skills/criar-pocs/`) ou anexe o conteúdo
ao prompt do agente. Com a skill + esta pasta, um agente novo produz POCs que
validam de primeira.

## Adaptando para implantação de clientes

O que muda de POC para implantação real é o conteúdo, não o mecanismo:

1. **Org própria** em `ORGANIZACOES` + chaves no `.env` + `database_id` no
   validador (ver "Organização nova" acima).
2. **Catálogo real** no lugar dos 9–15 produtos de vitrine — o formato de
   etapas/placeholders aguenta qualquer volume; o limite de 15 é regra do
   validador pensada para demo, ajuste-o se necessário.
3. **Tabelas de preço e descontos reais** no lugar do padrão 3 TPs/spread
   agressivo — de novo: regra de demo no validador, não do runner.
4. O mecanismo que vale a pena preservar: **JSON declarativo como contrato**,
   **validador como portão** (todo erro conhecido da API vira checagem), e
   **estado derivado do disco** com rollback por POC.
