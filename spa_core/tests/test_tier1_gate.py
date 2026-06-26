"""
test_tier1_gate.py — pins the Tier-1 backtest->paper eligibility gate.

Covers (deterministic, stdlib-only, no network):
  * _block_reason: validated => eligible; each block branch => its reason.
  * build_gate: partitions a leaderboard into eligible / blocked.
  * _live_divergence: live APY > floor*expected => ok; below => DIVERGENT;
                      missing data => insufficient_data.
  * is_eligible: present-and-listed, present-and-not-listed, and the
                 FAIL-OPEN-ON-MISSING-FILE branch (documented + asserted).

FAIL-OPEN ASSESSMENT (see test_is_eligible_failopen_on_missing_file):
  is_eligible() returns True when data/tier1_gate.json is absent. This is a
  PROMOTION/advisory gate, not a money/risk gate (the module never touches the
  execution domain — see module docstring + RiskPolicy is the real money gate).
  Fail-OPEN here means "missing Tier-1 run does not block the tournament from
  considering a strategy for the paper-shadow set." Because the downstream live
  allocation is still gated by the deterministic RiskPolicy (LLM-forbidden,
  approved=False non-overridable), fail-open at THIS layer admits a strategy to
  PAPER only — not to live capital. That is an acceptable default for an
  advisory gate. The notable nuance: the fail-open is to PROMOTE (admit), not to
  withhold; this is documented behavior, asserted below, and flagged so a future
  change of policy (e.g. fail-CLOSED until a Tier-1 run exists) is a conscious
  decision rather than a silent regression.
"""
import json
import unittest
from pathlib import Path

from spa_core.backtesting.tier1 import gate as gate_mod


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj))


class _PathPatch:
    """Tiny ctx-manager to redirect the module's data paths (no pytest dep)."""

    def __init__(self, **paths):
        self._paths = paths
        self._saved = {}

    def __enter__(self):
        for k, v in self._paths.items():
            self._saved[k] = getattr(gate_mod, k)
            setattr(gate_mod, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            setattr(gate_mod, k, v)


class TestBlockReason(unittest.TestCase):
    def test_validated_is_eligible(self):
        self.assertIsNone(gate_mod._block_reason({"validated": True}))

    def test_net_apy_non_positive(self):
        self.assertEqual(
            gate_mod._block_reason({"validated": False, "net_apy_pct": 0}),
            "net_of_cost_apy<=0",
        )

    def test_outside_packages(self):
        self.assertEqual(
            gate_mod._block_reason(
                {"validated": False, "net_apy_pct": 4.0, "package": None}),
            "outside_all_package_risk_bands",
        )

    def test_oos_decay(self):
        self.assertEqual(
            gate_mod._block_reason(
                {"validated": False, "net_apy_pct": 4.0, "package": "balanced",
                 "oos_holds": False}),
            "yield_decayed_out_of_sample",
        )

    def test_capacity_below_capital(self):
        r = gate_mod._block_reason(
            {"validated": False, "net_apy_pct": 4.0, "package": "balanced",
             "oos_holds": True, "capacity_ok": False, "binding_protocol": "maple"})
        self.assertIn("capacity_below_capital", r)
        self.assertIn("maple", r)

    def test_unproven_grade(self):
        self.assertEqual(
            gate_mod._block_reason(
                {"validated": False, "net_apy_pct": 4.0, "package": "balanced",
                 "oos_holds": True, "capacity_ok": True, "tier1_grade": "UNPROVEN"}),
            "data_not_trustworthy",
        )

    def test_generic_not_validated(self):
        self.assertEqual(
            gate_mod._block_reason(
                {"validated": False, "net_apy_pct": 4.0, "package": "balanced",
                 "oos_holds": True, "capacity_ok": True, "tier1_grade": "OK"}),
            "not_validated",
        )


class TestBuildGate(unittest.TestCase):
    def test_partitions_eligible_and_blocked(self):
        verdict = {
            "regime": "VOLATILE",
            "leaderboard_tier1": [
                {"id": "S_good", "validated": True, "net_apy_pct": 5.0},
                {"id": "S_bad", "validated": False, "net_apy_pct": 0},
            ],
        }
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            vp = Path(d) / "verdict.json"
            op = Path(d) / "gate.json"
            pp = Path(d) / "paper.json"
            _write(vp, verdict)
            _write(pp, {})
            with _PathPatch(_VERDICT=vp, _OUT=op, _PAPER=pp):
                g = gate_mod.build_gate(write=True)
            self.assertIn("S_good", g["eligible_for_paper"])
            self.assertNotIn("S_bad", g["eligible_for_paper"])
            self.assertEqual(g["blocked"]["S_bad"], "net_of_cost_apy<=0")
            self.assertEqual(g["eligible_count"], 1)
            self.assertEqual(g["blocked_count"], 1)
            self.assertTrue(g["llm_forbidden"])
            self.assertTrue(op.exists(), "gate file written atomically")


class TestLiveDivergence(unittest.TestCase):
    def _run(self, live_apy, validated_nets):
        verdict = {"leaderboard_tier1": [
            {"id": f"S{i}", "validated": True, "net_apy_pct": n}
            for i, n in enumerate(validated_nets)]}
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            pp = Path(d) / "paper.json"
            _write(pp, {"apy_today_pct": live_apy} if live_apy is not None else {})
            with _PathPatch(_PAPER=pp):
                return gate_mod._live_divergence(verdict)

    def test_within_floor_is_ok(self):
        # expected median = 4.0; floor 0.5 => threshold 2.0; live 3.0 > 2.0 -> ok
        r = self._run(3.0, [4.0, 4.0])
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["expected_apy_pct"], 4.0)

    def test_below_floor_is_divergent(self):
        # live 1.0 < 0.5*4.0=2.0 -> DIVERGENT (auto-demote signal)
        r = self._run(1.0, [4.0, 4.0])
        self.assertEqual(r["status"], "DIVERGENT")
        self.assertGreater(r["shortfall_pct"], 0)

    def test_exactly_at_floor_is_ok(self):
        # live == 0.5*expected is NOT strictly below -> ok (boundary pinned)
        r = self._run(2.0, [4.0, 4.0])
        self.assertEqual(r["status"], "ok")

    def test_missing_live_apy_insufficient(self):
        r = self._run(None, [4.0, 4.0])
        self.assertEqual(r["status"], "insufficient_data")

    def test_no_validated_strategies_insufficient(self):
        r = self._run(3.0, [])
        self.assertEqual(r["status"], "insufficient_data")


class TestIsEligible(unittest.TestCase):
    def test_listed_strategy_is_eligible(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            op = Path(d) / "gate.json"
            _write(op, {"eligible_for_paper": ["S1", "S2"]})
            with _PathPatch(_OUT=op):
                self.assertTrue(gate_mod.is_eligible("S1"))
                self.assertFalse(gate_mod.is_eligible("S_not_listed"))

    def test_is_eligible_failopen_on_missing_file(self):
        """DOCUMENTED behavior: missing gate file => fail-OPEN to True (admit).

        This is an advisory PROMOTION gate; the real money gate is RiskPolicy.
        Fail-open here admits to PAPER only. Asserted so any future shift to
        fail-CLOSED is a deliberate, reviewed change rather than a silent
        regression. See module-level docstring FAIL-OPEN ASSESSMENT.
        """
        with _PathPatch(_OUT=Path("/definitely/missing/tier1_gate.json")):
            self.assertTrue(gate_mod.is_eligible("anything"))

    def test_is_eligible_failopen_on_empty_file(self):
        # _load returns {} (falsy) on empty -> same fail-open branch.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            op = Path(d) / "gate.json"
            op.write_text("")  # unparseable -> _load default None -> fail-open
            with _PathPatch(_OUT=op):
                self.assertTrue(gate_mod.is_eligible("anything"))


if __name__ == "__main__":
    unittest.main()
