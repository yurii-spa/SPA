"""Проводка шага «подданный числа ряда» (заказ G99 п. 2, ADR-572).

Шаг, которого никто не зовёт, и число, которого никто не читает, — та самая
форма, что ловит ADR-208; и зелёный храповик непроведённых модулей гасится
одним ВВОЗОМ, что уже случалось (ADR-547). Поэтому проводка мерится ФОРМОЙ
ВЫЗОВА и ЧТЕНИЕМ, а не наличием имени в файле.

Звеньев четыре: зов в `measure` ПОСЛЕ сборки документа · ключ в возвращённом
документе · чтение ключа отрисовкой честной формой · обязательность ключа в
схеме офиса, иначе потеря шага была бы молчаливой.

Пятое звено — своё: шаг обязан получать СОБРАННЫЙ документ, а не корень
дерева в одиночку. Число ряда есть свойство опубликованного замера; шаг,
которому передали бы только дерево, отвечал бы на другой вопрос.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import rule_second_copy_census as C

ROOT = Path(C.__file__).resolve().parents[2]
STEP = "subject_of_a_series_number"
OFFICE = ROOT / "scripts" / "consume_office_reports.py"
BRIDGE = ROOT / "spa_core" / "monitoring" / "findings_bridge.py"


def _producer_tree() -> ast.AST:
    return ast.parse(Path(C.__file__).read_text(encoding="utf-8"))


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    raise AssertionError(f"функции {name} нет в производителе")


# ------------------------------------------------- ЗВЕНО 1: ЗОВ, НЕ ВВОЗ

def test_measure_calls_the_step_by_call_form():
    measure = _function(_producer_tree(), "measure")
    calls = [node for node in ast.walk(measure)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == STEP]
    assert len(calls) == 1, "шаг обязан быть позван РОВНО один раз за прогон"


def test_the_step_is_given_the_assembled_document():
    """Второй аргумент — СОБРАННЫЙ документ: подданный числа есть свойство
    опубликованного замера, а не отдельного прохода по дереву."""
    measure = _function(_producer_tree(), "measure")
    call = next(node for node in ast.walk(measure)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == STEP)
    assert len(call.args) == 2
    assert isinstance(call.args[1], ast.Name) and call.args[1].id == "doc"


def test_the_step_name_lives_in_one_constant():
    """Имя ключа объявлено ОДНОЙ строкой: вторая копия имени расходилась бы
    молча — ровно тот предмет, который перепись и меряет."""
    assert C.SUBJECT_OWN_STEP == STEP


# --------------------------------------- ЗВЕНО 2: КЛЮЧ В ДОКУМЕНТЕ ЗАМЕРА

def test_the_measured_document_carries_the_step_under_its_own_name():
    """Ключ ставится ИМЕНЕМ-КОНСТАНТОЙ, и это проверяется формой присваивания:
    литерал рядом с константой был бы второй копией имени."""
    measure = _function(_producer_tree(), "measure")
    writes = [node for node in ast.walk(measure)
              if isinstance(node, ast.Assign)
              and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Subscript)
              and isinstance(node.targets[0].value, ast.Name)
              and node.targets[0].value.id == "doc"
              and isinstance(node.targets[0].slice, ast.Name)
              and node.targets[0].slice.id == "SUBJECT_OWN_STEP"]
    assert len(writes) == 1


def test_the_step_is_called_after_the_document_is_assembled():
    """Порядок — часть утверждения: шаг, позванный до сборки, мерил бы пустой
    ряд и отвечал бы «ни одного шага» на исправном прогоне."""
    measure = _function(_producer_tree(), "measure")
    assembly = [node.lineno for node in ast.walk(measure)
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "doc"]
    call = next(node.lineno for node in ast.walk(measure)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == STEP)
    assert assembly and call > max(assembly)


# ----------------------------------------- ЗВЕНО 3: ОТРИСОВКА ЧИТАЕТ КЛЮЧ

def test_the_report_reads_the_key_through_observed():
    """Честная форма чтения: `observed` разводит «нет шага» от «ноль»."""
    report = _function(_producer_tree(), "report")
    reads = [node for node in ast.walk(report)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "observed"
             and any(isinstance(arg, ast.Name)
                     and arg.id == "SUBJECT_OWN_STEP" for arg in node.args)]
    assert len(reads) == 1


def test_the_office_rendering_carries_the_head_number():
    """Офис зовёт `format_report` производителя — та же дорога, что живая."""
    doc = {"status": "CLEAN", STEP: {
        "status": "MEASURED", "population": 43,
        "steps_declaring_an_order": 19,
        "steps_with_a_number_of_the_declared_form": 13,
        "steps_without_a_number_of_the_declared_form": ["tail_value_divergence"],
        "subject_outcomes": {cls: 1 for cls in C._SUBJECT_OUTCOMES},
        "unmeasured_reasons": {gap: 0 for gap in C._SUBJECT_GAPS},
        "filter_forms": {form: 1 for form in C._SUBJECT_FORMS},
        "matched_by": {kind: 1 for kind in C._SUBJECT_MATCHES},
        "published_numbers_per_step": {"least": 0, "most": 21},
        "fields_outside_the_declared_form": 8,
        "sum_matches_no_published_number": 1,
        "unpublished_sample": [{"step": "writer_harm_form", "order": "G84.2",
                                "line": 10, "field": "silence_proved_by",
                                "sum": 142, "keys": 2,
                                "form": C.SUBJECT_FORM_EQ,
                                "closest": {"name": "population",
                                            "value": 248, "delta": 106}}],
        "control": {"passed": True, "scenes": 8, "gaps": ["a", "b", "c"]},
    }}
    lines = "\n".join(C.format_report(doc))
    assert "[ПОДДАННЫЙ ЧИСЛА]" in lines
    assert "writer_harm_form.silence_proved_by" in lines
    assert "142" in lines


# ------------------------- ЗВЕНО 4: ПОТЕРЯ ШАГА ОБЯЗАНА БЫТЬ ГРОМКОЙ

def test_the_office_schema_requires_the_step_key():
    """Ключ объявлен ОБЯЗАТЕЛЬНЫМ в схеме офиса: иначе исчезновение шага из
    артефакта прошло бы молча, а «находок 0» стало бы неотличимо от «шага
    нет» (инв. #17)."""
    tree = ast.parse(OFFICE.read_text(encoding="utf-8"))
    required: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == C.ARTIFACT):
                continue
            if isinstance(value, ast.Tuple):
                required.extend(element.value for element in value.elts
                                if isinstance(element, ast.Constant))
    assert required, f"схема офиса не знает артефакта {C.ARTIFACT}"
    assert STEP in required


def test_the_artifact_is_declared_by_the_bridge_stage():
    """Шаг едет в объявленном артефакте, а не в новом безымянном файле."""
    source = BRIDGE.read_text(encoding="utf-8")
    assert f'"data/{C.ARTIFACT}"' in source
    assert C.PRODUCER in source
