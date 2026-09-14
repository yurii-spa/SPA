"""Приёмка прибора «интервал значения критерия» (заказ #600/G14, ADR-382).

Каждый отказ проверяется ПОЛОЖИТЕЛЬНЫМ контролем — стендом, на котором он обязан
сработать, и соседним стендом, на котором он обязан молчать. Контроль, никогда не
видевший поломки, — украшение (`.claude/rules/deployment.md`).

Время в стендах ИНЪЕКТИРУЕТСЯ: прибор принимает ``now``, и якорь проверяется по
``generated_at`` — урок цикла #599, где инъекция часов до этого поля не доезжала и
мутация поля пережила всю батарею.
"""
# FROZEN-DATE-OK: injected-clock — даты стенда СИНТЕТИЧЕСКИЕ (2026-01-xx), календарём
# не судятся ни разу: прибор получает `now=` параметром, а свежесть не мерит вовсе.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import criterion_value_interval as cvi
from spa_core.paper_trading import shadow_trigger_eval as _ste

FIXED_NOW = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)

A, C, M = "aave_v3", "compound_v3", "maple"
HORIZON = 2
#: Стоимость хода в стенде мала НАМЕРЕННО: при равных ставках ног выгода хода ровно
#: нулевая, net = -cost < 0, и тогда HOLD даёт `hit`, а ACT — `miss`. Так исход дня
#: задаётся ОДНИМ полем `verdict`, и стенду не нужно подбирать ставки под вердикт.
COST_USD = 5.0


def _record(date: str, *, verdict: str, moves: str, evidenced: dict) -> dict:
    """Одна строка журнала решений. Ход всегда существенный: $40 000 оборота."""
    other = C if moves == "AC" else M
    return {
        "schema": "shadow-hist-v1",
        "cycle_date": date,
        "verdict": verdict,
        "capital_usd": 100000.0,
        "cost_usd": COST_USD,
        "turnover_usd": 40000.0,
        "current_positions": {A: 10000.0, other: 40000.0},
        "target_positions": {A: 50000.0},
        "apy_evidenced_pct": dict(evidenced),
        "apy_unevidenced": [],
        "reasons": [],
    }


def _write_stand(root: Path, days: list, series: dict) -> Path:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / _ste.HISTORY_FILENAME).write_text(
        "\n".join(json.dumps(r) for r in days) + "\n", encoding="utf-8")
    (data / cvi.SERIES_FILENAME).write_text(
        json.dumps({"series": series}), encoding="utf-8")
    return data


def _ladder(*, today: int, material_days: list, extra_rungs: bool = True) -> dict:
    """Выдача соседа ADR-381 в той форме, в какой прибор её читает."""
    rungs = [{"rung": cvi.RUNG_OUR_CODE,
              "denominator": today + len(material_days),
              "share_pct": round(100.0 * today / (today + len(material_days)), 2)}]
    if extra_rungs:
        rungs.insert(0, {"rung": "ceiling", "denominator": today + len(material_days) + 4})
    return {
        "status": cvi.STATUS_OK,
        "ladder": rungs,
        "population": {"denominator_today": today,
                       "days_recoverable_by_our_code_with_material": list(material_days)},
    }


# ── стенд №1: один день поднимается материалом, один остаётся неразрешённым ───
def stand_interval(root: Path):
    """5 базовых дней (все ``hit``) · 01-03 поднимается материалом · 01-05 — нет.

    01-03 отвергнут ногой ``compound_v3``, и в ряду её точки ЕСТЬ ⇒ материал
    разрешает день настоящей ставкой. 01-05 отвергнут ногой ``maple``, точек в ряду
    у неё нет НИ ОДНОЙ ⇒ день остаётся неразрешённым и входит в обе границы.
    """
    full = {A: 3.0, C: 3.0}
    days = [
        _record("2026-01-01", verdict="HOLD", moves="AC", evidenced=full),
        _record("2026-01-02", verdict="HOLD", moves="AC", evidenced=full),
        _record("2026-01-03", verdict="HOLD", moves="AC", evidenced=full),
        _record("2026-01-04", verdict="HOLD", moves="AC", evidenced={A: 3.0}),
        _record("2026-01-05", verdict="HOLD", moves="AM", evidenced={A: 3.0}),
        _record("2026-01-06", verdict="HOLD", moves="AC", evidenced=full),
        _record("2026-01-07", verdict="HOLD", moves="AC", evidenced=full),
        _record("2026-01-08", verdict="HOLD", moves="AC", evidenced=full),
    ]
    series = {
        # Пересечение с журналом — материал для контроля ШКАЛЫ: без общих пар
        # отношение брать неоткуда, и прибор обязан отказать.
        A: [[d, 3.0] for d in (f"2026-01-0{i}" for i in range(1, 9))],
        # Точки ровно тех дней, которых журналу не хватило, — и ТОЛЬКО их.
        C: [["2026-01-04", 3.0], ["2026-01-05", 3.0]],
    }
    return _write_stand(root, days, series)


# ── стенд №2: границы расходятся ПО РАЗНЫЕ стороны порога взвода ──────────────
def stand_straddle(root: Path):
    """8 базовых дней (5 ``hit`` + 3 ``miss``) · 2 поднимаются материалом · 3 нет.

    Исход базового дня задаётся ОДНИМ полем: при нулевой выгоде хода HOLD — ``hit``,
    ACT — ``miss``. Знаменатель 13, нижняя граница 6/13 = 0.4615 (порог 0.6 НЕ
    пройден), верхняя 9/13 = 0.6923 (пройден) — то есть починка способна перевернуть
    взвод, и прибор обязан назвать это CRITICAL.

    Промахи в базе обязательны: стенд из одних попаданий доказывал бы только сложение
    единиц, и ошибка в отборе числителя прошла бы мимо.
    """
    full = {A: 3.0, C: 3.0}
    onlyA = {A: 3.0}
    days = [
        _record("2026-01-01", verdict="HOLD", moves="AC", evidenced=full),   # hit
        _record("2026-01-02", verdict="HOLD", moves="AC", evidenced=full),   # hit
        _record("2026-01-03", verdict="HOLD", moves="AC", evidenced=full),   # hit
        _record("2026-01-04", verdict="HOLD", moves="AC", evidenced=full),   # hit
        _record("2026-01-05", verdict="HOLD", moves="AC", evidenced=full),   # hit
        _record("2026-01-06", verdict="ACT", moves="AC", evidenced=full),    # miss
        # провал эвиденса по `compound_v3` — четыре дня теряют вердикт
        _record("2026-01-07", verdict="HOLD", moves="AC", evidenced=onlyA),
        _record("2026-01-08", verdict="HOLD", moves="AC", evidenced=onlyA),
        _record("2026-01-09", verdict="HOLD", moves="AC", evidenced=onlyA),
        _record("2026-01-10", verdict="HOLD", moves="AC", evidenced=onlyA),
        _record("2026-01-11", verdict="ACT", moves="AC", evidenced=onlyA),   # miss
        _record("2026-01-12", verdict="ACT", moves="AC", evidenced=onlyA),   # miss
        _record("2026-01-13", verdict="ACT", moves="AC", evidenced=full),    # miss
        _record("2026-01-14", verdict="HOLD", moves="AC", evidenced=full),
    ]
    series = {
        A: [[f"2026-01-{i:02d}", 3.0] for i in range(1, 15)],
        # Точка РОВНО одна, и стои́т она так, что поднимает ДВА дня из пяти:
        # 01-06 и 01-07 (у обоих 01-08 попадает в форвардное окно), а 01-08..01-10
        # не поднимает ни одного — им нужны точки 01-09..01-12, которых в ряду нет.
        C: [["2026-01-08", 3.0]],
    }
    return _write_stand(root, days, series)


STRADDLE_LADDER = dict(today=8, material_days=["2026-01-06", "2026-01-07",
                                               "2026-01-08", "2026-01-09",
                                               "2026-01-10"])


class StandShapeTest(unittest.TestCase):
    """Стенд обязан иметь ту форму, ради которой написан — иначе тесты ниже пусты."""

    def test_interval_stand_has_one_liftable_and_one_unresolvable_day(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5, material_days=[
                                  "2026-01-03", "2026-01-05"]))
            self.assertEqual(doc["status"], cvi.STATUS_OK, doc.get("unmeasured_reason"))
            self.assertEqual(doc["answer"]["days_resolved_by_material"], ["2026-01-03"])
            self.assertEqual(doc["answer"]["days_unresolved"], ["2026-01-05"])


class IntervalAnswerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.data = stand_interval(Path(self.tmp.name))
        self.ladder = _ladder(today=5, material_days=["2026-01-03", "2026-01-05"])
        self.doc = cvi.measure(self.data, now=FIXED_NOW, horizon_days=HORIZON,
                               ladder_doc=self.ladder)

    def tearDown(self):
        self.tmp.cleanup()

    def test_both_bounds_are_measured_and_differ_by_the_unresolved_day(self):
        ans = self.doc["answer"]
        self.assertEqual(ans["denominator"], 7)
        self.assertEqual(ans["numerator_low"], 6)
        self.assertEqual(ans["numerator_high"], 7)
        self.assertEqual(ans["bound_low"], round(6 / 7, cvi.RATE_DIGITS))
        self.assertEqual(ans["bound_high"], 1.0)
        self.assertEqual(ans["interval_width"],
                         round(1.0 - round(6 / 7, cvi.RATE_DIGITS), cvi.RATE_DIGITS))

    def test_unresolved_day_enters_BOTH_sides_and_neither_bound_assumes_its_outcome(self):
        # Нижняя граница обязана быть тем же числом, что и без дня вовсе в числителе,
        # а верхняя — тем же, что и с ним. Ровно это и значит «входит обеими сторонами».
        ans = self.doc["answer"]
        self.assertEqual(ans["numerator_high"] - ans["numerator_low"],
                         len(ans["days_unresolved"]))

    def test_no_number_between_the_bounds_is_printed_anywhere(self):
        """Середина запрещена ЗАКАЗОМ, и запрет держится тестом, а не намерением."""
        ans = self.doc["answer"]
        self.assertIsNone(ans["midpoint"])
        mid = (ans["bound_low"] + ans["bound_high"]) / 2.0
        self.assertNotEqual(ans["bound_low"], mid)  # стенд обязан быть невырожденным
        blob = json.dumps(self.doc, ensure_ascii=False)
        for rounding in (2, 3, 4):
            self.assertNotIn(str(round(mid, rounding)), blob)

    def test_resolved_day_carries_a_real_outcome_and_a_real_verdict(self):
        outcomes = self.doc["answer"]["days_resolved_outcomes"]
        self.assertEqual(outcomes, {"2026-01-03": "hit"})

    def test_every_granted_rate_is_found_back_in_the_series(self):
        self.assertTrue(self.doc["provenance_control"]["passed"])
        self.assertTrue(self.doc["granted_rates"])
        for row in self.doc["granted_rates"]:
            self.assertEqual(row["rate_pct"],
                             {"aave_v3": {}, "compound_v3": {
                                 "2026-01-04": 3.0, "2026-01-05": 3.0}}
                             .get(row["key"], {}).get(row["cycle_date"], row["rate_pct"]))
            self.assertIn(cvi.SERIES_FILENAME, row["source"])

    def test_the_sentinel_of_the_neighbours_is_never_granted(self):
        """Семь предыдущих заказов подставляли ноль; этот не подставляет ничего.

        Проверяется по ИСХОДУ, а не по отсутствию имени в тексте: ключу, у которого
        точки ряда нет, не выдано ни одной ставки ни в одной записи.
        """
        granted_keys = {(r["cycle_date"], r["key"]) for r in self.doc["granted_rates"]}
        self.assertFalse([x for x in granted_keys if x[1] == M],
                         "ноге без единой точки ряда ставка выдана — это сентинел")

    def test_baseline_outcomes_are_not_moved_by_the_material(self):
        self.assertEqual(self.doc["baseline_stability"]["count"], 0)
        self.assertEqual(self.doc["baseline_stability"]["hits_today"],
                         self.doc["baseline_stability"]["hits_under_grant"])

    def test_gate_verdict_is_reported_on_BOTH_bounds(self):
        gate = self.doc["gate"]
        self.assertEqual(gate["min_hit_rate"], _ste.MIN_HIT_RATE)
        self.assertTrue(gate["passes_at_low_bound"])
        self.assertTrue(gate["passes_at_high_bound"])
        self.assertTrue(gate["verdict_insensitive"])

    def test_injected_clock_reaches_generated_at(self):
        self.assertEqual(self.doc["generated_at"], FIXED_NOW.isoformat())

    def test_report_prints_both_bounds_on_ONE_line(self):
        """Разнеси границы по строкам — и читатель унесёт ту, что ближе к началу."""
        lines = cvi.format_report(self.doc)
        bound_lines = [ln for ln in lines
                       if str(self.doc["answer"]["bound_low"]) in ln
                       and str(self.doc["answer"]["bound_high"]) in ln]
        self.assertTrue(bound_lines, lines)
        self.assertIn("[ИНТЕРВАЛ]", "\n".join(lines))


class WideningCapabilityTest(unittest.TestCase):
    """Нулевая ширина законна ТОЛЬКО у прибора, который умеет расходиться."""

    def test_capability_control_widens_when_material_is_withheld(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5, material_days=[
                                  "2026-01-03", "2026-01-05"]))
            cap = doc["widening_capability"]
            self.assertTrue(cap["passed"])
            self.assertEqual(cap["day_starved"], "2026-01-03")
            self.assertEqual(cap["legs_withheld"], [C])
            self.assertGreater(cap["width"], 0.0)

    def test_degenerate_interval_is_a_measured_outcome_not_a_silent_point(self):
        """Материал разрешает ВСЁ ⇒ ширина ноль, и она объявлена строкой."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5,
                                                 material_days=["2026-01-03"]))
            self.assertEqual(doc["status"], cvi.STATUS_OK, doc.get("unmeasured_reason"))
            self.assertEqual(doc["answer"]["interval_width"], 0.0)
            self.assertEqual(doc["answer"]["days_unresolved"], [])
            self.assertTrue([x for x in doc["findings"] if x.startswith("[ШИРИНА]")])
            self.assertTrue(doc["widening_capability"]["passed"])
            self.assertGreater(doc["widening_capability"]["width"], 0.0)

    def test_capability_refuses_when_the_judge_row_names_no_blocking_legs(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = cvi._outcomes

            def blind(records, horizon):
                rows, den = real(records, horizon)
                for row in rows.values():
                    row.pop("unpriced_protocols", None)
                return rows, den

            cvi._outcomes = blind
            try:
                doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                                  ladder_doc=_ladder(today=5, material_days=[
                                      "2026-01-03", "2026-01-05"]))
            finally:
                cvi._outcomes = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("не умеет расходиться", doc["unmeasured_reason"])


class GateStraddleTest(unittest.TestCase):
    """Когда границы лежат ПО РАЗНЫЕ стороны порога — это CRITICAL, а не WARNING."""

    def test_straddling_bounds_are_named_critical(self):
        with TemporaryDirectory() as tmp:
            data = stand_straddle(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(**STRADDLE_LADDER))
            self.assertEqual(doc["status"], cvi.STATUS_CRITICAL,
                             doc.get("unmeasured_reason") or doc["answer"])
            gate = doc["gate"]
            self.assertFalse(gate["passes_at_low_bound"])
            self.assertTrue(gate["passes_at_high_bound"])
            self.assertFalse(gate["verdict_insensitive"])
            self.assertTrue([x for x in doc["findings"] if x.startswith("[CRITICAL]")])

    def test_the_same_stand_has_a_mixed_numerator(self):
        """Без промахов в базе стенд доказывал бы только сложение единиц."""
        with TemporaryDirectory() as tmp:
            data = stand_straddle(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(**STRADDLE_LADDER))
            self.assertEqual(doc["answer"]["numerator_low"], 6)
            self.assertEqual(doc["answer"]["numerator_high"], 9)
            self.assertEqual(doc["answer"]["denominator"], 13)
            self.assertEqual(doc["answer"]["days_resolved_outcomes"],
                             {"2026-01-06": "miss", "2026-01-07": "hit"})
            self.assertEqual(len(doc["answer"]["days_unresolved"]), 3)


class RefusalTest(unittest.TestCase):
    """Каждый отказ — ТРЕТИЙ исход с названной причиной, а не ноль и не скип."""

    def _measure(self, data, **kw):
        kw.setdefault("ladder_doc", _ladder(today=5, material_days=["2026-01-03",
                                                                    "2026-01-05"]))
        return cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON, **kw)

    def test_missing_journal_is_unmeasured_not_an_empty_denominator(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            doc = self._measure(data)
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("журнал решений", doc["unmeasured_reason"])
            self.assertIsNone(doc["answer"])

    def test_missing_series_is_unmeasured_not_absent_material(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            (data / cvi.SERIES_FILENAME).unlink()
            doc = self._measure(data)
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn(cvi.SERIES_FILENAME, doc["unmeasured_reason"])

    def test_series_without_overlap_refuses_instead_of_assuming_the_scale(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            # Ряд есть, но ни одной пары, наблюдённой обоими: ключ журналу неизвестен.
            (data / cvi.SERIES_FILENAME).write_text(
                json.dumps({"series": {"yearn_v3": [["2026-01-04", 3.0]]}}),
                encoding="utf-8")
            doc = self._measure(data)
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("шкала", doc["unmeasured_reason"])
            self.assertFalse(doc["unit_parity"]["measured"])

    def test_series_in_the_other_scale_refuses_and_names_the_ratio(self):
        """Проценты против долей — ×100, и каждый вердикт был бы подделан."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc_raw = json.loads((data / cvi.SERIES_FILENAME).read_text())
            doc_raw["series"] = {k: [[d, v / 100.0] for d, v in rows]
                                 for k, rows in doc_raw["series"].items()}
            (data / cvi.SERIES_FILENAME).write_text(json.dumps(doc_raw),
                                                    encoding="utf-8")
            doc = self._measure(data)
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("РАЗНЫХ шкалах", doc["unmeasured_reason"])
            self.assertTrue(doc["unit_parity"]["measured"])
            self.assertFalse(doc["unit_parity"]["passed"])

    def test_unmeasured_ladder_refuses_instead_of_inventing_a_denominator(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = self._measure(data, ladder_doc={"status": cvi.STATUS_UNMEASURED,
                                                  "unmeasured_reason": "сосед молчит"})
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("сосед молчит", doc["unmeasured_reason"])

    def test_ladder_without_our_rung_refuses(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = self._measure(data, ladder_doc={
                "status": cvi.STATUS_OK,
                "ladder": [{"rung": "ceiling", "denominator": 9}],
                "population": {"denominator_today": 5,
                               "days_recoverable_by_our_code_with_material": []}})
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn(cvi.RUNG_OUR_CODE, doc["unmeasured_reason"])

    def test_ladder_that_does_not_name_its_days_refuses(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = self._measure(data, ladder_doc={
                "status": cvi.STATUS_OK,
                "ladder": [{"rung": cvi.RUNG_OUR_CODE, "denominator": 7}],
                "population": {"denominator_today": 5}})
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("поимённо", doc["unmeasured_reason"])

    def test_rung_that_disagrees_with_its_own_day_list_refuses(self):
        """Ступень сосед считает вычитанием, перечень — разностью множеств."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            bad = _ladder(today=5, material_days=["2026-01-03", "2026-01-05"])
            bad["ladder"][-1]["denominator"] = 9      # 5 + 2 ≠ 9
            doc = self._measure(data, ladder_doc=bad)
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("про разные населения", doc["unmeasured_reason"])

    def test_neighbour_counting_a_different_today_refuses(self):
        """Знаменатель чужой, числитель свой — стоять они обязаны на ОДНОМ населении.

        Согласия ступени с её же перечнем для этого мало: сосед мог мерить другой
        журнал или другой горизонт. Контроль найден положительным замером — стенд с
        расхождением 9 против 8 давал ответ, и ни один контроль не краснел.
        """
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = self._measure(data, ladder_doc=_ladder(
                today=4, material_days=["2026-01-03", "2026-01-05", "2026-01-08"]))
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("РАЗНЫХ населениях", doc["unmeasured_reason"])

    def test_the_same_ladder_with_the_right_today_does_NOT_refuse(self):
        """Обратная сторона того же контроля: верное население проходит."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = self._measure(data)
            self.assertEqual(doc["status"], cvi.STATUS_OK,
                             doc.get("unmeasured_reason"))

    def test_lifting_a_day_the_neighbour_does_not_list_refuses(self):
        """Улика односторонней сверки: реплей поднял ЧУЖОЙ день."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = self._measure(data, ladder_doc=_ladder(
                today=5, material_days=["2026-01-05"]))
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("вне материального перечня", doc["unmeasured_reason"])
            self.assertIn("2026-01-03", doc["unmeasured_reason"])

    def test_lifting_FEWER_days_than_the_rung_is_allowed_and_is_the_interval(self):
        """Обратная сторона: недобор — не отказ, а ИСТОЧНИК интервала."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = self._measure(data)
            self.assertEqual(doc["status"], cvi.STATUS_OK)
            self.assertTrue(doc["ladder_parity"]["passed"])
            self.assertFalse(doc["ladder_parity"]["denominator_agreement"])

    def test_broken_numerator_parity_refuses(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = _ste.evaluate_window

            def liar(*a, **kw):
                out = real(*a, **kw)
                out["hit_rate"] = 0.5
                return out

            _ste.evaluate_window = liar
            try:
                doc = self._measure(data)
            finally:
                _ste.evaluate_window = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("определении числителя", doc["unmeasured_reason"])

    def test_broken_canonical_denominator_refuses(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = _ste.scored_days
            _ste.scored_days = lambda *a, **kw: {"2026-01-01"}
            try:
                doc = self._measure(data)
            finally:
                _ste.scored_days = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("каноническим", doc["unmeasured_reason"])

    def test_unmeasured_canonical_denominator_refuses(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = _ste.scored_days
            _ste.scored_days = lambda *a, **kw: None
            try:
                doc = self._measure(data)
            finally:
                _ste.scored_days = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("hit_rate", doc["unmeasured_reason"])

    def test_a_granted_rate_absent_from_the_series_refuses(self):
        """Положительный контроль провенанса: выдать не-материал и покраснеть."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = cvi.grant_material

            def forger(records, **kw):
                recs, prov = real(records, **kw)
                prov.append({"cycle_date": "2026-01-04", "key": M, "rate_pct": 99.0,
                             "source": "выдумка"})
                return recs, prov

            cvi.grant_material = forger
            try:
                doc = self._measure(data)
            finally:
                cvi.grant_material = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("в ряду не найдено", doc["unmeasured_reason"])

    def test_a_day_lost_from_the_denominator_refuses(self):
        """Положительный контроль монотонности: выдача ставок не смеет ОТНИМАТЬ дни."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = cvi.grant_material

            def saboteur(records, **kw):
                recs, prov = real(records, **kw)
                for date in ("2026-01-02", "2026-01-03"):
                    if date in recs:
                        recs[date]["apy_evidenced_pct"] = {}
                return recs, prov

            cvi.grant_material = saboteur
            try:
                doc = self._measure(data)
            finally:
                cvi.grant_material = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("монотонность", doc["unmeasured_reason"])

    def test_unreadable_polled_set_refuses(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = cvi._remedy._polled_keys
            cvi._remedy._polled_keys = lambda *a, **kw: None
            try:
                doc = self._measure(data)
            finally:
                cvi._remedy._polled_keys = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("POLLED_ADAPTERS", doc["unmeasured_reason"])

    def test_a_raising_ladder_neighbour_is_unmeasured_not_a_crash(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = cvi._cpf.measure

            def boom(*a, **kw):
                raise RuntimeError("сосед упал")

            cvi._cpf.measure = boom
            try:
                doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON)
            finally:
                cvi._cpf.measure = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("сосед упал", doc["unmeasured_reason"])


class UnitParityTest(unittest.TestCase):
    def test_median_not_mean_survives_a_single_outlier(self):
        records = {f"2026-01-{i:02d}": {"apy_evidenced_pct": {A: 3.0}}
                   for i in range(1, 10)}
        points = {A: {f"2026-01-{i:02d}": 3.0 for i in range(1, 10)}}
        points[A]["2026-01-05"] = 300.0          # один выброс ×100
        got = unit = cvi.unit_parity(records, points)
        self.assertTrue(unit["measured"])
        self.assertTrue(got["passed"], got)
        self.assertEqual(got["median_ratio"], 1.0)

    def test_zero_denominator_pairs_do_not_produce_a_division_error(self):
        records = {"2026-01-01": {"apy_evidenced_pct": {A: 0.0}},
                   "2026-01-02": {"apy_evidenced_pct": {A: 4.0}}}
        points = {A: {"2026-01-01": 0.0, "2026-01-02": 4.0}}
        got = cvi.unit_parity(records, points)
        self.assertTrue(got["measured"])
        self.assertEqual(got["compared"], 1)
        self.assertEqual(got["pairs"], 2)


class GrantMaterialTest(unittest.TestCase):
    def test_withholding_a_key_stops_its_grant_entirely(self):
        records = {"2026-01-01": {"cycle_date": "2026-01-01",
                                  "apy_evidenced_pct": {}, "apy_unevidenced": []}}
        points = {A: {"2026-01-01": 3.0}, C: {"2026-01-01": 4.0}}
        _, prov = cvi.grant_material(records, polled={A, C}, twins={}, points=points)
        self.assertEqual({r["key"] for r in prov}, {A, C})
        _, prov2 = cvi.grant_material(records, polled={A, C}, twins={}, points=points,
                                      withhold=[C])
        self.assertEqual({r["key"] for r in prov2}, {A})

    def test_the_writers_own_unevidenced_judgement_is_respected(self):
        """Рычаг писателя в чистом виде: объявленную им неэвиденсной ногу не трогаем."""
        records = {"2026-01-01": {"cycle_date": "2026-01-01", "apy_evidenced_pct": {},
                                  "apy_unevidenced": [C]}}
        points = {A: {"2026-01-01": 3.0}, C: {"2026-01-01": 4.0}}
        _, prov = cvi.grant_material(records, polled={A, C}, twins={}, points=points)
        self.assertEqual({r["key"] for r in prov}, {A})

    def test_an_existing_rate_is_never_overwritten(self):
        records = {"2026-01-01": {"cycle_date": "2026-01-01",
                                  "apy_evidenced_pct": {A: 1.25}, "apy_unevidenced": []}}
        points = {A: {"2026-01-01": 9.0}}
        out, prov = cvi.grant_material(records, polled={A}, twins={}, points=points)
        self.assertEqual(out["2026-01-01"]["apy_evidenced_pct"][A], 1.25)
        self.assertEqual(prov, [])

    def test_the_source_record_is_not_mutated(self):
        original = {"2026-01-01": {"cycle_date": "2026-01-01", "apy_evidenced_pct": {},
                                   "apy_unevidenced": []}}
        cvi.grant_material(original, polled={A}, twins={},
                           points={A: {"2026-01-01": 3.0}})
        self.assertEqual(original["2026-01-01"]["apy_evidenced_pct"], {})


class RunAndMainTest(unittest.TestCase):
    """Путь, которым артефакт РОЖДАЕТСЯ, обязан исполняться тестом — урок #599."""

    def test_run_writes_the_artifact_and_counts_findings(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stand_interval(root)
            doc = cvi.run(root=str(root), now=FIXED_NOW, horizon_days=HORIZON,
                          ladder_doc=_ladder(today=5, material_days=["2026-01-03",
                                                                     "2026-01-05"]))
            written = json.loads((root / "data" / cvi.OUTPUT_FILENAME).read_text())
            self.assertEqual(written["version"], cvi.VERSION)
            self.assertEqual(written["generated_at"], FIXED_NOW.isoformat())
            self.assertEqual(doc["overall"], doc["status"])
            self.assertEqual(doc["counts"]["unchecked"], 0)
            self.assertGreater(doc["counts"]["info"], 0)

    def test_run_counts_a_refusal_as_unchecked_not_as_a_clean_pass(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            doc = cvi.run(root=str(root), now=FIXED_NOW, horizon_days=HORIZON,
                          ladder_doc=_ladder(today=5, material_days=[]))
            self.assertEqual(doc["overall"], cvi.STATUS_UNMEASURED)
            self.assertGreaterEqual(doc["counts"]["unchecked"], 1)
            self.assertEqual(doc["counts"]["critical"], 0)

    def test_main_returns_nonzero_when_the_measurement_refused(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            self.assertEqual(cvi.main(["--data-dir", str(data), "--no-write"]), 1)
            self.assertFalse((data / cvi.OUTPUT_FILENAME).exists())


class ReadOnlyTest(unittest.TestCase):
    """«Прибор только ЧИТАЕТ» — измерение, а не строка в ADVISORY.

    Найдено батареей: мутация ``write=False`` -> ``write=True`` у канонического
    расчёта переживала ВЕСЬ набор, то есть заявление о read-only не проверял никто,
    а на живом `data/` такая правка молча писала бы в прод.
    """

    def _files(self, data):
        return {p.name: p.stat().st_mtime_ns for p in Path(data).iterdir()}

    def test_measure_writes_nothing_into_the_data_dir(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            before = self._files(data)
            cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                        ladder_doc=_ladder(today=5, material_days=["2026-01-03",
                                                                   "2026-01-05"]))
            self.assertEqual(self._files(data), before)

    def test_measure_writes_nothing_even_when_it_refuses(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            before = self._files(data)
            cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                        ladder_doc={"status": cvi.STATUS_UNMEASURED,
                                    "unmeasured_reason": "сосед молчит"})
            self.assertEqual(self._files(data), before)


class RoundingAndZeroDenominatorTest(unittest.TestCase):
    """Округлитель и нулевой знаменатель — ЧИСЛА, и они закрепляются литералом.

    Найдено батареей: тесты выше считали ожидание через ``cvi.RATE_DIGITS``, то есть
    были истинны ПО ПОСТРОЕНИЮ и переживали подмену самого округлителя.
    """

    def test_bounds_are_rounded_to_four_digits_by_literal(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5, material_days=["2026-01-03",
                                                                         "2026-01-05"]))
            self.assertEqual(doc["answer"]["bound_low"], 0.8571)
            self.assertEqual(doc["answer"]["bound_high"], 1.0)
            self.assertEqual(doc["answer"]["interval_width"], 0.1429)

    def test_zero_denominator_is_not_a_zero_rate(self):
        self.assertIsNone(cvi._rate(0, 0))
        self.assertIsNone(cvi._rate(3, 0))
        self.assertIsNone(cvi._rate(0, -1))
        self.assertEqual(cvi._rate(1, 2), 0.5)


class SeriesReaderRefusalTest(unittest.TestCase):
    """Три разных «ряда нет» — три отказа, и ни один не есть «фид молчал»."""

    def _write(self, data, payload):
        (data / cvi.SERIES_FILENAME).write_text(json.dumps(payload), encoding="utf-8")

    def test_document_without_a_series_key_is_unmeasured(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            self._write(data, {"generated_at": "x"})
            self.assertIsNone(cvi.load_series_points(data))

    def test_empty_series_is_unmeasured_not_an_empty_material(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            self._write(data, {"series": {}})
            self.assertIsNone(cvi.load_series_points(data))

    def test_a_readable_series_returns_points_not_dates(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            got = cvi.load_series_points(data)
            self.assertEqual(got[C], {"2026-01-04": 3.0, "2026-01-05": 3.0})

    def test_both_refusals_reach_measure_as_UNMEASURED(self):
        for payload in ({"generated_at": "x"}, {"series": {}}):
            with TemporaryDirectory() as tmp:
                data = stand_interval(Path(tmp))
                self._write(data, payload)
                doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                                  ladder_doc=_ladder(today=5,
                                                     material_days=["2026-01-03"]))
                self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
                self.assertIn(cvi.SERIES_FILENAME, doc["unmeasured_reason"])


class UnitBandEdgeTest(unittest.TestCase):
    """Полоса шкалы закрывается С ОБЕИХ сторон и включает свои концы."""

    def _ratio(self, factor):
        records = {f"2026-01-{i:02d}": {"apy_evidenced_pct": {A: 4.0}}
                   for i in range(1, 6)}
        points = {A: {f"2026-01-{i:02d}": 4.0 * factor for i in range(1, 6)}}
        return cvi.unit_parity(records, points)

    def test_a_hundredfold_series_is_refused_by_the_UPPER_edge(self):
        got = self._ratio(100.0)
        self.assertTrue(got["measured"])
        self.assertFalse(got["passed"])
        self.assertEqual(got["median_ratio"], 100.0)

    def test_a_hundredth_series_is_refused_by_the_LOWER_edge(self):
        got = self._ratio(0.01)
        self.assertFalse(got["passed"])
        self.assertEqual(got["median_ratio"], 0.01)

    def test_both_edges_are_INCLUSIVE(self):
        self.assertTrue(self._ratio(cvi.UNIT_RATIO_HIGH)["passed"])
        self.assertTrue(self._ratio(cvi.UNIT_RATIO_LOW)["passed"])

    def test_just_outside_each_edge_is_refused(self):
        self.assertFalse(self._ratio(cvi.UNIT_RATIO_HIGH * 1.001)["passed"])
        self.assertFalse(self._ratio(cvi.UNIT_RATIO_LOW * 0.999)["passed"])

    def test_a_hundredfold_series_refuses_the_WHOLE_measurement(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc_raw = json.loads((data / cvi.SERIES_FILENAME).read_text())
            doc_raw["series"] = {k: [[d, v * 100.0] for d, v in rows]
                                 for k, rows in doc_raw["series"].items()}
            (data / cvi.SERIES_FILENAME).write_text(json.dumps(doc_raw),
                                                    encoding="utf-8")
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5,
                                                 material_days=["2026-01-03"]))
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            self.assertIn("РАЗНЫХ шкалах", doc["unmeasured_reason"])

    def test_non_numeric_journal_values_are_not_counted_as_pairs(self):
        """``None`` и ``True`` — не ставки; счесть их ставками значило бы делить на них."""
        records = {"2026-01-01": {"apy_evidenced_pct": {A: None, C: True, M: 4.0}}}
        points = {A: {"2026-01-01": 4.0}, C: {"2026-01-01": 4.0},
                  M: {"2026-01-01": 4.0}}
        got = cvi.unit_parity(records, points)
        self.assertEqual(got["pairs"], 1)
        self.assertEqual(got["compared"], 1)

    def test_median_ratio_is_reported_to_six_digits(self):
        records = {"2026-01-01": {"apy_evidenced_pct": {A: 3.0}}}
        points = {A: {"2026-01-01": 3.0000004}}
        self.assertEqual(cvi.unit_parity(records, points)["median_ratio"], 1.0)


class OrderingTest(unittest.TestCase):
    """Множество печатается ОТСОРТИРОВАННЫМ: произвольный порядок читает человек."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.data = stand_straddle(Path(self.tmp.name))
        self.doc = cvi.measure(self.data, now=FIXED_NOW, horizon_days=HORIZON,
                               ladder_doc=_ladder(**STRADDLE_LADDER))

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_day_list_in_the_answer_is_sorted(self):
        ans = self.doc["answer"]
        for key in ("days_resolved_by_material", "days_unresolved"):
            self.assertEqual(ans[key], sorted(ans[key]), key)
            self.assertGreater(len(ans[key]), 1, key)   # стенд обязан быть нетривиален

    def test_every_day_list_in_the_ladder_parity_is_sorted(self):
        par = self.doc["ladder_parity"]
        for key in ("days_lifted", "days_expected"):
            self.assertEqual(par[key], sorted(par[key]), key)
            self.assertGreater(len(par[key]), 1, key)
        self.assertEqual(self.doc["denominator_source"]["days_expected_to_lift"],
                         sorted(self.doc["denominator_source"]["days_expected_to_lift"]))

    def test_granted_rates_are_emitted_in_a_stable_order(self):
        rows = [(r["cycle_date"], r["key"]) for r in self.doc["granted_rates"]]
        self.assertEqual(rows, sorted(rows))

    def test_withheld_legs_of_the_capability_control_are_sorted(self):
        cap = self.doc["widening_capability"]
        self.assertEqual(cap["legs_withheld"], sorted(cap["legs_withheld"]))

    def test_the_starved_day_is_the_EARLIEST_lifted_one_not_an_arbitrary_one(self):
        self.assertEqual(self.doc["widening_capability"]["day_starved"],
                         min(self.doc["ladder_parity"]["days_lifted"]))


class TwinLeverTest(unittest.TestCase):
    """Рычаг близнецов — ЧУЖОЙ и берётся у соседа целиком; здесь он и проверяется.

    Найдено батареей: во всех стендах близнецов не было вовсе (``trades.json``
    отсутствует), поэтому снятие ``grant_twin`` и подмена чтения пар переживали набор.
    """

    def test_a_twin_rate_from_the_same_record_lifts_a_leg_without_a_sentinel(self):
        records = {"2026-01-01": {"cycle_date": "2026-01-01",
                                  "apy_evidenced_pct": {C: 7.5},
                                  "apy_unevidenced": []}}
        out, prov = cvi.grant_material(records, polled=set(), twins={A: [C]},
                                       points={})
        self.assertEqual(out["2026-01-01"]["apy_evidenced_pct"][A], 7.5)
        self.assertEqual(prov, [],
                         "ставка близнеца не из ряда — в провенансе материала ей не место")

    def test_measure_reads_the_twin_pairs_from_the_canonical_guard(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            seen = {}
            real = cvi._remedy._twin_keys

            def spy(dd):
                seen["called"] = True
                return {"measured": True, "pairs": {"yearn_v3": [A]}}

            cvi._remedy._twin_keys = spy
            try:
                doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                                  ladder_doc=_ladder(today=5,
                                                     material_days=["2026-01-03",
                                                                    "2026-01-05"]))
            finally:
                cvi._remedy._twin_keys = real
            self.assertTrue(seen.get("called"))
            self.assertEqual(doc["status"], cvi.STATUS_OK, doc.get("unmeasured_reason"))

    def test_a_guard_that_gives_no_pairs_is_not_read_as_a_pair(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = cvi._remedy._twin_keys
            cvi._remedy._twin_keys = lambda dd: {"measured": False, "pairs": None}
            try:
                doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                                  ladder_doc=_ladder(today=5,
                                                     material_days=["2026-01-03",
                                                                    "2026-01-05"]))
            finally:
                cvi._remedy._twin_keys = real
            self.assertEqual(doc["status"], cvi.STATUS_OK, doc.get("unmeasured_reason"))


class WideningBranchTest(unittest.TestCase):
    """Три ветки контроля способности — три разных ответа, и они не сливаются."""

    def _ctl(self, **kw):
        base = dict(records={}, base_rows={}, baseline=set(), polled=set(), twins={},
                    points={}, expected=set(), denominator=7, horizon=HORIZON,
                    lifted=set())
        base.update(kw)
        return cvi._widening_control(**base)

    def test_no_lifted_day_is_reported_as_NOT_REQUIRED_not_as_a_pass(self):
        got = self._ctl(lifted=set())
        self.assertFalse(got["required"])
        self.assertTrue(got["passed"])
        self.assertIsNone(got["width"])
        self.assertIn("раздвигать нечего", got["reason"])

    def test_a_day_that_still_lifts_without_material_gives_width_zero_and_refuses(self):
        """Положительный контроль ветки «поднимался не материалом»."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            real = cvi.grant_material

            def deaf(records, **kw):
                kw.pop("withhold", None)          # изъятие ИГНОРИРУЕТСЯ
                return real(records, **kw)

            cvi.grant_material = deaf
            try:
                doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                                  ladder_doc=_ladder(today=5,
                                                     material_days=["2026-01-03",
                                                                    "2026-01-05"]))
            finally:
                cvi.grant_material = real
            self.assertEqual(doc["status"], cvi.STATUS_UNMEASURED)
            cap = doc["widening_capability"]
            self.assertTrue(cap["required"])
            self.assertFalse(cap["passed"])
            self.assertEqual(cap["width"], 0.0)
            self.assertIn("поднимался он не", cap["reason"])

    def test_the_happy_path_marks_the_control_as_REQUIRED_and_passed(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5, material_days=["2026-01-03",
                                                                         "2026-01-05"]))
            cap = doc["widening_capability"]
            self.assertTrue(cap["required"])
            self.assertTrue(cap["passed"])
            self.assertIsNone(cap["reason"])
            self.assertEqual(cap["bound_low"], 0.7143)
            self.assertEqual(cap["bound_high"], 1.0)
            self.assertEqual(cap["width"], 0.2857)


class ControlFlagsTest(unittest.TestCase):
    """Флаги контролей читает человек — значит каждый обязан быть проверен ОБОИМИ значениями."""

    def test_all_control_flags_are_true_on_the_clean_stand(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5, material_days=["2026-01-03",
                                                                         "2026-01-05"]))
            for block in ("unit_parity", "numerator_parity", "ladder_parity",
                          "provenance_control", "monotonicity_control",
                          "widening_capability"):
                self.assertTrue(doc[block]["passed"], block)
            self.assertEqual(doc["monotonicity_control"]["days_lost"], [])
            self.assertEqual(doc["provenance_control"]["not_found_in_series"], [])

    def test_the_gate_flags_follow_the_bounds_and_not_each_other(self):
        with TemporaryDirectory() as tmp:
            data = stand_straddle(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(**STRADDLE_LADDER))
            self.assertEqual(doc["answer"]["bound_low"], 0.4615)
            self.assertEqual(doc["answer"]["bound_high"], 0.6923)
            self.assertFalse(doc["gate"]["passes_at_low_bound"])
            self.assertTrue(doc["gate"]["passes_at_high_bound"])


class CountsAndExitCodeTest(unittest.TestCase):
    """Счётчики моста и код возврата — числа, которые читают бегун и CI."""

    def test_counts_are_exact_on_a_known_stand(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stand_interval(root)
            doc = cvi.run(root=str(root), now=FIXED_NOW, horizon_days=HORIZON,
                          write=False,
                          ladder_doc=_ladder(today=5, material_days=["2026-01-03",
                                                                     "2026-01-05"]))
            findings = doc["findings"]
            self.assertEqual(doc["counts"]["critical"], 0)
            self.assertEqual(doc["counts"]["warn"], 0)
            self.assertEqual(doc["counts"]["unchecked"], 0)
            self.assertEqual(
                doc["counts"]["info"],
                len([x for x in findings
                     if x.startswith(("[ОТВЕТ]", "[БЕЗ СЕНТИНЕЛА]", "[ПО ДНЯМ]",
                                      "[ОПОРА]", "[ШИРИНА]", "[ОТДАЧА]"))]))
            self.assertEqual(doc["counts"]["info"], 5)
            self.assertEqual(
                sorted(x.split("]")[0] + "]" for x in findings),
                ["[БЕЗ СЕНТИНЕЛА]", "[ОПОРА]", "[ОТВЕТ]", "[ОТДАЧА]", "[ПО ДНЯМ]"])

    def test_counts_on_a_critical_stand_name_exactly_one_critical(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stand_straddle(root)
            doc = cvi.run(root=str(root), now=FIXED_NOW, horizon_days=HORIZON,
                          write=False, ladder_doc=_ladder(**STRADDLE_LADDER))
            self.assertEqual(doc["counts"]["critical"], 1)
            self.assertEqual(doc["counts"]["unchecked"], 0)

    def test_run_with_write_false_leaves_the_data_dir_untouched(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = stand_interval(root)
            before = sorted(p.name for p in data.iterdir())
            cvi.run(root=str(root), now=FIXED_NOW, horizon_days=HORIZON, write=False,
                    ladder_doc=_ladder(today=5, material_days=["2026-01-03"]))
            self.assertEqual(sorted(p.name for p in data.iterdir()), before)

    def test_main_writes_the_artifact_even_when_the_measurement_refused(self):
        """Отказ — тоже ответ, и он обязан доехать до читателя файлом, а не пропасть."""
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            self.assertEqual(cvi.main(["--data-dir", str(data)]), 1)
            written = json.loads((data / cvi.OUTPUT_FILENAME).read_text())
            self.assertEqual(written["version"], cvi.VERSION)
            self.assertEqual(written["status"], cvi.STATUS_UNMEASURED)

    def test_main_maps_each_status_to_its_own_exit_code(self):
        real = cvi.measure
        try:
            for status, code in ((cvi.STATUS_OK, 0), (cvi.STATUS_WARNING, 0),
                                 (cvi.STATUS_CRITICAL, 1),
                                 (cvi.STATUS_UNMEASURED, 1)):
                cvi.measure = (lambda st: lambda *a, **kw: {
                    "status": st, "answer": None, "findings": []})(status)
                with TemporaryDirectory() as tmp:
                    self.assertEqual(
                        cvi.main(["--data-dir", tmp, "--no-write"]), code, status)
        finally:
            cvi.measure = real


class ReportOnRefusalTest(unittest.TestCase):
    """Отрисовка отказа обязана НАЗВАТЬ причину, а не промолчать о ней."""

    def test_a_refusal_doc_renders_its_reason_and_skips_absent_blocks(self):
        doc = {"status": cvi.STATUS_UNMEASURED, "unmeasured_reason": "нет журнала",
               "findings": ["[НЕ ИЗМЕРЕНО] нет журнала"], "answer": None,
               "advisory": cvi._ADVISORY}
        lines = cvi.format_report(doc)
        text = "\n".join(lines)
        self.assertIn("нет журнала", text)
        self.assertIn(cvi.STATUS_UNMEASURED, text)
        self.assertNotIn("[ИНТЕРВАЛ]", text)
        self.assertNotIn("сошлась", text)

    def test_a_failed_control_is_rendered_as_NOT_PASSED(self):
        doc = {"status": cvi.STATUS_UNMEASURED, "answer": None, "findings": [],
               "unit_parity": {"passed": False, "measured": True}}
        self.assertIn("НЕ СОШЛАСЬ", "\n".join(cvi.format_report(doc)))


class GateThresholdEdgeTest(unittest.TestCase):
    """Порог взвода ВКЛЮЧАЮЩИЙ, и каждая граница судится ОТДЕЛЬНО.

    Найдено батареей: `>=` -> `>` и `and` -> `or` в обоих сравнениях переживали набор —
    стенды никогда не клали границу РОВНО на порог и никогда не роняли обе сразу.
    Порог берётся у канонического производителя (`shadow_trigger_eval.MIN_HIT_RATE`,
    правило ADR-067), поэтому и подменяется он там же: своей копии порога у прибора нет.
    """

    def _measure(self, threshold, stand, ladder):
        real = _ste.MIN_HIT_RATE
        _ste.MIN_HIT_RATE = threshold
        try:
            with TemporaryDirectory() as tmp:
                data = stand(Path(tmp))
                return cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                                   ladder_doc=_ladder(**ladder))
        finally:
            _ste.MIN_HIT_RATE = real

    def test_a_bound_landing_exactly_on_the_threshold_PASSES(self):
        doc = self._measure(0.8571, stand_interval,
                            dict(today=5, material_days=["2026-01-03", "2026-01-05"]))
        self.assertEqual(doc["answer"]["bound_low"], 0.8571)
        self.assertEqual(doc["gate"]["min_hit_rate"], 0.8571)
        self.assertTrue(doc["gate"]["passes_at_low_bound"],
                        "порог `hit_rate >= MIN_HIT_RATE` ВКЛЮЧАЮЩИЙ у самого судьи")

    def test_a_bound_a_hair_above_the_threshold_also_passes(self):
        doc = self._measure(0.8570, stand_interval,
                            dict(today=5, material_days=["2026-01-03", "2026-01-05"]))
        self.assertTrue(doc["gate"]["passes_at_low_bound"])

    def test_a_bound_a_hair_below_the_threshold_fails(self):
        doc = self._measure(0.8572, stand_interval,
                            dict(today=5, material_days=["2026-01-03", "2026-01-05"]))
        self.assertFalse(doc["gate"]["passes_at_low_bound"])
        self.assertTrue(doc["gate"]["passes_at_high_bound"])
        self.assertFalse(doc["gate"]["verdict_insensitive"])

    def test_BOTH_bounds_below_the_threshold_are_both_reported_as_failing(self):
        """Иначе «верхняя граница проходит» держалось бы на том, что она не `None`."""
        doc = self._measure(0.99, stand_straddle, STRADDLE_LADDER)
        self.assertEqual(doc["answer"]["bound_high"], 0.6923)
        self.assertFalse(doc["gate"]["passes_at_low_bound"])
        self.assertFalse(doc["gate"]["passes_at_high_bound"])
        self.assertTrue(doc["gate"]["verdict_insensitive"])
        self.assertEqual(doc["status"], cvi.STATUS_OK)

    def test_the_high_bound_landing_exactly_on_the_threshold_passes(self):
        doc = self._measure(0.6923, stand_straddle, STRADDLE_LADDER)
        self.assertTrue(doc["gate"]["passes_at_high_bound"])
        self.assertFalse(doc["gate"]["passes_at_low_bound"])


class UnitBandLiteralTest(unittest.TestCase):
    """Полоса шкалы закрепляется ЛИТЕРАЛАМИ, а не через собственные константы.

    Найдено батареей: подмена `UNIT_RATIO_HIGH` переживала набор, потому что все
    ожидания считались через саму константу — контроль, истинный по построению.
    """

    def _passed(self, ratio):
        records = {"2026-01-01": {"apy_evidenced_pct": {A: 4.0}}}
        points = {A: {"2026-01-01": 4.0 * ratio}}
        return cvi.unit_parity(records, points)["passed"]

    def test_ratio_two_passes_and_ratio_two_and_a_half_does_not(self):
        self.assertTrue(self._passed(2.0))
        self.assertFalse(self._passed(2.5))
        self.assertFalse(self._passed(3.0))

    def test_ratio_one_half_passes_and_ratio_one_third_does_not(self):
        self.assertTrue(self._passed(0.5))
        self.assertFalse(self._passed(0.4))

    def test_the_band_literals_are_the_ones_the_module_declares(self):
        self.assertEqual((cvi.UNIT_RATIO_LOW, cvi.UNIT_RATIO_HIGH), (0.5, 2.0))


class EmptyListRenderingTest(unittest.TestCase):
    """Пустой перечень печатается ЗНАКОМ, а не пустотой: пустота читается как обрыв."""

    def test_no_unresolved_days_renders_a_dash_not_an_empty_gap(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5,
                                                 material_days=["2026-01-03"]))
            answer = [x for x in doc["findings"] if x.startswith("[ОТВЕТ]")][0]
            self.assertIn("не разрешено 0 (—)", answer)
            self.assertIn("2026-01-03", answer)


class ReportBlockSkippingTest(unittest.TestCase):
    """Отсутствующий блок НЕ печатается вовсе — ни «сошлась», ни «НЕ СОШЛАСЬ».

    Найдено батераей: снятие `not` в пропуске блока переживало набор, потому что тест
    искал слово в одном регистре, а печаталось оно в другом.
    """

    LABELS = ("шкала журнала и ряда", "сверка числителя с каноническим",
              "односторонняя сверка знаменателя с лестницей",
              "каждая ставка найдена в ряду", "способность разойтись границами")

    def test_absent_control_blocks_produce_no_line_at_all(self):
        doc = {"status": cvi.STATUS_UNMEASURED, "unmeasured_reason": "нет журнала",
               "findings": [], "answer": None}
        text = "\n".join(cvi.format_report(doc))
        for label in self.LABELS:
            self.assertNotIn(label, text)

    def test_present_control_blocks_produce_exactly_one_line_each(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5, material_days=["2026-01-03",
                                                                         "2026-01-05"]))
            text = "\n".join(cvi.format_report(doc))
            for label in self.LABELS:
                self.assertEqual(text.count(label), 1, label)

    def test_an_empty_findings_list_prints_no_finding_lines(self):
        doc = {"status": cvi.STATUS_OK, "answer": None, "findings": []}
        lines = cvi.format_report(doc)
        self.assertEqual(len(lines), 1, lines)


class UncheckedCountTest(unittest.TestCase):
    """Счётчик «не измерено» считает ОДИН отказ один раз, а не сколько-нибудь."""

    def test_a_refusal_counts_exactly_one_unchecked(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            doc = cvi.run(root=str(root), now=FIXED_NOW, horizon_days=HORIZON,
                          write=False, ladder_doc=_ladder(today=5, material_days=[]))
            # Отказ даёт И статус UNMEASURED, И строку findings — счётчик обязан
            # сложить оба слагаемых, иначе одно из них прикрывает пропажу второго.
            self.assertEqual(doc["counts"]["unchecked"], 2)
            self.assertEqual(len([x for x in doc["findings"]
                                  if x.startswith("[НЕ ИЗМЕРЕНО]")]), 1)


class ArtifactBoundariesTest(unittest.TestCase):
    def test_the_limits_of_the_claim_travel_inside_the_artifact(self):
        with TemporaryDirectory() as tmp:
            data = stand_interval(Path(tmp))
            doc = cvi.measure(data, now=FIXED_NOW, horizon_days=HORIZON,
                              ladder_doc=_ladder(today=5, material_days=["2026-01-03",
                                                                         "2026-01-05"]))
            self.assertEqual(doc["what_it_does_not_prove"], cvi.WHAT_IT_DOES_NOT_PROVE)
            self.assertTrue(any("середина" in x or "между границами" in x
                                for x in doc["what_it_does_not_prove"]))
            self.assertIn("ADVISORY", doc["advisory"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
