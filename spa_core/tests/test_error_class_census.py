"""Батарея §32 ТЗ «Portfolio CIO» — ``spa_core/analytics/error_class_census.py``.

Каждый класс проверяется в обе стороны: сцена, где измеритель ЕСТЬ, и сцена, где его нет
или он неполон, с названным звеном. Литеральных дат нет: отметки носителей строятся от
одного якоря ``_NOW`` и свежесть судится относительно него же (время — вход, не часы).
Носители подаются артефактами сцены, а не живыми файлами.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from typing import Any

from spa_core.analytics import error_class_census as EC
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

ROOT = EC.REPO_ROOT
PROBE = "every_declared_error_class_has_a_measurer"
_NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
_D = [(_NOW.date() + dt.timedelta(days=i)).isoformat() for i in range(6)]


def _iso(hours_ago: float) -> str:
    return (_NOW - dt.timedelta(hours=hours_ago)).isoformat()


def _card(tmp, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


_GOOD_CARD = """\
    ---
    title: x
    ---
    31. Counterfactual tracking
    что-то
    32. Ошибки, которые необходимо измерять
    Минимум:
    False Rebalance

    Missed Opportunity

    <!-- источник: inbox-x.md строки 1-2 -->

    Late Rebalance

    Excessive Turnover

    Risk Violation

    APY Forecast Error

    Break-even Forecast Error


    ⸻


    33. Portfolio KPIs
    """

# ───────────────────────────── сцена каталога данных ─────────────────────────


def _replay(*, fr=None, mo=None, stamp_hours_ago=1.0) -> dict:
    doc = {"generated_at": _iso(stamp_hours_ago), "population": {"horizon_days": 7}}
    doc["false_rebalances"] = fr if fr is not None else {
        "checked": 13, "unchecked": 6, "false": 12, "max_payback_days": 30.0,
        "worst": [{"cycle_date": _D[1], "payback_days": 31.8}, {"cycle_date": _D[2], "payback_days": None}]}
    doc["missed_opportunities"] = mo if mo is not None else {"checked": 7, "missed": 0, "worst": []}
    return doc


def _judge_row(date: str, **over) -> dict:
    r = {"cycle_date": date, "verdict": "HOLD", "reasons": ["payback_too_long:36.3d"],
         "counterfactual": "CHECKED", "outcome": "hit", "missed_usd": 0.0}
    r.update(over)
    return r


def _judge(rows=None) -> dict:
    rows = rows if rows is not None else [
        _judge_row(_D[0], reasons=["move_turnover_over_budget:35%>15%", "payback_too_long:1d"]),
        _judge_row(_D[1], reasons=["week_turnover_over_budget"]),
        _judge_row(_D[2], counterfactual="UNCHECKED", outcome="UNCHECKED", missed_usd=None),
    ]
    return {"params": {"horizon_days": 7}, "per_verdict": rows}


def _forecast(*, scoreable=149, observed=173, sign_n=32, with_unchecked=True, stamp_hours_ago=1.0) -> dict:
    doc = {"generated_at": _iso(stamp_hours_ago),
           "population": {"days_observed": observed, "scoreable": scoreable, "horizon_days": 7},
           "sign_disagreements": [{"cycle_date": _D[0]}] * sign_n,
           "magnitude": {"n": 25}}
    if with_unchecked:
        doc["unchecked"] = []
    return doc


def _limits(*, statuses=("PASS", "PASS", "FAIL", "PASS", "PASS"), with_skip_key=True,
            stamp_hours_ago=1.0) -> dict:
    doc = {"gate": "WARN", "checked_at": _iso(stamp_hours_ago),
           "checks": [{"id": f"DL-0{i + 1}", "status": s} for i, s in enumerate(statuses)]}
    if with_skip_key:
        doc["skip_reasons"] = []
    return doc


def _trigger(*, with_rt04=True) -> dict:
    checks: dict[str, Any] = {"rt01": {"triggered": True}}
    if with_rt04:
        checks["rt04"] = {"triggered": True, "days_since": 60, "threshold_days": 7, "measured": True}
    return {"verdict": "REBALANCE", "checks": checks}


def _records(n=4, with_payback=True) -> list:
    rows = []
    for i in range(n):
        r = {"cycle_date": _D[i % len(_D)], "verdict": "HOLD", "cost_usd": 1.0}
        if with_payback:
            r["payback_days"] = 3.0 + i
        rows.append(r)
    return rows


def _track(n=3, turnover_on=(0,)) -> dict:
    daily = []
    for i in range(n):
        d = {"date": _D[i], "positions": {"a": 50.0}}
        if i in turnover_on:
            d["turnover_usd"] = 100.0
        daily.append(d)
    return {"daily": daily}


def _manifest(slo: dict) -> dict:
    return {"artifacts": [{"path": f"data/{rel}", "slo_hours": h} for rel, h in slo.items()]}


_DEFAULT_SLO = {EC.REPLAY_REL: 9.28, EC.FORECAST_REL: 9.28}


def _scene_dir(tmp, *, replay: Any = "default", judge: Any = "default", forecast: Any = "default",
               limits: Any = "default", blocks: Any = "default", trigger: Any = "default",
               records: Any = "default", track: Any = "default", manifest: Any = "default") -> str:
    root = tmp / "root"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "architecture").mkdir()

    def put(rel, doc):
        if doc is None:
            return
        (data / rel).write_text(json.dumps(doc), encoding="utf-8")

    put(EC.REPLAY_REL, _replay() if replay == "default" else replay)
    put(EC.EVAL_REL, _judge() if judge == "default" else judge)
    put(EC.FORECAST_REL, _forecast() if forecast == "default" else forecast)
    put(EC.LIMITS_REL, _limits() if limits == "default" else limits)
    put(EC.BLOCKS_REL, ([{"date": _D[0], "violations": ["x"]}, {"date": _D[1], "violations": []}]
                        if blocks == "default" else blocks))
    put(EC.TRIGGER_REL, _trigger() if trigger == "default" else trigger)
    put(EC.TRACK_REL, _track() if track == "default" else track)
    recs = _records() if records == "default" else records
    if recs is not None:
        (data / EC.RECORD_REL).write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    man = _manifest(_DEFAULT_SLO) if manifest == "default" else manifest
    if man is not None:
        (root / EC.MANIFEST_REL).write_text(json.dumps(man), encoding="utf-8")
    return str(root)


def _classes(root: str, now=_NOW) -> dict:
    carriers = EC.load_carriers(os.path.join(root, "data"))
    return EC.measure_classes(carriers, EC.load_slo(root), now)


# ───────────────────────────── паритет ───────────────────────────────────────

def test_constants_agree_with_the_real_owner_card():
    p = EC.parity(os.path.join(ROOT, EC.CARD_REL))
    assert p["parsed"]["measured"], p["parsed"].get("reason")
    assert p["agrees"] is True, p["mismatches"]
    assert len(EC.OWNER_CLASSES) == EC.OWNER_CLASSES_DECLARED == 7
    assert p["order_undercount"] == {"classes": 0}


def test_measurers_cover_every_declared_class():
    assert set(EC.MEASURERS) == set(EC.OWNER_CLASSES)


def test_parity_on_a_faithful_scene_card_skips_html_comments(tmp_path):
    p = EC.parity(_card(tmp_path, _GOOD_CARD))
    assert p["agrees"] is True, p["mismatches"]


def test_parity_names_a_missing_class(tmp_path):
    p = EC.parity(_card(tmp_path, _GOOD_CARD.replace("Late Rebalance\n", "")))
    assert p["agrees"] is False
    assert any("классы карточки" in m for m in p["mismatches"])
    assert p["order_undercount"] == {"classes": -1}


def test_parity_names_a_lost_floor_word(tmp_path):
    p = EC.parity(_card(tmp_path, _GOOD_CARD.replace("Минимум:\n", "Перечень:\n")))
    assert p["agrees"] is False
    assert any("Минимум" in m for m in p["mismatches"])


def test_missing_second_border_refuses_to_count(tmp_path):
    parsed = EC.owner_section_from_card(_card(tmp_path, _GOOD_CARD.replace("33. Portfolio KPIs", "")))
    assert parsed["measured"] is False
    assert "вторая граница" in parsed["reason"]


def test_unreadable_card_is_a_third_outcome(tmp_path):
    p = EC.parity(str(tmp_path / "nope.md"))
    assert p["agrees"] is None
    assert "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── False Rebalance ───────────────────────────────

def test_false_rebalance_on_the_live_shaped_replay_is_measured(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["False Rebalance"]
    assert r["kind"] == "measured"
    assert (r["population"], r["errors"]) == (13, 12)
    assert r["carriers"][0]["third_outcome_present"] is True


def test_false_rebalance_without_unchecked_key_lacks_the_third_outcome(tmp_path):
    fr = {"checked": 13, "false": 12, "max_payback_days": 30.0, "worst": []}
    r = _classes(_scene_dir(tmp_path, replay=_replay(fr=fr)))["classes"]["False Rebalance"]
    assert r["kind"] == "measured_without_third_outcome"


def test_false_rebalance_when_the_replay_refused_is_unmeasured(tmp_path):
    fr = {"verdict": "UNCHECKED", "reason": "горизонт окупаемости не прочитан"}
    r = _classes(_scene_dir(tmp_path, replay=_replay(fr=fr)))["classes"]["False Rebalance"]
    assert r["kind"] == UNMEASURED
    assert "сам отказал" in r["reason"]


def test_false_rebalance_without_replay_is_unmeasured_not_absent(tmp_path):
    r = _classes(_scene_dir(tmp_path, replay=None))["classes"]["False Rebalance"]
    assert r["kind"] == UNMEASURED
    assert EC.REPLAY_REL in r["reason"]


# ───────────────────────────── Missed Opportunity ────────────────────────────

def test_missed_opportunity_judge_rows_carry_population_and_unchecked(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["Missed Opportunity"]
    assert r["kind"] == "measured"
    judge = next(c for c in r["carriers"] if c["carrier"].startswith(EC.EVAL_REL))
    assert (judge["population"], judge["unchecked"]) == (2, 1)


def test_missed_opportunity_replay_block_alone_lacks_the_third_outcome(tmp_path):
    root = _scene_dir(tmp_path, judge=None)
    r = _classes(root)["classes"]["Missed Opportunity"]
    assert r["kind"] == "measured_without_third_outcome"
    assert len(r["carriers"]) == 1


def test_missed_opportunity_without_both_carriers_is_unmeasured(tmp_path):
    r = _classes(_scene_dir(tmp_path, judge=None, replay=None))["classes"]["Missed Opportunity"]
    assert r["kind"] == UNMEASURED


# ───────────────────────────── Late Rebalance ────────────────────────────────

def test_late_rebalance_with_rt04_is_a_signal_at_t0_only(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["Late Rebalance"]
    assert r["kind"] == "signal_at_t0_only"
    assert r["carriers"][0]["days_since"] == 60


def test_late_rebalance_without_rt04_is_absent(tmp_path):
    r = _classes(_scene_dir(tmp_path, trigger=_trigger(with_rt04=False)))["classes"]["Late Rebalance"]
    assert r["kind"] == "absent"


def test_late_rebalance_without_trigger_artifact_is_unmeasured(tmp_path):
    r = _classes(_scene_dir(tmp_path, trigger=None))["classes"]["Late Rebalance"]
    assert r["kind"] == UNMEASURED


# ───────────────────────────── Excessive Turnover ────────────────────────────

def test_excessive_turnover_counts_refusal_reasons_and_track_rows(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["Excessive Turnover"]
    assert r["kind"] == "signal_at_t0_only"
    judge = next(c for c in r["carriers"] if c["role"] == "signal_at_t0")
    assert judge["rows_with_turnover_refusal"] == 2
    assert judge["by_prefix"]["move_turnover_over_budget"] == 1
    track = next(c for c in r["carriers"] if c["role"] == "raw_observation")
    assert (track["rows_with_turnover"], track["rows_without_turnover"]) == (1, 2)
    assert track["compared_to_budget_by"] is None


def test_excessive_turnover_reason_prefix_is_split_on_the_colon(tmp_path):
    judge = _judge([_judge_row(_D[0], reasons=["day_turnover_over_budget:55%>15%"])])
    r = _classes(_scene_dir(tmp_path, judge=judge))["classes"]["Excessive Turnover"]
    assert r["carriers"][0]["rows_with_turnover_refusal"] == 1


def test_excessive_turnover_without_judge_and_track_is_unmeasured(tmp_path):
    r = _classes(_scene_dir(tmp_path, judge=None, track=None))["classes"]["Excessive Turnover"]
    assert r["kind"] == UNMEASURED


# ───────────────────────────── Risk Violation ────────────────────────────────

def test_risk_violation_limits_snapshot_is_measured_and_names_the_failing_check(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["Risk Violation"]
    assert r["kind"] == "measured"
    assert (r["population"], r["errors"]) == (5, 1)
    assert r["failing_today"] == ["DL-03"]


def test_risk_violation_limits_without_skip_key_lack_the_third_outcome(tmp_path):
    lim = _limits(with_skip_key=False)
    r = _classes(_scene_dir(tmp_path, limits=lim, blocks=None))["classes"]["Risk Violation"]
    assert r["kind"] == "measured_without_third_outcome"


def test_risk_violation_status_skip_is_a_third_outcome_even_without_the_key(tmp_path):
    lim = _limits(statuses=("PASS", "SKIP"), with_skip_key=False)
    r = _classes(_scene_dir(tmp_path, limits=lim, blocks=None))["classes"]["Risk Violation"]
    assert r["kind"] == "measured"
    assert r["carriers"][0]["unchecked"] == 1


def test_risk_violation_blocks_history_alone_lacks_the_third_outcome(tmp_path):
    r = _classes(_scene_dir(tmp_path, limits=None))["classes"]["Risk Violation"]
    assert r["kind"] == "measured_without_third_outcome"
    assert r["carriers"][0]["shape"] == "history"


def test_risk_violation_without_carriers_is_unmeasured(tmp_path):
    r = _classes(_scene_dir(tmp_path, limits=None, blocks=None))["classes"]["Risk Violation"]
    assert r["kind"] == UNMEASURED


# ───────────────────────────── APY Forecast Error ────────────────────────────

def test_apy_forecast_error_is_measured_with_unscoreable_days_as_third_outcome(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["APY Forecast Error"]
    assert r["kind"] == "measured"
    assert (r["population"], r["errors"]) == (149, 32)
    assert r["carriers"][0]["unchecked"] == 173 - 149


def test_apy_forecast_error_without_unchecked_key_lacks_the_third_outcome(tmp_path):
    fc = _forecast(with_unchecked=False)
    r = _classes(_scene_dir(tmp_path, forecast=fc))["classes"]["APY Forecast Error"]
    assert r["kind"] == "measured_without_third_outcome"


def test_apy_forecast_error_without_population_is_unmeasured(tmp_path):
    fc = {"generated_at": _iso(1.0), "findings": []}
    r = _classes(_scene_dir(tmp_path, forecast=fc))["classes"]["APY Forecast Error"]
    assert r["kind"] == UNMEASURED


# ───────────────────────────── Break-even Forecast Error ─────────────────────

def test_break_even_forecast_and_fact_in_different_carriers_is_uncompared(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["Break-even Forecast Error"]
    assert r["kind"] == "forecast_and_fact_uncompared"
    roles = {c["role"] for c in r["carriers"]}
    assert roles == {"forecast", "fact"}
    assert "разность не считает никто" in r["reason"]


def test_break_even_forecast_without_any_realised_payback_is_forecast_without_fact(tmp_path):
    fr = {"checked": 13, "unchecked": 6, "false": 12, "max_payback_days": 30.0,
          "worst": [{"cycle_date": _D[1], "payback_days": None}]}
    r = _classes(_scene_dir(tmp_path, replay=_replay(fr=fr)))["classes"]["Break-even Forecast Error"]
    assert r["kind"] == "forecast_without_fact"


def test_break_even_without_forecast_in_records_is_absent(tmp_path):
    fr = {"checked": 13, "unchecked": 6, "false": 12, "max_payback_days": 30.0, "worst": []}
    root = _scene_dir(tmp_path, records=_records(with_payback=False), replay=_replay(fr=fr))
    r = _classes(root)["classes"]["Break-even Forecast Error"]
    assert r["kind"] == "absent"


def test_break_even_without_records_and_replay_is_unmeasured(tmp_path):
    r = _classes(_scene_dir(tmp_path, records=None, replay=None))["classes"]["Break-even Forecast Error"]
    assert r["kind"] == UNMEASURED


# ───────────────────────────── свежесть ──────────────────────────────────────

def test_freshness_is_judged_against_the_manifest_slo_and_the_injected_now(tmp_path):
    root = _scene_dir(tmp_path, replay=_replay(stamp_hours_ago=183.7))
    r = _classes(root)["classes"]["False Rebalance"]
    assert r["freshness"]["fresh"] is False
    assert r["freshness"]["slo_hours"] == 9.28
    assert 183.0 < r["freshness"]["age_hours"] < 184.5


def test_fresh_carrier_within_slo_is_fresh(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["False Rebalance"]
    assert r["freshness"]["fresh"] is True


def test_carrier_without_manifest_slo_has_unmeasured_freshness_not_fresh(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["Risk Violation"]
    assert r["freshness"]["fresh"] is None
    assert "SLO" in r["freshness"]["reason"]


def test_carrier_without_a_stamp_has_unmeasured_freshness(tmp_path):
    rp = _replay()
    del rp["generated_at"]
    r = _classes(_scene_dir(tmp_path, replay=rp))["classes"]["False Rebalance"]
    assert r["freshness"]["fresh"] is None
    assert "отметка" in r["freshness"]["reason"]


def test_now_is_an_input_moving_now_moves_the_verdict(tmp_path):
    root = _scene_dir(tmp_path)
    later = _NOW + dt.timedelta(hours=20)
    assert _classes(root)["classes"]["False Rebalance"]["freshness"]["fresh"] is True
    assert _classes(root, now=later)["classes"]["False Rebalance"]["freshness"]["fresh"] is False


def test_signal_only_class_has_no_freshness_row(tmp_path):
    r = _classes(_scene_dir(tmp_path))["classes"]["Late Rebalance"]
    assert r["freshness"] is None


# ───────────────────────────── прогон ────────────────────────────────────────

def test_run_on_the_live_shaped_scene_is_critical_and_names_the_unmeasured_classes(tmp_path):
    root = _scene_dir(tmp_path)
    doc = EC.run(root=root, card_path=_card(tmp_path, _GOOD_CARD), write=False, now=_NOW)
    assert doc["overall"] == "CRITICAL"
    assert doc["classes"]["measured"] == 4
    codes = {f["code"] for f in doc["findings"]}
    assert "error_classes_declared_vs_measured" in codes
    assert "error_class_forecast_and_fact_uncompared:Break-even Forecast Error" in codes
    assert "error_class_signal_at_t0_only:Late Rebalance" in codes
    assert "error_class_signal_at_t0_only:Excessive Turnover" in codes
    assert "risk_limit_failing_today" in codes
    summary = next(f for f in doc["findings"] if f["code"] == "error_classes_declared_vs_measured")
    assert "Минимум" in summary["message"] and "Late Rebalance" in summary["message"]
    assert any("Risk Violation" in u for u in doc["unmeasured"])


def test_run_stale_measurer_is_a_warn_not_a_missing_class(tmp_path):
    root = _scene_dir(tmp_path, replay=_replay(stamp_hours_ago=183.7))
    doc = EC.run(root=root, card_path=_card(tmp_path, _GOOD_CARD), write=False, now=_NOW)
    codes = {f["code"] for f in doc["findings"]}
    assert "measurer_stale:False Rebalance" in codes
    assert doc["classes"]["classes"]["False Rebalance"]["kind"] == "measured"


def test_run_unreadable_card_and_carriers_are_named_unmeasured(tmp_path):
    root = _scene_dir(tmp_path, replay=None, judge=None, forecast=None, limits=None,
                      blocks=None, trigger=None, records=None, track=None)
    doc = EC.run(root=root, card_path=str(tmp_path / "nope.md"), write=False, now=_NOW)
    assert doc["counts"]["unmeasured"] >= 8
    assert doc["overall"] == "UNCHECKED"
    assert doc["classes"]["measured"] == 0


def test_run_write_true_calls_atomic_save_with_data_then_path(tmp_path, monkeypatch):
    import spa_core.utils.atomic as atomic
    calls = []
    monkeypatch.setattr(atomic, "atomic_save", lambda data, path: calls.append((data, path)))
    root = _scene_dir(tmp_path)
    EC.run(root=root, card_path=_card(tmp_path, _GOOD_CARD), write=True, now=_NOW)
    assert len(calls) == 1
    assert isinstance(calls[0][0], dict) and calls[0][1].endswith(EC.REPORT_REL)


def test_main_on_the_scene_returns_1_and_prints_the_verdict(tmp_path, capsys):
    root = _scene_dir(tmp_path)
    rc = EC.main(["--root", root, "--card", _card(tmp_path, _GOOD_CARD), "--no-write",
                  "--now", _NOW.isoformat()])
    out = capsys.readouterr().out
    assert rc == 1
    assert "§32" in out and "измеряется 4" in out and "Break-even Forecast Error" in out


def test_main_empty_now_is_unmeasured_code_2(tmp_path, capsys):
    rc = EC.main(["--root", str(tmp_path), "--no-write", "--now", ""])
    assert rc == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


# ───────────────────────────── проба приёмки ─────────────────────────────────

def test_probe_is_registered_with_data_dir_as_input():
    assert PROBE in CA.PROBES
    assert "data_dir" in CA.probe_tree_inputs(PROBE)


def test_probe_on_the_scene_is_not_satisfied_and_names_the_classes(tmp_path):
    root = _scene_dir(tmp_path)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.NOT_SATISFIED
    assert "Late Rebalance" in why and "Break-even Forecast Error" in why


def test_probe_satisfied_only_when_every_class_is_measured(tmp_path, monkeypatch):
    root = _scene_dir(tmp_path)
    real = EC.measure_classes

    def all_measured(carriers, slo, now):
        doc = real(carriers, slo, now)
        for r in doc["classes"].values():
            r["kind"] = "measured"
        doc["measured"] = len(doc["classes"])
        return doc

    monkeypatch.setattr(EC, "measure_classes", all_measured)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.SATISFIED, why


def test_probe_unmeasured_class_is_unmeasured_not_a_verdict(tmp_path):
    root = _scene_dir(tmp_path, trigger=None)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED
    assert "Late Rebalance" in why


def test_probe_without_any_carrier_is_unmeasured(tmp_path):
    root = _scene_dir(tmp_path, replay=None, judge=None, forecast=None, limits=None)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED
    assert "НЕ ИЗМЕРЕНО" in why


def test_probe_refuses_an_argument():
    verdict, why = CA.run_probe(f"{PROBE}:foo")
    assert verdict == UNMEASURED
    assert "аргумент" in why


def test_probe_is_not_a_substring_check(tmp_path):
    """Файл с нужными словами, но без структуры носителя — не измеритель."""
    root = _scene_dir(tmp_path, replay={"generated_at": _iso(1.0),
                                        "note": "false_rebalances missed_opportunities measured"},
                      judge=None, forecast=None, limits=None, blocks=None)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED
