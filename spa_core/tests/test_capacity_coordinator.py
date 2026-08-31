"""CIO oversight phase A — Global Capacity Coordinator.

Owner decisions (2026-08-30): warn-only (never blocks a book), reuse the existing
capacity threshold (no new number). These tests pin: the aggregation math itself,
the honest degrade-on-missing-book behavior, and the separator-only protocol-key
canonicalization (narrow on purpose — it must NOT merge semantically distinct
protocols like morpho_blue/morpho_steakhouse).
"""
from __future__ import annotations

import json

from spa_core.risk.capacity_coordinator import (
    _canonical_protocol_key,
    aggregate_book_positions,
    check_aggregate_capacity,
    read_books_capacity_check,
)


# ─── canonicalization: narrow on purpose ───────────────────────────────────


def test_canonical_key_collapses_hyphen_underscore_and_case():
    assert _canonical_protocol_key("aave_v3_arbitrum") == "aave_v3_arbitrum"
    assert _canonical_protocol_key("aave-v3-arbitrum") == "aave_v3_arbitrum"
    assert _canonical_protocol_key("AAVE_V3_ARBITRUM") == "aave_v3_arbitrum"


def test_canonical_key_does_not_merge_distinct_vaults():
    """morpho_blue and morpho_steakhouse are DIFFERENT protocols (different
    vaults, different risk) — canonicalization must never conflate them."""
    assert _canonical_protocol_key("morpho_blue") != _canonical_protocol_key("morpho_steakhouse")


# ─── aggregation math ───────────────────────────────────────────────────────


def test_aggregate_sums_across_books_by_canonical_key():
    books = {
        "conservative": {"aave_v3_arbitrum": 10_000.0},
        "balanced": {"aave-v3-arbitrum": 5_000.0},  # spelling variant, same protocol
        "aggressive": {"morpho_steakhouse": 2_000.0},
    }
    agg = aggregate_book_positions(books)
    assert agg["aave_v3_arbitrum"] == 15_000.0  # merged despite the spelling variant
    assert agg["morpho_steakhouse"] == 2_000.0


def test_aggregate_with_no_books_is_empty_not_an_error():
    assert aggregate_book_positions({}) == {}


# ─── the aggregate capacity check ──────────────────────────────────────────


def test_three_small_books_can_sum_past_the_limit():
    """The exact gap this module closes: each book alone is within the 1% cap,
    but the SUM of three books in the same pool exceeds it."""
    books = {
        "conservative": {"maple": 4_000.0},
        "balanced": {"maple": 4_000.0},
        "aggressive": {"maple": 4_000.0},
    }  # sum $12,000 vs individually-fine $4,000 each
    tvl_map = {"maple": 1_000_000.0}  # 1% cap = $10,000
    result = check_aggregate_capacity(books, tvl_map, max_pct=0.01)
    assert result["ok"] is False
    assert any("maple" in v for v in result["violations"])
    assert result["aggregated_positions"]["maple"] == 12_000.0


def test_three_small_books_within_limit_is_ok():
    books = {
        "conservative": {"maple": 2_000.0},
        "balanced": {"maple": 2_000.0},
        "aggressive": {"maple": 2_000.0},
    }  # sum $6,000, well under $10,000 cap
    tvl_map = {"maple": 1_000_000.0}
    result = check_aggregate_capacity(books, tvl_map, max_pct=0.01)
    assert result["ok"] is True
    assert result["violations"] == []


def test_tvl_map_keys_are_canonicalized_too_not_just_positions():
    """If the TVL snapshot spells a protocol differently than the position keys
    (e.g. hyphenated), the lookup must still connect them — otherwise every
    aggregate check on a hyphenated protocol would silently read as
    no-TVL-data and never actually flag anything."""
    books = {
        "conservative": {"aave_v3_arbitrum": 6_000.0},
        "balanced": {"aave_v3_arbitrum": 6_000.0},
    }
    tvl_map = {"aave-v3-arbitrum": 1_000_000.0}  # hyphenated in the TVL snapshot
    result = check_aggregate_capacity(books, tvl_map, max_pct=0.01)  # cap = $10k
    assert result["ok"] is False  # $12k > $10k — must be caught, not silently skipped
    assert not result["warnings"]  # and NOT reported as missing TVL data


def test_missing_tvl_data_warns_never_blocks():
    """Matches capacity_limits.py's own fail-safe: no TVL data → skip, don't block."""
    books = {"conservative": {"ghost_pool": 50_000.0}}
    result = check_aggregate_capacity(books, tvl_map={}, max_pct=0.01)
    assert result["ok"] is True
    assert result["warnings"]


def test_books_included_names_exactly_who_contributed():
    books = {"conservative": {"maple": 1000.0}, "balanced": {}}
    result = check_aggregate_capacity(books, tvl_map={"maple": 1_000_000.0})
    assert result["books_included"] == ["balanced", "conservative"]


# ─── read_books_capacity_check: file I/O + honest degradation ──────────────


def test_read_with_no_files_at_all_is_ok_not_fabricated(tmp_path):
    result = read_books_capacity_check(tmp_path)
    assert result["ok"] is True
    assert result["books_included"] == []
    assert result["aggregated_positions"] == {}


def test_read_conservative_dict_shape(tmp_path):
    (tmp_path / "current_positions.json").write_text(
        json.dumps({"positions": {"maple": 30_000.0}}), encoding="utf-8")
    (tmp_path / "adapter_orchestrator_status.json").write_text(
        json.dumps({"adapters": [{"protocol": "maple", "tvl_usd": 1_000_000.0}]}),
        encoding="utf-8")
    result = read_books_capacity_check(tmp_path, max_pct=0.01)
    assert result["books_included"] == ["conservative"]
    assert result["aggregated_positions"]["maple"] == 30_000.0
    assert result["ok"] is False  # $30k on $1M TVL at 1% cap ($10k) = violation


def test_read_balanced_list_shape_sums_multiple_legs(tmp_path):
    (tmp_path / "hy_paper_trading.json").write_text(json.dumps({"positions": [
        {"protocol": "maple", "notional_usd": 3_000.0},
        {"protocol": "maple", "notional_usd": 2_000.0},  # second leg, same protocol
    ]}), encoding="utf-8")
    result = read_books_capacity_check(tmp_path)
    assert result["aggregated_positions"]["maple"] == 5_000.0
    assert result["books_included"] == ["balanced"]


def test_read_corrupt_book_file_degrades_that_book_not_the_whole_check(tmp_path):
    (tmp_path / "current_positions.json").write_text("{not valid json", encoding="utf-8")
    (tmp_path / "hy_paper_trading.json").write_text(
        json.dumps({"positions": [{"protocol": "maple", "notional_usd": 1000.0}]}),
        encoding="utf-8")
    result = read_books_capacity_check(tmp_path)  # must not raise
    assert result["books_included"] == ["balanced"]


def test_read_never_raises_even_on_totally_malformed_orchestrator_file(tmp_path):
    (tmp_path / "adapter_orchestrator_status.json").write_text("]][not json[[", encoding="utf-8")
    (tmp_path / "current_positions.json").write_text(
        json.dumps({"positions": {"maple": 1000.0}}), encoding="utf-8")
    result = read_books_capacity_check(tmp_path)  # must not raise
    assert result["ok"] is True  # no TVL data reachable -> warn, not block
