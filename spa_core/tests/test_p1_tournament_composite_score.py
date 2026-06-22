"""
spa_core/tests/test_p1_tournament_composite_score.py

P1.2 — Tests: честный composite_score в TournamentEvaluator.

Проверяет:
  - compute_composite_score = 0.0 при is_statistically_significant=False
  - compute_composite_score > 0 при реальных данных (>= MIN_OBS)
  - Поля has_real_data и days_observed присутствуют в to_dict()
  - Стратегии без данных больше НЕ получают артефактный балл 0.3386

Run:
    python3 -m pytest spa_core/tests/test_p1_tournament_composite_score.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.paper_trading.tournament_evaluator import (
    MIN_OBS,
    StrategyMetrics,
    compute_composite_score,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

ARTIFACT_SCORE = 0.3386   # Старый артефактный балл (должен исчезнуть)


def _make_metrics(
    is_sig: bool,
    days: int = 5,
    sharpe: float | None = None,
    calmar: float | None = None,
    ulcer: float | None = None,
    rachev: float | None = None,
    realized_apy: float = 0.0,
    target_min: float = 4.0,
    target_max: float = 8.0,
) -> StrategyMetrics:
    """Фабрика StrategyMetrics для тестов."""
    return StrategyMetrics(
        strategy_id="test_strategy",
        name="Test Strategy",
        status="active",
        days_observed=days,
        current_equity=100_000.0,
        total_return_pct=0.0,
        realized_apy_pct=realized_apy,
        target_apy_min=target_min,
        target_apy_max=target_max,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        ulcer_index=ulcer,
        rachev_ratio=rachev,
        max_drawdown_pct=0.0,
        drawdown_pct=0.0,
        sharpe_ci_lower=None,
        sharpe_ci_upper=None,
        apy_vs_baseline_bps=None,
        is_statistically_significant=is_sig,
    )


# ─── Test 1: Zero score without real data ─────────────────────────────────────

class TestZeroScoreWithoutData(unittest.TestCase):
    """Стратегии без достаточного числа дней получают score=0.0, НЕ 0.3386."""

    def test_score_is_zero_when_not_significant(self):
        """При is_statistically_significant=False → score строго 0.0."""
        m = _make_metrics(is_sig=False, days=3)
        score = compute_composite_score(m)
        self.assertEqual(score, 0.0,
            f"Expected 0.0 for insufficient data, got {score}. "
            f"Old artifact value was {ARTIFACT_SCORE}")

    def test_score_is_not_artifact_338(self):
        """Артефактный балл 0.338597 больше не возвращается при нехватке данных."""
        for days in range(1, MIN_OBS):
            m = _make_metrics(is_sig=False, days=days)
            score = compute_composite_score(m)
            self.assertNotAlmostEqual(
                score, ARTIFACT_SCORE, places=3,
                msg=f"Got artifact score {score} for {days} days (< {MIN_OBS} required)"
            )

    def test_all_strategies_without_data_get_same_zero(self):
        """Все стратегии с нехваткой данных получают одинаковый балл 0.0."""
        scores = []
        for target_min, target_max in [(4, 8), (10, 20), (1, 3), (14, 42)]:
            m = _make_metrics(is_sig=False, days=5,
                              target_min=float(target_min), target_max=float(target_max))
            scores.append(compute_composite_score(m))
        # Все должны быть 0.0
        self.assertTrue(all(s == 0.0 for s in scores),
                        f"Not all zero: {scores}")

    def test_zero_days_gives_zero_score(self):
        m = _make_metrics(is_sig=False, days=0)
        self.assertEqual(compute_composite_score(m), 0.0)

    def test_min_obs_minus_one_gives_zero_score(self):
        """Ровно MIN_OBS-1 дней → всё ещё нулевой балл."""
        m = _make_metrics(is_sig=False, days=MIN_OBS - 1)
        self.assertEqual(compute_composite_score(m), 0.0)


# ─── Test 2: Real score with sufficient data ──────────────────────────────────

class TestRealScoreWithData(unittest.TestCase):
    """При is_statistically_significant=True → используется реальный расчёт."""

    def test_positive_sharpe_gives_score_above_zero(self):
        m = _make_metrics(
            is_sig=True, days=MIN_OBS,
            sharpe=1.5, calmar=0.8, ulcer=0.02, rachev=1.3,
            realized_apy=6.0,
        )
        score = compute_composite_score(m)
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_negative_sharpe_gives_low_score(self):
        m = _make_metrics(
            is_sig=True, days=MIN_OBS,
            sharpe=-2.0, calmar=-1.0, ulcer=0.1, rachev=0.5,
            realized_apy=-5.0,
        )
        score_bad = compute_composite_score(m)
        m_good = _make_metrics(
            is_sig=True, days=MIN_OBS,
            sharpe=2.0, calmar=1.5, ulcer=0.01, rachev=1.5,
            realized_apy=10.0,
        )
        score_good = compute_composite_score(m_good)
        self.assertLess(score_bad, score_good,
            "Bad metrics should give lower score than good metrics")

    def test_score_in_unit_range(self):
        """Score всегда в диапазоне [0, 1]."""
        test_cases = [
            dict(sharpe=5.0, calmar=10.0, ulcer=0.0, rachev=5.0, realized_apy=50.0),
            dict(sharpe=-5.0, calmar=-10.0, ulcer=0.5, rachev=0.1, realized_apy=-50.0),
            dict(sharpe=0.0, calmar=0.0, ulcer=0.05, rachev=1.0, realized_apy=5.0),
        ]
        for kwargs in test_cases:
            m = _make_metrics(is_sig=True, days=MIN_OBS, **kwargs)
            score = compute_composite_score(m)
            self.assertGreaterEqual(score, 0.0, f"Score {score} < 0 for {kwargs}")
            self.assertLessEqual(score, 1.0, f"Score {score} > 1 for {kwargs}")

    def test_sharpe_only_none_uses_neutral(self):
        """Если Sharpe=None (но is_sig=True), нейтральный 0.4 применяется только для Sharpe."""
        m = _make_metrics(
            is_sig=True, days=MIN_OBS,
            sharpe=None,   # Только Sharpe отсутствует
            calmar=1.0, ulcer=0.02, rachev=1.2,
            realized_apy=5.0,
        )
        score = compute_composite_score(m)
        # Должен быть > 0 (другие метрики есть)
        self.assertGreater(score, 0.0)

    def test_min_obs_boundary_with_real_data(self):
        """Ровно MIN_OBS дней с is_sig=True → реальный расчёт."""
        m = _make_metrics(
            is_sig=True, days=MIN_OBS,
            sharpe=1.0, calmar=0.6,
            realized_apy=5.0,
        )
        score = compute_composite_score(m)
        self.assertGreater(score, 0.0)


# ─── Test 3: StrategyMetrics fields ───────────────────────────────────────────

class TestStrategyMetricsFields(unittest.TestCase):
    """StrategyMetrics.has_real_data и to_dict() содержат нужные поля."""

    def test_has_real_data_false_when_not_significant(self):
        m = _make_metrics(is_sig=False, days=5)
        self.assertFalse(m.has_real_data)

    def test_has_real_data_true_when_significant(self):
        m = _make_metrics(is_sig=True, days=MIN_OBS)
        self.assertTrue(m.has_real_data)

    def test_to_dict_contains_has_real_data(self):
        m = _make_metrics(is_sig=False)
        d = m.to_dict()
        self.assertIn("has_real_data", d,
            "to_dict() must include 'has_real_data' field")
        self.assertFalse(d["has_real_data"])

    def test_to_dict_contains_days_observed(self):
        m = _make_metrics(is_sig=False, days=7)
        d = m.to_dict()
        self.assertIn("days_observed", d)
        self.assertEqual(d["days_observed"], 7)

    def test_to_dict_has_real_data_true(self):
        m = _make_metrics(is_sig=True, days=MIN_OBS)
        d = m.to_dict()
        self.assertTrue(d["has_real_data"])

    def test_to_dict_has_real_data_matches_is_statistically_significant(self):
        for sig in (True, False):
            m = _make_metrics(is_sig=sig)
            d = m.to_dict()
            self.assertEqual(d["has_real_data"], d["is_statistically_significant"])

    def test_days_observed_preserved_in_to_dict(self):
        for days in (0, 1, MIN_OBS - 1, MIN_OBS, MIN_OBS + 10):
            m = _make_metrics(is_sig=(days >= MIN_OBS), days=days)
            d = m.to_dict()
            self.assertEqual(d["days_observed"], days)


# ─── Test 4: Integration — score ordering ─────────────────────────────────────

class TestScoreOrdering(unittest.TestCase):
    """Стратегии ранжируются корректно: нет данных < есть данные."""

    def test_no_data_ranks_below_any_real_data(self):
        """Любая стратегия с реальными данными должна быть выше нулевого балла."""
        no_data = _make_metrics(is_sig=False, days=1)
        score_no_data = compute_composite_score(no_data)

        # Даже стратегия с нулевым Sharpe и is_sig=True > 0
        with_data = _make_metrics(
            is_sig=True, days=MIN_OBS,
            sharpe=0.1, calmar=0.2, ulcer=0.05, rachev=1.1,
            realized_apy=4.5,
        )
        score_with_data = compute_composite_score(with_data)

        self.assertEqual(score_no_data, 0.0)
        self.assertGreater(score_with_data, score_no_data)

    def test_better_sharpe_gives_higher_score(self):
        m_low = _make_metrics(is_sig=True, days=MIN_OBS, sharpe=0.5)
        m_high = _make_metrics(is_sig=True, days=MIN_OBS, sharpe=2.0)
        self.assertLess(
            compute_composite_score(m_low),
            compute_composite_score(m_high),
        )

    def test_min_obs_constant_is_14(self):
        """MIN_OBS должен быть 14 (зафиксировано в документации)."""
        self.assertEqual(MIN_OBS, 14)


if __name__ == "__main__":
    unittest.main(verbosity=2)
