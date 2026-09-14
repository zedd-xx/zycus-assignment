from copy import deepcopy
from decimal import Decimal

from autodraft.payables import EMPTY_PAYABLE, booked_gross, build_payable
from autodraft.reading import LineReading, Reading, TaxReading
from autodraft.reconcile import reconcile


def _reading(**overrides: object) -> Reading:
    reading = Reading(kind="INVOICE", currency="EUR")
    reading.invoice_number = "1"
    for key, value in overrides.items():
        setattr(reading, key, value)
    return reading


def test_a_clean_invoice_needs_no_hypothesis() -> None:
    reading = _reading(
        lines=[LineReading(description="Widget", quantity=Decimal(2), unit_price=Decimal(100), total=Decimal(200), tax_rate=Decimal(20), tax_amount=Decimal(40))],
        printed_subtotal=Decimal(200),
        printed_tax_total=Decimal(40),
        printed_gross=Decimal(240),
    )
    result = reconcile(reading, build_payable(reading))
    assert result.status == "reconciled_as_read"
    assert result.applied == []


def test_header_tax_restating_line_tax_is_not_charged_twice() -> None:
    reading = _reading(
        lines=[LineReading(description="Widget", quantity=Decimal(2), unit_price=Decimal(100), total=Decimal(200), tax_rate=Decimal(20), tax_amount=Decimal(40))],
        header_taxes=[TaxReading(name="VAT 20%", rate=Decimal(20), amount=Decimal(40))],
        printed_gross=Decimal(240),
    )
    result = reconcile(reading, build_payable(reading))
    assert result.books
    assert booked_gross(result.payable) == Decimal("240.00")


def test_tax_inclusive_prices_are_converted_to_net() -> None:
    reading = _reading(
        lines=[LineReading(description="Widget", quantity=Decimal(1), unit_price=Decimal(124), total=Decimal(124), tax_rate=Decimal(24))],
        printed_gross=Decimal(124),
        prices_include_tax=True,
    )
    result = reconcile(reading, build_payable(reading))
    assert result.applied == ["tax_inclusive_prices"]
    assert Decimal(result.payable["line_items"][0]["total"]) == Decimal("100.00")
    assert booked_gross(result.payable) == Decimal("124.00")


def test_a_prepayment_is_deducted_only_when_the_page_prints_one() -> None:
    reading = _reading(
        lines=[LineReading(description="Deposit", quantity=Decimal(1), unit_price=Decimal(1000), total=Decimal(1000))],
        printed_prepayment=Decimal(400),
        printed_gross=Decimal(600),
    )
    result = reconcile(reading, build_payable(reading))
    assert result.books
    assert "prepayment_already_paid" in result.applied


def test_an_unexplainable_gap_is_left_unreconciled() -> None:
    reading = _reading(
        lines=[LineReading(description="Widget", quantity=Decimal(1), unit_price=Decimal(100), total=Decimal(100))],
        printed_gross=Decimal(1_000_000),
    )
    payable = build_payable(reading)
    before = deepcopy(payable)
    result = reconcile(reading, payable)
    assert result.status == "unreconciled"
    assert result.payable["line_items"] == before["line_items"], "an unexplained gap must not be papered over"
    assert result.notes


def test_a_document_without_a_total_is_emitted_as_transcribed() -> None:
    reading = _reading(lines=[LineReading(description="Widget", total=Decimal(100))])
    result = reconcile(reading, build_payable(reading))
    assert result.status == "no_stated_total"


def test_the_empty_payable_is_the_documented_schema() -> None:
    assert EMPTY_PAYABLE["invoice_type"] == "INVOICE"
    assert EMPTY_PAYABLE["taxes"] == [] and EMPTY_PAYABLE["line_items"] == []
