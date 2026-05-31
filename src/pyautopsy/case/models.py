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

__all__ = [
    "Case",
    "EvidenceSource",
    "FileRow",
    "TimelineEvent",
    "VolumeLimitation",
    "AuditEvent",
]


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
class FileRow:
    """One inventoried filesystem entry produced by the walk (META-01..05).

    The required typed fields are the META-01 core the walk always knows: which
    evidence source + volume the entry came from, its path/name, inode/MFT
    address, allocated/unallocated status, declared meta-type and size. The
    optional fields (MACB/ownership/hash/file-type) default to ``None`` meaning
    "not yet known" — they are declared interface-first here but stay null until
    Plans 02-02/02-03 populate them. MACB times are UTC ISO-8601 strings (D-10)
    or ``None`` (``0`` epoch ⇒ "not recorded", never a fake 1970).

    Args:
        evidence_source_id: Owning evidence source id (FK into
            ``evidence_sources``).
        volume_id: Volume/partition id the entry was found in (D-15).
        volume_offset: Byte offset of that volume within the image (D-15).
        path: Full path of the entry within its filesystem.
        name: The entry's own name (decoded ``utf-8``/``errors="replace"``).
        parent_addr: Parent directory inode/MFT address, when known.
        meta_addr: The entry's inode/MFT address (META-01).
        fs_type: Filesystem type string (e.g. ``ext4``/``ntfs``/``fat``).
        size: Logical size in bytes, when known.
        allocated: ``True`` if both name + meta slots are allocated; ``False``
            for a deleted/unallocated entry (META-01/D-18).
        meta_type: Entry meta-type label (``reg``/``dir``/``lnk``/...).
        uid: Owning user id (META-03), when populated.
        gid: Owning group id (META-03), when populated.
        mode: POSIX permission/mode bits (META-03), when populated.
        md5: MD5 hex digest of the content (META-04), when populated.
        sha1: SHA-1 hex digest of the content (META-04), when populated.
        sha256: SHA-256 hex digest of the content (META-04), when populated.
        mtime_utc: Modified time as UTC ISO-8601 (META-02), or ``None``.
        atime_utc: Accessed time as UTC ISO-8601 (META-02), or ``None``.
        ctime_utc: Changed/metadata time as UTC ISO-8601 (META-02), or ``None``.
        crtime_utc: Created/born time as UTC ISO-8601 (META-02), or ``None``.
        timestamp_source: Origin of the MACB times (e.g. ``ext4:inode``).
        file_type: Content-signature file type (META-05), when populated.
        recovered: ``True`` on a recovered deleted/orphan row written by the
            recovery pass (RECOV-01, D-35); ``None`` for a normal walk row.
        confidence_tier: Recovery confidence label — current domain
            {``intact``, ``partial/overwritten``} (RECOV-03, D-30); ``None`` for a
            normal walk row. Free-form so future journal/carved tiers add no
            schema churn.
        recovered_path: The case-relative path the recovered bytes were written
            to under ``recovered/`` (D-33/D-34); ``None`` for a normal walk row.
        is_orphan: ``True`` when the recovered entry's parent directory is gone
            (RECOV-02); ``None`` for a normal walk row.
        attributes: Heterogeneous JSON-serialisable extra data (D-02), incl. the
            recovery tier rationale + per-fs caveats.
        id: Surrogate primary key; ``None`` until persisted.
    """

    evidence_source_id: int
    volume_id: int
    volume_offset: int
    path: str
    name: str
    meta_addr: int | None = None
    parent_addr: int | None = None
    fs_type: str | None = None
    size: int | None = None
    allocated: bool | None = None
    meta_type: str | None = None
    uid: int | None = None
    gid: int | None = None
    mode: int | None = None
    md5: str | None = None
    sha1: str | None = None
    sha256: str | None = None
    mtime_utc: str | None = None
    atime_utc: str | None = None
    ctime_utc: str | None = None
    crtime_utc: str | None = None
    timestamp_source: str | None = None
    file_type: str | None = None
    recovered: bool | None = None
    confidence_tier: str | None = None
    recovered_path: str | None = None
    is_orphan: bool | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One normalized forensic timeline event (D-23/D-24).

    This is the shared forensic-event model: the filesystem MACB explosion is
    the first producer (one event per populated MACB timestamp — a file with 4
    distinct times yields up to 4 events), and Phase 5 log producers will write
    the same shape into the same table for the TIME-02 super-timeline. The
    ``ts_utc`` sort key is the UTC ISO-8601 string copied **verbatim** from the
    walk's ``*_utc`` column — it is never re-derived from a raw epoch (the
    timezone/FAT/zero-epoch work is already done and tested in the walk).

    Args:
        evidence_source_id: Owning evidence source id (FK into
            ``evidence_sources``).
        ts_utc: Event timestamp as a UTC ISO-8601 string (D-10); the primary
            sort key of the D-26 total order. Copied verbatim from the source
            file row, never reformatted.
        source: Event source label (e.g. ``filesystem`` or
            ``filesystem:ext4``); future log producers use their own labels.
        event_type: The MACB kind — one of ``modified``/``accessed``/
            ``changed``/``born``; log producers use their own action types.
        volume_id: Volume/partition id the event's entry came from (D-15).
        volume_offset: Byte offset of that volume within the image (D-15).
        path: Full path of the entry the event belongs to (evidence-ref).
        meta_addr: The entry's inode/MFT address (part of the D-26 total order
            + evidence-ref); ``None`` when not applicable.
        actor: Actor attribution where known — for filesystem events the
            owning ``uid``/``gid`` (D-23); reserved otherwise.
        action: The action performed; reserved for Phase 5 log producers
            (filesystem timestamp events leave it ``None``).
        outcome: The action outcome; reserved for Phase 5 log producers.
        file_id: FK into ``files`` for filesystem events; ``None`` for log
            events that have no associated file (Phase 5).
        attributes: Heterogeneous JSON-serialisable extra data (D-02).
        id: Surrogate primary key; ``None`` until persisted.
    """

    evidence_source_id: int
    ts_utc: str
    source: str
    event_type: str
    volume_id: int
    volume_offset: int
    path: str
    meta_addr: int | None = None
    actor: str | None = None
    action: str | None = None
    outcome: str | None = None
    file_id: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    id: int | None = None


@dataclass(frozen=True, slots=True)
class VolumeLimitation:
    """A known-limitation finding for a volume the walk could not open (D-20).

    When ``FS_Info`` raises ``OSError`` on an encrypted/unsupported volume, the
    orchestrator records this row (volume id/offset + detected type + reason)
    and continues, rather than aborting the run or emitting empty ``files``
    rows. The ``attributes`` blackboard can carry an optional encryption hint
    (e.g. a likely LUKS/BitLocker magic-byte match).

    Args:
        evidence_source_id: Owning evidence source id (FK into
            ``evidence_sources``).
        volume_id: Volume/partition id that could not be opened.
        volume_offset: Byte offset of that volume within the image.
        detected_desc: Human-readable detected description (e.g. the partition
            type string from the volume system).
        reason: Why the volume could not be walked (e.g. the ``FS_Info``
            ``OSError`` message — "encrypted/unsupported volume").
        attributes: Heterogeneous JSON-serialisable extra data (D-02).
        id: Surrogate primary key; ``None`` until persisted.
    """

    evidence_source_id: int
    volume_id: int
    volume_offset: int
    detected_desc: str | None = None
    reason: str | None = None
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
