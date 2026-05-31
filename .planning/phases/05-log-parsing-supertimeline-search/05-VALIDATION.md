---
phase: 05
slug: log-parsing-supertimeline-search
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-31
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (config in pyproject.toml `[tool.pytest.ini_options]`, `pythonpath = ["src"]`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `python -m pytest tests/test_logs.py tests/test_search.py -x -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~12 seconds (full suite is ~10s today + new log/search tests) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command for the affected module
- **After every plan wave:** Run the full suite
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

> Expanded by the planner per PLAN.md task. Every behavior-adding task must map to an
> `<automated>` pytest command or a Wave-0 fixture dependency.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-00-01 | 00 | 0 | LOG-01/02/03, SEARCH-01/02 | — | Read-only fixture build (no source mutation) | fixture | `python tests/fixtures/make_fixtures.py` | ❌ W0 | ⬜ pending |
| 05-XX-XX | XX | N | REQ-XX | T-05-XX / — | (expected secure behavior or N/A) | unit | `python -m pytest tests/test_logs.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Per RESEARCH.md Validation Architecture, Wave 0 must build committed, deterministic
log-bearing and search fixtures (read-only; no mkfs/mutation at test time):

- [ ] `tests/fixtures/make_fixtures.py` — extend to plant: rotated/gz `auth.log` set, `syslog`/`messages`, per-user `.bash_history`/`.zsh_history`, `/etc/localtime` symlink + `/etc/timezone`, and planted-string content in allocated + unallocated space + an IOC/known-bad-hash target
- [ ] `tests/test_logs.py` — stubs for LOG-01, LOG-02, LOG-03, LOG-04 (parser + normalization)
- [ ] `tests/test_search.py` — stubs for SEARCH-01 (literal/regex over allocated/unallocated/content) + SEARCH-02 (IOC/known-bad-hash file+offset)
- [ ] `tests/test_supertimeline.py` (or extend `tests/test_timeline.py`) — TIME-02 merged-order stub
- [ ] `tests/test_no_new_deps.py` — guard that Phase 5 adds no new runtime dependency (D-43)
- [ ] `tests/conftest.py` — shared fixtures for the above

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real-world rotated-log year/tz inference on a live multi-year image | LOG-01/LOG-02, D-46 | Synthetic fixtures cannot fully exercise year-boundary + DST ambiguity on real captures | Run `pyautopsy logs` on a real Linux image spanning a year boundary; confirm `timestamp_source` flags + UTC fallback warnings |
| Super-timeline visual review across merged fs+log events at scale | TIME-02 | Ordering correctness across thousands of mixed events is a human-judgment review | Render report on a real image; eyeball UTC ordering + CR-01 tiebreaks |

*Refine during Wave 0; if a behavior gains automated coverage, move it out of this table.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
