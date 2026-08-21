#!/usr/bin/env python3
"""ADR-112 — a daily-limit check that RAISED stops the cycle, it does not excuse it.

Owner decision of 2026-08-21 12:34Z (card
``owner-decision-dnevnoi-limit-ubytka-a-esli-sama-proverk``, **вариант 2**):
"не посчитали — не торгуем" now covers the case where the check itself crashed.

The defect these tests replay
-----------------------------
``cycle_runner`` wrapped the whole Step-2a daily-limits block in::

    except Exception as _dl_exc:
        log.warning("DailyLimitsChecker failed (%s) — fail-open, cycle continues", ...)
        notes.append(f"daily_limits_check_error: ...")

So on a day when DL-01 (daily loss > 2 %) or DL-02 (peak drawdown > 10 %) raised
— a bad state file, an unpacking error, a typo in the checker — the cycle went
on to allocate capital with **no daily-loss limit at all**, and said so only in
a WARNING line. ADR-105 had just closed the neighbouring case ("we could not
measure it" → HALT); this branch was the hole left beside it, and the previous
session named it honestly instead of guessing the owner's answer.

Every test below is a positive control: it goes red on the fail-open code.

The reconciliation that had to come with it
-------------------------------------------
A naive HALT would have re-opened the hole ADR-048 closed. ``HALT`` early-returns
``blocked_by_daily_limits`` — positions HELD — and that runs BEFORE the kill
switch. On a day with ≥10 % drawdown AND a crashed checker, holding is strictly
weaker than the all-cash hard kill, and would shadow it. So DL-ERR defers to an
armed kill exactly as DL-02 does. Both directions are pinned below.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as _cr
from spa_core.paper_trading._cycle_io import (
    EQUITY_FILENAME,
    POSITIONS_FILENAME,
    TRADES_FILENAME,
)
from spa_core.risk.daily_limits import DailyLimitsChecker

CAP = 100_000.0
# PAPER_REAL_START — bars dated on/after this count as evidenced, so the
# drawdown the kill switch computes is exactly (peak - last) / peak.
_ANCHOR = date(2026, 6, 10)
_NOW = datetime(2026, 6, 18, 8, 0, tzinfo=timezone.utc)


class _Boom(RuntimeError):
    """The shape of the accident: something inside the checker blew up."""


# ── Hermetic fakes (network-free) ────────────────────────────────────────────


def _make_orch(universe):
    def _orch(_data_dir):  # noqa: ANN001 — matches orchestrator_fn signature
        adapters = [
            {
                "protocol": p, "id": p, "apy_pct": 4.0, "tvl_usd": 1e8,
                "tvl_source": "live", "tier": t, "status": "ok",
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


def _equity_curve(closes: list[float]) -> list[dict]:
    return [
        {
            "date": date.fromordinal(_ANCHOR.toordinal() + i).isoformat(),
            "close_equity": float(v),
            "open_equity": float(v),
        }
        for i, v in enumerate(closes)
    ]


def _gradual_closes_for_drawdown(dd_pct: float, peak: float = 102_000.0) -> list[float]:
    """≤1.5 %/day decline to ``dd_pct`` — each step stays inside DL-01's 2 %."""
    current = peak * (1.0 - dd_pct / 100.0)
    closes = [100_000.0, peak]
    v = peak
    while v > current * 1.0001:
        v = max(current, v * 0.985)
        closes.append(round(v, 2))
    return closes


def _seed(td: Path, *, held: dict, closes: list[float]) -> None:
    td.mkdir(parents=True, exist_ok=True)
    (td / POSITIONS_FILENAME).write_text(
        json.dumps({"positions": held, "cash_usd": CAP - sum(held.values())}),
        encoding="utf-8",
    )
    (td / EQUITY_FILENAME).write_text(
        json.dumps({"source": "cycle_runner", "daily": _equity_curve(closes)}),
        encoding="utf-8",
    )


_UNIVERSE = [("aave_v3", "T1"), ("compound_v3", "T1"), ("morpho_blue", "T1")]
_TARGET = {"aave_v3": 30_000.0, "compound_v3": 30_000.0, "morpho_blue": 25_000.0}
_HELD = {"aave_v3": 30_000.0, "compound_v3": 30_000.0, "morpho_blue": 25_000.0}
# A calm, ordinary book: no drawdown worth mentioning, no daily loss. Whatever
# these tests observe is caused by the crashing checker and by nothing else.
_CALM = [100_000.0, 100_100.0, 100_050.0, 100_080.0]


@pytest.fixture(autouse=True)
def _no_live_telegram(monkeypatch):
    """Transport-only stub — a simulated HALT must not ring the owner's phone."""
    from spa_core.telegram import push_policy

    monkeypatch.setattr(push_policy, "_send", lambda text: True)


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def _run(td: Path):
    return _cr.run_cycle(
        data_dir=str(td),
        now=_NOW,
        orchestrator_fn=_make_orch(_UNIVERSE),
        allocator=_make_alloc(_TARGET),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=False,
    )


def _final_book(td: Path, result) -> dict:
    trades = []
    tp = td / TRADES_FILENAME
    if tp.exists():
        try:
            trades = json.loads(tp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            trades = []
    if isinstance(trades, list) and trades and trades[-1].get("type") == "rebalance":
        return {k: float(v) for k, v in (trades[-1].get("to_allocation") or {}).items()}
    return {k: float(v) for k, v in (result.positions or {}).items()}


# ═══════════════════════════════════════════════════════════════════════════
# The accident: the check raises on an otherwise perfectly ordinary day
# ═══════════════════════════════════════════════════════════════════════════

# FROZEN-DATE-OK: injected-clock — every cycle here is driven by an explicit
# ``now=`` and bars the test writes itself, so both sides of every freshness
# comparison are pinned and the calendar cannot move this file.
def test_a_crashed_check_halts_the_cycle(tmp_path, monkeypatch):
    """THE test. Before ADR-112 this cycle traded; now it refuses.

    Nothing about the book is alarming — the curve is flat and profitable. The
    only thing wrong is that the guard blew up, and that alone is enough.
    """
    monkeypatch.setattr(
        DailyLimitsChecker, "check",
        lambda *a, **k: (_ for _ in ()).throw(_Boom("history[-1] is not subscriptable")),
    )
    td = tmp_path / "data"
    _seed(td, held=dict(_HELD), closes=list(_CALM))

    res = _run(td)

    assert res.status == "blocked_by_daily_limits", (
        f"cycle status {res.status!r}: the daily-loss guard raised, so the day's "
        f"loss limit did not exist — a cycle that allocates capital here is the "
        f"fail-open ADR-112 closed"
    )
    assert res.traded is False
    assert res.policy_approved is False


def test_the_crash_is_named_in_the_cycle_record(tmp_path, monkeypatch):
    """A refusal nobody can read is a refusal nobody can fix.

    Two facts must survive into the record: that the gate halted, and what the
    exception actually was. The old code kept the second and threw away the
    first — which is why the day looked like an ordinary trading day.
    """
    monkeypatch.setattr(
        DailyLimitsChecker, "check",
        lambda *a, **k: (_ for _ in ()).throw(_Boom("history[-1] is not subscriptable")),
    )
    td = tmp_path / "data"
    _seed(td, held=dict(_HELD), closes=list(_CALM))

    res = _run(td)

    joined = " | ".join(res.notes)
    assert "daily_limits_check_error" in joined, (
        f"the exception must still be recorded verbatim; notes={res.notes!r}"
    )
    assert "_Boom" in joined and "not subscriptable" in joined, (
        f"the note must carry the real exception, not a generic word; got {joined!r}"
    )
    assert any("daily_limits_halt" in n and "DL-ERR" in n for n in res.notes), (
        f"the HALT must be recorded on its own axis (DL-ERR), otherwise the "
        f"refusal cannot be told apart from DL-01/DL-02; notes={res.notes!r}"
    )
    assert "NOT MEASURED" in joined, (
        "the reason must say the number is missing, in the same words ADR-105 "
        "chose for the neighbouring case"
    )


def test_a_failed_save_also_halts(tmp_path, monkeypatch):
    """``save_result`` is inside the guarded region on purpose.

    A verdict that was computed but could not be written is, from everywhere
    outside this function, indistinguishable from one that was never computed.
    Fail-CLOSED is the only direction this project moves a safety branch.
    """
    monkeypatch.setattr(
        DailyLimitsChecker, "save_result",
        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only file system")),
    )
    td = tmp_path / "data"
    _seed(td, held=dict(_HELD), closes=list(_CALM))

    res = _run(td)

    assert res.status == "blocked_by_daily_limits", (
        f"cycle status {res.status!r}: the verdict never reached disk"
    )
    assert any("OSError" in n for n in res.notes)


def test_a_healthy_check_still_trades(tmp_path):
    """The other direction — the mutation guard.

    Without this, replacing the whole Step-2a block with an unconditional HALT
    would pass every test above. The same book, the same day, nothing patched:
    the cycle must behave exactly as it always has.
    """
    td = tmp_path / "data"
    _seed(td, held=dict(_HELD), closes=list(_CALM))

    res = _run(td)

    assert res.status != "blocked_by_daily_limits", (
        f"a working daily-limits check must not stop an ordinary day; "
        f"status={res.status!r}, notes={res.notes!r}"
    )
    assert not any("DL-ERR" in n for n in res.notes), (
        "no error happened, so no error may be claimed"
    )


# ═══════════════════════════════════════════════════════════════════════════
# ADR-048 reconciliation: the new HALT must not shadow the hard kill
# ═══════════════════════════════════════════════════════════════════════════

def test_crashed_check_defers_to_an_armed_hard_kill(tmp_path, monkeypatch):
    """≥10 % drawdown + crashed checker → ALL-CASH, not "hold and refuse".

    This is the trap ADR-112 could have walked into. ``blocked_by_daily_limits``
    early-returns with the positions still on the book; the hard kill (Step 2c)
    never runs. Holding a book through a 12 % drawdown is strictly weaker than
    liquidating it, so an un-reconciled DL-ERR would have made the cycle LESS
    safe on exactly the worst day — the same shadow bug ADR-048 fixed for DL-02.
    """
    monkeypatch.setattr(
        DailyLimitsChecker, "check",
        lambda *a, **k: (_ for _ in ()).throw(_Boom("checker exploded")),
    )
    td = tmp_path / "data"
    _seed(td, held=dict(_HELD), closes=_gradual_closes_for_drawdown(12.0))

    res = _run(td)

    assert res.kill_switch_active is True, (
        "12 % drawdown must arm the hard kill"
    )
    assert res.status != "blocked_by_daily_limits", (
        f"status={res.status!r}: the DL-ERR halt shadowed the all-cash kill — "
        f"the cycle held a book through a 12 % drawdown because a guard crashed"
    )
    assert any("dl02_deferred_to_hard_kill" in n for n in res.notes), (
        f"the deferral must be stated out loud, not inferred; notes={res.notes!r}"
    )
    book = _final_book(td, res)
    positive = {k: v for k, v in book.items() if v > 0}
    assert not positive, (
        f"the hard kill must end all-cash end-to-end, got {positive}"
    )


def test_deferral_needs_the_kill_to_be_armed(tmp_path, monkeypatch):
    """Both sides of the same switch.

    Same crash, same book — but no drawdown, so no kill. Nothing stronger is
    waiting downstream, and the deferral must NOT fire: otherwise DL-ERR would
    become a decorative note on a day that goes on to trade unprotected.
    """
    monkeypatch.setattr(
        DailyLimitsChecker, "check",
        lambda *a, **k: (_ for _ in ()).throw(_Boom("checker exploded")),
    )
    td = tmp_path / "data"
    _seed(td, held=dict(_HELD), closes=list(_CALM))

    res = _run(td)

    assert res.kill_switch_active is False
    assert res.status == "blocked_by_daily_limits", (
        f"status={res.status!r}: with no kill armed, DL-ERR is the strongest "
        f"word available and it must be honoured"
    )
    assert not any("dl02_deferred_to_hard_kill" in n for n in res.notes), (
        "nothing to defer to — claiming a deferral would be a false record"
    )


def test_thresholds_are_untouched():
    """The owner attached this condition to the decision, so it is a test.

    ADR-112 changes what happens when the check CRASHES. It does not move a
    single number, and RiskPolicy stays v1.0.
    """
    assert DailyLimitsChecker.MAX_DAILY_LOSS_PCT == 2.0
    assert DailyLimitsChecker.MAX_DRAWDOWN_PCT == 10.0
