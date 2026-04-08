from app.models import Account, Category, Statement, Transaction
from app.services.transfer_detector import TransferDetector


def _setup_accounts(db):
    acc_maybank = Account(name="Maybank Savings", bank="maybank", type="savings")
    acc_tng = Account(name="TnG Wallet", bank="tng", type="ewallet")
    db.add_all([acc_maybank, acc_tng])
    db.flush()
    return acc_maybank, acc_tng


def _setup_statement(db, bank):
    stmt = Statement(file_hash=f"hash_{bank}", bank=bank, source="manual", filename=f"{bank}.pdf", period_month="2026-04")
    db.add(stmt)
    db.flush()
    return stmt


def test_detects_matching_transfer(db):
    acc_m, acc_t = _setup_accounts(db)
    stmt_m = _setup_statement(db, "maybank")
    stmt_t = _setup_statement(db, "tng")

    tx_debit = Transaction(
        statement_id=stmt_m.id, account_id=acc_m.id,
        date="2026-04-05", description="TNG RELOAD",
        amount=100.0, type="debit",
    )
    tx_credit = Transaction(
        statement_id=stmt_t.id, account_id=acc_t.id,
        date="2026-04-05", description="RELOAD FROM MAYBANK",
        amount=100.0, type="credit",
    )
    db.add_all([tx_debit, tx_credit])
    db.commit()

    detector = TransferDetector(db)
    pairs = detector.detect_transfers("2026-04")
    assert len(pairs) == 1
    assert set(pairs[0]) == {tx_debit.id, tx_credit.id}


def test_ignores_different_amounts(db):
    acc_m, acc_t = _setup_accounts(db)
    stmt_m = _setup_statement(db, "maybank")
    stmt_t = _setup_statement(db, "tng")

    tx_debit = Transaction(
        statement_id=stmt_m.id, account_id=acc_m.id,
        date="2026-04-05", description="TNG RELOAD",
        amount=100.0, type="debit",
    )
    tx_credit = Transaction(
        statement_id=stmt_t.id, account_id=acc_t.id,
        date="2026-04-05", description="RELOAD",
        amount=200.0, type="credit",
    )
    db.add_all([tx_debit, tx_credit])
    db.commit()

    detector = TransferDetector(db)
    pairs = detector.detect_transfers("2026-04")
    assert len(pairs) == 0


def test_ignores_same_account(db):
    acc_m, _ = _setup_accounts(db)
    stmt = _setup_statement(db, "maybank")

    tx1 = Transaction(
        statement_id=stmt.id, account_id=acc_m.id,
        date="2026-04-05", description="DEBIT",
        amount=100.0, type="debit",
    )
    tx2 = Transaction(
        statement_id=stmt.id, account_id=acc_m.id,
        date="2026-04-05", description="CREDIT",
        amount=100.0, type="credit",
    )
    db.add_all([tx1, tx2])
    db.commit()

    detector = TransferDetector(db)
    pairs = detector.detect_transfers("2026-04")
    assert len(pairs) == 0


def test_within_2_day_window(db):
    acc_m, acc_t = _setup_accounts(db)
    stmt_m = _setup_statement(db, "maybank")
    stmt_t = _setup_statement(db, "tng")

    tx_debit = Transaction(
        statement_id=stmt_m.id, account_id=acc_m.id,
        date="2026-04-05", description="TRANSFER",
        amount=500.0, type="debit",
    )
    tx_credit = Transaction(
        statement_id=stmt_t.id, account_id=acc_t.id,
        date="2026-04-08", description="RECEIVED",
        amount=500.0, type="credit",
    )
    db.add_all([tx_debit, tx_credit])
    db.commit()

    detector = TransferDetector(db)
    pairs = detector.detect_transfers("2026-04")
    assert len(pairs) == 0


def test_apply_transfers_flags_transactions(db):
    acc_m, acc_t = _setup_accounts(db)
    stmt_m = _setup_statement(db, "maybank")
    stmt_t = _setup_statement(db, "tng")

    tx_debit = Transaction(
        statement_id=stmt_m.id, account_id=acc_m.id,
        date="2026-04-05", description="TNG RELOAD",
        amount=100.0, type="debit",
    )
    tx_credit = Transaction(
        statement_id=stmt_t.id, account_id=acc_t.id,
        date="2026-04-05", description="RELOAD",
        amount=100.0, type="credit",
    )
    db.add_all([tx_debit, tx_credit])
    db.commit()

    detector = TransferDetector(db)
    detector.apply_transfers("2026-04")

    db.refresh(tx_debit)
    db.refresh(tx_credit)
    assert tx_debit.is_internal_transfer is True
    assert tx_credit.is_internal_transfer is True
    assert tx_debit.linked_transfer_id == tx_credit.id
    assert tx_credit.linked_transfer_id == tx_debit.id
