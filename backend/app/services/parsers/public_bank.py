import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction

# Matches "01/04/26" at the start of a line
TRANSACTION_LINE_RE = re.compile(r"^(\d{2}/\d{2}/\d{2})\s{2,}(.+)$")
AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")
STATEMENT_DATE_RE = re.compile(r"Statement Date:\s*(\d{2}/\d{2}/\d{2})")

# Column positions from the sample:
#   Date (0), Description (10), Debit (48), Credit (63), Balance (78)
_COL_DR = 48
_COL_CR = 63
_COL_BAL = 78


def _parse_amount(s: str) -> float:
    s = s.strip()
    if not s:
        return 0.0
    return float(s.replace(",", ""))


def _extract_column_amount(line: str, start: int, end: int) -> float:
    if len(line) <= start:
        return 0.0
    segment = line[start:end].strip()
    if not segment:
        return 0.0
    m = AMOUNT_RE.search(segment)
    return _parse_amount(m.group()) if m else 0.0


class PublicBankParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "public_bank"

    def can_parse(self, text: str) -> bool:
        upper = text.upper()
        return "PUBLIC BANK" in upper

    def parse(self, text: str) -> list[ParsedTransaction]:
        transactions: list[ParsedTransaction] = []
        for line in text.splitlines():
            m = TRANSACTION_LINE_RE.match(line)
            if not m:
                continue
            date_raw = m.group(1)
            dt = datetime.strptime(date_raw, "%d/%m/%y")
            date_str = dt.strftime("%Y-%m-%d")

            desc = line[10:_COL_DR].strip()

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
            dt = datetime.strptime(match.group(1), "%d/%m/%y")
            return dt.strftime("%Y-%m")
        return ""
