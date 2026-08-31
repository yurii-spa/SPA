"""Сверка двух домов срока годности (ADR-158 / карточка «порог живёт в двух местах»).

Каждый тест — воспроизведение реального свойства, замеренного 28.08, а не выдумка:

  1. Порог хранится в ДВУХ местах — `manifest.produces[].slo_hours` и
     `AGENT_OUTPUT_FILES` в `uptime_monitor.py`. Сверки между ними не было ни одной.
  2. На живом дереве сверка сразу нашла настоящее расхождение: `com.spa.daily_cycle`
     монитор судит по `data/paper_trading_status.json`, которого НЕТ среди объявленных
     продуктов агента в манифесте.
  3. Главное свойство конструкции: при ПУСТОМ пересечении вердикт обязан быть
     «сравнивать нечего», а не «всё сошлось». Зелёный вердикт на пустом множестве —
     сторож, который не может сработать.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from spa_core.monitoring import freshness_threshold_parity as p


class TestFindsRealDivergence(unittest.TestCase):
    def test_same_artifact_different_hours_is_recorded_not_alarmed(self):
        """ИЗМЕНЁН НАМЕРЕННО 29.08 (инв. #16), прежнее имя —
        `test_same_artifact_different_hours_is_a_finding`.

        Тест закреплял правило «разные числа = находка». Правило оказалось неверным:
        окно живости и срок годности продукта отвечают на РАЗНЫЕ вопросы, а свежесть
        продукта против `slo_hours` сторожит проверка B2 напрямую, каждые 6 ч. Посылка
        «продукт протухнет незамеченным» ложна. На исправном флоте правило давало 12
        находок из 12 — то есть краснело на ВЕРНОЕ состояние.

        Проверка не отключена: числа считаются и лежат в отчёте, а предмет сверки сужен
        до тождества файла (`different_artifact`), где разногласие настоящее.
        """
        r = p.compare({"a": {"data/x.json": 3.0}}, {"a": ("data/x.json", 6.0)})
        self.assertEqual(r["verdict"], p.AGREES)
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["threshold_notes"][0]["manifest_hours"], 3.0)
        self.assertEqual(r["threshold_notes"][0]["monitor_hours"], 6.0)

    def test_different_artifact_for_the_same_agent_is_a_finding(self):
        """Авария, найденная на живом дереве: живость `daily_cycle` судят по файлу,
        которого нет в его объявленном контракте."""
        r = p.compare({"a": {"data/declared.json": 3.0}}, {"a": ("data/watched.json", 3.0)})
        self.assertEqual(r["verdict"], p.DIFFERENT_ARTIFACT)

    def test_agreement_is_silent(self):
        """Обратный контроль: сошлись — молчим."""
        r = p.compare({"a": {"data/x.json": 3.0}}, {"a": ("data/x.json", 3.0)})
        self.assertEqual(r["verdict"], p.AGREES)
        self.assertEqual(r["findings"], [])


class TestEmptyIntersectionIsItsOwnAnswer(unittest.TestCase):
    """Главный тест конструкции."""

    def test_no_overlap_is_not_compared_not_agreement(self):
        r = p.compare({"a": {"data/x.json": 3.0}}, {"b": ("data/y.json", 3.0)})
        self.assertEqual(r["compared"], 0)
        self.assertEqual(r["verdict"], p.NOT_COMPARED)
        self.assertNotEqual(r["verdict"], p.AGREES,
                            "пустое пересечение, объявленное согласием, — сторож, "
                            "который не может сработать")

    def test_both_sources_empty_is_also_not_compared(self):
        self.assertEqual(p.compare({}, {})["verdict"], p.NOT_COMPARED)


class TestToleranceIsForArithmeticNotForSlack(unittest.TestCase):
    def test_rounding_noise_does_not_fire(self):
        """1800 секунд → 0.5 ч: перевод не обязан давать находку."""
        r = p.compare({"a": {"data/x.json": 0.5}}, p.monitor_thresholds({"a": ("data/x.json", 1800)}))
        self.assertEqual(r["verdict"], p.AGREES)

    def test_a_real_difference_is_not_swallowed(self):
        """ИЗМЕНЁН НАМЕРЕННО 29.08 (инв. #16) вместе с тестом выше — та же причина.

        Смысл контроля сохранён и даже усилен: настоящая разница чисел не должна
        ПРОПАДАТЬ. Она и не пропадает — она записана. Изменилось только то, кем
        она считается: наблюдением, а не аварией. Допуск по-прежнему защищает лишь
        от арифметики с плавающей точкой, а не даёт люфт.
        """
        r = p.compare({"a": {"data/x.json": 0.5}}, {"a": ("data/x.json", 0.6)})
        self.assertEqual(r["findings"], [])
        self.assertEqual(len(r["threshold_notes"]), 1)


class TestMonitorParsing(unittest.TestCase):
    def test_entries_without_a_file_are_skipped(self):
        """`(None, 0)` — демон, судимый по PID/порту, а не по файлу."""
        self.assertEqual(p.monitor_thresholds({"d": (None, 0)}), {})

    def test_seconds_become_hours(self):
        self.assertEqual(p.monitor_thresholds({"a": ("data/x.json", 3600)}), {"a": ("data/x.json", 1.0)})


class TestLiveTreeStillHasTheKnownFinding(unittest.TestCase):
    """Положительный контроль на ЖИВОМ дереве — иначе тест проверял бы фикстуру."""

    def test_live_audit_runs_and_reports_a_verdict(self):
        r = p.audit()
        self.assertIn(r["verdict"], (p.AGREES, p.NOT_COMPARED,
                                     p.THRESHOLD_MISMATCH, p.DIFFERENT_ARTIFACT))
        self.assertGreater(r["manifest_agents"], 0, "манифест обязан давать сроки")
        self.assertGreater(r["monitor_agents"], 0, "карта монитора обязана давать сроки")


if __name__ == "__main__":
    unittest.main()


class TwoNumbersAnswerTwoDifferentQuestions(unittest.TestCase):
    """Сверка выдала 12 «расхождений» на ИСПРАВНОМ флоте — дефект был в ней самой.

    Порог `uptime_monitor` отвечает «ЖИВ ЛИ АГЕНТ» и выводится из расписания с запасом
    1.25–1.5 такта, чтобы один пропуск не мигал. `slo_hours` манифеста отвечает «СВЕЖ ЛИ
    ПРОДУКТ ДЛЯ ПОТРЕБИТЕЛЯ» и назначается двумя ролями по цене опоздания (ADR-158).

    Я сузил проверку дважды за день. Сначала счёл дефектом случай «монитор лояльнее»:
    продукт протухает через 26 ч, а тревога о молчании — через 36 ч. Посылка «десять
    часов никто не знает» оказалась ЛОЖНОЙ: свежесть продукта против `slo_hours`
    сторожит проверка B2 каждые 6 ч и напрямую. Соотношения между окнами не требуется
    ни в какую сторону — это ровно ошибка «три вопроса — три сторожа» из
    .claude/rules/deployment.md, допущенная в собственной проверке.
    """

    def test_looser_monitor_is_not_a_finding_because_B2_watches_the_product(self):
        r = p.compare({"a": {"data/x.json": 26.0}}, {"a": ("data/x.json", 36.0)})
        self.assertEqual(r["findings"], [])
        self.assertEqual(len(r["threshold_notes"]), 1)

    def test_stricter_monitor_is_not_a_finding_either(self):
        r = p.compare({"a": {"data/x.json": 168.0}}, {"a": ("data/x.json", 1.0)})
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["verdict"], p.AGREES)

    def test_the_difference_is_recorded_so_checked_is_not_unchecked(self):
        """«Сверено, соотношение такое-то» не должно быть неотличимо от «не сверяли»."""
        r = p.compare({"a": {"data/x.json": 26.0}}, {"a": ("data/x.json", 36.0)})
        self.assertEqual(r["compared"], 1)
        self.assertIn("НОРМА", r["threshold_notes"][0]["note"])

    def test_equal_numbers_produce_no_note_at_all(self):
        r = p.compare({"a": {"data/x.json": 26.0}}, {"a": ("data/x.json", 26.0)})
        self.assertEqual(r["threshold_notes"], [])
        self.assertEqual(r["findings"], [])

    def test_different_file_is_the_one_real_subject_left(self):
        """Сужение не тронуло предмет, где разногласие настоящее — тождество файла."""
        r = p.compare({"a": {"data/x.json": 26.0}}, {"a": ("data/y.json", 26.0)})
        self.assertEqual([f["verdict"] for f in r["findings"]], [p.DIFFERENT_ARTIFACT])


class LiveTreeDailyCycleHousesAgree(unittest.TestCase):
    """Последняя находка B7 первого прогона, закрытая по существу (29.08).

    `uptime_monitor` судил живость `com.spa.daily_cycle` по `paper_trading_status.json`,
    а контракт агента о нём молчал: два дома называли продуктом дневного цикла РАЗНЫЕ
    файлы. Что файл принадлежит циклу, доказывает он сам — внутри `"source":
    "cycle_runner"`; статическим разбором запись не видна, имя собирается на лету.

    Тест связывает дома НАПРЯМУЮ, а не через вердикт сверки: так он краснеет и в том
    случае, если сверку однажды снова сузят.
    """

    def test_the_file_uptime_watches_is_in_the_agents_contract(self):
        from spa_core.monitoring.artifact_contract import declared_produces
        from spa_core.monitoring.uptime_monitor import AGENT_OUTPUT_FILES
        watched = (AGENT_OUTPUT_FILES.get("com.spa.daily_cycle") or (None, 0))[0]
        self.assertIsNotNone(watched, "монитор перестал следить за дневным циклом")
        decl = declared_produces(
            Path(__file__).resolve().parents[2] / "spa_core/paper_trading/cycle_runner.py")
        self.assertIn(watched, decl or (),
                      "монитор судит живость по файлу, которого нет в контракте агента")

    def test_the_manifest_knows_it_too(self):
        """Третий дом: без записи в конституции у файла нет ни срока, ни потребителя."""
        import json
        root = Path(__file__).resolve().parents[2]
        man = json.loads((root / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        entry = next(a for a in man["agents"] if a["label"] == "com.spa.daily_cycle")
        arts = {p["artifact"] for p in (entry.get("produces") or [])}
        self.assertIn("data/paper_trading_status.json", arts)


class SilentlyDroppedAgentsAreTheSameDiseaseOneLevelDown(unittest.TestCase):
    """Замер цикла #444 (2026-08-31) — положительные контроли на НАСТОЯЩИЙ пропуск.

    Модуль написан ради правила «„сравнивать нечего“ не имеет права выглядеть зелёным»,
    и исполнял его ровно для одного случая: когда пересечение пусто ЦЕЛИКОМ. По каждому
    агенту стояло безмолвное `continue` — у монитора срок есть, манифест не дал ни одного,
    и агент не попадал НИ В ОДИН исход отчёта. Печаталось «сошлись все сопоставимые
    пороги», и это была правда о МЕНЬШЕМ множестве, чем звучало: 14 из 16.

    На живом дереве так пропадали `com.spa.autopush` (intent=active, curation=partial,
    produces: []) и `com.spa.checkpoint-7day` (intent=retired). Первый — острый край:
    монитор судит его живость по `logs/auto_push.log`, а манифест не объявляет за ним
    ни одного продукта; это ровно разногласие о тождестве, ради которого модуль написан,
    отброшенное до того, как его можно было увидеть.

    Каждый тест ниже КРАСНЕЕТ на коде до правки.
    """

    def test_monitor_label_without_a_manifest_threshold_is_named(self):
        """Прежде — молчание. Теперь — исход с именем агента и причиной."""
        r = p.compare({}, {"com.spa.x": ("logs/x.log", 4.5)},
                      meta={"com.spa.x": {"intent": "active", "curation": "partial",
                                          "declares_produces": False}})
        self.assertEqual(len(r["uncompared"]), 1)
        row = r["uncompared"][0]
        self.assertEqual(row["label"], "com.spa.x")
        self.assertEqual(row["reason"], p.UNCOMPARED_NO_THRESHOLD)
        self.assertEqual(row["monitor_artifact"], "logs/x.log")
        self.assertEqual(row["monitor_hours"], 4.5)

    def test_every_monitor_label_lands_in_exactly_one_outcome(self):
        """Тождество учёта — то, что делает немой пропуск невозможным ПО ПОСТРОЕНИЮ.

        Пока `compared + не сверено == меток монитора со сроком`, отбросить агента
        молча нельзя: он обязан где-то лежать.
        """
        mon = {"a": ("data/x.json", 1.0), "b": ("data/y.json", 2.0), "c": ("logs/z.log", 3.0)}
        r = p.compare({"a": {"data/x.json": 1.0}, "b": {"data/other.json": 2.0}}, mon, meta={})
        self.assertEqual(r["compared"] + len(r["uncompared"]), len(mon))

    def test_absent_label_and_unthresholded_label_do_not_sound_alike(self):
        """Разные адресаты починки: курация флота против назначения срока (ADR-158)."""
        meta = {"known": {"intent": "active", "curation": "partial", "declares_produces": False}}
        absent = p.compare({}, {"unknown": ("logs/a.log", 1.0)}, meta=meta)["uncompared"][0]
        present = p.compare({}, {"known": ("logs/b.log", 1.0)}, meta=meta)["uncompared"][0]
        self.assertEqual(absent["reason"], p.UNCOMPARED_ABSENT)
        self.assertEqual(present["reason"], p.UNCOMPARED_NO_THRESHOLD)
        self.assertNotEqual(absent["note"], present["note"])

    def test_without_meta_the_reason_is_not_guessed(self):
        """Fail-CLOSED: не измерили причину — так и сказать, а не выбрать правдоподобную."""
        row = p.compare({}, {"a": ("logs/a.log", 1.0)})["uncompared"][0]
        self.assertEqual(row["reason"], p.UNCOMPARED_UNKNOWN)
        self.assertIn("не измерено", row["note"])

    def test_retired_agent_carries_its_intent_so_it_reads_differently(self):
        """Пустой контракт у отставного агента законен; у активного — пробел курации.
        Сверка не выбирает виноватого, но обязана дать читателю различить эти два."""
        meta = {"r": {"intent": "retired", "curation": "complete", "declares_produces": False},
                "a": {"intent": "active", "curation": "partial", "declares_produces": False}}
        rows = p.compare({}, {"r": ("logs/r.log", 1.0), "a": ("logs/a.log", 1.0)},
                         meta=meta)["uncompared"]
        by = {x["label"]: x for x in rows}
        self.assertEqual(by["r"]["manifest_intent"], "retired")
        self.assertEqual(by["a"]["manifest_intent"], "active")

    def test_full_overlap_leaves_the_block_empty(self):
        """Обратный контроль: сверили всех — блок пуст, и он не выдумывает пробел."""
        r = p.compare({"a": {"data/x.json": 1.0}}, {"a": ("data/x.json", 1.0)}, meta={})
        self.assertEqual(r["uncompared"], [])
        self.assertEqual(r["verdict"], p.AGREES)


class LiveTreeReplaysTheDroppedAgents(unittest.TestCase):
    """Тот же замер на ЖИВОМ дереве — иначе тест проверял бы фикстуру.

    Множество не приколочено именами: агенту могут назначить срок завтра, и тест обязан
    пережить это, не покраснев по календарю. Приколочено СВОЙСТВО: кого сверка не смогла
    сопоставить, того она обязана НАЗВАТЬ — всех до одного.
    """

    def test_audit_names_every_label_it_could_not_compare(self):
        from spa_core.monitoring.uptime_monitor import AGENT_OUTPUT_FILES
        import json
        root = Path(__file__).resolve().parents[2]
        man = json.loads((root / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        expected = {lbl for lbl in p.monitor_thresholds(AGENT_OUTPUT_FILES)
                    if lbl not in p.manifest_thresholds(man)}
        r = p.audit()
        self.assertEqual({u["label"] for u in r["uncompared"]}, expected)
        self.assertEqual(r["compared"] + len(r["uncompared"]), r["monitor_agents"],
                         "метка монитора со сроком обязана лежать РОВНО в одном исходе")

    def test_the_gap_is_spoken_not_only_stored(self):
        """Блок в JSON, который не звучит в выводе, — тот же немой исход (урок #426).

        Ожидание считается из ДВУХ ДОМОВ напрямую, а не из отчёта сверки: иначе тест
        краснел бы на отсутствие ключа (подготовка), а не на то, что читатель пробела
        не увидел (поведение). На коде до правки этот тест краснеет ровно потому, что
        `com.spa.autopush` не звучит в выводе ни разу.
        """
        import contextlib, io, json
        from spa_core.monitoring.uptime_monitor import AGENT_OUTPUT_FILES
        root = Path(__file__).resolve().parents[2]
        man = json.loads((root / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        expected = {lbl for lbl in p.monitor_thresholds(AGENT_OUTPUT_FILES)
                    if lbl not in p.manifest_thresholds(man)}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            p.main()
        out = buf.getvalue()
        for label in expected:
            self.assertIn(label, out, "не сверённый агент обязан ЗВУЧАТЬ в выводе")
        if expected:
            self.assertIn("не сверено", out,
                          "итоговая строка обязана называть размер несверённого множества")


class TheArchitectureGuardCarriesTheGapUp(unittest.TestCase):
    """Пробел, доехавший до отчёта сверки и умерший там, читателя не достигает.
    Единственный обязательный читатель B7 — шаг 0-офис через `architecture_conformance`."""

    def test_report_carries_uncompared_into_the_office_step(self):
        import datetime as dt
        from spa_core.monitoring import architecture_conformance as ac
        parity = p.compare({}, {"com.spa.x": ("logs/x.log", 4.5)},
                           meta={"com.spa.x": {"intent": "active", "curation": "partial",
                                               "declares_produces": False}})
        report = ac.run_checks(
            manifest={"agents": []}, fleet=set(), ts_of=lambda _p: None, receipts={},
            now=dt.datetime(2026, 8, 31, tzinfo=dt.timezone.utc), freshness_parity=parity)
        block = (report.get("contracts") or {}).get("freshness_parity") or {}
        self.assertEqual([u["label"] for u in block.get("uncompared") or []], ["com.spa.x"],
                         "пробел, умерший в отчёте сверки, читателя не достигает")
        self.assertEqual(block.get("monitor_agents"), 1)

    def test_the_gap_is_not_promoted_to_a_finding(self):
        """Сознательно НЕ тревога (инструкция карточки): ни одна из двух сторон отсюда
        не признаётся виноватой, а сторож, кричащий на пробел курации, учит себя
        игнорировать. Предмет — видимость, а не эскалация."""
        import datetime as dt
        from spa_core.monitoring import architecture_conformance as ac
        parity = p.compare({}, {"com.spa.x": ("logs/x.log", 4.5)}, meta={})
        report = ac.run_checks(
            manifest={"agents": []}, fleet=set(), ts_of=lambda _p: None, receipts={},
            now=dt.datetime(2026, 8, 31, tzinfo=dt.timezone.utc), freshness_parity=parity)
        self.assertEqual([f for f in report["findings"] if "freshness_parity" in f["key"]], [])
