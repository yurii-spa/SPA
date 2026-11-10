"""Ответ владельца 10.11 (вариант 1, ADR-975) ИСПОЛНЕН — ADR-976.

Окно свежести ``_EVIDENCE_MAX_AGE_H`` (36 ч) действует на ОБА источника
доказательности в ``_load_evidenced_apy``: на снимок собственного опросчика
(``adapter_orchestrator_status.json``) так же, как на ``adapter_status.json``.
До ADR-976 ветка снимка окна не применяла (ADR-969 ось C: на сдвиге часов на год
9 протоколов ``orchestrator_live`` оставались «доказанными»).

ВРЕМЯ — ВХОД, А НЕ ОКРУЖЕНИЕ: сцены строятся от одного якоря, полученного в
рантайме, и тот же якорь передаётся коду аргументом ``now=``. Литеральных дат нет.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

import spa_core.allocator.allocator as A
from spa_core.allocator.allocator import _load_evidenced_apy
from spa_core.analytics import determinism_census as DC
from spa_core.monitoring import card_acceptance as CA
from spa_core.tests._never_aging_allocator import install as install_never_aging

WINDOW_H = 36.0
PROBE = "snapshot_evidence_ages_out"


def _anchor() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _iso(moment: dt.datetime) -> str:
    return moment.isoformat()


def _scene(tmp_path: Path, anchor: dt.datetime, *, entry_age_h=None,
           generated_age_h: float = 1.0, entry_stamp: object = "auto",
           status_age_h: float = 1.0) -> tuple[Path, Path]:
    """Один протокол у КАЖДОГО источника — разведены, чтобы тай-брейк не мешал окну."""
    entry = {"protocol": "from_orchestrator", "live_data": True, "status": "ok",
             "apy_pct": 5.0}
    if entry_stamp == "auto":
        if entry_age_h is not None:
            entry["last_updated"] = _iso(anchor - dt.timedelta(hours=entry_age_h))
    elif entry_stamp is not None:
        entry["last_updated"] = entry_stamp
    orch_doc = {"adapters": [entry]}
    if generated_age_h is not None:
        orch_doc["generated_at"] = _iso(anchor - dt.timedelta(hours=generated_age_h))
    st_ts = _iso(anchor - dt.timedelta(hours=status_age_h))
    orch = tmp_path / "adapter_orchestrator_status.json"
    st = tmp_path / "adapter_status.json"
    orch.write_text(json.dumps(orch_doc), encoding="utf-8")
    st.write_text(json.dumps({"generated_at": st_ts,
                              "adapters": {"from_status": {"live_apy": 4.0,
                                                           "live_apy_as_of": st_ts}}}),
                  encoding="utf-8")
    return orch, st


# ───────────── ветка снимка: окно действует, граница — та же константа ─────────────

def test_window_constant_is_the_owner_number():
    assert A._EVIDENCE_MAX_AGE_H == WINDOW_H


def test_snapshot_entry_inside_the_window_is_evidence(tmp_path):
    anchor = _anchor()
    orch, st = _scene(tmp_path, anchor, entry_age_h=1.0)
    out = _load_evidenced_apy(orch, st, now=anchor)
    assert out["from_orchestrator"] == (pytest.approx(0.05), "orchestrator_live")
    assert out["from_status"][1] == "adapter_status_live"


def test_snapshot_entry_outside_the_window_is_not_evidence(tmp_path):
    anchor = _anchor()
    orch, st = _scene(tmp_path, anchor, entry_age_h=WINDOW_H + 0.1)
    out = _load_evidenced_apy(orch, st, now=anchor)
    assert "from_orchestrator" not in out
    assert "from_status" in out  # второй источник свеж и не пострадал


def test_the_boundary_is_inclusive_like_the_second_source(tmp_path):
    anchor = _anchor()
    orch, st = _scene(tmp_path, anchor, entry_age_h=WINDOW_H - 0.01)
    assert "from_orchestrator" in _load_evidenced_apy(orch, st, now=anchor)


def test_without_last_updated_the_snapshot_generated_at_is_the_clock(tmp_path):
    anchor = _anchor()
    orch, st = _scene(tmp_path, anchor, generated_age_h=1.0)
    assert "from_orchestrator" in _load_evidenced_apy(orch, st, now=anchor)
    orch, st = _scene(tmp_path, anchor, generated_age_h=WINDOW_H + 1.0)
    assert "from_orchestrator" not in _load_evidenced_apy(orch, st, now=anchor)


def test_unparseable_last_updated_is_not_evidence_even_with_a_fresh_generated_at(tmp_path):
    """Неразбираемая отметка ⇒ возраст неизвестен ⇒ не доказательство (fail-CLOSED)."""
    anchor = _anchor()
    orch, st = _scene(tmp_path, anchor, entry_stamp="not-a-timestamp", generated_age_h=1.0)
    assert "from_orchestrator" not in _load_evidenced_apy(orch, st, now=anchor)


def test_no_stamp_at_all_is_not_evidence(tmp_path):
    anchor = _anchor()
    orch, st = _scene(tmp_path, anchor, entry_stamp=None, generated_age_h=None)
    assert "from_orchestrator" not in _load_evidenced_apy(orch, st, now=anchor)


def test_orchestrator_only_call_applies_the_window_too(tmp_path):
    """Вызов без второго источника (``adapter_status_path=None``) — та же дверь."""
    anchor = _anchor()
    orch, _st = _scene(tmp_path, anchor, entry_age_h=WINDOW_H + 1.0)
    assert _load_evidenced_apy(orch, None, now=anchor) == {}
    orch, _st = _scene(tmp_path, anchor, entry_age_h=1.0)
    assert set(_load_evidenced_apy(orch, None, now=anchor)) == {"from_orchestrator"}


def test_one_door_one_window_for_both_sources(tmp_path, monkeypatch):
    """Одно правило — одна константа: сдвиг окна двигает ОБА источника вместе."""
    anchor = _anchor()
    orch, st = _scene(tmp_path, anchor, entry_age_h=WINDOW_H + 1.0,
                      status_age_h=WINDOW_H + 1.0)
    assert _load_evidenced_apy(orch, st, now=anchor) == {}
    monkeypatch.setattr(A, "_EVIDENCE_MAX_AGE_H", WINDOW_H + 2.0)
    assert set(_load_evidenced_apy(orch, st, now=anchor)) == {"from_orchestrator", "from_status"}
    monkeypatch.setattr(A, "_EVIDENCE_MAX_AGE_H", 0.5)
    orch, st = _scene(tmp_path, anchor, entry_age_h=1.0, status_age_h=1.0)
    assert _load_evidenced_apy(orch, st, now=anchor) == {}


def test_default_clock_is_the_wall_clock_only_when_now_is_absent(tmp_path):
    """Боевой путь без ``now`` не меняется: свежая сцена доказана, старая — нет."""
    anchor = _anchor()
    orch, st = _scene(tmp_path, anchor, entry_age_h=1.0)
    assert "from_orchestrator" in _load_evidenced_apy(orch, st)
    orch, st = _scene(tmp_path, anchor, entry_age_h=WINDOW_H + 1.0)
    assert "from_orchestrator" not in _load_evidenced_apy(orch, st)


# ───────────── прибор §26 и проба приёмки на НАСТОЯЩЕМ аллокаторе ─────────────

def test_axis_c_on_the_live_allocator_has_no_never_aging_source(tmp_path):
    anchor = _anchor()
    _scene(tmp_path, anchor, entry_age_h=1.0)
    out = DC.measure_fifth_input(str(tmp_path), offsets_h=(0.0, 8760.0), now=anchor)
    assert out["measured"], out["reason"]
    assert out["rows"][0]["apy_evidenced"] == ["from_orchestrator", "from_status"]  # сцена непуста
    assert out["never_aging"]["apy_by_source"] == {}
    assert out["never_aging"]["apy_evidenced"] == []
    assert out["counts"]["apy_at_far"] == 0


def test_probe_is_satisfied_on_the_live_allocator_scene(tmp_path):
    anchor = _anchor()
    _scene(tmp_path, anchor, entry_age_h=1.0)
    status, reason = CA.PROBES[PROBE](None, data_dir=str(tmp_path), now=anchor)
    assert status == CA.SATISFIED, reason
    assert "оба" in reason


def test_the_old_defect_is_still_reachable_and_still_caught(tmp_path, monkeypatch):
    """Контроль в другую сторону: аллокатор ДО ADR-976 прибор и проба всё ещё ловят."""
    anchor = _anchor()
    _scene(tmp_path, anchor, entry_age_h=1.0)
    install_never_aging(monkeypatch)
    out = DC.measure_fifth_input(str(tmp_path), offsets_h=(0.0, 8760.0), now=anchor)
    assert out["measured"], out["reason"]
    assert out["never_aging"]["apy_by_source"] == {"orchestrator_live": 1}
    status, reason = CA.PROBES[PROBE](None, data_dir=str(tmp_path), now=anchor)
    assert status == CA.NOT_SATISFIED, reason
    assert "orchestrator_live" in reason
