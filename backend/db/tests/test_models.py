"""Seam: the pydantic models generated from contracts/schemas."""
import json
from pathlib import Path

import pytest

from backend.db.contracts import MODELS

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def all_fixtures():
    for path in sorted(FIXTURES.glob("*.json")):
        for i, item in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            yield pytest.param(path.stem, item, id=f"{path.stem}[{i}]")


@pytest.mark.parametrize("entity,item", list(all_fixtures()))
def test_every_fixture_parses_into_its_model_without_loss(entity, item):
    model = MODELS[entity].model_validate(item)

    assert model.model_dump(mode="json", by_alias=True, exclude_unset=True) == item
