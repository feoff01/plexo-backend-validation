# Checkpoint — FQ5.7 official source + shadow capability

Data: 2026-10-03
Estado: **SOURCE GATE GREEN / parser+fixture frozen / first capability em shadow**

## Fonte oficial
- ANBIMA first-party `CZ-down.asp` materializada via runner do repositório autorizado;
- CSV `CurvaZero_.csv`;
- 2.899 bytes;
- SHA-256 `a254ebf789b41cb83838d9b0df29c4d094f1a4c37ddf0f1400d94637267af1f7`;
- referência 02/10/2026;
- 65 vértices IPCA; 19 PRE; 19 inflação implícita.

## Implementação
- fixture física congelada sem reencodificação;
- parser `app/market/anbima_yield_curve_source.py` fail-closed;
- `dados.curva_juros` 1.0.0 criada em shadow (`exposed_to_llm=False`);
- composição exclusiva sobre `load_yield_curve()`;
- sem interpolation/extrapolation/slope/forecast/choque.

## Cobertura histórica
- superfície pública: últimos cinco dias úteis;
- API oficial: consulta por `data=AAAA-MM-DD`, sujeita ao acesso autorizado;
- produto não assume histórico ilimitado.

## Próximo gate
Executar PostgreSQL 18 + testes específicos + suíte completa + prompts/tools sync. Somente após GREEN revisar promoção pública da tool.
