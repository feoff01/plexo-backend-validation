"""
db_runner.py — substituto do `psql -v ON_ERROR_STOP=1 -f arquivo.sql` quando não há psql.

Uso (a partir de qualquer diretório):
    python tools/db_runner.py schemas              # lista schemas; avisa se algum do projeto já existe
    python tools/db_runner.py apply                # aplica sql/*.sql em ordem alfabética, para no 1º erro
    python tools/db_runner.py tests [papel]        # roda tests/*.sql; opcional: SET ROLE plexo_service
    python tools/db_runner.py inventory            # contagens por schema (tabelas, enums, triggers, ...)
    python tools/db_runner.py reset                # DROP CASCADE dos 23 schemas do projeto + public.alembic_version

Regras:
- Lê DATABASE_URL de plexo-backend/.env. NUNCA imprime a string (host/usuário/senha são
  redigidos de qualquer mensagem de erro).
- Aceita formato SQLAlchemy (postgresql+psycopg://) e converte; assume sslmode=require (Aiven)
  quando a URL não declara um.
- Executa cada arquivo inteiro em autocommit: o BEGIN;/COMMIT; do próprio arquivo manda na
  transação (mesma semântica do psql). Ignora `\\set`, imprime `\\echo`, captura RAISE NOTICE.
- Nunca derruba o database (é gerenciado): reset = schemas do projeto, nada de `public`.

Caminho "oficial" de aplicação é o Alembic (`python -m alembic upgrade head`); este runner serve
para validação rápida, testes e reset. Os dois produzem o mesmo banco (provado em 2026-08-22).
"""
import sys, re, io, pathlib, urllib.parse
from dotenv import dotenv_values
import psycopg

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent      # plexo-backend/
SQL_DIR, TESTS_DIR = ROOT / "sql", ROOT / "tests"
PROJECT_SCHEMAS = sorted("""agents analysis analytics audit billing budget content context copilot core
decisions diagnostics docs engine estate household identity ledger llm market
planning preferences tools wealth""".split())

# ------------------------------------------------------------------ conexão
def _conninfo():
    env = dotenv_values(ROOT / ".env")
    url = env.get("DATABASE_URL") or ""
    if not url:
        sys.exit("DATABASE_URL ausente em plexo-backend/.env")
    url = re.sub(r"^postgres(ql)?\+[a-z0-9]+://", "postgresql://", url)
    parts = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(parts.query))
    q.setdefault("sslmode", "require")   # `setdefault`, como alembic/env.py e Settings: o Aiven exige
                                        # TLS e continua ganhando, mas uma URL que declara `sslmode`
                                        # (Postgres local do CI, sem TLS) deixa de ser sobrescrita.
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))
    secrets = [s for s in (parts.password, parts.hostname, parts.username) if s]
    return url, secrets

URL, SECRETS = _conninfo()

def redact(txt):
    txt = str(txt)
    for s in SECRETS:
        txt = txt.replace(s, "***")
    return txt

def connect():
    conn = psycopg.connect(URL, autocommit=True)
    conn.add_notice_handler(lambda d: print(f"  {d.severity}: {d.message_primary}"))
    return conn

# ------------------------------------------------------------------ execução de arquivo
def _prep(text):
    """Remove \\set; transforma \\echo em print; preserva numeração de linhas."""
    out, echoes = [], {}
    for i, line in enumerate(text.splitlines(), 1):
        s = line.lstrip()
        if s.startswith("\\set"):
            out.append("")
        elif s.startswith("\\echo"):
            echoes[i] = s[len("\\echo"):].strip().strip("'")
            out.append("")
        else:
            out.append(line)
    return "\n".join(out), echoes

def run_file(conn, path):
    text = path.read_text(encoding="utf-8")
    sql, echoes = _prep(text)
    try:
        conn.execute(sql)
    except psycopg.Error as e:
        d = e.diag
        line = None
        if d.statement_position:
            line = sql[: int(d.statement_position)].count("\n") + 1
        print(f"\n*** ERRO em {path.name}" + (f" linha {line}" if line else ""))
        print(f"    SQLSTATE {d.sqlstate}: {redact(d.message_primary)}")
        if d.message_detail: print(f"    DETAIL: {redact(d.message_detail)}")
        if d.message_hint:   print(f"    HINT:   {redact(d.message_hint)}")
        if d.context:        print(f"    CONTEXT: {redact(d.context)}")
        return False
    for _, msg in sorted(echoes.items()):
        print(msg)
    return True

# ------------------------------------------------------------------ subcomandos
def cmd_schemas(conn):
    rows = conn.execute("""select nspname from pg_namespace
                           where nspname not like 'pg\\_%' and nspname <> 'information_schema'
                           order by 1""").fetchall()
    names = [r[0] for r in rows]
    print("schemas existentes:", ", ".join(names))
    clash = sorted(set(names) & set(PROJECT_SCHEMAS))
    print("schemas do projeto já presentes:", ", ".join(clash) if clash else "(nenhum)")
    return not clash

def cmd_apply(conn):
    for f in sorted(SQL_DIR.glob("*.sql")):
        print(f"== {f.name}")
        if not run_file(conn, f):
            return False
    print("\nTODAS AS MIGRATIONS APLICADAS")
    return True

def cmd_tests(conn):
    # Uso: tests [papel] [arquivo.sql ...] — argumentos terminados em .sql filtram a suíte
    # (verificação direcionada durante uma fase); sem eles roda tudo, como sempre.
    ok = True
    extras = sys.argv[2:]
    somente = {a for a in extras if a.endswith(".sql")}
    papeis = [a for a in extras if not a.endswith(".sql")]
    role = papeis[0] if papeis else None
    arquivos = [f for f in sorted(TESTS_DIR.glob("*.sql")) if not somente or f.name in somente]
    faltando = somente - {f.name for f in arquivos}
    if faltando:
        print(f"arquivo(s) de teste inexistente(s): {', '.join(sorted(faltando))}")
        return False
    for f in arquivos:
        print(f"\n===== {f.name}" + (f" (SET ROLE {role})" if role else "") + " =====")
        if role:
            conn.execute(f"SET ROLE {role}")
        if not run_file(conn, f):
            ok = False
        conn.close(); conn = connect()   # sessão limpa por arquivo (papel, GUCs, transação)
    return ok

def cmd_inventory(conn):
    q = """
    with s as (select unnest(%s::text[]) as nsp)
    select s.nsp,
      (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
         where n.nspname=s.nsp and c.relkind in ('r','p') and not c.relispartition) as tabelas,
      (select count(*) from pg_type t join pg_namespace n on n.oid=t.typnamespace
         where n.nspname=s.nsp and t.typtype='e') as enums,
      (select count(*) from pg_type t join pg_namespace n on n.oid=t.typnamespace
         where n.nspname=s.nsp and t.typtype='d') as domains,
      (select count(*) from pg_trigger tg join pg_class c on c.oid=tg.tgrelid
         join pg_namespace n on n.oid=c.relnamespace
         where n.nspname=s.nsp and not tg.tgisinternal and tg.tgparentid=0) as triggers,
      (select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace
         where n.nspname=s.nsp) as funcoes,
      (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
         where n.nspname=s.nsp and c.relkind='v') as views,
      (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
         where n.nspname=s.nsp and c.relkind='m') as matviews,
      (select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace
         where n.nspname=s.nsp and c.relkind in ('i','I') and not c.relispartition) as indices,
      (select count(*) from pg_policy pol join pg_class c on c.oid=pol.polrelid
         join pg_namespace n on n.oid=c.relnamespace where n.nspname=s.nsp) as policies
    from s order by 1"""
    rows = conn.execute(q, (PROJECT_SCHEMAS,)).fetchall()
    hdr = ("schema","tabelas","enums","domains","triggers","funcoes","views","matviews","indices","policies")
    print(" | ".join(f"{h:>9}" if i else f"{h:<12}" for i,h in enumerate(hdr)))
    tot = [0]*9
    for r in rows:
        print(" | ".join(f"{v:>9}" if i else f"{v:<12}" for i,v in enumerate(r)))
        for i in range(9): tot[i] += r[i+1]
    print(" | ".join(f"{v:>9}" if i else f"{v:<12}" for i,v in enumerate(["TOTAL"]+tot)))
    parts = conn.execute("select count(*) from pg_class where relispartition and relkind='r'").fetchone()[0]
    print(f"\n(partições filhas, fora da contagem: {parts})")
    print("extensões:", ", ".join(e[0] for e in conn.execute("select extname from pg_extension order by 1")))
    try:
        print("alembic_version:", conn.execute("select version_num from public.alembic_version").fetchone()[0])
    except psycopg.Error:
        print("alembic_version: (tabela ausente — banco aplicado via runner, não via Alembic)")

def cmd_reset(conn):
    existing = {r[0] for r in conn.execute("select nspname from pg_namespace").fetchall()}
    for s in PROJECT_SCHEMAS:
        if s in existing:
            conn.execute(f'drop schema "{s}" cascade')
            print("drop schema", s)
    conn.execute("drop table if exists public.alembic_version")   # tabela de versão do Alembic (nossa)
    print("reset concluído (schemas do projeto + public.alembic_version)")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "schemas"
    try:
        conn = connect()
    except psycopg.Error as e:
        sys.exit("falha de conexão: " + redact(e))
    fn = {"schemas": cmd_schemas, "apply": cmd_apply, "tests": cmd_tests,
          "inventory": cmd_inventory, "reset": cmd_reset}[cmd]
    rc = fn(conn)
    sys.exit(0 if rc in (None, True) else 1)
