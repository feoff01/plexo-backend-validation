"""Modelos dos itens que a IA pode propor a partir do texto do onboarding.

Vocabulário fechado nos tipos estruturados: `tipo` de objetivo é validado contra o CHECK
de planning.goals.kind e o de dívida contra o enum budget.debt_kind — valor desconhecido
vira 'outro' (não descarta: o cliente disse algo real, só não coube na taxonomia). Faixas
numéricas espelham as do wizard (F21a) e do catálogo.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Espelhos dos vocabulários do banco (sql/07_planning.sql CHECK de goals.kind e
# sql/08_budget.sql enum budget.debt_kind; estate.asset_kind em sql/25_estate.sql).
TIPOS_OBJETIVO = {"aposentadoria", "imovel", "educacao", "reserva_oportunidade", "viagem", "outro"}
TIPOS_DIVIDA = {"cartao_rotativo", "cheque_especial", "emprestimo_pessoal", "consignado",
                "financiamento_imovel", "financiamento_veiculo", "fies", "outro"}
TIPOS_BEM = {"imovel_residencial", "imovel_comercial", "terreno", "imovel_rural", "veiculo",
             "participacao_empresa", "previdencia_fechada", "obra_arte_colecionavel",
             "direito_a_receber", "cripto_autocustodia", "equipamento_profissional", "outro"}


class ItemFato(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_key: str
    valor: float | str | bool


class ItemObjetivo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str = Field(min_length=1)
    tipo: str = "outro"
    valor: float = Field(gt=0)
    prazo_meses: int = Field(ge=1, le=960)
    prioridade: int = Field(default=3, ge=1, le=10)

    @field_validator("tipo")
    @classmethod
    def _tipo_conhecido(cls, v: str) -> str:
        return v if v in TIPOS_OBJETIVO else "outro"


class ItemDivida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: str = "outro"
    saldo: float = Field(gt=0)
    taxa_aa_percentual: float = Field(default=0, ge=0)
    parcela: float = Field(default=0, ge=0)
    parcelas_restantes: int | None = Field(default=None, ge=1)

    @field_validator("tipo")
    @classmethod
    def _tipo_conhecido(cls, v: str) -> str:
        return v if v in TIPOS_DIVIDA else "outro"


class ItemBem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: str = "outro"
    rotulo: str = Field(min_length=1)
    valor: float = Field(gt=0)

    @field_validator("tipo")
    @classmethod
    def _tipo_conhecido(cls, v: str) -> str:
        return v if v in TIPOS_BEM else "outro"


MODELO_POR_KIND = {"fato": ItemFato, "objetivo": ItemObjetivo, "divida": ItemDivida, "bem": ItemBem}
