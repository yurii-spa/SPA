#!/usr/bin/env python3
"""Контроль переписи удержания ставки — критерий §49 `Persistence` приказа CIO.

Каждый тест здесь — либо ВОСПРОИЗВЕДЕНИЕ настоящего исхода из журнала ходов,
либо контроль звена в обратную сторону: порванное звено обязано КРАСНЕТЬ, и
звено названо в имени теста. Проверка, никогда не видевшая настоящей поломки,
есть украшение (`.claude/rules/deployment.md`).

Эталон воспроизводится дословно — замер 27.09 по живому `data/`:

* **T022** (2026-08-28, оборот $40 000): на входе преимущество **+0.5920 пп**,
  то есть планка владельца 0.50 пп ПРОЙДЕНА, а за 30 наблюдённых дней
  горизонта — **−0.1569 пп**. Больше всех в падение внёс `aave_v3` как
  ИСТОЧНИК: 3.3364 пп на входе → 4.9934 пп в среднем по горизонту. Деньги ушли
  из протокола на его собственной просадке, и она не продержалась.
* **`pendle`**: книга двигала им $76 644, а накопитель ставок не наблюдал его
  НИ ОДНОГО дня; поверхность решения знала его 28 дней, последняя ставка
  14.0048 пп (2026-09-06). Ближайший по ЗНАЧЕНИЮ ключ накопителя расходится на
  8.6 пп — то есть «это он под другим именем» замером НЕ подтверждается.
* **поверхность решения несёт максимум ОДИН день наблюдения на запись** —
  значит гейта, требующего, чтобы преимущество продержалось, из такой записи
  не выводится ни при каком пороге.

# FROZEN-DATE-OK: injected-clock — все отметки сцен происходят от якоря
# `_ANCHOR` (см. `_ts` и `_day`), и ОН ЖЕ передаётся прибору аргументом `now=`;
# ни одна проверка этого файла не спрашивает время у машины, поэтому сдвиг
# календаря вердикта здесь не меняет.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from spa_core.monitoring import apy_persistence_census as census

#: Якорь сцен. От него происходят ВСЕ отметки и он же идёт в `now=`.
_ANCHOR = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


def _ts(days_before: float) -> str:
    """Отметка за N суток до якоря — обе стороны сцены закреплены якорем."""
    return (_ANCHOR - timedelta(days=days_before)).isoformat()


def _day(days_before: float) -> str:
    """Дата за N суток до якоря."""
    return (_ANCHOR - timedelta(days=days_before)).date().isoformat()


class _Params:
    """Колонка порогов ADR-060 §3 как ВХОД сцены, а не как живой файл."""

    def __init__(self, min_gain_pp: float = 0.50, max_payback_days: float = 30.0,
                 min_leg_frac: float = 0.005, mode: str = "paper",
                 version: str = "test") -> None:
        self.min_gain_pp = min_gain_pp
        self.max_payback_days = max_payback_days
        self.min_leg_frac = min_leg_frac
        self.mode = mode
        self.version = version


def _move(trade_id: str, days_before: float, frm: dict, to: dict,
          capital: float = 100_000.0) -> dict:
    return {"trade_id": trade_id, "ts": _ts(days_before),
            "from_allocation": frm, "to_allocation": to, "capital": capital}


def _scene(tmp_path: Path, moves: List[dict],
           rates: Dict[str, Dict[str, float]],
           surface: Optional[List[dict]] = None) -> Path:
    """Одноразовая сцена: журнал ходов, накопитель ставок, поверхность решения.

    ``rates`` — ``{дата: {ключ: пп}}``; накопитель на диске хранит обратную
    форму, и перевод делается здесь, чтобы сцены читались по дням.
    """
    (tmp_path / census.JOURNAL_NAME).write_text(json.dumps(moves),
                                                encoding="utf-8")
    series: Dict[str, List[list]] = {}
    for day in sorted(rates):
        for key, value in rates[day].items():
            series.setdefault(key, []).append([day, value])
    (tmp_path / census.SERIES_NAME).write_text(
        json.dumps({"generated_at": _ts(0), "series": series}), encoding="utf-8")
    if surface is not None:
        (tmp_path / census.SURFACE_NAME).write_text(
            "\n".join(json.dumps(rec) for rec in surface) + "\n",
            encoding="utf-8")
    return tmp_path


def _flat(days: List[float], rates: Dict[str, float]) -> Dict[str, Dict[str, float]]:
    """Одни и те же ставки на перечисленных днях — ставка держится идеально."""
    return {_day(d): dict(rates) for d in days}


# ── эталон T022: преимущество прошло планку и не продержалось ────────────────

def _t022_scene(tmp_path: Path, *, source_recovers: bool = True) -> Path:
    """Сцена хода T022 замером 27.09: $40 000 уходят из `aave_v3`.

    На входе `aave_v3` даёт 3.3364 пп, приёмники — 4.99 пп; через день источник
    восстанавливается до 4.9934 пп, и преимущество исчезает. ``source_recovers``
    гасит именно это восстановление — тогда преимущество обязано удержаться.
    """
    entry = 30.0
    rates = {_day(entry): {"aave_v3": 3.3364, "compound_v3": 4.99,
                           "morpho_steakhouse": 4.99}}
    for step in range(1, 31):
        rates[_day(entry - step)] = {
            "aave_v3": 4.9934 if source_recovers else 3.3364,
            "compound_v3": 4.99, "morpho_steakhouse": 4.99}
    move = _move("T022", entry,
                 {"aave_v3": 40_000.0, "compound_v3": 40_000.0,
                  "morpho_steakhouse": 15_000.0},
                 {"aave_v3": 0.0, "compound_v3": 60_000.0,
                  "morpho_steakhouse": 35_000.0})
    return _scene(tmp_path, [move], rates)


def test_t022_advantage_cleared_the_owner_band_and_then_died(tmp_path: Path) -> None:
    """Настоящий исход: планка пройдена на входе, за горизонт — ниже планки."""
    data = _t022_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["measured"] is True
    faded = rep["faded"]
    assert [m["trade_id"] for m in faded] == ["T022"]
    item = faded[0]
    assert item["entry_gain_pp"] >= rep["policy"]["min_gain_pp"]
    assert item["realized_gain_pp"] < rep["policy"]["min_gain_pp"]
    assert item["decay_pp"] > 0
    assert item["klass"] == census.KLASS_FADED


def test_when_the_source_does_not_recover_the_same_move_is_persisted(tmp_path: Path) -> None:
    """Контроль в обратную сторону: без восстановления источника — `persisted`."""
    data = _t022_scene(tmp_path, source_recovers=False)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["faded"] == []
    assert [m["trade_id"] for m in rep["moves"]
            if m["klass"] == census.KLASS_PERSISTED] == ["T022"]
    assert rep["status"] == census.STATUS_OK


def test_decay_is_attributed_to_the_source_not_to_the_target(tmp_path: Path) -> None:
    """Чья ставка поехала — замер, а не догадка: у T022 это ИСТОЧНИК `aave_v3`."""
    data = _t022_scene(tmp_path)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    top = rep["faded"][0]["decay_attribution"][0]
    assert top["protocol"] == "aave_v3"
    assert top["delta_usd"] < 0          # источник, а не цель
    assert top["mean_rate_over_horizon_pp"] > top["rate_at_entry_pp"]
    assert top["contribution_to_decay_pp"] > 0


def test_attribution_contributions_sum_to_the_whole_decay(tmp_path: Path) -> None:
    """Вклады обязаны складываться в падение целиком — иначе виновник назван на глаз."""
    data = _t022_scene(tmp_path)
    item = census.run_census(data, now=_ANCHOR, params=_Params())["faded"][0]
    total = sum(row["contribution_to_decay_pp"] for row in item["decay_attribution"])
    assert abs(total - item["decay_pp"]) < 0.01


# ── вердикт судит НАСТОЯЩЕЕ, история остаётся замером ────────────────────────

def test_fresh_faded_move_is_critical_and_old_one_is_only_warning(tmp_path: Path) -> None:
    """Горизонт окупаемости ещё открыт ⇒ CRITICAL; закрыт ⇒ WARNING."""
    fresh = _t022_scene(tmp_path)
    rep = census.run_census(fresh, now=_ANCHOR, params=_Params())
    assert rep["status"] == census.STATUS_CRITICAL
    assert rep["counts"]["harm_with_open_horizon"] == 1

    # Тот же ход, но увиденный на 40 суток позже: горизонт владельца закрыт.
    later = _ANCHOR + timedelta(days=40)
    rep_late = census.run_census(fresh, now=later, params=_Params())
    assert rep_late["status"] == census.STATUS_WARNING
    assert rep_late["counts"]["harm_total"] == 1
    assert rep_late["counts"]["harm_with_open_horizon"] == 0


def test_a_book_that_never_bought_a_fading_advantage_is_ok(tmp_path: Path) -> None:
    """OK существует: ни одного хода с упавшим преимуществом за весь журнал."""
    days = [d for d in range(31, -1, -1)]
    rates = _flat([float(d) for d in days],
                  {"aave_v3": 3.0, "compound_v3": 5.0})
    move = _move("T001", 31.0, {"aave_v3": 50_000.0}, {"compound_v3": 50_000.0})
    data = _scene(tmp_path, [move], rates)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["status"] == census.STATUS_OK
    assert rep["counts"]["harm_total"] == 0
    assert rep["counts"]["persisted"] == 1


# ── породы не смешиваются ───────────────────────────────────────────────────

def test_a_move_negative_at_entry_is_a_separate_breed_not_this_criterion(tmp_path: Path) -> None:
    """Ход, убыточный уже на входе, спайком вызван быть не мог — своя порода."""
    entry = 5.0
    rates = {_day(entry - step): {"aave_v3": 3.0, "compound_v3": 5.0}
             for step in range(0, 6)}
    move = _move("T009", entry, {"compound_v3": 40_000.0}, {"aave_v3": 40_000.0})
    data = _scene(tmp_path, [move], rates)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["counts"]["negative_at_entry"] == 1
    assert rep["counts"]["harm_total"] == 0
    assert rep["status"] == census.STATUS_OK
    assert rep["moves"][0]["klass"] == census.KLASS_NEGATIVE_AT_ENTRY


def test_sign_flip_below_the_owner_band_is_counted_apart_from_faded(tmp_path: Path) -> None:
    """Преимущество ниже планки, но перевернувшееся в минус, — свой счётчик."""
    entry = 10.0
    rates = {_day(entry): {"aave_v3": 3.0, "compound_v3": 3.2}}
    for step in range(1, 11):
        rates[_day(entry - step)] = {"aave_v3": 3.6, "compound_v3": 3.2}
    move = _move("T015", entry, {"aave_v3": 40_000.0}, {"compound_v3": 40_000.0})
    rep = census.run_census(_scene(tmp_path, [move], rates), now=_ANCHOR,
                            params=_Params())
    assert rep["counts"]["sign_flipped"] == 1
    assert rep["counts"]["faded_below_owner_band"] == 0
    assert rep["moves"][0]["entry_gain_pp"] < rep["policy"]["min_gain_pp"]


# ── третий исход: «не измерено» не выдаётся ни за «чисто», ни за ноль ────────

def test_move_older_than_the_accumulator_is_unmeasured_with_a_named_reason(tmp_path: Path) -> None:
    """Ход старше первого наблюдённого дня — НЕ ИЗМЕРЕН, а не «держалась»."""
    rates = _flat([3.0, 2.0, 1.0, 0.0], {"aave_v3": 3.0, "compound_v3": 5.0})
    old = _move("T001", 99.0, {"aave_v3": 50_000.0}, {"compound_v3": 50_000.0})
    good = _move("T030", 3.0, {"aave_v3": 50_000.0}, {"compound_v3": 50_000.0})
    rep = census.run_census(_scene(tmp_path, [old, good], rates), now=_ANCHOR,
                            params=_Params())
    hit = [m for m in rep["unmeasured_moves"] if m["trade_id"] == "T001"]
    assert len(hit) == 1
    assert "старше накопителя" in hit[0]["reason"]
    assert hit[0]["klass"] == census.KLASS_UNMEASURED
    # И оборот неизмеримого хода назван, а не растворён.
    assert rep["turnover_unmeasured_usd"] >= 50_000.0


def test_unpriced_leg_on_the_entry_day_refuses_the_whole_move(tmp_path: Path) -> None:
    """Нога без ставки в день входа — день не оценивается ЦЕЛИКОМ (fail-CLOSED)."""
    entry = 5.0
    rates = {_day(entry - step): {"compound_v3": 5.0} for step in range(0, 6)}
    move = _move("T033", entry, {"compound_v3": 20_000.0}, {"pendle": 20_000.0})
    rep = census.run_census(_scene(tmp_path, [move], rates), now=_ANCHOR,
                            params=_Params())
    assert rep["measured"] is False          # других ходов в сцене нет
    assert rep["status"] == census.STATUS_UNMEASURED
    item = rep["unmeasured_moves"][0]
    assert item["missing_protocols"] == ["pendle"]
    assert "pendle" in item["reason"]


def test_no_forward_day_priced_is_unmeasured_not_persisted(tmp_path: Path) -> None:
    """Вперёд ни одного оценённого дня — исход НЕ ИЗМЕРЕН, а не «удержалось»."""
    entry = 1.0
    rates = {_day(entry): {"aave_v3": 3.0, "compound_v3": 9.0}}
    move = _move("T034", entry, {"aave_v3": 40_000.0}, {"compound_v3": 40_000.0})
    rep = census.run_census(_scene(tmp_path, [move], rates), now=_ANCHOR,
                            params=_Params())
    assert rep["measured"] is False
    assert "ни один день не оценён" in rep["unmeasured_moves"][0]["reason"]


def test_missing_owner_column_is_the_third_outcome_not_a_default(tmp_path: Path) -> None:
    """Колонка без нужных полей ⇒ НЕ ИЗМЕРЕНО: подставлять свои числа нельзя."""
    class _Broken:
        min_gain_pp = "не число"
    rep = census.run_census(tmp_path, now=_ANCHOR, params=_Broken())
    assert rep["measured"] is False
    assert rep["status"] == census.STATUS_UNMEASURED
    assert "НЕ ИЗМЕРЕНО" in rep["reason"]


def test_nonpositive_horizon_is_refused_rather_than_silently_empty(tmp_path: Path) -> None:
    """Горизонт ≤ 0: вперёд смотреть некуда — отказ, а не пустой зелёный замер."""
    rep = census.run_census(tmp_path, now=_ANCHOR,
                            params=_Params(max_payback_days=0.0))
    assert rep["measured"] is False
    assert "горизонт окупаемости" in rep["reason"]


def test_missing_series_is_unmeasured_and_says_so(tmp_path: Path) -> None:
    """Накопителя ставок нет ⇒ третий исход с названной дверью."""
    (tmp_path / census.JOURNAL_NAME).write_text(json.dumps([
        _move("T001", 3.0, {"aave_v3": 50_000.0}, {"compound_v3": 50_000.0})]),
        encoding="utf-8")
    rep = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert rep["measured"] is False
    assert census.SERIES_NAME in rep["reason"]


def test_missing_journal_is_unmeasured_and_not_a_quiet_book(tmp_path: Path) -> None:
    """Журнала ходов нет ⇒ НЕ ИЗМЕРЕНО, и это сказано вслух."""
    rep = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert rep["measured"] is False
    assert "НЕ «ставки держались»" in rep["reason"]


def test_unreadable_series_refuses_instead_of_reading_zero_days(tmp_path: Path) -> None:
    """Битый JSON накопителя — отказ, а не «дней наблюдения ноль»."""
    (tmp_path / census.JOURNAL_NAME).write_text(json.dumps([
        _move("T001", 3.0, {"aave_v3": 50_000.0}, {"compound_v3": 50_000.0})]),
        encoding="utf-8")
    (tmp_path / census.SERIES_NAME).write_text("{не json", encoding="utf-8")
    rep = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert rep["measured"] is False
    assert "нечитаем" in rep["reason"]


def test_gain_model_is_borrowed_and_its_absence_is_the_third_outcome() -> None:
    """Модель дневной выгоды — ЧУЖАЯ; её отсутствие ⇒ НЕ ИЗМЕРЕНО, не своя формула."""
    got = census.load_gain_model()
    assert got["measured"] is True
    from spa_core.paper_trading import shadow_trigger_eval
    assert got["day_gain_usd"] is shadow_trigger_eval._day_gain_usd


def test_day_is_refused_whole_when_one_leg_is_unpriced_in_the_borrowed_model() -> None:
    """Свойство, на которое прибор опирается: частичная оценка дня запрещена."""
    model = census.load_gain_model()["day_gain_usd"]
    gain, missing = model({"aave_v3": 100.0, "pendle": -100.0}, {"aave_v3": 5.0})
    assert gain is None
    assert missing == ["pendle"]


# ── ключ книги, которого накопитель не наблюдал ни одного дня ────────────────

def test_book_key_absent_from_the_accumulator_is_named_with_what_is_known(tmp_path: Path) -> None:
    """Эталон `pendle`: ключ двигал деньги, а наблюдённой ставки нет ни одной."""
    entry = 5.0
    rates = {_day(entry - step): {"compound_v3": 5.0, "moonwell_base": 5.4}
             for step in range(0, 6)}
    move = _move("T033", entry, {"compound_v3": 20_000.0}, {"pendle": 20_000.0})
    # Дни поверхности лежат ВНУТРИ дней накопителя — иначе общих дней меньше
    # двух и вопрос о ближайшем по значению ключе честно не имеет ответа (на
    # это есть свой контроль ниже). ПОЗДНИЙ день — `entry - 1`: «последняя
    # ставка» обязана быть его, а не той, что стои́т в файле первой строкой.
    surface = [{"cycle_date": _day(entry),
                "apy_evidenced_pct": {"pendle": 13.9654, "compound_v3": 5.0},
                "apy_as_of": {"pendle": _ts(entry)},
                "gates": {"gain_above_band": True}},
               {"cycle_date": _day(entry - 1),
                "apy_evidenced_pct": {"pendle": 14.0048, "compound_v3": 5.0},
                "apy_as_of": {"pendle": _ts(entry - 1)},
                "gates": {"gain_above_band": True}}]
    data = _scene(tmp_path, [move], rates, surface=surface)
    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    absent = {item["book_key"]: item for item in rep["absent_from_series"]}
    assert "pendle" in absent
    hit = absent["pendle"]
    assert hit["moved_usd_total"] == pytest.approx(20_000.0)
    assert hit["days_on_decision_surface"] == 2
    assert hit["last_seen_day"] == _day(entry - 1)
    assert hit["last_seen_rate_pp"] == pytest.approx(14.0048)
    # Ближайший ПО ЗНАЧЕНИЮ ключ назван, и расхождение — величина, а не вердикт.
    near = hit["nearest_series_key_by_value"]
    assert near["series_key"] == "moonwell_base"   # 5.4 ближе к 14, чем 5.0
    assert near["shared_days"] == 2
    assert near["mean_gap_pp"] > 8.0
    # Вердикта «это тот же пул» прибор не выносит: порога близости владелец не
    # назначал, и заводить свой было бы своим числом в приборе (§22).
    assert "alias_confirmed" not in hit


def test_alias_question_without_shared_days_has_no_answer_rather_than_a_guess(tmp_path: Path) -> None:
    """Общих дней меньше двух ⇒ ближайшего ключа НЕТ, а не «наверное, вот этот»."""
    entry = 5.0
    rates = {_day(entry - step): {"compound_v3": 5.0} for step in range(0, 6)}
    move = _move("T033", entry, {"compound_v3": 20_000.0}, {"pendle": 20_000.0})
    surface = [{"cycle_date": _day(entry + 9),
                "apy_evidenced_pct": {"pendle": 14.0},
                "gates": {"gain_above_band": True}}]
    rep = census.run_census(_scene(tmp_path, [move], rates, surface=surface),
                            now=_ANCHOR, params=_Params())
    hit = rep["absent_from_series"][0]
    assert hit["book_key"] == "pendle"
    assert hit["nearest_series_key_by_value"] is None
    assert hit["days_on_decision_surface"] == 1


def test_a_key_the_accumulator_does_observe_is_not_reported_as_absent(tmp_path: Path) -> None:
    """Контроль в обратную сторону: наблюдаемый ключ в перечень НЕ попадает."""
    entry = 5.0
    rates = {_day(entry - step): {"compound_v3": 5.0, "pendle": 14.0}
             for step in range(0, 6)}
    move = _move("T033", entry, {"compound_v3": 20_000.0}, {"pendle": 20_000.0})
    rep = census.run_census(_scene(tmp_path, [move], rates), now=_ANCHOR,
                            params=_Params())
    assert [i["book_key"] for i in rep["absent_from_series"]] == []
    assert rep["counts"]["book_keys_absent_from_series"] == 0


# ── по построению: решение видит один день ───────────────────────────────────

def test_one_observation_day_per_decision_means_persistence_is_unrepresentable(tmp_path: Path) -> None:
    """Эталон: запись вердикта несёт один день ⇒ гейт про удержание невыводим."""
    surface = [{"cycle_date": _day(2), "apy_as_of": {"a": _ts(2), "b": _ts(2)},
                "gates": {"gain_above_band": True, "min_hold_ok": True}},
               {"cycle_date": _day(1), "apy_as_of": {"a": _ts(1)},
                "gates": {"cooldown_ok": False}}]
    got = census.gate_surface_claim(census.read_surface(
        _scene(tmp_path, [], {}, surface=surface)))
    assert got["measured"] is True
    assert got["max_distinct_observation_days"] == 1
    assert got["persistence_representable_in_decision"] is False
    assert got["gate_keys"] == ["cooldown_ok", "gain_above_band", "min_hold_ok"]


def test_two_observation_days_in_one_record_would_make_it_representable(tmp_path: Path) -> None:
    """Контроль в обратную сторону: два дня в записи — и утверждение падает."""
    surface = [{"cycle_date": _day(1),
                "apy_as_of": {"a": _ts(1), "b": _ts(2)},
                "gates": {"gain_above_band": True}}]
    got = census.gate_surface_claim(census.read_surface(
        _scene(tmp_path, [], {}, surface=surface)))
    assert got["max_distinct_observation_days"] == 2
    assert got["persistence_representable_in_decision"] is True


def test_absent_surface_gates_only_that_claim_not_the_whole_census(tmp_path: Path) -> None:
    """Поверхности нет ⇒ гаснет ОДНО утверждение, замер ходов остаётся."""
    days = [float(d) for d in range(5, -1, -1)]
    rates = _flat(days, {"aave_v3": 3.0, "compound_v3": 5.0})
    move = _move("T030", 5.0, {"aave_v3": 50_000.0}, {"compound_v3": 50_000.0})
    rep = census.run_census(_scene(tmp_path, [move], rates), now=_ANCHOR,
                            params=_Params())
    assert rep["measured"] is True
    assert rep["gate_surface"]["measured"] is False
    assert rep["counts"]["moves_measured"] == 1


# ── пороги и существенность — владельца, не прибора ─────────────────────────

def test_the_owner_band_is_the_only_bar_and_moving_it_moves_the_verdict(tmp_path: Path) -> None:
    """Планка — вход: подняв её, тот же ход перестаёт быть «прошедшим планку»."""
    data = _t022_scene(tmp_path)
    strict = census.run_census(data, now=_ANCHOR, params=_Params(min_gain_pp=2.0))
    assert strict["counts"]["faded_below_owner_band"] == 0
    assert strict["counts"]["sign_flipped"] == 1     # знак всё равно перевернулся
    loose = census.run_census(data, now=_ANCHOR, params=_Params(min_gain_pp=0.5))
    assert loose["counts"]["faded_below_owner_band"] == 1


def test_horizon_length_comes_from_the_owner_column(tmp_path: Path) -> None:
    """Горизонт — вход: короткий горизонт видит меньше дней, и это видно в отчёте."""
    data = _t022_scene(tmp_path)
    short = census.run_census(data, now=_ANCHOR, params=_Params(max_payback_days=3.0))
    assert short["moves"][0]["horizon_days"] == 3
    assert short["moves"][0]["forward_days_checked"] == 3


def test_dust_leg_below_the_owner_materiality_is_not_a_move(tmp_path: Path) -> None:
    """Пыль ниже `min_leg_frac` ходом не считается — и это НЕ «преимущество держалось»."""
    days = [float(d) for d in range(5, -1, -1)]
    rates = _flat(days, {"aave_v3": 3.0, "compound_v3": 5.0})
    dust = _move("T099", 5.0, {"aave_v3": 100.0, "compound_v3": 50_000.0},
                 {"aave_v3": 0.0, "compound_v3": 50_100.0})
    rep = census.run_census(_scene(tmp_path, [dust], rates), now=_ANCHOR,
                            params=_Params())
    assert rep["measured"] is False
    assert "существеннее" in rep["unmeasured_moves"][0]["reason"]


# ── отчёт и артефакт: читатель обязан получить всё это на диске ──────────────

def test_report_lines_name_the_door_and_never_hide_the_third_outcome(tmp_path: Path) -> None:
    """Печать называет породу, колонку и «не измерено» — каждое своей строкой."""
    data = _t022_scene(tmp_path)
    lines = census.format_report(census.run_census(data, now=_ANCHOR,
                                                   params=_Params()))
    assert any("ПРЕИМУЩЕСТВО НЕ УДЕРЖАЛОСЬ" in line for line in lines)
    assert any("[КОЛОНКА]" in line for line in lines)
    assert any("ПО ПОСТРОЕНИЮ" in line for line in lines)


def test_unmeasured_report_prints_as_unmeasured_not_as_ok(tmp_path: Path) -> None:
    """Третий исход в печати — «НЕ ИЗМЕРЕНО», и ни одной строки про удержание."""
    lines = census.format_report(census.run_census(tmp_path, now=_ANCHOR,
                                                   params=_Params()))
    assert len(lines) == 1
    assert "НЕ ИЗМЕРЕНО" in lines[0]


def test_hidden_line_count_is_measured_per_section(tmp_path: Path) -> None:
    """Скрытых строк столько, сколько СКРЫТО: разность по секциям, не по итогу."""
    entry = 30.0
    rates = {_day(entry): {"aave_v3": 3.0, "compound_v3": 9.0}}
    for step in range(1, 31):
        rates[_day(entry - step)] = {"aave_v3": 9.0, "compound_v3": 9.0}
    moves = [_move(f"T{i:03d}", entry, {"aave_v3": 40_000.0},
                   {"compound_v3": 40_000.0}) for i in range(1, 4)]
    rep = census.run_census(_scene(tmp_path, moves, rates), now=_ANCHOR,
                            params=_Params())
    assert rep["counts"]["faded_below_owner_band"] == 3
    lines = census.format_report(rep, limit=1)
    hidden = [line for line in lines if line.startswith("… ещё")]
    assert hidden and hidden[0].startswith("… ещё 2 ")


def test_artifact_reaches_the_disk_and_carries_the_third_outcome(tmp_path: Path) -> None:
    """Артефакт читается С ДИСКА — иначе отказ записи неотличим от успеха."""
    (tmp_path / "data").mkdir()
    got = census.run(root=str(tmp_path), now=_ANCHOR)
    path = tmp_path / "data" / census.ARTIFACT_NAME
    assert path.exists(), "ступень доложила исход, а файла на диске нет"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["measured"] is False
    assert doc["status"] == census.STATUS_UNMEASURED
    assert got["measured"] is False


def test_bridge_stage_writes_the_measured_report_to_disk(tmp_path: Path) -> None:
    """Тот же контроль на измеренной сцене: на диске лежит именно замер."""
    data = (tmp_path / "data")
    data.mkdir()
    _t022_scene(data)
    got = census.run(root=str(tmp_path), now=_ANCHOR)
    doc = json.loads((data / census.ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert doc["measured"] is True
    assert doc["faded"][0]["trade_id"] == "T022"
    assert got["doc"]["status"] == doc["status"]


def test_exit_code_is_three_when_nothing_could_be_measured(tmp_path: Path) -> None:
    """Код возврата: 3 — «не измерено», и это не ноль."""
    assert census.main(["--data-dir", str(tmp_path)]) == census.EXIT_UNMEASURED


def test_exit_code_is_one_on_a_fresh_faded_move_and_zero_on_a_quiet_book(tmp_path: Path) -> None:
    """Код 1 — только на то, что решается сегодня; на тихой книге 0."""
    fresh = _t022_scene(tmp_path)
    assert census.main(["--data-dir", str(fresh)]) == 1

    quiet = tmp_path / "quiet"
    quiet.mkdir()
    days = [float(d) for d in range(5, -1, -1)]
    _scene(quiet, [_move("T001", 5.0, {"aave_v3": 50_000.0},
                         {"compound_v3": 50_000.0})],
           _flat(days, {"aave_v3": 3.0, "compound_v3": 5.0}))
    assert census.main(["--data-dir", str(quiet)]) == 0


# ── `True` — не ставка и не доллар (мутация, выжившая в первом прогоне) ──────

def test_boolean_rate_is_not_read_as_one_percent(tmp_path: Path) -> None:
    """`true` в накопителе — НЕ ставка 1 %: день остаётся неоценённым."""
    entry = 3.0
    rates = {_day(entry - step): {"aave_v3": 3.0, "compound_v3": 9.0}
             for step in range(0, 4)}
    data = _scene(tmp_path, [_move("T001", entry, {"aave_v3": 40_000.0},
                                   {"compound_v3": 40_000.0})], rates)
    # Подменяем ставку дня входа на `true` прямо на диске — так, как её мог бы
    # записать сломавшийся производитель.
    doc = json.loads((data / census.SERIES_NAME).read_text(encoding="utf-8"))
    doc["series"]["compound_v3"] = [
        [day, True] if day == _day(entry) else [day, value]
        for day, value in doc["series"]["compound_v3"]]
    (data / census.SERIES_NAME).write_text(json.dumps(doc), encoding="utf-8")

    rep = census.run_census(data, now=_ANCHOR, params=_Params())
    assert rep["measured"] is False
    item = rep["unmeasured_moves"][0]
    assert item["missing_protocols"] == ["compound_v3"]


def test_boolean_position_amount_is_not_read_as_one_dollar(tmp_path: Path) -> None:
    """`true` в книге — не $1: нога считается по числам, а не по правдивости.

    Существенность здесь нарочно опущена до $0.10, иначе «$1» отсеялся бы как
    пыль и сцена не отличала бы правильный разбор от подстановки единицы.
    """
    days = [float(d) for d in range(3, -1, -1)]
    move = _move("T001", 3.0, {"aave_v3": 50_000.0, "sfrax": 0.0},
                 {"aave_v3": 50_000.0, "sfrax": True})
    rep = census.run_census(
        _scene(tmp_path, [move], _flat(days, {"aave_v3": 3.0})),
        now=_ANCHOR, params=_Params(min_leg_frac=1e-6))
    assert rep["measured"] is False
    item = rep["unmeasured_moves"][0]
    # Ключа `sfrax` в ногах нет вовсе — значит `True` не стал долларом.
    assert "missing_protocols" not in item
    assert "существеннее" in item["reason"]


def test_unread_surface_does_not_claim_nobody_knew_the_key(tmp_path: Path) -> None:
    """Поверхность не прочитана ⇒ «дней ноль» НЕ утверждается (инв. #17).

    Контроль разницы двух исходов: прочитанная поверхность без этого ключа даёт
    измеренный НОЛЬ дней, непрочитанная — `None` с названной причиной.
    """
    entry = 3.0
    rates = {_day(entry - step): {"compound_v3": 5.0} for step in range(0, 4)}
    move = _move("T033", entry, {"compound_v3": 20_000.0}, {"pendle": 20_000.0})

    blind = census.run_census(_scene(tmp_path, [move], rates), now=_ANCHOR,
                              params=_Params())
    hit = blind["absent_from_series"][0]
    assert hit["decision_surface_read"] is False
    assert hit["days_on_decision_surface"] is None
    assert hit["decision_surface_reason"]
    assert any("НЕ ПРОЧИТАНА" in line for line in census.format_report(blind))

    seeing = tmp_path / "seen"
    seeing.mkdir()
    _scene(seeing, [move], rates,
           surface=[{"cycle_date": _day(entry), "apy_evidenced_pct": {"compound_v3": 5.0},
                     "gates": {"gain_above_band": True}}])
    read = census.run_census(seeing, now=_ANCHOR, params=_Params())
    hit2 = read["absent_from_series"][0]
    assert hit2["decision_surface_read"] is True
    assert hit2["days_on_decision_surface"] == 0
