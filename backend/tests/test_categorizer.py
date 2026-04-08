from app.models import Category, KeywordMapping
from app.services.categorizer import Categorizer


def test_matches_default_keyword(db):
    cat = Category(name="Fuel", is_default=True)
    db.add(cat)
    db.flush()
    db.add(KeywordMapping(keyword_pattern="SHELL", category_id=cat.id, source="auto"))
    db.commit()

    c = Categorizer(db)
    result = c.categorize("SHELL TAMAN MELAWATI")
    assert result == cat.id


def test_case_insensitive(db):
    cat = Category(name="Fuel", is_default=True)
    db.add(cat)
    db.flush()
    db.add(KeywordMapping(keyword_pattern="PETRONAS", category_id=cat.id, source="auto"))
    db.commit()

    c = Categorizer(db)
    result = c.categorize("petronas dagangan berhad")
    assert result == cat.id


def test_user_mapping_wins_over_auto(db):
    cat_auto = Category(name="Shopping", is_default=True)
    cat_user = Category(name="Groceries", is_default=True)
    db.add_all([cat_auto, cat_user])
    db.flush()
    db.add(KeywordMapping(keyword_pattern="99", category_id=cat_auto.id, source="auto"))
    db.add(KeywordMapping(keyword_pattern="99 SPEEDMART", category_id=cat_user.id, source="user"))
    db.commit()

    c = Categorizer(db)
    result = c.categorize("99 SPEEDMART AMPANG")
    assert result == cat_user.id


def test_longest_match_wins(db):
    cat_broad = Category(name="Transport", is_default=True)
    cat_specific = Category(name="Food & Dining", is_default=True)
    db.add_all([cat_broad, cat_specific])
    db.flush()
    db.add(KeywordMapping(keyword_pattern="GRAB", category_id=cat_broad.id, source="auto"))
    db.add(KeywordMapping(keyword_pattern="GRABFOOD", category_id=cat_specific.id, source="auto"))
    db.commit()

    c = Categorizer(db)
    result = c.categorize("GRABFOOD A-32891KL")
    assert result == cat_specific.id


def test_no_match_returns_none(db):
    c = Categorizer(db)
    result = c.categorize("RANDOM TRANSACTION XYZ")
    assert result is None


def test_learn_from_correction(db):
    cat = Category(name="Fuel", is_default=True)
    db.add(cat)
    db.commit()

    c = Categorizer(db)
    c.learn("PETRONAS DAGANGAN BERHAD", cat.id)

    mapping = db.query(KeywordMapping).filter_by(source="user").first()
    assert mapping is not None
    assert mapping.keyword_pattern == "PETRONAS DAGANGAN BERHAD"
    assert mapping.category_id == cat.id

    # Now it should match
    result = c.categorize("PETRONAS DAGANGAN BERHAD KL")
    assert result == cat.id
