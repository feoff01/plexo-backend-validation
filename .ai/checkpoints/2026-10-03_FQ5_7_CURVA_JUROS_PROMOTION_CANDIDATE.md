# Checkpoint — FQ5.7 curva de juros · promotion candidate

Data: 2026-10-03
Status: **CANDIDATA PÚBLICA / AGUARDANDO CI**

## Capability
- `dados.curva_juros` -> semver candidata **1.0.1**;
- `exposed_to_llm=True`;
- família `dados`;
- fonte determinística: `market.yield_curve` / ANBIMA;
- somente vértices oficiais exatos.

## Planner
Rotas autorizadas:
- ETTJ nominal/prefixada -> `ettj_pre`;
- curva real/IPCA -> `ettj_ipca`;
- inflação implícita -> `inflacao_implicita`;
- "curva de juros" genérica -> ETTJ prefixada explicitada no objetivo.

Restrições:
- `vertices_du` somente se o cliente informar dias úteis;
- não inventar nearest/conversão;
- sem delta entre datas;
- sem slope/curvature;
- sem interpolation/extrapolation;
- sem duration/DV01;
- sem choque;
- sem forecast;
- sem fair value/recomendação.

## Apresentação
Mapper determinístico em `app/agents/blocos.py`:
- até 20 vértices -> tabela;
- curva maior -> série por d.u.;
- provenance ANBIMA + cutoff;
- warning explícito para vértice ausente;
- nota de não interpolação/previsão.

## Readiness
- catálogo esperado: 36 tools registradas / 33 públicas / 3 legacy ocultas;
- maior payload observado (IPCA 65 vértices): <5 KB;
- readiness adicionado ao gate dirigido.

## Gate
Não considerar promoção GREEN até PostgreSQL 18, directed, full suite, prompts check e tools sync --check passarem no mesmo HEAD.
