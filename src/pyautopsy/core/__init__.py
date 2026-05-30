"""Orchestration tier — composes the forensic spine into runnable workflows.

This package wires the proven lower tiers (the native evidence seam, the
integrity layer, the case store, and the audit log) into end-to-end operations.
Phase 1 ships a single orchestrator, :func:`pyautopsy.core.ingest.run_ingest`,
the read-only / hashed / audited / re-verified ingest that the ``pyautopsy
ingest`` CLI command drives.
"""

from __future__ import annotations

from pyautopsy.core.ingest import IngestError, IngestResult, run_ingest

__all__ = ["IngestError", "IngestResult", "run_ingest"]
