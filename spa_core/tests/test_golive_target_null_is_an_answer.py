"""Обнулённый срок go-live — ОТВЕТ гейта, а не отсутствие входа (ADR-277).

Замер 2026-09-09. Правка карточки «Производители устаревших чисел сайта» обнуляет
`golive_status.target_date`, как только временной гейт пройден: проекция «якорь + 29 дней»
оказывается в прошлом и перестаёт быть сроком (гейт печатал 2026-07-21 при 77/30 днях).
Но у поля ТРИ потребителя, и каждый при пустом значении подставлял свой литерал
**той же самой даты 2026-07-21** — то есть правка перенесла бы ложь из одного места в три:

* `spa_core/paper_trading/progress_tracker.py` → `GO_LIVE_TARGET_DATE = "2026-07-21"`;
* `spa_core/paper_trading/paper_evidence_tracker.py` → `GOLIVE_TARGET_DATE = 2026-07-21`;
* `spa_core/golive/readiness_score.py` → `TARGET_DATE = "2026-07-21"`.

Правило: файл гейта ПРОЧИТАН и даты нет ⇒ `None` («срок не применяется»); литерал остаётся
только для «файл не прочитан» — там мы действительно не знаем.

# FROZEN-DATE-OK: historical-incident — дата 2026-07-21 и есть предмет теста (конкретный
# литерал, который подставлялся вместо ответа гейта); живых часов в файле нет.
"""
from __future__ import annotations

import json

import pytest

from spa_core.golive import readiness_score as rs
from spa_core.paper_trading import paper_evidence_tracker as pet
from spa_core.paper_trading import progress_tracker as pt

STALE_LITERAL = "2026-07-21"


def _gate(tmp_path, doc: dict | None):
    if doc is not None:
        (tmp_path / "golive_status.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


# ── progress_tracker ──────────────────────────────────────────────────────────────────
def test_progress_tracker_does_not_substitute_the_stale_literal(tmp_path, monkeypatch):
    _gate(tmp_path, {"target_date": None, "go_live_state": "gate_passed_owner_decision_pending"})
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": []}), encoding="utf-8")
    rep = pt.build_progress_report(str(tmp_path)) if hasattr(pt, "build_progress_report") else None
    if rep is None:                      # имя функции могло измениться — тогда это НЕ «прошло»
        pytest.fail("в progress_tracker не нашлось сборщика отчёта — проверка не состоялась")
    assert rep.get("go_live_target_date") != STALE_LITERAL
    assert rep.get("go_live_target_date") is None
    assert rep.get("go_live_state") == "gate_passed_owner_decision_pending"


def test_progress_tracker_keeps_a_real_date_when_the_gate_gives_one(tmp_path):
    _gate(tmp_path, {"target_date": "2027-01-01", "go_live_state": "gate_in_progress"})
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": []}), encoding="utf-8")
    rep = pt.build_progress_report(str(tmp_path))
    assert rep.get("go_live_target_date") == "2027-01-01"


# ── paper_evidence_tracker ────────────────────────────────────────────────────────────
def test_paper_evidence_tracker_returns_none_when_the_gate_emits_no_date(tmp_path, monkeypatch):
    _gate(tmp_path, {"target_date": None})
    monkeypatch.setattr(pet, "GOLIVE_STATUS_FILE", str(tmp_path / "golive_status.json"))
    assert pet._golive_target_iso() is None


def test_paper_evidence_tracker_falls_back_only_when_the_file_is_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(pet, "GOLIVE_STATUS_FILE", str(tmp_path / "nope.json"))
    assert pet._golive_target_iso() == STALE_LITERAL


def test_paper_evidence_tracker_keeps_a_real_date(tmp_path, monkeypatch):
    _gate(tmp_path, {"target_date": "2027-03-04"})
    monkeypatch.setattr(pet, "GOLIVE_STATUS_FILE", str(tmp_path / "golive_status.json"))
    assert pet._golive_target_iso() == "2027-03-04"


# ── readiness_score ───────────────────────────────────────────────────────────────────
def test_readiness_score_says_the_countdown_is_not_about_anything(tmp_path):
    rec = rs._schedule_component(_gate(tmp_path, {"target_date": None}))
    assert rec["target_date"] is None and rec["days_to_golive"] is None
    assert "срок не применяется" in rec["note"]


def test_readiness_score_falls_back_only_when_the_file_is_unreadable(tmp_path):
    rec = rs._schedule_component(_gate(tmp_path, None))
    assert rec["target_date"] == STALE_LITERAL


# ── общий контроль класса ─────────────────────────────────────────────────────────────
def test_no_consumer_turns_an_absent_date_into_the_stale_literal(tmp_path, monkeypatch):
    """Один контроль на весь класс: пустой ответ гейта не превращается в 2026-07-21 нигде."""
    gate = _gate(tmp_path, {"target_date": None, "go_live_state": "gate_in_progress"})
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps({"daily": []}), encoding="utf-8")
    monkeypatch.setattr(pet, "GOLIVE_STATUS_FILE", str(gate / "golive_status.json"))
    values = [
        pt.build_progress_report(str(gate)).get("go_live_target_date"),
        pet._golive_target_iso(),
        rs._schedule_component(gate)["target_date"],
    ]
    assert values == [None, None, None], values


def test_buffer_days_is_none_when_there_is_no_target(tmp_path, monkeypatch):
    """Срока нет ⇒ и запаса до него нет. «0 дней запаса» было бы утверждением, а не отказом."""
    _gate(tmp_path, {"target_date": None})
    monkeypatch.setattr(pet, "GOLIVE_STATUS_FILE", str(tmp_path / "golive_status.json"))
    import inspect
    src = inspect.getsource(pet)
    assert "if golive_target is not None else None" in src, (
        "buffer_days снова считается от отсутствующей даты — упадёт на None")
