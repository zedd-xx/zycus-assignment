"""Optional vision-LLM extraction backend.

The pipeline runs fully offline on OCR by default. When an API key is present,
the model is used for one job only — reading the page into the schema's raw
components. Classification, master-data matching and reconciliation stay
deterministic, so enabling this changes extraction quality, not behaviour.

    export AUTODRAFT_LLM=openai     # or: anthropic
    export OPENAI_API_KEY=...       # or: ANTHROPIC_API_KEY=...
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT_SECONDS = int(os.environ.get("AUTODRAFT_LLM_TIMEOUT", "180"))

PROMPT = """You read supplier documents into a strict JSON record. Transcribe only
what is printed. Never compute, balance or invent a value: if the page does not
print it, leave it empty.

Return JSON of this exact shape:
{"documents": [{
  "doc_kind": "INVOICE|CREDIT_NOTE|PROFORMA|STATEMENT|REMITTANCE|RECEIPT|ORDER|DELIVERY_NOTE|REMINDER|OTHER",
  "pages": [1],
  "invoice_number": "", "invoice_date": "YYYY-MM-DD", "due_date": "YYYY-MM-DD",
  "currency": "ISO code",
  "supplier": {"name": "", "address": "", "vat_id": "", "iban": ""},
  "buyer": {"name": "", "address": "", "vat_id": ""},
  "payment_terms_text": "", "po_number": "",
  "prices_include_tax": true|false|null,
  "printed_gross_total": "", "printed_subtotal": "", "printed_total_tax": "",
  "printed_prepayment": "", "printed_rounding": "",
  "header_discount": "", "freight": "", "insurance": "", "other_charges": "", "excise": "",
  "header_taxes": [{"name": "", "rate": "", "amount": ""}],
  "line_items": [{"description": "", "uom": "", "quantity": "", "unit_price": "",
                  "total": "", "discount": "", "discount_percentage": "",
                  "tax_rate": "", "tax_amount": "", "tax_name": ""}],
  "notes": ["any printed statement about tax treatment, payment already made, or that this is not a payable"]
}]}

Rules:
- One entry per distinct document in the file. A single PDF may hold several.
- Numbers dot-decimal, no thousands separators, no currency symbols.
- Keep amounts exactly as printed, including whether unit prices include tax
  (set prices_include_tax from the page's own wording, else null).
- Keep a tax where the page puts it: per-line taxes on the line, a single
  stated tax at the header.
- Do not fill a field to make a total foot."""


def backend() -> str | None:
    """The configured backend name, or ``None`` when running OCR-only."""
    name = (os.environ.get("AUTODRAFT_LLM") or "").strip().lower()
    if name in {"", "none", "off", "ocr"}:
        return None
    if name in {"openai", "anthropic"}:
        return name if _api_key(name) else None
    log.warning("unknown AUTODRAFT_LLM backend %r; running OCR-only", name)
    return None


def _api_key(name: str) -> str | None:
    return os.environ.get("OPENAI_API_KEY" if name == "openai" else "ANTHROPIC_API_KEY")


def _model(name: str) -> str:
    default = "gpt-4o-mini" if name == "openai" else "claude-3-5-sonnet-latest"
    return os.environ.get("AUTODRAFT_LLM_MODEL", default)


def read_document(pdf_path: str | Path, page_numbers: list[int], ocr_text: str) -> dict | None:
    """Ask the model to transcribe the given pages; ``None`` if unavailable."""
    name = backend()
    if not name:
        return None
    images = _render_pages(pdf_path, page_numbers)
    if not images:
        return None
    try:
        raw = _call_openai(images, ocr_text) if name == "openai" else _call_anthropic(images, ocr_text)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning("LLM backend unreachable (%s); falling back to OCR parsing", error)
        return None
    return _parse_json(raw)


def _render_pages(pdf_path: str | Path, page_numbers: list[int]) -> list[str]:
    try:
        from pdf2image import convert_from_path
    except ImportError:  # pragma: no cover - dependency is declared
        return []
    import io

    encoded: list[str] = []
    for number in page_numbers:
        images = convert_from_path(str(pdf_path), dpi=200, first_page=number, last_page=number)
        for image in images:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            encoded.append(base64.b64encode(buffer.getvalue()).decode())
    return encoded


def _post(url: str, headers: dict[str, str], payload: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode())


def _call_openai(images: list[str], ocr_text: str) -> str:
    content: list[dict] = [{"type": "text", "text": f"{PROMPT}\n\nOCR of the same pages:\n{ocr_text[:8000]}"}]
    for image in images:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}})
    body = _post(
        OPENAI_URL,
        {"Authorization": f"Bearer {_api_key('openai')}"},
        {
            "model": _model("openai"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content}],
        },
    )
    return body["choices"][0]["message"]["content"]


def _call_anthropic(images: list[str], ocr_text: str) -> str:
    content: list[dict] = []
    for image in images:
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": image},
            }
        )
    content.append({"type": "text", "text": f"{PROMPT}\n\nOCR of the same pages:\n{ocr_text[:8000]}"})
    body = _post(
        ANTHROPIC_URL,
        {"x-api-key": _api_key("anthropic") or "", "anthropic-version": ANTHROPIC_VERSION},
        {
            "model": _model("anthropic"),
            "max_tokens": 8000,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}],
        },
    )
    return "".join(block.get("text", "") for block in body.get("content", []))


def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        log.warning("LLM returned no JSON object")
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        log.warning("LLM returned malformed JSON")
        return None
