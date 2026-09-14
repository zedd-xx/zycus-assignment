"""The single command: read a folder of PDFs, write output/X.json for each.

    python -m autodraft --input documents --output output
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from autodraft.masters import MasterData
from autodraft.pipeline import FileResult, process_pdf
from autodraft.report import build_report, print_summary

DEFAULT_CACHE = ".autodraft_cache"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autodraft", description=__doc__)
    parser.add_argument("--input", "-i", default="documents", help="folder of PDFs to process")
    parser.add_argument("--output", "-o", default="output", help="folder to write one JSON per PDF into")
    parser.add_argument("--master-data", "-m", default="master_data", help="folder holding the master data")
    parser.add_argument("--report", default="reports/run_report.json", help="where to write the run report")
    parser.add_argument("--tenant", default="", help="buyer/tenant hint when it is not printed on the documents")
    parser.add_argument("--cache", default=DEFAULT_CACHE, help="extraction cache folder ('' to disable)")
    parser.add_argument("--workers", type=int, default=0, help="parallel workers (0 = one per CPU)")
    parser.add_argument("--only", default="", help="process just the PDFs whose name contains this")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    input_dir = Path(args.input)
    if not input_dir.is_dir():
        parser.error(f"input folder {input_dir} does not exist")

    pdfs = sorted(path for path in input_dir.rglob("*.pdf") if args.only.lower() in path.name.lower())
    if not pdfs:
        parser.error(f"no PDFs found under {input_dir}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache) if args.cache else None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    masters = MasterData(args.master_data)
    results = _run(pdfs, masters, cache_dir, args.tenant, args.workers)

    for result in results:
        target = output_dir / f"{Path(result.file).stem}.json"
        target.write_text(json.dumps(result.to_output(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    report = build_report(results)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print_summary(report, output_dir)
    return 0


def _run(
    pdfs: list[Path],
    masters: MasterData,
    cache_dir: Path | None,
    tenant: str,
    workers: int,
) -> list[FileResult]:
    if workers == 1 or len(pdfs) == 1:
        return [process_pdf(pdf, masters, cache_dir, tenant) for pdf in pdfs]

    results: list[FileResult] = []
    with ProcessPoolExecutor(max_workers=workers or None) as pool:
        futures = {pool.submit(process_pdf, pdf, masters, cache_dir, tenant): pdf for pdf in pdfs}
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda result: result.file)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
