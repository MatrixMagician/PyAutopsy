---
phase: 05-log-parsing-supertimeline-search
reviewed: 2026-05-31T00:00:00Z
depth: deep
files_reviewed: 22
files_reviewed_list:
  - src/pyautopsy/case/models.py
  - src/pyautopsy/case/schema.sql
  - src/pyautopsy/case/store.py
  - src/pyautopsy/cli/main.py
  - src/pyautopsy/core/analyze.py
  - src/pyautopsy/core/logs.py
  - src/pyautopsy/core/search.py
  - src/pyautopsy/evidence/filesystem.py
  - src/pyautopsy/log/auth.py
  - src/pyautopsy/log/discover.py
  - src/pyautopsy/log/_grammar.py
  - src/pyautopsy/log/__init__.py
  - src/pyautopsy/log/normalize.py
  - src/pyautopsy/log/registry.py
  - src/pyautopsy/log/shell_history.py
  - src/pyautopsy/log/syslog.py
  - src/pyautopsy/log/timeresolve.py
  - src/pyautopsy/report/assemble.py
  - src/pyautopsy/report/templates/report.html.j2
  - src/pyautopsy/search/content.py
  - src/pyautopsy/search/ioc.py
findings:
  critical: 3
  warning: 7
  info: 4
  total: 14
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-05-31
**Depth:** deep
**Files Reviewed:** 22
**Status:** issues_found

## Summary

Phase 5 adds log parsing (auth/syslog/shell-history), super-timeline merge, and
content/IOC/hash search. The architecture is broadly sound on the hard
invariants this project cares about: the native seam (`evidence/filesystem.py`)
remains the only pytsk3 importer, no log/search module imports a native binding,
CaseStore stays the sole DB writer, read-only guards are re-asserted around image
opens, and the HTML renderer keeps autoescape on. Determinism is mostly preserved
via store-owned ordering.

However, the review found **three Critical defects** that defeat the phase's own
stated goals:

1. The Wave-2 syslog and shell-history parsers **never register at runtime** —
   `run_logs` imports only `auth`, and `pyautopsy.log.__init__` imports none of
   the three parsers. LOG-02 and LOG-03 are dead on the real code path.
2. A **wall-clock leak** (`datetime.now()`) flows into the persisted timeline
   events and thus into the byte-deterministic report body, breaking CLI-02 for
   any log with no usable mtime.
3. The RFC3164 year-inference produces **incorrect years for same-month rollovers
   and intra-day backward jumps**, silently mis-dating events the tool presents
   as a forensic super-timeline.

Plus seven warnings (a dead `ioc_terms` path, non-deterministic hash-arm ordering
fallbacks, an unreachable `MountedSourceError` handler in `run_logs`, a fragile
RFC3164 grammar boundary, etc.) and four info items.

## Critical Issues

### CR-01: Syslog (LOG-02) and shell-history (LOG-03) parsers never register — dead at runtime

**File:** `src/pyautopsy/core/logs.py:49`, `src/pyautopsy/log/__init__.py:25-26`
**Issue:** Parser registration is an *import-time side effect*: `auth.py`,
`syslog.py`, and `shell_history.py` each call `register(...)` only when the module
is imported (`auth.py:136`, `syslog.py:139`, `shell_history.py:207`). But:

- `core/logs.py:49` imports **only** `auth`:
  `from pyautopsy.log import auth as _auth  # noqa: F401 (registers AuthParser)`.
- `pyautopsy/log/__init__.py` imports `registry` and `timeresolve` but **none** of
  `auth` / `syslog` / `shell_history` (lines 25-26).

So when `run_logs` calls `iter_parsers()` (via `_parse_log_set`,
`logs.py:388-390`), the registry contains exactly one parser: `AuthParser`.
`SyslogParser` and `ShellHistoryParser` are never appended, so `syslog`/`messages`
and `.bash_history`/`.zsh_history` files are silently never parsed even though
`discover.py` discovers `secure`/`auth.log` only — and shell-history/syslog
basenames are not even in `DEFAULT_LOG_BASENAMES` (`discover.py:38`). The Phase-5
LOG-02/LOG-03 deliverables are effectively non-functional on the orchestrated
path; the modules are reachable only from tests that import them directly.

**Fix:** Register all Wave-1/Wave-2 parsers at package import and discover their
basenames. Minimal version:

```python
# pyautopsy/log/__init__.py
from pyautopsy.log import auth, shell_history, syslog  # noqa: F401  (EXT-01 register)
```

and extend `discover.DEFAULT_LOG_BASENAMES` to include `"syslog"`, `"messages"`,
and handle the home-dir shell-history discovery, OR have `run_logs` import the
parsers explicitly and pass the full basename set to `discover_log_sets`. Add a
test asserting `len(list(iter_parsers())) == 3` after importing `pyautopsy.log`.

---

### CR-02: Wall-clock `datetime.now()` leaks into the deterministic report body (CLI-02 violation)

**File:** `src/pyautopsy/core/logs.py:132-139`
**Issue:** `_seed_year_from_mtime` falls back to the analysis host's current year
when a log member has no usable mtime:

```python
if mtime:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).year
return datetime.now(timezone.utc).year   # <-- wall-clock
```

That seed year is fed to `infer_years` (`logs.py:167`) and into
`naive_from_components` → `to_utc`, producing the event's `ts_utc` **and** the
`year_inferred` attribute (`timeresolve.py:199-201`). Both are persisted into
`timeline_events` and surfaced in the report body: `ts_utc` is a timeline row
(`assemble.py:407`) and `year_inferred` drives `inferred_year_count`
(`assemble.py:445-449`). The module docstring explicitly promises "never
wall-clock (CLI-02)" (`logs.py:30`, `logs.py:85-89`), but this path makes
`report.json`/`report.html` differ between two runs of the same fixture whenever a
log member's mtime is 0 — which is exactly the standalone-`logs` case the code
claims to support. This is the same class of bug the FAT/zero-epoch work was
designed to avoid, re-introduced on the log seam.

**Fix:** Do not call `datetime.now()`. Anchor the fallback to a deterministic,
content-derived value (e.g. the evidence source's `acquired_utc` year if you must
have one, or — better — leave the year explicitly unresolved and flag it
`year_basis="undeterminable; no mtime and no per-line year"` while anchoring the
naive instant to a fixed sentinel that is clearly flagged, never `now()`). Any
choice must be a pure function of the evidence, not the clock.

---

### CR-03: RFC3164 year inference is wrong for same-month and intra-month backward rolls

**File:** `src/pyautopsy/log/timeresolve.py:190-195`
**Issue:** `infer_years` decrements the year only on a strict month *decrease*
going backward in time (`if cur_mon > next_mon`). It compares **month only**, so:

- A backward jump *within the same month* across a year boundary (e.g. records
  spanning `Dec 31 2024` → `Dec 01 2025`, or any set where two adjacent records
  share a month but the earlier one is a year older) is never detected — both get
  the same year. Day/time are ignored entirely.
- More importantly, the logic assumes a single monotonic non-decreasing month
  sequence. Real rotated auth logs commonly contain out-of-order or repeated
  months (e.g. syslog interleaving, a `Jan` line followed by a stray `Dec`
  continuation), and any `cur_mon > next_mon` flips the year for *all* preceding
  records, cascading a one-off anomaly into a wholesale year shift for the rest of
  the file.

The result is events mis-dated by a full year in a timeline the report presents
as forensic truth. The honesty flagging (`year_inferred`) records the *wrong*
inferred year as if it were the method's considered output.

**Fix:** Compare the full `(month, day, hour, minute, second)` tuple, not just the
month, when deciding a backward roll, and bound the year adjustment so a single
anomalous record cannot cascade (e.g. detect a roll only on a genuine
descending-then-ascending wrap, and clamp). Add fixtures covering: same-month
year boundary, an out-of-order single line, and a clean Dec→Jan rotation. At
minimum, document and test the exact month-only assumption if it is intentional —
but month-only is demonstrably incorrect for the same-month boundary case.

---

## Warnings

### WR-01: `run_search` `ioc_terms` parameter is dead from the CLI; `--ioc` works but direct IOC terms cannot be passed

**File:** `src/pyautopsy/core/search.py:119`, `src/pyautopsy/cli/main.py:663-671`
**Issue:** `run_search` accepts `ioc_terms: Sequence[bytes] = ()` and merges it
into `ioc_all` (`search.py:160`). The CLI `search` command never passes
`ioc_terms` (only `ioc_file`), and `analyze` calls `run_search` with only
`terms=[...]` (`analyze.py:360-365`). So `ioc_terms` is reachable only from tests.
Not a correctness bug on its own, but it is an untested, unwired public parameter
that suggests an intended capability (direct IOC literals) that no command
exposes. Confirm whether this is intentional dead surface or a missing CLI wiring.
**Fix:** Either wire a `--ioc-term` repeatable option through to `ioc_terms`, or
drop the parameter to keep the surface honest.

### WR-02: Hash-arm SearchHit uses `volume_id=0`/`volume_offset=0` fallback when the file row is missing — non-deterministic/ambiguous ordering

**File:** `src/pyautopsy/core/search.py:229-247`
**Issue:** For each known-bad-hash `KnownMatch`, the code looks up
`file_by_id.get(m.file_id)` and, when `fr is None`, emits a `SearchHit` with
`volume_id=0, volume_offset=0, path=None`. `match_bad_hashes` only produces
matches for rows whose `id` is non-None and present in `files`, so `fr` should
never be `None` in practice — but if it ever is, the hit collapses to volume
`(0,0)` and sorts ambiguously against real volume-0 hits in
`get_search_hits` (ordered by `volume_id, volume_offset, byte_offset, term, id`,
`store.py:778`). With `byte_offset=None` for all hash hits, ties break only on
`term` then `id`; the `(0,0)` fallback can interleave hash hits with genuine
volume-0 content hits unpredictably.
**Fix:** Since `m.file_id` always maps to a known row here, assert it
(`assert fr is not None`) or skip emitting a hit when the row is missing rather
than fabricating a `(0,0)` provenance that misrepresents where the match lives.

### WR-03: `_latest_evidence_source_id` runs raw SQL in the orchestrator tier

**File:** `src/pyautopsy/core/logs.py:104-114`, `src/pyautopsy/core/search.py:86-96`
**Issue:** Both `run_logs` and `run_search` execute
`store.connection.execute("SELECT id FROM evidence_sources ORDER BY id DESC ...")`
directly against the connection. CLAUDE.md / the store docstring state CaseStore
is the sole DB access point and "no raw SQL is permitted elsewhere"
(`store.py:1-8`). This is read-only SQL so it is not a soundness hazard, but it
violates the stated boundary and duplicates a query that belongs behind a store
method (the same SELECT is copy-pasted in both orchestrators).
**Fix:** Add `CaseStore.get_latest_evidence_source_id()` (or `latest_source()`)
and call it from both orchestrators; remove the inline SQL.

### WR-04: `run_logs` lists `MountedSourceError` in expected errors but never imports it into the union correctly vs. asserts after open only

**File:** `src/pyautopsy/core/logs.py:234-263`
**Issue:** `assert_source_not_mounted` is called before open (line 235) and again
after open (line 263). The post-open call happens *inside* the `try` whose
handler is `_EXPECTED_LOGS_ERRORS`, but the pre-open call at line 235 is **outside
the try/except and outside the audit scope** — if it raises `MountedSourceError`,
no `logs.error` FAIL audit event is written (the audit log is constructed at line
245, after the guard). The module docstring (step 5) and `analyze` rely on a FAIL
audit event being recorded before re-raise (D-08). `run_search` has the same shape
(`search.py:149` pre-open guard before `audit` is built at `search.py:166`).
**Fix:** Either construct the audit log before the first guard and wrap the
pre-open assertion so a mounted-source rejection is audited, or document that the
pre-open guard is intentionally pre-audit and ensure the CLI still maps it (it
does map `MountedSourceError` to a clean exit, but with no audit trail — which
contradicts the D-08 "record FAIL before non-zero exit" claim in the CLI
docstring, `cli/main.py:8-10`).

### WR-05: RFC3164 grammar requires a host token, dropping headerless/relay lines into the unmatched bucket

**File:** `src/pyautopsy/log/_grammar.py:22-27`
**Issue:** The `RFC3164` regex mandates `\s+(?P<host>\S+)\s+` between the
timestamp and the program. Many real auth.log lines (especially from local
journald-to-text or certain sshd configs) omit the host, or the "program" token
contains characters excluded by `[^\s:\[]+`. Such lines fall through to
`parse_line` returning `None`, and the auth parser emits them as raw unmatched
records with `raw_timestamp=None` — which then take the seed-year-Jan-1 fallback
(`logs.py:179`), mis-dating a line that actually carried a parseable timestamp.
This is a coverage/correctness gap that silently degrades timeline accuracy rather
than crashing.
**Fix:** Make the host token optional or add a hostless RFC3164 variant, and add
fixtures for hostless/relay-prefixed lines. At minimum, attempt to salvage the
timestamp head even when the rest of the line does not match.

### WR-06: `_DATEEXT_SUFFIX` maps dates to negative indices that collide with the numeric scheme and corrupt completeness findings

**File:** `src/pyautopsy/log/discover.py:113-117`, `:175-186`
**Issue:** A dateext member (`auth.log-20250131`) is mapped to
`index = -int("20250131")` (a large negative number). `_completeness`
(`discover.py:175`) then computes `numeric = sorted({m.index for m if m.index >= 0})`,
which **excludes all dateext members** from the present/missing computation, so a
purely dateext-rotated set reports `present_indices=()` / `missing` derived only
from index 0. The completeness finding (D-45 honesty) is therefore wrong for
dateext rotation, and `order_rotated_set`'s `order_key = (-index, ...)` makes the
negative indices sort as enormous positive keys, placing dateext members
*newest-first* rather than oldest-first relative to numeric members in a mixed
set. Note also this finding is computed but **never persisted or surfaced** in the
report (see WR-07).
**Fix:** Use a separate, sign-consistent ordering domain for dateext (e.g. order
by parsed date ascending) and include dateext members in the completeness count,
or explicitly document dateext as out-of-scope and reject it from the set.

### WR-07: Log completeness finding (D-45) is computed but never recorded or reported

**File:** `src/pyautopsy/log/discover.py:173-193`, `src/pyautopsy/core/logs.py:292-305`
**Issue:** `discover_log_sets` builds a `CompletenessFinding` per set
(`LogSet.finding`), and the module docstring frames it as the D-45 honesty signal
("which indices are present/absent"). But `run_logs` iterates
`discover.discover_log_sets(rows)` and uses only `log_set.members` /
`log_set.basename` (`logs.py:292`, `_parse_log_set` at `logs.py:376`); it never
reads `log_set.finding`, never writes it to `attributes`, and the report's
`log_findings` section derives provenance solely from per-event `year_inferred`/
`assumed_timezone` (`assemble.py:445-454`). So a "log set may be incomplete:
rotation indices [...] absent" finding is silently dropped — the report cannot
disclose a gap in the rotation chain, defeating the stated D-45 honesty goal.
**Fix:** Thread the completeness finding into the events' `attributes` (or a
dedicated findings list) so it reaches `assemble_report_body` and is surfaced in
the Log Findings section.

---

## Info

### IN-01: Unused import `RecoveredEntry`/`DeletedInode` re-export churn vs. actual seam use

**File:** `src/pyautopsy/evidence/filesystem.py:31-50`
**Issue:** The `__all__` exports `DeletedInode`, `RecoveredEntry`, `recover_meta`,
etc., which are recovery-phase APIs unrelated to Phase 5; not a defect, but the
Phase-5 additions (`iter_unallocated_blocks`, `block_size`) sit alongside them
with no grouping. Cosmetic.
**Fix:** None required; consider a `# --- search seam (Phase 5) ---` comment band
for navigability.

### IN-02: `_read_text` decodes with `errors="replace"` then `/etc/timezone` parse takes only first line — silent truncation of multi-zone files

**File:** `src/pyautopsy/log/timeresolve.py:98-105`
**Issue:** `text.strip().splitlines()[0]` takes the first line of `/etc/timezone`.
A malformed multi-line file is silently reduced to its first line. Acceptable
(Debian `/etc/timezone` is single-line), but worth a one-line comment that
multi-line content is intentionally ignored.
**Fix:** Add a clarifying comment; no behavior change needed.

### IN-03: `auth_events` count depends on `source == "auth"` literal coupling

**File:** `src/pyautopsy/core/logs.py:305`
**Issue:** `auth_events += sum(1 for e in set_events if e.source == "auth")` couples
the count to the literal parser name string. If `AuthParser.name` changes, the
count silently goes to zero with no error. Low risk (the name is stable) but a
magic-string coupling.
**Fix:** Reference `auth.AuthParser.name` rather than the literal `"auth"`.

### IN-04: `search_bytes` `region` defaults to `"unallocated"` with `block_size=0`, so `block_index` is never set on blob scans

**File:** `src/pyautopsy/search/content.py:217-270`
**Issue:** `search_bytes` defaults `region="unallocated"` but always calls `_emit`
with `block_size=0`, so `_emit`'s `block_index` computation is skipped
(`content.py:199-200`). A caller using `search_bytes` directly for an unallocated
blob gets `block_index=None`. Harmless for the orchestrated path (which uses
`search_image`), but the default is misleading.
**Fix:** Default `region="allocated"` for the generic blob scanner, or document
that `block_index` is only populated via `search_image`.

---

_Reviewed: 2026-05-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
