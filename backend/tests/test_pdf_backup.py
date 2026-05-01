import hashlib
from unittest.mock import patch

from app.models import Account, Statement
from app.routers.email import _process_fetched_pdf


def _seed_account(db, bank="maybank"):
    acc = Account(name="Test Maybank", bank=bank, type="savings")
    db.add(acc)
    db.commit()
    return acc


def _fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\nfake content for tests\n"


def test_fetched_pdf_written_to_disk_and_path_recorded(db, pdf_root):
    _seed_account(db)

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text): return [{"date": "2026-04-01", "description": "TEST", "amount": 10.0, "type": "debit"}]
        def extract_period_month(self, text): return "2026-04"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="MAYBANK STATEMENT OF ACCOUNT..."
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        result = _process_fetched_pdf("mbb.pdf", _fake_pdf_bytes(), db, "user@gmail.com")

    assert result.status == "done"
    stmt = db.query(Statement).first()
    assert stmt.file_path is not None
    full_path = pdf_root.parent / stmt.file_path
    assert full_path.exists()
    assert full_path.read_bytes() == _fake_pdf_bytes()
    assert "user_gmail_com" in stmt.file_path
    assert "maybank" in stmt.file_path


def test_duplicate_pdf_not_rewritten(db, pdf_root):
    _seed_account(db)

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text): return []
        def extract_period_month(self, text): return "2026-04"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="text"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        # First call: writes the file.
        _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "user@gmail.com")
        stmt = db.query(Statement).first()
        written = pdf_root.parent / stmt.file_path
        mtime_before = written.stat().st_mtime_ns

        # Second call with identical bytes: duplicate-skipped, no overwrite.
        result = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "user@gmail.com")
        assert result.status == "duplicate"
        assert written.stat().st_mtime_ns == mtime_before


def test_unknown_bank_still_writes_pdf(db, pdf_root):
    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="some text"
    ):
        mock_reg.detect_bank.return_value = None
        result = _process_fetched_pdf("unk.pdf", _fake_pdf_bytes(), db, "user@gmail.com")

    assert result.status == "failed"
    # Even on detection failure, bytes are preserved for later inspection.
    slug_dir = pdf_root / "user_gmail_com"
    pdfs = list(slug_dir.glob("unknown_unknown_*.pdf"))
    assert len(pdfs) == 1
    assert pdfs[0].read_bytes() == _fake_pdf_bytes()


def test_unknown_bank_dedup_blocks_second_fetch(db, pdf_root):
    # Without recording a Statement on failure, every poll re-writes the same
    # file. Verify the file_hash gate now catches the second attempt.
    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="some text"
    ):
        mock_reg.detect_bank.return_value = None
        first = _process_fetched_pdf("unk.pdf", _fake_pdf_bytes(), db, "user@gmail.com")
        second = _process_fetched_pdf("unk.pdf", _fake_pdf_bytes(), db, "user@gmail.com")

    assert first.status == "failed"
    assert second.status == "duplicate"

    stmts = db.query(Statement).all()
    assert len(stmts) == 1
    assert stmts[0].bank == "unknown"
    assert stmts[0].file_path is not None


def test_encrypted_pdf_saved_to_disk_with_stub_statement(db, pdf_root):
    encrypted_bytes = b"%PDF-1.4 fake-encrypted"
    with patch("app.routers.email._extract_text_from_pdf", side_effect=RuntimeError("encrypted")):
        result = _process_fetched_pdf("locked.pdf", encrypted_bytes, db, "user@gmail.com")

    assert result.status == "failed"
    assert "Password-protected" in (result.message or "")

    # Bytes are preserved on disk under a sensible name.
    saved = list((pdf_root / "user_gmail_com").glob("encrypted_*.pdf"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == encrypted_bytes

    # Stub Statement row exists so the dedup gate fires next fetch.
    stmt = db.query(Statement).filter_by(file_hash=hashlib.sha256(encrypted_bytes).hexdigest()).first()
    assert stmt is not None
    assert stmt.bank == "encrypted"
    assert stmt.file_path is not None


def test_sender_password_is_forwarded_to_text_extraction(db, pdf_root, monkeypatch):
    # When the sender has a password configured in SENDER_PASSWORDS, that
    # password must be threaded through to _extract_text_from_pdf.
    monkeypatch.setitem(
        __import__("app.config", fromlist=["SENDER_PASSWORDS"]).SENDER_PASSWORDS,
        "ewallet@tngdigital.com.my",
        "the-secret-password",
    )

    received_password = []
    def _fake_extract(content, password=None):
        received_password.append(password)
        return "TNG WALLET TRANSACTION HISTORY\nstub for can_parse"

    with patch("app.routers.email._extract_text_from_pdf", side_effect=_fake_extract):
        _process_fetched_pdf(
            "tng.pdf", b"%PDF-1.4 anything", db, "user@gmail.com",
            sender="ewallet@tngdigital.com.my",
        )

    assert received_password == ["the-secret-password"]


def test_unconfigured_sender_passes_no_password(db, pdf_root):
    received_password = []
    def _fake_extract(content, password=None):
        received_password.append(password)
        return "TNG WALLET TRANSACTION HISTORY\nstub"

    with patch("app.routers.email._extract_text_from_pdf", side_effect=_fake_extract):
        _process_fetched_pdf(
            "x.pdf", b"%PDF-1.4 anything", db, "user@gmail.com",
            sender="random@nowhere.com",
        )

    assert received_password == [None]


def test_encrypted_stub_dedup_blocks_re_fetch(db, pdf_root):
    encrypted_bytes = b"%PDF-1.4 fake-encrypted-2"
    with patch("app.routers.email._extract_text_from_pdf", side_effect=RuntimeError("encrypted")):
        first = _process_fetched_pdf("a.pdf", encrypted_bytes, db, "user@gmail.com")
        second = _process_fetched_pdf("a.pdf", encrypted_bytes, db, "user@gmail.com")

    assert first.status == "failed"
    assert second.status == "duplicate"
    # Only the original stub exists; the second fetch did not write a new one.
    assert db.query(Statement).count() == 1


def test_dedup_skips_overlapping_transactions_within_same_account(db, pdf_root):
    # Simulates an overlapping statement: pre-seed one transaction, then a
    # parser returns the same one plus a new one. Only the new one should be
    # inserted; the duplicate is reported via duplicates_skipped.
    from app.models import Transaction
    acc = _seed_account(db)
    db.add(Transaction(
        account_id=acc.id, date="2025-09-15", description="RFID Payment NPE - PJS 2",
        amount=1.00, type="debit",
    ))
    db.commit()

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text):
            return [
                # Duplicate of the pre-seeded row
                {"date": "2025-09-15", "description": "RFID Payment NPE - PJS 2", "amount": 1.00, "type": "debit"},
                # New row
                {"date": "2025-09-16", "description": "RFID Payment LDP - PETALING JAYA", "amount": 2.10, "type": "debit"},
            ]
        def extract_period_month(self, text): return "2025-09"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="MAYBANK STATEMENT"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        result = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "u@g.com")

    assert result.status == "done"
    assert result.transactions_imported == 1
    assert result.duplicates_skipped == 1
    # Only one new row added (plus the pre-seeded one) = 2 total for the account.
    assert db.query(Transaction).filter_by(account_id=acc.id).count() == 2


def test_strict_ref_dedup_blocks_re_import_with_same_reference(db, pdf_root):
    # When the parser exposes external_reference, dedup must use that key
    # rather than only the broad (date, amount, type, description) tuple.
    from app.models import Transaction
    acc = _seed_account(db)
    db.add(Transaction(
        account_id=acc.id, date="2025-09-15",
        description="RFID PLUS - JURU", amount=1.75, type="debit",
        external_reference="71114855443",
    ))
    db.commit()

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text):
            # Same ref → must be skipped, even though desc differs.
            return [{"date": "2025-09-15", "description": "RFID JURU PLUS",
                     "amount": 1.75, "type": "debit",
                     "external_reference": "71114855443"}]
        def extract_period_month(self, text): return "2025-09"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="MAYBANK STATEMENT"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        result = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "u@g.com")

    assert result.transactions_imported == 0
    assert result.duplicates_skipped == 1
    assert db.query(Transaction).filter_by(account_id=acc.id).count() == 1


def test_strict_ref_dedup_keeps_same_day_same_amount_with_different_refs(db, pdf_root):
    # The case that motivated strict dedup: two genuinely-different toll
    # passes on the same day for the same amount and (post-our-parser) the
    # same description string. Different external_reference must keep both.
    from app.models import Transaction
    acc = _seed_account(db)

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text):
            return [
                {"date": "2025-09-15", "description": "RFID PLUS - JURU",
                 "amount": 1.75, "type": "debit", "external_reference": "71114855443"},
                {"date": "2025-09-15", "description": "RFID PLUS - JURU",
                 "amount": 1.75, "type": "debit", "external_reference": "71114855444"},
            ]
        def extract_period_month(self, text): return "2025-09"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="MAYBANK STATEMENT"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        result = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "u@g.com")

    assert result.transactions_imported == 2
    assert result.duplicates_skipped == 0
    assert db.query(Transaction).filter_by(account_id=acc.id).count() == 2


def test_strict_ref_promotes_existing_no_ref_row(db, pdf_root):
    # Migration case: existing row has no ref. New parser run brings a ref
    # for what is the same transaction (same broad key). We should NOT insert
    # a duplicate — instead promote the existing row's ref to match.
    from app.models import Transaction
    acc = _seed_account(db)
    db.add(Transaction(
        account_id=acc.id, date="2025-09-15",
        description="RFID PLUS - JURU", amount=1.75, type="debit",
        external_reference=None,
    ))
    db.commit()

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text):
            return [{"date": "2025-09-15", "description": "RFID PLUS - JURU",
                     "amount": 1.75, "type": "debit",
                     "external_reference": "tng-ref-99"}]
        def extract_period_month(self, text): return "2025-09"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="MAYBANK STATEMENT"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        result = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "u@g.com")

    assert result.transactions_imported == 0
    assert result.duplicates_skipped == 1
    rows = db.query(Transaction).filter_by(account_id=acc.id).all()
    assert len(rows) == 1
    assert rows[0].external_reference == "tng-ref-99"  # promoted


def test_dedup_within_a_single_statement_run(db, pdf_root):
    # Two identical entries in the same parser output should also collapse.
    from app.models import Transaction
    acc = _seed_account(db)

    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text):
            return [
                {"date": "2025-09-15", "description": "RFID PLUS - JURU", "amount": 1.75, "type": "debit"},
                {"date": "2025-09-15", "description": "RFID PLUS - JURU", "amount": 1.75, "type": "debit"},
            ]
        def extract_period_month(self, text): return "2025-09"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="MAYBANK STATEMENT"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        result = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "u@g.com")

    assert result.transactions_imported == 1
    assert result.duplicates_skipped == 1
    assert db.query(Transaction).filter_by(account_id=acc.id).count() == 1


def test_no_account_for_bank_dedup_blocks_second_fetch(db, pdf_root):
    # Bank detected, but no Account row exists for it yet.
    class _FakeParser:
        bank_id = "maybank"
        def can_parse(self, text): return True
        def parse(self, text): return []
        def extract_period_month(self, text): return "2026-04"

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="text"
    ):
        mock_reg.detect_bank.return_value = _FakeParser()
        first = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "user@gmail.com")
        second = _process_fetched_pdf("a.pdf", _fake_pdf_bytes(), db, "user@gmail.com")

    assert first.status == "failed"
    assert "No account" in (first.message or "")
    assert second.status == "duplicate"

    stmts = db.query(Statement).all()
    assert len(stmts) == 1
    assert stmts[0].bank == "maybank"
