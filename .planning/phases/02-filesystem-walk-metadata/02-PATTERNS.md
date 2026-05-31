# Phase 2: Filesystem Walk & Metadata - Pattern Map

**Mapped:** 2026-05-31
**Files analyzed:** 12 (4 new modules, 4 modified, 4+ new test files)
**Analogs found:** 11 / 12 (one new native FS seam has only a partial role-analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/pyautopsy/evidence/filesystem.py` (NEW) | native seam | streaming (generator yield) | `src/pyautopsy/evidence/image.py` | role-match (both are native pytsk3 seams; image=byte-layer, fs=fs-layer) |
| `src/pyautopsy/evidence/filetype.py` (NEW) | utility (libmagic wrapper) | transform | `src/pyautopsy/evidence/image.py` (lazy-import + actionable-error guard) | partial (no existing content-typing module) |
| `src/pyautopsy/evidence/integrity.py` (MODIFY: add 3-digest single-pass helper) | utility | streaming hash | `hash_image` in same file (lines 120-164) | exact (extend existing pattern) |
| `src/pyautopsy/core/walk.py` (NEW) | orchestrator | event-driven (per-entry) + CRUD persist | `src/pyautopsy/core/ingest.py` | exact (same compose-tiers + audit + transaction shape) |
| `src/pyautopsy/case/schema.sql` (MODIFY: add `files` + limitation rows) | schema | n/a | existing `evidence_sources` table (lines 21-37) | exact (typed cols + JSON attributes + FK + index) |
| `src/pyautopsy/case/models.py` (MODIFY: add `FileRow`, limitation model) | model | n/a | `EvidenceSource` dataclass (lines 45-73) | exact |
| `src/pyautopsy/case/store.py` (MODIFY: add `insert_file`/`insert_files`/getters) | service (repository) | CRUD bulk | `insert_evidence_source` (lines 250-285) | exact |
| `src/pyautopsy/cli/main.py` (MODIFY: add `walk`/`inventory` command) | CLI | request-response | `ingest` command (lines 61-130) | exact |
| `tests/fixtures/make_fixtures.py` (MODIFY: add ext4/NTFS/FAT/partitioned builders) | test fixture | file-I/O | `build_tiny_raw_image` + builders (lines 38-143) | role-match |
| `tests/test_filesystem.py` (NEW) | test | n/a | `tests/test_image.py` | exact (seam-level tests) |
| `tests/test_walk.py` (NEW) | test | n/a | `tests/test_ingest.py` + `tests/test_integrity.py` | exact (orchestrator tests) |
| `tests/test_seam_allowlist.py` (NEW) | test (arch guard) | n/a | no analog — D-06 gate is currently a *convention*, not a test | none |
| `tests/test_readonly_guarantee.py` (MODIFY: add `test_source_unchanged_after_walk`) | test | n/a | `test_source_mtime_and_size_unchanged_after_open_and_hash` (lines 24-34) | exact |

## Pattern Assignments

### `src/pyautopsy/evidence/filesystem.py` (NEW native FS seam, D-14)

**Analog:** `src/pyautopsy/evidence/image.py` (the byte-layer native seam — `filesystem.py` is its FS-layer sibling under the new D-14 allowlist)

**Module-docstring + seam-declaration pattern** (image.py lines 1-23): open the docstring by declaring this is part of the native-seam allowlist, cite D-14, state "no native type escapes this module," and cite read-only/never-mount (D-05/P1). Mirror image.py's tone exactly — it is the canonical seam doc.

**Import + `__all__` style** (image.py lines 25-52):
```python
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import pytsk3   # the ONLY new module (besides image.py) permitted this import (D-14)

__all__ = [ ... sorted ... ]
```

**Value-object-yielding pattern** (image.py `ImageHandle`, lines 131-173): convert native `File`/`Directory`/`meta`/`name` into a frozen `@dataclass(frozen=True, slots=True)` `FileEntry` value object so no `pytsk3` type leaks. Mirror `ImageHandle`'s frozen-slots dataclass + a `ReadableImage`-style `Protocol` (lines 71-87) for any byte-reader closure the entry carries. Use RESEARCH Pattern 1 (`enumerate_volumes`/`open_fs`) and Pattern 2 (`walk_fs` recursion with `_seen` inode guard).

**Custom error class** (image.py `ImageOpenError`, lines 55-61): define a `FilesystemError` (or reuse) for seam-edge failures; carry an examiner-facing message, never a raw native trace. The D-20 `OSError` from `FS_Info` is caught by the *orchestrator*, not here (seam translates/raises, orchestrator records the limitation finding — RESEARCH Pattern 7).

**Decode-untrusted-names rule** (RESEARCH Security V5): `name_obj.name.decode("utf-8", "replace")`; skip `.`/`..`; treat names as data only.

---

### `src/pyautopsy/evidence/filetype.py` (NEW python-magic wrapper, D-19)

**Analog:** `src/pyautopsy/evidence/image.py` — specifically the **lazy-import + actionable-error guard** for an optional/ambiguous native dep (`_open_ewf`, lines 233-263, and the `pyewf` TYPE_CHECKING import lines 36-37).

**Binding-collision guard** (mirror the PITFALLS-P5 pyewf hint in image.py lines 239-246). RESEARCH Pitfall 1 is the load-bearing concern — `file-magic` 0.4.0 is the currently-installed `magic` and lacks `from_buffer`:
```python
import magic
if not hasattr(magic, "from_buffer"):
    raise ImportError(
        "the installed 'magic' module is file-magic, not python-magic; "
        "install python-magic==0.4.27 (the two collide on the 'magic' name)."
    )
```
Surface this as an actionable message exactly like `ImageOpenError`'s "install pyautopsy[ewf] ... libewf-dev" hint.

**Core typing pattern** (RESEARCH Pattern 6): read head bytes via the TSK `File` object (read-only), `magic.from_buffer(head, mime=True)`; empties → `"inode/x-empty"`; non-regular → `None`/derived. Keep `magic` isolated here so the walk orchestrator stays testable with a fake.

---

### `src/pyautopsy/evidence/integrity.py` (MODIFY — add 3-digest single-pass helper, D-17)

**Analog:** `hash_image` in the same file (lines 120-164) — extend, do not duplicate.

**Exact pattern to extend** (lines 146-164): one `while offset < total` loop updating multiple `hashlib` objects, then a short-read guard. Add SHA-1 to the existing MD5+SHA-256 trio:
```python
md5, sha1, sha256 = hashlib.md5(), hashlib.sha1(), hashlib.sha256()
# ... single loop: md5.update(block); sha1.update(block); sha256.update(block)
```
**Critical conventions to preserve from `hash_image`:**
- `if chunk <= 0: raise ValueError(...)` (line 143-144)
- short-read → loud failure (`IntegrityError`) NOT a partial digest (lines 158-163). For per-file (D-17), RESEARCH Pattern 5 returns `None` on a short/truncated read (record null hashes + reason) rather than raising — this is the documented per-file divergence; keep the no-partial-digest principle.
- `_DEFAULT_CHUNK` is 8 MiB (line 48); per-file uses `1 << 20` (1 MiB) per RESEARCH — both fine, just be explicit.
- Add EMPTY-file sentinel digests (RESEARCH Pattern 5) for the zero-length case.
- The `ReadableSource` Protocol (lines 80-88) is the testability contract — the per-file hasher should consume bytes via a `read_random`-style callable from the seam, kept native-free.

---

### `src/pyautopsy/core/walk.py` (NEW orchestrator, mirrors ingest.py)

**Analog:** `src/pyautopsy/core/ingest.py` — the canonical orchestrator. Copy its full shape.

**Import block** (ingest.py lines 33-47):
```python
from __future__ import annotations
from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore
from pyautopsy.case.models import ...        # add FileRow
from pyautopsy.evidence import image as image_seam
from pyautopsy.evidence import filesystem as fs_seam   # NEW
from pyautopsy.evidence import integrity
from pyautopsy.evidence import filetype                # NEW
from pyautopsy.util.timeutil import iso_utc, from_epoch_utc
__all__ = ["WalkError", "WalkResult", "run_walk"]
```

**Error + result dataclass** (ingest.py `IngestError` lines 50-57, `IngestResult` lines 60-89): define `WalkError` and a frozen-slots `WalkResult` carrying only analytical/reproducible counts (files inventoried, deleted count, volumes walked, limitations recorded) — never wall-clock (PITFALLS P3).

**Transaction + audit composition** (ingest.py lines 170-270): this is the load-bearing pattern. Copy:
1. `audit.write("walk.start", ...)` then a `try:` wrapping the work.
2. Bulk inserts inside **`with store.transaction():`** (lines 188-189) so a batch is atomic (WR-01).
3. Audit each stage: `walk.start` / `walk.volume` / `walk.limitation` / `walk.end` (RESEARCH diagram lines 159-161).
4. **FAIL-before-propagate** `except Exception as exc:` block (lines 258-268) writing `walk.error` outcome=FAIL BEFORE `raise` (CR-03 contract — REPORT-02).
5. `finally: store.close()` (lines 269-270).

**Per-entry processing** (RESEARCH diagram lines 152-160): for each `FileEntry` → normalize MACB via RESEARCH Pattern 4 (`from_epoch_utc`/`iso_utc`, FAT `--timezone` rebase + `local-time-inferred` flag), gate hashing/typing on `meta.type == REG` (Pitfall 5), build a `FileRow`, batch.

**D-20 limitation handling** (RESEARCH Pattern 7): catch `OSError` per-volume, `audit.write("walk.limitation", ...)`, persist a limitation row, `continue`. Never abort the whole run (Pitfall 6).

---

### `src/pyautopsy/case/schema.sql` (MODIFY — add `files` table + limitation rows)

**Analog:** the `evidence_sources` table (lines 21-37) — copy its column+index pattern verbatim.

**Pattern to copy** (lines 22-37):
```sql
CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_source_id INTEGER NOT NULL REFERENCES evidence_sources (id),
    -- typed core columns: path, name, parent_addr, meta_addr (inode/MFT),
    -- volume_id, volume_offset, size, alloc/unalloc status, fs_type,
    -- uid, gid, mode, file_type, md5, sha1, sha256,
    -- mtime_utc, atime_utc, ctime_utc, crtime_utc, timestamp_source,
    attributes   TEXT NOT NULL DEFAULT '{}'   -- JSON blackboard (D-02): nano, local-time-inferred, assumed_timezone, hash-skip reason
);
CREATE INDEX IF NOT EXISTS idx_files_evidence_source_id ON files (evidence_source_id);
```
**Conventions (header comment lines 1-8 + existing tables):** every table = typed core columns + single JSON `attributes TEXT NOT NULL DEFAULT '{}'`; timestamps stored as UTC ISO-8601 strings (D-10); FK `REFERENCES` + a `CREATE INDEX IF NOT EXISTS` on the FK (lines 36-37). `IF NOT EXISTS` makes the addition non-destructive to existing `case.db` (RESEARCH Runtime State). Limitation findings: either a `volume_limitations` table (same shape) or rows in `files`-adjacent — Claude's discretion, but use the same typed+attributes pattern.

---

### `src/pyautopsy/case/models.py` (MODIFY — add `FileRow` + limitation model)

**Analog:** `EvidenceSource` dataclass (lines 45-73) — copy exactly.

**Pattern to copy** (lines 45-73):
```python
@dataclass(frozen=True, slots=True)
class FileRow:
    """..."""
    evidence_source_id: int
    path: str
    # ... required typed fields ...
    md5: str | None = None
    sha1: str | None = None
    sha256: str | None = None
    # ... MACB UTC strings, None = "not recorded" ...
    attributes: dict[str, Any] = field(default_factory=dict)
    id: int | None = None
```
**Conventions (module docstring lines 1-10 + EvidenceSource):** `@dataclass(frozen=True, slots=True)`; `attributes: dict[str, Any] = field(default_factory=dict)` last-but-one; `id: int | None = None` last; optional/unknown fields default `None` meaning "not yet known"; timestamps are UTC ISO-8601 strings (D-10). Add `FileRow` (and any limitation model) to `__all__` (line 17).

---

### `src/pyautopsy/case/store.py` (MODIFY — add `insert_file`/`insert_files`/getters)

**Analog:** `insert_evidence_source` (lines 250-285) and `get_evidence_source` (lines 287-316).

**Insert pattern to copy** (lines 250-285):
```python
def insert_file(self, file_row: FileRow) -> int:
    cur = self.connection.execute(
        "INSERT INTO files (evidence_source_id, path, ...) VALUES (?, ?, ...)",
        ( file_row.evidence_source_id, file_row.path, ...,
          json.dumps(file_row.attributes, sort_keys=True) ),
    )
    self._commit_unless_in_transaction()       # lines 280; transaction-aware
    if cur.lastrowid is None:
        raise RuntimeError("INSERT INTO files did not return a row id")
    return cur.lastrowid
```
**Bulk variant `insert_files`** (Don't-Hand-Roll / WR-01): use `executemany` inside the caller's `transaction()`; still call `_commit_unless_in_transaction()` so it composes with the orchestrator's outer transaction (lines 179-182). NO raw SQL anywhere but this class (module docstring lines 1-11).

**Getter pattern** (lines 299-316): `SELECT * ... fetchone()` → reconstruct `FileRow`, `attributes` via the module-level `_load_attributes` helper (lines 319-329). Import `FileRow` at top (line 25) and re-export from `case/__init__.py` (`__all__` line in that file).

---

### `src/pyautopsy/cli/main.py` (MODIFY — add `walk`/`inventory` command)

**Analog:** the `ingest` command (lines 61-130).

**Command pattern to copy** (lines 61-130): `@app.command()`, `Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)]` for the image (lines 63-71), `Annotated[..., typer.Option("--case"/"--examiner"/...)]` for options. Add **`--timezone` (default `"UTC"`)** and **`--max-hash-size`** options per D-16/D-17. Thin shell: call `run_walk(...)`, then the `except (...Error) as exc:` → `typer.echo(err=True)` + `raise typer.Exit(code=_INTEGRITY_EXIT_CODE)` pattern (lines 110-112), then an `typer.echo` summary (lines 121-130). Reuse `_INTEGRITY_EXIT_CODE` (line 36).

**`--timezone` validation** (RESEARCH Security V5): validate via `zoneinfo.ZoneInfo(tz)` (raises on a bad zone) before passing to the orchestrator.

---

### `tests/test_filesystem.py` (NEW — seam-level tests)

**Analog:** `tests/test_image.py`.

**Pattern to copy** (test_image.py lines 1-118): module docstring citing the requirement; import the public seam surface; `def test_...(fixture) -> None:` with `try/finally: handle.close()` for resources (lines 26-37); `@pytest.mark.parametrize` for the routing/fs-type matrix (lines 55-73); actionable-error assertions checking message substrings (lines 106-110). Add new fixtures (ext4/NTFS/FAT/partitioned images) via `conftest.py` (mirror `tiny_raw_image`, conftest lines 37-47).

---

### `tests/test_walk.py` (NEW — orchestrator tests, META-01..05 + D-20)

**Analog:** `tests/test_ingest.py` (orchestrator composition) + `tests/test_integrity.py` (hash assertions).

Cover the RESEARCH "Phase Requirements → Test Map" (RESEARCH lines 500-511): inventory-includes-deleted, MACB-UTC-and-FAT-flagged, no-naive-datetimes (every MACB column re-parses to aware + ends `+00:00`), ownership/mode, three-digest-single-pass (vs a direct `hashlib` pass + empty-file sentinels + `--max-hash-size` skip), filetype-by-content, unsupported-volume-records-limitation. **Exact row-count assertions per fixture** (RESEARCH Sampling Rate — the "every file" Nyquist signal).

---

### `tests/test_seam_allowlist.py` (NEW — arch guard; NO analog)

**No analog — this is genuinely new.** The D-06/D-14 seam rule is currently only a *convention* (verified: `grep "import pytsk3"` matches only `evidence/image.py` today). Make it executable: scan `src/` for `import pytsk3` / `import pyewf` (`from __future__ import` is fine to ignore) and assert the importing files are EXACTLY the D-14 allowlist `{evidence/image.py, evidence/filesystem.py}`. Use a plain file walk + regex over `src/pyautopsy/**/*.py`; no analog test exists to copy structure from, so model the assertion style on the existing simple unit tests.

---

### `tests/test_readonly_guarantee.py` (MODIFY — add `test_source_unchanged_after_walk`)

**Analog:** `test_source_mtime_and_size_unchanged_after_open_and_hash` in the same file (lines 24-34).

**Pattern to copy** (lines 24-34): stat `before`, run the walk over an opened handle, stat `after`, assert `st_mtime_ns` and `st_size` unchanged (D-05/P1). Mirror exactly for the full walk path (META-01..05 over the fs fixtures).

---

## Shared Patterns

### Audit-every-stage + FAIL-before-propagate (REPORT-02 / CR-03)
**Source:** `src/pyautopsy/core/ingest.py` lines 170-268
**Apply to:** `core/walk.py`
```python
audit.write("walk.start", ...)
try:
    with store.transaction():
        ...  # walk.volume / walk.limitation per volume
    audit.write("walk.end", outcome="SUCCESS", ...)
except Exception as exc:
    audit.write("walk.error", outcome="FAIL", error=str(exc),
                error_type=type(exc).__name__)   # written BEFORE raise
    raise
finally:
    store.close()
```

### Atomic bulk persistence (WR-01)
**Source:** `src/pyautopsy/case/store.py` `transaction()` lines 149-182 + `_commit_unless_in_transaction` lines 179-182
**Apply to:** `store.insert_file`/`insert_files`, driven from `core/walk.py`
All file rows for a volume (or the whole walk) land in one `with store.transaction():` block; per-insert methods defer their commit so the batch is atomic and a partial inventory is never persisted.

### UTC-everywhere timestamp normalization (D-10 / META-02 / P4)
**Source:** `src/pyautopsy/util/timeutil.py` (`from_epoch_utc` lines 57-70, `iso_utc` lines 30-54)
**Apply to:** every MACB value in `core/walk.py`
```python
from pyautopsy.util.timeutil import from_epoch_utc, iso_utc
# ext4/NTFS: iso_utc(from_epoch_utc(secs))   -> ends "+00:00"
# FAT: datetime.fromtimestamp(secs, tz=walk_tz) -> iso_utc(...) + flag local-time-inferred
# secs == 0 -> None (never 1970)   (Pitfall 3)
```
`iso_utc` **rejects naive datetimes** (lines 49-53) — routing every value through it makes the "no naive datetimes" invariant (success-criterion 2) structurally enforced.

### Read-only / never-mount boundary (D-05 / P1 / ASVS V4)
**Source:** `src/pyautopsy/evidence/integrity.py` `assert_source_not_mounted` lines 287-328 (reuse as-is)
**Apply to:** all file content + signature reads go through the seam's TSK `File.read_random` (RESEARCH Anti-Patterns), never a mount. `core/walk.py` may re-assert `assert_source_not_mounted` like `ingest.py` does at lines 167 & 199.

### Native-binding isolation + actionable lazy-import hint (D-14 / D-06 / PITFALLS P5)
**Source:** `src/pyautopsy/evidence/image.py` — frozen value-object yield (`ImageHandle` lines 131-173), `Protocol` contract (lines 71-87), lazy-import-with-install-hint (`_open_ewf` lines 233-246)
**Apply to:** `evidence/filesystem.py` (FileEntry value objects, no native type escapes) and `evidence/filetype.py` (python-magic binding-collision guard). Keeps all `pytsk3` behind the 2-file allowlist and `magic` isolated for testability.

### Frozen typed model ↔ typed-columns+JSON-attributes round-trip (D-02)
**Source:** `case/models.py` `EvidenceSource` (lines 45-73) ↔ `case/schema.sql` `evidence_sources` (lines 21-37) ↔ `case/store.py` insert/get (lines 250-316)
**Apply to:** `FileRow` ↔ `files` table ↔ `insert_file`/`get_file`. Typed core columns for known fields; everything heterogeneous (nano-seconds, `local-time-inferred`, `assumed_timezone`, hash-skip reason, encryption hint) → JSON `attributes`. `json.dumps(..., sort_keys=True)` (store.py lines 213, 277) keeps serialization deterministic.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/test_seam_allowlist.py` | test (arch guard) | n/a | The D-06/D-14 seam rule is enforced today only by convention (grep confirms only `evidence/image.py` imports pytsk3). No existing test asserts the allowlist; Phase 2 makes the gate executable for the first time. Model assertion style on existing simple unit tests; structure is novel. |
| `src/pyautopsy/evidence/filetype.py` | utility | transform | No existing content-typing/transform module. Borrows only the *lazy-import + actionable-error* shape from `image.py::_open_ewf`; the libmagic core (RESEARCH Pattern 6) has no in-repo precedent. |

## Metadata

**Analog search scope:** `src/pyautopsy/{evidence,core,case,cli,util,audit}/`, `tests/`, `tests/fixtures/`, `pyproject.toml`
**Files scanned:** 10 source files read in full + 4 test files + schema + pyproject + case `__init__`
**Seam-gate state:** D-06 currently a convention (`grep "import pytsk3" src/` → only `evidence/image.py`); D-14 evolves it to a 2-file allowlist enforced by the new `tests/test_seam_allowlist.py`.
**Dependency action (RESEARCH):** add `python-magic==0.4.27` to `[project.dependencies]`; ensure `file-magic` is absent from the env (Pitfall 1). `pytsk3==20260520` already pinned (pyproject line 27); `pyewf` is the `[ewf]` extra (line 35).
**Pattern extraction date:** 2026-05-31
