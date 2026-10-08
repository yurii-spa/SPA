"""Заказ владельца G145 п. 1 (хвост ADR-644/ADR-526), решение ADR-645.

ПОСЛЕДНИЙ из перечня непрочитанных производителей находок, названных ADR-526
поимённо, — и замер ПОВЕРНУЛ пункт, как сам заказ и предупреждал. Перечень
называл `data/uptime_prev_state.json`; замер показал, что это служебное
состояние ПИСАТЕЛЯ (дедуп-отметки тревог в ключе `alerts`), а непрочитанным
оказался ОТЧЁТ агента — `data/uptime_status.json`, которого не было в
`artifacts[]` конституции ВООБЩЕ: шаг 0-офис не открывал его ни разу.

Предмет. `com.spa.uptime_monitor` — единственный, кто спрашивает, живы ли
службы 24/7 (launchd, порт API, свежесть цикла, доставка). Его находка доезжала
только тревогой в Телеграм и только про ПЕРЕХОД running→down
(`_process_agent_alerts`): устойчиво лежащая служба тревогу уже не производит,
а внутри цикла не звучала вовсе. Замер 08.10: `all_ok=false`, ШЕСТЬ launchd-служб
лежат, и ни одна строка до сегодня в цикл не попадала.

Каждый тест — либо положительный контроль формы, ИЗМЕРЕННОЙ у производителя
(`run_all_checks()` в `spa_core/monitoring/uptime_monitor.py`), либо контроль в
обратную сторону с поимённо порванным звеном. Проверки идут по ИСХОДУ, а не
подстрокой (ADR-333): где сравнивается текст, там рядом сверяется и ЧИСЛО,
различающее сцены, — иначе подмена имени ключа осталась бы невидимой (#786).

Сцены уложены так, чтобы быть НЕГОДНЫМИ без проверяемого звена (заказ G144 п. 3):
неизмеренная проверка лежит в наборе ПОСЛЕДНЕЙ и алфавитно, и по порядку
вставки, поэтому поднять её на первую строку может ТОЛЬКО разведение исходов по
тяжести; а у `launchd_`-проверки и у не-launchd проверки намеренно стоят ОБА
ключа вердикта (`running` и `ok`) с ПРОТИВОПОЛОЖНЫМИ значениями — тест на
«чем судят этот род проверки» без этого был бы зелен при любой подмене.

Литеральных дат нет: часы приходят входом `now=`, все отметки сцены вычислены
от якоря.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
ARTIFACT = "data/uptime_status.json"
BASENAME = ARTIFACT.rsplit("/", 1)[-1]
PRODUCER_AGENT = "com.spa.uptime_monitor"
PRODUCER_SRC = "spa_core/monitoring/uptime_monitor.py"
SERVICE_STATE = "data/uptime_prev_state.json"

# Якорь сцены.
# FROZEN-DATE-OK: injected-clock — ветка выжимки принимает часы входом
# `_summarize_json(..., now=NOW)`, все отметки документов сцены вычислены ОТ
# ЭТОГО ЯКОРЯ (включая эпоху: `NOW.timestamp()`), стенных часов в батарее нет ни
# одних. Якорь уведён от стенных часов на месяцы намеренно: совпадение с
# сегодняшним днём делало бы батарею зелёной и тогда, когда ветка часы НЕ
# принимает.
NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location(
        "_office_probe_uptime", REPO / "scripts" / "consume_office_reports.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


office = _office()


def _ts(hours_ago: float) -> float:
    """Отметка производителя — СЕКУНДЫ ЭПОХИ (так пишет `run_all_checks`)."""
    return (NOW - dt.timedelta(hours=hours_ago)).timestamp()


#: Лежащая launchd-служба в форме производителя (`check_agent`, ветка
#: `output_file_age`). Имя начинается на `launchd_aaa` НАМЕРЕННО: и алфавитно,
#: и по порядку вставки она идёт РАНЬШЕ неизмеренной, поэтому порядок печати
#: «неизмеренное вперёд» может дать ТОЛЬКО разведение исходов, а не сортировка.
_DOWN = {
    "running": False,
    "method": "output_file_age",
    "file": "data/governance_proposals.json",
    "age_seconds": 79904,
    "max_age": 2700,
    "launchctl_pid": None,
    "launchctl_last_exit": None,
}

#: Служба, о которой СУДИТЬ НЕ ПО ЧЕМУ: производитель сам исключает её из
#: `all_ok` (`running is None` ⇒ `continue`). Это третий исход, и он здесь не
#: теоретический — периодический агент между запусками выглядит именно так.
_UNJUDGEABLE = {
    "running": None,
    "method": "no_output_file",
    "pid": None,
    "last_exit": None,
    "error": None,
}


def _status(**over):
    """Отчёт в форме, ИЗМЕРЕННОЙ у производителя: ровно три верхних ключа."""
    doc = {
        "all_ok": False,
        "ts": _ts(0.06),
        "checks": {
            "launchd_aaa_down": dict(_DOWN),
            "launchd_mmm_live": {"running": True, "pid": 21752, "last_exit": 0,
                                 "error": None, "method": "launchctl_pid"},
            "http_server": {"ok": True, "status_code": 200, "latency_ms": 22.71,
                            "error": None},
            "launchd_zzz_unjudgeable": dict(_UNJUDGEABLE),
        },
    }
    doc.update(over)
    return doc


def _calm(**over):
    """Всё судимо и всё прошло — «измерено и равно нулю», а не «не измерено»."""
    doc = {
        "all_ok": True,
        "ts": _ts(0.06),
        "checks": {
            "launchd_mmm_live": {"running": True, "pid": 21752, "last_exit": 0,
                                 "error": None, "method": "launchctl_pid"},
            "http_server": {"ok": True, "status_code": 200, "latency_ms": 22.71,
                            "error": None},
        },
    }
    doc.update(over)
    return doc


def _lines(doc, *, now=NOW):
    return office._summarize_json(BASENAME, doc, now=now, root=str(REPO))


def _body(lines):
    """Строки ВЕТКИ без общей шапки (расхождение схемы + возраст + предмет)."""
    return [ln for ln in lines
            if "вердикт:" in ln or "[CRITICAL]" in ln or "оговорка" in ln
            or f"[{office._UNMEASURED}]" in ln or "не напечатано" in ln
            or ln.strip().startswith(office._UNMEASURED)]


def _manifest_entry(path=ARTIFACT):
    manifest = json.loads((REPO / "architecture" / "manifest.json")
                          .read_text(encoding="utf-8"))
    return manifest, next((a for a in manifest["artifacts"]
                           if a.get("path") == path), None)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Находка ВООБЩЕ звучит в цикле
# ─────────────────────────────────────────────────────────────────────────────

class TheFindingIsAudibleAtAll(unittest.TestCase):
    """Без этой ветки лежащая служба не доезжала до цикла НИКАК."""

    def test_the_down_service_is_named_by_name(self):
        out = "\n".join(_lines(_status()))
        self.assertIn("launchd_aaa_down", out)
        self.assertIn("[CRITICAL]", out)

    def test_the_count_of_down_services_is_printed_not_just_the_names(self):
        """Имена без счётчика не дают масштаба, счётчик без имён — разбора."""
        verdict = next(ln for ln in _lines(_status()) if "вердикт:" in ln)
        self.assertIn("лежит 1", verdict)

    def test_a_calm_report_says_zero_and_not_silence(self):
        verdict = next(ln for ln in _lines(_calm()) if "вердикт:" in ln)
        self.assertIn("лежит 0", verdict)
        self.assertIn("не измерено 0", verdict)
        self.assertNotIn("[CRITICAL]", "\n".join(_lines(_calm())))

    def test_the_producers_own_verdict_is_carried_through(self):
        self.assertIn("ЕСТЬ ЛЕЖАЩИЕ СЛУЖБЫ",
                      next(ln for ln in _lines(_status()) if "вердикт:" in ln))
        self.assertIn("все судимые проверки прошли",
                      next(ln for ln in _lines(_calm()) if "вердикт:" in ln))

    def test_a_missing_all_ok_is_unmeasured_not_false(self):
        """Отсутствующий вердикт — третий исход, а не «есть лежащие» (инв. #17)."""
        doc = _calm()
        del doc["all_ok"]
        verdict = next(ln for ln in _lines(doc) if "вердикт:" in ln)
        self.assertIn(office._UNMEASURED, verdict)
        self.assertNotIn("ЕСТЬ ЛЕЖАЩИЕ", verdict)
        # и при этом сами проверки всё равно посчитаны: вердикт производителя
        # отсутствует, а население — нет.
        self.assertIn("проверок 2", verdict)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Третий исход — отдельным значением и ПЕРВЫМ
# ─────────────────────────────────────────────────────────────────────────────

class TheThirdOutcomeIsItsOwnValue(unittest.TestCase):
    """`running is None` — «судить не по чему», и `all_ok` о такой службе молчит."""

    def test_unjudgeable_is_not_counted_as_down(self):
        verdict = next(ln for ln in _lines(_status()) if "вердикт:" in ln)
        self.assertIn("не измерено 1", verdict)
        self.assertIn("лежит 1", verdict)

    def test_unjudgeable_is_not_counted_as_alive_either(self):
        """ДВА знаменателя: `судимых` меньше `проверок` ровно на неизмеренные."""
        verdict = next(ln for ln in _lines(_status()) if "вердикт:" in ln)
        self.assertIn("проверок 4", verdict)
        self.assertIn("судимых 3", verdict)

    def test_the_two_denominators_coincide_when_nothing_is_unmeasured(self):
        """Обратный контроль: равенство знаменателей — ЗАМЕР, а не совпадение."""
        verdict = next(ln for ln in _lines(_calm()) if "вердикт:" in ln)
        self.assertIn("проверок 2", verdict)
        self.assertIn("судимых 2", verdict)

    def test_unmeasured_is_printed_before_the_critical_findings(self):
        """Сцена негодна без разведения исходов: лежащая идёт в наборе ПЕРВОЙ."""
        body = _body(_lines(_status()))
        first_unmeasured = next(i for i, ln in enumerate(body)
                                if f"[{office._UNMEASURED}]" in ln)
        first_critical = next(i for i, ln in enumerate(body)
                              if "[CRITICAL]" in ln)
        self.assertLess(first_unmeasured, first_critical,
                        "третий исход задвинут в хвост — служба, о которой "
                        "нечем судить, читалась бы как живая")

    def test_the_unmeasured_line_says_all_ok_is_silent_about_it(self):
        line = next(ln for ln in _lines(_status())
                    if f"[{office._UNMEASURED}]" in ln)
        self.assertIn("launchd_zzz_unjudgeable", line)
        self.assertIn("не говорит ничего", line)

    def test_a_missing_verdict_key_is_unmeasured_not_down(self):
        """Ключа вердикта нет вовсе ⇒ третий исход, а не «лежит»."""
        doc = _calm()
        doc["checks"]["launchd_mmm_live"] = {"method": "launchctl_pid"}
        verdict = next(ln for ln in _lines(doc) if "вердикт:" in ln)
        self.assertIn("не измерено 1", verdict)
        self.assertIn("лежит 0", verdict)

    def test_a_non_dict_check_is_unmeasured_not_skipped(self):
        doc = _calm()
        doc["checks"]["launchd_broken"] = "running"
        verdict = next(ln for ln in _lines(doc) if "вердикт:" in ln)
        self.assertIn("не измерено 1", verdict)
        self.assertIn("проверок 3", verdict)


class AnAbsentChecksBlockIsRefusedWholesale(unittest.TestCase):
    """`all_ok` без `checks` — вердикт ни о чём, и печатать его одного нельзя."""

    def test_missing_checks_is_the_third_outcome(self):
        doc = _calm()
        del doc["checks"]
        body = "\n".join(_body(_lines(doc)))
        self.assertIn(office._UNMEASURED, body)
        self.assertNotIn("вердикт:", body)

    def test_empty_checks_is_the_third_outcome_too(self):
        """Пустой словарь — не «ноль лежащих»: осмотрено НОЛЬ проверок."""
        body = "\n".join(_body(_lines(_calm(checks={}))))
        self.assertIn(office._UNMEASURED, body)
        self.assertNotIn("вердикт:", body)

    def test_a_true_all_ok_does_not_rescue_an_absent_checks_block(self):
        doc = {"all_ok": True, "ts": _ts(0.06)}
        body = "\n".join(_body(_lines(doc)))
        self.assertIn(office._UNMEASURED, body)
        self.assertNotIn("все судимые проверки прошли", body)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Чем судят проверку — измерено у производителя, а не угадано
# ─────────────────────────────────────────────────────────────────────────────

class TheRightKeyJudgesTheRightKind(unittest.TestCase):
    """launchd-проверка отвечает `running`, остальные — `ok`. Два разных ключа.

    В обеих сценах стоят ОБА ключа с противоположными значениями: подмена
    одного другим иначе осталась бы невидимой, и тест был бы зелен от того,
    что в живом файле лишнего ключа просто нет.
    """

    def test_a_launchd_check_is_judged_by_running_not_by_ok(self):
        doc = _calm()
        doc["checks"]["launchd_mmm_live"] = {"running": True, "ok": False,
                                             "method": "launchctl_pid"}
        verdict = next(ln for ln in _lines(doc) if "вердикт:" in ln)
        self.assertIn("лежит 0", verdict)
        self.assertIn("не измерено 0", verdict)

    def test_a_plain_check_is_judged_by_ok_not_by_running(self):
        doc = _calm()
        doc["checks"]["http_server"] = {"ok": True, "running": False,
                                        "status_code": 200}
        verdict = next(ln for ln in _lines(doc) if "вердикт:" in ln)
        self.assertIn("лежит 0", verdict)

    def test_a_failing_plain_check_is_still_a_finding(self):
        """Обратная сторона: `ok=false` у не-launchd проверки — тоже находка."""
        doc = _calm()
        doc["checks"]["cycle_freshness"] = {"ok": False, "stale_hours": 22.205,
                                            "last_run_ts": _ts(22.205),
                                            "error": None}
        out = "\n".join(_lines(doc))
        self.assertIn("cycle_freshness", out)
        self.assertIn("отстал на 22.2ч", out)


class TheReasonComesFromTheProducersOwnFields(unittest.TestCase):
    """`_uptime_detail` ничего не подставляет: отсутствующее поле — НЕ ИЗМЕРЕНО."""

    def test_output_file_age_names_file_age_and_ceiling(self):
        detail = office._uptime_detail("launchd_aaa_down", dict(_DOWN))
        self.assertIn("data/governance_proposals.json", detail)
        self.assertIn("1332м", detail)   # 79904 с
        self.assertIn("45м", detail)     # 2700 с

    def test_a_missing_age_is_unmeasured_not_zero_minutes(self):
        """«возрастом 0м» читалось бы как «только что» — худшая из подмен."""
        chk = dict(_DOWN)
        del chk["age_seconds"]
        detail = office._uptime_detail("launchd_aaa_down", chk)
        self.assertIn(office._UNMEASURED, detail)
        self.assertNotIn("0м при потолке", detail)

    def test_a_last_exit_is_printed_when_the_producer_wrote_one(self):
        detail = office._uptime_detail(
            "launchd_weekly_backup",
            {"running": False, "method": "no_output_file", "last_exit": 256})
        self.assertIn("256", detail)

    def test_an_absent_last_exit_is_not_invented_as_zero(self):
        """`last_exit: null` значит «кода нет», а ноль значил бы «вышел чисто»."""
        detail = office._uptime_detail(
            "launchd_fund-api",
            {"running": False, "method": "no_output_file", "last_exit": None})
        self.assertNotIn("код выхода", detail)

    def test_an_unknown_method_is_named_not_silently_dropped(self):
        detail = office._uptime_detail("launchd_x", {"running": False})
        self.assertIn(office._UNMEASURED, detail)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Оговорка об ИЗМЕРИТЕЛЕ — чтобы цикл не гнался за фантомом
# ─────────────────────────────────────────────────────────────────────────────

class TheSensorCaveatIsNamedNotSilenced(unittest.TestCase):
    """Известная причина названа РЯДОМ с находкой, а находка не погашена."""

    def test_the_finding_itself_is_not_suppressed(self):
        doc = _calm()
        doc["checks"]["git_push"] = {"ok": False, "stale_hours": 951.9,
                                     "last_push_ts": _ts(951.9), "error": None}
        out = "\n".join(_lines(doc))
        self.assertIn("[CRITICAL]", out)
        self.assertIn("git_push", out)

    def test_the_caveat_follows_the_finding(self):
        doc = _calm()
        doc["checks"]["git_push"] = {"ok": False, "stale_hours": 951.9,
                                     "last_push_ts": _ts(951.9), "error": None}
        body = _body(_lines(doc))
        i_find = next(i for i, ln in enumerate(body) if "[CRITICAL]" in ln)
        i_cav = next(i for i, ln in enumerate(body) if "оговорка" in ln)
        self.assertLess(i_find, i_cav)
        self.assertIn("минуя индекс", body[i_cav])

    def test_no_caveat_is_printed_when_the_check_is_fine(self):
        """Оговорка без находки — шум, который научил бы её пролистывать."""
        doc = _calm()
        doc["checks"]["git_push"] = {"ok": True, "stale_hours": 0.2}
        self.assertEqual([ln for ln in _lines(doc) if "оговорка" in ln], [])

    def test_the_caveated_names_are_real_checks_of_this_producer(self):
        """Оговорка о несуществующей проверке молча прикрывала бы пустоту."""
        src = (REPO / PRODUCER_SRC).read_text(encoding="utf-8")
        for key in office._UPTIME_SENSOR_CAVEATS:
            self.assertIn(f'checks["{key}"]', src,
                          f"оговорка про {key}, а производитель такой проверки "
                          f"не пишет — объявление прикрывает пустоту")

    def test_the_cycle_freshness_caveat_names_the_measured_threshold(self):
        """Порог назван ЧИСЛОМ из исходника, а не словами «слишком строгий»."""
        import spa_core.monitoring.uptime_monitor as um
        self.assertIn(str(um.STALE_CYCLE_HOURS),
                      office._UPTIME_SENSOR_CAVEATS["cycle_freshness"])


# ─────────────────────────────────────────────────────────────────────────────
# 5. Возраст измерим — иначе `slo_hours` украшение (класс #267)
# ─────────────────────────────────────────────────────────────────────────────

class TheAgeIsMeasurableAtAll(unittest.TestCase):
    """Производитель пишет `ts` в ЭПОХЕ, читатель разбирал только ISO."""

    def test_the_live_shape_age_is_measured_not_refused(self):
        head = _lines(_status())[0]
        self.assertIn("возраст 0.1ч", head)
        self.assertNotIn("НЕ ИЗМЕРЕН", head)

    def test_without_the_declared_unit_the_age_would_be_unmeasured(self):
        """Положительный контроль самого объявления: порвать звено `_TS_UNIT`."""
        line = office._age_line(_ts(0.06), NOW, field="ts", unit="iso8601")
        self.assertIn("НЕ ИЗМЕРЕН", line)

    def test_the_epoch_value_is_also_shown_in_human_form(self):
        """Сырое число оставлено (оно в файле), но рядом стои́т читаемый вид."""
        head = _lines(_status())[0]
        self.assertIn("2026-03-15T11:56", head)
        self.assertIn(str(int(_ts(0.06))), head)

    def test_ts_field_matches_producer(self):
        keys = office._source_keys(str(REPO / office._PRODUCER[BASENAME]))
        self.assertIsNotNone(keys)
        self.assertIn(office._TS_FIELD[BASENAME], keys)

    def test_ts_unit_matches_producer(self):
        """Претензия «в эпохе» ДОКАЗАНА AST-ом: значение ключа — от `time.time()`.

        Записка не есть замер (урок #477 про `injected-clock`): объявленную
        единицу проверяем так же, как инъекцию часов, — прослеживая, откуда
        происходит значение, которое производитель кладёт в ключ.
        """
        tree = ast.parse((REPO / PRODUCER_SRC).read_text(encoding="utf-8"))
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "run_all_checks")
        # 1. какое ИМЯ производитель кладёт в ключ `ts`
        bound = None
        for node in ast.walk(func):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "ts":
                        bound = v
        self.assertIsInstance(bound, ast.Name, "ключ `ts` заполнен не именем")
        # 2. откуда происходит значение этого имени — до вызова `time.time()`
        origin = None
        for node in ast.walk(func):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == bound.id):
                origin = node.value
        self.assertIsInstance(origin, ast.Call)
        self.assertEqual(ast.unparse(origin), "time.time()",
                         "объявленная единица `epoch_seconds` не подтверждена "
                         "исходником производителя")
        self.assertEqual(office._TS_UNIT[BASENAME], "epoch_seconds")


class TheEpochParserRefusesWhatIsNotATime(unittest.TestCase):
    """Разбор эпохи вне окна правдоподобия — третий исход, а не уверенный возраст."""

    def test_a_calendar_number_is_refused_not_read_as_1970(self):
        self.assertIsNone(office._parse_ts(20261008, unit="epoch_seconds"))

    def test_a_small_counter_is_refused(self):
        self.assertIsNone(office._parse_ts(42, unit="epoch_seconds"))

    def test_a_boolean_is_refused_and_it_is_the_window_that_refuses_it(self):
        """`True` в питоне есть 1 — и отвергает его ОКНО, а не проверка типа.

        Замер (порванное звено «запрет bool как времени» не уронил ни одного
        теста): отдельная проверка типа на `bool` вердикт не меняла НИ НА ОДНОМ
        входе. Такой ворот снимается потом молча, потому что его снятие ничем
        не наблюдаемо, — поэтому он снят СЕЙЧАС и названо, чем именно закрыт
        вход: ровно тем же, чем закрыт числовой `1.0`.
        """
        self.assertIsNone(office._parse_ts(True, unit="epoch_seconds"))
        self.assertIsNone(office._parse_ts(1.0, unit="epoch_seconds"))

    def test_a_string_is_never_read_as_epoch(self):
        self.assertIsNone(office._parse_ts("1773575640.0", unit="epoch_seconds"))

    def test_a_live_epoch_value_is_parsed(self):
        parsed = office._parse_ts(_ts(0), unit="epoch_seconds")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed, NOW)

    def test_iso_producers_are_untouched_by_the_new_unit(self):
        """Обратный контроль: умолчание не изменилось ни для кого другого."""
        iso = (NOW - dt.timedelta(hours=3)).isoformat()
        self.assertEqual(office._parse_ts(iso), NOW - dt.timedelta(hours=3))
        self.assertEqual(office._produced_at("loop_health.json",
                                             {"generated_at": iso}), iso)
        self.assertIsNone(office._parse_ts(_ts(0)))

    def test_the_unit_reaches_the_schema_drift_path_too(self):
        """Один `ts` — одно прочтение. Иначе один читатель видит время, другой мусор."""
        self.assertEqual(office._produced_moment(BASENAME, _status()["ts"] and _status()),
                         NOW - dt.timedelta(hours=0.06))
        self.assertIsNone(office._produced_moment("loop_health.json",
                                                  {"generated_at": _ts(0)}))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Объявления: схема, производитель, место в наборе шага
# ─────────────────────────────────────────────────────────────────────────────

class TheDeclarationsAreMeasuredNotGuessed(unittest.TestCase):

    def test_every_declared_field_is_written_by_the_producer(self):
        keys = office._source_keys(str(REPO / PRODUCER_SRC))
        self.assertIsNotNone(keys)
        for field in office._READ_SCHEMA[BASENAME]:
            self.assertIn(field.split(".")[0], keys)

    def test_the_live_shape_raises_no_word_about_the_declared_fields(self):
        head = "\n".join(office._schema_drift(BASENAME, _status(), root=str(REPO)))
        self.assertEqual(head, "", "объявление спорит с живой формой отчёта")

    def test_a_dropped_field_is_named_by_name(self):
        """Обратный контроль: пропавшее поле обязано быть НАЗВАНО.

        Какой из трёх исходов выпадет — расхождение, «отчёт старого образца»
        или «НЕ ИЗМЕРЕНО» — решает возраст отчёта против правки производителя,
        и это не предмет этого теста. Предмет — что молчания не будет.
        """
        doc = _status()
        del doc["checks"]
        head = office._schema_drift(BASENAME, doc, root=str(REPO))
        self.assertTrue(head, "поле пропало, а сторож схемы молчит")
        self.assertIn("checks", "\n".join(head))

    def test_the_declaration_is_not_padded_with_fields_nobody_reads(self):
        """Объявленное, но не читаемое — ложная строка расхождения."""
        read = self._fields_read_by_the_branch()
        declared = set(office._READ_SCHEMA[BASENAME])
        # `ts` читает общая строка возраста, а не эта ветка.
        self.assertEqual(sorted(declared - read - {"ts"}), [])

    def test_the_branch_reads_nothing_it_did_not_declare(self):
        read = self._fields_read_by_the_branch()
        declared = {f.split(".")[0] for f in office._READ_SCHEMA[BASENAME]}
        self.assertEqual(sorted(read - declared), [],
                         "ветка читает поле, о котором `_READ_SCHEMA` молчит: "
                         "дрейф производителя по нему пройдёт МИМО сторожа")

    def _fields_read_by_the_branch(self):
        src = (REPO / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        branch = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.comparators[0], ast.Constant)
                    and node.test.comparators[0].value == BASENAME):
                branch = node
        self.assertIsNotNone(branch, "ветки выжимки для этого артефакта нет вовсе")
        # ТОЛЬКО тело своей ветки. `elif`-цепочка в AST вложена, поэтому
        # `orelse` этого узла содержит ВСЕ последующие ветки файла: обход
        # целого узла дал бы 115 чужих полей и зеленел бы всегда (сцена,
        # негодная по построению — класс G144 п. 3).
        read = set()
        for stmt in branch.body:
            for node in ast.walk(stmt):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "get"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "data"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    read.add(node.args[0].value)
        return read

    def test_the_producer_is_declared(self):
        self.assertEqual(office._PRODUCER[BASENAME], PRODUCER_SRC)
        self.assertTrue((REPO / PRODUCER_SRC).exists())


class TheReaderIsActuallyWiredIn(unittest.TestCase):
    """Ветка без места в наборе шага 0-офис не исполнится ни разу."""

    def test_manifest_declares_the_artifact_for_this_consumer(self):
        _, entry = _manifest_entry()
        self.assertIsNotNone(entry, "артефакта нет в artifacts[] — шаг его не возьмёт")
        self.assertEqual(entry["status"], "active")
        self.assertIn(office.CONSUMER, entry["consumers"])

    def test_the_artifact_has_a_shelf_life_and_it_is_the_producers_own(self):
        """Второй дом порога расходится молча (ADR-513): срок берётся у писателя."""
        manifest, entry = _manifest_entry()
        self.assertIsInstance(entry.get("slo_hours"), (int, float))
        agent = next(a for a in manifest["agents"] if a["label"] == PRODUCER_AGENT)
        declared = next(p for p in agent["produces"] if p["artifact"] == ARTIFACT)
        self.assertEqual(entry["slo_hours"], declared["slo_hours"])

    def test_the_producer_is_not_its_own_consumer(self):
        """Цикл `producer == consumer` объявил бы читателем самого писателя."""
        _, entry = _manifest_entry()
        self.assertNotIn(PRODUCER_AGENT, entry["consumers"])

    def test_the_writers_service_state_is_deliberately_not_declared(self):
        """Поправка заказа: `uptime_prev_state.json` — состояние ПИСАТЕЛЯ.

        Его единственный законный читатель — сам писатель на следующем такте
        (дедуп тревог), поэтому объявлять его потребляемым нельзя: это был бы
        ровно тот цикл, который запрещён тестом выше. Положительный контроль
        поворота пункта: файл обязан ОСТАТЬСЯ необъявленным, и причина — замер
        у производителя, а не забывчивость.
        """
        _, entry = _manifest_entry(SERVICE_STATE)
        self.assertIsNone(entry, "служебное состояние писателя объявлено "
                                 "потребляемым — читателя у него нет и быть не "
                                 "должно, кроме самого писателя")
        src = (REPO / PRODUCER_SRC).read_text(encoding="utf-8")
        self.assertIn("alerts", src)
        self.assertIn("UPTIME_PREV_STATE_FILE", src)


if __name__ == "__main__":
    unittest.main()
