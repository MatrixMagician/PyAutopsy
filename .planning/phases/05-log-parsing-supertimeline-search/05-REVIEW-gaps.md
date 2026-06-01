---
phase: 05-log-parsing-supertimeline-search
reviewed: 2026-06-01T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - src/pyautopsy/case/__init__.py
  - src/pyautopsy/case/models.py
  - src/pyautopsy/case/schema.sql
  - src/pyautopsy/case/store.py
  - src/pyautopsy/core/logs.py
  - src/pyautopsy/log/shell_history.py
  - src/pyautopsy/report/assemble.py
  - src/pyautopsy/report/templates/report.html.j2
  - tests/fixtures/make_fixtures.py
  - tests/fixtures/log_search_groundtruth.json
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 5: Code Review Report (Gap-Closure Plans 05-05 + 05-06)

**Reviewed:** 2026-06-01
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Adversarial review of the two gap-closure changes on phase 05:

- **05-05 (G-2):** an additive `log_findings` table threading D-44 shell-history
  tamperability + D-45 completeness disclosures from the parsers through
  `core/logs.py:run_logs` into the `CaseStore`, rendered in
  `report/assemble.py` + `report.html.j2`.
- **05-06 (G-1):** reconciliation of `make_fixtures.py` year constants +
  `log_search_groundtruth.json` to the committed image's frozen mtime anchor.

I verified each of the focus areas explicitly:

- **SQL injection / parameterization:** Clean. The new `log_findings` write path
  (`insert_log_findings` → `_LOG_FINDING_INSERT_SQL` / `_log_finding_params`) and
  read path (`get_log_findings`) use the same column-list + positional `?`
  parameter idiom as every other table; no f-string/`%`/concatenation of
  evidence-controlled data into SQL anywhere in the new code. `category`,
  `subject`, `detail` and `attributes` are all bound as parameters. **No BLOCKER.**
- **Transaction atomicity / sole-writer:** Correct. `run_logs` persists fs-backfill
  events, log events, AND log findings inside ONE `store.transaction()` block
  (logs.py:493-500); `insert_log_findings` defers its commit via
  `_commit_unless_in_transaction`, so the three writes land atomically and roll back
  together. CaseStore remains the sole writer. **No BLOCKER.**
- **Neutral observed-fact framing (D-44):** Correct. The tamperability `detail`
  (shell_history.py:179-183) and the report intros (`_LOG_DISCLOSURE_INTRO`,
  assemble.py:229-237) state only the observed fact that history is editable and
  order is not chronological truth; no intent/guilt is imputed. **No BLOCKER.**
- **Template escaping / XSS:** Safe. `render_html` builds the Jinja2 `Environment`
  with `autoescape=select_autoescape(["html","j2"])` and the template is
  `report.html.j2`, so the evidence-controlled `d.subject` (a `/home/<user>` path)
  and `d.detail` are HTML-escaped. **No BLOCKER.**
- **Determinism / byte-identical default path:** Holds. On the default `analyze`
  path `get_log_findings` returns `[]`, so `disclosures` renders `[]`
  (asserted by `tests/test_reproducibility.py:496`). Finding insertion order is
  deterministic (fixed `basenames` order in `discover_log_sets`, walk-encounter
  order in `discover_shell_histories`), and `get_log_findings` reads back in
  insertion-deterministic `id` order. **No BLOCKER.**

No BLOCKER-class defects were found. The findings below are correctness/robustness
WARNINGs and quality INFO items.

## Warnings

### WR-01: `_seed_year_from_mtime` swallows a `mtime` attribute-name regression silently

**File:** `src/pyautopsy/core/logs.py:174-198` (also `_parse_log_set`
`getattr(row, "read_random", None)` / `getattr(row, "size", 0)` at lines 578-581)

**Issue:** The seed-year logic reads the evidence anchor via
`getattr(row, "mtime", 0)` with a default of `0`. The FS-seam walk row currently
exposes a raw-int `mtime` field (`filesystem.py:233`), so this works today. But if
the seam row is ever renamed (e.g. to `mtime_epoch`) or refactored to expose only
`mtime_utc`, the `getattr` default silently makes `mtime == 0` for EVERY member,
which cascades into `seed_unresolved=True` for the entire image — every
RFC3164/shell event then sorts to `_UNDATED_SORT_LAST_ISO` (9999-...) and the
super-timeline silently loses its real chronology with no error. The same brittle
`getattr(..., default)` pattern is used for `read_random` and `size`. For a
forensic tool whose core promise is an honest timeline, a silent, undetected
"everything is undated" failure mode is a real robustness defect.

**Fix:** Bind to the typed seam row contract instead of a stringly-typed
`getattr` with a swallowing default. Either type `rows_by_path` to the concrete
seam row type and access `row.mtime` directly (let an `AttributeError` surface as
a real bug, not a silent zero), or assert the attribute exists once:
```python
row = rows_by_path.get(member_path)
mtime = row.mtime if row is not None else 0   # typed access; no silent default
```
At minimum add a test that fails if the seam row stops exposing `mtime`.

### WR-02: Completeness `LogFinding` emitted for every shell-history file produces low-signal/noisy disclosures

**File:** `src/pyautopsy/core/logs.py:431-450` together with
`src/pyautopsy/log/discover.py:268-307`

**Issue:** `run_logs` emits one `category="completeness"` `LogFinding` for EVERY
discovered `LogSet`, unconditionally — including each single-member shell-history
"set", whose `finding.note` is the boilerplate `"shell history is a single,
non-rotated per-user file"` (discover.py:301-306). The D-45 completeness disclosure
is meaningful for a rotated `/var/log` set (which indices are present/absent); for a
non-rotated dotfile it is content-free noise. On a typical multi-user image this
emits one such empty-signal completeness disclosure per history file (plus the real
tamperability disclosure), padding the report's honesty section with rows that
disclose nothing actionable. It also slightly muddies the D-45 contract (a
"completeness" finding that can never report a gap).

**Fix:** Only emit a completeness `LogFinding` when the set can actually be
incomplete — i.e. skip it for single-member shell-history sets, or gate on
`fnd.member_count > 1 or fnd.missing_indices`:
```python
fnd = log_set.finding
if fnd.member_count > 1 or fnd.missing_indices:
    all_findings.append(LogFinding(category="completeness", ...))
```
This keeps the rotated-set completeness signal while dropping the per-history
boilerplate. (Determinism is unaffected — the filter is order-preserving.)

### WR-03: `findings_for` re-parses the entire history file a second time, decoupling findings from the records actually emitted

**File:** `src/pyautopsy/log/shell_history.py:209-221` and its call site
`src/pyautopsy/core/logs.py:595-605`

**Issue:** `_parse_log_set` calls `parser.parse(text, ctx)` (which internally calls
`parse(...).records`) and THEN separately calls `parser.findings_for(text, ctx)`
(which calls `parse(...).findings`). The file is fully re-parsed a second time. Two
problems: (1) the `ShellHistoryResult` object that pairs records with their
findings is discarded twice over, so the findings are no longer guaranteed to
correspond to the same parse that produced the events the report counts; (2) any
future per-content finding (e.g. "history -c observed at line N") computed from
parse state would diverge between the two calls. Today the tamperability finding is
a constant string so the divergence is harmless, but the design re-derives the same
result from the same input twice and relies on `parse` being pure — a latent
correctness trap if `findings_for` ever becomes content-sensitive.

**Fix:** Parse once and read both halves off the single `ShellHistoryResult`. Have
the orchestrator obtain records and findings from one call (e.g. add an optional
protocol method that returns the full result, or have the registry expose the
result object for parsers that produce one), so events and findings provably come
from the same parse.

### WR-04: `findings_count` is reported but the per-history `tamperability` finding is unconditional, so the count is not a useful integrity signal

**File:** `src/pyautopsy/core/logs.py:451-462`, `534-540`;
`src/pyautopsy/log/shell_history.py:179-184`

**Issue:** `LogsResult.findings_count` and the audit `findings_count` are surfaced
as analytical outputs, but a tamperability finding is emitted for EVERY shell-history
file regardless of its content (the `findings` list in `parse` is a hardcoded
single-element list, shell_history.py:179). Combined with WR-02 (a completeness
finding per set including each history), `findings_count` is essentially
`len(discovered_sets) + len(history_files)` rather than a count of substantive
disclosures. A reader of the CLI summary / audit trail will read a non-zero
`findings_count` as "the tool found something noteworthy", when it may be entirely
boilerplate. This is a framing/over-claim risk for an evidence-presentation tool.

**Fix:** Either (a) document `findings_count` explicitly as "honesty disclosures
emitted (always >=1 per history/log set)" so it is not misread as a count of
anomalies, or (b) after applying WR-02, keep the tamperability finding (it is a
correct standing D-44 caveat) but report it separately from any
gap/anomaly-bearing completeness findings so the count distinguishes "standing
caveat" from "actual completeness gap detected".

## Info

### IN-01: `LogFinding.detail` / `subject` are nullable in the model but the schema allows NULL category-less reads with no validation

**File:** `src/pyautopsy/case/models.py:283-288`, `src/pyautopsy/case/schema.sql:138-145`

**Issue:** `category` is `NOT NULL` in SQL and required in the dataclass (good), but
the dataclass performs no validation that `category` is one of the documented domain
values `{"tamperability","completeness"}`. A typo in a future producer (e.g.
`category="tamperabilty"`) would persist silently and the report would render it
verbatim. The codebase elsewhere relies on free-form strings by design (D-30 tiers),
so this is consistent — but a small guard would catch producer typos.

**Fix:** Optionally validate `category` in `LogFinding.__post_init__` against the
known set, or add a constant tuple of allowed categories shared by producer + model.

### IN-02: `disclosures` dict key set is unconditionally present in the body even on the default path

**File:** `src/pyautopsy/report/assemble.py:480-505`

**Issue:** `log_findings["disclosures"]` and `disclosures_intro` are always added to
the body. This is intentional and correct for determinism (empty list on the default
path, asserted by the reproducibility test), and the template guards rendering with
`{% if body.log_findings.disclosures %}`. Noting only that the `disclosures_intro`
string is carried in the body even when there are zero disclosures — harmless (the
template never renders it when the list is empty) but it does mean the JSON body
always carries the intro copy. Not a defect; documented for completeness.

**Fix:** None required. If JSON-body minimalism is desired, the intro could be moved
to render-time only, but that would break the body-is-single-source-of-truth pattern
— leave as-is.

### IN-03: Year-reconciliation sidecar and constants agree, but the relationship is asserted only by comment

**File:** `tests/fixtures/make_fixtures.py:756-763`,
`tests/fixtures/log_search_groundtruth.json:23,32`

**Issue:** The 05-06 reconciliation sets `LOG_SEARCH_YEAR = 2023` /
`LOG_SEARCH_PREV_YEAR = 2022` to match the committed image's frozen
`_EXT4_FAKE_TIME = 1700000000` (2023-11-14 UTC). The sidecar JSON mirrors these
(`"year": 2023`, `"prev_year": 2022`). I confirmed `1700000000` decodes to
2023-11-14 UTC, so `mtime.year == 2023` and the Dec lines fall in 2022 — the
constants are correct. However the link between `_EXT4_FAKE_TIME` and
`LOG_SEARCH_YEAR` is enforced only by a prose comment; a future bump of
`_EXT4_FAKE_TIME` across a year boundary (without rebuilding the committed image)
would silently desync them again (the exact G-1 drift this plan closed).

**Fix:** Derive the year from the anchor instead of hardcoding, so they cannot drift:
```python
from datetime import datetime, timezone
LOG_SEARCH_YEAR = datetime.fromtimestamp(int(_EXT4_FAKE_TIME), tz=timezone.utc).year
LOG_SEARCH_PREV_YEAR = LOG_SEARCH_YEAR - 1
```
(The committed image is not rebuilt, so this changes only the derivation, not the
value.) The existing guard test from commit `cc2ce16` mitigates this, so it is INFO.

### IN-04: Comment in schema claims `timeline_events` is UNTOUCHED but `run_logs` still backfills filesystem events into it

**File:** `src/pyautopsy/case/schema.sql:131-132` ("`timeline_events` is UNTOUCHED
(D-47)") vs `src/pyautopsy/core/logs.py:486-496`

**Issue:** The `log_findings` schema comment states `timeline_events` is UNTOUCHED.
That is true for the *schema* (no DDL change), but `run_logs` does write into
`timeline_events` (the one-time filesystem-MACB backfill + the log events) within
the same transaction. A reader skimming the schema comment could misread it as "the
logs path does not write timeline_events at all." Pure documentation clarity.

**Fix:** Tighten the comment to "the `timeline_events` *schema* is UNTOUCHED (no DDL
/ backfill of existing rows; D-47)" to avoid implying no inserts occur.

### IN-05: `_parse_log_set` silently drops a member when its row/`read_random` is absent

**File:** `src/pyautopsy/core/logs.py:576-583`

**Issue:** When `rows_by_path.get(member.path)` is `None` or the row lacks
`read_random`, the member is `continue`'d with no audit/finding recorded. For a
discovered-but-unreadable rotated member (e.g. a path the walk indexed but whose
content reader is unavailable), the set is silently parsed as if that member did not
exist — which can under-report events without any honesty disclosure, slightly at
odds with the D-45 completeness intent (the completeness finding is computed from
discovery, not from what was actually readable).

**Fix:** When a discovered member cannot be read, record it (an audit
`logs.member_skipped` event, or fold it into the completeness finding's attributes
as an unreadable index) so the honesty trail reflects what was actually parsed
versus discovered.

---

_Reviewed: 2026-06-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
