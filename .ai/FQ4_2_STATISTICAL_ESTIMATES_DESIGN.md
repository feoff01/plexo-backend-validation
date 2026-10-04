# FQ4.2 Foundation — Structured Statistical Estimates

Data: 2026-09-21
Estado: design congelado antes do código

## Objetivo

Preparar o contrato interno necessário para `quant.sensibilidade` e futuras análises inferenciais sem alargar indiscriminadamente `Evidencia.metricas` e sem quebrar os outputs/goldens das tools atuais.

## Problema atual

`Evidencia.metricas` é `dict[str, float | None]`. Isso é suficiente para métricas escalares simples, mas insuficiente para uma estimativa inferencial que precisa transportar, de forma auditável:

- estimativa pontual;
- unidade;
- tamanho da amostra;
- erro-padrão;
- intervalo de confiança e nível;
- método;
- warnings específicos da estimativa.

Transformar `metricas` em `Any` seria perda de contrato. Adicionar `estimativas={}` diretamente ao `Evidencia` base alteraria o JSON serializado de todas as tools existentes e quebraria goldens/replay sem necessidade.

## Decisão

### 1. `MetricEstimate` é contrato interno isolado do Quant Core

Em `app/market/analytics/estimates.py`:

- `ConfidenceInterval`
  - `lower`;
  - `upper`;
  - `level` em `(0, 1)`;
  - `method` opcional, quando o método do intervalo difere do estimador.

- `MetricEstimate`
  - `estimate: float | None`;
  - `unit: str`;
  - `n: int`;
  - `standard_error: float | None`;
  - `confidence_interval: ConfidenceInterval | None`;
  - `method: str`;
  - `warnings: tuple[str, ...]`.

Todos os números são finitos; `standard_error >= 0`; modelos são frozen e `extra=forbid`. O arquivo é separado de `models.py` para não alterar fingerprints de tools existentes que dependem daquele módulo sem mudança matemática.

Se `estimate is None`, erro-padrão e intervalo também devem ser `None`. A ausência de uma estimativa deve ser explicada por warning/método da tool, não convertida em zero/NaN.

### 2. Unidade permanece explícita, mas não como enum fechado nesta fase

Sensibilidade pode produzir unidades compostas como `pct_return_per_percentage_point`. Um enum prematuro forçaria conversões artificiais. O contrato exige string não vazia e a futura tool terá um conjunto versionado de unidades aceitas.

### 3. Não alterar `Evidencia` base

Criar `EvidenciaEstatistica(Evidencia)` em `app/tools/analista/evidencia_estatistica.py` com:

`estimativas: dict[str, MetricEstimate]`

Somente tools inferenciais usam essa subclasse. O arquivo fica separado de `_comum.py` porque `_comum.py` participa do fingerprint de várias tools atuais; assim outputs/goldens e source hashes legacy não mudam por uma capacidade futura.

### 4. Findings carregam estimativas quando presentes

`app/agents/analysis.py` deve incluir `estimativas` no finding `quantitative` apenas quando a evidência possuir esse campo e ele não estiver vazio.

Isso mantém retrocompatibilidade dos findings atuais e prepara Research para consumir coeficiente/SE/CI sem parsear texto.

### 5. Ainda não implementar regressão

Esta etapa NÃO escolhe OLS/HC1/Newey-West, não calcula p-value e não cria `quant.sensibilidade`. Ela congela somente o envelope de resultado necessário para que a regressão futura nasça sobre um contrato estável.

## Invariantes

- nenhum `NaN`/`inf`;
- intervalo precisa ter `lower <= upper`;
- nível precisa estar estritamente entre 0 e 1;
- erro-padrão não pode ser negativo;
- estimate ausente implica SE/CI ausentes;
- `Evidencia` legacy serializa exatamente sem `estimativas`;
- `EvidenciaEstatistica` serializa estimativas de forma JSON-safe;
- finding quantitativo só adiciona `estimativas` quando o campo existir e estiver preenchido.

## Próximo passo após este contrato

Desenhar o Regression/Sensitivity Engine: variável resposta, transformação da condicionante, unidade do coeficiente, método de erro-padrão, amostra mínima e intervalo de confiança.
