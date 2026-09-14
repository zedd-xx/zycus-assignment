"""Locale-tolerant parsing of the scalars printed on supplier documents.

Everything the pipeline emits is dot-decimal text, so amounts, dates and
currencies are normalised here once, as close to the page as possible.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")

CURRENCY_SYMBOLS = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "R$": "BRL",
    "RM": "MYR",
    "₵": "GHS",
    "₦": "NGN",
    "KSh": "KES",
    "R": "ZAR",
    "zł": "PLN",
    "Kč": "CZK",
    "kr": "SEK",
    "₺": "TRY",
    "₴": "UAH",
    "₪": "ILS",
    "CHF": "CHF",
}

CURRENCY_CODES = {
    "EUR", "USD", "GBP", "JPY", "INR", "BRL", "MYR", "GHS", "NGN", "KES",
    "ZAR", "PLN", "CZK", "SEK", "NOK", "DKK", "TRY", "UAH", "ILS", "CHF",
    "AUD", "CAD", "NZD", "SGD", "HKD", "AED", "SAR", "RON", "HUF", "BGN",
    "HRK", "RSD", "MXN", "ARS", "CLP", "COP", "PEN", "EGP", "MAD", "TZS",
    "UGX", "RWF", "ZMW", "XOF", "XAF", "THB", "IDR", "PHP", "VND", "KRW",
    "CNY", "TWD", "PKR", "BDT", "LKR", "NPR",
}

_AMOUNT_RE = re.compile(r"[-+(]?\s*\d[\d\s.,'\u00a0\u202f]*\d|\d")

# A printed amount carries no letters: "1.254,00" and "(120.00)" are money,
# "GHA-VAT-887766" and "DE209177122" are registration numbers.
_MONEY_TOKEN_RE = re.compile(
    r"^[\s(\-+]*[€$£¥₹₵₦₺₴₪]?\s*\d[\d.,'\s\u00a0\u202f]*(?:[%]|[-)])?[\s.,;:]*$"
)


def looks_like_amount(text: str) -> bool:
    """Whether a token printed on a page is a number rather than an identifier."""
    return bool(text) and bool(_MONEY_TOKEN_RE.match(text.strip()))


def _strip_space(text: str) -> str:
    return re.sub(r"[\s\u00a0\u202f']", "", text)


def parse_amount(text: str | float | int | None) -> Decimal | None:
    """Parse one printed amount, whatever its thousands/decimal convention.

    ``1.234,56``, ``1 234.56``, ``1,234.56``, ``(120.00)`` and ``120,00-`` all
    parse; anything without digits returns ``None`` rather than zero, so the
    caller can tell "absent" from "zero".
    """
    if text is None:
        return None
    if isinstance(text, (int, float, Decimal)):
        return Decimal(str(text))
    raw = text.strip()
    if not raw:
        return None

    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative = True
        raw = raw[1:-1]
    if raw.endswith("-"):
        negative = True
        raw = raw[:-1]
    if raw.startswith("-"):
        negative = True
        raw = raw[1:]
    if raw.startswith("+"):
        raw = raw[1:]

    body = re.sub(r"[^\d.,\s\u00a0\u202f']", "", raw)
    body = _strip_space(body)
    if not body or not any(ch.isdigit() for ch in body):
        return None

    last_dot = body.rfind(".")
    last_comma = body.rfind(",")
    if last_dot == -1 and last_comma == -1:
        digits = body
    else:
        sep_index = max(last_dot, last_comma)
        sep = body[sep_index]
        tail = body[sep_index + 1:]
        # A separator followed by exactly three digits and no other separator
        # of the same kind is a thousands group, not a decimal point.
        if len(tail) == 3 and body.count(sep) >= 1 and (len(body) - sep_index - 1) == 3:
            other = "." if sep == "," else ","
            if other not in body and not _looks_like_decimal_tail(body, sep):
                digits = body.replace(".", "").replace(",", "")
            else:
                digits = body[:sep_index].replace(".", "").replace(",", "") + "." + tail
        else:
            digits = body[:sep_index].replace(".", "").replace(",", "") + "." + tail

    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


def _looks_like_decimal_tail(body: str, sep: str) -> bool:
    """True when a 3-digit tail is a decimal fraction (e.g. a unit price ``0.125``)."""
    head = body.split(sep)[0]
    return len(head) <= 1 and head in {"0", ""}


def money(value: Decimal | float | int | str | None) -> str:
    """Format a value as the dot-decimal, 2dp text the schema asks for."""
    if value is None or value == "":
        return ""
    dec = value if isinstance(value, Decimal) else parse_amount(str(value))
    if dec is None:
        return ""
    return str(dec.quantize(CENT, rounding=ROUND_HALF_UP))


def rate(value: Decimal | float | int | str | None) -> str:
    """Format a tax rate: no percent sign, no trailing zeros, dot-decimal."""
    if value is None or value == "":
        return ""
    dec = value if isinstance(value, Decimal) else parse_amount(str(value))
    if dec is None:
        return ""
    normalised = dec.normalize()
    text = format(normalised, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def quantity(value: Decimal | float | int | str | None) -> str:
    if value is None or value == "":
        return ""
    dec = value if isinstance(value, Decimal) else parse_amount(str(value))
    if dec is None:
        return ""
    text = format(dec.normalize(), "f")
    return text


def find_amounts(text: str) -> list[Decimal]:
    """Every amount printed in a fragment of text, in reading order."""
    found = []
    for match in _AMOUNT_RE.finditer(text):
        value = parse_amount(match.group())
        if value is not None:
            found.append(value)
    return found


def detect_currency(text: str) -> str:
    """The currency the page states, by ISO code first and symbol second."""
    upper = text.upper()
    for code in sorted(CURRENCY_CODES):
        if re.search(rf"(?<![A-Z]){code}(?![A-Z])", upper):
            return code
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text and len(symbol) > 1:
            return code
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    return ""


_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2})\b"), "dmy2"),
]

_MONTHS = {
    "jan": 1, "januar": 1, "january": 1, "janeiro": 1, "jaanuar": 1, "januari": 1,
    "feb": 2, "februar": 2, "february": 2, "fevereiro": 2, "veebruar": 2, "februari": 2,
    "mar": 3, "marz": 3, "märz": 3, "march": 3, "marco": 3, "março": 3, "marts": 3, "mac": 3,
    "apr": 4, "april": 4, "abril": 4, "aprill": 4,
    "mai": 5, "may": 5, "maio": 5, "mei": 5,
    "jun": 6, "juni": 6, "june": 6, "junho": 6, "juuni": 6,
    "jul": 7, "juli": 7, "july": 7, "julho": 7, "juuli": 7, "julai": 7,
    "aug": 8, "august": 8, "agosto": 8, "ogos": 8,
    "sep": 9, "sept": 9, "september": 9, "setembro": 9, "september ": 9,
    "okt": 10, "oct": 10, "october": 10, "oktober": 10, "outubro": 10,
    "nov": 11, "november": 11, "novembro": 11,
    "dez": 12, "dec": 12, "december": 12, "dezember": 12, "dezembro": 12, "disember": 12,
}

_TEXT_DATE_RE = re.compile(
    r"\b(\d{1,2})\.?\s+([A-Za-zÄÖÜäöüßÇçÃãÕõÁáÉéÍíÓóÚú]{3,12})\.?\s+(\d{4})\b"
)
_TEXT_DATE_RE_US = re.compile(
    r"\b([A-Za-zÄÖÜäöüßÇçÃãÕõÁáÉéÍíÓóÚú]{3,12})\.?\s+(\d{1,2}),?\s+(\d{4})\b"
)


def parse_date(text: str, dayfirst: bool = True) -> date | None:
    """First date in a fragment of text, as a ``date``."""
    if not text:
        return None
    for pattern, kind in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        a, b, c = match.groups()
        try:
            if kind == "ymd":
                return date(int(a), int(b), int(c))
            year = int(c) if kind == "dmy" else 2000 + int(c)
            first, second = int(a), int(b)
            if not dayfirst and second <= 12:
                first, second = second, first
            if first > 12 and second <= 12:
                return date(year, second, first)
            if second > 12 and first <= 12:
                return date(year, first, second)
            return date(year, second, first)
        except ValueError:
            continue

    match = _TEXT_DATE_RE.search(text)
    if match:
        day, month_name, year = match.groups()
        month = _MONTHS.get(month_name.lower().strip("."))
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                return None
    match = _TEXT_DATE_RE_US.search(text)
    if match:
        month_name, day, year = match.groups()
        month = _MONTHS.get(month_name.lower().strip("."))
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                return None
    return None


def iso(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()
