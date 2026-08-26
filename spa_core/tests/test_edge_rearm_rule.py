"""
spa_core/tests/test_edge_rearm_rule.py — tests for ideas #75 (RARM) and #76 (RSN).

Every test here is a POSITIVE CONTROL in the sense `.claude/rules/deployment.md` demands: it
replays something that actually happened in the 2026-08-24 R&D run and goes RED if the property
it pins is removed. Where a test could pass for the wrong reason, the mutation that would fool it
is asserted from the OTHER side as well (`..._negative_control`), because a check that has never
seen the failure it claims to catch is decoration.

No network. The lab feeds are INJECTED from fixtures (the documented test seam in
`AggressiveFeeds`), so these run identically on a laptop and in CI. The two tests that need the
real deep-history feeds are gated on the /tmp cache that the script itself writes and say so out
loud when they cannot run — they never pretend to have checked.

Advisory / OUTSIDE_RISKPOLICY throughout: nothing here touches RiskPolicy, the kill-switch, the
live track or data/.
"""
# FROZEN-DATE-OK: даты — ПРЕДМЕТ теста и не связаны ни с какой свежестью. Здесь два класса, оба
# неподвижны по построению: (1) исторический инцидент — четыре даты kill'ов панели
# (2024-03-07 / 2024-03-18 / 2024-08-09 / 2024-08-23) и окно реплея 2024-03-05..2026-07-05;
# это ПРОШЛОЕ, замер идёт по фиксированной сетке дат, календарь его не двигает.
# (2) синтетическая ось фикстуры (`_dates()`), где дата — просто метка порядка дня: ни один
# тест в файле не читает часы, не сравнивает с `now` и не знает понятия «протухло», так что
# инъекция часов (предпочтение #1) здесь нечего инъектировать.
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import edge_rearm_rule as R  # noqa: E402
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds  # noqa: E402


# ───────────────────────────── fixtures: a tiny, fully synthetic lab history ─────────────────────

def _dates(n: int, start: str = "2024-03-05"):
    d0 = datetime.date.fromisoformat(start)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _flat(dates, value):
    return {d: value for d in dates}


def make_feeds(*, n_days: int = 120, spike_day: int = 40, spike: float = -0.20,
               spike_len: int = 1, recover: bool = True) -> AggressiveFeeds:
    """A lab history whose ONLY interesting event is a stETH/ETH ratio print at `spike_day`.

    `spike_len` days at (1 + spike), then back to 1.0 if `recover`. That is precisely the shape
    the real feed produces (a one-day print that is undone the next day) and precisely what the
    persistence gate is supposed to tell apart from a depeg that stays.
    """
    ds = _dates(n_days)
    ratio = {}
    for i, d in enumerate(ds):
        if spike_day <= i < spike_day + spike_len:
            ratio[d] = 1.0 + spike
        else:
            ratio[d] = 1.0 if (recover or i < spike_day) else 1.0 + spike
    return AggressiveFeeds(
        pt_susde_series=_flat(ds, 0.12),
        susde_apy_series=_flat(ds, 0.09),
        funding_series=_flat(ds, 0.0001),
        restaking_series={"steth": _flat(ds, 0.03), "eeth": _flat(ds, 0.03),
                          "weeth": _flat(ds, 0.03), "ezeth": _flat(ds, 0.03)},
        eth_price_series=_flat(ds, 3000.0),
        lrt_ratio_series={"steth": dict(ratio), "eeth": dict(ratio),
                          "weeth": dict(ratio), "ezeth": dict(ratio)},
    )


def snaps_from(feeds: AggressiveFeeds):
    ds = sorted(feeds.available_dates())
    return feeds.historical_snapshots(ds[0], ds[-1])


# ───────────────────────────── #76: the discriminator itself ─────────────────────────────

def test_lag1_autocorr_detects_iid_noise_on_a_level():
    """THE positive control for #76's whole argument.

    A level plus independent per-day measurement error differences to lag-1 autocorrelation −0.5.
    This is the statistic that separated the ratio feed (−0.48…−0.55) from the ETH price control
    (−0.011). If it stops reading −0.5 on a series that IS noise-on-a-level, #76's evidence table
    means nothing.
    """
    noise = [0.02 if i % 2 else -0.02 for i in range(200)]     # level + alternating error
    level = [1.0 + e for e in noise]
    diffs = R.diff_series({d: v for d, v in zip(_dates(len(level)), level)})
    assert R.lag1_autocorr(diffs) < -0.45


def test_lag1_autocorr_negative_control_random_walk_reads_zero():
    """The other side: a price PATH must not read −0.5, or the statistic proves nothing.

    Without this the previous test passes for a function that returns −1 unconditionally.
    """
    import random
    rng = random.Random(7)
    eq, v = [], 100.0
    for _ in range(400):
        v *= 1.0 + rng.gauss(0.0, 0.02)
        eq.append(v)
    diffs = R.diff_series({d: x for d, x in zip(_dates(len(eq)), eq)})
    assert abs(R.lag1_autocorr(diffs)) < 0.20


def test_reversal_stats_separates_a_round_trip_from_a_move_that_stays():
    """A depeg is a state; noise is a round trip. Both directions asserted."""
    round_trip = [0.10, -0.10, 0.0, 0.10, -0.10]
    stays = [0.10, 0.0, 0.0, 0.10, 0.0]
    assert R.reversal_stats(round_trip)["n_reversed"] == 2
    assert R.reversal_stats(stays)["n_reversed"] == 0


# ───────────────────────────── #76 repair (A): the causal median ─────────────────────────────

def test_causal_median_is_causal_a_future_point_cannot_change_a_past_output():
    """The standard way this repair is done WRONG is a centred window, and it is lookahead.

    TWO assertions, because the obvious one does not work. A median ABSORBS outliers: on a flat
    series, mutating future points cannot move a centred median at all (the future is always a
    minority of the window), so "mutate the tail and compare" passes for a centred implementation
    and proves nothing. That was the first version of this test, and swapping the implementation
    to a centred window left it green — decoration, caught by mutation.

    What actually distinguishes the two is measurable on a MONOTONE series:
      (1) the LAG. A trailing median-of-3 of a strictly increasing series returns the PREVIOUS
          observation; a centred one returns the current. That is the whole difference.
      (2) TRUNCATION INVARIANCE — the definition of causal: the output at day i is identical
          whether or not the series has any days after i.
    """
    ds = _dates(30)
    ser = {d: 1.0 + i * 0.01 for i, d in enumerate(ds)}      # strictly increasing
    out = R.causal_median(ser, 3)

    for i in range(2, len(ds)):
        assert out[ds[i]] == pytest.approx(ser[ds[i - 1]]), (
            f"day {i}: a trailing median-of-3 must return the PREVIOUS observation, got "
            f"{out[ds[i]]} — a centred window returns {ser[ds[i]]}")

    for i in (5, 12, 29):
        truncated = R.causal_median({d: ser[d] for d in ds[: i + 1]}, 3)
        assert truncated[ds[i]] == out[ds[i]], (
            f"day {i} changed when later days were removed — the window is not causal")


def test_causal_median_keeps_length_and_never_invents_a_value():
    ds = _dates(30)
    ser = {d: 1.0 + (0.1 if i % 3 == 0 else 0.0) for i, d in enumerate(ds)}
    out = R.causal_median(ser, 3)
    assert set(out) == set(ser)
    lo, hi = min(ser.values()), max(ser.values())
    # A median never leaves the observed range. It is not always an OBSERVED value: the first
    # k-1 days run on a shorter window, and an even-sized one averages the middle pair — that is
    # `statistics.median`'s documented behaviour, not a fabricated point.
    assert all(lo <= v <= hi for v in out.values())
    assert out[ds[0]] == ser[ds[0]]          # day one can only be itself


def test_causal_median_removes_a_one_day_spike_but_keeps_a_sustained_move():
    """The repair must be a repair, not a blunt low-pass: a real, sustained move survives."""
    ds = _dates(20)
    spike = {d: 1.0 for d in ds}
    spike[ds[10]] = 0.80
    assert R.causal_median(spike, 5)[ds[10]] == 1.0          # the one-day print is gone

    sustained = {d: (0.80 if i >= 10 else 1.0) for i, d in enumerate(ds)}
    smoothed = R.causal_median(sustained, 5)
    assert smoothed[ds[19]] == 0.80                           # the state is still there


# ───────────────────────────── #75: the re-arm operation ─────────────────────────────

def test_rearm_clears_the_kill_and_every_entry_anchor():
    from spa_core.strategy_lab.aggressive_lab.roster import build_roster
    strat = build_roster()["lrt_neutral"]
    strat._killed = True
    strat._kill_reason = "depeg"
    strat._entry_ratio = 1.0
    strat._prev_ratio = 1.0
    R.rearm(strat)
    assert strat._killed is False
    assert strat._kill_reason == ""
    assert strat._entry_ratio is None
    assert strat._prev_ratio is None


def test_rearm_without_clearing_the_entry_anchor_would_rekill_immediately():
    """POSITIVE CONTROL for why `_ENTRY_ANCHORS` exists.

    `lrt_neutral` kills on a drop from `_entry_ratio`. Re-admitting a book while keeping the OLD
    entry means the very next tick still sees the same breach and the book dies again having
    traded once — the arm would measure nothing and would look like an honest negative. This
    reproduces that failure directly, so the reset can never be quietly dropped.
    """
    from spa_core.strategy_lab.base import MarketSnapshot

    from spa_core.strategy_lab.aggressive_lab.roster import build_roster
    strat = build_roster()["lrt_neutral"]
    strat._killed = True
    strat._entry_ratio = 1.0            # entry the book NO LONGER holds
    strat._killed = False               # a re-admission that forgot the anchor reset
    snap = MarketSnapshot(date="2024-06-01")
    snap.restaking_apy = {"eeth": 0.03}
    snap.lrt_eth_ratio = {"eeth": 0.90}         # 10 % below the STALE entry, 0 % below a fresh one
    snap.funding_rate_8h = 0.0001
    res = strat.kill_check(snap)
    assert res.triggered, "stale entry anchor must re-kill — that is the failure being pinned"

    strat2 = build_roster()["lrt_neutral"]
    strat2._killed = True
    strat2._entry_ratio = 1.0
    R.rearm(strat2)                              # the real re-admission
    assert strat2.kill_check(snap).triggered is False


# ───────────────────────────── #76 repair (B): the persistence gate ─────────────────────────────

def test_persist_1_is_byte_identical_to_the_lab_rule_today():
    """k=1 must change NOTHING, or every comparison against `baseline` is meaningless."""
    snaps = snaps_from(make_feeds())
    a = R.replay(snaps, R.RearmRule(), persist_days=1)
    b = R.replay(snaps, R.RearmRule())
    assert a.returns == b.returns
    assert {k: v.kill_dates for k, v in a.events.items()} == \
           {k: v.kill_dates for k, v in b.events.items()}


def test_one_day_print_kills_at_k1_and_survives_at_k2():
    """The #76 (B) claim, on the exact shape the real feed produces.

    A single −20 % ratio print liquidates the 2x loop (levered −40 % against a −25 % buffer). At
    k=2 the breach has to hold a second day and it does not, so the book lives. Both sides are
    asserted: if the gate silently stopped killing at k=1 too, this test goes red.
    """
    snaps = snaps_from(make_feeds(spike_day=40, spike=-0.20, spike_len=1))
    k1 = R.replay(snaps, R.RearmRule(), persist_days=1)
    k2 = R.replay(snaps, R.RearmRule(), persist_days=2)
    assert k1.events["leverage_loop"].kills == 1
    assert k2.events["leverage_loop"].kills == 0


def test_a_breach_that_holds_two_days_still_kills_at_k2():
    """The gate must not become 'never kill'. A REAL, sustained breach must still fire.

    Without this, `persist2` could pass the previous test by disabling the kill entirely — which
    is exactly the fail-OPEN weakening `.claude/rules` forbids.

    The book here is `lrt_neutral` on purpose. Its trigger reads a LEVEL (ratio vs entry), so a
    depeg that stays breaches on every subsequent day and the gate must let it through. The
    liquidation trigger of `leverage_loop` reads a day-over-day MOVE instead, so for that book
    "sustained" means two consecutive breaching moves — a different fixture and a different test.
    The gate is uniform over both; the two shapes are what make that worth asserting.
    """
    snaps = snaps_from(make_feeds(spike_day=40, spike=-0.20, spike_len=1, recover=False))
    k1 = R.replay(snaps, R.RearmRule(), persist_days=1)
    k2 = R.replay(snaps, R.RearmRule(), persist_days=2)
    assert k1.events["lrt_neutral"].kills == 1
    assert k2.events["lrt_neutral"].kills == 1, "a depeg that STAYS must still kill at k=2"


def test_persistence_counter_requires_CONSECUTIVE_days():
    """on/off/on must NOT accumulate to a kill at k=2 — otherwise the gate counts occurrences,
    not persistence, and the word in the registry entry would be wrong."""
    ds = _dates(120)
    ratio = {}
    for i, d in enumerate(ds):
        ratio[d] = 0.80 if i in (40, 42, 44) else 1.0     # three breaches, never consecutive
    feeds = AggressiveFeeds(
        pt_susde_series=_flat(ds, 0.12), susde_apy_series=_flat(ds, 0.09),
        funding_series=_flat(ds, 0.0001),
        restaking_series={"steth": _flat(ds, 0.03)},
        eth_price_series=_flat(ds, 3000.0),
        lrt_ratio_series={"steth": dict(ratio)},
    )
    res = R.replay(snaps_from(feeds), R.RearmRule(), persist_days=2)
    assert res.events["leverage_loop"].kills == 0


def test_persist_days_zero_is_refused():
    snaps = snaps_from(make_feeds())
    with pytest.raises(ValueError):
        R.replay(snaps, R.RearmRule(), persist_days=0)


# ───────────────────────────── the guard that produced the #76 finding ──────────────────────────

def test_books_from_replay_refuses_a_move_beyond_the_panel_guard():
    """The refusal that started #76 (`leverage_loop: 66.9% one-day move at 2025-03-03`).

    It is the same JUMP_REFUSE threshold `RPE.load_panel` applies, so an arm this run builds can
    never be looser than the panel every other registry entry was measured on.
    """
    res = R.ReplayResult(dates=("2024-03-05", "2024-03-06"),
                         returns={"b": {"2024-03-05": 0.0, "2024-03-06": 0.669}},
                         events={}, rule="test")
    with pytest.raises(ValueError, match="66.9"):
        R.books_from_replay(res)


def test_books_from_replay_accepts_a_move_below_the_guard():
    """Negative control: the guard must not simply refuse everything."""
    res = R.ReplayResult(dates=("2024-03-05", "2024-03-06"),
                         returns={"b": {"2024-03-05": 0.0, "2024-03-06": 0.49}},
                         events={}, rule="test")
    axis, books = R.books_from_replay(res)
    assert len(books["b"]) == 3          # seed + two days


def test_reentry_frac_scales_the_return_and_is_range_checked():
    res = R.ReplayResult(dates=("2024-03-05", "2024-03-06"),
                         returns={"b": {"2024-03-05": 0.0, "2024-03-06": 0.10}},
                         events={}, rule="test")
    _, half = R.books_from_replay(res, reentry_frac=0.5)
    assert half["b"][-1] == pytest.approx(R.INITIAL * 1.05)
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            R.books_from_replay(res, reentry_frac=bad)


# ───────────────────────────── #75 mechanics ─────────────────────────────

def test_absorbing_rule_never_rearms_and_a_cooldown_does():
    snaps = snaps_from(make_feeds(spike_day=40, spike=-0.20, spike_len=1))
    absorbing = R.replay(snaps, R.RearmRule())
    warm = R.replay(snaps, R.FixedCooldown(30))
    assert absorbing.events["leverage_loop"].rearms == 0
    assert warm.events["leverage_loop"].rearms >= 1
    assert warm.events["leverage_loop"].dead_days < absorbing.events["leverage_loop"].dead_days


def test_rearm_costs_a_full_roundtrip_on_the_day_it_happens():
    """The 96 bp is charged, and charged ONCE, on the re-admission date.

    An over-charge is deliberate (the exit was already paid at the kill) and must stay visible:
    if it silently became zero, #75's negative would be flattered by exactly that amount.
    """
    snaps = snaps_from(make_feeds(spike_day=40, spike=-0.20, spike_len=1))
    priced = R.replay(snaps, R.FixedCooldown(30), roundtrip=R.ROUNDTRIP)
    free = R.replay(snaps, R.FixedCooldown(30), roundtrip=0.0)
    d = priced.events["leverage_loop"].rearm_dates[0]
    assert priced.returns["leverage_loop"][d] == pytest.approx(
        free.returns["leverage_loop"][d] - R.ROUNDTRIP)


def test_random_cooldown_is_seeded_and_reproducible():
    a = R.RandomCooldown(90, 3)
    import random
    r1, r2 = random.Random(3), random.Random(3)
    assert [a.wait_days("b", 0, r1) for _ in range(5)] == \
           [a.wait_days("b", 0, r2) for _ in range(5)]


def test_fixed_cooldown_refuses_a_nonsense_wait():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            R.FixedCooldown(bad)


# ───────────────────────────── isolation: data/ is never written ─────────────────────────────

def test_replay_writes_nothing_into_the_panel():
    """The panel on disk is eleven registry entries' shared measuring stick.

    A functional check, not a code-reading one: the modification times of every series file are
    compared before and after a full replay + panel build.
    """
    panel = ROOT / "data" / "aggressive_lab"
    if not panel.exists():
        pytest.skip(f"panel absent at {panel} — nothing to protect in this tree")
    before = {p: p.stat().st_mtime_ns for p in panel.rglob("*") if p.is_file()}
    # a mild print: 3x levered it stays inside the panel guard, so the arm builds and the test
    # measures ISOLATION rather than re-testing the refusal
    snaps = snaps_from(make_feeds(spike=-0.10))
    R.books_from_replay(R.replay(snaps, R.FixedCooldown(30)))
    after = {p: p.stat().st_mtime_ns for p in panel.rglob("*") if p.is_file()}
    assert before == after


def test_feed_cache_never_points_into_the_repo_data_dir():
    assert not str(R.DEFAULT_FEED_CACHE).startswith(str(ROOT / "data"))


# ───────────────────── the two checks that need the real deep history ─────────────────────

def _cached_series():
    """The real feed series, ONLY from the cache the script writes. Never a network call here."""
    cache = R.DEFAULT_FEED_CACHE
    if not cache.exists():
        return None
    try:
        return json.loads(cache.read_text())
    except Exception:  # noqa: BLE001
        return None


@pytest.mark.skipif(_cached_series() is None,
                    reason="real-history feed cache absent (run scripts/edge_rearm_rule.py once); "
                           "this test is NOT a no-op — it is unrunnable without the deep feeds")
def test_absorbing_replay_reproduces_the_published_panel_kill_dates():
    """PARITY. The four kills the panel on disk carries, reproduced by this run's replay.

    If this goes red, the replay is measuring a different history than every registry entry that
    cites the panel, and no comparison in #75/#76 may be published.
    """
    series = _cached_series()
    feeds = R.feeds_from_series(series)
    ds = sorted(feeds.available_dates())
    res = R.replay(feeds.historical_snapshots(ds[0], ds[-1]), R.RearmRule())
    got = {b: e.kill_dates[0] for b, e in res.events.items() if e.kills}
    assert got == {"leverage_loop": "2024-08-09", "levered_restaking": "2024-03-18",
                   "lp_eth_stable": "2024-03-07", "lrt_neutral": "2024-08-23"}


@pytest.mark.skipif(_cached_series() is None,
                    reason="real-history feed cache absent (run scripts/edge_rearm_rule.py once); "
                           "this test is NOT a no-op — it is unrunnable without the deep feeds")
def test_ratio_feed_noise_signature_is_still_there():
    """#76's evidence, pinned. Every LRT/ETH ratio reads near −0.5; the ETH price control does not.

    This is the assertion the whole entry rests on. If someone repairs `history_ratios` upstream,
    THIS test is the thing that goes red and tells the next session the registry entry is stale —
    which is the correct outcome, not a nuisance.
    """
    series = _cached_series()
    rep = R.noise_report(series)
    ratios = {k: v for k, v in rep.items() if k.startswith("ratio:")}
    assert ratios, "no ratio series in the cache"
    for name, d in ratios.items():
        assert d["lag1_autocorr"] < -0.4, f"{name} lost its noise signature: {d['lag1_autocorr']}"
        assert d["mean_reversed_frac"] > 0.3, name
    ctrl = rep["CONTROL:eth_price"]
    assert abs(ctrl["lag1_autocorr"]) < 0.2
    assert ctrl["mean_reversed_frac"] < 0.2
