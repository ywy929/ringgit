"""Helper for real-PDF regression tests.

Each parser gets one `test_<bank>_real` test that loads
`backend/tests/fixtures/real/<bank>_<YYYYMM>.pdf` — gitignored — and asserts
basic parse counts. When the file is missing (fresh clone, CI) the test skips.
"""
from pathlib import Path

import fitz  # PyMuPDF
import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "real"


def load_real_pdf_text(filename: str) -> str | None:
    """Return extracted text, or None if the fixture is absent."""
    path = FIXTURE_DIR / filename
    if not path.exists():
        return None
    doc = fitz.open(str(path))
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def skip_if_no_fixture(filename: str):
    """Decorator factory: skips the test when the fixture file is absent."""
    return pytest.mark.skipif(
        not (FIXTURE_DIR / filename).exists(),
        reason=f"real fixture {filename} not present (drop into {FIXTURE_DIR} to enable)",
    )
