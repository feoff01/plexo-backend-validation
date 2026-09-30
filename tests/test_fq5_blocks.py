from app.agents.blocos import blocos_de


def ev(**kw):
    base = {
        "fonte": "teste", "cutoff_date": "2026-09-30", "as_of": "2026-09-29",
        "n_observacoes": 10, "lacunas": [], "metodo": "teste", "suficiente": True,
        "avisos": [], "metricas": {}, "ingestion_batch_ids": [],
    }
    base.update(kw)
    return base


def test_bloco_valor_mercado_nao_chama_market_cap_de_fair_value():
    payload = {
        "ticker": "PETR4", "requested_price_brl": 32.0, "requested_price_date": "2026-09-29",
        "classes": [{"ticker": "PETR4", "instrument_id": "pn", "price_brl": 32.0,
                     "price_date": "2026-09-29", "shares_outstanding": 10.0,
                     "market_value_brl": 320.0, "complete": True}],
        "market_cap_brl": 320.0, "net_debt_brl": 80.0, "enterprise_value_brl": 400.0,
        "multiples": {"pe": 7.0, "ev_ebitda": 4.0, "price_to_book": 1.1, "fcf_yield_pct": 12.0},
        "intrinsic_value_produced": False, "evidencia": ev(),
    }
    blocks = blocos_de("quant.valor_mercado", payload, execution_id="e1")
    assert blocks and blocks[0]["tipo"] == "indicadores"
    labels = {x["rotulo"] for x in blocks[0]["dados"]["itens"]}
    assert {"Preço da classe consultada", "Valor de mercado", "Enterprise value (EV)"} <= labels
    assert "não são valor intrínseco" in blocks[0]["nota"]


def test_bloco_cenario_deixa_explicito_que_nao_e_previsao():
    payload = {
        "ticker": "PETR4", "driver": "selic_meta", "choque_driver": 1.0,
        "unidade_choque": "pontos_percentuais", "base_price_brl": 32.0,
        "base_price_date": "2026-09-29", "impacto_incremental_pct": -2.0,
        "scenario_price_brl": 31.36, "scenario_price_interval_brl": {"lower": 30.8, "upper": 31.9},
        "sensibilidade": -2.0, "r_squared": 0.25, "n": 200,
        "evidencia": ev(avisos=["cenario_associacional_nao_previsao"]),
    }
    blocks = blocos_de("quant.cenario_sensibilidade", payload, execution_id="e2")
    assert len(blocks) == 1
    assert "não é previsão" in blocks[0]["nota"].lower()
    assert any("cenário mecânico" in x["rotulo"].lower() for x in blocks[0]["dados"]["itens"])
    assert any("não previsão" in x.lower() for x in blocks[0]["proveniencia"]["avisos"])


def test_bloco_dependencia_macro_reusa_visual_de_dependencia_com_proveniencia_fx():
    payload = {
        "par": "PETR4 × USD/BRL", "factor_type": "cambio", "factor_code": "USD/BRL",
        "metodo": "pearson", "coeficiente": 0.42, "n_pares": 200,
        "defasagem_observacoes": 0, "price_basis_ativo": "adjusted_close",
        "temporal_semantics_ativo": "retrospective_as_known_now",
        "evidencia": ev(avisos=["fx_observation_date_cutoff_sem_vintage"]),
    }
    blocks = blocos_de("quant.dependencia_macro", payload, execution_id="e3")
    assert len(blocks) == 2
    assert blocks[0]["dados"]["valor"] == 0.42
    assert blocks[0]["subtitulo"] == "fator cambio: USD/BRL"
    assert any("vintage histórico" in x for x in blocks[0]["proveniencia"]["avisos"])


def test_bloco_fundamentos_e_tabela_pit_compacta():
    payload = {
        "ticker": "PETR4", "scope": "consolidated", "periodo": "ultimo_dfp_anual_disponivel_no_cutoff",
        "fundamentos": [
            {"metric": "net_income", "value": 100.0, "value_unit": "brl", "currency": "BRL",
             "instrument_id": None, "reference_date": "2025-12-31", "availability_date": "2026-03-01",
             "document_type": "DFP", "period_label": "FY", "is_derived": False, "source_code": "cvm"}
        ],
        "evidencia": ev(),
    }
    blocks = blocos_de("dados.fundamentos_empresa", payload, execution_id="e4")
    assert len(blocks) == 1 and blocks[0]["tipo"] == "tabela"
    assert blocks[0]["dados"]["linhas"][0]["metrica"] == "net_income"
    assert blocks[0]["dados"]["linhas"][0]["disponivel_em"] == "2026-03-01"
