"""Characterization test for cycle_runner (Architect N12 refactor guard).

PURPOSE
=======
This is a GOLDEN-REFERENCE test that pins the *exact* observable output of one
``run_cycle`` invocation on a controlled (temp-dir, injected-data, no-network)
run. It exists to prove that the N12 decomposition of ``cycle_runner.py`` into
submodules (``equity.py`` / ``risk_gate.py`` / ``cycle_reporting.py``) is a PURE
behaviour-preserving MOVE: the captured artefacts below MUST be byte-identical
before and after the refactor.

It is deterministic and fully isolated:
  * fake orchestrator + allocator injected in-process (no live adapters / network)
  * no-op risk_scorer / track_persister (no iCloud / home writes)
  * a fixed UTC ``now`` so dates / IDs are stable
  * a fresh ``tmp_path`` data dir per run — NEVER touches the live ``data/`` track
    (the known honest-track corruption hazard).

What it captures (the golden surface the prompt enumerates):
  1. the equity bar(s) written to equity_curve_daily.json
     (close_equity / daily_yield_usd / accrual_source / source / evidenced),
  2. the trade record in trades.json
     (to_allocation / diff_usd / delta_abs / from_allocation),
  3. the status/summary fields in paper_trading_status.json,
  4. the go-live inputs (current_positions.json validation_summary + summary
     roll-up incl. the real_* evidenced-bar fields and ALLOC-002 protocol count),
  5. the full ``CycleResult.to_dict()`` (minus the volatile run_ts/correlation_id).

If ANY field below changes, the refactor altered behaviour — fix it to match.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from spa_core.paper_trading import cycle_runner as cr


# ─── Deterministic fakes (mirror test_cycle_runner.py) ───────────────────────


def _orch_fn(apy_map, status="ok"):
    def _fn(data_dir):
        adapters = [
            {
                "protocol": p,
                "apy_pct": a,
                "tvl_usd": 1e7,
                "tier": "T1" if p == "aave_v3" else "T2",
                "status": "ok",
                "chain": "ethereum",
            }
            for p, a in apy_map.items()
        ]
        return SimpleNamespace(adapters=adapters, status=status, data_freshness="live")

    return _fn


class _FakeAllocator:
    def __init__(self, target_usd):
        self._target = target_usd

    def allocate(self):
        return SimpleNamespace(
            target_usd=dict(self._target),
            target_weights={p: v / 100_000 for p, v in self._target.items()},
            expected_apy_pct=3.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )


# A small, policy-compliant T1-anchored allocation (deterministic).
_APY = {"aave_v3": 3.5, "compound_v3": 4.0, "morpho_blue": 4.8}
_TARGET = {"aave_v3": 30_000.0, "compound_v3": 20_000.0, "morpho_blue": 15_000.0}
_NOW = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)


def _run(tmp_path):
    return cr.run_cycle(
        data_dir=tmp_path,
        now=_NOW,
        orchestrator_fn=_orch_fn(_APY),
        allocator=_FakeAllocator(_TARGET),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
    )


def _load(tmp_path, name):
    p = tmp_path / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _golden_snapshot(tmp_path, result) -> dict:
    """Build the stable, volatile-field-stripped snapshot of all outputs."""
    rd = result.to_dict()
    # Strip volatile fields (wall-clock / random correlation id).
    rd.pop("run_ts", None)
    rd.pop("correlation_id", None)

    equity = _load(tmp_path, cr.EQUITY_FILENAME) or {}
    daily = equity.get("daily") or []
    bars = [
        {
            k: b.get(k)
            for k in (
                "date",
                "open_equity",
                "close_equity",
                "daily_return_pct",
                "cumulative_return_pct",
                "drawdown_pct",
                "equity",
                "apy_today",
                "daily_yield_usd",
                "source",
                "evidenced",
                "accrual_source",
                "positions",
            )
        }
        for b in daily
    ]
    summary = {
        k: (equity.get("summary") or {}).get(k)
        for k in (
            "num_days",
            "real_days",
            "start_equity",
            "end_equity",
            "total_return_pct",
            "max_drawdown_pct",
            "real_start_equity",
            "real_end_equity",
            "real_total_return_pct",
            "real_max_drawdown_pct",
            "first_real_date",
            "last_date",
        )
    }

    trades = _load(tmp_path, cr.TRADES_FILENAME) or []
    trade = None
    if trades:
        t = trades[-1]
        trade = {
            k: t.get(k)
            for k in (
                "type",
                "from_allocation",
                "to_allocation",
                "diff_usd",
                "delta_abs",
                "reason",
                "model_used",
                "is_demo",
                "capital",
            )
        }

    status = _load(tmp_path, cr.STATUS_FILENAME) or {}
    status_fields = {
        k: status.get(k)
        for k in (
            "is_demo",
            "source",
            "last_cycle_status",
            "days_running",
            "current_equity",
            "total_return_pct",
            "daily_return_pct",
            "apy_today_pct",
            "daily_yield_usd",
            "num_adapters_live",
            "current_positions",
            "last_allocation_model",
            "strategy_loop_active",
            "risk_policy_checked",
            "risk_policy_approved",
            "risk_policy_trimmed",
            "kill_switch_active",
            "safety_check_failed",
        )
    }

    positions = _load(tmp_path, cr.POSITIONS_FILENAME) or {}
    pos_fields = {
        k: positions.get(k)
        for k in (
            "is_demo",
            "source",
            "capital_usd",
            "current_equity_usd",
            "deployed_usd",
            "cash_usd",
            "accrued_yield_usd",
            "policy_compliant",
            "tuner_expected_apy",
            "positions",
            "validation_summary",
        )
    }

    return {
        "result": rd,
        "equity_bars": bars,
        "equity_summary": summary,
        "trade": trade,
        "status": status_fields,
        "positions": pos_fields,
    }


# The frozen golden reference — captured byte-for-byte from the PRE-refactor
# cycle_runner on the baseline (4858-passing) tree via ``_golden_snapshot``.
# ``notes`` is intentionally excluded from the result comparison: it is free
# text whose wording/order depends on which optional advisory modules happen to
# be importable in the test env, NOT on the behaviour the N12 move preserves.
# Every other field is pinned exactly — a single drift fails the refactor.
_GOLDEN = {
    "equity_bars": [
        {
            "accrual_source": "live",
            "apy_today": 2.57,
            "close_equity": 100007.04,
            "cumulative_return_pct": 0.007041,
            "daily_return_pct": 0.0,
            "daily_yield_usd": 7.0411,
            "date": "2026-06-10",
            "drawdown_pct": 0.0,
            "equity": 100007.04,
            "evidenced": True,
            "open_equity": 100000.0,
            "positions": {
                "aave_v3": 30000.0,
                "compound_v3": 20000.0,
                "morpho_blue": 15000.0,
            },
            "source": "cycle",
        }
    ],
    "equity_summary": {
        "end_equity": 100007.04,
        "first_real_date": "2026-06-10",
        "last_date": "2026-06-10",
        "max_drawdown_pct": 0.0,
        "num_days": 1,
        "real_days": 1,
        "real_end_equity": 100007.04,
        "real_max_drawdown_pct": 0.0,
        "real_start_equity": 100000.0,
        "real_total_return_pct": 0.007,
        "start_equity": 100000.0,
        "total_return_pct": 0.007,
    },
    "positions": {
        "accrued_yield_usd": 7.04,
        "capital_usd": 100000.0,
        "cash_usd": 35000.0,
        "current_equity_usd": 100007.04,
        "deployed_usd": 65000.0,
        "is_demo": False,
        "policy_compliant": True,
        "positions": {
            "aave_v3": 30000.0,
            "compound_v3": 20000.0,
            "morpho_blue": 15000.0,
        },
        "source": "cycle_runner",
        "tuner_expected_apy": 3.9538,
        "validation_summary": {
            "accrued_yield_usd": 7.04,
            "capital_usd": 100000.0,
            "cash_pct": 35.0,
            "cash_usd": 35000.0,
            "current_equity_usd": 100007.04,
            "deployed_usd": 65000.0,
            "protocol_count": 3,
            "t1_pct": 50.0,
            "t2_pct": 15.0,
        },
    },
    "result": {
        "apy_today_pct": 2.57,
        "current_equity": 100007.04,
        "daily_return_pct": 0.0,
        "daily_yield_usd": 7.0411,
        "date": "2026-06-10",
        "days_running": 1,
        "kill_switch_active": False,
        "kill_switch_reason": "all triggers clear",
        "live_data": True,
        "market_regime": "STABLE",
        "model_used": "risk_adjusted",
        "num_adapters_live": 3,
        "policy_approved": True,
        "policy_checked": True,
        "policy_trimmed": False,
        "policy_violations": [],
        "policy_warnings": ["Concentration 20.0% approaching T2 limit 20.0%"],
        "positions": {
            "aave_v3": 30000.0,
            "compound_v3": 20000.0,
            "morpho_blue": 15000.0,
        },
        "regime_t1_avg_apy": 4.1,
        "safety_check_failed": False,
        "safety_check_reason": "",
        "status": "ok",
        "strategy_loop_active": False,
        "total_return_pct": 0.007,
        "trade_id": "T001",
        "traded": True,
    },
    "status": {
        "apy_today_pct": 2.57,
        "current_equity": 100007.04,
        "current_positions": {
            "aave_v3": 30000.0,
            "compound_v3": 20000.0,
            "morpho_blue": 15000.0,
        },
        "daily_return_pct": 0.0,
        "daily_yield_usd": 7.0411,
        "days_running": 1,
        "is_demo": False,
        "kill_switch_active": False,
        "last_allocation_model": "risk_adjusted",
        "last_cycle_status": "ok",
        "num_adapters_live": 3,
        "risk_policy_approved": True,
        "risk_policy_checked": True,
        "risk_policy_trimmed": False,
        "safety_check_failed": False,
        "source": "cycle_runner",
        "strategy_loop_active": False,
        "total_return_pct": 0.007,
    },
    "trade": {
        "capital": 100000.0,
        "delta_abs": 32500.0,
        "diff_usd": 65000.0,
        "from_allocation": {},
        "is_demo": False,
        "model_used": "risk_adjusted",
        "reason": "orchestrator_cycle",
        "to_allocation": {
            "aave_v3": 30000.0,
            "compound_v3": 20000.0,
            "morpho_blue": 15000.0,
        },
        "type": "rebalance",
    },
}


def test_characterization_full_cycle(tmp_path):
    """Golden reference: one full cycle's observable output is byte-identical.

    Every artefact ``run_cycle`` writes (equity bar, summary roll-up incl. the
    evidenced real_* fields, trade record, status doc, positions/NAV) plus the
    ``CycleResult`` is pinned against a frozen literal captured from the
    pre-refactor tree. The N12 decomposition is a pure MOVE — every value below
    must remain identical.
    """
    result = _run(tmp_path)
    snap = _golden_snapshot(tmp_path, result)

    # ``notes`` is free advisory text (env-dependent ordering) — not behavioural.
    snap["result"].pop("notes", None)

    # Hard-pinned, field-by-field, so a diff localises the regression.
    assert snap["result"] == _GOLDEN["result"], (
        "CycleResult drifted from golden reference — behaviour changed.\n"
        f"got:      {json.dumps(snap['result'], sort_keys=True, default=str)}\n"
        f"expected: {json.dumps(_GOLDEN['result'], sort_keys=True, default=str)}"
    )
    assert snap["equity_bars"] == _GOLDEN["equity_bars"], "equity bar drifted"
    assert snap["equity_summary"] == _GOLDEN["equity_summary"], "summary drifted"
    assert snap["trade"] == _GOLDEN["trade"], "trade record drifted"
    assert snap["status"] == _GOLDEN["status"], "status doc drifted"
    assert snap["positions"] == _GOLDEN["positions"], "positions doc drifted"

    # NAV reconciliation invariant (deployed + cash + accrued == equity).
    po = snap["positions"]
    assert (
        round(po["deployed_usd"] + po["cash_usd"] + po["accrued_yield_usd"], 2)
        == po["current_equity_usd"]
    )
