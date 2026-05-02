# Vault Documentation Refresh — Design

**Date:** 2026-05-02
**Status:** Approved (pending spec review before plan)
**Goal:** Refresh `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer` to reflect current shipped state (April design → May implementation gap), and capture the load-bearing architectural decisions made during implementation as ADRs in the `decisions/` folder (currently empty).

## Context

The vault folder for this project was last touched 2026-04-07 during the design phase. About 4 weeks of implementation has shipped since (TnG parser, AEON Credit Card parser, Maybank Savings parser, reconciliation layer, Gmail multi-account fetch with cursor handling, encrypted-PDF stub pattern, per-sender env-var passwords, reprocess scripts, real-fixture testing pattern). The vault doc is now stale enough that future-me glancing at it gets a misleading picture of the project.

Two distinct documentation needs:
1. **Make-it-accurate** — current snapshot of what's shipped vs not. Vault stays at status/dashboard altitude; implementation lives in the project repo's `docs/superpowers/specs/` and `docs/superpowers/plans/`.
2. **Capture-the-journey** — preserve reasoning for non-obvious architectural choices that future-me would benefit from knowing before reversing them. The `decisions/` folder was set up but never populated; it's the right home for ADRs.

The vault's `CLAUDE.md` permits personal projects under `projects/` to follow their own internal conventions (ADR-NNN, SPEC-NNN). SPEC-001 already exists with frontmatter + revision-history table; ADRs will follow the same conventions.

## Scope Exclusions

- **Plans folder edits.** The 3 historical plan docs from 2026-04-07 stay as-is — they're the original-intent record, not a current-state document.
- **Assets folder edits.** Design mockups (HTML files) are a separate concern with their own update cadence.
- **Tactical decision ADRs.** Per-sender env vars, subagent-driven workflow, real-fixture test gating, and similar tactical choices are recoverable from git log + commit messages or obvious from code structure. Only the 4 load-bearing architectural decisions get ADRs.
- **SPEC-002 or new spec creation.** SPEC-001 is updated in place; no parallel spec.
- **Database/references folders.** Empty in the vault, left empty for future use.
- **Cross-vault sync mechanism.** No automation; this refresh is a manual snapshot. Future updates are ad-hoc as ship-events warrant.

## File Map

### Modified files
- `projects/ringgit-financial-analyzer/index.md` — refresh status, supported banks table, add "Recent shipped" + "Active decisions" sections, update architecture summary
- `projects/ringgit-financial-analyzer/specs/SPEC-001-system-design.md` — Acceptance Criteria becomes shipped-status checklist, per-feature Implementation Notes for divergence callouts, revision history row appended

### New files
- `projects/ringgit-financial-analyzer/decisions/ADR-001-anchor-based-parsing.md`
- `projects/ringgit-financial-analyzer/decisions/ADR-002-reconciliation-as-runtime-guardrail.md`
- `projects/ringgit-financial-analyzer/decisions/ADR-003-file-level-dedup-only.md`
- `projects/ringgit-financial-analyzer/decisions/ADR-004-encrypted-stub-fallback.md`

### Untouched
- `plans/` — 3 historical plan docs from April, no edits
- `assets/` — 14 HTML design mockups, separate concern
- `database/`, `references/` — empty, leave for future

## index.md Update

### Status table
Refresh the existing 4-row table:

| Attribute | Old value | New value |
|---|---|---|
| Phase | Design | Implementation |
| Stack | FastAPI + React (Vite) + SQLite | (unchanged) |
| Owner | Yeow | (unchanged) |
| Started | 2026-04-07 | (unchanged) |

Add new rows:
- **Last shipped:** `2026-05-02 — Maybank savings parser (61 statements, 1076 transactions reconciled)`
- **Branch:** `main`
- **Test count:** 173 passing, 6 skipped (real-fixture tests for fixtures not staged)

### Supported Banks table
Replace the current 6-row "all dedicated" table with current reality:

| Bank/Service | Source | Parser | Reconciled | Notes |
|---|---|---|---|---|
| TnG eWallet | Email + manual | Shipped | Per-row + statement | New format + legacy format both covered |
| AEON Credit (BC) | Email + manual | Shipped | Statement-level (no per-row) | 31 statements reprocessed |
| Maybank Savings | Email + manual | Shipped | Per-row + statement + beg/end | 61 statements, 2 eras (2018 GST + post-2018) |
| AEON Visa Platinum (VP) | Email | Not started | — | 8 stubs as `bank='unknown'` |
| CIMB | Email + manual | Not started | — | No data in inbox yet |
| Public Bank | Email + manual | Not started | — | No data in inbox yet |
| Hong Leong | Email + manual | Not started | — | App-only / different inbox |

### New "Recent shipped" section
Rolling list of last ~5 ship-events with date + 1-line summary. Replaces stale revision-history mindset; gives a recent timeline at a glance:

```markdown
## Recent shipped

- **2026-05-02** — Maybank savings parser (anchor-based, both 2018 GST and 2026 post-GST formats; 61 statements reprocessed; reconciler arm with per-row + statement-level + beginning/ending balance cross-checks)
- **2026-05-02** — Fetch cursor advancement bug fix + reset script + PDF_PASSWORD_MAYBANK wired
- **2026-05-02** — AEON Credit Card (BC) parser + statement-level reconciliation; 31 statements reprocessed
- **2026-05-01** — TnG reprocess + reconciliation layer (find_tables-based)
- **2026-04-18** — Blocking gaps closed (TnG parser hardening, encrypted-stub pattern, persisted file_path)
```

### New "Active decisions" section
Discoverable links to the ADRs from the dashboard:

```markdown
## Active decisions

See `decisions/` folder for full reasoning behind each.

- **[[decisions/ADR-001-anchor-based-parsing|ADR-001]]** — Why anchor-based parsing instead of column-position regex
- **[[decisions/ADR-002-reconciliation-as-runtime-guardrail|ADR-002]]** — Why a reconciliation layer at all (and what it actually catches)
- **[[decisions/ADR-003-file-level-dedup-only|ADR-003]]** — Why no transaction-level dedup for non-TnG banks
- **[[decisions/ADR-004-encrypted-stub-fallback|ADR-004]]** — Why we save bytes for un-decryptable PDFs instead of failing
```

### Architecture summary block
Update the ASCII diagram to reflect what actually exists:
- Add the **Reconciliation Layer** box as a peer to the Parser Registry
- Drop the "6 bank-specific parsers" label (replace with "Per-bank parsers")
- Add an annotation noting `find_tables` is TnG-only; AEON and Maybank use anchor-based text parsing

## SPEC-001 Update

The existing Goals, Non-Goals, Architecture, Data Model, Tech Stack, Constraints sections stay as-is — they're still the original-intent record and remain accurate.

### Acceptance Criteria becomes a shipped-status checklist
Each existing item gets `[x]`, `[~]` (partial), or `[ ]` plus a one-line note when it landed differently:

- `[x] Can upload a password-protected Maybank PDF and see parsed transactions` — *Shipped via per-sender env-var passwords (PDF_PASSWORD_MAYBANK), not the originally planned upload-time dialog.*
- `[~] Auto-detects bank from PDF content without user selection` — *Two-marker text-content check per parser (e.g., Maybank requires both "Malayan Banking Berhad" AND "URUSNIAGA AKAUN"). No image/logo recognition. Confidence-fallback UI not built — unknown PDFs save as encrypted-stub Statements with `bank='unknown'` instead.*
- `[x] Skips duplicate PDFs (same file uploaded twice)` — *SHA-256 file_hash check on Statement insert.*
- `[x] Transactions auto-categorized with bilingual keyword matching`
- `[x] Correcting a category on one transaction improves future auto-categorization`
- `[ ] Internal transfers (bank→ewallet, bank→credit card, bank→bank) detected and excluded from spending totals` — *Not yet implemented.*
- `[x] ATM withdrawals tracked separately with untracked cash gap shown`
- `[x] Dashboard shows monthly income, spending, savings with trend indicators`
- `[x] Budget progress bar reflects current month spending vs target`
- `[x] Gmail fetch retrieves new statement PDFs on app open` — *Multi-account; cursor advances only on attachment-bearing fetches (bug fixed 2026-05-02).*
- `[~] Historical savings trend chart shows 6+ months` — *Data is now available (Maybank backfill provides 8 years); chart UI status not verified at time of this update — re-tick when confirmed.*
- `[x] Recurring transactions flagged with badge`
- `[x] Manual cash transaction entry works`
- `[~] All 6 bank parsers extract transactions correctly from sample PDFs` — *3 of 6 shipped (TnG, AEON BC, Maybank). CIMB, Public Bank, Hong Leong, AEON VP not started.*

### Implementation Notes
Short callouts under the relevant Feature section explaining where reality diverged. Not a rewrite — margin notes only.

Examples:

> **Implementation note** under "PDF Parsing": *Original plan assumed regex-against-column-positions per bank. First fixture-test contact with reality showed PyMuPDF doesn't preserve column positions in extracted text — see [[decisions/ADR-001-anchor-based-parsing|ADR-001]]. All shipped parsers use anchor-based extraction.*

> **Implementation note** under "Auto Bank Detection": *Implemented as a content-based two-marker text check per parser. No image/logo recognition. Confidence-fallback UI not built — unknown PDFs save as encrypted-stub Statements with `bank='unknown'` so the bytes are preserved for later — see [[decisions/ADR-004-encrypted-stub-fallback|ADR-004]].*

> **Implementation note** under "Duplicate Detection": *File-level dedup is the only dedup. The reprocess scripts use DELETE + INSERT for idempotency — see [[decisions/ADR-003-file-level-dedup-only|ADR-003]]. A broad-key `(date, amount, type, description)` dedup was tried in the reprocess scripts and found to silently drop legitimate same-day repeats (toll gates, parking).*

> **New Implementation note section** after "Duplicate Detection": *Reconciliation Layer (not in original spec) — see [[decisions/ADR-002-reconciliation-as-runtime-guardrail|ADR-002]]. Runtime guardrail that re-extracts rows independently from the parser and cross-checks. Each parser dispatches to its own reconciler arm. Caught two real bugs in May (multi-page Maybank, toll-gate dedup).*

### Revision history
Append:

| Date | Author | Changes |
|---|---|---|
| 2026-05-02 | Yeow | Implementation gap-update: ticked Acceptance Criteria, added Implementation Notes where reality diverged, linked new ADRs |

## ADR Format

### Frontmatter convention
Consistent with vault conventions (matches SPEC-001's frontmatter style):

```yaml
---
type: adr
status: accepted   # accepted / proposed / superseded / deprecated
date: 2026-05-02
project: ringgit-financial-analyzer
tags:
  - adr
  - project/ringgit
---
```

### Body template
Michael Nygard-style, kept short:

```markdown
# ADR-NNN: <decision title>

## Context
<1-2 paragraphs: what forces are at play, what problem are we solving>

## Decision
<the choice made, in 1-3 sentences>

## Consequences
<what this enables and what it costs; positive AND negative>

## Alternatives considered
<what we rejected and why — short bullets>

## Notes
<optional: links to specific commits/PRs/specs in the project repo where this manifests>
```

## The 4 ADRs

### ADR-001: Anchor-based parsing

**Context.** The original plan assumed regex-against-column-positions per bank (e.g., "DR amount is at column 49–62, balance at column 77+"). First fixture-test against a real Maybank PDF showed PyMuPDF's text extraction does NOT preserve column positions — text comes out line-by-line with whatever spacing the source PDF was generated with, which varies across bank statement generators and even across pages within one statement. The fictional-sample-tuned column-position parser produced 0 transactions on real data.

**Decision.** Anchor on date lines per bank, walk forward within each chunk to find the signed-amount line and balance line. Each parser's anchor regex is bank-specific (e.g., Maybank: `^DD/MM/YY$`, AEON: two consecutive `^DD MMM YYYY$` lines, TnG: more complex pattern matching).

**Consequences.**
- Tolerates layout drift, era differences (Maybank 2018 GST column vs 2026 post-GST), multi-line descriptions, and page-header repeats in multi-page statements.
- Each parser is bank-specific by design — no shared abstraction. Adding a new bank is "write a new parser file" not "extend a base."
- Forward-walk approach naturally skips optional/inserted lines (e.g., the GST `SR` column line in old Maybank) without explicit branching.
- Couples each parser to its bank's specific anchor pattern; if the bank changes the date format, the anchor breaks.

**Alternatives considered.**
- *Column-position regex* — original plan, rejected after first real-PDF test.
- *PyMuPDF `Page.find_tables()`* — works for TnG (its PDF has visible row separators) but not for AEON or Maybank (no row separators, transactions get mashed into one row per column).
- *OCR fallback* — investigated; not needed because all encountered PDFs decrypt and yield clean text via PyMuPDF.

**Notes.**
- `backend/app/services/parsers/tng.py`, `aeon.py`, `maybank.py`
- Project specs: `docs/superpowers/specs/2026-05-01-tng-reprocess-and-reconciliation-design.md`, `docs/superpowers/specs/2026-05-02-aeon-credit-card-parser-and-reconciliation-design.md`, `docs/superpowers/specs/2026-05-02-maybank-savings-parser-design.md`

---

### ADR-002: Reconciliation as runtime guardrail

**Context.** Parsers can drift silently — a bank changes a header label, PyMuPDF updates its extraction algorithm, a new transaction type doesn't match the existing regex — and unit tests pass while production data is wrong. Synthetic fixtures only cover what the author thought to test. We want runtime evidence that an import is complete and correct, not just a green CI light.

**Decision.** Per-bank dispatch arm in `reconcile_statement` re-extracts transaction rows independently from whatever the per-bank parser produced (TnG via `find_tables`, AEON/Maybank via anchor-based text parsing) and runs three checks: count match, statement-level balance (when balance data is present), per-row balance (when adjacent rows have balances). Bank-specific cross-checks are layered on inline (AEON: vs header Previous/Current; Maybank: vs explicit BEGINNING/ENDING balance markers). Failures soft-flag `Statement.needs_review = True`; inserts are not rolled back. Skips (encrypted PDFs we cannot open, file missing, unknown bank format) return `ok=True` with a note explaining the skip — absence of evidence is not evidence of failure.

**Consequences.**
- Caught two real bugs in May 2026:
  1. Multi-page Maybank: page footer text was being treated as end-of-section, dropping page 2+ transactions silently. Real-fixture test surfaced this.
  2. Broad-key dedup in reprocess script ate legitimate same-day repeats (toll gates, parking) — see ADR-003. Reconciler flagged the count mismatches.
- Duplicates parsing logic per bank (the reconciler's `_extract_rows_from_<bank>` mirrors the parser's `parse`, just emits dict rows instead of `ParsedTransaction` objects). Accepted cost — keeps each module standalone and testable.
- No false positives accepted: the reconciler skips silently if the format is unknown or the file can't be opened, preferring under-flagging over crying wolf.
- The `needs_review` flag is queryable and could be surfaced in the UI as a review queue if that becomes useful.

**Alternatives considered.**
- *Run-the-parser-twice* — no independent signal; just confirms determinism.
- *Compare against bank's running totals only* — misses per-row mismatches that statement-level math papers over.
- *Hash-based check* — would require the bank to expose stable per-tx IDs; most don't.

**Notes.**
- `backend/app/services/reconciler.py`
- The reconciler's three pure check functions (`_check_count`, `_check_statement_balance`, `_check_per_row`) are reusable; bank-specific dispatch arms compose them differently per format.

---

### ADR-003: File-level dedup only (no transaction-level dedup for non-TnG banks)

**Context.** TnG transactions expose `external_reference` IDs in their PDFs, so per-transaction dedup is natural and reliable. AEON and Maybank statements don't expose per-transaction unique IDs — at most they include merchant references in description text, which are inconsistent across transactions and missing entirely on some types (e.g., toll-gate `PRE-AUTH MYDEBIT` charges have no unique identifier in the bank's own statement). The original implementation copy-pasted TnG's dedup pattern to AEON and Maybank using a "broad key" `(date, amount, type, description)` — which silently dropped 6 legitimate same-day same-merchant repeats from the Maybank reprocess (two toll-gate events on March 14 each producing PRE-AUTH/REV-PREAUTH/PAYMENT triplets at RM2.10).

**Decision.** Dedup at the file level only: `Statement.file_hash` (SHA-256) prevents the same PDF from being processed twice via the fetch path. Reprocess scripts use DELETE + INSERT for idempotency (delete all bank-X transactions before re-inserting). No transaction-level dedup for non-TnG banks.

**Consequences.**
- Same-day identical-key transactions correctly preserved (toll gates, parking, identical-amount recurring charges).
- No protection against partial reprocess — but reprocess is a one-shot operation, not exposed in the UI, so this isn't a real risk.
- Architecture is simpler: one less moving part to reason about.
- TnG keeps its `external_reference`-based dedup because it's reliable for that bank.

**Alternatives considered.**
- *Reference-based dedup using description-embedded references* — inconsistent across transaction types; would silently lose data for toll/parking-style transactions that have no embedded reference.
- *Position-in-statement based dedup* — would require parser to emit a sequence number; complicates the data model for negligible benefit.
- *Keep broad-key dedup but make it per-statement only* — would still have within-statement collisions (the toll-gate case).

**Notes.**
- `backend/scripts/reprocess_maybank.py`, `reprocess_aeon.py` — dedup removed.
- `backend/app/models.py` — `Statement.file_hash` UNIQUE constraint is the source-of-truth dedup.
- Project commit: `07f24e4 fix(ringgit): drop reprocess-script broad-key dedup that ate legitimate repeats`

---

### ADR-004: Encrypted-stub fallback

**Context.** PDFs may arrive from senders we haven't configured a password for, or with passwords that have changed. The original fetch path would either: throw the PDF away (data loss), or fail the entire fetch (blocking the rest of the inbox). Neither is acceptable when adding a new sender — the user wants the bytes saved so they can configure the password later, or upload manually.

**Decision.** When a PDF can't be decrypted (no configured password, or configured password fails authentication), save the PDF bytes to `backend/fetched_pdfs/<account>/<hash>.pdf` and create a `Statement` row with `bank='unknown'` and a recoverable `file_path`. The user can either: (a) configure the password in `.env` and re-run a reprocess script, or (b) upload manually with the password via the UI. When the matching parser ships later (e.g., Maybank ships in May 2026 after the AEON parser shipped), the same files become processable via reprocess.

**Consequences.**
- Robust against new banks/senders we haven't configured: bytes are never lost.
- Statements sit as `bank='unknown'` until the user gets around to them. The `bank='unknown'` rows are queryable and could be surfaced in the UI as a backlog if useful.
- The Maybank case in May 2026 was a textbook validation: 61 statements had been sitting as encrypted stubs for weeks before the parser landed; the reprocess script picked them all up cleanly.
- The 8 AEON Visa Platinum (VP) stubs continue to sit as `bank='unknown'` because the VP parser hasn't been written.

**Alternatives considered.**
- *Throw away undecryptable PDFs* — data loss, especially bad for new-sender cases where the password just hasn't been configured yet.
- *Fail the fetch on any undecryptable PDF* — blocks the rest of the inbox, including PDFs we CAN decrypt.
- *Prompt user at fetch time for password* — requires a UI flow, doesn't work for bulk historical backfill.

**Notes.**
- `backend/app/routers/email.py` — fetch path saves bytes + creates Statement before attempting decryption.
- `backend/app/services/parser_registry.py` — unknown bank case writes the encrypted stub.
- Real-world example: 61 Maybank PDFs sat as `bank='unknown'` from initial fetch (April 2026) until the Maybank parser landed (2026-05-02) — zero data loss, recovered via `reprocess_maybank.py`.

## Testing Strategy

This is a documentation-only change with no runtime behavior. "Testing" reduces to a quick visual inspection after writing:

- Markdown lints cleanly in the user's editor (Obsidian)
- Internal `[[wikilinks]]` resolve correctly within the vault
- Frontmatter parses (YAML, no syntax errors)
- The 4 ADR files are discoverable from `index.md` and from SPEC-001's Implementation Notes
- The Acceptance Criteria status is internally consistent (no `[x]` claim that contradicts an Implementation Note)

No automated tests. No commits in the project repo other than this spec.

## Risks & Open Questions

- **Vault is outside the project repo.** Edits won't show up in project git history. The vault has its own version control if any (likely none — personal Obsidian vault). Acceptable: this is by design; the vault is separate from the project's code repo and tracks personal-knowledge altitude, not implementation artifacts.

- **Update cadence going forward.** This refresh is a one-time snapshot. No commitment to update on every ship-event. Future updates are ad-hoc when the gap between vault and reality starts to feel misleading. Acceptable: low-stakes and self-correcting.

- **Implementation Notes in SPEC-001 risk turning into a parallel changelog.** Mitigation: keep notes to 1-2 sentences max, defer detail to ADRs and project repo specs. If a note grows beyond a sentence or two, that's a signal an ADR is the better home.

- **ADR-003 contains a recent-incident reference (toll-gate dedup) that may feel dated in 6 months.** Acceptable: ADRs are time-stamped artifacts; the date in frontmatter contextualizes them. Future readers see "this was written in May 2026 when X happened" not "this is a current claim."

- **SPEC-001's "Acceptance Criteria → status checklist" repurposing.** The original use of Acceptance Criteria was "what must be true for v1 ship." Repurposing it as ongoing status is a slight semantic shift but matches what's actually useful. Alternative would be a separate "Status" section, but that duplicates content and creates a sync problem.
