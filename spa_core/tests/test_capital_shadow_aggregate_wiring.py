"""E6.3 кандидат подключения: совокупный допуск к ``run_cycle`` — выключен по умолчанию, книга «до» неисполненных.

Главная сцена — двойной учёт: бумажная книга УЖЕ содержит сделку, из которой построено намерение. Судить намерение
против текущей книги значит посчитать её капитал дважды; правильная база — книга до неисполненных намерений.
Обратный контроль: голый ``aggregate.admit`` на ТЕКУЩЕЙ книге отказывает той же заявке."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.capital_shadow import aggregate as ag
from spa_core.capital_shadow import aggregate_wiring as aw
from spa_core.capital_shadow import contract, intent as intent_mod, machine, run as run_mod

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — verdicts(now=NOW), run_cycle(now=NOW)


def _scene(tmp_path, *, positions=None, cash=5_000.0, equity=100_000.0, registry=True):
    """Книга conservative ПОСЛЕ сделки «+20 000 в aave»: кэш 25 000 → 5 000, aave 20 000 → 40 000."""
    (tmp_path / "current_positions.json").write_text(json.dumps({
        "current_equity_usd": equity, "cash_usd": cash,
        "positions": positions if positions is not None else {"aave_v3": 40_000.0, "maple": 20_000.0,
                                                              "compound_v3": 35_000.0}}))
    (tmp_path / "trades.json").write_text(json.dumps([{"trade_id": "t1", "ts": "2026-11-01T11:00:00Z"}]))
    if registry:
        (tmp_path / "adapter_registry.json").write_text(json.dumps({"adapters": {
            "aave_v3": {"tier": 1}, "compound_v3": {"tier": 1}, "maple": {"tier": 2}}}))
    digest, _, _ = intent_mod.book_digest_and_asof(tmp_path, "trades.json")
    return digest


def _intent(iid, proto, usd, digest, *, action=contract.ACTION_SUPPLY, ttl_h=6, strategy="s"):
    return {"intent_id": iid, "sleeve_id": "defi_conservative", "strategy_id": strategy, "action_type": action,
            "network_or_venue": proto, "notional": usd, "expires_at": (NOW + timedelta(hours=ttl_h)).isoformat(),
            "policy_version": contract.POLICY_VERSION, "risk_snapshot": {"book_state_digest": {"value": digest}}}


def test_the_trade_already_in_the_book_is_not_counted_twice(tmp_path):
    d = _scene(tmp_path)
    it = _intent("a", "aave_v3", 20_000, d)
    res = aw.verdicts(tmp_path, [it], NOW)["defi_conservative"]
    assert res["verdicts"]["a"]["verdict"] == ag.ADMIT, res
    assert res["basis"].startswith("книга до неисполненных") and res["unexecuted"] == ["a"]
    # обратный контроль: та же заявка против ТЕКУЩЕЙ книги — кэш 5 000 − 20 000 < 5 % ⇒ отказ (двойной учёт)
    raw = ag.Book(nav_usd=100_000.0, cash_usd=5_000.0,
                  positions_usd={"aave_v3": 40_000.0, "maple": 20_000.0, "compound_v3": 35_000.0},
                  policy_version=contract.POLICY_VERSION, book_state_digest=d)
    assert ag.admit(raw, [it], now=NOW)["a"]["verdict"] == ag.REFUSE


def test_a_set_that_breaches_together_is_still_refused_on_the_pre_trade_basis(tmp_path):
    """База «до» не отменяет совокупность: две покупки, вместе выше потолка протокола (40 %), — отказ второй."""
    d = _scene(tmp_path, positions={"aave_v3": 50_000.0}, cash=50_000.0)
    res = aw.verdicts(tmp_path, [_intent("a", "aave_v3", 15_000, d),
                                 _intent("b", "aave_v3", 15_000, d, strategy="t")], NOW)["defi_conservative"]
    # база: aave 20 000, кэш 80 000; a → 35 %, b → 50 % > 40 %
    assert res["verdicts"]["a"]["verdict"] == ag.ADMIT and res["verdicts"]["b"]["verdict"] == ag.REFUSE


def test_tiers_come_from_the_registry_and_an_unknown_protocol_is_refused(tmp_path):
    # книга ПОСЛЕ сделки +15 000 в maple (T2): maple 25 000, кэш 75 000; база — maple 10 000 ⇒ +15 000 = 25 % > 20 %
    d = _scene(tmp_path, positions={"maple": 25_000.0}, cash=75_000.0)
    res = aw.verdicts(tmp_path, [_intent("a", "maple", 15_000, d)], NOW)["defi_conservative"]
    assert res["tiers"] == "реестр адаптеров"
    assert res["verdicts"]["a"]["verdict"] == ag.REFUSE and "потолка тира 20%" in res["verdicts"]["a"]["why"]
    d2 = _scene(tmp_path, positions={"maple": 25_000.0, "nobody": 1_000.0}, cash=74_000.0)
    res2 = aw.verdicts(tmp_path, [_intent("b", "nobody", 1_000, d2)], NOW)["defi_conservative"]
    assert res2["verdicts"]["b"]["verdict"] == ag.REFUSE and "не известен" in res2["verdicts"]["b"]["why"]


def test_without_a_registry_the_tier_axis_is_named_unchecked(tmp_path):
    d = _scene(tmp_path, registry=False)
    res = aw.verdicts(tmp_path, [_intent("a", "aave_v3", 20_000, d)], NOW)["defi_conservative"]
    assert res["tiers"].startswith("НЕ ПРОВЕРЕНЫ") and res["verdicts"]["a"]["unchecked"] == ["tier_caps"]


def test_unreadable_book_refuses_not_zero(tmp_path):
    d = _scene(tmp_path)
    (tmp_path / "current_positions.json").write_text("{not json")
    res = aw.verdicts(tmp_path, [_intent("a", "aave_v3", 1_000, d)], NOW)["defi_conservative"]
    assert res["state"] == "UNKNOWN" and res["verdicts"]["a"]["verdict"] == ag.REFUSE


def test_a_pending_intent_from_an_earlier_cycle_holds_its_reservation(tmp_path):
    """Незавершённое прошлое намерение (на ledger, до SHADOW_EXECUTED) вычитается из базы И держит резерв: его
    капитал не становится свободным. Книга после обеих сделок: compound 30 000 (прошлая), aave 10 000 (текущая),
    maple 30 000, кэш 30 000. База: кэш 70 000; резерв 30 000; текущая 10 000 ⇒ кэш после = 30 %.
    Если бы резерв потерялся, было бы 60 % — это и есть мера, а не только слово «допущено»."""
    d = _scene(tmp_path, positions={"compound_v3": 30_000.0, "aave_v3": 10_000.0, "maple": 30_000.0}, cash=30_000.0)
    old = _intent("old", "compound_v3", 30_000, d, strategy="prev")
    machine.record_intent(tmp_path, old, NOW - timedelta(hours=1))
    assert [i["intent_id"] for i in aw.pending_intents(tmp_path, NOW)] == ["old"]
    res = aw.verdicts(tmp_path, [_intent("a", "aave_v3", 10_000, d)], NOW)["defi_conservative"]
    v = res["verdicts"]["a"]
    assert v["verdict"] == ag.ADMIT and res["unexecuted"] == ["a", "old"]
    assert abs(v["cash_share_after"] - 0.30) < 1e-9, v
    # истёкшее прошлое намерение — не резерв и не вычитается
    assert aw.pending_intents(tmp_path, NOW + timedelta(hours=7)) == []


def _cycle(tmp_path, monkeypatch, intents, mode):
    calls = []
    monkeypatch.setattr(intent_mod, "build_current_intents", lambda *a, **k: intents)
    monkeypatch.setattr(run_mod, "_validate", lambda *a, **k: True)
    monkeypatch.setattr(run_mod, "_simulate_and_execute",
                        lambda dd, it, now, **k: calls.append(it["intent_id"]) or {"intent_id": it["intent_id"],
                                                                                     "outcome": "SIMULATED"})
    monkeypatch.setattr(run_mod, "_run_forward_reconciliation", lambda *a, **k: [])
    kw = {} if mode is None else {"aggregate_mode": mode}
    return run_mod.run_cycle(tmp_path, NOW, simulate_mod=object(), **kw), calls


@pytest.mark.parametrize("mode", [None, "off"])
def test_off_is_the_default_and_changes_nothing(tmp_path, monkeypatch, mode):
    d = _scene(tmp_path, positions={"aave_v3": 50_000.0}, cash=50_000.0)
    s, calls = _cycle(tmp_path, monkeypatch, [_intent("a", "aave_v3", 15_000, d),
                                              _intent("b", "aave_v3", 15_000, d, strategy="t")], mode)
    assert "aggregate" not in s and calls == ["a", "b"]


def test_shadow_reports_and_enforce_stops_the_refused_intent(tmp_path, monkeypatch):
    d = _scene(tmp_path, positions={"aave_v3": 50_000.0}, cash=50_000.0)
    ints = [_intent("a", "aave_v3", 15_000, d), _intent("b", "aave_v3", 15_000, d, strategy="t")]
    s, calls = _cycle(tmp_path, monkeypatch, ints, "shadow")
    assert calls == ["a", "b"] and s["aggregate"]["books"]["defi_conservative"]["verdicts"]["b"]["verdict"] == ag.REFUSE
    s2, calls2 = _cycle(tmp_path, monkeypatch, ints, "enforce")
    assert calls2 == ["a"]
    assert {r["intent_id"]: r["outcome"] for r in s2["per_intent"]}["b"] == "AGGREGATE_REFUSED"


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        run_mod.run_cycle("/nonexistent", NOW, aggregate_mode="on")
