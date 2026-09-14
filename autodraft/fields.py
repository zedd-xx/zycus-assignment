"""Reading labelled values off a page.

Documents put a label next to its value — to the right of it, or under it. These
helpers find values that way rather than by absolute position, so they survive a
layout they have never seen.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from autodraft.extract.page import TextRow
from autodraft.money import looks_like_amount, parse_amount

_LABEL_SPLIT_RE = re.compile(r"[:：]")

# A registration number always carries digits: two country letters then a digit,
# or a run of digits long enough not to be a quantity.
STRICT_VAT_ID_RE = re.compile(r"\b[A-Z]{2}[ ]?\d[0-9A-Z]{6,13}\b")
LABELLED_ID_RE = re.compile(r"[A-Z0-9][A-Z0-9\-./ ]{5,24}[A-Z0-9]")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def normalise(text: str) -> str:
    """Lowercase, accent-folded, whitespace-collapsed text for matching."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", normalise(text)) if token]


def find_labelled_value(
    rows: list[TextRow], labels: tuple[str, ...], max_lookahead: int = 2
) -> str | None:
    """The text a label points at: same row to its right, else the rows beneath."""
    ordered = sorted(labels, key=len, reverse=True)
    for index, row in enumerate(rows):
        row_text = row.text
        lowered = normalise(row_text)
        for label in ordered:
            if not _label_at_word_boundary(lowered, label):
                continue
            remainder = _text_after(row_text, label)
            remainder = _LABEL_SPLIT_RE.sub(" ", remainder).strip(" .-–—\t")
            if remainder:
                return remainder
            for offset in range(1, max_lookahead + 1):
                if index + offset < len(rows):
                    below = rows[index + offset].text.strip()
                    if below and not _is_label_only(below, ordered):
                        return below
    return None


def _label_at_word_boundary(lowered: str, label: str) -> bool:
    return _find_label(lowered, label) != -1


def _find_label(lowered: str, label: str) -> int:
    """Where a label starts, counting only whole-word occurrences."""
    start = 0
    while True:
        position = lowered.find(label, start)
        if position == -1:
            return -1
        before = lowered[position - 1] if position else " "
        after_index = position + len(label)
        after = lowered[after_index] if after_index < len(lowered) else " "
        if not before.isalnum() and not after.isalnum():
            return position
        start = position + 1


def find_labelled_amount(
    rows: list[TextRow], labels: tuple[str, ...], exclude: tuple[str, ...] = ()
) -> Decimal | None:
    """The rightmost amount on the row carrying one of these labels.

    A label printed above its amount (two-column totals blocks) is only followed
    downwards when no row anywhere states the amount beside the label, so a
    column heading never captures the first body row underneath it.
    """
    ordered = sorted(labels, key=len, reverse=True)
    same_row: tuple[int, Decimal] | None = None
    below_row: tuple[int, Decimal] | None = None
    for index, row in enumerate(rows):
        lowered = normalise(row.text)
        if any(word in lowered for word in exclude):
            continue
        label_hit = next((label for label in ordered if _label_at_word_boundary(lowered, label)), None)
        if not label_hit:
            continue
        specificity = len(label_hit)
        amount = _rightmost_amount(row, after=label_hit)
        if amount is not None:
            if same_row is None or specificity >= same_row[0]:
                same_row = (specificity, amount)
            continue
        if index + 1 < len(rows):
            beneath = _rightmost_amount(rows[index + 1])
            if beneath is not None and (below_row is None or specificity > below_row[0]):
                below_row = (specificity, beneath)
    chosen = same_row or below_row
    return chosen[1] if chosen else None


def _rightmost_amount(row: TextRow, after: str | None = None) -> Decimal | None:
    words = row.words
    if after:
        lowered = normalise(row.text)
        position = _find_label(lowered, after)
        if position != -1:
            cut = position + len(after)
            consumed, keep_from = 0, 0
            for index, word in enumerate(words):
                consumed += len(normalise(word.text)) + 1
                if consumed > cut:
                    keep_from = index
                    break
            words = words[keep_from:]
    for word in reversed(words):
        if not looks_like_amount(word.text):
            continue
        amount = parse_amount(word.text)
        if amount is not None:
            return amount
    return None


def _normalise_with_offsets(text: str) -> tuple[str, list[int]]:
    """`normalise(text)` alongside, per character, its offset in the original."""
    characters: list[str] = []
    offsets: list[int] = []
    previous_space = True
    for index, character in enumerate(text):
        decomposed = unicodedata.normalize("NFKD", character)
        folded = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
        if not folded:
            continue
        if folded.isspace():
            if previous_space:
                continue
            characters.append(" ")
            offsets.append(index)
            previous_space = True
            continue
        previous_space = False
        for character_out in folded:
            characters.append(character_out)
            offsets.append(index)
    while characters and characters[-1] == " ":
        characters.pop()
        offsets.pop()
    return "".join(characters), offsets


def _text_after(text: str, label: str) -> str:
    lowered, offsets = _normalise_with_offsets(text)
    position = _find_label(lowered, label)
    if position == -1:
        return ""
    end = position + len(label)
    if end >= len(offsets):
        return ""
    return text[offsets[end]:]


def _is_label_only(text: str, labels: list[str]) -> bool:
    lowered = normalise(text)
    return any(lowered == label for label in labels)


def find_vat_ids(text: str) -> list[str]:
    """VAT / tax registration numbers printed anywhere in the text."""
    found: list[str] = []
    for match in STRICT_VAT_ID_RE.finditer(text.upper()):
        value = match.group().replace(" ", "")
        if value not in found:
            found.append(value)
    for match in re.finditer(r"\bGHA-VAT-\d{4,10}\b", text.upper()):
        if match.group() not in found:
            found.append(match.group())
    return found


def find_ibans(text: str) -> list[str]:
    return [match.group().replace(" ", "") for match in IBAN_RE.finditer(text.upper())]


def contains_any(text: str, words: tuple[str, ...]) -> str | None:
    """The first of these words present in the text, if any."""
    lowered = normalise(text)
    for word in sorted(words, key=len, reverse=True):
        if word in lowered:
            return word
    return None
