"""RED Wave-0 scaffold for deleted-file recovery (RECOV-01/02/03).

These stubs pin the exact pytest node IDs from 04-VALIDATION.md's Per-Task
Verification Map. They reference the recovery orchestrator ``core.recover``
(``run_recover``) and its honest confidence-tier copy — none of which exist yet
(Wave 1 builds them) — so every test here MUST *fail* until those plans land.

The contract for a Wave-0 stub: the file COLLECTS cleanly (no import error at
collection time) but each test FAILS. The not-yet-existing modules are therefore
imported *inside* the test body; an ``ImportError`` there surfaces as a test
failure (RED), not a collection error. Ground-truth constants come from
``tests/fixtures/make_fixtures.py`` so the Wave-1 implementation must reproduce
EXACT bytes/addresses, not merely spot-check.

No ``import pytsk3`` here: recovery is driven through the orchestrator/CLI seam
(D-14); the tests never touch the native binding directly.
"""

from __future__ import annotations

from pathlib import Path

from pyautopsy.case import CaseStore
from pyautopsy.core.ingest import run_ingest
from tests.fixtures import make_fixtures

# Recovery orchestrator + honesty copy land in Wave 1; until then these RED stubs
# fail at the in-body import / behavior assertion.
_NOT_YET = "Wave 1: core/recover.py run_recover not implemented yet (RED)"

# Forbidden substrings the tier/report copy must never contain — recovery labels
# describe DATA SURVIVAL, never user intent or a good/bad verdict (D-32, mirrors
# the Phase-3 WR-02 honesty test).
_FORBIDDEN_INTENT_COPY = (
    "user deleted",
    "good",
    "bad",
    "malicious",
    "guilty",
    "smoking gun",
)


def _ingest_then_recover(image: Path, case_dir: Path):
    """Ingest ``image`` then run the (future) recovery orchestrator.

    Mirrors ``tests/test_walk.py::_ingest_then_walk`` — ingest read-only, then
    drive the recovery pass. ``run_recover`` does not exist yet, so importing it
    here fails the calling test (RED) without breaking collection.
    """
    from pyautopsy.core.recover import run_recover  # noqa: PLC0415 (RED stub)

    ingested = run_ingest(image, case_dir, examiner="tester", evidence_id="E1")
    result = run_recover(image, case_dir)
    return result, ingested.evidence_source_id


def test_recovers_deleted_ext4_content(ext4_orphan_image: Path, case_dir: Path) -> None:
    """RECOV-01: a deleted ext4 inode recovers its EXACT bytes + hashes.

    The recovered entry is cataloged as a ``files`` row with ``allocated=False``
    and its bytes are written under a confined ``recovered/`` tree. The orphan
    fixture's deleted inode (``EXT4_ORPHAN_META_ADDR``) round-trips its exact
    ``EXT4_ORPHAN_CONTENT``.
    """
    _result, source_id = _ingest_then_recover(ext4_orphan_image, case_dir)

    with CaseStore.open(case_dir) as store:
        rows = store.get_files(source_id)

    recovered = [r for r in rows if r.meta_addr == make_fixtures.EXT4_ORPHAN_META_ADDR]
    assert recovered, "deleted ext4 inode was not cataloged as a recovered files row"
    row = recovered[0]
    assert row.allocated is False

    # Bytes are written under a confined recovered/ tree (D-33).
    recovered_root = case_dir / "recovered"
    assert recovered_root.is_dir(), "recovered/ confinement tree was not created"
    written = list(recovered_root.rglob("*"))
    assert any(
        p.is_file() and p.read_bytes() == make_fixtures.EXT4_ORPHAN_CONTENT
        for p in written
    ), "recovered bytes do not match EXT4_ORPHAN_CONTENT exactly"


def test_recovers_ntfs_resident(
    ntfs_resident_deleted_image: Path, case_dir: Path
) -> None:
    """RECOV-01: NTFS resident ``$DATA`` recovered from the MFT record.

    A resident deleted file has NO data-block runs (Pitfall 3); its content is
    recovered straight from the surviving MFT record. The fixture's deleted entry
    (``NTFS_RESIDENT_META_ADDR``) recovers its exact ``NTFS_RESIDENT_CONTENT``.
    """
    _result, source_id = _ingest_then_recover(ntfs_resident_deleted_image, case_dir)

    with CaseStore.open(case_dir) as store:
        rows = store.get_files(source_id)

    recovered = [
        r for r in rows if r.meta_addr == make_fixtures.NTFS_RESIDENT_META_ADDR
    ]
    assert recovered, "resident deleted NTFS entry was not recovered"
    assert recovered[0].allocated is False

    recovered_root = case_dir / "recovered"
    written = list(recovered_root.rglob("*")) if recovered_root.is_dir() else []
    assert any(
        p.is_file() and p.read_bytes() == make_fixtures.NTFS_RESIDENT_CONTENT
        for p in written
    ), "resident $DATA not recovered byte-exact from the MFT record"


def test_orphan_reported_separately(ext4_orphan_image: Path, case_dir: Path) -> None:
    """RECOV-02: an orphan (parent dir deleted) is reported in a SEPARATE list.

    Orphan-ness is a provenance fact independent of the recovery tier; the
    orchestrator must surface orphans in their own list/section, not mixed into
    the normal recovered-files list.
    """
    result, _source_id = _ingest_then_recover(ext4_orphan_image, case_dir)

    # The recovery result exposes orphans separately from the normal recovered
    # list (exact attribute names finalized in Wave 1; the contract is that they
    # are DISTINCT collections and the orphan inode appears only in the orphan
    # one).
    orphans = getattr(result, "orphans", None)
    recovered = getattr(result, "recovered", None)
    assert orphans is not None and recovered is not None, (
        "RecoverResult must expose orphans and recovered as separate lists"
    )
    orphan_addrs = {getattr(o, "meta_addr", None) for o in orphans}
    recovered_addrs = {getattr(r, "meta_addr", None) for r in recovered}
    assert make_fixtures.EXT4_ORPHAN_META_ADDR in orphan_addrs
    assert make_fixtures.EXT4_ORPHAN_META_ADDR not in recovered_addrs


def test_confidence_tiers() -> None:
    """RECOV-03: intact vs partial/overwritten vs ext4-zeroed-pointer caveat.

    Pure tier-classification logic over a frozen value object (no pytsk3, no
    image) — mirrors how ``walk._content_fields`` is unit-tested with fakes. The
    classifier must yield:
      * ``intact`` when no data block overlaps an allocated file;
      * ``partial/overwritten`` when a block was reallocated;
      * ``partial/overwritten`` (with a pointers-cleared caveat) for an ext4
        deleted entry whose pointers were zeroed (no recoverable runs, size>0);
      * ``intact`` (resident-from-MFT caveat) for a resident NTFS file with no
        runs.
    """
    from pyautopsy.core.recover import classify_tier  # noqa: PLC0415 (RED stub)

    class _Entry:
        def __init__(
            self,
            *,
            data_blocks=(),
            has_resident_data=False,
            now_allocated=False,
            size=10,
        ):
            self.data_blocks = data_blocks
            self.has_resident_data = has_resident_data
            self.now_allocated = now_allocated
            self.size = size

    allocated = frozenset({100, 101, 102})

    intact_tier, _ = classify_tier(_Entry(data_blocks=(5, 6)), allocated)
    assert intact_tier == "intact"

    overwritten_tier, _ = classify_tier(_Entry(data_blocks=(101,)), allocated)
    assert overwritten_tier == "partial/overwritten"

    # ext4 zeroed pointers: no runs but a non-zero size -> honest overwritten.
    zeroed_tier, zeroed_reason = classify_tier(
        _Entry(data_blocks=(), has_resident_data=False, size=42), allocated
    )
    assert zeroed_tier == "partial/overwritten"
    assert zeroed_reason  # carries a rationale, never bare certainty

    # NTFS resident: no runs but resident data survives in the MFT -> intact.
    resident_tier, _ = classify_tier(
        _Entry(data_blocks=(), has_resident_data=True, size=20), allocated
    )
    assert resident_tier == "intact"


def test_no_overclaiming_copy() -> None:
    """RECOV-03 / D-32: tier + report copy contains no intent/good-bad language.

    Mirrors the Phase-3 WR-02 honesty test: scan every confidence-tier rationale
    string the classifier can emit (and the report section copy) for a forbidden
    substring set. Confidence labels describe data survival, never user intent.
    """
    from pyautopsy.core import recover  # noqa: PLC0415 (RED stub)

    # The module exposes the human-facing copy the report renders for the
    # recovery sections (exact symbol finalized in Wave 1); it must be free of
    # any forbidden intent/good-bad substring.
    copy_blob = getattr(recover, "RECOVERY_REPORT_COPY", None)
    assert copy_blob is not None, (
        "recover.py must expose the honesty-reviewed report copy for scanning"
    )
    haystack = str(copy_blob).lower()
    for forbidden in _FORBIDDEN_INTENT_COPY:
        assert forbidden not in haystack, (
            f"forbidden intent/good-bad copy present: {forbidden!r}"
        )
