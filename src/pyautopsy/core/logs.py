"""The log-parsing orchestrator (LOG-01/LOG-04/TIME-02, D-45/D-46/D-47).

:func:`run_logs` is the sibling of :func:`pyautopsy.core.recover.run_recover`: it
composes the proven lower tiers into one forensically-sound operation that turns
an opened evidence image's on-disk logs into normalized
:class:`~pyautopsy.case.TimelineEvent` rows in the shared ``timeline_events``
table — so the existing D-26 ordered read (:meth:`CaseStore.get_timeline_events`)
becomes the TIME-02 super-timeline with NO new ordering code (D-47). In order:

1. **Re-assert the read-only guard** before any access (D-05/P1) and again after
   the image open — logs are read, never mounted or written.
2. **Open the case store** (a prior ``ingest`` created it) and resolve the
   evidence source to attach events to.
3. **Per volume** (encrypted/unsupported → skip, D-20), derive the host timezone
   once (``/etc/localtime`` symlink → ``/etc/timezone`` text, D-46), discover the
   rotated/gz log sets oldest→newest (D-45), parse each member through the EXT-01
   registry, time-resolve each record with honest tz/year flagging (D-46),
   normalize to a :class:`TimelineEvent` (LOG-04), and resolve its ``file_id`` via
   a ``get_files`` path-match (``None`` when standalone).
4. **Persist** all events through ONE ``store.transaction()`` /
   ``insert_timeline_events`` (CaseStore is the sole writer, WR-01).
5. **Audit** with the mandatory two-arm expected-vs-crashed split.

Events are inserted in encounter order (oldest→newest files, registry-declared
parser order, file line order) so the store's surrogate-``id`` tiebreak is
insertion-deterministic — the CR-01 tied-second guarantee (Pitfall 3).

This module is part of the orchestration tier and **imports no pytsk3/pyewf**
(D-14): all native access is behind the two seam modules. The result carries
analytical counts only — never wall-clock (CLI-02).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore, TimelineEvent
from pyautopsy.evidence import filesystem as fs_seam
from pyautopsy.evidence import image as image_seam
from pyautopsy.evidence import integrity
from pyautopsy.evidence.filesystem import FilesystemError
from pyautopsy.evidence.image import ImageOpenError
from pyautopsy.log import auth as _auth  # noqa: F401  (registers AuthParser, EXT-01)
from pyautopsy.log import discover, normalize, timeresolve
from pyautopsy.log.registry import ParsedRecord, iter_parsers
from pyautopsy.timeline.builder import explode

__all__ = ["LogsError", "LogsResult", "run_logs"]


class LogsError(Exception):
    """Raised when log parsing cannot proceed for a non-integrity reason.

    Chiefly: the case directory has no ``case.db`` (ingest was never run) or no
    evidence source to attach events to. Integrity / read-only-boundary failures
    surface as :class:`~pyautopsy.evidence.integrity.MountedSourceError` /
    :class:`~pyautopsy.evidence.integrity.IntegrityError` instead.
    """


# The operational exception set log parsing legitimately expects (mirrors
# recover._EXPECTED_RECOVER_ERRORS). Recorded as ``logs.error`` FAIL and
# re-raised; anything OUTSIDE this set is a genuine bug recorded under
# ``logs.crashed``. ``sqlite3.Error`` is listed explicitly because it is NOT an
# ``OSError`` (BL-02) — a corrupt case DB must exit cleanly, not crash.
_EXPECTED_LOGS_ERRORS: tuple[type[BaseException], ...] = (
    LogsError,
    integrity.MountedSourceError,
    integrity.IntegrityError,
    ImageOpenError,
    FilesystemError,
    OSError,
    sqlite3.Error,
)


@dataclass(frozen=True, slots=True)
class LogsResult:
    """The analytical outcome of a log-parsing run (reproducible counts only).

    Carries only analytical content — never wall-clock — so the CLI prints a
    deterministic summary and the reproducibility test can compare two runs
    (CLI-02, mirrors :class:`~pyautopsy.core.recover.RecoverResult`).

    Attributes:
        evidence_source_id: The evidence source the events were attached to.
        events_parsed: Total :class:`TimelineEvent` rows written.
        auth_events: How many of those came from the auth parser.
        log_sets: How many rotated log sets were discovered + parsed.
    """

    evidence_source_id: int
    events_parsed: int
    auth_events: int
    log_sets: int


def _latest_evidence_source_id(store: CaseStore) -> int:
    """Return the latest ``evidence_sources`` id, or raise :class:`LogsError`."""
    row = store.connection.execute(
        "SELECT id FROM evidence_sources ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise LogsError(
            "no evidence source in the case; run `pyautopsy ingest` first so log "
            "parsing has an evidence_sources row to attach events to"
        )
    return int(row["id"])


def _build_path_index(store: CaseStore, source_id: int) -> dict[str, int]:
    """Map each known file path → its ``files`` row id for the file_id lookup.

    Open Q3: a log event's ``file_id`` is the FK to the log FILE's ``files`` row.
    When no prior walk inventoried the file (standalone ``logs``), the path is
    simply absent here and the event keeps ``file_id=None`` with the log path in
    ``path``/``attributes`` (mirrors recover's standalone design).
    """
    index: dict[str, int] = {}
    for row in store.get_files(source_id):
        if row.id is not None and row.path is not None and row.path not in index:
            index[row.path] = row.id
    return index


def _seed_year_from_mtime(rows_by_path: dict[str, Any], member_path: str) -> int:
    """Seed the RFC3164 year from a member's mtime (falls back to its enclosing set)."""
    row = rows_by_path.get(member_path)
    mtime = getattr(row, "mtime", 0) if row is not None else 0
    if mtime:
        return datetime.fromtimestamp(mtime, tz=timezone.utc).year
    # No usable mtime: anchor to the current UTC year (still flagged as inferred).
    return datetime.now(timezone.utc).year


def _resolve_records_to_events(
    records: list[ParsedRecord],
    *,
    source: str,
    log_path: str,
    evidence_source_id: int,
    file_id: int | None,
    host_tz: Any,
    tz_basis: str,
    seed_year: int,
    volume_id: int,
    volume_offset: int,
) -> list[TimelineEvent]:
    """Time-resolve a member's parsed records, then normalize to events (D-46/LOG-04).

    Records with a parseable RFC3164 head get a per-set year-inferred UTC instant
    (honest tz + year flags); records with no parseable timestamp fall back to the
    member's seed-year January 1 with an explicit basis flag rather than being
    dropped (the line is still evidence).
    """
    comps: list[tuple[int, int, int, int, int] | None] = [
        timeresolve.rfc3164_components(r.raw_timestamp) if r.raw_timestamp else None
        for r in records
    ]
    datable = [c for c in comps if c is not None]
    year_flags = timeresolve.infer_years(datable, seed_year=seed_year)
    year_iter = iter(year_flags)

    events: list[TimelineEvent] = []
    for record, comp in zip(records, comps, strict=True):
        if comp is not None:
            year, yflags = next(year_iter)
            naive = timeresolve.naive_from_components(year, comp)
            utc_iso, tz_flags = timeresolve.to_utc(naive, host_tz)
            attrs: dict[str, Any] = {**record.attributes, **tz_flags, **yflags}
        else:
            # No per-line timestamp: anchor to the seed year's start, flagged.
            naive = datetime(seed_year, 1, 1)  # noqa: DTZ001 (naive by design)
            utc_iso, tz_flags = timeresolve.to_utc(naive, host_tz)
            attrs = {
                **record.attributes,
                **tz_flags,
                "ts_basis": "file-mtime-fallback; no per-line timestamp",
            }
        attrs["tz_resolution"] = tz_basis
        events.append(
            normalize.to_event(
                record,
                evidence_source_id=evidence_source_id,
                file_id=file_id,
                source=source,
                log_path=log_path,
                utc_iso=utc_iso,
                attrs=attrs,
                volume_id=volume_id,
                volume_offset=volume_offset,
            )
        )
    return events


def run_logs(
    image: str | os.PathLike[str],
    case_dir: str | os.PathLike[str],
    *,
    evidence_source_id: int | None = None,
) -> LogsResult:
    """Parse an image's logs into the shared super-timeline (LOG-01/04, TIME-02).

    See the module docstring for the full ordered pipeline. The source is opened
    read-only and never mounted or written; auth events are time-resolved with
    honest tz/year flags (D-46), normalized into the shared ``TimelineEvent``
    model (LOG-04), and merged into the existing get_timeline_events total order
    (TIME-02) — no new ordering code (D-47).

    Args:
        image: Path to the evidence image (raw/dd file or first E01 segment).
        case_dir: Existing case directory (created by a prior ingest).
        evidence_source_id: Which evidence source to attach events to; defaults to
            the latest ``evidence_sources`` row in the case.

    Returns:
        A :class:`LogsResult` with the analytical event counts.

    Raises:
        LogsError: If the case has no ``case.db`` or no evidence source.
        MountedSourceError: If the source path is a mounted filesystem (P1).
        ImageOpenError: If the image cannot be opened read-only.
    """
    image_path = Path(image).resolve()
    case_path = Path(case_dir).resolve()

    # (1) Re-assert the read-only / not-mounted guard before any access (D-05/P1).
    integrity.assert_source_not_mounted(image_path)

    # (2) Open the existing case store (ingest created it).
    try:
        store = CaseStore.open(case_path)
    except FileNotFoundError as exc:
        raise LogsError(
            f"no case database under {case_path}; run `pyautopsy ingest` first"
        ) from exc

    audit = AuditLog(case_path)
    audit.write("logs.start", image=str(image_path), case_dir=str(case_path))

    events_parsed = 0
    auth_events = 0
    log_sets = 0

    try:
        source_id = (
            evidence_source_id
            if evidence_source_id is not None
            else _latest_evidence_source_id(store)
        )
        path_index = _build_path_index(store, source_id)

        handle = image_seam.open_image(image_path)
        try:
            # (WR-02) Re-assert not-mounted after the open, before reading.
            integrity.assert_source_not_mounted(image_path)

            all_events: list[TimelineEvent] = []
            for vol in fs_seam.enumerate_volumes(handle.image):
                try:
                    fs = fs_seam.open_fs(handle.image, vol.offset)
                except OSError:
                    # (D-20) Encrypted/unsupported volume: nothing to parse here.
                    continue

                # (D-46) Derive the host zone ONCE per volume via the seam. Bind
                # ``fs`` explicitly so the reader closures capture THIS volume's
                # filesystem (not the loop variable by reference — B023).
                def _symlink(p: str, _fs: Any = fs) -> str | None:
                    return fs_seam.read_symlink_target(_fs, p)

                def _text(p: str, _fs: Any = fs) -> str | None:
                    return _read_text(_fs, p)

                host_tz, tz_basis = timeresolve.resolve_host_tz(
                    read_symlink=_symlink,
                    read_text=_text,
                )

                rows = list(
                    fs_seam.walk_fs(fs, vol.volume_id, vol.offset)
                )
                rows_by_path = {r.path: r for r in rows}

                for log_set in discover.discover_log_sets(rows):
                    log_sets += 1
                    set_events = _parse_log_set(
                        log_set,
                        rows_by_path=rows_by_path,
                        path_index=path_index,
                        source_id=source_id,
                        host_tz=host_tz,
                        tz_basis=tz_basis,
                        volume_id=vol.volume_id,
                        volume_offset=vol.offset,
                    )
                    all_events.extend(set_events)
                    auth_events += sum(1 for e in set_events if e.source == "auth")

                audit.write(
                    "logs.volume",
                    volume_id=vol.volume_id,
                    volume_offset=vol.offset,
                    tz_basis=tz_basis,
                )

            # (TIME-02/D-47) The super-timeline IS the existing get_timeline_events
            # read — log events sort in the SAME table/total order as filesystem
            # events. So the merged read needs the filesystem MACB events present.
            # Build them from the walk inventory ONCE (idempotent): only when the
            # source has no timeline events yet, so a prior `analyze`/build does
            # not get double-inserted. No new ordering code is added (D-47).
            fs_events: list[TimelineEvent] = []
            if not store.get_timeline_events(source_id, limit=1):
                for file_row in store.get_files(source_id):
                    fs_events.extend(explode(file_row))

            with store.transaction():
                if fs_events:
                    store.insert_timeline_events(fs_events)
                store.insert_timeline_events(all_events)
            events_parsed = len(all_events)
        finally:
            handle.close()

        audit.write(
            "logs.end",
            outcome="SUCCESS",
            evidence_source_id=source_id,
            events_parsed=events_parsed,
            auth_events=auth_events,
            log_sets=log_sets,
        )
    except _EXPECTED_LOGS_ERRORS as exc:
        audit.write(
            "logs.error",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    except Exception as exc:
        audit.write(
            "logs.crashed",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    finally:
        store.close()

    return LogsResult(
        evidence_source_id=source_id,
        events_parsed=events_parsed,
        auth_events=auth_events,
        log_sets=log_sets,
    )


def _read_text(fs: Any, path: str) -> str | None:
    """Read a small file's bytes via the seam and decode as text (DATA only)."""
    raw = fs_seam.read_file_bytes(fs, path)
    if raw is None:
        return None
    return raw.decode("utf-8", "replace")


def _parse_log_set(
    log_set: discover.LogSet,
    *,
    rows_by_path: dict[str, Any],
    path_index: dict[str, int],
    source_id: int,
    host_tz: Any,
    tz_basis: str,
    volume_id: int,
    volume_offset: int,
) -> list[TimelineEvent]:
    """Discover the parser, read+decode each member oldest→newest, resolve to events."""
    parser = next(
        (p for p in iter_parsers() if p.matches(log_set.basename)), None
    )
    if parser is None:
        return []

    events: list[TimelineEvent] = []
    for member in log_set.members:
        row = rows_by_path.get(member.path)
        reader = getattr(row, "read_random", None) if row is not None else None
        if reader is None:
            continue
        size = getattr(row, "size", 0) or 0
        raw = reader(0, size) if size else b""
        text = discover.decode_member(raw or b"", is_gz=member.is_gz)
        if not text:
            continue
        records = list(parser.parse(text))
        file_id = path_index.get(member.path)
        seed_year = _seed_year_from_mtime(rows_by_path, member.path)
        events.extend(
            _resolve_records_to_events(
                records,
                source=parser.name,
                log_path=member.path,
                evidence_source_id=source_id,
                file_id=file_id,
                host_tz=host_tz,
                tz_basis=tz_basis,
                seed_year=seed_year,
                volume_id=volume_id,
                volume_offset=volume_offset,
            )
        )
    return events
