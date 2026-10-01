# Checkpoint — FQ5.6A1 fonte B3 + loader setorial shadow

Data: 2026-09-30
Estado: **GREEN no PostgreSQL 18; ingestão externa ainda bloqueada por contrato de fonte**

## Fonte
- B3/UP2DATA Empresas Listadas / SummaryData é o contrato estruturado oficial preferido;
- acesso recorrente exige contratação/autenticação;
- `listedCompaniesProxy` não é tratado como API pública estável;
- parser/ingestão de rede segue bloqueado até fixture oficial real.

## Shadow
Commit de código: `08bda53fa47eeef576a5fa525260f69d7818d906`.

`app/market/sectors.py`:
- strict PIT por lote succeeded + finished_at <= cutoff;
- fonte B3 explícita;
- classificação company-level por issuer;
- dedupe de múltiplas classes;
- divergência entre classes no mesmo snapshot falha fechado;
- peer universe por segmento/subsetor/setor, sem auto-widen;
- target de peers deve ser ação in-universe;
- legacy sem lote só entra com strict_pit=False + warning.

## Testes
- 6 testes puros verdes;
- E2E PostgreSQL para cutoff/finished_at, legacy, divergência, dedupe e target fora do universo;
- E2E incluído no gate explícito do workflow;
- registry: 34 -> 34, zero drift.

## Invariantes
Nenhuma tool nova, migration/schema, semver/exposição/fingerprint, coletor de rede ou matemática nova.


## Gate remoto GREEN

HEAD: `e039d771c1b086e0f425d73d6c73822e688d3faa`  
Run: #61 / `36799893075`  
Conclusão: success

- migrations do zero: verde;
- validador: 0 erros / 0 avisos;
- invariantes SQL admin e `plexo_service`: verdes;
- gate explícito incluindo `test_fq56_sectors_db.py`: **98 passed**;
- suíte completa: **849 passed, 52 skipped, 19 warnings, 0 failed**;
- prompts check: verde;
- tools sync --check: verde.

## Próximo bloqueio

Loader setorial está pronto em shadow, mas `market.sector_classification` ainda não tem ingestão oficial/cobertura comprovada. Não abrir FQ5.6B até obter fixture oficial B3/UP2DATA ou export oficial equivalente, implementar parser/ingestão e executar coverage gate.
