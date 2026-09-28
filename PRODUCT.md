# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Prospect B2B** (distribuidora, indústria, atacado) vendo o portal de POC numa demonstração comercial conduzida pelo time de pré-vendas da Zydon. É quem julga o resultado visual.
- **Time de pré-vendas / implantação da Zydon**: opera os scripts, monta o JSON da POC, gera a identidade visual e apresenta. Usa `agente-de-portal.html` e os comandos de `Criar Portais/` e `Identidade Visual/`.

## Product Purpose

Fabricar, em minutos, um portal B2B de demonstração na plataforma Zydon que pareça o site do próprio prospect: logo dele, identidade visual dele, produtos dele — e já com as regras comerciais da plataforma funcionando (preço por cliente, descontos, três contextos: Cliente, Vendedor, Vitrine). Sucesso = o prospect reconhece a própria empresa no portal e vê as regras operando.

## Positioning

A POC não é um mock: é o portal real da Zydon, criado por API a partir de um JSON declarativo, com catálogo e identidade extraídos do site do cliente. Concorrente mostra demo genérica; aqui o prospect vê "a minha loja, já pronta".

## Operating Context

- Fluxo: agente ou pessoa escreve o JSON a partir do site do cliente → `validar_poc.py` → `executar_lote.py` cria o portal via API Zydon.
- Identidade visual: `Identidade Visual/gerar_banners.py preparar` (logo → paleta + prompt) → cenas geradas no Gemini (arrastadas para `cenas/`) → `montar` valida, compõe e sobe. Fallback determinístico garante peça apresentável mesmo sem cena.
- Apresentação acontece em reunião comercial, tela compartilhada ou projetada; peça ruim na frente do prospect custa a venda — regra do repo: **banner ruim não sobe**.
- Portal em si roda na plataforma Zydon (não é código deste repo); daqui saem só conteúdo, regras e as peças de imagem.

## Capabilities and Constraints

- Superfícies visuais que este repo controla:
  1. Peças de identidade que entram no portal do prospect: `login.jpg` 1920x1440 (4:3), `cabecalho.jpg` 1920x320 (6:1, com selo do cupom), `minimalista.png` 1920x320 (6:1, sem texto), mais `paleta.json` com os três hex do portal. **É a superfície principal** — é o que o prospect vê.
  2. `agente-de-portal.html`: página interna do agente (uso do time Zydon). Secundária.
- Superfície principal do Impeccable: **não decidida pelo usuário** ("eu não sei"). Assumido por evidência: as peças de identidade visual, por serem o que o prospect enxerga. Confirmar antes de trabalho visual grande.
- Stack: Python (requests, Pillow, numpy, svglib), sem framework web. HTML estático para a página interna.
- Validação é a espinha do gerador (`juiz.py`, `validar.py`, `regua.json`): limiares de legibilidade, contraste e ocupação da logo.
- Fonte disponível offline: `Identidade Visual/fontes/Inter.ttf`.
- Extensão da peça segue o conteúdo: JPEG para fotografia, PNG para arte chapada.

## Brand Commitments

- A marca no portal é sempre a **do prospect**, nunca a da Zydon. Logo do cliente é entrada obrigatória; paleta deriva da logo.
- Selo do cupom no cabeçalho é elemento fixo da peça.

## Evidence on Hand

- Exemplos reais validados de POC em `exemplos/` e `Arquivos Json/`.
- Casos de identidade gerada em `Identidade Visual/saidas/` (alimentos-talita, aroca-mercearia, atlas-autopecas, cirurgica-sao-jose) e `Identidade Visual/casos`.
- Documentação do formato em `ESTRUTURA-JSON.md`; entrega em `ENTREGA.md`; rotina em `ROTINA.md`.
- Não há depoimentos, métricas de conversão nem cases públicos; não inventar.

## Product Principles

1. O prospect tem que se reconhecer: fidelidade à marca dele acima de qualquer expressão própria.
2. Peça ruim não sobe — validação antes de estética, fallback sempre apresentável.
3. O portal é real: regras comerciais funcionando valem mais que polimento cosmético.
4. Velocidade é argumento: minutos, não dias; nada que exija retoque manual por peça.
5. Idempotente e reproduzível: mesmo JSON, mesmo portal.

## Accessibility & Inclusion

Peças de imagem são vistas em projeção e tela compartilhada com compressão: contraste alto entre logo e fundo, texto legível a distância. Sem requisito formal (WCAG) estabelecido.
