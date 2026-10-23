"""Положительные контроли переписи «цена пересъёмки описания» (ADR-794, заказ G793 п. 1).

Каждый тест — ВОПРОС, на который прибор обязан отвечать ПО-РАЗНОМУ в двух сценах:
зелёный на одной сцене не доказывает ничего (`.claude/rules/acceptance.md`, п. 3).
Сцены — настоящие ленты (перехешированы кодом `HashLedger`), читает их НАСТОЯЩАЯ
читающая модель `research_factory.read`, а не заглушка: предмет прибора — ответ
модели, и подобие отвечало бы на другой вопрос.

# FROZEN-DATE-OK: injected-clock — якорь сцены ``ANCHOR`` литерал, и от него же
# вычислены ВСЕ отметки строк; момент замера приходит в прибор аргументом
# (``measure(..., now=NOW)``). Окно и сетку пересъёмки прибор отмеряет от САМОЙ
# СВЕЖЕЙ ЗАПИСИ ленты (``horizon``), а не от стенных часов, поэтому ни один
# вердикт не движется от календаря.
"""

from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import ledger_resnapshot_price_census as rpc
from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.research_factory import contract

ANCHOR = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
SPAN_DAYS = 6
LADDER = (1, 2, 3)
NOW = ANCHOR + dt.timedelta(days=SPAN_DAYS)

ONLY_SNAPSHOT = (rpc.Recipe("none", cadence_days=1),
                 rpc.Recipe("snapshot", cadence_days=1,
                            newest_kinds=("candidate_snapshot",)))


def _iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot(cid: str, nonce: int, at: dt.datetime) -> dict:
    return {"kind": "candidate_snapshot",
            "key": ["candidate_snapshot", cid, f"{cid}-{nonce}"],
            "payload": {"candidate": {"candidate_id": cid, "domain": "D",
                                      "admission_state": None}},
            "at": _iso(at)}


def _run_row(nonce: int, at: dt.datetime) -> dict:
    return {"kind": "run", "key": ["run", f"r{nonce}"], "payload": {"scanned": 3},
            "at": _iso(at)}


def scene_entries(*, refreshed: bool, candidates: int = 3) -> list:
    """Шесть суток ленты; ``refreshed`` — переснимались ли кандидаты каждый день.

    Сцена без пересъёмки — это ровно тот случай, ради которого написан прибор:
    описание кандидата лежит в ПЕРВОМ дне, и усечение по возрасту его съедает.
    """
    entries: list = []
    for day in range(SPAN_DAYS):
        at = ANCHOR + dt.timedelta(days=day)
        if day == 0 or refreshed:
            for i in range(candidates):
                entries.append(_snapshot(f"cand{i}", day, at + dt.timedelta(minutes=i)))
        entries.append(_run_row(day, at + dt.timedelta(hours=1)))
    return entries


def build_scene(root: Path, entries) -> Path:
    data = Path(root) / "data"
    lwd.rechain(entries, data)
    return data


def _row(doc: dict, recipe_id: str) -> dict:
    for row in doc.get("rows") or []:
        if row.get("recipe") == recipe_id:
            return row
    raise AssertionError(f"в отчёте нет строки рецепта {recipe_id}: "
                         f"{[r.get('recipe') for r in doc.get('rows') or []]}")


class TheCureIsMeasuredNotAssumed(unittest.TestCase):
    """Главная пара: лекарство открывает окно ровно там, где его не было."""

    def test_resnapshot_opens_a_window_that_the_raw_ledger_does_not_have(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            self.assertTrue(doc["measured"], doc.get("reason"))
            self.assertIsNone(_row(doc, "none")["safe_window_days"],
                              "без лекарства у ленты не должно быть окна — "
                              "иначе сравнивать не с чем")
            self.assertEqual(_row(doc, "snapshot")["safe_window_days"], 1,
                             "пересъёмка описания обязана открыть окно в такт")
            self.assertEqual(doc["cheapest_opener"], "snapshot")

    def test_a_ledger_that_already_refreshes_needs_no_cure(self):
        """Обратная сцена: описание и так переснимается ⇒ окно есть БЕЗ лекарства."""
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=True))
            doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            self.assertTrue(doc["measured"], doc.get("reason"))
            self.assertIsNotNone(_row(doc, "none")["safe_window_days"])
            kinds = {f["kind"] for f in doc["findings"]}
            self.assertIn(rpc.FINDING_BASELINE_DRIFTED, kinds,
                          "нулевой рецепт с окном обязан быть НАЗВАН: иначе "
                          "разница рецептов меряет не лекарство")


class ThePriceIsTheBytesTheWriterWouldAdd(unittest.TestCase):
    """Цена — ЗАМЕР на сцене, а не произведение в уме."""

    def test_the_price_is_positive_and_grows_as_the_cadence_shortens(self):
        daily = rpc.Recipe("daily", cadence_days=1,
                           newest_kinds=("candidate_snapshot",))
        rare = rpc.Recipe("rare", cadence_days=3,
                          newest_kinds=("candidate_snapshot",))
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            doc = rpc.measure(data, now=NOW, recipes=(daily, rare), windows=LADDER)
            self.assertTrue(doc["measured"], doc.get("reason"))
            fast, slow = _row(doc, "daily"), _row(doc, "rare")
            self.assertGreater(fast["added_mb_per_day"], 0.0)
            self.assertGreater(fast["added_mb_per_day"], slow["added_mb_per_day"],
                               "чаще писать не может стоить дешевле")
            self.assertLess(fast["safe_window_days"], slow["safe_window_days"],
                            "реже писать не может дать окно ýже")

    def test_the_zero_recipe_adds_nothing(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            self.assertEqual(_row(doc, "none")["added_mb_per_day"], 0.0)
            self.assertEqual(_row(doc, "none")["injected_entries"], 0)

    def test_the_steady_state_size_is_the_window_slice_not_a_guess(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            row = _row(doc, "snapshot")
            self.assertIsNotNone(row["steady_state_bytes"])
            self.assertLess(row["steady_state_bytes"], row["scene_bytes"],
                            "устаканившаяся лента не может быть не меньше сцены")
            self.assertIsNone(_row(doc, "none")["steady_state_bytes"],
                              "окна нет ⇒ размер устаканивания НЕ ИЗМЕРЕН, а не ноль")


class ACureThatMovesTheAnswerIsNotACure(unittest.TestCase):
    """Положительный контроль №2 — и именно он поймал ошибку цикла #916 на себе."""

    def test_repeating_history_rows_that_accumulate_is_reported_as_not_neutral(self):
        """Повтор записи, чьи строки НАКАПЛИВАЮТСЯ в ответе, сдвигает ответ."""
        entries = scene_entries(refreshed=False, candidates=1)
        at = ANCHOR + dt.timedelta(days=1)
        entries.append({"kind": "transition",
                        "key": ["transition", "cand0", None, "REJECTED", _iso(at)],
                        "payload": {"candidate_id": "cand0", "to_state": "REJECTED",
                                    "reason": "нет второго источника"},
                        "at": _iso(at)})
        entries.sort(key=lambda e: e["at"])
        noisy = rpc.Recipe("history", cadence_days=1, all_kinds=("transition",))
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), entries)
            doc = rpc.measure(data, now=NOW, recipes=(noisy,), windows=LADDER)
            self.assertTrue(doc["measured"], doc.get("reason"))
            self.assertIs(_row(doc, "history")["answer_neutral"], False,
                          "повтор накапливающихся строк обязан быть назван НЕ "
                          "нейтральным — иначе прибор рекомендует лекарство, "
                          "которое портит ответ")
            self.assertIn(rpc.FINDING_NOT_NEUTRAL,
                          {f["kind"] for f in doc["findings"]})
            self.assertIsNone(doc["cheapest_opener"],
                              "рецепт, сдвинувший ответ, не вправе стать "
                              "рекомендацией, даже открыв окно")

    def test_repeating_a_latest_wins_row_leaves_the_answer_untouched(self):
        """Обратная сцена: повтор описания НЕ накапливается — ответ тот же."""
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            self.assertIs(_row(doc, "snapshot")["answer_neutral"], True)
            self.assertEqual(_row(doc, "snapshot")["answer_drifted_leaves"], 0)
            self.assertNotIn(rpc.FINDING_NOT_NEUTRAL,
                             {f["kind"] for f in doc["findings"]})


class TheSceneIsTheSameLedger(unittest.TestCase):
    """Положительный контроль №1: построение сцены проверяется, а не предполагается."""

    def test_a_tampered_head_makes_the_whole_measurement_unmeasured(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            path = data / contract.DATA_SUBDIR / contract.LEDGER
            rows = [json.loads(line) for line in path.read_text().splitlines() if line]
            rows[-1]["entry_hash"] = "0" * 64
            path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
            doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            self.assertFalse(doc["measured"])
            self.assertEqual(doc["status"], rpc.STATUS_UNMEASURED)
            self.assertIn("вершину", doc["reason"])

    def test_the_injection_never_touches_the_source_directory(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            path = data / contract.DATA_SUBDIR / contract.LEDGER
            before = path.read_bytes()
            rpc.measure(data, now=NOW, recipes=rpc.RECIPES[:2], windows=LADDER)
            self.assertEqual(path.read_bytes(), before,
                             "прибор ADVISORY: живая лента не смеет измениться")


class ThirdOutcomeIsDistinguishable(unittest.TestCase):
    """Инв. #17: «не измерено» нигде не выдаётся за «измерено и равно нулю»."""

    def test_an_undeclared_identityless_list_refuses_before_any_recipe(self):
        """Та же дверь у нового прибора: мерить собственную адресацию он не вправе."""
        from unittest import mock

        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            good = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            self.assertTrue(good["measured"], good.get("reason"))
            with mock.patch.object(rpc.lwd, "ID_KEYS", ()):
                bad = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT,
                                  windows=LADDER)
            self.assertFalse(bad["measured"])
            self.assertEqual(bad["status"], rpc.STATUS_UNMEASURED)
            self.assertIn("без объявленной природы", bad["reason"])
            self.assertEqual(bad["rows"], [],
                             "отказ наступил ПОСЛЕ рецептов — цена считалась по "
                             "ответу, адресацию которого прибор не знает")

    def test_a_missing_ledger_is_unmeasured_not_a_clean_report(self):
        with TemporaryDirectory() as tmp:
            doc = rpc.measure(Path(tmp) / "nowhere", now=NOW)
            self.assertFalse(doc["measured"])
            self.assertEqual(doc["status"], rpc.STATUS_UNMEASURED)
            self.assertIn("ленты нет", doc["reason"])

    def test_an_unparsable_stamp_refuses_instead_of_guessing_the_grid(self):
        entries = scene_entries(refreshed=False)
        entries[2] = dict(entries[2], at="позавчера")
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), entries)
            doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            self.assertFalse(doc["measured"])
            self.assertIn("отметки не разобраны", doc["reason"])

    def test_a_ledger_shorter_than_the_ladder_is_unmeasured(self):
        entries = [_snapshot("cand0", 0, ANCHOR),
                   _run_row(0, ANCHOR + dt.timedelta(hours=1))]
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), entries)
            doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=(5,))
            self.assertFalse(doc["measured"])
            self.assertIn("короче наименьшего окна", doc["reason"])
            # Отказ обязан наступить ДО рецептов: пустая лестница, протащенная
            # внутрь, дала бы «ни один рецепт не измерен» — тот же `measured:
            # False`, но причина другая, и строки рецептов в отчёте были бы.
            self.assertEqual(doc["rows"], [],
                             "отказ наступил ПОСЛЕ рецептов — лестница пустой "
                             "протащилась внутрь")
            self.assertTrue(doc["reason"].startswith("охват ленты"),
                            f"причина обёрнута чужой: {doc['reason'][:80]}")

    def test_no_opener_is_a_finding_not_a_silent_clean_verdict(self):
        """Ни один рецепт не открыл окна ⇒ это НАЗВАНО, а не пустой отчёт."""
        useless = rpc.Recipe("useless", cadence_days=1, newest_kinds=("paper_mark",))
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            doc = rpc.measure(data, now=NOW, recipes=(useless,), windows=LADDER)
            self.assertTrue(doc["measured"], doc.get("reason"))
            self.assertIsNone(doc["cheapest_opener"])
            self.assertIn(rpc.FINDING_NO_RECIPE, {f["kind"] for f in doc["findings"]})
            self.assertEqual(doc["status"], rpc.STATUS_FINDINGS)

    def test_the_growth_rate_is_none_when_the_window_does_not_fit(self):
        entries = scene_entries(refreshed=False)
        stamps = [lwd._parse_at(e["at"]) for e in entries]
        self.assertIsNone(
            rpc.observed_growth_mb_per_day(entries, stamps, stamps[-1],
                                           window_days=30),
            "охвата не хватило ⇒ темп НЕ ИЗМЕРЕН, а не ноль")
        self.assertIsNotNone(
            rpc.observed_growth_mb_per_day(entries, stamps, stamps[-1], window_days=2))


class TheGridIsAnchoredToTheLedgerNotTheWallClock(unittest.TestCase):
    """Сетка пересъёмки меряется от ГОРИЗОНТА ленты — иначе вердикт движет календарь."""

    def test_the_verdict_does_not_move_when_the_measuring_moment_moves(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            early = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT, windows=LADDER)
            late = rpc.measure(data, now=NOW + dt.timedelta(days=400),
                               recipes=ONLY_SNAPSHOT, windows=LADDER)
            self.assertEqual(_row(early, "snapshot")["safe_window_days"],
                             _row(late, "snapshot")["safe_window_days"])
            self.assertEqual(_row(early, "snapshot")["added_mb_per_day"],
                             _row(late, "snapshot")["added_mb_per_day"])

    def test_the_freshest_resnapshot_is_exactly_one_cadence_old(self):
        """Сетка идёт назад от горизонта: писатель с тактом N не бывает свежее N."""
        entries = scene_entries(refreshed=False)
        stamps = [lwd._parse_at(e["at"]) for e in entries]
        rows = rpc.resnapshot_rows(entries, stamps,
                                   rpc.Recipe("r", cadence_days=2,
                                              newest_kinds=("candidate_snapshot",)),
                                   {"cand0", "cand1", "cand2"})
        scene, injected = rpc.build_scene_entries(entries, stamps, rows, 2,
                                                  stamps[-1], stamps[0])
        self.assertGreater(injected, 0)
        newest = max(lwd._parse_at(e["at"]) for e in scene
                     if e["kind"] == "candidate_snapshot")
        self.assertEqual(stamps[-1] - newest, dt.timedelta(days=2))


class TheTactIsDecidedByTheFile(unittest.TestCase):
    """Срок решает ФАЙЛ, а не расписание бегуна — и «внутри такта» ≠ «измерено»."""

    def test_within_the_tact_nothing_is_measured_and_nothing_is_written(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / rpc.ARTIFACT
            out.write_text(json.dumps({"generated_at": _iso(NOW), "measured": True}),
                           encoding="utf-8")
            before = out.read_bytes()
            res = rpc.run(data_dir=str(Path(tmp)), dest=str(out), if_due=True,
                          now=NOW + dt.timedelta(days=1))
            self.assertFalse(res["measured"])
            self.assertEqual(out.read_bytes(), before, "артефакт переписан внутри такта")

    def test_an_unreadable_stamp_means_measure_not_assume_fresh(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / rpc.ARTIFACT
            out.write_text("{не json", encoding="utf-8")
            due, why = rpc.measurement_due(out, now=NOW)
            self.assertTrue(due)
            self.assertIn("не прочитан", why)


class TheRecipePopulationIsClosed(unittest.TestCase):
    """Рецепт — ОБЪЯВЛЕНИЕ; неизвестное имя есть НЕ ИЗМЕРЕНО, а не пустой набор."""

    def test_an_unknown_recipe_name_refuses_loudly(self):
        with TemporaryDirectory() as tmp:
            build_scene(Path(tmp), scene_entries(refreshed=False))
            code = rpc.main(["--data-dir", str(Path(tmp) / "data"), "--no-write",
                             "--recipes", "выдуманный"])
            self.assertEqual(code, 2)

    def test_the_declared_recipes_grow_by_exactly_one_kind_each(self):
        """Соседние рецепты отличаются одним видом — иначе их разность не есть цена вида."""
        ladder = [r for r in rpc.RECIPES if r.cadence_days == 1]
        for before, after in zip(ladder, ladder[1:]):
            added = ((set(after.newest_kinds) | set(after.all_kinds))
                     - (set(before.newest_kinds) | set(before.all_kinds)))
            self.assertTrue(added, f"{after.id} не добавил ни одного вида к {before.id}")
            self.assertTrue(set(before.newest_kinds) <= set(after.newest_kinds),
                            f"{after.id} ПОТЕРЯЛ вид, объявленный в {before.id}")


class TheRowOfEveryRequestedRecipeReachesTheReport(unittest.TestCase):
    """Отказ модели на сцене рецепта — ТРЕТИЙ исход, а не исчезнувшая строка."""

    def test_a_model_failure_on_a_recipe_scene_leaves_an_unmeasured_row(self):
        from unittest import mock

        real = rpc.lwd.answer_leaves

        def only_the_live_scene_answers(data_dir, now, undeclared=None):
            #: Живая сцена отвечает, сцена РЕЦЕПТА — нет. Проверяется именно та
            #: ветка, которую мутация «проглотить отказ» и снимает: строка
            #: рецепта обязана доехать с `measured=False` и причиной.
            if "/r_" in str(data_dir):
                raise RuntimeError("модель не ответила на сцене рецепта")
            return real(data_dir, now, undeclared=undeclared)

        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            with mock.patch.object(rpc.lwd, "answer_leaves",
                                   side_effect=only_the_live_scene_answers):
                doc = rpc.measure(data, now=NOW, recipes=ONLY_SNAPSHOT,
                                  windows=LADDER)
            self.assertEqual({row["recipe"] for row in doc["rows"]},
                             {"none", "snapshot"},
                             "строка рецепта ИСЧЕЗЛА — отчёт выглядит полным, "
                             "не будучи полным")
            row = _row(doc, "snapshot")
            self.assertFalse(row["measured"])
            self.assertIn("читающая модель не ответила", row["reason"])


class ANonNeutralRecipeNeverBecomesTheRecommendation(unittest.TestCase):
    """Даже ОТКРЫВ окно, рецепт со сдвинутым ответом не вправе быть советом.

    Сцена построена с ПОДМЕНЁННЫМ оконным прибором намеренно: на настоящих
    лентах сдвиг ответа и отсутствие окна до сих пор ходили вместе (замер 23.10
    на живой ленте: оба ненейтральных рецепта окна не открыли), и импликация
    «ненейтральный ⇒ окна нет» НЕ ДОКАЗАНА. Снять фильтр, опираясь на то, что
    сцену не удалось построить, значило бы считать недоказанное верным.
    """

    def test_a_window_reported_for_a_non_neutral_recipe_is_not_an_opener(self):
        from unittest import mock

        entries = scene_entries(refreshed=False, candidates=1)
        at = ANCHOR + dt.timedelta(days=1)
        entries.append({"kind": "transition",
                        "key": ["transition", "cand0", None, "REJECTED", _iso(at)],
                        "payload": {"candidate_id": "cand0", "to_state": "REJECTED",
                                    "reason": "нет второго источника"},
                        "at": _iso(at)})
        entries.sort(key=lambda e: e["at"])
        noisy = rpc.Recipe("noisy", cadence_days=1,
                           newest_kinds=("candidate_snapshot",),
                           all_kinds=("transition",))
        window_says_yes = {"schema": lwd.VERSION, "measured": True,
                           "status": lwd.STATUS_CLEAN, "rows": [], "findings": [],
                           "safe_window_days": 1,
                           "one_day_dependent_share_pct": 0.0}
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), entries)
            with mock.patch.object(rpc.lwd, "measure",
                                   return_value=window_says_yes):
                doc = rpc.measure(data, now=NOW, recipes=(noisy,), windows=LADDER)
            row = _row(doc, "noisy")
            self.assertEqual(row["safe_window_days"], 1,
                             "сцена не воспроизвела предпосылку: окна нет, и "
                             "фильтр нейтральности этим тестом НЕ проверен")
            self.assertIs(row["answer_neutral"], False)
            self.assertIsNone(doc["cheapest_opener"],
                              "рецепт со сдвинутым ответом стал рекомендацией")

    def test_a_neutral_recipe_with_the_same_window_IS_an_opener(self):
        """Обратная сцена той же парой: нейтральный — советом становится."""
        from unittest import mock

        window_says_yes = {"schema": lwd.VERSION, "measured": True,
                           "status": lwd.STATUS_CLEAN, "rows": [], "findings": [],
                           "safe_window_days": 1,
                           "one_day_dependent_share_pct": 0.0}
        quiet = rpc.Recipe("quiet", cadence_days=1,
                           newest_kinds=("candidate_snapshot",))
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            with mock.patch.object(rpc.lwd, "measure",
                                   return_value=window_says_yes):
                doc = rpc.measure(data, now=NOW, recipes=(quiet,), windows=LADDER)
            self.assertIs(_row(doc, "quiet")["answer_neutral"], True)
            self.assertEqual(doc["cheapest_opener"], "quiet")


class ThePriceIsPaidOnlyForCandidatesTheAnswerKNOWS(unittest.TestCase):
    """Переснимать мёртвого кандидата — платить за того, кого в ответе нет."""

    def test_a_candidate_outside_the_live_set_is_not_resnapshotted(self):
        entries = scene_entries(refreshed=False, candidates=3)
        stamps = [lwd._parse_at(e["at"]) for e in entries]
        recipe = rpc.Recipe("r", cadence_days=1,
                            newest_kinds=("candidate_snapshot",))
        everyone = rpc.resnapshot_rows(entries, stamps, recipe,
                                       {"cand0", "cand1", "cand2"})
        two = rpc.resnapshot_rows(entries, stamps, recipe, {"cand0", "cand1"})
        self.assertEqual(len(everyone), 3)
        self.assertEqual(len(two), 2, "мёртвый кандидат попал в пересъёмку — "
                                      "цена завышена на того, кого нет в ответе")
        self.assertNotIn("cand2", {row["key"][1] for row in two})

    def test_an_empty_live_set_costs_nothing_and_injects_nothing(self):
        entries = scene_entries(refreshed=False)
        stamps = [lwd._parse_at(e["at"]) for e in entries]
        rows = rpc.resnapshot_rows(entries, stamps,
                                   rpc.Recipe("r", cadence_days=1,
                                              newest_kinds=("candidate_snapshot",)),
                                   set())
        self.assertEqual(rows, [])
        scene, injected = rpc.build_scene_entries(entries, stamps, rows, 1,
                                                  stamps[-1], stamps[0])
        self.assertEqual(injected, 0)
        self.assertEqual(scene, list(entries), "сцена без пересъёмки обязана быть "
                                               "той же лентой байт в байт")


class TheInjectionSitsAFTERTheRealRowOfTheSameMoment(unittest.TestCase):
    """Равная отметка: вставка идёт ПОСЛЕ живой записи, иначе подменяет ответ."""

    def test_an_injected_copy_never_overtakes_the_real_row_it_shares_a_stamp_with(self):
        entries = scene_entries(refreshed=False, candidates=1)
        stamps = [lwd._parse_at(e["at"]) for e in entries]
        horizon, first = stamps[-1], stamps[0]
        #: Сетка пересъёмки с таким тактом садится РОВНО на отметку живой записи
        #: (день 5 минус 1 сутки = день 4), и порядок между ними решает всё:
        #: читающая модель берёт ПОСЛЕДНЮЮ строку кандидата.
        marker = {"kind": "run", "key": ["run", "injected"],
                  "payload": {"scanned": 999}, "at": _iso(horizon)}
        scene, injected = rpc.build_scene_entries(entries, stamps, [marker], 1,
                                                  horizon, first)
        self.assertGreater(injected, 0)
        same_stamp = [e for e in scene
                      if lwd._parse_at(e["at"]) == horizon - dt.timedelta(days=1)]
        self.assertGreater(len(same_stamp), 1,
                           "сцена не воспроизвела предпосылку: равных отметок нет, "
                           "и порядок вставки этим тестом НЕ проверен")
        self.assertEqual(same_stamp[-1]["key"], ["run", "injected"],
                         "вставка обогнала живую запись того же мгновения — "
                         "последняя строка кандидата подменена")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
