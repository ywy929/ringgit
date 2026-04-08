from sqlalchemy.orm import Session

from app.models import Category, KeywordMapping

DEFAULT_CATEGORIES = [
    "Food & Dining", "Groceries", "Transport", "Fuel", "Utilities",
    "Entertainment", "Shopping", "Healthcare", "Insurance", "Loan Repayment",
    "Rent", "Subscriptions", "Cash Withdrawal", "Internal Transfer",
    "Income", "Uncategorized",
]

DEFAULT_KEYWORDS = {
    "Food & Dining": [
        "GRABFOOD", "FOODPANDA", "MCDONALD", "KFC", "PIZZA", "NASI", "WARUNG",
        "RESTORAN", "RESTAURANT", "CAFE", "KOPITIAM", "MAMAK", "SUSHI",
        "STARBUCKS", "SUBWAY", "BURGER", "DOMINO", "DAGING", "AYAM",
    ],
    "Groceries": [
        "JAYA GROCER", "LOTUS", "MYDIN", "99 SPEEDMART", "AEON BIG",
        "VILLAGE GROCER", "COLD STORAGE", "TESCO", "GIANT", "ECONSAVE",
        "PASAR", "MARKET", "GROCERY",
    ],
    "Transport": [
        "GRAB ", "GOJEK", "PARKING", "TOLL", "LRT", "MRT", "RAPIDKL",
        "TOUCH N GO", "TNG", "PLUS HIGHWAY", "SMART TAG",
    ],
    "Fuel": [
        "SHELL", "PETRONAS", "PETRON", "CALTEX", "BHP",
    ],
    "Utilities": [
        "TNB", "TENAGA", "SYABAS", "IWK", "INDAH WATER", "UNIFI", "MAXIS",
        "DIGI", "CELCOM", "ASTRO", "TM NET", "TIME FIBRE",
    ],
    "Entertainment": [
        "NETFLIX", "SPOTIFY", "CINEMA", "GSC", "TGV", "DISNEY",
        "YOUTUBE", "STEAM", "PLAYSTATION", "NINTENDO",
    ],
    "Shopping": [
        "SHOPEE", "LAZADA", "AMAZON", "ZALORA", "UNIQLO", "H&M",
        "MR DIY", "IKEA", "DAISO",
    ],
    "Healthcare": [
        "PHARMACY", "GUARDIAN", "WATSONS", "CLINIC", "HOSPITAL",
        "FARMASI", "DENTAL", "DOCTOR",
    ],
    "Insurance": [
        "INSURANCE", "PRUDENTIAL", "AIA", "GREAT EASTERN", "ALLIANZ",
        "TAKAFUL", "ZURICH",
    ],
    "Loan Repayment": [
        "LOAN", "INSTALMENT", "PINJAMAN", "HIRE PURCHASE", "ANSURAN",
    ],
    "Rent": [
        "RENT", "SEWA", "RENTAL",
    ],
    "Subscriptions": [
        "SUBSCRIPTION", "PREMIUM", "APPLE.COM", "GOOGLE PLAY",
        "MICROSOFT", "ADOBE", "CHATGPT",
    ],
    "Cash Withdrawal": [
        "ATM WITHDRAWAL", "CASH W/D", "ATM W/D", "CASH WITHDRAWAL",
        "PENGELUARAN TUNAI",
    ],
    "Income": [
        "SALARY", "GAJI", "GIRO CREDIT", "PAYROLL", "BONUS", "DIVIDEN",
        "DIVIDEND", "INTEREST CREDIT",
    ],
}


def seed_database(db: Session) -> None:
    existing = db.query(Category).first()
    if existing:
        return

    categories = {}
    for name in DEFAULT_CATEGORIES:
        cat = Category(name=name, is_default=True)
        db.add(cat)
        db.flush()
        categories[name] = cat

    for cat_name, keywords in DEFAULT_KEYWORDS.items():
        cat = categories.get(cat_name)
        if not cat:
            continue
        for kw in keywords:
            db.add(KeywordMapping(keyword_pattern=kw, category_id=cat.id, source="auto"))

    db.commit()
