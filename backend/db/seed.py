"""Seed the demo Companies and their People. Run: `uv run python -m backend.db seed`.

People come from seed_data/people.json, a stand-in until role 4's scenario writes the full list (all invented,
marked SAMPLE, `.sample` addresses). The real phone address used in the live demo is never in Git: it arrives
through the Secret-backed environment variable ORDO_PERSON_ADDRESSES, a JSON object {"address": "per_..."}.
"""
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

DATA = Path(__file__).parent / "seed_data"
COMPANIES_FILE = DATA / "companies.json"
PEOPLE_FILE = DATA / "people.json"


def address_map_from_env() -> dict[str, str]:
    raw = os.environ.get("ORDO_PERSON_ADDRESSES", "").strip()
    return json.loads(raw) if raw else {}


def seed(conn: psycopg.Connection, address_map: dict[str, str] | None = None) -> None:
    """Insert or update Companies and People; safe to run on every deploy."""
    if address_map is None:
        address_map = address_map_from_env()
    for c in json.loads(COMPANIES_FILE.read_text(encoding="utf-8")):
        conn.execute(
            """insert into companies (id, name, base_currency, country, as_of_date, tax_id)
               values (%(id)s, %(name)s, %(base_currency)s, %(country)s, %(as_of_date)s, %(tax_id)s)
               on conflict (id) do update set name = excluded.name, base_currency = excluded.base_currency,
                 country = excluded.country, as_of_date = excluded.as_of_date, tax_id = excluded.tax_id""",
            {"tax_id": None, **c},
        )
    for p in json.loads(PEOPLE_FILE.read_text(encoding="utf-8")):
        conn.execute(
            """insert into people (id, company_id, name, email, role, pay_type, card_last4, statement_names)
               values (%(id)s, %(company_id)s, %(name)s, %(email)s, %(role)s, %(pay_type)s, %(card_last4)s, %(statement_names)s)
               on conflict (id) do update set company_id = excluded.company_id, name = excluded.name,
                 email = excluded.email, role = excluded.role, pay_type = excluded.pay_type,
                 card_last4 = excluded.card_last4, statement_names = excluded.statement_names""",
            {"pay_type": None, "card_last4": [], "statement_names": [], **p},
        )
    for address, person_id in address_map.items():
        conn.execute(
            """insert into person_addresses (address, person_id) values (lower(%s), %s)
               on conflict (address) do update set person_id = excluded.person_id""",
            (address, person_id),
        )
    conn.commit()


def companies(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.cursor(row_factory=dict_row).execute(
        "select id, name, base_currency, country, as_of_date from companies order by id desc"
    ).fetchall()
    return [{**r, "as_of_date": r["as_of_date"].isoformat()} for r in rows]


def person_for_address(conn: psycopg.Connection, address: str) -> dict[str, Any] | None:
    """The Person who sends from this address: their own e-mail or a Secret-mapped extra address."""
    return conn.cursor(row_factory=dict_row).execute(
        """select p.id, p.company_id, p.name, p.email, p.role from people p
           where lower(p.email) = lower(%(a)s)
              or p.id = (select person_id from person_addresses where address = lower(%(a)s))""",
        {"a": address},
    ).fetchone()
