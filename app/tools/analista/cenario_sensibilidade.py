"""Cenário linear de preço a partir da sensibilidade histórica canônica (FQ5.3)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.market import snapshots as market_snapshots
from app.market.analytics import scenario as scenario_engine
from app.market.series import PriceBasis
from app.tools.analista import sensibilidade as sens_tool
from app.tools.analista.evidencia_estatistica import EvidenciaEstatistica
from app.tools.executor import ToolContext
from app.tools.registry import tool


BASE_PRICE_UNAVAILABLE = "preco_base_indisponivel"
SCENARIO_NOT_FORECAST = "cenario_associacional_nao_previsao"


class CenarioSensibilidadeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, description="Ativo cujo preço de cenário será calculado.")
    choque_driver: float = Field(
        allow_inf_nan=False,
        description=(
            "Choque explícito na unidade do driver: p.p. para taxa/percentual; % de retorno para ativo/índice em pontos."
        ),
    )
    ticker_driver: str | None = Field(
        default=None,
        description="Ativo usado como driver. Use exatamente um entre ticker_driver e indice_driver.",
    )
    indice_driver: str | None = Field(
        default=None,
        description="Índice/taxa usado como driver, por exemplo selic_meta, cdi ou índice em pontos.",
    )
    janela_dias: int | None = Field(default=None, ge=1)
    de: date | None = None
    ate: date | None = None
    data_referencia: date | None = None
    price_basis: PriceBasis = Field(
        default=PriceBasis.ADJUSTED_CLOSE,
        description="Base usada para estimar a sensibilidade histórica; o preço-base do cenário é sempre raw_close.",
    )

    @model_validator(mode="after")
    def _um_driver(self):
        if (self.ticker_driver is None) == (self.indice_driver is None):
            raise ValueError("informe exatamente um: ticker_driver ou indice_driver")
        return self


class CenarioSensibilidadeResolvida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choque_driver: float = Field(allow_inf_nan=False)
    sensibilidade: sens_tool.SensibilidadeResolvida
    base_price: market_snapshots.MarketPriceSnapshot | None = None


class ScenarioRangeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lower: float
    upper: float


class CenarioSensibilidadeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    driver: str
    choque_driver: float
    unidade_choque: sens_tool.DriverVariationUnit
    base_price_brl: float | None = None
    base_price_date: date | None = None
    impacto_incremental_pct: float | None = None
    impacto_intervalo_pct: ScenarioRangeOutput | None = None
    scenario_price_brl: float | None = None
    scenario_price_interval_brl: ScenarioRangeOutput | None = None
    sensibilidade: float | None = None
    r_squared: float | None = None
    n: int = 0
    evidencia: EvidenciaEstatistica


async def preparar_cenario_sensibilidade(
    params: CenarioSensibilidadeParams,
    ctx: ToolContext,
) -> CenarioSensibilidadeResolvida:
    sens_params = sens_tool.SensibilidadeParams(
        ticker=params.ticker,
        ticker_driver=params.ticker_driver,
        indice_driver=params.indice_driver,
        janela_dias=params.janela_dias,
        de=params.de,
        ate=params.ate,
        data_referencia=params.data_referencia,
        price_basis=params.price_basis,
    )
    resolved = await sens_tool.preparar_sensibilidade(sens_params, ctx)
    base_price = None
    if resolved.instrument_id is not None and resolved.response_in_universe:
        base_price = await market_snapshots.read_latest_raw_price(
            ctx.conn,
            resolved.instrument_id,
            cutoff=resolved.cutoff_date,
        )
    ctx.registrar_insumo(
        "market.scenario_base_price",
        ticker=resolved.ticker,
        cutoff=resolved.cutoff_date.isoformat(),
        price_basis="raw_close",
        price_date=base_price.price_date.isoformat() if base_price is not None else None,
        source_codes=base_price.source_codes if base_price is not None else [],
    )
    return CenarioSensibilidadeResolvida(
        choque_driver=params.choque_driver,
        sensibilidade=resolved,
        base_price=base_price,
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


@tool(
    code="quant.cenario_sensibilidade",
    family="quant",
    semver="1.0.0",
    display_name="Cenário por sensibilidade histórica",
    description=(
        "Aplica um choque explícito à sensibilidade histórica OLS/HAC e calcula o impacto incremental e um "
        "preço mecânico de cenário sobre o fechamento bruto atual. É cenário associacional, não previsão, "
        "causalidade, fair value ou preço-alvo."
    ),
    preparar=preparar_cenario_sensibilidade,
    source_dependencies=(sens_tool.__file__, market_snapshots.__file__, scenario_engine.__file__),
    requires_market_data=True,
    exposed_to_llm=False,
)
def calcular_cenario_sensibilidade(r: CenarioSensibilidadeResolvida) -> CenarioSensibilidadeOutput:
    sens = sens_tool.calcular_sensibilidade(r.sensibilidade)
    warnings = list(sens.evidencia.avisos)
    warnings.append(SCENARIO_NOT_FORECAST)
    if r.base_price is not None:
        warnings.extend(r.base_price.warnings)

    base_value = (
        r.base_price.value
        if r.base_price is not None and r.base_price.currency == "BRL"
        else None
    )
    scenario = None
    if base_value is None:
        warnings.append(BASE_PRICE_UNAVAILABLE)
    else:
        scenario = scenario_engine.apply_sensitivity_scenario(
            slope=sens.sensibilidade,
            shock_driver=r.choque_driver,
            base_price_brl=base_value,
        )
        warnings.extend(scenario.warnings)

    batches = set(sens.evidencia.ingestion_batch_ids)
    fonte_parts = [x for x in sens.evidencia.fonte.split("+") if x]
    if r.base_price is not None:
        batches.update(r.base_price.ingestion_batch_ids)
        fonte_parts.extend(r.base_price.source_codes)

    evidencia = EvidenciaEstatistica(
        fonte="+".join(sorted(set(fonte_parts))) or "market",
        instrument_ids=sens.evidencia.instrument_ids,
        tickers=sens.evidencia.tickers,
        index_codes=sens.evidencia.index_codes,
        cutoff_date=sens.evidencia.cutoff_date,
        as_of=r.base_price.price_date if r.base_price is not None else sens.evidencia.as_of,
        n_observacoes=sens.evidencia.n_observacoes,
        lacunas=sens.evidencia.lacunas,
        metodo=f"cenario_incremental_{sens.covariance_method}_{sens.medida_driver.value}",
        nota_metodo=(
            "O cenário reaplica a sensibilidade histórica já estimada: impacto incremental = slope × choque. "
            "O intercepto da regressão não é somado ao choque. O preço-base é fechamento bruto observado em ou "
            "antes do cutoff. Intervalos, quando disponíveis, propagam apenas o CI do slope. O resultado é uma "
            "extrapolação linear associacional para o choque informado, não previsão, causalidade, fair value ou "
            "preço-alvo."
        ),
        suficiente=(
            sens.evidencia.suficiente
            and scenario is not None
            and scenario.scenario_price_brl is not None
        ),
        avisos=_unique(warnings),
        metricas={
            **sens.evidencia.metricas,
            "choque_driver": r.choque_driver,
            "impacto_incremental_pct": scenario.impact_incremental_pct if scenario is not None else None,
            "base_price_brl": base_value,
            "scenario_price_brl": scenario.scenario_price_brl if scenario is not None else None,
        },
        ingestion_batch_ids=sorted(batches),
        estimativas=sens.evidencia.estimativas,
    )

    impact_range = None
    price_range = None
    if scenario is not None and scenario.impact_interval_pct is not None:
        impact_range = ScenarioRangeOutput(
            lower=scenario.impact_interval_pct.lower,
            upper=scenario.impact_interval_pct.upper,
        )
    if scenario is not None and scenario.scenario_price_interval_brl is not None:
        price_range = ScenarioRangeOutput(
            lower=scenario.scenario_price_interval_brl.lower,
            upper=scenario.scenario_price_interval_brl.upper,
        )

    return CenarioSensibilidadeOutput(
        ticker=sens.ticker,
        driver=sens.driver,
        choque_driver=r.choque_driver,
        unidade_choque=sens.unidade_variacao_driver,
        base_price_brl=base_value,
        base_price_date=r.base_price.price_date if r.base_price is not None else None,
        impacto_incremental_pct=scenario.impact_incremental_pct if scenario is not None else None,
        impacto_intervalo_pct=impact_range,
        scenario_price_brl=scenario.scenario_price_brl if scenario is not None else None,
        scenario_price_interval_brl=price_range,
        sensibilidade=sens.sensibilidade.estimate,
        r_squared=sens.r_squared,
        n=sens.n,
        evidencia=evidencia,
    )
