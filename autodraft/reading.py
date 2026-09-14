"""What a document literally says, before anyone decides what to book.

`Reading` is deliberately dumb: every field on it is something printed on the
page. Interpretation — which tax base applies, whether a total already includes
a deposit — happens later, in `reconcile`, so that the faithful transcription
always survives as the thing corrections are judged against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class TaxReading:
    name: str = ""
    rate: Decimal | None = None
    amount: Decimal | None = None
    kind: str = "VAT"
    is_withholding: bool = False


@dataclass
class LineReading:
    description: str = ""
    uom: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None
    discount: Decimal | None = None
    discount_percentage: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    tax_name: str = ""
    item_type: str = "GOODS"

    @property
    def has_own_tax(self) -> bool:
        return self.tax_rate is not None or self.tax_amount is not None


@dataclass
class Reading:
    """One document, transcribed."""

    kind: str = "INVOICE"
    pages: list[int] = field(default_factory=list)

    invoice_number: str = ""
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str = ""

    supplier_name: str = ""
    supplier_address: str = ""
    supplier_vat: str = ""
    supplier_iban: str = ""
    supplier_email: str = ""

    buyer_name: str = ""
    buyer_address: str = ""
    buyer_vat: str = ""

    payment_terms_text: str = ""
    po_number: str = ""

    printed_gross: Decimal | None = None
    printed_subtotal: Decimal | None = None
    printed_tax_total: Decimal | None = None
    printed_prepayment: Decimal | None = None
    printed_rounding: Decimal | None = None

    header_discount: Decimal | None = None
    freight: Decimal | None = None
    insurance: Decimal | None = None
    other_charges: Decimal | None = None
    excise: Decimal | None = None

    header_taxes: list[TaxReading] = field(default_factory=list)
    lines: list[LineReading] = field(default_factory=list)

    prices_include_tax: bool | None = None
    reverse_charge: bool = False
    source: str = "ocr"
    notes: list[str] = field(default_factory=list)

    @property
    def line_tax_rates(self) -> list[Decimal]:
        return [line.tax_rate for line in self.lines if line.tax_rate is not None]

    @property
    def has_line_taxes(self) -> bool:
        return any(line.has_own_tax for line in self.lines)

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)
