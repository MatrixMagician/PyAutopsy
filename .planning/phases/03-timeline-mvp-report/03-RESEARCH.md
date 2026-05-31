# Phase 3: Timeline & MVP Report - Research

**Researched:** 2026-05-31
**Domain:** Forensic timeline generation (bodyfile/mactime) + deterministic offline report rendering (Jinja2 HTML + structured JSON) on a normalized SQLite case store
**Confidence:** HIGH on determinism technique, mactime semantics, Jinja2 offline setup, and integration surface (all verified against the installed runtime and the existing codebase); MEDIUM on exact JSON schema shape (Claude's discretion) and HTML row-cap default (discretion).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-21:** `pyautopsy analyze <image> --case ...` runs the **full pipeline in one process** — ingest → walk → build-timeline → render-report — creating a fresh case and producing the complete report set. The existing **`ingest` and `walk` subcommands REMAIN** standalone. `analyze` **composes** the existing `run_ingest` / `run_walk` orchestrators (does not duplicate their logic); the Phase 1 end-of-run source-hash **re-verify still runs** as part of the composed pipeline. The `analyze` option surface mirrors `ingest` (image, `--case`, `--examiner`, `--evidence-id`, `--acquisition-hash`) plus the `walk` knobs (`--timezone`, `--max-hash-size`).
- **D-22:** MVP human report is **HTML rendered via Jinja2**; the structured report is **JSON**. **WeasyPrint/PDF is DEFERRED**. Jinja2 is a **new pure-Python dependency** added this phase (no native seam — D-14 unaffected). The HTML template is authored so a later PDF path can reuse it.
- **D-23:** **Persist a normalized timeline-event table now**, shaped as the **shared forensic-event model** (timestamp, source, type, actor, action, outcome, evidence-ref) that Phase 5 LOG-04 will reuse and TIME-02 will merge. Filesystem MACB times are the first *producer*. Phase 5 adds log producers + a merge step — **no schema churn, no backfill**.
- **D-24:** **Event granularity = one event per MACB timestamp** (classic bodyfile→mactime explosion). Each distinct M/A/C/B time becomes its own event row with `type` ∈ {modified, accessed, changed, born}; a file with 4 distinct times yields up to 4 events. **Zero/None MACB values produce NO event**.
- **D-25:** **Segregate run metadata from the analytical body.** The analytical body (timeline, inventory, findings, evidence hashes) is fully deterministic; **volatile run-metadata** (report generation timestamp, run durations, host, run-id) lives in a **distinct `run_metadata` block/section EXCLUDED from the byte-comparable body**. Two runs ⇒ byte-identical bodies.
- **D-26:** **Total, stable ordering** for the timeline: `timestamp → volume (id/offset) → path → event type (M/A/C/B) → meta_addr`. TSK/tool/pyautopsy versions are **pinned and recorded** (sourced from the Phase 1 COC: `tsk_version`, `pyautopsy_version`).
- **D-27:** **HTML shows a bounded view** (capped rows / most-relevant slice) with an explicit, honest "truncated — full timeline in JSON" disclosure; the **complete unabridged timeline lives in the JSON** report. (A CSV/bodyfile export of the full timeline is at planner discretion.)
- **D-28:** Report **findings** = **inventory summary stats** (file/dir counts, deleted-entry count, per-volume breakdown, file-type distribution) + **integrity verification result** (acquisition compare + end-of-run re-verify PASS/FAIL) + the **D-20 encrypted/unsupported volume limitations**. Report is honest about what the MVP does NOT yet analyze (limitations section).

### Claude's Discretion

- Exact `timeline_events` table schema — typed core columns vs JSON `attributes` split — consistent with D-02. Suggested mapping: `source` = `filesystem`/fs-type, `type` = MACB kind, `evidence-ref` = path + meta_addr + volume id/offset, `actor` = uid/gid (where known); planner finalizes the field mapping.
- JSON report schema shape (keys, nesting, whether pydantic models back it). Pydantic is in the recommended stack — planner decides whether to introduce it here or defer.
- HTML template structure, CSS, and theming; whether a CSV/bodyfile timeline export ships this phase.
- Output file layout within the case directory (e.g. `reports/report.html`, `reports/report.json`, run-metadata sidecar vs embedded block) — consistent with Phase 1's case-dir confinement.
- Whether the timeline build is its own internal module/orchestrator or folded into the report step; whether a standalone `timeline`/`report` subcommand is exposed in addition to `analyze` (optional).
- Bounded-HTML row cap default — pick a sane value, make it configurable if cheap.

### Deferred Ideas (OUT OF SCOPE)

- WeasyPrint / PDF rendering → later phase (template authored to allow it).
- Super-timeline (merging filesystem + log events) and log producers → Phase 5 (TIME-02, LOG-01..04).
- Deleted-recovery findings, confidence tiers, NSRL/hash-set filtering → Phase 4.
- Search (keyword/regex/IOC) report integration → Phase 5.
- CASE/UCO-conformant JSON export, report diffing across runs, config-driven recipes → v2.
- Timeline anomaly / timestomp surfacing → v2 (ANOM-01); Phase 3 only ORDERS events, does not flag anomalies.
- Optional standalone `timeline`/`report`/CSV-bodyfile export subcommands — revisit if a fixture/UAT surfaces the need.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TIME-01 | Build a chronological timeline from filesystem MACB metadata (bodyfile/mactime style) | "bodyfile/mactime Timeline Semantics" + "Architecture Patterns / Pattern 2" sections give the MACB-explosion algorithm and the `FileRow → timeline_events` mapping. The walk already produces UTC-normalized `*_utc` columns (`run_walk`); the timeline producer reads them via `CaseStore.get_files`. |
| REPORT-03 | Human-readable report (HTML) with case/COC, methodology + tool versions, findings, evidence hashes, timeline, limitations (no overclaiming) | "Jinja2 in a Forensic/Offline Context" + "Don't Hand-Roll" sections. All report inputs already exist in the store: `get_case` (COC + `pyautopsy_version`), `get_evidence_source` (hashes + `tsk_version`), `get_files` (inventory + timeline), `get_volume_limitations` (D-28 limitations). |
| REPORT-04 | Structured machine-readable JSON report alongside the human report | "JSON Report Schema" section. `json.dumps(..., sort_keys=True, ensure_ascii=False)` is the determinism primitive (already proven in `audit/log.py` and `case/store.py`). |
| CLI-01 | Single command `pyautopsy analyze <image> --case ...` produces the complete report | "Composing `analyze`" section. Compose `run_ingest` then `run_walk` then the new timeline+report step; mirror the existing thin-Typer-shell pattern in `cli/main.py`. |
| CLI-02 | Deterministic, reproducible output (stable ordering, pinned versions recorded) | "Determinism / Reproducibility" section (the hardest criterion). Extends the existing `tests/test_reproducibility.py` seed from DB-field comparison to byte-identical report-body comparison. |
</phase_requirements>

## Summary

Phase 3 closes the MVP vertical slice. Every input the timeline and report need **already exists** in the case store and is already UTC-normalized: Phase 2's `run_walk` writes `mtime_utc`/`atime_utc`/`ctime_utc`/`crtime_utc` as tz-aware ISO-8601 strings (or `None` for a 0 epoch), plus volume/path/meta_addr/uid/gid/file_type, and Phase 1's COC carries `tsk_version`, `pyautopsy_version`, `md5`, `sha256`. So this phase is **pure-Python composition over the read API** — no new native code, no new timestamp logic (the hard timezone work is done and tested). Three genuinely new things ship: (1) a `timeline_events` table + producer that explodes MACB columns into normalized event rows (D-23/D-24), (2) a deterministic JSON + Jinja2-HTML reporter (D-22), and (3) the `analyze` command composing the two existing orchestrators (D-21).

The single hardest criterion is **CLI-02 byte-identical reproducibility**. The project has already solved the *technique* in three places you must follow exactly: `audit/log.py` and `case/store.py` both serialize JSON with `json.dumps(..., sort_keys=True)` and segregate wall-clock metadata; `core/ingest.py`/`core/walk.py` return analytical-only result dataclasses; `tests/test_reproducibility.py` already compares two runs with `_RUN_METADATA_COLUMNS` excluded. Phase 3 extends this discipline to the *rendered report bytes*: build a deterministic body dict (timeline sorted by the D-26 total order, findings sorted, dicts emitted with `sort_keys=True`), hash it for the byte-comparison, and put `run_metadata` (generation timestamp, durations, host) in a clearly-marked separate block excluded from that hash.

**Primary recommendation:** Add a `timeline/builder.py` producer (FileRow → timeline_events) and a `report/` package (a pure `assemble_report_body()` returning a deterministic dict, plus a `json` writer and a Jinja2 `html` renderer). Add `analyze` to `cli/main.py` composing `run_ingest` → `run_walk` → build-timeline → render-report. Add Jinja2 3.1.6 to `dependencies`. Drive byte-determinism through one canonical body dict serialized with `sort_keys=True`, and write a two-run byte-equality test on `tiny_ext4_image` extending the existing reproducibility test.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| MACB-explosion (FileRow → events) | Producer / orchestration (`timeline/builder.py`) | Case store (persist rows) | A producer that reads `files` and writes `timeline_events` — the blackboard pattern (ARCHITECTURE Pattern 1). Pure Python; no pytsk3. |
| `timeline_events` persistence + ordered query | Case store (`case/store.py`) | — | The store is the SOLE DB writer abstraction (no raw SQL elsewhere — enforced project-wide). New table + insert/query methods live here. |
| Inventory/findings aggregation (D-28) | Reporter assembly (`report/`) | Case store (read API) | Pure read-aggregation over `get_files` / `get_volume_limitations`; no new persistence needed for MVP findings. |
| Deterministic body assembly | Reporter assembly (`report/assemble.py` or similar) | — | One canonical dict that both JSON and HTML consume; the determinism single-source-of-truth. |
| JSON serialization | Reporter (`report/json` writer) | — | stdlib `json.dumps(sort_keys=True, ensure_ascii=False)` — same primitive already used in `audit/log.py`. |
| HTML rendering | Reporter (`report/html` renderer, Jinja2) | — | Pure-Python Jinja2; templates bundled as package data; autoescape ON (security). |
| Pipeline composition (`analyze`) | CLI orchestration (`cli/main.py` + a thin `core` composer) | `core/ingest.py`, `core/walk.py` | `analyze` composes existing orchestrators (D-21); follows the established thin-Typer-shell-over-orchestrator pattern. |
| Report file output | Case-dir confinement (Phase 1 layout) | — | All writes confined to the case dir (like `logs/audit.jsonl` and `exports/`). New `reports/` subdir recommended. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Jinja2 | 3.1.6 | HTML report templating | [CITED: STACK.md] Industry-standard templating; the deferred WeasyPrint PDF path reuses the same template. Pure Python, no native deps (D-14 safe). `[VERIFIED: installed in this env — `import jinja2; jinja2.__version__ == '3.1.6'`]` |
| json | stdlib | Structured JSON report (REPORT-04) | [VERIFIED: codebase] `json.dumps(sort_keys=True, ensure_ascii=False)` is already the determinism primitive in `audit/log.py:104` and `case/store.py`. Reuse, don't reinvent. |
| sqlite3 | stdlib | `timeline_events` persistence + ordered reads | [VERIFIED: codebase] Already the case-store backend; new table joins the existing schema. |
| Typer | >=0.12,<1 | `analyze` command | [VERIFIED: pyproject.toml] Already the CLI framework; `analyze` joins `ingest`/`walk` with the same `Annotated`-option shape. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | 2.13.4 | Typed JSON report models | [VERIFIED: installed in env] In the recommended stack (STACK.md) and present in the environment, but NOT in `pyproject.toml` dependencies. **Recommendation: DEFER for the MVP.** The report body is a closed, internally-produced dict (not untrusted input needing validation); stdlib dataclasses + `json.dumps(sort_keys=True)` already give deterministic, typed output with zero new dependency. Introducing pydantic now adds a dependency and a second serialization path (`model_dump_json`) whose key-ordering/formatting you'd have to pin for D-25 anyway. Revisit if/when the JSON schema must be validated against external consumers (v2 JSON-01 CASE/UCO). |
| Rich | >=13 | Progress output during `analyze` | [VERIFIED: pyproject.toml] Optional; pairs with Typer for a progress bar over the walk. Not required for the deliverable. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Jinja2 hand-assembled HTML body dict | pydantic `model_dump_json()` for JSON | pydantic gives validation + typed models, but adds a dependency and a separate serialization path you must pin for determinism. Defer (see above). |
| Native bodyfile/mactime producer (this phase) | TSK `fls`+`mactime` subprocess | [CITED: STACK.md] The native (pure-Python) explosion is cheaper, fully under your control, and avoids text-parsing brittleness. The data is already in the store — no need to shell out. |
| Bounded HTML + full JSON (D-27) | Full HTML timeline | Real images produce multi-hundred-MB HTML; D-27 already locks the bounded-HTML + full-JSON split. |

**Installation:**
```bash
# Add to pyproject.toml [project.dependencies]:
#   "jinja2>=3.1,<4"
# Jinja2 is pure-Python (MarkupSafe is its only dep, also pure-Python with a
# compiled-speedup fallback) — no system/native packages, D-14 gate unaffected.
pip install "jinja2>=3.1,<4"
```

**Version verification:**
```
jinja2  3.1.6   [VERIFIED: `python3 -c "import jinja2; print(jinja2.__version__)"` → 3.1.6 in this env]
pydantic 2.13.4 [VERIFIED: installed in env; recommend NOT adding to deps this phase]
Python  3.14.5  [VERIFIED: `python3 --version`] — within the declared >=3.11 range; pyproject classifies 3.11–3.14.
```

## Package Legitimacy Audit

> Jinja2 is the only new package this phase introduces. slopcheck was not available in this environment; per the graceful-degradation rule the package is tagged below with its provenance and the planner should treat the install as a normal (well-known, already-installed) dependency rather than a hand-verify gate — Jinja2 is a flagship Pallets project already present in the runtime.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| jinja2 | PyPI | ~15 yrs | ~100M+/mo | github.com/pallets/jinja | unavailable | Approved — flagship Pallets project, already installed (3.1.6), pure-Python, transitively depended on by WeasyPrint (already in STACK.md). |
| markupsafe | PyPI (transitive of jinja2) | ~14 yrs | very high | github.com/pallets/markupsafe | unavailable | Approved — Jinja2's autoescape dependency; pulled automatically. |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck was unavailable at research time. Jinja2/MarkupSafe are not `[ASSUMED]` discoveries — they are the documented STACK.md recommendation, are already importable in this environment, and are maintained flagship Pallets packages. No `checkpoint:human-verify` is warranted for these specific packages.*

## Architecture Patterns

### System Architecture Diagram

```
                        pyautopsy analyze <image> --case C
                                      │
                                      ▼
            ┌─────────────────── analyze composer (core) ───────────────────┐
            │                                                                │
            │   1. run_ingest(image, C, examiner, evidence_id, acq_hash)     │
            │        → creates case.db, COC rows, source hashes,             │
            │          end-of-run RE-VERIFY (still runs, D-21)               │
            │        → IngestResult(case_id, evidence_source_id, sha256,…)   │
            │                          │                                     │
            │   2. run_walk(image, C, timezone, max_hash_size)               │
            │        → files rows (MACB *_utc, volume, path, uid/gid,        │
            │          file_type, allocated) + volume_limitations            │
            │        → WalkResult(files_inventoried, deleted_count, …)       │
            │                          │                                     │
            │   3. build_timeline(store, evidence_source_id)   ◄── NEW       │
            │        reads files → explodes MACB → timeline_events rows      │
            │                          │                                     │
            │   4. render_report(store, evidence_source_id)    ◄── NEW       │
            └──────────────────────────┼─────────────────────────────────────┘
                                       │
            reads back via CaseStore read API (get_case, get_evidence_source,
            get_files, get_volume_limitations, NEW get_timeline_events)
                                       │
                          ┌────────────┴────────────┐
                          ▼                          ▼
              assemble_report_body()        run_metadata block
              (DETERMINISTIC dict:           (volatile: gen ts,
               COC, methodology+versions,     durations, host, run-id)
               findings(D-28), evidence        — written ONLY to the
               hashes, FULL timeline           run_metadata.json sidecar,
               sorted by D-26 order,           NEVER into the body and
               timeline_total=M)              NEVER into report.html
                          │                           │
            ┌─────────────┼─────────────┐             │
            ▼             ▼             ▼             │
   json.dumps(body,   Jinja2 render   (bounded HTML   │
   sort_keys=True,    html template   timeline slice  │
   ensure_ascii=      (autoescape ON, + truncation    │
   False)             trim_blocks)     note, D-27)     │
            │             │                            │
            ▼             ▼                            ▼
   reports/report.json  reports/report.html   reports/run_metadata.json
   (FULL timeline,      (human, bounded,       (the ONLY volatile file;
    REPORT-04,          ZERO run metadata —     gen ts, durations, host,
    no run metadata)    fully deterministic)    run-id)
                  all writes confined to case dir C (Phase 1 confinement)
```

The diagram traces the primary use case (raw image in → report set out). File-to-module mapping is in the next section.

### Recommended Project Structure

```
src/pyautopsy/
├── case/
│   ├── store.py            # ADD: insert_timeline_events / get_timeline_events; ADD TimelineEvent model handling
│   ├── schema.sql          # ADD: timeline_events table + index
│   └── models.py           # ADD: TimelineEvent dataclass (frozen, slots, attributes JSON — like FileRow)
├── timeline/               # NEW producer package
│   └── builder.py          # build_timeline(store, evidence_source_id) -> count; FileRow -> TimelineEvent explosion
├── report/                 # NEW reporter package
│   ├── assemble.py         # assemble_report_body(store, esid) -> deterministic dict (the single source of truth)
│   ├── jsonreport.py       # write_json(body, path) — json.dumps(sort_keys=True, ensure_ascii=False)
│   ├── htmlreport.py       # render_html(body, case_dir, *, cap) — Jinja2, autoescape, bounded timeline, NO run metadata
│   └── templates/
│       └── report.html.j2  # bundled as package data (importlib.resources)
├── core/
│   ├── analyze.py          # NEW: run_analyze(...) composing run_ingest + run_walk + build_timeline + render_report
│   ├── ingest.py           # unchanged (composed)
│   └── walk.py             # unchanged (composed)
└── cli/
    └── main.py             # ADD: analyze command (thin shell over run_analyze)
```

(Whether timeline-build folds into the report step, and whether standalone `timeline`/`report` subcommands ship, is Claude's discretion per CONTEXT.md. The split above keeps the producer/reporter boundary that ARCHITECTURE.md Pattern 1 mandates.)

### Pattern 1: Normalized event producer (blackboard) — TIME-01 / D-23

**What:** A producer reads `files` rows and writes normalized `timeline_events` rows; the reporter reads `timeline_events` back. Producers never talk to each other — they meet at the store. This is the project's existing spine (ARCHITECTURE Pattern 1) and is exactly what makes Phase 5's super-timeline additive: log producers write the same table shape, and TIME-02 is a single ordered read across all producers.

**When to use:** Always for this phase — it is the architectural keystone (CONTEXT "Specific Ideas").

**Example (the shape, mirroring `case/models.py` conventions):**
```python
# Source: derived from existing case/models.py FileRow + ARCHITECTURE.md events table
@dataclass(frozen=True, slots=True)
class TimelineEvent:
    evidence_source_id: int
    ts_utc: str                # the sort key; ISO-8601 +00:00 (D-10)
    source: str                # "filesystem" or fs-type (e.g. "filesystem:ext")
    event_type: str            # "modified" | "accessed" | "changed" | "born"
    volume_id: int
    volume_offset: int
    path: str
    meta_addr: int | None      # part of the D-26 total order + evidence-ref
    actor: str | None = None   # uid/gid where known (D-23 mapping)
    action: str | None = None  # reserved for log producers (Phase 5); fs leaves None/"timestamp"
    outcome: str | None = None # reserved for log producers (Phase 5)
    file_id: int | None = None # FK to files (nullable — log events may lack a file)
    attributes: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
```

### Pattern 2: MACB explosion (one event per timestamp) — D-24

**What:** For each `FileRow`, emit one `TimelineEvent` per *populated* MACB column:

| FileRow column | event_type |
|----------------|-----------|
| `mtime_utc`    | `modified` |
| `atime_utc`    | `accessed` |
| `ctime_utc`    | `changed`  |
| `crtime_utc`   | `born`     |

A `None` column produces NO event (D-24; the walk already maps a 0 epoch → `None`, so "0 epoch ⇒ not recorded" propagates correctly with no extra logic here). A file with 4 distinct populated times yields 4 events; if two columns share an identical timestamp they remain **two distinct events** (different `event_type`) — the D-26 total order groups them adjacently and the report can collapse them for display, but the persisted events stay one-per-MACB-time so Phase 5 merges cleanly.

> **mactime collapsing note (HONESTY):** classic `mactime` collapses identical M/A/C/B times for the *same file* into one display line with a combined `macb` flag string (e.g. `m.c.`). That is a **display** concern, not a persistence concern. Persist one event per timestamp (D-24); optionally collapse in the HTML rendering only. Do NOT collapse in JSON (D-27: JSON is the full, unabridged timeline).

**When to use:** The core of `timeline/builder.py`.

### Pattern 3: One deterministic body dict, two serializers — CLI-02 / D-25

**What:** `assemble_report_body()` returns ONE plain dict containing only analytical content. Both the JSON writer and the HTML renderer consume it. The volatile `run_metadata` (generation timestamp, durations, host, run-id) is assembled separately and never enters the body dict, never enters `report.html`, and is written ONLY to the `reports/run_metadata.json` sidecar (W-1 lock — see Open Questions RESOLVED). This guarantees the JSON body and the HTML body are derived from the identical source, that `report.html` is itself byte-deterministic across runs, and that the only volatile file is the sidecar.

**Anti-Patterns to Avoid:**
- **Interpolating `datetime.now()` into the report body** — [VERIFIED: PITFALLS P3] the #1 reproducibility killer. Generation time goes ONLY in the `run_metadata.json` sidecar.
- **Relying on dict insertion order / set iteration for output** — [VERIFIED: PITFALLS P3] always serialize with `sort_keys=True` and sort lists by the explicit D-26 key before emitting.
- **Each section rendering its own HTML fragment** — [CITED: ARCHITECTURE Anti-Pattern 2] one renderer reads the assembled body; sections are template blocks, not string-stitching producers.
- **Letting one malformed/huge file abort report rendering** — bound the HTML (D-27) and stream/iterate the timeline rather than building giant intermediate strings.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTML escaping of attacker-controlled filenames/paths | Manual `.replace("<","&lt;")` | Jinja2 `autoescape=select_autoescape(["html"])` (ON by default for `.html`/`.j2`) | [VERIFIED: jinja2 in env] Filenames/paths in evidence are attacker-controlled; autoescape neutralizes HTML/JS injection (Security V5). Hand-rolled escaping misses edge cases. |
| Deterministic JSON serialization | Custom key-sorter / string builder | `json.dumps(obj, sort_keys=True, ensure_ascii=False)` | [VERIFIED: codebase] Already the proven primitive in `audit/log.py:104`. `ensure_ascii=False` keeps non-ASCII filenames as real UTF-8 (matches the audit log) instead of `\uXXXX` noise. |
| UTC timestamp formatting | New datetime formatting | `pyautopsy.util.timeutil.iso_utc` / `from_epoch_utc` | [VERIFIED: codebase] The single sanctioned timestamp source (D-10); rejects naive datetimes structurally. The walk already wrote `*_utc` strings — the timeline copies them verbatim, no reformatting needed. |
| MACB→UTC conversion / FAT local-time handling | Re-deriving from epochs | The already-persisted `*_utc` columns | [VERIFIED: codebase] `core/walk.py` already did all the timezone/FAT/zero-epoch work and tested it (META-02). The timeline reads the *output* (`mtime_utc` etc.), never the raw epochs again. |
| Sorting the timeline | ad-hoc Python sort scattered around | One `ORDER BY` in `get_timeline_events` AND/OR one `sorted(key=...)` with the D-26 tuple | A single canonical sort key prevents drift between JSON and HTML ordering. |
| Path confinement for report files | Manual string checks | The `audit/log.py:_is_within` pattern + writing under `case_dir/reports/` only | [VERIFIED: codebase] Phase 1 already established case-dir confinement (`AuditLog`); reuse the same `realpath`-within-root check (Security path-traversal). |

**Key insight:** Almost nothing here is genuinely new computation — the timeline reads already-normalized columns and the report reads already-persisted rows. The risk is *re-deriving* something the lower tiers already got right (timezones, escaping, determinism). Lean on the existing helpers.

## Common Pitfalls

### Pitfall 1: Non-byte-identical report bodies across runs (CLI-02 — the hardest)
**What goes wrong:** Two runs on the same fixture produce reports that differ — a generation timestamp leaks into the body, dict ordering wobbles, the timeline sort isn't total (ties resolved by sqlite rowid which differs run-to-run), or Jinja2 whitespace varies.
**Why it happens:** [VERIFIED: PITFALLS P3] Python dict/set ordering, `datetime.now()` in the body, and SQL ordering that isn't a *total* order (equal timestamps fall back to insertion order).
**How to avoid:**
- Make the ordering a **total** order exactly per D-26: `ts_utc → volume_id → volume_offset → path → event_type → meta_addr`. No two distinct events can tie on all of these (meta_addr + event_type disambiguates same-file same-time; path + volume disambiguates across files). Apply it in `ORDER BY` and re-assert with a Python `sorted(key=...)` before serialization so the result never depends on sqlite's tiebreak.
- Serialize the body with `json.dumps(sort_keys=True, ensure_ascii=False)`. Decide one trailing-newline convention and keep it (the audit log appends `"\n"` per line; for a single JSON document pick "no trailing newline" or "one trailing newline" and lock it in the test).
- Put generation timestamp / durations / host / run-id in the `run_metadata.json` sidecar ONLY (D-25); `report.html` carries ZERO run metadata (W-1 lock). The existing `IngestResult`/`WalkResult` are already analytical-only — follow that.
- For Jinja2: set `trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True` so template whitespace is deterministic and not editor-dependent; render the timeline by iterating an already-sorted list (never a dict/set).
**Warning signs:** `datetime.now()` / `utc_now()` reachable from `assemble_report_body`; a timeline `ORDER BY ts_utc` with no further tiebreak; comparing two report files fails only on a timestamp line.

### Pitfall 2: Overclaiming / dishonest truncation (REPORT-03 / D-27 / D-28)
**What goes wrong:** The bounded HTML silently drops timeline rows, or findings imply analysis the MVP doesn't do (recovery/log conclusions), or FAT "local-time-inferred" provenance from Phase 2 is dropped.
**Why it happens:** [VERIFIED: PITFALLS P10] Convenience; the bounded view (D-27) looks complete unless you label it.
**How to avoid:** Every truncated HTML timeline carries an explicit "showing N of M events — full timeline in report.json" note. The findings section (D-28) states what the MVP does NOT analyze (a limitations subsection). Surface the Phase-2 `attributes` flags (`time_precision: local-time-inferred`, `assumed_timezone`, `file_type_provenance`) into the report — they are in the `files.attributes` JSON and must not be lost. Record `tsk_version`/`pyautopsy_version` in the methodology section (D-26).
**Warning signs:** HTML timeline length == cap with no disclosure; a finding phrased as a conclusion about user intent; FAT timestamps shown without the inferred-zone flag.

### Pitfall 3: HTML injection from evidence-controlled strings (Security V5)
**What goes wrong:** A filename like `<script>…</script>` or `"><img onerror=…>` in the evidence renders as live markup in the report HTML.
**Why it happens:** Disabling autoescape, using `| safe`, or building HTML by string concatenation.
**How to avoid:** Jinja2 autoescape ON for the HTML template; NEVER use `| safe` / `Markup()` on any evidence-derived value (path, name, file_type, limitation reason, encryption hint). The JSON path is inherently safe via `json.dumps`. Test with a fixture filename containing `<`, `>`, `&`, `"`.
**Warning signs:** `autoescape=False`, `| safe` in the template, f-string HTML assembly.

### Pitfall 4: Report files escaping the case directory (Security — path traversal)
**What goes wrong:** Report output path is derived from a caller-supplied or evidence-derived string and escapes `case_dir`.
**How to avoid:** Compute report paths ONLY from `case_dir` + fixed names (`reports/report.html`, `reports/report.json`, `reports/run_metadata.json`), never from evidence content. Reuse the `audit/log.py` `_is_within` realpath-confinement check. Create `reports/` like Phase 1 creates `logs/`/`exports/`.
**Warning signs:** A report filename built from `evidence_id` or a path component without confinement.

### Pitfall 5: Resource exhaustion on a huge real timeline (Security — DoS / Performance)
**What goes wrong:** A real image yields millions of events; building a giant in-memory list/string for HTML OOMs or hangs (PITFALLS performance traps: "holding timeline fully in RAM").
**How to avoid:** D-27's bounded HTML already caps the HTML side. For the HTML renderer, slice the body's already-assembled timeline list in-process (`body["timeline"][:cap]`) and render the honest "Showing {cap} of {timeline_total}" disclosure from `body["timeline_total"]` (W-2 lock — render_html takes no store handle). For JSON, stream/iterate from the sqlite cursor rather than materializing the full `get_timeline_events` list when large (consider a generator-based JSON writer, or accept full materialization only for MVP fixtures and document the limit).
**Warning signs:** `get_timeline_events` returns a full `list` that HTML then slices after the fact on a multi-GB image without a `timeline_total` count carried in the body.

## Code Examples

### Deterministic JSON body (the proven project primitive)
```python
# Source: VERIFIED pattern from src/pyautopsy/audit/log.py:104 and case/store.py
import json
body_bytes = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
# byte-comparable across runs because: keys sorted, no datetime.now() in `body`,
# timeline list pre-sorted by the D-26 total order, non-ASCII kept as real UTF-8.
```

### Jinja2 offline, autoescaped, deterministic environment
```python
# Source: VERIFIED against jinja2 3.1.6 installed in this env
from importlib.resources import files
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Templates bundled as package data; importlib.resources locates them whether
# the package is installed or run from a source checkout (no __file__ guessing).
template_dir = files("pyautopsy.report") / "templates"
env = Environment(
    loader=FileSystemLoader(str(template_dir)),
    autoescape=select_autoescape(["html", "j2"]),  # neutralize evidence-controlled strings
    trim_blocks=True,        # deterministic whitespace
    lstrip_blocks=True,      # deterministic whitespace
    keep_trailing_newline=True,
)
# No network/CDN: the template must inline all CSS (no <link href="http...">,
# no external fonts/scripts) so the HTML is self-contained and offline-safe.
# report.html carries NO run metadata (W-1) — render only body + the bounded slice.
html = env.get_template("report.html.j2").render(body=body)
```
Note: to package the template, add to `pyproject.toml`:
`[tool.hatch.build.targets.wheel] ... ` already lists `packages = ["src/pyautopsy"]`; ensure `report/templates/*.j2` is included (hatchling includes package files by default for listed packages; verify the `.j2` is picked up, or add a `force-include` / `artifacts` entry if needed).

### timeline_events table (D-02 typed-core + JSON attributes, matching existing schema)
```sql
-- Source: derived from existing case/schema.sql conventions + ARCHITECTURE.md events
CREATE TABLE IF NOT EXISTS timeline_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_source_id INTEGER NOT NULL REFERENCES evidence_sources (id),
    file_id            INTEGER REFERENCES files (id),   -- nullable (log events, Phase 5)
    ts_utc             TEXT    NOT NULL,                 -- the sort key, ISO-8601 +00:00
    source             TEXT    NOT NULL,                 -- 'filesystem' | 'filesystem:ext' ...
    event_type         TEXT    NOT NULL,                 -- modified|accessed|changed|born
    volume_id          INTEGER NOT NULL,
    volume_offset      INTEGER NOT NULL,
    path               TEXT    NOT NULL,
    meta_addr          INTEGER,
    actor              TEXT,                              -- uid/gid where known (D-23)
    action             TEXT,                              -- reserved (Phase 5 log producers)
    outcome            TEXT,                              -- reserved (Phase 5 log producers)
    attributes         TEXT    NOT NULL DEFAULT '{}'
);
-- Index supporting the D-26 total-order read.
CREATE INDEX IF NOT EXISTS idx_timeline_events_order
    ON timeline_events (ts_utc, volume_id, volume_offset, path, event_type, meta_addr);
CREATE INDEX IF NOT EXISTS idx_timeline_events_evidence_source_id
    ON timeline_events (evidence_source_id);
```
```sql
-- D-26 ordered read (the SINGLE place ordering is defined for reads):
SELECT * FROM timeline_events
 WHERE evidence_source_id = ?
 ORDER BY ts_utc, volume_id, volume_offset, path, event_type, meta_addr;
```

### MACB explosion (the builder core)
```python
# Source: derived from D-24 + existing FileRow columns
_MACB = (("mtime_utc", "modified"), ("atime_utc", "accessed"),
         ("ctime_utc", "changed"), ("crtime_utc", "born"))

def explode(file_row) -> list[TimelineEvent]:
    actor = None
    if file_row.uid is not None or file_row.gid is not None:
        actor = f"uid={file_row.uid},gid={file_row.gid}"
    events = []
    for col, etype in _MACB:
        ts = getattr(file_row, col)
        if ts is None:        # D-24: zero/None ⇒ no event
            continue
        events.append(TimelineEvent(
            evidence_source_id=file_row.evidence_source_id,
            file_id=file_row.id, ts_utc=ts,
            source=f"filesystem:{file_row.fs_type}" if file_row.fs_type else "filesystem",
            event_type=etype, volume_id=file_row.volume_id,
            volume_offset=file_row.volume_offset, path=file_row.path,
            meta_addr=file_row.meta_addr, actor=actor,
        ))
    return events
```

### Composing `analyze` (mirrors the existing thin-shell + orchestrator pattern)
```python
# Source: derived from cli/main.py + core/ingest.py + core/walk.py patterns
def run_analyze(image, case_dir, *, examiner, evidence_id,
                acquisition_hash=None, timezone="UTC", max_hash_size=None):
    ingest_result = run_ingest(image, case_dir, examiner=examiner,
                               evidence_id=evidence_id,
                               acquisition_hash=acquisition_hash)  # re-verify runs here (D-21)
    walk_result = run_walk(image, case_dir, timezone=timezone,
                           max_hash_size=max_hash_size)
    with CaseStore.open(case_dir) as store:
        n_events = build_timeline(store, ingest_result.evidence_source_id)
        render_report(store, ingest_result.evidence_source_id)  # writes reports/report.{html,json} + run_metadata.json
    return AnalyzeResult(...)  # analytical-only (no wall-clock), like IngestResult/WalkResult
```
Idempotency/clobber note (D-21 creates a *fresh* case): `run_ingest` calls `CaseStore.create` which `mkdir(parents=True, exist_ok=True)` then applies schema with `CREATE TABLE IF NOT EXISTS`. Re-running `analyze` against an existing `--case` would therefore APPEND a second `cases`/`evidence_sources` row to the same db (not a clean clobber). **Planner decision needed:** either (a) require `--case` to be a fresh/empty dir and fail loudly if `case.db` exists (cleanest, matches "creates a fresh case"), or (b) document append-and-use-latest. Recommend (a) — fail if `case.db` already exists — for reproducibility clarity. Audit the `analyze.start`/`analyze.end` actions like ingest/walk do (REPORT-02).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `fls`/`mactime` CLI text bodyfile | In-process explosion of already-normalized store columns | This project's design (ARCHITECTURE) | No subprocess, no text parsing; deterministic structured events. |
| wkhtmltopdf for PDF | WeasyPrint (deferred) over the same Jinja2 HTML | [CITED: STACK.md] | Template authored now so PDF is additive later (D-22). |

**Deprecated/outdated:**
- Do NOT shell out to `mactime` (the data is already in the store). Do NOT add WeasyPrint this phase (D-22 deferral — avoids pango/cairo/gdk-pixbuf native deps).

## Runtime State Inventory

> Greenfield-for-this-phase (additive feature, no rename/refactor). Included briefly because Phase 3 adds a new table to an existing DB schema.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New `timeline_events` table added to `case/schema.sql`. Existing cases created before Phase 3 won't have it, but Phase 3 cases are created fresh by `analyze`/`ingest` (schema applied at `CaseStore.create` via `CREATE TABLE IF NOT EXISTS`). | None — no migration of existing data needed (no production cases exist; this is pre-release). Schema is forward-only and idempotent. |
| Live service config | None — local CLI tool, no external services. | None. |
| OS-registered state | None. | None. |
| Secrets/env vars | None. | None. |
| Build artifacts | Adding Jinja2 to `pyproject.toml` and a `report/templates/*.j2` package-data file means the wheel build must include the template. | Verify `.j2` is included in the wheel (hatchling includes listed-package files by default; add `force-include`/`artifacts` if the template is missed). Reinstall after the dependency change. |

**Nothing found in categories:** Live service config / OS-registered state / secrets — None (verified: local Python CLI, no daemons, no external integrations in the codebase).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Defer pydantic; stdlib dataclasses + `json.dumps(sort_keys=True)` suffice for the MVP JSON report | Standard Stack / Supporting | LOW — if a richer/validated schema is needed, pydantic can be added in a later phase without rework (the body dict is the stable contract). |
| A2 | `analyze` should fail if `case.db` already exists (fresh-case semantics) rather than append | Code Examples / Composing `analyze` | MEDIUM — this is a UX/idempotency decision the planner must lock; either choice is implementable, but the determinism story is cleanest with fail-on-existing. |
| A3 | Bounded-HTML default row cap (suggest ~1,000–5,000 events) | (discretion) | LOW — purely a display default; configurable; does not affect JSON (full) or determinism. |
| A4 | `actor` encoded as `"uid=<n>,gid=<n>"` string | Code Examples / explosion | LOW — D-23 leaves the exact `actor` encoding to the planner; any stable encoding preserves determinism. |
| A5 | Hatchling includes `report/templates/*.j2` in the wheel by default | Code Examples / Jinja2 | MEDIUM — if missed, installed (non-source-checkout) runs fail to find the template; verify with a built wheel or add an explicit include. |

## Open Questions (RESOLVED)

1. **Run-metadata placement: sidecar file vs embedded HTML block? — RESOLVED**
   - What we knew: D-25 requires run metadata segregated from the byte-comparable body; either a `reports/run_metadata.json` sidecar or a clearly-marked, comparison-excluded HTML footer block satisfies it.
   - **RESOLVED (W-1 lock):** **Sidecar-only.** Run metadata (generation timestamp, durations, host, run-id) lives in a **separate `reports/run_metadata.json` file ONLY**. `report.html` carries **ZERO run metadata** — no footer block, no embedded volatile values — so it is itself fully byte-deterministic across runs. `report.json` likewise carries no run metadata in its body. `reports/run_metadata.json` is the **single volatile file**. This is the per-CONTEXT D-25 segregation realized as physical file separation, which removes the need for any "strip the footer before comparing" logic in the CLI-02 test.

2. **What exactly is byte-compared in the CLI-02 test? — RESOLVED**
   - What we knew: If the HTML embedded a run-metadata footer, comparing the whole file would always differ.
   - **RESOLVED (W-1 lock):** Because of resolution #1, the CLI-02 test asserts **whole-file byte-equality on BOTH `reports/report.json` AND `reports/report.html`** (no footer-stripping; the HTML contains no run metadata). `reports/run_metadata.json` is **excluded** from the byte comparison (it is the only file expected to differ across runs). The test additionally asserts that the segregated `run_metadata.json` generation timestamp IS present and DOES differ between runs (proving segregation is real, not accidental equality). The executor has **no runtime choice** about the comparison strategy — it is locked to sidecar-only / whole-file byte-equality on report.json + report.html.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.14.5 | — (within declared >=3.11) |
| Jinja2 | HTML report (REPORT-03) | ✓ | 3.1.6 | — (pure Python; pip-installable) |
| json / sqlite3 / dataclasses | JSON report, persistence, models | ✓ | stdlib | — |
| pytsk3 | (via composed run_ingest/run_walk) | ✓ | 20260520 | — |
| pydantic | NOT used this phase (deferred) | ✓ (2.13.4) | — | stdlib dataclasses + json |
| Test fixtures (ext4/ntfs/fat) | timeline + report tests | ✓ committed | — | already in `tests/fixtures/` (tiny_ext4.img has known file + deleted entry + MACB times) |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None — Jinja2 is already importable; add it to `pyproject.toml` to make it declared.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest [VERIFIED: pyproject.toml `[tool.pytest.ini_options]`, `pythonpath=["src"]`, `testpaths=["tests"]`] |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `python3 -m pytest tests/test_timeline.py tests/test_report.py -x -q` |
| Full suite command | `python3 -m pytest -q` |

CLI tests use `typer.testing.CliRunner` (see `tests/test_cli_smoke.py`, `tests/test_reproducibility.py`). Fixtures (`tiny_ext4_image`, `tiny_fat32_image`, etc.) are committed images injected via `conftest.py`.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TIME-01 | MACB explosion: each populated `*_utc` → one event; `None` → no event; correct `event_type` mapping | unit | `pytest tests/test_timeline.py -x` | ❌ Wave 0 |
| TIME-01 | Total order is exactly D-26 (`ts→vol→offset→path→type→meta_addr`); value-level exact ordered sequence on a fixture with events that tie on ts AND vol/offset/path (differing only on event_type + meta_addr) | unit | `pytest tests/test_timeline.py::test_total_order -x` | ❌ Wave 0 |
| TIME-01 | End-to-end on `tiny_ext4_image`: known file's MACB times appear as events; deleted entry handled | integration | `pytest tests/test_timeline.py::test_ext4_timeline -x` | ❌ Wave 0 |
| REPORT-04 | JSON report contains COC, methodology+versions, findings(D-28), evidence hashes, FULL timeline | integration | `pytest tests/test_report.py::test_json_report -x` | ❌ Wave 0 |
| REPORT-03 | HTML renders; autoescape neutralizes a `<script>`-style filename (Security V5) | unit | `pytest tests/test_report.py::test_html_autoescape -x` | ❌ Wave 0 |
| REPORT-03 | HTML bounded view shows the truncation disclosure when events > cap (D-27, no overclaiming) | unit | `pytest tests/test_report.py::test_html_truncation_note -x` | ❌ Wave 0 |
| REPORT-03 | Findings = inventory stats + integrity PASS/FAIL + D-20 limitations; limitations section present (D-28) | integration | `pytest tests/test_report.py::test_findings_d28 -x` | ❌ Wave 0 |
| REPORT-03 | FAT `local-time-inferred` / `assumed_timezone` provenance survives into the report (no overclaiming) | integration | `pytest tests/test_report.py::test_fat_provenance -x` | ❌ Wave 0 |
| CLI-01 | `pyautopsy analyze <image> --case ...` exits 0 and writes `reports/report.html` + `reports/report.json` | integration (CliRunner) | `pytest tests/test_analyze.py::test_analyze_produces_reports -x` | ❌ Wave 0 |
| CLI-01 | `analyze` composes ingest+walk: COC rows, files, timeline_events, AND end-of-run re-verify all present | integration | `pytest tests/test_analyze.py::test_analyze_composes_pipeline -x` | ❌ Wave 0 |
| CLI-01 | `ingest`/`walk` still work standalone (no regression) | regression | `pytest tests/test_cli_smoke.py tests/test_ingest.py tests/test_walk.py -q` | ✅ exists |
| **CLI-02** | **Two `analyze` runs on the same fixture (separate case dirs) → BYTE-IDENTICAL `report.json` AND `report.html` (whole-file, both); `run_metadata.json` excluded from comparison and differs** | reproducibility | `pytest tests/test_reproducibility.py::test_two_analyze_runs_byte_identical_report -x` | ⚠️ extend existing file |
| CLI-02 | `tsk_version` + `pyautopsy_version` recorded in the report (versions pinned) | unit | `pytest tests/test_report.py::test_versions_recorded -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_timeline.py tests/test_report.py tests/test_analyze.py -x -q`
- **Per wave merge:** `python3 -m pytest -q` (full suite — includes the existing 16 test modules and the new ones)
- **Phase gate:** Full suite green + ruff + mypy clean before `/gsd-verify-work`; the CLI-02 byte-identical test is the gating reproducibility check.

### CLI-02 byte-identical test design (the critical one)
The existing `tests/test_reproducibility.py` already proves DB-field-level reproducibility with `_RUN_METADATA_COLUMNS` excluded. Extend it for the report bytes (run-metadata placement is LOCKED to sidecar-only — see Open Questions RESOLVED / W-1):
1. Run `analyze` on `tiny_ext4_image` into `case_a`, then again into `case_b` (separate dirs, like the existing `_ingest` helper but calling `analyze`).
2. Assert `(case_a/"reports"/"report.json").read_bytes() == (case_b/"reports"/"report.json").read_bytes()` — strict byte equality (this is the heart of CLI-02).
3. Assert `(case_a/"reports"/"report.html").read_bytes() == (case_b/"reports"/"report.html").read_bytes()` — strict whole-file byte equality (report.html carries ZERO run metadata, so no footer-stripping; W-1 lock). `reports/run_metadata.json` is EXCLUDED from the byte comparison.
4. Sanity-assert the body is non-empty and contains the known fixture file's timeline events (not an empty-dict false pass — mirror the existing test's `assert fields_a["evidence.sha256"]` sanity check).
5. Negative assert: the segregated `reports/run_metadata.json` generation timestamp IS present and DOES differ between runs (proving segregation is real, not accidental equality).

### Wave 0 Gaps
- [ ] `tests/test_timeline.py` — MACB explosion + D-26 total order + ext4 integration (TIME-01)
- [ ] `tests/test_report.py` — JSON/HTML content, autoescape, truncation note, D-28 findings, FAT provenance, versions recorded (REPORT-03/04)
- [ ] `tests/test_analyze.py` — `analyze` produces reports + composes pipeline + re-verify runs (CLI-01)
- [ ] Extend `tests/test_reproducibility.py` — add the two-run byte-identical report test (CLI-02)
- [ ] (optional) a fixture or in-test file with a `<script>`-bearing name for the autoescape test — can be synthesized in-test against a fake `FileRow`, no new committed image needed.
- Framework install: none — pytest already configured; Jinja2 already importable (add to `pyproject.toml` deps as part of the implementation task).

## Security Domain

> `security_enforcement` not present in config → treated as enabled. ASVS L1 for an offline forensic report generator.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local CLI, no auth surface. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no (file confinement covered under V5/V12) | — |
| V5 Validation / Encoding / Output | **yes** | Jinja2 autoescape ON for all evidence-derived strings (filenames, paths, file_type, limitation reasons, encryption hints). `json.dumps` for JSON. NEVER `| safe` on evidence values. Validate `--timezone` (already done in `cli/main.py`). |
| V6 Cryptography | no (integrity hashing already in Phase 1) | The report only *displays* the Phase-1 hashes; no new crypto. |
| V12 Files & Resources | **yes** | Report output confined to `case_dir/reports/` via the `audit/log.py` `_is_within` realpath check; paths built only from `case_dir` + fixed names, never from evidence content. Bound the HTML timeline (D-27) to prevent resource exhaustion on huge images. |

### Known Threat Patterns for {Jinja2 HTML + JSON report over evidence-controlled data}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| HTML/JS injection via attacker-controlled filename/path | Tampering / Elevation | Jinja2 autoescape ON; no `| safe`; test with `<script>`-bearing name. |
| Path traversal writing report files outside the case dir | Tampering | Build paths from `case_dir` + fixed names only; reuse `_is_within` confinement; create `reports/` like `logs/`. |
| Resource exhaustion (multi-million-event timeline) → OOM/hang | Denial of Service | Bounded HTML (D-27); render_html slices `body["timeline"][:cap]` in-process; cap HTML slice. |
| Overclaiming / dishonest output (soundness, not classic infosec) | Information Disclosure (misleading) | D-28 limitations section; D-27 truncation disclosure; preserve FAT/inferred-time provenance flags; record tool/TSK versions. |
| Non-reproducible output undermining defensibility | Repudiation | D-25/D-26 determinism: byte-identical report.json + report.html, run metadata in run_metadata.json sidecar only, total order, pinned versions (CLI-02 test). |
| No self-audit of the report step | Repudiation | `analyze` writes `analyze.start`/`analyze.end` (and any FAIL) audit events like `ingest`/`walk` (REPORT-02). |

## Sources

### Primary (HIGH confidence)
- Existing codebase (read this session): `case/store.py`, `case/models.py`, `case/schema.sql`, `core/ingest.py`, `core/walk.py`, `cli/main.py`, `util/timeutil.py`, `audit/log.py`, `tests/test_reproducibility.py`, `tests/conftest.py`, `tests/fixtures/` — the integration surface and the proven determinism/escaping/confinement patterns.
- `.planning/research/ARCHITECTURE.md` — blackboard/event-store pattern, `events` table shape, producer/reporter boundary, anti-patterns (HIGH).
- `.planning/research/PITFALLS.md` — P3 (reproducibility), P4 (UTC/MACB), P10 (overclaiming), security mistakes (HIGH).
- `.planning/research/STACK.md` — Jinja2/WeasyPrint/pydantic/Typer recommendations, native bodyfile/mactime vs plaso, version pinning (HIGH).
- Installed-runtime verification: `python3 -c "import jinja2; jinja2.__version__"` → 3.1.6; `json.dumps(sort_keys=True, ensure_ascii=False)` behavior; Jinja2 `Environment(autoescape=select_autoescape, trim_blocks, lstrip_blocks, keep_trailing_newline)` all import/construct cleanly (HIGH — verified in this env).

### Secondary (MEDIUM confidence)
- Context7 / ctx7 CLI documentation lookup was unavailable in this environment (MCP tool absent, `ctx7` not on PATH). Jinja2 API claims are therefore verified against the *installed* 3.1.6 runtime rather than fetched docs — equivalent or stronger for the specific API surface used (autoescape, whitespace control, importlib.resources loader).

### Tertiary (LOW confidence)
- None — no unverified web-only claims were relied on.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Jinja2 verified installed; everything else stdlib/already-in-project.
- Architecture/integration: HIGH — read every relevant source/test; the producer/reporter boundary and read API already exist.
- Determinism technique (CLI-02): HIGH — the exact primitives are already proven in `audit/log.py`, `case/store.py`, and `tests/test_reproducibility.py`.
- mactime semantics: HIGH on the explosion algorithm (matches D-24); collapsing is a display-only nuance, flagged.
- JSON schema shape / HTML cap / actor encoding: MEDIUM — Claude's discretion per CONTEXT.md; recommendations given, locked in the Assumptions Log.

**Research date:** 2026-05-31
**Valid until:** 2026-06-30 (stable — stdlib + Jinja2 3.1.x; no fast-moving deps).
