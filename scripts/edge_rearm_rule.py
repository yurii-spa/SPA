#!/usr/bin/env python3
"""
scripts/edge_rearm_rule.py — Ideas #75 (RARM) and #76 (RARM-PANEL)

Advisory-only backtest. IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
Never imports spa_core.execution. Never touches RiskPolicy v1.0, the kill-switch, the live
track (data/equity_curve_daily.json) or the fleet. Reads data/ READ-ONLY and — this is the
part that is new and needs saying loudly — it REPLAYS THE LAB ROSTER IN MEMORY and writes
NOTHING into data/aggressive_lab/. The panel on disk is the shared measuring stick of eleven
registry entries; a run that rewrote it would silently invalidate all of them.


WHY THIS RUN EXISTS — THE BOTTLENECK #74 NAMED AND DID NOT MEASURE
------------------------------------------------------------------
#73 went looking for a rule about basket size and came back with a property of the PANEL
instead: four of its ten books were killed by the lab's own kill-switch in 2024 and have been
frozen ever since — 40 % of the capital sitting at exactly zero dispersion — leaving
`eth_directional` as the single source of volatility (sd 3.529 %/day against 0.435 % for the
next book). That is the whole content of the "law of one book" that #68, #69, #71 and #72 each
rediscovered from a different direction.

#74 closed the pair with an explicit diagnosis of the cause:

    "...не оживляет ни одной, потому что возвратов в строй ноль у всех четырёх — узкое место
     в отсутствующем re-arm-правиле лаборатории"

Nobody has measured what that missing rule costs. This run does, and the code says why it is
missing in one line: `_AggressiveBase.step()` opens with `if self._killed: return`, and NOTHING
anywhere in the lab ever clears `_killed`. The kill is an ABSORBING state. A desk that blew up
a levered loop in August 2024 does not stay in cash for the following two years; it waits out
the event and re-opens. The lab has no way to express that, so its panel cannot either.


IDEA #75 — RARM: what does a re-admission rule buy, and is it a rule or just more exposure?
  MECHANISM (causal, no oracle, fail-CLOSED). A book killed on day k is re-admitted on day
  k+C — a FRESH position opened at TODAY's market, at the equity the book was frozen with:

      _killed → False, and every ENTRY anchor is reset (_entry_ratio / _entry_eth /
      _prev_ratio / _prev_pt_price / _prev_eth) plus the _liquidated latch.

  Resetting the anchors is not a convenience, it is the only honest reading. Three of the four
  kill criteria on this panel are measured against an entry the book NO LONGER HOLDS
  (`lrt_neutral`: depeg vs `_entry_ratio`; `lp_eth_stable`: LP value vs `_entry_eth`), so a
  re-admission that kept them would re-kill the book on its first tick and the arm would test
  nothing. Leaving `_prev_*` cleared is likewise the conservative choice: the first tick after
  re-entry marks ZERO, so no move that happened while the book sat in cash is ever credited to
  it. A re-armed book can be killed again, from its new entry — the state machine keeps running
  and the kill counts are reported.

  THE ARMS. `absorbing` is the status quo (the published panel's rule) and `no_kill` is the
  other bound — the kill switch removed entirely. Between them, C ∈ {30, 60, 90, 180, 365}.

  THE CONTROL THAT DECIDES THE VERDICT. "Wait exactly C days" is a claim that the WAIT carries
  information. The frequency-matched control draws each wait from uniform{1..2C} — same
  expected wait, same state machine, zero information about the market — over 20 seeds. If the
  fixed cooldown cannot beat that, then the only thing the rule contributes is "come back
  eventually", and the honest way to publish it is as an exposure statement, not a timing edge.
  This is #72's control, reused because it is the one that has already killed a rule here.

  COSTS. Each re-admission is charged a FULL round-trip (96 bp, canonical #10/#49) although it
  is really a one-way entry — the exit was paid by the kill and is common to every arm. The
  over-charge is deliberate and one-directional: it can only make the hypothesis look worse.
  A cost-free arm is run alongside, because "lost" must be decomposable into COST and TIMING
  (the decomposition #71 had to add after the fact).

IDEA #76 — RSN: the kill trigger reads a series whose OWN NOISE crosses its threshold
  This started as "RARM-PANEL": does re-arming heal the panel and dissolve the law of one book?
  The first arm answered a different and larger question, so the entry follows the measurement.

  The `no_kill` bound refused to build: with the kill removed, `leverage_loop` takes a +66.9 %
  ONE-DAY move (2025-03-03) and the panel loader's accounting-discontinuity guard fires. Chasing
  that number down leads to the input every depeg/liquidation kill on this panel reads —
  `PriceFeed.history_ratios`, which is `price[lrt][d] / price[eth][d]`, two independently
  timestamped DeFiLlama daily series divided by each other. Its statistics, measured here:

    • stETH/ETH daily sd 3.47 %, worst prints −17.4 % and +33.4 %, and 59 days of the 565 move
      more than 5 % — the very threshold `lrt_neutral` kills on. Ten days exceed 12.5 %, the
      2x-levered liquidation buffer; seventeen exceed 8.33 %, the 3x one;
    • LAG-1 AUTOCORRELATION −0.512, and −0.476/−0.511/−0.549/−0.490 for the other four ratios.
      Independent per-day measurement error on a near-constant level produces EXACTLY −0.5 in
      the differenced series; the five observed values bracket it;
    • the CONTROLS say it is not "crypto is volatile": the ETH price series itself has lag-1
      autocorrelation −0.011 and reverses 2.2 % of a big move next day, and the PT implied-yield
      series −0.167 / 2.3 %. The ratios reverse 46–57 % of every big move the very next day;
    • the level is right (stETH/ETH median 0.9994) — it is the DISPERSION that is fabricated,
      which is why nothing downstream ever noticed.

  So the four dead books, the 40 % of frozen capital #73 found, and the "law of one book" that
  #68/#69/#71/#72/#73 each rediscovered are all downstream of a quoting artifact. A real stETH
  has never moved 33 % against ETH in a day.

  TWO REPAIRS ARE TESTED, and they are NOT equally defensible — the entry says so rather than
  picking the flattering one:
    (A) MEASUREMENT SIDE (preferred): a CAUSAL median-of-k on the ratio (median of the last k
        observations, never centred — a centred window is lookahead). This fixes the input and
        leaves both the kill and the mark reading a series that means what it says. Its cost is
        one day of lag, which #51 SLT already priced on this exact panel as ~0.07 pp.
    (B) REACTION SIDE: require the breach to HOLD k consecutive days before the kill commits.
        Cheaper, but it carries a real objection that must be stated and not buried: if the
        print were REAL, a levered position breaching its liquidation threshold is gone that
        day, and no persistence rule can un-liquidate it. (B) is only defensible BECAUSE the
        print is demonstrably noise; on a trustworthy feed it would be a fail-OPEN weakening of
        a kill switch, which this project forbids.
  Then the original RARM-PANEL question is re-asked on whichever panel survives: per-book sd,
  frozen share, and #71's own leave-one-out control (`PRP.loo_per_book`, imported unchanged) —
  does the per-book advantage still collapse to machine zero when `eth_directional` is dropped?


HONEST LIMITS DECLARED UP FRONT
  • evidence L0 — backtest on an advisory paper panel; every number is [bt], never realized;
  • the panel's books are themselves backtests (harness.py over real deep-history feeds), so
    what is measured is a rule on a real return SHAPE, not a realized P&L;
  • REPLAY DRIFT IS REAL AND IS MEASURED, NOT ASSUMED AWAY. harness.py states outright that a
    replay re-derives every past row from TODAY's feed data, so this run's `absorbing` arm is
    NOT guaranteed to equal the panel written on disk weeks ago. `--parity` prints the gap book
    by book. Every comparison below is made WITHIN this run (absorbing vs re-armed on the same
    replay, same days, same feeds); the on-disk panel is a reference, never a mixed-in arm;
  • the phase="backtest" window only (2024-03-05..2026-07-05), which is where all four kills
    live. The forward block is not touched and not glued (the seam fabricates ±30-100 %);
  • splits are the registry's four, canonical one first; no parameter is chosen on TEST;
  • a fractional re-entry dial (`--reentry-frac`) scales the capital allocated to the book, not
    its leverage — so the kill triggers, which are properties of the ratio path and not of
    position size, are unchanged by it. That is why it is separable and honest here;
  • IS_ADVISORY=True / OUTSIDE_RISKPOLICY=True; no capital moves, no agent is deployed, the
    fleet is untouched, and data/aggressive_lab/ is opened read-only.

stdlib-only, deterministic (seeded), fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from pathlib import Path
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import edge_pde_real_panel as PRP                      # noqa: E402  (#71/#72 machinery)
import edge_proportional_drawdown_exit as PDE          # noqa: E402  (#70 wedge + guardian)
import edge_real_panel_ensemble as RPE                 # noqa: E402  (#16/#17 panel loader)

from spa_core.strategy_lab.aggressive_lab import feeds as af       # noqa: E402
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds  # noqa: E402
from spa_core.strategy_lab.aggressive_lab.roster import build_roster    # noqa: E402

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

INITIAL = PRP.INITIAL
#: 96 bp round-trip — canonical #10/#49, inherited through #70 rather than restated.
ROUNDTRIP = PDE._ROUNDTRIP
#: Registry-canonical split first, then the other three used by #68/#69/#71.
SPLITS: Tuple[str, ...] = PRP.SPLITS
#: The cooldown ladder. Not tuned: a month, a quarter, a half-year, a year, plus 60 to give the
#: short end a second point so "shorter is always better" is distinguishable from a shape.
COOLDOWNS: Tuple[int, ...] = (30, 60, 90, 180, 365)
#: Seeds for the frequency-matched random-cooldown control (same count as #71/#72 use).
PERM_SEEDS = 20
#: Feed-series cache. /tmp on purpose — never data/.
DEFAULT_FEED_CACHE = Path(os.environ.get("SPA_REARM_FEED_CACHE") or "/tmp/spa_rearm_feeds.json")

#: The anchors a re-admitted book must forget. Each is an entry reference the book no longer
#: holds; carrying one across a re-admission would either re-kill the book instantly or credit
#: it with a move it did not sit through. Attributes absent on a given class are skipped.
_ENTRY_ANCHORS = ("_entry_ratio", "_entry_eth", "_prev_ratio", "_prev_pt_price",
                  "_prev_eth", "_prev_iy")
_LATCHES = ("_liquidated",)


# ─────────────────────────── feed series (cached, injectable) ───────────────────────────

def build_feed_series() -> Dict[str, object]:
    """The REAL deep-history series behind the lab's backtest, as plain JSON-able dicts.

    Same sources as `aggressive_lab.run._real_history_feeds` — deliberately the same call, so
    this run cannot quietly measure a different history than the panel it is compared against.
    A best-effort feed that raises is omitted (the books needing it then fail closed, honestly),
    exactly as the lab does; it is never replaced with a fabricated series.
    """
    pt_series, susde_series = af.load_real_susde_history()   # fail-closed if the dataset is gone
    start, end = min(pt_series), max(pt_series)
    out: Dict[str, object] = {"pt": pt_series, "susde": susde_series,
                              "start": start, "end": end}
    try:
        from spa_core.strategy_lab.data.funding_feed import FundingFeed
        out["funding"] = FundingFeed(symbol="ETH").history(start, end) or None
    except Exception:  # noqa: BLE001
        out["funding"] = None
    try:
        from spa_core.strategy_lab.data.restaking_feed import RestakingFeed
        out["restaking"] = RestakingFeed().history(start, end) or None
    except Exception:  # noqa: BLE001
        out["restaking"] = None
    try:
        from spa_core.strategy_lab.data.price_feed import PriceFeed
        pf = PriceFeed()
        hist = pf.history(start_date=start, end_date=end)
        out["eth"] = (hist or {}).get("eth") or None
        out["ratio"] = pf.history_ratios(start_date=start, end_date=end) or None
    except Exception:  # noqa: BLE001
        out["eth"] = None
        out["ratio"] = None
    return out


def load_feed_series(cache: Path = DEFAULT_FEED_CACHE, *, refresh: bool = False
                     ) -> Dict[str, object]:
    """`build_feed_series()` with a /tmp cache, so a re-run does not re-hit the feeds.

    The cache is a convenience for repeated analysis inside one investigation, NOT a data
    source: a missing/unreadable cache simply rebuilds. It never lives under data/.
    """
    if not refresh and cache.exists():
        try:
            return json.loads(cache.read_text())
        except Exception:  # noqa: BLE001 — a corrupt cache must never become a fabricated feed
            pass
    series = build_feed_series()
    try:
        cache.write_text(json.dumps(series))
    except Exception:  # noqa: BLE001 — caching is best-effort; the run continues either way
        pass
    return series


def feeds_from_series(series: Dict[str, object]) -> AggressiveFeeds:
    return AggressiveFeeds(
        pt_susde_series=series.get("pt"), susde_apy_series=series.get("susde"),
        funding_series=series.get("funding"), restaking_series=series.get("restaking"),
        eth_price_series=series.get("eth"), lrt_ratio_series=series.get("ratio"),
    )


# ─────────────────────────── #76: the noise measurement and repair (A) ───────────────────────────

def diff_series(series: Dict[str, float]) -> List[float]:
    ds = sorted(series)
    return [series[ds[i]] / series[ds[i - 1]] - 1.0
            for i in range(1, len(ds)) if series[ds[i - 1]]]


def lag1_autocorr(xs: Sequence[float]) -> float:
    """Lag-1 autocorrelation. −0.5 is the fingerprint of iid measurement error on a level.

    If `ratio_t = L + e_t` with e iid, the DIFFERENCED series has lag-1 autocorrelation exactly
    −0.5 in the limit. That is the whole test: a price path reads ~0, a noisy quotient reads −0.5.
    """
    xs = list(xs)
    if len(xs) < 3:
        return 0.0
    m = statistics.fmean(xs)
    num = sum((xs[i] - m) * (xs[i - 1] - m) for i in range(1, len(xs)))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den else 0.0


def reversal_stats(xs: Sequence[float], thr: float = 0.05) -> Dict[str, float]:
    """Of the moves bigger than `thr`, how much of each is undone the NEXT day.

    A depeg is a state; noise is a round trip. This separates them without any model.
    """
    xs = list(xs)
    big = [i for i in range(len(xs) - 1) if abs(xs[i]) > thr]
    if not big:
        return {"n_big": 0, "n_reversed": 0, "mean_reversed_frac": 0.0}
    rev = sum(1 for i in big if xs[i + 1] * xs[i] < 0 and abs(xs[i + 1]) >= 0.5 * abs(xs[i]))
    frac = statistics.fmean([-xs[i + 1] / xs[i] for i in big])
    return {"n_big": len(big), "n_reversed": rev, "mean_reversed_frac": frac}


def noise_report(series: Dict[str, object], *, thr: float = 0.05) -> Dict[str, object]:
    """The evidence table behind #76: every ratio beside the two control series."""
    out: Dict[str, object] = {}

    def one(name: str, ser: Dict[str, float], is_control: bool) -> None:
        d = diff_series(ser)
        if not d:
            return
        r = reversal_stats(d, thr)
        out[name] = {
            "n": len(d), "sd_pct": statistics.pstdev(d) * 100.0,
            "lag1_autocorr": lag1_autocorr(d),
            "min_pct": min(d) * 100.0, "max_pct": max(d) * 100.0,
            "days_over_5pct": sum(1 for x in d if abs(x) > 0.05),
            "days_over_8_33pct": sum(1 for x in d if abs(x) > 0.0833),
            "days_over_12_5pct": sum(1 for x in d if abs(x) > 0.125),
            "is_control": is_control,
            **r,
        }

    for sym, ser in sorted((series.get("ratio") or {}).items()):
        one(f"ratio:{sym}", ser, False)
    if series.get("eth"):
        one("CONTROL:eth_price", series["eth"], True)
    if series.get("pt"):
        one("CONTROL:pt_implied_yield", series["pt"], True)
    return out


def causal_median(series: Dict[str, float], k: int) -> Dict[str, float]:
    """Repair (A): each day replaced by the median of the last `k` OBSERVED values, inclusive.

    Causal by construction — day t may use t, t-1 … t-k+1 and nothing later. A centred window
    would be lookahead and is the standard way this repair is done wrong. The first k-1 days
    take the median of what exists so far (never of the future), so the series keeps its length
    and no point is fabricated.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    ds = sorted(series)
    out: Dict[str, float] = {}
    for i, d in enumerate(ds):
        window = [series[x] for x in ds[max(0, i - k + 1): i + 1]]
        out[d] = statistics.median(window)
    return out


def smooth_ratio_series(series: Dict[str, object], k: int) -> Dict[str, object]:
    """`series` with every LRT/ETH ratio path replaced by its causal median-of-k. Nothing else
    is touched: the yields, funding and the ETH price path stay exactly as the lab reads them,
    so any difference downstream is attributable to the ratio and to nothing else."""
    out = dict(series)
    ratio = series.get("ratio") or {}
    out["ratio"] = {sym: causal_median(ser, k) for sym, ser in ratio.items()}
    return out


# ─────────────────────────── the re-arm rules ───────────────────────────

class RearmRule:
    """How long a book waits, in days, before it is re-admitted. None = never (absorbing)."""

    name = "absorbing"

    def wait_days(self, book: str, kill_index: int, rng: random.Random) -> Optional[int]:
        return None


class FixedCooldown(RearmRule):
    """Re-admit exactly `cooldown` days after the kill. The hypothesis under test."""

    def __init__(self, cooldown: int) -> None:
        if cooldown < 1:
            raise ValueError(f"cooldown must be >= 1 day, got {cooldown}")
        self.cooldown = int(cooldown)
        self.name = f"rearm_{self.cooldown}d"

    def wait_days(self, book: str, kill_index: int, rng: random.Random) -> Optional[int]:
        return self.cooldown


class RandomCooldown(RearmRule):
    """The frequency-matched control: wait ~uniform{1..2C}, same mean, zero market information.

    This is the arm that decides whether #75 is a TIMING rule or an EXPOSURE statement. If a
    schedule that knows nothing matches the fixed cooldown, the wait carries no information —
    the same test that killed #50 (no-trade band) and #72 (deadband).
    """

    def __init__(self, cooldown: int, seed: int) -> None:
        if cooldown < 1:
            raise ValueError(f"cooldown must be >= 1 day, got {cooldown}")
        self.cooldown = int(cooldown)
        self.seed = int(seed)
        self.name = f"rand_{self.cooldown}d_s{self.seed}"

    def wait_days(self, book: str, kill_index: int, rng: random.Random) -> Optional[int]:
        return rng.randint(1, 2 * self.cooldown)


def rearm(strat) -> None:
    """Re-open a FRESH position today at the book's frozen equity.

    Clears the kill, every ENTRY anchor and the liquidation latch. Equity is NOT restored to
    notional — the book comes back with what the blow-up left it, which is the whole point.
    """
    strat._killed = False
    strat._kill_reason = ""
    for attr in _ENTRY_ANCHORS:
        if hasattr(strat, attr):
            setattr(strat, attr, None)
    for attr in _LATCHES:
        if hasattr(strat, attr):
            setattr(strat, attr, False)


# ─────────────────────────── the in-memory replay ───────────────────────────

class BookEvents(NamedTuple):
    kills: int
    rearms: int
    kill_dates: Tuple[str, ...]
    rearm_dates: Tuple[str, ...]
    dead_days: int


class ReplayResult(NamedTuple):
    dates: Tuple[str, ...]
    returns: Dict[str, Dict[str, float]]     # {book: {date: daily return, cost included}}
    events: Dict[str, BookEvents]
    rule: str


def replay(snaps: Sequence, rule: RearmRule, *, disable_kill: bool = False,
           roundtrip: float = ROUNDTRIP, seed: int = 0, persist_days: int = 1,
           config: Optional[Dict[str, dict]] = None) -> ReplayResult:
    """Replay the whole roster day by day, in memory, under one re-admission rule.

    The per-day loop is `run_backtest`'s, verbatim in order (`step` then `kill_check`), with a
    re-admission check inserted BEFORE the step — a book whose cooldown elapsed trades back in
    today and is marked from today. Nothing is written anywhere.

    `disable_kill=True` is the other bound: kill_check is not called at all, so no book ever
    stops. It is a BOUND, not a proposal — a lab with no kill switch is not a thing anyone is
    arguing for, it is there to separate "re-entry helped" from "the kill was the problem".

    `persist_days=k` is #76's repair (B): a trigger must fire on k CONSECUTIVE days before the
    kill commits. k=1 is the lab's rule today and must be byte-identical to it (tested). While a
    breach is pending, the latch the trigger set is released so the next day is a fresh reading —
    including `_liquidated`, which is the honest reading ONLY because the print is noise, and is
    flagged as such in the header. On a trustworthy feed this arm would be a fail-OPEN weakening
    of a kill switch and must not be shipped.
    """
    if persist_days < 1:
        raise ValueError(f"persist_days must be >= 1, got {persist_days}")
    strats = build_roster(config)
    rng = random.Random(seed)
    pending: Dict[str, int] = {sid: 0 for sid in strats}
    returns: Dict[str, Dict[str, float]] = {sid: {} for sid in strats}
    kill_idx: Dict[str, Optional[int]] = {sid: None for sid in strats}
    wait: Dict[str, Optional[int]] = {sid: None for sid in strats}
    kills: Dict[str, List[str]] = {sid: [] for sid in strats}
    rearms: Dict[str, List[str]] = {sid: [] for sid in strats}
    dead: Dict[str, int] = {sid: 0 for sid in strats}
    dates: List[str] = []

    for i, snap in enumerate(snaps):
        dates.append(snap.date)
        for sid, strat in strats.items():
            cost = 0.0
            if strat._killed and kill_idx[sid] is not None and wait[sid] is not None \
                    and (i - kill_idx[sid]) >= wait[sid]:
                rearm(strat)
                rearms[sid].append(snap.date)
                kill_idx[sid] = None
                wait[sid] = None
                pending[sid] = 0     # a fresh position gets a fresh persistence count
                cost += roundtrip
            was_dead = strat._killed
            before = strat._equity
            strat.step(snap)
            if not disable_kill:
                strat.kill_check(snap)
                if strat._killed and not was_dead:
                    pending[sid] += 1
                    if pending[sid] < persist_days:
                        # the breach must HOLD: release the latch and read the feed again tomorrow
                        strat._killed = False
                        strat._kill_reason = ""
                        for attr in _LATCHES:
                            if hasattr(strat, attr):
                                setattr(strat, attr, False)
                elif not strat._killed:
                    pending[sid] = 0
            if strat._killed:
                if not was_dead:
                    kills[sid].append(snap.date)
                    kill_idx[sid] = i
                    wait[sid] = rule.wait_days(sid, i, rng)
                else:
                    dead[sid] += 1
            move = (strat._equity / before - 1.0) if before > 0 else 0.0
            returns[sid][snap.date] = move - cost

    events = {sid: BookEvents(kills=len(kills[sid]), rearms=len(rearms[sid]),
                              kill_dates=tuple(kills[sid]), rearm_dates=tuple(rearms[sid]),
                              dead_days=dead[sid])
              for sid in strats}
    return ReplayResult(tuple(dates), returns, events, rule.name)


def books_from_replay(res: ReplayResult, *, reentry_frac: float = 1.0
                      ) -> Tuple[List[str], Dict[str, List[float]]]:
    """(axis, {book: equity series}) in EXACTLY the shape `PRP.load_books` returns.

    Same convention: one leading $100k seed, so axis index i is equity index i+1. That is what
    lets every downstream helper (#70's guardian, #71's LOO, the metrics) be imported and used
    unchanged instead of re-implemented — the discipline #71 and #73 both insisted on.

    `reentry_frac` < 1 allocates only that share of the book's capital to the strategy, the
    remainder sitting in 0 % cash. It scales the RETURN, never the leverage, so the kill
    triggers — which read the ratio path, not the position size — are identical.
    """
    if not 0.0 < reentry_frac <= 1.0:
        raise ValueError(f"reentry_frac must be in (0, 1], got {reentry_frac}")
    axis = list(res.dates)
    books: Dict[str, List[float]] = {}
    for name in sorted(res.returns):
        eq = [INITIAL]
        for d in axis:
            r = res.returns[name][d] * reentry_frac
            if abs(r) > RPE.JUMP_REFUSE:
                raise ValueError(
                    f"{name}: {abs(r) * 100:.1f}% one-day move at {d} — refusing to treat an "
                    f"accounting discontinuity as a return (same guard as RPE.load_panel)"
                )
            eq.append(eq[-1] * (1.0 + r))
        books[name] = eq
    return axis, books


# ─────────────────────────── metrics over an arm ───────────────────────────

def arm_metrics(axis: Sequence[str], books: Dict[str, List[float]], *,
                start: Optional[str], end: Optional[str]) -> Dict[str, float]:
    """Equal-weight panel metrics over one window. Tail is reported beside return, always."""
    _, sub = PRP.slice_books(axis, books, start, end)
    eq = PRP.equity_from_returns(PRP.portfolio_returns(sub))
    n_days = len(eq) - 1
    m = PRP.metrics(eq, 0.0, n_days, 0.0)
    return {"apy": m["apy"], "maxdd": m["maxdd"], "calmar": m["calmar"]}


def per_book_metrics(axis: Sequence[str], books: Dict[str, List[float]], *,
                     start: Optional[str], end: Optional[str]) -> Dict[str, Dict[str, float]]:
    _, sub = PRP.slice_books(axis, books, start, end)
    out: Dict[str, Dict[str, float]] = {}
    for name, eq in sub.items():
        n_days = len(eq) - 1
        m = PRP.metrics(eq, 0.0, n_days, 0.0)
        out[name] = {"apy": m["apy"], "maxdd": m["maxdd"], "calmar": m["calmar"]}
    return out


def daily_sd_pct(eq: Sequence[float]) -> float:
    rets = [(eq[i] / eq[i - 1] - 1.0) for i in range(1, len(eq)) if eq[i - 1] > 0]
    return statistics.pstdev(rets) * 100.0 if len(rets) > 1 else 0.0


def frozen_fraction(axis: Sequence[str], books: Dict[str, List[float]], *,
                    start: Optional[str], end: Optional[str], tol: float = 1e-12) -> float:
    """Share of books whose window return series is identically flat (zero dispersion).

    #73's "40 % of the capital with zero dispersion" restated as something computable on any
    arm, so absorbing and re-armed are comparable on the same definition.
    """
    _, sub = PRP.slice_books(axis, books, start, end)
    flat = sum(1 for eq in sub.values() if daily_sd_pct(eq) <= tol)
    return flat / len(sub) * 100.0 if sub else 0.0


# ─────────────────────────── #75 runner ───────────────────────────

def run_ladder(snaps: Sequence, *, splits: Sequence[str] = SPLITS,
               cooldowns: Sequence[int] = COOLDOWNS, roundtrip: float = ROUNDTRIP,
               reentry_frac: float = 1.0, gross_too: bool = True) -> Dict[str, object]:
    """The #75 ladder: absorbing / no_kill / fixed cooldowns, on every split, TRAIN and TEST.

    One replay per arm; the splits are windows cut out of the same replay, so every arm sees
    the same days and the same feeds — the only thing that changes is the re-admission rule.
    """
    arms: List[Tuple[str, ReplayResult]] = []
    arms.append(("absorbing", replay(snaps, RearmRule(), roundtrip=roundtrip)))
    arms.append(("no_kill", replay(snaps, RearmRule(), disable_kill=True, roundtrip=roundtrip)))
    for c in cooldowns:
        arms.append((f"rearm_{c}d", replay(snaps, FixedCooldown(c), roundtrip=roundtrip)))
    if gross_too:
        arms.append(("absorbing_gross", replay(snaps, RearmRule(), roundtrip=0.0)))
        for c in cooldowns:
            arms.append((f"rearm_{c}d_gross", replay(snaps, FixedCooldown(c), roundtrip=0.0)))

    out: Dict[str, object] = {"arms": {}, "events": {}, "splits": {}, "refused": {}}
    built: Dict[str, Tuple[List[str], Dict[str, List[float]]]] = {}
    for name, res in arms:
        out["events"][name] = {b: e._asdict() for b, e in res.events.items()}
        try:
            axis, books = books_from_replay(res, reentry_frac=reentry_frac)
        except ValueError as exc:
            # NOT swallowed and NOT worked around: an arm that cannot be built is REPORTED as
            # refused, with the reason, and left out of every table. Silently dropping it would
            # read as "the arm lost" when what actually happened is "the feed cannot carry it" —
            # and in this run that refusal is the finding (#76), not an inconvenience.
            out["refused"][name] = str(exc)
            continue
        built[name] = (axis, books)

    for split in splits:
        rows: Dict[str, Dict[str, Dict[str, float]]] = {}
        for name, (axis, books) in built.items():
            rows[name] = {
                "train": arm_metrics(axis, books, start=None, end=split),
                "test": arm_metrics(axis, books, start=split, end=None),
            }
        out["splits"][split] = rows
    out["arms"] = {name: sorted(books) for name, (axis, books) in built.items()}
    out["_built"] = built
    return out


def run_random_control(snaps: Sequence, *, cooldown: int, splits: Sequence[str] = SPLITS,
                       seeds: int = PERM_SEEDS, roundtrip: float = ROUNDTRIP,
                       reentry_frac: float = 1.0) -> Dict[str, object]:
    """Frequency-matched control for ONE cooldown: uniform{1..2C} waits over `seeds` seeds.

    Reported the way #72 reported its own: the median of the control, how many of the seeds
    BEAT the fixed rule, and the resulting one-sided p. A fixed cooldown that loses to coin
    flips of the same average patience is not a timing rule, and gets published as one.
    """
    out: Dict[str, object] = {"cooldown": cooldown, "seeds": seeds, "splits": {},
                              "refused_seeds": 0}
    fixed = replay(snaps, FixedCooldown(cooldown), roundtrip=roundtrip)
    try:
        f_axis, f_books = books_from_replay(fixed, reentry_frac=reentry_frac)
    except ValueError as exc:
        # The rule under test cannot be built on this feed. Reported, never worked around.
        out["refused"] = str(exc)
        for split in splits:
            out["splits"][split] = {"refused": str(exc)}
        return out
    controls: List[Tuple[List[str], Dict[str, List[float]]]] = []
    for s in range(seeds):
        res = replay(snaps, RandomCooldown(cooldown, s), roundtrip=roundtrip, seed=s)
        try:
            controls.append(books_from_replay(res, reentry_frac=reentry_frac))
        except ValueError:
            # A control draw that lands on a short wait hits the same wall as the short rungs of
            # the ladder. Counted and named — dropping it silently would bias the control toward
            # the long, tame waits and hand the fixed rule an easier opponent than it deserves.
            out["refused_seeds"] += 1
    if not controls:
        out["refused"] = "every control seed refused — no comparison is possible"
        for split in splits:
            out["splits"][split] = {"refused": out["refused"]}
        return out

    for split in splits:
        fixed_m = arm_metrics(f_axis, f_books, start=split, end=None)
        ctrl = [arm_metrics(a, b, start=split, end=None) for a, b in controls]
        beats_apy = sum(1 for c in ctrl if c["apy"] >= fixed_m["apy"])
        beats_calmar = sum(1 for c in ctrl if c["calmar"] >= fixed_m["calmar"])
        out["splits"][split] = {
            "fixed": fixed_m,
            "n_built": len(ctrl),
            "ctrl_median_apy": statistics.median([c["apy"] for c in ctrl]),
            "ctrl_median_calmar": statistics.median([c["calmar"] for c in ctrl]),
            "ctrl_min_apy": min(c["apy"] for c in ctrl),
            "ctrl_max_apy": max(c["apy"] for c in ctrl),
            "beats_apy": beats_apy,
            "beats_calmar": beats_calmar,
            "p_apy": (beats_apy + 1) / (len(ctrl) + 1),
            "p_calmar": (beats_calmar + 1) / (len(ctrl) + 1),
        }
    return out


# ─────────────────────────── #76 runner ───────────────────────────

def panel_health(axis: Sequence[str], books: Dict[str, List[float]], *,
                 start: Optional[str], end: Optional[str]) -> Dict[str, object]:
    """Per-book dispersion + the frozen share — #73's diagnosis, made comparable across arms."""
    _, sub = PRP.slice_books(axis, books, start, end)
    sds = {name: daily_sd_pct(eq) for name, eq in sub.items()}
    ranked = sorted(sds.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[0][1] if ranked else 0.0
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return {
        "sd_pct": sds,
        "frozen_pct": frozen_fraction(axis, books, start=start, end=end),
        "top_book": ranked[0][0] if ranked else None,
        "top_sd": top,
        "second_sd": second,
        "dominance": (top / second) if second > 0 else float("inf"),
    }


def run_idea76(series: Dict[str, object], *, splits: Sequence[str] = SPLITS,
               persist_grid: Sequence[int] = (1, 2, 3, 5),
               smooth_grid: Sequence[int] = (3, 5),
               roundtrip: float = ROUNDTRIP) -> Dict[str, object]:
    """#76: the noise evidence, then both repairs, on the same days and the same feeds.

    Arm naming is literal so no reader has to infer which repair produced a row:
      `baseline`      — the lab exactly as it is today (persist=1, raw ratio);
      `persistN`      — repair (B), the breach must hold N consecutive days;
      `smoothK`       — repair (A), causal median-of-K on the ratio, kill rule untouched;
      `smoothK+persistN` is deliberately NOT run: two repairs at once cannot be attributed.
    """
    out: Dict[str, object] = {"noise": noise_report(series), "arms": {}, "refused": {},
                              "events": {}, "splits": {}, "health": {}}
    built: Dict[str, Tuple[List[str], Dict[str, List[float]]]] = {}

    def add(name: str, ser: Dict[str, object], persist: int) -> None:
        feeds = feeds_from_series(ser)
        dates = sorted(feeds.available_dates())
        snaps = feeds.historical_snapshots(dates[0], dates[-1])
        res = replay(snaps, RearmRule(), roundtrip=roundtrip, persist_days=persist)
        out["events"][name] = {b: e._asdict() for b, e in res.events.items()}
        try:
            built[name] = books_from_replay(res)
        except ValueError as exc:
            out["refused"][name] = str(exc)

    add("baseline", series, 1)
    for k in persist_grid:
        if k > 1:
            add(f"persist{k}", series, k)
    for k in smooth_grid:
        add(f"smooth{k}", smooth_ratio_series(series, k), 1)

    for split in splits:
        rows = {}
        for name, (axis, books) in built.items():
            rows[name] = {"train": arm_metrics(axis, books, start=None, end=split),
                          "test": arm_metrics(axis, books, start=split, end=None)}
        out["splits"][split] = rows
    for name, (axis, books) in built.items():
        out["health"][name] = panel_health(axis, books, start=SPLITS[0], end=None)
    out["arms"] = sorted(built)
    out["_built"] = built
    return out


def one_book_law(axis: Sequence[str], books: Dict[str, List[float]], *,
                 start: Optional[str], end: Optional[str],
                 d_start: float = 0.01, d_full: float = 0.06) -> Dict[str, Dict[str, float]]:
    """#71's leave-one-out control, imported unchanged, re-run on whichever arm is handed in.

    `PRP.loo_per_book` is used as-is on purpose: if this run re-implemented it, a difference
    between the absorbing and re-armed panels could be a difference between two readings of the
    control instead of a property of the panel.
    """
    _, sub = PRP.slice_books(axis, books, start, end)
    return PRP.loo_per_book(sub, d_start=d_start, d_full=d_full)


# ─────────────────────────── parity against the published panel ───────────────────────────

def parity_with_panel(res: ReplayResult, panel_dir: Path = PRP.PANEL_DIR) -> Dict[str, object]:
    """How far this replay's `absorbing` arm sits from the panel written on disk.

    harness.py warns in its own docstring that a replay re-derives every past row from TODAY's
    feed data, so a gap here is EXPECTED and is information, not a failure. It is printed so no
    reader has to wonder whether the comparison arms were mixed: they never are — every #75/#76
    comparison is absorbing-vs-re-armed inside this one replay.
    """
    panel = RPE.load_panel(panel_dir)
    out: Dict[str, object] = {}
    for name, rets in sorted(res.returns.items()):
        disk = panel.get(name)
        if not disk:
            out[name] = {"status": "absent_on_disk"}
            continue
        common = sorted(set(rets) & set(disk))
        if not common:
            out[name] = {"status": "no_common_dates"}
            continue
        diffs = [abs(rets[d] - disk[d]) for d in common]
        out[name] = {
            "status": "compared",
            "common_days": len(common),
            "max_abs_diff_pct": max(diffs) * 100.0,
            "mean_abs_diff_pct": statistics.fmean(diffs) * 100.0,
            "identical_days": sum(1 for x in diffs if x < 1e-12),
        }
    return out


# ─────────────────────────── reporting ───────────────────────────

def _f(v: float, nd: int = 2) -> str:
    return f"{v:.{nd}f}"


def _pc(v: float, nd: int = 2) -> str:
    """Fraction → percent string. `PRP.metrics` returns apy/maxdd as FRACTIONS (its own printer
    multiplies by 100); printing them raw would understate every number by 100x."""
    return f"{v * 100.0:.{nd}f}%"


def _print_ladder(out: Dict[str, object], split: str) -> None:
    rows = out["splits"][split]
    print(f"\n  split {split} — equal-weight panel, 96 bp per re-admission [bt]")
    print("  | arm | TRAIN APY | TRAIN maxDD | TRAIN Calmar | TEST APY | TEST maxDD | TEST Calmar |")
    print("  |---|---|---|---|---|---|---|")
    for name in sorted(rows, key=lambda n: (n.endswith("_gross"), n)):
        tr, te = rows[name]["train"], rows[name]["test"]
        print(f"  | {name} | {_pc(tr['apy'])} | {_pc(tr['maxdd'])} | {_f(tr['calmar'])} "
              f"| {_pc(te['apy'])} | {_pc(te['maxdd'])} | {_f(te['calmar'])} |")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Ideas #75 RARM / #76 RARM-PANEL (advisory)")
    ap.add_argument("--refresh-feeds", action="store_true", help="ignore the /tmp feed cache")
    ap.add_argument("--reentry-frac", type=float, default=1.0)
    ap.add_argument("--control-cooldown", type=int, default=365)
    ap.add_argument("--seeds", type=int, default=PERM_SEEDS)
    ap.add_argument("--json-out", default="/tmp/spa_rearm_report.json")
    ap.add_argument("--parity", action="store_true", help="print the replay-vs-disk gap")
    args = ap.parse_args(argv)

    print("=" * 100)
    print("IDEAS #75 RARM / #76 RARM-PANEL — advisory backtest, OUTSIDE_RISKPOLICY, [bt] L0")
    print("in-memory replay of the aggressive-lab roster; data/aggressive_lab is READ-ONLY")
    print("=" * 100)

    series = load_feed_series(refresh=args.refresh_feeds)
    feeds = feeds_from_series(series)
    dates = sorted(feeds.available_dates())
    snaps = feeds.historical_snapshots(dates[0], dates[-1])
    print(f"\nreplay window: {dates[0]} .. {dates[-1]}  ({len(snaps)} days)")

    report: Dict[str, object] = {"window": [dates[0], dates[-1]], "n_days": len(snaps),
                                 "is_advisory": True, "outside_riskpolicy": True,
                                 "evidence": "L0", "marker": "[bt]"}

    if args.parity:
        base = replay(snaps, RearmRule())
        par = parity_with_panel(base)
        report["parity_vs_disk"] = par
        print("\nPARITY — this replay's `absorbing` arm vs the panel written on disk:")
        print("  | book | common days | identical | max |Δ| /day | mean |Δ| /day |")
        print("  |---|---|---|---|---|")
        for name, d in sorted(par.items()):
            if d.get("status") != "compared":
                print(f"  | {name} | — | — | — | {d.get('status')} |")
                continue
            print(f"  | {name} | {d['common_days']} | {d['identical_days']} "
                  f"| {_f(d['max_abs_diff_pct'], 4)}% | {_f(d['mean_abs_diff_pct'], 4)}% |")

    print("\n" + "-" * 100)
    print("IDEA #75 — RARM ladder")
    print("-" * 100)
    ladder = run_ladder(snaps, reentry_frac=args.reentry_frac)
    built = ladder.pop("_built")
    for split in SPLITS:
        _print_ladder(ladder, split)
    report["idea75_ladder"] = {"splits": ladder["splits"], "events": ladder["events"],
                               "refused": ladder["refused"]}
    if ladder["refused"]:
        print("\n  ARMS THAT COULD NOT BE BUILT — named, never silently dropped:")
        print("  | arm | why |")
        print("  |---|---|")
        for arm, why in sorted(ladder["refused"].items()):
            print(f"  | {arm} | {why} |")

    print("\n  kill / re-admission counts over the whole window:")
    print("  | arm | book | kills | re-admissions | dead days |")
    print("  |---|---|---|---|---|")
    for arm in ("absorbing", f"rearm_{args.control_cooldown}d"):
        for book, e in sorted(ladder["events"][arm].items()):
            if e["kills"] or e["rearms"]:
                print(f"  | {arm} | {book} | {e['kills']} | {e['rearms']} | {e['dead_days']} |")

    print("\n" + "-" * 100)
    print(f"IDEA #75 — frequency-matched control (uniform{{1..{2*args.control_cooldown}}}), "
          f"{args.seeds} seeds")
    print("-" * 100)
    ctrl = run_random_control(snaps, cooldown=args.control_cooldown, seeds=args.seeds,
                             reentry_frac=args.reentry_frac)
    report["idea75_control"] = ctrl
    if ctrl.get("refused_seeds"):
        print(f"  {ctrl['refused_seeds']} of {args.seeds} control seeds REFUSED to build (a short "
              f"random wait hits the same wall the short ladder rungs do) — counted, not dropped.")
    print("  | split | fixed APY | ctrl median APY | ctrl min..max | seeds beating fixed | p |")
    print("  |---|---|---|---|---|---|")
    for split in SPLITS:
        c = ctrl["splits"][split]
        if "refused" in c:
            print(f"  | {split} | REFUSED | — | — | — | {c['refused']} |")
            continue
        print(f"  | {split} | {_pc(c['fixed']['apy'])} | {_pc(c['ctrl_median_apy'])} "
              f"| {_pc(c['ctrl_min_apy'])}..{_pc(c['ctrl_max_apy'])} "
              f"| {c['beats_apy']}/{c['n_built']} | {_f(c['p_apy'], 3)} |")

    print("\n" + "-" * 100)
    print("IDEA #76 — RSN: the kill trigger reads a series whose own noise crosses its threshold")
    print("-" * 100)
    idea76 = run_idea76(series)
    built76 = idea76.pop("_built")
    report["idea76"] = idea76

    print("\n  1. THE EVIDENCE — daily statistics of every ratio the kills read, "
          "beside two control series [bt]:")
    print("  | series | n | sd %/day | lag-1 AC | worst − | worst + | days >5% | >8.33% | >12.5% "
          "| big moves reversed next day |")
    print("  |---|---|---|---|---|---|---|---|---|---|")
    for name, d in sorted(idea76["noise"].items(), key=lambda kv: (kv[1]["is_control"], kv[0])):
        print(f"  | {name} | {d['n']} | {_f(d['sd_pct'])} | {_f(d['lag1_autocorr'], 3)} "
              f"| {_f(d['min_pct'])}% | {_f(d['max_pct'])}% | {d['days_over_5pct']} "
              f"| {d['days_over_8_33pct']} | {d['days_over_12_5pct']} "
              f"| {d['n_reversed']}/{d['n_big']} ({_f(d['mean_reversed_frac'], 3)} of the move) |")

    print("\n  2. KILLS UNDER EACH REPAIR (whole window):")
    print("  | arm | books killed | total kills | dead book-days |")
    print("  |---|---|---|---|")
    for arm in sorted(idea76["events"]):
        ev = idea76["events"][arm]
        killed = [b for b, e in ev.items() if e["kills"]]
        print(f"  | {arm} | {len(killed)} ({', '.join(sorted(killed)) or '—'}) "
              f"| {sum(e['kills'] for e in ev.values())} "
              f"| {sum(e['dead_days'] for e in ev.values())} |")
    for arm, why in sorted(idea76["refused"].items()):
        print(f"  | {arm} | REFUSED | — | {why} |")

    print("\n  3. PANEL UNDER EACH REPAIR — equal weight, tail beside return [bt]:")
    for split in SPLITS:
        print(f"\n  split {split}")
        print("  | arm | TRAIN APY | TRAIN maxDD | TRAIN Calmar | TEST APY | TEST maxDD "
              "| TEST Calmar |")
        print("  |---|---|---|---|---|---|---|")
        for arm in sorted(idea76["splits"][split]):
            tr, te = idea76["splits"][split][arm]["train"], idea76["splits"][split][arm]["test"]
            print(f"  | {arm} | {_pc(tr['apy'])} | {_pc(tr['maxdd'])} | {_f(tr['calmar'])} "
                  f"| {_pc(te['apy'])} | {_pc(te['maxdd'])} | {_f(te['calmar'])} |")

    print("\n  4. PANEL HEALTH — #73's diagnosis recomputed on each arm (TEST window):")
    print("  | arm | frozen books % | loudest book | its sd %/day | next sd %/day | dominance |")
    print("  |---|---|---|---|---|---|")
    for arm in sorted(idea76["health"]):
        h = idea76["health"][arm]
        print(f"  | {arm} | {_f(h['frozen_pct'])}% | {h['top_book']} | {_f(h['top_sd'], 3)} "
              f"| {_f(h['second_sd'], 3)} | x{_f(h['dominance'])} |")

    print("\n  5. THE LAW OF ONE BOOK — #71's leave-one-out, imported unchanged, per arm")
    print("     (per-book PDE 1%-6% MINUS per-book binary guardian, ΔCalmar on TEST — the grid")
    print("      #71 published its own LOO table on, so the `baseline` column is that table):")
    law: Dict[str, object] = {}
    law_arms = [a for a in ("baseline", "persist2", "smooth3", "smooth5") if a in built76]
    for arm in law_arms:
        axis, books = built76[arm]
        law[arm] = one_book_law(axis, books, start=SPLITS[0], end=None)
    # the re-armed panel from #75 answers the ORIGINAL RARM-PANEL question and stays in the table
    rearm_arm = f"rearm_{args.control_cooldown}d"
    if rearm_arm in built:
        axis, books = built[rearm_arm]
        law[rearm_arm] = one_book_law(axis, books, start=SPLITS[0], end=None)
    report["idea76_loo"] = law
    cols = list(law)
    print("  | dropped | " + " | ".join(cols) + " |")
    print("  |---|" + "---|" * len(cols))
    drops = sorted(set().union(*[set(v) for v in law.values()])) if law else []
    for drop in drops:
        cells = []
        for c in cols:
            v = law[c].get(drop, {}).get("d_calmar")
            cells.append(_f(v) if v is not None else "—")
        print(f"  | {drop} | " + " | ".join(cells) + " |")

    Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True, default=str))
    print(f"\nreport → {args.json_out}")
    print("\nadvisory only · no capital moved · no agent deployed · data/ untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
