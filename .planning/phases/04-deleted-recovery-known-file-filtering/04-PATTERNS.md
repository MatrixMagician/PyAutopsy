# Phase 4: Deleted Recovery & Known-File Filtering - Pattern Map

**Mapped:** 2026-05-31
**Files analyzed:** 15 (5 NEW source, 6 MODIFIED source, 4 NEW/extended test)
**Analogs found:** 15 / 15 (all in-tree — Phase 4 is composition, not new infrastructure)

This map tells the planner exactly which existing file each new/modified Phase-4
file copies its shape from, with line-referenced excerpts. Every analog lives in
this repo; RESEARCH.md confirms "every hard part of this phase already exists
in-tree" (04-RESEARCH §Don't Hand-Roll). No external pattern is needed.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/pyautopsy/core/recover.py` (NEW) | orchestrator | transform / file-I/O | `src/pyautopsy/core/walk.py` (`run_walk`, `_build_file_row`, `_content_fields`) | exact (sibling orchestrator) |
| `src/pyautopsy/filter/nsrl.py` (NEW) | utility/service | request-response (read-only SQL probe) | `src/pyautopsy/evidence/integrity.py` (`hash_file` + `_LEN_TO_ALGO` hex-length idiom) + `case/store.py` (`_connect` read-only conn) | role-match |
| `src/pyautopsy/filter/hashsets.py` (NEW) | utility | transform (text parse) | `src/pyautopsy/evidence/integrity.py` (`_LEN_TO_ALGO`, `verify_acquisition` hex validation) | role-match |
| `src/pyautopsy/core/knownfiles.py` *(or `filter` pkg orchestrator)* (NEW) | orchestrator | batch (post-walk pass over rows) | `src/pyautopsy/timeline/builder.py` pattern via `walk.py` (read `get_files`, write via store in one transaction) | role-match |
| `src/pyautopsy/evidence/filesystem.py` (MODIFIED) | native seam | file-I/O (inode read + run enum) | itself — `FileEntry`/`_make_reader`/`walk_fs` already in file | exact (extend in place) |
| `src/pyautopsy/case/store.py` (MODIFIED) | model/persistence | CRUD | itself — `insert_files`/`_file_row_params`/`get_files`/`insert_volume_limitation` | exact (extend in place) |
| `src/pyautopsy/case/schema.sql` (MODIFIED) | config/schema | — | itself — `files` table + `volume_limitations`/`timeline_events` additive tables | exact (extend in place) |
| `src/pyautopsy/case/models.py` (MODIFIED) | model | — | itself — `FileRow`, `VolumeLimitation` frozen dataclasses | exact (extend in place) |
| `src/pyautopsy/core/analyze.py` (MODIFIED) | orchestrator | request-response | itself — `run_analyze` opt-in step composition | exact (extend in place) |
| `src/pyautopsy/report/assemble.py` (MODIFIED) | report builder | transform | itself — `assemble_report_body` deterministic-dict pattern | exact (extend in place) |
| `src/pyautopsy/report/templates/report.html.j2` (MODIFIED) | template | — | itself — existing autoescaped sections | exact (extend in place) |
| `src/pyautopsy/cli/main.py` (MODIFIED) | route/CLI | request-response | itself — `walk` / `analyze` Typer command pattern | exact (extend in place) |
| `tests/test_recover.py` (NEW) | test | — | `tests/test_walk.py` + `tests/test_readonly_guarantee.py::test_source_unchanged_after_walk` | role-match |
| `tests/test_knownfiles.py` (NEW) | test | — | `tests/test_integrity.py` (hex/digest unit tests, fakes) | role-match |
| `tests/fixtures/make_fixtures.py` (MODIFIED) | test fixture builder | file-I/O | itself — `build_tiny_ext4_image` debugfs pattern + ground-truth constants | exact (extend in place) |
| `tests/test_reproducibility.py` + `tests/test_readonly_guarantee.py` (MODIFIED) | test | — | themselves — `_analyze` runner + byte-compare; stat-before/after | exact (extend in place) |

## Pattern Assignments

### `src/pyautopsy/core/recover.py` (orchestrator, transform/file-I/O) — NEW

**Analog:** `src/pyautopsy/core/walk.py` — `run_walk` is the sibling orchestrator
to mirror exactly. RESEARCH §Architectural Responsibility Map puts confidence-tier
classification + hashing + writing + cataloging here, with NO pytsk3 import.

**Module docstring + no-native-import contract** (walk.py:36-40): copy the exact
"this module is part of the orchestration tier and **does not import pytsk3**"
note — `test_seam_allowlist.py` will fail if recover.py imports pytsk3.

**Imports pattern** (walk.py:42-67): the orchestrator imports the seam as a module
(`from pyautopsy.evidence import filesystem as fs_seam`), plus `integrity`,
`filetype`, `CaseStore`, models, `AuditLog`. Copy this block; add
`from pyautopsy.util.safe_extract import _confined_target, _sanitize_name`.

**Hashing the recovered bytes — reuse, never re-implement** (walk.py:328-348):
`_content_fields` already calls `integrity.hash_file(reader, entry.size, max_size=...)`
and degrades a read error to null hashes + a `hash_skipped` reason. RESEARCH
Code-Example "Hash the recovered bytes" maps 1:1 onto this:
```python
digests = integrity.hash_file(entry.read_random, entry.size, max_size=max_hash_size)
```
Recovered bytes are hashed exactly the way allocated files are.

**`WalkResult`-style frozen result** (walk.py:236-256): `RecoverResult` carries
reproducible counts only — never wall-clock (PITFALLS P3). Copy the
`@dataclass(frozen=True, slots=True)` shape; e.g. `files_recovered`,
`intact_count`, `overwritten_count`, `orphan_count`.

**Expected-vs-crashed error split** (walk.py:225-233, 579-600): copy
`_EXPECTED_RECOVER_ERRORS` tuple + the `except _EXPECTED... / except Exception`
two-arm audit pattern (`recover.error` FAIL vs `recover.crashed`), always writing
the FAIL event before re-raising.

**`store.transaction()` bulk-write** (walk.py:510-557): wrap recovered-row inserts
in one `with store.transaction():` and insert per batch — the sole-writer +
atomic-write contract (WR-01).

**Tier classification (pure logic, the genuinely new code)** — RESEARCH
Code-Example "Classify the confidence tier" is the spec; keep it pure (no pytsk3)
so it is testable with fakes, mirroring how `_content_fields`/`_macb_fields` are
pure over a `FileEntry`.

---

### `src/pyautopsy/evidence/filesystem.py` (native seam, file-I/O) — MODIFIED

**Analog:** itself. Add `recover_meta`, `iter_block_runs`/`allocated_data_blocks`,
and orphan enumeration. This is the ONLY file (besides `image.py`) allowed to
import pytsk3 (allowlist gate `tests/test_seam_allowlist.py`).

**"No native type escapes" value-object contract** (filesystem.py:159-223):
`FileEntry` is the template for the new `RecoveredEntry` value object — a
`@dataclass(frozen=True, slots=True)` of plain primitives plus a single
`read_random` closure. RESEARCH Code-Example "Recover a deleted inode" gives the
exact `RecoveredEntry` shape (meta_addr, size, meta_type, is_orphan,
now_allocated, data_blocks: tuple[int,...], has_resident_data, read_random).
Return plain `int`s for block runs — never an `Attribute`/`TSK_FS_ATTR_RUN`.

**Read-only closure idiom** (filesystem.py:294-306): copy `_make_reader` verbatim
for the recovered inode — `read_random(offset, size)` over the `open_meta` `File`,
documented "read-only; never writes or mounts the source (D-05)".

**Plain-int flag constants kept inside the seam** (filesystem.py:78-83): add
`_FS_META_FLAG_UNALLOC`, `_FS_META_FLAG_ORPHAN`, `TSK_FS_ATTR_NONRES`,
`TSK_FS_ATTR_RUN_FLAG_SPARSE` here as `int(pytsk3....)` so the orchestrator never
touches the binding. Mirror the `FAT_FS_TYPES`/`NTFS_FS_TYPES` "derive from enums,
never hard-code ints" rule (filesystem.py:43-76, CR-02).

**Run-enumeration + derived bitmap**: RESEARCH §Pattern 2 (`iter_block_runs`,
`allocated_data_blocks`) is the verified-working code; `allocated_data_blocks`
returns `frozenset[int]` (matches the seam's frozenset export convention).

**OSError-on-missing-inode signal** (filesystem.py:271-291, `open_fs`): mirror the
"let OSError propagate / catch and return None" idiom for `fs.open_meta(inode=...)`
when an inode address is invalid (RESEARCH `recover_meta` wraps it in `try/except OSError: return None`).

---

### `src/pyautopsy/case/store.py` + `schema.sql` + `models.py` (CRUD) — MODIFIED

**Analog:** itself — the `files`-table write/read path is the exact template.

**Insert SQL kept in lockstep with a column tuple** (store.py:588-654):
`_FILES_COLUMNS` + `_FILES_INSERT_SQL` + `_file_row_params` is the pattern for any
new insert (e.g. a `known_file_matches` table or recovery columns). If a dedicated
`known_file_matches` table is chosen (RESEARCH Open Question 2 recommendation),
copy this three-part structure: a `_KNOWN_MATCH_COLUMNS` tuple, a derived
`_KNOWN_MATCH_INSERT_SQL`, and a `_known_match_params` flattener.

**Bulk insert composing with an outer transaction** (store.py:344-362,
`insert_files`): copy for `insert_known_matches` / recovered-row writes —
`executemany` + `_commit_unless_in_transaction()` so it nests under the
orchestrator's `transaction()`.

**Reader returning models in a total order** (store.py:409-422, `get_files`):
`get_files` filters by `evidence_source_id ORDER BY id`. New readers
(`get_recovered_files`, `get_known_matches`) copy this. The timeline reader
(store.py:557-561) shows the explicit D-26 multi-column `ORDER BY` to copy when a
report-facing total order beyond `id` is needed (D-41 — never re-sort outside the
store).

**`attributes` JSON blackboard** (store.py:653, `json.dumps(..., sort_keys=True)`):
recovery metadata (tier rationale, overwrite evidence, FAT first-char-lost note,
resident-data note) and the neutral `known` annotation go here per D-35/D-39.
`_load_attributes` (store.py:703-713) is the read side.

**Additive schema, DEFAULT NULL** (schema.sql:63-96): the `files` table is the
template. RESEARCH §Runtime-State note: any new recovery column on `files` MUST be
`... DEFAULT NULL` (additive, no backfill — a pre-recovery walk row stays valid).
A dedicated table copies the `volume_limitations` shape (schema.sql:101-112):
`id INTEGER PRIMARY KEY AUTOINCREMENT`, FK `REFERENCES files(id)` /
`evidence_sources(id)`, an `attributes TEXT NOT NULL DEFAULT '{}'`, plus a
`CREATE INDEX IF NOT EXISTS` on the FK (schema.sql:111-112).

**Model shape** (models.py:83-149, `FileRow`; 206-235, `VolumeLimitation`): a new
`KnownMatch` model (if a table is used) copies the frozen-dataclass +
`attributes: dict = field(default_factory=dict)` + `id: int | None = None`
convention. Recovered files reuse `FileRow` itself (D-35) — `allocated=False`,
recovery metadata in `attributes` and/or new narrow columns.

---

### `src/pyautopsy/filter/nsrl.py` (read-only SQL probe) — NEW

**Analog:** `case/store.py::_connect` (store.py:129-136) for the connection idiom,
and RESEARCH §Pattern 4 / Code-Example for the read-only specifics. This module is
NOT a native seam (stdlib `sqlite3` only — D-14 unaffected).

**Read-only connection** — mirror `_connect`'s `sqlite3.connect` + `row_factory`,
but open the examiner DB read-only (RESEARCH Code-Example, verified idiom):
```python
conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
conn.execute("PRAGMA query_only=ON;")
```

**Table discovery + parameterized probe** (RESEARCH §Pattern 4, Pitfall 4):
discover `FILE` vs `METADATA` from `sqlite_master`, choose the table name from a
fixed `{FILE, METADATA}` allowlist (never interpolate user input), match
md5→sha1→sha256 (D-37) with `.upper()` (RDSv3 is uppercase), `?` placeholders only.

**Neutral match model** (RESEARCH §Pattern 4/5, D-38): return
`{"source": "nsrl", "matched_on": col}` — NO good/bad/malicious key anywhere
(the honesty rule, mirrors `assemble.py`'s integrity-copy discipline).

---

### `src/pyautopsy/filter/hashsets.py` (text transform) — NEW

**Analog:** `evidence/integrity.py` — the hex-length→algorithm idiom and hex
validation already exist and are the exact pattern to copy.

**Hex-length → algorithm map** (integrity.py:70, `_LEN_TO_ALGO = {32: "md5", 64: "sha256"}`):
extend to `{32: "md5", 40: "sha1", 64: "sha256"}` for the custom-list parser
(RESEARCH §Pattern 5 `_HEX`).

**Hex validation** (integrity.py:299-305, `verify_acquisition`): copy the
`int(normalised, 16)` / `all(c in "0123456789abcdef" ...)` validation + lowercase
normalization for skipping malformed/comment lines.

**Neutral match shape** (D-38): `{"source": "custom", "list": name, "sense": "allow"|"block", "matched_on": col}`.

---

### `src/pyautopsy/core/knownfiles.py` *(filtering orchestrator)* (batch) — NEW

**Analog:** `core/walk.py` read→write-in-one-transaction pattern (walk.py:498-557)
+ `core/analyze.py` composition.

**Post-walk pass** (D-39): read `store.get_files(source_id)` (store.py:409), and for
each row with hashes call the nsrl/hashsets matchers, then write annotations via a
new `store.insert_known_matches` inside one `with store.transaction():` block.
Order is the store's total order (D-41) — never re-sort here.

**Audit + error-split**: same `_EXPECTED_*_ERRORS` / `*.error` vs `*.crashed`
two-arm pattern as walk.py:579-600 and analyze.py:282-304.

---

### `src/pyautopsy/core/analyze.py` (opt-in step composition) — MODIFIED

**Analog:** itself — `run_analyze` (analyze.py:154-317).

**Opt-in step insertion** (analyze.py:236-260): recovery + filtering slot in
BETWEEN `run_walk` (line 236) and `build_timeline`/report (lines 247-260), and run
ONLY when the relevant inputs are supplied (D-40 — default `analyze` stays
byte-stable). Copy the existing "drive the lower orchestrator, then read back
through one open store" shape (`store = CaseStore.open(case_path)` line 246).

**Threading the real outcome through to the report** (analyze.py:248-256): mirror
how `acquisition_verified` is passed into `assemble_report_body` — pass
recovery/known results the same honest way.

**Result dataclass + audit.end fields** (analyze.py:101-129, 273-281): extend
`AnalyzeResult` with recovered/known counts and add them to the `analyze.end`
event — analytical content only, no wall-clock.

---

### `src/pyautopsy/report/assemble.py` (deterministic dict) — MODIFIED

**Analog:** itself — `assemble_report_body` (assemble.py:99-332) is THE
determinism single-source-of-truth.

**No-wall-clock body contract** (assemble.py:1-23, 245-253): new sections
("Recovered Files", "Orphan Files", "Known-File Filtering (noise reduction)")
carry zero run metadata (D-41).

**Deterministic ordering by sorted keys / store order** (assemble.py:144-191):
copy the `volume_acc` + `sorted(...)` and `Counter` + `sorted(items, key=...)`
idioms for any new aggregation (e.g. tier counts, per-source known-match counts).
Read recovered/known rows via the new `store.get_*` readers (already in D-26 order)
and emit lists verbatim — never re-sort (the `timeline` list, assemble.py:204-217,
is the template: read events in store order, project to plain dicts).

**Honest, non-overclaiming copy** (assemble.py:38-67, the `_MVP_LIMITATIONS` /
integrity-copy strings): tier wording and the "known = noise reduction" framing
copy this discipline — describe data survival only, never intent / good-bad
(D-32/D-38, mirrors the Phase-3 WR-02 honesty test). NOTE: `_MVP_LIMITATIONS`
(assemble.py:38-43) currently states the report does NOT include deleted-file
recovery / NSRL filtering — when those run, this disclaimer must be updated so it
stays honest.

**JSON determinism downstream** (jsonreport.py:85): `write_json` already does
`json.dumps(body, sort_keys=True, ensure_ascii=False)` with no trailing newline —
new keys ride this for free.

---

### `src/pyautopsy/cli/main.py` (Typer command) — MODIFIED

**Analog:** itself — the `walk` (main.py:138-206) and `analyze` (main.py:209-306)
commands.

**Subcommand skeleton** (main.py:138-170): `@app.command()` def `recover(...)`
copies the `walk` shape — `image: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)]`, `case: Annotated[Path, typer.Option("--case", ...)]`.

**New flags** (D-40): add `--nsrl` (`Path | None`) and `--hash-set`
(`list[Path] | None` with an allow/block sense) following the `--max-hash-size:
Annotated[int | None, typer.Option(...)] = None` shape (main.py:163-169).

**Error mapping + summary** (main.py:188-206): copy the `try/except (...) as exc:
typer.echo(... err=True); raise typer.Exit(code=_INTEGRITY_EXIT_CODE)` block and
the `typer.echo("... complete\n  ...")` deterministic summary. Reuse
`_INTEGRITY_EXIT_CODE` (main.py:41).

**Input validation before work** (main.py:181-186): mirror the timezone-validation
guard for new untrusted inputs (e.g. assert the `--nsrl` path exists/readable —
Typer `exists=True` on the option covers most of it).

---

### `tests/test_recover.py` (NEW)

**Analogs:** `tests/test_walk.py` (fixture-image integration via the `tiny_ext4_image`
conftest fixture) + `tests/test_readonly_guarantee.py::test_source_unchanged_after_walk`
(readonly.py:37-57, the stat-before/after pattern) for the D-42 read-only case.

Copy: pytest functions taking `tiny_ext4_image: Path, tmp_path: Path`,
`run_ingest(...)` then the new `run_recover(...)`, asserting EXACT ground-truth
constants from `make_fixtures.py` (e.g. `EXT4_DELETED_CONTENT` round-trips). Use
`tests/fixtures/fake_fs.py` style fakes for pure tier-classification unit tests
(no image needed). Honesty test mirrors the Phase-3 WR-02 copy test: assert no
intent/good-bad substring appears in tier copy or report sections.

---

### `tests/test_knownfiles.py` (NEW)

**Analog:** `tests/test_integrity.py` (hex/digest unit tests with plain values and
in-memory inputs). Build a tiny NSRL-format SQLite fixture (a `FILE` table + a
`METADATA` variant, a couple of UPPERCASE-hash rows) at fixture-build time
(RESEARCH §Wave 0 Gaps), then unit-test md5→sha1→sha256 matching, the
uppercase/lowercase normalization (Pitfall 4), `FILE`-vs-`METADATA` discovery, and
custom allow/block parsing of comment/blank/mixed-case lines.

---

### `tests/fixtures/make_fixtures.py` (MODIFIED)

**Analog:** itself — `build_tiny_ext4_image` (make_fixtures.py:140-180).

**debugfs request-file pattern** (make_fixtures.py:158-179): copy to build the new
fixtures — (a) an **orphan** (write a file in a subdir, then `rm` the file AND
`rmdir`/remove its parent so the inode has no surviving parent), (b) an
**overwritten** deleted entry (write a file, `rm` it, write a new file that reclaims
its blocks). Add an NTFS **resident deleted** file fixture via the `ntfscp`-then-
delete path (make_fixtures.py:210-234).

**Ground-truth constants** (make_fixtures.py:97-110, `FS_FILE_NAME`,
`EXT4_DELETED_NAME`, `EXT4_DELETED_CONTENT`, uid/gid/mode): add analogous module
constants for the new fixtures so `test_recover.py` asserts EXACT bytes/counts.

**`_require_tool` + committed-image convention** (make_fixtures.py:121-131, 372-388):
new builders use `_require_tool` and register in `main()`'s `builders` tuple so
`python tests/fixtures/make_fixtures.py` regenerates them; the built `.img` files
are committed (CI never runs mkfs). Build the NSRL SQLite fixture deterministically
here too (stdlib `sqlite3`, no external tool).

---

### `tests/test_reproducibility.py` + `tests/test_readonly_guarantee.py` (MODIFIED)

**Analog:** themselves.

**Byte-identical report across runs** (reproducibility.py:147-188,
`test_two_analyze_runs_byte_identical_report`): copy `_analyze` (reproducibility.py:49-69)
to add `--recover`/`--nsrl`/`--hash-set` args, run twice into `case_a`/`case_b`,
assert `report.json` and `report.html` whole-file byte-equal AND recovered/ filenames
identical (D-41/Pitfall 6). Add `test_default_analyze_unchanged` (D-40) — default
`analyze` report stays byte-identical to the Phase-3 baseline.

**Read-only source after recover** (readonly.py:37-57): copy
`test_source_unchanged_after_walk` — stat before, `run_ingest` + `run_recover`,
stat after, assert `st_mtime_ns` + `st_size` unchanged (D-42).

## Shared Patterns

### Single native-seam allowlist (D-14)
**Source:** `src/pyautopsy/evidence/filesystem.py:36-40` (the docstring contract) +
`tests/test_seam_allowlist.py:25-30` (the executable gate, `_ALLOWLIST`).
**Apply to:** `core/recover.py`, `core/knownfiles.py`, `filter/nsrl.py`,
`filter/hashsets.py` — NONE may `import pytsk3`. All inode reads / run enumeration /
the derived allocated-block set go through new `filesystem.py` functions that
return plain ints and `read_random` closures.

### CaseStore is the sole DB writer (D-08/D-35/D-39)
**Source:** `src/pyautopsy/case/store.py:54-55` (class docstring) +
`_FILES_COLUMNS`/`_FILES_INSERT_SQL`/`_file_row_params` (store.py:588-654).
**Apply to:** recovered-row writes and known-match writes — new `insert_*` methods
on `CaseStore`; no raw SQL anywhere in `recover.py`/`knownfiles.py`/`filter/*`.
The `sqlite3` use in `filter/nsrl.py` is a READ-ONLY external DB, not `case.db` —
that is allowed and distinct from the sole-writer rule.

### Read-only / never-mount the source (D-42 / P1)
**Source:** `src/pyautopsy/evidence/integrity.py:392-433` (`assert_source_not_mounted`)
and the seam's `_make_reader` "read-only; never writes or mounts" note
(filesystem.py:302-304). `run_walk` re-asserts the guard (walk.py:474, 508).
**Apply to:** `run_recover` — re-assert `assert_source_not_mounted` before reading,
write ONLY under the case dir's `recovered/` tree, and let the Phase-1 end-of-run
re-verify (inside `run_ingest`) still run.

### Confined, sanitized writes (D-33/D-34, Security V5)
**Source:** `src/pyautopsy/util/safe_extract.py` — `_sanitize_name` (lines 144-168),
`_confined_target` (lines 171-195), `ExtractionLimits` (lines 73-93).
**Apply to:** writing recovered bytes. A deleted filename is adversarial input
(may contain `../`, control chars, FAT `?`/`_`). RESEARCH Code-Example
"recovered_path" composes these into a deterministic `vol<id>-off<off>/<meta_addr>-<safe_name>`
target — never the raw name. Honor a recovered-size cap (the `ExtractionLimits`
ethos / `max_hash_size`).

### Single-pass MD5/SHA-1/SHA-256 (D-17/D-37)
**Source:** `src/pyautopsy/evidence/integrity.py:195-266` (`hash_file`), already
wired through `walk.py:328-348` (`_content_fields`).
**Apply to:** hashing recovered bytes and (already-computed) allocated-file hashes
for NSRL keying. Never add a second hashing loop. `EMPTY` (integrity.py:63-67) is
the zero-byte sentinel; a short read returns `None` (no partial digest).

### Deterministic, run-metadata-free report body (D-25/D-26/D-41)
**Source:** `src/pyautopsy/report/assemble.py:99-332` (sorted-key aggregation) +
`src/pyautopsy/report/jsonreport.py:85` (`json.dumps(sort_keys=True, ensure_ascii=False)`,
no trailing newline) + `store.get_timeline_events` ORDER BY (store.py:557-561).
**Apply to:** all new report sections + any new store reader — order via the store,
project to plain dicts, no wall-clock, byte-identical across runs.

### Honest status copy — no overclaiming (D-32/D-38, Phase-3 WR-02 lesson)
**Source:** `src/pyautopsy/report/assemble.py:38-67` (the verbatim, honesty-reviewed
copy strings and the three-state integrity logic, assemble.py:230-243).
**Apply to:** confidence-tier copy ("data survival, never intent"), the neutral
"known" framing ("noise reduction, never good/bad"), and the per-filesystem caveats
(ext4 pointer-zeroing, NTFS resident, FAT first-char-lost). Stamp caveats into
`attributes` so the report never presents a tier or a hash as bare certainty
(mirrors walk.py:366 `file_type_provenance`).

### Audit two-arm error handling (expected vs crashed)
**Source:** `src/pyautopsy/core/walk.py:225-233, 579-600` and
`src/pyautopsy/core/analyze.py:89-98, 282-304`.
**Apply to:** `run_recover` and the filtering pass — `_EXPECTED_*_ERRORS` tuple,
`except _EXPECTED... -> *.error FAIL -> raise`, `except Exception -> *.crashed FAIL
-> raise`, always writing the terminal FAIL before propagating.

## No Analog Found

None. Every Phase-4 file maps to an in-tree analog. The only genuinely new logic
(confidence-tier classification and the derived allocated-block set) is pure
composition over the seam's plain-int outputs and is fully specified by
RESEARCH §Pattern 2 / §Code Examples with verified-working code — it has no
existing structural analog only because no prior phase needed block-overlap
classification, but it follows the same "pure logic over a frozen value object,
no pytsk3" shape as `walk.py`'s `_macb_fields` / `_content_fields`.

## Metadata

**Analog search scope:** `src/pyautopsy/{core,evidence,case,report,cli,util}/`,
`tests/` (graphmind-indexed project; files read directly).
**Files scanned:** 14 source files + 6 test files + schema + 2 templates dir checks.
**Pattern extraction date:** 2026-05-31
