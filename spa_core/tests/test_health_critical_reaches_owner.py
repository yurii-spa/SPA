"""CRITICAL-вердикт о здоровье системы обязан ДОЙТИ. Теперь это измеряется.

Третий экземпляр одного класса — после стоп-крана (10.08) и внутридневной
проверки. `scripts/run_health_check.py` слал `category="p0"` через
`TelegramManager`, а тот отставлен: `_send_raw` ВСЕГДА возвращает False и
уводит текст в суточный дайджест.

Хуже потери был ДИАГНОЗ. Ниже стоял запасной путь `except: ok =
_send_telegram(...)`, но `mgr.send()` не БРОСАЕТ — он возвращает False, поэтому
`except` не срабатывал НИКОГДА: запасной путь был мёртв вместе с основным. А
оператору печаталось «suppressed (cooldown active)» — никакого остывания не
было, канал отставлен насовсем. Благополучное, самоустраняющееся объяснение
вечной тишины закрывает вопрос надёжнее, чем само молчание.

ЧЕСТНАЯ ГРАНИЦА (измерено циклом #205, а не предположено). Живой тревоги этот
дефект не съел: у скрипта единственный вызывающий — `run_daily_simulation.py`,
сам лежащий в базе неподключённых, и ни один plist/шелл/CI его не зовёт; живой
300-секундный `cycle_health_monitor` уходит в CRITICAL ровно по `cycle_gap`, а
его закрывает живой `com.spa.cycle_gap_monitor`. Чинилась ЛОВУШКА, а не
потерянная тревога — и тесты ниже утверждают ровно это, не больше.

ЧЕМ МЕРЯЕМ. Ни один тест не смотрит на написание вызова: каждый подменяет
ТРАНСПОРТ и требует исходящего сообщения (или его обоснованного отсутствия).
Проверка, никогда не видевшая настоящей поломки, — украшение; положительный
контроль ниже воспроизводит отставленный путь целиком.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import io
import json
import tempfile
import textwrap
import tokenize
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_health_check.py"


def _load_script():
    """Загрузить скрипт как модуль: он не пакет, импортом по имени не берётся."""
    spec = importlib.util.spec_from_file_location("_rhc_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rhc = _load_script()


def _code_only(src: str) -> str:
    """Убрать комментарии, оставив КОД (строковые литералы сохраняются).

    Структурный тест обязан судить о том, что ИСПОЛНЯЕТСЯ, а не о том, что
    написано в пояснении: разбор аварии в шапке файла сам содержит и
    `TelegramManager`, и «cooldown active». Без этого шага проверка краснела бы
    на РАССКАЗЕ о дефекте — ровно тогда, когда дефект уже устранён. Ложный
    отказ опаснее пропуска: он учит отключать проверку.
    """
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            out.append(tok.string if tok.type != tokenize.NL else "\n")
    except (tokenize.TokenError, IndentationError):
        return "\n".join(
            line.split("#", 1)[0] if "#" in line else line
            for line in src.splitlines()
        )
    return " ".join(out)


def _report(overall: str, **checks) -> dict:
    """Отчёт нужной формы. Время — вход, а не окружение (фиксированная метка)."""
    return {
        "overall": overall,
        "checked_at": "2026-08-12T18:00:00+00:00",
        "checks": {
            name: {"status": status, "detail": f"{name} is {status}"}
            for name, status in checks.items()
        },
        "recommendations": [],
    }


class _Transport:
    """Ловушка вместо телеграма: помнит всё, что реально ушло бы в сеть."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.messages: list[str] = []

    def __call__(self, text: str) -> bool:
        self.messages.append(text)
        return self.ok


class _EffectCase(unittest.TestCase):
    """Свой каталог состояния, подменённый транспорт — живое не трогаем."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.transport = _Transport()

    def _dispatch(self, report: dict, **kw):
        with mock.patch("spa_core.telegram.push_policy._send", self.transport):
            return rhc.dispatch_health_alert(report, data_dir=self.data_dir, **kw)


class TestTheCriticalVerdictActuallyLeaves(_EffectCase):
    """Главный вопрос: ушло ли сообщение. Не «есть ли вызов в коде»."""

    def test_a_critical_report_produces_an_outgoing_message(self):
        sent, why = self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))

        self.assertTrue(sent, f"CRITICAL обязан уйти владельцу, а вернулось: {why}")
        self.assertEqual(len(self.transport.messages), 1,
                         "ровно одно исходящее сообщение")

    def test_the_message_carries_what_broke(self):
        """Тревога без причины ничем не лучше молчания."""
        self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))

        text = self.transport.messages[0]
        self.assertIn("cycle_gap", text)
        self.assertIn("CRITICAL", text.upper())

    def test_a_dead_transport_is_reported_as_not_sent(self):
        """Канал отказал ⇒ False. Рапортовать успех нельзя."""
        self.transport.ok = False

        sent, why = self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))

        self.assertFalse(sent)
        self.assertTrue(why, "у отказа обязана быть названная причина")

    def test_the_event_key_is_tier1_whitelisted(self):
        """Ключ вне закрытого списка не может push'ить — он был бы демоцией."""
        from spa_core.telegram.push_policy import TIER1_WHITELIST

        self.assertIn(rhc.HEALTH_EVENT_KEY, TIER1_WHITELIST)


class TestTheSameIncidentDoesNotSpam(_EffectCase):
    """Отпечаток происшествия — набор упавших проверок, а не факт «плохо»."""

    def test_the_same_incident_twice_sends_once(self):
        self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))
        self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))

        self.assertEqual(len(self.transport.messages), 1,
                         "та же авария не будит владельца дважды")

    def test_a_different_failure_is_a_new_incident(self):
        """Сломалось ДРУГОЕ — это другая новость, и она обязана прозвучать."""
        self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))
        self._dispatch(_report("CRITICAL", data_freshness="CRITICAL"))

        self.assertEqual(len(self.transport.messages), 2)

    def test_two_crashes_without_named_checks_are_two_incidents(self):
        """Аварийный отчёт не содержит проверок — по первой рекомендации.

        Схлопнуть все такие падения в один отпечаток значило бы промолчать о
        втором, ДРУГОМ падении.
        """
        first = _report("CRITICAL")
        first["recommendations"] = ["run_all_checks raised: boom A"]
        second = _report("CRITICAL")
        second["recommendations"] = ["run_all_checks raised: boom B"]

        self._dispatch(first)
        self._dispatch(second)

        self.assertEqual(len(self.transport.messages), 2)


class TestBelowCriticalStaysInTheDigest(_EffectCase):
    """WARNING не будит владельца — это и есть замысел отставки, а не дефект."""

    def test_a_warning_pushes_nothing(self):
        sent, why = self._dispatch(_report("WARNING", data_freshness="WARNING"))

        self.assertFalse(sent)
        self.assertEqual(self.transport.messages, [],
                         "WARNING не Tier-1: push'а быть не должно")
        self.assertIn("дайджест", why)

    def test_a_warning_is_not_silently_dropped(self):
        """Не push — не значит «потеряно»: текст обязан лечь в дайджест."""
        self._dispatch(_report("WARNING", data_freshness="WARNING"))

        queue = self.data_dir / "telegram" / "digest_queue.json"
        self.assertTrue(queue.exists(), "очередь дайджеста не создана")
        self.assertIn("data_freshness", queue.read_text(encoding="utf-8"))

    def test_healthy_says_nothing_at_all(self):
        sent, why = self._dispatch(_report("HEALTHY"))

        self.assertFalse(sent)
        self.assertEqual(self.transport.messages, [])
        self.assertNotIn("дайджест", why)


class TestTheDiagnosisIsMeasuredNotGuessed(_EffectCase):
    """Неверный диагноз хуже молчания: он объясняет тишину и закрывает вопрос."""

    def test_a_blocked_push_is_never_called_a_cooldown(self):
        """Гейт мог не пустить по дедупу/потолку — «остывание» тут выдумка."""
        self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))
        sent, why = self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))

        self.assertFalse(sent)
        self.assertNotIn("cooldown active", why)
        self.assertTrue(why.strip(), "у «не ушло» обязана быть названная причина")

    def test_the_false_cooldown_line_is_gone_from_the_code(self):
        """Мутация проводки: верни строку — тест краснеет."""
        code = _code_only(inspect.getsource(rhc))

        self.assertNotIn("suppressed (cooldown active)", code)

    def test_the_dispatch_no_longer_touches_the_retired_manager(self):
        """Мутация проводки: верни `TelegramManager` — тест краснеет."""
        code = _code_only(inspect.getsource(rhc.dispatch_health_alert))

        self.assertNotIn("TelegramManager", code)
        self.assertIn("push_critical", code)

    def test_the_alert_never_raises_even_if_the_channel_explodes(self):
        """Тревога не смеет уронить саму проверку здоровья."""
        with mock.patch("spa_core.telegram.push_policy.push_critical",
                        side_effect=RuntimeError("boom")):
            sent, why = rhc.dispatch_health_alert(
                _report("CRITICAL", cycle_gap="CRITICAL"), data_dir=self.data_dir
            )

        self.assertFalse(sent)
        self.assertIn("boom", why)


class TestTheRetiredPathIsTheBugItself(_EffectCase):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария, воспроизведённая целиком.

    Если тревогу снова повесят на `TelegramManager`, этот тест покраснеет — а
    прежние (искавшие `category="p0"` в исходнике) остались бы зелёными.
    """

    def test_the_retired_manager_sends_nothing_and_admits_it(self):
        from spa_core.alerts.telegram_manager import TelegramManager

        with mock.patch("spa_core.telegram.push_policy._send", self.transport):
            result = TelegramManager(data_dir=self.data_dir).send(
                "🚨 SPA Health: CRITICAL",
                title="health_critical",
                category="p0",
            )

        self.assertFalse(result,
                         "отставленный путь ВСЕГДА возвращает False — это и был дефект")
        self.assertEqual(self.transport.messages, [],
                         "и не отправляет НИЧЕГО: текст уходил в суточный дайджест")

    def test_the_unreachable_fallback_is_gone(self):
        """`mgr.send()` не бросал ⇒ `except` не срабатывал НИКОГДА.

        Сырой отправитель в обход единственной инстанции push'а — путь, которым
        дефект возвращается. Его в модуле больше нет.
        """
        self.assertFalse(hasattr(rhc, "_send_telegram"))
        self.assertFalse(hasattr(rhc, "_keychain_get"))


class TestLiveStateIsNotTouched(_EffectCase):
    """Прогон тестов не смеет глушить НАСТОЯЩУЮ тревогу (уроки #180 / #193)."""

    def test_state_is_written_into_the_given_dir_and_nowhere_else(self):
        self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))

        state = self.data_dir / "telegram" / "push_state.json"
        self.assertTrue(state.exists(), "состояние push'а обязано лечь в СВОЙ каталог")
        doc = json.loads(state.read_text(encoding="utf-8"))
        self.assertIn(rhc.HEALTH_EVENT_KEY, json.dumps(doc))

    def test_the_repository_state_file_is_not_touched(self):
        live = _REPO_ROOT / "data" / "telegram" / "push_state.json"
        before = live.read_bytes() if live.exists() else None

        self._dispatch(_report("CRITICAL", cycle_gap="CRITICAL"))

        after = live.read_bytes() if live.exists() else None
        self.assertEqual(before, after, "живое состояние push'а изменено тестом")

    def test_the_runner_passes_its_data_dir_down(self):
        """Мутация проводки: убери `data_dir=` — прогон над песочницей начнёт
        писать в ЖИВОЕ edge-состояние и заглушит следующую тревогу.

        Судим по САМОМУ ВЫЗОВУ (AST), а не по наличию слова `data_dir` в теле:
        первая редакция этого теста искала подстроку — и осталась зелёной на
        мутации, потому что `data_dir` встречается в функции и без аргумента.
        Ровно тот класс, против которого написан весь файл, пойманный на себе.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(rhc.run_health_check)))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "dispatch_health_alert"
        ]

        self.assertEqual(len(calls), 1, "ровно один вызов доставки в раннере")
        self.assertIn(
            "data_dir", [kw.arg for kw in calls[0].keywords],
            "каталог проверки обязан ехать в доставку: иначе песочница пишет "
            "в живое состояние push'а и глушит следующую НАСТОЯЩУЮ тревогу",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
