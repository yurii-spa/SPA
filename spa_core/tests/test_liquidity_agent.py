"""spa_core/tests/test_liquidity_agent.py — Liquidity analyst (AAA Phase 2, step 11).

Proves it CONSUMES the desk's exit-liquidity measurement (latest log entry) into an advisory view —
score, instantly-exitable $, exit-label + bottleneck breakdown — evidence-tagged, and fails CLOSED to
UNKNOWN when the log is missing/empty. PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.liquidity import LiquidityAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, entries=None):
    p = tmp_path / "exit_liquidity_log.json"
    if entries is None:
        entries = [
            {"average_exit_liquidity_score": 50.0, "positions": []},  # older
            {"average_exit_liquidity_score": 80.0, "instantly_exitable_usd": 12000.0,
             "liquidity_ratio_pct": 40.0, "most_locked": "pendle_pt",
             "positions": [
                 {"exit_label": "INSTANT", "bottleneck": "MARKET_DEPTH"},
                 {"exit_label": "INSTANT", "bottleneck": "MARKET_DEPTH"},
                 {"exit_label": "SLOW", "bottleneck": "LOCKUP"},
             ]},  # latest
        ]
    p.write_text(json.dumps(entries))
    return p


def test_consumes_latest_entry(tmp_path):
    out = LiquidityAgent(exit_log_path=_seed(tmp_path), data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    v = out["exit_liquidity"]["value"]
    assert v["average_exit_liquidity_score"] == 80.0   # latest, not the older 50.0
    assert v["instantly_exitable_usd"] == 12000.0
    assert v["n_positions"] == 3
    assert v["by_exit_label"] == {"INSTANT": 2, "SLOW": 1}
    assert v["top_bottlenecks"]["MARKET_DEPTH"] == 2
    assert out["exit_liquidity"]["evidence_level"] == "L4"


def test_missing_log_is_unknown(tmp_path):
    out = LiquidityAgent(exit_log_path=tmp_path / "nope.json", data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN and "fail-closed" in out["reason"]


def test_empty_log_is_unknown(tmp_path):
    p = tmp_path / "exit_liquidity_log.json"
    p.write_text("[]")
    assert LiquidityAgent(exit_log_path=p, data_dir=tmp_path).analyze()["status"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    path = LiquidityAgent(exit_log_path=_seed(tmp_path), data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "liquidity"
    assert doc["exit_liquidity"]["value"]["n_positions"] == 3
    assert (tmp_path / "liquidity_proof.jsonl").exists()
