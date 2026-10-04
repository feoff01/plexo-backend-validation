# Checkpoint — Design de consolidação de fatores/dependência

Data: 2026-09-30  
Estado: design concluído; implementação não iniciada.

## Documento canônico
`.ai/FACTOR_DEPENDENCY_CONSOLIDATION_DESIGN.md`

## Resultado do design
- resolução de fonte será separada da transformação estatística;
- nova abstração proposta: `FactorRef` + `ResolvedFactor`;
- primeira cobertura: ativo, índice/taxa e FX;
- `quant.dependencia` recomendada para 2.0.0 com `serie_b={tipo,codigo}`;
- `quant.dependencia_macro` recomendada para compatibilidade oculta, preservando v1.0.0 para replay;
- FQ3/FQ4 Quant Core permanece intacto;
- sem migration/tabela nova;
- sensibilidade/condicional/regimes ficam fora do primeiro cutover;
- commodity/Brent e yield curve ficam fora até seus adapters/fontes terem contrato próprio.

## Estado
Nenhum arquivo de código, SQL, migration, prompt ou tool foi alterado nesta etapa.

Próxima ação: revisar/aprovar o design antes de qualquer implementação.
