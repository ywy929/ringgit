from pathlib import Path

from app.services.parsers.tng import TnGParser

SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "tng_sample.txt").read_text()
NEW_SAMPLE_TEXT = (Path(__file__).parent.parent / "sample_data" / "tng_new_sample.txt").read_text()


def test_can_parse_detects_tng():
    assert TnGParser().can_parse(SAMPLE_TEXT) is True


def test_can_parse_rejects_other():
    assert TnGParser().can_parse("MAYBANK\nStatement of Account") is False


def test_extract_period_month():
    assert TnGParser().extract_period_month(SAMPLE_TEXT) == "2026-04"


def test_parses_all_transactions():
    txs = TnGParser().parse(SAMPLE_TEXT)
    # 3 online (one reload + two fare usage) + 1 offline = 4 total.
    assert len(txs) == 4


def test_parses_reload_as_credit():
    txs = TnGParser().parse(SAMPLE_TEXT)
    reload = txs[0]
    assert reload["date"] == "2026-04-01"
    assert reload["type"] == "credit"
    assert reload["amount"] == 100.00
    assert "Reload" in reload["description"]


def test_parses_fare_usage_as_debit():
    txs = TnGParser().parse(SAMPLE_TEXT)
    toll = txs[1]
    assert toll["date"] == "2026-04-01"
    assert toll["type"] == "debit"
    assert toll["amount"] == 2.30
    # Description should mention the toll plaza names from the location columns.
    assert "PLUS" in toll["description"]
    assert "JAWI" in toll["description"]


def test_parses_offline_section():
    txs = TnGParser().parse(SAMPLE_TEXT)
    offline = txs[3]
    assert offline["date"] == "2026-04-05"
    assert offline["type"] == "debit"
    assert offline["amount"] == 1.75
    assert "Barrier" in offline["description"]
    assert "LAGONG" in offline["description"]


def test_legacy_strips_trailing_sector_label():
    # Sector labels like "TOLL" appear after the balance and must not leak.
    txs = TnGParser().parse(SAMPLE_TEXT)
    toll = txs[1]  # the first Fare Usage tx in the sample has TOLL sector
    assert "TOLL" not in toll["description"]


def test_legacy_collapses_repeated_reload_location():
    # "OTA-TNGD" appears 3x in the chunk (Entry/Exit/Reload Location); the
    # description should not parrot it.
    txs = TnGParser().parse(SAMPLE_TEXT)
    reload = txs[0]
    assert reload["description"].count("OTA-TNGD") == 1


# ----- New format (TNG WALLET TRANSACTION HISTORY) -----

def test_new_format_can_parse():
    assert TnGParser().can_parse(NEW_SAMPLE_TEXT) is True


def test_new_format_extract_period_month():
    assert TnGParser().extract_period_month(NEW_SAMPLE_TEXT) == "2025-01"


def test_new_format_parses_all_transactions():
    txs = TnGParser().parse(NEW_SAMPLE_TEXT)
    assert len(txs) == 4  # 1 RFID + 1 Payment + 1 DUITNOW receive + 1 DuitNow QR


def test_new_format_rfid_payment_is_debit():
    txs = TnGParser().parse(NEW_SAMPLE_TEXT)
    rfid = txs[0]
    assert rfid["date"] == "2025-01-24"
    assert rfid["type"] == "debit"
    assert rfid["amount"] == 1.50
    assert "RFID" in rfid["description"]
    assert "BORR" in rfid["description"]


def test_new_format_payment_to_merchant():
    txs = TnGParser().parse(NEW_SAMPLE_TEXT)
    digi = txs[1]
    assert digi["date"] == "2025-01-22"
    assert digi["type"] == "debit"
    assert digi["amount"] == 83.00
    assert "Digi" in digi["description"]


def test_new_format_duitnow_receive_is_credit():
    txs = TnGParser().parse(NEW_SAMPLE_TEXT)
    incoming = txs[2]
    assert incoming["date"] == "2025-01-20"
    assert incoming["type"] == "credit"
    assert incoming["amount"] == 200.00
    # Both halves of the split DUITNOW_RECEI/VEFROM type should survive.
    assert "DUITNOW_RECEI" in incoming["description"]
    assert "VEFROM" in incoming["description"]


def test_new_format_duitnow_qr_payment():
    txs = TnGParser().parse(NEW_SAMPLE_TEXT)
    qr = txs[3]
    assert qr["date"] == "2025-01-15"
    assert qr["type"] == "debit"
    assert qr["amount"] == 25.50
    # Two-line merchant description should be joined.
    assert "RESTORAN TEST" in qr["description"]
    assert "PINANG" in qr["description"]


def test_legacy_populates_external_reference_from_trans_no():
    txs = TnGParser().parse(SAMPLE_TEXT)
    # Sample online transactions have Trans No 70001, 70002, 70003.
    refs = [tx.get("external_reference") for tx in txs[:3]]
    assert refs == ["70001", "70002", "70003"]


def test_new_format_populates_external_reference_from_ref_concat():
    txs = TnGParser().parse(NEW_SAMPLE_TEXT)
    rfid = txs[0]
    ref = rfid.get("external_reference")
    assert ref is not None
    # Reference should include the unique tx id from the source PDF.
    assert "71114855443" in ref


def test_new_format_skips_email_footer():
    # The "*This is a system generated email..." block sits between transactions.
    # It must not be included in any description.
    txs = TnGParser().parse(NEW_SAMPLE_TEXT)
    for tx in txs:
        assert "system generated" not in tx["description"]
        assert "do not reply" not in tx["description"].lower()
