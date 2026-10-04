# Checkpoint — FQ5.6B comparação de peers shadow GREEN

Data: 2026-10-01
Estado: GREEN em shadow; não pública.

Tool:
- quant.comparaveis_setor 1.0.0
- exposed_to_llm=false
- default subsetor; setor opt-in; segmento não suportado neste XLSX B3.

Reuso:
- app.market.sectors.peer_issuers
- quant.valor_mercado
- quant.tendencias_fundamentais
- app.market.analytics.statistics.describe

Contrato:
- company-level por issuer;
- multi-classe deduplicada;
- target excluído;
- distribuição usa todos os peers válidos;
- missing reduz n_valid;
- exemplos são apenas compactos/alfabéticos;
- sem ranking, score, recomendação ou fair value.

CI:
- commit final de código/teste: 8acb3affa0d030bfad93443d985a69742031cf96
- run #93 / 36950608900: success
- gate: 118 passed
- full suite: 876 passed, 52 skipped, 19 warnings, 0 failed
- PostgreSQL 18, invariantes, prompts check e tools sync verdes.

Run #92 falhou apenas por file_hash sintético não hexadecimal no fixture; a correção não mudou lógica de domínio.

Registry:
- 35 tools totais;
- única adição: quant.comparaveis_setor shadow;
- nenhuma tool anterior teve semver/exposição alterados.

Bloqueios para promoção:
1. coverage real do XLSX B3 contra catálogo Plexo;
2. benchmark de performance real da composição por peer;
3. revisar tamanho de resolved params/payload;
4. planner/blocos/golden somente após decisão de promoção.
