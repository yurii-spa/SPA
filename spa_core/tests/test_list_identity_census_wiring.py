"""Проводка переписи личности списков: у числа есть ПРОИЗВОДИТЕЛЬ и ЧИТАТЕЛЬ.

Заказ **G35 п. 5** приказа владельца «Portfolio CIO» (хвост ADR-410), решение —
ADR-411.

## Что измерялось ДО написания файла

Артефакт `data/list_identity_census.json` лежал на прод-пути с 18.09 02:39Z и
**не читался никем**: в `architecture/manifest.json` его не было вовсе, поэтому
обязательный шаг 0-офис его даже не открывал; трёх реестров читателя
(`_READ_SCHEMA` — форма, `_PRODUCER` — производитель, именная ветка
`_summarize_json` — отрисовка) он не касался; производящего вызова не
существовало ни одного — файл написала РУКА цикла #626 единожды.

Это класс «построено и не зарегистрировано», который эта же семья ловит у
других (ADR-259: измеритель с записью в манифесте, именной веткой офиса и 37
зелёными тестами не появился на диске НИ РАЗУ, потому что вызова не было).

## Почему проверок несколько, а не одна

Проводка рвётся в четырёх разных местах, и каждое молчит по-своему:

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется никогда; SLO скажет об этом ЧАСАМИ позже и чужим голосом |
| запись в `artifacts[]` конституции | шаг 0-офис файл не открывает вовсе — числа нет в контексте |
| запись в `produces[]` паспорта | агент утверждает, что этого продукта не производит; SLO не назначен |
| именная ветка отрисовки | файл открыт, прочитано НОЛЬ строк, ресит не пишется («вхолостую») |

У каждой проверки здесь есть обратная сторона: порванное звено краснеет, целое —
проходит. Проверка, никогда не видевшая поломки, — украшение
(`.claude/rules/deployment.md`).

Часы инъектируются, литеральных дат нет вовсе; живое `data/` не читается — все
стенды одноразовые, поэтому вердикт не зависит ни от календаря хоста, ни от
того, отработал ли сегодня бегун.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import copy
import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import list_identity_census as census

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
ARTIFACT_REL = "data/list_identity_census.json"
STAGE_KEY = "list_identity_census"

# FROZEN-DATE-OK: injected-clock — NOW уезжает аргументом в `census.run(now=)` и
# в `_summarize_json(now=)`, а ВСЕ отметки стендов вычисляются от него же
# (`NOW - timedelta(...)`). Обе стороны закреплены, календарь хоста не участвует.
#: Часы — ВХОД, а не окружение: и отметки стендов, и `now` происходят отсюда.
NOW = dt.datetime(2026, 9, 18, 4, 0, tzinfo=dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location("_office_under_test", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest() -> dict:
    return json.loads((REPO / "architecture" / "manifest.json")
                      .read_text(encoding="utf-8"))


def _finding_doc() -> dict:
    """Полный документ переписи: у КАЖДОГО объявленного поля есть значение.

    Пустых значений здесь нет намеренно: поле, печатаемое только когда оно
    непусто (`truncated_readers`), на пустом документе не отличалось бы от
    неотрисованного, и дифференциальная проверка ниже была бы слепа ровно там,
    где ей положено видеть.
    """
    return {
        "schema": census.SCHEMA,
        "generated_at": NOW.isoformat(),
        "status": "FINDING",
        "invoked_by": {"schema": "call_provenance.v1", "measured": True,
                       "entry": "spa_core/monitoring/findings_bridge.py",
                       "inside_tree": True, "doors_agree": True,
                       "read_by": "sys.modules['__main__'].__file__"},
        "reason": "списков без личности с годным полем ВНЕ списка имён: 2",
        "advisory": "прибор только ЧИТАЕТ",
        "counts": {
            "lists_total": 30,
            "outcomes": {"named": 4, "unnamed_candidate_outside": 2,
                         "unnamed_no_candidate": 1, "unnamed_not_dicts": 20,
                         "unnamed_empty": 3},
            "singletons": 5,
            "scalar_lists_multi": 20,
            "denominator_of_finding": 3,
            "candidate_fields_outside": {"source": 1, "forward_date": 7},
            "candidate_field_strength": {"source": 210, "forward_date": 7},
            "finding_rows": [
                {"module": "m.one", "coord": ".a.b", "n": 9,
                 "candidates": ["source"]},
                {"module": "m.two", "coord": ".c", "n": 7,
                 "candidates": ["forward_date"]},
            ],
            "truncated_readers": ["m.three"],
            "unmeasured_causes": {"no_entry_point": 4},
            "readers_measured": 50,
            "named_fields": {"protocol": 3},
        },
    }


def _unmeasured_doc() -> dict:
    return {"schema": census.SCHEMA, "generated_at": NOW.isoformat(),
            "status": "UNMEASURED", "reason": "стенд не построен: журнал пуст",
            "invoked_by": {"schema": "call_provenance.v1", "measured": True,
                           "entry": "spa_core/monitoring/list_identity_census.py",
                           "inside_tree": True, "doors_agree": True,
                           "read_by": "sys.modules['__main__'].__file__"},
            "advisory": "прибор только ЧИТАЕТ", "counts": {}}


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
                      "list_identity_census.run(...) не зовётся в "
                      "findings_bridge.main — артефакт будет писать только рука")

    def test_positive_control_a_mention_is_not_a_call(self):
        """Обратная сторона МЕРКИ: упоминание имени ей не годится."""
        mention = ("def main(argv=None):\n"
                   "    # list_identity_census тут только назван\n"
                   "    x = 'list_identity_census.run(root=1)'\n"
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

    def test_slo_is_looser_than_the_tact_of_the_census_itself(self):
        """Срок годности НЕ имеет права истекать раньше собственного такта.

        Положительный контроль класса: поставь здесь 168ч (ровно такт) — и
        артефакт объявлялся бы протухшим в ту самую минуту, когда ему только
        предстоит перемериться, то есть сторож свежести краснел бы на
        ИСПРАВНОМ контуре каждую неделю.
        """
        art = next(a for a in _manifest()["artifacts"]
                   if a["path"] == ARTIFACT_REL)
        tact_h = census.MEASUREMENT_TACT_DAYS * 24
        self.assertGreater(art["slo_hours"], tact_h)


class TactIsDecidedByTheFileNotBySchedule(unittest.TestCase):
    """Внутри такта ступень НЕ мерит и НЕ пишет; вне такта — мерит."""

    def setUp(self):
        self._real = census.measure
        self.calls: list = []

        def _spy(data_dir, tree_root, *, now=None):
            self.calls.append((str(data_dir), str(tree_root), now))
            return {"status": "CLEAN", "reason": "-", "advisory": "-",
                    "generated_at": (now or NOW).isoformat(),
                    "counts": {"lists_total": 0, "outcomes": {},
                               "singletons": 0, "scalar_lists_multi": 0,
                               "denominator_of_finding": 0,
                               "candidate_fields_outside": {},
                               "candidate_field_strength": {},
                               "finding_rows": [], "truncated_readers": [],
                               "unmeasured_causes": {}, "readers_measured": 1,
                               "named_fields": {}}}

        census.measure = _spy

    def tearDown(self):
        census.measure = self._real

    def _root(self, stamp: dt.datetime | None):
        tmp = tempfile.mkdtemp(prefix="spa_g35_")
        data = Path(tmp) / "data"
        data.mkdir()
        if stamp is not None:
            (data / census.ARTIFACT).write_text(
                json.dumps({"generated_at": stamp.isoformat(),
                            "status": "FINDING", "marker": "ПРЕЖНИЙ"}),
                encoding="utf-8")
        return Path(tmp)

    def test_inside_the_tact_nothing_is_measured_and_nothing_is_written(self):
        root = self._root(NOW - dt.timedelta(days=1))
        before = (root / "data" / census.ARTIFACT).read_bytes()
        outcome = census.run(root, now=NOW)
        self.assertFalse(outcome["measured"])
        self.assertEqual(self.calls, [], "внутри такта перепись всё же позвали")
        self.assertEqual(before, (root / "data" / census.ARTIFACT).read_bytes())
        self.assertIn("дн", outcome["reason"])

    def test_not_measured_is_not_a_verdict(self):
        """Инв. #17: «не мерили» обязано быть отличимо от «измерено и чисто»."""
        outcome = census.run(self._root(NOW - dt.timedelta(hours=2)), now=NOW)
        self.assertNotIn("doc", outcome)
        self.assertNotIn("status", outcome)

    def test_outside_the_tact_it_measures_and_rewrites(self):
        root = self._root(NOW - dt.timedelta(days=census.MEASUREMENT_TACT_DAYS + 1))
        outcome = census.run(root, now=NOW)
        self.assertTrue(outcome["measured"])
        self.assertEqual(len(self.calls), 1)
        written = json.loads((root / "data" / census.ARTIFACT)
                             .read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "CLEAN")
        self.assertNotIn("marker", written)

    def test_missing_artifact_measures_rather_than_skips(self):
        """Fail-safe направление: отсутствие отметки — не «свежо»."""
        outcome = census.run(self._root(None), now=NOW)
        self.assertTrue(outcome["measured"])
        self.assertEqual(len(self.calls), 1)

    def test_write_can_be_switched_off_without_touching_the_tact(self):
        root = self._root(None)
        outcome = census.run(root, now=NOW, write=False)
        self.assertTrue(outcome["measured"])
        self.assertFalse((root / "data" / census.ARTIFACT).exists())


class OfficeReadsItAndNotVacuously(unittest.TestCase):
    """Читатель обязан ПЕЧАТАТЬ числа, а не просто открывать файл."""

    def setUp(self):
        self.office = _office()

    def _lines(self, doc, name=ARTIFACT_REL):
        return self.office._summarize_json(name, doc, now=NOW,
                                          root=str(REPO), artifact_root=str(REPO))

    def test_named_branch_prints_the_denominator_before_the_numerator(self):
        text = "\n".join(self._lines(_finding_doc()))
        self.assertIn("ЗНАМЕНАТЕЛЬ", text)
        self.assertIn("ОСМЫСЛЕН (словари, длина > 1): 3", text)
        self.assertLess(text.index("ЗНАМЕНАТЕЛЬ"), text.index("НАХОДКА"),
                        "числитель напечатан раньше знаменателя")

    def test_a_finding_is_marked_so_the_reader_acts(self):
        self.assertIn("⚠️", "\n".join(self._lines(_finding_doc())))

    def test_clean_is_not_dressed_as_a_finding(self):
        doc = _finding_doc()
        doc["status"] = "CLEAN"
        doc["reason"] = "ни один список без личности не имеет годного поля"
        doc["counts"]["candidate_fields_outside"] = {}
        doc["counts"]["finding_rows"] = []
        text = "\n".join(self._lines(doc))
        self.assertNotIn("⚠️", text)
        self.assertIn("[ОПОРА]", text)

    def test_unmeasured_says_the_reason_and_claims_no_numbers(self):
        text = "\n".join(self._lines(_unmeasured_doc()))
        self.assertIn("[НЕ ИЗМЕРЕНО]", text)
        self.assertIn("стенд не построен", text)
        self.assertNotIn("ЗНАМЕНАТЕЛЬ", text)

    def test_the_read_is_not_hollow(self):
        lines = self._lines(_finding_doc())
        self.assertFalse(any(l.startswith(self.office._HOLLOW_MARK)
                             for l in lines))

    def test_positive_control_without_the_branch_the_read_degenerates(self):
        """Что именно делает чтение содержательным — ВЕТКА, а не наличие файла.

        Замер, а не догадка: тот же документ под невведённым именем уходит в
        общий путь, и оттуда выходит ОДНО СЛОВО статуса с причиной. Слово
        верное и бесполезное — знаменателя нет, непозванных читателей нет,
        силы свидетельства нет; ровно то состояние, из которого шаг 0-офис
        уже однажды вытаскивали поимённой веткой (`shadow_trigger_evaluation`,
        цикл #487: «NOT_READY» одинаково звучало на «копим дни» и на «взвод
        недостижим никаким ожиданием»).

        Первая редакция этого контроля утверждала, что чтение станет
        ХОЛОСТЫМ, — и была неверна: общий путь печатает `status` и `reason`,
        поэтому ресит пишется, а число не доезжает. Ошибка найдена прогоном,
        а не перечитыванием, и разница существенная: холостое чтение видно
        сторожу (`⚠️ ПРОЧИТАН ВХОЛОСТУЮ`), а выродившееся — НЕТ.
        """
        lines = self._lines(_finding_doc(),
                            name="data/list_identity_census_NOT_WIRED.json")
        text = "\n".join(lines)
        self.assertIn("статус: FINDING", text)
        for absent in ("ЗНАМЕНАТЕЛЬ", "макс. длина", "[НЕ ИЗМЕРЕНО]", "[ПОЗВАНО]"):
            self.assertNotIn(absent, text,
                             f"общий путь напечатал {absent!r} — тогда мерка "
                             f"выше не про ветку")
        self.assertFalse(any(l.startswith(self.office._HOLLOW_MARK)
                             for l in lines),
                         "выродившееся чтение не холостое, и это главное: "
                         "сторож холостого чтения его НЕ увидит")

    def test_truncation_is_said_aloud(self):
        doc = _finding_doc()
        doc["counts"]["finding_rows"] = [
            {"module": f"m.{i}", "coord": ".x", "n": 3, "candidates": ["day"]}
            for i in range(9)]
        text = "\n".join(self._lines(doc))
        self.assertIn("ещё", text)
        self.assertIn(census.ARTIFACT, text)

    def test_shortened_field_list_leads_with_LENGTH_not_frequency(self):
        """Укорочение сделало ПОРЯДОК утверждением (ADR-410: сила = длина).

        В фикстуре `forward_date` встречается семь раз при длине 7, а `source`
        — один раз при длине 210. Частотный порядок поставил бы во главе
        слабейшее свидетельство, и читатель, видящий только голову списка,
        получил бы обратное правде.
        """
        line = next(l for l in census.format_report(_finding_doc(), max_fields=1)
                    if "[НАХОДКА]" in l)
        self.assertIn("source", line)
        self.assertNotIn("forward_date", line)
        self.assertIn("ещё 1", line)


class DeclaredSchemaIsWhatTheBranchActuallyReads(unittest.TestCase):
    """Объявленная форма сверяется с ЧТЕНИЕМ, а не с добрым словом.

    Дифференциальный замер: у полного документа убирается ОДНО объявленное
    поле, и вывод читателя обязан измениться. Поле, объявленное и никем не
    читаемое, — украшение схемы; поле, читаемое и не объявленное, уезжает из
    тревоги «СХЕМА РАЗОШЛАСЬ» (класс ADR-325).
    """

    def setUp(self):
        self.office = _office()
        self.declared = self.office._READ_SCHEMA["list_identity_census.json"]

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

        Батарея цикла #628 показала, что снятие САМОГО объявления не красит
        ничего: сосед перебирает объявленные поля, и поле, вычеркнутое из
        объявления, просто выпадает из его цикла. Тогда объявление — то самое
        украшение, которое сосед ищет у других, только на уровень выше.

        Меряется ИСХОД: у документа убрано `invoked_by`, и тревога о форме
        обязана НАЗВАТЬ это поле. Строка отрисовки (`[ЗВАВШИЙ] … НЕ ЗАПИСАНО`)
        из счёта исключена намеренно — она называет то же поле и без всякого
        объявления, то есть приняла бы мутацию за живого сторожа.
        """
        text = self._text(_drop(_finding_doc(), "invoked_by"))
        named_by_the_schema_alarm = [
            line for line in text.splitlines()
            if "invoked_by" in line and not line.startswith("[ЗВАВШИЙ]")
        ]
        self.assertTrue(named_by_the_schema_alarm,
                        "поле пропало из документа, а тревога о ФОРМЕ промолчала "
                        f"— объявление в `_READ_SCHEMA` ничего не держит:\n{text}")

    def test_the_producer_writes_every_declared_field(self):
        src = (REPO / "spa_core" / "monitoring"
               / "list_identity_census.py").read_text(encoding="utf-8")
        missing = [p for p in self.declared
                   if f'"{p.split(".")[-1]}"' not in src]
        self.assertEqual(missing, [], f"объявлено, а производитель не пишет: {missing}")

    def test_the_producer_map_points_at_a_file_that_exists(self):
        rel = self.office._PRODUCER["list_identity_census.json"]
        self.assertTrue((REPO / rel).exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
