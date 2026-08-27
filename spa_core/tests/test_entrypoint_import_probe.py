"""Способна ли точка входа агента импортироваться ТАК, КАК ЕЁ ЗАПУСКАЕТ launchd.

Каждый тест — положительный контроль по аварии 2026-08-26 либо по ошибке, которую
эта проверка успела совершить в тот же день и которую поймал замер, а не рассуждение:

* `com.spa.source_discovery` падал КАЖДЫЙ запуск на `ModuleNotFoundError: No module
  named 'spa_core'`, а `deployment_acceptance` отвечал «85 entrypoints executable,
  6 modules import» — по букве верно, по существу мимо;
* пер-агентный `agent_static_probe.sh` на том же скрипте сказал `✅ STATIC PROBE
  PASSED`: скриптовой цели он даёт только `py_compile`, то есть проверку синтаксиса;
* ПЕРВАЯ версия этой пробы (список импортов, вырванный из порядка исполнения)
  объявила мёртвым живой `com.spa.strategy_lab_paper` — тот чинит `sys.path` строкой
  ВЫШЕ импорта. Тесты 3 и 4 держат обе стороны: и находку, и ложную тревогу;
* режим «запусти обёртку с флагом только-проверь» снят в тот же заход: обёртка
  `exec`ает шаблон БОЕВОГО дерева, и пока флаг туда не доехал, она запускает
  НАСТОЯЩЕГО АГЕНТА — измерено, шесть агентов отработали за 86.6 с.

Офлайн и герметично: скрипты, обёртки и plist'ы строятся в `tmp_path`, живой флот
не затрагивается. Времени в фикстурах нет — датам тут нечего судить.
"""
from __future__ import annotations

import os
import plistlib
import stat
import sys
from pathlib import Path

import pytest

from spa_core.monitoring.deployment_acceptance import (
    CRITICAL,
    OK,
    WARNING,
    check_entrypoint_imports,
    run_acceptance,
)
from spa_core.monitoring.entrypoint_import_probe import (
    FAILED,
    OK as PROBE_OK,
    UNCHECKED,
    has_main_guard,
    invokes_template,
    probe_module,
    probe_script,
    probe_wrapper,
    resolve_wrapper_target,
    strip_comments,
)

_TEMPLATE = Path(__file__).resolve().parents[2] / "scripts" / "agent_template.sh"


# ---------------------------------------------------------------------------
# фикстуры: дерево «как у нас» — пакет в корне, точка входа в подкаталоге scripts/
# ---------------------------------------------------------------------------

def _tree(tmp_path: Path) -> tuple:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    return root, scripts


def _script(scripts: Path, name: str, body: str) -> Path:
    p = scripts / name
    p.write_text(body, encoding="utf-8")
    return p


_PLAIN = (
    "import json\n"
    "from pkg import VALUE\n"
    "\n"
    "def main():\n"
    "    return VALUE\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    raise SystemExit(main())\n"
)

_SELF_FIXING = (
    "import sys\n"
    "from pathlib import Path\n"
    "_ROOT = Path(__file__).resolve().parents[1]\n"
    "if str(_ROOT) not in sys.path:\n"
    "    sys.path.insert(0, str(_ROOT))\n"
    "from pkg import VALUE\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    print(VALUE)\n"
)

_TRY_GUARDED = (
    "try:\n"
    "    from pkg import VALUE\n"
    "except ImportError:\n"
    "    VALUE = 0\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    print(VALUE)\n"
)


def _wrapper(scripts: Path, name: str, *, mode: str, target: str,
             pythonpath: str = "", repo_root: str = "") -> Path:
    """Обёртка агента в одном из двух настоящих режимов шаблона."""
    head = "#!/bin/bash\n"
    if pythonpath:
        head += 'export PYTHONPATH="{}${{PYTHONPATH:+:$PYTHONPATH}}"\n'.format(pythonpath)
    if mode == "A":
        body = (head
                + 'AGENT_NAME="probe"\n'
                + 'RUN_SCRIPT="{}"\n'.format(target)
                + 'exec /bin/bash {}\n'.format(_TEMPLATE))
    else:
        body = head + 'exec /bin/bash {} probe {}\n'.format(_TEMPLATE, target)
    p = scripts / name
    p.write_text(body, encoding="utf-8")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
    return p


def _plist(agents: Path, label: str, entry: Path) -> Path:
    agents.mkdir(exist_ok=True)
    p = agents / "{}.plist".format(label)
    p.write_bytes(plistlib.dumps({"Label": label,
                                  "ProgramArguments": ["/bin/bash", str(entry)]}))
    return p


# ---------------------------------------------------------------------------
# 1–2. САМА АВАРИЯ 2026-08-26 и её починка — обе стороны
# ---------------------------------------------------------------------------

def test_script_target_cannot_import_the_package_2026_08_26(tmp_path):
    """launchd зовёт скрипт ПО ПУТИ ⇒ `sys.path[0]` — каталог скрипта, не корень."""
    root, scripts = _tree(tmp_path)
    s = _script(scripts, "entry.py", _PLAIN)
    res = probe_script(str(s), env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    assert res["status"] == FAILED, res
    assert "ModuleNotFoundError" in res["failures"][0]["error"]


def test_exported_pythonpath_is_what_makes_it_green(tmp_path):
    """Обратная сторона: ровно та строка, которой чинили source_discovery."""
    root, scripts = _tree(tmp_path)
    s = _script(scripts, "entry.py", _PLAIN)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    assert probe_script(str(s), env=env)["status"] == PROBE_OK


# ---------------------------------------------------------------------------
# 3–4. ЛОЖНАЯ ТРЕВОГА, которую первая модель выдала на живом агенте
# ---------------------------------------------------------------------------

def test_script_that_fixes_its_own_syspath_is_not_a_finding(tmp_path):
    """`sys.path.insert` СТРОКОЙ ВЫШЕ импорта — так живёт strategy_lab_paper.

    Первая модель собирала импорты разбором и пробовала их вне порядка исполнения:
    починки она не видела и объявляла мёртвым агента с exit 0.
    """
    root, scripts = _tree(tmp_path)
    s = _script(scripts, "entry.py", _SELF_FIXING)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    assert probe_script(str(s), env=env)["status"] == PROBE_OK


def test_try_guarded_import_is_not_a_finding(tmp_path):
    """`site_freshness_monitor.py` грузит зависимость по пути внутри try — исправен."""
    root, scripts = _tree(tmp_path)
    (root / "pkg").rename(root / "pkg_hidden")           # пакета на пути НЕТ вовсе
    s = _script(scripts, "entry.py", _TRY_GUARDED)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    assert probe_script(str(s), env=env)["status"] == PROBE_OK


# ---------------------------------------------------------------------------
# 5–6. Проба НЕ ИМЕЕТ ПРАВА исполнить агента
# ---------------------------------------------------------------------------

def test_main_block_is_never_executed(tmp_path):
    """Загрузить — да; запустить — нет. Метка из `__main__` не должна появиться."""
    root, scripts = _tree(tmp_path)
    mark = tmp_path / "MAIN_RAN"
    s = _script(scripts, "entry.py",
                "import sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
                "from pkg import VALUE\n"
                "\n"
                'if __name__ == "__main__":\n'
                '    Path(r"{}").write_text("ran")\n'.format(mark))
    assert probe_script(str(s))["status"] == PROBE_OK
    assert not mark.exists(), "проба ЗАПУСТИЛА агента — этого делать нельзя"


def test_script_without_main_guard_is_refused_not_run(tmp_path):
    """Нет заслона ⇒ верхний уровень И ЕСТЬ работа ⇒ ОТКАЗ, а не запуск."""
    root, scripts = _tree(tmp_path)
    mark = tmp_path / "TOPLEVEL_RAN"
    s = _script(scripts, "entry.py",
                "from pathlib import Path\n"
                'Path(r"{}").write_text("ran")\n'.format(mark))
    res = probe_script(str(s))
    assert res["status"] == UNCHECKED
    assert "__main__" in res["reason"]
    assert not mark.exists()


def test_has_main_guard_reads_the_top_level_only():
    assert has_main_guard('if __name__ == "__main__":\n    pass\n')
    assert not has_main_guard("def f():\n    pass\n")


# ---------------------------------------------------------------------------
# 7–9. Разбор обёртки: оба режима шаблона, и никаких примеров из комментариев
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["A", "B"])
def test_both_wrapper_modes_resolve_the_same_target(tmp_path, mode):
    root, scripts = _tree(tmp_path)
    s = _script(scripts, "entry.py", _PLAIN)
    w = _wrapper(scripts, "agent_probe.sh", mode=mode, target=str(s))
    info = resolve_wrapper_target(str(w), default_repo_root=str(root))
    assert (info["kind"], info["target"]) == ("script", str(s)), info


def test_comment_examples_are_not_taken_for_the_target(tmp_path):
    """Шапки наших обёрток полны примеров. `agent_aggressive_lab.sh` из-за этого
    «запускал» цель с именем `bash-wrapper`, вычитанную из фразы в комментарии."""
    root, scripts = _tree(tmp_path)
    w = scripts / "agent_probe.sh"
    w.write_text("#!/bin/bash\n"
                 '# пример: RUN_SCRIPT="/abs/example.py", позови agent_template.sh bash-wrapper\n'
                 '# MODULE="pkg.example"\n'
                 'export MODULE="pkg.real"\n'
                 'exec /bin/bash {}\n'.format(_TEMPLATE), encoding="utf-8")
    info = resolve_wrapper_target(str(w), default_repo_root=str(root))
    assert (info["kind"], info["target"]) == ("module", "pkg.real"), info
    assert "#" not in strip_comments("# a\nb\n")


def test_wrapper_that_is_its_own_script_is_structural_not_a_failure(tmp_path):
    """Дневной цикл, автопуш, бэкап — сценарии, а не агенты с одной целью.

    Такое «не проверено» обязано быть НАЗВАНО и НЕ красить вердикт: сторож, который
    не может стать зелёным ни при каком значении, перестают читать.
    """
    root, scripts = _tree(tmp_path)
    w = scripts / "agent_own.sh"
    w.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    res = probe_wrapper(str(w), default_repo_root=str(root))
    assert res["status"] == UNCHECKED
    assert res["structural"] is True


def test_wrapper_pythonpath_reaches_the_probe(tmp_path):
    """Обе стороны на ОДНОЙ обёртке: строка export решает вердикт."""
    root, scripts = _tree(tmp_path)
    s = _script(scripts, "entry.py", _PLAIN)
    broken = _wrapper(scripts, "agent_broken.sh", mode="A", target=str(s))
    fixed = _wrapper(scripts, "agent_fixed.sh", mode="A", target=str(s),
                     pythonpath=str(root))
    assert probe_wrapper(str(broken), default_repo_root=str(root))["status"] == FAILED
    assert probe_wrapper(str(fixed), default_repo_root=str(root))["status"] == PROBE_OK


def test_probe_does_not_inherit_our_own_pythonpath(tmp_path, monkeypatch):
    """Иначе проба чинит то, что в проде не починено, и тихо зеленеет на сломанном."""
    root, scripts = _tree(tmp_path)
    s = _script(scripts, "entry.py", _PLAIN)
    w = _wrapper(scripts, "agent_broken.sh", mode="A", target=str(s))
    monkeypatch.setenv("PYTHONPATH", str(root))
    assert probe_wrapper(str(w), default_repo_root=str(root))["status"] == FAILED


# ---------------------------------------------------------------------------
# 10–13. Вердикт приёмки
# ---------------------------------------------------------------------------

def _acceptance(tmp_path, agents, root):
    """Приёмка про ФИКСТУРНЫЙ флот. Артефакты кладутся свежими намеренно: предмет
    этих тестов — цели агентов, и вердикт обязан держаться на них, а не на возрасте
    пустой папки (`artifacts={}` не годится — пустой словарь падает на умолчание)."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    for name in ("current_positions.json", "adapter_status.json", "agent_health.json"):
        (data / name).write_text("{}", encoding="utf-8")
    return run_acceptance(agent_dir=agents, data_dir=data,
                          repo_root=root, modules=(), write=False)


def test_acceptance_now_turns_the_dead_agent_CRITICAL(tmp_path):
    """ТОТ САМЫЙ вердикт, которого не было 2026-08-26."""
    root, scripts = _tree(tmp_path)
    s = _script(scripts, "entry.py", _PLAIN)
    w = _wrapper(scripts, "agent_dead.sh", mode="A", target=str(s))
    agents = tmp_path / "agents"
    _plist(agents, "com.spa.dead", w)
    doc = _acceptance(tmp_path, agents, root)
    assert doc["status"] == CRITICAL, doc["reasons"]
    assert [p["label"] for p in doc["entrypoint_imports_failed"]] == ["com.spa.dead"]
    assert doc["entrypoints_broken"] == [], "обёртка исполняема — старая проверка молчала"


def test_acceptance_is_OK_when_the_target_imports(tmp_path):
    root, scripts = _tree(tmp_path)
    s = _script(scripts, "entry.py", _PLAIN)
    w = _wrapper(scripts, "agent_ok.sh", mode="A", target=str(s), pythonpath=str(root))
    agents = tmp_path / "agents"
    _plist(agents, "com.spa.ok", w)
    doc = _acceptance(tmp_path, agents, root)
    assert doc["status"] == OK, doc["reasons"]
    assert doc["entrypoint_imports_ok"] == 1


def test_structural_blindness_alone_does_not_redden_the_verdict(tmp_path):
    root, scripts = _tree(tmp_path)
    w = scripts / "agent_own.sh"
    w.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    os.chmod(w, os.stat(w).st_mode | stat.S_IXUSR)
    agents = tmp_path / "agents"
    _plist(agents, "com.spa.script", w)
    doc = _acceptance(tmp_path, agents, root)
    assert doc["status"] == OK, doc["reasons"]
    assert len(doc["entrypoint_imports_structural"]) == 1
    assert any("НАЗВАНО" in r for r in doc["reasons"]), "слепота обязана быть названа"


def test_probe_that_crashes_is_unchecked_not_a_pass(tmp_path):
    """Fail-CLOSED: упавшая проба — находка, а не тихий зачёт."""
    root, scripts = _tree(tmp_path)
    w = _wrapper(scripts, "agent_x.sh", mode="A", target=str(scripts / "entry.py"))
    agents = tmp_path / "agents"
    _plist(agents, "com.spa.x", w)

    def boom(_wrapper_path):
        raise RuntimeError("проба сломалась")

    got = check_entrypoint_imports(agents, repo_root=root, prober=boom)
    assert [g["status"] for g in got] == [UNCHECKED]
    assert got[0]["structural"] is False, "не структурная слепота — это находка"
    assert "проба сама упала" in got[0]["reason"]


def test_module_target_is_probed_from_the_repo_root(tmp_path):
    """`python -m` кладёт в путь РАБОЧИЙ каталог — обёртка делает туда `cd`."""
    root, scripts = _tree(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    assert probe_module("pkg", cwd=str(root), env=env)["status"] == PROBE_OK
    assert probe_module("pkg", cwd=str(scripts), env=env)["status"] == FAILED


# ---------------------------------------------------------------------------
# 14. Храповик слепоты: обёртки НАШЕГО репозитория обязаны разбираться
# ---------------------------------------------------------------------------

def test_every_delegating_wrapper_in_this_repo_resolves_a_target():
    """Судит РЕПОЗИТОРИЙ, а не хост: в CI живого флота нет, а обёртки есть.

    Смысл: если завтра кто-то напишет обёртку, делегирующую шаблону, но названную
    так, что разбор её не поймёт, — слепота появится молча. Здесь она краснеет.
    """
    repo = Path(__file__).resolve().parents[2]
    unresolved = []
    for w in sorted((repo / "scripts").glob("agent_*.sh")):
        if w.name == "agent_template.sh":
            continue
        src = w.read_text(encoding="utf-8", errors="replace")
        if not invokes_template(src):
            continue          # собственный сценарий или инструмент — не обёртка агента
        info = resolve_wrapper_target(str(w), default_repo_root=str(repo))
        if not info["kind"]:
            unresolved.append((w.name, info["reason"]))
    assert not unresolved, "обёртки делегируют шаблону, но цель не разобрана: {}".format(unresolved)
