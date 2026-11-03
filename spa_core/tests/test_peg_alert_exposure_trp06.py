"""TRP-06: уведомление о депеге несёт затронутую экспозицию, устойчивый ID и не прячется фильтром по позиции.

Приёмка (бэклог TRP): повторная доставка не повторяет событие, смена причины учитывается; фильтр по позиции не
скрывает угрозу данным и риск ПЛАНИРУЕМОЙ сделки; бумажный нотионал не выдаётся за реальные деньги. Транспорт
перехвачен — в чат владельца из теста не уходит ничего."""
import json

import pytest

from spa_core.monitoring import peg_monitor as pm
from spa_core.telegram import push_policy


@pytest.fixture
def scene(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(push_policy, "push_critical", lambda *a, **k: calls.append((a, k)) or True)
    (tmp_path / "current_positions.json").write_text(json.dumps({"positions": {"aave_v3": 20000.0}}))
    (tmp_path / "allocation_rationale.json").write_text(json.dumps(
        {"admissible_trim": {"target_after": {"aave_v3": 20000.0, "morpho_blue": 3529.41}}}))
    return pm.PegStabilityMonitor(data_path=str(tmp_path), use_alert_dispatcher=False), calls, tmp_path


def _st(aid, status="CRITICAL"):
    return pm.PegStatus(adapter_id=aid, asset="USDC", chain="ethereum", current_price=0.95, deviation_pct=5.0,
                        status=status, last_checked="t")


def test_held_protocol_pushes_with_paper_exposure_and_a_stable_id(scene):
    m, calls, _ = scene
    m._push_peg_break(_st("aave_v3"), "Peg CRITICAL", "body")
    a, k = calls[-1]
    assert k["held_protocol"] is True and k["dedup_key"] == "peg:aave_v3:CRITICAL"
    assert "удерживается в бумажной книге $20,000 (не реальные деньги)" in a[3]


def test_planned_exposure_is_not_hidden_by_the_position_filter(scene):
    m, calls, _ = scene
    m._push_peg_break(_st("morpho_blue"), "Peg CRITICAL", "body")
    a, k = calls[-1]
    assert k["held_protocol"] is True                                   # прежде — False ⇒ дайджест
    assert "ПЛАНИРУЕТСЯ" in a[3] and "$3,529" in a[3]


def test_unreadable_positions_are_unmeasured_and_still_push(scene):
    m, calls, tmp = scene
    (tmp / "current_positions.json").write_text("{broken")
    m._push_peg_break(_st("aave_v3"), "Peg CRITICAL", "body")
    a, k = calls[-1]
    assert k["held_protocol"] is True and "НЕ ИЗМЕРЕНА" in a[3]


def test_untouched_protocol_stays_scoped_and_the_cause_is_part_of_the_id(scene):
    m, calls, _ = scene
    m._push_peg_break(_st("frax_somewhere"), "Peg CRITICAL", "body")
    assert calls[-1][1]["held_protocol"] is False and "не затронуты" in calls[-1][0][3]
    m._push_peg_break(_st("aave_v3", "WARNING"), "Peg WARNING", "body")
    assert calls[-1][1]["dedup_key"] == "peg:aave_v3:WARNING"           # смена причины — другой отпечаток


def test_the_edge_trigger_keeps_redelivery_silent(tmp_path):
    """Повторная доставка того же события молчит — проверка на НАСТОЯЩЕМ push_policy (без транспорта)."""
    kw = dict(held_protocol=True, data_dir=tmp_path, send=False, dedup_key="peg:aave_v3:CRITICAL")
    assert push_policy.push_critical("peg_break", "CRITICAL", "t", "b", **kw) is True     # первая доставка
    assert push_policy.push_critical("peg_break", "CRITICAL", "t", "b", **kw) is False    # повтор — молчит
    kw2 = dict(kw, dedup_key="peg:aave_v3:WARNING")
    assert push_policy.push_critical("peg_break", "CRITICAL", "t", "b", **kw2) is True    # смена причины — пушит
