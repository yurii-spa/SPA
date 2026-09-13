"""Сторожа прибора «чего РЕАЛЬНО стоит рычаг `writer_universe`» (заказ #596/G10).

Каждый тест — положительный контроль на дефект, который замер 13.09 изготовил бы,
будь правило написано иначе. Проверка, никогда не видевшая настоящей поломки, —
украшение (`.claude/rules/deployment.md`).

Главный из них — САМ ПРЕДМЕТ заказа. Четыре прибора подряд (G6→G9) объявляли класс
`writer_universe` самым дешёвым рычагом и оставляли его ПОТОЛКОМ, а читатель дважды
сделал из этого вывод «начинать с него». На живых данных 13.09 потолок оказался
ДОКАЗАННО ПУСТ на $100 000.00 из $195 000.00: ноге `pendle` в ряду не принадлежит
ни одной точки за всю историю накопителя, и строка отсечения по `universe` не
поднимет эти доллары ни при каком состоянии нашего кода.

Второй по важности — НАПРАВЛЕНИЕ подмены: «нет ключа у производителя ряда» и «ключ
есть, живой ставки не было» обязаны оставаться РАЗНЫМИ исходами (инв. #17). Слить их
значило бы выдать «не измерено» за наблюдение и отправить владельцу починку,
которой не требуется.

FROZEN-DATE-OK: injected-clock — якорь `_NOW` объявлен литералом и передаётся
прибору параметром ``now=``; прочие даты суть КЛЮЧИ-ДАТЫ фикстур (предмет замера, не
свежесть). Стенных часов ни один тест здесь не спрашивает.
"""
# FROZEN-DATE-OK: injected-clock — якорь `_NOW` объявлен литералом и передаётся
# прибору параметром ``now=``; прочие даты суть КЛЮЧИ-ДАТЫ фикстур (предмет замера,
# не свежесть). Стенных часов ни один тест здесь не спрашивает.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import writer_universe_lever_floor as mod

#: Якорь времени — ВХОД прибора, а не окружение: обе стороны закреплены, тест
#: бессмертен (порядок предпочтения №1, `.claude/rules/deployment.md`).
_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)

_DAY = "2026-09-06"
_F1 = "2026-09-07"
_F2 = "2026-09-08"
_WINDOW = ["2026-09-05", "2026-09-06", _F1, _F2, "2026-09-09"]


def _series(points: dict) -> dict:
    """Ряд накопителя: ``{ключ: [[дата, ставка], …]}``."""
    return {"generated_at": _NOW.isoformat(),
            "source": "apy_series_accumulator (daily cycle hook)",
            "series": {k: [[d, 4.0] for d in sorted(dates)]
                       for k, dates in points.items()}}


def _producer(keys) -> dict:
    """Вселенная производителя ряда — ключи ``adapter_status.json``."""
    return {"generated_at": _NOW.isoformat(),
            "adapters": {k: {"live_apy": None, "apy": 8.0} for k in keys}}


def _g7_doc(days) -> dict:
    """Ответ соседа #590 в той форме, в какой его читает прибор."""
    return {"status": "CRITICAL", "per_day": list(days),
            "twin_keys": {"measured": True, "pairs": {}}}


def _day(date, gross, legs) -> dict:
    """День соседа: ``legs`` = ``[(нога, [(форв.день, рычаг), …]), …]``."""
    return {"cycle_date": date, "unpriced_gross_usd": gross,
            "legs": [{"protocol": p,
                      "pairs": [{"forward_date": f, "remedy": r} for f, r in prs]}
                     for p, prs in legs]}


class _Fixture:
    """Одноразовый каталог данных: ряд, производитель и подменённый сосед #590."""

    def __init__(self, case: unittest.TestCase, *, series: dict, producer: dict,
                 g7: dict):
        self.tmp = TemporaryDirectory()
        case.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        if series is not None:
            (self.data / mod.SERIES_FILENAME).write_text(json.dumps(series))
        if producer is not None:
            (self.data / mod.PRODUCER_FILENAME).write_text(json.dumps(producer))
        real = mod._g7.measure
        mod._g7.measure = lambda *_a, **_k: g7
        case.addCleanup(lambda: setattr(mod._g7, "measure", real))

    def measure(self) -> dict:
        return mod.measure(self.data, now=_NOW)


class WriterUniverseLeverFloor(unittest.TestCase):

    # ── предмет заказа: потолок бывает ПУСТ ──────────────────────────────
    def test_leg_with_no_point_in_the_whole_series_is_proven_empty(self):
        """АВАРИЯ 13.09: `pendle` — потолок, который не поднимает НИЧЕГО.

        Ключ есть у производителя ряда, точек в ряду нет ни одной за всю историю
        накопителя. Объявить такой доллар «поднимаемым дешёвой строкой» значило бы
        отправить починку туда, где её нет.
        """
        fx = _Fixture(
            self,
            series=_series({"aave_v3": _WINDOW}),
            producer=_producer(["aave_v3", "pendle"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("pendle", [(_F1, "writer_universe"),
                                          (_F2, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["status"], mod.STATUS_CRITICAL)
        self.assertEqual(doc["answer"]["proven_empty_usd"], 20000.0)
        self.assertEqual(doc["answer"]["material_usd"], 0.0)
        self.assertEqual(doc["population"]["pair_outcomes"][mod.PAIR_NEVER_LIVE], 2)
        self.assertEqual(doc["per_day"][0]["verdict"], "proven_empty")

    def test_leg_with_points_on_every_forward_day_is_material(self):
        """Обратное плечо того же контроля: где материал есть — он назван материалом."""
        fx = _Fixture(
            self,
            series=_series({"aave_v3": _WINDOW}),
            producer=_producer(["aave_v3"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("aave_v3", [(_F1, "writer_universe"),
                                           (_F2, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["answer"]["material_usd"], 20000.0)
        self.assertEqual(doc["answer"]["proven_empty_usd"], 0.0)
        self.assertEqual(doc["status"], mod.STATUS_OK)
        self.assertEqual(doc["per_day"][0]["verdict"], "material")

    def test_key_present_but_day_missing_is_a_gap_not_a_missing_key(self):
        """Пропуск ОДНОГО дня — «фид молчал тогда», а не «ноги нет в ряду».

        Различие несёт адресата починки: `gap` говорит о фиде того дня, а
        `never_live` — о ноге целиком.
        """
        fx = _Fixture(
            self,
            series=_series({"aave_v3": [d for d in _WINDOW if d != _F1]}),
            producer=_producer(["aave_v3"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("aave_v3", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["population"]["pair_outcomes"][mod.PAIR_GAP], 1)
        self.assertEqual(doc["population"]["pair_outcomes"][mod.PAIR_NEVER_LIVE], 0)
        self.assertEqual(doc["answer"]["proven_empty_usd"], 20000.0)

    # ── инв. #17: «не измерено» не есть ноль ─────────────────────────────
    def test_key_absent_from_the_producer_is_unmeasured_not_proven_empty(self):
        """Ключа нет и у производителя ⇒ сказать нечего.

        Прочитать это как «живой ставки не было» значило бы судить о ноге по
        чужой двери: производитель её просто не видел.
        """
        fx = _Fixture(
            self,
            series=_series({"aave_v3": _WINDOW}),
            producer=_producer(["aave_v3"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("sky_susds", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(
            doc["population"]["pair_outcomes"][mod.PAIR_OUTSIDE_PRODUCER], 1)
        self.assertEqual(doc["answer"]["proven_empty_usd"], 0.0)
        self.assertEqual(doc["answer"]["unmeasured_usd"], 20000.0)
        self.assertEqual(doc["status"], mod.STATUS_WARNING)
        self.assertEqual(doc["per_day"][0]["verdict"], "unmeasured")

    def test_forward_day_before_the_series_began_is_unmeasured_not_a_gap(self):
        """День до начала накопления НЕ читается как «фид молчал».

        Иначе прибор объявил бы потолок пустым на всей предыстории ряда — и был
        бы уверенно неправ.
        """
        fx = _Fixture(
            self,
            series=_series({"aave_v3": _WINDOW}),
            producer=_producer(["aave_v3"]),
            g7=_g7_doc([_day("2026-07-01", 20000.0,
                             [("aave_v3", [("2026-07-02", "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(
            doc["population"]["pair_outcomes"][mod.PAIR_OUTSIDE_WINDOW], 1)
        self.assertEqual(doc["answer"]["proven_empty_usd"], 0.0)
        self.assertEqual(doc["answer"]["unmeasured_usd"], 20000.0)

    def test_a_key_whose_series_row_is_unreadable_is_unmeasured_not_a_gap(self):
        """Ключ в ряду есть, разобранных точек НЕТ — это нечитаемая строка.

        Канонический разборщик оставляет такой ключ с ПУСТЫМ множеством намеренно,
        чтобы «протокола нет в ряду» и «ряд по протоколу нечитаем» не схлопнулись.
        Прочитать пустоту как «фид молчал каждый день» значило бы объявить потолок
        доказанно пустым на строке, которую не удалось разобрать, — ровно тот
        дефект, ради которого прибор и написан.
        """
        broken = _series({"aave_v3": _WINDOW})
        broken["series"]["aave_v3"] = [["не-дата", None], 42]   # ни одной точки
        broken["series"]["compound_v3"] = [[d, 4.0] for d in _WINDOW]
        fx = _Fixture(
            self, series=broken, producer=_producer(["aave_v3", "compound_v3"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("aave_v3", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(
            doc["population"]["pair_outcomes"][mod.PAIR_ROW_UNREADABLE], 1)
        self.assertEqual(doc["population"]["pair_outcomes"][mod.PAIR_GAP], 0)
        self.assertEqual(doc["answer"]["proven_empty_usd"], 0.0)
        self.assertEqual(doc["answer"]["unmeasured_usd"], 20000.0)

    def test_one_unmeasured_leg_keeps_the_whole_day_unmeasured(self):
        """Смешанный день: доказать ПУСТОТУ потолка нечем, пока хоть одна нога слепа."""
        fx = _Fixture(
            self,
            series=_series({"aave_v3": [d for d in _WINDOW if d != _F1]}),
            producer=_producer(["aave_v3"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("aave_v3", [(_F1, "writer_universe")]),
                              ("sky_susds", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["per_day"][0]["verdict"], "unmeasured")
        self.assertEqual(doc["answer"]["proven_empty_usd"], 0.0)
        self.assertEqual(len(doc["population"]["unmeasured_days"]), 1)

    # ── правило подъёма дня — ОДИН форвардный день, не объединение ───────
    def test_material_scattered_across_different_forward_days_does_not_raise_the_day(self):
        """АВАРИЯ-ДВОЙНИК ADR-371: объединение форвардных дней подняло бы день зря.

        У каждой ноги материал есть — но на РАЗНЫХ форвардных днях, и полного
        набора ставок не собирается ни на одном. Считать по объединению значило бы
        объявить день поднятым, хотя судья его не вернёт.
        """
        fx = _Fixture(
            self,
            series=_series({"aave_v3": [_F1], "compound_v3": [_F2]}),
            producer=_producer(["aave_v3", "compound_v3"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("aave_v3", [(_F1, "writer_universe"),
                                           (_F2, "writer_universe")]),
                              ("compound_v3", [(_F1, "writer_universe"),
                                               (_F2, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["per_day"][0]["forward_days_with_full_material"], [])
        self.assertEqual(doc["answer"]["material_usd"], 0.0)
        self.assertEqual(doc["answer"]["proven_empty_usd"], 20000.0)

    def test_a_single_forward_day_with_full_material_is_enough(self):
        """Обратное плечо: ОДНОГО общего дня довольно, и он назван поимённо."""
        fx = _Fixture(
            self,
            series=_series({"aave_v3": [_F1, _F2], "compound_v3": [_F2]}),
            producer=_producer(["aave_v3", "compound_v3"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("aave_v3", [(_F1, "writer_universe"),
                                           (_F2, "writer_universe")]),
                              ("compound_v3", [(_F1, "writer_universe"),
                                               (_F2, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["per_day"][0]["forward_days_with_full_material"], [_F2])
        self.assertEqual(doc["answer"]["material_usd"], 20000.0)

    # ── близнец: только ДОКАЗАННЫЙ, и никогда по виду имени ──────────────
    def test_proven_twin_carries_the_material_of_the_renamed_leg(self):
        """Переименованная нога ищет материал под именем близнеца.

        Родство берётся у сторожа второй записи (равные суммы, один-к-одному) —
        того же источника, что у соседа #590.
        """
        g7 = _g7_doc([_day(_DAY, 20000.0,
                           [("fluid_usdc", [(_F1, "writer_universe")])])])
        g7["twin_keys"]["pairs"] = {"fluid_usdc": ["fluid_fusdc"],
                                    "fluid_fusdc": ["fluid_usdc"]}
        fx = _Fixture(self, series=_series({"fluid_fusdc": _WINDOW}),
                      producer=_producer(["fluid_usdc", "fluid_fusdc"]), g7=g7)
        doc = fx.measure()
        self.assertEqual(doc["answer"]["material_usd"], 20000.0)
        self.assertEqual(doc["twin_pairs_used"], {"fluid_usdc": ["fluid_fusdc"]})

    def test_a_lookalike_name_is_not_a_twin(self):
        """`pendle` и `pendle_pt_susde` похожи — и родство их записью НЕ доказано.

        Догадка по виду имени стоила бы ровно половину ответа: она перевела бы
        $100 000.00 из «доказанно не поднимаемых» в «поднимаемые нашей строкой».
        """
        fx = _Fixture(
            self,
            series=_series({"pendle_pt_susde": _WINDOW}),
            producer=_producer(["pendle", "pendle_pt_susde"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("pendle", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["answer"]["proven_empty_usd"], 20000.0)
        self.assertEqual(doc["answer"]["material_usd"], 0.0)
        self.assertEqual(doc["twin_pairs_used"], {})

    # ── предмет узкий: чужие рычаги не считаются ─────────────────────────
    def test_other_remedies_are_outside_the_subject_and_do_not_enter_the_answer(self):
        """День без пар класса `writer_universe` не «поднят» и не «не поднят».

        Зачислить его в знаменатель значило бы раздуть предмет заказа чужими
        долларами и занизить долю пустого потолка.
        """
        fx = _Fixture(
            self,
            series=_series({"aave_v3": _WINDOW}),
            producer=_producer(["aave_v3", "spark_susds"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("spark_susds", [(_F1, "needs_polling")])]),
                        _day("2026-09-10", 40000.0,
                             [("aave_v3", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["answer"]["subject_usd"], 40000.0)
        self.assertEqual([d["cycle_date"] for d in doc["per_day"]], ["2026-09-10"])

    def test_no_subject_pairs_at_all_is_a_measured_zero_not_a_refusal(self):
        """Ноль пар предмета — ИЗМЕРЕННЫЙ ноль: соседи дали дни, класс не встретился."""
        fx = _Fixture(
            self,
            series=_series({"aave_v3": _WINDOW}),
            producer=_producer(["aave_v3", "spark_susds"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("spark_susds", [(_F1, "needs_polling")])])]))
        doc = fx.measure()
        self.assertEqual(doc["status"], mod.STATUS_OK)
        self.assertIsNone(doc["answer"])
        self.assertEqual(doc["population"]["subject_pairs"], 0)
        self.assertEqual(doc["counts"]["unchecked"], 0)

    # ── третий исход у входов ────────────────────────────────────────────
    def test_unreadable_series_is_unmeasured_and_never_a_clean_pass(self):
        fx = _Fixture(self, series=None, producer=_producer(["aave_v3"]),
                      g7=_g7_doc([_day(_DAY, 20000.0,
                                       [("aave_v3", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIn(mod.SERIES_FILENAME, doc["unmeasured_reason"])
        self.assertIsNone(doc["answer"])

    def test_unreadable_producer_is_unmeasured_and_never_a_clean_pass(self):
        fx = _Fixture(self, series=_series({"aave_v3": _WINDOW}), producer=None,
                      g7=_g7_doc([_day(_DAY, 20000.0,
                                       [("aave_v3", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertIn(mod.PRODUCER_FILENAME, doc["unmeasured_reason"])

    def test_neighbour_without_days_is_unmeasured_not_an_empty_class(self):
        fx = _Fixture(self, series=_series({"aave_v3": _WINDOW}),
                      producer=_producer(["aave_v3"]), g7=_g7_doc([]))
        doc = fx.measure()
        self.assertEqual(doc["status"], mod.STATUS_UNMEASURED)
        self.assertEqual(doc["findings"], [f"[НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}"])
        self.assertIn("НЕ «класс пуст»", doc["unmeasured_reason"])

    # ── форма чужого ответа: «ключа нет» ≠ «пусто» (инв. #17) ───────────
    def test_missing_per_day_key_is_named_apart_from_an_empty_list(self):
        """АВАРИЯ ФОРМЫ: `or []` слил бы отказ соседа с «дней слепоты нет».

        Первое означает, что сосед отказал или сменил форму; второе — что в
        истории таких дней нет вовсе. Обе ветки ведут в отказ, но причина у них
        разная, и читатель по ней решает, чинить соседа или радоваться.
        """
        common = dict(series=_series({"aave_v3": _WINDOW}),
                      producer=_producer(["aave_v3"]))
        no_key = {"status": "CRITICAL", "twin_keys": {"measured": True, "pairs": {}}}
        doc_missing = _Fixture(self, g7=no_key, **common).measure()
        doc_empty = _Fixture(self, g7=_g7_doc([]), **common).measure()
        self.assertEqual(doc_missing["status"], mod.STATUS_UNMEASURED)
        self.assertEqual(doc_empty["status"], mod.STATUS_UNMEASURED)
        self.assertIn("ключа `per_day` в ответе нет", doc_missing["unmeasured_reason"])
        self.assertIn("список дней ПУСТ", doc_empty["unmeasured_reason"])
        self.assertNotEqual(doc_missing["unmeasured_reason"],
                            doc_empty["unmeasured_reason"])

    def test_a_day_without_the_legs_key_becomes_unmeasured_and_does_not_vanish(self):
        """День без ключа `legs` обязан попасть в НЕИЗМЕРЕННЫЕ, а не исчезнуть.

        Молча пропущенный день неотличим от дня вне предмета — и знаменатель
        ответа тихо усох бы на его доллары.
        """
        broken = _day(_DAY, 20000.0, [])
        del broken["legs"]
        fx = _Fixture(
            self,
            series=_series({"aave_v3": _WINDOW}),
            producer=_producer(["aave_v3"]),
            g7=_g7_doc([broken,
                        _day("2026-09-10", 40000.0,
                             [("aave_v3", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        named = [b["cycle_date"] for b in doc["population"]["unmeasured_days"]]
        self.assertIn(_DAY, named)
        self.assertIn("нет ключа `legs`",
                      " ".join(b["reason"] for b in doc["population"]["unmeasured_days"]))
        self.assertEqual(doc["answer"]["subject_usd"], 40000.0)
        # Счёт измеренных дней берётся ПО ВЕРДИКТУ. Вычитание отказов из `per_day`
        # ушло бы в ноль (а при двух отказах — в минус): день, отвергнутый по
        # ФОРМЕ, в `per_day` не попадает вовсе, и вычесть его оттуда нельзя.
        self.assertEqual(doc["population"]["measured_days"], 1)
        self.assertEqual(doc["population"]["days_with_subject"], 1)

    def test_twins_not_measured_is_recorded_apart_from_twins_not_found(self):
        """«Сторож близнецов отказал» ≠ «близнецов нет».

        Различие меняет ответ: при отказе сторожа переименованная нога уедет в
        `never_live` по ЧУЖОМУ отказу, а не по наблюдению, и доллар будет
        объявлен доказанно не поднимаемым без единого доказательства.
        """
        common = dict(series=_series({"fluid_fusdc": _WINDOW}),
                      producer=_producer(["fluid_usdc", "fluid_fusdc"]))
        refused = _g7_doc([_day(_DAY, 20000.0,
                                [("fluid_usdc", [(_F1, "writer_universe")])])])
        refused["twin_keys"] = {"measured": False,
                                "reason": "сторож второй записи отказал"}
        found_none = _g7_doc([_day(_DAY, 20000.0,
                                   [("fluid_usdc", [(_F1, "writer_universe")])])])
        doc_refused = _Fixture(self, g7=refused, **common).measure()
        doc_none = _Fixture(self, g7=found_none, **common).measure()
        self.assertFalse(doc_refused["twins_measured"])
        self.assertTrue(doc_none["twins_measured"])
        # оба уедут в `never_live` — и именно поэтому род отказа обязан быть
        # записан: иначе вердикт «доказанно пуст» неотличим от «не проверяли»
        self.assertEqual(doc_refused["answer"]["proven_empty_usd"], 20000.0)
        self.assertEqual(doc_none["answer"]["proven_empty_usd"], 20000.0)

    # ── проводка: `run` даёт ступени ту форму, которую она ждёт ──────────
    def test_run_writes_the_artifact_and_counts_unmeasured_separately(self):
        """Счётчик `unchecked` обязан жить ОТДЕЛЬНО от нулей (инв. #17)."""
        fx = _Fixture(self, series=None, producer=_producer(["aave_v3"]),
                      g7=_g7_doc([_day(_DAY, 20000.0,
                                       [("aave_v3", [(_F1, "writer_universe")])])]))
        root = Path(fx.tmp.name).parent / f"root-{Path(fx.tmp.name).name}"
        (root / "data").mkdir(parents=True, exist_ok=True)
        for name in (mod.PRODUCER_FILENAME,):
            (root / "data" / name).write_text(
                (fx.data / name).read_text())
        doc = mod.run(root=str(root), now=_NOW)
        self.assertEqual(doc["overall"], mod.STATUS_UNMEASURED)
        # 2 = сам вердикт «не измерено» + названная строка причины. Важно здесь
        # не число, а то, что счётчик НЕ нулевой при нулевых critical/warn:
        # растворив «не измерено» в нулях, ступень сделала бы молчание прибора
        # неотличимым от чистого прогона (инв. #17).
        self.assertEqual(doc["counts"]["unchecked"], 2)
        self.assertEqual(doc["counts"]["critical"], 0)
        self.assertEqual(doc["counts"]["warn"], 0)
        self.assertTrue((root / "data" / mod.OUTPUT_FILENAME).exists())
        written = json.loads((root / "data" / mod.OUTPUT_FILENAME).read_text())
        self.assertEqual(written["status"], mod.STATUS_UNMEASURED)

    def test_the_artifact_carries_the_limits_of_its_own_claim(self):
        """Границы утверждения — В АРТЕФАКТ: читатель отчёта шапку модуля не открывает."""
        fx = _Fixture(
            self,
            series=_series({"aave_v3": _WINDOW}),
            producer=_producer(["aave_v3"]),
            g7=_g7_doc([_day(_DAY, 20000.0,
                             [("aave_v3", [(_F1, "writer_universe")])])]))
        doc = fx.measure()
        self.assertTrue(doc["what_it_does_not_prove"])
        joined = " ".join(doc["what_it_does_not_prove"])
        self.assertIn("провенанс", joined)
        self.assertIn("[СТАТУС ЧИСЛА]",
                      " ".join(x[:16] for x in doc["findings"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
