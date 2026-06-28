"""
spa_core/tests/test_allocator_feed_coverage.py — WS1.1 money-path data-integrity.

WHY THIS FILE EXISTS
--------------------
Before WS1.1 the StrategyAllocator ranked/allocated ~28 of its ~35 adapters off
HARDCODED ``fallback_apy`` literals in data/adapter_registry.json — e.g. it
ranked aave on the stale 3.5% literal while the LIVE DeFiLlama feed said ~6.9%.
WS1.1 makes the LIVE point-in-time APY WIN over the literal, labels every
adapter's ``apy_source`` ("live" | "fallback_stale"), emits a ``feed_coverage``
metric, and FAILS CLOSED (NaN / missing / out-of-band live → labeled stale
literal or excluded, NEVER a fabricated number, NEVER a stale literal silently
presented as live).

This suite pins that contract with PROPERTY + RED-TEAM (adversarial feed) cases.
The live feed is ALWAYS injected (a dict / callable) — never the network — so
the suite is offline + bit-reproducible. RiskPolicy caps are asserted to still
hold (no violation introduced by the feed change).

Pure stdlib + pytest. Deterministic. LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from spa_core.allocator.allocator import AllocationResult, StrategyAllocator

T1_CAP = StrategyAllocator.T1_CAP            # 0.40
T2_CAP = StrategyAllocator.T2_CAP            # 0.20
T2_TOTAL_CAP = StrategyAllocator.T2_TOTAL_CAP  # 0.50
TVL_FLOOR = StrategyAllocator.TVL_FLOOR_USD   # 5_000_000
CAP = StrategyAllocator.CAPITAL               # 100_000
_TOL = 1e-6


# ---------------------------------------------------------------------------
# Harness: a registry file with stale literals + an injected live feed. The
# orchestrator snapshot is left empty so EVERY adapter flows through the
# registry-merge path (the exact path WS1.1 fixes). registry_path points at a
# real temp file; status_path at a missing file (no orchestrator snapshot).
# ---------------------------------------------------------------------------
def _registry(tmpdir: Path, entries: dict) -> Path:
    doc = {"version": "test", "updated": "2024-01-01T00:00:00Z", "adapters": entries}
    p = tmpdir / "adapter_registry.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _alloc(
    tmpdir: Path, entries: dict, live: dict | None, model: str = "equal_weight"
) -> AllocationResult:
    a = StrategyAllocator(
        status_path=tmpdir / "_no_status.json",   # no orchestrator snapshot
        registry_path=_registry(tmpdir, entries),
        strategy_loop_enabled=False,
        live_apy_provider=(live if live is not None else {}),
    )
    return a.allocate(model=model)


def _base_entry(tier: int, apy: float, tvl: float = 5e8) -> dict:
    return {
        "tier": tier,
        "protocol": "X",
        "chain": "ethereum",
        "fallback_apy": apy,        # decimal literal
        "research_only": False,
        "per_protocol_cap": 0.4 if tier == 1 else 0.2,
        "status": "active",
        "fallback_tvl_usd": tvl,
    }


# ───────────────────────── PROPERTY: live WINS over literal ─────────────────
def test_live_apy_drives_ranking_not_the_stale_literal(tmp_path):
    """best_apy must rank on the LIVE 6.9% aave, not the 3.5% stale literal.

    Two T1 adapters: aave (literal 3.5%, live 6.9%) and compound (literal 5.2%,
    live unavailable → stale 5.2%). Under best_apy the TOP pool is the one with
    the higher *ranked* APY. If the allocator (wrongly) ranked on literals,
    compound (5.2%) would out-rank aave (3.5%). With WS1.1, aave ranks on its
    LIVE 6.9% and wins. We assert aave gets the larger weight AND its recorded
    apy_used reflects 6.9%, not 3.5%.
    """
    entries = {
        "aave_v3": _base_entry(1, 0.035),       # stale literal 3.5%
        "compound_v3": _base_entry(1, 0.052),   # stale literal 5.2%
    }
    live = {"aave_v3": 0.069}                    # LIVE 6.9% for aave only
    r = _alloc(tmp_path, entries, live, model="best_apy")

    # apy_source labeled correctly
    assert r.apy_sources["aave_v3"] == "live"
    assert r.apy_sources["compound_v3"] == "fallback_stale"
    # the value RANKED ON is the live 6.9%, never the 3.5% literal
    assert abs(r.apy_used["aave_v3"] - 6.9) < 1e-6
    assert abs(r.apy_used["compound_v3"] - 5.2) < 1e-6
    # live aave out-ranks stale compound → larger (or equal-capped) weight
    assert r.target_weights["aave_v3"] >= r.target_weights["compound_v3"]
    assert r.target_weights["aave_v3"] > 0.0
    # feed coverage reports the split honestly
    assert r.feed_coverage["live"] == 1
    assert r.feed_coverage["fallback_stale"] == 1
    assert r.feed_coverage["total"] == 2


def test_apy_source_labeled_for_every_adapter(tmp_path):
    entries = {
        "aave_v3": _base_entry(1, 0.035),
        "morpho_blue": _base_entry(2, 0.041),
        "maple": _base_entry(2, 0.048),
    }
    live = {"aave_v3": 0.069, "maple": 0.051}
    r = _alloc(tmp_path, entries, live)
    assert r.apy_sources == {
        "aave_v3": "live",
        "maple": "live",
        "morpho_blue": "fallback_stale",
    }
    # every loaded adapter has an as_of stamp
    for p in entries:
        assert p in r.feed_coverage["as_of"]
    assert r.feed_coverage["live_pct"] == pytest.approx(66.7, abs=0.1)


# ───────────────────────── FAIL-CLOSED on bad live feed ─────────────────────
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), 0.0, -0.05])
def test_fail_closed_bad_live_falls_to_labeled_stale(tmp_path, bad):
    """A NaN / Inf / 0 / negative live APY must NOT be used. The adapter falls
    to its labeled stale literal (flagged fallback_stale) — never the bad
    number, never silently 'live'."""
    entries = {"aave_v3": _base_entry(1, 0.035)}
    live = {"aave_v3": bad}
    r = _alloc(tmp_path, entries, live)
    assert r.apy_sources["aave_v3"] == "fallback_stale"
    assert abs(r.apy_used["aave_v3"] - 3.5) < 1e-6   # the stale literal, not `bad`
    # the bad value never reached expected_apy_pct
    assert math.isfinite(r.expected_apy_pct)


def test_fail_closed_out_of_band_live_500pct_rejected(tmp_path):
    """A 500% live spike is out of band → rejected → adapter falls to its stale
    literal (NOT the spike). RED-TEAM: the allocator must NEVER pile into a
    fabricated/anomalous live spike."""
    entries = {"aave_v3": _base_entry(1, 0.035)}
    live = {"aave_v3": 5.0}   # 500% — above 200% band
    r = _alloc(tmp_path, entries, live)
    assert r.apy_sources["aave_v3"] == "fallback_stale"
    assert abs(r.apy_used["aave_v3"] - 3.5) < 1e-6


def test_no_live_and_no_literal_excludes_adapter(tmp_path):
    """No usable live AND no usable literal → adapter excluded entirely (never a
    fabricated number)."""
    bad_entry = _base_entry(1, 0.035)
    bad_entry["fallback_apy"] = 0.0   # unusable literal
    entries = {"aave_v3": bad_entry, "compound_v3": _base_entry(1, 0.052)}
    r = _alloc(tmp_path, entries, {})  # no live
    assert "aave_v3" not in r.apy_sources           # excluded
    assert r.apy_sources["compound_v3"] == "fallback_stale"


# ───────────────────────── RED-TEAM: adversarial mixed feed ─────────────────
def test_red_team_adversarial_feed(tmp_path):
    """The architect's predicted catch: a stale-fallback HIGH literal must NOT
    silently win over a live number; a 500% spike must not be piled into; NaN
    must fail closed; a 29.9% live (just under the 30% gate band) ranks live but
    the TVL floor + tier caps still hold (no over-concentration).

    Adapters:
      aave_v3      live 29.9%  (just under gate band) — ranks LIVE, capped 40%
      morpho_blue  live 500%   (spike)               — REJECTED → stale 4.1%
      maple        live NaN                          — REJECTED → stale 4.8%
      yearn_v3     NO live, stale literal 25% (HIGH)  — stays fallback_stale
      sub_floor    live 10%, TVL $1M (< $5M floor)    — TVL-filtered out
    """
    entries = {
        "aave_v3": _base_entry(1, 0.035),                 # live 29.9 wins
        "morpho_blue": _base_entry(2, 0.041),             # spike → stale 4.1
        "maple": _base_entry(2, 0.048),                   # NaN → stale 4.8
        "yearn_v3": _base_entry(2, 0.25),                 # high stale literal, no live
        "sub_floor": _base_entry(2, 0.10, tvl=1_000_000), # below TVL floor
    }
    live = {
        "aave_v3": 0.299,
        "morpho_blue": 5.0,          # 500% spike
        "maple": float("nan"),
        "sub_floor": 0.10,           # live but TVL kills it
    }
    r = _alloc(tmp_path, entries, live, model="best_apy")

    # provenance: only aave is live; spike/NaN fell to stale; yearn stays stale
    assert r.apy_sources["aave_v3"] == "live"
    assert abs(r.apy_used["aave_v3"] - 29.9) < 1e-6
    assert r.apy_sources["morpho_blue"] == "fallback_stale"
    assert abs(r.apy_used["morpho_blue"] - 4.1) < 1e-6   # NOT 500%
    assert r.apy_sources["maple"] == "fallback_stale"
    assert abs(r.apy_used["maple"] - 4.8) < 1e-6         # NOT NaN
    assert r.apy_sources["yearn_v3"] == "fallback_stale"

    # sub-floor pool is TVL-filtered out of the BOOK (weight 0 / absent)
    assert r.target_weights.get("sub_floor", 0.0) == 0.0
    assert "sub_floor" in r.tvl_filtered_protocols

    # ── RiskPolicy caps STILL hold (no violation introduced) ──
    tier = {"aave_v3": "T1"}  # aave is T1; the rest T2
    for p, w in r.target_weights.items():
        cap = T1_CAP if tier.get(p) == "T1" else T2_CAP
        assert w <= cap + _TOL, f"{p} weight {w} > cap {cap}"
        assert w >= -_TOL, f"{p} negative weight {w}"
    t2_total = sum(w for p, w in r.target_weights.items() if tier.get(p) != "T1")
    assert t2_total <= T2_TOTAL_CAP + _TOL
    assert sum(r.target_weights.values()) <= 1.0 + _TOL

    # the spike never poisoned the expected APY metric
    assert math.isfinite(r.expected_apy_pct)
    # no single pool absorbed the whole book on the basis of a stale-high literal
    # (yearn_v3 25% literal must NOT out-rank/over-concentrate past its T2 cap)
    assert r.target_weights.get("yearn_v3", 0.0) <= T2_CAP + _TOL


def test_stale_high_literal_does_not_beat_live(tmp_path):
    """Direct probe of the architect's predicted flaw: a stale-fallback HIGH
    literal (yearn 25%) must NOT out-rank a LIVE aave whose live APY is lower
    in a way that lets the stale number silently 'win' the live label. We assert
    the live adapter keeps its live label & live value, and the stale one keeps
    its fallback label — provenance is never confused by magnitude."""
    entries = {
        "aave_v3": _base_entry(1, 0.035),    # live 6.9
        "yearn_v3": _base_entry(2, 0.25),    # stale literal 25%, NO live
    }
    live = {"aave_v3": 0.069}
    r = _alloc(tmp_path, entries, live, model="best_apy")
    assert r.apy_sources["aave_v3"] == "live"
    assert r.apy_sources["yearn_v3"] == "fallback_stale"
    # yearn's high literal is honestly labeled stale, not promoted to "live"
    assert r.feed_coverage["fallback_stale_adapters"] == ["yearn_v3"]
    assert r.feed_coverage["live_adapters"] == ["aave_v3"]


# ───────────────────────── provider robustness ─────────────────────────────
def test_provider_callable_form(tmp_path):
    entries = {"aave_v3": _base_entry(1, 0.035)}
    r = _alloc(tmp_path, entries, (lambda: {"aave_v3": 0.069}))
    assert r.apy_sources["aave_v3"] == "live"
    assert abs(r.apy_used["aave_v3"] - 6.9) < 1e-6


def test_provider_failure_fails_closed(tmp_path):
    """A provider that raises must not break allocation — fail closed to stale."""
    def boom():
        raise RuntimeError("feed down")

    entries = {"aave_v3": _base_entry(1, 0.035)}
    r = _alloc(tmp_path, entries, boom)
    assert r.apy_sources["aave_v3"] == "fallback_stale"
    assert abs(r.apy_used["aave_v3"] - 3.5) < 1e-6


def test_pytest_default_provider_does_no_network(tmp_path):
    """Under pytest the DEFAULT provider must be offline (returns {}), so an
    allocator built without an explicit provider ranks on stale literals and
    never touches the network."""
    from spa_core.allocator.allocator import _default_live_apy_provider
    assert _default_live_apy_provider() == {}
