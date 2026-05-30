# Walking Skeleton — PyAutopsy

**Phase:** 1 (Forensic Foundation)
**Generated:** 2026-05-30

## Capability Proven End-to-End

An examiner runs `pyautopsy ingest <raw-image> --case <dir> --examiner <name> --evidence-id <id>` and the tool opens the image entirely read-only (never mounted), computes MD5+SHA-256, persists chain-of-custody and evidence metadata into a SQLite case store, writes an append-only audit log, re-verifies the source hash at end of run, and exits 0 — proving the forensic-soundness spine that every later analysis phase writes into.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Forensic engine | The Sleuth Kit (libtsk) via `pytsk3` 20260520 — NOT Autopsy-the-app | Autopsy automation is Jython 2.7 and cannot load native libs; pytsk3 gives Python-3-native, court-trusted byte-level read-only access (STACK.md decision; D-04). |
| Image formats | raw/dd via `pytsk3.Img_Info`; E01/EWF via an `EWFImgInfo(pytsk3.Img_Info)` adapter over `pyewf` | E01 is the dominant DFIR container; raw is universal. pyewf ships as an optional `[ewf]` extra so the core install stays light (D-04). |
| Native isolation | All `pytsk3`/`pyewf` imports confined to `src/pyautopsy/evidence/image.py` (single seam) | Testability + native-swap insurance; the rest of the system is pure-Python and mockable (D-06; ARCHITECTURE Anti-Pattern 1). |
| Read-only guarantee | Byte-layer `O_RDONLY` via TSK; never `mount`/`losetup`; mounted-source path refused; hash re-verified at end of run | Mounting replays journals / bumps atimes — fatal to soundness (D-05; PITFALLS P1/P2). |
| Case store | A case **directory** containing a single `case.db` (SQLite, WAL) + `logs/` + `exports/`; the only writer is `case/store.py` | Single-file, archivable, hashable for COC, transactional, queryable (D-01/D-03; both Autopsy and plaso validate this). |
| Schema shape | Typed core columns + a JSON `attributes` column on every table | Heterogeneous later producers (metadata, log events, findings) add JSON keys, never migrations (D-02; plaso/Autopsy blackboard pattern). |
| Integrity hashing | Single streaming pass computing MD5 + SHA-256 via stdlib `hashlib`; SHA-256 primary, MD5 interop-only | Memory-bounded; SHA-256 is the forensic tamper-evidence primitive, MD5 retained for NSRL/EWF interop (D-07; never hand-rolled — ASVS V6). |
| Audit log | Append-only JSON Lines `logs/audit.jsonl`, `O_APPEND` + `fsync` + sorted keys, UTC ISO-8601, confined to the case dir | One structured, tamper-evident, deterministic event per line; written only to the case dir (D-09; PITFALLS P12). |
| Time handling | UTC-everywhere from day one via `util/timeutil.py` (tz-aware ISO-8601 with explicit `+00:00`); naive datetimes banned | Retrofitting tz-awareness across a timeline is a rewrite (D-10; PITFALLS P4). |
| Safe extraction | A standalone hardened `util/safe_extract.py` jail (path confinement + `filter='data'` + symlink/special refusal + bomb caps), gated against malicious fixtures | Evidence is adversarial input; the security contract is locked in Phase 1 even though consumers arrive in Phase 5 (D-11; PITFALLS P6). |
| CLI | Typer app; Phase 1 ships `pyautopsy ingest`; the full-pipeline `analyze` command is assembled in Phase 3 | Type-hint-driven, on Click; partial CLI now, full pipeline later (D-12). |
| Project layout | src layout, `pyproject.toml` + hatchling backend, pytest (`pythonpath=src`, `tmp_path`), ruff + mypy, pinned dated TSK/pyewf releases, README + Containerfile | Modern Python defaults; reproducible forensic builds; native-dep install story documented (D-13). |

## Stack Touched in Phase 1

- [x] Project scaffold — hatchling, src layout, pytest, ruff, mypy, pinned deps, README + Containerfile (plan 01-00)
- [x] CLI entrypoint — Typer `pyautopsy ingest` command, real route (plans 01-00 target, 01-04 implementation)
- [x] Database — real write (cases + evidence_sources rows) AND real read (round-trip COC) in the SQLite case store (plan 01-01)
- [x] Real I/O slice wired to the engine — one read-only image open + single-pass hash + end-of-run re-verify (plans 01-02, 01-04)
- [x] Audit log — append-only JSONL written to the case dir on every action (plans 01-01, 01-04)
- [x] Security gate — `safe_extract` jail proven against malicious-archive fixtures (plan 01-03)
- [x] Local full-stack run command — `pyautopsy ingest <raw-image> --case <dir> --examiner <name> --evidence-id <id>` (documented in README; Containerfile bakes sleuthkit+libewf for raw+E01)

## Out of Scope (Deferred to Later Slices)

- Filesystem walk, MACB metadata, per-file hashing, ownership/perms, type-by-signature → **Phase 2**
- Chronological timeline, human-readable HTML/Markdown + JSON report, the single-command `analyze` pipeline, reproducibility hard-gate → **Phase 3**
- Deleted-file recovery, orphan reporting, confidence tiers, NSRL/custom hash filtering → **Phase 4**
- Log parsing (auth/syslog/shell history), shared forensic-event model, super-timeline, keyword/IOC search → **Phase 5**
- File carving, journald/auditd/wtmp parsers, YARA, CASE/UCO export, plaso/dfVFS backends, qcow2, exFAT/HFS+/APFS recovery → **v2**
- A real E01 ingest on a libewf-equipped host (CI mocks the adapter; manual verification per 01-VALIDATION.md) → validated in the Containerfile / manually

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions (single native seam, SQLite case store with typed+JSON-attributes schema, UTC-everywhere, append-only audit, read-only evidence boundary):

- **Phase 2:** Walk ext4/NTFS/FAT → normalized per-file inventory (path, size, inode/MFT, alloc status, MACB UTC times, owner/perms, per-file hashes, type-by-signature) written as rows into the same case store.
- **Phase 3:** Build a chronological timeline from the metadata + emit a deterministic HTML/Markdown + JSON report from one `analyze` command — closing the image→report MVP and adding the two-run-identical reproducibility hard gate.
- **Phase 4:** Recover deleted/orphan files with per-filesystem confidence tiers; filter against NSRL + custom hash sets — more rows into the same store.
- **Phase 5:** Parse Linux logs into the shared event model, merge into a UTC super-timeline, add keyword/IOC search across allocated/unallocated/content.
