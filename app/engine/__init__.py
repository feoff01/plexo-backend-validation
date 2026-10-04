"""Motor do perfil do cliente: fato → indicador → score → gate.

Determinístico por desenho. O LLM nunca calcula nada aqui — ele lê o resultado e explica.
Toda premissa numérica vem de `engine.policy_versions` (CLIENT_SCORES); o que está em Python
é fórmula e interpolação, ambas puras e travadas por golden master.
"""
from __future__ import annotations
