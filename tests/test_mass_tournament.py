# LLM_FORBIDDEN
"""
Tests for spa_core/backtesting/mass_tournament.py and
spa_core/backtesting/strategy_tournament_runner.py

Coverage (55+ tests):
  - Strategy file discovery
  - Source-code analysis (leverage detection, AMM LP detection, class finding)
  - Allocation normalization (dollars vs weights, aliasing, unknown protocols)
  - Allocation extraction with mock APY (various signatures)
  - MassTournament.run() — full integration smoke test
  - Leaderboard sorting by Sharpe
  - Skip-reason recording
  - StrategyTournamentRunner.run() — reads mass results, writes tournament JSON
  - shadow_paper_trading.json initialisation
  - run_shadow_day() — daily simulation and ring-buffer append
  - ProfessionalBacktest.run_strategy() — added helper method
  - JSON schema validation for all output files
  - Atomic write helper
  - Edge cases: empty allocation, all-zero weights, duplicate aliases, single protocol

LLM_FORBIDDEN: no LLM calls in this module.
"""
# LLM_FORBIDDEN

from __future__ import annotations
from spa_core.utils.errors import SPAError

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# ── project path ──────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.backtesting.mass_tournament import (
    INITIAL_CAPITAL,
    KNOWN_PROTOCOLS,
    MOCK_APY,
    PROTOCOL_ALIAS,
    MassTournament,
    _atomic_write_json,
)
from spa_core.backtesting.strategy_tournament_runner import (
    StrategyTournamentRunner,
    run_shadow_day,
)
from spa_core.backtesting.professional_backtest import ProfessionalBacktest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_leaderboard(n: int) -> List[Dict]:
    """Generate a fake leaderboard list of length *n*."""
    protocols = list(KNOWN_PROTOCOLS)
    entries = []
    for i in range(n):
        entries.append({
            "rank":              i + 1,
            "id":                f"s{50 + i}_test_strategy",
            "class":             f"TestStrategy{i}",
            "method_used":       "get_allocation()",
            "sharpe":            round(10.0 - i * 0.5, 4),
            "sortino":           round(12.0 - i * 0.4, 4),
            "calmar":            round(5.0 - i * 0.1, 4),
            "annual_return_pct": round(4.5 - i * 0.1, 4),
            "total_return_pct":  round(20.0 - i * 0.4, 4),
            "max_dd_pct":        round(0.05 + i * 0.01, 6),
            "volatility_pct":    round(0.5 + i * 0.05, 6),
            "win_rate_pct":      round(60.0 - i * 0.5, 4),
            "final_equity_usd":  round(120_000 - i * 500, 2),
            "allocation":        {protocols[i % len(protocols)]: 0.6,
                                  protocols[(i + 1) % len(protocols)]: 0.4},
        })
    return entries


def _make_mass_result(n: int = 10) -> Dict:
    """Build a minimal mass_tournament_results.json payload."""
    lb = _make_leaderboard(n)
    return {
        "generated_at":       "2026-06-22T00:00:00+00:00",
        "version":            "v1.0",
        "llm_forbidden":      True,
        "simulation_period":  "2022-01-01 to 2025-12-31",
        "initial_capital_usd": INITIAL_CAPITAL,
        "strategies_tested":  n,
        "strategies_skipped": 3,
        "total_files_scanned": n + 3,
        "skip_reasons": {
            "s3_yield_loop": "leverage_detected",
            "s2_lp_stable":  "amm_lp_strategy",
            "s21_aave_loop": "leverage_detected",
        },
        "leaderboard": lb,
        "top_5":    lb[:5],
        "bottom_5": lb[-5:],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Constants and module-level checks
# ─────────────────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_known_protocols_not_empty(self):
        self.assertGreater(len(KNOWN_PROTOCOLS), 0)

    def test_known_protocols_are_strings(self):
        for p in KNOWN_PROTOCOLS:
            self.assertIsInstance(p, str)

    def test_mock_apy_covers_known_protocols(self):
        for p in KNOWN_PROTOCOLS:
            self.assertIn(p, MOCK_APY, f"{p} missing from MOCK_APY")

    def test_mock_apy_values_are_positive(self):
        for k, v in MOCK_APY.items():
            self.assertGreater(v, 0, f"{k} has non-positive APY in MOCK_APY")

    def test_mock_apy_values_are_fractions(self):
        """All mock APY values should be in [0, 1] (decimal fractions)."""
        for k, v in MOCK_APY.items():
            self.assertLess(v, 1.0, f"{k}={v} looks like a percent not a fraction")

    def test_protocol_alias_values_are_known_or_none(self):
        for src, dest in PROTOCOL_ALIAS.items():
            if dest is not None:
                self.assertIn(dest, KNOWN_PROTOCOLS,
                              f"Alias {src}->{dest} not in KNOWN_PROTOCOLS")

    def test_initial_capital(self):
        self.assertEqual(INITIAL_CAPITAL, 100_000.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Atomic write helper
# ─────────────────────────────────────────────────────────────────────────────

class TestAtomicWriteJson(unittest.TestCase):

    def test_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.json"
            _atomic_write_json(p, {"key": "value", "num": 42})
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(data["key"], "value")
            self.assertEqual(data["num"], 42)

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sub" / "dir" / "file.json"
            _atomic_write_json(p, [1, 2, 3])
            self.assertTrue(p.exists())

    def test_no_tmp_file_left(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.json"
            _atomic_write_json(p, {"x": 1})
            tmp = Path(str(p) + ".tmp")
            self.assertFalse(tmp.exists())

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.json"
            _atomic_write_json(p, {"v": 1})
            _atomic_write_json(p, {"v": 2})
            with open(p) as fh:
                data = json.load(fh)
            self.assertEqual(data["v"], 2)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Source-code analysis (MassTournament static methods)
# ─────────────────────────────────────────────────────────────────────────────

class TestLeverageDetection(unittest.TestCase):

    def test_detects_borrow_amount_field(self):
        src = """
class S3Loop:
    borrow_amount: float = 0.0
    deposit_amount: float = 100_000.0
"""
        self.assertTrue(MassTournament.detect_leverage(src))

    def test_detects_loop_factor(self):
        src = "LOOP_FACTOR = 2.5\nMAX_LOOPS = 3\n"
        self.assertTrue(MassTournament.detect_leverage(src))

    def test_detects_max_loops(self):
        src = "MAX_LOOPS: int = 3\n"
        self.assertTrue(MassTournament.detect_leverage(src))

    def test_clean_strategy_no_leverage(self):
        src = """
class S46SafeHarbor:
    def get_allocation(self, capital_usd):
        return {"aave_v3": capital_usd * 0.4, "compound_v3": capital_usd * 0.6}
"""
        self.assertFalse(MassTournament.detect_leverage(src))

    def test_borrow_in_comment_not_detected(self):
        # "borrow" as plain word in comment shouldn't trigger
        # (our pattern matches "borrow_amount :=" specifically)
        src = "# This strategy does not borrow funds\n"
        self.assertFalse(MassTournament.detect_leverage(src))


class TestAmmLpDetection(unittest.TestCase):

    def test_detects_is_lp_pool(self):
        src = "def _is_lp_pool(self, key): return True\n"
        self.assertTrue(MassTournament.detect_amm_lp(src))

    def test_detects_impermanent_loss(self):
        src = "il = impermanent_loss * portfolio_value\n"
        self.assertTrue(MassTournament.detect_amm_lp(src))

    def test_clean_lending_not_amm(self):
        src = """
class S30AllWeather:
    def get_allocation(self):
        return {"aave_v3": 0.3, "compound_v3": 0.25}
"""
        self.assertFalse(MassTournament.detect_amm_lp(src))


class TestFindPrimaryClass(unittest.TestCase):

    def test_finds_single_class(self):
        src = "class MyStrategy:\n    pass\n"
        self.assertEqual(MassTournament.find_primary_class(src), "MyStrategy")

    def test_skips_private_class(self):
        src = "class _Helper:\n    pass\nclass RealStrategy:\n    pass\n"
        self.assertEqual(MassTournament.find_primary_class(src), "RealStrategy")

    def test_returns_first_public(self):
        src = "class Alpha:\n    pass\nclass Beta:\n    pass\n"
        self.assertEqual(MassTournament.find_primary_class(src), "Alpha")

    def test_no_class_returns_none(self):
        src = "# no class here\nFOO = 1\n"
        self.assertIsNone(MassTournament.find_primary_class(src))

    def test_skips_adapter_mixin(self):
        src = "class AdapterAPYMixin:\n    pass\nclass S46Strategy:\n    pass\n"
        self.assertEqual(MassTournament.find_primary_class(src), "S46Strategy")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Allocation normalization
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeAllocation(unittest.TestCase):

    def test_weight_format_passthrough(self):
        raw = {"aave_v3": 0.4, "compound_v3": 0.6}
        result = MassTournament.normalize_allocation(raw)
        self.assertAlmostEqual(result.get("aave_v3", 0), 0.4, places=5)
        self.assertAlmostEqual(result.get("compound_v3", 0), 0.6, places=5)

    def test_dollar_format_normalised(self):
        raw = {"aave_v3": 40_000.0, "compound_v3": 60_000.0}
        result = MassTournament.normalize_allocation(raw)
        self.assertAlmostEqual(result.get("aave_v3", 0), 0.4, places=5)
        self.assertAlmostEqual(result.get("compound_v3", 0), 0.6, places=5)

    def test_cash_excluded(self):
        raw = {"aave_v3": 0.7, "cash": 0.3}
        result = MassTournament.normalize_allocation(raw)
        self.assertNotIn("cash", result)
        self.assertIn("aave_v3", result)

    def test_morpho_blue_aliased_to_steakhouse(self):
        raw = {"morpho_blue": 0.5, "aave_v3": 0.5}
        result = MassTournament.normalize_allocation(raw)
        self.assertIn("morpho_steakhouse", result)
        self.assertNotIn("morpho_blue", result)

    def test_sky_susds_aliased_to_spark(self):
        raw = {"sky_susds": 0.4, "compound_v3": 0.6}
        result = MassTournament.normalize_allocation(raw)
        self.assertIn("spark_susds", result)
        self.assertNotIn("sky_susds", result)

    def test_aave_arbitrum_kept_as_own_series(self):
        # aave_v3_arbitrum now has its own REAL per-chain series (PROTOCOL_ALIAS
        # maps it to itself, not to the ETH-tracked aave_v3 proxy), so it must be
        # preserved as a first-class key in the normalised allocation.
        raw = {"aave_v3_arbitrum": 0.5, "compound_v3": 0.5}
        result = MassTournament.normalize_allocation(raw)
        self.assertIn("aave_v3_arbitrum", result)

    def test_pendle_pt_dropped(self):
        raw = {"pendle_pt": 0.5, "aave_v3": 0.5}
        result = MassTournament.normalize_allocation(raw)
        self.assertNotIn("pendle_pt", result)
        # aave_v3 should still be there (possibly renormalised)
        self.assertIn("aave_v3", result)

    def test_unknown_protocol_dropped(self):
        raw = {"aave_v3": 0.4, "unknown_xyz": 0.6}
        result = MassTournament.normalize_allocation(raw)
        self.assertNotIn("unknown_xyz", result)
        self.assertIn("aave_v3", result)

    def test_weights_sum_at_most_one(self):
        raw = {"aave_v3": 0.4, "compound_v3": 0.4, "morpho_steakhouse": 0.4}
        result = MassTournament.normalize_allocation(raw)
        self.assertLessEqual(sum(result.values()), 1.0 + 1e-9)

    def test_empty_dict_returns_empty(self):
        self.assertEqual(MassTournament.normalize_allocation({}), {})

    def test_all_zeros_returns_empty(self):
        self.assertEqual(MassTournament.normalize_allocation({"aave_v3": 0.0}), {})

    def test_duplicate_alias_merged(self):
        # Both morpho_blue and morpho_steakhouse map to morpho_steakhouse
        raw = {"morpho_blue": 0.2, "morpho_steakhouse": 0.3, "aave_v3": 0.5}
        result = MassTournament.normalize_allocation(raw)
        # morpho_steakhouse should be sum of 0.2+0.3=0.5, aave_v3=0.5
        # after renorm: each 0.5
        self.assertIn("morpho_steakhouse", result)
        self.assertIn("aave_v3", result)

    def test_none_values_skipped(self):
        raw = {"aave_v3": 0.4, "compound_v3": None}
        result = MassTournament.normalize_allocation(raw)
        self.assertIn("aave_v3", result)
        self.assertNotIn("compound_v3", result)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Allocation extraction (using real strategy classes)
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractAllocation(unittest.TestCase):

    def setUp(self):
        self.mt = MassTournament()

    def test_extract_s46_safe_harbor(self):
        alloc, method = self.mt.extract_allocation(
            "spa_core.strategies.s46_safe_harbor",
            "SafeHarborStrategy",
            "",
        )
        self.assertIsNotNone(alloc, f"Should extract allocation but got: {method}")
        self.assertIsInstance(alloc, dict)
        self.assertGreater(len(alloc), 0)
        self.assertLessEqual(sum(alloc.values()), 1.0 + 1e-9)

    def test_extract_s30_all_weather(self):
        alloc, method = self.mt.extract_allocation(
            "spa_core.strategies.s30_all_weather",
            "S30AllWeather",
            "",
        )
        self.assertIsNotNone(alloc, f"Should extract: {method}")
        self.assertGreater(len(alloc), 0)

    def test_extract_s1_t1t2_balanced(self):
        alloc, method = self.mt.extract_allocation(
            "spa_core.strategies.s1_t1t2_balanced",
            "S1T1T2BalancedStrategy",
            "",
        )
        self.assertIsNotNone(alloc)

    def test_import_error_returns_none(self):
        alloc, reason = self.mt.extract_allocation(
            "spa_core.strategies.nonexistent_module_xyz",
            "SomeClass",
            "",
        )
        self.assertIsNone(alloc)
        self.assertIn("import_error", reason)

    def test_class_not_found_returns_none(self):
        alloc, reason = self.mt.extract_allocation(
            "spa_core.strategies.s46_safe_harbor",
            "NonExistentClass999",
            "",
        )
        self.assertIsNone(alloc)

    def test_all_known_protocols_in_result(self):
        """All extracted protocol keys should be from KNOWN_PROTOCOLS."""
        alloc, method = self.mt.extract_allocation(
            "spa_core.strategies.s46_safe_harbor",
            "SafeHarborStrategy",
            "",
        )
        if alloc:
            for k in alloc:
                self.assertIn(k, KNOWN_PROTOCOLS, f"Protocol {k} not known")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Leverage and AMM skip in real strategy files
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategySkipLogic(unittest.TestCase):

    def setUp(self):
        self.mt = MassTournament()

    def _load_content(self, fname: str) -> str:
        p = _PROJECT_ROOT / "spa_core" / "strategies" / fname
        with open(p) as fh:
            return fh.read()

    def test_s3_yield_loop_detected_as_leverage(self):
        content = self._load_content("s3_yield_loop.py")
        self.assertTrue(self.mt.detect_leverage(content))

    def test_s2_lp_stable_detected_as_amm(self):
        content = self._load_content("s2_lp_stable.py")
        self.assertTrue(self.mt.detect_amm_lp(content))

    def test_s46_safe_harbor_not_leverage(self):
        content = self._load_content("s46_safe_harbor.py")
        self.assertFalse(self.mt.detect_leverage(content))

    def test_s55_max_sharpe_not_leverage(self):
        content = self._load_content("s55_max_sharpe_portfolio.py")
        self.assertFalse(self.mt.detect_leverage(content))


# ─────────────────────────────────────────────────────────────────────────────
# 7. ProfessionalBacktest.run_strategy() added method
# ─────────────────────────────────────────────────────────────────────────────

class TestRunStrategy(unittest.TestCase):

    def setUp(self):
        self.bt = ProfessionalBacktest(add_noise=False)

    def test_run_strategy_returns_dict(self):
        alloc = {"aave_v3": 0.5, "compound_v3": 0.5}
        result = self.bt.run_strategy(alloc, strategy_name="test")
        self.assertIsInstance(result, dict)

    def test_run_strategy_has_sharpe(self):
        alloc = {"aave_v3": 0.4, "morpho_steakhouse": 0.6}
        result = self.bt.run_strategy(alloc)
        self.assertIn("sharpe_ratio", result)
        self.assertIsInstance(result["sharpe_ratio"], float)

    def test_run_strategy_has_required_keys(self):
        alloc = {"aave_v3": 0.5, "compound_v3": 0.5}
        result = self.bt.run_strategy(alloc)
        for key in [
            "sharpe_ratio", "annualized_return_pct", "max_drawdown_pct",
            "calmar_ratio", "sortino_ratio", "total_return_pct",
            "weights", "cash_pct",
        ]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_run_strategy_positive_return(self):
        alloc = {"aave_v3": 0.5, "compound_v3": 0.5}
        result = self.bt.run_strategy(alloc)
        # Lending strategies should produce positive returns over 4 years
        self.assertGreater(result["annualized_return_pct"], 0)

    def test_run_strategy_empty_raises(self):
        with self.assertRaises((ValueError, Exception)):
            self.bt.run_strategy({})

    def test_run_strategy_weights_preserved(self):
        alloc = {"aave_v3": 0.3, "compound_v3": 0.7}
        result = self.bt.run_strategy(alloc, "my_strat")
        self.assertEqual(result["weights"], alloc)

    def test_run_strategy_single_protocol(self):
        alloc = {"aave_v3": 1.0}
        result = self.bt.run_strategy(alloc)
        self.assertIn("sharpe_ratio", result)

    def test_cash_pct_computed(self):
        alloc = {"aave_v3": 0.7}  # 30% cash
        result = self.bt.run_strategy(alloc)
        self.assertAlmostEqual(result["cash_pct"], 0.3, places=5)


# ─────────────────────────────────────────────────────────────────────────────
# 8. MassTournament.run() — integration smoke test
# ─────────────────────────────────────────────────────────────────────────────

class TestMassTournamentRun(unittest.TestCase):
    """Integration tests for MassTournament.run().

    Uses setUpClass so the full tournament runs only once for the entire class
    (avoiding 12× repeated 60-strategy backtests with DeFiLlama retry delays).
    """

    _tmpdir: Any = None
    _data_dir: Any = None
    _result: Any = None

    @classmethod
    def setUpClass(cls) -> None:  # type: ignore[override]
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._data_dir = Path(cls._tmpdir.name)
        mt = MassTournament(data_dir=cls._data_dir, add_noise=False)
        cls._result = mt.run()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._tmpdir:
            cls._tmpdir.cleanup()

    def test_run_produces_output_file(self):
        out = self._data_dir / "mass_tournament_results.json"
        self.assertTrue(out.exists(), "mass_tournament_results.json should be created")

    def test_run_returns_dict_with_required_keys(self):
        for key in [
            "generated_at", "version", "strategies_tested",
            "strategies_skipped", "skip_reasons", "leaderboard",
            "top_5", "bottom_5",
        ]:
            self.assertIn(key, self._result, f"Missing key: {key}")

    def test_run_leaderboard_sorted_by_net_return(self):
        # OWNER DECISION 2026-06-27: leaderboard ranks by net-of-cost annual
        # return (net_annual_return_pct), NOT Sharpe. Rows with a finite net
        # return are ordered descending; UNKNOWN rows (no finite net return)
        # sort last. Sharpe is only a tiebreaker.
        lb = self._result["leaderboard"]
        self.assertEqual(self._result["meta"]["rank_metric"], "net_annual_return_pct")
        finite = [e for e in lb if not e.get("rank_unknown", False)]
        for i in range(len(finite) - 1):
            self.assertGreaterEqual(
                finite[i]["annual_return_pct"], finite[i + 1]["annual_return_pct"],
                "Leaderboard not sorted by net return desc"
            )
        # UNKNOWN rows (if any) must all come after the finite ones.
        seen_unknown = False
        for e in lb:
            if e.get("rank_unknown", False):
                seen_unknown = True
            elif seen_unknown:
                self.fail("A finite-net-return row ranked below an UNKNOWN row")

    def test_degenerate_sharpe_flagged(self):
        # |Sharpe| > 100 must be flagged degenerate and shown as locked-vol n/a.
        for e in self._result["leaderboard"]:
            if e.get("sharpe_degenerate"):
                self.assertEqual(e["sharpe_display"], "n/a (locked-vol)")
            else:
                self.assertIsInstance(e["sharpe_display"], (int, float))

    def test_run_leaderboard_has_ranks(self):
        for i, entry in enumerate(self._result["leaderboard"], 1):
            self.assertEqual(entry["rank"], i)

    def test_run_at_least_some_strategies_tested(self):
        self.assertGreater(self._result["strategies_tested"], 0)

    def test_run_skip_reasons_is_dict(self):
        self.assertIsInstance(self._result["skip_reasons"], dict)

    def test_run_leverage_strategies_skipped(self):
        self.assertIn("s3_yield_loop", self._result["skip_reasons"])
        self.assertEqual(
            self._result["skip_reasons"]["s3_yield_loop"], "leverage_detected"
        )

    def test_run_top5_length(self):
        self.assertLessEqual(len(self._result["top_5"]), 5)

    def test_run_bottom5_length(self):
        self.assertLessEqual(len(self._result["bottom_5"]), 5)

    def test_run_all_allocation_protocols_known(self):
        for entry in self._result["leaderboard"]:
            for proto in entry.get("allocation", {}):
                self.assertIn(
                    proto, KNOWN_PROTOCOLS,
                    f"Unknown protocol {proto} in {entry['id']}"
                )

    def test_run_output_valid_json(self):
        out = self._data_dir / "mass_tournament_results.json"
        with open(out) as fh:
            data = json.load(fh)
        self.assertIn("leaderboard", data)

    def test_run_llm_forbidden_flag(self):
        self.assertTrue(self._result.get("llm_forbidden"))


# ─────────────────────────────────────────────────────────────────────────────
# 9. StrategyTournamentRunner
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategyTournamentRunner(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmpdir.name)
        # Write a pre-built mass tournament result
        mass = _make_mass_result(n=10)
        _atomic_write_json(self.data_dir / "mass_tournament_results.json", mass)
        self.runner = StrategyTournamentRunner(data_dir=self.data_dir)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_run_produces_tournament_file(self):
        self.runner.run(top_n=5)
        self.assertTrue((self.data_dir / "strategy_tournament.json").exists())

    def test_run_returns_dict(self):
        result = self.runner.run(top_n=5)
        self.assertIsInstance(result, dict)

    def test_tournament_has_required_keys(self):
        result = self.runner.run(top_n=5)
        for key in [
            "schema_version", "generated_at", "ranked_strategies",
            "shadow_active_strategies", "top_5", "bottom_5",
            "total_strategies", "shadow_top_n",
        ]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_schema_version_is_2(self):
        result = self.runner.run()
        self.assertEqual(result["schema_version"], "2.0")

    def test_shadow_active_count_matches_top_n(self):
        result = self.runner.run(top_n=3)
        self.assertEqual(len(result["shadow_active_strategies"]), 3)

    def test_shadow_active_strategies_are_top_ranked(self):
        result = self.runner.run(top_n=3)
        ranks = [s["rank"] for s in result["shadow_active_strategies"]]
        self.assertEqual(sorted(ranks), [1, 2, 3])

    def test_ranked_strategies_sorted_by_rank(self):
        result = self.runner.run()
        ranks = [s["rank"] for s in result["ranked_strategies"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_shadow_paper_trading_initialised(self):
        self.runner.run(top_n=5)
        spt = self.data_dir / "shadow_paper_trading.json"
        self.assertTrue(spt.exists())

    def test_shadow_paper_trading_schema(self):
        self.runner.run(top_n=5)
        spt = self.data_dir / "shadow_paper_trading.json"
        with open(spt) as fh:
            data = json.load(fh)
        self.assertIn("schema_version", data)
        self.assertIn("active_strategies", data)
        self.assertIn("daily_results", data)
        self.assertIsInstance(data["daily_results"], list)

    def test_run_missing_mass_results_raises(self):
        runner = StrategyTournamentRunner(data_dir=Path(self.tmpdir.name) / "empty")
        with self.assertRaises(SPAError):
            runner.run()

    def test_tournament_total_strategies_correct(self):
        result = self.runner.run()
        self.assertEqual(result["total_strategies"], 10)

    def test_no_overwrite_existing_shadow_trading(self):
        """If shadow_paper_trading.json already exists, don't overwrite it."""
        existing = {"my_key": "my_value", "daily_results": [{"date": "2026-01-01"}]}
        _atomic_write_json(self.data_dir / "shadow_paper_trading.json", existing)
        self.runner.run(top_n=5)
        with open(self.data_dir / "shadow_paper_trading.json") as fh:
            data = json.load(fh)
        # Should still have the original data
        self.assertEqual(data.get("my_key"), "my_value")


# ─────────────────────────────────────────────────────────────────────────────
# 10. run_shadow_day()
# ─────────────────────────────────────────────────────────────────────────────

class TestRunShadowDay(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmpdir.name)
        # Create tournament file with 3 shadow-active strategies
        lb = _make_leaderboard(5)
        tournament = {
            "schema_version": "2.0",
            "shadow_top_n": 3,
            "total_strategies": 5,
            "shadow_active_strategies": [
                {
                    "rank": i + 1,
                    "id": lb[i]["id"],
                    "sharpe": lb[i]["sharpe"],
                    "annual_return_pct": lb[i]["annual_return_pct"],
                    "max_dd_pct": lb[i]["max_dd_pct"],
                    "allocation": lb[i]["allocation"],
                }
                for i in range(3)
            ],
            "ranked_strategies": [],
        }
        _atomic_write_json(self.data_dir / "strategy_tournament.json", tournament)
        # Create initial shadow_paper_trading.json
        _atomic_write_json(self.data_dir / "shadow_paper_trading.json", {
            "schema_version": "1.0",
            "active_strategies": [],
            "daily_results": [],
        })
        self.apy_map = {
            "aave_v3": 3.8, "compound_v3": 4.5, "morpho_steakhouse": 5.2,
            "spark_susds": 4.2, "maple": 6.5, "euler_v2": 5.8, "yearn_v3": 4.7,
        }

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_shadow_day_returns_dict(self):
        result = run_shadow_day(
            self.apy_map, data_dir=self.data_dir, date_str="2026-06-22"
        )
        self.assertIsInstance(result, dict)

    def test_shadow_day_has_date(self):
        result = run_shadow_day(
            self.apy_map, data_dir=self.data_dir, date_str="2026-06-22"
        )
        self.assertEqual(result["date"], "2026-06-22")

    def test_shadow_day_has_strategies(self):
        result = run_shadow_day(
            self.apy_map, data_dir=self.data_dir, date_str="2026-06-22"
        )
        self.assertIn("strategies", result)
        self.assertIsInstance(result["strategies"], list)

    def test_shadow_day_has_best_strategy(self):
        result = run_shadow_day(
            self.apy_map, data_dir=self.data_dir, date_str="2026-06-22"
        )
        self.assertIn("best_strategy", result)

    def test_shadow_day_appends_to_file(self):
        run_shadow_day(self.apy_map, data_dir=self.data_dir, date_str="2026-06-22")
        with open(self.data_dir / "shadow_paper_trading.json") as fh:
            data = json.load(fh)
        records = data["daily_results"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["date"], "2026-06-22")

    def test_shadow_day_no_duplicate_date(self):
        """Running twice for same date should not duplicate entries."""
        run_shadow_day(self.apy_map, data_dir=self.data_dir, date_str="2026-06-22")
        run_shadow_day(self.apy_map, data_dir=self.data_dir, date_str="2026-06-22")
        with open(self.data_dir / "shadow_paper_trading.json") as fh:
            data = json.load(fh)
        dates = [r["date"] for r in data["daily_results"]]
        self.assertEqual(dates.count("2026-06-22"), 1)

    def test_shadow_day_ring_buffer_365(self):
        """Ring buffer should keep at most 365 records."""
        from spa_core.backtesting.strategy_tournament_runner import _atomic_write_json as aw
        # Pre-fill with 370 records
        records = [{"date": f"2025-01-{i:02d}", "strategies": []} for i in range(1, 31)]
        records += [{"date": f"2025-02-{i:02d}", "strategies": []} for i in range(1, 29)]
        records += [{"date": f"2025-{m:02d}-01", "strategies": []} for m in range(3, 15)]
        # Just use a large list directly
        big = [{"date": f"entry_{i}", "strategies": []} for i in range(400)]
        existing = {"schema_version": "1.0", "active_strategies": [], "daily_results": big}
        _atomic_write_json(self.data_dir / "shadow_paper_trading.json", existing)
        run_shadow_day(self.apy_map, data_dir=self.data_dir, date_str="2026-06-22")
        with open(self.data_dir / "shadow_paper_trading.json") as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data["daily_results"]), 365)

    def test_shadow_day_daily_yield_is_positive(self):
        result = run_shadow_day(
            self.apy_map, data_dir=self.data_dir, date_str="2026-06-22"
        )
        for s in result.get("strategies", []):
            # With positive APY, yield should be positive
            self.assertGreaterEqual(s["daily_yield_usd"], 0.0)

    def test_shadow_day_no_tournament_file(self):
        """If no tournament file, returns empty result without crashing."""
        empty_dir = Path(self.tmpdir.name) / "empty"
        empty_dir.mkdir()
        result = run_shadow_day({}, data_dir=empty_dir, date_str="2026-06-22")
        self.assertEqual(result["strategies"], [])


# ─────────────────────────────────────────────────────────────────────────────
# 11. Leaderboard sorting
# ─────────────────────────────────────────────────────────────────────────────

class TestLeaderboardSorting(unittest.TestCase):

    def test_top5_is_highest_sharpe(self):
        lb = _make_leaderboard(10)
        top_sharpes = [e["sharpe"] for e in lb[:5]]
        bottom_sharpes = [e["sharpe"] for e in lb[5:]]
        if top_sharpes and bottom_sharpes:
            self.assertGreater(min(top_sharpes), max(bottom_sharpes))

    def test_ranks_are_consecutive(self):
        lb = _make_leaderboard(8)
        ranks = [e["rank"] for e in lb]
        self.assertEqual(ranks, list(range(1, 9)))


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
