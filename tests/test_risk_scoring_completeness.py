"""
Risk-scoring completeness — every adapter in ADAPTER_REGISTRY must have a
risk_score, and that score must respect its tier band.

Companion to ``spa_core/risk/protocol_risk_map.py`` (v1.266). These tests are the
guard rail that prevents a newly-added adapter from shipping without a score:
the moment a registry entry has no mapping, the suite goes red.

Tier ↔ risk_score contract (risk_score ∈ [0, 1], higher = riskier):

    T1  risk_score  < 0.25
    T2  0.25 ≤ risk_score ≤ 0.60
    T3  risk_score  > 0.60
"""

import json
from pathlib import Path

import pytest

from spa_core.adapters import ADAPTER_REGISTRY
from spa_core.risk.protocol_risk_map import (
    PROTOCOL_RISK_SCORES,
    DEFAULT_OUTPUT_PATH,
    get_risk_score,
    build_map,
)

_REGISTRY_KEYS = [key for key, _tier, _cls in ADAPTER_REGISTRY]
_REGISTRY_TIERS = {key: tier for key, tier, _cls in ADAPTER_REGISTRY}


def test_every_registry_protocol_has_a_risk_score():
    """1. Every protocol in ADAPTER_REGISTRY has an explicit risk_score entry."""
    missing = [k for k in _REGISTRY_KEYS if k not in PROTOCOL_RISK_SCORES]
    assert not missing, f"adapters with no risk_score: {missing}"


def test_registry_is_not_empty_and_expected_size():
    """2. Registry has the expanded adapter set (>= 30) and the map matches it."""
    assert len(_REGISTRY_KEYS) >= 30, f"registry shrank unexpectedly: {len(_REGISTRY_KEYS)}"
    assert len(PROTOCOL_RISK_SCORES) >= len(_REGISTRY_KEYS)


def test_all_risk_scores_in_unit_interval():
    """3. Every risk_score is a float in [0, 1]."""
    bad = {
        k: e["risk_score"]
        for k, e in PROTOCOL_RISK_SCORES.items()
        if not isinstance(e["risk_score"], (int, float))
        or not (0.0 <= float(e["risk_score"]) <= 1.0)
    }
    assert not bad, f"risk_score outside [0,1]: {bad}"


def test_t1_protocols_below_025():
    """4. T1 protocols have risk_score < 0.25."""
    bad = {
        k: e["risk_score"]
        for k, e in PROTOCOL_RISK_SCORES.items()
        if e["tier"] == "T1" and not (e["risk_score"] < 0.25)
    }
    assert not bad, f"T1 protocols not < 0.25: {bad}"


def test_t2_protocols_in_band():
    """5. T2 protocols have risk_score in [0.25, 0.60]."""
    bad = {
        k: e["risk_score"]
        for k, e in PROTOCOL_RISK_SCORES.items()
        if e["tier"] == "T2" and not (0.25 <= e["risk_score"] <= 0.60)
    }
    assert not bad, f"T2 protocols outside [0.25, 0.60]: {bad}"


def test_t3_protocols_above_060():
    """6. T3 protocols have risk_score > 0.60."""
    bad = {
        k: e["risk_score"]
        for k, e in PROTOCOL_RISK_SCORES.items()
        if e["tier"] == "T3" and not (e["risk_score"] > 0.60)
    }
    assert not bad, f"T3 protocols not > 0.60: {bad}"


def test_map_tier_matches_registry_tier():
    """7. The tier recorded in the map agrees with the registry's tier."""
    mismatched = {
        k: (_REGISTRY_TIERS[k], PROTOCOL_RISK_SCORES[k]["tier"])
        for k in _REGISTRY_KEYS
        if k in PROTOCOL_RISK_SCORES and _REGISTRY_TIERS[k] != PROTOCOL_RISK_SCORES[k]["tier"]
    }
    assert not mismatched, f"tier mismatch (registry, map): {mismatched}"


def test_get_risk_score_resolves_every_registry_key():
    """8. get_risk_score() returns an in-range score for every registry key."""
    for key in _REGISTRY_KEYS:
        score = get_risk_score(key, _REGISTRY_TIERS[key])
        assert 0.0 <= score <= 1.0, f"{key} -> {score}"


def test_get_risk_score_tier_fallback_for_unknown_key():
    """9. An unknown key falls back to the tier mid-band default (still in-range)."""
    assert get_risk_score("does_not_exist", "T1") < 0.25
    assert 0.25 <= get_risk_score("does_not_exist", "T2") <= 0.60
    assert get_risk_score("does_not_exist", "T3") > 0.60
    # No tier and unknown key -> neutral T2 default, still valid.
    assert 0.0 <= get_risk_score("does_not_exist") <= 1.0


def test_exported_json_snapshot_is_consistent():
    """10. The on-disk data/protocol_risk_map.json (if present) matches the map."""
    path = Path(DEFAULT_OUTPUT_PATH)
    if not path.exists():
        pytest.skip("protocol_risk_map.json not generated yet")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    on_disk = snapshot.get("protocols", {})
    # Every registry key present on disk with a matching score.
    for key in _REGISTRY_KEYS:
        assert key in on_disk, f"{key} missing from exported JSON"
        assert on_disk[key]["risk_score"] == PROTOCOL_RISK_SCORES[key]["risk_score"]
    # build_map() count agrees with the registry coverage.
    assert build_map()["count"] == len(PROTOCOL_RISK_SCORES)
