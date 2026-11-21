"""The owner tells Ordo about closed days in plain words ("We are closed for all of June")."""
from datetime import date

import pytest

from backend.agents.chat import _closed_period

AS_OF = date(2025, 5, 15)


@pytest.mark.parametrize("message,period", [
    ("We are closed for all of June", ("2025-06-01", "2025-06-30")),
    ("We are closed 1–30 June", ("2025-06-01", "2025-06-30")),
    ("closed the whole of July", ("2025-07-01", "2025-07-31")),
    ("We are closed in June", ("2025-06-01", "2025-06-30")),
    ("Wir haben den ganzen Juni geschlossen", ("2025-06-01", "2025-06-30")),
    ("closed all of March", ("2026-03-01", "2026-03-31")),
])
def test_a_month_or_a_range_of_days(message, period):
    assert _closed_period(message, AS_OF) == period


@pytest.mark.parametrize("message", ["nothing here", "all in all fine", "June was good"])
def test_no_period_without_a_month_after_a_cue(message):
    assert _closed_period(message, AS_OF) is None
