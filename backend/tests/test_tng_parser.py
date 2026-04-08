from pathlib import Path

from app.services.parsers.tng import TnGParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "tng_sample.txt").read_text()


def test_can_parse_detects_tng():
    parser = TnGParser()
    assert parser.can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    parser = TnGParser()
    assert parser.can_parse("MAYBANK\nStatement of Account") is False


def test_parses_correct_transaction_count():
    parser = TnGParser()
    transactions = parser.parse(SAMPLE_TEXT)
    assert len(transactions) == 10


def test_parses_credit_transaction():
    parser = TnGParser()
    transactions = parser.parse(SAMPLE_TEXT)
    reload = transactions[0]
    assert reload["date"] == "2026-04-01"
    assert reload["description"] == "Reload from Maybank ****7890"
    assert reload["amount"] == 100.00
    assert reload["type"] == "credit"


def test_parses_debit_transaction():
    parser = TnGParser()
    transactions = parser.parse(SAMPLE_TEXT)
    grab = transactions[1]
    assert grab["date"] == "2026-04-01"
    assert grab["description"] == "GrabFood - Nasi Lemak House"
    assert grab["amount"] == 15.50
    assert grab["type"] == "debit"


def test_extract_period_month():
    parser = TnGParser()
    month = parser.extract_period_month(SAMPLE_TEXT)
    assert month == "2026-04"
