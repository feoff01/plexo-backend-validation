# Auditoria dos arquivos Economatica fornecidos pelo usuário

Data: 2026-10-01  
Estado: **fonte auxiliar útil; não promovida a fonte canônica de produção**

## Arquivos auditados

1. `economatica com ativos cancelados.zip`
   - 17 workbooks anuais de 2009 a 2025;
   - workbook 2025 com 175 colunas;
   - contém cadastro/status, `Código`, `Setor Econômico Bovespa`, `Subsetor Bovespa`, `Setor Economatica` e diversas métricas financeiras/valuation.

2. `arquivos economaticas preços.zip`
   - 17 workbooks anuais de 2009 a 2025;
   - preços mensais ajustados por proventos em moeda original;
   - contém ativos ativos/cancelados e códigos de negociação.

Os arquivos brutos não serão commitados no repositório nem redistribuídos.

## O que os dados ajudam a resolver

### 1. Cobertura atual de setor/subsetor
No workbook 2025 foram observadas 1.419 linhas Bovespa/B3 de ações:
- 478 marcadas como ativas;
- 478/478 com Setor Econômico Bovespa;
- 478/478 com Subsetor Bovespa;
- 941 marcadas como canceladas;
- 358/941 canceladas com setor/subsetor preenchido.

Isto indica boa utilidade como fonte auxiliar para:
- validação de cobertura corrente;
- conferência de classificação por ticker;
- apoio a investigações de instrumentos cancelados.

### 2. Fundamentais e múltiplos
O export contém, entre outros:
- ativo total;
- patrimônio líquido;
- receita;
- lucro bruto;
- EBIT;
- lucro líquido;
- EBITDA;
- dívida líquida/bruta;
- margens;
- ROIC;
- CAPEX;
- FCL/FCLF;
- P/L;
- P/VPA;
- EV;
- EV/EBITDA;
- dividend yield;
- beta;
- volatilidade;
- Sharpe;
- market cap.

Isso é útil para **validação cruzada** de resultados calculados pelo Plexo.

Não usar esses campos como substituto automático da fonte canônica CVM/B3, porque:
- várias métricas são calculadas pelo fornecedor;
- definições podem divergir das fórmulas canônicas do Plexo;
- o export não carrega o mesmo provenance/vintage PIT de `market.fundamentals`.

### 3. Preços
O segundo ZIP oferece preços mensais ajustados e inclui ativos cancelados. Pode ser útil no futuro como:
- fonte auxiliar para validação histórica;
- investigação de instrumentos deslistados.

Não deve ser ingerido agora em `market.prices` porque:
- a frequência é mensal, enquanto o contrato canônico é fechamento diário;
- o ajuste por proventos é do fornecedor e não é necessariamente idêntico ao `v_precos_ajustados` do Plexo;
- introduzir segunda fonte de preço exige primeiro policy explícita de prioridade/conflitos.

## Achado temporal crítico

Os workbooks anuais não são snapshots históricos de cadastro/setor.

Evidência:
- 2009 e 2025 têm exatamente 1.419 linhas Bovespa/B3;
- o workbook 2009 contém códigos modernos como `TTEN3`, que não existiam como listados em 2009;
- portanto o ano do arquivo governa os dados financeiros/preços, mas os metadados de cadastro/setor parecem refletir o cadastro disponível na exportação.

Consequência:
- **é proibido** gravar a classificação do arquivo 2009 como `reference_date=2009`;
- isso introduziria look-ahead;
- a classificação Economatica pode ser tratada, no máximo, como snapshot conhecido na data de ingestão/exportação.

## Campos ausentes para o contrato B3 atual

Não foram encontrados no workbook auditado:
- CNPJ do emissor;
- segmento B3 detalhado equivalente ao `segment` de `market.sector_classification`;
- data efetiva/vintage da classificação.

Portanto esses arquivos **não substituem** o SummaryData oficial da B3 para o pipeline strict PIT desenhado em FQ5.6A.

## Identidade possível

Economatica fornece ticker/código exato. Uma integração futura específica para Economatica poderia resolver:
`ticker exato -> market.instruments.id -> issuer_id`.

Regras se essa integração vier a ser aprovada:
- somente match exato;
- nunca remover `-old` silenciosamente;
- nunca fuzzy/root-code;
- instrumentos não encontrados ficam em relatório de cobertura;
- source_code próprio (`economatica` ou equivalente), nunca `b3`.

## Decisão

Economatica passa a ser classificada no projeto como **fonte auxiliar de validação**, não como substituta da fonte oficial B3/CVM.

Permitido agora:
- usar para auditoria de cobertura;
- comparar números calculados pelo Plexo;
- ajudar a identificar gaps de instrumentos cancelados;
- desenhar uma futura integração explicitamente versionada.

Bloqueado agora:
- gravar dados Economatica como `source_code='b3'`;
- usar classificação dos arquivos anuais como histórico PIT;
- misturar preços Economatica e B3 sem source-priority policy;
- substituir fundamentos CVM PIT por métricas vendor-derived;
- liberar FQ5.6B com default `segmento` apenas com estes arquivos.

## Próximo passo recomendado

1. manter B3/UP2DATA como fonte canônica desejada para setor/segmento strict PIT;
2. usar Economatica como validação auxiliar enquanto o feed B3 não é materializado;
3. antes de qualquer ingestão Economatica em produção, criar design de source policy limitado à classificação setorial:
   - source_code próprio;
   - semântica `known_at_ingestion`;
   - match por ticker exato;
   - B3 preferida quando disponível;
   - sem retrodatação;
4. não abrir uma policy multi-source global de preços/fundamentos apenas por causa deste dataset.
