"""Tests for spa_core/strategy_lab/swarm/funding_regime.py (Swarm block 3 — L1 regime classifier)."""
from __future__ import annotations

import json

import pytest

from spa_core.strategy_lab.swarm import funding_regime as fr


def _series(n: int, base: float = 0.0001, tail: list[float] | None = None,
            noise_amp: float = 0.0) -> dict[str, float]:
    """n days ending 2026-07-10; optional `tail` overrides the LAST len(tail) days."""
    from datetime import date, timedelta
    end = date(2026, 7, 10)
    vals = []
    x = 12345
    for i in range(n):
        v = base
        if noise_amp:
            x = (x * 1103515245 + 12345) % (2 ** 31)
            v += ((x / 2 ** 31) - 0.5) * noise_amp
        vals.append(v)
    if tail:
        vals[-len(tail):] = tail
    return {(end - timedelta(days=n - 1 - i)).isoformat(): vals[i] for i in range(n)}


# ── classify: the four regimes ─────────────────────────────────────────────────────────────────
def test_green_rich_stable_carry():
    # 0.0003/8h ≈ 32.8% ann, tiny noise → GREEN
    out = fr.classify(_series(90, base=0.0003, noise_amp=0.00002))
    assert out["regime"] == "GREEN"
    assert out["metrics"]["carry_ann_pct_7d"] > fr.THRESHOLDS["THIN_CARRY_ANN_PCT"]


def test_red_inverted_funding():
    out = fr.classify(_series(90, base=0.0003, noise_amp=0.00002,
                              tail=[-0.0002] * 7))
    assert out["regime"] == "RED"
    assert any("inverted" in r or "negative" in r for r in out["reasons"])


def test_red_majority_negative_days():
    # median stays barely positive but 4/7 days negative → RED by neg-days rule
    tail = [-0.0001, 0.0004, -0.0001, 0.0004, -0.0001, 0.0004, -0.0001]
    out = fr.classify(_series(90, base=0.0003, noise_amp=0.00002, tail=tail))
    assert out["regime"] == "RED"
    assert out["metrics"]["neg_days_of_last_7"] == 4


def test_yellow_fast_compression():
    # rich 30d history, last 7 days collapse to 40% of it (still positive, still fat) → YELLOW
    out = fr.classify(_series(90, base=0.0010, noise_amp=0.00002,
                              tail=[0.0004] * 7))
    assert out["regime"] == "YELLOW"
    assert any("compression" in r for r in out["reasons"])


def test_yellow_vol_spike():
    # calm baseline then violent oscillation (mean preserved, fat ann carry) → YELLOW via vol
    tail = [0.0030, -0.0004, 0.0030, -0.0004, 0.0030, -0.0004, 0.0030,
            -0.0004, 0.0030, -0.0004, 0.0030, -0.0004, 0.0030, 0.0030]
    out = fr.classify(_series(120, base=0.0008, noise_amp=0.00001, tail=tail))
    assert out["regime"] == "YELLOW"
    assert any("vol" in r for r in out["reasons"])


def test_yellow_thin_carry():
    # positive and stable but ≈1.1% ann — not worth the tail → YELLOW
    out = fr.classify(_series(90, base=0.00001, noise_amp=0.000001))
    assert out["regime"] == "YELLOW"
    assert any("thin" in r for r in out["reasons"])


def test_unknown_short_history_fail_closed():
    out = fr.classify(_series(fr.THRESHOLDS["MIN_HISTORY_DAYS"] - 1, base=0.0003))
    assert out["regime"] == "UNKNOWN"


def test_classify_deterministic():
    s = _series(90, base=0.0003, noise_amp=0.00003)
    assert fr.classify(s) == fr.classify(dict(s))


# ── run: provider failures + status/proof ──────────────────────────────────────────────────────
def test_run_provider_failure_is_unknown(tmp_path):
    def provider(sym):
        if sym == "BTC":
            raise ConnectionError("all venues down")
        return _series(90, base=0.0003, noise_amp=0.00002)

    doc = fr.run_funding_regime(provider=provider, out_dir=tmp_path)
    assert doc["symbols"]["ETH"]["regime"] == "GREEN"
    assert doc["symbols"]["BTC"]["regime"] == "UNKNOWN"
    assert doc["regime"] == "GREEN"  # primary = ETH
    assert "feed failed" in doc["symbols"]["BTC"]["reasons"][0]


def test_run_writes_status_and_daily_proof(tmp_path):
    provider = lambda sym: _series(90, base=0.0003, noise_amp=0.00002)  # noqa: E731
    doc = fr.run_funding_regime(provider=provider, out_dir=tmp_path)
    assert doc["proof_appended"] is True
    saved = json.loads((tmp_path / fr.STATUS_NAME).read_text())
    assert saved["regime"] == "GREEN" and saved["is_advisory"] is True
    assert "not-GREEN" in saved["consumer_contract"]

    doc2 = fr.run_funding_regime(provider=provider, out_dir=tmp_path)
    assert doc2["proof_appended"] is False  # idempotent per day
    lines = (tmp_path / fr.PROOF_NAME).read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["regime"] == "GREEN" and rec["per_symbol"] == {"ETH": "GREEN", "BTC": "GREEN"}


def test_run_all_feeds_dead_fail_closed(tmp_path):
    def provider(sym):
        raise TimeoutError("network gone")
    doc = fr.run_funding_regime(provider=provider, out_dir=tmp_path)
    assert doc["regime"] == "UNKNOWN"
    assert all(v["regime"] == "UNKNOWN" for v in doc["symbols"].values())
