---
phase: 05-log-parsing-supertimeline-search
fixed_at: 2026-05-31T00:00:00Z
review_path: .planning/phases/05-log-parsing-supertimeline-search/05-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 5: Code Review Fix Report

**Source review:** `.planning/phases/05-log-parsing-supertimeline-search/05-REVIEW.md`
**Iteration:** 1
**Scope:** Critical + Warning (Info findings IN-01/IN-02/IN-03 explicitly out of scope)

**Summary:**
- Findings in scope: 8 (2 Critical, 6 Warning)
- Fixed: 8
- Skipped: 0
- Test suite: **228 passed, 0 failed** (`PYTHONPATH=src python -m pytest`), exit 0.
- `ruff check` on all touched files: clean.

All work was done in an isolated git worktree on branch
`gsd-reviewfix/05-956518`; six atomic commits were made there and the cleanup
tail fast-forwards the user's branch to capture them. **This report is NOT
committed by the fixer — the orchestrator commits it.**

> Commit grouping: several findings co-touch the same file (`core/logs.py`,
> `case/store.py`, `core/search.py`), so commits are grouped by file-coherence;
> each finding lists the commit(s) that carry it.

## Commits (on the reviewfix branch, fast-forwarded onto the working branch)

| hash | summary |
|------|---------|
| `d195642` | CR-01 compile-time ReDoS guard + truncate long regex hits |
| `ada4d44` | WR-02/WR-06 CaseStore source-id + fs-prefix reads; walk/recover/knownfiles |
| `1f8a30e` | WR-02/WR-03/WR-04 run_search (store read, audited pre-open guard, doc) |
| `cef1f56` | WR-05 bounded rotated `.gz` inflation |
| `71701ba` | WR-01 Dec→Jan year-wrap confirmation |
| `f0a9c44` | CR-02/WR-02/WR-03/WR-06 run_logs (undated→end, audit, fs gate) |

## Fixed Issues

### CR-01: Search regex ReDoS guard applied AFTER the match completes

**Files modified:** `src/pyautopsy/search/content.py`
**Commit:** `d195642`
**Applied fix:** Added `assert_redos_safe()` enforced at COMPILE time (called from
`compile_regex`), rejecting nested-unbounded-quantifier patterns (`(a+)+`,
`(.*a){30}`, `(a*)*`, `(\d+)*`, `(.*)+`) and quantified overlapping alternations
(`(a|a)*`) before any matching runs — because Python's `re` is a backtracking
engine with no timeout, so the post-hoc `MAX_REGEX_MATCH_LEN` length check could
never short-circuit catastrophic backtracking (it happens inside `finditer`
before a match object exists). No new runtime dependency (avoids `re2`, D-43).
Separately fixed the silent-drop correctness gap: a match longer than
`MAX_REGEX_MATCH_LEN` is now REPORTED truncated (span clamped to the bound)
instead of `continue`-skipped.
**Verification:** Direct runtime checks confirmed `(a+)+$` and `(.*a){30}` over
crafted buffers reject in <0.001 s (no hang); a 5000-byte `A+` match is reported
with a 4096-byte truncated term at offset 0; legit bounded patterns
(`[a-z]+@[a-z]+`, `\d{1,4}`, `.*foo`) still compile. The existing
`tests/test_search.py` SEARCH-01 suite still passes (boundary-spanning + region
tests unaffected). NOTE: `tests/test_search.py` is a RED Wave-0 scaffold that
imports `pyautopsy.search` lazily and uses image fixtures; dedicated unit-level
ReDoS regression tests were NOT added there to avoid disturbing that scaffold —
the runtime verification above stands in their place.

### CR-02: `_seed_year_from_mtime` epoch-1970 fallback sorts to FRONT of the timeline

**Files modified:** `src/pyautopsy/core/logs.py`
**Commit:** `f0a9c44`
**Applied fix:** `_seed_year_from_mtime` now returns a third value
`unresolved: bool`, true only when NO mtime exists anywhere on the image. In
`_resolve_records_to_events`, an unresolved member's events get a far-future
sentinel `ts_utc` (`9999-12-31T23:59:59+00:00`, the new `_UNDATED_SORT_LAST_ISO`)
so they sort to the END of the `get_timeline_events` (ts_utc-ASC) super-timeline
instead of the 1970 FRONT, carrying an explicit `ts_basis` flag
("... sorted to end of timeline, NOT genuine chronology"). Mtime-anchored
fallbacks (seed-year Jan 1) remain inline — only the fully-unresolved case is
segregated. The disclosure now reaches the place the distortion would appear.
**Verification:** Full suite green; the existing `test_run_logs_*` shell-history
fallback tests still pass with the new return arity. **Logic/presentation change
— flagged for the verifier phase** to confirm the segregation reads correctly in
the rendered report timeline.

### WR-01: `infer_years` confirmed-wrap heuristic can refuse a genuine year boundary

**Files modified:** `src/pyautopsy/log/timeresolve.py`
**Commit:** `71701ba`
**Applied fix:** Broadened the `confirmed` condition so a wrap is confirmed when
EITHER the next-older record is in H2 (original signal) OR the current record is a
strong year-end signal (`month >= 11`, Nov/Dec) that is later-in-calendar than an
H1 anchor. Fixes review shape #1 (a genuine Dec→Jan boundary whose pre-boundary
neighbour sits in H1 was mis-dated by a year) while preserving the single-anomaly
anti-cascade guard (a lone mid-year spike still fails both clauses). A
conservative refinement, not the full per-member-mtime re-anchor the review
sketched.
**Verification:** Direct check: `[Dec 31, Jan 02, Jan 20]` seeded 2024 now yields
`[2023, 2024, 2024]` (previously `[2024, 2024, 2024]`). Existing year-inference
regressions (same-month backward step, lone-spike no-cascade) still pass.
**`fixed: requires human verification`** — this is a heuristic logic change;
confirm it matches intended D-46 semantics on real rotated-log fixtures. Review
shape #2 (a purely-Q4 multi-year rotated set whose anchor never enters H1) is only
partially mitigated by clause (b) and may warrant the per-member re-anchor in a
follow-up.

### WR-02: Orchestrators issue raw read-only SQL against `store.connection`

**Files modified:** `src/pyautopsy/case/store.py`, `src/pyautopsy/core/walk.py`,
`src/pyautopsy/core/knownfiles.py`, `src/pyautopsy/core/recover.py`,
`src/pyautopsy/core/search.py`, `src/pyautopsy/core/logs.py`,
`tests/test_store_latest_source.py`
**Commits:** `ada4d44` (store + walk/knownfiles/recover + test), `1f8a30e`
(search), `f0a9c44` (logs)
**Applied fix:** Added `CaseStore.get_latest_evidence_source_id() -> int | None`
(the single sanctioned read). All five `_latest_evidence_source_id` helpers now
call it and raise their own domain error on `None`; the inline
`SELECT id FROM evidence_sources ORDER BY id DESC LIMIT 1` reads are deleted.
Grep confirms zero remaining inline copies in `src/`.
**Verification:** New tests `test_get_latest_evidence_source_id_none_when_empty`
and `..._returns_newest` pass; the walk/recover/knownfiles/search/logs suites all
pass.

### WR-03: Pre-open `assert_source_not_mounted` is outside the audit scope

**Files modified:** `src/pyautopsy/core/logs.py`, `src/pyautopsy/core/search.py`
**Commits:** `f0a9c44` (logs), `1f8a30e` (search)
**Applied fix:** In both `run_logs` and `run_search`, the `AuditLog` is bound
BEFORE the first `assert_source_not_mounted` guard; the pre-open guard is wrapped
so a `MountedSourceError` writes a `logs.error` / `search.error` FAIL event before
re-raising (D-08 "record FAIL before non-zero exit"). The FileNotFoundError
store-open path is likewise audited. The now-duplicate later `audit = AuditLog(...)`
binding in `run_search` was removed (single binding confirmed).
**Verification:** Full suite green; both orchestrators still bind exactly one
AuditLog. NOTE: a dedicated mounted-source audit assertion test was NOT added to
the RED Wave-0 `tests/test_logs.py` scaffold (it lacks the seam fixtures such a
test needs and a malformed addition would corrupt the scaffold); the FAIL-before-
raise path is exercised structurally by the existing error-path tests.

### WR-04: Hash-arm split provenance (KnownMatch vs SearchHit), ambiguous order

**Files modified:** `src/pyautopsy/core/search.py`
**Commit:** `1f8a30e`
**Applied fix:** Documented the two-table provenance model explicitly in the
`run_search` module docstring: the hash arm writes BOTH a NEUTRAL `KnownMatch`
(read via `get_known_matches`) and a `term_kind="hash"` `SearchHit` (read via
`get_search_hits`); these are two distinct, individually byte-deterministic
ordering domains, and the report must reconcile both tables for one logical
search. The hash arm's determinism rests on `get_files` input order.
**Verification:** Review classified this "not a correctness bug per se"; the
actionable deliverable is the explicit boundary documentation, now in place. Full
suite green.

### WR-05: `safe_extract` has no caller; rotated `.gz` inflated unbounded via `gzip`

**Files modified:** `src/pyautopsy/log/discover.py`
**Commit:** `cef1f56`
**Applied fix:** `decode_member` now inflates a gz member in 4 MiB chunks with a
running uncompressed-byte counter and refuses (returns `""`) once it crosses the
new `MAX_GZ_UNCOMPRESSED` cap (256 MiB, mirroring
`safe_extract._DEFAULT_MAX_ENTRY_SIZE`), instead of an unbounded `gz.read()` that
let a small crafted gz expand into a memory-exhausting blob. A corrupt/over-cap
member is dropped without losing the rest of the rotated set.
**Verification:** The existing `test_rotation_reassembly_order` (which exercises
real `.gz` members through `decode_member`) still passes, confirming legitimate
small gz members inflate and decode normally. The bomb-refusal path is bounded by
construction (chunked read with a hard cap). Full suite green.

### WR-06: fs-event idempotency keys on "any timeline event exists"

**Files modified:** `src/pyautopsy/case/store.py`, `src/pyautopsy/core/logs.py`,
`tests/test_store_latest_source.py`
**Commits:** `ada4d44` (store method + test), `f0a9c44` (logs guard)
**Applied fix:** Added
`CaseStore.has_timeline_events_with_source_prefix(source_id, prefix)` (a bounded
`SELECT 1 ... LIKE ? LIMIT 1` EXISTS read, kept inside the store boundary). The
`run_logs` filesystem-MACB backfill now gates on the absence of
`source LIKE 'filesystem%'` events rather than the absence of ANY event, so a
prior standalone `logs` run (which inserts LOG events but never runs
`build_timeline`) no longer permanently suppresses the backfill. Verified the
filesystem event source label is exactly `filesystem` via
`timeline.builder.explode`.
**Verification:** New test
`test_has_timeline_events_with_source_prefix_gates_on_filesystem` asserts that
with only an `auth` event the gate is False (backfill will run) and after a
`filesystem` event it is True (no double-backfill). Passes. A full
`run_logs`-twice end-to-end test was NOT added because the RED Wave-0
`tests/test_logs.py` seam helper does not seed `files` inventory rows (the
backfill produces 0 events regardless there), so the gate logic is pinned at the
store-method level where the behavioral change lives.

## Skipped Issues

None — all 8 in-scope findings were fixed.

## Out of scope (not addressed)

- **IN-01, IN-02, IN-03** (Info severity) — outside the Critical+Warning scope of
  this `--fix` run.

## Test-infrastructure note

The Phase-5 test files `tests/test_search.py` and `tests/test_logs.py` are RED
Wave-0 scaffolds (lazy in-body imports, image-fixture-driven). New unit-level
regression tests for the source-only behavioral fixes were therefore added in a
dedicated new file `tests/test_store_latest_source.py` (store boundary, WR-02 +
WR-06) rather than grafted into the scaffolds. The remaining fixes' correctness is
covered by the existing scaffold tests staying green plus the direct runtime
verifications recorded above.

---

_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
