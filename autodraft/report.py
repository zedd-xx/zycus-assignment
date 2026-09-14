"""What happened on a run, in the terms the brief is graded in.

The oracle answers one question — the gross it will book — so the report says,
per payable, whether that equals the total the document states, which reading
got it there, and which master-data codes were resolved rather than guessed.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from autodraft.pipeline import FileResult


def build_report(results: list[FileResult]) -> dict:
    files: list[dict] = []
    statuses: Counter[str] = Counter()
    hypotheses: Counter[str] = Counter()
    declines: Counter[str] = Counter()
    codes = Counter({"supplier_id": 0, "buyer": 0, "payment_term_id": 0, "po_id": 0, "tax_type_code": 0})
    payable_count = 0
    booking_count = 0

    for result in results:
        entries: list[dict] = []
        for index, document in enumerate(result.documents):
            reconciliation = document.reconciliation
            payable = reconciliation.payable
            statuses[reconciliation.status] += 1
            hypotheses.update(reconciliation.applied)
            payable_count += 1
            booking_count += int(reconciliation.books)
            for field_name in ("supplier_id", "buyer", "payment_term_id", "po_id"):
                if document.master_evidence.get(field_name):
                    codes[field_name] += 1
            codes["tax_type_code"] += sum(
                1 for tax in payable.get("taxes", []) if tax.get("tax_type_code")
            )
            entries.append(
                {
                    "index": index,
                    "invoice_number": payable.get("invoice_number", ""),
                    "invoice_type": payable.get("invoice_type", ""),
                    "currency": payable.get("currency", ""),
                    "stated_gross": str(reconciliation.stated) if reconciliation.stated is not None else "",
                    "will_book_gross": str(reconciliation.booked),
                    "difference": str(reconciliation.difference) if reconciliation.difference is not None else "",
                    "status": reconciliation.status,
                    "hypotheses": reconciliation.applied,
                    "evidence": reconciliation.evidence,
                    "master_data": document.master_evidence,
                    "pages": document.reading.pages,
                    "extraction": document.reading.source,
                    "notes": reconciliation.notes,
                }
            )
        for decline in result.declined:
            declines[decline.get("doc_type", "OTHER")] += 1

        files.append(
            {
                "file": result.file,
                "payables": entries,
                "declined": result.declined,
                "error": result.error,
            }
        )

    return {
        "totals": {
            "files": len(results),
            "payables": payable_count,
            "book_to_stated_total": booking_count,
            "book_rate": round(booking_count / payable_count, 4) if payable_count else 0.0,
            "declined": sum(declines.values()),
        },
        "statuses": dict(statuses),
        "hypotheses_used": dict(hypotheses),
        "declined_by_type": dict(declines),
        "master_data_resolved": dict(codes),
        "files": files,
    }


def print_summary(report: dict, output_dir: Path) -> None:
    totals = report["totals"]
    print(f"wrote {totals['files']} files to {output_dir}/")
    print(
        f"payables: {totals['payables']}  "
        f"booking to the document's own total: {totals['book_to_stated_total']} "
        f"({totals['book_rate']:.0%})  declined: {totals['declined']}"
    )
    if report["statuses"]:
        print("  status:", ", ".join(f"{name}={count}" for name, count in sorted(report["statuses"].items())))
    if report["hypotheses_used"]:
        print(
            "  hypotheses:",
            ", ".join(f"{name}={count}" for name, count in sorted(report["hypotheses_used"].items())),
        )
    unreconciled = [
        (file["file"], entry["invoice_number"], entry["difference"])
        for file in report["files"]
        for entry in file["payables"]
        if entry["status"] == "unreconciled"
    ]
    for name, number, difference in unreconciled[:20]:
        print(f"  unreconciled: {name} invoice {number or '?'} differs by {difference}")
