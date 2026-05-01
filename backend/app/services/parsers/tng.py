"""Touch 'n Go statement parsers.

TnG sends two distinct PDF layouts depending on the source:

1. **Legacy "Customer Transactions Statement"** — from no.reply@addcard.touchngo.com.my.
   Tabular: Trans No, Entry Date+Time, Posted Date, Tran Type (multi-line), Entry Location,
   Entry SP, Exit Location, Exit SP, [Reload Location], Amount, Balance, [Sector].
   Has separate Online and Offline sections.

2. **New "TNG WALLET TRANSACTION HISTORY"** — from ewallet@tngdigital.com.my.
   Per-row: Date, Status, Transaction Type, Reference (split across 4-5 lines),
   Description (1-2 lines, possibly merged with details), Details (datetime or extra ref),
   Amount (RM-prefixed), Wallet Balance (RM-prefixed).
   Inter-row "*This is a system generated email..." footers may interrupt a page break.

`can_parse` matches either format; `parse` dispatches.
"""
import re
from datetime import datetime

from app.services.parsers.base import BaseParser, ParsedTransaction


# Shared
_AMOUNT_RE = re.compile(r"^\d+(?:,\d{3})*\.\d{2}$")

# Legacy format
_LEGACY_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_LEGACY_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_LEGACY_PERIOD_RE = re.compile(r"Transaction Period[\s\S]*?:\s*(\d{2})\s+(\w+)\s+(\d{4})")
_LEGACY_OFFLINE_MARKER = "Offline Card Transactions"
_LEGACY_MARKER = "Customer Transactions Statement"

# New format
_NEW_MARKER = "TNG WALLET TRANSACTION HISTORY"
_NEW_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_RM_RE = re.compile(r"^RM(\d+(?:,\d{3})*\.\d{2})$")
# Period header in new format: "1 January 2025 - 31 January 2025"
_NEW_PERIOD_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})\s*-\s*\d{1,2}\s+\w+\s+\d{4}")
# Reference tokens to drop from descriptions:
_PURE_DIGITS_RE = re.compile(r"^\d+$")  # any pure-digit line is a ref part
# Matches reference codes. All three alternatives require at least one digit
# so pure-letter location/name tokens (THESEIRA, DAMANSARA, PAVLONDM, etc.)
# survive in descriptions:
#   1. 8+ alnum with at least one digit (TNGOW3MY1, MY171114855292106).
#   2. Letters-then-digits run, any length (TNGOW3, RM3 etc. — short ref tail).
#   3. Digits-then-letters run, any length (3MY1, etc.).
_ALNUM_REF_RE = re.compile(
    r"^(?=[A-Z0-9]*\d)[A-Z0-9]{8,}$|^[A-Z]+\d+[A-Z0-9]*$|^\d+[A-Z]+[A-Z0-9]*$"
)
# Datetime in details column (can be standalone or appended to description):
_DETAILS_DATETIME_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+(?:AM|PM)", re.IGNORECASE)
# Footer lines that may appear mid-document at page breaks:
_FOOTER_PATTERNS = (
    "system generated email",
    "do not reply",
    "https://",
    "careline",
    "+603",
)

# Known TnG transaction-type tokens that PyMuPDF splits across lines because
# the source cell wraps. Joining with a space is harmless for words like
# "PLUS - JURU" but wrong for atomic identifiers like "DUITNOW_RECEIVEFROM".
# Add more entries as new split patterns are observed in real PDFs.
_TYPE_REJOIN = (
    ("DUITNOW_RECEI VEFROM", "DUITNOW_RECEIVEFROM"),
)


def is_credit_type(type_text: str) -> bool:
    """Whether a TnG transaction-type string indicates a credit (money in).

    Shared by the parser's per-row classification and the reconciler's
    sign normalization so the two cannot drift apart. Empty / unknown types
    fall through to debit, which is the safer default for accounting.
    """
    if not type_text:
        return False
    upper = type_text.upper().replace(" ", "")
    return (
        upper.startswith("DUITNOW_RECEI")
        or upper.startswith("RECEIVE")
        or upper.startswith("RELOAD")
        or upper.startswith("REFUND")
        or upper.startswith("CASHBACK")
    )


class TnGParser(BaseParser):
    @property
    def bank_id(self) -> str:
        return "tng"

    def can_parse(self, text: str) -> bool:
        return _LEGACY_MARKER in text or _NEW_MARKER in text

    def extract_period_month(self, text: str) -> str:
        # Try the legacy format header first.
        m = _LEGACY_PERIOD_RE.search(text)
        if m:
            try:
                dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
                return dt.strftime("%Y-%m")
            except ValueError:
                pass
        # New format: "1 January 2025 - 31 January 2025" near top.
        m = _NEW_PERIOD_RE.search(text)
        if m:
            try:
                dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
                return dt.strftime("%Y-%m")
            except ValueError:
                pass
        return ""

    def parse(self, text: str) -> list[ParsedTransaction]:
        if _NEW_MARKER in text:
            return self._parse_new_format(text)
        return self._parse_legacy_format(text)

    # ------------------------------------------------------------------
    # Legacy "Customer Transactions Statement" format
    # ------------------------------------------------------------------
    def _parse_legacy_format(self, text: str) -> list[ParsedTransaction]:
        if _LEGACY_OFFLINE_MARKER in text:
            online_text, offline_text = text.split(_LEGACY_OFFLINE_MARKER, 1)
        else:
            online_text, offline_text = text, ""
        return (
            self._parse_legacy_section(online_text)
            + self._parse_legacy_section(offline_text)
        )

    def _parse_legacy_section(self, text: str) -> list[ParsedTransaction]:
        lines = text.splitlines()
        anchors = self._find_legacy_anchors(lines)
        transactions: list[ParsedTransaction] = []
        for k, start in enumerate(anchors):
            end = anchors[k + 1] if k + 1 < len(anchors) else len(lines)
            tx = self._extract_legacy_tx(lines[start:end])
            if tx:
                transactions.append(tx)
        return transactions

    def _find_legacy_anchors(self, lines: list[str]) -> list[int]:
        indices: list[int] = []
        for i in range(len(lines) - 2):
            if (
                _LEGACY_DATE_RE.match(lines[i + 1].strip())
                and _LEGACY_TIME_RE.match(lines[i + 2].strip())
            ):
                indices.append(i)
        return indices

    def _extract_legacy_tx(self, chunk: list[str]) -> ParsedTransaction | None:
        if len(chunk) < 6:
            return None
        date_match = _LEGACY_DATE_RE.match(chunk[1].strip())
        if not date_match:
            return None
        date_str = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
        # chunk[0] is the Trans No anchor — TnG's per-transaction unique ID.
        external_reference = chunk[0].strip() or None

        # Track positions of amount lines so we can ignore everything AFTER the
        # last amount (the trailing Sector field, page numbers, etc.).
        amount_positions = [
            (i, ln.strip()) for i, ln in enumerate(chunk[5:], start=5)
            if _AMOUNT_RE.match(ln.strip())
        ]
        if not amount_positions:
            return None
        amount_val = float(amount_positions[0][1].replace(",", ""))
        last_amount_idx = amount_positions[-1][0]

        chunk_text_lower = " ".join(chunk).lower()
        tx_type = "credit" if "reload" in chunk_text_lower else "debit"

        # Description spans chunk[5:last_amount_idx] — anything after the last
        # decimal is structural trailer (Sector code, next-page number).
        skip_lines = {chunk[i].strip() for i in range(min(5, len(chunk)))}
        sp_re = re.compile(r"^[A-Z0-9]{2,5}_[A-Z0-9]+$")
        desc_parts: list[str] = []
        prev = None
        for ln in chunk[5:last_amount_idx]:
            stripped = ln.strip()
            if not stripped:
                continue
            if stripped in skip_lines:
                continue
            if _AMOUNT_RE.match(stripped):
                continue
            if sp_re.match(stripped):
                continue
            if "End of the statement" in stripped:
                continue
            if stripped.isdigit():
                continue
            # Drop consecutive identical tokens (e.g. "OTA-TNGD" repeated as
            # Entry/Exit/Reload Location of the same Reload transaction).
            if stripped == prev:
                continue
            desc_parts.append(stripped)
            prev = stripped
        description = re.sub(r"\s+", " ", " ".join(desc_parts)).strip()

        tx: ParsedTransaction = ParsedTransaction(
            date=date_str,
            description=description[:200] if description else "TnG transaction",
            amount=abs(amount_val),
            type=tx_type,
        )
        if external_reference:
            tx["external_reference"] = external_reference  # type: ignore[typeddict-unknown-key]
        return tx

    # ------------------------------------------------------------------
    # New "TNG WALLET TRANSACTION HISTORY" format
    # ------------------------------------------------------------------
    def _parse_new_format(self, text: str) -> list[ParsedTransaction]:
        # Drop footer lines that interrupt page breaks before searching for
        # transaction anchors — keeps the chunk-walk-back from spanning footers.
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if not self._is_footer_line(ln)]

        # Each transaction ends with two consecutive RM-prefixed lines:
        # the transaction Amount and the Wallet Balance.
        pair_starts = [
            i for i in range(len(lines) - 1)
            if _RM_RE.match(lines[i]) and _RM_RE.match(lines[i + 1])
        ]

        transactions: list[ParsedTransaction] = []
        last_date_idx = -1
        for amount_idx in pair_starts:
            # Walk backward from the amount to find the transaction's date line.
            date_idx = None
            for j in range(amount_idx - 1, last_date_idx, -1):
                if _NEW_DATE_RE.match(lines[j]):
                    date_idx = j
                    break
            if date_idx is None:
                continue
            chunk = lines[date_idx:amount_idx + 2]
            tx = self._extract_new_format_tx(chunk)
            if tx:
                transactions.append(tx)
            last_date_idx = amount_idx + 1
        return transactions

    def _is_footer_line(self, line: str) -> bool:
        lower = line.lower()
        return any(p in lower for p in _FOOTER_PATTERNS)

    def _extract_new_format_tx(self, chunk: list[str]) -> ParsedTransaction | None:
        if len(chunk) < 4:
            return None
        date_match = _NEW_DATE_RE.match(chunk[0])
        if not date_match:
            return None
        day, month, year = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
        date_str = f"{year:04d}-{month:02d}-{day:02d}"

        rm_lines = [ln for ln in chunk if _RM_RE.match(ln)]
        if len(rm_lines) < 2:
            return None
        amount_val = float(_RM_RE.match(rm_lines[0]).group(1).replace(",", ""))

        # Reference: concat of all ref-pattern lines (the things we filter from
        # description). Order in the source PDF is stable per transaction so
        # the concatenation is also stable.
        ref_parts = [
            ln for ln in chunk[1:]
            if _PURE_DIGITS_RE.match(ln) or _ALNUM_REF_RE.match(ln)
        ]
        external_reference = "|".join(ref_parts) if ref_parts else None

        # Credit detection: check the TYPE column specifically, not the whole
        # chunk. (A "Payment" tx with "Card Reload" in its description is a
        # debit, not a credit — the user paid to reload another card.)
        # The TYPE column is chunk[2] in normal cases, with chunk[3] joined
        # for the DUITNOW_RECEI/VEFROM line-split.
        type_text = chunk[2] if len(chunk) > 2 else ""
        if len(chunk) > 3 and chunk[2].upper() == "DUITNOW_RECEI":
            type_text = chunk[2] + chunk[3]
        tx_type = "credit" if is_credit_type(type_text) else "debit"

        # Description: keep human-readable lines (transaction type, merchant/location).
        # Drop reference IDs, RM amounts, "Success" status, and embedded datetimes.
        desc_parts: list[str] = []
        for ln in chunk[1:]:
            if not ln or ln == "Success":
                continue
            if _RM_RE.match(ln):
                continue
            if _PURE_DIGITS_RE.match(ln):
                continue  # 11-digit ref parts, 3-digit suffixes, etc.
            if _ALNUM_REF_RE.match(ln):
                continue  # TNGOW3MY1, MY171114855292106, etc.
            # Strip embedded "DD/MM/YYYY HH:MM AM/PM" details from descriptions.
            cleaned = _DETAILS_DATETIME_RE.sub("", ln).strip()
            # Refs sometimes glue onto the description without a separator
            # ("CASE ZONE (SUNWAY CARNIVAL)202508112112128001..."). Strip any
            # trailing run of 10+ pure digits — real merchant names virtually
            # never end with that many consecutive digits.
            cleaned = re.sub(r"\d{10,}$", "", cleaned).strip()
            # Whitespace-separated alnum-with-digit refs (e.g.,
            # "DuitNow QR TNGD 20251102101", "MERCHANT TNGOW3MY1"). Require
            # at least one digit in the token so uppercase location names
            # like "DAMANSARA" or "PAVLONDM" stay.
            m = re.search(r"\s+([A-Z0-9]{8,})$", cleaned)
            if m and any(c.isdigit() for c in m.group(1)):
                cleaned = cleaned[:m.start()].strip()
            if not cleaned:
                continue
            # If the cleaned line is now just a numeric or alnum ref residue, skip.
            if _PURE_DIGITS_RE.match(cleaned) or _ALNUM_REF_RE.match(cleaned):
                continue
            desc_parts.append(cleaned)

        description = re.sub(r"\s+", " ", " ".join(desc_parts)).strip()
        for split, joined in _TYPE_REJOIN:
            description = description.replace(split, joined)

        tx: ParsedTransaction = ParsedTransaction(
            date=date_str,
            description=description[:200] if description else "TnG transaction",
            amount=amount_val,
            type=tx_type,
        )
        if external_reference:
            tx["external_reference"] = external_reference  # type: ignore[typeddict-unknown-key]
        return tx
