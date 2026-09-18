"""Проводка прибора «двери часов»: у числа появились ПРОИЗВОДИТЕЛЬ и ЧИТАТЕЛЬ.

Заказ **G37 п. 2** (он же п. 2 заказа G36) приказа владельца «Portfolio CIO»,
решение — ADR-414.

## Что измерялось ДО написания файла

`data/python_reader_clock_doors.json` лежал на прод-пути и жил **строкой в
обязательном промпте** (шаг (1ж)) — не вызовом. Замер 18.09 (ADR-412) ответил
прямо: автоматического зова не наблюдалось НИ ОДНОГО, отметку артефакта каждый
раз ставила рука цикла. Читателя у числа не было тоже: трёх реестров шага
0-офис (`_READ_SCHEMA` — форма, `_PRODUCER` — производитель, именная ветка
`_summarize_json` — отрисовка) он не касался, в `architecture/manifest.json`
его не было, поэтому шаг 0-офис файл даже не открывал.

Это ВТОРОЕ ПЛЕЧО опыта, первое плечо которого закрыто заказом G35 п. 5
(ADR-411): сосед `list_identity_census` был проведён ступенью моста, а этот
прибор намеренно оставлен строкой промпта — чтобы вопрос «стои́т ли строка в
промпте чего-нибудь» получил ответ, а не догадку. Ответ получен, опыт закончен,
плечо проводится.

## Своя находка этого цикла, которой заказ не называл

`measure` пишет `invoked_by` с #628, и **ни одна строка отчёта его не читала** —
признак записывался и умирал в файле. Наблюдение 25.09 (заказ G37 п. 1) идёт
ИМЕННО по `invoked_by.entry`, то есть у него не было бы читателя вовсе: ADR-259
во второй раз, на приборе, который сам же меряет непрочитанные записи. Класс
закрыт строкой `[ЗВАВШИЙ]` и проверками `CallerIsReadNotOnlyRecorded` ниже.

## Почему проверок несколько, а не одна

Проводка рвётся в четырёх местах, и каждое молчит по-своему:

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется никогда; SLO скажет об этом часами позже и чужим голосом |
| запись в `artifacts[]` конституции | шаг 0-офис файл не открывает — числа нет в контексте |
| запись в `produces[]` паспорта | агент утверждает, что этого продукта не производит; SLO не назначен |
| именная ветка отрисовки | файл открыт, прочитано НОЛЬ чисел, ресит не пишется («вхолостую») |

У каждой проверки здесь есть обратная сторона: порванное звено краснеет, целое —
проходит. Проверка, никогда не видевшая поломки, — украшение
(`.claude/rules/deployment.md`).

Часы инъектируются, литеральных дат нет вовсе; живое `data/` не читается — все
стенды одноразовые, поэтому вердикт не зависит ни от календаря хоста, ни от
того, отработал ли сегодня бегун. НАСТОЯЩИЙ замер здесь не зовётся ни разу: он
поднимает читателей подпроцессами и стоит минуты, поэтому `measure` подменяется
шпионом — предмет этих проверок ПРОВОДКА, а не сам замер.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import copy
import datetime as dt
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import python_reader_clock_doors as doors

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
ARTIFACT_REL = "data/python_reader_clock_doors.json"
STAGE_KEY = "python_reader_clock_doors"

# FROZEN-DATE-OK: injected-clock — NOW уезжает аргументом в `doors.run(now=)` и
# в `_summarize_json(now=)`, а ВСЕ отметки стендов вычисляются от него же
# (`NOW - timedelta(...)`). Обе стороны закреплены, календарь хоста не участвует.
#: Часы — ВХОД, а не окружение.
NOW = dt.datetime(2026, 9, 18, 10, 0, tzinfo=dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location("_office_under_test", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest() -> dict:
    return json.loads((REPO / "architecture" / "manifest.json")
                      .read_text(encoding="utf-8"))


def _finding_doc() -> dict:
    """Полный документ: у КАЖДОГО объявленного поля есть непустое значение.

    Пустых значений здесь нет намеренно. Раздел, который печатается только
    когда он непуст, на пустом документе неотличим от неотрисованного, и
    дифференциальная проверка формы была бы слепа ровно там, где ей положено
    видеть. Форма взята с НАСТОЯЩЕГО артефакта прод-пути, а не выдумана.
    """
    return {
        "generated_at": NOW.isoformat(),
        "generated_by": doors.PRODUCER,
        "status": "FINDING",
        "invoked_by": {"schema": "call_provenance.v1", "measured": True,
                       "entry": "spa_core/monitoring/findings_bridge.py",
                       "inside_tree": True, "doors_agree": True,
                       "read_by": "sys.modules['__main__'].__file__"},
        "advisory": "прибор только ЧИТАЕТ",
        "counts": {
            "python_branch": 5, "measured": 5, "unmeasured": 1,
            "rest_on_import_bound_door": 1, "rest_on_other_door": 1,
            "carry_run_provenance_not_a_door": 2,
            "provenance_unmeasured": 1, "noisy_reverse": 1,
            "doors_free_to_close": 1,
            "doors_whose_closing_rewrites_the_answer": 1,
            "door_price_unmeasured": 1,
        },
        "import_bound_doors": {
            "spa_core.monitoring.decision_audit_trail":
                [".snapshot_id_probe.samples[0]"]},
        "other_doors": {"spa_core.monitoring.judge_alone_price": [".wall_clock"]},
        "run_provenance": {
            "spa_core.monitoring.heir_all_rows_price": [".stand.s_one"]},
        "provenance_unmeasured": {
            "spa_core.monitoring.act_day_recovery": {".stand_root": "зов не вернулся"}},
        "doors_that_rewrite_the_answer": {
            "spa_core.monitoring.decision_audit_trail": {
                "door": [".snapshot_id_probe.samples[0]"],
                "answer_changed_at": [".counts.info"],
                "samples": {".counts.info": {"unpinned": 3, "pinned": 4}}}},
        "doors_free_to_close": {
            "spa_core.monitoring.criterion_sign_price": [".stand_mtime"]},
        "door_price_unmeasured": {
            "spa_core.monitoring.swap_existence_price": "второй зов не вернулся"},
        "control_arm": {"outcome": "measured", "pin_observed": False},
        "reverse_direction": {"spa_core.monitoring.act_day_recovery": [".x"]},
        "unmeasured_causes": {"no_entry_point": 1},
    }


def _unmeasured_doc() -> dict:
    return {"generated_at": NOW.isoformat(), "status": "UNMEASURED",
            "reason": "стенд не построен: каталог data/ пуст",
            "generated_by": doors.PRODUCER,
            "invoked_by": {"schema": "call_provenance.v1", "measured": True,
                           "entry": "spa_core/monitoring/python_reader_clock_doors.py",
                           "inside_tree": True, "doors_agree": True,
                           "read_by": "sys.modules['__main__'].__file__"},
            "advisory": "прибор только ЧИТАЕТ"}


def _drop(doc: dict, path: str) -> dict:
    """Копия документа без ОДНОГО объявленного поля (дифференциальный замер)."""
    out = copy.deepcopy(doc)
    node = out
    parts = path.split(".")
    for key in parts[:-1]:
        node = node.get(key)
        if not isinstance(node, dict):
            return out
    node.pop(parts[-1], None)
    return out


class ProducerIsACallNotADeclaration(unittest.TestCase):
    """Объявление без вызова — дефект ADR-259, и мерится ФОРМА вызова."""

    @staticmethod
    def _called_modules(src: str) -> set:
        tree = ast.parse(src)
        main = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        seen = set()
        for node in ast.walk(main):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run"
                    and isinstance(node.func.value, ast.Name)):
                seen.add(node.func.value.id)
        return seen

    def test_the_bridge_actually_calls_run(self):
        src = Path(fb.__file__).read_text(encoding="utf-8")
        self.assertIn(STAGE_KEY, self._called_modules(src),
                      "python_reader_clock_doors.run(...) не зовётся в "
                      "findings_bridge.main — артефакт будет писать только рука, "
                      "ровно как до этого цикла")

    def test_positive_control_a_mention_is_not_a_call(self):
        """Обратная сторона МЕРКИ: упоминание имени ей не годится.

        Это не украшение: до ADR-414 имя прибора встречалось в промпте и в
        комментариях, и мерка «имя попалось в тексте» объявила бы проводку
        целой при полном её отсутствии — то самое состояние, которое замер
        18.09 нашёл на прод-пути.
        """
        mention = ("def main(argv=None):\n"
                   "    # python_reader_clock_doors тут только назван\n"
                   "    x = 'python_reader_clock_doors.run(root=1)'\n"
                   "    return x\n")
        self.assertNotIn(STAGE_KEY, self._called_modules(mention))

    def test_stage_composition_declares_it(self):
        self.assertIn(STAGE_KEY, fb.CENSUS_STAGE)
        self.assertIn(STAGE_KEY, fb.CENSUS_PRODUCT)
        self.assertEqual(fb.CENSUS_PRODUCT[STAGE_KEY]["artifact"], ARTIFACT_REL)
        self.assertTrue((REPO / fb.CENSUS_PRODUCT[STAGE_KEY]["module"]).exists())

    def test_entry_point_declares_the_product(self):
        """`PRODUCES` — то объявление, которое читает сторож B7."""
        self.assertIn(ARTIFACT_REL, fb.PRODUCES)


class ArtifactHasTwoHomesInTheConstitution(unittest.TestCase):
    """Дом артефакта — ДВЕ записи: `artifacts[]` и `produces[]` паспорта."""

    def test_artifacts_entry_names_consumer_and_producer(self):
        art = next((a for a in _manifest()["artifacts"]
                    if a["path"] == ARTIFACT_REL), None)
        self.assertIsNotNone(art, "артефакта нет в artifacts[] конституции — "
                                  "шаг 0-офис его не откроет вовсе")
        self.assertEqual(art["status"], "active")
        self.assertIn("orchestrator_protocol", art.get("consumers") or [])
        self.assertEqual(art.get("producer"), "com.spa.decision_loop")

    def test_passport_of_the_producer_declares_it_too(self):
        agent = next(a for a in _manifest()["agents"]
                     if a.get("label") == "com.spa.decision_loop")
        produced = {p.get("artifact") for p in (agent.get("produces") or [])}
        self.assertIn(ARTIFACT_REL, produced,
                      "второй записи дома нет: паспорт агента утверждает, что "
                      "этого артефакта он не производит, и SLO ему не назначен")

    def test_slo_is_looser_than_the_tact_of_the_measurement_itself(self):
        """Срок годности НЕ имеет права истекать раньше собственного такта.

        Положительный контроль класса: поставь здесь 168ч (ровно такт) — и
        артефакт объявлялся бы протухшим в ту самую минуту, когда ему только
        предстоит перемериться, то есть сторож свежести краснел бы на
        ИСПРАВНОМ контуре каждую неделю.
        """
        art = next(a for a in _manifest()["artifacts"]
                   if a["path"] == ARTIFACT_REL)
        self.assertGreater(art["slo_hours"], doors.MEASUREMENT_TACT_DAYS * 24)


class TactIsDecidedByTheFileNotBySchedule(unittest.TestCase):
    """Внутри такта ступень НЕ мерит и НЕ пишет; вне такта — мерит.

    Замер подменён шпионом намеренно: настоящий поднимает читателей
    подпроцессами и стоит минуты, а предмет проверки — ГЕЙТ, а не замер.
    """

    def setUp(self):
        self._real = doors.measure
        self.calls: list = []

        def _spy(data_dir, tree_root, *, now=None, full=False):
            self.calls.append((str(data_dir), str(tree_root), now, full))
            return {"status": "CLEAN", "advisory": "-",
                    "generated_at": (now or NOW).isoformat(),
                    "counts": {"python_branch": 0, "measured": 0,
                               "unmeasured": 0, "rest_on_import_bound_door": 0,
                               "rest_on_other_door": 0}}

        doors.measure = _spy

    def tearDown(self):
        doors.measure = self._real

    def _root(self, stamp: dt.datetime | None):
        tmp = tempfile.mkdtemp(prefix="spa_g37_")
        data = Path(tmp) / "data"
        data.mkdir()
        if stamp is not None:
            (data / doors.ARTIFACT).write_text(
                json.dumps({"generated_at": stamp.isoformat(),
                            "status": "FINDING", "marker": "ПРЕЖНИЙ"}),
                encoding="utf-8")
        return Path(tmp)

    def test_inside_the_tact_nothing_is_measured_and_nothing_is_written(self):
        root = self._root(NOW - dt.timedelta(days=1))
        before = (root / "data" / doors.ARTIFACT).read_bytes()
        outcome = doors.run(root, now=NOW)
        self.assertFalse(outcome["measured"])
        self.assertEqual(self.calls, [], "внутри такта замер всё же позвали — "
                                         "а он стоит минуты на каждом прогоне "
                                         "шестичасового агента")
        self.assertEqual(before, (root / "data" / doors.ARTIFACT).read_bytes())
        self.assertIn("дн", outcome["reason"])

    def test_not_measured_is_not_a_verdict(self):
        """Инв. #17: «не мерили» обязано быть отличимо от «измерено и чисто»."""
        outcome = doors.run(self._root(NOW - dt.timedelta(hours=2)), now=NOW)
        self.assertNotIn("doc", outcome)
        self.assertNotIn("status", outcome)

    def test_outside_the_tact_it_measures_and_rewrites(self):
        root = self._root(NOW - dt.timedelta(days=doors.MEASUREMENT_TACT_DAYS + 1))
        outcome = doors.run(root, now=NOW)
        self.assertTrue(outcome["measured"])
        self.assertEqual(len(self.calls), 1)
        written = json.loads((root / "data" / doors.ARTIFACT)
                             .read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "CLEAN")
        self.assertNotIn("marker", written)

    def test_missing_artifact_measures_rather_than_skips(self):
        """Fail-safe направление: отсутствие отметки — не «свежо»."""
        outcome = doors.run(self._root(None), now=NOW)
        self.assertTrue(outcome["measured"])
        self.assertEqual(len(self.calls), 1)

    def test_write_can_be_switched_off_without_touching_the_tact(self):
        root = self._root(None)
        outcome = doors.run(root, now=NOW, write=False)
        self.assertTrue(outcome["measured"])
        self.assertFalse((root / "data" / doors.ARTIFACT).exists())

    def test_the_clock_reaches_the_measurement_itself(self):
        """Инъекция обязана доходить до ПРОВОДКИ, а не кончаться у гейта.

        Половина инъекции — та же бомба (`.claude/rules/deployment.md`,
        поправка #453): гейт такта судил бы по переданным часам, а сам замер
        штамповал бы документ стенными. Мерится ИСХОД: шпион получил ровно те
        часы, что дал вызывающий.
        """
        doors.run(self._root(None), now=NOW)
        self.assertEqual(self.calls[0][2], NOW)


class TheTactGateLivesInOnePlace(unittest.TestCase):
    """Рука владельца и ступень моста судят о сроке ОДНИМ правилом.

    Вторая копия гейта в `main()` означала бы, что `--if-due` из командной
    строки и ступень расходятся молча — тот самый класс «две копии одной мерки»
    (ADR-220), которым этот же цикл занимался у карточек.
    """

    def test_main_delegates_to_run(self):
        src = Path(doors.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        main = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        called = {n.func.id for n in ast.walk(main)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("run", called, "main() не зовёт run() — гейт такта "
                                     "размножился")
        self.assertNotIn("measurement_due",
                         {n.func.id for n in ast.walk(main)
                          if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)},
                         "в main() осталась ВТОРАЯ копия гейта такта")

    def test_main_prints_the_reason_inside_the_tact_and_exits_zero(self):
        real = doors.run
        doors.run = lambda *a, **k: {"measured": False, "reason": "такт не вышел",
                                     "artifact": "x"}
        try:
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = doors.main(["--if-due"])
            self.assertEqual(rc, 0)
            self.assertIn("такт не вышел", buf.getvalue())
        finally:
            doors.run = real


class CallerIsReadNotOnlyRecorded(unittest.TestCase):
    """`invoked_by` записывался с #628 и не читался НИ ОДНОЙ строкой отчёта.

    Наблюдение 25.09 (заказ G37 п. 1) идёт именно по `entry`; запись без
    читателя — ADR-259, и завести её второй раз, зная о классе, значило бы
    воспроизвести его намеренно.
    """

    def test_the_caller_line_is_printed(self):
        text = "\n".join(doors.report(_finding_doc()))
        self.assertIn("[ЗВАВШИЙ]", text)
        self.assertIn("findings_bridge.py", text,
                      "строка звавшего напечатана, но не НАЗЫВАЕТ точку входа")

    def test_it_is_printed_before_the_early_return_of_an_unmeasured_doc(self):
        """На UNMEASURED вопрос «кто позвал» не менее интересен.

        Ровно так выглядел бы прогон, который ступень моста завела, а стенд не
        построила: без этой строки различить его и ручной зов было бы нечем.
        """
        text = "\n".join(doors.report(_unmeasured_doc()))
        self.assertIn("[ЗВАВШИЙ]", text)
        self.assertIn("python_reader_clock_doors.py", text)

    def test_the_line_comes_from_the_document_not_from_a_constant(self):
        """Обратная сторона: подменили запись — сменилась строка."""
        doc = _finding_doc()
        doc["invoked_by"] = dict(doc["invoked_by"], entry="scripts/mine.py")
        line = next(l for l in doors.report(doc) if "[ЗВАВШИЙ]" in l)
        self.assertIn("scripts/mine.py", line)
        self.assertNotIn("findings_bridge", line)

    def test_absence_of_the_record_is_not_dressed_as_a_record(self):
        """Инв. #17: «поля нет» ≠ «позван неизвестно кем»."""
        line = next(l for l in doors.report(_drop(_finding_doc(), "invoked_by"))
                    if "[ЗВАВШИЙ]" in l)
        self.assertIn("НЕ ЗАПИСАНО", line)


class TheHandMustNotRaceTheStage(unittest.TestCase):
    """Ручной зов в промпте и ступень борются за ОДИН недельный такт.

    Замер, из-за которого шаг (1ж) снят этим циклом. Такт решает ФАЙЛ: кто
    позвал первым после семидневной отметки, тот его и потратил, второй увидит
    «не назначен». Циклы оркестратора идут примерно РАЗ В ЧАС (#627 04:38,
    #628 05:49, #629 07:24, #630 09:41Z), а агент `com.spa.decision_loop` — раз
    в 6 ч; значит рука побеждала бы почти наверняка, и наблюдение 25.09 (заказ
    G37 п. 1, по `invoked_by.entry`) прочло бы РУКУ вместо ступени — то есть
    объявило бы исправную проводку молчащей.

    Тише всего здесь то, что обе стороны выглядят исправно: артефакт свежий,
    вердикт верный, ступень «работает». Поэтому мерка — не на глаз, а
    храповиком: ручной зов, вернувшийся в промпт, краснеет сразу.
    """

    PROMPT = REPO / "scripts" / "agent_orchestrator.sh"

    #: Мерка — ФОРМА ВЫЗОВА, а не имя и не строка файла.
    #:
    #: Первая редакция мерила построчно и была неверна, что этот же тест и
    #: показал на первом прогоне: весь промпт — ОДНА строка с продолжениями,
    #: поэтому «в строке есть имя и есть python3 -m» истинно от соседних шагов,
    #: и объяснение, ПОЧЕМУ звать не надо, считалось бы зовом. Имя без формы
    #: вызова ловит собственный комментарий; форма вызова ловит зов.
    _CALL = re.compile(
        r"python3\s+(?:-m\s+spa_core\.monitoring\.|scripts/)python_reader_clock_doors")

    @classmethod
    def _hand_calls(cls, text: str) -> list:
        return [m.group(0) for m in cls._CALL.finditer(text)]

    def test_the_prompt_no_longer_calls_it_by_hand(self):
        found = self._hand_calls(self.PROMPT.read_text(encoding="utf-8"))
        self.assertEqual(found, [], "ручной зов вернулся в промпт — он заберёт "
                                    f"недельный такт у ступени: {found}")

    def test_positive_control_the_measure_sees_such_a_call(self):
        """Обратная сторона: проверка, не видевшая зова, ничего не держит."""
        self.assertTrue(self._hand_calls(
            "(1ж) ОБЯЗАТЕЛЬНО python3 -m spa_core.monitoring."
            "python_reader_clock_doors --data-dir x --if-due"))

    def test_the_prompt_still_explains_why_not_to_call_it(self):
        """Снятый шаг обязан оставить ПРИЧИНУ, иначе его вернут как пропажу."""
        text = self.PROMPT.read_text(encoding="utf-8")
        self.assertIn("ADR-414", text)
        self.assertIn("ЗАБИРАЕТ такт", text)


class OfficeReadsItAndNotVacuously(unittest.TestCase):
    """Читатель обязан ПЕЧАТАТЬ числа, а не просто открывать файл."""

    def setUp(self):
        self.office = _office()

    def _lines(self, doc, name=ARTIFACT_REL):
        return self.office._summarize_json(name, doc, now=NOW,
                                           root=str(REPO), artifact_root=str(REPO))

    def test_named_branch_prints_the_numerator_with_its_denominator(self):
        text = "\n".join(self._lines(_finding_doc()))
        self.assertIn("[ОТВЕТ]", text)
        self.assertIn("население питоньей ветви 5", text)
        self.assertIn("[ПИН ЗАКРЫВАЕТ]", text)

    def test_a_finding_is_marked_so_the_reader_acts(self):
        self.assertIn("⚠️", "\n".join(self._lines(_finding_doc())))

    def test_clean_is_not_dressed_as_a_finding(self):
        doc = _finding_doc()
        doc["status"] = "CLEAN"
        doc["counts"]["rest_on_import_bound_door"] = 0
        doc["import_bound_doors"] = {}
        doc["doors_that_rewrite_the_answer"] = {}
        doc["door_price_unmeasured"] = {}
        doc["reverse_direction"] = {}
        text = "\n".join(self._lines(doc))
        self.assertNotIn("⚠️", text)
        self.assertIn("[ОПОРА]", text)

    def test_unmeasured_says_the_reason_and_claims_no_numbers(self):
        text = "\n".join(self._lines(_unmeasured_doc()))
        self.assertIn("[НЕ ИЗМЕРЕНО]", text)
        self.assertIn("стенд не построен", text)
        self.assertNotIn("[ОТВЕТ]", text)

    def test_the_read_is_not_hollow(self):
        lines = self._lines(_finding_doc())
        self.assertFalse(any(l.startswith(self.office._HOLLOW_MARK)
                             for l in lines))

    def test_positive_control_without_the_branch_the_read_degenerates(self):
        """Что делает чтение содержательным — ВЕТКА, а не наличие файла.

        Замер, а не догадка: тот же документ под невведённым именем уходит в
        общий путь, и оттуда выходит одно слово статуса. Слово верное и
        бесполезное: ни знаменателя, ни дверей, ни звавшего. И главное —
        выродившееся чтение сторож холостого чтения НЕ видит.
        """
        lines = self._lines(_finding_doc(),
                            name="data/python_reader_clock_doors_NOT_WIRED.json")
        text = "\n".join(lines)
        self.assertIn("FINDING", text)
        for absent in ("[ОТВЕТ]", "[ПИН ЗАКРЫВАЕТ]", "[ЗВАВШИЙ]"):
            self.assertNotIn(absent, text,
                             f"общий путь напечатал {absent!r} — тогда мерка "
                             f"выше не про ветку")
        self.assertFalse(any(l.startswith(self.office._HOLLOW_MARK)
                             for l in lines),
                         "выродившееся чтение не холостое, и это главное: "
                         "сторож холостого чтения его НЕ увидит")


class DeclaredSchemaIsWhatTheBranchActuallyReads(unittest.TestCase):
    """Объявленная форма сверяется с ЧТЕНИЕМ, а не с добрым словом.

    Дифференциальный замер: у полного документа убирается ОДНО объявленное
    поле, и вывод читателя обязан измениться. Поле, объявленное и никем не
    читаемое, — украшение схемы.
    """

    def setUp(self):
        self.office = _office()
        self.declared = self.office._READ_SCHEMA["python_reader_clock_doors.json"]

    def _text(self, doc):
        return "\n".join(self.office._summarize_json(
            ARTIFACT_REL, doc, now=NOW, root=str(REPO), artifact_root=str(REPO)))

    def test_every_declared_field_changes_the_output_when_removed(self):
        base_finding = self._text(_finding_doc())
        base_unmeasured = self._text(_unmeasured_doc())
        unread = []
        for path in self.declared:
            a = self._text(_drop(_finding_doc(), path)) != base_finding
            b = self._text(_drop(_unmeasured_doc(), path)) != base_unmeasured
            if not (a or b):
                unread.append(path)
        self.assertEqual(unread, [], f"объявлено и не читается: {unread}")

    def test_removing_the_declaration_itself_silences_the_schema_alarm(self):
        """ОБРАТНАЯ сторона соседа: сосед мерит «объявлено ⇒ читается».

        Снятие САМОГО объявления соседа не красит: он перебирает объявленные
        поля, и вычеркнутое просто выпадает из его цикла (находка батареи
        #628). Меряется ИСХОД: у документа убрано `invoked_by`, и тревога о
        ФОРМЕ обязана назвать это поле. Строка отрисовки `[ЗВАВШИЙ]` из счёта
        исключена намеренно — она называет то же поле и без объявления, то есть
        приняла бы мутацию за живого сторожа.
        """
        text = self._text(_drop(_finding_doc(), "invoked_by"))
        named_by_the_schema_alarm = [
            line for line in text.splitlines()
            if "invoked_by" in line and "[ЗВАВШИЙ]" not in line
        ]
        self.assertTrue(named_by_the_schema_alarm,
                        "поле пропало из документа, а тревога о ФОРМЕ промолчала "
                        f"— объявление в `_READ_SCHEMA` ничего не держит:\n{text}")

    def test_the_producer_writes_every_declared_field(self):
        src = (REPO / "spa_core" / "monitoring"
               / "python_reader_clock_doors.py").read_text(encoding="utf-8")
        missing = [p for p in self.declared
                   if f'"{p.split(".")[-1]}"' not in src]
        self.assertEqual(missing, [], f"объявлено, а производитель не пишет: {missing}")

    def test_the_producer_map_points_at_a_file_that_exists(self):
        rel = self.office._PRODUCER["python_reader_clock_doors.json"]
        self.assertTrue((REPO / rel).exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
