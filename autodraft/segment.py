"""Splitting a PDF into documents, and deciding what each one is.

A file is not a document. The pipeline treats every PDF as a stack of pages and
asks two questions in order: where does one document end and the next begin, and
what kind of thing is each of them. Only then does anything try to read a
payable out of it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from autodraft import lexicon
from autodraft.extract.page import Page
from autodraft.fields import find_labelled_value, normalise

PAYABLE_KINDS = {"INVOICE", "CREDIT_NOTE"}

DECLINE_REASONS = {
    "PROFORMA": "Proforma/quotation: an offer, not a booked payable.",
    "STATEMENT": "Account statement: lists other documents, is not itself owed.",
    "REMITTANCE": "Remittance/payment advice: reports a payment, creates no liability.",
    "RECEIPT": "Receipt: evidences a payment already made.",
    "ORDER": "Purchase/sales order: a commitment to buy, not a supplier claim.",
    "DELIVERY_NOTE": "Delivery note/packing list: movement of goods, no amount owed.",
    "REMINDER": "Payment reminder/dunning: restates an existing invoice.",
    "CONTRACT": "Contract/terms/correspondence: no payable content.",
    "OTHER": "No payable content identified on the page.",
}

_PAGE_OF_RE = re.compile(
    r"\b(?:page|seite|lehekulg|lehekülg|pagina|página|muka surat|blatt)\s*"
    r"(\d{1,3})\s*(?:/|of|von|van|de|dari|from)\s*(\d{1,3})\b",
    re.IGNORECASE,
)
_PAGE_SLASH_RE = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b")
_CONTINUATION_WORDS = ("continued", "fortsetzung", "jätkub", "jatkub", "continuacao", "continuação", "carried forward")


@dataclass
class Document:
    """One logical document inside a PDF."""

    kind: str
    pages: list[Page]
    title_hit: str = ""
    signals: dict[str, object] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)

    @property
    def lowered(self) -> str:
        return normalise(self.text)

    @property
    def page_numbers(self) -> list[int]:
        return [page.number for page in self.pages]

    @property
    def is_payable_candidate(self) -> bool:
        return self.kind in PAYABLE_KINDS

    def decline_reason(self) -> str:
        return DECLINE_REASONS.get(self.kind, DECLINE_REASONS["OTHER"])


def segment(pages: list[Page]) -> list[Document]:
    """Group pages into documents and classify each one."""
    if not pages:
        return []

    groups: list[list[Page]] = []
    previous_identity: tuple[str, str] | None = None
    for page in pages:
        identity = _page_identity(page)
        if not groups or _starts_new_document(page, identity, previous_identity):
            groups.append([page])
        else:
            groups[-1].append(page)
        if identity[0] or identity[1]:
            previous_identity = identity

    return [_classify(group) for group in groups]


def _page_identity(page: Page) -> tuple[str, str]:
    """(document number, title kind) as printed on this page."""
    number = find_labelled_value(page.rows, lexicon.INVOICE_NUMBER_LABELS) or ""
    return normalise(number), _title_kind(page)[0]


def _starts_new_document(page: Page, identity: tuple[str, str], previous: tuple[str, str] | None) -> bool:
    text = normalise(page.text)
    page_index, page_count = _page_position(text)
    if page_index and page_index > 1:
        return False
    if any(word in text for word in _CONTINUATION_WORDS):
        return False
    if previous is None:
        return True

    number, kind = identity
    previous_number, previous_kind = previous
    if number and previous_number and number != previous_number:
        return True
    if kind and previous_kind and kind != previous_kind:
        return True
    if page_index == 1 and page_count and page_count > 1:
        return True
    # No shared identity and this page announces itself with a title: new document.
    return bool(kind) and not number and not previous_number


def _page_position(text: str) -> tuple[int | None, int | None]:
    match = _PAGE_OF_RE.search(text)
    if match:
        return int(match.group(1)), int(match.group(2))
    for match in _PAGE_SLASH_RE.finditer(text):
        index, count = int(match.group(1)), int(match.group(2))
        if 1 <= index <= count <= 20 and "page" in text:
            return index, count
    return None, None


def _title_kind(page: Page) -> tuple[str, str]:
    """The document kind announced by a title on this page, plus the phrase that said so."""
    rows = page.rows
    if not rows:
        return "", ""
    top_rows = rows[: max(8, len(rows) // 4)]
    header_text = normalise(" \n".join(row.text for row in top_rows))
    whole_text = normalise(page.text)

    # The document announces itself with the first title it prints; "invoice"
    # then appears again further down half the statements and reminders there are.
    best: tuple[int, int, str, str] | None = None
    for kind, titles in lexicon.ALL_DOC_TITLES.items():
        for title in titles:
            position = header_text.find(title)
            if position == -1:
                continue
            candidate = (position, -len(title), kind, title)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    if best is not None:
        return best[2], best[3]

    for kind, titles in lexicon.ALL_DOC_TITLES.items():
        if kind == "INVOICE":
            continue  # the word "invoice" appears on half of all documents
        for title in sorted(titles, key=len, reverse=True):
            if title in whole_text:
                return kind, title
    return "", ""


def _classify(pages: list[Page]) -> Document:
    """Decide what a group of pages is, from its title and what it contains."""
    text = normalise("\n".join(page.text for page in pages))
    kind, title = "", ""
    for page in pages:
        kind, title = _title_kind(page)
        if kind:
            break

    signals: dict[str, object] = {
        "has_amount_due": _mentions(text, lexicon.GROSS_LABELS),
        "has_tax_words": _mentions(text, lexicon.TAX_WORDS),
        "has_bank_details": _mentions(text, lexicon.IBAN_LABELS),
        "negative_language": _mentions(text, lexicon.CREDIT_TITLES),
    }

    resolved = _resolve_kind(kind, text, signals)
    return Document(resolved, pages, title, signals)


def _resolve_kind(title_kind: str, text: str, signals: dict[str, object]) -> str:
    if title_kind == "CREDIT_NOTE":
        return "CREDIT_NOTE"
    if title_kind in {"STATEMENT", "REMITTANCE", "RECEIPT", "ORDER", "DELIVERY_NOTE", "REMINDER", "PROFORMA", "CONTRACT"}:
        # A credit note titled inside a statement page still reads as a statement.
        return title_kind
    if title_kind == "INVOICE":
        return "CREDIT_NOTE" if _credit_worded(text) else "INVOICE"
    if signals["has_amount_due"] and signals["has_tax_words"]:
        return "CREDIT_NOTE" if _credit_worded(text) else "INVOICE"
    return "OTHER"


def _credit_worded(text: str) -> bool:
    return any(title in text for title in lexicon.CREDIT_TITLES)


def _mentions(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)
