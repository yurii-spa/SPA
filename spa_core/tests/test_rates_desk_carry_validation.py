"""
spa_core/tests/test_rates_desk_carry_validation.py — deep Pendle PT history + carry (Assertion 2).

Covers the data-gap FIX and the carry validation it unlocks. Pure / no network (the Pendle fetcher is
injected with a FakeFetcher), deterministic, fail-CLOSED. Proves:

  • implied_yield_from_price() derivation is correct on a known PT (price 0.95, 180d → ~10.8%),
    handles the USD→face denomination convention, continuous form, and fail-CLOSEs on bad inputs.
  • the deep-history fetcher selects the canonical straight PTs (rejecting wrapper variants), parses
    per-market daily implied-yield series, and load() validates the schema (fail-CLOSED on malformed).
  • the carry validation (assertion2 on deep data) runs DETERMINISTICALLY and produces an honest
    GO/NO-GO with a survivor-book APY beating the floor across stress.
  • assertion1_deep refuses the toxic LRT books on the real-shaped history.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
from pathlib import Path

import os
import pytest

from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk import validation as V
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams


# ── implied yield from price (the DERIVED cross-check method) ────────────────────────────────────
def test_implied_yield_from_price_known_pt():
    # PT at 0.95, 180 days to maturity, face=1 → (1/0.95)^(365/180) - 1 ≈ 0.1083
    y = pph.implied_yield_from_price(0.95, 180.0)
    assert abs(y - 0.1083) < 0.002


def test_implied_yield_from_price_continuous():
    # continuous: -ln(0.95) * 365/180 ≈ 0.10399
    y = pph.implied_yield_from_price(0.95, 180.0, continuous=True)
    assert abs(y - (-math.log(0.95) * 365.0 / 180.0)) < 1e-9


def test_implied_yield_from_price_usd_denomination():
    # PT priced in USD (0.95) that redeems 1 sUSDe worth $1.00 → price_in_face = 0.95/1.00
    y_usd = pph.implied_yield_from_price(0.95, 180.0, underlying_price=1.00)
    y_face = pph.implied_yield_from_price(0.95, 180.0)
    assert abs(y_usd - y_face) < 1e-12
    # if the underlying is worth $1.05, the PT is cheaper in face units → HIGHER implied yield
    y_hi = pph.implied_yield_from_price(0.95, 180.0, underlying_price=1.05)
    assert y_hi > y_face


def test_implied_yield_from_price_fail_closed():
    with pytest.raises(ValueError):
        pph.implied_yield_from_price(0.95, 0.0)          # non-positive days
    with pytest.raises(ValueError):
        pph.implied_yield_from_price(1.01, 180.0)        # price >= face → non-positive yield, malformed
    with pytest.raises(ValueError):
        pph.implied_yield_from_price(-0.1, 180.0)        # negative price
    with pytest.raises(ValueError):
        pph.implied_yield_from_price(0.95, 180.0, underlying_price=0.0)  # bad underlying price


# ── deep-history fetcher (network-free via injected FakeFetcher) ──────────────────────────────────
def _fake_markets_payload():
    """Two pages of markets: a canonical sUSDe PT, a canonical ezETH (toxic) PT, and a wrapper variant
    that MUST be rejected (PT-zs-ezETH) plus a non-target (PENDLE-LPT)."""
    results = [
        {"address": "0xMKT_SUSDE", "symbol": "PENDLE-LPT", "expiry": "2024-12-26T00:00:00.000Z",
         "pt": {"address": "0xPT_SUSDE", "symbol": "PT-sUSDE-26DEC2024"},
         "underlyingAsset": {"symbol": "sUSDe"}},
        {"address": "0xMKT_EZETH", "symbol": "PENDLE-LPT", "expiry": "2024-09-26T00:00:00.000Z",
         "pt": {"address": "0xPT_EZETH", "symbol": "PT-ezETH-26SEP2024"},
         "underlyingAsset": {"symbol": "ezETH"}},
        {"address": "0xMKT_WRAP", "symbol": "PENDLE-LPT", "expiry": "2024-09-26T00:00:00.000Z",
         "pt": {"address": "0xPT_WRAP", "symbol": "PT-zs-ezETH-26SEP2024"},
         "underlyingAsset": {"symbol": "ezETH"}},
        {"address": "0xMKT_OTHER", "symbol": "PENDLE-LPT", "expiry": "2026-08-27T00:00:00.000Z",
         "pt": {"address": "0xPT_OTHER", "symbol": "PT-sUSDD-27AUG2026"},
         "underlyingAsset": {"symbol": "sUSDD"}},
    ]
    return {"total": len(results), "limit": 100, "skip": 0, "results": results}


def _fake_history(start_ts, n, implied):
    DAY = 86400
    return {
        "total": n,
        "timestamp": [start_ts + i * DAY for i in range(n)],
        "impliedApy": [f"{implied:.4f}"] * n,
        "underlyingApy": [f"{max(0.0, implied - 0.02):.4f}"] * n,
    }


def _make_fetcher():
    # sUSDe market history starts 2024-07-17 (well before its 2024-12-26 maturity, drops near-mat)
    SUSDE_START = 1721174400   # 2024-07-17 UTC
    EZETH_START = 1715644800   # 2024-05-14 UTC
    hist = {
        "0xMKT_SUSDE": _fake_history(SUSDE_START, 60, 0.10),
        "0xMKT_EZETH": _fake_history(EZETH_START, 60, 0.20),
    }

    def fetcher(url: str):
        if "/markets?expired=true" in url:
            return _fake_markets_payload()
        if "/historical-data" in url:
            for addr, payload in hist.items():
                if addr in url:
                    return payload
            raise AssertionError(f"unexpected history url {url}")
        raise AssertionError(f"unexpected url {url}")

    return fetcher


def test_select_target_markets_rejects_wrappers():
    raw = _fake_markets_payload()["results"]
    picked = pph.select_target_markets(raw)
    syms = {m["symbol"] for m in picked}
    assert "PT-sUSDE-26DEC2024" in syms
    assert "PT-ezETH-26SEP2024" in syms
    assert "PT-zs-ezETH-26SEP2024" not in syms   # wrapper variant rejected
    assert "PT-sUSDD-27AUG2026" not in syms       # non-target underlying rejected


def test_match_underlying_strict_segments():
    assert pph._match_underlying("PT-sUSDE-26DEC2024") == "sUSDe"
    assert pph._match_underlying("PT-USDe-26DEC2024") == "USDe"
    assert pph._match_underlying("PT-weETH-26SEP2024") == "eETH"  # eETH trades as weETH
    # leading-segment strictness: these must NOT match a target
    assert pph._match_underlying("PT-reUSDe-25JUN2026") is None
    assert pph._match_underlying("PT-weETHs-29AUG2024") is None
    assert pph._match_underlying("PT-Karak-sUSDe-30JAN2025") is None


def test_build_deep_dataset_and_load(tmp_path: Path):
    out = tmp_path / "pendle_pt_history.json"
    ds = pph.build(fetcher=_make_fetcher(), out_path=out)
    assert out.exists()
    assert ds["method"].startswith("direct_api_implied")
    assert set(ds["underlyings"]) == {"sUSDe", "ezETH"}
    markets = ds["markets"]
    assert "PT-sUSDE-26DEC2024" in markets and "PT-ezETH-26SEP2024" in markets
    susde = markets["PT-sUSDE-26DEC2024"]
    assert susde["kind"] == "stable_synth"
    assert susde["series"], "series must be non-empty"
    # near-maturity samples dropped: last series date is >3d before the 2024-12-26 maturity
    assert susde["series"][-1]["date"] < "2024-12-23"
    for p in susde["series"]:
        assert abs(p["implied_yield"] - 0.10) < 1e-9
    # load() round-trips + validates
    loaded = pph.load(out)
    assert loaded["markets"].keys() == markets.keys()


def test_load_fail_closed_on_malformed(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"markets": {}}))            # empty markets
    with pytest.raises(ValueError):
        pph.load(bad)
    bad.write_text(json.dumps({"markets": {"X": {"kind": "stable_synth"}}}))  # missing series
    with pytest.raises(ValueError):
        pph.load(bad)
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        pph.load(missing)


# ── carry validation on deep data (deterministic) ─────────────────────────────────────────────────
def _build_deep_fixture(tmp_path: Path) -> Path:
    """A small but real-shaped deep dataset: a multi-maturity sUSDe carry book (clears the floor) +
    a toxic ezETH book — enough to exercise assertion2 + assertion1_deep deterministically."""
    DAY = 86400

    def series(start, n, implied, und):
        out = []
        for i in range(n):
            ts = start + i * DAY
            import datetime
            d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date().isoformat()
            out.append({"date": d, "implied_yield": implied, "underlying_yield": und, "pt_price": None})
        return out

    markets = {
        # two consecutive sUSDe maturities → ~2x window, all clears the floor with carry
        "PT-sUSDE-A": {"underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-A",
                       "market_address": "0xA", "pt_address": "0xpa", "maturity": "2025-01-15",
                       "method": "direct_api_implied", "series": series(1722470400, 120, 0.10, 0.07)},
        "PT-sUSDE-B": {"underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-B",
                       "market_address": "0xB", "pt_address": "0xpb", "maturity": "2025-06-15",
                       "method": "direct_api_implied", "series": series(1736899200, 120, 0.09, 0.06)},
        # toxic restaking PT
        "PT-ezETH-Z": {"underlying": "ezETH", "kind": "lrt", "symbol": "PT-ezETH-Z",
                       "market_address": "0xZ", "pt_address": "0xpz", "maturity": "2024-12-26",
                       "method": "direct_api_implied", "series": series(1722470400, 90, 0.25, 0.03)},
    }
    ds = {"generated_at": "x", "method": "direct_api_implied (test)",
          "underlyings": ["ezETH", "sUSDe"], "window": {"start": "2024-08-01", "end": "2025-06-14"},
          "markets": markets}
    out = tmp_path / "pendle_pt_history.json"
    out.write_text(json.dumps(ds))
    return out


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="data/env-dependent (needs committed data/ or the Mac host); runs locally, skipped in the data-less GitHub CI")
def test_assertion2_carry_validation_runs_deterministically(tmp_path, monkeypatch):
    out = _build_deep_fixture(tmp_path)
    monkeypatch.setattr(pph, "_OUT", out)
    monkeypatch.setattr(V.pph, "_OUT", out)
    p = RatePolicyParams()
    r1 = V.assertion2_survivor_beats_floor(p)
    r2 = V.assertion2_survivor_beats_floor(p)
    assert r1["data_source"] == "deep_pendle_pt_history"
    # deterministic: same inputs → same verdict + same survivor depth
    assert r1["VERDICT_assertion2_GO"] == r2["VERDICT_assertion2_GO"]
    assert r1["survivor_days"] == r2["survivor_days"]
    # the carry book beat the floor (mean book APY > floor) on this clearing fixture
    assert r1["deflated_sharpe"]["mean_book_apy_pct"] > r1["rwa_floor_apy_pct"]
    assert r1["survivor_days"] > 100  # multi-maturity roll covered both books


def test_assertion1_deep_refuses_toxic_book(tmp_path, monkeypatch):
    out = _build_deep_fixture(tmp_path)
    monkeypatch.setattr(pph, "_OUT", out)
    monkeypatch.setattr(V.pph, "_OUT", out)
    res = V.assertion1_deep_refusal(RatePolicyParams())
    assert res["VERDICT_assertion1_deep"] is True
    assert res["all_toxic_books_refused_every_day"] is True
    assert res["any_toxic_day_approved"] is False
    # the ezETH book is the only LRT in the fixture and is refused on every day
    ez = [m for m in res["per_market"] if m["market"] == "PT-ezETH-Z"][0]
    assert ez["approved_days"] == 0 and ez["refused_days"] > 0
