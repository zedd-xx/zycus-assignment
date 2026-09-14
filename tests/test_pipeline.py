import json
from decimal import Decimal
from pathlib import Path

import pytest

from autodraft.masters import MasterData
from autodraft.payables import EMPTY_PAYABLE, booked_gross
from autodraft.pipeline import FileResult, process_pdf

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def run(documents: Path, masters: MasterData, cache: Path) -> dict[str, FileResult]:
    return {
        path.name: process_pdf(path, masters, cache_dir=cache)
        for path in sorted(documents.glob("*.pdf"))
    }


def test_every_document_produces_a_result(run: dict[str, FileResult]) -> None:
    assert len(run) == 8
    assert all(not result.error for result in run.values())


def test_output_shape_is_the_contract(run: dict[str, FileResult]) -> None:
    output = run["01_simple_invoice.pdf"].to_output()
    assert set(output) == {"file", "payables", "declined"}
    assert output["file"] == "01_simple_invoice.pdf"


def test_payables_use_exactly_the_schema_fields(run: dict[str, FileResult]) -> None:
    for result in run.values():
        for payable in result.payables:
            assert set(payable) == set(EMPTY_PAYABLE)
            for item in payable["line_items"]:
                assert set(item) >= {"description", "quantity", "unit_price", "total", "taxes"}


def test_every_payable_books_to_its_own_printed_total(run: dict[str, FileResult]) -> None:
    for name, result in run.items():
        for document in result.documents:
            stated = document.reconciliation.stated
            if stated is None:
                continue
            booked = booked_gross(document.reconciliation.payable)
            assert abs(booked - stated) <= Decimal("0.005"), (
                f"{name} books {booked}, the page states {stated}"
            )


def test_a_statement_is_declined_not_booked(run: dict[str, FileResult]) -> None:
    result = run["05_statement.pdf"]
    assert result.payables == []
    assert result.declined and result.declined[0]["doc_type"] == "STATEMENT"
    assert result.declined[0]["reason"]


def test_credit_note_is_a_credit_memo_with_positive_magnitudes(run: dict[str, FileResult]) -> None:
    payable = run["04_credit_note.pdf"].payables[0]
    assert payable["invoice_type"] == "CREDIT_MEMO"
    assert Decimal(payable["gross_total"]) > 0
    assert all(Decimal(item["total"]) > 0 for item in payable["line_items"])


def test_two_documents_in_one_file_become_two_payables(run: dict[str, FileResult]) -> None:
    payables = run["07_two_invoices.pdf"].payables
    assert len(payables) == 2
    assert payables[0]["invoice_number"] != payables[1]["invoice_number"]


def test_line_taxes_stay_on_lines(run: dict[str, FileResult]) -> None:
    payable = run["03_mixed_rate_invoice.pdf"].payables[0]
    rates = {item["tax_rate"] for item in payable["line_items"]}
    assert len(rates) > 1, "distinct printed rates must not be collapsed into one"
    assert payable["taxes"] == [] or all(tax["tax_rate"] for tax in payable["taxes"])


def test_german_locale_amounts_are_read_as_numbers(run: dict[str, FileResult]) -> None:
    payable = run["08_german_locale.pdf"].payables[0]
    assert Decimal(payable["gross_total"]) == Decimal("1492.26")
    assert payable["currency"] == "EUR"


def test_supplier_codes_come_from_the_master_or_stay_empty(run: dict[str, FileResult]) -> None:
    known = {record["supplier_id"] for record in json.loads((ROOT / "master_data" / "suppliers.json").read_text())["suppliers"]}
    for result in run.values():
        for payable in result.payables:
            assert payable["supplier"]["supplier_id"] in known | {""}
            assert payable["po_id"] in {""} or payable["po_id"].startswith("PO-")


def test_nothing_is_invented_when_the_page_is_silent(run: dict[str, FileResult]) -> None:
    payable = run["01_simple_invoice.pdf"].payables[0]
    assert payable["insurance_charges"] == ""
    assert payable["excise_duties"] == ""
