"""Resolving printed values to master-data codes, at master-data scale.

The samples shipped here are tiny; real masters are not. So nothing in this
module scans a master per lookup. Each master is loaded once into exact-match
indexes (VAT id, IBAN, PO number, alias) plus an inverted token index used to
generate a bounded candidate set, and only those few candidates are scored.

The scoring is deliberately conservative: a code is emitted only when the
evidence is strong. "No match" is a legitimate answer and always preferred to a
plausible-looking guess.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from autodraft.fields import normalise, tokens

log = logging.getLogger(__name__)

MAX_CANDIDATES = 25
NAME_ACCEPT_SCORE = 88.0
NAME_WITH_CORROBORATION_SCORE = 76.0

_COMPANY_NOISE = {
    "gmbh", "ag", "kg", "mbh", "ltd", "limited", "plc", "llc", "inc", "co",
    "corp", "bv", "nv", "oy", "ab", "as", "ou", "osauhing", "sa", "lda",
    "unipessoal", "sdn", "bhd", "srl", "spa", "sarl", "sas", "pte", "pty",
    "the", "and", "of",
}


def _ratio(left: str, right: str) -> float:
    try:
        from rapidfuzz import fuzz

        return float(fuzz.token_set_ratio(left, right))
    except ImportError:  # pragma: no cover - rapidfuzz is declared
        from difflib import SequenceMatcher

        return SequenceMatcher(None, left, right).ratio() * 100.0


@dataclass
class Match:
    code: str
    score: float
    reason: str

    @property
    def matched(self) -> bool:
        return bool(self.code)


NO_MATCH = Match("", 0.0, "no match in master data")


class _TokenIndex:
    """Inverted index over name tokens, for bounded candidate generation."""

    def __init__(self) -> None:
        self._postings: dict[str, set[int]] = defaultdict(set)
        self._document_count = 0

    def add(self, record_id: int, text: str) -> None:
        self._document_count += 1
        for token in self._useful_tokens(text):
            self._postings[token].add(record_id)

    def candidates(self, text: str, limit: int = MAX_CANDIDATES) -> list[int]:
        scores: dict[int, float] = defaultdict(float)
        for token in self._useful_tokens(text):
            postings = self._postings.get(token)
            if not postings or len(postings) > max(50, self._document_count // 4):
                continue  # a token this common carries no discriminating power
            weight = 1.0 / len(postings)
            for record_id in postings:
                scores[record_id] += weight
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return [record_id for record_id, _ in ranked[:limit]]

    @staticmethod
    def _useful_tokens(text: str) -> list[str]:
        return [token for token in tokens(text) if token not in _COMPANY_NOISE and len(token) > 1]


def _normalise_id(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


class SupplierMaster:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self._by_vat: dict[str, int] = {}
        self._by_iban: dict[str, int] = {}
        self._by_email: dict[str, int] = {}
        self._by_name: dict[str, int] = {}
        self._index = _TokenIndex()
        for record_id, record in enumerate(records):
            if record.get("vat_id"):
                self._by_vat[_normalise_id(record["vat_id"])] = record_id
            if record.get("bank_iban"):
                self._by_iban[_normalise_id(record["bank_iban"])] = record_id
            if record.get("email"):
                self._by_email[record["email"].strip().lower()] = record_id
            self._by_name[normalise(record.get("name", ""))] = record_id
            self._index.add(record_id, f"{record.get('name', '')} {record.get('address', '')}")

    def match(
        self,
        name: str,
        vat_id: str = "",
        iban: str = "",
        email: str = "",
        address: str = "",
    ) -> Match:
        vat_key = _normalise_id(vat_id)
        if vat_key and vat_key in self._by_vat:
            record = self.records[self._by_vat[vat_key]]
            return Match(record["supplier_id"], 100.0, f"VAT id {record['vat_id']}")

        iban_key = _normalise_id(iban)
        if iban_key and iban_key in self._by_iban:
            record = self.records[self._by_iban[iban_key]]
            return Match(record["supplier_id"], 99.0, "bank IBAN")

        email_key = email.strip().lower()
        if email_key and email_key in self._by_email:
            record = self.records[self._by_email[email_key]]
            return Match(record["supplier_id"], 97.0, "billing email")

        normalised_name = normalise(name)
        if normalised_name and normalised_name in self._by_name:
            record = self.records[self._by_name[normalised_name]]
            return Match(record["supplier_id"], 96.0, "exact name")

        if not normalised_name:
            return NO_MATCH

        best = NO_MATCH
        for record_id in self._index.candidates(f"{name} {address}"):
            record = self.records[record_id]
            name_score = _ratio(normalised_name, normalise(record.get("name", "")))
            address_score = (
                _ratio(normalise(address), normalise(record.get("address", "")))
                if address and record.get("address")
                else 0.0
            )
            threshold = (
                NAME_WITH_CORROBORATION_SCORE if address_score >= 80 else NAME_ACCEPT_SCORE
            )
            if name_score >= threshold and name_score > best.score:
                reason = "name match" + (" corroborated by address" if address_score >= 80 else "")
                best = Match(record["supplier_id"], name_score, reason)
        return best


class TaxMaster:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self._by_country_rate: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self._by_rate: dict[str, list[dict]] = defaultdict(list)
        for record in records:
            rate_key = _rate_key(record.get("rate"))
            country = (record.get("country") or "").upper()
            self._by_country_rate[(country, rate_key)].append(record)
            self._by_rate[rate_key].append(record)

    def match(self, rate: Decimal | None, country: str = "", tax_type: str = "", name: str = "") -> Match:
        if rate is None:
            return NO_MATCH
        rate_key = _rate_key(rate)
        country = (country or "").upper()

        candidates = self._by_country_rate.get((country, rate_key), []) if country else []
        if not candidates and not country:
            candidates = self._by_rate.get(rate_key, [])
        if not candidates:
            return NO_MATCH

        if tax_type:
            typed = [record for record in candidates if (record.get("tax_type") or "").upper() == tax_type.upper()]
            candidates = typed or candidates
        if len(candidates) > 1 and name:
            candidates = sorted(
                candidates, key=lambda record: _ratio(normalise(name), normalise(record.get("name", ""))), reverse=True
            )
        if len(candidates) > 1 and not country:
            # Several countries levy the same rate; without a country that is a guess.
            return NO_MATCH
        record = candidates[0]
        return Match(record["code"], 95.0, f"{record.get('country', '')} rate {record.get('rate')}")


def _rate_key(rate: Decimal | float | int | str | None) -> str:
    if rate is None or rate == "":
        return ""
    value = Decimal(str(rate))
    return str(value.quantize(Decimal("0.01")))


class PaymentTermMaster:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self._by_alias: dict[str, dict] = {}
        self._by_days: dict[int, dict] = {}
        for record in records:
            for alias in record.get("text_aliases", []):
                self._by_alias[normalise(alias)] = record
            self._by_alias.setdefault(normalise(record["payment_term_id"].replace("_", " ")), record)
            days = record.get("days")
            if isinstance(days, int):
                self._by_days.setdefault(days, record)

    def match(self, text: str, days: int | None = None) -> Match:
        normalised = normalise(text)
        if normalised:
            for alias, record in self._by_alias.items():
                if alias and alias in normalised:
                    return Match(record["payment_term_id"], 96.0, f"term text '{alias}'")
            match = re.search(r"\b(\d{1,3})\s*(?:days|tage|paeva|päeva|dias|hari)\b", normalised)
            if match:
                record = self._by_days.get(int(match.group(1)))
                if record:
                    return Match(record["payment_term_id"], 92.0, f"{match.group(1)} days stated")
        if days is not None and days in self._by_days:
            record = self._by_days[days]
            return Match(record["payment_term_id"], 85.0, f"{days} days between invoice and due date")
        return NO_MATCH


class PurchaseOrderMaster:
    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self._by_number = {_normalise_id(record.get("po_number")): record for record in records}

    def match(self, po_number: str) -> Match:
        key = _normalise_id(po_number)
        if not key:
            return NO_MATCH
        record = self._by_number.get(key)
        if record:
            return Match(record["po_id"], 100.0, "PO number in master")
        return Match("", 0.0, "PO printed but not in the PO master (non-ERP reference)")


@dataclass
class BuyerMatch:
    company_code: str = ""
    business_unit_code: str = ""
    location_code: str = ""
    score: float = 0.0
    reason: str = "no match in master data"

    @property
    def matched(self) -> bool:
        return bool(self.company_code or self.business_unit_code or self.location_code)


class OrgMaster:
    """chart_of_books.json flattened to (company, business unit, location) rows."""

    def __init__(self, companies: list[dict]) -> None:
        self.rows: list[dict] = []
        self._index = _TokenIndex()
        self._by_vat: dict[str, int] = {}
        for company in companies:
            for unit in company.get("business_units", []):
                for location in unit.get("locations", []):
                    row = {
                        "company_code": company["company_code"],
                        "company_name": company.get("company_name", ""),
                        "business_unit_code": unit["business_unit_code"],
                        "business_unit_name": unit.get("business_unit_name", ""),
                        "location_code": location["location_code"],
                        "location_name": location.get("location_name", ""),
                        "invoice_to_address": location.get("invoice_to_address", ""),
                        "vat_id": unit.get("vat_id") or company.get("vat_id") or "",
                    }
                    row_id = len(self.rows)
                    self.rows.append(row)
                    self._index.add(
                        row_id,
                        f"{row['company_name']} {row['business_unit_name']} "
                        f"{row['location_name']} {row['invoice_to_address']}",
                    )
                    if row["vat_id"]:
                        self._by_vat.setdefault(_normalise_id(row["vat_id"]), row_id)

    def match(self, name: str, address: str = "", vat_id: str = "", tenant_hint: str = "") -> BuyerMatch:
        vat_key = _normalise_id(vat_id)
        if vat_key and vat_key in self._by_vat:
            return self._as_match(self.rows[self._by_vat[vat_key]], 100.0, "buyer VAT id")

        query = " ".join(part for part in (tenant_hint, name, address) if part)
        if not query.strip():
            return BuyerMatch()

        best: tuple[float, dict, str] | None = None
        for row_id in self._index.candidates(query):
            row = self.rows[row_id]
            unit_score = _ratio(normalise(name), normalise(row["business_unit_name"])) if name else 0.0
            address_score = (
                _ratio(normalise(address), normalise(row["invoice_to_address"]))
                if address and row["invoice_to_address"]
                else 0.0
            )
            company_score = _ratio(normalise(name), normalise(row["company_name"])) if name else 0.0
            score = max(unit_score, address_score, company_score * 0.9)
            reason = (
                "business unit name" if score == unit_score
                else "invoice-to address" if score == address_score
                else "company name"
            )
            if score >= 80 and (best is None or score > best[0]):
                best = (score, row, reason)
        if best is None:
            return BuyerMatch()
        score, row, reason = best
        return self._as_match(row, score, reason)

    @staticmethod
    def _as_match(row: dict, score: float, reason: str) -> BuyerMatch:
        return BuyerMatch(row["company_code"], row["business_unit_code"], row["location_code"], score, reason)


class MasterData:
    """All masters, loaded once and reused across every document in a run."""

    def __init__(self, directory: str | Path) -> None:
        directory = Path(directory)
        self.suppliers = SupplierMaster(_load(directory / "suppliers.json", "suppliers"))
        self.taxes = TaxMaster(_load(directory / "tax_master.json", "taxes"))
        self.payment_terms = PaymentTermMaster(_load(directory / "payment_terms.json", "payment_terms"))
        self.purchase_orders = PurchaseOrderMaster(_load(directory / "po_master.json", "purchase_orders"))
        self.org = OrgMaster(_load(directory / "chart_of_books.json", "companies"))


def _load(path: Path, key: str) -> list[dict]:
    if not path.exists():
        log.warning("master file %s is missing; matches against it will be empty", path)
        return []
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    records = payload.get(key, []) if isinstance(payload, dict) else payload
    return [record for record in records if isinstance(record, dict)]
