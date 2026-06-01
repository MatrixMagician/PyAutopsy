# Milestones

## v1.0 MVP (Shipped: 2026-06-01)

**Delivered:** The full "disk image (+ logs) → defensible, presentation-ready forensic report" pipeline — read-only ingest, filesystem metadata, deleted-file recovery, known-file filtering, log parsing, a UTC super-timeline, and keyword/IOC search — driven by one reproducible `pyautopsy analyze` command on The Sleuth Kit (pytsk3).

**Stats:**
- 5 phases · 25 plans · 37 tasks · all complete (100%)
- 27/27 v1 requirements satisfied (milestone audit: 0 blockers; cross-phase integration 6/6 flows wired)
- ~11,550 LOC src + ~7,230 LOC tests (Python); 202 files, ~42k insertions
- 213 commits (39 `feat`) · 2026-05-30 → 2026-06-01 (3 days)
- Git range: `7244b62` (root) → milestone close

**Key accomplishments (by phase):**

1. **Phase 1 — Forensic Foundation:** the forensic-soundness spine — single-native-seam `evidence/image.py` (raw/dd + E01/EWF, read-only at the byte layer, never mounted), single-pass MD5+SHA-256 with acquisition-compare + end-of-run re-verify, a `CaseStore` SQLite repository (typed columns + JSON `attributes`, WAL, sole writer) for chain-of-custody, an append-only fsync-durable JSONL audit log, and a hardened `safe_extract` jail (Zip-Slip / symlink / decompression-bomb proof). (INGEST-01..04, REPORT-01/02)
2. **Phase 2 — Filesystem Walk & Metadata:** `pyautopsy walk` enumerates every volume and inventories every entry (incl. deleted) as normalized `files` rows with tz-aware UTC MACB times, ownership/mode, single-pass MD5+SHA-1+SHA-256, and content-signature file typing; encrypted/unsupported volumes recorded as honest limitation findings. (META-01..05)
3. **Phase 3 — Timeline & MVP Report:** the shared `timeline_events` model with a deterministic total order; `build_timeline` MACB explosion; and `pyautopsy analyze` producing byte-identical HTML (Jinja2, autoescaped, bounded) + structured JSON reports from one command with pinned tool/TSK versions and a no-overclaiming limitations section. (TIME-01, REPORT-03/04, CLI-01/02)
4. **Phase 4 — Deleted Recovery & Known-File Filtering:** metadata-intact recovery of deleted/orphaned files through the TSK seam with honest intact/partial-overwritten confidence tiers (orphans reported separately, no intent asserted), plus NSRL RDS + custom allow/block hash-set filtering surfaced as neutral "known" annotations — opt-in via `recover` / `analyze --recover/--nsrl/--hash-set-*`. (RECOV-01..03, FILTER-01)
5. **Phase 5 — Log Parsing, Super-Timeline & Search:** stdlib-only parsers for auth.log/secure, syslog/messages, and per-user shell history (rotated/gz reassembled, tz+year inferred-and-flagged, tamperability + completeness surfaced as neutral findings) normalized into the shared event model and merged into one UTC super-timeline; plus streaming literal/regex search across allocated + unallocated + file content with IOC/known-bad-hash matching reported by file+offset — all via `analyze --logs --search`, default `analyze` staying byte-identical. (LOG-01..04, TIME-02, SEARCH-01/02)

**Known tech debt at close** (accepted; full detail in `milestones/v1.0-MILESTONE-AUDIT.md`):
- Nyquist validation: phases 2–5 have draft VALIDATION.md (`nyquist_compliant: false`); only Phase 1 formally compliant.
- Phase 3 missing `test_analyze_refuses_existing_case` regression (guard implemented, untested); `durations={}` always empty.
- Phase 5 ~15 non-blocking carried warnings (RFC3164 hostless lines, dateext rotation ordering, low-signal boilerplate findings, framing/reachability nits).
- 1 documented manual-only check: real E01 ingest on a libewf-equipped host.

---
