"""Батарея к переписи командных поверхностей владельца (ADR-712).

Предмет — карточка `inbox-dva-obyavleniya-komand-bota-rashodyatsya` и пятый
пункт заказа G711: набор команд владельца был объявлен в дереве ТРИЖДЫ, и
прибор органов владельца читал ту копию, которую Telegram владельцу не
показывает.

Порядок батареи: у каждого звена ОБРАТНАЯ сторона с НАЗВАННЫМ звеном.
Положительные контроли — не украшение: каждый ломает ровно одно звено на
ОДНОРАЗОВОЙ копии дерева и требует, чтобы перепись это назвала. Живое дерево
при этом не правится ни в одном тесте.

Почему контроль идёт по копии ФАЙЛОВ, а не по подмене функций: предмет
переписи — ТЕКСТ дерева, и подменив разбор, мы проверили бы не её. Копия
кладётся в `tmp_path`-подобный каталог, пути внутри переписи — вход (`root`).
"""

from __future__ import annotations

import ast
import pathlib
import shutil
import tempfile
import unittest
import unittest.mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import owner_command_surfaces as ocs

LIVE_ROOT = ocs.REPO_ROOT


def _disposable_tree() -> pathlib.Path:
    """Одноразовая копия ДВУХ файлов, которые читает перепись, и только их."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="ocs_"))
    for rel in (ocs.BOT_REL, ocs.ROUTER_REL):
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pathlib.Path(LIVE_ROOT) / rel, dst)
    return root


class _Tree(unittest.TestCase):
    """Общая сцена: одноразовая копия, убирается в любом случае."""

    def setUp(self) -> None:
        self.root = _disposable_tree()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.bot = self.root / ocs.BOT_REL
        self.router = self.root / ocs.ROUTER_REL

    def measure(self) -> dict:
        return ocs.measure(str(self.root))

    def patch_bot(self, old: str, new: str) -> None:
        """Точечная правка копии. Отсутствие якоря — ГРОМКИЙ отказ, не тихий ноль."""
        text = self.bot.read_text(encoding="utf-8")
        self.assertIn(old, text, "предпосылка контроля НЕ ОБЕСПЕЧЕНА: якорь не найден")
        self.bot.write_text(text.replace(old, new, 1), encoding="utf-8")


# ─────────────── 1. исход на ЖИВОМ дереве: ноль обязан быть ИЗМЕРЕН ───────────


class TestLiveTree(unittest.TestCase):
    """Вердикт по дереву, которое доставляется. Это и есть предмет карточки."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.m = ocs.measure(LIVE_ROOT)

    def test_the_zero_is_measured_and_not_an_empty_set(self):
        """Звено: третий исход. Пустая перепись НЕ имеет права читаться как «чисто»."""
        self.assertIsNone(self.m["unmeasured"], self.m["unmeasured"])
        self.assertTrue(self.m["advertised"], "меню ☰ не снято — ноль не измерен")
        self.assertTrue(self.m["dispatched"], "карта диспетчера не снята")
        self.assertTrue(self.m["routed"], "маршруты набора не сняты")
        self.assertTrue(self.m["buttoned"], "кнопки не сняты")

    def test_no_declaration_is_a_copy_of_another_surface(self):
        """Звено: детектор копий. Это дефект, ради которого карточка написана."""
        self.assertEqual(self.m["duplicate_declarations"], [],
                         ocs.findings(self.m))

    def test_no_dead_door_in_the_dispatcher_map(self):
        """Звено: мёртвая дверь. Запись, до которой не доходит ни один путь."""
        self.assertEqual(self.m["dispatched_not_reachable"], [], ocs.findings(self.m))

    def test_every_advertised_command_is_reachable(self):
        """Звено: обещание без двери. Владелец видит в меню то, чего нет."""
        self.assertEqual(self.m["advertised_not_reachable"], [], ocs.findings(self.m))

    def test_every_unadvertised_reachable_command_names_its_reason(self):
        """Звено: расхождение без причины. Равенства множеств НЕ требуется."""
        self.assertEqual(self.m["unexplained_divergence"], [], ocs.findings(self.m))
        self.assertTrue(self.m["reachable_not_advertised"],
                        "расхождение исчезло ВОВСЕ — значит проверка больше не "
                        "о том предмете: /pause намеренно вне меню ☰")

    def test_no_reason_outlived_its_door(self):
        """Звено: устаревшее исключение. Причина без двери — способ промолчать."""
        self.assertEqual(self.m["stale_reasons"], [], ocs.findings(self.m))

    def test_no_reason_is_blank(self):
        """Звено: «и так понятно» причиной не является."""
        self.assertEqual(self.m["reasons_without_cause"], [], ocs.findings(self.m))

    def test_findings_are_empty_only_when_every_link_is_whole(self):
        """Сводка: ноль находок на живом дереве."""
        self.assertEqual(ocs.findings(self.m), [])

    def test_the_emergency_stop_stayed_in_the_organ_census(self):
        """Звено: равнять «обещано» и «достижимо» ЗАПРЕЩЕНО.

        Положительный контроль самой ИДЕИ правки: если бы критерий требовал
        равенства множеств, `/pause` ушёл бы из переписи органов владельца —
        то есть находка `CONFLATED` погасла бы слепотой. Этот тест краснеет,
        как только аварийная остановка перестанет быть достижимой.
        """
        self.assertIn("/pause", self.m["reachable"])
        self.assertNotIn("/pause", self.m["advertised"])
        self.assertIn("/pause", self.m["reasons"])


# ─────────── 2. положительные контроли: по одному порванному звену ───────────


class TestBrokenCopyDeclaration(_Tree):
    def test_a_second_hand_written_copy_of_the_dispatcher_set_is_named(self):
        """ЗВЕНО «детектор копий»: возвращаю снятый `_COMMANDS` — перепись обязана назвать.

        Это дословное воспроизведение состояния `origin/main` до 13.10.
        """
        copy = ('    _COMMANDS = (\n'
                '        "/start", "/menu", "/status", "/portfolio", "/today",\n'
                '        "/week", "/agents", "/alerts", "/pause", "/resume", "/why",\n'
                '        "/protocols",\n'
                '    )\n\n    def _dispatch(')
        self.patch_bot("    def _dispatch(", copy)
        m = self.measure()
        self.assertEqual(len(m["duplicate_declarations"]), 1, ocs.findings(m))
        self.assertEqual(m["duplicate_declarations"][0]["name"], "_COMMANDS")
        self.assertEqual(m["duplicate_declarations"][0]["copy_of"], "dispatched")
        self.assertTrue(any("КОПИЯ ОБЪЯВЛЕНИЯ" in f for f in ocs.findings(m)))

    def test_a_declaration_that_is_not_a_copy_is_not_accused(self):
        """ОБРАТНАЯ сторона того же звена: `_INTERCEPTED_COMMANDS` копией НЕ является.

        Обвинить его значило бы заставить автора снять ВЕРНОЕ объявление —
        источник своей поверхности, чью правдивость мерит отдельный сторож.
        """
        m = self.measure()
        self.assertIn("_INTERCEPTED_COMMANDS", m["declared"])
        self.assertEqual(m["duplicate_declarations"], [])


class TestBrokenCopyDeadDoor(_Tree):
    def test_a_map_entry_no_path_reaches_is_named(self):
        """ЗВЕНО «мёртвая дверь»: запись в карте без кнопки, маршрута и перехвата."""
        self.patch_bot('            "/start":     self.cmd_start,',
                       '            "/start":     self.cmd_start,\n'
                       '            "/ghost":     self.cmd_start,')
        m = self.measure()
        self.assertEqual(m["dispatched_not_reachable"], ["/ghost"], ocs.findings(m))
        self.assertTrue(any("МЁРТВАЯ ДВЕРЬ" in f for f in ocs.findings(m)))

    def test_a_map_entry_a_button_reaches_is_not_named(self):
        """ОБРАТНАЯ сторона: та же запись С кнопкой мёртвой дверью не является."""
        self.patch_bot('            "/start":     self.cmd_start,',
                       '            "/start":     self.cmd_start,\n'
                       '            "/ghost":     self.cmd_start,')
        self.patch_bot('{"text": "📊 Статус системы", "callback_data": "/status"},',
                       '{"text": "📊 Статус системы", "callback_data": "/status"},\n'
                       '                {"text": "ghost", "callback_data": "/ghost"},')
        m = self.measure()
        self.assertEqual(m["dispatched_not_reachable"], [], ocs.findings(m))
        self.assertIn("/ghost", m["reachable"])


class TestBrokenCopyDivergence(_Tree):
    def test_a_reachable_command_without_a_named_reason_is_red(self):
        """ЗВЕНО «расхождение без причины»: это и есть «добавил в один, забыл в другом»."""
        text = self.router.read_text(encoding="utf-8")
        anchor = '"/warnings"'
        self.assertIn(anchor, text, "предпосылка НЕ ОБЕСПЕЧЕНА: якорь маршрута не найден")
        self.router.write_text(
            text.replace(anchor, '"/brandnew": "home",\n    ' + anchor, 1),
            encoding="utf-8")
        m = self.measure()
        self.assertEqual(m["unexplained_divergence"], ["/brandnew"], ocs.findings(m))
        self.assertTrue(any("РАСХОЖДЕНИЕ БЕЗ ПРИЧИНЫ" in f for f in ocs.findings(m)))

    def test_the_same_command_with_a_named_reason_is_not_red(self):
        """ОБРАТНАЯ сторона: названная причина закрывает ровно это расхождение."""
        text = self.router.read_text(encoding="utf-8")
        self.router.write_text(
            text.replace('"/warnings"', '"/brandnew": "home",\n    "/warnings"', 1),
            encoding="utf-8")
        self.patch_bot('        "/why": "кнопка',
                       '        "/brandnew": "внутренний экран, причина названа",\n'
                       '        "/why": "кнопка')
        m = self.measure()
        self.assertEqual(m["unexplained_divergence"], [], ocs.findings(m))

    def test_an_advertised_command_with_no_door_is_named(self):
        """ЗВЕНО «обещание без двери»: меню ☰ обещает то, до чего нет пути."""
        self.patch_bot('{"command": "start",      "description": "Главная панель SPA"},',
                       '{"command": "start",      "description": "Главная панель SPA"},\n'
                       '            {"command": "nowhere", "description": "никуда"},')
        m = self.measure()
        self.assertEqual(m["advertised_not_reachable"], ["/nowhere"], ocs.findings(m))
        self.assertTrue(any("ОБЕЩАНИЕ БЕЗ ДВЕРИ" in f for f in ocs.findings(m)))


class TestBrokenCopyReasons(_Tree):
    def test_a_reason_that_outlived_its_door_is_named(self):
        """ЗВЕНО «причина пережила дверь»: кнопку сняли, исключение осталось."""
        self.patch_bot('{"text": "🛑 Аварийная остановка", "callback_data": "/pause"},', "")
        m = self.measure()
        self.assertIn("/pause", m["stale_reasons"])
        self.assertNotIn("/pause", m["reachable"])
        self.assertTrue(any("ПРИЧИНА ПЕРЕЖИЛА ДВЕРЬ" in f for f in ocs.findings(m)))

    def test_a_blank_reason_is_named(self):
        """ЗВЕНО «пустая причина»: исключение без причины исключением не является."""
        self.patch_bot('        "/why": "кнопка «❓ Почему ❌?» на панели, не команда меню",',
                       '        "/why": "   ",')
        m = self.measure()
        self.assertEqual(m["reasons_without_cause"], ["/why"], ocs.findings(m))
        self.assertTrue(any("ПРИЧИНА ПУСТА" in f for f in ocs.findings(m)))


class TestThirdOutcome(_Tree):
    """Инв. #17: «не измерено» обязано быть отдельным значением, а не нулём."""

    def test_an_unparsable_owner_channel_is_unmeasured_not_clean(self):
        """ЗВЕНО «третий исход» у канала владельца."""
        self.bot.write_text("def broken(:\n", encoding="utf-8")
        m = self.measure()
        self.assertIsNotNone(m["unmeasured"])
        self.assertIn("SyntaxError", m["unmeasured"])
        self.assertEqual(m["duplicate_declarations"], [])
        self.assertEqual(ocs.findings(m), [f"НЕ ИЗМЕРЕНО: {m['unmeasured']}"])

    def test_a_missing_route_map_is_unmeasured_not_clean(self):
        """ЗВЕНО «третий исход» у карты набранных команд."""
        self.router.unlink()
        m = self.measure()
        self.assertIsNotNone(m["unmeasured"])
        self.assertEqual(ocs.findings(m), [f"НЕ ИЗМЕРЕНО: {m['unmeasured']}"])

    def test_a_route_map_renamed_away_is_unmeasured_not_zero(self):
        """Файл есть, реестра в нём нет: пустые маршруты НЕ выдаются за ноль."""
        text = self.router.read_text(encoding="utf-8")
        self.router.write_text(
            text.replace(f"{ocs.ROUTER_MAP_NAME} =", "COMMAND_TO_PATH_RENAMED =", 1),
            encoding="utf-8")
        m = self.measure()
        self.assertIsNotNone(m["unmeasured"])
        self.assertIn(ocs.ROUTER_MAP_NAME, m["unmeasured"])

    def test_a_class_renamed_away_is_unmeasured_not_zero(self):
        """Класс канала не найден — тоже третий исход, а не «поверхностей ноль»."""
        self.patch_bot("class TelegramBot", "class TelegramBotRenamed")
        m = self.measure()
        self.assertIsNotNone(m["unmeasured"])
        self.assertIn("TelegramBot", m["unmeasured"])

    def test_the_exit_code_separates_all_three_outcomes(self):
        """Код возврата различает чисто / находка / НЕ ИЗМЕРЕНО — три значения."""
        self.assertEqual(ocs._main(["--root", LIVE_ROOT]), 0)
        self.patch_bot('            "/start":     self.cmd_start,',
                       '            "/start":     self.cmd_start,\n'
                       '            "/ghost":     self.cmd_start,')
        self.assertEqual(ocs._main(["--root", str(self.root)]), 1)
        self.bot.write_text("def broken(:\n", encoding="utf-8")
        self.assertEqual(ocs._main(["--root", str(self.root)]), 2)


# ───────────── 3. перепись мерит ТЕКСТ дерева, а не подстроку ────────────────


class TestNotASubstring(_Tree):
    """ADR-333: ни одна ветка не проходит подстрокой."""

    def test_a_declaration_inside_a_string_is_not_counted(self):
        """Имя набора, упомянутое в ДОКСТРИНГЕ, объявлением не является."""
        self.patch_bot(
            "    def _dispatch(",
            '    _DOC = """_COMMANDS = ("/start", "/menu")"""\n\n    def _dispatch(')
        m = self.measure()
        self.assertEqual(m["duplicate_declarations"], [], ocs.findings(m))
        self.assertNotIn("_COMMANDS", m["declared"])

    def test_a_prefix_tuple_is_not_a_command_declaration(self):
        """`_LEGACY_CB_PREFIXES` несёт `"/"` как ПРЕФИКС — это не команда."""
        m = self.measure()
        self.assertNotIn("_LEGACY_CB_PREFIXES", m["declared"])
        self.assertNotIn("/", m["reachable"])

    def test_renaming_the_handler_variable_does_not_blind_the_census(self):
        """Снимается ФОРМА, а не имя переменной."""
        before = self.measure()["dispatched"]
        self.patch_bot("        handlers: Dict[str, Any] = {",
                       "        routes: Dict[str, Any] = {")
        self.patch_bot("        handler = handlers.get(cmd)", "        handler = routes.get(cmd)")
        self.assertEqual(self.measure()["dispatched"], before)


# ───── 3b. дыры, найденные МУТАЦИЯМИ: четыре выживших мутанта были настоящими ─────


class TestHolesFoundByMutation(_Tree):
    """Каждый тест здесь убивает КОНКРЕТНОГО выжившего мутанта цикла #856.

    Все четыре звена молчали не потому, что проверка верна, а потому, что
    сегодняшнее население до них не доходит: кнопки все до одной лежат в карте,
    в `_dispatch` один словарь, в методах нет кортежей команд, а объявление
    причин — словарь-литерал. «Не красит на живом дереве» и «проверено» —
    разные утверждения, и мутация ровно эту разницу и назвала.
    """

    def test_a_button_outside_the_dispatcher_map_does_not_make_it_reachable(self):
        """Мутант `dispatched∩buttoned→buttoned`.

        Кнопка, чьей команды в карте НЕТ, ведёт в `cmd_help` (ветка «неизвестно»),
        то есть своей двери у неё нет. Считать её достижимой значило бы
        записать владельцу орган, которого не существует.
        """
        self.patch_bot('{"text": "📊 Статус системы", "callback_data": "/status"},',
                       '{"text": "📊 Статус системы", "callback_data": "/status"},\n'
                       '                {"text": "сирота", "callback_data": "/orphanbtn"},')
        m = self.measure()
        self.assertIn("/orphanbtn", m["buttoned"])
        self.assertNotIn("/orphanbtn", m["dispatched"])
        self.assertNotIn("/orphanbtn", m["reachable"])

    def test_a_dict_whose_values_are_not_methods_is_not_the_dispatcher_map(self):
        """Мутант `_dispatched: accept any value node`.

        Карта диспетчера — это «команда → `self.<метод>`». Словарь с теми же
        ключами и НЕ методами (подписи, тексты, что угодно) картой не является,
        и принять его значило бы выдумать владельцу двери из подписей.
        """
        self.patch_bot('        handler = handlers.get(cmd)',
                       '        _labels = {"/fakeone": "подпись", "/faketwo": "подпись"}\n'
                       '        handler = handlers.get(cmd)')
        m = self.measure()
        self.assertNotIn("/fakeone", m["dispatched"])
        self.assertNotIn("/faketwo", m["dispatched"])

    def test_a_local_tuple_inside_a_method_is_not_a_class_declaration(self):
        """Мутант `_declarations: walk instead of body`.

        Объявление класса живёт в теле КЛАССА. Кортеж внутри метода — локальная
        переменная; обвинить её в копии значило бы требовать снять рабочий код.
        """
        self.patch_bot('        handler = handlers.get(cmd)',
                       '        _local = ("/start", "/menu")\n'
                       '        handler = handlers.get(cmd)')
        m = self.measure()
        self.assertNotIn("_local", m["declared"])
        self.assertEqual(m["duplicate_declarations"], [], ocs.findings(m))

    def test_reasons_that_are_not_a_literal_dict_count_as_none_named(self):
        """Мутант `_reasons: accept empty dict silently`.

        Объявление причин, собранное вызовом вместо литерала, разобрать нельзя —
        и тогда НИ ОДНА причина не названа, то есть всё расхождение красно
        (fail-CLOSED). Тихо считать, что причины есть, — ровно fail-OPEN.
        """
        self.patch_bot("    _UNADVERTISED_BY_DESIGN = {",
                       "    _UNADVERTISED_BY_DESIGN = dict({")
        self.patch_bot('        "/why": "кнопка «❓ Почему ❌?» на панели, не команда меню",\n    }',
                       '        "/why": "кнопка «❓ Почему ❌?» на панели, не команда меню",\n    })')
        m = self.measure()
        self.assertEqual(m["reasons"], {})
        self.assertEqual(sorted(m["unexplained_divergence"]),
                         sorted(m["reachable_not_advertised"]))
        self.assertTrue(ocs.findings(m))


# ──────── 4. прибор органов владельца читает КАРТУ, а не копию набора ────────


class TestOwnerOrgansInstrumentReadsTheMap(_Tree):
    def test_a_resurrected_copy_does_not_change_the_enumeration(self):
        """Копия `_COMMANDS` вернулась — перечень прибора не дрогнул.

        Это и есть доказательство, что прибор больше её не читает: до 13.10
        перечень снимался именно с неё.
        """
        from spa_core.monitoring import cio_kill_switch_controls as organs
        before = organs._owner_doors(str(self.root))["commands"]
        self.patch_bot(
            "    def _dispatch(",
            '    _COMMANDS = ("/only", "/this", "/copy")\n\n    def _dispatch(')
        self.assertEqual(organs._owner_doors(str(self.root))["commands"], before)

    def test_a_new_map_entry_does_change_the_enumeration(self):
        """ОБРАТНАЯ сторона: карта — ЖИВОЙ источник, перечень за ней следует."""
        from spa_core.monitoring import cio_kill_switch_controls as organs
        before = organs._owner_doors(str(self.root))["commands"]
        self.patch_bot('            "/start":     self.cmd_start,',
                       '            "/start":     self.cmd_start,\n'
                       '            "/ghost":     self.cmd_start,')
        after = organs._owner_doors(str(self.root))["commands"]
        self.assertEqual(sorted(set(after) - set(before)), ["/ghost"])

    def test_an_unparsable_channel_is_unchecked_for_the_instrument_too(self):
        """Третий исход у соседа сохранён правкой, а не потерян."""
        from spa_core.monitoring import cio_kill_switch_controls as organs
        self.bot.write_text("def broken(:\n", encoding="utf-8")
        channel = organs._owner_doors(str(self.root))
        self.assertIsNotNone(channel["unchecked"])
        self.assertEqual(channel["commands"], [])


# ──── 4b. снятие мёртвой записи `/help` ПОВЕДЕНИЯ не меняет — это тоже замер ────


class TestRemovingTheDeadDoorChangedNoBehaviour(unittest.TestCase):
    """`/help` снят из карты. Утверждение «поведение то же» обязано быть ИЗМЕРЕНО.

    `_dispatch` отвечает на неизвестную команду вызовом `cmd_help` — значит
    запись `/help → cmd_help` была избыточна, и её снятие ничего не меняет. На
    слово это брать нельзя: старые кнопки в чате владельца могут нести
    `callback_data == "/help"` до сих пор.
    """

    def _bot(self):
        from spa_core.telegram import bot as bot_mod
        return bot_mod.TelegramBot(token="probe-token", chat_id="probe-chat")

    def test_slash_help_still_reaches_cmd_help(self):
        from spa_core.telegram import bot as bot_mod
        bot = self._bot()
        with unittest.mock.patch.object(bot_mod.TelegramBot, "cmd_help",
                                        autospec=True) as spy:
            bot._dispatch("/help", "probe-chat")
        self.assertEqual(spy.call_count, 1)

    def test_an_unknown_command_reaches_the_same_handler(self):
        """ОБРАТНАЯ сторона: та же дверь отвечает и на то, чего в карте нет."""
        from spa_core.telegram import bot as bot_mod
        bot = self._bot()
        with unittest.mock.patch.object(bot_mod.TelegramBot, "cmd_help",
                                        autospec=True) as spy:
            bot._dispatch("/this-command-never-existed", "probe-chat")
        self.assertEqual(spy.call_count, 1)

    def test_help_is_no_longer_a_declared_door(self):
        """И при этом перепись больше НЕ считает `/help` органом владельца."""
        m = ocs.measure(LIVE_ROOT)
        self.assertNotIn("/help", m["dispatched"])
        self.assertNotIn("/help", m["reachable"])


# ───────────────────────── 5. проводка пробы приёмки ─────────────────────────


class TestProbeWiring(unittest.TestCase):
    """Проба переводит вердикт переписи в вердикт приёмки, не теряя исходов."""

    PROBE = "owner_command_surfaces_declared_once"

    def test_the_probe_is_registered(self):
        self.assertIn(self.PROBE, ca.PROBES)

    def test_the_probe_is_satisfied_on_the_live_tree(self):
        verdict, why = ca.PROBES[self.PROBE](None)
        self.assertEqual(verdict, ca.SATISFIED, why)

    def test_a_finding_makes_the_probe_not_satisfied(self):
        """ЗВЕНО: находка переписи обязана доходить до вердикта приёмки."""
        broken = dict(ocs.measure(LIVE_ROOT))
        broken["duplicate_declarations"] = [
            {"name": "_COMMANDS", "copy_of": "dispatched", "size": 13}]
        with unittest.mock.patch.object(ocs, "measure", return_value=broken):
            verdict, why = ca.PROBES[self.PROBE](None)
        self.assertEqual(verdict, ca.NOT_SATISFIED)
        self.assertIn("КОПИЯ ОБЪЯВЛЕНИЯ", why)

    def test_an_unmeasured_census_is_unmeasured_and_never_not_satisfied(self):
        """ЗВЕНО: третий исход не имеет права стать `not_satisfied` (инв. #17)."""
        with unittest.mock.patch.object(
                ocs, "measure",
                return_value={**ocs.measure(LIVE_ROOT),
                              "unmeasured": "канал владельца не разобран: причина"}):
            verdict, why = ca.PROBES[self.PROBE](None)
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("причина", why)

    def test_the_probe_does_not_pass_by_substring(self):
        """ADR-333: вердикт считается по ЧИСЛАМ множеств, не по тексту кода."""
        source = pathlib.Path(ca.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_probe_owner_command_surfaces_declared_once")
        body = ast.get_source_segment(source, fn) or ""
        # докстринг отрезан: он называет предмет словами, и это не ветка
        body = body.replace(ast.get_docstring(fn) or "", "")
        for forbidden in (" in source", "startswith(", "find(", "re.search"):
            self.assertNotIn(forbidden, body, f"ветка по тексту: {forbidden}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
