from pathlib import Path

from app.services.parsers.cimb import CIMBParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "cimb_sample.txt").read_text()


def test_can_parse_detects_cimb():
    parser = CIMBParser()
    assert parser.can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    parser = CIMBParser()
    assert parser.can_parse("MAYBANK\nStatement of Account") is False


def test_parses_correct_transaction_count():
    parser = CIMBParser()
    transactions = parser.parse(SAMPLE_TEXT)
    assert len(transactions) == 8


def test_parses_credit_transaction():
    parser = CIMBParser()
    transactions = parser.parse(SAMPLE_TEXT)
    salary = transactions[0]
    assert salary["date"] == "2026-04-01"
    assert salary["description"] == "SALARY CREDIT"
    assert salary["amount"] == 5200.00
    assert salary["type"] == "credit"


def test_parses_debit_transaction():
    parser = CIMBParser()
    transactions = parser.parse(SAMPLE_TEXT)
    shopee = transactions[1]
    assert shopee["date"] == "2026-04-03"
    assert shopee["description"] == "POS DEBIT SHOPEE PAY"
    assert shopee["amount"] == 120.80
    assert shopee["type"] == "debit"


def test_extract_period_month():
    parser = CIMBParser()
    month = parser.extract_period_month(SAMPLE_TEXT)
    assert month == "2026-04"
