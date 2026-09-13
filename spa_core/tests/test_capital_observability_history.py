"""Приёмка прибора «доля наблюдённого капитала по дням знаменателя hit_rate» (заказ #586).

Набор писался так, чтобы у КАЖДОГО вердикта прибора была парная сцена
противоположного знака: контроль, у которого нет ответа на вопрос «при каких
данных он бы НЕ прошёл», — украшение, а не проверка.

Четыре свойства закрыты отдельно и намеренно, потому что именно на них прибор
такого рода врёт молча:

1. **зелёное из отсутствия** — запись без полей провенанса обязана дать «НЕ
   ИЗМЕРЕНО» с причиной, а не 100 %. Это сама форма дефекта, ради которого
   написан инвариант #17, и первым делом такой прибор врёт именно так;
2. **знаменатель берётся у канонического производителя** — своя копия правила
   отбора была бы ВТОРЫМ определением, и спор двух копий был бы молчаливым
   (обе печатают число, ни одна — правило);
3. **структурность связи ИЗМЕРЯЕТСЯ, а не предполагается** — «все деградировавшие
   дни выпали из знаменателя» и «выпали ИЗ-ЗА ТОГО ЖЕ факта» суть разные
   утверждения, и второе понижается до WARNING, если не доказано на всех днях;
4. **несостоявшаяся сверка не есть согласие** — день с одним сигналом провенанса
   не зачитывается в `agreed`.

FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят параметром
`now=` в `measure`/`run` (константа `FIXED_NOW` ниже передаётся туда же),
поэтому ни одно утверждение набора не зависит от календаря. Даты в фикстурах
(`2026-08-01` и соседи) — ИМЕНА строк журнала решений: по ним `load_history`
сортирует и разрешает повтор дня, свойством свежести они не являются.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят параметром
# now= в measure()/run() (FIXED_NOW ниже передаётся туда же), поэтому ни одно
# утверждение набора не зависит от календаря. Даты в фикстурах — ИМЕНА строк
# журнала решений, свойством свежести они не являются.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from spa_core.monitoring import capital_observability_history as coh
from spa_core.monitoring import day_replacement_verdict_loss as drvl
from spa_core.paper_trading import shadow_trigger_eval as ste

#: Часы прибора — вход, а не окружение (правило `.claude/rules/deployment.md`).
FIXED_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

#: Нога, наблюдённая всегда: держит знаменатель непустым в любой сцене.
ANCHOR = "aave_v3"
#: Нога, которую сцены гасят.
DARK = "pendle"

D1, D2, D3 = "2026-08-01", "2026-08-02", "2026-08-03"


def _day(date: str, *, current: dict | None = None, target: dict | None = None,
         apys: dict | None = None, unevidenced: list | None = None,
         drop_evidenced_key: bool = False, drop_unevidenced_key: bool = False,
         drop_positions_key: bool = False) -> dict:
    """Одна строка журнала решений в форме настоящего писателя."""
    current = {ANCHOR: 50_000.0} if current is None else current
    row = {
        "cycle_date": date,
        "verdict": "HOLD",
        "schema": "shadow-hist-v2",
        "capital_usd": 100_000.0,
        "current_positions": dict(current),
        "target_positions": dict(current if target is None else target),
        "apy_evidenced_pct": ({k: 4.0 for k in current} if apys is None else apys),
        "apy_unevidenced": list(unevidenced or []),
    }
    if drop_evidenced_key:
        row.pop("apy_evidenced_pct")
    if drop_unevidenced_key:
        row.pop("apy_unevidenced")
    if drop_positions_key:
        row.pop("current_positions")
    return row


class _Case(unittest.TestCase):
    """Общая обвязка: журнал на диске + знаменатель, заданный сценой."""

    def measure(self, rows, *, scored=frozenset({D1, D2, D3})):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / ste.HISTORY_FILENAME).write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                encoding="utf-8")
            with mock.patch.object(
                    ste, "scored_days",
                    lambda d, **kw: (None if scored is None else set(scored))):
                return coh.measure(data_dir, now=FIXED_NOW)

    def finding(self, doc, needle):
        return [f for f in doc["findings"] if needle in f]


class ThirdOutcomeIsNamedPerDay(_Case):
    """Отсутствие наблюдения — отдельное значение, а не 0 и не 100 % (инв. #17)."""

    def test_day_without_both_provenance_fields_is_not_measured(self):
        doc = self.measure([_day(D1),
                            _day(D2, drop_evidenced_key=True,
                                 drop_unevidenced_key=True)])
        self.assertEqual([r["cycle_date"] for r in doc["per_day"]], [D1])
        unmeasured = doc["population"]["unmeasured_days"]
        self.assertEqual([u["cycle_date"] for u in unmeasured], [D2])
        self.assertEqual(unmeasured[0]["reason"], coh.DAY_NO_PROVENANCE)

    def test_the_same_day_WITH_provenance_is_measured(self):
        """Парная сцена: без неё сцена выше краснела бы и на сломанном разборе."""
        doc = self.measure([_day(D1), _day(D2)])
        self.assertEqual([r["cycle_date"] for r in doc["per_day"]], [D1, D2])
        self.assertEqual(doc["population"]["unmeasured_days"], [])

    def test_unmeasured_day_is_not_silently_counted_as_full_observation(self):
        """Дефект, ради которого прибор написан: зелёное, изготовленное из пустоты."""
        doc = self.measure([_day(D1, drop_evidenced_key=True,
                                 drop_unevidenced_key=True)],
                           scored={D1})
        self.assertEqual(doc["answer"]["at_full_observation"], 0)
        self.assertEqual(doc["answer"]["not_measured"], 1)
        self.assertEqual(doc["status"], coh.STATUS_UNMEASURED)

    def test_empty_book_day_is_not_measured_and_says_why(self):
        doc = self.measure([_day(D1), _day(D2, current={})])
        self.assertEqual(doc["population"]["unmeasured_days"][0]["reason"],
                         coh.DAY_EMPTY_BOOK)

    def test_day_without_positions_map_is_not_measured_and_says_why(self):
        doc = self.measure([_day(D1), _day(D2, drop_positions_key=True)])
        self.assertEqual(doc["population"]["unmeasured_days"][0]["reason"],
                         coh.DAY_NO_BOOK)

    def test_three_reasons_stay_distinct(self):
        """Разные причины — разные адресаты починки; слив их в одну скрыл бы адрес."""
        doc = self.measure([_day(D1, drop_positions_key=True),
                            _day(D2, current={}),
                            _day(D3, drop_evidenced_key=True,
                                 drop_unevidenced_key=True)])
        self.assertEqual(
            {u["cycle_date"]: u["reason"]
             for u in doc["population"]["unmeasured_days"]},
            {D1: coh.DAY_NO_BOOK, D2: coh.DAY_EMPTY_BOOK, D3: coh.DAY_NO_PROVENANCE})


class AccountingIdentity(_Case):
    """Пока тождество держится, уронить день молча нельзя ПО ПОСТРОЕНИЮ."""

    def test_measured_plus_unmeasured_equals_input_counted_from_the_source(self):
        rows = [_day(D1), _day(D2, current={}),
                _day(D3, drop_evidenced_key=True, drop_unevidenced_key=True)]
        doc = self.measure(rows)
        # Ожидание считается ИЗ ИСТОЧНИКА, а не из отчёта сверки: производная от
        # собственного вывода прибора была бы утверждением о самой себе.
        self.assertEqual(doc["population"]["input_days"], len(rows))
        self.assertEqual(
            len(doc["per_day"]) + len(doc["population"]["unmeasured_days"]),
            len(rows))
        self.assertTrue(doc["population"]["accounting_identity_holds"])

    def test_duplicate_and_corrupt_lines_are_NAMED_not_silently_lost(self):
        """Разница «строк в файле» и «дней замера» обязана быть объяснена поимённо."""
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / ste.HISTORY_FILENAME).write_text(
                json.dumps(_day(D1)) + "\n"
                + json.dumps(_day(D1)) + "\n"      # повтор дня — схлопнется
                + "{не json\n"                      # нечитаемая строка
                + json.dumps(_day(D2)) + "\n",
                encoding="utf-8")
            with mock.patch.object(ste, "scored_days", lambda d, **kw: {D1}):
                doc = coh.measure(data_dir, now=FIXED_NOW)
        rec = doc["population"]["reader_reconciliation"]
        self.assertEqual(rec["journal_lines"], 4)
        self.assertEqual(rec["distinct_dates"], 2)
        self.assertEqual(rec["corrupt_lines"], 1)
        self.assertEqual(rec["duplicate_date_lines_collapsed"], 1)
        self.assertTrue(rec["readers_agree"])
        self.assertTrue(doc["population"]["accounting_identity_holds"])

    def test_readers_disagreeing_is_unmeasured_with_the_two_counts_named(self):
        """Парная сцена: у флага обязана быть достижимая ветка ОТКАЗА.

        Без неё «учёт замкнулся» истинно по построению — украшение, а не
        проверка: мутация «флаг всегда True» пережила бы весь набор.
        """
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / ste.HISTORY_FILENAME).write_text(
                json.dumps(_day(D1)) + "\n" + json.dumps(_day(D2)) + "\n",
                encoding="utf-8")
            real = ste.load_history
            with mock.patch.object(
                    coh, "load_history",
                    lambda d, *a, **kw: (real(d)[0][:1], real(d)[1])), \
                 mock.patch.object(ste, "scored_days", lambda d, **kw: {D1}):
                doc = coh.measure(data_dir, now=FIXED_NOW)
        self.assertFalse(doc["population"]["accounting_identity_holds"])
        self.assertFalse(doc["population"]["reader_reconciliation"]["readers_agree"])
        self.assertEqual(doc["status"], coh.STATUS_UNMEASURED)
        line, = [f for f in doc["findings"] if "учёт не замкнулся" in f]
        self.assertIn("два чтения одного файла спорят", line)

    def test_missing_journal_file_is_unmeasured_not_agreement(self):
        with TemporaryDirectory() as tmp:
            with mock.patch.object(ste, "scored_days", lambda d, **kw: {D1}):
                doc = coh.measure(Path(tmp), now=FIXED_NOW)
        self.assertFalse(
            doc["population"]["reader_reconciliation"]["measured"])
        self.assertEqual(doc["status"], coh.STATUS_UNMEASURED)

    def test_broken_identity_is_unmeasured_not_a_clean_pass(self):
        doc = self.measure([_day(D1)])
        doc["population"]["accounting_identity_holds"] = False
        self.assertEqual(coh._status(doc, []), coh.STATUS_UNMEASURED)
        self.assertTrue(coh._findings(doc, [])[0].startswith("[НЕ ИЗМЕРЕНО]"))


class ObservationRule(_Case):
    """Наблюдение — согласие двух сигналов; расхождение читается fail-CLOSED."""

    def test_share_falls_by_DOLLARS_not_by_rounded_percent(self):
        doc = self.measure([_day(D1, current={ANCHOR: 99_999.0, DARK: 1.0},
                                 apys={ANCHOR: 4.0}, unevidenced=[DARK])])
        row = doc["per_day"][0]
        self.assertFalse(row["fully_observed"])
        self.assertEqual(round(row["observed_pct"], 2), 100.00)

    def test_fully_observed_book_is_fully_observed(self):
        row = self.measure([_day(D1)])["per_day"][0]
        self.assertTrue(row["fully_observed"])
        self.assertEqual(row["observed_pct"], 100.0)

    def test_rate_present_but_listed_unevidenced_reads_unobserved(self):
        doc = self.measure([_day(D1, current={ANCHOR: 50_000.0, DARK: 50_000.0},
                                 apys={ANCHOR: 4.0, DARK: 8.0},
                                 unevidenced=[DARK])])
        row = doc["per_day"][0]
        self.assertEqual([x["protocol"] for x in row["unobserved"]], [DARK])
        self.assertEqual(len(doc["provenance_cross_check"]["disagreements"]), 1)
        self.assertTrue(self.finding(doc, "два поля ОДНОЙ записи спорят"))

    def test_absent_rate_not_listed_unevidenced_also_reads_unobserved(self):
        """Второе направление того же спора: молчание карты — тоже не наблюдение."""
        doc = self.measure([_day(D1, current={ANCHOR: 50_000.0, DARK: 50_000.0},
                                 apys={ANCHOR: 4.0}, unevidenced=[])])
        self.assertEqual([x["protocol"] for x in doc["per_day"][0]["unobserved"]],
                         [DARK])
        self.assertEqual(len(doc["provenance_cross_check"]["disagreements"]), 1)

    def test_non_numeric_rate_is_not_an_observation(self):
        doc = self.measure([_day(D1, current={ANCHOR: 50_000.0, DARK: 50_000.0},
                                 apys={ANCHOR: 4.0, DARK: "live"},
                                 unevidenced=[DARK])])
        self.assertEqual([x["protocol"] for x in doc["per_day"][0]["unobserved"]],
                         [DARK])

    # ЦИКЛ #587 — две сцены, дописанные ПРИ ПОДЪЁМЕ работы цикла #586.
    # Батарея мутаций этого цикла (28 координат по поверхностям решения) оставила
    # в живых три мутанта. Один из них эквивалентен ПО ПОСТРОЕНИЮ и потому верен:
    # `votes` не может оказаться пустым — оба немых сигнала означают отсутствие
    # ОБОИХ полей провенанса, а такой день отсекается раньше, третьим исходом
    # (`DAY_NO_PROVENANCE`). Два других мутанта были настоящими дырами покрытия, и
    # закрывают их сцены ниже. Проверки не ослаблены и не сужены: сюда только
    # добавлено (инв. #16).

    def test_boolean_is_NOT_a_rate(self):
        """`True` — не ставка 1 %, а другой тип; иначе булево наблюдает капитал.

        Мутант «убрать исключение `bool` из `_numeric`» выживал: сцена со строкой
        (`"live"`) есть, а с булевым не было. Разница не косметическая — `True`
        единственное не-число, которое `float()` проглотит молча, превратив
        ненаблюдённую ногу в наблюдённую на все её доллары.
        """
        doc = self.measure([_day(D1, current={ANCHOR: 50_000.0, DARK: 50_000.0},
                                 apys={ANCHOR: 4.0, DARK: True},
                                 unevidenced=[])])
        row = doc["per_day"][0]
        self.assertEqual([x["protocol"] for x in row["unobserved"]], [DARK])
        self.assertEqual(row["observed_usd"], 50_000.0)

    def test_position_of_exactly_zero_is_not_a_funded_leg(self):
        """Ключ с $0 в книге — не профинансированная нога, и в отчёт не попадает.

        Мутант «`amount > 0` → `>= 0`» выживал: долю он не двигает (ноль долларов
        и есть ноль), но подмешивает в `unobserved` строку на $0 и переводит
        `unobserved_leg_is_material` из `None` в булево. То есть читатель отчёта
        видит ненаблюдённую ногу там, где денег нет вовсе.
        """
        doc = self.measure([_day(D1, current={ANCHOR: 50_000.0, DARK: 0.0},
                                 apys={ANCHOR: 4.0}, unevidenced=[DARK])])
        row = doc["per_day"][0]
        self.assertEqual(row["deployed_usd"], 50_000.0)
        self.assertEqual(row["unobserved"], [])
        self.assertIsNone(row["unobserved_leg_is_material"])
        self.assertTrue(row["fully_observed"])

    def test_one_signal_day_is_NOT_counted_as_agreed(self):
        doc = self.measure([_day(D1), _day(D2, drop_unevidenced_key=True)])
        cross = doc["provenance_cross_check"]
        self.assertEqual(cross["days_with_both_signals"], 1)
        self.assertEqual(cross["days_with_one_signal"], 1)
        self.assertEqual(cross["agreed"], 1)

    def test_both_signals_day_IS_counted_as_agreed(self):
        cross = self.measure([_day(D1), _day(D2)])["provenance_cross_check"]
        self.assertEqual(cross["days_with_both_signals"], 2)
        self.assertEqual(cross["agreed"], 2)


class MaterialLegThreshold(_Case):
    """«Существенность» берётся у судьи, а не переписывается второй копией."""

    def _moved(self, delta):
        doc = self.measure([_day(
            D1, current={ANCHOR: 50_000.0, DARK: 50_000.0},
            target={ANCHOR: 50_000.0, DARK: 50_000.0 - delta},
            apys={ANCHOR: 4.0}, unevidenced=[DARK])])
        return doc["per_day"][0]["unobserved_leg_is_material"]

    def test_move_at_the_judges_threshold_is_material(self):
        self.assertTrue(self._moved(ste.MATERIAL_TURNOVER_USD))

    def test_move_below_the_judges_threshold_is_not(self):
        self.assertFalse(self._moved(ste.MATERIAL_TURNOVER_USD - 0.01))


class DenominatorComesFromTheCanonicalProducer(_Case):
    """Второго определения знаменателя нет — ни здесь, ни у соседа."""

    def test_module_follows_the_canonical_producer(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / ste.HISTORY_FILENAME).write_text(
                json.dumps(_day(D1)) + "\n" + json.dumps(_day(D2)) + "\n",
                encoding="utf-8")
            with mock.patch.object(ste, "scored_days", lambda d, **kw: {D2}):
                doc = coh.measure(data_dir, now=FIXED_NOW)
        self.assertEqual(doc["denominator"]["days"], [D2])

    def test_canonical_producer_returns_none_on_failure_not_empty_set(self):
        with mock.patch.object(ste, "evaluate_window",
                               side_effect=RuntimeError("нет журнала")):
            self.assertIsNone(ste.scored_days(Path("/nonexistent")))

    def test_canonical_producer_returns_none_when_rows_are_not_a_list(self):
        with mock.patch.object(ste, "evaluate_window",
                               return_value={"per_verdict": None}):
            self.assertIsNone(ste.scored_days(Path("/nonexistent")))

    def test_canonical_producer_keeps_only_scored_days(self):
        report = {"per_verdict": [
            {"cycle_date": D1, "trivial": False, "outcome": "hit"},
            {"cycle_date": D2, "trivial": True, "outcome": "hit"},
            {"cycle_date": D3, "trivial": False, "outcome": "UNCHECKED"},
        ]}
        with mock.patch.object(ste, "evaluate_window", return_value=report):
            self.assertEqual(ste.scored_days(Path("/nonexistent")), {D1})

    def test_day_replacement_verdict_loss_delegates_to_the_same_definition(self):
        """Поведенчески: сосед обязан вернуть ровно то, что сказал производитель."""
        with mock.patch.object(ste, "scored_days", lambda d, **kw: {"дал-производитель"}):
            self.assertEqual(drvl._scored_days(Path("/nonexistent")),
                             {"дал-производитель"})


class TheAnswerToTheOrder(_Case):
    """На скольких днях знаменателя капитал стоял на наблюдённых числах."""

    def _degraded_day(self, date, *, material: bool):
        # Ненаблюдённая нога либо ДВИГАЕТСЯ (тот же факт делает день неоценимым),
        # либо стои́т на месте — и тогда исключение дня имеет другую причину.
        target = {ANCHOR: 50_000.0, DARK: 50_000.0}
        if material:
            target[DARK] = 50_000.0 - 10 * ste.MATERIAL_TURNOVER_USD
        return _day(date, current={ANCHOR: 50_000.0, DARK: 50_000.0},
                    target=target, apys={ANCHOR: 4.0}, unevidenced=[DARK])

    def test_clean_window_is_OK_and_says_the_regime_never_happened(self):
        doc = self.measure([_day(D1), _day(D2)], scored={D1, D2})
        self.assertEqual(doc["status"], coh.STATUS_OK)
        self.assertEqual(doc["answer"],
                         {"scored_days": 2, "at_full_observation": 2,
                          "below_full_observation": 0, "not_measured": 0})
        self.assertTrue(self.finding(doc, "режима деградации в окне не было вовсе"))

    def test_degraded_day_INSIDE_the_denominator_is_critical(self):
        doc = self.measure([self._degraded_day(D1, material=True)], scored={D1})
        self.assertEqual(doc["status"], coh.STATUS_CRITICAL)
        self.assertEqual(doc["answer"]["below_full_observation"], 1)
        self.assertTrue(self.finding(doc, "стоят на КАПИТАЛЕ, часть которого не наблюдена"))

    def test_all_degraded_days_excluded_by_the_same_fact_is_critical(self):
        doc = self.measure([_day(D1), self._degraded_day(D2, material=True)],
                           scored={D1})
        self.assertEqual(doc["status"], coh.STATUS_CRITICAL)
        self.assertTrue(self.finding(doc, "НИ РАЗУ не оценивался в режиме деградации"))
        self.assertEqual(doc["degraded_days"][0]["in_denominator"], False)
        self.assertTrue(doc["degraded_days"][0]["unobserved_leg_is_material"])

    def test_degraded_day_excluded_for_ANOTHER_reason_is_only_warning(self):
        """Парная сцена: «выпали все» и «выпали из-за того же факта» — разное."""
        doc = self.measure([_day(D1), self._degraded_day(D2, material=False)],
                           scored={D1})
        self.assertEqual(doc["status"], coh.STATUS_WARNING)
        self.assertTrue(self.finding(doc, "совпадение совпадением и остаётся"))
        self.assertFalse(self.finding(doc, "НИ РАЗУ не оценивался"))

    def test_每_degraded_day_is_named_with_its_share_and_its_side(self):
        doc = self.measure([_day(D1), self._degraded_day(D2, material=True)],
                           scored={D1})
        line, = self.finding(doc, D2)
        self.assertIn("50.00 %", line)
        self.assertIn("вне знаменателя", line)
        self.assertIn(DARK, line)


class DenominatorUnmeasured(_Case):
    """Не ответил производитель ⇒ НЕ ИЗМЕРЕНО, а не пустое множество."""

    def test_missing_denominator_is_unmeasured_with_a_reason(self):
        doc = self.measure([_day(D1)], scored=None)
        self.assertEqual(doc["status"], coh.STATUS_UNMEASURED)
        self.assertIsNone(doc["answer"])
        self.assertFalse(doc["denominator"]["measured"])
        self.assertTrue(self.finding(doc, "пустым множеством он НЕ подменяется"))

    def test_present_denominator_yields_an_answer(self):
        doc = self.measure([_day(D1)], scored={D1})
        self.assertIsNotNone(doc["answer"])
        self.assertTrue(doc["denominator"]["measured"])

    def test_empty_denominator_is_unmeasured_not_ok(self):
        """Ноль оценённых дней — не «всё чисто»: доли у пустого знаменателя нет."""
        doc = self.measure([_day(D1)], scored=set())
        self.assertEqual(doc["status"], coh.STATUS_UNMEASURED)

    def test_empty_journal_is_unmeasured(self):
        doc = self.measure([])
        self.assertEqual(doc["status"], coh.STATUS_UNMEASURED)
        self.assertTrue(self.finding(doc, "журнал решений пуст"))

    def test_producer_REFUSING_BY_EXCEPTION_is_unmeasured_with_the_cause_kept(self):
        """Отказ производителя БРОСКОМ — та же «не измерено», и причина не теряется.

        Найдено подъёмом цикла #588 своей батареей мутаций: ветка
        ``except Exception → days = None`` не была закреплена ничем, и подмена
        её на ``days = set()`` не покраснила НИ ОДНОГО теста. Вердикт при этом
        оставался ``UNMEASURED`` (пустой знаменатель ловится отдельно, см.
        ``test_empty_denominator_is_unmeasured_not_ok``) — терялась ПРИЧИНА:
        артефакт объявлял знаменатель ИЗМЕРЕННЫМ и пустым вместо «производитель
        не ответил». Инвариант #17 требует различать три исхода у КАЖДОГО
        производителя числа, а здесь «не измерено» переодевалось в «измерено и
        равно нулю» — ровно в тот исход, который инвариант и разделяет.
        Возврат ``None`` закреплён выше; бросок — здесь.
        """
        def boom(_d, **_kw):
            raise RuntimeError("производитель знаменателя упал")

        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / ste.HISTORY_FILENAME).write_text(
                json.dumps(_day(D1)) + "\n", encoding="utf-8")
            with mock.patch.object(ste, "scored_days", boom):
                doc = coh.measure(data_dir, now=FIXED_NOW)

        self.assertFalse(doc["denominator"]["measured"])
        self.assertIsNone(doc["denominator"]["days"])
        self.assertIn("пустым множеством он НЕ подменяется",
                      doc["denominator"]["reason"])
        self.assertIsNone(doc["answer"])
        self.assertEqual(doc["status"], coh.STATUS_UNMEASURED)


class TheSecondAxisIsNamedNotSilent(_Case):
    """Печатать одну ось за обе — дефект, найденный ADR-364 у feed_coverage."""

    def test_tvl_axis_is_reported_unmeasured_with_a_reason(self):
        doc = self.measure([_day(D1)])
        self.assertEqual(doc["axis"], "apy")
        self.assertFalse(doc["tvl_axis"]["measured"])
        self.assertIn("не несёт TVL", doc["tvl_axis"]["reason"])

    def test_the_office_line_names_the_axis_before_any_number(self):
        lines = coh.format_report(self.measure([_day(D1)]))
        self.assertIn("ось TVL по истории НЕ ИЗМЕРЕНА", lines[1])

    def test_office_line_says_NOT_MEASURED_instead_of_zero_on_a_missing_key(self):
        """Отчёт старого образца молчал бы ровно так же, как здоровый."""
        lines = coh.format_report({"status": "OK", "journal_rows": 3})
        self.assertIn("измерено НЕ ИЗМЕРЕНО", lines[0])
        self.assertNotIn("не измерено 0", lines[0])

    def test_office_line_prints_the_counts_when_they_ARE_measured(self):
        lines = coh.format_report(self.measure([_day(D1)]))
        self.assertIn("измерено 1", lines[0])
        self.assertIn("не измерено 0", lines[0])

    def test_limits_of_the_claim_live_in_the_ARTIFACT_not_only_the_docstring(self):
        doc = self.measure([_day(D1)])
        blob = " ".join(doc["what_it_does_not_prove"])
        self.assertIn("hit_rate_selection_bias", blob)
        self.assertIn("unevidenced_leg_causes", blob)
        self.assertIn("ось TVL", blob)


class BridgeShape(_Case):
    """Форма, которую ждут ступень переписей и шаг 0-офис."""

    def _run(self, rows, scored):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / ste.HISTORY_FILENAME).write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            with mock.patch.object(ste, "scored_days",
                                   lambda d, **kw: (None if scored is None
                                                    else set(scored))):
                doc = coh.run(root=str(root), now=FIXED_NOW)
            self.assertTrue((root / "data" / coh.OUTPUT_FILENAME).is_file())
        return doc

    def test_run_writes_the_artifact_and_carries_overall_and_counts(self):
        doc = self._run([_day(D1)], {D1})
        self.assertEqual(doc["overall"], doc["status"])
        self.assertEqual(doc["counts"]["critical"], 0)

    def test_unchecked_is_counted_apart_from_zeros(self):
        """Растворив «не измерено» в нулях, мы сделали бы молчание неотличимым."""
        doc = self._run([_day(D1)], None)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)
        self.assertEqual(doc["counts"]["critical"], 0)


class WiredAtBirth(unittest.TestCase):
    """Прибор без потребителя — источник, до которого никто не доехал."""

    ARTIFACT = "data/capital_observability_history.json"

    def test_declared_in_the_bridge_census(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("capital_observability_history", fb.CENSUS_STAGE)
        self.assertIn(self.ARTIFACT, fb.PRODUCES)
        self.assertEqual(
            fb.CENSUS_PRODUCT["capital_observability_history"]["artifact"],
            self.ARTIFACT)

    def test_declared_in_BOTH_manifest_homes(self):
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads((root / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        self.assertIn(self.ARTIFACT,
                      [a["path"] for a in manifest["artifacts"]])
        produced = [p["artifact"] for a in manifest["agents"]
                    for p in a.get("produces", [])]
        self.assertIn(self.ARTIFACT, produced)

    def test_the_office_renders_it_through_its_own_formatter(self):
        """Поведенчески: диспетчер обязан позвать ИМЕННО наш форматтер."""
        import importlib.util
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "_coh_office_probe", root / "scripts" / "consume_office_reports.py")
        office = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(office)
        name = "capital_observability_history.json"
        self.assertIn(name, office._READ_SCHEMA)
        self.assertEqual(office._PRODUCER[name],
                         "spa_core/monitoring/capital_observability_history.py")
        sentinel = "СТРОКА-МАЯК ФОРМАТТЕРА"
        with mock.patch.object(coh, "format_report", return_value=[sentinel]):
            out = office._summarize_json(f"/tmp/{name}", {"status": "OK"},
                                         root=str(root))
        self.assertIn(sentinel, out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
