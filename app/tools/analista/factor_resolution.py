"""Resolução compartilhada de fatores do Analista.

Esta camada resolve identidade, série, qualidade e provenance. Ela NÃO escolhe a transformação
estatística da série: retorno, mudança de nível, nível e regimes continuam sendo decisões de cada
análise quantitativa.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg import AsyncConnection

from app.market import factors as market_factors
from app.market import series as market_series
from app.market.series import PriceBasis, ResolvedMarketSeries, TemporalSemantics
from app.tools.analista._comum import (
    carregar_indice_resolvido,
    carregar_serie_resolvida,
    instrumento_por_termo,
)

FactorKind = Literal["ativo", "indice", "cambio"]
FATOR_CAMBIO_DESCONHECIDO = "par_cambio_desconhecido"


class FactorRef(BaseModel):
    """Referência pública compacta para uma série usada como fator/driver."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tipo: FactorKind = Field(description="Tipo da série: ativo, indice ou cambio.")
    codigo: str = Field(min_length=1, description="Ticker/alias, código de índice ou par cambial AAA/BBB.")

    @model_validator(mode="before")
    @classmethod
    def _normalizar(cls, raw):
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        tipo = str(data.get("tipo") or "").strip().lower()
        codigo = str(data.get("codigo") or "").strip()
        if tipo == "ativo":
            if not codigo:
                raise ValueError("codigo do ativo não pode ser vazio")
            data["codigo"] = codigo
        elif tipo == "indice":
            if not codigo:
                raise ValueError("codigo do índice não pode ser vazio")
            data["codigo"] = codigo.lower()
        elif tipo == "cambio":
            base, quote = parse_fx_pair(codigo)
            data["codigo"] = market_factors.fx_code(base, quote)
        data["tipo"] = tipo
        return data


class ResolvedFactor(BaseModel):
    """Fator resolvido sem impor transformação matemática à série."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ref: FactorRef
    tipo: FactorKind
    codigo: str
    found: bool
    in_universe: bool | None = None
    instrument_id: str | None = None
    index_code: str | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    unit: str | None = None
    series: ResolvedMarketSeries | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> "ResolvedFactor":
        if self.tipo != self.ref.tipo:
            raise ValueError("tipo resolvido diverge da referência")
        if self.codigo != self.ref.codigo and self.tipo != "ativo":
            raise ValueError("código canônico diverge da referência")

        if self.tipo == "ativo":
            if self.in_universe is None:
                raise ValueError("ativo deve informar in_universe")
            if self.index_code is not None or self.base_currency is not None or self.quote_currency is not None:
                raise ValueError("ativo não pode carregar identidade de índice/câmbio")
            if self.series is not None:
                if self.series.instrument_id != self.instrument_id:
                    raise ValueError("instrument_id da série diverge do fator")
                if self.series.provenance.price_basis is None:
                    raise ValueError("ativo deve carregar price_basis")
        elif self.tipo == "indice":
            if self.in_universe is not None or self.instrument_id is not None:
                raise ValueError("índice não pertence ao universo de instrumentos")
            if self.base_currency is not None or self.quote_currency is not None:
                raise ValueError("índice não pode carregar identidade cambial")
            if self.index_code != self.codigo:
                raise ValueError("index_code diverge do código canônico")
            if self.series is not None:
                if self.series.index_code != self.index_code:
                    raise ValueError("index_code da série diverge do fator")
                _validar_serie_nao_ativo(self.series)
        else:
            if self.in_universe is not None or self.instrument_id is not None or self.index_code is not None:
                raise ValueError("câmbio não pertence ao universo de instrumentos/índices")
            if not self.base_currency or not self.quote_currency:
                raise ValueError("câmbio deve informar base_currency e quote_currency")
            if self.codigo != market_factors.fx_code(self.base_currency, self.quote_currency):
                raise ValueError("par cambial resolvido é incoerente")
            if self.series is not None:
                if self.series.code != self.codigo:
                    raise ValueError("código da série cambial diverge do fator")
                _validar_serie_nao_ativo(self.series)
        return self


def _validar_serie_nao_ativo(series: ResolvedMarketSeries) -> None:
    if series.provenance.price_basis is not None:
        raise ValueError("fator não-ativo não pode carregar price_basis")
    if series.provenance.temporal_semantics != TemporalSemantics.OBSERVATION_DATE_CUTOFF:
        raise ValueError("fator não-ativo deve usar observation_date_cutoff")


def parse_fx_pair(code: str) -> tuple[str, str]:
    pieces = [part.strip() for part in str(code).split("/")]
    if len(pieces) != 2 or not all(pieces):
        raise ValueError("par cambial deve usar o formato AAA/BBB, por exemplo USD/BRL")
    base = market_factors.normalize_currency(pieces[0])
    quote = market_factors.normalize_currency(pieces[1])
    if base == quote:
        raise ValueError("moedas do par cambial devem ser diferentes")
    return base, quote


async def resolve_factor(
    conn: AsyncConnection,
    ref: FactorRef,
    *,
    de: date,
    ate: date,
    cutoff: date,
    asset_price_basis: PriceBasis,
    asset_temporal_semantics: TemporalSemantics,
    include_calendar: bool = True,
) -> ResolvedFactor:
    """Resolve ativo, índice/taxa ou FX sem escolher transformação estatística."""
    if ref.tipo == "ativo":
        inst = await instrumento_por_termo(conn, ref.codigo, cutoff=cutoff)
        found = inst is not None
        in_universe = bool(inst is not None and inst["is_in_universe"])
        series = None
        canonical = inst["ticker"] if inst and inst.get("ticker") else ref.codigo
        instrument_id = inst["instrument_id"] if inst else None
        if in_universe and inst is not None:
            series = await carregar_serie_resolvida(
                conn,
                inst["instrument_id"],
                de=de,
                ate=ate,
                cutoff=cutoff,
                codigo=canonical,
                basis=asset_price_basis,
                temporal_semantics=asset_temporal_semantics,
                include_calendar=include_calendar,
            )
        return ResolvedFactor(
            ref=ref,
            tipo="ativo",
            codigo=canonical,
            found=found,
            in_universe=in_universe,
            instrument_id=instrument_id,
            unit=series.unit if series is not None else None,
            series=series,
        )

    if ref.tipo == "indice":
        try:
            series = await carregar_indice_resolvido(
                conn,
                ref.codigo,
                de=de,
                ate=ate,
                cutoff=cutoff,
                include_calendar=include_calendar,
            )
        except market_series.UnknownIndex:
            return ResolvedFactor(
                ref=ref,
                tipo="indice",
                codigo=ref.codigo,
                found=False,
                index_code=ref.codigo,
                unit=None,
                series=None,
            )
        return ResolvedFactor(
            ref=ref,
            tipo="indice",
            codigo=ref.codigo,
            found=True,
            index_code=ref.codigo,
            unit=series.unit or "pontos",
            series=series,
        )

    base, quote = parse_fx_pair(ref.codigo)
    found = await market_factors.fx_pair_exists(conn, base, quote, cutoff=cutoff)
    series = None
    if found:
        series = await market_factors.load_fx_series(
            conn,
            base,
            quote,
            de=de,
            ate=ate,
            cutoff=cutoff,
            include_calendar=include_calendar,
        )
    return ResolvedFactor(
        ref=ref,
        tipo="cambio",
        codigo=ref.codigo,
        found=found,
        base_currency=base,
        quote_currency=quote,
        unit=series.unit if series is not None else "pontos",
        series=series,
    )
