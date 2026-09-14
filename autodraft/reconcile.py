"""Deciding what to book, once the page has been transcribed.

A document states two things independently: the parts (lines, rates, charges)
and the total it says is owed. When the ERP's recompute of the parts already
reaches that total, the transcription is the answer and nothing may touch it.

When it does not, the gap means the page is doing something the naive reading
missed — prices quoted with tax in them, a deposit already paid, a rounding
line, a tax restated in two places. Each of those is modelled once, as a
*reading hypothesis* that is allowed to fire only when the page itself prints
the fact that licenses it, and is accepted only when it closes the gap exactly.
A hypothesis that merely shrinks the gap is rejected: near-misses are how a fix
corrupts a document that was already right.
"""
from __future__ import annotations

import itertools
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal

from autodraft.money import money, parse_amount
from autodraft.payables import booked_gross, stated_gross
from autodraft.reading import Reading

MAX_COMBINED_HYPOTHESES = 3
CENT = Decimal("0.01")


@dataclass
class Hypothesis:
    """A licensed reinterpretation of the page."""

    name: str
    evidence: str
    cost: int
    apply: Callable[[dict], None]


@dataclass
class Reconciliation:
    payable: dict
    status: str
    stated: Decimal | None
    booked: Decimal
    applied: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def books(self) -> bool:
        return self.status in {"reconciled_as_read", "reconciled_with_hypothesis"}

    @property
    def difference(self) -> Decimal | None:
        return None if self.stated is None else (self.booked - self.stated)


def reconcile(reading: Reading, payable: dict) -> Reconciliation:
    """Pick the reading of this document that the ERP recomputes to its own total."""
    target = stated_gross(reading)
    baseline = booked_gross(payable)

    if target is None:
        return Reconciliation(
            payable,
            "no_stated_total",
            None,
            baseline,
            notes=["Document states no total; emitted exactly as transcribed."] + reading.notes,
        )

    if baseline == target:
        return Reconciliation(
            payable, "reconciled_as_read", target, baseline, notes=list(reading.notes)
        )

    hypotheses = licensed_hypotheses(reading, payable)
    best: tuple[int, int, dict, list[Hypothesis]] | None = None
    for size in range(1, min(MAX_COMBINED_HYPOTHESES, len(hypotheses)) + 1):
        for combination in itertools.combinations(hypotheses, size):
            candidate = deepcopy(payable)
            for hypothesis in combination:
                hypothesis.apply(candidate)
            if booked_gross(candidate) != target:
                continue
            cost = sum(hypothesis.cost for hypothesis in combination)
            key = (size, cost)
            if best is None or key < (best[0], best[1]):
                best = (size, cost, candidate, list(combination))
        if best is not None:
            break  # the fewest hypotheses that explain the page win

    if best is None:
        return Reconciliation(
            payable,
            "unreconciled",
            target,
            baseline,
            notes=[
                "No licensed reading of this page reproduces its stated total; "
                "emitted as transcribed rather than adjusted to fit."
            ]
            + reading.notes,
        )

    _, _, candidate, applied = best
    return Reconciliation(
        candidate,
        "reconciled_with_hypothesis",
        target,
        booked_gross(candidate),
        applied=[hypothesis.name for hypothesis in applied],
        evidence=[hypothesis.evidence for hypothesis in applied],
        notes=list(reading.notes),
    )


# ── hypotheses ─────────────────────────────────────────────────────────────
def licensed_hypotheses(reading: Reading, payable: dict) -> list[Hypothesis]:
    """Only the reinterpretations this page prints the evidence for."""
    hypotheses: list[Hypothesis] = []
    for builder in (
        _tax_inclusive_prices,
        _header_tax_restates_line_tax,
        _line_tax_restates_header_tax,
        _prepayment_already_paid,
        _rounding_difference,
        _header_discount_already_in_lines,
        _tax_line_duplicates_tax,
        _withholding_reduces_total,
    ):
        hypothesis = builder(reading, payable)
        if hypothesis is not None:
            hypotheses.append(hypothesis)
    return sorted(hypotheses, key=lambda item: item.cost)


def _rates_in_play(reading: Reading, payable: dict) -> list[Decimal]:
    rates = [rate for rate in reading.line_tax_rates if rate and rate > 0]
    if rates:
        return rates
    header = [parse_amount(tax.get("tax_rate")) for tax in payable.get("taxes", [])]
    return [rate for rate in header if rate and rate > 0]


def _tax_inclusive_prices(reading: Reading, payable: dict) -> Hypothesis | None:
    """Unit prices quoted with tax in them; the ERP adds tax on top of net."""
    rates = _rates_in_play(reading, payable)
    if not rates:
        return None

    stated = stated_gross(reading)
    printed_sum = _line_extension_sum(payable)
    says_so = reading.prices_include_tax is True
    lines_already_gross = stated is not None and printed_sum is not None and printed_sum == stated
    if not (says_so or lines_already_gross):
        return None

    evidence = (
        "page states prices include tax"
        if says_so
        else "line extensions already sum to the stated gross while a tax is charged"
    )

    def apply(candidate: dict) -> None:
        for item in candidate["line_items"]:
            rate = _effective_rate(item, candidate)
            price = parse_amount(item.get("unit_price"))
            if rate is None or rate <= 0 or price is None:
                continue
            net = price / (Decimal(1) + rate / Decimal(100))
            item["unit_price"] = str(net.quantize(Decimal("0.0001")))
            extension = parse_amount(item.get("total"))
            if extension is not None:
                net_extension = extension / (Decimal(1) + rate / Decimal(100))
                item["total"] = str(net_extension.quantize(Decimal("0.01")))

    return Hypothesis("tax_inclusive_prices", evidence, cost=2, apply=apply)


def _effective_rate(item: dict, payable: dict) -> Decimal | None:
    rate = parse_amount(item.get("tax_rate"))
    if rate:
        return rate
    for tax in item.get("taxes", []):
        value = parse_amount(tax.get("tax_rate"))
        if value:
            return value
    header_rates = [parse_amount(tax.get("tax_rate")) for tax in payable.get("taxes", [])]
    header_rates = [value for value in header_rates if value]
    return header_rates[0] if len(header_rates) == 1 else None


def _line_extension_sum(payable: dict) -> Decimal | None:
    totals = [parse_amount(item.get("total")) for item in payable.get("line_items", [])]
    totals = [value for value in totals if value is not None]
    return sum(totals) if totals else None


def _header_tax_restates_line_tax(reading: Reading, payable: dict) -> Hypothesis | None:
    """The totals block repeats a tax the lines already carry."""
    if not payable.get("taxes") or not reading.has_line_taxes:
        return None

    def apply(candidate: dict) -> None:
        candidate["taxes"] = []

    return Hypothesis(
        "header_tax_restates_line_tax",
        "lines carry their own tax and the totals block restates the same tax",
        cost=1,
        apply=apply,
    )


def _line_tax_restates_header_tax(reading: Reading, payable: dict) -> Hypothesis | None:
    """One tax stated once at the header, echoed against each line by the layout."""
    if not payable.get("taxes") or not reading.has_line_taxes:
        return None
    rates = {rate for rate in reading.line_tax_rates if rate is not None}
    if len(rates) != 1:
        return None

    def apply(candidate: dict) -> None:
        for item in candidate["line_items"]:
            item["taxes"] = []
            item["tax_rate"] = ""
            item["tax_amount"] = ""

    return Hypothesis(
        "line_tax_restates_header_tax",
        "a single rate repeated on every line is the header tax the totals block states",
        cost=2,
        apply=apply,
    )


def _prepayment_already_paid(reading: Reading, payable: dict) -> Hypothesis | None:
    """A deposit or payment already made reduces what is still owed, after tax."""
    prepayment = reading.printed_prepayment
    if prepayment is None or prepayment == 0:
        return None
    amount = abs(prepayment)

    def apply(candidate: dict) -> None:
        existing = parse_amount(candidate.get("extra_charges")) or Decimal(0)
        candidate["extra_charges"] = money(existing - amount)

    return Hypothesis(
        "prepayment_already_paid",
        f"page prints an amount already paid ({money(amount)}) deducted from what is owed",
        cost=2,
        apply=apply,
    )


def _rounding_difference(reading: Reading, payable: dict) -> Hypothesis | None:
    rounding = reading.printed_rounding
    if rounding is None or rounding == 0:
        return None

    def apply(candidate: dict) -> None:
        existing = parse_amount(candidate.get("extra_charges")) or Decimal(0)
        candidate["extra_charges"] = money(existing + rounding)

    return Hypothesis(
        "rounding_difference",
        f"page prints a rounding adjustment of {money(rounding)}",
        cost=1,
        apply=apply,
    )


def _header_discount_already_in_lines(reading: Reading, payable: dict) -> Hypothesis | None:
    """A discount shown in the totals block that the line extensions already reflect."""
    if not payable.get("discount_amount"):
        return None

    def apply(candidate: dict) -> None:
        candidate["discount_amount"] = ""

    return Hypothesis(
        "header_discount_already_in_lines",
        "the discount printed in the totals block is already reflected in the line extensions",
        cost=2,
        apply=apply,
    )


def _tax_line_duplicates_tax(reading: Reading, payable: dict) -> Hypothesis | None:
    """A tax printed as if it were a line item, alongside the tax itself."""
    tax_lines = [item for item in payable.get("line_items", []) if item.get("item_type") == "TAX"]
    if not tax_lines:
        return None
    if not payable.get("taxes") and not reading.has_line_taxes:
        return None

    def apply(candidate: dict) -> None:
        candidate["line_items"] = [
            item for item in candidate["line_items"] if item.get("item_type") != "TAX"
        ]

    return Hypothesis(
        "tax_line_duplicates_tax",
        "a tax amount printed in the item table is the same tax the document charges",
        cost=2,
        apply=apply,
    )


def _withholding_reduces_total(reading: Reading, payable: dict) -> Hypothesis | None:
    """A tax the buyer withholds: printed positive, owed as a deduction."""
    candidates = [
        index
        for index, tax in enumerate(payable.get("taxes", []))
        if (parse_amount(tax.get("tax_amount")) or Decimal(0)) > 0
    ]
    if not candidates:
        return None
    stated = stated_gross(reading)
    if stated is None or reading.printed_subtotal is None:
        return None
    if stated >= abs(reading.printed_subtotal):
        return None  # nothing on the page suggests the total was reduced

    def apply(candidate: dict) -> None:
        for index in candidates:
            amount = parse_amount(candidate["taxes"][index].get("tax_amount"))
            if amount is not None:
                candidate["taxes"][index]["tax_amount"] = money(-abs(amount))

    return Hypothesis(
        "withholding_reduces_total",
        "the stated total is below the net, so the tax printed is withheld rather than charged",
        cost=3,
        apply=apply,
    )
