"""Mailbox connector (#33) against a fake IMAP server (imaplib's answers, read-only) and the real tables."""
import imaplib
import json
from email.message import EmailMessage
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb

from backend.connectors import main as connectors
from backend.connectors.base import run_once
from backend.connectors.mailbox import ImapConnector, message_items, parse_cursor
from backend.db.contracts import MODELS
from backend.db.store import Store

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
SETTINGS = {"host": "imap.example.test", "port": 993, "user": "invoices@borsuk-labs.sample", "password": "x",
            "folder": "INBOX"}
PHOTO = b"\xff\xd8\xff\xe0" + b"JPEG-SAMPLE" * 3000  # ~33 kB, a "photo"
LOGO = b"\x89PNG" + b"x" * 500  # a small signature image
FA3 = (b'<?xml version="1.0" encoding="UTF-8"?>\n<Faktura xmlns="http://crd.gov.pl/wzor/2025/06/25/13775/">'
       b"<Naglowek/></Faktura>")


class FakeImap:
    """The parts of imaplib.IMAP4_SSL the connector uses, with imaplib's return shapes."""

    def __init__(self, messages=None, *, validity="1001", password="x"):
        self.messages: dict[int, bytes] = dict(messages or {})
        self.validity = validity
        self.password = password
        self.selected_readonly = None
        self.logged_out = 0
        self.seen_flags_changed = False

    def __call__(self, host, port):  # the factory
        return self

    def login(self, user, password):
        if password != self.password:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"LOGIN completed"]

    def select(self, folder, readonly=False):
        self.selected_readonly = readonly
        return ("OK", [str(len(self.messages)).encode()]) if folder == "INBOX" else ("NO", [b"no such folder"])

    def response(self, code):
        return code, [self.validity.encode()]

    def uid(self, command, *args):
        if command == "search":
            low = int(args[1].split()[1].split(":")[0])
            found = [u for u in sorted(self.messages) if u >= low] or ([max(self.messages)] if self.messages else [])
            return "OK", [" ".join(map(str, found)).encode()]
        if command == "fetch":
            uid = int(args[0])
            if "PEEK" not in args[1]:
                self.seen_flags_changed = True
            return "OK", [(f"{uid} (UID {uid} BODY[] {{n}}".encode(), self.messages[uid]), b")"]
        raise AssertionError(command)

    def logout(self):
        self.logged_out += 1
        return "BYE", [b""]


def mail(uid, *, sender="jan@borsuk-labs.sample", subject="Fwd: monitor do biura", body="Faktura w zalaczniku",
         files=(), message_id=None) -> bytes:
    m = EmailMessage()
    m["From"] = f"Jan Kowalski (SAMPLE) <{sender}>"
    m["To"] = "invoices@borsuk-labs.sample"
    m["Subject"] = subject
    m["Date"] = "Fri, 20 Nov 2026 10:14:21 +0100"
    m["Message-ID"] = message_id or f"<msg-{uid}@mail.example.test>"
    m.set_content(body)
    for name, ctype, data, inline in files:
        maintype, subtype = ctype.split("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name,
                         disposition="inline" if inline else "attachment")
    return m.as_bytes()


@pytest.fixture
def source(db):
    """src_mail as contracts/fixtures/source.json has it: an invented cursor UIDVALIDITY=7;UID=412."""
    src = next(s for s in json.loads((FIXTURES / "source.json").read_text(encoding="utf-8")) if s["id"] == "src_mail")
    src = {**src, "next_run_at": None, "items_total": 0}
    db.execute("insert into sources (id, company_id, doc) values (%s, %s, %s)", (src["id"], src["company_id"], Jsonb(src)))
    db.commit()
    return src


def poll(db, imap, waited=None):
    src = Store(db).get("source", "src_mail")
    return run_once(db, ImapConnector(src, settings=SETTINGS, imap_factory=imap),
                    sleep=(waited.append if waited is not None else lambda s: None))


def items(db):
    return {i["external_id"]: i for i in Store(db).list("raw_item", source_id="src_mail")}


def content(db, raw_id):
    row = db.execute("select content_type, bytes from raw_item_content where raw_item_id = %s", (raw_id,)).fetchone()
    return (row[0], bytes(row[1])) if row else None


# ---------- acceptance: a forwarded photo = one e-mail + one attachment ----------
def test_a_forwarded_photo_becomes_one_email_and_one_attachment(db, source):
    imap = FakeImap({1: mail(1, files=[("IMG_2041.jpg", "image/jpeg", PHOTO, False)])})
    result = poll(db, imap)
    assert result["status"] == "success" and result["items_new"] == 2
    got = items(db)
    email_item, photo = got["<msg-1@mail.example.test>"], got["<msg-1@mail.example.test>#1"]
    assert email_item["kind"] == "email" and email_item["metadata"]["from"] == "jan@borsuk-labs.sample"
    assert email_item["metadata"]["subject"] == "Fwd: monitor do biura" and email_item["metadata"]["attachments"] == 1
    assert photo["kind"] == "email_attachment" and photo["parent_raw_item_id"] == email_item["id"]
    assert photo["metadata"]["forwarded_by"] == "jan@borsuk-labs.sample"  # who paid: role 3 reads this
    assert photo["metadata"]["filename"] == "IMG_2041.jpg" and photo["content_type"] == "image/jpeg"
    assert content(db, photo["id"]) == ("image/jpeg", PHOTO)  # the pipeline reads the bytes from here
    for it in got.values():
        MODELS["raw_item"].model_validate(it)
    assert imap.selected_readonly is True and imap.seen_flags_changed is False  # the mailbox is never changed


def test_five_forwards_in_a_row_each_arrive_once(db, source):
    imap = FakeImap()
    for uid in range(1, 6):
        imap.messages[uid] = mail(uid, files=[(f"IMG_{uid}.jpg", "image/jpeg", PHOTO + bytes([uid]), False)])
        result = poll(db, imap)
        assert (result["items_new"], result["items_duplicate"]) == (2, 0), uid
    assert len(items(db)) == 10
    assert parse_cursor(Store(db).get("source", "src_mail")["cursor"]) == ("1001", 5)


# ---------- acceptance: re-running creates nothing new ----------
def test_rerunning_creates_nothing_new(db, source):
    imap = FakeImap({1: mail(1, files=[("a.jpg", "image/jpeg", PHOTO, False)])})
    poll(db, imap)
    again = poll(db, imap)
    assert again["items_fetched"] == 0 and again["items_new"] == 0
    db.execute("""update sources set doc = doc || '{"cursor": null}'::jsonb where id = 'src_mail'""")
    db.commit()
    reread = poll(db, imap)
    assert reread["items_new"] == 0 and reread["items_duplicate"] == 2


def test_the_same_file_forwarded_twice_is_stored_once(db, source):
    imap = FakeImap({1: mail(1, files=[("IMG_2041.jpg", "image/jpeg", PHOTO, False)]),
                     2: mail(2, sender="owner@borsuk-labs.sample", files=[("copy.jpg", "image/jpeg", PHOTO, False)])})
    result = poll(db, imap)
    assert result["items_new"] == 3 and result["items_duplicate"] == 1  # 2 e-mails + 1 file
    assert "<msg-2@mail.example.test>#1" not in items(db)


def test_the_fixtures_invented_cursor_does_not_skip_real_mail(db, source):
    assert parse_cursor(source["cursor"]) == ("7", 412)
    result = poll(db, FakeImap({1: mail(1, files=[("a.pdf", "application/pdf", b"%PDF-1.7 sample", False)])}))
    assert result["items_new"] == 2


# ---------- what is read and what is skipped ----------
def test_fa3_xml_is_an_e_invoice_for_role_3(db, source):
    poll(db, FakeImap({1: mail(1, sender="faktury@dostawcy.sample", subject="Faktura FV/BS/00038",
                               files=[("fa3_20261114_01.xml", "application/xml", FA3, False)])}))
    xml = items(db)["<msg-1@mail.example.test>#1"]
    assert xml["kind"] == "ksef_invoice_xml" and xml["content_type"] == "application/xml"
    assert content(db, xml["id"])[1] == FA3


def test_mails_without_files_or_invoice_words_are_skipped_but_passed(db, source):
    imap = FakeImap({1: mail(1, subject="Lunch?", body="Pizza at 1?"),
                     2: mail(2, subject="Re: invoice 2026/11/045", body="Please see the invoice number"),
                     3: mail(3, subject="Hi", body="Logo only", files=[("logo.png", "image/png", LOGO, True)])})
    result = poll(db, imap)
    assert set(items(db)) == {"<msg-2@mail.example.test>"}  # invoice-like text, no file: the e-mail only
    assert parse_cursor(Store(db).get("source", "src_mail")["cursor"])[1] == 3  # skipped mails are not re-read
    assert result["items_fetched"] == 1


def test_a_notification_naming_the_invoices_mailbox_is_not_an_invoice(db, source):
    """Found on the real mailbox: Google's security mails repeat the address borsuk.invoices.demo@gmail.com."""
    body = ("2-Step Verification turned on\n\nborsuk.invoices.demo@example.test\n"
            "Your Google Account borsuk.invoices.demo@example.test is now protected.\n"
            "https://myaccount.example.test/AccountChooser?Email=borsuk.invoices.demo@example.test")
    poll(db, FakeImap({1: mail(1, sender="no-reply@accounts.example.test", subject="Security alert", body=body),
                       2: mail(2, subject="faktura test", body="[image: obraz.png]")}))
    assert set(items(db)) == {"<msg-2@mail.example.test>"}


def test_a_small_inline_image_is_ignored_but_a_photo_inline_is_read(db, source):
    poll(db, FakeImap({1: mail(1, files=[("logo.png", "image/png", LOGO, True), ("receipt.jpg", "image/jpeg", PHOTO, True)])}))
    got = items(db)
    assert got["<msg-1@mail.example.test>"]["metadata"]["attachments"] == 1
    assert got["<msg-1@mail.example.test>#1"]["metadata"]["filename"] == "receipt.jpg"


def test_many_messages_are_read_in_pages(db, source):
    imap = FakeImap({uid: mail(uid, files=[(f"{uid}.jpg", "image/jpeg", PHOTO + bytes([uid]), False)]) for uid in range(1, 24)})
    result = poll(db, imap)
    assert result["items_new"] == 46 and imap.logged_out == 3  # 10 + 10 + 3, one login each


# ---------- failures ----------
def test_a_wrong_password_sets_the_source_to_error(db, source):
    waited = []
    result = poll(db, FakeImap(password="other"), waited)
    assert waited == [] and result["error"]["code"] == "auth_failed"
    assert Store(db).get("source", "src_mail")["status"] == "error"


def test_an_unreachable_server_is_retried_then_degraded(db, source):
    def down(host, port):
        raise OSError("connection refused")

    waited = []
    src = Store(db).get("source", "src_mail")
    result = run_once(db, ImapConnector(src, settings=SETTINGS, imap_factory=down), sleep=waited.append)
    assert waited == [5, 20, 60] and result["error"]["code"] == "imap_unreachable"
    assert Store(db).get("source", "src_mail")["status"] == "degraded"


def test_a_missing_folder_is_an_error(db, source):
    src = Store(db).get("source", "src_mail")
    result = run_once(db, ImapConnector(src, settings={**SETTINGS, "folder": "Faktury"}, imap_factory=FakeImap()),
                      sleep=lambda s: None)
    assert result["error"]["code"] == "imap_folder"


# ---------- the process ----------
def test_the_process_reads_the_mailbox_only_when_credentials_are_set(db, source, monkeypatch):
    import httpx

    import backend.connectors.mailbox as mailbox

    fake = FakeImap({1: mail(1, files=[("a.jpg", "image/jpeg", PHOTO, False)])})
    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", lambda host, port, timeout=None: fake)
    with httpx.Client(base_url="http://bank.invalid") as bank:
        for var in ("ORDO_IMAP_USER", "ORDO_IMAP_PASSWORD"):
            monkeypatch.delenv(var, raising=False)
        assert connectors.tick(db, bank, first=True, sleep=lambda s: None) == []
        monkeypatch.setenv("ORDO_IMAP_USER", "invoices@borsuk-labs.sample")
        monkeypatch.setenv("ORDO_IMAP_PASSWORD", "x")
        [run] = connectors.tick(db, bank, first=True, sleep=lambda s: None)
    assert run["source_id"] == "src_mail" and run["items_new"] == 2


def test_message_items_without_a_message_id_use_the_uid():
    raw = mail(9, files=[("a.jpg", "image/jpeg", PHOTO, False)]).replace(b"Message-ID: <msg-9@mail.example.test>\n", b"")
    got = message_items(raw, 9)
    assert got[0].external_id == "<uid-9@ordo.sample>" and got[1].external_id == "<uid-9@ordo.sample>#1"
