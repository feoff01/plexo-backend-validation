# Design — Consolidação de fatores + dependência

Data: 2026-09-30  
Estado: **design proposto; nenhuma implementação autorizada por este documento**  
Pré-requisitos: `.ai/ANALISTA_CAPABILITY_AUDIT_2026-09-30.md` e `.ai/WORKING_PROTOCOL.md`

## 1. Problema a resolver

O FQ5.4 adicionou `quant.dependencia_macro` para responder dependência de um ativo com FX, porque `market.fx_rates` não fazia parte do contrato histórico de `quant.dependencia`.

A matemática não era nova. As duas tools usam o mesmo Quant Core:
- `calculate_returns` / `calculate_index_returns`;
- `align_returns`;
- `dependence_estimate`;
- mesmos gates de qualidade e mesma semântica de lag.

O gap real era **resolver/carregar uma nova fonte de série**.

Se o padrão for repetido, Brent, curva de juros, commodity, inflação ou qualquer novo fator tenderiam a gerar novas tools de dependência/sensibilidade/regime. Esse desenho é rejeitado.

## 2. Objetivo

Criar uma abstração compartilhada de resolução de fator/série para o Analista e fazer uma única interface canônica de dependência consumir:
- ativo;
- índice/taxa;
- câmbio.

O cutover deve:
- reutilizar integralmente o Quant Core existente;
- não alterar a matemática de FQ3/FQ4;
- não criar tabela/migration;
- preservar provenance, quality, cutoff e temporal semantics;
- preservar versões históricas/replay;
- eliminar `quant.dependencia_macro` do catálogo de novas chamadas sem apagar seu histórico;
- deixar uma extensão limpa para fatores futuros.

## 3. Não objetivos

Este cutover **não** deve:
- adicionar Pearson/Spearman novos;
- criar rolling correlation;
- criar up/down-market;
- criar sensibilidade a FX;
- refatorar `quant.sensibilidade`, `quant.analise_condicional` ou `quant.regimes`;
- adicionar Brent/commodity;
- implementar yield curve;
- alterar storage, source priority ou vintage;
- modificar migrations históricas;
- transformar dependência em causalidade ou previsão.

As capacidades rolling/up-down já existem no Quant Core e continuam fora do contrato desta etapa.

## 4. Princípio central

**Resolução de dados é compartilhada; transformação estatística pertence à análise.**

Um `ResolvedFactor` deve dizer:
- o que foi pedido;
- o que foi resolvido;
- qual série foi carregada;
- qual unidade/origem/identidade existe;
- se foi encontrado e, para ativo, se está no universo.

Ele **não** deve dizer universalmente se a série vira retorno ou mudança de nível.

Exemplo:
- Selic em `quant.dependencia` segue a semântica histórica de `calculate_index_returns`;
- Selic em `quant.sensibilidade` usa mudança de nível;
- Selic em `quant.regimes` pode usar nível ou direção.

Embebedar uma única transformação dentro do resolver recriaria acoplamento entre dados e matemática.

## 5. Camadas propostas

### 5.1 Camada física já existente — manter

`app/market/series.py`
- preços;
- índices/taxas;
- calendário;
- `ResolvedMarketSeries`;
- quality/provenance;
- PriceBasis/TemporalSemantics.

`app/market/factors.py`
- adapter físico de FX;
- normalização de moeda;
- leitura de `market.fx_rates`;
- produção de `ResolvedMarketSeries`.

Não alterar esses arquivos no primeiro passo apenas para "limpar" arquitetura.

### 5.2 Nova camada compartilhada do Analista

Arquivo recomendado:

`app/tools/analista/factor_resolution.py`

Motivo para viver no Analista, e não em `app/market/`:
- a resolução de instrumento por termo atualmente vive em `_comum.py`;
- mover essa função para `app/market/` exigiria alterar `_comum.py`, que participa do fingerprint de várias tools públicas;
- isso causaria um bump em cascata sem necessidade analítica.

A nova camada pode **consumir** os loaders existentes sem alterar `_comum.py`. Migração de resolução de instrumentos para uma camada market pode ser avaliada futuramente, com versionamento próprio.

## 6. Contrato de referência

### 6.1 `FactorKind`

Primeira versão:

- `ativo`;
- `indice`;
- `cambio`.

Não adicionar `commodity` ou `curva_juros` até existir adapter/fonte validado.

### 6.2 `FactorRef`

Modelo interno/público reutilizável:

```
tipo: "ativo" | "indice" | "cambio"
codigo: str
```

Semântica de `codigo`:
- ativo: ticker/alias/nome resolvível pelo mecanismo atual;
- índice: `market.index_definitions.code`, normalizado para lowercase;
- câmbio: par explícito `AAA/BBB`, normalizado para uppercase.

Exemplos:
- `{"tipo":"ativo","codigo":"VALE3"}`
- `{"tipo":"indice","codigo":"ibov"}`
- `{"tipo":"indice","codigo":"selic_meta"}`
- `{"tipo":"cambio","codigo":"USD/BRL"}`

Não aceitar inversão implícita de FX. Se `USD/BRL` não existir e apenas `BRL/USD` existir, a primeira versão falha fechado. Uma série derivada por inversão precisaria de provenance explícita e design próprio.

### 6.3 `ResolvedFactor`

Campos recomendados:

- `ref: FactorRef`;
- `tipo: FactorKind`;
- `codigo: str` canônico;
- `found: bool`;
- `in_universe: bool | None` — só relevante para ativo;
- `instrument_id: str | None`;
- `index_code: str | None`;
- `base_currency: str | None`;
- `quote_currency: str | None`;
- `unit: str | None`;
- `series: ResolvedMarketSeries | None`.

Não duplicar `quality`, `provenance`, `price_basis` ou `temporal_semantics` fora de `ResolvedMarketSeries`.

## 7. Resolver compartilhado

API conceitual:

```
resolve_factor(
    conn,
    ref,
    *,
    de,
    ate,
    cutoff,
    asset_price_basis,
    asset_temporal_semantics,
    include_calendar=True,
) -> ResolvedFactor
```

### Ativo

1. resolver por `instrumento_por_termo`;
2. distinguir desconhecido vs fora do universo;
3. se no universo, carregar por `carregar_serie_resolvida`;
4. usar `asset_price_basis` e temporal semantics coerentes.

### Índice/taxa

1. normalizar code;
2. carregar por `carregar_indice_resolvido`;
3. `UnknownIndex` vira `found=false`;
4. preservar unidade do `index_definitions`;
5. `price_basis=None`;
6. temporal semantics = `observation_date_cutoff`.

### Câmbio

1. parsear `AAA/BBB`;
2. validar duas moedas distintas;
3. usar `fx_pair_exists`;
4. carregar por `load_fx_series`;
5. `price_basis=None`;
6. temporal semantics = `observation_date_cutoff`;
7. preservar warning `fx_observation_date_cutoff_sem_vintage`.

## 8. Limitações temporais que devem continuar explícitas

### Ativos

- `adjusted_close`: `retrospective_as_known_now`;
- `raw_close`: `observation_date_cutoff`.

### Índices/taxas

- cutoff pela data da observação;
- não há garantia geral de vintage contra revisão/backfill.

### FX

- cutoff pela `rate_date`;
- schema atual não possui `availability_date` ou `ingestion_batch_id`;
- não afirmar strict point-in-time.

O resolver não "corrige" essas limitações; apenas as preserva na provenance.

## 9. Transformação para dependência

A nova tool canônica continua usando **somente funções já existentes**.

Para série A (ativo):
- `quant_returns.calculate_returns`.

Para série B:
- `ativo` -> `calculate_returns`;
- `indice` -> `calculate_index_returns`, preservando exatamente a semântica FQ3 atual por unidade;
- `cambio` -> `calculate_returns` sobre o nível cambial.

Depois:
- `quant_dependence.align_returns`;
- `quant_dependence.dependence_estimate`.

Nenhuma fórmula nova.

Importante: para índices de taxa, dependência mantém a semântica histórica de `calculate_index_returns`. Não trocar silenciosamente para mudança de nível apenas porque sensibilidade usa essa transformação.

## 10. Novo contrato público recomendado para `quant.dependencia`

### 10.1 Semver

Recomendação: **`quant.dependencia` 2.0.0**.

Motivo: a interface de entrada muda de:
- `ticker_b` XOR `indice_b`

para:
- `serie_b: FactorRef`.

Adicionar `base_currency`/`quote_currency` ao schema 1.x seria menos disruptivo no curto prazo, mas repetiria o anti-padrão quando entrarem novos fatores. O major version compra um contrato limpo e extensível.

### 10.2 Params propostos

Manter:
- `ticker_a`;
- `janela_dias`;
- `de`;
- `ate`;
- `data_referencia`;
- `price_basis`;
- `metodo`;
- `defasagem_observacoes`.

Substituir:
- `ticker_b`;
- `indice_b`;

por:
- `serie_b: FactorRef`.

Exemplos:

Ativo × ativo:
```
ticker_a="PETR4"
serie_b={"tipo":"ativo","codigo":"VALE3"}
```

Ativo × IBOV:
```
ticker_a="PETR4"
serie_b={"tipo":"indice","codigo":"ibov"}
```

Ativo × USD/BRL:
```
ticker_a="PETR4"
serie_b={"tipo":"cambio","codigo":"USD/BRL"}
```

### 10.3 Por que A continua sendo ticker

Não generalizar os dois lados nesta etapa.

A intenção atual da tool é responder dependência **de um ativo analisado** contra outra série. Permitir fator × fator, curva × FX etc. ampliaria o produto sem necessidade e complicaria quality/provenance.

Se no futuro houver uma pergunta real que exija dependência arbitrária entre fatores, isso recebe design próprio.

## 11. Output recomendado

Preservar o máximo possível do contrato atual:

- `par`;
- `metodo`;
- `coeficiente`;
- `n_pares`;
- `defasagem_observacoes`;
- `price_basis_ativos`;
- `temporal_semantics_ativos`;
- `tipo_b` agora aceita `ativo|indice|cambio`;
- `evidencia`.

Opcionalmente adicionar `codigo_b` se testes de consumo mostrarem necessidade; não é necessário para o primeiro cutover porque `par` e provenance já identificam a série.

Continuar sem enviar pontos alinhados ou séries completas ao LLM.

## 12. Warnings / fail-closed

Mapeamento recomendado:

- ativo desconhecido -> `instrumento_desconhecido`;
- ativo fora do universo -> `fora_da_cobertura`;
- índice desconhecido -> `indice_desconhecido`;
- FX inexistente -> `par_cambio_desconhecido`;
- série constante -> `serie_constante`;
- amostra insuficiente -> coeficiente `None`;
- warnings de provenance/quality sempre propagados.

`as_of` continua sendo a data do último par realmente usado depois de alinhamento/lag.

## 13. Source fingerprint e replay

### 13.1 `quant.dependencia` 1.0.1

Antes do cutover, congelar a implementação atual em um módulo legacy sem decorator:

`dependencia_legacy_1_0_1.py`

Objetivo:
- golden/replay explícito;
- permitir comparação de equivalência;
- não registrar outro código público.

Não alterar `returns.py`, `dependence.py`, `series.py` ou `_comum.py` no cutover, para que o comportamento histórico continue reproduzível.

### 13.2 `quant.dependencia` 2.0.0

Novo fingerprint deve incluir:
- módulo da tool;
- `factor_resolution.py`;
- `market/factors.py`;
- `market/series.py`;
- `analytics/models.py`;
- `analytics/returns.py`;
- `analytics/dependence.py`;
- helpers de resolução efetivamente usados.

Mudança material = major version + novo source SHA.

### 13.3 `quant.dependencia_macro` 1.0.0

Congelar a implementação atual em:
- `dependencia_macro_legacy_1_0_0.py`.

A tool registrada passa a uma versão de compatibilidade:
- semver recomendado: **1.0.1**;
- `exposed_to_llm=False`;
- executável/auditável;
- nenhum planner novo pode escolhê-la.

Ela pode ser um wrapper fino sobre o legacy 1.0.0 para não reabrir matemática.

O histórico 1.0.0 permanece no banco/git e o helper congelado preserva replay/golden.

## 14. Catálogo, planner e compiler

Após o cutover:

Visível:
- `quant.dependencia` 2.0.0.

Oculta:
- `quant.dependencia_macro` 1.0.1;
- `quant.correlacao` legacy;
- outros legacy já existentes.

Planner:
- remover instrução “FX -> `quant.dependencia_macro`”;
- toda dependência usa `quant.dependencia`;
- dólar/real deve virar `serie_b={"tipo":"cambio","codigo":"USD/BRL"}`;
- não chamar dependência quando a intenção for sensibilidade, condição ou regime.

Compiler:
- `exposed_to_llm=False` continua impedindo novos planos com macro legacy.

## 15. Blocos

`_dependencia` já consegue renderizar o núcleo do output canônico.

Objetivo:
- manter um único mapper canônico para novas execuções;
- `_dependencia_macro` pode permanecer apenas para outputs históricos/compatibilidade;
- não criar um bloco novo para cada tipo de fator.

## 16. Testes obrigatórios antes de promoção

### 16.1 Resolver

- ativo exato;
- alias;
- desconhecido;
- fora do universo;
- índice conhecido/desconhecido;
- FX conhecido/desconhecido;
- normalização `usd/brl -> USD/BRL`;
- par inválido;
- moedas iguais;
- cutoff;
- calendar/quality;
- provenance e temporal semantics.

### 16.2 Equivalência numérica

Com fixtures atuais:

- v2 ativo×ativo == v1.0.1 em coeficiente, n, lag e as-of;
- v2 ativo×índice == v1.0.1;
- v2 ativo×FX == macro v1.0.0;
- Pearson e Spearman;
- lag positivo/zero/negativo;
- série constante;
- amostra curta;
- sem dados.

A equivalência deve comparar números e warnings/provenance materialmente relevantes, não apenas “teste passou”.

### 16.3 Replay

- golden de `dependencia_legacy_1_0_1`;
- golden de `dependencia_macro_legacy_1_0_0`;
- versões legacy não registram aliases novos;
- nenhuma execução histórica muda de significado.

### 16.4 Registry/catálogo

- só `quant.dependencia` visível como dependência canônica;
- macro escondida;
- nenhuma `quant.dependencia_fx`, `quant.dependencia_petroleo` etc.;
- semvers esperadas;
- fingerprints das demais tools inalterados.

### 16.5 Planner/evals/blocos

- “PETR4 e VALE3 andam juntas?” -> dependência/ativo;
- “PETR4 e IBOV?” -> dependência/índice;
- “PETR4 e dólar?” -> dependência/câmbio;
- “quanto PETR4 reage a +1 p.p. de Selic?” -> cenário/sensibilidade, não dependência;
- “PETR4 quando Selic sobe?” -> condicional, não dependência;
- mapper único de dependência para nova saída.

### 16.6 Gate real

- migrations do zero PostgreSQL 18;
- invariantes admin + `plexo_service`;
- FQ1/F5/F22/FQ4/FQ5 E2E;
- novos E2E de cutover;
- suíte completa;
- `prompts check`;
- `tools sync --check`.

## 17. Sequência de implementação proposta

### Fase 1 — shadow de infraestrutura
- criar `factor_resolution.py`;
- testes isolados de resolução;
- nenhum catálogo muda.

### Fase 2 — `quant.dependencia` 2.0.0 shadow
- congelar v1.0.1;
- implementar novo contrato com `exposed_to_llm=False`;
- equivalência ativo/índice/FX.

### Fase 3 — cutover atômico
Somente com shadow verde:
- expor `quant.dependencia` 2.0.0;
- ocultar/versionar `quant.dependencia_macro`;
- atualizar planner/evals/blocos/goldens;
- sync real no banco descartável.

### Fase 4 — pós-promoção
- CI completo;
- checkpoint;
- atualizar `.ai/`;
- só depois desbloquear FQ5.5/FQ5.6.

## 18. Migração futura das outras análises

Depois que o resolver estiver provado, cada tool pode migrar **separadamente**, com seu próprio design/semver:

- `quant.sensibilidade`;
- `quant.analise_condicional`;
- `quant.regimes`;
- `quant.cenario_sensibilidade` acompanha a versão canônica de sensibilidade quando necessário.

Não fazer um “big bang” porque essas tools têm transformações distintas e fingerprints publicados.

## 19. Extensão futura

### Commodity/Brent

Só adicionar um novo `FactorKind` depois de:
- fonte/schema definidos;
- prioridade de fonte definida;
- temporal semantics/provenance definidos;
- adapter produzir `ResolvedMarketSeries`.

Depois disso, dependência não ganha uma nova tool; ganha apenas um novo adapter/kind no contrato canônico.

### Yield curve

`market.yield_curve` já existe, mas curva não é automaticamente uma série escalar: é preciso selecionar curve_name + tenor/maturity.

Não encaixar yield curve artificialmente em `codigo` sem design de seleção de tenor. Primeiro criar um adapter explícito que transforme um ponto de curva escolhido em série temporal auditável.

## 20. Critérios de aprovação do design

Antes de implementar, confirmar:
1. aceitar `quant.dependencia` **2.0.0** com `serie_b: {tipo,codigo}`;
2. manter A como ativo nesta versão;
3. manter `quant.dependencia_macro` somente como compatibilidade/replay oculta;
4. não migrar sensibilidade/condicional/regimes no mesmo cutover;
5. não adicionar commodity/yield curve nesta etapa;
6. nenhuma matemática FQ3/FQ4 será modificada.

Até essa aprovação, este documento é design e não autorização de código.


---

## 21. Implementação realizada — 2026-09-30

O design foi aprovado e executado sem mudança de escopo.

- `FactorRef`/`ResolvedFactor` implementados em `factor_resolution.py`;
- `quant.dependencia` promovida para 2.0.0 e pública;
- `quant.dependencia_macro` 1.0.1 mantida oculta para compatibilidade;
- replay 1.0.1/1.0.0 congelado em módulos legacy e goldens;
- equivalência numérica comprovada antes do cutover;
- nenhum engine FQ3/FQ4, migration ou schema alterado.

Commit de código: `60bad205666e5cc5c5d0e2b2b8e643f41e2ac322`.
CI: run #54 `36793672760` success — 87 E2E; 831 passed, 52 skipped, 19 warnings, 0 failed; prompts/tools sync verdes.

Checkpoint: `.ai/checkpoints/2026-09-30_FACTOR_DEPENDENCY_CUTOVER_GREEN.md`.

Estado deste documento: realizado/encerrado. Migrações futuras de sensibilidade, condicional, regimes, commodity ou curva exigem novo gate reuse-before-build.
