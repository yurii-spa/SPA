"""spa_core/tests/test_chief_investment_agent.py — Chief Investment analyst (Head of Product synthesis).

Proves the capstone SYNTHESISES the other analysts' artifacts into one house-view: most-cautious posture,
surfaced (not averaged) conflicts, opportunities/track/liquidity preserved with their tags, honest
coverage, owner_gate flag; and fails CLOSED to UNKNOWN with no inputs. It moves NO capital and emits NO
auto-executed allocation. PURE / sandbox only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.chief_investment import ChiefInvestmentAgent, _synthesise_posture
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _seed(tmp_path, **artifacts):
    for name, payload in artifacts.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))


def test_synthesise_posture_most_cautious_and_conflicts():
    assert _synthesise_posture("GREEN", "CRITICAL") == ("CRITICAL", [
        "regime=GREEN vs threat=CRITICAL diverge — surfaced, not averaged"])
    assert _synthesise_posture("STABLE", "NO_THREAT_OBSERVED")[0] == "STABLE"
    assert _synthesise_posture(None, "THREATS_PRESENT")[0] == "THREATS_PRESENT"
    assert _synthesise_posture("UNKNOWN_CAUTIOUS", "UNKNOWN_CAUTIOUS")[0] == "UNKNOWN_CAUTIOUS"


def test_full_synthesis(tmp_path):
    _seed(tmp_path,
          market_regime={"combined_posture": "STABLE"},
          red_team={"posture": "NO_THREAT_OBSERVED"},
          stablecoin_yield={"top_stablecoin_yields": [
              {"value": {"protocol": "aave_usdc"}}, {"value": {"protocol": "morpho_usdc"}},
              {"value": {"protocol": "sky_susds"}}, {"value": {"protocol": "extra"}}]},
          reporting={"track": {"value": {"n_evidenced_days": 19}, "evidence_level": "L6"}},
          liquidity={"exit_liquidity": {"value": {"average_exit_liquidity_score": 80.0}}})
    out = ChiefInvestmentAgent(data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    hv = out["house_view"]
    assert hv["overall_posture"] == "STABLE"
    assert len(hv["top_opportunities"]) == 3       # capped at 3
    assert hv["evidenced_track"]["evidence_level"] == "L6"   # tag preserved
    assert out["owner_gate"] is True
    assert out["coverage"]["n_analysts"] == 5
    # never emits an auto-executed allocation
    assert "allocation" not in out and "execute" not in out


def test_conflict_is_surfaced(tmp_path):
    _seed(tmp_path, market_regime={"combined_posture": "GREEN"}, red_team={"posture": "CRITICAL"})
    out = ChiefInvestmentAgent(data_dir=tmp_path).analyze()
    assert out["house_view"]["overall_posture"] == "CRITICAL"
    assert out["house_view"]["conflicts"]           # divergence surfaced


def test_partial_coverage_reports_missing(tmp_path):
    _seed(tmp_path, reporting={"track": {"value": {"n_evidenced_days": 19}}})
    out = ChiefInvestmentAgent(data_dir=tmp_path).analyze()
    assert out["status"] == "ok"
    assert "stablecoin_yield" in out["coverage"]["missing_or_unknown"]
    assert out["coverage"]["available"] == ["reporting"]


def test_no_inputs_is_unknown(tmp_path):
    out = ChiefInvestmentAgent(data_dir=tmp_path).analyze()
    assert out["status"] == UNKNOWN and "fail-closed" in out["reason"]


def test_run_emits_advisory_owner_gated_artifact(tmp_path):
    _seed(tmp_path, market_regime={"combined_posture": "STABLE"}, red_team={"posture": "NO_THREAT_OBSERVED"})
    path = ChiefInvestmentAgent(data_dir=tmp_path).run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True and doc["agent"] == "chief_investment"
    assert doc["owner_gate"] is True
    assert (tmp_path / "chief_investment_proof.jsonl").exists()
