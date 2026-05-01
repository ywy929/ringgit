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
