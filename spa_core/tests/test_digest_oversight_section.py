"""Три строки надзора в дневном отчёте владельцу (мандат владельца 29.08).

# LLM_FORBIDDEN

Сторож, который говорит только в файл, — это файл. `allocation_audit_daily.json`
и `apy_evidence.json` писались каждый день и имели на весь отчётный слой РОВНО
НОЛЬ читателей. Сторож скачков APY имел верный порог и не был позван ни разу.

Здесь проверяется не красота строк, а то, что вердикт ДОХОДИТ до человека —
и что отчёт при этом ничего не меняет в состоянии системы.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from spa_core.telegram.reports import daily as D

_GOOD_AUDIT = {
    "verdict": "VIOLATION",
    "counts": {"OK": 16, "VIOLATION": 1, "UNCHECKED": 1},
    "findings": [
        {"rule_id": "ECON-10", "verdict": "VIOLATION", "subject": "compound_v3"},
        {"rule_id": "CAP-03", "verdict": "OK", "subject": "aave_v3"},
    ],
}
_GOOD_EVIDENCE = {"counts": {"L0": 8, "L1": 0, "L2": 22, "UNCHECKED": 0},
                  "quotable_pct": 73.3}


@pytest.fixture
def ddir(tmp_path):
    (tmp_path / "allocation_audit_daily.json").write_text(
        json.dumps(_GOOD_AUDIT), encoding="utf-8")
    (tmp_path / "apy_evidence.json").write_text(
        json.dumps(_GOOD_EVIDENCE), encoding="utf-8")
    return tmp_path


def test_all_three_lines_are_present(ddir):
    out = D._build_oversight_section(ddir)
    assert "Надзор аллокации" in out
    assert "Доказанность APY" in out
    assert "Скачки APY" in out


def test_the_violation_is_NAMED_not_just_counted(ddir):
    """Положительный контроль: первая редакция читала ключи `rule`/`status`.

    Файл использует `rule_id`/`verdict`. Строка выглядела рабочей — счётчик
    показывал «нарушений 1», — а САМО нарушение не называлось никогда. Владелец
    из такой строки не может начать работу без уточняющего вопроса, а стандарт
    отчёта требует ровно обратного.
    """
    out = D._build_oversight_section(ddir)
    assert "ECON-10" in out, "нарушение посчитано, но не названо"
    assert "compound_v3" in out, "не названо, ГДЕ нарушение"


def test_an_ok_verdict_names_no_violations(ddir):
    """Обратный контроль: хвост появляется от нарушений, а не всегда."""
    (ddir / "allocation_audit_daily.json").write_text(json.dumps(
        {"verdict": "OK", "counts": {"OK": 18, "VIOLATION": 0, "UNCHECKED": 0},
         "findings": [{"rule_id": "CAP-03", "verdict": "OK", "subject": "aave_v3"}]}),
        encoding="utf-8")
    out = D._build_oversight_section(ddir)
    assert "нарушено:" not in out


def test_a_missing_source_says_so_out_loud(tmp_path):
    """Нет данных — это сигнал, а не пропущенная строка."""
    out = D._build_oversight_section(tmp_path)
    assert "Надзор аллокации" in out and "нет данных" in out
    assert "Доказанность APY" in out


def test_a_corrupt_source_never_raises(ddir):
    (ddir / "apy_evidence.json").write_text("{не json", encoding="utf-8")
    out = D._build_oversight_section(ddir)
    assert "Доказанность APY" in out and "нет данных" in out
    assert "Надзор аллокации" in out, "одна битая строка не должна съедать остальные"


def test_an_unmeasured_percentage_is_not_printed_as_a_number(ddir):
    (ddir / "apy_evidence.json").write_text(
        json.dumps({"counts": {}, "quotable_pct": None}), encoding="utf-8")
    out = D._build_oversight_section(ddir)
    assert "не измерено" in out


# --- проводка и безопасность -----------------------------------------------

def test_the_section_is_wired_into_the_message():
    """Секция, которую никто не зовёт, — это ровно та болезнь, что лечим."""
    src = Path(D.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "build_digest_message")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_build_oversight_section" in called


def test_the_three_lines_are_in_the_report_standard():
    """Пропала секция — отчёт обязан НАЗВАТЬ дыру сам."""
    markers = {m for m, _ in D._REQUIRED_BLOCKS}
    assert {"Надзор аллокации", "Доказанность APY", "Скачки APY"} <= markers


def test_the_spike_guard_is_consulted_read_only():
    """Отчёт зовёт `check_spikes` (чистая), а не `run` (телеграм + запись).

    Отчётный модуль, меняющий состояние, — это подмена свежести: сторож
    свежести после сборки отчёта увидит «всё свежее».
    """
    src = Path(D.__file__).read_text(encoding="utf-8")
    fn_src = src[src.index("def _build_oversight_section"):
                 src.index("def _standard_gaps")]
    assert "check_spikes()" in fn_src
    assert ".run(" not in fn_src, "отчёт шлёт алерты и пишет историю — это не отчёт"


def test_the_section_writes_nothing(ddir):
    before = {p.name: p.read_bytes() for p in ddir.iterdir()}
    D._build_oversight_section(ddir)
    after = {p.name: p.read_bytes() for p in ddir.iterdir()}
    assert before == after, "сборка отчёта изменила состояние на диске"
