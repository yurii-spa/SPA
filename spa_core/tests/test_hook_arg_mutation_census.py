"""Батарея прибора `scripts/hook_arg_mutation_census.py` (ADR-1037).

Предмет — класс, найденный жертвой в ADR-1036: НАША реализация хука трогает поле
объекта-аргумента, а идущая ПОЗЖЕ чужая реализация ТОГО ЖЕ хука это поле
ПРИСВАИВАЕТ, то есть наша работа обнуляется молча. Цена класса измерена дважды
одним обмороком сессии (17.10 прогон 39003158532, шард 2, 4320 тестов без исхода;
16.11 прогон 43933147333, шард 7).

**Каждый тест здесь — контроль на ОДНО звено**, и у утверждений, на которых стоит
прибор, есть положительный контроль:

* порядок зова (`reversed(get_hookimpls())`) СВЕРЯЕТСЯ с настоящим порядком вызова
  на живом pytest — это не принятое на веру чтение pluggy;
* форма класса ловится БОМБОЙ (иначе «членов N» неотличимо от «прибор слеп»);
* «после `yield` обёртка видит окончательное состояние» проверено ПАРОЙ сцен с
  ПРОТИВОПОЛОЖНЫМИ ответами на одном и том же поле;
* третий исход (инв. #17) проверен отдельно для каждого источника «НЕ ИЗМЕРЕНО».

Сцены — одноразовые деревья в `tmp_path`; дерево доставки не трогается ничем
(`.claude/rules/deployment.md` § «БАЙТЫ, КОТОРЫЕ НЕ ЯВЛЯЮТСЯ КОДОМ» п. 1).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _REPO_ROOT / "scripts" / "hook_arg_mutation_census.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("spa_hook_arg_census", _TOOL)
    assert spec and spec.loader, _TOOL
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TOOL = _load_tool()


def _scene(tmp_path: Path, plugins: dict, test_body: str = "def test_one():\n    assert True\n") -> Path:
    """Одноразовое дерево-сцена: маркер корня, плагины, один тест."""
    root = tmp_path / "scene"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / ".keep").write_text("", encoding="utf-8")
    for name, source in plugins.items():
        (root / f"{name}.py").write_text(source, encoding="utf-8")
    (root / "test_scene.py").write_text(test_body, encoding="utf-8")
    return root


def _run_census(root: Path, plugins) -> dict:
    return TOOL.census(root, (), ("test_scene.py",), tuple(plugins))


# ─────────── звено 1: ПОРЯДОК ЗОВА измерен, а не выведен из чтения ───────────

ORDER_RECORDER = '''\
import json, os

NAME = "{name}"


def pytest_sessionstart(session):
    path = os.environ["SPA_SCENE_ORDER"]
    actual = []
    if os.path.exists(path):
        actual = json.load(open(path)).get("actual", [])
    actual.append(NAME)
    caller = session.config.pluginmanager.hook.pytest_sessionstart
    predicted = [str(i.plugin_name) for i in reversed(caller.get_hookimpls())]
    json.dump({{"actual": actual, "predicted": predicted}}, open(path, "w"))
'''


def test_call_order_claim_has_a_positive_control(tmp_path):
    """`reversed(get_hookimpls())` ЕСТЬ настоящий порядок вызова — проверено живым pytest.

    Контроль на звено: поменяйте в наблюдателе `reversed(...)` на прямой обход —
    предсказание разойдётся с наблюдённым порядком, и этот тест покраснеет.
    Без него весь прибор стоял бы на чтении исходника pluggy, а не на замере.
    """
    root = _scene(tmp_path, {
        "order_a": ORDER_RECORDER.format(name="order_a"),
        "order_b": ORDER_RECORDER.format(name="order_b"),
    })
    out = tmp_path / "order.json"
    env = {**os.environ, "SPA_SCENE_ORDER": str(out), "PYTHONHASHSEED": "0"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:randomly",
         "-p", "order_a", "-p", "order_b", "test_scene.py"],
        cwd=str(root), env=env, text=True, capture_output=True, timeout=600)
    assert out.exists(), (
        "сцена не записала порядок — предпосылка НЕ ОБЕСПЕЧЕНА, судить о порядке нечем: "
        f"код {proc.returncode}, вывод {proc.stdout[-500:]!r} / {proc.stderr[-500:]!r}")
    data = json.loads(out.read_text(encoding="utf-8"))
    ours = [n for n in data["predicted"] if n in {"order_a", "order_b"}]
    assert data["actual"] == ours, (
        "предсказанный порядок зова разошёлся с НАБЛЮДЁННЫМ: "
        f"наблюдали {data['actual']}, предсказали {ours}")


# ─────────── звено 2: форма класса ловится БОМБОЙ ───────────

BOMB = '''\
def pytest_sessionstart(session):
    # читает поле, которое ПОЗЖЕ присваивает встроенный `runner`
    return getattr(session, "_setupstate", None)
'''

QUIET = '''\
def pytest_sessionstart(session):
    # трогает поле, которого никто позже не присваивает
    return session.startpath
'''


def test_a_bomb_in_the_shape_is_named(tmp_path):
    """Бомба обязана быть НАЗВАНА: без неё «членов N» неотличимо от «прибор слеп».

    Поле выбрано не из головы: при первом прогоне бомба, читавшая
    `session._setupstate` БЕЗ `getattr`, уронила сессию `AttributeError` — то есть
    замена этого поля встроенным `runner` ПОЗЖЕ нашего хука подтверждена живым
    отказом, а не только разбором AST.
    """
    root = _scene(tmp_path, {"bomb_plugin": BOMB, "quiet_plugin": QUIET})
    result = _run_census(root, ("bomb_plugin", "quiet_plugin"))
    assert result["verdict"] == "measured", result.get("reasons")
    keys = [m["key"] for m in result["members"]]
    assert any(k.startswith("bomb_plugin.py::pytest_sessionstart") for k in keys), (
        f"бомба в форме класса НЕ НАЗВАНА — прибор слеп: {keys}")
    paths = [p for m in result["members"] for p in m["paths"]]
    assert "session._setupstate" in paths, paths


def test_a_plugin_outside_the_shape_is_not_a_member(tmp_path):
    """Отрицательный контроль той же сцены: прибор не красит всё, что трогает аргумент."""
    root = _scene(tmp_path, {"bomb_plugin": BOMB, "quiet_plugin": QUIET})
    result = _run_census(root, ("bomb_plugin", "quiet_plugin"))
    keys = [m["key"] for m in result["members"]]
    assert not any(k.startswith("quiet_plugin.py") for k in keys), (
        f"тихий плагин назван членом класса — предикат шире предмета: {keys}")
    quiet_rows = [r for r in result["rows"] if r["ours"] == "quiet_plugin.py"]
    assert quiet_rows and quiet_rows[0]["touches"] == ["session.startpath"], quiet_rows


# ─────────── звено 3: «до yield» против «после yield» ───────────

WRAP_BEFORE = '''\
import pytest


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    seen = getattr(call, "excinfo", None)      # ДО yield — объект ещё заменят
    assert seen is None or seen is not None
    return (yield)
'''

WRAP_AFTER = '''\
import pytest


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    report = yield
    seen = getattr(call, "excinfo", None)      # ПОСЛЕ yield — состояние окончательное
    assert seen is None or seen is not None
    return report
'''


def test_touch_before_yield_is_a_member_and_after_yield_is_not(tmp_path):
    """Пара сцен с ПРОТИВОПОЛОЖНЫМИ ответами на ОДНОМ поле — это и есть предмет ADR-1036.

    Обе сцены трогают `call.excinfo` у `pytest_runtest_makereport`, который ПОЗЖЕ
    присваивает встроенный ПЛОСКИЙ `_pytest/unittest.py`. Разница ровно в том, по
    какую сторону `yield` стоит чтение. Контроль на звено: уберите из прибора
    отсечку по строке `yield` — вторая половина теста покраснеет.
    """
    before = _scene(tmp_path / "b", {"wrap_before": WRAP_BEFORE})
    after = _scene(tmp_path / "a", {"wrap_after": WRAP_AFTER})
    got_before = _run_census(before, ("wrap_before",))
    got_after = _run_census(after, ("wrap_after",))
    assert got_before["verdict"] == "measured", got_before.get("reasons")
    assert got_after["verdict"] == "measured", got_after.get("reasons")
    keys_before = [m["key"] for m in got_before["members"]]
    keys_after = [m["key"] for m in got_after["members"]]
    assert any(k.startswith("wrap_before.py") for k in keys_before), keys_before
    assert not any(k.startswith("wrap_after.py") for k in keys_after), (
        "чтение ПОСЛЕ `yield` названо членом класса — отсечка по `yield` не работает: "
        f"{keys_after}")


# ─────────── звено 4: контейнер привязкой НЕ является ───────────

CONTAINER = '''\
import pytest


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    box = {"c": call}                 # контейнер — НЕ привязка (урок _injected_clock)
    assert box["c"].excinfo is None or True
    return (yield)
'''


def test_container_is_not_a_binding(tmp_path):
    """Объявленная ГРАНИЦА оси, а не недосмотр.

    Считать «RHS содержит аргумент» происхождением значения значило бы оправдать
    ровно ту форму, против которой написан `_injected_clock` (авария 2026-08-04:
    `doc = {"generated_at": …}` рядом с `age_hours(doc)`). Граница названа вслух
    и в модуле прибора, и здесь; поэтому её исход — «не член», а не «член».
    """
    root = _scene(tmp_path, {"box_plugin": CONTAINER})
    result = _run_census(root, ("box_plugin",))
    assert result["verdict"] == "measured", result.get("reasons")
    assert [m["key"] for m in result["members"]] == [], (
        "граница оси сдвинулась: контейнер стал привязкой — тогда её надо не чинить "
        "молча, а объявить заново (инв. #16)")


FALSE_BINDING = '''\
import pytest


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    # Сравнение СОДЕРЖИТ аргумент, но значением от него не происходит.
    flag = call.when is not None
    probe = getattr(flag, "excinfo", None)
    assert probe is None or True
    return (yield)
'''


def test_a_false_binding_does_not_breed_a_member(tmp_path):
    """Вторая половина той же границы: `flag = call.when is not None` НЕ привязка.

    Сцена написана ПО ВЫЖИВШЕЙ МУТАЦИИ (замер цикла #1176): расширение засева до
    «RHS содержит имя аргумента» в одиночку не ловилось ни одним тестом батареи —
    контейнерная сцена держится ВТОРЫМ отказом (`_attr_root` требует `Name` в
    основании цепочки), и одиночную мутацию засева она не различает. Здесь поле
    выбрано так, чтобы ложная привязка дала именно `call.excinfo` — то есть
    ВЫДУМАННОГО члена класса там, где его нет.
    """
    root = _scene(tmp_path, {"false_binding": FALSE_BINDING})
    result = _run_census(root, ("false_binding",))
    assert result["verdict"] == "measured", result.get("reasons")
    assert [m["key"] for m in result["members"]] == [], (
        "ложная привязка родила члена класса: прибор стал выдумывать находки — "
        f"{result['members']}")
    rows = [r for r in result["rows"] if r["ours"] == "false_binding.py"]
    assert rows and rows[0]["touches"] == ["call.when"], rows


# ─────────── звено 5: прибор вычитает СЕБЯ ───────────

def test_observer_is_subtracted_from_the_subject(tmp_path):
    """Наблюдатель не предмет. Прибор, мерящий своё возмущение, мерит себя (ADR-898)."""
    root = _scene(tmp_path, {"quiet_plugin": QUIET})
    result = _run_census(root, ("quiet_plugin",))
    assert result["verdict"] == "measured", result.get("reasons")
    assert result["observer_impls_subtracted"] >= 1, result
    for row in result["rows"]:
        assert TOOL.OBSERVER_PLUGIN not in row["ours"], row
        for later in row["later_not_ours"]:
            assert later["plugin"] != TOOL.OBSERVER_PLUGIN, (
                f"наблюдатель попал в предмет как чужая реализация: {later}")


# ─────────── звено 6: третий исход у КАЖДОГО источника ───────────

def test_unreadable_root_is_the_third_outcome(tmp_path, capsys):
    """Названное дерево не читается ⇒ ОТКАЗ код 2, а не молчаливый возврат к своему."""
    code = TOOL.main(["--repo-root", str(tmp_path / "нет-такого"), "--no-baseline"])
    assert code == TOOL.EXIT_UNMEASURED, code
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_child_without_a_record_is_unmeasured(tmp_path):
    """Дочерний pytest не дал записи ⇒ «НЕ ИЗМЕРЕНО» с причиной, а не пустой состав.

    Это ровно та ловушка, что стоила цикла #1175 (заказ G1025 п. 7): на пустом
    выводе разбор честно возвращает пустой список, и «0 членов» читается как ответ.
    """
    root = _scene(tmp_path, {})
    result = TOOL.census(root, (), ("нет-такой-цели.py",), ("нет-такого-плагина",))
    assert result["verdict"] == "unmeasured", result
    assert result["members"] == []
    assert result["reasons"] and any("наблюдатель" in r or "pytest" in r
                                     for r in result["reasons"]), result["reasons"]


def test_absent_function_name_is_unmeasured(tmp_path):
    """Имени функции нет в AST ⇒ причина названа, а не пустое множество путей."""
    src = TOOL._Source()
    path = tmp_path / "mod.py"
    path.write_text("def other():\n    pass\n", encoding="utf-8")
    touched, reasons, _bounds = TOOL.touched_paths(src, str(path), "pytest_x", ["item"], False)
    assert touched == set()
    assert reasons and "НЕ ИЗМЕРЕНО" in reasons[0], reasons


def test_unreadable_baseline_is_the_third_outcome(tmp_path, capsys):
    """Непрочитанное ОБЪЯВЛЕНИЕ — тоже «не измерено» (fail-CLOSED), а не «расхождений нет»."""
    root = _scene(tmp_path, {"quiet_plugin": QUIET})
    code = TOOL.main(["--repo-root", str(root), "--plugin", "quiet_plugin",
                      "--target", "test_scene.py",
                      "--baseline", str(tmp_path / "нет-объявления.json")])
    assert code == TOOL.EXIT_UNMEASURED, code
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


# ─────────── звено 7: расхождение с объявлением — находка, в ОБЕ стороны ───────────

def test_baseline_drift_is_a_finding_in_both_directions(tmp_path, capsys):
    """Пришло новое И объявленное исчезло — два РАЗНЫХ события, оба находки."""
    root = _scene(tmp_path, {"bomb_plugin": BOMB})
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"members": []}), encoding="utf-8")
    code = TOOL.main(["--repo-root", str(root), "--plugin", "bomb_plugin",
                      "--target", "test_scene.py", "--baseline", str(empty)])
    assert code == TOOL.EXIT_FINDINGS, code
    assert "ПРИШЛО НОВОЕ" in capsys.readouterr().err

    phantom = tmp_path / "phantom.json"
    phantom.write_text(json.dumps({"members": [
        "bomb_plugin.py::pytest_sessionstart#pytest_sessionstart",
        "нет-такого.py::pytest_x#pytest_x"]}), encoding="utf-8")
    code = TOOL.main(["--repo-root", str(root), "--plugin", "bomb_plugin",
                      "--target", "test_scene.py", "--baseline", str(phantom)])
    assert code == TOOL.EXIT_FINDINGS, code
    assert "ОБЪЯВЛЕННОЕ ИСЧЕЗЛО" in capsys.readouterr().err


def test_matching_baseline_is_green(tmp_path, capsys):
    """Обратный контроль: верный состав НЕ красит — иначе починка начала бы звонить."""
    root = _scene(tmp_path, {"bomb_plugin": BOMB})
    exact = tmp_path / "exact.json"
    exact.write_text(json.dumps({
        "members": ["bomb_plugin.py::pytest_sessionstart#pytest_sessionstart"]}),
        encoding="utf-8")
    code = TOOL.main(["--repo-root", str(root), "--plugin", "bomb_plugin",
                      "--target", "test_scene.py", "--baseline", str(exact)])
    assert code == TOOL.EXIT_OK, capsys.readouterr()


# ─────────── звено 8: живое дерево и объявление класса ───────────

def _assert_live_set_is_faithful(result) -> None:
    """Предпосылка живого дерева: набор плагинов зарегистрирован так, как в CI.

    Нужна отдельным утверждением, потому что ОДНА и та же пустота имеет две
    причины: класс действительно пуст ИЛИ дерево не поднимает набор (замер цикла
    #1176: клон `cp -Rc` дал **3** наших реализации вместо 23 и честный «ноль
    членов» — ровно та подделка, что в памяти записана за rsync-копией без `.git`).
    Без этой проверки копия отвечала бы «прибор ослеп» о целом приборе.
    """
    registrants = {row["ours"] for row in result["rows"]}
    assert result["ours_total"] >= 20 and "spa_core/ci/pytest_stream_record.py" in registrants, (
        "предпосылка НЕ ОБЕСПЕЧЕНА: в этом дереве зарегистрировано "
        f"{result['ours_total']} наших реализаций у {sorted(registrants)} — "
        "живой набор CI не поднялся, и судить о составе класса нечем")


@pytest.mark.repo_scan
def test_live_tree_matches_the_declaration(capsys):
    """Состав класса в ЖИВОМ наборе РОВНО совпадает с объявлением (храповик).

    Новый хук, вошедший в форму, краснит этот тест — именно для этого объявление и
    существует. **Дописывать в него, чтобы погасить падение, ЗАПРЕЩЕНО** (инв. #16):
    цена класса — 4320 тестов без исхода, и ADR-1036 показал, что «починено и
    доставлено» может не работать ни одного дня.
    """
    _assert_live_set_is_faithful(TOOL.census(_REPO_ROOT))
    code = TOOL.main(["--repo-root", str(_REPO_ROOT)])
    out = capsys.readouterr()
    assert code == TOOL.EXIT_OK, f"{out.out}\n{out.err}"


@pytest.mark.repo_scan
def test_live_tree_still_names_the_adr_1036_shape(capsys):
    """Положительный контроль на ЖИВОМ коде: известный член обязан быть виден.

    `spa_core/ci/pytest_stream_record.py::pytest_runtest_makereport` трогает
    `call.excinfo`, а ПОЗЖЕ его присваивает плоский `_pytest/unittest.py` — это
    настоящая авария ADR-1036, а не выдуманная сцена. Исчезни эта строка из вывода
    прибора — ослеп прибор, а не починился репозиторий.
    """
    result = TOOL.census(_REPO_ROOT)
    assert result["verdict"] == "measured", result.get("reasons")
    _assert_live_set_is_faithful(result)
    keys = {m["key"] for m in result["members"]}
    assert "spa_core/ci/pytest_stream_record.py::pytest_runtest_makereport#pytest_runtest_makereport" in keys, (
        f"прибор перестал видеть форму ADR-1036 на живом коде: {sorted(keys)}")
    _ = capsys.readouterr()
