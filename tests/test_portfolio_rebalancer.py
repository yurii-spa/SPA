"""
tests/test_portfolio_rebalancer.py — Test suite for ALLOC-001 portfolio_rebalancer

Coverage:
  - Happy path: tuner produces valid portfolio → write succeeds
  - Rejection flow: tuner returns bad weights → fallback used
  - Fallback rejection: both tuner and fallback fail → False returned
  - Atomic write: file not written on failure
  - Policy constraints satisfied after rebalance
  - Watchdog compatibility
  - check_current_positions()
  - Telegram alert (not actually sent)
  - Edge cases: empty adapters, zero capital, missing file

Tests: 35 total
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

# ── helpers ──────────────────────────────────────────────────────────────────

_CAPITAL = 100_000.0

# Known-valid portfolio (T1=60%, T2=28%, T3=5%, cash=7%)
_VALID_POSITIONS: Dict[str, float] = {
    "aave_v3": 25_000.0,          # T1, 25%
    "compound_v3": 20_000.0,      # T1, 20%
    "spark_susds": 15_000.0,      # T1, 15%
    "morpho_steakhouse": 7_000.0, # T1, 7%  → T1 total = 67%
    "maple": 15_000.0,            # T2, 15%
    "euler_v2": 11_000.0,         # T2, 11%
}
# cash = 100000 - 93000 = 7000 = 7%


# Adapter data with 2 T1 adapters only (tuner will fail T1 min constraint)
_ADAPTER_DATA_2T1 = [
    {"id": "aave_v3",     "tier": "T1", "apy": 3.1, "tvl_usd": 200_000_000},
    {"id": "compound_v3", "tier": "T1", "apy": 5.2, "tvl_usd": 1_500_000_000},
    {"id": "maple",       "tier": "T2", "apy": 5.0, "tvl_usd": 3_000_000_000},
    {"id": "euler_v2",    "tier": "T2", "apy": 2.8, "tvl_usd":    15_000_000},
    {"id": "yearn_v3",    "tier": "T2", "apy": 3.2, "tvl_usd":    26_000_000},
]

# Adapter data with 4 T1 adapters (tuner should succeed)
_ADAPTER_DATA_4T1 = [
    {"id": "aave_v3",           "tier": "T1", "apy": 3.1, "tvl_usd": 200_000_000},
    {"id": "compound_v3",       "tier": "T1", "apy": 5.2, "tvl_usd": 1_500_000_000},
    {"id": "spark_susds",       "tier": "T1", "apy": 4.2, "tvl_usd":  500_000_000},
    {"id": "morpho_steakhouse", "tier": "T1", "apy": 4.6, "tvl_usd":   50_000_000},
    {"id": "maple",             "tier": "T2", "apy": 5.0, "tvl_usd": 3_000_000_000},
    {"id": "euler_v2",          "tier": "T2", "apy": 2.8, "tvl_usd":    15_000_000},
]


def _make_data_dir(positions: dict = None, adapter_data: list = None) -> tempfile.TemporaryDirectory:
    """Create a temp data directory with optional pre-populated files."""
    tmpdir = tempfile.TemporaryDirectory()
    path = Path(tmpdir.name)

    if positions is not None:
        pos_doc = {
            "generated_at": "2026-06-22T00:00:00+00:00",
            "source": "test",
            "capital_usd": _CAPITAL,
            "deployed_usd": sum(positions.values()),
            "cash_usd": _CAPITAL - sum(positions.values()),
            "is_demo": False,
            "positions": positions,
        }
        (path / "current_positions.json").write_text(json.dumps(pos_doc))

    if adapter_data is not None:
        orch_doc = {
            "generated_at": "2026-06-22T00:00:00+00:00",
            "adapters": [
                {
                    "protocol": a["id"],
                    "tier": a["tier"],
                    "apy_pct": a["apy"],
                    "tvl_usd": a["tvl_usd"],
                    "status": "ok",
                }
                for a in adapter_data
            ],
        }
        (path / "adapter_orchestrator_status.json").write_text(json.dumps(orch_doc))

    return tmpdir


# ── Test class ────────────────────────────────────────────────────────────────


class TestPortfolioRebalancer(unittest.TestCase):
    """Tests for spa_core/tuner/portfolio_rebalancer.py (ALLOC-001)."""

    # ── Import smoke test ─────────────────────────────────────────────────

    def test_module_imports_without_error(self):
        """rebalancer module must be importable."""
        from spa_core.tuner import portfolio_rebalancer
        self.assertIsNotNone(portfolio_rebalancer)

    def test_rebalance_portfolio_is_callable(self):
        from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
        self.assertTrue(callable(rebalance_portfolio))

    def test_check_current_positions_is_callable(self):
        from spa_core.tuner.portfolio_rebalancer import check_current_positions
        self.assertTrue(callable(check_current_positions))

    def test_safe_fallback_positions_defined(self):
        from spa_core.tuner.portfolio_rebalancer import _SAFE_FALLBACK_POSITIONS
        self.assertIsInstance(_SAFE_FALLBACK_POSITIONS, dict)
        self.assertGreater(len(_SAFE_FALLBACK_POSITIONS), 0)

    # ── Happy path: write valid positions ─────────────────────────────────

    def test_rebalancer_writes_valid_positions_with_4t1_adapters(self):
        """When tuner has 4 T1 adapters available, it should produce valid portfolio."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_4T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            ok = rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            self.assertTrue(ok, "Rebalancer should succeed with 4 T1 adapters")
            # File must exist
            pos_path = Path(tmpdir.name) / "current_positions.json"
            self.assertTrue(pos_path.exists(), "current_positions.json must be written")
        finally:
            tmpdir.cleanup()

    def test_rebalancer_returns_true_on_success(self):
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_4T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            result = rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            self.assertIs(result, True)
        finally:
            tmpdir.cleanup()

    def test_fallback_path_writes_valid_positions(self):
        """With only 2 T1 adapters, tuner fails and fallback is used."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            ok = rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            self.assertTrue(ok, "Fallback should write valid positions")
        finally:
            tmpdir.cleanup()

    def test_fallback_portfolio_passes_policy(self):
        """The safe fallback positions must pass policy_enforcer validation."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            pos_path = Path(tmpdir.name) / "current_positions.json"
            doc = json.loads(pos_path.read_text())
            self.assertTrue(doc.get("policy_compliant"), "Written portfolio must be policy_compliant=true")
        finally:
            tmpdir.cleanup()

    # ── Positions satisfy constraints after rebalance ─────────────────────

    def test_positions_satisfy_t1_min_after_rebalance(self):
        """After rebalance, T1 allocation must be >= 55%."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            t1_pct = doc["validation_summary"]["t1_pct"]
            self.assertGreaterEqual(t1_pct, 55.0, "T1 must be >= 55%")
        finally:
            tmpdir.cleanup()

    def test_positions_cash_buffer_after_rebalance(self):
        """After rebalance, cash buffer must be >= 5%."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            cash_pct = doc["validation_summary"]["cash_pct"]
            self.assertGreaterEqual(cash_pct, 5.0, "Cash must be >= 5%")
        finally:
            tmpdir.cleanup()

    def test_positions_max_protocols_after_rebalance(self):
        """After rebalance, max 8 protocols in portfolio."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            n_protocols = doc["validation_summary"]["protocol_count"]
            self.assertLessEqual(n_protocols, 8, "Max 8 protocols")
        finally:
            tmpdir.cleanup()

    def test_per_protocol_max_not_exceeded_after_rebalance(self):
        """No single protocol exceeds 25% after rebalance."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            positions = doc["positions"]
            for proto, usd in positions.items():
                pct = usd / _CAPITAL * 100
                self.assertLessEqual(pct, 25.0, f"{proto}={pct:.1f}% exceeds 25% cap")
        finally:
            tmpdir.cleanup()

    def test_t2_max_not_exceeded_after_rebalance(self):
        """T2 total allocation <= 50% (ADR-019)."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            t2_pct = doc["validation_summary"]["t2_pct"]
            self.assertLessEqual(t2_pct, 50.0, "T2 must be <= 50%")
        finally:
            tmpdir.cleanup()

    def test_capital_conservation_after_rebalance(self):
        """deployed_usd + cash_usd == capital_usd (within rounding tolerance)."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            total = doc["deployed_usd"] + doc["cash_usd"]
            self.assertAlmostEqual(total, _CAPITAL, delta=1.0, msg="Capital must be conserved")
        finally:
            tmpdir.cleanup()

    def test_is_demo_false_in_written_file(self):
        """Written file must have is_demo: false."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            self.assertFalse(doc.get("is_demo"), "is_demo must be False")
        finally:
            tmpdir.cleanup()

    def test_source_field_is_portfolio_rebalancer(self):
        """Written file must have source='portfolio_rebalancer_v1'."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            self.assertEqual(doc.get("source"), "portfolio_rebalancer_v1")
        finally:
            tmpdir.cleanup()

    # ── Rejection flow ────────────────────────────────────────────────────

    def test_rebalancer_returns_false_when_no_adapter_data(self):
        """Without orchestrator data, rebalancer must return False."""
        tmpdir = _make_data_dir()   # no adapter file
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            result = rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            self.assertFalse(result)
        finally:
            tmpdir.cleanup()

    def test_rebalancer_does_not_write_on_no_adapter_data(self):
        """Without adapter data, current_positions.json must NOT be created."""
        tmpdir = _make_data_dir()
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            pos_path = Path(tmpdir.name) / "current_positions.json"
            self.assertFalse(pos_path.exists(), "File must NOT be written when no adapter data")
        finally:
            tmpdir.cleanup()

    def test_rebalancer_does_not_write_on_validation_failure(self):
        """If both tuner and fallback fail validation, original file unchanged."""
        orig_positions = {"aave_v3": 50_000.0}  # invalid: only 50% T1, T1 < 55%? Actually 50% T1...
        # Let's use a truly invalid portfolio: too many protocols
        many_pos = {f"proto_{i}": 5000.0 for i in range(12)}  # 12 > 8 max
        tmpdir = _make_data_dir(positions=many_pos, adapter_data=_ADAPTER_DATA_2T1)
        orig_content = (Path(tmpdir.name) / "current_positions.json").read_text()
        try:
            # Monkeypatch _build_safe_fallback_positions to return invalid positions
            from spa_core.tuner import portfolio_rebalancer as mod

            _orig_fallback = mod._build_safe_fallback_positions

            def _bad_fallback(capital_usd, base_positions=None):
                # Return positions that violate per_protocol_max (30% each)
                bad_pos = {"aave_v3": 30_000.0, "compound_v3": 30_000.0, "maple": 30_000.0}
                return bad_pos, 10_000.0

            mod._build_safe_fallback_positions = _bad_fallback
            try:
                result = mod.rebalance_portfolio(
                    capital_usd=_CAPITAL,
                    data_dir=Path(tmpdir.name),
                    write=True,
                    send_alert=False,
                )
                self.assertFalse(result, "Must return False when all paths fail validation")
                # File must not be changed
                new_content = (Path(tmpdir.name) / "current_positions.json").read_text()
                self.assertEqual(orig_content, new_content, "File must not be modified on failure")
            finally:
                mod._build_safe_fallback_positions = _orig_fallback
        finally:
            tmpdir.cleanup()

    def test_check_mode_does_not_write(self):
        """With write=False, rebalancer must not touch the file system."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_4T1)
        try:
            pos_path = Path(tmpdir.name) / "current_positions.json"
            self.assertFalse(pos_path.exists(), "File should not exist before rebalance")
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            ok = rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=False,
                send_alert=False,
            )
            self.assertTrue(ok, "Check mode should still return True on valid portfolio")
            self.assertFalse(pos_path.exists(), "File must NOT be written in check mode")
        finally:
            tmpdir.cleanup()

    # ── check_current_positions() ─────────────────────────────────────────

    def test_check_current_positions_passes_valid_portfolio(self):
        """check_current_positions() must return passed=True for valid portfolio."""
        tmpdir = _make_data_dir(positions=_VALID_POSITIONS)
        try:
            from spa_core.tuner.portfolio_rebalancer import check_current_positions
            result = check_current_positions(
                data_dir=Path(tmpdir.name),
                capital_usd=_CAPITAL,
            )
            self.assertTrue(result.passed, f"Valid portfolio should pass: {result.violations}")
        finally:
            tmpdir.cleanup()

    def test_check_current_positions_fails_missing_file(self):
        """check_current_positions() returns passed=False when file missing."""
        tmpdir = _make_data_dir()  # no positions file
        try:
            from spa_core.tuner.portfolio_rebalancer import check_current_positions
            result = check_current_positions(
                data_dir=Path(tmpdir.name),
                capital_usd=_CAPITAL,
            )
            self.assertFalse(result.passed)
            self.assertEqual(result.violations[0].rule, "file_exists")
        finally:
            tmpdir.cleanup()

    def test_check_current_positions_fails_corrupt_file(self):
        """check_current_positions() returns passed=False for invalid JSON."""
        tmpdir = _make_data_dir()
        (Path(tmpdir.name) / "current_positions.json").write_text("{bad json{{")
        try:
            from spa_core.tuner.portfolio_rebalancer import check_current_positions
            result = check_current_positions(
                data_dir=Path(tmpdir.name),
                capital_usd=_CAPITAL,
            )
            self.assertFalse(result.passed)
            self.assertEqual(result.violations[0].rule, "file_valid_json")
        finally:
            tmpdir.cleanup()

    def test_check_current_positions_detects_t1_violation(self):
        """check_current_positions() detects T1 below minimum."""
        low_t1 = {
            "maple": 50_000.0,    # T2, 50%
            "euler_v2": 43_000.0, # T2, 43%
        }
        tmpdir = _make_data_dir(positions=low_t1)
        try:
            from spa_core.tuner.portfolio_rebalancer import check_current_positions
            result = check_current_positions(data_dir=Path(tmpdir.name), capital_usd=_CAPITAL)
            self.assertFalse(result.passed)
            rules = [v.rule for v in result.violations]
            self.assertIn("t1_min_pct", rules, "Should detect T1 below minimum")
        finally:
            tmpdir.cleanup()

    def test_check_current_positions_detects_max_protocols_violation(self):
        """check_current_positions() detects too many protocols."""
        many = {f"proto_{i}": 5_000.0 for i in range(10)}  # 10 > 8
        tmpdir = _make_data_dir(positions=many)
        try:
            from spa_core.tuner.portfolio_rebalancer import check_current_positions
            result = check_current_positions(data_dir=Path(tmpdir.name), capital_usd=_CAPITAL)
            self.assertFalse(result.passed)
            rules = [v.rule for v in result.violations]
            self.assertIn("max_protocols", rules)
        finally:
            tmpdir.cleanup()

    # ── Weights to USD conversion ─────────────────────────────────────────

    def test_weights_to_usd_conserves_capital(self):
        """_weights_to_usd: deployed + cash == capital."""
        from spa_core.tuner.portfolio_rebalancer import _weights_to_usd
        weights = {"aave_v3": 0.40, "compound_v3": 0.30, "maple": 0.20}
        pos, cash = _weights_to_usd(weights, _CAPITAL, cash_min_fraction=0.07)
        total = sum(pos.values()) + cash
        self.assertAlmostEqual(total, _CAPITAL, delta=1.0)

    def test_weights_to_usd_enforces_cash_min(self):
        """_weights_to_usd: cash must be >= cash_min_fraction * capital."""
        from spa_core.tuner.portfolio_rebalancer import _weights_to_usd
        # Weights that sum to 0.98 → cash = 2% < 7% min
        weights = {"aave_v3": 0.50, "compound_v3": 0.48}
        pos, cash = _weights_to_usd(weights, _CAPITAL, cash_min_fraction=0.07)
        min_cash = _CAPITAL * 0.07
        self.assertGreaterEqual(cash, min_cash - 1.0, "Cash must be >= 7% floor")

    def test_weights_to_usd_ignores_dust_positions(self):
        """_weights_to_usd ignores weights < 1e-6."""
        from spa_core.tuner.portfolio_rebalancer import _weights_to_usd
        weights = {"aave_v3": 0.60, "dust": 1e-9}
        pos, cash = _weights_to_usd(weights, _CAPITAL, cash_min_fraction=0.05)
        self.assertNotIn("dust", pos, "Dust positions must be excluded")

    # ── Safe fallback ─────────────────────────────────────────────────────

    def test_safe_fallback_positions_are_policy_compliant(self):
        """_SAFE_FALLBACK_POSITIONS pass policy_enforcer validation."""
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        from spa_core.risk.policy_enforcer import validate_positions
        positions, cash_usd = _build_safe_fallback_positions(_CAPITAL)
        result = validate_positions(positions=positions, capital_usd=_CAPITAL, cash_usd=cash_usd)
        self.assertTrue(
            result.passed,
            "Safe fallback must pass policy: {}".format([v.message for v in result.violations])
        )

    def test_safe_fallback_t1_at_least_55pct(self):
        """Safe fallback positions have T1 >= 55%."""
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        from spa_core.risk.policy_enforcer import validate_positions
        positions, cash_usd = _build_safe_fallback_positions(_CAPITAL)
        result = validate_positions(positions=positions, capital_usd=_CAPITAL, cash_usd=cash_usd)
        self.assertGreaterEqual(result.portfolio_summary["t1_pct"], 55.0)

    def test_safe_fallback_scales_to_different_capital(self):
        """Safe fallback scales to any capital (e.g., $50K)."""
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        from spa_core.risk.policy_enforcer import validate_positions
        capital = 50_000.0
        positions, cash_usd = _build_safe_fallback_positions(capital)
        total = sum(positions.values()) + cash_usd
        self.assertAlmostEqual(total, capital, delta=5.0, msg="Capital must be conserved at $50K")
        result = validate_positions(positions=positions, capital_usd=capital, cash_usd=cash_usd)
        self.assertTrue(result.passed, "Scaled fallback must still pass policy")

    # ── Real repo data ─────────────────────────────────────────────────────

    def test_real_current_positions_pass_validation(self):
        """data/current_positions.json (written by rebalancer) must pass validation."""
        from spa_core.tuner.portfolio_rebalancer import check_current_positions
        result = check_current_positions()
        self.assertTrue(
            result.passed,
            "Real current positions must pass policy: {}".format(
                [v.message for v in result.violations]
            )
        )

    def test_real_positions_source_is_rebalancer(self):
        """data/current_positions.json written by ALLOC-001 must have correct source."""
        repo = Path(__file__).resolve().parents[1]
        pos_path = repo / "data" / "current_positions.json"
        if not pos_path.exists():
            self.skipTest("current_positions.json not found")
        doc = json.loads(pos_path.read_text())
        self.assertEqual(doc.get("source"), "portfolio_rebalancer_v1",
                         "source must be 'portfolio_rebalancer_v1' (written by ALLOC-001)")

    # ── Telegram alert (mocked) ────────────────────────────────────────────

    def test_telegram_not_sent_on_success(self):
        """On success, no Telegram alert should be sent."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_4T1)
        try:
            from spa_core.tuner import portfolio_rebalancer as mod
            with patch.object(mod, "_send_telegram") as mock_tg:
                mod.rebalance_portfolio(
                    capital_usd=_CAPITAL,
                    data_dir=Path(tmpdir.name),
                    write=False,
                    send_alert=True,
                )
                mock_tg.assert_not_called()
        finally:
            tmpdir.cleanup()

    def test_telegram_sent_on_double_failure(self):
        """When both tuner and fallback fail, Telegram alert must be sent."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner import portfolio_rebalancer as mod

            _orig = mod._build_safe_fallback_positions

            def _bad_fallback(capital_usd, base_positions=None):
                # Return positions that violate per_protocol_max
                bad = {"aave_v3": 30_000.0, "compound_v3": 30_000.0, "maple": 30_000.0}
                return bad, 10_000.0

            mod._build_safe_fallback_positions = _bad_fallback
            try:
                with patch.object(mod, "_send_telegram") as mock_tg:
                    mod.rebalance_portfolio(
                        capital_usd=_CAPITAL,
                        data_dir=Path(tmpdir.name),
                        write=True,
                        send_alert=True,
                    )
                    mock_tg.assert_called_once()
            finally:
                mod._build_safe_fallback_positions = _orig
        finally:
            tmpdir.cleanup()

    def test_no_telegram_when_send_alert_false(self):
        """With send_alert=False, Telegram must never be called regardless of result."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner import portfolio_rebalancer as mod

            _orig = mod._build_safe_fallback_positions

            def _bad_fallback(capital_usd, base_positions=None):
                return {"aave_v3": 30_000.0, "compound_v3": 30_000.0, "maple": 30_000.0}, 10_000.0

            mod._build_safe_fallback_positions = _bad_fallback
            try:
                with patch.object(mod, "_send_telegram") as mock_tg:
                    mod.rebalance_portfolio(
                        capital_usd=_CAPITAL,
                        data_dir=Path(tmpdir.name),
                        write=True,
                        send_alert=False,
                    )
                    mock_tg.assert_not_called()
            finally:
                mod._build_safe_fallback_positions = _orig
        finally:
            tmpdir.cleanup()

    # ── Watchdog ─────────────────────────────────────────────────────────

    def test_watchdog_passes_after_rebalance(self):
        """After rebalancing, running check_current_positions passes — proxy for watchdog."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio, check_current_positions
            # Rebalance first
            ok = rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            self.assertTrue(ok, "Rebalance must succeed")
            # Check
            result = check_current_positions(data_dir=Path(tmpdir.name), capital_usd=_CAPITAL)
            self.assertTrue(
                result.passed,
                "Policy check must pass after rebalance: {}".format(
                    [v.message for v in result.violations]
                )
            )
        finally:
            tmpdir.cleanup()

    # ── Policy enforcer integration ───────────────────────────────────────

    def test_validate_positions_called_before_write(self):
        """validate_positions must be called (via policy_enforcer) before writing."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_4T1)
        try:
            from spa_core.tuner import portfolio_rebalancer as mod
            with patch(
                "spa_core.tuner.portfolio_rebalancer.validate_positions",
                wraps=mod.validate_positions,
            ) as mock_val:
                mod.rebalance_portfolio(
                    capital_usd=_CAPITAL,
                    data_dir=Path(tmpdir.name),
                    write=True,
                    send_alert=False,
                )
                self.assertGreater(mock_val.call_count, 0, "validate_positions must be called")
        finally:
            tmpdir.cleanup()

    def test_written_file_is_valid_json(self):
        """Written current_positions.json must be valid JSON."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            pos_path = Path(tmpdir.name) / "current_positions.json"
            content = pos_path.read_text(encoding="utf-8")
            parsed = json.loads(content)  # must not raise
            self.assertIsInstance(parsed, dict)
        finally:
            tmpdir.cleanup()

    def test_written_file_has_required_fields(self):
        """Written file must contain all required fields."""
        required = {
            "generated_at", "source", "is_demo", "capital_usd",
            "deployed_usd", "cash_usd", "policy_compliant", "positions",
        }
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import rebalance_portfolio
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            doc = json.loads((Path(tmpdir.name) / "current_positions.json").read_text())
            for field in required:
                self.assertIn(field, doc, f"Missing required field: {field}")
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
