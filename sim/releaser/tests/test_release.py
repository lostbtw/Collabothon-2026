"""Releaser on the real plan against a fake IMAP mailbox; the released mail read by the real connector."""
import email
import email.policy
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sim" / "releaser"))
import release  # noqa: E402

SETTINGS = {"host": "imap.example.test", "port": 993, "user": "invoices@example.test", "password": "x", "folder": "INBOX"}
PLAN = release.load_plan()


class FakeImap:
    def __init__(self, existing: list[bytes] = ()):
        self.messages: list[bytes] = list(existing)
        self.appended_dates: list[str] = []

    def __call__(self, host, port):
        return self

    def login(self, user, password):
        return "OK", [b""]

    def select(self, folder, readonly=False):
        assert readonly, "the releaser only looks at the folder read-only"
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        if command == "search":
            return "OK", [" ".join(str(i + 1) for i in range(len(self.messages))).encode()]
        assert command == "fetch" and "PEEK" in args[1]
        out = []
        for i, raw in enumerate(self.messages):
            mid = email.message_from_bytes(raw, policy=email.policy.default)["Message-ID"]
            out += [(f"{i + 1} (UID {i + 1} BODY[HEADER.FIELDS (MESSAGE-ID)] {{n}}".encode(),
                     f"Message-ID: {mid}\r\n\r\n".encode()), b")"]
        return "OK", out

    def append(self, folder, flags, date_time, message):
        self.messages.append(message)
        self.appended_dates.append(date_time)
        return "OK", [b"APPEND completed"]

    def logout(self):
        return "BYE", [b""]


def mailbox(fake):
    return release.Mailbox(SETTINGS, factory=fake)


def parsed(fake):
    return [email.message_from_bytes(m, policy=email.policy.default) for m in fake.messages]


def test_the_plan_has_what_role_4_promised():
    counts = Counter((i["mode"], i["channel"]) for i in PLAN)
    assert counts[("backfill", "bank")] == 1070
    assert len(release.select(PLAN, "backfill")) == 531
    assert len(release.select(PLAN, "drip")) == 15 and len(release.select(PLAN, "live")) == 1


def test_every_artefact_exists():
    missing = [i["artefact"] for i in PLAN if i["channel"] != "bank" and not release.artefact_path(i["artefact"]).is_file()]
    assert missing == []


def test_backfill_puts_every_document_into_the_mailbox_once(tmp_path):
    fake = FakeImap()
    counts = release.release(mailbox(fake), release.select(PLAN, "backfill"))
    assert counts["released"] == 531 and len(fake.messages) == 531
    ids = [m["Message-ID"] for m in parsed(fake)]
    assert len(set(ids)) == 531
    again = release.release(mailbox(fake), release.select(PLAN, "backfill"))
    assert again["released"] == 0 and again["already_in_mailbox"] == 531 and len(fake.messages) == 531


def test_backfill_until_and_limit():
    fake = FakeImap()
    release.release(mailbox(fake), release.select(PLAN, "backfill", until="2026-01-31"))
    assert all(m["Date"].endswith("+0100") for m in parsed(fake))
    assert 0 < len(fake.messages) < 100
    fake2 = FakeImap()
    release.release(mailbox(fake2), release.select(PLAN, "backfill", limit=3))
    assert len(fake2.messages) == 3


def test_dry_run_touches_nothing():
    counts = release.release(None, release.select(PLAN, "backfill"), dry_run=True)
    assert counts["would_release"] == 531 and counts["released"] == 0


def test_the_lakeshore_invoice_without_a_sender_comes_from_the_owner():
    item = next(i for i in PLAN if i.get("document_id") == "nov_lakeshore")
    assert "sender" not in item and release.sender_of(item) == "owner@borsuk-labs.sample"


def test_a_message_carries_sender_subject_and_the_file():
    item = next(i for i in PLAN if i["channel"] == "photo" and i["mode"] == "backfill")
    msg = release.build_message(item, "invoices@example.test", release._documents(), release.scenario_time(item))
    assert msg["From"] == item["sender"] and msg["To"] == "invoices@example.test"
    assert msg["Message-ID"] == release.message_id(item) and msg["Subject"].startswith("Fwd: paragon")
    [att] = list(msg.iter_attachments())
    assert att.get_filename() == release.artefact_path(item["artefact"]).name
    assert att.get_content() == release.artefact_path(item["artefact"]).read_bytes()


def test_the_connector_reads_released_mail_as_documents():
    from backend.connectors.mailbox import message_items

    fake = FakeImap()
    items = release.select(PLAN, "backfill")
    release.release(mailbox(fake), items)
    kinds, senders = Counter(), set()
    by_id = {release.message_id(i): i for i in items}
    for uid, raw in enumerate(fake.messages, start=1):
        got = message_items(raw, uid)
        assert len(got) == 2, raw[:200]
        kinds[got[1].kind] += 1
        item = by_id[got[0].external_id]
        assert got[1].metadata["forwarded_by"] == release.sender_of(item)
        senders.add(release.sender_of(item))
    xml_items = sum(i["artefact"].endswith(".xml") for i in items)
    assert kinds == {"ksef_invoice_xml": xml_items, "email_attachment": 531 - xml_items}
    assert "jan@borsuk-labs.sample" in senders


def test_drip_follows_the_offsets_at_the_chosen_speed():
    fake, waits = FakeImap(), []
    release.time.monotonic, real = (lambda: 0.0), release.time.monotonic
    try:
        counts = release.release(mailbox(fake), release.select(PLAN, "drip"), paced=True, speed=10,
                                 sleep=waits.append, log=lambda s: None)
    finally:
        release.time.monotonic = real
    offsets = [i["offset_seconds"] for i in release.select(PLAN, "drip")]
    assert counts["released"] == 15
    assert waits == [o / 10 for o in offsets if o > 0]


def test_live_sends_only_the_backup_photo():
    fake = FakeImap()
    release.release(mailbox(fake), release.select(PLAN, "live"))
    [msg] = parsed(fake)
    assert msg["From"] == "jan@borsuk-labs.sample"
    assert [a.get_filename() for a in msg.iter_attachments()] == ["doc_rcpt412.jpg"]


def test_no_credentials_no_run():
    with pytest.raises(SystemExit, match="ORDO_IMAP_USER"):
        release.Mailbox({**SETTINGS, "password": ""}, factory=FakeImap())


def test_check_bank_against_the_real_sandbox_bank():
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(ROOT / "sim" / "bank"))
    from bank_sim.app import create_app
    from bank_sim.store import Store

    with TestClient(create_app(Store(), token="t", autoload_dir=str(release.OUT))) as bank:
        def get(url, headers):
            return bank.get(url.removeprefix("http://bank"), headers=headers).json()

        assert release.check_bank(PLAN, "http://bank", "t", get=get) == {"lines": 1070, "missing": 0, "wrong_date": 0}
    with TestClient(create_app(Store(), token="t")) as empty:
        res = release.check_bank(PLAN, "http://bank", "t",
                                 get=lambda url, headers: empty.get(url.removeprefix("http://bank"), headers=headers).json())
        assert res["missing"] == 1070


def test_next_sends_one_not_yet_sent_drip_document_each_time():
    fake = FakeImap()
    drip = release.select(PLAN, "drip")
    sent_order = []
    for _ in range(3):
        box = mailbox(fake)
        todo = [i for i in drip if release.message_id(i) not in box.message_ids()]
        release.release(box, todo[:1], fresh=True, log=lambda s: None)
        sent_order.append(todo[0]["document_id"])
    assert sent_order == [i["document_id"] for i in drip[:3]]
    assert len(fake.messages) == 3 and len({m["Message-ID"] for m in parsed(fake)}) == 3


def test_fresh_mail_is_dated_now_not_on_the_scenario_day():
    fake = FakeImap()
    item = release.select(PLAN, "drip")[0]
    release.release(mailbox(fake), [item], fresh=True, log=lambda s: None)
    assert parsed(fake)[0]["Date"].datetime.year == datetime.now().year
    assert "2026-11-02" not in fake.appended_dates[0]
