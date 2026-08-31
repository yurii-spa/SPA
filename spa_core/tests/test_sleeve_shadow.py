# FROZEN-DATE-OK: синтетические forward-даты фикстур; обе стороны сравнения
# запинены, часы модуль не читает (date_str — вход).
"""ADR-201 — тень слива 50/30/20 с рычагом пропорций CIO.

Три свойства несут решение и потому тестируются жёстко:
(1) тень НЕ выдумывает: день без forward-точки компонента = UNCHECKED, не ноль;
(2) рычаг пропорций ограничен: ±10пп жёстко, за границей REFUSED и вес не меняется,
    между применёнными сдвигами ≥7 дней, недостающая метрика ⇒ HOLD;
(3) каждое ревью — запись с decision_id, молчаливых сдвигов не существует.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

from spa_core.strategy_lab.sleeve.composer import (
    ANCHOR,
    CASH_SLOT,
    SleeveConfig,
    append_ledger,
    compose_day,
    load_ledger,
    review_proportions,
    run_sleeve_shadow,
)


# ── compose_day: честность дня ──────────────────────────────────────────────


def test_compose_day_weighted_sum_with_cash_slot_at_zero():
    w = {"pendle_pt_levered": 0.5, ANCHOR: 0.3, CASH_SLOT: 0.2}
    r = compose_day(w, {"pendle_pt_levered": 0.02, ANCHOR: 0.001})
    assert abs(r - (0.5 * 0.02 + 0.3 * 0.001 + 0.2 * 0.0)) < 1e-12


def test_compose_day_missing_component_is_unchecked_not_partial():
    w = {"pendle_pt_levered": 0.5, ANCHOR: 0.3, CASH_SLOT: 0.2}
    assert compose_day(w, {"pendle_pt_levered": 0.02, ANCHOR: None}) is None


# ── review_proportions: рычаг CIO ───────────────────────────────────────────


def _healthy_eq(n=30):
    return [100000.0 * (1.0 + 0.0005 * i) for i in range(n)]


def _breached_eq(n=30, dd=0.20):
    up = [100000.0 * (1.0 + 0.001 * i) for i in range(n // 2)]
    return up + [up[-1] * (1.0 - dd)] * (n - n // 2)


def test_review_all_healthy_holds_base():
    cfg = SleeveConfig()
    out = review_proportions(
        config=cfg, current_weights=dict(cfg.base_weights),
        trailing_equity={"pendle_pt_levered": _healthy_eq(), ANCHOR: _healthy_eq()},
        days_since_last_applied=None)
    assert out["status"] == "HOLD_HEALTHY"


def test_review_dd_breach_shifts_ten_pp_to_anchor():
    cfg = SleeveConfig()
    out = review_proportions(
        config=cfg, current_weights=dict(cfg.base_weights),
        trailing_equity={"pendle_pt_levered": _breached_eq(dd=0.20),  # 20% > 2×7.6%
                         ANCHOR: _healthy_eq()},
        days_since_last_applied=None)
    assert out["status"] == "PROPOSE_APPLIED"
    assert out["new_weights"]["pendle_pt_levered"] == 0.40
    assert out["new_weights"][ANCHOR] == 0.40


def test_review_second_shift_is_refused_out_of_bounds():
    """База 50/30; после одного сдвига 40/40 — второй увёл бы якорь на +20пп
    от базы. Граница ±10пп жёсткая: REFUSED, веса не меняются."""
    cfg = SleeveConfig()
    shifted = {"pendle_pt_levered": 0.40, ANCHOR: 0.40, CASH_SLOT: 0.20}
    out = review_proportions(
        config=cfg, current_weights=shifted,
        trailing_equity={"pendle_pt_levered": _breached_eq(dd=0.20),
                         ANCHOR: _healthy_eq()},
        days_since_last_applied=30.0)
    assert out["status"] == "REFUSED_OUT_OF_BOUNDS"


def test_review_cooldown_holds_even_on_breach():
    cfg = SleeveConfig()
    out = review_proportions(
        config=cfg, current_weights=dict(cfg.base_weights),
        trailing_equity={"pendle_pt_levered": _breached_eq(dd=0.20),
                         ANCHOR: _healthy_eq()},
        days_since_last_applied=3.0)  # < 7
    assert out["status"] == "HOLD_COOLDOWN"


def test_review_missing_series_holds_unmeasured_never_guesses():
    cfg = SleeveConfig()
    out = review_proportions(
        config=cfg, current_weights=dict(cfg.base_weights),
        trailing_equity={"pendle_pt_levered": [], ANCHOR: _healthy_eq()},
        days_since_last_applied=None)
    assert out["status"] == "HOLD_UNMEASURED"


def test_anchor_noise_does_not_trigger_via_dd_floor():
    """2×0.1% для susde_dn — шум; пол 2.0% обязан гасить ложный триггер."""
    cfg = SleeveConfig()
    tiny_dip = _healthy_eq()[:15] + [x * 0.995 for x in _healthy_eq()[15:]]  # ~0.5% DD
    out = review_proportions(
        config=cfg, current_weights=dict(cfg.base_weights),
        trailing_equity={"pendle_pt_levered": _healthy_eq(), ANCHOR: tiny_dip},
        days_since_last_applied=None)
    assert out["status"] == "HOLD_HEALTHY"


# ── леджер ──────────────────────────────────────────────────────────────────


def test_ledger_idempotent_by_date_keeps_foreign_lines(tmp_path):
    append_ledger({"date": "2026-09-01", "equity": 100100.0}, tmp_path)
    append_ledger({"date": "2026-09-02", "equity": 100200.0}, tmp_path)
    append_ledger({"date": "2026-09-01", "equity": 100150.0}, tmp_path)  # re-run дня
    led = load_ledger(tmp_path)
    assert [r["date"] for r in led] == ["2026-09-01", "2026-09-02"]
    assert led[0]["equity"] == 100150.0  # последний прогон дня победил


# ── run_sleeve_shadow: e2e на синтетической панели ──────────────────────────


def _seed_panel(panel, sid, days=70, daily=0.001, start="2026-07-01"):
    from datetime import date, timedelta
    d = panel / sid
    d.mkdir(parents=True)
    d0 = date.fromisoformat(start)
    lines = []
    eq = 100000.0
    for i in range(days):
        phase = "backtest" if i < days - 5 else "forward"
        eq *= (1.0 + daily)
        lines.append(json.dumps({
            "date": (d0 + timedelta(days=i)).isoformat(),
            "equity_usd": round(eq, 4), "phase": phase}))
    (d / "realized_series.jsonl").write_text("\n".join(lines) + "\n")
    return (d0 + timedelta(days=days - 1)).isoformat()  # последняя forward-дата


def test_run_shadow_writes_checked_day_with_decision_id(tmp_path):
    panel = tmp_path / "panel"
    last = _seed_panel(panel, "pendle_pt_levered")
    _seed_panel(panel, ANCHOR)
    rec = run_sleeve_shadow(data_dir=tmp_path, panel_dir=panel, date_str=last)
    assert rec["checked"] is True
    assert rec["decision_id"] == f"sleeve-{last}"
    assert rec["policy_version"] == "v1.0"
    assert rec["equity"] > 100000.0
    assert load_ledger(tmp_path)[0]["date"] == last


def test_run_shadow_day_without_forward_point_is_unchecked(tmp_path):
    panel = tmp_path / "panel"
    _seed_panel(panel, "pendle_pt_levered")
    _seed_panel(panel, ANCHOR)
    rec = run_sleeve_shadow(data_dir=tmp_path, panel_dir=panel, date_str="2030-01-01")
    assert rec["checked"] is False
    assert rec["sleeve_return"] is None
    assert rec["equity"] == 100000.0  # не выдумано, стоит на seed


def test_run_shadow_never_raises_on_empty_panel(tmp_path):
    rec = run_sleeve_shadow(data_dir=tmp_path, panel_dir=tmp_path / "nope",
                            date_str="2026-09-01")
    assert rec.get("is_advisory") is True  # fail-open, цикл не пострадает


def test_wiring_lp_cycle_calls_the_shadow():
    """Проводка по ФОРМЕ вызова (урок «wiring-check-by-call-form»)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2]
           / "spa_core/paper_trading/lp_cycle.py").read_text(encoding="utf-8")
    assert "run_sleeve_shadow(" in src
    assert "from spa_core.strategy_lab.sleeve.composer import run_sleeve_shadow" in src
