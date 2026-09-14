"""Transcribing a document into a `Reading`.

Header values are found by their labels; line items by the geometry of the table
the page draws. Nothing here decides anything — a value only lands on the
`Reading` if the page printed it.
"""
from __future__ import annotations

import re
from decimal import Decimal

from autodraft import lexicon
from autodraft.extract.page import TextRow
from autodraft.fields import (
    EMAIL_RE,
    contains_any,
    find_ibans,
    find_labelled_amount,
    find_labelled_value,
    find_vat_ids,
    normalise,
    tokens,
)
from autodraft.money import detect_currency, looks_like_amount, parse_amount, parse_date
from autodraft.reading import LineReading, Reading, TaxReading
from autodraft.segment import Document

_QTY_PRICE_RE = re.compile(
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*(?:x|×|\*|@)\s*(?P<price>\d[\d.,\s]*)", re.IGNORECASE
)
_RATE_RE = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
_TOTALS_STOP_LABELS = lexicon.SUBTOTAL_LABELS + lexicon.GROSS_LABELS + lexicon.TAX_TOTAL_LABELS


def parse_document(document: Document) -> Reading:
    rows = [row for page in document.pages for row in page.rows]
    text = document.text
    reading = Reading(kind=document.kind, pages=document.page_numbers)
    reading.source = document.pages[0].source if document.pages else "unknown"

    header_index, columns = _find_table_header(rows)
    # The line-table heading says "VAT  Amount"; read as a totals label it would
    # claim the first body row's figures, so totals never look at it.
    totals_rows = [row for index, row in enumerate(rows) if index != header_index]

    _read_header(reading, rows, text)
    _read_parties(reading, rows, text)
    _read_totals(reading, totals_rows)
    reading.lines = _read_lines(rows, header_index, columns)
    _read_taxes(reading, totals_rows)
    if reading.printed_tax_total is None:
        # No "total tax" label, but the tax rows themselves state amounts.
        stated = [tax.amount for tax in reading.header_taxes if tax.amount is not None]
        if stated:
            reading.printed_tax_total = sum(stated, Decimal("0"))
    _read_tax_treatment(reading, text)
    classify_items(reading)
    return reading


# ── header ────────────────────────────────────────────────────────────────
def _read_header(reading: Reading, rows: list[TextRow], text: str) -> None:
    number = find_labelled_value(rows, lexicon.INVOICE_NUMBER_LABELS)
    reading.invoice_number = _clean_identifier(number)

    invoice_date = find_labelled_value(rows, lexicon.INVOICE_DATE_LABELS)
    reading.invoice_date = parse_date(invoice_date or "") or parse_date(text)
    due = find_labelled_value(rows, lexicon.DUE_DATE_LABELS)
    reading.due_date = parse_date(due or "")

    terms = find_labelled_value(rows, lexicon.PAYMENT_TERM_LABELS)
    reading.payment_terms_text = (terms or "").strip()[:120]

    po_value = find_labelled_value(rows, lexicon.PO_LABELS)
    reading.po_number = _clean_identifier(po_value)

    reading.currency = detect_currency(text)


def _clean_identifier(value: str | None) -> str:
    """The identifier a label points at, keeping a short alphabetic prefix.

    Numbers are printed as "265345", "FT 2026/118" or "No. 4471": the first
    token is taken, and a leading series prefix is kept with the digits it
    belongs to rather than being dropped or treated as the number itself.
    """
    if not value:
        return ""
    parts = value.strip().split()
    if not parts:
        return ""
    candidate = parts[0].strip(".,;:#")
    if not any(char.isdigit() for char in candidate):
        following = parts[1].strip(".,;:#") if len(parts) > 1 else ""
        if not any(char.isdigit() for char in following):
            return ""
        prefix = candidate.strip(".")
        candidate = f"{prefix} {following}" if len(prefix) <= 4 and prefix.isalpha() else following
    return candidate[:40]


# ── parties ───────────────────────────────────────────────────────────────
def _read_parties(reading: Reading, rows: list[TextRow], text: str) -> None:
    supplier_rows = rows[: min(len(rows), 14)]
    reading.supplier_name = _guess_supplier_name(supplier_rows)
    reading.supplier_address = _join_address(supplier_rows, reading.supplier_name)

    vat_ids = find_vat_ids(text)
    if vat_ids:
        reading.supplier_vat = vat_ids[0]
        if len(vat_ids) > 1:
            reading.buyer_vat = vat_ids[1]
    ibans = find_ibans(text)
    if ibans:
        reading.supplier_iban = ibans[0]
    email = EMAIL_RE.search(text)
    if email:
        reading.supplier_email = email.group()

    reading.buyer_name, reading.buyer_address = _read_bill_to(rows)


_COMPANY_SUFFIXES = (
    "gmbh", "ag", "kg", "ohg", "ltd", "limited", "plc", "llc", "inc", "corp",
    "bv", "nv", "oy", "ab", "as", "ou", "osauhing", "sa", "lda", "unipessoal",
    "sdn", "bhd", "srl", "spa", "sarl", "sas", "pte", "pty", "co",
)
_BILL_TO_LABELS = (
    "bill to", "billed to", "invoice to", "sold to", "customer", "client",
    "rechnungsempfanger", "rechnungsempfänger", "rechnung an", "kunde",
    "arve saaja", "maksja", "klient", "cliente", "faturar a", "kepada",
    "pelanggan", "buyer", "ship to",
)


def _guess_supplier_name(rows: list[TextRow]) -> str:
    """The issuer is the first company-looking line near the top of the page."""
    for row in rows:
        text = row.text.strip()
        if len(text) < 3 or len(text) > 80:
            continue
        lowered = normalise(text)
        if any(title in lowered for titles in lexicon.ALL_DOC_TITLES.values() for title in titles):
            continue
        if any(suffix in tokens(text) for suffix in _COMPANY_SUFFIXES):
            return text
    for row in rows[:6]:
        text = row.text.strip()
        if 3 <= len(text) <= 60 and not any(char.isdigit() for char in text):
            lowered = normalise(text)
            if not any(title in lowered for titles in lexicon.ALL_DOC_TITLES.values() for title in titles):
                return text
    return ""


def _join_address(rows: list[TextRow], supplier_name: str) -> str:
    if not supplier_name:
        return ""
    collected: list[str] = []
    seen_name = False
    for row in rows:
        text = row.text.strip()
        if not seen_name:
            seen_name = supplier_name in text
            continue
        if not text or len(collected) >= 3:
            break
        lowered = normalise(text)
        if any(label in lowered for label in _BILL_TO_LABELS):
            break
        if any(title in lowered for titles in lexicon.ALL_DOC_TITLES.values() for title in titles):
            break
        collected.append(text)
    return ", ".join(collected)[:160]


def _read_bill_to(rows: list[TextRow]) -> tuple[str, str]:
    for index, row in enumerate(rows):
        lowered = normalise(row.text)
        if not any(label in lowered for label in _BILL_TO_LABELS):
            continue
        following = [r.text.strip() for r in rows[index + 1: index + 5] if r.text.strip()]
        if following:
            return following[0][:80], ", ".join(following[1:3])[:160]
    return "", ""


# ── totals ────────────────────────────────────────────────────────────────
def _read_totals(reading: Reading, rows: list[TextRow]) -> None:
    skip = lexicon.IDENTIFIER_LABELS
    reading.printed_gross = find_labelled_amount(rows, lexicon.GROSS_LABELS, skip)
    reading.printed_subtotal = find_labelled_amount(rows, lexicon.SUBTOTAL_LABELS, skip)
    reading.printed_tax_total = find_labelled_amount(rows, lexicon.TAX_TOTAL_LABELS, skip)
    reading.printed_prepayment = find_labelled_amount(rows, lexicon.PREPAYMENT_WORDS, skip)
    reading.printed_rounding = find_labelled_amount(rows, lexicon.ROUNDING_WORDS, skip)
    reading.freight = find_labelled_amount(rows, lexicon.FREIGHT_WORDS, skip)
    reading.insurance = find_labelled_amount(rows, lexicon.INSURANCE_WORDS, skip)
    reading.excise = find_labelled_amount(rows, lexicon.EXCISE_WORDS, skip)

    charges = find_labelled_amount(rows, lexicon.CHARGE_WORDS, skip)
    if charges is not None and charges != reading.freight:
        reading.other_charges = charges

    discount = find_labelled_amount(rows, lexicon.DISCOUNT_WORDS, skip)
    if discount is not None:
        reading.header_discount = abs(discount)


# ── line items ────────────────────────────────────────────────────────────
_COLUMN_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("quantity", lexicon.COLUMN_QUANTITY),
    ("unit_price", lexicon.COLUMN_UNIT_PRICE),
    ("total", lexicon.COLUMN_TOTAL),
    ("tax", lexicon.COLUMN_TAX),
    ("discount", lexicon.COLUMN_DISCOUNT),
    ("uom", lexicon.COLUMN_UOM),
    ("description", lexicon.COLUMN_DESCRIPTION),
)


def _read_lines(
    rows: list[TextRow], header_index: int | None, columns: dict[str, tuple[float, float]]
) -> list[LineReading]:
    if header_index is None:
        return _read_lines_without_header(rows)

    body = rows[header_index + 1:]
    lines: list[LineReading] = []
    for row in body:
        if _is_totals_row(row):
            break
        cells = _cells(row, columns)
        line = _line_from_cells(cells, row)
        if line is None:
            if lines and _is_description_continuation(cells, row):
                lines[-1].description = f"{lines[-1].description} {row.text.strip()}".strip()
            continue
        lines.append(line)
    return [line for line in lines if _is_plausible_line(line)]


def _find_table_header(rows: list[TextRow]) -> tuple[int | None, dict[str, tuple[float, float]]]:
    for index, row in enumerate(rows):
        columns = _columns_from_row(row)
        kinds = set(columns)
        if len(kinds) >= 3 or ({"quantity", "unit_price"} <= kinds) or ({"description", "total"} <= kinds):
            return index, columns
    return None, {}


def _columns_from_row(row: TextRow) -> dict[str, tuple[float, float]]:
    """Column anchors from a header row, matching multi-word headings too.

    "Unit price" and "Preco unitario" are one heading printed as two words, so
    the row is scanned in windows rather than word by word, longest window
    first, and each word is claimed by at most one heading.
    """
    words = row.words
    labels = [normalise(word.text).strip(".:%()") for word in words]
    columns: dict[str, tuple[float, float]] = {}
    claimed: set[int] = set()
    for width in (3, 2, 1):
        for start in range(len(words) - width + 1):
            span = range(start, start + width)
            if any(index in claimed for index in span):
                continue
            phrase = " ".join(labels[index] for index in span).strip()
            if not phrase:
                continue
            for kind, vocabulary in _COLUMN_KINDS:
                if kind in columns:
                    continue
                if any(phrase == normalise(entry) for entry in vocabulary):
                    columns[kind] = (words[start].x0, words[start + width - 1].x1)
                    claimed.update(span)
                    break
    return columns


def _cells(row: TextRow, columns: dict[str, tuple[float, float]]) -> dict[str, str]:
    if not columns:
        return {}
    bounds = _column_bounds(columns)
    cells: dict[str, list[str]] = {kind: [] for kind in columns}
    for word in row.words:
        centre = (word.x0 + word.x1) / 2
        kind = _column_for(centre, bounds)
        if kind:
            cells[kind].append(word.text)
    return {kind: " ".join(parts).strip() for kind, parts in cells.items()}


def _column_bounds(columns: dict[str, tuple[float, float]]) -> list[tuple[str, float, float]]:
    ordered = sorted(columns.items(), key=lambda item: item[1][0])
    bounds: list[tuple[str, float, float]] = []
    for index, (kind, (x0, x1)) in enumerate(ordered):
        left = 0.0 if index == 0 else (ordered[index - 1][1][1] + x0) / 2
        right = float("inf") if index == len(ordered) - 1 else (x1 + ordered[index + 1][1][0]) / 2
        bounds.append((kind, left, right))
    return bounds


def _column_for(x: float, bounds: list[tuple[str, float, float]]) -> str | None:
    for kind, left, right in bounds:
        if left <= x < right:
            return kind
    return None


def _line_from_cells(cells: dict[str, str], row: TextRow) -> LineReading | None:
    description = cells.get("description", "").strip()
    quantity = parse_amount(cells.get("quantity", ""))
    unit_price = parse_amount(cells.get("unit_price", ""))
    total = parse_amount(cells.get("total", ""))
    if total is None and unit_price is None and quantity is None:
        return None
    if not description and total is None:
        return None

    line = LineReading(
        description=description,
        uom=_clean_uom(cells.get("uom", "")) or _uom_from_quantity(cells.get("quantity", "")),
        quantity=quantity,
        unit_price=unit_price,
        total=total,
    )
    _apply_tax_cell(line, cells.get("tax", ""))
    _apply_discount_cell(line, cells.get("discount", ""))
    _fill_missing_components(line, row)
    return line


def _read_lines_without_header(rows: list[TextRow]) -> list[LineReading]:
    """Tables that print no header: rows of text ending in amounts."""
    lines: list[LineReading] = []
    for row in rows:
        if _is_totals_row(row):
            break
        text = row.text.strip()
        if len(text) < 4:
            continue
        amounts = _row_amounts(row)
        if len(amounts) < 1 or not re.search(r"[A-Za-z]{3,}", text):
            continue
        description = re.sub(r"[\d.,%€$£]+\s*$", "", text).strip()
        line = LineReading(description=description[:200], total=amounts[-1])
        _fill_missing_components(line, row)
        if _is_plausible_line(line):
            lines.append(line)
    return lines


def _apply_tax_cell(line: LineReading, cell: str) -> None:
    if not cell:
        return
    match = _RATE_RE.search(cell)
    if match:
        line.tax_rate = parse_amount(match.group(1))
        return
    value = parse_amount(cell)
    if value is None:
        return
    # A bare number in a tax column is a rate when small, an amount otherwise.
    line.tax_rate = value if value <= 40 else None
    if line.tax_rate is None:
        line.tax_amount = value


def _apply_discount_cell(line: LineReading, cell: str) -> None:
    if not cell:
        return
    if "%" in cell:
        line.discount_percentage = parse_amount(cell)
        return
    value = parse_amount(cell)
    if value is not None and value != 0:
        line.discount = abs(value)


def _fill_missing_components(line: LineReading, row: TextRow) -> None:
    """Recover quantity/price from the row's own wording, never by arithmetic."""
    if line.quantity is None or line.unit_price is None:
        match = _QTY_PRICE_RE.search(row.text)
        if match:
            line.quantity = line.quantity if line.quantity is not None else parse_amount(match.group("qty"))
            line.unit_price = line.unit_price if line.unit_price is not None else parse_amount(match.group("price"))

    if line.unit_price is not None and line.quantity is None and line.total is not None:
        if line.unit_price == line.total:
            line.quantity = Decimal("1")
    if line.quantity is None and line.unit_price is None and line.total is not None:
        line.quantity = Decimal("1")
        line.unit_price = line.total


def _clean_uom(cell: str) -> str:
    cell = cell.strip()
    if not cell or any(char.isdigit() for char in cell):
        return ""
    return cell[:12]


def _uom_from_quantity(cell: str) -> str:
    match = re.search(r"\d[\d.,]*\s*([A-Za-z]{1,6})\b", cell or "")
    return match.group(1) if match else ""


def _row_amounts(row: TextRow) -> list[Decimal]:
    """Every money-looking token on a row, left to right."""
    values: list[Decimal] = []
    for word in row.words:
        if not looks_like_amount(word.text):
            continue
        amount = parse_amount(word.text)
        if amount is not None:
            values.append(amount)
    return values


def _is_totals_row(row: TextRow) -> bool:
    lowered = normalise(row.text)
    return any(label in lowered for label in _TOTALS_STOP_LABELS)


def _is_description_continuation(cells: dict[str, str], row: TextRow) -> bool:
    text = row.text.strip()
    if not text or len(text) < 3:
        return False
    return not _row_amounts(row)


def _is_plausible_line(line: LineReading) -> bool:
    if not line.description or len(line.description) < 2:
        return False
    if line.total is None and line.unit_price is None:
        return False
    return bool(re.search(r"[A-Za-z]", line.description))


# ── taxes ─────────────────────────────────────────────────────────────────
def _read_taxes(reading: Reading, rows: list[TextRow]) -> None:
    """Header taxes are the tax rows printed in the totals block."""
    taxes: list[TaxReading] = []
    for row in rows:
        text = row.text.strip()
        lowered = normalise(text)
        tax_word = contains_any(text, lexicon.TAX_WORDS)
        if not tax_word:
            continue
        if any(label in lowered for label in lexicon.SUBTOTAL_LABELS):
            continue
        if any(label in lowered for label in lexicon.IDENTIFIER_LABELS):
            continue  # "VAT ID: DE209177122" is a registration, not a tax
        rate_match = _RATE_RE.search(text)
        amounts = _row_amounts(row)
        rate = parse_amount(rate_match.group(1)) if rate_match else None
        amount = amounts[-1] if amounts else None
        if rate is not None and amount is not None and amount == rate:
            amount = None
        if rate is None and amount is None:
            continue

        withholding = contains_any(text, lexicon.WITHHOLDING_WORDS) is not None
        if withholding and amount is not None:
            amount = -abs(amount)
        taxes.append(
            TaxReading(
                name=_tax_name(text),
                rate=rate,
                amount=amount,
                kind=_tax_kind(lowered),
                is_withholding=withholding,
            )
        )

    reading.header_taxes = _dedupe_taxes(taxes)


def _tax_name(text: str) -> str:
    cleaned = re.sub(r"[\d.,]{3,}\s*$", "", text).strip(" .:-")
    return cleaned[:60]


def _tax_kind(lowered: str) -> str:
    if any(word in lowered for word in ("iva",)):
        return "IVA"
    if "gst" in lowered:
        return "GST"
    if "sst" in lowered:
        return "SST"
    if any(word in lowered for word in lexicon.WITHHOLDING_WORDS):
        return "WHT"
    if "levy" in lowered or "nhil" in lowered or "getfund" in lowered:
        return "LEVY"
    return "VAT"


def _dedupe_taxes(taxes: list[TaxReading]) -> list[TaxReading]:
    unique: list[TaxReading] = []
    for tax in taxes:
        key = (tax.rate, tax.amount, tax.kind)
        if any((other.rate, other.amount, other.kind) == key for other in unique):
            continue
        unique.append(tax)
    return unique


def _read_tax_treatment(reading: Reading, text: str) -> None:
    if contains_any(text, lexicon.TAX_INCLUSIVE_WORDS):
        reading.prices_include_tax = True
        reading.note("Page states prices include tax.")
    elif contains_any(text, lexicon.TAX_EXCLUSIVE_WORDS):
        reading.prices_include_tax = False
    if contains_any(text, lexicon.REVERSE_CHARGE_WORDS):
        reading.reverse_charge = True
        reading.note("Page states a reverse-charge / zero-rated supply.")


def classify_items(reading: Reading) -> None:
    for line in reading.lines:
        lowered = normalise(line.description)
        if any(word in lowered for word in lexicon.FREIGHT_ITEM_WORDS):
            line.item_type = "FREIGHT"
        elif any(word in lowered for word in lexicon.TAX_WORDS) and len(lowered) < 30:
            line.item_type = "TAX"
        elif any(word in lowered for word in lexicon.SERVICE_WORDS):
            line.item_type = "SERVICE"
        else:
            line.item_type = "GOODS"
