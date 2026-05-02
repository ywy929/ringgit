import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay_statement.py"


def _make_pdf_with_text(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def test_replay_exits_nonzero_for_unknown_bank(tmp_path):
    pdf = tmp_path / "mystery.pdf"
    _make_pdf_with_text(pdf, "this does not look like any bank statement")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(pdf)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "no parser matched" in result.stdout.lower() or "no parser matched" in result.stderr.lower()


def test_replay_exits_zero_when_parser_finds_transactions(tmp_path):
    # Use the committed maybank text fixture as a PDF.
    pdf = tmp_path / "maybank.pdf"
    sample_txt = Path(__file__).resolve().parents[1] / "sample_data" / "maybank_sample.txt"
    _make_pdf_with_text(pdf, sample_txt.read_text(encoding="utf-8"))

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(pdf)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "maybank" in result.stdout.lower()
    assert "transactions parsed" in result.stdout.lower()
