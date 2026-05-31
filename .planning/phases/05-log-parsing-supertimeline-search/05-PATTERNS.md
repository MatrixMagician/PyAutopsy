# Phase 5: Log Parsing, Super-Timeline & Search - Pattern Map

**Mapped:** 2026-05-31
**Files analyzed:** 15 new + 4 modified
**Analogs found:** 18 / 19 (1 with no exact analog: the streaming-search core)

> **Phase 5 is ~80% reuse.** Every load-bearing piece (the event model, the store
> writer/reader, the orchestrator shape, the opt-in CLI, the tz/year inference,
> the hash-set matcher, the byte/FS seams) already exists. The planner should
> treat almost every new file as a *transcription* of a named existing analog,
> not a greenfield design. Concrete signatures to reuse are inlined below.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `log/registry.py` (NEW) | registry/protocol | event-driven (dispatch) | `timeline/builder.py` (producer convention) + `filter` module dispatch | role-match |
| `log/discover.py` (NEW) | service | file-I/O (path grouping) | `evidence/filesystem.py::walk_fs` (enumeration) + `core/recover.py` volume loop | role-match |
| `log/timeresolve.py` (NEW) | utility | transform | `core/walk.py::_macb_to_utc_iso` / `_macb_fields` | **exact** |
| `log/auth.py` (NEW) | parser | transform (text→records) | RESEARCH Pattern 2/4 (no in-repo text parser; closest is `filter/hashsets.parse_hash_set` line-tolerant style) | role-match |
| `log/syslog.py` (NEW) | parser | transform (text→records) | same as `log/auth.py` | role-match |
| `log/shell_history.py` (NEW) | parser | transform (text→records) | same as `log/auth.py` | role-match |
| `log/normalize.py` (NEW) | utility | transform (→TimelineEvent) | `timeline/builder.py::_explode` | **exact** |
| `search/content.py` (NEW) | service | streaming | `evidence/image.py::ImageHandle.read` + `filesystem.allocated_data_blocks` (composed; no single analog) | partial (NEW capability) |
| `search/ioc.py` (NEW) | service | CRUD/match | `core/knownfiles.py::run_filter` + `filter/hashsets.py` | **exact** |
| `core/logs.py` (NEW) | orchestrator | event-driven pipeline | `core/recover.py::run_recover` | **exact** |
| `core/search.py` (NEW) | orchestrator | streaming pipeline | `core/knownfiles.py::run_filter` + `core/recover.py` | **exact** |
| `case/models.py::SearchHit` (MOD, additive) | model | — | `case/models.py::KnownMatch` | **exact** |
| `case/schema.sql` (MOD, additive `search_hits` table) | migration | — | `case/schema.sql` `known_file_matches` table | **exact** |
| `case/store.py::insert_search_hits/get_search_hits` (MOD) | store writer/reader | CRUD | `case/store.py::insert_known_matches`/`get_known_matches` (+ `insert_timeline_events`) | **exact** |
| `evidence/filesystem.py::iter_unallocated_blocks` (MOD, seam) | seam helper | streaming | `evidence/filesystem.py::allocated_data_blocks` + `enumerate_volumes` | **exact** |
| `cli/main.py::logs`/`search` + `analyze --logs/--search` (MOD) | route/CLI | request-response | `cli/main.py::recover` + `analyze` opt-in flags | **exact** |
| `core/analyze.py` (MOD, wire `--logs`/`--search`) | orchestrator | pipeline | `core/analyze.py::run_analyze` opt-in `recover`/`filter_requested` | **exact** |
| `report/assemble.py` (MOD, log-findings + search-results sections) | component | transform | `report/assemble.py` existing timeline/known-filter sections | role-match (in-file) |

---

## Shared Patterns

These cross-cutting patterns apply to MULTIPLE new files. Apply them everywhere noted before reading the per-file assignments.

### Shared 1 — Orchestrator skeleton (two-arm audit + sole-writer + read-only re-assert)
**Source:** `src/pyautopsy/core/recover.py` (lines 336–570) and `src/pyautopsy/core/knownfiles.py` (lines 93–274)
**Apply to:** `core/logs.py::run_logs`, `core/search.py::run_search`

The mandatory shape (asserted across the test suite). From `core/knownfiles.py`:
```python
_EXPECTED_FILTER_ERRORS: tuple[type[BaseException], ...] = (
    FilterError, OSError, sqlite3.Error,
)
# run_recover adds: integrity.MountedSourceError, integrity.IntegrityError,
#                   ImageOpenError, FilesystemError  (when it opens the image)

def run_X(case_dir, *, evidence_source_id=None, ...) -> XResult:
    case_path = Path(case_dir).resolve()
    try:
        store = CaseStore.open(case_path)
    except FileNotFoundError as exc:
        raise XError(f"no case database under {case_path}; run `pyautopsy ingest` first") from exc
    audit = AuditLog(case_path)
    audit.write("X.start", case_dir=str(case_path), ...)
    try:
        source_id = evidence_source_id if evidence_source_id is not None else _latest_evidence_source_id(store)
        # ... work ...
        with store.transaction():
            store.insert_<rows>(rows)          # SOLE writer, ONE transaction (WR-01)
        audit.write("X.end", outcome="SUCCESS", evidence_source_id=source_id, ...)
    except _EXPECTED_X_ERRORS as exc:          # expected → .error FAIL + re-raise
        audit.write("X.error", outcome="FAIL", error=str(exc), error_type=type(exc).__name__)
        raise
    except Exception as exc:                   # bug → DISTINCT .crashed
        audit.write("X.crashed", outcome="FAIL", error=str(exc), error_type=type(exc).__name__)
        raise
    finally:
        store.close()
    return XResult(...)   # analytical counts ONLY — no wall-clock (CLI-02/P3)
```
When the orchestrator opens the image (run_logs / run_search do), copy `run_recover`'s
double `integrity.assert_source_not_mounted(image_path)` (once before open at recover.py:378,
once after open at recover.py:411) and the `handle = image_seam.open_image(image_path)` /
`try: ... finally: handle.close()` frame (recover.py:408–531).

The `_latest_evidence_source_id` helper is **identical** in both analogs (recover.py:273–283,
knownfiles.py:80–90) — copy verbatim, swap the error class.

### Shared 2 — Result dataclass (reproducible counts, no wall-clock)
**Source:** `core/recover.py::RecoverResult` (199–246), `core/knownfiles.py::FilterResult` (49–67)
**Apply to:** `core/logs.py::LogsResult`, `core/search.py::SearchResult`
`@dataclass(frozen=True, slots=True)` carrying analytical counts only (e.g. `events_parsed`,
`auth_events`, `hits`, `unallocated_hits`) + `evidence_source_id`. NEVER a timestamp — the
reproducibility test compares two runs.

### Shared 3 — CaseStore is the SOLE DB writer; store owns ordering
**Source:** `case/store.py` (whole class); `core/knownfiles.py` docstring (16–23)
**Apply to:** all of `core/logs.py`, `core/search.py`, `case/store.py` new methods
No raw SQL outside `case/store.py`. Never re-sort in the orchestrator — the store's
`ORDER BY` is the single ordering source (D-41). New `insert_*` methods call
`_commit_unless_in_transaction()` so they compose inside one outer `store.transaction()`.

### Shared 4 — No pytsk3/pyewf in `log/` or `search/` (seam allowlist, D-14)
**Source:** `core/recover.py` docstring (30–33), `core/knownfiles.py` docstring (21–23)
**Apply to:** every file under `log/` and `search/`
ALL native access goes through `evidence/image.py` (byte seam) and `evidence/filesystem.py`
(FS seam) ONLY. `tests/test_seam_allowlist.py` fails the build otherwise. The new
`iter_unallocated_blocks` helper MUST live inside `evidence/filesystem.py` (it touches
`fs.info`), NOT in `search/`.

### Shared 5 — UTC honesty / naive-rejecting serialization
**Source:** `util/timeutil.py::iso_utc` (rejects naive), `core/walk.py::_macb_to_utc_iso`
**Apply to:** `log/timeresolve.py`, `log/normalize.py`
Every timestamp goes through `iso_utc(dt)` (raises on naive — structural SOUND-02 guard).
Never store an inferred time without a flag in `attributes` (the CR-01 silent-offset lesson).

---

## Pattern Assignments

### `core/logs.py` (orchestrator, event-driven pipeline) — `run_logs`

**Analog:** `src/pyautopsy/core/recover.py::run_recover` (the volume-loop + image-open variant).

**Imports pattern** (recover.py:40–63): copy the import block — `AuditLog`, `CaseStore`,
`evidence.filesystem as fs_seam`, `evidence.image as image_seam`, `evidence.integrity`,
`FilesystemError`, `ImageOpenError`. Add `from pyautopsy.case import TimelineEvent`.

**Core loop** (recover.py:401–531): copy the `for vol in fs_seam.enumerate_volumes(handle.image)`
frame with the `try: fs = fs_seam.open_fs(handle.image, volume_offset) except OSError: continue`
(D-20 encrypted-volume skip), then inside it: discover → parse (registry) → resolve-time →
normalize → append `TimelineEvent`s. Single `with store.transaction(): store.insert_timeline_events(events)`.

**Insert call — exact existing signature to reuse** (store.py:584):
```python
store.insert_timeline_events(rows: Iterable[TimelineEvent]) -> int
```

**file_id lookup (RESEARCH Open Q3):** find the log file's `files` row via `store.get_files(source_id)`
(store.py:418, id-order) path-match; if absent (standalone `logs` with no prior walk), set
`file_id=None` and keep the log path in `path`/`attributes` — mirrors recover's standalone design.

**Audit + two-arm split:** Shared 1. Error set:
`_EXPECTED_LOGS_ERRORS = (LogsError, integrity.MountedSourceError, integrity.IntegrityError, ImageOpenError, FilesystemError, OSError, sqlite3.Error)`.

---

### `core/search.py` (orchestrator, streaming pipeline) — `run_search`

**Analog:** `core/knownfiles.py::run_filter` (the hash/IOC arm) + `core/recover.py` (image-open + volume loop for the content/unallocated arm).

**IOC/hash arm — copy `run_filter` body verbatim** (knownfiles.py:185–240): iterate
`store.get_files(source_id)`, for each row with hashes call the reused filter API (see
`search/ioc.py` below), collect hits, write in one transaction. The store-owned ordering
discipline (knownfiles.py docstring 16–23) carries over directly.

**Content/unallocated arm:** open the image like recover (recover.py:408–531), loop volumes,
stream allocated file content (per-inode `read_random`) and unallocated blocks (new
`iter_unallocated_blocks` seam helper). Write `SearchHit` rows via the new `insert_search_hits`.

**Result:** `SearchResult` per Shared 2.

---

### `log/timeresolve.py` (utility, transform) — D-46 tz/year inference

**Analog:** `core/walk.py::_macb_to_utc_iso` (110–161) and `_macb_fields` (164–204) — **exact structural mirror**.

**The naive-wall-clock → flagged-UTC core to mirror** (walk.py:150–161):
```python
naive_wall = datetime.fromtimestamp(secs, tz=timezone.utc).replace(tzinfo=None)
dt = naive_wall.replace(tzinfo=walk_tz)   # interpret wall-clock IN host zone, then to UTC
# ...
return iso_utc(dt)                        # iso_utc raises on naive (SOUND-02 guard)
```
For RFC3164 you start from parsed naive components (not a TSK epoch), but the
`replace(tzinfo=host_tz)` → `iso_utc()` step is identical.

**The flagging convention to mirror** (walk.py:196–204): walk records
`attributes["time_precision"] = "local-time-inferred"` and `attributes["assumed_timezone"] = str(walk_tz)`.
D-46 records the same shape: `attributes["timestamp_source"]` (`"log:inferred-tz"` /
`"log:assumed-utc"`) + `assumed_timezone` and, for the year, `{"year_inferred": ..., "year_basis": ...}`.

**Provenance-label table** to mirror: walk.py:103–107 `_TIMESTAMP_SOURCE_BY_LABEL` — make a
sibling dict of log `timestamp_source` labels.

**Host-tz resolution (D-46):** read `/etc/localtime` symlink target + `/etc/timezone` text
through the FS seam (`walk_fs` surfaces entries; symlink-target access is RESEARCH assumption A5,
verify in Wave 0). Map `.../zoneinfo/<Zone>` → `ZoneInfo(<Zone>)`; fallback to UTC + warning flag.

---

### `log/normalize.py` (utility, transform) — → TimelineEvent (LOG-04)

**Analog:** `timeline/builder.py::_explode` (34–81) — **exact pure-transform mirror**.

**The actor-build honesty pattern to copy** (builder.py:50–56): build `actor` from ONLY
populated components — never emit literal `"user=None"`. builder.py does:
```python
parts: list[str] = []
if file_row.uid is not None: parts.append(f"uid={file_row.uid}")
if file_row.gid is not None: parts.append(f"gid={file_row.gid}")
actor = ",".join(parts) if parts else None
```
Mirror for log events: `actor = f"user={name}"` only when name is known, else `None` (WR-05).

**TimelineEvent construction — exact existing field set to populate** (models.py:206–219, builder.py:67–80):
```python
TimelineEvent(
    evidence_source_id=...,   # required int
    ts_utc=utc_iso,           # str, verbatim from timeresolve — never re-derived
    source=...,               # "auth" | "syslog" | "shell-history"
    event_type=...,           # the parsed action, or "log"
    volume_id=...,            # int (0 / source log file's volume)
    volume_offset=...,        # int (0 / source log file's offset)
    path=log_path,            # evidence-ref: the source log file path
    meta_addr=None,           # nullable — log events have no inode
    actor=...,                # "user=alice" or None
    action=...,               # D-47: now populated (reserved column)
    outcome=...,              # D-47: now populated
    file_id=...,              # FK to the log file's files row, or None
    attributes=attrs,         # timestamp_source, assumed_timezone/year, raw msg
)
```
Note: `action`/`outcome`/`file_id`/`meta_addr`/`actor` all default-None in the model, so
filesystem events leaving them blank and log events filling them is the designed-in path.

---

### `log/auth.py`, `log/syslog.py`, `log/shell_history.py` (parsers, transform)

**Analog:** No in-repo text-line parser exists; closest convention is
`filter/hashsets.py::parse_hash_set` (41–73) — the **tolerant line-iteration style** to copy:
```python
for raw_line in text.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):   # skip blanks/comments
        continue
    # ... per-line parse; a malformed line is SKIPPED, never aborts the whole parse
```
For the parsers: a line that matches no pattern still becomes an event with `action=None` and
the raw msg in `attributes` (RESEARCH Pattern 4) — never silently dropped.

**RFC3164/RFC5424 grammar + auth taxonomy:** RESEARCH §Pattern 2 (compiled `re` for both line
formats) and §Pattern 4 (the `AUTH_PATTERNS` action/outcome list — honest, observed-line-only).

**Decode discipline (Security V5):** decode evidence bytes `utf-8`/`errors="replace"` (mirrors
`FileEntry.name` handling, filesystem.py:193) — data only, never a write path.

**shell_history.py (Pitfall 2):** detect zsh extended (`: <ts>:<dur>;cmd`) / bash `#<epoch>`
pairs; otherwise NO per-line time → emit with `ts_utc` = log file mtime, flag
`{"ts_basis": "file-mtime-fallback; no per-line timestamp"}` + a tamperability finding (D-44).

---

### `log/discover.py` (service, file-I/O) — locate + order rotated/gz log sets

**Analog:** `evidence/filesystem.py::walk_fs` (673+, enumeration source) + `core/recover.py`
volume loop. Pure logic over seam outputs — **MUST NOT import pytsk3** (Shared 4).

**Reading bytes (incl. gz) through the seam** — reuse the `FileEntry.read_random` closure
(filesystem.py:217, `(offset, size) -> bytes`). RESEARCH §Code Example:
```python
raw = entry.read_random(0, entry.size) if entry.read_random else b""
if entry.name.endswith(".gz"):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz: return gz.read()
```
**Ordering (Pitfall 4):** group by base name, sort **oldest→newest** (highest numeric suffix
first; `.gz` before non-gz of same index; live file last); handle numeric and `dateext`
suffixes; surface a "log completeness" finding. Deterministic order is load-bearing for CR-01
(Pitfall 3): fixed file order → fixed `insert_timeline_events` order → stable `id` tiebreak.

---

### `log/registry.py` (registry/protocol, EXT-01)

**Analog:** No formal registry exists yet; the closest *convention* is the producer pattern in
`timeline/builder.py` (each producer parse→emit `TimelineEvent`→insert) and the public-alias
style (`builder.py:85` `explode = _explode`). Discretion (RESEARCH): define a small
`LogParser` `Protocol` (`name`, `matches(path) -> bool`, `parse(text, ctx) -> Iterable[ParsedRecord]`)
+ a registry list iterated in **declared order** (determinism, Pitfall 3). Keep it minimal —
the three parsers register uniformly; future formats add without touching `core/logs.py`.

---

### `search/ioc.py` (service, match) — SEARCH-02

**Analog:** `core/knownfiles.py::run_filter` (93–274) + `filter/hashsets.py` — **exact reuse**.

**Existing hash-matching API to reuse verbatim:**
```python
filter.hashsets.parse_hash_set(text: str) -> dict[str, set[str]]            # hashsets.py:41
filter.hashsets.custom_match(parsed, sense, list_name, *, md5, sha1, sha256) # hashsets.py:76
    -> dict[str, str] | None        # {"source","list","sense","matched_on"}
filter.nsrl.open_nsrl(path: str) -> tuple[sqlite3.Connection, str]           # nsrl.py:47
filter.nsrl.nsrl_match(conn, table, *, md5, sha1, sha256) -> dict | None     # nsrl.py:99
```
**Hash-hit recording** reuses `KnownMatch` (models.py:254–283) + `store.insert_known_matches`
(store.py:668). The IOC *string-term* arm is a sibling parser to `parse_hash_set` (same
skip-`#`/blank tolerance), feeding literal/regex terms to the content scanner.

**UTF-8 list guard to copy** (knownfiles.py:169–175): wrap `read_text(encoding="utf-8")` to
re-raise `UnicodeDecodeError` as a clean operator-error (`SearchError`), not a `.crashed` bug.

---

### `search/content.py` (service, streaming) — SEARCH-01 [NO single analog — composed]

**Composed from two verified seam primitives** (this is the one genuinely new capability):

**Byte seam** (image.py:152): `handle.read(offset: int, size: int) -> bytes` (read-only).
**Allocated-block set** (filesystem.py:537): `allocated_data_blocks(fs) -> frozenset[int]`.
**New seam helper** `iter_unallocated_blocks` (see below) yields `(block_index, bytes)` for
blocks NOT in the allocated set — keeping ALL pytsk3 inside the seam (D-14).

**Allocated/file content:** per-inode `FileEntry.read_random` (filesystem.py:217), streamed.
**Unallocated:** the new generator. RESEARCH §"Streaming unallocated scan" example:
```python
window = carry + data
for m in pattern.finditer(window):
    abs_off = vol.offset + i * block_size - len(carry) + m.start()
    yield i, abs_off, m.group(0)
carry = window[-MAX_OVERLAP:]   # boundary-spanning match guard (Pitfall 5)
```
Stream in chunks, never slurp (PERF-01). Carry `max_term_len-1` overlap; dedupe overlap hits;
report **absolute** offset (file-relative for content, image/volume-relative for unallocated).

---

### `evidence/filesystem.py::iter_unallocated_blocks` (seam helper) [MODIFY seam]

**Analog:** `allocated_data_blocks` (537–565) and `enumerate_volumes` (568–610) in the SAME file
— **exact pattern**. RESEARCH Open Q2 recommends a single generator (not leaking block geometry):
```python
def iter_unallocated_blocks(handle, fs, vol) -> Iterator[tuple[int, bytes]]:
    """Yield (block_index, bytes) for blocks NOT owned by allocated files."""
    # block geometry from fs.info.block_size (cf. enumerate_volumes:599 vol.info.block_size,
    # allocated_data_blocks reads fs.info.first_inum/last_inum:554-555)
    # allocated set via allocated_data_blocks(fs); complement read via handle.read(...)
```
Keeps `fs.info` access inside the seam; hands `search/content.py` a clean
`(block_index, bytes)` stream. Mirror the seam's frozenset/plain-int export convention.

---

### `case/models.py::SearchHit` (model) [MODIFY, additive]

**Analog:** `case/models.py::KnownMatch` (254–283) — **exact**: `@dataclass(frozen=True, slots=True)`,
typed core columns + `attributes: dict[str, Any] = field(default_factory=dict)` + `id: int | None = None`.
RESEARCH Open Q1 proposed columns: `evidence_source_id, file_id (nullable), region
(allocated|unallocated|metadata), term, term_kind (literal|regex|ioc|hash), volume_id,
volume_offset, byte_offset, block_index (nullable), context (bounded snippet), attributes, id`.

---

### `case/schema.sql` (migration) [MODIFY, additive `search_hits` table]

**Analog:** the `known_file_matches` table (schema.sql:135–146) — **exact**: typed columns +
`attributes TEXT NOT NULL DEFAULT '{}'`, FK to `files (id)` for the nullable `file_id`, a
`CREATE INDEX` matching the read `ORDER BY`. The ONLY schema change in the phase (D-47:
`timeline_events` is untouched). Schema is applied via `executescript` on store create
(store.py:101–102) — additive `CREATE TABLE IF NOT EXISTS` needs no migration runner.

---

### `case/store.py::insert_search_hits` / `get_search_hits` (writer/reader) [MODIFY]

**Analog:** `insert_known_matches`/`get_known_matches` (store.py:668–713) and
`insert_timeline_events`/`get_timeline_events` (store.py:584–664) — **exact**.

**The four pieces to copy (lockstep, WR-01)** — mirror store.py:810–885:
1. `_SEARCH_HIT_COLUMNS: tuple[str, ...]` (cf. `_KNOWN_MATCH_COLUMNS:858`)
2. `_SEARCH_HIT_INSERT_SQL = "INSERT INTO search_hits (...) VALUES (...)"` (cf. :867)
3. `_search_hit_params(hit) -> tuple[Any, ...]` with `json.dumps(hit.attributes, sort_keys=True)` (cf. :876)
4. insert method body (cf. :668–688):
```python
params = [_search_hit_params(row) for row in rows]
if params:
    self.connection.executemany(_SEARCH_HIT_INSERT_SQL, params)
self._commit_unless_in_transaction()
return len(params)
```
**Read ordering (store owns it, D-41)** — mirror `get_known_matches` ORDER BY (store.py:711+).
RESEARCH Open Q1 total order: `volume_id, volume_offset, byte_offset, term, id` (trailing
surrogate `id` is the insertion-deterministic final tiebreak, exactly as timeline/known-match do).
Use `_load_attributes(row["attributes"])` (store.py:888) when reconstructing the model.

---

### `cli/main.py` — `logs` / `search` subcommands + `analyze --logs/--search` [MODIFY]

**Analog:** the `recover` command (main.py:229–340) + the `analyze` opt-in flags.

**Opt-in flag + error-mapping pattern to copy** (main.py:301–324): call the orchestrator, map
the expected error set to a clean non-zero exit, then run the opt-in arm only when the flag is
supplied. Note BL-02 (main.py:317–324): `sqlite3.Error` is NOT an `OSError` — catch it
explicitly so a bad IOC/NSRL DB exits cleanly. Reuse `_hash_sets(...)` (main.py:47) for the
hash-set pairing in `search`.

**`analyze` wiring** — mirror `run_analyze`'s opt-in gate (analyze.py:174 `recover: bool`,
:253 `filter_requested`, :283/:294 the `if recover:` / `if filter_requested:` arms): add
`logs: bool` and `search: str | None` that run `run_logs`/`run_search` ONLY when set, keeping
default `analyze` byte-identical to the Phase-4 baseline (CLI-02, D-48). Echo a deterministic
summary block like recover's (main.py:326–340).

---

### `core/analyze.py` (orchestrator) [MODIFY] + `report/assemble.py` [MODIFY]

**analyze.py:** add the `--logs`/`--search` opt-in arms next to the existing `recover`/`filter`
arms (analyze.py:283–299), forwarding `evidence_source_id=source_id`. Record the new flags in
the `analyze.start` audit (analyze.py:254–264). Keep all counts in `AnalyzeResult` (no wall-clock).

**assemble.py:** add log-findings + search-results sections next to the existing
timeline/known-filter sections. **Body byte-determinism (Pitfall 6):** read through store-owned
total orders only (`get_timeline_events` for the super-timeline = TIME-02, the new
`get_search_hits`); NO `utc_now()` in the body; volatile run metadata stays in the
`reports/run_metadata.json` sidecar (the pattern `run_analyze` already uses, analyze.py:185).

---

## Key existing signatures the planner will reference (quick index)

| Symbol | File:line | Signature / shape |
|--------|-----------|-------------------|
| `TimelineEvent` | models.py:169 | `evidence_source_id, ts_utc, source, event_type, volume_id, volume_offset, path, meta_addr=None, actor=None, action=None, outcome=None, file_id=None, attributes={}, id=None` |
| `KnownMatch` | models.py:255 | `file_id, source, matched_on, list_name=None, sense=None, attributes={}, id=None` |
| `CaseStore.insert_timeline_events` | store.py:584 | `(rows: Iterable[TimelineEvent]) -> int` |
| `CaseStore.get_timeline_events` | store.py:606 | `(evidence_source_id, *, limit=None) -> list[TimelineEvent]` (D-26 order = TIME-02) |
| `CaseStore.get_files` | store.py:418 | `(evidence_source_id) -> list[FileRow]` (id order, allocated+recovered) |
| `CaseStore.insert_known_matches` | store.py:668 | `(rows: Iterable[KnownMatch]) -> int` |
| `CaseStore.transaction` | store.py:157 | `@contextmanager` — one atomic unit; no nesting |
| `CaseStore.open` | store.py:111 | `(case_dir) -> CaseStore`; raises `FileNotFoundError` |
| `_macb_to_utc_iso` | walk.py:110 | `(secs, nano, *, is_fat, walk_tz) -> str | None` (D-16 mirror for D-46) |
| `builder._explode` | builder.py:34 | `(file_row) -> list[TimelineEvent]` (normalize mirror) |
| `parse_hash_set` | hashsets.py:41 | `(text) -> dict[str, set[str]]` |
| `custom_match` | hashsets.py:76 | `(parsed, sense, list_name, *, md5, sha1, sha256) -> dict | None` |
| `open_nsrl` / `nsrl_match` | nsrl.py:47/99 | `(path)->(conn,table)` / `(conn,table,*,md5,sha1,sha256)->dict|None` |
| `walk_fs` | filesystem.py:673 | `(fs, volume_id, volume_offset, ...) -> Iterator[FileEntry]` |
| `FileEntry.read_random` | filesystem.py:217 | `(offset, size) -> bytes | None` (per-file content reader) |
| `allocated_data_blocks` | filesystem.py:537 | `(fs) -> frozenset[int]` |
| `enumerate_volumes` | filesystem.py:568 | `(img) -> Iterator[VolumeEntry]` (offset/len/desc) |
| `open_fs` | filesystem.py:613 | `(img, offset) -> FS_Info` (OSError = D-20 encrypted) |
| `fs_type_int` | filesystem.py:402 | `(fs) -> int` |
| `ImageHandle.read` | image.py:152 | `(offset, size) -> bytes` (raw read-only byte seam) |
| `image_seam.open_image` | image.py:266 | `(path) -> ImageHandle` |
| `iso_utc` | util/timeutil.py | `(dt) -> str`; raises on naive (SOUND-02 guard) |

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `search/content.py` (the streaming literal/regex scan over allocated + **unallocated** + file content) | service | streaming | No existing streaming-scan code in the repo. It is *composed* from two verified seam primitives (`ImageHandle.read` + `allocated_data_blocks`/the new `iter_unallocated_blocks`) and RESEARCH §"Streaming unallocated scan" pseudocode. pytsk3 exposes no block-flag/`block_walk` API (verified) — the derive-allocated-set + raw-byte-read workaround is the only option. Planner should follow RESEARCH Pattern + Pitfall 5 here, not an in-repo file. |

All other 18 files map to a strong (mostly **exact**) in-repo analog above.

---

## Metadata

**Analog search scope:** `src/pyautopsy/{core,case,evidence,filter,timeline,report,cli,util}/`
**Files scanned:** core/recover.py, core/knownfiles.py, core/analyze.py, core/walk.py,
timeline/builder.py, case/models.py, case/store.py, case/schema.sql, evidence/filesystem.py,
evidence/image.py, filter/hashsets.py, filter/nsrl.py, cli/main.py (13 read in full or targeted).
**Pattern extraction date:** 2026-05-31
