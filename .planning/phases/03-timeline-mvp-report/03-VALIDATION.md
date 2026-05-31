---
phase: 3
slug: timeline-mvp-report
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-31
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Detailed per-criterion validation architecture lives in `03-RESEARCH.md` §"Validation Architecture";
> the planner populates the per-task map below from it.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (src layout, `pythonpath = "src"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `python -m pytest -q` |
| **Full suite command** | `python -m pytest && ruff check . && mypy src` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest -q`
- **After every plan wave:** Run `python -m pytest && ruff check . && mypy src`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| _populated by planner from 03-RESEARCH.md Validation Architecture_ | | | TIME-01 / REPORT-03 / REPORT-04 / CLI-01 / CLI-02 | | | unit/behavior | `python -m pytest -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_timeline.py` — MACB-explosion correctness (TIME-01), one event per non-null MACB, stable ordering
- [ ] `tests/test_report.py` — HTML autoescape + bounded-timeline note (REPORT-03), JSON schema/shape (REPORT-04)
- [ ] `tests/test_analyze.py` — single-command pipeline composition (CLI-01)
- [ ] extend `tests/test_reproducibility.py` — two `analyze` runs ⇒ byte-identical report bodies (CLI-02)
- [ ] shared fixtures: reuse Phase 1/2 fixture images with known files + a deleted entry

*Reference the concrete commands itemized in 03-RESEARCH.md as Wave 0 gaps.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| _planner to confirm none required_ | | | |

*Target: All phase behaviors have automated verification (criterion 5 byte-equality is automatable).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
