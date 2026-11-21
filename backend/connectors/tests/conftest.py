import pytest


@pytest.fixture(autouse=True)
def _no_real_mailbox(monkeypatch):
    """settings.py loads the developer's .env at import; cleared here so no test reads the real invoices mailbox."""
    for name in ("ORDO_IMAP_USER", "ORDO_IMAP_PASSWORD", "ORDO_IMAP_HOST", "ORDO_IMAP_PORT", "ORDO_IMAP_FOLDER"):
        monkeypatch.delenv(name, raising=False)
