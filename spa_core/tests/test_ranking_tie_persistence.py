"""Сторож устойчивости ничьих (``ranking_tie_persistence``), заказ #536.

Каждая сцена — вопрос, на который прибор обязан отвечать ИЗМЕРЕНИЕМ, а не
формой отчёта. Ключевые воспроизводят настоящие ловушки этого замера:

* ``test_a_coverage_dependent_producer_makes_the_census_refuse`` —
  ЕДИНСТВЕННАЯ опора прибора. Журнал несёт 4–6 ставок в день, живой снимок
  ранжирует 14; право реконструировать день по ставкам журнала держится на том,
  что счёт и стоимость перестановки от ПОКРЫТИЯ не зависят. Зависели бы —
  прибор мерил бы покрытие журнала, выдавая его за книгу дня. Опора меряется
  каждый прогон, и у неё есть положительный контроль: производитель, чей счёт
  зависит от числа ключей, обязан ОСТАНОВИТЬ перепись.
* ``test_run_is_counted_twice_because_consecutive_has_two_meanings`` — дни
  журнала не сплошные. «Пять дней подряд» по наблюдениям может быть тремя по
  календарю, и одно число вместо двух утверждало бы режим, которого нет.
* ``test_a_census_pair_never_co_observed_is_unmeasured_not_never_a_tie`` —
  главный fail-CLOSED: молчание журнала о паре НЕ есть «пара не ничья».
* ``test_identity_and_tie_stay_separate_predicates`` — ловушка #535 в силе:
  ничья ОДНОГО пула под двумя именами и ничья ДВУХ инструментов это разные
  предметы и разные решения владельца.
* ``test_names_are_not_merged_by_pool_identity_only_annotated`` — журнал зовёт
  пул одним именем, снимок другим; срастив их молча, мы подменили бы «эта пара
  наблюдалась» на «наблюдалась похожая».
* ``test_an_inert_day_axis_is_declared_not_passed_off_as_a_regime`` — прибор,
  повторивший снимок одного дня столько раз, сколько в журнале строк, обязан
  сказать это вслух: «не измерено» неотличимо от «измерено» только пока молчит.

Тесты герметичны: живой ``data/`` не читается и не пишется, производитель цели
инъектируется. Герметичность проверяется ОТДЕЛЬНОЙ сценой и на СЛОМАННОМ
субъекте тоже — занятая у исправного субъекта, она перестаёт держать ровно
тогда, когда нужна.

FROZEN-DATE-OK: injected-clock — час замера подаётся в ``measure(..., now=)``
параметром; даты журнала суть ПРЕДМЕТ проверки (календарная серия считается по
ним), а не окружение, и от календаря машины не зависят.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import ranking_tie_census as rtc
from spa_core.monitoring import ranking_tie_persistence as rtp

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
CAPITAL = 100_000.0
QUANTUM = 0.0001
MULT = 0.85


# ──────────────────────────────────────────────────────────────────────────
# стенд
# ──────────────────────────────────────────────────────────────────────────
def make_producer(caps, *, budget=0.5, capital=CAPITAL, quantum=QUANTUM,
                  mult=MULT, coverage_dependent=False):
    """{ставки в долях} → (цель $, разбор со счётом, капитал).

    Форма та же, что у ``optimized_yield_breakdown``: победитель получает ПОЛНЫЙ
    потолок, величина победы в размер порции не входит. Ставка квантуется ровно
    так же, как её округляет аллокатор.

    ``coverage_dependent`` — положительный контроль на опору: счёт начинает
    зависеть от ЧИСЛА поданных ключей, то есть от покрытия журнала.
    """
    def produce(provider):
        factor = (1.0 + 0.01 * len(provider)) if coverage_dependent else 1.0
        scores = {}
        for key, val in provider.items():
            pp = float(val) * 100.0
            if quantum:
                pp = round(pp / quantum) * quantum
            scores[key] = pp * mult * factor
        order = sorted(scores, key=lambda k: (-scores[k], k))
        left, target = budget, {}
        for key in order:
            room = min(float(caps.get(key, 0.0)), left)
            if room <= 1e-12:
                continue
            target[key] = room * capital
            left -= room
        breakdown = {k: {"score": s, "risk_multiplier": mult}
                     for k, s in scores.items()}
        return target, breakdown, capital
    return produce


def write_snapshot(data_dir: Path, rates_pp: dict, days: list, *,
                   compared: list | None = None,
                   collisions: list | None = None) -> None:
    """Живой снимок + журнал решений по дням + артефакт тождества пула.

    ``days`` — [(дата, {ключ: ставка в ПРОЦЕНТАХ})], ровно та форма, в которой
    писатель решения кладёт ``apy_evidenced_pct``.
    """
    (data_dir / "adapter_status.json").write_text(json.dumps(
        {"adapters": {k: {"live_apy": v} for k, v in rates_pp.items()}}),
        encoding="utf-8")
    rows = [{"cycle_date": d, "apy_evidenced_pct": r} for d, r in days]
    (data_dir / "allocation_rationale_history.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if compared is not None:
        (data_dir / rtc.IDENTITY_ARTIFACT).write_text(json.dumps(
            {"keys_compared": compared,
             "collisions": [{"keys": list(k)} for k in (collisions or [])]}),
            encoding="utf-8")


def measure(data_dir, producer, **kw):
    return rtp.measure(Path(data_dir), now=NOW,
                       producer_factory=lambda _sandbox: producer, **kw)


def pair_row(doc, name):
    for r in doc["pairs"]:
        if r["pair"] == name:
            return r
    raise AssertionError(f"пары {name} нет в переписи: "
                         f"{[r['pair'] for r in doc['pairs']]}")


# сцены ───────────────────────────────────────────────────────────────────
#: Живой снимок: a забирает 0.4, b — оставшиеся 0.1 из бюджета 0.5; c и d в
#: цель не входят. Ставки b и c совпадают ДО ЗНАКА — ничья, решающая деньги.
CAPS = {"a_anchor": 0.4, "b_holder": 0.2, "c_rival": 0.2, "d_far": 0.2}
LIVE_RATES = {"a_anchor": 8.0, "b_holder": 4.0, "c_rival": 4.0, "d_far": 1.0}

#: Журнал: b/c ничья КАЖДЫЙ наблюдённый день, но дни не сплошные —
#: 08-01…08-03, затем провал до 08-20. Пять наблюдений, три календарных дня.
#: a/b меняет вердикт от дня ко дню: без этого ось дней была бы инертна.
#:
#: `e_journal` живёт ТОЛЬКО в журнале (в живом снимке его нет) — значит пара
#: a/e есть КОНТЕКСТ, а не пара переписи, и её календарная серия (5 дн.,
#: 08-01…08-05) ДЛИННЕЕ, чем у любой пары переписи (3 дн. у b/c). Без такой
#: пары сцена не отличает «максимум» от «первой строки после пересортировки»,
#: и проверка головной строки была бы украшением: замер это подтвердил —
#: мутация `longest` → `regime[0]` на прежней сцене ВЫЖИВАЛА.
DAYS = [
    ("2026-08-01", {"a_anchor": 8.0, "b_holder": 4.0, "c_rival": 4.0,
                    "e_journal": 7.9}),
    ("2026-08-02", {"a_anchor": 5.0, "b_holder": 4.9, "c_rival": 4.8,
                    "e_journal": 4.95}),
    ("2026-08-03", {"a_anchor": 8.0, "b_holder": 4.1, "c_rival": 4.2,
                    "e_journal": 7.9}),
    ("2026-08-04", {"a_anchor": 8.0, "b_holder": 4.3, "e_journal": 7.9}),
    ("2026-08-05", {"a_anchor": 8.0, "b_holder": 4.2, "e_journal": 7.9}),
    ("2026-08-20", {"a_anchor": 5.2, "b_holder": 5.0, "c_rival": 5.1}),
    ("2026-08-21", {"a_anchor": 8.0, "b_holder": 4.0, "c_rival": 4.0}),
]
ALL_KEYS = sorted(LIVE_RATES)


class TheAnswerToTheOrder(unittest.TestCase):
    """Сколько дней ПОДРЯД одна и та же пара остаётся ничьёй."""

    def _measure(self, **kw):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS,
                           compared=ALL_KEYS, collisions=[])
            return measure(d, make_producer(CAPS), **kw)

    def test_the_permanent_tie_is_found_and_counted(self):
        doc = self._measure()
        row = pair_row(doc, "b_holder/c_rival")
        self.assertEqual(row["class"], "always_a_tie", doc["findings"])
        self.assertEqual(row["days_observed"], 5)
        self.assertEqual(row["days_tie"], 5)

    def test_run_is_counted_twice_because_consecutive_has_two_meanings(self):
        """Пять наблюдений подряд — это ТРИ дня подряд по календарю."""
        row = pair_row(self._measure(), "b_holder/c_rival")
        self.assertEqual(row["longest_run_observed"], 5)
        self.assertEqual(row["longest_run_calendar"], 3)
        self.assertEqual(row["longest_run_calendar_from"], "2026-08-01")
        self.assertEqual(row["longest_run_calendar_to"], "2026-08-03")

    def test_the_calendar_run_and_not_the_observed_one_reaches_the_finding(self):
        doc = self._measure()
        # ИМЕННО построчная находка о паре, а не головная строка: та тоже
        # называет пару, и нестрогий отбор проверял бы не тот текст.
        line = next(f for f in doc["findings"]
                    if f.startswith("[CRITICAL] b_holder/c_rival:"))
        self.assertIn("КАЛЕНДАРЮ 3", line)
        self.assertIn("по наблюдениям 5", line)

    def test_an_occasional_tie_is_a_different_class_from_a_permanent_one(self):
        """Ровно то различие, ради которого заказ #536 и написан."""
        doc = self._measure()
        self.assertEqual(pair_row(doc, "a_anchor/b_holder")["class"],
                         "sometimes_a_tie")
        self.assertEqual(pair_row(doc, "b_holder/c_rival")["class"],
                         "always_a_tie")

    def test_headline_leads_with_the_census_population_not_the_biggest_number(self):
        doc = self._measure()
        head = doc["findings"][0]
        self.assertIn("ОТВЕТ ЗАКАЗУ #536", head)
        self.assertIn("НИ РАЗУ", head)

    def test_the_headline_maximum_is_the_real_maximum_not_the_first_row(self):
        """Население пересортировывается «пары переписи первыми», и рекорд
        перестаёт быть первой строкой. Головная строка обязана называть
        НАСТОЯЩИЙ максимум — иначе она говорит «максимум 5» там, где 6."""
        doc = self._measure()
        real_max = max(r["longest_run_calendar"] for r in doc["pairs"])
        winner = next(r for r in doc["pairs"]
                      if r["longest_run_calendar"] == real_max)
        head = doc["findings"][0]
        self.assertIn(f"максимум {real_max} дн. ({winner['pair']})", head)

    def test_status_is_critical_when_a_tie_is_a_regime(self):
        self.assertEqual(self._measure()["status"], rtp.STATUS_CRITICAL)

    def test_a_short_run_stays_a_case_and_is_not_called_a_regime(self):
        """Порог режима — вход, а не зашитая константа."""
        doc = self._measure(regime_run_days=99)
        self.assertNotEqual(doc["status"], rtp.STATUS_CRITICAL)
        self.assertFalse([f for f in doc["findings"]
                          if f.startswith("[CRITICAL]")])


class TheSupportThatLicensesReconstructingADay(unittest.TestCase):
    """Опора: покрытие журнала не меняет счёта и стоимости перестановки."""

    def test_the_support_is_measured_every_run_and_holds_here(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = measure(d, make_producer(CAPS))
        ci = doc["coverage_independence"]
        self.assertEqual(ci["verdict"], "independent", ci)
        self.assertEqual(ci["max_score_delta"], 0.0)
        self.assertEqual(ci["days_checked"], len(DAYS))
        self.assertGreater(ci["flips_identical"], 0)

    def test_a_coverage_dependent_producer_makes_the_census_refuse(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на единственную опору прибора.

        Счёт, зависящий от ЧИСЛА поданных ключей, означает, что реконструкция
        дня по 4–6 ставкам мерит покрытие журнала. Прибор обязан остановиться
        ГРОМКО, а не посчитать серии по величине, которая от вопроса не зависит.
        """
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = measure(d, make_producer(CAPS, coverage_dependent=True))
        self.assertEqual(doc["coverage_independence"]["verdict"],
                         "DEPENDS_ON_COVERAGE")
        self.assertEqual(doc["status"], rtp.STATUS_UNMEASURED)
        self.assertEqual(doc["pairs"], [])
        self.assertTrue(any("опора не подтверждена" in f
                            for f in doc["findings"]), doc["findings"])

    def test_agreement_on_no_flip_in_range_is_not_counted_as_divergence(self):
        """``None`` в ОБОИХ режимах — согласие, а не расхождение.

        Считать его расхождением значило бы уронить опору на самом частом
        честном исходе и превратить прибор в вечное «не измерено».
        """
        produce = make_producer(CAPS)
        live = {k: v / 100.0 for k, v in LIVE_RATES.items()}
        # Разрыв заведомо больше предела поиска перестановки (_FLIP_MAX_PP = 12
        # pp): 50 pp против 0.001 pp — подняв нижнего на 12 pp, верхнего не
        # обойти НИ в одном режиме, и оба отвечают None. Первая редакция сцены
        # ставила 8 pp, где перестановка НАХОДИЛАСЬ, — тест зеленел, ничего не
        # проверив, и мутация «None/None считать расхождением» его пережила.
        far = [{"date": "2026-08-01",
                "rates": {"a_anchor": 50.0 / 100.0, "d_far": 0.001 / 100.0}}]
        ci = rtp.verify_coverage_independence(produce, live, far, QUANTUM)
        self.assertEqual(ci["verdict"], "independent", ci)
        self.assertEqual(ci["flips_identical"], 1)
        self.assertEqual(ci["flips_diverged"], [])


class SilenceIsNotAnAnswer(unittest.TestCase):
    """Молчание журнала о паре НЕ есть «пара не ничья»."""

    def test_a_census_pair_never_co_observed_is_unmeasured_not_never_a_tie(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = measure(d, make_producer(CAPS))
        row = pair_row(doc, "c_rival/d_far")
        self.assertEqual(row["class"], "never_co_observed")
        self.assertEqual(row["days_observed"], 0)
        self.assertNotEqual(row["class"], "never_a_tie")
        self.assertTrue(any("c_rival/d_far" in f and f.startswith("[НЕ ИЗМЕРЕНО]")
                            and "НЕ следует" in f for f in doc["findings"]),
                        doc["findings"])

    def test_the_unobserved_pair_is_counted_in_the_headline(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = measure(d, make_producer(CAPS))
        self.assertGreater(doc["counts_by_class"]["never_co_observed"], 0)
        self.assertIn("не наблюдал НИ РАЗУ", doc["findings"][0])

    def test_a_pair_measured_on_no_day_is_not_called_never_a_tie(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на fail-OPEN классификации.

        Обе ставки встретились в журнале по ОДНОМУ разу ⇒ собственного хода нет
        ни у одной, ярлык не применяется НИ В ОДИН день. При подсчёте «ничьих
        ноль» такая пара попала бы в `never_a_tie` — неизмеренное, выданное за
        измеренный отрицательный ответ.
        """
        days = [("2026-08-01", {"a_anchor": 8.0, "p_once": 6.0, "q_once": 5.9})]
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, days,
                           compared=ALL_KEYS + ["p_once", "q_once"])
            doc = measure(d, make_producer(dict(CAPS, p_once=0.2, q_once=0.2)))
        row = pair_row(doc, "p_once/q_once")
        self.assertEqual(row["days_observed"], 1)
        self.assertEqual(row["days_measured"], 0)
        self.assertEqual(row["class"], "co_observed_but_unmeasured")
        self.assertNotEqual(row["class"], "never_a_tie")
        self.assertTrue(any(f.startswith("[НЕ ИЗМЕРЕНО] p_once/q_once")
                            and "НЕ следует" in f for f in doc["findings"]),
                        doc["findings"])

    def test_a_pair_with_no_rate_history_is_move_unmeasured(self):
        """Нет собственного хода ни у одной из ставок ⇒ третий исход."""
        v, n, m = rtp.tie_verdict(0.5, {}, "x", "y")
        self.assertEqual(v, rtp.VERDICT_MOVE_UNMEASURED)
        self.assertEqual((n, m), (0, 0))

    def test_no_flip_in_range_is_its_own_outcome(self):
        v, _n, _m = rtp.tie_verdict(None, {"x": [1.0, 2.0]}, "x", "y")
        self.assertEqual(v, rtp.VERDICT_NO_FLIP)


class IdentityIsASeparatePredicate(unittest.TestCase):
    """Ловушка заказа #535 остаётся в силе и на этом приборе."""

    def test_identity_and_tie_stay_separate_predicates(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS,
                           collisions=[["b_holder", "c_rival"]])
            doc = measure(d, make_producer(CAPS))
        row = pair_row(doc, "b_holder/c_rival")
        self.assertEqual(row["pool_identity"], rtc.IDENTITY_SAME)
        # ключи НЕ слиты: пара осталась парой, серии посчитаны
        self.assertEqual(row["days_observed"], 5)
        line = next(f for f in doc["findings"]
                    if f.startswith("[CRITICAL] b_holder/c_rival:"))
        self.assertIn("ОДИН пул", line)

    def test_the_headline_says_a_permanent_tie_of_one_pool_explains_itself(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS,
                           collisions=[["b_holder", "c_rival"]])
            doc = measure(d, make_producer(CAPS))
        self.assertIn("тождеством, а не рынком", doc["findings"][0])

    def test_two_different_instruments_are_labelled_differently(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS,
                           collisions=[])
            doc = measure(d, make_producer(CAPS))
        row = pair_row(doc, "b_holder/c_rival")
        self.assertEqual(row["pool_identity"], rtc.IDENTITY_DIFFERENT)
        self.assertNotIn("тождеством, а не рынком", doc["findings"][0])

    def test_an_uncompared_key_is_identity_unmeasured_not_different(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS,
                           compared=["a_anchor", "b_holder"], collisions=[])
            doc = measure(d, make_producer(CAPS))
        self.assertEqual(pair_row(doc, "c_rival/d_far")["pool_identity"],
                         rtc.IDENTITY_UNMEASURED)

    def test_names_are_not_merged_by_pool_identity_only_annotated(self):
        """Журнал зовёт пул одним именем, снимок — другим.

        Срастив имена молча, прибор подменил бы «эта пара наблюдалась» на
        «наблюдалась похожая». Пара обязана остаться ненаблюдавшейся, а
        совпадение по адресу — быть НАЗВАНО отдельной строкой.
        """
        days = [(d, dict(r, d_far_alias=2.0)) for d, r in DAYS]
        with TemporaryDirectory() as tmp:
            write_snapshot(Path(tmp), LIVE_RATES, days,
                           compared=ALL_KEYS + ["d_far_alias"],
                           collisions=[["d_far", "d_far_alias"]])
            doc = measure(tmp, make_producer(CAPS))
        row = pair_row(doc, "c_rival/d_far")
        self.assertEqual(row["class"], "never_co_observed")
        line = next(f for f in doc["findings"] if "c_rival/d_far" in f)
        self.assertIn("d_far_alias", line)
        self.assertIn("НЕ срощены", line)


class TheDayAxisMustDoSomething(unittest.TestCase):
    """Прибор, повторивший один день N раз, обязан сказать это вслух."""

    def test_the_day_axis_control_passes_when_verdicts_vary(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = measure(d, make_producer(CAPS))
        dac = doc["day_axis_control"]
        self.assertEqual(dac["verdict"], "live")
        self.assertGreater(dac["pairs_varying"], 0)

    def test_an_inert_day_axis_is_declared_not_passed_off_as_a_regime(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: те же ставки каждый день."""
        same = {"a_anchor": 8.0, "b_holder": 4.0, "c_rival": 4.0}
        days = [(f"2026-08-{i:02d}", dict(same)) for i in range(1, 6)]
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, days, compared=ALL_KEYS)
            doc = measure(d, make_producer(CAPS))
        self.assertEqual(doc["day_axis_control"]["verdict"], "INERT")
        self.assertTrue(any("ось дней ИНЕРТНА" in f for f in doc["findings"]),
                        doc["findings"])


class WhatIsDeliberatelyNotMeasured(unittest.TestCase):
    """Покрытие журнала — не книга дня, и прибор об этом не молчит."""

    def _doc(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            return measure(d, make_producer(CAPS))

    def test_no_per_day_capital_is_reported_anywhere(self):
        """Ход капитала по дню из журнала не восстанавливается — и не пишется."""
        doc = self._doc()
        blob = json.dumps(doc, ensure_ascii=False)
        self.assertNotIn("capital_moved_usd", blob)
        for row in doc["pairs"]:
            for day in row["days"]:
                self.assertEqual(sorted(day), ["date", "verdict"])

    def test_the_limit_is_declared_in_the_artifact_and_in_the_report(self):
        doc = self._doc()
        self.assertEqual(len(doc["not_measured_by_design"]), 2)
        text = "\n".join(rtp.format_report(doc))
        self.assertIn("[НЕ МЕРИТСЯ ПО ПОСТРОЕНИЮ]", text)
        self.assertIn("СОСЕДСТВО", text)

    def test_journal_coverage_is_measured_against_the_live_universe(self):
        cov = self._doc()["journal_coverage"]
        self.assertEqual(cov["per_day_min"], 3)
        self.assertEqual(cov["per_day_max"], 4)
        self.assertEqual(cov["live_ranked"], 4)
        self.assertEqual(cov["ranked_live_not_in_journal"], ["d_far"])


class TheYardstickIsMeasuredNotDerived(unittest.TestCase):
    """Аналитическая формула занижает стоимость перестановки."""

    def test_exact_ties_are_excluded_from_the_understatement_number(self):
        """У точной ничьи доля 100 % при любом кванте — это деление на единицу
        измерения, а не свойство формулы."""
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = measure(d, make_producer(CAPS))
        av = doc["analytic_vs_measured"]
        self.assertGreaterEqual(av["exact_ties_excluded"], 1)
        self.assertNotEqual(av["max_understatement_frac"], 1.0)

    def test_an_unmeasured_quantum_refuses_the_census(self):
        """Возмущение ниже кванта отвечает «ничего не двигается» на любой
        вопрос, и это молчание неотличимо от чистого прогона."""
        flat = make_producer(CAPS, quantum=0.0)

        def deaf(provider):
            target, breakdown, cap = flat(provider)
            return target, {k: {"score": 1.0, "risk_multiplier": MULT}
                            for k in breakdown}, cap

        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = measure(d, deaf)
        self.assertIsNone(doc["quantum_pp"])
        self.assertEqual(doc["status"], rtp.STATUS_UNMEASURED)
        self.assertTrue(any("квант" in f for f in doc["findings"]))


class RunsAreCountedCorrectly(unittest.TestCase):
    """Арифметика серий — отдельно от всего остального."""

    def test_a_gap_in_observation_breaks_the_calendar_run(self):
        days = [("2026-08-01", rtp.VERDICT_TIE),
                ("2026-08-02", rtp.VERDICT_TIE),
                ("2026-08-20", rtp.VERDICT_TIE),
                ("2026-08-21", rtp.VERDICT_TIE)]
        run, lo, hi = rtp.longest_run_calendar(days)
        self.assertEqual((run, lo, hi), (2, "2026-08-01", "2026-08-02"))
        self.assertEqual(rtp.longest_run_observed([v for _d, v in days]), 4)

    def test_a_holding_day_breaks_both_runs(self):
        days = [("2026-08-01", rtp.VERDICT_TIE),
                ("2026-08-02", rtp.VERDICT_HOLDS),
                ("2026-08-03", rtp.VERDICT_TIE)]
        self.assertEqual(rtp.longest_run_calendar(days)[0], 1)
        self.assertEqual(rtp.longest_run_observed([v for _d, v in days]), 1)

    def test_an_unparsable_date_never_extends_a_run(self):
        days = [("2026-08-01", rtp.VERDICT_TIE),
                ("не дата", rtp.VERDICT_TIE),
                ("2026-08-02", rtp.VERDICT_TIE)]
        self.assertEqual(rtp.longest_run_calendar(days)[0], 1)


class RefusalsAreLoud(unittest.TestCase):
    """Отказ — третий исход с названной причиной, а не тихий ноль."""

    def test_an_unreadable_snapshot_refuses(self):
        with TemporaryDirectory() as d:
            doc = measure(d, make_producer(CAPS))
        self.assertEqual(doc["status"], rtp.STATUS_UNMEASURED)
        self.assertTrue(any("adapter_status.json" in f for f in doc["findings"]))

    def test_an_empty_journal_refuses(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, [], compared=ALL_KEYS)
            doc = measure(d, make_producer(CAPS))
        self.assertEqual(doc["status"], rtp.STATUS_UNMEASURED)
        self.assertTrue(any("журнал решений" in f for f in doc["findings"]))

    def test_a_producer_that_raises_refuses_instead_of_exploding(self):
        def broken(_provider):
            raise RuntimeError("производитель упал")

        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = measure(d, broken)
        self.assertEqual(doc["status"], rtp.STATUS_UNMEASURED)
        self.assertTrue(any("производитель цели не отработал" in f
                            for f in doc["findings"]))

    def test_a_missing_identity_artifact_is_unmeasured_not_different_pool(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=None)
            doc = measure(d, make_producer(CAPS))
        self.assertTrue(any("тождества пула нечитаем" in f
                            for f in doc["findings"]))
        self.assertEqual(pair_row(doc, "b_holder/c_rival")["pool_identity"],
                         rtc.IDENTITY_UNMEASURED)

    def test_counts_keep_unchecked_separate_from_zero(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            doc = rtp.run(root=d, now=NOW, write=False,
                          producer_factory=lambda _s: make_producer(CAPS))
        # run() читает <root>/data — его тут нет, значит отказ, и он СЧИТАЕТСЯ
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)
        self.assertEqual(doc["overall"], doc["status"])


class Hermeticity(unittest.TestCase):
    """Живое ``data/`` не читается и не пишется — и на СЛОМАННОМ субъекте тоже."""

    def test_the_producer_gets_a_sandbox_that_is_not_the_data_dir(self):
        seen = []

        def factory(sandbox):
            seen.append(sandbox)
            return make_producer(CAPS)

        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            rtp.measure(Path(d), now=NOW, producer_factory=factory)
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(Path(seen[0]).resolve(), Path(d).resolve())

    def test_measure_writes_nothing_into_the_directory_it_reads(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            before = sorted(p.name for p in Path(d).iterdir())
            measure(d, make_producer(CAPS))
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), before)

    def test_it_writes_nothing_even_when_the_subject_is_broken(self):
        """Герметичность, занятая у исправного субъекта, не держит.

        Спрашивать надо «герметичен ли он, если код СЛОМАН?» — именно под
        мутацией прибор и уходит писать не туда.
        """
        def broken(_provider):
            raise RuntimeError("производитель упал")

        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            before = sorted(p.name for p in Path(d).iterdir())
            measure(d, broken)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), before)

    def test_the_sandbox_is_removed_afterwards(self):
        seen = []

        def factory(sandbox):
            seen.append(Path(sandbox))
            return make_producer(CAPS)

        with TemporaryDirectory() as d:
            write_snapshot(Path(d), LIVE_RATES, DAYS, compared=ALL_KEYS)
            rtp.measure(Path(d), now=NOW, producer_factory=factory)
        self.assertFalse(seen[0].exists())


class Wiring(unittest.TestCase):
    """Прибор без потребителя — измеритель, не доехавший до реестра."""

    ROOT = Path(__file__).resolve().parents[2]

    def test_findings_bridge_runs_the_census(self):
        src = (self.ROOT / "spa_core/monitoring/findings_bridge.py").read_text(
            encoding="utf-8")
        self.assertIn("from spa_core.monitoring import ranking_tie_persistence", src)
        self.assertIn("ranking_tie_persistence.run(root=args.root)", src)

    def test_the_census_stage_declares_it(self):
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("ranking_tie_persistence", fb.CENSUS_STAGE)

    def test_office_step_reads_the_artifact_and_prints_the_report(self):
        # Проверяется СЛОВАРЬ шага 0-офис, а не наличие подстроки: переименовать
        # ключ схемы чтения и оставить его же в карте производителей — ровно тот
        # дефект, который текстовая проверка НЕ ловит.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_office_for_rtp_test", self.ROOT / "scripts/consume_office_reports.py")
        office = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(office)
        self.assertIn("ranking_tie_persistence.json", office._READ_SCHEMA)
        self.assertIn("ranking_tie_persistence.json", office._PRODUCER)
        self.assertIn("status",
                      office._READ_SCHEMA["ranking_tie_persistence.json"])
        self.assertIn("coverage_independence",
                      office._READ_SCHEMA["ranking_tie_persistence.json"])
        src = (self.ROOT / "scripts/consume_office_reports.py").read_text(
            encoding="utf-8")
        self.assertIn(
            "from spa_core.monitoring.ranking_tie_persistence import format_report",
            src)

    def test_artifact_has_both_manifest_homes(self):
        manifest = json.loads((self.ROOT / "architecture/manifest.json").read_text(
            encoding="utf-8"))
        rel = "data/ranking_tie_persistence.json"
        self.assertTrue(any(a.get("path") == rel for a in manifest["artifacts"]),
                        "нет записи в artifacts[]")
        producer = next(a for a in manifest["artifacts"]
                        if a.get("path") == rel)["producer"]
        agent = next(a for a in manifest["agents"] if a.get("label") == producer)
        self.assertTrue(any(p.get("artifact") == rel for p in agent["produces"]),
                        "нет записи в produces[] паспорта производителя")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
