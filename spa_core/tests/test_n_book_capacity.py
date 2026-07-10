"""Tests for the Q2-1 N-book capacity aggregator (spa_core/strategy_lab/rates_desk/n_book_capacity.py).

Verifies the honest deterministic properties: the above-floor $/yr curve is monotone non-decreasing and
plateaus; the spread is read from the real compression curve; the plateau is rail-limited (stacking
same-rail books adds ~nothing at the margin); fail-closed on missing capacity input. Uses injected
fixtures — no live network, no dependence on the live venue cache being present.
"""
import json

import pytest

from spa_core.strategy_lab.rates_desk import n_book_capacity as nbc


# a compact but realistic single-book compression curve (matches capacity.py shape: spread decays with AUM)
_CAP_FIXTURE = {
    "rwa_floor_pct": 3.4,
    "aum_levels": [
        {"aum_usd": 100000.0, "book_net_apy_pct": 6.09},
        {"aum_usd": 250000.0, "book_net_apy_pct": 5.65},
        {"aum_usd": 500000.0, "book_net_apy_pct": 4.52},
        {"aum_usd": 1000000.0, "book_net_apy_pct": 3.96},
        {"aum_usd": 10000000.0, "book_net_apy_pct": 3.46},
    ],
}

# two rails: rail A (3 books, deep) and rail B (2 books) → additive across rails, haircut within
_BOOKS_FIXTURE = [
    {"book_id": "a1", "venue": "railA", "contribution_usd": 100000.0},
    {"book_id": "a2", "venue": "railA", "contribution_usd": 50000.0},
    {"book_id": "b1", "venue": "railB", "contribution_usd": 80000.0},
    {"book_id": "a3", "venue": "railA", "contribution_usd": 30000.0},
    {"book_id": "b2", "venue": "railB", "contribution_usd": 20000.0},
]


@pytest.fixture(autouse=True)
def _inject(monkeypatch):
    monkeypatch.setattr(nbc, "_load_capacity", lambda: dict(_CAP_FIXTURE))
    monkeypatch.setattr(nbc, "_live_books",
                        lambda: (list(_BOOKS_FIXTURE), {"haircut_frac": 0.5}))


def test_spread_fn_matches_compression_and_clamps():
    spread, floor = nbc._spread_fn(_CAP_FIXTURE)
    assert floor == 3.4
    # at $100k the above-floor spread is 6.09-3.4 = 2.69pp
    assert spread(100000.0) == pytest.approx(2.69, abs=1e-6)
    # below/above the measured range clamps flat (never extrapolates a fabricated spread)
    assert spread(1.0) == pytest.approx(2.69, abs=1e-6)
    assert spread(1e12) == pytest.approx(3.46 - 3.4, abs=1e-6)
    # interpolates between points, and never negative
    mid = spread(375000.0)
    assert 4.52 - 3.4 <= mid <= 5.65 - 3.4
    assert spread(5e11) >= 0.0


def test_curve_monotone_and_plateaus():
    rep = nbc.build_report(write=False)
    curve = rep["curve"]
    assert [r["n_books"] for r in curve] == [1, 2, 3, 4, 5]
    af = [r["above_floor_usd_per_yr"] for r in curve]
    # monotone non-decreasing (adding a book never REDUCES above-floor $)
    assert all(af[i] <= af[i + 1] + 1e-6 for i in range(len(af) - 1))
    # plateau is the max and equals the full-book value here (flattening, not falling)
    assert rep["plateau_above_floor_usd_per_yr"] == pytest.approx(af[-1], abs=1e-6)


def test_rail_limited_marginal_value():
    """Stacking a 3rd same-rail book (a3) adds far less than opening the first book of a NEW rail."""
    rep = nbc.build_report(write=False)
    c = {r["n_books"]: r for r in rep["curve"]}
    # book 3 (b1) opens rail B → n_rails goes 1→2, a real additive jump
    assert c[3]["n_rails"] == 2
    jump_new_rail = c[3]["above_floor_usd_per_yr"] - c[2]["above_floor_usd_per_yr"]
    # book 4 (a3) is a 3rd railA book → shared depth → small marginal add
    add_same_rail = c[4]["above_floor_usd_per_yr"] - c[3]["above_floor_usd_per_yr"]
    assert jump_new_rail > add_same_rail
    assert rep["n_distinct_rails"] == 2


def test_deterministic_and_advisory():
    a = nbc.build_report(write=False)
    b = nbc.build_report(write=False)
    assert a == b
    assert a["is_advisory"] is True and a["llm_forbidden"] is True


def test_fail_closed_on_missing_capacity(monkeypatch):
    def _boom():
        raise RuntimeError("capacity.json unreadable")
    monkeypatch.setattr(nbc, "_load_capacity", _boom)
    with pytest.raises(RuntimeError):
        nbc.build_report(write=False)


def test_write_roundtrip(tmp_path, monkeypatch):
    out = tmp_path / "n_book_capacity.json"
    monkeypatch.setattr(nbc, "_OUT_JSON", out)
    rep = nbc.build_report(write=True)
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk["curve"] == rep["curve"]
