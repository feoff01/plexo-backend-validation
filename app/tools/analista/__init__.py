"""Tools do Analista (F5) — famílias `dados` (séries e resolução de instrumento) e `quant` (métricas).

Contrato comum (`_comum.Evidencia`, presente em TODO output): fonte, instrumentos/índices lidos,
`cutoff_date` (limite pela data da observação — nada datado depois dele entra; não implica vintage PIT), `as_of` (último dado usado), `n_observacoes`,
`lacunas` (pregões sem preço), método e nota de método, `suficiente` + `avisos`, `metricas`.
Dado insuficiente NÃO é exceção: a tool devolve `suficiente=false`; o turno grava evidência `missing`
e o Analista diz que não há base. RCVM 20: fatos, séries e métricas — nunca tese nem previsão.
Um módulo por tool (convenção 13); toda premissa numérica vem de `ANALISE_PARAMS`.
"""
