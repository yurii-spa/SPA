"""Батарея §31 ТЗ «Portfolio CIO» — ``spa_core/analytics/counterfactual_tracking_census.py``.

Каждая ось проверяется в обе стороны: сцена, где находка ЕСТЬ, и сцена, где её нет, с
названным звеном. Литеральных дат нет: даты сцены строятся от одного якоря (``_D``) и
сравниваются как строки; шаг наблюдения выводится из дат трека; судья и реплей подаются
артефактами сцены, а не живыми файлами.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap

from spa_core.analytics import counterfactual_tracking_census as CT
from spa_core.analytics import shadow_mode_census as SM
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

ROOT = CT.REPO_ROOT
PROBE = "counterfactual_tracks_every_declared_horizon"


def _card(tmp, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


_GOOD_CARD = """\
    ---
    title: x
    ---
    30. Shadow Mode — обязательный этап
    что-то
    31. Counterfactual tracking
    Для каждой неисполненной shadow recommendation отслеживать:
    Что было бы, если бы мы ее выполнили?
    Например:
    T0:
    Move $15k Aave → Morpho

    Expected break-even:
    1.8 days

    Expected holding:
    14 days
    После:
    1h
    6h
    24h
    3d
    7d
    пересчитывать:
    actual opportunity APY
    actual theoretical gain

    <!-- источник: inbox-actual-costs.md строки 12-339 -->

    actual costs
    whether recommendation was good


    ⸻


    32. Ошибки, которые необходимо измерять
    Минимум:
    """

# ───────────────────────────── сцена каталога данных ─────────────────────────

_BASE = dt.datetime.now(dt.timezone.utc).date()
_D = [(_BASE + dt.timedelta(days=i)).isoformat() for i in range(9)]


def _rec(date: str, verdict: str = "HOLD", **over) -> dict:
    r = {"schema": "shadow-hist-v2", "cycle_date": date, "verdict": verdict,
         "generated_at": f"{date}T07:00:00+00:00", "reasons": ["scene"], "legs": [],
         "target_positions": {"a": 60.0}, "current_positions": {"a": 40.0, "b": 60.0},
         "gain_pp": 0.1, "cost_usd": 1.0, "payback_days": 3.0}
    r.update(over)
    return r


def _day(date: str, turnover=0.0) -> dict:
    d = {"date": date, "positions": {"a": 40.0, "b": 60.0}}
    if turnover is not None:
        d["turnover_usd"] = turnover
    return d


def _judge_row(date: str, **over) -> dict:
    r = {"cycle_date": date, "verdict": "HOLD", "outcome": "hit", "counterfactual": "CHECKED",
         "benefit_usd_over_checked_days": -1.0, "cost_usd_used": 1.0, "cost_source": "recorded",
         "net_usd": -2.0}
    r.update(over)
    return r


def _judge_doc(rows, horizon_days=7) -> dict:
    return {"ready_to_arm": False, "status": "NOT_READY", "observation_days": len(rows),
            "criteria": [], "counts": {"act": 0}, "arming_blockade": {"verdict": "X"},
            "params": {"horizon_days": horizon_days}, "per_verdict": list(rows)}


def _replay_doc(horizon_days=7) -> dict:
    return {"population": {"horizon_days": horizon_days},
            "comparison": {"observed": {"net_apy_pct": {"current": 0.3, "cio_hold": 5.4},
                                        "gross_apy_pct": {"current": 5.3},
                                        "opt_minus_current_pp": 0.4}},
            "columns": {"observed": {"arms": {}}},
            "false_rebalances": {"checked": 1}, "missed_opportunities": {"checked": 1}}


def _scene_dir(tmp, *, records, days, trades=(), judge=None, replay=None, books=None,
               drop=()) -> str:
    base = tmp / "data"
    base.mkdir(exist_ok=True)
    if "records" not in drop:
        (base / SM.RECORD_REL).write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    if "daily" not in drop:
        (base / SM.TRACK_REL).write_text(json.dumps({"daily": list(days)}), encoding="utf-8")
    if "trades" not in drop:
        (base / SM.TRADES_REL).write_text(json.dumps(list(trades)), encoding="utf-8")
    if "eval" not in drop:
        doc = judge if judge is not None else _judge_doc([_judge_row(r["cycle_date"]) for r in records])
        (base / SM.EVAL_REL).write_text(json.dumps(doc), encoding="utf-8")
    if "replay" not in drop:
        (base / CT.REPLAY_REL).write_text(json.dumps(replay or _replay_doc()), encoding="utf-8")
    for book, rel in CT.RECORD_BOOKS.items():
        if book == "conservative" or f"book:{book}" in drop:
            continue
        rows = (books or {}).get(book, [_rec(_D[0])])
        (base / rel).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return str(base)


def _plain(tmp, **kw) -> str:
    """Сцена без расхождений: три дня, система держит, CIO HOLD."""
    recs = [_rec(_D[i]) for i in range(3)]
    days = [_day(_D[i]) for i in range(3)]
    return _scene_dir(tmp, records=recs, days=days, **kw)


# ───────────────────────────── паритет ────────────────────────────────────────

def test_constants_agree_with_the_real_owner_card():
    p = CT.parity(os.path.join(ROOT, CT.CARD_REL))
    assert p["agrees"] is True, p
    assert len(CT.OWNER_HORIZONS) == CT.OWNER_HORIZONS_DECLARED == 5
    assert len(CT.OWNER_QUANTITIES) == CT.OWNER_QUANTITIES_DECLARED == 4
    assert p["order_undercount"] == {"horizons": 0, "quantities": 0}
    assert CT.ORDER_G964_NAMED["tail_read"] is True


def test_horizon_hours_cover_every_declared_horizon():
    assert set(CT.HORIZON_HOURS) == set(CT.OWNER_HORIZONS)
    assert [CT.HORIZON_HOURS[h] for h in CT.OWNER_HORIZONS] == [1, 6, 24, 72, 168]


def test_parity_on_a_faithful_scene_card_skips_html_comments(tmp_path):
    p = CT.parity(_card(tmp_path, _GOOD_CARD))
    assert p["agrees"] is True and p["mismatches"] == [], p


def test_parity_names_a_missing_horizon(tmp_path):
    p = CT.parity(_card(tmp_path, _GOOD_CARD.replace("    6h\n", "")))
    assert p["agrees"] is False
    assert any("горизонты карточки" in m for m in p["mismatches"])


def test_parity_names_a_missing_quantity(tmp_path):
    p = CT.parity(_card(tmp_path, _GOOD_CARD.replace("    actual costs\n", "")))
    assert p["agrees"] is False
    assert any("величины карточки" in m for m in p["mismatches"])


def test_parity_names_a_lost_example(tmp_path):
    p = CT.parity(_card(tmp_path, _GOOD_CARD.replace("1.8 days", "1.9 days")))
    assert p["agrees"] is False
    assert any("пример владельца" in m for m in p["mismatches"])


def test_missing_second_border_refuses_to_count(tmp_path):
    p = CT.parity(_card(tmp_path, _GOOD_CARD.replace(
        "32. Ошибки, которые необходимо измерять", "32. Что-то другое")))
    assert p["agrees"] is None
    assert "вторая граница" in p["parsed"]["reason"]


def test_unreadable_card_is_a_third_outcome(tmp_path):
    p = CT.parity(str(tmp_path / "nope.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── (A) предмет ───────────────────────────────────

def test_axis_a_unfollowed_hold_is_a_subject_with_a_judge_row(tmp_path):
    recs = [_rec(_D[i]) for i in range(3)]
    days = [_day(_D[0]), _day(_D[1], turnover=5000.0), _day(_D[2])]
    c = CT.load_carriers(_scene_dir(tmp_path, records=recs, days=days))
    s = CT.measure_subject(c, armed_at=None)
    assert s["measured"] and s["subject_exists"]
    assert s["tally"] == {"unexecuted_act": 0, "unfollowed_hold": 1}
    assert s["subjects"][0]["date"] == _D[1] and s["subjects"][0]["judge"] == "tracked"
    assert s["acts_by_book"] == {"conservative": 0, "balanced": 0, "aggressive": 0}


def test_axis_a_unexecuted_act_is_the_other_kind(tmp_path):
    recs = [_rec(_D[0]), _rec(_D[1], verdict="ACT"), _rec(_D[2])]
    days = [_day(_D[i]) for i in range(3)]
    c = CT.load_carriers(_scene_dir(tmp_path, records=recs, days=days))
    s = CT.measure_subject(c, armed_at=None)
    assert s["tally"] == {"unexecuted_act": 1, "unfollowed_hold": 0}


def test_axis_a_without_divergence_there_is_no_subject(tmp_path):
    c = CT.load_carriers(_plain(tmp_path))
    s = CT.measure_subject(c, armed_at=None)
    assert s["measured"] and not s["subject_exists"] and s["subjects"] == []


def test_axis_a_after_arming_zero_divergence_is_named_impossible(tmp_path):
    c = CT.load_carriers(_plain(tmp_path))
    s = CT.measure_subject(c, armed_at=_D[0])
    assert s["subject_impossible_after_arming"] is True
    s2 = CT.measure_subject(c, armed_at=None)
    assert s2["subject_impossible_after_arming"] is False


def test_axis_a_subject_without_a_judge_row_is_untracked(tmp_path):
    recs = [_rec(_D[i]) for i in range(3)]
    days = [_day(_D[0]), _day(_D[1], turnover=5000.0), _day(_D[2])]
    judge = _judge_doc([_judge_row(_D[0]), _judge_row(_D[2])])
    c = CT.load_carriers(_scene_dir(tmp_path, records=recs, days=days, judge=judge))
    s = CT.measure_subject(c, armed_at=None)
    assert s["subjects"][0]["judge"] == "untracked"


def test_axis_a_unreadable_book_is_unmeasured_not_zero(tmp_path):
    c = CT.load_carriers(_plain(tmp_path, drop=("book:aggressive",)))
    s = CT.measure_subject(c, armed_at=None)
    assert s["acts_by_book"]["aggressive"] is None
    assert s["acts_unmeasured_books"] == ["aggressive"]


def test_axis_a_without_records_is_unmeasured(tmp_path):
    c = CT.load_carriers(_plain(tmp_path, drop=("records",)))
    s = CT.measure_subject(c, armed_at=None)
    assert s["measured"] is False and "пары §30" in s["reason"]


# ───────────────────────────── (B) горизонты ─────────────────────────────────

def test_axis_b_daily_cadence_makes_1h_6h_unreachable_and_7d_tracked(tmp_path):
    c = CT.load_carriers(_plain(tmp_path))
    h = CT.measure_horizons(c)
    kinds = {k: v["kind"] for k, v in h["horizons"].items()}
    assert h["cadence_hours"] == 24.0
    assert kinds == {"1h": "unreachable_by_cadence", "6h": "unreachable_by_cadence",
                     "24h": "reachable_untracked", "3d": "reachable_untracked", "7d": "tracked"}
    assert sorted(h["horizons"]["7d"]["carriers"]) == ["judge", "replay"]
    assert h["tally"]["tracked"] == 1


def test_axis_b_judge_horizon_in_hours_is_read_from_params(tmp_path):
    judge = _judge_doc([_judge_row(_D[0])], horizon_days=3)
    c = CT.load_carriers(_plain(tmp_path, judge=judge, replay=_replay_doc(horizon_days=1)))
    h = CT.measure_horizons(c)
    kinds = {k: v["kind"] for k, v in h["horizons"].items()}
    assert kinds["3d"] == "tracked" and h["horizons"]["3d"]["carriers"] == ["judge"]
    assert kinds["24h"] == "tracked" and h["horizons"]["24h"]["carriers"] == ["replay"]
    assert kinds["7d"] == "reachable_untracked"


def test_axis_b_hourly_track_makes_short_horizons_reachable(tmp_path):
    # Шаг наблюдения выводится из дат трека: сутки → 24 ч. Трек с ОДНОЙ датой шаг не задаёт.
    recs = [_rec(_D[0])]
    c = CT.load_carriers(_scene_dir(tmp_path, records=recs, days=[_day(_D[0])]))
    h = CT.measure_horizons(c)
    assert h["cadence_hours"] is None
    assert all(v["kind"] in ("tracked", UNMEASURED) for v in h["horizons"].values())
    assert h["horizons"]["1h"]["kind"] == UNMEASURED and "шаг наблюдения" in h["horizons"]["1h"]["reason"]


def test_axis_b_without_judge_and_replay_horizons_are_named_unmeasured_or_untracked(tmp_path):
    c = CT.load_carriers(_plain(tmp_path, drop=("eval", "replay")))
    h = CT.measure_horizons(c)
    assert h["carriers"]["judge"]["hours"] is None and h["carriers"]["replay"]["hours"] is None
    assert h["horizons"]["7d"]["kind"] == "reachable_untracked"
    assert h["tally"]["tracked"] == 0


# ───────────────────────────── (C) величины ──────────────────────────────────

def test_axis_c_live_shape_two_per_recommendation_one_aggregate_one_estimate(tmp_path):
    c = CT.load_carriers(_plain(tmp_path))
    q = CT.measure_quantities(c)
    kinds = {k: v["kind"] for k, v in q["quantities"].items()}
    assert kinds == {"actual opportunity APY": "aggregate_only",
                     "actual theoretical gain": "per_recommendation",
                     "actual costs": "estimate_reused",
                     "whether recommendation was good": "per_recommendation"}
    assert q["quantities"]["actual costs"]["judge_sources"] == {"recorded": 3}


def test_axis_c_observed_cost_source_is_per_recommendation(tmp_path):
    rows = [_judge_row(_D[i], cost_source="observed") for i in range(3)]
    c = CT.load_carriers(_plain(tmp_path, judge=_judge_doc(rows)))
    q = CT.measure_quantities(c)
    assert q["quantities"]["actual costs"]["kind"] == "per_recommendation"


def test_axis_c_mixed_cost_sources_are_still_an_estimate(tmp_path):
    rows = [_judge_row(_D[0], cost_source="observed"), _judge_row(_D[1]), _judge_row(_D[2])]
    c = CT.load_carriers(_plain(tmp_path, judge=_judge_doc(rows)))
    q = CT.measure_quantities(c)
    assert q["quantities"]["actual costs"]["kind"] == "estimate_reused"


def test_axis_c_opportunity_apy_on_the_judge_row_is_per_recommendation(tmp_path):
    rows = [_judge_row(_D[i], opportunity_apy_pct=4.2) for i in range(3)]
    c = CT.load_carriers(_plain(tmp_path, judge=_judge_doc(rows)))
    q = CT.measure_quantities(c)
    assert q["quantities"]["actual opportunity APY"]["kind"] == "per_recommendation"


def test_axis_c_unchecked_outcomes_are_not_a_verdict(tmp_path):
    rows = [_judge_row(_D[i], outcome="UNCHECKED") for i in range(3)]
    c = CT.load_carriers(_plain(tmp_path, judge=_judge_doc(rows)))
    q = CT.measure_quantities(c)
    r = q["quantities"]["whether recommendation was good"]
    assert r["kind"] == "aggregate_only" and r["judge_rows_scored"] == 0


def test_axis_c_absent_everywhere_is_its_own_kind(tmp_path):
    rows = [_judge_row(_D[i], outcome="UNCHECKED") for i in range(3)]
    replay = _replay_doc()
    del replay["false_rebalances"], replay["missed_opportunities"]
    c = CT.load_carriers(_plain(tmp_path, judge=_judge_doc(rows), replay=replay))
    q = CT.measure_quantities(c)
    assert q["quantities"]["whether recommendation was good"]["kind"] == "absent"


def test_axis_c_without_judge_is_unmeasured_not_absent(tmp_path):
    c = CT.load_carriers(_plain(tmp_path, drop=("eval",)))
    q = CT.measure_quantities(c)
    assert all(v["kind"] == UNMEASURED for v in q["quantities"].values())
    assert q["tally"]["unmeasured"] == 4


# ───────────────────────────── (D) связь ─────────────────────────────────────

def test_axis_d_two_records_on_one_date_make_the_date_link_ambiguous(tmp_path):
    recs = [_rec(_D[0]), _rec(_D[0], generated_at=f"{_D[0]}T08:00:00+00:00"), _rec(_D[1])]
    c = CT.load_carriers(_scene_dir(tmp_path, records=recs, days=[_day(_D[0]), _day(_D[1])]))
    l = CT.measure_linkage(c)
    assert l["kind"] == "by_date_ambiguous" and l["ambiguous_dates"] == [_D[0]]


def test_axis_d_one_record_per_date_is_a_plain_date_link(tmp_path):
    c = CT.load_carriers(_plain(tmp_path))
    assert CT.measure_linkage(c)["kind"] == "by_date"


def test_axis_d_decision_id_on_every_judge_row_is_the_strong_link(tmp_path):
    recs = [_rec(_D[0]), _rec(_D[0]), _rec(_D[1])]
    rows = [_judge_row(_D[0], decision_id="x"), _judge_row(_D[0], decision_id="y"),
            _judge_row(_D[1], decision_id="z")]
    c = CT.load_carriers(_scene_dir(tmp_path, records=recs, days=[_day(_D[0]), _day(_D[1])],
                                    judge=_judge_doc(rows)))
    assert CT.measure_linkage(c)["kind"] == "by_decision_id"


def test_axis_d_without_judge_is_unmeasured(tmp_path):
    c = CT.load_carriers(_plain(tmp_path, drop=("eval",)))
    assert CT.measure_linkage(c)["kind"] == UNMEASURED


# ───────────────────────────── run / main ────────────────────────────────────

def test_run_on_the_live_shaped_scene_is_critical_and_names_the_horizons(tmp_path):
    d = _plain(tmp_path)
    doc = CT.run(root=str(tmp_path), data_dir=d, card_path=_card(tmp_path, _GOOD_CARD), write=False)
    codes = {f["code"]: f["severity"] for f in doc["findings"]}
    assert doc["overall"] == "CRITICAL"
    assert codes["horizons_declared_vs_tracked"] == "CRITICAL"
    assert codes["quantity_not_recomputed:actual costs"] == "CRITICAL"
    assert codes["quantity_aggregate_only:actual opportunity APY"] == "WARN"
    assert codes["no_unexecuted_recommendation"] == "WARN"
    assert doc["unmeasured"] == []
    assert doc["applied"] is False


def test_run_with_every_horizon_tracked_and_actual_costs_is_not_critical(tmp_path):
    # Носители на всех пяти горизонтах нельзя собрать из двух артефактов (у каждого один
    # горизонт) — поэтому CRITICAL по горизонтам неустраним сценой из двух носителей;
    # но стоимость и величины — устранимы, и это проверяется отдельно.
    rows = [_judge_row(_D[i], cost_source="observed", opportunity_apy_pct=4.0) for i in range(3)]
    d = _plain(tmp_path, judge=_judge_doc(rows))
    doc = CT.run(root=str(tmp_path), data_dir=d, card_path=_card(tmp_path, _GOOD_CARD), write=False)
    codes = {f["code"] for f in doc["findings"]}
    assert "quantity_not_recomputed:actual costs" not in codes
    assert "quantity_aggregate_only:actual opportunity APY" not in codes
    assert "horizons_declared_vs_tracked" in codes


def test_run_unreadable_card_and_judge_are_named_unmeasured(tmp_path):
    d = _plain(tmp_path, drop=("eval",))
    doc = CT.run(root=str(tmp_path), data_dir=d, card_path=str(tmp_path / "nope.md"), write=False)
    assert any("паритет" in u for u in doc["unmeasured"])
    assert any("ось C" in u for u in doc["unmeasured"])
    assert any("ось D" in u for u in doc["unmeasured"])


def test_run_write_true_calls_atomic_save_with_data_then_path(tmp_path, monkeypatch):
    calls = []
    import spa_core.utils.atomic as atomic
    monkeypatch.setattr(atomic, "atomic_save", lambda data, path: calls.append((data, path)))
    d = _plain(tmp_path)
    CT.run(root=str(tmp_path), data_dir=d, card_path=_card(tmp_path, _GOOD_CARD), write=True)
    assert len(calls) == 1
    data, path = calls[0]
    assert isinstance(data, dict) and data["schema"] == "counterfactual_tracking_census/v1"
    assert str(path).endswith(CT.REPORT_REL)


def test_main_on_the_scene_returns_1_and_prints_the_verdict(tmp_path, capsys):
    d = _plain(tmp_path)
    rc = CT.main(["--root", str(tmp_path), "--data-dir", d, "--card", _card(tmp_path, _GOOD_CARD),
                  "--no-write"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "§31" in out and "CRITICAL" in out and "horizons_declared_vs_tracked" in out


def test_parse_now_is_an_input_and_refuses_garbage():
    assert CT.parse_now(None) == (None, None)
    assert CT.parse_now("")[1] is not None
    assert CT.parse_now("not-a-date")[1] is not None
    ts, why = CT.parse_now(f"{_D[0]}T00:00:00Z")
    assert why is None and ts.tzinfo is not None


def test_main_empty_now_is_unmeasured_code_2(tmp_path, capsys):
    rc = CT.main(["--now", "", "--no-write", "--root", str(tmp_path)])
    assert rc == 2 and "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


# ───────────────────────────── проба приёмки ─────────────────────────────────

def test_probe_is_registered():
    assert PROBE in CA.PROBES


def test_probe_on_the_scene_is_not_satisfied_and_names_the_horizons(tmp_path):
    d = _plain(tmp_path)
    status, why = CA.PROBES[PROBE](None, data_dir=d)
    assert status == CA.NOT_SATISFIED
    assert "1h" in why and "6h" in why and "unreachable_by_cadence" in why and "24h" in why


def test_probe_satisfied_only_when_every_horizon_is_tracked(tmp_path, monkeypatch):
    d = _plain(tmp_path)
    real = CT.measure_horizons

    def all_tracked(carriers):
        out = real(carriers)
        for h in out["horizons"].values():
            h["kind"], h["carriers"] = "tracked", ["scene"]
        return out
    monkeypatch.setattr(CT, "measure_horizons", all_tracked)
    status, why = CA.PROBES[PROBE](None, data_dir=d)
    assert status == CA.SATISFIED and "5" in why


def test_probe_unmeasured_horizon_is_unmeasured_not_a_verdict(tmp_path):
    recs = [_rec(_D[0])]
    d = _scene_dir(tmp_path, records=recs, days=[_day(_D[0])])
    status, why = CA.PROBES[PROBE](None, data_dir=d)
    assert status == CA.UNMEASURED and "шаг наблюдения" in why


def test_probe_without_judge_and_replay_is_unmeasured(tmp_path):
    d = _plain(tmp_path, drop=("eval", "replay"))
    status, why = CA.PROBES[PROBE](None, data_dir=d)
    assert status == CA.UNMEASURED and "НЕ ИЗМЕРЕНО" in why


def test_probe_refuses_an_argument():
    status, why = CA.PROBES[PROBE]("x")
    assert status == CA.UNMEASURED and "аргумента" in why


def test_probe_is_not_a_substring_check(tmp_path):
    """ADR-333: проба меряет ИСХОД прибора, не слово в файле — подмена артефакта на текст с
    нужными словами исхода не меняет."""
    d = _plain(tmp_path)
    (tmp_path / "data" / SM.EVAL_REL).write_text(
        json.dumps({"per_verdict": [], "params": {"horizon_days": 7},
                    "note": "tracked tracked 1h 6h 24h 3d 7d satisfied"}), encoding="utf-8")
    status, _ = CA.PROBES[PROBE](None, data_dir=d)
    assert status == CA.NOT_SATISFIED
