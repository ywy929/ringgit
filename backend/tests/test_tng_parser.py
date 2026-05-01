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
    # The split DUITNOW_RECEI/VEFROM should be rejoined into the full atomic
    # type identifier (no space artifact from PyMuPDF cell wrapping).
    assert "DUITNOW_RECEIVEFROM" in incoming["description"]
    assert "DUITNOW_RECEI VEFROM" not in incoming["description"]


def test_new_format_duitnow_qr_payment():
    txs = TnGParser().parse(NEW_SAMPLE_TEXT)
    qr = txs[3]
    assert qr["date"] == "2025-01-15"
    assert qr["type"] == "debit"
    assert qr["amount"] == 25.50
    # Two-line merchant description should be joined.
    assert "RESTORAN TEST" in qr["description"]
    assert "PINANG" in qr["description"]
    # The trailing "20250115101" reference fragment glued to "DuitNow QR TNGD"
    # in the source PDF must NOT leak into the description.
    assert "20250115101" not in qr["description"]
    assert "DuitNow QR TNGD" in qr["description"]


def test_payment_with_reload_in_description_is_debit():
    # "Payment" type whose description contains the word "Card Reload" must
    # remain a debit — credit detection looks at the TYPE column, not the
    # whole chunk text.
    text = """TNG WALLET TRANSACTION HISTORY
1 August 2025 - 31 August 2025
TEST USER
1000005200000000
Registered Name
Wallet ID
Account Status
Generated Date & Time
Transaction Period
1 September 2025 10:00 AM
Active
Date
Status
Transaction Type
Reference
Description
Details
Amount (RM)
Wallet Balance
21/8/2025
Success
Payment
20250821101
10000010000
TNGOW3MY1
71114807495
985
Card Reload
202508212112128001001711173976
33540
RM10.00
RM270.49
"""
    txs = TnGParser().parse(text)
    assert len(txs) == 1
    assert txs[0]["type"] == "debit"
    assert txs[0]["amount"] == 10.00
    assert "Card Reload" in txs[0]["description"]


def test_cashback_is_credit():
    text = """TNG WALLET TRANSACTION HISTORY
1 April 2026 - 30 April 2026
TEST USER
1000005200000000
Registered Name
Wallet ID
Account Status
Generated Date & Time
Transaction Period
1 May 2026 10:00 AM
Active
Date
Status
Transaction Type
Reference
Description
Details
Amount (RM)
Wallet Balance
13/4/2026
Success
Cashback
20260413211
22590230017
11111493626
59
7-Eleven RM1 Cashback with Min.
Spend RM11
2026041310110000010000TNGOW3
MY171114883347208
RM1.00
RM13.21
"""
    txs = TnGParser().parse(text)
    assert len(txs) == 1
    assert txs[0]["type"] == "credit"
    assert txs[0]["amount"] == 1.00
    assert "Cashback" in txs[0]["description"]


def test_receive_from_wallet_is_credit():
    text = """TNG WALLET TRANSACTION HISTORY
1 September 2025 - 30 September 2025
TEST USER
1000005200000000
Registered Name
Wallet ID
Account Status
Generated Date & Time
Transaction Period
1 October 2025 10:00 AM
Active
Date
Status
Transaction Type
Reference
Description
Details
Amount (RM)
Wallet Balance
16/9/2025
Success
Receive from Wallet20250916111
21700010100
17111484151
6033
SOME PAYER
2025091610110000010000TNGOW3
MY171114855292106
RM50.00
RM200.00
"""
    txs = TnGParser().parse(text)
    assert len(txs) == 1
    assert txs[0]["type"] == "credit"
    assert txs[0]["amount"] == 50.00


def test_no_whitespace_glued_ref_is_stripped():
    # Some Payment-type rows render the merchant name and a long Details
    # reference glued together with NO whitespace between them, e.g.
    # "CASE ZONE (SUNWAY CARNIVAL)202508112112128001101711140285".
    # The trailing pure-digit run must be stripped from the description.
    text = """TNG WALLET TRANSACTION HISTORY
1 January 2025 - 31 January 2025
TEST USER
1000005200000000
Registered Name
Wallet ID
Account Status
Generated Date & Time
Transaction Period
1 February 2025 10:00 AM
Active
Date
Status
Transaction Type
Reference
Description
Details
Amount (RM)
Wallet Balance
11/8/2025
Success
Payment
20250811101
10000010000
TNGOW3MY1
71114804604
626
CASE ZONE (SUNWAY CARNIVAL)202508112112128001101711140285
11200
RM15.00
RM25.85
"""
    txs = TnGParser().parse(text)
    assert len(txs) == 1
    desc = txs[0]["description"]
    assert "CASE ZONE (SUNWAY CARNIVAL)" in desc
    # The 30-digit ref must NOT appear anywhere in the description.
    assert "202508112112128001101711140285" not in desc
    # Nor the 5-digit fragment from the next line.
    assert "11200" not in desc


def test_uppercase_name_words_are_not_stripped_as_refs():
    # Multi-line description with a pure-letter 8+ char surname continuation
    # (e.g., "MERVIN CHRISTOPHER" / "THESEIRA"). The continuation must not be
    # filtered as if it were a reference code.
    text = """TNG WALLET TRANSACTION HISTORY
1 January 2025 - 31 January 2025
TEST USER
1000005200000000
Registered Name
Wallet ID
Account Status
Generated Date & Time
Transaction Period
1 February 2025 10:00 AM
Active
Date
Status
Transaction Type
Reference
Description
Details
Amount (RM)
Wallet Balance
30/4/2025
Success
Transfer to Wallet
20250430101
11000010000
TNGOW3MY1
71114886142
3509
MERVIN CHRISTOPHER
THESEIRA
RM10.00
RM75.61
"""
    txs = TnGParser().parse(text)
    assert len(txs) == 1
    desc = txs[0]["description"]
    assert "MERVIN CHRISTOPHER" in desc
    assert "THESEIRA" in desc


def test_uppercase_location_words_are_not_stripped_as_refs():
    # All-letter uppercase tokens of 8+ chars (e.g., DAMANSARA, PAVLONDM) are
    # location names, not references — they must survive description cleanup.
    text = """TNG WALLET TRANSACTION HISTORY
1 January 2025 - 31 January 2025
TEST USER
1000005200000000
Registered Name
Wallet ID
Account Status
Generated Date & Time
Transaction Period
1 February 2025 10:00 AM
Active
Date
Status
Transaction Type
Reference
Description
Details
Amount (RM)
Wallet Balance
20/1/2025
Success
DuitNow QR
20250120101
10000010000
TNGOW3MY1
71114854480
515
BEUTEA PAVILION DAMANSARA
202501202112128001001711107748
29536
RM17.90
RM55.57
"""
    txs = TnGParser().parse(text)
    assert len(txs) == 1
    assert "DAMANSARA" in txs[0]["description"]


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


# ----- is_credit_type() helper tests -----

from app.services.parsers.tng import is_credit_type


def test_is_credit_type_known_credit_types():
    # Five canonical credit types — including the line-split DUITNOW_RECEI
    # form where chunk[2] alone is the prefix.
    assert is_credit_type("DUITNOW_RECEI") is True
    assert is_credit_type("DUITNOW_RECEIVEFROM") is True
    assert is_credit_type("Receive from Wallet20250916111") is True
    assert is_credit_type("Reload") is True
    assert is_credit_type("Refund") is True
    assert is_credit_type("Cashback") is True


def test_is_credit_type_legacy_ota_reload():
    # Legacy "Customer Transactions Statement" format puts the type as
    # "OTA Reload" (or "OTA\nReload" pre-join). The "OTA " prefix means a
    # plain startswith("RELOAD") check would miss it. Use substring `in`.
    assert is_credit_type("OTA Reload") is True


def test_is_credit_type_known_debit_types():
    # All Payment / RFID Payment / DuitNow QR / Transfer / PayDirect / DUITNOW_TRANSFER
    # variants must come back False so credits aren't accidentally flipped.
    assert is_credit_type("Payment") is False
    assert is_credit_type("RFID Payment") is False
    assert is_credit_type("DuitNow QR") is False
    assert is_credit_type("DuitNow QR TNGD 20251102101") is False
    assert is_credit_type("Transfer to Wallet") is False
    assert is_credit_type("PayDirect Payment 20251017101") is False
    assert is_credit_type("DUITNOW_TRANS") is False
