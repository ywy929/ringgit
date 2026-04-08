from pathlib import Path

from app.services.parsers.hong_leong import HongLeongParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "hong_leong_sample.txt").read_text()


def test_can_parse_detects_hong_leong():
    parser = HongLeongParser()
    assert parser.can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    parser = HongLeongParser()
    assert parser.can_parse("MAYBANK\nStatement of Account") is False


def test_parses_correct_transaction_count():
    parser = HongLeongParser()
    transactions = parser.parse(SAMPLE_TEXT)
    assert len(transactions) == 8


def test_parses_credit_transaction():
    parser = HongLeongParser()
    transactions = parser.parse(SAMPLE_TEXT)
    salary = transactions[0]
    assert salary["date"] == "2026-04-01"
    assert salary["description"] == "SALARY APR"
    assert salary["amount"] == 3800.00
    assert salary["type"] == "credit"


def test_parses_debit_transaction():
    parser = HongLeongParser()
    transactions = parser.parse(SAMPLE_TEXT)
    starbucks = transactions[1]
    assert starbucks["date"] == "2026-04-03"
    assert starbucks["description"] == "VISA DBS STARBUCKS BANGSAR"
    assert starbucks["amount"] == 18.90
    assert starbucks["type"] == "debit"


def test_extract_period_month():
    parser = HongLeongParser()
    month = parser.extract_period_month(SAMPLE_TEXT)
    assert month == "2026-04"
