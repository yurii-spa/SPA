# FROZEN-DATE-OK: даты — синтетические фикстуры истории, обе стороны сравнения запинены; логика модуля часы не читает (generated_at — только метаданные-штамп).
"""Y3 (ADR-055/ADR-060 tooling): accumulator + shadow-vs-fact evaluator.

Two properties carry the arming decision and therefore get the hard tests:
(1) the verdict history can never lie by duplication, silent loss, or a
    corrupt-line wipe — it is the ONLY durable record of the shadow's word;
(2) the evaluator's counterfactual is hand-checkable arithmetic, and every
    data hole surfaces as UNCHECKED, never as a made-up number.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.paper_trading import allocation_rationale as ar
from spa_core.paper_trading import shadow_trigger_eval as ste
from spa_core.paper_trading.allocation_rationale import (
    HISTORY_FILENAME,
    append_rationale_history,
    build_history_record,
    write_shadow_rationale,
)
from spa_core.paper_trading.shadow_trigger_eval import (
    EVAL_FILENAME,
    evaluate_window,
    format_summary,
    load_history,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
BOOK = {"morpho_steakhouse": 40_000.0, "maple": 20_000.0, "pendle": 20_000.0,
        "compound_v3": 5_000.0}
APY = {"morpho_steakhouse": 3.4657, "maple": 5.1097, "pendle": 13.9419,
       "compound_v3": 3.2984}
SRC = {k: "live" for k in APY}
CAPITAL = 100_000.0


def _rec(date: str, **kw) -> dict:
    r = {"schema": "shadow-hist-v1", "cycle_date": date, "verdict": "HOLD",
         "reasons": [], "capital_usd": CAPITAL, "current_positions": {},
         "target_positions": {}, "apy_evidenced_pct": {}, "cost_usd": 0.0}
    r.update(kw)
    return r


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ═══════════════════════ accumulator ═══════════════════════


def test_append_is_idempotent_by_run_not_by_date(tmp_path: Path) -> None:
    """Повторная запись ТОГО ЖЕ прогона не двоит; ДРУГОЙ прогон дня остаётся.

    ⚠️ **Тест изменён намеренно** (инв. #16 CLAUDE.md: не молча, с обоснованием).
    Прежняя редакция звалась ``test_append_is_idempotent_by_date`` и требовала
    ОДНОЙ строки на день — то есть закрепляла ровно то правило, которое владелец
    велел снять ([ADR-392] решение 3, вариант A; исполнение — [ADR-395]).
    Цена прежнего правила измерена: ADR-314 — 206 прогонов вне журнала на
    17 днях (худший день: 36 прогонов и одна строка); ADR-383 — единственный ACT
    за сорок дней стёрт повторным прогоном того же дня.

    Защитная суть теста НЕ ослаблена, а сужена до своего предмета: двойной счёт
    по-прежнему запрещён, но единицей стал ПРОГОН (``cycle_date`` +
    ``generated_at``), а не календарный день. Обе половины проверяются здесь,
    иначе «починка» выродилась бы в дописывание всегда.
    """
    p = tmp_path / HISTORY_FILENAME
    early = "2026-08-01T09:00:00+00:00"
    late = "2026-08-01T23:00:00+00:00"
    # тот же прогон дважды ⇒ ОДНА строка, побеждает последняя запись
    append_rationale_history(
        _rec("2026-08-01", generated_at=early, verdict="HOLD"), tmp_path)
    append_rationale_history(
        _rec("2026-08-01", generated_at=early, verdict="ACT"), tmp_path)
    lines = _lines(p)
    assert len(lines) == 1
    assert json.loads(lines[0])["verdict"] == "ACT"
    # ДРУГОЙ прогон того же дня ⇒ вторая строка, первая цела
    append_rationale_history(
        _rec("2026-08-01", generated_at=late, verdict="HOLD"), tmp_path)
    lines = _lines(p)
    assert len(lines) == 2
    assert [json.loads(ln)["verdict"] for ln in lines] == ["ACT", "HOLD"]
    append_rationale_history(
        _rec("2026-08-02", generated_at="2026-08-02T23:00:00+00:00"), tmp_path)
    dates = [json.loads(ln)["cycle_date"] for ln in _lines(p)]
    assert dates == ["2026-08-01", "2026-08-01", "2026-08-02"]  # order preserved


def test_append_keeps_an_unidentified_run_rather_than_erasing_a_sibling(
        tmp_path: Path) -> None:
    """Прогон БЕЗ ``generated_at`` дописывается и не удаляет соседа по дню.

    Выбор несимметричен намеренно ([ADR-395]): стирание необратимо, а двойная
    строка видна и измерима. Обратная ветка («нет ключа ⇒ заменяем по дате»)
    вернула бы дефект ADR-314/383, и вернула бы его МОЛЧА. Инвариант #17:
    отсутствие наблюдения имеет своё представление, а не подставляется чужим.
    """
    p = tmp_path / HISTORY_FILENAME
    append_rationale_history(
        _rec("2026-08-01", generated_at="2026-08-01T09:00:00+00:00",
             verdict="ACT"), tmp_path)
    append_rationale_history(_rec("2026-08-01", verdict="HOLD"), tmp_path)
    lines = _lines(p)
    assert len(lines) == 2, "неопознанный прогон СТЁР опознанного соседа"
    assert [json.loads(ln)["verdict"] for ln in lines] == ["ACT", "HOLD"]


def test_append_preserves_corrupt_and_foreign_lines(tmp_path: Path) -> None:
    """The accumulator may drop nothing it did not write this call."""
    p = tmp_path / HISTORY_FILENAME
    corrupt = '{"cycle_date": "2026-07-30", broken json'
    p.write_text(corrupt + "\n" + json.dumps(_rec("2026-07-31")) + "\n",
                 encoding="utf-8")
    append_rationale_history(_rec("2026-08-01"), tmp_path)
    lines = _lines(p)
    assert lines[0] == corrupt          # unreadable ≠ deletable, byte-for-byte
    assert json.loads(lines[1])["cycle_date"] == "2026-07-31"
    assert json.loads(lines[2])["cycle_date"] == "2026-08-01"


def test_append_caps_at_max_lines(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ar, "HISTORY_MAX_LINES", 5)
    for i in range(1, 8):
        append_rationale_history(_rec(f"2026-07-{i:02d}"), tmp_path)
    lines = _lines(tmp_path / HISTORY_FILENAME)
    assert len(lines) == 5
    assert json.loads(lines[0])["cycle_date"] == "2026-07-03"  # oldest dropped


def test_writer_appends_one_history_line_per_cycle(tmp_path: Path) -> None:
    """Integration: write_shadow_rationale feeds the accumulator, idempotently."""
    kw = dict(data_dir=tmp_path, current_positions=BOOK, target_positions=BOOK,
              apy_pct=APY, apy_sources=SRC, capital_usd=CAPITAL,
              cycle_date="2026-08-02", run_ts=NOW.isoformat(), now=NOW)
    write_shadow_rationale(**kw)
    write_shadow_rationale(**kw)  # same-date re-run
    lines = _lines(tmp_path / HISTORY_FILENAME)
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["cycle_date"] == "2026-08-02"
    assert row["verdict"] in ("ACT", "HOLD")
    assert row["apy_evidenced_pct"] == APY          # all sources are "live"
    assert row["current_positions"] == BOOK
    assert row["capital_usd"] == CAPITAL


def test_writer_write_false_leaves_no_history(tmp_path: Path) -> None:
    write_shadow_rationale(
        data_dir=tmp_path, current_positions=BOOK, target_positions=BOOK,
        apy_pct=APY, apy_sources=SRC, capital_usd=CAPITAL,
        cycle_date="2026-08-02", run_ts=NOW.isoformat(), now=NOW, write=False)
    assert not (tmp_path / HISTORY_FILENAME).exists()


def test_history_record_prices_only_evidenced_protocols() -> None:
    doc = {"cycle_date": "2026-08-02", "generated_at": "x",
           "decision_shadow": {"decision": "HOLD", "reasons": ["r"]}}
    rec = build_history_record(
        doc, apy_pct=APY, apy_sources={**SRC, "maple": "fallback_stale"},
        current_positions=BOOK, target_positions=BOOK, capital_usd=CAPITAL)
    assert "maple" not in rec["apy_evidenced_pct"]
    assert rec["apy_unevidenced"] == ["maple"]


# ═══════ CIO oversight phase F: Investment Decision Object ═══════
#
# decision_id / policy_version / mode / legs / gates — none of these are new
# computation, they only make already-computed identity and rationale part of
# the durable ledger instead of the overwritten-every-cycle rationale file.


def test_decision_id_is_deterministic_and_dated() -> None:
    doc = {"cycle_date": "2026-08-02", "generated_at": "x",
           "decision_shadow": {"decision": "HOLD"}}
    rec = build_history_record(
        doc, apy_pct=APY, apy_sources=SRC,
        current_positions=BOOK, target_positions=BOOK, capital_usd=CAPITAL)
    assert rec["decision_id"] == "adr060-shadow-2026-08-02"


def test_decision_id_is_none_without_a_cycle_date() -> None:
    """Never raises on a missing key — an unidentifiable decision stays None,
    it does not fabricate an id out of the string "None"."""
    doc = {"generated_at": "x", "decision_shadow": {"decision": "HOLD"}}
    rec = build_history_record(
        doc, apy_pct=APY, apy_sources=SRC,
        current_positions=BOOK, target_positions=BOOK, capital_usd=CAPITAL)
    assert rec["decision_id"] is None


def test_policy_identity_flows_from_params_into_the_ledger() -> None:
    doc = {"cycle_date": "2026-08-02", "generated_at": "x",
           "decision_shadow": {"decision": "ACT"},
           "params": {"policy_version": "v1.0", "mode": "pilot"}}
    rec = build_history_record(
        doc, apy_pct=APY, apy_sources=SRC,
        current_positions=BOOK, target_positions=BOOK, capital_usd=CAPITAL)
    assert rec["policy_version"] == "v1.0"
    assert rec["mode"] == "pilot"


def test_policy_identity_is_unchecked_not_fabricated_without_params() -> None:
    doc = {"cycle_date": "2026-08-02", "generated_at": "x",
           "decision_shadow": {"decision": "HOLD"}}  # no "params" key at all
    rec = build_history_record(
        doc, apy_pct=APY, apy_sources=SRC,
        current_positions=BOOK, target_positions=BOOK, capital_usd=CAPITAL)
    assert rec["policy_version"] is None
    assert rec["mode"] is None


def test_legs_and_gates_are_the_ledgers_alternative_record() -> None:
    """legs/gates are the honest reading of 'considered and rejected
    alternatives' — the trigger evaluates one proposed move per cycle, and
    `gates` names exactly which criterion accepted or rejected it."""
    doc = {"cycle_date": "2026-08-02", "generated_at": "x",
           "decision_shadow": {
               "decision": "HOLD",
               "legs": [{"protocol": "maple", "delta_usd": 5000.0,
                         "direction": "increase"}],
               "gates": {"gain_above_band": False, "payback_within_horizon": True},
           }}
    rec = build_history_record(
        doc, apy_pct=APY, apy_sources=SRC,
        current_positions=BOOK, target_positions=BOOK, capital_usd=CAPITAL)
    assert rec["legs"] == [{"protocol": "maple", "delta_usd": 5000.0,
                            "direction": "increase"}]
    assert rec["gates"] == {"gain_above_band": False, "payback_within_horizon": True}


def test_legs_and_gates_default_to_empty_not_missing() -> None:
    doc = {"cycle_date": "2026-08-02", "generated_at": "x",
           "decision_shadow": {"decision": "HOLD"}}
    rec = build_history_record(
        doc, apy_pct=APY, apy_sources=SRC,
        current_positions=BOOK, target_positions=BOOK, capital_usd=CAPITAL)
    assert rec["legs"] == []
    assert rec["gates"] == {}


def test_history_schema_bumped_for_the_new_fields() -> None:
    assert ar.HISTORY_SCHEMA == "shadow-hist-v2"


def test_full_writer_stamps_the_history_line_with_the_investment_decision_fields(
        tmp_path: Path) -> None:
    """End-to-end: write_shadow_rationale → JSONL line carries phase F fields,
    sourced from the SAME params object that decided the verdict."""
    write_shadow_rationale(
        data_dir=tmp_path, current_positions=BOOK, target_positions=BOOK,
        apy_pct=APY, apy_sources=SRC, capital_usd=CAPITAL,
        cycle_date="2026-08-02", run_ts=NOW.isoformat(), now=NOW)
    lines = _lines(tmp_path / HISTORY_FILENAME)
    row = json.loads(lines[0])
    assert row["decision_id"] == "adr060-shadow-2026-08-02"
    # ИЗМЕНЕНО НАМЕРЕННО (ADR-357, инв. #16): предмет не тронут — строка истории
    # обязана НЕСТИ версию контракта. Сменилось число: ответ владельца 12.09
    # добавил две ручки, контракт требует новой версии при изменении порогов.
    # ИЗМЕНЕНО НАМЕРЕННО (ADR-972, инв. #16): тот же предмет, новое число — ответ
    # владельца 27.10 добавил две ручки срока/свежести, версия контракта v1.2.
    assert row["policy_version"] == "v1.2"
    assert row["mode"] == "paper"
    assert "legs" in row and "gates" in row


# ═══════════════════════ evaluator: hand-checked arithmetic ═══════════════════
#
# Timeline d01..d10, capital $100k, APYs constant: A = 2 %, B = 8 %, C never
# priced. Moving $50k A→B earns 50 000·0.06/365 = $8.2192/day; over a 7-day
# horizon $57.5342.


def _seed_timeline(tmp_path: Path) -> None:
    apy = {"A": 2.0, "B": 8.0}
    rows = [
        # d01: ACT that PAID — benefit 57.53, cost 10 ⇒ net +47.53 ⇒ hit
        _rec("2026-07-01", verdict="ACT", cost_usd=10.0,
             current_positions={"A": 100_000.0},
             target_positions={"A": 50_000.0, "B": 50_000.0},
             apy_evidenced_pct=apy),
        # d02: ACT that did NOT pay — $10k leg: 10 000·0.06/365·7 = 11.51,
        # cost 50 ⇒ net −38.49 ⇒ miss
        _rec("2026-07-02", verdict="ACT", cost_usd=50.0,
             current_positions={"A": 100_000.0},
             target_positions={"A": 90_000.0, "B": 10_000.0},
             apy_evidenced_pct=apy),
        # d03: HOLD that MISSED the same $50k move (net +47.53) ⇒ miss
        _rec("2026-07-03", verdict="HOLD", cost_usd=10.0,
             reasons=["cooldown"],
             current_positions={"A": 100_000.0},
             target_positions={"A": 50_000.0, "B": 50_000.0},
             apy_evidenced_pct=apy),
        # d04: trivial HOLD (no proposal) ⇒ hit, excluded from hit-rate
        _rec("2026-07-04", verdict="HOLD",
             current_positions={"A": 100_000.0},
             target_positions={"A": 100_000.0},
             apy_evidenced_pct=apy),
        # d05: HOLD proposing a move into NEVER-PRICED C ⇒ UNCHECKED, not a guess
        _rec("2026-07-05", verdict="HOLD",
             current_positions={"A": 100_000.0},
             target_positions={"A": 80_000.0, "C": 20_000.0},
             apy_evidenced_pct=apy),
    ]
    # ADR-067: владелец поднял порог наблюдения до 30 дней — тихие дни растянуты
    # d06..d31 (26 шт), counterfactual-утверждения не изменены (инв. 16, журнал W32)
    for i in range(6, 31):  # d06..d30: quiet days supplying forward APYs
        rows.append(_rec(f"2026-07-{i:02d}", verdict="HOLD",
                         current_positions={"A": 100_000.0},
                         target_positions={"A": 100_000.0},
                         apy_evidenced_pct=apy))
    # d31: material ACT on the LAST day, no recorded cost ⇒ assumption cost,
    # no forward data ⇒ UNCHECKED (был d10; сдвинут в хвост при растяжке окна
    # до порога ADR-067 — смысл «последний день без форвардов» сохранён)
    rows.append(_rec("2026-07-31", verdict="ACT", cost_usd=None,
                     current_positions={"A": 100_000.0},
                     target_positions={"A": 90_000.0, "B": 10_000.0},
                     apy_evidenced_pct=apy))
    for r in rows:
        append_rationale_history(r, tmp_path)


def test_evaluator_matches_hand_computed_counterfactuals(tmp_path: Path) -> None:
    _seed_timeline(tmp_path)
    doc = evaluate_window(tmp_path, write=True)
    by_date = {r["cycle_date"]: r for r in doc["per_verdict"]}

    act_hit = by_date["2026-07-01"]
    assert act_hit["outcome"] == "hit"
    assert act_hit["forward_days_checked"] == 7
    assert act_hit["benefit_usd_over_checked_days"] == pytest.approx(57.53, abs=0.01)
    assert act_hit["net_usd"] == pytest.approx(47.53, abs=0.01)
    assert act_hit["cost_source"] == "recorded"

    act_miss = by_date["2026-07-02"]
    assert act_miss["outcome"] == "miss"
    assert act_miss["net_usd"] == pytest.approx(-38.49, abs=0.01)

    hold_missed = by_date["2026-07-03"]
    assert hold_missed["outcome"] == "miss"
    assert hold_missed["missed_usd"] == pytest.approx(47.53, abs=0.01)

    trivial = by_date["2026-07-04"]
    assert trivial["outcome"] == "hit" and trivial["trivial"] is True

    unpriced = by_date["2026-07-05"]
    assert unpriced["outcome"] == "UNCHECKED"
    assert unpriced["unchecked_reason"] == "no_evidenced_apy_for_moved_legs"
    assert unpriced["unpriced_protocols"] == ["C"]

    last = by_date["2026-07-31"]
    assert last["outcome"] == "UNCHECKED"
    assert last["unchecked_reason"] == "no_forward_data"
    # turnover $10k ⇒ 15 bps assumption = $15, labelled as such
    assert last["cost_usd_used"] == pytest.approx(15.0, abs=0.01)
    assert last["cost_source"].startswith("assumption:")

    # Aggregates: scored = {d01 hit, d02 miss, d03 miss} ⇒ hit-rate 1/3;
    # following the ACTs nets 47.53 − 38.49 = $9.04 = 0.9 bps of $100k.
    # hold: d03+d04+d05 + 25 тихих (d06..d30) = 28; trivial: d04 + 25 = 26
    # (растяжка окна до порога ADR-067; scored/unchecked не изменились)
    assert doc["counts"] == {"act": 3, "hold": 28, "trivial_hold": 26,
                             "scored": 3, "unchecked": 2,
                             "corrupt_history_lines": 0}
    assert doc["hit_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert doc["net_usd_if_followed"] == pytest.approx(9.04, abs=0.01)
    assert doc["net_bps_if_followed"] == pytest.approx(0.9, abs=0.01)
    assert doc["hold_missed_usd_total"] == pytest.approx(47.53, abs=0.01)

    # 31 день наблюдения (ADR-067: порог 30), но лишь 3 scored ⇒ hit-rate
    # criterion UNCHECKED ⇒ fail-closed NOT_READY.
    assert doc["status"] == "NOT_READY" and doc["ready_to_arm"] is False
    st = {c["criterion"]: c["status"] for c in doc["criteria"]}
    assert st["observation_days"] == "PASS"
    assert st["hit_rate"] == "UNCHECKED"
    assert st["net_bps_if_followed"] == "PASS"

    assert (tmp_path / EVAL_FILENAME).exists()
    on_disk = json.loads((tmp_path / EVAL_FILENAME).read_text(encoding="utf-8"))
    assert on_disk["status"] == "NOT_READY"


def test_all_criteria_pass_makes_ready(tmp_path: Path) -> None:
    """5 scored ACT hits over 31 days ⇒ READY (positive control, пороги ADR-067)."""
    apy = {"A": 2.0, "B": 8.0}
    for i in range(1, 6):  # d01..d05: five paying ACTs
        append_rationale_history(
            _rec(f"2026-07-{i:02d}", verdict="ACT", cost_usd=10.0,
                 current_positions={"A": 100_000.0},
                 target_positions={"A": 50_000.0, "B": 50_000.0},
                 apy_evidenced_pct=apy), tmp_path)
    # ADR-067: порог наблюдения 30 дней — тихий хвост растянут до d31 (инв. 16)
    for i in range(6, 32):  # d06..d31: quiet forward days
        append_rationale_history(
            _rec(f"2026-07-{i:02d}", verdict="HOLD",
                 current_positions={"A": 100_000.0},
                 target_positions={"A": 100_000.0},
                 apy_evidenced_pct=apy), tmp_path)
    doc = evaluate_window(tmp_path, write=False)
    assert doc["hit_rate"] == 1.0
    assert doc["net_bps_if_followed"] > 0
    assert all(c["status"] == "PASS" for c in doc["criteria"])
    assert doc["status"] == "READY" and doc["ready_to_arm"] is True


def test_undersized_window_is_not_ready(tmp_path: Path) -> None:
    for i in range(1, 4):  # only 3 observed days
        append_rationale_history(_rec(f"2026-08-{i:02d}"), tmp_path)
    doc = evaluate_window(tmp_path, write=False)
    assert doc["observation_days"] == 3
    days = next(c for c in doc["criteria"] if c["criterion"] == "observation_days")
    assert days["status"] == "FAIL"
    assert doc["status"] == "NOT_READY"


def test_no_scored_act_keeps_payoff_unchecked(tmp_path: Path) -> None:
    """An all-HOLD week must NOT read as proof the trigger pays (fail-closed)."""
    for i in range(1, 9):
        append_rationale_history(
            _rec(f"2026-08-{i:02d}", verdict="HOLD",
                 current_positions={"A": 100_000.0},
                 target_positions={"A": 100_000.0},
                 apy_evidenced_pct={"A": 2.0}), tmp_path)
    doc = evaluate_window(tmp_path, write=False)
    net = next(c for c in doc["criteria"] if c["criterion"] == "net_bps_if_followed")
    assert net["status"] == "UNCHECKED"
    assert doc["status"] == "NOT_READY"


def test_missing_target_is_a_data_hole_not_a_liquidation(tmp_path: Path) -> None:
    """A log-reconstructed line without the proposed book must go UNCHECKED —
    pricing it as 'sell everything' would fabricate a counterfactual."""
    append_rationale_history(
        _rec("2026-08-01", verdict="HOLD",
             current_positions={"A": 100_000.0}, target_positions={},
             apy_evidenced_pct={"A": 2.0}), tmp_path)
    append_rationale_history(
        _rec("2026-08-02", apy_evidenced_pct={"A": 2.0},
             current_positions={"A": 100_000.0},
             target_positions={"A": 100_000.0}), tmp_path)
    doc = evaluate_window(tmp_path, write=False)
    row = doc["per_verdict"][0]
    assert row["outcome"] == "UNCHECKED"
    assert row["unchecked_reason"] == "no_target_recorded"


def test_equity_curve_cross_check_is_attached(tmp_path: Path) -> None:
    append_rationale_history(
        _rec("2026-08-01", apy_evidenced_pct={"A": 2.0},
             current_positions={"A": 100_000.0},
             target_positions={"A": 100_000.0}), tmp_path)
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps(
        {"daily": [{"date": "2026-08-01", "apy_today": 6.01}]}), encoding="utf-8")
    doc = evaluate_window(tmp_path, write=False)
    assert doc["per_verdict"][0]["book_apy_equity_pct"] == 6.01


# ═══════════════════════ robustness: nothing here may break the cycle ═════════


def test_evaluator_survives_empty_dir_and_writes_not_ready(tmp_path: Path) -> None:
    doc = evaluate_window(tmp_path, write=True)
    assert doc["status"] == "NOT_READY"
    assert doc["observation_days"] == 0
    assert (tmp_path / EVAL_FILENAME).exists()


def test_evaluator_counts_corrupt_lines_instead_of_dying(tmp_path: Path) -> None:
    (tmp_path / HISTORY_FILENAME).write_text(
        "garbage\n" + json.dumps(_rec("2026-08-01")) + "\n[1,2]\n", encoding="utf-8")
    records, bad = load_history(tmp_path)
    assert len(records) == 1 and bad == 2
    doc = evaluate_window(tmp_path, write=False)
    assert doc["counts"]["corrupt_history_lines"] == 2


def test_cycle_hook_is_guarded_and_after_rationale() -> None:
    """The Step-2g hook exists, sits AFTER the shadow write, and is fail-open."""
    src = Path(ste.__file__).parents[1].joinpath("paper_trading", "cycle_runner.py") \
        .read_text(encoding="utf-8")
    imp = src.index(
        "from spa_core.paper_trading.shadow_trigger_eval import evaluate_window")
    assert src.index("write_shadow_rationale(") < imp  # history first, eval second
    assert "Y3 shadow-eval skipped" in src             # except-branch: fail-open
    # the import is inside the guarded block, not module-level
    assert src.rfind("try:", 0, imp) > src.index("write_shadow_rationale(")


def test_format_summary_is_printable(tmp_path: Path) -> None:
    _seed_timeline(tmp_path)
    text = format_summary(evaluate_window(tmp_path, write=False))
    assert "NOT_READY" in text and "Критерии включения" in text


# ── book scoping: load_history reads the SAME file the writer routed to ───────


def test_load_history_without_book_id_is_unaffected_by_scoping(tmp_path: Path) -> None:
    """Every pre-existing caller of load_history() calls it with no book_id —
    that must keep reading the original filename exactly as before."""
    append_rationale_history(_rec("2026-08-01"), tmp_path)
    records, bad = load_history(tmp_path)
    assert len(records) == 1 and bad == 0


def test_load_history_with_book_id_reads_that_books_own_file(tmp_path: Path) -> None:
    write_shadow_rationale(
        data_dir=tmp_path, current_positions=BOOK, target_positions=BOOK,
        apy_pct=APY, apy_sources=SRC, capital_usd=CAPITAL,
        cycle_date="2026-08-02", run_ts=NOW.isoformat(), now=NOW,
        book_id="balanced")
    conservative_records, _ = load_history(tmp_path)
    balanced_records, _ = load_history(tmp_path, book_id="balanced")
    assert conservative_records == []          # writer never touched this file
    assert len(balanced_records) == 1
    assert balanced_records[0]["book_id"] == "balanced"


def test_load_history_for_a_book_with_no_ledger_yet_is_empty_not_an_error(
        tmp_path: Path) -> None:
    """A book whose cycle has never run (or never called the writer) must
    read as an empty, valid history — not raise, not silently read a
    DIFFERENT book's file."""
    write_shadow_rationale(
        data_dir=tmp_path, current_positions=BOOK, target_positions=BOOK,
        apy_pct=APY, apy_sources=SRC, capital_usd=CAPITAL,
        cycle_date="2026-08-02", run_ts=NOW.isoformat(), now=NOW,
        book_id="balanced")
    records, bad = load_history(tmp_path, book_id="aggressive")
    assert records == [] and bad == 0


# ═════════════ §31 приказа «Portfolio CIO»: ПЯТЬ горизонтов (ADR-1071) ═════════
#
# Владелец объявил горизонты дословно (1h · 6h · 24h · 3d · 7d) и четыре
# величины, которые на каждом надо пересчитать. До цикла #1214 судья считал на
# ОДНОМ горизонте. Сцена ниже — ручной счёт, и она же показывает, зачем
# короткий горизонт нужен: разовая цена хода одна и та же, а выгода набегает
# со временем, поэтому ОДИН И ТОТ ЖЕ совет меняет исход между 24h и 3d.

_H0 = "2026-07-01T00:00:00+00:00"
_HAPY = {"A": 2.0, "B": 8.0}          # спред 6 пп в пользу B


def _hrec(stamp: str, **kw) -> dict:
    r = {"schema": "shadow-hist-v2", "cycle_date": stamp[:10], "verdict": "HOLD",
         "generated_at": stamp, "reasons": [], "capital_usd": CAPITAL,
         "current_positions": {}, "target_positions": {},
         "apy_evidenced_pct": dict(_HAPY), "cost_usd": 0.0}
    r.update(kw)
    return r


def _hscene() -> list[dict]:
    """T0 с материальным HOLD и форвардные наблюдения в +2ч, +30ч, +80ч.

    Ручной счёт: Δ_A = −50 000, Δ_B = +50 000 ⇒ выгода за СУТКИ
    ``(−50 000·2 + 50 000·8)/100/365 = 8.219178`` $/день; цена записана $10.
    """
    return [
        _hrec(_H0, cost_usd=10.0,
              current_positions={"A": 100_000.0},
              target_positions={"A": 50_000.0, "B": 50_000.0}),
        _hrec("2026-07-01T02:00:00+00:00"),
        _hrec("2026-07-02T06:00:00+00:00"),   # +30 ч
        _hrec("2026-07-04T08:00:00+00:00"),   # +80 ч
    ]


def test_horizon_1h_without_a_forward_observation_is_unchecked_not_zero() -> None:
    """Внутри часа наблюдений нет ⇒ UNCHECKED с НАЗВАННОЙ причиной, не ноль."""
    scene = _hscene()
    row = ste._evaluate_over_hours(scene[0], ste._forward_within(
        [(ste._run_time(r), r) for r in scene], ste._run_time(scene[0]), 1.0), 1.0)
    assert row["outcome"] == "UNCHECKED"
    assert row["unchecked_reason"] == "no_forward_observation"
    assert "net_usd" not in row and "benefit_usd" not in row


def test_horizon_6h_counts_only_the_observed_slice_and_names_the_tail() -> None:
    """Выгода считается по НАБЛЮДЁННОЙ доле окна, остаток назван, не домыслен."""
    scene = _hscene()
    timed = [(ste._run_time(r), r) for r in scene]
    row = ste._evaluate_over_hours(scene[0],
                                   ste._forward_within(timed, ste._run_time(scene[0]), 6.0),
                                   6.0)
    # Один ломоть 2 ч = 2/24 дня: 8.219178 · 0.0833333 = 0.684932
    assert row["benefit_usd"] == 0.68
    assert row["net_usd"] == -9.32              # 0.684932 − 10
    assert row["outcome"] == "hit"              # HOLD верен: ход не окупился
    assert row["observed_hours"] == 2.0 and row["uncovered_hours"] == 4.0
    assert row["coverage_pct"] == 33.33
    # Годовой спред, наблюдённый на перемещённом объёме, — РОВНО 6 пп.
    assert row["opportunity_apy_pct"] == 6.0


def test_the_same_advice_flips_between_24h_and_3d_which_is_why_horizons_exist() -> None:
    """Разовая цена одна, выгода набегает: до суток HOLD верен, к трём дням — нет."""
    scene = _hscene()
    timed = [(ste._run_time(r), r) for r in scene]
    t0 = ste._run_time(scene[0])
    day = ste._evaluate_over_hours(scene[0], ste._forward_within(timed, t0, 24.0), 24.0)
    three = ste._evaluate_over_hours(scene[0], ste._forward_within(timed, t0, 72.0), 72.0)
    week = ste._evaluate_over_hours(scene[0], ste._forward_within(timed, t0, 168.0), 168.0)
    assert day["net_usd"] == -9.32 and day["outcome"] == "hit"
    assert three["net_usd"] == 0.27 and three["outcome"] == "miss"
    assert three["missed_usd"] == 0.27
    assert week["net_usd"] == 17.4 and week["outcome"] == "miss"
    # Цена РАЗОВАЯ и одинакова на всех горизонтах — иначе короткий горизонт
    # выглядел бы дешевле, и «когда ход окупается» было бы не измерить.
    assert day["cost_usd_used"] == three["cost_usd_used"] == week["cost_usd_used"] == 10.0


def test_an_observation_beyond_the_window_does_not_close_its_tail() -> None:
    """Наблюдение ЗА границей окна хвост НЕ закрывает (вторая редакция #1214).

    Иначе часовое окно без наблюдений внутри закрывалось бы ставкой, снятой
    через тридцать часов, — интерполяция под видом замера.
    """
    scene = _hscene()
    timed = [(ste._run_time(r), r) for r in scene]
    t0 = ste._run_time(scene[0])
    assert ste._forward_within(timed, t0, 1.0) == []
    assert len(ste._forward_within(timed, t0, 6.0)) == 1
    # Покрытие НИ НА ОДНОМ горизонте не выдаётся за полное.
    for hours in (6.0, 24.0, 72.0, 168.0):
        row = ste._evaluate_over_hours(scene[0], ste._forward_within(timed, t0, hours), hours)
        assert row["coverage_pct"] < 100.0
        assert row["counterfactual"] == "PARTIAL"


def test_trivial_and_timeless_records_are_named_separately() -> None:
    """Три разных исхода не схлопываются в один (инв. #17).

    Проверяется НЕ только причина, но и ВЕРДИКТ: мутация, оставившая причину
    «no_run_time» и назвавшая запись тривиально верным HOLD, выжила в прогоне
    №1 (#1214) — причина без вердикта вердикта не держит.
    """
    timeless = _hrec(_H0, cost_usd=10.0,
                     current_positions={"A": 100_000.0},
                     target_positions={"A": 50_000.0, "B": 50_000.0})
    timeless.pop("generated_at")
    row = ste._evaluate_over_hours(timeless, [], 24.0)
    assert row["unchecked_reason"] == "no_run_time"
    assert row["outcome"] == "UNCHECKED" and row["counterfactual"] == "UNCHECKED"
    assert row["trivial"] is False and "net_usd" not in row
    trivial = _hrec(_H0, current_positions={"A": 100.0}, target_positions={"A": 100.0})
    trow = ste._evaluate_over_hours(trivial, [], 24.0)
    assert trow["counterfactual"] == "TRIVIAL" and trow["trivial"] is True
    hole = _hrec(_H0, current_positions={"A": 100_000.0}, target_positions={})
    hrow = ste._evaluate_over_hours(hole, [], 24.0)
    assert hrow["unchecked_reason"] == "no_target_recorded"
    assert hrow["outcome"] == "UNCHECKED" and hrow["trivial"] is False


def test_a_recorded_zero_cost_is_a_price_not_a_missing_price() -> None:
    """Дверь цены (ADR-392/393) держит оба плеча в СВОЁМ файле.

    Контроль этого правила в наборе был — но у ЧУЖОГО читателя
    (`test_criterion_sign_price.py`), поэтому мутация `if cost_rec:` выжила в
    прогоне №1 (#1214): правило переехало в дверь `_cost_used`, а контроль
    остался у соседа. Дверь и её контроль живут вместе.
    """
    zero = _hrec(_H0, cost_usd=0.0)
    rec, used, source = ste._cost_used(zero, 50_000.0)
    assert (rec, used, source) == (0.0, 0.0, "recorded")   # ноль ЗАПИСАН ⇒ он и есть цена
    absent = _hrec(_H0)
    absent.pop("cost_usd")
    rec2, used2, source2 = ste._cost_used(absent, 50_000.0)
    assert rec2 is None and source2.startswith("assumption:") and used2 > 0.0
    junk = _hrec(_H0, cost_usd="дорого")
    rec3, _, source3 = ste._cost_used(junk, 50_000.0)
    assert rec3 is None and source3.startswith("assumption:")


def test_horizon_rollups_judge_only_the_records_of_the_window() -> None:
    """Свод горизонта судит ПОДДАННЫХ окна, а форварды берёт из ВСЕГО журнала.

    Сцена РАЗЛИЧАЮЩАЯ: подданных меньше, чем записей журнала. Без неё мутация
    «судить всех» не меняет ничего и выживает (прогон №1, #1214).
    """
    scene = _hscene()
    keys = {ste._rec_key(scene[0])}
    section, rows = ste.horizon_census(
        scene, legacy_horizon_days=7, legacy_hit_rate=None, legacy_net_usd=None,
        subject_keys=keys)
    assert section["subjects"] == 1 and len(rows) == 1
    assert section["horizons"]["7d"]["population_material"] == 1
    # Форвардные наблюдения при этом НЕ обрезаны окном подданных.
    assert section["horizons"]["7d"]["with_forward_observation"] == 1
    whole, rows_all = ste.horizon_census(
        scene, legacy_horizon_days=7, legacy_hit_rate=None, legacy_net_usd=None)
    assert whole["subjects"] == 4 and len(rows_all) == 4


def test_horizon_vocabulary_has_ONE_door_and_a_third_outcome(monkeypatch) -> None:
    """Пять чисел владельца ВВОЗЯТСЯ; «не ввезены» — причина, не своя копия."""
    from spa_core.analytics import counterfactual_tracking_census as ctc
    hours, why = ste.declared_horizons()
    assert why is None and hours == {k: int(v) for k, v in ctc.HORIZON_HOURS.items()}
    import sys
    import spa_core.analytics as analytics_pkg
    monkeypatch.setitem(sys.modules,
                        "spa_core.analytics.counterfactual_tracking_census", None)
    monkeypatch.delattr(analytics_pkg, "counterfactual_tracking_census", raising=False)
    hours2, why2 = ste.declared_horizons()
    assert hours2 is None and "не ввезён" in why2
    # Второй третий исход того же двери: словарь ввезён, но УСЕЧЁН — ответ
    # «НЕ ИЗМЕРЕНО», а не счёт по неполному перечню требований владельца.
    monkeypatch.undo()
    monkeypatch.setattr(ctc, "HORIZON_HOURS", {"1h": 1}, raising=True)
    hours3, why3 = ste.declared_horizons()
    assert hours3 is None and "при объявленных 5" in why3


def test_horizon_section_is_not_an_input_to_arming(tmp_path: Path) -> None:
    """Секция горизонтов НЕ меняет мандат владельца (ADR-067) ни одним числом."""
    _seed_timeline(tmp_path)
    full = evaluate_window(tmp_path, write=False, now=NOW)
    sec = full["counterfactual_horizons"]
    assert sec["measured"] is True and len(sec["horizons"]) == 5
    assert "НЕ входят в ready_to_arm" in sec["not_an_arming_input"]
    # Тот же прогон с ОТНЯТОЙ секцией: ни одно число мандата не шевельнулось.
    import spa_core.paper_trading.shadow_trigger_eval as mod
    real = mod.horizon_census
    monkey = lambda *a, **k: ({"measured": False, "reason": "сцена"}, {})  # noqa: E731
    mod.horizon_census = monkey
    try:
        bare = evaluate_window(tmp_path, write=False, now=NOW)
    finally:
        mod.horizon_census = real
    for key in ("ready_to_arm", "status", "hit_rate", "net_usd_if_followed",
                "net_bps_if_followed", "criteria", "counts", "observation_days",
                "hold_missed_usd_total"):
        assert bare[key] == full[key], key
    bare_rows = [{k: v for k, v in r.items() if k != "horizons"}
                 for r in bare["per_verdict"]]
    full_rows = [{k: v for k, v in r.items() if k != "horizons"}
                 for r in full["per_verdict"]]
    assert bare_rows == full_rows


def test_horizon_rows_are_attached_by_run_identity_not_by_date(tmp_path: Path) -> None:
    """Два прогона ОДНОГО дня получают РАЗНЫЕ строки горизонтов, не одну."""
    for rec in (_hrec("2026-07-01T00:00:00+00:00", cost_usd=10.0,
                      current_positions={"A": 100_000.0},
                      target_positions={"A": 50_000.0, "B": 50_000.0}),
                _hrec("2026-07-01T20:00:00+00:00", cost_usd=10.0,
                      current_positions={"A": 100_000.0},
                      target_positions={"A": 90_000.0, "B": 10_000.0}),
                _hrec("2026-07-02T06:00:00+00:00")):
        append_rationale_history(rec, tmp_path)
    doc = evaluate_window(tmp_path, write=False, now=NOW)
    rows = [r for r in doc["per_verdict"] if r["cycle_date"] == "2026-07-01"]
    assert len(rows) == 2
    assert rows[0]["horizons"] != rows[1]["horizons"]
