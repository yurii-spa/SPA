"""Сторож переписи «порог сенсора против такта предмета» (заказ G146 п. 2, ADR-646).

Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ одного звена: он красен, если это
звено порвать, и называет звено в сообщении. Проверка, никогда не видевшая
настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Литеральных дат и номеров процессов здесь нет ПО ПОСТРОЕНИЮ: предмет прибора —
КОД и ОБЪЯВЛЕНИЯ, у него нет часов и нет возраста, поэтому ни фиксированная
дата, ни живость pid в сцену не входят.
"""

from __future__ import annotations

import ast
import json
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import sensor_tact_census as census


def _manifest(agents, artifacts=()):
    return {"schema_version": 1, "agents": list(agents),
            "artifacts": list(artifacts)}


def _agent(label, schedule, produces):
    return {"label": label, "schedule": schedule,
            "produces": [{"artifact": path, "slo_hours": slo}
                         for path, slo in produces]}


class TactIsAPropertyOfTheArtifact(unittest.TestCase):
    """ЗВЕНО: такт считается по ВСЕМ производителям, а не по одному.

    Авария, воспроизводимая здесь дословно: первая редакция прибора считала такт
    у ОДНОГО производителя и объявила находкой `data/deployment_acceptance.json`
    (`slo_hours=15` против суточного `calendar:20:00`). Тот же артефакт пишет
    второй агент в 08:00 — худший разрыв 12 ч, запас есть, находка ложная.
    """

    def test_two_daily_producers_halve_the_tact(self):
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.morning", "calendar:08:00", [("data/a.json", 15)]),
            _agent("com.spa.evening", "calendar:20:00", [("data/a.json", 15)]),
        ]))
        self.assertAlmostEqual(table["data/a.json"]["tact_hours"], 12.0,
                              msg="такт считается по ОДНОМУ производителю — "
                                  "ложная находка на двух писателях суток")
        rows = census.measure_declared(table)
        self.assertEqual({row["verdict"] for row in rows}, {"has_margin"})

    def test_one_daily_producer_is_a_whole_day(self):
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.daily", "calendar:08:00", [("data/a.json", 2)]),
        ]))
        self.assertAlmostEqual(table["data/a.json"]["tact_hours"], 24.0)
        row, = census.measure_declared(table)
        self.assertEqual(row["verdict"], "below_tact")

    def test_gap_is_measured_around_the_circle(self):
        """Два прогона в 08:00 и 09:00 дают разрыв 23 ч, а не 1 ч."""
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.a", "calendar:08:00", [("data/a.json", 2)]),
            _agent("com.spa.b", "calendar:09:00", [("data/a.json", 2)]),
        ]))
        self.assertAlmostEqual(table["data/a.json"]["tact_hours"], 23.0,
                              msg="разрыв меряется не по кругу — ночь выпала")

    def test_interval_and_calendar_take_the_minimum(self):
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.daily", "calendar:08:00", [("data/a.json", 2)]),
            _agent("com.spa.hourly", "interval:3600s", [("data/a.json", 2)]),
        ]))
        self.assertAlmostEqual(table["data/a.json"]["tact_hours"], 1.0,
                              msg="минимум границ не взят — часовой писатель "
                                  "не учтён")

    def test_weekly_schedule_is_a_week(self):
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.weekly", "calendar:wd1·09:00", [("data/a.json", 2)]),
        ]))
        self.assertAlmostEqual(table["data/a.json"]["tact_hours"], 168.0)

    def test_minute_schedule_is_an_hour(self):
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.min", "calendar:minute:7", [("data/a.json", 2)]),
        ]))
        self.assertAlmostEqual(table["data/a.json"]["tact_hours"], 1.0)


class TactlessProducerIsTheThirdOutcome(unittest.TestCase):
    """ЗВЕНО: нет такта ⇒ `tact_unknown` с причиной, а НЕ ноль и не «с запасом».

    Инв. #17: три исхода — измерено · измерено и равно нулю · не измерено —
    обязаны быть различимы. Такт `daemon`-а не равен нулю и не бесконечен: его
    НЕТ, и сравнивать порог не с чем.
    """

    def test_each_tactless_form_names_its_reason(self):
        for schedule, needle in (("daemon", "daemon"),
                                 ("manual", "manual"),
                                 ("event:watchpaths", "событийный"),
                                 (None, "не объявлено"),
                                 ("every other tuesday", "не разобрана")):
            with self.subTest(schedule=schedule):
                table = census.artifact_tacts(_manifest([
                    _agent("com.spa.x", schedule, [("data/a.json", 1)]),
                ]))
                self.assertIsNone(table["data/a.json"]["tact_hours"])
                row, = census.measure_declared(table)
                self.assertEqual(row["verdict"], "tact_unknown",
                                 msg=f"{schedule!r} выдан за измеренный такт")
                self.assertIn(needle, row["reason"],
                              msg="причина третьего исхода не названа")

    def test_missing_slo_is_not_a_zero_threshold(self):
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.x", "interval:3600s", [("data/a.json", None)]),
        ]))
        row, = census.measure_declared(table)
        self.assertEqual(row["verdict"], "unit_undeclared")
        self.assertNotEqual(row["verdict"], "below_tact",
                            msg="отсутствующий порог подставлен нулём")


class UnitIsDeclaredByTheName(unittest.TestCase):
    """ЗВЕНО: единица времени берётся у ИМЕНИ константы, а не у её величины.

    Урок ADR-645 (`_TS_UNIT`): производитель писал отметку в эпохе, читатель
    разбирал ISO, и возраст был «НЕ ИЗМЕРЕН» по построению. Здесь та же развилка:
    `2.0` одинаково правдоподобно как часы и как секунды.
    """

    def test_each_suffix_is_read(self):
        cases = {"X_SECONDS": 1 / 3600, "X_SEC": 1 / 3600, "X_S": 1 / 3600,
                 "X_MIN": 1 / 60, "X_MINUTES": 1 / 60, "X_HOURS": 1.0,
                 "X_H": 1.0, "X_DAYS": 24.0, "X_WEEKS": 168.0}
        for name, factor in cases.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(census.declared_unit_hours(name), factor,
                                       msg=f"суффикс {name} прочитан неверно")

    def test_longer_suffix_wins_over_shorter(self):
        self.assertAlmostEqual(census.declared_unit_hours("X_MINUTES"), 1 / 60,
                               msg="`_MINUTES` прочитан как `_S`")

    def test_a_name_without_a_unit_refuses(self):
        self.assertIsNone(census.declared_unit_hours("APY_FEED_STALE_CYCLES"),
                          msg="единица додумана по величине — порог в ЦИКЛАХ "
                              "выдан за часы")


class _CodeTree:
    """Одноразовое дерево: конституция + пакет с одним модулем."""

    def __init__(self, module_source: str, agents, artifacts=()):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "architecture").mkdir()
        (self.root / "architecture" / "manifest.json").write_text(
            json.dumps(_manifest(agents, artifacts)), encoding="utf-8")
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "sensor.py").write_text(
            textwrap.dedent(module_source), encoding="utf-8")

    def measure(self):
        manifest = census.load_constitution(self.root)
        table = census.artifact_tacts(manifest)
        rows = census.measure_in_code(self.root, table, code_roots=("pkg",))
        return table, rows

    def close(self):
        self._tmp.cleanup()


class ScopeIsResolvedLikePython(unittest.TestCase):
    """ЗВЕНО: имя разрешается в СВОЕЙ области, а не в общем словаре модуля.

    Авария, воспроизводимая здесь: первая редакция прибора собирала
    присваивания модуля обходом ВСЕГО дерева — то есть вместе с телами функций —
    и получала один namespace на файл. На `uptime_monitor.STALE_CYCLE_HOURS`
    исходом стал `subject_ambiguous`: к честному предмету
    (`paper_trading_status.json`) примешался литерал СОСЕДНЕЙ функции. Находка,
    ради которой прибор написан, пропала бы в третьем исходе — то есть
    выглядела бы как «не измерено», тише красной строки и потому опаснее её.

    Соседние функции здесь намеренно пользуются ОДНИМИ именами (`path`, `raw`,
    `age`): так написан и живой `uptime_monitor`, и именно это делает общий
    словарь модуля заразным.
    """

    SOURCE = '''
        STALE_HOURS = 2.0

        def judge_subject(data_dir):
            path = data_dir / "subject.json"
            raw = path.read_text()
            age = (now() - json.loads(raw)["ts"]) / 3600.0
            return age <= STALE_HOURS

        def judge_other(data_dir):
            path = data_dir / "other.json"
            raw = path.read_text()
            age = (now() - json.loads(raw)["ts"]) / 3600.0
            return age
    '''

    def test_a_neighbour_function_does_not_pollute_the_road(self):
        tree = _CodeTree(self.SOURCE, [
            _agent("com.spa.daily", "calendar:08:00", [("data/subject.json", 26)]),
            _agent("com.spa.other", "interval:600s", [("data/other.json", 1)]),
        ])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "STALE_HOURS"]
        self.assertEqual(row["subjects"], ["data/subject.json"],
                         msg="имена модуля собраны обходом всего дерева — "
                             "литерал соседней функции примешался в предмет")
        self.assertEqual(row["verdict"], "below_tact")

    def test_fallback_sees_only_assignments_made_OUTSIDE_functions(self):
        """Имя, взятое из глобальной области, не разрешается телом СОСЕДА.

        Это ЕДИНСТВЕННЫЙ вход, на котором отбор «присваивания вне функций»
        меняет вердикт: имя `stamp` локально не присваивают, поэтому дорога
        уходит в откат — и если откат собран обходом всего дерева, литерал
        соседней функции становится предметом сторожа. Ворот без своего
        входа снимается потом молча, поэтому вход назван здесь.
        """
        tree = _CodeTree('''
            STALE_HOURS = 2.0

            def judge(now):
                age = (now - stamp) / 3600.0
                return age <= STALE_HOURS

            def loader(data_dir):
                stamp = json.loads((data_dir / "other.json").read_text())["ts"]
                return stamp
        ''', [
            _agent("com.spa.daily", "calendar:08:00", [("data/subject.json", 26)]),
            _agent("com.spa.other", "interval:600s", [("data/other.json", 1)]),
        ])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "STALE_HOURS"]
        self.assertEqual(row["verdict"], "outside_population",
                         msg="откат собран обходом всего дерева — предметом "
                             "сторожа назначен литерал соседней функции")

    def test_module_level_namesake_loses_to_the_local_one(self):
        """Тёзка уровня модуля не виден там, где имя присваивают локально."""
        tree = _CodeTree('''
            STALE_HOURS = 2.0
            raw = "other.json"

            def judge(data_dir):
                raw = (data_dir / "subject.json").read_text()
                age = (now() - json.loads(raw)["ts"]) / 3600.0
                return age <= STALE_HOURS
        ''', [
            _agent("com.spa.daily", "calendar:08:00", [("data/subject.json", 26)]),
            _agent("com.spa.other", "interval:600s", [("data/other.json", 1)]),
        ])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "STALE_HOURS"]
        self.assertEqual(row["subjects"], ["data/subject.json"],
                         msg="модульный тёзка примешался к локальному имени — "
                             "область разрешается объединением, а не как в Python")

    def test_a_module_level_path_is_still_reachable(self):
        """Обратная сторона: модульная константа-путь дорогой ОСТАЁТСЯ."""
        tree = _CodeTree('''
            STALE_HOURS = 2.0
            SUBJECT = "subject.json"

            def judge(data_dir):
                raw = (data_dir / SUBJECT).read_text()
                age = (now() - json.loads(raw)["ts"]) / 3600.0
                return age <= STALE_HOURS
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/subject.json", 26)])])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "STALE_HOURS"]
        self.assertEqual(row["subjects"], ["data/subject.json"],
                         msg="откат к модульной области снят — настоящая "
                             "дорога через константу модуля потеряна")


class AContainerIsNotABinding(unittest.TestCase):
    """ЗВЕНО: словарь-результат привязкой НЕ является.

    Форма аварии 2026-08-04 (`.claude/rules/deployment.md`): `doc = {"ts": …}`
    рядом с `age_hours(doc)`. Считать «RHS поминает литерал» происхождением
    значило бы оправдать бомбу.
    """

    def test_a_dict_literal_on_the_road_does_not_bind_the_subject(self):
        """Дорога ИДЁТ через словарь — и всё равно привязкой он не является.

        Форма дословно та же, что у аварии: контейнер собран рядом с именем
        файла, а сравнивается поле контейнера. Спуск в словарь оправдал бы
        любую случайную близость литерала.
        """
        tree = _CodeTree('''
            STALE_HOURS = 2.0

            def judge(now):
                doc = {"ts": 0, "file": "subject.json"}
                age = (now - doc["ts"]) / 3600.0
                return age <= STALE_HOURS
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/subject.json", 26)])])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "STALE_HOURS"]
        self.assertEqual(row["verdict"], "outside_population",
                         msg="контейнер принят за привязку — предмет сторожа "
                             "назначен по случайной близости литерала")


class OnlyOrderComparisonsJudgeAge(unittest.TestCase):
    """ЗВЕНО: `==` вердикта о свежести не выносит и в население не входит."""

    def test_equality_is_not_a_freshness_verdict(self):
        tree = _CodeTree('''
            STALE_HOURS = 2.0

            def judge(data_dir):
                raw = (data_dir / "subject.json").read_text()
                age = (now() - json.loads(raw)["ts"]) / 3600.0
                return age == STALE_HOURS
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/subject.json", 26)])])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        self.assertEqual([r for r in rows if r["constant"] == "STALE_HOURS"], [],
                         msg="равенство принято за сравнение порядка")


class ThirdOutcomesOfTheSubject(unittest.TestCase):
    """ЗВЕНО: четыре исхода предмета различимы, и ни один не выдан за запас."""

    def test_disk_subject_outside_the_constitution_is_unmeasured(self):
        tree = _CodeTree('''
            STALE_HOURS = 2.0

            def judge(data_dir):
                raw = (data_dir / "undeclared.json").read_text()
                age = (now() - json.loads(raw)["ts"]) / 3600.0
                return age <= STALE_HOURS
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/subject.json", 26)])])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "STALE_HOURS"]
        self.assertEqual(row["verdict"], "subject_not_declared",
                         msg="предмет, читаемый с диска и не объявленный в "
                             "конституции, слит с «вне населения»")
        self.assertIn("undeclared.json", row["reason"])

    def test_an_external_command_subject_names_its_own_reason(self):
        """`STALE_PUSH_HOURS` живого дерева имеет ровно эту форму."""
        tree = _CodeTree('''
            STALE_HOURS = 3.0

            def judge():
                out = subprocess.run(["git", "log", "-1"], capture_output=True)
                age = (now() - float(out.stdout)) / 3600.0
                return age <= STALE_HOURS
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/subject.json", 26)])])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "STALE_HOURS"]
        self.assertEqual(row["verdict"], "subject_not_declared")
        self.assertIn("внешней команды", row["reason"],
                      msg="предмет-вывод команды не отличён от предмета-файла")

    def test_two_artifacts_on_the_road_refuse_to_guess(self):
        tree = _CodeTree('''
            STALE_HOURS = 2.0

            def judge(data_dir, which):
                name = "a.json" if which else "b.json"
                raw = (data_dir / name).read_text()
                age = (now() - json.loads(raw)["ts"]) / 3600.0
                return age <= STALE_HOURS
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/a.json", 26), ("data/b.json", 26)])])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "STALE_HOURS"]
        self.assertEqual(row["verdict"], "subject_ambiguous",
                         msg="предмет угадан при двух артефактах на дороге")

    def test_a_network_timeout_is_outside_the_population(self):
        tree = _CodeTree('''
            FETCH_STALE_S = 30.0

            def judge(elapsed):
                return elapsed < FETCH_STALE_S
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/subject.json", 26)])])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        row, = [r for r in rows if r["constant"] == "FETCH_STALE_S"]
        self.assertEqual(row["verdict"], "outside_population",
                         msg="таймаут сети зачислен в сторожа свежести — "
                             "население раздуто, доля находок разбавлена")

    def test_an_unparsable_file_is_named_not_skipped(self):
        tree = _CodeTree("STALE_HOURS = (((\n", [
            _agent("com.spa.daily", "calendar:08:00", [("data/a.json", 26)])])
        self.addCleanup(tree.close)
        _, rows = tree.measure()
        self.assertEqual([r["verdict"] for r in rows], ["file_unparsed"],
                         msg="нечитаемый файл пропущен молча — «не измерено» "
                             "выдано за «чисто»")


class BelowTactAndNoMarginAreDistinct(unittest.TestCase):
    """ЗВЕНО: равенство порога такту — свой исход, а не находка и не запас."""

    def test_equal_threshold_is_no_margin(self):
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.hourly", "interval:3600s", [("data/a.json", 1)]),
        ]))
        row, = census.measure_declared(table)
        self.assertEqual(row["verdict"], "no_margin")

    def test_greater_threshold_has_margin(self):
        table = census.artifact_tacts(_manifest([
            _agent("com.spa.hourly", "interval:3600s", [("data/a.json", 3)]),
        ]))
        row, = census.measure_declared(table)
        self.assertEqual(row["verdict"], "has_margin")
        self.assertIsNone(row["reason"])


class TwoThresholdsIsItsOwnAxis(unittest.TestCase):
    """ЗВЕНО: ось «два срока» НЕ выводится из двух первых.

    Оба порога могут иметь запас к такту и всё равно расходиться между собой —
    значит, сложить эту ось с `below_tact` нельзя.
    """

    def test_both_with_margin_still_contradict(self):
        tree = _CodeTree('''
            STALE_HOURS = 48.0

            def judge(data_dir):
                raw = (data_dir / "subject.json").read_text()
                age = (now() - json.loads(raw)["ts"]) / 3600.0
                return age <= STALE_HOURS
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/subject.json", 26)])])
        self.addCleanup(tree.close)
        table, rows = tree.measure()
        declared = census.measure_declared(table)
        self.assertEqual({r["verdict"] for r in declared}, {"has_margin"})
        self.assertEqual([r["verdict"] for r in rows], ["has_margin"])
        both, = census.measure_contradictions(declared, rows)
        self.assertEqual(both["declared_hours"], 26.0)
        self.assertEqual(both["code_hours"], 48.0)

    def test_equal_thresholds_do_not_contradict(self):
        tree = _CodeTree('''
            STALE_HOURS = 26.0

            def judge(data_dir):
                raw = (data_dir / "subject.json").read_text()
                age = (now() - json.loads(raw)["ts"]) / 3600.0
                return age <= STALE_HOURS
        ''', [_agent("com.spa.daily", "calendar:08:00",
                     [("data/subject.json", 26)])])
        self.addCleanup(tree.close)
        table, rows = tree.measure()
        self.assertEqual(
            census.measure_contradictions(census.measure_declared(table), rows), [],
            msg="согласные пороги объявлены спорящими")


class TheInstrumentOnlyReads(unittest.TestCase):
    """ЗВЕНО: прибор ничего не правит и ничего не пишет (`applied=False`)."""

    def test_applied_is_false(self):
        self.assertFalse(census.APPLIED)
        self.assertFalse(census.measure(Path(__file__).resolve().parents[2])
                         ["applied"])

    def test_no_write_call_in_the_module(self):
        source = Path(census.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        writers = {"atomic_save", "write_text", "write_bytes", "mkdir", "unlink"}
        found = {node.func.attr if isinstance(node.func, ast.Attribute)
                 else getattr(node.func, "id", None)
                 for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertFalse(found & writers,
                         msg=f"прибор пишет на диск: {sorted(found & writers)}")


class LiveTreeRatchet(unittest.TestCase):
    """ЗВЕНО: храповик класса на ЖИВОМ дереве — только вниз.

    Набор может УМЕНЬШАТЬСЯ (находку починили — строку убрать). Дописывать сюда,
    чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16): тот же порядок, что у
    `frozen_date_baseline.json`.
    """

    #: Замер 2026-10-08 (цикл #802, ADR-646). Ключ — где порог объявлен.
    KNOWN = {
        ("declared", "data/investment_os/chief_investment.json",
         "produces[com.spa.io_chief_investment]"),
        ("declared", "data/investment_os/chief_investment.json", "artifacts[]"),
        ("in_code", "spa_core/analytics/signal_aggregator.py", "TIER_B_TTL_S"),
        ("in_code", "spa_core/api/routers/live.py", "FLEET_STALE_MIN"),
        ("in_code", "spa_core/monitoring/uptime_monitor.py", "STALE_CYCLE_HOURS"),
    }

    @classmethod
    def setUpClass(cls):
        cls.result = census.measure(Path(__file__).resolve().parents[2])

    def _found(self):
        found = set()
        for row in self.result["declared"]:
            if row["verdict"] in census.FINDING_VERDICTS:
                found.add(("declared", row["artifact"], row["where"]))
        for row in self.result["in_code"]:
            if row["verdict"] in census.FINDING_VERDICTS:
                found.add(("in_code", row["module"], row["constant"]))
        return found

    def test_no_new_sensor_is_red_by_construction(self):
        new = self._found() - self.KNOWN
        self.assertFalse(new, msg=f"НОВЫЙ сторож с порогом ниже такта: {sorted(new)}")

    def test_the_named_instance_of_the_order_is_still_measured(self):
        """`STALE_CYCLE_HOURS` — тот самый случай, которым заказан класс.

        Если он уходит из находок, причина обязана быть названа: либо порог
        починен (тогда строку убрать из `KNOWN`), либо прибор потерял дорогу —
        и тогда это регресс переписи, а не исправление сторожа.
        """
        anchor = ("in_code", "spa_core/monitoring/uptime_monitor.py",
                  "STALE_CYCLE_HOURS")
        rows = [row for row in self.result["in_code"]
                if row["module"] == anchor[1] and row["constant"] == anchor[2]]
        self.assertTrue(rows, msg="прибор потерял названный заказом сторож")
        self.assertEqual(rows[0]["verdict"], "below_tact",
                         msg=f"вердикт названного сторожа изменился: {rows[0]}")
        self.assertEqual(rows[0]["artifact"], "data/paper_trading_status.json")

    def test_report_prints_the_third_outcome_first(self):
        text = census.format_report(self.result)
        self.assertIn(census.NOT_MEASURED, text.splitlines()[0],
                      msg="третий исход не первым — «не измерено» тонет")
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text)
        self.assertIn("ADVISORY", text)


if __name__ == "__main__":
    unittest.main()
