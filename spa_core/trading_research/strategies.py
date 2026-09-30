"""Strategy families + the candidate registry.

A candidate is DATA, not code:

    family(+family_version) × params × asset × timeframe × direction × execution model

Every family is ONE pure, causal function `signal(bars, params) -> [target per bar]` where the target
at index t uses only bars[0..t] and means «position to hold from the NEXT bar's open»:
    +1 long · 0 flat · -1 short.
Direction `long_only` clips -1 to 0 (spot: cash → asset → cash); `long_short` keeps it (perpetual
paper model only). Adding a candidate never adds code; adding a family adds one function.

VERSIONING RULE. If a family's logic changes, bump its version: every candidate id embeds it, so old
forward evidence keeps its identity and the new logic starts a new history. A golden fingerprint test
(test_trading_research_backtest.py::test_family_fingerprints_are_pinned) fails if outputs change
without a version bump.

Provenance: all families are textbook public-domain technical rules (moving averages, Wilder RSI/ATR,
Appel MACD, Donchian channel, SuperTrend, Bollinger bands); no proprietary TradingView script is
copied.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import indicators as ind

Targets = List[int]


def _cols(bars):
    return ([b.open for b in bars], [b.high for b in bars], [b.low for b in bars], [b.close for b in bars])


def _hold(raw: List[Optional[int]]) -> Targets:
    """None = «no new instruction»: keep the previous target (0 during warm-up)."""
    out, cur = [], 0
    for v in raw:
        if v is not None:
            cur = v
        out.append(cur)
    return out


def f_ma_cross(bars, p):  # trend: fast MA above slow MA
    _, _, _, c = _cols(bars)
    f = (ind.ema if p.get("kind") == "ema" else ind.sma)(c, p["fast"])
    s = (ind.ema if p.get("kind") == "ema" else ind.sma)(c, p["slow"])
    return _hold([None if a is None or b is None else (1 if a > b else -1) for a, b in zip(f, s)])


def f_price_vs_ma(bars, p):  # trend: close vs long MA
    _, _, _, c = _cols(bars)
    m = ind.sma(c, p["n"])
    return _hold([None if v is None else (1 if x > v else -1) for x, v in zip(c, m)])


def f_momentum(bars, p):  # time-series momentum: n-bar rate of change beyond a threshold
    _, _, _, c = _cols(bars)
    n, th = p["n"], p.get("threshold", 0.0)
    raw: List[Optional[int]] = []
    for i, x in enumerate(c):
        if i < n:
            raw.append(None)
            continue
        r = x / c[i - n] - 1.0
        raw.append(1 if r > th else (-1 if r < -th else 0))
    return _hold(raw)


def f_donchian(bars, p):  # breakout: close above prior n-high enters, below prior m-low exits
    _, h, l, c = _cols(bars)
    hi, lo = ind.rolling_max(h, p["entry"]), ind.rolling_min(l, p["exit"])
    raw: List[Optional[int]] = [None]
    for i in range(1, len(c)):
        ph, pl = hi[i - 1], lo[i - 1]          # the channel of the PREVIOUS bar: no self-reference
        if ph is None or pl is None:
            raw.append(None)
        elif c[i] > ph:
            raw.append(1)
        elif c[i] < pl:
            raw.append(-1)
        else:
            raw.append(None)
    return _hold(raw)


def f_supertrend(bars, p):
    _, h, l, c = _cols(bars)
    return _hold(ind.supertrend(h, l, c, p["n"], p["mult"]))


def f_rsi_meanrev(bars, p):  # mean reversion: long below lo, exit above exit_level
    _, _, _, c = _cols(bars)
    r = ind.rsi(c, p["n"])
    raw: List[Optional[int]] = []
    for v in r:
        if v is None:
            raw.append(None)
        elif v < p["lo"]:
            raw.append(1)
        elif v > p["hi"]:
            raw.append(-1 if p.get("short_above_hi") else 0)
        else:
            raw.append(None)
    return _hold(raw)


def f_macd(bars, p):
    _, _, _, c = _cols(bars)
    line, sig = ind.macd(c, p["fast"], p["slow"], p["signal"])
    return _hold([None if a is None or b is None else (1 if a > b else -1) for a, b in zip(line, sig)])


def f_bollinger_meanrev(bars, p):  # long below lower band, exit at the mean
    _, _, _, c = _cols(bars)
    m, sd = ind.sma(c, p["n"]), ind.rolling_std(c, p["n"])
    raw: List[Optional[int]] = []
    for x, mu, s in zip(c, m, sd):
        if mu is None:
            raw.append(None)
        elif x < mu - p["k"] * s:
            raw.append(1)
        elif x > mu:
            raw.append(0)
        else:
            raw.append(None)
    return _hold(raw)


def f_trend_vol_filter(bars, p):  # trend (close > SMA n) only while ATR% is below a ceiling
    _, h, l, c = _cols(bars)
    m, a = ind.sma(c, p["n"]), ind.atr(h, l, c, p.get("atr_n", 14))
    raw: List[Optional[int]] = []
    for x, mu, av in zip(c, m, a):
        if mu is None or av is None:
            raw.append(None)
        elif av / x > p["max_atr_pct"]:
            raw.append(0)
        else:
            raw.append(1 if x > mu else -1)
    return _hold(raw)


def f_supertrend_and_ma(bars, p):  # combination of two independent signals: both must agree
    st = f_supertrend(bars, p)
    ma = f_price_vs_ma(bars, {"n": p["ma_n"]})
    return [a if a == b else 0 for a, b in zip(st, ma)]


#: family name -> (version, function). Bump the version whenever the function's output changes.
FAMILIES: Dict[str, tuple] = {
    "ma_cross": (1, f_ma_cross),
    "price_vs_ma": (1, f_price_vs_ma),
    "momentum": (1, f_momentum),
    "donchian": (1, f_donchian),
    "supertrend": (1, f_supertrend),
    "rsi_meanrev": (1, f_rsi_meanrev),
    "macd": (1, f_macd),
    "bollinger_meanrev": (1, f_bollinger_meanrev),
    "trend_vol_filter": (1, f_trend_vol_filter),
    "supertrend_and_ma": (1, f_supertrend_and_ma),
}
TREND_FAMILIES = {"ma_cross", "price_vs_ma", "momentum", "donchian", "supertrend", "macd",
                  "trend_vol_filter", "supertrend_and_ma"}

#: Parameter grids — deliberately modest; each point is one candidate per (tf, exec).
GRIDS: Dict[str, List[dict]] = {
    "ma_cross": [{"kind": k, "fast": f, "slow": s} for k in ("sma", "ema")
                 for f, s in ((10, 30), (20, 50), (50, 200))],
    "price_vs_ma": [{"n": n} for n in (50, 100, 200)],
    "momentum": [{"n": n, "threshold": 0.0} for n in (24, 72, 168)],
    "donchian": [{"entry": e, "exit": x} for e, x in ((20, 10), (55, 20))],
    "supertrend": [{"n": n, "mult": m} for n, m in ((10, 2.0), (10, 3.0), (20, 3.0))],
    "rsi_meanrev": [{"n": 14, "lo": lo, "hi": hi} for lo, hi in ((30, 55), (25, 50))],
    "macd": [{"fast": 12, "slow": 26, "signal": 9}],
    "bollinger_meanrev": [{"n": 20, "k": k} for k in (2.0, 2.5)],
    "trend_vol_filter": [{"n": 100, "max_atr_pct": m} for m in (0.02, 0.04)],
    "supertrend_and_ma": [{"n": 10, "mult": 3.0, "ma_n": 200}],
}

ASSETS = {"BTC": "BTCUSDT"}                 # v0; the registry is keyed by asset — ETH/SOL are one line
TIMEFRAMES_V0 = ("1h", "4h", "1D")
EXEC_MODELS = ("spot_long", "perp_ls_1x")   # see execution.py


@dataclass(frozen=True)
class Candidate:
    family: str
    family_version: int
    params: tuple                  # sorted (key, value) pairs — hashable and canonical
    asset: str
    timeframe: str
    exec_model: str

    @property
    def direction(self) -> str:
        return "long_only" if self.exec_model == "spot_long" else "long_short"

    def definition(self) -> dict:
        from .execution import EXEC_MODELS
        return {"family": self.family, "family_version": self.family_version,
                "params": dict(self.params), "asset": self.asset, "timeframe": self.timeframe,
                "direction": self.direction, "exec_model": self.exec_model,
                "exec_model_version": EXEC_MODELS[self.exec_model].version}

    @property
    def def_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.definition(), sort_keys=True).encode()).hexdigest()

    @property
    def id(self) -> str:
        return f"{self.family}@v{self.family_version}:{self.asset}:{self.timeframe}:{self.exec_model}:{self.def_hash[:10]}"

    def signal(self, bars) -> Targets:
        _, fn = FAMILIES[self.family]
        t = fn(bars, dict(self.params))
        return [max(0, v) for v in t] if self.direction == "long_only" else t


def registry(assets=tuple(ASSETS), timeframes=TIMEFRAMES_V0) -> List[Candidate]:
    """Every candidate of v0. Mean-reversion families run spot long-only; trend families also run in
    the long/short perpetual paper model (futures stay simulation-only)."""
    out = []
    for fam, grid in GRIDS.items():
        ver, _ = FAMILIES[fam]
        execs = EXEC_MODELS if fam in TREND_FAMILIES else ("spot_long",)
        for p, a, tf, ex in itertools.product(grid, assets, timeframes, execs):
            out.append(Candidate(fam, ver, tuple(sorted(p.items())), a, tf, ex))
    return out


def by_id() -> Dict[str, Candidate]:
    return {c.id: c for c in registry()}
