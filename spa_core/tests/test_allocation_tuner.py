"""Tests for AllocationTuner (MP-207).

10+ тестов покрывающих:
- Корректность весов (сумма=1.0, нет негативных)
- T1 constraint (≥ 55%)
- T2 cap (≤ 35%)
- Per-protocol cap (≤ 40%)
- TVL floor (< 5M исключается)
- Backtest с положительным APY → положительный return
- Improvements vs suboptimal
- run_allocation_tuner с mock данными
- expected_apy положительный
- All-cash если нет eligible протоколов
- Objective score выше у лучшей аллокации
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List

# Ensure repo root on path for direct test runs
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.tuner.allocation_tuner import (
    AllocationTuner,
    TunerConstraints,
    TunerResult,
    run_allocation_tuner,
)

# ─── Фикстуры ────────────────────────────────────────────────────────────────

_GOOD_ADAPTERS = [
    {"id": "aave_v3",    "apy": 3.13, "tvl_usd": 209_000_000.0, "tier": "T1"},
    {"id": "compound_v3","apy": 3.18, "tvl_usd": 48_000_000.0,  "tier": "T1"},
    {"id": "yearn_v3",   "apy": 3.18, "tvl_usd": 26_000_000.0,  "tier": "T2"},
    {"id": "euler_v2",   "apy": 2.77, "tvl_usd": 16_000_000.0,  "tier": "T2"},
    {"id": "maple",      "apy": 4.72, "tvl_usd": 3_114_000_000.0, "tier": "T2"},
]

# Morpho Blue имеет TVL < 5M — должен исключаться
_LOW_TVL_ADAPTER = {"id": "morpho_blue", "apy": 4.94, "tvl_usd": 402_866.0, "tier": "T2"}

_ALL_ADAPTERS = _GOOD_ADAPTERS + [_LOW_TVL_ADAPTER]


def _make_tuner(constraints: TunerConstraints = None) -> AllocationTuner:
    return AllocationTuner(constraints=constraints)


# ─── Тест 1: корректные веса ─────────────────────────────────────────────────

def test_optimizer_returns_valid_weights():
    """Веса: sum=1.0 (с допуском), нет отрицательных, нет NaN."""
    tuner = _make_tuner()
    result = tuner.optimize(_GOOD_ADAPTERS, n_candidates=200)

    assert result.optimal_weights, "optimal_weights не должен быть пустым"
    for pid, w in result.optimal_weights.items():
        assert w >= 0.0, f"Вес {pid} отрицательный: {w}"
        assert not math.isnan(w), f"Вес {pid} == NaN"

    total = sum(result.optimal_weights.values())
    # Сумма ≤ 1.0 (неразмещённый остаток — cash)
    assert total <= 1.0 + 1e-4, f"Сумма весов > 1.0: {total}"
    # Минимальная сумма — должно быть развёрнуто хоть что-то
    assert total >= 0.50, f"Слишком мало развёрнуто: {total * 100:.1f}%"


# ─── Тест 2: T1 constraint ───────────────────────────────────────────────────

def test_no_phantom_t1_floor():
    """T1-пола в политике НЕТ ⇒ тюнер не штрафует низкий T1 (2026-08-18).

    ИЗМЕНЕНИЕ ТЕСТА, обоснование (инвариант 16, запись в journal 2026-08-18):
    прежняя редакция проверяла собственный литерал тюнера `t1_min=0.55` —
    правило, которого у источника (RiskConfig) не существует и которое
    `policy_enforcer` обнулил у себя ещё 2026-07-08 (`_T1_MIN_PCT = 0.0`).
    Проверка литерала второй копии — не проверка, а её консервация. Ниже
    проверяется противоположное и предметное: политика-совместимая раскладка
    БЕЗ T1 не должна получать штрафа. Возврат фантомного пола красит тест.
    """
    tuner = _make_tuner()
    zero_t1 = {"yearn_v3": 0.15, "euler_v2": 0.15, "maple": 0.15}
    valid, penalty = tuner._check_constraints(zero_t1, _GOOD_ADAPTERS)

    assert valid
    assert penalty == 0.0, (
        f"раскладка без T1 не нарушает политику, штраф должен быть 0, получили {penalty}"
    )


# ─── Тест 3: T2 cap ──────────────────────────────────────────────────────────

def test_t2_cap_respected():
    """Сумма T2-весов ≤ потолка ПОЛИТИКИ (ADR-019), а не копии в тюнере.

    ИЗМЕНЕНИЕ ТЕСТА, обоснование (инвариант 16, запись в journal 2026-08-18):
    литерал 0.35 — значение T2-cap ДО ADR-019 (2026-06-12 поднял 35 % → 50 %).
    Тест закреплял устаревшую вторую копию порога: политика уехала, копия нет.
    Число теперь читается из RiskConfig — если политика двинется снова, тест
    поедет вместе с ней, а расхождение зеркала поймает
    test_tuner_constraints_mirror_riskpolicy.py.
    """
    from spa_core.risk.policy import RiskConfig

    tuner = _make_tuner()
    result = tuner.optimize(_GOOD_ADAPTERS, n_candidates=300)

    t2_ids = {a["id"] for a in _GOOD_ADAPTERS if a["tier"] == "T2"}
    t2_total = sum(result.optimal_weights.get(pid, 0.0) for pid in t2_ids)
    policy_cap = float(RiskConfig().max_total_t2_allocation)

    assert t2_total <= policy_cap + 1e-4, (
        f"T2 total {t2_total * 100:.2f}% > policy cap {policy_cap * 100:.0f}%"
    )


# ─── Тест 4: per-protocol cap ────────────────────────────────────────────────

def test_per_protocol_cap():
    """Ни один протокол не выше ТИРОВОГО потолка политики.

    ИЗМЕНЕНИЕ ТЕСТА, обоснование (инвариант 16, запись в journal 2026-08-18):
    плоские 40 % пропускали T2-позицию на 23.8 % при policy-cap T2 = 20 %,
    то есть тест зеленел на раскладке, которую `policy_enforcer` отклонял
    (`per_protocol_max_pct CRITICAL 23.81 <= 20.0`, замер 2026-08-18).
    Проверка стала СТРОЖЕ и читает пороги из RiskConfig.
    """
    from spa_core.risk.policy import RiskConfig

    cfg = RiskConfig()
    tiers = {a["id"]: a["tier"] for a in _GOOD_ADAPTERS}
    tuner = _make_tuner()
    result = tuner.optimize(_GOOD_ADAPTERS, n_candidates=300)

    for pid, w in result.optimal_weights.items():
        cap = min(
            float(cfg.max_concentration_t1) if tiers[pid] == "T1"
            else float(cfg.max_concentration_t2),
            float(cfg.max_single_protocol),
        )
        assert w <= cap + 1e-4, (
            f"Протокол {pid} ({tiers[pid]}) превышает cap {cap * 100:.0f}%: {w * 100:.2f}%"
        )


# ─── Тест 5: TVL floor исключает мелкие пулы ─────────────────────────────────

def test_tvl_floor_excludes_low_tvl():
    """Протокол с TVL < 5M должен быть исключён из оптимальных весов."""
    tuner = _make_tuner()
    result = tuner.optimize(_ALL_ADAPTERS, n_candidates=200)

    # morpho_blue с TVL ~400K должен быть исключён (вес = 0 или отсутствует)
    morpho_weight = result.optimal_weights.get("morpho_blue", 0.0)
    assert morpho_weight < 1e-4, (
        f"morpho_blue (TVL < 5M) должен иметь вес ≈0, а не {morpho_weight * 100:.2f}%"
    )


# ─── Тест 6: backtest с положительным APY ────────────────────────────────────

def test_backtest_positive_with_positive_apy():
    """Backtest должен давать положительный return при положительном APY."""
    tuner = _make_tuner()
    weights = {"aave_v3": 0.60, "yearn_v3": 0.30}
    adapters = [
        {"id": "aave_v3", "apy": 5.0, "tvl_usd": 100_000_000.0, "tier": "T1"},
        {"id": "yearn_v3","apy": 3.0, "tvl_usd": 30_000_000.0,  "tier": "T2"},
    ]
    bt = tuner.backtest_allocation(weights, adapters, days=30)

    assert bt["total_return_pct"] > 0, (
        f"Backtest total return должен быть > 0, получили {bt['total_return_pct']}"
    )
    assert bt["annualized_pct"] > 0, "Annualized APY должен быть > 0"
    assert len(bt["daily_returns"]) == 30, "Должно быть 30 дневных доходностей"
    assert all(r > 0 for r in bt["daily_returns"]), "Все дневные доходности должны быть > 0"


# ─── Тест 7: improvements vs suboptimal ──────────────────────────────────────

def test_improvements_detected_vs_suboptimal():
    """Если текущая аллокация явно хуже — improvements должен быть непустым."""
    tuner = _make_tuner()
    # Намеренно плохая аллокация: 5% в лучшем, 95% в худшем
    bad_weights = {
        "aave_v3":    0.05,
        "compound_v3": 0.0,
        "yearn_v3":   0.0,
        "euler_v2":   0.95,  # много в низкодоходном
        "maple":      0.0,
    }
    result = tuner.optimize(_GOOD_ADAPTERS, current_weights=bad_weights, n_candidates=300)

    # Должны быть обнаружены улучшения
    assert result.improvements, "Должны быть зафиксированы improvements"
    assert result.improvements != ["Текущая аллокация близка к оптимальной"], (
        f"Плохая аллокация должна порождать конкретные улучшения: {result.improvements}"
    )


# ─── Тест 8: run_allocation_tuner с mock данными ─────────────────────────────

def test_run_with_mock_adapter_data():
    """run_allocation_tuner с явно переданными adapter_data и save=False."""
    result = run_allocation_tuner(
        adapter_data=_GOOD_ADAPTERS,
        current_weights=None,
        save=False,
    )

    assert isinstance(result, TunerResult)
    assert result.optimal_weights
    assert result.expected_apy >= 0.0
    assert result.objective_score > -999.0


# ─── Тест 9: expected_apy положительный ──────────────────────────────────────

def test_result_expected_apy_positive():
    """expected_apy должен быть > 0 при наличии eligible протоколов."""
    tuner = _make_tuner()
    result = tuner.optimize(_GOOD_ADAPTERS, n_candidates=200)

    assert result.expected_apy > 0.0, (
        f"expected_apy должен быть > 0, получили {result.expected_apy}"
    )


# ─── Тест 10: all-cash при отсутствии eligible протоколов ────────────────────

def test_all_cash_if_no_eligible_protocols():
    """Если все протоколы ниже TVL floor → all-cash (пустые веса)."""
    low_tvl_adapters = [
        {"id": "proto_a", "apy": 5.0, "tvl_usd": 100_000.0, "tier": "T1"},
        {"id": "proto_b", "apy": 4.0, "tvl_usd": 200_000.0, "tier": "T2"},
    ]
    tuner = _make_tuner()
    result = tuner.optimize(low_tvl_adapters, n_candidates=100)

    assert result.optimal_weights == {}, (
        f"При отсутствии eligible протоколов ожидались пустые веса, "
        f"получили: {result.optimal_weights}"
    )
    assert result.expected_apy == 0.0
    assert result.objective_score == -999.0
    assert any("all-cash" in imp.lower() or "eligible" in imp.lower()
               for imp in result.improvements)


# ─── Тест 11: objective_score выше у лучшей аллокации ────────────────────────

def test_better_allocation_has_higher_score():
    """_score_allocation выдаёт более высокий score для лучшей аллокации."""
    tuner = _make_tuner()

    # Сбалансированная аллокация
    good = {"aave_v3": 0.40, "compound_v3": 0.20, "yearn_v3": 0.20, "euler_v2": 0.10, "maple": 0.05}
    # Сконцентрированная плохая аллокация
    bad  = {"aave_v3": 0.00, "compound_v3": 0.00, "yearn_v3": 0.00, "euler_v2": 0.00, "maple": 0.95}

    score_good = tuner._score_allocation(good, _GOOD_ADAPTERS)
    score_bad  = tuner._score_allocation(bad, _GOOD_ADAPTERS)

    assert score_good > score_bad, (
        f"Лучшая аллокация должна иметь higher score: {score_good:.4f} vs {score_bad:.4f}"
    )


# ─── Тест 12: backtest sharpe ≥ 0 для положительного APY ─────────────────────

def test_backtest_sharpe_nonnegative():
    """Sharpe estimate должен быть ≥ 0 для портфеля с положительным APY."""
    tuner = _make_tuner()
    weights = {"aave_v3": 0.55, "compound_v3": 0.30, "yearn_v3": 0.15}
    adapters = [
        {"id": "aave_v3",    "apy": 3.13, "tvl_usd": 209_000_000.0, "tier": "T1"},
        {"id": "compound_v3","apy": 3.18, "tvl_usd": 48_000_000.0,  "tier": "T1"},
        {"id": "yearn_v3",   "apy": 3.18, "tvl_usd": 26_000_000.0,  "tier": "T2"},
    ]
    bt = tuner.backtest_allocation(weights, adapters, days=30)

    assert bt["sharpe_estimate"] >= 0.0, (
        f"Sharpe должен быть ≥ 0, получили {bt['sharpe_estimate']}"
    )


# ─── Тест 13: протокол с APY вне bounds исключается ──────────────────────────

def test_apy_out_of_bounds_excluded():
    """Протокол с APY > 30% или < 1% должен быть исключён из eligible."""
    adapters_with_outlier = _GOOD_ADAPTERS + [
        {"id": "risky_pool", "apy": 999.0, "tvl_usd": 50_000_000.0, "tier": "T2"},
        {"id": "zero_pool",  "apy": 0.1,   "tvl_usd": 50_000_000.0, "tier": "T2"},
    ]
    tuner = _make_tuner()
    result = tuner.optimize(adapters_with_outlier, n_candidates=200)

    risky_w = result.optimal_weights.get("risky_pool", 0.0)
    zero_w  = result.optimal_weights.get("zero_pool", 0.0)

    assert risky_w < 1e-4, f"risky_pool (APY=999%) должен быть исключён, вес={risky_w:.4f}"
    assert zero_w  < 1e-4, f"zero_pool (APY=0.1%) должен быть исключён, вес={zero_w:.4f}"


# ─── Тест 14-16: MP-207 — вход data_dir строкой (живой вызов cycle_runner) ────
#
# Регресс на реальный дефект: `cycle_runner.main()` держит эффективную
# data-директорию СТРОКОЙ (`_eff_data_dir = str(_eff_dir)`, back-compat API) и
# передавал её в тюнер, а тот делал `ddir / "tuner_suggestion.json"` ⇒
# `TypeError: unsupported operand type(s) for /: 'str' and 'str'`. Исключение
# съедала fail-safe-обёртка воскресной ветки (`except Exception → log.warning`),
# поэтому предложение тюнера не писалось НИ РАЗУ и никто этого не видел.

_ORCH_STATUS_FIXTURE = {
    "adapters": [
        {"protocol": "aave_v3",     "status": "ok", "apy_pct": 3.13,
         "tvl_usd": 209_000_000.0, "tier": "T1"},
        {"protocol": "compound_v3", "status": "ok", "apy_pct": 3.18,
         "tvl_usd": 48_000_000.0,  "tier": "T1"},
        {"protocol": "yearn_v3",    "status": "ok", "apy_pct": 3.18,
         "tvl_usd": 26_000_000.0,  "tier": "T2"},
    ]
}


def _seed_data_dir(tmp_path: Path) -> Path:
    """Кладёт в tmp-директорию снимок адаптеров в формате оркестратора."""
    import json as _json
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "adapter_orchestrator_status.json").write_text(
        _json.dumps(_ORCH_STATUS_FIXTURE), encoding="utf-8"
    )
    return tmp_path


def test_run_allocation_tuner_accepts_str_data_dir(tmp_path):
    """`run_allocation_tuner(data_dir="<str>")` — ровно как зовёт cycle_runner.

    До фикса падало TypeError'ом. Проверяем и отсутствие исключения, и то, что
    предложение РЕАЛЬНО записано в переданную директорию (симптом бага —
    отсутствующий tuner_suggestion.json).
    """
    ddir = _seed_data_dir(tmp_path)

    result = run_allocation_tuner(data_dir=str(ddir))   # str, не Path — как в проде

    assert isinstance(result, TunerResult)
    out = ddir / "tuner_suggestion.json"
    assert out.exists(), "воскресный прогон обязан записать tuner_suggestion.json"

    import json as _json
    payload = _json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("generated_at"), "в предложении должна быть метка времени"
    assert "note" in payload, "предложение остаётся advisory (применяется вручную)"


def test_run_allocation_tuner_str_and_path_agree(tmp_path):
    """str и Path дают одинаковый результат — нормализация не меняет поведение."""
    d_str = _seed_data_dir(tmp_path / "as_str")
    d_path = _seed_data_dir(tmp_path / "as_path")

    r_str = run_allocation_tuner(data_dir=str(d_str))
    r_path = run_allocation_tuner(data_dir=d_path)

    assert (d_str / "tuner_suggestion.json").exists()
    assert (d_path / "tuner_suggestion.json").exists()
    assert set(r_str.optimal_weights) == set(r_path.optimal_weights)


def test_run_allocation_tuner_writes_only_inside_given_dir(tmp_path):
    """Герметичность: запись идёт в переданную директорию, а не в живой data/."""
    ddir = _seed_data_dir(tmp_path)
    from spa_core.tuner import allocation_tuner as _mod
    live_out = _mod._TUNER_OUT
    live_before = live_out.read_bytes() if live_out.exists() else None

    run_allocation_tuner(data_dir=str(ddir))

    live_after = live_out.read_bytes() if live_out.exists() else None
    assert live_after == live_before, "живой data/tuner_suggestion.json не должен трогаться"
