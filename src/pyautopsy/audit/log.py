"""Append-only JSONL audit log (REPORT-02, D-09/D-10).

:class:`AuditLog` writes one structured event per line to ``logs/audit.jsonl``
under the case directory and **only** there (never near the read-only evidence —
PITFALLS P12). Each write uses ``O_APPEND`` so concurrent writers interleave
whole lines and an existing log is never truncated, then ``fsync`` for
tamper-evidence durability (01-RESEARCH.md §Code Examples). Events are serialised
with ``sort_keys=True`` so two runs of the same event diff byte-identically
(PITFALLS P3). Every event carries a UTC ISO-8601 ``ts`` sourced from
:mod:`pyautopsy.util.timeutil` (D-10).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pyautopsy.case.models import AuditEvent
from pyautopsy.util.timeutil import iso_utc

__all__ = ["AuditLog", "AuditPathError"]

_LOG_SUBDIR = "logs"
_LOG_NAME = "audit.jsonl"
_OPEN_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_APPEND
_OPEN_MODE = 0o644

# Record keys the writer owns. A caller may never supply them: ``action`` names
# the event and ``ts`` is the UTC stamp, and a forgeable audit trail is no audit
# trail at all.
_RESERVED_FIELDS: tuple[str, ...] = ("action", "ts")


class AuditPathError(ValueError):
    """Raised when an audit-log path would escape the case directory."""


class AuditLog:
    """An append-only JSONL audit writer confined to one case directory."""

    def __init__(self, case_dir: Path | str) -> None:
        """Bind the log to ``<case_dir>/logs/audit.jsonl``.

        The path is computed from the case directory and never from a
        caller-supplied filename, so the log cannot be redirected outside the
        case dir (T-1-01-A confinement). The ``logs/`` directory is expected to
        exist (created by :meth:`CaseStore.create`).

        Args:
            case_dir: Root directory of the case.

        Raises:
            AuditPathError: If the resolved log path escapes the case directory.
        """
        case_root = Path(case_dir).resolve()
        path = (case_root / _LOG_SUBDIR / _LOG_NAME).resolve()
        if not _is_within(path, case_root):
            raise AuditPathError(
                f"audit log path {path} escapes case directory {case_root}"
            )
        self.case_dir = case_root
        self.path = path

    def write(self, action: str, **fields: Any) -> None:
        """Append one audit event built from an action and keyword fields.

        The reserved-key guard lives on :meth:`write_event`, the single path
        every write traverses. ``action`` cannot reach ``fields`` at all here:
        it is bound by the positional parameter, so passing it is a
        ``TypeError`` from the call itself.

        Args:
            action: The action name (e.g. ``"ingest.open"``).
            **fields: Action-specific JSON-serialisable payload (inputs, hashes,
                parameters, versions, outcome, errors). ``action`` and ``ts``
                are reserved and must not appear here.

        Raises:
            ValueError: If a reserved key (``action`` / ``ts``) is supplied.
            OSError: If the event cannot be written to disk.
        """
        self.write_event(AuditEvent(action=action, fields=fields))

    def write_event(self, event: AuditEvent) -> None:
        """Append a fully-formed :class:`AuditEvent`.

        ``ts`` is stamped here when the event leaves it unset, keeping the
        timestamp source single (D-10). The flattened record is
        ``{"action": ..., "ts": ..., **event.fields}``.

        This is the single point every write path passes through, so it owns
        the reserved-key guard: a caller using either entry point cannot forge
        an action or a timestamp.

        Args:
            event: The event to append.

        Raises:
            ValueError: If ``event.fields`` collides with a reserved key.
            OSError: If the event cannot be written to disk.
        """
        record: dict[str, Any] = dict(event.fields)
        for reserved in _RESERVED_FIELDS:
            if reserved in record:
                # One guard means one message, so the two entry points can no
                # longer word this differently. This is ``write``'s original
                # wording, kept because it names the offending key; the version
                # that lived here listed both reserved names without saying
                # which one the caller actually passed.
                raise ValueError(
                    f"{reserved!r} is a reserved audit field and is set "
                    "automatically; do not pass it explicitly"
                )
        record["action"] = event.action
        record["ts"] = event.ts or iso_utc()
        line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
        self._append(line)

    def _append(self, line: str) -> None:
        """Append one already-serialised line with O_APPEND + fsync durability."""
        try:
            fd = os.open(self.path, _OPEN_FLAGS, _OPEN_MODE)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise OSError(f"failed to append to audit log {self.path}: {exc}") from exc


def _is_within(path: Path, root: Path) -> bool:
    """Return True if ``path`` is ``root`` or a descendant of it."""
    return path == root or root in path.parents
