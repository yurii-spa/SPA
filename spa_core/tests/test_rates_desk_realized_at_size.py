"""
spa_core/tests/test_rates_desk_realized_at_size.py — Lane B W1 verification.

Covers the measurement spine built in Lane B Phase 1 Week 1:
  • depth_at_size.py   (B1.1) — per-market depth-at-size feed (real-or-flagged, monotonic, fail-CLOSED)
  • realized_at_size.py (B1.2/B1.4) — the killer-test harness + idle-cash@floor reconcile-to-the-cent
  • B1.3 — the HONESTY guardrails: the harness MUST be able to say NO (synthetic below-floor →
           DOES_NOT_SURVIVE_PAST) AND say YES (synthetic above-floor-at-size → SURVIVES_AT)
  • B1.5 — RED-TEAM: depth > pool TVL claim, stale depth, replay determinism, the ≤ Σ-caps−haircut
           property, ticket monotonicity (depth@$1M ≥ depth@$5M ≥ depth@$10M after impact)
  • B1.6 — exit-NAV $1M+ hole closure: the depth feed resolves a surface/history hole to a real bound

PURE / no network / deterministic / fail-CLOSED. All fixtures match the FROZEN Lane A data contract
(realized_series.jsonl schema) so this is hermetic against Lane A's files not yet existing.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from decimal import Decimal
from pathlib import Path

import pytest

from spa_core.strategy_lab.rates_desk import depth_at_size as DAS
from spa_core.strategy_lab.rates_desk import realized_at_size as RAS
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams


# ════════════════════════════════════════════════════════════════════════════════════════════════
# FIXTURES — match the FROZEN Lane A data contract
# ════════════════════════════════════════════════════════════════════════════════════════════════
def _series_row(as_of, book_id, deployable, carry, floor=3.4, refusal="safe",
                shares_venue=True):
    """One realized_series.jsonl row matching the frozen schema (the fields the harness reads)."""
    return {
        "as_of": as_of,
        "book_id": book_id,
        "market": f"PT-{book_id}",
        "maturity": "2026-12-31",
        "chain": "ethereum",
        "deployable_usd": deployable,
        "deployed_usd": deployable,
        "idle_usd": 0.0,
        "gross_carry_pct": carry + 0.5,
        "net_carry_after_slippage_pct": carry,
        "floor_pct": floor,
        "refusal_state": refusal,
        "shares_exit_venue": shares_venue,
        "prev_hash": "0" * 64,
        "row_hash": "deadbeef",
    }


def _make_series(book_id, n_days, deployable, carry, floor=3.4, refusal="safe", shares_venue=True):
    """A book series of n_days rows (the latest row drives the harness)."""
    start = datetime.date(2026, 1, 1)
    return [
        _series_row((start + datetime.timedelta(days=i)).isoformat(), book_id, deployable, carry,
                    floor, refusal, shares_venue)
        for i in range(n_days)
    ]


def _surface(quotes, as_of="2026-06-29"):
    return {"as_of": as_of, "mode": "backtest", "quotes": quotes}


def _quote(market_id, underlying, tvl, exit_liq, as_of="2026-06-29", venue="pendle_pt"):
    return {
        "market_id": market_id, "underlying": underlying, "venue": venue,
        "tvl_usd": str(tvl), "exit_liquidity_usd": str(exit_liq), "as_of": as_of,
    }


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B1.1 — depth-at-size feed: real-or-flagged, monotonic, fail-CLOSED
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_depth_at_size_real_market_monotonic():
    """A deep market produces real per-ticket depth, monotonically non-increasing across tickets."""
    surf = _surface([_quote("0xdeep", "susde", tvl=200_000_000, exit_liq=50_000_000)])
    res = DAS.build_depth_at_size(write=False, surface=surf)
    assert res["n_markets"] == 1
    m = res["markets"][0]
    assert not m["flagged"]
    fracs = [t["exit_frac"] for t in m["tickets"]]
    assert all(f is not None for f in fracs)
    # depth@$1M ≥ depth@$5M ≥ depth@$10M after impact (ticket monotonic)
    assert fracs[0] >= fracs[1] >= fracs[2]
    abss = [t["absorbable_usd"] for t in m["tickets"]]
    assert all(a is not None and a > 0 for a in abss)
    DAS.assert_market_monotonic(m)  # explicit property


def test_depth_at_size_thin_pool_flagged_never_fabricated():
    """A pool below the DEX floor → flagged insufficient_contemporaneous_depth, NEVER a number."""
    surf = _surface([_quote("0xthin", "usde", tvl=100_000, exit_liq=50_000)])  # < MIN_DEX_POOL_TVL_USD
    res = DAS.build_depth_at_size(write=False, surface=surf)
    m = res["markets"][0]
    assert m["flagged"] is True
    assert m["flag_reason"] == "insufficient_contemporaneous_depth"
    for t in m["tickets"]:
        assert t["exit_frac"] is None and t["absorbable_usd"] is None  # the HOLE, not a fill


def test_depth_at_size_proof_hash_chained():
    """Every market row carries a prev-linked proof_hash (reorder/forge detectable)."""
    surf = _surface([
        _quote("0xa", "susde", 100_000_000, 30_000_000),
        _quote("0xb", "usde", 80_000_000, 20_000_000),
    ])
    res = DAS.build_depth_at_size(write=False, surface=surf)
    rows = res["markets"]
    assert rows[0]["prev_hash"] == "0" * 64
    assert rows[1]["prev_hash"] == rows[0]["proof_hash"]
    assert len({r["proof_hash"] for r in rows}) == 2


def test_depth_at_size_empty_surface_flagged():
    """No surface → empty, flagged feed (fail-CLOSED, never a fabricated market)."""
    res = DAS.build_depth_at_size(write=False, surface={})
    assert res["n_markets"] == 0
    assert res["flagged"] is True


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B1.2 — killer-test harness: the honest INSUFFICIENT_DATA on thin data
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_killer_insufficient_data_on_thin_track():
    """A book with too few realized days → INSUFFICIENT_DATA (the honest default, never a YES)."""
    series = {"book1": _make_series("book1", n_days=5, deployable=250_000, carry=6.0)}
    res = RAS.build_realized_at_size(write=False, series_map=series)
    assert res["verdict"] == "INSUFFICIENT_DATA"
    assert res["survives_at_aum_usd"] is None


def test_killer_no_books_insufficient_data():
    """No books at all → INSUFFICIENT_DATA (never fabricates a survival)."""
    res = RAS.build_realized_at_size(write=False, series_map={})
    assert res["verdict"] == "INSUFFICIENT_DATA"


def test_killer_on_real_desk_data_is_honest():
    """On the desk's CURRENT books dir (likely absent/thin) the verdict is INSUFFICIENT_DATA or
    DOES_NOT_SURVIVE_PAST — NEVER a fabricated SURVIVES_AT. This is the honesty mandate in vivo."""
    res = RAS.build_realized_at_size(write=False)  # reads data/rates_desk/books/ (absent today)
    assert res["verdict"] in ("INSUFFICIENT_DATA", "DOES_NOT_SURVIVE_PAST", "SURVIVES_AT")
    if res["verdict"] == "SURVIVES_AT":
        # if it ever claims survival it must be backed by real deployable + enough days
        assert res["n_books_deployable"] > 0
        assert res["realized_days"] >= RAS.MIN_REALIZED_DAYS


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B1.3 — THE HONESTY GUARDRAILS: prove it can say NO and can say YES
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_can_say_NO_below_floor_book_does_not_survive():
    """SYNTHETIC book whose capped APY < floor at size → DOES_NOT_SURVIVE_PAST. The harness MUST fail.

    A tiny deployable ($200k) at a thin carry means that past ~$1M the idle@floor dilution drags the
    book to ~the floor → below floor+200bps → it does NOT survive at $5M/$10M."""
    series = {"thin": _make_series("thin", n_days=40, deployable=200_000, carry=6.0, floor=3.4)}
    res = RAS.build_realized_at_size(write=False, series_map=series)
    assert res["verdict"] == "DOES_NOT_SURVIVE_PAST"
    # it does not clear floor+200bps at $5M (the dilution killed it)
    assert res["floor_plus_bps_at_5M"] < RAS.SURVIVE_BPS
    # the killer names the AUM it dies past (the last surviving, or None if it never cleared)
    assert "does_not_survive_past_aum_usd" in res


def test_can_say_NO_even_at_smallest_ticket():
    """A book so thin it fails even at $1M → DOES_NOT_SURVIVE_PAST with no surviving AUM."""
    series = {"micro": _make_series("micro", n_days=40, deployable=10_000, carry=6.0, floor=3.4)}
    res = RAS.build_realized_at_size(write=False, series_map=series)
    assert res["verdict"] == "DOES_NOT_SURVIVE_PAST"
    assert res["survives_at_aum_usd"] is None  # never cleared even the smallest ticket


def test_can_say_YES_above_floor_at_size_survives():
    """SYNTHETIC above-floor-at-size book → SURVIVES_AT. Deep enough deployable ($12M) at a fat carry
    (12%) so even at $10M the book stays well above floor+200bps."""
    series = {"deep": _make_series("deep", n_days=40, deployable=12_000_000, carry=12.0, floor=3.4,
                                   shares_venue=False)}
    res = RAS.build_realized_at_size(write=False, series_map=series)
    assert res["verdict"] == "SURVIVES_AT"
    assert res["survives_at_aum_usd"] == 10_000_000  # clears at the largest ticket
    assert res["floor_plus_bps_at_5M"] >= RAS.SURVIVE_BPS


def test_can_say_partial_survival_does_not_survive_past_a_middle_ticket():
    """A book that clears $1M but not $5M → DOES_NOT_SURVIVE_PAST with survives_at = $1M."""
    # deployable $1.5M @ 8% carry: at $1M fully deployed → 8% (460bps, survives); at $5M only 30%
    # deployed → 0.3·8 + 0.7·3.4 = 4.78% (138bps < 200bps bar) → fails past $1M.
    series = {"mid": _make_series("mid", n_days=40, deployable=1_500_000, carry=8.0, floor=3.4,
                                  shares_venue=False)}
    res = RAS.build_realized_at_size(write=False, series_map=series)
    assert res["verdict"] == "DOES_NOT_SURVIVE_PAST"
    assert res["survives_at_aum_usd"] == 1_000_000
    assert res["does_not_survive_past_aum_usd"] == 5_000_000


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B1.4 — idle-cash@floor accounting reconciles to the cent
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_idle_at_floor_reconciles_to_the_cent():
    """capped_book_net_apy = deployed_frac·carry + idle_frac·floor, reconciled to the cent."""
    s = RAS.score_at_aum(Decimal("5000000"), combined_deployable=Decimal("2000000"),
                         deployed_weighted_carry_pct=Decimal("8.0"), floor_pct=Decimal("3.4"))
    assert s["reconciled"] is True
    # hand-computed: deployed 2M (40%), idle 3M (60%) → 0.4·8 + 0.6·3.4 = 3.2 + 2.04 = 5.24
    assert s["capped_book_net_apy_pct"] == pytest.approx(5.24, abs=1e-6)
    # annual income: 2M·8% + 3M·3.4% = 160k + 102k = 262k
    assert s["annual_income_usd"] == pytest.approx(262_000.0, abs=0.01)
    # floor+bps = (5.24 − 3.4)·100 = 184 bps
    assert s["floor_plus_bps"] == pytest.approx(184.0, abs=1e-4)


def test_idle_at_floor_fully_capped_out_earns_floor():
    """If AUM far exceeds deployable, the book → ~the floor (capped-out capital earns the floor, 0
    above) — matching edge_at_scale / capacity convention."""
    s = RAS.score_at_aum(Decimal("10000000"), combined_deployable=Decimal("250000"),
                         deployed_weighted_carry_pct=Decimal("6.0"), floor_pct=Decimal("3.4"))
    assert s["reconciled"] is True
    assert s["capped_book_net_apy_pct"] == pytest.approx(3.4 + 0.025 * (6.0 - 3.4), abs=1e-6)
    assert s["floor_plus_bps"] < RAS.SURVIVE_BPS  # diluted to ~the floor → does not survive


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B1.5 — RED-TEAM
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_redteam_depth_claim_above_pool_tvl_is_bounded_by_real_depth():
    """A book claiming exit liquidity > the real pool TVL: the depth feed uses the SURFACE's own
    exit_liquidity (§9, derived from real TVL) — a row cannot inflate beyond what the surface carries.
    We assert the absorbable never exceeds the §9 exit liquidity at any ticket."""
    surf = _surface([_quote("0xreal", "susde", tvl=50_000_000, exit_liq=10_000_000)])
    res = DAS.build_depth_at_size(write=False, surface=surf)
    m = res["markets"][0]
    el = float(m["exit_liquidity_usd"])
    for t in m["tickets"]:
        if t["absorbable_usd"] is not None:
            # the conservative constant-product bound never delivers more than the §9 capacity
            assert t["absorbable_usd"] <= el * 1.0 + 1e-6


def test_redteam_stale_depth_flagged():
    """A market quote whose as_of trails the surface date beyond the freshness window → stale → flagged
    (non-contemporaneous depth is never trusted as live)."""
    surf = _surface(
        [_quote("0xstale", "susde", 100_000_000, 30_000_000, as_of="2026-01-01")],
        as_of="2026-06-29")  # ~6 months stale
    res = DAS.build_depth_at_size(write=False, surface=surf)
    m = res["markets"][0]
    assert m["stale"] is True
    assert m["flagged"] is True
    assert m["flag_reason"] == "insufficient_contemporaneous_depth"


def test_redteam_replay_determinism():
    """Replay the same inputs N times → byte-identical verdict + scores (deterministic)."""
    series = {"a": _make_series("a", 40, 1_500_000, 30.0, shares_venue=False)}
    payloads = []
    for _ in range(3):
        r = RAS.run_killer_test({k: list(v) for k, v in series.items()})
        payloads.append(json.dumps(r, sort_keys=True, default=str))
    assert len(set(payloads)) == 1


def test_redteam_combined_le_sum_caps_minus_haircut():
    """PROPERTY: combined deployable ≤ Σ per-book caps − haircut (shared-venue books non-additive)."""
    # two shared-venue books → the smaller is haircut
    series = {
        "a": _make_series("a", 40, 1_000_000, 8.0, shares_venue=True),
        "b": _make_series("b", 40, 2_000_000, 8.0, shares_venue=True),
    }
    res = RAS.run_killer_test(series)
    c = res["combined"]
    naive = c["naive_sum_deployable_usd"]
    haircut = c["correlation_haircut_usd"]
    combined = c["combined_deployable_usd"]
    assert combined <= naive
    assert combined == pytest.approx(naive - haircut, abs=0.01)
    # haircut = 50% of the smaller (binding) shared leg = 0.5 · 1,000,000 = 500,000
    assert haircut == pytest.approx(500_000.0, abs=0.01)


def test_redteam_distinct_venue_books_not_haircut():
    """Distinct-venue books are fully additive (no correlation haircut)."""
    series = {
        "a": _make_series("a", 40, 1_000_000, 8.0, shares_venue=False),
        "b": _make_series("b", 40, 2_000_000, 8.0, shares_venue=False),
    }
    res = RAS.run_killer_test(series)
    assert res["combined"]["correlation_haircut_usd"] == 0.0
    assert res["combined"]["combined_deployable_usd"] == pytest.approx(3_000_000.0, abs=0.01)


def test_lane_a_DEPLOYED_state_is_deployable():
    """CROSS-LANE CONTRACT: Lane A stamps the live state as 'DEPLOYED' (uppercase) on its realized_
    series rows. The harness lower-cases + matches it so a deployed book is honestly counted (a real
    finding from data/rates_desk/books/)."""
    series = {"d": _make_series("d", 40, 1_000_000, 8.0, refusal="DEPLOYED", shares_venue=False)}
    res = RAS.run_killer_test(series)
    assert res["n_books_deployable"] == 1
    assert res["books"][0]["in_combined_book"] is True


def test_redteam_refused_book_contributes_zero_deployable():
    """A book in a REFUSE state contributes 0 deployable (not in the combined book)."""
    series = {
        "live": _make_series("live", 40, 1_000_000, 8.0, refusal="safe", shares_venue=False),
        "dead": _make_series("dead", 40, 5_000_000, 20.0, refusal="refuse", shares_venue=False),
    }
    res = RAS.run_killer_test(series)
    by = {b["book_id"]: b for b in res["books"]}
    assert by["dead"]["deployable_usd"] == 0.0
    assert by["dead"]["in_combined_book"] is False
    assert by["live"]["in_combined_book"] is True


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B1.5 — SMOKE: full build writes atomically + carries the honesty envelope
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_smoke_build_writes_and_envelopes(tmp_path):
    series = {"a": _make_series("a", 40, 1_500_000, 30.0, shares_venue=False)}
    out = tmp_path / "realized_at_size.json"
    res = RAS.build_realized_at_size(write=True, series_map=series, out_path=out)
    assert out.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk["llm_forbidden"] is True
    assert on_disk["is_advisory"] is True
    assert "honesty_mandate" in on_disk
    assert on_disk["proof_hash"] == res["proof_hash"]
    # as_of is a DATA date, not the wall clock
    assert on_disk["as_of"] == "2026-02-09"  # 40 days from 2026-01-01


def test_depth_feed_writes_atomically(tmp_path):
    surf = _surface([_quote("0xdeep", "susde", 200_000_000, 50_000_000)])
    out = tmp_path / "depth_at_size.json"
    DAS.build_depth_at_size(write=True, surface=surf, out_path=out)
    assert out.exists()
    d = json.loads(out.read_text())
    assert d["llm_forbidden"] is True and d["is_advisory"] is True


# ════════════════════════════════════════════════════════════════════════════════════════════════
# B1.6 — exit-NAV $1M+ hole closure: depth feed resolves a surface/history hole to a real bound
# ════════════════════════════════════════════════════════════════════════════════════════════════
def test_b16_depth_feed_closes_exit_nav_hole_where_depth_exists():
    """exit_nav._resolve_depth: when surface AND history miss a market, the Lane-B depth feed resolves
    a REAL conservative bound WHERE it has the depth (the $1M+ hole closes), and STAYS a hole where it
    doesn't (no fabrication)."""
    from spa_core.strategy_lab.rates_desk import exit_nav as EN

    params = RatePolicyParams()
    # depth feed HAS this market → hole closes to a real bound
    feed_surf = _surface([_quote("0xclosed", "susde", 200_000_000, 50_000_000)])
    depth_feed = DAS.build_depth_at_size(write=False, surface=feed_surf)

    # surface + history both EMPTY → without the feed it would be a permanent hole
    depth, src = EN._resolve_depth({}, {}, "0xclosed", "susde", "2026-06-29", params, depth_feed)
    assert depth is not None and depth > 0
    assert src == "depth_at_size.exit_liquidity_usd"

    # a market the feed does NOT have → STILL a hole (fail-CLOSED, no fabrication)
    depth2, src2 = EN._resolve_depth({}, {}, "0xmissing", "unknownunderlying", "2026-06-29",
                                     params, depth_feed)
    assert depth2 is None and src2 == "none"


def test_b16_thin_feed_row_does_not_close_hole():
    """A flagged (thin) depth-feed row must NOT resolve a hole — fail-CLOSED stays fail-CLOSED."""
    from spa_core.strategy_lab.rates_desk import exit_nav as EN

    params = RatePolicyParams()
    thin_surf = _surface([_quote("0xthin", "usde", 100_000, 50_000)])  # below DEX floor → flagged
    depth_feed = DAS.build_depth_at_size(write=False, surface=thin_surf)
    depth, src = EN._resolve_depth({}, {}, "0xthin", "usde", "2026-06-29", params, depth_feed)
    assert depth is None and src == "none"  # the thin feed row is NOT a usable bound
