# Project Research Summary

**Project:** PyAutopsy
**Domain:** Automated digital forensic analysis (disk-image + log analysis CLI on Linux, built on The Sleuth Kit)
**Researched:** 2026-05-30
**Confidence:** HIGH

## Executive Summary

PyAutopsy is an "image in -> defensible report out" forensic pipeline: a scriptable, single-command Python/Linux CLI that ingests disk images and logs, walks filesystems, recovers deleted files, builds a timeline, and emits both a human-readable and a structured (JSON) report. The domain is mature and the way experts build these tools is near-universal: an **Acquire -> Process -> Analyze -> Report** pipeline organized around a **normalized common store** (Autopsy's *blackboard*, plaso's *attribute containers*) that decouples many producers (extractors, parsers) from one consumer (the reporter). All four research tracks converged on this same shape.

The single most decisive finding is a stack correction the other three tracks reinforce: **drive The Sleuth Kit directly from Python 3 via `pytsk3` - do NOT build on Autopsy the application.** "PyAutopsy" is a product name, not an instruction to use Autopsy. Autopsy's only automation surface is Jython 2.7, which cannot load any native-code Python library (pytsk3, pyewf, plaso, cryptography, WeasyPrint deps) and has no supported headless batch mode. Both Autopsy and pytsk3 sit on the *same* engine (`libtsk`), so going direct loses nothing forensically while gaining Python 3, the entire modern forensic ecosystem, and easier read-only guarantees. The supporting stack is well-settled: `pyewf` for E01 images, `dfVFS` as the optional image/volume abstraction, native TSK bodyfile/mactime timelines (with `plaso` as an optional richer engine), `pydantic` for typed findings + JSON, `Jinja2`/`WeasyPrint` for reports, `Typer`/`Rich` for the CLI, and SQLite as the per-case store.

The central risk is not technical capability but **forensic defensibility**, and the pitfalls track is unusually load-bearing here: the bar is "defensible and reproducible," not merely "works." Five risks must be designed in from the foundation, not bolted on: (1) never modify the evidence source (never `mount`; read only through TSK's byte layer); (2) hash the source (SHA-256 primary) before and after every run and hash every finding; (3) UTC-everywhere with tz-aware datetimes from the first metadata extraction; (4) honest per-filesystem recovery confidence (ext4 deletion wipes inode block pointers - "recovery" there is journal/carving, not intact); and (5) safe extraction of adversarial evidence (no `extractall()`; path-jailed, size/ratio/depth-limited). These dictate that a read-only ingest + hashing + extraction-jail + audit-log **foundation phase gates everything**, and that determinism, provenance, and confidence labeling are enforced in every phase thereafter.

## Key Findings

### Recommended Stack

Drive `libtsk` directly via `pytsk3` (Python 3.11+, target 3.12). This is the load-bearing architectural choice for the whole project - see STACK.md "The Central Decision." Compose the forensic core as: image format handle (`pyewf` for E01 / raw open) -> `pytsk3.Img_Info` adapter -> `Volume_Info` -> `FS_Info` -> directory walk yielding files, metadata, and `UNALLOC` deleted entries. Keep the MVP dependency-light (native TSK bodyfile/mactime timeline, hand-rolled `Img_Info` adapter) and treat `dfVFS` + `plaso` as an optional `[timeline]` extra for broad artifact coverage. Native C-library system dependencies (libtsk, libewf, libfuzzy, libsystemd) are the #1 install failure mode - ship a documented system-dependency list and ideally a Containerfile.

**Core technologies:**
- **pytsk3 (on sleuthkit/libtsk 4.12+)**: direct Python 3 bindings to TSK - court-trusted FS walk, MAC times, deleted-file recovery; the engine everything wraps.
- **pyewf (libewf)**: E01/EWF image access as a file-like object feeding pytsk3 - E01 is the dominant DFIR evidence container.
- **pydantic 2.x**: typed models for files/events/hashes/COC and `.model_dump_json()` structured export - the JSON deliverable with validation.
- **Jinja2 + WeasyPrint**: one HTML/CSS report rendered to both HTML and PDF for evidence presentation.
- **Typer + Rich**: type-hint-driven CLI with subcommands (`ingest`, `recover`, `timeline`, `report`) + progress over large images.
- **SQLite + hashlib (stdlib)**: per-case normalized store (single-file, archivable/hashable for COC); SHA-256 primary integrity hash, MD5/SHA-1 retained only for NSRL/EWF interop.
- **dfVFS / plaso (optional)**: virtual-FS abstraction + super-timeline engine for broad artifact coverage; isolate behind a `[timeline]` extra.

### Expected Features

The feature bar is set by Autopsy/TSK, plaso, X-Ways, and EnCase: "table stakes" means *missing it makes the output non-credible as forensic tooling*. Differentiators are exactly where an automated Python CLI beats the Autopsy GUI: repeatability, structured output, scriptability. Scope v1 recovery firmly around **ext4 + NTFS + FAT** (HIGH confidence) and image formats **raw/dd + E01**; gate exFAT/HFS+/APFS behind a runtime capability probe.

**Must have (table stakes):**
- Read-only ingest of raw/dd + E01 with source-image hash verification - nothing is defensible without it.
- Filesystem walk + full metadata (MACB times, owner/perms, size, inode, allocated/deleted flag) on ext4/NTFS/FAT.
- Per-file hashing (the hub feature feeding NSRL filtering, IOC matching, exhibit ID).
- Deleted-file enumeration & recovery (+ orphan files) - the headline capability.
- Linux log parsing (auth.log/secure, syslog, bash history first) + timeline / super-timeline merging FS metadata and log events.
- Case/COC metadata + audit log; human-readable (HTML/MD) **and** structured JSON report.

**Should have (competitive):**
- Single-command automated pipeline (`pyautopsy analyze image.E01 --case ...`) - the headline differentiator.
- Deterministic/repeatable output - same image -> same report; directly supports defensibility.
- First-class structured JSON, with CASE/UCO ontology conformance as a stretch interoperability win.
- Config-driven runs (YAML/TOML), keyword/IOC/YARA rule packs, timeline-anomaly/timestomp surfacing, extension-vs-content mismatch flags (cheap add-ons on data already collected).

**Defer (v2+):**
- File carving from unallocated (photorec/scalpel wrapper) - high value, high effort; add once core pipeline is trusted (v1.x).
- journald (binary) + auditd + wtmp/btmp parsers; YARA packs; CASE/UCO export (v1.x triggers).
- NSRL known-file filtering can be P1/P2 - it is a large external SQLite dataset, not a pip install.
- Full-text search indexing; exFAT/HFS+/APFS recovery; report diffing; plaso as alternate timeline backend (v2+).

### Architecture Approach

Adopt the domain-standard **Acquire -> Process -> Analyze -> Report** pipeline with a **normalized SQLite case store as the architectural spine** - the single most important idea, borrowed from both Autopsy and plaso. All producers (extractors, log parsers, recovery) write normalized rows; the reporter only reads. The schema's `events` table (typed core columns + a JSON `attributes` column) is what lets FS-metadata events and log events feed *one* super-timeline; the `findings` table mirrors Autopsy's blackboard (typed artifact + JSON attributes). Confine `pytsk3` to a single module (`fs/tsk.py`) yielding plain dataclasses - the one native seam that keeps the rest pure-Python and testable. Build a thin vertical slice (store -> ingest -> FS walk -> metadata -> timeline -> HTML+JSON report) before widening.

**Major components:**
1. **Evidence Loader + Integrity (`evidence/`)** - open image read-only via `Img_Info`; SHA-256 hash + verify; record COC.
2. **TSK FS wrapper + walker (`fs/`)** - the *only* module importing pytsk3; yields file dataclasses.
3. **Case Store (`case/`)** - SQLite schema (files, metadata, hashes, events, findings, run_log) + repository methods; the spine and only writer abstraction.
4. **Extractors + Parsers (`extractors/`, `parsers/`)** - plugin families (metadata, recovery, hashing; log parsers via registry) writing normalized rows.
5. **Timeline Builder + Analyzers (`timeline/`, `analysis/`)** - merge MAC + log events into one UTC-ordered timeline; correlate into findings.
6. **Report Generator (`report/`)** - Jinja2 -> HTML/PDF + JSON/CSV exporters; reads only from the store.

### Critical Pitfalls

1. **Modifying the evidence source (the cardinal sin)** - never `mount`/`losetup` writable; read only through `pytsk3.Img_Info`->`FS_Info` byte access. Add a hard guard refusing mounted paths; all output to a separate case dir; assert pre/post image hashes match.
2. **Missing/wrong/unverified hashing** - SHA-256 of the source as ingested, recomputed and compared at run end (fail loudly); hash every recovered artifact with its source offset/inode. MD5/SHA-1 only as additional interop hashes. Stream-hash in a single pass.
3. **Local-time / naive timestamps** - store everything UTC tz-aware from the first metadata extraction; render with explicit offset only at the presentation edge; let the operator supply evidence timezone + clock-skew; label MACB semantics per filesystem.
4. **False confidence in deleted-file recovery** - ext4 deletion wipes inode block pointers, so recovery is journal/carving, not intact. Report three confidence tiers (metadata-intact / journal / signature-carving), detect overwriting, never assert "the user deleted this."
5. **Unsafe parsing of untrusted evidence** - never `extractall()`; path-jail every member, reject `..`/absolute/symlink escapes, enforce size/ratio/depth/count limits (zip-bomb), isolate per-artifact errors so one bad file doesn't abort the run.

Plus cross-cutting: **non-deterministic output** (sort all output; segregate run metadata; two-run CI diff), **overclaiming in the report** (every finding carries source/method/version/hash/confidence/assumptions + a limitations section), and **no self-audit log** (append-only run log in the output).

## Implications for Roadmap

The four tracks converge on a single, dependency-driven phase ordering. The recurring spine: **foundation (read-only ingest + hashing + extraction jail + audit) -> FS walk + metadata (UTC-everywhere) -> deleted recovery + NSRL -> log parsing + shared event model -> timeline -> search -> report (human + JSON).** Build a thin vertical slice through the store first, then widen.

### Phase 1: Foundation - Case Store, Read-Only Ingest, Integrity & Safety
**Rationale:** Everything writes to the store and consumes the hashed source; read-only and safety guarantees cannot be retrofitted (Pitfalls 1, 2, 6, 12 all map here). This is the non-negotiable gate.
**Delivers:** SQLite case store + schema (the spine); `Img_Info` read-only loader for raw/dd + E01 (pyewf); SHA-256 source hashing with pre/post verify; chain-of-custody + authorization intake; append-only audit/run log; path-jailed, limit-enforced safe-extraction utility.
**Addresses:** Read-only ingest, source hash verification, case/COC metadata, audit log (FEATURES table stakes).
**Avoids:** Evidence modification (P1), missing hashing (P2), unsafe extraction (P6), no self-audit (P12), legal scope (P11).

### Phase 2: Filesystem Walk + Metadata Extraction (UTC-everywhere)
**Rationale:** The core forensic primitive and the second event source-of-truth; tz-awareness must be enforced here or the timeline is a rewrite (P4).
**Delivers:** `fs/tsk.py` pytsk3 wrapper + walker (the single native seam) yielding file dataclasses; metadata extractor (MACB times, uid/gid/mode, size, inode, deleted flag) writing `files`/`metadata`/`events` rows; per-file hashing; FS capability matrix with clear failure on encrypted/unsupported volumes.
**Uses:** pytsk3, hashlib, pydantic models.
**Implements:** TSK FS wrapper, Metadata Extractor, normalized `events` producer.
**Avoids:** Timezone/MAC misinterpretation (P4), pytsk3/TSK build + FS gaps + filename encoding (P8).

### Phase 3: Timeline + Vertical-Slice Report (MVP close)
**Rationale:** Closes the first end-to-end slice (image -> report) with one event source, proving the spine before investing in many producers.
**Delivers:** Timeline builder (UTC-ordered, explicit offsets); deterministic HTML + JSON report with methodology, tool/TSK versions, per-finding provenance, and a limitations section; single-command pipeline orchestrator.
**Implements:** Timeline Builder, Report Generator, pipeline conductor.
**Avoids:** Non-deterministic output (P3), overclaiming (P10).

### Phase 4: Deleted-File Recovery + Known-File Filtering
**Rationale:** The headline forensic capability; layers onto the proven spine as an independent producer. Recovery confidence tiering must be designed in, not bolted on (P5).
**Delivers:** Unallocated/deleted enumeration + recovery with three-tier confidence labeling (metadata-intact / journal / carving), per-filesystem caveats, overwrite detection, orphan-file handling; NSRL RDS known-file filtering + custom hash/IOC sets.
**Addresses:** Deleted recovery, orphans, NSRL filtering, hash/IOC matching (FEATURES).
**Avoids:** False recovery confidence (P5), slack/unallocated mishandling (P9).

### Phase 5: Log Parsing + Shared Event Model -> Super-Timeline
**Rationale:** Logs are half the evidence; parsers emit rows identical in shape to FS events so the existing timeline merges both transparently. Plugin registry validates extensibility.
**Delivers:** Log-parser plugin framework + registry; HIGH-confidence text parsers first (auth.log/secure, syslog, bash history) with rotation/compression reassembly, year inference, local-tz-with-offset handling, completeness-as-a-finding; super-timeline merge; keyword + IOC search.
**Addresses:** Log parsing, super-timeline, keyword/IOC search (FEATURES).
**Avoids:** Log-parsing naïveté (P7), and reinforces UTC discipline (P4) and per-artifact error isolation (P6).

### Phase 6: Breadth & Differentiators (v1.x)
**Rationale:** Add value once the core pipeline is examiner-validated; each item is an independent producer or reporter add-on.
**Delivers:** File carving (photorec/scalpel wrapper); binary-log parsers (journald, auditd, wtmp/btmp); timeline-anomaly/timestomp + extension-mismatch flags; YARA packs; CASE/UCO JSON conformance; PDF output polish.

### Phase Ordering Rationale
- **Dependencies discovered:** Everything depends on read-only ingest + hash verification (foundation). Per-file hashing is a hub (NSRL/IOC/exhibits). The super-timeline requires *both* FS metadata and normalized log events, so the shared "forensic event" model must exist before either feeds it - hence the store is Phase 1 and the event schema is fixed early. The report necessarily comes after findings, but its JSON model is defined before the human renderer.
- **Architecture grouping:** The normalized store + pipeline conductor are built first as the spine; extractors, parsers, recovery, and analyzers all plug in as independent producers writing the same rows, which is why recovery (Phase 4) and log parsing (Phase 5) can layer on after the MVP slice (Phase 3) without touching core.
- **Pitfall avoidance:** Foundation-gating read-only/hashing/extraction-jail/audit (P1/P2/P6/P12), UTC-from-metadata (P4), recovery-confidence-by-design (P5), and determinism + provenance enforced in the report phase and every phase thereafter - all driven by the "defensible and reproducible" bar.

### Research Flags

Phases likely needing deeper research during planning (`/gsd-plan-phase --research-phase <N>`):
- **Phase 1:** Confirm E01/`pyewf` wrapping into `Img_Info` and the safe-extraction jail design against current libraries; resolve native-dependency packaging (Containerfile vs. system pkgs).
- **Phase 2:** **pytsk3 FS-capability spike** - build-time confirmation of exFAT/HFS+/APFS support in the bundled libtsk, filename-encoding edge cases, and struct-version pinning; LUKS/dm-crypt detection.
- **Phase 4:** NSRL RDS current distribution format ("RDS Modern" SQLite/minimal sets) and ingestion strategy; ext4 journal-based recovery method specifics.
- **Phase 5:** journald binary parsing (`python-systemd` vs. native parser) and rotation/locale handling.
- **Phase 6:** plaso integration as an alternate backend; CASE/UCO ontology conformance scope.

Phases with standard patterns (skip research-phase):
- **Phase 3:** Timeline merge, Jinja2/WeasyPrint reporting, and Typer CLI are well-documented, established patterns; pydantic JSON export is standard.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Autopsy-vs-TSK decision and core forensic stack confirmed against primary docs/issue trackers; MEDIUM only for AFF4/qcow edge formats and NSRL distribution specifics. |
| Features | MEDIUM-HIGH | Forensic feature landscape is mature and well-documented; pytsk3-specific filesystem limits are MEDIUM and need a build-time spike. |
| Architecture | HIGH | Pipeline + normalized-store pattern is settled (Autopsy blackboard, plaso containers); MEDIUM only on exact pytsk3 method signatures (verify at implementation). |
| Pitfalls | HIGH | Soundness, integrity, timeline, TSK/pytsk3, and safe-parsing risks verified against primary sources; some legal/admissibility points are jurisdiction-dependent (MEDIUM). |

**Overall confidence:** HIGH

### Gaps to Address
- **pytsk3 / libtsk filesystem-capability matrix** (exFAT/HFS+/APFS, encrypted volumes): resolve with a build-time capability spike in Phase 2; gate unsupported FS behind a runtime probe and fail clearly, never silently.
- **E01 (`pyewf`) and optional qcow support**: validate the `Img_Info` adapter idiom in Phase 1; decide dfVFS-vs-hand-rolled glue based on how many container formats v1 must support.
- **NSRL RDS distribution & integration**: verify current "RDS Modern" SQLite format at acquisition time (Phase 4); treat as a large external dataset, not a dependency.
- **plaso integration & CASE/UCO conformance**: deferred design questions - native timeline and ad-hoc JSON first; revisit in Phase 6 when interoperability demand appears.
- **journald / binary-log parsing and LUKS handling**: non-trivial; scope in Phase 5 (journald) and flag encrypted volumes early (Phase 2) as known-limitation findings rather than attempting decryption (out of scope).
- **Native-dependency packaging**: libtsk/libewf/libfuzzy/libsystemd are the #1 install failure mode - design the install story (Containerfile + documented system packages) in Phase 1.

## Sources

### Primary (HIGH confidence)
- https://pypi.org/project/pytsk3/ + https://github.com/py4n6/pytsk - pytsk3 (libtsk bindings, Python 3.10-3.14, libyal/Joachim Metz), build/troubleshooting.
- https://www.autopsy.com/python-autopsy-module-tutorial-1-the-file-ingest-module/ + https://github.com/sleuthkit/autopsy/issues/988 - Autopsy modules are Jython 2.7, cannot use native-code libs (decisive for the pytsk3-vs-Autopsy decision).
- https://github.com/log2timeline/plaso + https://deepwiki.com/log2timeline/plaso + https://plaso.readthedocs.io/ - plaso pipeline, attribute containers, parser/plugin pattern, SQLite storage.
- https://github.com/log2timeline/dfvfs + https://dfvfs.readthedocs.io/ - dfVFS read-only virtual FS over pytsk3/pyewf/pyqcow.
- http://sleuthkit.org/sleuthkit/docs/jni-docs/4.12.1/db_schema_9_4_page.html + https://sleuthkit.org/autopsy/docs/api-docs/4.1/platform_page.html - TSK/Autopsy DB schema and blackboard artifacts/attributes.
- https://www.sleuthkit.org/sleuthkit/desc.php - TSK supported filesystems.

### Secondary (MEDIUM confidence)
- https://www.nist.gov/itl/ssd/software-quality-group/national-software-reference-library-nsrl + https://dfir.science/2022/02/A-more-efficient-NSRL-for-digital-forensics - NSRL RDS Modern (SQLite/minimal sets) for known-file filtering.
- https://www.freedesktop.org/software/systemd/python-systemd/journal.html - systemd.journal.Reader for binary journald (v259 persistent-by-default).
- https://dfrws.org/ (adding APFS support to the Sleuth Kit framework) + https://cellebrite.com/ (APFS support to TSK) - APFS support partial / encryption incomplete in TSK.
- https://ssdeep-project.github.io/ssdeep/ - fuzzy hashing (similarity, not integrity).
- https://www.glukhov.org/post/2025/05/generating-pdf-in-python/ - WeasyPrint = HTML/CSS->PDF + Jinja2; wkhtmltopdf deprecated.
- https://typer.tiangolo.com/alternatives/ + https://packaging.python.org/en/latest/guides/writing-pyproject-toml/ - Typer + hatchling + src layout.

### Tertiary (LOW confidence / needs validation)
- https://pypi.org/project/pyaff4/ - pyaff4 ~0.34 (2021), effectively unmaintained; AFF4 treated out of scope.
- https://github.com/libyal/libqcow - libqcow alpha, read-only; qcow2 optional.
- https://www.slashroot.in/how-does-file-deletion-work-linux + https://ext4magic.sourceforge.net/inode_en.html - ext4 deletion wipes inode block pointers (recovery-confidence basis).
- Daubert/admissibility & reproducibility for open-source forensic tools (jurisdiction-dependent): https://pmc.ncbi.nlm.nih.gov/articles/PMC12431127/ , https://jmids.avestia.com/2021/005.html.

---
*Research completed: 2026-05-30*
*Ready for roadmap: yes*
