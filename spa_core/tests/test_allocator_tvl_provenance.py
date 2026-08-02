"""
spa_core/tests/test_allocator_tvl_provenance.py — ADR-053 (allocator side).

WHY THIS FILE EXISTS
--------------------
ADR-053 removed the fabricated TVL fallback in the RiskPolicy gate; the SIBLING
fabrication lived in the allocator: registry-merged pools got ``tvl =
fallback_tvl_usd`` (or the $50M default literal) and ``_filter_by_tvl`` treated
that literal as PASSING the $5M floor — the allocator ranked and proposed pools
on invented liquidity, presenting a committed constant as verification.

The fix pinned here:
  * every allocator row carries ``tvl_source`` — "live" ONLY when the
    orchestrator record explicitly declares ``tvl_source == "live"`` (adapter
    fetched TVL from the feed); registry literals and undeclared snapshot TVLs
    are "static" (fail-closed labeling);
  * ``feed_coverage`` surfaces the split (``tvl_sources`` / ``tvl_live`` /
    ``tvl_static`` / ``tvl_static_adapters``) plus ``tvl_floor_unverified`` —
    pools whose floor pass rests on a static TVL;
  * static-TVL pools are LABELED + LOGGED, но ОСТАЮТСЯ в ранжировании:
    исключение обнулило бы цели held-позиций (registry-merge путь) → forced
    sell — owner-gated (карточка в трекере); enforcement — RiskPolicy-гейт.

Pure stdlib + pytest. Deterministic. Offline. LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

from spa_core.allocator.allocator import (
    _REGISTRY_FALLBACK_TVL_USD,
    AllocationResult,
    StrategyAllocator,
)

TVL_FLOOR = StrategyAllocator.TVL_FLOOR_USD  # 5_000_000


def _registry(tmpdir: Path, entries: dict) -> Path:
    doc = {"version": "test", "updated": "2024-01-01T00:00:00Z", "adapters": entries}
    p = tmpdir / "adapter_registry.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _status(tmpdir: Path, adapters: list[dict]) -> Path:
    doc = {"generated_at": "2024-01-01T00:00:00Z", "adapters": adapters}
    p = tmpdir / "adapter_orchestrator_status.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _entry(tier: int, apy: float, tvl: float | None = 5e8) -> dict:
    e = {
        "tier": tier,
        "chain": "ethereum",
        "fallback_apy": apy,
        "research_only": False,
        "status": "active",
    }
    if tvl is not None:
        e["fallback_tvl_usd"] = tvl
    return e


# ───────────────── registry merge: always static, floor unverified ──────────
def test_registry_tvl_labeled_static_and_floor_unverified(tmp_path):
    """A registry-merged pool ranks on a TVL literal → tvl_source="static" and
    its floor pass is listed in tvl_floor_unverified. It STAYS ranked (weight
    > 0) — exclusion would zero held positions' targets (owner-gated)."""
    entries = {
        "aave_v3": _entry(1, 0.035),                    # explicit 5e8 literal
        "morpho_steakhouse": _entry(2, 0.041, tvl=None)  # $50M default literal
    }
    a = StrategyAllocator(
        status_path=tmp_path / "_no_status.json",
        registry_path=_registry(tmp_path, entries),
        strategy_loop_enabled=False,
        live_apy_provider={},
    )
    r = a.allocate(model="equal_weight")

    cov = r.feed_coverage
    assert cov["tvl_sources"] == {
        "aave_v3": "static",
        "morpho_steakhouse": "static",
    }
    assert cov["tvl_live"] == 0
    assert cov["tvl_static"] == 2
    assert cov["tvl_static_adapters"] == ["aave_v3", "morpho_steakhouse"]
    # both passed the numeric floor — on literals, so the pass is UNVERIFIED
    assert cov["tvl_floor_unverified"] == ["aave_v3", "morpho_steakhouse"]
    # no exclusion: static-TVL pools still receive weight (owner-gated decision)
    assert r.target_weights["aave_v3"] > 0.0
    assert r.target_weights["morpho_steakhouse"] > 0.0
    # the honest note is visible where a reviewer looks
    assert any("ADR-053" in n and "СТАТИЧЕСКОМ" in n for n in r.notes)


def test_default_50m_literal_still_used_but_never_verified(tmp_path):
    """The $50M default keeps the pool rankable (no behaviour change) but is
    never presented as verifying the floor."""
    entries = {"spark_susds_x": _entry(2, 0.05, tvl=None)}
    a = StrategyAllocator(
        status_path=tmp_path / "_no_status.json",
        registry_path=_registry(tmp_path, entries),
        strategy_loop_enabled=False,
        live_apy_provider={},
    )
    r = a.allocate(model="equal_weight")
    assert _REGISTRY_FALLBACK_TVL_USD >= TVL_FLOOR  # the literal passes numerically
    assert "spark_susds_x" in r.feed_coverage["tvl_floor_unverified"]


# ───────────────── orchestrator snapshot: declaration decides ───────────────
def test_orchestrator_declared_live_tvl_vs_undeclared(tmp_path):
    """Snapshot row WITH tvl_source=="live" → "live" (not in
    tvl_floor_unverified); a row WITHOUT the declaration → "static"
    (fail-closed: a numeric TVL is not an observation unless declared)."""
    adapters = [
        {
            "protocol": "pool_live_tvl",
            "status": "ok",
            "apy_pct": 4.5,
            "tvl_usd": 60_000_000.0,
            "tier": "T1",
            "tvl_source": "live",       # ADR-053 declaration
            "last_updated": "2024-01-01T00:00:00Z",
        },
        {
            "protocol": "pool_undeclared_tvl",
            "status": "ok",
            "apy_pct": 4.0,
            "tvl_usd": 60_000_000.0,
            "tier": "T2",
            # no tvl_source field — pre-ADR-053 snapshot shape
            "last_updated": "2024-01-01T00:00:00Z",
        },
    ]
    a = StrategyAllocator(
        status_path=_status(tmp_path, adapters),
        registry_path=tmp_path / "_no_registry.json",
        strategy_loop_enabled=False,
        live_apy_provider={},
    )
    r = a.allocate(model="equal_weight")

    cov = r.feed_coverage
    assert cov["tvl_sources"]["pool_live_tvl"] == "live"
    assert cov["tvl_sources"]["pool_undeclared_tvl"] == "static"
    assert cov["tvl_live"] == 1
    assert cov["tvl_static"] == 1
    assert cov["tvl_floor_unverified"] == ["pool_undeclared_tvl"]
    # a live-verified floor pass emits no unverified note about that pool
    assert not any("pool_live_tvl" in n and "ADR-053" in n for n in r.notes)


def test_below_floor_pool_is_rejected_not_unverified(tmp_path):
    """A static-TVL pool BELOW the floor is rejected outright (existing MP-011
    path) — it must appear in tvl_filtered_protocols, not in
    tvl_floor_unverified (which lists only PASSES on static TVL)."""
    entries = {
        "aave_v3": _entry(1, 0.035),                    # above floor (static)
        "tiny_pool": _entry(2, 0.10, tvl=1_000_000),    # below floor
    }
    a = StrategyAllocator(
        status_path=tmp_path / "_no_status.json",
        registry_path=_registry(tmp_path, entries),
        strategy_loop_enabled=False,
        live_apy_provider={},
    )
    r = a.allocate(model="equal_weight")
    assert "tiny_pool" in r.tvl_filtered_protocols
    assert r.feed_coverage["tvl_floor_unverified"] == ["aave_v3"]


# ───────────────── direct _filter_by_tvl contract ───────────────────────────
def test_filter_by_tvl_populates_unverified_and_keeps_signature(tmp_path):
    a = StrategyAllocator(
        status_path=tmp_path / "_no_status.json",
        registry_path=tmp_path / "_no_registry.json",
        strategy_loop_enabled=False,
        live_apy_provider={},
    )
    pools = [
        {"protocol": "live_ok", "tvl_usd": 1e8, "tvl_source": "live"},
        {"protocol": "static_ok", "tvl_usd": 1e8, "tvl_source": "static"},
        {"protocol": "legacy_no_field", "tvl_usd": 1e8},   # fail-closed → static
        {"protocol": "too_small", "tvl_usd": 1e6, "tvl_source": "static"},
    ]
    ok, rejected = a._filter_by_tvl(pools)
    assert {p["protocol"] for p in ok} == {"live_ok", "static_ok", "legacy_no_field"}
    assert rejected == ["too_small"]
    assert a._tvl_floor_unverified == ["legacy_no_field", "static_ok"]


def test_result_shape_still_serializable(tmp_path):
    """target_allocation.json consumers read asdict() output — the new
    provenance lives inside feed_coverage and must round-trip through JSON."""
    entries = {"aave_v3": _entry(1, 0.035)}
    a = StrategyAllocator(
        status_path=tmp_path / "_no_status.json",
        registry_path=_registry(tmp_path, entries),
        strategy_loop_enabled=False,
        live_apy_provider={},
    )
    r = a.allocate(model="equal_weight")
    assert isinstance(r, AllocationResult)
    payload = json.loads(json.dumps(r.to_dict()))
    assert payload["feed_coverage"]["tvl_sources"] == {"aave_v3": "static"}
    assert payload["feed_coverage"]["tvl_floor_unverified"] == ["aave_v3"]
