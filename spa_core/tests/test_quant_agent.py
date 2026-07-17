"""spa_core/tests/test_quant_agent.py — Quant & Backtesting analyst (AAA Phase 2).

Proves it surfaces the backtest↔paper rank correlation, flags WEAK_MODEL_FIT below ρ=0.70 and
INSUFFICIENT_PAPER_DAYS under 30 days, and fails CLOSED to UNKNOWN. PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.quant import QuantBacktestAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, rho=0.85, paper_days=35):
    p = tmp_path / "backtest_vs_paper.json"
    p.write_text(json.dumps({"generated_at": "2026-07-17T00:00:00Z", "rank_correlation": rho,
                             "confidence": "HIGH", "paper_days": paper_days,
                             "strategies": ["a", "b"], "summary": "ok"}))
    return p


def test_strong_fit_no_concern(tmp_path):
    out = QuantBacktestAgent(bt_path=_seed(tmp_path), data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["model_trust"]["value"]["rank_correlation"] == 0.85
    assert out["concern"] == "NONE_SURFACED"
    assert out["model_trust"]["evidence_level"] == "L5"


def test_weak_fit_flags(tmp_path):
    out = QuantBacktestAgent(bt_path=_seed(tmp_path, rho=0.4), data_dir=tmp_path).analyze()
    assert out["concern"] == "WEAK_MODEL_FIT"


def test_insufficient_days_when_no_rho(tmp_path):
    p = tmp_path / "backtest_vs_paper.json"
    p.write_text(json.dumps({"rank_correlation": None, "paper_days": 12}))
    out = QuantBacktestAgent(bt_path=p, data_dir=tmp_path).analyze()
    assert out["concern"] == "INSUFFICIENT_PAPER_DAYS"


def test_missing_is_unknown(tmp_path):
    out = QuantBacktestAgent(bt_path=tmp_path / "no.json", data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    path = QuantBacktestAgent(bt_path=_seed(tmp_path), data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "quant"
    assert (tmp_path / "quant_proof.jsonl").exists()
