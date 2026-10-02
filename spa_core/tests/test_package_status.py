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


def test_an_overdue_run_without_a_confirmed_fault_is_unknown_not_running(tmp_path):
    # ADR-537: red (FAILED) is kept for a CONFIRMED fault; an overdue run with exit 0 is UNKNOWN —
    # it is still never RUNNING, which is what the earlier form of this test protected.
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW - timedelta(hours=7),
          experiment="balanced-fixed-carry-v1@d0", rows=3)
    p = PS.build_all(tmp_path, NOW)["packages"]["balanced"]
    assert p["work"]["state"] == "UNKNOWN" and "7.0 h" in p["work"]["reason"]
    assert "not confirmed" in p["headline_en"] and "7,0" in p["work"]["reason_ru"]
    assert "no successful run" not in p["headline_ru"], "the RU headline is Russian"


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
    assert p["data"]["state"] == "HEALTHY", "a correct HOLD is a decision, not a data fault"
    assert p["decision"]["state"] == "HOLD" and "levered net" in p["decision"]["reason"]
    assert "петли" in p["decision"]["reason_ru"]


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



def test_reasons_are_people_sentences_in_both_languages():
    en, ru = PS.localized_reason("sUSDS 0x9c56: implied 4.905 % < floor 6.336 % (benchmark 7.336 %)")
    assert "4.905" in en and "4,905" in ru and "floor" not in ru and "implied" not in ru  # RU decimal comma (ADR-537)
    en2, ru2 = PS.localized_reason("levered net 5.631 % < unlevered 5.285 % + 1.0 pp")
    assert "петли" in ru2
    assert PS.localized_reason("something new") == ("something new", "причина записана в журнале книги")
    assert PS.localized_reason(None) == (None, None)


def _obs(tmp, book, at, **data):
    from spa_core.paper_trading import paper_observations as PO
    PO.record(tmp, book, at, {"data": data})


def test_an_old_observation_is_stale_even_when_the_run_is_recent(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW, experiment="aggressive-susde-loop-v1@d0", rows=1)
    _obs(tmp_path, "aggressive", NOW - timedelta(hours=5), morpho_ok=True)
    p = PS.build_all(tmp_path, NOW)["packages"]["aggressive"]
    assert p["data"]["state"] == "STALE" and "5,0" in p["data"]["reason_ru"]


def test_open_loop_is_an_open_decision_with_its_debt_and_last_hf(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW, experiment="aggressive-susde-loop-v1@d0", rows=1,
          extra={"loop": {"status": "open", "last_valuation": {"debt_value": 116696.4, "hf": 1.30714,
                                                              "at": _iso(NOW)}}})
    _obs(tmp_path, "aggressive", NOW, morpho_ok=True)
    p = PS.build_all(tmp_path, NOW)["packages"]["aggressive"]
    assert p["decision"]["state"] == "OPEN"
    assert "$116,696" in p["decision"]["position_en"] and "1,307" in p["decision"]["position_ru"] and "1.307" in p["decision"]["position_en"]
    assert p["data"]["state"] == "HEALTHY" and p["work"]["state"] == "RUNNING"


def test_balanced_without_pt_is_hold_not_open_and_a_bad_pendle_hour_is_degraded(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=1,
          extra={"fixed_carry": {"legs": []}})
    _obs(tmp_path, "balanced", NOW, pendle_ok=False, pendle_reason="price stale")
    p = PS.build_all(tmp_path, NOW)["packages"]["balanced"]
    assert p["decision"]["state"] == "HOLD" and "PT" in p["decision"]["position_en"]
    assert p["data"]["state"] == "DEGRADED" and p["data"]["reason_ru"] == "данные Pendle не подтверждены"


def test_live_admission_is_its_own_field_and_the_refusal_is_named(tmp_path):
    _health(tmp_path)
    pk = PS.build_all(tmp_path, NOW)["packages"]
    assert pk["conservative"]["mode"]["live"] == "NOT_APPROVED"
    for name in ("balanced", "aggressive"):
        assert pk[name]["mode"]["state"] == "PAPER_ONLY" and pk[name]["mode"]["live"] == "REFUSED"
        assert "refused for live" in pk[name]["mode"]["live_reason_en"]


def test_freshness_names_the_window_the_reader_must_apply(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=1)
    f = PS.build_all(tmp_path, NOW)["packages"]["balanced"]["freshness"]
    assert f["expected_every_h"] == 1.0 and f["stale_after_h"] == 2.5
    assert f["stale_at"] == _iso(NOW + timedelta(hours=2.5))


def test_launchd_drift_across_an_hour_is_not_a_missed_run():
    from spa_core.paper_trading import paper_observations as PO
    rows = [{"run_ts": "2026-01-15T05:59:59Z"}, {"run_ts": "2026-01-15T07:00:10Z"},
            {"run_ts": "2026-01-15T09:00:30Z"}]
    assert PO.gaps([{"slot": "2026-01-15T05"}, {"slot": "2026-01-15T07"}]) == ["2026-01-15T06"]
    assert PO.missed_runs(rows) == 1, "05:59→07:00 is one interval; 07:00→09:00 hides one missed run"


def test_observed_drawdown_is_of_the_current_version_only(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW, experiment="aggressive-susde-loop-v1@d0", rows=0)
    st = json.loads((tmp_path / "lp_paper_trading.json").read_text())
    st["daily_history"][0]["equity"] = 0.5          # an earlier-version crash must not leak in
    st["daily_history"] += [{"date": "d0", "equity": 100.0, "experiment_id": "aggressive-susde-loop-v1@d0"},
                            {"date": "d1", "equity": 98.0, "experiment_id": "aggressive-susde-loop-v1@d0"},
                            {"date": "d2", "equity": 99.0, "experiment_id": "aggressive-susde-loop-v1@d0"}]
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps(st))
    assert PS.build_all(tmp_path, NOW)["packages"]["aggressive"]["history"]["observed_drawdown_pct"] == -2.0


def test_public_view_carries_no_local_path_or_process_label(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW - timedelta(hours=9),
          experiment="aggressive-susde-loop-v1@d0", rows=1)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=1)
    v = PS.public_view(PS.build_all(tmp_path, NOW))
    blob = json.dumps(v)
    for leak in ("com.spa.", "data/", ".json", str(tmp_path), "launchd"):
        assert leak not in blob, leak
    assert v["status_colour_is_not_a_risk_grade"] is True
    for name, p in v["packages"].items():
        for dim in ("work", "data", "decision", "history", "mode", "freshness"):
            assert isinstance(p[dim], dict), (name, dim)
        assert p["mechanic_short_ru"] and p["mechanic_short_en"]


def test_open_pt_leg_position_reads_naturally_in_both_languages(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=1,
          extra={"fixed_carry": {"legs": [{"units": 25000.0, "mark": 0.99}]}})
    d = PS.build_all(tmp_path, NOW)["packages"]["balanced"]["decision"]
    assert d["state"] == "OPEN"
    assert d["position_ru"] == "PT в книге: 1, держатся до погашения, $24 750"
    assert d["position_en"] == "1 PT leg(s) held to maturity, $24,750"


def _cons(tmp, *, ks=None, ds=None, flag=False):
    _health(tmp)
    (tmp / "current_positions.json").write_text(json.dumps(
        {"generated_at": _iso(NOW), "positions": {"aave_v3": {}}, "cash_usd": 5000.0, "current_equity_usd": 1.0}))
    if ks is not None:
        (tmp / "kill_switch_status.json").write_text(json.dumps(ks))
    if ds is not None:
        (tmp / "derisk_status.json").write_text(json.dumps(ds))
    if flag:
        (tmp / "kill_switch_active.json").write_text("{}")
    return PS.build_all(tmp, NOW)["packages"]["conservative"]


def test_conservative_hard_kill_is_read_from_the_keys_the_governance_writer_writes(tmp_path):
    # review 02.10: the read model asked for `active`/`tier`, the writer records `triggered`/`state`
    p = _cons(tmp_path, ks={"triggered": True, "state": "TRIGGERED"})
    assert p["work"]["state"] == "PAUSED" and p["decision"]["state"] == "EXIT"
    assert "кэш" in p["decision"]["position_ru"]


def test_conservative_manual_kill_flag_and_soft_derisk(tmp_path):
    assert _cons(tmp_path, ks={"triggered": False, "state": "CLEAR"}, flag=True)["work"]["state"] == "PAUSED"
    (tmp_path / "kill_switch_active.json").unlink()
    soft = _cons(tmp_path, ks={"triggered": False, "state": "CLEAR"}, ds={"active": True, "tier": "SOFT_DERISK"})
    assert soft["work"]["state"] == "RUNNING" and soft["decision"]["state"] == "HOLD"
    assert "SOFT_DERISK" in soft["decision"]["position_en"]


def test_conservative_unmeasured_kill_switch_degrades_data_and_clear_is_healthy(tmp_path):
    assert _cons(tmp_path, ks={"triggered": False, "state": "UNMEASURED"})["data"]["state"] == "DEGRADED"
    clear = _cons(tmp_path, ks={"triggered": False, "state": "CLEAR_PARTIAL"}, ds={"active": False, "tier": "NONE"})
    assert clear["work"]["state"] == "RUNNING" and clear["data"]["state"] == "HEALTHY"
    assert clear["decision"]["state"] == "OPEN"


def test_balanced_book_kill_is_paused(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=2, regime="EXIT")
    assert PS.build_all(tmp_path, NOW)["packages"]["balanced"]["work"]["state"] == "PAUSED"


def test_a_known_decision_defect_is_named_next_to_its_row(tmp_path, monkeypatch):
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=2)
    monkeypatch.setitem(PS.DECISION_DEFECTS, ("balanced", "d1"), ("defect EN", "дефект RU"))
    v = PS.public_view(PS.build_all(tmp_path, NOW))["packages"]["balanced"]["decision"]
    assert v["defect_en"] == "defect EN" and v["defect_ru"] == "дефект RU"


def test_the_sanitiser_replaces_a_leaking_reason(tmp_path):
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW, experiment="aggressive-susde-loop-v1@d0", rows=1)
    st = json.loads((tmp_path / "lp_paper_trading.json").read_text())
    st["daily_history"][-1].update(loop_decision="hold",
                                   loop_reason="cannot read /Users/x/data/lp_paper_trading.json via com.spa.lp_cycle")
    (tmp_path / "lp_paper_trading.json").write_text(json.dumps(st))
    _obs(tmp_path, "aggressive", NOW, morpho_ok=False, missing=["market state: errors ['host: TimeoutError']"])
    blob = json.dumps(PS.public_view(PS.build_all(tmp_path, NOW)))
    for leak in ("/Users/", "com.spa.", ".json", "TimeoutError"):
        assert leak not in blob, leak


def test_missed_runs_counts_a_stopped_process_and_clips_to_the_window():
    from spa_core.paper_trading import paper_observations as PO
    t0 = NOW.replace(tzinfo=None)
    rows = [{"run_ts": (t0 - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")}]
    assert PO.missed_runs(rows, now=t0) == 29, "a stopped process is a growing number, not a measured zero"
    assert PO.missed_runs(rows, now=t0, since=t0 - timedelta(hours=24)) == 24
    rows.append({"run_ts": t0.strftime("%Y-%m-%dT%H:%M:%SZ")})
    assert PO.missed_runs(rows, since=t0 - timedelta(hours=24)) == 24, "a restart is not «29 in 24 h»"


def test_composition_is_measured_from_registry_labels_of_held_positions(tmp_path):
    # «Tier mix: T1 + T2» was printed for every package; measured 02.10 Balanced held susde (T3)
    _health(tmp_path)
    _book(tmp_path, "hy_paper_trading.json", last_run=NOW, experiment="balanced-fixed-carry-v1@d0", rows=1,
          extra={"positions": [{"protocol": "aave_v3"}, {"protocol": "susde"}, {"protocol": "no_such_key"}]})
    c = PS.public_view(PS.build_all(tmp_path, NOW))["packages"]["balanced"]["composition"]
    assert c["state"] == "MEASURED"
    assert c["tiers_held"]["T1"] == ["aave_v3"] and c["tiers_held"]["T3"] == ["susde"]
    assert c["tiers_held"]["unlabelled"] == ["no_such_key"], "an unknown label is never assumed T1"
    assert "без метки" in c["summary_ru"]


def test_code_identity_comes_from_the_sync_receipt_and_says_when_it_is_old(tmp_path):
    _health(tmp_path)
    assert PS.build_all(tmp_path, NOW)["code_identity"]["state"] == "UNMEASURED"
    (tmp_path / "code_sync_status.json").write_text(json.dumps(
        {"timestamp": _iso(NOW - timedelta(minutes=10)), "result": "IN_SYNC", "origin_main": "a" * 40}))
    ci = PS.public_view(PS.build_all(tmp_path, NOW))["code_identity"]
    assert ci["state"] == "IN_SYNC" and ci["origin_commit"] == "a" * 12
    (tmp_path / "code_sync_status.json").write_text(json.dumps(
        {"timestamp": _iso(NOW - timedelta(hours=5)), "result": "IN_SYNC", "origin_main": "a" * 40}))
    assert PS.build_all(tmp_path, NOW)["code_identity"]["state"] == "STALE_RECEIPT"
    (tmp_path / "code_sync_status.json").write_text(json.dumps(
        {"timestamp": _iso(NOW), "result": "SYNCED", "origin_main": "c" * 40}))
    assert PS.build_all(tmp_path, NOW)["code_identity"]["state"] == "IN_SYNC", "a fresh sync is in sync"
    for bad in ("ROLLED_BACK", "CHECKOUT_FAILED", "FETCH_FAILED"):
        (tmp_path / "code_sync_status.json").write_text(json.dumps(
            {"timestamp": _iso(NOW), "result": bad, "origin_main": "b" * 40}))
        assert PS.build_all(tmp_path, NOW)["code_identity"]["state"] == "NOT_IN_SYNC", bad


def test_a_written_status_is_not_proof_of_a_run(tmp_path):
    # negative check (owner 02.10): a fresh generated_at with an old run is not «running»
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW - timedelta(hours=10),
          experiment="aggressive-susde-loop-v1@d0", rows=3)
    full = PS.build_all(tmp_path, NOW)
    assert full["generated_at"] == _iso(NOW)
    assert full["packages"]["aggressive"]["work"]["state"] != "RUNNING"


def test_a_tripped_stop_reaches_the_public_view_and_the_director_alert(tmp_path):
    # the whole chain: book kill → read model → the projection the API and the site serve → Director
    from spa_core.studio_os.director_report import defi_alerts
    _health(tmp_path)
    _book(tmp_path, "lp_paper_trading.json", last_run=NOW, experiment="aggressive-susde-loop-v1@d0", rows=2,
          extra={"il_drawdown_pct": -0.30})
    full = PS.build_all(tmp_path, NOW)
    assert PS.public_view(full)["packages"]["aggressive"]["work"]["state"] == "PAUSED"
    alerts = defi_alerts(full["packages"])
    assert any("aggressive" in a and "пауза" in a for a in alerts), alerts
    assert defi_alerts(None) and "не измерено" in defi_alerts(None)[0].lower()
