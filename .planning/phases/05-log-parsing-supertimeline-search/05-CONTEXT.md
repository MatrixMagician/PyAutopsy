---
gsd_context_version: 1.0
phase: 5
phase_name: Log Parsing, Super-Timeline & Search
phase_slug: log-parsing-supertimeline-search
depends_on: Phase 4
requirements: [LOG-01, LOG-02, LOG-03, LOG-04, TIME-02, SEARCH-01, SEARCH-02]
discuss_mode: discuss
created: 2026-05-31
---

# Phase 5 Context — Log Parsing, Super-Timeline & Search

## Goal (from ROADMAP)

An examiner sees filesystem and log evidence merged into one UTC-ordered
super-timeline and can search across allocated, unallocated, and file content —
completing the full "image + logs → defensible report" pipeline.

## Requirements in scope (verified against REQUIREMENTS.md)

| ID | Requirement |
|----|-------------|
| LOG-01 | Parse Linux **authentication** logs (`auth.log` / `secure`) from the evidence image — logins, SSH, sudo, failed-auth |
| LOG-02 | Parse **syslog / messages** — service, kernel, cron, error events |
| LOG-03 | Parse per-user **shell history** (`.bash_history` / `.zsh_history`), noting tamperability |
| LOG-04 | Normalize all parsed log events into the shared forensic-event model (timestamp, source, type, actor, action, outcome, evidence-ref) |
| TIME-02 | Build a super-timeline merging filesystem metadata + parsed log events into one UTC-sorted view |
| SEARCH-01 | Literal **and regex** keyword search across allocated content, **unallocated space**, and file content |
| SEARCH-02 | Match files/content against IOC lists + known-bad hash sets, reporting hits with **file and offset** |

ROADMAP Success Criteria add: rotated/compressed log sets reassembled;
year/timezone **inferred-and-flagged**; tamperability + log-completeness surfaced
as findings; log events identical in shape to filesystem events.

Cross-cutting NFRs gating this phase: SOUND-01 (read-only), SOUND-02 (tz-aware
UTC everywhere), REPRO-01 / CLI-02 (byte-identical report bodies), PERF-01
(stream, don't slurp), EXT-01 (plugin-style parsers).

## EXPLICITLY OUT OF SCOPE this phase (v2 — do NOT build)

- **journald (binary `*.journal`)**, auditd, wtmp/btmp/lastlog → **LOG-05 (v2)**.
  This means **no `python-systemd`, no `libsystemd`, no new native dependency,
  and no second native seam** this phase. The single-native-seam rule (D-06,
  only `evidence/image.py` imports native libs) stays intact.
- web/server + package-manager logs → LOG-06 (v2).
- full-text search **indexing** for fast keyword search → SEARCH-03 (v2). This
  phase does *streaming* (linear-scan) search, not an index.
- plaso backend (TIME-03), timestomp/anomaly surfacing (ANOM-*), YARA (RULE-01).

> **Correction note:** an earlier draft of this file wrongly treated journald as
> in-scope (LOG-02) and proposed a `python-systemd` seam. That was a misreading —
> LOG-02 is syslog/messages; journald is the v2 LOG-05 item. The decisions below
> are the corrected, requirement-accurate set.

## Existing foundation this phase builds on (recon-verified)

- **The event model is already Phase-5-shaped (D-23 realized).**
  `case/models.py::TimelineEvent` carries `ts_utc, source, event_type,
  volume_id, volume_offset, path, meta_addr, actor, action, outcome,
  attributes`. The schema (`case/schema.sql`) gives `timeline_events` a
  **nullable `file_id`** ("log events, Phase 5") and reserves `action`/`outcome`
  explicitly for log producers. **No schema churn needed.**
- **The merge (LOG-04 / TIME-02) is largely free.** `CaseStore` is the sole
  writer; `insert_timeline_events` (store.py:584) bulk-inserts, and
  `get_timeline_events` returns the **deterministic total order**
  `ts_utc, volume_id, volume_offset, path, event_type, meta_addr, source,
  actor, id` — the trailing surrogate `id` is the guaranteed-unique tiebreak
  (CR-01 fix). Log events carry NULL/`0` volume fields and NULL `meta_addr`, so
  `source`/`actor`/`id` are what keep them in stable order — exactly the
  NULL-key tie trap CR-01 already covers.
- **Timeline producer pattern**: `timeline/builder.py` = `_explode(file_row)` →
  `build_timeline(store, evidence_source_id)`. Log producers mirror this: parse
  → emit `TimelineEvent` rows → `insert_timeline_events`.
- **Reusable for SEARCH-02 (hash side)**: `filter/nsrl.py`, `filter/hashsets.py`,
  `case/models.py::KnownMatch`, `store.insert_known_matches` — the Phase-4
  known-file infra already matches MD5/SHA-1/SHA-256 against supplied sets.
- **CLI + opt-in precedent (D-40)**: `cli/main.py` has `ingest|walk|recover|
  analyze`; `recover`/`analyze` run extra passes only when `--nsrl`/`--hash-set-*`
  are supplied (`core/analyze.py::run_analyze`, `AnalyzeResult`), keeping default
  `analyze` Phase-3 byte-stable.
- **Seam for reading bytes**: `evidence/image.py` (image/volume) +
  `evidence/filesystem.py` (FS walk + file content) are the read-only seam used
  to fetch log-file bytes, allocated content, and unallocated blocks.
- **Deps today**: pytsk3, python-magic, typer, rich, jinja2; extras `ewf`, `dev`.
  **This phase adds NO new runtime dependency** (all text parsing + streaming
  search is stdlib: `re`, `gzip`, `datetime`/`zoneinfo`).
- **No `log/` or `search/` package exists yet.**

## Decisions made in discussion

- **D-43 — journald DEFERRED to v2 (it is LOG-05, not LOG-02).** No
  `python-systemd`, no new native dependency, no second native seam. The
  single-native-seam discipline (D-06) is preserved unchanged. *(User choice:
  "Defer journald to v2".)*

- **D-44 — three text-log parsers in scope:** auth.log/secure (LOG-01),
  syslog/messages (LOG-02), per-user shell history (LOG-03). All are plain text /
  gzip-rotated — parsed with stdlib only. Shell-history tamperability and overall
  log completeness are surfaced as **findings** (Success Criterion 2), never as
  asserted intent (honesty — RECOV-03 / WR-02 lesson).

- **D-45 — logs sourced FROM THE DISK IMAGE via the existing seam.** Discover
  `/var/log/auth.log*`, `/var/log/secure*`, `/var/log/syslog*`,
  `/var/log/messages*`, and per-user `~/.bash_history` / `~/.zsh_history` during
  the filesystem walk; read bytes through `evidence/filesystem.py`; reassemble
  rotated/compressed (`.1`, `.gz`) sets in order. Everything stays
  chain-of-custody traceable. *(User choice: "From the disk image (seam)".)*
  Examiner-supplied external `--log` files are **deferred** (requirements say
  "from the evidence image").

- **D-46 — syslog/auth.log RFC3164 timestamp → UTC: infer from image, flag
  honestly.** RFC3164 lines have no year and no tz. Resolve by: (1) deriving host
  tz from the image (`/etc/localtime` → `/etc/timezone` fallback); (2) inferring
  the year from the log file's mtime / surrounding context (handle rotation +
  year-boundary spans); (3) recording `timestamp_source` + the inferred
  assumption per event and **flagging** it; (4) falling back to
  UTC-with-explicit-warning when tz is undeterminable. Mirrors D-16/FAT, directly
  avoids repeating the Phase-2 CR-01 silent-offset bug, and satisfies Success
  Criterion 1 ("year/timezone inferred-and-flagged"). RFC5424 lines (ISO-8601
  with offset) are parsed directly. *(User choice: "Infer from image, flag
  honestly".)*

- **D-47 — log events write into the SHARED `timeline_events` table; merge is
  the existing read.** Normalize (LOG-04) to `TimelineEvent` with
  `source` = `auth`/`syslog`/`shell-history`, `actor` = user/uid where known,
  `action`/`outcome` populated (e.g. login/success, sudo/denied), `file_id` →
  the source log file's row, NULL volume/meta fields. The super-timeline
  (TIME-02) **is** `get_timeline_events`' total-order read — no new ordering
  code. Introduce a small `LogParser` protocol/registry (EXT-01) so the three
  parsers register uniformly and future formats add without touching the
  orchestrator. **CaseStore stays the sole writer** (reuse
  `insert_timeline_events`).

- **D-48 — CLI opt-in (extends D-40) + standalone subcommands.** `analyze
  --logs` / `analyze --search <term>` stay opt-in so default `analyze` remains
  Phase-3 byte-stable; add standalone `pyautopsy logs` and `pyautopsy search`
  subcommands. Report surfaces the super-timeline (already merged in the read) +
  a log-summary/findings section + search-results section, keeping the report
  **body** byte-stable.

- **D-49 — search = FULL SEARCH-01/02, streaming (no index).** Implement a
  *streaming* (linear-scan) literal **and regex** search over **allocated file
  content + unallocated space + metadata**, plus IOC-list + known-bad-hash
  matching (reusing the Phase-4 `filter/*` + `KnownMatch` infra). Hits are
  reported with **file and offset** (SEARCH-02). No full-text index — that is
  SEARCH-03 (v2). Reads go through the seam, read-only; PERF-01-conscious
  streaming (never slurp whole volumes). *(User choice: "Full SEARCH-01/02
  (streaming)".)*

## Architecture sketch (for researcher / planner)

New packages / files (following existing one-concern conventions):

- `log/` — `registry.py` (LogParser protocol + registry, EXT-01),
  `auth.py` (LOG-01), `syslog.py` (LOG-02), `shell_history.py` (LOG-03),
  `discover.py` (locate + order rotated log sets in the image),
  `timeresolve.py` (D-46 tz/year inference + flagging),
  `normalize.py` (→ `TimelineEvent`).
- `search/` — `content.py` (streaming literal+regex over allocated +
  unallocated + file content, SEARCH-01), `ioc.py` (IOC + known-bad-hash
  matching reusing `filter/*`, SEARCH-02), reporting hits by file+offset.
- `core/` — `logs.py` (`run_logs`: discover → parse → resolve-time → normalize →
  `insert_timeline_events`); `search.py` (`run_search`). Wire opt-in flags into
  `core/analyze.py::run_analyze` (D-48).
- `case/store.py` — **reuse** `insert_timeline_events`; add a narrow search-hit
  recorder + (optional) a log-source provenance recorder if needed. CaseStore
  stays sole writer; no `timeline_events` schema change.
- `cli/main.py` — `logs`, `search` subcommands + `analyze --logs/--search`.
- `report/` — super-timeline already merged; add log-findings + search-results
  sections; report **body** stays byte-stable (CLI-02).

## Resolved questions (closed during Phase 5 execution — see 05-VERIFICATION.md)

All discussion questions below were answered by the shipped implementation and
confirmed by phase verification (16/16 truths, status `passed`, 2026-06-01).
Recorded here as a closed log; none remain open at milestone close.

1. **syslog format detection + year inference — RESOLVED.** `log/timeresolve.py`
   derives host tz (`/etc/localtime` → `/etc/timezone` fallback) and infers year
   from log mtime + rotation order; `infer_years` compares `(month, day)` tuples
   with a cascade guard so a lone out-of-order line is absorbed (CR-03 fix), and
   handles Dec→Jan rollover. RFC5424 (ISO-8601+offset) lines parse directly. Each
   event carries `timestamp_source` / `assumed_timezone` / `year_basis` /
   `time_warning` flags (D-46). Verified base truth 3 + G-1 fixture/sidecar
   reconciliation.
2. **auth.log event taxonomy — RESOLVED.** `log/auth.py`: Accepted → ssh-login,
   Failed password → failure, sudo granted/denied, session opened/closed —
   neutral observed-fact framing, never inferred intent (D-44). Verified truth 1.
3. **Unallocated-space read for SEARCH-01 — RESOLVED.** `evidence/filesystem.py::
   iter_unallocated_blocks` seam; `search/content.py` streams allocated +
   unallocated + file content with overlap logic for regex-across-chunk-boundary;
   hits reported with absolute file + offset. Verified truths 9/10/12.
4. **Determinism (CLI-02) — RESOLVED.** Store-owned total order with the surrogate
   `id` tiebreak; tied-log-event regression tests (`test_tied_log_events_stable`,
   `test_tied_log_events_null_meta_tiebreak`) pass. Verified truth 14.
5. **Rotated/compressed reassembly — RESOLVED.** `discover.order_rotated_set`
   (`order_key (-index, gz)`) + `decode_member` gzip inflate; the D-45
   log-completeness finding is surfaced in the report (G-2 closure). The dateext
   negative-index ordering nit (WR-06) is carried as a non-blocking warning
   (numeric rotation is correct). Verified truths 2/5/15.

## Risks / watch-items (carried lessons)

- **UTC honesty (SOUND-02):** never store an inferred syslog time without a flag
  (Phase-2 CR-01 FAT lesson).
- **Determinism (CLI-02):** log events have NULL fs keys → rely on the
  `source`/`actor`/`id` tiebreak; add a tied-event regression test.
- **Read-only (SOUND-01):** all log + content + unallocated reads go through the
  seam; source image never written; Phase 1 end-of-run re-verify still runs.
- **Overclaiming (CON-03 / RECOV-03):** auth-log and shell-history labels
  describe observed log content + tamperability, never attacker intent.
- **PERF-01:** content/unallocated search must stream; never load whole volumes.
- **No new native dep:** scope is stdlib-only text parsing + streaming search.
