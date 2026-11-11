"""Батарея §39 ТЗ «Portfolio CIO» — ``spa_core/analytics/observation_period_census.py``.

Прибор спрашивает у ЖИВОГО периода тени (журнал ADR-060, история газа, артефакт взвода),
какие из восьми рыночных событий владельца он уже содержит — у двери СИСТЕМЫ (полоса
`required_gain_pp`, режим газа p25/p75, горизонт судьи, гейт `target_fully_evidenced`), и
спрашивает ли критерий взвода о событиях. Сцены строятся на синтетическом журнале в
``tmp_path``; живой ``data/`` не читается.

Дни сцен — смещения от инъектированного ``now``; литеральных дат нет. Часы — ТОЛЬКО вход
``now=`` (рост входа судится от него).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from pathlib import Path

import pytest

from spa_core.analytics import observation_period_census as O
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA
from spa_core.monitoring import decision_journal_coverage as DJC
from spa_core.monitoring import gas_price_agent as gpa

PROBE = "observation_period_covers_the_owner_events"
_REPO = O.REPO_ROOT
_LIVE_CARD = os.path.join(_REPO, O.CARD_REL)
NOW = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)   # FROZEN-DATE-OK: injected-clock — якорь передаётся входом now= в run()/measure_growth(); стенные часы прибор не спрашивает
A, B, C = "proto_a", "proto_b", "proto_c"
REQ = 0.5


# ───────────────────────────── карточка ───────────────────────────────────────

def _card(tmp: Path, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


def _good_card_text() -> str:
    out = ["---", "title: x", "---", "38. Historical replay", "что-то", "", "⸻", "", O.SECTION_HEAD,
           O.OWNER_LINE_BEFORE, O.OWNER_LINE_DURATION, O.OWNER_LINE_NOT_DAYS_ONLY, O.OWNER_EVENTS_LEAD]
    for i, ev in enumerate(O.OWNER_EVENTS):
        out.append(ev + ("." if i == len(O.OWNER_EVENTS) - 1 else ";"))
    out += ["", "", "⸻", "", O.NEXT_SECTION_HEAD, "Stage 0"]
    return "\n".join(out) + "\n"


def test_constants_agree_with_the_real_owner_card():
    p = O.parity(_LIVE_CARD)
    assert p["parsed"]["measured"], p["parsed"].get("reason")
    assert p["agrees"] is True, p["mismatches"]
    assert len(p["parsed"]["events"]) == O.OWNER_EVENTS_DECLARED == 8


def test_parity_agrees_on_a_card_in_the_owner_form(tmp_path):
    p = O.parity(_card(tmp_path, _good_card_text()))
    assert p["agrees"] is True, p["mismatches"]


def test_parity_names_a_renamed_event(tmp_path):
    text = _good_card_text().replace("\nhigh gas;", "\nexpensive gas;")
    p = O.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("expensive gas" in m for m in p["mismatches"])


def test_parity_names_a_missing_events_lead(tmp_path):
    text = _good_card_text().replace(O.OWNER_EVENTS_LEAD + "\n", "")
    p = O.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("нет строки" in m and "событий" in m for m in p["mismatches"])


@pytest.mark.parametrize("line, word", [(O.OWNER_LINE_BEFORE, "тень"), (O.OWNER_LINE_DURATION, "сроке"),
                                        (O.OWNER_LINE_NOT_DAYS_ONLY, "количество дней")])
def test_parity_names_each_missing_owner_line(tmp_path, line, word):
    text = _good_card_text().replace(line + "\n", "")
    p = O.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any(word in m for m in p["mismatches"]), p["mismatches"]


def test_parity_requires_the_second_boundary(tmp_path):
    text = _good_card_text().replace(O.NEXT_SECTION_HEAD, "хвост без границы")
    p = O.parity(_card(tmp_path, text))
    assert p["agrees"] is None and "вторая граница" in p["parsed"]["reason"]


def test_parity_is_unmeasured_without_a_card(tmp_path):
    p = O.parity(str(tmp_path / "none.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── синтетический журнал ADR-060 ────────────────────

def _day(i: int) -> str:
    return (NOW.date() - dt.timedelta(days=30) + dt.timedelta(days=i)).isoformat()


def _rec(i: int, *, apy=None, gain=0.1, capital=100_000.0, target=None, unevidenced=None,
         gates=None, verdict="HOLD", policy_ok=None, hour=6) -> dict:
    day = _day(i)
    rec = {"cycle_date": day, "generated_at": f"{day}T{hour:02d}:00:00+00:00", "capital_usd": capital,
           "current_positions": {A: 60_000.0, B: 40_000.0},
           "target_positions": target if target is not None else {A: 50_000.0, B: 50_000.0},
           "apy_evidenced_pct": dict(apy if apy is not None else {A: 4.0, B: 5.0}),
           "apy_unevidenced": list(unevidenced or []), "verdict": verdict,
           "gain_pp": gain, "required_gain_pp": REQ}
    if gates is not None:
        rec["gates"] = gates
    if policy_ok is not None:
        rec["admissible_trim"] = {"policy": {"approved": policy_ok}}
    return rec


def _flat(n: int = 12, **kw) -> list:
    return [_rec(i, **kw) for i in range(n)]


def _write_journal(tmp: Path, records: list) -> Path:
    ddir = tmp / "data"
    ddir.mkdir(parents=True, exist_ok=True)
    with open(ddir / O.HISTORY_FILE, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return ddir


def _days(tmp: Path, records: list) -> list:
    ddir = _write_journal(tmp, records)
    days, why, _ = O.load_days(str(ddir))
    assert days is not None, why
    return days


def test_load_days_is_unmeasured_without_a_journal(tmp_path):
    days, why, bad = O.load_days(str(tmp_path))
    assert days is None and "наблюдать нечего" in why and bad == 0


def test_load_days_is_unmeasured_on_an_empty_journal(tmp_path):
    ddir = _write_journal(tmp_path, [])
    days, why, _ = O.load_days(str(ddir))
    assert days is None and "пуст" in why


def test_load_days_keeps_one_row_per_date_the_last_run_of_the_day(tmp_path):
    days = _days(tmp_path, [_rec(0, gain=0.1, hour=6), _rec(0, gain=0.9, hour=9), _rec(1)])
    assert [d["date"] for d in days] == [_day(0), _day(1)]
    assert days[0]["gain_pp"] == 0.9


def test_load_days_counts_corrupt_lines_instead_of_dropping_them_silently(tmp_path):
    ddir = _write_journal(tmp_path, _flat(3))
    with open(ddir / O.HISTORY_FILE, "a", encoding="utf-8") as fh:
        fh.write("{битая строка\n")
    days, why, bad = O.load_days(str(ddir))
    assert days is not None and len(days) == 3 and bad == 1


def test_load_days_reads_gates_through_the_arming_door_and_absent_fields_as_none(tmp_path):
    rec = _rec(0, gates={"target_fully_evidenced": False, "gain_above_band": True}, policy_ok=False)
    bare = {"cycle_date": _day(1), "generated_at": f"{_day(1)}T06:00:00+00:00"}
    days = _days(tmp_path, [rec, bare])
    assert days[0]["gates"] == {"target_fully_evidenced": False, "gain_above_band": True}
    assert days[0]["policy_approved"] is False
    assert days[1]["apy"] is None and days[1]["gain_pp"] is None and days[1]["gates"] is None
    assert days[1]["policy_approved"] is None and days[1]["capital_usd"] is None


# ───────────────────────────── детекторы: APY spike ───────────────────────────

def test_spike_fires_on_a_rise_at_least_the_band_and_names_the_protocol(tmp_path):
    recs = _flat(6)
    recs[3]["apy_evidenced_pct"][A] = 4.0 + REQ
    got = O.detect_apy_spike(_days(tmp_path, recs))
    assert got["days"] == [_day(3)]
    assert got["evidence"][0]["protocol"] == A and got["evidence"][0]["band_pp"] == REQ


def test_spike_ignores_a_rise_below_the_band(tmp_path):
    recs = _flat(6)
    recs[3]["apy_evidenced_pct"][A] = 4.0 + REQ * 0.9
    assert O.detect_apy_spike(_days(tmp_path, recs))["days"] == []


def test_spike_judges_the_rate_back_next_day_as_reverted(tmp_path):
    recs = _flat(6)
    recs[3]["apy_evidenced_pct"][A] = 4.0 + 2 * REQ
    got = O.detect_apy_spike(_days(tmp_path, recs))
    assert got["evidence"][0]["reverted_next_day"] is True


def test_spike_that_persists_is_not_reverted_and_the_last_day_is_unjudged(tmp_path):
    recs = _flat(6)
    for r in recs[3:]:
        r["apy_evidenced_pct"][A] = 4.0 + 2 * REQ
    got = O.detect_apy_spike(_days(tmp_path, recs))
    assert got["evidence"][0]["reverted_next_day"] is False
    recs2 = _flat(4)
    recs2[3]["apy_evidenced_pct"][A] = 4.0 + 2 * REQ
    got2 = O.detect_apy_spike(_days(tmp_path / "b", recs2))
    assert got2["evidence"][0]["reverted_next_day"] is None


def test_spike_skips_a_day_without_rates_instead_of_inventing_a_zero(tmp_path):
    recs = _flat(6)
    recs[2].pop("apy_evidenced_pct")
    recs[3]["apy_evidenced_pct"][A] = 9.0
    assert O.detect_apy_spike(_days(tmp_path, recs))["days"] == []


# ───────────────────────────── детекторы: серии ───────────────────────────────

def test_stable_opportunity_needs_the_judge_horizon_of_consecutive_days(tmp_path):
    n = O.RUN_DAYS
    hot = _flat(n + 2, gain=2 * REQ)
    got = O.detect_stable_opportunity(_days(tmp_path, hot))
    assert got["days"] and got["longest_run_days"] == n + 2 and got["min_run_days"] == n
    short = _flat(n + 2)
    for r in short[: n - 1]:
        r["gain_pp"] = 2 * REQ
    got = O.detect_stable_opportunity(_days(tmp_path / "b", short))
    assert got["days"] == [] and got["longest_run_days"] == n - 1


def test_a_calendar_gap_breaks_a_run(tmp_path):
    n = O.RUN_DAYS
    recs = [_rec(i, gain=2 * REQ) for i in range(n + 3) if i != 3]   # день 3 отсутствует
    got = O.detect_stable_opportunity(_days(tmp_path, recs))
    assert got["longest_run_days"] == n - 1 and got["runs_total"] == 2


def test_a_day_without_a_gain_breaks_a_run_rather_than_joining_it(tmp_path):
    n = O.RUN_DAYS
    recs = _flat(n + 2, gain=2 * REQ)
    recs[2].pop("gain_pp")
    got = O.detect_stable_opportunity(_days(tmp_path, recs))
    assert got["longest_run_days"] == n - 1


def test_no_action_period_is_a_quiet_hold_run_of_the_horizon(tmp_path):
    n = O.RUN_DAYS
    quiet = _flat(n + 1)
    got = O.detect_no_action_period(_days(tmp_path, quiet))
    assert got["days"] and got["longest_run_days"] == n + 1
    busy = _flat(n + 1, gain=2 * REQ)
    assert O.detect_no_action_period(_days(tmp_path / "b", busy))["days"] == []


def test_no_action_period_is_broken_by_an_act_verdict(tmp_path):
    n = O.RUN_DAYS
    recs = _flat(2 * n)
    recs[n - 1]["verdict"] = "ACT"
    got = O.detect_no_action_period(_days(tmp_path, recs))
    assert got["longest_run_days"] == n and got["runs_total"] == 2


# ───────────────────────────── детекторы: исчезновение, взнос, risk block ─────

def test_disappearing_fires_for_a_targeted_protocol_that_loses_its_rate(tmp_path):
    recs = _flat(6)
    for r in recs[4:]:
        r["apy_evidenced_pct"].pop(B)
    got = O.detect_opportunity_disappearing(_days(tmp_path, recs))
    assert got["days"] == [_day(4)] and got["evidence"][0]["protocol"] == B
    assert got["evidence"][0]["target_usd"] == 50_000.0


def test_disappearing_ignores_a_protocol_outside_the_target_or_with_a_zero_target(tmp_path):
    recs = _flat(6)
    for r in recs:
        r["apy_evidenced_pct"][C] = 7.0
    for r in recs[4:]:
        r["apy_evidenced_pct"].pop(C)
    assert O.detect_opportunity_disappearing(_days(tmp_path, recs))["days"] == []
    recs2 = _flat(6, target={A: 100_000.0, B: 0.0})
    for r in recs2[4:]:
        r["apy_evidenced_pct"].pop(B)
    assert O.detect_opportunity_disappearing(_days(tmp_path / "b", recs2))["days"] == []


def test_incoming_capital_fires_on_a_rise_only(tmp_path):
    recs = _flat(6)
    for r in recs[3:]:
        r["capital_usd"] = 110_000.0
    got = O.detect_incoming_capital(_days(tmp_path, recs))
    assert got["days"] == [_day(3)] and got["distinct_capital_values"] == [100_000.0, 110_000.0]
    down = _flat(6)
    for r in down[3:]:
        r["capital_usd"] = 90_000.0
    assert O.detect_incoming_capital(_days(tmp_path / "b", down))["days"] == []


@pytest.mark.parametrize("kw, door", [
    ({"gates": {"target_fully_evidenced": False}}, "gate:target_fully_evidenced"),
    ({"unevidenced": [B]}, "apy_unevidenced"),
    ({"policy_ok": False}, "risk_policy:approved=False"),
])
def test_risk_block_fires_on_each_declared_door_and_names_it(tmp_path, kw, door):
    recs = _flat(5)
    recs[2] = _rec(2, **kw)
    got = O.detect_risk_block(_days(tmp_path, recs))
    assert got["days"] == [_day(2)] and any(door in d for d in got["evidence"][0]["doors"])


def test_risk_block_is_silent_on_passing_gates_and_an_approving_policy(tmp_path):
    recs = _flat(5, gates={"target_fully_evidenced": True}, policy_ok=True)
    assert O.detect_risk_block(_days(tmp_path, recs))["days"] == []


def test_risk_block_does_not_read_an_economics_gate_as_risk(tmp_path):
    recs = _flat(5, gates={"gain_above_band": False, "target_fully_evidenced": True})
    assert O.detect_risk_block(_days(tmp_path, recs))["days"] == []


# ───────────────────────────── детекторы: газ ─────────────────────────────────

def _gas_file(tmp: Path, days: list, chain: str = O.GAS_CHAIN) -> Path:
    ddir = tmp / "data"
    ddir.mkdir(parents=True, exist_ok=True)
    readings = []
    for day, gweis, unchecked in days:
        for k, g in enumerate(gweis):
            readings.append({"ts": f"{day}T{k % 24:02d}:00:00Z", "source": "live", "gwei": g})
        for k in range(unchecked):
            readings.append({"ts": f"{day}T{k % 24:02d}:30:00Z", "source": "unchecked"})
    (ddir / O.GAS_FILE).write_text(json.dumps({"history": {chain: readings}}), encoding="utf-8")
    return ddir


def _gas_days(tmp: Path, spike: str | None, n_hist: int = gpa.MIN_HISTORY_FOR_REGIME) -> list:
    rows = [(_day(i), [1.0 + 0.01 * (k % 5) for k in range(n_hist)], 0) for i in range(3)]
    last = {"high": [10.0] * 4, "low": [0.1] * 4, None: [1.02] * 4}[spike]
    rows.append((_day(3), last, 2))
    ddir = _gas_file(tmp, rows)
    got, why = O.load_gas_days(str(ddir))
    assert got is not None, why
    return got


def test_gas_history_is_grouped_by_day_and_unchecked_readings_are_counted_not_numbered(tmp_path):
    gas = _gas_days(tmp_path, None)
    assert [g["date"] for g in gas] == [_day(i) for i in range(4)]
    assert gas[3]["unchecked"] == 2 and len(gas[3]["live_gwei"]) == 4


def test_gas_regime_is_judged_causally_by_the_system_door(tmp_path):
    hi = O.detect_gas_regime(_gas_days(tmp_path, "high"), gpa.REGIME_EXPENSIVE)
    assert hi["days"] == [_day(3)] and hi["evidence"][0]["percentile"] >= gpa.EXPENSIVE_PCTL
    assert hi["evidence"][0]["history_n"] == 3 * gpa.MIN_HISTORY_FOR_REGIME
    lo = O.detect_gas_regime(_gas_days(tmp_path / "b", "low"), gpa.REGIME_CHEAP)
    assert lo["days"] == [_day(3)]
    flat = O.detect_gas_regime(_gas_days(tmp_path / "c", None), gpa.REGIME_EXPENSIVE)
    assert flat["days"] == [] and flat["regime_tally"][gpa.REGIME_NORMAL] >= 1


def test_the_first_day_has_no_history_and_is_not_judged(tmp_path):
    rows = O._gas_regimes(_gas_days(tmp_path, "high"))
    assert rows[0]["regime"] == gpa.REGIME_NO_HISTORY


def test_a_day_of_unchecked_readings_only_is_unmeasured_not_normal(tmp_path):
    ddir = _gas_file(tmp_path, [(_day(0), [1.0] * gpa.MIN_HISTORY_FOR_REGIME, 0), (_day(1), [], 5)])
    gas, _ = O.load_gas_days(str(ddir))
    rows = O._gas_regimes(gas)
    assert rows[1]["regime"] == gpa.REGIME_UNMEASURED and rows[1]["unchecked"] == 5


def test_gas_history_without_the_chain_is_unmeasured_and_names_the_chains(tmp_path):
    ddir = _gas_file(tmp_path, [(_day(0), [1.0], 0)], chain="base")
    gas, why = O.load_gas_days(str(ddir))
    assert gas is None and "ethereum" in why and "base" in why


def test_gas_history_missing_is_unmeasured(tmp_path):
    gas, why = O.load_gas_days(str(tmp_path))
    assert gas is None and "не прочитана" in why


# ───────────────────────────── ось C: контроль детекторов ─────────────────────

def test_every_real_detector_discriminates_its_scene():
    ctl = O.control_detectors()
    assert set(ctl) == set(O.OWNER_EVENTS)
    assert {e: c["kind"] for e, c in ctl.items()} == {e: "discriminates" for e in O.OWNER_EVENTS}


def test_a_blind_detector_is_indiscriminate():
    got = O._control("x", [1], [2], lambda _d: {"days": ["d"]})
    assert got["kind"] == "indiscriminate" and got["fires_without_event"] is True


def test_a_detector_that_never_fires_is_indiscriminate_too():
    got = O._control("x", [1], [2], lambda _d: {"days": []})
    assert got["kind"] == "indiscriminate"


def test_a_crashing_detector_is_unmeasured_with_the_reason():
    def boom(_d):
        raise RuntimeError("упал")
    got = O._control("x", [1], [2], boom)
    assert got["kind"] == UNMEASURED and "упал" in got["reason"]


# ───────────────────────────── ось B: сборка на входах ────────────────────────

def _controls_ok() -> dict:
    return {e: {"event": e, "kind": "discriminates"} for e in O.OWNER_EVENTS}


def test_measure_events_is_unmeasured_per_input_when_it_is_missing():
    rows = O.measure_events(None, "журнала нет", None, "газа нет", _controls_ok())
    assert rows["APY spike"]["kind"] == UNMEASURED and "журнала" in rows["APY spike"]["reason"]
    assert rows["high gas"]["kind"] == UNMEASURED and "газа" in rows["high gas"]["reason"]


def test_an_indiscriminate_control_makes_its_event_unmeasured_not_observed(tmp_path):
    days = _days(tmp_path, _flat(10))
    ctl = _controls_ok()
    ctl["no-action period"] = {"event": "no-action period", "kind": "indiscriminate"}
    rows = O.measure_events(days, None, None, "газа нет", ctl)
    assert rows["no-action period"]["kind"] == UNMEASURED and "не различает" in rows["no-action period"]["reason"]


def test_measure_events_names_observed_and_never_observed_with_their_windows(tmp_path):
    n = O.RUN_DAYS
    recs = _flat(n + 3)
    recs[2]["apy_evidenced_pct"][A] = 4.0 + REQ
    days = _days(tmp_path, recs)
    rows = O.measure_events(days, None, None, "газа нет", _controls_ok())
    sp = rows["APY spike"]
    assert sp["kind"] == "observed" and sp["days_with_event"] == 1 and sp["input_days"] == n + 3
    assert sp["first"] == sp["last"] == _day(2) and sp["reverted_next_day"] == 1
    assert rows["incoming capital"]["kind"] == "never_observed"
    assert rows["incoming capital"]["distinct_capital_values"] == [100_000.0]
    assert rows["no-action period"]["kind"] == "observed" and rows["no-action period"]["longest_run_days"] == n + 3
    assert O._tally(rows) == {"observed": 2, "never_observed": 4, UNMEASURED: 2}


# ───────────────────────────── ось D: критерий срока ──────────────────────────

def _eval_file(tmp: Path, names: list, blockade: dict | None = None) -> Path:
    ddir = tmp / "data"
    ddir.mkdir(exist_ok=True)
    doc = {"criteria": [{"criterion": n, "status": "PASS"} for n in names], "observation_days": 40,
           "ready_to_arm": False, "generated_at": "x"}
    if blockade is not None:
        doc["arming_blockade"] = blockade
    (ddir / O.EVAL_FILE).write_text(json.dumps(doc), encoding="utf-8")
    return ddir


def test_criterion_is_unmeasured_without_the_artifact(tmp_path):
    got = O.measure_criterion(str(tmp_path))
    assert got["kind"] == UNMEASURED and "не прочитан" in got["reason"]


def test_criterion_without_a_criteria_section_is_unmeasured(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / O.EVAL_FILE).write_text(json.dumps({"ready_to_arm": False}), encoding="utf-8")
    got = O.measure_criterion(str(tmp_path / "data"))
    assert got["kind"] == UNMEASURED and "criteria" in got["reason"]


def test_criterion_of_the_live_arming_door_is_days_and_outcomes_only(tmp_path):
    ddir = _eval_file(tmp_path, ["observation_days", "hit_rate", "net_bps_if_followed"],
                      {"verdict": "UNREACHABLE_UNTIL_CHANGED", "reason": "ACT не было"})
    got = O.measure_criterion(str(ddir))
    assert got["kind"] == "days_and_outcomes_only"
    assert got["arming_blockade"]["verdict"] == "UNREACHABLE_UNTIL_CHANGED" and got["observation_days"] == 40


def test_criterion_of_days_alone_is_days_only(tmp_path):
    assert O.measure_criterion(str(_eval_file(tmp_path, ["observation_days"])))["kind"] == "days_only"


def test_criterion_naming_events_is_events_in_criterion(tmp_path):
    ddir = _eval_file(tmp_path, ["observation_days", "event_coverage"])
    assert O.measure_criterion(str(ddir))["kind"] == "events_in_criterion"


def test_criterion_with_no_names_is_absent(tmp_path):
    assert O.measure_criterion(str(_eval_file(tmp_path, [])))["kind"] == "absent"


# ───────────────────────────── ось E: рост ────────────────────────────────────

def test_growth_is_can_grow_while_the_input_is_within_the_horizon_and_cannot_grow_after():
    ev = {"incoming capital": {"kind": "never_observed", "source": "journal", "input_days": 9,
                               "distinct_capital_values": [100_000.0]}}
    fresh = {"journal": {"last": (NOW.date() - dt.timedelta(days=O.RUN_DAYS)).isoformat()}}
    g = O.measure_growth(ev, fresh, now=NOW)["incoming capital"]
    assert g["kind"] == "can_grow" and g["distinct_capital_values"] == 1 and "взносов" in g["note"]
    stale = {"journal": {"last": (NOW.date() - dt.timedelta(days=O.RUN_DAYS + 1)).isoformat()}}
    assert O.measure_growth(ev, stale, now=NOW)["incoming capital"]["kind"] == "cannot_grow"


def test_growth_is_unmeasured_when_the_input_has_no_last_date_and_skips_observed_events():
    ev = {"risk block": {"kind": "never_observed", "source": "journal"},
          "APY spike": {"kind": "observed", "source": "journal"}}
    g = O.measure_growth(ev, {"journal": {"days": None}}, now=NOW)
    assert g["risk block"]["kind"] == UNMEASURED and "APY spike" not in g


# ───────────────────────────── полный стенд ───────────────────────────────────

def _stand(tmp: Path, *, all_events: bool = False, criterion_names=None, gas: bool = True, card: bool = True) -> Path:
    n = O.RUN_DAYS
    recs = []
    for i in range(3 * n):
        recs.append(_rec(i, gain=(2 * REQ if (all_events and n <= i < 2 * n + 1) else 0.1)))
    if all_events:
        recs[2]["apy_evidenced_pct"][A] = 4.0 + REQ               # spike
        for r in recs[4:]:
            r["apy_evidenced_pct"].pop(B, None)                    # disappearing (B в цели)
        for r in recs[5:]:
            r["capital_usd"] = 110_000.0                           # incoming capital
        recs[6]["gates"] = {"target_fully_evidenced": False}       # risk block
    ddir = _write_journal(tmp, recs)
    if gas:
        rows = [(_day(i), [1.0 + 0.01 * (k % 5) for k in range(gpa.MIN_HISTORY_FOR_REGIME)], 0) for i in range(3)]
        rows.append((_day(3), [10.0] * 4, 0))
        rows.append((_day(4), [0.1] * 4, 0))
        _gas_file(tmp, rows)
    names = criterion_names if criterion_names is not None else ["observation_days", "hit_rate", "net_bps_if_followed"]
    _eval_file(tmp, names, {"verdict": "UNREACHABLE_UNTIL_CHANGED", "reason": "ACT не было"})
    if card:
        (tmp / O.CARD_REL).parent.mkdir(parents=True, exist_ok=True)
        (tmp / O.CARD_REL).write_text(_good_card_text(), encoding="utf-8")
    return ddir


def test_run_on_a_live_like_stand_is_critical_and_names_the_unobserved_events(tmp_path):
    ddir = _stand(tmp_path)
    doc = O.run(root=str(tmp_path), data_dir=str(ddir), write=False, now=NOW)
    assert doc["overall"] == "CRITICAL" and doc["applied"] is False
    codes = [f["code"] for f in doc["findings"]]
    assert codes.count("owner_event_never_observed") == 5   # spike, stable, disappearing, incoming, risk block
    assert "event_coverage_not_a_criterion" in codes and "arming_blockade_carried" in codes
    assert doc["coverage"]["observed"] == 3 and doc["coverage"]["share"] == 0.375
    assert doc["population"]["scoreable"] == 3 * O.RUN_DAYS
    assert "gas_window_shorter_than_journal" in codes


def test_run_on_a_stand_with_every_event_and_an_event_criterion_is_ok(tmp_path):
    ddir = _stand(tmp_path, all_events=True, criterion_names=["observation_days", "event_coverage"])
    doc = O.run(root=str(tmp_path), data_dir=str(ddir), write=False, now=NOW)
    assert doc["events_tally"] == {"observed": 8, "never_observed": 0, UNMEASURED: 0}, doc["events"]
    assert doc["criterion"]["kind"] == "events_in_criterion"
    assert [f["code"] for f in doc["findings"] if f["severity"] == "CRITICAL"] == []
    # окно газа короче журнала — честный WARN даже на полном стенде
    assert doc["overall"] == "WARNING"


def test_run_without_any_input_is_unchecked_with_every_reason_named(tmp_path):
    doc = O.run(root=str(tmp_path), data_dir=str(tmp_path / "data"), write=False, now=NOW)
    assert doc["overall"] == "UNCHECKED" and doc["coverage"]["share"] is None
    assert doc["population"]["scoreable"] is None
    assert any("паритет" in u for u in doc["unmeasured"])
    assert sum(1 for u in doc["unmeasured"] if u.startswith("событие")) == O.OWNER_EVENTS_DECLARED
    assert any("критерий срока" in u for u in doc["unmeasured"])


def test_a_drifted_card_is_a_critical_finding(tmp_path):
    ddir = _stand(tmp_path)
    (tmp_path / O.CARD_REL).write_text(_good_card_text().replace("\nlow gas;", "\ncheap gas;"), encoding="utf-8")
    doc = O.run(root=str(tmp_path), data_dir=str(ddir), write=False, now=NOW)
    assert any(f["code"] == "owner_section_drifted" for f in doc["findings"])


def test_write_false_leaves_the_tree_untouched_and_write_true_writes_the_report(tmp_path):
    ddir = _stand(tmp_path)
    O.run(root=str(tmp_path), data_dir=str(ddir), write=False, now=NOW)
    assert not (tmp_path / O.REPORT_REL).exists()
    O.run(root=str(tmp_path), data_dir=str(ddir), write=True, now=NOW)
    got = json.loads((tmp_path / O.REPORT_REL).read_text(encoding="utf-8"))
    assert got["schema"] == "observation_period_census/v1" and got["generated_at"] == NOW.isoformat()


def test_declared_kinds_cover_every_kind_the_instrument_can_emit(tmp_path):
    ddir = _stand(tmp_path, all_events=True)
    doc = O.run(root=str(tmp_path), data_dir=str(ddir), write=False, now=NOW)
    assert all(r["kind"] in O.EVENT_KINDS for r in doc["events"].values())
    assert all(c["kind"] in O.CONTROL_KINDS for c in doc["controls"].values())
    assert doc["criterion"]["kind"] in O.CRITERION_KINDS
    assert set(doc["declared"]["event_doors"]) == set(O.OWNER_EVENTS)


def test_run_days_is_the_judge_horizon_of_the_arming_door():
    from spa_core.paper_trading import shadow_trigger_eval as ste
    assert O.RUN_DAYS == ste.DEFAULT_HORIZON_DAYS


def test_main_refuses_an_unparseable_now_with_code_2(capsys):
    assert O.main(["--now", "вчера", "--no-write"]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_main_returns_1_on_a_critical_stand_and_prints_the_events(tmp_path, capsys):
    ddir = _stand(tmp_path)
    rc = O.main(["--root", str(tmp_path), "--data-dir", str(ddir), "--now", NOW.isoformat(), "--no-write"])
    out = capsys.readouterr().out
    assert rc == 1 and "наблюдено 3 из 8" in out and "never_observed" in out and "days_and_outcomes_only" in out


def test_main_returns_2_on_an_unchecked_tree(tmp_path):
    rc = O.main(["--root", str(tmp_path), "--data-dir", str(tmp_path / "data"), "--now", NOW.isoformat(), "--no-write"])
    assert rc == 2


# ───────────────────────────── проба приёмки ──────────────────────────────────

def test_probe_is_registered_with_both_tree_inputs():
    assert PROBE in CA.PROBES
    assert set(CA.probe_tree_inputs(PROBE)) == {"repo_root", "data_dir"}


def test_probe_rejects_an_argument():
    status, why = CA.PROBES[PROBE]("x")
    assert status == CA.UNMEASURED and "аргумента" in why


def test_probe_is_unmeasured_on_a_tree_without_the_card(tmp_path):
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(tmp_path))
    assert status == CA.UNMEASURED and "паритет" in why


def test_probe_is_unmeasured_without_a_journal(tmp_path):
    (tmp_path / O.CARD_REL).parent.mkdir(parents=True)
    (tmp_path / O.CARD_REL).write_text(_good_card_text(), encoding="utf-8")
    (tmp_path / "data").mkdir()
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(tmp_path / "data"))
    assert status == CA.UNMEASURED and "APY spike" in why and "критерий срока" in why


def test_probe_is_not_satisfied_on_a_live_like_stand_and_names_the_points(tmp_path):
    ddir = _stand(tmp_path)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED
    assert "событие stable opportunity" in why and "событие incoming capital" in why
    assert "критерий срока" in why and "days_and_outcomes_only" in why and "рост" in why


def test_probe_is_not_satisfied_when_a_detector_is_indiscriminate(tmp_path, monkeypatch):
    ddir = _stand(tmp_path, all_events=True, criterion_names=["event_coverage"])
    real = O.control_detectors
    def blind():
        ctl = real()
        ctl["risk block"] = {"event": "risk block", "kind": "indiscriminate"}
        return ctl
    monkeypatch.setattr(O, "control_detectors", blind)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    # событие стало unmeasured ⇒ проба не судит
    assert status == CA.UNMEASURED and "risk block" in why


def test_probe_is_satisfied_only_when_every_event_is_observed_and_the_criterion_asks_about_events(tmp_path):
    ddir = _stand(tmp_path, all_events=True, criterion_names=["observation_days", "event_coverage"])
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.SATISFIED, why
    assert "все 8 событий" in why


def test_probe_is_not_satisfied_when_the_card_drifts(tmp_path):
    ddir = _stand(tmp_path, all_events=True, criterion_names=["event_coverage"])
    (tmp_path / O.CARD_REL).write_text(_good_card_text().replace("\nlow gas;", "\ncheap gas;"), encoding="utf-8")
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED and "карточка" in why


# ───────────────────────────── население читателей журнала ────────────────────

def test_instrument_is_a_registered_reader_of_the_journal_and_publishes_its_population(tmp_path):
    spec = [r for r in DJC.READERS if r["module"] == O.__name__]
    assert spec and spec[0]["probe"] == "run"
    ddir = _stand(tmp_path)
    doc = O.run(str(tmp_path), data_dir=str(ddir), write=False, now=NOW)
    assert isinstance(doc["population"]["scoreable"], int) and DJC._own_coverage(doc) == 3 * O.RUN_DAYS
