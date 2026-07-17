"""spa_core/tests/test_market_structure_agent.py — Market Structure analyst (AAA Phase 2)."""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.market_structure import MarketStructureAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, risk=28.0, dangerous=0):
    p = tmp_path / "cross_asset_correlation_log.json"
    p.write_text(json.dumps([
        {"ts": "2026-07-16T00:00:00Z", "avg_correlation_risk": 10.0},
        {"ts": "2026-07-17T00:00:00Z", "avg_correlation_risk": risk, "dangerous_count": dangerous,
         "well_diversified_count": 2, "most_concentrated": "P1", "portfolio_count": 1},
    ]))
    return p


def test_consumes_latest_none_concern(tmp_path):
    out = MarketStructureAgent(corr_log_path=_seed(tmp_path), data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["market_structure"]["value"]["avg_correlation_risk"] == 28.0
    assert out["concern"] == "NONE_SURFACED"
    assert out["market_structure"]["evidence_level"] == "L4"


def test_dangerous_correlation_flags(tmp_path):
    out = MarketStructureAgent(corr_log_path=_seed(tmp_path, dangerous=1), data_dir=tmp_path).analyze()
    assert out["concern"] == "DANGEROUS_CORRELATION"


def test_high_risk_flags(tmp_path):
    out = MarketStructureAgent(corr_log_path=_seed(tmp_path, risk=75.0), data_dir=tmp_path).analyze()
    assert out["concern"] == "HIGH_CORRELATION_RISK"


def test_missing_is_unknown(tmp_path):
    out = MarketStructureAgent(corr_log_path=tmp_path / "no.json", data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    path = MarketStructureAgent(corr_log_path=_seed(tmp_path), data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "market_structure"
    assert (tmp_path / "market_structure_proof.jsonl").exists()
