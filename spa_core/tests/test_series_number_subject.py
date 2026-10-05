"""Батарея шага «подданный числа ряда» (заказ G99 п. 2, ADR-572).

ADR-518 мерил честность имени ЧИСЛОМ (``misnamed_gaps``) — у ДВУХ полей одного
шага. Заказ G99 п. 2 просит дословно:

    Честность имени спрошена у ДВУХ полей одного шага. ``misnamed_gaps``
    сверяет два утверждения ADR-469 из десятков полей ряда. Тот же вопрос,
    заданный ВСЕМ именам вердиктов ряда: сколько из них утверждают
    неспрошенное. Второй экземпляр класса нашёлся за шесть дней — значит класс
    не одиночный, и мерить его надо переписью, а не находкой.

Предмет батареи — правило, а не число дня: сцены несут ФОРМЫ (авария ADR-469
дословно, её починка оговоркой, вхождения, ноль, перечень не модуля, форма вне
перечня, счётчик вне формы), и у каждой свой названный ответ. Контроль в обе
стороны обязателен: правило, зелёное только на исправном контуре, от константы
не отличается.

Ни одного литерала даты и ни одного литерала pid здесь нет вовсе: подданный
числа не зависит ни от календаря, ни от того, какой номер процесса сегодня
занят.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import rule_second_copy_census as C

ROOT = Path(C.__file__).resolve().parents[2]
STEP = C.SUBJECT_OWN_STEP

#: Сцена одного шага: перечень ОБЪЯВЛЕН модулем, счётчик собран словарным
#: включением. Форму отбора подставляет каждый тест — именно она и есть
#: предмет правила.
SCENE = '''
A = "a"
B = "b"
_PROOFS = (A, B)
SILENT = "silent"
LOUD = "loud"
_OUTS = (SILENT, LOUD)


def scene_step(root):
    rows = walk(root)
    outcomes = {cls: sum(1 for r in rows if r["outcome"] == cls)
                for cls in _OUTS}
    picked = {p: sum(1 for r in rows if %s) for p in _PROOFS}
    return {"status": "MEASURED", "order": "G0.1", "population": len(rows),
            "writer_outcomes": outcomes, "picked": picked}
'''

#: Числа сцены объявлены ЗДЕСЬ: вердикт, вычисленный самой сценой, проверял бы
#: сам себя.
def _doc(picked: dict, **over) -> dict:
    step = {"status": "MEASURED", "order": "G0.1", "population": 248,
            "writer_outcomes": {"silent": 106, "loud": 120,
                                "unmeasured": 22},
            "picked": picked}
    step.update(over)
    return {"scene_step": step}


def _rows(source: str, doc: dict):
    tree = ast.parse(source)
    enums = C._subject_declared_enumerations(tree)
    return C._subject_rows(tree, doc, enums)


def _picked(source: str, doc: dict) -> dict:
    rows, _outside, _budget = _rows(source, doc)
    picked = [row for row in rows if row["field"] == "picked"]
    assert len(picked) == 1, f"сцена дала {len(picked)} строк(и) о `picked`"
    return picked[0]


# ------------------------------------------------------- КОНТРОЛЬ ПРАВИЛА

def test_the_declared_control_passes():
    """Контроль — часть правила: без него прибор отказывает целиком."""
    control = C._subject_control()
    assert control.get("passed") is True, control


def test_the_control_exercises_every_outcome_it_declares():
    """Сцены контроля дают РАЗНЫЕ ответы, а не один зелёный."""
    control = C._subject_control()
    assert set(control["outcomes"]) == {
        C.SUBJECT_POPULATION, C.SUBJECT_PUBLISHED, C.SUBJECT_UNPUBLISHED,
        C.SUBJECT_ZERO, C.SUBJECT_MEMBERSHIPS, C.SUBJECT_UNMEASURED_OUTCOME}
    assert len(control["gaps"]) >= 3
    assert control["outside_named"] >= 1


def test_a_failed_control_refuses_the_whole_step(monkeypatch):
    """Правило, не прошедшее свой контроль, не мерит НИЧЕГО — fail-CLOSED."""
    monkeypatch.setattr(C, "_subject_control",
                        lambda: {"passed": False, "reason": "сцена порвана"})
    out = C.subject_of_a_series_number(ROOT, _doc({"a": 1}))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_SUBJECT_CONTROL
    assert "сцена порвана" in out["reason"]


# -------------------------------------------- ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ ADR-469

def test_the_adr469_defect_is_named_a_number_without_a_published_subject():
    """Авария ДОСЛОВНО: имя говорит «чем доказано молчание», счёт идёт по ВСЕМ
    строкам. Сумма 142 не равна ни одному числу шага ⇒ находка."""
    row = _picked(SCENE % 'r["proved_by"] == p', _doc({"a": 80, "b": 62}))
    assert row["outcome"] == C.SUBJECT_UNPUBLISHED
    assert row["sum"] == 142
    assert row["form"] == C.SUBJECT_FORM_EQ
    assert row["closest"]["name"] and row["closest"]["delta"] != 0


def test_the_repair_of_that_defect_is_green_and_its_match_is_a_class_count():
    """Починка — та же оговорка исходом, которой чинились оба известных случая.
    Совпадение обязано быть именно с КЛАССОВЫМ счётом шага."""
    row = _picked(SCENE % 'r["proved_by"] == p and r["outcome"] == SILENT',
                  _doc({"a": 70, "b": 36}))
    assert row["outcome"] == C.SUBJECT_PUBLISHED
    assert row["form"] == C.SUBJECT_FORM_GUARDED
    assert row["match_kind"] == C.SUBJECT_MATCH_IN_COUNTER
    assert row["matched"] == ["writer_outcomes[silent]"]


def test_a_sum_equal_to_the_declared_population_is_its_own_answer():
    """Поле, делящее ВСЁ население, подданного не теряет."""
    row = _picked(SCENE % 'r["proved_by"] == p', _doc({"a": 148, "b": 100}))
    assert row["outcome"] == C.SUBJECT_POPULATION
    assert row["sum"] == 248


def test_a_match_with_a_scalar_field_is_weaker_and_said_to_be_weaker():
    """Сила совпадения разведена: «файлов просмотрено» подданным не является,
    и слить его с классовым счётом значило бы выдать слабое за сильное."""
    row = _picked(SCENE % 'r["proved_by"] == p',
                  _doc({"a": 300, "b": 200}, files_scanned=500))
    assert row["outcome"] == C.SUBJECT_PUBLISHED
    assert row["match_kind"] == C.SUBJECT_MATCH_SCALAR


def test_a_number_carried_by_several_names_names_no_subject():
    """Два имени с тем же числом подданного не называют — это сказано вслух."""
    row = _picked(SCENE % 'r["proved_by"] == p',
                  _doc({"a": 5, "b": 2}, files_scanned=7, extra_field=7)
                  )
    assert row["outcome"] == C.SUBJECT_PUBLISHED
    assert row["match_kind"] == C.SUBJECT_MATCH_SEVERAL


def test_the_field_is_never_matched_against_itself():
    """Сумма, равная ЗНАЧЕНИЮ своего же ключа, подданного не называет: иначе
    любое одноключевое поле объявлялось бы названным по построению."""
    row = _picked(SCENE % 'r["proved_by"] == p',
                  {"scene_step": {"status": "MEASURED", "order": "G0.1",
                                  "population": 248,
                                  "picked": {"a": 7, "b": 0}}})
    assert row["sum"] == 7
    assert row["outcome"] == C.SUBJECT_UNPUBLISHED


# --------------------------------------------- ВЫДУМАННАЯ НАХОДКА: НЕ ДОПУСТИТЬ

def test_a_membership_counter_is_not_an_invented_finding():
    """Поиск ключа ВНУТРИ поля строки считает вхождения: сумма превышает
    население ПО ПОСТРОЕНИЮ, и назвать это находкой значило бы выдумать её.

    Это не оговорка в тексте: ровно такую форму несут `routes`, `read_forms` и
    `forms` живого ряда, и без разведения форм прибор напечатал бы три находки
    там, где нет ни одной."""
    row = _picked(SCENE % 'p in (r.get("routes") or [])',
                  _doc({"a": 60, "b": 35}, population=94))
    assert row["outcome"] == C.SUBJECT_MEMBERSHIPS
    assert row["form"] == C.SUBJECT_FORM_MEMBERSHIP
    assert row["sum"] == 95 > 94


def test_membership_through_a_plain_subscript_is_the_same_door():
    """Защитный хвост — не вторая дверь: `r["routes"]` и `r.get(...) or []`
    суть одно чтение поля строки."""
    row = _picked(SCENE % 'p in r["routes"]',
                  _doc({"a": 60, "b": 35}, population=94))
    assert row["form"] == C.SUBJECT_FORM_MEMBERSHIP


def test_zero_is_a_separate_outcome_because_a_zero_matches_every_zero():
    """Ноль не зачитывается совпадением (инв. #17)."""
    row = _picked(SCENE % 'r["proved_by"] == p', _doc({"a": 0, "b": 0}))
    assert row["outcome"] == C.SUBJECT_ZERO


# ----------------------------------------------- ТРЕТИЙ ИСХОД, А НЕ «ЧИСТО»

def test_an_unmeasured_step_cannot_look_clean():
    """У шага, который сам не измерен, подданного нет — и это НЕ «назван»."""
    row = _picked(SCENE % 'r["proved_by"] == p',
                  _doc({"a": 1, "b": 1}, status="UNMEASURED"))
    assert row["outcome"] == C.SUBJECT_UNMEASURED_OUTCOME
    assert row["gap"] == C.SUBJECT_GAP_STEP_UNMEASURED


def test_a_field_the_source_builds_but_the_verdict_lacks_is_named():
    doc = _doc({"a": 1})
    doc["scene_step"].pop("picked")
    row = _picked(SCENE % 'r["proved_by"] == p', doc)
    assert row["gap"] == C.SUBJECT_GAP_FIELD_ABSENT


def test_a_field_that_is_not_a_mapping_of_whole_numbers_is_named():
    row = _picked(SCENE % 'r["proved_by"] == p',
                  _doc({"a": "много"}))
    assert row["gap"] == C.SUBJECT_GAP_NOT_A_COUNTER


def test_an_enumeration_written_in_place_is_not_a_declared_one():
    """Перечень, живущий только внутри функции, правилом формы не признаётся:
    его состав меняется той же правкой, что и счёт."""
    source = SCENE.replace("for p in _PROOFS", "for p in ['a', 'b']")
    row = _picked(source % 'r["proved_by"] == p', _doc({"a": 1, "b": 1}))
    assert row["gap"] == C.SUBJECT_GAP_ENUM_UNDECLARED


def test_a_filter_form_outside_the_closed_list_is_a_third_outcome():
    """Форма вне перечня есть НЕЗНАНИЕ, а не «наверное, равенство»."""
    row = _picked(SCENE % 'r["proved_by"] != p', _doc({"a": 1, "b": 1}))
    assert row["gap"] == C.SUBJECT_GAP_FORM_OUTSIDE
    assert row["form"] is None


def test_a_counter_named_by_two_verdict_keys_is_not_guessed():
    """Поле, названное в вердикте ДВАЖДЫ, есть два утверждения; взять первое
    значило бы ответить уверенно там, где ответа нет."""
    source = SCENE.replace('"picked": picked}',
                           '"picked": picked, "also_picked": picked}')
    rows, _outside, _budget = _rows(source % 'r["proved_by"] == p',
                                    _doc({"a": 1, "b": 1}))
    unnamed = [row for row in rows if row["field"] is None]
    assert [row["gap"] for row in unnamed] == [C.SUBJECT_GAP_FIELD_UNNAMED]


def test_a_step_naming_no_module_level_function_is_named():
    doc = _doc({"a": 1})
    doc["ghost_step"] = {"status": "MEASURED", "order": "G0.9",
                         "population": 1, "ghost": {"a": 1}}
    rows, _outside, _budget = _rows(SCENE % 'r["proved_by"] == p', doc)
    ghost = [row for row in rows if row["step"] == "ghost_step"]
    assert [row["gap"] for row in ghost] == [C.SUBJECT_GAP_NO_FUNCTION]


# ------------------------------------------------------------ ВТОРАЯ ДВЕРЬ

def test_a_counter_built_by_a_loop_is_named_by_the_second_door():
    """Счётчик вне формы НЕ пропадает: правило формы его не судит, а вердикт
    шага называет его отдельным числом. Ненайденное не есть ноль."""
    source = SCENE + '''

def tally_step(root):
    rows = walk(root)
    tally = {}
    for r in rows:
        tally[r["proved_by"]] = tally.get(r["proved_by"], 0) + 1
    return {"status": "MEASURED", "order": "G0.2", "population": len(rows),
            "tally": tally}
'''
    doc = _doc({"a": 1, "b": 1})
    doc["tally_step"] = {"status": "MEASURED", "order": "G0.2",
                         "population": 9, "tally": {"a": 5, "b": 4}}
    rows, outside, _budget = _rows(source % 'r["proved_by"] == p', doc)
    assert not [row for row in rows if row["step"] == "tally_step"]
    assert {(item["step"], item["field"]) for item in outside} >= {
        ("tally_step", "tally")}


def test_the_budget_of_a_chance_equality_is_measured_not_promised():
    """Сколько РАЗНЫХ чисел публикует шаг — свойство замера, и оно измерено
    рядом с ним: чем их больше, тем дешевле случайное равенство."""
    _rows_, _outside, budget = _rows(SCENE % 'r["proved_by"] == p',
                                     _doc({"a": 1, "b": 1}))
    assert budget["scene_step"] >= 1
    out = C.subject_of_a_series_number(ROOT, _doc({"a": 1, "b": 1}))
    per_step = out["published_numbers_per_step"]
    assert per_step["least"] is not None and per_step["most"] is not None
    assert per_step["most"] >= per_step["least"] >= 1


# --------------------------------------------- ПРИБОР ВНЕ СВОЕГО НАСЕЛЕНИЯ

def test_the_own_step_is_excluded_by_name_not_by_luck():
    """Прибор в головной клетке своего замера менял бы его числа от одной
    доставки (ADR-566, воспроизведён ADR-568 в этом же файле)."""
    doc = _doc({"a": 1, "b": 1})
    before = C.subject_of_a_series_number(ROOT, doc)
    doc[STEP] = {"status": "MEASURED", "order": "G99.2", "population": 43,
                 "subject_outcomes": {"x": 43}}
    after = C.subject_of_a_series_number(ROOT, doc)
    assert before["population"] == after["population"]
    assert after["own_step_excluded"] == STEP
    assert STEP not in after["steps_without_a_number_of_the_declared_form"]


# ---------------------------------------------------- ОТКАЗЫ ЦЕЛОГО ПРИБОРА

def test_an_unreadable_producer_is_not_a_clean_pass(tmp_path):
    out = C.subject_of_a_series_number(tmp_path, _doc({"a": 1}))
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_SUBJECT_SOURCE


def test_a_series_without_a_single_order_is_not_zero_findings():
    out = C.subject_of_a_series_number(ROOT, {"status": "CLEAN",
                                              "counts": {"x": 1}})
    assert out["status"] == "UNMEASURED"
    assert out["unmeasured_class"] == C.UNMEASURED_SUBJECT_SERIES


# ------------------------------------------------- ЖИВОЙ ИСХОДНИК И СЧЁТ

def test_the_step_measures_the_real_producer():
    """Правило читает НАСТОЯЩИЙ исходник ряда, а не только сцены."""
    doc = {"verdict_over_named_keys": {
        "status": "MEASURED", "order": "G100.3", "population": 6,
        "verdict_outcomes": {cls: 1 for cls in C._VERDICT_OUTCOMES},
        "unresolved_reasons": {gap: 0 for gap in C._VERDICT_GAPS},
        "producer_proved_by": {form: 1 for form in C._PRODUCER_FORMS},
        "verdict_forms": {form: 2 for form in C._VERDICT_FORMS}}}
    out = C.subject_of_a_series_number(ROOT, doc)
    assert out["status"] == "MEASURED"
    assert out["population"] >= 4
    assert out["steps_declaring_an_order"] == 1


def test_the_outcomes_account_for_every_number_of_the_population():
    """Сумма исходов равна населению: число без исхода было бы ровно тем
    молчанием, которое шаг и ищет."""
    doc = _doc({"a": 1, "b": 1})
    out = C.subject_of_a_series_number(ROOT, doc)
    assert sum(out["subject_outcomes"].values()) == out["population"]
    assert (sum(out["unmeasured_reasons"].values())
            == out["subject_outcomes"][C.SUBJECT_UNMEASURED_OUTCOME])


def test_the_step_names_its_blindness_and_what_it_does_not_prove():
    out = C.subject_of_a_series_number(ROOT, _doc({"a": 1, "b": 1}))
    blind = " ".join(out["blind"])
    assert "равенство не есть тождество" in blind
    assert any("вред наступил" in item for item in out["what_it_does_not_prove"])
    assert out["applied"] is False


# ------------------------------------------------------------- ОТРИСОВКА

def test_the_report_carries_the_number_to_the_reader():
    doc = {"status": "CLEAN", STEP: C.subject_of_a_series_number(
        ROOT, _doc({"a": 80, "b": 62}))}
    lines = "\n".join(C.format_report(doc))
    assert "[ПОДДАННЫЙ ЧИСЛА]" in lines
    assert "[ПОДДАННЫЙ · ФОРМА ОТБОРА]" in lines
    assert "[ПОДДАННЫЙ · СИЛА СОВПАДЕНИЯ]" in lines
    assert "[ПОДДАННЫЙ · КОНТРОЛЬ]" in lines


def test_the_report_says_unmeasured_when_the_step_is_absent():
    """Отсутствие шага — ОТДЕЛЬНОЕ значение, а не «у всех подданный назван»."""
    lines = "\n".join(C.format_report({"status": "CLEAN"}))
    assert "[ПОДДАННЫЙ ЧИСЛА] НЕ ИЗМЕРЕНО" in lines


def test_the_report_says_unmeasured_when_the_step_refused(tmp_path):
    step = C.subject_of_a_series_number(tmp_path, _doc({"a": 1}))
    lines = "\n".join(C.format_report({"status": "CLEAN", STEP: step}))
    assert C.UNMEASURED_SUBJECT_SOURCE in "\n".join(
        line for line in lines.splitlines() if "ПОДДАННЫЙ" in line)


# ------------------------- ЖИВОЙ КОНТРОЛЬ: ТА ЖЕ ПОЧИНКА В НАСТОЯЩЕМ РЯДУ

#: Оговорка исхода у `resolved_by` — ДОСЛОВНО та починка, которой чинились оба
#: известных экземпляра класса (ADR-469 о себе, ADR-518 о двух своих именах).
#: Снятие её в НАСТОЯЩЕМ исходнике и есть форма аварии.
GUARD_WHOLE = '''    repairs = {rep: sum(1 for r in mine if r["resolved_by"] == rep
                        and r["kind_outcome"] == KIND_RESOLVED)
               for rep in _KIND_REPAIRS}'''
GUARD_TORN = '''    repairs = {rep: sum(1 for r in mine if r["resolved_by"] == rep)
               for rep in _KIND_REPAIRS}'''

#: Сцена ПРИГОДНА только если в ней есть строка исхода «накопитель —
#: последовательность», НЕСУЩАЯ ремонт: иначе снятие оговорки не меняет числа
#: вовсе, и зелёный мутант означал бы негодную сцену, а не силу правила.
#: Такую строку даёт элемент со СПИСКОВЫМ умолчанием (`setdefault(k, [0, 0])`).
LIVE_SCENE = '''
def walk(items):
    counts, extra = {}, [0] * 7
    for item in items:
        counts[item["cls"]] += 1
        extra[item["idx"]] += 1
    return counts, extra


def second(items):
    tally, spread = {}, [0] * 3
    for item in items:
        tally[item["cls"]] += 1
        spread[item["idx"]] += 1
    return tally, spread


def sequence_with_a_repair(items, witness):
    for item in items:
        witness.setdefault(item["k"], [0, 0])[item["idx"]] += 1


def opaque(items, lookup):
    counts = {}
    for item in items:
        counts[lookup(item)] += 1
    return counts
'''


def _disposable_series(root: Path, *, torn: bool) -> None:
    """Одноразовое дерево: сцена в каталогах ряда + НАСТОЯЩИЙ производитель."""
    for sub in C.OPEN_COUNTER_DIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
        (root / sub / "scene_counters.py").write_text(LIVE_SCENE,
                                                      encoding="utf-8")
    source = Path(C.__file__).read_text(encoding="utf-8")
    if torn:
        assert source.count(GUARD_WHOLE) == 1, (
            "оговорки исхода в исходнике нет — предпосылка контроля НЕ "
            "обеспечена, и судить о правиле нечем")
        source = source.replace(GUARD_WHOLE, GUARD_TORN, 1)
    target = root / C.PRODUCER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")


def _live_verdict(root: Path, name: str) -> dict:
    """Числа и форму даёт ОДИН текст — тот, что лежит в дереве.

    Грузить производителя из дерева обязательно: прогон импортированного
    модуля при мутированном файле отвечал бы о ДВУХ разных текстах, и
    контроль проверял бы не то, что заявлен.
    """
    spec = importlib.util.spec_from_file_location(name, root / C.PRODUCER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        counters = module.open_class_counter_census(root)
        writer = module.writer_harm_form(root, counters)
        kind = module.accumulator_kind_at_the_binding(root, writer)
        assert kind["status"] == "MEASURED", kind.get("reason")
        doc = {"open_class_counter_census": counters,
               "writer_harm_form": writer,
               "accumulator_kind_at_the_binding": kind}
        return {"kind": kind,
                "subject": module.subject_of_a_series_number(root, doc)}
    finally:
        sys.modules.pop(name, None)


def test_the_live_scene_is_eligible_for_the_control(tmp_path):
    """Предпосылка контроля ИЗМЕРЕНА, а не предположена: в сцене обязана быть
    строка, несущая ремонт при исходе «накопитель — последовательность»."""
    _disposable_series(tmp_path, torn=False)
    kind = _live_verdict(tmp_path, "c781_eligibility")["kind"]
    assert sum(kind["sequence_proved_by"].values()) > 0, (
        "сцена негодна: снятие оговорки не изменило бы ни одного числа, и "
        "зелёный контроль означал бы негодную сцену, а не силу правила")


def test_the_whole_contour_of_the_real_series_names_no_unpublished_number(
        tmp_path):
    _disposable_series(tmp_path, torn=False)
    subject = _live_verdict(tmp_path, "c781_whole")["subject"]
    assert subject["status"] == "MEASURED"
    assert subject["sum_matches_no_published_number"] == 0


def test_removing_that_guard_in_the_real_source_is_named_at_once(tmp_path):
    """Авария ADR-469, воспроизведённая в НАСТОЯЩЕМ модуле: оговорка снята —
    и число отчитывается о населении, которого шаг не назвал."""
    _disposable_series(tmp_path, torn=True)
    live = _live_verdict(tmp_path, "c781_torn")
    subject = live["subject"]
    assert subject["sum_matches_no_published_number"] == 1
    named = subject["unpublished_sample"][0]
    assert named["step"] == "accumulator_kind_at_the_binding"
    assert named["field"] == "resolved_by"
    assert named["form"] == C.SUBJECT_FORM_EQ
    assert named["sum"] == sum(live["kind"]["resolved_by"].values())


# ------------- ДЫРЫ СЦЕНЫ, НАЙДЕННЫЕ МУТАЦИЕЙ (каждая названа по мутанту)

def test_an_enumeration_resolved_only_in_part_is_not_a_declared_one():
    """Перечень, у которого разобран не КАЖДЫЙ член, не объявлен наполовину:
    он не перечень вовсе. Мутант «разобран наполовину считается объявленным»
    выжил, потому что ни одна сцена такого перечня не несла."""
    source = SCENE.replace("_PROOFS = (A, B)", "_PROOFS = (A, 7)")
    row = _picked(source % 'r["proved_by"] == p', _doc({"a": 1, "b": 1}))
    assert row["gap"] == C.SUBJECT_GAP_ENUM_UNDECLARED


def test_the_form_tally_counts_only_measured_numbers():
    """«Сколько чисел собрано формой X» и «сколько ИЗМЕРЕНО формой X» — разные
    утверждения, и слить их значило бы повторить предмет самого шага. Мутант
    «формы считаются и у третьего исхода» выжил на дыре этой сцены.

    Сцена берёт НАСТОЯЩИЙ шаг ряда (его функция в производителе есть, значит
    форма у строк читается), но объявляет его НЕ ИЗМЕРЕННЫМ: тогда формы
    известны, а измеренных чисел нет ни одного."""
    doc = {"verdict_over_named_keys": {
        "status": "UNMEASURED", "order": "G100.3",
        "verdict_outcomes": {cls: 1 for cls in C._VERDICT_OUTCOMES},
        "unresolved_reasons": {gap: 0 for gap in C._VERDICT_GAPS},
        "producer_proved_by": {form: 1 for form in C._PRODUCER_FORMS},
        "verdict_forms": {form: 2 for form in C._VERDICT_FORMS}}}
    out = C.subject_of_a_series_number(ROOT, doc)
    assert out["population"] >= 4
    assert (out["subject_outcomes"][C.SUBJECT_UNMEASURED_OUTCOME]
            == out["population"])
    assert {row for row in out["unmeasured_reasons"]
            if out["unmeasured_reasons"][row]} == {
                C.SUBJECT_GAP_STEP_UNMEASURED}
    assert sum(out["filter_forms"].values()) == 0, (
        "форма третьего исхода зачтена в раскладку измеренных")


def test_the_budget_edges_are_not_the_same_number():
    """Нижняя и верхняя границы бюджета — РАЗНЫЕ утверждения: выдать самое
    частое за самое редкое значит скрыть шаг, публикующий одно число. Мутант
    «самое частое выдаётся за самое редкое» выжил, пока сцена была одношаговой."""
    doc = _doc({"a": 1, "b": 1})
    doc["lean_step"] = {"status": "MEASURED", "order": "G0.3",
                        "picked": {"a": 1}}
    out = C.subject_of_a_series_number(ROOT, doc)
    per_step = out["published_numbers_per_step"]
    assert per_step["least"] < per_step["most"]
