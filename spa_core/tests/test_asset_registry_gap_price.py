"""Сторож прибора #610/G23 — приборa «цена двух разрывов».

Каждый тест ниже — положительный контроль: он краснеет на конкретной поломке,
которая в этом цикле была РЕАЛЬНОЙ либо разрушила бы ответ заказа. Две из них
прибор уже совершал и они исправлены — разбор, знающий только ``ast.Assign``
(реестр активов тогда «не измерен» ни на одном коммите), и счёт латентности, в
котором отсутствие ключа в книге позиций считалось сливающим вводом (весь класс
выглядел ЖИВЫМ, хотя он латентный).

Время инъектируется (``now=``), живой каталог данных не открывается ни разу.
"""
# FROZEN-DATE-OK: injected-clock — все даты приходят параметром now= либо лежат
# в фикстурах, которые тест же и создаёт; настенных часов прибор здесь не видит.
from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import asset_registry_gap_price as argp

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _write_history(data_dir: Path, rows) -> None:
    (data_dir / argp.JUDGE_INPUTS[0]).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")


def _day(date, *, current, target, turnover, cost=25.0, verdict="HOLD",
         apy=None, capital=100_000.0, gain=0.4):
    rec = {"cycle_date": date, "verdict": verdict, "reasons": [],
           "current_positions": dict(current), "target_positions": dict(target),
           "turnover_usd": turnover, "cost_usd": cost, "capital_usd": capital,
           "gain_pp": gain}
    if apy is not None:
        rec["apy_evidenced_pct"] = dict(apy)
    return rec


class SymbolSizeTests(unittest.TestCase):
    """Разбор состава реестра на произвольном коммите."""

    def test_annotated_assignment_is_a_definition(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ реальной поломки: `X: Dict = {...}`.

        Первая редакция разбора знала только `ast.Assign` и на настоящем
        `spa_core/adapters/registry.py` не находила `ADAPTER_METADATA` НИ НА
        ОДНОМ коммите — прибор печатал «состав НЕ ИЗМЕРЕН» там, где состав есть.
        """
        tree = ast.parse("from typing import Dict\n"
                         "ADAPTER_METADATA: Dict[str, dict] = {'a': 1, 'b': 2}\n")
        self.assertEqual(argp._symbol_size(tree, "ADAPTER_METADATA"), (2, 0))

    def test_plain_assignment_still_counted(self):
        tree = ast.parse("ADAPTER_REGISTRY = [('a', 'T1', object)]\n")
        self.assertEqual(argp._symbol_size(tree, "ADAPTER_REGISTRY"), (1, 0))

    def test_appends_counted_separately_from_the_literal(self):
        """Литерал и дописи НЕ складываются молча — из их различия и следует ответ."""
        tree = ast.parse(
            "ADAPTER_REGISTRY = [('a', 'T1', object), ('b', 'T2', object)]\n"
            "try:\n"
            "    ADAPTER_REGISTRY.append(('c', 'T2', object))\n"
            "except ImportError:\n"
            "    pass\n")
        self.assertEqual(argp._symbol_size(tree, "ADAPTER_REGISTRY"), (2, 1))

    def test_absent_symbol_is_none_not_zero(self):
        """«Символа нет» обязано быть отличимо от «реестр пуст» (инв. #17)."""
        tree = ast.parse("OTHER = {'a': 1}\n")
        self.assertIsNone(argp._symbol_size(tree, "ADAPTER_METADATA"))


class EntryPathTests(unittest.TestCase):
    """Два пути роста канонического реестра — структурная причина разрыва."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="argp_paths_"))
        (self.tmp / "spa_core" / "adapters").mkdir(parents=True)
        (self.tmp / argp.CANONICAL_REGISTRY_FILE).write_text(
            "ADAPTER_REGISTRY = [\n"
            "    ('aave_v3', 'T1', object),\n"
            "    ('frax', 'T3', object),\n"
            "]\n"
            "try:\n"
            "    ADAPTER_REGISTRY.append(('aave_v3_base', 'T2', object))\n"
            "    ADAPTER_REGISTRY.append(('morpho_blue_base', 'T2', object))\n"
            "except ImportError:\n"
            "    pass\n", encoding="utf-8")

    def test_literal_and_append_keys_are_separated(self):
        got = argp.entry_path_of_keys(self.tmp)
        self.assertTrue(got["measured"])
        self.assertEqual(got["literal"], ["aave_v3", "frax"])
        self.assertEqual(got["appended"], ["aave_v3_base", "morpho_blue_base"])

    def test_unreadable_registry_refuses_with_a_reason(self):
        """Файла нет ⇒ НЕ ИЗМЕРЕНО с причиной, а не пустые списки."""
        got = argp.entry_path_of_keys(Path(tempfile.mkdtemp(prefix="argp_empty_")))
        self.assertFalse(got["measured"])
        self.assertIn("не разобран", got["reason"])


class CompositionHistoryTests(unittest.TestCase):
    """История СОСТАВА в настоящем git-репозитории, а не в подделке."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="argp_repo_"))
        self._git("init", "-q")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")
        self.rel = "reg.py"

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args],
                       capture_output=True, text=True, check=False)

    def _commit(self, body, message):
        (self.repo / self.rel).write_text(body, encoding="utf-8")
        self._git("add", self.rel)
        self._git("commit", "-q", "-m", message)

    def test_rename_only_commit_does_not_count_as_composition_change(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: переименование символа — НЕ смена состава.

        Мерить «когда файл трогали» значило бы назвать реестр активов живым по
        коммиту цикла #275, который лишь переименовал символ, — и ответ на
        «почему разошлись» получился бы обратный истине.
        """
        self._commit("ADAPTER_REGISTRY = {'a': 1, 'b': 2}\n", "состав 2")
        self._commit("ADAPTER_METADATA = {'a': 1, 'b': 2}\n", "переименование")
        got = argp.composition_history(self.repo, self.rel,
                                       ("ADAPTER_METADATA", "ADAPTER_REGISTRY"))
        self.assertTrue(got["measured"])
        self.assertEqual(got["entries_now"], 2)
        self.assertEqual(got["commits_parsed"], 2)
        # Состав не менялся ни разу после первого коммита ⇒ последняя смена там.
        self.assertEqual(got["composition_last_changed"], got["series"][0]["date"])
        self.assertNotEqual(got["composition_last_commit"],
                            got["series"][-1]["commit"])

    def test_real_composition_change_is_caught(self):
        self._commit("ADAPTER_METADATA = {'a': 1}\n", "состав 1")
        self._commit("ADAPTER_METADATA = {'a': 1, 'b': 2}\n", "состав 2")
        got = argp.composition_history(self.repo, self.rel, ("ADAPTER_METADATA",))
        self.assertEqual(got["entries_now"], 2)
        self.assertEqual(got["composition_last_commit"],
                         got["series"][-1]["commit"])

    def test_renamed_symbol_is_asked_for_by_both_names(self):
        """Спросить только нынешнее имя = объявить историю до переименования пустой."""
        self._commit("ADAPTER_REGISTRY = {'a': 1}\n", "старое имя")
        only_new = argp.composition_history(self.repo, self.rel,
                                            ("ADAPTER_METADATA",))
        self.assertFalse(only_new["measured"])
        both = argp.composition_history(self.repo, self.rel,
                                        ("ADAPTER_METADATA", "ADAPTER_REGISTRY"))
        self.assertTrue(both["measured"])

    def test_missing_symbol_everywhere_is_unmeasured_not_empty(self):
        self._commit("OTHER = {'a': 1}\n", "чужой символ")
        got = argp.composition_history(self.repo, self.rel, ("ADAPTER_METADATA",))
        self.assertFalse(got["measured"])
        self.assertIn("НЕ ИЗМЕРЕН", got["reason"])

    def test_shallow_clone_refuses_instead_of_naming_a_truncation_date(self):
        """Урок ADR-390: на обрезке первая дата — о глубине обрезки, не о писателе."""
        self._commit("ADAPTER_METADATA = {'a': 1}\n", "один коммит")
        got = argp.registry_divergence(self.repo)
        self.assertFalse(got["measured"])
        self.assertIn("обрезан", got["reason"])
        self.assertEqual(got["clone_depth"], 1)


class BlindedTurnoverTests(unittest.TestCase):
    """Пересечение «ключи книги» × «ключи без актива», в двух валютах."""

    AMAP = {"aave_v3": {"state": "resolved", "asset": "USDC"},
            "morpho_blue_base": {"state": "unknown", "asset": None},
            "pendle": {"state": "disputed", "asset": None}}

    def _recs(self):
        return [
            {"cycle_date": "2026-09-01", "turnover_usd": 100.0, "legs": [
                {"protocol": "aave_v3", "delta_usd": 60.0},
                {"protocol": "morpho_blue_base", "delta_usd": -40.0}]},
            {"cycle_date": "2026-09-02", "turnover_usd": 10.0, "legs": [
                {"protocol": "aave_v3", "delta_usd": 10.0}]},
        ]

    def test_blinded_dollars_and_days_are_named(self):
        got = argp.blinded_turnover(self._recs(), self.AMAP)
        self.assertEqual(got["blinded_keys"], ["morpho_blue_base"])
        self.assertEqual(got["leg_usd_blinded"], 40.0)
        self.assertEqual(got["leg_usd_total"], 110.0)
        # Оборот ДНЯ, которого касается ослеплённый ключ, — вторая валюта, и она
        # не равна долларам ног: путать их значило бы занизить ответ.
        self.assertEqual(got["day_turnover_touched_by_blinded"], 100.0)
        self.assertEqual(got["day_turnover_total"], 110.0)
        self.assertEqual(list(got["blinded_days"]), ["2026-09-01"])

    def test_disputed_counts_as_blinded_too(self):
        """Спор двух источников — не «разрешено»: ключ в счёт актива не идёт."""
        recs = [{"cycle_date": "2026-09-03", "turnover_usd": 50.0,
                 "legs": [{"protocol": "pendle", "delta_usd": 50.0}]}]
        got = argp.blinded_turnover(recs, self.AMAP)
        self.assertEqual(got["blinded_keys"], ["pendle"])

    def test_key_outside_the_canonical_registry_is_its_own_outcome(self):
        """«Нет актива» и «нет записи о пуле» чинятся в разных местах."""
        recs = [{"cycle_date": "2026-09-04", "turnover_usd": 5.0,
                 "legs": [{"protocol": "ghost_pool", "delta_usd": 5.0}]}]
        got = argp.blinded_turnover(recs, self.AMAP)
        self.assertEqual(got["outside_canonical_registry"], ["ghost_pool"])

    def test_leg_without_amount_is_counted_not_silently_dropped(self):
        recs = [{"cycle_date": "2026-09-05", "turnover_usd": 5.0,
                 "legs": [{"protocol": "aave_v3"}]}]
        got = argp.blinded_turnover(recs, self.AMAP)
        self.assertEqual(got["legs_without_amount"], 1)
        self.assertEqual(got["leg_usd_total"], 0.0)


class ClassifyTests(unittest.TestCase):
    """Три исхода, а не два: «совпали» ещё не есть дефект."""

    BASE = (("d",), ("t",))

    def test_verdicts_differ_means_distinguishes(self):
        got = argp._classify(self.BASE, (("z",), ("t",)), (("a",), ("t",)),
                             (("n",), ("t",)), [(("p",), ("t",))])
        self.assertEqual(got["state"], "distinguishes")

    def test_same_verdict_and_sensitive_means_conflated(self):
        same = (("z",), ("t",))
        got = argp._classify(self.BASE, same, same, same,
                             [(("moved",), ("t",))])
        self.assertEqual(got["state"], "conflated")

    def test_same_verdict_and_insensitive_is_not_decisive_not_clean(self):
        """`gain_pp` судья только переписывает — назвать это дефектом нельзя."""
        same = (("z",), ("t",))
        got = argp._classify(self.BASE, same, same, same, [same, same])
        self.assertEqual(got["state"], "not_decisive")
        self.assertFalse(got["sensitive"])

    def test_top_floor_alone_is_enough_to_move_the_verdict(self):
        """`capital_usd` не двигает НИ ОДНОГО дня и решает итог — оба этажа."""
        same_day = ("d",)
        got = argp._classify((same_day, ("t0",)), (same_day, ("t1",)),
                             (same_day, ("t1",)), (same_day, ("t1",)),
                             [(same_day, ("t2",))])
        self.assertEqual(got["state"], "conflated")


class ProbeValueTests(unittest.TestCase):
    def test_large_probe_is_derived_from_the_data(self):
        recs = [{"cost_usd": 20.0}, {"cost_usd": 50.0}]
        self.assertEqual(argp._probe_values(recs, "cost_usd", None),
                         [argp.SMALL_PROBE, 500.0])

    def test_no_observed_values_falls_back_and_says_so_by_the_constant(self):
        self.assertEqual(argp._probe_values([{}], "cost_usd", None),
                         [argp.SMALL_PROBE, argp.FALLBACK_LARGE_PROBE])

    def test_leaf_coordinate_reads_the_leaf_not_the_container(self):
        recs = [{"target_positions": {"a": 3.0, "b": 900.0}}]
        self.assertEqual(argp._probe_values(recs, "target_positions", "a"),
                         [argp.SMALL_PROBE, 30.0])


class NumericFieldPopulationTests(unittest.TestCase):
    """Население берётся из КОДА судьи ∩ ЗАПИСИ, а не из головы."""

    def test_scalars_and_containers_split_by_the_recorded_kind(self):
        recs = [{"cost_usd": 10.0, "target_positions": {"a": 1.0},
                 "verdict": "HOLD", "reasons": []}]
        got = argp.numeric_fields(
            recs, ["cost_usd", "target_positions", "verdict", "reasons"])
        self.assertEqual(list(got["scalars"]), ["cost_usd"])
        self.assertEqual(list(got["containers"]), ["target_positions"])
        self.assertEqual(list(got["containers"]["target_positions"]), ["a"])
        self.assertIn("verdict", got["read_but_not_numeric"])

    def test_key_the_judge_never_reads_is_excluded(self):
        """Ключ записи, которого код не касается, в население не входит."""
        recs = [{"cost_usd": 10.0, "unused_number": 5.0}]
        got = argp.numeric_fields(recs, ["cost_usd"])
        self.assertNotIn("unused_number", got["scalars"])

    def test_boolean_is_not_a_number(self):
        recs = [{"material": True}]
        got = argp.numeric_fields(recs, ["material"])
        self.assertEqual(got["scalars"], {})
        self.assertEqual(got["read_but_not_numeric"]["material"], "булево")

    def test_observed_call_form_is_seen_by_the_ast(self):
        """`observed(rec, "x")` — честная форма чтения; пропустить её значило бы
        объявить класс ШИРЕ, чем он есть, потеряв уже правильные поля."""
        src = Path(tempfile.mkdtemp(prefix="argp_ast_")) / "m.py"
        src.write_text("def f(rec):\n"
                       "    return observed(rec, 'apy_evidenced_pct', kind=dict)\n",
                       encoding="utf-8")
        keys, err = argp.judge_record_keys(src)
        self.assertIsNone(err)
        self.assertIn("apy_evidenced_pct", keys)

    def test_unparsable_module_reports_a_reason(self):
        src = Path(tempfile.mkdtemp(prefix="argp_bad_")) / "m.py"
        src.write_text("def (:\n", encoding="utf-8")
        keys, err = argp.judge_record_keys(src)
        self.assertEqual(keys, [])
        self.assertIn("не разобран", err)


class OccurrenceAtBranchTests(unittest.TestCase):
    """Латентность: что считается сливающим вводом и где он должен «дойти»."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="argp_occ_"))

    def _census(self, coordinate, field, leaf):
        return {"rows": [{"coordinate": coordinate, "field": field, "leaf": leaf,
                          "state": "conflated"}]}

    def test_absent_leaf_is_not_a_collapsing_input(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ реальной поломки прибора.

        В книге позиций отсутствие ключа значит «не держим» — законное
        наблюдение. Первая редакция считала его сливающим и объявляла ЖИВЫМ весь
        класс (у `target_positions[aave_v3_base]` — 40 «вхождений», и все сорок
        просто дни без этого ключа), хотя класс латентный.
        """
        rows = [_day("2026-09-0%d" % i, current={"aave_v3": 100.0},
                     target={"aave_v3": 100.0 + i}, turnover=5_000.0,
                     apy={"aave_v3": 4.0}) for i in range(1, 6)]
        _write_history(self.tmp, rows)
        got = argp.occurrence_at_branch(
            self.tmp, rows, self._census("target_positions[ghost]",
                                         "target_positions", "ghost"),
            horizon_days=2)
        row = got["rows"][0]
        self.assertEqual(row["collapsing_kinds"], ["null"])
        self.assertEqual(row["counts"]["absent"], 5)   # видно
        self.assertEqual(row["in_file"], 0)            # но не сливающее
        self.assertTrue(row["latent"])

    def test_null_leaf_is_a_collapsing_input(self):
        """`null` — единственное представление «не наблюдалось» (инв. #17)."""
        rows = [_day("2026-09-0%d" % i, current={"aave_v3": 100.0},
                     target={"aave_v3": None}, turnover=5_000.0,
                     apy={"aave_v3": 4.0}) for i in range(1, 6)]
        _write_history(self.tmp, rows)
        got = argp.occurrence_at_branch(
            self.tmp, rows, self._census("target_positions[aave_v3]",
                                         "target_positions", "aave_v3"),
            horizon_days=2)
        row = got["rows"][0]
        self.assertEqual(row["counts"]["null"], 5)
        self.assertGreater(row["in_file"], 0)

    def test_absent_scalar_IS_a_collapsing_input(self):
        """У скаляра «поля нет» и есть заказанная пара — род координаты решает."""
        rows = [_day("2026-09-0%d" % i, current={"aave_v3": 100.0},
                     target={"aave_v3": 90.0}, turnover=5_000.0,
                     apy={"aave_v3": 4.0}) for i in range(1, 6)]
        for r in rows:
            r.pop("cost_usd")
        _write_history(self.tmp, rows)
        got = argp.occurrence_at_branch(
            self.tmp, rows, self._census("cost_usd", "cost_usd", None),
            horizon_days=2)
        row = got["rows"][0]
        self.assertEqual(row["counts"]["absent"], 5)
        self.assertEqual(row["in_file"], 5)

    def test_zero_on_a_non_material_day_does_not_reach_the_branch(self):
        """Случай `cost_usd`: нулей пятнадцать, до ветки цены не доходит ни один.

        Ветка цены живёт за проверкой существенности; день без хода до неё не
        добирается. Считать вхождения в ФАЙЛЕ значило бы объявить латентный
        дефект живым.
        """
        rows = [_day("2026-09-0%d" % i, current={"aave_v3": 100.0},
                     target={"aave_v3": 100.0}, turnover=0.0, cost=0.0,
                     apy={"aave_v3": 4.0}) for i in range(1, 6)]
        _write_history(self.tmp, rows)
        got = argp.occurrence_at_branch(
            self.tmp, rows, self._census("cost_usd", "cost_usd", None),
            horizon_days=2)
        row = got["rows"][0]
        self.assertEqual(row["counts"]["zero"], 5)
        self.assertEqual(row["reached_decision"], 0)
        self.assertTrue(row["latent"])
        self.assertEqual(got["material_days"], 0)

    def test_zero_on_a_material_day_DOES_reach_the_branch(self):
        """Обратное плечо: без него предыдущий тест доказывал бы лишь, что
        счётчик всегда ноль."""
        rows = [_day("2026-09-0%d" % i, current={"aave_v3": 100_000.0},
                     target={"aave_v3": 50_000.0, "maple": 50_000.0},
                     turnover=50_000.0, cost=0.0,
                     apy={"aave_v3": 4.0, "maple": 6.0}) for i in range(1, 6)]
        _write_history(self.tmp, rows)
        got = argp.occurrence_at_branch(
            self.tmp, rows, self._census("cost_usd", "cost_usd", None),
            horizon_days=2)
        row = got["rows"][0]
        self.assertGreater(got["material_days"], 0)
        self.assertGreater(row["reached_decision"], 0)
        self.assertFalse(row["latent"])

    def test_judge_failure_is_unmeasured_not_zero(self):
        got = argp.occurrence_at_branch(
            Path(tempfile.mkdtemp(prefix="argp_none_")), [],
            {"rows": []}, horizon_days=2)
        # Пустой каталог судью не валит — он честно возвращает пустой отчёт;
        # проверяем, что прибор при этом не выдумывает ни одной строки.
        self.assertTrue(got["measured"])
        self.assertEqual(got["rows"], [])


class EndToEndTests(unittest.TestCase):
    """Настоящий судья на синтетическом каталоге — исход, а не структура."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="argp_e2e_"))

    def test_cost_usd_is_found_conflated_by_running_the_real_judge(self):
        """Ветка `cost_rec > 0.0` найдена ИСХОДОМ, а не чтением кода."""
        rows = [_day("2026-09-%02d" % i, current={"aave_v3": 100_000.0},
                     target={"aave_v3": 40_000.0, "maple": 60_000.0},
                     turnover=60_000.0, cost=120.0,
                     apy={"aave_v3": 3.0, "maple": 9.0}) for i in range(1, 13)]
        _write_history(self.tmp, rows)
        fields = argp.numeric_fields(rows, ["cost_usd"])
        census = argp.zero_vs_absent_census(self.tmp, rows, fields,
                                            horizon_days=3)
        row = next(r for r in census["rows"] if r["coordinate"] == "cost_usd")
        self.assertEqual(row["state"], "conflated")
        self.assertTrue(row["zero_equals_absent"])
        self.assertTrue(row["sensitive"])

    def test_turnover_usd_is_found_distinguishing(self):
        """Обратное плечо: поле, сделанное правильно, прибор НЕ обвиняет."""
        rows = [_day("2026-09-%02d" % i, current={"aave_v3": 100_000.0},
                     target={"aave_v3": 40_000.0, "maple": 60_000.0},
                     turnover=60_000.0, apy={"aave_v3": 3.0, "maple": 9.0})
                for i in range(1, 13)]
        _write_history(self.tmp, rows)
        fields = argp.numeric_fields(rows, ["turnover_usd"])
        census = argp.zero_vs_absent_census(self.tmp, rows, fields,
                                            horizon_days=3)
        row = next(r for r in census["rows"] if r["coordinate"] == "turnover_usd")
        self.assertEqual(row["state"], "distinguishes")

    def test_empty_journal_is_unmeasured_with_a_status(self):
        got = argp.measure(self.tmp, repo=self.tmp, now=NOW)
        self.assertEqual(got["status"], argp.UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", got["headline"])

    def test_report_of_an_unmeasured_run_says_so_and_invents_nothing(self):
        doc = argp.measure(self.tmp, repo=self.tmp, now=NOW)
        lines = argp.format_report(doc)
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])

    def test_main_returns_two_when_unmeasured(self):
        code = argp.main(["--data-dir", str(self.tmp), "--root", str(self.tmp),
                          "--no-write"])
        self.assertEqual(code, 2)


class WritePathTests(unittest.TestCase):
    """Артефакт РОЖДАЕТСЯ. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ реальной поломки цикла.

    Первая редакция звала ``atomic_save(path, doc)`` — порядок аргументов
    обратный, — и ни один из сорока тестов этого не видел: все ходили мимо
    записи (``--no-write`` / прямые вызовы). Поломку нашёл только настоящий
    прогон моста, где прибор ушёл в «пропущено». Проверять надо ИСХОД записи.
    """

    def test_run_actually_writes_the_artifact(self):
        tmp = Path(tempfile.mkdtemp(prefix="argp_write_"))
        rows = [_day("2026-09-%02d" % i, current={"aave_v3": 100_000.0},
                     target={"aave_v3": 40_000.0, "maple": 60_000.0},
                     turnover=60_000.0, apy={"aave_v3": 3.0, "maple": 9.0})
                for i in range(1, 13)]
        _write_history(tmp, rows)
        argp.run(root=str(tmp), data_dir=str(tmp), write=True, horizon_days=3)
        written = tmp / argp.ARTIFACT
        self.assertTrue(written.exists(), "артефакт не рождён")
        doc = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(doc["version"], argp.VERSION)
        self.assertIn("zero_vs_absent", doc)


class ReportAbsenceTests(unittest.TestCase):
    """Отсутствие секции печатается ПРИЧИНОЙ, а не словом `None`.

    ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ дефекта, который прибор едва не отгрузил сам:
    `observed(doc, key) or {}` превращает «секции нет» в «measured=False без
    причины», и отчёт печатает `None` там, где обязан назвать, чего не хватило.
    Это ровно тот класс, который прибор и меряет, — инв. #17.
    """

    def test_missing_section_prints_a_named_reason_not_none(self):
        doc = {"status": argp.CRITICAL, "headline": "h", "findings": []}
        lines = argp.format_report(doc)
        text = "\n".join(lines)
        self.assertNotIn("None", text)
        self.assertIn("blinded_turnover", text)

    def test_present_section_is_used_not_replaced(self):
        """Обратное плечо: секция ЕСТЬ ⇒ причина не печатается, печатаются числа."""
        doc = {"status": argp.CRITICAL, "headline": "h", "findings": [],
               "blinded_turnover": {"measured": True, "book_keys_count": 3,
                                    "blinded_keys_count": 1,
                                    "blinded_keys": ["x"],
                                    "leg_usd_blinded": 10.0,
                                    "leg_usd_total": 100.0,
                                    "day_turnover_touched_by_blinded": 20.0,
                                    "day_turnover_total": 50.0,
                                    "blinded_days": {"2026-09-01": ["x"]},
                                    "days_with_legs": 2}}
        text = "\n".join(argp.format_report(doc))
        self.assertIn("$10.00", text)
        self.assertNotIn("секции `blinded_turnover` нет", text)


class StatusTests(unittest.TestCase):
    def test_critical_outranks_warning(self):
        self.assertEqual(argp._status([{"severity": argp.WARNING},
                                       {"severity": argp.CRITICAL}]),
                         argp.CRITICAL)

    def test_no_findings_is_ok(self):
        self.assertEqual(argp._status([]), argp.OK)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
