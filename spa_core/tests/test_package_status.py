"""The paper-portfolio read model (ADR-533): three separate dimensions, honest headlines.

# LLM_FORBIDDEN

Sandboxed books in ``tmp_path``; ``now`` injected.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from spa_core.defi_engine import package_status as PS

# FROZEN-DATE-OK: injected-clock — NOW is passed as now= to build_all and PO.record in every test
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _book(tmp, name, *, last_run, experiment=None, rows=0, regime="ENTER", extra=None):
    exps = []
    hist = [{"date": f"old{i}", "equity": 1.0} for i in range(3)]
    if experiment:
        exps = [{"experiment_id": "legacy", "strategy_version": "legacy", "status": "closed"},
                {"experiment_id": experiment, "strategy_version": experiment.split("@")[0], "status": "active",
                 "start_date": "d0", "started_at": _iso(NOW)}]
        hist += [{"date": f"d{i}", "equity": 1.0, "experiment_id": experiment} for i in range(rows)]
    st = {"equity": 100.0, "positions": [], "daily_history": hist, "last_cycle_at": _iso(last_run),
          "experiments": exps, "regime": regime, **(extra or {})}
    (tmp / name).write_text(json.dumps(st), encoding="utf-8")


def _health(tmp, **over):
    agents = [{"label": l, "loaded": True, "last_exit": 0} for l in
              ("com.spa.daily_cycle", "com.spa.hy_cycle", "com.spa.lp_cycle")]
    for a in agents:
        a.update(over.get(a["label"], {}))
    (tmp / "agent_health.json").write_text(json.dumps({"timestamp": _iso(NOW), "agents": agents}))


def test_running_new_version_is_warmup_not_not_started(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW - timedelta(minutes=30),
          experiment="aggressive-susde-loop-v1@d0", rows=1)
    p = PS.build_all(tmp_path, NOW)["packages"]["aggressive"]
    assert p["work"]["state"] == "RUNNING" and p["history"]["state"] == "WARMUP"
    assert p["history"]["valid_periods"] == 1 and p["history"]["earlier_rows_kept"] == 3
    assert "accumulating" in p["headline_en"] and "накапливается" in p["headline_ru"]


def test_old_version_rows_are_not_carried_into_the_new_one(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=0)
    p = PS.build_all(tmp_path, NOW)["packages"]["balanced"]
    assert p["history"]["valid_periods"] == 0 and p["history"]["state"] == "WARMUP"
    assert p["history"]["earlier_rows_kept"] == 3, "the old rows are kept, just not counted"


def test_a_stopped_process_is_failed_not_running(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW - timedelta(hours=7),
          experiment="balanced-fixed-carry-v1@d0", rows=3)
    p = PS.build_all(tmp_path, NOW)["packages"]["balanced"]
    assert p["work"]["state"] == "FAILED" and "7.0 h" in p["work"]["reason"]
    assert "not running" in p["headline_en"]


def test_nonzero_exit_and_unloaded_agent_are_named(tmp_path):
    _health(tmp_path, **{"com.spa.lp_cycle": {"last_exit": 1}, "com.spa.hy_cycle": {"loaded": False}})
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW, experiment="aggressive-susde-loop-v1@d0", rows=2)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=2)
    pk = PS.build_all(tmp_path, NOW)["packages"]
    assert pk["aggressive"]["work"]["state"] == "FAILED" and "exit 1" in pk["aggressive"]["work"]["reason"]
    assert pk["balanced"]["work"]["state"] == "PAUSED"


def test_installed_version_waiting_for_its_first_row_is_shown_separately(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW)
    p = PS.build_all(tmp_path, NOW)["packages"]["aggressive"]
    assert p["running_version"] == "aggressive-legacy-lending"
    assert p["new_version_pending"]["strategy_version"] == "aggressive-susde-loop-v1"
    assert p["data"]["state"] == "WAITING_FOR_DATA"


def test_hold_shows_its_reason(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW, experiment="aggressive-susde-loop-v1@d0", rows=1)
    st = json.loads((tmp_path / "lp_paper_trading.json").read_text())
    st["daily_history"][-1].update(loop_decision="hold", loop_reason="levered net 5.6 % < unlevered 5.3 % + 1.0 pp")
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps(st))
    no_obs = PS.build_all(tmp_path, NOW)["packages"]["aggressive"]
    assert no_obs["data"]["state"] == "WAITING_FOR_DATA", "no observation is not a measured hold"
    from spa_core.paper_trading import paper_observations as PO
    PO.record(tmp_path, "aggressive", NOW, {"data": {"morpho_ok": True}})
    p = PS.build_all(tmp_path, NOW)["packages"]["aggressive"]
    assert p["data"]["state"] == "HOLD" and "levered net" in p["data"]["reason"]


def test_killed_aggressive_book_is_paused_not_running(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW, experiment="aggressive-susde-loop-v1@d0", rows=2,
          extra={"il_drawdown_pct": -0.30})
    p = PS.build_all(tmp_path, NOW)["packages"]["aggressive"]
    assert p["work"]["state"] == "PAUSED" and "kill" in p["work"]["reason"]


def test_absent_book_is_not_started(tmp_path):
    _health(tmp_path)
    pk = PS.build_all(tmp_path, NOW)["packages"]
    assert pk["balanced"]["work"]["state"] == "NOT_STARTED"
    assert pk["conservative"]["work"]["state"] == "NOT_STARTED"


def test_reportable_after_thirty_valid_periods(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=30)
    assert PS.build_all(tmp_path, NOW)["packages"]["balanced"]["history"]["state"] == "REPORTABLE"
