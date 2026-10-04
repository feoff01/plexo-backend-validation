# Brent spot — auditoria de fonte EIA

Data: 2026-10-03
Estado: **fonte candidata tecnicamente identificada; gate físico/licença específico ainda pendente**
Capability futura: fator commodity para Company & Market Analytics
Não é futures/ICE.

## 1. Fonte candidata
Publisher: **U.S. Energy Information Administration (EIA)**.

Série pública:
- nome: `Europe Brent Spot Price FOB (Dollars per Barrel)`;
- código/series facet: `RBRTE`;
- periodicidade disponível: diária;
- unidade: dólares por barril;
- histórico público observado: desde maio de 1987;
- rota API v2 documentada: `/v2/petroleum/pri/spt/data/` com facet `series=RBRTE`.

Evidência pública consultada em 2026-10-03:
- https://www.eia.gov/opendata/browser/petroleum/pri/spt?data=value&facets=series&frequency=daily&series=RBRTE%3B
- https://www.eia.gov/dnav/pet/hist/RBRTED.htm
- https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm
- https://www.eia.gov/opendata/documentation.php
- https://www.eia.gov/opendata/bulk-downloads.php

A página diária observada em 03/10/2026 mostrava valores recentes até 29/09/2026 e release date 30/09/2026; portanto não tratar a série como real-time.

## 2. Transporte
### API v2
A documentação EIA exige API key individual gratuita.
Não ler, pedir, versionar ou logar segredo no repo.

### Bulk
A EIA declara que bulk download não exige API key e publica o dataset Petroleum.
Candidato de transporte físico para CI/source gate:
- dataset bulk PET;
- série histórica conhecida no ecossistema legado como `PET.RBRTE.D`.

O adapter de domínio deve receber bytes/records; HTTP/transporte deve ficar separado do parser e da ingestão.

## 3. Semântica econômica
Esta capability representa **Brent spot europeu FOB em USD/barril**.

Não representa:
- contrato futuro ICE Brent;
- front-month futures;
- curva de futuros;
- roll yield;
- contango/backwardation;
- crack spread;
- preço realizado da Petrobras;
- forecast de petróleo.

Pergunta genérica "Brent" só poderá ser roteada para esta série se o output/planner rotular explicitamente "Brent spot Europe FOB (EIA)".

## 4. Provenance/licença — gate obrigatório
A EIA informa em materiais próprios que a série Brent spot é publicada pela EIA com dados baseados em Thomson Reuters.

Regras públicas consultadas:
- API Terms permitem desenvolver serviços para buscar/exibir/analisar dados EIA e exigem atribuição;
- Copyright & Reuse diz que conteúdo EIA em geral pode ser usado/distribuído, mas materiais contribuídos/licenciados por terceiros podem ter proteção própria;
- Information Quality orienta usuários a considerar a fonte inicial de informação externa disseminada pela EIA.

Portanto:
- **não declarar licença totalmente GREEN ainda**;
- antes de persistência/redistribuição de produção, capturar no payload/metadata oficial da série o campo de copyright/licença aplicável e registrar decisão explícita;
- se o metadata específico restringir redistribuição, procurar fonte alternativa oficial ou limitar uso conforme permitido.

Referências:
- https://www.eia.gov/opendata/terms-of-service.php
- https://www.eia.gov/about/copyrights_reuse.php
- https://www.eia.gov/about/information_quality_guidelines.php
- https://www.eia.gov/todayinenergy/detail.php?id=66944

## 5. Gate físico
Ainda não foi congelado no repo um payload EIA machine-readable da série.

Antes de código de ingestão:
1. materializar via source oficial, preferencialmente bulk Petroleum sem segredo ou API v2 autorizada;
2. registrar SHA-256;
3. confirmar series id, frequency, units, first/latest observation e copyright;
4. congelar fixture mínima real;
5. escrever parser fail-closed contra o formato real;
6. medir coverage e revisões observadas.

Não usar:
- scraping HTML de produção;
- FRED como fonte canônica quando a EIA first-party está disponível;
- Yahoo/Stooq/Investing/vendor não auditado;
- futures como substituto silencioso do spot.

## 6. Resultado
**Source identity: GREEN.**
**Physical payload: PENDENTE.**
**Dataset-specific copyright/licensing: PENDENTE.**
**Implementação de produto: BLOQUEADA até esses dois gates.**
