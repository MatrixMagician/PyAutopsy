# Phase 3: Timeline & MVP Report - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase **closes the end-to-end MVP vertical slice**: one command turns an
acquired disk image into (a) a UTC-ordered chronological timeline, (b) a
human-readable report, and (c) a structured machine-readable report — **and
proves the spine is reproducible** before more producers (recovery, logs,
search) are layered on. It is the first phase that *reads back* from the case
store rather than only writing into it. In scope (maps TIME-01, REPORT-03,
REPORT-04, CLI-01, CLI-02):

- **Chronological timeline (TIME-01)** built from the Phase 2 filesystem MACB
  metadata, bodyfile/mactime style, UTC-ordered with explicit offsets.
- **Human-readable report (REPORT-03)** containing case/COC, methodology +
  tool/TSK versions, findings, evidence hashes, timeline, and a limitations
  section — **no overclaiming**.
- **Structured JSON report (REPORT-04)** emitted alongside the human report.
- **Single-command pipeline (CLI-01)** — `pyautopsy analyze <image> --case ...`
  produces the complete report set.
- **Determinism / reproducibility (CLI-02)** — two runs on the same fixture
  produce byte-identical analytical report *bodies* (run metadata segregated),
  with TSK/tool versions pinned and recorded.

Out of scope (later phases): deleted-file **recovery** + confidence tiers +
NSRL/hash-set filtering (Phase 4); **log parsing**, the **super-timeline**
merge of filesystem + log events, and **search** (Phase 5). This phase builds
the *filesystem-only* timeline and the report shell that Phase 4/5 findings will
later flow into. PDF rendering is deferred.

</domain>

<decisions>
## Implementation Decisions

### `analyze` Command Shape (CLI-01)
- **D-21:** `pyautopsy analyze <image> --case ...` runs the **full pipeline in
  one process** — ingest → walk → build-timeline → render-report — creating a
  fresh case and producing the complete report set, directly satisfying
  success-criterion 4. The existing **`ingest` and `walk` subcommands REMAIN**
  as standalone commands for partial/advanced workflows (and to keep Phase 1/2
  UAT intact). `analyze` composes the existing `run_ingest` / `run_walk`
  orchestrators rather than duplicating their logic; the Phase 1 end-of-run
  source-hash **re-verify still runs** as part of the composed pipeline. The
  `analyze` argument/option surface mirrors `ingest` (image, `--case`,
  `--examiner`, `--evidence-id`, `--acquisition-hash`) plus the `walk` knobs
  (`--timezone`, `--max-hash-size`).

### Report Format & Rendering (REPORT-03 / REPORT-04)
- **D-22:** MVP human report is **HTML rendered via Jinja2**; the structured
  report is **JSON**. **WeasyPrint/PDF is deferred** to a later phase to avoid
  pulling in heavy native libs (pango/cairo/gdk-pixbuf) during the MVP. Jinja2
  is a **new pure-Python dependency** added this phase (no native seam — D-14
  unaffected). The HTML template is authored so a later PDF path can reuse it.

### Timeline Persistence Model (TIME-01, forward-compatible with Phase 5)
- **D-23:** **Persist a normalized timeline-event table now**, shaped as the
  **shared forensic-event model** (timestamp, source, type, actor, action,
  outcome, evidence-ref) that Phase 5 LOG-04 will reuse and TIME-02 will merge
  into a super-timeline. Filesystem MACB times are the first *producer* into
  this table. Phase 5 then only adds log producers + a merge step — **no schema
  churn, no backfill**. (This realizes the Phase 2 intent that the file-row
  shape "anticipate the timeline and super-timeline without pre-building them.")
- **D-24:** **Event granularity = one event per MACB timestamp** (classic
  bodyfile→mactime explosion). Each distinct M/A/C/B time becomes its own event
  row with `type` ∈ {modified, accessed, changed, born}; a file with 4 distinct
  times yields up to 4 events. Zero/None MACB values (Phase 2 "0 epoch ⇒ not
  recorded") produce **no event**. This matches the per-event super-timeline
  shape so Phase 5 merges cleanly.

### Determinism / Reproducibility (CLI-02)
- **D-25:** **Segregate run metadata from the analytical body.** The analytical
  body (timeline, inventory, findings, evidence hashes) is fully deterministic;
  **volatile run-metadata** (report generation timestamp, run durations, host,
  run-id) lives in a **distinct `run_metadata` block/section that is excluded
  from the byte-comparable body**. Two runs ⇒ byte-identical bodies; run
  metadata differs and is clearly marked as non-analytical.
- **D-26:** **Total, stable ordering** for the timeline:
  `timestamp → volume (id/offset) → path → event type (M/A/C/B) → meta_addr`.
  This guarantees byte-equality (D-25) and is human-sensible (a file's events
  group together at equal times). TSK/tool/pyautopsy versions are **pinned and
  recorded** in the report (sourced from the Phase 1 COC: `tsk_version`,
  `pyautopsy_version`).

### HTML Timeline Volume Handling
- **D-27:** Real images yield huge timelines, so the **HTML shows a bounded
  view** (capped rows / most-relevant slice) with an explicit, honest
  "truncated — full timeline in JSON" disclosure; the **complete unabridged
  timeline lives in the JSON** report. Keeps the human report usable without
  overclaiming or producing multi-hundred-MB HTML. (A CSV/bodyfile export of the
  full timeline is at the planner's discretion.)

### MVP Report "Findings" Content
- **D-28:** Because recovery/log analysis don't exist yet, the report's
  **findings** = **inventory summary stats** (file/dir counts, deleted-entry
  count, per-volume breakdown, file-type distribution) + the **integrity
  verification result** (acquisition compare + end-of-run re-verify PASS/FAIL) +
  the **D-20 encrypted/unsupported volume limitations**. The report is honest
  about what this MVP does and does not yet analyze (limitations section).

### Claude's Discretion
- Exact `timeline_events` table schema — typed core columns vs JSON
  `attributes` split — consistent with D-02 (typed core + JSON `attributes`).
  Suggested mapping for filesystem events: `source` = `filesystem`/fs-type,
  `type` = MACB kind, `evidence-ref` = path + meta_addr + volume id/offset,
  `actor` = uid/gid (where known); planner finalizes the field mapping.
- JSON report schema shape (keys, nesting, whether pydantic models back it).
  Pydantic is in the recommended stack — planner decides whether to introduce it
  here or defer.
- HTML template structure, CSS, and theming; whether a CSV/bodyfile timeline
  export ships this phase.
- Output file layout within the case directory (e.g. `reports/report.html`,
  `reports/report.json`, run-metadata sidecar vs embedded block) — consistent
  with Phase 1's case-dir confinement (audit log + exports already live there).
- Whether the timeline build is its own internal module/orchestrator or folded
  into the report step; whether a standalone `timeline`/`report` subcommand is
  exposed in addition to `analyze` (optional, planner's call).
- Bounded-HTML row cap default — pick a sane value, make it configurable if cheap.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project specs
- `.planning/PROJECT.md` — product definition, core value, forensic-soundness
  constraints (read-only, reproducible, Linux CLI, human-readable + structured
  report).
- `.planning/REQUIREMENTS.md` — Phase 3 maps **TIME-01, REPORT-03, REPORT-04,
  CLI-01, CLI-02** (timeline, human report, JSON report, single-command
  pipeline, determinism). Note **LOG-04/TIME-02** (Phase 5) define the shared
  forensic-event model + super-timeline this phase's D-23 table must anticipate.
- `.planning/ROADMAP.md` §"Phase 3: Timeline & MVP Report" — goal + 5 success
  criteria (the acceptance bar); **UI hint: yes**.

### Research (drives the decisions above)
- `.planning/research/STACK.md` — Jinja2 (HTML templating) + WeasyPrint
  (deferred PDF) + Rich + Typer + pydantic; `fls`+`mactime` bodyfile workflow as
  the dependency-light timeline; version pinning for reproducibility.
- `.planning/research/ARCHITECTURE.md` — case-store schema (typed columns + JSON
  `attributes`), normalized **forensic-event model** (the shape D-23 persists),
  read-only evidence handling.
- `.planning/research/PITFALLS.md` — P4 (UTC-everywhere, explicit offsets),
  defensibility / **no-overclaiming** (drives D-27 truncation honesty + D-28
  limitations), reproducibility/determinism guidance (drives D-25/D-26).
- `.planning/research/SUMMARY.md` — cross-cutting synthesis and phase ordering.

### Phase 1 + 2 foundation (the substrate this phase reads from)
- `.planning/phases/01-forensic-foundation/01-CONTEXT.md` — D-01..D-13 (case
  store, single seam, UTC-everywhere D-10, Typer CLI D-12, reproducibility seed).
- `.planning/phases/02-filesystem-walk-metadata/02-CONTEXT.md` — D-14..D-20
  (walk, MACB→UTC, file-row shape that feeds this timeline).
- `src/pyautopsy/case/store.py` — `CaseStore`: `get_files(evidence_source_id)`,
  `get_case`, `get_evidence_source`, `get_volume_limitations`,
  `insert_files`/bulk insert, `transaction()`. Phase 3 adds a `timeline_events`
  table + insert/query path here, and reads files/COC/limitations back for the
  report.
- `src/pyautopsy/case/models.py` — `Case`, `EvidenceSource` (COC + `md5`/`sha256`
  + `tsk_version` + `pyautopsy_version` for the report header), `FileRow` (MACB
  `*_utc` + `path`/`name`/`allocated`/`fs_type`/`volume_id`/hashes/`file_type` —
  the timeline + inventory source), `VolumeLimitation` (D-28 findings).
- `src/pyautopsy/core/ingest.py` — `run_ingest` + `IngestResult` (composed by
  `analyze`; carries acquisition-verify result for the integrity finding).
- `src/pyautopsy/core/walk.py` — `run_walk` + `WalkResult` (composed by
  `analyze`; counts feed inventory summary findings).
- `src/pyautopsy/cli/main.py` — Typer `app` with `ingest` + `walk`; Phase 3 adds
  the `analyze` command beside them (D-21), reusing the validation patterns
  (e.g. timezone validation) already present.
- `src/pyautopsy/util/timeutil.py` — UTC helper (D-10) for any timestamp
  formatting in the report/timeline.
- `src/pyautopsy/audit/log.py` — append-only JSONL audit log; `analyze` records
  its actions here too (REPORT-02 pattern), confined to the case dir.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`CaseStore` read API** (`case/store.py`): `get_files`, `get_case`,
  `get_evidence_source`, `get_volume_limitations` give the timeline + report
  everything they need to read back; `insert_files` bulk pattern is the template
  for a `timeline_events` insert path. `transaction()` keeps writes atomic.
- **`FileRow`** (`case/models.py`): already carries tz-aware UTC MACB strings
  (`mtime_utc`/`atime_utc`/`ctime_utc`/`crtime_utc`), path, allocation status,
  hashes, file type, volume tagging — the direct input to the timeline producer
  (D-24) and the inventory findings (D-28).
- **COC fields** on `Case`/`EvidenceSource`: `pyautopsy_version`, `tsk_version`,
  `md5`, `sha256`, acquisition metadata — populate the report header +
  methodology + evidence-hash sections (REPORT-03) and satisfy "versions pinned
  and recorded" (CLI-02 / D-26).
- **Typer CLI pattern** (`cli/main.py`): thin command shells over orchestrators
  with usage-error vs integrity-exit-code separation — `analyze` follows the
  same shape (D-21).

### Established Patterns
- **D-02 typed columns + JSON `attributes` blackboard** — the new
  `timeline_events` table follows it (D-23 discretion).
- **D-10 UTC-everywhere, tz-aware, no naive datetimes** — binding on all
  timeline/report timestamps; explicit offsets in output.
- **D-12 Typer surface** — `analyze` joins `ingest`/`walk`.
- **D-14 native-seam allowlist** — timeline + report are **pure Python**
  (Jinja2, stdlib); no new native imports, gate unaffected.
- **Case-dir confinement** (Phase 1) — all report outputs written only into the
  case directory, like the audit log + exports.
- **src layout, pytest with `tmp_path` fixtures, ruff + mypy, pinned deps
  (D-13)** — Phase 3 adds determinism tests (two runs → byte-identical bodies)
  and small golden fixtures.

### Integration Points
- Phase 3 is the first **consumer** of the Phase 2 `files` rows. The new
  `timeline_events` table is the integration surface **Phase 5** writes log
  producers into and merges for the super-timeline (TIME-02) — so its shape is
  a forward contract, not throwaway.
- The HTML/JSON report shell is where **Phase 4** (recovery/filtering findings)
  and **Phase 5** (log/search findings) will later add sections.

</code_context>

<specifics>
## Specific Ideas

- **Forensic honesty over completeness** (continued from Phase 2): the HTML
  report must disclose timeline truncation (D-27), the findings section must
  state what this MVP does NOT yet analyze (D-28), and FAT local-time /
  inferred values from Phase 2 must keep their flags through to the report.
- **Reproducibility is a first-class deliverable**, not a nice-to-have: the
  byte-identical-body guarantee (D-25/D-26) is itself a success criterion and
  should have a dedicated determinism test on a fixture image.
- The shared forensic-event model (D-23) is the **architectural keystone** for
  the back half of the roadmap — get its shape right so Phase 5 is additive.

</specifics>

<deferred>
## Deferred Ideas

- **WeasyPrint / PDF rendering** of the HTML report → later phase (kept out of
  MVP to avoid pango/cairo/gdk-pixbuf native deps); template authored to allow it.
- **Super-timeline** (merging filesystem + log events) and **log producers**
  into the shared event model → **Phase 5** (TIME-02, LOG-01..04).
- **Deleted-recovery findings, confidence tiers, NSRL/hash-set filtering**
  report sections → **Phase 4**.
- **Search** (keyword/regex/IOC) report integration → **Phase 5**.
- **CASE/UCO-conformant JSON export**, report diffing across runs, config-driven
  recipes → v2 (REQUIREMENTS.md v2: JSON-01, DIFF-01, CONF-01).
- **Timeline anomaly / timestomp surfacing** ($SI vs $FN, future/out-of-order
  times) → v2 (ANOM-01); Phase 3 only orders events, does not flag anomalies.
- Optional standalone `timeline`/`report`/CSV-bodyfile export subcommands —
  revisit if a fixture/UAT surfaces the need.

</deferred>

---

*Phase: 3-Timeline & MVP Report*
*Context gathered: 2026-05-31*
