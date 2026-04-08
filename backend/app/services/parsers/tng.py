import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction

# Matches "01/04/2026 09:15" at the start of a line
TRANSACTION_LINE_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2})\s+(.+?)\s{2,}([+-][\d,]+\.\d{2})\s*$"
)
PERIOD_RE = re.compile(r"Period:\s*(\w+)\s+(\d{4})")


class TnGParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "tng"

    def can_parse(self, text: str) -> bool:
        upper = text.upper()
        return "TOUCH" in upper and "GO" in upper and ("WALLET" in upper or "EWALLET" in upper)

    def parse(self, text: str) -> list[ParsedTransaction]:
        transactions: list[ParsedTransaction] = []
        for line in text.splitlines():
            m = TRANSACTION_LINE_RE.match(line)
            if not m:
                continue
            date_raw = m.group(1)
            dt = datetime.strptime(date_raw, "%d/%m/%Y %H:%M")
            date_str = dt.strftime("%Y-%m-%d")

            desc = m.group(2).strip()
            amount_raw = m.group(3).replace(",", "")
            amount_val = float(amount_raw)

            if amount_val > 0:
                tx_type = "credit"
            else:
                tx_type = "debit"

            transactions.append(ParsedTransaction(
                date=date_str, description=desc, amount=abs(amount_val), type=tx_type,
            ))
        return transactions

    def extract_period_month(self, text: str) -> str:
        match = PERIOD_RE.search(text)
        if match:
            month_name = match.group(1)
            year = match.group(2)
            dt = datetime.strptime(f"{month_name} {year}", "%B %Y")
            return dt.strftime("%Y-%m")
        return ""
