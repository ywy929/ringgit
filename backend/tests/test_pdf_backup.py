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
