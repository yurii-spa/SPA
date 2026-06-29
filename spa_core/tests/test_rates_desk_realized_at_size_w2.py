"""
spa_core/tests/test_rates_desk_realized_at_size_w2.py — Lane B Phase-2 Week-2 verification.

Covers the W2 measurement-spine hardening built on top of W1:
  • B2.1 — the live-depth surface-freshness provenance block (auditable, fail-CLOSED)
  • B2.2 — the REAL venue-GROUP correlation collapse (consumes Lane A `shares_exit_venue` /
           `exit_venue`): shared-venue books are NOT additive; genuinely-independent books are.
           The honest non-additivity (N books on one rail plateau near the deepest single leg).
  • B2.3 — the haircut-fraction SENSITIVITY band: the verdict's load-bearing assumption is visible,
           and the verdict CAN FLIP across the band (the band has teeth).
  • B2.4 — concentrated-liquidity conservatism: the published constant-product fraction is NEVER
           optimistic vs the precise near-peg concentrated model (published ≤ concentrated), and the
           forced-unwind floor is ≤ the published number.
  • B2.5 — RED-TEAM: feed Sep-peak depth as if contemporaneous during the Oct-2025 trough → the
           killer test SHRINKS combined deployable with the trough (depth@size non-increasing in
           stress); the haircut is non-decreasing in frac and in group cardinality.

PURE / no network / deterministic / fail-CLOSED. Fixtures match the FROZEN Lane A data contract.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from spa_core.strategy_lab.rates_desk import depth_at_size as DAS
from spa_core.strategy_lab.rates_desk import realized_at_size as RAS


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FIXTURES — match the FROZEN Lane A data contract (incl. the W2 exit_venue field)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def _series_row(as_of, book_id, deployable, carry, floor=3.4, refusal="safe",
                shares_venue=True, exit_venue=None):
    row = {
        "as_of": as_of, "book_id": book_id, "market": f"PT-{book_id}", "maturity": "2026-12-31",
        "chain": "ethereum", "deployable_usd": deployable, "deployed_usd": deployable,
        "idle_usd": 0.0, "gross_carry_pct": carry + 0.5, "net_carry_after_slippage_pct": carry,
        "floor_pct": floor, "refusal_state": refusal, "shares_exit_venue": shares_venue,
        "prev_hash": "0" * 64, "row_hash": "deadbeef",
    }
    if exit_venue is not None:
        row["exit_venue"] = exit_venue
    return row


def _make_series(book_id, n_days, deployable, carry, floor=3.4, refusal="safe",
                 shares_venue=True, exit_venue=None):
    start = datetime.date(2026, 1, 1)
    return [
        _series_row((start + datetime.timedelta(days=i)).isoformat(), book_id, deployable, carry,
                    floor, refusal, shares_venue, exit_venue)
        for i in range(n_days)
    ]


def _surface(quotes, as_of="2026-06-29"):
    return {"as_of": as_of, "mode": "backtest", "quotes": quotes}


def _quote(market_id, underlying, tvl, exit_liq, as_of="2026-06-29", venue="pendle_pt"):
    return {"market_id": market_id, "underlying": underlying, "venue": venue,
            "tvl_usd": str(tvl), "exit_liquidity_usd": str(exit_liq), "as_of": as_of}


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B2.2 — the REAL venue-group collapse
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_b22_many_shared_books_collapse_toward_deepest_leg():
    """N books ALL on one shared rail collapse toward the DEEPEST single leg — NOT a flattering sum.

    5 books of $1M each on the same default shared bucket: naive $5M, but at frac=1 the venue
    collapses to the deepest single leg ($1M); at frac=0.5 the tail (4×$1M) is half-removed → $3M."""
    series = {f"b{i}": _make_series(f"b{i}", 40, 1_000_000, 8.0, shares_venue=True) for i in range(5)}
    res = RAS.run_killer_test(series)
    c = res["combined"]
    assert c["naive_sum_deployable_usd"] == pytest.approx(5_000_000, abs=0.01)
    assert c["n_exit_venues"] == 1  # all on one rail
    # frac=0.5 removes 50% of the 4 non-deepest legs = 0.5 · 4M = 2M → combined 3M
    assert c["correlation_haircut_usd"] == pytest.approx(2_000_000, abs=0.01)
    assert c["combined_deployable_usd"] == pytest.approx(3_000_000, abs=0.01)
    # at frac=1 the band's last point collapses to the deepest single leg ($1M)
    band = {b["haircut_frac"]: b for b in res["haircut_sensitivity"]["band"]}
    assert band[1.0]["combined_deployable_usd"] == pytest.approx(1_000_000, abs=0.01)


def test_b22_distinct_exit_venue_keys_are_additive():
    """Books with DISTINCT exit_venue keys are independent → fully additive (no haircut)."""
    series = {
        "a": _make_series("a", 40, 1_000_000, 8.0, shares_venue=True, exit_venue="usde_eth"),
        "b": _make_series("b", 40, 2_000_000, 8.0, shares_venue=True, exit_venue="usdc_arb"),
    }
    res = RAS.run_killer_test(series)
    c = res["combined"]
    assert c["n_exit_venues"] == 2
    assert c["correlation_haircut_usd"] == 0.0
    assert c["combined_deployable_usd"] == pytest.approx(3_000_000, abs=0.01)


def test_b22_w1_two_book_haircut_unchanged():
    """BACKWARD-COMPAT: the W1 two-shared-book case still haircuts 50% of the smaller leg."""
    series = {
        "a": _make_series("a", 40, 1_000_000, 8.0, shares_venue=True),
        "b": _make_series("b", 40, 2_000_000, 8.0, shares_venue=True),
    }
    res = RAS.run_killer_test(series)
    # one shared group [2M, 1M]: tail = [1M], haircut = 0.5·1M = 500k (matches W1)
    assert res["combined"]["correlation_haircut_usd"] == pytest.approx(500_000, abs=0.01)


def test_b22_haircut_nondecreasing_in_group_cardinality():
    """PROPERTY: adding another shared-venue book to a group can only INCREASE the haircut."""
    base = {f"b{i}": _make_series(f"b{i}", 40, 1_000_000, 8.0, shares_venue=True) for i in range(2)}
    more = {f"b{i}": _make_series(f"b{i}", 40, 1_000_000, 8.0, shares_venue=True) for i in range(4)}
    h2 = RAS.run_killer_test(base)["combined"]["correlation_haircut_usd"]
    h4 = RAS.run_killer_test(more)["combined"]["correlation_haircut_usd"]
    assert h4 >= h2


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B2.3 — the haircut SENSITIVITY band (the honesty crux)
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_b23_sensitivity_band_present_and_monotone():
    """The band sweeps the haircut fracs; combined deployable is NON-INCREASING in frac (more
    haircut → less deployable) and the haircut $ is NON-DECREASING in frac."""
    series = {f"b{i}": _make_series(f"b{i}", 40, 1_000_000, 8.0, shares_venue=True) for i in range(4)}
    res = RAS.run_killer_test(series)
    band = res["haircut_sensitivity"]["band"]
    assert [b["haircut_frac"] for b in band] == [0.0, 0.25, 0.5, 0.75, 1.0]
    combos = [b["combined_deployable_usd"] for b in band]
    haircuts = [b["correlation_haircut_usd"] for b in band]
    assert combos == sorted(combos, reverse=True)   # combined non-increasing in frac
    assert haircuts == sorted(haircuts)             # haircut non-decreasing in frac


def test_b23_verdict_can_FLIP_across_the_band_band_has_teeth():
    """THE CRUX: a book set engineered so the verdict FLIPS across the haircut band — at frac=0
    (fully additive) it SURVIVES at size, but at frac=1 (full collapse) it does NOT. The band must
    SHOW that the answer hinges on the haircut (verdict_stable_across_band == False)."""
    # 6 books @ $1.2M each, fat carry, ALL on one shared rail, 40 days.
    #  frac=0: combined = $7.2M deployed at ~12% → at $5M fully deployed → ~12% (860bps) → SURVIVES
    #  frac=1: collapses to deepest leg $1.2M → at $5M only 24% deployed →
    #          0.24·12 + 0.76·3.4 = 5.46% (206bps) ... tune carry so it falls below 200bps.
    series = {f"b{i}": _make_series(f"b{i}", 40, 1_200_000, 11.0, shares_venue=True) for i in range(6)}
    res = RAS.run_killer_test(series)
    hs = res["haircut_sensitivity"]
    band = {b["haircut_frac"]: b for b in hs["band"]}
    # at frac=0 it survives at the largest ticket; at frac=1 it does not survive past some smaller AUM
    assert band[0.0]["verdict"] == "SURVIVES_AT"
    assert band[1.0]["verdict"] == "DOES_NOT_SURVIVE_PAST"
    assert hs["verdict_stable_across_band"] is False  # the haircut IS load-bearing here → flagged


def test_b23_stable_band_when_data_insufficient():
    """When the realized track is too thin (< MIN_REALIZED_DAYS) the verdict is INSUFFICIENT_DATA at
    EVERY haircut frac → the band is stable (the answer does not hinge on the haircut yet)."""
    series = {f"b{i}": _make_series(f"b{i}", 3, 1_000_000, 12.0, shares_venue=True) for i in range(5)}
    res = RAS.run_killer_test(series)
    assert res["verdict"] == "INSUFFICIENT_DATA"
    assert res["haircut_sensitivity"]["verdict_stable_across_band"] is True
    assert {b["verdict"] for b in res["haircut_sensitivity"]["band"]} == {"INSUFFICIENT_DATA"}


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B2.4 — concentrated-liquidity conservatism: published is a LOWER bound, never optimistic
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_b24_published_frac_is_lower_bound_of_concentrated_model():
    """The published constant-product exit_frac is NEVER optimistic vs the precise near-peg
    concentrated model (published ≤ concentrated_near_peg_frac at every ticket)."""
    surf = _surface([_quote("0xdeep", "susde", tvl=200_000_000, exit_liq=50_000_000)])
    res = DAS.build_depth_at_size(write=False, surface=surf)
    m = res["markets"][0]
    el = float(m["exit_liquidity_usd"])
    DAS.assert_published_is_lower_bound(m)  # explicit (also runs inside build)
    for t in m["tickets"]:
        if t["exit_frac"] is None:
            continue
        ref = DAS.concentrated_near_peg_frac(el, float(t["ticket_usd"]))
        assert t["exit_frac"] <= ref + 1e-12


def test_b24_forced_unwind_floor_below_published():
    """The forced-unwind floor (a sell past the concentrated band) is ≤ the published fill at every
    ticket — the published number is itself conservative but the forced-unwind floor is even lower."""
    surf = _surface([_quote("0xdeep", "usde", tvl=200_000_000, exit_liq=40_000_000)])
    res = DAS.build_depth_at_size(write=False, surface=surf)
    m = res["markets"][0]
    for t in m["tickets"]:
        if t["exit_frac"] is None or t["forced_unwind_exit_frac"] is None:
            continue
        assert t["forced_unwind_exit_frac"] <= t["exit_frac"] + 1e-12
        assert t["forced_unwind_absorbable_usd"] <= t["absorbable_usd"] + 1e-6


def test_b24_optimistic_published_row_raises():
    """fail-CLOSED: a hand-forged row whose published frac EXCEEDS the concentrated bound RAISES."""
    el = 10_000_000.0
    # concentrated bound at $5M with kappa=2: one_sided = 10M, frac = 10M/15M = 0.667
    over = DAS.concentrated_near_peg_frac(el, 5_000_000) + 0.05  # optimistic by construction
    row = {
        "flagged": False, "market_id": "0xforge", "exit_liquidity_usd": el,
        "tickets": [{"ticket_usd": 5_000_000, "exit_frac": over}],
    }
    with pytest.raises(AssertionError):
        DAS.assert_published_is_lower_bound(row)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B2.5 — RED-TEAM: Oct-2025 stale-proxy replay shrinks deployable; depth@size non-increasing in stress
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_b25_stale_peak_proxy_in_trough_shrinks_combined_deployable():
    """The EXACT stale-proxy failure exit_liquidity_validation guards: a desk that sizes against the
    Sep PEAK depth as if it were contemporaneous in the Oct TROUGH overstates deployable. The killer
    test, fed the TRUE (collapsed) trough depth, must SHRINK the combined deployable vs the peak."""
    # PEAK book set (Sep): deep deployable per book.
    peak = {f"b{i}": _make_series(f"b{i}", 40, 4_000_000, 10.0, shares_venue=True) for i in range(3)}
    # TROUGH book set (Oct, USDe unwind): the SAME books but depth collapsed ~75% (deployable shrank).
    trough = {f"b{i}": _make_series(f"b{i}", 40, 1_000_000, 10.0, shares_venue=True) for i in range(3)}
    peak_combined = RAS.run_killer_test(peak)["combined"]["combined_deployable_usd"]
    trough_combined = RAS.run_killer_test(trough)["combined"]["combined_deployable_usd"]
    assert trough_combined < peak_combined  # the stress SHRINKS deployable, never inflates


def test_b25_depth_at_size_non_increasing_in_stress():
    """PROPERTY: depth@size is NON-INCREASING in stress — a shrinking pool TVL (peak→trough) can only
    REDUCE the absorbable at every ticket, never raise it (the proxy tracks the real drain)."""
    peak = _surface([_quote("0xpool", "susde", tvl=100_000_000, exit_liq=30_000_000)])
    trough = _surface([_quote("0xpool", "susde", tvl=25_000_000, exit_liq=7_500_000)])  # ~75% drain
    mp = DAS.build_depth_at_size(write=False, surface=peak)["markets"][0]
    mt = DAS.build_depth_at_size(write=False, surface=trough)["markets"][0]
    ap = {t["ticket_usd"]: t["absorbable_usd"] for t in mp["tickets"]}
    at = {t["ticket_usd"]: t["absorbable_usd"] for t in mt["tickets"]}
    for ticket in ap:
        if ap[ticket] is None or at[ticket] is None:
            continue
        assert at[ticket] <= ap[ticket] + 1e-6  # trough absorbable ≤ peak absorbable at every size


def test_b25_replay_determinism_with_sensitivity_band():
    """The full W2 payload (verdict + scores + venue exposure + sensitivity band) is byte-identical
    on replay — deterministic across the new haircut + sensitivity machinery."""
    import json
    series = {
        "a": _make_series("a", 40, 1_500_000, 9.0, shares_venue=True),
        "b": _make_series("b", 40, 900_000, 7.0, shares_venue=True, exit_venue="usdc_arb"),
    }
    payloads = [json.dumps(RAS.run_killer_test({k: list(v) for k, v in series.items()}),
                           sort_keys=True, default=str) for _ in range(3)]
    assert len(set(payloads)) == 1


def test_b25_surface_freshness_provenance_present():
    """B2.1 — the depth feed carries an auditable surface-freshness provenance block."""
    surf = _surface([_quote("0xdeep", "susde", 200_000_000, 50_000_000)], as_of="2026-06-29")
    res = DAS.build_depth_at_size(write=False, surface=surf)
    sf = res["surface_freshness"]
    assert sf["surface_as_of"] == "2026-06-29"
    assert sf["max_staleness_days"] == DAS.MAX_DEPTH_STALENESS_DAYS
    assert sf["n_stale_markets"] == 0  # contemporaneous quote → not stale


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B2.6 — the STANDING forward-measurement agent: daily, advisory, idempotent per UTC day
# ════════════════════════════════════════════════════════════════════════════════════════════════
def _books_dir_with(tmp_path, series_map):
    """Materialize a Lane-A-style books dir from a series_map for the agent's tick()."""
    bd = tmp_path / "books"
    for book_id, series in series_map.items():
        d = bd / book_id
        d.mkdir(parents=True)
        (d / "realized_series.jsonl").write_text(
            "".join(__import__("json").dumps(r) + "\n" for r in series), encoding="utf-8")
    return bd


def test_b26_agent_tick_writes_track_and_is_idempotent(tmp_path):
    """The standing agent appends ONE verdict row per UTC day; re-ticking the SAME day REFRESHES
    (replaces) that row, never duplicates — the track holds at most one row per UTC date."""
    from spa_core.strategy_lab.rates_desk import paper_realized_at_size as PRAS

    series = {f"b{i}": _make_series(f"b{i}", 40, 1_000_000, 8.0, shares_venue=True) for i in range(3)}
    bd = _books_dir_with(tmp_path, series)
    track = tmp_path / "track.jsonl"
    out = tmp_path / "realized_at_size.json"

    r1 = PRAS.tick(books_dir=bd, track_path=track, out_path=out, as_of_utc="2026-07-01")
    assert r1["track_len"] == 1 and r1["refreshed"] is False
    # re-tick SAME UTC day → refresh, still ONE row
    r2 = PRAS.tick(books_dir=bd, track_path=track, out_path=out, as_of_utc="2026-07-01")
    assert r2["track_len"] == 1 and r2["refreshed"] is True
    # a NEW UTC day → the track GROWS to two rows
    r3 = PRAS.tick(books_dir=bd, track_path=track, out_path=out, as_of_utc="2026-07-02")
    assert r3["track_len"] == 2 and r3["refreshed"] is False
    lines = [l for l in track.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert out.exists()


def test_b26_agent_fail_closed_on_empty_books(tmp_path):
    """fail-CLOSED: no books dir → an INSUFFICIENT_DATA row, never a fabricated survival."""
    from spa_core.strategy_lab.rates_desk import paper_realized_at_size as PRAS

    bd = tmp_path / "no_books"  # does not exist
    track = tmp_path / "track.jsonl"
    out = tmp_path / "realized_at_size.json"
    r = PRAS.tick(books_dir=bd, track_path=track, out_path=out, as_of_utc="2026-07-01")
    assert r["verdict"] == "INSUFFICIENT_DATA"
    assert r["track_len"] == 1
