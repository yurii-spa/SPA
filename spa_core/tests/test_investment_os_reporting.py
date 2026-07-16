"""spa_core/tests/test_investment_os_reporting.py — Reporting analyst (AAA Phase 2, step 8).

For the AI Investment OS Reporting analyst (spa_core/investment_os/agents/reporting.py) — distinct from
the Telegram daily-report agent (spa_core/agents/reporting_agent.py). Proves it SURFACES the desk's own
evidenced track + review readiness with L6 evidence tags, invents nothing, and fails CLOSED to UNKNOWN
when the track ledger is unavailable. PURE / sandbox only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.reporting import ReportingAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, *, ledger=True, day30=True):
    lp = tmp_path / "track_ledger.json"
    dp = tmp_path / "day30_review.json"
    if ledger:
        lp.write_text(json.dumps({
            "n_evidenced_days": 19, "days_needed": 30, "days_remaining": 11,
            "cumulative_return_pct": 0.2095, "max_drawdown_from_peak_pct": 0.0,
            "first_evidenced_date": "2026-06-22", "last_evidenced_date": "2026-07-10",
        }))
    if day30:
        dp.write_text(json.dumps({"review_readiness_pct": 63.3, "state": "ACCUMULATING",
                                  "ready_for_review": False, "remaining_days": 11, "min_track_days": 30,
                                  "generated_at": "2026-07-16T08:00:00Z"}))
    return lp, dp


def test_surfaces_track_with_l6_evidence(tmp_path):
    lp, dp = _seed(tmp_path)
    out = ReportingAgent(ledger_path=lp, day30_path=dp, data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["track"]["evidence_level"] == "L6"
    assert out["track"]["value"]["n_evidenced_days"] == 19
    assert out["track"]["value"]["cumulative_return_pct"] == 0.2095
    assert out["review_readiness"]["value"]["state"] == "ACCUMULATING"


def test_missing_ledger_is_unknown(tmp_path):
    lp, dp = _seed(tmp_path, ledger=False)
    out = ReportingAgent(ledger_path=lp, day30_path=dp, data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN and "fail-closed" in out["reason"]


def test_missing_day30_still_reports_track(tmp_path):
    lp, dp = _seed(tmp_path, day30=False)
    out = ReportingAgent(ledger_path=lp, day30_path=dp, data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert out["track"]["value"]["n_evidenced_days"] == 19
    assert out["review_readiness"]["value"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    lp, dp = _seed(tmp_path)
    path = ReportingAgent(ledger_path=lp, day30_path=dp, data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "reporting"
    assert doc["track"]["value"]["days_needed"] == 30
    assert (tmp_path / "reporting_proof.jsonl").exists()
