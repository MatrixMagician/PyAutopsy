# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — MVP

**Shipped:** 2026-06-01
**Phases:** 5 | **Plans:** 25 | **Tasks:** 37 | **Span:** 3 days (2026-05-30 → 2026-06-01)

### What Was Built
- The full "disk image (+ logs) → defensible forensic report" pipeline on The Sleuth Kit (pytsk3), driven by one reproducible `pyautopsy analyze` command.
- Forensic-soundness spine first: read-only never-mounted ingest, single-pass MD5+SHA-256 with acquisition-compare + end-of-run re-verify, SQLite `CaseStore` (sole writer), append-only JSONL audit log, hardened `safe_extract` jail.
- Filesystem walk (ext4/NTFS/FAT) → normalized inventory with tz-aware UTC MACB, ownership/mode, per-file MD5+SHA-1+SHA-256, content-signature typing.
- Deterministic HTML + JSON reporting with a shared `timeline_events` total order; deleted/orphan recovery with honest confidence tiers; NSRL + custom hash-set filtering.
- Linux log parsing (auth/syslog/shell-history) into the shared event model, a UTC super-timeline, and streaming literal/regex + IOC/known-bad-hash search — all stdlib-only, zero new runtime deps.

### What Worked
- **MVP vertical slices + Wave-0 RED scaffolding per phase.** Each phase opened with committed deterministic fixtures and failing tests pinning the requirements, so "done" was always test-observable. Phase 3 closed the end-to-end MVP early (image → report) before layering headline capabilities — the spine was proven before more producers were added.
- **Architectural invariants enforced by executable gates, not convention.** The single-native-seam allowlist test (D-14), CaseStore-sole-writer, and byte-identical-report (CLI-02) checks caught regressions mechanically across all 5 phases.
- **Deep code review caught masked Criticals.** Green suites still hid real defects (Phase 5 CR-01/02/03 on the orchestrated path; Phase 4 RECOV-02 root-deletion misclassification) that adversarial review + re-verification surfaced and pinned.
- **Honesty-over-verdicts framing held end-to-end** — confidence tiers, neutral "known" annotations, tamperability/completeness as observed-fact findings; verified free of accusatory/intent vocabulary.

### What Was Inefficient
- **Human-UAT gaps surfaced late, forcing post-verification gap-closure phases** (Phase 4 plan 04-04; Phase 5 plans 05-05/05-06) after phases were already marked `passed`. Tamperability/completeness findings were *computed but not threaded to the report* — an integration miss a wiring check could have caught earlier.
- **Fixture/ground-truth drift.** The Phase 5 fixture's frozen-clock mtime anchor (2023) disagreed with the documented sidecar year (2026) — reconciled in 05-06, but a fixture-vs-sidecar consistency check up front would have avoided it.
- **A GSD process incident** (a `mode:fix` doc-writer using Write to truncate an uncommitted generated doc) cost a recovery cycle — generated-but-uncommitted artifacts had no fallback.
- **Nyquist validation never formally closed** for phases 2–5 (left `draft`), creating a partial-coverage tail at milestone audit.

### Patterns Established
- Phase shape: Wave-0 RED fixtures/tests → vertical slices in dependency waves → deep code review → goal-backward verification → human UAT → (if needed) `--gaps-only` closure plans.
- Additive schema for new findings (`volume_limitations`, `known_file_matches`, `log_findings`, `search_hits`) inserted in the existing single `store.transaction()` — never mutating the shared `timeline_events` shape.
- New producers mirror the timeline-builder pattern: parse → emit normalized rows → `insert_*` via the store; the super-timeline is just the existing total-order read (no new ordering code).
- Opt-in CLI flags (`--recover/--nsrl/--logs/--search`) keep default `analyze` byte-identical to the prior baseline, preserving CLI-02 as scope grows.

### Key Lessons
1. **A passing test suite is necessary but not sufficient** — adversarial review on the *orchestrated path* (not just unit tests) is where masked Criticals die. Schedule it every phase.
2. **"Computed" ≠ "surfaced."** Findings must be traced all the way into the rendered report; add an integration/wiring check that asserts each finding reaches report.json/html.
3. **Pin fixture ground-truth to what the fixture actually yields** (mtime anchors, inferred years) with a guard test, and reconcile sidecars at creation time — not at UAT.
4. **Generated-but-uncommitted artifacts have no recovery copy** — snapshot or `git add -N` before any agent edit loop; fix-mode must be surgical Edit, never whole-file Write.
5. **Close Nyquist validation in-phase** rather than letting `draft` VALIDATION.md accumulate into a milestone-audit tail.

### Cost Observations
- Model mix: not instrumented this milestone (quality profile / Opus-led planning + review).
- Sessions: multi-session across 3 days; high autonomy between explicit approval gates.
- Notable: zero new runtime dependencies added in Phase 5 (stdlib-only log parsing + streaming search) kept the install surface flat while doubling capability.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 MVP | 5 | 25 | Baseline GSD pipeline established: Wave-0 RED → waves → deep review → verify → UAT → gap-closure |

### Cumulative Quality

| Milestone | Tests | Requirements | Zero-Dep Additions |
|-----------|-------|--------------|--------------------|
| v1.0 MVP | 220 passing | 27/27 satisfied | Phase 5 (log parsing + search, stdlib-only) |

### Top Lessons (Verified Across Milestones)

1. *(Established v1.0)* Deep review on the orchestrated path catches what green unit suites mask — carry forward and confirm in v2.
2. *(Established v1.0)* Trace findings end-to-end into the rendered report; "computed" is not "surfaced."
