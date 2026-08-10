"""Tests for the append-only JSONL audit log (REPORT-02, D-09/D-10).

These prove the tamper-evidence properties: every action appends exactly one
valid JSON line, each carries a UTC ``ts``, keys are deterministically ordered,
the log lives only under ``<case_dir>/logs/``, and writes never truncate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyautopsy.audit import AuditLog
from pyautopsy.case import AuditEvent


def _read_lines(case_dir: Path) -> list[str]:
    path = case_dir / "logs" / "audit.jsonl"
    return path.read_text(encoding="utf-8").splitlines()


def test_two_writes_two_lines(case_dir: Path) -> None:
    """Two writes produce exactly two JSON lines."""
    (case_dir / "logs").mkdir(parents=True)
    log = AuditLog(case_dir)
    log.write("ingest.open", image="disk.dd")
    log.write("ingest.hash", sha256="a" * 64)
    lines = _read_lines(case_dir)
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # each line is valid JSON


def test_event_carries_utc_ts_and_fields(case_dir: Path) -> None:
    """Each event has a UTC ``ts`` and retains the supplied fields."""
    (case_dir / "logs").mkdir(parents=True)
    log = AuditLog(case_dir)
    log.write(
        "ingest.verify",
        inputs={"path": "/x.dd"},
        hashes={"sha256": "b" * 64},
        parameters={"chunk": 8},
        outcome="PASS",
    )
    event = json.loads(_read_lines(case_dir)[0])
    assert event["ts"].endswith("+00:00")
    assert event["action"] == "ingest.verify"
    assert event["inputs"] == {"path": "/x.dd"}
    assert event["hashes"] == {"sha256": "b" * 64}
    assert event["parameters"] == {"chunk": 8}
    assert event["outcome"] == "PASS"


def test_keys_are_sorted_deterministically(case_dir: Path) -> None:
    """Keys are emitted sorted so identical events serialise byte-identically."""
    (case_dir / "logs").mkdir(parents=True)
    log = AuditLog(case_dir)
    event = AuditEvent(
        action="x",
        fields={"zeta": 1, "alpha": 2, "mid": 3},
        ts="2026-05-30T00:00:00+00:00",
    )
    log.write_event(event)
    log.write_event(event)
    lines = _read_lines(case_dir)
    assert lines[0] == lines[1]  # byte-identical repeat
    # keys appear in sorted order within the line
    decoded = list(json.loads(lines[0], object_pairs_hook=lambda p: p))
    keys = [k for k, _ in decoded]
    assert keys == sorted(keys)


def test_append_never_truncates(case_dir: Path) -> None:
    """A fresh AuditLog appends to an existing log rather than truncating it."""
    (case_dir / "logs").mkdir(parents=True)
    AuditLog(case_dir).write("first")
    AuditLog(case_dir).write("second")  # new instance, same file
    lines = _read_lines(case_dir)
    assert len(lines) == 2
    assert json.loads(lines[0])["action"] == "first"
    assert json.loads(lines[1])["action"] == "second"


def test_log_path_is_under_case_dir(case_dir: Path) -> None:
    """The log path always resolves under ``<case_dir>/logs/``."""
    (case_dir / "logs").mkdir(parents=True)
    log = AuditLog(case_dir)
    expected = (case_dir / "logs" / "audit.jsonl").resolve()
    assert log.path == expected


def test_reserved_ts_field_rejected(case_dir: Path) -> None:
    """A caller cannot smuggle a ``ts`` field that would shadow the UTC stamp."""
    (case_dir / "logs").mkdir(parents=True)
    log = AuditLog(case_dir)
    with pytest.raises(ValueError):
        log.write("x", ts="not-a-utc-stamp")


@pytest.mark.parametrize("reserved", ["action", "ts"])
def test_reserved_key_rejected_by_the_shared_write_path(
    case_dir: Path, reserved: str
) -> None:
    """A fully-formed event cannot carry a forged action or timestamp.

    ``write`` builds an event and hands it to ``write_event``, so a single
    guard on ``write_event`` covers every write path.
    """
    (case_dir / "logs").mkdir(parents=True)
    log = AuditLog(case_dir)

    with pytest.raises(ValueError) as excinfo:
        log.write_event(AuditEvent(action="x", fields={reserved: "forged"}))
    assert reserved in str(excinfo.value)

    # Nothing was written by a rejected call.
    assert not log.path.exists() or log.path.read_text(encoding="utf-8") == ""


def test_reserved_ts_rejected_identically_through_both_entry_points(
    case_dir: Path,
) -> None:
    """``write`` and ``write_event`` reject a forged ``ts`` the same way."""
    (case_dir / "logs").mkdir(parents=True)
    log = AuditLog(case_dir)

    with pytest.raises(ValueError) as via_write:
        log.write("x", ts="forged")
    with pytest.raises(ValueError) as via_write_event:
        log.write_event(AuditEvent(action="x", fields={"ts": "forged"}))

    assert str(via_write.value) == str(via_write_event.value)


def test_action_cannot_be_smuggled_through_write_at_all(case_dir: Path) -> None:
    """``write`` cannot even express an ``action`` field — Python binds it.

    ``write(self, action, **fields)`` binds the name ``action`` to the
    positional parameter, so ``fields`` can never contain that key: a caller
    attempting it gets ``TypeError`` from the call itself, before any guard
    runs. This is why the reserved-key check needs to live only on the shared
    ``write_event`` path.
    """
    (case_dir / "logs").mkdir(parents=True)
    log = AuditLog(case_dir)

    with pytest.raises(TypeError):
        log.write("x", **{"action": "forged"})
