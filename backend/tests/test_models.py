from app.models import Account, Category, KeywordMapping, Budget, Statement, Transaction


def test_create_account(db):
    acc = Account(name="Maybank Savings", bank="maybank", type="savings")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    assert acc.id is not None
    assert acc.bank == "maybank"


def test_create_category(db):
    cat = Category(name="Food & Dining", is_default=True)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    assert cat.id is not None
    assert cat.is_default is True


def test_create_keyword_mapping(db):
    cat = Category(name="Fuel", is_default=True)
    db.add(cat)
    db.commit()

    km = KeywordMapping(keyword_pattern="SHELL", category_id=cat.id, source="user")
    db.add(km)
    db.commit()
    db.refresh(km)
    assert km.category_id == cat.id
    assert km.source == "user"


def test_create_statement(db):
    stmt = Statement(
        file_hash="abc123",
        bank="maybank",
        source="manual",
        filename="stmt.pdf",
        period_month="2026-04",
    )
    db.add(stmt)
    db.commit()
    db.refresh(stmt)
    assert stmt.id is not None


def test_duplicate_statement_hash_rejected(db):
    import sqlalchemy
    stmt1 = Statement(file_hash="same_hash", bank="maybank", source="manual", filename="a.pdf", period_month="2026-04")
    stmt2 = Statement(file_hash="same_hash", bank="cimb", source="email", filename="b.pdf", period_month="2026-04")
    db.add(stmt1)
    db.commit()
    db.add(stmt2)
    try:
        db.commit()
        assert False, "Should have raised IntegrityError"
    except sqlalchemy.exc.IntegrityError:
        db.rollback()


def test_create_transaction(db):
    acc = Account(name="Maybank Savings", bank="maybank", type="savings")
    cat = Category(name="Food", is_default=True)
    stmt = Statement(file_hash="h1", bank="maybank", source="manual", filename="s.pdf", period_month="2026-04")
    db.add_all([acc, cat, stmt])
    db.commit()

    tx = Transaction(
        statement_id=stmt.id,
        account_id=acc.id,
        date="2026-04-07",
        description="GRABFOOD KL",
        amount=32.50,
        type="debit",
        category_id=cat.id,
        is_recurring=False,
        is_cash_withdrawal=False,
        is_internal_transfer=False,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    assert tx.amount == 32.50
    assert tx.type == "debit"


def test_create_budget(db):
    b = Budget(month="2026-04", target_amount=4000.0)
    db.add(b)
    db.commit()
    db.refresh(b)
    assert b.target_amount == 4000.0
