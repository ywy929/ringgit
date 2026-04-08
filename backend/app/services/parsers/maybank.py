import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction

# Matches a transaction line starting with a date; captures the full line
TRANSACTION_LINE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.+)$")

# Matches an amount value anywhere in a string
AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")

STATEMENT_DATE_RE = re.compile(r"Statement Date:\s*(\d{2}/\d{2}/\d{4})")

# Column positions (0-indexed) from the statement header:
#   DATE (0), DESCRIPTION (12), AMOUNT(DR) (49), AMOUNT(CR) (63), BALANCE (77)
_COL_DR = 49
_COL_CR = 63
_COL_BAL = 77


def _parse_amount(s: str) -> float:
    s = s.strip()
    if not s:
        return 0.0
    return float(s.replace(",", ""))


def _extract_column_amount(line: str, start: int, end: int) -> float:
    """Extract a numeric amount from a fixed-width column slice."""
    if len(line) <= start:
        return 0.0
    segment = line[start:end].strip()
    if not segment:
        return 0.0
    m = AMOUNT_RE.search(segment)
    return _parse_amount(m.group()) if m else 0.0


class MaybankParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "maybank"

    def can_parse(self, text: str) -> bool:
        upper = text.upper()
        return "MAYBANK" in upper and "STATEMENT OF ACCOUNT" in upper

    def parse(self, text: str) -> list[ParsedTransaction]:
        transactions: list[ParsedTransaction] = []
        for line in text.splitlines():
            m = TRANSACTION_LINE_RE.match(line)
            if not m:
                continue
            date_raw = m.group(1)
            dt = datetime.strptime(date_raw, "%d/%m/%Y")
            date_str = dt.strftime("%Y-%m-%d")

            # Description spans from col 12 up to (but not including) the DR column
            desc = line[12:_COL_DR].strip()

            dr = _extract_column_amount(line, _COL_DR, _COL_CR)
            cr = _extract_column_amount(line, _COL_CR, _COL_BAL)

            if cr > 0:
                tx_type = "credit"
                amount = cr
            else:
                tx_type = "debit"
                amount = dr

            transactions.append(ParsedTransaction(
                date=date_str, description=desc, amount=amount, type=tx_type,
            ))
        return transactions

    def extract_period_month(self, text: str) -> str:
        match = STATEMENT_DATE_RE.search(text)
        if match:
            dt = datetime.strptime(match.group(1), "%d/%m/%Y")
            return dt.strftime("%Y-%m")
        return ""
