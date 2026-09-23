"""Заказ G76 п. 1 — население класса «исход с именем, которого никто не объявлял».

ADR-459 снял класс с именем ``'None'`` у ОДНОГО поля одного прибора и на этом
остановился. Население класса не спросил никто, а форма ищется механически:
``X[k] = X.get(k, 0) + 1``, где ``k`` пришёл из артефакта и НЕ сверен с
объявленным перечнем.

Каждый тест здесь — положительный контроль: он воспроизводит либо УЖЕ
СЛУЧИВШУЮСЯ аварию (известный случай ADR-459), либо дефект, найденный при
постройке самого прибора отрицательной половиной сцены контроля.

**Два дефекта прибора, найденные ДО замера и закреплённые здесь:**

1. ``counts[cls] = counts.get(cls, 0) + 1`` связывало ИМЯ КЛЮЧА правой частью
   (обход цели ``ast.walk``-ом возвращает и контейнер, и ключ), а правая часть
   счётчика всегда читает данные — и ключ, пробегающий ОБЪЯВЛЕННЫЙ перечень,
   объявлялся «пришедшим из артефакта». Ровно тот дефект, который прибор ищет,
   внутри самого прибора.
2. Область разбиралась «сначала модуль, потом функции», а ``ast.walk`` по
   модулю видит и тела функций: всякий счётчик привязывался к области МОДУЛЯ,
   параметры функции оставались неизвестны.

Оба найдены ОТРИЦАТЕЛЬНОЙ половиной сцены. Без неё «правило нашло 2 в
известном случае» было бы неотличимо от «правило считает открытым что угодно».
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spa_core.monitoring import rule_second_copy_census as census
from spa_core.monitoring.rule_second_copy_census import (
    KEY_ARTIFACT,
    KEY_DECLARED,
    KEY_LITERAL,
    KEY_UNRESOLVED,
    OPEN_COUNTER_CONTROL_CLEAN,
    OPEN_COUNTER_CONTROL_SOURCE,
    OPEN_COUNTER_DIRS,
    OPEN_COUNTER_FOUND,
    OPEN_COUNTER_GUARDED,
    OPEN_COUNTER_NONE,
    UNMEASURED_CONTROL_MISSED,
    UNMEASURED_NO_TREE,
    _key_origin,
    _open_counter_control,
    _open_counter_sites,
    _scope_bindings,
    open_class_counter_census,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def sites(source: str):
    return _open_counter_sites("<scene>", ast.parse(source))


def only(source: str):
    found = sites(source)
    assert len(found) == 1, f"ожидался один счётчик, найдено {len(found)}"
    return found[0]


# ---------------------------------------------------------------------------
# 1. ИЗВЕСТНЫЙ СЛУЧАЙ — форма обязана его находить
# ---------------------------------------------------------------------------

def test_known_case_of_adr_459_is_found_by_the_declared_form():
    """Сцена — дословные строки прибора до ADR-459. Не найдены ⇒ форма врёт."""
    found = sites(OPEN_COUNTER_CONTROL_SOURCE)
    assert len(found) == 2, [s["key"] for s in found]
    assert [s["key"] for s in found] == ["outcome", "reach"]
    for site in found:
        assert site["key_origin"] == KEY_ARTIFACT
        assert site["membership_checked"] is False
        assert site["str_over_absence"] is True


def test_known_case_counters_are_attributed_to_their_function_not_the_module():
    """Дефект 2 прибора: область считалась модульной у всякого счётчика."""
    for site in sites(OPEN_COUNTER_CONTROL_SOURCE):
        assert site["owner"] == "scene", site


def test_preseeding_with_a_declared_enumeration_is_not_a_guard():
    """В известном случае предзаполнение БЫЛО и классу `'None'` не помешало."""
    scene = '''
DECLARED = ("a", "b")


def step(rows):
    counts = {cls: 0 for cls in DECLARED}
    for row in rows:
        counts[row.get("verdict")] = counts.get(row.get("verdict"), 0) + 1
'''
    assert only(scene)["membership_checked"] is False


# ---------------------------------------------------------------------------
# 2. ОТРИЦАТЕЛЬНАЯ ПОЛОВИНА — форма обязана ПРОМАХИВАТЬСЯ там, где должна
# ---------------------------------------------------------------------------

def test_key_running_over_a_declared_enumeration_is_not_from_an_artifact():
    """Дефект 1 прибора: подписка в цели связывала ключ правой частью."""
    found = sites(OPEN_COUNTER_CONTROL_CLEAN)
    declared = [s for s in found if s["key"] == "cls"]
    assert len(declared) == 1
    assert declared[0]["key_origin"] == KEY_DECLARED, declared[0]


def test_subscript_target_does_not_bind_the_key_name():
    """Корень дефекта 1, закреплённый у самого связывателя."""
    tree = ast.parse("def f(rows):\n    counts[cls] = counts.get(cls, 0) + 1\n")
    fn = tree.body[0]
    assert "cls" not in _scope_bindings(fn)


def test_membership_check_before_the_counter_is_seen():
    checked = [s for s in sites(OPEN_COUNTER_CONTROL_CLEAN)
               if s["key"] == "name"]
    assert len(checked) == 1
    assert checked[0]["key_origin"] == KEY_ARTIFACT
    assert checked[0]["membership_checked"] is True


def test_enclosing_if_membership_also_counts_as_a_check():
    scene = '''
DECLARED = ("a", "b")


def step(rows):
    counts = {}
    for row in rows:
        name = row.get("verdict")
        if name in DECLARED:
            counts[name] = counts.get(name, 0) + 1
'''
    assert only(scene)["membership_checked"] is True


def test_key_bound_by_a_subscript_is_from_an_artifact():
    """Слабость МОИХ тестов, найденная мутацией: подписка — тоже чтение данных.

    Мутация «subscript no longer reads data» выжила первый заход: все мои
    сцены доставали ключ через `.get`, и ветка подписки не проверялась ни
    разу.
    """
    scene = '''
def step(rows):
    counts = {}
    for row in rows:
        name = row["verdict"]
        counts[name] = counts.get(name, 0) + 1
'''
    site = only(scene)
    assert site["key_origin"] == KEY_ARTIFACT
    assert site["membership_checked"] is False


def test_literal_key_is_not_an_open_counter():
    scene = '''
def step(rows):
    counts = {}
    for _row in rows:
        counts["total"] = counts.get("total", 0) + 1
'''
    assert only(scene)["key_origin"] == KEY_LITERAL


# ---------------------------------------------------------------------------
# 3. ФОРМА объявлена, и не-счётчик счётчиком не объявляется
# ---------------------------------------------------------------------------

def test_a_different_container_on_each_side_is_not_a_counter():
    """`a[i] = b.get(i, 0) + 1` — не счётчик, а перенос."""
    assert sites('''
def step(a, b, i):
    a[i] = b.get(i, 0) + 1
''') == []


def test_a_different_key_on_each_side_is_not_a_counter():
    assert sites('''
def step(a, i, j):
    a[i] = a.get(j, 0) + 1
''') == []


def test_augmented_subscript_is_measured_as_its_own_form():
    scene = '''
def step(rows):
    counts = {}
    for row in rows:
        counts[row.get("verdict")] += 1
'''
    site = only(scene)
    assert site["form"] == "form_aug"
    assert site["key_origin"] == KEY_ARTIFACT


def test_subtracting_subscript_is_not_a_counter():
    assert sites('''
def step(a, i):
    a[i] -= 1
''') == []


# ---------------------------------------------------------------------------
# 4. `str()` ПОВЕРХ ОТСУТСТВИЯ — третья половина заказа
# ---------------------------------------------------------------------------

def test_str_over_a_get_is_seen_through_the_binding_chain():
    scene = '''
def step(rows):
    counts = {}
    for row in rows:
        name = str(row.get("verdict"))
        counts[name] = counts.get(name, 0) + 1
'''
    assert only(scene)["str_over_absence"] is True


def test_str_over_an_or_fallback_is_seen():
    scene = '''
def step(rows):
    counts = {}
    for row in rows:
        name = str((row.get("reach") or {}).get("reach"))
        counts[name] = counts.get(name, 0) + 1
'''
    assert only(scene)["str_over_absence"] is True


def test_str_over_an_or_fallback_alone_is_seen():
    """Слабость МОИХ тестов: прежняя сцена `or` несла ещё и `.get`.

    Мутация «str() over an `or` fallback no longer seen» выжила первый заход
    именно поэтому: ветку `.get` она не трогала, а сцена проходила по ней.
    Здесь `or` — ЕДИНСТВЕННОЕ свидетельство возможного отсутствия.
    """
    scene = '''
def step(rows, fallback):
    counts = {}
    for row in rows:
        name = str(row or fallback)
        counts[name] = counts.get(name, 0) + 1
'''
    assert only(scene)["str_over_absence"] is True


def test_str_over_a_literal_is_not_absence():
    scene = '''
def step(rows):
    counts = {}
    for _row in rows:
        name = str("total")
        counts[name] = counts.get(name, 0) + 1
'''
    assert only(scene)["str_over_absence"] is False


# ---------------------------------------------------------------------------
# 5. ТРЕТИЙ ИСХОД — «не разобрано» отличимо от «безопасно»
# ---------------------------------------------------------------------------

def test_unresolved_key_is_a_third_outcome_not_a_safe_one():
    scene = '''
def step(source, i):
    counts = {}
    counts[compute(source, i)] = counts.get(compute(source, i), 0) + 1
'''
    assert only(scene)["key_origin"] == KEY_UNRESOLVED


def test_bare_parameter_key_is_unresolved_not_declared():
    """Параметр не ограничен объявленным перечнем — и это НЕ «ключ безопасен»."""
    scene = '''
def step(key):
    counts = {}
    counts[key] = counts.get(key, 0) + 1
'''
    assert only(scene)["key_origin"] == KEY_UNRESOLVED


def test_binding_cycle_terminates_and_says_unresolved():
    scene = '''
def step(flag):
    counts = {}
    a = b
    b = a
    counts[a] = counts.get(a, 0) + 1
'''
    assert only(scene)["key_origin"] == KEY_UNRESOLVED


# ---------------------------------------------------------------------------
# 6. КОНТРОЛЬ ПРАВИЛА — без него ноль был бы свойством формы
# ---------------------------------------------------------------------------

def test_the_declared_rule_passes_its_own_control_both_ways():
    control = _open_counter_control()
    assert control["passed"] is True, control
    assert control["known_case_open"] == 2
    assert control["clean_false_positives"] == 0


@pytest.mark.repo_scan
def test_step_refuses_wholesale_when_the_form_misses_the_known_case(monkeypatch):
    """Форма, промахнувшаяся по известному случаю, ОТМЕНЯЕТ весь замер."""
    monkeypatch.setattr(census, "OPEN_COUNTER_CONTROL_SOURCE",
                        "def scene():\n    pass\n")
    out = open_class_counter_census(REPO_ROOT)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_CONTROL_MISSED
    assert "counters_total" not in out


@pytest.mark.repo_scan
def test_step_refuses_when_the_rule_calls_a_declared_key_open(monkeypatch):
    """Ложное срабатывание на отрицательной половине тоже ОТМЕНЯЕТ замер."""
    monkeypatch.setattr(census, "OPEN_COUNTER_CONTROL_CLEAN", '''
def clean(doc):
    counts = {}
    for item in doc:
        name = item.get("verdict")
        counts[name] = counts.get(name, 0) + 1
''')
    out = open_class_counter_census(REPO_ROOT)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_CONTROL_MISSED
    # Утверждение о ПОЛЕ, а не о слове в прозе: отказ обязан назвать, что
    # промах случился на отрицательной половине, а не на известном случае.
    assert out["control"]["clean_false_positives"] == 1
    assert "counters_total" not in out


@pytest.mark.repo_scan
def test_step_refuses_when_the_known_case_loses_its_str_over_absence(monkeypatch):
    """Слабость МОИХ тестов: половину контроля про `str()` не проверял никто.

    Мутация «control no longer demands str-over-absence» выжила первый заход.
    Сцена ниже несёт ОБА открытых счётчика, но ключ в ней приходит без
    `str()` поверх отсутствия — контроль обязан это заметить и отменить шаг.
    """
    monkeypatch.setattr(census, "OPEN_COUNTER_CONTROL_SOURCE", '''
def scene(rows):
    values = {}
    reaches = {}
    for row in rows:
        outcome = row.get("value_outcome")
        values[outcome] = values.get(outcome, 0) + 1
        reach = row.get("reach")
        reaches[reach] = reaches.get(reach, 0) + 1
''')
    out = open_class_counter_census(REPO_ROOT)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_CONTROL_MISSED
    assert out["control"]["open"] == 2
    assert "counters_total" not in out


def test_step_refuses_when_no_file_is_parsed(tmp_path):
    """Пустое дерево — НЕ «счётчиков нет»."""
    out = open_class_counter_census(tmp_path)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == UNMEASURED_NO_TREE
    assert "НЕ «счётчиков нет»" in out["reason"]


def test_unparsable_file_is_named_and_not_counted_as_clean(tmp_path):
    for sub in OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    good = tmp_path / OPEN_COUNTER_DIRS[0] / "good.py"
    good.write_text('def f(rows):\n    c = {}\n'
                    '    for r in rows:\n'
                    '        c[r.get("v")] = c.get(r.get("v"), 0) + 1\n',
                    encoding="utf-8")
    (tmp_path / OPEN_COUNTER_DIRS[0] / "broken.py").write_text(
        "def (:\n", encoding="utf-8")
    out = open_class_counter_census(tmp_path)
    assert out["status"] == "MEASURED"
    assert [f["file"] for f in out["files_unreadable"]] == [
        f"{OPEN_COUNTER_DIRS[0]}/broken.py"]
    assert out["open_to_an_unnamed_class"] == 1


# ---------------------------------------------------------------------------
# 7. ВЕРДИКТ — три исхода, и разделяет их предмет
# ---------------------------------------------------------------------------

def _tree_with(tmp_path: Path, body: str) -> Path:
    for sub in OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / OPEN_COUNTER_DIRS[0] / "mod.py").write_text(body,
                                                            encoding="utf-8")
    return tmp_path


def test_verdict_none_when_no_artifact_key_exists(tmp_path):
    out = open_class_counter_census(_tree_with(tmp_path, '''
def step(rows):
    counts = {}
    for _row in rows:
        counts["total"] = counts.get("total", 0) + 1
'''))
    assert out["verdict"] == OPEN_COUNTER_NONE
    assert out["open_to_an_unnamed_class"] == 0


def test_verdict_guarded_when_every_artifact_key_is_checked(tmp_path):
    out = open_class_counter_census(_tree_with(tmp_path, '''
DECLARED = ("a", "b")


def step(rows):
    counts = {}
    for row in rows:
        name = row.get("verdict")
        if name not in DECLARED:
            continue
        counts[name] = counts.get(name, 0) + 1
'''))
    assert out["verdict"] == OPEN_COUNTER_GUARDED
    assert out["key_from_artifact"] == 1
    assert out["membership_checked"] == 1
    assert out["open_to_an_unnamed_class"] == 0


def test_verdict_found_when_one_key_is_unchecked(tmp_path):
    out = open_class_counter_census(_tree_with(tmp_path, '''
def step(rows):
    counts = {}
    for row in rows:
        name = str(row.get("verdict"))
        counts[name] = counts.get(name, 0) + 1
'''))
    assert out["verdict"] == OPEN_COUNTER_FOUND
    assert out["open_to_an_unnamed_class"] == 1
    assert out["open_via_str_over_absence"] == 1


def test_str_over_absence_is_counted_only_among_the_open_ones(tmp_path):
    """Слабость МОИХ тестов: живой замер проверял лишь `<=`.

    Мутация «str-over-absence counted over ALL sites» выжила первый заход: в
    прежних сценах всякий счётчик с `str()` был ещё и открыт, и два населения
    совпадали. Здесь СВЕРЕННЫЙ счётчик тоже приходит через `str()`, и число
    обязано остаться при ОТКРЫТЫХ.
    """
    out = open_class_counter_census(_tree_with(tmp_path, '''
DECLARED = ("a", "b")


def step(rows):
    counts = {}
    for row in rows:
        name = str(row.get("verdict"))
        if name not in DECLARED:
            continue
        counts[name] = counts.get(name, 0) + 1
'''))
    assert out["verdict"] == OPEN_COUNTER_GUARDED
    assert out["membership_checked"] == 1
    assert out["open_to_an_unnamed_class"] == 0
    assert out["open_via_str_over_absence"] == 0


# ---------------------------------------------------------------------------
# 7б. ГРАНИЦА С СОСЕДЯМИ — обе аварии этого цикла
# ---------------------------------------------------------------------------

def test_the_control_scene_does_not_resurrect_the_retired_name():
    """Сцена не вправе гасить чужого сторожа ради буквальности.

    ADR-459 отставил имя `reach_outcome`, и сосед
    (`test_tail_value_divergence.py`) держит сторожа, требующего, чтобы в
    НЕ-комментарных строках модуля его не было вовсе. Первая редакция сцены
    воспроизводила известный случай ДОСЛОВНО и красила соседа. Класс
    составляют `str()` поверх отсутствия, ключ из артефакта и счётчик без
    сверки — отставленное имя классом не является.
    """
    assert "reach_outcome" not in OPEN_COUNTER_CONTROL_SOURCE
    assert "reach_outcome" not in OPEN_COUNTER_CONTROL_CLEAN
    # и контроль по-прежнему ловит известный случай — сцена ослаблена НЕ была
    assert _open_counter_control()["known_case_open"] == 2


def test_counter_census_helpers_do_not_shadow_a_neighbour_name():
    """Одно имя — один объект (`.claude/rules/adapters.md`).

    Помощник этого шага назывался `_enclosing_scope` — так же, как сосед по
    модулю строкой 5778, отвечающий на ДРУГОЙ вопрос и берущий два
    аргумента. Второе определение молча побеждало первое, и сосед падал
    `TypeError` на живом дереве. Тест — положительный контроль этой аварии.
    """
    tree = ast.parse(Path(census.__file__).read_text(encoding="utf-8"))
    names = [node.name for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    mine = {"_counter_target_key", "_scope_bindings", "_reads_data",
            "_literal_enumeration", "_key_origin", "_membership_checked",
            "_str_over_absence", "_counter_owner_scopes",
            "_open_counter_sites", "_open_counter_control",
            "open_class_counter_census"}
    assert mine <= set(names), sorted(mine - set(names))
    duplicated = sorted({n for n in mine if names.count(n) != 1})
    assert duplicated == [], duplicated


# ---------------------------------------------------------------------------
# 8. ЗАМЕР ЖИВОГО ДЕРЕВА — население класса, ради которого заказ и написан
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live() -> dict:
    return open_class_counter_census(REPO_ROOT)


@pytest.mark.repo_scan
def test_live_measurement_is_measured_at_all(live):
    assert live["status"] == "MEASURED", live.get("reason")
    assert live["files_scanned"] > 0
    assert live["counters_total"] > 0


@pytest.mark.repo_scan
def test_the_class_of_adr_459_has_a_population_beyond_one(live):
    """Главный ответ заказа: класс НЕ закрыт снятием одного случая."""
    assert live["open_to_an_unnamed_class"] > 1, live


@pytest.mark.repo_scan
def test_every_counter_is_classified_into_a_declared_outcome(live):
    counts = live["key_origin_counts"]
    assert set(counts) == {KEY_LITERAL, KEY_DECLARED, KEY_ARTIFACT,
                           KEY_UNRESOLVED}
    assert sum(counts.values()) == live["counters_total"]


@pytest.mark.repo_scan
def test_checked_plus_open_accounts_for_every_artifact_key(live):
    assert (live["membership_checked"] + live["open_to_an_unnamed_class"]
            == live["key_from_artifact"])


@pytest.mark.repo_scan
def test_str_over_absence_is_a_subset_of_the_open_ones(live):
    assert live["open_via_str_over_absence"] <= live["open_to_an_unnamed_class"]


@pytest.mark.repo_scan
def test_blindness_is_stated_in_the_document(live):
    joined = " ".join(live["blind"])
    assert "Counter(" in joined
    assert KEY_UNRESOLVED in joined


@pytest.mark.repo_scan
def test_step_is_advisory(live):
    assert live["applied"] is False
