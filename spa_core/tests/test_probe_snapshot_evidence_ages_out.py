"""Проба `snapshot_evidence_ages_out` (ADR-975): окно свежести действует на ОБА источника.

Контроль в обе стороны на настоящем приборе §26 (`determinism_census.measure_fifth_input`)
и на сцене каталога данных; третий исход — отдельно. Даты сцены строятся от входа `now`.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from spa_core.analytics import determinism_census as DC
from spa_core.monitoring import card_acceptance as CA

PROBE = "snapshot_evidence_ages_out"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _scene(tmp_path, now: dt.datetime) -> str:
    """Снимок оркестратора и adapter_status с наблюдениями «сейчас»."""
    ts = now.isoformat()
    (tmp_path / "adapter_orchestrator_status.json").write_text(json.dumps({
        "generated_at": ts,
        "adapters": [{"protocol": "aave_v3", "live_data": True, "status": "ok", "apy_pct": 3.1}],
    }), encoding="utf-8")
    (tmp_path / "adapter_status.json").write_text(json.dumps({
        "generated_at": ts,
        "adapters": {"maple": {"live_apy": 0.05, "live_apy_as_of": ts}},
    }), encoding="utf-8")
    return str(tmp_path)


def test_probe_is_registered_and_declares_its_inputs():
    assert PROBE in CA.PROBES
    assert CA.validate_spec(PROBE) is None
    assert "data_dir" in CA.probe_tree_inputs(PROBE)


def test_probe_on_the_scene_names_the_source_that_never_ages(tmp_path, monkeypatch):
    """ИЗМЕНЕНО НАМЕРЕННО (ADR-976, инв. #16): живой аллокатор исполняет ответ
    владельца 10.11 и этот исход на нём больше не достижим; прежний исход сохранён
    СЦЕНОЙ — двойником аллокатора образца 09.11. Проба НЕ правилась (п. 2 правила
    приёмки) — сменился исход дерева, и живой исход меряет соседний тест."""
    from spa_core.tests._never_aging_allocator import install
    install(monkeypatch)
    now = _now()
    status, reason = CA.PROBES[PROBE](None, data_dir=_scene(tmp_path, now), now=now)
    # Контроль со стороны прибора: adapter_status на дальнем сдвиге выпал, оркестратор — нет.
    fifth = DC.measure_fifth_input(str(tmp_path), now=now)
    assert fifth["measured"]
    assert status == CA.NOT_SATISFIED, reason
    assert "orchestrator_live" in reason and "не стареет" in reason


def test_probe_on_the_live_allocator_scene_is_satisfied(tmp_path):
    """ADR-976: на живом аллокаторе окно действует на оба источника — проба `satisfied`."""
    now = _now()
    status, reason = CA.PROBES[PROBE](None, data_dir=_scene(tmp_path, now), now=now)
    assert status == CA.SATISFIED, reason
    assert "оба" in reason


def test_probe_satisfied_when_the_far_offset_leaves_nothing(tmp_path, monkeypatch):
    def aged(data_dir, offsets_h=DC.CLOCK_OFFSETS_H, now=None):
        return {"measured": True, "max_age_h": 36.0,
                "never_aging": {"offset_h": 8760.0, "apy_by_source": {}}}
    monkeypatch.setattr(DC, "measure_fifth_input", aged)
    status, reason = CA.PROBES[PROBE](None, data_dir=str(tmp_path), now=_now())
    assert status == CA.SATISFIED and "оба" in reason


def test_probe_three_outcomes_are_distinct(tmp_path, monkeypatch):
    # снимков нет ⇒ не измерено, а не «исполнено» и не «находка»
    status, reason = CA.PROBES[PROBE](None, data_dir=str(tmp_path / "nowhere"), now=_now())
    assert status == CA.UNMEASURED and "НЕ ИЗМЕРЕНО" in reason
    # аргумент пробе не положен
    assert CA.PROBES[PROBE]("x", data_dir=str(tmp_path))[0] == CA.UNMEASURED
    # прибор ответил без дальнего сдвига ⇒ не измерено
    monkeypatch.setattr(DC, "measure_fifth_input",
                        lambda d, offsets_h=None, now=None: {"measured": True, "never_aging": {}})
    assert CA.PROBES[PROBE](None, data_dir=str(tmp_path))[0] == CA.UNMEASURED


def test_probe_import_failure_is_unmeasured(monkeypatch):
    import sys
    import spa_core.analytics as pkg
    monkeypatch.delattr(pkg, "determinism_census", raising=False)
    monkeypatch.setitem(sys.modules, "spa_core.analytics.determinism_census", None)
    status, reason = CA.PROBES[PROBE](None)
    assert status == CA.UNMEASURED and "не импортирован" in reason


def test_probe_is_not_a_substring_match():
    with pytest.raises(KeyError):
        CA.PROBES["snapshot_evidence"]
