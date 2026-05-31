-- PyAutopsy case-store schema (D-02/D-03).
--
-- Every table follows the blackboard pattern: typed core columns for the fields
-- we know up front, plus a single JSON ``attributes`` TEXT column so later
-- producers (metadata, findings, log events) attach heterogeneous data WITHOUT
-- forcing a migration. Timestamps are stored as UTC ISO-8601 strings (D-10).
-- Run metadata (timestamps, status) lives in ``run_log``, segregated from the
-- analytical chain-of-custody rows (PITFALLS P3).

-- Chain-of-custody / case metadata (REPORT-01).
CREATE TABLE IF NOT EXISTS cases (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    examiner          TEXT    NOT NULL,
    created_utc       TEXT    NOT NULL,
    pyautopsy_version TEXT    NOT NULL,
    notes             TEXT,
    attributes        TEXT    NOT NULL DEFAULT '{}'
);

-- Per-evidence acquisition / integrity record (REPORT-01).
CREATE TABLE IF NOT EXISTS evidence_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      INTEGER NOT NULL REFERENCES cases (id),
    evidence_id  TEXT    NOT NULL,
    path         TEXT    NOT NULL,
    image_type   TEXT    NOT NULL,
    sha256       TEXT,
    md5          TEXT,
    byte_size    INTEGER,
    acquired_utc TEXT,
    tsk_version  TEXT,
    attributes   TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_evidence_sources_case_id
    ON evidence_sources (case_id);

-- Segregated run / processing-stage metadata (PITFALLS P3); also the optional
-- SQLite mirror target for the JSONL audit log (Claude's Discretion, D-09).
CREATE TABLE IF NOT EXISTS run_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      INTEGER REFERENCES cases (id),
    stage        TEXT    NOT NULL,
    started_utc  TEXT,
    finished_utc TEXT,
    status       TEXT,
    detail       TEXT,
    attributes   TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_run_log_case_id
    ON run_log (case_id);

-- Per-file inventory produced by the filesystem walk (META-01..05, D-15/D-18).
--
-- Typed core columns carry the fields the walk knows up front (path, size,
-- inode/MFT address, allocated/unallocated status, volume id/offset). The
-- MACB/ownership/hash/file-type columns are declared now (interface-first) but
-- stay NULL until Plans 02-02/02-03 populate them; ``attributes`` is the D-02
-- JSON blackboard (nano fields, local-time-inferred flag, assumed_timezone,
-- hash-skip reason, encryption hint).
CREATE TABLE IF NOT EXISTS files (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_source_id INTEGER NOT NULL REFERENCES evidence_sources (id),
    -- (WR-06) The walk ALWAYS tags every row with its source volume id + byte
    -- offset (D-15), and FileRow types both as non-optional ``int``. Declared
    -- NOT NULL so the column contract matches the model: a NULL here can never
    -- silently construct a FileRow with None in an int field.
    volume_id          INTEGER NOT NULL,
    volume_offset      INTEGER NOT NULL,
    path               TEXT    NOT NULL,
    name               TEXT    NOT NULL,
    parent_addr        INTEGER,
    meta_addr          INTEGER,
    fs_type            TEXT,
    size               INTEGER,
    allocated          INTEGER,
    meta_type          TEXT,
    uid                INTEGER,
    gid                INTEGER,
    mode               INTEGER,
    md5                TEXT,
    sha1               TEXT,
    sha256             TEXT,
    mtime_utc          TEXT,
    atime_utc          TEXT,
    ctime_utc          TEXT,
    crtime_utc         TEXT,
    timestamp_source   TEXT,
    file_type          TEXT,
    attributes         TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_files_evidence_source_id
    ON files (evidence_source_id);

-- Explicit known-limitation findings for volumes the walk could not open
-- (encrypted/unsupported — FS_Info OSError, D-20). Recording the volume rather
-- than emitting empty/garbage ``files`` rows keeps the inventory honest.
CREATE TABLE IF NOT EXISTS volume_limitations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_source_id INTEGER NOT NULL REFERENCES evidence_sources (id),
    volume_id          INTEGER,
    volume_offset      INTEGER,
    detected_desc      TEXT,
    reason             TEXT,
    attributes         TEXT    NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_volume_limitations_evidence_source_id
    ON volume_limitations (evidence_source_id);

-- Normalized forensic timeline events — the shared event model (D-23/D-24).
--
-- This is the spine Phase 3 reads back for the timeline and report, and the
-- table Phase 5 log producers will write into and TIME-02 will merge into a
-- super-timeline — no schema churn, no backfill. Filesystem MACB times are the
-- first producer: one event per populated MACB timestamp (D-24; a 0-epoch ⇒
-- None ⇒ no event propagates from the walk). ``event_type`` ∈
-- {modified, accessed, changed, born}; ``ts_utc`` is the UTC ISO-8601 string
-- copied verbatim from the file row (never re-derived). ``volume_id`` and
-- ``volume_offset`` are NOT NULL mirroring ``files`` (WR-06) since every
-- filesystem event is tagged with its source volume. ``file_id`` is nullable
-- so Phase 5 log events (which lack a file) reuse the table. ``actor``/
-- ``action``/``outcome`` are the D-23 forensic-event slots (fs events fill
-- ``actor`` with uid/gid; ``action``/``outcome`` are reserved for log
-- producers). ``attributes`` is the D-02 JSON blackboard.
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
