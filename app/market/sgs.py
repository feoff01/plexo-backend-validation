"""Cliente do SGS (Sistema Gerenciador de Séries Temporais do Banco Central).

Endpoint público: {base}/dados/serie/bcdata.sgs.{serie}/dados?formato=json&dataInicial=dd/MM/yyyy&dataFinal=dd/MM/yyyy
Resposta: [{"data": "dd/MM/yyyy", "valor": "0.043927"}, ...]. Para séries diárias a API limita a janela
por chamada (na prática 10 anos) — `janelas` fatia o pedido. `buscar` é a única função com rede; parse e
URL são puros para os testes rodarem sem conexão.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import httpx


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def url_serie(base: str, serie_id: int, de: date, ate: date) -> str:
    q = urlencode({"formato": "json", "dataInicial": _br(de), "dataFinal": _br(ate)}, safe="/")
    return f"{base.rstrip('/')}/dados/serie/bcdata.sgs.{serie_id}/dados?{q}"


def parse_sgs(texto: str) -> list[tuple[date, Decimal]]:
    """JSON oficial → [(data, valor)] em ordem cronológica; Decimal preserva as casas do provedor."""
    pontos = []
    for item in json.loads(texto):
        dd, mm, aaaa = item["data"].split("/")
        pontos.append((date(int(aaaa), int(mm), int(dd)), Decimal(str(item["valor"]))))
    pontos.sort(key=lambda p: p[0])
    return pontos


def janelas(de: date, ate: date, *, max_dias: int) -> list[tuple[date, date]]:
    """Fatia [de, ate] em janelas de no máximo `max_dias` (limite da API por chamada)."""
    saida, inicio = [], de
    while inicio <= ate:
        fim = min(ate, inicio + timedelta(days=max_dias - 1))
        saida.append((inicio, fim))
        inicio = fim + timedelta(days=1)
    return saida


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


async def buscar_texto(client: httpx.AsyncClient, base: str, serie_id: int, de: date, ate: date,
                       *, max_dias: int = 3650) -> str:
    """Baixa a série em janelas e devolve UM JSON (lista concatenada) — o hash dele é o do lote."""
    itens: list[dict] = []
    for a, b in janelas(de, ate, max_dias=max_dias):
        r = await client.get(url_serie(base, serie_id, a, b))
        r.raise_for_status()
        itens.extend(r.json())
    return json.dumps(itens, ensure_ascii=False, separators=(",", ":"))


async def buscar(client: httpx.AsyncClient, base: str, serie_id: int, de: date, ate: date,
                 *, max_dias: int = 3650) -> list[tuple[date, Decimal]]:
    return parse_sgs(await buscar_texto(client, base, serie_id, de, ate, max_dias=max_dias))
