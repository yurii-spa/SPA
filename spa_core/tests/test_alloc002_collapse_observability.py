#!/usr/bin/env python3
"""ALLOC-002 collapse must be VISIBLE and NAMED — positive control.

THE REAL FAILURE THIS REPRODUCES
================================
On 2026-08-08 the polled adapter set grew from 8 to 10; the allocator's
post-gate target then held 9 funded protocols, breached the ALLOC-002 diversity
floor (``max_protocols`` = 8) and ``_compliant_target`` silently replaced the
proposed book with the deterministic emergency book: ``pendle`` (17.92 % live)
fell out and the expected yield went 6.03 % → 3.51 %.

The cycle recorded that event as ONE free-text note::

    "ALLOC-002: raw allocator target (7 protocols) collapsed to compliant book
     (7 protocols) before rebalance diff."

Both numbers were ``len(target_usd)`` read AFTER the reassignment, so the note
printed the SAME count twice no matter how large the raw target was, never said
which protocols were dropped, and no field in ``paper_trading_status.json``
distinguished a collapsed cycle from a normal one. Nothing in ``monitoring/`` or
``alerts/`` reads cycle notes, so no watchdog saw it either.

WHAT IS ASSERTED
================
1. Collapse fired  → ``alloc002_collapse.fired`` is True, the two counts are the
   REAL ones (raw > compliant), the dropped protocols are named, and the note
   carries the same true numbers.
2. Normal cycle    → ``alloc002_collapse`` is present and says ``fired: False``
   (a positive "nothing happened", not a missing key) and no collapse note is
   emitted — no false alarm.

Both directions must go red under mutation: reverting the note to
``len(target_usd), len(target_usd)`` or dropping the status field fails (1);
stamping ``fired: True`` unconditionally fails (2).

Hermetic: per-test temp ``data_dir`` (``allow_live_write=False``), network-free
fakes, pinned clock. The live repo ``data/`` is never read or written.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as _cr
from spa_core.paper_trading._cycle_io import (
    EQUITY_FILENAME,
    POSITIONS_FILENAME,
    STATUS_FILENAME,
)
from spa_core.paper_trading.risk_gate import alloc002_collapse_record
from spa_core.risk.policy_enforcer import RULES

CAP = 100_000.0
_ANCHOR = date(2026, 6, 10)
_NOW = datetime(2026, 6, 18, 8, 0, tzinfo=timezone.utc)
MAX_P = int(RULES["max_protocols"])


@pytest.fixture(autouse=True)
def _no_live_telegram(monkeypatch):
    """Transport-only stub — the cycle's alerting must never leave the sandbox."""
    from spa_core.telegram import push_policy

    monkeypatch.setattr(push_policy, "_send", lambda text: True)


def _make_orch(universe):
    def _orch(_data_dir):  # noqa: ANN001 — matches orchestrator_fn signature
        adapters = [
            {
                "protocol": p,
                "id": p,
                "apy_pct": 4.0,
                "tvl_usd": 1e8,
                "tvl_source": "live",
                "tier": t,
                "status": "ok",
                "chain": f"chain_{p}",  # per-pool chain → no false single-chain cap
            }
            for p, t in universe
        ]
        return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")

    return _orch


def _make_alloc(target_usd):
    class _Alloc:
        def allocate(self):  # noqa: D401 — fake
            return SimpleNamespace(
                target_usd=dict(target_usd),
                target_weights={p: v / CAP for p, v in target_usd.items()},
                expected_apy_pct=4.0,
                model_used="risk_adjusted",
                strategy_loop_active=False,
            )

    return _Alloc()


def _seed(td: Path, held: dict) -> None:
    td.mkdir(parents=True, exist_ok=True)
    (td / POSITIONS_FILENAME).write_text(
        json.dumps({"positions": held, "cash_usd": CAP - sum(held.values())}),
        encoding="utf-8",
    )
    (td / EQUITY_FILENAME).write_text(
        json.dumps(
            {
                "source": "cycle_runner",
                "daily": [
                    {
                        "date": date.fromordinal(_ANCHOR.toordinal() + i).isoformat(),
                        "close_equity": v,
                        "open_equity": v,
                    }
                    for i, v in enumerate([100_000.0, 100_100.0, 100_200.0])
                ],
            }
        ),
        encoding="utf-8",
    )


def _run(td: Path, universe, target):
    return _cr.run_cycle(
        data_dir=str(td),
        now=_NOW,
        orchestrator_fn=_make_orch(universe),
        allocator=_make_alloc(target),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=False,
    )


def _status(td: Path) -> dict:
    return json.loads((td / STATUS_FILENAME).read_text(encoding="utf-8"))


def _over_cap_target() -> tuple[dict, list]:
    """``max_protocols`` + 1 funded protocols that violate ONLY the count cap.

    The 08.08 shape: two T1 anchors at 20 % each (T1 cap 40 %) and the rest T2
    sharing 45 % — strictly under the 50 % T2-total cap (which rejects a target
    that merely REACHES it), each far under the 20 % per-protocol cap — 85 %
    deployed → the 5 % cash buffer holds. Every other RiskPolicy rule
    passes, so ``max_protocols`` is the sole violation — which is the only rule
    that opens the ``_compliant_target`` collapse branch.
    """
    n_t2 = MAX_P - 1
    target = {"t1_a": 20_000.0, "t1_b": 20_000.0}
    universe = [("t1_a", "T1"), ("t1_b", "T1")]
    for i in range(n_t2):
        target[f"t2_{i}"] = round(45_000.0 / n_t2, 2)
        universe.append((f"t2_{i}", "T2"))
    assert len(target) == MAX_P + 1
    return target, universe


# ── 1. POSITIVE CONTROL: the 08.08 collapse is visible and named ─────────────


def test_collapse_is_named_with_true_counts_and_dropped_protocols(tmp_path):
    td = tmp_path / "sandbox"
    target, universe = _over_cap_target()
    _seed(td, {"t1_a": 10_000.0})
    _run(td, universe, target)

    st = _status(td)
    rec = st.get("alloc002_collapse")
    assert rec is not None, "status doc carries no alloc002_collapse field"
    assert rec["fired"] is True, f"collapse did not fire on {len(target)} protocols: {rec}"
    assert rec["trigger_rule"] == "max_protocols"

    # The counts must be the REAL ones — the bug printed the same number twice.
    assert rec["raw_protocols"] == len(target)
    assert rec["compliant_protocols"] <= MAX_P
    assert rec["raw_protocols"] > rec["compliant_protocols"], (
        "raw and compliant counts identical — the pre-collapse target was not "
        "captured (this is exactly the 08.08 defect)"
    )
    # What fell out is named, not merely counted.
    assert rec["dropped"], "collapse dropped protocols but named none"
    assert set(rec["dropped"]) <= set(target)

    notes = " ".join(st.get("notes") or [])
    assert "ALLOC-002" in notes and "collapsed" in notes
    assert f"({rec['raw_protocols']} protocols)" in notes, (
        f"note does not carry the true raw count: {notes}"
    )
    assert f"({rec['compliant_protocols']} protocols)" in notes


# ── 2. NEGATIVE CONTROL: a normal cycle raises no alarm ──────────────────────


def test_normal_cycle_states_no_collapse_and_emits_no_alarm(tmp_path):
    td = tmp_path / "sandbox"
    target = {f"proto_{i}": 15_000.0 for i in range(4)}
    _seed(td, {"proto_0": 15_000.0})
    _run(td, [(p, "T2") for p in target], target)

    st = _status(td)
    rec = st.get("alloc002_collapse")
    assert rec is not None, "field must be present on every cycle, not only on collapse"
    assert rec["fired"] is False, f"false alarm on a compliant {len(target)}-protocol book: {rec}"
    assert "collapsed to compliant book" not in " ".join(st.get("notes") or [])


# ── 3. The record itself (pure helper) ───────────────────────────────────────


def test_record_names_dropped_and_opened():
    raw = {"a": 10.0, "b": 20.0, "c": 30.0}
    new = {"a": 10.0, "d": 50.0}
    rec = alloc002_collapse_record(raw, new, True)
    assert rec["raw_protocols"] == 3 and rec["compliant_protocols"] == 2
    assert rec["dropped"] == ["b", "c"]
    assert rec["opened"] == ["d"]
    assert rec["raw_deployed_usd"] == 60.0
    assert rec["compliant_deployed_usd"] == 60.0


def test_record_is_a_positive_no_collapse_statement():
    assert alloc002_collapse_record({"a": 1.0}, {"a": 1.0}, False) == {"fired": False}


def test_record_ignores_zeroed_positions():
    rec = alloc002_collapse_record({"a": 10.0, "b": 0.0}, {"a": 10.0}, True)
    assert rec["dropped"] == [], f"a zero-funded protocol is not a dropped one: {rec}"
