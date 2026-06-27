"""
test_exit_nav.py — the quality bar for the LIQUIDATION-NAV-BY-SIZE surface.

The flagship investor-facing per-ticket exit schedule must withstand a Gauntlet/Chaos-Labs-grade
reviewer: a CONSERVATIVE LOWER BOUND tied to VALIDATED contemporaneous depth, monotonic in size,
fail-CLOSED on thin/absent/non-finite depth (visible holes, no fabrication), deterministic +
byte-identical, with reproducible per-row proof hashes. These tests pin every one of those
properties. PURE / no network / no live data mutation (write=False everywhere).
"""
from __future__ import annotations

import hashlib
import json
import math

import pytest

from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams
from spa_core.strategy_lab.rates_desk.exit_nav import (
    EXIT_TICKETS_USD,
    MODEL_NAME,
    VALIDATION_REF,
    build_exit_nav_schedule,
    compute_ticket_row,
)
from spa_core.strategy_lab.rwa_backstop.liquidation_nav import (
    MIN_DEX_POOL_TVL_USD,
    OPERATIONAL_HAIRCUT_BPS,
    dex_exit_frac,
)

_P = RatePolicyParams()


def _deep_book(depth_usd=50_000_000.0):
    """A book + surface with depth WELL above the floor so real numbers are produced."""
    book = {"market_id": "MKT", "underlying": "usdc", "gross_usd": 10_000_000.0,
            "as_of": "2026-06-25", "source": "hypothetical"}
    surface = {"as_of": "2026-06-25",
               "quotes": [{"market_id": "MKT", "underlying": "usdc",
                           "exit_liquidity_usd": depth_usd}]}
    return surface, book


# ── core defensibility: monotonic in size ────────────────────────────────────────────────────────
def test_haircut_monotonic_in_size():
    """Bigger ticket ⇒ haircut NON-DECREASING and net-of-gross fraction NON-INCREASING.

    This is THE property a reviewer checks: a conservative slippage bound must get worse, never
    better, as you try to exit more. Tested across the published ticket ladder on a deep pool."""
    surface, book = _deep_book(depth_usd=80_000_000.0)
    r = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
    rows = r["schedule"]
    assert len(rows) == len(EXIT_TICKETS_USD)
    # every row should clear the floor (deep pool) → real numbers
    assert all(not row["flagged"] for row in rows), [r2["flag_reason"] for r2 in rows]
    haircuts = [row["haircut_pct"] for row in rows]
    net_fracs = [row["net_proceeds_usd"] / row["gross_usd"] for row in rows]
    for i in range(1, len(rows)):
        assert rows[i]["ticket_usd"] > rows[i - 1]["ticket_usd"]
        assert haircuts[i] >= haircuts[i - 1] - 1e-9, (haircuts[i - 1], haircuts[i])
        assert net_fracs[i] <= net_fracs[i - 1] + 1e-9, (net_fracs[i - 1], net_fracs[i])
    # impact must also be monotonic up
    impacts = [row["price_impact_frac"] for row in rows]
    for i in range(1, len(impacts)):
        assert impacts[i] >= impacts[i - 1] - 1e-9


# ── fail-closed: thin/absent depth flagged, never fabricated ──────────────────────────────────────
@pytest.mark.parametrize("depth", [0.0, None, MIN_DEX_POOL_TVL_USD - 1.0, 1000.0])
def test_thin_depth_flagged_not_fabricated(depth):
    """Depth zero / None / below the DEX floor ⇒ net_proceeds & haircut are None, flagged True with
    the canonical reason, and NO numeric fill is invented."""
    row = compute_ticket_row(
        ticket_usd=100_000, gross_usd=100_000.0, depth_usd=depth,
        as_of="2026-06-25", data_source="rate_surface.exit_liquidity_usd", params=_P,
    )
    assert row["flagged"] is True
    assert row["flag_reason"] == "insufficient_contemporaneous_depth"
    assert row["net_proceeds_usd"] is None
    assert row["haircut_pct"] is None
    assert row["price_impact_frac"] is None
    assert row["time_to_exit_days"] is None
    assert row["within_one_tick"] is False
    # provenance still present on a hole
    assert row["as_of"] == "2026-06-25"
    assert row["model"] == MODEL_NAME
    assert row["proof_hash"]


def test_live_thin_book_all_flagged_is_honest():
    """A book whose contemporaneous depth is below the floor ⇒ EVERY ticket flagged. This is the
    HONEST live-book result for thin Pendle PT pools — not a bug, a visible hole."""
    book = {"market_id": "MKT", "underlying": "susde", "gross_usd": 7_000.0,
            "as_of": "2026-06-25", "source": "live"}
    surface = {"as_of": "2026-06-25",
               "quotes": [{"market_id": "MKT", "underlying": "susde",
                           "exit_liquidity_usd": 30_000.0}]}  # < $250k floor
    r = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
    assert r["flagged"] is True
    assert all(row["flagged"] for row in r["schedule"])
    assert all(row["net_proceeds_usd"] is None for row in r["schedule"])


# ── determinism: byte-identical JSON ⇒ identical proof_hash ───────────────────────────────────────
def test_determinism_byte_identical():
    """Same inputs ⇒ byte-identical serialized schedule (sans wall-clock generated_at) ⇒ identical
    per-row proof hashes."""
    surface, book = _deep_book()
    r1 = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
    r2 = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)

    def _canon(r):
        r = dict(r)
        r.pop("generated_at", None)
        return json.dumps(r, sort_keys=True, separators=(",", ":"), default=str)

    assert _canon(r1) == _canon(r2)
    assert [row["proof_hash"] for row in r1["schedule"]] == [row["proof_hash"] for row in r2["schedule"]]


# ── robustness: non-finite/negative never leaks out ───────────────────────────────────────────────
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -1.0, -1e9])
def test_non_finite_safe(bad):
    """NaN / inf / negative depth ⇒ never NaN/inf out: clamped/flagged to a clean hole."""
    row = compute_ticket_row(
        ticket_usd=1_000_000, gross_usd=1_000_000.0, depth_usd=bad,
        as_of="2026-06-25", data_source="x", params=_P,
    )
    # must be a clean fail-closed hole, no NaN/inf escaping
    for k in ("net_proceeds_usd", "haircut_pct", "price_impact_frac"):
        v = row[k]
        assert v is None or (isinstance(v, float) and math.isfinite(v))
    assert row["flagged"] is True
    # the primitive itself never returns a non-finite number
    f = dex_exit_frac(bad, 1_000_000.0)
    assert f is None or (math.isfinite(f) and 0.0 <= f <= 1.0)
    # and bad SIZE is equally safe
    assert dex_exit_frac(1_000_000.0, bad) is None or math.isfinite(dex_exit_frac(1_000_000.0, bad))


def test_non_finite_size_safe():
    """A non-finite ticket/size never produces NaN/inf — the primitive fail-closes to None."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert dex_exit_frac(50_000_000.0, bad) is None


# ── proof hash reproducible from published inputs ─────────────────────────────────────────────────
def test_proof_hash_reproducible():
    """Recompute each row's proof_hash INDEPENDENTLY from the row's published inputs ⇒ matches.

    A reviewer (or investor) can verify every published number was derived from the published depth +
    model, not retro-fitted."""
    surface, book = _deep_book()
    r = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
    for row in r["schedule"]:
        # reconstruct EXACTLY the canonical input dict the engine hashes (from published fields)
        row_inputs = {
            "ticket_usd": int(row["ticket_usd"]),
            "gross_usd": round(float(row["gross_usd"]), 6),
            "depth_usd": (None if row["depth_usd"] is None else round(float(row["depth_usd"]), 6)),
            "as_of": row["as_of"],
            "model": row["model"],
            "model_params": row["model_params"],
            "data_source": row["data_source"],
        }
        blob = json.dumps(row_inputs, sort_keys=True, separators=(",", ":"), default=str)
        recomputed = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        assert recomputed == row["proof_hash"], row["ticket_usd"]


# ── conservative bound: net ≤ gross always ────────────────────────────────────────────────────────
def test_conservative_bound():
    """Modeled net proceeds ≤ gross for every ticket, every depth — the bound never over-states."""
    for depth in (300_000.0, 1_000_000.0, 50_000_000.0, 1e12):
        surface, book = _deep_book(depth_usd=depth)
        r = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
        for row in r["schedule"]:
            if row["net_proceeds_usd"] is not None:
                assert row["net_proceeds_usd"] <= row["gross_usd"] + 1e-6
                assert 0.0 <= row["price_impact_frac"] <= 1.0


def test_net_proceeds_includes_op_haircut():
    """Even an INFINITE-depth pool still loses the operational haircut — nothing is frictionless."""
    surface, book = _deep_book(depth_usd=1e15)  # ~zero slippage
    r = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
    row = r["schedule"][0]
    op = OPERATIONAL_HAIRCUT_BPS / 10_000.0
    # net ≈ gross*(1 - op) at infinite depth (slippage→0, routing applies inside frac)
    assert row["net_proceeds_usd"] < row["gross_usd"]
    assert row["haircut_pct"] >= op * 100.0 - 1e-6


# ── provenance + honest envelope present ───────────────────────────────────────────────────────────
def test_provenance_present():
    """Every row carries as_of/depth_usd/model/data_source; the envelope carries is_advisory/basis/
    validation_ref + the conservative-bound label."""
    surface, book = _deep_book()
    r = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
    # envelope
    assert r["is_advisory"] is True
    assert "conservative lower bound" in r["basis"].lower()
    assert r["validation_ref"] == VALIDATION_REF
    assert "Oct-2025" in r["validation_ref"]
    assert r["model"] == MODEL_NAME
    assert "lower bound" in r["model_label"].lower()
    assert r["llm_forbidden"] is True
    assert "aggregat" in r["depth_basis"].lower()  # single-market, NOT aggregated
    # per row
    for row in r["schedule"]:
        assert "as_of" in row and row["as_of"]
        assert "depth_usd" in row
        assert row["model"] == MODEL_NAME
        assert row["data_source"]
        assert row["proof_hash"]


def test_time_to_exit_one_tick_rule():
    """time_to_exit_days = ceil(ticket / (max_size_frac_of_exit × depth)) — the §9 one-tick cap."""
    depth = 1_000_000.0
    surface, book = _deep_book(depth_usd=depth)
    r = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
    max_frac = float(_P.max_size_frac_of_exit)
    daily = max_frac * depth
    for row in r["schedule"]:
        if row["time_to_exit_days"] is not None:
            expected = math.ceil(row["ticket_usd"] / daily)
            assert row["time_to_exit_days"] == expected
            assert row["within_one_tick"] == (expected == 1)


def test_single_market_depth_not_aggregated():
    """Two quotes on the same underlying ⇒ engine picks ONE (the deepest), never sums them."""
    book = {"market_id": "NOPE", "underlying": "usdc", "gross_usd": 1_000_000.0,
            "as_of": "2026-06-25", "source": "hypothetical"}
    surface = {"as_of": "2026-06-25", "quotes": [
        {"market_id": "A", "underlying": "usdc", "exit_liquidity_usd": 10_000_000.0},
        {"market_id": "B", "underlying": "usdc", "exit_liquidity_usd": 40_000_000.0},
    ]}
    r = build_exit_nav_schedule(write=False, surface=surface, deep={}, book=book)
    # deepest single quote = 40M, NOT 50M (the sum)
    assert r["depth_usd"] == pytest.approx(40_000_000.0)


def test_history_fallback_depth():
    """No surface match ⇒ priority (b): derive depth from deep Pendle PT history tvl_usd × band."""
    from spa_core.strategy_lab.rates_desk import config
    book = {"market_id": "0xabc", "underlying": "usde", "gross_usd": 1_000_000.0,
            "as_of": "2026-06-25", "source": "live"}
    surface = {"as_of": "2026-06-25", "quotes": []}  # no surface depth
    deep = {"markets": {"PT-USDe-X": {
        "underlying": "USDe", "market_address": "0xabc",
        "series": [{"date": "2026-06-20", "tvl_usd": 100_000_000.0},
                   {"date": "2026-06-25", "tvl_usd": 200_000_000.0}],
    }}}
    r = build_exit_nav_schedule(write=False, surface=surface, deep=deep, book=book)
    band = float(config.EXIT_PRICE_IMPACT_BAND_BPS) / 10_000.0
    assert r["data_source"].startswith("pendle_pt_history")
    # contemporaneous (<= as_of) latest = 200M × band
    assert r["depth_usd"] == pytest.approx(200_000_000.0 * band)


def test_write_atomic_and_readable(tmp_path):
    """write=True ⇒ a valid JSON file is produced atomically (no half-write); re-readable."""
    surface, book = _deep_book()
    out = tmp_path / "exit_nav.json"
    r = build_exit_nav_schedule(write=True, surface=surface, deep={}, book=book, out_path=out)
    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["model"] == MODEL_NAME
    assert loaded["schedule"][0]["proof_hash"] == r["schedule"][0]["proof_hash"]
