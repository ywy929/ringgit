import logging
from unittest.mock import patch

from app.models import Account
from app.routers.email import _process_fetched_pdf


class _SilentParser:
    bank_id = "maybank"
    def can_parse(self, text): return True
    def parse(self, text): return []
    def extract_period_month(self, text): return "2026-04"


def test_zero_parse_from_long_text_emits_warning(db, caplog):
    db.add(Account(name="A", bank="maybank", type="savings"))
    db.commit()

    long_text = "MAYBANK STATEMENT OF ACCOUNT " * 50
    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value=long_text
    ), caplog.at_level(logging.WARNING, logger="app.routers.email"):
        mock_reg.detect_bank.return_value = _SilentParser()
        _process_fetched_pdf("a.pdf", b"%PDF-1.4 fake", db, "u@g.com")

    matching = [r for r in caplog.records if "returned 0 transactions" in r.getMessage()]
    assert len(matching) == 1
    assert "maybank" in matching[0].getMessage()


def test_zero_parse_from_short_text_does_not_warn(db, caplog):
    db.add(Account(name="A", bank="maybank", type="savings"))
    db.commit()

    with patch("app.routers.email.registry") as mock_reg, patch(
        "app.routers.email._extract_text_from_pdf", return_value="short"
    ), caplog.at_level(logging.WARNING, logger="app.routers.email"):
        mock_reg.detect_bank.return_value = _SilentParser()
        _process_fetched_pdf("a.pdf", b"%PDF-1.4 fake", db, "u@g.com")

    matching = [r for r in caplog.records if "returned 0 transactions" in r.getMessage()]
    assert len(matching) == 0
