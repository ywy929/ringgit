from pathlib import Path

from app.services.parsers.aeon import AEONParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "aeon_sample.txt").read_text()


def test_can_parse_detects_aeon_credit_card():
    assert AEONParser().can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    assert AEONParser().can_parse("MAYBANK\nStatement of Account") is False


def test_can_parse_rejects_vp_prepaid():
    # VP statements have AEON CREDIT SERVICE but no "Total Charges of the Month"
    # — the credit-card-billing-cycle concept that distinguishes BC from VP.
    vp_text = (
        "AEON CREDIT SERVICE (M) BHD\n"
        "Your Previous Statement Balance\n"
        "0.00\n"
        "Credit Transaction(s)\n"
        "Total Spent for this month\n"
        "0.00\n"
        "Total Available Balance\n"
        "100.00\n"
    )
    assert AEONParser().can_parse(vp_text) is False


def test_extract_period_month():
    # Statement Date in the synthetic sample is "25 Apr 2026" → "2026-04".
    assert AEONParser().extract_period_month(SAMPLE_TEXT) == "2026-04"


def test_parses_transaction_count():
    txs = AEONParser().parse(SAMPLE_TEXT)
    # 3 real transactions; the "YOUR PREVIOUS STATEMENT BALANCE" header row
    # in the description column must NOT be counted as a transaction.
    assert len(txs) == 3


def test_parses_credit_payment():
    # The CR-marked payment ("PAYMENT - THANK YOU CR 500.00").
    txs = AEONParser().parse(SAMPLE_TEXT)
    payment = txs[0]
    assert payment["date"] == "2026-04-01"
    assert payment["type"] == "credit"
    assert payment["amount"] == 500.00
    assert "PAYMENT" in payment["description"]
    # The literal "CR" line must NOT leak into the description.
    assert payment["description"].strip() != "CR"
    assert " CR " not in f" {payment['description']} "
    assert payment["description"] != "CR"


def test_parses_debit_purchase():
    txs = AEONParser().parse(SAMPLE_TEXT)
    coffee = txs[1]
    assert coffee["date"] == "2026-04-04"
    assert coffee["type"] == "debit"
    assert coffee["amount"] == 20.00
    assert "COFFEE SHOP" in coffee["description"]
    assert "KUALA LUMPUR" in coffee["description"]


def test_parses_multi_line_description():
    txs = AEONParser().parse(SAMPLE_TEXT)
    multi = txs[2]
    assert multi["date"] == "2026-04-09"
    assert multi["type"] == "debit"
    assert multi["amount"] == 200.00
    # The merchant name is split across two source lines and must be joined.
    assert "LONG MERCHANT NAME" in multi["description"]
    assert "MULTI LINE DESCRIPTION TEST" in multi["description"]


def test_external_reference_is_none():
    # AEON statements don't expose per-tx reference IDs.
    txs = AEONParser().parse(SAMPLE_TEXT)
    for tx in txs:
        assert tx.get("external_reference") is None
