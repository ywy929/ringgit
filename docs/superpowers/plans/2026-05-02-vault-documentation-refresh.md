# Vault Documentation Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer` to reflect current shipped state and capture 4 load-bearing architectural decisions as ADRs in the previously-empty `decisions/` folder.

**Architecture:** Documentation-only changes in a separate git-tracked vault (Obsidian). 4 ADRs created in `decisions/`, SPEC-001 updated in-place with status checklist + Implementation Notes, `index.md` dashboard refreshed. Three commits (one per logical group: ADRs / SPEC update / index refresh) so each can be rolled back independently. No tests — verification is visual + cross-link resolution.

**Tech Stack:** Markdown + YAML frontmatter, Obsidian wiki-link syntax (`[[file|alias]]`), git for tracking. No code, no test suite.

**Reference spec:** `docs/superpowers/specs/2026-05-02-vault-documentation-refresh-design.md` (committed at 5aa85a9 in the project repo). The spec is the source of truth for all file content — implementers should copy verbatim where exact text is given, and follow the structural outlines (Context/Decision/Consequences/Alternatives/Notes) for the ADR prose sections.

---

## File Map

### New files
- `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-001-anchor-based-parsing.md`
- `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-002-reconciliation-as-runtime-guardrail.md`
- `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-003-file-level-dedup-only.md`
- `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-004-encrypted-stub-fallback.md`

### Modified files
- `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\specs\SPEC-001-system-design.md` — Acceptance Criteria becomes status checklist; per-feature Implementation Notes added inline; revision-history row appended
- `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\index.md` — refresh status table, supported-banks table, architecture summary; add Recent shipped + Active decisions sections

### Untouched
- `plans/` — historical April plans, no edits
- `assets/` — design mockups, separate concern
- `database/`, `references/` — empty, leave as-is

### Working directory note
All work happens in `C:\Users\aquam\PersonalVault`. The vault is its own git repo (separate from the ringgit project repo). Use bash with absolute paths. The shell may auto-reset its `cwd` between commands — always use absolute paths in commands rather than relying on `cd` persistence.

---

## Task 1: Write the 4 ADRs

**Files:**
- Create: `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-001-anchor-based-parsing.md`
- Create: `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-002-reconciliation-as-runtime-guardrail.md`
- Create: `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-003-file-level-dedup-only.md`
- Create: `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-004-encrypted-stub-fallback.md`

All 4 ADRs use the same frontmatter and body template. Frontmatter:

```yaml
---
type: adr
status: accepted
date: 2026-05-02
project: ringgit-financial-analyzer
tags:
  - adr
  - project/ringgit
---
```

Body template (Michael Nygard-style):

```markdown
# ADR-NNN: <decision title>

## Context
<1-2 paragraphs>

## Decision
<the choice in 1-3 sentences>

## Consequences
<positive AND negative>

## Alternatives considered
<short bullets with reasoning>

## Notes
<links to specific files in the project repo>
```

The spec section "## The 4 ADRs" gives the Context, Decision, Consequences, Alternatives, and Notes content for each ADR. The implementer expands the bullet outlines into clean prose — keeping the original substance, not adding new claims.

- [ ] **Step 1: Create `ADR-001-anchor-based-parsing.md`**

Write the file at `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\ADR-001-anchor-based-parsing.md` with the frontmatter above (with `# ADR-001: Anchor-based parsing` as the H1), and prose expansion of the spec's "ADR-001: Anchor-based parsing" section. Final content:

```markdown
---
type: adr
status: accepted
date: 2026-05-02
project: ringgit-financial-analyzer
tags:
  - adr
  - project/ringgit
---

# ADR-001: Anchor-based parsing

## Context

The original plan in SPEC-001 assumed regex-against-column-positions per bank — for example, "the DR amount column starts at character 49, the balance column at character 77." First fixture-test against a real Maybank PDF showed PyMuPDF's text extraction does NOT preserve column positions. Text comes out line-by-line with whatever spacing the source PDF was generated with, which varies across bank statement generators and even across pages within one statement. The fictional-sample-tuned column-position parser produced 0 transactions on real data.

Each bank's statement also has its own quirks: Maybank statements have a 2-era split (pre-September 2018 includes a GST column, post-2018 doesn't); AEON credit card statements have anchor pairs (Posting Date + Transaction Date on consecutive lines); TnG has both a new format and a legacy format with different table structures. A single column-position approach can't tolerate any of this drift.

## Decision

Anchor on date lines per bank, walk forward within each chunk to find the signed-amount line and balance line. Each parser's anchor regex is bank-specific (Maybank: `^DD/MM/YY$`; AEON: two consecutive `^DD MMM YYYY$` lines; TnG: more complex pattern matching specific to its table layouts).

## Consequences

**Positive:**
- Tolerates layout drift across statement generators and PDF versions.
- Handles era differences (Maybank 2018 GST column vs 2026 post-GST) within a single parser via forward-walk that naturally skips optional/inserted lines.
- Multi-line descriptions and page-header repeats in multi-page statements are accommodated by walking forward to known anchors instead of relying on absolute positions.

**Negative:**
- Each parser is bank-specific by design — no shared abstraction. Adding a new bank is "write a new parser file" not "extend a base."
- Couples each parser to its bank's specific anchor pattern. If a bank changes the date format (e.g., Maybank moving from DD/MM/YY to DD-MM-YYYY), the anchor breaks and requires a parser update.

## Alternatives considered

- **Column-position regex** — original plan in SPEC-001. Rejected after the first real-PDF test produced zero transactions.
- **PyMuPDF `Page.find_tables()`** — works for TnG (its PDF has visible row separators that find_tables detects) but not for AEON or Maybank (no row separators; transactions get mashed into one row per column). Used selectively for TnG, abandoned for the others.
- **OCR fallback** — investigated. Not needed because all encountered PDFs decrypt and yield clean text via PyMuPDF.

## Notes

- Parser modules: `backend/app/services/parsers/tng.py`, `backend/app/services/parsers/aeon.py`, `backend/app/services/parsers/maybank.py`
- Project specs documenting the rewrites:
  - `docs/superpowers/specs/2026-05-01-tng-reprocess-and-reconciliation-design.md`
  - `docs/superpowers/specs/2026-05-02-aeon-credit-card-parser-and-reconciliation-design.md`
  - `docs/superpowers/specs/2026-05-02-maybank-savings-parser-design.md`
```

- [ ] **Step 2: Create `ADR-002-reconciliation-as-runtime-guardrail.md`**

Write the file at the path above. Final content:

```markdown
---
type: adr
status: accepted
date: 2026-05-02
project: ringgit-financial-analyzer
tags:
  - adr
  - project/ringgit
---

# ADR-002: Reconciliation as runtime guardrail

## Context

Parsers can drift silently. A bank changes a header label, PyMuPDF updates its extraction algorithm, a new transaction type doesn't match the existing regex — and unit tests pass while production data is wrong. Synthetic fixtures only cover what the author thought to test.

We want runtime evidence that an import is complete and correct, not just a green CI light. The mechanism should be independent of the parser itself (otherwise a parser bug would be invisible to its own self-check) and should fail soft (don't block imports just because we can't verify them).

## Decision

A per-bank dispatch arm in `reconcile_statement` re-extracts transaction rows independently from whatever the per-bank parser produced (TnG via `find_tables`, AEON and Maybank via anchor-based text parsing) and runs three checks: count match, statement-level balance (when balance data is present), and per-row balance (when adjacent rows have balances). Bank-specific cross-checks are layered on inline — AEON validates against header Previous/Current balance values; Maybank validates against the explicit BEGINNING and ENDING balance markers in the statement.

Failures soft-flag `Statement.needs_review = True`; inserts are not rolled back. Skips (encrypted PDFs we cannot open, file missing, unknown bank format) return `ok=True` with a note explaining the skip — absence of evidence is not evidence of failure.

## Consequences

**Positive:**
- Caught two real bugs in May 2026 that synthetic tests missed:
  1. Multi-page Maybank statements: page-footer text was being treated as end-of-section, dropping page-2+ transactions silently. The real-fixture test surfaced this.
  2. Broad-key dedup in the reprocess script ate legitimate same-day repeats (toll gates, parking) — see ADR-003. The reconciler flagged the resulting count mismatches.
- The `needs_review` flag is queryable and could be surfaced in the UI as a review queue if that becomes useful.
- No false positives accepted: the reconciler skips silently if the format is unknown or the file can't be opened, preferring under-flagging over crying wolf.

**Negative:**
- Duplicates parsing logic per bank — the reconciler's `_extract_rows_from_<bank>` mirrors the parser's `parse`, just emitting dict rows instead of `ParsedTransaction` objects. Accepted cost — keeps each module standalone and testable.
- Adds runtime cost on every import (parse twice, plus check arithmetic). Acceptable at current data volumes.

## Alternatives considered

- **Run the parser twice and compare** — provides no independent signal; just confirms determinism.
- **Compare against bank's running totals only** — misses per-row mismatches that statement-level math papers over (e.g., two errors that cancel out).
- **Hash-based check** — would require the bank to expose stable per-transaction IDs; most don't.

## Notes

- Module: `backend/app/services/reconciler.py`
- The three pure check functions (`_check_count`, `_check_statement_balance`, `_check_per_row`) are reusable; bank-specific dispatch arms compose them differently per format.
- See ADR-001 for the parser strategy that the reconciler cross-checks against.
```

- [ ] **Step 3: Create `ADR-003-file-level-dedup-only.md`**

Write the file at the path above. Final content:

```markdown
---
type: adr
status: accepted
date: 2026-05-02
project: ringgit-financial-analyzer
tags:
  - adr
  - project/ringgit
---

# ADR-003: File-level dedup only (no transaction-level dedup for non-TnG banks)

## Context

TnG transactions expose `external_reference` IDs in their PDFs, so per-transaction dedup is natural and reliable. AEON and Maybank statements don't expose per-transaction unique IDs — at most they include merchant references in description text, which are inconsistent across transactions and missing entirely on some types (e.g., toll-gate `PRE-AUTH MYDEBIT` charges have no unique identifier in the bank's own statement).

The original implementation copy-pasted TnG's dedup pattern into the AEON and Maybank reprocess scripts using a "broad key" `(date, amount, type, description)`. This silently dropped 6 legitimate transactions during the Maybank reprocess: two toll-gate events on March 14 each producing PRE-AUTH/REV-PREAUTH/PAYMENT triplets at RM2.10. The bank's own statement listed all 6 as distinct line items; the dedup couldn't tell them apart because the bank doesn't tag them with anything that distinguishes one event from the other.

## Decision

Dedup at the file level only. `Statement.file_hash` (SHA-256 of the PDF bytes) prevents the same PDF from being processed twice via the email-fetch path. Reprocess scripts use `DELETE + INSERT` for idempotency — delete all transactions for the bank's account before re-inserting from parser output. No transaction-level dedup for non-TnG banks. TnG keeps its `external_reference`-based dedup because it's reliable for that bank's data.

## Consequences

**Positive:**
- Same-day identical-key transactions are correctly preserved (toll gates, parking, identical-amount recurring charges).
- Architecture is simpler: one less moving part to reason about.
- The reconciliation layer (ADR-002) now sees correct counts and surfaces issues clearly rather than masking them as "expected dedup."

**Negative:**
- No protection against partial reprocess. If the reprocess script crashes mid-loop, some transactions may be missing for the bank's account. Mitigation: the script's `DELETE + INSERT` pattern is run as a one-shot operation, not exposed in the UI, so this isn't a real risk.

## Alternatives considered

- **Reference-based dedup using description-embedded references** — inconsistent across transaction types; would silently lose data for toll/parking-style transactions that have no embedded reference.
- **Position-in-statement based dedup** — would require the parser to emit a sequence number; complicates the data model for negligible benefit.
- **Per-statement broad-key dedup (instead of global)** — would still have within-statement collisions, which is exactly the toll-gate case. Doesn't solve the actual problem.

## Notes

- Reprocess scripts where dedup was removed: `backend/scripts/reprocess_maybank.py`, `backend/scripts/reprocess_aeon.py`
- The `Statement.file_hash` UNIQUE constraint in `backend/app/models.py` is the source-of-truth dedup mechanism.
- Project commit that removed the broad-key dedup: `07f24e4 fix(ringgit): drop reprocess-script broad-key dedup that ate legitimate repeats`
```

- [ ] **Step 4: Create `ADR-004-encrypted-stub-fallback.md`**

Write the file at the path above. Final content:

```markdown
---
type: adr
status: accepted
date: 2026-05-02
project: ringgit-financial-analyzer
tags:
  - adr
  - project/ringgit
---

# ADR-004: Encrypted-stub fallback

## Context

PDFs may arrive from senders we haven't configured a password for, or with passwords that have changed. The original fetch path had two unacceptable failure modes: throw the PDF away (data loss), or fail the entire fetch (blocking the rest of the inbox).

Neither is acceptable, especially when adding a new sender. The user wants the bytes saved so they can configure the password later, or upload the file manually with the password.

## Decision

When a PDF can't be decrypted (no configured password for the sender, or the configured password fails authentication), save the PDF bytes to `backend/fetched_pdfs/<account>/<hash>.pdf` and create a `Statement` row with `bank='unknown'` and a recoverable `file_path`. The user can then either (a) configure the password in `.env` and re-run the appropriate `reprocess_*.py` script, or (b) upload the file manually with the password via the UI. When the matching parser ships later — for example, Maybank's parser shipped 2026-05-02 after the AEON parser had already shipped — the same files become processable via reprocess.

## Consequences

**Positive:**
- Robust against new banks/senders we haven't configured: bytes are never lost.
- The Maybank case in May 2026 was a textbook validation: 61 statements had been sitting as encrypted stubs for weeks before the parser landed, and the reprocess script picked them all up cleanly with zero data loss.
- The `bank='unknown'` rows are queryable and could be surfaced in the UI as a backlog if useful.

**Negative:**
- Statements sit as `bank='unknown'` until the user gets around to them. The 8 AEON Visa Platinum (VP) stubs continue to sit as `bank='unknown'` because the VP parser hasn't been written.

## Alternatives considered

- **Throw away undecryptable PDFs** — data loss, especially bad for new-sender cases where the password just hasn't been configured yet.
- **Fail the fetch on any undecryptable PDF** — blocks the rest of the inbox, including PDFs we CAN decrypt.
- **Prompt user at fetch time for password** — requires a UI flow that doesn't fit the bulk historical-backfill use case.

## Notes

- Fetch path: `backend/app/routers/email.py` — saves bytes and creates the Statement row before attempting decryption.
- Parser registry: `backend/app/services/parser_registry.py` — handles the unknown-bank case by writing the encrypted stub.
- Real-world example: 61 Maybank PDFs sat as `bank='unknown'` from initial fetch (April 2026) until the Maybank parser landed (2026-05-02) — zero data loss, recovered via `backend/scripts/reprocess_maybank.py`.
```

- [ ] **Step 5: Verify all 4 files exist and have correct frontmatter**

Run:
```bash
ls "C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\decisions\"
```
Expected: lists ADR-001 through ADR-004 (4 markdown files).

Run:
```bash
for f in "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/decisions"/*.md; do
  head -3 "$f"
done
```
Expected: each file's first 3 lines are `---`, `type: adr`, `status: accepted` — consistent frontmatter across all 4.

- [ ] **Step 6: Commit the ADRs as a single bundle**

The vault uses Conventional Commits style with scope `(ringgit)`. Bundle commit matches the precedent set by the brightness-assay project's recent doc-pass commit pattern.

```bash
cd "C:/Users/aquam/PersonalVault" && git add projects/ringgit-financial-analyzer/decisions/ && git commit -m "$(cat <<'EOF'
docs(ringgit): add ADR-001..004 capturing load-bearing architectural decisions

Captures the reasoning behind 4 architectural choices made during
implementation that aren't obvious from current code:

- ADR-001 Anchor-based parsing (replacing the original column-position
  regex approach after first real-PDF test contact with reality)
- ADR-002 Reconciliation as runtime guardrail (per-bank dispatch arm
  in reconcile_statement that re-extracts rows independently)
- ADR-003 File-level dedup only (file_hash + DELETE+INSERT covers all
  cases; broad-key dedup ate legitimate same-day repeats)
- ADR-004 Encrypted-stub fallback (save bytes + bank='unknown'
  Statement when password unconfigured or wrong, parse later)

Each ADR follows Michael Nygard format (Context / Decision /
Consequences / Alternatives / Notes) with cross-links to project repo
files where each decision manifests.
EOF
)"
```

Expected: single commit added. `git log -1 --oneline` shows the commit message.

---

## Task 2: Update `SPEC-001-system-design.md`

**Files:**
- Modify: `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\specs\SPEC-001-system-design.md`

The SPEC's existing Goals, Non-Goals, Architecture (ASCII diagram), Data Model, Frontend Pages, Tech Stack, and Constraints sections stay AS-IS — they're the original-intent record and remain accurate.

Three changes:
1. **Implementation Notes** added inline under affected Feature subsections (these are quoted callouts; don't rewrite the surrounding text).
2. **Acceptance Criteria** section becomes a status checklist (each `- [ ]` becomes `- [x]`, `- [~]`, or stays `- [ ]` with a brief note when reality landed differently).
3. **Revision History** row appended.

- [ ] **Step 1: Read the current SPEC-001 to understand the section structure**

Run:
```bash
head -200 "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/specs/SPEC-001-system-design.md"
```

Then `tail -100` for the rest. The file is ~384 lines. Note where each Feature subsection sits (PDF Parsing, Auto Bank Detection, Duplicate Detection, etc.) so you can insert Implementation Notes in the right place.

- [ ] **Step 2: Add Implementation Note under "PDF Parsing" feature**

Find the "### Core" Feature 1 ("PDF Parsing (6 bank-specific parsers)") subsection. After its bullet list, insert this paragraph as a blockquote callout:

```markdown
> **Implementation note (2026-05-02):** Original plan assumed regex-against-column-positions per bank. First fixture-test contact with reality showed PyMuPDF doesn't preserve column positions in extracted text — see [[../decisions/ADR-001-anchor-based-parsing|ADR-001]]. All 3 shipped parsers (TnG, AEON BC, Maybank) use anchor-based extraction. The 6-parser scope is partial: TnG, AEON BC, and Maybank are shipped; CIMB, Public Bank, Hong Leong, and AEON VP are not started.
```

- [ ] **Step 3: Add Implementation Note under "Auto Bank Detection" feature**

Find Feature 2 ("Auto Bank Detection"). After its bullet list, insert:

```markdown
> **Implementation note (2026-05-02):** Implemented as a content-based two-marker text check per parser. For example, the Maybank parser requires both `"Malayan Banking Berhad"` AND `"URUSNIAGA AKAUN"` in the extracted text. No image/logo recognition. Confidence-fallback UI not built — unknown PDFs save as encrypted-stub Statements with `bank='unknown'` so the bytes are preserved for later. See [[../decisions/ADR-004-encrypted-stub-fallback|ADR-004]].
```

- [ ] **Step 4: Add Implementation Note under "Duplicate Detection" feature**

Find Feature 3 ("Duplicate Detection"). After its bullet list, insert:

```markdown
> **Implementation note (2026-05-02):** File-level dedup is the only dedup mechanism. The reprocess scripts use DELETE + INSERT for idempotency — see [[../decisions/ADR-003-file-level-dedup-only|ADR-003]]. A broad-key `(date, amount, type, description)` transaction-level dedup was tried in the reprocess scripts and found to silently drop legitimate same-day repeats (toll gates, parking) — removed.
```

- [ ] **Step 5: Add a new "Reconciliation Layer" subsection between "Duplicate Detection" and "Learning Categorizer"**

The reconciliation layer didn't exist in the original SPEC-001. Add a new numbered subsection. The numbering of subsequent features shifts by one (Learning Categorizer becomes 5, Income Auto-Detection becomes 6, etc.). Keep the original numbers as-is and instead add the reconciliation subsection without renumbering — call it Feature 3.5, or use the section header "**Reconciliation Layer (added post-spec)**" without a number. The latter is cleaner.

Insert this subsection between Feature 3 (Duplicate Detection) and Feature 4 (Learning Categorizer):

```markdown
**Reconciliation Layer (added post-spec, 2026-05-02)**
   - Runtime guardrail that re-extracts transaction rows independently from the parser and cross-checks counts, statement balance, and per-row balance.
   - Per-bank dispatch arm in `reconcile_statement` (TnG via `find_tables`, AEON and Maybank via anchor-based text parsing).
   - Bank-specific cross-checks layered on inline (AEON: header Previous/Current; Maybank: explicit BEGINNING/ENDING balance markers).
   - Failures soft-flag `Statement.needs_review = True`; inserts are not rolled back.
   - See [[../decisions/ADR-002-reconciliation-as-runtime-guardrail|ADR-002]] for full reasoning.
```

- [ ] **Step 6: Replace the entire Acceptance Criteria section**

Find the `## Acceptance Criteria` section. Replace its body (the unordered checkbox list) with:

```markdown
Status as of 2026-05-02. Items marked `[x]` are shipped, `[~]` are partially shipped (with note), `[ ]` are not started.

- [x] Can upload a password-protected Maybank PDF and see parsed transactions — *Shipped via per-sender env-var passwords (`PDF_PASSWORD_MAYBANK`), not the originally planned upload-time dialog.*
- [~] Auto-detects bank from PDF content without user selection — *Two-marker text-content check per parser. No image/logo recognition. Confidence-fallback UI not built — unknown PDFs save as encrypted-stub Statements with `bank='unknown'` instead. See [[../decisions/ADR-004-encrypted-stub-fallback|ADR-004]].*
- [x] Skips duplicate PDFs (same file uploaded twice) — *SHA-256 `file_hash` check on Statement insert.*
- [x] Transactions auto-categorized with bilingual keyword matching
- [x] Correcting a category on one transaction improves future auto-categorization
- [ ] Internal transfers (bank→ewallet, bank→credit card, bank→bank) detected and excluded from spending totals — *Not yet implemented.*
- [x] ATM withdrawals tracked separately with untracked cash gap shown
- [x] Dashboard shows monthly income, spending, savings with trend indicators
- [x] Budget progress bar reflects current month spending vs target
- [x] Gmail fetch retrieves new statement PDFs on app open — *Multi-account; cursor advances only on attachment-bearing fetches (bug fixed 2026-05-02).*
- [~] Historical savings trend chart shows 6+ months — *Data is now available (Maybank backfill provides 8 years); chart UI status not verified at time of this update — re-tick when confirmed.*
- [x] Recurring transactions flagged with badge
- [x] Manual cash transaction entry works
- [~] All 6 bank parsers extract transactions correctly from sample PDFs — *3 of 6 shipped (TnG, AEON BC, Maybank). CIMB, Public Bank, Hong Leong, and AEON VP not started.*
```

- [ ] **Step 7: Append revision history row**

Find the `## Revision History` table at the bottom of the file. Add a new row:

```markdown
| 2026-05-02 | Yeow   | Implementation gap-update: ticked Acceptance Criteria, added Implementation Notes where reality diverged, added Reconciliation Layer subsection, linked new ADRs |
```

- [ ] **Step 8: Verify all wikilinks and structure**

Run:
```bash
grep -n "ADR-00" "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/specs/SPEC-001-system-design.md"
```
Expected: at least 4 hits, one for each of ADR-001, ADR-002, ADR-003, ADR-004 — confirms all 4 ADRs are linked from somewhere in SPEC-001.

Run:
```bash
grep -n "Implementation note" "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/specs/SPEC-001-system-design.md"
```
Expected: 3 hits (under PDF Parsing, Auto Bank Detection, Duplicate Detection).

Run:
```bash
grep -n "Reconciliation Layer" "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/specs/SPEC-001-system-design.md"
```
Expected: 1 hit — the new subsection header.

Run:
```bash
grep -c "^- \[" "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/specs/SPEC-001-system-design.md"
```
Expected: 14 — the count of acceptance-criteria checkboxes (matches the original list count, just with status added).

- [ ] **Step 9: Commit the SPEC-001 update**

```bash
cd "C:/Users/aquam/PersonalVault" && git add projects/ringgit-financial-analyzer/specs/SPEC-001-system-design.md && git commit -m "$(cat <<'EOF'
docs(ringgit): SPEC-001 implementation gap-update

- Acceptance Criteria becomes a status checklist (3 partial, 1 not
  started, rest shipped) with brief notes where reality diverged from
  the original 2026-04-07 design
- Implementation Notes added inline under PDF Parsing, Auto Bank
  Detection, and Duplicate Detection features pointing at the relevant
  ADRs and explaining the divergence
- New Reconciliation Layer subsection (didn't exist in the original
  spec) with link to ADR-002
- Revision history row appended
EOF
)"
```

Expected: single commit added.

---

## Task 3: Refresh `index.md`

**Files:**
- Modify: `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\index.md`

The dashboard becomes useful at a glance for future-you. Concrete changes: status table refreshed, Supported Banks table replaced, two new sections added (Recent shipped + Active decisions), architecture summary updated.

- [ ] **Step 1: Replace the entire `index.md` file**

Write the file at `C:\Users\aquam\PersonalVault\projects\ringgit-financial-analyzer\index.md` with this content (full replacement — preserves frontmatter, refreshes everything below it):

```markdown
---
type: project
status: active
date: 2026-04-07
owner: Yeow
tags:
  - project/ringgit
  - active
aliases:
  - Ringgit
  - Financial Analyzer
---

# Ringgit — Personal Financial Analyzer

## Overview

Personal finance web application for tracking spending, income, and savings across multiple Malaysian bank accounts. Parses PDF bank statements (with password support), auto-categorizes transactions using a learning keyword matcher, detects internal transfers between own accounts, and fetches statements from Gmail automatically.

## Status

| Attribute     | Value                                                                          |
| ------------- | ------------------------------------------------------------------------------ |
| Phase         | Implementation                                                                  |
| Stack         | FastAPI + React (Vite) + SQLite                                                |
| Owner         | Yeow                                                                            |
| Started       | 2026-04-07                                                                      |
| Last shipped  | 2026-05-02 — Maybank savings parser (61 statements, 1076 transactions reconciled) |
| Branch        | `main`                                                                          |
| Test count    | 173 passing, 6 skipped (real-fixture tests for fixtures not staged)            |

## Key Links

- [[specs/SPEC-001-system-design|SPEC-001: System Design]] — Full system specification (with 2026-05-02 implementation status)

## Supported Banks

| Bank/Service             | Source         | Parser      | Reconciled                            | Notes                                          |
| ------------------------ | -------------- | ----------- | ------------------------------------- | ---------------------------------------------- |
| TnG eWallet              | Email + manual | Shipped     | Per-row + statement                    | New format + legacy format both covered         |
| AEON Credit (BC)         | Email + manual | Shipped     | Statement-level (no per-row)           | 31 statements reprocessed                      |
| Maybank Savings          | Email + manual | Shipped     | Per-row + statement + beginning/ending | 61 statements; 2 eras (2018 GST + post-2018)   |
| AEON Visa Platinum (VP)  | Email          | Not started | —                                      | 8 stubs as `bank='unknown'`                    |
| CIMB                     | Email + manual | Not started | —                                      | No data in inbox yet                           |
| Public Bank              | Email + manual | Not started | —                                      | No data in inbox yet                           |
| Hong Leong               | Email + manual | Not started | —                                      | App-only / different inbox                     |

## Recent shipped

- **2026-05-02** — Maybank savings parser (anchor-based, both 2018 GST and 2026 post-GST formats; 61 statements reprocessed; reconciler arm with per-row + statement-level + beginning/ending balance cross-checks)
- **2026-05-02** — Fetch cursor advancement bug fix + reset script + `PDF_PASSWORD_MAYBANK` wired
- **2026-05-02** — AEON Credit Card (BC) parser + statement-level reconciliation; 31 statements reprocessed
- **2026-05-01** — TnG reprocess + reconciliation layer (find_tables-based)
- **2026-04-18** — Blocking gaps closed (TnG parser hardening, encrypted-stub pattern, persisted file_path)

## Active decisions

See `decisions/` folder for full reasoning behind each.

- [[decisions/ADR-001-anchor-based-parsing|ADR-001]] — Why anchor-based parsing instead of column-position regex
- [[decisions/ADR-002-reconciliation-as-runtime-guardrail|ADR-002]] — Why a reconciliation layer at all (and what it actually catches)
- [[decisions/ADR-003-file-level-dedup-only|ADR-003]] — Why no transaction-level dedup for non-TnG banks
- [[decisions/ADR-004-encrypted-stub-fallback|ADR-004]] — Why we save bytes for un-decryptable PDFs instead of failing

## Architecture Summary

```
React Frontend ──REST API──▶ FastAPI Backend ──▶ SQLite
                              ├── Gmail Fetcher (multi-account, on-app-open)
                              ├── Per-bank Parsers (TnG, AEON BC, Maybank shipped;
                              │                     CIMB / Public Bank / Hong Leong /
                              │                     AEON VP pending)
                              ├── Reconciliation Layer (find_tables for TnG,
                              │                        anchor-based text parsing
                              │                        for AEON/Maybank; soft-flags
                              │                        Statement.needs_review)
                              ├── Categorizer (bilingual keywords + learning)
                              └── Transfer Detector (cross-account matching;
                                                     not yet implemented)
```

---
## Revision History

| Date       | Author | Changes                                                                          |
| ---------- | ------ | -------------------------------------------------------------------------------- |
| 2026-04-07 | Yeow   | Initial draft                                                                    |
| 2026-05-02 | Yeow   | Implementation status snapshot — supported banks updated, Recent shipped + Active decisions sections added, architecture summary updated |
```

- [ ] **Step 2: Verify the file was written correctly**

Run:
```bash
head -10 "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/index.md"
```
Expected: shows YAML frontmatter (`---`, `type: project`, `status: active`, etc.) followed by the H1 title.

Run:
```bash
grep -n "Recent shipped\|Active decisions" "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/index.md"
```
Expected: 2 hits — one for each new section header.

Run:
```bash
grep -c "ADR-00" "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/index.md"
```
Expected: 4 — one wikilink per ADR.

- [ ] **Step 3: Commit the index.md refresh**

```bash
cd "C:/Users/aquam/PersonalVault" && git add projects/ringgit-financial-analyzer/index.md && git commit -m "$(cat <<'EOF'
docs(ringgit): refresh index.md dashboard for current shipped state

- Phase moved Design → Implementation
- Status table extended with Last shipped, Branch, Test count
- Supported Banks table replaced with current per-bank ship status
  (TnG, AEON BC, Maybank shipped; AEON VP, CIMB, Public Bank, Hong
  Leong not started)
- New Recent shipped section (rolling list of last 5 ship-events)
- New Active decisions section linking to the 4 ADRs
- Architecture summary updated to show Reconciliation Layer as a
  peer to the Parser Registry, parsers labelled per-bank rather than
  "6 bank-specific"
EOF
)"
```

Expected: single commit added.

---

## Task 4: Final visual check + push

**Files:** None modified.

This is verification-only. Confirm everything is in order, then push the 3 commits to the vault's remote.

- [ ] **Step 1: Confirm the 3 commits landed**

Run:
```bash
cd "C:/Users/aquam/PersonalVault" && git log --oneline -5
```
Expected: top 3 commits are the docs(ringgit) commits from Tasks 1, 2, 3 in reverse order (Task 3 most recent).

- [ ] **Step 2: Confirm vault file structure**

Run:
```bash
ls "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/decisions/"
```
Expected: 4 ADR files.

Run:
```bash
ls "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/"
```
Expected: shows `assets`, `database`, `decisions`, `index.md`, `plans`, `references`, `specs` (all original folders + the now-populated decisions folder).

- [ ] **Step 3: Spot-check internal wikilinks**

The wikilinks use Obsidian syntax: `[[path/to/file|display text]]`. The vault doesn't run these through a build step, so they only render in Obsidian. We can at least confirm the link targets exist as files.

Run:
```bash
for adr in 001 002 003 004; do
  test -f "C:/Users/aquam/PersonalVault/projects/ringgit-financial-analyzer/decisions/ADR-${adr}-"*.md && echo "ADR-${adr} OK" || echo "ADR-${adr} MISSING"
done
```
Expected: 4 lines, all "OK".

- [ ] **Step 4: Push to vault remote**

```bash
cd "C:/Users/aquam/PersonalVault" && git push origin main
```
Expected: `4 commits` (or however many were ahead of origin) pushed successfully. Note: the vault was already 1 commit ahead of origin at the start of this work, so the push will include 1 prior commit + the 3 new ones.

- [ ] **Step 5: No commit (verification-only task)**

This task changes no files. The push in Step 4 publishes the 3 commits from Tasks 1-3.

---

## Self-review

**Spec coverage:** each section of `2026-05-02-vault-documentation-refresh-design.md` is covered:
- File map → Tasks 1, 2, 3.
- index.md update plan → Task 3.
- SPEC-001 update plan → Task 2.
- ADR format and 4 ADRs → Task 1.
- Frontmatter convention → embedded in Task 1.
- Body template → embedded in Task 1.
- Testing strategy ("visual + cross-link resolution, no automated tests") → Task 4.
- Risks (vault outside project repo; update cadence; Implementation Notes risk; ADR-003 dated reference; Acceptance Criteria repurposing) → no task needed; these are accepted in the spec, not actionable.

**Placeholder scan:** no TBD/TODO markers in the plan. Every step has either complete file content (for create/replace operations) or specific edit instructions plus the exact content to insert (for in-place edits to SPEC-001). The verification commands have concrete expected output. The commit messages are spelled out in HEREDOCs.

**Type consistency:** N/A for documentation. Cross-checks done:
- All 4 ADR filenames match between Task 1 (creation) and Task 2 (linked from SPEC-001) and Task 3 (linked from index.md).
- Frontmatter `type: adr`, `status: accepted` consistent across all 4 ADRs.
- Wiki-link paths consistent: `../decisions/ADR-NNN-...` from SPEC-001 (since SPEC-001 is in `specs/` and ADRs in `decisions/`); `decisions/ADR-NNN-...` from `index.md` (since `index.md` is at the project root).
- `Statement.needs_review`, `Statement.file_hash`, `Statement.bank` field names consistent with the actual model and matching the wording used in the project repo's specs and ADR bodies.
- Date `2026-05-02` consistent across all ADR frontmatter, Implementation Notes timestamps, and revision history rows.
