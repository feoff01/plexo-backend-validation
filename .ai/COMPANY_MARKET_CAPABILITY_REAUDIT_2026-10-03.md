# Company & Market Analytics — reauditoria pós-FQ5.7

Data: 2026-10-03
Status: **canônico para selecionar a próxima tranche; nenhuma FQ5.8 assumida**

## Estado descontado do audit de 30/09

Lacunas antigas já encerradas e que não devem ser reabertas:
- factor resolver/dependência: `quant.dependencia` 2.0.0 unificada para ativo/índice/FX;
- tendências fundamentais multi-período: `quant.tendencias_fundamentais` 1.0.1;
- peers/setor: `quant.comparaveis_setor` 1.0.1;
- yield curve: foundation + fonte física + `dados.curva_juros` 1.0.1.

## Reuse-before-build sobre lacunas restantes

### Composição/membership/peso de índice
- schema: `market.index_weights` já existe;
- fonte/ingestão: B3 oficial + IBrA 02/10/2026 já GREEN;
- snapshot operacional: 148 componentes, peso total 100%;
- consumer atual: existe apenas ingestão/projeção de universo em `index_portfolios.py`; não há loader client-facing PIT;
- matemática nova: nenhuma;
- gap real: **loader de leitura + contrato compacto**;
- intenção: distinta de `dados.serie_indice`, que lê nível/série do índice.

### Risco histórico avançado
- engine já contém rolling volatility, downside deviation e detalhes de drawdown;
- `quant.risco_retorno` já expõe retorno/vol/max drawdown e episódio;
- gap real: contrato/exposição, não matemática;
- manter como candidata posterior para evolução versionada da tool existente, não criar tool paralela automaticamente.

### Commodity/Brent
- não há fonte/schema/cobertura auditada no estado atual;
- bloqueada em source audit; não criar adapter/tool.

### Fair value / reverse DCF
- exige premissas governadas de forecast/WACC/ERP/growth;
- permanece fora até contrato explícito; não inferir premissas.

### Source priority, vintages, storage e artifacts
- continuam dívidas transversais relevantes;
- não são requisito para a leitura do snapshot oficial de composição de índice, desde que strict PIT use lote succeeded/finished_at e o output seja limitado;
- devem permanecer na fila e virar gate quando uma capability depender deles.

## Próxima tranche selecionada

**Composição oficial de índice**, começando por uma fundação de leitura PIT sobre `market.index_weights`.

Razões:
- maior reuse: schema, source, ingestão, identidade e snapshot já validados;
- zero matemática nova;
- intenção client-facing concreta: “quais ações compõem o índice?”, “qual o peso de X?”, “qual snapshot está disponível?”;
- não depende de Portfolio Analytics nem de dados do cliente;
- permite contrato compacto sem mecanismo de artifacts na v1.

A tranche começa por design + loader shadow. Tool pública só pode ser considerada depois de PostgreSQL 18, payload/provenance e coverage gates.
