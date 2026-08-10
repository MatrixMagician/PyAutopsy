"""Tests for the shared orchestrator audit epilogue (CR-03/WR-05).

The epilogue is the audit trail's contract: an expected operational failure is
recorded as ``<step>.error``, a genuine bug as a distinct ``<step>.crashed``,
both are re-raised, and the store is closed on every path. Five orchestrators
depend on this one context manager, so it is tested directly rather than only
through them.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore
from pyautopsy.core.epilogue import OPERATIONAL_ERRORS, audited_step


class _StoreSpy(CaseStore):
    """A real CaseStore that counts how often it is closed.

    Subclassed rather than faked so the epilogue is exercised against the type
    its five callers actually pass.
    """

    def __init__(self, case_dir: Path) -> None:
        created = CaseStore.create(case_dir / "spy-case")
        super().__init__(created.case_dir, created.connection)
        self.closes = 0

    def close(self) -> None:
        self.closes += 1
        super().close()


class _StepError(Exception):
    """A step's own error class, as each orchestrator supplies."""


def _audit(case_dir: Path) -> AuditLog:
    (case_dir / "logs").mkdir(parents=True, exist_ok=True)
    return AuditLog(case_dir)


def _records(case_dir: Path) -> list[dict]:
    log = case_dir / "logs" / "audit.jsonl"
    if not log.exists():
        return []
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_success_path_writes_nothing_and_closes_the_store(case_dir: Path) -> None:
    """A clean step leaves no terminal FAIL record — only the store is closed."""
    audit = _audit(case_dir)
    store = _StoreSpy(case_dir)

    with audited_step(audit, store, "walk", _StepError):
        pass

    assert _records(case_dir) == []
    assert store.closes == 1


@pytest.mark.parametrize(
    "exc",
    [
        _StepError("the step's own error"),
        OSError("an os-level failure"),
        sqlite3.Error("a corrupt case database"),
    ],
    ids=["step_error", "os_error", "sqlite_error"],
)
def test_expected_failure_is_audited_as_error_and_reraised(
    case_dir: Path, exc: Exception
) -> None:
    """An operational failure is recorded as ``<step>.error`` and propagates."""
    audit = _audit(case_dir)
    store = _StoreSpy(case_dir)

    with pytest.raises(type(exc)):
        with audited_step(audit, store, "walk", _StepError):
            raise exc

    records = _records(case_dir)
    assert [r["action"] for r in records] == ["walk.error"]
    assert records[0]["outcome"] == "FAIL"
    assert records[0]["error"] == str(exc)
    assert records[0]["error_type"] == type(exc).__name__
    assert store.closes == 1


def test_unexpected_failure_is_audited_as_crashed_not_error(case_dir: Path) -> None:
    """A programming bug gets its own action, never the operational one.

    This split is why the epilogue exists: a bug filed as an operational
    failure would make the audit trail lie about what happened.
    """
    audit = _audit(case_dir)
    store = _StoreSpy(case_dir)

    with pytest.raises(KeyError):
        with audited_step(audit, store, "walk", _StepError):
            raise KeyError("simulated programming bug")

    records = _records(case_dir)
    assert [r["action"] for r in records] == ["walk.crashed"]
    assert records[0]["error_type"] == "KeyError"
    assert store.closes == 1


def test_store_is_closed_even_when_the_audit_write_itself_fails(
    case_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing audit write must not leak the database connection."""
    audit = _audit(case_dir)
    store = _StoreSpy(case_dir)

    def broken_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("audit log is unwritable")

    monkeypatch.setattr(audit, "write", broken_write)

    with pytest.raises(OSError, match="unwritable"):
        with audited_step(audit, store, "walk", _StepError):
            raise _StepError("original operational failure")

    assert store.closes == 1


def test_missing_store_is_tolerated(case_dir: Path) -> None:
    """A step that failed before opening a store still audits its failure."""
    audit = _audit(case_dir)

    with pytest.raises(_StepError):
        with audited_step(audit, None, "analyze", _StepError):
            raise _StepError("failed before the store was opened")

    assert [r["action"] for r in _records(case_dir)] == ["analyze.error"]


def test_step_name_prefixes_both_actions(case_dir: Path) -> None:
    """Each orchestrator's records are namespaced by its own step name."""
    audit = _audit(case_dir)

    with pytest.raises(_StepError):
        with audited_step(audit, None, "recover", _StepError):
            raise _StepError("x")
    with pytest.raises(KeyError):
        with audited_step(audit, None, "recover", _StepError):
            raise KeyError("y")

    assert [r["action"] for r in _records(case_dir)] == [
        "recover.error",
        "recover.crashed",
    ]


def test_operational_set_includes_sqlite_error_which_is_not_an_oserror() -> None:
    """BL-02: ``sqlite3.Error`` is listed explicitly because it is not an OSError.

    Without it, a corrupt case DB would be recorded as a crash rather than an
    operational failure.
    """
    assert sqlite3.Error in OPERATIONAL_ERRORS
    assert not issubclass(sqlite3.Error, OSError)
