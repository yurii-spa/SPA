"""Контроль ВЫВЕДЕННОГО срока годности (ADR-814, заказ G813 п. 1 приказа «Portfolio CIO»).

Прибор `slo_keepability` с ADR-813 различает два состояния находки, но на вопрос
«а какой срок тогда?» не отвечал — и пока не отвечает прибор, отвечает глаз
сессии. Заказ владельца требует число ВЫВЕСТИ.

Соврать здесь можно ровно пятью способами, и на каждый ниже стои́т положительный
контроль с обратной стороной:

1. **вывести пол из ОБЪЯВЛЕННОГО расписания.** Ровно этот дефект измерил ADR-506:
   launchd отсчитывает `StartInterval` от ЗАВЕРШЕНИЯ прогона, поэтому объявленные
   6 ч дают наблюдённые 7,6 ч, и пол из объявления оказывается НИЖЕ физически
   возможного — то есть ниже того, от чего пол должен защищать;
2. **завести ВТОРУЮ копию правила запаса.** Запас поверх такта восстановлен
   `slo_proposal` по 35 курированным человеком срокам (ADR-158); пересчитать его
   в приборе значило бы повторить ADR-220 (два определения одного имени);
3. **выдать «такта не наблюдали» за число.** Подставить расписание или ноль —
   нарушение инв. #17: три исхода обязаны быть различимы;
4. **назвать ОДНИМ словом два состояния «ниже пола».** Слить «обещание нарушено»
   с «запаса на пропуск нет» значило бы воспроизвести дефект ADR-813 на один этаж
   выше — в СВОЕЙ новой оси. ⚠️ **Носитель этого контроля заменён ADR-815:** при
   КОНСТАНТНОМ запасе 2 ч сюда попадал `resource_health.json` (срок 0,5 ч, медиана
   0,083 ч, пол 2,08 ч) — и попадал не по своему свойству, а потому что у
   пятиминутного агента константа требует срока в 25 тактов. Семь пар из девяти
   были таким артефактом; теперь носитель — `architecture_conformance.json`
   (такт 6 ч, срок 7 ч), у кого утверждение верно;
5. **предложить проглотить ВЫБРОС сроком.** У состояния
   `cadence_keeps_outlier_broke` причина разрыва прибором НЕ измерена, и печатать
   ему выведенный срок значило бы советовать спрятать неизмеренное.

Главный положительный контроль — живая авария 26.10: семья
`com.spa.decision_loop`, объявлено `slo_hours: 7`, наблюдённый такт по 30
периодам подряд `7.014 … 23.349` ч, медиана **7.278** — срок превысили **30 из
30**, то есть ни один период не уложился. 69 артефактов одной семьи.

## Часы

Литеральной даты в этом файле НЕТ ни одной, поэтому пометки освобождения он не
несёт: `_ANCHOR` приходит ИМПОРТОМ у соседа `test_slo_keepability`, который и
отдаёт его прибору аргументом `now=`. Поставить здесь `FROZEN-DATE-OK:
injected-clock` было бы ЛОЖНОЙ претензией — освобождать нечего, — и
`test_injected_clock_claim` ровно это и сказал, когда пометка тут стояла.
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import slo_keepability as sk  # noqa: E402
from spa_core.monitoring import slo_proposal as sp  # noqa: E402
from spa_core.tests.test_slo_keepability import _ANCHOR, _Stand  # noqa: E402

#: Наблюдённые периоды семьи `com.spa.decision_loop`, замер 26.10 по
#: `/tmp/spa_decision_loop.log` (31 баннер, 30 периодов). Числа НЕ округлены:
#: медиана 7.278 и максимум 23.349 — обе величины предмета.
_LIVE_PERIODS = [9.315, 7.795, 7.291, 7.822, 7.049, 7.117, 7.681, 7.021, 23.349,
                 7.045, 8.506, 7.014, 7.067, 7.023, 7.018, 7.019, 7.066, 7.204,
                 7.251, 7.254, 7.300, 7.470, 8.259, 7.264, 7.163, 7.350, 7.317,
                 8.740, 7.448, 7.350]
#: Срок, объявленный в конституции до этого цикла.
_DECLARED = 7.0
#: Срок, который ВЫВОДИТСЯ из наблюдённой медианы. Литералом здесь он стои́т
#: намеренно: тест обязан поймать смену правила, а не пересчитать его заново.
#: Число, которое ПРЕДЛАГАЕТСЯ поставить в манифест (и которое ADR-814 туда
#: доставил). Округлено ВВЕРХ: срок, предложенный ниже физически возможного, и
#: есть дефект, с которым этот модуль чинили.
_OFFERED = 9.28
#: То же точное значение, но как СУДЬЯ («срок невозможен?»), округлённое ВНИЗ.
#: Две стороны у одного числа — ADR-815: судья, ошибившийся вверх, объявляет
#: невозможным возможное (замер: 18 секунд округления у пятиминутного агента).
_FLOOR = 9.27
_DERIVED = _OFFERED


def _hours_ago(periods: list) -> list:
    """Из периодов — отметки «сколько часов назад», от свежайшей к старейшей."""
    out = [0.0]
    for gap in reversed(periods):
        out.append(out[-1] + gap)
    return out


class _Scene(unittest.TestCase):
    """Стенд с ОДНИМ производителем, чей такт воспроизводит живой замер."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.stand = _Stand(Path(self._tmp.name))

    def scene(self, slo, *, periods=None, artifact="data/subject.json"):
        short = self.stand.agent("com.spa.loop", [(artifact, slo)],
                                 schedule="interval:21600s")
        self.stand.runs(short, _hours_ago(list(_LIVE_PERIODS if periods is None else periods)))
        # Окно шире, чем сумма периодов (≈240 ч): умолчание 168 ч отрезало бы
        # ДЕВЯТЬ старейших периодов, и тест мерил бы усечённый такт, а не живой
        # замер. Окно — вход сцены, как часы.
        doc = self.stand.measure(window_hours=800.0)
        return doc, next(r for r in doc["rows"] if r["artifact"] == artifact)


# ─────────── 1. база пола — НАБЛЮДЕНИЕ, а не объявленное расписание ───────────

class FloorComesFromTheObservation(unittest.TestCase):

    def test_floor_is_derived_from_the_observed_median(self):
        """Прямая сторона: медиана живого замера ⇒ выведенный срок."""
        floor, why = sp.observed_floor(7.27764)
        self.assertEqual(floor, _FLOOR, "пол есть СУДЬЯ и округляется вниз")
        self.assertEqual(sp.offered_slo(7.27764), _OFFERED,
                         "ПРЕДЛОЖЕНИЕ округляется вверх — и это то же точное значение")
        self.assertIn("МЕДИАНА", why)

    def test_the_declared_schedule_does_NOT_produce_the_same_floor(self):
        """Обратная сторона — и это ВЕСЬ предмет ADR-506.

        Расписание у семьи объявлено `interval:21600s` (6 ч). Пол из объявления —
        8 ч, пол из наблюдения — 9,28 ч. Совпади они, замер ADR-506 («launchd
        считает от завершения прогона») не имел бы предмета, и тест обязан это
        различие СТЕРЕЧЬ, а не подтверждать равенство.
        """
        declared, _ = sp.architect_floor("interval:21600s")
        observed, _ = sp.observed_floor(7.27764)
        self.assertEqual(declared, 8.0)
        self.assertEqual(observed, _FLOOR)
        self.assertGreater(observed, declared)

    def test_the_margin_itself_has_exactly_one_definition(self):
        """Звено «правило не скопировано»: запас живёт ТОЛЬКО в `slo_proposal`.

        Обе двери обязаны двигаться от одной константы. Подменяем её и требуем,
        чтобы СДВИНУЛИСЬ ОБЕ: вторая копия правила этот контроль не переживёт.
        """
        original = sp._MARGIN_HOURS
        try:
            # Потолок двигается ВНИЗ: так он остаётся связывающим у ОБОИХ тактов,
            # и движение видно у обеих дверей. Сдвинь его вверх — у такта 6 ч
            # связывать стал бы сам такт (запас = один пропуск), и дверь молчала
            # бы не от копии правила, а от того, что константа перестала решать.
            sp._MARGIN_HOURS = 1.0
            self.assertEqual(sp.observed_floor(7.27764)[0], 8.27)
            self.assertEqual(sp.architect_floor("interval:21600s")[0], 7.0)
        finally:
            sp._MARGIN_HOURS = original
        self.assertEqual(sp.observed_floor(7.27764)[0], _FLOOR)

    def test_the_instrument_goes_THROUGH_the_module_and_not_around_it(self):
        """Звено, которое утверждение выше НЕ закрывает — и мутация это доказала.

        Проверить, что константа одна, недостаточно: прибор мог бы считать пол
        СВОЕЙ строкой (`median + 2.0`), и обе двери `slo_proposal` при этом
        остались бы верны — мутант «запас заведён вторым определением» пережил
        первую редакцию батареи именно так. Поэтому дверь проверяется ДВИЖЕНИЕМ:
        двигаем константу в модуле и требуем, чтобы сдвинулось число В СТРОКЕ
        ЗАМЕРА. Своя копия правила так не сдвинется.
        """
        original = sp._MARGIN_HOURS
        try:
            sp._MARGIN_HOURS = original + 5.0
            moved = sk._derived(7.27764, _DECLARED)
        finally:
            sp._MARGIN_HOURS = original
        self.assertEqual(moved["derived_slo_hours"], _DERIVED + 5.0)
        self.assertEqual(sk._derived(7.27764, _DECLARED)["derived_slo_hours"], _DERIVED)


# ─────────── 2. такта не наблюдали — ТРЕТИЙ ИСХОД, а не число ───────────

class AbsentObservationIsItsOwnOutcome(unittest.TestCase):

    def test_no_median_gives_no_floor_and_a_named_reason(self):
        floor, why = sp.observed_floor(None)
        self.assertIsNone(floor)
        self.assertIn("ADR-506", why)

    def test_zero_is_refused_rather_than_taken_as_a_tact(self):
        """Ноль — не «мгновенный такт», а отсутствие замера с другой стороны."""
        for bad in (0, 0.0, -1.0):
            floor, why = sp.observed_floor(bad)
            self.assertIsNone(floor, bad)
            self.assertIn("не положителен", why)

    def test_a_non_number_is_refused_rather_than_coerced(self):
        floor, why = sp.observed_floor("7.3")
        self.assertIsNone(floor)
        self.assertIn("не число", why)

    def test_a_row_without_a_producer_carries_no_floor_but_names_why(self):
        """Проводка третьего исхода: у пары без производителя пола НЕТ."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        stand = _Stand(Path(tmp.name))
        # Живой агент в сцене нужен: без перечня агентов прибор верно поднимает
        # `Unmeasured` («конституции нет»), и тест судил бы о другом отказе.
        stand.agent("com.spa.other", [("data/other.json", 7.0)])
        stand.runs("other", [0.0, 1.0, 2.0, 3.0])
        stand.artifact("data/orphan.json", 7.0, producer="com.spa.absent")
        doc = stand.measure()
        row = next(r for r in doc["rows"] if r["artifact"] == "data/orphan.json")
        self.assertIsNone(row["derived_slo_hours"])
        self.assertEqual(row["curated_vs_floor"], sp.CURATED_UNMEASURED)
        self.assertEqual(doc["curated_vs_floor"][sp.CURATED_UNMEASURED], 1)


# ─────────── 3. «ниже пола» — ДВА состояния, не одно ───────────

class BelowTheFloorIsTwoStates(unittest.TestCase):
    """Дефект ADR-813, воспроизведённый бы в НОВОЙ оси, если слить состояния."""

    def test_the_real_class_is_named_when_the_median_breaks_the_promise(self):
        axis, note = sp.audit_curated(_DECLARED, _DERIVED, 7.27764)
        self.assertEqual(axis, sp.CURATED_BELOW)
        self.assertIn("ПРЕВЫШАЕТ", note)

    def test_a_producer_without_slack_for_one_miss_is_NOT_the_same_class(self):
        """Состояние «обещание держится, но запаса на пропуск нет» — своё имя.

        **Пара в этом контроле ЗАМЕНЕНА ADR-815, и это не подгонка под новый
        ответ.** Прежде здесь стоя́л `data/resource_health.json` (срок 0,5 ч,
        медиана 0,083 ч), и он попадал сюда НЕ по своему свойству, а потому что
        запас был КОНСТАНТОЙ 2 ч: у пятиминутного агента пол 2,08 ч требовал
        срока в 25 его тактов. Из девяти пар замера 26.10 семь были таким же
        артефактом константы. Вопрос контроля («два состояния обязаны носить
        разные имена») остался, а носителем стал тот, у кого утверждение ВЕРНО:
        `data/architecture_conformance.json` — такт 6 ч при сроке 7 ч, то есть
        один пропуск срок не переживает.
        """
        floor, _ = sp.observed_floor(6.001)
        axis, note = sp.audit_curated(7.0, floor, 6.001)
        self.assertEqual(axis, sp.CURATED_MARGIN_ONLY)
        self.assertNotEqual(axis, sp.CURATED_BELOW)
        self.assertIn("ОДИН ПРОПУСК", note)

    def test_the_constant_margin_false_alarm_is_gone(self):
        """Обратная сторона той же правки: прежний носитель ушёл из класса.

        `data/resource_health.json` держит обещание с запасом ×6, и объявлять
        его срок невозможным было ложной тревогой. Контроль на ОТСУТСТВИЕ
        находки — иначе «починили» было бы нечем поверить.
        """
        floor, _ = sp.observed_floor(0.083)
        axis, note = sp.audit_curated(0.5, floor, 0.083)
        self.assertEqual(axis, sp.CURATED_ABOVE, note)

    def test_without_a_median_the_two_states_are_unmeasured_not_guessed(self):
        """Различать нечем ⇒ третий исход, а НЕ «обещание нарушено»."""
        axis, note = sp.audit_curated(_DECLARED, _DERIVED)
        self.assertEqual(axis, sp.CURATED_UNMEASURED)
        self.assertNotEqual(axis, sp.CURATED_BELOW)
        self.assertIn("НЕЧЕМ", note)

    def test_a_curated_value_at_or_above_the_floor_is_not_a_finding(self):
        for declared in (_DERIVED, _DERIVED + 1):
            axis, _ = sp.audit_curated(declared, _DERIVED, 7.27764)
            self.assertEqual(axis, sp.CURATED_ABOVE, declared)

    def test_a_missing_floor_is_unmeasured_rather_than_above(self):
        axis, why = sp.audit_curated(_DECLARED, None, 7.27764)
        self.assertEqual(axis, sp.CURATED_UNMEASURED)
        self.assertNotEqual(axis, sp.CURATED_ABOVE)
        self.assertIn("пол не выведен", why)


# ─────────── 4. проводка: прибор НЕСЁТ выведенный срок читателю ───────────

class TheInstrumentCarriesTheDerivedNumber(_Scene):

    def test_the_live_family_gets_both_the_class_and_the_number(self):
        """Главный положительный контроль: авария 26.10 целиком."""
        doc, row = self.scene(_DECLARED)
        self.assertEqual(row["verdict"], sk.UNKEEPABLE)
        self.assertEqual(row["cadence_axis"], sk.CADENCE_CANNOT_KEEP)
        self.assertEqual(row["periods"], 30)
        self.assertEqual(row["periods_over_slo"], 30)
        # Медиана стенда 7.277, а живой замер даёт 7.278: периоды в `_LIVE_PERIODS`
        # сами округлены до трёх знаков, и реконструкция отметок из них теряет
        # последний разряд. Разница НАЗВАНА, а не подогнана — и на выведенный срок
        # она не влияет: 7.277 + 2 и 7.27764 + 2 округляются в одно 9.28.
        self.assertEqual(row["observed_median_hours"], 7.277)
        self.assertEqual(row["observed_max_hours"], 23.349)
        self.assertEqual(row["derived_slo_hours"], _DERIVED)
        self.assertEqual(row["curated_vs_floor"], sp.CURATED_BELOW)
        self.assertEqual(doc["curated_vs_floor"][sp.CURATED_BELOW], 1)

    def test_raising_the_slo_to_the_derived_number_empties_the_ADR_506_class(self):
        """Лекарство ДЕЙСТВУЕТ — и это измеряется, а не утверждается."""
        doc, row = self.scene(_DERIVED)
        self.assertEqual(row["cadence_axis"], sk.CADENCE_OUTLIER)
        self.assertEqual(doc["cadence_axis"][sk.CADENCE_CANNOT_KEEP], 0)
        self.assertEqual(row["curated_vs_floor"], sp.CURATED_ABOVE)
        self.assertEqual(row["periods_over_slo"], 2)

    def test_and_it_does_NOT_hide_the_finding(self):
        """Обратная сторона лекарства — его цена.

        Поднять срок до выведенного значило бы спрятать находку, если бы вердикт
        от этого позеленел. Он НЕ зеленеет: максимум 23,349 ч по-прежнему больше
        срока, пара остаётся `unkeepable`, и меняется только КЛАСС. Позеленей
        она — лекарство было бы глушением сторожа (инв. #16).
        """
        self.assertEqual(self.scene(_DECLARED)[1]["verdict"], sk.UNKEEPABLE)
        self.assertEqual(self.scene(_DERIVED)[1]["verdict"], sk.UNKEEPABLE)

    def test_swallowing_the_outlier_would_take_a_far_larger_number(self):
        """Чтобы находка исчезла, срок пришлось бы задрать ВЫШЕ выброса.

        Это и есть граница: выведенный срок лечит ТАКТ, а не разрыв, причина
        которого не измерена.
        """
        _, row = self.scene(25.0)
        self.assertEqual(row["verdict"], sk.KEEPABLE)
        self.assertGreater(25.0, max(_LIVE_PERIODS))

    def test_every_row_carries_the_axis_so_the_tally_cannot_silently_shrink(self):
        doc, _ = self.scene(_DECLARED)
        self.assertTrue(all("curated_vs_floor" in r for r in doc["rows"]))
        self.assertEqual(sum(doc["curated_vs_floor"].values()), len(doc["rows"]))


# ─────────── 5. отчёт: число печатается ТОМУ, кого оно лечит ───────────

class TheReportOffersTheNumberOnlyWhereItCures(_Scene):

    def test_the_cannot_keep_row_is_offered_the_derived_number(self):
        doc, _ = self.scene(_DECLARED)
        body = "\n".join(sk.report(doc))
        self.assertIn("срок, который такт выдержать СПОСОБЕН", body)
        self.assertIn(f"{_DERIVED}ч", body)

    def test_an_outlier_row_is_NOT_offered_a_number(self):
        """Обратная сторона: причина выброса НЕ измерена, и советовать нечего."""
        doc, row = self.scene(_DERIVED)
        self.assertEqual(row["cadence_axis"], sk.CADENCE_OUTLIER)
        body = "\n".join(sk.report(doc))
        self.assertNotIn("срок, который такт выдержать СПОСОБЕН", body)

    def test_the_census_line_names_all_four_states(self):
        doc, _ = self.scene(_DECLARED)
        body = "\n".join(sk.report(doc))
        self.assertIn("медиана его ПРЕВЫШАЕТ", body)
        self.assertIn("такт обещание ДЕРЖИТ", body)
        self.assertIn("пол НЕ ВЫВЕДЕН", body)

    def test_a_report_written_before_this_ADR_is_unmeasured_not_clean(self):
        """Отчёт бегуна ДО ADR-814 про пол не говорит ничего — и это не ноль."""
        doc, _ = self.scene(_DECLARED)
        doc.pop("curated_vs_floor")
        body = "\n".join(sk.report(doc))
        self.assertIn("НЕ ИЗМЕРЕНО", body)
        self.assertIn("ДО ADR-814", body)


# ─────────── 6. конституция: число ДОСТАВЛЕНО в оба дома ───────────

class TheConstitutionCarriesTheDerivedNumber(unittest.TestCase):
    """Срок живёт в ДВУХ домах конституции, и в силе самое КОРОТКОЕ число.

    Поднять его в одном доме и забыть другой значит не изменить ничего:
    `manifest_slo` возьмёт прежние 7 ч как fail-CLOSED, а дерево при этом будет
    выглядеть поправленным. Поэтому проверяются ОБА дома поимённо.
    """

    def setUp(self):
        import json
        self.manifest = json.loads(
            (_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        self.loop = next(a for a in self.manifest["agents"]
                         if a["label"] == "com.spa.decision_loop")

    def family(self) -> set:
        return {p["artifact"] for p in self.loop["produces"]
                if p.get("slo_hours") == _DERIVED}

    def test_the_family_is_the_measured_sixty_nine(self):
        self.assertEqual(len(self.family()), 69)

    def test_the_second_home_agrees_pair_for_pair(self):
        top = {e["path"]: e.get("slo_hours") for e in self.manifest["artifacts"]}
        disagreeing = sorted(a for a in self.family() if top.get(a) != _DERIVED)
        self.assertEqual(disagreeing, [], "срок поднят в одном доме из двух")

    def test_the_old_number_is_gone_from_this_family(self):
        stale = sorted(p["artifact"] for p in self.loop["produces"]
                       if p.get("slo_hours") == _DECLARED)
        self.assertEqual(stale, [])

    def test_the_prose_of_the_passport_does_not_keep_the_old_number(self):
        """Третий дом числа — ПРОЗА паспорта, и она читается человеком.

        Оставить в ней «свежее 7 ч» значило бы держать опровергнутое число там,
        где его никто не сверяет машиной.
        """
        prose = (self.loop.get("passport") or {}).get("quality_metric") or ""
        for artifact in self.family():
            self.assertNotIn(f"{artifact} свежее {_DECLARED:g} ч", prose)


if __name__ == "__main__":
    unittest.main()
