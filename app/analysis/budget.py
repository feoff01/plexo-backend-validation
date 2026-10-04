"""Orçamento por análise: o envelope congelado em `analyses.budget` (max_usd, max_tasks) contra o custo REAL
somado de `llm.model_calls.cost_usd` da análise (não uma estimativa). Estouro ⇒ `BudgetExceeded` antes da
chamada seguinte — o pipeline fecha a análise em `blocked`. Sem pricing do provedor (`LLM_PRICING`) o custo
é NULL e o teto não morde: pendência operacional, não regra afrouxada."""
from __future__ import annotations

from dataclasses import dataclass

from psycopg import AsyncConnection

from app.agents import analysis as an
from app.analysis.config import ConfigResearch
from app.llm.budget import BudgetExceeded


@dataclass(frozen=True)
class AnalysisBudget:
    analysis_id: str
    max_usd: float | None
    max_tasks: int
    max_replans: int

    @classmethod
    def from_analysis(cls, analise: an.AnaliseRow, *, cfg: ConfigResearch) -> "AnalysisBudget":
        envelope = analise.budget or {}
        max_usd = envelope.get("max_usd")
        max_tasks = envelope.get("max_tasks") or cfg.max_tasks
        return cls(analysis_id=analise.id, max_usd=float(max_usd) if max_usd is not None else None,
                   max_tasks=int(max_tasks), max_replans=int(analise.max_replans))

    async def custo_acumulado(self, conn: AsyncConnection) -> float:
        cur = await conn.execute(
            "select coalesce(sum(cost_usd), 0)::float from llm.model_calls where analysis_id = %s", (self.analysis_id,))
        return float((await cur.fetchone())[0])

    async def checar(self, conn: AsyncConnection) -> float:
        """Custo até agora; levanta se já estourou (chamar ANTES de cada chamada de LLM)."""
        gasto = await self.custo_acumulado(conn)
        if self.max_usd is not None and gasto >= self.max_usd:
            raise BudgetExceeded(f"análise {self.analysis_id}: custo {gasto:.4f} USD atingiu o teto {self.max_usd:.4f}")
        return gasto
