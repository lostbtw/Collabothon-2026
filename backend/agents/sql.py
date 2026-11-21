"""The chat's free SQL tool: one SELECT, a read-only 3 s transaction, role ordo_readonly, company-filtered views."""
import re
from decimal import Decimal
from typing import Any

import psycopg

MAX_ROWS = 200
VIEWS = ("v_ledger", "v_transactions", "v_documents", "v_accounts", "v_recommendations", "v_forecast_components")
_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_WRITES = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|grant|revoke|truncate|copy|call|do|execute|"
                     r"vacuum|analyze|set|reset|lock|listen|notify|into|refresh|comment|security|pg_sleep_for|"
                     r"set_config|dblink\w*|lo_\w+|pg_read_\w+|pg_ls_\w+|pg_terminate_\w+|pg_cancel_\w+)\b", re.I)


class UnsafeQuery(ValueError):
    pass


def guard(sql: str) -> str:
    """The query to run, or UnsafeQuery."""
    text = _COMMENTS.sub(" ", sql or "").strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    if not text:
        raise UnsafeQuery("empty query")
    if ";" in text:
        raise UnsafeQuery("only one statement is allowed")
    if not re.match(r"(?is)^(select|with)\b", text):
        raise UnsafeQuery("only SELECT or WITH queries are allowed")
    if _WRITES.search(text):
        raise UnsafeQuery("the query contains a write or session keyword")
    limits = [int(n) for n in re.findall(r"(?i)\blimit\s+(\d+)", text)]
    if re.search(r"(?i)\blimit\s+all\b", text) or any(n > MAX_ROWS for n in limits):
        raise UnsafeQuery(f"LIMIT may be at most {MAX_ROWS}")
    if not re.search(r"(?i)\blimit\s+\d+\s*(offset\s+\d+\s*)?$", text):
        text = f"{text} limit {MAX_ROWS}"
    return text


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def run_readonly_sql(conn: psycopg.Connection, company: str, sql: str) -> dict[str, Any]:
    """{"columns", "rows", "sql"} or {"error", "sql"}."""
    try:
        query = guard(sql)
    except UnsafeQuery as exc:
        return {"error": f"rejected: {exc}", "sql": sql}
    member = conn.execute("select pg_has_role(current_user, 'ordo_readonly', 'member') "
                          "from pg_roles where rolname = 'ordo_readonly'").fetchone()
    if not member or not member[0]:
        conn.rollback()
        return {"error": "the SQL tool is not configured (role ordo_readonly missing)", "sql": query}
    conn.rollback()
    try:
        with conn.transaction(force_rollback=True):  # nothing to keep, even if a write slipped through
            conn.execute("set transaction read only")
            conn.execute("set local statement_timeout = '3s'")
            conn.execute("select set_config('ordo.company_id', %s, true)", (company,))
            conn.execute("set local role ordo_readonly")
            cur = conn.execute(query)
            columns = [d.name for d in cur.description or []]
            rows = [[_plain(v) for v in row] for row in cur.fetchmany(MAX_ROWS)]
        return {"columns": columns, "rows": rows, "sql": query}
    except psycopg.Error as exc:
        return {"error": str(exc).strip().splitlines()[0], "sql": query}
