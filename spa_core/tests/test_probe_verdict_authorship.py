"""Контроль прибора «чья мера произвела вердикт пробы» (заказ G96 п. 3, ADR-559).

Каждый тест — положительный контроль на конкретный способ соврать, а не
украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»). Прибор,
раздающий ярлык «ПРИБОР / САМА ПРОБА», опасен ровно тем же, чем опасна сводка
§49: он производит КРАСИВЫЙ ЯРЛЫК, и ложный ярлык по форме неотличим от верного,
а читатель по нему выбирает АДРЕСАТА спора.

Сцена синтетическая и это НАМЕРЕННО: каждая форма охраны предъявляется отдельным
исходным текстом, поэтому «проба такого рода в дереве сегодня есть» и «правило
такую пробу узнаёт» остаются разными утверждениями. Живое дерево проверяется
отдельно — паритетом разбора с настоящим реестром.

Литеральных дат в файле нет: у разбора исходного текста нет понятия свежести, и
заводить его фикстурой значило бы поставить бомбу на пустом месте
(`.claude/rules/deployment.md`, раздел про время). Литеральных pid нет: ни одного
процесса прибор не спрашивает.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from spa_core.monitoring import probe_verdict_authorship as A
from spa_core.monitoring.card_acceptance import PROBES

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import cio_acceptance_rollup as rollup  # noqa: E402

# --------------------------------------------------------------------------
# Сцена: одноразовый ИСХОДНЫЙ ТЕКСТ с реестром проб. Шапка одна на все сцены —
# иначе каждый тест заводил бы свою копию словаря статусов, и расхождение копий
# стало бы объяснять падения вместо правила (ADR-220).
# --------------------------------------------------------------------------
HEAD = '''
SATISFIED = "satisfied"
NOT_SATISFIED = "not_satisfied"
UNMEASURED = "unmeasured"

CENSUS_MODULE = "pkg.census_under_test"


def _census_module():
    import importlib
    return importlib.import_module(CENSUS_MODULE)
'''


def _source(tmp_path, body: str, registry: dict) -> str:
    """Исходный текст со шапкой, телами проб и реестром `PROBES`."""
    entries = ",\n".join(f'    "{k}": {v}' for k, v in registry.items())
    text = HEAD + body + "\n\nPROBES = {\n" + entries + ",\n}\n"
    path = tmp_path / "source_under_test.py"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _kind(tmp_path, body: str, registry: dict, probe: str) -> dict:
    report = A.measure(source=_source(tmp_path, body, registry))
    row = A.authorship_of(probe, report=report)
    assert row is not None, "проба не найдена в разборе — сцена собрана не так"
    return row


# --------------------------------------------------------------------------
# 1. Два рода узнаются, и каждый — своей формой охраны
# --------------------------------------------------------------------------

TRANSCRIBED = '''
def _probe_carried(arg):
    census = _census_module()
    report = census.run()
    status = report.get("status")
    if status == census.STATUS_OK:
        return SATISFIED, "перенос"
    if status in (census.STATUS_CRITICAL, census.STATUS_WARNING):
        return NOT_SATISFIED, "перенос"
    return UNMEASURED, "статус не переносится"
'''

SELF_JUDGED = '''
def _probe_own(arg):
    rows = [1, 2, 3]
    if len(rows) > 2:
        return NOT_SATISFIED, "свой порог"
    return SATISFIED, "свой порог"
'''


def test_a_probe_carrying_the_instruments_verdict_is_named_transcribed(tmp_path):
    row = _kind(tmp_path, TRANSCRIBED, {"carried": "_probe_carried"}, "carried")
    assert row["kind"] == A.KIND_TRANSCRIBED
    assert row["instruments"] == ["pkg.census_under_test"], (
        "имя прибора обязано доехать до читателя: без него «перенос» не говорит, "
        "С КЕМ спорить")


def test_a_probe_with_its_own_threshold_is_named_self_judged(tmp_path):
    row = _kind(tmp_path, SELF_JUDGED, {"own": "_probe_own"}, "own")
    assert row["kind"] == A.KIND_SELF_JUDGED
    assert row["instruments"] == []


# --------------------------------------------------------------------------
# 2. ОДНО ИМЯ — ДВА ОБЪЕКТА: приставка `STATUS_` вердиктом не является
# --------------------------------------------------------------------------

STATUS_PREFIX_BUT_NOT_A_VERDICT = '''
def _probe_filename(arg):
    census = _census_module()
    name = census.STATUS_FILENAME
    if name.endswith(".json"):
        return NOT_SATISFIED, "имя файла — не вердикт"
    return SATISFIED, "имя файла — не вердикт"
'''


def test_status_prefix_on_a_filename_is_not_a_carried_verdict(tmp_path):
    """`ds.STATUS_FILENAME` живёт в реестре по-настоящему (ADR-333: по СЛОВУ).

    Приставку он несёт, а вердиктом не является вовсе — это ИМЯ ФАЙЛА. Правило
    по приставке дало бы ложным членом пробу, судящую целиком сама.
    """
    row = _kind(tmp_path, STATUS_PREFIX_BUT_NOT_A_VERDICT,
                {"fn": "_probe_filename"}, "fn")
    assert row["kind"] == A.KIND_SELF_JUDGED
    assert "census.STATUS_FILENAME" in row["rejected_anchors"], (
        "цена словаря обязана печататься: читатель видит, что именно словарь "
        "отверг, а не верит ему на слово")


# --------------------------------------------------------------------------
# 3. ДВА ИМЕНИ — ОДИН ОБЪЕКТ: второй диалект вердикта узнаётся тоже
# --------------------------------------------------------------------------

SECOND_DIALECT = '''
def _probe_meter(arg):
    meter = _census_module()
    block = meter.run()["criterion"]
    status = block.get("status")
    if status == meter.CRITERION_NOT_SATISFIED:
        return NOT_SATISFIED, "перенос вторым диалектом"
    if status == meter.CRITERION_SATISFIED:
        return SATISFIED, "перенос вторым диалектом"
    return UNMEASURED, "статус не переносится"
'''


def test_the_second_dialect_of_the_verdict_vocabulary_is_recognised(tmp_path):
    """В дереве живут ОБА диалекта: `STATUS_OK` и `CRITERION_SATISFIED`.

    Правило по приставке `STATUS_` потеряло бы три пробы из восьми — и потеря
    была бы молчаливой: они встали бы в «судят сами», то есть в род, который
    читателя никуда не посылает.
    """
    row = _kind(tmp_path, SECOND_DIALECT, {"m": "_probe_meter"}, "m")
    assert row["kind"] == A.KIND_TRANSCRIBED


# --------------------------------------------------------------------------
# 4. База сравнения обязана быть ЧУЖИМ ПРИБОРОМ, а не похожим именем
# --------------------------------------------------------------------------

LOOKS_LIKE_AN_INSTRUMENT = '''
class _Local:
    STATUS_OK = "ok"


def _probe_local(arg):
    census = _Local()
    if census.STATUS_OK == "ok":
        return SATISFIED, "свой объект, не прибор"
    return NOT_SATISFIED, "свой объект, не прибор"
'''


def test_a_verdict_constant_of_a_local_object_is_not_a_carried_verdict(tmp_path):
    """Имя `census` само ничего не доказывает — доказывает ДВЕРЬ ИМПОРТА.

    Признак «имя похоже на прибор» был бы той же претензией без сверки, против
    которой написан весь ряд (ADR-477: записка не есть инъекция).
    """
    row = _kind(tmp_path, LOOKS_LIKE_AN_INSTRUMENT, {"l": "_probe_local"}, "l")
    assert row["kind"] == A.KIND_SELF_JUDGED
    assert row["instruments"] == []


# --------------------------------------------------------------------------
# 5. РЕШАЮЩИЙ ПУТЬ: якорь на ТРЕТЬЕМ исходе переносом не является
# --------------------------------------------------------------------------

ANCHOR_ONLY_ON_THE_THIRD_OUTCOME = '''
def _probe_refusal_anchor(arg):
    census = _census_module()
    report = census.run()
    if report.get("status") == census.STATUS_UNMEASURED:
        return UNMEASURED, "прибор отказался мерить"
    rows = report.get("rows") or []
    if len(rows) > 2:
        return NOT_SATISFIED, "свой порог над числами прибора"
    return SATISFIED, "свой порог над числами прибора"
'''


def test_an_anchor_guarding_only_the_third_outcome_is_not_a_transfer(tmp_path):
    """Отказ по свежести есть у КАЖДОЙ пробы ряда — и он не делает её переносящей.

    Правило, читающее всё тело, назвало бы судящей самой даже `Economics`
    (у неё свой порог `DECISION_JOURNAL_MAX_AGE_D` — но он стои́т на третьем
    исходе). Признак надо брать у ПРЕДМЕТА, а не у окрестности (разбор ADR-558
    над `.replace`).
    """
    row = _kind(tmp_path, ANCHOR_ONLY_ON_THE_THIRD_OUTCOME,
                {"r": "_probe_refusal_anchor"}, "r")
    assert row["kind"] == A.KIND_SELF_JUDGED
    assert row["instruments"] == ["pkg.census_under_test"], (
        "прибор назван (числа его), а порог свой — именно эту пару читатель и "
        "обязан увидеть")


# --------------------------------------------------------------------------
# 6. ПРОВАЛИВАНИЕ: обе стороны правила, и обе измерены на живых формах
# --------------------------------------------------------------------------

FALLTHROUGH_AFTER_A_REFUSAL = '''
def _probe_fallthrough_refusal(arg):
    census = _census_module()
    report = census.run()
    bad = [r for r in report["rows"] if r["state"] == census.NOT_ARRIVED]
    if bad:
        return NOT_SATISFIED, "своё правило над построчным состоянием"
    if report["state"] == census.STATUS_UNMEASURED:
        return UNMEASURED, "прибор отказался"
    return SATISFIED, "своё правило: не доехавших нет"
'''

FALLTHROUGH_AFTER_A_DECISIVE_BRANCH = '''
def _probe_fallthrough_decisive(arg):
    census = _census_module()
    report = census.run()
    if report.get("status") != census.STATUS_OK:
        return NOT_SATISFIED, "перенос: прибор не сказал ОК"
    return SATISFIED, "перенос проваливанием: прибор сказал ОК"
'''


def test_falling_through_a_refusal_does_not_credit_the_instrument(tmp_path):
    """«Прибор не отказал» ≠ «прибор сказал ОК» — ИЗМЕРЕННЫЙ ложный член.

    Первая редакция правила считала охраной любой предшествующий `if` и назвала
    переносящей `pr_work_arrived_on_main`, чей `satisfied` стои́т за отказом
    прибора, а население `bad`/`blind` строится её собственным правилом.
    """
    row = _kind(tmp_path, FALLTHROUGH_AFTER_A_REFUSAL,
                {"f": "_probe_fallthrough_refusal"}, "f")
    assert row["kind"] == A.KIND_SELF_JUDGED


def test_falling_through_a_decisive_branch_does_credit_the_instrument(tmp_path):
    """Обратная сторона того же правила: иначе оно было бы проверено с одной.

    Односторонне проверенное правило — девятый по счёту выживший мутант этого
    ряда (ADR-558), поэтому контроль обязан быть в обе стороны.
    """
    row = _kind(tmp_path, FALLTHROUGH_AFTER_A_DECISIVE_BRANCH,
                {"f": "_probe_fallthrough_decisive"}, "f")
    assert row["kind"] == A.KIND_TRANSCRIBED


# --------------------------------------------------------------------------
# 7. СМЕШАННЫЙ род: читатель не может приписать строку никому
# --------------------------------------------------------------------------

MIXED = '''
def _probe_mixed(arg):
    census = _census_module()
    report = census.run()
    if report.get("status") == census.STATUS_CRITICAL:
        return NOT_SATISFIED, "перенос"
    rows = report.get("rows") or []
    if len(rows) > 2:
        return SATISFIED, "свой порог"
    return UNMEASURED, "нечем"
'''


def test_a_probe_that_carries_one_half_and_judges_the_other_is_named_mixed(tmp_path):
    row = _kind(tmp_path, MIXED, {"x": "_probe_mixed"}, "x")
    assert row["kind"] == A.KIND_MIXED
    assert row["reason"], "смешанный род обязан нести причину, а не один ярлык"


# --------------------------------------------------------------------------
# 8. ТРЕТИЙ ИСХОД прибора: непрочитанный путь ≠ «судит сама»
# --------------------------------------------------------------------------

UNREADABLE = '''
def _probe_unreadable(arg):
    table = {"a": SATISFIED}
    return table[arg], "вердикт собран в рантайме"
'''

NO_DECISIVE_RETURN = '''
def _probe_no_verdict(arg):
    return UNMEASURED, "эта проба не судит о критерии вовсе"
'''


def test_an_unreadable_decisive_path_is_the_third_outcome_not_self_judged(tmp_path):
    """Непрочитанное обязано быть ОТДЕЛЬНЫМ значением (инв. #17).

    Выдать «не прочитал» за «судит сама» значило бы послать читателя спорить с
    пробой о пороге, которого прибор не нашёл.
    """
    row = _kind(tmp_path, UNREADABLE, {"u": "_probe_unreadable"}, "u")
    assert row["kind"] == A.KIND_UNMEASURED
    assert "не разобран" in (row["reason"] or "")


def test_a_probe_without_a_decisive_return_is_unmeasured_with_a_reason(tmp_path):
    row = _kind(tmp_path, NO_DECISIVE_RETURN, {"n": "_probe_no_verdict"}, "n")
    assert row["kind"] == A.KIND_UNMEASURED
    assert "решающих возвратов" in (row["reason"] or "")


def test_a_probe_name_pointing_at_a_missing_function_is_unmeasured(tmp_path):
    row = _kind(tmp_path, SELF_JUDGED, {"ghost": "_probe_missing"}, "ghost")
    assert row["kind"] == A.KIND_UNMEASURED
    assert "_probe_missing" in (row["reason"] or "")


# --------------------------------------------------------------------------
# 9. ПОМОЩНИК: вердикт остаётся вердиктом того, кто его произвёл
# --------------------------------------------------------------------------

HELPER_REFUSES_ONLY = '''
def _liveness(data):
    if not data:
        return UNMEASURED, "дерево мёртвое"
    return None, ""


def _probe_with_refusing_helper(arg):
    census = _census_module()
    report = census.run()
    verdict, why = _liveness(report)
    if verdict is not None:
        return verdict, why
    if report.get("status") == census.STATUS_OK:
        return SATISFIED, "перенос"
    return NOT_SATISFIED, "перенос"
'''

HELPER_JUDGES = '''
def _judge(report):
    if len(report.get("rows") or []) > 2:
        return NOT_SATISFIED, "порог помощника"
    return None, ""


def _probe_with_judging_helper(arg):
    census = _census_module()
    report = census.run()
    if report.get("status") == census.STATUS_OK:
        verdict, why = _judge(report)
        if verdict is not None:
            return verdict, why
        return SATISFIED, "перенос"
    return UNMEASURED, "нечем"
'''


def test_a_helper_that_only_refuses_leaves_the_probe_a_pure_transfer(tmp_path):
    """Ровно форма проб `Risk`, `Anti-churn`, `Pre-trade safety` в дереве.

    Шаг в помощника НЕСУЩИЙ: без него нулевой слот `return verdict, why` стал бы
    «непрочитанным», и три настоящие привязки прибора ушли бы в третий исход
    ([[token-in-the-file-is-not-a-reader]]).
    """
    row = _kind(tmp_path, HELPER_REFUSES_ONLY,
                {"h": "_probe_with_refusing_helper"}, "h")
    assert row["kind"] == A.KIND_TRANSCRIBED


def test_a_verdict_produced_by_a_helper_is_credited_to_the_helper(tmp_path):
    """Якорь звавшего лишь ВПУСКАЛ к помощнику, вердикт произвёл помощник.

    Приписать такой `not_satisfied` прибору значило бы послать читателя спорить
    с прибором о пороге, который написан в теле модуля проб.
    """
    row = _kind(tmp_path, HELPER_JUDGES, {"h": "_probe_with_judging_helper"}, "h")
    assert row["kind"] == A.KIND_MIXED, (
        "один исход переносится, второй произведён помощником — читателю это "
        "обязано быть видно, а не слито в один ярлык")
    helper_sites = [s for s in row["sites"] if s["via"] == "_judge"]
    assert helper_sites and all(s["guard"] == A.GUARD_OWN for s in helper_sites)


# --------------------------------------------------------------------------
# 10. ВЛОЖЕННОЕ ОПРЕДЕЛЕНИЕ — своя область, а не возврат внешней пробы
# --------------------------------------------------------------------------

NESTED_DEF = '''
def _probe_with_nested(arg):
    census = _census_module()

    def _close(path):
        if path:
            return SATISFIED
        return NOT_SATISFIED

    report = census.run()
    if len(report.get("rows") or []) > 2:
        return NOT_SATISFIED, "свой порог"
    return SATISFIED, "свой порог"
'''


def test_returns_of_a_nested_definition_are_not_the_probes_verdicts(tmp_path):
    """У вложенного определения свой звавший: его исход — не исход пробы.

    Считать иначе значило бы приписать внешней мере чужой вердикт — и именно в
    таком вложенном шаге живёт дефект G126 п. 1 (`card_acceptance:2024`).
    """
    row = _kind(tmp_path, NESTED_DEF, {"n": "_probe_with_nested"}, "n")
    assert row["kind"] == A.KIND_SELF_JUDGED
    assert all(s["via"] != "_close" for s in row["sites"])
    assert row["decisive"] == 2, (
        "решающих мест у пробы ровно два — её собственные; четыре означало бы, "
        "что возвраты вложенного шага записаны внешней мере")


# --------------------------------------------------------------------------
# 11. Источник не прочитан — НЕ ИЗМЕРЕНО целиком, с ненулевым кодом
# --------------------------------------------------------------------------

def test_a_missing_source_refuses_loudly_and_never_returns_an_empty_tally(tmp_path):
    with pytest.raises(A.Unmeasured):
        A.measure(source=str(tmp_path / "нет-такого.py"))


def test_a_source_without_a_registry_refuses(tmp_path):
    path = tmp_path / "bare.py"
    path.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(A.Unmeasured) as exc:
        A.measure(source=str(path))
    assert "PROBES" in str(exc.value)


def test_exit_code_two_when_nothing_was_measured(tmp_path, capsys):
    code = A.main(["--source", str(tmp_path / "нет.py")])
    assert code == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_exit_code_one_when_a_kind_cannot_be_attributed(tmp_path, capsys):
    code = A.main(["--source", _source(tmp_path, MIXED, {"x": "_probe_mixed"})])
    assert code == 1


def test_exit_code_zero_when_every_kind_is_readable(tmp_path):
    code = A.main(["--source", _source(tmp_path, TRANSCRIBED + SELF_JUDGED,
                                       {"c": "_probe_carried", "o": "_probe_own"})])
    assert code == 0


def test_an_unknown_probe_name_is_none_not_a_made_up_kind(tmp_path):
    report = A.measure(source=_source(tmp_path, SELF_JUDGED, {"own": "_probe_own"}))
    assert A.authorship_of("нет-такой-пробы", report=report) is None


# --------------------------------------------------------------------------
# 12. ЖИВОЕ ДЕРЕВО: разбор обязан совпадать с настоящим реестром
# --------------------------------------------------------------------------

def test_the_parsed_registry_matches_the_imported_one():
    """Разбор и импорт обязаны видеть ОДНО население.

    Разбор берётся вместо импорта намеренно (тела проб читаются из того же
    текста), но расхождение двух способов прочесть один реестр означало бы, что
    прибор судит о паре «реестр одного дерева × тело другого» — и молчит об этом.
    """
    report = A.measure()
    assert report["population"] == len(PROBES)
    assert {r["probe"] for r in report["probes"]} == set(PROBES)


def test_every_registered_probe_gets_exactly_one_kind():
    report = A.measure()
    assert sum(report["counts"].values()) == report["population"]
    assert all(r["kind"] in A.KIND_RU for r in report["probes"])


def test_the_live_tree_has_probes_of_both_kinds():
    """Население обоих родов — ЗАМЕР, а не литерал.

    Числа заказа («две привязки») были замером своего дня и к этому дню устарели;
    закреплять их тестом значило бы перепечатать чужое число вместо своего
    прибора (`.claude/rules/site-numbers.md`). Закрепляется ФОРМА ответа: оба
    рода населены, и ни один род не выдуман.
    """
    report = A.measure()
    assert report["counts"][A.KIND_TRANSCRIBED] > 0
    assert report["counts"][A.KIND_SELF_JUDGED] > 0


# --------------------------------------------------------------------------
# 13. ЧИТАТЕЛЬ: сводка §49 обязана НАЗЫВАТЬ чью меру она печатает
# --------------------------------------------------------------------------

BRANCH = "main"

SECTION = """49. Acceptance criteria
Работа считается выполненной только когда доказано следующее.
Economics
Решения используют net expected return, а не raw APY.


⸻


50. Definition of Done
"""


def _scene(tmp_path) -> str:
    root = tmp_path / "repo"
    (root / os.path.dirname(rollup.CARD_REL)).mkdir(parents=True)
    subprocess.run(["git", "init", "-b", BRANCH], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / rollup.CARD_REL).write_text(
        "---\ntitle: \"TASK\"\nstatus: in-progress\n---\n\n## Задание\n\nпреамбула"
        "\n\n\n⸻\n\n\n" + SECTION, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "card"], cwd=root, check=True,
                   capture_output=True)
    return str(root)


def _row(tmp_path, monkeypatch, probe: str, criterion: str = "Economics") -> dict:
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {criterion: [probe]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda spec: [])
    report = rollup.measure(_scene(tmp_path),
                            probe_runner=lambda spec, **kw: (rollup.UNMEASURED, "ф"))
    rows = [r for r in report["rows"] if r["criterion"] == criterion]
    assert len(rows) == 1
    return rows[0]


def test_the_rollup_names_whose_measure_produced_each_verdict(tmp_path, monkeypatch):
    """Вред заказа G96 п. 3 закрыт у ЧИТАТЕЛЯ, а не только у прибора.

    До этого строка `❌ НЕ ВЫПОЛНЕН Economics [economics_…]` несла два разных
    утверждения под одним видом, и читатель шёл не к тому адресату.
    """
    row = _row(tmp_path, monkeypatch, "economics_net_return_dominates_keep")
    assert row["measure"]["kind"] == A.KIND_TRANSCRIBED
    assert "keep_dominance_census" in " ".join(row["measure"]["instruments"])


def test_the_rollup_names_a_self_judged_probe_as_such(tmp_path, monkeypatch):
    row = _row(tmp_path, monkeypatch, "adapter_status_live_apy")
    assert row["measure"]["kind"] == A.KIND_SELF_JUDGED


def test_a_self_judged_probe_over_a_foreign_report_is_warned_about(tmp_path,
                                                                   monkeypatch,
                                                                   capsys):
    """Самый опасный для читателя род: числа прибора, порог свой.

    Заказ такого рода не предполагал вовсе — он делил реестр на два. Строка
    такой пробы ВЫГЛЯДИТ вердиктом прибора, и без предупреждения читатель спорил
    бы с прибором о пороге, которого у прибора нет.
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Economics": ["second_artifact_tvl_agrees"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda spec: [])
    monkeypatch.setattr(rollup, "run_probe", lambda spec, **kw: (rollup.UNMEASURED, "ф"))
    rollup.main(["--repo-root", _scene(tmp_path)])
    out = capsys.readouterr().out
    assert "МЕРА ·" in out
    assert "порог ЗДЕСЬ свой" in out


def test_the_rollup_refuses_the_kind_instead_of_inventing_self_judged(tmp_path,
                                                                      monkeypatch):
    """Прибор рода отказал ⇒ строка несёт НЕ ИЗМЕРЕНО, а не «своя мера».

    Подмена третьего исхода вторым родом тише красного и потому опаснее: сводка
    выглядела бы полной (инв. #17).
    """
    def _refuse(**kw):
        raise A.Unmeasured("источник рода не прочитан (контроль)")

    monkeypatch.setattr(rollup.authorship, "measure", _refuse)
    row = _row(tmp_path, monkeypatch, "economics_net_return_dominates_keep")
    assert row["measure"]["kind"] == A.KIND_UNMEASURED
    assert "контроль" in row["measure"]["reason"]


def test_the_kind_is_read_from_the_module_the_probes_came_from(tmp_path,
                                                               monkeypatch):
    """Адрес разбора — `card_acceptance.__file__`, а НЕ `--repo-root`.

    Пробы приходят из `sys.path`, карточка — из названного дерева. Прочитать род
    из второго значило бы судить о паре «реестр одного дерева × тело другого» —
    тот самый `split_tree`, про который сводка уже говорит вслух.
    """
    seen = {}

    real = A.measure

    def _spy(repo_root=None, *, source=None):
        seen["source"] = source
        return real(repo_root, source=source)

    monkeypatch.setattr(rollup.authorship, "measure", _spy)
    row = _row(tmp_path, monkeypatch, "economics_net_return_dominates_keep")
    assert seen["source"] == rollup._card_acceptance.__file__
    assert str(tmp_path) not in str(seen["source"])
    assert row["measure"]["kind"] == A.KIND_TRANSCRIBED


# --------------------------------------------------------------------------
# 14. Шесть тестов ниже названы по ВЫЖИВШИМ МУТАНТАМ первого прохода. Каждый —
# дыра СЦЕНЫ, не прибора: правило было верным, а предъявить ему форму, на
# которой ослабление видно, сцена не умела. Десятый подряд случай этого рода в
# ряду (ADR-558), и порядок тот же — закрывать поимённо, а не «усилить вообще».
# --------------------------------------------------------------------------

SUBSTRING_NOT_A_WORD = '''
def _probe_bookkeeping(arg):
    census = _census_module()
    if census.STATUS_BOOKKEEPING == "on":
        return SATISFIED, "не вердикт"
    return NOT_SATISFIED, "не вердикт"
'''


def test_a_verdict_word_inside_another_word_is_not_a_verdict(tmp_path):
    """`STATUS_BOOKKEEPING` СОДЕРЖИТ «OK» — и вердиктом не является.

    Ровно разбор ADR-333 («permutation содержит mutation»), и без этой сцены
    подмена сверки по слову на сверку подстрокой проходила незамеченной: в
    `STATUS_FILENAME` ни одно слово вердикта подстрокой не входит, поэтому старый
    контроль был зелен при ОБОИХ правилах.
    """
    row = _kind(tmp_path, SUBSTRING_NOT_A_WORD, {"b": "_probe_bookkeeping"}, "b")
    assert row["kind"] == A.KIND_SELF_JUDGED
    assert "census.STATUS_BOOKKEEPING" in row["rejected_anchors"]


NAMED_LIKE_A_LOADER_BUT_IMPORTS_NOTHING = '''
class _Shelf:
    STATUS_OK = "ok"


def _shelf_module():
    return _Shelf()


def _probe_shelf(arg):
    census = _shelf_module()
    if census.STATUS_OK == "ok":
        return SATISFIED, "полка, а не прибор"
    return NOT_SATISFIED, "полка, а не прибор"
'''


def test_a_function_named_like_a_loader_without_an_import_door_is_not_an_instrument(
        tmp_path):
    """Признак прибора — ДВЕРЬ ИМПОРТА, а не суффикс `_module` в имени.

    Все настоящие загрузчики дерева названы `_*_module`, поэтому подмена признака
    на проверку имени была зелена на каждой прежней сцене — и означала бы ровно то,
    против чего написан ряд: претензию вместо сверки.
    """
    row = _kind(tmp_path, NAMED_LIKE_A_LOADER_BUT_IMPORTS_NOTHING,
                {"s": "_probe_shelf"}, "s")
    assert row["kind"] == A.KIND_SELF_JUDGED
    assert row["instruments"] == []


VERDICT_TAKEN_FROM_THE_SECOND_SLOT = '''
def _helper(data):
    if not data:
        return UNMEASURED, "нечем"
    return None, ""


def _probe_slot_confusion(arg):
    why, verdict = _helper(arg)
    return verdict, why
'''


def test_a_name_bound_to_the_second_slot_is_not_read_as_a_verdict(tmp_path):
    """Имя из НЕнулевого слота несёт причину, а не статус.

    Судить о строке причины как о вердикте значило бы приписать пробе род по
    чужому значению; честный исход — третий (`unmeasured`), и он обязан быть
    отличим от обоих родов.
    """
    row = _kind(tmp_path, VERDICT_TAKEN_FROM_THE_SECOND_SLOT,
                {"s": "_probe_slot_confusion"}, "s")
    assert row["kind"] == A.KIND_UNMEASURED
    assert "не разобран" in (row["reason"] or "")


def test_a_syntactically_broken_source_names_the_parse_failure(tmp_path):
    """«Файл не разобран» и «реестра в файле нет» — РАЗНЫЕ причины.

    Оба исхода — отказ, и поэтому проверка «отказал ли» их не различает: подмена,
    превращавшая нечитаемый файл в пустое дерево, оставляла отказ на месте и
    меняла лишь ПРИЧИНУ. Читателю же причина и нужна — она говорит, что починить.
    """
    path = tmp_path / "broken.py"
    path.write_text("def сломано(:\n", encoding="utf-8")
    with pytest.raises(A.Unmeasured) as exc:
        A.measure(source=str(path))
    assert "не разобран" in str(exc.value)
    assert "PROBES" not in str(exc.value)


def test_two_registry_names_on_one_function_are_both_measured(tmp_path):
    """Два имени реестра на одной функции — законная форма, и оба обязаны быть.

    Схлопнуть их молча значило бы уменьшить население: сводка §49 считает две
    пробы на одном критерии СТОЛКНОВЕНИЕМ и говорит о нём вслух, а исчезнувшая
    из разбора проба стала бы «нет такой», то есть третьим исходом по мёртвой
    ссылке.
    """
    report = A.measure(source=_source(tmp_path, SELF_JUDGED,
                                      {"one": "_probe_own", "two": "_probe_own"}))
    assert report["population"] == 2
    assert {r["probe"] for r in report["probes"]} == {"one", "two"}
    assert {r["kind"] for r in report["probes"]} == {A.KIND_SELF_JUDGED}


def test_the_rollup_refuses_a_probe_absent_from_the_parsed_registry(tmp_path,
                                                                    monkeypatch):
    """Объявленной мерой может стоять имя, которого в разборе НЕТ.

    Тогда род её вердикта не измерен — и выдать за него род ПЕРВОЙ пробы разбора
    (или упасть) значило бы ответить читателю о чужой строке. Это не
    гипотетическая форма: сводка уже знает «привязка МИМО населения».
    """
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Economics": ["пробы-с-таким-именем-нет"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda spec: [])
    report = rollup.measure(_scene(tmp_path),
                            probe_runner=lambda spec, **kw: (rollup.UNMEASURED, "ф"))
    row = [r for r in report["rows"] if r["criterion"] == "Economics"][0]
    assert row["measure"]["kind"] == A.KIND_UNMEASURED
    assert "пробы-с-таким-именем-нет" in row["measure"]["reason"]


DELEGATING_WRAPPER_WITHOUT_AN_IMPORT_DOOR = '''
class _Shelf:
    STATUS_OK = "ok"


def _inner_module():
    return _Shelf()


def _wrapper_module():
    return _inner_module()


def _probe_wrapper(arg):
    census = _wrapper_module()
    if census.STATUS_OK == "ok":
        return SATISFIED, "обёртка над полкой, а не прибор"
    return NOT_SATISFIED, "обёртка над полкой, а не прибор"
'''


def test_calling_something_named_like_a_loader_is_not_an_import_door(tmp_path):
    """Седьмой выживший мутант: признак сместился с ДВЕРИ на имя ВЫЗВАННОГО.

    Форма настоящая — загрузчик, делегирующий другому загрузчику. Подмена
    `fname in ("import_module", …)` → `fname.endswith("_module")` объявляет
    прибором любую функцию, которая ЗОВЁТ что-то с таким суффиксом, и на живом
    дереве результата не меняет (`importlib.import_module` сам оканчивается на
    `_module`) — поэтому замечается она только здесь. Ослабление настоящее:
    цепочка обёрток без единого импорта получала бы ярлык прибора.
    """
    row = _kind(tmp_path, DELEGATING_WRAPPER_WITHOUT_AN_IMPORT_DOOR,
                {"w": "_probe_wrapper"}, "w")
    assert row["kind"] == A.KIND_SELF_JUDGED
    assert row["instruments"] == []
