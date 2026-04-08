from pathlib import Path

from app.services.parsers.aeon import AEONParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "aeon_sample.txt").read_text()


def test_can_parse_detects_aeon():
    parser = AEONParser()
    assert parser.can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    parser = AEONParser()
    assert parser.can_parse("MAYBANK\nStatement of Account") is False


def test_parses_correct_transaction_count():
    parser = AEONParser()
    transactions = parser.parse(SAMPLE_TEXT)
    assert len(transactions) == 8


def test_parses_credit_transaction():
    parser = AEONParser()
    transactions = parser.parse(SAMPLE_TEXT)
    payment = transactions[0]
    assert payment["date"] == "2026-04-01"
    assert payment["description"] == "PAYMENT RECEIVED - THANK YOU"
    assert payment["amount"] == 1200.00
    assert payment["type"] == "credit"


def test_parses_debit_transaction():
    parser = AEONParser()
    transactions = parser.parse(SAMPLE_TEXT)
    watsons = transactions[1]
    assert watsons["date"] == "2026-04-04"
    assert watsons["description"] == "WATSON'S PAVILION KL"
    assert watsons["amount"] == 42.50
    assert watsons["type"] == "debit"


def test_extract_period_month():
    parser = AEONParser()
    month = parser.extract_period_month(SAMPLE_TEXT)
    assert month == "2026-04"
