# Phase 3: Timeline & MVP Report - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-31
**Phase:** 3-Timeline & MVP Report
**Areas discussed:** analyze command shape, Report format & rendering, Timeline persistence model, Determinism strategy

---

## `analyze` Command Shape (CLI-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Full pipeline, keep subcommands | analyze runs ingest→walk→timeline→report end-to-end on a fresh case; ingest/walk remain standalone | ✓ |
| Compose over existing case | analyze requires a prior ingest+walk; only adds timeline+report | |
| Full pipeline, retire ingest/walk | Only analyze exists; ingest/walk folded in and removed | |

**User's choice:** Full pipeline, keep subcommands
**Notes:** Directly satisfies success-criterion 4 (single command) while preserving the granular commands and Phase 1/2 UAT. analyze composes existing run_ingest/run_walk; Phase 1 end-of-run re-verify still runs. → D-21

---

## Report Format & Rendering (REPORT-03 / REPORT-04)

| Option | Description | Selected |
|--------|-------------|----------|
| HTML + JSON, PDF deferred | Jinja2 HTML + structured JSON; WeasyPrint/PDF deferred to avoid pango/cairo/gdk-pixbuf native deps | ✓ |
| HTML + PDF + JSON | Add WeasyPrint now | |
| Markdown + JSON | Markdown human report, no Jinja2/HTML | |
| HTML + Markdown + JSON | Both human formats + JSON | |

**User's choice:** HTML + JSON, PDF deferred
**Notes:** Jinja2 is a new pure-Python dep (no native seam). Template authored so a later PDF path can reuse it. → D-22

---

## Timeline Persistence Model (TIME-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Persist normalized event table now | Add timeline_events table shaped as the shared forensic-event model; Phase 5 adds log producers + merge with no schema churn | ✓ |
| Derive on-the-fly from files rows | No new table; timeline computed at report time | |
| You decide | Planner chooses | |

**User's choice:** Persist normalized event table now
**Notes:** Realizes the Phase 2 intent that the file-row shape anticipate the super-timeline. → D-23

### Event Granularity (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| One event per MACB timestamp | bodyfile→mactime explosion; each distinct M/A/C/B time = its own event (type modified/accessed/changed/born) | ✓ |
| One row per file, MACB as flags | Single row per file with combined MACB flags | |
| You decide | Planner chooses | |

**User's choice:** One event per MACB timestamp
**Notes:** Matches the per-event super-timeline shape so Phase 5 merges cleanly. Zero/None MACB ⇒ no event. → D-24

---

## Determinism / Reproducibility (CLI-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Segregate run metadata + stable sort | Deterministic analytical body; volatile run-metadata in a distinct block excluded from the comparable body | ✓ |
| Separate run-metadata sidecar file | Body files contain zero volatile data; run.json sidecar holds timestamps | |
| You decide | Planner chooses | |

**User's choice:** Segregate run metadata + stable sort
**Notes:** → D-25

### Stable Sort Tiebreaker (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| ts → volume → path → event type | Then meta_addr as final tiebreaker; deterministic + human-sensible | ✓ |
| ts → meta_addr → event type | Deterministic, cheaper, less readable | |
| You decide | Planner chooses | |

**User's choice:** ts → volume → path → event type
**Notes:** → D-26. TSK/tool/pyautopsy versions pinned + recorded from Phase 1 COC.

---

## HTML Timeline Volume Handling (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Bounded HTML view, full data in JSON | HTML shows capped slice with honest "truncated — full in JSON" note; complete timeline in JSON | ✓ |
| Full timeline embedded in HTML | Every event in HTML | |
| You decide | Planner chooses | |

**User's choice:** Bounded HTML view, full data in JSON
**Notes:** → D-27. Avoids multi-hundred-MB HTML on real evidence; no overclaiming.

---

## MVP Report Findings Content (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Inventory + integrity + limitations summary | Inventory stats + acquisition/re-verify PASS/FAIL + D-20 volume limitations | ✓ |
| Minimal: counts + limitations only | Just totals + volume-limitation findings | |
| You decide | Planner chooses | |

**User's choice:** Inventory + integrity + limitations summary
**Notes:** → D-28. Report honest about what the MVP does not yet analyze.

---

## Claude's Discretion

- Exact `timeline_events` table schema (typed columns vs JSON attributes) + the filesystem-event field mapping.
- JSON report schema shape; whether pydantic backs it this phase.
- HTML template structure/CSS/theming; whether a CSV/bodyfile export ships.
- Output file layout in the case directory (run-metadata sidecar vs embedded block).
- Whether timeline build is its own module vs folded into report; optional standalone timeline/report subcommands.
- Bounded-HTML row-cap default value.

## Deferred Ideas

- WeasyPrint/PDF rendering → later phase.
- Super-timeline + log producers → Phase 5 (TIME-02, LOG-01..04).
- Deleted-recovery / confidence tiers / NSRL filtering report sections → Phase 4.
- Search integration → Phase 5.
- CASE/UCO JSON export, report diffing, config recipes → v2 (JSON-01, DIFF-01, CONF-01).
- Timeline anomaly / timestomp surfacing → v2 (ANOM-01).
