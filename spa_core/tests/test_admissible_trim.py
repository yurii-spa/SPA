#!/usr/bin/env python3
"""ADR-850 — предложение урезается до допустимого РАЗМЕРА хода, и это ПРОВОДКА.

Каждый тест ниже — положительный контроль на РЕАЛЬНОЕ поведение живых функций
(`admissible_trim.apply_admissible_trim`, `rebalance_economics.evaluate`,
`risk_gate._apply_risk_policy_gate`, настоящий `run_cycle` в песочнице), а не на
формулировки записи. Контроль в ОБЕ стороны: у каждого утверждения есть сцена,
где ответ обязан быть противоположным.

Что здесь измеряется, а что НЕТ:

* измеряется — что урезанный ход закрывает ровно потолки РАЗМЕРА
  (`move_amount_ok`, `move_turnover_ok`) у настоящего `evaluate()`; что цель
  заменяется ТОЛЬКО с одобрения той же RiskPolicy; что де-риск, первичное
  размещение и вложение кэша не урезаются НИКОГДА; что цикл судит УРЕЗАННУЮ
  цель (сквозной прогон); что строка без поля — третий исход, а не ноль;
* НЕ измеряется — наступит ли `ACT` на живой истории: это вопрос наблюдения
  вперёд, и приёмка карточки стои́т на `counts.act >= 1` в
  `data/shadow_trigger_evaluation.json`, а не на этом файле.

FROZEN-DATE-OK: injected-clock — единственный якорь времени ``_NOW`` уходит
параметром ``now=`` в :func:`run_cycle`, :func:`write_shadow_rationale` и
:func:`apply_admissible_trim`; стенных часов ни один тест не спрашивает.
"""
from __future__ import annotations

import json
import logging
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from spa_core.allocator.rebalance_economics import TriggerParams, evaluate
from spa_core.paper_trading import admissible_trim as AT
from spa_core.paper_trading.admissible_size import admissible_turnover_usd

CAP = 100_000.0
# FROZEN-DATE-OK: injected-clock — якорь уходит параметром now= в вызовы ниже.
_NOW = datetime(2026, 6, 18, 8, 0, tzinfo=timezone.utc)
_ANCHOR = date(2026, 6, 10)

#: Сцена острой записи ADR-848 (`2026-10-02`): перекладка $40 000 при потолке
#: $15 000 — отказывали ТОЛЬКО потолки размера.
_HELD = {"compound_v3": 40_000.0, "maple": 20_000.0, "fluid_fusdc": 20_000.0,
         "morpho_blue_base": 10_000.0, "aave_v3": 5_000.0}
_TARGET_BIG = {"compound_v3": 0.0, "maple": 20_000.0, "fluid_fusdc": 20_000.0,
               "morpho_blue_base": 50_000.0, "aave_v3": 5_000.0}

_APY = {"compound_v3": 3.0, "maple": 4.0, "fluid_fusdc": 4.3,
        "morpho_blue_base": 7.0, "aave_v3": 3.2}


def _approving_gate(target, capital, adapters, ddir=None, current_positions=None):
    """Дверь RiskPolicy, которая ОДОБРЯЕТ ровно поданную книгу."""
    return {"approved": True, "error": None, "violations": [], "warnings": [],
            "trimmed": False, "target_usd": dict(target), "tvl_unverified": []}


def _refusing_gate(target, capital, adapters, ddir=None, current_positions=None):
    """Та же дверь, отказывающая. Контроль «ответ приходит ИЗ двери»."""
    return {"approved": False, "error": None, "violations": ["morpho_blue_base: cap"],
            "warnings": [], "trimmed": False, "target_usd": dict(target),
            "tvl_unverified": []}


def _trim(target, held=None, *, gate=_approving_gate, notes=None, **kw):
    return AT.apply_admissible_trim(
        target,
        current_positions=dict(_HELD if held is None else held),
        capital_usd=CAP,
        notes=notes if notes is not None else [],
        adapters=[],
        ddir=None,
        trades=[],
        now=_NOW,
        policy_gate=gate,
        **kw,
    )


def _gates(current, target):
    """Гейты НАСТОЯЩЕГО `evaluate()` для пары книг — без подстановок."""
    d = evaluate(
        current_positions=dict(current), target_positions=dict(target),
        apy_pct=dict(_APY), evidenced=set(_APY), chains={}, capital_usd=CAP,
        params=TriggerParams.for_mode("paper"),
        days_since_last_act=None, position_age_days={},
        turnover_last_week_usd=0.0, turnover_today_usd=0.0,
        last_move_legs=None, days_since_last_move=None,
        tvl_evidenced=set(_APY),
    )
    return d


# ══════════════════════════════════════════════════════════════════════════════
# 1. Предмет: ход, отказанный ТОЛЬКО размером, после урезания размер проходит
# ══════════════════════════════════════════════════════════════════════════════


class TheCutClosesExactlyTheSizeCaps(unittest.TestCase):
    def test_the_full_proposal_is_refused_by_size_and_only_by_size(self):
        """Сцена — положительный контроль: без неё урезать было бы нечего."""
        d = _gates(_HELD, _TARGET_BIG)
        self.assertFalse(d.gates["move_amount_ok"],
                         "сцена обязана упираться в потолок суммы хода")
        self.assertFalse(d.gates["move_turnover_ok"])
        self.assertGreater(d.turnover_usd, admissible_turnover_usd(CAP, TriggerParams.for_mode("paper")))

    def test_the_cut_proposal_passes_the_size_caps(self):
        cut, rec = _trim(_TARGET_BIG)
        self.assertEqual(rec["verdict"], AT.TRIM_APPLIED, rec)
        d = _gates(_HELD, cut)
        self.assertTrue(d.gates["move_amount_ok"],
                        f"урезанный ход ${d.turnover_usd} обязан пройти потолок суммы")
        self.assertTrue(d.gates["move_turnover_ok"])
        self.assertLessEqual(d.turnover_usd,
                             admissible_turnover_usd(CAP, TriggerParams.for_mode("paper")) + 0.01)

    def test_no_owner_threshold_is_weakened_by_the_cut(self):
        """Потолки, которыми судят урезанный ход, — те же числа ADR-357/060 §3."""
        p = TriggerParams.for_mode("paper")
        _, rec = _trim(_TARGET_BIG)
        self.assertEqual(rec["caps"]["max_trade_usd"], 15_000.0)
        self.assertEqual(rec["caps"]["max_turnover_per_move"], 0.15)
        self.assertEqual(rec["admissible_usd"], min(0.15 * CAP, p.max_trade_usd))

    def test_the_cut_book_lies_between_the_held_book_and_the_target(self):
        """Допустимость урезанной книги держится ОТРЕЗКОМ, а не числом выигрыша."""
        cut, _ = _trim(_TARGET_BIG)
        for proto in set(_HELD) | set(_TARGET_BIG):
            held = _HELD.get(proto, 0.0)
            tgt = _TARGET_BIG.get(proto, 0.0)
            got = cut.get(proto, 0.0)
            self.assertGreaterEqual(got, min(held, tgt) - 0.01, proto)
            self.assertLessEqual(got, max(held, tgt) + 0.01, proto)
        self.assertAlmostEqual(sum(cut.values()), sum(_HELD.values()), delta=1.0,
                               msg="урезание не создаёт и не теряет денег")

    def test_the_cut_keeps_the_direction_of_every_leg(self):
        """Урезание не разворачивает ни одну ногу — иначе это другой ход."""
        cut, _ = _trim(_TARGET_BIG)
        for proto in set(_HELD) | set(_TARGET_BIG):
            full = _TARGET_BIG.get(proto, 0.0) - _HELD.get(proto, 0.0)
            part = cut.get(proto, 0.0) - _HELD.get(proto, 0.0)
            if abs(full) > 1.0:
                self.assertGreaterEqual(full * part, -0.01, proto)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Чего шаг НЕ трогает: предложение внутри потолков, де-риск, размещение кэша
# ══════════════════════════════════════════════════════════════════════════════


class WhatTheStepNeverTouches(unittest.TestCase):
    def test_a_proposal_already_within_the_caps_is_returned_unchanged(self):
        small = dict(_HELD)
        small["compound_v3"] -= 5_000.0
        small["morpho_blue_base"] += 5_000.0
        out, rec = _trim(small)
        self.assertEqual(rec["verdict"], AT.TRIM_NOT_NEEDED, rec)
        self.assertEqual(rec["k"], 1.0)
        self.assertEqual(out, small, "цель внутри потолков обязана вернуться той же")

    def test_a_pure_derisk_is_never_cut(self):
        """Де-риск не ждёт никогда — урезать его значило бы задержать защиту."""
        derisk = {p: v * 0.4 for p, v in _HELD.items()}
        out, rec = _trim(derisk)
        self.assertEqual(rec["verdict"], AT.TRIM_NOT_A_RESHUFFLE, rec)
        self.assertEqual(out, derisk)

    def test_an_initial_placement_of_an_empty_book_is_never_cut(self):
        out, rec = _trim(dict(_HELD), held={})
        self.assertEqual(rec["verdict"], AT.TRIM_NOT_A_RESHUFFLE, rec)
        self.assertEqual(out, dict(_HELD))

    def test_deploying_idle_cash_is_never_cut(self):
        """ADR-055: простой капитала запрещён, значит вложение кэша не урезается."""
        held = {"compound_v3": 20_000.0}
        target = {"compound_v3": 20_000.0, "morpho_blue_base": 60_000.0}
        out, rec = _trim(target, held=held)
        self.assertEqual(rec["verdict"], AT.TRIM_NOT_A_RESHUFFLE, rec)
        self.assertEqual(out, target)

    def test_nothing_material_to_move_is_its_own_verdict(self):
        out, rec = _trim(dict(_HELD))
        self.assertIn(rec["verdict"], (AT.TRIM_NOTHING_TO_MOVE, AT.TRIM_NOT_A_RESHUFFLE), rec)
        self.assertEqual(out, dict(_HELD))


# ══════════════════════════════════════════════════════════════════════════════
# 3. RiskPolicy судит урезанную книгу — и ответ приходит ИЗ ДВЕРИ
# ══════════════════════════════════════════════════════════════════════════════


class TheSameRiskPolicyJudgesTheCutBook(unittest.TestCase):
    def test_a_refusing_policy_keeps_the_untouched_target(self):
        notes: list[str] = []
        out, rec = _trim(_TARGET_BIG, gate=_refusing_gate, notes=notes)
        self.assertEqual(rec["verdict"], AT.TRIM_REFUSED_BY_POLICY, rec)
        self.assertEqual(out, _TARGET_BIG, "отказ политики ⇒ поведение дня не меняется")
        self.assertTrue(any("admissible_trim" in n for n in notes),
                        "отказ обязан быть НАЗВАН в заметках цикла")

    def test_the_answer_comes_from_the_door_not_from_a_copy_of_the_rule_here(self):
        """Одна сцена, две противоположные двери — два противоположных ответа."""
        yes, rec_yes = _trim(_TARGET_BIG, gate=_approving_gate)
        no, rec_no = _trim(_TARGET_BIG, gate=_refusing_gate)
        self.assertNotEqual(rec_yes["verdict"], rec_no["verdict"])
        self.assertNotEqual(yes, no)

    def test_a_gate_error_is_not_an_approval(self):
        """Сцена отдаёт ТУ ЖЕ урезанную книгу — иначе отказ придёт от соседа.

        Первая редакция возвращала здесь полную цель, и вторая защита (оборот
        выше потолка) закрывала сцену вместо проверяемой. Мутационный замер
        #969 это и показал: мутант «ошибка гейта читается как одобрение» ВЫЖИЛ.
        """
        def _broken(target, capital, adapters, ddir=None, current_positions=None):
            return {"approved": True, "error": "RiskPolicyUnavailable",
                    "violations": [], "target_usd": dict(target)}

        out, rec = _trim(_TARGET_BIG, gate=_broken)
        self.assertEqual(rec["verdict"], AT.TRIM_REFUSED_BY_POLICY, rec)
        self.assertEqual(out, _TARGET_BIG)

    def test_a_raising_gate_is_a_third_outcome_with_a_named_reason(self):
        def _raises(*a, **kw):
            raise RuntimeError("gate down")

        out, rec = _trim(_TARGET_BIG, gate=_raises)
        self.assertEqual(rec["verdict"], AT.TRIM_UNMEASURED, rec)
        self.assertIn("RuntimeError", rec["why"])
        self.assertEqual(out, _TARGET_BIG)

    def test_a_gate_that_hands_back_an_oversized_book_is_refused(self):
        """Гейт вправе подрезать книгу сам — но его вывод обязан остаться в потолке."""
        def _reexpands(target, capital, adapters, ddir=None, current_positions=None):
            return {"approved": True, "error": None, "violations": [], "warnings": [],
                    "trimmed": True, "target_usd": dict(_TARGET_BIG), "tvl_unverified": []}

        out, rec = _trim(_TARGET_BIG, gate=_reexpands)
        self.assertEqual(rec["verdict"], AT.TRIM_REFUSED_BY_POLICY, rec)
        self.assertEqual(out, _TARGET_BIG)

    def test_the_real_risk_policy_door_is_the_default(self):
        """Умолчание — настоящая дверь Step 2b, а не одобряющая заглушка."""
        adapters = [{"protocol": p, "id": p, "apy_pct": _APY[p], "tvl_usd": 1e8,
                     "tvl_source": "live", "tier": "T1" if p in ("aave_v3", "compound_v3")
                     else "T2", "status": "ok", "chain": f"chain_{p}"}
                    for p in _APY]
        out, rec = AT.apply_admissible_trim(
            dict(_TARGET_BIG), current_positions=dict(_HELD), capital_usd=CAP,
            notes=[], adapters=adapters, ddir=None, trades=[], now=_NOW)
        # Какой бы вердикт настоящая политика ни дала, он ОБЯЗАН быть назван и
        # измерен — «молча как было» запрещено.
        self.assertIn(rec["verdict"], (AT.TRIM_APPLIED, AT.TRIM_REFUSED_BY_POLICY), rec)
        self.assertIn("policy", rec)
        if rec["verdict"] == AT.TRIM_APPLIED:
            self.assertLessEqual(
                AT._turnover(_HELD, out, CAP, TriggerParams.for_mode("paper").min_leg_frac),
                admissible_turnover_usd(CAP, TriggerParams.for_mode("paper")) + 0.01)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Третий исход: «не измерено» никогда не выдаётся за «не урезано»
# ══════════════════════════════════════════════════════════════════════════════


class UnmeasuredIsItsOwnOutcome(unittest.TestCase):
    def test_no_capital_is_unmeasured_not_zero(self):
        out, rec = AT.apply_admissible_trim(
            dict(_TARGET_BIG), current_positions=dict(_HELD), capital_usd=0.0,
            notes=[], adapters=[], ddir=None, trades=[], now=_NOW,
            policy_gate=_approving_gate)
        self.assertEqual(rec["verdict"], AT.TRIM_UNMEASURED)
        self.assertTrue(rec["why"])
        self.assertEqual(out, _TARGET_BIG)

    def test_an_unclassified_move_is_unmeasured_and_the_target_is_untouched(self):
        def _raises(*a, **kw):
            raise ValueError("damper down")

        out, rec = _trim(_TARGET_BIG, damper_decide=_raises)
        self.assertEqual(rec["verdict"], AT.TRIM_UNMEASURED, rec)
        self.assertIn("ValueError", rec["why"])
        self.assertEqual(out, _TARGET_BIG)

    def test_the_census_counts_a_record_without_the_field_separately(self):
        from spa_core.paper_trading.shadow_trigger_eval import live_trim_census

        census = live_trim_census([
            {"cycle_date": "2026-10-01", "verdict": "HOLD"},                     # до ADR-850
            {"cycle_date": "2026-10-02", "verdict": "HOLD",
             "admissible_trim": {"verdict": AT.TRIM_APPLIED, "k": 0.375,
                                 "turnover_full_usd": 40_000.0,
                                 "turnover_final_usd": 15_000.0}},
            {"cycle_date": "2026-10-03", "verdict": "HOLD",
             "admissible_trim": {"verdict": AT.TRIM_NOT_NEEDED}},
        ])
        self.assertEqual(census["records"], 3)
        self.assertEqual(census["records_without_field"], 1)
        self.assertEqual(census["counts"][AT.TRIM_APPLIED], 1)
        self.assertEqual(census["counts"][AT.TRIM_NOT_NEEDED], 1)
        self.assertEqual(census["last_applied"]["date"], "2026-10-02")

    def test_the_printer_says_unmeasured_when_there_is_no_census(self):
        self.assertIn("НЕ ИЗМЕРЕНО", " ".join(AT.format_live_trim(None)))
        self.assertIn("НЕ ИЗМЕРЕНО", " ".join(AT.format_live_trim({})))
        lines = " ".join(AT.format_live_trim(
            {"records": 2, "records_without_field": 1,
             "counts": {AT.TRIM_APPLIED: 1},
             "last_applied": {"date": "2026-10-02", "k": 0.375,
                              "turnover_full_usd": 40_000.0,
                              "turnover_final_usd": 15_000.0}}))
        self.assertNotIn("НЕ ИЗМЕРЕНО", lines)
        self.assertIn("2026-10-02", lines)


# ══════════════════════════════════════════════════════════════════════════════
# 5. ПРОВОДКА: документ советника и запись истории несут провенанс хода
# ══════════════════════════════════════════════════════════════════════════════


class TheRecordCarriesTheProvenanceOfTheMove(unittest.TestCase):
    def test_the_rationale_document_and_the_history_line_both_carry_the_trim(self):
        import tempfile

        from spa_core.paper_trading.allocation_rationale import (
            history_filename,
            write_shadow_rationale,
        )

        cut, rec = _trim(_TARGET_BIG)
        with tempfile.TemporaryDirectory() as td:
            doc = write_shadow_rationale(
                data_dir=Path(td), current_positions=dict(_HELD),
                target_positions=cut, apy_pct=dict(_APY),
                apy_sources={p: "live" for p in _APY}, capital_usd=CAP,
                cycle_date="2026-10-02", run_ts=_NOW.isoformat(),
                trades=[], now=_NOW, write=True, admissible_trim=rec)
            self.assertEqual((doc.get("admissible_trim") or {}).get("verdict"),
                             AT.TRIM_APPLIED, doc.get("admissible_trim"))
            line = json.loads(
                (Path(td) / history_filename("conservative")).read_text(
                    encoding="utf-8").strip().splitlines()[-1])
            self.assertEqual((line.get("admissible_trim") or {}).get("verdict"),
                             AT.TRIM_APPLIED,
                             "запись истории обязана нести провенанс урезания")
            self.assertEqual(line["turnover_usd"], rec["turnover_final_usd"],
                             "судимый оборот — оборот УРЕЗАННОГО хода")

    def test_a_call_without_the_trim_leaves_the_field_absent_not_false(self):
        import tempfile

        from spa_core.paper_trading.allocation_rationale import write_shadow_rationale

        with tempfile.TemporaryDirectory() as td:
            doc = write_shadow_rationale(
                data_dir=Path(td), current_positions=dict(_HELD),
                target_positions=dict(_HELD), apy_pct=dict(_APY),
                apy_sources={p: "live" for p in _APY}, capital_usd=CAP,
                cycle_date="2026-10-02", run_ts=_NOW.isoformat(),
                trades=[], now=_NOW, write=False)
            self.assertIsNone(doc.get("admissible_trim"),
                              "«шаг не звали» обязано отличаться от «не урезано»")


# ══════════════════════════════════════════════════════════════════════════════
# 6. СКВОЗНОЙ контроль: цикл судит УРЕЗАННУЮ цель, а не предложение аллокатора
# ══════════════════════════════════════════════════════════════════════════════

_UNIVERSE = [("compound_v3", "T1"), ("aave_v3", "T1"), ("maple", "T2"),
             ("fluid_fusdc", "T2"), ("morpho_blue_base", "T2")]


def _make_orch(universe):
    def _orch(_data_dir):  # noqa: ANN001 — matches orchestrator_fn signature
        return SimpleNamespace(
            adapters=[{"protocol": p, "id": p, "apy_pct": _APY.get(p, 4.0),
                       "tvl_usd": 1e8, "tvl_source": "live", "tier": t,
                       "status": "ok", "chain": f"chain_{p}"} for p, t in universe],
            status="ok", data_freshness="live")
    return _orch


def _make_alloc(target_usd):
    class _Alloc:
        def allocate(self):  # noqa: D401 — fake
            return SimpleNamespace(
                target_usd=dict(target_usd),
                target_weights={p: v / CAP for p, v in target_usd.items()},
                expected_apy_pct=4.0, model_used="risk_adjusted",
                strategy_loop_active=False)
    return _Alloc()


#: Сцена сквозного прогона: перекладка ВНУТРИ T1 на $20 000 при потолке $15 000.
#: Обе книги — и стоящая, и целевая — проходят RiskPolicy сами (потолки тира,
#: сумма T2, буфер кэша), иначе сквозной контроль мерил бы не урезание, а
#: несоответствие сцены политике.
_HELD_E2E = {"compound_v3": 35_000.0, "aave_v3": 5_000.0, "maple": 20_000.0,
             "fluid_fusdc": 15_000.0, "morpho_blue_base": 10_000.0}
_TARGET_E2E_BIG = {**_HELD_E2E, "compound_v3": 15_000.0, "aave_v3": 25_000.0}
_TARGET_E2E_SMALL = {**_HELD_E2E, "compound_v3": 30_000.0, "aave_v3": 10_000.0}


@pytest.fixture(autouse=True)
def _hermetic_side_cars(monkeypatch):
    """Заглушаются ТОЛЬКО сторонние писатели в живое `data/` и транспорт Telegram.

    Ни одна проверяемая функция не подменяется: шаг урезания, RiskPolicy,
    `evaluate()` и советник работают настоящие. Без этих заглушек прогон пишет
    в git-tracked `data/adapter_status.json`, `gap_monitor.json`,
    `risk_alerts.json`, `apy_milestone_log.json` — их писатели держат путь
    КОНСТАНТОЙ модуля и песочницу `data_dir` не видят (сторож
    `tracked_write_guard`; дописывать его базу запрещено, инв. #16).
    """
    from spa_core.telegram import push_policy

    monkeypatch.setattr(push_policy, "_send", lambda text: True)

    from spa_core.analytics import apy_milestone_tracker as _amt
    from spa_core.milestone import milestone_tracker as _mt
    from spa_core.monitoring import adapter_status_generator as _asg
    from spa_core.paper_trading import gap_monitor as _gm

    monkeypatch.setattr(_asg, "run_and_write", lambda *a, **kw: None)
    monkeypatch.setattr(_gm, "check_gaps", lambda *a, **kw: None)
    monkeypatch.setattr(_mt, "check_milestone",
                        lambda *a, **kw: SimpleNamespace(consecutive_days=0,
                                                         progress_pct=0.0,
                                                         milestone_reached=False))

    class _NoopTracker:
        def record_day(self, *a, **kw):
            return None

    monkeypatch.setattr(_amt, "ApyMilestoneTracker", _NoopTracker)


def _run_sandbox(tmp_path: Path, target: dict, held: dict):
    from spa_core.paper_trading import cycle_runner as _cr
    from spa_core.paper_trading._cycle_io import EQUITY_FILENAME, POSITIONS_FILENAME
    from spa_core.tests._measured_inputs import write_measured_red_flags

    td = tmp_path / "data"
    td.mkdir(parents=True, exist_ok=True)
    (td / POSITIONS_FILENAME).write_text(
        json.dumps({"positions": held, "cash_usd": CAP - sum(held.values())}),
        encoding="utf-8")
    (td / EQUITY_FILENAME).write_text(json.dumps({
        "source": "cycle_runner",
        "daily": [{"date": date.fromordinal(_ANCHOR.toordinal() + i).isoformat(),
                   "close_equity": CAP, "open_equity": CAP} for i in range(8)],
    }), encoding="utf-8")
    write_measured_red_flags(td, _NOW)
    logging.disable(logging.CRITICAL)
    try:
        _cr.run_cycle(data_dir=str(td), now=_NOW,
                      orchestrator_fn=_make_orch(_UNIVERSE),
                      allocator=_make_alloc(target),
                      risk_scorer_fn=lambda d: None,
                      track_persister_fn=lambda d: None,
                      write=True, allow_live_write=False)
    finally:
        logging.disable(logging.NOTSET)
    return json.loads((td / "allocation_rationale.json").read_text(encoding="utf-8"))


def test_the_cycle_judges_the_cut_target_not_the_allocators_proposal(tmp_path):
    """Сквозной контроль проводки: вердикт обязан судить ТОТ ход, что будет сделан."""
    doc = _run_sandbox(tmp_path, _TARGET_E2E_BIG, dict(_HELD_E2E))
    trim = doc.get("admissible_trim") or {}
    assert trim.get("verdict") == AT.TRIM_APPLIED, trim
    judged = float((doc.get("decision_shadow") or {}).get("turnover_usd") or 0.0)
    cap = admissible_turnover_usd(CAP, TriggerParams.for_mode("paper"))
    assert judged <= cap + 0.01, (
        f"вердикт судил ${judged:,.2f} при потолке ${cap:,.2f} — цель не урезана")
    gates = (doc.get("decision_shadow") or {}).get("gates") or {}
    assert gates.get("move_amount_ok") is True, gates


def test_the_cycle_leaves_an_admissible_proposal_untouched(tmp_path):
    """Обратная сторона: ход внутри потолков цикл не трогает вовсе."""
    doc = _run_sandbox(tmp_path, _TARGET_E2E_SMALL, dict(_HELD_E2E))
    trim = doc.get("admissible_trim") or {}
    assert trim.get("verdict") == AT.TRIM_NOT_NEEDED, trim
    assert trim.get("k") == 1.0, trim


# ══════════════════════════════════════════════════════════════════════════════
# 7. Проба приёмки карточки — контроль в обе стороны на НАСТОЯЩЕМ реестре
# ══════════════════════════════════════════════════════════════════════════════


class TheAcceptanceProbeMeasuresTheOutcome(unittest.TestCase):
    """`cio_act_fires_and_is_scored` — критерий карточки, а не наличие модуля.

    Четыре сцены, и каждая рвёт своё звено: артефакта нет · артефакт протух ·
    ACT нет · ACT есть, но НЕ оценён. Пятая — целый контур. Проба зовётся через
    НАСТОЯЩИЙ реестр (`run_probe`), иначе тест мерил бы свою копию правила.
    """

    @staticmethod
    def _tree(tmp: Path, doc) -> str:
        d = tmp / "data"
        d.mkdir(parents=True, exist_ok=True)
        if doc is not None:
            (d / "shadow_trigger_evaluation.json").write_text(
                json.dumps(doc), encoding="utf-8")
        return str(d)

    @staticmethod
    def _doc(acts, outcome, *, stamp=_NOW):
        return {
            "generated_at": stamp.isoformat(),
            "observation_days": 84,
            "net_bps_if_followed": 1.2,
            "counts": {"act": acts, "hold": 163},
            "per_verdict": ([{"cycle_date": "2026-10-02", "verdict": "ACT",
                              "outcome": outcome, "net_usd": 12.0}] if acts else
                            [{"cycle_date": "2026-10-02", "verdict": "HOLD",
                              "outcome": "UNCHECKED"}]),
        }

    def _run(self, tmp, doc, now=_NOW):
        from spa_core.monitoring.card_acceptance import PROBES

        # Реестр — предмет: имя обязано быть зарегистрировано, иначе очередь
        # не примет объявление пробы у карточки.
        self.assertIn("cio_act_fires_and_is_scored", PROBES)
        return PROBES["cio_act_fires_and_is_scored"](
            None, now=now, data_dir=self._tree(tmp, doc))

    def test_a_missing_artifact_is_unmeasured_not_a_finding(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            verdict, why = self._run(Path(td), None)
        self.assertEqual(verdict, "unmeasured")
        self.assertIn("не прочитан", why)

    def test_a_stale_artifact_is_unmeasured_the_frozen_canon_is_not_an_observation(self):
        import tempfile
        from datetime import timedelta

        with tempfile.TemporaryDirectory() as td:
            verdict, why = self._run(Path(td), self._doc(1, "hit"),
                                     now=_NOW + timedelta(hours=50))
        self.assertEqual(verdict, "unmeasured")
        self.assertIn("протух", why)

    def test_no_act_is_not_satisfied_with_the_number(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            verdict, why = self._run(Path(td), self._doc(0, None))
        self.assertEqual(verdict, "not_satisfied")
        self.assertIn("84", why)

    def test_an_unscored_act_is_not_satisfied_naming_the_outcome(self):
        """Половина критерия — не критерий: ACT, посчитанный успехом заранее."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            verdict, why = self._run(Path(td), self._doc(1, "UNCHECKED"))
        self.assertEqual(verdict, "not_satisfied")
        self.assertIn("НЕ ОЦЕНЁН", why)

    def test_a_scored_act_satisfies_the_whole_contour(self):
        import tempfile

        for outcome in ("hit", "miss"):
            with tempfile.TemporaryDirectory() as td:
                verdict, why = self._run(Path(td), self._doc(1, outcome))
            self.assertEqual(verdict, "satisfied", why)
            self.assertIn(outcome, why)

    def test_an_unparsable_count_is_unmeasured(self):
        import tempfile

        doc = self._doc(1, "hit")
        doc["counts"]["act"] = "много"
        with tempfile.TemporaryDirectory() as td:
            verdict, why = self._run(Path(td), doc)
        self.assertEqual(verdict, "unmeasured")
        self.assertIn("не разобрано", why)

    def test_the_probe_declares_the_tree_it_accepts(self):
        """Половина инъекции — та же бомба: читатель обязан узнать это у реестра."""
        from spa_core.monitoring.card_acceptance import probe_tree_inputs

        self.assertIn("data_dir", probe_tree_inputs("cio_act_fires_and_is_scored"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
