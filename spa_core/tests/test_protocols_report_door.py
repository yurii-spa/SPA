"""Дверь отчёта `/protocols`: доезжает ли он до владельца ЦЕЛИКОМ (ADR-711).

Что здесь измеряется
------------------------------------------------------------------------------
Цикл #854 поднял население отчёта владельцу с 2 записей до 34 и проверил это
у ПРОИЗВОДИТЕЛЯ (ADR-710). Вопрос «кто это читает» был задан после правки, и
ответ оказался: НИКТО. Замер 13.10 на `origin/main` e40e9cc1f:

* ни один plist `launchd/` не зовёт `telegram_protocols_reporter`;
* у бота 12 опубликованных команд, `/protocols` среди них нет, а типизированная
  команда вне `router.COMMAND_TO_PATH` открывает ДОМАШНЮЮ панель — то есть
  владелец не получает ни отчёта, ни отказа: молчание неотличимо от ответа;
* единственная живая дверь (`_post_message` → дайджест) помечена RETIRED и
  обрезает текст до 500 символов; в живой очереди дайджеста 71 запись и
  `protocols_report` среди них НОЛЬ — дверью не пользовались ни разу.

Блок `*System*` стоит в сообщении ПОСЛЕДНИМ, и в нём `Capital`/`Deployed`/
`Cash`/`Total adapters` плюс строка «НЕ РАЗОБРАНО», которой ADR-709 сделал
молчание отличимым (инв. #17). Поэтому любое усечение С ХВОСТА убивает сводку
первой — и именно это делала дверь-дайджест.

Положительные контроли — настоящие аварии
------------------------------------------------------------------------------
Каждый отрицательный тест ниже воспроизводит аварию, а не придуманный случай:

1. **одно сообщение вместо кусков** — авария дайджеста (предел 500) и ровно то,
   что сделал бы экран Router'а (предел 4096, усечение с хвоста);
2. **деление кодовыми точками при усечении единицами UTF-16** — дефект, который
   проба нашла в ПЕРВОЙ редакции этой же двери: в каждой строке отчёта эмодзи,
   «📊» стоит две единицы UTF-16 при одной кодовой точке;
3. **перевод разметки ПОСЛЕ деления** — дефект ВТОРОЙ редакции: экранирование
   только удлиняет текст, и кусок, нарезанный до перевода, перешагивает предел
   после него.

Время — ВХОД, а не окружение (`.claude/rules/deployment.md`): возраст артефакта
выражен относительными отметками (`_freshness.ts`), а часы пробы передаются
аргументом `now`. Литеральных дат в файле нет ни одной, поэтому и пометки
`FROZEN-DATE-OK` ему не требуется.

Сети здесь нет по построению: `send_message` подменяется на экземпляре, общий
заслон (`guard_outbound`), история отправок и состояние бота не трогаются.
"""
from __future__ import annotations

import json
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core import telegram_protocols_reporter as reporter
from spa_core.monitoring import card_acceptance as ca
from spa_core.telegram import bot as bot_mod
from spa_core.tests._freshness import now_utc, ts

_EMOJI = "\U0001F4CA"  # 📊 — одна кодовая точка, ДВЕ единицы UTF-16


def _records(count: int, *, age_h: float) -> dict:
    """Записи раздела `adapters` в современной форме (словарь «ключ → запись»)."""
    out: dict = {}
    for i in range(count):
        out[f"proto_{i:03d}"] = {
            "display_name": f"Protocol {i:03d} {_EMOJI}",
            "tier": "1",
            "apy": 4.0 + i / 100.0,
            "live_apy": 4.0 + i / 100.0,
            "live_apy_as_of": ts(hours_ago=age_h),
            "live_apy_fresh": True,
            "tvl_usd": 10_000_000.0 + i,
            "tvl_source": "live",
        }
    return out


def _doc(count: int, *, age_h: float = 1.0) -> dict:
    return {
        "generated_at": ts(hours_ago=age_h),
        "adapters": _records(count, age_h=age_h),
        "positions_data": {
            "capital_usd": 100_000,
            "deployed_usd": 95_000,
            "cash_usd": 5_000,
            "positions": {"proto_000": 95_000.0},
        },
    }


def _door(captured: list[str]):
    """Инертный бот, у которого отправка ПЕРЕХВАЧЕНА ровно там, где режет фитер."""
    bot = bot_mod.TelegramBot(token="probe-token", chat_id="probe-chat")

    def _capture(text, chat_id=None, parse_mode="HTML", **_kw):
        captured.append(bot_mod._fit_telegram(text or "", parse_mode))
        return {"ok": True}

    bot.send_message = _capture  # type: ignore[method-assign]
    return bot


def _lines(text: str) -> int:
    return len(text.split("\n"))


def _write(data_dir: Path, doc: dict) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "adapter_status.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ─────────────────────────── 1. признание команды ──────────────────────────


class TestCommandRecognition(unittest.TestCase):
    def test_plain_command_is_recognised(self):
        self.assertTrue(bot_mod.TelegramBot._is_protocols_command("/protocols"))

    def test_command_with_bot_suffix_is_recognised(self):
        self.assertTrue(bot_mod.TelegramBot._is_protocols_command("/protocols@spa_bot"))

    def test_command_is_case_insensitive(self):
        self.assertTrue(bot_mod.TelegramBot._is_protocols_command("/PROTOCOLS"))

    def test_trailing_words_do_not_hide_the_command(self):
        self.assertTrue(bot_mod.TelegramBot._is_protocols_command("/protocols  сейчас"))

    def test_a_longer_command_is_NOT_this_one(self):
        """Обратная сторона: `/protocolsx` — другая команда, дверь её не берёт."""
        self.assertFalse(bot_mod.TelegramBot._is_protocols_command("/protocolsx"))

    def test_bare_word_is_not_a_command(self):
        self.assertFalse(bot_mod.TelegramBot._is_protocols_command("protocols"))

    def test_empty_text_is_not_a_command(self):
        self.assertFalse(bot_mod.TelegramBot._is_protocols_command("   "))


# ─────────────────────────── 2. гейт владельца ─────────────────────────────


class TestOwnerGate(unittest.TestCase):
    def test_owner_gets_the_report(self):
        captured: list[str] = []
        bot = _door(captured)
        with unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_protocols", autospec=True
        ) as spy:
            self.assertTrue(bot._handle_protocols_command("/protocols", "probe-chat"))
        self.assertEqual(spy.call_count, 1)

    def test_NON_owner_is_refused_and_the_door_is_not_opened(self):
        """Обратная сторона гейта: перехват не имеет права обойти fail-CLOSED."""
        captured: list[str] = []
        bot = _door(captured)
        with unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_protocols", autospec=True
        ) as spy:
            self.assertFalse(bot._handle_protocols_command("/protocols", "1234567"))
        self.assertEqual(spy.call_count, 0)

    def test_a_BROKEN_gate_keeps_the_door_shut(self):
        """Сломанный гейт отвечает исключением — дверь обязана остаться закрытой."""
        captured: list[str] = []
        bot = _door(captured)

        def _boom():
            raise RuntimeError("router unavailable")

        bot._get_router = _boom  # type: ignore[method-assign]
        with unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_protocols", autospec=True
        ) as spy:
            self.assertFalse(bot._handle_protocols_command("/protocols", "probe-chat"))
        self.assertEqual(spy.call_count, 0)


# ─────────────────────────── 3. проводка двери ─────────────────────────────


class TestWiring(unittest.TestCase):
    def test_command_is_on_the_surface_the_owner_organs_instrument_reads(self):
        """Перечень прибора органов владельца несёт `/protocols`.

        НАМЕРЕННАЯ правка 13.10 (ADR-712, инв. #16 — усиление, не ослабление).
        Было: `assertIn("/protocols", TelegramBot._COMMANDS)` — утверждение о
        КОПИИ набора, которую в боте не читал никто. Копия снята, и проверять
        надо то, что прибор читает СЕЙЧАС: перечень, снятый с карты
        `_dispatch` его собственным разбором дерева. Прежняя форма зеленела бы
        и при карте, из которой команда выпала, — а эта нет.
        """
        from spa_core.monitoring import cio_kill_switch_controls as organs
        channel = organs._owner_doors(organs.REPO_ROOT)
        self.assertIsNone(channel["unchecked"], channel["unchecked"])
        self.assertIn("/protocols", channel["commands"])

    def test_command_is_offered_in_the_telegram_menu(self):
        captured: list[dict] = []
        bot = _door([])
        bot._api_call = lambda method, params=None, timeout=None: (  # type: ignore[method-assign]
            captured.append(params or {}) or {"ok": True}
        )
        self.assertTrue(bot.register_commands())
        names = [c["command"] for c in captured[0]["commands"]]
        self.assertIn("protocols", names)

    def test_legacy_dispatch_reaches_the_same_door(self):
        bot = _door([])
        with unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_protocols", autospec=True
        ) as spy:
            bot._dispatch("/protocols", "probe-chat")
        self.assertEqual(spy.call_count, 1)

    def test_an_unknown_command_still_falls_back_to_help(self):
        """Обратная сторона: диспетчер не начал звать отчёт на всё подряд."""
        bot = _door([])
        with unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_protocols", autospec=True
        ) as spy, unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_help", autospec=True
        ) as help_spy:
            bot._dispatch("/protocolsx", "probe-chat")
        self.assertEqual(spy.call_count, 0)
        self.assertEqual(help_spy.call_count, 1)

    def test_typed_message_reaches_the_door_and_NOT_the_router(self):
        bot = _door([])
        with unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_protocols", autospec=True
        ) as spy:
            bot.handle_update(
                {"message": {"text": "/protocols", "chat": {"id": "probe-chat"}}}
            )
        self.assertEqual(spy.call_count, 1)

    def test_another_typed_command_still_goes_to_the_router(self):
        """Обратная сторона перехвата: он не съел остальные команды."""
        bot = _door([])
        with unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_protocols", autospec=True
        ) as spy:
            bot.handle_update(
                {"message": {"text": "/portfolio", "chat": {"id": "probe-chat"}}}
            )
        self.assertEqual(spy.call_count, 0)


class TestInterceptDeclaration(unittest.TestCase):
    """Объявление перехватов не ЛЖЁТ — иначе сторож меню судил бы о записке.

    `_INTERCEPTED_COMMANDS` — единственное объявление набора команд, на которые
    отвечает перехват в `handle_update`. Сторож меню
    (`test_spa_bot_safety_boundaries`) читает его вместо прежнего литерала; значит,
    кто-то обязан мерить САМО объявление, иначе достаточно дописать туда имя, чтобы
    сторож замолчал.
    """

    def test_every_declared_intercept_really_intercepts(self):
        for cmd in bot_mod.TelegramBot._INTERCEPTED_COMMANDS:
            with self.subTest(cmd=cmd):
                bot = _door([])
                reached: list[str] = []
                bot._get_router = lambda: _FakeRouter(reached)  # type: ignore[method-assign]
                with unittest.mock.patch.object(
                    bot_mod.TelegramBot, "cmd_protocols", autospec=True
                ), unittest.mock.patch.object(
                    bot_mod.TelegramBot, "_classify_route", autospec=True
                ), unittest.mock.patch(
                    "spa_core.telegram.status_summary.build_status_summary",
                    lambda *a, **k: "сводка",
                ):
                    bot.handle_update(
                        {"message": {"text": cmd, "chat": {"id": "probe-chat"}}})
                self.assertEqual(reached, [], f"{cmd} доехала до Router'а")

    def test_a_command_that_is_NOT_declared_reaches_the_router(self):
        """Обратная сторона: объявление не накрывает всё подряд."""
        bot = _door([])
        reached: list[str] = []
        bot._get_router = lambda: _FakeRouter(reached)  # type: ignore[method-assign]
        bot.handle_update(
            {"message": {"text": "/portfolio", "chat": {"id": "probe-chat"}}})
        self.assertEqual(reached, ["/portfolio"])


class _FakeRouter:
    """Router, который только ЗАПИСЫВАЕТ, что до него доехало. Сети нет."""

    def __init__(self, reached: list[str]):
        self._reached = reached

    def is_owner(self, chat_id):
        return True

    def handle_command(self, text, chat_id):
        self._reached.append(text)
        return None


# ─────────────────────────── 4. перевод разметки ───────────────────────────


class TestMarkupTranslation(unittest.TestCase):
    def test_bold_becomes_html_bold(self):
        self.assertEqual(bot_mod._md_to_html("*x*"), "<b>x</b>")

    def test_backticks_become_code(self):
        self.assertEqual(bot_mod._md_to_html("`x`"), "<code>x</code>")

    def test_html_metacharacters_are_escaped_BEFORE_markup(self):
        """Авария, которой здесь не будет: `<` в имени = 400 от Bot API = тишина."""
        out = bot_mod._md_to_html("*A & <b>*")
        self.assertEqual(out, "<b>A &amp; &lt;b&gt;</b>")

    def test_an_UNBALANCED_asterisk_stays_a_plain_character(self):
        """Обратная сторона: непарная звёздочка не имеет права уронить разбор."""
        self.assertEqual(bot_mod._md_to_html("a * b"), "a * b")

    def test_TWO_bold_spans_on_one_line_stay_two(self):
        """Жадный шаблон склеил бы их в один — найдено мутацией этой батареи."""
        self.assertEqual(
            bot_mod._md_to_html("*a* и *b*"), "<b>a</b> и <b>b</b>")

    def test_line_count_is_preserved(self):
        src = "*a*\n\n`b`\nc & d"
        self.assertEqual(_lines(bot_mod._md_to_html(src)), _lines(src))


# ─────────────────────────── 5. исход у двери ──────────────────────────────


class TestDeliveryOutcome(unittest.TestCase):
    def test_small_report_arrives_whole_in_one_piece(self):
        captured: list[str] = []
        bot = _door(captured)
        doc = _doc(4)
        self.assertEqual(bot.cmd_protocols("probe-chat", data=doc), 1)  # измеренный 1
        want = _lines(reporter.format_protocols_message(doc))
        self.assertEqual(sum(_lines(p) for p in captured), want)
        self.assertEqual([p for p in captured if p.endswith("… (сокращено)")], [])

    def test_large_report_arrives_whole_in_several_pieces(self):
        captured: list[str] = []
        bot = _door(captured)
        doc = _doc(120)
        produced = reporter.format_protocols_message(doc)
        self.assertGreater(len(produced), bot_mod.TG_TEXT_LIMIT)
        sent = bot.cmd_protocols("probe-chat", data=doc)
        self.assertGreater(sent, 1)
        self.assertEqual(sum(_lines(p) for p in captured), _lines(produced))
        self.assertEqual([p for p in captured if p.endswith("… (сокращено)")], [])

    def test_the_door_really_TRANSLATES_the_markup(self):
        """Найдено мутацией: снятие перевода батарею не красило — она считала
        строки, а HTML у двери никто не проверял. Markdown, отданный как HTML,
        владелец читает со звёздочками, а `<` в имени протокола роняет разбор."""
        captured: list[str] = []
        bot = _door(captured)
        bot.cmd_protocols("probe-chat", data=_doc(4))
        self.assertIn("<b>", captured[0])
        self.assertNotIn("*", captured[0])

    def test_the_summary_block_survives_a_large_report(self):
        """Предмет карточки дословно: сводка обязана доживать до читателя."""
        captured: list[str] = []
        bot = _door(captured)
        bot.cmd_protocols("probe-chat", data=_doc(120))
        self.assertIn("Total adapters: 120", captured[-1])
        self.assertIn("Capital:", captured[-1])

    def test_the_unparsed_counter_survives_a_large_report(self):
        """Третий исход (инв. #17) живёт в той же сводке и тоже обязан доживать."""
        captured: list[str] = []
        bot = _door(captured)
        doc = _doc(120)
        doc["adapters"]["broken_entry"] = "это не запись"
        bot.cmd_protocols("probe-chat", data=doc)
        self.assertIn("НЕ РАЗОБРАНО", captured[-1])

    def test_a_report_that_cannot_be_built_is_SAID_not_swallowed(self):
        captured: list[str] = []
        bot = _door(captured)

        def _boom(_data, **_kw):
            raise ValueError("artifact unreadable")

        with unittest.mock.patch.object(reporter, "protocols_report_parts", _boom):
            # Третий исход: НЕ ноль. Ноль здесь был бы «отчёт пуст», а отчёта нет
            # вовсе (инв. #17) — поймано храповиком отсутствующего наблюдения.
            self.assertIsNone(bot.cmd_protocols("probe-chat", data=_doc(2)))
        self.assertEqual(len(captured), 1)
        self.assertIn("ValueError", captured[0])

    def test_ONE_message_instead_of_pieces_loses_the_summary(self):
        """Положительный контроль — авария дайджеста (и экрана Router'а)."""
        captured: list[str] = []
        bot = _door(captured)
        doc = _doc(120)
        whole = bot_mod._md_to_html(reporter.format_protocols_message(doc))
        bot.send_message(whole, "probe-chat")
        self.assertTrue(captured[0].endswith("… (сокращено)"))
        self.assertNotIn("Total adapters: 120", captured[0])

    def test_splitting_by_CODE_POINTS_while_cutting_by_UTF16_loses_lines(self):
        """Положительный контроль — дефект первой редакции этой двери."""
        captured: list[str] = []
        bot = _door(captured)
        doc = _doc(120)
        parts = reporter.protocols_report_parts(
            doc, max_len=bot_mod.TG_TEXT_LIMIT, render=bot_mod._md_to_html
        )  # measure=len — кодовые точки
        for part in parts:
            bot.send_message(part, "probe-chat")
        self.assertTrue(any(p.endswith("… (сокращено)") for p in captured))

    def test_rendering_AFTER_the_split_loses_lines(self):
        """Положительный контроль — дефект второй редакции этой двери."""
        captured: list[str] = []
        bot = _door(captured)
        doc = _doc(120)
        parts = reporter.protocols_report_parts(
            doc, max_len=bot_mod.TG_TEXT_LIMIT, measure=bot_mod._utf16_len
        )
        for part in parts:
            bot.send_message(bot_mod._md_to_html(part), "probe-chat")
        self.assertTrue(any(p.endswith("… (сокращено)") for p in captured))


# ─────────────────────────── 6. правило деления ────────────────────────────


class TestSplitRule(unittest.TestCase):
    def test_measure_is_an_input_and_defaults_to_code_points(self):
        text = "a" * 10
        self.assertEqual(reporter.split_message(text, 10), [text])
        self.assertEqual(len(reporter.split_message(text, 4)), 3)

    def test_an_injected_measure_changes_the_split(self):
        # 8 строк: 15 кодовых точек, 23 единицы UTF-16 — предел 20 лежит МЕЖДУ,
        # поэтому мера решает вердикт, а не длина текста.
        text = "\n".join([_EMOJI] * 8)
        self.assertEqual(reporter.split_message(text, 20, measure=len), [text])
        self.assertGreater(
            len(reporter.split_message(text, 20, measure=bot_mod._utf16_len)), 1
        )

    def test_no_line_is_lost_by_the_split(self):
        doc = _doc(120)
        produced = reporter.format_protocols_message(doc)
        parts = reporter.split_message(produced, 1000)
        self.assertGreater(len(parts), 1)
        self.assertEqual(sum(_lines(p) for p in parts), _lines(produced))

    def test_the_retired_push_shares_the_SAME_split_rule(self):
        """Иначе проза «одно правило на обе двери» была бы неправдой — а проза,
        пережившая правку, врёт тише, чем молчание."""
        seen: list[dict] = []

        def _spy(data, **_kw):
            seen.append(data)
            return ["часть"]

        with unittest.mock.patch.object(reporter, "protocols_report_parts", _spy), \
             unittest.mock.patch.object(reporter, "_resolve_credentials",
                                        lambda *a, **k: ("t", "c")), \
             unittest.mock.patch.object(reporter, "_post_message",
                                        lambda *a, **k: {"ok": False}):
            reporter.send_protocols_report(data=_doc(2))
        self.assertEqual(len(seen), 1)

    def test_render_runs_before_the_split(self):
        doc = _doc(2)
        parts = reporter.protocols_report_parts(doc, render=lambda s: "RENDERED\n" + s)
        self.assertTrue(parts[0].startswith("RENDERED\n"))


# ─────────────────────────── 7. контроль ПРОБЫ ─────────────────────────────


class TestProbeBothWays(unittest.TestCase):
    """У каждого звена — обратная сторона с НАЗВАННЫМ звеном (`acceptance.md` §3)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        _write(self.data_dir, _doc(12))
        self.addCleanup(self._tmp.cleanup)

    def _run(self):
        return ca._probe_owner_protocols_report_reaches_the_owner(
            None, now=now_utc(), data_dir=str(self.data_dir)
        )

    # --- целый контур -------------------------------------------------------

    def test_whole_circuit_is_satisfied(self):
        status, detail = self._run()
        self.assertEqual(status, ca.SATISFIED, detail)

    def test_the_verdict_names_all_three_measurements(self):
        """Снятие любого из трёх замеров — находка, а не тихое упрощение."""
        _status, detail = self._run()
        for half in ("живой вход", "раздутый вход", "по умолчанию вход"):
            self.assertIn(half, detail)

    # --- звено: двери нет вовсе --------------------------------------------

    def test_link_NO_DOOR_turns_the_probe_red(self):
        door = bot_mod.TelegramBot.cmd_protocols
        del bot_mod.TelegramBot.cmd_protocols
        try:
            status, detail = self._run()
        finally:
            bot_mod.TelegramBot.cmd_protocols = door
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn("cmd_protocols", detail)

    # --- звено: дверь отдаёт ОДНО сообщение --------------------------------

    def test_link_ONE_MESSAGE_door_turns_the_probe_red(self):
        def _one(self_bot, chat_id, *, data=None):
            doc = data if data is not None else {}
            self_bot.send_message(
                bot_mod._md_to_html(reporter.format_protocols_message(doc)), chat_id)
            return 1

        with unittest.mock.patch.object(bot_mod.TelegramBot, "cmd_protocols", _one):
            status, detail = self._run()
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn("усечено", detail)

    # --- звено: деление НЕ той мерой ---------------------------------------

    def test_link_WRONG_MEASURE_turns_the_probe_red(self):
        def _codepoints(self_bot, chat_id, *, data=None):
            doc = data if data is not None else {}
            for part in reporter.protocols_report_parts(
                doc, max_len=bot_mod.TG_TEXT_LIMIT, render=bot_mod._md_to_html
            ):
                self_bot.send_message(part, chat_id)
            return 1

        with unittest.mock.patch.object(bot_mod.TelegramBot, "cmd_protocols", _codepoints):
            status, detail = self._run()
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn("усечено", detail)

    # --- звено: перевод ПОСЛЕ деления --------------------------------------

    def test_link_RENDER_AFTER_SPLIT_turns_the_probe_red(self):
        def _late_render(self_bot, chat_id, *, data=None):
            doc = data if data is not None else {}
            for part in reporter.protocols_report_parts(
                doc, max_len=bot_mod.TG_TEXT_LIMIT, measure=bot_mod._utf16_len
            ):
                self_bot.send_message(bot_mod._md_to_html(part), chat_id)
            return 1

        with unittest.mock.patch.object(bot_mod.TelegramBot, "cmd_protocols", _late_render):
            status, detail = self._run()
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn("усечено", detail)

    # --- звено: дверь молчит ------------------------------------------------

    def test_link_SILENT_door_turns_the_probe_red(self):
        with unittest.mock.patch.object(
            bot_mod.TelegramBot, "cmd_protocols",
            lambda self_bot, chat_id, *, data=None: 0,
        ):
            status, detail = self._run()
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn("НИ ОДНОГО куска", detail)

    # --- звено: дверь упала -------------------------------------------------

    def test_link_CRASHING_door_is_UNMEASURED_not_red(self):
        def _boom(self_bot, chat_id, *, data=None):
            raise RuntimeError("door exploded")

        with unittest.mock.patch.object(bot_mod.TelegramBot, "cmd_protocols", _boom):
            status, detail = self._run()
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("door exploded", detail)

    # --- подстрокой не проходит (ADR-333) ----------------------------------

    def test_a_door_that_only_PRINTS_the_right_words_stays_red(self):
        def _words(self_bot, chat_id, *, data=None):
            self_bot.send_message(
                "*System*\nCapital: $100,000 | Total adapters: 12\nНЕ РАЗОБРАНО: 0",
                chat_id)
            return 1

        with unittest.mock.patch.object(bot_mod.TelegramBot, "cmd_protocols", _words):
            status, detail = self._run()
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn("потеряно строк", detail)

    def test_the_probe_is_indifferent_to_MARKUP(self):
        """Вердикт — числа, не текст: дверь без перевода разметки тоже зелена."""
        def _plain(self_bot, chat_id, *, data=None):
            # Дверь ВЕРНАЯ во всём, кроме разметки: источник по умолчанию тот же,
            # что у настоящей, иначе красный говорил бы о подмене источника, а не
            # о разметке — это и есть то смешение, которое проба уже один раз
            # поймала у себя самой.
            doc = (data if data is not None
                   else reporter.load_adapter_data(bot_mod.DATA_DIR))
            for part in reporter.protocols_report_parts(
                doc, max_len=bot_mod.TG_TEXT_LIMIT, measure=bot_mod._utf16_len
            ):
                self_bot.send_message(part, chat_id)
            return 1

        with unittest.mock.patch.object(bot_mod.TelegramBot, "cmd_protocols", _plain):
            status, detail = self._run()
        self.assertEqual(status, ca.SATISFIED, detail)

    # --- три исхода различимы (инв. #17) -----------------------------------

    def test_a_missing_artifact_is_UNMEASURED(self):
        (self.data_dir / "adapter_status.json").unlink()
        status, detail = self._run()
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("нет в этом дереве", detail)

    def test_an_unparsable_artifact_is_UNMEASURED(self):
        (self.data_dir / "adapter_status.json").write_text("{", encoding="utf-8")
        status, detail = self._run()
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("не разобран", detail)

    def test_a_STALE_artifact_is_UNMEASURED_never_red(self):
        _write(self.data_dir, _doc(12, age_h=ca.ADAPTER_STATUS_MAX_AGE_H + 2))
        status, detail = self._run()
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("протух", detail)

    def test_an_artifact_without_a_stamp_is_UNMEASURED(self):
        doc = _doc(12)
        doc.pop("generated_at")
        _write(self.data_dir, doc)
        status, detail = self._run()
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("возраст не измерен", detail)

    def test_an_UNGROWABLE_artifact_is_UNMEASURED_never_satisfied(self):
        """Предпосылка испытания не обеспечена ⇒ сказать вслух, а не судить."""
        doc = _doc(3)
        doc["adapters"] = list(doc["adapters"].values())  # раздел СПИСКОМ
        _write(self.data_dir, doc)
        status, detail = self._run()
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("испытание населением не поставлено", detail)

    # --- проба зарегистрирована и ничего не пишет --------------------------

    def test_the_probe_is_in_the_registry(self):
        self.assertIs(
            ca.PROBES["owner_protocols_report_reaches_the_owner"],
            ca._probe_owner_protocols_report_reaches_the_owner,
        )

    def test_the_probe_writes_nothing(self):
        before = sorted(p.name for p in self.data_dir.iterdir())
        stamp = (self.data_dir / "adapter_status.json").read_bytes()
        self._run()
        self.assertEqual(sorted(p.name for p in self.data_dir.iterdir()), before)
        self.assertEqual((self.data_dir / "adapter_status.json").read_bytes(), stamp)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
