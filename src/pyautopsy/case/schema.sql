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
