"""Business days and month arithmetic; PL-CAL-04 moves a payment due on a weekend or PL/DE holiday to the next business day."""
from datetime import date, timedelta
from functools import lru_cache


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=None)
def holidays(country: str, year: int) -> frozenset[date]:
    e = easter(year)
    if country == "PL":
        fixed = [(1, 1), (1, 6), (5, 1), (5, 3), (8, 15), (11, 1), (11, 11), (12, 24), (12, 25), (12, 26)]
        moving = [e, e + timedelta(days=1), e + timedelta(days=49), e + timedelta(days=60)]
    elif country == "DE":
        fixed = [(1, 1), (5, 1), (10, 3), (12, 25), (12, 26)]
        moving = [e - timedelta(days=2), e + timedelta(days=1), e + timedelta(days=39), e + timedelta(days=50)]
    else:
        return frozenset()
    return frozenset([date(year, mo, d) for mo, d in fixed] + moving)


def is_business_day(day: date, country: str) -> bool:
    return day.weekday() < 5 and day not in holidays(country, day.year)


def on_or_after(day: date, country: str) -> date:
    while not is_business_day(day, country):
        day += timedelta(days=1)
    return day


def next_business_day(day: date, country: str) -> date:
    return on_or_after(day + timedelta(days=1), country)


def last_day_of_month(year: int, month: int) -> date:
    return (date(year, month, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def last_business_day(year: int, month: int, country: str) -> date:
    day = last_day_of_month(year, month)
    while not is_business_day(day, country):
        day -= timedelta(days=1)
    return day


def add_months(year: int, month: int, k: int) -> tuple[int, int]:
    m0 = month - 1 + k
    return year + m0 // 12, m0 % 12 + 1


def day_in_month(year: int, month: int, dom: int) -> date:
    """The `dom`-th of the month, or its last day when the month is shorter."""
    return date(year, month, min(dom, last_day_of_month(year, month).day))
