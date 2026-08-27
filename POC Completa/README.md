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

O `criar_poc.py` daqui é uma **cópia** do de `Criar Portais/`, para que iterar
nesta costura não toque no runner que já roda em produção.

A cópia tem **uma única diferença**, e ela existe por um motivo concreto: o
portal só ganha UUID no meio da execução, e até agora esse id era apenas
impresso na tela — o `_ids.json` é gravado *antes* da etapa do portal e não o
contém. Sem isso, subir a identidade exigia o humano copiar o UUID da tela e
colar num segundo comando. O `run_poc` da cópia aceita `saida=None`; quando vem
um dicionário, ele recebe `saida["portal_id"]`.

Para ver a diferença:

```bash
diff "Criar Portais/criar_poc.py" "POC Completa/criar_poc.py"
```

**Cópia diverge.** Correção feita no original não chega aqui sozinha. Enquanto
esta pasta for experimental isso é aceitável; quando a costura estabilizar, o
certo é o parâmetro `saida` subir para o runner original e esta cópia sumir.

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
