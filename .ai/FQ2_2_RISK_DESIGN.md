# FQ2.2 — Risk Engine Design

Status: contrato pré-implementação.
Data: 2026-09-21.

## Escopo

Entram:
- volatilidade anualizada;
- rolling volatility;
- downside deviation e versão anualizada;
- série de drawdown;
- maximum drawdown;
- episódio de maximum drawdown;
- duração até o fundo e até recuperação.

Não entram:
- Sharpe/Sortino/Calmar;
- VaR/Expected Shortfall;
- beta/correlação;
- policy/gates;
- I/O de mercado.

## Contratos

### Volatilidade
- input: retornos finitos;
- amostra com <2 retornos: `None`;
- desvio amostral (`n-1`), preservando legado;
- anualização exige `periods_per_year > 0` explícito.

### Rolling volatility
- input: `ReturnObservation` em datas estritamente crescentes;
- `window >= 2`;
- cada valor é a volatilidade anualizada da janela terminando naquela data;
- se há menos observações que a janela, retorna lista vazia;
- nenhuma interpolação/preenchimento.

### Downside deviation
Definição por período:
`sqrt(mean(min(r_i - target, 0)^2))` sobre TODAS as observações.

Consequências deliberadas:
- amostra vazia: `None`;
- série sem shortfall: `0.0`;
- uma observação já é suficiente para a métrica;
- target precisa estar na mesma convenção/período dos retornos;
- anualização multiplica por `sqrt(periods_per_year)`.

### Drawdown
- níveis devem ser positivos, finitos, datas estritamente crescentes;
- drawdown em t = `price_t / running_peak_t - 1`;
- primeiro ponto e novos picos têm drawdown `0`;
- drawdowns nunca são positivos;
- série vazia => drawdown vazio; maximum drawdown `None`;
- série não vazia sem queda => maximum drawdown `0.0` e nenhum episódio material.

### Episódio de maximum drawdown
Campos:
- `peak_date` / `peak_value`;
- `trough_date` / `trough_value`;
- `recovery_date` / `recovery_value` opcional;
- `depth` <= 0;
- `time_to_trough_intervals`: número de intervalos entre observações pico→fundo;
- `recovery_intervals`: número de intervalos observados fundo→recuperação, ou `None` se ainda não recuperou;
- `duration_intervals`: pico→recuperação; se não recuperado, pico→última observação do recorte;
- `recovered`: booleano.

A duração é em observações, não dias corridos, para não inventar calendário dentro do engine. Conversão para dias/pregões pertence à camada que possui calendário.

## Compatibilidade legacy

`quant.retorno_volatilidade` deverá migrar:
- volatilidade -> `annualized_volatility`;
- maximum drawdown -> `maximum_drawdown`.

O output/golden da tool deve permanecer idêntico neste bloco.

## Testes obrigatórios
- série crescente => max DD 0;
- queda e recuperação conhecida;
- queda sem recuperação;
- dois episódios: seleciona o mais profundo;
- empate de profundidade: regra determinística documentada/testada;
- scaling de preço não altera drawdown;
- drawdown sempre <= 0;
- rolling vol usa janela correta e data final;
- vol constante = 0;
- downside sem shortfall = 0;
- NaN/inf/datas duplicadas falham fechado;
- equivalência bit-a-bit/approx com legado onde aplicável.
