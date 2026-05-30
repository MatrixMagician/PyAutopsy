"""The ingest orchestrator — the Walking-Skeleton closer (INGEST-01/02/03,
REPORT-01/02, D-01/D-05/D-07/D-08).

:func:`run_ingest` composes the proven lower tiers into a single
forensically-sound operation. In order (01-RESEARCH.md §System Architecture
Diagram):

1. **Resolve + validate paths and run the write-guard.** Refuse a case directory
   that is inside, equal to, or a parent of the evidence path (D-01), and refuse
   a mounted source (:func:`integrity.assert_source_not_mounted`, P1/D-05).
2. **Initialise the case store.** :meth:`CaseStore.create` materialises the D-01
   layout (``logs/``/``exports/``/``case.db``) and persists the ``cases`` row.
3. **Open the evidence read-only** through the single native seam
   (:func:`open_image`) — the source is never written or mounted (INGEST-01/03).
4. **Hash in a single pass** (:func:`integrity.hash_image`, MD5+SHA-256, D-07),
   capturing the baseline. If an ``acquisition_hash`` is supplied,
   :func:`integrity.verify_acquisition` records PASS/FAIL (D-08).
5. **Persist the ``evidence_sources`` COC row** (path, type, digests, byte size,
   TSK version, evidence id, UTC acquired time).
6. **Re-verify at end of run** (:func:`integrity.reverify`); any drift is a loud
   :class:`~pyautopsy.evidence.integrity.IntegrityError` (D-08/INGEST-03).
7. **Audit every action** (start → write-guard → case-init → open → hash →
   acquisition-compare → reverify → end), including the integrity outcome and any
   error, with a FAIL event always written *before* the exception propagates
   (REPORT-02, P12).

Run/wall-clock metadata (timestamps) lives only in the audit log and the COC
``created_utc``/``acquired_utc`` columns — segregated from the analytical content
(digests, byte size, image type) so two runs of the same image produce
byte-identical analytical fields (PITFALLS P3, CLI-02 seed).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore
from pyautopsy.case.models import Case, EvidenceSource
from pyautopsy.evidence import image as image_seam
from pyautopsy.evidence import integrity
from pyautopsy.evidence.integrity import IntegrityError
from pyautopsy.util.timeutil import iso_utc

__all__ = ["IngestError", "IngestResult", "run_ingest"]


class IngestError(Exception):
    """Raised when ingest cannot proceed for a non-integrity reason.

    Used for input-validation failures the CLI turns into a non-zero exit —
    chiefly the D-01 write-guard rejecting a case directory that overlaps the
    read-only evidence path. Integrity mismatches surface as
    :class:`~pyautopsy.evidence.integrity.IntegrityError` instead (D-08).
    """


@dataclass(frozen=True, slots=True)
class IngestResult:
    """The analytical outcome of a successful ingest run.

    Carries only analytical (reproducible) content — never wall-clock metadata —
    so the CLI can print a deterministic summary and the reproducibility test can
    compare two runs (PITFALLS P3).

    Attributes:
        case_id: Surrogate id of the persisted ``cases`` row.
        evidence_source_id: Surrogate id of the persisted ``evidence_sources``
            row.
        sha256: SHA-256 hex digest of the source image.
        md5: MD5 hex digest of the source image.
        byte_size: Total size of the source image in bytes.
        image_type: Detected container format (``"raw"`` or ``"ewf"``).
        acquisition_verified: ``True`` if an acquisition hash was supplied and
            matched; ``None`` if no acquisition hash was supplied.
        success: Always ``True`` for a returned result (failures raise).
    """

    case_id: int
    evidence_source_id: int
    sha256: str
    md5: str
    byte_size: int
    image_type: str
    acquisition_verified: bool | None
    success: bool = True


def _assert_case_dir_separate(case_dir: Path, image: Path) -> None:
    """Refuse a case dir that overlaps the read-only evidence path (D-01).

    The case directory must be wholly separate from the evidence: it may not be
    the evidence file's directory, equal to the image path, inside it, or a
    parent of it. Keeping output away from the source is the load-bearing D-01
    guarantee — all writes land in the case dir, never near the evidence.

    Args:
        case_dir: The resolved target case directory.
        image: The resolved evidence image path.

    Raises:
        IngestError: If the case dir overlaps the evidence path.
    """
    evidence_dir = image.parent
    # Reject when the case dir overlaps the evidence in any direction:
    #   * equals the image path or the evidence directory,
    #   * sits inside the evidence directory (output would land beside evidence),
    #   * is an ancestor of the image (evidence would live under the output).
    if case_dir == image or case_dir == evidence_dir:
        raise IngestError(
            f"case directory {case_dir} overlaps the evidence path {image}; "
            "the case dir must be separate from the read-only evidence (D-01)"
        )
    if evidence_dir == case_dir or evidence_dir in case_dir.parents:
        raise IngestError(
            f"case directory {case_dir} is inside the evidence directory "
            f"{evidence_dir}; the case dir must be separate from the evidence "
            "(D-01)"
        )
    if case_dir in image.parents:
        raise IngestError(
            f"case directory {case_dir} is an ancestor of the evidence "
            f"{image}; the case dir must be separate from the evidence (D-01)"
        )


def run_ingest(
    image: str | os.PathLike[str],
    case_dir: str | os.PathLike[str],
    *,
    examiner: str,
    evidence_id: str,
    acquisition_hash: str | None = None,
) -> IngestResult:
    """Ingest a disk image read-only into a case, hashed, audited, re-verified.

    See the module docstring for the full ordered pipeline. The source is opened
    read-only and never mounted or written; all output is confined to
    ``case_dir``. Any integrity failure (acquisition mismatch or end-of-run
    re-verify drift) is recorded as a FAIL audit event and then raised so the CLI
    exits non-zero (D-08).

    Args:
        image: Path to the evidence image (raw/dd file or first E01 segment).
        case_dir: Target case directory (created with the D-01 layout).
        examiner: Name of the examiner accountable for the case.
        evidence_id: Examiner-supplied evidence identifier.
        acquisition_hash: Optional acquisition hash (md5 or sha256 hex) to
            compare against; a mismatch fails the run loudly (D-08).

    Returns:
        An :class:`IngestResult` with the analytical outcome.

    Raises:
        IngestError: If the case dir overlaps the evidence path (D-01).
        MountedSourceError: If the source path is a mounted filesystem (P1).
        ImageOpenError: If the image cannot be opened read-only.
        IntegrityError: On an acquisition mismatch or re-verify drift (D-08).
    """
    image_path = Path(image).resolve()
    case_path = Path(case_dir).resolve()

    # (1) Resolve + validate paths and run the write-guard (D-01, P1/D-05).
    _assert_case_dir_separate(case_path, image_path)
    integrity.assert_source_not_mounted(image_path)

    # (2) Initialise the case store + persist the COC case row (REPORT-01).
    store = CaseStore.create(case_path)
    audit = AuditLog(case_path)
    audit.write(
        "ingest.start",
        image=str(image_path),
        case_dir=str(case_path),
        examiner=examiner,
        evidence_id=evidence_id,
        acquisition_hash_supplied=acquisition_hash is not None,
    )

    try:
        audit.write("ingest.write_guard", outcome="PASS", source=str(image_path))

        # The two chain-of-custody inserts (cases + evidence_sources) land in a
        # single transaction so a failure between them can never leave an
        # orphaned cases row with no evidence_sources row (WR-01). The commit
        # happens once, after a clean re-verify; any exception rolls both back.
        with store.transaction():
            case_id = store.insert_case(
                Case(name=evidence_id, examiner=examiner)
            )
            audit.write("ingest.case_init", case_id=case_id, examiner=examiner)

            # (3) Open the evidence read-only through the single native seam.
            handle = image_seam.open_image(image_path)
            try:
                # (WR-02) Re-assert the source did not become mounted between
                # the up-front guard and the open, before any digest is taken.
                integrity.assert_source_not_mounted(image_path)
                audit.write(
                    "ingest.write_guard_recheck",
                    outcome="PASS",
                    source=str(image_path),
                )

                image_type = str(handle.image_format)
                tsk = image_seam.tsk_version()
                audit.write(
                    "ingest.open",
                    image=str(image_path),
                    image_type=image_type,
                    byte_size=handle.get_size(),
                    read_only=True,
                    tsk_version=tsk,
                )

                # (4) Single-pass MD5 + SHA-256 (D-07); capture the baseline.
                baseline = integrity.hash_image(handle)
                byte_size = handle.get_size()
                audit.write(
                    "ingest.hash",
                    sha256=baseline["sha256"],
                    md5=baseline["md5"],
                    byte_size=byte_size,
                )

                acquisition_verified = _compare_acquisition(
                    audit, baseline, acquisition_hash
                )

                # (5) Persist the evidence_sources COC row (REPORT-01).
                source_id = store.insert_evidence_source(
                    EvidenceSource(
                        case_id=case_id,
                        evidence_id=evidence_id,
                        path=str(image_path),
                        image_type=image_type,
                        sha256=baseline["sha256"],
                        md5=baseline["md5"],
                        byte_size=byte_size,
                        acquired_utc=iso_utc(),
                        tsk_version=tsk,
                    )
                )

                # (6) End-of-run re-verify (D-08/INGEST-03).
                _reverify(audit, handle, baseline)
            finally:
                handle.close()

        audit.write(
            "ingest.end",
            outcome="SUCCESS",
            case_id=case_id,
            evidence_source_id=source_id,
            sha256=baseline["sha256"],
        )
    except Exception as exc:
        # (CR-03) Every failed run leaves a terminal FAIL audit event before the
        # exception propagates — honouring the docstring/REPORT-02 contract for
        # open/hash/persist failures, not just the integrity checks.
        audit.write(
            "ingest.error",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    finally:
        store.close()

    return IngestResult(
        case_id=case_id,
        evidence_source_id=source_id,
        sha256=baseline["sha256"],
        md5=baseline["md5"],
        byte_size=byte_size,
        image_type=image_type,
        acquisition_verified=acquisition_verified,
    )


def _compare_acquisition(
    audit: AuditLog, baseline: dict[str, str], acquisition_hash: str | None
) -> bool | None:
    """Compare against a supplied acquisition hash, auditing PASS/FAIL (D-08).

    Args:
        audit: The case audit log.
        baseline: The computed digests from :func:`integrity.hash_image`.
        acquisition_hash: The supplied acquisition hash, or ``None``.

    Returns:
        ``True`` if a hash was supplied and matched; ``None`` if none supplied.

    Raises:
        IntegrityError: On a mismatch — a FAIL event is written first (D-08).
    """
    if acquisition_hash is None:
        return None
    try:
        result = integrity.verify_acquisition(baseline, acquisition_hash)
    except IntegrityError as exc:
        # (WR-05) A malformed/unrecognised supplied hash raises before any
        # compare can run; audit the failed comparison attempt before it
        # propagates, closing the same FAIL-before-propagate gap as CR-03.
        audit.write(
            "ingest.acquisition_compare",
            outcome="FAIL",
            reason="malformed_hash",
            error=str(exc),
        )
        raise
    audit.write(
        "ingest.acquisition_compare",
        outcome="PASS" if result.passed else "FAIL",
        algorithm=result.algorithm,
        computed=result.computed,
        supplied=result.supplied,
    )
    result.raise_for_status()
    return True


def _reverify(
    audit: AuditLog, handle: image_seam.ImageHandle, baseline: dict[str, str]
) -> None:
    """Re-verify the source hash at end of run, auditing PASS/FAIL (D-08).

    Args:
        audit: The case audit log.
        handle: The open read-only image handle.
        baseline: The ingest-time digests to compare against.

    Raises:
        IntegrityError: On drift — a FAIL event is written first (D-08).
    """
    try:
        integrity.reverify(handle, baseline)
    except IntegrityError as exc:
        audit.write(
            "ingest.reverify",
            outcome="FAIL",
            baseline_sha256=baseline["sha256"],
            error=str(exc),
        )
        raise
    audit.write(
        "ingest.reverify", outcome="PASS", baseline_sha256=baseline["sha256"]
    )
