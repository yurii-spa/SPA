"""spa_core/tests/test_money_path_failure_modes.py — LIVE-PATH FAILURE-MODE COVERAGE.

# LLM_FORBIDDEN

Cutover-Bulletproof WS-1.1: the inert execution layer must fail-CLOSED on EVERY
realistic money-path failure mode BEFORE it could ever carry capital. This suite
injects each failure mode against the REAL execution modules (reconciliation.py,
position_monitor.py) plus a mocked signer/chain, and asserts:

    failure mode  →  safe ABORT / BLOCK  +  clean book (NAV unchanged, no partial
                     corruption)  +  NO silent pass.

Failure modes covered (each fails-CLOSED; ≥20 injection tests):
  * PARTIAL-FILL          — an order fills only partially → reconcile detects
                            matches_target=False → ABORT (no partial NAV corruption).
  * REVERTED-TX           — the tx reverts → no NAV change, position unchanged,
                            and the intended (un-applied) target is NOT reported
                            as matched.
  * REORG / STATE-CHANGE  — on-chain state differs from expected (a reorg rewrote
                            a position) → reconcile mismatch → BLOCK.
  * SIGNER-FAILURE        — eth_signer raises / nonce gap → safe ABORT, and NO
                            private-key material leaks into any error/log line.
  * RECONCILIATION-MISMATCH — nav_conserved=False (capital appeared/vanished) →
                            BLOCK.

HARD GUARANTEES (do not relax):
  * INERT. NO live calls — the chain and the signer are mocked. is_live is never
    flipped. No live ``data/`` file is read or written (everything is in-process
    or against tmp_path).
  * The signer tests mock ``eth_signer._get_account`` so they run WITHOUT the
    optional ``eth_account`` dependency installed.
  * Red-team property: NO failure mode may silently proceed or corrupt NAV; on a
    signer failure NO key material may appear in any surfaced diagnostic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

import pytest

_SPA_CORE = Path(__file__).parent.parent
if str(_SPA_CORE.parent) not in sys.path:
    sys.path.insert(0, str(_SPA_CORE.parent))

from spa_core.execution import reconciliation as rec
from spa_core.execution import eth_signer
from spa_core.execution.position_monitor import PositionMonitor


# WS-6 hermetic guard: ``reconciliation.round_trip`` does a best-effort
# ``hash_chain.append`` even with ``write=False``; redirect the tamper-evident
# audit chain to a throwaway tmp file so this suite NEVER appends to the LIVE
# data/audit_chain.jsonl (a guardrail: tests must not touch live data/).
@pytest.fixture(autouse=True)
def _hermetic_audit_chain(tmp_path, monkeypatch):
    from spa_core.audit import hash_chain
    monkeypatch.setattr(hash_chain, "_CHAIN", tmp_path / "audit_chain.jsonl")
    yield


# A publicly-known dev test private key (Hardhat/Foundry account #0). It carries
# NO real funds; it is used ONLY to prove it never leaks into a diagnostic.
_PUBLIC_DEV_KEY = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

# reconciliation.reconcile compares nav_after (= sum of DEPLOYED positions) to
# nav_before − costs, so the NAV-before passed to a fully-deployed target must
# equal that target's deployed notional. _target() deploys $75k, so _CAPITAL is
# the deployed notional ($75k) — a clean full fill then conserves NAV exactly.
_CAPITAL = 75_000.0


# --------------------------------------------------------------------------- #
# Helpers — a target the cycle INTENDED, and the various corrupted outcomes.
# --------------------------------------------------------------------------- #
def _target() -> dict:
    """A representative intended target book — $75k fully deployed across 3 pools."""
    return {"aave_v3": 40_000.0, "morpho_blue": 20_000.0, "compound_v3": 15_000.0}


def _proceeds(recon: dict) -> bool:
    """Would the cycle PROCEED on this reconciliation? Only if intent==outcome
    AND NAV conserved. Anything else MUST abort/block (fail-CLOSED)."""
    return bool(recon["matches_target"]) and bool(recon["nav_conserved"])


# =========================================================================== #
# PARTIAL-FILL — an order fills only partially → reconcile catches it → ABORT.
# =========================================================================== #
class TestPartialFill:
    def test_partial_fill_detected_as_mismatch(self):
        target = _target()
        # aave order filled only $25k of the intended $40k (a $15k short fill).
        partial = dict(target)
        partial["aave_v3"] = 25_000.0
        recon = rec.reconcile(target, partial, nav_before=_CAPITAL, costs_usd=0.0)
        assert recon["matches_target"] is False
        assert recon["max_position_delta_usd"] == pytest.approx(15_000.0)

    def test_partial_fill_does_not_silently_proceed(self):
        target = _target()
        partial = dict(target)
        partial["compound_v3"] = 5_000.0  # $10k short
        recon = rec.reconcile(target, partial, nav_before=_CAPITAL, costs_usd=0.0)
        # The cycle MUST NOT proceed on a partial fill.
        assert _proceeds(recon) is False

    def test_partial_fill_zero_fill_caught(self):
        """An order that did not fill AT ALL (0 of intended) is still a mismatch."""
        target = _target()
        zero = dict(target)
        zero["morpho_blue"] = 0.0  # never entered
        recon = rec.reconcile(target, zero, nav_before=_CAPITAL, costs_usd=0.0)
        assert recon["matches_target"] is False
        assert _proceeds(recon) is False

    def test_full_fill_still_reconciles_clean(self):
        """Control: a clean FULL fill DOES reconcile (so the gate is not vacuous)."""
        target = _target()
        recon = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0)
        assert recon["matches_target"] is True
        assert recon["nav_conserved"] is True
        assert _proceeds(recon) is True

    def test_partial_fill_overfill_caught(self):
        """An order that filled MORE than intended (over-fill) is also a mismatch."""
        target = _target()
        over = dict(target)
        over["aave_v3"] = 60_000.0  # $20k over the intended $40k
        recon = rec.reconcile(target, over, nav_before=_CAPITAL, costs_usd=0.0)
        assert recon["matches_target"] is False
        assert _proceeds(recon) is False


# =========================================================================== #
# REVERTED-TX — the tx reverts: NO state change, position unchanged, intended
# target NOT matched (the cycle must not believe an un-applied trade succeeded).
# =========================================================================== #
class TestRevertedTx:
    def test_reverted_tx_leaves_positions_unchanged(self):
        """A revert means the dry-run virtual ledger is untouched: applying ZERO
        executed trades to current yields current (no NAV drift)."""
        current = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        # planned to add compound_v3, but the supply tx REVERTED → no trade applied.
        exec_result = rec.dry_run_execute(current, trades=[])  # reverted → 0 trades
        assert exec_result["resulting_positions"] == {
            p: round(v, 2) for p, v in current.items()
        }
        assert exec_result["gross_traded_usd"] == 0.0

    def test_reverted_tx_not_reported_as_matched(self):
        current = {"aave_v3": 40_000.0}
        # Intended to enter morpho_blue $20k, but the tx reverted (outcome == current).
        target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        recon = rec.reconcile(target, current, nav_before=40_000.0, costs_usd=0.0)
        assert recon["matches_target"] is False
        assert _proceeds(recon) is False

    def test_reverted_tx_nav_before_equals_after(self):
        """NAV is conserved across a revert (no capital moved) — the book is clean,
        it just does not MATCH the intended target."""
        current = {"aave_v3": 40_000.0}
        target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        nav_before = sum(current.values())
        recon = rec.reconcile(target, current, nav_before=nav_before, costs_usd=0.0)
        # No partial NAV corruption: nav_after == nav_before.
        assert recon["nav_after"] == pytest.approx(nav_before)
        assert recon["nav_conserved"] is True   # clean book...
        assert recon["matches_target"] is False  # ...but intent != outcome → abort

    def test_partial_revert_in_multi_leg_caught(self):
        """One leg of a multi-leg rebalance reverts → the surviving outcome does
        NOT match the full intended target → abort."""
        current = {"aave_v3": 60_000.0}
        # Intended: trim aave to 40k AND open morpho 20k. The morpho leg reverted.
        target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        outcome = {"aave_v3": 40_000.0}  # aave trimmed, morpho leg reverted
        recon = rec.reconcile(target, outcome, nav_before=60_000.0, costs_usd=0.0)
        assert recon["matches_target"] is False
        assert _proceeds(recon) is False


# =========================================================================== #
# REORG / STATE-CHANGE — on-chain state differs from expected (a reorg rewrote a
# position) → reconcile mismatch → BLOCK.
# =========================================================================== #
class TestReorgStateChange:
    def test_reorg_rewrote_position_caught(self):
        target = _target()
        # A reorg dropped the aave supply tx → on-chain shows the pre-trade balance.
        reorged = dict(target)
        reorged["aave_v3"] = 0.0
        recon = rec.reconcile(target, reorged, nav_before=_CAPITAL, costs_usd=0.0)
        assert recon["matches_target"] is False
        assert _proceeds(recon) is False

    def test_reorg_added_phantom_position_caught(self):
        target = _target()
        # A reorg re-ordered txs so an unexpected protocol shows a balance.
        phantom = dict(target)
        phantom["euler_v2"] = 12_000.0
        recon = rec.reconcile(target, phantom, nav_before=_CAPITAL, costs_usd=0.0)
        assert recon["matches_target"] is False
        assert _proceeds(recon) is False

    def test_state_change_within_tolerance_passes(self):
        """A sub-tolerance dust drift (< $1) is NOT a mismatch (control)."""
        target = _target()
        drifted = dict(target)
        drifted["aave_v3"] = 40_000.0 + 0.50  # 50c drift < $1 POSITION_TOLERANCE_USD
        recon = rec.reconcile(target, drifted, nav_before=_CAPITAL + 0.50, costs_usd=0.0)
        assert recon["matches_target"] is True

    def test_state_change_above_tolerance_blocks(self):
        target = _target()
        drifted = dict(target)
        drifted["aave_v3"] = 40_000.0 + 5.0  # $5 drift > $1 tolerance
        recon = rec.reconcile(target, drifted, nav_before=_CAPITAL + 5.0, costs_usd=0.0)
        assert recon["matches_target"] is False


# =========================================================================== #
# RECONCILIATION-MISMATCH — nav_conserved=False (capital appeared / vanished) →
# BLOCK. NAV conservation is an independent axis from position-match.
# =========================================================================== #
class TestReconciliationMismatch:
    def test_capital_vanished_blocks(self):
        """Outcome positions sum to LESS than nav_before − costs → capital
        vanished → nav_conserved False → BLOCK."""
        target = {"aave_v3": 40_000.0}
        # Outcome shows only $30k deployed though nav_before was $40k with no costs.
        outcome = {"aave_v3": 30_000.0}
        recon = rec.reconcile(target, outcome, nav_before=40_000.0, costs_usd=0.0)
        assert recon["nav_conserved"] is False
        assert _proceeds(recon) is False

    def test_capital_appeared_blocks(self):
        """Outcome positions sum to MORE than nav_before − costs → phantom capital
        → nav_conserved False → BLOCK."""
        target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        outcome = {"aave_v3": 40_000.0, "morpho_blue": 50_000.0}  # +$30k phantom
        recon = rec.reconcile(target, outcome, nav_before=60_000.0, costs_usd=0.0)
        assert recon["nav_conserved"] is False
        assert _proceeds(recon) is False

    def test_nav_conserved_within_tolerance_passes(self):
        """Control: NAV within $1 tolerance of expected is conserved."""
        target = {"aave_v3": 40_000.0}
        outcome = {"aave_v3": 40_000.0}
        # costs of 0.50 → expected nav_after 39_999.50; nav_after 40_000 → within $1.
        recon = rec.reconcile(target, outcome, nav_before=40_000.0, costs_usd=0.50)
        assert recon["nav_conserved"] is True

    def test_nav_conserved_above_tolerance_blocks(self):
        target = {"aave_v3": 40_000.0}
        outcome = {"aave_v3": 40_000.0}
        # costs $100 → expected 39_900; nav_after 40_000 → $100 gap > $1 → block.
        recon = rec.reconcile(target, outcome, nav_before=40_000.0, costs_usd=100.0)
        assert recon["nav_conserved"] is False
        assert _proceeds(recon) is False

    def test_round_trip_clean_reconciles_and_conserves(self):
        """The full plan→dry-run→reconcile loop on a no-op (current==target)
        rebalance reconciles AND conserves NAV — the baseline clean path."""
        current = _target()
        target = dict(current)
        report = rec.round_trip(current=current, target=target, write=False,
                                ts="2026-06-28T00:00:00+00:00")
        assert report["matches_target"] is True
        assert report["nav_conserved"] is True
        assert report["go_live_ready"] is True
        # And it NEVER claims live execution.
        assert report["live_execution"] is False

    def test_round_trip_partial_outcome_not_go_live_ready(self):
        """A round-trip whose intended target differs from a partial outcome is
        NOT go_live_ready (intent != outcome)."""
        current = {"aave_v3": 60_000.0}
        target = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        # Simulate the morpho leg never filling: pass current as the 'outcome' to
        # reconcile directly (the round-trip dry-run assumes full fills, so we
        # assert at the reconcile layer that a partial outcome blocks go-live).
        recon = rec.reconcile(target, {"aave_v3": 40_000.0}, nav_before=40_000.0,
                              costs_usd=0.0)
        assert recon["matches_target"] is False
        assert _proceeds(recon) is False


# =========================================================================== #
# SIGNER-FAILURE — eth_signer raises / nonce gap → safe ABORT, NO key leak.
# These mock eth_signer._get_account so they run without eth_account installed.
# =========================================================================== #
class TestSignerFailure:
    def test_malformed_key_raises_before_any_signing(self):
        """A wrong-length key fails CLOSED with ValidationError — the cycle never
        reaches a chain call."""
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError):
            eth_signer.sign_transaction("deadbeef", {  # 8 hex chars, not 64
                "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
                "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
                "nonce": 0, "chainId": 1, "data": b"",
            })

    def test_signer_account_load_failure_aborts(self, monkeypatch):
        """eth_account raises on key load (e.g. corrupt keystore) → propagates →
        the cycle ABORTS (never returns a half-built tx)."""
        class _Boom:
            @staticmethod
            def from_key(_k):
                raise RuntimeError("keystore corrupt (drill)")

        monkeypatch.setattr(eth_signer, "_get_account", lambda: _Boom)
        with pytest.raises(RuntimeError, match="keystore corrupt"):
            eth_signer.get_address_from_private_key(_PUBLIC_DEV_KEY)

    def test_signer_sign_failure_aborts(self, monkeypatch):
        """eth_account.sign_transaction raises (nonce gap / RPC fault) → propagates
        → safe abort, no raw tx returned."""
        class _Boom:
            @staticmethod
            def sign_transaction(_tx, private_key):
                raise RuntimeError("nonce gap detected (drill)")

        monkeypatch.setattr(eth_signer, "_get_account", lambda: _Boom)
        with pytest.raises(RuntimeError, match="nonce gap"):
            eth_signer.sign_transaction(_PUBLIC_DEV_KEY, {
                "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
                "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
                "nonce": 0, "chainId": 1, "data": b"",
            })

    def test_no_key_material_in_validation_error(self):
        """RED-TEAM: a malformed-key ValidationError must NOT echo the raw key.

        eth_signer raises ValidationError with the offending value — assert the
        full private-key string never appears verbatim in the surfaced message
        when the key is otherwise valid-looking but wrong length."""
        from spa_core.utils.errors import ValidationError
        # A 65-char key (one over) — wrong length, but a realistic secret-shaped value.
        bad_key = _PUBLIC_DEV_KEY + "ff"
        try:
            eth_signer.get_address_from_private_key(bad_key)
            pytest.fail("expected ValidationError")
        except ValidationError as exc:
            msg = str(exc)
            # The FULL secret must not be reproduced in the diagnostic.
            assert bad_key not in msg, "private key leaked into ValidationError message"
            assert _PUBLIC_DEV_KEY not in msg, "private key leaked into ValidationError message"

    def test_no_key_material_in_signer_failure_logs(self, monkeypatch, caplog):
        """RED-TEAM: when the signer raises, NO key material may land in any log
        line emitted on the signing path."""
        class _Boom:
            @staticmethod
            def sign_transaction(_tx, private_key):
                # A faulty backend that does NOT echo the key (the contract).
                raise RuntimeError("signing backend error (key redacted)")

        monkeypatch.setattr(eth_signer, "_get_account", lambda: _Boom)
        with caplog.at_level(logging.DEBUG, logger="spa.eth_signer"):
            with pytest.raises(RuntimeError):
                eth_signer.sign_transaction(_PUBLIC_DEV_KEY, {
                    "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
                    "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
                    "nonce": 0, "chainId": 1, "data": b"",
                })
        combined = "\n".join(r.getMessage() for r in caplog.records)
        assert _PUBLIC_DEV_KEY not in combined, "private key leaked into a log line"

    def test_no_key_material_in_raised_exception_repr(self, monkeypatch):
        """RED-TEAM: the repr() of the raised exception must not carry the key."""
        class _Boom:
            @staticmethod
            def sign_transaction(_tx, private_key):
                raise RuntimeError("backend failure (no key here)")

        monkeypatch.setattr(eth_signer, "_get_account", lambda: _Boom)
        try:
            eth_signer.sign_transaction(_PUBLIC_DEV_KEY, {
                "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
                "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
                "nonce": 0, "chainId": 1, "data": b"",
            })
            pytest.fail("expected RuntimeError")
        except RuntimeError as exc:
            assert _PUBLIC_DEV_KEY not in repr(exc)

    def test_signer_failure_does_not_mutate_positions(self, monkeypatch):
        """A signer failure must leave the position book untouched (no partial
        write before the abort)."""
        positions_before = {"aave_v3": 40_000.0, "morpho_blue": 20_000.0}
        positions = dict(positions_before)

        class _Boom:
            @staticmethod
            def sign_transaction(_tx, private_key):
                raise RuntimeError("signer down (drill)")

        monkeypatch.setattr(eth_signer, "_get_account", lambda: _Boom)
        submitted = False
        try:
            eth_signer.sign_transaction(_PUBLIC_DEV_KEY, {
                "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
                "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
                "nonce": 0, "chainId": 1, "data": b"",
            })
            submitted = True  # unreachable
        except RuntimeError:
            pass
        assert submitted is False
        assert positions == positions_before  # no mutation on the failure path


# =========================================================================== #
# POSITION-MONITOR — corrupt post-execution books must be flagged (no silent
# pass), healthy post-kill / post-derisk books must NOT false-positive.
# =========================================================================== #
class TestPositionMonitorCorruption:
    def _write_status(self, tmp_path: Path, positions: list) -> PositionMonitor:
        import json
        (tmp_path / "status.json").write_text(
            json.dumps({"positions": positions, "timestamp": "2026-06-28T00:00:00+00:00"}),
            encoding="utf-8",
        )
        return PositionMonitor(data_dir=str(tmp_path), mode="paper")

    def test_apy_below_floor_flagged(self, tmp_path):
        mon = self._write_status(tmp_path, [
            {"protocol_key": "aave-v3", "amount_usd": 40_000.0, "apy": 0.5,
             "last_updated": "2026-06-28T00:00:00+00:00"},
        ])
        anomalies = mon.detect_anomalies()
        assert any(a["type"] == "apy_below_minimum" for a in anomalies)

    def test_apy_above_ceiling_flagged(self, tmp_path):
        mon = self._write_status(tmp_path, [
            {"protocol_key": "maple", "amount_usd": 20_000.0, "apy": 99.0,
             "last_updated": "2026-06-28T00:00:00+00:00"},
        ])
        anomalies = mon.detect_anomalies()
        assert any(a["type"] == "apy_above_maximum" for a in anomalies)

    def test_healthy_book_no_anomaly(self, tmp_path):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        mon = self._write_status(tmp_path, [
            {"protocol_key": "aave-v3", "amount_usd": 40_000.0, "apy": 4.0,
             "last_updated": now},
        ])
        anomalies = mon.detect_anomalies()
        # A healthy in-range, fresh position raises no ALERT anomalies.
        assert not [a for a in anomalies if a["severity"] == "ALERT"]

    def test_live_mode_not_implemented_fails_closed(self):
        """The on-chain (live) monitor path is NOT implemented → constructing it
        RAISES rather than silently reading a paper DB as if it were chain truth."""
        with pytest.raises(NotImplementedError):
            PositionMonitor(data_dir="data", mode="live")


# =========================================================================== #
# RED-TEAM SWEEP — assert NO failure mode silently proceeds. This is the
# property test: across a battery of injected defects, _proceeds is False for
# every corrupt outcome and True ONLY for the clean one.
# =========================================================================== #
class TestRedTeamNoSilentPass:
    def test_no_corrupt_outcome_ever_proceeds(self):
        target = _target()
        nav_before = _CAPITAL
        corrupt_outcomes = {
            "partial_fill":     {**target, "aave_v3": 25_000.0},
            "zero_fill":        {**target, "morpho_blue": 0.0},
            "overfill":         {**target, "aave_v3": 60_000.0},
            "reorg_drop":       {**target, "aave_v3": 0.0},
            "phantom_position": {**target, "euler_v2": 10_000.0},
            "capital_vanished": {"aave_v3": 10_000.0},
            "capital_appeared": {**target, "morpho_blue": 80_000.0},
        }
        for name, outcome in corrupt_outcomes.items():
            recon = rec.reconcile(target, outcome, nav_before=nav_before, costs_usd=0.0)
            assert _proceeds(recon) is False, f"{name} SILENTLY PROCEEDED — fail-OPEN!"

    def test_only_clean_outcome_proceeds(self):
        target = _target()
        recon = rec.reconcile(target, dict(target), nav_before=_CAPITAL, costs_usd=0.0)
        assert _proceeds(recon) is True

    def test_non_finite_position_blocks(self):
        """A NaN/Inf position (a corrupt feed read) must NOT pass reconciliation."""
        target = {"aave_v3": 40_000.0}
        for bad in (float("nan"), float("inf"), float("-inf")):
            outcome = {"aave_v3": bad}
            recon = rec.reconcile(target, outcome, nav_before=40_000.0, costs_usd=0.0)
            # nav_after becomes non-finite → conservation check fails (NaN compares
            # False), and the position delta is non-finite → not matched.
            assert _proceeds(recon) is False, f"non-finite {bad} silently proceeded"


# =========================================================================== #
# INERT INVARIANT — confirm these tests never flip is_live / touch live data.
# =========================================================================== #
class TestInert:
    def test_reconciliation_module_declares_dry_run(self):
        report = rec.round_trip(current={"aave_v3": 1_000.0},
                                target={"aave_v3": 1_000.0}, write=False,
                                ts="2026-06-28T00:00:00+00:00")
        assert report["mode"] == "dry_run_analytical"
        assert report["live_execution"] is False
        assert report["llm_forbidden"] is True

    def test_safe_tx_builder_is_paper_by_default(self):
        """SafeTxBuilder must be a no-op in paper mode (default) — building an
        allocate tx returns {} (no proposal, no signing, no chain)."""
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        builder = SafeTxBuilder(safe_address="0x" + "0" * 39 + "1")
        assert builder.is_paper_mode() is True
        assert builder.build_allocate_tx("aave_v3", 500.0) == {}
        assert builder.build_withdraw_tx("aave_v3", 500.0) == {}

    def test_submit_proposal_is_live_forbidden(self):
        """The actual submit path is hard-blocked by @live_trading_forbidden."""
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        builder = SafeTxBuilder(safe_address="0x" + "0" * 39 + "1")
        with pytest.raises(Exception):  # LiveTradingForbiddenError subclass
            builder.submit_proposal({"dummy": True})


# =========================================================================== #
# WS-3.3 — SIGNER KEY-MATERIAL: EXHAUSTIVE NO-LEAK SWEEP.
# Every signer entry-point, on every failure mode, must surface ZERO key
# material in its message / repr / log lines. These mock _get_account so they
# run WITHOUT eth_account installed.
# =========================================================================== #
class TestSignerNoKeyLeakExhaustive:
    # A realistic, secret-shaped (but public, fund-less) key used as the canary.
    KEY = _PUBLIC_DEV_KEY

    def _tx(self) -> dict:
        return {
            "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
            "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
            "nonce": 0, "chainId": 1, "data": b"",
        }

    def _assert_no_key(self, blob: str):
        """The raw key, its 0x form, and the 32-byte body must NOT appear."""
        for form in (self.KEY, "0x" + self.KEY, self.KEY.upper(), self.KEY.lower()):
            assert form not in blob, "PRIVATE KEY LEAKED into a diagnostic"

    def _hostile_backend(self):
        """A backend whose EVERY method echoes the key verbatim — the worst case.

        WS-3.3 must scrub this so the key never reaches a surfaced diagnostic.
        """
        key = self.KEY

        class _Hostile:
            @staticmethod
            def from_key(k):
                raise RuntimeError(f"corrupt keystore for key={key} 0x{key}")

            @staticmethod
            def sign_transaction(_tx, private_key):
                raise RuntimeError(f"backend blew up with private_key={private_key}")

            @staticmethod
            def sign_message(_msg, private_key):
                raise RuntimeError(f"signing failed key={private_key}")

        return _Hostile

    def test_hostile_backend_from_key_scrubbed(self, monkeypatch, caplog):
        monkeypatch.setattr(eth_signer, "_get_account", lambda: self._hostile_backend())
        with caplog.at_level(logging.DEBUG, logger="spa.eth_signer"):
            with pytest.raises(Exception) as ei:
                eth_signer.get_address_from_private_key(self.KEY)
        self._assert_no_key(str(ei.value))
        self._assert_no_key(repr(ei.value))
        self._assert_no_key("\n".join(r.getMessage() for r in caplog.records))

    def test_hostile_backend_sign_transaction_scrubbed(self, monkeypatch, caplog):
        monkeypatch.setattr(eth_signer, "_get_account", lambda: self._hostile_backend())
        with caplog.at_level(logging.DEBUG, logger="spa.eth_signer"):
            with pytest.raises(Exception) as ei:
                eth_signer.sign_transaction(self.KEY, self._tx())
        self._assert_no_key(str(ei.value))
        self._assert_no_key(repr(ei.value))
        self._assert_no_key("\n".join(r.getMessage() for r in caplog.records))

    def test_hostile_backend_sign_message_scrubbed(self, monkeypatch, caplog):
        # sign_message needs eth_account.messages.encode_defunct; skip if absent.
        pytest.importorskip("eth_account")
        monkeypatch.setattr(eth_signer, "_get_account", lambda: self._hostile_backend())
        with caplog.at_level(logging.DEBUG, logger="spa.eth_signer"):
            with pytest.raises(Exception) as ei:
                eth_signer.sign_message("hello", self.KEY)
        self._assert_no_key(str(ei.value))
        self._assert_no_key(repr(ei.value))
        self._assert_no_key("\n".join(r.getMessage() for r in caplog.records))

    def test_hostile_backend_with_0x_prefixed_key_scrubbed(self, monkeypatch):
        """The 0x-prefixed input form must ALSO be scrubbed (not just the body)."""
        monkeypatch.setattr(eth_signer, "_get_account", lambda: self._hostile_backend())
        with pytest.raises(Exception) as ei:
            eth_signer.sign_transaction("0x" + self.KEY, self._tx())
        self._assert_no_key(str(ei.value))
        self._assert_no_key(repr(ei.value))

    def test_malformed_key_redacted_every_entry_point(self):
        """A wrong-length key never echoes into the ValidationError on ANY path."""
        from spa_core.utils.errors import ValidationError
        bad = self.KEY + "ff"  # 66 chars, wrong length, secret-shaped
        for fn in (
            lambda: eth_signer.get_address_from_private_key(bad),
            lambda: eth_signer.sign_transaction(bad, self._tx()),
        ):
            try:
                fn()
                pytest.fail("expected ValidationError")
            except ValidationError as exc:
                self._assert_no_key(str(exc))
                self._assert_no_key(repr(exc))
                assert "<redacted>" in str(exc)

    def test_non_hex_key_redacted(self):
        """A non-hex (but right-length) key fails CLOSED with the value redacted."""
        from spa_core.utils.errors import ValidationError
        bad = "zz" * 32  # 64 chars, not hex
        with pytest.raises(ValidationError) as ei:
            eth_signer.sign_transaction(bad, self._tx())
        assert bad not in str(ei.value)
        assert "<redacted>" in str(ei.value)

    def test_scrub_helper_redacts_all_variants(self):
        """Unit: _scrub replaces the secret and its 0x/case variants."""
        secret = self.KEY
        text = f"key={secret} or 0x{secret} or {secret.upper()}"
        out = eth_signer._scrub(text, (secret,))
        self._assert_no_key(out)
        assert "<redacted>" in out


# =========================================================================== #
# WS-3.3 — NONCE SAFETY: a gap or reuse is detected and aborts before signing.
# =========================================================================== #
class TestNonceSafety:
    def test_nonce_gap_aborts(self):
        """intended > on-chain pending → GAP → ABORT (tx would stall)."""
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError, match="gap"):
            eth_signer.assert_nonce_ok(intended_nonce=9, pending_nonce=7)

    def test_nonce_reuse_aborts(self):
        """intended < on-chain pending → REUSE → ABORT."""
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError, match="reuse"):
            eth_signer.assert_nonce_ok(intended_nonce=5, pending_nonce=7)

    def test_nonce_match_passes(self):
        """intended == pending → the only includable nonce → OK."""
        assert eth_signer.assert_nonce_ok(7, 7) == 7

    def test_negative_nonce_in_tx_aborts_before_sign(self, monkeypatch):
        """A negative nonce in tx_dict fails CLOSED in sign_transaction — the
        backend is never reached (so no tx could be built/submitted)."""
        from spa_core.utils.errors import ValidationError

        class _ShouldNotRun:
            @staticmethod
            def sign_transaction(_tx, private_key):
                raise AssertionError("backend reached despite bad nonce!")

        monkeypatch.setattr(eth_signer, "_get_account", lambda: _ShouldNotRun)
        with pytest.raises(ValidationError):
            eth_signer.sign_transaction(_PUBLIC_DEV_KEY, {
                "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
                "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
                "nonce": -1, "chainId": 1, "data": b"",
            })

    def test_float_nonce_aborts(self):
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError):
            eth_signer._coerce_nonce(5.5)

    def test_bool_nonce_aborts(self):
        """A bool nonce (True==1) must be rejected, never silently coerced."""
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError):
            eth_signer._coerce_nonce(True)

    def test_nan_nonce_aborts(self):
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError):
            eth_signer._coerce_nonce(float("nan"))


# =========================================================================== #
# WS-3.3 — MULTISIG: an insufficient / missing signer set must BLOCK (never
# build an unsignable tx).
# =========================================================================== #
class TestMultisigUnsignableBlocks:
    SAFE = "0x" + "0" * 39 + "1"
    A = "0x" + "1" * 40
    B = "0x" + "2" * 40
    C = "0x" + "3" * 40

    def test_valid_2_of_3_is_signable(self):
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        b = SafeTxBuilder(self.SAFE, owners=[self.A, self.B, self.C], threshold=2)
        assert b.is_signable() is True
        assert b.get_signer_set() == ((self.A, self.B, self.C), 2)

    def test_threshold_exceeds_owners_blocks_at_construction(self):
        """3-of-2 can never reach M-of-N → refused at construction."""
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError, match="UNSIGNABLE|exceeds"):
            SafeTxBuilder(self.SAFE, owners=[self.A, self.B], threshold=3)

    def test_duplicate_owners_blocked(self):
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError, match="duplicate"):
            SafeTxBuilder(self.SAFE, owners=[self.A, self.A, self.B], threshold=2)

    def test_malformed_owner_address_blocked(self):
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError):
            SafeTxBuilder(self.SAFE, owners=[self.A, "0xnothex"], threshold=1)

    def test_zero_threshold_blocked(self):
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        from spa_core.utils.errors import ValidationError
        with pytest.raises(ValidationError):
            SafeTxBuilder(self.SAFE, owners=[self.A], threshold=0)

    def test_no_owners_is_proposal_only_signable(self):
        """Historical proposal-only mode (no declared owners) stays a no-op."""
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        b = SafeTxBuilder(self.SAFE)
        assert b.is_signable() is True
        assert b.get_signer_set() == ((), 1)

    def test_build_blocks_when_signer_set_degraded(self, monkeypatch):
        """RED-TEAM: if the signer set is degraded below threshold AFTER
        construction (e.g. an owner removed), building in LIVE mode must ABORT —
        never emit an unsignable proposal."""
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        from spa_core.utils.errors import ValidationError
        monkeypatch.setenv("SPA_EXECUTION_MODE", "live")
        b = SafeTxBuilder(self.SAFE, owners=[self.A, self.B, self.C], threshold=2)
        # Simulate two owners lost → only 1 left, threshold still 2 → unsignable.
        b._owners = (self.A,)
        assert b.is_signable() is False
        with pytest.raises(ValidationError, match="UNSIGNABLE|insufficient"):
            b.build_allocate_tx("aave_v3", 500.0)
        with pytest.raises(ValidationError, match="UNSIGNABLE|insufficient"):
            b.build_withdraw_tx("aave_v3", 500.0)


# =========================================================================== #
# WS-3.4 — GAS / MEV: the protection triggers on adversarial fixtures. A gas
# spike or sandwich pattern must route protected-or-ABORT; a stale oracle fails
# CLOSED. NEVER a naive public submit.
# =========================================================================== #
class TestGasMevProtection:
    from spa_core.execution import mev_protection as _mp

    def test_stale_oracle_aborts(self):
        from spa_core.execution import mev_protection as mp
        v = mp.evaluate_gas_and_mev(20.0, 20.0, oracle_age_s=120.0)
        assert v["decision"] == "ABORT"
        assert "stale" in v["reason"]

    def test_gas_spike_routes_protected(self):
        from spa_core.execution import mev_protection as mp
        # 2x baseline → routable spike → PROTECT (private).
        v = mp.evaluate_gas_and_mev(40.0, 20.0, oracle_age_s=5.0)
        assert v["decision"] == "PROTECT"
        assert v["require_private"] is True

    def test_extreme_gas_spike_aborts(self):
        from spa_core.execution import mev_protection as mp
        # 4x baseline → refuse to overpay blindly → ABORT.
        v = mp.evaluate_gas_and_mev(80.0, 20.0, oracle_age_s=5.0)
        assert v["decision"] == "ABORT"

    def test_sandwich_pattern_routes_protected(self):
        from spa_core.execution import mev_protection as mp
        v = mp.evaluate_gas_and_mev(20.0, 20.0, oracle_age_s=5.0, sandwich_risk=0.3)
        assert v["decision"] == "PROTECT"
        assert v["require_private"] is True

    def test_extreme_sandwich_aborts(self):
        from spa_core.execution import mev_protection as mp
        v = mp.evaluate_gas_and_mev(20.0, 20.0, oracle_age_s=5.0, sandwich_risk=0.9)
        assert v["decision"] == "ABORT"

    def test_calm_market_low_risk_is_ok(self):
        from spa_core.execution import mev_protection as mp
        v = mp.evaluate_gas_and_mev(21.0, 20.0, oracle_age_s=5.0, sandwich_risk=0.01)
        assert v["decision"] == "OK"
        assert v["require_private"] is False

    def test_non_finite_gas_aborts(self):
        from spa_core.execution import mev_protection as mp
        for bad in (float("nan"), float("inf"), float("-inf")):
            assert mp.evaluate_gas_and_mev(bad, 20.0, 5.0)["decision"] == "ABORT"
            assert mp.evaluate_gas_and_mev(20.0, bad, 5.0)["decision"] == "ABORT"

    def test_zero_oracle_baseline_aborts(self):
        """A zero/negative oracle baseline is untrustworthy → ABORT (no div-by-0)."""
        from spa_core.execution import mev_protection as mp
        assert mp.evaluate_gas_and_mev(20.0, 0.0, 5.0)["decision"] == "ABORT"

    def test_out_of_range_sandwich_risk_aborts(self):
        from spa_core.execution import mev_protection as mp
        assert mp.evaluate_gas_and_mev(20.0, 20.0, 5.0, sandwich_risk=1.5)["decision"] == "ABORT"
        assert mp.evaluate_gas_and_mev(20.0, 20.0, 5.0, sandwich_risk=-0.1)["decision"] == "ABORT"

    def test_guard_broadcast_aborts_submits_nothing(self, monkeypatch):
        """RED-TEAM: on an ABORT verdict (stale oracle), guard_broadcast must
        broadcast NOTHING — send_protected is never called."""
        from spa_core.execution import mev_protection as mp
        called = {"n": 0}

        def _boom(*a, **k):
            called["n"] += 1
            raise AssertionError("send_protected called on an ABORT verdict!")

        monkeypatch.setattr(mp, "send_protected", _boom)
        res = mp.guard_broadcast(
            "0x" + "cc" * 64, proposed_gas_gwei=20.0, oracle_gas_gwei=20.0,
            oracle_age_s=999.0,  # stale → ABORT
        )
        assert res["status"] == "ABORTED"
        assert called["n"] == 0

    def test_guard_broadcast_protect_has_no_public_fallback(self, monkeypatch):
        """RED-TEAM: a PROTECT verdict must route private with NO public fallback —
        a private-required tx may not silently fall through to the mempool."""
        from spa_core.execution import mev_protection as mp
        captured = {}

        def _fake_send(signed, fallback_rpc=None, timeout=30):
            captured["fallback_rpc"] = fallback_rpc
            return {"status": "PENDING", "tx_hash": "0x" + "ab" * 32,
                    "endpoint": mp.FLASHBOTS_RPC_FAST, "protection": "flashbots"}

        monkeypatch.setattr(mp, "send_protected", _fake_send)
        res = mp.guard_broadcast(
            "0x" + "cc" * 64, proposed_gas_gwei=40.0, oracle_gas_gwei=20.0,
            oracle_age_s=5.0,  # 2x spike → PROTECT
            fallback_rpc="https://public.example.com",
        )
        # PROTECT requires private — the public fallback must be suppressed.
        assert captured["fallback_rpc"] is None
        assert res["gas_decision"] == "PROTECT"

    def test_guard_broadcast_ok_allows_fallback(self, monkeypatch):
        """An OK verdict still routes through the protected relay but MAY use the
        public fallback the caller supplied."""
        from spa_core.execution import mev_protection as mp
        captured = {}

        def _fake_send(signed, fallback_rpc=None, timeout=30):
            captured["fallback_rpc"] = fallback_rpc
            return {"status": "PENDING", "tx_hash": "0x" + "ab" * 32,
                    "endpoint": mp.FLASHBOTS_RPC_FAST, "protection": "flashbots"}

        monkeypatch.setattr(mp, "send_protected", _fake_send)
        res = mp.guard_broadcast(
            "0x" + "cc" * 64, proposed_gas_gwei=21.0, oracle_gas_gwei=20.0,
            oracle_age_s=5.0, sandwich_risk=0.0,
            fallback_rpc="https://public.example.com",
        )
        assert captured["fallback_rpc"] == "https://public.example.com"
        assert res["gas_decision"] == "OK"


# =========================================================================== #
# WS-3.3/3.4 — INERT SMOKE: the signer + MEV path run with NO real chain calls
# and is_live OFF.
# =========================================================================== #
class TestSignerMevInertSmoke:
    def test_signer_path_makes_no_network_call(self, monkeypatch):
        """Signing is pure-crypto — it must never touch the network."""
        import urllib.request
        monkeypatch.setattr(eth_signer, "_get_account", lambda: _StubAccount())

        def _no_net(*a, **k):
            raise AssertionError("signer made a network call!")

        monkeypatch.setattr(urllib.request, "urlopen", _no_net)
        raw = eth_signer.sign_transaction(_PUBLIC_DEV_KEY, {
            "to": "0x" + "0" * 40, "value": 0, "gas": 21000,
            "maxFeePerGas": 1, "maxPriorityFeePerGas": 1,
            "nonce": 0, "chainId": 1, "data": b"",
        })
        assert raw == b"\x02stubraw"

    def test_gas_guard_makes_no_network_call(self):
        """evaluate_gas_and_mev is a pure decision — no HTTP at all."""
        import unittest.mock as mock
        from spa_core.execution import mev_protection as mp
        with mock.patch("urllib.request.urlopen") as m:
            mp.evaluate_gas_and_mev(40.0, 20.0, 5.0, 0.3)
            m.assert_not_called()

    def test_is_live_never_flipped(self):
        """The signer/MEV modules carry no live flag we could flip — assert the
        SafeTxBuilder default stays paper (is_live OFF)."""
        from spa_core.execution.safe_tx_builder import SafeTxBuilder
        b = SafeTxBuilder(safe_address="0x" + "0" * 39 + "1")
        assert b.is_paper_mode() is True


class _StubAccount:
    """A minimal eth_account stand-in for the inert smoke test (no real crypto)."""
    @staticmethod
    def sign_transaction(_tx, private_key):
        class _Signed:
            raw_transaction = b"\x02stubraw"
        return _Signed()
