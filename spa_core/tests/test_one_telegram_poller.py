"""Второго читателя очереди Telegram в дереве быть не может; дверь без владельца — тоже.

Авария, которую повторяет каждый тест ниже
------------------------------------------------------------------------------
13.08 (#185): рядом с живым ботом поднялся ВТОРОЙ процесс на том же токене. Два
`getUpdates` на одном токене — 409 Conflict, и нажатия владельца достаются то
одному, то другому. Часть теряется молча.

16.08 замерено, что тот же класс живёт в дереве в виде МОДУЛЯ, а не процесса:
`spa_core/alerts/bot_commands.py` был заменён `spa_core/telegram/bot.py` ещё
14.06 (обёртка снятого агента `com.spa.bot_commands` звала УЖЕ новый модуль,
`git show 9ff165ee6^:scripts/agent_bot_commands.sh`), но остался целиком: свой
цикл `getUpdates` (и короткий, и длинный опрос), своё смещение
`data/tg_update_offset.json`, свои отправки в чат и свой `__main__`. Ни одного
вызывающего в боевом коде — и ровно одна строка `python3 -m …` до второго
поллера.

Что здесь проверяется — и чего эти проверки НЕ проверяют
------------------------------------------------------------------------------
* читателей очереди ровно столько, сколько названо (и список может только
  уменьшаться);
* хранилищ смещения ровно столько же — своё смещение есть своя память о
  прочитанном;
* у каждой двери в чат владельца есть ВЛАДЕЛЕЦ: её кто-то импортирует или
  запускает. Дверь без владельца никто не открывает — но открыть может любой;
* списанный поллер не вернулся ни модулем, ни установщиком.

Ни один из них не отвечает на вопрос «сколько поллеров сейчас живо на хосте» —
это вопрос `launchctl`, и он тут не задаётся. Ничего не запускается: правило
долгожителя (`.claude/rules/deployment.md`) прямо запрещает проверять живой бот
запуском, а разбор здесь инертный (AST, без импорта разбираемых модулей).
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from spa_core.tests import _telegram_doors as doors
from spa_core.tests import _telegram_pollers as pollers

_REPO = Path(__file__).resolve().parents[2]

#: Кто ИМЕЕТ ПРАВО читать очередь обновлений — поимённо, с причиной.
#: База может только уменьшаться: новое имя здесь означает, что в проекте
#: появился ещё один претендент на тот же токен.
EXPECTED_POLLERS = {
    # Канонический долгоживущий бот владельца (KeepAlive, long-poll timeout=30).
    # Единственный, у кого чтение очереди — его работа.
    "spa_core/telegram/bot.py",
    # Ежедневный отчёт: `getUpdates?limit=1` БЕЗ смещения, только как запасной
    # способ узнать chat_id, если ключа нет в Keychain. Очередь не подтверждает
    # (ничего не удаляет), но токен трогает — поэтому назван, а не забыт.
    "scripts/checkpoint_7day.py",
    # ОТКРЫТЫЙ дефект, не одобрение: watcher выгребает очередь СО смещением,
    # то есть подтверждает апдейты и удаляет их для всех. Карточка
    # `own-55-vtoroi-chitatel-komand-v-telegram`; закреплён отдельным
    # тестом-KNOWN_GAP ниже, который обязан покраснеть, когда дефект закроют.
    "spa_core/monitoring/telegram_watcher.py",
}

#: Хранилище смещения = память о прочитанном. Их ровно столько же, сколько
#: читателей, ПОДТВЕРЖДАЮЩИХ очередь (checkpoint_7day смещения не хранит).
EXPECTED_OFFSET_STORES = {
    "spa_core/telegram/bot.py": {"tg_bot_v2_offset.json"},
    "spa_core/monitoring/telegram_watcher.py": {"telegram_last_update_id.json"},
}

#: Списанный поллер (цикл #258). Возврат ЛЮБОГО из этих путей — возврат класса.
RETIRED_POLLER = "spa_core/alerts/bot_commands.py"
RETIRED_INSTALLER = "scripts/install_bot_commands.sh"


class TestOnePoller(unittest.TestCase):
    """Читателей очереди — ровно столько, сколько названо."""

    def test_no_unnamed_reader_of_the_update_queue(self):
        found = set(pollers.poller_modules())
        extra = found - EXPECTED_POLLERS
        self.assertEqual(
            extra, set(),
            "новый читатель очереди Telegram на том же токене: "
            f"{sorted(extra)}. Два getUpdates = 409 Conflict = потерянные "
            "нажатия владельца (#185). Либо это канонический бот, либо этого "
            "модуля быть не должно.")

    def test_no_unnamed_offset_store(self):
        found = {rel: set(names) for rel, names in pollers.offset_stores().items()}
        self.assertEqual(
            found, EXPECTED_OFFSET_STORES,
            "изменился набор хранилищ смещения очереди. Своё смещение = своя "
            "память о прочитанном, то есть намерение читать очередь независимо "
            "от канонического бота.")

    def test_the_retired_poller_did_not_come_back(self):
        self.assertFalse(
            (_REPO / RETIRED_POLLER).exists(),
            f"{RETIRED_POLLER} вернулся в дерево: собственный getUpdates + "
            "собственный __main__ = второй поллер в одну строку.")
        self.assertFalse(
            (_REPO / RETIRED_INSTALLER).exists(),
            f"{RETIRED_INSTALLER} вернулся: установщик агента, которого нет ни "
            "в одном коммите, и чья удача стоила бы владельцу команд.")


class TestScanIsNotBlind(unittest.TestCase):
    """Положительные контроли САМОГО разбора: ослепнув, он вернул бы пустоту."""

    def test_the_scan_still_sees_the_canonical_poller(self):
        found = pollers.poller_modules()
        self.assertIn(
            "spa_core/telegram/bot.py", found,
            "разбор перестал видеть ГЛАВНЫЙ поллер проекта — значит пустой "
            "результат выше читался бы как «чисто»")
        self.assertGreater(found["spa_core/telegram/bot.py"], 0)

    def test_a_docstring_mention_is_not_a_reader(self):
        """Урок #227: упоминание — не вызов. Комментарий и докстринг не считаются."""
        src = (
            '"""getUpdates упоминается в шапке — это не чтение очереди."""\n'
            "# и в комментарии тоже: getUpdates\n"
            "X = 1\n"
        )
        tree = ast.parse(src)
        self.assertEqual(
            [s for s in pollers._code_string_constants(tree) if "getUpdates" in s],
            [], "докстринг/комментарий засчитан за вызов Bot API")

    def test_a_real_call_argument_is_a_reader(self):
        """Обратная сторона: настоящий параметр вызова обязан считаться."""
        tree = ast.parse('_api_call("getUpdates", {"timeout": 30})\n')
        self.assertEqual(
            [s for s in pollers._code_string_constants(tree) if "getUpdates" in s],
            ["getUpdates"])


class TestEveryDoorHasAnOwner(unittest.TestCase):
    """Дверь в чат владельца, которую никто не зовёт, — заряженное ружьё."""

    def test_no_ownerless_door(self):
        found = pollers.ownerless(sorted(doors.scan_repo()))
        self.assertEqual(
            found, {},
            "дверь в чат владельца без единого вызывающего и без запуска: "
            f"{sorted(found)}. Такой модуль выглядит рабочим, его правят «по "
            "аналогии», и он запускается одной строкой.")

    def test_the_ownership_scan_still_sees_a_real_owner(self):
        """Положительный контроль: ослепший разбор объявил бы сиротой ВСЕХ.

        Обёртка НАЗВАНА поимённо, а не проверяется «есть хоть какой-то launch».
        Так первая редакция и была написана — и мутация «засчитывать запуск
        только из `.py`» её НЕ покрасила: точечное имя модуля встречается и в
        боевом `.py`, поэтому расплывчатое «any(launch:)» оставалось истинным,
        когда обёртки агента разбор уже не видел. Замер, а не рассуждение:
        мутация прошла молча, и это единственное, что отличает контроль от
        украшения.
        """
        owners = pollers.module_owners("spa_core/telegram/bot.py")
        self.assertTrue(owners, "разбор не видит владельца у главного бота")
        self.assertIn(
            "launch:scripts/agent_telegram_bot.sh", owners,
            f"обёртка агента перестала считаться запуском: {owners}")

    def test_a_delivery_list_is_not_an_owner(self):
        """Путь файла в списке доставки пушера — упоминание, а не запуск.

        Ровно этой формой `bot_commands` числился бы «подключённым»:
        `scripts/push_all_session.sh` перечисляет его путь среди файлов для
        отправки на origin. Четвёртая слепота храповика #227, закрытая тем,
        что путь засчитывается только рядом с интерпретатором и в одной строке.
        """
        hay = {
            "scripts/push_manifest.sh": (
                "FILES=\"\\\n  /abs/spa_core/alerts/ghost.py \\\n  /abs/other.py\"\n"
            ),
        }
        self.assertEqual(
            pollers._owners_from("spa_core/alerts/ghost.py", hay, set()), [],
            "перечисление пути в списке доставки засчитано за запуск")
        hay["scripts/run_it.sh"] = "python3 spa_core/alerts/ghost.py\n"
        self.assertTrue(
            pollers._owners_from("spa_core/alerts/ghost.py", hay, set()),
            "запуск интерпретатором перестал считаться владением")


class TestSecondReaderKnownGap(unittest.TestCase):
    """ОТКРЫТЫЙ дефект, названный вслух: watcher выгребает ту же очередь.

    `spa_core/monitoring/telegram_watcher.py` читает `getUpdates` СО смещением
    и продвигает его (`run_once`: `_save_offset(max_update_id + 1)`). Апдейт,
    подтверждённый им, Telegram больше НИКОМУ не отдаст — то есть сообщение
    владельца может не дойти до бота вовсе. Его plist лежит в дереве
    (`launchd/com.spa.telegram_watcher.plist`, StartInterval 300).

    Чинить это здесь нельзя: это боевой агент и решение владельца (стоп-правило
    CLAUDE.md). Карточка заведена. Тест держит дефект НАЗВАННЫМ и обязан
    покраснеть в тот день, когда его закроют, — иначе закрытие пройдёт молча.
    """

    def test_watcher_still_confirms_updates_KNOWN_GAP(self):
        src = (_REPO / "spa_core/monitoring/telegram_watcher.py").read_text(encoding="utf-8")
        self.assertIn(
            "_save_offset(max_update_id + 1)", src,
            "watcher перестал подтверждать очередь — дефект закрыт: убрать этот "
            "KNOWN_GAP, снять модуль из EXPECTED_POLLERS/EXPECTED_OFFSET_STORES "
            "и закрыть карточку own-55-vtoroi-chitatel-komand-v-telegram")
        self.assertTrue(
            (_REPO / "launchd/com.spa.telegram_watcher.plist").exists(),
            "plist watcher'а исчез — состояние изменилось, пересмотреть базу")


if __name__ == "__main__":
    unittest.main()
