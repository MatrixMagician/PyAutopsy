"""Dataclasses for the case store and audit log.

These are plain, frozen value objects mirroring the typed core columns of the
:mod:`pyautopsy.case.schema` tables. Every model carries an ``attributes`` dict
mapping to the table's JSON ``attributes`` column (D-02 blackboard pattern), so
later phases attach heterogeneous data without a schema migration.

Timestamp fields are UTC ISO-8601 strings (D-10) sourced from
:mod:`pyautopsy.util.timeutil`; ``None`` means "not yet known".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Case", "EvidenceSource", "AuditEvent"]


@dataclass(frozen=True, slots=True)
class Case:
    """A case / chain-of-custody record (REPORT-01).

    Args:
        name: Human-readable case name.
        examiner: Name of the examiner accountable for this case.
        notes: Optional free-text intake notes.
        created_utc: UTC ISO-8601 creation timestamp; assigned by the store on
            insert when ``None``.
        pyautopsy_version: Tool version recorded for the COC record; assigned by
            the store on insert when ``None``.
        attributes: Heterogeneous JSON-serialisable extra data (D-02).
        id: Surrogate primary key; ``None`` until persisted.
    """

    name: str
    examiner: str
    notes: str | None = None
    created_utc: str | None = None
    pyautopsy_version: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    """Per-evidence acquisition + integrity metadata (REPORT-01).

    Args:
        case_id: Owning case id (FK into ``cases``).
        evidence_id: Examiner-supplied evidence identifier.
        path: Acquisition source path of the image.
        image_type: Image container type (e.g. ``raw`` or ``ewf``).
        sha256: SHA-256 of the source image, when computed.
        md5: MD5 of the source image, when computed.
        byte_size: Total size of the source image in bytes.
        acquired_utc: UTC ISO-8601 acquisition timestamp.
        tsk_version: The Sleuth Kit (libtsk) version used.
        attributes: Heterogeneous JSON-serialisable extra data (D-02).
        id: Surrogate primary key; ``None`` until persisted.
    """

    case_id: int
    evidence_id: str
    path: str
    image_type: str
    sha256: str | None = None
    md5: str | None = None
    byte_size: int | None = None
    acquired_utc: str | None = None
    tsk_version: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A single structured audit-log event (REPORT-02).

    The event is serialised to one JSON line in ``logs/audit.jsonl``. ``ts`` is a
    UTC ISO-8601 timestamp assigned by the writer when ``None``; ``fields``
    carries the action-specific payload (inputs, hashes, parameters, versions,
    outcome, errors).

    Args:
        action: The action name (e.g. ``"ingest.open"``).
        fields: Action-specific JSON-serialisable payload.
        ts: UTC ISO-8601 timestamp; assigned by the writer when ``None``.
    """

    action: str
    fields: dict[str, Any] = field(default_factory=dict)
    ts: str | None = None
