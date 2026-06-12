"""
tests/test_strategy_summary.py

20+ tests for spa_core.reporting.strategy_summary.
All tests use stdlib only; no external dependencies.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date

# Make sure the repo root is on sys.path regardless of how pytest is invoked.
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.reporting.strategy_summary import (
    _GO_LIVE_DATE,
    _analyze_adapters,
    _atomic_write,
    _compute_milestones,
    _days_to_go_live,
    _get_leading_strategy,
    _load_json,
    generate_summary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_strategies(
    *,
    leader_apy: float = 10.115,
    leader_sharpe: float = 1.2,
    leader_id: str = "S7",
    leader_strategy_id: str = "s7_pendle_yt",
) -> list:
    """Return a minimal list of 13 strategies matching the current tournament."""
    return [
        {
            "rank": 1,
            "id": leader_id,
            "strategy_id": leader_strategy_id,
            "name": "Pendle YT+PT Aggressive",
            "status": "leading",
            "apy_target": 10.0,
            "apy_realized": leader_apy,
            "sharpe": leader_sharpe,
        },
        {
            "rank": 2,
            "id": "S11",
            "strategy_id": "s11_hybrid",
            "name": "Hybrid Yield Maximizer",
            "status": "research",
            "apy_target": 15.6,
            "apy_realized": None,
            "sharpe": None,
        },
        *[
            {
                "rank": r,
                "id": f"S{r}",
                "status": "active",
                "apy_target": 5.0,
                "apy_realized": 5.0,
                "sharpe": 1.0,
            }
            for r in range(3, 12)
        ],
        {
            "rank": 12,
            "id": "S12",
            "strategy_id": "s12_base_layer",
            "status": "research",
            "apy_target": 6.0,
            "apy_realized": None,
            "sharpe": None,
        },
        {
            "rank": 13,
            "id": "S9",
            "status": "research",
            "apy_target": 6.0,
            "apy_realized": 5.84,
            "sharpe": 0.52,
        },
    ]


def _make_adapter_data(*, include_moonwell: bool = True) -> dict:
    """Return a minimal adapter_status structure."""
    adapters = [
        {"protocol_key": "aave-v3", "tier": "T1", "status": "active"},
        {"protocol_key": "compound-v3", "tier": "T1", "status": "active"},
        {"protocol_key": "morpho-steakhouse", "tier": "T1", "status": "active"},
        {"protocol_key": "yearn-v3", "tier": "T2", "status": "active"},
        {"protocol_key": "euler-v2", "tier": "T2", "status": "active"},
        {"protocol_key": "maple", "tier": "T2", "status": "active"},
        {"protocol_key": "pendle-pt", "tier": "T2", "status": "active"},
        {"protocol_key": "sky-susds", "tier": "T2", "status": "active"},
        {"protocol_key": "aave-v3-arbitrum", "tier": "T1", "status": "active"},
        {"protocol_key": "spark-susds", "tier": "T1", "status": "research"},
        {"protocol_key": "fluid-fusdc", "tier": "T2", "status": "research"},
    ]
    top_level = {
        "generated_at": "2026-06-12T00:00:00Z",
        "schema_version": 1,
        "adapters": adapters,
        # duplicates — should be skipped
        "morpho_steakhouse": {"protocol_key": "morpho-steakhouse", "apy": 6.5},
        "compound_v3": {"protocol_key": "compound-v3", "apy": 4.8},
        "base_gas_monitor": {"status": "OK"},  # not an adapter
        # unique extra adapters
        "sfrax": {"adapter_id": "sfrax", "tier": "T2", "apy": 6.0, "status": "active"},
        "susde": {"adapter_id": "susde", "tier": "T3", "apy": 12.0, "status": "active"},
        "aave_v3_base": {"protocol_id": "aave-v3-base", "tier": "T2", "apy_pct": 4.5, "status": "active"},
        "morpho_blue_base": {"protocol_id": "morpho-blue-base", "tier": "T2", "apy_pct": 6.2, "status": "active"},
        "extra_finance_base": {"adapter_id": "extra_finance_base", "tier": "T3", "apy_pct": 8.0, "status": "monitoring"},
    }
    if include_moonwell:
        top_level["moonwell_base"] = {
            "adapter_id": "moonwell_base",
            "tier": "T2",
            "apy_pct": 4.1,
            "status": "suspended",
        }
    return top_level


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestLoadJson(unittest.TestCase):
    """Tests for _load_json helper."""

    def test_load_valid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump({"key": "value"}, fh)
            path = fh.name
        try:
            result = _load_json(path)
            self.assertEqual(result, {"key": "value"})
        finally:
            os.unlink(path)

    def test_load_missing_file_returns_empty_dict(self):
        result = _load_json("/nonexistent/path/to/file.json")
        self.assertEqual(result, {})

    def test_load_corrupt_json_returns_empty_dict(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write("{not valid json")
            path = fh.name
        try:
            result = _load_json(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)


class TestAtomicWrite(unittest.TestCase):
    """Tests for _atomic_write helper."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_file_is_created(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, {"ok": True})
        self.assertTrue(os.path.exists(path))

    def test_file_content_is_valid_json(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, {"val": 42})
        with open(path) as fh:
            data = json.load(fh)
        self.assertEqual(data["val"], 42)

    def test_no_tmp_file_left_after_write(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, {"x": 1})
        leftovers = [f for f in os.listdir(self.tmpdir) if f.startswith(".tmp_")]
        self.assertEqual(leftovers, [])

    def test_overwrites_existing_file_atomically(self):
        path = os.path.join(self.tmpdir, "out.json")
        _atomic_write(path, {"v": 1})
        _atomic_write(path, {"v": 2})
        with open(path) as fh:
            data = json.load(fh)
        self.assertEqual(data["v"], 2)


class TestGetLeadingStrategy(unittest.TestCase):
    """Tests for _get_leading_strategy."""

    def test_returns_rank1_entry(self):
        strategies = _make_strategies()
        result = _get_leading_strategy(strategies)
        self.assertEqual(result["id"], "s7_pendle_yt")

    def test_apy_is_realized_when_present(self):
        strategies = _make_strategies(leader_apy=10.115)
        result = _get_leading_strategy(strategies)
        self.assertAlmostEqual(result["apy"], 10.115)

    def test_apy_falls_back_to_target_when_realized_none(self):
        strategies = [
            {"rank": 1, "id": "S7", "apy_target": 10.0, "apy_realized": None, "sharpe": None}
        ]
        result = _get_leading_strategy(strategies)
        self.assertAlmostEqual(result["apy"], 10.0)

    def test_sharpe_is_captured(self):
        strategies = _make_strategies(leader_sharpe=1.2)
        result = _get_leading_strategy(strategies)
        self.assertAlmostEqual(result["sharpe"], 1.2)

    def test_empty_list_returns_empty_dict(self):
        self.assertEqual(_get_leading_strategy([]), {})

    def test_no_rank1_returns_empty_dict(self):
        strategies = [{"rank": 2, "id": "S5", "apy_realized": 8.5, "sharpe": 1.0}]
        self.assertEqual(_get_leading_strategy(strategies), {})

    def test_id_normalised_to_lowercase(self):
        strategies = [
            {
                "rank": 1,
                "id": "S7",
                "strategy_id": "S7_Pendle_YT",
                "apy_realized": 10.115,
                "sharpe": 1.2,
            }
        ]
        result = _get_leading_strategy(strategies)
        self.assertEqual(result["id"], "s7_pendle_yt")

    def test_id_falls_back_to_id_field_when_strategy_id_missing(self):
        strategies = [
            {"rank": 1, "id": "S7", "apy_realized": 10.0, "sharpe": 1.0}
        ]
        result = _get_leading_strategy(strategies)
        self.assertEqual(result["id"], "s7")


class TestAnalyzeAdapters(unittest.TestCase):
    """Tests for _analyze_adapters."""

    def test_total_count_includes_list_and_unique_top_level(self):
        data = _make_adapter_data(include_moonwell=True)
        total, _, _ = _analyze_adapters(data)
        # 11 in adapters list + 6 unique top-level (sfrax, susde, aave_v3_base,
        # morpho_blue_base, extra_finance_base, moonwell_base) = 17
        self.assertGreater(total, 11)

    def test_moonwell_is_suspended(self):
        data = _make_adapter_data(include_moonwell=True)
        _, _, suspended = _analyze_adapters(data)
        self.assertIn("moonwell_base", suspended)

    def test_suspended_count_without_moonwell_is_zero(self):
        data = _make_adapter_data(include_moonwell=False)
        _, _, suspended = _analyze_adapters(data)
        self.assertEqual(suspended, [])

    def test_active_equals_total_minus_suspended(self):
        data = _make_adapter_data(include_moonwell=True)
        total, active, suspended = _analyze_adapters(data)
        self.assertEqual(active, total - len(suspended))

    def test_duplicate_top_level_entries_not_double_counted(self):
        """morpho_steakhouse / compound_v3 are duplicates; they must not inflate count."""
        data = _make_adapter_data(include_moonwell=False)
        total_with_dups, _, _ = _analyze_adapters(data)
        # Remove the duplicates; count should be the same (duplicates are skipped)
        data_no_dups = {k: v for k, v in data.items()
                        if k not in ("morpho_steakhouse", "compound_v3")}
        total_no_dups, _, _ = _analyze_adapters(data_no_dups)
        self.assertEqual(total_with_dups, total_no_dups)

    def test_empty_adapter_data_returns_zeroes(self):
        total, active, suspended = _analyze_adapters({})
        self.assertEqual(total, 0)
        self.assertEqual(active, 0)
        self.assertEqual(suspended, [])

    def test_base_gas_monitor_not_counted(self):
        """base_gas_monitor is metadata, not an adapter."""
        data = {"adapters": [], "base_gas_monitor": {"status": "OK"}}
        total, _, _ = _analyze_adapters(data)
        self.assertEqual(total, 0)


class TestComputeMilestones(unittest.TestCase):
    """Tests for _compute_milestones."""

    def test_all_three_milestones_with_real_tournament(self):
        strategies = _make_strategies()  # S7=10.115 realized, S11 target=15.6
        milestones = _compute_milestones(strategies)
        self.assertIn("L1", milestones)
        self.assertIn("L2", milestones)
        self.assertIn("L3", milestones)

    def test_l1_only_when_max_realized_under_10(self):
        strategies = [
            {"rank": 1, "id": "S0", "apy_target": 5.0, "apy_realized": 5.0},
        ]
        milestones = _compute_milestones(strategies)
        self.assertIn("L1", milestones)
        self.assertNotIn("L2", milestones)
        self.assertNotIn("L3", milestones)

    def test_no_milestones_when_all_apy_below_5(self):
        strategies = [
            {"rank": 1, "id": "S0", "apy_target": 3.5, "apy_realized": 3.2},
        ]
        milestones = _compute_milestones(strategies)
        self.assertEqual(milestones, [])

    def test_empty_strategies_gives_no_milestones(self):
        self.assertEqual(_compute_milestones([]), [])

    def test_l3_triggered_by_target_not_just_realized(self):
        """S11 has target=15.6 but no realized APY — L3 should still appear."""
        strategies = [
            {"rank": 1, "id": "S7", "apy_target": 10.0, "apy_realized": 10.1},
            {"rank": 2, "id": "S11", "apy_target": 15.6, "apy_realized": None},
        ]
        milestones = _compute_milestones(strategies)
        self.assertIn("L3", milestones)

    def test_l2_requires_realized_not_just_target(self):
        """L2 threshold uses realized pool only."""
        strategies = [
            {"rank": 1, "id": "S0", "apy_target": 12.0, "apy_realized": 4.0},
        ]
        milestones = _compute_milestones(strategies)
        self.assertNotIn("L2", milestones)

    def test_milestones_ordered_l1_l2_l3(self):
        strategies = _make_strategies()
        milestones = _compute_milestones(strategies)
        self.assertEqual(milestones, sorted(milestones))


class TestDaysToGoLive(unittest.TestCase):
    """Tests for _days_to_go_live."""

    def test_50_days_from_2026_06_12(self):
        self.assertEqual(_days_to_go_live(date(2026, 6, 12)), 50)

    def test_zero_on_go_live_day(self):
        self.assertEqual(_days_to_go_live(_GO_LIVE_DATE), 0)

    def test_zero_after_go_live_day(self):
        self.assertEqual(_days_to_go_live(date(2026, 9, 1)), 0)

    def test_one_day_before_go_live(self):
        from datetime import timedelta
        self.assertEqual(_days_to_go_live(_GO_LIVE_DATE - timedelta(days=1)), 1)


class TestGenerateSummary(unittest.TestCase):
    """Integration tests for generate_summary()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Write ranking and adapter files
        _write_json(
            os.path.join(self.tmpdir, "tournament_ranking.json"),
            {"strategies": _make_strategies()},
        )
        _write_json(
            os.path.join(self.tmpdir, "adapter_status.json"),
            _make_adapter_data(include_moonwell=True),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- required keys ----

    def test_output_has_all_required_keys(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        required = {
            "generated", "leading_strategy", "tournament_count",
            "active_adapters", "suspended_adapters", "adapter_registry_count",
            "milestones_reached", "days_to_go_live",
        }
        self.assertTrue(required.issubset(result.keys()))

    # ---- leading strategy ----

    def test_leading_strategy_id_is_s7(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(result["leading_strategy"]["id"], "s7_pendle_yt")

    def test_leading_strategy_apy(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertAlmostEqual(result["leading_strategy"]["apy"], 10.115)

    def test_leading_strategy_sharpe(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertAlmostEqual(result["leading_strategy"]["sharpe"], 1.2)

    # ---- tournament count ----

    def test_tournament_count_is_13(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(result["tournament_count"], 13)

    def test_tournament_count_empty_strategies(self):
        _write_json(
            os.path.join(self.tmpdir, "tournament_ranking.json"),
            {"strategies": []},
        )
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(result["tournament_count"], 0)

    # ---- adapter counts ----

    def test_suspended_adapters_contains_moonwell(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertIn("moonwell_base", result["suspended_adapters"])

    def test_active_adapters_less_than_registry(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertLess(result["active_adapters"], result["adapter_registry_count"])

    def test_active_plus_suspended_equals_registry(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(
            result["active_adapters"] + len(result["suspended_adapters"]),
            result["adapter_registry_count"],
        )

    # ---- milestones ----

    def test_milestones_include_l1_l2_l3(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertIn("L1", result["milestones_reached"])
        self.assertIn("L2", result["milestones_reached"])
        self.assertIn("L3", result["milestones_reached"])

    # ---- days to go-live ----

    def test_days_to_go_live_is_50_on_2026_06_12(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(result["days_to_go_live"], 50)

    # ---- generated date ----

    def test_generated_field_is_today(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        today = date(2026, 6, 12)
        result = generate_summary(data_dir=self.tmpdir, output_path=out, today=today)
        self.assertEqual(result["generated"], "2026-06-12")

    # ---- output file ----

    def test_output_file_is_valid_json(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        generate_summary(data_dir=self.tmpdir, output_path=out,
                         today=date(2026, 6, 12))
        with open(out) as fh:
            loaded = json.load(fh)
        self.assertIsInstance(loaded, dict)

    def test_output_file_matches_returned_dict(self):
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        with open(out) as fh:
            on_disk = json.load(fh)
        self.assertEqual(result, on_disk)

    # ---- missing input files ----

    def test_missing_ranking_file_gives_zero_tournament_count(self):
        os.unlink(os.path.join(self.tmpdir, "tournament_ranking.json"))
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(result["tournament_count"], 0)

    def test_missing_adapter_file_gives_zero_adapters(self):
        os.unlink(os.path.join(self.tmpdir, "adapter_status.json"))
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(result["adapter_registry_count"], 0)
        self.assertEqual(result["active_adapters"], 0)
        self.assertEqual(result["suspended_adapters"], [])

    def test_both_files_missing_still_writes_valid_summary(self):
        os.unlink(os.path.join(self.tmpdir, "tournament_ranking.json"))
        os.unlink(os.path.join(self.tmpdir, "adapter_status.json"))
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertIsInstance(result, dict)
        self.assertIn("generated", result)

    def test_corrupt_ranking_json_gives_zero_count(self):
        with open(os.path.join(self.tmpdir, "tournament_ranking.json"), "w") as fh:
            fh.write("{bad json")
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(result["tournament_count"], 0)

    def test_corrupt_adapter_json_gives_zero_adapters(self):
        with open(os.path.join(self.tmpdir, "adapter_status.json"), "w") as fh:
            fh.write("NOT JSON")
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        self.assertEqual(result["adapter_registry_count"], 0)

    # ---- custom output_path ----

    def test_custom_output_path(self):
        out = os.path.join(self.tmpdir, "subdir", "custom_summary.json")
        generate_summary(data_dir=self.tmpdir, output_path=out,
                         today=date(2026, 6, 12))
        self.assertTrue(os.path.exists(out))

    # ---- strategies without any realized APY ----

    def test_all_null_realized_apys_no_l1_l2(self):
        strategies = [
            {"rank": 1, "id": "S11", "apy_target": 15.6, "apy_realized": None},
        ]
        _write_json(
            os.path.join(self.tmpdir, "tournament_ranking.json"),
            {"strategies": strategies},
        )
        out = os.path.join(self.tmpdir, "strategy_summary.json")
        result = generate_summary(data_dir=self.tmpdir, output_path=out,
                                  today=date(2026, 6, 12))
        # No realized APY → L1 / L2 cannot be triggered
        self.assertNotIn("L1", result["milestones_reached"])
        self.assertNotIn("L2", result["milestones_reached"])
        # But L3 target is 15.6 ≥ 15 → L3 appears
        self.assertIn("L3", result["milestones_reached"])

    # ---- S7 rank-1 specifics ----

    def test_s7_is_rank1_in_ranking_file(self):
        """Confirm tournament_ranking.json was updated correctly (regression guard)."""
        import os as _os
        ranking_path = _os.path.join(
            _os.path.dirname(__file__), "..", "data", "tournament_ranking.json"
        )
        if not _os.path.exists(ranking_path):
            self.skipTest("tournament_ranking.json not found")
        with open(ranking_path) as fh:
            data = json.load(fh)
        rank1 = next(
            (s for s in data.get("strategies", []) if s.get("rank") == 1), None
        )
        self.assertIsNotNone(rank1)
        self.assertEqual(rank1["id"], "S7")
        self.assertEqual(rank1["status"], "leading")
        self.assertAlmostEqual(rank1["apy_realized"], 10.115)
        self.assertAlmostEqual(rank1["sharpe"], 1.2)

    def test_s11_is_rank2_in_ranking_file(self):
        """Confirm S11 was promoted to rank 2."""
        import os as _os
        ranking_path = _os.path.join(
            _os.path.dirname(__file__), "..", "data", "tournament_ranking.json"
        )
        if not _os.path.exists(ranking_path):
            self.skipTest("tournament_ranking.json not found")
        with open(ranking_path) as fh:
            data = json.load(fh)
        rank2 = next(
            (s for s in data.get("strategies", []) if s.get("rank") == 2), None
        )
        self.assertIsNotNone(rank2)
        self.assertEqual(rank2["id"], "S11")

    def test_s12_is_rank12_in_ranking_file(self):
        """Confirm S12 Phase 1 ETH fallback is at rank 12."""
        import os as _os
        ranking_path = _os.path.join(
            _os.path.dirname(__file__), "..", "data", "tournament_ranking.json"
        )
        if not _os.path.exists(ranking_path):
            self.skipTest("tournament_ranking.json not found")
        with open(ranking_path) as fh:
            data = json.load(fh)
        rank12 = next(
            (s for s in data.get("strategies", []) if s.get("rank") == 12), None
        )
        self.assertIsNotNone(rank12)
        self.assertEqual(rank12["id"], "S12")
        self.assertIn("Phase 1", rank12.get("description", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
