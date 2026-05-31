---
phase: 04-deleted-recovery-known-file-filtering
plan: 02
subsystem: known-file-filtering
tags: [FILTER-01, nsrl, hashsets, noise-reduction, D-38, D-39, D-41]
requires:
  - "04-01: files rows (allocated + recovered) the filtering pass reads via CaseStore"
  - "04-00: nsrl_minimal.db (FILE) + nsrl_metadata.db (METADATA) UPPERCASE-hash fixtures"
provides:
  - "filter/ package: read-only NSRL membership probe + custom allow/block parser"
  - "core/knownfiles.run_filter: post-walk neutral known-annotation pass"
  - "CaseStore.insert_known_matches / get_known_matches + known_file_matches table"
  - "report 'Known-File Filtering (noise reduction)' section (assemble.py + html.j2)"
affects:
  - "04-03: CLI --nsrl/--hash-set flags + analyze wiring will call run_filter"
tech-stack:
  added: []
  patterns:
    - "read-only external SQLite via file:...?mode=ro URI + PRAGMA query_only=ON"
    - "fixed {FILE,METADATA} table allowlist; ?-parameterized hash lookups (no SQLi)"
    - "UPPERCASE-normalized hash comparison (Pitfall 4 silent-zero-match trap)"
    - "_KNOWN_MATCH_* lockstep COLUMNS/INSERT_SQL/params triple (mirrors files/timeline)"
    - "store-owned deterministic total order for report byte-stability (D-41)"
key-files:
  created:
    - src/pyautopsy/filter/__init__.py
    - src/pyautopsy/filter/nsrl.py
    - src/pyautopsy/filter/hashsets.py
    - src/pyautopsy/core/knownfiles.py
  modified:
    - src/pyautopsy/case/schema.sql
    - src/pyautopsy/case/models.py
    - src/pyautopsy/case/__init__.py
    - src/pyautopsy/case/store.py
    - src/pyautopsy/report/assemble.py
    - src/pyautopsy/report/templates/report.html.j2
decisions:
  - "Single dedicated known_file_matches table (FK to files), not a column: supports multiple matches per file (NSRL + N custom lists) while keeping the sole-writer rule (Open Question 2)"
  - "get_known_matches orders by file (volume_id,volume_offset,path,id) then match (source,list_name,sense,matched_on,id) so the report is byte-deterministic (D-41)"
  - "NSRL match dict carries source/matched_on only; custom adds list/sense — never a good/bad/verdict key (D-38)"
  - "core/knownfiles is NOT exported from core/__init__ (mirrors core/recover.py, wired by CLI/analyze in 04-03)"
metrics:
  duration: ~35min
  completed: 2026-05-31
---

# Phase 4 Plan 02: Known-File Filtering Summary

NSRL RDS + custom allow/block hash-list filtering as a runnable vertical slice: a
read-only NSRL membership probe (FILE/METADATA variant discovery, UPPERCASE
normalization, parameterized SQL) and a custom-list parser feed a post-walk
`run_filter` pass that writes neutral "known" annotations via CaseStore and
renders a deterministic noise-reduction report section — turning the three Wave-0
`test_knownfiles` RED tests GREEN.

## What was built

**Task 1 — filter/ package (`fe32be1`):**
- `filter/nsrl.py` — `open_nsrl(path)` opens the examiner DB with
  `sqlite3.connect("file:...?mode=ro", uri=True)` + `PRAGMA query_only=ON`,
  discovers the hash table from `sqlite_master` choosing from the fixed
  `{FILE, METADATA}` allowlist (never interpolating arbitrary input), and returns
  `(conn, table)`. `nsrl_match(...)` probes md5→sha1→sha256 (D-37) with
  `val.upper()` normalization (Pitfall 4) via `?`-parameterized `SELECT` and
  returns a neutral `{"source":"nsrl","matched_on":col}` or `None`.
- `filter/hashsets.py` — `parse_hash_set(text)` tolerates `#` comments, blanks,
  trailing per-line comments and mixed case, inferring algo by hex length
  `{32:md5,40:sha1,64:sha256}` and hex-validating/lowercasing each token;
  `custom_match(...)` matches md5→sha1→sha256 returning
  `{"source":"custom","list":name,"sense":sense,"matched_on":col}` or `None`.

**Task 2 — orchestrator + storage + report (`ac149fc`):**
- `schema.sql` — additive `known_file_matches` table (`id` PK, `file_id` FK→files,
  `source`, `list_name`, `sense`, `matched_on`, `attributes`) + file_id index.
- `models.py` — `KnownMatch` frozen-slots dataclass; exported via `case` package.
- `store.py` — `_KNOWN_MATCH_*` lockstep triple, `insert_known_matches`
  (executemany + `_commit_unless_in_transaction`), and `get_known_matches` with a
  deterministic file-then-match total order (D-41). No raw SQL outside store.py.
- `core/knownfiles.py` — `run_filter(case_dir, *, nsrl_db=None, hash_sets=())`:
  reads `store.get_files` (allocated + recovered), opens NSRL once, parses each
  list once, probes every hashed row, collects `KnownMatch`es and writes them in
  ONE `store.transaction()`; `filter.error`/`filter.crashed` two-arm audit;
  returns a reproducible `FilterResult` (files_matched/nsrl_matches/custom_matches).
- `assemble.py` + `report.html.j2` — neutral "Known-File Filtering (noise
  reduction)" section with deterministic per-source/per-list counts, explicit
  no-verdict framing, no wall-clock.

## Verification

- `pytest tests/test_knownfiles.py -q` → 3 GREEN (nsrl_membership, custom_hash_sets,
  variant_table_discovery).
- `pytest tests/test_seam_allowlist.py -q` → GREEN; `grep -rl 'import pytsk3'
  src/pyautopsy/{filter,core/knownfiles.py}` empty.
- Full suite `pytest -q` → **181 passed** (178 prior incl. recovery + 3 knownfiles);
  no regression.
- `ruff check src/pyautopsy/` and `mypy src/pyautopsy/` both clean (31 files).

## Threat-model coverage (all `mitigate` dispositions applied)

| Threat | Mitigation in code |
|--------|--------------------|
| T-04-02-SQLI | `?` placeholders for every hash; table from fixed `{FILE,METADATA}` allowlist; `nsrl_match` rejects a non-allowlisted table name before interpolating |
| T-04-02-DBRO | `?mode=ro` URI + `PRAGMA query_only=ON`; never `ATTACH`; NSRL DB distinct from case.db |
| T-04-02-CASE | `.upper()` probe normalization + runtime FILE/METADATA discovery |
| T-04-02-PARSE | skip blank/`#` lines; hex-validate; only lengths {32,40,64}; lowercase-normalize |
| T-04-02-VERDICT | match model + report carry source/list/sense/matched_on only; no good/bad/verdict key (verified by grep) |
| T-04-02-SC | no new packages (stdlib sqlite3/hashlib only) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] mypy variable-name collision in assemble.py**
- **Found during:** Task 2 (mypy gate)
- **Issue:** the new custom-list aggregation reused the function-scope name `key`
  already bound to `tuple[int,int]` in the per-volume loop, so mypy narrowed the
  later `tuple[str,str]` use to the earlier type (4 errors).
- **Fix:** renamed to `custom_key`, typed `custom_lists: list[dict[str, Any]]`,
  and wrapped the `sum` operand in `int(...)`.
- **Files modified:** src/pyautopsy/report/assemble.py
- **Commit:** ac149fc

## TDD Gate Compliance

This is a Wave-2 GREEN execution: the RED gate (`tests/test_knownfiles.py`) was
committed in Wave 0 (phase setup), and this plan supplies the GREEN
implementation (two `feat(04-02)` commits). Baseline confirmed RED before work
(`3 failed, 178 passed`) and GREEN after (`181 passed`). No REFACTOR commit was
needed — the implementation matched the RESEARCH code examples directly.

## Notes for 04-03

- `core/knownfiles.run_filter` is intentionally NOT exported from `core/__init__`
  (mirrors `core/recover.py`); 04-03 wires the `--nsrl`/`--hash-set` CLI flags and
  the `analyze` integration, and is responsible for updating
  `assemble._MVP_LIMITATIONS` (left untouched here per plan scope).
- The report `body["known"]` section is already populated by `assemble_report_body`
  for any source with persisted matches; 04-03 only needs to trigger the pass.

## Known Stubs

None — the slice is end-to-end: real NSRL/custom probes, real CaseStore
persistence, and a real report section reading the persisted rows.

## Self-Check: PASSED

- Created files all present: filter/__init__.py, filter/nsrl.py,
  filter/hashsets.py, core/knownfiles.py.
- Commits present: fe32be1 (Task 1), ac149fc (Task 2).
