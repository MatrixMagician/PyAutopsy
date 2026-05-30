# Phase 1: Forensic Foundation - Research

**Researched:** 2026-05-30
**Domain:** Forensically-sound disk-image ingest on The Sleuth Kit (Python/Linux CLI) — the read-only spine (image open + integrity hashing + SQLite case store + audit log + safe-extraction jail) that every later analysis phase writes into.
**Confidence:** HIGH for the core stack, pytsk3/pyewf API, tarfile filter API, and SQLite patterns (verified against PyPI + official docs + canonical recipes); MEDIUM for exact decompression-bomb thresholds (sane defaults, configurable) and the cp314 wheel/native-build interaction (see Environment Availability).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Case Store & Layout**
- **D-01:** The case is a **directory** created by the tool, containing a single **SQLite database** (`case.db`) plus subdirectories `logs/` (audit log), `exports/` (recovered files / reports in later phases), and metadata. The read-only evidence image is **never** placed inside or modified.
- **D-02:** SQLite schema = **typed core columns + a JSON `attributes` column** so heterogeneous later producers never force a migration. Phase 1 creates the schema and the `case`/chain-of-custody and `audit`/evidence tables; later phases add rows/tables.
- **D-03:** SQLite is the case store: single-file, archivable, hashable for chain of custody, transactional, queryable.

**Image Adapter & Read-Only Handling**
- **D-04:** Use **pytsk3** (`Img_Info`) to open raw/dd images directly. For **E01/EWF**, wrap **pyewf** as a `pytsk3.Img_Info` subclass adapter. pyewf is an optional `[ewf]` install extra.
- **D-05:** Evidence is opened **`O_RDONLY` at the byte layer via TSK** — the source is **never mounted**. A hard guard forbids any write path to the source.
- **D-06:** Isolate all native `pytsk3`/`pyewf` calls behind one module seam (e.g. `evidence/image.py`) so the rest of the system is testable without an image and the native dependency is swappable.

**Hashing & Integrity**
- **D-07:** Compute **MD5 + SHA-256 in a single streaming pass** (configurable chunk size), not two passes. SHA-256 is the forensic primary; MD5 retained for legacy hash-set interop.
- **D-08:** If the user supplies an acquisition hash, compare and record PASS/FAIL. **Re-verify the source hash at end of run**; any mismatch is a loud, non-zero-exit failure recorded in the audit log.

**Audit Log**
- **D-09:** Append-only **JSON Lines** file (`logs/audit.jsonl`) — one structured event per line (timestamp UTC, action, inputs, hashes, parameters, tool+TSK versions, outcome, errors). Written **only** to the case directory.
- **D-10:** All timestamps are **UTC, timezone-aware ISO-8601** from the very first phase.

**Safe-Extraction Jail**
- **D-11:** A dedicated `safe_extract` utility is the only sanctioned way to expand any archive/container. It **canonicalizes and confines** every member path to the destination (reject Zip Slip), **refuses symlinks and special files**, and enforces hard limits: max total uncompressed size, max compression ratio, max nesting depth, max entry count. **Phase-completion gate**, validated against a malicious-archive fixture.

**CLI Surface**
- **D-12:** Use **Typer**. Phase 1 ships `pyautopsy ingest <image> --case <case-dir> --examiner <name> --evidence-id <id> [--acquisition-hash <hash>]`. The full pipeline `analyze` command is assembled in Phase 3.

**Project Scaffolding**
- **D-13:** **src layout**, `pyproject.toml` with **hatchling** backend, **pytest** (`tmp_path` fixtures), **ruff** + **mypy**. Pin dated TSK/pyewf releases. Document native deps (`sleuthkit`/`libtsk`, `libewf`) in README; provide a Containerfile.

### Claude's Discretion
- Exact SQLite table/column names and module/file names — consistent with D-02.
- Chunk size for streaming hashing, exact bomb-limit thresholds — sane defaults, configurable.
- Whether the audit log is *also* mirrored into a SQLite table in addition to JSONL.

### Deferred Ideas (OUT OF SCOPE)
- Filesystem walk, MACB metadata, per-file hashing → **Phase 2**
- Deleted-file recovery, orphans, NSRL/custom hash filtering → **Phase 4**
- Log parsing, shared event model, super-timeline, keyword/IOC search → **Phase 5**
- Timeline + human/JSON report rendering, single-command `analyze` pipeline → **Phase 3**
- File carving, journald/auditd/wtmp parsers, YARA, CASE/UCO export, plaso backend, dfVFS, qcow2 → **v2**
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **INGEST-01** | Ingest a disk image (raw/dd and E01/EWF) for analysis | pytsk3 `Img_Info(path)` for raw/dd; `EWFImgInfo(pytsk3.Img_Info)` adapter over `pyewf.handle` for E01 (canonical recipe below, §Code Examples). Single seam `evidence/image.py` (D-06). |
| **INGEST-02** | Verify integrity: MD5 + SHA-256, compare against supplied acquisition hash when provided | Single-pass streaming `hashlib.md5` + `hashlib.sha256` over a chunked read (§Code Examples). Compare → PASS/FAIL recorded; for E01, `pyewf` also exposes stored-vs-computed MD5/SHA-1 to cross-check. |
| **INGEST-03** | Evidence never modified — read-only, never mounted, output to separate case dir, hash re-verified at end | TSK `Img_Info` opens byte-level read-only — never mounts. Hard write-guard + mounted-path refusal (P1). End-of-run re-hash + compare (D-08). Case dir is separate (D-01). |
| **INGEST-04** | Extract/parse archives safely, rejecting Zip Slip and decompression bombs | `safe_extract` jail: `tarfile` `filter='data'` (3.12+) + explicit path-confinement + bomb limits (size/ratio/depth/count) + symlink/special-file refusal. zipfile needs manual confinement (no built-in filter). §Safe-Extraction. |
| **REPORT-01** | Record case / chain-of-custody metadata (case ID, examiner, evidence ID, acquisition source, tool + versions, timestamps) | `cases` + `evidence_sources` tables (typed + JSON `attributes`). Tool version via `importlib.metadata.version("pyautopsy")`; TSK version via `pytsk3.TSK_VERSION_STR` / `Img_Info`. UTC ISO-8601 timestamps (D-10). |
| **REPORT-02** | Append-only audit log of actions (inputs, hashes, parameters, tool versions, start/end times, errors) | `logs/audit.jsonl` JSONL, one event/line, opened `O_APPEND`, fsync per write, written only to case dir (D-09). |
</phase_requirements>

## Summary

This is a **Walking Skeleton** phase: the goal is the thinnest end-to-end forensically-sound slice — scaffold the project, open one real read-only image, write one real SQLite case-store row, emit the audit log, and harden the extraction jail — proving the spine all later phases build on. Every architectural decision is already locked in CONTEXT.md and traces to the three research docs; this research confirms the **current package versions, the exact native APIs, and the concrete defensive patterns** the planner needs to write tasks against.

The five load-bearing facts verified this session: (1) **pytsk3 20260520** ships a Python-3.14 wheel and opens raw images read-only by construction via `Img_Info(path)`; (2) the **canonical `EWFImgInfo(pytsk3.Img_Info)` adapter** (init with `TSK_IMG_TYPE_EXTERNAL`, override `read(offset,size)`/`get_size()`/`close()` over a `pyewf.handle`) is stable and reproduced verbatim from two authoritative sources; (3) **`tarfile`'s `filter='data'`** (Python 3.12+) blocks Zip Slip, absolute paths, symlinks, hardlinks, and device files — but **does NOT** stop decompression bombs, so the jail must add explicit size/ratio/count/depth caps; (4) **`zipfile` has no equivalent filter** — Zip Slip confinement must be hand-written for archives; (5) **SQLite stdlib** is the right store, but WAL mode + wall-clock-free analytical content are needed for the reproducibility bar.

**Primary recommendation:** Build the MVP-light variant from STACK.md — pytsk3 + pyewf + stdlib `sqlite3` + `hashlib` + Typer. **Do NOT add dfVFS, plaso, or qcow2 in Phase 1** (deferred to v2/timeline extras). Pin the dated pytsk3/pyewf releases, confine all native calls to one module, store all timestamps as tz-aware UTC ISO-8601, and treat the safe-extraction jail as a hard phase-completion gate validated by a malicious-archive fixture.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read-only image open (raw/E01) | Native (libtsk/libewf via pytsk3/pyewf) | Python seam `evidence/image.py` | TSK opens byte-level RO; Python only orchestrates. The single native boundary (D-06). |
| Integrity hashing (MD5+SHA-256) | Python (`hashlib`, stdlib) | — | Pure-Python streaming over the image read API; no native dep beyond the read source. |
| Case store (schema + writes) | Python (`sqlite3`, stdlib) | — | Single-file DB owned entirely by Python; the normalized spine (D-02/D-03). |
| Audit log (JSONL) | Python (`json` + `os.open O_APPEND`) | — | Append-only file in the case dir; no external dep (D-09). |
| Safe-extraction jail | Python (`tarfile` filter + manual confinement) | — | Security control; stdlib `tarfile`/`zipfile` + explicit guards (D-11). |
| CLI surface | Python (Typer on Click) | — | Type-hint-driven command parsing; no native dep (D-12). |
| Read-only write-guard | Python (path/mount checks) | OS (`os.stat`, `/proc/mounts`) | Refuse mounted-source paths and any write path to source (P1). |

**Tier-correctness note for the planner:** Only `evidence/image.py` may import `pytsk3`/`pyewf`. Hashing, case store, audit, jail, and CLI are pure-Python tiers and must be unit-testable with `tmp_path` fixtures and *no* real image.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **Python** | 3.11–3.14 (target 3.12+) | Implementation language | Modern type hints; pytsk3 wheels cover 3.10–3.14. `[VERIFIED: host is 3.14.5; pytsk3 ships cp314 wheel]` Note: `tarfile` default filter is `'data'` only on 3.14 (§Pitfalls). |
| **pytsk3** | 20260520 (pin) | Python-3 bindings to libtsk | Direct RO access: `Img_Info`, `Volume_Info`, `FS_Info`. `[VERIFIED: PyPI — latest 20260520, cp314 wheel exists]` |
| **libewf-python (pyewf)** | 20240506 (pin) | E01/EWF access via `Img_Info` adapter | E01 is the dominant DFIR container. Optional `[ewf]` extra. `[VERIFIED: PyPI — latest 20240506; sdist build needs libewf-dev]` |
| **sqlite3** | stdlib | Case store | Single-file, transactional, hashable for COC (D-03). `[VERIFIED: stdlib]` |
| **hashlib** | stdlib | MD5 + SHA-256 integrity | Streaming one-pass hashing (D-07). `[VERIFIED: stdlib]` |
| **Typer** | 0.26.3 (pin `>=0.12,<1`) | CLI | Type-hint-driven, on Click. `[VERIFIED: PyPI — latest 0.26.3]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **Rich** | 15.0.0 | Progress over multi-GB hashing | Optional UX; pairs with Typer. `[VERIFIED: PyPI — latest 15.0.0]` |
| **pydantic** | 2.13.4 | Typed audit-event / COC models | Optional in Phase 1 (dataclasses suffice); pays off as schema grows. `[VERIFIED: PyPI — latest 2.13.4]` |
| **tarfile / zipfile** | stdlib | Archive expansion in the jail | `tarfile` has `filter='data'`; `zipfile` needs manual confinement. `[VERIFIED: docs.python.org]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled pyewf adapter | **dfVFS** | dfVFS wraps pytsk3+pyewf+pyqcow behind one RO API but pulls a large dep tree. **Deferred** — overkill for a 2-format Walking Skeleton (STACK.md). |
| pytsk3 bindings | TSK CLI (`fls`/`icat`) via subprocess | Brittle text parsing; bindings give structured objects. Keep subprocess as a later fallback only. |
| Typer | argparse | argparse only if zero-dep stdlib CLI is mandatory; verbose with subcommands. |
| stdlib `sqlite3` | SQLAlchemy / pydantic-backed ORM | ORM is overkill for a single-file forensic store; raw `sqlite3` + repository methods is simpler and fully inspectable. |

**Installation:**
```bash
# Core (raw/dd only)
pip install "pytsk3==20260520" "typer>=0.12,<1" "rich>=13"
# E01 support (the [ewf] extra) — needs system libewf-dev/libewf
pip install "libewf-python==20240506"
# Dev
pip install pytest ruff mypy hatchling
```

**Native system dependencies (the #1 install failure mode — must be in README + Containerfile):**
```bash
# Fedora / RHEL
sudo dnf install -y sleuthkit sleuthkit-devel libewf libewf-devel gcc gcc-c++ python3-devel
# Debian / Ubuntu / Kali
sudo apt install -y libtsk-dev libewf-dev build-essential python3-dev
```
`[CITED: STACK.md Installation; pytsk3 wheels bundle libtsk so a raw-only install may not need sleuthkit-devel — but libewf-python is sdist-only and DOES need libewf-dev to build]`

**Version verification (run this session):**
- `pip index versions pytsk3` → **20260520** (cp314 wheel present) `[VERIFIED: PyPI 2026-05-30]`
- `pip index versions libewf-python` → **20240506** (sdist, 2.7 MB tarball, builds against libewf) `[VERIFIED: PyPI 2026-05-30]`
- `pip index versions typer` → **0.26.3** · `rich` → **15.0.0** · `pydantic` → **2.13.4** · `hatchling` → **1.29.0** `[VERIFIED: PyPI 2026-05-30]`

## Package Legitimacy Audit

slopcheck 0.6.1 ran `slopcheck install pytsk3 libewf-python typer rich pydantic hatchling pytest ruff mypy` — **all 9 returned `[OK]`** on PyPI.

| Package | Registry | Age | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-------------|-----------|-------------|
| pytsk3 | PyPI | est. ~10 yrs (releases since 2016) | github.com/py4n6/pytsk | [OK] | Approved |
| libewf-python | PyPI | est. ~5 yrs (releases since 2020) | github.com/libyal/libewf (not linked on PyPI) | [OK] (note: "no source repository linked") | Approved — libyal/Joachim Metz canonical project; repo verified manually |
| typer | PyPI | est. ~5 yrs | github.com/fastapi/typer | [OK] | Approved |
| rich | PyPI | est. ~6 yrs | github.com/Textualize/rich | [OK] | Approved |
| pydantic | PyPI | est. ~6 yrs | github.com/pydantic/pydantic | [OK] | Approved |
| hatchling | PyPI | est. ~4 yrs | github.com/pypa/hatch | [OK] | Approved |
| pytest | PyPI | est. ~15 yrs | github.com/pytest-dev/pytest | [OK] | Approved |
| ruff | PyPI | est. ~3 yrs | github.com/astral-sh/ruff | [OK] | Approved |
| mypy | PyPI | est. ~12 yrs | github.com/python/mypy | [OK] | Approved |

**Packages removed due to [SLOP]:** none.
**Packages flagged [SUS]:** none. (`libewf-python` carries an advisory "no source repository linked on PyPI" — not a slop signal; it is the canonical libyal EWF binding. No postinstall network scripts; build is a standard C-extension compile.)

## Architecture Patterns

### System Architecture Diagram

```
  CLI: pyautopsy ingest <image> --case <dir> --examiner --evidence-id [--acquisition-hash]
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Ingest orchestrator (core)                                       │
  │   1. Resolve + validate paths ──► write-guard: refuse mounted /   │
  │      writable source; case dir MUST be separate from image        │
  └───────┬───────────────────────────┬──────────────────────────────┘
          │                           │
          ▼                           ▼
  ┌───────────────────┐      ┌──────────────────────────────┐
  │ Case init (case/) │      │ Evidence open (evidence/      │
  │  create <dir>/,    │      │   image.py — ONLY pytsk3/pyewf│
  │  logs/, exports/   │      │   importer)                   │
  │  open case.db,     │      │   raw  → Img_Info(path)       │
  │  WAL, run schema   │      │   E01  → EWFImgInfo(handle)   │
  │  insert cases row, │      │   open RO byte-layer,         │
  │  evidence_sources  │◄─────┤   NEVER mount                 │
  └───────┬───────────┘ rows  └──────────────┬───────────────┘
          │                                  │ read(offset,size)
          ▼                                  ▼
  ┌───────────────────┐      ┌──────────────────────────────┐
  │ Audit log (logs/  │      │ Integrity (evidence/          │
  │  audit.jsonl)     │◄─────┤   integrity.py)               │
  │  O_APPEND, fsync, │ event│   ONE streaming pass:         │
  │  UTC ISO-8601,    │      │   md5+sha256 over chunks;     │
  │  every action     │      │   compare to acquisition hash │
  └───────┬───────────┘      │   → PASS/FAIL; store baseline │
          │                  └──────────────┬───────────────┘
          │                                 │ end-of-run
          │                                 ▼
          │                  ┌──────────────────────────────┐
          │                  │ RE-VERIFY hash == baseline    │
          │                  │  mismatch → loud non-zero exit│
          │                  │  + audit FAIL event           │
          │                  └──────────────────────────────┘
          ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  safe_extract jail (util/)  — ONLY sanctioned archive expander     │
  │   canonicalize+confine each member to dest (reject Zip Slip);      │
  │   refuse symlink/hardlink/device; enforce size/ratio/depth/count   │
  │   (NOT wired into ingest flow in Phase 1; standalone gated util)   │
  └──────────────────────────────────────────────────────────────────┘
```
*Note: `safe_extract` is built and tested as a standalone hardened utility this phase (gate). It has no caller in the Phase-1 ingest path — its consumers (archive/log parsers) arrive in Phase 5. Building it now satisfies INGEST-04 and locks the security contract early.*

### Recommended Project Structure
```
src/pyautopsy/
├── __init__.py            # __version__ (single source of truth)
├── cli/
│   └── main.py            # Typer app, `ingest` command (D-12)
├── case/
│   ├── store.py           # SQLite open/WAL/migrate; repository methods (only writer)
│   ├── schema.sql         # DDL: cases, evidence_sources, audit/run_log (typed + JSON attributes)
│   └── models.py          # dataclasses: Case, EvidenceSource, AuditEvent
├── evidence/
│   ├── image.py           # *** ONLY module importing pytsk3/pyewf *** Img_Info + EWFImgInfo
│   └── integrity.py       # single-pass md5+sha256 streaming + verify/re-verify
├── audit/
│   └── log.py             # append-only JSONL writer (O_APPEND, fsync, UTC)
├── util/
│   ├── safe_extract.py    # the hardened extraction jail (gate)
│   └── timeutil.py        # utc_now() -> tz-aware ISO-8601; ban naive datetime
└── core/
    └── ingest.py          # orchestrator wiring the above for `ingest`
tests/
├── conftest.py            # tmp_path case dir fixture; tiny synthetic raw image fixture
├── fixtures/
│   ├── make_raw_image.py  # generates a tiny FAT/ext raw image (build-time, deterministic)
│   └── malicious/         # zip-slip.tar, bomb.tar.gz, symlink-escape.tar fixtures
├── test_image.py          # real raw open is read-only; mounted-path refused
├── test_integrity.py      # streaming md5+sha256 correct vs hashlib reference
├── test_store.py          # schema creates; cases/evidence rows round-trip
├── test_audit.py          # JSONL append-only, UTC, one event/line, fsync
└── test_safe_extract.py   # zip-slip/symlink/bomb fixtures all REJECTED
pyproject.toml             # hatchling, src layout, [ewf] extra, ruff/mypy/pytest config
README.md                  # native deps + install + Containerfile usage
Containerfile              # bakes sleuthkit + libewf
```

### Pattern 1: Single Native Seam (`evidence/image.py`)
**What:** `pytsk3` and `pyewf` are imported in exactly one module. It yields/exposes plain Python objects (`Img_Info` handle + size + format) to the rest of the app.
**When to use:** Always — testability + native-swap insurance (D-06, ARCHITECTURE Anti-Pattern 1).
**Example:** see §Code Examples (raw + EWF adapter).

### Pattern 2: Typed Columns + JSON `attributes` (Blackboard)
**What:** Every table has typed core columns plus a `attributes TEXT` JSON column for heterogeneous extras. New producers add JSON keys, never migrations.
**When to use:** All case-store tables (D-02). `[CITED: ARCHITECTURE.md Data Model — plaso/Autopsy pattern]`

### Pattern 3: Read-Only Evidence Boundary
**What:** Open RO, hash once at ingest, re-verify at end; the code path has *no* write access to the source; all output to the separate case dir.
**When to use:** Always (INGEST-03, PITFALLS P1). Add a hard guard refusing a source path that is a mounted filesystem (check against `/proc/mounts`) and never call `mount`/`losetup`.

### Anti-Patterns to Avoid
- **`import pytsk3` scattered across modules** → confine to `evidence/image.py` (ARCHITECTURE AP-1).
- **`zipfile.extractall()` / `tarfile.extractall(filter='fully_trusted')` on evidence** → use the jail (P6).
- **Naive `datetime.fromtimestamp(ts)` (no `tz=`)** → always tz-aware UTC (P4).
- **Wall-clock `datetime.now()` interpolated into analytical content** → segregate run metadata from reproducible body (P3).
- **`mount -o loop` on the source** → never; TSK byte-layer only (P1).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Filesystem / image parsing | Custom dd/E01 parser | pytsk3 `Img_Info` / pyewf | TSK/libewf are court-trusted, decades-hardened; reimplementation is a soundness liability (REQUIREMENTS out-of-scope). |
| E01 segment globbing | Manual `.E01/.E02…` enumeration | `pyewf.glob(path)` | Handles multi-segment naming transparently. |
| Tar Zip-Slip/symlink/device defense | Per-member string checks from scratch | `tarfile` `filter='data'` (3.12+) | Stdlib filter blocks traversal, absolute paths, symlinks, hardlinks, device files — battle-tested. Still ADD bomb limits on top. |
| Hashing | Custom digest loop reading whole image | `hashlib` `.update()` over chunks | Memory-bounded one-pass; FIPS-validated digests. |
| CLI parsing/validation/help | argparse boilerplate | Typer | Type-hint-driven, auto help/validation, subcommands. |
| Case store | Custom file format / pickle | stdlib `sqlite3` | Transactional, hashable, queryable single file. |

**Key insight:** In forensics, hand-rolling a parser or a "good enough" extraction routine is not just extra work — it is a *defensibility* failure. The trusted-tool boundary (TSK/libewf/stdlib-filters) is itself part of the chain-of-custody story. The one thing you DO hand-write is the *bomb-limit wrapper* around the trusted extractor, because no stdlib facility caps decompression ratio/size.

## Common Pitfalls

### Pitfall 1: `tarfile filter='data'` does NOT stop decompression bombs
**What goes wrong:** Teams assume `filter='data'` makes extraction safe. It blocks path traversal, symlinks, and device files — but **not** zip/tar bombs (a 10 KB file expanding to 10 GB extracts happily). `[VERIFIED: docs.python.org tarfile — "does not prevent denial-of-service (excessive files, sizes)"]`
**How to avoid:** Wrap extraction with explicit caps: max total uncompressed bytes, max per-member size, max compression ratio (uncompressed/compressed), max entry count, max nesting depth. Count bytes as you stream each member; abort + log on breach. This is the hand-written part of the jail.
**Warning signs:** No running byte-counter during extraction; reliance on `filter='data'` alone.

### Pitfall 2: `zipfile` has no extraction filter
**What goes wrong:** The 3.12 filter API is **tarfile-only**. `zipfile.extractall()` still happily writes `../../etc/...` paths. `[VERIFIED: docs.python.org — filter API is on TarFile]`
**How to avoid:** For zip members, resolve `os.path.realpath(os.path.join(dest, member))` and assert it `startswith(realpath(dest) + os.sep)` BEFORE writing; reject entries whose name is absolute or contains `..`; skip/refuse entries flagged as symlinks (zip stores them in external attrs). Same bomb caps as Pitfall 1.

### Pitfall 3: Default `tarfile` filter differs by Python version
**What goes wrong:** On 3.12–3.13 the default `extractall()` filter was `fully_trusted` (a DeprecationWarning, unsafe); only on **3.14+** is the default `'data'`. Relying on the default is non-portable. `[VERIFIED: docs.python.org — "Changed in version 3.14: default changed from fully_trusted to data"]`
**How to avoid:** **Always pass `filter='data'` explicitly** regardless of Python version. Never rely on the default.

### Pitfall 4: Naive timestamps poison the timeline foundation
**What goes wrong:** `datetime.fromtimestamp(ts)` applies the *analysis host's* local tz; naive datetimes lose offset. Retrofitting tz-awareness later is a rewrite. `[CITED: PITFALLS P4]`
**How to avoid:** One helper `utc_now()` returning `datetime.now(timezone.utc)`; all serialized timestamps `.isoformat()` with explicit `+00:00`. Ban bare `fromtimestamp` (ruff rule or review). TSK epoch times → `datetime.fromtimestamp(ts, tz=timezone.utc)`.

### Pitfall 5: pytsk3/libtsk version mismatch & cp314 native build
**What goes wrong:** Multiple libtsk versions on one host make pytsk3 reference struct members that don't exist (AttributeError). `[CITED: PITFALLS P8]` Separately: the host here is **Python 3.14.5** — pytsk3 ships a cp314 wheel (good), but **libewf-python is sdist-only** and must compile against `libewf-dev`, which is **not installed** (see Environment Availability).
**How to avoid:** Pin pytsk3 (wheel bundles libtsk). Record `pytsk3.TSK_VERSION_STR` in the audit log + `cases` row for reproducibility. Make E01 an *optional* `[ewf]` extra so a missing libewf doesn't block the core install. Detect E01 path → if pyewf import fails, fail with a clear "install pyautopsy[ewf] + libewf-dev" message, not a stack trace.

### Pitfall 6: SQLite WAL & reproducibility
**What goes wrong:** Default rollback-journal SQLite is fine but WAL gives better concurrency/crash-safety; either way, embedding wall-clock or non-deterministic ordering in *analytical* output breaks the two-run-identical reproducibility test. `[CITED: PITFALLS P3]`
**How to avoid:** `PRAGMA journal_mode=WAL;` on case.db open. Keep run metadata (timestamps, host) in clearly-segregated columns/rows (`run_log`), separate from analytical content. Use deterministic ordering (sort by inode/path/offset) anywhere output is emitted — relevant from Phase 1 for the audit/COC content the report will later consume.

## Code Examples

### Open a raw/dd image read-only (INGEST-01, INGEST-03)
```python
# Source: pytsk3 PyPI / py4n6/pytsk samples [VERIFIED: pytsk3 20260520 API]
import pytsk3

img = pytsk3.Img_Info("evidence.dd")   # opens byte-layer READ-ONLY; never mounts
size = img.get_size()                  # total bytes
data = img.read(0, 512)                # read(offset, size) -> bytes
# Confirm readable without mounting; for partitioned images:
#   vol = pytsk3.Volume_Info(img)              # iterate partitions
#   fs  = pytsk3.FS_Info(img, offset=part.start * vol.info.block_size)
# (Volume_Info / FS_Info are Phase-2 walk concerns; Phase 1 only needs open+read.)
img.close()
```

### EWF/E01 adapter — the canonical recipe (INGEST-01)
```python
# Source: hecfblog "Automating DFIR" pt.9 + libewf wiki Python-development
# [VERIFIED: reproduced verbatim from two independent authoritative sources]
import pyewf
import pytsk3

class EWFImgInfo(pytsk3.Img_Info):
    def __init__(self, ewf_handle: "pyewf.handle") -> None:
        self._ewf_handle = ewf_handle
        super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)

    def close(self) -> None:
        self._ewf_handle.close()

    def read(self, offset: int, size: int) -> bytes:
        self._ewf_handle.seek(offset)
        return self._ewf_handle.read(size)

    def get_size(self) -> int:
        return self._ewf_handle.get_media_size()

# Opening an E01 (handles multi-segment .E01/.E02/... via glob):
filenames = pyewf.glob("evidence.E01")     # -> list of all segment files
ewf_handle = pyewf.handle()
ewf_handle.open(filenames)                 # read-only
img = EWFImgInfo(ewf_handle)               # now usable exactly like pytsk3.Img_Info
# pyewf also exposes stored MD5/SHA-1 from the EWF container to cross-check on ingest.
```

### Single-pass streaming MD5 + SHA-256 (INGEST-02)
```python
# Source: hashlib stdlib pattern [VERIFIED: stdlib]
import hashlib

def hash_image(img, total_size: int, chunk: int = 8 * 1024 * 1024) -> dict[str, str]:
    """One streaming pass over a pytsk3/pyewf Img_Info (or EWFImgInfo).
    Works for raw and E01 alike because both expose read(offset, size).
    For a whole-image raw hash you may also read the underlying file directly,
    but reading via Img_Info keeps one code path for raw + E01."""
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    offset = 0
    while offset < total_size:
        n = min(chunk, total_size - offset)
        block = img.read(offset, n)
        if not block:
            break
        md5.update(block)
        sha256.update(block)
        offset += len(block)
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}
# Compare result["sha256"] to the supplied acquisition hash -> PASS/FAIL.
# Re-run at end of ingest; mismatch -> audit FAIL event + non-zero exit.
```

### Tool + TSK versions for the COC record (REPORT-01)
```python
# Source: importlib.metadata stdlib + pytsk3 [VERIFIED]
from importlib.metadata import version
import pytsk3
tool_version = version("pyautopsy")        # from package metadata
tsk_version = pytsk3.TSK_VERSION_STR        # libtsk version string  [ASSUMED: attribute name — verify at build]
```

### Append-only audit JSONL writer (REPORT-02)
```python
# Source: stdlib os/json pattern [VERIFIED: stdlib]
import json, os
from datetime import datetime, timezone

def audit(case_dir: str, event: dict) -> None:
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}  # UTC ISO-8601
    line = json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n"
    path = os.path.join(case_dir, "logs", "audit.jsonl")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)  # append-only
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)                       # durability for tamper-evidence
    finally:
        os.close(fd)
```

### SQLite case store init (REPORT-01)
```python
# Source: sqlite3 stdlib [VERIFIED: stdlib]
import sqlite3
def open_case_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.executescript(SCHEMA_SQL)         # typed columns + JSON attributes (D-02)
    return conn
```

## Safe-Extraction Jail (INGEST-04, D-11) — concrete defenses

This is the phase-completion gate. Layered defenses:

1. **Path confinement (reject Zip Slip):** For every member, compute `dest_real = os.path.realpath(dest)` and `target = os.path.realpath(os.path.join(dest, member_name))`; require `target == dest_real or target.startswith(dest_real + os.sep)`. Reject absolute names and any `..` component before resolution too.
2. **Use the stdlib filter for tar:** `tar.extractall(path=jail, filter='data')` — **always pass `filter='data'` explicitly** (Pitfall 3). This blocks absolute paths, traversal (post-symlink-resolution), symlinks, hardlinks, and device/special files via `AbsolutePathError`/`OutsideDestinationError`/`AbsoluteLinkError`/`LinkOutsideDestinationError`/`SpecialFileError`. `[VERIFIED: docs.python.org]`
3. **zip has no filter — confine manually:** iterate `ZipFile.infolist()`, apply the §1 path check per entry, refuse entries with symlink mode bits (`(info.external_attr >> 16) & 0o170000 == 0o120000`), then extract one validated member at a time. `[VERIFIED: zipfile has no filter API]`
4. **Refuse symlinks / hardlinks / device files:** covered by `filter='data'` for tar; explicit for zip (§3).
5. **Decompression-bomb limits (hand-written — NOT covered by `filter='data'`):**
   - `max_total_uncompressed` (e.g. 1 GiB default — configurable)
   - `max_entry_size` (e.g. 256 MiB)
   - `max_ratio` = uncompressed/compressed (e.g. 100× → reject) — for zip use `ZipInfo.file_size / ZipInfo.compress_size`; for tar count streamed bytes
   - `max_entries` (e.g. 10 000)
   - `max_depth` (nested archives, e.g. 3) — track recursion depth if the jail recurses
   Maintain a running uncompressed-byte counter while streaming each member; abort with a logged reason on any breach (never crash).
6. **Sanitize write-names:** preserve the original member name as metadata (it's evidence); write to a sanitized safe name.
7. **Error isolation:** one malformed member logs a finding and does not abort the run.

**Malicious-archive fixture strategy (for the gate test):** build fixtures programmatically at test time (don't ship live bombs):
- `zip-slip`: a tar/zip whose member name is `../../escape.txt` → assert REJECTED (`OutsideDestinationError` for tar; manual check for zip).
- `symlink-escape`: a tar containing a symlink `link -> /etc/passwd` → assert REJECTED (`AbsoluteLinkError`/`SpecialFileError`).
- `device-file`: a tar with a char/block device member → assert `SpecialFileError`.
- `ratio-bomb`: a small archive of a highly-compressible large file (e.g. 50 MiB of `\0` → tiny compressed) → assert ratio/size cap REJECTS.
- `count-bomb`: an archive with > `max_entries` tiny members → assert count cap REJECTS.
All fixtures generated with `tarfile`/`zipfile` in `tests/fixtures/`; the test asserts each raises the expected guard and that **nothing is written outside the jail** (check `tmp_path` after each attempt).

## Runtime State Inventory

> Greenfield project — no pre-existing runtime state to migrate. This phase *creates* the runtime-state contract (case dir layout, case.db schema, audit JSONL) that later phases inherit. Included for completeness:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — repo contains only `.gitignore`, `LICENSE`, `CLAUDE.md`. No existing case.db. | None. Phase 1 defines the schema. |
| Live service config | None — no external services. | None. |
| OS-registered state | None. | None. |
| Secrets/env vars | None. | None — forensic tool must have no network egress / phone-home (PITFALLS P11). |
| Build artifacts | None — no prior package install. Phase 1 creates `pyproject.toml` + egg/dist on first `pip install -e`. | None. |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `zipfile/tarfile.extractall()` unguarded | `tarfile` `filter='data'` + manual zip confinement | Py 3.12 (filter API); 3.14 (default `data`) | Tar traversal/symlink/device defense is now stdlib; still must add bomb caps + zip confinement. |
| Autopsy Jython 2.7 modules | pytsk3 direct on Python 3 | n/a (architectural) | Full Python-3 ecosystem; native libs usable. |
| `setup.py` / Poetry | hatchling + src layout | 2024+ default | Simpler, src-layout-friendly build. |
| MD5-only integrity | SHA-256 primary + MD5 for interop | longstanding forensic best practice | Defensible tamper-evidence. |

**Deprecated/outdated for this phase:**
- `tarfile.extractall()` with no `filter=` → raises DeprecationWarning on 3.12/3.13, behaves `fully_trusted`. Never rely on it.
- dfVFS/plaso/qcow2/pyaff4 → out of scope for the Walking Skeleton (deferred).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `pytsk3.TSK_VERSION_STR` is the attribute for the libtsk version string | Code Examples (REPORT-01) | LOW — if absent, fall back to `subprocess fls -V` or the pytsk3 `__version__`; verify at build. Recording *some* TSK version is required, the exact attribute is not. |
| A2 | Default decompression-bomb thresholds (1 GiB total / 256 MiB entry / 100× ratio / 10 000 entries / depth 3) | Safe-Extraction §5 | LOW — these are configurable sane defaults per D-11 discretion; planner/user may tune. |
| A3 | Tiny synthetic raw image can be generated deterministically at test time (e.g. mkfs on a sparse file, or a pre-built tiny fixture) | Validation Architecture | MEDIUM — generating a FAT/ext image may need `mkfs`/`mtools` in CI; fallback is committing a small (<1 MB) pre-built fixture image to the repo. |
| A4 | `pyewf.handle.read(size)` (vs `read_buffer(size)`) is the current method name | Code Examples (EWF) | LOW — both names appear in sources across libewf versions; the canonical recipe uses `read`. Verify against installed pyewf 20240506 at implementation; adapter is a 4-line change either way. |

## Open Questions (RESOLVED)

1. **libtsk version recording attribute (A1).** — **RESOLVED:** probe `dir(pytsk3)` for the VERSION attribute at runtime and record whatever is present; never assert a hard-coded attribute name. (Adopted by plan 01-02.)
   - What we know: pytsk3 exposes a TSK version; the audit/COC record must capture it (P8, REPORT-01).
   - What's unclear: exact attribute name on pytsk3 20260520.
   - Recommendation: at build/spike, `python -c "import pytsk3; print([a for a in dir(pytsk3) if 'VERSION' in a.upper()])"`; record whatever is present.
2. **Test-fixture image generation (A3).** — **RESOLVED:** commit a small (<1 MB) deterministic `tiny_raw.dd` fixture to `tests/fixtures/` (no CI `mkfs`/`mtools` dependency). (Adopted by plan 01-00.)
   - What we know: tests need a real tiny image to prove read-only open.
   - What's unclear: generate-at-test-time (needs `mkfs`/`mtools`) vs. commit a pre-built fixture.
   - Recommendation: commit a small (<1 MB) deterministic raw fixture to `tests/fixtures/` to avoid CI tool dependencies; document how it was built.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.14.5 | — (3.11+ fine; note 3.14 tarfile default) |
| pip | install | ✓ | 26.0.1 | — |
| pytsk3 (wheel) | raw/E01 open | installable | 20260520 (cp314 wheel) | wheel bundles libtsk → no system sleuthkit needed for raw |
| sleuthkit / libtsk (system) | pytsk3 source build only | ✗ not installed | — | pytsk3 cp314 **wheel** avoids needing it; install `sleuthkit-devel` only if building from source |
| libewf / libewf-dev (system) | **libewf-python build** | ✗ not installed | — | **BLOCKING for E01**: libewf-python is sdist-only; needs `libewf-dev` to compile. Raw/dd works without it. Make E01 the optional `[ewf]` extra (D-04). |
| libewf-python (pyewf) | E01 support | sdist (needs libewf-dev) | 20240506 | optional extra; raw-only core install unaffected |
| Typer / Rich / pydantic / hatchling / pytest / ruff / mypy | CLI, build, dev | installable | 0.26.3 / 15.0.0 / 2.13.4 / 1.29.0 / latest | — pure-Python wheels |

**Missing dependencies with no fallback:** none for the *core* (raw/dd) Walking Skeleton — pytsk3 cp314 wheel covers it.
**Missing dependencies with fallback:** `libewf-dev` (system) for E01 — gate E01 behind the `[ewf]` extra and a clear runtime error if pyewf import fails. The Containerfile (D-13) MUST bake `sleuthkit` + `libewf` so the container has full raw+E01 support out of the box. **Planner should add a task to validate E01 ingest inside the container** (since the host lacks libewf), or descope E01 verification to "import-guarded path + unit-tested adapter logic with a mocked handle" if the container build is out of Phase-1 scope.

## Validation Architecture

> nyquist_validation is enabled (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (latest, 9.x) + `tmp_path` + `parametrize` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` with `pythonpath = ["src"]` — **Wave 0 (does not exist yet)** |
| Quick run command | `pytest -x -q` |
| Full suite command | `pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | Open tiny synthetic raw image; `get_size()` > 0, `read(0,512)` returns bytes | unit/integration | `pytest tests/test_image.py::test_open_raw_readonly -x` | ❌ Wave 0 |
| INGEST-01 (E01) | EWFImgInfo adapter delegates read/get_size/close to a mocked `pyewf.handle` (host lacks libewf) | unit | `pytest tests/test_image.py::test_ewf_adapter_delegates -x` | ❌ Wave 0 |
| INGEST-02 | Streaming md5+sha256 over fixture == `hashlib` reference; supplied-hash compare PASS/FAIL | unit | `pytest tests/test_integrity.py -x` | ❌ Wave 0 |
| INGEST-03 | Source mtime unchanged after open+hash; mounted-source path is REFUSED; end-of-run re-verify mismatch → non-zero exit | integration | `pytest tests/test_image.py::test_source_readonly tests/test_integrity.py::test_reverify_mismatch_fails -x` | ❌ Wave 0 |
| INGEST-04 | zip-slip / symlink-escape / device / ratio-bomb / count-bomb fixtures each REJECTED; nothing written outside `tmp_path` jail | unit (parametrized) | `pytest tests/test_safe_extract.py -x` | ❌ Wave 0 |
| REPORT-01 | `cases` + `evidence_sources` rows round-trip; tool+TSK versions and UTC ISO-8601 timestamps recorded | unit | `pytest tests/test_store.py -x` | ❌ Wave 0 |
| REPORT-02 | audit.jsonl is append-only (two writes → two lines), each line valid JSON with UTC `ts`, written only under case dir | unit | `pytest tests/test_audit.py -x` | ❌ Wave 0 |
| CLI smoke | `pyautopsy ingest <fixture> --case <tmp> --examiner X --evidence-id E1` exits 0 and creates case.db + audit.jsonl | integration | `pytest tests/test_cli.py::test_ingest_smoke -x` | ❌ Wave 0 |
| Reproducibility (CLI-02 seed) | Two ingests of the same fixture produce identical analytical content (hashes/COC), modulo segregated run metadata | integration | `pytest tests/test_repro.py::test_two_runs_identical -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest -x -q`
- **Per wave merge:** `pytest`
- **Phase gate:** full suite green + the **safe_extract malicious-archive fixtures all REJECTED** (hard gate, D-11) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` with `pythonpath=["src"]` — no test infra exists yet (greenfield).
- [ ] `tests/conftest.py` — `tmp_path` case-dir fixture + tiny synthetic raw image fixture.
- [ ] `tests/fixtures/` — committed <1 MB raw image; programmatic malicious-archive builders.
- [ ] Framework install: `pip install pytest` (none detected).
- [ ] Mocked `pyewf.handle` for E01 adapter test (host has no libewf — verify adapter logic without a real E01).

## Security Domain

> security_enforcement is enabled (config.json `workflow.security_enforcement: true`, ASVS level 1).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-user local CLI; no auth surface. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | partial | File-system confinement: all writes under the case dir; refuse writes to the evidence source (read-only guard). Refuse operating on a mounted source path. |
| V5 Input Validation | **yes** | Evidence is **adversarial input** (P6). Validate image paths; jail all archive members (path canonicalization, reject `..`/absolute); validate Typer args. |
| V6 Cryptography | **yes** | Use `hashlib` (never hand-roll digests). SHA-256 primary for integrity; MD5 only as a non-security interop hash — document that MD5 is NOT relied upon for tamper-evidence. |
| V12 Files & Resources | **yes** | The core threat surface this phase: Zip Slip, decompression bombs, symlink/device escape, resource exhaustion → the safe-extraction jail with size/ratio/count/depth caps + path confinement. |
| V10 Malicious Code / Supply Chain | **yes** | slopcheck-audited deps (all [OK]); pinned dated TSK/pyewf releases; no network egress / no phone-home (P11). |

### Known Threat Patterns for {Python forensic CLI ingesting untrusted disk images/archives}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Zip Slip / path traversal on archive extract | Tampering / Elevation | `tarfile` `filter='data'` + `realpath` confinement; manual confinement for zip. |
| Decompression bomb (zip/tar bomb) | Denial of Service | Hand-written caps: max total/entry size, max ratio, max count, max depth; abort+log. |
| Symlink / hardlink / device-file escape on extract | Tampering / Elevation | `filter='data'` (tar) refuses these; explicit mode-bit checks for zip. |
| Modifying the evidence source (mount / write / atime) | Tampering / Repudiation | TSK byte-layer RO open; never `mount`; refuse mounted/writable source path; pre/post hash compare. |
| Forged/altered evidence undetected | Repudiation | SHA-256 baseline at ingest + end-of-run re-verify; per-action append-only audit log (tamper-evident JSONL, fsync). |
| Malicious filename (control chars, overlong, absolute) | Tampering | Sanitize write-name; preserve original as metadata. |
| One crafted member aborts the whole run | Denial of Service | Per-member error isolation; log finding, continue. |
| Supply-chain (hallucinated/typosquatted dep) | Tampering | slopcheck audit (done, all [OK]); pinned versions; verified canonical libyal/TSK provenance. |
| Data exfiltration / phone-home | Information Disclosure | No network egress; all writes confined to case dir (P11). |

## Sources

### Primary (HIGH confidence)
- https://pypi.org/project/pytsk3/ + `pip index versions pytsk3` — pytsk3 **20260520**, cp314 wheel — verified this session.
- https://pypi.org/project/libewf-python/ + `pip index versions libewf-python` — **20240506**, sdist (needs libewf-dev) — verified this session.
- https://docs.python.org/3/library/tarfile.html — extraction filter API (`data`/`tar`/`fully_trusted`), 3.14 default change, exceptions, "does not prevent DoS" — verified this session.
- https://www.hecfblog.com/2015/03/automating-dfir-how-to-series-on.html — canonical `ewf_Img_Info(pytsk3.Img_Info)` recipe (verbatim).
- https://github.com/libyal/libewf/wiki/Python-development — pyewf `glob`/`handle`/`open`/`read`/`seek`/`get_media_size`/`close` API.
- slopcheck 0.6.1 `install` audit — 9/9 packages [OK].
- Project research docs: `.planning/research/{STACK,ARCHITECTURE,PITFALLS}.md` (HIGH per their own confidence tags).

### Secondary (MEDIUM confidence)
- https://hub.packtpub.com/working-forensic-evidence-container-recipes/ — EWF container recipe cross-check.
- PyPI version queries for typer/rich/pydantic/hatchling (latest confirmed).

### Tertiary (LOW confidence)
- pyewf `read` vs `read_buffer` method name varies across libewf versions (A4) — verify against installed 20240506.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified against PyPI this session; slopcheck clean.
- Architecture: HIGH — locked in CONTEXT.md + ARCHITECTURE.md; patterns are domain-standard (plaso/Autopsy).
- pytsk3/pyewf API & EWF adapter: HIGH — canonical recipe reproduced from two independent authoritative sources.
- tarfile/zipfile defenses: HIGH — official docs; the gap (bombs not covered by `filter='data'`) explicitly verified.
- Bomb thresholds: MEDIUM — sane defaults, configurable (discretion per D-11).
- E01 native build availability: MEDIUM — host lacks libewf-dev; mitigated via `[ewf]` extra + Containerfile.

**Research date:** 2026-05-30
**Valid until:** ~2026-06-29 (30 days; stable forensic stack — pytsk3/pyewf are dated-release, slow-moving).
