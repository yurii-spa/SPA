"""
spa_core/tests/test_refusal_engine.py — Rates-Desk PRODUCTION refusal engine tests.

Pure synthetic, hermetic (a FakeMarketData injects controlled live snapshots — no network).
Verifies the production contracts:
  - build_report scores every tracked underlying + writes valid, atomic JSON
  - a synthetic depegging underlying → REFUSE; a stable one → SAFE
  - fail-CLOSED: an underlying with no data → UNKNOWN (never a fabricated SAFE)
  - deterministic (same input → identical verdicts/scores)
  - refusal_verdict()/is_refused() advisory helpers read the file fail-closed
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json

import pytest

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.rates_desk import config as C
from spa_core.strategy_lab.rates_desk import refusal_engine as RE


# ── synthetic live data ──────────────────────────────────────────────────────────────────────
def _dates(n: int, start_ord: int = 739200):
    base = datetime.date.fromordinal(start_ord)
    return [(base + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _stable_ratio(ds):
    """Tight-peg LST: ratio hugs ~1.0 with tiny symmetric noise."""
    return {d: 1.0 + (0.0005 if i % 2 else -0.0005) for i, d in enumerate(ds)}


def _depegging_ratio(ds):
    """Toxic LRT: starts ~1.03 then grinds DOWN ~0.25%/day (sustained one-sided decay)."""
    out, r = {}, 1.03
    for d in ds:
        r *= (1.0 - 0.0025)
        out[d] = r
    return out


class FakeMarketData:
    """Minimal MarketData stand-in: latest() + historical_range() over injected per-symbol
    ratio series + a funding series. Builds real MarketSnapshots so the engine path is exercised
    exactly as in production."""

    def __init__(self, ratios_by_symbol, funding_by_date):
        self._ratios = ratios_by_symbol
        self._funding = funding_by_date
        all_dates = set(funding_by_date)
        for ser in ratios_by_symbol.values():
            all_dates |= set(ser)
        self._dates = sorted(all_dates)

    def latest(self):
        if not self._dates:
            raise InvalidDataError("latest: no data")  # mirrors MarketData.latest()
        return self._snap(self._dates[-1])

    def historical_range(self, start, end):
        return [self._snap(d) for d in self._dates if start <= d <= end]

    def _snap(self, date):
        snap = MarketSnapshot(date=date)
        if date in self._funding:
            snap.funding_rate_8h = self._funding[date]
        for sym, ser in self._ratios.items():
            if date in ser:
                snap.lrt_eth_ratio[sym] = ser[date]
        return snap


def _market(n=120, include=("ezeth", "steth")):
    ds = _dates(n)
    ratios = {}
    if "ezeth" in include:
        ratios["ezeth"] = _depegging_ratio(ds)
    if "steth" in include:
        ratios["steth"] = _stable_ratio(ds)
    funding = {d: (0.0001 if i % 2 else -0.0001) for i, d in enumerate(ds)}
    return FakeMarketData(ratios, funding)


# ── tests ──────────────────────────────────────────────────────────────────────────────────────
def test_build_report_scores_all_and_writes_valid_json(tmp_path):
    out = tmp_path / "refusal_status.json"
    rep = RE.build_report(write=True, market=_market(), out_path=out)

    # every tracked underlying scored
    syms = {u["symbol"] for u in rep["underlyings"]}
    assert syms == set(RE.TRACKED_UNDERLYINGS)
    # file written and re-readable as valid JSON with the same shape
    on_disk = json.loads(out.read_text())
    assert on_disk["model"] == "rates_desk_refusal_engine"
    assert on_disk["advisory"] is True
    assert {u["symbol"] for u in on_disk["underlyings"]} == set(RE.TRACKED_UNDERLYINGS)
    assert "verdict_counts" in on_disk and isinstance(on_disk["verdict_counts"], dict)


def test_depegging_refuses_stable_safe(tmp_path):
    out = tmp_path / "r.json"
    rep = RE.build_report(write=True, market=_market(include=("ezeth", "steth")), out_path=out)
    by_sym = {u["symbol"]: u for u in rep["underlyings"]}
    # the sustained depeg breaches the REFUSE threshold
    assert by_sym["ezeth"]["verdict"] == RE.REFUSE
    assert by_sym["ezeth"]["tail_score"] >= C.TAIL_REFUSE_THRESHOLD
    # the tight peg stays SAFE
    assert by_sym["steth"]["verdict"] == RE.SAFE
    assert by_sym["steth"]["tail_score"] <= C.SAFE_MEDIAN_BAND


def test_failclosed_unknown_on_missing_data(tmp_path):
    out = tmp_path / "r.json"
    # only ezeth has data; the others (incl. all LSTs) have NONE → must be UNKNOWN, never SAFE
    rep = RE.build_report(write=True, market=_market(include=("ezeth",)), out_path=out)
    by_sym = {u["symbol"]: u for u in rep["underlyings"]}
    for sym in RE.TRACKED_UNDERLYINGS:
        if sym == "ezeth":
            continue
        assert by_sym[sym]["verdict"] == RE.UNKNOWN
        assert by_sym[sym]["tail_score"] is None       # never fabricated
        assert by_sym[sym]["verdict"] != RE.SAFE


def test_no_data_at_all_all_unknown(tmp_path):
    """An empty market (no latest date) fails-closed to UNKNOWN for every underlying."""
    out = tmp_path / "r.json"
    rep = RE.build_report(write=True, market=FakeMarketData({}, {}), out_path=out)
    assert all(u["verdict"] == RE.UNKNOWN for u in rep["underlyings"])
    assert rep["verdict_counts"]["UNKNOWN"] == len(RE.TRACKED_UNDERLYINGS)


def test_deterministic(tmp_path):
    r1 = RE.build_report(write=False, market=_market())
    r2 = RE.build_report(write=False, market=_market())
    v1 = [(u["symbol"], u["verdict"], u["tail_score"]) for u in r1["underlyings"]]
    v2 = [(u["symbol"], u["verdict"], u["tail_score"]) for u in r2["underlyings"]]
    assert v1 == v2


def test_classify_bands():
    assert RE.classify(0.90, False) == RE.REFUSE
    assert RE.classify(C.TAIL_REFUSE_THRESHOLD, False) == RE.REFUSE
    assert RE.classify(C.SAFE_MEDIAN_BAND + 0.01, False) == RE.WATCH
    assert RE.classify(0.10, False) == RE.SAFE
    assert RE.classify(0.10, True) == RE.UNKNOWN          # fail-closed wins
    assert RE.classify(1.5, False) == RE.UNKNOWN          # malformed → UNKNOWN, not SAFE
    assert RE.classify(-0.1, False) == RE.UNKNOWN


def test_refusal_verdict_helper(tmp_path):
    out = tmp_path / "refusal_status.json"
    RE.build_report(write=True, market=_market(include=("ezeth", "steth")), out_path=out)
    v = RE.refusal_verdict("ezeth", status_path=out)
    assert v["verdict"] == RE.REFUSE
    assert v["symbol"] == "ezeth"
    assert RE.is_refused("ezeth", status_path=out) is True
    assert RE.is_refused("steth", status_path=out) is False
    # unscored / unknown symbol → fail-closed UNKNOWN (not refused, not fabricated SAFE)
    v2 = RE.refusal_verdict("doesnotexist", status_path=out)
    assert v2["verdict"] == RE.UNKNOWN


def test_refusal_verdict_missing_file(tmp_path):
    """No status file → fail-closed UNKNOWN (never SAFE)."""
    v = RE.refusal_verdict("ezeth", status_path=tmp_path / "absent.json")
    assert v["verdict"] == RE.UNKNOWN
    assert RE.is_refused("ezeth", status_path=tmp_path / "absent.json") is False
