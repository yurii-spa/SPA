"""Приёмка прибора «меняет ли расширение населения вердикт §49» (заказ G107 п. 1).

У каждого звена здесь ЕСТЬ обратная сторона с НАЗВАННЫМ звеном: порви его — и
находки не будет. Проверка, никогда не видевшая настоящей поломки, есть
украшение (`.claude/rules/deployment.md`).

Литеральных дат, литеральных pid и ``git init`` в батарее нет ПО ПОСТРОЕНИЮ:
входов у прибора ровно два — ПУТЬ дерева и ПУТЬ записи, — поэтому ни часы, ни
личность процесса, ни git-окружение он не спрашивает ни у машины, ни у календаря.
"""
from __future__ import annotations

import ast
import json
import pathlib
import xml.etree.ElementTree as ET

from spa_core.monitoring import membership_reach_census as reach
from spa_core.monitoring import no_regression_census as nrc
from spa_core.monitoring import verdict_population_shift as vps
from spa_core.monitoring.verdict_population_shift import (
    CHANGED,
    FAILED,
    OUTCOMES,
    PASSED,
    SAME,
    find_records,
    format_report,
    main,
    measure,
    verdict,
)

MODULE_PATH = pathlib.Path(vps.__file__)

PASS, FAIL, SKIP = "passed", "failure", "skipped"


# ───────────────────────────────── сцена ──────────────────────────────────────

def _tree(tmp_path: pathlib.Path, files: dict[str, str]) -> str:
    """Одноразовое дерево. Единственный вход прибора — его ПУТЬ."""
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return str(tmp_path)


def _record(path: pathlib.Path, cases: dict[str, str],
            hostname: str | None = "сцена", timestamp: str | None = None) -> str:
    """junit-запись в том же виде, в каком её пишет наш pytest (``xunit2``).

    Атрибута ``file`` здесь НЕТ намеренно: умолчание pytest его не пишет, и
    запись, у которой он есть, не воспроизводила бы нашу настоящую запись.
    """
    suite = ET.Element("testsuite", {"name": "pytest", "tests": str(len(cases))})
    if hostname is not None:
        suite.set("hostname", hostname)
    if timestamp is not None:
        suite.set("timestamp", timestamp)
    for rel, kind in cases.items():
        classname = rel[: -len(".py")].replace("/", ".")
        case = ET.SubElement(suite, "testcase",
                             {"classname": classname, "name": "test_one"})
        if kind != PASS:
            ET.SubElement(case, kind, {"message": "сцена"})
    root = ET.Element("testsuites")
    root.append(suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return str(path)


#: Сцена-основа: у поверхности ``risk`` есть ОДИН объявленный член (видит правило)
#: и ОДИН член через помощника (правило не видит).
def _scene(tmp_path: pathlib.Path, *, direct: str = PASS, helper: str = FAIL,
           extra: dict[str, str] | None = None) -> tuple[str, str]:
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "scripts/__init__.py": "",
        "scripts/helper.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_via_helper.py": "import scripts.helper\n",
    })
    cases = {"spa_core/tests/test_direct.py": direct,
             "spa_core/tests/test_via_helper.py": helper}
    cases.update(extra or {})
    rec = _record(tmp_path / "reports" / "junit-scene.xml", cases)
    return root, rec


# ─────────────────── ОТВЕТ ЗАКАЗА и обратная сторона каждого звена ───────────

def test_a_failure_the_rule_cannot_see_changes_the_surface_verdict(tmp_path):
    """ОТВЕТ заказа: слепота правила СДВИГАЕТ вердикт, и это измерено записью.

    Объявленный член зелен, член через помощника КРАСЕН ⇒ правило говорит
    «регрессии нет», расширенное население — «регрессия есть»."""
    root, rec = _scene(tmp_path, direct=PASS, helper=FAIL)
    doc = measure(root, records=[rec])
    assert doc["measured"], doc.get("unmeasured_reason")
    assert doc["verdict_declared"] == nrc.NO_REGRESSION
    assert doc["verdict_widened"] == nrc.REGRESSION
    assert doc["shift"] == CHANGED
    assert doc["per_surface"]["risk"]["shift"] == CHANGED
    assert doc["counts"][FAILED] == 1
    assert verdict(doc) == "the_extension_changes_the_verdict"


def test_the_same_scene_with_a_green_helper_finds_nothing(tmp_path):
    """Обратная сторона: порви ПОЛОМКУ — и находки нет.

    Сцена отличается от предыдущей РОВНО исходом одного члена в записи, поэтому
    находка доказана исходом, а не формой дерева."""
    root, rec = _scene(tmp_path, direct=PASS, helper=PASS)
    doc = measure(root, records=[rec])
    assert doc["counts"][FAILED] == 0
    assert doc["shift"] == SAME
    assert doc["surfaces_changed"] == []
    assert verdict(doc) == "the_extension_changes_nothing"
    assert main(["--root", root, "--record", rec]) == 0


def test_a_direct_import_leaves_nothing_to_add(tmp_path):
    """Обратная сторона звена «через ПОМОЩНИКА»: убери помощника — и добавлять нечего.

    Тот же файл, но ввозящий поверхность НАПРЯМУЮ, попадает в население правила
    сам; расширять нечем, и это ТРЕТИЙ ИСХОД, а не «вердикт не меняется»."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
    })
    rec = _record(tmp_path / "reports" / "junit-scene.xml",
                  {"spa_core/tests/test_direct.py": FAIL})
    doc = measure(root, records=[rec])
    assert not doc["measured"]
    assert "не слепо ни на одной паре" in doc["unmeasured_reason"]
    assert main(["--root", root, "--record", rec]) == 2


def test_no_record_is_a_third_outcome_with_a_named_reason(tmp_path):
    """Обратная сторона звена ЗАПИСИ: §49 измеряется ТОЛЬКО записью.

    Записи нет ⇒ «НЕ ИЗМЕРЕНО» с причиной и ненулевой код возврата. Ноль здесь
    был бы fail-OPEN тише красного теста (урок `pyflakes`, #465)."""
    root, _rec = _scene(tmp_path)
    doc = measure(root, records=[])
    assert not doc["measured"]
    assert doc["unmeasured_reason"] == ("записи прогона не подано, а искать её "
                                       "не просили")
    assert verdict(doc) == "unmeasured"
    assert "НЕ ИЗМЕРЕНО" in format_report(doc)
    assert main(["--root", root, "--record", "/нет/такой/записи.xml"]) == 2


def test_a_missing_directory_and_an_empty_one_are_different_reasons(tmp_path):
    """Два разных третьих исхода поиска записи, и склеивать их нельзя (инв. #17).

    «Каталога нет» чинится тем, что запись с хоста никто не держит (заказы
    G106/G150); «каталог есть, записи нет» — прогоном. Один текст на оба случая
    увёл бы починку не туда."""
    absent_root = _tree(tmp_path / "absent", {"spa_core/tests/test_x.py": "\n"})
    empty_root = _tree(tmp_path / "empty", {"spa_core/tests/test_x.py": "\n"})
    (pathlib.Path(empty_root) / vps.RECORD_DIR).mkdir()

    _found_a, why_a = find_records(absent_root)
    _found_b, why_b = find_records(empty_root)
    assert why_a and why_b and why_a != why_b
    assert why_a == (f"каталога записи `{vps.RECORD_DIR}/` в дереве нет: запись "
                     "прогона на хосте не держит никто, а §49 измеряется ТОЛЬКО "
                     "записью")
    assert why_b == (f"каталог `{vps.RECORD_DIR}/` есть, но ни одного файла "
                     f"`{vps.RECORD_GLOB}` в нём нет")


def test_an_unreadable_record_is_named_not_counted_as_clean(tmp_path):
    """Запись, которую не разобрать, обязана быть НАЗВАНА, а не пропущена."""
    root, _rec = _scene(tmp_path)
    broken = tmp_path / "reports" / "junit-broken.xml"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("это не xml", encoding="utf-8")
    doc = measure(root, records=[str(broken)])
    assert not doc["measured"]
    assert doc["unmeasured_reason"].startswith("ни одна запись прогона не прочитана: ")
    assert "junit-broken.xml" in doc["unmeasured_reason"]

    second = tmp_path / "reports" / "junit-broken2.xml"
    second.write_text("тоже не xml", encoding="utf-8")
    both = measure(root, records=[str(broken), str(second)])["unmeasured_reason"]
    assert "junit-broken.xml" in both and "junit-broken2.xml" in both
    assert "; " in both, "две непрочитанные записи обязаны быть РАЗДЕЛЕНЫ"
    assert " — " in both, "у каждой названа СВОЯ причина"


# ──────────────── ось исхода: перечень ЗАКРЫТ, третьи исходы РАЗНЫЕ ──────────

def test_a_member_absent_from_the_record_is_not_counted_as_passed(tmp_path):
    """Члена в записи нет ⇒ НЕ ИЗМЕРЕНО С ИМЕНЕМ, а не «прошёл»."""
    root, _rec = _scene(tmp_path)
    rec = _record(tmp_path / "reports" / "junit-partial.xml",
                  {"spa_core/tests/test_direct.py": PASS})
    doc = measure(root, records=[rec])
    assert doc["counts"][nrc.ABSENT_FROM_RECORD] == 1
    assert doc["counts"][PASSED] == 0
    assert doc["counts"][FAILED] == 0


def test_all_cases_skipped_is_its_own_outcome(tmp_path):
    """Все случаи пропущены ⇒ свой третий исход, не «прошёл» и не «нет в записи»."""
    root, rec = _scene(tmp_path, direct=PASS, helper=SKIP)
    doc = measure(root, records=[rec])
    assert doc["counts"][nrc.ALL_CASES_SKIPPED] == 1
    assert doc["counts"][nrc.ABSENT_FROM_RECORD] == 0
    assert doc["counts"][PASSED] == 0


def test_the_two_third_outcomes_are_machine_distinguishable(tmp_path):
    """Разбирать исход ПРОЗОЙ запрещено (ADR-333): у исхода есть ИМЯ.

    До заказа G107 п. 1 «нет в записи» и «все пропущены» различались только
    текстом строки ``reason``. Имя — предпосылка того, что соседние два теста
    вообще могут о чём-то утверждать."""
    rec_doc = {"files": {"a.py": {"passed": 0, "skipped": 3, "bad": [],
                                  "records": []}}}
    judged = nrc.judge({"risk": ["a.py", "b.py"]}, rec_doc)
    kinds = {row["kind"] for row in judged["unmeasured_members"]}
    assert kinds == {nrc.ALL_CASES_SKIPPED, nrc.ABSENT_FROM_RECORD}


def test_the_outcome_list_is_closed_and_sums_to_the_added_population(tmp_path):
    """Сумма исходов равна добавленному населению — перечень ЗАКРЫТ (инв. #17).

    Сцена несёт ВСЕ ЧЕТЫРЕ исхода разом: иначе равенство держалось бы на
    ненаселённых слагаемых."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "scripts/__init__.py": "",
        "scripts/helper.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_red.py": "import scripts.helper\n",
        "spa_core/tests/test_green.py": "import scripts.helper\n",
        "spa_core/tests/test_skipped.py": "import scripts.helper\n",
        "spa_core/tests/test_absent.py": "import scripts.helper\n",
    })
    rec = _record(tmp_path / "reports" / "junit-all.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_red.py": FAIL,
        "spa_core/tests/test_green.py": PASS,
        "spa_core/tests/test_skipped.py": SKIP,
    })
    doc = measure(root, records=[rec])
    assert sum(doc["counts"].values()) == doc["pairs_added"] == 4
    assert [doc["counts"][name] for name in OUTCOMES] == [1, 1, 1, 1]


# ──────────── РАЗЛИЧИМОСТЬ: ярлык поверхности ≠ ярлык критерия ───────────────

def test_a_surface_label_changes_while_the_overall_label_does_not(tmp_path):
    """Настоящая поломка 08.10, воспроизведённая сценой: ярлык ЦЕЛИКОМ лжёт.

    У ``risk`` объявленный член уже красен, поэтому ярлык критерия равен
    ``REGRESSION`` и ДО, и ПОСЛЕ расширения. Прибор, сравнивающий только ярлык
    целиком, доложил бы «вердикт не меняется» — а у ``architecture`` он меняется
    с ``NO_REGRESSION`` на ``REGRESSION``. Это тот самый класс, ради которого ось
    вердикта спрашивается У КАЖДОЙ поверхности."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "build_architecture_manifest.py": "MANIFEST = {}\n",
        "scripts/__init__.py": "",
        "scripts/arch_helper.py": "import build_architecture_manifest\n",
        "spa_core/tests/test_direct_risk.py":
            "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct_arch.py": "import build_architecture_manifest\n",
        "spa_core/tests/test_via_helper_arch.py": "import scripts.arch_helper\n",
    })
    rec = _record(tmp_path / "reports" / "junit-two.xml", {
        "spa_core/tests/test_direct_risk.py": FAIL,
        "spa_core/tests/test_direct_arch.py": PASS,
        "spa_core/tests/test_via_helper_arch.py": FAIL,
    })
    doc = measure(root, records=[rec])
    assert doc["verdict_declared"] == doc["verdict_widened"] == nrc.REGRESSION
    assert doc["shift"] == SAME, "ярлык целиком и правда не меняется"
    assert doc["surfaces_changed"] == ["architecture"]
    assert doc["per_surface"]["architecture"]["shift"] == CHANGED
    assert doc["per_surface"]["risk"]["shift"] == SAME
    assert verdict(doc) == "the_extension_changes_the_verdict"
    assert main(["--root", root, "--record", rec]) == 1


def test_added_failures_without_any_label_change_have_their_own_verdict(tmp_path):
    """Третий вердикт прибора населён: поломка добавлена, ни один ярлык не сменился.

    Отличает «расширение ничего не меняет» от «меняет меру, но не ярлык»: у
    ``risk`` объявленный член уже красен, и добавленный красен тоже."""
    root, rec = _scene(tmp_path, direct=FAIL, helper=FAIL)
    doc = measure(root, records=[rec])
    assert doc["counts"][FAILED] == 1
    assert doc["shift"] == SAME and doc["surfaces_changed"] == []
    assert verdict(doc) == "the_extension_adds_failures_without_changing_a_label"
    assert main(["--root", root, "--record", rec]) == 1
    assert len(doc["files_failed_declared"]) == 1
    assert len(doc["files_failed_added_only"]) == 1


def test_the_count_of_broken_files_separates_seen_from_unseen(tmp_path):
    """«Правило видит N из M» — счёт ФАЙЛОВ, и пересчёт независим от пар.

    Один файл, дотягивающийся до ДВУХ поверхностей, даёт две пары и ОДИН файл;
    без этого различия «видит 2 из 13» читалось бы как число пар."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "build_architecture_manifest.py": "MANIFEST = {}\n",
        "scripts/__init__.py": "",
        "scripts/both.py": ("from spa_core.risk.policy import APPROVED\n"
                            "import build_architecture_manifest\n"),
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_both.py": "import scripts.both\n",
    })
    rec = _record(tmp_path / "reports" / "junit-both.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_both.py": FAIL,
    })
    doc = measure(root, records=[rec])
    assert doc["counts"][FAILED] == 2, "две ПАРЫ"
    assert len(doc["files_failed_added_only"]) == 1, "один ФАЙЛ"
    assert doc["files_failed_widened"] == 1


# ──────────────────────── пределы — ВХОДЫ, а не свойства ────────────────────

def test_the_depth_limit_is_an_input_that_decides_finding_or_price(tmp_path):
    """Предел глубины НАГРУЖЕН: он решает, находка это или цена предела."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "scripts/__init__.py": "",
        "scripts/a.py": "import scripts.b\n",
        "scripts/b.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_far.py": "import scripts.a\n",
    })
    rec = _record(tmp_path / "reports" / "junit-depth.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_far.py": FAIL,
    })
    assert measure(root, records=[rec], max_depth=2)["counts"][FAILED] == 1
    narrow = measure(root, records=[rec], max_depth=1)
    assert not narrow["measured"], "дорога длиной 2 за пределом 1 — добавлять нечего"


def test_the_price_of_the_limit_is_measured_only_when_asked(tmp_path):
    """Цена предела не подана ⇒ `not_asked`, и НОЛЬ не печатается.

    Ноль на неспрошенный вопрос есть ровно та склейка «не измерено = чисто»,
    против которой написан инв. #17."""
    root, rec = _scene(tmp_path)
    doc = measure(root, records=[rec])
    assert doc["price_of_the_limit"]["state"] == "not_asked"
    assert "ЦЕНА ПРЕДЕЛА" not in format_report(doc)
    assert "НЕ СПРОШЕНО" in format_report(doc)


def test_a_price_depth_below_the_finding_depth_is_unmeasured(tmp_path):
    """Предел цены не больше предела находок ⇒ мерить нечего, и это сказано."""
    root, rec = _scene(tmp_path)
    doc = measure(root, records=[rec], max_depth=3, price_depth=3)
    price = doc["price_of_the_limit"]
    assert set(price) == {"state", "why"}
    assert price["state"] == "unmeasured"
    assert price["why"] == ("предел цены 3 не больше предела находок 3 — мерить "
                            "нечего")


def test_a_failure_beyond_the_limit_is_counted_as_the_price(tmp_path):
    """Отрезанная пределом пара, которая УПАЛА, есть цена предела — числом."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "scripts/__init__.py": "",
        "scripts/a.py": "import scripts.b\n",
        "scripts/b.py": "import scripts.c\n",
        "scripts/c.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_near.py": "import scripts.c\n",
        "spa_core/tests/test_far.py": "import scripts.a\n",
    })
    rec = _record(tmp_path / "reports" / "junit-price.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_near.py": PASS,
        "spa_core/tests/test_far.py": FAIL,
    })
    doc = measure(root, records=[rec], max_depth=1, price_depth=9)
    price = doc["price_of_the_limit"]
    assert price["state"] == "measured"
    assert price["pairs"] == 1 and price["counts"][FAILED] == 1
    assert "ЦЕНА ПРЕДЕЛА" in format_report(doc)


def test_a_green_pair_beyond_the_limit_costs_nothing_but_is_still_counted(tmp_path):
    """Обратная сторона цены: пара за пределом зелена ⇒ пар > 0, поломок 0."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "scripts/__init__.py": "",
        "scripts/a.py": "import scripts.b\n",
        "scripts/b.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_near.py": "import scripts.b\n",
        "spa_core/tests/test_far.py": "import scripts.a\n",
    })
    rec = _record(tmp_path / "reports" / "junit-price2.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_near.py": FAIL,
        "spa_core/tests/test_far.py": PASS,
    })
    doc = measure(root, records=[rec], max_depth=1, price_depth=9)
    price = doc["price_of_the_limit"]
    assert price["pairs"] == 1 and price["counts"][FAILED] == 0
    assert price["counts"][PASSED] == 1


# ───────────── связь записи с деревом — ЧИСЛА, а не утверждение ─────────────

def test_the_binding_numbers_are_zero_when_tree_and_record_agree(tmp_path):
    """Согласие дерева и записи — ИЗМЕРЕНО, а не объявлено подписью."""
    root, rec = _scene(tmp_path)
    b = measure(root, records=[rec])["binding"]
    assert b["tree_tests_absent_from_record"] == []
    assert b["cases_without_file"] == 0
    assert b["record_files"] == 2 and b["tree_tests"] == 2


def test_a_record_from_another_slice_shows_up_in_both_binding_numbers(tmp_path):
    """Разъехавшийся срез НАЗВАН с ОБЕИХ сторон: дерева и записи.

    Ровно это и случилось у настоящего замера: тест, рождённый ПОСЛЕ записи,
    читался как «не дошёл до вердикта». Со стороны записи сторона другая, и
    КОНТРОЛЬ нашёл это за меня: случай из чужого срезa не попадает в
    ``record["files"]`` вовсе (``_file_of_case`` привязывает ПО СУЩЕСТВОВАНИЮ
    файла), поэтому его видно только счётчиком ``cases_without_file`` — поле
    «файл записи, которого нет в дереве» было бы пусто по построению."""
    root, _rec = _scene(tmp_path)
    rec = _record(tmp_path / "reports" / "junit-other.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_gone.py": PASS,
    })
    b = measure(root, records=[rec])["binding"]
    assert b["cases_without_file"] == 1, "сторона ЗАПИСИ"
    assert b["tree_tests_absent_from_record"] == ["spa_core/tests/test_via_helper.py"], \
        "сторона ДЕРЕВА"
    assert "spa_core/tests/test_gone.py" not in b["tree_tests_absent_from_record"]


def test_the_origin_of_the_record_is_read_not_invented(tmp_path):
    """``hostname`` берётся у записи; его отсутствие НАЗЫВАЕТСЯ, а не выдумывается."""
    root, _rec = _scene(tmp_path)
    anonymous = _record(tmp_path / "reports" / "junit-anon.xml",
                        {"spa_core/tests/test_direct.py": PASS,
                         "spa_core/tests/test_via_helper.py": FAIL},
                        hostname=None)
    doc = measure(root, records=[anonymous])
    assert doc["binding"]["records_meta"][0]["hostname"] is None
    assert doc["binding"]["records_meta"][0]["timestamp"] is None
    report = format_report(doc)
    assert "хост НЕ НАЗВАН" in report
    assert "время НЕ НАЗВАНО" in report, "вторая отметка названа своим отсутствием"

    named = measure(root, records=[_record(
        tmp_path / "reports" / "junit-named.xml",
        {"spa_core/tests/test_direct.py": PASS,
         "spa_core/tests/test_via_helper.py": FAIL}, hostname="машина-сцены",
        timestamp="отметка-сцены")])
    report = format_report(named)
    assert "машина-сцены@отметка-сцены" in report
    assert "НЕ НАЗВАН" not in report


# ─────────── контроль, который прибор несёт сам: двойной счёт ────────────────

def test_an_overlap_between_the_two_populations_is_named(tmp_path, monkeypatch):
    """Пересечение населений ПУСТО по построению — и измеряется, а не полагается.

    Непустое пересечение означало бы двойной счёт одного члена, то есть «ярлык
    сменился» могло бы быть следствием арифметики, а не записи. Подменяется ВХОД
    прибора (перечень дорог соседа), а не его собственный счёт."""
    root, rec = _scene(tmp_path)
    real = reach.measure

    def _with_overlap(repo_root, max_depth=reach.MAX_DEPTH, graph=None):
        doc = real(repo_root, max_depth=max_depth, graph=graph)
        doc["findings"] = doc["findings"] + [
            {"file": "spa_core/tests/test_direct.py", "surface": "risk",
             "depth": 1, "chain": ["spa_core/tests/test_direct.py"]}]
        return doc

    monkeypatch.setattr(reach, "measure", _with_overlap)
    doc = measure(root, records=[rec])
    assert doc["overlap"] == ["risk::spa_core/tests/test_direct.py"]
    assert "посчитан дважды" in format_report(doc)


def test_the_clean_scene_reports_no_overlap(tmp_path):
    """Обратная сторона: на целой сцене пересечения нет, и об этом не кричат."""
    root, rec = _scene(tmp_path)
    doc = measure(root, records=[rec])
    assert doc["overlap"] == []
    assert "посчитан дважды" not in format_report(doc)


# ─────────── нижняя граница названа нижней, и цены взяты у соседа ───────────

def test_the_finding_is_printed_as_a_lower_bound_with_three_prices(tmp_path):
    """Ноль находок обязан называться нижней границей — с ТРЕМЯ ценами (ADR-528)."""
    root, rec = _scene(tmp_path, helper=PASS)
    doc = measure(root, records=[rec])
    assert doc["counts"][FAILED] == 0
    report = format_report(doc)
    assert "НИЖНЯЯ ГРАНИЦА" in report
    assert set(doc["lower_bound_prices"]) == {
        "pairs_beyond_depth", "name_outside_tree", "name_unresolved"}


def test_the_prices_come_from_the_neighbour_not_from_a_second_count(tmp_path):
    """Цены — ЧИСЛА соседа, а не свой пересчёт: вторая копия разошлась бы молча."""
    root, rec = _scene(tmp_path)
    doc = measure(root, records=[rec])
    theirs = reach.measure(root)
    assert doc["lower_bound_prices"]["pairs_beyond_depth"] == \
        theirs["counts"][reach.BEYOND]
    assert doc["lower_bound_prices"]["name_outside_tree"] == \
        theirs["name_counts"][reach.NAME_OUTSIDE]


# ──────────────────── правило вердикта — ОДНА копия (ADR-522) ───────────────

def test_the_verdict_rule_is_the_neighbours_own_function(tmp_path):
    """Вердикт считает ``no_regression_census.judge`` — тот же, которым критерий
    считает себя. Своя копия («есть `bad` ⇒ упал») разошлась бы при первой правке
    соседа и дала бы два разных вердикта у одного критерия."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and (node.module or "").endswith("no_regression_census")
                for alias in node.names}
    assert "judge" in imported, "вердикт обязан браться у соседа"
    body = source.split('"""', 2)[-1]
    assert '"bad"' not in body, "своя классификация исхода = вторая копия правила"
    assert "ET." not in body, "свой разбор записи = вторая копия чтения"


def test_the_declared_population_is_the_neighbours_own(tmp_path):
    """Население критерия НЕ пересчитывается здесь: оно берётся у ``population``."""
    root, rec = _scene(tmp_path)
    doc = measure(root, records=[rec])
    theirs = nrc.population(root)
    assert doc["pairs_declared"] == sum(len(s["files"])
                                        for s in theirs["surfaces"].values())


def test_the_criterion_population_is_not_widened_by_this_measurement(tmp_path):
    """Заказ запрещает расширять население соседа замером — проверено ИСХОДОМ.

    Население критерия до и после прогона прибора обязано совпасть, и вердикт
    объявленного населения обязан остаться вердиктом объявленного."""
    root, rec = _scene(tmp_path)
    before = nrc.population(root)
    judged_before = nrc.judge({n: list(s["files"])
                               for n, s in before["surfaces"].items()},
                              nrc.read_record([rec], repo_root=root))
    doc = measure(root, records=[rec])
    after = nrc.population(root)
    assert {n: sorted(s["files"]) for n, s in before["surfaces"].items()} == \
        {n: sorted(s["files"]) for n, s in after["surfaces"].items()}
    assert judged_before["verdict"] == nrc.NO_REGRESSION
    assert doc["verdict_declared"] == nrc.NO_REGRESSION

    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("DECLARED_SURFACES[", "DECLARED_SURFACES.update",
                      "TEST_ROOTS ="):
        assert forbidden not in source, "прибор не вправе править объявление соседа"


# ─────────────────────── проводка: у находки есть ЧИТАТЕЛЬ ──────────────────

def _office_aliases(module_suffix: str) -> tuple[set[str], list[ast.Call]]:
    """Имена, под которыми шаг 0-офис ввёз модуль, и все его вызовы.

    Ищется ФОРМА вызова, а не имя в тексте: имя поймало бы собственный
    комментарий этой же секции (урок ADR-414), а зелёный храповик проводки
    считает импорт вызовом (урок ADR-547)."""
    office = MODULE_PATH.parents[2] / "scripts" / "consume_office_reports.py"
    tree = ast.parse(office.read_text(encoding="utf-8"))
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and node.module.endswith(module_suffix):
            aliases |= {a.asname or a.name for a in node.names}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    return aliases, calls


def test_the_office_step_calls_the_instrument_and_prints_it():
    """Прибор без артефакта имеет РОВНО одного читателя — шаг 0-офис."""
    aliases, calls = _office_aliases("verdict_population_shift")
    assert aliases, "шаг 0-офис не ввозит прибор вовсе"
    called = {c.func.id for c in calls
              if isinstance(c.func, ast.Name) and c.func.id in aliases}
    assert len(called) == 2, (
        f"офис зовёт {sorted(called)}: нужны и замер, и отрисовка — открыть "
        "артефакт и ничего не напечатать значит прочитать его вхолостую")


def test_the_instrument_is_not_declared_as_an_artifact_producer():
    """ADR-524: артефакт этого прибора стал бы операндом следующего замера."""
    manifest = MODULE_PATH.parents[2] / "architecture" / "manifest.json"
    text = manifest.read_text(encoding="utf-8") if manifest.is_file() else "{}"
    assert "verdict_population_shift" not in json.dumps(json.loads(text))


def test_the_instrument_writes_nothing_and_runs_nothing(tmp_path):
    """Прибор только ЧИТАЕТ: ни записи на диск, ни запуска pytest (инв. #16)."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]
    for forbidden in ("atomic_save", "subprocess", "open(", ".write_text(",
                      "pytest.main"):
        assert forbidden not in body, f"прибор не вправе {forbidden}"


def test_the_record_dir_is_the_one_the_workflows_declare():
    """Каталог записи — ОДНА копия пути с воркфлоу, иначе разойдутся молча."""
    workflows = MODULE_PATH.parents[2] / ".github" / "workflows"
    texts = [p.read_text(encoding="utf-8")
             for p in workflows.glob("*.yml")] if workflows.is_dir() else []
    assert texts, "воркфлоу не прочитаны — предпосылка НЕ ОБЕСПЕЧЕНА"
    assert any(f"{vps.RECORD_DIR}/junit-" in text for text in texts), (
        f"ни один воркфлоу не кладёт запись в `{vps.RECORD_DIR}/`")


# ─────────────────────────── коды возврата ──────────────────────────────────

def test_every_verdict_has_its_own_exit_code(tmp_path, capsys):
    """Четыре вердикта — три разных кода; «не измерено» никогда не ноль."""
    root, rec = _scene(tmp_path, direct=PASS, helper=FAIL)
    assert main(["--root", root, "--record", rec]) == 1
    root2, rec2 = _scene(tmp_path / "second", direct=PASS, helper=PASS)
    assert main(["--root", root2, "--record", rec2]) == 0
    assert main(["--root", root2, "--record", "/нет.xml"]) == 2
    capsys.readouterr()


def test_the_json_form_carries_the_same_verdict(tmp_path, capsys):
    """``--json`` отдаёт тот же документ, а не вторую редакцию вердикта."""
    root, rec = _scene(tmp_path, direct=PASS, helper=FAIL)
    assert main(["--root", root, "--record", rec, "--json"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["surfaces_changed"] == ["risk"]
    assert doc["counts"][FAILED] == 1


def test_an_empty_tree_is_unmeasured_not_clean(tmp_path):
    """Пустое дерево ⇒ НЕ ИЗМЕРЕНО, а не «изменений нет» (fail-OPEN тише красного)."""
    empty = str(tmp_path / "void")
    pathlib.Path(empty).mkdir()
    rec = _record(tmp_path / "reports" / "junit-void.xml", {})
    doc = measure(empty, records=[rec])
    assert not doc["measured"] and doc["unmeasured_reason"]
    assert verdict(doc) == "unmeasured"


# ══════════════════════════════════════════════════════════════════════════════
# Контроли, добавленные ПО ИСХОДУ мутационного замера (цикл #810)
#
# Первый замер: 241 применено · 177 убито · **64 выжило** при ЗЕЛЁНОМ контроле на
# шум пересборки — то есть замер честный, и он говорит, что батарея выше дырява.
# Каждый тест ниже убивает НАЗВАННЫЙ выживший мутант, а не «добавляет покрытие».
# ══════════════════════════════════════════════════════════════════════════════

def test_the_published_document_carries_exactly_the_declared_keys(tmp_path):
    """Подмена ИМЕНИ ключа вердикта не меняет — её видно только схемой документа.

    Убивает семью мутантов вида ``str#515 'repo_root'->mutated``: писатель и
    читатель переименовываются ВМЕСТЕ, поэтому поведение внутри файла то же, а
    опубликованный документ (`--json`, шаг 0-офис) становится другим МОЛЧА —
    урок #786/ADR-581."""
    root, rec = _scene(tmp_path)
    doc = measure(root, records=[rec], price_depth=9)
    assert set(doc) == {
        "repo_root", "max_depth", "price_depth", "records",
        "record_search_reason", "records_read", "records_unread",
        "measured", "unmeasured_reason", "pairs_declared", "pairs_added",
        "counts", "findings", "per_surface", "verdict_declared",
        "verdict_widened", "shift", "surfaces_changed",
        "files_failed_declared", "files_failed_added_only",
        "files_failed_widened", "overlap", "lower_bound_prices",
        "price_of_the_limit", "binding",
    }
    assert set(doc["per_surface"]["risk"]) == {
        "population_declared", "population_added", "verdict_declared",
        "verdict_widened", "shift", "failed_added"}
    assert set(doc["price_of_the_limit"]) == {
        "state", "price_depth", "pairs", "counts", "failed"}
    assert set(doc["binding"]) == {
        "record_files", "tree_tests", "tree_tests_absent_from_record",
        "cases_without_file", "records_meta"}

    nothing = measure(root, records=[])
    assert set(nothing) == {"repo_root", "max_depth", "price_depth", "records",
                            "record_search_reason", "measured",
                            "unmeasured_reason"}


def test_the_declared_vocabulary_is_literal(tmp_path):
    """Имена исходов и ярлыков — опубликованный СЛОВАРЬ, а не внутренние метки.

    Убивает ``str#49 'failed_in_the_record'``, ``str#51``, ``str#56``, ``str#58``:
    их читает человек в отчёте 0-офиса и машина в `--json`, поэтому переименование
    есть смена контракта, а не правка написания."""
    assert FAILED == "failed_in_the_record"
    assert PASSED == "passed_in_the_record"
    assert SAME == "verdict_label_unchanged"
    assert CHANGED == "verdict_label_changes"
    assert nrc.ABSENT_FROM_RECORD == "absent_from_the_record"
    assert nrc.ALL_CASES_SKIPPED == "all_cases_skipped"
    assert OUTCOMES == (FAILED, PASSED, nrc.ABSENT_FROM_RECORD,
                        nrc.ALL_CASES_SKIPPED)

    root, rec = _scene(tmp_path)
    assert verdict(measure(root, records=[rec])) == \
        "the_extension_changes_the_verdict"
    assert verdict(measure(root, records=[])) == "unmeasured"


def test_the_record_glob_matches_the_name_the_workflow_writes():
    """Маска записи обязана ЛОВИТЬ настоящее имя, а не просто существовать.

    Убивает ``str#47 'junit-*.xml'->mutated``: сосед-тест сверяет КАТАЛОГ, а маска
    могла разойтись с именем молча — и прибор доложил бы «записи нет» на дереве,
    где она лежит."""
    import fnmatch
    for name in ("junit-tests.xml", "junit-spa_core.xml", "junit-scripts.xml"):
        assert fnmatch.fnmatch(name, vps.RECORD_GLOB), name
    assert not fnmatch.fnmatch("stream-spa_core.jsonl", vps.RECORD_GLOB)


def test_an_unmeasured_road_census_stops_the_measurement_by_either_leg(
        tmp_path, monkeypatch):
    """У отказа дорог ДВЕ ноги, и каждая обязана остановить замер ОДНА.

    Убивает ``bool#271 Or-flip`` и семью строк того же возврата
    (``str#1029/1032/1033/1521/2201``, ``const#1035``, ``bool#1523``): с ``and``
    замер пошёл бы дальше на НЕИЗМЕРЕННЫХ дорогах. Подменяется ВХОД прибора —
    документ соседа, — а не его собственный счёт."""
    root, rec = _scene(tmp_path)
    real = reach.measure

    for leg, patched, expected in (
        ("причина названа",
         lambda *a, **k: {**real(*a, **k), "unmeasured_reason": "граф порван"},
         "граф порван"),
        ("население пусто",
         lambda *a, **k: {**real(*a, **k), "population": 0},
         "население пар ПУСТО — ноль исходов на пустом населении не есть «чисто»"),
    ):
        monkeypatch.setattr(reach, "measure", patched)
        doc = measure(root, records=[rec])
        assert not doc["measured"], leg
        assert doc["unmeasured_reason"] == f"дороги не измерены: {expected}", leg
    monkeypatch.setattr(reach, "measure", real)
    assert measure(root, records=[rec])["measured"]


def test_an_unmeasured_wide_census_stops_the_price_by_either_leg(
        tmp_path, monkeypatch):
    """То же у ЦЕНЫ предела: две ноги, каждая останавливает ОДНА.

    Убивает ``bool#338 Or-flip``, ``bool#1226 Or-flip`` и строки того же
    возврата (``str#1220/1223/1224/1225/1667/2011``). Без этого цена считалась бы
    по неизмеренному широкому обходу и печаталась как число."""
    root, rec = _scene(tmp_path)
    real = reach.measure

    def _narrow_ok_wide_broken(repo_root, max_depth=reach.MAX_DEPTH, graph=None):
        doc = real(repo_root, max_depth=max_depth, graph=graph)
        if max_depth > 3:
            return {**doc, "unmeasured_reason": "широкий обход порван"}
        return doc

    monkeypatch.setattr(reach, "measure", _narrow_ok_wide_broken)
    price = measure(root, records=[rec], max_depth=3, price_depth=9)["price_of_the_limit"]
    assert price["state"] == "unmeasured"
    assert price["why"] == "широкий обход порван"

    def _narrow_ok_wide_empty(repo_root, max_depth=reach.MAX_DEPTH, graph=None):
        doc = real(repo_root, max_depth=max_depth, graph=graph)
        if max_depth > 3:
            return {**doc, "population": 0}
        return doc

    monkeypatch.setattr(reach, "measure", _narrow_ok_wide_empty)
    price = measure(root, records=[rec], max_depth=3, price_depth=9)["price_of_the_limit"]
    assert price["state"] == "unmeasured"
    assert "население пар ПУСТО" in price["why"]


def test_only_the_failing_pairs_land_in_the_findings_list(tmp_path):
    """Перечень находок несёт РОВНО упавшие пары, и это проверено разностью.

    Убивает ``cmp#631 Eq->NotEq``: с ``!=`` в перечень уехали бы зелёные пары, а
    счётчик ``counts`` остался бы прежним — то есть подмена была бы НЕВИДИМА
    счётом (урок #786)."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "scripts/__init__.py": "",
        "scripts/helper.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_red.py": "import scripts.helper\n",
        "spa_core/tests/test_green.py": "import scripts.helper\n",
    })
    rec = _record(tmp_path / "reports" / "junit-only.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_red.py": FAIL,
        "spa_core/tests/test_green.py": PASS,
    })
    doc = measure(root, records=[rec])
    assert [row["file"] for row in doc["findings"]] == \
        ["spa_core/tests/test_red.py"]


def test_only_the_failing_pairs_land_in_the_price_list(tmp_path):
    """То же у цены предела: ``cmp#755 Eq->NotEq``."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "scripts/__init__.py": "",
        "scripts/a.py": "import scripts.b\n",
        "scripts/b.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_near.py": "import scripts.b\n",
        "spa_core/tests/test_far_red.py": "import scripts.a\n",
        "spa_core/tests/test_far_green.py": "import scripts.a\n",
    })
    rec = _record(tmp_path / "reports" / "junit-price3.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_near.py": PASS,
        "spa_core/tests/test_far_red.py": FAIL,
        "spa_core/tests/test_far_green.py": PASS,
    })
    price = measure(root, records=[rec], max_depth=1,
                    price_depth=9)["price_of_the_limit"]
    assert [row["file"] for row in price["failed"]] == \
        ["spa_core/tests/test_far_red.py"]
    assert price["pairs"] == 2


def test_each_surface_lists_only_its_own_failures(tmp_path):
    """``failed_added`` поверхности несёт ЕЁ файлы, а не чужие.

    Убивает ``cmp#2258 Eq->NotEq``. Сцена обязана нести РАЗНЫЕ файлы на разных
    поверхностях: один файл на двух поверхностях выжил бы и при ``!=``."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "build_architecture_manifest.py": "MANIFEST = {}\n",
        "scripts/__init__.py": "",
        "scripts/risk_helper.py": "from spa_core.risk.policy import APPROVED\n",
        "scripts/arch_helper.py": "import build_architecture_manifest\n",
        "spa_core/tests/test_direct_risk.py":
            "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct_arch.py": "import build_architecture_manifest\n",
        "spa_core/tests/test_red_risk.py": "import scripts.risk_helper\n",
        "spa_core/tests/test_red_arch.py": "import scripts.arch_helper\n",
    })
    rec = _record(tmp_path / "reports" / "junit-own.xml", {
        "spa_core/tests/test_direct_risk.py": PASS,
        "spa_core/tests/test_direct_arch.py": PASS,
        "spa_core/tests/test_red_risk.py": FAIL,
        "spa_core/tests/test_red_arch.py": FAIL,
    })
    doc = measure(root, records=[rec])
    assert doc["per_surface"]["risk"]["failed_added"] == \
        ["spa_core/tests/test_red_risk.py"]
    assert doc["per_surface"]["architecture"]["failed_added"] == \
        ["spa_core/tests/test_red_arch.py"]


def test_the_default_of_the_price_lookup_is_unreachable_by_the_neighbour(tmp_path):
    """Умолчание ``.get(…, 0)`` НЕДОСТИЖИМО: сосед заводит все четыре ключа.

    Убивает ``int#1644`` и ``int#1647`` ТЕСТОМ ПРЕДПОСЫЛКИ, а не подгонкой: если
    сосед когда-нибудь перестанет заводить ключ, покраснеет ЭТОТ тест — и тогда
    умолчание станет настоящей веткой, которую надо будет мерить."""
    root, _rec = _scene(tmp_path)
    counts = reach.measure(root)["name_counts"]
    assert set(counts) == set(reach.NAME_OUTCOMES)
    assert all(isinstance(v, int) for v in counts.values())


def test_the_report_tail_counter_agrees_with_the_printed_rows(tmp_path):
    """«… ещё N» обязано сходиться с числом напечатанных строк находок.

    Убивает ``cmp#385``, ``int#808``, ``int#1320``, ``int#2376``: три числа одного
    усечения живут в трёх местах, и мутант сдвигает ОДНО — отчёт тогда называет
    неверный остаток."""
    files = {"spa_core/risk/__init__.py": "",
             "spa_core/risk/policy.py": "APPROVED = True\n",
             "scripts/__init__.py": "",
             "spa_core/tests/test_direct.py":
                 "from spa_core.risk.policy import APPROVED\n"}
    cases = {"spa_core/tests/test_direct.py": PASS}
    # РОВНО 13: край порога. При 15 мутант `> 12 → > 13` остался бы незамеченным,
    # а при 13 он снимает хвостовую строку, и одна находка исчезает МОЛЧА.
    for i in range(13):
        files[f"scripts/h{i}.py"] = "from spa_core.risk.policy import APPROVED\n"
        files[f"spa_core/tests/test_h{i}.py"] = f"import scripts.h{i}\n"
        cases[f"spa_core/tests/test_h{i}.py"] = FAIL
    root = _tree(tmp_path / "tree", files)
    rec = _record(tmp_path / "reports" / "junit-many.xml", cases)
    doc = measure(root, records=[rec])
    assert doc["counts"][FAILED] == 13
    report = format_report(doc)
    printed = [line for line in report.splitlines() if f"[{FAILED}]" in line]
    assert len(printed) == 12
    assert "ещё 1 находок" in report


def test_the_search_path_puts_its_reason_into_the_document(tmp_path):
    """Причина поиска записи ЖИВЁТ в документе под объявленным ключом.

    Убивает ``str#984 'record_search_reason'->mutated``: ветка присваивания
    исполняется ТОЛЬКО когда запись не подана (``records=None``), а оба соседних
    теста подают её списком — и подмена ключа оставалась невидимой."""
    root, _rec = _scene(tmp_path)
    doc = measure(root)  # записи не подано ⇒ прибор ИЩЕТ её сам
    assert set(doc) == {"repo_root", "max_depth", "price_depth", "records",
                        "record_search_reason", "measured", "unmeasured_reason"}
    assert doc["record_search_reason"] == doc["unmeasured_reason"]
    assert "каталога записи" in doc["record_search_reason"]


def test_a_broken_graph_is_named_by_its_own_reason(tmp_path, monkeypatch):
    """Граф не построен ⇒ своя причина, а не причина дорог.

    Убивает ``str#1894 'граф импортов не построен'``. Отказ графа и отказ
    переписи дорог — РАЗНЫЕ третьи исхода: первый чинится деревом, второй
    правилом, и один текст на оба увёл бы починку не туда."""
    root, rec = _scene(tmp_path)

    def _no_graph(repo_root, module_level_only=False):
        raise reach.Unmeasured("дерева нет по пути сцены")

    monkeypatch.setattr(reach, "build_graph", _no_graph)
    doc = measure(root, records=[rec])
    assert not doc["measured"]
    assert doc["unmeasured_reason"] == ("граф импортов не построен: дерева нет по "
                                        "пути сцены")


def test_the_price_row_carries_the_depth_it_was_cut_at(tmp_path):
    """У отрезанной пары печатается ГЛУБИНА — иначе «за пределом» без числа.

    Убивает ``str#2033 'depth'->mutated``: без глубины читатель не отличит
    дорогу в четыре дуги от дороги в тринадцать, а это ровно разница между
    «почти принадлежит» и «в нашем дереве всё достигает всего»."""
    root = _tree(tmp_path / "tree", {
        "spa_core/risk/__init__.py": "",
        "spa_core/risk/policy.py": "APPROVED = True\n",
        "scripts/__init__.py": "",
        "scripts/a.py": "import scripts.b\n",
        "scripts/b.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_direct.py": "from spa_core.risk.policy import APPROVED\n",
        "spa_core/tests/test_near.py": "import scripts.b\n",
        "spa_core/tests/test_far.py": "import scripts.a\n",
    })
    rec = _record(tmp_path / "reports" / "junit-depth2.xml", {
        "spa_core/tests/test_direct.py": PASS,
        "spa_core/tests/test_near.py": PASS,
        "spa_core/tests/test_far.py": FAIL,
    })
    price = measure(root, records=[rec], max_depth=1,
                    price_depth=9)["price_of_the_limit"]
    assert price["failed"] == [{"file": "spa_core/tests/test_far.py",
                               "surface": "risk", "depth": 2}]


def test_the_dummy_surface_name_never_escapes_the_single_file_question():
    """Имя поверхности в вопросе об ОДНОМ файле равносильно любому другому.

    ТЕСТ ПРЕДПОСЫЛКИ, а не подгонка: мутант ``str#934 '_'->mutated`` выжил, и
    равносильность надо доказать, а не объявить. ``_outcome_of`` читает у ``judge``
    только ТИП исхода, а имя поверхности живёт в строках, которые он не трогает;
    если это когда-нибудь перестанет быть правдой, покраснеет ЭТОТ тест."""
    record = {"files": {"a.py": {"passed": 0, "skipped": 0,
                                 "bad": [{"case": "x", "kind": "failure",
                                          "message": ""}], "records": []}}}
    assert vps._outcome_of("a.py", record) == FAILED
    one = nrc.judge({"_": ["a.py"]}, record)
    other = nrc.judge({"совсем другое имя": ["a.py"]}, record)
    assert [row["kind"] if "kind" in row else None
            for row in one["failed"]] == [None]
    assert one["verdict"] == other["verdict"]
    assert [r["file"] for r in one["failed"]] == [r["file"] for r in other["failed"]]


def test_a_non_empty_record_list_always_lands_in_one_of_the_two_lists(tmp_path):
    """Ветка «запись не прочитана» НЕДОСТИЖИМА, и это доказано, а не заявлено.

    Мутант ``str#1006`` выжил. ``read_record`` кладёт КАЖДЫЙ поданный путь либо в
    ``records_read``, либо в ``records_unread``; значит при непустом списке оба
    множества пустыми быть не могут, и запасной текст недостижим. Перестанет быть
    так — покраснеет ЭТОТ тест, и ветка станет настоящей."""
    root, rec = _scene(tmp_path)
    broken = tmp_path / "reports" / "junit-bad.xml"
    broken.write_text("не xml", encoding="utf-8")
    for paths in ([rec], [str(broken)], [rec, str(broken)], ["/нет.xml"]):
        doc = nrc.read_record(paths, repo_root=root)
        assert len(doc["records_read"]) + len(doc["records_unread"]) == len(paths)
