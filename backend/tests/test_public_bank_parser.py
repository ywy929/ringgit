import logging
from pathlib import Path

from app.services.parsers.public_bank import PublicBankParser

SAMPLE = (Path(__file__).parent.parent / "sample_data" / "public_bank_sample.txt").read_text(encoding="utf-8")


def test_can_parse_positive():
    assert PublicBankParser().can_parse(SAMPLE) is True


def test_can_parse_rejects_partial_marker():
    text = "Public Bank Berhad\nSavings Account\nSomething else"
    assert PublicBankParser().can_parse(text) is False


def test_can_parse_rejects_maybank():
    text = "Malayan Banking Berhad\nURUSNIAGA AKAUN\nMaybank Savings"
    assert PublicBankParser().can_parse(text) is False


def test_extract_period_month():
    assert PublicBankParser().extract_period_month(SAMPLE) == "2026-04"


def test_extract_period_month_missing():
    assert PublicBankParser().extract_period_month("no date here") == ""


def test_parse_count_matches_summary():
    txs = PublicBankParser().parse(SAMPLE)
    # Summary: 6 debits + 1 credit = 7 transactions.
    assert len(txs) == 7, f"expected 7, got {len(txs)}: {txs}"


def test_parse_simple_debit_first_transaction():
    txs = PublicBankParser().parse(SAMPLE)
    first = txs[0]
    assert first["date"] == "2026-03-05"
    assert first["type"] == "debit"
    assert first["amount"] == 500.00
    assert "DUITNOW TRSF DR 123456" in first["description"]


def test_parse_simple_credit_second_transaction():
    txs = PublicBankParser().parse(SAMPLE)
    second = txs[1]
    assert second["date"] == "2026-03-07"
    assert second["type"] == "credit"
    assert second["amount"] == 30.00
    assert "INT CR-INT CYCLE" in second["description"]


def test_parse_same_day_repeats_preserved():
    # Three identical RM2.10 ATM withdrawals on 15/03 (toll-gate-style case
    # from ADR-003) must all be present.
    txs = PublicBankParser().parse(SAMPLE)
    same_day = [t for t in txs if t["date"] == "2026-03-15"]
    assert len(same_day) == 3
    assert all(t["amount"] == 2.10 for t in same_day)
    assert all(t["type"] == "debit" for t in same_day)


def test_parse_multi_line_description():
    txs = PublicBankParser().parse(SAMPLE)
    last = txs[-1]
    assert last["date"] == "2026-04-02"
    assert last["amount"] == 253.70
    assert last["type"] == "debit"
    # Joins all description lines.
    assert "TSFR FUND" in last["description"]
    assert "RECIPIENT" in last["description"]
    assert "APR FEES" in last["description"]


def test_parse_skips_balance_from_last_statement():
    # The opening-balance row produces no transaction; it just seeds the
    # running balance for the first real transaction's sign inference.
    txs = PublicBankParser().parse(SAMPLE)
    assert not any("Balance From Last Statement" in t["description"] for t in txs)


def test_parse_skips_closing_balance_marker():
    # The Closing Balance footer marker is a section terminator, not a
    # transaction row.
    txs = PublicBankParser().parse(SAMPLE)
    assert not any("Closing Balance" in t["description"] for t in txs)


def test_parse_signs_are_correct_via_balance_delta():
    # Sanity: total signed = closing - opening.
    txs = PublicBankParser().parse(SAMPLE)
    signed_total = sum(t["amount"] if t["type"] == "credit" else -t["amount"] for t in txs)
    # Opening 2000.00 → closing 1250.00 → delta -750.00.
    assert abs(signed_total - (-750.00)) < 0.01


PAGE_WRAP_SAMPLE = """\
PENYATA AKAUN / STATEMENT OF ACCOUNT
Tarikh Penyata / Statement Date
03 Apr 2026
Jenis Akaun / Account Type RM Moneyplus Savings Account
Public Bank's Privacy Notice
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
500.00
500.00
1
0.00
0
03/03
Balance From Last Statement
1,000.00
24/03
500.00
500.00
DR-ECP 462236 LINE-1
LINE-2
LINE-3
Balance C/F
500.00
Muka Surat 1 Daripada 2
Page 1 of 2
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
24/03
Balance B/F
500.00
ORPHAN-LINE-FROM-PAGE-2
Closing Balance In This Statement
500.00
"""


def test_page_wrap_description_stitched():
    txs = PublicBankParser().parse(PAGE_WRAP_SAMPLE)
    assert len(txs) == 1
    only = txs[0]
    assert only["date"] == "2026-03-24"
    assert only["amount"] == 500.00
    assert only["type"] == "debit"
    # All description lines (page-1 + page-2 orphan) are joined.
    assert "LINE-1" in only["description"]
    assert "LINE-2" in only["description"]
    assert "LINE-3" in only["description"]
    assert "ORPHAN-LINE-FROM-PAGE-2" in only["description"]


YEAR_WRAP_SAMPLE = """\
PENYATA AKAUN / STATEMENT OF ACCOUNT
Tarikh Penyata / Statement Date
03 Jan 2026
Jenis Akaun / Account Type RM Moneyplus Savings Account
Public Bank's Privacy Notice
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
1,000.00
0.00
0
2.00
1
03/12
Balance From Last Statement
998.00
31/12
2.00
1,000.00
INT CR-INT CYCLE
Closing Balance In This Statement
1,000.00
"""


def test_year_inference_wrap():
    # Jan 2026 statement contains 03/12 and 31/12 → those are Dec 2025.
    txs = PublicBankParser().parse(YEAR_WRAP_SAMPLE)
    assert len(txs) == 1
    only = txs[0]
    assert only["date"] == "2025-12-31"
    assert only["type"] == "credit"
    assert only["amount"] == 2.00


def test_out_of_bounds_date_logs_warning(caplog):
    # A statement claiming Apr 2026 with a transaction dated 03/06 (June)
    # would infer 2025-06 (year-1 because 6 > 4). That's > 40 days before
    # the statement date — the parser should log a warning but still emit
    # the transaction.
    sample = """\
Tarikh Penyata / Statement Date
03 Apr 2026
Jenis Akaun / Account Type RM Moneyplus Savings Account
Public Bank's Privacy Notice
TARIKH
URUS NIAGA
DEBIT
KREDIT
BAKI
DATE
TRANSACTION
DEBIT
CREDIT
BALANCE
0.00
10.00
1
0.00
0
03/06
Balance From Last Statement
10.00
03/06
10.00
0.00
SOMETHING SUSPICIOUS
Closing Balance In This Statement
0.00
"""
    with caplog.at_level(logging.WARNING):
        txs = PublicBankParser().parse(sample)
    # Transaction is still emitted (soft-bound, not hard fail).
    assert len(txs) == 1
    # And a warning was logged.
    assert any("out of bounds" in r.message.lower() for r in caplog.records)
