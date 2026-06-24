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
