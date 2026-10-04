"""Plexo — backend de agentes de IA.

Princípios que todo módulo respeita:
- o banco executa as regras (constraints, triggers, RLS); o código só conduz;
- o LLM entende e sintetiza; quem calcula é tool determinística e versionada;
- config-first: nenhum número de negócio no código — vive em engine.policy_versions;
- segredos (DATABASE_URL, chaves) nunca aparecem em log, erro ou repr.
"""
