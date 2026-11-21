"""NBP rates connector (#34) against a fake NBP that keeps the real API's rules, and the real tables."""
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from psycopg.types.json import Jsonb

from backend.connectors import main as connectors
from backend.connectors.base import run_once
from backend.connectors.nbp import NbpConnector, history, rate_on
from backend.db.contracts import MODELS
from backend.db.store import Store

TODAY = date(2026, 11, 20)  # a Friday
HOLIDAYS = {date(2024, 11, 11), date(2024, 12, 25), date(2024, 12, 26), date(2025, 1, 1), date(2025, 1, 6),
            date(2025, 11, 11), date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1), date(2026, 1, 6),
            date(2026, 11, 11)}
FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def is_table_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


class FakeNbp:
    """GET /api/exchangerates/tables/A/{start}/{end}/ like api.nbp.pl: 400 over 93 days or in the future, 404 when the
    range holds no table, else one table per business day with EUR, USD and CHF."""

    def __init__(self, today: date = TODAY):
        self.today = today
        self.requests: list[tuple[date, date]] = []
        self.down = 0  # answer this many requests with a connection error
        self.status: int | None = None  # answer every request with this status

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            self.down -= 1
            raise httpx.ConnectError("connection refused", request=request)
        if self.status:
            return httpx.Response(self.status)
        parts = request.url.path.strip("/").split("/")
        start, end = date.fromisoformat(parts[-2]), date.fromisoformat(parts[-1])
        self.requests.append((start, end))
        if (end - start).days + 1 > 93 or end > self.today or start > end:
            return httpx.Response(400, text="400 BadRequest - Błędny zakres dat / Invalid date range")
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        tables = [self.table(d) for d in days if is_table_day(d)]
        if not tables:
            return httpx.Response(404, text="404 NotFound - Not Found - Brak danych")
        return httpx.Response(200, json=tables)

    @staticmethod
    def table(d: date) -> dict:
        n = d.toordinal() % 1000
        return {"table": "A", "no": f"{n:03d}/A/NBP/{d.year}", "effectiveDate": d.isoformat(),
                "rates": [{"currency": "euro", "code": "EUR", "mid": 4.30 + n / 10000},
                          {"currency": "dolar amerykański", "code": "USD", "mid": 3.90 + n / 10000},
                          {"currency": "frank szwajcarski", "code": "CHF", "mid": 4.60 + n / 10000}]}


@pytest.fixture
def nbp():
    fake = FakeNbp()
    with httpx.Client(base_url="https://api.nbp.pl", transport=httpx.MockTransport(fake.handler)) as client:
        yield fake, client


@pytest.fixture
def source(db):
    """src_nbp exactly as contracts/fixtures/source.json has it: an invented cursor, 3 years of history."""
    src = next(s for s in json.loads((FIXTURES / "source.json").read_text(encoding="utf-8")) if s["id"] == "src_nbp")
    src = {**src, "next_run_at": None}
    db.execute("insert into sources (id, company_id, doc) values (%s, %s, %s)", (src["id"], src["company_id"], Jsonb(src)))
    db.commit()
    return src


def poll(db, source, nbp, today=TODAY, waited=None):
    fake, client = nbp
    return run_once(db, NbpConnector(Store(db).get("source", source["id"]), client, today=today),
                    sleep=(waited.append if waited is not None else lambda s: None))


def expected_tables(since: date, until: date) -> int:
    return sum(1 for i in range((until - since).days + 1) if is_table_day(since + timedelta(days=i)))


# ---------- acceptance: 3 years of history ----------
def test_first_run_reads_three_years_in_93_day_windows(db, source, nbp):
    fake, _ = nbp
    result = poll(db, source, nbp)
    want = expected_tables(TODAY - timedelta(days=1095), TODAY)
    assert result["status"] == "success" and result["items_new"] == want
    assert all((e - s).days + 1 <= 93 and e <= TODAY for s, e in fake.requests)  # never a request NBP refuses
    src = Store(db).get("source", "src_nbp")
    assert src["cursor"] == f"2026-11-20|{FakeNbp.table(TODAY)['no']}" and src["items_total"] == want
    for code in ("EUR", "USD", "CHF"):
        assert 740 <= len(history(db, code)) == want <= 790  # "about 756 daily rates per currency"


def test_tables_are_raw_items_of_the_contract(db, source, nbp):
    poll(db, source, nbp, today=date(2026, 11, 20))
    item = max(Store(db).list("raw_item", source_id="src_nbp"), key=lambda i: i["payload"]["effectiveDate"])
    MODELS["raw_item"].model_validate(item)
    assert item["kind"] == "fx_rate_table" and item["external_id"].endswith("/A/NBP/2026")
    assert set(item["payload"]["rates"]) == {"EUR", "USD", "CHF"}
    assert item["payload"]["rates"]["USD"] == f"{3.90 + (date.fromisoformat(item['payload']['effectiveDate']).toordinal() % 1000) / 10000:.4f}"


# ---------- acceptance: idempotent by table number ----------
def test_second_run_and_a_re_read_create_nothing(db, source, nbp):
    first = poll(db, source, nbp)
    assert poll(db, source, nbp)["items_new"] == 0
    db.execute("""update sources set doc = doc || '{"cursor": null}'::jsonb where id = 'src_nbp'""")
    db.commit()
    again = poll(db, source, nbp)
    assert again["items_new"] == 0 and again["items_duplicate"] == first["items_new"]


def test_the_next_business_day_brings_one_table(db, source, nbp):
    fake, _ = nbp
    poll(db, source, nbp)
    fake.today = date(2026, 11, 23)  # Monday
    result = poll(db, source, nbp, today=date(2026, 11, 23))
    assert result["items_new"] == 1
    assert Store(db).get("source", "src_nbp")["cursor"].startswith("2026-11-23|")


# ---------- acceptance: the last business day before ----------
def test_rate_on_sunday_and_on_11_november_is_the_last_business_day_before(db, source, nbp):
    poll(db, source, nbp)
    sunday = rate_on(db, "USD", date(2026, 11, 22))
    assert sunday["rate_date"] == "2026-11-20"
    holiday_after = rate_on(db, "usd", date(2026, 11, 12))  # 11 Nov is a holiday
    assert holiday_after["rate_date"] == "2026-11-10"
    assert holiday_after["source"] == f"NBP table A {FakeNbp.table(date(2026, 11, 10))['no']}"
    assert holiday_after["rule"] == "pl_tax_prev_business_day"
    assert holiday_after["rate"] == f"{3.90 + date(2026, 11, 10).toordinal() % 1000 / 10000:.4f}"


def test_booking_day_rule_takes_the_same_day(db, source, nbp):
    poll(db, source, nbp)
    assert rate_on(db, "EUR", date(2026, 11, 20), rule="booking_day")["rate_date"] == "2026-11-20"
    assert rate_on(db, "EUR", date(2026, 11, 20))["rate_date"] == "2026-11-19"
    assert rate_on(db, "EUR", date(2026, 11, 22), rule="booking_day")["rate_date"] == "2026-11-20"


def test_rate_on_follows_the_contract_shape_and_unknowns(db, source, nbp):
    poll(db, source, nbp)
    found = rate_on(db, "CHF", date(2026, 11, 20))
    from backend.db.models.common_schema import FxConversion
    FxConversion.model_validate(found)
    assert rate_on(db, "XYZ", date(2026, 11, 20)) is None
    assert rate_on(db, "EUR", date(2020, 1, 1)) is None  # before the history
    assert rate_on(db, "PLN", date(2026, 11, 20))["rate"] == "1"


# ---------- weekends and holidays (found on the cluster) ----------
SATURDAY = date(2026, 11, 21)


def test_a_weekend_is_not_asked_for_and_does_not_degrade_the_source(db, source, nbp):
    fake, _ = nbp
    poll(db, source, nbp)  # history up to Friday 20 Nov
    asked = len(fake.requests)
    fake.today = SATURDAY
    fake.status = 500  # what api.nbp.pl answered for a day without a table
    result = poll(db, source, nbp, today=SATURDAY)
    assert result["status"] == "success" and result["items_new"] == 0
    assert len(fake.requests) == asked  # a Saturday-only window is never requested
    assert fake.status == 500 and Store(db).get("source", "src_nbp")["status"] == "connected"


def test_an_error_on_a_short_window_after_the_last_table_is_nothing_new_not_an_outage(db, source, nbp):
    """A holiday (11 Nov 2026 is a Wednesday): NBP answers 500 for it; the source stays connected."""
    fake, _ = nbp
    poll(db, source, nbp, today=date(2026, 11, 10))
    fake.status = 500
    result = poll(db, source, nbp, today=date(2026, 11, 11))
    assert result["status"] == "success" and result["items_new"] == 0
    assert Store(db).get("source", "src_nbp")["status"] == "connected"


def test_a_real_outage_on_the_first_read_is_still_an_error(db, source, nbp):
    fake, _ = nbp
    fake.status = 500
    waited = []
    result = poll(db, source, nbp, waited=waited)  # no table stored yet: the long history window fails
    assert result["status"] == "failed" and waited == [5, 20, 60]
    assert Store(db).get("source", "src_nbp")["status"] == "degraded"


# ---------- GET /api/v1/fx/rates ----------
def test_the_api_serves_the_stored_nbp_rate_and_falls_back_before_it(db, db_url, source, nbp):
    from fastapi.testclient import TestClient

    from backend.api.app import create_app
    from backend.db.seed import seed

    seed(db)
    with TestClient(create_app(database_url=db_url)) as api:
        before = api.get("/api/v1/fx/rates", params={"currency": "USD", "date": "2026-11-12"}).json()
        assert before["source"].startswith("Demo-day rate")  # nothing stored yet: role 5's stand-in answers
        poll(db, source, nbp)
        after = api.get("/api/v1/fx/rates", params={"currency": "USD", "date": "2026-11-12"}).json()
        assert after["rate_date"] == "2026-11-10" and after["source"].startswith("NBP table A ")
        booking = api.get("/api/v1/fx/rates", params={"currency": "EUR", "date": "2026-11-20", "rule": "booking_day"}).json()
        assert booking["rate_date"] == "2026-11-20"


# ---------- failures ----------
def test_nbp_down_is_retried_then_degraded(db, source, nbp):
    fake, _ = nbp
    fake.down = 10
    waited = []
    result = poll(db, source, nbp, waited=waited)
    assert waited == [5, 20, 60] and result["status"] == "failed" and result["error"]["code"] == "nbp_unreachable"
    assert Store(db).get("source", "src_nbp")["status"] == "degraded"


def test_a_short_outage_is_survived(db, source, nbp):
    fake, _ = nbp
    fake.down = 1
    assert poll(db, source, nbp)["status"] == "success"


def test_a_bad_request_is_not_retried(db, source, nbp):
    fake, _ = nbp
    fake.status = 400
    waited = []
    result = poll(db, source, nbp, waited=waited)
    assert waited == [] and result["error"]["code"] == "http_400"
    assert Store(db).get("source", "src_nbp")["status"] == "error"


# ---------- the process ----------
def test_the_connector_process_polls_src_nbp(db, source, nbp):
    fake, client = nbp
    fake.today = datetime.now(UTC).date()  # the process uses the real date
    with httpx.Client(base_url="http://bank.invalid") as bank:
        done = connectors.tick(db, bank, now=datetime(2026, 11, 20, 13, 0, tzinfo=UTC), first=True,
                               sleep=lambda s: None, nbp=client)
    nbp_runs = [r for r in done if r["source_id"] == "src_nbp"]
    assert len(nbp_runs) == 1 and nbp_runs[0]["status"] == "success" and nbp_runs[0]["items_new"] > 700


def test_without_an_nbp_client_the_source_is_left_alone(db, source):
    with httpx.Client(base_url="http://bank.invalid") as bank:
        assert connectors.tick(db, bank, now=datetime.now(UTC), first=True, sleep=lambda s: None) == []
