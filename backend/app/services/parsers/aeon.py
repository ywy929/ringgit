"""AEON Credit Card (BC / AMP VISA CLASSIC) statement parser.

PyMuPDF's `Page.find_tables()` doesn't yield clean per-row data on AEON
statements — the PDF table lacks visible row separators, so all transactions
get mashed into one row per column. We use anchor-based text parsing instead:
each transaction is a chunk anchored by two consecutive `DD MMM YYYY` lines
(Posting Date and Transaction Date).

Per-row layout:
    DD MMM YYYY            <- Posting Date
    DD MMM YYYY            <- Transaction Date
    <Description>          <- one or more lines
    [CR]                   <- standalone "CR" line marks credit (payment/refund)
    <amount>               <- "1,234.56" format

Header rows like "YOUR PREVIOUS STATEMENT BALANCE\\n2,138.72\\n<card> MR NAME"
appear in the description column before the first transaction. They are NOT
date-pair-anchored, so they are naturally skipped by the anchor walk.
"""
import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction


# A line containing only a "DD MMM YYYY" date.
_DATE_LINE_RE = re.compile(r"^(\d{2})\s+(\w{3})\s+(\d{4})$")
# A line containing only a "1,234.56" or "1234.56" amount.
_AMOUNT_LINE_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$")
# Marker for credit (payment / refund) transactions.
_CR_LINE = "CR"


class AEONParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "aeon"

    def can_parse(self, text: str) -> bool:
        # `Total Charges of the Month` is the credit-card billing-cycle concept
        # that distinguishes BC from VP prepaid (which has no payment cycle).
        return "AEON CREDIT SERVICE" in text and "Total Charges of the Month" in text

    def extract_period_month(self, text: str) -> str:
        # Statement Date label (bilingual). The English label comes first;
        # the BM translation is on the next line; the value is the line after.
        m = re.search(
            r"Statement Date[\s\S]*?Tarikh Penyata\s*\n(\d{2})\s+(\w{3})\s+(\d{4})",
            text,
        )
        if not m:
            return ""
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y")
            return dt.strftime("%Y-%m")
        except ValueError:
            return ""

    def parse(self, text: str) -> list[ParsedTransaction]:
        lines = [ln.strip() for ln in text.splitlines()]
        anchors = self._find_anchor_indices(lines)
        transactions: list[ParsedTransaction] = []
        for k, start in enumerate(anchors):
            end = anchors[k + 1] if k + 1 < len(anchors) else len(lines)
            tx = self._extract_tx(lines[start:end])
            if tx:
                transactions.append(tx)
        return transactions

    def _find_anchor_indices(self, lines: list[str]) -> list[int]:
        # Anchor: two consecutive lines, each matching DD MMM YYYY.
        # The anchor index points at the FIRST date (Posting Date).
        indices: list[int] = []
        for i in range(len(lines) - 1):
            if _DATE_LINE_RE.match(lines[i]) and _DATE_LINE_RE.match(lines[i + 1]):
                indices.append(i)
        return indices

    def _extract_tx(self, chunk: list[str]) -> ParsedTransaction | None:
        if len(chunk) < 4:
            return None

        # chunk[0] = Posting Date, chunk[1] = Transaction Date.
        # Use Transaction Date as the user-facing date (when the spend actually occurred).
        date_match = _DATE_LINE_RE.match(chunk[1])
        if not date_match:
            return None
        try:
            dt = datetime.strptime(
                f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)}",
                "%d %b %Y",
            )
        except ValueError:
            return None
        date_str = dt.strftime("%Y-%m-%d")

        # Find the amount: the FIRST line after the date pair matching the
        # amount pattern. Walking BACKWARD picks up footer numbers in the
        # final transaction's chunk (which extends to end-of-text past the
        # transactions section). Forward walk finds the real transaction
        # amount, which immediately follows the description and optional CR.
        amount_idx = None
        for i in range(2, len(chunk)):
            if _AMOUNT_LINE_RE.match(chunk[i]):
                amount_idx = i
                break
        if amount_idx is None:
            return None
        amount_val = float(chunk[amount_idx].replace(",", ""))

        # Type: credit if any line in the chunk is exactly "CR".
        is_credit = any(ln == _CR_LINE for ln in chunk[2:amount_idx])
        tx_type = "credit" if is_credit else "debit"

        # Description: lines between the date pair and the amount, excluding
        # the standalone "CR" line. Joined with spaces, whitespace-collapsed.
        desc_lines = [
            ln for ln in chunk[2:amount_idx]
            if ln and ln != _CR_LINE
        ]
        description = re.sub(r"\s+", " ", " ".join(desc_lines)).strip()

        tx: ParsedTransaction = ParsedTransaction(
            date=date_str,
            description=description[:200] if description else "AEON transaction",
            amount=amount_val,
            type=tx_type,
        )
        return tx
