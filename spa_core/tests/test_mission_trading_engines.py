"""S4 K3: два раздельных paper-движка на пульте Director OS — тот же проектор S3, без суммы, без ложной защиты."""
from datetime import datetime, timezone
from pathlib import Path

from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import trading_engines as te

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — _trading_engines_section(now=NOW)


def _blocks(present=(True, True)):
    return {"blocks": [{"engine": "spa_trading_research", "present": present[0], "freshness": "LIVE",
                        "provenance": "spa", "as_of": "x", "why_no_result": None if present[0] else "нет"},
                       {"engine": "earn_defi", "present": present[1], "freshness": "STALE",
                        "provenance": "earn", "as_of": "y", "why_no_result": None if present[1] else "нет"}],
            "note": "n"}


def test_two_separate_blocks_not_summed_and_aggregate_not_claimed(monkeypatch, tmp_path):
    monkeypatch.setattr(te, "build_trading", lambda now=None, data_dir=None, earn_dir=None: _blocks())
    sec = mc._trading_engines_section(tmp_path, NOW)
    assert [b["engine"] for b in sec["blocks"]] == ["spa_trading_research", "earn_defi"]
    assert sec["summed"] is False and sec["_meta"]["state"] == "HEALTHY"
    assert "not a live protection" in sec["aggregate_admission"]
    assert [b["recency"] for b in sec["blocks"]] == ["LIVE", "STALE"]
    assert sec["blocks"][1]["evidence"]["canon"] == "earn"
    assert not any(k for k in sec if "total" in k or "sum" == k)


def test_one_missing_engine_is_degraded_with_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(te, "build_trading", lambda now=None, data_dir=None, earn_dir=None: _blocks((True, False)))
    sec = mc._trading_engines_section(tmp_path, NOW)
    assert sec["_meta"]["state"] == "DEGRADED" and "earn_defi" in (sec["_meta"].get("reason") or "")


def test_projector_failure_is_not_measured_not_a_crash(monkeypatch, tmp_path):
    def boom(**kw):
        raise RuntimeError("db locked")
    monkeypatch.setattr(te, "build_trading", boom)
    sec = mc._trading_engines_section(tmp_path, NOW)
    assert sec["_meta"]["state"] == "NOT_MEASURED" and "db locked" in sec["_meta"]["reason"]


def test_real_projector_on_empty_dirs_names_both_gaps(tmp_path, monkeypatch):
    monkeypatch.setenv("EARN_DEFI_DIR", str(tmp_path / "no-earn"))
    sec = mc._trading_engines_section(tmp_path, NOW)
    assert [b["present"] for b in sec["blocks"]] == [False, False]
    assert all(b["why_no_result"] for b in sec["blocks"]) and sec["_meta"]["state"] == "NOT_MEASURED"


def test_contract_declares_the_section():
    assert any(c["path"] == "capital.trading_engines" for c in mc.CONTRACT)
