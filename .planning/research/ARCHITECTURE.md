# Architecture Research

**Domain:** Automated digital forensic analysis (disk image + log → forensic report), Python/Linux CLI on The Sleuth Kit
**Researched:** 2026-05-30
**Confidence:** HIGH on the pipeline pattern, plaso/Autopsy designs, and TSK boundaries; MEDIUM on exact pytsk3 method signatures (well-established but verify at implementation).

## Standard Architecture

The forensic domain has a near-universal, well-settled pipeline shape: **Acquire → Process → Analyze → Report**, with a normalized event/artifact store in the middle that decouples producers (extractors/parsers) from the consumer (reporter). Both Autopsy and plaso are built this way. PyAutopsy should adopt the same shape but in a smaller, scriptable form.

The single most important architectural idea borrowed from both tools: **a common normalized store that all analyzers write into and the reporter reads from.** Autopsy calls this the *blackboard* (artifacts + attributes in a SQLite case DB). Plaso calls it *attribute containers* (event / event_data / event_data_stream, persisted to a SQLite storage file). This is the "spine" of the system — get it right early and every analyzer/reporter plugs into it.

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                          ACQUIRE (read-only)                           │
│  ┌────────────────┐   ┌───────────────────┐   ┌────────────────────┐   │
│  │ Evidence Loader│   │ Integrity/Hashing │   │ Case Init + COC    │   │
│  │ (image/dd/E01) │   │ (SHA-256 of image)│   │ (case metadata)    │   │
│  └───────┬────────┘   └─────────┬─────────┘   └─────────┬──────────┘   │
│          │  Img_Info (RO)        │ verify                │             │
├──────────┼──────────────────────┼───────────────────────┼─────────────┤
│          ▼                       ▼          PROCESS (extract)          │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │           Filesystem Abstraction (TSK / pytsk3)              │     │
│  │  Volume_Info → FS_Info → Directory walk → File + meta        │     │
│  └───────┬─────────────────┬──────────────────┬─────────────────┘     │
│          │                 │                  │                       │
│  ┌───────▼──────┐  ┌────────▼───────┐  ┌───────▼────────┐  ┌─────────┐ │
│  │ Metadata     │  │ Deleted-File   │  │ Log Parser     │  │ File    │ │
│  │ Extractor    │  │ Recovery/Carve │  │ (syslog, auth, │  │ Hashing │ │
│  │ (MAC times)  │  │ (UNALLOC)      │  │  app logs)     │  │ (SHA256)│ │
│  └───────┬──────┘  └────────┬───────┘  └───────┬────────┘  └────┬────┘ │
├──────────┼──────────────────┼──────────────────┼────────────────┼─────┤
│          ▼                  ▼                  ▼                ▼       │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │     CASE STORE (SQLite)  —  the normalized "spine"            │     │
│  │  files | metadata | events (timeline) | findings/artifacts   │     │
│  │  + case, evidence_source, hashes, run_log                    │     │
│  └────────────────────────────┬─────────────────────────────────┘     │
├───────────────────────────────┼───────────────────────────────────────┤
│                                ▼              ANALYZE                   │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  Timeline Builder (merge file MAC times + log events)        │     │
│  │  Findings/Analyzers (suspicious patterns, tags, correlation) │     │
│  └────────────────────────────┬─────────────────────────────────┘     │
├───────────────────────────────┼───────────────────────────────────────┤
│                                ▼              REPORT                    │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  Report Generator → HTML/PDF (human) + JSON/CSV (structured)  │     │
│  └──────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility (what it owns) | Typical Implementation |
|-----------|-------------------------------|------------------------|
| **Evidence Loader** | Open a disk image read-only; expose partitions/filesystems; never write to source | `pytsk3.Img_Info` (raw/dd) over the image path; partitions via `Volume_Info` |
| **Integrity / Hashing** | SHA-256 of the source image at ingest; verify on each run; record in case store | `hashlib`, streamed; compare against stored baseline |
| **Filesystem Abstraction (TSK)** | Mount filesystem, walk directory tree, yield file objects + raw metadata | `pytsk3.FS_Info`, `fs.open_dir()`, recursive walk, `file.info.meta` |
| **Metadata Extractor** | Normalize per-file metadata: MAC(B) timestamps, size, uid/gid, mode, inode, allocated/deleted flag | Reads `file.info.meta.{crtime,atime,mtime,ctime,size,uid,gid,mode,flags}` → `files`/`metadata` rows |
| **Deleted-File Recovery / Carver** | Detect unallocated/deleted entries and recover content; optional signature carving | `TSK_FS_META_FLAG_UNALLOC` detection via TSK; carving is a separate, later module |
| **File Hashing** | Per-recovered/per-notable file SHA-256 for the findings record | `hashlib` over `file.read_random()` chunks |
| **Log Parser** | Parse forensically relevant logs (syslog, auth.log, journald, app logs) into timeline events | Plugin-per-format parsers emitting normalized `events` rows |
| **Case Store (SQLite)** | Single source of truth: files, metadata, events, findings, case/COC metadata | One SQLite DB per case (Autopsy/plaso both do this) |
| **Timeline Builder** | Merge file MAC times + log events into one ordered, queryable timeline | Query/insert into `events`; derives the "super timeline" |
| **Findings / Analyzers** | Cross-cutting analysis that tags/correlates (e.g., deletions near a login) into `findings` | Read events/metadata, write `findings` rows |
| **Report Generator** | Render the case store into HTML/PDF + JSON/CSV | Jinja2 templates → HTML; `weasyprint` → PDF; `json`/`csv` exporters |

## Recommended Project Structure

```
src/pyautopsy/
├── cli/                    # argparse/click entry points, subcommands (ingest, report)
│   └── main.py
├── case/                   # case lifecycle + state store
│   ├── store.py            # SQLite open/migrate, repositories (files, events, findings)
│   ├── schema.sql          # DDL — the normalized spine (see Data Model below)
│   └── models.py           # dataclasses: FileRecord, TimelineEvent, Finding, Hash
├── evidence/               # read-only acquisition layer
│   ├── loader.py           # Img_Info wrapper, partition/FS discovery (pytsk3 boundary)
│   └── integrity.py        # SHA-256 image hashing + verification + chain-of-custody log
├── fs/                     # filesystem abstraction over TSK
│   ├── walker.py           # recursive directory walk → yields File objects
│   └── tsk.py              # thin pytsk3 wrapper (the ONLY module importing pytsk3)
├── extractors/             # PROCESS-stage producers (write to case store)
│   ├── base.py             # Extractor ABC: applies_to() / extract(ctx) → events/files
│   ├── metadata.py         # MAC times, ownership, perms, size
│   ├── recovery.py         # deleted/unallocated detection + recovery
│   └── hashing.py          # per-file SHA-256
├── parsers/                # log/artifact parsers (plugin registry)
│   ├── base.py             # LogParser ABC: format_spec() / parse(stream) → events
│   ├── registry.py         # discovery + dispatch (plaso-style manager)
│   ├── syslog.py
│   ├── auth.py
│   └── journald.py
├── timeline/
│   └── builder.py          # merge metadata + log events into ordered timeline
├── analysis/               # ANALYZE-stage (cross-cutting findings)
│   └── analyzers.py        # tagging / correlation → findings
├── report/
│   ├── generator.py        # orchestrates render
│   ├── templates/          # Jinja2 HTML templates
│   └── exporters.py        # JSON / CSV
└── core/
    ├── pipeline.py         # orchestrates Acquire→Process→Analyze→Report
    └── context.py          # RunContext: case store handle, config, logger
```

### Structure Rationale

- **`fs/tsk.py` is the *only* file that imports `pytsk3`.** This is the critical boundary. All native TSK behavior is wrapped behind a Pythonic interface (yield plain `dataclass` records), so the rest of the codebase is testable without an image and the native dependency is isolated for swapping/mocking.
- **`extractors/` and `parsers/` mirror plaso's split:** extractors operate on the filesystem (Autopsy's "ingest modules"); parsers operate on byte streams/files (plaso's "parsers/plugins"). Both are plugin families sharing a common base + registry.
- **`case/` owns the schema and is the only writer abstraction.** Every producer goes through repository methods, never raw SQL scattered across modules. This keeps the normalized contract enforceable.
- **`core/pipeline.py` is the conductor**, not a god-object: it wires producers → store → reporter and owns ordering, so individual stages stay decoupled.

## Architectural Patterns

### Pattern 1: Normalized Common Store (Blackboard / Attribute Containers)

**What:** All analyzers write into one normalized store (files, events, findings); the reporter only reads from it. Producers never talk to each other directly. This is Autopsy's *blackboard* and plaso's *attribute container store*.
**When to use:** Always, from day one — it is the architectural spine.
**Trade-offs:** (+) Add a new analyzer or report format without touching anything else; trivially reproducible; queryable. (−) Requires designing the normalized schema up front; a too-rigid schema fights heterogeneous artifacts (mitigate with a generic `findings` table + JSON attribute column, exactly as Autopsy's `blackboard_attributes` does).

```python
# Producers depend only on the store interface, never on each other.
class MetadataExtractor(Extractor):
    def extract(self, ctx: RunContext, file: FileRecord) -> None:
        ctx.store.add_event(TimelineEvent(
            ts=file.mtime, source="fs:metadata", kind="modified",
            path=file.path, inode=file.inode, file_id=file.id))
```

### Pattern 2: Plugin Registry + Dispatch (plaso parsers / Autopsy ingest modules)

**What:** Each parser/extractor is a class implementing a small ABC (`applies_to()` / `parse()`), self-registered into a manager. The pipeline discovers plugins at runtime and dispatches each file/stream to the parsers that claim it (via signature/format spec or extension).
**When to use:** For the extensible analyzer families (log parsers, artifact parsers, future carvers).
**Trade-offs:** (+) New artifact support = one new file, zero core changes; matches how the entire domain extends. (−) Slight indirection; needs a format-detection step so the right parser fires.

```python
@register_parser
class SyslogParser(LogParser):
    NAME = "syslog"
    def applies_to(self, stream) -> bool:
        return _looks_like_syslog(stream.peek(512))
    def parse(self, stream) -> Iterator[TimelineEvent]:
        for line in stream: ...
```

### Pattern 3: Read-Only Evidence Boundary

**What:** The source image is opened read-only and hashed at ingest; the hash is stored and re-verified before each run. The code path has *no* write access to the source — all output goes to a separate case directory. Mirrors the hardware write-blocker discipline (NIST / ISO 27037) in software.
**When to use:** Always — forensic soundness is a stated first-class requirement.
**Trade-offs:** (+) Defensible chain of custody; reproducible. (−) None worth noting; a small verify-on-open cost. Recommend documenting that PyAutopsy is *not* a substitute for a hardware write-blocker during acquisition — it operates on already-acquired images.

```python
# Open RO, hash once, verify thereafter. SHA-256 is the forensic baseline (MD5/SHA-1 deprecated).
img = pytsk3.Img_Info(image_path)          # read-only handle
baseline = sha256_stream(image_path)        # stored in case.evidence_source
assert baseline == case.stored_image_hash   # verify integrity each run
```

### Pattern 4: Pipeline Orchestrator (Acquire → Process → Analyze → Report)

**What:** A single conductor runs ordered stages, each consuming the previous stage's store output. Stages are independently runnable/resumable (helps reprocessing and testing).
**When to use:** The top-level control flow.
**Trade-offs:** (+) Clear ordering, resumable, easy to reason about. (−) Must define stage boundaries cleanly so a later stage never reaches back into a producer.

## Data Flow

### End-to-end flow (image → report)

```
disk image (.dd/.raw) ──RO──► Img_Info ──► Volume_Info ──► FS_Info
                                                              │
                              ┌───────────────────────────────┘ walk
                              ▼
                        File objects (info.meta)
        ┌──────────────┬──────────────┬───────────────┐
        ▼              ▼              ▼               ▼
  MetadataExtractor  Recovery     FileHashing     (log files read
  → metadata,events  → files      → hashes         from recovered FS)
        │              │              │               │
        └──────────────┴──────────────┴──────────────►  Log Parsers
                              │                          → events
                              ▼
                ┌──────────────────────────────┐
                │      CASE STORE (SQLite)      │
                │  files, metadata, events,     │
                │  hashes, findings, case meta  │
                └───────────────┬───────────────┘
                                ▼
                   TimelineBuilder (merge MAC + log events, order by ts)
                                ▼
                   Analyzers (correlate → findings)
                                ▼
                   ReportGenerator ──► report.html / report.pdf
                                   └─► report.json / timeline.csv
```

### Key Data Flows

1. **Metadata → timeline:** Each file yields up to 4 events (created/accessed/modified/changed = the MACB times). The timeline builder unions these with log events and orders by timestamp — this *is* the "super timeline."
2. **Recovery → findings + hashes:** Files flagged `UNALLOC` (deleted) become `files` rows marked deleted, get SHA-256 hashed, and generate a `finding` ("recovered deleted file"). The reporter highlights these.
3. **Logs → timeline:** Parsers emit normalized `events` rows identical in shape to filesystem events, so the timeline merges both sources transparently — the schema is what makes this possible.

## Data Model (recommended SQLite case store)

One SQLite DB per case in a dedicated case directory. SQLite is the correct, idiomatic choice: **both Autopsy and plaso use SQLite for the case/storage DB.** It is single-file (easy to archive/hash for COC), zero-config, transactional, and queryable.

```sql
-- Case + evidence provenance (chain of custody)
CREATE TABLE cases (
  id INTEGER PRIMARY KEY, name TEXT, examiner TEXT,
  created_utc TEXT, pyautopsy_version TEXT, notes TEXT);

CREATE TABLE evidence_sources (
  id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id),
  path TEXT, image_type TEXT,                 -- raw/dd/E01
  sha256 TEXT, acquired_utc TEXT, byte_size INTEGER);

CREATE TABLE run_log (                        -- audit / reproducibility
  id INTEGER PRIMARY KEY, case_id INTEGER, stage TEXT,
  started_utc TEXT, finished_utc TEXT, status TEXT, detail TEXT);

-- Filesystem object model (mirrors TSK tsk_objects/tsk_files idea, simplified)
CREATE TABLE files (
  id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES evidence_sources(id),
  parent_id INTEGER,                          -- self-ref for tree
  inode INTEGER, name TEXT, path TEXT,
  fs_type TEXT,                               -- ext4/ntfs/...
  size INTEGER, uid INTEGER, gid INTEGER, mode INTEGER,
  is_dir INTEGER, is_deleted INTEGER,         -- TSK_FS_META_FLAG_UNALLOC
  is_recovered INTEGER);

-- Per-file MAC(B) times kept structured (also exploded into events)
CREATE TABLE metadata (
  file_id INTEGER REFERENCES files(id),
  crtime TEXT, mtime TEXT, atime TEXT, ctime TEXT);   -- ISO-8601 UTC

CREATE TABLE hashes (
  file_id INTEGER REFERENCES files(id),
  algo TEXT, value TEXT);                      -- 'sha256'

-- THE NORMALIZED TIMELINE — fs metadata events AND log events land here
CREATE TABLE events (
  id INTEGER PRIMARY KEY, case_id INTEGER,
  ts_utc TEXT NOT NULL,                        -- ISO-8601, the sort key
  source TEXT,                                 -- 'fs:metadata' | 'log:syslog' | ...
  kind TEXT,                                   -- created/modified/login/...
  file_id INTEGER REFERENCES files(id),        -- nullable (log events may lack a file)
  message TEXT,                                -- human-readable summary
  attributes TEXT);                            -- JSON blob for parser-specific fields
CREATE INDEX idx_events_ts ON events(ts_utc);

-- Generic findings/artifacts (Autopsy blackboard analog: typed + JSON attributes)
CREATE TABLE findings (
  id INTEGER PRIMARY KEY, case_id INTEGER,
  type TEXT,                                   -- 'recovered_deleted_file', 'suspicious_login'
  severity TEXT, title TEXT, description TEXT,
  file_id INTEGER, event_id INTEGER,
  attributes TEXT);                            -- JSON name/value pairs
```

**Why this shape:** `events` + JSON `attributes` is the plaso pattern (typed core columns + serialized extras); `findings` + JSON `attributes` is the Autopsy blackboard pattern (artifact type + attribute name/value pairs). The normalized `events` table is what lets metadata, recovery, and logs all feed *one* timeline that the reporter consumes. Store all timestamps as ISO-8601 UTC strings to avoid TZ ambiguity (a classic forensic pitfall).

## Suggested Build Order (MVP-first vertical slice)

Build a **thin vertical slice end-to-end first**, then widen. The slice proves the spine (store + pipeline) before investing in many parsers.

| Order | Component | Why this order / dependency |
|-------|-----------|-----------------------------|
| **1** | Case store + schema (`case/`) | Everything writes here; the spine must exist first. |
| **2** | Evidence loader + integrity (`evidence/`) | Need a read-only, hashed image handle before any analysis. |
| **3** | TSK FS wrapper + walker (`fs/`) | The single native boundary; yields file objects all extractors need. |
| **4** | Metadata extractor (`extractors/metadata.py`) | Simplest real producer; proves files→store→events path. |
| **5** | Timeline builder (`timeline/`) | Consumes events; proves the merge concept with one source. |
| **6** | Report generator — HTML + JSON (`report/`) | **Closes the vertical slice: image → report. This is the MVP.** |
| **7** | Log parser framework + 1 parser (e.g. syslog) | Adds a *second* event source; validates the plugin registry + timeline merge. |
| **8** | Deleted-file recovery (`extractors/recovery.py`) | Higher-value forensic feature; depends on FS wrapper + findings table. |
| **9** | File hashing on notable/recovered files | Cheap; attaches integrity to findings. |
| **10** | Additional parsers + analyzers + PDF output | Breadth: more log/artifact parsers, correlation findings, polished report. |

**MVP = steps 1–6:** ingest a raw image read-only, hash it, walk the filesystem, extract MAC times, build a timeline, emit an HTML+JSON report. That is a complete, demonstrable, defensible slice. Recovery and log parsing (the headline forensic features) layer on *after* the spine is proven, each as an independent plugin that just writes more rows into the same store.

## Anti-Patterns

### Anti-Pattern 1: pytsk3 imported everywhere

**What people do:** Sprinkle `import pytsk3` and raw TSK structs across extractors, parsers, and the reporter.
**Why it's wrong:** Couples the whole codebase to a native, hard-to-mock dependency; makes unit tests require a real image; blocks swapping the backend or shelling out to `fls`/`icat` where bindings fall short.
**Do this instead:** Confine pytsk3 to `fs/tsk.py`, yielding plain dataclasses. Everything else is pure Python and testable with fixtures.

### Anti-Pattern 2: Each analyzer renders its own report fragment

**What people do:** Metadata module writes its own HTML, log module writes its own — reporter stitches strings.
**Why it's wrong:** N analyzers × M formats explosion; inconsistent output; no single queryable timeline.
**Do this instead:** Analyzers only write normalized rows to the store. The reporter reads the store. One renderer, many producers (the blackboard contract).

### Anti-Pattern 3: Mutating or writing to the source image

**What people do:** Mount the image read-write, or write recovered files / temp data back into the evidence path.
**Why it's wrong:** Destroys forensic soundness and chain of custody — the entire point of the tool.
**Do this instead:** Open read-only, hash at ingest, verify each run, write *all* output to a separate case directory. Never touch the source.

### Anti-Pattern 4: Local-time / naive timestamps in the timeline

**What people do:** Store timestamps as local time or naive datetimes.
**Why it's wrong:** Forensic timelines are useless if you can't trust ordering across sources and timezones; a known evidentiary pitfall.
**Do this instead:** Normalize *everything* to ISO-8601 UTC at the producer boundary; record original TZ in `attributes` if relevant.

### Anti-Pattern 5: Over-rigid schema that can't hold heterogeneous artifacts

**What people do:** Add a typed column per parser field.
**Why it's wrong:** Every new parser forces a migration; the schema rots.
**Do this instead:** Typed core columns + a JSON `attributes` column (the plaso/Autopsy approach). New parser fields go in JSON, queryable, no migration.

## Integration Points

### External Services / Native Tools

| Tool | Integration Pattern | Notes |
|------|---------------------|-------|
| The Sleuth Kit (libtsk) | In-process via `pytsk3` bindings | Primary path; FS walk, metadata, deleted-file flags, content read. Confine to `fs/tsk.py`. |
| TSK CLI (`fls`, `icat`, `mmls`) | `subprocess` fallback | Use only where bindings are awkward (some carving/recovery flows); shell-out is a known, accepted pattern. Keep behind the same wrapper. |
| WeasyPrint / wkhtmltopdf | Library call from `report/` | HTML → PDF for the human-readable report. Optional; JSON/HTML is the baseline. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `fs/` ↔ rest of app | Plain dataclasses (no pytsk3 leakage) | The native isolation seam. |
| extractors/parsers ↔ case store | Repository methods only (no raw SQL) | Enforces the normalized contract. |
| producers ↔ reporter | Through the store, never directly | Blackboard decoupling. |
| pipeline ↔ stages | Ordered calls + shared `RunContext` | Conductor owns ordering/resumability. |

## Where the Python Boundary Sits Relative to Native TSK

- **Native side (C / libtsk):** image parsing, volume/partition detection, filesystem parsing, inode/MFT walking, unallocated-block detection, content reads. *Do not reimplement any of this* — it is the trusted, validated core (a stated project constraint).
- **Python side (PyAutopsy):** orchestration, the case store/schema, normalization to the event/finding model, log parsing, timeline merging, analysis/correlation, and reporting. This is where all the *value-add automation* lives.
- **The seam:** `fs/tsk.py` (and an optional `subprocess` shim for `fls`/`icat`). Python calls in, plain records come out. This single boundary is the most important design decision for testability and longevity.

## Sources

- [Plaso DeepWiki — architecture & pipeline stages](https://deepwiki.com/log2timeline/plaso) — HIGH
- [Plaso Parsers and plugins (official docs)](https://plaso.readthedocs.io/en/latest/sources/user/Parsers-and-plugins.html) — HIGH
- [Plaso "How to write a parser/plugin" (official docs)](https://plaso.readthedocs.io/en/stable/sources/developer/How-to-write-a-parser.html) — HIGH (EventData subclass, RegisterParser, ParseFileObject, ParserMediator)
- [Plaso containers (events.py source)](https://plaso.readthedocs.io/en/latest/_modules/plaso/containers/events.html) — HIGH (event/event_data containers, _parser_chain, JSON+zlib SQLite storage)
- [Autopsy Ingest Modules (official user docs)](http://sleuthkit.org/autopsy/docs/user-docs/4.12.0/ingest_page.html) — HIGH (file vs data-source ingest modules)
- [Autopsy Module Development Overview / Blackboard](https://sleuthkit.org/autopsy/docs/api-docs/4.1/platform_page.html) — HIGH (blackboard artifacts/attributes, SleuthkitCase, SQLite case DB)
- [TSK & Autopsy DB Schema (jni-docs 9.4)](http://sleuthkit.org/sleuthkit/docs/jni-docs/4.12.1/db_schema_9_4_page.html) — HIGH (tsk_objects/tsk_files, blackboard tables)
- [pytsk3 on PyPI](https://pypi.org/project/pytsk3/) — HIGH (binding to libtsk, Python ≥3.10)
- [Python SleuthKit for FS investigations](https://johal.in/digital-forensics-toolkit-python-sleuthkit-for-file-system-investigations/) — MEDIUM (pytsk3 walk/metadata/recovery usage)
- [Best practices for write blockers / forensic imaging](https://hawkeyeforensic.com/best-practices-for-using-write-blockers-in-forensic-imaging/) — MEDIUM (read-only handling, SHA-256 baseline, ISO 27037/NIST)
- [Hash values & evidence integrity](https://www.granitediscovery.com/2025/09/08/the-cornerstone-of-digital-evidence-ensuring-integrity-with-hash-values/) — MEDIUM (SHA-256 as forensic minimum)

---
*Architecture research for: automated digital forensic analysis CLI on The Sleuth Kit*
*Researched: 2026-05-30*
