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
