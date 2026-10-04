# Company & Market Analytics — rolling volatility em quant.risco_retorno

Data: 2026-10-03
Estado: **PROMOVIDO / GREEN**
Capability canônica: `quant.risco_retorno`
Versão pública atual: **1.2.0**
Versão-alvo eventual: **1.2.0 — encerrada**

## 1. Intenção
Permitir que a mesma capability responda perguntas históricas como:
- "como a volatilidade evoluiu ao longo do período?";
- "o risco recente está maior ou menor que no início?";
- "qual foi a faixa de volatilidade móvel observada?".

A resposta continua descritiva e histórica. Não é forecast, sinal, recomendação, stress test, VaR/ES ou análise de carteira.

## 2. Reuse-before-build
Reutilizar obrigatoriamente:
- `preparar_risco_retorno()` e `RiscoRetornoResolvido`;
- `quant_returns.calculate_returns()`;
- `quant_risk.rolling_volatility()`;
- `amostrar_mensal()`;
- métricas, warnings, temporal semantics e provenance já produzidos por `quant.risco_retorno` 1.1.0.

Nenhuma matemática financeira nova é autorizada.

## 3. Estratégia de shadow
O shadow será **interno e não registrado**.
Durante shadow:
- `quant.risco_retorno` 1.1.0 permanece pública, sem semver/exposure/fingerprint drift;
- o candidato recebe a preparação canônica e compõe somente campos adicionais;
- nenhuma nova tool/alias é registrada;
- planner, bloco e policy pública não mudam;
- a janela rolling deve ser explícita no teste/shadow.

Somente após shadow + PostgreSQL/payload/provenance/readiness GREEN será permitido congelar replay 1.1.0 e considerar cutover 1.2.0.

## 4. Contrato-alvo 1.2.0
Preservar todos os parâmetros existentes.

Adicionar:
- `incluir_evolucao_volatilidade: bool = false`;
- `janela_volatilidade_observacoes: int | None`, mínimo 2.

Regras:
- se evolução=false, a janela deve ser omitida; não ignorar parâmetro silenciosamente;
- se evolução=true e a janela for informada, usar exatamente o valor fornecido;
- se evolução=true e a janela for omitida, somente a versão pública futura poderá ler um default governado em `ANALISE_PARAMS.risco_janela_movel_observacoes`;
- o valor concreto dessa policy **não é congelado neste design**;
- o shadow não terá fallback numérico escondido.

## 5. Output adicional
Adicionar objeto opcional `evolucao_volatilidade` com:
- `janela_observacoes`;
- `n_janelas_total`;
- `primeira_data`;
- `ultima_data`;
- `vol_inicio_pct`;
- `vol_fim_pct`;
- `vol_min_pct` + `vol_min_data`;
- `vol_max_pct` + `vol_max_data`;
- `pontos`;
- `amostrado`.

Cada ponto:
- `data`;
- `vol_anualizada_pct`.

As métricas 1.1.0 permanecem intactas e numericamente equivalentes.

## 6. Compactação determinística
A série rolling completa é usada para resumo/min/max/início/fim.
Para o payload:
1. calcular rolling completo;
2. manter o último ponto de cada mês via `amostrar_mensal()`;
3. se ainda houver mais de **60** pontos, escolher 60 posições aproximadamente equidistantes por índice, preservando primeiro e último;
4. marcar `amostrado=true` se qualquer redução ocorrer;
5. nunca recalcular métricas sobre a amostra exibida.

O limite 60 é estrutural de payload, não premissa financeira. A promoção continua condicionada ao gate real de **<5 KB**.

## 7. Suficiência e warnings
- `window < 2`: validação de schema;
- retornos insuficientes: `evolucao_volatilidade=None`, sem padding/interpolação;
- warning candidato: `janela_volatilidade_insuficiente`;
- compactação: warning candidato `serie_risco_amostrada`;
- adjusted close continua `retrospective_as_known_now`;
- raw close continua `observation_date_cutoff`.

## 8. Policy
Somente no cutover 1.2.0:
- adicionar/aprovar `ANALISE_PARAMS.risco_janela_movel_observacoes`;
- unidade = número de observações de retorno;
- não confundir com dias corridos;
- não criar fallback em código.

## 9. Semver, replay e fingerprint
Target eventual: **1.2.0**, por parâmetros/campos públicos aditivos.
Antes do cutover:
- registrar fingerprint atual da 1.1.0;
- provar que shadow não altera registry/source dependencies;
- congelar golden/replay 1.1.0;
- preservar números de retorno, volatilidade agregada, downside deviation, max drawdown e duração/recovery.

Não registrar `quant.risco_historico`, `quant.rolling_volatility` ou alias equivalente.

## 10. Planner e bloco — somente no cutover
Planner:
- risco/retorno agregado continua sem evolução;
- perguntas de evolução temporal ativam `incluir_evolucao_volatilidade=true`;
- janela explícita do usuário prevalece;
- sem janela explícita, somente policy governada.

Bloco:
- preservar indicadores atuais;
- adicionar uma única série temporal de volatilidade rolling;
- rotular janela em observações;
- não inferir tendência futura, regime, atratividade ou recomendação.

## 11. Gates do shadow
Antes de qualquer alteração pública:
- unit tests de rolling, insuficiência e compactação;
- equivalência exata das métricas 1.1.0;
- registry/catálogo inalterado;
- semver/exposure/fingerprint 1.1.0 inalterados;
- adjusted/raw semantics preservadas;
- PostgreSQL 18 com preparação real;
- payload representativo;
- provenance/readiness;
- nenhum planner/bloco/policy novo.

## 12. Gates de promoção
Depois do shadow GREEN:
- replay/golden 1.1.0 congelado;
- policy aprovada;
- cutover único 1.2.0;
- planner + bloco + evals;
- payload <5 KB;
- PostgreSQL 18 / directed gate;
- suíte completa;
- prompts check;
- tools sync --check;
- checkpoint GREEN;
- atualização integral de `.ai/`.

## 13. Próximo passo permitido
Implementar **somente o shadow interno não registrado + testes de equivalência**.
Não fazer cutover 1.2.0, policy pública ou promoção na mesma tranche.

## 14. Resultado final / override

As seções de shadow e próximo passo acima registram o fluxo histórico e estão supersedidas por este resultado.

- policy congelada: `risco_janela_movel_observacoes=21`;
- replay 1.1.0 preservado em módulo legacy + golden;
- cutover canônico para 1.2.0 concluído;
- planner/bloco/evals concluídos;
- run #334 / `37162747600` GREEN;
- directed 186;
- full 929/53/19/0;
- prompts/tools sync GREEN;
- catálogo 37/34/3.

Checkpoint: `.ai/checkpoints/2026-10-03_RISK_ROLLING_1_2_GREEN.md`.
