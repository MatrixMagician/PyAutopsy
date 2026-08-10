"""D-43 guard: Phase 5 must add NO new runtime dependency (regression, GREEN).

Unlike the other Phase-5 Wave-0 stubs (which are RED until the slices land), this
test PASSES now and must keep passing: it pins the ``[project.dependencies]``
array in ``pyproject.toml`` to the exact Phase-4 baseline. The whole architectural
thesis of Phase 5 (RESEARCH §Standard Stack) is "stdlib-only on top of the
existing set" — the three log parsers use ``re``/``gzip``/``datetime``/
``zoneinfo``, search reuses the Phase-4 ``filter/*`` infra, and the unallocated
read goes through the existing seams. No ``python-systemd``, no syslog-parsing
PyPI lib, no new native binding (D-06 single-seam discipline preserved).

If a later Phase-5 slice adds a runtime dependency, this test FAILS, forcing an
explicit decision (and a baseline update) rather than a silent dependency creep.
The comparison is on the *set* of declared runtime requirements (order- and
comment-insensitive) so a benign reformat of the array does not false-fail, while
adding/removing any requirement does.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# The declared runtime dependency set. Started as the Phase-4 baseline; D-43
# forbids adding to it without an explicit decision recorded here.
#
# ``rich`` was removed by a deliberate baseline update (issue #1): it was
# declared but never imported — CLI output is plain ``typer.echo`` — and every
# runtime dependency is something an examiner may have to justify in an
# evidence context.
_BASELINE_DEPENDENCIES: frozenset[str] = frozenset(
    {
        "pytsk3==20260520",
        "python-magic==0.4.27",
        "typer>=0.12,<1",
        "jinja2>=3.1,<4",
    }
)


def _normalize(req: str) -> str:
    """Strip all internal whitespace so a reformat of the array does not false-fail."""
    return re.sub(r"\s+", "", req)


def _declared_runtime_dependencies() -> frozenset[str]:
    """Return the normalized `[project.dependencies]` set from pyproject.toml."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    return frozenset(_normalize(d) for d in deps)


def test_no_new_runtime_dependency_added() -> None:
    """`[project.dependencies]` is byte-equivalent to the declared baseline (D-43)."""
    declared = _declared_runtime_dependencies()
    baseline = frozenset(_normalize(d) for d in _BASELINE_DEPENDENCIES)

    added = declared - baseline
    removed = baseline - declared
    assert not added, (
        "Phase 5 must add NO new runtime dependency (D-43): unexpected "
        f"dependencies {sorted(added)} in pyproject.toml [project.dependencies]. "
        "Phase 5 is stdlib-only on top of the existing set — re-route through "
        "re/gzip/datetime/zoneinfo or the existing seams, or get an explicit "
        "decision to update the baseline."
    )
    assert not removed, (
        "An existing runtime dependency disappeared from pyproject.toml "
        f"[project.dependencies]: {sorted(removed)}. Update the declared baseline "
        "deliberately if this removal is intended."
    )


def test_no_python_systemd_or_native_log_binding() -> None:
    """Belt-and-braces D-43/D-06: the deferred journald deps are absent everywhere.

    journald (LOG-05) is explicitly deferred to v2: no ``python-systemd`` and no
    second native binding may appear in any dependency table (runtime, ewf, or
    dev). This catches a dep added under the wrong table that the runtime-set
    check above would miss.
    """
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project", {})
    all_reqs: list[str] = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        all_reqs.extend(extra)
    blob = _normalize("|".join(all_reqs)).lower()
    for forbidden in ("python-systemd", "systemd", "libsystemd", "pysyslog"):
        assert forbidden not in blob, (
            f"forbidden journald/syslog binding '{forbidden}' appears in "
            "pyproject.toml — journald is deferred to LOG-05/v2 (D-43, no new "
            "native seam)."
        )
