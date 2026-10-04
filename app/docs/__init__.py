"""Camada documental (F13a): documento externo citável como evidência `documentary`.

Mesma divisão que `app/market/`: **a única função com rede vive em `app/jobs/tasks.py`**. Aqui só
parser puro (`copom.py`) e gravação (`ingest.py`), para o teste rodar sem conexão e sem provedor.

O lote é o de `market.ingestion_batches` — imutável e idempotente por `file_hash` desde a 31. Não há
tabela de lote própria: um documento é mais um dado externo datado, e o mecanismo já existe.
"""
