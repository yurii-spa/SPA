"""Tests for architecture/roles.json (ADR-554 'role identity' section).

Authority binds to ``role_id``; ``display_name`` is UI metadata only. These tests check both halves
of that claim: the schema/identity facts in the file, AND that no live authority check in
``spa_core`` branches on a display name instead of a role_id.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROLES_PATH = ROOT / "architecture" / "roles.json"

# the former CIO display name stays in the guard: it must never become an authority key either
DISPLAY_NAMES = ("Oracle", "Sherlock", "Штирлиц", "Шурик")
#: files allowed to carry a display-name literal at all (identity declaration / tests / contract).
ALLOWED_FILES = {ROLES_PATH}


def _roles_doc() -> dict:
    return json.loads(ROLES_PATH.read_text())


def _role(doc: dict, role_id: str) -> dict:
    match = [r for r in doc["roles"] if r["role_id"] == role_id]
    assert len(match) == 1, f"expected exactly one role_id={role_id!r}, found {len(match)}"
    return match[0]


def test_schema_tag():
    doc = _roles_doc()
    assert doc["schema"] == "roles/1"


def test_cio_title_exact():
    doc = _roles_doc()
    cio = _role(doc, "chief_investment_officer")
    assert cio["title"] == "Chief Investment Officer"
    assert cio["display_name"] == "Oracle"  # owner renamed the display identity 2026-10-04 (was «Штирлиц»)
    assert cio["implemented"] is True


def test_coo_reserved_and_not_implemented():
    doc = _roles_doc()
    coo = _role(doc, "chief_operating_officer")
    assert coo["title"] == "Chief Operating Officer"
    assert coo["display_name"] == "Шурик"
    assert coo.get("reserved") is True
    assert coo["implemented"] is False
    assert coo["components"] == []


def test_component_paths_exist():
    doc = _roles_doc()
    cio = _role(doc, "chief_investment_officer")
    for comp in cio["components"] + cio["related_preexisting"]:
        p = ROOT / comp["path"]
        assert p.exists(), f"roles.json names a component that does not exist: {comp['path']}"


def test_authority_per_component():
    """ADR-554 review finding 11: the role OWNS only the advisory layer (authority NONE). The paper veto and
    brake are related pre-existing mechanisms with their own ADRs — listed so the reader sees them, but the
    role neither owns nor extends their authority («authority binds to role_id» would otherwise confer it)."""
    doc = _roles_doc()
    cio = _role(doc, "chief_investment_officer")
    assert cio["authority"] == "NONE"
    assert {c["path"]: c["authority"] for c in cio["components"]} == {"spa_core/investment_cio/": "NONE"}
    related = {c["path"]: c["authority"] for c in cio["related_preexisting"]}
    assert related == {
        "spa_core/paper_trading/cio_arming.py": "PAPER_VETO",
        "spa_core/investment_os/directive.py": "PAPER_BRAKE",
        "spa_core/investment_os/agents/chief_investment.py": "ADVISORY_INPUT_TO_BRAKE",
    }
    assert all(c.get("governed_by") and "NOT conferred" in c.get("note", "") for c in cio["related_preexisting"])


def test_may_not_covers_execution_and_claims():
    doc = _roles_doc()
    cio = _role(doc, "chief_investment_officer")
    must_forbid = ("move money", "change RiskPolicy", "enable live trading or live DeFi",
                  "publish financial claims")
    for phrase in must_forbid:
        assert any(phrase in item for item in cio["may_not"]), f"missing may_not: {phrase}"


def test_rules_state_display_name_is_ui_only():
    doc = _roles_doc()
    assert any("display_name is UI metadata only" in r for r in doc["rules"])
    assert any("no agent is created to fill a title" in r for r in doc["rules"])


# ── reverse guard: a display name is never used as an authority KEY anywhere in spa_core ───────────

def _py_files(root: Path):
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        yield p


def _is_excluded(path: Path) -> bool:
    if path in ALLOWED_FILES:
        return True
    if path.name == "contract.py" and path.parent.name == "investment_cio":
        return True  # the frozen contract declares ROLE_DISPLAY_NAME itself
    if path.name.startswith("test_"):
        return True
    if "/tests/" in str(path).replace("\\", "/"):
        return True
    return False


class _ConditionalDisplayNameUse(ast.NodeVisitor):
    """Flags a display-name string literal used as part of a COMPARISON, dict KEY, or
    subscript/lookup index — i.e. as the thing an authority check branches on."""

    def __init__(self):
        self.hits: list[str] = []

    def _is_display_name(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in DISPLAY_NAMES

    def visit_Compare(self, node: ast.Compare):
        if self._is_display_name(node.left) or any(self._is_display_name(c) for c in node.comparators):
            self.hits.append(ast.dump(node))
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict):
        for k in node.keys:
            if k is not None and self._is_display_name(k):
                self.hits.append(ast.dump(node))
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        sl = node.slice
        if self._is_display_name(sl):
            self.hits.append(ast.dump(node))
        self.generic_visit(node)


def test_display_name_never_used_as_an_authority_key():
    """Grep spa_core (outside roles.json / contract.py / tests) for either display name; a hit is
    fine when the file merely DISPLAYS it (a future Mission Control render, a log line) — it is a
    violation only when the literal is the thing a comparison, dict key or subscript branches on.

    Documented today (2026-10-04): no file outside roles.json/contract.py/tests carries either name
    yet — Mission Control's "capital.investment_cio" section (ADR-554, ADR-552) is future work.
    """
    violations = []
    for path in _py_files(ROOT / "spa_core"):
        if _is_excluded(path):
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        if not any(name in text for name in DISPLAY_NAMES):
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        visitor = _ConditionalDisplayNameUse()
        visitor.visit(tree)
        if visitor.hits:
            violations.append((str(path), visitor.hits))
    assert violations == [], f"display name used as an authority-check key: {violations}"


def test_cio_display_name_has_one_value_everywhere_it_is_shown():
    """Owner renamed the CIO's display identity to «Oracle» (2026-10-04). Mission Control used to
    carry its own hard-coded literal, so a rename in roles.json would not have reached the UI. The
    registry, the CIO contract, the Mission Control section and both UI languages must agree."""
    from spa_core.investment_cio import contract as cio_contract
    from spa_core.studio_os import mission_control as mc
    name = _role(_roles_doc(), "chief_investment_officer")["display_name"]
    assert cio_contract.ROLE_DISPLAY_NAME == name
    assert mc._cio_display_name() == name
    i18n = (ROOT / "spa_core" / "studio_os" / "mission_ui" / "i18n.js").read_text(encoding="utf-8")
    titles = [ln for ln in i18n.splitlines() if '"cio.title"' in ln or '"cio.short"' in ln]
    assert len(titles) == 4 and all(name in ln for ln in titles), titles
    assert "Штирлиц" not in i18n


def test_head_of_research_is_sherlock_with_no_capital_authority():
    """Owner selected «Sherlock» for head_of_research (RM-EVIDENCE-01). The role governs research/paper
    admission only: authority over capital is NONE and the may_not list carries the capital boundary."""
    r = _role(_roles_doc(), "head_of_research")
    assert r["title"] == "Head of Research" and r["display_name"] == "Sherlock"
    assert r["authority"] == "NONE" and r["authority_over_capital"] == "NONE"
    assert {c["authority"] for c in r["components"]} == {"PAPER_ADMISSION"}
    for must_not in ("allocate capital", "move money", "approve live use", "change RiskPolicy",
                     "change Oracle (cio-policy-v1) policy"):
        assert must_not in r["may_not"], must_not
