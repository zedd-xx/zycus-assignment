import json
from pathlib import Path

import pytest

from autodraft.cli import main
from autodraft.extract import llm
from autodraft.pipeline import _read_documents
from autodraft.segment import segment

ROOT = Path(__file__).resolve().parents[1]


def test_one_json_per_input_pdf(documents: Path, tmp_path: Path, cache: Path) -> None:
    output = tmp_path / "output"
    report = tmp_path / "run_report.json"
    code = main(
        [
            "--input", str(documents),
            "--output", str(output),
            "--master-data", str(ROOT / "master_data"),
            "--report", str(report),
            "--cache", str(cache),
            "--workers", "1",
        ]
    )
    assert code == 0

    inputs = sorted(path.stem for path in documents.glob("*.pdf"))
    written = sorted(path.stem for path in output.glob("*.json"))
    assert written == inputs

    for path in output.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert set(payload) == {"file", "payables", "declined"}
        assert payload["file"].endswith(".pdf")

    summary = json.loads(report.read_text(encoding="utf-8"))["totals"]
    assert summary["files"] == len(inputs)
    assert summary["payables"] >= len(inputs) - 1
    assert summary["book_to_stated_total"] == summary["payables"]


def test_a_missing_input_folder_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--input", str(tmp_path / "nope"), "--output", str(tmp_path / "out")])


def test_no_llm_configured_means_no_network_call(
    documents: Path, monkeypatch: pytest.MonkeyPatch, cache: Path
) -> None:
    for variable in ("AUTODRAFT_LLM", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(variable, raising=False)

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("the default path must not call a model")

    monkeypatch.setattr(llm, "read_document", explode)

    from autodraft.extract import read_pdf

    pdf = documents / "01_simple_invoice.pdf"
    readings = _read_documents(pdf, segment(read_pdf(pdf, cache_dir=cache)))
    assert readings and readings[0].invoice_number


def test_an_llm_that_fails_falls_back_to_the_deterministic_reading(
    documents: Path, monkeypatch: pytest.MonkeyPatch, cache: Path
) -> None:
    monkeypatch.setenv("AUTODRAFT_LLM", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setattr(llm, "read_document", lambda *args, **kwargs: None)

    from autodraft.extract import read_pdf

    pdf = documents / "01_simple_invoice.pdf"
    readings = _read_documents(pdf, segment(read_pdf(pdf, cache_dir=cache)))
    assert readings[0].invoice_number == "265345"
    assert readings[0].source != "llm"
