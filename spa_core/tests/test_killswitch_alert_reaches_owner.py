"""Стоп-кран сработал ⇒ владелец обязан узнать. Теперь это ИЗМЕРЯЕТСЯ.

История этого файла — сама по себе находка, и её стоит держать перед глазами.

**06.08.** Замер прошёл всю цепочку и нашёл разрыв в каждом звене: `kill_switch`
писал вердикт в файл и на этом всё; `risk_sentinel` и `incident_commander` не
отправляют и не запущены; `reporting_agent` умеет, но его нет в флоте; вызовов
`category="p0"` — канала, построенного ИМЕННО для стоп-крана, — во всём коде
ноль. Владелец решил: «чинить СЕЙЧАС, не дожидаясь просадки». Починка добавила
два вызова, и родились четыре теста — вот эти.

**Чем они мерили.** Каждый: `inspect.getsource(...)` + `assertIn('category="p0"')`.
Файл при этом обещал в своей же шапке «требуют ФАКТА исходящего сообщения».
Он требовал наличия подстроки в исходнике.

**10.08, 00:52 UTC.** Стоп-кран сработал по-настоящему (EB-02). Оба вызова
оказались холостыми: `TelegramManager` отставлен в ходе Phase-1 Telegram
rebuild, его `_send_raw` ВСЕГДА возвращает False и уводит текст в суточный
дайджест. `cycle_runner` при этом писал в лог «отправлен владельцу»
безусловно, не глядя на возврат. Тесты всё это время были зелёными: строка
`category="p0"` в исходнике честно присутствовала.

Владелец в тот день узнал — но по ДРУГОМУ пути (`threat_reactor` шлёт через
`push_policy`, в состоянии видно `entry_pushed: true`). У внутридневной
проверки (ADR-068) такой дублёрки нет: там тишина была бы полной.

**Поэтому здесь.** Ни один тест ниже не смотрит на написание вызова. Каждый
подменяет ТРАНСПОРТ и требует исходящего сообщения (или его обоснованного
отсутствия). Плюс положительный контроль, воспроизводящий аварию 10.08:
отставленный путь обязан краснеть. Проверка, никогда не видевшая настоящей
поломки, — украшение; эта видела.

Структурные тесты остались ровно на то, что эффектом не проверить: ПОРЯДОК
(сначала стоп-кран применён, потом уведомили) и отсутствие безусловного
рапорта об успехе.
"""
from __future__ import annotations

import inspect
import io
import tempfile
import tokenize
import unittest
from pathlib import Path
from unittest import mock

from spa_core.alerts.kill_switch_alert import EVENT_KEY, notify_kill_switch


def _code_only(src: str) -> str:
    """Убрать комментарии, оставив КОД (строковые литералы сохраняются).

    Структурные тесты обязаны судить о том, что исполняется, а не о том, что
    написано в пояснении. Разбор аварии 10.08 сам по себе содержит слово
    `TelegramManager` — и без этого шага тест краснел бы на РАССКАЗЕ о дефекте,
    ровно тогда, когда дефект уже устранён. Ложный отказ опаснее пропуска: он
    учит отключать проверку.
    """
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            out.append(tok.string if tok.type != tokenize.NL else "\n")
    except (tokenize.TokenError, IndentationError):
        # Срез исходника может быть синтаксически неполным — тогда достаточно
        # построчной чистки. Терять проверку из-за формы среза нельзя.
        return "\n".join(
            line.split("#", 1)[0] if "#" in line else line
            for line in src.splitlines()
        )
    return " ".join(out)


def _norm(text: str) -> str:
    """Схлопнуть пробелы: после токенизации `if x:` выглядит как `if x :`.

    Проверять надо смысл кода, а не расстановку пробелов в нём.
    """
    return " ".join(text.split())


def _code_needle(snippet: str) -> str:
    """Привести искомый КОД к той же форме, что и просматриваемый.

    Токенайзер разносит `log.critical` в `log . critical`; сравнивать надо
    одинаково обработанные стороны, иначе тест краснеет на форматировании.
    Литералы («ТРЕВОГА НЕ …») в этом не нуждаются — они сохраняются дословно.
    """
    return _norm(_code_only(snippet))


def _trigger_branch_source(cycle_runner) -> str:
    """Ветка срабатывания стоп-крана, от применения до записи в notes.

    Границы — якоря, а не длина: срез по числу символов молча укорачивался бы
    при каждом новом комментарии, и проверка тихо переставала бы видеть свой
    предмет.
    """
    src = inspect.getsource(cycle_runner)
    start = src.index("_ks_allocation = dict")
    end = src.index('notes.append(f"kill_switch_active', start)
    return _code_only(src[start:end])


class _Transport:
    """Ловушка вместо телеграма: запоминает всё, что реально ушло бы в сеть."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.messages: list[str] = []

    def __call__(self, text: str) -> bool:
        self.messages.append(text)
        return self.ok


class _EffectCase(unittest.TestCase):
    """Общая обвязка: свой каталог состояния, подменённый транспорт."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.transport = _Transport()

    def _notify(self, reason: str, **kw) -> bool:
        with mock.patch("spa_core.telegram.push_policy._send", self.transport):
            return notify_kill_switch(reason, data_dir=self.data_dir, **kw)


class TestTheAlertActuallyLeaves(_EffectCase):
    """Главный вопрос: ушло ли сообщение. Не «есть ли вызов в коде»."""

    def test_a_fired_kill_switch_produces_an_outgoing_message(self):
        sent = self._notify("drawdown -5.2% SOFT_DERISK")

        self.assertTrue(sent, "стоп-кран сработал — сообщение обязано уйти")
        self.assertEqual(len(self.transport.messages), 1,
                         "ровно одно исходящее сообщение")

    def test_the_message_carries_the_reason_the_owner_needs(self):
        """Сообщение без причины ничем не лучше молчания."""
        self._notify("threat_reactor: emergency breaker: HALT")

        text = self.transport.messages[0]
        self.assertIn("HALT", text)
        self.assertIn("KILL SWITCH", text.upper())

    def test_the_source_is_named_so_the_owner_knows_who_saw_it(self):
        """«Дневной цикл» и «внутридневная проверка» — разные новости."""
        self._notify("drawdown -11%", source="внутридневная проверка")

        self.assertIn("внутридневная проверка", self.transport.messages[0])

    def test_a_dead_transport_is_reported_as_not_sent(self):
        """Канал отказал ⇒ False. Именно это и не проверялось раньше."""
        self.transport.ok = False

        sent = self._notify("drawdown -6%")

        self.assertFalse(sent, "транспорт отказал — рапортовать успех нельзя")


class TestTheRetiredPathIsTheBugItself(_EffectCase):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария 10.08, воспроизведённая целиком.

    Если однажды тревогу снова повесят на `TelegramManager`, эти тесты
    покраснеют — а прежние остались бы зелёными.
    """

    def test_the_retired_manager_sends_nothing_and_admits_it(self):
        from spa_core.alerts.telegram_manager import TelegramManager

        with mock.patch("spa_core.telegram.push_policy._send", self.transport):
            result = TelegramManager().send(
                "🚨 KILL SWITCH: drawdown -6%",
                title="kill_switch",
                category="p0",
            )

        self.assertFalse(result,
                         "отставленный путь ВСЕГДА возвращает False — это и был дефект")
        self.assertEqual(self.transport.messages, [],
                         "и не отправляет НИЧЕГО: текст уходил в суточный дайджест")

    def test_the_daily_cycle_no_longer_uses_it(self):
        """Мутация проводки: удали починку — тест краснеет."""
        from spa_core.paper_trading import cycle_runner

        branch = self._trigger_branch(cycle_runner)
        self.assertNotIn("TelegramManager", branch,
                         "ветка срабатывания обязана идти каноническим путём")
        self.assertIn("notify_kill_switch", branch)

    def test_the_intraday_check_no_longer_uses_it(self):
        from spa_core.monitoring import cycle_health_monitor as chm

        src = inspect.getsource(chm)
        tail = src[src.index("run_kill_switch_check"):]
        tail = _code_only(tail[:tail.index("# Human-readable output")])
        self.assertNotIn("TelegramManager", tail,
                         "у внутридневной проверки дублёрки нет — путь обязан быть живым")
        self.assertIn("notify_kill_switch", tail)

    @staticmethod
    def _trigger_branch(cycle_runner) -> str:
        return _trigger_branch_source(cycle_runner)


class TestOneIncidentIsOneMessage(_EffectCase):
    """Дневной цикл идёт десятки раз в сутки, внутридневная проверка — каждые
    5 минут. Без дедупликации починка превратилась бы в спам, а спам владелец
    выключает — и мы вернулись бы к тишине с другой стороны."""

    def test_the_same_incident_pushed_twice_sends_once(self):
        reason = "threat_reactor: emergency breaker: HALT"

        first = self._notify(reason)
        second = self._notify(reason)

        self.assertTrue(first)
        self.assertFalse(second, "тот же отпечаток — повтор молчит")
        self.assertEqual(len(self.transport.messages), 1)

    def test_two_watchers_seeing_one_incident_send_once(self):
        """Один инцидент, замеченный циклом и внутридневной проверкой, —
        одно сообщение: отпечаток берётся от ПРИЧИНЫ, не от источника."""
        reason = "drawdown -10.4% HARD_KILL"

        self._notify(reason, source="дневной цикл")
        self._notify(reason, source="внутридневная проверка")

        self.assertEqual(len(self.transport.messages), 1)

    def test_a_different_reason_is_a_new_incident(self):
        """Иначе первая же авария навсегда заглушила бы все следующие —
        ровно та жалоба, с которой карточка и начиналась («застряло в плохо
        с 4 июля»)."""
        self._notify("drawdown -5.2% SOFT_DERISK")
        self._notify("drawdown -10.4% HARD_KILL")

        self.assertEqual(len(self.transport.messages), 2)


class TestTheChannelItRelaysOn(unittest.TestCase):
    """То, на что опирается доставка, обязано существовать с нужными свойствами."""

    def test_the_event_key_is_tier1_whitelisted(self):
        """Ключ вне whitelist молча демотируется в дайджест — то есть опечатка
        здесь неотличима от исправной работы. Fail-closed by design."""
        from spa_core.telegram.push_policy import TIER1_WHITELIST

        self.assertIn(EVENT_KEY, TIER1_WHITELIST)

    def test_the_alert_never_raises_even_if_the_channel_explodes(self):
        """Сбой доставки не имеет права отменить сам стоп-кран."""
        with mock.patch("spa_core.telegram.push_policy.push_critical",
                        side_effect=RuntimeError("канал лёг")):
            self.assertFalse(notify_kill_switch("drawdown -7%"))


class TestTheOrderAndTheHonestLog(unittest.TestCase):
    """Эффектом не проверить: порядок действий и отсутствие ложного рапорта."""

    def setUp(self):
        from spa_core.paper_trading import cycle_runner

        self.branch = _norm(_trigger_branch_source(cycle_runner))

    def test_the_kill_switch_is_applied_before_anyone_is_told(self):
        """Если сбой телеграма отменит стоп-кран, лечение опаснее болезни."""
        self.assertLess(self.branch.index("_ks_allocation = dict"),
                        self.branch.index("notify_kill_switch"))

    def test_the_send_has_its_own_handler(self):
        self.assertIn("except Exception", self.branch,
                      "отправка обязана иметь СВОЙ обработчик")

    def test_success_is_never_logged_unconditionally(self):
        """Сердцевина дефекта 10.08: лог рапортовал «отправлен владельцу», не
        глядя на возврат. Успех обязан быть ПОД условием."""
        ok_at = self.branch.index("отправлен владельцу")
        guard = self.branch[:ok_at]
        self.assertIn(_code_needle("if _ks_sent:"), guard,
                      "рапорт об успехе обязан стоять под проверкой возврата")

    def test_a_silent_failure_to_notify_is_itself_loud(self):
        """Не ушедшая тревога обязана быть видна ОТДЕЛЬНЫМ событием, иначе мы
        заменим одну тишину другой."""
        self.assertIn("ТРЕВОГА НЕ", self.branch)
        self.assertIn(_code_needle("log.critical"), self.branch)


if __name__ == "__main__":
    unittest.main()


class TestTheAlertNeverTouchesLiveState(_EffectCase):
    """Состояние тревоги обязано следовать за каталогом ВЫЗЫВАЮЩЕГО.

    Замер #193, найдено регрессией: перевод тревоги на живой канон сделал её
    доставку настоящей — и тем самым открыл вторую дверь к той же беде.
    `push_policy` без `data_dir` берёт РЕПОЗИТОРНЫЙ `data/telegram`, а его
    состояние edge-триггерное: прогон над песочницей пометил бы `kill_switch`
    как уже отправленный, и СЛЕДУЮЩАЯ НАСТОЯЩАЯ тревога промолчала бы. То есть
    починка доставки, сделанная без этого, сама воспроизвела бы дефект, ради
    которого затевалась, — только с другой стороны.
    """

    def test_state_is_written_into_the_given_dir_and_nowhere_else(self):
        self._notify("drawdown -7%")

        self.assertTrue(
            (self.data_dir / "telegram" / "push_state.json").exists(),
            "состояние обязано лечь в переданный каталог",
        )

    def test_the_repository_state_file_is_not_touched(self):
        """Положительный контроль: живой файл не меняется от нашего вызова."""
        from spa_core.telegram import push_policy

        live = Path(push_policy._DEFAULT_TG_DIR) / push_policy.PUSH_STATE_FILENAME
        before = live.read_bytes() if live.exists() else None

        self._notify("drawdown -8.1% (проверка изоляции)")

        after = live.read_bytes() if live.exists() else None
        self.assertEqual(before, after,
                         "вызов с собственным каталогом не имеет права трогать живое состояние")


class TestBothWatchersPassTheirOwnDir(unittest.TestCase):
    """Проводка: оба отправителя обязаны ПЕРЕДАВАТЬ свой каталог.

    Урок #144 («мутируй проводку, а не деталь»): сама функция изоляцию умеет,
    но если вызывающий каталог не передал — изоляции нет. Проверяется ВЫЗОВ.
    """

    def test_the_daily_cycle_passes_its_data_dir(self):
        from spa_core.paper_trading import cycle_runner

        branch = _norm(_trigger_branch_source(cycle_runner))
        self.assertIn(_code_needle("data_dir=ddir"), branch,
                      "дневной цикл обязан отдавать тревоге СВОЙ каталог")

    def test_the_intraday_check_passes_its_data_dir(self):
        from spa_core.monitoring import cycle_health_monitor as chm

        src = inspect.getsource(chm)
        tail = src[src.index("run_kill_switch_check"):]
        tail = _norm(_code_only(tail[:tail.index("# Human-readable output")]))
        self.assertIn(_code_needle("data_dir=data_dir"), tail,
                      "внутридневная проверка обязана отдавать тревоге СВОЙ каталог")
