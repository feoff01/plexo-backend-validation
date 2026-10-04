"""Pesquisa Focus (Sistema de Expectativas de Mercado do BCB) — OData aberto, sem chave.

Nada aqui toca o banco nem a rede: recebe o JSON já baixado e devolve estrutura, como `sgs.py`.

Contrato observado (verificado em 2026-08-27), envelope `value`:
    {"value": [{"Indicador": "Selic", "IndicadorDetalhe": null, "Data": "2026-08-21",
                "DataReferencia": "2026", "Media": ..., "Mediana": ..., "DesvioPadrao": ...,
                "Minimo": ..., "Maximo": ..., "numeroRespondentes": 41}]}

`LAYOUT_VERSAO` versiona o CONTRATO DE LEITURA: mudar o que se extrai muda a versão, senão a mesma
resposta (mesmo hash) já é lote `succeeded` e a reingestão vira no-op.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from dataclasses import dataclass
from datetime import date

BASE = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"
RECURSO = "ExpectativasMercadoAnuais"
LAYOUT_VERSAO = "2"  # 2: passou a ler baseCalculo (37) — layout novo, lote novo
DATASET = f"focus@{LAYOUT_VERSAO}"


@dataclass(frozen=True)
class Expectativa:
    indicador: str
    detalhe: str | None
    data_coleta: date
    referencia: str
    mediana: float | None
    media: float | None
    desvio_padrao: float | None
    minimo: float | None
    maximo: float | None
    respondentes: int | None
    base_calculo: int | None      # 0 = 30 dias, 1 = 5 dias úteis — chave, não detalhe


def url(indicador: str | None, top: int, desde: date | None = None) -> str:
    """OData: filtra por indicador e data de coleta, ordena da mais recente para trás."""
    filtros = []
    if indicador:
        filtros.append(f"Indicador eq '{indicador}'")
    if desde:
        filtros.append(f"Data ge '{desde.isoformat()}'")
    # Percent-encoding explícito: o OData usa espaço em `$orderby`/`$filter`, e cliente HTTP que
    # não tolera caractere de controle recusa a URL crua (visto com urllib em 2026-08-27).
    consulta = {"$top": str(top), "$format": "json", "$orderby": "Data desc"}
    if filtros:
        consulta["$filter"] = " and ".join(filtros)
    return f"{BASE}/{RECURSO}?" + urllib.parse.urlencode(consulta, quote_via=urllib.parse.quote)


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _num(x: object) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def parse(json_texto: str) -> list[Expectativa]:
    """Itens do envelope `value`. Linha sem indicador, data ou horizonte é descartada — sem esses
    três a estatística não identifica nada e não pode virar citação."""
    itens = (json.loads(json_texto) or {}).get("value") or []
    saida: list[Expectativa] = []
    for it in itens:
        indicador, data, referencia = it.get("Indicador"), it.get("Data"), it.get("DataReferencia")
        if not indicador or not data or not referencia:
            continue
        respondentes = it.get("numeroRespondentes")
        saida.append(Expectativa(
            indicador=str(indicador).strip(),
            detalhe=(str(it["IndicadorDetalhe"]).strip() or None) if it.get("IndicadorDetalhe") else None,
            data_coleta=date.fromisoformat(str(data)[:10]), referencia=str(referencia).strip(),
            mediana=_num(it.get("Mediana")), media=_num(it.get("Media")),
            desvio_padrao=_num(it.get("DesvioPadrao")), minimo=_num(it.get("Minimo")),
            maximo=_num(it.get("Maximo")),
            respondentes=int(respondentes) if isinstance(respondentes, int) else None,
            base_calculo=it["baseCalculo"] if isinstance(it.get("baseCalculo"), int) else None))
    return saida
