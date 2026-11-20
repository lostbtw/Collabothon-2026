"""Seam: the number check (pure). Generated text may only contain numbers that appear in the tool results."""
import pytest

from backend.agents.numbers import numbers_in, unexpected_numbers


@pytest.mark.parametrize("text,expected", [
    ("Open a 30,000 PLN credit line", {"30000"}),
    ("about 30000.00 PLN", {"30000"}),
    ("-7,870 PLN on 5 Dec", {"7870", "5"}),
    ("1 299,00 PLN", {"1299"}),
    ("rate 11.5% and 0.86", {"11.5", "0.86"}),
    ("no numbers here", set()),
])
def test_numbers_are_read_in_any_usual_format(text, expected):
    assert {format(n, "f") for n in numbers_in(text)} == expected


def test_text_with_only_tool_numbers_passes():
    tool_results = [{"min_balance": {"amount": "-7870.00", "currency": "PLN"}, "date": "2026-12-05"}, {"limit": "30000.00"}]

    assert unexpected_numbers(["Open a 30,000 PLN credit line: -7,870 PLN on 5 Dec"], tool_results) == []


def test_an_invented_number_is_reported():
    tool_results = [{"limit": "30000.00"}]

    assert [format(n, "f") for n in unexpected_numbers(["Open a 35,000 PLN credit line"], tool_results)] == ["35000"]
