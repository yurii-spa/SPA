"""Приёмка прибора сшивки осей по времени (заказ #556, ADR-319).

Каждый тест отвечает на вопрос «при каких данных этот вердикт был бы ДРУГИМ?» —
требование, поставленное уроком ADR-319. Тесты, истинные по построению, здесь
запрещены: у каждого утверждения есть положительный контроль.

# FROZEN-DATE-OK: injected-clock — `measure(..., now=)` принимает часы
# параметром, и ВСЕ отметки фикстур задаются относительно него же внутри
# `_carrier()`/`_trail()`; ни одна ветка прибора не спрашивает стенных часов.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import run_axis_time_stitch as m

#: Якорь фикстур. Сам по себе он ничего не решает: прибор получает его через
#: `now=`, а все отметки носителей строятся от него арифметикой.
ANCHOR = datetime(2026, 9, 10, 6, 0, 0, tzinfo=timezone.utc)


def _ts(offset_s: float) -> str:
    return (ANCHOR + timedelta(seconds=offset_s)).isoformat()


def _write_carrier(data_dir: Path, runs) -> None:
    """runs: список (observed_at_offset, snapshot_offset, legs)."""
    lines = []
    for obs, snap, legs in runs:
        for i in range(legs):
            lines.append(json.dumps({
                "observed_at": _ts(obs),
                "snapshot": _ts(snap),
                "kind": "hint_winner",
                "adapter": f"proto_{i}",
                "apy": 2.5 + i,
            }))
    (data_dir / m.RATE_CARRIER_FILENAME).write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _write_trail(data_dir: Path, offsets) -> None:
    lines = []
    for j, off in enumerate(offsets):
        day = (ANCHOR + timedelta(seconds=off)).date().isoformat()
        lines.append(json.dumps({
            "event_id": f"e{j}",
            "correlation_id": f"c{j}",
            "snapshot_id": f"{day}:hash{j}",
            "event_type": "cycle_start",
            "timestamp": _ts(off),
            "data": {"cycle_date": day},
            "prev_event_id": None,
        }))
    (data_dir / m.TRAIL_FILENAME).write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


class RunAxisTimeStitchTest(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _measure(self, **kw):
        return m.measure(self.data, now=ANCHOR, **kw)

    # ───────────── слой 1: какое поле есть ось ─────────────
    def test_axis_is_chosen_by_measurement_not_by_declaration_order(self):
        """Ось выбирает ЗАМЕР. Контроль: переставь близость — сменится выбор.

        Это и есть промах заказа: он назвал ось числом, а число принадлежало
        другому полю записи.
        """
        # snapshot близко к трейлу, observed_at — далеко
        _write_carrier(self.data, [(20000, 3, 5)])
        _write_trail(self.data, [0])
        doc = self._measure()
        self.assertEqual(
            doc["axis_candidates"]["axis_chosen_by_measurement"],
            m.AXIS_SNAPSHOT)

        # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: поменяли местами — выбор обязан перевернуться
        _write_carrier(self.data, [(3, 20000, 5)])
        doc2 = self._measure()
        self.assertEqual(
            doc2["axis_candidates"]["axis_chosen_by_measurement"],
            m.AXIS_WRITE_TIME)

    def test_axis_disagreement_within_one_record_is_measured(self):
        """Расхождение осей ВНУТРИ одной записи — улика, и она считается."""
        _write_carrier(self.data, [(3600, 5, 5)])
        _write_trail(self.data, [0])
        doc = self._measure()
        spread = doc["axis_candidates"]["axes_disagree_within_one_record_s"]
        self.assertAlmostEqual(spread["min"], 3595.0, places=1)
        self.assertEqual(spread["runs"], 1)

    # ───────────── слой 3: население и неоднозначность ─────────────
    def test_two_nearby_trail_runs_make_the_match_ambiguous(self):
        """Два чужих прогона в окне ⇒ `ambiguous`, а не «нашли пару»."""
        _write_carrier(self.data, [(10, 10, 5)])
        _write_trail(self.data, [8, 12])
        doc = self._measure()
        fwd = doc["forward_direction"]
        self.assertEqual(fwd[m.MATCH_AMBIGUOUS], 1)
        self.assertEqual(fwd[m.MATCH_UNAMBIGUOUS], 0)

    def test_ambiguous_share_is_none_not_zero_when_no_pairs(self):
        """Доля от НУЛЯ пар — `None`. Ноль читался бы как успех правила."""
        t = m._tally([ANCHOR], [], 10)
        self.assertIsNone(t["ambiguous_share"])
        # контроль: при наличии пар доля — число
        t2 = m._tally([ANCHOR], [ANCHOR], 10)
        self.assertEqual(t2["ambiguous_share"], 0.0)

    def test_reverse_direction_is_measured_too(self):
        """Заказ требовал ОБЕ стороны: 443 против 11 — вопрос о покрытии."""
        _write_carrier(self.data, [(5, 5, 5)])
        _write_trail(self.data, [0, 86400, 172800])
        doc = self._measure()
        rev = doc["reverse_direction"]
        self.assertEqual(rev[m.MATCH_UNAMBIGUOUS], 1)
        self.assertEqual(rev[m.MATCH_UNMATCHED], 2)

    def test_zero_unambiguous_pairs_is_the_third_outcome(self):
        """Ноль однозначных ⇒ UNMEASURED, а не «сшивка невозможна»."""
        # все прогоны носителя неоднозначны: у каждого по два соседа вплотную
        _write_carrier(self.data, [(10, 10, 5)])
        _write_trail(self.data, [10, 10])
        doc = self._measure()
        self.assertEqual(doc["status"], m.STATUS_UNMEASURED)
        self.assertTrue(any("[НЕ ИЗМЕРЕНО]" in f for f in doc["findings"]))

    # ───────────── слой 4: своя цена ошибки ─────────────
    def test_derived_window_must_not_drop_the_run_it_came_from(self):
        """Окно, выведенное из населения, обязано ВМЕСТИТЬ всё население.

        Положительный контроль ровно на тот дефект, который прибор показал в
        первом же прогоне: округлённое вниз окно потеряло прогон, из которого
        само и выведено (10 однозначных из 11).
        """
        # расстояние с дробной частью, которая при round(.,3) уедет ВНИЗ
        _write_carrier(self.data, [(30000, 7.0450794, 5),
                                   (30000, 2.1880001, 5)])
        _write_trail(self.data, [0, 86400])
        doc = self._measure()
        self.assertEqual(doc["forward_direction"][m.MATCH_UNMATCHED], 0,
                         "выведенное окно потеряло свой же прогон")
        self.assertEqual(doc["forward_direction"][m.MATCH_UNAMBIGUOUS], 2)

    def test_band_and_margin_are_measured_from_the_population(self):
        """Полоса [самое далёкое верное, самое близкое неверное) и её запас."""
        # верные расстояния 2 и 6; второй сосед не ближе 20.
        # observed_at уведён на часы — как на живом носителе, иначе ось
        # выбиралась бы по нему и замер отвечал бы не на тот вопрос.
        _write_carrier(self.data, [(30000, 2, 5), (30000, 86400 + 6, 5)])
        _write_trail(self.data, [0, 20, 86400, 86400 + 26])
        doc = self._measure()
        err = doc["error_rate"]
        # прогон лежит на +2, поэтому сосед на +20 удалён на 18, а не на 20;
        # у второго прогона (+86406) второй сосед ровно в 20 — берётся минимум.
        self.assertAlmostEqual(err["widest_true_gap_s"], 6.0, places=1)
        self.assertAlmostEqual(err["narrowest_wrong_gap_s"], 18.0, places=1)
        self.assertAlmostEqual(err["margin_ratio"], 18.0 / 6.0, places=2)

    def test_out_of_sample_is_reported_as_zero_not_omitted(self):
        """Правило не проверялось вне выборки — это число, а не молчание."""
        _write_carrier(self.data, [(0, 3, 5)])
        _write_trail(self.data, [0])
        doc = self._measure()
        self.assertEqual(doc["error_rate"]["out_of_sample_runs"], 0)
        self.assertEqual(doc["error_rate"]["in_sample_runs"], 1)
        self.assertIn("does_not_report", doc)

    def test_signed_gap_direction_is_measured_not_assumed(self):
        """Снимок ПОСЛЕ старта прогона — замер, а не предположение."""
        _write_carrier(self.data, [(30000, 5, 5)])
        _write_trail(self.data, [0])
        self.assertTrue(self._measure()["error_rate"]["all_after_run_start"])
        # контроль: снимок ПЕРЕД стартом ⇒ признак обязан перевернуться
        _write_carrier(self.data, [(30000, -5, 5)])
        self.assertFalse(self._measure()["error_rate"]["all_after_run_start"])

    # ───────────── слой 2: порядок печати есть утверждение ─────────────
    def test_caveat_is_printed_before_the_share(self):
        """Заказ требовал: оговорку сказать ПРЕЖДЕ, чем называть долю."""
        _write_carrier(self.data, [(0, 3, 5)])
        _write_trail(self.data, [0])
        lines = m.format_report(self._measure())
        caveat = min(i for i, l in enumerate(lines) if "НЕ СНИМАЕТ" in l)
        share = min(i for i, l in enumerate(lines) if "доля" in l)
        self.assertLess(caveat, share,
                        "доля названа прежде оговорки — читается как ответ на "
                        "вопрос о втором входе, которым она не является")

    def test_caveat_finding_exists_and_precedes_the_population_finding(self):
        """Порядок закреплён и на уровне НАХОДОК, не только строк отчёта.

        Батарея цикла #559 нашла зазор: утверждение ADR-320 о порядке было
        закреплено только для `format_report` — находку `[ОГОВОРКА ДО ДОЛИ]`
        можно было убрать из `doc["findings"]` целиком, и ни один тест не
        краснел. Находки читает офис и мост, то есть другой потребитель с тем
        же правом на порядок. Положительный контроль — сама та мутация.
        """
        _write_carrier(self.data, [(0, 3, 5)])
        _write_trail(self.data, [0])
        findings = self._measure()["findings"]
        caveat = [i for i, f in enumerate(findings)
                  if f.startswith("[ОГОВОРКА ДО ДОЛИ]")]
        population = [i for i, f in enumerate(findings)
                      if f.startswith("[НАСЕЛЕНИЕ]")]
        self.assertEqual(len(caveat), 1,
                         "находка-оговорка пропала из findings: офис и мост "
                         "прочтут долю, не прочитав оговорки")
        self.assertEqual(len(population), 1)
        self.assertLess(caveat[0], population[0],
                        "в findings доля названа прежде оговорки — тот же "
                        "дефект, что и в отчёте, только у другого потребителя")

    def test_caveat_names_the_shortage_of_observations(self):
        """Третий запрет — нехватка НАБЛЮДЕНИЙ — добавлен этим замером."""
        _write_carrier(self.data, [(0, 3, 5)])
        _write_trail(self.data, [0])
        doc = self._measure()
        joined = " ".join(doc["what_the_stitch_cannot_remove"])
        self.assertIn("НАБЛЮДЕНИЙ", joined)

    # ───────────── слой 5: перенос на знаменатель ─────────────
    def test_transfer_counts_only_days_with_two_observations(self):
        """Сшивка покупает только дни, где носитель И в знаменателе, И дважды."""
        day0 = ANCHOR.date().isoformat()
        runs = [{"observed_at": _ts(0), "snapshot": _ts(0)},
                {"observed_at": _ts(60), "snapshot": _ts(60)}]
        tr = m._transfer(runs, {day0})
        self.assertEqual(tr["denominator_days_adjudicable_after_stitch"],
                         [day0])
        # контроль: ОДНО наблюдение на том же дне ⇒ день не покупается
        tr2 = m._transfer(runs[:1], {day0})
        self.assertEqual(tr2["denominator_days_adjudicable_after_stitch"], [])
        self.assertEqual(tr2["denominator_days_still_unadjudicable"], 1)

    def test_transfer_unmeasured_when_denominator_is_none(self):
        """Знаменатель не получен ⇒ «не измерено», НЕ пустое множество."""
        tr = m._transfer([{"observed_at": _ts(0), "snapshot": _ts(0)}], None)
        self.assertFalse(tr["measured"])
        self.assertIn("shadow_trigger_eval", tr["reason"])
        # контроль: пустое множество — ДРУГОЙ исход, он измерен
        tr2 = m._transfer([{"observed_at": _ts(0), "snapshot": _ts(0)}], set())
        self.assertTrue(tr2["measured"])

    def test_multi_run_days_outside_the_denominator_buy_nothing(self):
        """Два наблюдения на дне ВНЕ знаменателя знаменателю не помогают.

        Это и есть живой вердикт: дни с двумя снимками в знаменатель не входят.
        """
        other = (ANCHOR + timedelta(days=5)).date().isoformat()
        runs = [{"observed_at": _ts(0), "snapshot": _ts(0)},
                {"observed_at": _ts(60), "snapshot": _ts(60)}]
        tr = m._transfer(runs, {other})
        self.assertEqual(tr["denominator_days_adjudicable_after_stitch"], [])
        self.assertEqual(tr["denominator_days_touched"], [])
        self.assertEqual(tr["denominator_days_still_unadjudicable"], 1)

    # ───────────── третий исход на входах ─────────────
    def test_missing_carrier_is_unmeasured_with_a_named_reason(self):
        _write_trail(self.data, [0])
        doc = self._measure()
        self.assertEqual(doc["status"], m.STATUS_UNMEASURED)
        self.assertTrue(doc["reason"])

    def test_missing_trail_is_unmeasured_with_a_named_reason(self):
        _write_carrier(self.data, [(0, 3, 5)])
        doc = self._measure()
        self.assertEqual(doc["status"], m.STATUS_UNMEASURED)
        self.assertTrue(doc["reason"])

    def test_broken_lines_do_not_sink_the_measurement(self):
        """Битая строка называется, но не рушит замер."""
        _write_trail(self.data, [0])
        (self.data / m.RATE_CARRIER_FILENAME).write_text(
            "{not json\n" + json.dumps(
                {"observed_at": _ts(0), "snapshot": _ts(3)}) + "\n",
            encoding="utf-8")
        doc = self._measure()
        self.assertEqual(doc["rate_carrier_runs"], 1)

    def test_unparsable_timestamps_are_counted_not_guessed(self):
        _write_trail(self.data, [0])
        (self.data / m.RATE_CARRIER_FILENAME).write_text(
            json.dumps({"observed_at": "не дата", "snapshot": _ts(3)}) + "\n",
            encoding="utf-8")
        doc = self._measure()
        self.assertEqual(
            doc["axis_candidates"][m.AXIS_WRITE_TIME]["unparsed"], 1)

    # ───────────── гигиена ─────────────
    def test_run_writes_exactly_one_file_its_own(self):
        """Проверяется СОСТАВОМ каталога, а не отсутствием исключения."""
        root = self.data / "root"
        (root / "data").mkdir(parents=True)
        _write_carrier(root / "data", [(0, 3, 5)])
        _write_trail(root / "data", [0])
        before = set(p.name for p in (root / "data").iterdir())
        m.run(root=str(root), now=ANCHOR)
        after = set(p.name for p in (root / "data").iterdir())
        self.assertEqual(after - before, {m.OUTPUT_FILENAME})

    def test_run_counts_unchecked_separately_from_zeros(self):
        root = self.data / "root2"
        (root / "data").mkdir(parents=True)
        doc = m.run(root=str(root), now=ANCHOR, write=False)
        self.assertEqual(doc["overall"], m.STATUS_UNMEASURED)
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)

    def test_instrument_is_not_in_the_journal_reader_census(self):
        """Решение ADR-317, закреплённое В ОБЕ СТОРОНЫ.

        Прибор ключа ставки в журнале решений не касается, поэтому внесение его
        в `READERS` дало бы `insensitive`, истинный ПО ПОСТРОЕНИЮ.
        """
        from spa_core.monitoring import decision_journal_coverage as djc
        names = " ".join(str(r) for r in getattr(djc, "READERS", []))
        self.assertNotIn("run_axis_time_stitch", names)
        # вторая сторона: прибор действительно не читает журнал решений
        src = Path(m.__file__).read_text(encoding="utf-8")
        self.assertNotIn("allocation_rationale_history", src)

    def test_the_office_dispatches_to_this_instrument(self):
        """Отчёт доходит до читателя шага 0-офис, а не только существует.

        Проверяется ВЫЗОВОМ: тест проводки, не делающий вызова, переживает
        любое расплетение (координата, пережившая батарею цикла #554).
        """
        import importlib.util
        root = Path(m.__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "_cor_probe", root / "scripts" / "consume_office_reports.py")
        cor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cor)

        # Схема объявлена — иначе офис доложит «СХЕМА РАЗОШЛАСЬ» вместо отчёта
        self.assertIn("run_axis_time_stitch.json", cor._READ_SCHEMA)

        doc = {
            "status": m.STATUS_WARNING,
            "axis_candidates": {"measured": True,
                                "axis_chosen_by_measurement": m.AXIS_SNAPSHOT},
            "what_the_stitch_cannot_remove": ["нехватку НАБЛЮДЕНИЙ"],
            "forward_direction": {"window_s": 7.045, "unambiguous": 11,
                                  "ambiguous": 0, "ambiguous_share": 0.0,
                                  "unmatched": 0, "paired": 11},
            "reverse_direction": {"window_s": 7.045, "unambiguous": 11,
                                  "ambiguous": 0, "ambiguous_share": 0.0,
                                  "unmatched": 432, "paired": 11},
            "error_rate": {"measured": True, "widest_true_gap_s": 7.045,
                           "narrowest_wrong_gap_s": 17.231,
                           "margin_ratio": 2.446, "out_of_sample_runs": 0,
                           "in_sample_runs": 11},
            "transfer_to_denominator": {
                "measured": True, "denominator_days": 15,
                "denominator_days_adjudicable_after_stitch": []},
            "findings": ["[ОТВЕТ] переносит НОЛЬ дней"],
            "does_not_report": "верно ли правило вне этого снимка",
        }
        out = "\n".join(
            cor._summarize_json("data/run_axis_time_stitch.json", doc))
        # Три РАЗНЫХ слоя отчёта. Проверять один — пережить расплетение прочих.
        self.assertIn(m.AXIS_SNAPSHOT, out)
        self.assertIn("НЕ СНИМАЕТ", out)
        self.assertIn("запас", out)
        self.assertNotIn("СХЕМА РАЗОШЛАСЬ", out)

    def test_the_bridge_census_knows_this_instrument(self):
        """Три ОТДЕЛЬНЫХ объявления моста знают прибор — три отдельных иска.

        Прежняя редакция (цикл #559) спрашивала одним `assertIn` путь артефакта
        у объединения `CENSUS_PRODUCT + PRODUCES`, и половина вопроса была
        мертва ПО ПОСТРОЕНИЮ: ключи `CENSUS_PRODUCT` — это ИМЕНА переписей, и
        путь-артефакт не совпадёт ни с одним (замер цикла #560: ключей,
        похожих на путь, 0 из 44). Иск удовлетворялся одним лишь `PRODUCES`,
        то есть проверял координату B1, а именем обещал B2/B3 — контроль,
        истинный по построению, есть украшение. Сами B2/B3 закреплены не здесь,
        а в `test_artifact_absence_shared_verdict.py` и
        `test_office_absent_artifact_producer_aware.py` (замер #560: обе
        мутации краснеют на населении, включающем эти файлы). Этот тест не
        дублирует их, а говорит о СВОЁМ приборе — и теперь способен упасть на
        каждом из трёх объявлений порознь.
        """
        from spa_core.monitoring import findings_bridge as fb
        self.assertIn("run_axis_time_stitch", fb.CENSUS_STAGE,
                      "имени прибора нет в ступени переписей моста")
        self.assertIn("run_axis_time_stitch", fb.CENSUS_PRODUCT,
                      "прибор не объявлен в CENSUS_PRODUCT — читатель, идущий "
                      "по манифесту, подставит ЧУЖОГО бегуна")
        self.assertEqual(
            fb.CENSUS_PRODUCT["run_axis_time_stitch"]["artifact"],
            "data/run_axis_time_stitch.json")
        self.assertIn("data/run_axis_time_stitch.json", fb.PRODUCES,
                      "артефакт не объявлен продуктом — он «без дома»")

    def test_census_product_keys_are_names_not_artifact_paths(self):
        """Положительный контроль на само украшение (замер #560).

        Иск «путь артефакта лежит среди ключей `CENSUS_PRODUCT`» не может быть
        истинным ни при каком состоянии кода. Если завтра ключи станут путями,
        этот тест покраснеет и потребует перечитать соседа выше, а не молча
        воскресит мёртвую половину вопроса.
        """
        from spa_core.monitoring import findings_bridge as fb
        pathlike = [k for k in fb.CENSUS_PRODUCT if "/" in k or k.endswith(".json")]
        self.assertEqual(pathlike, [],
                         "ключи CENSUS_PRODUCT — имена переписей, не пути")

    def test_llm_is_forbidden_in_this_module(self):
        src = Path(m.__file__).read_text(encoding="utf-8")
        self.assertIn("LLM_FORBIDDEN", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
