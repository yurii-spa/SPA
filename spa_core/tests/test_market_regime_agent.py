"""spa_core/tests/test_market_regime_agent.py — Market Regime analyst (AAA Phase 2, reshape).

Proves the analyst CONSUMES the desk's two regime feeds (yield + funding), never recomputes, tags each
with evidence, derives a fail-safe most-cautious combined posture, and fails CLOSED to UNKNOWN when both
sources are gone. PURE / sandbox files only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.market_regime import MarketRegimeAgent, _combine_posture
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, yield_regime="STABLE", funding_regime="GREEN", both=True):
    yp = tmp_path / "market_regime.json"
    fp = tmp_path / "funding_regime.json"
    if both or yield_regime is not None:
        yp.write_text(json.dumps({"regime": yield_regime, "t1_avg_apy": 4.1, "apy_std_dev": 0.6,
                                  "recommendation": "hold", "detected_at": "2026-07-16T07:00:00Z"}))
    if both or funding_regime is not None:
        fp.write_text(json.dumps({"regime": funding_regime, "primary_symbol": "ETH",
                                  "as_of_utc": "2026-07-16T22:00:00Z",
                                  "symbols": {"ETH": {"regime": funding_regime}, "BTC": {"regime": "GREEN"}}}))
    return yp, fp


def test_both_feeds_ok(tmp_path):
    yp, fp = _seed(tmp_path)
    out = MarketRegimeAgent(yield_path=yp, funding_path=fp, data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["yield_regime"]["value"]["regime"] == "STABLE"
    assert out["funding_regime"]["value"]["regime"] == "GREEN"
    assert out["yield_regime"]["evidence_level"] == "L4"
    assert out["combined_posture"] == "STABLE"     # STABLE(1) more cautious than GREEN(0)


def test_combined_posture_most_cautious():
    assert _combine_posture("GREEN", "RED") == "RED"
    assert _combine_posture("GREEN", "GREEN") == "GREEN"
    assert _combine_posture("YELLOW", "GREEN") == "YELLOW"
    assert _combine_posture(None, "GREEN") == "GREEN"      # unknown one side → use the known
    assert _combine_posture(None, None) == UNKNOWN
    assert _combine_posture("WEIRD", "GREEN") == "GREEN"   # unrecognised label → prefer known


def test_one_feed_missing_still_ok(tmp_path):
    yp, fp = _seed(tmp_path)
    fp.unlink()  # funding feed gone
    out = MarketRegimeAgent(yield_path=yp, funding_path=fp, data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["yield_regime"]["value"]["regime"] == "STABLE"
    assert out["funding_regime"]["value"] == UNKNOWN


def test_both_missing_is_unknown(tmp_path):
    out = MarketRegimeAgent(yield_path=tmp_path / "no1.json", funding_path=tmp_path / "no2.json",
                            data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN


def test_stale_feed_treated_as_missing(tmp_path):
    import os
    yp, fp = _seed(tmp_path)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(yp, (old, old)); os.utime(fp, (old, old))
    out = MarketRegimeAgent(yield_path=yp, funding_path=fp, data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    yp, fp = _seed(tmp_path)
    path = MarketRegimeAgent(yield_path=yp, funding_path=fp, data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "market_regime"
    assert doc["combined_posture"] == "STABLE"
    assert (tmp_path / "market_regime_proof.jsonl").exists()
