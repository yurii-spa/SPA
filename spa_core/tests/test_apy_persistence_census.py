#!/usr/bin/env python3
"""Контроль переписи устойчивости ставки — критерий §49 `Persistence` приказа CIO.

Каждый тест здесь — либо ВОСПРОИЗВЕДЕНИЕ настоящего исхода из журнала решений,
либо контроль звена в обратную сторону: порванное звено обязано КРАСНЕТЬ, и
звено названо в имени теста. Проверка, никогда не видевшая настоящей поломки,
есть украшение (`.claude/rules/deployment.md`).

Эталон воспроизводится дословно: строка **2026-09-14** журнала
`data/allocation_rationale_history.jsonl` — `aave_v3` наблюдён под 5.2038 % при
трёх предыдущих днях 3.5682 / 3.5133 / 3.5138, цель добавляет в него $35 000,
записанная выгода 0.543 пп проходит полосу владельца 0.500 пп, а на устойчивых
ставках та же цель даёт **минус** 0.048 пп. Полосу прошёл скачок, а ход
остановили гейты об обороте, сумме, cooldown и payback — ни один из них не про
длительность ставки.

# FROZEN-DATE-OK: injected-clock — все отметки сцен происходят от якоря
# `_ANCHOR` (см. `_date` и `_stamp`), и ОН ЖЕ передаётся прибору аргументом
# `now=`; ни одна проверка этого файла не спрашивает время у машины, поэтому
# сдвиг календаря вердикта здесь не меняет.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import apy_persistence_census as census

#: Якорь сцен. От него происходят ВСЕ отметки и он же идёт в `now=`.
_ANCHOR = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)

_CAPITAL = 100_000.0


def _date(days_before: int) -> str:
    """Дата цикла за N суток до якоря — обе стороны сцены закреплены якорем."""
    return (_ANCHOR - timedelta(days=days_before)).date().isoformat()


def _stamp(days_before: int) -> str:
    """Отметка производителя за N суток до якоря."""
    return (_ANCHOR - timedelta(days=days_before)).isoformat()


class _Params:
    """Колонка порогов ADR-060 §3 как ВХОД сцены, а не как живой файл."""

    def __init__(self, min_hold_days: int = 3, min_leg_frac: float = 0.005,
                 reversal_window_days: float = 14.0, mode: str = "paper",
                 version: str = "test") -> None:
        self.min_hold_days = min_hold_days
        self.min_leg_frac = min_leg_frac
        self.reversal_window_days = reversal_window_days
        self.mode = mode
        self.version = version


def _row(days_before: int, apy: dict, current: dict, target: dict, *,
         required: float = 0.5, gates: dict | None = None,
         reasons: list | None = None, book_pp: float | None = None,
         target_pp: float | None = None, gain_pp: float | None = None) -> dict:
    """Строка журнала решений. Числа производителя считаются ЕГО формулой.

    Это и делает сцену воспроизведением, а не сочинением: `book_apy_pp` и
    `target_apy_pp` здесь такие, какими их записал бы живой производитель, —
    прибор их сверяет, и подделка сцены обрушила бы сверку.
    """
    def blend(pos: dict) -> float:
        return sum(v * apy.get(k, 0.0) for k, v in pos.items()) / _CAPITAL
    book = blend(current) if book_pp is None else book_pp
    tgt = blend(target) if target_pp is None else target_pp
    return {
        "cycle_date": _date(days_before),
        "generated_at": _stamp(days_before),
        "book_id": "conservative",
        "capital_usd": _CAPITAL,
        "apy_evidenced_pct": dict(apy),
        "current_positions": dict(current),
        "target_positions": dict(target),
        "book_apy_pp": book,
        "target_apy_pp": tgt,
        "gain_pp": (tgt - book) if gain_pp is None else gain_pp,
        "required_gain_pp": required,
        "gates": {"gain_above_band": True} if gates is None else gates,
        "reasons": reasons or [],
    }


def _history(tmp_path: Path, rows: list) -> Path:
    (tmp_path / census.HISTORY_NAME).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return tmp_path


# ── эталон: сцена 14.09, воспроизведённая по числам журнала ──────────────────

_FLAT = {"aave_v3": 3.5682, "compound_v3": 3.652, "maple": 5.0, "fluid_fusdc": 4.3}


def _quiet_day(days_before: int, aave: float) -> dict:
    """Спокойный день: цель равна книге, полоса не при чём — он кормит РЯД."""
    book = {"aave_v3": 5_000.0, "compound_v3": 40_000.0, "maple": 20_000.0,
            "fluid_fusdc": 20_000.0}
    apy = dict(_FLAT, aave_v3=aave)
    return _row(days_before, apy, book, book, gates={"has_legs": False},
                reasons=["no_material_legs"])


def _spike_scene(aave_today: float = 5.2038,
                 prior: tuple = (3.5682, 3.5133, 3.5138)) -> list:
    """Три спокойных дня, затем день, где цель уходит в подскочивший `aave_v3`.

    Ровно форма строки 2026-09-14: $35 000 из `compound_v3` в `aave_v3`.
    """
    rows = [_quiet_day(len(prior) - i, value) for i, value in enumerate(prior)]
    apy = dict(_FLAT, aave_v3=aave_today)
    current = {"aave_v3": 5_000.0, "compound_v3": 40_000.0, "maple": 20_000.0,
               "fluid_fusdc": 20_000.0}
    target = {"aave_v3": 40_000.0, "compound_v3": 5_000.0, "maple": 20_000.0,
              "fluid_fusdc": 20_000.0}
    rows.append(_row(0, apy, current, target, gates={
        "gain_above_band": True, "cooldown_ok": False, "move_amount_ok": False,
        "move_turnover_ok": False, "payback_within_horizon": False,
        "week_turnover_ok": False, "day_turnover_ok": False, "has_legs": True,
        "min_hold_ok": True, "target_fully_evidenced": True,
    }, reasons=["payback_too_long:35.0d", "cooldown_active:2.3d<3d",
                "move_turnover_over_budget:35.0%>15%"]))
    return rows


def _run(tmp_path: Path, rows: list, **kw):
    params = kw.pop("params", _Params())
    return census.run_census(_history(tmp_path, rows), now=_ANCHOR,
                             params=params, **kw)


# ── 1. эталон и его обратная сторона ────────────────────────────────────────

def test_spike_carried_band_reproduces_the_2026_09_14_row(tmp_path):
    """Полосу прошёл скачок: на устойчивых ставках выгода уходит В МИНУС."""
    report = _run(tmp_path, _spike_scene())
    assert report["measured"] is True
    assert report["counts"]["spike_carried"] == 1
    found = report["findings"][0]
    assert found["verdict"] == "spike_carried"
    assert found["recorded_gain_pp"] >= found["required_gain_pp"]
    assert found["counterfactual_gain_pp"] < 0.0
    assert [e["protocol"] for e in found["elevated"]] == ["aave_v3"]
    assert found["elevated"][0]["added_usd"] == pytest.approx(35_000.0)


def test_sustained_rise_is_not_a_finding(tmp_path):
    """Обратная сторона: новый РЕЖИМ держался — находкой он быть не смеет.

    Тот же подскок, но предыдущие дни стоят на том же уровне: ставка выросла
    по-настоящему, и защищаться тут не от чего. Без этого контроля прибор
    краснел бы на каждом честном росте ставки.
    """
    report = _run(tmp_path, _spike_scene(prior=(5.2038, 5.2038, 5.2038)))
    assert report["counts"]["spike_carried"] == 0
    assert report["status"] == census.STATUS_OK
    assert report["graded"][-1]["verdict"] == "persists"


def test_elevated_but_still_clearing_the_band_is_not_a_finding(tmp_path):
    """Воспроизведение строки 05.09: ставка подскочила, а полоса пройдена БЕЗ неё.

    Записанная выгода 2.400 пп, на устойчивых ставках 1.792 пп, полоса 0.750 пп —
    скачок был, но решение на нём не стояло. Обратная сторона эталона: прибор
    краснеет на ПРИЧИНУ прохождения полосы, а не на всякий подскок в ряду.
    Порванное звено (сравнивать контрфакт с записанной выгодой вместо полосы)
    объявило бы находкой и этот день.
    """
    report = _run(tmp_path, _spike_scene(aave_today=5.2038,
                                         prior=(3.5682, 3.5133, 3.5138)),
                  params=_Params(min_hold_days=3))
    # та же сцена, но полоса заведомо ниже вклада устойчивых ставок
    rows = _spike_scene(aave_today=5.2038, prior=(3.5682, 3.5133, 3.5138))
    rows[-1]["required_gain_pp"] = -1.0
    lenient = _run(tmp_path, rows)
    assert report["counts"]["spike_carried"] == 1
    assert lenient["counts"]["spike_carried"] == 0
    graded = lenient["graded"][-1]
    assert graded["verdict"] == "persists"
    assert graded["elevated"], "подскок в ряду обязан остаться НАЗВАННЫМ"
    assert graded["counterfactual_gain_pp"] < graded["recorded_gain_pp"]


def test_gain_attributable_to_transient_is_the_difference(tmp_path):
    report = _run(tmp_path, _spike_scene())
    found = report["findings"][0]
    assert found["gain_attributable_to_transient_pp"] == pytest.approx(
        found["recorded_gain_pp"] - found["counterfactual_gain_pp"], abs=1e-9)


def test_refusing_gates_are_quoted_from_the_row_not_invented(tmp_path):
    """Кто на самом деле остановил ход — читается из строки, а не из нашей головы."""
    found = _run(tmp_path, _spike_scene())["findings"][0]
    assert found["refusing_gates"] == sorted([
        "cooldown_ok", "day_turnover_ok", "move_amount_ok", "move_turnover_ok",
        "payback_within_horizon", "week_turnover_ok"])
    assert "gain_above_band" not in found["refusing_gates"]


# ── 2. односторонность подстановки ──────────────────────────────────────────

def test_substitution_is_one_sided_a_dip_is_never_lifted(tmp_path):
    """Ставка НИЖЕ устойчивого уровня не поднимается: выдумать улучшение нельзя.

    Сцена: полоса пройдена честно — деньги едут в `maple` под устойчивые 5 %, —
    и ОДНОВРЕМЕННО цель добавляет в `aave_v3`, чья сегодняшняя ставка ПРОСЕЛА
    ниже своего уровня. Порванное звено (двусторонняя замена) подняло бы 3.0 %
    до устойчивых 3.5 % и изменило бы контрфакт, то есть посчитало бы выгоду,
    которой в этот день не наблюдалось.
    """
    apy_flat = {"aave_v3": 3.5138, "compound_v3": 3.652, "maple": 8.0}
    book = {"aave_v3": 10_000.0, "compound_v3": 60_000.0, "maple": 20_000.0}
    rows = [_row(d, apy_flat, book, book, gates={"has_legs": False})
            for d in (3, 2, 1)]
    apy_today = dict(apy_flat, aave_v3=3.0)
    target = {"aave_v3": 20_000.0, "compound_v3": 30_000.0, "maple": 40_000.0}
    rows.append(_row(0, apy_today, book, target))
    graded = _run(tmp_path, rows)["graded"][-1]
    assert graded["recorded_gain_pp"] >= graded["required_gain_pp"]
    assert graded["verdict"] == "persists"
    assert [e["protocol"] for e in graded["elevated"]] == []
    assert graded["counterfactual_gain_pp"] == pytest.approx(
        graded["recorded_gain_pp"], abs=1e-9)


# ── 3. ряд ставок: чей он и как строится ────────────────────────────────────

def test_row_cannot_see_its_own_day_as_history(tmp_path):
    """Решение дня не могло знать собственную точку как «продержалось».

    Положительный контроль звена: если бы сегодняшняя точка входила в ряд, при
    окне 3 дня медианой из (3.51, 3.51, 5.20) осталось бы 3.51 — находка выжила
    бы, — поэтому сцена сделана так, что включение своей точки УБИВАЕТ находку:
    окно 1 день и единственная прошлая точка равна сегодняшней.
    """
    rows = _spike_scene(prior=(3.5138,))
    report = _run(tmp_path, rows, params=_Params(min_hold_days=1))
    found = report["findings"][0]
    assert found["elevated"][0]["prior_pct"] == [3.5138]
    assert found["counterfactual_gain_pp"] < found["required_gain_pp"]


def test_two_runs_of_the_same_day_are_one_point_of_the_series(tmp_path):
    """Дубль прогона за сутки не имеет права занять место дня в окне.

    Дни несут РАЗЛИЧИМЫЕ ставки (1 / 2 / 3 %), а у последнего дня два прогона
    (8 %, затем 3 %). При склейке по дате окно 3 дня есть ровно
    ``[1.0, 2.0, 3.0]`` — последний прогон каждого дня. Без склейки самый
    старый день ВЫТЕСНЯЕТСЯ дублем и окно становится ``[2.0, 8.0, 3.0]``, то
    есть «продержалась» измеряется по двум дням вместо трёх. Проверяется
    СОСТАВ окна, а не только его длина: совпавшая медиана скрыла бы подмену.
    """
    rows = [_quiet_day(3, 1.0), _quiet_day(2, 2.0),
            _quiet_day(1, 8.0), _quiet_day(1, 3.0)]
    rows[-1]["generated_at"] = _stamp(1) + "+01:00"
    rows.extend(_spike_scene(prior=()))   # prior=() ⇒ одна строка решения
    report = _run(tmp_path, rows)
    prior = report["findings"][0]["elevated"][0]["prior_pct"]
    assert prior == [1.0, 2.0, 3.0]


def test_prior_levels_are_strictly_before_the_decision_day(tmp_path):
    """Контракт окна — СТРОГО до дня решения, и он проверяется напрямую.

    Ряд наращивается после оценки строки, поэтому своя точка в него и так не
    попадает; строгость сравнения — второй пояс, и без прямого контроля его
    снятие не заметил бы никто (мутация «`<` → `<=`» выживала).
    """
    series = {"aave_v3": [(_date(2), 1.0), (_date(1), 2.0), (_date(0), 9.0)]}
    assert census._prior_levels(series, "aave_v3", _date(0), 3) == [1.0, 2.0]
    assert census._prior_levels(series, "aave_v3", _date(1), 3) == [1.0]
    assert census._prior_levels(series, "missing", _date(0), 3) == []


def test_series_comes_from_the_decision_journal_only(tmp_path):
    """Ряд берётся из строк решений: чужой артефакт рядом ничего не меняет.

    Сосед `apy_series_daily.json` на 14.09 называет `aave_v3` под 12.55 % —
    другое число того же дня. Операнд обязан быть тем, который читало решение.
    """
    data_dir = _history(tmp_path, _spike_scene())
    (data_dir / "apy_series_daily.json").write_text(json.dumps(
        {"series": {"aave_v3": [[_date(1), 12.5545], [_date(0), 12.5545]]}}),
        encoding="utf-8")
    report = census.run_census(data_dir, now=_ANCHOR, params=_Params())
    assert report["findings"][0]["elevated"][0]["today_pct"] == pytest.approx(5.2038)


# ── 4. третий исход вместо нуля ─────────────────────────────────────────────

def test_short_history_is_unchecked_not_no_spike(tmp_path):
    """Истории короче окна — «НЕ ИЗМЕРЕНО» у протокола, а не «скачка нет»."""
    report = _run(tmp_path, _spike_scene(prior=(3.5138,)))
    graded = report["graded"][-1]
    assert graded["partially_unchecked"] is True
    assert graded["unchecked_protocols"][0]["protocol"] == "aave_v3"
    assert graded["unchecked_protocols"][0]["observed_days"] == 1
    assert "НЕ ИЗМЕРЕНО" in graded["unchecked_protocols"][0]["reason"]
    assert report["counts"]["partially_unchecked"] == 1


def test_protocol_without_observed_apy_today_is_unchecked(tmp_path):
    """Ненаблюдённая ставка протокола цели — отдельная причина, не ноль.

    Полоса пройдена честно (деньги едут в `maple` под устойчивые 8 %), и
    ОДНОВРЕМЕННО цель добавляет существенные $1 000 в `euler_v2`, чья ставка в
    этот день не наблюдена вовсе. Такой протокол обязан попасть в «НЕ ИЗМЕРЕНО»
    со своей причиной, а не тихо сойти за «скачка не было».
    """
    apy_flat = {"aave_v3": 3.5138, "compound_v3": 3.652, "maple": 8.0}
    book = {"aave_v3": 10_000.0, "compound_v3": 60_000.0, "maple": 20_000.0}
    rows = [_row(d, apy_flat, book, book, gates={"has_legs": False})
            for d in (3, 2, 1)]
    target = {"aave_v3": 10_000.0, "compound_v3": 29_000.0, "maple": 60_000.0,
              "euler_v2": 1_000.0}
    rows.append(_row(0, apy_flat, book, target))
    report = _run(tmp_path, rows)
    graded = report["graded"][-1]
    assert graded["recorded_gain_pp"] >= graded["required_gain_pp"]
    assert graded["partially_unchecked"] is True
    unchecked = {u["protocol"]: u for u in graded["unchecked_protocols"]}
    assert unchecked["euler_v2"]["observed_days"] == 0
    assert "НЕ наблюдена" in unchecked["euler_v2"]["reason"]


def test_policy_column_unavailable_is_the_third_outcome(tmp_path):
    """Колонка владельца недоступна ⇒ НЕ ИЗМЕРЕНО, а не своё умолчание (§22)."""
    class _NoDials:
        pass
    report = _run(tmp_path, _spike_scene(), params=_NoDials())
    assert report["measured"] is False
    assert report["status"] == census.STATUS_UNMEASURED
    assert "Не hardcode" in report["reason"] or "НЕ ИЗМЕРЕНО" in report["reason"]
    assert report["counts"]["spike_carried"] == 0


def test_policy_window_below_one_day_is_unmeasured_not_quiet(tmp_path):
    """На окне 0 дней «продержалась» не определено — это отказ, а не тишина."""
    report = _run(tmp_path, _spike_scene(), params=_Params(min_hold_days=0))
    assert report["measured"] is False
    assert "НЕ ИЗМЕРЕНО" in report["reason"]


def test_missing_history_is_unmeasured_not_ok(tmp_path):
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert report["measured"] is False
    assert census.HISTORY_NAME in report["reason"]
    assert report["status"] != census.STATUS_OK


def test_unparsable_lines_are_counted_not_swallowed(tmp_path):
    rows = _spike_scene()
    path = _history(tmp_path, rows) / census.HISTORY_NAME
    path.write_text(path.read_text(encoding="utf-8") + "{не json\n",
                    encoding="utf-8")
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert report["history"]["unparsable"] == 1
    assert report["counts"]["spike_carried"] == 1


def test_history_without_dated_rows_is_unmeasured(tmp_path):
    report = census.run_census(_history(tmp_path, [{"gain_pp": 1.0}]),
                               now=_ANCHOR, params=_Params())
    assert report["measured"] is False
    assert "НЕ ИЗМЕРЕН" in report["reason"]


# ── 5. сверка формулы с производителем ──────────────────────────────────────

def test_formula_mismatch_refuses_to_grade_the_row(tmp_path):
    """Наша формула расходится со строкой ⇒ строка НЕ судится, причина названа.

    Порванное звено: без сверки контрфакт считался бы формулой, которой
    производитель не пользуется, и находка отвечала бы не на тот вопрос.
    """
    rows = _spike_scene()
    rows[-1]["target_apy_pp"] = rows[-1]["target_apy_pp"] + 1.0
    report = _run(tmp_path, rows)
    graded = report["graded"][-1]
    assert graded["verdict"] == "formula_mismatch"
    assert "target_apy_pp" in graded["reason"]
    assert report["counts"]["formula_mismatch"] == 1
    assert report["counts"]["spike_carried"] == 0


def test_formula_identity_holds_on_the_reproduced_row(tmp_path):
    """Положительный контроль сверки: неиспорченная строка проходит её."""
    rows = _spike_scene()
    row = rows[-1]
    assert census._verify_formula(
        row, row["apy_evidenced_pct"], row["current_positions"],
        row["target_positions"], _CAPITAL) is None


def test_row_without_recorded_blend_is_not_graded(tmp_path):
    rows = _spike_scene()
    rows[-1].pop("target_apy_pp")
    graded = _run(tmp_path, rows)["graded"][-1]
    assert graded["verdict"] == "formula_mismatch"


# ── 6. что вообще попадает в население ──────────────────────────────────────

def test_band_not_cleared_day_is_outside_the_population(tmp_path):
    """Полоса не пройдена ⇒ атрибутировать нечего, и это НЕ находка."""
    rows = _spike_scene()
    rows[-1]["gates"]["gain_above_band"] = False
    report = _run(tmp_path, rows)
    assert report["graded"][-1]["verdict"] == "band_not_cleared"
    assert report["counts"]["band_cleared_days"] == 0
    assert report["status"] == census.STATUS_OK


def test_dust_increase_is_not_material(tmp_path):
    """Прибавка ниже `min_leg_frac` владельца существенной не является.

    Полоса у строки 0.0 пп — такие строки в журнале есть, — поэтому мизерная
    прибавка её формально проходит; существенной она от этого не становится, и
    атрибутировать в ней нечего.
    """
    apy_flat = {"aave_v3": 3.5138, "compound_v3": 3.652, "maple": 8.0}
    book = {"aave_v3": 10_000.0, "compound_v3": 60_000.0, "maple": 20_000.0}
    rows = [_row(d, apy_flat, book, book, gates={"has_legs": False})
            for d in (3, 2, 1)]
    target = dict(book, maple=20_100.0, compound_v3=59_900.0)
    rows.append(_row(0, apy_flat, book, target, required=0.0))
    graded = _run(tmp_path, rows)["graded"][-1]
    assert graded["verdict"] == "no_material_increase"
    assert "существенность" in graded["reason"]


def test_bool_is_not_a_rate(tmp_path):
    """``True`` в ставках не есть 1 % — иначе `bool` тихо стал бы числом."""
    assert census._num(True) is None
    rows = _spike_scene()
    rows[-1]["apy_evidenced_pct"]["maple"] = True
    def blend(pos):
        return sum(v * rows[-1]["apy_evidenced_pct"].get(k, 0.0)
                   for k, v in pos.items() if k != "maple") / _CAPITAL
    rows[-1]["book_apy_pp"] = blend(rows[-1]["current_positions"])
    rows[-1]["target_apy_pp"] = blend(rows[-1]["target_positions"])
    rows[-1]["gain_pp"] = rows[-1]["target_apy_pp"] - rows[-1]["book_apy_pp"]
    report = _run(tmp_path, rows)
    assert report["graded"][-1]["verdict"] == "spike_carried"


# ── 7. вердикт судит настоящее, история остаётся замером ────────────────────

def test_fresh_finding_is_critical(tmp_path):
    report = _run(tmp_path, _spike_scene())
    assert report["status"] == census.STATUS_CRITICAL
    assert report["counts"]["recent_from_now"] == 1


def test_old_finding_is_warning_not_forever_red(tmp_path):
    """Находка старше окна владельца — WARNING: вечно красный учит себя не читать."""
    rows = _spike_scene()
    old = [dict(r) for r in rows]
    for row in old:
        shift = 40
        row["cycle_date"] = (
            datetime.fromisoformat(row["cycle_date"]) - timedelta(days=shift)
        ).date().isoformat()
        row["generated_at"] = (
            datetime.fromisoformat(row["generated_at"]) - timedelta(days=shift)
        ).isoformat()
    report = _run(tmp_path, old)
    assert report["counts"]["spike_carried"] == 1
    assert report["counts"]["recent_from_now"] == 0
    assert report["status"] == census.STATUS_WARNING


def test_no_finding_anywhere_is_ok(tmp_path):
    report = _run(tmp_path, [_quiet_day(3, 3.5), _quiet_day(2, 3.5),
                             _quiet_day(1, 3.5), _quiet_day(0, 3.5)])
    assert report["status"] == census.STATUS_OK
    assert report["no_persistence_gate"] is False


# ── 8. выбор оценки предъявлен числом ───────────────────────────────────────

def test_all_estimators_are_counted_and_headline_is_the_lower_bound(tmp_path):
    report = _run(tmp_path, _spike_scene())
    assert set(report["counts_by_estimator"]) == set(census.ESTIMATORS)
    assert report["estimator"] == census.HEADLINE_ESTIMATOR
    assert report["headline_is_lower_bound"] is True
    assert (report["counts"]["spike_carried"]
            == report["counts_by_estimator"][census.HEADLINE_ESTIMATOR])


def test_headline_stops_claiming_a_lower_bound_when_it_is_not_one(tmp_path):
    """Сцена, где медиана НЕ минимальна, обязана сказать это вслух.

    Прошлые точки 3.0 / 3.0 / 12.0: медиана 3.0 (находка), минимум 3.0
    (находка), среднее 6.0 — оно ВЫШЕ сегодняшних 5.2038 %, подстановки нет
    вовсе и находки нет. Головное число тогда не является нижней границей
    класса, и флаг обязан погаснуть, а не молчать.
    """
    report = _run(tmp_path, _spike_scene(aave_today=5.2038,
                                         prior=(3.0, 3.0, 12.0)))
    counts = report["counts_by_estimator"]
    assert counts["mean"] < counts["median"]
    assert report["headline_is_lower_bound"] is False


# ── 9. артефакт и коды возврата — читается ДИСК, не возвращённое значение ────

def test_artifact_is_written_to_disk(tmp_path):
    (tmp_path / "data").mkdir()
    _history(tmp_path / "data", _spike_scene())
    out = census.run(root=str(tmp_path), now=_ANCHOR)
    assert out["measured"] is True
    on_disk = json.loads(
        (tmp_path / "data" / census.ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert on_disk["counts"]["spike_carried"] == 1
    assert "artifact_not_written" not in out["doc"]


def test_artifact_is_written_even_on_the_third_outcome(tmp_path):
    """«Не измерено» обязано доехать до офиса: иначе его не отличить от «не запускалась»."""
    (tmp_path / "data").mkdir()
    out = census.run(root=str(tmp_path), now=_ANCHOR)
    assert out["measured"] is False
    on_disk = json.loads(
        (tmp_path / "data" / census.ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert on_disk["status"] == census.STATUS_UNMEASURED
    assert on_disk["reason"]


def test_write_failure_is_named_not_swallowed(tmp_path, monkeypatch):
    """Отказ записи обязан быть отличим от успеха у того, кто смотрит на вывод."""
    (tmp_path / "data").mkdir()
    _history(tmp_path / "data", _spike_scene())

    def _boom(report, data_dir):
        raise OSError("read-only")
    monkeypatch.setattr(census, "save_artifact", _boom)
    out = census.run(root=str(tmp_path), now=_ANCHOR)
    assert "read-only" in out["doc"]["artifact_not_written"]


def test_exit_codes_separate_the_three_outcomes(tmp_path):
    (tmp_path / "data").mkdir()
    assert census.main(["--data-dir", str(tmp_path / "data")]) == census.EXIT_UNMEASURED
    _history(tmp_path / "data", _spike_scene())
    assert census.main(["--data-dir", str(tmp_path / "data")]) == 1
    assert census.EXIT_UNMEASURED not in (0, 1)


def test_summary_line_of_the_third_outcome_prints_no_number(tmp_path):
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    line = census.summary_line(report)
    assert "НЕ ИЗМЕРЕНО" in line
    assert "ПРОЙДЕНА РАЗОВЫМ СКАЧКОМ 0" not in line


def test_format_report_names_the_structural_claim_and_the_estimator(tmp_path):
    lines = census.format_report(_run(tmp_path, _spike_scene()))
    body = "\n".join(lines)
    assert "СЛЕПОТА ПО ПОСТРОЕНИЮ" in body
    assert "median" in body
    assert "payback НЕ пересчитан" in body


def test_row_claiming_the_band_against_its_own_numbers_is_refused(tmp_path):
    """Флаг гейта против чисел той же строки ⇒ НЕ судится, а не «скачок».

    Найдено приёмкой #702: без этой сверки лживый `gain_above_band` при выгоде
    НИЖЕ полосы давал находку из ничего — контрфакт сравнивался с полосой, а
    прохождения полосы не было и в записи.
    """
    rows = _spike_scene(aave_today=3.0, prior=(3.5682, 3.5133, 3.5138))
    report = _run(tmp_path, rows)
    graded = report["graded"][-1]
    assert graded["verdict"] == "row_self_inconsistent"
    assert "НЕ ИЗМЕРЕНА" in graded["reason"]
    assert "recorded_gain_pp" not in graded   # строка не судится — числа не выдаются
    assert report["counts"]["row_self_inconsistent"] == 1
    assert report["counts"]["spike_carried"] == 0
