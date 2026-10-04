# Checkpoint — FQ5.6 Economatica coverage dry-run GREEN

Data: 2026-10-01
Estado: **infraestrutura GREEN; coverage real de produção ainda não medida**

## Implementação
- app/market/economatica_coverage.py: somente SELECT, relatório ticker-level + issuer-level;
- tools/economatica_sector_coverage.py: CLI operacional com transação PostgreSQL read-only;
- gaps separados: ticker ausente, ticker sem issuer, issuer fora do universo, issuer do universo não coberto;
- nenhuma ingestão, migration ou tool pública nova;
- raw Economatica não versionado.

## Fonte validada localmente
- export 2025 fornecido pelo usuário: 478 ações B3 ativas;
- 478/478 com setor econômico preenchido;
- 478/478 com subsetor preenchido.

## CI
Commit de código/correção: af58906642665056e3b244fe21a03629d4f7339a
Run: #75 / 36943721475
Conclusão: success

- migrations do zero até 0063: verde;
- validador e invariantes SQL: verdes;
- gate explícito: 110 passed;
- suíte completa: 868 passed, 52 skipped, 19 warnings, 0 failed;
- prompts check: verde;
- tools sync --check: verde;
- 34 tools inalteradas.

## Limitação de ambiente
O seed do CI não representa o catálogo real de mercado e não pode produzir um percentual de coverage de produção. Não existe conector Aiven/PostgreSQL genérico disponível nesta sessão para ler o banco real. Nenhuma credencial ou .env foi solicitada/lida.

## Como completar o coverage real sem segredo
Executar o CLI no ambiente autorizado com acesso read-only ao banco, ou fornecer um export não sensível do catálogo com:
- ticker;
- kind;
- issuer_id;
- is_in_universe;
- issuer_name.

Query de export equivalente:

select i.ticker, i.kind::text as kind, i.issuer_id::text as issuer_id,
       i.is_in_universe, iss.name as issuer_name
  from market.instruments i
  left join market.issuers iss on iss.id = i.issuer_id
 where i.kind = 'acao' and i.ticker is not null
 order by i.ticker;

FQ5.6B permanece bloqueada até a medição real e decisão explícita de source/nível.