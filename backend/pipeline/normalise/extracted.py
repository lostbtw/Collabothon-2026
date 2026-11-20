"""Photos and PDFs (#25 with role 1's #17): role 1's `extract_document()` reads the fields; this module adds what
only the pipeline knows, so the result is a whole Document (contracts/schemas/document.schema.json):

- id `doc_<raw id>`, company, the RawItem it came from, created_at;
- direction: sale when the seller's tax id is the company's, else purchase;
- channel: photo for images (e-mailed or sent from the phone), email for an e-mailed PDF, upload for the upload form;
- submitted_by: who forwarded or uploaded it, as a PersonRef (who paid reads the address, #25);
- gross_base and fx for a foreign-currency document: NBP rate of the previous business day (PL-FX-01).

The extractor's fields, confidence, status and flags are kept as they are: numbers come from the extraction with
its confidence value, never from here (hard rule 4).
"""
from .fx import to_base

BASE_CURRENCY = "PLN"
EXTRACTABLE_KINDS = ("email_attachment", "chat_photo", "upload")
PERSON_ROLES = ("owner", "employee", "accountant", "system")


def is_extractable(content_type: str | None) -> bool:
    ctype = (content_type or "").split(";")[0].strip().lower()
    return ctype.startswith("image/") or ctype == "application/pdf"


def is_xml(content_type: str | None) -> bool:
    ctype = (content_type or "").split(";")[0].strip().lower()
    return ctype in ("application/xml", "text/xml")


def channel_of(raw_item: dict) -> str:
    if raw_item["kind"] == "upload":
        return "upload"
    return "email" if (raw_item.get("content_type") or "").lower().startswith("application/pdf") else "photo"


def _bare_nip(tax_id: str | None) -> str:
    """'PL 999-000-00-14' -> '9990000014'; foreign ids keep their country prefix."""
    return (tax_id or "").upper().replace("-", "").replace(" ", "").removeprefix("PL")


def person_ref(sender: str | None, people: list[dict]) -> dict | None:
    """The forwarding address or uploader (an e-mail or a person id) -> PersonRef; unknown senders keep the address."""
    if not sender:
        return None
    key = sender.strip().lower()
    for person in people:
        if key in ((person.get("email") or "").lower(), (person.get("person_id") or "").lower()):
            role = person.get("role", "unknown")
            return {"person_id": person.get("person_id"), "name": person.get("name"), "email": person.get("email"),
                    "role": role if role in PERSON_ROLES else "unknown"}
    return {"person_id": None, "name": None, "email": sender if "@" in sender else None, "role": "unknown"}


def document_from_extraction(fields: dict, raw_item: dict, company: dict, *, people: list[dict],
                             sender: str | None, rates=None) -> dict:
    """`fields` = role 1's `extract_document()` result; `company` needs `id` and `tax_id`."""
    own_nip = _bare_nip(company.get("tax_id"))
    seller_nip = _bare_nip((fields.get("seller") or {}).get("tax_id"))
    direction = "sale" if own_nip and seller_nip == own_nip else "purchase"

    totals = dict(fields["totals"])
    warnings = list(fields["extraction"].get("warnings") or [])
    gross = totals.get("gross")
    if gross and gross["currency"] != BASE_CURRENCY and not totals.get("gross_base"):
        totals["gross_base"], totals["fx"] = to_base(gross, fields.get("issue_date"), rates)
        if totals["gross_base"] is None:
            warnings.append(f"No NBP rate for {gross['currency']} before {fields.get('issue_date')}; gross_base empty")

    return {
        "id": "doc_" + raw_item["id"].removeprefix("raw_"),
        "company_id": company["id"],
        "raw_item_ids": [raw_item["id"]],
        "duplicate_of": None,
        **fields,
        "direction": direction,
        "channel": channel_of(raw_item),
        "totals": totals,
        "extraction": {**fields["extraction"], "warnings": warnings},
        "submitted_by": person_ref(sender, people),
        "created_at": raw_item.get("fetched_at") or raw_item.get("received_at"),
    }
