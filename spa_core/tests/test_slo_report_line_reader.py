"""ВОСЬМАЯ секция `slo_keepability` — ДОЙДЁТ ЛИ СТРОКА ОТЧЁТА до цикла (ADR-823).

Заказ G822 пп. 1–2 запретил платить за четыре дешёвые правки прежде, чем
спрошена их ЦЕНА, и назвал меру той же, что у ADR-822: **ИСХОДОМ, не
структурой.** Поэтому ни один тест здесь не разбирает текст двери: все пробы
поднимают НАСТОЯЩУЮ дверь (`scripts/consume_office_reports.py`) и НАСТОЯЩИЕ
модули производителей, а вердикт берётся из того, что оказалось в ВЫВОДЕ двери.

Два урока предшественников держат форму этого набора:

* «контроль строки на словаре РУКАМИ мерит свой словарь» (мутация «секция под
  другим именем» пережила два прогона подряд у ADR-820/821) ⇒ класс
  `WiringIsMeasuredNotDeclared` зовёт настоящий `measure()` и спрашивает
  ПРИСУТСТВИЕ ключа;
* «проверка, зелёная при любом значении» (ADR-822: `assertIn("НЕ ИЗМЕРЕНО")`
  было пустой проверкой) ⇒ класс `ProbeIsNotVacuous` доказывает, что ПУСТАЯ
  проба отвергается, а не принимается за «дошла», и что у переписи есть
  ОТРИЦАТЕЛЬНЫЙ исход на живом дереве.

Положительный контроль класса — `IncidentOf26October`: он воспроизводит аварию
на НАСТОЯЩЕЙ двери, откатив в её КОПИИ ровно ту правку, которой авария закрыта,
и требует ПРОТИВОПОЛОЖНЫХ вердиктов у двух сцен. Не применился откат ⇒ громкий
отказ «предпосылка НЕ ОБЕСПЕЧЕНА», а не скип (урок #465: скип неотличим от
«прошло»).

Время — ВХОД, а не окружение (`.claude/rules/deployment.md`, приём №1): якорь
`_ANCHOR` уезжает параметром `now=` в каждую отрисовку и в `measure()`, отметки
сцен считаются ОТ ЭТОГО ЖЕ якоря.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — `_ANCHOR` уезжает параметром `now=` в
# `report_line_observation`, `report_line_census` и `measure()`, а отметки сцен
# (`_stamp_of`, `_doc`) вычисляются ОТ ЭТОГО ЖЕ якоря: закреплены обе стороны
# сравнения, настенных часов в файле нет ни одного зова.
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import slo_keepability as keep
from spa_core.monitoring import slo_proposal as prop

_REPO = Path(__file__).resolve().parents[2]
_ANCHOR = datetime(2026, 10, 26, 18, 0, 0, tzinfo=timezone.utc)
#: Артефакт, чью отрисовку дверь СПРАШИВАЕТ и чьи строки печатает (замер 26.10:
#: таких 88).
_ASKED_ARTIFACT = "list_identity_census.json"
#: Артефакт аварии 26.10: его `format_report` отдаёт ОДНУ СТРОКУ, и до правки
#: ADR-823 дверь раскладывала её ПОСИМВОЛЬНО.
_SHRED_ARTIFACT = "vacuous_advice_census.json"
#: Артефакт, чью отрисовку дверь не спрашивает НИ РАЗУ — печатает своими
#: строками (замер 26.10: таких 36).
_NOT_ASKED_ARTIFACT = "artifact_freshness.json"
#: Имя, которого в карте производителей двери нет вовсе.
_UNNAMED_ARTIFACT = "zz_no_such_office_artifact_7f3a.json"
#: Байты, которыми авария 26.10 жила в двери, и байты, которыми она закрыта.
_INCIDENT_BYTES = "out.extend(str(_vac_report(data)).splitlines())"
_FIXED_BYTES = "out.extend(_vac_report(data))"


def _stamp_of(moment: datetime) -> str:
    """Отметка ОТ ЯКОРЯ — а не от настенных часов (приём №1)."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _doc(moment: datetime | None = None, **extra) -> dict:
    doc = {"status": "CLEAN",
           "generated_at": _stamp_of(moment or (_ANCHOR - timedelta(hours=1))),
           "counts": {}}
    doc.update(extra)
    return doc


def _advice_doc(moment: datetime | None = None) -> dict:
    """Документ производителя аварии — в форме, которую он умеет отрисовать.

    Поля взяты у НАСТОЯЩЕЙ отрисовки (`vacuous_advice_census.format_report`
    читает их по ключу и падает без них): документ-сцена обязан быть тем, что
    производитель умеет печатать, иначе проба мерила бы отказ производителя, а
    не судьбу строки.
    """
    return _doc(moment, status="OK", books={
        "conservative": {"brief_available": True, "declared_weighed": True,
                         "declared_reason": "проба", "declared_unchanged_days": 1,
                         "tape": {"records": 2, "days": 2, "days_with_legs": 1,
                                  "streak_days": 1, "outcomes": {}}}},
        books_measured=1, records_total=2, vacuous_records=1, findings=[],
        reason=None)


class ReportLineVerdicts(unittest.TestCase):
    """Шесть исходов двери вердикта, каждый своей сценой (инв. #17)."""

    def test_read_when_the_probe_came_as_a_line_of_its_own(self):
        kind, why = prop.report_line(True, True, addressed=True, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_READ)
        self.assertIn("ОТДЕЛЬНОЙ строкой", why)

    def test_shredded_when_the_letters_arrived_and_the_line_did_not(self):
        kind, why = prop.report_line(False, True, addressed=True, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_SHREDDED)
        self.assertIn("ПОСИМВОЛЬНО", why)

    def test_dropped_when_the_rendering_was_asked_and_nothing_arrived(self):
        kind, why = prop.report_line(False, False, addressed=True, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_DROPPED)
        self.assertIn("уронили", why)

    def test_never_asked_is_its_own_outcome_not_a_dropped_line(self):
        kind, why = prop.report_line(False, False, addressed=True, asked=False)
        self.assertEqual(kind, prop.REPORT_RENDERING_NOT_ASKED)
        self.assertIn("веткой двери", why)

    def test_not_addressed_is_a_measured_answer_not_unmeasured(self):
        kind, why = prop.report_line(None, None, addressed=False, asked=None)
        self.assertEqual(kind, prop.REPORT_LINE_NOT_ADDRESSED)
        self.assertIn("НЕ следует", why)

    def test_unmeasured_when_addressedness_itself_is_unmeasured(self):
        kind, why = prop.report_line(True, True, addressed=None, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_unmeasured_when_the_rendering_did_not_happen(self):
        kind, why = prop.report_line(None, None, addressed=True, asked=None)
        self.assertEqual(kind, prop.REPORT_LINE_UNMEASURED)
        self.assertIn("не состоялась", why)

    def test_unmeasured_when_the_line_is_known_but_the_letters_are_not(self):
        """Причина проверяется ДОСЛОВНО: соседний сторож (род) даёт ТОТ ЖЕ
        вердикт, и без причины мутация «не измерено = букв нет» невидима."""
        kind, why = prop.report_line(False, None, addressed=True, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_UNMEASURED)
        self.assertIn("пришла ли ВООБЩЕ", why)

    def test_unmeasured_when_nothing_arrived_and_asking_is_unmeasured(self):
        kind, why = prop.report_line(False, False, addressed=True, asked=None)
        self.assertEqual(kind, prop.REPORT_LINE_UNMEASURED)
        self.assertIn("лечатся разным", why)

    # Каждый род-вход — СВОЙ метод, а не ветка `subTest`: утверждение под
    # `subTest` НЕВИДИМО мутациям по дельте (они сравнивают набор упавших
    # ИМЁН), и четыре мутации про род входов пережили первый прогон именно
    # поэтому — носитель claim был, а имени у него не было.
    def test_a_non_boolean_line_outcome_is_unmeasured_never_read(self):
        kind, why = prop.report_line("да", True, addressed=True, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_UNMEASURED)
        self.assertIn("ОТДЕЛЬНОЙ строкой не разобран", why)

    def test_a_non_boolean_letters_outcome_is_unmeasured_never_shredded(self):
        kind, why = prop.report_line(False, "нет", addressed=True, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_UNMEASURED)
        self.assertIn("в склейке вывода не разобран", why)

    def test_a_non_boolean_asking_is_unmeasured_never_dropped(self):
        kind, why = prop.report_line(False, False, addressed=True, asked="ага")
        self.assertEqual(kind, prop.REPORT_LINE_UNMEASURED)
        self.assertIn("не разобрано", why)

    def test_a_non_boolean_addressedness_is_unmeasured_never_addressed(self):
        kind, why = prop.report_line(True, True, addressed="да", asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_UNMEASURED)
        self.assertIn("не разобрана", why)

    def test_every_outcome_has_its_own_name(self):
        names = {prop.REPORT_LINE_READ, prop.REPORT_LINE_SHREDDED,
                 prop.REPORT_LINE_DROPPED, prop.REPORT_RENDERING_NOT_ASKED,
                 prop.REPORT_LINE_NOT_ADDRESSED, prop.REPORT_LINE_UNMEASURED}
        self.assertEqual(len(names), 6)


class OrderOfQuestionsIsAsymmetric(unittest.TestCase):
    """Порядок вопросов обоснован, и каждый порядок проверен своей сценой."""

    def test_not_addressed_beats_any_rendering_outcome(self):
        """Отрисовка для артефакта, которого дверь не зовёт, — ответ про зов,
        которого не бывает."""
        kind, _ = prop.report_line(True, True, addressed=False, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_NOT_ADDRESSED)

    def test_a_line_of_its_own_beats_the_letters(self):
        """«Пришла строкой» — сильнейшее свидетельство, и уступать его слабому
        было бы занижением."""
        kind, _ = prop.report_line(True, False, addressed=True, asked=True)
        self.assertEqual(kind, prop.REPORT_LINE_READ)

    def test_asking_decides_only_in_the_absence_of_arrival(self):
        self.assertEqual(
            prop.report_line(True, True, addressed=True, asked=False)[0],
            prop.REPORT_LINE_READ)
        self.assertEqual(
            prop.report_line(False, True, addressed=True, asked=False)[0],
            prop.REPORT_LINE_SHREDDED)


class ProbeIsNotVacuous(unittest.TestCase):
    """ПУСТАЯ проба сделала бы вердикт зелёным при любом значении."""

    def test_the_probe_constant_is_not_empty(self):
        self.assertTrue(keep.REPORT_LINE_PROBE)

    def test_an_empty_probe_is_refused_not_counted_as_read(self):
        door, why = keep.stamp_reader_door(_REPO)
        self.assertIsNotNone(door, why)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / _ASKED_ARTIFACT
            path.write_text(json.dumps(_doc()), encoding="utf-8")
            obs = keep.report_line_observation(
                door, "spa_core.monitoring.list_identity_census", path,
                root=_REPO, artifact_root=Path(folder), probe="", now=_ANCHOR)
        self.assertIsNone(obs["as_line"])
        self.assertIn("ПУСТА", obs["why"])

    def test_the_probe_sits_where_the_proposed_edit_would_sit(self):
        """Место пробы — место правки: у одиннадцати читающих строка звавшего
        стои́т вторым элементом списка."""
        self.assertEqual(keep.REPORT_LINE_POSITION, 1)


class SpyRecordsWhatTheDoorAsked(unittest.TestCase):
    """`asked` мерится НАБЛЮДЕНИЕМ зова, а не разбором текста двери."""

    class _Fake:
        __name__ = "spa_fake_producer"
        CONSTANT = 7

        @staticmethod
        def format_report(doc):
            return ["первая", "вторая"]

        @staticmethod
        def tick_hours(doc):
            return 3.5

        @staticmethod
        def one_line(doc):
            return "одна строка\nвторая"

    def _spy(self):
        return keep._RenderingSpy(self._Fake, "ПРОБА")

    def test_a_list_rendering_gets_the_probe_at_the_edit_position(self):
        spy = self._spy()
        self.assertEqual(spy.format_report({}), ["первая", "ПРОБА", "вторая"])
        self.assertEqual(spy.invoked, ["format_report"])

    def test_a_string_rendering_gets_the_probe_as_its_second_line(self):
        spy = self._spy()
        self.assertEqual(spy.one_line({}).splitlines(),
                         ["одна строка", "ПРОБА", "вторая"])
        self.assertEqual(spy.invoked, ["one_line"])

    def test_a_non_text_return_is_not_a_rendering_and_is_said_so(self):
        """«Позвала помощника, отдающего число» НЕ есть «позвала отрисовку и
        уронила строку»."""
        spy = self._spy()
        self.assertEqual(spy.tick_hours({}), 3.5)
        self.assertEqual(spy.invoked, [])
        self.assertEqual(spy.non_text, ["tick_hours"])

    def test_access_and_invocation_are_two_observations(self):
        spy = self._spy()
        self.assertEqual(spy.CONSTANT, 7)
        self.assertEqual(spy.accessed, ["CONSTANT"])
        self.assertEqual(spy.invoked, [])

    def test_the_real_module_is_put_back_after_the_observation(self):
        door, why = keep.stamp_reader_door(_REPO)
        self.assertIsNotNone(door, why)
        name = "spa_core.monitoring.list_identity_census"
        before = sys.modules.get(name)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / _ASKED_ARTIFACT
            path.write_text(json.dumps(_doc()), encoding="utf-8")
            keep.report_line_observation(door, name, path, root=_REPO,
                                         artifact_root=Path(folder), now=_ANCHOR)
        self.assertIs(sys.modules.get(name), before)
        self.assertNotIsInstance(sys.modules.get(name), keep._RenderingSpy)

    def test_the_real_module_is_put_back_even_when_the_door_refuses(self):
        class Refusing:
            @staticmethod
            def _summarize_json(*args, **kwargs):
                raise RuntimeError("дверь отказала")

        name = "spa_core.monitoring.list_identity_census"
        before = sys.modules.get(name)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / _ASKED_ARTIFACT
            path.write_text(json.dumps(_doc()), encoding="utf-8")
            obs = keep.report_line_observation(
                Refusing, name, path, root=_REPO,
                artifact_root=Path(folder), now=_ANCHOR)
        self.assertIsNone(obs["as_line"])
        self.assertIn("дверь отказала", obs["why"])
        self.assertIs(sys.modules.get(name), before)


class ProducerComesFromTheDoorsOwnMap(unittest.TestCase):
    """Своя копия карты «артефакт → модуль» разошлась бы с дверью молча."""

    def test_the_door_names_the_module_it_actually_imports(self):
        door, why = keep.stamp_reader_door(_REPO)
        self.assertIsNotNone(door, why)
        name, why = keep.report_line_producer(door, f"data/{_SHRED_ARTIFACT}")
        self.assertEqual(name, "spa_core.monitoring.vacuous_advice_census")
        self.assertEqual(why, "")

    def test_an_artifact_outside_the_map_is_unmeasured_not_producerless(self):
        door, _ = keep.stamp_reader_door(_REPO)
        name, why = keep.report_line_producer(door, f"data/{_UNNAMED_ARTIFACT}")
        self.assertIsNone(name)
        self.assertIn("НЕ «отрисовки нет»", why)

    def test_a_door_without_the_map_is_unmeasured_with_its_OWN_cause(self):
        """Причина проверяется ДОСЛОВНО: «карты нет вовсе» и «артефакта в карте
        нет» — разные положения дел, и обе строки называют `_PRODUCER`."""
        class Bare:
            pass

        name, why = keep.report_line_producer(Bare, "data/anything.json")
        self.assertIsNone(name)
        self.assertIn("нет карты", why)
        self.assertNotIn("не называет производителя", why)

    def test_a_non_python_path_in_the_map_is_unmeasured_not_a_module(self):
        class Odd:
            _PRODUCER = {"anything.json": "spa_core/monitoring/whatever.txt"}

        name, why = keep.report_line_producer(Odd, "data/anything.json")
        self.assertIsNone(name)
        self.assertIn("не называет производителя", why)


class ObservationOnTheRealDoor(unittest.TestCase):
    """Замер ИСХОДОМ: НАСТОЯЩАЯ дверь, НАСТОЯЩИЕ модули производителей."""

    @classmethod
    def setUpClass(cls):
        cls.door, why = keep.stamp_reader_door(_REPO)
        assert cls.door is not None, why

    def _observe(self, name: str, module: str, payload) -> dict:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_text(payload if isinstance(payload, str)
                            else json.dumps(payload), encoding="utf-8")
            return keep.report_line_observation(
                self.door, module, path, root=_REPO,
                artifact_root=Path(folder), now=_ANCHOR)

    def test_an_asked_rendering_carries_the_probe_as_a_line(self):
        obs = self._observe(_ASKED_ARTIFACT,
                            "spa_core.monitoring.list_identity_census", _doc())
        self.assertTrue(obs["as_line"], obs["why"])
        self.assertTrue(obs["asked"], obs["why"])
        self.assertIn("format_report", obs["rendering"] or [])

    def test_a_door_that_prints_its_own_lines_never_asks_the_producer(self):
        obs = self._observe(_NOT_ASKED_ARTIFACT,
                            "spa_core.monitoring.artifact_freshness", _doc())
        self.assertFalse(obs["as_line"], obs["why"])
        self.assertFalse(obs["anywhere"], obs["why"])
        self.assertFalse(obs["asked"], obs["why"])

    def test_an_absent_carrier_is_unmeasured_not_a_mute_line(self):
        with tempfile.TemporaryDirectory() as folder:
            obs = keep.report_line_observation(
                self.door, "spa_core.monitoring.list_identity_census",
                Path(folder) / "nope.json", root=_REPO,
                artifact_root=Path(folder), now=_ANCHOR)
        self.assertIsNone(obs["as_line"])
        self.assertIn("носителя нет", obs["why"])

    def test_an_unparseable_carrier_is_unmeasured_not_a_mute_line(self):
        obs = self._observe(_ASKED_ARTIFACT,
                            "spa_core.monitoring.list_identity_census", "{не json")
        self.assertIsNone(obs["as_line"])
        self.assertIn("не разобран", obs["why"])

    def test_access_without_a_call_is_not_a_question_about_the_rendering(self):
        """`asked` мерится ЗОВОМ, а не доступом: население этого состояния на
        живом дереве — НОЛЬ (замер 26.10), поэтому сцена строится дверью-входом.

        Предмет здесь — проводка самого наблюдения (какое из двух наблюдений
        соглядатая становится `asked`), и дверь ей ВХОД: своя дверь в роли
        входа — не «свой словарь вместо проводки», а единственный способ
        достичь состояния, которого в дереве сегодня нет.
        """
        class Peeking:
            @staticmethod
            def _summarize_json(path, data, **kwargs):
                import sys as _sys
                module = _sys.modules["spa_core.monitoring.list_identity_census"]
                return [f"дверь взяла константу: {getattr(module, 'ARTIFACT')}"]

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / _ASKED_ARTIFACT
            path.write_text(json.dumps(_doc()), encoding="utf-8")
            obs = keep.report_line_observation(
                Peeking, "spa_core.monitoring.list_identity_census", path,
                root=_REPO, artifact_root=Path(folder), now=_ANCHOR)
        self.assertEqual(obs["accessed"], ["ARTIFACT"])
        self.assertFalse(obs["asked"], obs)
        self.assertFalse(obs["as_line"], obs)
        kind, _ = prop.report_line(obs["as_line"], obs["anywhere"],
                                   addressed=True, asked=obs["asked"])
        self.assertEqual(kind, prop.REPORT_RENDERING_NOT_ASKED)

    def test_a_module_that_does_not_import_is_unmeasured_with_a_cause(self):
        obs = self._observe(_ASKED_ARTIFACT,
                            "spa_core.monitoring.zz_no_such_module_7f3a", _doc())
        self.assertIsNone(obs["as_line"])
        self.assertIn("не ввозится", obs["why"])


class IncidentOf26October(unittest.TestCase):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария воспроизводится на НАСТОЯЩЕЙ двери.

    Две сцены отличаются РОВНО теми байтами двери, которыми авария закрыта, и
    отвечают ПРОТИВОПОЛОЖНОЕ. Проверка, никогда не видевшая настоящей поломки,
    есть украшение (`.claude/rules/deployment.md`).
    """

    _SOURCE = _REPO / "scripts" / "consume_office_reports.py"

    def _door_with(self, text: str, folder: str):
        """Дверь из КОПИИ настоящего файла. `root` остаётся настоящим: сцены
        обязаны различаться только байтами двери."""
        scripts = Path(folder) / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        target = scripts / "consume_office_reports.py"
        target.write_text(text, encoding="utf-8")
        door, why = keep.stamp_reader_door(Path(folder))
        self.assertIsNotNone(door, why)
        return door

    def _observe(self, door, folder: str) -> dict:
        path = Path(folder) / _SHRED_ARTIFACT
        path.write_text(json.dumps(_advice_doc()), encoding="utf-8")
        return keep.report_line_observation(
            door, "spa_core.monitoring.vacuous_advice_census", path,
            root=_REPO, artifact_root=Path(folder), now=_ANCHOR)

    def test_the_fix_is_in_the_real_door_and_the_incident_bytes_are_not(self):
        text = self._SOURCE.read_text(encoding="utf-8")
        self.assertIn(_INCIDENT_BYTES, text,
                      "предпосылка НЕ ОБЕСПЕЧЕНА: правки ADR-823 в двери нет")
        self.assertEqual(text.count(_INCIDENT_BYTES), 1)

    def test_reverting_the_fix_brings_the_shredded_report_back(self):
        text = self._SOURCE.read_text(encoding="utf-8")
        self.assertEqual(
            text.count(_INCIDENT_BYTES), 1,
            "предпосылка НЕ ОБЕСПЕЧЕНА: откатывать нечего — байты правки не "
            "найдены ровно один раз")
        reverted = text.replace(_INCIDENT_BYTES, _FIXED_BYTES)
        with tempfile.TemporaryDirectory() as folder:
            obs = self._observe(self._door_with(reverted, folder), folder)
        self.assertTrue(obs["asked"], obs["why"])
        self.assertFalse(obs["as_line"], obs["why"])
        self.assertTrue(obs["anywhere"], obs["why"])
        kind, _ = prop.report_line(obs["as_line"], obs["anywhere"],
                                   addressed=True, asked=obs["asked"])
        self.assertEqual(kind, prop.REPORT_LINE_SHREDDED)

    def test_the_real_door_delivers_the_same_report_as_lines(self):
        text = self._SOURCE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as folder:
            obs = self._observe(self._door_with(text, folder), folder)
        self.assertTrue(obs["as_line"], obs["why"])
        kind, _ = prop.report_line(obs["as_line"], obs["anywhere"],
                                   addressed=True, asked=obs["asked"])
        self.assertEqual(kind, prop.REPORT_LINE_READ)

    def test_the_shredding_is_visible_as_one_character_lines(self):
        """Число строк — предмет находки: 731 буква столбиком против шести."""
        text = self._SOURCE.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as folder:
            broken = self._observe(self._door_with(
                text.replace(_INCIDENT_BYTES, _FIXED_BYTES), folder), folder)
        with tempfile.TemporaryDirectory() as folder:
            whole = self._observe(self._door_with(text, folder), folder)
        self.assertGreater(broken["door_lines"], 10 * whole["door_lines"])


class CensusTakesItsPopulationsByReference(unittest.TestCase):
    """Население и адресность берутся у СЕДЬМОЙ секции, не считаются заново."""

    @staticmethod
    def _seventh(rows, findings=None) -> dict:
        return {"status": "OK", "rows": rows,
                "findings": findings if findings is not None
                else [r for r in rows
                      if r.get("reader") == prop.READER_ABSENCE_ONLY]}

    def _census(self, rows, data: Path, findings=None) -> dict:
        return keep.report_line_census(
            self._seventh(rows, findings), _REPO, data, now=_ANCHOR)

    def test_three_outcomes_in_one_census_on_the_real_door(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / _ASKED_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            (data / _NOT_ASKED_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            (data / _UNNAMED_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            doc = self._census([
                {"artifact": f"data/{_ASKED_ARTIFACT}", "addressed": True,
                 "reader": prop.READER_ABSENCE_ONLY},
                {"artifact": f"data/{_NOT_ASKED_ARTIFACT}", "addressed": True,
                 "reader": prop.READER_MUTE},
                {"artifact": f"data/{_UNNAMED_ARTIFACT}", "addressed": True,
                 "reader": prop.READER_MUTE},
            ], data)
        got = {row["artifact"]: row["line"] for row in doc["rows"]}
        self.assertEqual(got[f"data/{_ASKED_ARTIFACT}"], prop.REPORT_LINE_READ)
        self.assertEqual(got[f"data/{_NOT_ASKED_ARTIFACT}"],
                         prop.REPORT_RENDERING_NOT_ASKED)
        self.assertEqual(got[f"data/{_UNNAMED_ARTIFACT}"],
                         prop.REPORT_LINE_UNMEASURED)
        self.assertEqual(doc["inventory_population"], 3)
        self.assertEqual(sum(doc["inventory"].values()), 3)

    def test_addressedness_is_the_seventh_sections_answer_not_a_new_one(self):
        """Строка, объявленная НЕ адресованной, получает исход про адресность —
        даже если дверь этот артефакт в самом деле читает."""
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / _ASKED_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            doc = self._census([{"artifact": f"data/{_ASKED_ARTIFACT}",
                                 "addressed": False,
                                 "reader": prop.READER_NOT_ADDRESSED}], data)
        self.assertEqual(doc["rows"][0]["line"], prop.REPORT_LINE_NOT_ADDRESSED)
        self.assertIsNone(doc["rows"][0]["producer"])

    def test_unmeasured_addressedness_stays_unmeasured_never_false(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            doc = self._census([{"artifact": f"data/{_ASKED_ARTIFACT}",
                                 "addressed": None,
                                 "reader": prop.READER_UNMEASURED}], data)
        self.assertEqual(doc["rows"][0]["line"], prop.REPORT_LINE_UNMEASURED)

    def test_the_two_populations_are_counted_apart(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            for name in (_ASKED_ARTIFACT, _NOT_ASKED_ARTIFACT):
                (data / name).write_text(json.dumps(_doc()), encoding="utf-8")
            doc = self._census([
                {"artifact": f"data/{_ASKED_ARTIFACT}", "addressed": True,
                 "reader": prop.READER_ABSENCE_ONLY},
                {"artifact": f"data/{_NOT_ASKED_ARTIFACT}", "addressed": True,
                 "reader": prop.READER_MUTE},
            ], data)
        self.assertEqual(doc["population_absence_only"], 1)
        self.assertEqual(doc["absence_only_tally"],
                         {prop.REPORT_LINE_READ: 1})
        self.assertEqual(doc["population_mute"], 1)
        self.assertEqual(doc["mute_tally"],
                         {prop.REPORT_RENDERING_NOT_ASKED: 1})

    def _refused(self, section) -> dict:
        doc = keep.report_line_census(section, _REPO, _REPO / "data", now=_ANCHOR)
        self.assertEqual(doc["status"], prop.REPORT_LINE_UNMEASURED)
        self.assertIn("declared_stamp_reader", doc["cause"])
        self.assertIsNone(doc["inventory"])
        self.assertIsNone(doc["population_mute"])
        return doc

    def test_a_refused_seventh_section_leaves_everything_unmeasured(self):
        doc = self._refused({"status": "UNMEASURED", "cause": "дверь молчит"})
        self.assertIn("дверь молчит", doc["cause"])

    def test_a_seventh_section_without_rows_is_unmeasured_not_empty(self):
        self._refused({"status": "OK", "rows": None})

    def test_an_absent_seventh_section_is_unmeasured_not_zero(self):
        self._refused({})
        self._refused(None)

    def test_an_absent_door_tree_is_unmeasured_not_a_clean_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = keep.report_line_census(
                self._seventh([{"artifact": "data/x.json", "addressed": True,
                                "reader": prop.READER_MUTE}]),
                Path(folder), Path(folder), now=_ANCHOR)
        self.assertEqual(doc["status"], prop.REPORT_LINE_UNMEASURED)
        self.assertIn("дверь", doc["cause"])

    def test_findings_are_the_shredded_rows_and_never_the_unasked_ones(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / _NOT_ASKED_ARTIFACT).write_text(json.dumps(_doc()),
                                                    encoding="utf-8")
            doc = self._census([{"artifact": f"data/{_NOT_ASKED_ARTIFACT}",
                                 "addressed": True,
                                 "reader": prop.READER_MUTE}], data)
        self.assertEqual(doc["findings"], [])
        self.assertEqual(doc["inventory"][prop.REPORT_RENDERING_NOT_ASKED], 1)


class LineIsTheOnlyFormAndNeverSilent(unittest.TestCase):
    """Строка отчёта: все шесть чисел, оба населения и имя находки."""

    def test_an_absent_section_says_unmeasured_and_names_the_adr(self):
        line = keep.report_line_line({"status": "OK"})
        self.assertIn("declared_report_line_reader", line)
        self.assertIn("ADR-823", line)

    def test_a_refused_section_prints_its_own_cause(self):
        line = keep.report_line_line({"declared_report_line_reader": {
            "status": prop.REPORT_LINE_UNMEASURED, "cause": "дверь молчит"}})
        self.assertIn("дверь молчит", line)

    def test_an_ok_section_prints_every_number_and_both_populations(self):
        line = keep.report_line_line({"declared_report_line_reader": {
            "status": "OK", "inventory_population": 231,
            "inventory": {prop.REPORT_LINE_READ: 88,
                          prop.REPORT_LINE_SHREDDED: 1,
                          prop.REPORT_RENDERING_NOT_ASKED: 36,
                          prop.REPORT_LINE_NOT_ADDRESSED: 92,
                          prop.REPORT_LINE_UNMEASURED: 14},
            "population_absence_only": 4,
            "absence_only_tally": {prop.REPORT_LINE_READ: 3,
                                   prop.REPORT_LINE_SHREDDED: 1},
            "population_mute": 122,
            "mute_tally": {prop.REPORT_LINE_READ: 74,
                           prop.REPORT_RENDERING_NOT_ASKED: 36},
            "findings": [{"artifact": "data/vacuous_advice_census.json"}]}})
        needles = ("231", "88", "ПОСИМВОЛЬНО у 1", "НЕ СПРАШИВАЕТ у 36",
                   "УРОНИЛА у 0", "НЕ адресовано 92", "НЕ ИЗМЕРЕНО 14",
                   "(4) дошла бы у 3", "посимвольно у 1", "(122)",
                   "отрисовку у 36", "уронила у 0",
                   "data/vacuous_advice_census.json")
        # ОДИН видимый assert, а не ветка на иглу: утверждение под `subTest`
        # невидимо мутациям по дельте.
        self.assertEqual([n for n in needles if n not in line], [], line)

    def test_the_line_says_the_two_questions_are_different(self):
        line = keep.report_line_line({"declared_report_line_reader": {
            "status": "OK", "inventory_population": 1, "inventory": {},
            "population_absence_only": 0, "absence_only_tally": {},
            "population_mute": 0, "mute_tally": {}, "findings": []}})
        self.assertIn("РАЗНЫЕ вопросы", line)


class WiringIsMeasuredNotDeclared(unittest.TestCase):
    """Проводка проверяется НАСТОЯЩИМ `measure()` и `report()`, не словарём."""

    #: Каталог данных — СВОЙ, а не живой `data/` дерева: в worktree его нет ПО
    #: ПОСТРОЕНИЮ (`.gitignore`), и прогон там отвечал бы «носителя нет» у всех
    #: 231 артефакта, то есть мерил бы отсутствие каталога, а не проводку. Три
    #: носителя-сцены дают по одному исходу каждого рода — и РАЗНЫЕ, иначе
    #: «перепись не вакуумна» было бы проверкой, зелёной при любом значении.
    _SCENE = {_ASKED_ARTIFACT: _doc, _NOT_ASKED_ARTIFACT: _doc,
              _SHRED_ARTIFACT: _advice_doc}

    @classmethod
    def setUpClass(cls):
        cls._folder = tempfile.TemporaryDirectory()
        data = Path(cls._folder.name)
        for name, builder in cls._SCENE.items():
            (data / name).write_text(json.dumps(builder()), encoding="utf-8")
        cls.doc = keep.measure(root=_REPO, data_dir=data, now=_ANCHOR)

    @classmethod
    def tearDownClass(cls):
        cls._folder.cleanup()

    def test_measure_carries_the_eighth_section_by_that_very_key(self):
        self.assertIn("declared_report_line_reader", self.doc)
        self.assertIsInstance(self.doc["declared_report_line_reader"], dict)

    def test_the_section_is_measured_on_the_real_tree(self):
        section = self.doc["declared_report_line_reader"]
        self.assertEqual(section["status"], "OK", section.get("cause"))
        self.assertEqual(section["probe"], keep.REPORT_LINE_PROBE)
        self.assertGreater(section["inventory_population"], 100)
        self.assertEqual(sum(section["inventory"].values()),
                         section["inventory_population"])

    def test_the_census_has_both_answers_on_the_real_tree(self):
        """Отрицательный исход на живом дереве не ноль — перепись не вакуумна."""
        section = self.doc["declared_report_line_reader"]
        self.assertGreater(section["inventory"].get(prop.REPORT_LINE_READ, 0), 0)
        self.assertGreater(
            section["inventory"].get(prop.REPORT_RENDERING_NOT_ASKED, 0), 0)

    def test_the_fix_shows_up_as_a_read_line_for_the_incident_artifact(self):
        """Приёмка правки 26.10: тот самый артефакт теперь получает СТРОКУ."""
        rows = {row["artifact"]: row
                for row in self.doc["declared_report_line_reader"]["rows"]}
        row = rows.get(f"data/{_SHRED_ARTIFACT}")
        self.assertIsNotNone(row, sorted(rows)[:5])
        self.assertEqual(row["line"], prop.REPORT_LINE_READ, row["note"])

    def test_report_prints_the_line_from_the_real_measurement(self):
        lines = keep.report(self.doc)
        hit = [line for line in lines if "цена строки отчёта" in line]
        self.assertEqual(len(hit), 1, lines[-8:])
        self.assertIn("ADR-823", hit[0])

    def test_the_axis_is_not_merged_into_the_slo_verdict(self):
        """Заказ G815 п. 2: секция не входит в `tally`/`verdict` ни одним числом."""
        section = self.doc["declared_report_line_reader"]
        for key in section["inventory"]:
            self.assertNotIn(key, self.doc["tally"])

    def test_the_seventh_census_is_computed_exactly_ONCE_per_measure(self):
        """«Ровно один раз» — про ЧИСЛО ЗАМЕРОВ, и ответом его не проверить.

        На устойчивом дереве второй прогон седьмой переписи даёт ТО ЖЕ самое,
        поэтому сравнение чисел эту мутацию не видит (она и пережила первый
        прогон). Мера здесь — НАБЛЮДЁННОЕ число зовов, тот же приём, что у
        соглядатая: претензия про количество обязана мериться количеством.
        """
        calls = []
        real = keep.stamp_reader_census

        def counting(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        keep.stamp_reader_census = counting
        try:
            keep.measure(root=_REPO, data_dir=Path(self._folder.name),
                         now=_ANCHOR)
        finally:
            keep.stamp_reader_census = real
        self.assertEqual(len(calls), 1, calls)

    def test_the_seventh_section_is_measured_exactly_once(self):
        """Второй независимый прогон дал бы два ответа про один артефакт."""
        seventh = self.doc["declared_stamp_reader"]
        eighth = self.doc["declared_report_line_reader"]
        self.assertEqual(eighth["inventory_population"], len(seventh["rows"]))
        self.assertEqual(eighth["population_absence_only"],
                         len(seventh["findings"]))
        self.assertEqual(
            eighth["population_mute"],
            sum(1 for row in seventh["rows"]
                if row.get("reader") == prop.READER_MUTE))


if __name__ == "__main__":
    unittest.main()
