"""Контроль пробы приёмки `apy_name_carries_one_kind` (ADR-953).

Правило `.claude/rules/acceptance.md`, п. 3: проба регистрируется ТОЛЬКО с
тестом, где она зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном звене — с
названным звеном, — и где она НЕ проходит подстрокой (ADR-333).

FROZEN-DATE-OK: injected-clock — якорь `_NOW` объявлен литералом, обе стороны
сравнения от него ПРОИСХОДЯТ (отметка сцены = `_NOW - timedelta(...)`), и сам
`_NOW` уезжает в пробу аргументом `now=`. Стенных часов в файле нет ни одной
двери: подпроцессов проба не поднимает (§ «ИНЪЕКЦИЯ ЧАСОВ КОНЧАЕТСЯ НА ГРАНИЦЕ
ПОДПРОЦЕССА», `.claude/rules/deployment.md`).
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` объявлен литералом, отметка сцены
# ПРОИСХОДИТ от него (`_NOW - timedelta(...)`), и сам `_NOW` уезжает в пробу
# аргументом `now=`: обе стороны сравнения закреплены, календарь на вердикт не
# влияет. Подпроцессов проба не поднимает — второй двери к часам нет.
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring.card_acceptance import (
    APY_CENSUS_MAX_AGE_H,
    NOT_SATISFIED,
    SATISFIED,
    UNMEASURED,
)

_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)

_WHOLE_SECTION = {
    "status": "OK",
    "engine": "apy_name_census",
    "verdict": "FINDINGS",
    "paths_found": 8,
    "paths_declared": 8,
    "undeclared": [],
    "findings": ["ОДИН ПРЕДМЕТ — 3 ЧИСЛА: …"],
    "unmeasured": [],
}


def _scene(tmp_path: Path, monkeypatch, *, section=_WHOLE_SECTION,
           age_h: float = 1.0, stamp=..., sections=...) -> tuple[str, str]:
    """Собрать дерево со своим `data/` и спросить пробу. Часы — ВХОД."""
    monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
    (tmp_path / "data").mkdir(exist_ok=True)
    doc: dict = {}
    if stamp is ...:
        doc["generated_at"] = (_NOW - timedelta(hours=age_h)).isoformat()
    elif stamp is not None:
        doc["generated_at"] = stamp
    if sections is ...:
        doc["sections"] = {} if section is None else {"apy_name_census": section}
    elif sections is not None:
        doc["sections"] = sections
    (tmp_path / "data" / "analytics_summary.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return ca.PROBES["apy_name_carries_one_kind"](None, now=_NOW)


# ---------------------------------------------------------------------------
# Целый контур
# ---------------------------------------------------------------------------

def test_whole_contour_is_satisfied(tmp_path, monkeypatch):
    verdict, why = _scene(tmp_path, monkeypatch)
    assert verdict == SATISFIED, why
    assert "8" in why


def test_producer_findings_do_NOT_decide_the_verdict(tmp_path, monkeypatch):
    """Разброс ставок — свойство ПРОИЗВОДИТЕЛЕЙ; запирать критерий на них нельзя."""
    sec = dict(_WHOLE_SECTION, findings=["a", "b", "c", "d"])
    verdict, why = _scene(tmp_path, monkeypatch, section=sec)
    assert verdict == SATISFIED
    assert "4" in why


# ---------------------------------------------------------------------------
# Каждое порванное звено — красное, и звено НАЗВАНО
# ---------------------------------------------------------------------------

def test_link_missing_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
    verdict, why = ca.PROBES["apy_name_carries_one_kind"](None, now=_NOW)
    assert verdict == UNMEASURED
    assert "нет в этом дереве" in why


def test_link_unparsable_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "REPO_ROOT", str(tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "analytics_summary.json").write_text("{не json",
                                                              encoding="utf-8")
    verdict, why = ca.PROBES["apy_name_carries_one_kind"](None, now=_NOW)
    assert verdict == UNMEASURED
    assert "не разобран" in why


def test_link_no_timestamp(tmp_path, monkeypatch):
    verdict, why = _scene(tmp_path, monkeypatch, stamp=None)
    assert verdict == UNMEASURED
    assert "без generated_at" in why


def test_link_unparsable_timestamp(tmp_path, monkeypatch):
    verdict, why = _scene(tmp_path, monkeypatch, stamp="вчера")
    assert verdict == UNMEASURED
    assert "возраст не измерен" in why


def test_link_stale_artifact_is_unmeasured_never_not_satisfied(tmp_path, monkeypatch):
    verdict, why = _scene(tmp_path, monkeypatch, age_h=APY_CENSUS_MAX_AGE_H + 1.0)
    assert verdict == UNMEASURED
    assert "протух" in why


def test_link_fresh_edge_is_still_measured(tmp_path, monkeypatch):
    """Контроль порога в обе стороны: внутри предела вердикт ЕСТЬ."""
    verdict, _ = _scene(tmp_path, monkeypatch, age_h=APY_CENSUS_MAX_AGE_H - 0.1)
    assert verdict == SATISFIED


def test_link_no_sections_block(tmp_path, monkeypatch):
    verdict, why = _scene(tmp_path, monkeypatch, sections="не словарь")
    assert verdict == UNMEASURED
    assert "нет раздела sections" in why


def test_link_section_not_produced_yet(tmp_path, monkeypatch):
    verdict, why = _scene(tmp_path, monkeypatch, section=None)
    assert verdict == UNMEASURED
    assert "ещё не производил" in why


def test_link_section_crashed_in_the_cycle(tmp_path, monkeypatch):
    sec = {"status": "ERROR", "engine": "apy_name_census",
           "error": "KeyError: 'daily'"}
    verdict, why = _scene(tmp_path, monkeypatch, section=sec)
    assert verdict == UNMEASURED
    assert "KeyError" in why


def test_link_census_reported_unmeasured(tmp_path, monkeypatch):
    sec = dict(_WHOLE_SECTION, verdict="UNMEASURED",
               unmeasured=["паритет не измерен: книга не прочитана"])
    verdict, why = _scene(tmp_path, monkeypatch, section=sec)
    assert verdict == UNMEASURED
    assert "книга не прочитана" in why


def test_link_undeclared_field_absent_is_not_a_zero(tmp_path, monkeypatch):
    sec = {k: v for k, v in _WHOLE_SECTION.items() if k != "undeclared"}
    verdict, why = _scene(tmp_path, monkeypatch, section=sec)
    assert verdict == UNMEASURED
    assert "нулём не является" in why


def test_link_zero_numbers_found_is_unmeasured(tmp_path, monkeypatch):
    sec = dict(_WHOLE_SECTION, paths_found=0)
    verdict, why = _scene(tmp_path, monkeypatch, section=sec)
    assert verdict == UNMEASURED
    assert "НИ ОДНОГО" in why


# ---------------------------------------------------------------------------
# Настоящий отказ: род не объявлен
# ---------------------------------------------------------------------------

def test_undeclared_path_is_not_satisfied_and_names_the_path(tmp_path, monkeypatch):
    sec = dict(_WHOLE_SECTION,
               undeclared=[{"path": "sections/new_engine/blended_apy_pct",
                            "n": 1, "sample": 7.5}])
    verdict, why = _scene(tmp_path, monkeypatch, section=sec)
    assert verdict == NOT_SATISFIED
    assert "sections/new_engine/blended_apy_pct" in why


# ---------------------------------------------------------------------------
# ADR-333: подстрокой не проходит
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sec", [
    # Поля есть, но ТИПЫ не те: перечень — строкой, население — строкой.
    dict(_WHOLE_SECTION, undeclared="[]"),
    dict(_WHOLE_SECTION, paths_found="8"),
    # Секция — строка, в которой написаны все нужные слова.
    "status OK verdict clean undeclared [] paths_found 8",
])
def test_right_words_wrong_shape_never_satisfy(tmp_path, monkeypatch, sec):
    verdict, why = _scene(tmp_path, monkeypatch, section=sec)
    assert verdict == UNMEASURED, why


def test_probe_is_registered_under_its_name():
    assert "apy_name_carries_one_kind" in ca.PROBES
