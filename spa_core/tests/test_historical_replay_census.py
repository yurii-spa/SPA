"""Батарея §38 ТЗ «Portfolio CIO» — ``spa_core/analytics/historical_replay_census.py``.

Прибор меряет СУЩЕСТВУЮЩИЙ реплей (`cio_shadow_replay`, ADR-245): какие из девяти осей владельца
он несёт, держится ли «без look-ahead» сценой на живых дверях, какую долю прошлого периода
покрывает сравнение и может ли оно вырасти, считает ли кто-нибудь главную цель владельца.
Сцены строятся на синтетическом журнале ADR-060 в ``tmp_path``; живой ``data/`` не читается.

Дни сцен — порядковые строки (``day-NN``) либо смещения от инъектированного ``now``; литеральных
дат нет. Часы — ТОЛЬКО вход ``now=`` (свежесть артефакта судится от него).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from pathlib import Path

from spa_core.analytics import historical_replay_census as H
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA
from spa_core.monitoring import cio_shadow_replay as R

PROBE = "historical_replay_compares_the_owner_period"
_REPO = H.REPO_ROOT
_LIVE_CARD = os.path.join(_REPO, H.CARD_REL)
NOW = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)   # FROZEN-DATE-OK: injected-clock — якорь передаётся входом now= в run()/measure_freshness(); стенные часы прибор не спрашивает


# ───────────────────────────── карточка ───────────────────────────────────────

def _card(tmp: Path, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


def _good_card_text() -> str:
    out = ["---", "title: x", "---", "37. Testing scenarios", "что-то", H.SECTION_HEAD,
           H.OWNER_CONDITION_LINE, H.OWNER_NO_LOOKAHEAD_LINE, H.OWNER_COMPARE_LEAD,
           H.OWNER_STRATEGIES[0], "", H.OWNER_VS, "", H.OWNER_STRATEGIES[1], H.OWNER_AXES_LEAD]
    for ax in H.OWNER_AXES:
        out += [ax, ""]
    out += [H.OWNER_GOAL_LEAD, H.OWNER_GOAL_NOT, H.OWNER_GOAL_LEAD, H.OWNER_GOAL_SHOW,
            H.OWNER_GOAL_METRIC, "", "", "⸻", "", H.NEXT_SECTION_HEAD, "хвост"]
    return "\n".join(out) + "\n"


def test_constants_agree_with_the_real_owner_card():
    p = H.parity(_LIVE_CARD)
    assert p["parsed"]["measured"], p["parsed"].get("reason")
    assert p["agrees"] is True, p["mismatches"]
    assert len(p["parsed"]["axes"]) == H.OWNER_AXES_DECLARED == 9
    assert len(p["parsed"]["strategies"]) == H.OWNER_STRATEGIES_DECLARED == 2


def test_parity_agrees_on_a_card_in_the_owner_form(tmp_path):
    p = H.parity(_card(tmp_path, _good_card_text()))
    assert p["agrees"] is True, p["mismatches"]


def test_parity_names_a_renamed_axis(tmp_path):
    text = _good_card_text().replace("\nFees\n", "\nCommissions\n")
    p = H.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("Commissions" in m for m in p["mismatches"])


def test_parity_names_a_missing_no_lookahead_line(tmp_path):
    text = _good_card_text().replace(H.OWNER_NO_LOOKAHEAD_LINE + "\n", "")
    p = H.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("look-ahead" in m for m in p["mismatches"])


def test_parity_names_a_missing_goal_metric(tmp_path):
    text = _good_card_text().replace(H.OWNER_GOAL_METRIC + "\n", "")
    p = H.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("метрики цели" in m for m in p["mismatches"])


def test_parity_names_a_renamed_strategy(tmp_path):
    text = _good_card_text().replace("Portfolio CIO Shadow Strategy", "CIO Strategy")
    p = H.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("стратегии" in m for m in p["mismatches"])


def test_parity_requires_the_vs_between_strategies(tmp_path):
    text = _good_card_text().replace("\nvs\n", "\n\n")
    p = H.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("'vs'" in m for m in p["mismatches"])


def test_parity_requires_the_second_boundary(tmp_path):
    text = _good_card_text().replace(H.NEXT_SECTION_HEAD, "хвост без границы")
    p = H.parity(_card(tmp_path, text))
    assert p["agrees"] is None and "вторая граница" in p["parsed"]["reason"]


def test_parity_is_unmeasured_without_a_card(tmp_path):
    p = H.parity(str(tmp_path / "none.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── синтетический журнал ADR-060 ────────────────────

A, B, C = "proto_a", "proto_b", "proto_c"


def _write_history(tmp: Path, records: list) -> Path:
    ddir = tmp / "data"
    ddir.mkdir(exist_ok=True)
    with open(ddir / "allocation_rationale_history.jsonl", "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    (ddir / "adapter_registry.json").write_text(json.dumps(
        {"adapters": {A: {"chain": "ethereum"}, B: {"chain": "ethereum"}, C: {"chain": "base"}}}),
        encoding="utf-8")
    return ddir


def _history(n_days: int, *, drop_b_after: int | None = None, start: dt.date | None = None) -> list:
    """Книга стоит в A/B; с ``drop_b_after`` ставка B исчезает из записей (как `pendle` с 06.09)."""
    start = start or (NOW.date() - dt.timedelta(days=n_days))
    out = []
    for i in range(n_days):
        day = (start + dt.timedelta(days=i)).isoformat()
        apy = {A: 4.0 + 0.01 * i, B: 6.0, C: 5.0}
        if drop_b_after is not None and i > drop_b_after:
            apy.pop(B)
        out.append({"cycle_date": day, "generated_at": f"{day}T06:00:00+00:00", "capital_usd": 100_000.0,
                    "current_positions": {A: 60_000.0, B: 40_000.0},
                    "target_positions": {A: 50_000.0, B: 50_000.0},
                    "apy_evidenced_pct": apy, "verdict": "HOLD", "required_gain_pp": 0.5})
    return out


def test_replay_runs_on_a_copy_and_leaves_the_data_dir_untouched(tmp_path):
    ddir = _write_history(tmp_path, _history(14))
    before = {p.name: p.read_bytes() for p in ddir.iterdir()}
    got = H.run_replay_on_copy(str(ddir), now=NOW)
    assert got["measured"] is True, got.get("reason")
    assert got["copied"] == ["allocation_rationale_history.jsonl", "adapter_registry.json"]
    assert got["missing"] == ["gas_price_history.json"]
    assert {p.name: p.read_bytes() for p in ddir.iterdir()} == before
    assert not (ddir / "cio_shadow_replay.json").exists()
    assert got["doc"]["population"]["common_scored_days"] == 13


def test_replay_input_files_are_exactly_what_the_replay_reads():
    src = Path(R.__file__).read_text(encoding="utf-8")
    for name in H.REPLAY_INPUT_FILES:
        if name == "allocation_rationale_history.jsonl":
            continue   # читается через load_history (shadow_trigger_eval)
        assert name in src, name
    from spa_core.paper_trading import shadow_trigger_eval as ste
    assert "allocation_rationale_history.jsonl" in Path(ste.__file__).read_text(encoding="utf-8")


def test_a_missing_history_is_unmeasured_not_empty(tmp_path):
    got = H.run_replay_on_copy(str(tmp_path), now=NOW)
    assert got["measured"] is False and "прогонять нечего" in got["reason"]


def test_a_crashing_replay_is_unmeasured_with_the_reason(tmp_path, monkeypatch):
    ddir = _write_history(tmp_path, _history(5))
    def _boom(**_):
        raise RuntimeError("реплей упал")
    monkeypatch.setattr(R, "run", _boom)
    got = H.run_replay_on_copy(str(ddir), now=NOW)
    assert got["measured"] is False and "реплей упал" in got["reason"]


# ───────────────────────────── ось A: оси владельца ───────────────────────────

def _replay_doc(tmp_path, n_days=14, **kw):
    ddir = _write_history(tmp_path, _history(n_days, **kw))
    return H.run_replay_on_copy(str(ddir), now=NOW)["doc"], ddir


def test_axes_on_the_real_replay_are_seven_carried_two_partial(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    axes = H.measure_axes(doc)
    assert set(axes) == set(H.OWNER_AXES)
    kinds = {a: r["kind"] for a, r in axes.items()}
    assert kinds["Risk Events"] == "partial" and "concentration_cap" in axes["Risk Events"]["narrowing"]
    assert kinds["False Rebalances"] == "partial" and "живой книги" in axes["False Rebalances"]["narrowing"]
    assert all(k == "carried" for a, k in kinds.items() if a not in ("Risk Events", "False Rebalances"))
    assert H._tally(axes) == {"carried": 7, "partial": 2, "absent": 0, UNMEASURED: 0}


def test_an_axis_whose_field_vanishes_is_absent_and_named(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    for block in doc["columns"].values():
        for arm in block["arms"].values():
            arm.pop("fees_usd")
    axes = H.measure_axes(doc)
    assert axes["Fees"]["kind"] == "absent" and "fees_usd" in axes["Fees"]["reason"]


def test_an_axis_missing_in_one_column_only_is_absent(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    doc["columns"]["charged"]["arms"][R.ARM_CIO_HOLD].pop("turnover_usd")
    axes = H.measure_axes(doc)
    assert axes["Turnover"]["kind"] == "absent" and "charged/cio_hold" in axes["Turnover"]["reason"]


def test_a_column_axis_that_is_unchecked_is_absent(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    doc["columns"]["charged"]["missed_opportunities"] = {"verdict": "UNCHECKED", "reason": "нет"}
    axes = H.measure_axes(doc)
    assert axes["Missed Opportunities"]["kind"] == "absent" and "UNCHECKED" in axes["Missed Opportunities"]["reason"]


def test_a_report_without_columns_leaves_every_axis_absent():
    axes = H.measure_axes({"columns": {}})
    assert all(r["kind"] == "absent" for r in axes.values())


def test_risk_events_narrowing_is_measured_from_the_signature(tmp_path, monkeypatch):
    doc, _ = _replay_doc(tmp_path)
    monkeypatch.setattr(H, "risk_event_inputs", lambda: (("concentration_cap", "kill_switch_days"), None))
    axes = H.measure_axes(doc)
    assert axes["Risk Events"]["kind"] == UNMEASURED and "перемерить" in axes["Risk Events"]["reason"]


def test_risk_event_inputs_today_is_the_concentration_cap_only():
    inputs, why = H.risk_event_inputs()
    assert why is None and inputs == H.RISK_EVENT_INPUTS_EXPECTED


def test_false_rebalances_become_carried_when_judged_per_arm(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    for block in doc["columns"].values():
        block["false_rebalances"]["arms"] = {R.ARM_CURRENT: {}, R.ARM_CIO_HOLD: {}}
    axes = H.measure_axes(doc)
    assert axes["False Rebalances"]["kind"] == "carried"


# ───────────────────────────── цель владельца ─────────────────────────────────

def test_goal_on_the_real_replay_is_components_only(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    g = H.measure_goal(doc)
    assert g["kind"] == "components_only"
    assert set(g["components_present"]) == set(H.GOAL_COMPONENTS)
    assert "не складывает никто" in g["reason"]


def test_goal_is_computed_when_a_risk_adjusted_key_appears(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    doc["comparison"]["charged"]["risk_adjusted_net_pp"] = 1.0
    g = H.measure_goal(doc)
    assert g["kind"] == "computed" and g["keys"] == ["charged.risk_adjusted_net_pp"]


def test_goal_is_absent_when_a_component_is_missing(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    for block in doc["columns"].values():
        for arm in block["arms"].values():
            arm.pop("risk_events")
    g = H.measure_goal(doc)
    assert g["kind"] == "absent" and "risk_events" in g["reason"]


def test_goal_is_unmeasured_without_a_comparison():
    assert H.measure_goal({})["kind"] == UNMEASURED
    assert H.measure_goal({"comparison": {}})["kind"] == UNMEASURED


# ───────────────────────────── ось B: look-ahead ──────────────────────────────

def test_scene_composition_is_causal_on_the_live_door():
    row = H.scene_composition_is_causal()
    assert row["holds"] is True and row["torn_holds"] is False
    assert row["kind"] == "causal" and row["tear_kind"] == "discriminates"


def test_scene_scored_by_tomorrow_on_the_live_door():
    row = H.scene_scored_by_tomorrow()
    assert row["holds"] is True and row["torn_holds"] is False
    assert row["kind"] == "causal" and row["tear_kind"] == "discriminates"
    assert row["spike_day_gain_usd"]["book_in_spike"] == row["spike_day_gain_usd"]["book_outside"]
    assert row["torn_spike_day_gain_usd"]["book_in_spike"] > row["torn_spike_day_gain_usd"]["book_outside"]
    assert row["last_day_not_invented"] is True


def test_a_leaking_scorer_is_named_leaks(monkeypatch):
    """Положительный контроль: дверь с утечкой (оценка тем же днём) обязана дать `leaks`."""
    def leaky(books, records, *, day_gain):
        out = [day_gain(books[i], records[i]["apy_evidenced_pct"])[0] for i in range(len(records) - 1)]
        return out, set()
    monkeypatch.setattr(R, "score_days", leaky)
    row = H.scene_scored_by_tomorrow()
    assert row["kind"] == "leaks" and row["holds"] is False
    la = H.measure_lookahead()
    assert la["scored_by_tomorrow"]["kind"] == "leaks"


def test_a_leaking_builder_is_named_leaks(monkeypatch):
    real = R.build_arms
    def leaky(records):
        out = real(records)
        out[R.ARM_CIO_OPT] = [R._positions(records[min(i + 1, len(records) - 1)], "target_positions")
                              for i in range(len(records))]
        return out
    monkeypatch.setattr(R, "build_arms", leaky)
    row = H.scene_composition_is_causal()
    assert row["kind"] == "leaks"


def test_a_predicate_blind_to_the_spike_is_indiscriminate(monkeypatch):
    """Контроль чувствительности на НАСТОЯЩЕЙ сцене: если формула выгоды слепа к ставке, живая
    и порванная двери отвечают одинаково — сцена обязана сказать `indiscriminate`, а не
    «различает» по умолчанию."""
    monkeypatch.setattr(H, "_day_gain", lambda: (lambda _deltas, _apy: (1.0, [])))
    row = H.scene_scored_by_tomorrow()
    assert row["holds"] is True and row["torn_holds"] is True
    assert row["tear_kind"] == "indiscriminate"
    assert H.measure_lookahead()["scored_by_tomorrow"]["kind"] == UNMEASURED


def test_an_indiscriminate_scene_is_unmeasured_not_causal(monkeypatch):
    monkeypatch.setitem(H.LOOKAHEAD_SCENES, "scored_by_tomorrow",
                        lambda: {"name": "scored_by_tomorrow", "holds": True, "torn_holds": True,
                                 "kind": "causal", "tear_kind": "indiscriminate"})
    la = H.measure_lookahead()
    assert la["scored_by_tomorrow"]["kind"] == UNMEASURED and "не различает" in la["scored_by_tomorrow"]["reason"]


def test_a_scene_that_raises_is_unmeasured(monkeypatch):
    def _boom():
        raise RuntimeError("дверь упала")
    monkeypatch.setitem(H.LOOKAHEAD_SCENES, "composition_is_causal", _boom)
    la = H.measure_lookahead()
    assert la["composition_is_causal"]["kind"] == UNMEASURED and "дверь упала" in la["composition_is_causal"]["reason"]


# ───────────────────────────── ось C: популяция ───────────────────────────────

def test_population_can_grow_when_the_hold_book_is_priced_in_the_last_record(tmp_path):
    doc, ddir = _replay_doc(tmp_path, n_days=14)
    records, _ = H.load_records(str(ddir))
    pop = H.measure_population(doc, records)
    assert pop["kind"] == "can_grow" and pop["hold_book_unpriced_in_last_record"] == []
    assert pop["common_scored_days"] == 13 and pop["day_pairs"] == 13 and pop["coverage_share"] == 1.0
    assert pop["replay_refuses_claim"] is False


def test_population_cannot_grow_when_a_hold_protocol_lost_its_price(tmp_path):
    doc, ddir = _replay_doc(tmp_path, n_days=30, drop_b_after=8)
    records, _ = H.load_records(str(ddir))
    pop = H.measure_population(doc, records)
    assert pop["kind"] == "cannot_grow"
    assert pop["hold_book_unpriced_in_last_record"] == [B]
    assert pop["hold_book_last_priced"][B] == records[8]["cycle_date"]
    assert pop["common_scored_days"] == 8 and pop["day_pairs"] == 29
    assert pop["last_common_date"] == records[7]["cycle_date"]
    assert pop["replay_refuses_claim"] is True


def test_population_growth_is_measured_against_the_adr245_baseline(tmp_path):
    doc, ddir = _replay_doc(tmp_path, n_days=14)
    records, _ = H.load_records(str(ddir))
    pop = H.measure_population(doc, records)
    g = pop["growth_since_adr245"]
    assert g["day_pairs"] == 13 - H.ADR245_BASELINE["day_pairs"]
    assert g["common_scored_days"] == 13 - H.ADR245_BASELINE["common_scored_days"]


def test_population_empty_is_its_own_kind():
    pop = H.measure_population({"population": {"day_pairs": 5, "common_scored_days": 0, "common_dates": []}}, [])
    assert pop["kind"] == "empty"


def test_population_is_unmeasured_without_records(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    pop = H.measure_population(doc, None)
    assert pop["kind"] == UNMEASURED and "не прочитаны" in pop["reason"]


def test_population_is_unmeasured_without_the_block():
    assert H.measure_population({}, [])["kind"] == UNMEASURED


# ───────────────────────────── ось D / E ──────────────────────────────────────

def test_strategy_pair_maps_the_owner_words_to_the_replay_arms(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    pair = H.measure_strategy_pair(doc)
    assert pair["kind"] == "both_present"
    assert pair["mapping"] == {"Current Strategy": R.ARM_CURRENT, "Portfolio CIO Shadow Strategy": R.ARM_CIO_HOLD}
    assert pair["extra_arms"] == [R.ARM_CIO_OPT]
    assert pair["shadow_arm_acted_as"] == {"HOLD": 14}


def test_strategy_pair_is_absent_when_an_arm_is_missing(tmp_path):
    doc, _ = _replay_doc(tmp_path)
    for block in doc["columns"].values():
        block["arms"].pop(R.ARM_CIO_HOLD)
    assert H.measure_strategy_pair(doc)["kind"] == "absent"


def _manifest(tmp: Path, slo: float | None) -> None:
    arch = tmp / "architecture"
    arch.mkdir(exist_ok=True)
    rows = [] if slo is None else [{"path": "data/" + H.LIVE_ARTIFACT_REL, "slo_hours": slo}]
    (arch / "manifest.json").write_text(json.dumps({"artifacts": rows}), encoding="utf-8")


def _live_artifact(ddir: Path, age_hours: float) -> None:
    stamp = (NOW - dt.timedelta(hours=age_hours)).isoformat()
    (ddir / H.LIVE_ARTIFACT_REL).write_text(json.dumps(
        {"generated_at": stamp, "overall": "CRITICAL", "population": {"common_scored_days": 7}}), encoding="utf-8")


def test_freshness_fresh_and_stale_against_the_declared_slo(tmp_path):
    ddir = tmp_path / "data"
    ddir.mkdir()
    _manifest(tmp_path, 9.0)
    _live_artifact(ddir, 2.0)
    fr = H.measure_freshness(str(tmp_path), str(ddir), now=NOW)
    assert fr["kind"] == "fresh" and fr["age_hours"] == 2.0 and fr["slo_hours"] == 9.0
    assert fr["live_common_scored_days"] == 7
    _live_artifact(ddir, 20.0)
    assert H.measure_freshness(str(tmp_path), str(ddir), now=NOW)["kind"] == "stale"


def test_freshness_absent_and_unmeasured_are_distinct(tmp_path):
    ddir = tmp_path / "data"
    ddir.mkdir()
    _manifest(tmp_path, 9.0)
    assert H.measure_freshness(str(tmp_path), str(ddir), now=NOW)["kind"] == "absent"
    _live_artifact(ddir, 2.0)
    _manifest(tmp_path, None)
    fr = H.measure_freshness(str(tmp_path), str(ddir), now=NOW)
    assert fr["kind"] == UNMEASURED and "не объявлен" in fr["reason"] and fr["age_hours"] == 2.0


def test_freshness_unparseable_stamp_is_unmeasured(tmp_path):
    ddir = tmp_path / "data"
    ddir.mkdir()
    _manifest(tmp_path, 9.0)
    (ddir / H.LIVE_ARTIFACT_REL).write_text(json.dumps({"generated_at": "вчера"}), encoding="utf-8")
    fr = H.measure_freshness(str(tmp_path), str(ddir), now=NOW)
    assert fr["kind"] == UNMEASURED and "не разобран" in fr["reason"]


# ───────────────────────────── run: сборка и находки ──────────────────────────

def _stand(tmp_path, **kw):
    ddir = _write_history(tmp_path, _history(kw.pop("n_days", 14), **kw))
    _manifest(tmp_path, 9.0)
    card = _card(tmp_path, _good_card_text())
    return ddir, card


def test_run_on_a_growing_stand_has_no_critical_population_and_writes_nothing(tmp_path):
    ddir, card = _stand(tmp_path)
    doc = H.run(root=str(tmp_path), data_dir=str(ddir), card_path=card, write=False, now=NOW)
    codes = {f["code"] for f in doc["findings"]}
    assert "comparison_window_cannot_grow" not in codes and "replay_refuses_its_own_claim" not in codes
    assert "risk_adjusted_return_not_computed" in codes
    assert {f["axis"] for f in doc["findings"] if f["code"] == "axis_partial"} == {"Risk Events", "False Rebalances"}
    assert "live_artifact_absent" in codes
    assert doc["overall"] == "CRITICAL" and doc["unmeasured"] == []
    assert doc["applied"] is False and doc["generated_at"] == NOW.isoformat()
    assert not (tmp_path / H.REPORT_REL).exists()


def test_run_names_a_frozen_window_as_critical(tmp_path):
    ddir, card = _stand(tmp_path, n_days=30, drop_b_after=8)
    doc = H.run(root=str(tmp_path), data_dir=str(ddir), card_path=card, write=False, now=NOW)
    f = [f for f in doc["findings"] if f["code"] == "comparison_window_cannot_grow"]
    assert len(f) == 1 and B in f[0]["detail"] and "по построению" in f[0]["detail"]
    assert any(f["code"] == "replay_refuses_its_own_claim" for f in doc["findings"])


def test_run_carries_the_replay_findings_as_info_not_as_its_own(tmp_path):
    ddir, card = _stand(tmp_path)
    doc = H.run(root=str(tmp_path), data_dir=str(ddir), card_path=card, write=False, now=NOW)
    carried = [f for f in doc["findings"] if f["code"].startswith("replay.")]
    assert all(f["severity"] == "INFO" and f["carried_from"].startswith("cio_shadow_replay") for f in carried)


def test_run_write_true_puts_the_artifact_where_declared(tmp_path):
    ddir, card = _stand(tmp_path)
    H.run(root=str(tmp_path), data_dir=str(ddir), card_path=card, write=True, now=NOW)
    assert (tmp_path / H.REPORT_REL).exists()


def test_run_without_a_history_is_unchecked_and_names_it(tmp_path):
    (tmp_path / "data").mkdir()
    card = _card(tmp_path, _good_card_text())
    doc = H.run(root=str(tmp_path), data_dir=str(tmp_path / "data"), card_path=card, write=False, now=NOW)
    assert doc["replay"]["measured"] is False
    assert any("реплей не прогнан" in u for u in doc["unmeasured"])
    assert all(r["kind"] == UNMEASURED for r in doc["axes"].values())
    assert doc["population"]["kind"] == UNMEASURED and doc["goal"]["kind"] == UNMEASURED


def test_run_parity_mismatch_is_critical(tmp_path):
    ddir, _ = _stand(tmp_path)
    card = _card(tmp_path, _good_card_text().replace("\nGas\n", "\nPetrol\n"))
    doc = H.run(root=str(tmp_path), data_dir=str(ddir), card_path=card, write=False, now=NOW)
    assert any(f["code"] == "owner_section_drifted" and "Petrol" in f["detail"] for f in doc["findings"])


def test_run_stale_live_artifact_is_a_warning_with_the_known_cause(tmp_path):
    ddir, card = _stand(tmp_path)
    _live_artifact(ddir, 200.0)
    doc = H.run(root=str(tmp_path), data_dir=str(ddir), card_path=card, write=False, now=NOW)
    f = [f for f in doc["findings"] if f["code"] == "live_artifact_stale"]
    assert len(f) == 1 and "decision_loop" in f[0]["detail"]


def test_declared_vocabularies_are_closed_and_printed(tmp_path):
    ddir, card = _stand(tmp_path)
    doc = H.run(root=str(tmp_path), data_dir=str(ddir), card_path=card, write=False, now=NOW)
    d = doc["declared"]
    assert d["axes"] == list(H.OWNER_AXES) and d["axes_declared"] == 9
    assert set(doc["axes_tally"]) == set(H.AXIS_KINDS)
    assert {r["block"] for r in d["future_readers_by_right"]} == {"false_rebalances", "missed_opportunities"}
    assert d["order_g971_named"] == {"axes": 9, "strategies": 2, "tail_read": True}


def test_parse_now_rejects_empty_and_garbage():
    assert H.parse_now(None) == (None, None)
    assert H.parse_now("")[1] and "пуст" in H.parse_now("")[1]
    assert H.parse_now("вчера")[1] and "не разобран" in H.parse_now("вчера")[1]
    v, why = H.parse_now("2026-01-01T00:00:00Z")   # FROZEN-DATE-OK: injected-clock — литерал есть ПРЕДМЕТ разбора --now, часы не спрашиваются
    assert why is None and v.tzinfo is not None


def test_main_exit_codes(tmp_path, capsys):
    ddir, card = _stand(tmp_path)
    rc = H.main(["--root", str(tmp_path), "--data-dir", str(ddir), "--card", card, "--now", NOW.isoformat(), "--no-write"])
    out = capsys.readouterr().out
    assert rc == 1 and "§38" in out and "оси владельца" in out
    assert H.main(["--root", str(tmp_path), "--now", ""]) == 2


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


def test_probe_is_unmeasured_without_a_history(tmp_path):
    (tmp_path / H.CARD_REL).parent.mkdir(parents=True)
    (tmp_path / H.CARD_REL).write_text(_good_card_text(), encoding="utf-8")
    (tmp_path / "data").mkdir()
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(tmp_path / "data"))
    assert status == CA.UNMEASURED and "реплей не прогнан" in why


def _probe_stand(tmp_path, **kw):
    ddir = _write_history(tmp_path, _history(kw.pop("n_days", 14), **kw))
    _manifest(tmp_path, 9.0)
    (tmp_path / H.CARD_REL).parent.mkdir(parents=True)
    (tmp_path / H.CARD_REL).write_text(_good_card_text(), encoding="utf-8")
    return ddir


def test_probe_is_not_satisfied_on_the_real_replay_and_names_the_points(tmp_path):
    ddir = _probe_stand(tmp_path)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED
    assert "ось Risk Events" in why and "ось False Rebalances" in why and "цель" in why
    assert "популяция" not in why   # на растущем стенде популяция не в счёте


def test_probe_names_a_frozen_population(tmp_path):
    ddir = _probe_stand(tmp_path, n_days=30, drop_b_after=8)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED and "cannot_grow" in why and "вывод реплея" in why


def _all_good(monkeypatch):
    monkeypatch.setattr(H, "measure_axes", lambda _doc: {a: {"kind": "carried", "field": list(H.AXIS_FIELDS[a])}
                                                        for a in H.OWNER_AXES})
    monkeypatch.setattr(H, "measure_goal", lambda _doc: {"kind": "computed", "keys": ["charged.sharpe"]})


def test_probe_is_satisfied_only_when_every_axis_is_carried_and_the_goal_is_computed(tmp_path, monkeypatch):
    ddir = _probe_stand(tmp_path)
    _all_good(monkeypatch)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.SATISFIED, why
    assert "все 9 осей" in why and "способна расти" in why


def test_probe_is_not_satisfied_when_a_scene_leaks(tmp_path, monkeypatch):
    ddir = _probe_stand(tmp_path)
    _all_good(monkeypatch)
    monkeypatch.setitem(H.LOOKAHEAD_SCENES, "scored_by_tomorrow",
                        lambda: {"name": "scored_by_tomorrow", "holds": False, "torn_holds": False,
                                 "kind": "leaks", "tear_kind": "discriminates"})
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED and "look-ahead scored_by_tomorrow" in why


def test_probe_is_unmeasured_when_a_scene_does_not_discriminate(tmp_path, monkeypatch):
    ddir = _probe_stand(tmp_path)
    _all_good(monkeypatch)
    monkeypatch.setitem(H.LOOKAHEAD_SCENES, "scored_by_tomorrow",
                        lambda: {"name": "scored_by_tomorrow", "holds": True, "torn_holds": True,
                                 "kind": "causal", "tear_kind": "indiscriminate"})
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.UNMEASURED and "look-ahead scored_by_tomorrow" in why


def test_probe_is_not_satisfied_while_the_replay_refuses_its_claim(tmp_path, monkeypatch):
    ddir = _probe_stand(tmp_path, n_days=8)   # 7 общих дней < порога реплея, но рука тени оценена
    _all_good(monkeypatch)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED and "вывод реплея" in why and "популяция" not in why
