"""RED Wave-0 scaffold for the TIME-02 super-timeline merge (CR-01 tied order).

The super-timeline is NOT new code: it IS the existing D-26 ordered read
``CaseStore.get_timeline_events`` (D-47). Log events written into the shared
``timeline_events`` table sort in the same total order as filesystem events, so
this test pins the *merge + tied-order* contract specifically:

* fs + log events come back in one UTC-sorted sequence, and
* two log events stamped at the IDENTICAL second with NULL ``meta_addr`` (the
  fixture's CR-01 pair, ``log_search_groundtruth["tied_event_count"]``) keep a
  byte-stable order across two reads — never falling through to sqlite's rowid
  tiebreak (Pitfall 3).

References ``core.logs.run_logs`` (not yet built) so it is RED until the Wave-1
log slice lands; the not-yet-existing import is inside the test body so the file
collects cleanly. Not ``xfail``/``skip``. No ``import pytsk3`` (D-14 unaffected).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def test_super_timeline_merge(
    log_search_image: Path, case_dir: Path, log_search_groundtruth: dict[str, Any]
) -> None:
    """TIME-02 + CR-01: merged fs+log events are UTC-ordered and tied events stable.

    Ingest + walk (filesystem events) then ``run_logs`` (log events into the same
    table); the existing ordered read returns the merged super-timeline. The two
    tied-second syslog lines (identical ts, NULL meta) appear and order
    deterministically across repeated reads.
    """
    from pyautopsy.case import CaseStore  # noqa: PLC0415
    from pyautopsy.core.ingest import run_ingest  # noqa: PLC0415
    from pyautopsy.core.logs import run_logs  # noqa: PLC0415 (RED stub)
    from pyautopsy.core.walk import run_walk  # noqa: PLC0415

    ingested = run_ingest(log_search_image, case_dir, examiner="X", evidence_id="E1")
    run_walk(log_search_image, case_dir, timezone="UTC")
    run_logs(log_search_image, case_dir, evidence_source_id=ingested.evidence_source_id)

    with CaseStore.open(case_dir) as store:
        first = store.get_timeline_events(ingested.evidence_source_id)
        second = store.get_timeline_events(ingested.evidence_source_id)

    # Both producers contributed to one merged sequence.
    sources = {e.source for e in first}
    assert any(s.startswith("filesystem") for s in sources)
    assert sources & {"auth", "syslog", "shell-history"}

    # One UTC total order.
    stamps = [e.ts_utc for e in first]
    assert stamps == sorted(stamps)

    # The CR-01 tied-second pair is present (two events sharing one ts_utc).
    from collections import Counter  # noqa: PLC0415

    counts = Counter(e.ts_utc for e in first)
    assert any(
        c >= log_search_groundtruth["tied_event_count"] for c in counts.values()
    ), "expected the CR-01 tied-second events in the merged timeline"

    # Repeated reads are byte-stable (no rowid-tiebreak leak, Pitfall 3).
    assert [e.id for e in first] == [e.id for e in second]
