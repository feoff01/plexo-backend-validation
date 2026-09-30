#!/usr/bin/env python3
"""Validador estático do conjunto Synapta (sem PostgreSQL disponível).

Checa, na ordem de execução dos arquivos:
1. Todo objeto qualificado referenciado (REFERENCES x.y, EXECUTE FUNCTION x.f,
   tipos x.t em colunas, tabelas em INSERT/UPDATE/SELECT de corpos e testes)
   foi criado ANTES do ponto de uso.
2. Colunas usadas em INSERT (...cols...) e UPDATE ... SET col= nos testes
   existem na definição da tabela.
3. Sanidade: parênteses balanceados por statement de CREATE TABLE, BEGIN/COMMIT
   pareados por arquivo.
"""
import re, sys, pathlib, collections

# Caminhos relativos ao próprio script: tools/ é irmão de sql/ e tests/.
ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
TESTS_DIR = ROOT / "tests"
def path_of(f):
    return (TESTS_DIR if f.startswith("test_") else SQL_DIR) / f
ORDER = [
    "00_core.sql","01_identity.sql","02_engine.sql","03_billing.sql","04_market.sql",
    "05_wealth.sql","06_diagnostics.sql","07_planning.sql","08_budget.sql","09_content.sql",
    "10_copilot.sql","11_ledger.sql","12_analytics.sql","13_audit.sql","14_rls_partitions.sql",
    "15_taxonomia.sql","17_agents.sql","18_tools.sql","19_llm.sql","20_analysis.sql","21_context.sql",
    "22_assertions.sql","23_household.sql","24_income.sql","25_estate.sql",
    "26_preferences.sql","27_decisions.sql","28_roles_grants.sql","29_tool_gates.sql","30_content_education_gate.sql",
    "31_market_immutability.sql","32_analysis_dag_gates.sql","33_identity_sessions.sql",
    "34_docs.sql","35_market_expectations.sql","36_focus_source.sql","37_focus_base_calculo.sql","38_fact_catalog.sql","39_live_extraction.sql","40_client_profile.sql","41_score_premises.sql","42_supersede_on_user_confirm.sql","43_fact_derivation.sql","44_fidelidade_do_perfil.sql","45_perfil_client_facing.sql","46_insumos_da_lacuna.sql","47_renda_comprometivel.sql","48_market_assumptions.sql","49_elegibilidade_calibrada.sql","50_probabilidade_no_destino.sql","51_orcamento_da_sintese.sql","52_extracao_incremental.sql","53_reconciliacao_da_carteira.sql","54_raio_x_da_carteira.sql","55_security_invoker_das_views.sql","56_rls_particoes_e_filhas.sql","57_isencoes_de_rls_declaradas.sql","58_canario_do_card.sql","59_onboarding_fundacoes.sql","60_intake_do_onboarding.sql","61_acervo_de_mercado.sql",
]
TESTS = ["test_regras_invioláveis.sql","test_regras_invioláveis_agentes.sql","test_regras_invioláveis_contexto.sql",
         "test_rls_papeis.sql","test_regras_invioláveis_tools.sql",
         "test_regras_invioláveis_content.sql","test_regras_invioláveis_market.sql",
         "test_regras_invioláveis_analysis.sql","test_regras_invioláveis_identity.sql",
         "test_regras_invioláveis_docs.sql","test_regras_invioláveis_perfil.sql","test_regras_invioláveis_perfil_vivo.sql","test_regras_invioláveis_scores.sql","test_regras_invioláveis_derivacao.sql","test_regras_invioláveis_simulacao.sql","test_regras_invioláveis_carteira.sql","test_regras_invioláveis_raiox.sql","test_regras_invioláveis_views.sql","test_regras_invioláveis_rls_completa.sql","test_regras_invioláveis_onboarding.sql","test_regras_invioláveis_intake.sql"]

# As quatro reescritas que perderam a flag antes de a checagem existir. Migration aplicada
# não se edita (regra 3), e a 55 já as reparou com `ALTER VIEW ... SET`. Ficam LISTADAS, e
# não silenciadas por faixa de número, para que quem ler saiba exatamente quais foram —
# o T129 é quem garante que o banco está certo agora.
REESCRITAS_SEM_INVOKER_JA_REPARADAS = {
    ("43_fact_derivation.sql",      "context.v_fact_coverage"),
    ("44_fidelidade_do_perfil.sql", "diagnostics.v_client_profile"),
    ("45_perfil_client_facing.sql", "diagnostics.v_client_profile"),
    ("47_renda_comprometivel.sql",  "diagnostics.v_client_profile"),
}

# Schemas cujas views enxergam dado de UM cliente: nelas `security_invoker` não é
# preferência, é a decisão nº 1 do projeto ("views com security_invoker").
SCHEMAS_COM_DADO_DE_CLIENTE = {"diagnostics","context","wealth","estate","budget","planning",
                               "preferences","household","decisions","analysis","agents","ledger"}

SCHEMAS = {"core","identity","billing","market","wealth","engine","diagnostics","planning",
           "budget","content","copilot","ledger","analytics","audit",
           "agents","tools","llm","analysis","context",
           "household","estate","preferences","decisions","docs"}

def strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql

def split_statements(sql: str):
    """Split on top-level ';' respecting $$-quoted bodies and single quotes."""
    stmts, buf, i, n = [], [], 0, len(sql)
    in_dollar, tag = False, None
    in_squote = False
    while i < n:
        ch = sql[i]
        if in_dollar:
            if sql.startswith(tag, i):
                buf.append(tag); i += len(tag); in_dollar = False; continue
            buf.append(ch); i += 1; continue
        if in_squote:
            buf.append(ch)
            if ch == "'":
                if i+1 < n and sql[i+1] == "'":
                    buf.append("'"); i += 2; continue
                in_squote = False
            i += 1; continue
        if ch == "'":
            in_squote = True; buf.append(ch); i += 1; continue
        m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
        if m:
            tag = m.group(0); in_dollar = True; buf.append(tag); i += len(tag); continue
        if ch == ";":
            stmts.append("".join(buf).strip()); buf = []; i += 1; continue
        buf.append(ch); i += 1
    tail = "".join(buf).strip()
    if tail: stmts.append(tail)
    return [s for s in stmts if s]

QUAL = r"([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)"

created = {}          # (kind, schema, name) -> (file, seq)
table_cols = {}       # (schema, table) -> set(cols)
errors, warnings = [], []
seq = 0

def note_create(kind, schema, name, f, replace=False):
    global seq
    key = (kind, schema, name)
    if schema == "pg_temp":
        return
    if key in created and created[key][0] != f and not replace:
        errors.append(f"{f}: {kind} {schema}.{name} criado duas vezes (antes em {created[key][0]})")
    created[key] = created.get(key, (f, seq))

deferred = []   # (file, schema, table) — referências em corpo de função

def parse_table_columns(body: str):
    """body = text inside the outermost parens of CREATE TABLE."""
    cols, depth, cur = [], 0, []
    for ch in body:
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        if ch == "," and depth == 0:
            cols.append("".join(cur).strip()); cur = []
        else:
            cur.append(ch)
    if cur: cols.append("".join(cur).strip())
    names = set()
    for c in cols:
        first = c.split()[0].strip('"') if c.split() else ""
        if first.upper() in {"CONSTRAINT","PRIMARY","UNIQUE","CHECK","FOREIGN","LIKE","EXCLUDE"}:
            continue
        names.add(first)
    return names

def split_top_commas(body: str):
    parts, depth, cur = [], 0, []
    for ch in body:
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip()); cur = []
        else:
            cur.append(ch)
    if cur: parts.append("".join(cur).strip())
    return parts

def outer_parens(stmt: str):
    i = stmt.find("(")
    if i < 0: return None
    depth, j = 0, i
    for j in range(i, len(stmt)):
        if stmt[j] == "(": depth += 1
        elif stmt[j] == ")":
            depth -= 1
            if depth == 0: return stmt[i+1:j]
    return None

def exists_before(kind_options, schema, name, at_seq):
    for k in kind_options:
        hit = created.get((k, schema, name))
        if hit and hit[1] <= at_seq:
            return True
    return False

def check_ref(kinds, schema, name, f, ctx):
    if schema not in SCHEMAS:  # e.g. pg_catalog, pg_temp, information_schema
        return
    if not exists_before(kinds, schema, name, seq):
        later = any(created.get((k, schema, name)) for k in kinds)
        tag = "ORDEM" if later else "INEXISTENTE"
        errors.append(f"{f}: [{tag}] {ctx} referencia {schema}.{name} ({'/'.join(kinds)})")

# pass 1+2 merged: process in order, registering creates then checking refs in same stmt order
for f in ORDER + TESTS:
    sql = strip_comments(path_of(f).read_text(encoding="utf-8"))
    top_stmts = split_statements(sql)
    begins  = sum(1 for st in top_stmts if re.fullmatch(r"BEGIN", st.strip(), re.I))
    commits = sum(1 for st in top_stmts if re.fullmatch(r"COMMIT|ROLLBACK", st.strip(), re.I))
    if f in ORDER and (begins != 1 or commits != 1):
        warnings.append(f"{f}: BEGIN={begins} COMMIT/ROLLBACK={commits}")
    for stmt in top_stmts:
        seq += 1
        low = re.sub(r"\s+", " ", stmt).strip()
        # --- registros de criação -------------------------------------------
        m = re.match(r"CREATE SCHEMA (?:IF NOT EXISTS )?([a-z_]+)", low, re.I)
        if m: note_create("schema", m.group(1), "", f)
        m = re.match(r"CREATE TYPE " + QUAL, low, re.I)
        if m: note_create("type", m.group(1), m.group(2), f)
        m = re.match(r"CREATE DOMAIN " + QUAL, low, re.I)
        if m: note_create("type", m.group(1), m.group(2), f)
        m = re.match(r"CREATE (?:OR REPLACE )?FUNCTION " + QUAL, low, re.I)
        if m:
            # `CREATE OR REPLACE` em migration posterior é o ÚNICO jeito de evoluir um
            # trigger sob história append-only (a 38 refaz 3 funções da 22). Redefinir
            # não é duplicar: `replace=True` registra sem acusar colisão.
            replace = re.match(r"CREATE OR REPLACE FUNCTION", low, re.I) is not None
            note_create("function", m.group(1), m.group(2), f, replace=replace)
        m = re.match(r"CREATE (?:UNLOGGED )?TABLE (?:IF NOT EXISTS )?" + QUAL, low, re.I)
        if m:
            note_create("table", m.group(1), m.group(2), f)
            body = outer_parens(stmt)
            if body is None:
                errors.append(f"{f}: CREATE TABLE {m.group(1)}.{m.group(2)} sem parênteses parseáveis")
            else:
                table_cols[(m.group(1), m.group(2))] = parse_table_columns(body)
                # tipos de coluna schema-qualificados existem e vieram antes?
                for coldef in split_top_commas(body):
                    toks = coldef.split()
                    if len(toks) >= 2 and toks[0].upper() not in {"CONSTRAINT","PRIMARY","UNIQUE","CHECK","FOREIGN","LIKE","EXCLUDE"}:
                        tm = re.fullmatch(QUAL, toks[1].rstrip(","))
                        if tm:
                            check_ref(["type"], tm.group(1), tm.group(2), f,
                                      f"coluna {m.group(1)}.{m.group(2)}.{toks[0]}")
        am = re.match(r"ALTER TABLE\s+(?:ONLY\s+)?" + QUAL, low, re.I)
        if am:
            # Um ALTER TABLE pode trazer várias cláusulas ADD COLUMN separadas por
            # vírgula; a versão anterior enxergava só a primeira e acusava as demais
            # como coluna inexistente nos testes.
            cols = table_cols.get((am.group(1), am.group(2)))
            if cols is not None:
                for cm in re.finditer(r"ADD COLUMN\s+(?:IF NOT EXISTS\s+)?([a-z_][a-z0-9_]*)", low, re.I):
                    cols.add(cm.group(1))
        m = re.match(r"CREATE (?:OR REPLACE )?(?:MATERIALIZED )?VIEW " + QUAL, low, re.I)
        if m:
            # REPLACE não cria objeto novo: registrar de novo acusaria "criado duas vezes"
            # em toda reescrita legítima.
            if "or replace" not in low[:40].lower():
                note_create("table", m.group(1), m.group(2), f)   # referenciável como relação
            # [F19] `CREATE OR REPLACE VIEW` SUBSTITUI as reloptions em vez de mesclá-las:
            # omitir `WITH (security_invoker = true)` na reescrita DERRUBA a flag, e a view
            # passa a rodar com os direitos do dono, que tem BYPASSRLS. Foi o que aconteceu
            # com `diagnostics.v_client_profile` (44, 45, 47) e `context.v_fact_coverage`
            # (43): sob `plexo_app`, uma sessão de um cliente enxergava 9 e 22 escopos.
            # A regex anterior casava só `CREATE VIEW`, então nenhuma das quatro reescritas
            # foi olhada. Materialized view não aceita a opção — fica de fora.
            if (m.group(1) in SCHEMAS_COM_DADO_DE_CLIENTE
                    and "materialized" not in low.split("view")[0].lower()
                    and "security_invoker" not in low
                    and (f, f"{m.group(1)}.{m.group(2)}") not in REESCRITAS_SEM_INVOKER_JA_REPARADAS):
                errors.append(
                    f"{f}: VIEW {m.group(1)}.{m.group(2)} sem WITH (security_invoker = true) — "
                    f"view de dado de cliente roda com BYPASSRLS do dono sem essa cláusula, e "
                    f"REPLACE não a herda da versão anterior")
        # funções dentro de DO $$ ... EXECUTE 'CREATE FUNCTION core.new_id()...'
        if re.match(r"DO\b", low, re.I):
            for dm in re.finditer(r"CREATE FUNCTION " + QUAL, stmt, re.I):
                note_create("function", dm.group(1), dm.group(2), f)
        # --- checagens de referência ----------------------------------------
        bodies = re.findall(r"\$[A-Za-z_]*\$(.*?)\$[A-Za-z_]*\$", stmt, re.S)
        body_text = "\n".join(bodies)
        masked = re.sub(r"\$[A-Za-z_]*\$.*?\$[A-Za-z_]*\$", " ", stmt, flags=re.S)
        for rm in re.finditer(r"\b(?:INSERT INTO|UPDATE|DELETE FROM|FROM|JOIN)\s+" + QUAL, body_text, re.I):
            sch, nm = rm.group(1), rm.group(2)
            if sch in SCHEMAS and not any(created.get(("table", sch, nm)) for _ in [0]) and f in ORDER:
                # diferida: basta existir em algum lugar do conjunto — checada no passe final
                deferred.append((f, sch, nm))
        for rm in re.finditer(r"\bREFERENCES\s+" + QUAL, masked, re.I):
            check_ref(["table"], rm.group(1), rm.group(2), f, "FK")
        for rm in re.finditer(r"EXECUTE FUNCTION\s+" + QUAL, masked, re.I):
            check_ref(["function"], rm.group(1), rm.group(2), f, "trigger")
        for rm in re.finditer(r"\b(?:INSERT INTO|UPDATE|DELETE FROM)\s+" + QUAL, masked, re.I):
            check_ref(["table"], rm.group(1), rm.group(2), f, "DML")
        for rm in re.finditer(r"\b(?:FROM|JOIN)\s+" + QUAL, masked, re.I):
            check_ref(["table"], rm.group(1), rm.group(2), f, "leitura")
        # tipos qualificados em posição de tipo: "col schema.tipo" — heurística:
        # --- INSERTs: colunas existem? ---------------------------------------
        im = re.match(r"INSERT INTO\s+" + QUAL + r"\s*\(([^)]*)\)", stmt, re.I)
        if im:
            sch, tbl = im.group(1), im.group(2)
            cols = [c.strip().strip('"') for c in im.group(3).split(",")]
            known = table_cols.get((sch, tbl))
            if known is not None:
                for c in cols:
                    if c and c not in known:
                        errors.append(f"{f}: INSERT em {sch}.{tbl} usa coluna inexistente '{c}'")
        um = re.match(r"UPDATE\s+" + QUAL + r"\s+SET\s+(.*)", stmt, re.I | re.S)
        if um:
            sch, tbl = um.group(1), um.group(2)
            known = table_cols.get((sch, tbl))
            if known is not None:
                setpart = um.group(3).split(" WHERE ")[0]
                for cm in re.finditer(r"(?:^|,)\s*([a-z_][a-z0-9_]*)\s*=", setpart):
                    c = cm.group(1)
                    if c not in known:
                        errors.append(f"{f}: UPDATE em {sch}.{tbl} usa coluna inexistente '{c}'")

for (f, sch, nm) in deferred:
    if ("table", sch, nm) not in created:
        errors.append(f"{f}: [CORPO] função referencia {sch}.{nm}, que não existe em lugar nenhum")

# --- cobertura de RLS: toda tabela com scope_id ou user_id precisa de ENABLE ROW LEVEL SECURITY
RLS_EXCEPTIONS = {("analytics", "events")}   # eventos anônimos pré-cadastro; escrita via serviço (README §5.4)
rls_enabled = set()
for f in ORDER:
    raw = path_of(f).read_text(encoding="utf-8")
    for m in re.finditer(r"ALTER TABLE\s+" + QUAL + r"\s+ENABLE ROW LEVEL SECURITY", raw, re.I):
        rls_enabled.add((m.group(1), m.group(2)))
    if f == "14_rls_partitions.sql":   # listas curadas dentro de DO $$ ... VALUES (('schema','tabela'), ...)
        for m in re.finditer(r"\(\s*'([a-z_]+)'\s*,\s*'([a-z_]+)'\s*\)", raw):
            rls_enabled.add((m.group(1), m.group(2)))
for (sch, tbl), cols in sorted(table_cols.items()):
    if ({"scope_id", "user_id"} & cols) and (sch, tbl) not in rls_enabled and (sch, tbl) not in RLS_EXCEPTIONS:
        errors.append(f"RLS: {sch}.{tbl} tem scope_id/user_id e nenhum ENABLE ROW LEVEL SECURITY no conjunto")

# --- contagem global sob papel de serviço: sob serviço a RLS não filtra, então `expect_count` sem
# WHERE afirma sobre o BANCO INTEIRO, não sobre as linhas da fixture. Passa enquanto a tabela está
# vazia no dev e quebra no primeiro seed (aconteceu com T43 em 2026-08-26, quando a persona da F12
# commitou duas contas). Sob plexo_app a RLS já filtra pelo GUC — por isso a checagem é só a de serviço.
for f in TESTS:
    raw = path_of(f).read_text(encoding="utf-8")
    papel, intencao = None, None
    for trecho in re.split(r"(?=RESET ROLE|SET LOCAL ROLE|SET LOCAL app\.role)", raw):
        cab = trecho[:60]
        if re.match(r"RESET ROLE", cab, re.I):
            papel = "admin"                                   # avnadmin tem BYPASSRLS
        elif (mp := re.match(r"SET LOCAL ROLE\s+(\w+)", cab, re.I)):
            papel = mp.group(1).lower()
        elif (mi := re.match(r"SET LOCAL app\.role\s*=\s*'(\w+)'", cab, re.I)):
            intencao = mi.group(1).lower()
        # `core.is_service()` exige as DUAS coisas: papel plexo_service E app.role='service'.
        # Só aí a RLS não filtra. plexo_service com app.role='user' continua preso ao GUC (T43b).
        if not (papel == "admin" or (papel == "plexo_service" and intencao == "service")):
            continue
        for m in re.finditer(r"expect_count\(\$sql\$(.*?)\$sql\$\s*,\s*(\d+)\s*,\s*'([^']*)'", trecho, re.S):
            sql_asserido, esperado, nome = " ".join(m.group(1).split()), m.group(2), m.group(3)
            alvo = re.search(r"\bfrom\s+([\w.]+)\s*(\()?", sql_asserido, re.I)
            if alvo is not None and alvo.group(2):      # função com argumento: já escopada pelo parâmetro
                continue
            if esperado != "0" and " where " not in sql_asserido.lower():
                warnings.append(f"{f}: \"{nome[:60]}\" conta a tabela inteira sob papel sem RLS "
                                f"(esperado {esperado}, sem WHERE) — escope pelos ids da fixture")

print(f"objetos criados: {len(created)}  · tabelas c/ colunas parseadas: {len(table_cols)}")
print(f"erros: {len(errors)}  · avisos: {len(warnings)}")
for e in errors: print("ERRO ", e)
for w in warnings: print("aviso", w)
sys.exit(1 if errors else 0)
