"""spa_core/tests/test_mission_no_money_action.py — RM-TRUTH-01 / ADR-580 Director OS v2 design
§1 rule 4 + §6: the Company Truth cockpit is read-only end to end — UI, server and model.

Three layers, each checked by its own means (no layer's green answers for another):
  * UI (``mission_ui/*``): no ``<form``, no non-GET ``fetch``/``XMLHttpRequest``, no
    ``act:``/``/pause``/``/resume``/``kill``/``set_status``/``record_owner_answer``; every
    ``href`` is ``#...`` or ``https://t.me/...``.
  * Server (``mission_server.py``): POST/PUT/PATCH/DELETE are wired to one 405 handler on
    every listener — checked structurally here; the live socket behaviour is already covered
    by ``test_mission_server.py::test_post_put_delete_are_405_with_allow_header`` and its public
    variant, which this file does not duplicate.
  * Model (``company_truth.py``): its own AST imports neither ``spa_core.execution`` nor
    ``spa_core.telegram`` nor a ``governance.kill_switch`` writer — the read model has no path
    to a money action even if something upstream tried to hand it one.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI_DIR = REPO / "spa_core" / "studio_os" / "mission_ui"
MC_PATH = REPO / "spa_core" / "studio_os" / "mission_control.py"
CT_PATH = REPO / "spa_core" / "studio_os" / "company_truth.py"
SERVER_PATH = REPO / "spa_core" / "studio_os" / "mission_server.py"

FORBIDDEN_TOKENS = ("act:", "/pause", "/resume", "kill", "set_status", "record_owner_answer")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── UI layer (current mission_ui/*, as it stands before WP2's redesign lands) ───────────────────
class TestUiNeverActs:
    def test_no_form_tags(self):
        html = _read(UI_DIR / "index.html")
        assert "<form" not in html.lower()

    def test_no_non_get_fetch_or_xhr(self):
        js = _read(UI_DIR / "app.js")
        assert "XMLHttpRequest" not in js
        for m in re.finditer(r"fetch\(([^)]*)\)", js, re.S):
            args = m.group(1)
            assert not re.search(r"method\s*:\s*['\"](?!GET)", args, re.I), m.group(0)

    def test_no_forbidden_action_tokens_as_literal_paths_or_verbs(self):
        """Forbidden as an ACTION — a quoted string literal that IS one of these tokens or a
        path built from one (``/pause``, ``act:x``) — not as a substring of an unrelated
        status-field name like ``kill_switch`` (a value this very UI must be able to DISPLAY)."""
        js = _read(UI_DIR / "app.js")
        html = _read(UI_DIR / "index.html")
        literals = re.findall(r'["\']([^"\']*)["\']', js) + re.findall(r'["\']([^"\']*)["\']', html)
        for tok in FORBIDDEN_TOKENS:
            bad = [lit for lit in literals if lit == tok or lit.startswith(tok) or f"/{tok}" in lit]
            assert not bad, (tok, bad)

    def test_every_anchor_href_is_hash_or_telegram(self):
        html = _read(UI_DIR / "index.html")
        js = _read(UI_DIR / "app.js")
        anchors = re.findall(r'<a\s[^>]*href\s*=\s*["\']([^"\']+)["\']', html, re.I)
        anchors += re.findall(r'\.href\s*=\s*["\']([^"\']+)["\']', js)
        for h in anchors:
            assert h.startswith("#") or h.startswith("https://t.me/"), h


# ── server layer — structural check only (socket behaviour lives in test_mission_server.py) ─────
class TestServerRefusesWrites:
    def test_every_write_verb_maps_to_the_one_refusal_handler(self):
        src = _read(SERVER_PATH)
        m = re.search(r"do_POST\s*=\s*do_PUT\s*=\s*do_PATCH\s*=\s*do_DELETE\s*=\s*(\w+)", src)
        assert m, "expected the four write verbs wired to one shared handler"
        handler = m.group(1)
        assert "405" in src[src.index(f"def {handler}"):src.index(f"def {handler}") + 400]

    def test_server_module_never_imports_execution_or_telegram_writers(self):
        tree = ast.parse(_read(SERVER_PATH))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
        assert not any(n.startswith("spa_core.execution") for n in names), names
        assert not any(n.startswith("spa_core.telegram") for n in names), names


# ── model layer ───────────────────────────────────────────────────────────────────────────────
def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
    return names


class TestModelHasNoPathToMoney:
    def test_company_truth_imports_neither_execution_nor_telegram(self):
        names = _imported_module_names(CT_PATH)
        assert not any(n.startswith("spa_core.execution") for n in names), names
        assert not any(n.startswith("spa_core.telegram") for n in names), names

    def test_company_truth_never_imports_a_kill_switch_writer(self):
        names = _imported_module_names(CT_PATH)
        assert not any("kill_switch" in n for n in names), names

    def test_company_truth_module_contains_no_write_open(self):
        src = _read(CT_PATH)
        assert re.search(r'open\([^)]*["\']w', src) is None
        assert "atomic_save" not in src

    def test_company_truth_exposes_no_write_function(self):
        """The read model exposes no write/command: every public function returns a dict/cell;
        none of them is named like a mutation."""
        tree = ast.parse(_read(CT_PATH))
        forbidden_prefixes = ("set_", "write_", "save_", "record_", "approve_", "execute_", "kill_", "pause_", "resume_")
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                assert not node.name.startswith(forbidden_prefixes), node.name

    def test_mission_control_itself_never_imports_execution(self):
        names = _imported_module_names(MC_PATH)
        assert not any(n.startswith("spa_core.execution") for n in names), names
