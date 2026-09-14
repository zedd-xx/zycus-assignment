"""Turning a `Reading` into the autodraft record, and back into numbers.

The builder is faithful by construction: it copies the transcription into the
schema's fields and places each tax where the document placed it. It never
balances anything — that question belongs to `reconcile`.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from autodraft.masters import MasterData
from autodraft.money import iso, money, parse_amount, quantity
from autodraft.money import rate as fmt_rate
from autodraft.reading import LineReading, Reading, TaxReading
from erp import erp_book

EMPTY_PAYABLE: dict = {
    "invoice_number": "",
    "invoice_date": "",
    "due_date": "",
    "invoice_type": "INVOICE",
    "currency": "",
    "supplier": {"name": "", "supplier_id": "", "address": "", "vat_id": ""},
    "buyer": {"company_code": "", "business_unit_code": "", "location_code": ""},
    "payment_term_id": "",
    "po_number": "",
    "po_id": "",
    "gross_total": "",
    "subtotal": "",
    "total_tax_amount": "",
    "discount_amount": "",
    "freight_charges": "",
    "insurance_charges": "",
    "extra_charges": "",
    "excise_duties": "",
    "taxes": [],
    "line_items": [],
}


def build_payable(reading: Reading) -> dict:
    """The faithful autodraft: what the document says, in the schema's shape."""
    payable = deepcopy(EMPTY_PAYABLE)
    payable["invoice_number"] = reading.invoice_number
    payable["invoice_date"] = iso(reading.invoice_date)
    payable["due_date"] = iso(reading.due_date)
    payable["invoice_type"] = "CREDIT_MEMO" if reading.kind == "CREDIT_NOTE" else "INVOICE"
    payable["currency"] = reading.currency

    payable["supplier"] = {
        "name": reading.supplier_name,
        "supplier_id": "",
        "address": reading.supplier_address,
        "vat_id": reading.supplier_vat,
    }
    payable["po_number"] = reading.po_number

    payable["gross_total"] = money(_magnitude(reading.printed_gross))
    payable["subtotal"] = money(_magnitude(reading.printed_subtotal))
    payable["total_tax_amount"] = money(_magnitude(reading.printed_tax_total))

    payable["discount_amount"] = money(_magnitude(reading.header_discount))
    payable["freight_charges"] = money(_magnitude(reading.freight))
    payable["insurance_charges"] = money(_magnitude(reading.insurance))
    payable["extra_charges"] = money(_magnitude(reading.other_charges))
    payable["excise_duties"] = money(_magnitude(reading.excise))

    payable["line_items"] = [_line_to_dict(line) for line in reading.lines]
    payable["taxes"] = [_tax_to_dict(tax) for tax in reading.header_taxes]
    _drop_charges_already_itemised(payable, reading)
    return payable


def _magnitude(value: Decimal | None) -> Decimal | None:
    """Credit memos are delivered as positive magnitudes, as the schema requires."""
    return None if value is None else abs(value)


def _line_to_dict(line: LineReading) -> dict:
    item: dict = {
        "description": line.description.strip(),
        "item_type": line.item_type,
        "uom": line.uom,
        "quantity": quantity(_magnitude(line.quantity)),
        "unit_price": money(_magnitude(line.unit_price)),
        "total": money(_magnitude(line.total)),
        "discount": money(_magnitude(line.discount)),
        "discount_percentage": fmt_rate(line.discount_percentage),
        "tax_rate": fmt_rate(line.tax_rate),
        "tax_amount": money(line.tax_amount) if line.tax_amount is not None else "",
        "taxes": [],
    }
    if line.tax_rate is not None or line.tax_amount is not None:
        item["taxes"] = [
            {
                "tax_type": "VAT",
                "tax_name": line.tax_name or _default_tax_name(line.tax_rate),
                "tax_rate": fmt_rate(line.tax_rate),
                "tax_amount": money(line.tax_amount) if line.tax_amount is not None else "",
                "tax_type_code": "",
            }
        ]
        # The ERP reads taxes[] when present; the scalar fields stay as printed.
    return item


def _default_tax_name(rate: Decimal | None) -> str:
    return f"VAT {fmt_rate(rate)}%" if rate is not None else "VAT"


def _tax_to_dict(tax: TaxReading) -> dict:
    return {
        "tax_type": tax.kind,
        "tax_name": tax.name or tax.kind,
        "tax_rate": fmt_rate(tax.rate),
        "tax_amount": money(tax.amount) if tax.amount is not None else "",
        "tax_type_code": "",
    }


def _drop_charges_already_itemised(payable: dict, reading: Reading) -> None:
    """A freight charge printed as a line is not also a header charge."""
    for field_name, value in (
        ("freight_charges", reading.freight),
        ("insurance_charges", reading.insurance),
        ("extra_charges", reading.other_charges),
        ("excise_duties", reading.excise),
    ):
        if value is None:
            continue
        for item in payable["line_items"]:
            if parse_amount(item.get("total")) == abs(value):
                payable[field_name] = ""
                break


# ── recompute helpers ──────────────────────────────────────────────────────
def booked_gross(payable: dict) -> Decimal:
    """What the ERP will book for this payable."""
    result = erp_book(payable)
    return Decimal(str(result["will_book_gross"]))


def stated_gross(reading: Reading) -> Decimal | None:
    """What the document itself says is owed."""
    if reading.printed_gross is None:
        return None
    return abs(reading.printed_gross)


def apply_master_data(payable: dict, reading: Reading, masters: MasterData, tenant_hint: str = "") -> dict:
    """Fill every code that resolves, and leave the rest honestly empty."""
    evidence: dict[str, str] = {}

    supplier = masters.suppliers.match(
        name=reading.supplier_name,
        vat_id=reading.supplier_vat,
        iban=reading.supplier_iban,
        email=reading.supplier_email,
        address=reading.supplier_address,
    )
    payable["supplier"]["supplier_id"] = supplier.code
    if supplier.matched:
        evidence["supplier_id"] = supplier.reason

    buyer = masters.org.match(
        name=reading.buyer_name,
        address=reading.buyer_address,
        vat_id=reading.buyer_vat,
        tenant_hint=tenant_hint,
    )
    payable["buyer"] = {
        "company_code": buyer.company_code,
        "business_unit_code": buyer.business_unit_code,
        "location_code": buyer.location_code,
    }
    if buyer.matched:
        evidence["buyer"] = buyer.reason

    days = None
    if reading.invoice_date and reading.due_date:
        days = (reading.due_date - reading.invoice_date).days
    term = masters.payment_terms.match(reading.payment_terms_text, days)
    payable["payment_term_id"] = term.code
    if term.matched:
        evidence["payment_term_id"] = term.reason

    if payable["po_number"]:
        po = masters.purchase_orders.match(payable["po_number"])
        payable["po_id"] = po.code
        evidence["po_id"] = po.reason

    country = _country_of(reading)
    for tax in payable["taxes"]:
        code = masters.taxes.match(
            parse_amount(tax.get("tax_rate")), country, tax.get("tax_type", ""), tax.get("tax_name", "")
        )
        tax["tax_type_code"] = code.code
    for item in payable["line_items"]:
        for tax in item.get("taxes", []):
            code = masters.taxes.match(
                parse_amount(tax.get("tax_rate")), country, tax.get("tax_type", ""), tax.get("tax_name", "")
            )
            tax["tax_type_code"] = code.code
    return evidence


_CURRENCY_COUNTRY = {
    "GHS": "GH", "MYR": "MY", "ZAR": "ZA", "KES": "KE", "GBP": "GB",
    "NGN": "NG", "USD": "US", "INR": "IN",
}


def _country_of(reading: Reading) -> str:
    """The country whose tax regime the document is under, from its own evidence."""
    vat = (reading.supplier_vat or "").upper()
    if vat.startswith("GHA"):
        return "GH"
    if len(vat) >= 2 and vat[:2].isalpha():
        return vat[:2]
    address = (reading.supplier_address or "").upper()
    for code in ("DE", "EE", "PT", "MY", "GH", "ZA", "KE", "GB"):
        if address.endswith(code) or f", {code}" in address:
            return code
    return _CURRENCY_COUNTRY.get(reading.currency, "")
