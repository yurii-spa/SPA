"""Батарея §30 ТЗ «Portfolio CIO» — ``spa_core/analytics/shadow_mode_census.py``.

Каждая ось проверяется в обе стороны: сцена, где находка ЕСТЬ, и сцена, где её нет, с
названным звеном. Литеральных дат нет: даты сцены строятся от одного якоря-строки
(``_D``), сравниваются как строки и к часам не обращаются; порядок шагов цикла подаётся
ТЕКСТОМ; дверь взвода — настоящая (`cio_arming.trade_allowed`).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap

import pytest

from spa_core.analytics import shadow_mode_census as SM
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

ROOT = SM.REPO_ROOT
PROBE = "shadow_record_carries_the_system_action"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _card(tmp, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


_GOOD_CARD = """\
    ---
    title: x
    ---
    29. Emergency mode
    что-то
    30. Shadow Mode — обязательный этап
    Не подключать реальный capital execution сразу.
    После реализации Portfolio CIO сначала работает:
    SHADOW MODE
    Он видит реальные данные и портфель, но не выполняет транзакции.
    Каждый cycle сохраняет:
    what current system did

    what Portfolio CIO recommended

    why

    estimated outcome

    what happened afterwards


    ⸻


    31. Counterfactual tracking
    Для каждой неисполненной shadow recommendation отслеживать:
    """


def _order_text(*, record_first: bool = True, drop: str | None = None,
                dup: str | None = None) -> str:
    """Синтетический cycle_runner: три маркера в заданном порядке."""
    w = "        _cio_doc = write_shadow_rationale(\n"
    d = "    _cio_ok, _cio_dec, _cio_why = _cio_arming.trade_allowed(\n"
    t = "              and diff_usd > threshold_usd and (_churn.allowed or _cio_trial) and _cio_gate_ok)\n"
    parts = [w, d, t] if record_first else [d, t, w]
    text = "".join(parts)
    if drop:
        text = text.replace(SM.ORDER_MARKERS[drop], "nothing_here(")
    if dup:
        text += {"record_writer": w, "arming_door": d, "trade_decision": t}[dup]
    return text


# ───────────────────────────── сцена каталога данных ─────────────────────────

# Якорь сцены — ОДИН момент, снятый при импорте; все даты сцены производны от него и
# сравниваются только между собой как строки (к часам прибор на оси D не обращается).
_BASE = _now().date()
_D = [(_BASE + dt.timedelta(days=i)).isoformat() for i in range(9)]


def _rec(date: str, verdict: str = "HOLD", **over) -> dict:
    r = {
        "schema": "shadow-hist-v2", "cycle_date": date, "verdict": verdict,
        "reasons": ["scene"], "gates": {"g": True}, "legs": [], "target_positions": {"a": 60.0},
        "current_positions": {"a": 40.0, "b": 60.0}, "gain_pp": 0.1, "cost_usd": 1.0,
        "payback_days": 3.0, "target_apy_pp": 4.0, "book_apy_pp": 3.9,
        "apy_evidenced_pct": {"a": 3.0, "b": 4.0},
        "apy_as_of": {"a": f"{date}T07:00:00+00:00", "b": f"{date}T07:00:00+00:00"},
    }
    r.update(over)
    return r


def _day(date: str, turnover=0.0, positions=None) -> dict:
    d = {"date": date, "positions": positions or {"a": 40.0, "b": 60.0}}
    if turnover is not None:
        d["turnover_usd"] = turnover
    return d


def _scene_dir(tmp, *, records, days, trades=(), eval_doc=None, commits=(),
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
        (base / SM.EVAL_REL).write_text(json.dumps(eval_doc or {
            "ready_to_arm": False, "status": "NOT_READY", "observation_days": 9,
            "criteria": [{"criterion": "hit_rate", "status": "PASS"}],
            "counts": {"act": 0}, "arming_blockade": {"verdict": "X"},
            "per_verdict": [{"cycle_date": r["cycle_date"], "outcome": "hit"} for r in records],
        }), encoding="utf-8")
    if "commits" not in drop:
        (base / SM.COMMIT_REL).write_text(
            "".join(json.dumps({"cycle_date": c[0], "package": {"action": c[1]}}) + "\n"
                    for c in commits), encoding="utf-8")
    return str(base)


# ───────────────────────────── паритет ────────────────────────────────────────

def test_constants_agree_with_the_real_owner_card():
    p = SM.parity(os.path.join(ROOT, SM.CARD_REL))
    assert p["agrees"] is True, p
    assert len(SM.OWNER_SAVED_FIELDS) == SM.OWNER_SAVED_FIELDS_DECLARED == 5
    assert p["order_undercount"] == 5 - SM.ORDER_G962_NAMED["saved_fields"] == 3


def test_parity_on_a_faithful_scene_card(tmp_path):
    p = SM.parity(_card(tmp_path, _GOOD_CARD))
    assert p["agrees"] is True and p["mismatches"] == []


def test_parity_names_a_missing_field(tmp_path):
    p = SM.parity(_card(tmp_path, _GOOD_CARD.replace("    why\n\n", "")))
    assert p["agrees"] is False
    assert any("поля карточки" in m for m in p["mismatches"])


def test_parity_names_a_lost_no_exec_line(tmp_path):
    p = SM.parity(_card(tmp_path, _GOOD_CARD.replace(
        "Он видит реальные данные и портфель, но не выполняет транзакции.", "Он видит.")))
    assert p["agrees"] is False
    assert any("не выполняет транзакции" in m for m in p["mismatches"])


def test_missing_second_border_refuses_to_count(tmp_path):
    body = _GOOD_CARD.replace("31. Counterfactual tracking", "31. Что-то другое")
    p = SM.parity(_card(tmp_path, body))
    assert p["agrees"] is None
    assert "вторая граница" in p["parsed"]["reason"]


def test_unreadable_card_is_a_third_outcome_not_a_fallback(tmp_path):
    p = SM.parity(str(tmp_path / "nope.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── порядок шагов цикла ───────────────────────────

def test_live_cycle_runner_writes_the_record_before_the_trade():
    o = SM.measure_cycle_order(ROOT)
    assert o["kind"] == "record_precedes_the_trade", o
    ln = o["lines"]
    assert ln["record_writer"] < ln["arming_door"] < ln["trade_decision"]


def test_order_flips_when_the_trade_precedes_the_record():
    o = SM.measure_cycle_order(text=_order_text(record_first=False))
    assert o["kind"] == "trade_precedes_the_record"


def test_order_with_a_missing_marker_is_unmeasured_not_a_verdict():
    o = SM.measure_cycle_order(text=_order_text(drop="arming_door"))
    assert o["kind"] == UNMEASURED and "0 раз" in o["reason"]


def test_order_with_a_duplicated_marker_is_unmeasured():
    o = SM.measure_cycle_order(text=_order_text(dup="record_writer"))
    assert o["kind"] == UNMEASURED and "2 раз" in o["reason"]


def test_order_unreadable_source_is_unmeasured(tmp_path):
    o = SM.measure_cycle_order(root=str(tmp_path))
    assert o["kind"] == UNMEASURED and "не прочитан" in o["reason"]


# ───────────────────────────── ось A ─────────────────────────────────────────

def test_axis_a_on_the_live_tree_the_verdict_decides_and_arming_preceded_readiness(tmp_path):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])])
    a = SM.measure_execution(data, SM.measure_cycle_order(ROOT))
    assert a["measured"] and a["kind"] == "verdict_decides", a
    assert a["doors"]["armed_book_hold"]["allowed"] is False
    assert a["doors"]["armed_book_hold"]["kind"] == "verdict_decides"
    assert a["doors"]["armed_book_act"]["allowed"] is True
    assert a["doors"]["unarmed_book_hold"]["decision"] == "UNARMED"
    assert a["doors"]["unarmed_book_hold"]["kind"] == "shadow_only"
    assert a["armed_before_ready"] is True
    assert "conservative" in a["armed_books"]


def test_axis_a_unarmed_books_make_the_shadow_advisory(tmp_path, monkeypatch):
    from spa_core.paper_trading import cio_arming
    monkeypatch.setattr(cio_arming, "ARMED_BOOKS", {})
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])])
    a = SM.measure_execution(data, SM.measure_cycle_order(ROOT))
    assert a["kind"] == "shadow_only", a
    assert a["armed_before_ready"] is None
    assert a["armed_books"] == {}


def test_axis_a_unreadable_readiness_leaves_the_order_question_open(tmp_path):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])], drop=("eval",))
    a = SM.measure_execution(data, SM.measure_cycle_order(ROOT))
    assert a["kind"] == "verdict_decides"
    assert a["arming_readiness"]["measured"] is False
    assert a["armed_before_ready"] is None


def test_axis_a_ready_to_arm_true_is_not_an_inversion(tmp_path):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])],
                      eval_doc={"ready_to_arm": True, "criteria": []})
    a = SM.measure_execution(data, SM.measure_cycle_order(ROOT))
    assert a["armed_before_ready"] is False


def test_axis_a_door_failure_is_unmeasured_not_a_verdict(tmp_path, monkeypatch):
    from spa_core.paper_trading import cio_arming

    def boom(*a, **k):
        raise RuntimeError("scene")
    monkeypatch.setattr(cio_arming, "trade_allowed", boom)
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])])
    a = SM.measure_execution(data, SM.measure_cycle_order(ROOT))
    assert a["kind"] == UNMEASURED and "дверь упала" in a["why"]


def test_axis_a_a_door_whose_kind_contradicts_its_answer_is_unmeasured(tmp_path, monkeypatch):
    real = SM._door_arming

    def lying(book_id, verdict, current, target):
        r = real(book_id, verdict, current, target)
        r["kind"] = "shadow_only"  # ответ запрещает ход, род говорит «советник»
        return r
    monkeypatch.setattr(SM, "_door_arming", lying)
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])])
    a = SM.measure_execution(data, SM.measure_cycle_order(ROOT))
    assert a["kind"] == UNMEASURED and "непредвиденно" in a["why"]


def test_axis_a_every_kind_is_in_the_declared_vocabulary(tmp_path):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])])
    a = SM.measure_execution(data, SM.measure_cycle_order(ROOT))
    assert a["kind"] in SM.EXEC_KINDS
    for d in a["doors"].values():
        assert d["kind"] in SM.EXEC_KINDS


# ───────────────────────────── ось B ─────────────────────────────────────────

def test_axis_b_same_day_book_and_rates_are_real(tmp_path):
    c = SM.load_carriers(_scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])]))
    b = SM.measure_inputs(c)
    assert b["measured"]
    assert b["inputs"]["portfolio"]["kind"] == "real_same_day"
    assert b["inputs"]["rates"]["kind"] == "real_same_day"


def test_axis_b_a_book_that_differs_from_the_track_is_stale(tmp_path):
    c = SM.load_carriers(_scene_dir(tmp_path, records=[_rec(_D[0])],
                                    days=[_day(_D[0], positions={"a": 1.0})]))
    assert SM.measure_inputs(c)["inputs"]["portfolio"]["kind"] == "stale"


def test_axis_b_a_record_date_missing_from_the_track_is_stale(tmp_path):
    c = SM.load_carriers(_scene_dir(tmp_path, records=[_rec(_D[1])], days=[_day(_D[0])]))
    assert SM.measure_inputs(c)["inputs"]["portfolio"]["kind"] == "stale"


def test_axis_b_rates_observed_on_another_day_are_stale_and_no_as_of_is_unmeasured(tmp_path):
    stale = _rec(_D[1], apy_as_of={"a": f"{_D[0]}T07:00:00+00:00", "b": f"{_D[1]}T07:00:00+00:00"})
    c = SM.load_carriers(_scene_dir(tmp_path, records=[stale], days=[_day(_D[1])]))
    r = SM.measure_inputs(c)["inputs"]["rates"]
    assert r["kind"] == "stale" and r["same_day"] == 1
    no_asof = _rec(_D[1], apy_as_of={})
    c = SM.load_carriers(_scene_dir(tmp_path, records=[no_asof], days=[_day(_D[1])]))
    assert SM.measure_inputs(c)["inputs"]["rates"]["kind"] == UNMEASURED


def test_axis_b_empty_rates_are_absent_not_real(tmp_path):
    c = SM.load_carriers(_scene_dir(tmp_path, records=[_rec(_D[0], apy_evidenced_pct={})],
                                    days=[_day(_D[0])]))
    assert SM.measure_inputs(c)["inputs"]["rates"]["kind"] == "absent"


def test_axis_b_no_records_is_unmeasured(tmp_path):
    c = SM.load_carriers(_scene_dir(tmp_path, records=[], days=[_day(_D[0])]))
    b = SM.measure_inputs(c)
    assert b["measured"] is False and "пуста" in b["reason"]


# ───────────────────────────── ось C ─────────────────────────────────────────

def test_axis_c_on_the_live_tree_three_in_the_record_two_in_second_carriers(tmp_path):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])])
    f = SM.measure_fields(ROOT, SM.load_carriers(data))
    assert f["tally"] == {"in_the_record": 3, "in_a_second_carrier": 2,
                          "absent_everywhere": 0, UNMEASURED: 0}, f["tally"]
    sysr = f["fields"]["what current system did"]
    assert sysr["kind"] == "in_a_second_carrier" and sysr["commit_actions"] == {}
    assert f["fields"]["what happened afterwards"]["per_verdict"]["outcomes"] == {"hit": 1}


def test_axis_c_a_constant_the_writer_does_not_declare_is_unmeasured(monkeypatch, tmp_path):
    spec = dict(SM.FIELD_CARRIERS)
    spec["why"] = {"record_keys": ("reasons", "not_a_real_key"), "second": {}}
    monkeypatch.setattr(SM, "FIELD_CARRIERS", spec)
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])])
    f = SM.measure_fields(ROOT, SM.load_carriers(data))
    assert f["fields"]["why"]["kind"] == UNMEASURED
    assert "not_a_real_key" in f["fields"]["why"]["reason"]


def test_axis_c_no_live_records_leaves_coverage_unmeasured(tmp_path):
    data = _scene_dir(tmp_path, records=[], days=[_day(_D[0])])
    f = SM.measure_fields(ROOT, SM.load_carriers(data))
    assert f["fields"]["why"]["kind"] == UNMEASURED


def test_axis_c_unreadable_second_carriers_are_unmeasured_not_absent(tmp_path):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])],
                      drop=("daily", "trades", "commits"))
    f = SM.measure_fields(ROOT, SM.load_carriers(data))
    assert f["fields"]["what current system did"]["kind"] == UNMEASURED


def test_axis_c_unreadable_writer_is_unmeasured(tmp_path):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0])])
    f = SM.measure_fields(str(tmp_path), SM.load_carriers(data))
    assert f["fields"]["why"]["kind"] == UNMEASURED and "не прочитан" in f["fields"]["why"]["reason"]


def test_axis_c_writer_keys_are_read_from_the_real_writer():
    keys, why = SM._writer_keys(ROOT)
    assert why is None and {"verdict", "reasons", "gates", "gain_pp"} <= keys


# ───────────────────────────── ось D ─────────────────────────────────────────

def test_system_action_three_outcomes_are_distinct():
    days = {_D[0]: _day(_D[0], 0.0), _D[1]: _day(_D[1], 500.0), _D[2]: _day(_D[2], None)}
    assert SM.system_action_for_day(_D[0], days, set())["kind"] == "held"
    assert SM.system_action_for_day(_D[1], days, set())["kind"] == "moved"
    assert SM.system_action_for_day(_D[2], days, set())["kind"] == UNMEASURED
    # сделка на дату без оборота в треке — всё равно ход
    assert SM.system_action_for_day(_D[2], days, {_D[2]})["kind"] == "moved"
    # сделки не прочитаны: удержание по обороту названо с оговоркой, отсутствие — не измерено
    assert SM.system_action_for_day(_D[0], days, None)["kind"] == "held"
    assert SM.system_action_for_day(_D[2], days, None)["kind"] == UNMEASURED
    for k in ("held", "moved", UNMEASURED):
        assert k in SM.ACTION_KINDS


def test_axis_d_divergent_day_makes_the_answers_distinguishable(tmp_path):
    recs = [_rec(_D[0]), _rec(_D[1]), _rec(_D[2])]
    days = [_day(_D[0], 0.0), _day(_D[1], 1000.0), _day(_D[2], 0.0)]
    c = SM.load_carriers(_scene_dir(tmp_path, records=recs, days=days))
    d = SM.measure_pairs(c, armed_at=None)
    assert d["measured"] and d["track_days"] == 3 and d["days_with_record"] == 3
    assert d["matrix"] == {"held&HOLD": 2, "moved&HOLD": 1}
    assert d["divergent_days"][0]["date"] == _D[1]
    assert d["answers_distinguishable"] is True


def test_axis_d_after_arming_the_control_arm_is_counted_separately(tmp_path):
    recs = [_rec(_D[i]) for i in range(5)]
    days = [_day(_D[0], 0.0), _day(_D[1], 900.0), _day(_D[2], 0.0), _day(_D[3], 0.0), _day(_D[4], 0.0)]
    c = SM.load_carriers(_scene_dir(tmp_path, records=recs, days=days))
    d = SM.measure_pairs(c, armed_at=_D[2])
    assert d["after_arming"] == {"days": 2, "divergent": 0, "moved": 0}
    assert len(d["divergent_days"]) == 1


def test_axis_d_a_track_day_without_a_record_is_named(tmp_path):
    recs = [_rec(_D[0]), _rec(_D[2])]
    days = [_day(_D[0]), _day(_D[1]), _day(_D[2])]
    d = SM.measure_pairs(SM.load_carriers(_scene_dir(tmp_path, records=recs, days=days)), None)
    assert d["days_without_record"] == [_D[1]] and d["matrix"]["no_record"] == 1


def test_axis_d_two_runs_on_one_day_are_one_day_with_a_count(tmp_path):
    recs = [_rec(_D[0]), _rec(_D[0]), _rec(_D[1])]
    d = SM.measure_pairs(SM.load_carriers(_scene_dir(tmp_path, records=recs,
                                                     days=[_day(_D[0]), _day(_D[1])])), None)
    assert d["records"] == 3 and d["track_days"] == 2 and d["multi_run_days"] == 1


def test_axis_d_unreadable_track_is_unmeasured(tmp_path):
    c = SM.load_carriers(_scene_dir(tmp_path, records=[_rec(_D[0])], days=[], drop=("daily",)))
    d = SM.measure_pairs(c, None)
    assert d["measured"] is False and "трек" in d["reason"]


def test_axis_d_an_act_verdict_on_a_held_day_diverges_too(tmp_path):
    recs = [_rec(_D[0], verdict="ACT")]
    d = SM.measure_pairs(SM.load_carriers(_scene_dir(tmp_path, records=recs,
                                                     days=[_day(_D[0], 0.0)])), None)
    assert d["matrix"] == {"held&ACT": 1} and d["answers_distinguishable"]


# ───────────────────────────── находки и прогон ──────────────────────────────

def _scene_run(tmp_path, *, days_after_arming_diverge: bool, armed: bool = True,
               monkeypatch=None, **kw):
    recs = [_rec(_D[i]) for i in range(5)]
    tv = 700.0 if days_after_arming_diverge else 0.0
    days = [_day(_D[0], 0.0), _day(_D[1], 900.0), _day(_D[2], 0.0), _day(_D[3], tv), _day(_D[4], 0.0)]
    data = _scene_dir(tmp_path, records=recs, days=days, **kw)
    if monkeypatch is not None:
        from spa_core.paper_trading import cio_arming
        books = {"conservative": {"armed_at": _D[2], "adr": "ADR-scene"}} if armed else {}
        monkeypatch.setattr(cio_arming, "ARMED_BOOKS", books)
    (tmp_path / "card.md").write_text(textwrap.dedent(_GOOD_CARD), encoding="utf-8")
    return SM.run(root=ROOT, data_dir=data, card_path=str(tmp_path / "card.md"), write=False,
                  now=_now())


def test_run_on_the_scene_names_the_collapsed_control_arm(tmp_path, monkeypatch):
    doc = _scene_run(tmp_path, days_after_arming_diverge=False, monkeypatch=monkeypatch)
    codes = {f["code"] for f in doc["findings"]}
    assert "control_arm_collapsed_after_arming" in codes, codes
    assert "armed_before_the_shadow_criteria_passed" in codes
    assert "system_action_absent_from_the_record_by_step_order" in codes
    assert doc["overall"] == "CRITICAL" and doc["unmeasured"] == []
    assert doc["applied"] is False


def test_run_a_divergence_after_arming_drops_the_critical(tmp_path, monkeypatch):
    doc = _scene_run(tmp_path, days_after_arming_diverge=True, monkeypatch=monkeypatch)
    codes = {f["code"] for f in doc["findings"]}
    assert "control_arm_collapsed_after_arming" not in codes
    assert doc["counts"]["critical"] == 0


def test_run_an_unarmed_book_has_no_arming_findings(tmp_path, monkeypatch):
    doc = _scene_run(tmp_path, days_after_arming_diverge=False, armed=False,
                     monkeypatch=monkeypatch)
    codes = {f["code"] for f in doc["findings"]}
    assert not codes & {"control_arm_collapsed_after_arming",
                        "armed_before_the_shadow_criteria_passed",
                        "shadow_verdict_decides_the_reshuffle"}
    assert doc["axis_a_execution"]["kind"] == "shadow_only"


def test_run_unreadable_readiness_is_unmeasured_not_a_finding(tmp_path, monkeypatch):
    doc = _scene_run(tmp_path, days_after_arming_diverge=False, monkeypatch=monkeypatch,
                     drop=("eval",))
    codes = {f["code"] for f in doc["findings"]}
    assert "armed_before_the_shadow_criteria_passed" not in codes
    assert any("готовность взвода" in u for u in doc["unmeasured"])
    assert doc["axis_c_fields"]["fields"]["what happened afterwards"]["kind"] == UNMEASURED


def test_run_every_kind_printed_belongs_to_a_declared_vocabulary(tmp_path, monkeypatch, capsys):
    doc = _scene_run(tmp_path, days_after_arming_diverge=False, monkeypatch=monkeypatch)
    assert doc["axis_a_execution"]["kind"] in SM.EXEC_KINDS
    for v in doc["axis_b_inputs"]["inputs"].values():
        assert v["kind"] in SM.INPUT_KINDS
    for v in doc["axis_c_fields"]["fields"].values():
        assert v["kind"] in SM.FIELD_KINDS
    for key in doc["axis_d_pairs"]["matrix"]:
        if key != "no_record":
            assert key.split("&")[0] in SM.ACTION_KINDS
    SM._print(doc)
    assert "§30" in capsys.readouterr().out


def test_run_unreadable_card_is_unmeasured_not_a_finding(tmp_path, monkeypatch):
    recs = [_rec(_D[0])]
    data = _scene_dir(tmp_path, records=recs, days=[_day(_D[0], 0.0)])
    doc = SM.run(root=ROOT, data_dir=data, card_path=str(tmp_path / "nope.md"), write=False,
                 now=_now())
    assert any("паритет" in u for u in doc["unmeasured"])
    assert not any(f["code"] == "card_parity_mismatch" for f in doc["findings"])


def test_run_write_true_calls_atomic_save_with_data_then_path(tmp_path, monkeypatch):
    from spa_core.utils import atomic
    calls = []
    monkeypatch.setattr(atomic, "atomic_save", lambda data, path, **k: calls.append((data, path)))
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0], 0.0)])
    (tmp_path / "card.md").write_text(textwrap.dedent(_GOOD_CARD), encoding="utf-8")
    SM.run(root=ROOT, data_dir=data, card_path=str(tmp_path / "card.md"), write=True, now=_now())
    assert len(calls) == 1
    assert isinstance(calls[0][0], dict) and calls[0][1].endswith(SM.REPORT_REL)


def test_parse_now_is_an_input_and_refuses_garbage():
    anchor = _now()  # предмет — РАЗБОР формы, не дата: вход производится от часов сцены
    ts, why = SM.parse_now(anchor.isoformat().replace("+00:00", "Z"))
    assert why is None and ts == anchor and ts.tzinfo is not None
    assert SM.parse_now("")[1] and SM.parse_now("yesterday")[1]
    assert SM.parse_now(None) == (None, None)


def test_main_refuses_an_unparsable_now_with_code_2(capsys):
    assert SM.main(["--now", "garbage", "--no-write"]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_main_on_the_scene_returns_1_and_prints_the_verdict(tmp_path, monkeypatch, capsys):
    from spa_core.paper_trading import cio_arming
    monkeypatch.setattr(cio_arming, "ARMED_BOOKS",
                        {"conservative": {"armed_at": _D[2], "adr": "ADR-scene"}})
    recs = [_rec(_D[i]) for i in range(5)]
    days = [_day(_D[i], 0.0) for i in range(5)]
    data = _scene_dir(tmp_path, records=recs, days=days)
    (tmp_path / "card.md").write_text(textwrap.dedent(_GOOD_CARD), encoding="utf-8")
    rc = SM.main(["--data-dir", data, "--card", str(tmp_path / "card.md"), "--no-write"])
    out = capsys.readouterr().out
    assert rc == 1 and "CRITICAL" in out and "control_arm_collapsed_after_arming" in out


# ───────────────────────────── проба приёмки ─────────────────────────────────

def test_probe_is_registered_and_validates():
    assert PROBE in CA.PROBES
    assert CA.validate_spec(PROBE) is None
    assert "data_dir" in CA.probe_tree_inputs(PROBE)


def test_probe_on_the_scene_is_not_satisfied_and_names_the_carriers(tmp_path):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0], 0.0)])
    status, reason = CA.PROBES[PROBE](None, data_dir=data)
    assert status == CA.NOT_SATISFIED, reason
    assert "Step 2f" in reason and SM.TRACK_REL in reason


def test_probe_three_outcomes_are_distinct(tmp_path, monkeypatch):
    data = _scene_dir(tmp_path, records=[_rec(_D[0])], days=[_day(_D[0], 0.0)])
    assert CA.PROBES[PROBE](None, data_dir=str(tmp_path / "nowhere"))[0] == CA.UNMEASURED
    assert CA.PROBES[PROBE]("x", data_dir=data)[0] == CA.UNMEASURED
    spec = dict(SM.FIELD_CARRIERS)
    spec["what current system did"] = {"record_keys": ("verdict",), "second": {}}
    monkeypatch.setattr(SM, "FIELD_CARRIERS", spec)
    status, reason = CA.PROBES[PROBE](None, data_dir=data)
    assert status == CA.SATISFIED and "покрытие" in reason
    spec["what current system did"] = {"record_keys": ("no_such_key",), "second": {}}
    assert CA.PROBES[PROBE](None, data_dir=data)[0] == CA.UNMEASURED


def test_probe_import_failure_is_unmeasured(monkeypatch):
    import sys
    import spa_core.analytics as pkg
    monkeypatch.delattr(pkg, "shadow_mode_census", raising=False)
    monkeypatch.setitem(sys.modules, "spa_core.analytics.shadow_mode_census", None)
    status, reason = CA.PROBES[PROBE](None)
    assert status == CA.UNMEASURED and "не импортирован" in reason


def test_probe_is_not_a_substring_match():
    with pytest.raises(KeyError):
        CA.PROBES["shadow_record_carries"]
