from pathlib import Path

from app.services.parsers.maybank import MaybankParser

SAMPLE_2026 = (Path(__file__).parent.parent / "sample_data" / "maybank_sample.txt").read_text(encoding="utf-8")
SAMPLE_2018 = (Path(__file__).parent.parent / "sample_data" / "maybank_2018_sample.txt").read_text(encoding="utf-8")


def test_can_parse_detects_maybank_2026():
    assert MaybankParser().can_parse(SAMPLE_2026) is True


def test_can_parse_detects_maybank_2018():
    assert MaybankParser().can_parse(SAMPLE_2018) is True


def test_can_parse_rejects_just_maybank_word():
    # The word MAYBANK alone is not enough — we need both definitive markers.
    text = "MAYBANK\nSomething Statement of Account\n"
    assert MaybankParser().can_parse(text) is False


def test_can_parse_rejects_aeon():
    text = (
        "AEON CREDIT SERVICE (M) BHD\n"
        "Total Charges of the Month\n"
        "Statement Date / Tarikh Penyata\n"
        "25 Apr 2026\n"
    )
    assert MaybankParser().can_parse(text) is False


def test_can_parse_rejects_tng():
    text = "TNG WALLET TRANSACTION HISTORY\nDate Status Type\n"
    assert MaybankParser().can_parse(text) is False


def test_extract_period_month_2026():
    assert MaybankParser().extract_period_month(SAMPLE_2026) == "2026-03"


def test_extract_period_month_2018():
    assert MaybankParser().extract_period_month(SAMPLE_2018) == "2018-03"


def test_century_inference_via_strptime():
    # Python's %y treats 00-68 as 20XX and 69-99 as 19XX. Maybank data falls
    # in 18-26, well inside 20XX. Confirm via the parser's date-anchor handling.
    parser = MaybankParser()
    txs_2026 = parser.parse(SAMPLE_2026)
    assert txs_2026[0]["date"].startswith("2026-")
    txs_2018 = parser.parse(SAMPLE_2018)
    assert txs_2018[0]["date"].startswith("2018-")


def test_parses_2026_format_count():
    txs = MaybankParser().parse(SAMPLE_2026)
    assert len(txs) == 3, f"expected 3 transactions, got {len(txs)}: {txs}"


def test_parses_2026_credit_first_transaction():
    txs = MaybankParser().parse(SAMPLE_2026)
    first = txs[0]
    assert first["date"] == "2026-03-02"
    assert first["type"] == "credit"
    assert first["amount"] == 500.00
    assert first["description"] == "TRANSFER FROM A/C"


def test_parses_2026_debit_with_multi_line_description():
    txs = MaybankParser().parse(SAMPLE_2026)
    second = txs[1]
    assert second["date"] == "2026-03-06"
    assert second["type"] == "debit"
    assert second["amount"] == 200.00
    # Description joins type label + indented detail lines.
    assert "TRANSFER TO A/C" in second["description"]
    assert "SITTAL CARPARK SDN" in second["description"]
    assert "SITTAL CARPARK" in second["description"]


def test_parses_2026_credit_third_transaction_no_details():
    txs = MaybankParser().parse(SAMPLE_2026)
    third = txs[2]
    assert third["date"] == "2026-03-10"
    assert third["type"] == "credit"
    assert third["amount"] == 50.00
    # No detail lines, so description == type label only (no trailing " - ").
    assert third["description"] == "REFUND"


def test_parses_2018_format_count():
    txs = MaybankParser().parse(SAMPLE_2018)
    assert len(txs) == 3, f"expected 3 transactions, got {len(txs)}: {txs}"


def test_parses_2018_skips_gst_line():
    # The DEBIT ADVICE transaction in the 2018 sample has a standalone "SR"
    # line between the type label and the amount. The parser must not treat
    # SR as an amount or as the type label of a separate transaction.
    txs = MaybankParser().parse(SAMPLE_2018)
    debit = txs[1]
    assert debit["date"] == "2018-03-06"
    assert debit["type"] == "debit"
    assert debit["amount"] == 8.48
    assert "DEBIT ADVICE" in debit["description"]
    # The GST detail line gets joined into the description (acceptable).
    assert "INCLUSIVE OF GST" in debit["description"]


def test_parses_2018_cash_deposit_no_gst_line():
    # CASH DEPOSIT in old format has no GST line (transaction is GST-exempt).
    txs = MaybankParser().parse(SAMPLE_2018)
    deposit = txs[0]
    assert deposit["date"] == "2018-03-05"
    assert deposit["type"] == "credit"
    assert deposit["amount"] == 250.00
    assert deposit["description"] == "CASH DEPOSIT"


def test_skips_beginning_balance_as_transaction():
    # BEGINNING BALANCE is an anchor for the reconciler, not a transaction.
    # The parser must not emit a phantom row for it.
    txs = MaybankParser().parse(SAMPLE_2026)
    descriptions = [t["description"] for t in txs]
    assert not any("BEGINNING BALANCE" in d for d in descriptions)


def test_skips_ending_balance_as_transaction():
    # ENDING BALANCE is the 2018-format footer marker, not a transaction.
    txs = MaybankParser().parse(SAMPLE_2018)
    descriptions = [t["description"] for t in txs]
    assert not any("ENDING BALANCE" in d for d in descriptions)
    assert not any("TOTAL CREDIT" in d for d in descriptions)
    assert not any("TOTAL DEBIT" in d for d in descriptions)
