# FQ3.2 — `quant.dependencia` canonical tool design

Data: 2026-09-21
Estado: implementado e promovido no cutover FQ3.3; produção pendente dos gates DB/sync.

## Objetivo

Criar a tool canônica de dependência estatística sobre o Quant Core existente, inicialmente em shadow mode.
Ela substitui semanticamente `quant.correlacao` sem duplicar matemática.

## Escopo inicial

A tool mede uma dependência histórica entre:
- ativo A × ativo B; ou
- ativo A × índice/taxa B.

Suporta:
- Pearson;
- Spearman;
- defasagem assinada em **observações comuns**, não em dias corridos.

Não expõe ainda:
- rolling dependence;
- up/down-market;
- partial correlation;
- causalidade/Granger;
- cointegração.

Essas capacidades internas ficam para tools especializadas/FQ4, evitando um schema grande e ambíguo.

## Input canônico

- `ticker_a`: obrigatório;
- exatamente um entre `ticker_b` e `indice_b`;
- `janela_dias` opcional;
- `de` / `ate` opcionais;
- `data_referencia` opcional, com cutoff pela data da observação;
- `price_basis`: default `adjusted_close`; aplica-se aos ativos negociados, não ao índice/taxa;
- `metodo`: `pearson` (default) ou `spearman`;
- `defasagem_observacoes`: inteiro assinado; positivo = A antecede B, negativo = B antecede A.

A semântica temporal dos ativos é derivada da base de preço:
- adjusted -> retrospective_as_known_now;
- raw -> observation_date_cutoff.

Índice/taxa usa observation_date_cutoff do loader e não recebe `price_basis`.

## Output compacto

- `par`;
- `metodo`;
- `coeficiente`;
- `n_pares`;
- `defasagem_observacoes`;
- `price_basis_ativos`;
- `temporal_semantics_ativos`;
- `tipo_b` (`ativo`/`indice`);
- `evidencia`.

Nenhuma série ponto a ponto, ranking ou pares alinhados entra no payload da LLM.

## Qualidade / fail-closed

- correlação indefinida por série constante -> coeficiente `None` + warning `serie_constante`;
- amostra insuficiente -> coeficiente `None`;
- instrumento desconhecido, fora da cobertura e índice desconhecido são distinguíveis;
- provenance das séries de ativo deve ser coerente com `price_basis`/temporal semantics resolvidos;
- warnings dos loaders são preservados;
- lacunas das duas séries são unidas para evidência;
- `as_of` vem do último **par realmente usado** após alinhamento/lag.

## Migração

FQ3.2:
- `quant.dependencia` 1.0.0 nasce com `exposed_to_llm=False`.

FQ3.3 (mesmo ciclo de trabalho, somente após testes shadow verdes):
- expor `quant.risco_retorno` e `quant.dependencia`;
- ocultar `quant.retorno_volatilidade` e `quant.correlacao`;
- planner/evals/blocos passam para códigos canônicos;
- legacy continua registrada/executável para replay/auditoria, mas compiler recusa novos planos legacy.


## Resultado

- shadow `1.0.0` passou os testes do contrato;
- cutover promoveu a tool para `1.0.1` e `exposed_to_llm=True`;
- `quant.correlacao` passou a `1.0.3` e `exposed_to_llm=False`;
- planner/evals/Research usam `quant.dependencia`;
- output continua compacto e rolling/up-down seguem reservados ao FQ4;
- ativação no banco/produção ainda depende de CI/sync.
