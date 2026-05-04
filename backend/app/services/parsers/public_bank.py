"""Public Bank Moneyplus Savings Account statement parser.

Real Public Bank PDFs flatten through PyMuPDF as line-by-line tokens with
the debit/credit columns collapsed (no positional info). The parser scopes
work to the section between `Balance From Last Statement` and `Closing
Balance In This Statement`, classifies each line, and walks a state machine
that pairs amount/balance numerics, derives sign from running-balance delta,
and stitches descriptions across page-break carry-forwards.

See docs/superpowers/specs/2026-05-04-public-bank-parser-design.md for the
full architectural rationale.
"""
import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction


# Statement-date block: bilingual header followed by the date on the next line.
_STATEMENT_DATE_RE = re.compile(
    r"Tarikh Penyata / Statement Date\s*\n\s*(\d{2}\s+\w{3}\s+\d{4})"
)


class PublicBankParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "public_bank"

    def can_parse(self, text: str) -> bool:
        # Two-marker strict check. "Public Bank" alone matches AEON's footer
        # disclaimer; we additionally require the savings-account-type line.
        return "Public Bank" in text and "Moneyplus Savings Account" in text

    def extract_period_month(self, text: str) -> str:
        m = _STATEMENT_DATE_RE.search(text)
        if not m:
            return ""
        try:
            dt = datetime.strptime(m.group(1), "%d %b %Y")
            return dt.strftime("%Y-%m")
        except ValueError:
            return ""

    def parse(self, text: str) -> list[ParsedTransaction]:
        # Implemented in Task 4.
        return []
