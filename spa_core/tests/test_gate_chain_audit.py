"""spa_core/tests/test_gate_chain_audit.py — WS-3.1 PRE-EXECUTION GATE-CHAIN AUDIT.

# LLM_FORBIDDEN

Cutover-Bulletproof WS-3.1: pin the ORDERED, TOTAL, FAIL-CLOSED-on-ANY-gate
property of the pre-execution defense chain, and the governance-converged
kill-switch being consulted FIRST. Red-team: a reordering / skip of a gate is
caught; a malicious/over-cap allocation is rejected pre-sign; the audit is inert.

HARD GUARANTEES: INERT (no chain, no signing, is_live never flipped, live data/
never touched — the kill-switch persisted state is redirected to a sandbox).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pytest

from spa_core.execution import gate_chain_audit as gca
from spa_core.execution import safety_checks as sc


# --------------------------------------------------------------------------- #
# The chain is bulletproof: ordered + total + fail-closed + kill-first.
# --------------------------------------------------------------------------- #
class TestChainBulletproof:
    def test_audit_chain_bulletproof(self, tmp_path):
        report = gca.audit(data_dir=str(tmp_path), write=False)
        assert report["chain_bulletproof"] is True, report["failing_audits"]
        assert report["audits_passed"] == report["audits_total"]
        assert report["failing_audits"] == []

    def test_all_properties_hold(self, tmp_path):
        p = gca.audit(data_dir=str(tmp_path), write=False)["properties"]
        assert p["ordered"] is True
        assert p["kill_first"] is True
        assert p["total"] is True
        assert p["fail_closed_each"] is True
        assert p["no_later_gate_unblocks"] is True

    def test_kill_switch_is_position_one(self, tmp_path):
        report = gca.audit(data_dir=str(tmp_path), write=False)
        first = report["gate_scorecard"][0]
        assert first["gate"] == "Kill Switch"
        assert first["position"] == 1
        assert first["kill_switch_first"] is True
        assert report["kill_switch_first"] == "Kill Switch"

    def test_canonical_order_documented(self, tmp_path):
        report = gca.audit(data_dir=str(tmp_path), write=False)
        order = [g["gate"] for g in report["canonical_chain"]]
        assert order == [
            "Kill Switch", "Rate Limit", "RiskPolicy",
            "Transaction Simulation", "Gas Reasonableness", "Multisig Routing",
        ]
        # Only Multisig Routing is non-blocking (informational routing).
        non_blocking = [g["gate"] for g in report["canonical_chain"] if not g["blocking"]]
        assert non_blocking == ["Multisig Routing"]


# --------------------------------------------------------------------------- #
# RED-TEAM — a reordering or skip of a gate MUST be caught.
# --------------------------------------------------------------------------- #
class TestRedTeamReorderingCaught:
    def test_reordering_the_canonical_chain_is_caught(self, tmp_path, monkeypatch):
        """If the documented canonical order is mutated (kill switch no longer
        first), the ORDERED + KILL_FIRST audits FAIL — the audit detects drift."""
        scrambled = (
            ("Rate Limit", True),          # kill switch no longer first!
            ("Kill Switch", True),
            ("RiskPolicy", True),
            ("Transaction Simulation", True),
            ("Gas Reasonableness", True),
            ("Multisig Routing", False),
        )
        monkeypatch.setattr(gca, "CANONICAL_CHAIN", scrambled)
        report = gca.audit(data_dir=str(tmp_path), write=False)
        assert report["chain_bulletproof"] is False
        assert "ORDERED" in report["failing_audits"]
        assert "KILL_FIRST" in report["failing_audits"]

    def test_dropping_a_gate_from_canonical_is_caught(self, tmp_path, monkeypatch):
        """If a required gate is dropped from the documented chain, TOTAL fails
        (the realised pipeline still emits it → realised != documented)."""
        missing_sim = tuple(
            row for row in gca.CANONICAL_CHAIN if row[0] != "Transaction Simulation"
        )
        monkeypatch.setattr(gca, "CANONICAL_CHAIN", missing_sim)
        report = gca.audit(data_dir=str(tmp_path), write=False)
        assert report["chain_bulletproof"] is False
        assert "TOTAL" in report["failing_audits"]

    def test_simulation_made_non_blocking_is_caught(self, tmp_path, monkeypatch):
        """If a documented blocking gate is downgraded to non-blocking, the TOTAL
        audit (which pins the blocking SET) fails."""
        downgraded = tuple(
            (name, False if name == "Transaction Simulation" else blk)
            for name, blk in gca.CANONICAL_CHAIN
        )
        monkeypatch.setattr(gca, "CANONICAL_CHAIN", downgraded)
        report = gca.audit(data_dir=str(tmp_path), write=False)
        assert report["chain_bulletproof"] is False
        assert "TOTAL" in report["failing_audits"]


# --------------------------------------------------------------------------- #
# RED-TEAM — a malicious / over-cap allocation is rejected PRE-SIGN.
# --------------------------------------------------------------------------- #
class TestRedTeamMaliciousAllocation:
    def test_over_cap_allocation_rejected_pre_sign(self, tmp_path):
        """A 90%-of-capital single position (far above the 40% T1 cap) is blocked
        by the RiskPolicy gate inside the pipeline — before any signing path."""
        sc.set_data_dir_override(str(tmp_path))
        try:
            safety = sc.PreExecutionSafety()
            pipeline = safety.run_all(
                protocol="aave-v3", action="supply", amount_usd=90_000.0,
                portfolio_state={"total_capital_usd": 100_000.0, "cash_usd": 10_000.0,
                                 "total_drawdown_pct": 0.0, "positions": []},
                gas_cost_usd=10.0, simulation_result={"success": True, "mode": "local"},
                current_apy=4.0, tvl_usd=500_000_000.0, tier="T1",
            )
            assert pipeline.blocked is True
            assert any("RiskPolicy" in c.check_name and c.is_hard_block
                       for c in pipeline.checks)
        finally:
            sc.set_data_dir_override(None)

    def test_unwhitelisted_protocol_rejected_pre_sign(self, tmp_path):
        sc.set_data_dir_override(str(tmp_path))
        try:
            safety = sc.PreExecutionSafety()
            pipeline = safety.run_all(
                protocol="rug_pull_xyz", action="supply", amount_usd=100.0,
                portfolio_state={"total_capital_usd": 100_000.0, "cash_usd": 60_000.0,
                                 "total_drawdown_pct": 0.0, "positions": []},
                gas_cost_usd=0.1, simulation_result={"success": True, "mode": "local"},
            )
            assert pipeline.blocked is True
        finally:
            sc.set_data_dir_override(None)


# --------------------------------------------------------------------------- #
# INERT — the audit never flips is_live / touches live data / signs.
# --------------------------------------------------------------------------- #
class TestInert:
    def test_audit_is_inert(self, tmp_path):
        report = gca.audit(data_dir=str(tmp_path), write=False)
        assert report["is_inert"] is True
        assert report["moves_capital"] is False
        assert report["would_cutover"] is False
        assert report["llm_forbidden"] is True
        assert report["live_data_untouched"] is True

    def test_refuses_to_run_against_live_data(self):
        from spa_core.utils.errors import SPAError
        from pathlib import Path
        live = Path(gca._ROOT) / "data"
        with pytest.raises(SPAError):
            gca.audit(data_dir=str(live), write=False)

    def test_data_dir_override_restored(self, tmp_path):
        """The audit must restore the safety_checks data-dir override it set, so
        it leaves no global state mutated for other code."""
        before = sc._DATA_DIR_OVERRIDE
        gca.audit(data_dir=str(tmp_path), write=False)
        assert sc._DATA_DIR_OVERRIDE == before

    def test_write_lands_in_sandbox_only(self, tmp_path):
        gca.audit(data_dir=str(tmp_path), write=True)
        assert (tmp_path / "gate_chain_audit.json").exists()
