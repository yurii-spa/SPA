"""Сторож переписи ничьих ранжирования (``ranking_tie_census``), заказ #535.

Каждая сцена — вопрос, на который прибор обязан отвечать ИЗМЕРЕНИЕМ, а не
формой отчёта. Ключевые из них воспроизводят настоящие ошибки этого же цикла:

* ``test_quantum_below_the_producers_step_is_refused_not_counted`` — первая
  редакция прибора возмущала на 1e-6 pp, ниже кванта аллокатора (1e-4 pp), и
  получала «ничего не двигается» у ВСЕХ пар, включая ту, что ADR-279 уже назвал.
  Отказ считать перепись обязан быть ГРОМКИМ, а не тихим нулём.
* ``test_letter_of_the_order_and_the_working_yardstick_are_named_apart`` —
  признак «разрыв уложился в маржу» отбирает пары БЕЗ денег; отчёт, назвавший
  один ярлык, отвечает верно не на тот вопрос.
* ``test_pair_that_moves_money_only_together_with_a_neighbour_is_not_isolable``
  — сдвиг одной ставки пересекает всех, кто стои́т между; деньги неизолированной
  перестановке НЕ приписываются.
* ``test_control_failure_voids_the_attribution`` — деньги, которые двигает сам
  сдвиг ставки, а не смена порядка, паре не принадлежат.
* ``test_identity_and_tie_are_measured_apart`` — ловушка заказа: тождество пула
  (ADR-227) и ничья ранжирования это РАЗНЫЕ предметы.

Тесты герметичны: живой ``data/`` не читается и не пишется, производитель цели
инъектируется. Оба свойства проверяются отдельными сценами — герметичность,
занятая у исправного субъекта, перестаёт держать, как только субъект сломан.

FROZEN-DATE-OK: injected-clock — единственная дата в файле подаётся в
``measure(..., now=)`` параметром; отметки истории строятся от неё же.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import ranking_tie_census as rtc

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
CAPITAL = 100_000.0
QUANTUM = 0.0001
MULT = 0.85


# ──────────────────────────────────────────────────────────────────────────
# стенд: жадный рюкзак с потолками, повторяющий ФОРМУ настоящего производителя
# ──────────────────────────────────────────────────────────────────────────
def make_producer(caps, *, budget=0.5, capital=CAPITAL, quantum=QUANTUM,
                  mult=MULT, tie_break_reversed=False):
    """{ставки в долях} → (цель $, разбор со счётом, капитал).

    Форма — та же, что у ``optimized_yield_breakdown``: победитель получает
    ПОЛНЫЙ потолок, величина победы в размер порции не входит. Ставка
    квантуется ровно так же, как её округляет аллокатор.
    """
    def produce(provider):
        scores = {}
        for key, val in provider.items():
            pp = float(val) * 100.0
            if quantum:
                pp = round(pp / quantum) * quantum
            scores[key] = pp * mult
        order = sorted(scores, key=lambda k: (-scores[k],
                                              (k[::-1] if tie_break_reversed else k)))
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


def write_snapshot(data_dir: Path, rates_pp: dict, *,
                   history: dict | None = None,
                   compared: list | None = None,
                   collisions: list | None = None) -> None:
    """Снимок наблюдений + журнал решений + артефакт тождества пула."""
    (data_dir / "adapter_status.json").write_text(json.dumps(
        {"adapters": {k: {"live_apy": v} for k, v in rates_pp.items()}}),
        encoding="utf-8")
    rows = []
    if history:
        days = max(len(v) for v in history.values())
        for i in range(days):
            rows.append({"cycle_date": f"2026-08-{i + 1:02d}",
                         "apy_evidenced_pct": {k: v[i] for k, v in history.items()
                                               if i < len(v)}})
    (data_dir / "allocation_rationale_history.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if compared is not None:
        (data_dir / rtc.IDENTITY_ARTIFACT).write_text(json.dumps(
            {"keys_compared": compared,
             "collisions": [{"keys": list(k)} for k in (collisions or [])]}),
            encoding="utf-8")


def measure(data_dir, producer, **kw):
    return rtc.measure(Path(data_dir), now=NOW,
                       producer_factory=lambda _sandbox: producer, **kw)


def row_for(doc, above, below):
    for r in doc["adjacent_pairs"]:
        if r["above"] == above and r["below"] == below:
            return r
    raise AssertionError(f"пары {above}/{below} нет в переписи: "
                         f"{[(r['above'], r['below']) for r in doc['adjacent_pairs']]}")


# сцены снимка ────────────────────────────────────────────────────────────
#: A забирает 0.4, B — оставшиеся 0.1 из бюджета 0.5, C не входит вовсе.
#: Ставки B и C совпадают ДО ЗНАКА: порядок решает тай-брейк, деньги — $10 000.
EXACT_TIE_CAPS = {"a_anchor": 0.4, "b_holder": 0.2, "c_rival": 0.2}
EXACT_TIE_RATES = {"a_anchor": 8.0, "b_holder": 4.0, "c_rival": 4.0}
#: собственный ход ставки B и C заведомо больше кванта — «шум решает».
NOISY_HISTORY = {"b_holder": [4.0, 4.9, 4.1, 5.0], "c_rival": [4.0, 4.8, 4.2, 5.1]}


class AKeyWithoutAScoreIsNotRankedAtZero(unittest.TestCase):
    """ADR-344 (инвариант #17): счёта нет — значит порядок не определён.

    `ranked_order` читал `breakdown[p].get("score") or 0.0` и ставил ключ без
    счёта в конец так, будто счёт ИЗМЕРЕН и равен нулю; соседняя пара с ним
    давала разрыв величиной в счёт соседа, а «точная ничья» двух таких ключей
    была бы объявлена по двум подставленным нулям.
    """

    BD = {"a": {"score": 2.0, "risk_multiplier": 1.0},
          "b": {"score": 1.0, "risk_multiplier": 1.0},
          "c": {"risk_multiplier": 1.0}}

    def test_an_unscored_key_is_left_out_of_the_order_and_named(self):
        self.assertEqual(rtc.ranked_order(self.BD, ["a", "b", "c"]), ["a", "b"])
        self.assertEqual(rtc.unscored_keys(self.BD, ["a", "b", "c"]), ["c"])

    def test_a_recorded_zero_score_is_ranked(self):
        bd = dict(self.BD, c={"score": 0.0, "risk_multiplier": 1.0})
        self.assertEqual(rtc.ranked_order(bd, ["a", "b", "c"]), ["a", "b", "c"])
        self.assertEqual(rtc.unscored_keys(bd, ["a", "b", "c"]), [])

    def test_two_unscored_keys_are_not_an_exact_tie(self):
        bd = {"a": {"risk_multiplier": 1.0}, "b": {"risk_multiplier": 1.0}}
        out = rtc.verify_tie_break(bd, {"a": 10.0, "b": 0.0}, ["a", "b"])
        self.assertEqual(out.get("verdict"), "unmeasured", out)

    def test_two_recorded_equal_scores_still_are_a_tie(self):
        bd = {"a": {"score": 1.0, "risk_multiplier": 1.0},
              "b": {"score": 1.0, "risk_multiplier": 1.0}}
        out = rtc.verify_tie_break(bd, {"a": 10.0, "b": 0.0}, ["a", "b"])
        self.assertNotEqual(out.get("verdict"), "unmeasured", out)


class ExactTieCarryingCapital(unittest.TestCase):
    """Ничья, на которой стоят деньги, обязана быть НАЗВАНА и посчитана."""

    def _measure(self, **kw):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            return measure(d, make_producer(EXACT_TIE_CAPS), **kw)

    def test_the_pair_is_found_and_the_money_measured(self):
        doc = self._measure()
        row = row_for(doc, "b_holder", "c_rival")
        self.assertEqual(row["verdict"], "noise_decided", doc["findings"])
        self.assertAlmostEqual(row["capital_moved_usd"], 10_000.0, places=2)
        self.assertEqual(doc["status"], rtc.STATUS_CRITICAL)

    def test_the_flip_costs_exactly_one_quantum(self):
        doc = self._measure()
        self.assertEqual(doc["quantum_pp"], QUANTUM)
        self.assertAlmostEqual(row_for(doc, "b_holder", "c_rival")["flip_pp"],
                               QUANTUM, places=8)

    def test_the_negative_control_moves_nothing(self):
        """Ход денег принадлежит смене ПОРЯДКА, а не сдвигу ставки."""
        row = row_for(self._measure(), "b_holder", "c_rival")
        self.assertEqual(row["control_moved_usd"], 0.0)

    def test_the_flip_is_isolated_exactly_one_pair_changed_order(self):
        row = row_for(self._measure(), "b_holder", "c_rival")
        self.assertTrue(row["isolated"])
        self.assertEqual([sorted(p) for p in row["changed_pairs"]],
                         [["b_holder", "c_rival"]])

    def test_headline_capital_counts_only_noise_decided_pairs(self):
        doc = self._measure()
        self.assertAlmostEqual(doc["capital_moved_by_tie_flips_usd"],
                               10_000.0, places=2)
        self.assertEqual(doc["by_yardstick"]["own_daily_move"]["pairs"], 1)

    def test_alphabetical_tie_break_is_measured_not_assumed(self):
        doc = self._measure()
        self.assertEqual(doc["tie_break"]["verdict"], "alphabetical_confirmed")
        self.assertEqual(doc["tie_break"]["scenes"][0]["funded"], "b_holder")

    def test_a_reversed_tie_break_is_caught_and_the_census_refuses(self):
        """Положительный контроль на сам замер тай-брейка."""
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            doc = measure(d, make_producer(EXACT_TIE_CAPS,
                                           tie_break_reversed=True))
        self.assertEqual(doc["tie_break"]["verdict"], "DIVERGED")
        self.assertEqual(doc["adjacent_pairs"], [])
        self.assertTrue(any("тай-брейк" in f for f in doc["findings"]))


class LetterOfTheOrderVersusTheWorkingYardstick(unittest.TestCase):
    """Буква заказа и ярлык, который на вопрос отвечает, — РАЗНЫЕ признаки."""

    def test_letter_of_the_order_and_the_working_yardstick_are_named_apart(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            doc = measure(d, make_producer(EXACT_TIE_CAPS))
        ys = doc["by_yardstick"]
        self.assertIn("within_margin", ys)
        self.assertIn("own_daily_move", ys)
        # признак заказа не приписал себе денежную пару…
        self.assertEqual(ys["within_margin"]["pairs_with_capital"], 0)
        # …а рабочий ярлык её нашёл
        self.assertEqual(ys["own_daily_move"]["pairs"], 1)

    def test_a_pair_that_moves_money_is_never_within_the_margin(self):
        """Структурная причина: маржа — НАИМЕНЬШИЙ денежный сдвиг."""
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            doc = measure(d, make_producer(EXACT_TIE_CAPS))
        moved = [r for r in doc["adjacent_pairs"]
                 if (r["capital_moved_usd"] or 0.0) >= 0.01 * CAPITAL]
        self.assertTrue(moved, "сцена обязана содержать денежную пару")
        for r in moved:
            self.assertFalse(r["within_margin"], r)

    #: a и b налиты по потолок — их перестановка не двигает НИЧЕГО, а разрыв
    #: между ними (0.1 pp) много меньше маржи b (уронить b ниже c — 3.9 pp).
    #: Ровно та пара, которую БУКВА заказа отбирает, а денег на ней нет.
    _WITHIN_CAPS = {"a_top": 0.25, "b_next": 0.25, "c_far": 0.25}
    _WITHIN_RATES = {"a_top": 5.0, "b_next": 4.9, "c_far": 1.0}

    def _within_margin_scene(self):
        hist = {k: [v, v + 0.0001] for k, v in self._WITHIN_RATES.items()}
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), self._WITHIN_RATES, history=hist,
                           compared=list(self._WITHIN_RATES), collisions=[])
            return measure(d, make_producer(self._WITHIN_CAPS))

    def test_the_letter_of_the_order_is_counted_not_silently_dropped(self):
        """Признак заказа обязан быть ПОСЧИТАН — иначе «ноль пар» неотличимо
        от «признак не считался», и ветка закрывается молчанием."""
        doc = self._within_margin_scene()
        selected = [r for r in doc["adjacent_pairs"] if r["within_margin"]]
        self.assertGreaterEqual(len(selected), 1,
                                "сцена обязана содержать пару «в пределах маржи»")
        self.assertEqual(doc["by_yardstick"]["within_margin"]["pairs"],
                         len(selected))

    def test_the_pair_the_letter_selects_carries_no_money(self):
        doc = self._within_margin_scene()
        row = row_for(doc, "a_top", "b_next")
        self.assertTrue(row["within_margin"], row)
        self.assertLess(row["capital_moved_usd"], 0.01 * CAPITAL)
        self.assertEqual(doc["by_yardstick"]["within_margin"]["pairs_with_capital"],
                         0)

    def test_report_prints_both_yardsticks(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            doc = measure(d, make_producer(EXACT_TIE_CAPS))
        text = "\n".join(rtc.format_report(doc))
        self.assertIn("ЯРЛЫК ЗАКАЗА", text)
        self.assertIn("ЯРЛЫК ADR-279", text)


class ZeroPairsIsAnAnswer(unittest.TestCase):
    """«Ноль пар» закрывает ветку заказа — но только когда он ИЗМЕРЕН."""

    def test_well_separated_universe_reports_ok_and_zero(self):
        caps = {"a_anchor": 0.4, "b_holder": 0.2, "c_rival": 0.2}
        rates = {"a_anchor": 9.0, "b_holder": 6.0, "c_rival": 1.0}
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), rates,
                           history={"b_holder": [6.0, 6.001],
                                    "c_rival": [1.0, 1.001]},
                           compared=list(rates), collisions=[])
            doc = measure(d, make_producer(caps))
        self.assertEqual(doc["status"], rtc.STATUS_OK, doc["findings"])
        self.assertEqual(doc["by_yardstick"]["own_daily_move"]["pairs"], 0)
        self.assertEqual(doc["capital_moved_by_tie_flips_usd"], 0.0)
        self.assertTrue(any(f.startswith("[OK]") for f in doc["findings"]))

    def test_a_gap_wider_than_the_rates_own_move_is_not_a_tie(self):
        """Деньги двигаются, но разрыв ставка сама не проходит ⇒ не ничья."""
        rates = {"a_anchor": 8.0, "b_holder": 4.0, "c_rival": 3.0}
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), rates,
                           history={"b_holder": [4.0, 4.0001],
                                    "c_rival": [3.0, 3.0001]},
                           compared=list(rates), collisions=[])
            doc = measure(d, make_producer(EXACT_TIE_CAPS))
        row = row_for(doc, "b_holder", "c_rival")
        self.assertGreaterEqual(row["capital_moved_usd"], 0.01 * CAPITAL)
        self.assertEqual(row["verdict"], "gap_holds")
        self.assertEqual(doc["by_yardstick"]["own_daily_move"]["pairs"], 0)


class ThirdOutcomes(unittest.TestCase):
    """«Не измерено» — самостоятельный исход, а не ноль и не скип."""

    def test_quantum_below_the_producers_step_is_refused_not_counted(self):
        """Настоящая ошибка первой редакции прибора этого же цикла."""
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            blind = make_producer(EXACT_TIE_CAPS, quantum=10.0)
            doc = measure(d, blind)
        self.assertEqual(doc["status"], rtc.STATUS_UNMEASURED)
        self.assertEqual(doc["adjacent_pairs"], [])
        self.assertTrue(any("квант" in f and "НЕ ИЗМЕРЕНО" in f
                            for f in doc["findings"]), doc["findings"])

    def test_capital_without_observed_rate_history_is_unmeasured_not_a_tie(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=None,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            doc = measure(d, make_producer(EXACT_TIE_CAPS))
        row = row_for(doc, "b_holder", "c_rival")
        self.assertEqual(row["verdict"], "capital_but_move_unmeasured")
        self.assertEqual(doc["by_yardstick"]["own_daily_move"]["pairs"], 0)
        self.assertIn("b_holder/c_rival", doc["unmeasured"])
        self.assertEqual(doc["status"], rtc.STATUS_WARNING)

    def test_missing_identity_artifact_is_named_not_read_as_different_pools(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY)
            doc = measure(d, make_producer(EXACT_TIE_CAPS))
        self.assertEqual(row_for(doc, "b_holder", "c_rival")["pool_identity"],
                         rtc.IDENTITY_UNMEASURED)
        self.assertTrue(any("тождеств" in f and "НЕ ИЗМЕРЕНО" in f
                            for f in doc["findings"]), doc["findings"])

    def test_key_absent_from_keys_compared_is_unmeasured_not_different(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=["a_anchor", "b_holder"], collisions=[])
            doc = measure(d, make_producer(EXACT_TIE_CAPS))
        self.assertEqual(row_for(doc, "b_holder", "c_rival")["pool_identity"],
                         rtc.IDENTITY_UNMEASURED)

    def test_unreadable_snapshot_refuses_loudly(self):
        with TemporaryDirectory() as d:
            (Path(d) / "adapter_status.json").write_text("{не json", encoding="utf-8")
            doc = measure(d, make_producer(EXACT_TIE_CAPS))
        self.assertEqual(doc["status"], rtc.STATUS_UNMEASURED)
        self.assertTrue(doc["findings"])

    def test_counts_report_unchecked_separately_from_zero(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=None,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            doc = rtc.run(root=d, now=NOW, write=False,
                          producer_factory=lambda _s: make_producer(EXACT_TIE_CAPS))
        # run() читает <root>/data — его тут нет, и это тоже третий исход
        self.assertIn("unchecked", doc["counts"])
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)


class IsolationAndControl(unittest.TestCase):
    """Деньги принадлежат паре, только если перестановка ЕЙ и принадлежит."""

    #: c_rival держит остаток бюджета, d_twin совпадает с ним ставкой ДО ЗНАКА.
    #: Подъём e_outsider пересекает обоих ОДНИМ движением — деньги переезжают,
    #: но одной паре они не принадлежат.
    _WELDED_CAPS = {"a_anchor": 0.2, "b_holder": 0.2, "c_rival": 0.2,
                    "d_twin": 0.2, "e_outsider": 0.2}
    _WELDED_RATES = {"a_anchor": 8.0, "b_holder": 5.0, "c_rival": 4.0,
                     "d_twin": 4.0, "e_outsider": 3.9}

    def _welded_cluster(self):
        hist = {k: [v, v + 1.0] for k, v in self._WELDED_RATES.items()}
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), self._WELDED_RATES, history=hist,
                           compared=list(self._WELDED_RATES), collisions=[])
            return measure(d, make_producer(self._WELDED_CAPS))

    def test_pair_that_moves_money_only_together_with_a_neighbour_is_not_isolable(self):
        doc = self._welded_cluster()
        row = row_for(doc, "d_twin", "e_outsider")
        self.assertFalse(row["isolated"])
        self.assertGreaterEqual(len(row["changed_pairs"]), 2)
        self.assertEqual(row["verdict"], "not_isolable")
        self.assertTrue(any("НЕ изолирована" in f for f in doc["findings"]))

    def test_not_isolable_money_is_named_but_not_added_to_the_headline(self):
        doc = self._welded_cluster()
        row = row_for(doc, "d_twin", "e_outsider")
        self.assertGreaterEqual(row["capital_moved_usd"], 0.01 * CAPITAL)
        names = {f"{r['above']}/{r['below']}" for r in doc["adjacent_pairs"]
                 if r["verdict"] == "noise_decided"}
        self.assertNotIn("d_twin/e_outsider", names)

    def test_control_failure_voids_the_attribution(self):
        """Деньги двигает сам сдвиг ставки — паре они не принадлежат."""
        caps = {"a_anchor": 0.4, "b_holder": 0.2, "c_rival": 0.2}

        honest = make_producer(caps)

        def leaky(provider):
            target, breakdown, cap = honest(provider)
            # любой сдвиг c_rival вверх переливает деньги ДО перестановки
            bumped = round(float(provider["c_rival"]) * 100.0 / QUANTUM) * QUANTUM
            if bumped > 3.0 + 1e-9:
                target = dict(target)
                target["a_anchor"] = target.get("a_anchor", 0.0) - 20_000.0
                target["b_holder"] = target.get("b_holder", 0.0) + 20_000.0
            return target, breakdown, cap

        rates = {"a_anchor": 8.0, "b_holder": 4.0, "c_rival": 3.0}
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), rates, history={k: [v, v + 1.0]
                                                    for k, v in rates.items()},
                           compared=list(rates), collisions=[])
            doc = measure(d, leaky)
        row = row_for(doc, "b_holder", "c_rival")
        self.assertGreaterEqual(row["control_moved_usd"], 0.01 * CAPITAL)
        self.assertEqual(row["verdict"], "control_failed")
        self.assertTrue(any("контроль" in f and "НЕ ИЗМЕРЕНО" in f
                            for f in doc["findings"]), doc["findings"])


class IdentityIsOrthogonalToTheTie(unittest.TestCase):
    """Ловушка заказа #535: ADR-227 и ничья — РАЗНЫЕ предметы."""

    def _doc(self, collisions, compared=None):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=compared or list(EXACT_TIE_RATES),
                           collisions=collisions)
            return measure(d, make_producer(EXACT_TIE_CAPS))

    def test_identity_and_tie_are_measured_apart(self):
        same = self._doc([("b_holder", "c_rival")])
        diff = self._doc([])
        self.assertEqual(row_for(same, "b_holder", "c_rival")["pool_identity"],
                         rtc.IDENTITY_SAME)
        self.assertEqual(row_for(diff, "b_holder", "c_rival")["pool_identity"],
                         rtc.IDENTITY_DIFFERENT)
        # вердикт ничьи от тождества НЕ зависит — иначе один признак подменял бы другой
        self.assertEqual(row_for(same, "b_holder", "c_rival")["verdict"],
                         row_for(diff, "b_holder", "c_rival")["verdict"])

    def test_all_four_cells_of_the_census_exist(self):
        doc = self._doc([("b_holder", "c_rival"), ("a_anchor", "b_holder")])
        cells = doc["identity_census"]
        self.assertEqual(cells["tie_and_same_pool"], ["b_holder/c_rival"])
        self.assertEqual(cells["same_pool_only"], ["a_anchor/b_holder"])
        for key in ("tie_only", "neither", "identity_unmeasured"):
            self.assertIn(key, cells)

    def test_a_collision_that_is_not_a_tie_lands_in_its_own_cell(self):
        doc = self._doc([("a_anchor", "b_holder")])
        self.assertIn("a_anchor/b_holder", doc["identity_census"]["same_pool_only"])
        self.assertNotIn("a_anchor/b_holder",
                         doc["identity_census"]["tie_and_same_pool"])


class Hermeticity(unittest.TestCase):
    """Замер не открывает живое ``data/`` — и когда субъект СЛОМАН, тоже."""

    def test_measure_writes_nothing_into_the_data_dir(self):
        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            before = {p.name: p.read_bytes() for p in Path(d).iterdir()}
            measure(d, make_producer(EXACT_TIE_CAPS))
            after = {p.name: p.read_bytes() for p in Path(d).iterdir()}
        self.assertEqual(before, after)

    def test_a_producer_that_raises_leaves_the_data_dir_untouched(self):
        def broken(_provider):
            raise RuntimeError("производитель сломан")

        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            before = sorted(p.name for p in Path(d).iterdir())
            doc = measure(d, broken)
            after = sorted(p.name for p in Path(d).iterdir())
        self.assertEqual(before, after)
        self.assertEqual(doc["status"], rtc.STATUS_UNMEASURED)

    def test_default_producer_is_only_built_when_not_injected(self):
        """Инъекция обязана доходить до ПРОВОДКИ, а не только быть параметром."""
        seen = []

        def factory(sandbox):
            seen.append(sandbox)
            return make_producer(EXACT_TIE_CAPS)

        with TemporaryDirectory() as d:
            write_snapshot(Path(d), EXACT_TIE_RATES, history=NOISY_HISTORY,
                           compared=list(EXACT_TIE_RATES), collisions=[])
            rtc.measure(Path(d), now=NOW, producer_factory=factory)
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(Path(seen[0]).resolve(), Path(d).resolve())


class Wiring(unittest.TestCase):
    """Прибор без потребителя — измеритель, не доехавший до реестра."""

    ROOT = Path(__file__).resolve().parents[2]

    def test_findings_bridge_runs_the_census(self):
        src = (self.ROOT / "spa_core/monitoring/findings_bridge.py").read_text(
            encoding="utf-8")
        self.assertIn("from spa_core.monitoring import ranking_tie_census", src)
        self.assertIn("ranking_tie_census.run(root=args.root)", src)

    def test_office_step_reads_the_artifact_and_prints_the_report(self):
        # Проверяется СЛОВАРЬ шага 0-офис, а не наличие подстроки в файле:
        # переименовать ключ схемы чтения и оставить его же в карте
        # производителей — ровно тот дефект, который текстовая проверка НЕ
        # ловит (мутация «офис не знает артефакта» пережила первую редакцию).
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_office_for_test", self.ROOT / "scripts/consume_office_reports.py")
        office = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(office)
        self.assertIn("ranking_tie_census.json", office._READ_SCHEMA)
        self.assertIn("ranking_tie_census.json", office._PRODUCER)
        self.assertIn("status", office._READ_SCHEMA["ranking_tie_census.json"])
        src = (self.ROOT / "scripts/consume_office_reports.py").read_text(
            encoding="utf-8")
        self.assertIn("from spa_core.monitoring.ranking_tie_census import format_report",
                      src)

    def test_artifact_has_both_manifest_homes(self):
        manifest = json.loads((self.ROOT / "architecture/manifest.json").read_text(
            encoding="utf-8"))
        rel = "data/ranking_tie_census.json"
        self.assertTrue(any(a.get("path") == rel for a in manifest["artifacts"]),
                        "нет записи в artifacts[]")
        producer = next(a for a in manifest["artifacts"]
                        if a.get("path") == rel)["producer"]
        agent = next(a for a in manifest["agents"] if a.get("label") == producer)
        self.assertTrue(any(p.get("artifact") == rel for p in agent["produces"]),
                        "нет записи в produces[] паспорта производителя")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
