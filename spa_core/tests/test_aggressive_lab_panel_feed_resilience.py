"""spa_core/tests/test_aggressive_lab_panel_feed_resilience.py — POSITIVE CONTROLS for the three
research-panel defects diagnosed in docs/AGGRESSIVE_PANEL_FEEDS.md (2026-08-16).

Every test in this file reproduces a REAL failure of the aggressive_lab research panel and is RED on
the code as it stood before the fix. This is the research layer (advisory, outside RiskPolicy) — no
money path, no kill-switch, no live track is touched by anything here.

  DEFECT 1 — `lp_eth_stable` died PERMANENTLY on the first day without an ETH price: `EthStableLP.
             _kill` called `market.require("eth_price")` unguarded and `kill_check` turned the
             resulting InvalidDataError into an irreversible kill, even though the book declares
             `accrual_gap_is_safe_hold=True`. Absence of an observation is not an observation of a
             catastrophe: no data ⇒ PAUSE with a named reason, then resume.

  DEFECT 2 — `_ratio_mtm` compared the two nearest PRESENT ratio prints, not two calendar days: a
             hole in the series collapsed into ONE "daily" jump, multiplied by leverage, and the
             book was falsely liquidated (measured: 3× dies on a single −5.6% print, 2× on −12.5%;
             a 30-day hole with a 6% drift killed the 3× book). A change over N missing days must
             be judged as a change over N days.

  DEFECT 3 — `PriceFeed.history` fetched ALL 8 tokens (btc/tbtc/cbbtc included — the panel uses
             none of them) and `_parse_chart` raised on a token with no points, so `run.py`
             blanked BOTH the ETH price and every ratio at once. One unneeded token could black
             out the whole panel.

Time is an INPUT here, never the environment: every snapshot carries an explicit ISO date and no
test reads the wall clock.

# FROZEN-DATE-OK: injected-clock — every date in this file is an explicit ARGUMENT (MarketSnapshot.
# date, start_date/end_date, the chart timestamps built from those same dates), and nothing here
# calls datetime.now() or compares anything to the wall clock. Both sides of every assertion are
# pinned to the same anchor, so the calendar moving cannot change a single outcome. The dates are
# also the SUBJECT in defect 2: the whole point is that 2024-06-01 → 2024-07-01 is thirty days and
# must not be read as one.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as _dt

import pytest

from spa_core.strategy_lab.aggressive_lab import feeds as af
from spa_core.strategy_lab.aggressive_lab import run as lab_run
from spa_core.strategy_lab.aggressive_lab.roster import (
    EthStableLP,
    LeverageLoop,
    LeveredRestaking,
)
from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.data import price_feed as pf_mod
from spa_core.strategy_lab.data.price_feed import CHAIN, TOKENS, PriceFeed

LP_FEE_APY = 0.18


def _lp_snap(date: str, eth: float | None) -> MarketSnapshot:
    """One panel day for the LP book: the fee APY is always supplied, the ETH price may be absent."""
    snap = MarketSnapshot(date=date, defi_apy={"lp_eth_stable": LP_FEE_APY})
    if eth is None:
        snap.gaps.add("eth_price_usd")
    else:
        snap.eth_price_usd = float(eth)
    return snap


def _ratio_snap(date: str, ratio: float, staking: float = 0.03) -> MarketSnapshot:
    """One panel day for the levered staking books: real staking APY + real stETH/ETH ratio."""
    return MarketSnapshot(
        date=date,
        restaking_apy={"steth": staking},
        lrt_eth_ratio={"steth": float(ratio)},
    )


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# DEFECT 1 — a missing ETH price must PAUSE lp_eth_stable, never kill it
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_lp_eth_stable_pauses_on_missing_eth_price_and_resumes():
    """Two days without an ETH price must be a PAUSE, and the book must resume when the price
    returns. Before the fix the very first gap day killed it forever (unguarded require in _kill)."""
    book = EthStableLP()
    book.init(100_000.0, {})

    days = [
        _lp_snap("2024-06-01", 3000.0),
        _lp_snap("2024-06-02", None),      # gap
        _lp_snap("2024-06-03", None),      # gap
        _lp_snap("2024-06-04", 3010.0),    # the feed returns
    ]
    equities, holds = [], []
    for snap in days:
        book.step(snap)
        book.kill_check(snap)
        equities.append(book.equity())
        holds.append(book.metrics().extra.get("hold_reason") or "")

    assert book.metrics().extra["killed"] is False, (
        f"a data gap killed the book: {book.metrics().extra['kill_reason']}")
    # the gap days did not advance the book (no fabricated accrual) ...
    assert equities[1] == equities[0]
    assert equities[2] == equities[0]
    # ... and the book RESUMED once the real price came back.
    assert equities[3] > equities[0]
    # each pause is NAMED, never silent (invariant 2), and the name clears when the book resumes
    assert "eth_price" in holds[1] and "eth_price" in holds[2]
    assert holds[0] == "" and holds[3] == ""


def test_lp_kill_condition_is_unevaluable_without_a_price_on_its_own():
    """The book's OWN guard, independent of the global safe-hold policy: `EthStableLP._kill` measures
    an LP drawdown against the ETH price, so without a price there is no drawdown to measure — the
    same guard `LrtNeutral._kill` has always had. Pinned separately so removing it is visible even
    while `kill_check` also tolerates gaps for safe-hold books."""

    class _NoSafeHoldLP(EthStableLP):
        id = "lp_eth_stable_probe"
        accrual_gap_is_safe_hold = False        # the policy layer will NOT save it here

    book = _NoSafeHoldLP()
    book.init(100_000.0, {})
    book.step(_lp_snap("2024-06-01", 3000.0))
    assert book.kill_check(_lp_snap("2024-06-02", None)).triggered is False
    assert book.metrics().extra["killed"] is False


def test_kill_check_gap_is_a_pause_only_for_safe_hold_books():
    """`kill_check` must distinguish 'cannot evaluate the kill' from 'the kill fired'. For a book
    that declares accrual_gap_is_safe_hold it is a pause; for a book that does not, the documented
    fail-CLOSED kill is preserved (this test would go red if the fix over-reached)."""

    class _NeedsPrice(EthStableLP):
        id = "gap_probe_safe_hold"

        def _kill(self, market):                       # noqa: D401 - deliberately unguarded
            market.require("eth_price")
            return (False, "")

    class _NeedsPriceNoHold(_NeedsPrice):
        id = "gap_probe_fail_closed"
        accrual_gap_is_safe_hold = False

    gap = _lp_snap("2024-06-02", None)

    soft = _NeedsPrice()
    soft.init(100_000.0, {})
    res = soft.kill_check(gap)
    assert res.triggered is False
    assert soft.metrics().extra["killed"] is False
    assert "eth_price" in (soft.metrics().extra.get("hold_reason") or "")

    hard = _NeedsPriceNoHold()
    hard.init(100_000.0, {})
    assert hard.kill_check(gap).triggered is True
    assert hard.metrics().extra["killed"] is True


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# DEFECT 2 — a hole in the ratio series must not be spliced into one "daily" levered jump
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_levered_restaking_3x_survives_a_30_day_hole_with_a_6pct_drift():
    """The documented killer: a 30-day hole with a 6% stETH/ETH drift. −6% × 3 = −18% breaches the
    3× maintenance buffer (−16.7%) only if the whole drift is read as ONE day. Per day it is −0.21%."""
    book = LeveredRestaking()
    book.init(100_000.0, {})

    book.step(_ratio_snap("2024-06-01", 1.0))
    book.kill_check(_ratio_snap("2024-06-01", 1.0))
    later = _ratio_snap("2024-07-01", 0.94)            # 30 calendar days later, −6%
    book.step(later)
    book.kill_check(later)

    extra = book.metrics().extra
    assert extra["killed"] is False, f"false liquidation: {extra['kill_reason']}"
    # the real move is NOT discarded — it is booked in full, just not judged as a one-day print
    assert extra["cum_mtm_pct"] == pytest.approx(-18.0, abs=0.5)


def test_leverage_loop_2x_survives_a_30_day_hole_with_a_13pct_drift():
    """Same mechanism one leverage step down: 2× dies on a single −12.5% print. A −13% drift spread
    over 30 days is −0.46%/day — nowhere near the cliff."""
    book = LeverageLoop()
    book.init(100_000.0, {})

    book.step(_ratio_snap("2024-06-01", 1.0))
    book.kill_check(_ratio_snap("2024-06-01", 1.0))
    later = _ratio_snap("2024-07-01", 0.87)            # 30 calendar days later, −13%
    book.step(later)
    book.kill_check(later)

    extra = book.metrics().extra
    assert extra["killed"] is False, f"false liquidation: {extra['kill_reason']}"
    assert extra["cum_mtm_pct"] == pytest.approx(-26.0, abs=0.5)


def test_a_genuine_one_day_crash_still_liquidates_the_2x_loop():
    """NEGATIVE CONTROL — the fix must not disarm the real liquidation tail. Consecutive calendar
    days with a −13% ratio crash in ONE day is exactly the event the buffer exists for."""
    book = LeverageLoop()
    book.init(100_000.0, {})
    for date, ratio in (("2024-06-01", 1.0), ("2024-06-02", 0.87)):
        snap = _ratio_snap(date, ratio)
        book.step(snap)
        book.kill_check(snap)
    assert book.metrics().extra["killed"] is True
    assert "liquidat" in book.metrics().extra["kill_reason"]


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# DEFECT 3 — one token without points must not black out the panel's whole price selection
# ──────────────────────────────────────────────────────────────────────────────────────────────────
_WINDOW = ("2024-06-01", "2024-06-05")
_DATES = ["2024-06-01", "2024-06-02", "2024-06-03", "2024-06-04", "2024-06-05"]
_DEAD_TOKENS = ("btc", "tbtc", "cbbtc")     # the wrapped-BTC family the panel never reads


def _chart(addr: str, base: float) -> dict:
    pts = [{"timestamp": int(_dt.datetime.fromisoformat(d + "T00:00:00+00:00").timestamp()),
            "price": base + i}
           for i, d in enumerate(_DATES)]
    return {"coins": {f"{CHAIN}:{addr}": {"symbol": "X", "prices": pts}}}


def _empty_chart(addr: str) -> dict:
    """A token that did not exist yet in the window — the cbBTC case (deployed Sept-2024)."""
    return {"coins": {f"{CHAIN}:{addr}": {"symbol": "X", "prices": []}}}


class _PanelFetcher:
    """Live-shaped chart fetcher: every panel token has points, the BTC family has none."""

    def __init__(self):
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        for sym, addr in TOKENS.items():
            if addr.lower() in url.lower():
                if sym in _DEAD_TOKENS:
                    return _empty_chart(addr)
                return _chart(addr, 3000.0 if sym == "eth" else 3090.0)
        raise AssertionError(f"no route for {url}")


def test_price_history_can_skip_a_pointless_token_instead_of_refusing_everything():
    """A token with no points must cost only THAT token, and the cause must be named — not swallowed."""
    feed = PriceFeed(fetcher=_PanelFetcher(), page_delay_s=0)
    hist = feed.history(start_date=_WINDOW[0], end_date=_WINDOW[1],
                        symbols=("eth", "steth", "cbbtc"), tolerate_missing_tokens=True)
    assert "eth" in hist and hist["eth"]["2024-06-01"] == 3000.0
    assert "steth" in hist
    assert "cbbtc" not in hist
    assert "cbbtc" in feed.last_history_errors
    assert "cbbtc" in feed.last_history_errors["cbbtc"]        # the cause names the token


def test_price_history_still_refuses_when_no_token_has_data():
    """fail-CLOSED is preserved at the level that matters: nothing usable ⇒ a named refusal."""
    class _AllDead(_PanelFetcher):
        def __call__(self, url):
            for addr in TOKENS.values():
                if addr.lower() in url.lower():
                    return _empty_chart(addr)
            raise AssertionError(url)

    feed = PriceFeed(fetcher=_AllDead(), page_delay_s=0)
    with pytest.raises(InvalidDataError):
        feed.history(start_date=_WINDOW[0], end_date=_WINDOW[1],
                     symbols=("eth", "steth"), tolerate_missing_tokens=True)


def test_panel_price_and_ratio_series_survive_a_dead_btc_token(monkeypatch):
    """THE PANEL-LEVEL POSITIVE CONTROL. cbBTC/tBTC have no points in the replay window; the panel
    reads neither. Before the fix `_real_history_feeds` requested all 8 tokens, `_parse_chart` raised
    on the first pointless one, and BOTH eth_price_series and lrt_ratio_series were set to None —
    the whole panel went dark on a token it does not use."""
    pt_series = {d: 0.10 for d in _DATES}
    monkeypatch.setattr(af, "load_real_susde_history", lambda: (pt_series, dict(pt_series)))

    fetcher = _PanelFetcher()

    class _InjectedPriceFeed(PriceFeed):
        def __init__(self, *a, **kw):
            super().__init__(fetcher=fetcher, page_delay_s=0)

    monkeypatch.setattr(pf_mod, "PriceFeed", _InjectedPriceFeed)

    # keep the funding / restaking feeds off the network — they are not what this test measures
    from spa_core.strategy_lab.data import funding_feed as ff_mod
    from spa_core.strategy_lab.data import restaking_feed as rf_mod

    class _NoFeed:
        def __init__(self, *a, **kw):
            pass

        def history(self, *a, **kw):
            raise InvalidDataError("offline in test")

    monkeypatch.setattr(ff_mod, "FundingFeed", _NoFeed)
    monkeypatch.setattr(rf_mod, "RestakingFeed", _NoFeed)

    feeds = lab_run._real_history_feeds()

    assert feeds._eth, "the ETH price series was blanked by a token the panel never uses"
    assert feeds._eth["2024-06-01"] == 3000.0
    assert feeds._ratio and feeds._ratio.get("steth"), "the LRT/LST ratios were blanked too"
    # and the panel did not even ask for the BTC family
    assert not any(TOKENS[sym].lower() in u.lower() for u in fetcher.calls for sym in _DEAD_TOKENS)
