"""Батарея шага «ВЕРДИКТ ПО ИМЕНОВАННЫМ КЛЮЧАМ» (заказ G100 п. 3, ADR-520).

ADR-468 починил ОДИН гейт. Вердикт теневого моста доставки спрашивал у
счётчика классов ДВА ИМЕНИ:

    'verdict': ('CLEAN' if not counts.get(UNEXPLAINED)
                and not counts.get(WEAKENING) else 'DIRTY')

а производитель классов (`classify_mismatch`) умел вернуть ТРЕТИЙ —
«старое решение НЕ ЗАПИСАНО». На нуле сравнений гейт печатал `CLEAN` и код
возврата 0, то есть ПОДДЕЛЫВАЛ доказательство безопасности, и от настоящего
доказательства подделка была неотличима.

Нашли это не замером, а чужим заказом. Заказ G84 п. 1 (24.09), он же G85 п. 3,
он же G100 п. 3, просит дословно:

    Сколько в дереве функций, возвращающих вердикт из счётчика классов,
    читают его ИМЕНОВАННЫМИ ключами при производителе, способном вернуть
    класс вне этого набора. Односторонность назвать заранее и ограничить
    звеном: производитель обязан быть найден в ТОМ ЖЕ файле (межфайловый
    разбор — третий исход, а не догадка). Третий исход обязателен там, где
    производитель не найден: «читает два ключа» без знания, сколько классов
    бывает, — не отказ, а незнание.

Население шага мало, поэтому почти всё здесь — КОНТРОЛЬ: зелёный контур
целиком, красное на КАЖДОМ порванном звене с НАЗВАННЫМ звеном, и отказ шага
там, где предпосылка не обеспечена. Отдельный разряд — контроли НА КОНТРОЛЬ:
каждую клаузу `_verdict_control` обязан ловить отдельный тест, иначе снять
любую поодиночке можно было бы молча (уроки ADR-517, ADR-518, ADR-519).

Ни одного литерала даты и ни одного литерала pid здесь нет вовсе: предмет
шага не зависит ни от календаря, ни от того, какой номер сегодня занят.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import rule_second_copy_census as C

STEP = "verdict_over_named_keys"


# --------------------------------------------------------------- вход сцены

def _positive():
    rows, elsewhere = C._verdict_sites("<scene>",
                                       ast.parse(C.VERDICT_CONTROL_SOURCE))
    return rows, elsewhere


def _negative():
    rows, elsewhere = C._verdict_sites("<scene-clean>",
                                       ast.parse(C.VERDICT_CONTROL_CLEAN))
    return rows, elsewhere


def _sites(source: str):
    return C._verdict_sites("<inline>", ast.parse(source))


def _scope(source: str, name: str) -> ast.AST:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    raise AssertionError(f"в сцене нет функции {name}")


# ------------------------------------------------- положительная половина

def test_positive_scene_holds_exactly_five_verdicts():
    """Сцена, ничего не предъявившая, силы правила не доказывает."""
    rows, _elsewhere = _positive()
    assert len(rows) == 5, [r["owner"] for r in rows]


def test_positive_scene_excludes_nothing():
    """Половина сцены, не доехавшая до правила, — не сцена, а видимость."""
    _rows, elsewhere = _positive()
    assert elsewhere == 0


def test_every_positive_verdict_is_resolved():
    rows, _ = _positive()
    unresolved = [r for r in rows if r["verdict"] == C.VERDICT_UNRESOLVED]
    assert not unresolved, [(r["owner"], r["gap"]) for r in unresolved]


def test_positive_scene_proves_every_declared_producer_form():
    """Правило, знающее одну форму, объявит «производителя нет» там, где он есть."""
    rows, _ = _positive()
    forms = sorted({f for r in rows for f in r["producer_forms"]})
    assert forms == sorted(C._PRODUCER_FORMS)


def test_positive_scene_shows_every_declared_verdict_form():
    rows, _ = _positive()
    assert sorted({r["form"] for r in rows}) == sorted(C._VERDICT_FORMS)


def test_positive_scene_shows_every_resolved_outcome():
    rows, _ = _positive()
    want = sorted(set(C._VERDICT_OUTCOMES) - {C.VERDICT_UNRESOLVED})
    assert sorted({r["verdict"] for r in rows}) == want


def test_the_adr468_incident_is_reproduced_by_name():
    """Положительный контроль = НАСТОЯЩАЯ авария, а не её пересказ."""
    rows, _ = _positive()
    blind = [r for r in rows if r["verdict"] == C.VERDICT_BLIND]
    assert len(blind) == 1
    assert blind[0]["owner"] == "incident"
    assert blind[0]["named_nowhere"] == ["old_not_recorded"]
    assert blind[0]["producer_forms"] == [C.PRODUCER_BY_CALL]


def test_the_incident_verdict_has_only_two_outcomes():
    """Цена аварии ADR-468 — ДВА исхода на ТРИ класса; число обязано быть в строке."""
    rows, _ = _positive()
    blind = [r for r in rows if r["verdict"] == C.VERDICT_BLIND][0]
    assert blind["outcomes"] == 2
    assert len(blind["producer_classes"]) == 3


def test_named_elsewhere_is_not_reported_as_blind():
    """Класс, названный ДРУГОЙ дорогой той же области, вредом не объявляется."""
    rows, _ = _positive()
    partial = [r for r in rows if r["verdict"] == C.VERDICT_NAMED_ELSEWHERE]
    assert len(partial) == 1 and partial[0]["owner"] == "named_elsewhere"
    assert partial[0]["missing"] == ["weakening"]
    assert "named_nowhere" not in partial[0]


# ------------------------------------------------- отрицательная половина

def test_negative_scene_resolves_nothing():
    rows, _ = _negative()
    resolved = [r for r in rows if r["verdict"] != C.VERDICT_UNRESOLVED]
    assert not resolved, [(r["owner"], r["verdict"]) for r in resolved]


def test_negative_scene_refuses_by_every_declared_name():
    """Отказ под ЧУЖИМ именем посылает чинить не то (урок ADR-465)."""
    rows, _ = _negative()
    assert sorted({r["gap"] for r in rows}) == sorted(C._VERDICT_GAPS)


def test_negative_scene_holds_one_counter_per_refusal_name():
    """Два класса, слитые в одно имя, есть потеря указания на починку."""
    rows, _ = _negative()
    assert len(rows) == len(C._VERDICT_GAPS)


def test_gap_order_is_a_permutation_of_the_declared_gaps():
    """`.index` на незаявленном имени падает ГРОМКО — это лучше «первого попавшегося»."""
    assert sorted(C._VERDICT_GAP_ORDER) == sorted(C._VERDICT_GAPS)
    assert len(set(C._VERDICT_GAP_ORDER)) == len(C._VERDICT_GAP_ORDER)


def test_the_most_expensive_limit_is_named_first():
    """Порядок отказа не украшение: спор записей дороже формы ключа."""
    order = list(C._VERDICT_GAP_ORDER)
    assert order.index(C.VERDICT_GAP_WRITES_DISAGREE) < order.index(
        C.VERDICT_GAP_KEY_FORM)


# ------------------------------------------------------- звенья по одному

def test_class_token_reads_a_constant_by_its_value_not_by_its_name():
    consts = {"CLEAN": "'clean'"}
    literal = ast.parse("'clean'", mode="eval").body
    named = ast.parse("CLEAN", mode="eval").body
    assert C._class_token(literal, consts) == ("value", "clean")
    assert C._class_token(named, consts) == ("value", "clean")


def test_class_token_of_an_unresolvable_name_is_not_a_value():
    """Ввезённая константа значением не является ни в какую сторону."""
    node = ast.parse("IMPORTED_CLASS", mode="eval").body
    assert C._class_token(node, {}) == ("name", "IMPORTED_CLASS")


def test_class_token_of_a_non_string_constant_is_absent():
    node = ast.parse("7", mode="eval").body
    assert C._class_token(node, {}) is None


def test_class_values_reads_both_branches_of_a_ternary():
    """Взять из тернарника одну ветвь значило бы занизить вселенную вдвое."""
    node = ast.parse("A if kinds else B", mode="eval").body
    got = C._class_values(node, {"A", "B"})
    assert got is not None and len(got) == 2


def test_class_values_of_a_half_opaque_ternary_is_absent_not_empty():
    """`None` — третий исход; пустой список читался бы как доказанная полнота."""
    node = ast.parse("A if kinds else row['x']", mode="eval").body
    assert C._class_values(node, {"A"}) is None


def test_field_read_name_knows_both_shapes_and_refuses_the_rest():
    assert C._field_read_name(ast.parse("row['cls']", mode="eval").body) == "cls"
    assert C._field_read_name(
        ast.parse("row.get('cls')", mode="eval").body) == "cls"
    assert C._field_read_name(ast.parse("row[key]", mode="eval").body) is None


def test_field_universe_knows_all_three_write_shapes():
    tree = ast.parse("""
A = "a"
B = "b"
D = "d"


def one(row):
    row["cls"] = A


def two():
    return {"cls": B}


def three(row):
    row.update(cls=D)
""")
    seen, opaque, values = C._field_class_universe(tree, "cls", {"A", "B", "D"})
    assert seen and not opaque
    assert sorted(v.id for v in values) == ["A", "B", "D"]


def test_field_universe_skips_a_relay_of_the_same_field():
    """Пересылка собственного поля нового класса не вводит и мутной не делает."""
    tree = ast.parse("""
A = "a"


def one(row):
    row["cls"] = A


def relay(prev):
    return {"cls": (prev or {}).get("cls")}
""")
    seen, opaque, values = C._field_class_universe(tree, "cls", {"A"})
    assert seen and not opaque and len(values) == 1


def test_field_universe_marks_a_genuinely_opaque_write():
    tree = ast.parse("""
A = "a"


def one(row, raw):
    row["cls"] = A


def two(row, raw):
    row["cls"] = raw["whatever"]
""")
    seen, opaque, _values = C._field_class_universe(tree, "cls", {"A"})
    assert seen and opaque


def test_a_loop_target_binding_is_not_mistaken_for_a_value():
    """Ловушка, из-за которой порядок звеньев не произволен.

    `_scope_bindings` связывает цель цикла с ИТЕРИРУЕМЫМ. Спроси правило о
    связываниях РАНЬШЕ, чем о цикле, — и классом объявился бы сам перечень.
    """
    source = """
A = "a"
B = "b"
KINDS = (A, B)
OK = "ok"
BAD = "bad"


def over(rows):
    counts = {}
    for cls in KINDS:
        counts[cls] = counts.get(cls, 0) + len(rows)
    return BAD if counts.get(A) or counts.get(B) else OK
"""
    rows, _ = _sites(source)
    assert len(rows) == 1
    assert rows[0]["producer_forms"] == [C.PRODUCER_BY_ENUMERATION]
    assert rows[0]["producer_classes"] == ["a", "b"]


def test_a_verdict_with_only_one_classful_branch_is_not_a_verdict():
    """Ветвь, способная вернуть что угодно, судить о полноте не позволяет."""
    source = """
A = "a"
OK = "ok"


def half(rows, fallback):
    counts = {}
    for row in rows:
        counts[A] = counts.get(A, 0) + 1
    return OK if counts.get(A) else fallback
"""
    rows, _ = _sites(source)
    assert rows == []


def test_class_named_in_scope_does_not_answer_by_substring():
    """`'field'` живёт внутри слова `fields` — текстовый ответ выдумал бы упоминание."""
    scope = _scope("""
def scope(rows):
    fields = [r["fields"] for r in rows]
    return fields
""", "scope")
    assert C._class_named_in_scope(scope, ("value", "field"), {}) is False
    assert C._class_named_in_scope(scope, ("value", "fields"), {}) is True


def test_owner_function_is_the_innermost_one():
    """Диапазон строк был бы догадкой: вложенная и объемлющая перекрываются."""
    tree = ast.parse("""
def outer():
    def inner():
        x = 1
        return x
    return inner
""")
    target = [n for n in ast.walk(tree)
              if isinstance(n, ast.Return) and isinstance(n.value, ast.Name)
              and n.value.id == "x"][0]
    parents = C._parent_map(tree)
    assert C._owner_function(parents, target).name == "inner"


def test_counter_reads_returns_unnamed_keys_too():
    """Отбор делает вызывающий: молча выкинуть такой вердикт значило бы сузить население."""
    test = ast.parse("counts.get(A) or counts[row['x']]", mode="eval").body
    got = C._counter_reads_by_name(test)
    assert sorted(ast.unparse(k) for k in got["counts"]) == ["A", "row['x']"]


def test_a_counter_read_by_a_key_that_is_not_a_class_is_outside_the_population():
    source = """
A = "a"
OK = "ok"
BAD = "bad"


def dynamic(rows, key):
    counts = {}
    for row in rows:
        counts[A] = counts.get(A, 0) + 1
    return BAD if counts.get(key) else OK
"""
    rows, _ = _sites(source)
    assert rows == []


def test_a_counter_written_in_another_scope_is_counted_not_swallowed():
    """Одноимённые `counts` соседних функций суть РАЗНЫЕ словари."""
    source = """
A = "a"
OK = "ok"
BAD = "bad"


def fill(rows):
    counts = {}
    for row in rows:
        counts[A] = counts.get(A, 0) + 1
    return counts


def judge(counts):
    return BAD if counts.get(A) else OK
"""
    rows, elsewhere = _sites(source)
    assert rows == []
    assert elsewhere == 1


def test_a_name_that_is_never_a_counter_is_not_counted_as_excluded():
    """Число, чьё имя не описывает считаемого, — предмет всего ряда."""
    source = """
A = "a"
OK = "ok"
BAD = "bad"


def fill(rows):
    counts = {}
    for row in rows:
        counts[A] = counts.get(A, 0) + 1
    return counts


def judge(doc):
    return BAD if doc.get(A) else OK
"""
    _rows, elsewhere = _sites(source)
    assert elsewhere == 0


def test_a_key_that_is_also_a_parameter_refuses_by_its_own_name():
    source = """
A = "a"
OK = "ok"
BAD = "bad"


def shadowed(rows, cls):
    counts = {}
    for row in rows:
        cls = A
        counts[cls] = counts.get(cls, 0) + 1
    return BAD if counts.get(A) else OK
"""
    rows, _ = _sites(source)
    assert len(rows) == 1
    assert rows[0]["gap"] == C.VERDICT_GAP_KEY_BOUND_ELSEWHERE


# ------------------------------------------------------- контроль целиком

def test_control_passes_on_the_declared_scenes():
    control = C._verdict_control()
    assert control["passed"], control.get("reason")
    assert control["positive"] == 5
    assert control["negative"] == len(C._VERDICT_GAPS)
    assert control["incident_class"] == ["old_not_recorded"]


# ------------------------------------------ КОНТРОЛИ НА КОНТРОЛЬ (по клаузе)

def _control_with(monkeypatch, *, source=None, clean=None):
    if source is not None:
        monkeypatch.setattr(C, "VERDICT_CONTROL_SOURCE", source)
    if clean is not None:
        monkeypatch.setattr(C, "VERDICT_CONTROL_CLEAN", clean)
    return C._verdict_control()


def test_control_refuses_a_scene_that_does_not_parse(monkeypatch):
    out = _control_with(monkeypatch, source="def broken(:\n")
    assert not out["passed"] and "не разобрана" in out["reason"]


def test_control_refuses_a_positive_scene_of_the_wrong_size(monkeypatch):
    out = _control_with(monkeypatch, source="A = 'a'\n")
    assert not out["passed"] and "из 5" in out["reason"]


def test_control_refuses_a_positive_scene_that_excludes_a_verdict(monkeypatch):
    """Сцена, половина которой до правила не доехала, силы правила не доказывает."""
    source = C.VERDICT_CONTROL_SOURCE + '''

def judged_elsewhere(counts):
    return DIRTY if counts.get(UNEXPLAINED) else CLEAN
'''
    out = _control_with(monkeypatch, source=source)
    assert not out["passed"] and "другой области" in out["reason"]


def test_control_refuses_when_a_positive_verdict_stays_unresolved(monkeypatch):
    source = C.VERDICT_CONTROL_SOURCE.replace(
        "        cls = classify(row)\n",
        "        cls = classify(row['raw'])['k']\n", 1)
    out = _control_with(monkeypatch, source=source)
    assert not out["passed"] and "не разрешил" in out["reason"]


def test_control_refuses_when_a_producer_form_is_never_shown(monkeypatch):
    """Форма, ни разу не предъявленная, пробой не проверена."""
    source = C.VERDICT_CONTROL_SOURCE.replace(
        "        counts[cls] = counts.get(cls, 0) + len(rows)\n",
        "        counts[UNEXPLAINED] = counts.get(UNEXPLAINED, 0) + len(rows)\n",
        1)
    out = _control_with(monkeypatch, source=source)
    assert not out["passed"] and "формами" in out["reason"]


def test_control_refuses_when_a_verdict_form_is_never_shown(monkeypatch):
    source = C.VERDICT_CONTROL_SOURCE.replace("""    if counts.get(UNEXPLAINED) or counts.get(WEAKENING):
        return DIRTY
    else:
        return CLEAN
""", """    return DIRTY if counts.get(UNEXPLAINED) or counts.get(WEAKENING) else CLEAN
""")
    out = _control_with(monkeypatch, source=source)
    assert not out["passed"] and "формы вердикта" in out["reason"]


def test_control_refuses_when_a_resolved_outcome_is_never_shown(monkeypatch):
    """Исход, ни разу не предъявленный, пробой не проверен."""
    source = C.VERDICT_CONTROL_SOURCE.replace(
        "    if counts.get(UNEXPLAINED) or seen_weak:",
        "    if counts.get(UNEXPLAINED) or counts.get(WEAKENING) or seen_weak:")
    out = _control_with(monkeypatch, source=source)
    assert not out["passed"] and "исходы" in out["reason"]


def test_control_refuses_when_the_incident_is_not_reproduced_by_name(monkeypatch):
    """Авария, потерявшая ИМЯ ослепшего класса, положительным контролем не является."""
    source = C.VERDICT_CONTROL_SOURCE.replace(
        'OLD_NOT_RECORDED = "old_not_recorded"',
        'OLD_NOT_RECORDED = "renamed_by_hand"', 1)
    out = _control_with(monkeypatch, source=source)
    assert not out["passed"] and "ADR-468" in out["reason"]


def test_control_refuses_a_negative_scene_that_resolves(monkeypatch):
    out = _control_with(monkeypatch, clean=C.VERDICT_CONTROL_SOURCE)
    assert not out["passed"] and "разрешил" in out["reason"]


def test_control_refuses_a_negative_scene_missing_a_refusal_name(monkeypatch):
    clean = C.VERDICT_CONTROL_CLEAN.replace("""

def by_a_form_outside(rows):
    counts = {}
    for row in rows:
        counts[str(row["s"]).lower()] = counts.get(str(row["s"]).lower(), 0) + 1
    return BAD if counts.get(ALPHA) else OK
""", "\n")
    assert "by_a_form_outside" not in clean
    out = _control_with(monkeypatch, clean=clean)
    assert not out["passed"] and "именами" in out["reason"]


def test_control_refuses_two_counters_under_one_refusal_name(monkeypatch):
    """Клауза, которую видно только сводным `passed`, снимается молча."""
    clean = C.VERDICT_CONTROL_CLEAN + '''

def a_second_form_outside(rows):
    counts = {}
    for row in rows:
        counts[str(row["s"]).upper()] = counts.get(str(row["s"]).upper(), 0) + 1
    return BAD if counts.get(ALPHA) else OK
'''
    out = _control_with(monkeypatch, clean=clean)
    assert not out["passed"]
    assert "объявленных имён" in out["reason"]


# ------------------------------------------------------------- шаг целиком

def test_step_measures_the_live_tree(tmp_path):
    out = C.verdict_over_named_keys(Path(__file__).resolve().parents[2])
    assert out["status"] == "MEASURED"
    assert out["applied"] is False
    assert out["order"] == "G100.3"


def test_outcome_form_is_closed_and_sums_to_the_population():
    """Форма ЗАКРЫТА, сумма равна населению, каждый ноль ОБЪЯВЛЕН (инв. #17)."""
    out = C.verdict_over_named_keys(Path(__file__).resolve().parents[2])
    outcomes = out["verdict_outcomes"]
    assert sorted(outcomes) == sorted(C._VERDICT_OUTCOMES)
    assert sum(outcomes.values()) == out["population"]


def test_refusal_reasons_are_declared_even_when_zero():
    out = C.verdict_over_named_keys(Path(__file__).resolve().parents[2])
    assert sorted(out["unresolved_reasons"]) == sorted(C._VERDICT_GAPS)
    assert sum(out["unresolved_reasons"].values()) == \
        out["verdict_outcomes"][C.VERDICT_UNRESOLVED]


def test_step_refuses_a_tree_without_its_directories(tmp_path):
    out = C.verdict_over_named_keys(tmp_path)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_VERDICT_TREE
    assert "population" not in out


def test_step_refuses_an_unreadable_file(tmp_path):
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / C.OPEN_COUNTER_DIRS[0] / "broken.py").write_text(
        "def broken(:\n", encoding="utf-8")
    out = C.verdict_over_named_keys(tmp_path)
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_VERDICT_TREE
    assert out["files_unreadable"][0]["file"].endswith("broken.py")


def test_a_failed_control_refuses_the_step_and_does_not_read_as_zero(monkeypatch):
    """Отказ шага обязан быть отличим от «таких вердиктов нет»."""
    monkeypatch.setattr(C, "VERDICT_CONTROL_SOURCE", "A = 'a'\n")
    out = C.verdict_over_named_keys(Path(__file__).resolve().parents[2])
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_VERDICT_CONTROL
    assert "population" not in out and "verdict_outcomes" not in out


def test_an_empty_tree_is_a_measured_zero_not_a_refusal(tmp_path):
    """Измеренный ноль и НЕ измерено — разные исходы (инв. #17)."""
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True)
    out = C.verdict_over_named_keys(tmp_path)
    assert out["status"] == "MEASURED" and out["population"] == 0


def test_the_step_names_its_one_sidedness_out_loud():
    out = C.verdict_over_named_keys(Path(__file__).resolve().parents[2])
    blind = " ".join(out["blind"])
    assert "ТОЛЬКО в том же файле" in blind
    assert C.VERDICT_NAMED_ELSEWHERE in blind


# ------------------------------------------------------------- отрисовка

def test_report_says_unmeasured_when_the_step_is_absent():
    lines = C.report({}, max_rows=1)
    assert any("[ВЕРДИКТ ПО ИМЕНАМ] НЕ ИЗМЕРЕНО" in line for line in lines)
    assert any("НЕ «таких вердиктов нет»" in line for line in lines)


def test_report_prints_the_refusal_class_when_the_step_refused():
    doc = {STEP: {"status": "UNMEASURED",
                  "unmeasured_class": C.UNMEASURED_VERDICT_CONTROL,
                  "reason": "правило не прошло контроль"}}
    lines = C.report(doc, max_rows=1)
    assert any(C.UNMEASURED_VERDICT_CONTROL in line for line in lines)


def test_report_prints_every_outcome_of_a_measured_step():
    doc = {STEP: C.verdict_over_named_keys(
        Path(__file__).resolve().parents[2])}
    lines = [ln for ln in C.report(doc, max_rows=3) if "ВЕРДИКТ" in ln]
    head = lines[0]
    assert "перечень ПОЛОН" in head and "не назван НИГДЕ" in head
    assert any("ЧЕМ ДОКАЗАН ПРОИЗВОДИТЕЛЬ" in ln for ln in lines)
    assert any("ПОЧЕМУ НЕ ИЗМЕРЕНО" in ln for ln in lines)
    assert any("НАСЕЛЕНИЕ" in ln for ln in lines)


# --------------------------------------------- ЧИСЛА И ОБРАЗЦЫ САМОГО ШАГА
#
# Раздел дописан циклом #737 по МУТАЦИОННОМУ замеру: из 89 мутаций региона
# батарея не убивала 18, и почти все выжившие сидели ровно здесь — в сводке.
# Числа шага были объявлены, но не ЗАКРЕПЛЕНЫ, и одна мутация оказалась не
# мутацией, а НАСТОЯЩИМ дефектом: `partial_sample` отбирался условием
# `!= VERDICT_NAMED_ELSEWHERE` при счётчике на `==`, то есть образец нёс НЕ
# свой класс. Это ровно тот дефект, который ищет вся перепись — число (здесь
# образец), чьё имя не описывает содержимого, — воспроизведённый внутри самого
# нового шага. Поэтому сводка закрепляется поимённо, а не «в целом».

#: Обе сцены сразу: только вместе они дают НЕНУЛЕВОЙ счёт по всем четырём
#: исходам, всем трём формам вердикта и всем пяти формам производителя. Сводка,
#: закреплённая там, где половина счётчиков нули, закрепляла бы нули.
_SCENES = {"scene": "VERDICT_CONTROL_SOURCE", "clean": "VERDICT_CONTROL_CLEAN"}


def _tree_of_both_scenes(tmp_path):
    """Одноразовое дерево шага + строки, выведенные ОТДЕЛЬНО от сводки.

    Сводка не выносит строк наружу, поэтому сверять её не с чем, кроме второго
    обхода теми же звеньями. Это и есть проверка: счётчик сводки обязан
    совпасть с прямым отбором по тому же классу.
    """
    for sub in C.OPEN_COUNTER_DIRS:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    rows = []
    for name, const in _SCENES.items():
        src = getattr(C, const)
        rel = f"{C.OPEN_COUNTER_DIRS[0]}/{name}.py"
        (tmp_path / rel).write_text(src, encoding="utf-8")
        found, _elsewhere = C._verdict_sites(rel, ast.parse(src))
        rows.extend(found)
    return C.verdict_over_named_keys(tmp_path), rows


def test_each_sample_carries_only_rows_of_its_own_class(tmp_path):
    """Положительный контроль на дефект, найденный мутацией #737.

    Образец обязан нести РОВНО свой класс. `partial_sample` отбирался на
    `!=` при счётчике на `==`: читатель видел «неполных 3» и образец из строк
    ДРУГОГО класса, и отличить это от верного образца было нечем.
    """
    out, rows = _tree_of_both_scenes(tmp_path)
    assert out["status"] == "MEASURED"
    by_class = {
        "harm_sample": (C.VERDICT_BLIND, "blind_to_a_class_named_nowhere"),
        "partial_sample": (C.VERDICT_NAMED_ELSEWHERE,
                           "partial_but_named_elsewhere"),
        "unresolved_sample": (C.VERDICT_UNRESOLVED, "still_unmeasured"),
    }
    # ни один образец не пуст: пустой прошёл бы «только свой класс» даром
    assert all(out[name] for name in by_class), \
        {n: len(out[n]) for n in by_class}
    for name, (cls, counter) in by_class.items():
        addrs = {(r["file"], r["line"]) for r in out[name]}
        same = {(r["file"], r["line"]) for r in rows if r["verdict"] == cls}
        assert addrs, name
        assert addrs <= same, (name, cls, sorted(addrs - same))
        assert len(out[name]) == min(out[counter], C.COSTED_SAMPLE)
    # и попарно образцы РАЗЛИЧНЫ: до починки два из трёх совпадали построчно
    assert {(r["file"], r["line"]) for r in out["partial_sample"]} != \
        {(r["file"], r["line"]) for r in out["unresolved_sample"]}


def test_the_report_pins_every_producer_form_count(tmp_path):
    """Форма ДОКАЗАТЕЛЬСТВА производителя — закрытый перечень со счётчиком."""
    out, rows = _tree_of_both_scenes(tmp_path)
    proved = out["producer_proved_by"]
    assert sorted(proved) == sorted(C._PRODUCER_FORMS)
    # счётчик считает ВХОЖДЕНИЕ формы в перечень форм строки, а не отсутствие
    for form in C._PRODUCER_FORMS:
        assert proved[form] == len(
            [r for r in rows if form in (r.get("producer_forms") or [])]), form
    # каждая форма предъявлена: ноль по одной означал бы, что её счётчик
    # закреплён нулём, то есть не закреплён вовсе
    assert all(proved[form] > 0 for form in C._PRODUCER_FORMS), proved


def test_the_report_pins_every_verdict_form_count(tmp_path):
    out, rows = _tree_of_both_scenes(tmp_path)
    forms = out["verdict_forms"]
    assert sorted(forms) == sorted(C._VERDICT_FORMS)
    for form in C._VERDICT_FORMS:
        assert forms[form] == len([r for r in rows if r["form"] == form]), form
    assert sum(forms.values()) == out["population"]
    assert all(forms[form] > 0 for form in C._VERDICT_FORMS), forms


def test_the_row_carries_the_line_of_its_verdict(tmp_path):
    """Адрес строки — часть находки: без него вердикт ищут глазами."""
    out, rows = _tree_of_both_scenes(tmp_path)
    assert rows, "сцена не дала ни одной строки"
    assert all(r["line"] > 0 for r in rows), [r["line"] for r in rows]
    assert len({r["line"] for r in rows}) > 1, \
        "все строки на одной линии — адрес не мог бы быть проверен"
    # и адрес доезжает до ОБРАЗЦА, а не только до строки
    assert all(item["line"] > 0
               for name in ("harm_sample", "partial_sample",
                            "unresolved_sample")
               for item in out[name])


# ------------------------------------------- ЗВЕНЬЯ РАЗБОРА, по одному тесту
#
# Те же 18 выживших мутаций назвали ветви, которых не касалась ни одна сцена.
# Здесь по тесту на ветвь, и каждый — положительный контроль: сцена подобрана
# так, что уронившее звено меняет ВЕРДИКТ, а не оформление.

def test_an_enumeration_may_be_annotated_and_may_follow_a_function():
    """Перечень ищется среди `AnnAssign` тоже, и не только до первой функции."""
    tree = ast.parse("def f():\n    pass\n\nKINDS: tuple = (A, B)\n")
    got = C._enumeration_elements(tree, "KINDS")
    assert got is not None and len(got) == 2


def test_an_enumeration_is_found_past_a_second_target_of_another_name():
    """Цель перебирается ВСЯ: имя может стоять не первым в `A = B = (...)`."""
    tree = ast.parse("OTHER = KINDS = (A, B)\n")
    assert C._enumeration_elements(tree, "KINDS") is not None


def test_a_non_name_target_does_not_crash_the_enumeration_search():
    """Цель-подписка именем не является — и не есть повод спрашивать `.id`."""
    tree = ast.parse("d = {}\nd['KINDS'] = (A, B)\n")
    assert C._enumeration_elements(tree, "KINDS") is None


def test_an_enumeration_that_is_not_a_container_is_not_an_enumeration():
    """`KINDS = build()` перечнем не является: перечислить его нечем."""
    tree = ast.parse("KINDS = build()\n")
    assert C._enumeration_elements(tree, "KINDS") is None


def test_an_empty_container_is_not_an_enumeration():
    tree = ast.parse("KINDS = ()\n")
    assert C._enumeration_elements(tree, "KINDS") is None


def test_a_one_sided_if_return_is_not_a_verdict():
    """Вердикт — развилка с ДВУМЯ объявленными ветвями.

    `if …: return DIRTY` без `else` даёт ОДИН класс, и признать его вердиктом
    значило бы взять в население развилку, второй ветви у которой нет.
    """
    declared = {"DIRTY", "CLEAN"}
    one = ast.parse("if x:\n    return DIRTY\n").body[0]
    assert C._verdict_outcomes(one, declared) is None
    both = ast.parse("if x:\n    return DIRTY\nelse:\n    return CLEAN\n").body[0]
    got = C._verdict_outcomes(both, declared)
    assert got is not None and got[0] == C.VERDICT_FORM_IF_RETURN


def test_a_return_branch_with_an_undeclared_class_is_not_a_verdict():
    """ВСЕ ветви обязаны быть объявленными классами, а не хотя бы одна."""
    declared = {"DIRTY"}
    node = ast.parse("if x:\n    return DIRTY\nelse:\n    return raw\n").body[0]
    assert C._verdict_outcomes(node, declared) is None


def test_an_if_assign_needs_a_shared_name_in_both_branches():
    """Пара присваиваний — это ОДНО имя в обеих ветвях."""
    declared = {"DIRTY", "CLEAN"}
    apart = ast.parse("if x:\n    a = DIRTY\nelse:\n    b = CLEAN\n").body[0]
    assert C._verdict_outcomes(apart, declared) is None
    shared = ast.parse("if x:\n    s = DIRTY\nelse:\n    s = CLEAN\n").body[0]
    got = C._verdict_outcomes(shared, declared)
    assert got is not None and got[0] == C.VERDICT_FORM_IF_ASSIGN


def test_an_if_assign_branch_with_an_undeclared_class_is_not_a_verdict():
    declared = {"DIRTY"}
    node = ast.parse("if x:\n    s = DIRTY\nelse:\n    s = raw\n").body[0]
    assert C._verdict_outcomes(node, declared) is None


_MIXED_KEYS = '''
OK = "ok"
BAD = "bad"


def verdict(rows, other):
    counts = {}
    for row in rows:
        counts[str(row)] = counts.get(str(row), 0) + 1
    return BAD if counts.get(BAD) or counts.get(other) else OK
'''


def test_a_verdict_whose_keys_are_not_all_declared_is_out_of_the_population():
    """Ключи ВСЕ до одного объявлены — иначе вердикт не в населении.

    `counts.get(other)` читает счётчик именем, чьё значение области неизвестно;
    взять такой вердикт значило бы судить о перечне, одного члена которого мы
    не знаем.
    """
    rows, _elsewhere = C._verdict_sites("<mixed>", ast.parse(_MIXED_KEYS))
    assert rows == []


_ITER_OVER_UNDECLARED = '''
OK = "ok"
BAD = "bad"
RAW = (1, 2)


def verdict(rows):
    counts = {}
    for n in RAW:
        counts[n] = counts.get(n, 0) + 1
    return BAD if counts.get(BAD) else OK
'''


def test_a_loop_over_a_container_of_undeclared_values_is_not_an_enumeration():
    """Перечень КЛАССОВ и просто контейнер на модуле — разные вещи.

    `RAW = (1, 2)` есть контейнер верхнего уровня, но классов в нём нет ни
    одного, поэтому перечнем объявленных классов он не является. Спросить о нём
    `_enumeration_elements` (которая отвечает о ЛЮБОМ контейнере) вместо
    `enums` (которая отвечает о перечне ОБЪЯВЛЕННЫХ) значило бы объявить
    вселенную производителя известной по содержимому, которое классами не
    является.
    """
    rows, _elsewhere = C._verdict_sites("<raw>",
                                        ast.parse(_ITER_OVER_UNDECLARED))
    assert len(rows) == 1, rows
    assert rows[0]["verdict"] == C.VERDICT_UNRESOLVED
    assert rows[0]["gap"] == C.VERDICT_GAP_KEY_FORM


_FIELD_ONLY_RELAYED = '''
OK = "ok"
BAD = "bad"


def writer(prev):
    return {"cls": (prev or {}).get("cls")}


def verdict(rows):
    counts = {}
    for row in rows:
        counts[row["cls"]] = counts.get(row["cls"], 0) + 1
    return BAD if counts.get(BAD) else OK
'''


def test_a_field_this_file_only_relays_gives_no_class_universe():
    """Поле, которое файл только ПЕРЕСЫЛАЕТ, вселенной классов не даёт.

    Релей (`{"cls": (prev or {}).get("cls")}`) новым классом не является и в
    мутные не зачисляется — значит `opaque` ложно, а классов ноль. «Мутно» и
    «классов не нашлось» суть РАЗНЫЕ причины одного отказа, и обе обязаны его
    давать: спроси только про `opaque`, и файл-релей объявил бы производителя
    известным с ПУСТОЙ вселенной, то есть вердикт — полным по построению.
    """
    tree = ast.parse(_FIELD_ONLY_RELAYED)
    seen, opaque, values = C._field_class_universe(tree, "cls", {"OK", "BAD"})
    assert (seen, opaque, values) == (True, False, [])
    rows, _elsewhere = C._verdict_sites("<relay>", tree)
    assert len(rows) == 1, rows
    assert rows[0]["verdict"] == C.VERDICT_UNRESOLVED
    assert rows[0]["gap"] == C.VERDICT_GAP_NOT_ENUMERABLE
