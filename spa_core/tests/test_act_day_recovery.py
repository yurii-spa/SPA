"""Приёмка G15 (ADR-383): существует ли рычаг, возвращающий ACT-день в оценённый набор.

Каждый отказ здесь — положительный контроль в ОБЕ стороны: сцена, где прибор
обязан промолчать, и сцена, где он обязан назвать находку. Проверка, никогда не
видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Аварию воспроизводит `test_erased_by_a_later_run_of_the_same_day`: ход 21:47
с меткой разрешения, строка журнала 23:31 с вердиктом HOLD — ровно 11.09.2026.

Время здесь ВХОД, а не окружение: все отметки строятся от одного якоря
``ANCHOR`` и передаются в прибор параметром ``now=``.
FROZEN-DATE-OK: injected-clock — якорь ANCHOR порождает все отметки сцен, и он же
уходит в ``measure(now=...)`` / ``run(now=...)``; стенных часов прибор на этом
пути не спрашивает.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import act_day_recovery as adr
from spa_core.paper_trading import cio_trial as _cio_trial

ANCHOR = datetime(2026, 9, 11, 21, 47, 52, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _record(date: str, *, verdict: str = "HOLD", generated_at: str,
            evidenced: dict | None = None) -> dict:
    """Строка журнала вердиктов в той форме, в какой её пишет писатель."""
    return {
        "cycle_date": date,
        "verdict": verdict,
        "generated_at": generated_at,
        "capital_usd": 100000.0,
        "current_positions": {"compound_v3": 40000.0},
        "target_positions": {"compound_v3": 40000.0},
        "apy_evidenced_pct": evidenced if evidenced is not None else {},
    }


class _Stand:
    """Одноразовый каталог data/ со всеми тремя производителями.

    Живое ``data/`` ни один тест не открывает: сцена строится целиком в tmp.
    """

    def __init__(self, tmp: str):
        self.dir = Path(tmp)
        self.trades: list[dict] = []
        self.records: list[dict] = []
        self.series: dict[str, list] = {}

    def trade(self, *, trade_id: str = "T034", ts: datetime, marked: bool = True,
              frm: dict | None = None, to: dict | None = None) -> "_Stand":
        row = {
            "trade_id": trade_id,
            "ts": _iso(ts),
            "type": "rebalance",
            "from_allocation": frm if frm is not None else {"pendle": 20000.0,
                                                            "compound_v3": 40000.0},
            "to_allocation": to if to is not None else {"maple": 20000.0,
                                                        "compound_v3": 40000.0},
        }
        if marked:
            row[_cio_trial.MARK] = _cio_trial.TRIAL_GRANT["adr"]
        self.trades.append(row)
        return self

    def record(self, *args, **kwargs) -> "_Stand":
        self.records.append(_record(*args, **kwargs))
        return self

    def point(self, key: str, date: str, rate: float) -> "_Stand":
        self.series.setdefault(key, []).append([date, rate])
        return self

    def write(self, *, trades_raw: str | None = None,
              series_raw: str | None = None) -> Path:
        (self.dir / "trades.json").write_text(
            trades_raw if trades_raw is not None
            else json.dumps({"trades": self.trades}), encoding="utf-8")
        (self.dir / "allocation_rationale_history.jsonl").write_text(
            "\n".join(json.dumps(r) for r in self.records) + ("\n" if self.records else ""),
            encoding="utf-8")
        (self.dir / "apy_series_daily.json").write_text(
            series_raw if series_raw is not None
            else json.dumps({"series": self.series}), encoding="utf-8")
        return self.dir


class _StandCase(unittest.TestCase):
    def stand(self) -> tuple[_Stand, TemporaryDirectory]:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return _Stand(tmp.name), tmp

    def full_day(self, *, line_at: datetime, verdict: str = "HOLD",
                 with_pendle_material: bool = True,
                 series_for_pendle: bool = True) -> Path:
        """Сцена настоящей аварии: ход с меткой + строка журнала того же дня."""
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", verdict=verdict, generated_at=_iso(line_at))
        for offset in (1, 2, 3):
            day = (ANCHOR + timedelta(days=offset)).date().isoformat()
            evidenced = {"maple": 4.97, "compound_v3": 3.2}
            if with_pendle_material:
                evidenced["pendle"] = 14.0
            stand.record(day, generated_at=_iso(ANCHOR + timedelta(days=offset)),
                         evidenced=evidenced)
            stand.point("maple", day, 4.97)
            stand.point("compound_v3", day, 3.2)
            if series_for_pendle:
                stand.point("pendle", day, 14.0)
        return stand.write()


class TestTheRealIncident(_StandCase):
    """Авария 11.09.2026 — строка ACT стёрта позднейшим прогоном того же дня."""

    def test_erased_by_a_later_run_of_the_same_day(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=1, minutes=44),
                             with_pendle_material=False, series_for_pendle=False)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        day = doc["days"][0]
        self.assertEqual(day["state"], adr.DAY_ERASED)
        self.assertEqual(doc["overall"], adr.OVERALL_CRITICAL)
        # Отпечаток правила замены: строка СТРОГО позже хода, и разница названа.
        self.assertGreater(day["detail"]["line_later_than_trade_sec"], 0)
        self.assertEqual(doc["journal"]["act_lines"], 0)

    def test_the_blocking_leg_is_named_and_its_lever_is_the_owners(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=False, series_for_pendle=False)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        day = doc["days"][0]
        self.assertEqual(day["lever"], adr.LEVER_FEED_OWNER)
        self.assertEqual(day["lever_detail"]["blocking_legs"], ["pendle"])
        # Ноль точек у производителя — наш код не поднимет ставку НИКОГДА.
        self.assertEqual(day["lever_detail"]["legs"][0]["series_points_total"], 0)

    def test_owner_blocked_day_enters_NEITHER_bound(self):
        """День, упёршийся в решение владельца, в верхнюю границу не входит.

        Включить его значило бы выдать решение владельца за нашу починку — ровно
        та подмена адресата, против которой заказ G15 и написан.
        """
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=False, series_for_pendle=False)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        bounds = doc["bounds"]
        self.assertEqual(bounds["act_days_recoverable_to_journal"], 1)
        self.assertEqual(bounds["scored_act_days_lower"], 0)
        self.assertEqual(bounds["scored_act_days_upper"], 0)
        self.assertEqual(bounds["blocked_on_owner_lever"], 1)
        self.assertFalse(doc["criterion"]["closes_at_upper_bound"])


class TestItStaysQuietWhenNothingIsWrong(_StandCase):
    """Обратная сторона каждого контроля: сцены, где прибор обязан молчать."""

    def test_journal_carrying_the_ACT_is_not_a_finding(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2), verdict="ACT")
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"][0]["state"], adr.DAY_PRESENT)
        self.assertEqual(doc["overall"], adr.OVERALL_OK)
        self.assertEqual(doc["bounds"]["act_days_recoverable_to_journal"], 0)

    def test_no_marked_move_is_not_a_finding(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR, marked=False)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"], [])
        self.assertEqual(doc["overall"], adr.OVERALL_OK)


class TestClassesAreNotMerged(_StandCase):
    """«Журнал не знал» и «журнал знал и строку стёрли» — разные дефекты."""

    def test_line_EARLIER_than_the_trade_is_a_different_class(self):
        data = self.full_day(line_at=ANCHOR - timedelta(hours=3),
                             with_pendle_material=False, series_for_pendle=False)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"][0]["state"], adr.DAY_NOT_JOURNALED)

    def test_no_line_at_all_is_its_own_class(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-12", generated_at=_iso(ANCHOR + timedelta(days=1)))
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"][0]["state"], adr.DAY_NO_LINE)

    def test_population_comes_from_the_MONEY_not_from_the_journal(self):
        """Журнал — подозреваемый; население, выведенное из него, потеряло бы день."""
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-12", generated_at=_iso(ANCHOR + timedelta(days=1)))
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        self.assertEqual(len(doc["days"]), 1)
        self.assertEqual(doc["days"][0]["date"], "2026-09-11")

    def test_the_mark_rule_is_the_neighbours_and_not_a_second_copy(self):
        self.assertEqual(adr.TRIAL_MARK, _cio_trial.MARK)
        self.assertIs(adr.TRIAL_GRANT, _cio_trial.TRIAL_GRANT)


class TestTheThirdOutcome(_StandCase):
    """Не измерено — самостоятельный исход, а не ноль и не успех (инв. #17)."""

    def test_unreadable_trades_is_UNMEASURED_not_clean(self):
        stand, _ = self.stand()
        data = stand.write(trades_raw="{ не json")
        doc = adr.measure(data, now=ANCHOR)
        self.assertEqual(doc["overall"], adr.OVERALL_UNMEASURED)
        self.assertIn("trades.json", doc["reason"])

    def test_empty_journal_is_UNMEASURED_not_clean(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        doc = adr.measure(stand.write(), now=ANCHOR)
        self.assertEqual(doc["overall"], adr.OVERALL_UNMEASURED)

    def test_unparseable_timestamp_is_UNMEASURED_not_erased(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.records.append({"cycle_date": "2026-09-11", "verdict": "HOLD",
                              "generated_at": "не отметка",
                              "apy_evidenced_pct": {}})
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"][0]["state"], adr.DAY_UNMEASURED)
        self.assertEqual(doc["overall"], adr.OVERALL_UNMEASURED)

    def test_unreadable_series_leaves_the_lever_UNNAMED(self):
        """Ряд не прочитан ⇒ рычаг НЕ НАЗВАН, а не «рычага не нужно».

        Сцена обязана нести форвардные дни с непокрытой ногой: без них день не
        оценим по СРОКУ, и тест отвечал бы на другой вопрос.
        """
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        for offset in (1, 2, 3):
            day = (ANCHOR + timedelta(days=offset)).date().isoformat()
            stand.record(day, generated_at=_iso(ANCHOR + timedelta(days=offset)),
                         evidenced={"maple": 4.97})      # pendle не покрыт
        data = stand.write(series_raw="{ не json")
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"][0]["scoring"]["unpriced_legs"], ["pendle"])
        self.assertEqual(doc["days"][0]["lever"], adr.LEVER_UNMEASURED)
        self.assertEqual(doc["overall"], adr.OVERALL_UNMEASURED)

    def test_no_forward_days_is_a_TERM_not_a_lever(self):
        """Горизонт не истёк — «слишком рано», а не «всё в порядке».

        Ровно этот класс судья ставит свежему дню (замер 14.09). Слить его с
        `none_needed` значило бы записать несудимый день в благополучные.
        """
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(hours=3))
        day = doc["days"][0]
        self.assertEqual(day["lever"], adr.LEVER_HORIZON_NOT_ELAPSED)
        self.assertEqual(day["scoring"]["forward_days_available"], 0)
        self.assertEqual(doc["overall"], adr.OVERALL_WARNING)
        self.assertEqual(doc["bounds"]["too_early_to_judge"], 1)
        self.assertEqual(doc["bounds"]["scored_act_days_upper"], 0)
        self.assertEqual(doc["bounds"]["blocked_on_owner_lever"], 0)

    def test_exit_codes_tell_the_three_outcomes_apart(self):
        clean = self.full_day(line_at=ANCHOR + timedelta(hours=2), verdict="ACT")
        self.assertEqual(adr.main(["--data-dir", str(clean), "--no-write"]), 0)
        broken = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                               with_pendle_material=False, series_for_pendle=False)
        self.assertEqual(adr.main(["--data-dir", str(broken), "--no-write"]), 1)
        stand, _ = self.stand()
        unmeasured = stand.write(trades_raw="{ не json")
        self.assertEqual(adr.main(["--data-dir", str(unmeasured), "--no-write"]), 2)


class TestTheBoundsSeparate(_StandCase):
    """Обе границы обязаны уметь РАЗОЙТИСЬ — иначе ширина ноль ничего не значит."""

    def test_our_code_lever_lifts_the_UPPER_bound_only(self):
        """Материал в ряду есть, в журнале ставки нет ⇒ рычаг наш, ширина 1."""
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=False, series_for_pendle=True)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        day = doc["days"][0]
        self.assertEqual(day["lever"], adr.LEVER_OUR_CODE)
        self.assertEqual(doc["bounds"]["scored_act_days_lower"], 0)
        self.assertEqual(doc["bounds"]["scored_act_days_upper"], 1)
        self.assertEqual(doc["bounds"]["width"], 1)
        self.assertTrue(doc["criterion"]["closes_at_upper_bound"])
        self.assertFalse(doc["criterion"]["closes_at_lower_bound"])

    def test_fully_material_day_closes_the_criterion_at_BOTH_bounds(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=True, series_for_pendle=True)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        day = doc["days"][0]
        self.assertTrue(day["scoring"]["scorable"])
        self.assertEqual(day["scoring"]["priced_forward_days"], 3)
        self.assertIsNotNone(day["scoring"]["gain_usd"])
        self.assertEqual(doc["bounds"]["scored_act_days_lower"], 1)
        self.assertEqual(doc["bounds"]["scored_act_days_upper"], 1)
        self.assertTrue(doc["criterion"]["closes_at_lower_bound"])


class TestTheWideningControl(_StandCase):
    """Прибор обязан УМЕТЬ разойтись — и обязан отказаться, когда падать неоткуда."""

    def test_withholding_a_leg_drops_a_scorable_day(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        control = adr.widening_control(data, now=ANCHOR + timedelta(days=3))
        self.assertTrue(control["measured"])
        self.assertTrue(control["scorable_before"])
        self.assertFalse(control["scorable_after"])
        self.assertTrue(control["diverged"])
        self.assertGreater(control["priced_days_before"], control["priced_days_after"])

    def test_control_REFUSES_when_no_day_is_scorable(self):
        """Контроль, истинный по построению, — украшение; он обязан сказать «нет».

        Это ровно живой замер 14.09: единственный день населения не оценивается,
        и «расхождение» там доказывало бы лишь удлинение списка непокрытых ног.
        """
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=False, series_for_pendle=False)
        control = adr.widening_control(data, now=ANCHOR + timedelta(days=3))
        self.assertFalse(control["measured"])
        self.assertIn("падать неоткуда", control["reason"])


class TestScaleControl(_StandCase):
    """Шкала сверяется ДО единого вердикта: доли против процентов подделали бы всё."""

    def test_decimal_series_against_percent_journal_is_caught(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        for offset in (1, 2, 3):
            day = (ANCHOR + timedelta(days=offset)).date().isoformat()
            stand.record(day, generated_at=_iso(ANCHOR + timedelta(days=offset)),
                         evidenced={"maple": 4.97})
            stand.point("maple", day, 0.0497)      # доли вместо процентов
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        self.assertTrue(doc["unit_parity"]["measured"])
        self.assertFalse(doc["unit_parity"]["passed"])

    def test_same_scale_passes_and_prints_NOTHING(self):
        """Пройденная шкала — не событие, и строки о ней быть не должно.

        Утверждения `passed is True` мало: ветка отрисовки требует ОБОИХ
        условий, и без проверки МОЛЧАНИЯ замена `and` на `or` пережила бы набор
        (замер батареи), то есть о каждой здоровой шкале печаталось бы
        расхождение.
        """
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertTrue(doc["unit_parity"]["passed"])
        self.assertFalse(any("ШКАЛА" in line for line in adr.format_report(doc)))


class TestItOnlyReads(_StandCase):
    """Заявление «прибор только ЧИТАЕТ» обязано быть ИЗМЕРЕНО, а не объявлено."""

    def test_no_write_creates_no_artifact(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        before = sorted(p.name for p in Path(data).iterdir())
        adr.run(data_dir=str(data), now=ANCHOR + timedelta(days=3), write=False)
        self.assertEqual(sorted(p.name for p in Path(data).iterdir()), before)

    def test_measure_never_touches_the_inputs(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        snapshot = {p.name: p.read_bytes() for p in Path(data).iterdir()}
        adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertEqual({p.name: p.read_bytes() for p in Path(data).iterdir()},
                         snapshot)

    def test_write_produces_the_artifact_and_the_report_renders(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=False, series_for_pendle=False)
        doc = adr.run(data_dir=str(data), now=ANCHOR + timedelta(days=3), write=True)
        written = json.loads((Path(data) / adr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual(written["schema"], adr.VERSION)
        self.assertIn("widening_control", written)
        lines = adr.format_report(doc)
        self.assertTrue(any("ГРАНИЦЫ" in line for line in lines))
        self.assertTrue(any("pendle" in line for line in lines))


class TestMoveShape(_StandCase):
    def test_dust_legs_are_not_a_move(self):
        deltas = adr._move_deltas({"from_allocation": {"a": 100.0, "b": 50.0},
                                   "to_allocation": {"a": 100.004, "b": 60.0}})
        self.assertEqual(deltas, {"b": 10.0})

    def test_horizon_limits_the_forward_days(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3), horizon_days=1)
        self.assertEqual(doc["days"][0]["scoring"]["priced_forward_days"], 1)

    def test_what_it_does_not_prove_reaches_the_artifact(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertEqual(list(doc["what_it_does_not_prove"]),
                         list(adr.WHAT_IT_DOES_NOT_PROVE))
        self.assertTrue(doc["what_it_does_not_prove"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestTheBatteryHoles(_StandCase):
    """Дыры, найденные батареей мутаций: числа, флаги и проводка флагов.

    Первый прогон батареи дал 36 выживших из 103 — набор выглядел плотным и им
    не был, а дыры оказались ЧИСЛАМИ (округления и суммы не проверял никто) и
    ПУТЯМИ (флаг `--no-write`, ветка `root`, коды возврата WARNING и «неизвестно»).
    """

    def test_the_gain_is_asserted_as_a_NUMBER_not_as_not_None(self):
        """Сумма счёта проверяется значением: «не None» переживает любую арифметику."""
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        scoring = doc["days"][0]["scoring"]
        # ноги: pendle −20 000 (14.00 %), maple +20 000 (4.97 %), три форвардных дня
        self.assertEqual(scoring["gain_usd"], -14.84)
        self.assertEqual(doc["days"][0]["executed_move"]["turnover_usd"], 20000.0)

    def test_one_priced_forward_day_is_enough_to_be_scorable(self):
        """Граница «>0», а не «>1»: один оценённый день уже делает день оценимым."""
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3), horizon_days=1)
        scoring = doc["days"][0]["scoring"]
        self.assertEqual(scoring["priced_forward_days"], 1)
        self.assertTrue(scoring["scorable"])
        self.assertEqual(scoring["gain_usd"], -4.95)

    def test_materiality_of_the_executed_move_is_asserted_both_ways(self):
        big = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        doc = adr.measure(big, now=ANCHOR + timedelta(days=3))
        self.assertTrue(doc["days"][0]["executed_move"]["material"])

        stand, _ = self.stand()
        stand.trade(ts=ANCHOR, frm={"maple": 100.0}, to={"maple": 110.0})
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        self.assertFalse(doc["days"][0]["executed_move"]["material"])

    def test_entry_only_and_exit_only_legs_keep_their_exact_size(self):
        """Нога, которой нет по одну сторону, — не «ноль по умолчанию» наугад."""
        deltas = adr._move_deltas({"from_allocation": {"pendle": 20000.0},
                                   "to_allocation": {"maple": 14736.84}})
        self.assertEqual(deltas, {"pendle": -20000.0, "maple": 14736.84})

    def test_act_lines_counts_the_ACT_lines_and_not_the_others(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2), verdict="ACT")
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        # три форвардных HOLD-строки рядом — счётчик обязан считать ровно ACT
        self.assertEqual(doc["journal"]["lines"], 4)
        self.assertEqual(doc["journal"]["act_lines"], 1)

    def test_the_erasure_delay_is_asserted_to_the_second(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=1, minutes=44, seconds=4),
                             with_pendle_material=False, series_for_pendle=False)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"][0]["detail"]["line_later_than_trade_sec"], 6244.0)
        self.assertEqual(doc["days"][0]["detail"]["journal_verdict"], "HOLD")

    def test_two_reasons_for_feed_owner_are_told_apart(self):
        """«Ноль точек у производителя» и «точки есть, но не в те дни» — разное."""
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        for offset in (1, 2, 3):
            day = (ANCHOR + timedelta(days=offset)).date().isoformat()
            stand.record(day, generated_at=_iso(ANCHOR + timedelta(days=offset)),
                         evidenced={"maple": 4.97})
        stand.point("pendle", "2026-08-01", 14.0)      # точка есть, но НЕ в окне
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        leg = doc["days"][0]["lever_detail"]["legs"][0]
        self.assertEqual(leg["class"], adr.LEVER_FEED_OWNER)
        self.assertEqual(leg["series_points_total"], 1)
        self.assertIn("ни одной в нужные форвардные дни", leg["why"])
        self.assertFalse(doc["days"][0]["lever_detail"]["any_material"])

    def test_the_named_addressee_reaches_the_reason_line(self):
        """Адресат рычага обязан быть В ТЕКСТЕ ответа, а не только в поле."""
        owner = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                              with_pendle_material=False, series_for_pendle=False)
        self.assertIn("рычаг у владельца",
                      adr.measure(owner, now=ANCHOR + timedelta(days=3))["reason"])
        ours = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=False, series_for_pendle=True)
        self.assertIn("рычаг НАШ",
                      adr.measure(ours, now=ANCHOR + timedelta(days=3))["reason"])

    def test_scale_failure_is_RENDERED_not_only_recorded(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        for offset in (1, 2, 3):
            day = (ANCHOR + timedelta(days=offset)).date().isoformat()
            stand.record(day, generated_at=_iso(ANCHOR + timedelta(days=offset)),
                         evidenced={"maple": 4.97})
            stand.point("maple", day, 0.0497)
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        self.assertTrue(any("ШКАЛА" in line for line in adr.format_report(doc)))

    def test_unreadable_series_leaves_parity_UNMEASURED(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        doc = adr.measure(stand.write(series_raw="{ не json"), now=ANCHOR)
        self.assertFalse(doc["unit_parity"]["measured"])


class TestTheWiringOfTheFlags(_StandCase):
    """Проводка флагов CLI — отдельный предмет: поле верно, а путь может врать."""

    def test_no_write_flag_really_suppresses_the_artifact(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        adr.main(["--data-dir", str(data), "--no-write"])
        self.assertFalse((Path(data) / adr.ARTIFACT).exists())

    def test_without_the_flag_main_writes(self):
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        adr.main(["--data-dir", str(data)])
        self.assertTrue((Path(data) / adr.ARTIFACT).exists())

    def test_root_branch_reads_the_data_subdirectory(self):
        """Ветка `root` читает подкаталог data/ — и стенд живёт в СВОЁМ каталоге.

        Первая редакция клала стенд в `Path(data).parent`, то есть в ОБЩИЙ
        системный tmp: в одиночку тест проходил, а в наборе падал на своём же
        мусоре, оставшемся от прошлого прогона (`FileExistsError`). Тест, пишущий
        мимо своей песочницы, проверяет не предмет, а порядок запуска.
        """
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        own = TemporaryDirectory()
        self.addCleanup(own.cleanup)
        root = Path(own.name) / "root_stand"
        (root / "data").mkdir(parents=True)
        for src in Path(data).iterdir():
            (root / "data" / src.name).write_bytes(src.read_bytes())
        doc = adr.run(root=str(root), now=ANCHOR + timedelta(days=3), write=False)
        self.assertEqual(len(doc["days"]), 1)

    def test_warning_outcome_has_its_OWN_exit_code(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        data = stand.write()
        self.assertEqual(adr.main(["--data-dir", str(data), "--no-write"]), 1)

    def test_an_UNKNOWN_outcome_exits_nonzero_not_clean(self):
        """Незнакомый исход — «не узнали», и выдавать его за чистый проход нельзя."""
        real = adr.run
        adr.run = lambda **kwargs: {"overall": "исход, которого не бывает"}
        try:
            self.assertEqual(adr.main(["--no-write"]), 2)
        finally:
            adr.run = real


class TestTheHonestBatteryHoles(_StandCase):
    """Дыры, найденные ЧЕСТНЫМ прогоном батареи (14 выживших из 103).

    Предыдущий прогон напечатал «0 выживших», и это было НЕВЕРНО: в наборе жил
    тест, протекавший в общий системный tmp, — после первой же мутации он падал
    в КАЖДОМ следующем прогоне, и любая мутация засчитывалась убитой. Тот же
    класс, что «известный красный тест красит всех выживших», только красным
    тест становился сам, со второго прогона. Урок: базу набора надо проверять
    ДВАЖДЫ подряд ДО батареи, иначе батарея меряет не тесты.
    """

    def test_subsecond_erasure_delay_keeps_its_precision(self):
        """Округление до 3 знаков: на целых секундах мутация неразличима."""
        data = self.full_day(
            line_at=ANCHOR + timedelta(seconds=42, milliseconds=125),
            with_pendle_material=False, series_for_pendle=False)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"][0]["detail"]["line_later_than_trade_sec"], 42.125)

    def test_fractional_turnover_keeps_its_cents(self):
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR, frm={"pendle": 20000.0},
                    to={"maple": 14736.84, "morpho_blue_base": 5263.17})
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=3))
        self.assertEqual(doc["days"][0]["executed_move"]["turnover_usd"], 20000.01)

    def test_any_material_is_TRUE_when_one_leg_has_material(self):
        """Обратная сторона: `any_material` обязан уметь быть истинным."""
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=False, series_for_pendle=True)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertTrue(doc["days"][0]["lever_detail"]["any_material"])

    def test_two_marked_moves_are_reported_in_time_order(self):
        """Порядок дней — по времени хода, а не по порядку строк в журнале."""
        stand, _ = self.stand()
        later = ANCHOR + timedelta(days=1)
        stand.trade(trade_id="T035", ts=later)       # записан ПЕРВЫМ, произошёл ПОЗЖЕ
        stand.trade(trade_id="T034", ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        stand.record("2026-09-12", generated_at=_iso(later + timedelta(hours=2)))
        doc = adr.measure(stand.write(), now=ANCHOR + timedelta(days=5))
        self.assertEqual([d["date"] for d in doc["days"]],
                         ["2026-09-11", "2026-09-12"])

    def test_run_writes_by_DEFAULT(self):
        """Умолчание `write=True` не спрашивал никто — а оно решает, пишем ли в прод."""
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        adr.run(data_dir=str(data), now=ANCHOR + timedelta(days=3))
        self.assertTrue((Path(data) / adr.ARTIFACT).exists())

    def test_diverged_is_FALSE_when_the_day_survives_the_withholding(self):
        """Обратный контроль `diverged`: не упало ⇒ не разошлось.

        Забираем ногу, которой в ходе нет вовсе — оценимость обязана УСТОЯТЬ.
        """
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2))
        base = adr.measure(data, now=ANCHOR + timedelta(days=3))
        self.assertTrue(base["days"][0]["scoring"]["scorable"])
        after = adr.measure(data, now=ANCHOR + timedelta(days=3),
                            withhold_forward=["нога-которой-нет"])
        self.assertTrue(after["days"][0]["scoring"]["scorable"])

    def test_report_renders_the_journal_and_legs_lines(self):
        """Строки отчёта проверяются СОДЕРЖИМЫМ, а не фактом непадения."""
        data = self.full_day(line_at=ANCHOR + timedelta(hours=2),
                             with_pendle_material=False, series_for_pendle=False)
        doc = adr.measure(data, now=ANCHOR + timedelta(days=3))
        lines = adr.format_report(doc)
        self.assertTrue(any("[ЖУРНАЛ] строк 4" in line for line in lines))
        self.assertTrue(any("pendle-20,000" in line for line in lines))
        self.assertTrue(any("erased_by_replacement" in line for line in lines))

    def test_unmeasured_scale_does_NOT_render_the_scale_line(self):
        """«Шкала не сверена» — не находка о шкале, и печатать её нельзя.

        Ветка отрисовки требует ОБОИХ условий: замер состоялся И полоса не
        пройдена. Без этого теста «не измерено» отрисовывалось бы как
        расхождение шкалы — то самое смешение, против которого инв. #17.
        """
        stand, _ = self.stand()
        stand.trade(ts=ANCHOR)
        stand.record("2026-09-11", generated_at=_iso(ANCHOR + timedelta(hours=2)))
        doc = adr.measure(stand.write(series_raw="{ не json"), now=ANCHOR)
        self.assertFalse(doc["unit_parity"]["measured"])
        self.assertNotIn("passed", doc["unit_parity"])
        self.assertFalse(any("ШКАЛА" in line for line in adr.format_report(doc)))
