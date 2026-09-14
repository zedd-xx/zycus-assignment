"""One PDF in, one output record out."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from autodraft.extract import llm as llm_backend
from autodraft.extract import read_pdf
from autodraft.masters import MasterData
from autodraft.money import parse_amount, parse_date
from autodraft.parse import classify_items, parse_document
from autodraft.payables import apply_master_data, build_payable
from autodraft.reading import LineReading, Reading, TaxReading
from autodraft.reconcile import Reconciliation, reconcile
from autodraft.segment import DECLINE_REASONS, PAYABLE_KINDS, Document, segment

log = logging.getLogger(__name__)


@dataclass
class DocumentResult:
    reading: Reading
    reconciliation: Reconciliation
    master_evidence: dict = field(default_factory=dict)


@dataclass
class FileResult:
    file: str
    payables: list[dict]
    declined: list[dict]
    documents: list[DocumentResult] = field(default_factory=list)
    error: str = ""

    def to_output(self) -> dict:
        return {"file": self.file, "payables": self.payables, "declined": self.declined}


def process_pdf(
    pdf_path: str | Path,
    masters: MasterData,
    cache_dir: str | Path | None = None,
    tenant_hint: str = "",
) -> FileResult:
    pdf_path = Path(pdf_path)
    try:
        pages = read_pdf(pdf_path, cache_dir=cache_dir)
    except Exception as error:  # a corrupt PDF must not stop the run
        log.exception("could not read %s", pdf_path.name)
        return FileResult(pdf_path.name, [], [{"doc_type": "UNREADABLE", "reason": str(error)}], error=str(error))

    documents = segment(pages)
    readings = _read_documents(pdf_path, documents)

    payables: list[dict] = []
    declined: list[dict] = []
    results: list[DocumentResult] = []

    for document, reading in zip(documents, readings, strict=True):
        if reading.kind not in PAYABLE_KINDS:
            declined.append({"doc_type": reading.kind, "reason": DECLINE_REASONS.get(reading.kind, document.decline_reason())})
            continue
        if not reading.lines and reading.printed_gross is None:
            declined.append(
                {
                    "doc_type": reading.kind,
                    "reason": "Looks like a payable but prints neither line items nor a total.",
                }
            )
            continue

        payable = build_payable(reading)
        result = reconcile(reading, payable)
        evidence = apply_master_data(result.payable, reading, masters, tenant_hint)
        payables.append(result.payable)
        results.append(DocumentResult(reading, result, evidence))

    return FileResult(pdf_path.name, payables, declined, results)


def _read_documents(pdf_path: Path, documents: list[Document]) -> list[Reading]:
    """Transcribe each document, preferring the LLM backend when it is configured."""
    if not llm_backend.backend():
        return [parse_document(document) for document in documents]

    page_numbers = [number for document in documents for number in document.page_numbers]
    ocr_text = "\n".join(document.text for document in documents)
    payload = llm_backend.read_document(pdf_path, page_numbers, ocr_text)
    if not payload or not payload.get("documents"):
        return [parse_document(document) for document in documents]

    by_page: dict[int, dict] = {}
    for entry in payload["documents"]:
        for number in entry.get("pages") or []:
            by_page.setdefault(int(number), entry)

    readings: list[Reading] = []
    for document in documents:
        entry = next((by_page[number] for number in document.page_numbers if number in by_page), None)
        fallback = parse_document(document)
        readings.append(_merge(fallback, entry) if entry else fallback)
    return readings


def _merge(fallback: Reading, entry: dict) -> Reading:
    """Trust the model for transcription, the deterministic pass for everything else."""
    reading = Reading(kind=fallback.kind, pages=fallback.pages, source=f"{fallback.source}+llm")
    reading.kind = _kind_from_llm(entry.get("doc_kind"), fallback.kind)
    reading.invoice_number = entry.get("invoice_number") or fallback.invoice_number
    reading.invoice_date = parse_date(entry.get("invoice_date") or "") or fallback.invoice_date
    reading.due_date = parse_date(entry.get("due_date") or "") or fallback.due_date
    reading.currency = (entry.get("currency") or fallback.currency or "").upper()[:3]

    supplier = entry.get("supplier") or {}
    reading.supplier_name = supplier.get("name") or fallback.supplier_name
    reading.supplier_address = supplier.get("address") or fallback.supplier_address
    reading.supplier_vat = supplier.get("vat_id") or fallback.supplier_vat
    reading.supplier_iban = supplier.get("iban") or fallback.supplier_iban
    reading.supplier_email = fallback.supplier_email

    buyer = entry.get("buyer") or {}
    reading.buyer_name = buyer.get("name") or fallback.buyer_name
    reading.buyer_address = buyer.get("address") or fallback.buyer_address
    reading.buyer_vat = buyer.get("vat_id") or fallback.buyer_vat

    reading.payment_terms_text = entry.get("payment_terms_text") or fallback.payment_terms_text
    reading.po_number = entry.get("po_number") or fallback.po_number

    reading.printed_gross = _amount(entry.get("printed_gross_total"), fallback.printed_gross)
    reading.printed_subtotal = _amount(entry.get("printed_subtotal"), fallback.printed_subtotal)
    reading.printed_tax_total = _amount(entry.get("printed_total_tax"), fallback.printed_tax_total)
    reading.printed_prepayment = _amount(entry.get("printed_prepayment"), fallback.printed_prepayment)
    reading.printed_rounding = _amount(entry.get("printed_rounding"), fallback.printed_rounding)
    reading.header_discount = _amount(entry.get("header_discount"), fallback.header_discount)
    reading.freight = _amount(entry.get("freight"), fallback.freight)
    reading.insurance = _amount(entry.get("insurance"), fallback.insurance)
    reading.other_charges = _amount(entry.get("other_charges"), fallback.other_charges)
    reading.excise = _amount(entry.get("excise"), fallback.excise)

    reading.header_taxes = [
        TaxReading(
            name=tax.get("name", ""),
            rate=parse_amount(tax.get("rate")),
            amount=parse_amount(tax.get("amount")),
        )
        for tax in entry.get("header_taxes") or []
    ] or fallback.header_taxes

    reading.lines = [
        LineReading(
            description=(item.get("description") or "").strip(),
            uom=item.get("uom", ""),
            quantity=parse_amount(item.get("quantity")),
            unit_price=parse_amount(item.get("unit_price")),
            total=parse_amount(item.get("total")),
            discount=parse_amount(item.get("discount")),
            discount_percentage=parse_amount(item.get("discount_percentage")),
            tax_rate=parse_amount(item.get("tax_rate")),
            tax_amount=parse_amount(item.get("tax_amount")),
            tax_name=item.get("tax_name", ""),
        )
        for item in entry.get("line_items") or []
    ] or fallback.lines

    includes = entry.get("prices_include_tax")
    reading.prices_include_tax = includes if isinstance(includes, bool) else fallback.prices_include_tax
    reading.reverse_charge = fallback.reverse_charge
    reading.notes = list(fallback.notes) + [note for note in entry.get("notes") or [] if isinstance(note, str)]

    classify_items(reading)
    return reading


def _kind_from_llm(kind: str | None, fallback: str) -> str:
    if kind in {"INVOICE", "CREDIT_NOTE"}:
        return kind
    if kind in {"PROFORMA", "STATEMENT", "REMITTANCE", "RECEIPT", "ORDER", "DELIVERY_NOTE", "REMINDER"}:
        return kind
    return fallback


def _amount(value: object, fallback: Decimal | None) -> Decimal | None:
    parsed = parse_amount(value) if isinstance(value, (str, int, float)) and value != "" else None
    return parsed if parsed is not None else fallback
