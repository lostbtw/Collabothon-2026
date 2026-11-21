"""Pydantic models generated from contracts/schemas; regenerate them in the same commit as a schema change."""
# uv run datamodel-codegen --input contracts/schemas --input-file-type jsonschema --output backend/db/models --output-model-type pydantic_v2.BaseModel --target-python-version 3.12 --use-annotated --disable-timestamp --use-schema-description --field-constraints
from pydantic import BaseModel

from backend.db.models.account_schema import Account
from backend.db.models.approval_schema import Approval
from backend.db.models.counterparty_schema import Counterparty
from backend.db.models.document_schema import Document
from backend.db.models.event_schema import EventEnvelope
from backend.db.models.forecast_schema import Forecast
from backend.db.models.ledger_entry_schema import LedgerEntry
from backend.db.models.match_schema import Match
from backend.db.models.raw_item_schema import RawItem
from backend.db.models.recommendation_schema import Recommendation
from backend.db.models.source_schema import Source
from backend.db.models.sync_run_schema import SyncRun
from backend.db.models.transaction_schema import Transaction

MODELS: dict[str, type[BaseModel]] = {
    "account": Account,
    "approval": Approval,
    "counterparty": Counterparty,
    "document": Document,
    "event": EventEnvelope,
    "forecast": Forecast,
    "ledger_entry": LedgerEntry,
    "match": Match,
    "raw_item": RawItem,
    "recommendation": Recommendation,
    "source": Source,
    "sync_run": SyncRun,
    "transaction": Transaction,
}
