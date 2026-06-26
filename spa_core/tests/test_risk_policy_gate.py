"""Tests for the MP-005 RiskPolicy blocking gate in the cycle runner.

The audit finding: the allocator's target reached ``trades.json`` without ever
passing through ``spa_core/risk/policy.py``. These tests pin the new contract:

* a policy-compliant target trades normally;
* over-deployment past the min-cash buffer is TRIMMED, not blocked;
* concentration / T2-total / TVL / APY violations BLOCK the trade,
  the cycle survives (``status="blocked_by_policy"``) holding prior positions;
* every block is appended to ``data/risk_policy_blocks.json`` (ring-buffer 100);
* an exception inside the gate is fail-open: WARNING + note, never a crash.

Orchestrator and allocator are injected as in-process fakes — fully
deterministic, no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as cr


# ─── Fakes ────────────────────────────────────────────────────────────────────


def _adapter(protocol, tier="T2", apy=4.0, tvl=1e7, status="ok", **extra):
    return {
        "protocol": protocol,
        "tier": tier,
        "apy_pct": apy,
        "tvl_usd": tvl,
        "status": status,
        **extra,
    }


DEFAULT_ADAPTERS = [
    _adapter("aave_v3", tier="T1", apy=4.0, tvl=2e8),
    _adapter("morpho_blue", tier="T2", apy=5.0, tvl=1e7),
    _adapter("yearn_v3", tier="T2", apy=3.0, tvl=1e7),
    _adapter("maple", tier="T2", apy=4.7, tvl=1e7),
]

# Compliant: T1 aave 40% (== cap, strict ">" passes), T2 total 34% < 35%.
CLEAN_TARGET = {"aave_v3": 40000.0, "morpho_blue": 20000.0, "yearn_v3": 14000.0}


def _orch_fn(adapters, status="ok"):
    def _fn(data_dir):
        return SimpleNamespace(adapters=adapters, status=status)

    return _fn


class _FakeAllocator:
    def __init__(self, target_usd):
        self._target = target_usd

    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(self._target),
            expected_apy_pct=3.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )


def _run(tmp_path, target_usd, *, adapters=None, now=None, write=True):
    return cr.run_cycle(
        data_dir=tmp_path,
        now=now or datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
        orchestrator_fn=_orch_fn(adapters if adapters is not None else DEFAULT_ADAPTERS),
        allocator=_FakeAllocator(target_usd),
        # MP-012: no-op risk scorer keeps these tests network-free.
        risk_scorer_fn=lambda d: None,
        # MP-109: no-op track persister keeps these tests off iCloud/home dirs.
        track_persister_fn=lambda d: None,
        write=write,
    )


def _load(tmp_path, name):
    p = tmp_path / name
    return json.loads(p.read_text()) if p.exists() else None


# ─── Clean pass ──────────────────────────────────────────────────────────────


def test_clean_allocation_passes(tmp_path):
    res = _run(tmp_path, CLEAN_TARGET)
    assert res.status == "ok"
    assert res.traded is True
    assert res.policy_checked is True
    assert res.policy_approved is True
    assert res.policy_violations == []
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 1
    # No block record for an approved allocation.
    assert _load(tmp_path, "risk_policy_blocks.json") is None


# ─── min_cash → trim, not block ──────────────────────────────────────────────


def test_min_cash_violation_trims_not_blocks(tmp_path):
    # Three T1 anchors → a structurally compliant target can exceed the 95%
    # deployable maximum; the gate must scale it down instead of blocking.
    adapters = [
        _adapter("aave_v3", tier="T1", apy=4.0, tvl=2e8),
        _adapter("compound_v3", tier="T1", apy=3.5, tvl=1e8),
        _adapter("morpho_blue", tier="T1", apy=5.0, tvl=1e8),
    ]
    target = {"aave_v3": 40000.0, "compound_v3": 35000.0, "morpho_blue": 25000.0}
    res = _run(tmp_path, target, adapters=adapters)
    assert res.status == "ok"
    assert res.traded is True
    assert res.policy_trimmed is True
    assert res.policy_approved is True
    deployed = sum(res.positions.values())
    assert deployed <= 95000.0 + 1e-6           # min_cash 5% respected
    assert deployed == pytest.approx(95000.0, abs=1.0)  # trimmed, not zeroed
    # Proportional scale 0.95 applied to each position.
    assert res.positions["aave_v3"] == pytest.approx(38000.0, abs=0.05)
    assert any("min-cash" in n for n in res.notes)


# ─── Blocking violations ─────────────────────────────────────────────────────


def test_concentration_violation_blocks(tmp_path):
    # morpho_blue is T2 → 30% target breaches the 20% per-protocol cap.
    res = _run(tmp_path, {"morpho_blue": 30000.0})
    assert res.status == "blocked_by_policy"
    assert res.traded is False
    assert res.policy_approved is False
    assert any("Concentration" in v for v in res.policy_violations)
    assert not _load(tmp_path, "trades.json")    # no trade records written


def test_t1_concentration_violation_blocks(tmp_path):
    # aave_v3 is T1 → 45% target breaches the 40% T1 cap.
    res = _run(tmp_path, {"aave_v3": 45000.0})
    assert res.status == "blocked_by_policy"
    assert any("Concentration" in v and "T1" in v for v in res.policy_violations)


def test_t2_total_allocation_blocks(tmp_path):
    # Each T2 pool ≤ its 20% cap, but combined 60% > the 35% T2-total limit.
    target = {"morpho_blue": 20000.0, "yearn_v3": 20000.0, "maple": 20000.0}
    res = _run(tmp_path, target)
    assert res.status == "blocked_by_policy"
    assert any("Total T2" in v for v in res.policy_violations)
    assert not _load(tmp_path, "trades.json")    # no trade records written


def test_low_tvl_blocks(tmp_path):
    adapters = [_adapter("morpho_blue", tier="T2", apy=5.0, tvl=400_000.0)]
    res = _run(tmp_path, {"morpho_blue": 10000.0}, adapters=adapters)
    assert res.status == "blocked_by_policy"
    assert any("TVL" in v for v in res.policy_violations)


def test_apy_too_high_blocks(tmp_path):
    adapters = [_adapter("degen_pool", tier="T2", apy=35.0, tvl=1e7)]
    res = _run(tmp_path, {"degen_pool": 10000.0}, adapters=adapters)
    assert res.status == "blocked_by_policy"
    assert any("exceeds maximum" in v for v in res.policy_violations)


def test_apy_too_low_blocks(tmp_path):
    adapters = [_adapter("dust_pool", tier="T2", apy=0.5, tvl=1e7)]
    res = _run(tmp_path, {"dust_pool": 10000.0}, adapters=adapters)
    assert res.status == "blocked_by_policy"
    assert any("below minimum" in v for v in res.policy_violations)


# ─── Blocked-cycle behaviour ─────────────────────────────────────────────────


def test_blocked_cycle_keeps_current_positions(tmp_path):
    # Day 1: compliant target establishes positions.
    res1 = _run(tmp_path, CLEAN_TARGET)
    assert res1.traded is True
    # Day 2: allocator goes rogue (T2 at 30%) → blocked, prior positions held.
    res2 = _run(
        tmp_path,
        {"morpho_blue": 30000.0},
        now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc),
    )
    assert res2.status == "blocked_by_policy"
    assert res2.traded is False
    assert res2.positions == res1.positions      # held, not replaced
    assert res2.daily_yield_usd > 0.0            # yield keeps accruing on held
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 1                       # no second trade


def test_blocked_first_cycle_deploys_nothing(tmp_path):
    res = _run(tmp_path, {"morpho_blue": 30000.0})
    assert res.status == "blocked_by_policy"
    assert res.positions == {}
    assert res.daily_yield_usd == 0.0
    assert res.current_equity == pytest.approx(100_000.0, abs=1e-6)


def test_status_doc_records_policy_verdict(tmp_path):
    _run(tmp_path, {"morpho_blue": 30000.0})
    st = _load(tmp_path, "paper_trading_status.json")
    assert st["last_cycle_status"] == "blocked_by_policy"
    assert st["risk_policy_checked"] is True
    assert st["risk_policy_approved"] is False
    assert st["risk_policy_violations"]
    assert any("blocked_by_policy" in n for n in st["notes"])


# ─── Audit log: data/risk_policy_blocks.json ─────────────────────────────────


def test_block_is_logged_to_file(tmp_path):
    _run(tmp_path, {"morpho_blue": 30000.0})
    blocks = _load(tmp_path, "risk_policy_blocks.json")
    assert isinstance(blocks, list) and len(blocks) == 1
    rec = blocks[0]
    assert rec["source"] == "cycle_runner"
    assert rec["date"] == "2026-06-10"
    assert rec["policy_version"] == "v1.0"
    assert rec["violations"]
    assert rec["blocked_target_usd"]["morpho_blue"] == 30000.0
    assert rec["capital_usd"] == 100000.0


def test_block_ring_buffer_capped_at_100(tmp_path):
    seed = [{"ts": f"2026-05-{(i % 28) + 1:02d}", "violations": ["x"]} for i in range(100)]
    (tmp_path / "risk_policy_blocks.json").write_text(json.dumps(seed))
    _run(tmp_path, {"morpho_blue": 30000.0})
    blocks = _load(tmp_path, "risk_policy_blocks.json")
    assert len(blocks) == 100                    # ring-buffer cap held
    assert blocks[-1]["date"] == "2026-06-10"    # newest kept
    assert blocks[0] != seed[0]                  # oldest dropped


def test_dry_run_blocked_writes_nothing(tmp_path):
    res = _run(tmp_path, {"morpho_blue": 30000.0}, write=False)
    assert res.status == "blocked_by_policy"
    assert _load(tmp_path, "risk_policy_blocks.json") is None
    assert _load(tmp_path, "trades.json") is None
    assert _load(tmp_path, "paper_trading_status.json") is None


# ─── LAW 1: fail-SAFE on safety-check errors (was fail-open) ─────────────────


def test_policy_exception_does_not_crash_cycle(tmp_path, monkeypatch):
    """LAW 1: a gate that cannot be evaluated must FAIL-SAFE (hold, no trade).

    Previously this asserted fail-OPEN (status=ok, traded=True). That let a
    broken RiskPolicy gate wave trades through — the exact anti-pattern LAW 1
    forbids. The contract is now: the cycle survives (no crash) but HOLDS.
    """
    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("policy config unavailable")

    monkeypatch.setattr("spa_core.risk.policy.RiskPolicy", _Boom)
    # Suppress the loud Telegram alert in tests.
    monkeypatch.setattr(cr, "_send_safety_failsafe_alert", lambda *a, **k: None)
    res = _run(tmp_path, CLEAN_TARGET)
    # Cycle survives (no crash) but is HELD: no new trade is recorded.
    assert res.status == "blocked_safety_check_error"
    assert res.safety_check_failed is True
    assert "risk_policy_gate_error" in res.safety_check_reason
    assert res.traded is False                    # FAIL-SAFE: gate error → HOLD
    assert any("FAIL_SAFE_HOLD" in n for n in res.notes)
    # No trade persisted (first cycle blocked → deploys nothing).
    assert _load(tmp_path, "trades.json") in (None, [])
    # No block record (that path is for policy-VIOLATIONS, not gate errors).
    assert _load(tmp_path, "risk_policy_blocks.json") is None


def test_kill_switch_check_error_holds_positions(tmp_path, monkeypatch):
    """LAW 1: a kill-switch check that raises → FAIL-SAFE hold, prior positions kept."""
    # Day 1: establish a compliant book.
    res1 = _run(tmp_path, CLEAN_TARGET)
    assert res1.traded is True

    # Day 2: the kill-switch check blows up — must NOT let a rebalance through.
    def _boom(*a, **k):
        raise RuntimeError("kill-switch state unreadable")

    monkeypatch.setattr(
        "spa_core.governance.kill_switch.run_kill_switch_check", _boom
    )
    monkeypatch.setattr(cr, "_send_safety_failsafe_alert", lambda *a, **k: None)
    res2 = _run(
        tmp_path,
        # A materially different target that WOULD trade if not held.
        {"aave_v3": 40000.0, "morpho_blue": 10000.0},
        now=datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc),
    )
    assert res2.status == "blocked_safety_check_error"
    assert res2.safety_check_failed is True
    assert "kill_switch_check_error" in res2.safety_check_reason
    assert res2.traded is False
    assert res2.positions == res1.positions      # held verbatim, not replaced
    trades = _load(tmp_path, "trades.json")
    assert len(trades) == 1                       # no second trade


def test_normal_cycle_unaffected_by_failsafe(tmp_path, monkeypatch):
    """Sanity: a clean compliant cycle is NOT flagged fail-safe and still trades."""
    monkeypatch.setattr(cr, "_send_safety_failsafe_alert", lambda *a, **k: None)
    res = _run(tmp_path, CLEAN_TARGET)
    assert res.status == "ok"
    assert res.safety_check_failed is False
    assert res.safety_check_reason == ""
    assert res.traded is True


# ─── GOVERNANCE INVARIANT (P3-10): approved=False CANNOT be overridden ────────
#
# CLAUDE.md rule #: "approved=False from RiskPolicy CANNOT be overridden by any
# agent." (See spa_core/risk/policy.py governance docstring + RiskConfig.)
# Before P3-10 this invariant was enforced ONLY by convention — no test pinned
# it. These tests assert the contract DIRECTLY on the extracted N12 gate
# (``_apply_risk_policy_gate``): whenever RiskPolicy returns approved=False the
# gate's verdict is ALWAYS approved=False, for EVERY rejection reason, and there
# is NO caller input / override flag / kwarg that flips it back to True. The
# only escapes are the two SAFE ones: a min-cash overshoot is TRIMMED (still
# approved over the trimmed book, never the raw over-deployed one), and a gate
# exception FAILS CLOSED (approved=False). This test fails the instant any code
# path lets a rejection slip through as approved=True.

from spa_core.paper_trading.risk_gate import (  # noqa: E402
    _apply_risk_policy_gate,
)

# One adapter per distinct rejection reason. Each target is engineered so the
# *only* outcome a correct gate can return is approved=False.
_REJECTION_CASES = {
    # T2 single-protocol concentration cap (20%): 30% target breaches it.
    "t2_concentration": (
        [_adapter("morpho_blue", tier="T2", apy=5.0, tvl=1e7)],
        {"morpho_blue": 30000.0},
        "Concentration",
    ),
    # T1 single-protocol concentration cap (40%): 45% breaches it.
    "t1_concentration": (
        [_adapter("aave_v3", tier="T1", apy=4.0, tvl=2e8)],
        {"aave_v3": 45000.0},
        "Concentration",
    ),
    # T2 total-allocation cap (50%): three 20% pools = 60% combined.
    "t2_total": (
        [
            _adapter("morpho_blue", tier="T2", apy=5.0, tvl=1e7),
            _adapter("yearn_v3", tier="T2", apy=3.0, tvl=1e7),
            _adapter("maple", tier="T2", apy=4.7, tvl=1e7),
        ],
        {"morpho_blue": 20000.0, "yearn_v3": 20000.0, "maple": 20000.0},
        "Total T2",
    ),
    # TVL floor ($5M): a $400k pool is below it.
    "tvl_floor": (
        [_adapter("morpho_blue", tier="T2", apy=5.0, tvl=400_000.0)],
        {"morpho_blue": 10000.0},
        "TVL",
    ),
    # APY upper bound (30%): 35% is too high.
    "apy_high": (
        [_adapter("degen_pool", tier="T2", apy=35.0, tvl=1e7)],
        {"degen_pool": 10000.0},
        "exceeds maximum",
    ),
    # APY lower bound (1%): 0.5% is too low.
    "apy_low": (
        [_adapter("dust_pool", tier="T2", apy=0.5, tvl=1e7)],
        {"dust_pool": 10000.0},
        "below minimum",
    ),
    # Drawdown / kill-switch threshold (5%): emulated via a tiny capital so the
    # deployed target also trips the buffer — but the salient verdict is a hard
    # reject. (Drawdown itself is portfolio-state driven; the gate replays onto a
    # fresh empty state, so we pin the kill-switch threshold via policy below.)
}


@pytest.mark.parametrize("case", list(_REJECTION_CASES))
def test_gate_rejection_is_final_for_every_reason(case):
    """For EACH rejection reason, the gate verdict is approved=False — full stop."""
    adapters, target, needle = _REJECTION_CASES[case]
    gate = _apply_risk_policy_gate(target, 100_000.0, adapters)
    assert gate["error"] is None, f"{case}: this is a violation path, not an error"
    assert gate["approved"] is False, f"{case}: rejection leaked through as approved"
    assert gate["violations"], f"{case}: rejected with no recorded violation"
    assert any(needle in v for v in gate["violations"]), (
        f"{case}: expected a '{needle}' violation, got {gate['violations']}"
    )


def test_drawdown_kill_switch_threshold_blocks_directly():
    """The 5% portfolio-drawdown kill switch in RiskPolicy rejects directly.

    Exercised on RiskPolicy.check_new_position (the gate replays onto a fresh
    empty state, so drawdown is pinned at the policy layer it lives in).
    """
    from spa_core.risk.policy import (
        PortfolioState,
        Position,
        RiskPolicy,
    )

    policy = RiskPolicy()
    # A position sitting at a 6% unrealized loss → total_drawdown 6% ≥ 5% stop.
    losing = Position(
        protocol_key="aave_v3",
        tier="T1",
        asset="USDC",
        amount_usd=40_000.0,
        apy_at_open=4.0,
        current_apy=4.0,
        unrealized_pnl_usd=-6_000.0,
    )
    state = PortfolioState(total_capital_usd=100_000.0, positions=[losing])
    res = policy.check_new_position(
        state,
        protocol_key="morpho_blue",
        tier="T2",
        amount_usd=5_000.0,
        current_apy=4.0,
        tvl_usd=1e7,
    )
    assert res.approved is False
    assert any("drawdown" in v.lower() for v in res.violations)


def test_no_kwarg_or_caller_input_can_override_a_rejection():
    """There is NO override knob: a rejected target stays rejected.

    ``_apply_risk_policy_gate`` exposes only (target, capital, adapters, ddir).
    None of them is an "approve anyway" switch. We sweep plausible caller
    intents (different ddir, extra adapter metadata claiming the pool is fine,
    a forced/elevated tier) and assert the verdict never flips to approved.
    """
    base_target = {"morpho_blue": 30000.0}  # 30% T2 → over the 20% cap

    # 1) Baseline rejection.
    g = _apply_risk_policy_gate(
        base_target, 100_000.0,
        [_adapter("morpho_blue", tier="T2", apy=5.0, tvl=1e7)],
    )
    assert g["approved"] is False

    # 2) Adapter metadata that "claims" a high TVL / friendly APY cannot waive
    #    the concentration cap (different axis entirely).
    g2 = _apply_risk_policy_gate(
        base_target, 100_000.0,
        [_adapter("morpho_blue", tier="T2", apy=4.0, tvl=9e9, status="ok",
                  approved=True, override=True, force=True)],
    )
    assert g2["approved"] is False, "spurious adapter flags must not approve"

    # 3) Mislabelling the tier as T1 (higher cap) still cannot rescue a 30% pool
    #    when its true reason persists — and if 30% < 40% T1 it would only pass
    #    by HONEST policy math, not an override. Use 45% so it fails under BOTH
    #    tier caps: no relabelling escapes.
    g3 = _apply_risk_policy_gate(
        {"morpho_blue": 45000.0}, 100_000.0,
        [_adapter("morpho_blue", tier="T1", apy=4.0, tvl=1e7)],
    )
    assert g3["approved"] is False, "tier relabelling must not approve a breach"


def test_gate_exception_fails_closed_not_open():
    """A gate that cannot be evaluated must FAIL CLOSED (approved=False).

    The only non-rejection outcomes a correct gate may produce are an honest
    approval or a fail-closed block — never a silent approve-on-error.
    """
    # capital_usd as a non-numeric type makes the internal arithmetic raise;
    # the gate must capture it into `error` and block, not propagate / approve.
    gate = _apply_risk_policy_gate(
        {"morpho_blue": 30000.0}, "not-a-number",  # type: ignore[arg-type]
        [_adapter("morpho_blue", tier="T2", apy=5.0, tvl=1e7)],
    )
    assert gate["approved"] is False
    assert gate["error"] is not None
    assert gate["violations"], "a fail-closed block must record a reason"


def test_only_safe_escape_is_trim_over_the_trimmed_book():
    """A min-cash overshoot is TRIMMED — approval is over the trimmed book only.

    This is the single benign 'override' of the raw caller target, and it makes
    the book MORE conservative (smaller deployment), never less. The raw
    over-deployed target is never the one approved.
    """
    adapters = [
        _adapter("aave_v3", tier="T1", apy=4.0, tvl=2e8),
        _adapter("compound_v3", tier="T1", apy=3.5, tvl=1e8),
        _adapter("morpho_blue", tier="T1", apy=5.0, tvl=1e8),
    ]
    raw = {"aave_v3": 40000.0, "compound_v3": 35000.0, "morpho_blue": 25000.0}
    gate = _apply_risk_policy_gate(raw, 100_000.0, adapters)
    assert gate["approved"] is True
    assert gate["trimmed"] is True
    deployed = sum(gate["target_usd"].values())
    assert deployed <= 95_000.0 + 1e-6          # min-cash 5% enforced
    assert deployed < sum(raw.values())          # strictly more conservative
