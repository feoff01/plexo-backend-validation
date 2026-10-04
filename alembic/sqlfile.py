"""Executa um arquivo de sql/ dentro de uma revision Alembic.

- Remove APENAS o BEGIN;/COMMIT; externo (coluna zero) — o Alembic gerencia a
  transação (transaction_per_migration). Qualquer outra coisa vai ao servidor
  intacta.
- Executa pela conexão do DRIVER (psycopg3) sem parâmetros: protocolo simples,
  vários comandos por chamada, nenhum parser de `:bind` (text()) nem de `%`
  (exec_driver_sql entrega parâmetros vazios e o psycopg trataria o `%I` dos
  format() como placeholder). O texto chega ao servidor byte a byte como está
  no arquivo, dentro da transação que o Alembic abriu para a revision.
"""
import re
from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

_BEGIN = re.compile(r"^BEGIN;[ \t]*$", re.M)
_COMMIT = re.compile(r"^COMMIT;[ \t]*$", re.M)

def strip_outer_transaction(sql: str, name: str) -> str:
    b = list(_BEGIN.finditer(sql)); c = list(_COMMIT.finditer(sql))
    if len(b) != 1 or len(c) != 1:
        raise RuntimeError(f"{name}: esperado exatamente 1 BEGIN; e 1 COMMIT; em coluna zero "
                           f"(achei {len(b)}/{len(c)})")
    if b[0].start() > c[0].start():
        raise RuntimeError(f"{name}: COMMIT; antes de BEGIN;")
    # substitui por linha vazia para preservar numeração de linhas nos erros
    return sql[:b[0].start()] + sql[b[0].end():c[0].start()] + sql[c[0].end():]

def run_sql_file(name: str) -> None:
    path = SQL_DIR / name
    sql = strip_outer_transaction(path.read_text(encoding="utf-8"), name)
    raw = op.get_bind().connection.driver_connection   # psycopg.Connection, mesma transação
    with raw.cursor() as cur:
        cur.execute(sql)
