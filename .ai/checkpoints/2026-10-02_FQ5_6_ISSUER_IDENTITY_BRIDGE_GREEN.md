# Checkpoint — FQ5.6 issuer identity bridge GREEN

Data: 2026-10-02
Estado: GREEN.

## Problema fechado
O projetor COTAHIST criava market.instruments sem identidade company-level. Isso impedia dedupe PETR3/PETR4 por issuer e limitava a ingestão oficial B3 quando o issuer ainda não tinha CNPJ.

## Implementação
- app.market.acervo: raiz B3 determinística e seleção somente das ações observadas no ano mais recente;
- tools/projetar_acervo.py: cria/reutiliza market.issuers para essas raízes e liga issuer_id apenas onde NULL;
- conflito de uma raiz já ligada a múltiplos issuers falha fechado;
- CNPJ nunca é sintetizado;
- sector_ingest.py ganhou core de persistência por issuer_id reutilizando a mesma lógica append-only;
- download oficial B3 resolve company code -> issuer e pode persistir mesmo sem CNPJ;
- rota CNPJ existente continua preservada;
- quant.comparaveis_setor continua shadow.

## Correções encontradas pelos gates
Runs intermediários capturaram apenas erros de publicação/teste (import com newline literal e helper raiz ausente no arquivo remoto). Foram corrigidos sem mudança de domínio.

## Gate final
Commit: 4d7f17f9478f7e958e86cf8f15fac3b7f46033a8
Run #113 / 37062697600: success.
- gate explícito: 120 passed;
- suíte completa: 878 passed, 52 skipped, 19 warnings, 0 failed;
- migrations/invariantes/validador PostgreSQL 18: verdes;
- prompts check: verde;
- tools sync --check: verde;
- 35 tools inalteradas.

## Próximo bloqueio real
O catálogo projetado ainda deixa is_in_universe=false. O schema F22 prevê que essa cobertura seja derivada por regra de market.index_weights. Não marcar ações manualmente nem usar classificação setorial como proxy de universo.

Próximo documento: .ai/FQ5_6_UNIVERSE_POLICY_DESIGN.md.
