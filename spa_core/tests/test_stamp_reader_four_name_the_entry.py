# -*- coding: utf-8 -*-
"""Четвёрка ADR-822 УМЕЕТ ПРОЧЕСТЬ штамп атрибуции, а не только пожаловаться.

ADR-825, заказ G825 п. 1. ADR-822 измерил ИСХОДОМ, кто прочтёт
``invoked_by.entry``, если он появится, и нашёл класс из четырёх
производителей: ``call_sourced_input_census`` · ``foreign_markup_reader_census``
· ``unresolved_path_census`` · ``vacuous_advice_census``. У них вывод читателя
от появления отметки МЕНЯЕТСЯ (шаг 0-офис снимает свою строку «отчёт СТАРОГО
ОБРАЗЦА»), а точку входа не называет никто: в ``report()`` каждого было НОЛЬ
зовов ``provenance_line``. То есть объявление научилось жаловаться на
отсутствие записки и не умело её прочесть.

Контроль здесь НЕ на словаре, собранном руками (урок #944/#945: мутация
«секция под другим именем» пережила два цикла подряд именно потому, что
контроль спрашивал свои же строки). Поднимается НАСТОЯЩИЙ прибор седьмой
секции — :func:`slo_keepability.stamp_reader_census` — с НАСТОЯЩЕЙ дверью
чтения (``scripts/consume_office_reports.py``, загружённая по файлу),
НАСТОЯЩЕЙ отметкой-пробой (её собирает ``call_provenance``) и НАСТОЯЩИМ
правилом адресности (``office_targets``). Руками собрана только СЦЕНА — четыре
документа-носителя, — и она есть ВХОД замера, а не его предмет.

Положительный контроль откатывает РОВНО ту строку проводки, которой находка
закрыта, и требует ПРОТИВОПОЛОЖНЫХ ответов на ОДНОЙ сцене: без неё вердикт
обязан вернуться в ``stamp_reader_notices_absence_only`` у всех четырёх.

Литеральных дат здесь нет намеренно: обе отрисовки сцены идут с ОДНИМИ
часами, поэтому любая строка про возраст сокращается в разности, и закреплять
календарь незачем (`.claude/rules/deployment.md`, раздел про время).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import call_sourced_input_census as csi
from spa_core.monitoring import foreign_markup_reader_census as fmrc
from spa_core.monitoring import slo_keepability, slo_proposal
from spa_core.monitoring import unresolved_path_census as upc
from spa_core.monitoring import vacuous_advice_census as vac

_ROOT = Path(__file__).resolve().parents[2]

#: Четвёрка ADR-822: модуль · его артефакт · документ-сцена, который его
#: `format_report` отрисовывает БЕЗ отказа, · строка, по которой видно, что
#: отрисовывал именно ЭТОТ производитель. Последнее поле — защита от мутации
#: «ветка офиса зовёт чужого производителя»: без неё контроль подтвердил бы
#: звавшего, напечатанного кем угодно.
QUARTET = (
    (csi, {
        "status": "CRITICAL", "guards": 1, "inputs": 1, "findings": 0,
        "doors": {}, "places": {}, "sites_seen": 1, "absent_here": 0,
        "latent": 0, "behaviour_measured": 0, "behaviour_disagrees": 0,
        "rows": [],
    }, "перепись входов, собранных ВЫЗОВОМ"),
    (upc, {
        "status": "MEASURED", "unresolved": 1, "resolved_by_tightening": 1,
        "still_unresolved": 0, "by_extension": {}, "by_reason": {},
        "by_place": {}, "new_repo_population": 0,
        "marginal_contribution": {}, "rows": [],
    }, "разрешимость невычисленных путей"),
    (fmrc, {
        "status": "MEASURED", "order": "G103 п. 2", "population": 1,
        "foreign_population": 0, "judged": 1, "unsupported": 0, "refuted": 0,
        "echoed_by_own_scene": 0, "refuted_rows": [], "parity_outcomes": {},
        "refuted_silently": 0, "refuted_loudness_unmeasured": 0,
        "oracle_markup_files": 0, "oracle_identities": 0,
        "origin_unresolved": 0,
    }, "читатели ЧУЖОЙ разметки по литеральной личности"),
    (vac, {
        "status": "OK", "books_measured": 1, "records_total": 1,
        "vacuous_records": 0, "books": {}, "findings": [],
    }, "пустой совет (ADR-765)"),
)

#: Документ, на котором производитель УХОДИТ В РАННИЙ ВОЗВРАТ. Предмет
#: отдельной пробы: строка звавшего стои́т ДО возврата, и «кто позвал слепой
#: прогон» — тот самый вопрос, на который отчёт обязан ответить.
NOT_MEASURED_SCENES = (
    (csi, {"status": "UNMEASURED", "reason": "стенд не построен"}),
    (upc, {"status": "UNMEASURED", "reason": "стенд не построен"}),
    (fmrc, {"status": "UNMEASURED", "gap": "G103 п. 2",
            "reason": "стенд не построен"}),
    (vac, {"status": "UNMEASURED", "reason": "стенд не построен"}),
)


def _lines(module, doc) -> list:
    """Строки, которые производитель отдаёт шагу 0-офис — его ПРАВИЛОМ.

    Второй копии правила отрисовки здесь нет: `vacuous_advice_census` отдаёт
    ОДНУ строку (его CLI печатает её `print`-ом), и шаг 0-офис разбирает её
    `splitlines()` — ровно это и повторяется.
    """
    out = module.format_report(doc)
    return out.splitlines() if isinstance(out, str) else list(out)


class QuartetNamesTheEntry(unittest.TestCase):
    """Отрисовка каждого из четырёх НАЗЫВАЕТ точку входа прогона.

    Утверждения здесь СНАРУЖИ ``subTest`` намеренно, и это не стиль. Падение
    под ``subTest`` приходит в pytest отдельным исходом ``SUBFAILED`` и
    ИМЕНИ теста в наборе упавших не добавляет — мутационный прибор по дельте
    сравнивает ровно этот набор, поэтому носитель утверждения становится для
    него НЕВИДИМЫМ и мутация «выживает», не будучи дырой (урок ADR-761, цикл
    #876; здесь он воспроизведён замером: пять мутаций раннего возврата
    пережили ПЕРВЫЙ прогон ровно по этой причине). Диагностика по
    производителям не теряется — она уходит в сообщение.
    """

    def _probe(self) -> tuple:
        stamp, why = slo_keepability.stamp_reader_probe(_ROOT)
        self.assertIsNotNone(stamp, f"отметка-проба не собрана: {why}")
        return stamp, stamp[slo_keepability.ATTRIBUTION_ENTRY_FIELD]

    def test_each_producer_prints_the_entry_point_it_was_called_from(self):
        stamp, entry = self._probe()
        bad = []
        for module, scene, own_line in QUARTET:
            lines = _lines(module, dict(scene, invoked_by=stamp))
            if not any(own_line in line for line in lines):
                bad.append(f"{module.PRODUCER}: отрисовывал НЕ этот "
                           f"производитель — контроль мерил бы чужую строку")
                continue
            named = [line for line in lines if entry in line]
            if len(named) != 1:
                bad.append(f"{module.PRODUCER}: точка входа `{entry}` названа "
                           f"{len(named)} раз(а) в {lines}")
            elif "[ЗВАВШИЙ]" not in named[0]:
                bad.append(f"{module.PRODUCER}: вход назван НЕ строкой "
                           f"звавшего: {named[0]!r}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_caller_is_named_before_the_early_return_too(self):
        stamp, entry = self._probe()
        bad = []
        for module, scene in NOT_MEASURED_SCENES:
            lines = _lines(module, dict(scene, invoked_by=stamp))
            if not any("НЕ ИЗМЕРЕНО" in line for line in lines):
                bad.append(f"{module.PRODUCER}: сцена обязана быть РАННИМ "
                           f"ВОЗВРАТОМ, иначе проба спрашивает не ту ветку: "
                           f"{lines}")
            elif not any(entry in line for line in lines):
                bad.append(f"{module.PRODUCER}: ранний возврат звавшего НЕ "
                           f"называет: {lines}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_absence_of_the_stamp_is_not_passed_off_as_a_record(self):
        """Нет отметки ⇒ третий исход НАЗВАН, а не подставлен (инв. #17)."""
        bad = []
        for module, scene, _own in QUARTET:
            lines = _lines(module, dict(scene))
            said = [line for line in lines if "[ЗВАВШИЙ]" in line]
            if len(said) != 1:
                bad.append(f"{module.PRODUCER}: строк звавшего {len(said)} в "
                           f"{lines}")
            elif "НЕ ЗАПИСАНО" not in said[0] or "None" in said[0]:
                bad.append(f"{module.PRODUCER}: отсутствие записи выдано за "
                           f"запись: {said[0]!r}")
        self.assertEqual(bad, [], "\n".join(bad))


class SeventhSectionVerdict(unittest.TestCase):
    """НАСТОЯЩИЙ прибор седьмой секции на сцене из четырёх носителей."""

    def _scene(self, folder: Path, scenes) -> tuple:
        """Сцена: четыре носителя в каталоге + конституция, их объявляющая."""
        artifacts = []
        for module, doc in scenes:
            (folder / module.ARTIFACT).write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            artifacts.append(f"data/{module.ARTIFACT}")
        door, why = slo_keepability.stamp_reader_door(_ROOT)
        self.assertIsNotNone(door, f"дверь чтения не опрошена: {why}")
        manifest = {"artifacts": [
            {"path": path, "status": "active", "consumers": [door.CONSUMER]}
            for path in artifacts]}
        agents = [{"label": "com.spa.scene",
                   "produces": [{"artifact": path} for path in artifacts]}]
        return manifest, agents

    def _measure(self, scenes) -> dict:
        with tempfile.TemporaryDirectory(prefix="spa_c950_scene_") as tmp:
            folder = Path(tmp) / "data"
            folder.mkdir()
            manifest, agents = self._scene(folder, scenes)
            return slo_keepability.stamp_reader_census(
                {}, agents, _ROOT, folder, manifest=manifest)

    def test_the_section_reports_the_entry_named_for_all_four(self):
        measured = [(module, dict(doc)) for module, doc, _own in QUARTET]
        section = self._measure(measured)
        self.assertEqual(section["status"], "OK", section.get("cause"))
        self.assertEqual(
            section["inventory"], {slo_proposal.READER_ENTRY_NAMED: 4},
            f"седьмая секция судит четвёрку иначе: {section['rows']}")
        self.assertEqual(section["findings"], [])
        for row in section["rows"]:
            self.assertTrue(row["differs"], row)
            self.assertTrue(row["entry_printed"], row)

    def test_rolling_back_the_wiring_brings_the_finding_back(self):
        """ОТКАТ ровно той строки ⇒ ПРОТИВОПОЛОЖНЫЙ вердикт у всех четырёх.

        Откатывается не вывод, а ПРОВОДКА: производителю подменяется
        `provenance_line`, то есть читатель отметки, которого у него до
        ADR-825 не было. Вывод при этом остаётся его собственным, и находка
        обязана вернуться ровно в том виде, в каком её назвал ADR-822.
        """
        measured = [(module, dict(doc)) for module, doc, _own in QUARTET]
        originals = {}
        try:
            for module, _doc in measured:
                originals[module] = module.provenance_line
                module.provenance_line = (
                    lambda _stamp: "запись о звавшем ЕСТЬ, а читать её нечем")
            section = self._measure(measured)
        finally:
            for module, original in originals.items():
                module.provenance_line = original
        self.assertEqual(section["status"], "OK", section.get("cause"))
        self.assertEqual(
            section["inventory"], {slo_proposal.READER_ABSENCE_ONLY: 4},
            f"откат проводки вердикт НЕ вернул: {section['rows']}")
        self.assertEqual(len(section["findings"]), 4)
        for row in section["rows"]:
            self.assertTrue(row["differs"], row)
            self.assertFalse(row["entry_printed"], row)

    def test_the_door_is_the_real_office_reader_and_it_delegates(self):
        """Дверь — настоящий шаг 0-офис, и отрисовку он просит У ПРОИЗВОДИТЕЛЯ.

        Без этой пробы контроль выше подтвердил бы звавшего, напечатанного
        кем угодно: «отметка дошла» и «дошла ЧЕРЕЗ отчёт этого прибора» —
        разные утверждения.
        """
        door, why = slo_keepability.stamp_reader_door(_ROOT)
        self.assertIsNotNone(door, f"дверь чтения не опрошена: {why}")
        bad = []
        with tempfile.TemporaryDirectory(prefix="spa_c950_door_") as tmp:
            folder = Path(tmp) / "data"
            folder.mkdir()
            for module, doc, own_line in QUARTET:
                path = folder / module.ARTIFACT
                path.write_text(json.dumps(doc, ensure_ascii=False),
                                encoding="utf-8")
                rendered = door._summarize_json(
                    str(path), dict(doc), root=str(_ROOT),
                    artifact_root=str(folder.parent))
                if not any(own_line in str(line) for line in rendered):
                    bad.append(f"дверь не делегировала отрисовку "
                               f"{module.PRODUCER}: {rendered}")
        self.assertEqual(bad, [], "\n".join(bad))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
