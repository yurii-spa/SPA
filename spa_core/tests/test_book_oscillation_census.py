#!/usr/bin/env python3
"""Контроль переписи прыжков книги — критерий §49 `Anti-churn` приказа CIO.

Каждый тест здесь — либо ВОСПРОИЗВЕДЕНИЕ настоящего исхода из журнала ходов,
либо контроль звена в обратную сторону: порванное звено обязано КРАСНЕТЬ, и
звено названо в имени теста. Проверка, никогда не видевшая настоящей поломки,
есть украшение (`.claude/rules/deployment.md`).

Эталон воспроизводится дословно: ходы **T033** (2026-09-08) и **T034**
(2026-09-11) журнала `data/trades.json` — книга ушла в `pendle` на $20 000 и
вернулась ровно туда, откуда ушла, с остатком $0.00 за 83.1 ч, заплатив
$20 263.16 оборота в каждую сторону. Между этими записями лежит переименование
`fluid_usdc` → `fluid_fusdc` (класс, независимо названный
`scripts/book_second_record.py` как T034), и без его разрешения возврат не
опознаётся вовсе — на это есть свой контроль в обе стороны.

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

from spa_core.monitoring import book_oscillation_census as census

#: Якорь сцен. От него происходят ВСЕ отметки и он же идёт в `now=`.
_ANCHOR = datetime(2026, 9, 26, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_before: float) -> str:
    """Отметка за N часов до якоря — обе стороны сцены закреплены якорем."""
    return (_ANCHOR - timedelta(hours=hours_before)).isoformat()


class _Params:
    """Колонка порогов ADR-060 §3 как ВХОД сцены, а не как живой файл."""

    def __init__(self, min_leg_frac: float = 0.005,
                 reversal_window_days: float = 14.0,
                 mode: str = "paper", version: str = "test") -> None:
        self.min_leg_frac = min_leg_frac
        self.reversal_window_days = reversal_window_days
        self.mode = mode
        self.version = version


def _journal(tmp_path: Path, rows: list) -> Path:
    (tmp_path / census.JOURNAL_NAME).write_text(
        json.dumps(rows), encoding="utf-8")
    return tmp_path


def _move(trade_id: str, hours_before: float, frm: dict, to: dict,
          delta_abs: float | None = None) -> dict:
    row = {"trade_id": trade_id, "ts": _ts(hours_before),
           "from_allocation": frm, "to_allocation": to}
    if delta_abs is not None:
        row["delta_abs"] = delta_abs
    return row


# ── эталон: настоящий возврат T033→T034 ─────────────────────────────────────

#: Книга перед T033 — дословно из журнала.
_BOOK_BEFORE = {"compound_v3": 40000.0, "fluid_usdc": 20000.0, "maple": 20000.0,
                "morpho_blue_base": 10000.0, "aave_v3": 5000.0}
#: Книга после T033 — ушли в `pendle`.
_BOOK_AFTER = {"pendle": 20000.0, "fluid_usdc": 20000.0, "compound_v3": 40000.0,
               "aave_v3": 4736.84, "maple": 5263.16, "morpho_blue_base": 4736.84}


def _real_incident(tmp_path: Path) -> Path:
    """T033 → T034 со стыковым переименованием, как это лежит в журнале."""
    after_renamed = {("fluid_fusdc" if k == "fluid_usdc" else k): v
                     for k, v in _BOOK_AFTER.items()}
    back_renamed = {("fluid_fusdc" if k == "fluid_usdc" else k): v
                    for k, v in _BOOK_BEFORE.items()}
    return _journal(tmp_path, [
        _move("T033", 90.0, _BOOK_BEFORE, _BOOK_AFTER, delta_abs=20263.16),
        _move("T034", 6.9, after_renamed, back_renamed, delta_abs=20263.16),
    ])


def test_the_real_t033_t034_round_trip_is_found(tmp_path):
    """Эталон: возврат за два хода с остатком $0.00 и двойной платой."""
    report = census.run_census(_real_incident(tmp_path), now=_ANCHOR,
                               params=_Params())
    assert report["measured"] is True
    assert report["counts"]["returns_total"] == 1
    found = report["returns"][0]
    assert (found["from_trade"], found["to_trade"]) == ("T033", "T034")
    assert found["residual_usd"] == 0.0, "книга вернулась РОВНО туда же"
    assert found["moves_spanned"] == 2
    assert found["turnover_usd"] == pytest.approx(40526.32, abs=0.01)
    assert found["span_hours"] == pytest.approx(83.1, abs=0.1)


def test_the_seam_rename_is_measured_not_invented(tmp_path):
    """Псевдоним берётся со СТЫКА записей, и берётся именно тот, что в журнале."""
    report = census.run_census(_real_incident(tmp_path), now=_ANCHOR,
                               params=_Params())
    assert report["aliases"] == {"fluid_usdc": "fluid_fusdc"}
    assert report["alias_seams"][0]["between"] == ["T033", "T034"]


def test_without_the_alias_the_rename_MASKS_the_round_trip(tmp_path):
    """Обратная сторона того же звена: неразрешённое переименование СКРЫВАЕТ прыжок.

    Это не украшение: расхождение $40 000 из $95 000 (42 %) уводит возврат за
    любой разумный порог, то есть дословная сверка ключей объявила бы книгу
    спокойной. Порви звено псевдонимов — находка исчезает.
    """
    journal = census.read_journal(_real_incident(tmp_path))
    moves = journal["moves"]
    # Существенность — та же доля владельца от книги сцены, а не круглое число.
    material = _Params().min_leg_frac * sum(_BOOK_BEFORE.values())
    with_alias = census.find_returns(
        moves, {"fluid_usdc": "fluid_fusdc"}, material, material)
    without_alias = census.find_returns(moves, {}, material, material)
    assert len(with_alias) == 1, "с псевдонимом возврат виден"
    assert without_alias == [], "без псевдонима тот же возврат НЕ опознаётся"


# ── две породы возврата: предмет сравнения гистерезиса ──────────────────────

def _states(tmp_path: Path, path: list, hours: list) -> Path:
    rows = []
    for idx, (frm, to) in enumerate(zip(path, path[1:])):
        rows.append(_move(f"M{idx + 1}", hours[idx], frm, to))
    return _journal(tmp_path, rows)


_A = {"aave_v3": 50000.0, "compound_v3": 50000.0}
_B = {"maple": 50000.0, "compound_v3": 50000.0}
_C = {"pendle": 50000.0, "compound_v3": 50000.0}


def test_two_move_return_is_marked_VISIBLE_to_the_hysteresis(tmp_path):
    """A→B→A: ноги второго хода — обратные ногам ПРЕДЫДУЩЕГО, гистерезис их видит."""
    report = census.run_census(_states(tmp_path, [_A, _B, _A], [48.0, 24.0]),
                               now=_ANCHOR, params=_Params())
    assert report["counts"]["returns_total"] == 1
    assert report["returns"][0]["visible_to_reversal_check"] is True
    assert report["blind_spot_demonstrated"] is False


def test_three_move_return_is_INVISIBLE_by_construction(tmp_path):
    """A→B→C→A: разворачивается ПЕРВЫЙ ход, а сверяется второй — увидеть нечем.

    Ровно эта форма и есть §22 приказа («A → B → A → B»), и ровно её
    `last_move_legs` пропускает не по величине порога, а по предмету сравнения.
    """
    report = census.run_census(
        _states(tmp_path, [_A, _B, _C, _A], [72.0, 48.0, 24.0]),
        now=_ANCHOR, params=_Params())
    assert report["counts"]["returns_total"] == 1
    found = report["returns"][0]
    assert found["moves_spanned"] == 3
    assert found["visible_to_reversal_check"] is False
    assert report["blind_spot_demonstrated"] is True
    assert report["counts"]["invisible_by_construction"] == 1


def test_a_book_that_never_comes_back_is_not_accused(tmp_path):
    """Контроль в обратную сторону: монотонный путь A→B→C возвратом не объявляется."""
    report = census.run_census(_states(tmp_path, [_A, _B, _C], [48.0, 24.0]),
                               now=_ANCHOR, params=_Params())
    assert report["counts"]["returns_total"] == 0
    assert report["status"] == census.STATUS_OK
    assert report["blind_spot_demonstrated"] is False


def test_moves_that_never_leave_the_state_are_not_a_round_trip(tmp_path):
    """Холостые ходы прыжком не считаются — иначе любая пара записей стала бы находкой."""
    report = census.run_census(_states(tmp_path, [_A, _A, _A], [48.0, 24.0]),
                               now=_ANCHOR, params=_Params())
    assert report["counts"]["returns_total"] == 0


# ── вердикт судит НАСТОЯЩЕЕ, а история остаётся замером ─────────────────────

def test_a_fresh_return_is_CRITICAL(tmp_path):
    """Возврат, чей последний ход внутри окна от `now`, решается сегодня."""
    report = census.run_census(_states(tmp_path, [_A, _B, _A], [48.0, 24.0]),
                               now=_ANCHOR, params=_Params())
    assert report["status"] == census.STATUS_CRITICAL
    assert report["counts"]["recent_within_window_from_now"] == 1


def test_the_same_journal_goes_WARNING_when_the_clock_moves_on(tmp_path):
    """ОДИН и тот же журнал, другой `now` — другой вердикт.

    Это контроль ПРОВОДКИ часов: спрашивай прибор настенное время, вердикт
    зависел бы от дня прогона, а не от входа, и тест был бы бомбой (та самая
    бомба от календаря из `.claude/rules/deployment.md`).
    """
    scene = _states(tmp_path, [_A, _B, _A], [48.0, 24.0])
    fresh = census.run_census(scene, now=_ANCHOR, params=_Params())
    later = census.run_census(scene, now=_ANCHOR + timedelta(days=30),
                              params=_Params())
    assert fresh["status"] == census.STATUS_CRITICAL
    assert later["status"] == census.STATUS_WARNING
    # История НЕ исчезает от того, что стало тихо — иначе «OK» читалось бы как
    # «такого не бывало».
    assert later["counts"]["returns_total"] == 1
    assert later["counts"]["recent_within_window_from_now"] == 0


def test_silence_never_reads_as_the_class_not_existing(tmp_path):
    """`WARNING` существует ровно для того, чтобы тишина не выдавалась за `OK`."""
    scene = _states(tmp_path, [_A, _B, _C, _A], [72.0, 48.0, 24.0])
    later = census.run_census(scene, now=_ANCHOR + timedelta(days=60),
                              params=_Params())
    assert later["status"] == census.STATUS_WARNING
    assert later["status"] != census.STATUS_OK
    # Слепота по построению не гаснет от тишины — это не про сегодняшний день.
    assert later["blind_spot_demonstrated"] is True


# ── пороги — колонка ВЛАДЕЛЬЦА, а не наши числа (§22) ───────────────────────

def test_the_reversal_window_comes_from_the_owner_column(tmp_path):
    """Сузь окно владельца — возврат выпадает из него. Порог здесь не наш."""
    scene = _states(tmp_path, [_A, _B, _A], [48.0, 24.0])
    wide = census.run_census(scene, now=_ANCHOR,
                             params=_Params(reversal_window_days=14.0))
    narrow = census.run_census(scene, now=_ANCHOR,
                               params=_Params(reversal_window_days=0.5))
    assert wide["counts"]["returns_within_window"] == 1
    assert narrow["counts"]["returns_within_window"] == 0
    assert narrow["returns"][0]["within_reversal_window"] is False


def test_materiality_comes_from_the_owner_column_too(tmp_path):
    """Пыль ниже `min_leg_frac` позицией не является — и порог опять не наш."""
    dusty = dict(_A)
    dusty["sdai"] = 1.0          # $1 при книге $100k — пыль
    scene = _states(tmp_path, [dusty, _B, _A], [48.0, 24.0])
    loose = census.run_census(scene, now=_ANCHOR,
                              params=_Params(min_leg_frac=0.005))
    strict = census.run_census(scene, now=_ANCHOR,
                               params=_Params(min_leg_frac=0.0000001))
    assert loose["counts"]["returns_total"] == 1, "пыль не мешает узнать возврат"
    assert strict["counts"]["returns_total"] == 0, "с нулевым порогом $1 — разница"


# ── третий исход: «не измерено» никогда не выдаётся за «чисто» ──────────────

def test_a_missing_journal_is_UNMEASURED_not_a_clean_book(tmp_path):
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert report["measured"] is False
    assert report["status"] == census.STATUS_UNMEASURED
    assert report["status"] != census.STATUS_OK
    assert "не найден" in report["reason"]


def test_an_unreadable_journal_is_UNMEASURED_with_a_named_reason(tmp_path):
    (tmp_path / census.JOURNAL_NAME).write_text("{не json", encoding="utf-8")
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert report["measured"] is False
    assert "нечитаем" in report["reason"]


def test_a_journal_without_readable_timestamps_is_UNMEASURED(tmp_path):
    """Порядок ходов — предмет прибора. Нет отметок ⇒ мерить нечем."""
    _journal(tmp_path, [{"trade_id": "X", "from_allocation": _A,
                         "to_allocation": _B}])
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert report["measured"] is False
    assert "отметк" in report["reason"]


def test_a_journal_that_is_not_a_list_is_UNMEASURED(tmp_path):
    (tmp_path / census.JOURNAL_NAME).write_text('{"nope": 1}', encoding="utf-8")
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    assert report["measured"] is False


def test_a_missing_policy_column_is_UNMEASURED_not_a_substituted_default(tmp_path):
    """Дословный урок `pyflakes`: отсутствие инструмента — ТРЕТИЙ исход.

    Подставить сюда своё окно значило бы завести четвёртую копию чисел
    ADR-060 §3 и ответить на СВОЙ вопрос вместо нужного — §22 приказа это
    запрещает прямо («Все значения должны быть config/policy. Не hardcode»).
    """
    class _Broken:
        pass

    _real_incident(tmp_path)
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Broken())
    assert report["measured"] is False
    assert report["status"] == census.STATUS_UNMEASURED
    assert "НЕ ИЗМЕРЕНО" in report["reason"]
    # И находки при этом НЕ печатаются как ноль: их просто не мерили.
    assert report["counts"]["returns_total"] == 0
    assert report["returns"] == []


# ── коды возврата и отчёт ───────────────────────────────────────────────────

def test_exit_code_is_three_when_nothing_could_be_measured(tmp_path):
    """Ноль здесь был бы «чисто», которого никто не мерил (инв. #17)."""
    assert census.main(["--data-dir", str(tmp_path)]) == census.EXIT_UNMEASURED


def test_exit_code_is_one_on_a_fresh_return_and_zero_on_history_only(tmp_path,
                                                                    monkeypatch):
    """Ненулевой код — только на то, что решается сегодня.

    `main` берёт часы у машины по умолчанию, поэтому здесь они подменяются
    ЯКОРЕМ сцены: иначе вердикт зависел бы от дня прогона.
    """
    scene = _states(tmp_path, [_A, _B, _A], [48.0, 24.0])
    original = census.run_census

    def _pin(moment):
        monkeypatch.setattr(
            census, "run_census",
            lambda d, now=None, params=None: original(d, now=moment, params=params))

    _pin(_ANCHOR)
    assert census.main(["--data-dir", str(scene)]) == 1
    _pin(_ANCHOR + timedelta(days=60))
    assert census.main(["--data-dir", str(scene)]) == 0


def test_the_office_line_says_UNMEASURED_out_loud(tmp_path):
    report = census.run_census(tmp_path, now=_ANCHOR, params=_Params())
    line = census.summary_line(report)
    assert "НЕ ИЗМЕРЕНО" in line
    assert census.format_report(report) == [line], \
        "нечего докладывать, кроме причины — находок не мерили"


def test_nested_returns_are_not_counted_twice_in_the_turnover(tmp_path):
    """Вложенные возвраты: итог считается по непересекающемуся подмножеству."""
    scene = _states(tmp_path, [_A, _B, _C, _B, _A], [96.0, 72.0, 48.0, 24.0])
    report = census.run_census(scene, now=_ANCHOR, params=_Params())
    total = report["counts"]["returns_within_window"]
    disjoint = report["counts"]["disjoint_within_window"]
    assert total >= 2, "сцена обязана дать вложенные возвраты"
    assert disjoint < total, "иначе один и тот же ход посчитан дважды"
    assert report["turnover_usd_disjoint"] <= sum(
        r["turnover_usd"] for r in report["returns"])


def test_the_report_names_the_door_of_the_blind_spot(tmp_path):
    """Находка обязана называть СВОЮ дверь, а не «что-то не так»."""
    scene = _states(tmp_path, [_A, _B, _C, _A], [72.0, 48.0, 24.0])
    lines = "\n".join(census.format_report(
        census.run_census(scene, now=_ANCHOR, params=_Params())))
    assert "last_move_legs" in lines
    assert "RiskPolicy" in lines, "прибор обязан сказать, чего он НЕ трогает"


def test_an_unavailable_policy_column_is_UNMEASURED(tmp_path, monkeypatch):
    """Порвано ЗВЕНО ДОБЫЧИ колонки, а не её содержимое.

    Замер мутациями (#701): проверка выше рвала колонку, ПЕРЕДАННУЮ входом, и
    ветку «колонку не удалось добыть вовсе» не проверял никто — подстановка
    умолчания на её месте выживала мутацию. Это ровно тот fail-OPEN, который
    тише красного теста и потому опаснее: прибор ответил бы на свой вопрос
    (умолчание автора) вместо нужного (колонка владельца).
    """
    import spa_core.allocator.rebalance_economics as econ

    def _refuse(*_a, **_kw):
        raise RuntimeError("колонка ADR-060 §3 недоступна на этой сцене")

    monkeypatch.setattr(econ.TriggerParams, "for_mode", staticmethod(_refuse))
    _real_incident(tmp_path)
    report = census.run_census(tmp_path, now=_ANCHOR)      # params=None ⇒ добыть самому
    assert report["measured"] is False
    assert report["status"] == census.STATUS_UNMEASURED
    assert "Не hardcode" in report["reason"], \
        "причина обязана назвать §22, а не просто «ошибка»"
    assert report["counts"]["returns_total"] == 0


# ── ступень моста: артефакт обязан ПОЯВИТЬСЯ на диске ───────────────────────

def test_the_bridge_stage_actually_leaves_the_artifact_on_disk(tmp_path):
    """Положительный контроль на настоящую поломку #701.

    Первая редакция звала `atomic_save(path, report)` — доводы наоборот.
    `atomic_save` отвергает такой путь fail-CLOSED, поэтому артефакта не
    появлялось ВОВСЕ, а ступень докладывала `measured=True`: отказ записи был
    неотличим от успеха у всех, кто смотрит на её вывод, а не на диск. Читать
    надо ДИСК — иначе проверка проверяет отчёт о себе.
    """
    root = tmp_path / "tree"
    (root / "data").mkdir(parents=True)
    _journal(root / "data", [
        _move("M1", 48.0, _A, _B),
        _move("M2", 24.0, _B, _A),
    ])
    result = census.run(root=str(root))
    assert result["measured"] is True
    assert "artifact_not_written" not in result["doc"], \
        result["doc"].get("artifact_not_written")
    written = root / "data" / census.ARTIFACT_NAME
    assert written.exists(), "артефакта нет на диске — читателю нечего читать"
    doc = json.loads(written.read_text(encoding="utf-8"))
    assert doc["counts"]["returns_total"] == 1
    assert doc["status"] in (census.STATUS_CRITICAL, census.STATUS_WARNING)


def test_the_bridge_stage_leaves_an_artifact_for_the_third_outcome_too(tmp_path):
    """«Не измерено» обязано ДОЕХАТЬ до читателя.

    Иначе шаг 0-офис видит отсутствие файла и не может отличить его от
    «ступень вообще не запускалась» — два разных исхода под одним видом.
    """
    root = tmp_path / "tree"
    (root / "data").mkdir(parents=True)          # журнала нет намеренно
    result = census.run(root=str(root))
    assert result["measured"] is False
    written = root / "data" / census.ARTIFACT_NAME
    assert written.exists()
    doc = json.loads(written.read_text(encoding="utf-8"))
    assert doc["status"] == census.STATUS_UNMEASURED
    assert doc["reason"]
