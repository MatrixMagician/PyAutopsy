---
phase: 04-deleted-recovery-known-file-filtering
reviewed: 2026-05-31T00:00:00Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - src/pyautopsy/evidence/filesystem.py
  - src/pyautopsy/core/recover.py
  - src/pyautopsy/core/knownfiles.py
  - src/pyautopsy/core/analyze.py
  - src/pyautopsy/filter/nsrl.py
  - src/pyautopsy/filter/hashsets.py
  - src/pyautopsy/case/store.py
  - src/pyautopsy/case/schema.sql
  - src/pyautopsy/case/models.py
  - src/pyautopsy/cli/main.py
  - src/pyautopsy/report/assemble.py
findings:
  blocker: 2
  warning: 5
  info: 3
  total: 10
status: resolved
resolved_note: "All 2 blockers (BL-01 inventory double-count, BL-02 uncaught sqlite3.Error) and all 5 warnings (WR-01..05) fixed in commits ada0f8a..ae3ae01; 185 tests pass, ruff+mypy clean. WR-05 structural pin intentionally not applied (would violate D-14 native-seam contract) — regression test used instead. Info items IN-01..03 left as-is."
---

# Phase 4: Code Review Report

**Reviewed:** 2026-05-31
**Depth:** deep
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the Phase-4 deleted-recovery + known-file-filtering vertical slice with a
focus on the locked invariants D-29..D-42 (determinism, NSRL case-folding, SQL
safety, single native seam, sole-writer, read-only soundness, honesty, overwrite
detection). The forensic-soundness fundamentals are largely well-engineered and
defensible:

- **D-14 native seam holds** — only `evidence/filesystem.py` imports `pytsk3`; `recover.py`/`knownfiles.py`/`filter/*` reference it only in docstrings.
- **NSRL case-folding (#1 trap) is correct** — `nsrl_match` `.upper()`-folds the probe value against RDSv3's UPPERCASE storage; custom lists `.lower()`-fold both sides.
- **SQL safety is correct** — hashes flow only via `?` placeholders; the table identifier is chosen from the fixed `{FILE, METADATA}` allowlist discovered from `sqlite_master`; the DB is opened `mode=ro` + `PRAGMA query_only=ON`.
- **Sole-writer + lockstep triples are aligned** — `_FILES_COLUMNS`/`_file_row_params` and `_KNOWN_MATCH_COLUMNS`/`_known_match_params` match the schema column order 1:1; no raw SQL outside `store.py`.
- **Confinement is keyed by `meta_addr` (int) + sanitized name**, never the raw deleted filename, routed through `_confined_target` — path-traversal closed (D-42 invariant 6).
- **Overwrite detection block-run math is correct** — `range(addr, addr+len)` is `[addr, addr+len)`, resident/sparse runs are skipped, the `now_allocated` reallocation re-check exists.
- **The store read-orders for recovered/orphan/known are stable** — they terminate in the unique surrogate `id`, so the Phase-3 CR-01 NULL-tie trap is closed for these readers.

The two blockers below are real correctness defects in the integrated
`analyze --recover` path (inventory double-counting) and CLI error mapping
(uncaught `sqlite3.Error`). The warnings are robustness/honesty gaps.

## Blockers

### BL-01: `analyze --recover` double-counts every deleted inode in the inventory findings

**File:** `src/pyautopsy/core/analyze.py:283-321`, `src/pyautopsy/report/assemble.py:259-286`, `src/pyautopsy/core/recover.py:480-503`

**Issue:** The walk already records *every* deleted entry as a `files` row with
`allocated=False`, `recovered=NULL` (`walk.py` `_build_file_row` → `insert_files`).
When `--recover` runs, `run_recover` inserts a **second** `files` row for the same
inode (`allocated=False`, `recovered=1`) via `insert_recovered_files`. Both rows
share the same `meta_addr`/volume but are distinct primary keys.

`assemble_report_body` then computes the inventory findings over the *full*
`get_files` set:

```python
file_count = len(files)                                  # counts walk row + recovered row
deleted_count = sum(1 for f in files if _is_deleted(f))  # _is_deleted == (allocated is False)
```

`_is_deleted` only tests `allocated is False`, which is `True` for *both* the walk
copy and the recovered copy. So `findings.inventory.file_count`,
`findings.inventory.deleted_count`, and every `per_volume["deleted_count"]` are
inflated by exactly the number of recovered inodes. The same inode is then *also*
reported in the dedicated `recovered`/`orphans` sections — a forensically wrong
double-count in an evidence-presentation report.

This is deterministic (so the reproducibility tests still pass on identical
fixtures), which is precisely why it slipped through — the determinism gate does
not catch a *consistently wrong* count.

**Fix:** Exclude recovered rows from the inventory aggregation (they are surfaced
in their own sections), e.g. in `assemble.py`:
```python
inventory_files = [f for f in files if f.recovered is not True]
file_count = len(inventory_files)
directory_count = sum(1 for f in inventory_files if _is_directory(f))
deleted_count = sum(1 for f in inventory_files if _is_deleted(f))
# and build per_volume / file_type_distribution from inventory_files too
```
Alternatively have `get_files`/the report exclude `recovered = 1` from the
inventory pass. Confirm `file_type_distribution` and `per_volume` are recomputed
on the filtered set so recovered rows do not skew them either.

### BL-02: `sqlite3.Error` from a malformed NSRL DB escapes the CLI handlers and crashes with a raw traceback

**File:** `src/pyautopsy/cli/main.py:312-318` (`recover`), `src/pyautopsy/cli/main.py:463-474` (`analyze`)

**Issue:** `open_nsrl`/`nsrl_match` are documented to raise `sqlite3.Error` on an
unopenable/corrupt NSRL DB, and `run_filter` re-raises it (it is in
`_EXPECTED_FILTER_ERRORS`, recorded as `filter.error`). But the `recover` command
catches only `(FilterError, OSError)`:

```python
except (FilterError, OSError) as exc:
    typer.echo(f"recover filtering failed: {exc}", err=True)
    raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc
```

`sqlite3.Error` is **not** a subclass of `OSError` (verified), so a corrupt
`--nsrl` DB propagates past this handler and aborts the CLI with an unhandled
traceback instead of the intended clean non-zero exit + audit FAIL. The `analyze`
command has the same gap: its `except (...)` tuple (lines 463-472) omits
`sqlite3.Error`, and although `run_analyze` lists `sqlite3.Error` in
`_EXPECTED_ANALYZE_ERRORS` and re-raises it, the CLI never maps it — so the same
corrupt-DB input crashes `analyze` too.

This is an examiner-facing robustness/UX defect on untrusted input (the NSRL DB is
explicitly examiner-supplied, third-party data).

**Fix:** Add `sqlite3.Error` to both handlers:
```python
import sqlite3
...
# recover:
except (FilterError, OSError, sqlite3.Error) as exc:
    typer.echo(f"recover filtering failed: {exc}", err=True)
    raise typer.Exit(code=_INTEGRITY_EXIT_CODE) from exc
# analyze: add sqlite3.Error to the existing except tuple.
```

## Warnings

### WR-01: Binary/undecodable custom hash-set file crashes filtering under `filter.crashed`

**File:** `src/pyautopsy/core/knownfiles.py:155-160`

**Issue:** Each custom list is read with `list_path.read_text(encoding="utf-8")`.
If an examiner points `--hash-set-allow`/`--hash-set-block` at a binary or
non-UTF-8 file, `read_text` raises `UnicodeDecodeError`, which is a `ValueError`
subclass — **not** in `_EXPECTED_FILTER_ERRORS` (`FilterError`, `OSError`,
`sqlite3.Error`). It therefore falls through to the `except Exception` arm and is
recorded as `filter.crashed` (a "genuine programming bug") and re-raised, when it
is actually an operational bad-input condition that should be a clean
`filter.error` + handled exit.

**Fix:** Either wrap the read and raise `FilterError` with an actionable message,
or add `ValueError`/`UnicodeDecodeError` to `_EXPECTED_FILTER_ERRORS`. Prefer the
former so the message names the offending list path.

### WR-02: NSRL `mode=ro` URI breaks for DB paths containing `?`, `#`, or spaces

**File:** `src/pyautopsy/filter/nsrl.py:69`

**Issue:** `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` interpolates the raw
path into a SQLite URI. A path containing a `?` (query delimiter), `#` (fragment),
or unescaped spaces/percent signs is misparsed: the `?mode=ro` may be lost (DB
silently opened *writable*, defeating T-04-02-DBRO) or the open fails with a
confusing error. `PRAGMA query_only=ON` still provides a backstop, but the primary
read-only control is bypassed.

**Fix:** URL-encode the path before building the URI, e.g.
```python
from urllib.request import pathname2url
uri = f"file:{pathname2url(str(Path(path).resolve()))}?mode=ro"
conn = sqlite3.connect(uri, uri=True)
```

### WR-03: `nsrl_db` path resolved for the audit log but not for the open

**File:** `src/pyautopsy/core/knownfiles.py:138` vs `:166`

**Issue:** The audit record logs `str(Path(nsrl_db).resolve())` but `open_nsrl` is
called with `str(Path(nsrl_db))` (un-resolved). If the process CWD differs from
where the relative `nsrl_db` was given, the audited path and the actually-opened
path can diverge — a chain-of-custody inconsistency (the audit trail claims a
different file than the one queried).

**Fix:** Resolve once and use the same resolved path for both the audit and the
open: `nsrl_path = Path(nsrl_db).resolve()` then pass `str(nsrl_path)` to
`open_nsrl`.

### WR-04: Oversize recovered entry reads full content for typing despite the size-bomb cap

**File:** `src/pyautopsy/core/recover.py:469-474`

**Issue:** When `entry.size > max_hash_size`, `_write_recovered_bytes` correctly
writes an empty placeholder and `hash_file` returns `None` (skipped). But
`active_typer(reader, entry.size)` is still invoked unconditionally afterward,
which streams the full oversize content through the type sniffer — re-opening the
exact size-bomb surface (T-04-01-BOMB) the cap was meant to bound. Determinism is
unaffected, but the DoS guard is partially defeated.

**Fix:** Skip typing under the same cap:
```python
if max_hash_size is None or entry.size <= max_hash_size:
    try:
        file_type = active_typer(reader, entry.size)
    except OSError:
        file_type = None
```

### WR-05: `recover_meta` builds the reader closure over `f` but never pins the `File` lifetime explicitly

**File:** `src/pyautopsy/evidence/filesystem.py:341-368`

**Issue:** `recover_meta` returns a `read_random` closure that captures `f`
(the TSK `File` from `open_meta`). The closure keeps `f` alive via the cell
reference, which works today, but the orchestrator calls the reader *across* the
`recover_meta` return boundary and after `iter_deleted_inodes`/`allocated_data_blocks`
have iterated other `open_meta` handles on the same `fs`. If a future refactor
drops the closure capture (e.g. extracts the bytes eagerly into a local), the
`File` would be GC'd and reads would fail or return garbage — a latent
forensic-correctness hazard. The comment claims the lifetime is bound but there is
no test asserting a read succeeds *after* the next inode is opened.

**Fix:** Add a regression test that calls the returned `read_random` after
iterating subsequent inodes on the same `fs`, and/or store `f` on the
`RecoveredEntry` explicitly (a private field) so the lifetime contract is
structural, not incidental to closure capture.

## Info

### IN-01: `now_allocated` branch in `classify_tier`/`run_recover` is effectively unreachable defensive code

**File:** `src/pyautopsy/core/recover.py:175-178`, `src/pyautopsy/evidence/filesystem.py:497-511`

**Issue:** `iter_deleted_inodes` already excludes `ALLOC` inodes in both discovery
passes, and `recover_meta` reopens within the *same* read-only `fs`, so allocation
state cannot change between enumeration and reopen. The `now_allocated == True`
tier path (and the Pitfall-5 re-check it implements) can therefore never fire in
the current call graph. It is harmless and defensible to keep as defense-in-depth,
but it is untestable through the public path — note it so a future reader does not
assume it is exercised.

**Fix:** Either add a comment that this is unreachable defense-in-depth, or
unit-test `classify_tier` directly with `now_allocated=True` (the only way to
cover it) so the branch is not dead.

### IN-02: Docstrings claim `run_recover` uses `walk_fs`; the code uses `iter_deleted_inodes`

**File:** `src/pyautopsy/core/recover.py:16-20` (module docstring) vs `:433`

**Issue:** The module docstring step 3 says recovery enumerates entries "through
the FS seam (`filesystem.walk_fs`) ... then for each deleted (`allocated is False`)
entry reopen the inode". The implementation actually iterates
`fs_seam.iter_deleted_inodes` (which internally unions `walk_fs` + an inode-range
scan). The docstring under-describes the range-scan pass, which is the part that
finds broken-link/orphan inodes. Misleading for maintainers.

**Fix:** Update the docstring to describe `iter_deleted_inodes` and its two passes.

### IN-03: Recovered rows silently contribute zero timeline events (intended, but undocumented at the integration seam)

**File:** `src/pyautopsy/core/analyze.py:303-306`, `src/pyautopsy/report/assemble.py:251-255`

**Issue:** Recovery never populates the MACB `*_utc` columns on recovered
`FileRow`s, so `build_timeline` (which explodes one event per populated MACB
timestamp) emits nothing for recovered rows — correct per D-24, but there is no
note at the analyze seam explaining that recovered entries are intentionally
timeline-invisible. Combined with BL-01 (they *are* inventory-visible), the
asymmetry is easy to misread as a bug during future work.

**Fix:** Add a one-line comment at the recover→timeline boundary documenting that
recovered rows carry no MACB times by design and therefore produce no timeline
events.

---

_Reviewed: 2026-05-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
