#!/usr/bin/env python3
"""Releaser (#37): pushes role 4's scenario (sim/scenario/out/release_plan.json) through the real sources.

It never writes into the app database: everything it releases reaches the app because a connector fetched it.

    python sim/releaser/release.py status                      # what is in the plan, what the mailbox already holds
    python sim/releaser/release.py backfill [--until 2026-10-31] [--limit N] [--dry-run]
    python sim/releaser/release.py drip [--speed 10] [--dry-run]   # during the demo: one item every 20-40 s
    python sim/releaser/release.py next                        # ONE not yet sent drip document (short demo)
    python sim/releaser/release.py list                        # the 15 drip documents, which are sent
    python sim/releaser/release.py live                        # backup only: the rendered photo of the live receipt
    python sim/releaser/release.py check-bank                  # the bank lines of the plan are in the Sandbox Bank

Channels:
- e-mail, photo and accounting_api (inFakt was cut, so its e-mail fallback): one message per document, put into the
  invoices mailbox with IMAP APPEND. No SMTP: no sending limits, no spam filter, seconds for the whole backfill.
  The mailbox connector (#33) then reads them like any forwarded mail.
- bank: nothing to send. The Sandbox Bank loads the statements at start (BANK_AUTOLOAD_DIR) with the same entry
  references the plan names; `check-bank` verifies it.

Safe to repeat: every message has a fixed Message-ID, and one already in the mailbox is not put there again (the
connector would skip it anyway). Stdlib only.
Environment: ORDO_IMAP_USER, ORDO_IMAP_PASSWORD, ORDO_IMAP_HOST (imap.gmail.com), ORDO_IMAP_PORT (993),
ORDO_IMAP_FOLDER (INBOX); for check-bank ORDO_BANK_URL, ORDO_BANK_TOKEN. A .env at the repo root is read too.
"""
from __future__ import annotations

import argparse
import imaplib
import json
import mimetypes
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "sim" / "scenario" / "out"
PLAN = OUT / "release_plan.json"
ROOTS = {"sim/scenario/out/": OUT, "november/": ROOT / "sim" / "documents" / "november"}
MAIL_CHANNELS = ("email", "photo", "accounting_api")
POLAND = timezone(timedelta(hours=1))
MESSAGE_ID = re.compile(rb"Message-ID:\s*(<[^>]+>)", re.I)


# ---------- plan ----------
def load_env_file(path: Path = ROOT / ".env") -> None:
    """Same rule as backend/settings.py: .env fills what the environment does not set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_plan(path: Path = PLAN) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def artefact_path(artefact: str) -> Path:
    for prefix, root in ROOTS.items():
        if artefact.startswith(prefix):
            return root / artefact[len(prefix):]
    raise ValueError(f"unknown artefact root: {artefact}")


def select(items: list[dict], mode: str, until: str | None = None, limit: int | None = None) -> list[dict]:
    chosen = [i for i in items if i["mode"] == mode and i["channel"] in MAIL_CHANNELS]
    if until:
        chosen = [i for i in chosen if i["scenario_date"] <= until]
    chosen.sort(key=lambda i: (i.get("offset_seconds", 0), i["scenario_date"], i["seq"]))
    return chosen[:limit] if limit else chosen


def _documents() -> dict[str, dict]:
    """document id -> {number, counterparty}, for readable subjects."""
    docs: dict[str, dict] = {}
    for e in json.loads((OUT / "fa3_index.json").read_text(encoding="utf-8")):
        docs[e["id"]] = {"number": e.get("number"), "counterparty": e.get("counterparty")}
    nov = json.loads((OUT / "november_documents.json").read_text(encoding="utf-8"))
    for e in (nov["documents"] if isinstance(nov, dict) else nov):
        docs[e["id"]] = {"number": e.get("number"), "counterparty": (e.get("seller") or {}).get("name")}
    return docs


OWNER = "owner@borsuk-labs.sample"


def sender_of(item: dict) -> str:
    """The plan's sender. The Lakeshore sales invoice has none (it was meant for the inFakt API, which was cut):
    it comes from the owner, like the other sales invoices that fall back to e-mail."""
    return item.get("sender") or OWNER


def message_id(item: dict) -> str:
    return f"<release-{item['seq']:04d}-{item['document_id']}@ordo.sample>"


def build_message(item: dict, mailbox: str, docs: dict[str, dict], when: datetime) -> EmailMessage:
    """One e-mail for one plan item: from its sender, with its artefact attached, a fixed Message-ID."""
    path = artefact_path(item["artefact"])
    doc = docs.get(item["document_id"], {})
    number, who = doc.get("number") or item["document_id"], doc.get("counterparty") or ""
    if item["channel"] == "photo":
        subject, body = f"Fwd: paragon {who}".strip(), "Zdjecie paragonu w zalaczniku, prosze o zwrot. (SAMPLE)"
    elif item["channel"] == "accounting_api":
        subject, body = f"Faktura sprzedazy {number} (kopia z systemu ksiegowego)", "Faktura w zalaczniku. (SAMPLE)"
    else:
        subject, body = f"Faktura {number} {who}".strip(), "Faktura w zalaczniku. (SAMPLE)"
    msg = EmailMessage()
    msg["From"] = sender_of(item)
    msg["To"] = mailbox
    msg["Subject"] = subject
    msg["Date"] = format_datetime(when)
    msg["Message-ID"] = message_id(item)
    msg["X-Ordo-Release"] = f"{item['mode']} seq={item['seq']} document={item['document_id']}"
    msg.set_content(body)
    ctype = "application/xml" if path.suffix == ".xml" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    maintype, subtype = ctype.split("/", 1)
    msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return msg


def scenario_time(item: dict) -> datetime:
    return datetime.fromisoformat(item["scenario_date"]).replace(hour=9, tzinfo=POLAND) + timedelta(minutes=item["seq"] % 480)


# ---------- mailbox ----------
def imap_settings() -> dict:
    return {"host": os.environ.get("ORDO_IMAP_HOST", "imap.gmail.com"),
            "port": int(os.environ.get("ORDO_IMAP_PORT", "993")),
            "user": os.environ.get("ORDO_IMAP_USER", ""), "password": os.environ.get("ORDO_IMAP_PASSWORD", ""),
            "folder": os.environ.get("ORDO_IMAP_FOLDER", "INBOX")}


class Mailbox:
    def __init__(self, settings: dict, factory=None):
        if not (settings["user"] and settings["password"]):
            raise SystemExit("set ORDO_IMAP_USER and ORDO_IMAP_PASSWORD (environment or .env)")
        self.settings = settings
        self.imap = (factory or (lambda h, p: imaplib.IMAP4_SSL(h, p, timeout=60)))(settings["host"], settings["port"])
        self.imap.login(settings["user"], settings["password"])

    def message_ids(self) -> set[str]:
        """Message-IDs already in the folder (read-only look, nothing is marked as seen)."""
        status, _ = self.imap.select(self.settings["folder"], readonly=True)
        if status != "OK":
            raise SystemExit(f"no folder {self.settings['folder']!r} in the mailbox")
        _, data = self.imap.uid("search", None, "ALL")
        if not (data and data[0]):
            return set()
        _, parts = self.imap.uid("fetch", "1:*", "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        found = set()
        for part in parts or []:
            if isinstance(part, tuple) and len(part) > 1:
                m = MESSAGE_ID.search(part[1])
                if m:
                    found.add(m.group(1).decode())
        return found

    def append(self, msg: EmailMessage, when: datetime) -> None:
        status, data = self.imap.append(self.settings["folder"], None, imaplib.Time2Internaldate(when.timestamp()),
                                        msg.as_bytes())
        if status != "OK":
            raise RuntimeError(f"the mailbox refused {msg['Message-ID']}: {data}")

    def close(self) -> None:
        try:
            self.imap.logout()
        except Exception:  # noqa: BLE001
            pass


# ---------- commands ----------
def release(mailbox: Mailbox, items: list[dict], *, now=None, sleep=time.sleep, paced: bool = False,
            speed: float = 1.0, dry_run: bool = False, fresh: bool = False, log=print) -> Counter:
    """Put each item's message into the mailbox unless its Message-ID is there. `paced`: wait for offset_seconds.
    `fresh`: dated now, like a mail that has just arrived (otherwise dated on the scenario day)."""
    docs = _documents()
    present = mailbox.message_ids() if mailbox else set()
    counts: Counter = Counter()
    started = time.monotonic()
    for item in items:
        if paced:
            wait = item.get("offset_seconds", 0) / speed - (time.monotonic() - started)
            if wait > 0:
                sleep(wait)
        mid = message_id(item)
        if mid in present:
            counts["already_in_mailbox"] += 1
            continue
        when = (now or (lambda: datetime.now(POLAND)))() if (paced or fresh) else scenario_time(item)
        msg = build_message(item, mailbox.settings["user"] if mailbox else "invoices@example.test", docs, when)
        if dry_run:
            counts["would_release"] += 1
        else:
            mailbox.append(msg, when)
            present.add(mid)
            counts["released"] += 1
            if paced or fresh:
                log(f"{datetime.now():%H:%M:%S} released {item['document_id']} ({item['channel']}) from {sender_of(item)}")
        counts[f"channel:{item['channel']}"] += 1
    return counts


def _get_json(url: str, headers: dict) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)


def check_bank(items: list[dict], url: str, token: str, get=_get_json) -> dict[str, int]:
    """For every bank line of the plan: does the Sandbox Bank hold that entry reference on that date?"""
    wanted: dict[str, dict[str, str]] = {}
    for i in items:
        if i["channel"] == "bank":
            wanted.setdefault(i["account"], {})[i["entry_reference"]] = i["scenario_date"]
    result = {"lines": 0, "missing": 0, "wrong_date": 0}
    headers = {"Authorization": f"Bearer {token}", "Consent-ID": "demo"}
    for account, refs in wanted.items():
        held: dict[str, str] = {}
        next_url = f"{url}/v1/accounts/{account}/transactions?bookingStatus=booked&limit=1000"
        while next_url:
            body = get(next_url, headers)
            held.update({ln["entryReference"]: ln["bookingDate"] for ln in body["transactions"]["booked"]})
            link = (body.get("_links") or {}).get("next", {}).get("href")
            next_url = f"{url}{link}" if link else None
        for ref, day in refs.items():
            result["lines"] += 1
            if ref not in held:
                result["missing"] += 1
            elif held[ref] != day:
                result["wrong_date"] += 1
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    b = sub.add_parser("backfill")
    b.add_argument("--until", help="only items up to this scenario date (YYYY-MM-DD)")
    b.add_argument("--limit", type=int)
    b.add_argument("--dry-run", action="store_true")
    d = sub.add_parser("drip")
    d.add_argument("--speed", type=float, default=1.0, help="2 = twice as fast as the plan's offsets")
    d.add_argument("--dry-run", action="store_true")
    sub.add_parser("live")
    sub.add_parser("list", help="the drip documents and which are already in the mailbox")
    n = sub.add_parser("next", help="send ONE not yet sent drip document (for a short demo)")
    n.add_argument("--dry-run", action="store_true")
    sub.add_parser("check-bank")
    args = parser.parse_args(argv)
    load_env_file()
    items = load_plan()

    if args.command == "check-bank":
        res = check_bank(items, os.environ.get("ORDO_BANK_URL", "http://localhost:8081"),
                         os.environ.get("ORDO_BANK_TOKEN", "demo-token"))
        print(f"bank lines in the plan: {res['lines']}, missing in the bank: {res['missing']}, "
              f"other booking date: {res['wrong_date']}")
        return 0 if res["missing"] == res["wrong_date"] == 0 else 1

    dry = getattr(args, "dry_run", False)
    mailbox = None if (dry and args.command not in ("status", "list", "next")) else Mailbox(imap_settings())
    try:
        if args.command == "status":
            present = mailbox.message_ids()
            for mode in ("backfill", "drip", "live"):
                mine = select(items, mode)
                done = sum(message_id(i) in present for i in mine)
                print(f"{mode:9} {len(mine):4} mail items, {done:4} already in the mailbox")
            print(f"bank      {sum(i['channel'] == 'bank' for i in items):4} lines (loaded by the Sandbox Bank itself)")
            return 0
        if args.command in ("list", "next"):
            drip = select(items, "drip")
            present = mailbox.message_ids() if mailbox else set()
            if args.command == "list":
                docs = _documents()
                for n, i in enumerate(drip, start=1):
                    who = docs.get(i["document_id"], {})
                    state = "sent" if message_id(i) in present else "    "
                    print(f"{n:2} {state} {i['document_id']:12} {i['channel']:6} from {sender_of(i):28} "
                          f"{who.get('counterparty') or ''}  [{artefact_path(i['artefact']).name}]")
                print(f"{sum(message_id(i) in present for i in drip)} of {len(drip)} sent")
                return 0
            todo = [i for i in drip if message_id(i) not in present]
            if not todo:
                print("all drip documents are already sent")
                return 0
            counts = release(mailbox, todo[:1], fresh=True, dry_run=dry)
            print(f"{len(todo) - 1} left")
            return 0
        if args.command == "backfill":
            counts = release(mailbox, select(items, "backfill", args.until, args.limit), dry_run=dry)
        elif args.command == "drip":
            counts = release(mailbox, select(items, "drip"), paced=True, speed=args.speed, dry_run=dry)
        else:
            counts = release(mailbox, select(items, "live"))
        print(dict(counts))
        return 0
    finally:
        if mailbox:
            mailbox.close()


if __name__ == "__main__":
    sys.exit(main())
