# FROZEN-DATE-OK: the date IS the subject - every literal date here is a Pendle
# maturity or an observation day, and the quantity under test is the arithmetic
# BETWEEN them (tau = maturity - day). No freshness window, no TTL, no "is it
# stale" question exists in these modules, so the calendar moving cannot change
# a single assertion; injecting a clock would inject nothing (the code never
# asks what time it is).
"""Controls for the Pendle-PT research loader and ideas #117 PTTS / #118 PTFF.

(The frozen-date decision for this file is recorded in the comment above, not here.)

Every test here is a positive control for a way the measurement could lie:

* the derived PT price could be inconsistent with the yield it came from;
* a missing series could be reported as zero instead of "not measured" (inv. #17);
* the #117 forward rate could peek at the row it is supposed to predict;
* a zero `underlying_yield` (USDe, by construction) could be mistaken for an
  observation of "no yield";
* an incomplete floating path could be silently padded instead of dropped;
* overlapping vintages could be counted as independent evidence.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _pt_history as H  # noqa: E402
import edge_pt_fixed_vs_float as PTFF  # noqa: E402
import edge_pt_term_structure as PTTS  # noqa: E402


def _market(symbol, maturity, underlying, kind, rows):
    return {
        "kind": kind,
        "market_address": "0x" + "0" * 40,
        "maturity": maturity,
        "method": "direct_api_implied",
        "pt_address": "0x" + "1" * 40,
        "series": rows,
        "symbol": symbol,
        "underlying": underlying,
    }


def _row(date, iy, uy=0.0, tvl=1_000_000.0):
    return {"date": date, "implied_yield": iy, "pt_price": None,
            "tvl_usd": tvl, "underlying_yield": uy}


def _write(tmp_path: Path, markets: dict) -> Path:
    data = tmp_path / "data"
    (data / "rates_desk").mkdir(parents=True, exist_ok=True)
    (data / "rates_desk" / "pendle_pt_history.json").write_text(
        json.dumps({"generated_at": "x", "markets": markets, "method": "test",
                    "underlyings": [], "window": {}})
    )
    return data


# ── derived price ────────────────────────────────────────────────────────────

def test_pt_price_is_the_inverse_of_the_yield_it_came_from():
    # PT redeems at 1: price at maturity is exactly 1, and the yield round-trips.
    assert H.pt_price(0.20, 0) == pytest.approx(1.0)
    p = H.pt_price(0.15, 182.5)
    implied = p ** (-365.0 / 182.5) - 1.0
    assert implied == pytest.approx(0.15, abs=1e-12)


def test_longer_tenor_at_the_same_yield_is_cheaper():
    assert H.pt_price(0.10, 180) < H.pt_price(0.10, 90) < H.pt_price(0.10, 30)


# ── third outcome, not zero (inv. #17) ──────────────────────────────────────

def test_missing_file_is_unmeasured_not_empty(tmp_path):
    with pytest.raises(H.Unmeasured):
        H.load(tmp_path / "nowhere")


def test_empty_markets_is_unmeasured_not_zero_markets(tmp_path):
    data = tmp_path / "data"
    (data / "rates_desk").mkdir(parents=True)
    (data / "rates_desk" / "pendle_pt_history.json").write_text(json.dumps({"markets": {}}))
    with pytest.raises(H.Unmeasured):
        H.load(data)


def test_scripts_exit_nonzero_when_the_series_is_absent(tmp_path, capsys):
    for main in (PTTS.main, PTFF.main):
        assert main(["--data-dir", str(tmp_path / "nowhere")]) == 3
        assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_zero_underlying_yield_is_not_an_observation(tmp_path):
    """USDe reports 0 on every row by construction. That is not 'the float rate is 0'."""
    data = _write(tmp_path, {
        "PT-USDe-1": _market("PT-USDe-1", "2025-06-30", "USDe", "stable_synth",
                             [_row("2025-01-01", 0.12, uy=0.0)]),
        "PT-sUSDe-1": _market("PT-sUSDe-1", "2025-06-30", "sUSDe", "stable_synth",
                              [_row("2025-01-01", 0.12, uy=0.05)]),
    })
    u = H.load(data)
    assert u["USDe"].has_float is False
    assert u["USDe"].float_rates() == {}
    assert u["sUSDe"].has_float is True
    out = PTFF.run(data)
    assert "unmeasured" in out["per_underlying"]["USDe"]


# ── #117: the forward rate must not peek ────────────────────────────────────

def _two_leg_panel(long_future_yield: float) -> H.Underlying:
    """One observation day with a short and a long leg, plus the long leg observed
    again on the day the short leg matures (the realization)."""
    u = H.Underlying("sUSDe")
    u.add("SHORT", "2025-02-10", _row("2025-01-01", 0.20, uy=0.05))   # tau = 40
    u.add("LONG", "2025-06-30", _row("2025-01-01", 0.10, uy=0.05))    # tau = 180
    u.add("LONG", "2025-06-30", _row("2025-02-10", long_future_yield, uy=0.05))
    return u


def test_forward_rate_does_not_read_the_row_it_predicts():
    base = PTTS.forward_bias(_two_leg_panel(0.08))
    moved = PTTS.forward_bias(_two_leg_panel(0.30))
    assert len(base) == len(moved) == 1
    # the forward is built from day-t rows only -> untouched by the future row
    assert base[0]["forward"] == pytest.approx(moved[0]["forward"])
    # the realization is the future row -> it must move, and the bias with it
    assert moved[0]["realized"] > base[0]["realized"]
    assert moved[0]["bias"] > base[0]["bias"]


def test_look_ahead_control_does_read_it_so_the_measure_can_discriminate():
    causal = PTTS.forward_bias(_two_leg_panel(0.30), look_ahead=False)[0]
    peeking = PTTS.forward_bias(_two_leg_panel(0.30), look_ahead=True)[0]
    assert causal["forward"] != pytest.approx(peeking["forward"])


def test_inverted_curve_is_reported_as_inverted():
    shape = PTTS.curve_shape(_two_leg_panel(0.08))
    assert shape["frac_upward"] == 0.0            # long 10% < short 20%
    assert shape["median_slope_per_30d_bp"] < 0


def test_legs_closer_than_the_minimum_gap_yield_no_slope():
    u = H.Underlying("wstETH")
    u.add("A", "2024-06-27", _row("2024-01-01", 0.05))
    u.add("B", "2024-06-27", _row("2024-01-01", 0.06))   # same maturity -> gap 0
    assert PTTS.curve_shape(u) is None


# ── #117: the shipped ladder simulator ──────────────────────────────────────

def _single_market_panel(iy: float = 0.10, n_days: int = 300) -> H.Underlying:
    u = H.Underlying("sUSDe")
    for i in range(n_days):
        day = H.shift("2025-01-01", i)
        if H.days(day, "2026-06-30") > 0:
            u.add("ONLY", "2026-06-30", _row(day, iy))
    return u


def _rolling_panel(n_days: int = 730, drift: float = 0.0) -> H.Underlying:
    """Quarterly maturities so the ladder actually rolls, and a yield that MOVES day to
    day — a constant-yield fixture cannot catch a one-day look-ahead."""
    u = H.Underlying("sUSDe")
    maturities = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31",
                  "2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"]
    for i in range(n_days):
        day = H.shift("2025-01-01", i)
        iy = 0.10 + drift * i + 0.02 * ((i % 7) - 3) / 3.0
        for m in maturities:
            tau = H.days(day, m)
            if 0 < tau <= 200:
                u.add(m, m, _row(day, iy))
    return u


def test_holding_one_pt_to_maturity_earns_its_implied_yield():
    r = PTTS.simulate_ladder(_single_market_panel(0.10), target_days=180, rt_bp=0.0)
    assert r["rolls"] == 0
    assert r["ann_pct"] == pytest.approx(10.0, abs=0.05)


def test_roll_cost_is_actually_charged_once_per_roll():
    free = PTTS.simulate_ladder(_rolling_panel(), 30, 0.0)
    paid = PTTS.simulate_ladder(_rolling_panel(), 30, 96.0)
    assert free["rolls"] >= 2, "fixture must roll, or this control proves nothing"
    assert paid["rolls"] == free["rolls"]
    # the whole cost is rolls * 96bp compounded; at minimum it must strictly bite
    assert paid["ann_pct"] < free["ann_pct"] - 0.5


def test_the_entry_price_comes_from_the_rows_of_that_same_day():
    """Causality control: a peeked entry (tomorrow's quote) is the bug this catches."""
    u = _rolling_panel(drift=0.0005)          # the yield must MOVE, or peeking is invisible
    r = PTTS.simulate_ladder(u, 90, 0.0)
    assert r["entries"], "fixture must enter at least once"
    for e in r["entries"]:
        same_day = u.obs[e["day"]][e["market"]]
        assert (e["tau"], e["implied_yield"]) == (same_day[0], same_day[1])


def test_the_curve_up_to_day_k_does_not_depend_on_anything_after_it():
    full = PTTS.simulate_ladder(_rolling_panel(n_days=600), 60, 0.0)
    short = PTTS.simulate_ladder(_rolling_panel(n_days=300), 60, 0.0)
    assert full["curve_fingerprint"][:300] == short["curve_fingerprint"][:300]


def test_degenerate_targets_are_named_not_silently_averaged(tmp_path):
    """One live market -> every target picks it -> the run must SAY so."""
    data = _write(tmp_path, {
        "PT-sUSDe-1": _market("PT-sUSDe-1", "2026-06-30", "sUSDe", "stable_synth",
                              [_row(H.shift("2025-01-01", i), 0.10, uy=0.05)
                               for i in range(300)]),
    })
    out = PTTS.run(data)["per_underlying"]["sUSDe"]
    assert out["ladder"]["frac_same"] == 1.0
    reported = {d["target_days"] for d in out["ladder_sim_degenerate"]}
    assert reported == {60, 90, 120, 180}          # all identical to target 30
    # and the fingerprint is stripped from the shipped result (it is a control, not a number)
    assert all("curve_fingerprint" not in r for r in out["ladder_sim"])


def test_an_empty_underlying_yields_no_simulation():
    assert PTTS.simulate_ladder(H.Underlying("sUSDe"), 30, 0.0) is None


# ── #118: vintages, coverage, regimes ───────────────────────────────────────

def _float_panel(n_float_days: int, float_rate: float = 0.05) -> H.Underlying:
    u = H.Underlying("sUSDe")
    for i in range(n_float_days):
        day = H.shift("2025-01-01", i)
        u.add("M", "2025-07-01", _row(day, 0.12, uy=float_rate))
    return u


def test_incomplete_float_path_drops_the_vintage_instead_of_padding_zeros():
    # tau = 181 on day 0; only 20 float days observed -> below the 80% floor
    short = PTFF.vintages(_float_panel(20))
    assert short == []
    # a fully covered panel does produce vintages
    assert PTFF.vintages(_float_panel(200)) != []


def test_advantage_is_fixed_minus_realized_float():
    v = PTFF.vintages(_float_panel(200, float_rate=0.05))[0]
    assert v["fixed"] == pytest.approx(0.12)
    assert v["realized_float"] == pytest.approx(0.05, abs=2e-4)
    assert v["advantage"] == pytest.approx(v["fixed"] - v["realized_float"])


def test_roll_frequency_counts_rolls_not_days(tmp_path):
    u = H.Underlying("sUSDe")
    for i in range(400):
        day = H.shift("2025-01-01", i)
        for market, maturity in (("A", "2025-06-30"), ("B", "2026-06-30")):
            if H.days(day, maturity) > 0:
                u.add(market, maturity, _row(day, 0.10, uy=0.04))
    rf = PTFF.roll_frequency(u)
    assert rf["rolls"] == 0          # the longest live market never expires in-window
    assert rf["rolls_per_year"] == 0.0


def test_no_vintages_is_unmeasured_not_a_clean_zero(tmp_path):
    data = _write(tmp_path, {
        "PT-sUSDe-1": _market("PT-sUSDe-1", "2026-06-30", "sUSDe", "stable_synth",
                              [_row("2025-01-01", 0.12, uy=0.05)]),
    })
    out = PTFF.run(data)["per_underlying"]["sUSDe"]
    assert "unmeasured" in out
    assert "advantage_all" not in out


# ── shared statistics ───────────────────────────────────────────────────────

def test_sign_test_is_two_sided_and_none_on_no_evidence():
    assert H.sign_test_p(0, 0) is None
    assert H.sign_test_p(5, 10) == pytest.approx(1.0)
    assert H.sign_test_p(10, 10) == pytest.approx(2.0 / 1024)
    assert H.sign_test_p(0, 10) == pytest.approx(2.0 / 1024)
    # large n used to overflow float (2**1588); it must still return a probability
    p = H.sign_test_p(1461, 1588)
    assert p is not None and 0.0 <= p < 1e-100


def test_non_overlapping_drops_vintages_inside_a_live_term():
    recs = [{"date": H.shift("2025-01-01", i), "tau": 90} for i in range(0, 200, 10)]
    kept = H.non_overlapping(recs)
    assert [r["date"] for r in kept] == ["2025-01-01", "2025-04-01", "2025-06-30"]
    assert len(kept) < len(recs)
