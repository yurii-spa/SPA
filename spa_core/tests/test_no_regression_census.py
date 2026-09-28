"""Контроль в обе стороны для переписи критерия §49 ``No regression``.

Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»). Поэтому здесь нет ни
одного теста «модуль импортируется»: каждый строит ЦЕЛУЮ одноразовую сцену —
крошечное дерево с настоящими тест-файлами и настоящей junit-записью, — и затем
рвёт РОВНО ОДНО звено, называя его.

Зелёная сторона тоже настоящая: сцена «всё зелено и всё измерено» обязана давать
``NO_REGRESSION``, иначе ``REGRESSION`` был бы неотличим от прибора, который не
умеет отвечать «да» вовсе.

Отдельно закреплены ДВА капкана, из-за которых критерий и не мерил никто:

* **имя файла** — ``test_defi_*_risk_*.py`` в население не входит, а
  ``test_risk_policy.py`` с написанием ``from risk.policy import …`` — входит;
* **форма junit** — по умолчанию pytest пишет ``xunit2``, где атрибута ``file``
  у случая НЕТ ВОВСЕ, и именно так пишет наш CI. Запись такой формы обязана
  читаться, иначе прибор объявил бы непрочитанным собственный CI.

Часы и корень дерева — ВХОДЫ: ни один тест не зависит от календаря, рабочего
каталога и состояния живого ``data/``.
"""
# FROZEN-DATE-OK: injected-clock — все отметки происходят от _NOW, который передаётся
# пробе аргументом now=; стенных часов сцена не спрашивает ни разу.
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import no_regression_census as nrc

_NOW = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)


# ───────────────────────────────── сцена ──────────────────────────────────────

def _tree(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    """Одноразовое дерево: все предписанные каталоги существуют, файлы — заданные."""
    for rel in nrc.TEST_ROOTS:
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    for rel, src in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src, encoding="utf-8")
    return tmp_path


def _junit(path: pathlib.Path, cases: list[dict], *,
           hostname: str = "stand", timestamp: str | None = None) -> str:
    """junit-запись формы ``xunit2`` (без атрибута ``file``) — так пишет наш CI.

    ``file=`` у случая появляется только если он задан явно: вторая форма
    (``xunit1``) тоже живая, и обе обязаны читаться.
    """
    stamp = timestamp or _NOW.isoformat()
    rows = []
    for case in cases:
        attrs = f'classname="{case["classname"]}" name="{case.get("name", "t")}"'
        if case.get("file"):
            attrs += f' file="{case["file"]}"'
        body = ""
        kind = case.get("kind")
        if kind in ("failure", "error", "skipped"):
            body = f'<{kind} message="{case.get("message", "boom")}">detail</{kind}>'
        rows.append(f"<testcase {attrs}>{body}</testcase>" if body
                    else f"<testcase {attrs} />")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuites name="pytest tests"><testsuite name="pytest" '
        f'hostname="{hostname}" timestamp="{stamp}" tests="{len(cases)}">'
        + "".join(rows) + "</testsuite></testsuites>", encoding="utf-8")
    return str(path)


_RISK_LONG = "from spa_core.risk.policy import RiskPolicy\n"
_RISK_SHORT = "from risk.policy import RiskPolicy\n"
_SECURITY = "import lint_llm_forbidden\n"
_ARCHITECTURE = "from spa_core.monitoring.architecture_conformance import check\n"
_ADVISORY = "from spa_core.strategy_lab.oracle_risk import score\n"

#: Минимальная сцена, у которой население непусто во ВСЕХ трёх поверхностях:
#: пустое население — законный отказ прибора, и наткнуться на него случайно
#: значило бы мерить не то, что задумано.
_MINIMAL = {
    "spa_core/tests/test_risk_policy.py": _RISK_SHORT,
    "tests/test_security_audit.py": "# сам сканирует дерево, импортировать нечего\n",
    "spa_core/tests/test_agent_servers_bind_loopback.py": "# читает обёртки\n",
    "spa_core/tests/test_architecture_conformance.py": _ARCHITECTURE,
}

_MINIMAL_GREEN = [
    {"classname": "spa_core.tests.test_risk_policy.T"},
    {"classname": "tests.test_security_audit"},
    {"classname": "spa_core.tests.test_agent_servers_bind_loopback.T"},
    {"classname": "spa_core.tests.test_architecture_conformance.T"},
]


# ───────────────────────────── население: правило ─────────────────────────────

def test_both_spellings_of_the_risk_surface_enter_the_population(tmp_path):
    """Второе написание — НЕ придирка: на нём висит главный risk-тест системы."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_a_long.py": _RISK_LONG,
        "spa_core/tests/test_b_short.py": _RISK_SHORT,
    })
    files = nrc.population(str(root))["surfaces"]["risk"]["files"]
    assert files == ["spa_core/tests/test_a_long.py", "spa_core/tests/test_b_short.py"]


def test_the_name_of_the_file_does_not_enter_the_population(tmp_path):
    """Капкан №1: сотня advisory-анализаторов зовётся risk и risk-политикой не является."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_defi_oracle_risk_scorer.py": _ADVISORY,
    })
    assert nrc.population(str(root))["surfaces"]["risk"]["files"] == []


def test_a_neighbouring_package_is_not_the_surface(tmp_path):
    """Сравнение по ГРАНИЦЕ имени: ``riskwire`` — не ``risk``."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_wire.py": "import riskwire\nimport governance_notes\n",
    })
    assert nrc.population(str(root))["surfaces"]["risk"]["files"] == []


def test_a_relative_import_is_not_guessed(tmp_path):
    """Односторонность объявлена вслух: у относительного импорта имени пакета нет."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_rel.py": "from . import policy\nfrom .risk import x\n",
    })
    assert nrc.population(str(root))["surfaces"]["risk"]["files"] == []


def test_an_opaque_import_with_a_literal_name_enters_the_population(tmp_path):
    """Форма НЕ выдумана: так грузит генератор манифеста настоящий architecture-тест.

    Найдено приёмкой: правило, знавшее только `import`/`from`, теряло
    `spa_core/tests/test_architecture_manifest.py` — и он КРАСЕН на прод-хосте.
    «Критерий выполнен» получался из слепоты правила, а не из зелени набора.
    """
    root = _tree(tmp_path, {
        "spa_core/tests/test_spec.py":
            "import importlib.util\n"
            "spec = importlib.util.spec_from_file_location("
            "'build_architecture_manifest', '/x/y.py')\n",
        "spa_core/tests/test_mod.py":
            "import importlib\n"
            "m = importlib.import_module('spa_core.risk.policy')\n",
    })
    surfaces = nrc.population(str(root))["surfaces"]
    assert surfaces["architecture"]["files"] == ["spa_core/tests/test_spec.py"]
    assert surfaces["risk"]["files"] == ["spa_core/tests/test_mod.py"]


def test_an_opaque_import_whose_name_is_computed_is_not_guessed(tmp_path):
    """Имя, которое надо вычислять, не гадается: перечень форм ЗАКРЫТ, литерал обязателен."""
    root = _tree(tmp_path, {
        "spa_core/tests/test_dyn.py":
            "import importlib\n"
            "name = 'spa_core' + '.risk.policy'\n"
            "m = importlib.import_module(name)\n"
            "n = importlib.import_module(MODULES[0])\n",
    })
    assert nrc.population(str(root))["surfaces"]["risk"]["files"] == []


def test_a_file_whose_every_case_is_skipped_has_no_outcome(tmp_path):
    """Пропущенный тест НЕ «проходит»: иначе скип по условию среды сошёл бы за зелень.

    Это не гипотетика: красный на прод-хосте `test_architecture_manifest.py` в CI
    именно скипается (`~/Library/LaunchAgents` без `com.spa.*`), и зачесть его
    зелёным значило бы закрыть критерий владельца отсутствием наблюдения.
    """
    root = _tree(tmp_path, _MINIMAL)
    cases = list(_MINIMAL_GREEN)
    cases[-1] = {"classname": "spa_core.tests.test_architecture_conformance.T",
                 "name": "a", "kind": "skipped", "message": "не прод-хост"}
    record = _junit(tmp_path / "r.xml", cases)
    report = nrc.measure(str(root), junit_paths=[record])
    assert report["verdict"] == nrc.UNMEASURED
    assert [u["file"] for u in report["unmeasured_members"]] == \
        ["spa_core/tests/test_architecture_conformance.py"]
    assert "ПРОПУЩЕНЫ" in report["unmeasured_members"][0]["reason"]


def test_a_partly_skipped_file_still_has_an_outcome(tmp_path):
    """Обратная сторона: один скип рядом с прошедшими случаями исход НЕ отменяет."""
    root = _tree(tmp_path, _MINIMAL)
    cases = list(_MINIMAL_GREEN) + [
        {"classname": "spa_core.tests.test_architecture_conformance.T",
         "name": "b", "kind": "skipped", "message": "одна ветка не на этом хосте"}]
    record = _junit(tmp_path / "r.xml", cases)
    report = nrc.measure(str(root), junit_paths=[record])
    assert report["verdict"] == nrc.NO_REGRESSION


def test_a_self_guard_enters_by_declaration_and_is_counted_separately(tmp_path):
    """Сторож, который САМ и есть проверка: импортировать ему нечего."""
    root = _tree(tmp_path, _MINIMAL)
    surface = nrc.population(str(root))["surfaces"]["security"]
    assert "tests/test_security_audit.py" in surface["files"]
    assert "tests/test_security_audit.py" in surface["by_declaration"]
    # объявлением, а не импортом: иначе счётчик соврал бы о происхождении
    assert all(row["file"] != "tests/test_security_audit.py"
               for row in surface["by_import"])


def test_a_declared_self_guard_missing_from_the_tree_is_unmeasured(tmp_path):
    """Объявление разошлось с деревом ⇒ громко, а не тихим выпадением из населения."""
    files = dict(_MINIMAL)
    del files["tests/test_security_audit.py"]
    root = _tree(tmp_path, files)
    pop = nrc.population(str(root))
    assert [m["file"] for m in pop["missing_self_guards"]] == \
        ["tests/test_security_audit.py"]
    report = nrc.measure(str(root), junit_paths=[])
    assert report["verdict"] == nrc.UNMEASURED
    assert "test_security_audit.py" in report["reason"]


def test_an_unparsed_test_file_makes_membership_unknown(tmp_path):
    """«Не знаю, входит ли он» нельзя записать ни в «входит», ни в «не входит»."""
    files = dict(_MINIMAL)
    files["spa_core/tests/test_broken.py"] = "def f(:\n"
    root = _tree(tmp_path, files)
    record = _junit(tmp_path / "r.xml", _MINIMAL_GREEN)
    report = nrc.measure(str(root), junit_paths=[record])
    assert report["verdict"] == nrc.UNMEASURED
    assert "test_broken.py" in report["reason"]
    assert not report["measured"]


def test_a_missing_prescribed_root_is_unmeasured_not_a_smaller_population(tmp_path):
    """Каталог предписанного прогона исчез ⇒ население неполно ПО ПОСТРОЕНИЮ."""
    root = _tree(tmp_path, _MINIMAL)
    (root / "research/cards").rmdir()
    report = nrc.measure(str(root), junit_paths=[])
    assert report["verdict"] == nrc.UNMEASURED
    assert "research/cards" in report["reason"]


def test_the_security_surface_also_enters_by_import(tmp_path):
    """У security две дороги в население, и обе живые: импорт И объявление."""
    files = dict(_MINIMAL)
    files["scripts/tests/test_lint_llm_forbidden.py"] = _SECURITY
    root = _tree(tmp_path, files)
    surface = nrc.population(str(root))["surfaces"]["security"]
    assert [row["file"] for row in surface["by_import"]] == \
        ["scripts/tests/test_lint_llm_forbidden.py"]
    assert len(surface["files"]) == 3


def test_an_empty_surface_is_refused_rather_than_green(tmp_path):
    """Сторож без населения зелен по построению, и эта зелень ничего не значит.

    Сцена намеренно ЦЕЛАЯ во всём остальном (объявленные сторожа на месте, файлы
    разбираются): иначе отказ дал бы другой сторож, и проверялся бы не тот.
    """
    files = dict(_MINIMAL)
    del files["spa_core/tests/test_architecture_conformance.py"]
    root = _tree(tmp_path, files)
    report = nrc.measure(str(root), junit_paths=[])
    assert report["verdict"] == nrc.UNMEASURED
    assert "ПУСТО" in report["reason"]
    assert "architecture" in report["reason"]


# ────────────────────────── запись прогона: чтение ────────────────────────────

def test_the_record_our_ci_actually_writes_is_read(tmp_path):
    """Форма ``xunit2``: атрибута ``file`` нет, путь берётся из classname и ПРОВЕРЯЕТСЯ."""
    root = _tree(tmp_path, _MINIMAL)
    record = _junit(tmp_path / "r.xml", _MINIMAL_GREEN)
    got = nrc.read_record([record], repo_root=str(root))
    assert set(got["files"]) == set(_MINIMAL)
    assert got["cases_without_file"] == 0


def test_a_classname_resolving_to_no_file_is_not_attributed_to_anyone(tmp_path):
    """Префикс, которому файла нет, не принимается: это замер, а не догадка."""
    root = _tree(tmp_path, _MINIMAL)
    record = _junit(tmp_path / "r.xml",
                    [{"classname": "somewhere.else.test_ghost.T"}])
    got = nrc.read_record([record], repo_root=str(root))
    assert got["files"] == {}
    assert got["cases_without_file"] == 1


def test_the_file_attribute_wins_when_the_record_carries_one(tmp_path):
    """Вторая живая форма (``xunit1``) тоже обязана читаться."""
    root = _tree(tmp_path, _MINIMAL)
    record = _junit(tmp_path / "r.xml",
                    [{"classname": "nonsense.T",
                      "file": "spa_core/tests/test_risk_policy.py"}])
    got = nrc.read_record([record], repo_root=str(root))
    assert list(got["files"]) == ["spa_core/tests/test_risk_policy.py"]


def test_failure_and_error_are_both_poor_outcomes_and_skipped_is_not(tmp_path):
    """``error`` в setUpClass — ровно форма настоящей аварии (ADR-474), и она НЕ «прошло»."""
    root = _tree(tmp_path, _MINIMAL)
    record = _junit(tmp_path / "r.xml", [
        {"classname": "spa_core.tests.test_risk_policy.T", "name": "a",
         "kind": "failure", "message": "assert"},
        {"classname": "spa_core.tests.test_risk_policy.T", "name": "b",
         "kind": "error", "message": "Timeout (>180.0s)"},
        {"classname": "spa_core.tests.test_risk_policy.T", "name": "c",
         "kind": "skipped", "message": "why"},
    ])
    row = nrc.read_record([record], repo_root=str(root))["files"][
        "spa_core/tests/test_risk_policy.py"]
    assert [b["kind"] for b in row["bad"]] == ["failure", "error"]
    assert row["skipped"] == 1 and row["passed"] == 0


def test_an_unreadable_record_is_named_and_is_not_a_clean_pass(tmp_path):
    """Отсутствие инструмента — самостоятельный третий исход, а не ноль и не скип."""
    root = _tree(tmp_path, _MINIMAL)
    report = nrc.measure(str(root), junit_paths=[str(tmp_path / "нет.xml")])
    assert report["verdict"] == nrc.UNMEASURED
    assert "нет.xml" in report["reason"]
    assert report["records_unread"] and not report["records_read"]


def test_no_record_at_all_is_unmeasured_and_says_so(tmp_path):
    root = _tree(tmp_path, _MINIMAL)
    report = nrc.measure(str(root), junit_paths=[])
    assert report["verdict"] == nrc.UNMEASURED
    assert "записи прогона нет" in report["reason"]


# ───────────────────────────────── вердикт ────────────────────────────────────

def test_everything_green_and_everything_measured_is_no_regression(tmp_path):
    """Зелёная сторона настоящая: иначе прибор не умел бы отвечать «да» вовсе."""
    root = _tree(tmp_path, _MINIMAL)
    record = _junit(tmp_path / "r.xml", _MINIMAL_GREEN)
    report = nrc.measure(str(root), junit_paths=[record])
    assert report["verdict"] == nrc.NO_REGRESSION
    assert report["complete"] is True
    assert report["population_total"] == 4
    assert report["failed_total"] == 0 and report["unmeasured_total"] == 0
    assert report["records_meta"][0]["hostname"] == "stand"


def test_a_member_absent_from_the_record_is_unmeasured_with_a_name(tmp_path):
    """Сердцевина инв. #17: «остальные, наверное, прошли» — это и есть подмена."""
    root = _tree(tmp_path, _MINIMAL)
    record = _junit(tmp_path / "r.xml", _MINIMAL_GREEN[:-1])
    report = nrc.measure(str(root), junit_paths=[record])
    assert report["verdict"] == nrc.UNMEASURED
    assert report["measured"] is True          # перепись состоялась, исход — нет
    assert report["complete"] is False
    assert [u["file"] for u in report["unmeasured_members"]] == \
        ["spa_core/tests/test_architecture_conformance.py"]
    # Три корзины РАЗДЕЛЬНЫ: файл, который попал бы и в «зелёные», и в «без
    # вердикта», сделал бы отчёт противоречивым, а читателя — вправе выбрать
    # удобную корзину. Найдено мутацией (выживала, пока корзины не сверялись).
    for surface in report["surfaces"].values():
        green = set(surface["files_passed"])
        bad = {row["file"] for row in surface["files_failed"]}
        unknown = {row["file"] for row in surface["files_unmeasured"]}
        assert not (green & bad) and not (green & unknown) and not (bad & unknown)


def test_a_named_failure_outweighs_a_missing_record(tmp_path):
    """Названный красный — факт сильнее дыры: вердикт REGRESSION, но дыра тоже названа."""
    root = _tree(tmp_path, _MINIMAL)
    cases = list(_MINIMAL_GREEN[:-1])
    cases[0] = {"classname": "spa_core.tests.test_risk_policy.T", "name": "a",
                "kind": "failure", "message": "RiskPolicy сломан"}
    record = _junit(tmp_path / "r.xml", cases)
    report = nrc.measure(str(root), junit_paths=[record])
    assert report["verdict"] == nrc.REGRESSION
    assert report["failed_total"] == 1 and report["unmeasured_total"] == 1
    assert report["failed"][0]["file"] == "spa_core/tests/test_risk_policy.py"
    assert report["failed"][0]["surface"] == "risk"


def test_several_records_are_read_together(tmp_path):
    """Предписанный прогон идёт четырьмя шагами — и записей у него столько же."""
    root = _tree(tmp_path, _MINIMAL)
    a = _junit(tmp_path / "a.xml", _MINIMAL_GREEN[:2])
    b = _junit(tmp_path / "b.xml", _MINIMAL_GREEN[2:])
    report = nrc.measure(str(root), junit_paths=[a, b])
    assert report["verdict"] == nrc.NO_REGRESSION
    assert len(report["records_read"]) == 2


# ──────────────────────────────────── проба ───────────────────────────────────

def _report(tmp_path: pathlib.Path, root: pathlib.Path, cases: list[dict],
            *, age_h: float = 1.0) -> pathlib.Path:
    """Отчёт переписи на диске сцены — ровно там, где его ищет проба."""
    record = _junit(tmp_path / "r.xml", cases)
    report = nrc.measure(str(root), junit_paths=[record])
    report["generated_at"] = (_NOW - timedelta(hours=age_h)).isoformat()
    path = root / nrc.REPORT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return path


def _probe(root: pathlib.Path, **kw):
    return ca.PROBES["no_regression_tests_pass"](
        None, now=_NOW, repo_root=str(root), **kw)


def test_the_probe_is_satisfied_only_when_complete_and_green(tmp_path):
    root = _tree(tmp_path, _MINIMAL)
    _report(tmp_path, root, _MINIMAL_GREEN)
    verdict, detail = _probe(root)
    assert verdict == ca.SATISFIED
    assert "население 4" in detail and "stand" in detail


def test_the_probe_names_the_failing_file(tmp_path):
    root = _tree(tmp_path, _MINIMAL)
    cases = list(_MINIMAL_GREEN)
    cases[0] = {"classname": "spa_core.tests.test_risk_policy.T", "name": "a",
                "kind": "failure", "message": "RiskPolicy сломан"}
    _report(tmp_path, root, cases)
    verdict, detail = _probe(root)
    assert verdict == ca.NOT_SATISFIED
    assert "test_risk_policy.py" in detail


def test_the_probe_refuses_a_stale_record(tmp_path):
    """Население могло не измениться, а код под ним — измениться."""
    root = _tree(tmp_path, _MINIMAL)
    _report(tmp_path, root, _MINIMAL_GREEN,
            age_h=ca._NO_REGRESSION_MAX_AGE_H + 1.0)
    verdict, detail = _probe(root)
    assert verdict == ca.UNMEASURED
    assert "старше предела" in detail


def test_the_probe_refuses_a_record_without_a_readable_stamp(tmp_path):
    root = _tree(tmp_path, _MINIMAL)
    path = _report(tmp_path, root, _MINIMAL_GREEN)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["generated_at"] = "не дата"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == ca.UNMEASURED
    assert "возраст записи НЕ ИЗМЕРЕН" in detail


def test_the_probe_refuses_when_the_report_is_missing(tmp_path):
    root = _tree(tmp_path, _MINIMAL)
    verdict, detail = _probe(root)
    assert verdict == ca.UNMEASURED
    assert nrc.REPORT_REL in detail


def test_a_member_added_after_the_measurement_is_not_counted_green(tmp_path):
    """Покрытие проверяется ЗАНОВО: иначе проба стала бы fail-OPEN на новом тесте."""
    root = _tree(tmp_path, _MINIMAL)
    _report(tmp_path, root, _MINIMAL_GREEN)
    (root / "spa_core/tests/test_brand_new_risk.py").write_text(
        _RISK_SHORT, encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == ca.UNMEASURED
    assert "test_brand_new_risk.py" in detail
    assert "появился после замера" in detail


def test_the_probe_refuses_a_report_that_contradicts_itself(tmp_path):
    """Один файл в двух корзинах — испорченная запись, а не «наверное, зелёный».

    Найдено МУТАЦИЕЙ: до этого проба проверяла корзины по порядку и выбирала
    первую подошедшую, поэтому запись, где файл значился и зелёным, и без
    вердикта, читалась как зелёная — fail-OPEN ровно там, где проба нужна.
    """
    root = _tree(tmp_path, _MINIMAL)
    path = _report(tmp_path, root, _MINIMAL_GREEN)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["surfaces"]["risk"]["files_unmeasured"].append(
        {"file": "spa_core/tests/test_risk_policy.py", "reason": "спорно"})
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == ca.UNMEASURED
    assert "противоречит сам себе" in detail


def test_the_probe_refuses_when_a_live_surface_has_no_population(tmp_path):
    """Население исчезло ПОСЛЕ замера: отчёт полон, а мерить сегодня нечего.

    Ветка достижима только так — через расхождение живого дерева с записью, —
    и без этого теста она оставалась непроверенной (найдено мутацией).
    """
    root = _tree(tmp_path, _MINIMAL)
    _report(tmp_path, root, _MINIMAL_GREEN)
    (root / "spa_core/tests/test_architecture_conformance.py").unlink()
    verdict, detail = _probe(root)
    assert verdict == ca.UNMEASURED
    assert "ПУСТО" in detail and "architecture" in detail


def test_the_probe_refuses_a_report_about_other_surfaces(tmp_path):
    root = _tree(tmp_path, _MINIMAL)
    path = _report(tmp_path, root, _MINIMAL_GREEN)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["surfaces"].pop("security")
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    verdict, detail = _probe(root)
    assert verdict == ca.UNMEASURED
    assert "разошлись с объявленными" in detail


def test_the_probe_refuses_an_argument(tmp_path):
    root = _tree(tmp_path, _MINIMAL)
    _report(tmp_path, root, _MINIMAL_GREEN)
    verdict, detail = ca.PROBES["no_regression_tests_pass"](
        "risk", now=_NOW, repo_root=str(root))
    assert verdict == ca.UNMEASURED
    assert "не принимает аргумента" in detail


def test_the_probe_is_registered_under_the_name_the_card_declares():
    """Имя, которого нет в реестре, проба честно зовёт `unmeasured` — то есть НИКОГДА."""
    assert ca.validate_spec("no_regression_tests_pass") is None


# ─────────────────── положительный контроль на ЖИВОМ дереве ───────────────────

class TestTheRuleBitesOnTheRealTree:
    """Правило, проверенное только на стенде, могло бы не найти в дереве НИЧЕГО."""

    @classmethod
    def setup_class(cls):
        cls.pop = nrc.population(nrc.REPO_ROOT)
        cls.files = {name: set(s["files"]) for name, s in cls.pop["surfaces"].items()}

    def test_the_main_risk_tests_of_the_system_are_in_the_population(self):
        for rel in ("spa_core/tests/test_risk_policy.py",
                    "spa_core/tests/test_kill_switch.py"):
            assert rel in self.files["risk"], rel

    def test_the_advisory_risk_analyzers_are_not(self):
        assert "spa_core/tests/test_defi_oracle_risk_scorer.py" not in self.files["risk"]

    def test_the_opaque_importer_of_the_manifest_generator_is_in_the_population(self):
        """Положительный контроль на живом дереве для ветки непрозрачного импорта.

        Без неё правило теряло РЕАЛЬНЫЙ architecture-тест, красный на прод-хосте, —
        и вердикт критерия выходил зелёным из слепоты, а не из набора.
        """
        assert "spa_core/tests/test_architecture_manifest.py" in \
            self.files["architecture"]

    def test_every_surface_has_population_here(self):
        for name, files in self.files.items():
            assert files, name

    def test_nothing_in_the_tree_defeated_the_parser(self):
        assert self.pop["unparsed"] == []
        assert self.pop["missing_self_guards"] == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
