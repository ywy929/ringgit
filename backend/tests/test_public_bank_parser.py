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
