# FROZEN-DATE-OK: даты — синтетические входные фикстуры (ряд APY и cycle_date запинены
# явно, обе стороны сравнения фиксированы); советники и _apy_series часы не читают.
"""Тесты allocator_advisors (own-27 поток 1) — 13 оптимизаторов как advisory-вход
в allocation_rationale.

Проверяется по существу, с ожиданиями, рассчитанными вручную из формул движков:
* cross_protocol_yield_optimizer — top-протокол и risk-adjusted APY (ручной расчёт);
* defi_gas_optimization_advisor — стоимость газа полного ребаланса книги (ручной);
* harvesting_frequency — оптимальный интервал t* = sqrt(2*gas/(pos*daily_r)) (ручной);
* fee_calculator — годовой cost-drag позиции (ручной);
* yield_timing — перцентиль/сигнал на синтетическом ряде (ручной).

Плюс: SKIPPED честен (без применимых данных — причина, не выдумка), советник
никогда не роняет писателя rationale (ERROR-запись / error-секция), и модуль
СТРОГО read-only по data/ (ни одного нового/изменённого файла).
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.analytics.allocator_advisors import (
    _ETH_PRICE_REF_USD,
    _STATIC_GAS_PRICE_GWEI,
    run_advisors,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)

BOOK_POSITIONS = {
    "aave_v3": 5_000.0,
    "pendle": 20_000.0,
    "maple": 20_000.0,
    "morpho_steakhouse": 40_000.0,
}
BOOK_APY = {
    "aave_v3": 3.0,
    "pendle": 15.0,
    "maple": 5.0,
    "morpho_steakhouse": 3.5,
}
CAPITAL = 100_000.0

ADVISOR_NAMES = [
    "defi_cross_protocol_yield_optimizer",
    "defi_gas_optimization_advisor",
    "gas_optimization_engine",
    "protocol_defi_gas_cost_optimizer",
    "defi_liquidity_mining_roi_calculator",
    "defi_protocol_fee_tier_optimizer",
    "defi_protocol_leverage_adjusted_apy_calculator",
    "defi_protocol_yield_harvesting_frequency_optimizer",
    "protocol_defi_position_size_optimizer",
    "protocol_defi_stable_yield_optimizer",
    "yield_reinvestment_optimizer",
    "yield_timing_optimizer",
    "fee_calculator",
]


def _write_fixture(data_dir: Path) -> None:
    """Живоподобные data/-файлы: снапшот оркестратора, реестр, книга."""
    adapters = []
    tvls = {"aave_v3": 100_000_000.0, "pendle": 50_000_000.0,
            "maple": 20_000_000.0, "morpho_steakhouse": 40_000_000.0}
    tiers = {"aave_v3": "T1", "pendle": "T2", "maple": "T2",
             "morpho_steakhouse": "T1"}
    for p, apy in BOOK_APY.items():
        adapters.append({
            "protocol": p, "tier": tiers[p], "apy_pct": apy,
            "tvl_usd": tvls[p], "status": "ok", "live_data": True,
            "tvl_source": "live",
        })
    (data_dir / "adapter_orchestrator_status.json").write_text(json.dumps({
        "generated_at": NOW.isoformat(), "adapters": adapters,
    }), encoding="utf-8")
    (data_dir / "adapter_registry.json").write_text(json.dumps({
        "adapters": {p: {"chain": "ethereum"} for p in BOOK_APY},
    }), encoding="utf-8")
    (data_dir / "current_positions.json").write_text(json.dumps({
        "capital_usd": CAPITAL,
        "accrued_yield_usd": 500.0,
        "positions": BOOK_POSITIONS,
    }), encoding="utf-8")


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    _write_fixture(tmp_path)
    from spa_core.analytics import _apy_series
    _apy_series.clear_cache()
    yield tmp_path
    _apy_series.clear_cache()


BOOK = {"positions": BOOK_POSITIONS, "capital_usd": CAPITAL, "apy_pct": BOOK_APY}


def _by_name(recs: list) -> dict:
    return {r["advisor"]: r for r in recs}


# ─────────────────────────────────────────────────────────────────────────────
# Форма и советники по существу (ручные ожидания)
# ─────────────────────────────────────────────────────────────────────────────

def test_all_13_advisors_present_in_order(data_dir: Path) -> None:
    recs = run_advisors(BOOK, data_dir)
    assert [r["advisor"] for r in recs] == ADVISOR_NAMES
    for r in recs:
        assert set(r) == {"advisor", "verdict", "detail", "est_bps"}
        assert isinstance(r["detail"], dict)
        json.dumps(r)  # каждая запись сериализуема как есть


def test_cross_protocol_top_is_pendle_with_hand_computed_risk_adj(
        data_dir: Path) -> None:
    """Ручной расчёт по формулам DeFiCrossProtocolYieldOptimizer для pendle.

    gas_entry (deposit, ethereum, 20 gwei)  = 200_000*20*3000/1e9 = $12
    gas_exit  (withdraw, ethereum, 20 gwei) = 250_000*20*3000/1e9 = $15
    ref_position = min(10% капитала, tvl, capital) = $10_000; hold 365 дней
    drag = 27/10_000*100 = 0.27 %; net = 15 − 0.27 = 14.73
    risk_factor T2 (risk_score 50) = 0.5 → risk_adj = 7.365
    """
    recs = _by_name(run_advisors(BOOK, data_dir))
    r = recs["defi_cross_protocol_yield_optimizer"]
    assert r["verdict"] == "TOP:pendle"
    assert r["detail"]["top_opportunity"] == "pendle"
    assert r["detail"]["top_risk_adjusted_net_apy_pct"] == pytest.approx(7.365)
    # est_bps = (top risk_adj − blended книги) в б.п. — неотрицателен и conсистентен
    blended = r["detail"]["book_blended_risk_adjusted_apy_pct"]
    assert r["est_bps"] == pytest.approx((7.365 - blended) * 100.0, abs=0.02)


def test_gas_advisor_full_book_rebalance_cost_hand_computed(
        data_dir: Path) -> None:
    """4 позиции × rebalance(ethereum) = 4 × 500_000*20*3000/1e9 = 4 × $30 = $120."""
    recs = _by_name(run_advisors(BOOK, data_dir))
    r = recs["defi_gas_optimization_advisor"]
    assert r["detail"]["full_book_rebalance_gas_usd"] == pytest.approx(120.0)
    assert r["detail"]["prohibitive_count"] == 0
    assert r["verdict"] == "GAS_OK"


def test_harvesting_optimal_interval_hand_computed(data_dir: Path) -> None:
    """morpho_steakhouse: t* = sqrt(2*gas/(pos*daily_r)), gas=$30, pos=$40k, APY 3.5%."""
    daily_r = (1.0 + 3.5 / 100.0) ** (1.0 / 365.25) - 1.0
    expected = math.sqrt(2.0 * 30.0 / (40_000.0 * daily_r))
    recs = _by_name(run_advisors(BOOK, data_dir))
    r = recs["defi_protocol_yield_harvesting_frequency_optimizer"]
    per = {p["name"]: p for p in r["detail"]["per_position"]}
    assert per["morpho_steakhouse"]["optimal_interval_days"] == pytest.approx(
        expected, abs=0.01)
    assert per["morpho_steakhouse"]["optimal_frequency_label"] == "WEEKLY"


def test_fee_calculator_drag_hand_computed(data_dir: Path) -> None:
    """aave_v3 $5k deposit: gas $12; slippage T1 = 5000*0.001*(1+5000/1e8) = $5.00025."""
    recs = _by_name(run_advisors(BOOK, data_dir))
    r = recs["fee_calculator"]
    per = {p["name"]: p for p in r["detail"]["per_position"]}
    assert per["aave_v3"]["gas"] == pytest.approx(12.0)
    assert per["aave_v3"]["slippage"] == pytest.approx(5.00025, abs=1e-4)
    assert per["aave_v3"]["total_usd"] == pytest.approx(17.00025, abs=1e-3)
    assert r["verdict"].startswith("DRAG:")


def test_yield_timing_signal_on_synthetic_series(data_dir: Path) -> None:
    """40 точек истории aave_v3 все ниже текущего APY → перцентиль 100, STRONG_BUY."""
    hist_dir = data_dir / "historical_apy"
    hist_dir.mkdir()
    rows = [{"date": f"2026-06-{d:02d}", "apy": 2.0 + 0.01 * d} for d in range(1, 31)]
    rows += [{"date": f"2026-07-{d:02d}", "apy": 2.5 + 0.01 * d} for d in range(1, 11)]
    (hist_dir / "aave_v3_usdc.json").write_text(json.dumps(rows), encoding="utf-8")
    from spa_core.analytics import _apy_series
    _apy_series.clear_cache()

    recs = _by_name(run_advisors(BOOK, data_dir))
    r = recs["yield_timing_optimizer"]
    sig = r["detail"]["signals"]["aave_v3"]
    assert sig["apy_percentile"] == pytest.approx(100.0)  # 3.0 выше всех 40 точек
    assert sig["entry_signal"] == "STRONG_BUY"
    assert sig["history_days"] == 40
    # Протоколы без рядов честно перечислены, не выдуманы
    assert set(r["detail"]["insufficient_history_days"]) == {
        "maple", "morpho_steakhouse", "pendle"}


def test_reinvestment_targets_highest_apy(data_dir: Path) -> None:
    recs = _by_name(run_advisors(BOOK, data_dir))
    r = recs["yield_reinvestment_optimizer"]
    assert r["detail"]["optimal_reinvest_target"] == "pendle"
    assert r["detail"]["accrued_yield_usd"] == pytest.approx(500.0)
    # threshold = 2×газ депозита ($12) = $24 < $500 → реинвест осмыслен
    assert r["detail"]["assumptions"]["threshold_usd"] == pytest.approx(24.0)


# ─────────────────────────────────────────────────────────────────────────────
# SKIPPED: без применимых данных — причина, не выдумка
# ─────────────────────────────────────────────────────────────────────────────

def test_inapplicable_engines_are_skipped_with_reasons(data_dir: Path) -> None:
    recs = _by_name(run_advisors(BOOK, data_dir))
    for name in ("defi_liquidity_mining_roi_calculator",
                 "defi_protocol_fee_tier_optimizer",
                 "defi_protocol_leverage_adjusted_apy_calculator",
                 "protocol_defi_stable_yield_optimizer"):
        assert recs[name]["verdict"] == "SKIPPED", name
        assert recs[name]["detail"]["reason"], name
        assert recs[name]["est_bps"] is None, name


def test_empty_book_and_empty_data_dir_all_skip_or_answer(tmp_path: Path) -> None:
    """Пустая директория: ни один советник не выдумывает вход и не падает."""
    recs = run_advisors({}, tmp_path)
    assert [r["advisor"] for r in recs] == ADVISOR_NAMES
    for r in recs:
        assert r["verdict"] != "ERROR", r
    by = _by_name(recs)
    assert by["defi_gas_optimization_advisor"]["verdict"] == "SKIPPED"
    assert "no positions" in by["fee_calculator"]["detail"]["reason"]
    assert by["defi_cross_protocol_yield_optimizer"]["verdict"] == "SKIPPED"


def test_timing_skips_when_history_short(data_dir: Path) -> None:
    """Без historical_apy ни у кого нет ≥30 точек → честный SKIPPED с причиной."""
    recs = _by_name(run_advisors(BOOK, data_dir))
    r = recs["yield_timing_optimizer"]
    assert r["verdict"] == "SKIPPED"
    assert "30" in r["detail"]["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# Read-only и отказоустойчивость
# ─────────────────────────────────────────────────────────────────────────────

def test_run_advisors_is_read_only_on_data_dir(data_dir: Path) -> None:
    """Ни один движковый ring-buffer-лог не просачивается в data_dir."""
    before = {p: p.stat().st_mtime_ns for p in data_dir.rglob("*") if p.is_file()}
    run_advisors(BOOK, data_dir)
    after = {p: p.stat().st_mtime_ns for p in data_dir.rglob("*") if p.is_file()}
    assert after == before


def test_single_advisor_crash_becomes_error_entry(data_dir: Path,
                                                  monkeypatch) -> None:
    import spa_core.analytics.allocator_advisors as mod

    def boom(_f):
        raise RuntimeError("engine exploded")

    patched = [(n, boom if n == "fee_calculator" else fn)
               for n, fn in mod._ADVISORS]
    monkeypatch.setattr(mod, "_ADVISORS", patched)
    recs = _by_name(run_advisors(BOOK, data_dir))
    assert recs["fee_calculator"]["verdict"] == "ERROR"
    assert recs["fee_calculator"]["detail"]["error"] == "RuntimeError"
    # Остальные 12 записей на месте и не ERROR
    others = [r for n, r in recs.items() if n != "fee_calculator"]
    assert len(others) == 12
    assert all(r["verdict"] != "ERROR" for r in others)


def test_gas_advisor_module_log_patch_is_restored(data_dir: Path) -> None:
    """Глушение модульного _append_log временное: после вызова функция прежняя."""
    import spa_core.analytics.defi_gas_optimization_advisor as gas_mod
    orig = gas_mod._append_log
    run_advisors(BOOK, data_dir)
    assert gas_mod._append_log is orig


# ─────────────────────────────────────────────────────────────────────────────
# Интеграция с писателем rationale (advisor_notes)
# ─────────────────────────────────────────────────────────────────────────────

def _write_rationale(data_dir: Path):
    from spa_core.paper_trading.allocation_rationale import (
        RATIONALE_FILENAME, write_shadow_rationale)
    doc = write_shadow_rationale(
        data_dir=data_dir,
        current_positions=BOOK_POSITIONS,
        target_positions=BOOK_POSITIONS,
        apy_pct=BOOK_APY,
        apy_sources={k: "live" for k in BOOK_APY},
        capital_usd=CAPITAL,
        cycle_date="2026-08-05",
        run_ts=NOW.isoformat(),
        now=NOW,
    )
    on_disk = json.loads(
        (data_dir / RATIONALE_FILENAME).read_text(encoding="utf-8"))
    return doc, on_disk


def test_rationale_gains_advisor_notes_section(data_dir: Path) -> None:
    doc, on_disk = _write_rationale(data_dir)
    assert on_disk == doc
    notes = doc["advisor_notes"]
    assert "never gate execution" in notes["note"]
    assert [r["advisor"] for r in notes["recommendations"]] == ADVISOR_NAMES
    # Advisory-инвариант: решение SHADOW не зависит от советников —
    # прочие секции rationale присутствуют нетронутыми.
    assert doc["decision_shadow"]["decision"] in ("ACT", "HOLD")
    assert doc["mode"] == "SHADOW"


def test_advisors_total_failure_leaves_rationale_intact(data_dir: Path,
                                                        monkeypatch) -> None:
    """Советники упали целиком → advisor_notes.error, rationale цел и записан."""
    import spa_core.analytics.allocator_advisors as mod

    def total_boom(*_a, **_k):
        raise OSError("advisors down")

    monkeypatch.setattr(mod, "run_advisors", total_boom)
    doc, on_disk = _write_rationale(data_dir)
    assert on_disk == doc
    assert doc["advisor_notes"]["error"] == "OSError"
    assert doc["advisor_notes"]["recommendations"] == []
    assert doc["decision_shadow"]["decision"] in ("ACT", "HOLD")
    assert "cash" in doc and "history" in doc  # прочие секции не пострадали


def test_advisors_never_import_execution_or_gate_domains() -> None:
    """Advisory-инвариант на уровне исходника: ни импорта execution/, ни
    governance/kill_switch, ни cycle_gates из модуля советников."""
    src = Path(__file__).resolve().parent.parent / "analytics" / "allocator_advisors.py"
    text = src.read_text(encoding="utf-8")
    for forbidden in ("spa_core.execution", "kill_switch", "cycle_gates",
                      "pre_cutover_gate"):
        assert forbidden not in text, forbidden
