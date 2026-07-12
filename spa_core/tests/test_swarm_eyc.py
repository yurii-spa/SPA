"""Tests for spa_core/strategy_lab/swarm/eyc_allocator.py (EYC v2 shadow allocator, idea #6)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.strategy_lab.swarm import eyc_allocator as ey

NOW = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


# ── pure math ──────────────────────────────────────────────────────────────────────────────────
def test_eq_score_shrinks_spike_toward_base():
    # spot 8% over base 3%, hl 2d, H 14d → most of the excess is gone in the mean
    s = ey.eq_score(8.0, 3.0, 2.0, 14)
    assert 3.0 < s < 4.5
    assert ey.eq_score(3.0, 3.0, 2.0) == pytest.approx(3.0)      # no excess → base
    assert ey.eq_score(8.0, 3.0, None) == 3.0                     # no persistence → base only


def test_eq_score_long_half_life_keeps_more():
    assert ey.eq_score(8.0, 3.0, 30.0) > ey.eq_score(8.0, 3.0, 2.0)


def test_dilution_quadratic():
    assert ey.dilution_at_size(0, 1e9) == pytest.approx(1.0)
    d = ey.dilution_at_size(1e8, 1e9)  # 10% of pool → (1/1.1)² ≈ 0.826
    assert d == pytest.approx((1 / 1.1) ** 2)
    assert ey.dilution_at_size(1e6, 0) is None                    # unknown supply → None, not 1


def test_measure_half_life_on_synthetic_spike():
    apys = [3.0] * 40 + [9.0, 7.0, 5.5, 4.2, 3.5, 3.2] + [3.0] * 20
    hl = ey.measure_half_life(apys)
    assert hl is not None and 1 <= hl <= 4                        # (9+3)/2=6 → crossed by day ~2
    assert ey.measure_half_life([3.0] * 100) is None              # no spikes → honest None


# ── run: injected artifacts ────────────────────────────────────────────────────────────────────
def _ranking(tmp: Path, rows: list[dict], age_h: float = 1.0) -> Path:
    p = tmp / "apy_ranking.json"
    p.write_text(json.dumps({
        "generated_at": (NOW - timedelta(hours=age_h)).isoformat(),
        "by_apy": rows}))
    return p


BASELINES = {
    "aave_v3_usdc": {"baseline": 3.0, "half_life_d": 2.0, "history_days": 365},
    "morpho_blue_usdc": {"baseline": 4.5, "half_life_d": 5.0, "history_days": 365},
}


def test_divergence_spot_vs_equilibrium(tmp_path):
    """The core story: a spiked venue wins on spot but loses on equilibrium at size."""
    rows = [
        {"protocol": "aave_v3", "apy_pct": 9.0, "tvl_usd": 2e9},       # spike (base 3, hl 2d)
        {"protocol": "morpho_blue", "apy_pct": 4.8, "tvl_usd": 5e8},   # steady near base 4.5
    ]
    doc = ey.run_eyc_allocator(ranking_path=_ranking(tmp_path, rows),
                               out_dir=tmp_path / "swarm", now=NOW, baselines=BASELINES)
    assert doc["state"] == "SCORED"
    assert doc["picks"]["$100,000"]["spot_pick"] == "aave_v3_usdc"
    assert doc["picks"]["$100,000"]["eyc_pick"] == "morpho_blue_usdc"   # equilibrium sees through
    assert doc["picks"]["$100,000"]["divergence"] is True
    a = doc["venues"]["aave_v3_usdc"]
    assert a["equilibrium_score_pct"] < a["spot_apy_pct"]               # spike shrunk


def test_size_awareness_dilutes_small_pool(tmp_path):
    """Same equilibrium scores, but the small pool dies at $50M — the at-size table must show it."""
    rows = [
        {"protocol": "aave_v3", "apy_pct": 3.0, "tvl_usd": 2e9},
        {"protocol": "morpho_blue", "apy_pct": 4.6, "tvl_usd": 5e7},   # better yield, tiny pool
    ]
    doc = ey.run_eyc_allocator(ranking_path=_ranking(tmp_path, rows),
                               out_dir=tmp_path / "swarm", now=NOW, baselines=BASELINES)
    assert doc["picks"]["$100,000"]["eyc_pick"] == "morpho_blue_usdc"  # small size: yield wins
    assert doc["picks"]["$50,000,000"]["eyc_pick"] == "aave_v3_usdc"   # big size: depth wins
    m50 = doc["venues"]["morpho_blue_usdc"]["apy_after_us_at_size"]["$50,000,000"]
    assert m50 < doc["venues"]["morpho_blue_usdc"]["equilibrium_score_pct"] * 0.5  # crushed


def test_unscored_never_guessed(tmp_path):
    rows = [{"protocol": "aave_v3", "apy_pct": 3.5, "tvl_usd": 2e9},
            {"protocol": "yearn_v3", "apy_pct": 7.7, "tvl_usd": 1e8}]  # no baseline injected
    doc = ey.run_eyc_allocator(ranking_path=_ranking(tmp_path, rows),
                               out_dir=tmp_path / "swarm", now=NOW, baselines=BASELINES)
    assert "yearn_v3_usdc" in doc["unscored"]
    assert "yearn_v3_usdc" not in doc["venues"]


def test_stale_ranking_fail_closed(tmp_path):
    rows = [{"protocol": "aave_v3", "apy_pct": 3.5, "tvl_usd": 2e9}]
    doc = ey.run_eyc_allocator(
        ranking_path=_ranking(tmp_path, rows, age_h=ey.RANKING_MAX_AGE_H + 1),
        out_dir=tmp_path / "swarm", now=NOW, baselines=BASELINES)
    assert doc["state"] == "UNAVAILABLE" and "venues" not in doc


def test_status_and_proof_idempotent(tmp_path):
    rows = [{"protocol": "aave_v3", "apy_pct": 3.5, "tvl_usd": 2e9}]
    out = tmp_path / "swarm"
    doc = ey.run_eyc_allocator(ranking_path=_ranking(tmp_path, rows),
                               out_dir=out, now=NOW, baselines=BASELINES)
    assert doc["proof_appended"] is True
    saved = json.loads((out / ey.STATUS_NAME).read_text())
    assert saved["is_advisory"] and "NONE" in saved["algorithm"]["authority"]
    doc2 = ey.run_eyc_allocator(ranking_path=_ranking(tmp_path, rows),
                                out_dir=out, now=NOW + timedelta(hours=1), baselines=BASELINES)
    assert doc2["proof_appended"] is False
    assert len((out / ey.PROOF_NAME).read_text().splitlines()) == 1
