import pytest


@pytest.fixture(autouse=True)
def _no_real_mailbox(monkeypatch):
    """backend/settings.py loads the developer's .env at import: without this, a test would read the real invoices
    mailbox. Tests that need the mailbox set the variables themselves, against a fake IMAP server."""
    for name in ("ORDO_IMAP_USER", "ORDO_IMAP_PASSWORD", "ORDO_IMAP_HOST", "ORDO_IMAP_PORT", "ORDO_IMAP_FOLDER"):
        monkeypatch.delenv(name, raising=False)
