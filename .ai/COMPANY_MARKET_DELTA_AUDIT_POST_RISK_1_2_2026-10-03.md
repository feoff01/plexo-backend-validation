# Company & Market Analytics — delta-audit pós quant.risco_retorno 1.2.0

Data: 2026-10-03
Estado: **audit concluído; próxima tranche selecionada para design**
Base funcional: `quant.risco_retorno` 1.2.0 pública/GREEN
HEAD validado: `bf16dfd561f97e136060d77d80f50092cdc4538d`
Run: #341 / `37162973757` — success

## 1. Capacidades descontadas
Não reabrir:
- FQ0.5–FQ4;
- factor/dependence unificado para ativo/índice/FX;
- fundamentos, valor de mercado/múltiplos, cenários mecânicos;
- tendências fundamentais;
- comparáveis/setor;
- curva ANBIMA;
- composição oficial de índice;
- risco histórico agregado/downside/drawdown;
- evolução rolling de volatilidade em `quant.risco_retorno` 1.2.0.

## 2. Lacunas remanescentes

### A. Brent / commodities
Classificação corrigida: **fonte + schema/fundação de série + loader/factor contract**.

Reuse existente:
- `ResolvedMarketSeries`;
- Returns Core para níveis positivos;
- `factor_resolution` como padrão de identidade/resolução;
- `quant.dependencia`, `quant.sensibilidade`, `quant.regimes`, `quant.analise_condicional` e cenário reutilizam séries/fatores e matemática já existente.

Gap real:
- `FactorKind` público só aceita `ativo|indice|cambio`;
- `market.index_definitions.unit` só suporta taxa/pontos/percentual e não representa honestamente USD/barril;
- não há source `eia`, tabela commodity, ingestão ou loader commodity;
- não há physical source fixture congelada no repo.

Conclusão: **não criar uma tool por commodity**. Primeiro fechar uma fundação de série Brent; depois integrar ao factor resolver e versionar somente as capabilities que realmente precisarem do novo tipo.

### B. Fair value / reverse DCF
Classificação: **nova matemática contratual + governança de premissas + composição determinística**.

O core atual `analytics/valuation.py` explicitamente não produz intrinsic/fair value e rejeita `intrinsic_value_produced=true`.
Ainda faltam:
- contrato de forecast;
- WACC/cost of equity/debt;
- ERP/risk-free/beta ou alternativa governada;
- crescimento terminal;
- regras de perpetuidade/múltiplo terminal;
- sensibilidade e provenance de premissas.

Continua bloqueada. Não inferir defaults.

### C. Histórico B3 de setor/membership
Classificação: **fonte histórica + loader temporal**.
Snapshots correntes oficiais não autorizam retrodatação.

### D. Source priority/conflicts + vintages
Classificação: **infra transversal**.
Continua gate sob demanda; não abrir como tool.

### E. Storage/artifacts/deploy
Classificação: **ops/infra**, não capability analítica.

## 3. Próxima tranche selecionada
**Brent spot / EIA — source + factor foundation**, ainda sem nova tool pública.

Motivos:
1. existe intenção concreta de Company & Market Analytics: relação de empresa/ativo com petróleo Brent;
2. a matemática de retorno/dependência/sensibilidade/regimes já existe;
3. fair value exigiria simultaneamente matemática nova e várias premissas governadas;
4. a próxima incerteza de Brent é isolável e testável: fonte física, unidade, provenance, storage e loader;
5. preserva a regra "não criar tool por fonte".

## 4. Gate imediato
1. congelar source audit EIA;
2. congelar design da fundação commodity/Brent;
3. **não implementar** antes de materializar payload machine-readable oficial e copyright/provenance da série;
4. depois implementar somente source/schema/loader shadow;
5. PostgreSQL 18 + strict PIT/quality/provenance;
6. só então desenhar cutover de `FactorRef(tipo="commodity")` e tools consumidoras.

Fair value não entra em paralelo.
