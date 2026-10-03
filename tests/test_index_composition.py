from datetime import date

from app.market.index_compositions import (
    IndexCompositionMember,
    IndexCompositionProvenance,
    ResolvedIndexComposition,
)
from app.tools import carregar_tools
from app.tools.analista.composicao_indice import (
    ComposicaoIndiceResolvida,
    montar_composicao_indice,
)
from app.tools.registry import spec_de, specs_registradas


def _resolved():
    ref = date(2026, 10, 2)
    return ResolvedIndexComposition(
        index_code="ibra",
        display_name="Índice Brasil Amplo B3",
        reference_date=ref,
        members=[
            IndexCompositionMember(
                instrument_id="a", ticker="AAAA3", name="AAAA",
                weight_pct=60.0, theoretical_qty=1000,
            ),
            IndexCompositionMember(
                instrument_id="b", ticker="BBBB3", name="BBBB",
                weight_pct=30.0, theoretical_qty=2000,
            ),
            IndexCompositionMember(
                instrument_id="c", ticker="CCCC3", name="CCCC",
                weight_pct=10.0, theoretical_qty=3000,
            ),
        ],
        total_weight_pct=100.0,
        provenance=IndexCompositionProvenance(
            source_codes=["b3"],
            ingestion_batch_ids=["batch"],
            reference_date=ref,
            availability_date=date(2026, 10, 3),
            cutoff_date=date(2026, 10, 3),
            strict_pit=True,
        ),
    )


def test_composicao_indice_public_registry_contract():
    carregar_tools()
    spec = spec_de("dados.composicao_indice")
    assert spec.semver == "1.0.1"
    assert spec.family == "dados"
    assert spec.exposed_to_llm is True
    assert spec.requires_market_data is True
    assert len(specs_registradas()) == 37
    assert sum(s.exposed_to_llm for s in specs_registradas()) == 34


def test_composicao_indice_compacta_por_limite_sem_inventar_membros():
    out = montar_composicao_indice(
        ComposicaoIndiceResolvida(composition=_resolved(), limite=2)
    )
    assert out.n_componentes_total == 3
    assert out.peso_total_pct == 100.0
    assert [m.ticker for m in out.componentes] == ["AAAA3", "BBBB3"]
    assert out.truncado is True
    assert "composicao_indice_truncada" in out.provenance.warnings


def test_composicao_indice_filtra_tickers_exatos_e_avisa_ausentes():
    out = montar_composicao_indice(
        ComposicaoIndiceResolvida(
            composition=_resolved(),
            requested_tickers=["CCCC3", "MISS3"],
            limite=10,
        )
    )
    assert [m.ticker for m in out.componentes] == ["CCCC3"]
    assert out.truncado is False
    assert "ticker_fora_da_carteira:MISS3" in out.provenance.warnings


def test_composicao_indice_payload_maximo_fica_abaixo_de_5kb():
    base = _resolved()
    members = [
        IndexCompositionMember(
            instrument_id=f"id-{i}",
            ticker=f"T{i:03}3",
            name="EMPRESA EXEMPLO COM NOME RAZOAVELMENTE LONGO SA",
            weight_pct=4.0,
            theoretical_qty=1234567890.1234,
        )
        for i in range(25)
    ]
    composition = base.model_copy(
        update={
            "members": members,
            "total_weight_pct": 100.0,
        }
    )
    out = montar_composicao_indice(
        ComposicaoIndiceResolvida(composition=composition, limite=25)
    )
    assert len(out.model_dump_json().encode("utf-8")) < 5_000
