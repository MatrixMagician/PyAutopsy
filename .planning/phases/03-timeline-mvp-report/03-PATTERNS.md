# Phase 3: Timeline & MVP Report - Pattern Map

**Mapped:** 2026-05-31
**Files analyzed:** 13 (8 source + 5 test/config)
**Analogs found:** 11 / 13 (2 are first-of-kind: HTML template, JSON emitter — partial analog via the `json.dumps(sort_keys=True)` primitive)

> Source of truth for the file plan is `03-RESEARCH.md` §"Recommended Project Structure". Field mappings, schema, and ordering come from D-21..D-28. This map binds each new/modified file to the closest existing PyAutopsy file and the exact lines to copy from. All line references are to files read this session.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/pyautopsy/case/schema.sql` (ADD `timeline_events` table + indexes) | migration/DDL | persistence | same file — existing `files` / `volume_limitations` DDL (schema.sql:55-112) | exact |
| `src/pyautopsy/case/models.py` (ADD `TimelineEvent` dataclass) | model | transform | same file — `FileRow` (models.py:82-148) | exact |
| `src/pyautopsy/case/store.py` (ADD `insert_timeline_events` / `get_timeline_events`) | service (repository) | CRUD | same file — `insert_files`/`get_files`/`_FILES_COLUMNS` (store.py:325-421, 503-569) | exact |
| `src/pyautopsy/timeline/builder.py` (NEW: `build_timeline`) | service (producer) | transform / event-driven | `core/walk.py` `_build_file_row` + `run_walk` (walk.py:371-421, 424-610) | role-match |
| `src/pyautopsy/report/assemble.py` (NEW: `assemble_report_body`) | service | transform / read-aggregation | `core/walk.py` read-aggregation over `get_files`; determinism from `audit/log.py:104` | role-match |
| `src/pyautopsy/report/jsonreport.py` (NEW: `write_json`) | utility | file-I/O | `audit/log.py` `_append` + `json.dumps(sort_keys=True, ensure_ascii=False)` (log.py:104, 107-119) | partial (primitive only) |
| `src/pyautopsy/report/htmlreport.py` (NEW: `render_html`, Jinja2) | utility | file-I/O / transform | none in-repo (first templating code); confinement from `audit/log.py:_is_within` (log.py:38-59, 122-124) | no analog (use RESEARCH Code Examples) |
| `src/pyautopsy/report/templates/report.html.j2` (NEW) | config (template) | render | none in-repo | no analog (use 03-UI-SPEC.md) |
| `src/pyautopsy/core/analyze.py` (NEW: `run_analyze` + `AnalyzeResult`) | service (orchestrator) | request-response / batch | `core/ingest.py` `run_ingest`/`IngestResult` + `core/walk.py` `run_walk`/`WalkResult` (ingest.py:60-280, walk.py:236-256, 424-610) | exact |
| `src/pyautopsy/cli/main.py` (ADD `analyze` command) | controller (CLI) | request-response | same file — `walk`/`ingest` commands (main.py:65-205) | exact |
| `pyproject.toml` (ADD `jinja2`, verify template packaging) | config | — | same file — `dependencies` + `[tool.hatch.build.targets.wheel]` (pyproject.toml:26-31, 48-49) | exact |
| `tests/test_timeline.py`, `tests/test_report.py`, `tests/test_analyze.py` (NEW) | test | — | `tests/test_walk.py` (helpers, fixtures, RED scaffold) | role-match |
| `tests/test_reproducibility.py` (EXTEND: byte-identical report test) | test | — | same file — `_ingest`/`_analytical_fields`/`_RUN_METADATA_COLUMNS` (test_reproducibility.py:27-93) | exact |

---

## Pattern Assignments

### `src/pyautopsy/case/schema.sql` — ADD `timeline_events` (migration/DDL)

**Analog:** the `files` and `volume_limitations` table blocks in the same file.

**Conventions to copy** (schema.sql:63-112): every table = `id INTEGER PRIMARY KEY AUTOINCREMENT`, typed core columns NOT NULL where the model guarantees them, FK via `REFERENCES evidence_sources (id)` / `REFERENCES files (id)`, a JSON blackboard `attributes TEXT NOT NULL DEFAULT '{}'` (D-02), and a `CREATE INDEX IF NOT EXISTS idx_<table>_evidence_source_id` per table. Header comment block explaining the table's role (matching the `files` comment style, schema.sql:55-62).

**Note:** `volume_id`/`volume_offset` are declared `NOT NULL` on `files` (schema.sql:70-71) with the WR-06 rationale "FileRow types both as non-optional int" — mirror that exactly for `timeline_events`. Use the DDL and the D-26 ordering index given verbatim in 03-RESEARCH.md lines 346-368 (`idx_timeline_events_order` on `ts_utc, volume_id, volume_offset, path, event_type, meta_addr`).

---

### `src/pyautopsy/case/models.py` — ADD `TimelineEvent` (model, transform)

**Analog:** `FileRow` (models.py:82-148).

**Pattern to copy:** `@dataclass(frozen=True, slots=True)` (models.py:82), required typed fields first then `None`-defaulted optionals, `attributes: dict[str, Any] = field(default_factory=dict)` and `id: int | None = None` as the **last two** fields (models.py:147-148). Full Args docstring per field. Timestamp fields are UTC ISO-8601 strings or `None` (module docstring models.py:8-9). Add `"TimelineEvent"` to `__all__` (models.py:17-23) and re-export from `case/__init__.py` (`__init__.py` exports `FileRow` etc.).

**Field shape (from 03-RESEARCH.md:217-235, planner finalizes `actor`/`source` encoding per D-23):**
```python
@dataclass(frozen=True, slots=True)
class TimelineEvent:
    evidence_source_id: int
    ts_utc: str
    source: str
    event_type: str          # modified|accessed|changed|born
    volume_id: int
    volume_offset: int
    path: str
    meta_addr: int | None = None
    actor: str | None = None
    action: str | None = None   # reserved (Phase 5)
    outcome: str | None = None  # reserved (Phase 5)
    file_id: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
```

---

### `src/pyautopsy/case/store.py` — ADD `insert_timeline_events` / `get_timeline_events` (repository, CRUD)

**Analog:** the `files` insert/query path (store.py:325-421) + the module-level `_FILES_COLUMNS` / `_FILES_INSERT_SQL` / `_file_row_params` helpers (store.py:503-569).

**Bulk-insert pattern** (store.py:343-361) — copy structure exactly, including the `_commit_unless_in_transaction()` so it composes inside an outer `transaction()`:
```python
def insert_files(self, rows: Iterable[FileRow]) -> int:
    params = [_file_row_params(row) for row in rows]
    if params:
        self.connection.executemany(_FILES_INSERT_SQL, params)
    self._commit_unless_in_transaction()
    return len(params)
```

**Column-tuple + SQL-builder pattern** (store.py:503-539) — define `_TIMELINE_COLUMNS`, derive `_TIMELINE_INSERT_SQL` by `", ".join(...)`, and a `_timeline_event_params(event)` that serialises `attributes` via `json.dumps(event.attributes, sort_keys=True)` (store.py:568) and coerces bools to int if any (cf. store.py:554).

**Ordered read** — UNLIKE `get_files` (which orders by `id`, store.py:417-420), `get_timeline_events` MUST apply the **D-26 total order** in the `ORDER BY` (the single place read ordering is defined — RESEARCH:372-374): `ORDER BY ts_utc, volume_id, volume_offset, path, event_type, meta_addr`. Accept an optional `limit` param for the D-27 bounded HTML slice. Reconstruct each row via `_load_attributes(row["attributes"])` (store.py:572-582). Class docstring (store.py:1-11) states "the ONLY sanctioned way to read or write case.db (no raw SQL is permitted elsewhere)" — so the timeline `ORDER BY` lives here, never in the builder/reporter.

---

### `src/pyautopsy/timeline/builder.py` — NEW `build_timeline` (producer, transform)

**Analog:** `core/walk.py` — the `_build_file_row` mapper (walk.py:371-421) and the `run_walk` store/transaction/audit shell (walk.py:424-610).

**Mapper pattern** (walk.py:371-421): a pure `_explode(file_row) -> list[TimelineEvent]` that reads the already-normalized `*_utc` columns verbatim (NEVER re-derives from epochs — RESEARCH:270-271). One event per populated MACB column; `None` ⇒ no event (D-24). MACB→event-type map per RESEARCH:380-400. Mirror the `actor` derivation idea (`uid`/`gid`) — `_build_file_row` shows how walk reads `entry.uid`/`entry.gid` (walk.py:412-413 region).

**Orchestrator shell** (walk.py:498-610): open store, wrap inserts in `with store.transaction():` (walk.py:510), read `store.get_files(source_id)`, explode, `store.insert_timeline_events(events)`. Return an analytical-only count (cf. `WalkResult`, walk.py:236-256 — "never wall-clock metadata"). Add `timeline/__init__.py` exporting `build_timeline` (mirror `core/__init__.py`).

**Important:** the builder does NOT import pytsk3 — it reads store rows only (cf. walk.py:36-37 "does not import pytsk3"). Whether build folds into the reporter is Claude's discretion (CONTEXT D-23 discretion / RESEARCH:208); the producer/reporter split above matches ARCHITECTURE Pattern 1.

---

### `src/pyautopsy/report/assemble.py` — NEW `assemble_report_body` (service, read-aggregation)

**Analog:** read-aggregation over the `CaseStore` read API; determinism primitive from `audit/log.py:104`.

**Pattern:** a pure function reading `store.get_case`, `store.get_evidence_source`, `store.get_files`, `store.get_volume_limitations`, `store.get_timeline_events` (all in store.py) and returning ONE plain dict containing only analytical content (D-25 / RESEARCH:254-256). Build the section order fixed by 03-UI-SPEC.md §"Report Section Hierarchy" (lines 123-137). Findings (D-28) = inventory stats + integrity PASS/FAIL + volume limitations — aggregate counts from `get_files` (allocated vs `allocated is False` for deleted, cf. walk.py:555). Surface Phase-2 provenance flags from `file_row.attributes` (`time_precision`, `assumed_timezone`, `file_type_provenance` — set in walk.py:202-203, 366) into the report — do NOT drop them (RESEARCH Pitfall 2).

**Determinism rules (binding):** NO `datetime.now()` / `utc_now()` reachable here (RESEARCH:259, 285). Timeline list comes pre-sorted from `get_timeline_events` (D-26). Generation timestamp/host/durations go ONLY into a separately-assembled `run_metadata` dict, never the body.

---

### `src/pyautopsy/report/jsonreport.py` — NEW `write_json` (utility, file-I/O)

**Analog:** `audit/log.py` — the serialization primitive (log.py:104) and the confined-write discipline (log.py:107-124).

**Serialization (copy exactly):**
```python
# Source: src/pyautopsy/audit/log.py:104
line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
```
For the single JSON document: `json.dumps(body, sort_keys=True, ensure_ascii=False)`. Lock ONE trailing-newline convention and assert it in the CLI-02 test (RESEARCH:284). `ensure_ascii=False` keeps non-ASCII filenames as real UTF-8.

**Path confinement (copy the idea):** compute the output path only from `case_dir` + fixed name `reports/report.json`; validate with the `_is_within(path, root)` realpath check (log.py:122-124) exactly as `AuditLog.__init__` does (log.py:52-57). Create a `reports/` subdir the way `CaseStore.create` makes `logs/`/`exports/` from `_SUBDIRS` (store.py:37, 88-92) — planner should add `"reports"` to `_SUBDIRS` or mkdir in the reporter.

---

### `src/pyautopsy/report/htmlreport.py` — NEW `render_html` (utility, Jinja2) — NO in-repo analog

**Pattern source:** 03-RESEARCH.md §"Jinja2 offline, autoescaped, deterministic environment" (lines 322-341) — verbatim recommended setup:
```python
from importlib.resources import files
from jinja2 import Environment, FileSystemLoader, select_autoescape
template_dir = files("pyautopsy.report") / "templates"
env = Environment(
    loader=FileSystemLoader(str(template_dir)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
)
html = env.get_template("report.html.j2").render(body=body, run_metadata=run_meta)
```
Reuse the SAME path-confinement check from `audit/log.py:_is_within` (log.py:122-124) for `reports/report.html`. Read a BOUNDED timeline slice via `get_timeline_events(..., limit=cap)` — never materialize the full set then slice (RESEARCH Pitfall 5). Autoescape ON; never `| safe` on evidence-derived values (RESEARCH Pitfall 3 / UI-SPEC line 21).

---

### `src/pyautopsy/report/templates/report.html.j2` — NEW template — NO in-repo analog

**Spec source:** 03-UI-SPEC.md is the authoritative contract — section order (UI-SPEC:123-137), inline single `<style>` block (no CDN/web fonts, UI-SPEC:27, 46), status encoding table (UI-SPEC:107-118), truncation disclosure wording (UI-SPEC:170), copywriting contract (UI-SPEC:162-176), determinism constraints (UI-SPEC:196-203). Iterate the timeline over an already-sorted list, never a dict/set (UI-SPEC:201).

**Packaging:** verify the `.j2` ships in the wheel — `[tool.hatch.build.targets.wheel] packages = ["src/pyautopsy"]` (pyproject.toml:48-49) includes package files by default; if missed add a `force-include`/`artifacts` entry (RESEARCH Assumption A5).

---

### `src/pyautopsy/core/analyze.py` — NEW `run_analyze` + `AnalyzeResult` (orchestrator)

**Analog:** `core/ingest.py` `run_ingest`/`IngestResult` (ingest.py:60-280) and `core/walk.py` `run_walk`/`WalkResult` (walk.py:236-610). This is an **exact** structural analog.

**Result dataclass** — copy `IngestResult` shape (ingest.py:60-88): `@dataclass(frozen=True, slots=True)`, "analytical (reproducible) content — never wall-clock metadata" docstring, full Args docs.

**Composition** (per RESEARCH:404-417 and D-21): call `run_ingest(...)` then `run_walk(...)` (re-verify already runs inside `run_ingest`, ingest.py:246-247), then open the store and `build_timeline` + `render_report`:
```python
# Source: derived from cli/main.py + core/ingest.py + core/walk.py (RESEARCH:404-417)
ingest_result = run_ingest(image, case_dir, examiner=..., evidence_id=..., acquisition_hash=...)
walk_result = run_walk(image, case_dir, timezone=timezone, max_hash_size=max_hash_size)
with CaseStore.open(case_dir) as store:
    build_timeline(store, ingest_result.evidence_source_id)
    render_report(store, ingest_result.evidence_source_id)
return AnalyzeResult(...)
```

**Error/audit pattern** — copy from `run_walk` (walk.py:579-602): an `_EXPECTED_*_ERRORS` tuple (walk.py:225-233), a `walk.error`-style FAIL audit before propagating, a distinct `*.crashed` event for genuine bugs, `finally: store.close()`. Define an `AnalyzeError` like `WalkError`/`IngestError` (walk.py:207-214, ingest.py:50-57). Audit `analyze.start`/`analyze.end` like `run_walk` does (walk.py:485-491, 570-578). Use `CaseStore` context-manager form (`with CaseStore.open(...)`, store.py:141-150).

**Planner decision (RESEARCH Assumption A2 / lines 418):** fresh-case semantics — recommend failing if `case.db` already exists (cleanest for reproducibility). Add to `core/__init__.py` exports (mirror `core/__init__.py`).

---

### `src/pyautopsy/cli/main.py` — ADD `analyze` command (controller, request-response)

**Analog:** the `walk` and `ingest` commands in the same file (main.py:65-205).

**Imports** (main.py:25-28): `from pyautopsy.core.analyze import AnalyzeError, run_analyze` alongside the existing orchestrator imports.

**Command shell pattern** — copy the `walk` command exactly (main.py:137-205):
- `@app.command()` with `Annotated[...]` Typer args/options. Mirror `ingest`'s `image`/`--case`/`--examiner`/`--evidence-id`/`--acquisition-hash` (main.py:66-97) PLUS `walk`'s `--timezone`/`--max-hash-size` (main.py:155-168) — exactly the D-21 surface.
- Up-front timezone validation block (main.py:180-185): `ZoneInfo(timezone)` in try/except → usage error.
- try/except around the orchestrator mapping forensic failures to `raise typer.Exit(code=_INTEGRITY_EXIT_CODE)` AFTER the orchestrator's FAIL audit (main.py:187-196). Catch `(AnalyzeError, IntegrityError, MountedSourceError, ImageOpenError, ...)`.
- Concise multi-line `typer.echo` summary (main.py:198-205) including report output paths.

---

### `pyproject.toml` — ADD jinja2 (config)

**Analog:** same file, `dependencies` list (pyproject.toml:26-31) and `[tool.hatch.build.targets.wheel]` (48-49).

Add `"jinja2>=3.1,<4"` to `[project.dependencies]` (RESEARCH:104-107). Pure-Python, no native seam (D-14 unaffected). Verify `report/templates/*.j2` ships in the wheel (already-listed `packages` includes package files by default; add `force-include`/`artifacts` only if a built wheel omits it — RESEARCH:342-343, A5).

---

### `tests/test_timeline.py` / `tests/test_report.py` / `tests/test_analyze.py` — NEW (tests)

**Analog:** `tests/test_walk.py` (helpers + RED scaffold) and `tests/conftest.py` (fixtures).

**Patterns to copy:**
- `from __future__ import annotations`, module docstring stating which plan/req the RED scaffold covers (test_walk.py:1-12).
- Committed-fixture fixtures injected via `conftest.py`: `tiny_ext4_image`, `tiny_fat32_image` (conftest.py:53-79). For autoescape unit test, synthesize an in-test `FileRow`/`TimelineEvent` (no new committed image — RESEARCH:526) using the `_reg_entry`/`_bytes_reader` style helpers (test_walk.py:33-77).
- `_ingest_then_walk` helper pattern (test_walk.py:80-88) — adapt to a `_analyze` helper invoking the `analyze` CLI via `CliRunner` (cf. test_reproducibility.py:30-45).
- Exact-count Nyquist assertions against recorded fixture ground truth (test_walk.py:28-30) for the MACB-explosion event counts.
- Node IDs must match the RESEARCH Test Map (RESEARCH:494-506): e.g. `test_total_order`, `test_ext4_timeline`, `test_json_report`, `test_html_autoescape`, `test_html_truncation_note`, `test_findings_d28`, `test_fat_provenance`, `test_versions_recorded`, `test_analyze_produces_reports`, `test_analyze_composes_pipeline`.

---

### `tests/test_reproducibility.py` — EXTEND (test) — EXACT analog (same file)

**Analog:** the existing helpers in the same file (test_reproducibility.py:27-93).

**Pattern to copy:**
- `_RUN_METADATA_COLUMNS` exclusion set idea (test_reproducibility.py:27) — extend to the report's segregated `run_metadata` region (D-25).
- `_ingest(image, case)` CliRunner helper (test_reproducibility.py:30-45) — add a parallel `_analyze(image, case)` invoking the new `analyze` command.
- Two-runs-into-separate-dirs structure (test_reproducibility.py:75-93): run into `case_a` and `case_b`, then assert byte equality:
```python
# Heart of CLI-02 (RESEARCH:513-519)
assert (case_a/"reports"/"report.json").read_bytes() == (case_b/"reports"/"report.json").read_bytes()
```
- Sanity-assert the body is non-empty / contains the known fixture's timeline events — mirror the existing `assert fields_a["evidence.sha256"]` non-empty guard (test_reproducibility.py:90-93) to avoid an empty-dict false pass.
- Negative assert: the segregated run-metadata generation timestamp IS present and DOES differ between runs (mirror `test_run_metadata_is_segregated`, test_reproducibility.py:96-120; checks `+00:00` suffix and that the column is excluded).
- Use `tiny_ext4_image` (RESEARCH:516) rather than `tiny_raw_image`.

---

## Shared Patterns

### Deterministic JSON serialization (CLI-02 / D-25)
**Source:** `src/pyautopsy/audit/log.py:104`; also `case/store.py:218,282,447,568`.
**Apply to:** `report/jsonreport.py`, `report/assemble.py`, every `attributes` write in `case/store.py`.
```python
json.dumps(record, sort_keys=True, ensure_ascii=False)
```

### UTC-everywhere timestamps (D-10)
**Source:** `src/pyautopsy/util/timeutil.py` — `iso_utc`, `from_epoch_utc` (the ONLY sanctioned timestamp source; `iso_utc` raises on naive datetimes).
**Apply to:** any timestamp in the report. BUT: the timeline copies the already-persisted `*_utc` strings verbatim — it does NOT reformat or re-derive (RESEARCH:270-271). `utc_now()`/`iso_utc()` are allowed ONLY in the `run_metadata` assembly (D-25), never in `assemble_report_body`.

### Case-directory path confinement (Security V12)
**Source:** `src/pyautopsy/audit/log.py:122-124` (`_is_within`) + `AuditLog.__init__` (log.py:52-57); subdir creation in `CaseStore.create` (store.py:88-92, `_SUBDIRS` store.py:37).
**Apply to:** `report/jsonreport.py`, `report/htmlreport.py` — build paths from `case_dir` + fixed names only (`reports/report.{json,html}`), validate with `_is_within`, create `reports/` like `logs/`.

### Frozen-slots dataclass model with JSON `attributes` blackboard (D-02)
**Source:** `src/pyautopsy/case/models.py:82-148` (`FileRow`).
**Apply to:** `TimelineEvent` and any new model — `@dataclass(frozen=True, slots=True)`, `attributes` + `id` as the last two fields, full Args docstring.

### Orchestrator FAIL-before-propagate audit + analytical-only result (REPORT-02 / P3)
**Source:** `core/walk.py:579-602` (expected-vs-crashed split, `finally: store.close()`); `core/ingest.py:258-270`; `WalkResult`/`IngestResult` "never wall-clock metadata" dataclasses (walk.py:236-256, ingest.py:60-88).
**Apply to:** `core/analyze.py` — `analyze.start`/`analyze.end`/`analyze.error`/`analyze.crashed` audit events; `AnalyzeResult` carries only reproducible content.

### Single-writer store + atomic transaction (WR-01)
**Source:** `case/store.py` — `CaseStore` is the SOLE DB abstraction (store.py:1-11); `transaction()` (store.py:154-182); `_commit_unless_in_transaction` (store.py:184-187).
**Apply to:** `timeline/builder.py` must write through `insert_timeline_events` inside `with store.transaction():` (cf. walk.py:510); NO raw SQL outside `store.py` — the D-26 `ORDER BY` lives in `get_timeline_events`.

### Thin Typer command shell over orchestrator (D-12)
**Source:** `cli/main.py:137-205` (`walk`), `:65-134` (`ingest`); `_INTEGRITY_EXIT_CODE` (main.py:40).
**Apply to:** the `analyze` command — validate inputs, call `run_analyze`, map forensic exceptions to `typer.Exit(_INTEGRITY_EXIT_CODE)` after the orchestrator's FAIL audit, echo a concise summary.

---

## No Analog Found

| File | Role | Data Flow | Reason / Substitute Source |
|------|------|-----------|----------------------------|
| `src/pyautopsy/report/htmlreport.py` | utility | file-I/O/render | First Jinja2 code in repo. Use 03-RESEARCH.md:322-341 (verified env setup) + reuse `audit/log.py:_is_within` for confinement. |
| `src/pyautopsy/report/templates/report.html.j2` | config (template) | render | First template in repo. Use 03-UI-SPEC.md as the authoritative visual/copy/determinism contract. |

> `report/jsonreport.py` is listed in the table as "partial": no JSON-emitter file exists, but the exact serialization primitive (`json.dumps(sort_keys=True, ensure_ascii=False)`) and the confined-write discipline are fully established in `audit/log.py`.

## Metadata

**Analog search scope:** `src/pyautopsy/{case,core,cli,audit,util}/`, `tests/`, `pyproject.toml` (read directly — project is graphmind-indexed but the file plan was small enough to read each analog in full).
**Files scanned (read in full this session):** `case/store.py`, `case/models.py`, `case/schema.sql`, `case/__init__.py`, `core/ingest.py`, `core/walk.py`, `core/__init__.py`, `cli/main.py`, `audit/log.py`, `util/timeutil.py`, `tests/test_reproducibility.py`, `tests/test_walk.py`, `tests/conftest.py`, `pyproject.toml`.
**Pattern extraction date:** 2026-05-31
