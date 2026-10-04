"""Ingestão de dados de mercado (F5): B3 COTAHIST (cotações oficiais D-1) e BACEN SGS (séries macro).

- cotahist.py — leitura posicional do arquivo da B3, em streaming; hash do arquivo cru
- sgs.py      — URL/parse do JSON oficial do SGS; a única função com rede é `buscar`
- ingest.py   — lotes idempotentes (market.ingestion_batches) e gravação append-only em
                market.prices / market.index_values, com trilha em audit.activity_log
As regras (append-only, sem data futura, lote finalizado imutável, um arquivo = um lote succeeded)
são do BANCO (31_market_immutability); aqui só se consulta antes de escrever.
"""
