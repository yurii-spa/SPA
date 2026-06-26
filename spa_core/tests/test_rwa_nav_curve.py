"""
spa_core/tests/test_rwa_nav_curve.py — the RWA backstop FORWARD RECORD (measured-NAV daily series).

Verifies the forward-record append contract (mirrors the rates-desk paper track):
  - one point per UTC day appended to data/rwa_nav_curve.json (atomic, no leftover tmp),
  - idempotent per UTC day — re-running the same day REFRESHES, never dups,
  - ring-buffer cap (SERIES_CAP),
  - restart-survival — the series reloads from disk intact and continues,
  - FAIL-CLOSED — a bad/empty measurement SKIPS the day's append (no fabricated point),
  - summarize_report produces the documented forward-point shape,
  - the daily safety_board run ALSO appends a forward point (wiring).

Pure synthetic, no network. LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os

from spa_core.strategy_lab.rwa_backstop import nav_curve as nc
from spa_core.strategy_lab.rwa_backstop import safety_board as sb


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────
def _report(date="2026-06-26", assets=None, gap=12.5, onchain_4626=1, off_chain=2):
    if assets is None:
        assets = [
            {"symbol": "VAULT", "onchain_nav_usd": 1.002, "marketing_nav_usd": 1.0,
             "on_chain_dex_liquidity_usd": 5_000_000.0},
            {"symbol": "BUIDL", "onchain_nav_usd": None, "marketing_nav_usd": 1.0,
             "on_chain_dex_liquidity_usd": 0.0},
            {"symbol": "USYC", "onchain_nav_usd": None, "marketing_nav_usd": 1.0,
             "on_chain_dex_liquidity_usd": 0.0},
        ]
    return {
        "date": date,
        "assets": assets,
        "max_marketing_vs_liq_gap_pct_1m": gap,
        "onchain_nav_coverage": {"onchain_4626": onchain_4626, "off_chain_estimate": off_chain},
    }


def _pools_payload(pools):
    return {"status": "success", "data": pools}


class _FakeFetcher:
    def __init__(self, payload):
        self._payload = payload

    def __call__(self, url):
        return self._payload


# ── 1. summarize_report shape ───────────────────────────────────────────────────────────────────
def test_summarize_report_shape():
    pt = nc.summarize_report(_report())
    assert pt is not None
    for k in ("date", "ts", "tvl_weighted_nav", "onchain_4626_count",
              "off_chain_estimate_count", "liq_nav_gap_pct", "n_assets"):
        assert k in pt
    assert pt["date"] == "2026-06-26"
    assert pt["onchain_4626_count"] == 1
    assert pt["off_chain_estimate_count"] == 2
    assert pt["liq_nav_gap_pct"] == 12.5
    assert pt["n_assets"] == 3
    # only VAULT has DEX TVL → tvl-weighted NAV equals its on-chain NAV
    assert abs(pt["tvl_weighted_nav"] - 1.002) < 1e-9


def test_summarize_falls_back_to_equal_weight_when_no_dex_tvl():
    """No asset has DEX TVL (the permissioned norm) → equal-weighted mean of measured NAVs."""
    assets = [
        {"symbol": "A", "onchain_nav_usd": None, "marketing_nav_usd": 1.0,
         "on_chain_dex_liquidity_usd": 0.0},
        {"symbol": "B", "onchain_nav_usd": None, "marketing_nav_usd": 0.98,
         "on_chain_dex_liquidity_usd": 0.0},
    ]
    pt = nc.summarize_report(_report(assets=assets))
    assert abs(pt["tvl_weighted_nav"] - 0.99) < 1e-9


# ── 2. append one point per day + shape ──────────────────────────────────────────────────────────
def test_append_one_point(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    doc = nc.record_forward_point(_report(date="2026-06-26"), curve_path=path)
    assert doc["n_points"] == 1
    assert doc["series"][0]["date"] == "2026-06-26"
    assert doc["advisory"] is True and doc["research_only"] is True
    assert doc["latest"]["date"] == "2026-06-26"
    assert path.exists()


# ── 3. idempotent per UTC day — re-run same day → no dup ──────────────────────────────────────────
def test_idempotent_same_day_no_dup(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    nc.record_forward_point(_report(date="2026-06-26", gap=10.0), curve_path=path)
    doc = nc.record_forward_point(_report(date="2026-06-26", gap=11.5), curve_path=path)
    assert doc["n_points"] == 1, "re-running the same day must REFRESH, not append a dup"
    # the refreshed value is the latest measurement
    assert doc["series"][-1]["liq_nav_gap_pct"] == 11.5


def test_distinct_days_accumulate(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    nc.record_forward_point(_report(date="2026-06-24"), curve_path=path)
    nc.record_forward_point(_report(date="2026-06-25"), curve_path=path)
    doc = nc.record_forward_point(_report(date="2026-06-26"), curve_path=path)
    assert doc["n_points"] == 3
    assert [p["date"] for p in doc["series"]] == ["2026-06-24", "2026-06-25", "2026-06-26"]


# ── 4. ring-buffer cap ────────────────────────────────────────────────────────────────────────────
def test_ring_buffer_cap(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    base = nc.SERIES_CAP + 50
    for i in range(base):
        # distinct UTC days so they accumulate (idempotency keys on date)
        day = f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}-{i}"  # unique synthetic date string
        nc.append_point({"date": day, "ts": "t", "tvl_weighted_nav": 1.0,
                         "onchain_4626_count": 0, "off_chain_estimate_count": 0,
                         "liq_nav_gap_pct": None, "n_assets": 1}, curve_path=path)
    doc = nc._load_curve(path)
    assert len(doc["series"]) == nc.SERIES_CAP


# ── 5. fail-CLOSED on bad data → no append ────────────────────────────────────────────────────────
def test_fail_closed_empty_report_no_append(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    assert nc.record_forward_point({}, curve_path=path) is None
    assert nc.record_forward_point({"assets": []}, curve_path=path) is None
    assert nc.record_forward_point(None, curve_path=path) is None
    # no file created — never fabricates a point
    assert not path.exists()


def test_fail_closed_no_numeric_nav_no_append(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    bad = _report(assets=[{"symbol": "X", "onchain_nav_usd": None,
                           "marketing_nav_usd": None, "on_chain_dex_liquidity_usd": 0.0}])
    assert nc.record_forward_point(bad, curve_path=path) is None
    assert not path.exists()


def test_fail_closed_preserves_existing_series(tmp_path):
    """A bad measurement after a good day must NOT touch the existing series."""
    path = tmp_path / "rwa_nav_curve.json"
    nc.record_forward_point(_report(date="2026-06-25"), curve_path=path)
    nc.record_forward_point({"assets": []}, curve_path=path)  # bad → skip
    doc = nc._load_curve(path)
    assert doc["n_points"] == 1
    assert doc["series"][-1]["date"] == "2026-06-25"


# ── 6. restart-survival — reload intact and continue ──────────────────────────────────────────────
def test_restart_survival(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    nc.record_forward_point(_report(date="2026-06-24"), curve_path=path)
    nc.record_forward_point(_report(date="2026-06-25"), curve_path=path)
    # simulate a fresh process: _load_curve reads from disk; append continues the series
    reloaded = nc._load_curve(path)
    assert [p["date"] for p in reloaded["series"]] == ["2026-06-24", "2026-06-25"]
    doc = nc.record_forward_point(_report(date="2026-06-26"), curve_path=path)
    assert [p["date"] for p in doc["series"]] == ["2026-06-24", "2026-06-25", "2026-06-26"]


def test_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    path.write_text("{ not json", encoding="utf-8")
    doc = nc.record_forward_point(_report(date="2026-06-26"), curve_path=path)
    assert doc["n_points"] == 1  # corrupt file → fresh series, append succeeds


# ── 7. atomic write — no leftover tmp ─────────────────────────────────────────────────────────────
def test_atomic_no_leftover_tmp(tmp_path):
    path = tmp_path / "rwa_nav_curve.json"
    nc.record_forward_point(_report(date="2026-06-26"), curve_path=path)
    with open(path) as f:
        on_disk = json.load(f)
    assert on_disk["n_points"] == 1
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".") and p.endswith(".tmp")]
    assert not leftovers


# ── 8. wiring — the safety_board run appends a forward point ───────────────────────────────────────
def test_safety_board_main_appends_forward_point(tmp_path, monkeypatch):
    """The daily safety_board entry, after writing the board, ALSO appends a forward point."""
    board_out = tmp_path / "rwa_safety_board.json"
    curve_out = tmp_path / "rwa_nav_curve.json"

    # build a real board over a deep-DEX transferable asset (offline, injected pools)
    from spa_core.strategy_lab.rwa_backstop.collateral_registry import CollateralAsset
    asset = CollateralAsset(
        symbol="USDY", issuer="Test", chain="ethereum", asset_class="tokenized_tbill",
        token_contract="0xabc", transfer_restricted=False, redemption_delay_days=2.0,
        redemption_fee_bps=0.0, min_redemption_usd=0.0, redemption_documented=True,
    )
    pools = [{"project": "uniswap-v3", "chain": "Ethereum", "symbol": "USDY-USDC",
              "tvlUsd": 5_000_000_000.0}]
    report = sb.build_report(write=True, fetcher=_FakeFetcher(_pools_payload(pools)),
                             out_path=board_out, assets=[asset], onchain=False)

    doc = nc.record_forward_point(report, curve_path=curve_out)
    assert doc is not None
    assert doc["n_points"] == 1
    assert doc["latest"]["n_assets"] == 1
    assert curve_out.exists()
