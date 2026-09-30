"""Analista research (F6): pergunta → plano (LLM) → DAG compilado → execução com checkpoints → relatório imutável.

- config.py   — `ConfigResearch` (policy ANALISE_RESEARCH: max_tasks, timeout, retentativas, dsl_version)
- dsl.py      — `AnalysisPlan`/`NodeSpec` (Pydantic estrito) e `validar_plano` (nó inválido descartado com motivo)
- compiler.py — valida cada nó contra o registry/catálogo/família/plano/params, ordena (Kahn) e grava
                `analysis.plans` + `analysis.tasks` (o banco recusa dependência inexistente, T65)
- executor.py — roda o DAG em ordem topológica com claim por task (CAS), timeout/retentativas, findings por task;
                retomada = ignora o que já está `succeeded`/`skipped`
- budget.py   — `AnalysisBudget`: custo real de `llm.model_calls` por análise contra `analyses.budget`
- planner.py / report.py / pipeline.py — LLM (planejamento e síntese) e orquestração de status (F6b)
O banco impõe: gates de tool pela análise (T63), research exige conversa e terminal não reabre (T64), DAG e
definição de tarefa (T65), replan limitado (T66), relatório fundamentado e imutável (T67).
"""
