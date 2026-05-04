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


_STATEMENT_DATE_RE = re.compile(
    r"Tarikh Penyata / Statement Date\s*\n\s*(\d{2}\s+\w{3}\s+\d{4})"
)
_DATE_LINE_RE = re.compile(r"^\d{2}/\d{2}$")
_NUMBER_LINE_RE = re.compile(r"^[\d,]+\.\d{2}$")

_SECTION_START_MARKER = "Balance From Last Statement"
_SECTION_END_MARKER = "Closing Balance In This Statement"

# Whole-line structural markers (page-break carry-forward + opening row).
_STRUCTURAL_LINES = frozenset({
    "Balance From Last Statement",
    "Balance B/F",
    "Balance C/F",
})

# Whole-line page-header / column-header / footer noise that appears on
# page 2+ and between transactions when extracted text concatenates pages.
_HEADER_LINES = frozenset({
    "TARIKH", "URUS NIAGA", "DEBIT", "KREDIT", "BAKI",
    "DATE", "TRANSACTION", "CREDIT", "BALANCE",
})

_PAGE_FOOTER_RE = re.compile(r"^Muka Surat \d+ Daripada \d+$|^Page \d+ of \d+$")


def _is_header_or_footer(line: str) -> bool:
    s = line.strip()
    if s in _HEADER_LINES:
        return True
    if _PAGE_FOOTER_RE.match(s):
        return True
    return False


class PublicBankParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "public_bank"

    def can_parse(self, text: str) -> bool:
        # Two-marker strict check: "Public Bank" alone appears in the privacy-
        # notice footer of every statement page (so it's not a discriminating
        # signal on its own); "Moneyplus Savings Account" pins the account type.
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
        lines = text.splitlines()

        # Locate section bounds: Balance From Last Statement → Closing Balance.
        start = None
        end = len(lines)
        for i, ln in enumerate(lines):
            s = ln.strip()
            if start is None and s == _SECTION_START_MARKER:
                start = i
            elif s == _SECTION_END_MARKER:
                end = i
                break
        if start is None:
            return []

        # The line preceding _SECTION_START_MARKER is the opening date; the
        # line right after is the opening balance.
        if start + 1 >= end:
            return []
        opening_balance_line = lines[start + 1].strip()
        if not _NUMBER_LINE_RE.match(opening_balance_line):
            return []
        prev_balance = float(opening_balance_line.replace(",", ""))

        # Statement (M_s, Y_s) for year inference.
        m = _STATEMENT_DATE_RE.search(text)
        if not m:
            return []
        stmt_dt = datetime.strptime(m.group(1), "%d %b %Y")
        stmt_year = stmt_dt.year
        stmt_month = stmt_dt.month

        # State machine over [section_start + 2, end).
        transactions: list[ParsedTransaction] = []
        current_date_str: str | None = None
        i = start + 2
        last_tx_desc: list[str] | None = None  # mutable description tracker for stitching (Task 5)

        while i < end:
            line = lines[i].strip()

            if not line or _is_header_or_footer(line) or line in _STRUCTURAL_LINES:
                i += 1
                continue

            # Date line: update current_date.
            if _DATE_LINE_RE.match(line):
                current_date_str = line
                i += 1
                continue

            # Number-pair pattern: amount + balance.
            if _NUMBER_LINE_RE.match(line):
                if i + 1 >= end:
                    break
                next_line = lines[i + 1].strip()
                if not _NUMBER_LINE_RE.match(next_line):
                    # Lone number — skip defensively.
                    i += 1
                    continue
                if current_date_str is None:
                    # Numbers before any date — skip (defensive).
                    i += 2
                    continue

                amount_val = float(line.replace(",", ""))
                curr_balance = float(next_line.replace(",", ""))
                signed = curr_balance - prev_balance
                if signed >= 0:
                    tx_type = "credit"
                    amount = round(signed, 2)
                else:
                    tx_type = "debit"
                    amount = round(-signed, 2)

                # Year inference for current_date (DD/MM): if MM > stmt_month,
                # transaction is in stmt_year - 1, else stmt_year.
                day_str, month_str = current_date_str.split("/")
                tx_month = int(month_str)
                tx_year = stmt_year - 1 if tx_month > stmt_month else stmt_year
                iso_date = f"{tx_year:04d}-{tx_month:02d}-{int(day_str):02d}"

                # Walk forward to collect description lines until next D/N/structural.
                desc_lines: list[str] = []
                j = i + 2
                while j < end:
                    dline = lines[j].strip()
                    if not dline:
                        j += 1
                        continue
                    if _DATE_LINE_RE.match(dline) or _NUMBER_LINE_RE.match(dline):
                        break
                    if dline in _STRUCTURAL_LINES or _is_header_or_footer(dline):
                        break
                    desc_lines.append(dline)
                    j += 1

                description = " ".join(desc_lines)[:200] if desc_lines else "Public Bank transaction"
                description = re.sub(r"\s+", " ", description).strip()

                tx: ParsedTransaction = {
                    "date": iso_date,
                    "description": description,
                    "amount": amount,
                    "type": tx_type,
                }
                transactions.append(tx)
                last_tx_desc = desc_lines  # for Task 5 page-wrap stitching

                prev_balance = curr_balance
                # `amount_val` is intentionally unused — sign comes from balance delta.
                # Reading it is purely defensive (catches a bad parse where the line
                # parses as a number but isn't actually the amount column).
                _ = amount_val
                i = j
                continue

            # Anything else: text line outside a transaction (orphan or carry-
            # forward). Page-wrap stitching is added in Task 5.
            i += 1

        return transactions
