"""Histórico anual point-in-time de fundamentos (FQ5.5).

Mantido separado de ``app.market.fundamentals`` de propósito: o módulo foundation existente
participa do fingerprint de tools públicas FQ5.1/FQ5.2. Esta camada reutiliza o reader/modelos
existentes sem provocar bump artificial nessas tools.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.market import fundamentals as fundamentals


class ResolvedFundamentalHistory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_cnpj: str
    scope: fundamentals.FundamentalScope
    document_type: fundamentals.FundamentalDocumentType = fundamentals.FundamentalDocumentType.DFP
    records: list[fundamentals.FundamentalRecord] = Field(default_factory=list)
    provenance: fundamentals.FundamentalProvenance


class FundamentalHistoryLoader:
    """Colapsa vintages por período usando somente o que já existia no cutoff."""

    def __init__(self, reader: fundamentals.FundamentalsReader):
        self.reader = reader

    async def load_annual_history(
        self,
        company_cnpj: str,
        *,
        cutoff: date,
        scope: fundamentals.FundamentalScope = fundamentals.FundamentalScope.CONSOLIDATED,
        metrics: tuple[str, ...] | None = None,
        periods: int = 5,
    ) -> ResolvedFundamentalHistory:
        if periods < 2 or periods > 10:
            raise ValueError("periods deve ficar entre 2 e 10")

        rows = await self.reader.read_fundamentals(
            company_cnpj,
            cutoff=cutoff,
            scope=scope,
            document_type=fundamentals.FundamentalDocumentType.DFP,
            metrics=metrics,
        )
        valid = [
            row
            for row in rows
            if row.company_cnpj == company_cnpj
            and row.scope == scope
            and row.document_type == fundamentals.FundamentalDocumentType.DFP
            and row.reference_date <= cutoff
            and row.availability_date <= cutoff
        ]

        # Primeiro fecha o vintage de cada coordenada histórica. Um restatement posterior ao cutoff
        # não pode substituir a versão que realmente existia naquela data.
        by_coordinate: dict[
            tuple[str, str | None, date, str], fundamentals.FundamentalRecord
        ] = {}
        for row in valid:
            key = (row.metric, row.instrument_id, row.reference_date, row.period_label)
            current = by_coordinate.get(key)
            if current is None or row.availability_date > current.availability_date:
                by_coordinate[key] = row

        # Depois limita a janela por série lógica (métrica + instrumento), preservando no máximo N
        # reference_dates mais recentes. period_label continua na coordenada/vintage e no output.
        grouped: dict[tuple[str, str | None], list[fundamentals.FundamentalRecord]] = defaultdict(list)
        for row in by_coordinate.values():
            grouped[(row.metric, row.instrument_id)].append(row)

        selected: list[fundamentals.FundamentalRecord] = []
        for rows_for_series in grouped.values():
            rows_for_series.sort(
                key=lambda row: (row.reference_date, row.availability_date, row.period_label),
                reverse=True,
            )
            # Defesa para eventual period_label duplicado na mesma reference_date: mantém o registro
            # mais recente daquela data sem fabricar agregação entre períodos.
            seen_dates: set[date] = set()
            for row in rows_for_series:
                if row.reference_date in seen_dates:
                    continue
                seen_dates.add(row.reference_date)
                selected.append(row)
                if len(seen_dates) >= periods:
                    break

        selected.sort(
            key=lambda row: (
                row.metric,
                row.instrument_id or "",
                row.reference_date,
                row.availability_date,
            )
        )
        warnings: list[str] = []
        if any(row.value_unit == fundamentals.FundamentalUnit.RAW for row in selected):
            warnings.append(fundamentals.RAW_UNIT_UNUSABLE)

        return ResolvedFundamentalHistory(
            company_cnpj=company_cnpj,
            scope=scope,
            records=selected,
            provenance=fundamentals.FundamentalProvenance(
                source_codes=sorted({row.source_code for row in selected if row.source_code}),
                ingestion_batch_ids=sorted(
                    {row.ingestion_batch_id for row in selected if row.ingestion_batch_id}
                ),
                cutoff_date=cutoff,
                warnings=warnings,
            ),
        )
