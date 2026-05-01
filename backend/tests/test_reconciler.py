from app.services.reconciler import (
    ReconcileResult,
    _check_count,
    _check_statement_balance,
    _check_per_row,
)


def test_reconcile_result_default_construction():
    r = ReconcileResult(ok=True)
    assert r.ok is True
    assert r.note is None
    assert r.checks_run == []


def test_check_count_pass():
    r = _check_count(db_count=10, table_count=10)
    assert r.ok is True


def test_check_count_fail_includes_both_numbers():
    r = _check_count(db_count=10, table_count=11)
    assert r.ok is False
    assert "10" in r.note and "11" in r.note


def test_check_statement_balance_pass():
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.30, "balance": 97.70},
        {"signed_amount":  5.00, "balance": 102.70},
    ]
    # opening = 100.00 - (-1.50) = 101.50
    # sum     = -1.50 + -2.30 + 5.00 = 1.20
    # closing = 102.70
    # 101.50 + 1.20 = 102.70 ✓
    assert _check_statement_balance(rows).ok is True


def test_check_statement_balance_fail():
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.30, "balance": 95.00},  # off
    ]
    r = _check_statement_balance(rows)
    assert r.ok is False
    assert "balance" in r.note.lower()


def test_check_statement_balance_no_data_passes():
    # Offline-only legacy section — every row's balance is None. Skip-pass.
    rows = [{"signed_amount": -1.75, "balance": None}]
    assert _check_statement_balance(rows).ok is True


def test_check_statement_balance_tolerance_001():
    rows = [
        {"signed_amount": -1.50, "balance": 100.005},
        {"signed_amount": -2.30, "balance": 97.71},  # off by 0.005, within 0.01
    ]
    assert _check_statement_balance(rows).ok is True


def test_check_per_row_pass():
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.30, "balance": 97.70},
        {"signed_amount":  5.00, "balance": 102.70},
    ]
    assert _check_per_row(rows).ok is True


def test_check_per_row_fail_at_specific_row():
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.30, "balance": 99.00},  # should be 97.70
    ]
    r = _check_per_row(rows)
    assert r.ok is False
    assert "row 2" in r.note  # 1-indexed


def test_check_per_row_skips_when_balance_missing():
    # Online row, then offline row (no balance), then back to online. The
    # offline row is unverifiable — the check just skips that pair.
    rows = [
        {"signed_amount": -1.50, "balance": 100.00},
        {"signed_amount": -2.00, "balance": None},   # offline, skip
        {"signed_amount": -3.00, "balance": 95.00},  # standalone, skip
    ]
    assert _check_per_row(rows).ok is True


import shutil
from pathlib import Path

import pytest

from app.models import Account, Statement, Transaction
from app.services.parsers.tng import TnGParser
from app.services.reconciler import reconcile_statement


_FIXTURE_NAME = "tng_annual.pdf"
_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "real"
_FIXTURE_PATH = _FIXTURE_DIR / _FIXTURE_NAME
_TNG_PASSWORD = "172895255"  # owner-supplied; matches PDF_PASSWORD_TNG in .env


def _seed_tng_account(db) -> Account:
    acc = Account(name="TnG", bank="tng", type="ewallet")
    db.add(acc)
    db.commit()
    return acc


@pytest.mark.skipif(not _FIXTURE_PATH.exists(), reason=f"real fixture {_FIXTURE_NAME} not present")
def test_reconcile_real_tng_annual_passes(db, monkeypatch, tmp_path):
    # Use the existing find_tables-validated annual statement. With the regex
    # parser's output and the real PDF, all three checks should pass.
    import fitz

    # Stage the fixture into tmp_path so file_path is portable.
    staged = tmp_path / _FIXTURE_NAME
    shutil.copy(_FIXTURE_PATH, staged)
    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)
    monkeypatch.setitem(
        __import__("app.config", fromlist=["SENDER_PASSWORDS"]).SENDER_PASSWORDS,
        "ewallet@tngdigital.com.my",
        _TNG_PASSWORD,
    )

    acc = _seed_tng_account(db)

    # Parse & insert via the same path the reconciler will compare against.
    doc = fitz.open(str(staged))
    if doc.is_encrypted:
        doc.authenticate(_TNG_PASSWORD)
    text = "".join(p.get_text() for p in doc)
    doc.close()
    parser = TnGParser()
    parsed = parser.parse(text)

    stmt = Statement(
        file_hash="annual-test-hash",
        bank="tng",
        source="email",
        filename=_FIXTURE_NAME,
        period_month=parser.extract_period_month(text) or "",
        file_path=_FIXTURE_NAME,  # relative to monkeypatched BACKEND_ROOT
    )
    db.add(stmt)
    db.flush()
    for p in parsed:
        db.add(Transaction(
            statement_id=stmt.id, account_id=acc.id,
            date=p["date"], description=p["description"],
            amount=p["amount"], type=p["type"],
            external_reference=p.get("external_reference"),
        ))
    db.commit()

    result = reconcile_statement(stmt.id, db)
    assert result.ok, f"reconciliation failed: {result.note} (checks_run={result.checks_run})"
    assert "count" in result.checks_run
    assert "statement" in result.checks_run
    assert "per_row" in result.checks_run


def test_reconcile_missing_file_skips_with_note(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.reconciler.BACKEND_ROOT", tmp_path)
    acc = _seed_tng_account(db)
    stmt = Statement(
        file_hash="x", bank="tng", source="email",
        filename="gone.pdf", period_month="", file_path="gone.pdf",
    )
    db.add(stmt); db.commit()
    result = reconcile_statement(stmt.id, db)
    assert result.ok is True
    assert "file missing" in (result.note or "")
    assert result.checks_run == []
