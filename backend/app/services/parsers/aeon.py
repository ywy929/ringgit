import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction

# Matches lines starting with a post date "DD/MM/YYYY" followed by trans date
TRANSACTION_LINE_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(.+?)\s{2,}([\d,]+\.\d{2})\s*(CR)?\s*$"
)
STATEMENT_DATE_RE = re.compile(r"Statement Date:\s*(\d{2} \w{3} \d{4})")


class AEONParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "aeon"

    def can_parse(self, text: str) -> bool:
        upper = text.upper()
        return "AEON CREDIT" in upper and "CREDIT CARD STATEMENT" in upper

    def parse(self, text: str) -> list[ParsedTransaction]:
        transactions: list[ParsedTransaction] = []
        for line in text.splitlines():
            m = TRANSACTION_LINE_RE.match(line)
            if not m:
                continue
            # Use trans date (group 2), not post date (group 1)
            date_raw = m.group(2)
            dt = datetime.strptime(date_raw, "%d/%m/%Y")
            date_str = dt.strftime("%Y-%m-%d")

            desc = m.group(3).strip()
            amount = float(m.group(4).replace(",", ""))
            is_credit = m.group(5) is not None

            tx_type = "credit" if is_credit else "debit"

            transactions.append(ParsedTransaction(
                date=date_str, description=desc, amount=amount, type=tx_type,
            ))
        return transactions

    def extract_period_month(self, text: str) -> str:
        match = STATEMENT_DATE_RE.search(text)
        if match:
            dt = datetime.strptime(match.group(1), "%d %b %Y")
            return dt.strftime("%Y-%m")
        return ""
