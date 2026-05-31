---
phase: 05-log-parsing-supertimeline-search
reviewed: 2026-05-31T00:00:00Z
depth: deep
files_reviewed: 19
files_reviewed_list:
  - src/pyautopsy/core/analyze.py
  - src/pyautopsy/core/logs.py
  - src/pyautopsy/log/__init__.py
  - src/pyautopsy/log/auth.py
  - src/pyautopsy/log/_grammar.py
  - src/pyautopsy/log/discover.py
  - src/pyautopsy/log/normalize.py
  - src/pyautopsy/log/registry.py
  - src/pyautopsy/log/syslog.py
  - src/pyautopsy/log/shell_history.py
  - src/pyautopsy/log/timeresolve.py
  - src/pyautopsy/search/__init__.py
  - src/pyautopsy/search/content.py
  - src/pyautopsy/search/ioc.py
  - src/pyautopsy/case/store.py
  - src/pyautopsy/util/safe_extract.py
  - src/pyautopsy/cli/main.py
  - tests/conftest.py
  - tests/test_logs_orchestrated.py
findings:
  critical: 2
  warning: 6
  info: 3
  total: 11
status: issues_found
---

# Phase 5: Code Review Report (Re-Review)

**Reviewed:** 2026-05-31
**Depth:** deep
**Files Reviewed:** 19 (16 source + test cross-reference)
**Status:** issues_found

## Scope-correction note

The config `files:` list named several paths that do not exist in the current
tree (`src/pyautopsy/cli.py`, `log/base.py`, `search/engine.py`, `search/hits.py`,
`evidence/blocks.py`). The real equivalents were located and reviewed instead:
the CLI is `src/pyautopsy/cli/main.py`; the shared syslog grammar is
`log/_grammar.py`; the streaming search engine is `search/content.py` +
`search/ioc.py`; the unallocated-block iterator lives in
`evidence/filesystem.py` (not separately reviewed — out of changed-file scope).
All four re-review focus areas were reachable and are covered below.

## Verification of the three prior Critical fixes

- **CR-01 (orchestrated parser registry) — HOLDS.** `log/__init__.py:33-37`
  imports `auth`, `shell_history`, `syslog` for their import-time `register(...)`
  side effect; `core/logs.py:54` imports `pyautopsy.log`, populating the full
  declared-order registry. `discover.DEFAULT_LOG_BASENAMES`
  (`discover.py:43-48`) now lists `auth.log`/`secure`/`syslog`/`messages`, and
  `run_logs` discovers shell histories via `discover_shell_histories`
  (`logs.py:350-353`). `registry.register` is idempotent on identity
  (`registry.py:123`), so the re-import cannot double-register. The orchestrated
  regression test `tests/test_logs_orchestrated.py` drives the REAL `run_logs` and
  asserts `{"auth","syslog","shell-history"} <= names` without hand-importing the
  parser modules — exactly the gate whose absence let the original CR-01 ship. Fix
  is real and guarded.
- **CR-02 (wall-clock determinism) — HOLDS.** `_seed_year_from_mtime`
  (`logs.py:137-175`) no longer calls `datetime.now()`. Precedence is member-mtime
  year → newest mtime across the walked set → epoch year 1970 with an explicit
  FLAGGED basis — all pure functions of evidence bytes. Repo scan confirms the only
  `datetime.now()` is the sanctioned `util/timeutil.py:27` helper, which the log
  path does not call.
- **CR-03 (RFC3164 year-inference cascade) — HOLDS, with a residual edge (WR-01).**
  `infer_years` (`timeresolve.py:164-241`) compares full `(month, day)`, walks
  newest→oldest with a running-minimum anchor, and rolls only on a CONFIRMED
  Dec→Jan-class wrap. The two regressions pin the same-month boundary and the
  single-anomaly no-cascade. The cascade is fixed; one heuristic edge remains.

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Search regex ReDoS guard is applied AFTER the match completes — it cannot prevent catastrophic backtracking; an examiner regex over crafted evidence bytes hangs the run

**File:** `src/pyautopsy/search/content.py:58-80` (`compile_regex`),
`:115-123` (`_iter_window_matches` regex loop)

**Issue:**
The module docstring (lines 14-15, 40-43, 63-66) repeatedly claims a "ReDoS /
unbounded-`.*` guard". The actual implementation is:
```python
def compile_regex(pattern): return re.compile(pattern)   # no complexity check
...
for m in rx.finditer(window):
    start, end = m.start(), m.end()
    if end - start > MAX_REGEX_MATCH_LEN:   # checked AFTER the match exists
        continue
```
The length check at line 118 runs only once `finditer` has already PRODUCED a
match object. Catastrophic backtracking happens *inside* `finditer`/the matcher,
before any match is yielded, so the `MAX_REGEX_MATCH_LEN` test can never short-
circuit it. Python's `re` has no timeout. The two adversarial inputs are both
present: (a) the regex is examiner-supplied via `pyautopsy search --term --regex`
(`cli/main.py:607-613,649,664-670`), and (b) the haystack is untrusted evidence
bytes from the image under investigation. A pattern like `(a+)+$` or `(.*a){30}`
against a 1 MiB chunk of crafted bytes (the default `DEFAULT_CHUNK_SIZE`,
`content.py:38`) backtracks super-polynomially and hangs the forensic run on a
single chunk — a DoS that also breaks the bounded/reproducible-run invariant. The
1 MiB chunk bound does NOT save it: `(a+)+` over 1 MiB of `a` is already
effectively unbounded. "The operator wrote the regex" is not a mitigation — the
operator does not control the bytes that trigger the blowup.

Separately, this same post-hoc check SILENTLY DROPS any legitimate match longer
than 4096 bytes (`content.py:118-121` `continue`), so a real `.*`-style hit that
spans >4 KiB is never reported at all — a correctness gap distinct from the DoS.

**Fix:**
- Make the guard actually bounding: either compile with a linear-time engine
  (`re2`/`google-re2`) — but that adds a runtime dep (D-43), so prefer — run each
  `finditer` under a hard wall-clock budget in a killable worker, OR reject
  patterns containing nested unbounded quantifiers at compile time, OR default to
  literal-only and gate true regex behind an explicitly-bounded backend.
- For the >4096 silent-drop: anchor the match length with a bounded quantifier at
  compile time (rewrite `.*`→`.{0,MAX}`) or report a truncated hit with a
  `truncated=True` flag rather than dropping it.
- Add a test that a known catastrophic pattern over a crafted buffer returns
  within a fixed time budget, and a test that a >4096 match is reported (not lost).

---

### CR-02: `_seed_year_from_mtime` epoch-1970 fallback materializes whole members at 1970-01-01, which sorts to the FRONT of the forensic super-timeline and misrepresents "earliest activity"

**File:** `src/pyautopsy/core/logs.py:164-175` (1970 fallback) +
`logs.py:232-240` (`datetime(seed_year, 1, 1)` anchor for no-timestamp lines)

**Issue:**
When neither the member nor any walked file carries an mtime, the seed year is
1970 and every no-per-line-timestamp record (the common bare `.bash_history`
case, which the module explicitly claims to support) resolves to
`datetime(1970, 1, 1)`. This is deterministic (CR-02-prior preserved) and flagged
in `attributes`, which is good — but `get_timeline_events`
(`store.py:637-641`) orders by `ts_utc` FIRST, and the report's timeline section
reads that order. So an entire member's commands land at the very top of the
UTC-sorted super-timeline that the report presents as forensic chronology, where
a reviewer reading "earliest activity" sees a 1970 cluster that is a pure artifact
of missing metadata, not real timing. The honesty flag lives in `attributes`,
which the ORDER never consults, so the disclosure does not reach the place the
distortion appears. For an evidence-presentation tool this is a defensibility
defect: the timeline's leading rows are fabricated-looking dates presented inline
with genuine ones.

This is the same class as the original CR-02 (mis-anchored log times polluting the
presented timeline), narrowed to the no-mtime-anywhere path the fix introduced
rather than fully closed.

**Fix:**
- Do not inject 1970-front events into the ordered timeline. Either (a) give
  undated/fallback events a `ts_utc` of `NULL` and surface them in a SEPARATE
  "undated artifacts" report section (sorted out of the chronological view), or
  (b) sort flagged-fallback events to the END rather than the 1970 front, or
  (c) carry an explicit `ts_precision`/`year_inferred` column the timeline ORDER
  and the report renderer both honor so a guessed instant is never rendered
  identically to a parsed one.
- Add a test asserting that fallback (no-mtime) events are visibly segregated from
  genuinely-timestamped events in the merged read, not interleaved at 1970.

---

## Warnings

### WR-01: `infer_years` "confirmed-wrap" heuristic can refuse a genuine year boundary, leaving a real prior-year segment mis-dated

**File:** `src/pyautopsy/log/timeresolve.py:216-228`

**Issue:**
The anti-cascade guard requires the boundary to be confirmed by the next-older
record also being in H2:
```python
wrap = cur_md > anchor_md and components[i][0] >= 7 and anchor_md[0] <= 6
confirmed = wrap and (i == 0 or components[i - 1][0] >= 7)
```
Two real shapes are mishandled:
1. A legitimate Dec→Jan boundary whose oldest pre-boundary neighbour happens to be
   in H1 is treated as an anomaly and NOT rolled (the `components[i-1][0] >= 7`
   confirmation fails), so that record keeps the seed year — wrong by one year.
2. A purely-Q4 multi-year rotated set (e.g. `Oct..Dec` year N-1 then `Oct..Dec`
   year N) never lets the anchor enter H1 (`anchor_md[0] <= 6` is never true), so
   NO record rolls and two distinct years collapse into one.
The honesty flag records the wrong year as considered output, in a timeline
presented as forensic truth. The existing regressions cover only Jan-side
boundaries and a lone spike, so these shapes pass CI while mis-dating.

**Fix:** Anchor each rotated member's year to ITS OWN mtime
(`_seed_year_from_mtime` already derives a per-member seed) and use the month-walk
only to disambiguate WITHIN a member — removing the dependency on the anchor
crossing the H1/H2 line. Add fixtures for both shapes above.

### WR-02: Orchestrator tier issues raw read-only SQL against `store.connection`, violating the documented "no raw SQL outside the store" boundary

**File:** `src/pyautopsy/core/logs.py:111` (`_latest_evidence_source_id`); same
copy-pasted `SELECT id FROM evidence_sources ORDER BY id DESC LIMIT 1` in
`core/search.py:88`, `core/walk.py:260`, `core/knownfiles.py:82`,
`core/recover.py:275`

**Issue:**
`store.py:1-8` declares CaseStore "the ONLY sanctioned way to read or write
case.db (no raw SQL is permitted elsewhere)". Five orchestrators bypass it with an
inline read. The sole-WRITER guarantee (D-08) is intact — these are reads, no
INSERT/executemany leaks outside `store.py` — but the documented boundary is
violated and an `evidence_sources` schema change silently breaks five call sites a
grep of `store.py` would miss.

**Fix:** Add `CaseStore.get_latest_evidence_source_id()` and call it from all
five; delete the inline SQL. Add an architectural test confining `.execute(` /
`import sqlite3` write usage to `case/store.py`.

### WR-03: Pre-open `assert_source_not_mounted` in `run_logs` is outside the audit scope — a mounted-source rejection writes NO `logs.error` FAIL event

**File:** `src/pyautopsy/core/logs.py:289-301` (guard at 290, `AuditLog` bound at
300); post-open re-assert at `:318` IS audited

**Issue:**
`integrity.assert_source_not_mounted(image_path)` runs at line 290, BEFORE the
audit log is constructed (line 300) and before the `try` whose handler emits
`logs.error`. A mounted source therefore raises `MountedSourceError` with NO FAIL
audit event, contradicting the D-08 "record FAIL before non-zero exit" contract
the module docstring (step 5) and the CLI rely on. The CLI maps the exception to a
clean exit code (`cli/main.py:378-385`) but the audit trail has no record.
`run_search` reportedly has the same shape.

**Fix:** Bind the audit log before the first guard (the case dir exists — `run_logs`
requires a prior ingest) and wrap the pre-open assertion so a mounted-source
rejection is audited before re-raise.

### WR-04: Hash-arm search reuses `custom_match` with sense `"block"` but emits a `KnownMatch`, not a `SearchHit` — provenance/order of hash hits depends on a join that can tie ambiguously

**File:** `src/pyautopsy/search/ioc.py:80-126` (`match_bad_hashes`)

**Issue:**
`match_bad_hashes` returns `KnownMatch` rows (persisted via
`insert_known_matches`), while content/IOC hits are `SearchHit` rows. The
`search` summary line reports `known-bad hits` (`cli/main.py:690`) but those rows
are read back through `get_known_matches` (`store.py:691-731`), a DIFFERENT
ordering domain than `get_search_hits`. A reviewer reading "search hits" in the
report must reconcile two tables with two orderings for one logical search. Not a
correctness bug per se, but a split provenance model that complicates the
deterministic-ordering guarantee (D-41) and the report's honesty. Confirm the
report renders both arms coherently and that hash-arm ordering is fully
deterministic (it relies on the `get_known_matches` join order, which ties on
`f.volume_id, f.volume_offset, f.path, f.id, k.*` — verify no NULL-path collision
across recovered/orphan rows can reorder between runs).

**Fix:** Document the two-table model explicitly in the search orchestrator and
add a test asserting hash-arm hit order is byte-stable across two runs of the same
fixture.

### WR-05: `safe_extract` (the hardened jail built "for Phase 5") has NO caller in the Phase-5 log path; rotated `.gz` is inflated directly via `gzip` instead

**File:** `src/pyautopsy/util/safe_extract.py:31-33` (docstring: consumers "arrive
in Phase 5"); `src/pyautopsy/log/discover.py:294-318` (`decode_member` →
`gzip.GzipFile`), `core/logs.py:462-464`

**Issue:**
`safe_extract`'s docstring states its consumers arrive in Phase 5 (this phase),
but `core/logs.py` decompresses rotated `.gz` members directly through
`discover.decode_member` and never routes anything through `safe_extract`. The gz
path is a single in-memory inflate of one member already size-bounded by the
recorded file `size` (`logs.py:462-464`), and `decode_member` swallows corrupt-gz
errors (`discover.py:316-317`), so there is no Zip-Slip surface here and no
decompression-bomb surface beyond the member size. BUT: a `.gz` member's
DECOMPRESSED size is not bounded by the on-disk member size — `gz.read()`
(`discover.py:315`) reads the full inflate into memory with no cap, so a small
crafted `.gz` log member can still expand to a memory-exhausting blob. That is
exactly the decompression-bomb case `safe_extract`'s caps exist to stop, and the
log path bypasses them.

**Fix:** Route gz inflation through a bounded reader (cap `gz.read(n)` to a sane
max-uncompressed limit, mirroring `safe_extract`'s `max_entry_size`), or reuse
`safe_extract`'s bomb-cap helper. Add a test with a small gz that inflates past
the cap, asserting it is refused/truncated rather than fully buffered.

### WR-06: `run_logs` fs-event idempotency backfill keys on "any timeline event exists" — a prior log-only run leaves filesystem MACB events permanently absent

**File:** `src/pyautopsy/core/logs.py:382-390`

**Issue:**
The backfill that ensures the super-timeline contains filesystem MACB events runs
only when `not store.get_timeline_events(source_id, limit=1)` (line 383) — i.e.
only when the source has ZERO timeline events. If `run_logs` is invoked
standalone (the `pyautopsy logs` CLI command, which never calls `build_timeline`
first) on a case where a prior `run_logs` already inserted LOG events but no walk
ever ran `build_timeline`, the guard sees existing events and skips the fs
backfill forever. The result is a "super-timeline" that is log-only with the
filesystem events silently missing, despite the docstring's TIME-02 merge promise.
The `analyze` path is safe (it calls `build_timeline` before `run_logs`,
`analyze.py:339-348`), but the standalone `logs` command is not.

**Fix:** Gate the fs backfill on "no FILESYSTEM-source events exist" (e.g.
`source LIKE 'filesystem%'`) rather than "no events at all", or have the standalone
`logs` command run `build_timeline` first like `analyze` does. Add a test running
`logs` twice standalone and asserting fs events are present.

## Info

### IN-01: `auth_events` count couples to the literal string `"auth"`

**File:** `src/pyautopsy/core/logs.py:367`

**Issue:** `sum(1 for e in set_events if e.source == "auth")` silently returns 0
if `AuthParser.name` changes. Magic-string coupling, low risk.

**Fix:** Reference `AuthParser.name`.

### IN-02: D-45 `CompletenessFinding` is computed per log set but never threaded into events/report

**File:** `src/pyautopsy/log/discover.py:193-213`; consumed only as
`.members`/`.basename` in `core/logs.py:354-366`

**Issue:** Each `LogSet.finding` describes missing rotation indices (the D-45
honesty signal) but `run_logs` never reads it, so a "rotation index N absent" gap
is never disclosed. (Carried from the prior review's WR-07; still unaddressed.)

**Fix:** Thread the finding into event `attributes` or a dedicated findings list
so the report can surface it.

### IN-03: `_DATEEXT_SUFFIX` members get negative synthetic indices excluded from `_completeness` and mis-ordered

**File:** `src/pyautopsy/log/discover.py:135-137`, `:195`

**Issue:** Dateext members map to `-int(YYYYMMDD)`; `_completeness` filters to
`index >= 0` (excluding them) and `order_key = (-index, …)` turns the negative
index into a huge positive sort key, mis-placing dateext members relative to
numeric ones in a mixed set. (Carried from the prior review's WR-06.)

**Fix:** Order dateext by parsed date in a sign-consistent domain and include them
in the completeness count, or reject dateext explicitly.

---

_Reviewed: 2026-05-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
