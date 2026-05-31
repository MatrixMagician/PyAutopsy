---
phase: 03-timeline-mvp-report
reviewed: 2026-05-31T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - src/pyautopsy/timeline/builder.py
  - src/pyautopsy/report/assemble.py
  - src/pyautopsy/report/htmlreport.py
  - src/pyautopsy/report/jsonreport.py
  - src/pyautopsy/core/analyze.py
  - src/pyautopsy/cli/main.py
  - src/pyautopsy/case/store.py
  - src/pyautopsy/case/models.py
  - src/pyautopsy/case/schema.sql
findings:
  critical: 1
  warning: 5
  info: 4
  total: 10
status: resolved
resolution: 2026-05-31 — CR-01 + WR-01..05 fixed (commits d632123, dbcb168, 8ec29a3, 08b9d8b, bdf052e, 456eefc, 1f831d2); 173 tests + ruff + mypy green. IN-01..04 (Info) deferred as non-blocking.
---

# Phase 3: Code Review Report

**Reviewed:** 2026-05-31
**Depth:** standard
**Files Reviewed:** 9
**Status:** resolved (Critical + Warning fixed; Info deferred)

## Summary

Reviewed the Phase 3 timeline builder, report assembly/render/serialize layer,
the `analyze` orchestrator, the CLI command, and the case-store/schema changes
that back them. The phase-specific concerns (HTML autoescape, path confinement,
verbatim timestamp copying, no native imports, determinism) are mostly handled
well: autoescape is on with no `| safe`/`Markup()`, the timeline copies `*_utc`
strings verbatim and skips `None`, no `pytsk3`/`pyewf` imports appear, and the
JSON/HTML bodies carry no wall-clock.

However the central determinism guarantee (CLI-02/D-26 byte-identical reports)
has a real hole: the documented "no two events tie on all six ORDER BY keys"
claim is false for deleted/orphan entries that share a reclaimed path and a NULL
`meta_addr`, so the timeline order — and therefore `report.json`/`report.html`
bytes — can vary across runs by falling through to SQLite's rowid tiebreak.
There are also several robustness gaps (missing path confinement on the
run-metadata sidecar, per-volume `fs_type` aggregation ambiguity, hardcoded
integrity PASS, a misleading docstring on the confinement guard).

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: D-26 total order is not actually total — determinism breaks on tied deleted entries

**File:** `src/pyautopsy/case/store.py:530-557`, `src/pyautopsy/timeline/builder.py:56-74`

**Issue:** The store documents and relies on the six-column ORDER BY
(`ts_utc, volume_id, volume_offset, path, event_type, meta_addr`) being a *total*
order: "no two distinct events can tie on all six keys, so the result never
depends on sqlite's rowid tiebreak" (store.py:535-537). This claim is false.

Two **distinct** timeline events can tie on all six keys:

- `meta_addr` is nullable (`FileRow.meta_addr` defaults to `None`; walk.py:403
  copies `entry.meta_addr` verbatim and the walk docstring at walk.py:175 states
  "Meta-less entries (no `meta_addr`) keep null MACB"). Deleted/orphan entries
  routinely have NULL `meta_addr`.
- Deleted/unallocated entries can share the same reclaimed `path` within the
  same `(volume_id, volume_offset)`.
- Such two files each explode (builder.py:56-74) a `"modified"` event with the
  identical `ts_utc` (e.g. both recovered with the same mtime, or both NULL→no
  event is fine, but matching non-null mtimes tie).

When all six keys tie, SQLite falls back to an unspecified order (effectively
rowid/insertion order), which is **not guaranteed stable** and is exactly the
non-determinism the phase forbids. Because `assemble_report_body` consumes this
list verbatim (assemble.py:177-189) and both `report.json` (jsonreport.py:76)
and `report.html` (htmlreport.py:82) are derived from it, the report bytes can
differ across runs on the same fixture — violating CLI-02/D-25.

Additionally, SQLite sorts `NULL` first by default; mixing NULL and non-NULL
`meta_addr` is deterministic *within* one DB, but the tie case above bypasses
`meta_addr` entirely.

**Fix:** Append a guaranteed-unique, content-derived tiebreaker to the total
order so it never falls through to rowid. The natural choice is the source row
identity, but `file_id`/`id` are surrogate keys (insertion-dependent) and would
reintroduce non-determinism if rows are inserted in a different order. Prefer
appending the remaining content columns then `file_id` only as a last resort
documented as stable-within-a-run, OR make the tie impossible by including a
deterministic discriminator. Concretely, extend the ORDER BY with `source` and
`actor` (content-derived) before any surrogate key:

```python
sql = (
    "SELECT * FROM timeline_events WHERE evidence_source_id = ? "
    "ORDER BY ts_utc, volume_id, volume_offset, path, event_type, "
    "meta_addr, source, actor, id"
)
```

and update the index (schema.sql:147-148) and the docstring to stop claiming the
six-column order is total. If `id` is used as the final tiebreak, the builder
must also guarantee a deterministic insertion order (it currently inserts in
`get_files` id order, builder.py:98 → store.py:418-422, which is stable), and
that guarantee must be documented as load-bearing rather than the false
"can never tie" claim.

## Warnings

### WR-01: run_metadata.json sidecar skips the path-confinement guard the report writers use

**File:** `src/pyautopsy/core/analyze.py:143-147`

**Issue:** `write_json` and `render_html` both route through
`_confined_reports_dir` (jsonreport.py:36-54), which re-checks the resolved
reports path with `_is_within` to defend against a symlinked/relative `case_dir`
redirecting output outside the case (threat T-03-07). `_write_run_metadata`
deliberately does NOT — it just does `(case_dir / _REPORTS_SUBDIR).resolve()`
and writes. The docstring even notes "the reports dir was already created by
`write_json`/`render_html`", but it still independently resolves and writes a
file without the confinement assertion. If `case_dir/reports` is a symlink to
outside the case (e.g. an attacker-staged case directory), the sidecar is
written outside the confinement boundary while the two reports are not — an
inconsistent and weaker guarantee for a forensic-output path.

**Fix:** Route the sidecar through the same guard:

```python
from pyautopsy.report.jsonreport import _confined_reports_dir

def _write_run_metadata(case_dir: Path, run_metadata: dict[str, object]) -> Path:
    reports_dir = _confined_reports_dir(case_dir)
    path = reports_dir / _RUN_METADATA_NAME
    serialized = json.dumps(run_metadata, sort_keys=True, ensure_ascii=False)
    path.write_text(serialized, encoding="utf-8")
    return path
```

### WR-02: Integrity PASS is hardcoded `True` — report can overclaim a passing verification

**File:** `src/pyautopsy/report/assemble.py:195`, `:235-240`, `:261-265`

**Issue:** `integrity_pass = True` is hardcoded with the justification "a
readable source means PASS" because ingest rolls back on FAIL. But the report
*body* is the evidence-presentation artifact, and it asserts
`acquisition_compare_pass: True`, `reverify_pass: True`, and emits
`_INTEGRITY_PASS_COPY` ("source hash matches acquisition value and end-of-run
re-verification") unconditionally. The store actually persists
`acquisition_verified` and hash columns (`EvidenceSource.sha256`/`md5`,
`acquired_utc`) — the real verification outcome is recoverable. Hardcoding PASS
means:
- If `--acquisition-hash` was never supplied, the report still claims
  "source hash matches acquisition value" — an overclaim (D-28 forbids
  overclaiming). The ingest path treats "not supplied" as a distinct state
  (`acquisition_verified is None`, cli/main.py:119-125), but the report
  flattens it to PASS.
- The `_INTEGRITY_FAIL_COPY` branch is dead code in practice; the FAIL path can
  never render even if a future caller assembles a report over a DB that
  recorded a mismatch.

**Fix:** Derive the integrity booleans/copy from the persisted evidence record
rather than a constant. Distinguish at least three states — verified-pass,
not-supplied (no acquisition hash to compare against), and fail — and surface the
not-supplied state honestly instead of claiming a hash match that never
happened. Read the stored `acquisition_verified`/attributes on the
`EvidenceSource` and branch on it.

### WR-03: per-volume aggregation silently keeps the first row's fs_type, hiding mixed/ambiguous data

**File:** `src/pyautopsy/report/assemble.py:124-140`

**Issue:** The per-volume bucket is keyed on `(volume_id, volume_offset)` and
records `fs_type` only from the *first* file row seen for that key
(`setdefault`). If two rows under the same volume key carry different `fs_type`
values (which can happen with NULL vs non-NULL `fs_type`, or a mislabeled
deleted entry), the divergence is silently dropped and the report presents a
single fs_type as authoritative. For a forensic report this is a quiet
correctness/over-claim risk. It is also order-sensitive: which fs_type "wins"
depends on `get_files` id order, so it is at least deterministic, but it can
present a NULL fs_type if the first row happens to be meta-less.

**Fix:** Either assert/aggregate fs_type per volume (e.g. collect the distinct
set and surface it, or prefer the non-null modal value) or document that fs_type
is a representative sample. At minimum, prefer a non-null fs_type over a null one
when building the bucket so the report does not show a blank fs for a volume that
clearly has one.

### WR-04: `_confined_reports_dir` docstring claims a realpath check it does not perform on the final file

**File:** `src/pyautopsy/report/jsonreport.py:36-54`, `:72-77`

**Issue:** The function confines the *directory* (`reports_dir`) and asserts it
is within `case_root`. The docstring (and the htmlreport.py:20-21 module
docstring) describes this as confining "report output". But the actual written
file path (`reports_dir / _JSON_NAME`, jsonreport.py:73) is never re-resolved or
re-checked. The filename is a fixed constant so traversal via the name is not
possible, but if `reports_dir` itself contains a symlinked child the guard does
not catch it — and more importantly the guard resolves `reports_dir` *before*
`mkdir`, so a TOCTOU window exists between the `_is_within` check (line 49) and
the `mkdir`/`write_text`. For a forensic tool the confinement claim should match
what is enforced.

**Fix:** Re-resolve and re-check the final file path after `mkdir`, or document
that confinement covers only the fixed-name file under a verified directory and
that the directory is created with `parents=True` from a resolved root. Tighten
the docstring so it does not overstate the guarantee.

### WR-05: `actor` only set when uid OR gid present, but format always emits both — produces misleading `uid=None,gid=5`

**File:** `src/pyautopsy/timeline/builder.py:47-49`

**Issue:** `actor` is built only when `uid is not None or gid is not None`, but
the format string always interpolates both: `f"uid={file_row.uid},gid={file_row.gid}"`.
If only one is populated, the other renders as the literal string `None`
(e.g. `"uid=1000,gid=None"`). This is persisted into `timeline_events.actor`
and rendered verbatim in the report. For an evidence-presentation artifact,
emitting `gid=None` as attribution is misleading and inconsistent — a reviewer
cannot tell "gid unknown" from a literal value.

**Fix:** Emit only the populated components, e.g.:

```python
parts = []
if file_row.uid is not None:
    parts.append(f"uid={file_row.uid}")
if file_row.gid is not None:
    parts.append(f"gid={file_row.gid}")
actor = ",".join(parts) if parts else None
```

## Info

### IN-01: HTML template "Showing N of M" disclosure rendered twice when truncated

**File:** `src/pyautopsy/report/templates/report.html.j2:229-233`, `:258-262`

**Issue:** The truncation disclosure block is emitted both above the table
(lines 229-233) and below it (lines 258-262) under the same
`timeline_total > timeline|length` condition. When truncated, the reader sees the
identical warning twice. This is likely intentional (top+bottom for long tables)
but is undocumented duplicated markup; if the copy ever changes, the two copies
can drift.

**Fix:** If the double disclosure is intentional, factor the text into a single
`{% set %}` / macro so the two placements cannot diverge. Otherwise drop one.

### IN-02: `explode = _explode` public alias adds an indirection with no behavioral value

**File:** `src/pyautopsy/timeline/builder.py:78`

**Issue:** `explode` is a bare alias of the private `_explode`. Exporting a
"public" name that is literally the private function (also re-exported in
`timeline/__init__.py:13`) is redundant indirection; either the transform is
public (name it `explode` directly) or it is private (don't export it). Minor
maintainability smell.

**Fix:** Rename `_explode` to `explode` and drop the alias, or keep `_explode`
private and have tests import it directly.

### IN-03: provenance dedup uses `repr(sorted(...))` as a dict marker — works but fragile

**File:** `src/pyautopsy/report/assemble.py:160-163`

**Issue:** Distinct provenance flag-sets are deduplicated by using
`repr(sorted(surfaced.items()))` as a dict key. This is correct for the current
flat `str->str` shape (the comment acknowledges this constraint), but it is a
fragile, non-obvious idiom: if a future value is ever non-str the `repr` could
collide or reorder. The determinism relies on `repr` of a sorted list of string
tuples being stable, which it is, but the intent is obscured.

**Fix:** Use a `frozenset(surfaced.items())` or a tuple of sorted items directly
as the dict key (still hashable, no `repr` round-trip), and keep the final
`sorted()` for output ordering.

### IN-04: `durations={}` always passed empty — run metadata never carries stage timings

**File:** `src/pyautopsy/core/analyze.py:254-258`

**Issue:** `build_run_metadata` accepts a `durations` dict and `run_id`, but the
orchestrator always passes `durations={}` and omits `run_id`. The sidecar
therefore never records the per-stage timings its own schema advertises
(assemble.py:289/305). Not a correctness bug (run metadata is non-analytical and
out of the determinism contract), but the capability is wired up and left inert,
which is dead-ish interface surface.

**Fix:** Either populate `durations` (wrap ingest/walk/timeline/report with a
monotonic clock) or drop the parameter until a consumer needs it, so the
interface does not imply a guarantee it never delivers.

---

_Reviewed: 2026-05-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
