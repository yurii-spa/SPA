"""СЕДЬМАЯ секция `slo_keepability` — КТО ПРОЧТЁТ штамп атрибуции (ADR-822).

Заказ G821 п. 1 запретил предлагать правку, дающую штамп, прежде чем спрошено
у ЧИТАТЕЛЯ, и назвал меру: **ИСХОДОМ, не структурой.** Поэтому ни один тест
здесь не проверяет, объявлено ли поле читаемым: все пробы поднимают
НАСТОЯЩЕГО читателя (`scripts/consume_office_reports.py`) и НАСТОЯЩЕГО
производителя отметки (`spa_core.monitoring.call_provenance`), а вердикт
берётся из РАЗНИЦЫ двух отрисовок.

Урок, из-за которого контроль устроен именно так: у ADR-820 и ADR-821 ОДНА И
ТА ЖЕ мутация пережила первый прогон дважды — «секция попадает в документ под
ДРУГИМ именем», — потому что контроль проверял строку на словаре, собранном
РУКАМИ. Проверка своего словаря проводку не видит. Здесь поэтому есть
отдельный класс `WiringIsMeasuredNotDeclared`, который зовёт настоящий
`measure()` и спрашивает ПРИСУТСТВИЕ ключа.

Время — ВХОД, а не окружение (`.claude/rules/deployment.md`, приём №1): якорь
`_ANCHOR` уезжает параметром `now=` в каждую пробу отрисовки и в `measure()`,
а отметки сцен вычисляются ОТ ЭТОГО ЖЕ якоря (`_stamp_of`), поэтому обе стороны
сравнения закреплены и календарь на вердикт не влияет.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — `_ANCHOR` уезжает параметром `now=` в
# `stamp_reader_observation`, `stamp_reader_census` и `measure()`, а отметки
# сцен (`_stamp_of`, `_doc`) вычисляются ОТ ЭТОГО ЖЕ якоря: закреплены обе
# стороны сравнения, настенных часов в файле нет ни одного зова.
from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import slo_keepability as keep
from spa_core.monitoring import slo_proposal as prop
from spa_core.monitoring import vacuous_advice_census as _absence_only_producer

_REPO = Path(__file__).resolve().parents[2]
_ANCHOR = datetime(2026, 10, 26, 18, 0, 0, tzinfo=timezone.utc)
#: Имя артефакта, чей производитель ПЕЧАТАЕТ звавшего (замер 26.10: 11 таких).
_READ_ARTIFACT = "list_identity_census.json"
#: Имя, которого читатель не знает ни одной ветвью — generic-отрисовка.
_UNKNOWN_ARTIFACT = "zz_no_such_office_artifact_7f3a.json"


def _stamp_of(moment: datetime) -> str:
    """Отметка времени ОТ ЯКОРЯ — а не от настенных часов (приём №1)."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _doc(moment: datetime | None = None) -> dict:
    return {"status": "CLEAN",
            "generated_at": _stamp_of(moment or (_ANCHOR - timedelta(hours=1))),
            "counts": {}}


class StampReaderDoorVerdicts(unittest.TestCase):
    """Шесть исходов двери вердикта, каждый своей сценой (инв. #17)."""

    def test_entry_named_when_output_changed_and_named_the_entry(self):
        kind, why = prop.stamp_reader(True, True, addressed=True)
        self.assertEqual(kind, prop.READER_ENTRY_NAMED)
        self.assertIn("НАЗВАЛ", why)

    def test_absence_only_when_output_changed_but_entry_not_named(self):
        kind, why = prop.stamp_reader(True, False, addressed=True)
        self.assertEqual(kind, prop.READER_ABSENCE_ONLY)
        self.assertIn("ОТСУТСТВИЕ", why)

    def test_mute_when_output_did_not_change_at_all(self):
        kind, why = prop.stamp_reader(False, False, addressed=True)
        self.assertEqual(kind, prop.READER_MUTE)
        self.assertIn("нем", why)

    def test_not_addressed_is_a_measured_answer_not_unmeasured(self):
        kind, why = prop.stamp_reader(None, None, addressed=False)
        self.assertEqual(kind, prop.READER_NOT_ADDRESSED)
        self.assertNotIn("НЕ ИЗМЕРЕНО", why)
        self.assertIn("НЕ следует", why)

    def test_contested_name_is_its_own_outcome(self):
        kind, why = prop.stamp_reader(True, True, addressed=True,
                                      name_contested=True)
        self.assertEqual(kind, prop.READER_NAME_CONTESTED)
        self.assertIn("ИМЕНИ ФАЙЛА", why)

    def test_unmeasured_when_addressedness_itself_is_unmeasured(self):
        kind, why = prop.stamp_reader(True, True, addressed=None)
        self.assertEqual(kind, prop.READER_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_unmeasured_when_rendering_did_not_happen(self):
        """Причина обязана быть ИМЕННО та, что случилась (инв. #17).

        Без этой проверки ветка «отрисовка не состоялась» неотличима от ветки
        «исход отрисовки не разобран»: вердикт у них один, а причины разные, и
        мутация, снявшая первую, пережила первый прогон именно здесь.
        """
        kind, why = prop.stamp_reader(None, None, addressed=True)
        self.assertEqual(kind, prop.READER_UNMEASURED)
        self.assertIn("отрисовка читателя не состоялась", why)
        self.assertNotIn("не разобран", why)

    def test_a_non_boolean_rendering_outcome_names_its_own_cause(self):
        kind, why = prop.stamp_reader("да", True, addressed=True)
        self.assertEqual(kind, prop.READER_UNMEASURED)
        self.assertIn("исход отрисовки не разобран", why)
        self.assertNotIn("не состоялась", why)

    def test_unmeasured_when_differs_is_known_but_naming_is_not(self):
        kind, why = prop.stamp_reader(True, None, addressed=True)
        self.assertEqual(kind, prop.READER_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_non_boolean_inputs_are_unmeasured_never_a_verdict(self):
        for differs, printed, addressed, contested in (
                ("да", True, True, False), (True, "да", True, False),
                (True, True, "да", False), (True, True, True, "да")):
            kind, _why = prop.stamp_reader(differs, printed,
                                           addressed=addressed,
                                           name_contested=contested)
            self.assertEqual(kind, prop.READER_UNMEASURED,
                             f"{differs!r}/{printed!r}/{addressed!r}/{contested!r}")


class OrderOfQuestionsIsAsymmetric(unittest.TestCase):
    """Порядок вопросов — часть вердикта, и обратный порядок БЫЛ БЫ неверен."""

    def test_not_addressed_beats_a_contested_name(self):
        kind, _ = prop.stamp_reader(True, True, addressed=False,
                                    name_contested=True)
        self.assertEqual(kind, prop.READER_NOT_ADDRESSED)

    def test_not_addressed_beats_any_rendering_outcome(self):
        for differs, printed in ((True, True), (False, False), (None, None)):
            kind, _ = prop.stamp_reader(differs, printed, addressed=False)
            self.assertEqual(kind, prop.READER_NOT_ADDRESSED)

    def test_contested_name_beats_a_positive_rendering_outcome(self):
        """Иначе чужая ветка отрисовки приписала бы артефакту читателя."""
        kind, _ = prop.stamp_reader(True, True, addressed=True,
                                    name_contested=True)
        self.assertNotEqual(kind, prop.READER_ENTRY_NAMED)


class ProbeStampComesFromTheRealProducer(unittest.TestCase):
    """Отметка-проба СОБРАНА производителем, а не сложена руками."""

    def test_probe_entry_is_the_sentinel_and_the_stamp_is_measured(self):
        stamp, why = keep.stamp_reader_probe(None)
        self.assertIsNotNone(stamp, why)
        self.assertEqual(stamp["schema"], "call_provenance.v1")
        self.assertTrue(stamp["measured"])
        self.assertEqual(stamp[keep.ATTRIBUTION_ENTRY_FIELD],
                         keep.STAMP_READER_PROBE_NAME)

    def test_probe_leaves_no_file_behind(self):
        stamp, _why = keep.stamp_reader_probe(None)
        self.assertIsNotNone(stamp)
        leaked = list(Path(tempfile.gettempdir()).glob(
            "spa_stamp_reader_*/" + keep.STAMP_READER_PROBE_NAME))
        self.assertEqual(leaked, [], f"проба оставила файл: {leaked}")

    def test_an_unmeasured_producer_is_refused_not_accepted(self):
        """Без инъекции эта ветка недостижима — настоящий производитель молчать
        на существующем файле не умеет, и мутация «принимать неизмеренную
        отметку» пережила первый прогон ровно поэтому."""
        stamp, why = keep.stamp_reader_probe(None, provenance=lambda **_kw: {
            "schema": "call_provenance.v1", "measured": False,
            "reason": "дверь молчала"})
        self.assertIsNone(stamp)
        self.assertIn("не назвал входа", why)
        self.assertIn("дверь молчала", why)

    def test_a_refusing_producer_is_a_cause_not_a_crash(self):
        stamp, why = keep.stamp_reader_probe(
            None, provenance=lambda **_kw: (_ for _ in ()).throw(
                RuntimeError("производитель упал")))
        self.assertIsNone(stamp)
        self.assertIn("производитель отметки отказал", why)

    def test_a_non_string_entry_is_refused(self):
        stamp, why = keep.stamp_reader_probe(None, provenance=lambda **_kw: {
            "schema": "call_provenance.v1", "measured": True, "entry": 7})
        self.assertIsNone(stamp)
        self.assertIn("вход не строкой", why)

    def test_an_unmeasured_probe_stops_the_whole_census_with_a_cause(self):
        doc = keep.stamp_reader_census(
            {"status": "OK", "rows": []},
            [{"label": "com.spa.probe", "intent": "active",
              "produces": [{"artifact": "data/x.json", "slo_hours": 3}]}],
            _REPO, _REPO / "data",
            manifest={"artifacts": []}, now=_ANCHOR,
            provenance=lambda **_kw: {"schema": "call_provenance.v1",
                                      "measured": False, "reason": "молчит"})
        self.assertEqual(doc["status"], prop.READER_UNMEASURED)
        self.assertIn("отметка-проба НЕ СОБРАНА", doc["cause"])
        self.assertIsNone(doc["inventory"])

    def test_the_real_printer_names_the_probe_entry(self):
        """Положительный контроль НУЖДЫ в пробе: печатник её ДЕЙСТВИТЕЛЬНО зовёт."""
        from spa_core.monitoring.call_provenance import describe
        stamp, _why = keep.stamp_reader_probe(None)
        self.assertIn(keep.STAMP_READER_PROBE_NAME, describe(stamp))


class MeasuredDoorIsTheRealReader(unittest.TestCase):
    """Дверь чтения — настоящий файл скрипта, и её отсутствие есть ПРИЧИНА."""

    def test_the_real_reader_loads_and_carries_both_doors(self):
        door, why = keep.stamp_reader_door(_REPO)
        self.assertIsNotNone(door, why)
        self.assertEqual(why, "")
        self.assertTrue(callable(door._summarize_json))
        self.assertTrue(callable(door.office_targets))

    def test_absent_reader_is_unmeasured_with_a_named_cause(self):
        with tempfile.TemporaryDirectory() as folder:
            door, why = keep.stamp_reader_door(Path(folder))
        self.assertIsNone(door)
        self.assertIn("читателя нет в дереве", why)

    def test_a_reader_without_the_door_is_refused_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            scripts = Path(folder) / "scripts"
            scripts.mkdir()
            (scripts / "consume_office_reports.py").write_text(
                "OFFICE = 1\n", encoding="utf-8")
            door, why = keep.stamp_reader_door(Path(folder))
        self.assertIsNone(door)
        self.assertIn("_summarize_json", why)

    def test_cache_key_carries_the_stamp_so_an_edit_is_visible(self):
        """Ключ по одному пути отвечал бы о двери, какой она была при первом зове."""
        with tempfile.TemporaryDirectory() as folder:
            scripts = Path(folder) / "scripts"
            scripts.mkdir()
            target = scripts / "consume_office_reports.py"
            target.write_text(
                "def _summarize_json(*a, **k):\n    return ['один']\n"
                "def office_targets(*a, **k):\n    return []\n", encoding="utf-8")
            first, _ = keep.stamp_reader_door(Path(folder))
            self.assertEqual(first._summarize_json(), ["один"])
            target.write_text(
                "def _summarize_json(*a, **k):\n    return ['два']\n"
                "def office_targets(*a, **k):\n    return []\n", encoding="utf-8")
            # Отметка файла в ключе — иначе вернулась бы первая загрузка.
            second, _ = keep.stamp_reader_door(Path(folder))
            self.assertEqual(second._summarize_json(), ["два"])


class DifferentialObservationOnTheRealReader(unittest.TestCase):
    """Замер ИСХОДОМ: две отрисовки НАСТОЯЩИМ читателем и их разница."""

    @classmethod
    def setUpClass(cls):
        cls.stamp, why = keep.stamp_reader_probe(None)
        assert cls.stamp is not None, why
        cls.door, why = keep.stamp_reader_door(_REPO)
        assert cls.door is not None, why

    def _observe(self, name: str, payload) -> dict:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_text(payload if isinstance(payload, str)
                            else json.dumps(payload), encoding="utf-8")
            return keep.stamp_reader_observation(
                self.door, self.stamp, path, root=_REPO,
                artifact_root=Path(folder), now=_ANCHOR)

    def test_an_artifact_whose_producer_prints_the_caller_is_read(self):
        obs = self._observe(_READ_ARTIFACT, _doc())
        self.assertTrue(obs["differs"], obs["why"])
        self.assertTrue(obs["entry_printed"], obs["why"])

    def test_an_artifact_the_reader_does_not_know_is_mute(self):
        obs = self._observe(_UNKNOWN_ARTIFACT, _doc())
        self.assertFalse(obs["differs"], obs["why"])
        self.assertFalse(obs["entry_printed"], obs["why"])

    def test_a_non_object_root_is_unmeasured_not_mute(self):
        obs = self._observe("zz_array_7f3a.json", "[1, 2]")
        self.assertIsNone(obs["differs"])
        self.assertIn("не объект", obs["why"])

    def test_an_unparseable_carrier_is_unmeasured_not_mute(self):
        obs = self._observe("zz_broken_7f3a.json", "{не json")
        self.assertIsNone(obs["differs"])
        self.assertIn("не разобран", obs["why"])

    def test_an_absent_carrier_is_unmeasured_not_mute(self):
        with tempfile.TemporaryDirectory() as folder:
            obs = keep.stamp_reader_observation(
                self.door, self.stamp, Path(folder) / "nope.json",
                root=_REPO, artifact_root=Path(folder), now=_ANCHOR)
        self.assertIsNone(obs["differs"])
        self.assertIn("носителя нет", obs["why"])

    def test_a_refusing_reader_is_unmeasured_not_a_verdict(self):
        class Boom:
            @staticmethod
            def _summarize_json(*_a, **_k):
                raise RuntimeError("дверь отказала")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / _READ_ARTIFACT
            path.write_text(json.dumps(_doc()), encoding="utf-8")
            obs = keep.stamp_reader_observation(
                Boom, self.stamp, path, root=_REPO,
                artifact_root=Path(folder), now=_ANCHOR)
        self.assertIsNone(obs["differs"])
        self.assertIn("читатель отказал", obs["why"])

    #: Артефакт класса «замечено только ОТСУТСТВИЕ». Его читатель печатает
    #: строку «отчёт СТАРОГО ОБРАЗЦА», когда отметки НЕТ, и НЕ печатает
    #: звавшего, когда она есть. Поля — те, без которых отрисовка этого
    #: артефакта падает; держатся здесь литералом намеренно, чтобы сцена не
    #: зависела от словаря читателя.
    #:
    #: **НАМЕРЕННОЕ ИЗМЕНЕНИЕ ТЕСТА (инв. #16), ADR-825, заказ G825 п. 1.**
    #: На 26.10 носителей этого класса было ЧЕТЫРЕ живых, и сцена брала
    #: любого из них как есть. Цикл #950 закрыл весь класс (замер на живом
    #: `data/`: 4 → 0, `stamp_reader_names_the_entry` 11 → 15), поэтому
    #: НАСТОЯЩЕГО носителя в системе больше НЕТ — и это не ослабление
    #: проверки, а исчезновение дефекта, которым она пользовалась как
    #: сценой. Предмет обеих проб НИЖЕ не менялся ни на слово: он про
    #: НАПРАВЛЕНИЕ замера (ПОЯВЛЕНИЕ отметки против смены её ЗНАЧЕНИЯ), а не
    #: про население класса. Предпосылку сцены теперь обеспечивает ИНЪЕКЦИЯ
    #: читателя отметки у производителя — тот же приём, которым положительный
    #: контроль ADR-825 откатывает свою же проводку
    #: (`test_stamp_reader_four_name_the_entry.py`). Подставлять вердикт или
    #: скипать пробу было бы ровно «не измерено, выданное за ответ».
    _ABSENCE_ONLY_ARTIFACT = "vacuous_advice_census.json"

    @contextlib.contextmanager
    def _producer_that_cannot_read_the_stamp(self):
        """Производитель носителя БЕЗ читателя отметки — предпосылка сцены.

        Откатывается РОВНО одна строка проводки ADR-825: `provenance_line`
        у производителя. Его собственный отчёт при этом остаётся его
        собственным — подменяется не вывод, а читатель отметки, которого у
        него до #950 не было.
        """
        original = _absence_only_producer.provenance_line
        _absence_only_producer.provenance_line = (
            lambda _stamp: "запись о звавшем ЕСТЬ, а читать её нечем")
        try:
            yield
        finally:
            _absence_only_producer.provenance_line = original

    def test_the_absence_only_scene_needs_an_injected_producer_today(self):
        """Положительный контроль САМОЙ предпосылки — в обе стороны.

        Без инъекции носитель класса уже НЕ принадлежит ему (это и есть
        правка #950), с инъекцией — принадлежит. Проба обязана отличать два
        состояния: иначе «сцена построена» стало бы неотличимо от «сцена
        построена не та», и две пробы ниже проверяли бы неизвестно что.
        """
        clean = self._observe(self._ABSENCE_ONLY_ARTIFACT,
                              self._absence_only_doc())
        self.assertTrue(clean["entry_printed"], clean["why"])
        with self._producer_that_cannot_read_the_stamp():
            rolled = self._observe(self._ABSENCE_ONLY_ARTIFACT,
                                   self._absence_only_doc())
        self.assertFalse(rolled["entry_printed"], rolled["why"])

    def _absence_only_doc(self) -> dict:
        return {"status": "CLEAN",
                "generated_at": _stamp_of(_ANCHOR - timedelta(hours=1)),
                "books": {}, "findings": [], "books_measured": {},
                "records_total": 0, "vacuous_records": 0,
                "unreadable": [], "what_it_does_not_prove": [],
                "advisory": "—"}

    def test_an_already_stamped_carrier_is_still_asked_about_APPEARANCE(self):
        """Снятие отметки ПЕРЕД первой отрисовкой — не гигиена, а сам вопрос.

        Сцена различающая: артефакт класса «замечено только ОТСУТСТВИЕ», уже
        несущий отметку. Со снятием вердикт — `READER_ABSENCE_ONLY` (жалоба на
        пропажу появляется в выводе «без отметки»). БЕЗ снятия оба вывода
        несут отметку, жалобы нет ни в одном, выводы совпадают — и вердикт
        становится `READER_MUTE`, то есть прибор отвечает на вопрос «если
        ЗНАЧЕНИЕ сменится» вместо «если отметка ПОЯВИТСЯ».
        """
        doc = self._absence_only_doc()
        doc[keep.ATTRIBUTION_ENTRY_KEY] = {
            "schema": "call_provenance.v1", "measured": True,
            "entry": "zz_a_completely_different_entry_7f3a.py"}
        with self._producer_that_cannot_read_the_stamp():
            obs = self._observe(self._ABSENCE_ONLY_ARTIFACT, doc)
        self.assertTrue(obs["differs"], obs["why"])
        self.assertFalse(obs["entry_printed"], obs["why"])
        kind, _why = prop.stamp_reader(obs["differs"], obs["entry_printed"],
                                       addressed=True)
        self.assertEqual(kind, prop.READER_ABSENCE_ONLY)

    def test_a_clean_carrier_of_the_same_class_gives_the_same_verdict(self):
        """Обратная сторона той же сцены: без отметки вердикт НЕ меняется."""
        with self._producer_that_cannot_read_the_stamp():
            obs = self._observe(self._ABSENCE_ONLY_ARTIFACT,
                                self._absence_only_doc())
        self.assertTrue(obs["differs"], obs["why"])
        self.assertFalse(obs["entry_printed"], obs["why"])

    def test_the_question_is_APPEARANCE_even_when_a_stamp_is_already_there(self):
        """Отметка снимается ПЕРЕД первой отрисовкой — иначе вопрос подменён.

        Без этого у пятнадцати артефактов, уже несущих `invoked_by`, «без
        отметки» означало бы «с настоящей отметкой», и перепись отвечала бы на
        вопрос «если ЗНАЧЕНИЕ сменится», а не «если отметка ПОЯВИТСЯ».
        """
        already = dict(_doc())
        already[keep.ATTRIBUTION_ENTRY_KEY] = {
            "schema": "call_provenance.v1", "measured": True,
            "entry": "zz_a_completely_different_entry_7f3a.py"}
        obs = self._observe(_READ_ARTIFACT, already)
        self.assertTrue(obs["differs"], obs["why"])
        self.assertTrue(obs["entry_printed"], obs["why"])


class CensusOnTheRealDoor(unittest.TestCase):
    """Перепись: исходы, население ССЫЛКОЙ и третий исход у каждого входа."""

    @staticmethod
    def _agents(artifacts) -> list:
        return [{"label": "com.spa.probe", "intent": "active",
                 "produces": [{"artifact": name, "slo_hours": 3}
                              for name in artifacts]}]

    @staticmethod
    def _price(rows) -> dict:
        return {"status": "OK", "rows": rows}

    def _census(self, artifacts, *, price, manifest, data: Path):
        return keep.stamp_reader_census(
            price, self._agents(artifacts), _REPO, data,
            manifest=manifest, now=_ANCHOR)

    def test_read_mute_and_not_addressed_in_one_census(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            for name in (_READ_ARTIFACT, _UNKNOWN_ARTIFACT, "zz_offstage_7f3a.json"):
                (data / name).write_text(json.dumps(_doc()), encoding="utf-8")
            manifest = {"artifacts": [
                {"path": f"data/{_READ_ARTIFACT}", "status": "active",
                 "consumers": ["orchestrator_protocol"]},
                {"path": f"data/{_UNKNOWN_ARTIFACT}", "status": "active",
                 "consumers": ["orchestrator_protocol"]},
                {"path": "data/zz_offstage_7f3a.json", "status": "active",
                 "consumers": ["com.spa.someone_else"]}]}
            names = [f"data/{_READ_ARTIFACT}", f"data/{_UNKNOWN_ARTIFACT}",
                     "data/zz_offstage_7f3a.json"]
            doc = self._census(names, price=self._price(
                [{"artifact": name, "price": prop.STAMP_ONE_EDIT}
                 for name in names]), manifest=manifest, data=data)
        self.assertEqual(doc["status"], "OK")
        got = {row["artifact"]: row["reader"] for row in doc["rows"]}
        self.assertEqual(got[f"data/{_READ_ARTIFACT}"], prop.READER_ENTRY_NAMED)
        self.assertEqual(got[f"data/{_UNKNOWN_ARTIFACT}"], prop.READER_MUTE)
        self.assertEqual(got["data/zz_offstage_7f3a.json"],
                         prop.READER_NOT_ADDRESSED)
        self.assertEqual(doc["inventory_population"], 3)
        self.assertEqual(doc["population"], 3)
        self.assertEqual(doc["tally"][prop.READER_ENTRY_NAMED], 1)

    def test_population_is_only_what_one_edit_would_reach(self):
        """Артефакт, которому штамп НЕ придёт, в население вопроса не входит."""
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / _READ_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            (data / _UNKNOWN_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            manifest = {"artifacts": [
                {"path": f"data/{name}", "status": "active",
                 "consumers": ["orchestrator_protocol"]}
                for name in (_READ_ARTIFACT, _UNKNOWN_ARTIFACT)]}
            doc = self._census(
                [f"data/{_READ_ARTIFACT}", f"data/{_UNKNOWN_ARTIFACT}"],
                price=self._price([
                    {"artifact": f"data/{_READ_ARTIFACT}",
                     "price": prop.STAMP_ONE_EDIT},
                    {"artifact": f"data/{_UNKNOWN_ARTIFACT}",
                     "price": prop.STAMP_OWN_EDIT_NEEDED}]),
                manifest=manifest, data=data)
        self.assertEqual(doc["population"], 1)
        self.assertEqual([row["artifact"] for row in doc["population_rows"]],
                         [f"data/{_READ_ARTIFACT}"])
        # Инвентарь при этом считает ОБА: это ДВА разных числа.
        self.assertEqual(doc["inventory_population"], 2)

    def test_a_broken_sixth_section_leaves_population_unmeasured_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / _READ_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            doc = self._census(
                [f"data/{_READ_ARTIFACT}"],
                price={"status": prop.STAMP_PRICE_UNMEASURED,
                       "cause": "двери НЕ ИЗМЕРЕНЫ"},
                manifest={"artifacts": [
                    {"path": f"data/{_READ_ARTIFACT}", "status": "active",
                     "consumers": ["orchestrator_protocol"]}]},
                data=data)
        self.assertEqual(doc["status"], "OK")
        self.assertIsNone(doc["population"])
        self.assertNotEqual(doc["population"], 0)
        self.assertIn("НЕ ИЗМЕРЕНО", doc["population_cause"])
        self.assertIn("двери НЕ ИЗМЕРЕНЫ", doc["population_cause"])

    def test_an_absent_manifest_leaves_addressedness_unmeasured_not_false(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / _READ_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            doc = self._census([f"data/{_READ_ARTIFACT}"],
                               price=self._price([]), manifest=None, data=data)
        self.assertEqual([row["reader"] for row in doc["rows"]],
                         [prop.READER_UNMEASURED])
        self.assertIn("конституция в перепись не передана", doc["rows"][0]["note"])

    def test_a_contested_basename_gets_its_own_outcome(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            nested = data / "nest"
            nested.mkdir()
            (data / _READ_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            (nested / _READ_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            names = [f"data/{_READ_ARTIFACT}", f"data/nest/{_READ_ARTIFACT}"]
            doc = self._census(names, price=self._price([]), manifest={
                "artifacts": [{"path": name, "status": "active",
                               "consumers": ["orchestrator_protocol"]}
                              for name in names]}, data=data)
        self.assertEqual({row["reader"] for row in doc["rows"]},
                         {prop.READER_NAME_CONTESTED})

    def test_findings_are_absence_only_rows_never_the_mute_ones(self):
        """«Читатель нем» — ОТВЕТ заказа, а не дефект, и находкой быть не должен."""
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / _UNKNOWN_ARTIFACT).write_text(json.dumps(_doc()), encoding="utf-8")
            doc = self._census([f"data/{_UNKNOWN_ARTIFACT}"],
                               price=self._price([]), manifest={"artifacts": [
                                   {"path": f"data/{_UNKNOWN_ARTIFACT}",
                                    "status": "active",
                                    "consumers": ["orchestrator_protocol"]}]},
                               data=data)
        self.assertEqual(doc["rows"][0]["reader"], prop.READER_MUTE)
        self.assertEqual(doc["findings"], [])

    def test_an_empty_constitution_is_unmeasured_not_a_clean_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = keep.stamp_reader_census(
                self._price([]), [], _REPO, Path(folder),
                manifest={"artifacts": []}, now=_ANCHOR)
        self.assertEqual(doc["status"], prop.READER_UNMEASURED)
        self.assertIsNone(doc["inventory"])
        self.assertIn("ни одного объявленного артефакта", doc["cause"])

    def test_an_absent_reader_tree_is_unmeasured_not_a_clean_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = keep.stamp_reader_census(
                self._price([]), self._agents(["data/x.json"]),
                Path(folder), Path(folder), manifest={"artifacts": []},
                now=_ANCHOR)
        self.assertEqual(doc["status"], prop.READER_UNMEASURED)
        self.assertIn("дверь чтения НЕ ОПРОШЕНА", doc["cause"])
        self.assertIsNone(doc["inventory"])


class LineIsTheOnlyFormAndNeverSilent(unittest.TestCase):
    """Строка отчёта: отсутствие секции НАЗЫВАЕТСЯ, а не печатается нулями."""

    def test_an_absent_section_says_unmeasured_and_names_the_adr(self):
        line = keep.stamp_reader_line({})
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("ADR-822", line)

    def test_a_refused_section_prints_its_cause(self):
        line = keep.stamp_reader_line({"declared_stamp_reader": {
            "status": prop.READER_UNMEASURED, "cause": "двери нет в дереве"}})
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("двери нет в дереве", line)

    def test_an_ok_section_prints_both_numbers_and_calls_them_different(self):
        line = keep.stamp_reader_line({"declared_stamp_reader": {
            "status": "OK", "inventory_population": 231,
            "inventory": {prop.READER_ENTRY_NAMED: 11,
                          prop.READER_ABSENCE_ONLY: 4,
                          prop.READER_MUTE: 122,
                          prop.READER_NOT_ADDRESSED: 92,
                          prop.READER_NAME_CONTESTED: 1,
                          prop.READER_UNMEASURED: 1},
            "population": 153,
            "tally": {prop.READER_ENTRY_NAMED: 9},
            "findings": [{"artifact": "data/vacuous_advice_census.json"}]}})
        self.assertIn("231", line)
        self.assertIn("153", line)
        self.assertIn("144 пришли бы НЕМЫМИ", line)
        self.assertIn("data/vacuous_advice_census.json", line)
        self.assertIn("РАЗНЫЕ числа", line)

    def test_an_unmeasured_population_is_not_printed_as_zero(self):
        """Ярлык «НЕ ИЗМЕРЕНО» в строке есть ВСЕГДА (им подписан исход
        инвентаря), поэтому искать его целиком — проверка пустая: именно так
        мутация «население печатается нулём» пережила первый прогон. Спрашивать
        надо ИМЕННО про население и ИМЕННО отсутствие подстановки."""
        line = keep.stamp_reader_line({"declared_stamp_reader": {
            "status": "OK", "inventory_population": 3, "inventory": {},
            "population": None, "tally": {}, "findings": []}})
        self.assertIn("ВОПРОСА (НЕ ИЗМЕРЕНО)", line)
        self.assertNotIn("None", line)
        self.assertNotIn("остальные", line)


class WiringIsMeasuredNotDeclared(unittest.TestCase):
    """Проводка проверяется НАСТОЯЩИМ `measure()` и `report()`, не словарём.

    Тот же урок, из-за которого у ADR-820/821 мутация «секция под другим
    именем» выжила дважды: контроль на словаре, собранном руками, проверяет
    свой словарь. Здесь спрашивается ПРИСУТСТВИЕ ключа в выводе настоящего
    прибора — ключ, переименованный мутацией, роняет этот класс.
    """

    @classmethod
    def setUpClass(cls):
        cls.doc = keep.measure(root=_REPO, data_dir=_REPO / "data", now=_ANCHOR)

    def test_measure_carries_the_seventh_section_by_that_very_key(self):
        self.assertIn("declared_stamp_reader", self.doc)
        self.assertIsInstance(self.doc["declared_stamp_reader"], dict)

    def test_the_section_is_measured_on_the_real_tree(self):
        section = self.doc["declared_stamp_reader"]
        self.assertEqual(section["status"], "OK", section.get("cause"))
        self.assertEqual(section["probe_entry"], keep.STAMP_READER_PROBE_NAME)
        self.assertGreater(section["inventory_population"], 100)
        self.assertEqual(sum(section["inventory"].values()),
                         section["inventory_population"])

    def test_report_prints_the_line_from_the_real_measurement(self):
        lines = keep.report(self.doc)
        hit = [line for line in lines if "читатель штампа атрибуции" in line]
        self.assertEqual(len(hit), 1, lines[-6:])
        self.assertIn("ADR-822", hit[0])

    def test_the_axis_is_not_merged_into_the_slo_verdict(self):
        """Заказ G815 п. 2: секция не входит в `tally`/`verdict` ни одним числом."""
        section = self.doc["declared_stamp_reader"]
        for key in section["inventory"]:
            self.assertNotIn(key, self.doc["tally"])
        self.assertIn(self.doc["verdict"], (
            "every_declared_slo_keepable", "declared_slo_unkeepable",
            "tact_not_observed"))

    def test_the_sixth_section_is_measured_exactly_once(self):
        """Второй независимый прогон дал бы два ответа про один артефакт."""
        price = self.doc["declared_write_stamp_price"]
        reader = self.doc["declared_stamp_reader"]
        if price.get("status") == "OK" and reader.get("population") is not None:
            one_edit = [row for row in price["rows"]
                        if row.get("price") == prop.STAMP_ONE_EDIT]
            self.assertEqual(reader["population"], len(one_edit))

    def test_what_is_not_reported_names_the_single_measured_door(self):
        """Контроль на СТРОКЕ, и это сказано вслух: предмет здесь — сама
        оговорка, а не проводка. Читатель отчёта обязан узнать, что измеренная
        дверь ОДНА, иначе «читателя нет» прочтётся как утверждение о системе.
        Спрашивается присутствие ВСЕХ трёх частей претензии — число дверей,
        имя двери и третий исход у прочих.
        """
        said = " ".join(self.doc.get("not_reported") or [])
        self.assertIn("ADR-822", said)
        self.assertIn("ЧИТАТЕЛЕЙ штампа БОЛЬШЕ ОДНОЙ двери", said)
        self.assertIn("_summarize_json", said)
        self.assertIn("НЕ ИЗМЕРЕНЫ", said)
        self.assertIn("`stamp_reader_door_not_addressed`", said)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
