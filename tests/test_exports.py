"""Every ``__all__`` entry is either used elsewhere or deliberately retained.

A published name is a promise. This gate keeps the promise deliberate: a name
in an ``__all__`` must either be imported somewhere outside its own module, or
be listed below with the reason it stays. Adding an export that nothing uses
and nobody justified fails here.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "pyautopsy"
TESTS = pathlib.Path(__file__).resolve().parent

# Names exported without an external importer, each retained on purpose.
#
# The rule: a type that a public function RETURNS or ACCEPTS stays exported even
# when no caller names it today, because a caller cannot annotate a value it
# cannot name. Everything else must earn its export by being used.
_DELIBERATELY_RETAINED: dict[str, str] = {
    # Orchestrator result types — returned by the public run_* entry points.
    "AnalyzeError": "raised by run_analyze; part of its contract",
    "AnalyzeResult": "returned by run_analyze",
    "FilterResult": "returned by run_filter",
    "LogsResult": "returned by run_logs",
    "RecoverResult": "returned by run_recover",
    "RecoveredFile": "carried in RecoverResult",
    "SearchResult": "returned by run_search",
    "ShellHistoryResult": "returned by the shell-history parser",
    # Seam value types — returned by the evidence seam's public functions.
    "DeletedInode": "yielded by iter_deleted_inodes",
    "RecoveredEntry": "returned by recover_meta",
    "VolumeEntry": "accepted by the FS-seam functions",
    "allocated_inodes": "public seam function; used by the fake-FS test double",
    "HeadReader": "parameter type of file_type",
    # Log-discovery value types — returned by the public discover functions.
    "CompletenessFinding": "carried in LogSet",
    "LogMember": "returned by order_rotated_set",
    "SyslogLine": "returned by parse_line",
    # Parser singletons/classes — named in the PARSERS tuple (EXT-01).
    "AuthParser": "the auth parser type; instantiated into PARSERS",
    "SyslogParser": "the syslog parser type; instantiated into PARSERS",
    "ShellHistoryParser": "the shell-history parser type; instantiated into PARSERS",
    # Security controls a caller may legitimately apply itself.
    "assert_redos_safe": "ReDoS guard; callable before handing a pattern in",
    "compile_regex": "the guarded compile; the only sanctioned way to build one",
    # Extension points.
    "ColumnCodec": "the type a new column's conversion must be declared as",
    "AuditPathError": "raised by AuditLog; part of its contract",
}


def _exports() -> dict[pathlib.Path, list[str]]:
    """Collect every module's ``__all__`` entries."""
    found: dict[pathlib.Path, list[str]] = {}
    for py in SRC.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "__all__" for t in node.targets
            ):
                found[py] = [
                    e.value
                    for e in node.value.elts  # type: ignore[attr-defined]
                    if isinstance(e, ast.Constant)
                ]
    return found


def _imported_names() -> dict[str, set[pathlib.Path]]:
    """Collect every name imported (or attribute-accessed) per file."""
    used: dict[str, set[pathlib.Path]] = {}
    for base in (SRC, TESTS):
        for py in base.rglob("*.py"):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - defensive
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        used.setdefault(alias.name, set()).add(py)
                elif isinstance(node, ast.Attribute):
                    used.setdefault(node.attr, set()).add(py)
    return used


def test_every_export_is_used_or_deliberately_retained() -> None:
    """No module promises a name that nothing uses and nobody justified."""
    exports = _exports()
    used = _imported_names()

    unjustified: list[str] = []
    for module, names in exports.items():
        for name in names:
            external = used.get(name, set()) - {module}
            if not external and name not in _DELIBERATELY_RETAINED:
                unjustified.append(f"{module.relative_to(SRC.parent.parent)}:{name}")

    assert not unjustified, (
        "these names are exported but nothing outside their module uses them, "
        "and they are not listed as deliberately retained: "
        f"{sorted(unjustified)}. Either make the name private, drop it from "
        "__all__, or add it to _DELIBERATELY_RETAINED with the reason."
    )


def test_retained_list_has_no_stale_entries() -> None:
    """The retained list does not outlive the names it justifies."""
    exported = {name for names in _exports().values() for name in names}
    stale = sorted(set(_DELIBERATELY_RETAINED) - exported)
    assert not stale, (
        f"_DELIBERATELY_RETAINED names no longer exported anywhere: {stale}"
    )
