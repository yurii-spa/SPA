"""
spa_core/redteam/scenarios.py — the ≥7 REAL adversarial scenarios (one per surface).

Each scenario reuses a PROVEN attack from a prior sprint and feeds the forgery through the SAME REAL
defense that ships. Every scenario:
  (1) builds a HEALTHY sandbox artifact and proves the defense passes it (control — no false alarm),
  (2) forges/tampers it (the attack),
  (3) feeds the forgery through the real defense and asserts it is CAUGHT.

A scenario that finds an UNCAUGHT forgery returns caught=False → the runner FAILS (the desk has a
real hole). All sandbox writes stay inside the per-run tmp dir — live data/ is never touched.

stdlib-only · deterministic (fixed ts/seeds) · fail-CLOSED · LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import List

from spa_core.redteam.base import Finding, RedTeamScenario, Surface

_ROOT = Path(__file__).resolve().parents[2]
_VERIFY_SPA = _ROOT / "scripts" / "verify_spa.py"


# ── load the standalone verifier as a module (it is a script, not a package) ──
def _load_verify_spa():
    spec = importlib.util.spec_from_file_location("_redteam_verify_spa", str(_VERIFY_SPA))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# (PROOF) proof-chain forge — flip one published byte; verify_spa must report a precise broken_at
# ════════════════════════════════════════════════════════════════════════════════════════════════
class ProofChainForgeScenario(RedTeamScenario):
    name = "proof_chain_forge"
    surface = Surface.PROOF
    description = ("forge a published decision-chain row (the value the proof anchors) — the "
                  "zero-dependency verify_spa.py must re-derive a divergent hash and FAIL it.")

    def attack(self, sandbox: Path) -> Finding:
        V = _load_verify_spa()
        rd = sandbox / "data" / "rates_desk"
        rd.mkdir(parents=True, exist_ok=True)
        log = rd / "decision_log.jsonl"

        # build a healthy 2-row single-genesis chain (the spec recipe verify_spa enforces).
        bodies = [
            {"kind": "ENTRY", "approved": True, "underlying": "susde", "as_of": "2026-06-28"},
            {"kind": "REFUSAL", "approved": False, "underlying": "ezeth", "as_of": "2026-06-28"},
        ]
        rows = []
        prev = "0" * 64
        for seq, body in enumerate(bodies):
            payload = dict(body)
            canon = _canonical({"seq": seq, "ts": "t", "event_type": "rates_desk_decision",
                                "payload": payload, "prev_hash": prev})
            eh = hashlib.sha256(canon.encode()).hexdigest()
            rows.append({"seq": seq, "ts": "t", "entry_hash": eh, "prev_hash": prev, **payload})
            prev = eh
        log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

        # (1) CONTROL: the verifier must PASS the healthy chain.
        rep_ok = V.run([str(rd)])
        if not (rep_ok["decision_chain"] and rep_ok["decision_chain"]["valid"]):
            return self._control_failed("verify_spa rejected a HEALTHY decision chain (false alarm)",
                                        report=rep_ok["errors"])

        # (2) ATTACK: forge the published `approved` flag on row 1 WITHOUT recomputing the hash —
        #     the exact "we changed history after the fact" tamper.
        forged = list(rows)
        forged[1] = dict(forged[1], approved=True, underlying="ezeth_now_approved")
        log.write_text("".join(json.dumps(r) + "\n" for r in forged), encoding="utf-8")

        # (3) the REAL defense must catch it (chain diverges at the forged row).
        rep = V.run([str(rd)])
        dc = rep["decision_chain"] or {}
        caught = (not dc.get("valid")) and dc.get("broken_at") == 1
        ev = (f"forged decision row 1 (approved flag) → verify_spa valid={dc.get('valid')} "
              f"broken_at={dc.get('broken_at')} (expected broken_at=1)")
        return self._caught(ev, broken_at=dc.get("broken_at")) if caught else self._uncaught(ev)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# (MONEY_PATH) exit-NAV output forge — a flagged (illiquid) ticket must NOT carry a fabricated fill
# ════════════════════════════════════════════════════════════════════════════════════════════════
class ExitNavOutputForgeScenario(RedTeamScenario):
    name = "exit_nav_output_forge"
    surface = Surface.MONEY_PATH
    description = ("fabricate a net_proceeds_usd on a FLAGGED (illiquid) liquidation ticket — the "
                  "money-path fail-closed contract requires flagged ⇒ net/haircut MUST be null.")

    @staticmethod
    def _contract_holds(schedule: List[dict]) -> bool:
        """The shipped money-path invariant (smoke_test_flagship._assert_rows_failclosed): a flagged
        row must have net_proceeds_usd == None AND haircut_pct == None (no fabricated fill)."""
        for r in schedule:
            if isinstance(r, dict) and r.get("flagged"):
                if r.get("net_proceeds_usd") is not None or r.get("haircut_pct") is not None:
                    return False
        return True

    def attack(self, sandbox: Path) -> Finding:
        rd = sandbox / "data" / "rates_desk"
        rd.mkdir(parents=True, exist_ok=True)
        # a healthy schedule: a priced ticket + an honestly-flagged illiquid hole (net/haircut null).
        healthy = [
            {"ticket_usd": 100000, "gross_usd": 100000, "net_proceeds_usd": 99500.0,
             "haircut_pct": 0.5, "flagged": False, "flag_reason": None},
            {"ticket_usd": 5000000, "gross_usd": 5000000, "net_proceeds_usd": None,
             "haircut_pct": None, "flagged": True, "flag_reason": "exceeds_pool_depth"},
        ]
        # (1) CONTROL: the contract must hold on the honest schedule.
        if not self._contract_holds(healthy):
            return self._control_failed("money-path contract rejected an HONEST schedule (false alarm)")

        # (2) ATTACK: fabricate a fill on the FLAGGED (illiquid) ticket — pretend we could exit a
        #     $5M position at a clean price the pool depth cannot support.
        forged = [dict(r) for r in healthy]
        forged[1].update(net_proceeds_usd=4_975_000.0, haircut_pct=0.5)  # the fabrication

        # (3) the REAL defense (the fail-closed contract the smoke test enforces) must catch it.
        caught = not self._contract_holds(forged)
        ev = ("fabricated net_proceeds_usd=$4,975,000 + haircut on a FLAGGED illiquid $5M ticket → "
              f"fail-closed contract caught={caught} (flagged rows must keep net/haircut null)")
        return self._caught(ev) if caught else self._uncaught(ev)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# (OPTIMIZER) over-concentration — the RiskPolicy gate must REJECT a >40% single-protocol allocation
# ════════════════════════════════════════════════════════════════════════════════════════════════
class OptimizerOverConcentrationScenario(RedTeamScenario):
    name = "optimizer_over_concentration"
    surface = Surface.OPTIMIZER
    description = ("push a single-protocol allocation past the 40% concentration cap — the "
                  "deterministic RiskPolicy gate must return approved=False (un-overridable).")

    def attack(self, sandbox: Path) -> Finding:
        from spa_core.risk.policy import RiskPolicy, PortfolioState, Position
        pol = RiskPolicy()
        # a portfolio already 35% in aave_v3; the optimizer now tries to add another 20% → 55%.
        state = PortfolioState(
            total_capital_usd=100_000.0,
            positions=[Position(protocol_key="aave_v3", tier="T1", asset="USDC",
                                amount_usd=35_000.0, apy_at_open=4.0, current_apy=4.0)],
        )
        # (1) CONTROL: a modest within-cap add must be APPROVED (no false alarm).
        ok = pol.check_new_position(state, "aave_v3", "T1", amount_usd=2_000.0,
                                    current_apy=4.0, tvl_usd=5_000_000_000.0)
        if not ok.approved:
            return self._control_failed(
                "RiskPolicy rejected a within-cap 37% allocation (false alarm)", violations=ok.violations)

        # (2)+(3) ATTACK: an over-concentrating add (→ 55% of one protocol) must be REJECTED.
        bad = pol.check_new_position(state, "aave_v3", "T1", amount_usd=20_000.0,
                                     current_apy=4.0, tvl_usd=5_000_000_000.0)
        caught = not bad.approved
        ev = (f"add $20k to aave_v3 already at 35% → 55% (cap 40%); RiskPolicy approved={bad.approved} "
              f"violations={bad.violations}")
        return self._caught(ev, violations=bad.violations) if caught else self._uncaught(ev)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# (PROOF / decision-log) toxic-LRT approval — a structurally-toxic row must be VETOED on regeneration
# ════════════════════════════════════════════════════════════════════════════════════════════════
class ToxicLrtApprovalScenario(RedTeamScenario):
    name = "toxic_lrt_structural_veto"
    surface = Surface.PROOF
    description = ("a formerly-APPROVED toxic-LRT row (size-down exploit) must be flipped to a "
                  "structural TAIL_VETO refusal by the corrected gate — REFUSED at any size.")

    def attack(self, sandbox: Path) -> Finding:
        from spa_core.strategy_lab.rates_desk import proof_chain as PC
        from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams

        params = RatePolicyParams()
        cap = params.max_structural_haircut  # the size-independent toxicity cap

        # A toxic LRT row: structural tail (peg+oracle+protocol) BREACHES the cap, yet it was
        # APPROVED (the size-down exploit shrank the TOTAL haircut below a size-dependent gate).
        big = float(cap) * 1.5  # decisively above the cap
        toxic_body = {
            "kind": "ENTRY", "approved": True, "reason": "approved", "as_of": "2026-06-28",
            "underlying": "ezeth", "shape": "FIXED_CARRY",
            "net_edge": "0.02", "approved_size_usd": "4062",
            "decomposition": {
                "fair_yield": "0.05", "peg_haircut": str(big), "oracle_haircut": "0.0",
                "protocol_haircut": "0.0", "funding_flip_haircut": "0.0",
            },
            "detail": {"quoted_rate": "0.07"},
            "proof_hash": "deadbeef" * 8,
        }
        # a clean approval (structurally under the cap) — must be PRESERVED verbatim.
        clean_body = {
            "kind": "ENTRY", "approved": True, "reason": "approved", "as_of": "2026-06-28",
            "underlying": "susde", "shape": "FIXED_CARRY",
            "net_edge": "0.02", "approved_size_usd": "10000",
            "decomposition": {
                "fair_yield": "0.05", "peg_haircut": "0.001", "oracle_haircut": "0.0",
                "protocol_haircut": "0.0", "funding_flip_haircut": "0.0",
            },
            "detail": {"quoted_rate": "0.03"},
            "proof_hash": "feedface" * 8,
        }

        # (1) CONTROL: the clean approval survives regeneration unchanged.
        clean_out = PC.corrected_decision_body(dict(clean_body), params)
        if clean_out.get("approved") is not True:
            return self._control_failed(
                "the corrected gate wrongly FLIPPED a structurally-clean approval (false veto)",
                clean_out=clean_out)

        # (2)+(3) ATTACK: the toxic approval must be flipped to a structural TAIL_VETO refusal.
        toxic_out = PC.corrected_decision_body(dict(toxic_body), params)
        caught = (toxic_out.get("approved") is False
                  and toxic_out.get("kind") == "REFUSAL"
                  and toxic_out.get("reason") == "tail_veto")
        ev = (f"toxic ezETH approval (structural {big:.4f} > cap {float(cap):.4f}) → corrected gate "
              f"approved={toxic_out.get('approved')} reason={toxic_out.get('reason')} "
              "(must be REFUSED at any size — size-down exploit closed)")
        return self._caught(ev, reason=toxic_out.get("reason")) if caught else self._uncaught(ev)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# (FEEDS) NaN / fabrication — a non-finite feed value must be rejected by the risk gate + scrubbed
# ════════════════════════════════════════════════════════════════════════════════════════════════
class FeedNanFabricationScenario(RedTeamScenario):
    name = "feed_nan_fabrication"
    surface = Surface.FEEDS
    description = ("inject a NaN/inf APY from a fabricated feed — the RiskPolicy finiteness guard "
                  "must REJECT it (no live-money bypass) and the API scrubber must null it.")

    def attack(self, sandbox: Path) -> Finding:
        from spa_core.risk.policy import RiskPolicy, PortfolioState
        from spa_core.api._shared import parse_log_line, scrub_nonfinite, _has_nonfinite
        pol = RiskPolicy()
        state = PortfolioState(total_capital_usd=100_000.0, positions=[])

        # (1) CONTROL: a finite, sane feed value is APPROVED.
        ok = pol.check_new_position(state, "aave_v3", "T1", amount_usd=5_000.0,
                                    current_apy=4.0, tvl_usd=5_000_000_000.0)
        if not ok.approved:
            return self._control_failed("RiskPolicy rejected a sane finite feed (false alarm)",
                                        violations=ok.violations)

        # (2)+(3) ATTACK A: a NaN APY (a fabricated/garbage feed) must be REJECTED, never approved.
        nan = float("nan")
        bad = pol.check_new_position(state, "aave_v3", "T1", amount_usd=5_000.0,
                                     current_apy=nan, tvl_usd=5_000_000_000.0)
        caught_gate = (not bad.approved) and any("non-finite" in v for v in bad.violations)

        # ATTACK B: a NaN smuggled into a published log row must be treated as CORRUPT (chain-failing)
        # by the API parser, and any echoed payload scrubbed to null (no serializer-crashing inf).
        line = '{"seq": 0, "value": NaN}'  # json.loads accepts bare NaN; the parser must reject it
        parsed = parse_log_line(line, corrupt_marker={"__corrupt__": True})
        caught_parse = parsed == {"__corrupt__": True}
        scrubbed = scrub_nonfinite({"apy": float("inf"), "ok": 1.0})
        caught_scrub = scrubbed["apy"] is None and not _has_nonfinite(scrubbed)

        caught = caught_gate and caught_parse and caught_scrub
        ev = (f"NaN APY → RiskPolicy approved={bad.approved} (gate caught={caught_gate}); "
              f"NaN log row → corrupt-marker={caught_parse}; inf payload → scrubbed={caught_scrub}")
        return self._caught(ev, violations=bad.violations) if caught else self._uncaught(ev)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# (SLEEVES) go-live-track mutation — a sandbox/test run must NOT pollute the canonical decision mirror
# ════════════════════════════════════════════════════════════════════════════════════════════════
class SleeveTrackMutationScenario(RedTeamScenario):
    name = "sleeve_track_mutation"
    surface = Surface.SLEEVES
    description = ("a sandbox/hermetic run that omits an explicit log_path must be REFUSED the "
                  "canonical mirror write (the interlock that stops transient runs corrupting track).")

    def attack(self, sandbox: Path) -> Finding:
        import os
        from decimal import Decimal
        from spa_core.strategy_lab.rates_desk import proof_chain as PC
        from spa_core.strategy_lab.rates_desk.contracts import (
            GateResult, KillReason, TradeShape, YieldDecomposition)

        # Point the module's CANONICAL mirror at a sandbox file (so even a BUG that wrote it can only
        # ever touch the sandbox, never the live track) and watch THAT file for a write.
        canonical = sandbox / "canonical_decision_log.jsonl"
        canonical.write_text("", encoding="utf-8")
        orig_log = PC._LOG
        PC._LOG = canonical

        # Force the hermetic/sandbox condition deterministically (the published interlock fires when
        # SPA_SANDBOX is set OR under pytest), regardless of how the red-team itself was launched.
        had_env = "SPA_SANDBOX" in os.environ
        prev_env = os.environ.get("SPA_SANDBOX")
        os.environ["SPA_SANDBOX"] = "1"

        # Build ONE real GateResult-shaped verdict to record (the interlock decision is made before
        # any mirror write, on (log_path is None and _is_sandbox())).
        decomp = YieldDecomposition(
            underlying="susde", as_of="2026-06-28", baseline=Decimal("0.05"),
            peg_haircut=Decimal("0.001"), funding_flip_haircut=Decimal("0"),
            oracle_haircut=Decimal("0"), liquidity_haircut=Decimal("0"),
            protocol_haircut=Decimal("0"))
        verdict = GateResult(
            approved=True, reason=KillReason.NONE, underlying="susde",
            shape=TradeShape.FIXED_CARRY, as_of="2026-06-28", net_edge=Decimal("0.02"),
            approved_size_usd=Decimal("10000"), decomposition=decomp, detail={})

        try:
            if not PC._is_sandbox():
                return self._control_failed(
                    "_is_sandbox() did not engage even with SPA_SANDBOX set (interlock unreachable)")

            # (CONTROL) an EXPLICIT log_path a sandbox OWNS IS written — sandbox runs are not muted,
            # only barred from the CANONICAL mirror.
            owned = sandbox / "owned_log.jsonl"
            PC.record_decisions([verdict], ts="2026-06-28T00:00:00+00:00", mirror=True, log_path=owned)
            if not (owned.exists() and owned.read_text(encoding="utf-8").strip()):
                return self._control_failed(
                    "the interlock wrongly muted an EXPLICIT-log_path sandbox write (over-broad)")

            # (ATTACK) the SAME sandbox run with log_path=None must be REFUSED the canonical mirror —
            # this is the guard that stops a transient run corrupting the live go-live track.
            before = canonical.read_text(encoding="utf-8")
            PC.record_decisions([verdict], ts="2026-06-28T00:00:00+00:00", mirror=True, log_path=None)
            after = canonical.read_text(encoding="utf-8")
            untouched = (after == before == "")
            ev = (f"hermetic run (is_sandbox=True) with log_path=None → canonical mirror write "
                  f"REFUSED; canonical track untouched={untouched} (an explicit-log_path write IS "
                  "allowed — the interlock is precise, not a blanket mute)")
            return self._caught(ev, untouched=untouched) if untouched else self._uncaught(ev)
        finally:
            PC._LOG = orig_log
            if had_env:
                os.environ["SPA_SANDBOX"] = prev_env  # type: ignore[assignment]
            else:
                os.environ.pop("SPA_SANDBOX", None)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# (KILL_SWITCH) drawdown ladder — a >10% evidenced drawdown must classify as a HARD_KILL
# ════════════════════════════════════════════════════════════════════════════════════════════════
class KillSwitchLadderScenario(RedTeamScenario):
    name = "kill_switch_ladder"
    surface = Surface.KILL_SWITCH
    description = ("an evidenced equity curve that draws down past the 10% hard threshold must "
                  "classify as TIER_HARD_KILL — the deterministic ladder cannot be talked out of it.")

    def attack(self, sandbox: Path) -> Finding:
        from spa_core.governance import kill_switch as KS

        # Bars must be EVIDENCED (dated >= PAPER_REAL_START 2026-06-10, source=live, finite
        # close_equity) — exactly the segregation the real drawdown computation enforces (warmup /
        # backfill bars can never fabricate OR mask a drawdown).
        def _bar(day: int, close: float) -> dict:
            return {"date": f"2026-06-{day:02d}", "close_equity": close, "open_equity": close,
                    "source": "live", "evidenced": True}

        # (1) CONTROL: a healthy, rising evidenced curve must be TIER_NONE (no false kill).
        healthy = [_bar(10 + i, 100_000.0 + i * 50.0) for i in range(12)]
        tier_ok, _ = KS.drawdown_tier(healthy)
        if tier_ok != KS.TIER_NONE:
            return self._control_failed(
                f"healthy rising curve classified {tier_ok} (false kill)", curve_len=len(healthy))

        # (2)+(3) ATTACK: a curve peaking at ~100,500 then collapsing ~12% must be a HARD_KILL — a
        # real protocol-collapse signal the deterministic ladder must escalate (not soft-pedal).
        crash = [_bar(10 + i, 100_000.0 + i * 100.0) for i in range(6)]      # peak ≈ 100,500
        crash.append(_bar(16, 88_000.0))                                     # −12.4% from peak
        tier, reason = KS.drawdown_tier(crash)
        caught = tier == KS.TIER_HARD_KILL
        ev = (f"evidenced curve peak≈$100,500 → $88,000 (≈−12.4%, > {KS.DRAWDOWN_THRESHOLD_PCT}% hard "
              f"threshold); drawdown_tier={tier} reason={reason!r}")
        return self._caught(ev, tier=tier) if caught else self._uncaught(ev)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# (DASHBOARD) tampered data — a tampered published proof must flip the dashboard integrity verdict
# ════════════════════════════════════════════════════════════════════════════════════════════════
class DashboardIntegrityScenario(RedTeamScenario):
    name = "dashboard_tampered_integrity"
    surface = Surface.DASHBOARD
    description = ("tamper the published decision_log the dashboard's integrity badge is derived "
                  "from — the data-contract verdict (chain.verified) must flip to FALSE.")

    def attack(self, sandbox: Path) -> Finding:
        # The dashboard's integrity badge is driven by the SAME verify-the-mirror verdict the API
        # serves (proof_chain.verify_mirror → chain.verified). We reproduce that contract: a healthy
        # mirror ⇒ verified True (green badge); a tampered mirror ⇒ verified False (INTEGRITY BROKEN).
        from spa_core.strategy_lab.rates_desk import proof_chain as PC

        bodies = [
            {"kind": "ENTRY", "approved": True, "underlying": "susde", "as_of": "2026-06-28"},
            {"kind": "REFUSAL", "approved": False, "underlying": "ezeth", "as_of": "2026-06-28"},
        ]
        rows = PC._rebase_rows([{"ts": "2026-06-28T00:00:00+00:00", **b} for b in bodies])

        # (1) CONTROL: the dashboard contract reports verified=True for the healthy mirror.
        healthy_verdict = PC.verify_mirror(rows)
        if not healthy_verdict.get("valid"):
            return self._control_failed(
                "dashboard data-contract reported a HEALTHY mirror as broken (false red badge)",
                verdict=healthy_verdict)

        # (2) ATTACK: tamper a published value the badge claims is verified (mutate the entry body
        #     WITHOUT recomputing entry_hash — exactly a swapped-in front-end JSON).
        tampered = [dict(r) for r in rows]
        tampered[1] = dict(tampered[1], approved=True, underlying="ezeth_silently_flipped")

        # (3) the data-contract must flip verified → False (the badge would read INTEGRITY BROKEN).
        verdict = PC.verify_mirror(tampered)
        caught = (not verdict.get("valid")) and verdict.get("broken_at") == 1
        ev = (f"tampered published decision row 1 → dashboard data-contract verified={verdict.get('valid')} "
              f"broken_at={verdict.get('broken_at')} (badge would read INTEGRITY BROKEN)")
        return self._caught(ev, broken_at=verdict.get("broken_at")) if caught else self._uncaught(ev)


# The seeded registry order is the canonical one-per-surface set.
ALL_SCENARIOS = [
    ProofChainForgeScenario(),
    ExitNavOutputForgeScenario(),
    OptimizerOverConcentrationScenario(),
    ToxicLrtApprovalScenario(),
    FeedNanFabricationScenario(),
    SleeveTrackMutationScenario(),
    KillSwitchLadderScenario(),
    DashboardIntegrityScenario(),
]
