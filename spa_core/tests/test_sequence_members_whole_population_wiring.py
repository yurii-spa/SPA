"""Проводка шага «знаменатель ряда» (заказ G99 п. 1, ADR-568).

Шаг, который никто не зовёт, и число, которого никто не читает, — ровно та
форма, что ловит ADR-208. Проводка мерится ФОРМОЙ ВЫЗОВА и ЧТЕНИЕМ, а не
наличием имени в файле: зелёный храповик непроведённых модулей гасится одним
ввозом, и это уже случалось (ADR-547).

Шаг РИДЕР ЧУЖОГО артефакта не заводит: он живёт внутри переписи
`rule_second_copy_census`, чей артефакт объявлен ступенью моста и читается
шагом 0-офис поимённой ветвью. Поэтому проводка здесь — четыре звена:
зов в `measure` · ключ в возвращённом документе · чтение ключа отрисовкой ·
ОБЯЗАТЕЛЬНОСТЬ ключа в схеме офиса (иначе потеря шага была бы молчаливой).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

if __package__ in (None, ""):                      # прямой запуск без conftest
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import rule_second_copy_census as C

ROOT = Path(C.__file__).resolve().parents[2]
STEP = "sequence_members_of_the_whole_population"
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
    """Зов измеряется ФОРМОЙ ВЫЗОВА: ввоз читателем не делает (ADR-547)."""
    measure = _function(_producer_tree(), "measure")
    calls = [n for n in ast.walk(measure)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == STEP]
    assert len(calls) == 1, "шаг обязан быть позван РОВНО один раз за прогон"


def test_the_step_is_given_the_neighbour_population_not_a_literal():
    """Население берётся у СОСЕДА живым: литерал знаменателя был бы той самой
    второй копией числа, которую шаг и чинит."""
    measure = _function(_producer_tree(), "measure")
    call = next(n for n in ast.walk(measure)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == STEP)
    assert len(call.args) == 2
    assert isinstance(call.args[1], ast.Name)
    assert call.args[1].id == "open_counters"


# --------------------------------------- ЗВЕНО 2: КЛЮЧ В ДОКУМЕНТЕ ЗАМЕРА

def test_the_measured_document_declares_the_step_key():
    """Ключ стои́т в возвращённом документе `measure` — иначе артефакт его
    не понесёт, и читать будет нечего."""
    measure = _function(_producer_tree(), "measure")
    keys = [n.value for node in ast.walk(measure)
            if isinstance(node, ast.Dict)
            for n in node.keys
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert STEP in keys


# ----------------------------------------- ЗВЕНО 3: ОТРИСОВКА ЧИТАЕТ КЛЮЧ

def test_the_report_reads_the_key_through_observed():
    """Чтение честной формой: `observed` разводит «нет шага» от «ноль»."""
    report = _function(_producer_tree(), "report")
    reads = [n for n in ast.walk(report)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "observed"
             and any(isinstance(a, ast.Constant) and a.value == STEP
                     for a in n.args)]
    assert len(reads) == 1


def test_the_office_rendering_carries_the_head_number():
    """Офис зовёт `format_report` производителя — та же дорога, что живая."""
    doc = {"status": "CLEAN", STEP: {
        "status": "MEASURED", "population": 206,
        "member_outcomes": {C.MEMBER_FALSE: 5, C.MEMBER_REFUTED: 193,
                            C.MEMBER_UNMEASURED: 8},
        "refuted_by_door": {d: 1 for d in C._MEMBER_DOORS},
        "refuted_by_exactly_these_doors": {
            lbl: 0 for lbl in C._door_labels(C._MEMBER_DOORS)},
        "refuted_by_doors_outside_the_declared_labels": 0,
        "unmeasured_reasons": {g: 0 for g in C._MEMBER_GAPS},
        "doors_contradicting": 0,
        "false_members_by_cause": {c: 1 for c in C._FALSE_CAUSES},
        "false_members_overlap": 0, "false_members_union": 6,
        "series_population_corrected": 200,
        "correction_at_least": 6, "correction_at_most": 14,
        "outside_the_writer_remainder": {
            "population": 189, "false_members": 0, "unmeasured": 0,
            "the_only_route_past_refutation": C.MEMBER_GAP_DOORS_CONTRADICT},
        "own_sites": {"producer": C.PRODUCER, "in_the_population": 31,
                      "in_the_false_cell": 0},
        "coordinates_agree_with_the_neighbour": True,
        "control": {"passed": True},
    }}
    lines = "\n".join(C.format_report(doc))
    assert "[ЗНАМЕНАТЕЛЬ РЯДА]" in lines
    assert "знаменатель ряда 200 вместо 206" in lines


# ------------------------- ЗВЕНО 4: ПОТЕРЯ ШАГА ОБЯЗАНА БЫТЬ ГРОМКОЙ

def test_the_office_schema_requires_the_step_key():
    """Ключ объявлен ОБЯЗАТЕЛЬНЫМ в схеме офиса: иначе исчезновение шага из
    артефакта прошло бы молча — дрейф, а не находка."""
    tree = ast.parse(OFFICE.read_text(encoding="utf-8"))
    required: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant)
                    and key.value == C.ARTIFACT):
                continue
            if isinstance(value, ast.Tuple):
                required.extend(el.value for el in value.elts
                                if isinstance(el, ast.Constant))
    assert required, f"схема офиса не знает артефакта {C.ARTIFACT}"
    assert STEP in required


def test_the_artifact_is_declared_by_the_bridge_stage():
    """Шаг едет в объявленном артефакте, а не в новом безымянном файле."""
    source = BRIDGE.read_text(encoding="utf-8")
    assert f'"data/{C.ARTIFACT}"' in source
    assert C.PRODUCER in source


def test_the_producer_names_the_artifact_it_writes():
    """Имя артефакта живёт ОДНОЙ строкой у производителя."""
    assert C.ARTIFACT == "rule_second_copy_census.json"
    assert C.PRODUCER.endswith("rule_second_copy_census.py")
