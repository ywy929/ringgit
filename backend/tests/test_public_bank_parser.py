from pathlib import Path

from app.services.parsers.public_bank import PublicBankParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "public_bank_sample.txt").read_text()


def test_can_parse_detects_public_bank():
    parser = PublicBankParser()
    assert parser.can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    parser = PublicBankParser()
    assert parser.can_parse("MAYBANK\nStatement of Account") is False


def test_parses_correct_transaction_count():
    parser = PublicBankParser()
    transactions = parser.parse(SAMPLE_TEXT)
    assert len(transactions) == 8


def test_parses_credit_transaction():
    parser = PublicBankParser()
    transactions = parser.parse(SAMPLE_TEXT)
    salary = transactions[0]
    assert salary["date"] == "2026-04-01"
    assert salary["description"] == "GIRO SALARY APR 2026"
    assert salary["amount"] == 4800.00
    assert salary["type"] == "credit"


def test_parses_debit_transaction():
    parser = PublicBankParser()
    transactions = parser.parse(SAMPLE_TEXT)
    jaya = transactions[1]
    assert jaya["date"] == "2026-04-04"
    assert jaya["description"] == "DEBIT CARD JAYA GROCER TTDI"
    assert jaya["amount"] == 245.60
    assert jaya["type"] == "debit"


def test_extract_period_month():
    parser = PublicBankParser()
    month = parser.extract_period_month(SAMPLE_TEXT)
    assert month == "2026-04"
