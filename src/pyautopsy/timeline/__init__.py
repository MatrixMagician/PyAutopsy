"""Timeline tier — producers that write the shared forensic-event model.

This package turns the lower tiers' normalized output into rows of the shared
``timeline_events`` table (D-23). The filesystem MACB explosion
(:func:`pyautopsy.timeline.builder.build_timeline`) is the first producer: it
reads the Phase 2 ``files`` rows and emits one event per populated MACB
timestamp (D-24). Phase 5 log producers will write the same shape into the same
table for the TIME-02 super-timeline.
"""

from __future__ import annotations

from pyautopsy.timeline.builder import build_timeline, explode

__all__ = ["build_timeline", "explode"]
