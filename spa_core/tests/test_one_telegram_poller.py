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

17.08 второй такой модуль СПИСАН решением владельца (карточка
`own-55-vtoroi-chitatel-komand-v-telegram`, ВАРИАНТ 1):
`spa_core/monitoring/telegram_watcher.py` раз в 5 минут выгребал ту же очередь
СО смещением и ПОДТВЕРЖДАЛ её (`_save_offset(max_update_id + 1)`), а
подтверждённый апдейт Telegram не отдаёт больше никому — то есть команда
владельца могла уйти сторожу и до бота не дойти вовсе. Удалены модуль, его
настройка агента (`launchd/com.spa.telegram_watcher.plist`, StartInterval 300),
его тесты и запись в `architecture/manifest.json`. Подтверждающий читатель
теперь РОВНО ОДИН, и этот файл обязан краснеть, если появится второй.

Что здесь проверяется — и чего эти проверки НЕ проверяют
------------------------------------------------------------------------------
* читателей очереди ровно столько, сколько названо (и список может только
  уменьшаться);
* ПОДТВЕРЖДАЮЩИЙ очередь — ровно один: своё смещение есть своя память о
  прочитанном и право стереть сообщение владельца для всех остальных;
* у каждой двери в чат владельца есть ВЛАДЕЛЕЦ: её кто-то импортирует или
  запускает. Дверь без владельца никто не открывает — но открыть может любой;
* списанные поллеры не вернулись ни модулем, ни установщиком, ни plist'ом.

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
}

#: Хранилище смещения = память о прочитанном. Читатель, ПОДТВЕРЖДАЮЩИЙ очередь,
#: с 17.08 ровно один: `telegram_watcher` списан решением владельца по карточке
#: `own-55-vtoroi-chitatel-komand-v-telegram` (`checkpoint_7day` смещения не
#: хранит и не подтверждает).
EXPECTED_OFFSET_STORES = {
    "spa_core/telegram/bot.py": {"tg_bot_v2_offset.json"},
}

#: Списанные поллеры: цикл #258 — `bot_commands`; 17.08 — `telegram_watcher`
#: (ВАРИАНТ 1 владельца по own-55: «убрать модуль, настройку агента и тесты»).
#: Возврат ЛЮБОГО из этих путей — возврат класса «второй читатель очереди».
RETIRED_POLLER = "spa_core/alerts/bot_commands.py"
RETIRED_INSTALLER = "scripts/install_bot_commands.sh"
RETIRED_WATCHER = "spa_core/monitoring/telegram_watcher.py"
RETIRED_WATCHER_PLIST = "launchd/com.spa.telegram_watcher.plist"
RETIRED_WATCHER_TEST = "tests/test_telegram_watcher.py"
#: Имя задания launchd. Файлов в дереве больше нет, но копия plist'а могла
#: уцелеть на Маке — и тогда её воскрешает не репозиторий, а установщик/сторож
#: самолечения. Держится это ТОЛЬКО именем в списках ретированных (см.
#: `test_the_host_cannot_re_bootstrap_the_retired_watcher`).
RETIRED_LABEL = "com.spa.telegram_watcher"

#: ОТКРЫТОЕ состояние, названное вслух, а не одобренное. `auto_fixer` — вторая
#: половина той же петли: watcher её ЗАПУСКАЛ (`run_auto_fix`), она просит
#: Claude переписать прод-код и запушить. Со списанием watcher'а вызывающих в
#: боевом коде у неё не осталось НИ ОДНОГО, а `__main__` остался — то есть это
#: ровно «дверь без владельца», которую запрещает `TestEveryDoorHasAnOwner`.
#:
#: Почему исключение, а не удаление: решение владельца по own-55 названо
#: поимённо и касается watcher'а (модуль, plist, тесты). Судьба `auto_fixer` —
#: отдельный вопрос владельцу (карточка
#: `own-56-avtopochinshchik-ostalsya-bez-vyzyvayushchih`), а не догадка сессии;
#: стоп-правило CLAUDE.md запрещает трогать боевой модуль без ответа.
#: Почему это НЕ молчаливое ослабление (инв. #16): исключение ровно одно и
#: названо путём; тест ниже краснеет в ОБЕ стороны — и если сирот станет
#: больше, и если эта перестанет быть сиротой (удалили или дали вызывающего),
#: то есть закрытие вопроса не может пройти незамеченным.
ORPHANED_DOORS_KNOWN_GAP = {"spa_core/devtools/auto_fixer.py"}


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

    def test_exactly_one_module_confirms_the_queue(self):
        """Подтверждающий читатель — РОВНО ОДИН, и это канонический бот.

        Читать очередь и ПОДТВЕРЖДАТЬ её — разные вещи, и цена у второй другая:
        подтверждённый апдейт Telegram не отдаёт больше НИКОМУ, то есть команда
        владельца исчезает совсем (own-55). Поэтому вопрос задан отдельно от
        `test_no_unnamed_reader_of_the_update_queue`: `checkpoint_7day` читает,
        но не подтверждает, и его появление здесь было бы новым дефектом.
        """
        confirming = set(pollers.offset_stores())
        self.assertEqual(
            confirming, {"spa_core/telegram/bot.py"},
            "подтверждать очередь Telegram имеет право только канонический бот; "
            f"нашлось: {sorted(confirming)}. Своё смещение = право стереть "
            "сообщение владельца для всех остальных.")

    def test_the_retired_poller_did_not_come_back(self):
        self.assertFalse(
            (_REPO / RETIRED_POLLER).exists(),
            f"{RETIRED_POLLER} вернулся в дерево: собственный getUpdates + "
            "собственный __main__ = второй поллер в одну строку.")
        self.assertFalse(
            (_REPO / RETIRED_INSTALLER).exists(),
            f"{RETIRED_INSTALLER} вернулся: установщик агента, которого нет ни "
            "в одном коммите, и чья удача стоила бы владельцу команд.")

    def test_the_retired_watcher_did_not_come_back(self):
        """Списание watcher'а — три следа, и возврат ЛЮБОГО красит тест.

        Модуль без plist'а — второй поллер в одну строку `python3 -m …`;
        plist без модуля — агент, падающий каждые 5 минут; тест без модуля —
        зелёный отчёт о том, чего нет. Поэтому спрашиваются все три.
        """
        for rel, why in (
            (RETIRED_WATCHER,
             "модуль с собственным getUpdates СО смещением: он подтверждает "
             "апдейты, и команда владельца может не дойти до бота вовсе"),
            (RETIRED_WATCHER_PLIST,
             "настройка агента com.spa.telegram_watcher (StartInterval 300): "
             "одна `launchctl bootstrap` — и второй читатель снова живой"),
            (RETIRED_WATCHER_TEST,
             "тест списанного модуля: зелёный отчёт о несуществующем коде"),
        ):
            self.assertFalse(
                (_REPO / rel).exists(),
                f"{rel} вернулся в дерево — {why}. Списан решением владельца "
                "17.08 по карточке own-55-vtoroi-chitatel-komand-v-telegram.")

    def test_the_host_cannot_re_bootstrap_the_retired_watcher(self):
        """Дерево чистое — а на Маке plist мог УЦЕЛЕТЬ, и его подняли бы обратно.

        Все проверки выше смотрят на файлы репозитория и по построению НЕ видят
        `~/Library/LaunchAgents`. Между тем и `self_heal._expected_labels`, и
        `scripts/verify_fleet_after_reboot.sh` перебирают именно то, что лежит на
        хосте: любой `com.spa.*.plist`, не названный ретированным, они
        BOOTSTRAP'ят обратно. То есть удаление plist'а из репозитория само по
        себе НЕ мешает уцелевшей копии воскреснуть после перезагрузки — воскресший
        watcher снова начал бы подтверждать очередь и красть команды владельца.

        Единственное, что это закрывает, — имя в списке ретированных, поэтому
        оно проверяется в ОБОИХ местах (Python-набор и shell-скрипт живут
        отдельно и уже расходились).
        """
        from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS

        self.assertIn(
            RETIRED_LABEL, RETIRED_LABELS,
            f"{RETIRED_LABEL} пропал из RETIRED_LABELS: self_heal снова считает "
            "уцелевший на хосте plist «ожидаемым» и поднимает второго читателя "
            "очереди (ADR-093 п.2).")

        verifier = (_REPO / "scripts" / "verify_fleet_after_reboot.sh").read_text(
            encoding="utf-8")
        retired_line = [
            ln for ln in verifier.splitlines() if ln.startswith("RETIRED=")]
        self.assertEqual(len(retired_line), 1, "разбор не нашёл строку RETIRED=")
        self.assertIn(
            RETIRED_LABEL, retired_line[0],
            f"{RETIRED_LABEL} пропал из RETIRED в verify_fleet_after_reboot.sh: "
            "проверка после перезагрузки сделает `launchctl bootstrap` уцелевшему "
            "plist'у вместо `bootout`.")


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
        found = set(pollers.ownerless(sorted(doors.scan_repo())))
        self.assertEqual(
            found - ORPHANED_DOORS_KNOWN_GAP, set(),
            "дверь в чат владельца без единого вызывающего и без запуска: "
            f"{sorted(found - ORPHANED_DOORS_KNOWN_GAP)}. Такой модуль выглядит "
            "рабочим, его правят «по аналогии», и он запускается одной строкой.")

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


class TestSecondReaderIsGoneForGood(unittest.TestCase):
    """Положительный контроль САМОГО списания: тест обязан краснеть ДО него.

    Предыдущая редакция этого класса (`TestSecondReaderKnownGap`) держала дефект
    названным, пока владелец решал. 17.08 он выбрал ВАРИАНТ 1 — списать. Класс
    заменён, а не удалён: проверка должна была бы покраснеть на состоянии ДО
    списания, иначе она украшение (правило `.claude/rules/deployment.md`).

    Здесь это ИЗМЕРЕНО герметично: дерево-фикстура воспроизводит вчерашнее
    состояние — модуль с собственным `getUpdates` и собственным смещением рядом
    с ботом, — и разбор обязан увидеть в нём ДВУХ подтверждающих читателей.
    Мутация «перестать смотреть на смещение» гасит именно этот вопрос.
    """

    @staticmethod
    def _tree_of_yesterday(root: Path) -> None:
        """Синтез дерева ДО списания: бот + watcher, у каждого своё смещение."""
        bot = root / "spa_core" / "telegram"
        bot.mkdir(parents=True)
        (bot / "bot.py").write_text(
            '_api_call("getUpdates", {"timeout": 30})\n'
            'OFFSET = "tg_bot_v2_offset.json"\n', encoding="utf-8")
        mon = root / "spa_core" / "monitoring"
        mon.mkdir(parents=True)
        (mon / "telegram_watcher.py").write_text(
            '_tg_request(token, "getUpdates", params)\n'
            'OFFSET_FILE = DATA_DIR / "telegram_last_update_id.json"\n',
            encoding="utf-8")

    def test_the_watchdog_would_be_red_on_yesterdays_tree(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree_of_yesterday(root)

            readers = set(pollers.poller_modules(root))
            self.assertIn(
                "spa_core/monitoring/telegram_watcher.py", readers,
                "разбор не видит вчерашнего второго читателя — значит зелёный "
                "результат на сегодняшнем дереве ничего не доказывает")
            self.assertNotEqual(
                readers - EXPECTED_POLLERS, set(),
                "на дереве ДО списания test_no_unnamed_reader_of_the_update_"
                "queue обязан краснеть")

            confirming = set(pollers.offset_stores(root))
            self.assertEqual(
                confirming,
                {"spa_core/telegram/bot.py",
                 "spa_core/monitoring/telegram_watcher.py"},
                "на дереве ДО списания подтверждающих читателей было ДВА — "
                "test_exactly_one_module_confirms_the_queue обязан краснеть")

    def test_todays_tree_has_exactly_one_confirming_reader(self):
        """Обратная сторона: на СЕГОДНЯШНЕМ дереве вопрос закрыт."""
        self.assertEqual(set(pollers.offset_stores()), {"spa_core/telegram/bot.py"})


class TestOrphanedAutoFixerKnownGap(unittest.TestCase):
    """ОТКРЫТЫЙ вопрос, названный вслух: у `auto_fixer` не осталось вызывающих.

    Списание watcher'а убрало ЕДИНСТВЕННОГО, кто звал `run_auto_fix`. Модуль
    остался целиком: свой `__main__`, свой ключ Claude, своя запись в прод-код и
    свой пуш — то есть вторая половина ровно той петли, из-за которой владелец
    и списал watcher («авто-починка кода по тексту из чата — самая рискованная
    петля в системе»). Удалять его сессия не имеет права: решение own-55 названо
    поимённо и его не касается.

    Тест держит состояние названным и краснеет в ОБЕ стороны:
      * сирота исчезла (удалили) или обзавелась вызывающим — вопрос закрыт,
        значит `ORPHANED_DOORS_KNOWN_GAP` обязан уйти вместе с этим классом;
      * сирот стало больше — ловит `test_no_ownerless_door` выше.
    """

    def test_auto_fixer_is_still_the_only_orphaned_door_KNOWN_GAP(self):
        found = set(pollers.ownerless(sorted(doors.scan_repo())))
        self.assertEqual(
            found, ORPHANED_DOORS_KNOWN_GAP,
            "набор дверей без владельца изменился: "
            f"{sorted(found)} против {sorted(ORPHANED_DOORS_KNOWN_GAP)}. Если "
            "auto_fixer получил вызывающего или снят — снять исключение "
            "ORPHANED_DOORS_KNOWN_GAP и этот класс, закрыв карточку "
            "own-56-avtopochinshchik-ostalsya-bez-vyzyvayushchih.")


if __name__ == "__main__":
    unittest.main()
