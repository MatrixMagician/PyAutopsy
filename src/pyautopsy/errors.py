"""The base class every PyAutopsy domain exception derives from.

The CLI's job at the end of each command is the same regardless of which layer
failed: print one message on stderr and exit with the integrity exit code. Its
handlers therefore need one name to catch, not a hand-maintained tuple of every
error class the command's call graph can raise — a tuple that silently goes
stale the moment a new error type appears.

:class:`PyAutopsyError` is that name. It is deliberately narrow: it covers the
errors this project defines and raises on purpose, so catching it never
swallows a programming bug. A ``KeyError`` or ``AttributeError`` is not a
``PyAutopsyError`` and still propagates with its traceback intact, which is
what the orchestrators' ``<step>.crashed`` audit arm exists to record.

Two project exceptions deliberately stay outside this hierarchy, because
becoming catchable would change behaviour rather than tidy it:

* ``AuditPathError`` — an audit log that cannot be confined to the case
  directory is a broken invariant, not an operational failure to report and
  exit on.
* ``ConfinementRejected`` — likewise, a path that escapes the case directory
  during recovery.

``OSError`` and ``sqlite3.Error`` are stdlib types this project cannot rebase,
so handlers that need them still name them explicitly.
"""

from __future__ import annotations

__all__ = ["PyAutopsyError"]


class PyAutopsyError(Exception):
    """Base class for every error PyAutopsy raises deliberately.

    Subclassed by the orchestrator errors (ingest/walk/recover/filter/logs/
    search/analyze) and the evidence-layer errors (image open, filesystem,
    integrity, mounted source).
    """
