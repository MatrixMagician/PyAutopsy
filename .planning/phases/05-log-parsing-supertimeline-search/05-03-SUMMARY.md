---
phase: 05-log-parsing-supertimeline-search
plan: 03
subsystem: search
tags: [search, streaming, regex, ioc, known-bad-hash, unallocated, sqlite, typer, pytsk3-seam]

# Dependency graph
requires:
  - phase: 05-00
    provides: log_search_ext4 fixture + groundtruth sidecar + RED search test stubs
  - phase: 05-01
    provides: filesystem seam + walk inventory the content/hash arms scan
  - phase: 04 (filter)
    provides: filter/hashsets parse_hash_set + custom_match reused for the known-bad-hash arm
  - phase: 01 (case store)
    provides: CaseStore sole-writer pattern + known_file_matches lockstep precedent
provides:
  - SEARCH-01 streaming literal/regex search over allocated content + unallocated space (offsets, boundary-spanning)
  - SEARCH-02 IOC-term + known-bad-hash matching (hits by file + offset, reuses filter/*)
  - iter_unallocated_blocks seam generator (the verified no-block-API workaround)
  - additive search_hits table/model/store methods (timeline_events untouched, D-47)
  - `pyautopsy search` CLI subcommand
affects: [report, super-timeline, future search-index (v2/SEARCH-03)]

# Tech tracking
tech-stack:
  added: []  # D-43 hard invariant honored — stdlib only (re), no new runtime dependency
  patterns:
    - "Unallocated read = COMPLEMENT of allocated_data_blocks, read raw via the byte seam, all pytsk3 in the FS seam (D-14)"
    - "Streaming chunk scan with carry-over overlap + end-past-carry dedup = exactly-once boundary-spanning match (Pitfall 5)"
    - "Search reuses filter/hashsets verbatim for the known-bad-hash arm (no duplicated matching logic, D-43)"

key-files:
  created:
    - src/pyautopsy/search/__init__.py
    - src/pyautopsy/search/content.py
    - src/pyautopsy/search/ioc.py
    - src/pyautopsy/core/search.py
  modified:
    - src/pyautopsy/evidence/filesystem.py
    - src/pyautopsy/case/schema.sql
    - src/pyautopsy/case/models.py
    - src/pyautopsy/case/store.py
    - src/pyautopsy/case/__init__.py
    - src/pyautopsy/cli/main.py
    - tests/test_cli_smoke.py
    - tests/test_readonly_guarantee.py

key-decisions:
  - "iter_unallocated_blocks(handle, fs, vol) is a single seam generator yielding (block_index, bytes); a block_size(fs) seam helper maps indices to absolute offsets so search/ never touches fs.info (D-14)"
  - "search_hits is the ONLY new schema item (additive); store-owned total order volume_id, volume_offset, byte_offset, term, id (D-41); timeline_events untouched (D-47)"
  - "SearchHit.term stored as latin-1 string so a non-UTF-8 needle round-trips byte-exactly"
  - "Boundary-spanning dedup: a match is emitted only when it ends PAST the carried overlap prefix (end > carry_len) — guarantees exactly-once"
  - "Known-bad-hash hits recorded BOTH as KnownMatch (FILTER-01 precedent) AND as term_kind=hash SearchHit (so they appear by file in unified search results, as the test asserts)"
  - "Regex ReDoS guard (V5): bounded match length MAX_REGEX_MATCH_LEN=4096 + bounded chunked streaming; bad regex -> SearchError, never .crashed"

patterns-established:
  - "Orchestrator copied from knownfiles.run_filter (two-arm audit, one transaction, expected-error set) + recover (image-open guard)"
  - "Streaming scanner: _stream_scan carries overlap only across CONTIGUOUS chunks; a gap drops the stale carry (no cross-file/cross-run false match)"

requirements-completed: [SEARCH-01, SEARCH-02]

# Metrics
duration: ~25min
completed: 2026-05-31
---

# Phase 05 Plan 03: Log/Search Vertical Slice (Search) Summary

**SEARCH-01 streaming literal/regex search across allocated content + unallocated space (exactly-once boundary-spanning, absolute offsets) and SEARCH-02 IOC + known-bad-hash matching, all read-only through the two seams with the verified iter_unallocated_blocks no-block-API workaround — zero new runtime dependency.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-31T18:48Z
- **Completed:** 2026-05-31T19:00Z
- **Tasks:** 2
- **Files modified:** 13 (4 created, 9 modified)

## Accomplishments
- `iter_unallocated_blocks` FS-seam generator: derives the allocated-block set via the existing `allocated_data_blocks`, reads the COMPLEMENT raw via the byte seam, yields `(block_index, bytes)` — pytsk3 exposes no block-walk API, so this is the verified workaround, kept entirely inside `filesystem.py` (D-14).
- Additive `search_hits` table + `SearchHit` model + sole-writer `insert_search_hits`/`get_search_hits` (store-owned total order `volume_id, volume_offset, byte_offset, term, id`); `timeline_events` provably untouched (39-line additive schema diff).
- Streaming content scanner (`search/content.py`): chunked reads with a carry-over overlap window and an end-past-carry dedup so a chunk-boundary-spanning match is found exactly ONCE at its correct absolute offset (Pitfall 5); never slurps a region (PERF-01); ReDoS-bounded regex (V5).
- IOC + known-bad-hash matcher (`search/ioc.py`) reusing `filter/hashsets` verbatim — no new matching logic, no new dependency (D-43).
- `run_search` orchestrator (`core/search.py`): re-asserts not-mounted before+after open (D-42), one `store.transaction()` writing SearchHit + KnownMatch, two-arm audit, counts-only `SearchResult`.
- `pyautopsy search` CLI subcommand mirroring `recover` (sqlite3.Error mapped, BL-02).
- The 4 RED search stubs in `tests/test_search.py` are now GREEN; full suite **206 passed** (was 199 passed + 4 failed).

## Task Commits

Each task was committed atomically:

1. **Task 1: iter_unallocated_blocks seam + search_hits table/model/store** - `8013417` (feat)
2. **Task 2: streaming search core + IOC/hash matcher + run_search + CLI** - `b5b39f5` (feat)

_Note: the Wave-0 RED test stubs (test_search.py) were committed in a prior plan; this plan turned them GREEN (the project-level TDD RED gate was satisfied upstream)._

## Files Created/Modified
- `src/pyautopsy/search/__init__.py` - search package docstring/marker (no native imports, D-14)
- `src/pyautopsy/search/content.py` - SEARCH-01 streaming literal/regex scanner (`search_bytes`/`search_image`), overlap dedup, ReDoS bound
- `src/pyautopsy/search/ioc.py` - IOC-term parser + known-bad-hash arm (`parse_ioc_terms`, `build_bad_hash_set`, `match_bad_hashes`) reusing filter/hashsets
- `src/pyautopsy/core/search.py` - `run_search`, `SearchResult`, `SearchError` orchestrator
- `src/pyautopsy/evidence/filesystem.py` - `iter_unallocated_blocks` generator + `block_size(fs)` seam helper
- `src/pyautopsy/case/schema.sql` - additive `search_hits` table + 2 indexes
- `src/pyautopsy/case/models.py` - `SearchHit` frozen/slots dataclass
- `src/pyautopsy/case/store.py` - `insert_search_hits`/`get_search_hits` + four-piece lockstep
- `src/pyautopsy/case/__init__.py` - export `SearchHit`
- `src/pyautopsy/cli/main.py` - `pyautopsy search` subcommand
- `tests/test_cli_smoke.py` - `search` smoke + help tests
- `tests/test_readonly_guarantee.py` - `run_search` read-only-guarantee test

## Decisions Made
See `key-decisions` in frontmatter. Notably: hash hits are persisted as BOTH `KnownMatch` (FILTER-01 precedent) and `term_kind="hash"` `SearchHit` because the Wave-0 RED test reads hash hits back from `get_search_hits` (by `term_kind` and `path`), so they must appear in the unified search-hit results, not only in `known_file_matches`.

## Deviations from Plan

None requiring user input. Two small additive choices, both within the plan's intent:

**1. [Rule 2 - Missing Critical] `block_size(fs)` seam helper added to filesystem.py**
- **Found during:** Task 2 (mapping unallocated `(block_index, bytes)` to absolute offsets)
- **Issue:** `search/content.py` must convert a block index to an absolute image offset (`vol.offset + index*block_size`) but MUST NOT read `fs.info` (D-14). The plan's `iter_unallocated_blocks` yields indices, not offsets.
- **Fix:** Added a one-line `block_size(fs) -> int` helper to the FS seam (mirrors the existing `fs_type_int` pytsk3-free-int export convention), keeping all native access in the seam.
- **Files modified:** src/pyautopsy/evidence/filesystem.py
- **Verification:** test_seam_allowlist passes (search/ imports no native binding); mypy/ruff clean.
- **Committed in:** b5b39f5 (Task 2 commit)

**2. [Rule 2 - Missing Critical] `SearchHit.path` column persisted**
- **Found during:** Task 1/2 (RED test reads `h.path` on hits from both `search_image` and `get_search_hits`)
- **Issue:** RESEARCH Open-Q1's proposed columns omitted `path`, but the Wave-0 tests assert `gt[...]["path"] in (h.path or "")` for allocated and hash hits.
- **Fix:** Added a nullable `path` column to `search_hits`/`SearchHit` (NULL for unallocated-space hits that belong to no live file).
- **Files modified:** src/pyautopsy/case/schema.sql, models.py, store.py
- **Verification:** test_search.py (all 4) GREEN; schema diff additive only.
- **Committed in:** 8013417 (Task 1) + b5b39f5 (Task 2)

---

**Total deviations:** 2 auto-fixed (both Rule 2 — required for the test contract / D-14 boundary). No scope creep; no new runtime dependency (D-43 holds, test_no_new_deps GREEN).
**Impact on plan:** Both additions were necessary for correctness and the D-14 seam boundary.

## Issues Encountered
- mypy/ruff initially flagged the unallocated-chunk inner closure (`arg-type` on `object`-typed fs/vol, then B023 loop-variable binding). Resolved by extracting a module-level `_unallocated_chunks(handle, fs, vol, block_bytes, base_offset)` helper that takes fs/vol as explicit arguments — no late-binding hazard, mypy + ruff clean.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SEARCH-01/02 complete and persisted; `get_search_hits` gives the report a deterministic, store-owned hit ordering to render.
- 05-04 (super-timeline / remaining phase work) can proceed; this slice is disjoint from the 05-02 log-parser slice (no file conflict — only this plan touched cli/main.py among the Wave-2 pair).
- Out of scope (by design, D-49): SEARCH-03 search index (v2).

## Self-Check: PASSED

- All created files present (search/__init__.py, content.py, ioc.py, core/search.py, SUMMARY.md).
- Task commits present: `8013417`, `b5b39f5`.
- Full suite: 206 passed; ruff + mypy clean on the plan's verification set.

---
*Phase: 05-log-parsing-supertimeline-search*
*Completed: 2026-05-31*
