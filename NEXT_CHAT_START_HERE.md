# START HERE — Continuação do Plexo

Leia primeiro:

1. `.ai/NEXT_CHAT_HANDOFF.md`
2. `.ai/PROJECT_STATE.md`
3. `.ai/DECISIONS.md`
4. `.ai/TASKS.md`

Estado atual: FQ4 foi promovido na branch de validação, o gate PostgreSQL/FQ4 pós-promoção passou e resta uma falha conhecida na suíte completa: o golden de blocos de `quant.event_study` ainda representa o contrato legacy enquanto o código canônico já está no contrato v2.

Não reverta o cutover só para satisfazer o golden. Leia o handoff completo e finalize conscientemente o golden + CI.

Repo autorizado: `feoff01/plexo-backend-validation`  
Branch: `bootstrap/plexo-project`
