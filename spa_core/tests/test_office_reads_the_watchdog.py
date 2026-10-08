"""Заказ владельца G143 п. 1 (хвост ADR-642/ADR-526), решение ADR-643.

ВТОРОЙ из перечня непрочитанных производителей находок, названных ADR-526
поимённо: `data/watchdog_status.json`.

Предмет здесь особый, и это не риторика. `com.spa.watchdog` — ПОСЛЕДНЕЕ звено
плана самолечения: единственный, кто спрашивает, живы ли сами `self_heal` и
`threat_reactor`. Его собственная находка доезжала только тревогой в Телеграм, и
притом ПОД ПОТОЛКОМ ЗАЩИТЫ ОТ ФЛУДА (`FLOOD_WINDOW` = 1 ч на стража): устойчиво
мёртвый страж даёт одну тревогу в час и больше ничего, а внутри цикла не звучал
ВОВСЕ. План самолечения мог лежать, и ни один цикл не обязан был узнать.

Каждый тест — либо положительный контроль формы, ИЗМЕРЕННОЙ у производителя
(`run_watchdog()` в `spa_core/monitoring/watchdog.py`), либо контроль в обратную
сторону с поимённо порванным звеном. Проверки идут по ИСХОДУ, а не подстрокой
(ADR-333): где сравнивается текст, там рядом сверяется и ЧИСЛО, различающее
сцены, — иначе подмена имени ключа осталась бы невидимой (урок #786).

Литеральных дат нет: часы приходят входом `now=`, отметки сцены вычислены от
якоря.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ARTIFACT = "data/watchdog_status.json"
PRODUCER_AGENT = "com.spa.watchdog"
PRODUCER_SRC = "spa_core/monitoring/watchdog.py"
CYCLE_CONSUMER = "orchestrator_protocol"

# Якорь сцены.
# FROZEN-DATE-OK: injected-clock — ветка выжимки принимает часы
# входом `_summarize_json(..., now=NOW)`, все отметки документов сцены вычислены
# от этого якоря, стенных часов в батарее нет ни одних. Якорь намеренно уведён от
# стенных часов на месяцы: совпадение с сегодняшним днём делало бы батарею
# зелёной и тогда, когда ветка часы НЕ принимает.
NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location(
        "_office_probe_wd", REPO / "scripts" / "consume_office_reports.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _calm(**over):
    """Документ в форме, ИЗМЕРЕННОЙ у производителя, и в состоянии «план цел».

    Это ЖИВОЙ замер 07.10 с прод-дерева, а не выдуманная форма: оба стража
    загружены, пульс минуты, находка пуста ЧЕСТНЫМ НУЛЁМ.
    """
    doc = {
        "ts": (NOW - dt.timedelta(hours=0.05)).isoformat(),
        "guardians": {
            "com.spa.self_heal": {"loaded": True, "status_age_min": 3.39,
                                  "stale": False, "action": None, "alert": None},
            "com.spa.threat_reactor": {"loaded": True, "status_age_min": 2.74,
                                       "stale": False, "action": None, "alert": None},
        },
        "actions": [],
        "failures": [],
        "unchecked": [],
        "healthy": True,
        "alerts_attempted": [],
        "alerts_delivered": [],
        "alerts_undelivered": [],
        "alerts_delivery_unmeasured": [],
        "stale_minutes_threshold": 20.0,
        "LLM_FORBIDDEN": True,
    }
    doc.update(over)
    return doc


def _dead_guardian(**over):
    """Страж НЕ ЗАГРУЖЕН, починка отказала, тревогу отказала политика."""
    doc = _calm()
    doc["guardians"]["com.spa.threat_reactor"] = {
        "loaded": False, "status_age_min": 412.5, "stale": True,
        "action": "bootstrap_failed", "alert": "refused"}
    doc.update({
        "failures": ["bootstrap failed com.spa.threat_reactor (not loaded)"],
        "healthy": False,
        "alerts_attempted": ["com.spa.threat_reactor"],
        "alerts_undelivered": ["com.spa.threat_reactor"],
    })
    doc.update(over)
    return doc


def _launchd_unmeasured(**over):
    """ТРЕТИЙ ИСХОД производителя: `launchctl list` не измерен.

    Форма взята из самого производителя — он кладёт в состояние стража ключ
    `unchecked` и `loaded: None`, и его docstring ПРЯМО запрещает читать
    неизмеренный launchd как «страж не загружен».
    """
    doc = _calm()
    doc["guardians"]["com.spa.self_heal"] = {
        "loaded": None, "status_age_min": None, "stale": True,
        "action": None, "alert": None,
        "unchecked": "launchctl list не измерен — загруженность стража неизвестна"}
    doc.update({"unchecked": ["com.spa.self_heal"], "healthy": False})
    doc.update(over)
    return doc


def _lines(doc):
    return _office()._summarize_json(ARTIFACT, doc, now=NOW, root=str(REPO))


def _manifest():
    return json.loads((REPO / "architecture" / "manifest.json").read_text())


def _row(manifest=None):
    man = manifest or _manifest()
    return next((a for a in man.get("artifacts") or []
                 if a.get("path") == ARTIFACT), None)


class TheOfficeActuallyReadsTheWatchdog(unittest.TestCase):
    """Объявить артефакт и не уметь его разобрать = `ПРОЧИТАН ВХОЛОСТУЮ`."""

    def test_the_branch_exists_so_the_read_is_not_hollow(self):
        o = _office()
        self.assertIn(ARTIFACT.rsplit("/", 1)[-1], o._READ_SCHEMA,
                      "без объявления схемы расхождение с производителем "
                      "не измеряется вовсе")
        lines = _lines(_calm())
        # ОБРАТНАЯ СТОРОНА, порванное звено названо: артефакт без ветки даёт
        # только служебную голову — ровно тот `ВХОЛОСТУЮ`, который #797 нашёл
        # на соседнем `artifact_stamp_clock_doors.json`.
        hollow = _office()._summarize_json(
            "data/__no_such_branch_exists__.json", _calm(), now=NOW, root=str(REPO))
        self.assertGreater(len(lines), len(hollow),
                           "ветка не добавила ни одной строки — чтение вхолостую")
        self.assertTrue(any("стражей" in ln for ln in lines))

    def test_the_verdict_line_carries_all_four_counters_and_the_denominator(self):
        """`отказов 0` без знаменателя не имеет масштаба: стражей ровно два."""
        head = next(ln for ln in _lines(_calm()) if "вердикт:" in ln)
        for token in ("стражей 2", "отказов 0", "вмешательств 0", "не измерено 0"):
            self.assertIn(token, head, f"в вердикте нет {token!r}")

    def test_an_empty_guardian_set_is_not_a_denominator_of_zero(self):
        """Знаменателя нет ⇒ третий исход, а не ноль (инв. #17)."""
        head = next(ln for ln in _lines(_calm(guardians={})) if "вердикт:" in ln)
        self.assertIn(f"стражей {_office()._UNMEASURED}", head)
        self.assertNotIn("стражей 0", head)


class TheThreeOutcomesStayDistinguishable(unittest.TestCase):
    """Инв. #17: измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО."""

    def test_unmeasured_launchd_is_not_reported_as_a_live_guardian(self):
        lines = _lines(_launchd_unmeasured())
        unm = _office()._UNMEASURED
        self.assertTrue(any(unm in ln and "com.spa.self_heal" in ln for ln in lines),
                        "неизмеренный launchd не назван третьим исходом")
        self.assertFalse(any("com.spa.self_heal" in ln and "жив" in ln for ln in lines),
                         "страж с неизмеренным launchd объявлен живым")
        # СЦЕНА РАЗЛИЧАЕТ, а не только даёт исход: счётчик `не измерено`
        # обязан отличаться от спокойной сцены, иначе подмена ИМЕНИ ключа
        # осталась бы невидимой (урок #786).
        calm_head = next(ln for ln in _lines(_calm()) if "вердикт:" in ln)
        head = next(ln for ln in lines if "вердикт:" in ln)
        self.assertIn("не измерено 1", head)
        self.assertIn("не измерено 0", calm_head)
        self.assertNotEqual(head, calm_head)

    def test_a_guardian_without_a_heartbeat_gets_no_substituted_number(self):
        """`status_age_min: None` — «пульса не добыть», а не «0 минут»."""
        lines = _lines(_launchd_unmeasured())
        line = next(ln for ln in lines if "com.spa.self_heal" in ln)
        self.assertIn(f"пульс {_office()._UNMEASURED}", line)
        self.assertNotIn("пульс 0.0мин", line)

    def test_a_measured_zero_still_reads_as_the_plane_being_whole(self):
        head = next(ln for ln in _lines(_calm()) if "вердикт:" in ln)
        self.assertIn("ПЛАН САМОЛЕЧЕНИЯ ЦЕЛ", head)


class TheFindingItselfReachesTheCycle(unittest.TestCase):
    def test_a_dead_guardian_and_its_failed_repair_are_both_named(self):
        lines = _lines(_dead_guardian())
        self.assertTrue(any("НЕ ЗАГРУЖЕН ВО ФЛОТЕ" in ln and
                            "com.spa.threat_reactor" in ln for ln in lines))
        self.assertTrue(any("ОТКАЗ ПОЧИНКИ" in ln for ln in lines))
        head = next(ln for ln in lines if "вердикт:" in ln)
        self.assertIn("отказов 1", head)
        self.assertIn("ЕСТЬ НАХОДКА", head)

    def test_the_heaviest_outcome_is_printed_before_the_calm_guardians(self):
        """Порядок — порядок тяжести: НЕ ИЗМЕРЕНО не задвигается в хвост.

        СЦЕНА ОБЯЗАНА РАЗЛИЧАТЬ, и первая её редакция НЕ различала: тяжёлый
        страж стоял в словаре ПЕРВЫМ, поэтому печать без сортировки давала тот
        же порядок, и снятие `_rank` не краснило ничего (замер этого цикла:
        «порядок тяжести снят → красных 0»). Здесь тяжёлый страж положен
        ПОСЛЕДНИМ намеренно — поднять его на первую строку может только
        сортировка.
        """
        doc = _calm(guardians={
            "com.spa.self_heal": {"loaded": True, "status_age_min": 3.39,
                                  "stale": False, "action": None, "alert": None},
            "com.spa.threat_reactor": {
                "loaded": None, "status_age_min": None, "stale": True,
                "action": None, "alert": None,
                "unchecked": "launchctl list не измерен"},
        }, unchecked=["com.spa.threat_reactor"], healthy=False)
        lines = [ln for ln in _lines(doc)
                 if "com.spa." in ln and "вердикт" not in ln]
        self.assertIn("com.spa.threat_reactor", lines[0],
                      "тяжёлый исход задвинут в хвост — порядок не по тяжести")
        self.assertIn(_office()._UNMEASURED, lines[0])
        # Контроль самой сцены: без сортировки порядок БЫЛ БЫ другим, иначе
        # тест зелен независимо от `_rank`.
        self.assertEqual(list(doc["guardians"])[0], "com.spa.self_heal")

    def test_a_revived_plane_is_not_reported_as_calm(self):
        """`actions` — тоже находка: план лежал и его поднимали.

        Производитель определяет `healthy` как
        `not actions and not failures and not unchecked`. Ветка, печатающая
        одни `failures`, назвала бы спокойным цикл, в котором оба стража
        поднимались из мёртвых, — и это не гипотеза, а прямое следствие его
        собственного определения.
        """
        doc = _calm(actions=["revived (bootstrap) com.spa.self_heal (was not loaded)",
                             "kickstarted com.spa.threat_reactor (stale: 48.0min old)"],
                    healthy=False)
        head = next(ln for ln in _lines(doc) if "вердикт:" in ln)
        self.assertIn("вмешательств 2", head)
        self.assertNotIn("ПЛАН САМОЛЕЧЕНИЯ ЦЕЛ", head)

    def test_a_long_failure_list_says_that_it_was_truncated(self):
        """Умолчание об усечении превратило бы перечень в «вот и всё»."""
        doc = _dead_guardian(failures=[f"bootstrap failed guardian-{i}" for i in range(9)])
        lines = _lines(doc)
        self.assertTrue(any("ещё 5 отказов не напечатано" in ln for ln in lines))


class TheOwnerMayNotHaveBeenWarned(unittest.TestCase):
    """Отказанный политикой push — НЕ «владельца предупредили»."""

    def test_a_refused_alert_is_not_booked_as_delivered(self):
        lines = _lines(_dead_guardian())
        line = next(ln for ln in lines if "тревога владельцу" in ln)
        self.assertIn("доставлено 0", line)
        self.assertIn("отказано политикой 1", line)
        self.assertTrue(any("владелец НЕ узнал" in ln for ln in lines))

    def test_an_unmeasured_delivery_is_its_own_outcome(self):
        doc = _dead_guardian(alerts_undelivered=[],
                             alerts_delivery_unmeasured=["com.spa.threat_reactor"])
        lines = _lines(doc)
        line = next(ln for ln in lines if "тревога владельцу" in ln)
        self.assertIn(f"{_office()._UNMEASURED} 1", line)
        self.assertTrue(any("владелец НЕ узнал" in ln for ln in lines))

    def test_a_whole_plane_prints_no_delivery_line_at_all(self):
        """При целом плане слать нечего, и «доставлено 0» читалось бы находкой."""
        self.assertFalse(any("тревога владельцу" in ln for ln in _lines(_calm())))


class TheAgeIsMeasuredNotFalselyUnmeasured(unittest.TestCase):
    def test_the_producers_own_timestamp_field_is_declared(self):
        """Производитель пишет `ts`; без объявления возраст был бы «НЕ ИЗМЕРЕН»
        ПО ПОСТРОЕНИЮ — ложный третий исход о величине, которая есть."""
        o = _office()
        self.assertEqual(o._TS_FIELD.get("watchdog_status.json"), "ts")
        head = _lines(_calm())[0]
        self.assertIn("возраст", head)
        self.assertNotIn(o._UNMEASURED, head)

    def test_tearing_the_timestamp_declaration_loses_the_age(self):
        """ОБРАТНАЯ СТОРОНА, звено названо: `_TS_FIELD` без строки."""
        o = _office()
        o._TS_FIELD.pop("watchdog_status.json")
        head = o._summarize_json(ARTIFACT, _calm(), now=NOW, root=str(REPO))[0]
        self.assertIn("НЕ ИЗМЕРЕН", head)


class TheSchemaWasMeasuredAtTheProducer(unittest.TestCase):
    """Перечень вымерен у производителя, а не списан с живого файла."""

    def test_every_declared_key_is_actually_written_by_the_producer(self):
        o = _office()
        declared = set(o._READ_SCHEMA["watchdog_status.json"])
        src = (REPO / PRODUCER_SRC).read_text()
        tree = ast.parse(src)
        written = {k.value for node in ast.walk(tree)
                   if isinstance(node, ast.Dict)
                   for k in node.keys
                   if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        missing = sorted(declared - written)
        self.assertEqual(missing, [],
                         f"объявлено как читаемое, но производитель не пишет: {missing}")

    def test_the_producer_is_declared_so_divergence_is_measurable(self):
        """Без `_PRODUCER` расхождение схемы стало бы «НЕ ИЗМЕРЕНО»."""
        o = _office()
        self.assertEqual(o._PRODUCER.get("watchdog_status.json"), PRODUCER_SRC)
        # Рвать надо КЛЮЧ, а не значение: `guardians: None` — ключ на месте,
        # и расхождения схемы тут нет по определению (это другой вопрос —
        # вырожденное значение, и его ловит тест про знаменатель).
        torn = _calm()
        torn.pop("guardians")
        gap = o._schema_drift("watchdog_status.json", torn, root=str(REPO))
        self.assertTrue(gap, "порванная схема не дала ни одной строки")
        self.assertFalse(any(o._UNMEASURED in ln for ln in gap),
                         "производитель объявлен, а расхождение всё равно "
                         "объявлено неизмеренным")


class TheConstitutionDeclaresTheCycleAsConsumer(unittest.TestCase):
    def test_the_row_exists_active_and_names_the_cycle(self):
        row = _row()
        self.assertIsNotNone(row, "строки artifacts[] нет — вердикт переписи "
                                  "не станет read_by_the_cycle")
        self.assertEqual(row["status"], "active")
        self.assertIn(CYCLE_CONSUMER, row["consumers"])
        self.assertEqual(row["producer"], PRODUCER_AGENT)

    def test_the_slo_is_taken_from_the_producer_not_chosen(self):
        """Второй дом порога — урок ADR-513: расхождение двух объявлений
        об ОДНОМ файле молчит."""
        man = _manifest()
        agent = next(a for a in man["agents"] if a.get("label") == PRODUCER_AGENT)
        produced = next(p for p in agent["produces"]
                        if p.get("artifact") == ARTIFACT)
        self.assertEqual(_row(man)["slo_hours"], produced["slo_hours"])


class TheCensusVerdictActuallyMoves(unittest.TestCase):
    """Приёмка по ИСХОДУ: перепись обязана перестать звать находку непрочитанной."""

    #: Сцена ОБЕСПЕЧИВАЕТ СВОЮ ПРЕДПОСЫЛКУ, а не берёт её у хоста. Нога
    #: писателя у переписи спрашивается ПЕРВОЙ и спрашивается у НАБЛЮДЕНИЯ:
    #: без свежего артефакта в каталоге данных вердикт будет `writer_silent`,
    #: и о читателе перепись не скажет НИЧЕГО. Живое прод-`data/` для этого
    #: брать нельзя — из worktree его нет по построению, и тест судил бы о
    #: чужой машине (замер: ровно так эти два теста и покраснели сначала).
    def _measure(self, manifest):
        import tempfile
        from spa_core.monitoring import finding_reader_census as frc
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp)
            (data / "watchdog_status.json").write_text(json.dumps(_calm()))
            res = frc.measure(REPO, data_dir=data, manifest=manifest, now=NOW)
        rows = res.get("rows") or []
        row = next((r for r in rows if r.get("artifact") == ARTIFACT), None)
        # Громкий отказ вместо тихого «не тот исход»: предпосылку надо
        # проверять, а не предполагать (урок #752–#754 про негодную сцену).
        if row is not None and str(row.get("verdict")).startswith("writer_"):
            raise AssertionError(
                f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: перепись считает писателя "
                f"молчащим ({row.get('verdict')}) и о читателе не судит вовсе")
        return row

    def test_the_pair_is_now_read_by_the_cycle(self):
        row = self._measure(_manifest())
        self.assertIsNotNone(row, "пары нет в населении — производитель не "
                                  "объявляет артефакт в produces")
        self.assertEqual(row.get("verdict"), "read_by_the_cycle")

    def test_tearing_the_artifacts_row_drops_it_to_the_weaker_outcome(self):
        """ОБРАТНАЯ СТОРОНА, звено названо: строка `artifacts[]` удалена.

        И ЗДЕСЬ ЗАМЕР ПОПРАВИЛ ОЖИДАНИЕ. Эта проверка была написана на
        `no_reader_found` и покраснела: в доставляемом дереве ветка выжимки
        САМА является читателем в коде, поэтому снятие одного объявления
        возвращает пару не в острую форму, а в СОСЕДНЮЮ, слабее —
        `read_in_code_by_another_module`. Разница существенная и
        зафиксирована намеренно: ADR-526 прямо говорит, что объявление не
        есть чтение, но верно и обратное — чтение в коде не есть объявление,
        и выдавать «цикл читает» за это нельзя. Острую форму возвращает
        только ДВОЙНОЙ разрыв (следующий тест).
        """
        man = _manifest()
        man["artifacts"] = [a for a in man["artifacts"] if a.get("path") != ARTIFACT]
        self.assertEqual(self._measure(man).get("verdict"),
                         "read_in_code_by_another_module")

    def test_tearing_both_the_row_and_the_branch_returns_the_acute_form(self):
        """Двойной разрыв: нет ни объявления, ни читателя в коде ⇒ находка
        снова непрочитана. Это и есть то состояние, которое заказ застал."""
        import tempfile
        import shutil
        from spa_core.monitoring import finding_reader_census as frc
        man = _manifest()
        man["artifacts"] = [a for a in man["artifacts"] if a.get("path") != ARTIFACT]
        with tempfile.TemporaryDirectory() as tmp:
            tree = pathlib.Path(tmp) / "tree"
            # Одноразовая копия дерева БЕЗ ветки выжимки: живое дерево не
            # трогается, а предмет замера — именно отсутствие читателя.
            shutil.copytree(REPO / "spa_core", tree / "spa_core",
                            ignore=shutil.ignore_patterns("tests", "__pycache__"))
            (tree / "scripts").mkdir(parents=True)
            (tree / "data").mkdir()
            (tree / "data" / "watchdog_status.json").write_text(json.dumps(_calm()))
            (tree / "scripts" / "consume_office_reports.py").write_text(
                "# ветка выжимки намеренно отсутствует в этой копии\n")
            res = frc.measure(tree, data_dir=tree / "data", manifest=man, now=NOW)
        row = next((r for r in (res.get("rows") or [])
                    if r.get("artifact") == ARTIFACT), None)
        self.assertIsNotNone(row)
        self.assertEqual(row.get("verdict"), "no_reader_found")
        # И форма ОСТРАЯ — ровно та, из-за которой заказ назвал артефакт.
        self.assertEqual(row.get("shape"), "finding_key_present")

    def test_tearing_the_cycle_from_consumers_returns_it_too(self):
        """Строка есть, а цикла в `consumers` нет — объявление не о том
        читателе. Проверка по ИСХОДУ, не по наличию строки."""
        man = _manifest()
        _row(man)["consumers"] = []
        self.assertNotEqual(self._measure(man).get("verdict"), "read_by_the_cycle")

    def test_a_retired_row_does_not_count_as_a_reader(self):
        man = _manifest()
        _row(man)["status"] = "retired"
        self.assertNotEqual(self._measure(man).get("verdict"), "read_by_the_cycle")


if __name__ == "__main__":
    unittest.main()
