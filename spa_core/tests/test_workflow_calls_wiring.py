"""Исполняемый вызов в GitHub Actions — проводка; упоминание имени в YAML — нет.

# LLM_FORBIDDEN

Решение ARB 23.10 (STUDIO-OS-NEXT-01, этап 8). Положительный контроль — настоящий
запуск; отрицательные — каждая форма, в которой имя модуля встречается в workflow,
но вызова нет: комментарий, `name:`/`description`, `echo`, путь к тесту, похожее
имя другого модуля, отключённый шаг/джоба, `uses:`/`with:`. Непонятное (`python -c`,
heredoc, чужая оболочка) не засчитывается и называется в `unclear`.
"""
from __future__ import annotations

import pathlib
import textwrap

import pytest

from spa_core.tests import _workflow_calls as wc
from spa_core.tests import test_unwired_guard_modules_ratchet as ratchet

MOD = "spa_core/monitoring/zzz_guard.py"
DOTTED = "spa_core.monitoring.zzz_guard"


def _scene(tmp_path: pathlib.Path, body: str, name: str = "w.yml") -> pathlib.Path:
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def _wf(steps: str, job_extra: str = "", head: str = "on:\n  push:\n") -> str:
    return (head + "jobs:\n  j:\n    runs-on: ubuntu-latest\n" + job_extra
            + "    steps:\n" + textwrap.indent(textwrap.dedent(steps), "      "))


def _invoked(root: pathlib.Path) -> dict:
    return wc.invoked_modules(root, {MOD, "spa_core/alerts/zzz_guard.py"})


# ---------------------------------------------------------------- положительные

def test_a_real_module_run_is_wiring(tmp_path):
    root = _scene(tmp_path, _wf(f"""\
        - name: Run
          run: |
            mkdir -p out
            set +e
            SPA_ENV=ci python -m {DOTTED} \\
              --out out/x.json | tee out/report.txt
            code=${{PIPESTATUS[0]}}
        """))
    calls = _invoked(root)[MOD]
    assert [(c.kind, c.target, c.conditional) for c in calls] == [("module", DOTTED, False)]


def test_a_script_path_run_is_wiring(tmp_path):
    root = _scene(tmp_path, _wf(f"""\
        - run: python3 ./{MOD} --check && echo done
        """))
    assert [c.kind for c in _invoked(root)[MOD]] == ["script"]


def test_a_conditional_step_still_runs(tmp_path):
    root = _scene(tmp_path, _wf(f"""\
        - if: ${{{{ always() }}}}
          run: python -m {DOTTED}
        """))
    assert [c.conditional for c in _invoked(root)[MOD]] == [True]


def test_the_real_census_workflow_wires_the_census_module():
    root = ratchet._ROOT
    rel = "spa_core/monitoring/live_registry_scene_census.py"
    calls = wc.invoked_modules(root, {rel}).get(rel, [])
    assert [c.workflow for c in calls] == [".github/workflows/live-registry-census.yml"]
    assert rel in ratchet._census_by_name(), "по имени модуль по-прежнему сирота — предмет теста"
    assert rel not in ratchet._census()


# ---------------------------------------------------------------- отрицательные

NEGATIVES = {
    "yaml_comment": _wf(f"""\
        # python -m {DOTTED}
        - run: echo hi
        """),
    "step_name": _wf(f"""\
        - name: python -m {DOTTED}
          run: echo hi
        """),
    "input_description": "on:\n  workflow_dispatch:\n    inputs:\n      x:\n"
                         f"        description: \"python -m {DOTTED}\"\n"
                         "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n",
    "echo_quoted": _wf(f"""\
        - run: echo "python -m {DOTTED}"
        """),
    "echo_bare": _wf(f"""\
        - run: echo python -m {DOTTED} > log.txt
        """),
    "shell_comment": _wf(f"""\
        - run: |
            ls  # python -m {DOTTED}
            # python3 {MOD}
        """),
    "path_as_argument_of_another_command": _wf(f"""\
        - run: ls -la {MOD} && git diff -- {MOD} && pytest -m {DOTTED}
        """),
    "test_path": _wf("""\
        - run: python -m pytest spa_core/tests/test_zzz_guard.py -q
        """),
    "test_path_as_script": _wf("""\
        - run: python spa_core/tests/test_zzz_guard.py
        """),
    "similar_name": _wf(f"""\
        - run: python -m {DOTTED}_v2 && python3 spa_core/monitoring/zzz_guard_v2.py
        """),
    "step_if_false": _wf(f"""\
        - if: false
          run: python -m {DOTTED}
        """),
    "step_if_false_expr": _wf(f"""\
        - if: ${{{{ false }}}}
          run: python -m {DOTTED}
        """),
    "job_if_false": _wf(f"""\
        - run: python -m {DOTTED}
        """, job_extra="    if: false\n"),
    "uses_with": _wf(f"""\
        - uses: some/action@v1
          with:
            args: python -m {DOTTED}
        """),
    "no_trigger": _wf(f"""\
        - run: python -m {DOTTED}
        """, head=""),
}


@pytest.mark.parametrize("case", sorted(NEGATIVES))
def test_a_mention_is_not_wiring(tmp_path, case):
    root = _scene(tmp_path, NEGATIVES[case])
    assert MOD not in _invoked(root), f"{case}: упоминание засчитано вызовом"


def test_another_package_with_the_same_stem_is_not_this_module(tmp_path):
    root = _scene(tmp_path, _wf("""\
        - run: python -m spa_core.alerts.zzz_guard
        """))
    got = _invoked(root)
    assert MOD not in got and "spa_core/alerts/zzz_guard.py" in got


# ---------------------------------------------------------------- неясное: не засчитано и названо

UNCLEAR = {
    "python_c": (_wf(f"""\
        - run: |
            python3 -c "
            import {DOTTED}
            "
        """), "python -c"),
    "heredoc": (_wf(f"""\
        - run: |
            cat <<'EOF' > s.sh
            python -m {DOTTED}
            EOF
        """), "heredoc"),
    "foreign_shell": (_wf(f"""\
        - shell: pwsh
          run: python -m {DOTTED}
        """), "оболочка"),
    "unclosed_quote": (_wf(f"""\
        - run: |
            python -m {DOTTED} "oops
        """), "незакрытая кавычка"),
}


@pytest.mark.parametrize("case", sorted(UNCLEAR))
def test_an_unclear_form_is_not_counted_and_is_named(tmp_path, case):
    body, reason = UNCLEAR[case]
    root = _scene(tmp_path, body)
    assert MOD not in _invoked(root), f"{case}: неясное засчитано вызовом молча"
    named = wc.unclear_mentions(root, "zzz_guard")
    assert any(reason in u.reason for u in named), (case, named)


def test_unreadable_yaml_is_named_not_silent(tmp_path):
    root = _scene(tmp_path, "on: [push\njobs: {\n")
    calls, unclear = wc.scan_workflows(root)
    assert calls == [] and [u.reason.split(":")[0] for u in unclear] == ["YAML не прочитан"]


def test_every_real_workflow_is_read():
    """Нечитаемый workflow молча снял бы свои вызовы с учёта — это не «сирота», а не измерено."""
    _, unclear = wc.scan_workflows(ratchet._ROOT)
    assert not [u for u in unclear if u.reason.startswith("YAML")], unclear


def test_the_name_search_still_does_not_read_github():
    """Имя в YAML не проводка: поиск по имени `.github/` не читает (вызов — только через разбор шагов)."""
    assert not [p for p in ratchet._tree_texts() if p.startswith(".github")]


# ---------------------------------------------------------------- такт изолированного census

_CENSUS_WF = ratchet._ROOT / ".github" / "workflows" / "live-registry-census.yml"
_BOOKKEEPING = ["docs/evidence/**", "docs/journal/**", "docs/STATE.md", "docs/ROADMAP.md"]


def _census_triggers() -> dict:
    import yaml  # noqa: PLC0415 — тест-домен
    doc = yaml.safe_load(_CENSUS_WF.read_text(encoding="utf-8"))
    return doc.get("on", doc.get(True))


def test_census_push_trigger_skips_only_bookkeeping_docs():
    """Решение ARB 23.10: docs-only сохранение evidence/хендовера census не перезапускает,
    а всё остальное — запускает (ignore не шире учётных документов)."""
    push = _census_triggers()["push"]
    assert push["branches"] == ["integ/studio-os-next-01-stab"]
    assert push["paths-ignore"] == _BOOKKEEPING
    assert "paths" not in push, "положительный список путей молча пропустил бы вход замера"


def test_census_keeps_an_explicit_control_run_and_has_no_schedule():
    on = _census_triggers()
    assert "workflow_dispatch" in on and "sha" in on["workflow_dispatch"]["inputs"]
    assert "schedule" not in on and "pull_request" not in on


@pytest.mark.parametrize("path,runs", [
    ("docs/evidence/x/HANDOVER.md", False),
    ("docs/journal/2026-W43.md", False),
    ("docs/STATE.md", False),
    ("docs/ROADMAP.md", False),
    ("docs/decisions/ADR-1.md", True),
    ("docs/SYSTEM_MAP.md", True),
    ("spa_core/monitoring/card_acceptance.py", True),
    ("spa_core/tests/test_x.py", True),
    (".github/workflows/live-registry-census.yml", True),
    ("architecture/manifest.json", True),
    ("data/x.json", True),
])
def test_census_path_filter_by_glob_semantics(path, runs):
    """Сверка смысла фильтра на путях: `**` — любая глубина, `*` — без `/` (как у Actions)."""
    import re  # noqa: PLC0415

    def rx(glob):
        return re.compile("^" + re.escape(glob).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$")
    ignored = any(rx(g).match(path) for g in _census_triggers()["push"]["paths-ignore"])
    assert (not ignored) is runs
