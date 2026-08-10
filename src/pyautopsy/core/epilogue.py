"""The shared audit epilogue for the orchestration tier (CR-03/WR-05).

Every orchestrator ends the same way, and it has to: the audit trail is the
contract, and its two-arm split is load-bearing.

* An **expected operational failure** — a bad path, an unopenable image, a
  corrupt case DB, a missing evidence source — is recorded as ``<step>.error``
  and re-raised with its traceback intact.
* Anything else is a **genuine programming bug** and is recorded under a
  distinct ``<step>.crashed`` event, so a bug is never filed in the audit trail
  as an operational failure. It is re-raised unwrapped so it surfaces in full.

Either way the store is closed exactly once, including when the audit write
itself fails.

:func:`audited_step` owns that shape so the five orchestrators state it once.
Each supplies its step name and its own error class; the operational set they
all share lives here in :data:`OPERATIONAL_ERRORS`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore
from pyautopsy.evidence.filesystem import FilesystemError
from pyautopsy.evidence.image import ImageOpenError
from pyautopsy.evidence.integrity import IntegrityError, MountedSourceError

__all__ = ["OPERATIONAL_ERRORS", "audited_step"]

# The operational failures every orchestrator legitimately expects, regardless
# of which step it is: a read-only-boundary or integrity refusal, an unopenable
# image, a filesystem-seam failure, an OS-level error, or a case-DB error.
#
# ``sqlite3.Error`` is listed explicitly because it is NOT an ``OSError``
# (BL-02) — a corrupt case DB must exit cleanly rather than read as a crash.
OPERATIONAL_ERRORS: tuple[type[BaseException], ...] = (
    MountedSourceError,
    IntegrityError,
    ImageOpenError,
    FilesystemError,
    OSError,
    sqlite3.Error,
)


@contextmanager
def audited_step(
    audit: AuditLog,
    store: CaseStore | None,
    step: str,
    *step_errors: type[BaseException],
) -> Iterator[None]:
    """Record the terminal audit event for one orchestrator step, then re-raise.

    Args:
        audit: The case's audit log.
        store: The case store to close on the way out. ``None`` is allowed for
            a step that may fail before it opens one.
        step: The step name that prefixes the audit action (e.g. ``"walk"``,
            yielding ``walk.error`` / ``walk.crashed``).
        *step_errors: The step's own error classes, expected on top of
            :data:`OPERATIONAL_ERRORS`.

    Yields:
        ``None`` — the step body runs inside the ``with``.

    Raises:
        BaseException: Whatever the body raised, re-raised unchanged after the
            audit record is written.
    """
    expected = tuple(step_errors) + OPERATIONAL_ERRORS
    try:
        yield
    except expected as exc:
        # An EXPECTED operational failure: always leave a terminal FAIL event
        # before propagating, then re-raise (traceback preserved).
        audit.write(
            f"{step}.error",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    except Exception as exc:
        # An UNEXPECTED error — a genuine programming bug, not an operational
        # failure. Record it under a DISTINCT ``<step>.crashed`` event (so the
        # audit trail never conflates a bug with an expected failure), then
        # re-raise unwrapped so the bug surfaces with its full traceback.
        audit.write(
            f"{step}.crashed",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    finally:
        # Closed on every path, including when the audit write above raised.
        if store is not None:
            store.close()
