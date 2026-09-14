from datetime import date
from decimal import Decimal

import pytest

from autodraft.money import detect_currency, looks_like_amount, money, parse_amount, parse_date


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1'234.56", "1234.56"),
        ("1234", "1234"),
        ("0,00", "0.00"),
        ("(120.00)", "-120.00"),
        ("120,00-", "-120.00"),
        ("€ 1.500,00", "1500.00"),
        ("12,5", "12.5"),
        ("1.500", "1500"),
    ],
)
def test_parse_amount_handles_locales(printed: str, expected: str) -> None:
    assert parse_amount(printed) == Decimal(expected)


def test_parse_amount_distinguishes_absent_from_zero() -> None:
    assert parse_amount("") is None
    assert parse_amount("n/a") is None
    assert parse_amount("0") == Decimal("0")


@pytest.mark.parametrize(
    ("token", "is_amount"),
    [
        ("1.254,00", True),
        ("(120.00)", True),
        ("19%", True),
        ("DE209177122", False),
        ("GHA-VAT-887766", False),
        ("EUR", False),
        ("2026-0455", False),
    ],
)
def test_looks_like_amount_rejects_identifiers(token: str, is_amount: bool) -> None:
    assert looks_like_amount(token) is is_amount


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("02.02.2026", date(2026, 2, 2)),
        ("2026-03-04", date(2026, 3, 4)),
        ("11/03/2026", date(2026, 3, 11)),
        ("4 March 2026", date(2026, 3, 4)),
        ("4. Marz 2026", date(2026, 3, 4)),
    ],
)
def test_parse_date_reads_numeric_and_written_dates(printed: str, expected: date) -> None:
    assert parse_date(printed) == expected


def test_money_is_always_two_decimals() -> None:
    assert money(Decimal("1234.5")) == "1234.50"
    assert money(None) == ""


def test_detect_currency_prefers_an_explicit_code() -> None:
    assert detect_currency("Total due: 521.22 EUR") == "EUR"
    assert detect_currency("Jumlah: RM 450.00") == "MYR"
    assert detect_currency("no currency here") == ""
