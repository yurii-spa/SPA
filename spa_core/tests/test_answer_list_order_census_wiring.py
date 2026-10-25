"""Проводка переписи ПОРЯДКА списков ответа: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Заказ **G800 п. 2** приказа владельца «Portfolio CIO», решение — ADR-801.

## Почему этот файл существует

ADR-800 построил перепись (`answer_list_order_census`) и САМ назвал её
единственный незакрытый изъян дословно:

    «У прибора НЕТ расписанного читателя. Он ADVISORY, зовётся рукой и
    тестами; ступенью моста находок не проведён. Это первый пункт заказа
    G800 и названо здесь, чтобы „прибор без читателя“ (ADR-345) не
    повторился молча.»

Соседний прибор того же семейства прожил без читателя ПЯТЬ ADR и четыре цикла
(`ledger_parse_census`, ADR-785), и ровно поэтому проводка меряется, а не
объявляется. По уроку ADR-427 запись в реестре исполнением не является, а по
уроку цикла #760 ИМПОРТ за вызов зачтётся, если спрашивать имя в тексте, —
поэтому вызов ищется разбором AST **ПО ФОРМЕ ВЫЗОВА**, и имя модуля берётся не
из литерала, а из той связки, которой его ввезли в тело `main()`.

## Проводка рвётся в шести местах, и каждое молчит по-своему

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется НИКОГДА; скажет SLO часами позже и чужим голосом |
| `PRODUCES` (состав моста) | продукт не объявлен — сторож сиротства о нём не спросит |
| `CENSUS_STAGE` / `CENSUS_PRODUCT` | ступень не числится переписью: «пропущено» не отличить от «не бывало» |
| `_READ_SCHEMA` + `_PRODUCER` офиса | шаг 0-офис файл не открывает — числа нет в контексте оркестратора |
| именная ветка отрисовки | файл ОТКРЫТ, прочитано ноль чисел («вхолостую») |
| запись манифеста | SLO не назначен; агент утверждает, что продукта не производит |

**Седьмое звено — ОТМЕТКА, и его открыла сама проводка.** Пока артефакт не
читал никто, источник `generated_at` был безразличен: возраст прибора не
спрашивал ни один сторож. Со SLO 192ч отметку читает сторож свежести, и
стенные часы в ней означали бы, что «свежо» и «протухло» — свойство календаря
машины, а не прогона (класс ADR-562, `artifact_stamp_clock_doors`: вердикт от
часов не зависит, поэтому подмена проходит все контроли вердикта и врёт ровно
в возрасте). Отметка закреплена ADR-801 и проверяется ДИФФЕРЕНЦИАЛЬНО —
подменой стенных часов, а не чтением подписи.

**ДЕВЯТОЕ звено — ЗВАВШИЙ, и его открыл заказ G801 п. 2.** Заказ велел
сверить, что отметка принадлежит прогону МОСТА, а не чьей-то руке, — и на
документе без записи о звавшем этот вопрос НЕИЗМЕРИМ ПО ПОСТРОЕНИЮ: отметка
сменится ОДИНАКОВО при зове ступенью и при зове рукой (ADR-411, заказ G36 п. 1).
Восьмое звено ниже закрывает ЧАСЫ отметки, девятое — её ПРОИСХОЖДЕНИЕ, и одно
другим не заменяется. Проба приёмки класса — `answer_list_order_names_its_caller`
(контроль в обе стороны — `test_answer_list_order_caller_probe.py`).

**Восьмое звено — ТРИ ИСХОДА ТАКТА.** `run(if_due=True)` обязан различать
«измерено», «внутри такта» и «срок НЕ ПРОЧИТАН». Слей последние два — и
сломанный артефакт станет неотличим от свежего: прибор молчит, а звавший
читает молчание как «мерили недавно» (инв. #17).

Живое `data/` на запись не открывается ни одной проверкой: сцена — одноразовая
лента во временном каталоге. Литеральных дат и литеральных pid здесь нет
ВОВСЕ: якорь времени ввезён у батареи прибора и доезжает до каждой пробы
аргументом, а об ОС этот файл не спрашивает ничего.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import inspect
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import answer_list_order_census as alo
from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import ledger_window_dependency_census as lwd

#: Сцена и ЯКОРЬ ВРЕМЕНИ берутся у батареи прибора намеренно: вторая копия
#: сцены разошлась бы с первой молча, а литеральная дата здесь была бы бомбой
#: замедленного действия (`.claude/rules/deployment.md`). Якорь приезжает
#: аргументом в каждый зов, часов этот файл не спрашивает.
from spa_core.tests.test_answer_list_order_census import NOW, build_ledger

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
BRIDGE = REPO / "spa_core" / "monitoring" / "findings_bridge.py"
ARTIFACT_REL = "data/answer_list_order.json"
ARTIFACT_NAME = "answer_list_order.json"
STAGE_KEY = "answer_list_order_census"
RUNNER = "com.spa.decision_loop"
SLO_HOURS = 192


def _office():
    spec = importlib.util.spec_from_file_location("_office_alo_under_test", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest() -> dict:
    return json.loads(
        (REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))


def _main_body() -> ast.FunctionDef:
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("у моста нет функции main — проводку не к чему крепить")


def _local_binding() -> str:
    """Чем перепись ВВЕЗЕНА в тело `main`: `… import X as _alo` ⇒ `_alo`.

    Имя спрашивается у СВЯЗКИ, а не у литерала: сосед по предмету ввозится под
    коротким псевдонимом, и проверка, знающая одно написание, объявила бы
    исправную проводку оборванной (урок ADR-443 о местном имени производителя).
    """
    for node in ast.walk(_main_body()):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == STAGE_KEY:
                    return alias.asname or alias.name
    raise AssertionError(f"{STAGE_KEY} в тело main() не ввезён вовсе")


def _run_calls(local: str) -> list:
    return [node for node in ast.walk(_main_body())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == local]


def _scene_doc(now: dt.datetime = NOW) -> dict:
    """НАСТОЯЩИЙ документ производителя на одноразовой ленте.

    Живой ленты в рабочем дереве нет ПО ПОСТРОЕНИЮ (`data/` рабочего дерева —
    замороженный канон git), поэтому «форма, которую производитель пишет на
    самом деле» снимается со сцены, а не с прода. Сцена — та же, на которой
    стои́т батарея прибора, и её положительный контроль там же: вершина
    пересобранной ленты обязана совпасть с её же живой вершиной.
    """
    with TemporaryDirectory() as root:
        return alo.measure(build_ledger(Path(root)), now=now)


class ProducingCallExistsAndIsACallNotAName(unittest.TestCase):
    def test_bridge_main_calls_the_producer_once(self):
        calls = _run_calls(_local_binding())
        self.assertEqual(len(calls), 1,
                         "в теле main() обязан быть ровно один зов run(...) "
                         "этой переписи")

    def test_the_call_passes_root_and_asks_for_the_tact(self):
        kwargs = {k.arg for k in _run_calls(_local_binding())[0].keywords}
        self.assertIn("root", kwargs,
                      "без root ступень мерила бы дерево, в котором её "
                      "случайно запустили")
        self.assertIn("if_due", kwargs,
                      "без if_due ступень поднимала бы читающую модель трижды "
                      "на КАЖДОМ прогоне моста — такт существует, чтобы этого "
                      "не было")

    def test_an_import_alone_is_not_credited_as_a_call(self):
        """ОБРАТНАЯ СТОРОНА (урок #760): импорт зовом не является."""
        fake = ast.parse("def main():\n"
                         f"    from spa_core.monitoring import {STAGE_KEY} as _alo\n")
        self.assertEqual(
            [c for c in ast.walk(fake)
             if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute)
             and c.func.attr == "run"], [])

    def test_a_mere_mention_of_the_name_is_not_credited_as_a_call(self):
        """ОБРАТНАЯ СТОРОНА: проверка по подстроке пережила бы снятие зова."""
        fake = ast.parse("def main():\n"
                         f"    print('{STAGE_KEY}.run(root=args.root)')\n")
        self.assertEqual(
            [c for c in ast.walk(fake)
             if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute)
             and c.func.attr == "run"], [])

    def test_the_stage_reports_its_own_skip_under_its_own_name(self):
        """Дверь, через которую пропуск ступени попадает в отчёт моста.

        Имя в `census_skipped` — ровно то, что сверяет с `CENSUS_STAGE` общий
        сторож разбором AST. Назови ступень здесь иначе — и «пропущено» стало
        бы неотличимо от «такой ступени не бывало».
        """
        named = [node.args[1].value for node in ast.walk(_main_body())
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "census_skipped"
                 and len(node.args) >= 2
                 and isinstance(node.args[1], ast.Constant)]
        self.assertEqual(named.count(STAGE_KEY), 1, named.count(STAGE_KEY))

    def test_producer_module_exposes_run_with_root_and_clock(self):
        params = inspect.signature(alo.run).parameters
        for name in ("root", "if_due", "now", "write", "dest", "data_dir"):
            self.assertIn(name, params)


class BridgeRegistriesDeclareTheProduct(unittest.TestCase):
    def test_artifact_is_declared_among_bridge_products(self):
        self.assertIn(ARTIFACT_REL, fb.PRODUCES)

    def test_stage_is_listed_as_a_census(self):
        self.assertIn(STAGE_KEY, fb.CENSUS_STAGE)

    def test_census_product_names_module_and_artifact(self):
        entry = fb.CENSUS_PRODUCT[STAGE_KEY]
        self.assertEqual(entry["artifact"], ARTIFACT_REL)
        self.assertTrue((REPO / entry["module"]).is_file())

    def test_declared_module_is_the_one_that_writes_the_declared_artifact(self):
        """Объявить можно что угодно — имена сверяются с ЭТАЛОНОМ прибора."""
        self.assertEqual(f"data/{alo.ARTIFACT}", ARTIFACT_REL)
        self.assertEqual(alo.PRODUCER, fb.CENSUS_PRODUCT[STAGE_KEY]["module"])
        self.assertTrue((REPO / alo.PRODUCER).is_file())


class OfficeReadsTheNumberNotJustTheFile(unittest.TestCase):
    def test_the_producer_is_named(self):
        self.assertEqual(_office()._PRODUCER[ARTIFACT_NAME], alo.PRODUCER)

    def test_shape_is_declared(self):
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        for field in ("status", "generated_at", "entries", "population",
                      "permutations", "lists", "carriers", "unmeasured_lists",
                      "findings", "unexercised_declarations",
                      "unmeasured_reason"):
            self.assertIn(field, schema)

    def test_the_third_outcome_of_a_declaration_is_part_of_the_shape(self):
        """Схема без `unexercised_declarations` унесла бы сам ЗАПРЕТ.

        «Объявления в ответе нет» и «объявление не защищает ни от чего» по
        одной ленте неразличимы, и прибор держит их раздельно. Схема,
        потерявшая третий исход, печатала бы находки и молчала о том, что
        часть объявлений этой лентой не проверена ВОВСЕ.
        """
        self.assertIn("unexercised_declarations",
                      _office()._READ_SCHEMA[ARTIFACT_NAME])

    def test_declared_shape_is_the_shape_the_producer_actually_writes(self):
        """Объявление, не сверенное с документом, есть утверждение о себе."""
        doc = _scene_doc()
        for field in _office()._READ_SCHEMA[ARTIFACT_NAME]:
            self.assertIn(field, doc, f"поле {field} объявлено и не пишется")

    def test_the_named_branch_prints_real_numbers_not_an_empty_read(self):
        lines = _office()._summarize_json(ARTIFACT_REL, _scene_doc())
        self.assertGreaterEqual(len(lines), 6, lines)
        self.assertTrue(any("списков в ответе" in line for line in lines), lines)
        self.assertTrue(any("порядок устойчив" in line for line in lines), lines)
        self.assertTrue(any("ADVISORY" in line for line in lines), lines)

    def test_an_unmeasured_document_is_not_rendered_as_clean(self):
        """ОБРАТНАЯ СТОРОНА: третий исход обязан дойти до читателя третьим."""
        doc = {"version": alo.VERSION, "status": alo.STATUS_UNMEASURED,
               "entries": None, "population": None, "permutations": [],
               "unmeasured_reason": "лента не прочитана: такого файла нет"}
        # SCHEMA-GAP-OK: документ ТРЕТЬЕГО исхода (население не считалось вовсе) — предмет сцены в том, что «НЕ ИЗМЕРЕНО» доходит до читателя третьим; полную схему на документе НАСТОЯЩЕГО производителя проверяет соседняя сцена того же файла
        lines = _office()._summarize_json(ARTIFACT_REL, doc)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in line for line in lines), lines)
        self.assertFalse(any("✅" in line for line in lines), lines)

    def test_a_document_without_the_findings_list_is_not_rendered_as_clean(self):
        """ОБРАТНАЯ СТОРОНА: перечня НЕТ и перечень ПУСТ — разные исходы.

        Артефакт прошлого образца (или оборванная запись) не имеет права
        читаться как «находок ноль»: это ровно класс «не измерено = ноль»
        (инв. #17), и у него есть свой храповик.
        """
        doc = _scene_doc()
        doc.pop("findings")
        # SCHEMA-GAP-OK: поле снято НАМЕРЕННО — сцена о том, что отсутствие перечня находок не печатается как «чисто»; полную схему проверяет соседняя сцена того же файла
        lines = _office()._summarize_json(ARTIFACT_REL, doc)
        self.assertFalse(any("✅" in line for line in lines), lines)
        self.assertTrue(any("НЕТ" in line for line in lines), lines)


class ManifestGivesTheArtifactAHome(unittest.TestCase):
    def _entry(self) -> dict:
        for group in _manifest().values():
            if not isinstance(group, list):
                continue
            for item in group:
                if isinstance(item, dict) and item.get("path") == ARTIFACT_REL:
                    return item
        raise AssertionError(f"{ARTIFACT_REL} не объявлен в манифесте")

    def test_artifact_is_active_with_a_producer_and_an_slo(self):
        entry = self._entry()
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["producer"], RUNNER)
        self.assertEqual(entry["slo_hours"], SLO_HOURS)

    def test_the_slo_is_strictly_longer_than_the_tact(self):
        """SLO 192ч против такта 168ч — ЗАПАС, а не округление.

        Равняя SLO такту, сторож свежести объявлял бы протухшим артефакт,
        которому только предстоит перемериться: красный от дрожания прогона,
        а не от состояния дерева (тот же довод у трёх соседей по предмету).
        """
        self.assertGreater(self._entry()["slo_hours"],
                           alo.MEASUREMENT_TACT_DAYS * 24)

    def test_the_runner_declares_it_among_what_it_produces(self):
        produced = [e.get("artifact") for group in _manifest().values()
                    if isinstance(group, list)
                    for item in group if isinstance(item, dict)
                    for e in (item.get("produces") or [])
                    if isinstance(e, dict)]
        self.assertIn(ARTIFACT_REL, produced)

    def test_the_manifest_note_names_the_order_and_the_class_it_closes(self):
        """Запись без предмета — адрес без содержания: SLO есть, смысла нет."""
        note = self._entry()["notes"]
        self.assertIn("G800", note)
        self.assertIn("ADR-345", note)
        self.assertIn("ADVISORY", note)


class TheStampIsAnInputNotTheWallClock(unittest.TestCase):
    """Седьмое звено: инъекция обязана доходить до САМОЙ отметки (ADR-562).

    Меряется ДИФФЕРЕНЦИАЛЬНО: стенные часы производителя подменяются на момент,
    далёкий и от якоря, и от календаря. Отметка, происходящая от них, выдаёт
    себя сама — чтение подписи такого не показало бы вовсе (замер ADR-562:
    `now` есть в подписи у 103 производителей из 112).
    """

    def _with_fake_wall(self, fake: dt.datetime):
        original = lwd._utcnow

        def fake_utcnow():
            return fake

        lwd._utcnow = fake_utcnow
        self.addCleanup(lambda: setattr(lwd, "_utcnow", original))
        return original

    def test_measure_stamps_the_passed_moment(self):
        fake = NOW + dt.timedelta(days=900)
        self._with_fake_wall(fake)
        doc = _scene_doc()
        self.assertEqual(doc["generated_at"], NOW.isoformat())
        self.assertNotEqual(doc["generated_at"], fake.isoformat())

    def test_the_fake_wall_clock_really_reaches_the_producer(self):
        """ПРОБА ПРЕДПОСЫЛКИ: без неё сцена выше зеленела бы по построению.

        Если подмена до производителя не доходит, «отметка не от стенных
        часов» верно по случайности, и тест ничего не мерит. Поэтому отдельно
        проверяется, что подменённые часы ВИДНЫ там, где производитель их
        действительно спрашивает — у собственного умолчания `run(now=None)`.
        """
        fake = NOW + dt.timedelta(days=900)
        self._with_fake_wall(fake)
        with TemporaryDirectory() as root:
            build_ledger(Path(root))
            result = alo.run(data_dir=str(Path(root) / "data"), write=False)
        self.assertEqual(result["doc"]["generated_at"], fake.isoformat())

    def test_the_stamp_the_tact_reads_is_the_stamp_the_run_wrote(self):
        """Петля замкнута: отметку ставит `run`, её же читает `measurement_due`."""
        with TemporaryDirectory() as root:
            data = Path(root) / "data"
            build_ledger(Path(root))
            written = alo.run(data_dir=str(data), now=NOW)
            artifact = Path(written["artifact"])
            self.assertEqual(
                json.loads(artifact.read_text(encoding="utf-8"))["generated_at"],
                NOW.isoformat())
            self.assertEqual(alo.NOT_DUE,
                             alo.measurement_due(artifact, now=NOW + dt.timedelta(days=1)))
            self.assertEqual(alo.DUE,
                             alo.measurement_due(artifact,
                                                 now=NOW + dt.timedelta(
                                                     days=alo.MEASUREMENT_TACT_DAYS)))


class TheTactHasThreeOutcomesNotTwo(unittest.TestCase):
    """Восьмое звено: «внутри такта» и «срок НЕ ПРОЧИТАН» — разные ответы."""

    def test_a_missing_artifact_is_measured_for_the_first_time(self):
        with TemporaryDirectory() as root:
            data = Path(root) / "data"
            build_ledger(Path(root))
            result = alo.run(data_dir=str(data), if_due=True, now=NOW)
        self.assertTrue(result["measured"])
        self.assertIn("doc", result)

    def test_inside_the_tact_nothing_is_measured_and_nothing_is_invented(self):
        with TemporaryDirectory() as root:
            data = Path(root) / "data"
            build_ledger(Path(root))
            alo.run(data_dir=str(data), now=NOW)
            artifact = data / alo.ARTIFACT
            before = artifact.read_text(encoding="utf-8")
            result = alo.run(data_dir=str(data), if_due=True,
                             now=NOW + dt.timedelta(days=1))
            self.assertFalse(result["measured"])
            self.assertFalse(result["due_unmeasured"])
            self.assertNotIn("doc", result)
            self.assertEqual(before, artifact.read_text(encoding="utf-8"),
                             "внутри такта артефакт НЕ переписывается — иначе "
                             "«мерили» стало бы следствием того, что позвали")

    def test_an_unreadable_deadline_is_its_own_outcome(self):
        with TemporaryDirectory() as root:
            data = Path(root) / "data"
            build_ledger(Path(root))
            (data / alo.ARTIFACT).write_text("{не json", encoding="utf-8")
            result = alo.run(data_dir=str(data), if_due=True, now=NOW)
        self.assertFalse(result["measured"])
        self.assertTrue(result["due_unmeasured"],
                        "сломанный артефакт не имеет права выглядеть свежим")
        self.assertIn("не разобран", result["reason"])

    def test_the_two_refusals_are_distinguishable(self):
        """ОБРАТНАЯ СТОРОНА: слей их — и звавший прочтёт одно за другое."""
        with TemporaryDirectory() as root:
            data = Path(root) / "data"
            build_ledger(Path(root))
            alo.run(data_dir=str(data), now=NOW)
            inside = alo.run(data_dir=str(data), if_due=True,
                             now=NOW + dt.timedelta(days=1))
            (data / alo.ARTIFACT).write_text("{не json", encoding="utf-8")
            broken = alo.run(data_dir=str(data), if_due=True, now=NOW)
        self.assertNotEqual(inside["due_unmeasured"], broken["due_unmeasured"])
        self.assertNotEqual(inside["reason"], broken["reason"])

    def test_write_false_leaves_no_artifact_behind(self):
        """Ступень обязана уметь мерить, НЕ трогая артефакт (сцены и мутации)."""
        with TemporaryDirectory() as root:
            data = Path(root) / "data"
            build_ledger(Path(root))
            alo.run(data_dir=str(data), write=False, now=NOW)
            self.assertFalse((data / alo.ARTIFACT).exists())


class TheCliAndTheStageShareOneDoor(unittest.TestCase):
    """CLI не вправе иметь СВОЮ копию правила «пора ли мерить» (класс ADR-220)."""

    def test_the_cli_delegates_to_run(self):
        src = Path(alo.__file__).read_text(encoding="utf-8")
        main = next(n for n in ast.parse(src).body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        called = {node.func.id for node in ast.walk(main)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("run", called,
                      "main() обязан звать run(): вторая копия такта отвечала "
                      "бы на свой вопрос")
        self.assertNotIn("measurement_due", called,
                         "правило такта в CLI — вторая копия того же правила")

    def test_the_renderer_lives_with_the_producer_and_the_cli_reuses_it(self):
        src = Path(alo.__file__).read_text(encoding="utf-8")
        printer = next(n for n in ast.parse(src).body
                       if isinstance(n, ast.FunctionDef) and n.name == "_print")
        called = {node.func.id for node in ast.walk(printer)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertIn("format_report", called)


class TheRecordSaysWhoCalled(unittest.TestCase):
    """ДЕВЯТОЕ звено (заказ G801 п. 2): документ называет ЗВАВШЕГО.

    Без этой записи вторая ось заказа неизмерима в ОДНУ сторону: отметка НЕ
    сменилась ⇒ ступень молчит (вывод верен), сменилась ⇒ не известно НИЧЕГО.
    Здесь мерится ПРОВОДКА записи (пишется · объявлена · печатается во ВСЕХ
    исходах); что запись есть ИЗМЕРЕНИЕ, а не константа, меряет проба приёмки
    на настоящих дверях — вторая копия того вопроса здесь была бы лишней.
    """

    def test_the_producer_writes_the_record(self):
        record = _scene_doc().get("invoked_by")
        self.assertIsInstance(record, dict,
                              "документ обязан нести запись о звавшем")
        self.assertIn("measured", record,
                      "у записи обязан быть третий исход своим значением")

    def test_the_office_declares_the_record_next_to_the_stamp(self):
        """Объявление рядом с `generated_at`: одно «когда», второе «кто».

        Схема, потерявшая `invoked_by`, унесла бы вместе с ним сам вопрос —
        стухший артефакт образца `/1` читался бы как обычный.
        """
        schema = _office()._READ_SCHEMA[ARTIFACT_NAME]
        self.assertIn("invoked_by", schema)
        self.assertIn("generated_at", schema)

    def test_the_caller_is_printed_in_every_outcome_including_the_third(self):
        """Строка о звавшем идёт ДО раннего выхода: он свойство ПРОГОНА.

        Документ третьего исхода (население не считалось вовсе) обязан называть
        звавшего так же, как документ с замером: иначе «кто это написал» исчезало
        бы ровно в том случае, когда ответ нужнее всего.
        """
        for doc in (_scene_doc(),
                    {"version": alo.VERSION, "status": alo.STATUS_UNMEASURED,
                     "invoked_by": {"schema": "call_provenance.v1",
                                    "measured": True, "entry": "драйвер.py",
                                    "inside_tree": False, "doors_agree": True},
                     "entries": None, "population": None, "permutations": [],
                     "unmeasured_reason": "лента не прочитана"}):
            lines = alo.format_report(doc)
            self.assertTrue(any("[ЗВАВШИЙ]" in line for line in lines), lines)

    def test_a_document_of_the_old_shape_is_not_read_as_called_by_the_stage(self):
        """ОБРАТНАЯ СТОРОНА: поля НЕТ — это своё значение, а не молчание.

        Артефакт образца `/1` записи не несёт вовсе. Молчание о звавшем читалось
        бы как «звал мост» — ровно та подмена, против которой инв. #17.
        """
        doc = _scene_doc()
        doc.pop("invoked_by")
        said = [ln for ln in alo.format_report(doc) if "[ЗВАВШИЙ]" in ln]
        self.assertEqual(len(said), 1, said)
        self.assertIn("НЕ ЗАПИСАНО", said[0])


if __name__ == "__main__":
    unittest.main()
