---
phase: 01-forensic-foundation
reviewed: 2026-05-30T00:00:00Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - src/pyautopsy/__init__.py
  - src/pyautopsy/util/timeutil.py
  - src/pyautopsy/util/safe_extract.py
  - src/pyautopsy/case/schema.sql
  - src/pyautopsy/case/models.py
  - src/pyautopsy/case/store.py
  - src/pyautopsy/audit/log.py
  - src/pyautopsy/evidence/image.py
  - src/pyautopsy/evidence/integrity.py
  - src/pyautopsy/core/ingest.py
  - src/pyautopsy/cli/main.py
findings:
  critical: 3
  warning: 7
  info: 5
  total: 15
status: issues_found
---

# Phase 1: Code Review Report

**Reviewed:** 2026-05-30T00:00:00Z
**Depth:** deep
**Files Reviewed:** 11
**Status:** issues_found

## Summary

PyAutopsy Phase 1 establishes the forensic foundation: a read-only image seam,
single-pass MD5+SHA-256 hashing with acquisition compare and end-of-run
re-verify, a hardened `safe_extract` jail, an append-only audit log, a
parameterized SQLite case store, and the `run_ingest` orchestrator. The code is
generally well-structured, uses parameterized SQL throughout (no injection found
in `store.py`), confines the audit log path, and opens evidence read-only with no
write/mount path in `image.py`. The read-only INGEST-03 contract holds
structurally at the native seam.

However, deep cross-file analysis surfaced **three CRITICAL forensic-soundness
defects** that undermine the very guarantees this phase exists to lock in:

1. The mounted-source guard (`assert_source_not_mounted`) silently fails to match
   any mountpoint containing non-ASCII bytes, due to a `unicode_escape` mis-decode
   — defeating the P1 read-only guard for a class of evidence paths.
2. `hash_image` silently hashes a **truncated** image on a short/early-empty read
   with no error — producing a digest over partial evidence that re-verify would
   happily confirm, masking acquisition truncation.
3. `run_ingest` violates its own documented audit contract: a failure in open /
   hash / persist (anything other than acquisition/re-verify) propagates **without
   any FAIL audit event** — there is no terminal `ingest.end outcome=FAIL` /
   `ingest.error` handler, so the forensic record of a failed run is incomplete.

There are also several robustness warnings (no transaction wrapping the two COC
inserts, missing source-not-mounted re-check after open, ratio guard absent on
the tar path, and a brittle tar name-rewrite comparison). Full detail below.

## Critical Issues

### CR-01: Mounted-source guard silently bypassed for non-ASCII mountpoints

**File:** `src/pyautopsy/evidence/integrity.py:232`
**Issue:** `_mountpoints` decodes each `/proc/mounts` mountpoint field with
`fields[1].encode("utf-8").decode("unicode_escape")`. `unicode_escape` is a
Latin-1-based codec: it correctly turns the octal escapes `/proc/mounts` uses
(e.g. `\040` → space) but it **corrupts every multi-byte UTF-8 mountpoint**. A
mountpoint `/mnt/café` round-trips to `/mnt/cafÃ©`, so `real_source == mountpoint`
never matches and the guard returns without refusing. The result: an examiner who
points the tool at a **mounted evidence filesystem** whose path contains any
non-ASCII character bypasses the P1/D-05 read-only guard entirely — exactly the
evidence-altering scenario this function exists to refuse. This is a
forensic-soundness failure: the guard gives false assurance.

```python
# Decode ONLY the octal escapes /proc/mounts emits, on the raw bytes, then
# decode the resulting bytes as UTF-8 — never route UTF-8 through unicode_escape.
import re

_OCT = re.compile(rb"\\([0-7]{3})")

def _unescape_mount_field(field: str) -> str:
    raw = field.encode("utf-8")
    raw = _OCT.sub(lambda m: bytes([int(m.group(1), 8)]), raw)
    return raw.decode("utf-8", errors="surrogateescape")

def _mountpoints(mounts_text: str) -> list[str]:
    points: list[str] = []
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        points.append(os.path.realpath(_unescape_mount_field(fields[1])))
    return points
```

### CR-02: `hash_image` silently hashes a truncated image on a short read

**File:** `src/pyautopsy/evidence/integrity.py:137-145`
**Issue:** The streaming loop computes `want = min(chunk, total - offset)` from
`get_size()`, but on a read that returns fewer bytes than `want` — or returns
`b""` before `offset` reaches `total` — it does `if not block: break` and then
returns the digest of whatever was read so far. There is **no check that
`offset == total` after the loop**. For the EWF path, `EWFImgInfo.read`
(`image.py:113`) delegates to `pyewf.handle.read`, which can short-read; for any
source whose reported `get_size()` exceeds the bytes actually retrievable (a
truncated/corrupt acquisition), `hash_image` returns a digest over a **partial
image with no error**. Worse, `reverify` calls the same `hash_image`, so the
truncated digest matches itself and end-of-run re-verify reports PASS — the
integrity layer actively masks acquisition truncation instead of failing loud
(INGEST-02/D-08). A digest that silently covers less than the whole image is a
chain-of-custody defect.

```python
    while offset < total:
        want = min(chunk, total - offset)
        block = source.read(offset, want)
        if not block:
            break
        md5.update(block)
        sha256.update(block)
        offset += len(block)
    if offset != total:
        raise IntegrityError(
            f"short read while hashing source: read {offset} of {total} bytes "
            "(image truncated or unreadable); refusing to record a partial digest"
        )
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}
```

### CR-03: Failed ingest leaves no FAIL audit event for non-integrity errors

**File:** `src/pyautopsy/core/ingest.py:181-243`
**Issue:** The module docstring (lines 22-25) and the `run_ingest` docstring
promise: "a FAIL event always written *before* the exception propagates." That
contract is honored for the acquisition compare (`_compare_acquisition`) and the
re-verify (`_reverify`), but **not** for the rest of the pipeline. If
`open_image`, `hash_image`, `insert_evidence_source`, or `insert_case` raises
(e.g. `ImageOpenError`, `sqlite3.IntegrityError`, a hashing/IO error), control
hits only the `finally: handle.close()` / `finally: store.close()` blocks — there
is **no `except` that writes a terminal `ingest.end outcome=FAIL` /
`ingest.error` event**. The audit log for a failed run therefore ends at
`ingest.open` (or `ingest.hash`) with no recorded failure, breaking the REPORT-02
"audit every action including any error" guarantee and leaving an incomplete
forensic record of what went wrong. The promise in the docstring is false for the
most common failure paths.

```python
    try:
        audit.write("ingest.write_guard", outcome="PASS", source=str(image_path))
        case_id = store.insert_case(Case(name=evidence_id, examiner=examiner))
        # ... existing body ...
        audit.write("ingest.end", outcome="SUCCESS", case_id=case_id,
                    evidence_source_id=source_id, sha256=baseline["sha256"])
    except Exception as exc:  # forensic record must capture every failed run
        audit.write("ingest.error", outcome="FAIL", error=str(exc),
                    error_type=type(exc).__name__)
        raise
    finally:
        store.close()
```
(Place the `handle.close()` failure inside the same guarantee — or wrap the inner
block so an open/hash failure is also audited before re-raising.)

## Warnings

### WR-01: Two chain-of-custody inserts are not wrapped in a single transaction

**File:** `src/pyautopsy/core/ingest.py:184,216` and `src/pyautopsy/case/store.py:175,241`
**Issue:** `insert_case` and `insert_evidence_source` each call
`self.connection.commit()` independently. `run_ingest` inserts the `cases` row
(committed) and only later the `evidence_sources` row. If anything between them
fails (open, hash, or the evidence insert itself), the DB is left with an
**orphaned case row and no evidence-source row** — a partially-written
chain-of-custody record that the audit log (per CR-03) may not even explain. For
forensic reproducibility the case + evidence COC rows should land atomically (or
the case row should be rolled back on failure).
**Fix:** Insert both rows inside one transaction (e.g. add store methods that
defer commit, or a `with store.transaction():` context that commits once at the
end of a successful ingest and rolls back on exception).

### WR-02: No re-check that the source did not become mounted between guard and read

**File:** `src/pyautopsy/core/ingest.py:167,188`
**Issue:** `assert_source_not_mounted` runs once at the start; the image is opened
and hashed later. While the window is small, the read-only contract is the load-
bearing forensic guarantee — and the guard is the only thing enforcing it for the
"mounted filesystem" case. A TOCTOU window exists. More importantly, the guard
only refuses a path that **is itself a mountpoint**; a raw image file *inside* a
read-write mounted filesystem is permitted (documented), which is acceptable, but
the single up-front check should at minimum be re-asserted (cheap) after
`open_image` so a late mount is caught before hashing records a digest.
**Fix:** Re-run `assert_source_not_mounted(image_path)` immediately after
`open_image` (and ideally before re-verify), auditing the re-check.

### WR-03: Compression-ratio bomb guard is missing on the tar path

**File:** `src/pyautopsy/util/safe_extract.py:277-315` vs `373`
**Issue:** `_extract_zip` calls `_check_ratio(info.file_size, info.compress_size, …)`
(line 373), but `_extract_tar` never calls `_check_ratio`. The module docstring
and `ExtractionLimits.max_ratio` advertise a compression-ratio cap as an enforced
bomb defense; for tar archives it is silently not enforced. The per-entry and
total-size streaming caps do bound disk usage, so this is not a full bypass, but
`max_ratio` is documented as a correctness requirement (lines 76-78) and a highly
compressible tar.gz member that stays under the per-entry cap evades the ratio
guard the contract promises. The inconsistency between the two extractors is a
defect against the stated security contract.
**Fix:** In `_extract_tar`, after resolving `member.size`, derive the compressed
size where available and call `_check_ratio`, or document explicitly that tar
streams enforce only absolute caps and remove `max_ratio` from the tar contract.

### WR-04: Tar escape detection via name-equality is brittle for normalizable names

**File:** `src/pyautopsy/util/safe_extract.py:271-275`
**Issue:** The "name rewritten by data filter (escape attempt)" check compares
`filtered.name != original_name.lstrip("/")`. `_confined_target` already rejects
absolute paths and `..`, so by the time this runs the name is relative and
traversal-free — but `data_filter` may still legitimately normalize a benign name
(e.g. collapse `a//b` → `a/b`, or strip a trailing slash) for which
`original_name.lstrip("/")` will not equal `filtered.name`, causing a **false
rejection** of a safe member. Conversely the equality check adds little real
security over `_confined_target`. This risks rejecting legitimate evidence
archives (forensic completeness) on cosmetic name differences.
**Fix:** Compare on a normalized form (`os.path.normpath` of both, POSIX-joined),
or drop the equality assertion and rely on `_confined_target` + `data_filter`'s
own `FilterError`, which is the actual security boundary.

### WR-05: `bare except`-style broad catch promised but `IntegrityError` reraised twice without distinct audit

**File:** `src/pyautopsy/core/ingest.py:282`
**Issue:** In `_compare_acquisition`, `result.raise_for_status()` raises
`IntegrityError` *after* the PASS/FAIL audit event is written — good — but the
function then `return True` only on the PASS path. The control flow is correct,
yet a reader cannot tell from the signature that FAIL never returns. More
substantively: `verify_acquisition` itself can raise `IntegrityError` for an
unrecognized-length supplied hash (`integrity.py:170`) **before** any
`ingest.acquisition_compare` event is written, so an operator who passes a
malformed `--acquisition-hash` gets an `IntegrityError` with **no audit record of
the comparison attempt** — the same FAIL-before-propagate gap as CR-03, scoped to
malformed input.
**Fix:** Wrap the `verify_acquisition` call so a malformed-hash `IntegrityError`
is audited (`outcome="FAIL", reason="unrecognized_hash"`) before propagating.

### WR-06: `insert_case`/`insert_evidence_source` try/except adds nothing

**File:** `src/pyautopsy/case/store.py:161-177,222-243`
**Issue:** Both methods wrap the insert in `try: … except sqlite3.IntegrityError:
raise`. Catching an exception only to re-raise it unchanged is dead control flow
— it does not add context, logging, or cleanup. It misleads readers into thinking
the error is handled. (The `assert cur.lastrowid is not None` after it would also
be stripped under `python -O`, so it should be an explicit check, not an assert,
for a value used as a returned primary key.)
**Fix:** Remove the no-op `try/except`. Replace the `assert cur.lastrowid is not
None` with `if cur.lastrowid is None: raise RuntimeError(...)`.

### WR-07: `verify_acquisition` length-only algorithm detection misclassifies hashes

**File:** `src/pyautopsy/evidence/integrity.py:169`
**Issue:** The algorithm is chosen purely by hex length (32 → MD5, 64 → SHA-256).
A supplied 64-char value is always compared as SHA-256 and a 32-char value always
as MD5, with no validation that the string is actually hex. A supplied hash that
is the right length but contains non-hex characters silently compares as a
mismatch (FAIL) rather than being rejected as malformed input, and a SHA-1 (40
hex) — which the STACK explicitly says EWF images carry and should be verifiable —
is rejected outright as "not recognised." For a tool whose stated stack computes
"MD5 and SHA-1" for EWF interop, length-only md5/sha256 detection is too narrow.
**Fix:** Validate the supplied string is hex (`int(normalised, 16)` guard) and,
if SHA-1 acquisition verification is in scope, compute and compare it too;
otherwise document that only md5/sha256 acquisition hashes are accepted.

## Info

### IN-01: `_open_ewf` catches only `OSError`, but `pyewf.glob/open` may raise other types

**File:** `src/pyautopsy/evidence/image.py:248-255`
**Issue:** Native pyewf errors are not guaranteed to subclass `OSError`; a
`RuntimeError`/`ValueError` from `pyewf.glob`/`handle.open` would escape as a raw
native traceback, defeating the PITFALLS-P5 "actionable hint, not a stack trace"
goal.
**Fix:** Broaden to `except (OSError, RuntimeError, ValueError) as exc:` (or
`except Exception`) and wrap as `ImageOpenError`.

### IN-02: `_assert_case_dir_separate` operates on un-normalized parents

**File:** `src/pyautopsy/core/ingest.py:106-126`
**Issue:** Paths are `.resolve()`d in `run_ingest` before the call, which is good,
but the overlap checks use `in case_dir.parents` / `in image.parents` set
membership. This is correct for resolved paths; however the first branch
(`case_dir == image or case_dir == evidence_dir`) is partly redundant with the
second (`evidence_dir == case_dir`). Minor dead-ish duplication; harmless but
worth tightening for clarity.
**Fix:** Collapse the redundant `case_dir == evidence_dir` / `evidence_dir ==
case_dir` checks into one branch.

### IN-03: `tsk_version` first loop over a single-element tuple is needless

**File:** `src/pyautopsy/evidence/image.py:204-207`
**Issue:** `for attr in ("TSK_VERSION_STR",):` iterates a one-element tuple; it
reads as if more attributes were intended. The subsequent `dir(pytsk3)` scan
already covers `TSK_VERSION_STR`.
**Fix:** Replace the loop with a direct `getattr(pytsk3, "TSK_VERSION_STR", None)`
check, or fold it into the `dir()` scan.

### IN-04: Audit log uses mode `0o644` while case dir may want tighter perms

**File:** `src/pyautopsy/audit/log.py:28`
**Issue:** `_OPEN_MODE = 0o644` makes the audit log world-readable. For an
append-only tamper-evidence record this is usually fine, but in a forensic context
the chain-of-custody log may warrant `0o640`/`0o600` and the file is not chmod'd
if it already exists with looser perms. Not a vulnerability; note for hardening.
**Fix:** Consider `0o600`/`0o640` and document the intended permission posture.

### IN-05: `_sanitize_name` result is recorded but never used as the on-disk path

**File:** `src/pyautopsy/util/safe_extract.py:285,318,365,395`
**Issue:** `on_disk_name` in `MemberRecord` is set to `_sanitize_name(member.name)`,
but the file is actually written to `target` (the confined realpath of the
*original* name), not to the sanitized name. So `on_disk_name` is evidence
metadata that does not reflect the real on-disk location, which is misleading for
anyone reconstructing what was written where.
**Fix:** Record the actual relative on-disk path (`os.path.relpath(target,
dest_real)`) as `on_disk_name`, or rename the field to clarify it is a proposed
sanitized name, not the path used.

---

_Reviewed: 2026-05-30T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
