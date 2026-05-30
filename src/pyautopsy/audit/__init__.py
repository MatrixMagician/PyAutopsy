"""Append-only audit log package (REPORT-02).

Exposes :class:`AuditLog`, the case-dir-confined JSONL writer that records every
tool action with a UTC timestamp for tamper-evident chain-of-custody (D-09/D-10).
"""

from __future__ import annotations

from pyautopsy.audit.log import AuditLog, AuditPathError

__all__ = ["AuditLog", "AuditPathError"]
