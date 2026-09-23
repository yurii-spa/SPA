"""spa_core/tests/test_forbidden_import_probe.py — контроль пробы приёмки
`forbidden_import_gate_single_instrument` (правило `.claude/rules/acceptance.md`, п. 3).

Проба обязана быть зелёной на ЦЕЛОМ контуре и красной на КАЖДОМ порванном
звене — с названным звеном. Здесь контур собирается в одноразовом дереве и
рвётся по одному звену за тест; живой репозиторий не трогается.

Звенья контура: прибор существует · прибор измеряет дерево · прибор кусается
на настоящем импорте · прибор молчит на ОБРАЗЦЕ кода в строке (авария 23.09) ·
прибор ПОЗВАН из ci-lite.yml · в workflow нет второй копии правила.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import os
import shutil
import sys

import pytest

from spa_core.monitoring import card_acceptance as ca

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROBE = "forbidden_import_gate_single_instrument"

_WORKFLOW_OK = """\
name: SPA CI-Lite
on: [workflow_dispatch]
jobs:
  syntax-and-import:
    steps:
      - name: Forbidden import check
        run: python3 scripts/lint_forbidden_imports.py
"""


@pytest.fixture()
def circuit(tmp_path, monkeypatch):
    """Одноразовая копия контура: прибор, база, workflow и пять доменов."""
    root = tmp_path / "tree"
    (root / "scripts").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    shutil.copy(os.path.join(_REPO, "scripts", "lint_forbidden_imports.py"),
                root / "scripts" / "lint_forbidden_imports.py")
    shutil.copy(os.path.join(_REPO, "scripts", "forbidden_import_baseline.json"),
                root / "scripts" / "forbidden_import_baseline.json")
    (root / ".github" / "workflows" / "ci-lite.yml").write_text(_WORKFLOW_OK, encoding="utf-8")
    sys.path.insert(0, os.path.join(_REPO, "scripts"))
    import lint_forbidden_imports as lfi
    for domain in lfi.DOMAINS:
        (root / domain).mkdir(parents=True, exist_ok=True)
        (root / domain / "_ok.py").write_text("import json\n", encoding="utf-8")
    monkeypatch.setattr(ca, "REPO_ROOT", str(root))
    return root


def _verdict(root=None):
    return ca.PROBES[_PROBE](None)


# ── контур цел ───────────────────────────────────────────────────────────────

def test_whole_circuit_is_satisfied(circuit):
    verdict, detail = _verdict()
    assert verdict == ca.SATISFIED, detail
    assert "замкнут" in detail


def test_probe_is_registered_and_declarable():
    assert _PROBE in ca.PROBES
    assert ca.validate_spec(_PROBE) is None


def test_probe_refuses_an_argument_out_loud(circuit):
    verdict, detail = ca.PROBES[_PROBE]("что-нибудь")
    assert verdict == ca.UNMEASURED and "аргумента" in detail


# ── каждое звено порвано по одному ──────────────────────────────────────────

def test_missing_instrument_is_unmeasured_not_satisfied(circuit):
    os.remove(circuit / "scripts" / "lint_forbidden_imports.py")
    verdict, detail = _verdict()
    assert verdict == ca.UNMEASURED, detail
    assert "нет в дереве" in detail


def test_instrument_that_never_bites_is_named(circuit):
    (circuit / "scripts" / "lint_forbidden_imports.py").write_text(
        "import sys\nprint('{}')\nsys.exit(0)\n", encoding="utf-8")
    verdict, detail = _verdict()
    assert verdict == ca.NOT_SATISFIED, detail
    assert "НЕ КУСАЕТСЯ" in detail


def test_instrument_that_reddens_on_a_sample_string_is_named(circuit):
    """Подстрочный прибор — ровно тот, что краснил CI-Lite с 07.09."""
    (circuit / "scripts" / "lint_forbidden_imports.py").write_text(
        "import argparse, os, sys\n"
        "p = argparse.ArgumentParser(); p.add_argument('--root', default='.')\n"
        "p.add_argument('--json', action='store_true'); a = p.parse_args()\n"
        "hits = []\n"
        "for r, d, fs in os.walk(a.root):\n"
        "    for f in fs:\n"
        "        if f.endswith('.py') and 'import anthropic' in open(os.path.join(r, f)).read():\n"
        "            hits.append(f)\n"
        "print('{}')\n"
        "sys.exit(1 if hits else 0)\n", encoding="utf-8")
    verdict, detail = _verdict()
    assert verdict == ca.NOT_SATISFIED, detail
    assert "ОБРАЗЦЕ" in detail


def test_instrument_that_cannot_measure_the_tree_is_named(circuit):
    (circuit / "scripts" / "lint_forbidden_imports.py").write_text(
        "import sys\nprint('НЕ ИЗМЕРЕНО: нечем')\nsys.exit(2)\n", encoding="utf-8")
    verdict, detail = _verdict()
    assert verdict == ca.NOT_SATISFIED, detail
    assert "НЕ ИЗМЕРИЛ" in detail


def test_instrument_nobody_calls_is_named(circuit):
    (circuit / ".github" / "workflows" / "ci-lite.yml").write_text(
        "name: SPA CI-Lite\njobs:\n  x:\n    steps:\n      - run: echo hi\n", encoding="utf-8")
    verdict, detail = _verdict()
    assert verdict == ca.NOT_SATISFIED, detail
    assert "не зовёт" in detail


def test_second_copy_of_the_rule_in_the_workflow_is_named(circuit):
    (circuit / ".github" / "workflows" / "ci-lite.yml").write_text(
        _WORKFLOW_OK + "      - run: python3 -c \"FORBIDDEN_LIBS = ['anthropic']\"\n",
        encoding="utf-8")
    verdict, detail = _verdict()
    assert verdict == ca.NOT_SATISFIED, detail
    assert "копия правила" in detail


def test_unreadable_workflow_is_unmeasured(circuit):
    os.remove(circuit / ".github" / "workflows" / "ci-lite.yml")
    verdict, detail = _verdict()
    assert verdict == ca.UNMEASURED, detail
    assert "зовущий НЕ ИЗМЕРЕН" in detail


# ── проба не проходит подстрокой (ADR-333) ──────────────────────────────────

def test_verdict_does_not_come_from_the_word_being_present(circuit):
    """Файл, в котором написано имя прибора и слово PASSED, вердикта не даёт."""
    (circuit / "spa_core" / "risk" / "decoy.py").write_text(
        "# python3 scripts/lint_forbidden_imports.py -> Forbidden import check PASSED\n",
        encoding="utf-8")
    (circuit / "scripts" / "lint_forbidden_imports.py").write_text(
        "import sys\nprint('{}')\nsys.exit(0)\n", encoding="utf-8")
    verdict, _ = _verdict()
    assert verdict == ca.NOT_SATISFIED
