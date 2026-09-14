"""PDF -> pages of positioned words.

A page reaches the rest of the pipeline in one shape regardless of how it was
produced: a born-digital text layer when the PDF has one, OCR when it does not.
Word boxes are kept because the table reader needs columns, and columns only
exist in geometry.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

MIN_TEXT_LAYER_CHARS = 60
OCR_DPI = int(os.environ.get("AUTODRAFT_OCR_DPI", "300"))
CACHE_VERSION = 3

# Tesseract language packs worth trying, keyed by cues that show up in the text.
LANGUAGE_CUES: dict[str, tuple[str, ...]] = {
    "deu": ("rechnung", "mwst", "betrag", "lieferung", "gmbh", "zahlung", "netto"),
    "est": ("arve", "käibemaks", "kaibemaks", "summa", "kokku", "kuupäev", "osaühing"),
    "por": ("fatura", "factura", "iva", "total a pagar", "contribuinte", "valor"),
    "msa": ("invois", "jumlah", "cukai", "bayaran", "sdn bhd", "harga"),
    "fra": ("facture", "tva", "montant", "règlement", "livraison"),
    "spa": ("factura", "iva", "importe", "total a pagar", "cliente"),
    "ita": ("fattura", "iva", "importo", "totale"),
    "nld": ("factuur", "btw", "bedrag", "totaal"),
}


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def mid_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class TextRow:
    """Words sharing a baseline, i.e. one printed row."""

    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def top(self) -> float:
        return min(word.top for word in self.words)

    @property
    def bottom(self) -> float:
        return max(word.bottom for word in self.words)


@dataclass
class Page:
    number: int
    width: float
    height: float
    words: list[Word] = field(default_factory=list)
    source: str = "text-layer"

    @property
    def rows(self) -> list[TextRow]:
        if not hasattr(self, "_rows"):
            self._rows = _group_rows(self.words)
        return self._rows

    @property
    def text(self) -> str:
        return "\n".join(row.text for row in self.rows)

    @property
    def lowered(self) -> str:
        return self.text.lower()


def _group_rows(words: list[Word], tolerance: float = 0.6) -> list[TextRow]:
    """Cluster words into printed rows by vertical overlap."""
    if not words:
        return []
    heights = sorted(word.bottom - word.top for word in words)
    median_height = heights[len(heights) // 2] or 10.0
    threshold = max(median_height * tolerance, 2.0)

    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.mid_y, w.x0)):
        if rows and abs(word.mid_y - rows[-1][-1].mid_y) <= threshold:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [TextRow(sorted(row, key=lambda w: w.x0)) for row in rows]


def read_pdf(path: str | Path, cache_dir: str | Path | None = None) -> list[Page]:
    """Every page of a PDF as positioned words, OCR'ing the pages that need it."""
    path = Path(path)
    cache_path = _cache_path(path, cache_dir) if cache_dir else None
    if cache_path and cache_path.exists():
        try:
            return _pages_from_json(json.loads(cache_path.read_text()))
        except (json.JSONDecodeError, KeyError):
            log.warning("ignoring unreadable extraction cache %s", cache_path)

    pages = _read_text_layer(path)
    scanned = [page for page in pages if len(page.text.strip()) < MIN_TEXT_LAYER_CHARS]
    if scanned:
        ocr_pages = _ocr_pages(path, [page.number for page in scanned])
        by_number = {page.number: page for page in ocr_pages}
        pages = [by_number.get(page.number, page) for page in pages]

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(_pages_to_json(pages)))
    return pages


def _read_text_layer(path: Path) -> list[Page]:
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - dependency is declared
        log.warning("pdfplumber missing; relying on OCR for %s", path.name)
        return _page_stubs(path)

    pages: list[Page] = []
    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            words = [
                Word(word["text"], word["x0"], word["x1"], word["top"], word["bottom"])
                for word in page.extract_words(use_text_flow=False, keep_blank_chars=False)
            ]
            pages.append(Page(index, page.width, page.height, words))
    return pages


def _page_stubs(path: Path) -> list[Page]:
    count = _page_count(path)
    return [Page(number, 612.0, 792.0, []) for number in range(1, count + 1)]


def _page_count(path: Path) -> int:
    if shutil.which("pdfinfo"):
        result = subprocess.run(
            ["pdfinfo", str(path)], capture_output=True, text=True, check=False
        )
        match = re.search(r"Pages:\s+(\d+)", result.stdout)
        if match:
            return int(match.group(1))
    return 1


def _ocr_pages(path: Path, numbers: list[int]) -> list[Page]:
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:  # pragma: no cover - dependency is declared
        log.error("OCR requested but pytesseract/pdf2image are missing")
        return []

    pages: list[Page] = []
    for number in numbers:
        images = convert_from_path(str(path), dpi=OCR_DPI, first_page=number, last_page=number)
        if not images:
            continue
        image = images[0]
        words, language = _ocr_image(image, pytesseract)
        page = Page(number, float(image.width), float(image.height), words, source=f"ocr:{language}")
        pages.append(page)
    return pages


def _ocr_image(image, pytesseract) -> tuple[list[Word], str]:
    """OCR a page once in English, then again in the language the page looks like."""
    words = _tesseract_words(image, pytesseract, "eng")
    language = _guess_language(" ".join(word.text for word in words).lower())
    if language == "eng":
        return words, "eng"

    combined = f"{language}+eng"
    if not _language_available(pytesseract, language):
        log.info("tesseract pack %s unavailable; keeping english OCR", language)
        return words, "eng"
    better = _tesseract_words(image, pytesseract, combined)
    return (better, combined) if len(better) >= len(words) * 0.8 else (words, "eng")


def _tesseract_words(image, pytesseract, language: str) -> list[Word]:
    data = pytesseract.image_to_data(
        image, lang=language, output_type=pytesseract.Output.DICT, config="--psm 6"
    )
    words: list[Word] = []
    for index, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence < 30:
            continue
        left, top = float(data["left"][index]), float(data["top"][index])
        width, height = float(data["width"][index]), float(data["height"][index])
        words.append(Word(text, left, left + width, top, top + height))
    return words


def _guess_language(text: str) -> str:
    best, best_hits = "eng", 0
    for language, cues in LANGUAGE_CUES.items():
        hits = sum(1 for cue in cues if cue in text)
        if hits > best_hits:
            best, best_hits = language, hits
    return best if best_hits >= 2 else "eng"


def _language_available(pytesseract, language: str) -> bool:
    try:
        return language in set(pytesseract.get_languages(config=""))
    except Exception:  # pragma: no cover - depends on local tesseract build
        return False


def _cache_path(path: Path, cache_dir: str | Path) -> Path:
    stat = path.stat()
    digest = hashlib.sha1(
        f"{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}|{OCR_DPI}|{CACHE_VERSION}".encode()
    ).hexdigest()
    return Path(cache_dir) / f"{path.stem}-{digest}.json"


def _pages_to_json(pages: list[Page]) -> dict:
    return {
        "version": CACHE_VERSION,
        "pages": [
            {
                "number": page.number,
                "width": page.width,
                "height": page.height,
                "source": page.source,
                "words": [[w.text, w.x0, w.x1, w.top, w.bottom] for w in page.words],
            }
            for page in pages
        ],
    }


def _pages_from_json(payload: dict) -> list[Page]:
    if payload.get("version") != CACHE_VERSION:
        raise KeyError("stale cache")
    return [
        Page(
            page["number"],
            page["width"],
            page["height"],
            [Word(text, x0, x1, top, bottom) for text, x0, x1, top, bottom in page["words"]],
            page.get("source", "text-layer"),
        )
        for page in payload["pages"]
    ]
