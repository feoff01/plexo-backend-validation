# FQ5.6 — Plano de promoção de comparáveis por setor

Data: 2026-10-03
Estado: promoção autorizada após gates GREEN de fonte, universo, equivalência e performance.

## Pré-condições satisfeitas

### Fonte / universo
- classificação setorial B3 oficial: GREEN;
- issuer bridge: GREEN;
- IBrA atual 02/10/2026: GREEN;
- coverage externa observada: 146/148 tickers e 142/144 company codes com classificação;
- gaps explícitos: RIAA3 e SAUD3;
- sem imputação por Economatica.

### Tool shadow
- quant.comparaveis_setor 1.0.0 registrada e oculta;
- subsetor default;
- setor opt-in;
- sem segmento;
- sem ranking/recomendação/fair value.

### Performance
Baseline #145:
- 2 peers: 38 queries;
- 8 peers: 98;
- 20 peers: 218.

Batch GREEN #157:
- 2 peers: 10 queries;
- 8 peers: 10;
- 20 peers: 10;
- output público ~4 KB;
- equivalência resolved + output contra tools canônicas GREEN;
- full suite: 886 passed, 52 skipped, 19 warnings, 0 failed.

## Promoção

### Semver
Promover para **quant.comparaveis_setor 1.0.1** e `exposed_to_llm=True`.

Patch bump porque a capability shadow já foi validada e a mudança material desta etapa é exposição/catálogo + presentation routing, não mudança de contrato de params/output.

### Planner

Quando a tool estiver no catálogo:
- "como X se compara com pares/empresas do mesmo subsetor?" -> quant.comparaveis_setor;
- "múltiplos/crescimento/margens de X vs pares" -> quant.comparaveis_setor;
- subsetor é default;
- usar nivel=setor somente quando o usuário pedir setor amplo.

Restrições:
- não usar a tool para escolher "melhor ação";
- não produzir ranking;
- não transformar mediana em fair value;
- não converter diferença vs mediana em recomendação;
- pedidos de fair value continuam fora até engine próprio governado.

### Bloco

Mapper novo para quant.comparaveis_setor:
- tabela compacta;
- métrica;
- valor do alvo;
- mediana dos pares;
- diferença alvo-mediana;
- unidade;
- n válido;
- subtítulo com classificação e peer_count;
- nota explícita: comparação descritiva, não ranking/recomendação/fair value.

Não renderizar tabela completa de peers.
Exemplos de peers continuam no output para explicação do LLM, limitados por max_exemplos.

### Regression gate

Benchmark passa a impor:
- prepare_query_count <= 12 para 2/8/20 peers;
- output_payload_bytes < 5000;
- equivalência E2E obrigatória.

### Registry

Após promoção:
- 35 tools total;
- comparaveis_setor = 1.0.1 pública;
- as outras 34 mantêm semver/exposição/source fingerprint.

## Gate pós-promoção

- promotion readiness;
- planner static contract;
- bloco client-facing;
- E2E executor/cache existente;
- benchmark regression;
- PostgreSQL 18;
- suíte completa;
- prompts check;
- tools sync --check;
- checkpoint final em .ai/.
