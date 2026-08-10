
## Project

**PyAutopsy**

PyAutopsy is a Python tool for automated digital forensic analysis on Linux. It
ingests disk images and log files, analyzes file metadata, recovers deleted
files, and generates a structured forensic report suitable for evidence
presentation. It is built on top of Autopsy / The Sleuth Kit, wrapping their
forensic primitives in an automated, scriptable Python workflow.

**Core Value:** Turn a raw disk image (and associated logs) into a defensible, presentation-ready
forensic report — with deleted-file recovery and metadata analysis — through a
single automated Python workflow.

### Constraints

- **Tech stack**: Python on Linux — Required: project explicitly targets Python + Linux
- **Dependencies**: Autopsy / The Sleuth Kit (TSK) and Python bindings (e.g. `pytsk3`) — Required: core forensic primitives come from TSK, not reimplemented
- **Forensic soundness**: Evidence sources must be treated read-only; findings must be hashable/reproducible — Why: output supports evidence presentation
- **Reporting**: Report must be both human-readable and structured/exportable — Why: needs to serve both investigators and downstream tooling

## Technology Stack

## The Central Decision: pytsk3 (direct TSK bindings), NOT Autopsy

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Python** | 3.12 (min 3.11) | Implementation language | Modern type hints, matches pytsk3 wheels (3.10–3.14) and plaso (>=3.10). Avoid 3.13/3.14 only if a transitive dep lags. |
| **The Sleuth Kit (libtsk)** | sleuthkit 4.12+ (system pkg) | Filesystem analysis engine | The mature, court-trusted standard for filesystem forensics and deleted-file recovery. Everything else wraps this. |
| **pytsk3** | 20260520 (latest; pin a dated release) | Python 3 bindings to libtsk | Direct, supported, native Python access to TSK: `Img_Info`, `Volume_Info`, `FS_Info`, `File`, `Directory` walking, MAC times, slack/deleted entries. Maintained by Joachim Metz (libyal). Apache-2.0. (HIGH) |
| **pyewf** (libewf-python) | libewf 20240506+ | EnCase/EWF (`.E01`, `.Ex01`, `.S01`) image access | E01 is the dominant evidence-container format in DFIR. pyewf exposes it as a file-like object that feeds straight into pytsk3's `Img_Info`. (HIGH) |
| **plaso / log2timeline** | 20260512 (latest) | Super-timeline generation | The de-facto standard for automated forensic timelines across hundreds of artifact types. Use as the timeline engine rather than reimplementing. Python >=3.10. (HIGH) |

### How the core pieces compose

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **dfVFS** | 20260207 (latest) | Higher-level "virtual file system" over TSK/pyewf/pyqcow | **Recommend adopting** instead of hand-rolling the image-format/volume-system glue. dfVFS already integrates pytsk3 + pyewf + pyqcow + LVM/BitLocker back-ends behind one read-only API and is the layer plaso itself uses. Reduces forensic-correctness risk. (HIGH) |
| **pyqcow** (libqcow-python) | 20240308 | QEMU qcow/qcow2 image access | Only if you must ingest VM disk images. Library is "alpha," read-only — fine for forensics. Optional. (MEDIUM) |
| **python-systemd** | 235+ (system `python3-systemd`) | Read binary systemd journald (`/var/log/journal/*.journal`) | Required for modern Linux log forensics — journald is binary/indexed, not text. `systemd.journal.Reader` gives filtered access. As of systemd v259 persistent journals are default, so expect them. (HIGH) |
| **ssdeep** (Python binding) | 3.4+ (libfuzzy system lib) | Context-triggered piecewise (fuzzy) hashing | File-similarity matching, finding near-duplicate/modified files. De-facto fuzzy-hash standard, ~2x faster than TLSH. (HIGH) |
| **python-tlsh** | 4.x | Alternative fuzzy hash (Trend Micro TLSH) | Use alongside or instead of ssdeep when robustness to large edits matters (TLSH is in VirusTotal/MalwareBazaar). Optional. (MEDIUM) |
| **Jinja2** | 3.1+ | HTML report templating | Industry-standard templating; renders the human-readable report and feeds WeasyPrint. (HIGH) |
| **WeasyPrint** | 63+ | HTML/CSS → PDF | Best HTML-to-PDF path: write one Jinja2 HTML/CSS report, render to both HTML and PDF. Excellent CSS (incl. flexbox) for evidence-presentation layout. (HIGH) |
| **pydantic** | 2.x | Typed models for findings + structured JSON export | Models for files, timeline events, hashes, chain-of-custody. `.model_dump_json()` gives the structured/exportable output PROJECT.md requires, with validation. (HIGH) |
| **Typer** | 0.12+ | CLI framework | Type-hint-driven CLI, built on Click; minimal boilerplate, auto help/validation, subcommands (`ingest`, `recover`, `timeline`, `report`). Matches the project's type-hint + modern-Python posture. (HIGH) |
| **Rich** | 13+ | Terminal progress/output | *Not a declared dependency.* Arrives transitively via Typer, which renders `--help` through it. PyAutopsy imports it nowhere and declares it nowhere: CLI output is plain `typer.echo` (issue #1). |
| **hashlib** | stdlib | Evidence integrity (MD5/SHA-1/SHA-256) | Image + file hashing for chain of custody. SHA-256 primary; MD5/SHA-1 also computed because NSRL and legacy evidence indexes use them. (HIGH) |

### Hashing / integrity specifics

- **`hashlib` (stdlib)** for cryptographic hashes. Compute **SHA-256 as the primary integrity hash**, but also emit **MD5 and SHA-1** for each artifact — not for security, but because **NSRL RDS** and most existing hash sets are keyed on MD5/SHA-1, and EWF images store stored-vs-computed MD5/SHA-1 you should verify on ingest.
- **NSRL (National Software Reference Library) RDS**: use to *filter out known-good files* (reduce noise) and *flag known-bad*. The modern RDS is distributed as large **SQLite "minimal" databases**; query directly with stdlib `sqlite3`. Treat NSRL ingestion as an optional, later phase — it is a big external dataset, not a pip install. (MEDIUM — verify current RDS distribution format at acquisition time.)
- **Fuzzy hashing (ssdeep/TLSH)** is *similarity*, not integrity — keep it conceptually separate from chain-of-custody hashes in the data model.

### Timeline generation

| Approach | Use it for |
|----------|-----------|
| **plaso (`log2timeline.py` → `.plaso` → `psort.py`)** | The primary super-timeline: broad artifact coverage, output to JSON/CSV/Elasticsearch. Drive it as a library or subprocess. **Recommended default.** |
| **TSK `fls` + `mactime` (the bodyfile workflow)** | A lightweight, purely-filesystem MAC-time timeline you can generate directly via pytsk3 (emit bodyfile, sort to mactime). Good for a fast, dependency-light timeline and for cross-checking plaso. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **hatchling** | Build backend | Modern, simple, src-layout friendly. `[build-system] requires = ["hatchling"]`. (uv_build is an emerging alternative; hatchling is the safe, widely-supported default.) |
| **uv** | Dependency/venv/lock management | Fast resolver + lockfile; manages dev dependency-groups. Optional but recommended for reproducible forensic builds. |
| **src layout** | `src/pyautopsy/` package root | Prevents "tested the wrong copy" bugs; standard for 2025/2026. Set `pythonpath = "src"` in pytest config. |
| **pytest** | Testing | Use small fixture disk images (generate tiny FAT/ext images with deleted files) as golden test data. |
| **ruff** | Lint + format | Single fast tool replacing flake8/isort/black. |
| **mypy** | Static typing | Enforces the type-hint discipline the project commits to. |
| **pre-commit** | Git hooks | Run ruff/mypy/pytest gates before commit. |

## Installation

# --- System packages (Fedora / RHEL) ---

# --- System packages (Debian / Ubuntu / Kali) equivalents ---

# sudo apt install -y libtsk-dev libewf-dev libfuzzy-dev libsystemd-dev \

#   build-essential python3-dev

# --- Python (declared in pyproject.toml [project.dependencies]) ---

# ssdeep and python-systemd are usually installed via system packages

# (python3-systemd, python3-ssdeep) to match the linked C libs.

# --- Dev (pyproject [dependency-groups] dev) ---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| pytsk3 (direct TSK) | Autopsy ingest/report modules (Jython) | Never for this project — Jython 2.7, no native libs. Only if deliverable were *an Autopsy plugin*. |
| pytsk3 | Calling TSK CLI tools (`fls`, `icat`, `mmls`) via subprocess | Acceptable for quick prototypes or for `mactime`; brittle (text parsing) vs. structured pytsk3 objects for a maintained tool. |
| dfVFS layer | Hand-rolled pyewf+pytsk3 glue | If you want zero extra deps and only ever handle one format (raw dd), the manual `Img_Info` adapter is fine and simpler. dfVFS pays off as soon as you support multiple containers/volume systems. |
| Typer | Click | Click if you dislike type-hint-driven APIs or need a pattern Typer doesn't expose; Typer is built on Click so you can drop down. |
| Typer | argparse | argparse only if a zero-dependency stdlib-only CLI is a hard requirement. Gets verbose with subcommands. |
| WeasyPrint | ReportLab | ReportLab for pixel-precise, programmatic, data-heavy PDFs (complex tables/charts built in code). More work; no HTML reuse. Use if the report is chart-dense rather than document-style. |
| ssdeep | TLSH | TLSH when similarity must survive large file modifications, or to align with VirusTotal/MalwareBazaar indicators. |
| plaso (full) | TSK `fls`+`mactime` only | mactime-only when you need just filesystem MAC times fast with minimal dependencies (good MVP default). |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Autopsy as the automation engine** | Jython 2.7 modules can't use native Python libs; no supported headless batch CLI; you'd inherit a GUI app's runtime to do library-level work. | `pytsk3` directly on `libtsk`. |
| **Jython / Python 2.7 anything** | EOL; blocks the entire modern forensic stack (all the C-backed libs). | Python 3.11+. |
| **Reimplementing filesystem parsing / deleted-file recovery** | TSK is decades-hardened and trusted in court; a reimplementation is a forensic-soundness liability. | TSK via pytsk3 (PROJECT.md already mandates this). |
| **pyaff4 (AFF4)** as a core dependency | Last PyPI release ~0.34 (2021); effectively unmaintained. AFF4 is rare in practice vs. E01/raw. | Support E01 (pyewf) + raw + qcow; treat AFF4 as out-of-scope unless a specific case needs it. |
| **wkhtmltopdf** for PDF | Project archived/unmaintained; QtWebKit security rot. | WeasyPrint. |
| **MD5/SHA-1 as the *only* integrity hash** | Collision-broken; weak for tamper-evidence. | SHA-256 primary; keep MD5/SHA-1 only for NSRL/EWF compatibility lookups. |
| **Mutating/auto-mounting evidence** (e.g. loopback `mount` of the image rw) | Violates read-only forensic soundness; alters timestamps. | Read-only access via pytsk3/pyewf, which never writes to the source. |
| **Poetry / setuptools `setup.py`** as the build path | Heavier / legacy; not the 2025/2026 default. | hatchling (+ optionally uv). |

## Stack Patterns by Variant

- pytsk3 + pyewf + native TSK bodyfile/mactime timeline + Jinja2/WeasyPrint reporting + hashlib.
- Skip plaso and dfVFS initially. Hand-write the `Img_Info` adapter for raw + E01.
- Because: smallest install surface, fastest to a working "image → report" pipeline; everything is directly inspectable for forensic defensibility.
- Add dfVFS (image/volume abstraction) and plaso (timeline engine) as a `[timeline]` extra.
- Because: plaso already parses hundreds of artifact types and logs; reusing it beats reimplementing parsers and is the community standard.
- Add pyqcow (qcow2). dfVFS already wires it in.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| pytsk3 20260520 | Python 3.10–3.14 | Prebuilt wheels; source build needs `sleuthkit-devel`/`libtsk-dev`. Pin the dated release for reproducibility. |
| pytsk3 | libtsk (sleuthkit) 4.12+ | When building from source, pytsk3 links against the system libtsk version. |
| plaso 20260512 | Python >=3.10 | Large dependency tree (incl. dfVFS, pyewf, dfwinreg). Isolate as an optional extra. |
| dfVFS 20260207 | pytsk3 + pyewf + pyqcow | dfVFS is the integration layer; keep its back-end libs version-aligned with what dfVFS pins. |
| WeasyPrint 63+ | Python 3.9+ | Needs system libs (pango, cairo, gdk-pixbuf) — another native dependency to document. |
| ssdeep (binding) | libfuzzy (system) | Python binding must match installed libfuzzy; prefer the distro `python3-ssdeep` to avoid mismatch. |
| python-systemd | libsystemd (system) | Install distro `python3-systemd` matching the host systemd. |

## Sources

- https://pypi.org/project/pytsk3/ — latest pytsk3 = 20260520, Python 3.10–3.14, libtsk build dep (HIGH)
- https://github.com/py4n6/pytsk — pytsk3 nature/maintenance (libyal/Joachim Metz) (HIGH)
- https://github.com/log2timeline/plaso + https://plaso.readthedocs.io/ — plaso 20260512, Python >=3.10, log2timeline/psort/pinfo workflow (HIGH)
- https://github.com/log2timeline/dfvfs + https://dfvfs.readthedocs.io/ + https://dfvfs.readthedocs.io/en/latest/sources/Supported-formats.html — dfVFS 20260207, EWF needs libewf/pyewf, read-only design (HIGH)
- https://www.autopsy.com/python-autopsy-module-tutorial-1-the-file-ingest-module/ + https://deepwiki.com/sleuthkit/autopsy/5.2-module-development + https://github.com/sleuthkit/autopsy/issues/988 — Autopsy modules are Jython 2.7, cannot use native-code Python libs (HIGH; decisive for the Autopsy-vs-TSK decision)
- https://www.sleuthkit.org/ — TSK is the C library/CLI powering Autopsy and commercial tools (HIGH)
- https://pypi.org/project/pyaff4/ + https://libraries.io/pypi/pyaff4 — pyaff4 0.34, last release ~2021 (unmaintained) (MEDIUM)
- https://github.com/libyal/libqcow + https://libraries.io/pypi/libqcow-python — libqcow alpha, read-only, pyqcow 20240308 (MEDIUM)
- https://ssdeep-project.github.io/ssdeep/ + https://en.wikipedia.org/wiki/Fuzzy_hashing — ssdeep CTPH de-facto standard, ~2x faster than TLSH; TLSH in VirusTotal/MalwareBazaar (HIGH/MEDIUM)
- https://www.freedesktop.org/software/systemd/python-systemd/journal.html — systemd.journal.Reader for binary journald; v259 persistent-by-default (HIGH)
- https://www.glukhov.org/post/2025/05/generating-pdf-in-python/ + https://www.nutrient.io/blog/top-10-ways-to-generate-pdfs-in-python/ — WeasyPrint = HTML/CSS→PDF + Jinja2; ReportLab = programmatic/data-heavy; wkhtmltopdf deprecated (HIGH)
- https://typer.tiangolo.com/alternatives/ + https://codecut.ai/comparing-python-command-line-interface-tools-argparse-click-and-typer/ — Typer (type-hint, on Click) recommended for maintainable CLIs (HIGH)
- https://packaging.python.org/en/latest/guides/writing-pyproject-toml/ + https://learn.scientific-python.org/development/guides/packaging-simple/ — hatchling + src layout + dependency-groups + pytest `pythonpath=src` (HIGH)

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.

## Agent skills

### Issue tracker

GitHub Issues on `MatrixMagician/PyAutopsy`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, used verbatim as label strings. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root (neither exists yet; created lazily). See `docs/agents/domain.md`.

## Workflow

Edit code directly. There is no planning gate to route through.

The durable record of a change is the code, its tests, and the commit message.
Historical planning documents live in `.planning/` and are read-only history:
they describe how the project got here, not a process to follow.

## Developer Profile

Senior engineer and tool-builder; domain-aware, multi-language (Python, TS/React, Rust, Go).

- **Autonomy between gates.** Drive multi-step work without per-step approval; pause for explicit sign-off at decision and release points.
- **Precise & reproducible:** detailed repro/test steps, exact commands/paths; honor tightly-scoped requirements without broadening scope.
- **Protect history & releases:** split/atomic commits, careful tag/deploy handling, security review on changes.
- **Register:** courteous and direct - plain, decisive; apply restated corrections immediately.
- **Surface options crisply.** Assume a senior, domain-aware reader; cite evidence where domain specifics matter.
- **Persist context** (decisions, patterns, bugs) to graphmind memory proactively.
