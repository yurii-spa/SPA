"""DIRECTOR-OS-UX-03 — KPI tiles of the directions, severity of problems, plain decision text.

Owner feedback 13.10: «показать все три пакета, сколько виртуальных денег на каждом, текущую доходность
каждого и общий результат; трейдинг: сколько стратегий и на какой стадии; проблемы с уровнем критичности».
Every check runs on the FIXED fixture with a fixed clock — nothing is read from production.
"""
# FROZEN-DATE-OK: injected-clock — NOW is passed to owner_view.build(model, NOW); the fixture is a fixed snapshot
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.studio_os import owner_view as ov

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "owner_view" / "mission_fixture.json"
NOW = datetime(2026, 10, 9, 7, 15, tzinfo=timezone.utc)


@pytest.fixture()
def model():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _kpis(m):
    return ov.build(m, NOW)["sections"]["overview"]["kpis"]


def test_three_package_tiles_carry_virtual_capital_from_the_canon(model):
    pk = _kpis(model)["packages"]
    assert [t["label"] for t in pk] == ["Консервативный", "Сбалансированный", "Агрессивный"]
    items = model["capital"]["package_values"]["items"]
    for t, key in zip(pk, ("conservative", "balanced", "aggressive")):
        assert t["confidence"] == "MEASURED"
        assert t["big"] == ov._usd(items[key]["nav_usd"])
        assert t["source"] == "capital.package_values"


def test_mature_package_shows_period_return_young_ones_say_early_with_a_bar(model):
    pk = _kpis(model)["packages"]
    assert "+1,41" in pk[0]["text"] and "22.06.2026–08.10.2026" in pk[0]["text"]
    assert pk[0]["state_pill"]["text"] == "работает"
    for t in pk[1:]:
        assert "рано" in t["text"] and "из 30 дней" in t["text"]
        assert t["bar"]["max"] == ov.MATURITY_DAYS and t["bar"]["value"] == 8
        assert t["state_pill"]["text"] == "собирает данные"


def test_unknown_capital_is_never_zero(model):
    m = copy.deepcopy(model)
    m["capital"].pop("package_values")
    k = _kpis(m)
    for t in k["packages"] + [k["total"]]:
        assert t["confidence"] == "NOT_MEASURED"
        assert t["big"] == "—"
        assert "$0" not in (t["text"] or "")
        assert t["text"].startswith("Не измерено")


def test_one_missing_nav_makes_the_total_unmeasured_not_partial_sum(model):
    m = copy.deepcopy(model)
    m["capital"]["package_values"]["items"]["balanced"]["nav_usd"] = None
    k = _kpis(m)
    assert k["total"]["confidence"] == "NOT_MEASURED"
    assert k["packages"][1]["confidence"] == "NOT_MEASURED"


def test_total_is_a_change_of_value_never_called_a_return(model):
    t = _kpis(model)["total"]
    items = model["capital"]["package_values"]["items"].values()
    assert t["big"] == ov._usd(sum(i["nav_usd"] for i in items))
    assert "изменение стоимости" in t["text"] and "доходност" not in t["text"]
    assert "рано" in t["secondary_short"]          # the aggregate annual figure waits for 30 days
    assert "не доходность" in t["secondary"]


def test_trading_tile_reads_the_lab_and_the_robustness_rule(model):
    from spa_core.trading_research.lifecycle import ROBUST_RULES
    t = _kpis(model)["trading"]
    assert t["big"] == str(model["truth"]["capital"]["trading_lab"]["value"]["strategies_researched"]["value"])
    assert t["bar"]["max"] == ROBUST_RULES["min_days"]
    m = copy.deepcopy(model)
    m["truth"]["capital"].pop("trading_lab")
    assert _kpis(m)["trading"]["confidence"] == "NOT_MEASURED"


def test_bar_is_drawn_only_with_a_measurable_denominator():
    t = ov.kpi("x", "1", "y", confidence="MEASURED", source=None, measured_at=None, updated_at=None,
               bar={"value": 3, "max": None})
    assert "bar" not in t


@pytest.mark.parametrize("code,agent,expected", [
    ("retired_but_loaded", "com.spa.weekly_backup", "info"),
    ("exit_nonzero:1", "com.spa.daily_backup", "critical"),
    ("exit_nonzero:1", "com.spa.swarm_health", "important"),
    ("log_missing__never_ran", "com.spa.monthly_statement", "info"),
    ("something_new", None, "important"),          # unknown is never downplayed
])
def test_severity_is_deterministic_and_fail_closed(code, agent, expected):
    sev, threat = ov._severity(code, agent, 3)
    assert sev == expected and threat


def test_protection_lists_problems_by_severity_with_threat_and_disabled_actions(model):
    p = ov.build(model, NOW)["sections"]["protection"]
    rows = p["problems"]["rows"]
    order = [ov.SEVERITY_ORDER.index(r["severity"]) for r in rows]
    assert order == sorted(order)
    assert all(r["threat"] and r["severity_ru"] in ov.SEVERITY_RU.values() for r in rows)
    assert "нужно" in p["problems"]["actions_note"] or "решения" in p["problems"]["actions_note"]
    assert p["level"].startswith("Уровень защиты:")


def test_decision_full_text_in_plain_words_is_complete_and_has_no_codes(model):
    d = ov.build(model, NOW)["sections"]["decisions"]
    cards = _walk_cards(d)
    assert any(c.get("full_available") for c in cards), "fixture carries full owner cards"
    for c in cards:
        if not c.get("full_available"):
            continue
        assert len(c["full_plain"]) == len(c["full"])
        for sec in c["full_plain"]:
            assert not ov.jargon_hits(sec["text"]), sec["text"][:120]
            assert "((" not in sec["text"]


def _walk_cards(node):
    out = []
    if isinstance(node, dict):
        if "full_plain" in node:
            out.append(node)
        for v in node.values():
            out.extend(_walk_cards(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_cards(v))
    return out


def test_no_jargon_on_the_new_main_texts(model):
    v = ov.build(model, NOW)["sections"]
    hits = [(p, ov.jargon_hits(t)) for p, t in ov.main_texts(v) if ov.jargon_hits(t)]
    assert hits == []
