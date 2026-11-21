"""The invoices mailbox as a Source: its address shown to the app, and limiting the process to some connectors."""
import httpx

from backend.connectors import main
from backend.connectors.mailbox import ImapConnector
from backend.db.fixtures import load_fixtures
from backend.db.store import Store


def test_a_configured_mailbox_puts_its_address_on_the_source(db, monkeypatch):
    load_fixtures(db)
    monkeypatch.setenv("ORDO_IMAP_USER", "Invoices.Demo@Example.test")
    monkeypatch.setenv("ORDO_IMAP_PASSWORD", "app-password")
    source = Store(db).get("source", "src_mail")

    connector = main.build_connector(db, source, httpx.Client())

    assert isinstance(connector, ImapConnector)
    assert Store(db).get("source", "src_mail")["config_public"]["mailbox"] == "invoices.demo@example.test"


def test_without_credentials_the_mailbox_is_left_alone(db, monkeypatch):
    load_fixtures(db)
    monkeypatch.delenv("ORDO_IMAP_USER", raising=False)
    monkeypatch.delenv("ORDO_IMAP_PASSWORD", raising=False)
    before = Store(db).get("source", "src_mail")

    assert main.build_connector(db, before, httpx.Client()) is None
    assert Store(db).get("source", "src_mail") == before


def test_connectors_only_limits_the_process(db, monkeypatch):
    load_fixtures(db)
    monkeypatch.setenv("ORDO_CONNECTORS_ONLY", "imap_mailbox, fx_rates")
    bank_source = Store(db).get("source", "src_bank_pln")

    assert main.enabled_connectors() == {"imap_mailbox", "fx_rates"}
    assert main.build_connector(db, bank_source, httpx.Client()) is None
