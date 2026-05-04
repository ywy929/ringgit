"""Per-bank regression tests against real PDF fixtures.

Each test is skipped on a fresh clone (fixture absent). As each bank's parser
is validated, drop the fixture PDF into tests/fixtures/real/, update the
expected count as needed, and the test will start running as a regression
guard on subsequent runs.
"""
from app.services.parsers.aeon import AEONParser
from app.services.parsers.cimb import CIMBParser
from app.services.parsers.hong_leong import HongLeongParser
from app.services.parsers.maybank import MaybankParser
from app.services.parsers.public_bank import PublicBankParser
from app.services.parsers.tng import TnGParser

from tests._real_pdf_helper import load_real_pdf_text, skip_if_no_fixture


@skip_if_no_fixture("maybank_202603.pdf")
def test_maybank_real_pdf():
    text = load_real_pdf_text("maybank_202603.pdf")
    parser = MaybankParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1, f"expected >=1 maybank transactions, got {len(txs)}"


@skip_if_no_fixture("cimb_202603.pdf")
def test_cimb_real_pdf():
    text = load_real_pdf_text("cimb_202603.pdf")
    parser = CIMBParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1


@skip_if_no_fixture("public_bank_202604.pdf")
def test_public_bank_real_pdf():
    # Real Apr 2026 statement: 9 debits + 2 credits = 11 transactions per
    # the summary block (and validates the page-wrap stitching against an
    # actual multi-page PDF, not just synthetic text).
    text = load_real_pdf_text("public_bank_202604.pdf")
    parser = PublicBankParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) == 11, f"expected 11 transactions, got {len(txs)}"
    # Sign sanity: closing - opening = 8,921.73 - 19,069.69 = -10,147.96.
    signed_total = sum(t["amount"] if t["type"] == "credit" else -t["amount"] for t in txs)
    assert abs(signed_total - (-10147.96)) < 0.01, f"signed total mismatch: {signed_total:.2f}"


@skip_if_no_fixture("hong_leong_202603.pdf")
def test_hong_leong_real_pdf():
    text = load_real_pdf_text("hong_leong_202603.pdf")
    parser = HongLeongParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1


@skip_if_no_fixture("tng_202603.pdf")
def test_tng_real_pdf():
    text = load_real_pdf_text("tng_202603.pdf")
    parser = TnGParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1


@skip_if_no_fixture("aeon_202603.pdf")
def test_aeon_real_pdf():
    text = load_real_pdf_text("aeon_202603.pdf")
    parser = AEONParser()
    assert parser.can_parse(text)
    txs = parser.parse(text)
    assert len(txs) >= 1
