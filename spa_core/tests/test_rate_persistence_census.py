#!/usr/bin/env python3
"""Контроль переписи выживания ставки — критерий §49 `Persistence` приказа CIO.

Каждый тест здесь — либо ВОСПРОИЗВЕДЕНИЕ настоящего исхода из журналов
(`data/allocation_rationale_history.jsonl` + `data/trades.json`), либо контроль
звена в обратную сторону: порванное звено обязано КРАСНЕТЬ, и звено названо в
имени теста. Проверка, никогда не видевшая настоящей поломки, есть украшение
(`.claude/rules/deployment.md`).

Эталоны воспроизводятся дословно из замера цикла #704 на живом `data/`:

* **осевшая ставка** — 2026-08-20, цель тянула $30 000 в `compound_v3` на
  6.3637 %, вперёд за 3 дн медиана 4.3373 % (−2.03 pp), и НИ ОДНО форвардное
  наблюдение не вернулось к порогу;
* **колебание** — 2026-09-14, цель тянула $35 000 в `aave_v3` на 5.2038 %,
  вперёд 3.5666…5.2402 % (размах 1.67 pp при существенности 0.5 pp): «осела» и
  «держалась» неверны ОДИНАКОВО;
* **ставка держалась** — ход T034 (11.09), $14 737 в `maple` на 4.9643 %,
  вперёд медиана 4.9657 %;
* **не измерено** — ход T009 (24.08), $40 000 в `aave_v3`, ближайшее наблюдение
  ставки старше срока удержания (7.06 дн > 3), и ход T033 (08.09), $20 000 в
  `pendle`, у которого форвардных наблюдений внутри срока НЕТ вовсе.

# FROZEN-DATE-OK: injected-clock — все отметки сцен происходят от якоря
# `_ANCHOR` (см. `_ts`), и ОН ЖЕ передаётся прибору аргументом `now=`; ни одна
# проверка этого файла не спрашивает время у машины, поэтому сдвиг календаря
# вердикта здесь не меняет.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import rate_persistence_census as census

#: Якорь сцен. От него происходят ВСЕ отметки и он же идёт в `now=`.
_ANCHOR = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_before: float) -> str:
    """Отметка за N часов до якоря — обе стороны сцены закреплены якорем."""
    return (_ANCHOR - timedelta(hours=hours_before)).isoformat()


class _Params:
    """Колонка порогов ADR-060 §3 как ВХОД сцены, а не как живой файл."""

    def __init__(self, min_gain_pp: float = 0.50, min_hold_days: float = 3.0,
                 min_leg_frac: float = 0.005, reversal_window_days: float = 14.0,
                 mode: str = "paper", version: str = "test") -> None:
        self.min_gain_pp = min_gain_pp
        self.min_hold_days = min_hold_days
        self.min_leg_frac = min_leg_frac
        self.reversal_window_days = reversal_window_days
        self.mode = mode
        self.version = version


def _decision(hours_before: float, rates: dict, *, current: dict | None = None,
              target: dict | None = None, capital: float | None = 100000.0,
              gates: dict | None = None, reasons: list | None = None,
              verdict: str = "HOLD", as_of: dict | None = None,
              cycle_date: str | None = None) -> dict:
    row: dict = {"generated_at": _ts(hours_before),
                 "apy_evidenced_pct": rates,
                 "verdict": verdict}
    row["apy_as_of"] = {k: _ts(hours_before) for k in rates} if as_of is None else as_of
    if current is not None:
        row["current_positions"] = current
    if target is not None:
        row["target_positions"] = target
    if capital is not None:
        row["capital_usd"] = capital
    if gates is not None:
        row["gates"] = gates
    if reasons is not None:
        row["reasons"] = reasons
    if cycle_date is not None:
        row["cycle_date"] = cycle_date
    return row


def _write(tmp_path: Path, decisions: list, moves: list | None = None) -> Path:
    (tmp_path / census.DECISIONS_NAME).write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8")
    if moves is not None:
        (tmp_path / "trades.json").write_text(json.dumps(moves), encoding="utf-8")
    return tmp_path


def _move(trade_id: str, hours_before: float, frm: dict, to: dict) -> dict:
    return {"trade_id": trade_id, "ts": _ts(hours_before),
            "from_allocation": frm, "to_allocation": to}


def _run(tmp_path: Path, params: _Params | None = None) -> dict:
    return census.run_census(tmp_path, now=_ANCHOR, params=params or _Params())


# ── эталон 1: осевшая ставка тянула цель (2026-08-20, compound_v3) ──────────

def _real_faded_pull(tmp_path: Path) -> Path:
    """Цель тянет $30 000 в `compound_v3` на 6.3637 %; вперёд 4.3373 и ниже."""
    return _write(tmp_path, [
        _decision(120.0, {"compound_v3": 6.3637},
                  current={"compound_v3": 10000.0}, target={"compound_v3": 40000.0},
                  gates={"move_turnover_ok": False, "payback_within_horizon": False},
                  reasons=["payback_too_long:35.0d", "move_turnover_over_budget:30.5%>15%"],
                  cycle_date="2026-08-20"),
        _decision(96.0, {"compound_v3": 4.3373}),
        _decision(72.0, {"compound_v3": 4.4890}),
        _decision(60.0, {"compound_v3": 4.2680}),
    ])


def test_the_real_faded_pull_is_found_with_its_dollars(tmp_path):
    report = _run(_real_faded_pull(tmp_path))
    assert report["measured"] is True
    assert report["faded_pull_legs"] == 1
    assert report["faded_pull_usd"] == pytest.approx(30000.0)
    item = report["faded_pulls"][0]
    assert item["protocol"] == "compound_v3"
    assert item["decided_pp"] == pytest.approx(6.3637)
    assert item["decline_pp"] > 0.5
    assert item["forward_n"] == 3


def test_a_pull_whose_rate_holds_is_not_called_faded(tmp_path):
    """Контроль в обратную сторону: та же сцена со стоящей ставкой — НЕ находка."""
    report = _run(_write(tmp_path, [
        _decision(120.0, {"compound_v3": 4.3373},
                  current={"compound_v3": 10000.0}, target={"compound_v3": 40000.0},
                  gates={}, reasons=[], cycle_date="2026-08-20"),
        _decision(96.0, {"compound_v3": 4.3400}),
        _decision(72.0, {"compound_v3": 4.3200}),
    ]))
    assert report["faded_pull_legs"] == 0
    assert report["pull_axis"]["legs"].get(census.CLASS_HELD) == 1
    assert report["status"] == census.STATUS_OK


# ── эталон 2: колебание — «осела» и «держалась» неверны одинаково ───────────

def _real_oscillation(tmp_path: Path) -> Path:
    """2026-09-14: решали на 5.2038 %, вперёд 3.5666…5.2402 % (размах 1.67 pp)."""
    return _write(tmp_path, [
        _decision(288.0, {"aave_v3": 5.2038},
                  current={"aave_v3": 5000.0}, target={"aave_v3": 40000.0},
                  gates={"cooldown_ok": False}, reasons=["cooldown_active:2.3d<3d"],
                  cycle_date="2026-09-14"),
        _decision(264.0, {"aave_v3": 3.5666}),
        _decision(240.0, {"aave_v3": 5.2402}),
        _decision(216.0, {"aave_v3": 3.5767}),
    ])


def test_an_oscillating_rate_is_its_own_outcome_not_a_fade(tmp_path):
    report = _run(_real_oscillation(tmp_path))
    assert report["faded_pull_legs"] == 0, "колебание НЕ есть падение ставки"
    assert report["oscillating_legs"] == 1
    assert report["oscillating_usd"] == pytest.approx(35000.0)
    item = report["oscillating"][0]
    assert item["cause"] == "forward_observations_disagree"
    assert item["forward_span_pp"] > 0.5
    assert "ADR-312" in item["reason"]


def test_oscillation_does_not_soften_the_verdict_to_ok(tmp_path):
    """Неопределённость — не «всё хорошо»: зелёный на ней был бы fail-OPEN."""
    report = _run(_real_oscillation(tmp_path))
    assert report["status"] == census.STATUS_WARNING


def test_without_the_returning_observation_the_same_scene_is_a_fade(tmp_path):
    """Звено названо: `max(forward) >= floor`. Порвать его — сцена краснеет как fade."""
    report = _run(_write(tmp_path, [
        _decision(288.0, {"aave_v3": 5.2038},
                  current={"aave_v3": 5000.0}, target={"aave_v3": 40000.0},
                  gates={}, reasons=[], cycle_date="2026-09-14"),
        _decision(264.0, {"aave_v3": 3.5666}),
        _decision(240.0, {"aave_v3": 3.5800}),
        _decision(216.0, {"aave_v3": 3.5767}),
    ]))
    assert report["oscillating_legs"] == 0
    assert report["faded_pull_legs"] == 1


def test_one_dip_below_the_floor_does_not_make_a_fade(tmp_path):
    """Медиана, а не минимум: одиночная просадка ставку осевшей не делает."""
    report = _run(_write(tmp_path, [
        _decision(288.0, {"maple": 4.9643},
                  current={"maple": 5000.0}, target={"maple": 20000.0},
                  gates={}, reasons=[], cycle_date="2026-09-11"),
        _decision(264.0, {"maple": 4.9657}),
        _decision(240.0, {"maple": 3.0000}),
        _decision(216.0, {"maple": 4.9700}),
    ]))
    assert report["faded_pull_legs"] == 0
    assert report["pull_axis"]["legs"].get(census.CLASS_HELD) == 1


# ── эталон 3: исполненная нога входа ───────────────────────────────────────

def test_the_real_t034_entry_is_measured_as_held(tmp_path):
    """T034: $14 737 в `maple` на 4.9643 %, вперёд медиана 4.9657 % — держалась."""
    report = _run(_write(
        tmp_path,
        [_decision(360.0, {"maple": 4.9643}),
         _decision(336.0, {"maple": 4.9657}),
         _decision(312.0, {"maple": 4.9650})],
        [_move("T034", 358.0, {"maple": 5263.16}, {"maple": 20000.0})]))
    legs = report["entry_axis"]["legs"]
    assert legs.get(census.CLASS_HELD) == 1
    assert report["faded_entry_legs"] == 0


def test_an_executed_entry_on_a_rate_that_never_returns_is_a_fade(tmp_path):
    """Положительный контроль оси денег: вход на ставке, которая не вернулась."""
    report = _run(_write(
        tmp_path,
        [_decision(360.0, {"compound_v3": 7.8486}),
         _decision(336.0, {"compound_v3": 4.0868}),
         _decision(312.0, {"compound_v3": 4.2000})],
        [_move("T032", 358.0, {"compound_v3": 10000.0}, {"compound_v3": 40000.0})]))
    assert report["faded_entry_legs"] == 1
    assert report["faded_entry_usd"] == pytest.approx(30000.0)
    assert report["status"] in (census.STATUS_CRITICAL, census.STATUS_WARNING)


def test_a_fresh_executed_fade_is_critical_and_an_old_one_is_only_warning(tmp_path):
    """Вердикт судит НАСТОЯЩЕЕ: свежесть меряется окном владельца от `now`."""
    fresh = _run(_write(
        tmp_path,
        [_decision(120.0, {"compound_v3": 7.8486}),
         _decision(96.0, {"compound_v3": 4.0868}),
         _decision(72.0, {"compound_v3": 4.1000})],
        [_move("T032", 118.0, {"compound_v3": 10000.0}, {"compound_v3": 40000.0})]))
    assert fresh["status"] == census.STATUS_CRITICAL
    assert fresh["fresh_faded_entry_legs"] == 1

    old = _run(_write(
        tmp_path,
        [_decision(24.0 * 40, {"compound_v3": 7.8486}),
         _decision(24.0 * 39, {"compound_v3": 4.0868}),
         _decision(24.0 * 38, {"compound_v3": 4.1000})],
        [_move("T032", 24.0 * 40 - 2, {"compound_v3": 10000.0},
               {"compound_v3": 40000.0})]))
    assert old["faded_entry_legs"] == 1
    assert old["fresh_faded_entry_legs"] == 0
    assert old["status"] == census.STATUS_WARNING


# ── третий исход: четыре разные двери, и они РАЗВЕДЕНЫ ─────────────────────

def test_an_observation_older_than_the_hold_window_is_not_the_deciding_rate(tmp_path):
    """T009: ближайшее наблюдение старше срока удержания ⇒ решали не на нём."""
    report = _run(_write(
        tmp_path,
        [_decision(24.0 * 10, {"aave_v3": 3.2780}),
         _decision(24.0 * 9, {"aave_v3": 3.2800})],
        [_move("T009", 24.0 * 2, {"aave_v3": 0.0}, {"aave_v3": 40000.0})]))
    legs = report["entry_axis"]["legs"]
    assert legs.get(census.CLASS_UNMEASURED) == 1
    assert legs.get(census.CLASS_HELD) is None, "старое наблюдение НЕ выдаётся за решение"
    causes = report["entry_axis"]["unmeasured_causes"]
    assert causes.get("observation_older_than_hold") == 1
    assert report["entry_axis"]["usd"][census.CLASS_UNMEASURED] == pytest.approx(40000.0)


def test_no_forward_observation_is_unmeasured_not_held(tmp_path):
    """T033 `pendle`: форвардных наблюдений внутри срока НЕТ вовсе."""
    report = _run(_write(
        tmp_path,
        [_decision(24.0 * 18, {"pendle": 14.0048})],
        [_move("T033", 24.0 * 18 - 1, {"pendle": 0.0}, {"pendle": 20000.0})]))
    legs = report["entry_axis"]["legs"]
    assert legs.get(census.CLASS_UNMEASURED) == 1
    assert legs.get(census.CLASS_HELD) is None
    assert report["entry_axis"]["unmeasured_causes"].get("no_forward_observation") == 1


def test_a_key_never_observed_before_the_move_names_its_own_door(tmp_path):
    report = _run(_write(
        tmp_path,
        [_decision(24.0, {"maple": 4.96})],
        [_move("T028", 48.0, {"fluid_fusdc": 0.0}, {"fluid_fusdc": 9474.0})]))
    assert report["entry_axis"]["unmeasured_causes"].get(
        "no_observation_before_move") == 1


def test_a_pull_whose_deciding_rate_is_absent_is_unmeasured_not_held(tmp_path):
    """Цель тянет ключ, ставки которого в записи НЕТ — класс ADR-366."""
    report = _run(_write(tmp_path, [
        _decision(48.0, {"maple": 4.96}, current={"aave_v3": 5000.0},
                  target={"aave_v3": 40000.0}, gates={}, reasons=[],
                  cycle_date="2026-08-24"),
        _decision(24.0, {"maple": 4.96}),
    ]))
    assert report["pull_axis"]["legs"].get(census.CLASS_UNMEASURED) == 1
    assert report["pull_axis"]["unmeasured_causes"].get("decided_rate_absent") == 1


def test_a_record_without_capital_is_unmeasured_not_silently_skipped(tmp_path):
    """Доля без знаменателя есть догадка: существенность ноги НЕ ИЗМЕРЕНА."""
    report = _run(_write(tmp_path, [
        _decision(48.0, {"maple": 4.96}, current={"maple": 1000.0},
                  target={"maple": 40000.0}, capital=None, cycle_date="2026-08-24"),
        _decision(24.0, {"maple": 4.96}),
    ]))
    assert report["pull_axis"]["unmeasured_causes"].get("capital_absent") == 1


def test_a_leg_below_the_owner_materiality_is_not_a_pull(tmp_path):
    """Порог существенности — доля капитала ИЗ ЗАПИСИ, а не наша константа."""
    report = _run(_write(tmp_path, [
        _decision(48.0, {"maple": 4.96}, current={"maple": 1000.0},
                  target={"maple": 1400.0}, capital=100000.0, cycle_date="2026-08-24"),
        _decision(24.0, {"maple": 4.96}),
    ]))
    assert sum(report["pull_axis"]["legs"].values()) == 0


def test_missing_threshold_column_is_the_third_outcome_not_a_default(tmp_path):
    """§22 «Не hardcode»: колонки нет ⇒ НЕ ИЗМЕРЕНО, а не подставленное число."""
    class _Broken:
        min_gain_pp = 0.5  # остальных полей нет

    report = census.run_census(_write(tmp_path, [_decision(24.0, {"maple": 4.96})]),
                               now=_ANCHOR, params=_Broken())
    assert report["measured"] is False
    assert report["status"] == census.STATUS_UNMEASURED
    assert "НЕ ИЗМЕРЕНО" in report["reason"]


def test_a_non_positive_hold_window_is_unmeasured(tmp_path):
    report = census.run_census(_write(tmp_path, [_decision(24.0, {"maple": 4.96})]),
                               now=_ANCHOR, params=_Params(min_hold_days=0.0))
    assert report["measured"] is False
    assert "срок удержания" in report["reason"]


def test_a_missing_decision_journal_is_unmeasured_with_a_named_reason(tmp_path):
    report = _run(tmp_path)
    assert report["measured"] is False
    assert census.DECISIONS_NAME in report["reason"]
    assert "НЕ" in report["reason"]


def test_an_unparsable_journal_line_is_counted_not_swallowed(tmp_path):
    (tmp_path / census.DECISIONS_NAME).write_text(
        "{не json}\n" + json.dumps(_decision(48.0, {"maple": 4.96})) + "\n"
        + json.dumps(_decision(24.0, {"maple": 4.96})) + "\n", encoding="utf-8")
    report = _run(tmp_path)
    assert report["measured"] is True
    assert report["decisions"]["unparsed"] == 1


def test_a_record_without_a_readable_stamp_is_counted_as_undated(tmp_path):
    rows = [dict(_decision(48.0, {"maple": 4.96}), generated_at="вчера"),
            _decision(24.0, {"maple": 4.96})]
    report = _run(_write(tmp_path, rows))
    assert report["decisions"]["undated"] == 1


def test_an_empty_journal_is_unmeasured_not_ok(tmp_path):
    (tmp_path / census.DECISIONS_NAME).write_text("\n", encoding="utf-8")
    report = _run(tmp_path)
    assert report["measured"] is False
    assert report["status"] == census.STATUS_UNMEASURED


# ── две оси не сворачиваются в один исход ──────────────────────────────────

def test_a_missing_money_journal_leaves_the_decision_axis_measured(tmp_path):
    report = _run(_real_faded_pull(tmp_path))
    assert report["measured"] is True
    assert report["journal"]["measured"] is False
    assert report["journal"]["note"] and "НЕ ИЗМЕРЕНА" in report["journal"]["note"]
    assert report["faded_pull_legs"] == 1, "ось решения измерена и без журнала денег"


# ── гейты: «поля нет» ≠ «ни один не отказал» (инв. #17) ────────────────────

def test_absent_gates_are_reported_as_unmeasured_not_as_nothing_refused(tmp_path):
    rows = [_decision(120.0, {"compound_v3": 6.3637},
                      current={"compound_v3": 10000.0},
                      target={"compound_v3": 40000.0}, cycle_date="2026-08-20"),
            _decision(96.0, {"compound_v3": 4.3373}),
            _decision(72.0, {"compound_v3": 4.3000})]
    report = _run(_write(tmp_path, rows))
    assert report["faded_pulls"][0]["gates_measured"] is False
    text = "\n".join(census.format_report(report))
    assert "НЕ ЗАПИСАНЫ" in text
    assert "ни один гейт не отказал" not in text


def test_present_gates_with_no_refusal_say_exactly_that(tmp_path):
    rows = [_decision(120.0, {"compound_v3": 6.3637},
                      current={"compound_v3": 10000.0},
                      target={"compound_v3": 40000.0}, gates={"has_legs": True},
                      cycle_date="2026-08-20"),
            _decision(96.0, {"compound_v3": 4.3373}),
            _decision(72.0, {"compound_v3": 4.3000})]
    text = "\n".join(census.format_report(_run(_write(tmp_path, rows))))
    assert "ни один гейт не отказал" in text
    assert "НЕ ЗАПИСАНЫ" not in text


# ── скрин ручки: утверждение не прошито, а измерено ────────────────────────

def test_the_missing_survival_dial_is_measured_over_real_names(tmp_path):
    report = _run(_real_faded_pull(tmp_path))
    assert report["no_survival_condition_named"] is True
    assert "min_gain_pp" in report["survival_screen"]["names_scanned"]


def test_a_column_that_does_name_survival_flips_the_screen(tmp_path):
    """Контроль в обратную сторону: утверждение «ручки нет» НЕ прошито True."""
    params = _Params()
    params.min_apy_persistence_days = 2.0  # type: ignore[attr-defined]
    report = census.run_census(_real_faded_pull(tmp_path), now=_ANCHOR, params=params)
    assert report["no_survival_condition_named"] is False
    assert "min_apy_persistence_days" in report["survival_screen"]["candidates"]
    assert "КАНДИДАТ В РУЧКУ" in "\n".join(census.format_report(report))


def test_a_gate_name_about_stability_is_also_screened(tmp_path):
    rows = [_decision(120.0, {"compound_v3": 6.3637},
                      current={"compound_v3": 10000.0},
                      target={"compound_v3": 40000.0},
                      gates={"apy_stability_ok": True}, cycle_date="2026-08-20"),
            _decision(96.0, {"compound_v3": 4.3373}),
            _decision(72.0, {"compound_v3": 4.3000})]
    report = _run(_write(tmp_path, rows))
    assert report["no_survival_condition_named"] is False
    assert "apy_stability_ok" in report["survival_screen"]["candidates"]


# ── момент наблюдения: `apy_as_of`, а не отметка записи ────────────────────

def test_the_observation_moment_comes_from_apy_as_of(tmp_path):
    """Сцена, где отметка записи и момент наблюдения дают РАЗНЫЙ исход."""
    rows = [
        # Запись «свежая» (отметка 24 ч назад), а ставка в ней НАБЛЮДЕНА 10 дней
        # назад. По отметке ЗАПИСИ ход попал бы в окно удержания и дверь
        # называлась бы другая (`no_forward_observation`); по МОМЕНТУ наблюдения
        # решали не на ней — и это разные причины, а не разная формулировка.
        _decision(24.0, {"aave_v3": 3.2780}, as_of={"aave_v3": _ts(24.0 * 10)}),
        _decision(12.0, {"maple": 4.9600}, as_of={"maple": _ts(12.0)}),
    ]
    report = _run(_write(tmp_path, rows,
                         [_move("T009", 2.0, {"aave_v3": 0.0}, {"aave_v3": 40000.0})]))
    causes = report["entry_axis"]["unmeasured_causes"]
    assert causes.get("observation_older_than_hold") == 1
    assert causes.get("no_forward_observation") is None, (
        "дверь названа по МОМЕНТУ наблюдения, а не по отметке записи")


def test_a_record_without_as_of_falls_back_to_its_stamp_and_is_counted(tmp_path):
    rows = [dict(_decision(48.0, {"maple": 4.96})), _decision(24.0, {"maple": 4.96})]
    rows[0].pop("apy_as_of")
    report = _run(_write(tmp_path, rows))
    assert report["panel"]["moment_from_record"] >= 1


def test_an_observation_at_the_deciding_moment_is_not_a_forward_one(tmp_path):
    """Форвардное окно строго ПОСЛЕ момента решения: своё наблюдение не считается."""
    rows = [_decision(48.0, {"maple": 6.0}, current={"maple": 1000.0},
                      target={"maple": 40000.0}, cycle_date="2026-09-01")]
    report = _run(_write(tmp_path, rows))
    assert report["pull_axis"]["unmeasured_causes"].get("no_forward_observation") == 1


def test_a_bool_or_string_rate_is_not_read_as_a_number(tmp_path):
    rows = [_decision(48.0, {"maple": True, "aave_v3": "4.5"}),
            _decision(24.0, {"maple": 4.9})]
    report = _run(_write(tmp_path, rows))
    assert report["panel"]["dropped_values"] == 2
    assert "aave_v3" not in report["survival_screen"]["names_scanned"]


# ── псевдонимы ключей: ряд ставки не рвётся на переименовании ──────────────

def test_a_renamed_key_keeps_one_rate_series(tmp_path):
    """`fluid_usdc`→`fluid_fusdc` измеряется у соседа (ADR-480) и сшивает ряд."""
    moves = [
        _move("T031", 24.0 * 8, {"fluid_usdc": 10000.0}, {"fluid_usdc": 20000.0}),
        _move("T032", 24.0 * 7, {"fluid_fusdc": 20000.0}, {"fluid_fusdc": 30000.0}),
    ]
    rows = [_decision(24.0 * 8 + 1, {"fluid_usdc": 6.0}),
            _decision(24.0 * 7 - 1, {"fluid_fusdc": 4.0}),
            _decision(24.0 * 6, {"fluid_fusdc": 4.1})]
    report = _run(_write(tmp_path, rows, moves))
    assert report["aliases"].get("fluid_usdc") == "fluid_fusdc"
    # Ряд сшит: у ноги T031 (старое имя) есть форвардные наблюдения под новым.
    t031 = [e for e in report["faded_entries"] if e["trade_id"] == "T031"]
    assert t031, "без сшивки ряда падение ставки на переименовании не видно"


# ── артефакт: контроль читает ДИСК, а не вывод (урок #701) ─────────────────

def test_run_leaves_the_artifact_on_disk(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write(data, [_decision(48.0, {"maple": 4.96}), _decision(24.0, {"maple": 4.96})])
    out = census.run(root=str(tmp_path), now=_ANCHOR)
    path = data / census.ARTIFACT_NAME
    assert path.is_file(), "ступень доложила исход, а артефакта на ДИСКЕ нет"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["status"] == out["doc"]["status"]


def test_the_third_outcome_also_reaches_disk(tmp_path):
    """«Не измерено» обязано доехать до офиса: иначе молчание = отсутствие файла."""
    data = tmp_path / "data"
    data.mkdir()
    out = census.run(root=str(tmp_path), now=_ANCHOR)
    assert out["measured"] is False
    on_disk = json.loads((data / census.ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert on_disk["status"] == census.STATUS_UNMEASURED
    assert on_disk["reason"]


def test_a_refused_write_is_named_not_swallowed(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    _write(data, [_decision(48.0, {"maple": 4.96}), _decision(24.0, {"maple": 4.96})])

    def _boom(report, path):  # noqa: ANN001
        raise OSError("диск не принял")

    monkeypatch.setattr("spa_core.utils.atomic.atomic_save", _boom)
    out = census.run(root=str(tmp_path), now=_ANCHOR)
    assert "artifact_not_written" in out["doc"]
    assert not (data / census.ARTIFACT_NAME).exists()


# ── отчёт и коды возврата ─────────────────────────────────────────────────

def test_the_office_line_names_the_unmeasured_dollars(tmp_path):
    report = _run(_write(
        tmp_path,
        [_decision(24.0 * 10, {"aave_v3": 3.2780}), _decision(24.0 * 9, {"aave_v3": 3.28})],
        [_move("T009", 24.0 * 2, {"aave_v3": 0.0}, {"aave_v3": 40000.0})]))
    text = "\n".join(census.format_report(report))
    assert "НЕ ИЗМЕРЕНО" in text
    assert "observation_older_than_hold" in text


def test_the_summary_of_an_unmeasured_report_says_so(tmp_path):
    line = census.summary_line(_run(tmp_path))
    assert line.startswith("выживание ставки (§49 Persistence): НЕ ИЗМЕРЕНО")


def test_exit_code_three_means_not_measured(tmp_path, capsys):
    code = census.main(["--data-dir", str(tmp_path)])
    capsys.readouterr()
    assert code == census.EXIT_UNMEASURED


def test_exit_code_one_only_on_a_fresh_executed_fade(tmp_path, capsys):
    _write(tmp_path,
           [_decision(120.0, {"compound_v3": 7.8486}),
            _decision(96.0, {"compound_v3": 4.0868}),
            _decision(72.0, {"compound_v3": 4.1})],
           [_move("T032", 118.0, {"compound_v3": 10000.0}, {"compound_v3": 40000.0})])
    # Коды считает `main`, а он берёт живую колонку порогов — сцена рассчитана на
    # бумажную (0.5 pp / 3 дн), то есть на ту, которой судит живой путь.
    code = census.main(["--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "CRITICAL" in out


def test_history_only_fade_does_not_nag_with_a_nonzero_code(tmp_path, capsys):
    """Вечно ненулевой прибор учит себя игнорировать — история кодом не нудит."""
    _write(tmp_path,
           [_decision(24.0 * 40, {"compound_v3": 7.8486}),
            _decision(24.0 * 39, {"compound_v3": 4.0868}),
            _decision(24.0 * 38, {"compound_v3": 4.1})],
           [_move("T032", 24.0 * 40 - 2, {"compound_v3": 10000.0},
                  {"compound_v3": 40000.0})])
    code = census.main(["--data-dir", str(tmp_path)])
    assert code == 0
    assert "WARNING" in capsys.readouterr().out


def test_the_report_never_sums_pull_dollars_as_distinct_money(tmp_path):
    """Одна и та же цель повторяется изо дня в день — сумма НЕ «разные деньги»."""
    # Две тяги ОДНОЙ цели, разнесённые шире срока удержания, — иначе вторая
    # оказалась бы форвардным наблюдением первой и обе стали бы КОЛЕБАНИЕМ.
    rows = [
        _decision(24.0 * 10, {"aave_v3": 5.2651}, current={"aave_v3": 5000.0},
                  target={"aave_v3": 40000.0}, cycle_date="2026-09-05"),
        _decision(24.0 * 9, {"aave_v3": 3.6000}),
        _decision(24.0 * 8, {"aave_v3": 3.6100}),
        _decision(96.0, {"aave_v3": 5.2469}, current={"aave_v3": 5000.0},
                  target={"aave_v3": 40000.0}, cycle_date="2026-09-07"),
        _decision(72.0, {"aave_v3": 3.6227}),
        _decision(48.0, {"aave_v3": 3.6100}),
    ]
    report = _run(_write(tmp_path, rows))
    assert report["faded_pull_legs"] == 2
    assert report["faded_pull_usd"] == pytest.approx(70000.0)
    assert report["faded_pull_usd_max_single"] == pytest.approx(35000.0)
    assert "наибольшая одиночная" in "\n".join(census.format_report(report))


def test_the_verdict_does_not_depend_on_machine_time(tmp_path):
    """Часы — ВХОД: сдвиг `now` на месяц меняет свежесть, а не сам замер."""
    tree = _write(
        tmp_path,
        [_decision(120.0, {"compound_v3": 7.8486}),
         _decision(96.0, {"compound_v3": 4.0868}),
         _decision(72.0, {"compound_v3": 4.1})],
        [_move("T032", 118.0, {"compound_v3": 10000.0}, {"compound_v3": 40000.0})])
    near = census.run_census(tree, now=_ANCHOR, params=_Params())
    far = census.run_census(tree, now=_ANCHOR + timedelta(days=30), params=_Params())
    assert near["faded_entry_legs"] == far["faded_entry_legs"] == 1
    assert near["status"] == census.STATUS_CRITICAL
    assert far["status"] == census.STATUS_WARNING


# ── суммы долларов: нога без числа НЕ равна нулю (инв. #17) ─────────────────

def test_a_leg_without_a_dollar_number_is_named_not_added_as_zero():
    """Проверка НА УРОВНЕ функции: в живых входах писатель сумму ставит всегда,
    поэтому класс достижим только так — и именно поэтому его надо закрепить:
    первая редакция писала `item["usd"] or 0.0`, и нога без суммы стала бы
    неотличима от ноги на $0 (храповик `test_absent_observation_ratchet`)."""
    total, missing = census._sum_usd([{"usd": 100.0}, {"protocol": "x"},
                                      {"usd": None}])
    assert total == pytest.approx(100.0)
    assert missing == 2


def test_the_largest_single_amount_is_none_when_no_leg_carries_a_number():
    assert census._max_usd([{"protocol": "x"}]) is None
    assert census._max_usd([{"usd": 5.0}, {"usd": 9.0}]) == pytest.approx(9.0)


def test_an_absent_amount_prints_as_unmeasured_not_as_zero_dollars():
    assert census._usd_text(None) == "НЕ ИЗМЕРЕНО"
    assert census._usd_text(0.0) == "$0"


def test_totals_report_legs_without_usd_separately(tmp_path):
    report = _run(_real_faded_pull(tmp_path))
    assert report["pull_axis"]["legs_without_usd"] == {}, (
        "на живой сцене сумма есть у каждой ноги — иначе итог неполон молча")


def test_the_verdict_line_names_when_the_latest_pull_happened(tmp_path):
    """`WARNING` без даты читается как «старая история» — замер #704 нашёл две
    тяги ВЧЕРАШНИМ днём, поэтому свежесть самой поздней тяги называется вслух."""
    report = _run(_real_faded_pull(tmp_path))
    assert report["latest_faded_pull_age_hours"] == pytest.approx(120.0, abs=0.1)
    text = "\n".join(census.format_report(report))
    assert "самая поздняя тяга" in text
    assert "120 ч назад" in text


def test_an_unparsable_latest_stamp_is_named_not_guessed(tmp_path):
    report = _run(_real_faded_pull(tmp_path))
    report["latest_faded_pull_age_hours"] = None
    text = "\n".join(census.format_report(report))
    assert "НЕ ИЗМЕРЕНА" in text


def test_a_screen_with_no_names_says_unmeasured_not_no_dial(tmp_path):
    """Пустое множество имён дало бы «ручки нет» БЕЗ замера — выдуманное
    утверждение того же класса, что «инструмента нет ⇒ ноль» (урок pyflakes)."""
    screen = census.screen_survival_names([], [])
    assert screen["no_survival_condition_named"] is None
    assert "НЕ ИЗМЕРЕНО" in screen["reason"]


def test_the_report_prints_the_unmeasured_screen_as_a_third_outcome(tmp_path):
    report = _run(_real_faded_pull(tmp_path))
    report["survival_screen"] = census.screen_survival_names([], [])
    report["no_survival_condition_named"] = None
    text = "\n".join(census.format_report(report))
    assert "РУЧКА НЕ ИЗМЕРЕНА" in text
    assert "НЕТ РУЧКИ ПО ПОСТРОЕНИЮ" not in text
