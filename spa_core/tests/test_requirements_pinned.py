"""WS2 (Round-2 security): runtime dependency pins MUST carry an upper bound.

An unbounded ``>=`` floor lets an unattended ``pip install -r requirements.txt``
silently pull a breaking next-major release into the running apiserver. This CI
guard parses every requirements file and asserts each pinned runtime dependency
declares an UPPER bound (``<`` / ``<=`` / ``==`` / ``~=``), i.e. no naked ``>=``.

stdlib-only, deterministic. Run::

    python3 -m pytest spa_core/tests/test_requirements_pinned.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Requirements files that pin runtime deps (relative to repo root).
_REQ_FILES = (
    "requirements.txt",
    "spa_core/requirements.txt",
)

# A requirement line: name[extras]<specifiers>. We only enforce on lines that
# declare at least one specifier; bare names / VCS / -r includes are skipped.
_REQ_LINE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*"
    r"(?:\[[^\]]+\])?\s*"
    r"(?P<spec>[<>=!~].*)$"
)


def _iter_requirement_lines(text: str):
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):  # comment / blank / -r include
            continue
        m = _REQ_LINE.match(line)
        if m:
            yield m.group("name"), m.group("spec")


def _has_upper_bound(spec: str) -> bool:
    """True if the specifier set caps the version (no naked `>=` floor)."""
    # `==`, `~=` and any `<`/`<=` clause cap the upper version.
    if "==" in spec or "~=" in spec:
        return True
    # A `<` that is NOT part of a `<=`-... already counts; `<=` also caps.
    return bool(re.search(r"<", spec))


def test_all_requirements_files_exist():
    for rel in _REQ_FILES:
        assert (_REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_unbounded_floor():
    """Every pinned runtime dep declares an upper bound."""
    offenders: list[str] = []
    checked = 0
    for rel in _REQ_FILES:
        path = _REPO_ROOT / rel
        text = path.read_text(encoding="utf-8")
        for name, spec in _iter_requirement_lines(text):
            checked += 1
            if not _has_upper_bound(spec):
                offenders.append(f"{rel}: {name} {spec}")
    assert checked > 0, "no pinned requirements parsed — parser/file drift"
    assert not offenders, (
        "unbounded `>=` floor(s) (add an upper bound, e.g. <2.0.0):\n  "
        + "\n  ".join(offenders)
    )


def test_security_relevant_deps_capped():
    """The deps named by WS2 specifically must be present and capped."""
    must_cap = {"fastapi", "uvicorn", "pydantic", "bcrypt", "requests", "reportlab"}
    seen: dict[str, str] = {}
    for rel in _REQ_FILES:
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        for name, spec in _iter_requirement_lines(text):
            seen[name.lower()] = spec
    missing = sorted(d for d in must_cap if d not in seen)
    assert not missing, f"WS2 deps not pinned anywhere: {missing}"
    uncapped = sorted(d for d in must_cap if not _has_upper_bound(seen[d]))
    assert not uncapped, f"WS2 deps without upper bound: {uncapped}"
