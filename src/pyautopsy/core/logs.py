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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore, LogFinding, TimelineEvent
from pyautopsy.core.epilogue import audited_step
from pyautopsy.errors import PyAutopsyError
from pyautopsy.evidence import filesystem as fs_seam
from pyautopsy.evidence import image as image_seam
from pyautopsy.evidence import integrity
from pyautopsy.log import PARSERS, discover, normalize, timeresolve
from pyautopsy.log.registry import ParsedRecord
from pyautopsy.timeline.builder import explode
from pyautopsy.util.timeutil import from_epoch_utc, iso_utc

__all__ = ["LogsError", "LogsResult", "run_logs"]

# Sort-to-END sentinel for events whose year could NOT be anchored to ANY mtime
# on the image (the epoch-fallback path, CR-02). ``get_timeline_events`` orders by
# ``ts_utc`` ASC (lexical on the ISO string), so a far-future instant places these
# undated artifacts at the TAIL of the presented chronology instead of the 1970
# FRONT, where they would otherwise masquerade as the "earliest activity" in a
# timeline the report presents as forensic truth. The instant itself is never real
# — every such event carries an explicit ``ts_basis`` / ``year_basis`` honesty
# flag in ``attributes`` saying the time is unresolved and the row is sorted out of
# the chronological view (the disclosure now reaches where the distortion appears).
_UNDATED_SORT_LAST_ISO = "9999-12-31T23:59:59+00:00"


class LogsError(PyAutopsyError):
    """Raised when log parsing cannot proceed for a non-integrity reason.

    Chiefly: the case directory has no ``case.db`` (ingest was never run) or no
    evidence source to attach events to. Integrity / read-only-boundary failures
    surface as :class:`~pyautopsy.evidence.integrity.MountedSourceError` /
    :class:`~pyautopsy.evidence.integrity.IntegrityError` instead.
    """




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
        findings_count: How many honesty-disclosure :class:`LogFinding` rows were
            persisted (D-44 tamperability + D-45 completeness).
    """

    evidence_source_id: int
    events_parsed: int
    auth_events: int
    log_sets: int
    findings_count: int = 0


def _latest_evidence_source_id(store: CaseStore) -> int:
    """Return the latest ``evidence_sources`` id, or raise :class:`LogsError`.

    Reads through the CaseStore (WR-02: no raw SQL outside the store boundary).
    """
    source_id = store.get_latest_evidence_source_id()
    if source_id is None:
        raise LogsError(
            "no evidence source in the case; run `pyautopsy ingest` first so log "
            "parsing has an evidence_sources row to attach events to"
        )
    return source_id


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


def _seed_year_from_mtime(
    rows_by_path: dict[str, Any], member_path: str
) -> tuple[int, str, bool]:
    """Deterministically seed the RFC3164 year from evidence only (CLI-02).

    Returns ``(year, basis, unresolved)``. The seed is derived ONLY from data on
    the image, so two runs of the same image always agree (CLI-02) — it never reads
    the analysis host's wall clock (the module docstring's "never wall-clock"
    promise). In precedence order:

    1. the member's own mtime year (the canonical RFC3164 anchor, D-46);
    2. the NEWEST mtime year across the whole walked file set, when the member
       itself has no usable mtime (still evidence-derived and reproducible);
    3. the Unix-epoch year (1970) as an explicit, honestly-flagged last resort when
       NOTHING on the image carries an mtime — never an invented current year.

    ``unresolved`` is ``True`` ONLY for case 3 (no mtime anywhere). The caller uses
    it to sort that member's events to the END of the ts_utc-ordered super-timeline
    instead of the 1970 FRONT, so an unanchored artifact never masquerades as the
    earliest activity (CR-02). The returned ``basis`` string is recorded on each
    event so the inference is never silent (SOUND-02 / the CR-01 honesty lesson).
    """
    row = rows_by_path.get(member_path)
    mtime = getattr(row, "mtime", 0) if row is not None else 0
    if mtime:
        year = datetime.fromtimestamp(mtime, tz=timezone.utc).year
        return year, "file mtime + rotation order", False

    # No usable member mtime: fall back to the NEWEST mtime anywhere in the walked
    # set (deterministic from the image alone — no wall clock, CLI-02).
    newest = max(
        (getattr(r, "mtime", 0) or 0 for r in rows_by_path.values()),
        default=0,
    )
    if newest:
        year = datetime.fromtimestamp(newest, tz=timezone.utc).year
        return year, "newest mtime in log set (member mtime absent)", False

    # Genuinely nothing to anchor to: use the Unix epoch year and SAY SO. We never
    # invent the analysis host's current year (that would break CLI-02 across a
    # New-Year boundary — the CR-02 wall-clock leak). Flag ``unresolved`` so the
    # caller sorts these events OUT of the chronological front (CR-02).
    return (
        1970,
        "year unresolved (no mtime on image); anchored to epoch, FLAGGED",
        True,
    )


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
    seed_basis: str,
    seed_unresolved: bool,
    volume_id: int,
    volume_offset: int,
) -> list[TimelineEvent]:
    """Time-resolve a member's parsed records, then normalize to events (D-46/LOG-04).

    Three timestamp provenances, in precedence order:

    * a record carrying an embedded Unix ``epoch`` (zsh extended / bash
      ``HISTTIMEFORMAT`` history) resolves DIRECTLY to that UTC instant — it is an
      authoritative absolute time, not a host-tz-inferred wall-clock;
    * a record with a parseable RFC3164 head gets a per-set year-inferred UTC
      instant (honest tz + year flags);
    * a record with neither falls back to the member's seed-year January 1 with an
      explicit basis flag rather than being dropped (the line is still evidence).
    """
    comps: list[tuple[int, int, int, int, int] | None] = [
        timeresolve.rfc3164_components(r.raw_timestamp) if r.raw_timestamp else None
        for r in records
    ]
    datable = [c for c in comps if c is not None]
    year_flags = timeresolve.infer_years(
        datable, seed_year=seed_year, seed_basis=seed_basis
    )
    year_iter = iter(year_flags)

    events: list[TimelineEvent] = []
    for record, comp in zip(records, comps, strict=True):
        epoch = getattr(record, "epoch", None)
        if epoch is not None:
            # Embedded Unix epoch (shell history): an absolute UTC instant. Do NOT
            # consume a year_iter slot — epoch records have comp=None so they were
            # never added to ``datable`` (the RFC3164 year inference is irrelevant).
            utc_iso = iso_utc(from_epoch_utc(epoch))
            attrs: dict[str, Any] = {
                **record.attributes,
                "timestamp_source": "log:embedded-epoch",
            }
        elif comp is not None:
            year, yflags = next(year_iter)
            naive = timeresolve.naive_from_components(year, comp)
            utc_iso, tz_flags = timeresolve.to_utc(naive, host_tz)
            attrs = {**record.attributes, **tz_flags, **yflags}
            if seed_unresolved:
                # The RFC3164 head has a real month/day/time but its YEAR could
                # not be anchored to any mtime on the image — the absolute instant
                # is a guess. Sort it OUT of the chronological front so it does not
                # read as genuine early activity (CR-02); keep the parsed pieces in
                # attributes for the undated-artifacts view.
                attrs["ts_resolved"] = utc_iso
                attrs["ts_basis"] = (
                    "year unresolved (no mtime on image); sorted to end of "
                    "timeline, NOT genuine chronology"
                )
                utc_iso = _UNDATED_SORT_LAST_ISO
        else:
            # No per-line timestamp AND no mtime anywhere → sort to the END of the
            # timeline rather than to a fabricated 1970-01-01 at the FRONT (CR-02).
            # With an mtime-derived seed the seed-year Jan 1 anchor is a defensible
            # bound and stays inline; only the fully-unresolved case is segregated.
            if seed_unresolved:
                utc_iso = _UNDATED_SORT_LAST_ISO
                attrs = {
                    **record.attributes,
                    "ts_basis": (
                        "no per-line timestamp and no mtime on image; sorted to "
                        "end of timeline, NOT genuine chronology"
                    ),
                    "year_basis": seed_basis,
                }
            else:
                naive = datetime(seed_year, 1, 1)  # noqa: DTZ001 (naive by design)
                utc_iso, tz_flags = timeresolve.to_utc(naive, host_tz)
                attrs = {
                    **record.attributes,
                    **tz_flags,
                    "ts_basis": "file-mtime-fallback; no per-line timestamp",
                    "year_basis": seed_basis,
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

    # Bind the audit log BEFORE the first guard so a pre-open mounted-source
    # rejection is recorded as a FAIL event (WR-03). ``run_logs`` requires a prior
    # ingest, so the case dir already exists; AuditLog creates the journal lazily
    # on first write. The D-08 contract is "record FAIL before non-zero exit" — the
    # pre-open guard must not be able to raise past the audit trail.
    # The audit log lives inside the case directory, so a case that does not
    # exist has nowhere to record a FAIL event. Check for it BEFORE binding the
    # log, otherwise the audit write's own OSError masks this actionable message
    # with a raw traceback (``run_logs`` requires a prior ingest).
    if not CaseStore.exists(case_path):
        raise LogsError(
            f"no case database under {case_path}; run `pyautopsy ingest` first"
        )

    audit = AuditLog(case_path)

    # (1) Re-assert the read-only / not-mounted guard before any access (D-05/P1).
    #     Audited: a mounted source is a FAIL event, not a silent clean exit.
    try:
        integrity.assert_source_not_mounted(image_path)
    except integrity.MountedSourceError as exc:
        audit.write(
            "logs.error",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise

    # (2) Open the existing case store (ingest created it).
    try:
        store = CaseStore.open(case_path)
    except FileNotFoundError as exc:
        audit.write(
            "logs.error",
            outcome="FAIL",
            error=str(exc),
            error_type="LogsError",
        )
        raise LogsError(
            f"no case database under {case_path}; run `pyautopsy ingest` first"
        ) from exc

    audit.write("logs.start", image=str(image_path), case_dir=str(case_path))

    events_parsed = 0
    auth_events = 0
    log_sets = 0
    findings_count = 0

    with audited_step(audit, store, "logs", LogsError):
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
            # D-44/D-45 honesty findings accumulated in encounter order so the
            # store's surrogate-id tiebreak stays insertion-deterministic
            # (Pitfall 3); persisted in the SAME single transaction as the events.
            all_findings: list[LogFinding] = []
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

                # Rotated /var/log sets (auth/syslog) THEN per-user shell-history
                # files (LOG-03). Both are parsed through the SAME EXT-01 registry;
                # the order here fixes the deterministic insert order (Pitfall 3).
                discovered = [
                    *discover.discover_log_sets(rows),
                    *discover.discover_shell_histories(rows),
                ]
                for log_set in discovered:
                    log_sets += 1
                    # (D-45) One completeness finding per discovered set: the
                    # neutral discover ``note`` (reassembled oldest→newest, or
                    # which rotation indices are absent) with the present/missing
                    # indices preserved in attributes for the report.
                    fnd = log_set.finding
                    all_findings.append(
                        LogFinding(
                            evidence_source_id=source_id,
                            category="completeness",
                            subject=log_set.basename,
                            detail=fnd.note,
                            attributes={
                                "present_indices": list(fnd.present_indices),
                                "missing_indices": list(fnd.missing_indices),
                                "member_count": fnd.member_count,
                            },
                        )
                    )
                    set_events, set_findings = _parse_log_set(
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
                    all_findings.extend(set_findings)
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
            # (WR-06) Gate on the absence of FILESYSTEM-source events, not on the
            # absence of ANY event. A prior standalone ``logs`` run inserts LOG
            # events but never runs build_timeline, so an "any event exists" guard
            # would see those log events and skip the filesystem backfill forever,
            # leaving a log-only "super-timeline" missing its MACB events. Keying
            # on ``source LIKE 'filesystem%'`` backfills exactly once even across
            # repeated standalone ``logs`` runs (still idempotent: once filesystem
            # events exist, this is False).
            fs_events: list[TimelineEvent] = []
            if not store.has_timeline_events_with_source_prefix(
                source_id, "filesystem"
            ):
                for file_row in store.get_files(source_id):
                    fs_events.extend(explode(file_row))

            with store.transaction():
                if fs_events:
                    store.insert_timeline_events(fs_events)
                store.insert_timeline_events(all_events)
                # (D-44/D-45) Persist the honesty findings in the SAME single
                # transaction (CaseStore sole writer / WR-01) so the report can
                # surface them; no second transaction is opened.
                store.insert_log_findings(all_findings)
                # Recorded even when a log set yielded no events: the pass still
                # covered the image's logs (D-40 honesty).
                store.record_stage(
                    store.get_evidence_source(source_id).case_id, "logs"
                )
            events_parsed = len(all_events)
            findings_count = len(all_findings)
        finally:
            handle.close()

        audit.write(
            "logs.end",
            outcome="SUCCESS",
            evidence_source_id=source_id,
            events_parsed=events_parsed,
            auth_events=auth_events,
            log_sets=log_sets,
            findings_count=findings_count,
        )

    return LogsResult(
        evidence_source_id=source_id,
        events_parsed=events_parsed,
        auth_events=auth_events,
        log_sets=log_sets,
        findings_count=findings_count,
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
) -> tuple[list[TimelineEvent], list[LogFinding]]:
    """Discover the parser, read+decode each member oldest→newest, resolve to events.

    Returns the member's normalized events AND any per-member honesty findings
    (D-44 tamperability) the matched parser exposes — both in encounter order so
    the store's surrogate-id tiebreak stays insertion-deterministic (Pitfall 3).
    """
    parser = next(
        (p for p in PARSERS if p.matches(log_set.basename)), None
    )
    if parser is None:
        return [], []

    events: list[TimelineEvent] = []
    findings: list[LogFinding] = []
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
        # Forward the member path as parser context: the shell-history parser
        # uses ctx["path"] for the per-user actor (/home/<user>) and the bash/zsh
        # kind; the RFC3164 parsers ignore keys they do not need (EXT-01).
        ctx = {"path": member.path}
        records = list(parser.parse(text, ctx))
        # (D-44) When the matched parser exposes the additive findings accessor
        # (shell-history), capture its observed-fact tamperability finding(s)
        # VERBATIM — one LogFinding per member finding. The RFC3164 parsers do
        # not expose it, so syslog/auth members add no tamperability finding.
        findings_for = getattr(parser, "findings_for", None)
        if findings_for is not None:
            for detail in findings_for(text, ctx):
                findings.append(
                    LogFinding(
                        evidence_source_id=source_id,
                        category="tamperability",
                        subject=member.path,
                        detail=detail,
                    )
                )
        file_id = path_index.get(member.path)
        seed_year, seed_basis, seed_unresolved = _seed_year_from_mtime(
            rows_by_path, member.path
        )
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
                seed_basis=seed_basis,
                seed_unresolved=seed_unresolved,
                volume_id=volume_id,
                volume_offset=volume_offset,
            )
        )
    return events, findings
