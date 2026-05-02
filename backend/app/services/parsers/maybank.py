"""Maybank savings account statement parser.

Maybank statements have evolved across two eras:

  - **Pre-September 2018 (GST era):** includes a `JENIS GST / GST TYPE`
    column with codes like `SR` (standard rated), `ES` (exempt supply), `ZR`
    (zero rated). Footer has explicit `ENDING BALANCE :` / `TOTAL CREDIT :` /
    `TOTAL DEBIT :` summary.
  - **Post-September 2018 (post-GST):** GST column dropped after Malaysia
    abolished GST and replaced it with SST. Footer no longer has the
    explicit ending-balance trio.

Both eras share the same per-transaction structure:

    DD/MM/YY            <- date anchor (line by itself, 2-digit year)
    <TYPE LABEL>        <- e.g., "TRANSFER FROM A/C", "DEBIT ADVICE     SR"
    [SR]                <- GST column line (old format only, optional)
    <amount><sign>      <- e.g., "442.00-" (debit), "500.00+" (credit)
    <balance>           <- running statement balance (no sign suffix)
    [   <detail 1>]     <- 0..N indented detail lines (merchant, references)
    [   <detail 2>]
    ...

The parser anchors on date lines and walks forward within each chunk to
find the first signed-amount line. The optional GST line in old-format
statements falls between the type label and the amount, and is naturally
skipped because it doesn't match the signed-amount regex.
"""
import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction


# A line containing only `DD/MM/YY`.
_DATE_LINE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
# A line containing only an amount with sign suffix: `442.00-` or `500.00+`.
_SIGNED_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}[+-]$")
# A line containing only a balance (no sign suffix).
_BALANCE_RE = re.compile(r"^[\d,]+\.\d{2}$")
# Statement Date label (trilingual block); we match the English label and walk
# forward to the next DD/MM/YY-only line.
_STATEMENT_DATE_RE = re.compile(
    r"STATEMENT DATE\s*\n\s*:\s*\n(\d{2}/\d{2}/\d{2})"
)

# Transaction-section terminators (any of these ends the transaction stream).
_END_MARKERS = (
    "ENDING BALANCE :",
    "TARIKH PENYATA",          # statement-date block (appears after txs in the layout)
    "TERMS AND CONDITION",
    "Malayan Banking Berhad",
)


class MaybankParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "maybank"

    def can_parse(self, text: str) -> bool:
        # Two-marker strict check: the bank name AND the BM transaction-section
        # header. Just the word "MAYBANK" is too weak (it may appear in
        # unrelated banks' marketing or in cross-bank reference data).
        return "Malayan Banking Berhad" in text and "URUSNIAGA AKAUN" in text

    def extract_period_month(self, text: str) -> str:
        m = _STATEMENT_DATE_RE.search(text)
        if not m:
            return ""
        try:
            dt = datetime.strptime(m.group(1), "%d/%m/%y")
            return dt.strftime("%Y-%m")
        except ValueError:
            return ""

    def parse(self, text: str) -> list[ParsedTransaction]:
        lines = text.splitlines()

        # Find the start of the transactions section: the line right after
        # `BEGINNING BALANCE` (which is followed by an amount line we skip).
        start_idx = None
        for i, ln in enumerate(lines):
            if ln.strip() == "BEGINNING BALANCE":
                start_idx = i + 2  # skip the BEGINNING BALANCE line and its amount
                break
        if start_idx is None:
            return []

        # Find the end: first occurrence of any END_MARKER after start_idx.
        end_idx = len(lines)
        for i in range(start_idx, len(lines)):
            stripped = lines[i].strip()
            if any(stripped.startswith(m) for m in _END_MARKERS):
                end_idx = i
                break

        section = lines[start_idx:end_idx]

        # Find anchor indices (date-only lines) within the section.
        anchors: list[int] = []
        for i, ln in enumerate(section):
            if _DATE_LINE_RE.match(ln.strip()):
                anchors.append(i)

        transactions: list[ParsedTransaction] = []
        for k, start in enumerate(anchors):
            end = anchors[k + 1] if k + 1 < len(anchors) else len(section)
            tx = self._extract_tx(section[start:end])
            if tx:
                transactions.append(tx)
        return transactions

    def _extract_tx(self, chunk: list[str]) -> ParsedTransaction | None:
        if len(chunk) < 4:
            return None

        # chunk[0] = date line.
        date_str = chunk[0].strip()
        try:
            dt = datetime.strptime(date_str, "%d/%m/%y")
        except ValueError:
            return None
        iso_date = dt.strftime("%Y-%m-%d")

        # chunk[1] = type label (first non-empty line after the date).
        # In old-format statements the type label may include an inline GST tag
        # (e.g., "DEBIT ADVICE     SR"). We preserve it as-is.
        type_label = chunk[1].strip()
        if not type_label:
            return None

        # Walk forward from chunk[2] to find the first signed-amount line.
        # In old-format statements, a standalone "SR" GST line may appear
        # between the type label and the amount; it doesn't match the
        # signed-amount regex, so we skip past it.
        signed_idx = None
        for i in range(2, len(chunk)):
            if _SIGNED_AMOUNT_RE.match(chunk[i].strip()):
                signed_idx = i
                break
        if signed_idx is None:
            return None

        signed_line = chunk[signed_idx].strip()
        sign = signed_line[-1]  # '+' or '-'
        amount = float(signed_line[:-1].replace(",", ""))
        tx_type = "credit" if sign == "+" else "debit"

        # Balance line: must immediately follow the signed amount.
        if signed_idx + 1 >= len(chunk):
            return None
        balance_line = chunk[signed_idx + 1].strip()
        if not _BALANCE_RE.match(balance_line):
            return None

        # Detail lines: everything after the balance line, leading whitespace
        # stripped, empty lines dropped.
        detail_lines = [ln.strip() for ln in chunk[signed_idx + 2:] if ln.strip()]

        if detail_lines:
            description = f"{type_label} - {' '.join(detail_lines)}"
        else:
            description = type_label
        # Collapse internal whitespace runs (the "DEBIT ADVICE     SR" type
        # label has multiple spaces inside it).
        description = re.sub(r"\s+", " ", description).strip()

        return ParsedTransaction(
            date=iso_date,
            description=description[:200] if description else "Maybank transaction",
            amount=amount,
            type=tx_type,
        )
