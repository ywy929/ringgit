from pathlib import Path

from app.services.parsers.maybank import MaybankParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "maybank_sample.txt").read_text(encoding="utf-8")


def test_can_parse_detects_maybank():
    parser = MaybankParser()
    assert parser.can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    parser = MaybankParser()
    assert parser.can_parse("CIMB BANK BERHAD\nStatement of Account") is False


def test_parses_correct_transaction_count():
    parser = MaybankParser()
    transactions = parser.parse(SAMPLE_TEXT)
    assert len(transactions) == 8


def test_parses_credit_transaction():
    parser = MaybankParser()
    transactions = parser.parse(SAMPLE_TEXT)
    salary = transactions[0]
    assert salary["date"] == "2026-04-01"
    assert salary["description"] == "SALARY APR 2026"
    assert salary["amount"] == 5200.00
    assert salary["type"] == "credit"


def test_parses_debit_transaction():
    parser = MaybankParser()
    transactions = parser.parse(SAMPLE_TEXT)
    grab = transactions[1]
    assert grab["date"] == "2026-04-03"
    assert grab["description"] == "GRABFOOD A-32891KL"
    assert grab["amount"] == 32.50
    assert grab["type"] == "debit"


def test_extract_period_month():
    parser = MaybankParser()
    month = parser.extract_period_month(SAMPLE_TEXT)
    assert month == "2026-04"
