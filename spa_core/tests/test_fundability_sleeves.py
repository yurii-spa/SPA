"""spa_core/tests/test_fundability_sleeves.py — Q-OWN-05 public per-sleeve verdicts.

Covers /api/fundability/sleeves: serves forward-analytics verdicts VERBATIM, keeps THIN_TRACK
(not enough data) and BELOW_FLOOR (has data, below floor) DISTINCT, sorts the flagship first, and
fails closed to an honest empty when the artifact is absent. No network, deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

from spa_core.api.routers import fundability as F


def _seed(tmp_path, tracks, floor=3.2):
    (tmp_path / "forward_analytics.json").write_text(
        json.dumps({"rwa_floor_apy_pct": floor, "min_points_for_ratio": 7,
                    "generated_at": "2026-07-12T00:00:00Z", "tracks": tracks}),
        encoding="utf-8",
    )


def test_verdicts_served_and_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "_DATA", tmp_path)
    _seed(tmp_path, [
        {"name": "paper/rates_desk_fixed_carry", "verdict": "BELOW_FLOOR", "excess_vs_floor_pct": -2.5, "n_points": 18, "days_to_robust_verdict": 2},
        {"name": "strategy_lab_paper/engine_a", "verdict": "BEATS_FLOOR", "excess_vs_floor_pct": 0.2, "n_points": 19},
        {"name": "strategy_lab_paper/fluid", "verdict": "THIN_TRACK", "excess_vs_floor_pct": 1.0, "n_points": 9, "days_to_robust_verdict": 11},
    ])
    d = F.sleeves()
    assert d["available"] is True
    assert d["counts"] == {"BEATS_FLOOR": 1, "THIN_TRACK": 1, "BELOW_FLOOR": 1}
    assert d["rwa_floor_apy_pct"] == 3.2
    assert d["evidence_level"] == "paper"
    # names cleaned of store prefix
    names = [s["name"] for s in d["sleeves"]]
    assert "rates_desk_fixed_carry" in names and "paper/" not in "".join(names)


def test_flagship_sorted_first_even_when_below_floor(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "_DATA", tmp_path)
    _seed(tmp_path, [
        {"name": "strategy_lab_paper/engine_a", "verdict": "BEATS_FLOOR", "excess_vs_floor_pct": 5.0, "n_points": 19},
        {"name": "paper/rates_desk_fixed_carry", "verdict": "BELOW_FLOOR", "excess_vs_floor_pct": -2.5, "n_points": 18},
    ])
    d = F.sleeves()
    assert d["sleeves"][0]["name"] == "rates_desk_fixed_carry"
    assert d["sleeves"][0]["is_flagship"] is True
    assert d["sleeves"][0]["verdict"] == "BELOW_FLOOR"  # honest flagship prominent, not buried


def test_thin_and_below_are_distinct_states(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "_DATA", tmp_path)
    _seed(tmp_path, [
        {"name": "a", "verdict": "THIN_TRACK", "n_points": 5, "days_to_robust_verdict": 20},
        {"name": "b", "verdict": "BELOW_FLOOR", "excess_vs_floor_pct": -1.0, "n_points": 18},
    ])
    verdicts = {s["name"]: s["verdict"] for s in F.sleeves()["sleeves"]}
    assert verdicts["a"] == "THIN_TRACK" and verdicts["b"] == "BELOW_FLOOR"


def test_fails_closed_when_artifact_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "_DATA", tmp_path)  # empty dir → no forward_analytics.json
    d = F.sleeves()
    assert d["available"] is False
    assert d["sleeves"] == []
    assert "not yet available" in d["note"]
