"""Приёмка прибора «доля населения критерия по ПОЛУ, а не по потолку» (заказ #599/G13).

Каждый тест — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на дефект, который замер изготовил бы, будь правило
написано иначе. Стенд подаёт выдачи соседей напрямую (точки инъекции ``rec_doc`` /
``sldp_doc`` / ``mat_doc``): живой журнал для вопроса «правильно ли мы делим» не нужен, а
зависимость от него сделала бы вердикт теста функцией сегодняшнего состояния фидов.

Дни в стенде — ISO-подобные строки, и это НЕ замороженные даты: прибор день не парсит
вовсе, он его только сравнивает и сортирует. Часы прибора инъектированы отдельно.
"""
# FROZEN-DATE-OK: injected-clock — часы прибора инъектируются литералом _NOW в measure(now=),
# а ISO-строки дней суть ИДЕНТИЧНОСТИ (прибор их не парсит и ни с чем не сравнивает по
# календарю), поэтому сдвиг календаря вердикт теста не меняет.
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import criterion_population_floor as C

#: Якорь часов. Передаётся в measure(now=) — единственный источник времени в приборе.
_NOW = datetime(2026, 9, 14, 4, 0, 0, tzinfo=timezone.utc)

_DATA = Path("/nonexistent-by-design")  # соседи инъектированы ⇒ каталог не читается

# Населения стенда. Имена держатся здесь ОДИН раз: вторая копия разошлась бы с первой молча.
_TODAY = [f"2026-08-{d:02d}" for d in (6, 7, 9, 13, 14, 15, 19, 20, 27, 29)] + \
         [f"2026-09-{d:02d}" for d in (2, 3, 4, 5, 7, 11)]          # 16 дн.
_SILENT = ["2026-09-06", "2026-09-08", "2026-09-09", "2026-09-10"]  # без материала, 4 дн.
_OWNER = ["2026-08-24"]                                             # рычаг владельца, 1 дн.
_OURS = ["2026-08-11", "2026-08-16", "2026-09-01"]                  # наш код + материал, 3
_RECOVERABLE = sorted(_OURS + _OWNER + _SILENT)                     # 8 дн.


def _rec(*, today=None, recoverable=None, ceiling=None, writer_added=None,
         writer_den=None, our_added=None, owner=None, status=C.STATUS_OK,
         parity=True, canonical_measured=True):
    """Выдача потолочного прибора. По умолчанию — форма живого замера 14.09."""
    today = list(_TODAY if today is None else today)
    recoverable = list(_RECOVERABLE if recoverable is None else recoverable)
    writer_added = list(_OURS + _SILENT[:3] if writer_added is None else writer_added)
    our_added = list(_OURS + _SILENT if our_added is None else our_added)
    owner = list(_OWNER if owner is None else owner)
    doc = {
        "status": status,
        "journal": {"days": 39},
        "population": {"denominator_today": len(today),
                       "denominator_days_today": today,
                       "recoverable_in_principle": len(recoverable),
                       "recoverable_days": recoverable},
        "canonical_parity": {"canonical_measured": canonical_measured,
                             "passed": parity, "canonical_size": len(today)},
        "scenarios": {
            C.SC_WRITER: {
                "denominator": (len(today) + len(writer_added) if writer_den is None
                                else writer_den),
                "days_added": writer_added},
            "key_mismatch": {"denominator": len(today), "days_added": []},
            C.SC_OUR_CODE: {"denominator": len(today) + len(our_added),
                            "days_added": our_added,
                            "recoverable_not_lifted": owner},
            C.SC_CEILING: {"denominator": (len(today) + len(recoverable)
                                           if ceiling is None else ceiling),
                           "days_added": recoverable,
                           "recoverable_not_lifted": []},
        },
    }
    return doc


def _sldp(*, today=None, recoverable=None, blocking=None, floor=None,
          status=C.STATUS_OK, parity=True, legs=("pendle",)):
    """Выдача прибора цены молчащей ноги."""
    today = list(_TODAY if today is None else today)
    recoverable = list(_RECOVERABLE if recoverable is None else recoverable)
    blocking = list(_SILENT if blocking is None else blocking)
    return {
        "status": status,
        "population": {"denominator_today": len(today),
                       "recoverable_in_principle": len(recoverable),
                       "recoverable_days": recoverable},
        "canonical_parity": {"canonical_measured": True, "passed": parity},
        "answer": {"silent_legs": list(legs)},
        "per_leg": [{"leg": legs[0] if legs else "pendle",
                     "blocking_days": len(blocking),
                     "blocking_day_list": blocking,
                     "writer_lever_floor_without_leg": (19 if floor is None else floor)}]
        if legs else [],
    }


def _mat(*, empty=None, material=None, status=C.STATUS_OK):
    """Выдача второго производителя материала (ADR-378), подтверждение НЕ несущее."""
    empty = list(_SILENT if empty is None else empty)
    material = list(_OURS + _OWNER if material is None else material)
    return {"status": status,
            "per_day": ([{"cycle_date": d, "verdict": "proven_empty"} for d in empty]
                        + [{"cycle_date": d, "verdict": "material"} for d in material])}


def _measure(**kw):
    kw.setdefault("rec_doc", _rec())
    kw.setdefault("sldp_doc", _sldp())
    kw.setdefault("mat_doc", _mat())
    return C.measure(_DATA, now=_NOW, **kw)


class TestAnswer(unittest.TestCase):
    """Ответ заказа: три ступени лестницы и доля на каждой."""

    def test_ladder_has_three_distinct_rungs(self):
        # Дефект, если слить: читатель отправляется чинить не то место — у ступеней
        # РАЗНЫЕ владельцы рычага, и одна доля их не различает.
        doc = _measure()
        rungs = {r["rung"]: r["denominator"] for r in doc["ladder"]}
        self.assertEqual(rungs, {C.RUNG_CEILING: 24, C.RUNG_MATERIAL: 20,
                                 C.RUNG_OUR_CODE: 19})

    def test_share_by_floor_is_higher_than_by_ceiling(self):
        # Дефект, если перепутать направление: опубликованная доля выглядела бы ЗАВЫШЕННОЙ,
        # и вывод «критерий стои́т на большем населении, чем думали» перевернулся бы.
        a = _measure()["answer"]
        self.assertEqual(a["share_by_ceiling_pct"], 66.67)
        self.assertEqual(a["share_by_material_floor_pct"], 80.0)
        self.assertEqual(a["share_by_our_code_floor_pct"], 84.21)
        self.assertLess(a["share_by_ceiling_pct"], a["share_by_material_floor_pct"])
        self.assertLess(a["share_by_material_floor_pct"],
                        a["share_by_our_code_floor_pct"])

    def test_the_ladder_and_the_answer_never_disagree_about_a_share(self):
        # Дефект, который эта проверка ловит, и он ТИХИЙ: доли считаются ДВАЖДЫ —
        # один раз в `ladder` (стр. «лестница»), второй в `answer`. Тесты выше
        # спрашивают только `answer`, а шаг 0-офис печатает ЛЕСТНИЦУ. Значит число,
        # которое читает человек, могло разойтись с числом, которое стережёт набор,
        # и оба выглядели бы измеренными (класс «два артефакта одного прогона,
        # спорящие между собой»). Сверяем ОБА представления и с арифметикой тоже:
        # совпадение друг с другом при общей ошибке иначе прошло бы за ответ.
        doc = _measure()
        a, today = doc["answer"], doc["population"]["denominator_today"]
        by_rung = {r["rung"]: r for r in doc["ladder"]}
        for rung, key in ((C.RUNG_CEILING, "share_by_ceiling_pct"),
                          (C.RUNG_MATERIAL, "share_by_material_floor_pct"),
                          (C.RUNG_OUR_CODE, "share_by_our_code_floor_pct")):
            with self.subTest(rung):
                row = by_rung[rung]
                self.assertEqual(row["share_pct"], a[key])
                self.assertEqual(row["share_pct"],
                                 C._share(today, row["denominator"]))

    def test_criterion_value_is_never_computed(self):
        # ADR-300: вердикт под сентинелом есть артефакт сентинела. Напечатать значение
        # означало бы выдать артефакт за наблюдение.
        a = _measure()["answer"]
        self.assertIsNone(a["criterion_value"])
        self.assertIn("ADR-300", a["criterion_value_note"])

    def test_days_denied_by_material_are_named_not_only_counted(self):
        # Дефект, если только считать: читатель не может проверить число и не знает,
        # какую починку оно отменяет.
        doc = _measure()
        self.assertEqual(doc["population"]["days_without_material"], _SILENT)
        self.assertEqual(doc["answer"]["days_queue_counts_but_material_denies"], 4)

    def test_bound_direction_travels_in_the_artifact(self):
        # Шапку модуля читатель отчёта не открывает; направление границы обязано ехать
        # там, где число.
        a = _measure()["answer"]
        self.assertIn("НИЖНЯЯ", a["bound_direction"])
        # Оговорка про недостаточность материала обязана ехать в СПИСКЕ границ, а не
        # только в шапке: без неё пол читается как «столько дней вернётся».
        self.assertTrue(any("НЕОБХОДИМОЕ" in x and "не достаточное" in x
                            for x in _measure()["what_it_does_not_prove"]))


class TestQueue(unittest.TestCase):
    """Очередь починок: что именно меняется сдвигом с потолка на пол."""

    def test_writer_lever_loses_half_its_published_days(self):
        # Ровно та находка, ради которой заказ и оставлен: дешёвая строка писателя,
        # опубликованная в 6 дн., материалом подтверждена на 3.
        row = {q["lever"]: q for q in _measure()["repair_queue"]}[C.SC_WRITER]
        self.assertEqual(row["days_published"], 6)
        self.assertEqual(row["days_with_material"], 3)
        self.assertEqual(row["day_list_with_material"], _OURS)
        self.assertEqual(row["days_resting_on_absent_material"], _SILENT[:3])

    def test_silent_leg_feed_returns_zero_historical_days_and_it_is_measured(self):
        # Дефект, если поставить дни фида в очередь: починка ценна ВПЕРЁД, исторических
        # дней она не возвращает ни одного — ряд задним числом не наполняется. Ноль здесь
        # ИЗМЕРЕН (население непустое), и это не «не измерено».
        row = {q["lever"]: q for q in _measure()["repair_queue"]}["silent_leg_feed"]
        self.assertEqual(row["days_published"], 4)
        self.assertEqual(row["days_with_material"], 0)
        self.assertEqual(row["days_resting_on_absent_material"], _SILENT)
        self.assertIn("ВПЕРЁД", row["whose"])

    def test_owner_lever_is_kept_separate_from_our_code(self):
        # Слить их значило бы отдать наружу работу, лежащую у нас, — или наоборот
        # записать себе в план чужой рычаг.
        rows = {q["lever"]: q for q in _measure()["repair_queue"]}
        self.assertEqual(rows["owner_polled_adapters"]["days_with_material"], 1)
        self.assertIn("владелец", rows["owner_polled_adapters"]["whose"])
        self.assertEqual(rows[C.SC_OUR_CODE]["whose"], "наш код")

    def test_every_lever_row_carries_both_numbers(self):
        # Строка с одним числом читается как план: опубликованное без материального
        # и есть та переоценка, против которой заказ написан.
        for q in _measure()["repair_queue"]:
            self.assertIn("days_published", q)
            self.assertIn("days_with_material", q)
            self.assertIn("whose", q)


class TestPopulationParity(unittest.TestCase):
    """Соседи обязаны говорить об ОДНОМ населении, и это проверяется."""

    def test_same_cardinality_different_days_refuses(self):
        # ГЛАВНЫЙ положительный контроль: две восьмёрки могут быть РАЗНЫМИ восьмёрками.
        # Совпадение мощности тождества населения не доказывает, а доля, собранная из
        # разных осей, выглядит измеренной.
        other = sorted(_OURS + _OWNER + ["2026-09-06", "2026-09-08", "2026-09-09",
                                         "2026-09-12"])
        self.assertEqual(len(other), len(_RECOVERABLE))
        doc = _measure(sldp_doc=_sldp(recoverable=other))
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("РАЗНЫХ населениях", doc["unmeasured_reason"])

    def test_recoverable_days_missing_refuses(self):
        # Сосед, назвавший только мощность, тождество проверить не даёт — и «похоже,
        # то же самое» причиной не является.
        s = _sldp()
        s["population"].pop("recoverable_days")
        doc = _measure(sldp_doc=s)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("поимённо", doc["unmeasured_reason"])

    def test_different_denominator_today_refuses(self):
        doc = _measure(sldp_doc=_sldp(today=_TODAY[:15]))
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("знаменателе", doc["unmeasured_reason"])

    def test_neighbour_without_canonical_parity_refuses(self):
        # Сосед, отобравший население ВТОРЫМ определением, отвечает не на тот вопрос;
        # доля стояла бы не на том наборе.
        for kw in ({"rec_doc": _rec(parity=False)}, {"sldp_doc": _sldp(parity=False)}):
            with self.subTest(**{k: "parity=False" for k in kw}):
                doc = _measure(**kw)
                self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
                self.assertIn("КАНОНИЧЕСКИМ", doc["unmeasured_reason"])

    def test_canonical_parity_not_measured_refuses(self):
        # «Не измерено» у соседа не есть «сошлось»: fail-OPEN тише красного и потому хуже.
        doc = _measure(rec_doc=_rec(canonical_measured=False))
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)

    def test_parity_result_is_recorded_in_the_artifact(self):
        p = _measure()["population"]["parity_with_neighbours"]
        self.assertTrue(p["same_recoverable_set"] and p["same_denominator_today"])


class TestThirdOutcome(unittest.TestCase):
    """Отсутствие наблюдения — отдельное значение, а не ноль и не успех (инв. #17)."""

    def test_neighbour_unmeasured_propagates_as_unmeasured(self):
        for kw in ({"rec_doc": _rec(status=C.STATUS_UNMEASURED)},
                   {"sldp_doc": _sldp(status=C.STATUS_UNMEASURED)}):
            with self.subTest(str(list(kw))):
                doc = _measure(**kw)
                self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
                self.assertNotIn("answer", doc)

    def test_neighbour_raising_is_named_not_swallowed(self):
        class Boom:
            @staticmethod
            def measure(*a, **k):
                raise RuntimeError("журнал не прочитан")

        real = C._rec
        try:
            C._rec = Boom
            doc = C.measure(_DATA, now=_NOW, sldp_doc=_sldp(), mat_doc=_mat())
        finally:
            C._rec = real
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("RuntimeError", doc["unmeasured_reason"])
        self.assertIn("журнал не прочитан", doc["unmeasured_reason"])

    def test_the_other_neighbour_raising_is_named_too_and_by_its_own_name(self):
        # Дефект, который эта проверка ловит: у соседа-прибора пола своя дверь отказа,
        # и снятая она НЕ видна — ниже стои́т дверь «сосед не назвал дни поимённо»,
        # которая перехватит пустую выдачу и назовёт ДРУГУЮ причину. Отказ соседа
        # выглядел бы разногласием о населении, и чинить пошли бы не то. Поэтому
        # спрашивается имя исключения, а не только статус.
        class Boom:
            @staticmethod
            def measure(*a, **k):
                raise RuntimeError("прибор пола не прочитан")

        real = C._sldp
        try:
            C._sldp = Boom
            doc = C.measure(_DATA, now=_NOW, rec_doc=_rec(), mat_doc=_mat())
        finally:
            C._sldp = real
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn(C.NO_SLDP, doc["unmeasured_reason"])
        self.assertIn("RuntimeError", doc["unmeasured_reason"])
        self.assertIn("прибор пола не прочитан", doc["unmeasured_reason"])

    def test_run_counts_unmeasured_separately_from_zero(self):
        # Растворив «не измерено» в нулях, мы сделали бы молчание прибора неотличимым от
        # чистого прогона. Считается ИМЕННО у run(): счётчики читает мост находок, и
        # проверять их у measure() значило бы проверять не то, что он печатает.
        doc = C.run(root=str(_DATA), now=_NOW, write=False,
                    rec_doc=_rec(status=C.STATUS_UNMEASURED),
                    sldp_doc=_sldp(), mat_doc=_mat())
        self.assertEqual(doc["overall"], C.STATUS_UNMEASURED)
        # Оба слагаемых названы поимённо: статус даёт единицу и строка [НЕ ИЗМЕРЕНО] даёт
        # свою. Проверка `>= 1` прошла бы при обнулённом вкладе любого из двух.
        self.assertEqual(doc["counts"]["unchecked"], 2)
        self.assertEqual(doc["counts"]["critical"], 0)

    def test_run_counts_a_clean_measurement_without_unchecked(self):
        # Обратная сторона: измеренный прогон обязан давать НОЛЬ в «не измерено», иначе
        # счётчик звонил бы всегда и перестал бы что-либо значить.
        doc = C.run(root=str(_DATA), now=_NOW, write=False, rec_doc=_rec(),
                    sldp_doc=_sldp(), mat_doc=_mat())
        self.assertEqual(doc["counts"]["unchecked"], 0)
        self.assertEqual(doc["counts"]["critical"], 1)

    def test_zero_denominator_gives_none_not_zero_share(self):
        self.assertIsNone(C._share(0, 0))
        self.assertEqual(C._share(0, 4), 0.0)  # измеренный ноль звучит иначе


class TestArithmeticGuards(unittest.TestCase):
    """Чужую арифметику прибор проверяет, а не принимает на слово."""

    def test_ceiling_not_equal_to_today_plus_recoverable_refuses(self):
        # Числа соседа, не сходящиеся между собой, сводить нельзя: результат выглядел бы
        # измеренным, а держался бы на опечатке производителя.
        doc = _measure(rec_doc=_rec(ceiling=25))
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("не сходятся", doc["unmeasured_reason"])

    def test_ceiling_scenario_absent_refuses_and_does_not_improvise_one(self):
        # Дефект, который эта проверка ловит: потолок — ЧУЖОЕ число, и взять его
        # неоткуда, если сосед сценарий не назвал. Собрать потолок самим (хоть бы и
        # «знаменатель плюс восстановимые») означало бы ровно то, что этому прибору
        # запрещено: пересчитать чужое число и выдать свою догадку за замер соседа.
        rec = _rec()
        del rec["scenarios"][C.SC_CEILING]
        doc = _measure(rec_doc=rec)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn(C.SC_CEILING, doc["unmeasured_reason"])
        self.assertNotIn("ladder", doc)
        self.assertNotIn("answer", doc)

    def test_silent_day_outside_population_refuses(self):
        # Вычитание из НЕ ТОГО набора даёт правдоподобный пол при разошедшихся осях.
        doc = _measure(sldp_doc=_sldp(blocking=_SILENT[:3] + ["2026-07-01"]))
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("вне населения", doc["unmeasured_reason"])

    def test_owner_day_outside_population_refuses(self):
        doc = _measure(rec_doc=_rec(owner=["2026-07-02"]))
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("вне собственного населения", doc["unmeasured_reason"])

    def test_day_both_without_material_and_owners_is_subtracted_once(self):
        # Двойной счёт занизил бы пол и ЗАВЫСИЛ бы долю — ошибка в сторону «у нас всё
        # лучше, чем думали», то есть самая опасная из двух.
        doc = _measure(rec_doc=_rec(owner=[_SILENT[0]]), sldp_doc=_sldp())
        rungs = {r["rung"]: r["denominator"] for r in doc["ladder"]}
        self.assertEqual(rungs[C.RUNG_MATERIAL], 20)
        self.assertEqual(rungs[C.RUNG_OUR_CODE], 20)  # не 19: день уже вычтен

    def test_no_days_without_material_leaves_floor_equal_to_ceiling(self):
        # Измеренное согласие обязано звучать иначе, чем отказ: пол = потолок это ОТВЕТ.
        doc = _measure(sldp_doc=_sldp(blocking=[], floor=22, legs=()),
                       mat_doc=_mat(empty=[], material=_RECOVERABLE))
        rungs = {r["rung"]: r["denominator"] for r in doc["ladder"]}
        self.assertEqual(rungs[C.RUNG_CEILING], rungs[C.RUNG_MATERIAL])
        self.assertEqual(doc["status"], C.STATUS_WARNING)  # остаётся день владельца
        self.assertEqual(doc["answer"]["days_queue_counts_but_material_denies"], 0)


class TestRouteParity(unittest.TestCase):
    """Контроль маршрута: пол рычага писателя получен двумя машинериями."""

    def test_routes_agree_on_live_shaped_input(self):
        r = _measure()["route_parity"]
        self.assertTrue(r["measured"] and r["passed"])
        self.assertEqual((r["our_route"], r["neighbour_route"]), (19, 19))

    def test_route_mismatch_refuses_and_does_not_pick_a_winner(self):
        # Дефект, если выбрать любое: прибор не знает, какое из двух неверно, и молчаливый
        # выбор выдал бы догадку за замер.
        doc = _measure(sldp_doc=_sldp(floor=20))
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("маршруты разошлись", doc["unmeasured_reason"].lower())
        self.assertNotIn("answer", doc)

    def test_route_unmeasurable_is_named_not_passed(self):
        s = _sldp()
        s["per_leg"][0].pop("writer_lever_floor_without_leg")
        doc = _measure(sldp_doc=s)
        self.assertFalse(doc["route_parity"]["measured"])
        self.assertIsNotNone(doc["route_parity"]["reason"])
        self.assertIn("route_parity", doc)
        self.assertIn("answer", doc)  # отсутствие контроля не отменяет ответ


class TestCorroboration(unittest.TestCase):
    """Подтверждение вторым производителем — названное, но НЕ несущее."""

    def test_neighbour_measuring_nothing_does_not_refuse_but_is_declared(self):
        # Чужая ось не вправе отменять наш ответ; но и молчать о её отсутствии нельзя.
        doc = _measure(mat_doc={"status": C.STATUS_UNMEASURED,
                                "unmeasured_reason": "ряд не прочитан"})
        self.assertIn("answer", doc)
        self.assertFalse(doc["material_corroboration"]["measured"])
        self.assertIn("ряд не прочитан", doc["material_corroboration"]["reason"])
        self.assertTrue(any(x.startswith("[НЕ ИЗМЕРЕНО]") for x in doc["findings"]))

    def test_neighbour_that_cannot_be_called_does_not_refuse_but_is_declared(self):
        """Вторая причина отсутствия, и она НЕ та же самая.

        «Звать было нечем» и «позван и сам не измерил» — разные состояния мира. Слить их
        значило бы отправить читателя чинить не то место: в первом случае сломан вызов,
        во втором у соседа нет материала. Путь проверяется ПОДМЕНОЙ соседа, а не
        передачей `mat_doc=None`: `None` означает «сходи и принеси», и прибор идёт —
        тест на нём мерил бы поведение соседа на несуществующем каталоге, а не наше.
        """
        class Boom:
            @staticmethod
            def measure(*a, **k):
                raise RuntimeError("ряд недоступен")

        real = C._mat
        try:
            C._mat = Boom
            doc = C.measure(_DATA, now=_NOW, rec_doc=_rec(), sldp_doc=_sldp())
        finally:
            C._mat = real
        self.assertIn("answer", doc)          # отказ соседа-подтверждения НЕ фатален
        self.assertEqual(doc["status"], C.STATUS_CRITICAL)
        self.assertFalse(doc["material_corroboration"]["measured"])
        self.assertIn("звать было нечем", doc["material_corroboration"]["reason"])

    def test_the_two_reasons_for_absence_are_distinguishable(self):
        # Инв. #17 внутри одного «не измерено»: причина обязана называть, ЧТО именно
        # не состоялось, иначе одна строка покрывает два разных дефекта.
        a = _measure(mat_doc={"status": C.STATUS_UNMEASURED,
                              "unmeasured_reason": "x"})["material_corroboration"]

        class Boom:
            @staticmethod
            def measure(*a, **k):
                raise RuntimeError("y")

        real = C._mat
        try:
            C._mat = Boom
            b = C.measure(_DATA, now=_NOW, rec_doc=_rec(),
                          sldp_doc=_sldp())["material_corroboration"]
        finally:
            C._mat = real
        self.assertNotEqual(a["reason"], b["reason"])

    def test_disagreement_is_named_not_swallowed_and_not_fatal(self):
        doc = _measure(mat_doc=_mat(empty=_SILENT[:2],
                                    material=_OURS + _OWNER + _SILENT[2:]))
        self.assertIn("answer", doc)
        self.assertTrue(doc["material_corroboration"]["disagreements"])
        self.assertTrue(any(x.startswith("[РАСХОЖДЕНИЕ]") for x in doc["findings"]))

    def test_agreement_on_live_shaped_input(self):
        c = _measure()["material_corroboration"]
        self.assertTrue(c["measured"] and c["agreed"])
        self.assertEqual(c["days_compared"], len(_RECOVERABLE))


class TestStatusAndReport(unittest.TestCase):
    """Статус и отрисовка — то, что читает шаг 0-офис."""

    def test_status_critical_when_material_denies_days(self):
        self.assertEqual(_measure()["status"], C.STATUS_CRITICAL)

    def test_status_ok_only_when_nothing_is_denied_and_no_owner_day(self):
        doc = _measure(rec_doc=_rec(owner=[]),
                       sldp_doc=_sldp(blocking=[], floor=22, legs=()),
                       mat_doc=_mat(empty=[], material=_RECOVERABLE))
        self.assertEqual(doc["status"], C.STATUS_OK)

    def test_report_prints_every_rung_and_every_lever(self):
        # Строка отчёта — единственное, что видит читатель шага 0-офис; ступень, не
        # попавшая в печать, для него не существует.
        lines = C.format_report(_measure())
        blob = "\n".join(lines)
        for rung in (C.RUNG_CEILING, C.RUNG_MATERIAL, C.RUNG_OUR_CODE):
            self.assertIn(rung, blob)
        for lever in (C.SC_WRITER, C.SC_OUR_CODE, "owner_polled_adapters",
                      "silent_leg_feed"):
            self.assertIn(lever, blob)

    def test_report_says_unmeasured_when_it_is(self):
        lines = C.format_report(_measure(rec_doc=_rec(ceiling=25)))
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in x for x in lines))

    def test_report_distinguishes_an_absent_section_from_an_unmeasured_control(self):
        """Три исхода у контроля, не два (инв. #17).

        «Секции нет вовсе» (прибор отказал раньше, чем до неё дошёл) и «секция есть, а
        замера в ней нет» — разные состояния мира и разные починки. Подстановка `or {}`
        склеила бы их, и отчёт сказал бы «НЕ ИЗМЕРЕН» там, где контроль вообще не
        запускался.
        """
        refused = _measure(rec_doc=_rec(ceiling=25))       # отказ ДО обеих секций
        self.assertNotIn("route_parity", refused)
        self.assertNotIn("material_corroboration", refused)
        absent = "\n".join(C.format_report(refused))
        self.assertIn("секции нет", absent)

        # А теперь секция ЕСТЬ, но замера в ней нет — формулировка обязана отличаться.
        s = _sldp()
        s["per_leg"][0].pop("writer_lever_floor_without_leg")
        present = _measure(sldp_doc=s)
        self.assertIn("route_parity", present)
        blob = "\n".join(C.format_report(present))
        self.assertIn("НЕ ИЗМЕРЕН", blob)
        self.assertNotIn("секции нет — прибор до неё не дошёл\n   подтверждение", blob)

    def test_report_never_prints_a_criterion_value(self):
        blob = "\n".join(C.format_report(_measure()))
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", blob)
        self.assertIn("ADR-300", blob)


class TestNeighboursCalledByModuleReference(unittest.TestCase):
    """Соседи зовутся по ССЫЛКЕ НА МОДУЛЬ, иначе подмена правила прошла бы молча."""

    def test_swapping_the_module_attribute_is_observed(self):
        # Связанное при импорте имя есть СНИМОК функции: подменив модуль, мы обязаны
        # увидеть другой ответ. Не увидели — прибор держит устаревшую копию соседа.
        class Swapped:
            @staticmethod
            def measure(*a, **k):
                return _rec(ceiling=25)

        real = C._rec
        try:
            C._rec = Swapped
            doc = C.measure(_DATA, now=_NOW, sldp_doc=_sldp(), mat_doc=_mat())
        finally:
            C._rec = real
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertEqual(C.measure(_DATA, now=_NOW, rec_doc=_rec(), sldp_doc=_sldp(),
                                   mat_doc=_mat())["status"], C.STATUS_CRITICAL)


class TestWiring(unittest.TestCase):
    """Проводка — СТРУКТУРНАЯ и ПОВЕДЕНЧЕСКАЯ, не по подстроке.

    Тест проводки по подстроке переживает ЛЮБОЕ расплетение: строка остаётся в файле,
    пока её кто-нибудь не сотрёт, а звать прибор бегун уже перестал. Поэтому имя ступени
    спрашивается у самого бегуна, а ветка отрисовки проверяется ВЫЗОВОМ.

    Урок ADR-376 отдельно: объявления ступени НЕДОСТАТОЧНО — объявленная ступень не
    звалась вовсе, и артефакт не рождался молча. Вызов в ``main()`` проверяется по AST.

    Дом артефакта — ДВЕ записи манифеста: ``produces`` паспорта агента И ``artifacts[]``.
    Парити-тест краснеет только на второй, поэтому первая проверяется здесь.
    """

    ARTIFACT = C.OUTPUT_FILENAME
    STAGE_KEY = "criterion_population_floor"

    @staticmethod
    def _repo_root():
        return Path(C.__file__).resolve().parents[2]

    def test_the_census_runner_actually_calls_this_instrument(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn(self.STAGE_KEY, findings_bridge.CENSUS_STAGE)

    def test_the_artifact_is_declared_among_the_runners_products(self):
        from spa_core.monitoring import findings_bridge
        self.assertIn(f"data/{self.ARTIFACT}", findings_bridge.PRODUCES)

    def test_the_stage_passport_names_module_and_artifact(self):
        from spa_core.monitoring import findings_bridge
        self.assertEqual(
            findings_bridge.CENSUS_PRODUCT[self.STAGE_KEY],
            {"module": f"spa_core/monitoring/{self.STAGE_KEY}.py",
             "artifact": f"data/{self.ARTIFACT}"})

    def test_main_really_calls_run_and_not_only_declares_the_stage(self):
        """Урок ADR-376: объявленная ступень может не зваться ВООБЩЕ.

        Ищется по AST вызов ``<модуль>.run(...)``, а не упоминание имени: имя стои́т и
        в трёх объявлениях выше, и подстрочный поиск был бы зелёным при снятом вызове.
        """
        import ast
        from spa_core.monitoring import findings_bridge
        tree = ast.parse(Path(findings_bridge.__file__).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
                 and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == self.STAGE_KEY]
        self.assertEqual(len(calls), 1,
                         f"вызовов {self.STAGE_KEY}.run() в бегуне: {len(calls)}")

    def _office(self):
        import importlib.util
        script = self._repo_root() / "scripts" / "consume_office_reports.py"
        spec = importlib.util.spec_from_file_location("_office_for_g13", script)
        office = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(office)
        return office

    def test_the_office_step_requires_the_ladder_and_the_queue(self):
        """Лестница и очередь обязательны НАРАВНЕ с ответом, а не примечанием.

        Артефакт с одной долей подал бы её как план работ — ровно тот дефект, ради
        которого заказ #599 и оставлен.
        """
        required = self._office()._READ_SCHEMA[self.ARTIFACT]
        for key in ("ladder", "repair_queue", "route_parity", "answer"):
            self.assertIn(key, required)

    def test_the_office_step_knows_who_produces_the_artifact(self):
        self.assertEqual(self._office()._PRODUCER[self.ARTIFACT],
                         f"spa_core/monitoring/{self.STAGE_KEY}.py")

    def test_the_office_step_renders_the_instruments_own_lines(self):
        """Ветка отрисовки проверяется ВЫЗОВОМ — иначе отчёт молча онемеет.

        Важно не «строка похожа», а «печатает ИМЕННО форматтер прибора»: generic-ветка
        шага 0-офис тоже что-нибудь напечатает, и отличить её по виду строки нельзя.
        """
        office = self._office()
        doc = _measure()
        lines = [x for x in office._summarize_json(f"data/{self.ARTIFACT}", doc,
                                                   now=_NOW) if x.strip()]
        mine = [x for x in C.format_report(doc) if x.strip()]
        self.assertTrue(mine, "форматтер не дал ни строки — сравнивать было бы не с чем")
        self.assertEqual(lines[-len(mine):], mine)

    def _manifest(self):
        import json
        return json.loads((self._repo_root() / "architecture" / "manifest.json")
                          .read_text(encoding="utf-8"))

    def test_the_manifest_declares_the_artifact_in_artifacts(self):
        rows = [a for a in self._manifest()["artifacts"]
                if a.get("path") == f"data/{self.ARTIFACT}"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "active")
        self.assertGreater(rows[0]["slo_hours"], 0)

    def test_the_producing_agents_passport_also_lists_it(self):
        # ВТОРАЯ запись дома артефакта. Без неё парити-тест манифеста молчит, а агент
        # не числит своим то, что производит.
        man = self._manifest()
        row = next(a for a in man["artifacts"] if a.get("path") == f"data/{self.ARTIFACT}")
        agent = next(g for g in man["agents"] if g.get("label") == row["producer"])
        self.assertIn(f"data/{self.ARTIFACT}",
                      [p.get("artifact") for p in (agent.get("produces") or [])])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestWhatTheBroadBatteryFound(unittest.TestCase):
    """Дыры приёмки, найденные батареей НАСЛЕДНИКА (цикл #599, третий держатель).

    Батарея прежнего держателя брала координаты по СЦЕНАМ его рассуждения (двери отказа)
    и дала «21 из 21, выживших 0». Наследник взял координаты МЕХАНИЧЕСКИ — каждый оператор
    файла, побайтовой подменой, — и получил 93 координаты и 25 выживших. Часть выживших
    эквивалентны (см. ADR-381), а перечисленное ниже было настоящими дырами: число, которое
    печатается человеку, и путь, которым артефакт РОЖДАЕТСЯ, не спрашивал ни один тест.
    """

    def test_injected_clock_reaches_generated_at(self):
        # Иначе прибор штампует стенные часы, а инъекция часов — записка без проводки
        # (`.claude/rules/deployment.md`, причина `injected-clock` сверяется с кодом).
        doc = _measure()
        self.assertEqual(doc["generated_at"], _NOW.isoformat())

    def test_remainder_finding_states_the_days_of_our_code(self):
        # [ОСТАТОК] — то самое число, ради которого заказан G13: сколько работы подпёрто
        # материалом. Его не спрашивал ни один тест, и знак вычитания мутировал молча.
        doc = _measure()
        line = next(x for x in doc["findings"] if x.startswith("[ОСТАТОК]"))
        ours = doc["answer"]["our_code_floor"] - doc["answer"]["denominator_today"]
        self.assertEqual(ours, len(_OURS))
        self.assertIn(f"{len(_OURS)} дн. нашего кода", line)
        self.assertIn(f"{len(_OWNER)} дн. владельца", line)

    def test_queue_finding_quotes_the_writer_row_and_not_a_neighbour(self):
        doc = _measure()
        row = next(q for q in doc["repair_queue"] if q["lever"] == C.SC_WRITER)
        line = next(x for x in doc["findings"] if x.startswith("[ОЧЕРЕДЬ]"))
        self.assertIn(str(row["days_published"]), line)
        self.assertIn(str(row["days_with_material"]), line)

    def test_owner_row_rests_on_the_intersection_not_the_union(self):
        # Объединение записало бы рычагу владельца ЧУЖИЕ дни без материала и раздуло бы
        # его цену; пересечение — ровно те, что и без материала, и его.
        doc = _measure()
        row = next(q for q in doc["repair_queue"] if q["lever"] == "owner_polled_adapters")
        self.assertEqual(row["days_resting_on_absent_material"], [])
        self.assertEqual(row["day_list_with_material"], list(_OWNER))

    def test_corroboration_compares_only_days_shared_with_the_population(self):
        # У второго производителя своё население; объединение заставило бы прибор судить
        # о днях, которых в нашем населении нет вовсе.
        m = _mat()
        m["per_day"].append({"cycle_date": "2026-07-01", "verdict": "material"})
        doc = _measure(mat_doc=m)
        self.assertEqual(doc["material_corroboration"]["days_compared"], len(_RECOVERABLE))
        self.assertTrue(doc["material_corroboration"]["agreed"])

    def test_silent_legs_and_journal_days_travel_to_the_artifact(self):
        doc = _measure()
        self.assertEqual(doc["population"]["silent_legs"], ["pendle"])
        self.assertEqual(doc["population"]["journal_days"], 39)

    def test_counts_classify_warning_and_info_lines_too(self):
        doc = C.run(root=None, now=_NOW, write=False,
                    rec_doc=_rec(), sldp_doc=_sldp(), mat_doc=_mat())
        self.assertEqual(doc["counts"]["critical"], 1)
        self.assertGreaterEqual(doc["counts"]["warn"], 1)
        self.assertGreaterEqual(doc["counts"]["info"], 1)

    def test_report_prints_the_findings_and_not_only_the_ladder(self):
        doc = _measure()
        text = "\n".join(C.format_report(doc))
        for line in doc["findings"]:
            self.assertIn(line, text)

    def test_run_writes_the_artifact_under_the_GIVEN_root(self):
        # Мост зовёт run(root=...); если root игнорируется, артефакт рождается не там,
        # и «файла нет» читалось бы как «производитель молчал».
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            C.run(root=tmp, now=_NOW, rec_doc=_rec(), sldp_doc=_sldp(), mat_doc=_mat())
            out = Path(tmp) / "data" / C.OUTPUT_FILENAME
            self.assertTrue(out.exists(), "артефакт не рождён под переданным root")
            self.assertEqual(json.loads(out.read_text())["version"], C.VERSION)

    def test_run_with_write_false_writes_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            C.run(root=tmp, now=_NOW, write=False,
                  rec_doc=_rec(), sldp_doc=_sldp(), mat_doc=_mat())
            self.assertFalse((Path(tmp) / "data" / C.OUTPUT_FILENAME).exists())

    def test_main_writes_under_the_given_data_dir(self):
        # Пустой каталог ⇒ соседей нет ⇒ НЕ ИЗМЕРЕНО и код возврата 1 (инв. #17:
        # отсутствие наблюдения обязано быть отличимо от успеха). Артефакт при этом
        # ОБЯЗАН родиться: отказ — тоже результат, и он записывается.
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rc = C.main(["--data-dir", tmp])
            self.assertEqual(rc, 1)
            out = Path(tmp) / C.OUTPUT_FILENAME
            self.assertTrue(out.exists(), "отказ не записан — «не измерено» пропало молча")
            self.assertEqual(json.loads(out.read_text())["status"], C.STATUS_UNMEASURED)

    def test_main_without_data_dir_resolves_one_and_does_not_crash(self):
        # Разрешение каталога по умолчанию исполняется ТОЛЬКО когда --data-dir не передан;
        # с --no-write оно проверяется, ничего не записывая.
        import os as _os
        saved = _os.environ.pop("SPA_DATA_DIR", None)
        try:
            # Предмет — что каталог РАЗРЕШАЕТСЯ без исключения; каким окажется вердикт,
            # зависит от дерева, поэтому закреплён не он, а множество допустимых кодов.
            self.assertIn(C.main(["--no-write"]), (0, 1))
        finally:
            if saved is not None:
                _os.environ["SPA_DATA_DIR"] = saved

    def test_remainder_finding_also_states_the_material_floor_share(self):
        # «4 дн. из 8» — вторая половина того же ответа; без неё знак вычитания
        # material_floor мутировал молча, а это и есть заголовочное число заказа.
        doc = _measure()
        line = next(x for x in doc["findings"] if x.startswith("[ОСТАТОК]"))
        expected = doc["answer"]["material_floor"] - doc["answer"]["denominator_today"]
        self.assertEqual(expected, len(_OURS) + len(_OWNER))
        self.assertIn(f"{expected} дн. из {len(_RECOVERABLE)} восстановимых", line)

    def test_no_disagreement_means_no_disagreement_line(self):
        # Иначе прибор печатает «[РАСХОЖДЕНИЕ] ... 0 дн.» на согласии — ложная тревога
        # там, где второй производитель как раз ПОДТВЕРДИЛ.
        doc = _measure()
        self.assertTrue(doc["material_corroboration"]["agreed"])
        self.assertEqual([x for x in doc["findings"] if x.startswith("[РАСХОЖДЕНИЕ]")], [])

    def test_counts_are_exact_not_merely_nonzero(self):
        doc = C.run(root=None, now=_NOW, write=False,
                    rec_doc=_rec(), sldp_doc=_sldp(), mat_doc=_mat())
        f = doc["findings"]
        self.assertEqual(doc["counts"]["critical"],
                         sum(1 for x in f if x.startswith("[CRITICAL]")))
        self.assertEqual(doc["counts"]["warn"],
                         sum(1 for x in f if x.startswith(("[ЦЕНА]", "[ОЧЕРЕДЬ]",
                                                           "[РАСХОЖДЕНИЕ]"))))
        self.assertEqual(doc["counts"]["warn"], 2)

    def test_empty_side_of_a_population_split_prints_a_dash_not_brackets(self):
        # Отказ читает человек: «[]» вместо «—» превращает названную сторону в мусор.
        rec = _rec(recoverable=_RECOVERABLE + ["2026-07-04"])
        doc = _measure(rec_doc=rec)
        self.assertEqual(doc["status"], C.STATUS_UNMEASURED)
        self.assertIn("только у потолочного ['2026-07-04']", doc["unmeasured_reason"])
        self.assertIn("только у прибора пола —", doc["unmeasured_reason"])

    def test_queue_finding_prints_a_dash_when_no_day_has_material(self):
        # Ни один день строки писателя не подпёрт материалом. Пол соседа обязан быть
        # согласован со сценарием, иначе сработает контроль маршрута — и справедливо.
        rec = _rec(writer_added=list(_SILENT))
        doc = _measure(rec_doc=rec, sldp_doc=_sldp(floor=len(_TODAY)))
        line = next(x for x in doc["findings"] if x.startswith("[ОЧЕРЕДЬ]"))
        self.assertIn("(—)", line)

    def test_the_clock_is_keyword_only(self):
        # `now` позиционным аргументом — это молча ДРУГОЙ параметр у соседей по ряду;
        # ключевой-только маркер здесь часть договора, а не оформление.
        with self.assertRaises(TypeError):
            C.measure(_DATA, _NOW)
