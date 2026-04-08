from sqlalchemy.orm import Session

from app.models import KeywordMapping


class Categorizer:
    def __init__(self, db: Session):
        self.db = db
        self._load_mappings()

    def _load_mappings(self) -> None:
        """Load all keyword mappings, ordered so user mappings come first."""
        all_mappings = (
            self.db.query(KeywordMapping)
            .order_by(KeywordMapping.source.desc())  # "user" before "auto"
            .all()
        )
        self.mappings = [
            (m.keyword_pattern.upper(), m.category_id, m.source)
            for m in all_mappings
        ]

    def categorize(self, description: str) -> int | None:
        """Return category_id for a transaction description, or None if no match."""
        desc_upper = description.upper()
        best_match: tuple[int, int, str] | None = None  # (length, category_id, source)

        for pattern, category_id, source in self.mappings:
            if pattern in desc_upper:
                match_len = len(pattern)
                if best_match is None:
                    best_match = (match_len, category_id, source)
                else:
                    # User mappings always win over auto for same length
                    if source == "user" and best_match[2] == "auto" and match_len >= best_match[0]:
                        best_match = (match_len, category_id, source)
                    elif match_len > best_match[0]:
                        best_match = (match_len, category_id, source)

        return best_match[1] if best_match else None

    def learn(self, description: str, category_id: int) -> None:
        """Save a user correction as a new keyword mapping."""
        pattern = description.strip().upper()
        existing = (
            self.db.query(KeywordMapping)
            .filter_by(keyword_pattern=pattern, source="user")
            .first()
        )
        if existing:
            existing.category_id = category_id
        else:
            self.db.add(KeywordMapping(
                keyword_pattern=pattern,
                category_id=category_id,
                source="user",
            ))
        self.db.commit()
        self._load_mappings()
