"""Jobs de manutenção dos agentes — tasks puras (`tasks.py`) + fiação Arq/Redis (`worker.py`).

As tasks recebem um `ctx` dict {db, llm, policies, enfileirar} e nunca importam Redis: o worker
injeta `enfileirar = enqueue_job(...)`; a CLI `plexo context run` injeta uma chamada direta.
Assim o dev Windows e os testes rodam a mesma lógica sem fila.
"""
