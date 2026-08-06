"""`AnnualWindow` — the year-free season the city publishes.

Two properties carry the whole model and both are counter-intuitive enough to pin explicitly:
a window whose `start > end` **wraps New Year**, and `precision=MONTH` means WHOLE MONTHS
INCLUSIVE (1 May through 30 September), not 1st-to-1st.
"""

from __future__ import annotations

from datetime import date

import pytest

from swimzh.domain.schedule import AnnualWindow, DatePrecision, MonthDay


def test_whole_months_covers_both_boundary_months_entirely() -> None:
    # "Mai–September" — the exact cell Bläsi and Käferberg publish.
    summer = AnnualWindow.whole_months(5, 9)
    assert summer.precision is DatePrecision.MONTH
    assert summer.contains(date(2026, 5, 1))  # first day of the FIRST month
    assert summer.contains(date(2026, 9, 30))  # last day of the LAST month
    assert summer.contains(date(2026, 7, 18))
    assert not summer.contains(date(2026, 4, 30))
    assert not summer.contains(date(2026, 10, 1))


def test_whole_months_wraps_new_year() -> None:
    # "Oktober–April": October through April, i.e. ACROSS the year boundary.
    winter = AnnualWindow.whole_months(10, 4)
    assert winter.contains(date(2026, 12, 31))
    assert winter.contains(date(2027, 1, 1))  # the same window, the next calendar year
    assert winter.contains(date(2026, 10, 1))
    assert winter.contains(date(2026, 4, 30))
    assert not winter.contains(date(2026, 5, 1))
    assert not winter.contains(date(2026, 9, 30))


def test_the_two_published_windows_partition_the_year() -> None:
    # Bläsi's weekend is stated as exactly two windows; every day of a year must fall in one.
    summer, winter = AnnualWindow.whole_months(5, 9), AnnualWindow.whole_months(10, 4)
    for month in range(1, 13):
        d = date(2026, month, 15)
        assert summer.contains(d) != winter.contains(d), d


def test_day_precision_is_inclusive_at_both_ends() -> None:
    # "30. Mai–16. August" — the outdoor grammar.
    window = AnnualWindow(start=MonthDay(5, 30), end=MonthDay(8, 16))
    assert window.precision is DatePrecision.DAY
    assert window.contains(date(2026, 5, 30))
    assert window.contains(date(2026, 8, 16))
    assert not window.contains(date(2026, 5, 29))
    assert not window.contains(date(2026, 8, 17))


def test_day_precision_wraps_new_year_too() -> None:
    window = AnnualWindow(start=MonthDay(11, 15), end=MonthDay(2, 10))
    assert window.contains(date(2026, 12, 25))
    assert window.contains(date(2027, 2, 10))
    assert not window.contains(date(2026, 11, 14))
    assert not window.contains(date(2027, 2, 11))


def test_month_precision_ignores_the_day_components() -> None:
    # A MONTH window built by hand with mid-month days still means whole months, so a consumer
    # can never read a published month range as a partial one.
    window = AnnualWindow(start=MonthDay(5, 20), end=MonthDay(9, 3), precision=DatePrecision.MONTH)
    assert window.contains(date(2026, 5, 1))
    assert window.contains(date(2026, 9, 30))


@pytest.mark.parametrize("month,day", [(0, 1), (13, 1), (5, 0), (4, 31), (2, 30)])
def test_impossible_month_days_are_rejected(month: int, day: int) -> None:
    with pytest.raises(ValueError):
        MonthDay(month, day)


def test_february_29_is_constructible() -> None:
    # A year-free date must stay valid in a leap year; rejecting it would make a leap-day
    # season unrepresentable.
    assert MonthDay(2, 29).day == 29
