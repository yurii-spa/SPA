"""Стоп-кран обязан дойти до владельца в САМЫЙ шумный день. Теперь измеряется.

Авария, которую воспроизводит каждый тест ниже
----------------------------------------------
10.08 стоп-кран сработал и простоял **13 часов незамеченным**. Он отработал
верно, и путь доставки формально существовал — `push_policy` знает ключ
`kill_switch` первым в Tier-1 whitelist. Утонула ДОСТАВКА: в тот день сторож
уже был красным по другой причине, дневной потолок в 10 сообщений выбрали
рутинные тревоги, и остановка торговли ушла в «⚠️ Ещё критические события — их
пока не показываю».

То есть самое важное событие, которое вообще может случиться с книгой,
доставлялось с тем же приоритетом, что рутинный WARN, — и проигрывало ему
гонку за место в дне.

Владелец 19.08 решил (вариант 1, ADR-089 §2): «Правится ПУТЬ УВЕДОМЛЕНИЯ;
порогов, логики и самого стоп-крана это не касается.» Порогов SOFT −5 % /
HARD −10 % и лестницы `check_drawdown_trigger`/`drawdown_tier` здесь нет ни
одного упоминания — и не должно быть.

Чем эти тесты мерят
-------------------
ЭФФЕКТОМ: подменённый транспорт и требование исходящего сообщения (или его
обоснованного отсутствия). Ни один не смотрит на написание вызова — этот урок
файл `test_killswitch_alert_reaches_owner.py` оплатил тринадцатью часами
тишины: там четыре теста были зелёными ровно потому, что проверяли наличие
подстроки в исходнике.

Обратные контроли обязательны и стоят рядом: освобождение стоп-крана от
потолка не имеет права отключить потолок для ВСЕХ (иначе мы починили бы немоту
и сломали защиту от заливки) и не имеет права ЕСТЬ чужой бюджет (иначе одна
остановка отняла бы место у десяти рутинных тревог — обмен одной немоты на
другую).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from spa_core.alerts.kill_switch_alert import EVENT_KEY, notify_kill_switch
from spa_core.telegram import push_policy


class _Transport:
    """Ловушка вместо телеграма: помнит всё, что реально ушло бы в сеть."""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.messages: list[str] = []

    def __call__(self, text: str) -> bool:
        self.messages.append(text)
        return self.ok


class _NoisyDay(unittest.TestCase):
    """Общая обвязка: свой каталог состояния, подменённый транспорт, ДЕНЬ УЖЕ
    ШУМНЫЙ — потолок выбран рутинными тревогами до последнего места."""

    #: Такой же, как в проде. Держим локально, чтобы тест не проверял сам себя
    #: константой из проверяемого модуля.
    CEILING = 10

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.transport = _Transport()

    #: Рутинные классы, которыми набирается шумный день. Каждый — СВОЙ класс:
    #: иначе edge-триггер погасил бы второй как «всё ещё плохо», день остался бы
    #: недобранным, и тест мерил бы не то, что заявляет.
    ROUTINE_KEYS = (
        "cycle_gap", "system_critical", "agent_health_critical",
        "core_agent_down", "rules_critical", "checkpoint_failed",
        "telegram_down", "cycle_failed", "peg_break", "red_flag",
    )

    def _exhaust_the_day(self, already: int = 0) -> None:
        """Добрать дневной потолок рутинными тревогами — как 10.08.

        ``already`` — сколько мест дня тест занял до вызова (например красным
        сторожем другого класса). Считать это обязан тест, а не «на глазок»:
        недобранный день молча превратил бы положительный контроль в проверку
        того, что и без починки зелено.
        """
        need = self.CEILING - already
        self.assertGreaterEqual(len(self.ROUTINE_KEYS) - already, need,
                                "классов рутинных тревог хватает на весь день")
        with mock.patch.object(push_policy, "_send", self.transport):
            for i, key in enumerate(self.ROUTINE_KEYS[already:already + need]):
                push_policy.push_critical(
                    key, "CRITICAL", f"рутинная тревога {i}", "тело",
                    held_protocol=True, dedup_key=f"routine-{i}",
                    data_dir=self.data_dir,
                )
        self.assertEqual(len(self.transport.messages), need,
                         "предусловие: день выбран ровно до потолка")
        self.assertEqual(self._ceiling_pushed(), self.CEILING,
                         "предусловие: бюджет дня исчерпан")
        self.transport.messages.clear()

    def _notify(self, reason: str, **kw) -> bool:
        with mock.patch.object(push_policy, "_send", self.transport):
            return notify_kill_switch(reason, data_dir=self.data_dir, **kw)

    def _ceiling_pushed(self) -> int:
        """Сколько мест дня потрачено по мнению самого состояния."""
        import json
        path = self.data_dir / "telegram" / "push_state.json"
        if not path.exists():
            return 0
        doc = json.loads(path.read_text())
        return int((doc.get("ceiling") or {}).get("pushed", 0))


class TestTheStopIsNotOneOfTheDaysEvents(_NoisyDay):
    """Главный вопрос: доходит ли остановка торговли в исчерпанный день."""

    def test_the_kill_switch_leaves_even_when_the_day_is_exhausted(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии 10.08 целиком.

        Снимите освобождение от потолка — тест краснеет ровно тем поведением,
        которое стоило тринадцати часов тишины.
        """
        self._exhaust_the_day()

        sent = self._notify("drawdown -10.4% HARD_KILL")

        self.assertTrue(sent, "остановка торговли обязана уйти в любой день")
        self.assertEqual(len(self.transport.messages), 1,
                         "ровно одно сообщение, а не «ещё события — открой /alerts»")
        self.assertIn("KILL SWITCH", self.transport.messages[0].upper())

    def test_it_leaves_once_and_the_repeat_is_silent(self):
        """«Уходит один раз» — вторая половина критерия приёмки карточки.

        Дневной цикл идёт десятки раз в сутки, внутридневная проверка — каждые
        пять минут. Освобождение от потолка без дедупа превратило бы починку в
        заливку, а заливку владелец выключает — и мы вернулись бы к тишине
        с другой стороны.
        """
        self._exhaust_the_day()
        reason = "drawdown -10.4% HARD_KILL"

        first = self._notify(reason)
        second = self._notify(reason)

        self.assertTrue(first)
        self.assertFalse(second, "тот же инцидент в шумный день — молчит")
        self.assertEqual(len(self.transport.messages), 1)

    def test_a_different_incident_rings_again_over_the_ceiling(self):
        """Иначе первая же авария навсегда заглушила бы все следующие."""
        self._exhaust_the_day()

        self._notify("drawdown -10.4% HARD_KILL")
        self._notify("threat_reactor: emergency breaker: HALT")

        self.assertEqual(len(self.transport.messages), 2)

    def test_a_red_guard_on_another_key_does_not_silence_it(self):
        """«При уже красном стороже» — дословно из критерия приёмки.

        Сторож другого класса стоит `bad` (10.08 так и было), день выбран.
        Стоп-кран это не касается ни в одном звене.
        """
        with mock.patch.object(push_policy, "_send", self.transport):
            push_policy.push_critical(
                self.ROUTINE_KEYS[0], "CRITICAL", "чужая авария", "тело",
                held_protocol=True, dedup_key="alien", data_dir=self.data_dir)
        self.assertEqual(push_policy.current_state(
            self.ROUTINE_KEYS[0], data_dir=self.data_dir), "bad")
        self.transport.messages.clear()
        self._exhaust_the_day(already=1)

        sent = self._notify("drawdown -11% HARD_KILL")

        self.assertTrue(sent)
        self.assertEqual(len(self.transport.messages), 1)


class TestTheExemptionDidNotBreakTheCeiling(_NoisyDay):
    """ОБРАТНЫЕ КОНТРОЛИ. Починка немоты не имеет права стать дырой."""

    def test_a_routine_alert_over_the_ceiling_is_still_demoted(self):
        """Потолок для всех остальных остался на месте.

        Если бы освобождение было сделано «поднять лимит» вместо «вывести один
        ключ», этот тест был бы зелёным при сломанной защите от заливки.
        """
        self._exhaust_the_day()

        with mock.patch.object(push_policy, "_send", self.transport):
            sent = push_policy.push_critical(
                "rules_critical", "CRITICAL", "рутинная тревога сверх потолка",
                "тело", dedup_key="over-the-top", data_dir=self.data_dir)

        self.assertFalse(sent, "рутинная тревога сверх потолка не проходит")
        self.assertEqual(len(self.transport.messages), 1,
                         "ушло только схлопнутое «ещё события», не сама тревога")
        self.assertIn("лимит", self.transport.messages[0].lower())

    def test_the_kill_switch_does_not_eat_the_routine_budget(self):
        """Остановка не тратит бюджет дня.

        Иначе одна остановка отнимала бы место у рутинных тревог — то есть мы
        обменяли бы одну немоту на другую, и заметили бы это на следующей
        аварии, а не здесь.
        """
        before = self._ceiling_pushed()
        self.assertEqual(before, 0, "предусловие: день ещё пуст")

        self._notify("drawdown -10.4% HARD_KILL")

        self.assertEqual(len(self.transport.messages), 1, "сообщение ушло")
        self.assertEqual(self._ceiling_pushed(), 0,
                         "бюджет дня остался нетронутым")

    def test_the_exemption_is_narrow(self):
        """Освобождён ровно стоп-кран, а не «критические события вообще».

        Набор — предмет решения владельца; расширение его молча (например
        «заодно и system_critical») вернуло бы дефект заливки под другим именем.
        """
        self.assertEqual(push_policy.CEILING_EXEMPT_KEYS, frozenset({EVENT_KEY}))


class TestTheFloodGuardCanStillDelayItButNotEatIt(_NoisyDay):
    """Минутный заслон потока — не потолок дня, и он ОТДЕЛЬНЫЙ вид отказа.

    Тревога, которую съел заслон, обязана быть повторена: `entry_pushed: false`
    — это «не доставлено», и следующая проверка (каждые 5 минут) досылает.
    Именно на этом месте в проде `kill_switch` завис `bad` с 04.07.
    """

    def test_a_refused_transport_is_retried_next_time(self):
        self._exhaust_the_day()
        reason = "drawdown -10.4% HARD_KILL"

        dead = _Transport(ok=False)
        with mock.patch.object(push_policy, "_send", dead):
            first = notify_kill_switch(reason, data_dir=self.data_dir)

        self.assertFalse(first, "канал отказал — рапортовать успех нельзя")

        second = self._notify(reason)

        self.assertTrue(second, "недоставленная тревога обязана быть досланной")
        self.assertEqual(len(self.transport.messages), 1)


class TestEveryLatchSourceHasAVoice(unittest.TestCase):
    """«Из ЛЮБОГО источника» — дословно из решения владельца.

    Автоматическая постановка (`run_kill_switch_check` → дневной цикл),
    внутридневная (ADR-068) и `threat_reactor` звонили каждая своим путём.
    РУЧНАЯ — единственная — уходила в `print`, то есть в лог, который в момент
    остановки торговли никто не читает.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.transport = _Transport()

    def test_a_manual_latch_tells_the_owner(self):
        from spa_core.execution import safety_checks as sc

        sc.set_data_dir_override(self.data_dir)
        self.addCleanup(sc.set_data_dir_override, None)

        with mock.patch.object(push_policy, "_send", self.transport):
            sc.PreExecutionSafety.activate_kill_switch("owner pulled the brake")

        self.assertEqual(len(self.transport.messages), 1,
                         "ручная постановка обязана дойти до владельца")
        text = self.transport.messages[0]
        self.assertIn("owner pulled the brake", text, "причина обязана быть в тексте")
        self.assertIn("ручная постановка", text, "источник обязан быть назван")

    def test_the_latch_is_written_before_anyone_is_told(self):
        """Если сбой телеграма отменит остановку, лечение опаснее болезни."""
        from spa_core.execution import safety_checks as sc

        sc.set_data_dir_override(self.data_dir)
        self.addCleanup(sc.set_data_dir_override, None)
        latch = self.data_dir / "kill_switch_active.json"

        def _explode(_text: str) -> bool:
            raise RuntimeError("канал лёг")

        with mock.patch.object(push_policy, "_send", _explode):
            sc.PreExecutionSafety.activate_kill_switch("brake with a dead channel")

        self.assertTrue(latch.exists(),
                        "защёлка обязана стоять даже при мёртвом канале")


class TestTheNewVoiceDoesNotReachTheLiveChannel(unittest.TestCase):
    """У ручной постановки появился голос — он обязан быть ИЗОЛИРОВАН в тестах.

    Свойство «прогон тестов не звонит владельцу» в репозитории уже есть и
    принадлежит стражу `spa_core/tests/telegram_guard.py` (цикл #58): он
    перехватывает `urlopen`, роняет тест и НАЗЫВАЕТ его. Второй, тихий заслон
    внутри `push_policy._send` я начал писать и снял — он ослепил бы стража
    (попытка не дошла бы до перехвата, новый нарушитель перестал бы называться).

    Здесь проверяется то, за что отвечает уже НАШ код: новый вызов уведомления
    ходит в тот же каталог состояния, что и защёлка, — то есть тест, изолировавший
    защёлку, изолировал и тревогу, и живой `data/` не трогается ни одним из двух.
    """

    def test_the_manual_latch_writes_its_alert_state_where_the_latch_goes(self):
        from spa_core.execution import safety_checks as sc

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name)
        sc.set_data_dir_override(data_dir)
        self.addCleanup(sc.set_data_dir_override, None)
        live = Path(push_policy.__file__).resolve().parents[2] / "data" / "telegram"
        before = sorted(p.name for p in live.glob("*.json")) if live.exists() else []

        with mock.patch.object(push_policy, "_send", _Transport()):
            sc.PreExecutionSafety.activate_kill_switch("isolation probe")

        self.assertTrue((data_dir / "telegram" / "push_state.json").exists(),
                        "состояние тревоги обязано лечь в тот же каталог, что защёлка")
        after = sorted(p.name for p in live.glob("*.json")) if live.exists() else []
        self.assertEqual(before, after, "живой data/ не трогается")
