"""Replay a saved PDF through the parser registry.

Usage: python scripts/replay_statement.py <path-to-pdf>

Exits 0 if >=1 transaction parsed, 1 otherwise. Useful for iterating on a
parser's regexes without re-fetching from Gmail.
"""
import sys
from pathlib import Path

# Allow running this script directly from anywhere inside the backend dir.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # PyMuPDF

from app.services.parser_registry import ParserRegistry


def _extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def main(pdf_path: Path) -> int:
    text = _extract_text(pdf_path)
    registry = ParserRegistry()
    parser = registry.detect_bank(text)
    if parser is None:
        print(f"no parser matched for {pdf_path}")
        print(f"extracted text length: {len(text)} chars")
        print(f"first 200 chars: {text[:200]!r}")
        return 1

    bank = parser.bank_id
    period = parser.extract_period_month(text)
    transactions = parser.parse(text)

    print(f"bank detected: {bank}")
    print(f"period_month: {period}")
    print(f"transactions parsed: {len(transactions)}")
    print("first 5:")
    for t in transactions[:5]:
        date = t.get("date") if isinstance(t, dict) else t.date
        desc = t.get("description") if isinstance(t, dict) else t.description
        amount = t.get("amount") if isinstance(t, dict) else t.amount
        ttype = t.get("type") if isinstance(t, dict) else t.type
        print(f"  {date}  {desc[:30]:30s}  {amount:>10.2f}  {ttype}")

    return 0 if len(transactions) > 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/replay_statement.py <path-to-pdf>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
