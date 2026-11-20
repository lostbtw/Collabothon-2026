"""Seams: the SQL guard (pure) and run_readonly_sql on a real Postgres (5.7b)."""
import pytest

from backend.agents.sql import UnsafeQuery, guard, run_readonly_sql
from backend.db.fixtures import load_fixtures


@pytest.mark.parametrize("sql", [
    "DELETE FROM v_ledger",
    "select 1; delete from recommendations",
    "select * from v_ledger limit 500",
    "update recommendations set status = 'approved'",
    "with x as (delete from recommendations returning *) select * from x",
    "select 1 -- comment\n; drop table people",
    "",
])
def test_unsafe_or_over_limit_queries_are_rejected(sql):
    with pytest.raises(UnsafeQuery):
        guard(sql)


def test_a_select_without_limit_gets_limit_200():
    assert guard("select * from v_ledger").endswith("limit 200")


def test_a_select_with_a_small_limit_is_kept():
    assert guard("WITH t AS (select 1) select * from t limit 5;") == "WITH t AS (select 1) select * from t limit 5"


def test_the_sql_tool_reads_only_the_companys_rows_of_its_views(db):
    load_fixtures(db)

    result = run_readonly_sql(db, "co_borsuk", "select id, category from v_ledger order by id")

    assert result["columns"] == ["id", "category"]
    assert [r[0] for r in result["rows"]] == ["led_412a", "led_412b"]
    assert run_readonly_sql(db, "co_amalfi", "select id from v_ledger")["rows"] == []


def test_the_sql_tool_cannot_see_tables_outside_its_views(db):
    load_fixtures(db)

    result = run_readonly_sql(db, "co_borsuk", "select * from people")

    assert "error" in result


def test_a_slow_query_stops_after_three_seconds(db):
    result = run_readonly_sql(db, "co_borsuk", "select pg_sleep(5)")

    assert "statement timeout" in result["error"]
