"""Intake do onboarding (F21b): texto/arquivo/áudio → extração por IA → itens propostos.

A cadeia de extração de conversas (app/context/extractor.py) fica intacta — este pacote
cuida só do que o cliente CONTA no onboarding, com o mesmo padrão epistêmico gravado no
banco (migration 60: nasce proposto, só o próprio usuário confirma, payload imutável).
"""
