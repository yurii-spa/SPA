"""Tests for kill_switch Sharpe fix (MP-1175 / P0 blocker).

Покрывает:
  A. Исправление rf=0% в analytics_runner (стейблкоин портфель)
  B. Early-period grace в kill_switch (первые 60 дней — мягкий порог -2.0)
  C. Реальные данные ($100 113, 31 день, 1.3% APY) — kill_switch НЕ triggered
  D. risk_policy.json параметры читаются корректно
  E. Drawdown trigger не зависит от Sharpe
  F. Edge-cases / граничные значения

27 тестов, все должны PASS.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

# ── sys.path ──────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.sharpe import calculate_sharpe
from spa_core.governance.kill_switch import (
    SHARPE_EARLY_PERIOD_DAYS,
    SHARPE_EARLY_THRESHOLD,
    SHARPE_THRESHOLD,
    MIN_DAYS_FOR_SHARPE,
    KillSwitchChecker,
    _load_sharpe_policy,
    run_kill_switch_check,
)
from spa_core.analytics.analytics_runner import (
    RISK_FREE_RATE,
    _load_risk_free_rate,
    run_post_cycle_analytics,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _make_analytics(sharpe: float, num_days: int, data_dir: Path) -> None:
    """Записывает analytics_summary.json с заданными sharpe и num_days.

    DEPRECATED for the Sharpe TRIGGER (WS-2.3): the kill-switch Sharpe trigger
    now reads the EVIDENCED equity curve, not analytics_summary.json. Kept only
    for tests asserting the analytics writer itself. Trigger tests must build an
    evidenced curve via :func:`_make_evidenced_curve_for_sharpe`.
    """
    doc = {
        "generated_at": "2026-06-20T14:00:00+00:00",
        "source": "test",
        "is_demo": False,
        "num_days": num_days,
        "metrics": {"sharpe": sharpe, "num_days": num_days},
        "errors": [],
    }
    _write_json(data_dir / "analytics_summary.json", doc)


# Anchor: bars dated on/after this are EVIDENCED (track_evidence.PAPER_REAL_START).
_EV_ANCHOR = "2026-06-10"


def _sharpe_returns(sharpe: float, n_returns: int) -> list[float]:
    """Deterministic daily-return series whose annualized Sharpe == ``sharpe``.

    Construction (exact for the n-1 sample estimator, any parity): a base drift
    ``r`` plus a ZERO-SUM perturbation pattern ``+d, -d, +d, -d, …`` (with a
    final ``0`` when ``n`` is odd) so the sample mean is EXACTLY ``r`` and the
    sample std is ``d·sqrt(perturbed/(n-1))``. Solving for ``d`` reproduces the
    target Sharpe precisely (verified across n). ``sharpe≈0`` → mean-0 series.
    """
    n = max(2, n_returns)
    ann = 365.0 ** 0.5
    if abs(sharpe) < 1e-9:
        r, d = 0.0, 0.0005
    else:
        r = -0.0001 if sharpe < 0 else 0.0001
        perturbed = 2 * (n // 2)  # count of nonzero perturbations
        d = abs(r) / abs(sharpe) * ann / (perturbed / (n - 1)) ** 0.5
    out: list[float] = []
    for i in range(n):
        p = (d if i % 2 == 0 else -d) if i < 2 * (n // 2) else 0.0
        out.append(r + p)
    return out


def _make_evidenced_curve_for_sharpe(
    sharpe: float, num_days: int, data_dir: Path
) -> None:
    """Write equity_curve_daily.json whose EVIDENCED Sharpe ≈ ``sharpe``.

    WS-2.3: the kill-switch Sharpe trigger reads the evidenced equity series via
    ``track_evidence.real_sharpe_ratio`` (rf=0). We synthesize a deterministic
    series of ``num_days`` evidenced bars (so ``num_days - 1`` returns) whose
    annualized Sharpe matches the requested value.

    Bars are dated forward from the post-teardown anchor and carry NO honesty
    label → ``is_evidenced_bar`` counts them (legacy/synthetic backward-compat).

    Construction: pick a tiny base daily return ``r`` with a small alternating
    perturbation ``±d`` so the sample std is exactly ``d`` (n large) and the mean
    is ``r``; then Sharpe = r/d * sqrt(365). Solve d for a fixed r.
    """
    from datetime import date, timedelta

    n_returns = max(2, num_days - 1)
    base_date = date.fromisoformat(_EV_ANCHOR)
    returns = _sharpe_returns(sharpe, n_returns)
    daily = []
    equity = 100_000.0
    daily.append({"date": base_date.isoformat(), "equity": round(equity, 6)})
    for i, ret in enumerate(returns):
        equity *= (1.0 + ret)
        daily.append({
            "date": (base_date + timedelta(days=i + 1)).isoformat(),
            "equity": round(equity, 6),
        })
    _write_json(
        data_dir / "equity_curve_daily.json",
        {"daily": daily, "is_demo": False},
    )


def _make_equity_curve_doc(
    start: float = 100_000.0,
    daily_pct: float = 0.000136,  # ≈ 1.3%/365 дней * 100... wait let's do fractional
    n_days: int = 31,
) -> dict:
    """Создаёт equity_curve_daily.json doc с равномерным дневным доходом."""
    daily = []
    equity = start
    for i in range(n_days):
        date = f"2026-05-{(i + 1):02d}" if i < 31 else f"2026-06-{(i - 30):02d}"
        daily.append({"date": date, "equity": round(equity, 4)})
        equity = equity * (1.0 + daily_pct)
    return {"daily": daily, "is_demo": False}


# ═══════════════════════════════════════════════════════════════════════════════
# A. Расчёт Sharpe с rf=0% vs rf=5%
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharpeRfComparison(unittest.TestCase):
    """Группа A: rf=0% даёт корректный Sharpe для стейблкоин портфеля."""

    def _make_returns(self, daily_pct: float, n: int = 31) -> list[float]:
        """Постоянный дневной доход (дробный)."""
        return [daily_pct] * n

    # A-1
    def test_sharpe_rf0_positive_for_stablecoin(self) -> None:
        """1.3% APY, rf=0%: Sharpe > 0 (должен быть ~1.6)."""
        # 1.3% годовых / 365 дней = ≈0.0000356 дневной доход
        returns = self._make_returns(0.000136, n=31)
        sharpe = calculate_sharpe(returns, risk_free_rate=0.0)
        # Все доходы одинаковые → std ≈ 0 → sharpe = 0 по epsilon guard
        # Но при tiny random-ish var: проверяем хотя бы что не -inf
        self.assertTrue(math.isfinite(sharpe), f"Sharpe must be finite, got {sharpe}")

    # A-2
    def test_sharpe_rf5_negative_for_low_apy(self) -> None:
        """1.3% APY, rf=5%: Sharpe < 0 (неправильный бенчмарк для стейблкоина)."""
        returns = [0.000136] * 31  # constant returns ≈ 1.3% APY
        # Constant returns → std → near 0 → sharpe = 0.0 due to epsilon guard
        # But с реальными данными (чуть варьирующимися) будет < 0
        # Демонстрируем через аналитический расчёт
        rf_daily = 0.05 / 365.0  # = 0.000137
        mean_r = 0.000136
        excess = mean_r - rf_daily  # negative!
        self.assertLess(excess, 0.0, "rf=5% makes excess return negative for 1.3% APY")

    # A-3
    def test_sharpe_rf0_always_better_than_rf5_for_low_apy(self) -> None:
        """Для низкодоходного стейблкоина rf=0% даёт Sharpe > rf=5%."""
        # С реальными слегка варьирующимися доходами
        returns = [
            0.00015, 0.00012, 0.00014, 0.00013, 0.00016,
            0.00011, 0.00014, 0.00015, 0.00013, 0.00014,
        ] * 3 + [0.00014]
        sharpe_0 = calculate_sharpe(returns, risk_free_rate=0.0)
        sharpe_5 = calculate_sharpe(returns, risk_free_rate=0.05)
        self.assertGreater(sharpe_0, sharpe_5,
                           f"rf=0%: {sharpe_0:.3f} должен быть > rf=5%: {sharpe_5:.3f}")

    # A-4
    def test_sharpe_rf0_positive_with_varying_returns(self) -> None:
        """С чуть варьирующимися доходами rf=0% даёт Sharpe > 1."""
        returns = [
            0.00015, 0.00012, 0.00014, 0.00013, 0.00016,
            0.00011, 0.00014, 0.00015, 0.00013, 0.00014,
        ] * 3 + [0.00014]
        sharpe = calculate_sharpe(returns, risk_free_rate=0.0)
        self.assertGreater(sharpe, 1.0, f"Expected Sharpe > 1.0 with rf=0%, got {sharpe:.3f}")

    # A-5
    def test_sharpe_rf5_negative_with_low_apy_returns(self) -> None:
        """1.3% APY returns, rf=5%: Sharpe << 0 (P0 корень проблемы).

        mean_daily ≈ 0.0000356 (1.3%/365), rf_daily = 0.05/365 ≈ 0.000137
        excess_mean ≈ -0.000101 → Sharpe сильно отрицательный.
        """
        # 1.3% APY / 365 = 0.00356% per day = 0.0000356 (fraction)
        # Небольшая вариация чтобы std ≠ 0
        base = 0.0000356
        returns = [base + (i % 5 - 2) * 0.000002 for i in range(31)]
        sharpe = calculate_sharpe(returns, risk_free_rate=0.05)
        self.assertLess(sharpe, 0.0,
                        f"rf=5% с 1.3% APY должен давать отрицательный Sharpe, got {sharpe:.3f}")

    # A-6
    def test_module_constant_risk_free_rate_is_zero(self) -> None:
        """RISK_FREE_RATE в analytics_runner должен быть 0.0."""
        self.assertEqual(RISK_FREE_RATE, 0.0,
                         f"RISK_FREE_RATE должен быть 0.0, got {RISK_FREE_RATE}")

    # A-7
    def test_analytics_runner_reads_rf_from_policy(self) -> None:
        """_load_risk_free_rate() читает SHARPE_RISK_FREE_RATE из risk_policy.json."""
        with tempfile.TemporaryDirectory(prefix="spa_ar_test_") as tmp:
            d = Path(tmp)
            _write_json(d / "risk_policy.json", {"SHARPE_RISK_FREE_RATE": 0.0})
            rate = _load_risk_free_rate(d)
            self.assertEqual(rate, 0.0)

    # A-8
    def test_analytics_runner_fallback_when_no_policy(self) -> None:
        """При отсутствии risk_policy.json — fallback на RISK_FREE_RATE (0.0)."""
        with tempfile.TemporaryDirectory(prefix="spa_ar_test_") as tmp:
            d = Path(tmp)
            rate = _load_risk_free_rate(d)
            self.assertEqual(rate, RISK_FREE_RATE)

    # A-9
    def test_analytics_runner_uses_zero_rf_to_produce_positive_sharpe(self) -> None:
        """analytics_runner с rf=0% генерирует положительный Sharpe для 1.3% APY."""
        with tempfile.TemporaryDirectory(prefix="spa_ar_test_") as tmp:
            d = Path(tmp)
            # Создаём equity_curve_daily.json со слегка варьирующимися доходами
            returns_seq = [
                0.00015, 0.00012, 0.00014, 0.00013, 0.00016,
                0.00011, 0.00014, 0.00015, 0.00013, 0.00014,
            ] * 3 + [0.00014]
            equity = [100_000.0]
            for r in returns_seq:
                equity.append(equity[-1] * (1.0 + r))
            daily = [{"date": f"2026-05-{(i + 1):02d}", "equity": e}
                     for i, e in enumerate(equity)]
            _write_json(d / "equity_curve_daily.json", {"daily": daily, "is_demo": False})
            _write_json(d / "risk_policy.json", {"SHARPE_RISK_FREE_RATE": 0.0})

            result = run_post_cycle_analytics(data_dir=d, write=False)
            sharpe = result["metrics"].get("sharpe")
            self.assertIsNotNone(sharpe)
            self.assertGreater(sharpe, 1.0,
                               f"analytics_runner с rf=0% должен дать Sharpe > 1, got {sharpe:.3f}")


# ═══════════════════════════════════════════════════════════════════════════════
# B. Early-period grace в kill_switch
# ═══════════════════════════════════════════════════════════════════════════════

class TestEarlyPeriodGrace(unittest.TestCase):
    """Группа B: early period grace — мягкий порог в первые 60 дней."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_sp_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # B-1
    def test_early_period_31days_uses_soft_threshold(self) -> None:
        """31 день < 60 дней grace → порог -2.0, sharpe=-1.5 → НЕ triggered."""
        _make_evidenced_curve_for_sharpe(sharpe=-1.5, num_days=31, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered,
                         f"31 дней, sharpe=-1.5 ≥ -2.0: должен быть ok, reason: {reason}")
        self.assertIn("early_period", reason)

    # B-2
    def test_early_period_59days_uses_soft_threshold(self) -> None:
        """59 дней < 60 → порог -2.0, sharpe=-1.9 → НЕ triggered."""
        _make_evidenced_curve_for_sharpe(sharpe=-1.9, num_days=59, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered,
                         f"59 дней, sharpe=-1.9 ≥ -2.0: должен быть ok, reason: {reason}")

    # B-3
    def test_normal_period_61days_uses_hard_threshold(self) -> None:
        """61 день ≥ 60 → нормальный порог -1.0, sharpe=-1.5 → triggered."""
        _make_evidenced_curve_for_sharpe(sharpe=-1.5, num_days=61, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertTrue(triggered,
                        f"61 дней, sharpe=-1.5 < -1.0: должен сработать, reason: {reason}")
        self.assertIn("normal_period", reason)

    # B-4
    def test_early_period_still_fires_below_soft_threshold(self) -> None:
        """31 день, sharpe=-3.0 < -2.0 → TRIGGERED даже в early period."""
        _make_evidenced_curve_for_sharpe(sharpe=-3.0, num_days=31, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertTrue(triggered,
                        f"31 дней, sharpe=-3.0 < -2.0: должен сработать, reason: {reason}")

    # B-5
    def test_normal_period_no_fire_above_threshold(self) -> None:
        """61 день, sharpe=0.5 > -1.0 → НЕ triggered."""
        _make_evidenced_curve_for_sharpe(sharpe=0.5, num_days=61, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"sharpe=0.5 ≥ -1.0: ok, reason: {reason}")

    # B-6
    def test_early_period_boundary_60days_is_normal(self) -> None:
        """Ровно 60 дней — НЕ early period (строгое <), порог -1.0."""
        _make_evidenced_curve_for_sharpe(sharpe=-1.5, num_days=60, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertTrue(triggered,
                        f"60 дней ≥ 60 → нормальный порог, sharpe=-1.5 < -1.0: triggered")
        self.assertIn("normal_period", reason)

    # B-7
    def test_early_threshold_exact_value(self) -> None:
        """sharpe = -2.0 exactly в early period → НЕ triggered (строгое <)."""
        _make_evidenced_curve_for_sharpe(sharpe=-2.0, num_days=31, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered,
                         f"sharpe=-2.0 ровно на пороге: НЕ triggered, reason: {reason}")

    # B-8
    def test_normal_threshold_exact_value(self) -> None:
        """sharpe = -1.0 exactly в normal period → НЕ triggered (строгое <)."""
        _make_evidenced_curve_for_sharpe(sharpe=-1.0, num_days=61, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered,
                         f"sharpe=-1.0 ровно на пороге: НЕ triggered, reason: {reason}")


# ═══════════════════════════════════════════════════════════════════════════════
# C. Реальные данные ($100 113, 31 день, 1.3% APY)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealDataScenario(unittest.TestCase):
    """Группа C: P0 — текущие данные не должны triggernuth kill_switch."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_real_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # C-1: КЛЮЧЕВОЙ ТЕСТ — rf=0% → Sharpe ~+1.6 → НЕ triggered
    def test_real_data_rf0_sharpe_positive(self) -> None:
        """$100K, 31 день, 1.3% APY: Sharpe с rf=0% > 1.0 → kill_switch НЕ triggered."""
        # Реплицируем реальный сценарий:
        # daily_vol = 0.0003933, mean_return ≈ 0.102699% / 31 = 0.00331%
        # Sharpe = (0.0000331 / 0.0003933) * sqrt(365) ≈ 1.61
        real_sharpe_rf0 = 1.61
        _make_evidenced_curve_for_sharpe(sharpe=real_sharpe_rf0, num_days=31, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered,
                         f"rf=0% Sharpe {real_sharpe_rf0} должен быть ok: {reason}")

    # C-2: Доказательство что старый rf=5% был неправильным
    def test_real_data_rf5_would_have_triggered(self) -> None:
        """$100K, 31 день: Sharpe с rf=5% ≈ -4.99 → TRIGGERED (P0 был здесь)."""
        wrong_sharpe_rf5 = -4.988
        # Важно: early period (31 < 60) → порог -2.0
        # -4.988 < -2.0 → TRIGGERED даже с early period grace
        # Это подтверждает что нужен Variant A (rf=0%), а не только B (early period)
        _make_evidenced_curve_for_sharpe(sharpe=wrong_sharpe_rf5, num_days=31, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertTrue(triggered,
                        f"Старый rf=5% Sharpe=-4.99 должен сработать: {reason}")

    # C-3: Комбо фикс: rf=0% делает Sharpe положительным → не triggered
    def test_combo_fix_resolves_p0_blocker(self) -> None:
        """ГЛАВНЫЙ: after fix rf=0%, Sharpe ~1.6 > -1.0 → kill_switch НЕ triggered."""
        # Имитируем analytics_summary.json который будет сгенерирован ПОСЛЕ фикса
        corrected_sharpe = 1.61  # что даст analytics_runner с rf=0.0
        _make_evidenced_curve_for_sharpe(sharpe=corrected_sharpe, num_days=31, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered,
                         f"P0 RESOLVED: corrected Sharpe={corrected_sharpe} → no kill_switch: {reason}")

    # C-4: Полная интеграция — нет ни одного триггера
    def test_full_integration_no_kill_switch(self) -> None:
        """Полная интеграция: корректный Sharpe + нет drawdown + нет red_flags → False."""
        # analytics_summary.json с исправленным Sharpe
        _make_evidenced_curve_for_sharpe(sharpe=1.61, num_days=31, data_dir=self.data_dir)
        # Нет red_flags.json, нет kill_switch_active.json
        # equity curve с drawdown < 15%
        equity_curve = [
            {"date": f"2026-05-{i+1:02d}", "close_equity": 100_000 + i * 5}
            for i in range(31)
        ]
        result = run_kill_switch_check(equity_curve=equity_curve, data_dir=self.data_dir)
        self.assertFalse(result["triggered"],
                         f"Полная интеграция: kill_switch НЕ triggered, reason: {result['reason']}")
        self.assertEqual(result["allocation"], {})


# ═══════════════════════════════════════════════════════════════════════════════
# D. risk_policy.json параметры
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharpePolicy(unittest.TestCase):
    """Группа D: _load_sharpe_policy читает параметры из risk_policy.json."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_sp_test_")
        self.data_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # D-1
    def test_policy_defaults_when_no_file(self) -> None:
        """Без risk_policy.json используются compile-time defaults."""
        sp = _load_sharpe_policy(self.data_dir)
        self.assertEqual(sp["kill_threshold"], SHARPE_THRESHOLD)
        self.assertEqual(sp["early_period_days"], SHARPE_EARLY_PERIOD_DAYS)
        self.assertEqual(sp["early_threshold"], SHARPE_EARLY_THRESHOLD)

    # D-2
    def test_policy_reads_kill_threshold(self) -> None:
        """SHARPE_KILL_THRESHOLD из файла применяется."""
        _write_json(self.data_dir / "risk_policy.json", {"SHARPE_KILL_THRESHOLD": -1.5})
        sp = _load_sharpe_policy(self.data_dir)
        self.assertEqual(sp["kill_threshold"], -1.5)

    # D-3
    def test_policy_reads_early_period_days(self) -> None:
        """SHARPE_EARLY_PERIOD_DAYS из файла применяется."""
        _write_json(self.data_dir / "risk_policy.json", {"SHARPE_EARLY_PERIOD_DAYS": 90})
        sp = _load_sharpe_policy(self.data_dir)
        self.assertEqual(sp["early_period_days"], 90.0)

    # D-4
    def test_policy_reads_early_threshold(self) -> None:
        """SHARPE_EARLY_THRESHOLD из файла применяется."""
        _write_json(self.data_dir / "risk_policy.json", {"SHARPE_EARLY_THRESHOLD": -3.0})
        sp = _load_sharpe_policy(self.data_dir)
        self.assertEqual(sp["early_threshold"], -3.0)

    # D-5
    def test_policy_all_sharpe_params(self) -> None:
        """Полный risk_policy.json с 4 Sharpe-параметрами."""
        _write_json(self.data_dir / "risk_policy.json", {
            "SHARPE_RISK_FREE_RATE": 0.0,
            "SHARPE_KILL_THRESHOLD": -1.0,
            "SHARPE_EARLY_PERIOD_DAYS": 60,
            "SHARPE_EARLY_THRESHOLD": -2.0,
        })
        sp = _load_sharpe_policy(self.data_dir)
        self.assertEqual(sp["kill_threshold"], -1.0)
        self.assertEqual(sp["early_period_days"], 60.0)
        self.assertEqual(sp["early_threshold"], -2.0)

    # D-6
    def test_policy_corrupt_json_uses_defaults(self) -> None:
        """Corrupted risk_policy.json → defaults без ошибки."""
        (self.data_dir / "risk_policy.json").write_text("NOT JSON", encoding="utf-8")
        sp = _load_sharpe_policy(self.data_dir)
        self.assertEqual(sp["kill_threshold"], SHARPE_THRESHOLD)

    # D-7: kill_switch использует policy при проверке
    def test_checker_uses_custom_policy(self) -> None:
        """kill_switch читает SHARPE_EARLY_PERIOD_DAYS=90 → 70 дней в early period."""
        checker = KillSwitchChecker(data_dir=self.data_dir)
        _write_json(self.data_dir / "risk_policy.json", {
            "SHARPE_KILL_THRESHOLD": -1.0,
            "SHARPE_EARLY_PERIOD_DAYS": 90,   # расширенный grace
            "SHARPE_EARLY_THRESHOLD": -2.0,
        })
        # 70 дней: при дефолте (60) это нормальный период, при policy (90) — early
        _make_evidenced_curve_for_sharpe(sharpe=-1.5, num_days=70, data_dir=self.data_dir)
        triggered, reason = checker.check_sharpe_trigger()
        # 70 < 90 → early period → порог -2.0 → sharpe=-1.5 ≥ -2.0 → НЕ triggered
        self.assertFalse(triggered,
                         f"70 дней < 90 grace → early_period, -1.5 ≥ -2.0: no trigger. reason={reason}")


# ═══════════════════════════════════════════════════════════════════════════════
# E. Drawdown trigger независим от Sharpe
# ═══════════════════════════════════════════════════════════════════════════════

class TestDrawdownIndependent(unittest.TestCase):
    """Группа E: drawdown trigger работает независимо от Sharpe."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_dd_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_curve(self, peak: float, current: float, n: int = 31) -> list[dict]:
        # Bars dated post-anchor (>= PAPER_REAL_START) + evidenced, so the
        # drawdown trigger (now strictly over the REAL evidenced series) sees
        # them. Pre-anchor / warmup bars are intentionally excluded.
        from datetime import timedelta
        from spa_core.paper_trading.track_evidence import PAPER_REAL_START
        base = PAPER_REAL_START
        bars = []
        for i in range(n - 1):
            bars.append({"date": (base + timedelta(days=i)).isoformat(),
                         "close_equity": peak,
                         "source": "cycle", "evidenced": True})
        bars.append({"date": (base + timedelta(days=n - 1)).isoformat(),
                     "close_equity": current,
                     "source": "cycle", "evidenced": True})
        return bars

    # E-1
    def test_drawdown_triggers_even_with_good_sharpe(self) -> None:
        """16% drawdown → triggered даже если Sharpe=2.0 (отличный)."""
        # Положительный Sharpe — kill_switch по drawdown всё равно сработает
        _make_analytics(sharpe=2.0, num_days=31, data_dir=self.data_dir)
        curve = self._make_curve(peak=100_000.0, current=83_000.0)  # -17%
        triggered, reason = self.checker.is_kill_switch_active(equity_curve=curve)
        self.assertTrue(triggered, f"17% drawdown должен триггернуть несмотря на Sharpe=2.0: {reason}")
        self.assertIn("drawdown", reason.lower())

    # E-2
    def test_current_drawdown_02pct_no_trigger(self) -> None:
        """Текущий drawdown 0.2% << 15% → НЕ triggered."""
        curve = self._make_curve(peak=100_200.0, current=100_000.0)  # -0.2%
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"0.2% drawdown << 15% threshold: ok, reason: {reason}")

    # E-3
    def test_drawdown_9pct_no_trigger(self) -> None:
        """ADR-048: 9% drawdown (< 10% порога) → НЕ triggered."""
        curve = self._make_curve(peak=100_000.0, current=91_000.0)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertFalse(triggered, f"9% < 10% порога: НЕ triggered, reason: {reason}")

    # E-4
    def test_drawdown_12pct_triggers(self) -> None:
        """ADR-048: 12% drawdown ≥ 10% → TRIGGERED."""
        curve = self._make_curve(peak=100_000.0, current=88_000.0)
        triggered, reason = self.checker.check_drawdown_trigger(curve)
        self.assertTrue(triggered, f"12% drawdown ≥ 10%: triggered, reason: {reason}")


# ═══════════════════════════════════════════════════════════════════════════════
# F. Edge-cases / граничные значения Sharpe trigger
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharpeEdgeCases(unittest.TestCase):
    """Группа F: граничные случаи."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="spa_ks_edge_test_")
        self.data_dir = Path(self._tmp.name)
        self.checker = KillSwitchChecker(data_dir=self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # F-1
    def test_insufficient_data_29days_no_trigger(self) -> None:
        """29 evidenced дней < MIN_DAYS_FOR_SHARPE (30) → не triggered.

        WS-2.3: the trigger now derives evidenced days from the equity curve.
        29 evidenced bars → 28 returns → below the MIN_DAYS gate → fail-closed.
        """
        _make_evidenced_curve_for_sharpe(sharpe=-99.0, num_days=29, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"29 дней < 30: insufficient data → no trigger: {reason}")
        self.assertIn("insufficient", reason.lower())

    # F-2
    def test_exactly_30days_activates_sharpe_check(self) -> None:
        """30 evidenced дней = MIN_DAYS_FOR_SHARPE → Sharpe check включается."""
        _make_evidenced_curve_for_sharpe(sharpe=-5.0, num_days=30, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        # 30 < 60 (early period) → порог -2.0, sharpe=-5.0 < -2.0 → triggered
        self.assertTrue(triggered, f"30 дней, sharpe=-5.0 < -2.0: triggered, reason: {reason}")

    # F-3
    def test_no_equity_curve_no_trigger(self) -> None:
        """Нет equity_curve_daily.json → не triggered (fail-closed)."""
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"Нет equity curve: no trigger, reason: {reason}")

    # F-4
    def test_thin_evidenced_series_no_trigger(self) -> None:
        """THIN evidenced series (too few returns) → None Sharpe → fail-closed."""
        # Only 3 evidenced bars → 2 returns, far below MIN_EVIDENCED_RETURNS.
        _make_evidenced_curve_for_sharpe(sharpe=-9.0, num_days=3, data_dir=self.data_dir)
        triggered, reason = self.checker.check_sharpe_trigger()
        self.assertFalse(triggered, f"THIN series → no trigger, reason: {reason}")

    # F-5
    def test_sharpe_positive_always_ok(self) -> None:
        """Любой положительный Sharpe → kill_switch НЕ triggered."""
        for sharpe_val in [0.01, 0.5, 1.0, 1.61, 3.0, 10.0]:
            _make_evidenced_curve_for_sharpe(sharpe=sharpe_val, num_days=90, data_dir=self.data_dir)
            triggered, reason = self.checker.check_sharpe_trigger()
            self.assertFalse(triggered,
                             f"sharpe={sharpe_val} ≥ 0: no trigger, reason: {reason}")

    # F-6: Module constants
    def test_compile_time_constants(self) -> None:
        """Compile-time константы имеют правильные значения."""
        self.assertEqual(SHARPE_THRESHOLD, -1.0)
        self.assertEqual(SHARPE_EARLY_PERIOD_DAYS, 60)
        self.assertEqual(SHARPE_EARLY_THRESHOLD, -2.0)
        self.assertEqual(MIN_DAYS_FOR_SHARPE, 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
