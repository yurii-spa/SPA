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
    # All six protocols resolve to Ethereum, so deployed total must stay within
    # the ADR-062 single-chain cap (≤90% of capital); 89% leaves margin.
    "aave_v3": 25_000.0,          # T1, 25%
    "compound_v3": 20_000.0,      # T1, 20%
    "spark_susds": 15_000.0,      # T1, 15%
    "morpho_steakhouse": 7_000.0, # T1, 7%  → T1 total = 67%
    "maple": 15_000.0,            # T2, 15%
    "euler_v2": 7_000.0,          # T2, 7%  → deployed = 89%
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

    def test_positions_valid_after_rebalance(self):
        """After rebalance, the written book must PASS policy validation. The 55% T1 floor
        was retired (owner reconcile 2026-07-08); the contract is COMPLIANCE, not a fixed
        T1% — so we assert the rebalanced book satisfies the authoritative policy caps."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner.portfolio_rebalancer import (
                rebalance_portfolio,
                check_current_positions,
            )
            rebalance_portfolio(
                capital_usd=_CAPITAL,
                data_dir=Path(tmpdir.name),
                write=True,
                send_alert=False,
            )
            result = check_current_positions(data_dir=Path(tmpdir.name), capital_usd=_CAPITAL)
            self.assertTrue(
                result.passed,
                "rebalanced book must be policy-compliant; violations="
                + str([v.rule for v in result.violations]),
            )
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
        """If BOTH the tuner allocation and the safe fallback fail policy validation, the
        original file is left unchanged and rebalance_portfolio returns False. Validation is
        forced to fail (via a monkeypatch) so the SAFETY CONTROL FLOW is exercised regardless
        of specific cap values — after the 2026-07-08 reconcile the tuner now passes on its
        own, so a value-based 'bad' fallback no longer reaches this path."""
        from types import SimpleNamespace
        many_pos = {f"proto_{i}": 5000.0 for i in range(12)}  # 12 > 8 max — invalid book on disk
        tmpdir = _make_data_dir(positions=many_pos, adapter_data=_ADAPTER_DATA_2T1)
        orig_content = (Path(tmpdir.name) / "current_positions.json").read_text()
        try:
            from spa_core.tuner import portfolio_rebalancer as mod

            _orig_validate = mod.validate_positions
            mod.validate_positions = lambda *a, **k: SimpleNamespace(
                passed=False,
                warnings=[],
                violations=[SimpleNamespace(rule="per_protocol_max_pct", message="forced test violation")],
                portfolio_summary={},
            )
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
                mod.validate_positions = _orig_validate
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

    def test_check_current_positions_low_t1_still_caught_by_other_caps(self):
        """The 55% T1 floor was removed (owner reconcile 2026-07-08), so a concentrated
        low-T1 book is no longer flagged t1_min_pct — but it is STILL rejected by the
        surviving caps (per-protocol 40% + T2 50%). Detection must not silently vanish."""
        low_t1 = {
            "maple": 50_000.0,    # T2, 50% — > 40% per-protocol cap
            "euler_v2": 43_000.0, # T2, 43% — > 40% per-protocol cap
        }
        tmpdir = _make_data_dir(positions=low_t1)
        try:
            from spa_core.tuner.portfolio_rebalancer import check_current_positions
            result = check_current_positions(data_dir=Path(tmpdir.name), capital_usd=_CAPITAL)
            self.assertFalse(result.passed)  # still rejected, just not on t1_min
            rules = [v.rule for v in result.violations]
            self.assertNotIn("t1_min_pct", rules)
            self.assertIn("per_protocol_max_pct", rules)
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

    def test_safe_fallback_t1_at_least_55pct_of_deployed(self):
        """Safe fallback stays T1-dominant: T1 >= 55% of the DEPLOYED book.

        DELIBERATE CHANGE (2026-08-05, card agent-safe-fallback-bypasses-
        adapter-gates, инв.16 rationale): the old assertion measured T1 as a
        share of TOTAL CAPITAL, which was only reachable by funding
        `spark_susds` — a protocol the adapter class gate BLOCKS
        (invariant 10: Sky/sUSDS = 0% until GSM Pause Delay >= 48h confirmed
        on-chain). The fallback now routes gate-blocked shares to CASH, so a
        capital-denominated 55% would force the test to demand a forbidden
        allocation. The 55% T1 floor itself was retired (owner reconcile
        2026-07-08; policy_enforcer t1_min_pct = 0.0) — what this test pins is
        the book's conservative SHAPE: whatever IS deployed must stay
        T1-dominant. Holds both with and without spark_susds (68.2% / 62.7%).
        """
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        from spa_core.risk.policy_enforcer import validate_positions
        positions, cash_usd = _build_safe_fallback_positions(_CAPITAL)
        result = validate_positions(positions=positions, capital_usd=_CAPITAL, cash_usd=cash_usd)
        deployed = sum(positions.values())
        self.assertGreater(deployed, 0.0, "fallback book unexpectedly empty")
        t1_usd = _CAPITAL * result.portfolio_summary["t1_pct"] / 100.0
        self.assertGreaterEqual(t1_usd / deployed * 100.0, 55.0)

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
        """data/current_positions.json must be written by a recognised code-owned writer.

        Two legitimate writers exist: the canonical daily ``cycle_runner`` (which
        refreshes positions at the end of each cycle — ALLOC-002) and the
        standalone ``portfolio_rebalancer_v1`` (ALLOC-001). The file must carry
        one of these sources — never a foreign/unknown writer.
        """
        repo = Path(__file__).resolve().parents[1]
        pos_path = repo / "data" / "current_positions.json"
        if not pos_path.exists():
            self.skipTest("current_positions.json not found")
        doc = json.loads(pos_path.read_text())
        self.assertIn(
            doc.get("source"),
            {"portfolio_rebalancer_v1", "cycle_runner"},
            "source must be a recognised code-owned writer "
            "(portfolio_rebalancer_v1 or cycle_runner)",
        )

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
        """When both the tuner allocation and the fallback fail validation, a Telegram alert
        must be sent. Validation is forced to fail (monkeypatch) to exercise the alert path
        independent of the post-2026-07-08 cap values (the tuner now passes on its own)."""
        from types import SimpleNamespace
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner import portfolio_rebalancer as mod

            _orig_validate = mod.validate_positions
            mod.validate_positions = lambda *a, **k: SimpleNamespace(
                passed=False,
                warnings=[],
                violations=[SimpleNamespace(rule="per_protocol_max_pct", message="forced test violation")],
                portfolio_summary={},
            )
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
                mod.validate_positions = _orig_validate
        finally:
            tmpdir.cleanup()

    def test_no_telegram_when_send_alert_false(self):
        """With send_alert=False, Telegram must never be called regardless of result."""
        tmpdir = _make_data_dir(adapter_data=_ADAPTER_DATA_2T1)
        try:
            from spa_core.tuner import portfolio_rebalancer as mod

            _orig = mod._build_safe_fallback_positions

            # ``**_kw`` added 2026-08-21 (ADR-108, invariant #16 — deliberate,
            # noted in docs/journal/2026-W34.md). The real function grew a
            # ``data_dir`` argument so the emergency book can consult live
            # observations; this double refused it and the call raised TypeError
            # before reaching the assertion. Nothing about what the test CHECKS
            # changed — it still asserts Telegram is never called with
            # send_alert=False — only the double's signature, which exists to
            # mirror the real one.
            def _bad_fallback(capital_usd, base_positions=None, **_kw):
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


class TestSafeFallbackAdapterClassGate(unittest.TestCase):
    """Card agent-safe-fallback-bypasses-adapter-gates (2026-08-05).

    The emergency book (`_SAFE_FALLBACK_POSITIONS`) used to bypass the
    allocator's adapter-class gate (ADR-061 `_adapter_class_gate`) entirely and
    funded `spark_susds` (13%) even while the gate said
    `(False, "gsm_not_confirmed")` — invariant 10 (Sky/sUSDS = 0% until GSM
    Pause Delay >= 48h confirmed on-chain). Every test here is a positive
    control: on the UNFIXED builder the gate-blocking tests are RED (spark in
    the book), and the allow-direction tests pin that a compliant protocol is
    NOT dropped (the fix cannot "pass" by going all-cash unconditionally).
    """

    @staticmethod
    def _gate_blocking(*blocked_map):
        """Build a class_gate that blocks {proto: reason} pairs, allows the rest."""
        merged = {}
        for m in blocked_map:
            merged.update(m)

        def gate(proto):
            if proto in merged:
                return False, merged[proto]
            return True, None
        return gate

    # ── direction 1: blocked protocols must NOT be funded ────────────────────

    def test_gsm_blocked_spark_excluded_from_fallback_book(self):
        """invariant 10: gate says gsm_not_confirmed → spark_susds gets $0."""
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        gate = self._gate_blocking({"spark_susds": "gsm_not_confirmed"})
        positions, cash_usd = _build_safe_fallback_positions(_CAPITAL, class_gate=gate)
        self.assertNotIn("spark_susds", positions)
        self.assertGreater(len(positions), 0, "survivors must stay funded")

    def test_blocked_share_goes_to_cash_not_redistributed(self):
        """The freed 13% lands in CASH; survivors keep their absolute amounts."""
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        allow_all = self._gate_blocking()
        blocked = self._gate_blocking({"spark_susds": "gsm_not_confirmed"})
        full_pos, full_cash = _build_safe_fallback_positions(_CAPITAL, class_gate=allow_all)
        filt_pos, filt_cash = _build_safe_fallback_positions(_CAPITAL, class_gate=blocked)
        # survivors byte-identical — no protocol grew because a peer was blocked
        for proto, usd in filt_pos.items():
            self.assertAlmostEqual(usd, full_pos[proto], places=2,
                                   msg=f"{proto} was re-scaled after the block")
        # capital conserved; the blocked share moved to cash
        self.assertAlmostEqual(
            filt_cash, full_cash + full_pos["spark_susds"], places=2)
        self.assertAlmostEqual(
            sum(filt_pos.values()) + filt_cash, _CAPITAL, delta=0.05)

    def test_advisory_blocked_protocol_excluded(self):
        """invariant 9: IS_ADVISORY/RESEARCH_ONLY verdict → protocol not funded."""
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        gate = self._gate_blocking({"maple": "advisory"})
        positions, _ = _build_safe_fallback_positions(_CAPITAL, class_gate=gate)
        self.assertNotIn("maple", positions)

    def test_all_blocked_goes_all_cash_fail_closed(self):
        """Nothing survives the filter → all-cash, never a forbidden book."""
        from spa_core.tuner.portfolio_rebalancer import (
            _SAFE_FALLBACK_POSITIONS, _build_safe_fallback_positions,
        )
        gate = self._gate_blocking(
            {p: "gsm_not_confirmed" for p in _SAFE_FALLBACK_POSITIONS})
        positions, cash_usd = _build_safe_fallback_positions(_CAPITAL, class_gate=gate)
        self.assertEqual(positions, {})
        self.assertAlmostEqual(cash_usd, _CAPITAL, delta=0.01)

    def test_gate_exception_fail_closed_for_that_protocol(self):
        """A gate that RAISES for a protocol blocks that protocol (fail-CLOSED)."""
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions

        def gate(proto):
            if proto == "spark_susds":
                raise RuntimeError("gate broke")
            return True, None
        positions, _ = _build_safe_fallback_positions(_CAPITAL, class_gate=gate)
        self.assertNotIn("spark_susds", positions)
        self.assertGreater(len(positions), 0)

    def test_gate_import_failure_goes_all_cash(self):
        """Gate module unavailable → NOTHING can be verified → all-cash."""
        import sys
        import types
        from unittest.mock import patch
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        hollow = types.ModuleType("spa_core.allocator.allocator")  # no gate attr
        with patch.dict(sys.modules, {"spa_core.allocator.allocator": hollow}):
            positions, cash_usd = _build_safe_fallback_positions(_CAPITAL)
        self.assertEqual(positions, {})
        self.assertAlmostEqual(cash_usd, _CAPITAL, delta=0.01)

    # ── direction 2: allowed protocols must NOT be dropped ───────────────────

    def test_allow_all_gate_keeps_full_book(self):
        """Reverse control: with every protocol allowed the full 7-protocol
        book is funded — the fix cannot 'pass' by refusing everything."""
        from spa_core.tuner.portfolio_rebalancer import (
            _SAFE_FALLBACK_POSITIONS, _build_safe_fallback_positions,
        )
        allow_all = self._gate_blocking()
        positions, _ = _build_safe_fallback_positions(_CAPITAL, class_gate=allow_all)
        self.assertEqual(set(positions), set(_SAFE_FALLBACK_POSITIONS))
        self.assertIn("spark_susds", positions)

    # ── default wiring: the builder consults the ALLOCATOR's gate ────────────

    def test_default_gate_is_allocator_adapter_class_gate(self):
        """POSITIVE CONTROL for the card defect: with NO injected gate the
        builder must consult `spa_core.allocator.allocator._adapter_class_gate`.
        On the unfixed builder this test is RED (gate never called, spark
        funded)."""
        from unittest.mock import patch
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions

        def fake_gate(proto):
            if proto == "spark_susds":
                return False, "gsm_not_confirmed"
            return True, None
        with patch("spa_core.allocator.allocator._adapter_class_gate",
                   side_effect=fake_gate) as mocked:
            positions, _ = _build_safe_fallback_positions(_CAPITAL)
        self.assertGreater(mocked.call_count, 0,
                           "fallback builder never consulted the adapter class gate")
        self.assertNotIn("spark_susds", positions)

    # ── the filtered book still satisfies the whole policy_enforcer ──────────

    def test_filtered_book_passes_policy_enforcer(self):
        """Card item 3: after the exclusion the book still passes ALL enforcer
        rules (incl. ADR-062 chain caps) — more cash, same survivors."""
        from spa_core.tuner.portfolio_rebalancer import _build_safe_fallback_positions
        from spa_core.risk.policy_enforcer import validate_positions
        gate = self._gate_blocking({"spark_susds": "gsm_not_confirmed"})
        positions, cash_usd = _build_safe_fallback_positions(_CAPITAL, class_gate=gate)
        result = validate_positions(
            positions=positions, capital_usd=_CAPITAL, cash_usd=cash_usd)
        self.assertTrue(
            result.passed,
            "filtered fallback must pass policy: {}".format(
                [v.message for v in result.violations]))

    # ── money-path consumer: risk_gate._compliant_target ─────────────────────

    def test_compliant_target_fallback_respects_gate(self):
        """The ALLOC-002 pre-diff collapse (risk_gate._compliant_target) adopts
        the safe fallback when the rebalancer cannot run (empty sandbox). That
        adopted book must honour the gate: blocked → no spark; allowed → spark
        present (both directions, same harness)."""
        from unittest.mock import patch
        from spa_core.paper_trading.risk_gate import _compliant_target
        # >8 protocols forces the max_protocols collapse branch
        raw_target = {f"proto_{i}": 6_000.0 for i in range(9)}
        raw_target["aave_v3"] = 6_000.0

        def blocking_gate(proto):
            if proto == "spark_susds":
                return False, "gsm_not_confirmed"
            return True, None

        with tempfile.TemporaryDirectory() as d:
            with patch("spa_core.allocator.allocator._adapter_class_gate",
                       side_effect=blocking_gate):
                out_blocked, collapsed_b = _compliant_target(
                    dict(raw_target), _CAPITAL, Path(d), write=False)
            with patch("spa_core.allocator.allocator._adapter_class_gate",
                       return_value=(True, None)):
                out_allowed, collapsed_a = _compliant_target(
                    dict(raw_target), _CAPITAL, Path(d), write=False)
        self.assertTrue(collapsed_b and collapsed_a,
                        "harness failed to reach the safe-fallback collapse branch")
        self.assertNotIn("spark_susds", out_blocked,
                         "money-path fallback funded a gate-blocked protocol")
        self.assertIn("spark_susds", out_allowed,
                      "reverse control: allowed protocol was dropped")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ── Зеркало политики: фантомный T1-пол не должен вернуться ────────────────────
# Решение владельца 2026-08-25 (вариант A). Ребалансер держал t1_min=0.55 — копию
# правила, удалённого из RiskPolicy 2026-07-08; гейт и сторож свели своё значение к
# 0.0 ещё тогда, а ребалансер остался единственным носителем фантома и потому строил
# раскладку под несуществующее требование. Сторож ниже краснеет, если копия вернётся.

class TestT1FloorMirrorsPolicy:
    def test_rebalancer_t1_min_mirrors_enforcer(self):
        """t1_min ребалансера обязан совпадать с RULES['t1_min_pct'] гейта."""
        from spa_core.tuner.portfolio_rebalancer import _DEFAULT_CONSTRAINTS
        from spa_core.risk.policy_enforcer import RULES
        assert _DEFAULT_CONSTRAINTS.t1_min * 100.0 == float(RULES["t1_min_pct"])

    def test_no_phantom_55pct_floor(self):
        """Прямой контроль на саму аварию: 55%-пола в ребалансере больше нет."""
        from spa_core.tuner.portfolio_rebalancer import _DEFAULT_CONSTRAINTS
        assert _DEFAULT_CONSTRAINTS.t1_min != 0.55

    def test_margins_mirror_policy_after_the_owner_reversed_himself(self):
        """Запасов больше нет: поля — ЗЕРКАЛО живого RiskConfig (ADR-144, реш. владельца 26.08).

        ИЗМЕНЕНИЕ ТЕСТА НАМЕРЕННОЕ (инв. #16), обоснование здесь и в
        `docs/journal/2026-W35.md`. Прежняя версия называлась
        `test_deliberate_margins_kept` и пинила запасы 0.25 / 0.45 / 0.07 / 7 по решению
        владельца **25.08 «запас оставить»**. **26.08 владелец это решение ОТМЕНИЛ** кнопкой
        «Зеркалить политику» (карточка `own-tuner-zerkalit-politiku-zapasy-snyaty`, ADR-144),
        и реализация уехала на `origin/main` коммитом `b6f426f88`. Автор той правки обновил три
        пина в `spa_core/tests/`, а этот — четвёртый, в ДРУГОМ корне (`tests/`) — не увидел,
        и с 26.08 он красил `main` в одиночку (замер цикла #388: полный прогон CI-командой на
        чистом `origin/main` = ровно 1 failed, и это он).

        Проверка не ослаблена, а перенесена на источник правды: раньше она сверяла литералы с
        литералами (класс «эхо»), теперь — поля тюнера с ЖИВЫМ `RiskConfig`. Изменится
        политика — зеркало обязано поехать следом, иначе тест краснеет.
        """
        from spa_core.tuner.portfolio_rebalancer import _DEFAULT_CONSTRAINTS as c
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
        assert c.per_protocol_max == cfg.max_concentration_t1
        assert c.t2_max == cfg.max_total_t2_allocation
        assert c.cash_min == cfg.min_cash_pct
        assert c.max_protocols == cfg.max_protocols
        # обратное плечо: ужесточение по-прежнему возможно ОДНИМ полем, формула min() жива
        from spa_core.tuner.allocation_tuner import TunerConstraints
        assert TunerConstraints(per_protocol_max=0.25).protocol_cap("T1") == 0.25
        # …и вторая половина того же: потолок ТИРА T2 под узким конвертом тоже действует.
        # Без неё min() проверен лишь с одной стороны — ужесточение видно, а потолок
        # политики мог бы молча исчезнуть.
        assert TunerConstraints(per_protocol_max=0.25).protocol_cap("T2") == 0.20
