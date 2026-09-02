# POC Completa

Catálogo + portal + identidade visual numa passada só.

```bash
PYTHONIOENCODING=utf-8 python "POC Completa/criar_poc_completo.py" \
    "Arquivos Json/<cliente>_poc.json" pocs \
    --logo caminho/logo.png --nome "Cliente" --gravar
```

Sem `--gravar`, a identidade é apenas simulada — **mas o catálogo e o portal são
criados de verdade assim mesmo**, porque o runner não tem modo de simulação. Ao
final ele imprime o comando pronto para gravar a identidade no portal que acabou
de criar, sem refazer a POC.

## Por que esta pasta existe

Ela costura o runner com a identidade visual. **O runner é um só**, o de
`Criar Portais/criar_poc.py` — esta pasta não tem cópia dele.

Teve, até 02/09/2026, "para iterar sem tocar no que roda em produção". A cópia
diferia do original por um parâmetro: o portal só ganha UUID no meio da
execução, e o `_ids.json` é gravado *antes* dessa etapa, então o id não estava
em lugar nenhum. O `run_poc` passou a aceitar `saida=None` e a escrever
`saida["portal_id"]` ali.

**O que a cópia custou.** Duas pastas com um módulo de mesmo nome, e o
`sys.path` do `criar_poc_completo.py` montado com `insert(0)` numa ordem que
punha `Criar Portais` na frente: o `import criar_poc` trazia o original, sem
`saida`, e a execução morria em `TypeError` antes de criar coisa alguma. Não
apareceu antes porque o caminho sem logo chama o runner direto — só a primeira
POC **com** logo passou por aqui (Película da Vida, 02/09/2026).

Hoje o parâmetro está no runner original e a cópia não existe. Se voltar a
aparecer um módulo de mesmo nome em duas pastas do `sys.path`, o import não é
"o daqui": é o da primeira pasta da lista.

## A ordem, e por que ela é essa

1. `run_poc` — marca, categorias, produtos, critérios, tabelas, descontos,
   duplicação do portal, associação das categorias, regra de listagem.
2. Só se o passo 1 voltou OK **e** um portal foi criado, chama o
   `Identidade Visual/subir_identidade.py` com o UUID.

Se a POC falha, a identidade não é tocada: subir logo num portal incompleto só
cria trabalho de limpeza. Se não há `portal_origem_id` na org, o runner pula o
portal — e aí não existe onde gravar a identidade; ele avisa e para.

## Credenciais

As chaves Zydon moram no `.env` do Sales Ops, não neste repositório. Quem sabe
achar os dois lugares é o `_carregar_env()` do `subir_identidade`, e é por isso
que ele é importado **antes** de `credenciais` — a ordem dos imports no topo do
`criar_poc_completo.py` não é estética.
