# Phase 5: Log Parsing, Super-Timeline & Search - Research

**Researched:** 2026-05-31
**Domain:** Linux log forensics (text parsing) · super-timeline merge · streaming content/unallocated search
**Confidence:** HIGH (this phase is overwhelmingly an extension of already-built, in-repo patterns; the one genuine unknown — reading unallocated space via the seam — is resolved below with a verified workaround)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-43 — journald DEFERRED to v2 (it is LOG-05, not LOG-02).** No `python-systemd`, no new native dependency, no second native seam. The single-native-seam discipline (D-06) is preserved unchanged.
- **D-44 — three text-log parsers in scope:** auth.log/secure (LOG-01), syslog/messages (LOG-02), per-user shell history (LOG-03). All plain text / gzip-rotated, parsed with stdlib only. Shell-history tamperability and overall log completeness are surfaced as **findings**, never as asserted intent.
- **D-45 — logs sourced FROM THE DISK IMAGE via the existing seam.** Discover `/var/log/auth.log*`, `/var/log/secure*`, `/var/log/syslog*`, `/var/log/messages*`, and per-user `~/.bash_history` / `~/.zsh_history` during the filesystem walk; read bytes through `evidence/filesystem.py`; reassemble rotated/compressed (`.1`, `.gz`) sets in order. Examiner-supplied external `--log` files are **deferred**.
- **D-46 — syslog/auth.log RFC3164 timestamp → UTC: infer from image, flag honestly.** (1) derive host tz from the image (`/etc/localtime` → `/etc/timezone` fallback); (2) infer the year from the log file's mtime / context (handle rotation + year-boundary spans); (3) record `timestamp_source` + the inferred assumption per event and **flag** it; (4) fall back to UTC-with-explicit-warning when tz is undeterminable. RFC5424 lines (ISO-8601 with offset) are parsed directly.
- **D-47 — log events write into the SHARED `timeline_events` table; merge is the existing read.** Normalize (LOG-04) to `TimelineEvent` with `source` = `auth`/`syslog`/`shell-history`, `actor` = user/uid where known, `action`/`outcome` populated, `file_id` → the source log file's row, NULL volume/meta fields. The super-timeline (TIME-02) **is** `get_timeline_events`' total-order read. Introduce a small `LogParser` protocol/registry (EXT-01). **CaseStore stays the sole writer** (reuse `insert_timeline_events`).
- **D-48 — CLI opt-in (extends D-40) + standalone subcommands.** `analyze --logs` / `analyze --search <term>` stay opt-in so default `analyze` remains Phase-3 byte-stable; add standalone `pyautopsy logs` and `pyautopsy search` subcommands. Report **body** stays byte-stable.
- **D-49 — search = FULL SEARCH-01/02, streaming (no index).** literal **and** regex over **allocated file content + unallocated space + metadata**, plus IOC-list + known-bad-hash matching (reusing the Phase-4 `filter/*` + `KnownMatch` infra). Hits reported with **file and offset**. No full-text index (SEARCH-03/v2). Reads go through the seam, read-only; PERF-01 streaming.

### Claude's Discretion

- Internal package/module layout (the `log/` and `search/` file split sketched in CONTEXT.md is a starting point, not locked).
- The exact `LogParser` protocol signature and registry shape (must follow the EXT-01 / existing-producer convention).
- auth.log event taxonomy → `action`/`outcome` vocabulary (kept honest — describes the observed log line, never inferred intent).
- The chunk size and regex-across-chunk-boundary overlap strategy for streaming search.

### Deferred Ideas (OUT OF SCOPE)

- **journald (binary `*.journal`)**, auditd, wtmp/btmp/lastlog → **LOG-05 (v2)**. NO `python-systemd`, NO `libsystemd`, NO new native dependency, NO second native seam.
- web/server + package-manager logs → LOG-06 (v2).
- full-text search **indexing** → SEARCH-03 (v2). This phase does *streaming* (linear-scan) search.
- plaso backend (TIME-03), timestomp/anomaly surfacing (ANOM-*), YARA (RULE-01).
- Examiner-supplied external `--log` files (requirements say "from the evidence image").
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LOG-01 | Parse Linux **authentication** logs (`auth.log`/`secure`) — logins, SSH, sudo, failed-auth | RFC3164 grammar (§Pattern 2) + auth taxonomy (§Pattern 4) + normalize → `TimelineEvent` (§Pattern 6). stdlib `re` only. |
| LOG-02 | Parse **syslog/messages** — service, kernel, cron, error events | Same RFC3164 line grammar; program/PID extraction + level/facility heuristics. stdlib `re` only. |
| LOG-03 | Parse per-user **shell history** (`.bash_history`/`.zsh_history`), noting tamperability | Format detection (zsh `: <ts>:<dur>;cmd` extended-history vs bare bash lines) + explicit "no reliable per-line timestamp" finding (§Pitfall 2). |
| LOG-04 | Normalize all parsed events into the shared forensic-event model | The model **already exists** — `TimelineEvent` carries `ts_utc/source/event_type/actor/action/outcome/file_id/attributes`; schema reserves nullable `file_id` + `action`/`outcome` for log producers. No schema churn (§Architectural Responsibility Map, §Pattern 6). |
| TIME-02 | Super-timeline merging filesystem + log events, UTC-sorted | TIME-02 **is** `store.get_timeline_events(source_id)` — log events written into the same table sort in the same D-26 total order. Zero new ordering code (§Pattern 5). |
| SEARCH-01 | Literal **and** regex search across allocated content, **unallocated space**, file content | Allocated/file content via per-inode `read_random` (existing seam); **unallocated** via allocated-block-set derivation (`allocated_data_blocks`, exists) + raw byte reads through the byte seam `ImageHandle.read` (§Pattern 3, §Don't Hand-Roll). |
| SEARCH-02 | Match files/content against IOC lists + known-bad hash sets, hits by file+offset | Reuse `filter/hashsets.py` (`parse_hash_set`/`custom_match`) + `filter/nsrl.py` + `KnownMatch`; add literal/regex IOC term list. Hit = `(file/region, offset)` (§Pattern 4, §Don't Hand-Roll). |
</phase_requirements>

## Summary

Phase 5 is, to an unusual degree, an **extension exercise over already-built infrastructure** rather than a greenfield build. Every load-bearing piece the phase needs already exists in the repo and was designed (Phase 3, D-23/D-24/D-26) explicitly to be the Phase-5 spine: the `timeline_events` table already has a nullable `file_id` ("log events, Phase 5") and reserved `action`/`outcome` columns; `TimelineEvent` already carries the full LOG-04 forensic-event shape; `CaseStore.insert_timeline_events` + `get_timeline_events` already give a deterministic total order whose tiebreak chain (`…source, actor, id`) was written to handle exactly the NULL-volume/NULL-meta log events this phase produces (the CR-01 fix). TIME-02 is therefore not new code — it is the existing `get_timeline_events` read. LOG-04 is not a new model — it is the existing `TimelineEvent`. The orchestrator, audit, opt-in-CLI, and report-body-determinism patterns are all stamped out four times already (ingest/walk/recover/filter) and Phase 5 follows them verbatim.

The three log parsers (LOG-01/02/03) are pure stdlib text processing: RFC3164 line grammar via `re`, gzip rotation reassembly via `gzip`, tz/year inference via `zoneinfo`/`datetime`. **No new runtime dependency is added** (D-43) and **no native binding is touched outside the existing seam** (D-06). The single genuinely novel technical problem is SEARCH-01's "unallocated space": pytsk3 exposes **no** block-flag / unallocated-enumeration / `block_walk` API (verified — this is a known pytsk3 limitation, and the repo's own `allocated_data_blocks` docstring already states it). The resolved approach reuses the existing `allocated_data_blocks(fs)` derivation (walk allocated inodes' runs) to know which blocks are allocated, then streams **raw bytes via the byte seam** (`ImageHandle.read(offset, size)` + `fs.info.block_size`), treating any block NOT in the allocated set as unallocated — chunked, never slurped (PERF-01).

**Primary recommendation:** Build `log/` (registry + 3 parsers + discover + timeresolve + normalize) and `search/` (streaming literal/regex + IOC/hash) as new upper-tier packages that import **no** native bindings; route all byte access through the two existing seams (`evidence/filesystem.py` for per-file/per-inode/allocated-block reads, `evidence/image.py` for raw unallocated reads); write every event/hit through `CaseStore` (sole writer); make `logs`/`search` opt-in and standalone exactly like `recover`/`analyze --recover`; and keep the report **body** byte-stable by segregating any wall-clock and ordering all reads through store-owned total orders.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Discover rotated/gz log sets in image | FS seam (`evidence/filesystem.py`) — `walk_fs` already enumerates every path | `log/discover.py` (upper) reassembles ordering | Path enumeration is a filesystem fact (native); ordering/grouping is pure logic. Discover must NOT import pytsk3 (D-14). |
| Read log-file bytes (incl. gz) | FS seam `read_random` closure on the `FileEntry` | `gzip` (stdlib) in `log/` | Bytes come through the existing read-only seam; decompression is stdlib upper-tier. |
| RFC3164 line parsing / taxonomy | `log/auth.py`, `log/syslog.py` (upper, stdlib `re`) | — | Pure text; no native dependency. |
| tz/year inference | `log/timeresolve.py` (upper) | reads `/etc/localtime`,`/etc/timezone` via FS seam | Mirror of walk's D-16 FAT handling — policy lives in the orchestration tier, not the seam. |
| Normalize → forensic event (LOG-04) | `log/normalize.py` (upper) → `TimelineEvent` | `case/models.py` (exists) | The model + table already exist; this is a pure transform like `timeline/builder._explode`. |
| Persist events / super-timeline read (TIME-02) | `CaseStore` (sole writer) — `insert_timeline_events` / `get_timeline_events` (both exist) | — | D-08 sole-writer + D-26 store-owned total order. No new SQL ordering. |
| Streaming search over allocated/file content | FS seam `read_random` (per inode) | `search/content.py` (upper) | Allocated content is reachable via the existing per-file reader. |
| Streaming search over **unallocated** space | FS seam `allocated_data_blocks` (exists) + **byte seam `ImageHandle.read`** | `search/content.py` (upper) | pytsk3 has no unallocated-block API (verified); derive allocated set, read raw blocks via the byte seam, treat the complement as unallocated. |
| IOC / known-bad-hash matching (SEARCH-02) | `filter/hashsets.py` + `filter/nsrl.py` + `KnownMatch` (all exist) | `search/ioc.py` (upper) | Reuse Phase-4 infra verbatim; add literal/regex term matching. |
| Record search hits | `CaseStore` (sole writer) — **new narrow recorder + table** | — | Sole-writer rule; needs a `search_hits` table (the one genuine additive schema item — see §Open Questions). |
| CLI `logs`/`search` + `analyze --logs/--search` | `cli/main.py` (Typer) | `core/logs.py`, `core/search.py` orchestrators | Mirror `recover`/`analyze` opt-in precedent (D-40/D-48). |

## Standard Stack

### Core

**No new packages.** This phase is stdlib-only on top of the existing dependency set. The existing `pyproject.toml` `[project.dependencies]` (pytsk3, python-magic, typer, rich, jinja2) is unchanged.

| Module (stdlib) | Purpose | Why Standard | Provenance |
|-----------------|---------|--------------|------------|
| `re` | RFC3164/RFC5424 line grammar; literal+regex search terms | The DFIR-standard way to parse syslog lines; no parser-combinator dep needed | [VERIFIED: in-repo — `filter/hashsets.py` is already pure-stdlib text parsing] |
| `gzip` | Decompress `*.log.N.gz` rotated members read-only | stdlib; streams via `gzip.GzipFile(fileobj=...)` | [CITED: docs.python.org/3/library/gzip] |
| `datetime` + `zoneinfo` | tz-aware UTC normalization; IANA zone resolution from image | The repo's UTC-everywhere idiom (`util/timeutil`) + walk's D-16 zone handling | [VERIFIED: in-repo — `util/timeutil.py`, `core/walk.py`] |
| `io` | Wrap seam byte-readers as file-like objects for `gzip`/line iteration | stdlib | [ASSUMED] |

**Installation:** None. Confirm no new deps land in `pyproject.toml`:
```bash
# Phase 5 must NOT modify [project.dependencies]; a regression test should assert this (see Validation Architecture).
grep -A8 '^dependencies = \[' pyproject.toml
```

### Supporting (existing in-repo infrastructure REUSED — not installed)

| In-repo module | Purpose for Phase 5 | Verified Signature |
|----------------|---------------------|--------------------|
| `case/store.py::CaseStore.insert_timeline_events(rows)` | Persist normalized log events (LOG-04) | Returns int count; composes inside `store.transaction()`; sole writer |
| `case/store.py::CaseStore.get_timeline_events(source_id, *, limit=None)` | **IS** the TIME-02 super-timeline read | Returns `list[TimelineEvent]` in D-26 total order |
| `case/models.py::TimelineEvent` | **IS** the LOG-04 forensic-event model | `evidence_source_id, ts_utc, source, event_type, volume_id, volume_offset, path, meta_addr, actor, action, outcome, file_id, attributes, id` |
| `case/store.py::CaseStore.get_files(source_id)` | Enumerate `files` rows (to find log-file rows + search targets) | id-order; allocated + recovered |
| `filter/hashsets.py::parse_hash_set / custom_match` | SEARCH-02 known-bad-hash matching | `parse_hash_set(text)->dict[str,set]`; `custom_match(parsed, sense, list_name, *, md5, sha1, sha256)->dict|None` |
| `filter/nsrl.py::open_nsrl / nsrl_match` | SEARCH-02 NSRL membership | (read-only sqlite) — same as Phase-4 filter |
| `case/models.py::KnownMatch` + `store.insert_known_matches` | Record hash hits | `(file_id, source, matched_on, list_name, sense)` |
| `evidence/filesystem.py::walk_fs / allocated_data_blocks / open_fs / enumerate_volumes` | Path discovery + allocated-block set + raw-FS access | All pytsk3-free outputs; see file for exact signatures |
| `evidence/image.py::ImageHandle.read(offset, size) / get_size()` | **Raw unallocated byte reads** for SEARCH-01 | `read(offset:int, size:int)->bytes` — read-only |
| `util/timeutil.py::iso_utc / from_epoch_utc / utc_now` | UTC ISO-8601 serialization (naive rejected) | `iso_utc(dt)` raises on naive — structural SOUND-02 guard |
| `util/safe_extract.py::_sanitize_name / _confined_target` | Confine any recovered/exported artifact names | Used by `recover.py` already |

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Verdict |
|------------|-----------|----------|---------|
| stdlib `re` syslog grammar | a syslog-parsing PyPI lib (e.g. `pysyslogclient`, `syslog-rfc5424-parser`) | New runtime dep — **violates D-43** (no new deps). Most target the *network* syslog wire format, not on-disk rotated files. | stdlib `re` (locked) |
| Derive allocated set + raw byte read for unallocated | pytsk3 block-flag/`blkls` equivalent | **No such pytsk3 API exists** (verified — see Pitfall 1 + Don't-Hand-Roll). | derive + raw read (only option) |
| Write events to existing `timeline_events` | a new `log_events` table | Would break TIME-02-is-the-existing-read (D-47) and duplicate ordering logic. | existing table (locked, D-47) |
| `zoneinfo` from `/etc/localtime` | hard-code/assume UTC | Repeats the Phase-2 CR-01 silent-offset bug; SOUND-02 requires honest flagging. | infer + flag (locked, D-46) |

## Package Legitimacy Audit

> **Not applicable — this phase installs ZERO external packages.** All work is stdlib (`re`, `gzip`, `datetime`, `zoneinfo`, `io`, `sqlite3`) plus reuse of already-installed in-repo modules. No npm/PyPI/crates install occurs, so there is no slopcheck/registry surface in scope.

**A planner-enforced guard is warranted:** add a test asserting `pyproject.toml [project.dependencies]` is byte-unchanged from the Phase-4 baseline (the "no new runtime dep" invariant, D-43). See Validation Architecture Wave 0.

## Architecture Patterns

### System Architecture Diagram

```
                    pyautopsy logs / search        analyze --logs/--search
                            │                              │
                            ▼                              ▼
                   ┌──────────────────┐         ┌────────────────────┐
                   │  core/logs.py    │         │  core/search.py    │
                   │  run_logs()      │         │  run_search()      │
                   │ (orchestrator,   │         │ (orchestrator,     │
                   │  no pytsk3)      │         │  no pytsk3)        │
                   └────────┬─────────┘         └─────────┬──────────┘
                            │                             │
        ┌───────────────────┼──────────────┐             │
        ▼                   ▼              ▼              ▼
 ┌────────────┐   ┌──────────────┐  ┌────────────┐  ┌───────────────┐
 │log/discover│   │log/timeresolve│  │log/auth    │  │search/content │ literal+regex
 │ group +    │   │ tz from image │  │log/syslog  │  │ ─ allocated   │ over chunks
 │ order .gz  │   │ + year infer  │  │log/shell_  │  │ ─ file content│ (offset-tracked)
 │ rotation   │   │ (D-46, flag)  │  │  history   │  │ ─ UNALLOC ◄───┼─┐
 └─────┬──────┘   └──────┬───────┘  └─────┬──────┘  └───────┬───────┘ │
       │                 │                │                 │         │
       │   ┌─────────────┴────────────────┴───┐     ┌───────┴───────┐ │
       │   │   log/normalize.py → TimelineEvent│     │ search/ioc.py │ │
       │   │   (LOG-04, action/outcome/actor)  │     │ IOC + hash    │ │
       │   └──────────────┬────────────────────┘     │ (reuse filter)│ │
       │                  │                          └───────┬───────┘ │
       ▼                  ▼                                  ▼         │
 ┌──────────────────────────────────────────────────────────────────┐│
 │              evidence/filesystem.py  (FS seam, pytsk3)            ││
 │  walk_fs · open_fs · enumerate_volumes · allocated_data_blocks ──┼┘ allocated-block set
 │  per-inode read_random closures                                  │
 └──────────────────────────────┬───────────────────────────────────┘
                                 │ raw unallocated byte reads
                                 ▼
                   ┌──────────────────────────────┐
                   │  evidence/image.py (byte seam)│  ImageHandle.read(off,size)
                   └──────────────────────────────┘
                                 │
          ┌──────────────────────┴───────────────────────┐
          ▼                                               ▼
 ┌──────────────────────────┐               ┌─────────────────────────┐
 │ CaseStore (SOLE WRITER)  │               │  CaseStore (read)       │
 │ insert_timeline_events   │               │  get_timeline_events ───┼──► TIME-02
 │ insert_search_hits (NEW) │               │  (D-26 total order)     │   super-timeline
 │ insert_known_matches     │               └─────────────────────────┘
 └──────────────────────────┘
                                 │
                                 ▼
                   report/ (log-findings + search-results sections;
                            BODY byte-stable, CLI-02)
```

### Recommended Project Structure (matches CONTEXT.md sketch + one-concern convention)

```
src/pyautopsy/
├── log/
│   ├── __init__.py
│   ├── registry.py        # LogParser protocol + registry (EXT-01)
│   ├── discover.py        # locate + order rotated/gz log sets in the image (NO pytsk3)
│   ├── timeresolve.py     # D-46 tz/year inference + per-event timestamp_source flag
│   ├── auth.py            # LOG-01 auth.log/secure parser
│   ├── syslog.py          # LOG-02 syslog/messages parser
│   ├── shell_history.py   # LOG-03 bash/zsh history parser (+ tamperability finding)
│   └── normalize.py       # → TimelineEvent (LOG-04)
├── search/
│   ├── __init__.py
│   ├── content.py         # SEARCH-01 streaming literal+regex (allocated+unalloc+file)
│   └── ioc.py             # SEARCH-02 IOC list + known-bad-hash (reuse filter/*)
├── core/
│   ├── logs.py            # run_logs orchestrator (discover→parse→resolve→normalize→insert)
│   └── search.py          # run_search orchestrator
```
`case/store.py` gains a narrow `insert_search_hits` + `get_search_hits` (sole-writer rule). `cli/main.py` gains `logs`/`search` commands + `analyze --logs/--search`. `report/assemble.py` gains a log-findings + search-results section (body byte-stable).

### Pattern 1: The orchestrator skeleton (copy `core/recover.py` / `core/knownfiles.py` verbatim)

Every Phase-5 orchestrator (`run_logs`, `run_search`) follows the identical, four-times-proven shape. This is the single most important pattern to replicate.

```python
# Source: in-repo core/recover.py, core/knownfiles.py (verified patterns)
def run_logs(image, case_dir, *, evidence_source_id=None, max_size=None) -> LogsResult:
    image_path = Path(image).resolve()
    case_path = Path(case_dir).resolve()

    integrity.assert_source_not_mounted(image_path)          # 1. re-assert read-only (D-42/P1)
    try:
        store = CaseStore.open(case_path)                    # 2. open existing case (sole writer)
    except FileNotFoundError as exc:
        raise LogsError("no case database; run `pyautopsy ingest` first") from exc

    audit = AuditLog(case_path)
    audit.write("logs.start", image=str(image_path), case_dir=str(case_path))

    try:
        source_id = evidence_source_id or _latest_evidence_source_id(store)
        handle = image_seam.open_image(image_path)
        try:
            integrity.assert_source_not_mounted(image_path)  # re-assert after open
            events: list[TimelineEvent] = []
            for vol in fs_seam.enumerate_volumes(handle.image):
                try:
                    fs = fs_seam.open_fs(handle.image, vol.offset)
                except OSError:
                    continue                                 # encrypted/unsupported (D-20)
                # discover → parse → resolve-time → normalize  (all pytsk3-free)
                events.extend(_parse_logs_for_volume(fs, vol, source_id, ...))
            with store.transaction():
                store.insert_timeline_events(events)         # 3. sole-writer, one txn (WR-01)
        finally:
            handle.close()
        audit.write("logs.end", outcome="SUCCESS", events=len(events))
    except _EXPECTED_LOGS_ERRORS as exc:                     # expected → logs.error FAIL + re-raise
        audit.write("logs.error", outcome="FAIL", error=str(exc), error_type=type(exc).__name__)
        raise
    except Exception as exc:                                 # bug → DISTINCT logs.crashed
        audit.write("logs.crashed", outcome="FAIL", error=str(exc), error_type=type(exc).__name__)
        raise
    finally:
        store.close()
    return LogsResult(...)   # analytical counts ONLY — no wall-clock (CLI-02/P3)
```

`_EXPECTED_LOGS_ERRORS = (LogsError, integrity.MountedSourceError, integrity.IntegrityError, ImageOpenError, FilesystemError, OSError, sqlite3.Error)` — mirror `_EXPECTED_RECOVER_ERRORS`. The two-arm expected-vs-crashed audit split is mandatory (it is asserted by tests across the suite).

### Pattern 2: RFC3164 / RFC5424 line grammar (stdlib `re`)

`auth.log`/`secure` and `syslog`/`messages` share the same on-disk RFC3164 line shape. Detect RFC5424 (leading `<pri>1 ` version digit + ISO-8601) vs RFC3164 (legacy `Mmm dd HH:MM:SS`) per line.

```python
# Source: composed from rsyslog pmrfc3164 docs + DFIR-standard practice. [CITED: rsyslog.com/doc/configuration/modules/pmrfc3164.html]
import re

# RFC3164 (the dominant on-disk Linux format): "Mmm  d HH:MM:SS host program[pid]: msg"
# Note the TWO spaces before a single-digit day (day is space-padded to width 2).
RFC3164 = re.compile(
    r"^(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<program>[^\s:\[]+)(?:\[(?P<pid>\d+)\])?:\s?"
    r"(?P<msg>.*)$"
)
# RFC5424 (modern; some distros): "<PRI>1 2026-05-31T12:00:00.000+00:00 host app pid msgid [sd] msg"
RFC5424 = re.compile(
    r"^<(?P<pri>\d+)>1\s+(?P<ts>\S+)\s+(?P<host>\S+)\s+(?P<app>\S+)\s+"
    r"(?P<pid>\S+)\s+(?P<msgid>\S+)\s+(?:-|\[.*?\])\s+(?P<msg>.*)$"
)
```

The RFC3164 month-name + space-padded-day + no-year + no-tz fields are exactly why D-46's inference is required. Parse the `ts` to naive wall-clock components, then apply the timeresolve algorithm (Pattern 3). RFC5424's `ts` is ISO-8601 with offset → parse directly with `datetime.fromisoformat` and `iso_utc`.

### Pattern 3: D-46 tz/year inference (mirror the walk's D-16 FAT handling)

The walk already solved the structurally identical "naive wall-clock → flagged UTC" problem for FAT (`core/walk.py::_macb_to_utc_iso`). Mirror it exactly.

```python
# Source: mirror of in-repo core/walk.py::_macb_to_utc_iso (verified D-16 pattern)
from datetime import datetime
from zoneinfo import ZoneInfo
from pyautopsy.util.timeutil import iso_utc

def resolve_host_tz(fs_seam_reader) -> tuple[ZoneInfo | None, str]:
    """Derive the image's local zone: /etc/localtime symlink target, then /etc/timezone."""
    # 1. /etc/localtime is normally a symlink to /usr/share/zoneinfo/<Area>/<City>.
    #    Read the link target through the FS seam; map .../zoneinfo/<Zone> -> ZoneInfo(<Zone>).
    # 2. Fallback: read /etc/timezone (Debian) which contains the IANA name as text.
    # 3. On failure: return (None, "tz-undeterminable") -> caller uses UTC + warning flag.
    ...

def to_utc(ts_naive_wallclock: datetime, host_tz: ZoneInfo | None) -> tuple[str, dict]:
    if host_tz is None:
        # D-46 fallback: treat as UTC, FLAG explicitly (never silent — SOUND-02 / CR-01 lesson)
        dt = ts_naive_wallclock.replace(tzinfo=ZoneInfo("UTC"))
        return iso_utc(dt), {"timestamp_source": "log:assumed-utc",
                             "time_warning": "host timezone undeterminable; assumed UTC"}
    dt = ts_naive_wallclock.replace(tzinfo=host_tz)         # interpret wall-clock IN host zone
    return iso_utc(dt), {"timestamp_source": "log:inferred-tz",
                         "assumed_timezone": str(host_tz)}  # mirrors walk's assumed_timezone attr
```

**Year inference** (the part FAT did not need): RFC3164 lines carry month+day+time but no year. Algorithm:
1. Seed the year from the **log file's mtime** (the FS-seam `FileEntry.mtime` for that log row).
2. Walk events **in file order**; when the month sequence rolls **backwards** (e.g. Dec → Jan within one file, or oldest rotated file → newest), decrement the seeded year at the boundary (logs are append-ordered, so a backwards month-jump means a year boundary was crossed).
3. For a rotated set processed oldest→newest (Pattern from §discover), carry the running year across files.
4. Record the inferred year + the inference basis in `attributes` (`{"year_inferred": 2025, "year_basis": "file mtime + rotation order"}`) — **flag it**, never silent.

### Pattern 4: auth taxonomy → action/outcome (honest, observed-line-only)

Map well-known auth.log message shapes to `action`/`outcome` — describing **the observed log line**, never inferred intent (CON-03/RECOV-03 lesson). Keep the vocabulary small and literal.

```python
# Source: standard Linux PAM/sshd/sudo log strings (well-known); kept descriptive only.
# action/outcome describe WHAT THE LINE SAYS, not why or who-is-guilty.
AUTH_PATTERNS = [
    (re.compile(r"Accepted (\w+) for (?P<user>\S+) from (?P<src>\S+)"),  "ssh-login",  "success"),
    (re.compile(r"Failed password for (?:invalid user )?(?P<user>\S+)"), "ssh-login",  "failure"),
    (re.compile(r"session opened for user (?P<user>\S+)"),               "session",    "opened"),
    (re.compile(r"session closed for user (?P<user>\S+)"),               "session",    "closed"),
    (re.compile(r"sudo:\s+(?P<user>\S+) : .*COMMAND=(?P<cmd>.*)"),       "sudo",       "granted"),
    (re.compile(r"sudo:.*authentication failure"),                       "sudo",       "denied"),
    (re.compile(r"new user|useradd"),                                    "account",    "created"),
]
# actor = "user=<name>" (and uid where the line carries it); unmatched lines still
# become events with action=None and the raw msg in attributes (never dropped silently).
```
For SEARCH-02 IOC matching: an IOC list is parsed like a hash list but for **literal/regex string terms**; reuse `filter/hashsets.parse_hash_set`'s tolerant-list style (skip `#`/blank, one token per line) for the *hash* arm, and a sibling parser for the *string-term* arm.

### Pattern 5: TIME-02 is the existing read (no new ordering code)

```python
# Source: in-repo case/store.py::get_timeline_events (verified)
# The super-timeline IS this call — log events written to timeline_events sort
# in the SAME D-26 total order as filesystem events:
#   ts_utc, volume_id, volume_offset, path, event_type, meta_addr, source, actor, id
super_timeline = store.get_timeline_events(evidence_source_id)
```
Log events carry `volume_id=0, volume_offset=0` (or the source log file's volume), `meta_addr=NULL`, `path=<log file path or actor>`. The trailing `source, actor, id` tiebreak — written specifically for the CR-01 NULL-key trap — keeps tied log events in a stable, insertion-deterministic order. **Do not add a new ORDER BY anywhere.**

### Pattern 6: normalize → TimelineEvent (mirror `timeline/builder._explode`)

```python
# Source: mirror of in-repo timeline/builder.py::_explode (verified pure-transform pattern)
def to_event(parsed, *, evidence_source_id, file_id, source, log_path, utc_iso, attrs) -> TimelineEvent:
    return TimelineEvent(
        evidence_source_id=evidence_source_id,
        ts_utc=utc_iso,                 # verbatim from timeresolve (never re-derived downstream)
        source=source,                  # "auth" | "syslog" | "shell-history"
        event_type=parsed.action or "log",   # log producers use their own action types (D-23)
        volume_id=parsed.volume_id, volume_offset=parsed.volume_offset,
        path=log_path,                  # evidence-ref: the source log file path
        meta_addr=None,                 # log events have no inode (nullable, schema-allowed)
        actor=parsed.actor,             # "user=alice" / uid where known (None, never "user=None")
        action=parsed.action,           # reserved column, now populated (D-23/D-47)
        outcome=parsed.outcome,
        file_id=file_id,                # FK to the log FILE's files row (D-47)
        attributes=attrs,               # timestamp_source, assumed_timezone/year, raw msg, etc.
    )
```

### Anti-Patterns to Avoid

- **Adding a `log_events`/`search_hits_ordering` table or any new ORDER BY for the super-timeline.** TIME-02 is `get_timeline_events`. (D-47)
- **Importing `pytsk3` in `log/` or `search/`.** The seam-allowlist test (`tests/test_seam_allowlist.py`) **will fail the build**. All native access goes through the two allowlisted seam files only.
- **Slurping a whole volume/file into memory for search.** PERF-01 — stream in chunks with a small carry-over overlap for regex boundaries.
- **Storing an inferred syslog time without a flag.** Repeats the Phase-2 CR-01 silent-offset bug. (SOUND-02/D-46)
- **Asserting intent from a log line** ("user X attacked", "this proves…"). Describe the observed line only. (CON-03)
- **Letting any wall-clock reach the report body.** Segregate to the run-metadata sidecar like `analyze` does. (CLI-02/W-1)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| The forensic-event model (LOG-04) | A new log-event dataclass/table | Existing `TimelineEvent` + `timeline_events` table | Already designed for Phase 5 (nullable `file_id`, reserved `action`/`outcome`); a parallel model breaks TIME-02. |
| Super-timeline merge/ordering (TIME-02) | A merge-sort of fs + log events | `store.get_timeline_events()` | The store already imposes the D-26 total order with the CR-01-safe tiebreak. |
| Deterministic event/hit ordering | Sorting in the orchestrator | Store-owned `ORDER BY` (D-26/D-41 pattern) | Re-sorting outside the store violates the single-ordering-source rule and risks CLI-02 drift. |
| Known-bad-hash matching (SEARCH-02) | New hash-set parser/matcher | `filter/hashsets.parse_hash_set` + `custom_match`, `filter/nsrl`, `KnownMatch` | Phase-4 infra is hash-sense-aware, tolerant, neutral, and tested. |
| **Reading unallocated space** | A custom block-bitmap walker / calling `blkls`/`blkstat` via subprocess | `allocated_data_blocks(fs)` (exists) to get the allocated set, then `ImageHandle.read(block*block_size, block_size)` for the complement | **pytsk3 exposes no block-flag/`block_walk`/`TSK_FS_BLOCK` API** (verified — Pitfall 1). The repo already derives allocated blocks this way; the byte seam already does read-only raw reads. |
| tz-aware UTC serialization | `datetime.isoformat()` calls scattered around | `util/timeutil.iso_utc` (rejects naive) | Structural SOUND-02 guard already in place. |
| Gzip rotation read | A custom inflate | `gzip.GzipFile(fileobj=<seam-byte-stream>)` | stdlib; streams without writing the source. |
| Path confinement for any exported log/hit artifact | Manual `os.path.join` | `util/safe_extract._confined_target` | Zip-Slip-class protection already built (Phase 1). |
| Audit + expected/crashed split | Ad-hoc try/except | Copy `core/recover.py`'s two-arm pattern | Asserted across the suite; consistency is a tested invariant. |

**Key insight:** Phase 5 is ~80% reuse. The highest-value engineering is (a) the three stdlib text parsers, (b) the D-46 tz/year inference (a direct mirror of the walk's D-16 work), and (c) the unallocated-read workaround. Everything else is wiring already-built components in the already-established orchestrator shape.

## Runtime State Inventory

> This is a feature-extension phase, not a rename/refactor. The category that *does* apply is "new persistent state this phase introduces" — included for completeness.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data (NEW) | Search hits need persistence with file+offset (SEARCH-02). No table exists. | **Additive** `search_hits` table + `SearchHit` model + `insert_search_hits`/`get_search_hits` (sole-writer). The ONE genuine new schema item. See Open Questions Q1. |
| Stored data (REUSE) | Log events → existing `timeline_events` (nullable `file_id`, reserved `action`/`outcome`). | **No schema churn** (D-47) — verified against `case/schema.sql`. |
| Live service config | None — PyAutopsy reads a disk image; it registers no external service state. | None — verified (no daemon, no scheduler, no external registration in repo). |
| OS-registered state | None. | None — verified. |
| Secrets/env vars | None — no secrets, no env-var-named config in this phase. | None — verified. |
| Build artifacts / deps | `pyproject.toml [project.dependencies]` MUST stay unchanged (D-43 no-new-dep). | Add a regression test asserting deps are byte-identical to Phase-4 baseline. |

## Common Pitfalls

### Pitfall 1: pytsk3 has no unallocated-block / block-flag API
**What goes wrong:** A plan that assumes `fs.read_block()`, a block-allocation bitmap, or a `blkls`/`block_walk` binding will not compile — none exist in pytsk3.
**Why it happens:** pytsk3 wraps TSK's file/meta layer but not its block-walk callback layer; `TSK_FS_BLOCK` is "immediately invalid" and there is no callback binding (confirmed by the sleuthkit discourse thread AND by the repo's own `allocated_data_blocks` docstring).
**How to avoid:** Reuse the established workaround: `allocated_data_blocks(fs)` (walk allocated inodes' non-resident runs → set of allocated block addresses), get `fs.info.block_size` (must be exposed through a small pytsk3-free seam helper, e.g. `block_size(fs)->int` and `block_count(fs)->int`, added inside `evidence/filesystem.py`), then for each block index `i` not in the allocated set, read `handle.read(vol_offset + i*block_size, block_size)` via the byte seam and scan it. Mark hits as `region="unallocated", block=i, offset=…`.
**Warning signs:** Any plan task referencing `blkls`, `block_walk`, `TSK_FS_BLOCK`, or a block bitmap. [VERIFIED: in-repo `allocated_data_blocks` docstring + sleuthkit.discourse.group/t/3274]

### Pitfall 2: shell history has NO reliable per-line timestamps
**What goes wrong:** Plain `.bash_history` lines are commands with **no timestamp** unless `HISTTIMEFORMAT` was set (then `#<epoch>` lines precede commands). `.zsh_history` extended format is `: <start>:<elapsed>;<command>` — but only if `EXTENDED_HISTORY` is on. History is trivially editable and order is not guaranteed.
**Why it happens:** History files are a usability feature, not an audit log.
**How to avoid:** (1) Detect format: zsh extended (`: \d+:\d+;`) → use the embedded epoch; bash `#<epoch>` pairs → use them; otherwise **no timestamp** — emit the event with `ts_utc` = the log file's mtime (flagged `"ts_basis": "file-mtime-fallback; no per-line timestamp"`) and surface a **tamperability finding** (D-44). (2) Never present history order as chronological truth. This is a Success-Criterion-2 honesty requirement.
**Warning signs:** A plan that assumes every history line has a time, or sorts history by line order as if chronological. [CITED: bash/zsh history format — well-known; ASSUMED on exact distro defaults]

### Pitfall 3: CR-01 total-order determinism with NULL volume/meta on log events
**What goes wrong:** Two log events with the same `ts_utc` (common — second-resolution syslog) and NULL `meta_addr` could tie and reorder between runs, breaking CLI-02.
**Why it happens:** The first six D-26 columns are not a total order when `meta_addr` is NULL.
**How to avoid:** The store's tiebreak chain already ends `…source, actor, id`, and `id` is insertion-deterministic **only if** `run_logs` inserts events in a deterministic order within one transaction. So: parse rotated files in a **fixed order** (oldest→newest), parsers in **registry-declared order**, events appended in encounter order, single `insert_timeline_events` call. Then the same fixture always assigns the same `id` to the same event (the exact mechanism `build_timeline` and `run_filter` rely on).
**Warning signs:** Parallel/unordered file processing; multiple insert transactions; any dict/set iteration feeding insert order. **Add a regression test with tied log events** (same ts, NULL meta) asserting byte-stable order across two runs. [VERIFIED: in-repo `get_timeline_events` docstring]

### Pitfall 4: rotation/year-boundary reassembly + "log completeness"
**What goes wrong:** `auth.log`, `auth.log.1`, `auth.log.2.gz`, `auth.log.3.gz` parsed in filename order = newest-first, corrupting year inference and event order; gaps (a missing rotation index, or logrotate `dateext` names like `auth.log-20260101`) silently dropped.
**Why it happens:** logrotate numbering is newest=lowest-number; `.gz` only on older members; two naming schemes (numeric suffix vs `dateext`).
**How to avoid:** In `discover.py`, group by base name, sort **oldest→newest** (highest numeric suffix first, gz before non-gz of same base, then the live file last), handle both numeric and `dateext` suffixes. Surface a "log completeness" finding noting which indices were present/absent and the covered time span (D-44 — completeness as a finding, never a silent assumption).
**Warning signs:** Sorting log files lexically; assuming `.1` is oldest. [ASSUMED: logrotate conventions — well-known, not session-verified against a specific distro]

### Pitfall 5: regex matches spanning chunk boundaries (PERF-01 streaming)
**What goes wrong:** Streaming a file/volume in fixed chunks misses a literal/regex match that straddles two chunks.
**Why it happens:** The match's bytes are split across read boundaries.
**How to avoid:** Carry an overlap window of `max_term_len - 1` bytes (literal) or a bounded overlap (regex — document a max-match-length cap) between chunks; dedupe hits whose absolute offset was already reported in the previous overlap. Report the **absolute** offset (file-relative for file content; volume/image-relative for unallocated). Never load the whole region (PERF-01).
**Warning signs:** A plan that reads with no overlap, or that buffers the whole file/volume.

### Pitfall 6: report-body byte-determinism (CLI-02) for new sections
**What goes wrong:** Adding log-findings / search-results sections to the report body introduces wall-clock or unstable ordering, breaking the byte-identical guarantee.
**How to avoid:** Read everything through store-owned total orders (`get_timeline_events`, `get_search_hits`); no `utc_now()` in `assemble_report_body`; counts/sections derived from sorted data only — exactly as `assemble.py` already does for the timeline/known-filter sections. Keep volatile run metadata in the existing `run_metadata.json` sidecar. [VERIFIED: in-repo `report/assemble.py` docstring]

## Code Examples

### Reading a gz-rotated log member read-only through the seam
```python
# Source: stdlib gzip + in-repo seam read_random closure. [CITED: docs.python.org/3/library/gzip]
import gzip, io

def read_log_bytes(entry) -> bytes:
    """entry is a FileEntry from walk_fs; entry.read_random is the seam's read-only closure."""
    size = entry.size
    raw = entry.read_random(0, size) if entry.read_random else b""
    if entry.name.endswith(".gz"):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            return gz.read()          # PERF note: for large members, stream in chunks instead
    return raw
```

### Streaming unallocated scan (the verified workaround)
```python
# Source: composed from in-repo allocated_data_blocks + ImageHandle.read (both verified).
def scan_unallocated(handle, fs, vol, pattern, block_size, allocated_blocks):
    """Yield (block_index, offset, match) for hits in UNALLOCATED blocks only (PERF-01)."""
    nblocks = block_count(fs)                      # new pytsk3-free seam helper
    carry = b""
    for i in range(nblocks):
        if i in allocated_blocks:
            carry = b""                            # reset overlap at an allocated gap
            continue
        data = handle.read(vol.offset + i * block_size, block_size)  # raw read-only byte seam
        window = carry + data
        for m in pattern.finditer(window):
            abs_off = vol.offset + i * block_size - len(carry) + m.start()
            yield i, abs_off, m.group(0)
        carry = window[-MAX_OVERLAP:]              # boundary-spanning match guard (Pitfall 5)
```

### /etc/localtime resolution through the FS seam (D-46)
```python
# Source: standard Linux tz layout; read via the existing FS seam (no pytsk3 in caller).
# /etc/localtime -> symlink to /usr/share/zoneinfo/<Area>/<City>.
# The FS seam yields the symlink target as the entry's content/target; map the
# zoneinfo suffix to ZoneInfo(<Area>/<City>). Fallback: read /etc/timezone text.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Parse `/var/log/*` as text only | Modern distros default to **binary journald** (`*.journal`) | systemd v259 persistent-by-default | **Out of scope (D-43/LOG-05)** — but the report MUST flag that text logs may be incomplete on a journald-primary host (log-completeness finding). |
| RFC3164 (BSD syslog, no year/tz) | RFC5424 (ISO-8601 + offset) | RFC5424 since 2009 | Parse both; RFC5424 needs no inference, RFC3164 needs D-46. |
| `blkls`/`blkcat` CLI for unallocated | pytsk3 still has no block-walk binding | unchanged | Must use the derive-allocated + raw-read workaround. |

**Deprecated/outdated:**
- Assuming text logs are complete on a 2026-era Linux host — journald is the primary store; text logs may be partial. Surface as a finding, do not fail.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `io.BytesIO`-wrapping seam bytes for `gzip` is acceptable; large gz members may need true streaming | Standard Stack / Code Examples | LOW — only a memory-efficiency concern; PERF-01 mitigation is to chunk. Verify member sizes against fixtures. |
| A2 | logrotate numeric-vs-`dateext` naming conventions are as described | Pitfall 4 | MEDIUM — wrong ordering corrupts year inference. Build fixtures covering both naming schemes and verify ordering. |
| A3 | bash/zsh history default formats (`#<epoch>` pairs, `: <ts>:<dur>;cmd`) | Pitfall 2 | LOW — handled by format detection with an honest no-timestamp fallback; never silently wrong. |
| A4 | `fs.info.block_size` / a derivable block count are accessible to add `block_size`/`block_count` seam helpers | Pitfall 1, Code Examples | MEDIUM — load-bearing for SEARCH-01 unallocated. Spike against a real fixture in Wave 0 (the `allocated_data_blocks` code already reads `fs.info`, so this is very likely fine). |
| A5 | `/etc/localtime` symlink target is readable through the FS seam (target string surfaced) | Pattern 3 / Code Examples | MEDIUM — if the seam does not surface symlink targets, fall back to `/etc/timezone` text or UTC-with-warning. Verify the seam's symlink handling in Wave 0. |
| A6 | auth.log message strings (sshd/sudo/PAM) match the taxonomy patterns on the target fixtures | Pattern 4 | LOW — unmatched lines still become events (raw msg in attributes), never dropped. Tune patterns against fixtures. |

## Open Questions

1. **`search_hits` persistence shape (the one genuine new schema item).**
   - What we know: SEARCH-02 requires hits reported by **file and offset**; the sole-writer rule requires a `CaseStore` method + table; the store-owned-ordering rule requires a deterministic `get_search_hits` ORDER BY.
   - What's unclear: exact columns. Proposed (additive, mirrors `known_file_matches`): `id, evidence_source_id, file_id (nullable — unallocated hits have none), region (allocated|unallocated|metadata), term, term_kind (literal|regex|ioc|hash), volume_id, volume_offset, byte_offset, block_index (nullable), context (bounded snippet), attributes`. Total order: `volume_id, volume_offset, byte_offset, term, id`.
   - Recommendation: planner adds this as a small additive migration in `case/schema.sql` + `SearchHit` model + `insert_search_hits`/`get_search_hits`. This is the ONLY schema change in the phase; `timeline_events` is untouched (D-47).

2. **`block_size`/`block_count` seam helpers.**
   - What we know: SEARCH-01 unallocated needs block geometry; `allocated_data_blocks` already reads `fs.info` inside the seam.
   - What's unclear: whether to expose `block_size(fs)->int` + `block_count(fs)->int` or a single `iter_unallocated_blocks(handle, fs, vol)` generator.
   - Recommendation: a single seam generator `iter_unallocated_blocks` keeps ALL pytsk3 access inside the seam (D-14) and hands `search/content.py` a clean `(block_index, bytes)` stream. Prefer this over leaking block geometry to the upper tier.

3. **Where do log-file `files` rows come from for `file_id`?**
   - What we know: D-47 sets `file_id` → the source log file's `files` row. Those rows exist only if `walk` ran.
   - Recommendation: `run_logs` looks up the log file's `files` row via `get_files(source_id)` path-match; if absent (standalone `logs` without a prior walk), set `file_id=None` and record the log path in `attributes`/`path`. Mirrors `recover`'s standalone-capable design.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python stdlib `re`/`gzip`/`datetime`/`zoneinfo`/`io`/`sqlite3` | all of Phase 5 | ✓ | 3.11+ | — (stdlib) |
| pytsk3 (existing seam only) | unallocated block geometry, FS access | ✓ | 20260520 (pinned) | — |
| IANA tz database (`zoneinfo`) | D-46 host-tz resolution | ✓ (system tzdata or `tzdata` wheel) | — | UTC-with-warning if a named zone is unresolvable (D-46 fallback) |
| `mkfs`/`debugfs`/`mtools` (test fixture build only) | building log-bearing fixtures | host-only (CI uses committed fixtures) | — | Commit fixtures like Phase 2/4 (CI needs no mkfs) |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** `zoneinfo` named-zone resolution → UTC-with-warning (D-46, by design).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (+ ruff, mypy) [VERIFIED: pyproject.toml] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`pythonpath=["src"]`, `testpaths=["tests"]`, `addopts="-ra"`) |
| Quick run command | `python -m pytest tests/test_logs.py tests/test_search.py -x` |
| Full suite command | `python -m pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LOG-01 | auth.log login/SSH/sudo/failed-auth → events w/ action/outcome | unit | `pytest tests/test_logs.py::test_auth_taxonomy -x` | ❌ Wave 0 |
| LOG-01/02 | RFC3164 + RFC5424 line grammar parses fixtures exactly | unit | `pytest tests/test_logs.py::test_rfc3164_grammar -x` | ❌ Wave 0 |
| LOG-02 | syslog/messages service/kernel/cron/error events | unit | `pytest tests/test_logs.py::test_syslog_events -x` | ❌ Wave 0 |
| LOG-03 | bash/zsh history parsed; no-timestamp + tamperability finding | unit | `pytest tests/test_logs.py::test_shell_history_tamperability -x` | ❌ Wave 0 |
| LOG-04 | parsed events normalize to TimelineEvent (action/outcome/actor/file_id) | unit | `pytest tests/test_logs.py::test_normalize_to_timeline_event -x` | ❌ Wave 0 |
| D-46 | tz inferred from /etc/localtime; year inferred; both FLAGGED; UTC fallback warned | unit | `pytest tests/test_logs.py::test_timeresolve_inferred_and_flagged -x` | ❌ Wave 0 |
| D-45/Pitfall4 | rotated `.1`/`.2.gz` reassembled oldest→newest; completeness finding | unit | `pytest tests/test_logs.py::test_rotation_reassembly_order -x` | ❌ Wave 0 |
| TIME-02 | get_timeline_events returns fs + log events in one UTC total order | integration | `pytest tests/test_logs.py::test_super_timeline_merge -x` | ❌ Wave 0 |
| CR-01 | tied log events (same ts, NULL meta) byte-stable across two runs | regression | `pytest tests/test_reproducibility.py::test_tied_log_events_stable -x` | ❌ Wave 0 (extend existing file) |
| SEARCH-01 | literal+regex over allocated + file content + UNALLOCATED; offsets correct | integration | `pytest tests/test_search.py::test_streaming_search_all_regions -x` | ❌ Wave 0 |
| SEARCH-01/Pitfall5 | match spanning a chunk boundary is found once, correct offset | unit | `pytest tests/test_search.py::test_boundary_spanning_match -x` | ❌ Wave 0 |
| SEARCH-02 | IOC + known-bad-hash hits reported by file+offset (reuse filter) | integration | `pytest tests/test_search.py::test_ioc_and_hash_hits -x` | ❌ Wave 0 |
| SOUND-01 | source image never written by logs/search (read-only re-verify) | regression | `pytest tests/test_readonly_guarantee.py -x` (extend) | ✅ (extend) |
| D-14 | log/ and search/ do not import pytsk3/pyewf | architecture | `pytest tests/test_seam_allowlist.py -x` | ✅ (already enforces) |
| D-43 | no new runtime dependency added to pyproject | regression | `pytest tests/test_no_new_deps.py -x` | ❌ Wave 0 |
| CLI-02/D-48 | default `analyze` (no --logs/--search) stays byte-identical to Phase-4 | regression | `pytest tests/test_reproducibility.py::test_default_analyze_unchanged -x` (extend) | ✅ (extend) |
| D-48 | `pyautopsy logs` / `pyautopsy search` smoke | smoke | `pytest tests/test_cli_smoke.py -x` (extend) | ✅ (extend) |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_logs.py tests/test_search.py -x` (+ `ruff check` + `mypy src`)
- **Per wave merge:** `python -m pytest`
- **Phase gate:** Full suite green + `ruff`/`mypy` clean before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_logs.py` — LOG-01/02/03/04, D-45/D-46, TIME-02 (new file)
- [ ] `tests/test_search.py` — SEARCH-01/02, boundary-spanning, unallocated (new file)
- [ ] `tests/test_no_new_deps.py` — assert `[project.dependencies]` byte-identical to Phase-4 baseline (D-43)
- [ ] Fixtures in `tests/fixtures/make_fixtures.py` + `conftest.py`:
  - A committed ext4 image carrying `/var/log/auth.log`, `auth.log.1`, `auth.log.2.gz`, `/var/log/syslog`, a `/etc/localtime` symlink + `/etc/timezone`, and a user `~/.bash_history` + `~/.zsh_history` (extended + bare), built once with mkfs/debugfs and committed (mirrors the existing fixture approach — CI needs no mkfs).
  - A fixture with a known string planted in **unallocated** space (write file, delete, leave blocks) + a known IOC term + a known-bad hash, for SEARCH-01/02 exact-offset assertions.
  - A fixture with two log events at the identical second + NULL meta (CR-01 tied-order regression).
- [ ] Extend `tests/test_reproducibility.py` (tied log events; default-analyze-unchanged), `tests/test_readonly_guarantee.py` (logs/search read-only), `tests/test_cli_smoke.py` (`logs`/`search`).

*(Existing `tests/test_seam_allowlist.py` already gates D-14 with no change — it will fail the build if `log/`/`search/` import pytsk3, which is the desired behavior.)*

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: high` (from config.json).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | PyAutopsy has no auth surface (offline forensic CLI). |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no | No multi-user surface. |
| V5 Input Validation | **yes** | Log file content, regex search terms, IOC lists, tz strings are all **untrusted evidence/operator input**: decode `utf-8`/`errors="replace"` (never as a write path); compile user regex with a documented complexity bound (ReDoS guard); validate `--timezone` via `ZoneInfo` before use (existing CLI pattern); never use a parsed log path/name to write a file (route exports through `safe_extract`). |
| V6 Cryptography | no (reuse) | Hash matching reuses the Phase-4 `hashlib`-based `filter/*`; no new crypto. |
| V12 Files & Resources | **yes** | Read-only evidence (SOUND-01): all reads via the two seams; PERF-01 streaming caps memory; decompression-bomb guard on gz members (cap inflated size, mirroring `safe_extract` ExtractionLimits); confined output for any exported snippet. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malicious log content (control chars, injection into report) | Tampering | jinja2 autoescape (already on) neutralizes evidence strings in HTML; decode lenient, treat as data only. |
| Operator-supplied regex ReDoS | Denial of Service | Bound match length / document a complexity cap; consider a per-term timeout or reject catastrophic patterns; never run unbounded `.*` over a whole volume without chunking. |
| gz rotation **decompression bomb** | Denial of Service | Cap inflated bytes per member (reuse the `safe_extract` size-cap ethos, T-04-01-BOMB pattern); stream, don't slurp. |
| Log path used as a write target (Zip-Slip-class) | Tampering | Parsed log/history paths are DATA; any export goes through `safe_extract._confined_target`. |
| Year/tz inference presented as fact | Information disclosure / integrity | D-46 honest flagging — `timestamp_source` + assumed-zone/year recorded; UTC fallback warned. |
| Source image mutation during search | Tampering | `assert_source_not_mounted` re-asserted in `run_logs`/`run_search`; reads via read-only seams only; Phase-1 end-of-run re-verify still runs under `analyze`. |

## Sources

### Primary (HIGH confidence — in-repo, verified this session)
- `src/pyautopsy/case/schema.sql` — `timeline_events` nullable `file_id` + reserved `action`/`outcome`; `idx_timeline_events_order` ORDER BY (D-26/CR-01).
- `src/pyautopsy/case/models.py::TimelineEvent` / `KnownMatch` — the LOG-04 model already exists.
- `src/pyautopsy/case/store.py` — `insert_timeline_events`, `get_timeline_events` (TIME-02), `insert_known_matches`, `get_known_matches`, `get_files`.
- `src/pyautopsy/timeline/builder.py::_explode` — the normalize-to-event transform pattern.
- `src/pyautopsy/core/recover.py`, `core/knownfiles.py`, `core/walk.py`, `core/analyze.py` — orchestrator + opt-in + audit + determinism patterns.
- `src/pyautopsy/core/walk.py::_macb_to_utc_iso` / `_macb_fields` — the D-16 naive-wall-clock → flagged-UTC model to mirror for D-46.
- `src/pyautopsy/evidence/filesystem.py` — `walk_fs`, `allocated_data_blocks` (**confirms no block-flag API**), `enumerate_volumes`, `open_fs`, per-inode `read_random`.
- `src/pyautopsy/evidence/image.py::ImageHandle.read` — the raw read-only byte seam for unallocated reads.
- `src/pyautopsy/util/timeutil.py` — `iso_utc` (rejects naive), `from_epoch_utc`.
- `src/pyautopsy/report/assemble.py` — body byte-determinism rules; existing limitations copy that already names "log analysis, super-timeline, content search" as the Phase-5 additions.
- `tests/test_seam_allowlist.py` — executable D-14 gate (will fail if log/search import pytsk3).
- `pyproject.toml` — dependency set (no new dep), pytest config.

### Secondary (MEDIUM confidence — verified against authoritative source)
- rsyslog `pmrfc3164` docs — RFC3164 `%b %d %H:%M:%S` no-year format. https://www.rsyslog.com/doc/configuration/modules/pmrfc3164.html
- Python stdlib `gzip` — streaming via `GzipFile(fileobj=...)`. https://docs.python.org/3/library/gzip.html

### Tertiary (LOW confidence — corroborates a negative claim)
- sleuthkit discourse "Pytsk3: Reading FS Block Flags via Python" (#3274) — confirms no exposed block-flag/`block_walk` API in pytsk3 (corroborates the in-repo `allocated_data_blocks` docstring). https://sleuthkit.discourse.group/t/pytsk3-reading-fs-block-flags-via-python/3274

## Metadata

**Confidence breakdown:**
- Standard stack (stdlib-only, no new deps): HIGH — verified against pyproject + repo conventions; D-43 makes this unambiguous.
- Architecture (reuse of existing model/store/orchestrator patterns): HIGH — every consumed module read and signature confirmed this session.
- LOG-04/TIME-02 (existing table + read): HIGH — schema + store code confirm nullable `file_id` and reserved `action`/`outcome`, and `get_timeline_events` is the documented super-timeline read.
- D-46 tz/year inference: HIGH on the pattern (direct mirror of in-repo D-16), MEDIUM on `/etc/localtime` seam access (A5 — verify in Wave 0).
- SEARCH-01 unallocated read: MEDIUM-HIGH — the no-pytsk3-block-API constraint is verified and the workaround reuses verified in-repo primitives; exact `block_size`/`block_count` seam surface needs a Wave-0 spike (A4).
- Pitfalls: HIGH for in-repo-grounded ones (CR-01, body determinism, seam allowlist), MEDIUM for distro-convention ones (logrotate naming, history formats).

**Research date:** 2026-05-31
**Valid until:** ~2026-06-30 (stable — stdlib + in-repo patterns; the only external-facing fact, pytsk3's lack of a block API, is long-standing).
