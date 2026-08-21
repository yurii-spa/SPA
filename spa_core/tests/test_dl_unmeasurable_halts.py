#!/usr/bin/env python3
"""ADR-105 — an unmeasurable daily loss HALTs instead of reading as a calm day.

Owner decision of 2026-08-21 09:40Z (card
``owner-decision-dnevnoy-limit-ubytka-schitaet-neizvestn``, **вариант В**):
when the daily loss cannot be computed, the cycle does not trade.

The defect these tests replay
-----------------------------
``DailyLimitsChecker`` had a per-check ``SKIP`` ("could not evaluate") but the
GATE had no rung for it: DL-01/DL-02 contributed to ``halt_reasons`` only on
``FAIL``. So four distinct broken states — empty history, truncated history,
bars carrying no equity value, a non-positive previous close — each produced a
verdict **byte-identical** to a calm profitable day: ``gate=PASS``, no reason,
no warning. The cycle then allocated capital on a day when the one check that
would have stopped it was blind. That is fail-OPEN inside the risk layer, i.e.
the exact opposite of invariant 2.

Every test below is a positive control: each one goes red on the code as it
stood before ADR-105 (verified by mutation, journal ``docs/journal/2026-W34.md``).

The one tolerated silence
-------------------------
A track younger than the two closes DL-01 compares has no loss to measure yet —
it is young, not broken. The excuse is narrow, explicit and **caller-supplied**
(``track_days``): the gate never infers a track's age, and a caller that says
nothing gets HALT. Tolerated silence is still named out loud, in
``skip_reasons``, so "we let this one pass" never has to be reconstructed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.paper_trading import cycle_runner as _cr
from spa_core.paper_trading._cycle_io import EQUITY_FILENAME, POSITIONS_FILENAME
from spa_core.risk.daily_limits import (
    CHECK_SKIP,
    GATE_HALT,
    GATE_PASS,
    MIN_BARS_FOR_DAILY_LOSS,
    SKIP_NO_HISTORY,
    SKIP_UNUSABLE,
    DailyLimitsChecker,
)

CAP = 100_000.0
# Deliberately unremarkable inputs: three adapters under the 40 % concentration
# WARN and APYs inside the sanity band, so DL-03/04/05 stay quiet and the gate
# verdict below is about DL-01/DL-02 and nothing else.
_ALLOC = {"aave_v3": 35_000.0, "compound_v3": 35_000.0, "morpho_blue": 30_000.0}
_APYS = {"aave_v3": 4.0, "compound_v3": 4.5, "morpho_blue": 5.0}

# A calm, entirely ordinary pair of closes: −0.1 % on the day.
_CALM = [{"close_equity": 100_000.0}, {"close_equity": 99_900.0}]


def _dl(check_result: dict, dl_id: str) -> dict:
    return next(c for c in check_result["checks"] if c["id"] == dl_id)


# ═══════════════════════════════════════════════════════════════════════════
# The four states in which the daily loss cannot be computed
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "history, expect_kind, label",
    [
        ([], SKIP_NO_HISTORY, "empty history file"),
        ([{"close_equity": 100_000.0}], SKIP_NO_HISTORY, "one bar only"),
        (
            [{"close_equity": None}, {"close_equity": None}],
            SKIP_UNUSABLE,
            "bars carry no equity value",
        ),
        (
            [{"close_equity": 0.0}, {"close_equity": 99_000.0}],
            SKIP_UNUSABLE,
            "previous close is not positive",
        ),
    ],
)
def test_unmeasurable_daily_loss_halts(history, expect_kind, label):
    """Each broken state HALTs and says WHY, instead of passing silently."""
    res = DailyLimitsChecker().check(history, _ALLOC, _APYS)

    assert res["gate"] == GATE_HALT, (
        f"{label}: daily loss could not be measured and the gate said "
        f"{res['gate']!r} — 'could not measure' is not 'nothing was lost'"
    )
    assert res["halt_reasons"], f"{label}: HALT with no reason given"
    assert any("NOT MEASURED" in r for r in res["halt_reasons"]), (
        f"{label}: the halt reason must say the number is missing, got "
        f"{res['halt_reasons']!r}"
    )
    dl01 = _dl(res, "DL-01")
    assert dl01["status"] == CHECK_SKIP
    assert dl01["skip_kind"] == expect_kind, (
        f"{label}: the reason for the silence must be machine-readable so the "
        f"gate never re-derives it by matching on prose"
    )


def test_truncated_curve_on_an_old_track_halts():
    """The corruption case the owner's decision is actually about.

    A 46-day track whose curve file came back empty (crash mid-write, a bad
    restore) is NOT a young track. Before ADR-105 this was the single most
    dangerous read in the module: the state file had just been destroyed, and
    the gate answered exactly as it does on a quiet profitable day.
    """
    res = DailyLimitsChecker().check([], _ALLOC, _APYS, track_days=46)

    assert res["gate"] == GATE_HALT, (
        "an emptied curve on a 46-day track is a broken state file, not youth"
    )
    assert not res["skip_reasons"], (
        "nothing here is excusable — the silence must not be filed as tolerated"
    )


def test_forgetful_caller_gets_halt_not_pass():
    """``track_days`` omitted → no tolerance. Fail-CLOSED for the forgetful."""
    res = DailyLimitsChecker().check([], _ALLOC, _APYS)
    assert res["gate"] == GATE_HALT, (
        "a caller that does not state the track's age must not be granted the "
        "young-track excuse by default — that would restore the old fail-OPEN"
    )


# ═══════════════════════════════════════════════════════════════════════════
# The one tolerated silence: a track too young to have two closes
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "track_days, history",
    [
        (1, []),                                # day 1: nothing written yet
        (2, [{"close_equity": 100_000.0}]),     # day 2: one prior close
    ],
)
def test_young_track_is_tolerated_and_named(track_days, history):
    """A new track can still start — and the excuse is recorded, not silent."""
    res = DailyLimitsChecker().check(
        history, _ALLOC, _APYS, track_days=track_days
    )

    assert res["gate"] != GATE_HALT, (
        f"day {track_days} of a track has no two closes to compare; halting "
        f"here would make it impossible to ever start a track"
    )
    assert res["skip_reasons"], (
        "the tolerated silence must be NAMED — an excused check that leaves no "
        "trace is indistinguishable from a check that passed"
    )
    assert any("DL-01" in s and "NOT MEASURED" in s for s in res["skip_reasons"])


def test_young_track_excuse_does_not_cover_corrupt_bars():
    """Youth excuses missing bars. It does not excuse bars full of nothing."""
    res = DailyLimitsChecker().check(
        [{"close_equity": None}, {"close_equity": None}],
        _ALLOC,
        _APYS,
        track_days=1,
    )
    assert res["gate"] == GATE_HALT, (
        "two bars exist and neither carries a number — that is a broken file "
        "on day 1, and the young-track excuse must not reach it"
    )


def test_tolerance_window_matches_the_check_it_excuses():
    """The excuse expires exactly when DL-01 becomes computable."""
    beyond = MIN_BARS_FOR_DAILY_LOSS + 1
    res = DailyLimitsChecker().check([], _ALLOC, _APYS, track_days=beyond)
    assert res["gate"] == GATE_HALT, (
        f"by day {beyond} the track has had time to write "
        f"{MIN_BARS_FOR_DAILY_LOSS} closes; their absence is a defect"
    )


# ═══════════════════════════════════════════════════════════════════════════
# The owner's acceptance criterion, stated literally
# ═══════════════════════════════════════════════════════════════════════════

def test_unmeasurable_day_differs_from_a_calm_day():
    """"...и это слово отличается от ответа в спокойный день."

    This is the card's "как понять, что готово", asserted as written. Before
    ADR-105 the two dicts below agreed on every field that carries meaning.
    """
    calm = DailyLimitsChecker().check(_CALM, _ALLOC, _APYS, track_days=46)
    blind = DailyLimitsChecker().check([], _ALLOC, _APYS, track_days=46)

    assert calm["gate"] == GATE_PASS
    assert blind["gate"] == GATE_HALT
    assert calm["gate"] != blind["gate"], (
        "a day we could not measure must not answer with the same word as a "
        "quiet profitable day"
    )
    assert not calm["halt_reasons"] and blind["halt_reasons"]


def test_a_real_loss_still_halts_with_its_own_words():
    """No regression: a measured 3 % loss halts as FAIL, not as 'NOT MEASURED'."""
    res = DailyLimitsChecker().check(
        [{"close_equity": 100_000.0}, {"close_equity": 97_000.0}],
        _ALLOC,
        _APYS,
        track_days=46,
    )
    assert res["gate"] == GATE_HALT
    joined = "; ".join(res["halt_reasons"])
    assert "DL-01" in joined and "exceeds limit" in joined
    assert "NOT MEASURED" not in joined, (
        "a loss we DID measure must not be reported as one we could not"
    )


def test_thresholds_are_untouched():
    """ADR-105 changes what silence means. It changes no threshold (RiskPolicy v1.0)."""
    assert DailyLimitsChecker.MAX_DAILY_LOSS_PCT == 2.0
    assert DailyLimitsChecker.MAX_DRAWDOWN_PCT == 10.0


# ═══════════════════════════════════════════════════════════════════════════
# Wiring: the cycle must pass the age of THIS book, not of the configured track
# ═══════════════════════════════════════════════════════════════════════════
# A gate nobody calls correctly is decoration. These run the REAL ``run_cycle``
# against a sandbox and pin BOTH directions of the call site, so deleting
# ``track_days=`` from cycle_runner.py cannot stay green.
#
# The first version of this wiring asked ``_days_running(today,
# paper_start_date)`` — the age of the CONFIGURED TRACK. That reads correctly in
# production and is wrong everywhere else: every fresh data directory inherits
# prod's start date, so a brand-new sandbox claimed to be a 46-day track whose
# curve had been destroyed, and its very first cycle halted. The full suite
# found it (~40 cycles across 8 modules went ``blocked_by_daily_limits``); the
# fix was the signal, not the rule. ``_book_age_days`` now asks the records a
# previous cycle would have left BESIDE the curve.

def _make_orch():
    def _orch(_data_dir):  # noqa: ANN001 — matches orchestrator_fn signature
        adapters = [
            {
                "protocol": "aave_v3", "id": "aave_v3", "apy_pct": 4.0,
                "tvl_usd": 1e8, "tvl_source": "live", "tier": "T1",
                "status": "ok", "chain": "ethereum",
            }
        ]
        return SimpleNamespace(adapters=adapters, status="ok", data_freshness="live")

    return _orch


def _make_alloc():
    class _Alloc:
        def allocate(self):  # noqa: D401 — fake
            return SimpleNamespace(
                target_usd={"aave_v3": 40_000.0},
                target_weights={"aave_v3": 0.4},
                expected_apy_pct=4.0,
                model_used="risk_adjusted",
                strategy_loop_active=False,
            )

    return _Alloc()


@pytest.fixture(autouse=True)
def _no_live_telegram(monkeypatch):
    """Transport-only stub — a simulated HALT must not ring the owner's phone."""
    from spa_core.telegram import push_policy

    monkeypatch.setattr(push_policy, "_send", lambda text: True)


def _seed(td: Path, bars: list[dict], *, prior_closes: int | None = None) -> None:
    td.mkdir(parents=True, exist_ok=True)
    (td / POSITIONS_FILENAME).write_text(
        json.dumps({"positions": {}, "cash_usd": CAP}), encoding="utf-8"
    )
    doc: dict = {"source": "cycle_runner", "daily": bars}
    if prior_closes is not None:
        # The roll-up a previous cycle left behind. It lives beside ``daily``,
        # so a write that truncates the bars leaves it standing — and then the
        # file testifies against itself. THIS is what says "this book has run".
        doc["summary"] = {"num_snapshots": prior_closes}
    (td / EQUITY_FILENAME).write_text(json.dumps(doc), encoding="utf-8")


def _run(td: Path, *, now: datetime, start: str):
    return _cr.run_cycle(
        data_dir=str(td),
        now=now,
        paper_start_date=start,
        orchestrator_fn=_make_orch(),
        allocator=_make_alloc(),
        risk_scorer_fn=lambda d: None,
        track_persister_fn=lambda d: None,
        write=True,
        allow_live_write=False,
    )


# FROZEN-DATE-OK: injected-clock — every cycle below is driven by an explicit
# ``now=`` and an explicit ``paper_start_date=``, and the bars/status it reads
# are written by the test itself. Both sides of every freshness comparison are
# pinned, so the calendar cannot move this file.
def test_cycle_blocks_when_the_curve_is_gone_on_an_established_book(tmp_path):
    """End-to-end: a book that has closed 46 days, bars gone → no trade.

    The witness is the curve's own ``summary`` — an object beside the ``daily``
    list, which a truncating write leaves standing. It says 46 closes; the bars
    say nothing. That contradiction is a broken state file, and it stops the
    cycle.
    """
    td = tmp_path / "data"
    _seed(td, [], prior_closes=46)
    res = _run(
        td,
        now=datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc),
        start="2026-06-22",
    )
    assert res.status == "blocked_by_daily_limits", (
        f"cycle status {res.status!r}: a book with 46 recorded days and no "
        f"equity history must not allocate capital"
    )
    assert res.traded is False


def test_cycle_still_starts_on_day_one_of_a_new_book(tmp_path):
    """The other direction — and the mutation guard for the call site.

    Nothing beside the curve claims this book has run, so it is new and there
    is no prior close by construction. If ``cycle_runner`` stops passing
    ``track_days``, the checker defaults to tolerating nothing and this cycle
    HALTs — so dropping the argument turns this test red rather than silently
    bricking every new book.
    """
    td = tmp_path / "data"
    _seed(td, [])
    res = _run(
        td,
        now=datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc),
        start="2026-06-22",
    )
    assert res.status != "blocked_by_daily_limits", (
        "day 1 of a book cannot have a two-day loss; halting here would mean "
        "no track can ever be started"
    )
    assert any("daily_limits_not_measured" in n for n in res.notes), (
        "the tolerated silence must reach the cycle record — notes were "
        f"{res.notes!r}"
    )


def test_the_age_signal_is_the_book_not_the_configured_track(tmp_path):
    """The defect the full suite caught, pinned so it cannot come back.

    Same empty curve, same brand-new data directory, but the configured track
    started long ago — exactly the shape of every sandbox in this repository.
    Judging age by ``paper_start_date`` made this cycle halt; judging it by what
    the book itself left behind makes it start, correctly.
    """
    td = tmp_path / "data"
    _seed(td, [])
    res = _run(
        td,
        now=datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc),
        start="2026-06-22",  # a track 46 days old — but THIS book is new
    )
    assert res.status != "blocked_by_daily_limits", (
        "a fresh data directory inherited the configured track's age and was "
        "judged a 46-day book whose curve had been destroyed"
    )


def test_recorded_trades_alone_make_the_book_established(tmp_path):
    """Second witness: the status file can be gone and the book still not new.

    Two trades mean two closed cycles, so today is at least day 3 — past the
    window in which "no two closes yet" is an honest answer. One trade would
    NOT be enough, and deliberately so: it puts the book on day 2, which really
    does have only one prior close.
    """
    td = tmp_path / "data"
    _seed(td, [])
    (td / _cr.TRADES_FILENAME).write_text(
        json.dumps([{"type": "rebalance"}, {"type": "rebalance"}]), encoding="utf-8"
    )
    res = _run(
        td,
        now=datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc),
        start="2026-06-22",
    )
    assert res.status == "blocked_by_daily_limits", (
        "a book with two recorded trades has closed cycles before; an empty "
        "curve there is a broken file, not a first day"
    )


def test_a_days_own_refusal_does_not_block_the_next_day(tmp_path):
    """The second defect the full suite caught, pinned so it cannot come back.

    This system deliberately produces days WITHOUT a close: a stale feed makes
    the cycle refuse (``skipped_no_live_data``) and append no bar, on purpose.
    An earlier version of the age signal counted calendar days, so the day after
    a refusal looked like "three days old, one bar" — a broken curve — and the
    next cycle halted over a gap the system had itself, correctly, created.

    A guard that reds on the system behaving properly is a broken guard, so the
    signal counts CLOSES, not days.
    """
    td = tmp_path / "data"
    # Day 1 closed and traded; day 2 refused and wrote no bar; today is day 3.
    _seed(td, [{
        "date": "2026-08-04",
        "open_equity": 100_000.0,
        "close_equity": 100_000.0,
        "daily_return_pct": 0.0,
        "evidenced": True,
    }])
    (td / _cr.TRADES_FILENAME).write_text(
        json.dumps([{"type": "rebalance"}]), encoding="utf-8"
    )
    res = _run(
        td,
        now=datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc),
        start="2026-06-22",
    )
    assert res.status != "blocked_by_daily_limits", (
        "the cycle halted because a PREVIOUS day had honestly refused to write "
        "a bar — punishing the system for its own fail-closed behaviour"
    )


def test_one_trade_is_still_day_two_and_is_tolerated(tmp_path):
    """The boundary, from the other side — the witness must not overstate age."""
    td = tmp_path / "data"
    _seed(td, [])
    (td / _cr.TRADES_FILENAME).write_text(
        json.dumps([{"type": "rebalance"}]), encoding="utf-8"
    )
    res = _run(
        td,
        now=datetime(2026, 8, 6, 8, 0, tzinfo=timezone.utc),
        start="2026-06-22",
    )
    assert res.status != "blocked_by_daily_limits", (
        "one closed cycle puts the book on day 2, which has one prior close — "
        "counting that as an established book would halt legitimate day-2 runs"
    )
