"""Mailbox connector: each forwarded e-mail and each attachment becomes a RawItem; the mailbox is read over IMAP, read-only."""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import imaplib
import os
import re
import socket
from collections.abc import Callable
from typing import Any

from backend.connectors.base import AuthError, Connector, ConnectorError, FetchedItem, FetchResult

PAGE_MESSAGES = 10
MIN_INLINE_IMAGE = 20 * 1024
INVOICE_WORDS = re.compile(r"faktur|invoice|rachun|paragon|receipt|quittung|rechnung|\bFV[/ ]|zwrot|reimburs", re.I)
ADDRESS_OR_LINK = re.compile(r"\S+@\S+|https?://\S+|www\.\S+", re.I)
FILE_TYPES = ("image/", "application/pdf", "application/xml", "text/xml")
FILE_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp", ".xml")
FA3_MARKERS = (b"crd.gov.pl/wzor", b"<Faktura")


def imap_settings() -> dict[str, Any]:
    return {"host": os.environ.get("ORDO_IMAP_HOST", "imap.gmail.com"),
            "port": int(os.environ.get("ORDO_IMAP_PORT", "993")),
            "user": os.environ.get("ORDO_IMAP_USER", ""),
            "password": os.environ.get("ORDO_IMAP_PASSWORD", ""),
            "folder": os.environ.get("ORDO_IMAP_FOLDER", "INBOX")}


def imap_configured() -> bool:
    s = imap_settings()
    return bool(s["user"] and s["password"])


def parse_cursor(cursor: str | None) -> tuple[str | None, int]:
    """`UIDVALIDITY=7;UID=412` -> ("7", 412)."""
    values = dict(part.split("=", 1) for part in (cursor or "").split(";") if "=" in part)
    try:
        return values.get("UIDVALIDITY"), int(values.get("UID", 0))
    except ValueError:
        return values.get("UIDVALIDITY"), 0


def _address(header: str | None) -> str | None:
    name, addr = email.utils.parseaddr(header or "")
    return addr.lower() or None


def _is_file(part) -> bool:
    ctype = part.get_content_type()
    name = (part.get_filename() or "").lower()
    return ctype.startswith(FILE_TYPES) or name.endswith(FILE_EXTENSIONS)


def _attachments(msg) -> list[tuple[str | None, str, bytes]]:
    """(filename, content type, bytes) of the files worth reading."""
    out = []
    for part in msg.walk():
        if part.is_multipart() or not _is_file(part):
            continue
        data = part.get_payload(decode=True) or b""
        if not data:
            continue
        disposition = (part.get_content_disposition() or "").lower()
        if disposition != "attachment" and part.get_content_type().startswith("image/") and len(data) < MIN_INLINE_IMAGE:
            continue  # a logo or a signature image in the mail body
        out.append((part.get_filename(), part.get_content_type(), data))
    return out


def _body_text(msg) -> str:
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
        return body.get_content() if body is not None else ""
    except (KeyError, LookupError, UnicodeDecodeError):
        return ""


def message_items(raw: bytes, uid: int) -> list[FetchedItem]:
    """The RawItems of one message: the e-mail and its attachments, or nothing when it is not worth reading."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    files = _attachments(msg)
    subject = str(msg.get("Subject") or "")
    # Addresses and links are not words: the mailbox's own name ("...invoices...") would make every mail look like an invoice.
    words = ADDRESS_OR_LINK.sub(" ", subject + "\n" + _body_text(msg))
    if not files and not INVOICE_WORDS.search(words):
        return []
    sender = _address(msg.get("From"))
    message_id = (str(msg.get("Message-ID") or "").strip() or f"<uid-{uid}@ordo.sample>")
    received = None
    if msg.get("Date"):
        try:
            received = email.utils.parsedate_to_datetime(str(msg["Date"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            received = None
    items = [FetchedItem(
        kind="email", external_id=message_id, received_at=received, content_type="message/rfc822",
        size_bytes=len(raw),
        metadata={"from": sender, "to": _address(msg.get("To")), "subject": subject, "uid": uid,
                  "attachments": len(files), "forwarded_by": sender},
    )]
    for n, (filename, ctype, data) in enumerate(files, start=1):
        is_fa3 = (ctype.endswith("xml") or (filename or "").lower().endswith(".xml")) and any(m in data[:4096] for m in FA3_MARKERS)
        items.append(FetchedItem(
            kind="ksef_invoice_xml" if is_fa3 else "email_attachment",
            external_id=f"{message_id}#{n}", parent_external_id=message_id, received_at=received,
            content_type="application/xml" if is_fa3 else ctype, size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(), content=data,
            metadata={"filename": filename, "forwarded_by": sender, "subject": subject},
        ))
    return items


class ImapConnector(Connector):
    connector = "imap_mailbox"
    key_prefix = "imap"
    dedupe_content = True

    def __init__(self, source: dict[str, Any], *, settings: dict[str, Any] | None = None,
                 imap_factory: Callable[[str, int], Any] | None = None):
        super().__init__(source)
        self.settings = settings or imap_settings()
        self.imap_factory = imap_factory or (lambda host, port: imaplib.IMAP4_SSL(host, port, timeout=30))

    def key_scope(self) -> str:
        return (self.settings.get("user") or (self.source.get("config_public") or {}).get("mailbox")
                or self.source["id"]).lower()

    def fetch(self, cursor: str | None) -> FetchResult:
        s = self.settings
        try:
            imap = self.imap_factory(s["host"], s["port"])
        except (OSError, socket.timeout, imaplib.IMAP4.error) as exc:
            raise ConnectorError(f"mailbox unreachable: {exc}", code="imap_unreachable") from exc
        try:
            try:
                imap.login(s["user"], s["password"])
            except imaplib.IMAP4.error as exc:
                raise AuthError(f"the mailbox refused the login: {exc}") from exc
            status, _ = imap.select(s["folder"], readonly=True)
            if status != "OK":
                raise ConnectorError(f"no folder {s['folder']!r} in the mailbox", code="imap_folder", retryable=False)
            validity = (imap.response("UIDVALIDITY")[1] or [b""])[0]
            validity = validity.decode() if isinstance(validity, bytes) else str(validity or "")
            stored_validity, last = parse_cursor(cursor)
            if stored_validity != validity:
                last = 0  # other UIDs than the ones the cursor counted: read everything again (duplicates skipped)
            status, data = imap.uid("search", None, f"UID {last + 1}:*")
            if status != "OK":
                raise ConnectorError("the mailbox refused the search", code="imap_search")
            uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > last)  # "n:*" can return the last one
            page, more = uids[:PAGE_MESSAGES], len(uids) > PAGE_MESSAGES
            items: list[FetchedItem] = []
            for uid in page:
                status, parts = imap.uid("fetch", str(uid), "(BODY.PEEK[])")
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
                if status != "OK" or raw is None:
                    raise ConnectorError(f"could not read message UID {uid}", code="imap_fetch")
                items += message_items(raw, uid)
            new_last = page[-1] if page else last
            return FetchResult(items=items, cursor=f"UIDVALIDITY={validity};UID={new_last}", more=more)
        except (OSError, socket.timeout, imaplib.IMAP4.abort) as exc:
            raise ConnectorError(f"mailbox connection lost: {exc}", code="imap_unreachable") from exc
        finally:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001 - closing a broken connection must not hide the real error
                pass
