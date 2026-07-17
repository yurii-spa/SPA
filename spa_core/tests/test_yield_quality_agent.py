"""spa_core/tests/test_yield_quality_agent.py — Yield Quality analyst (AAA Phase 2).

Proves it decomposes advertised vs sustainable yield from the desk's log, surfaces a cautious concern
(LOW_SUSTAINABILITY / HIGH_INCENTIVE_DECAY), and fails CLOSED to UNKNOWN. PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.yield_quality import YieldQualityAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, ratio=0.9, decay=5.0):
    p = tmp_path / "apy_decomposition_log.json"
    p.write_text(json.dumps([
        {"ts": "2026-07-16T00:00:00Z", "sustainability_ratio": 1.0},  # older
        {"ts": "2026-07-17T00:00:00Z", "protocol_name": "aave_usdc",
         "total_advertised_apy_pct": 6.0, "sustainable_apy_pct": 6.0 * ratio,
         "sustainability_ratio": ratio, "apy_label": "SUSTAINABLE_YIELD",
         "apy_quality_score": 90, "incentive_decay_risk_pct": decay},
    ]))
    return p


def test_decomposes_latest(tmp_path):
    out = YieldQualityAgent(decomp_path=_seed(tmp_path), data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    v = out["yield_quality"]["value"]
    assert v["total_advertised_apy_pct"] == 6.0
    assert v["sustainability_ratio"] == 0.9
    assert out["concern"] == "NONE_SURFACED"
    assert out["yield_quality"]["evidence_level"] == "L4"


def test_low_sustainability_flags(tmp_path):
    out = YieldQualityAgent(decomp_path=_seed(tmp_path, ratio=0.4), data_dir=tmp_path).analyze()
    assert out["concern"] == "LOW_SUSTAINABILITY"


def test_high_decay_flags(tmp_path):
    out = YieldQualityAgent(decomp_path=_seed(tmp_path, ratio=0.9, decay=55.0), data_dir=tmp_path).analyze()
    assert out["concern"] == "HIGH_INCENTIVE_DECAY"


def test_missing_is_unknown(tmp_path):
    out = YieldQualityAgent(decomp_path=tmp_path / "no.json", data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    path = YieldQualityAgent(decomp_path=_seed(tmp_path), data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "yield_quality"
    assert (tmp_path / "yield_quality_proof.jsonl").exists()
