"""Statement reconciliation — runtime guardrail against silent parser drift.

We use PyMuPDF's `Page.find_tables()` as an independent side-channel against
whatever the per-bank regex parser produced. Three checks, each short-circuits:

1. Count cross-check (universal): row counts agree.
2. Statement-level balance (when balance column present): opening + sum == closing.
3. Per-row monotonic (when both adjacent rows have balances): prev + signed == curr.

Failures soft-flag the Statement (caller sets needs_review); inserts are not
rolled back. Skips (encrypted PDFs we cannot open, file missing, unknown bank
format) return ok=True with a note explaining the skip — absence of evidence
is not evidence of failure.
"""
from dataclasses import dataclass, field


@dataclass
class ReconcileResult:
    ok: bool
    note: str | None = None
    checks_run: list[str] = field(default_factory=list)


def _check_count(db_count: int, table_count: int) -> ReconcileResult:
    if db_count != table_count:
        return ReconcileResult(
            ok=False,
            note=f"row count mismatch: db={db_count}, tables={table_count}",
        )
    return ReconcileResult(ok=True)


def _check_statement_balance(rows: list[dict]) -> ReconcileResult:
    balanced = [r for r in rows if r.get("balance") is not None]
    if not balanced:
        return ReconcileResult(ok=True)
    opening = balanced[0]["balance"] - balanced[0]["signed_amount"]
    closing = balanced[-1]["balance"]
    sum_signed = sum(r["signed_amount"] for r in balanced)
    expected = opening + sum_signed
    if abs(expected - closing) > 0.01:
        return ReconcileResult(
            ok=False,
            note=(
                f"closing balance mismatch: opening={opening:.2f}, "
                f"sum={sum_signed:.2f}, expected={closing:.2f}, "
                f"computed={expected:.2f}"
            ),
        )
    return ReconcileResult(ok=True)


def _check_per_row(rows: list[dict]) -> ReconcileResult:
    for i in range(len(rows) - 1):
        prev = rows[i]
        curr = rows[i + 1]
        if prev.get("balance") is None or curr.get("balance") is None:
            continue
        expected = prev["balance"] + curr["signed_amount"]
        if abs(expected - curr["balance"]) > 0.01:
            return ReconcileResult(
                ok=False,
                note=(
                    f"per-row balance mismatch at row {i + 2}: "
                    f"prev={prev['balance']:.2f}, signed_amount={curr['signed_amount']:.2f}, "
                    f"expected={expected:.2f}, got={curr['balance']:.2f}"
                ),
            )
    return ReconcileResult(ok=True)
