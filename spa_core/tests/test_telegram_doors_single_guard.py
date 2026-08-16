"""Все двери в чат владельца — через ОДИН заслон. Храповик + положительные контроли.

Авария, которую повторяет каждый тест ниже
------------------------------------------------------------------------------
13.08 владелец пожаловался дважды одними и теми же словами: поток одинаковых
сообщений, и невозможно узнать, кто их шлёт («параллельная история, которую ты не
видишь»). Дедуп в проекте к тому дню существовал четыре дня — но стоял на ОДНОЙ
двери, а владелец ходит в другие. Цикл #215 свёл под ``guard_outbound`` две; здесь
закрываются оставшиеся три и сам класс:

1. ``scripts/site_freshness_monitor._alert`` — сырой POST боевыми секретами из
   GitHub Actions каждые 6 ч: ни лимита потока, ни дедупа, ни журнала. Живого
   дерева в CI нет, поэтому её сообщения не попадали в ``alert_history.json``
   НИКОГДА;
2. ``spa_core/alerts/bot_commands._api_post`` — брала у заслона половину: лимит
   потока без журнала и без отметки о подавлении;
3. ``spa_core/telegram/bot.edit_message_text`` — та же половина: текст в чате
   владельца МЕНЯЛСЯ без следа в истории.

Плюс найденное по дороге: тревога «табличка честности НЕ уехала на сайт» падала
внутри ``_alert`` на ``KeyError: 'n_fails'`` (второй звонящий передаёт другую форму
отчёта), а call-site глотал исключение. То есть тревога о публично видимом
завышенном числе не уходила владельцу НИ РАЗУ. Тест 09.08 этого не видел: он
подменял сам ``_alert`` и проверял, что его ПОЗВАЛИ, — «сторож отвечает не на тот
вопрос» уровнем ниже.

Сеть не трогаем: ``urlopen`` подменяется в каждом тесте (живую попытку ловит
``telegram_guard``).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from spa_core.tests import _telegram_doors as doors

_REPO = Path(__file__).resolve().parents[2]

#: Двери, которые СЕГОДНЯ существуют и обязаны быть видны разбору. Список — не
#: украшение: класс прячется именно тем, что проверка перестаёт видеть дверь
#: (переименовали транспорт — и разбор молча вернул пустоту, которую легко
#: прочитать как «всё чисто»).
#:
#: Дверь 2 (`spa_core/alerts/bot_commands.py::_api_post`) СНЯТА 16.08 вместе с
#: модулем (цикл #258): у него не осталось ни одного вызывающего в боевом коде,
#: агента нет с 27.06, а собственный `getUpdates` и собственный `__main__`
#: делали его вторым поллером в одну строку. Дверей стало 4 — это уменьшение
#: класса, а не ослабление проверки: храповик `test_no_unguarded_door_anywhere`
#: не тронут, а новый сторож `test_one_telegram_poller.py` запрещает двери без
#: владельца (никто не импортирует и не запускает) — именно такой она и была.
KNOWN_DOORS = {
    "spa_core/alerts/telegram_client.py": {"_post_message"},
    "spa_core/telegram/bot.py": {"send_message", "edit_message_text"},
    "scripts/site_freshness_monitor.py": {"_alert"},
    "spa_core/devtools/auto_fixer.py": {"_tg_request"},
}


def _load_monitor():
    """Загрузить монитор по пути — как это делает CI (корня репо нет в sys.path)."""
    spec = importlib.util.spec_from_file_location(
        "site_freshness_monitor_c218", str(_REPO / "scripts" / "site_freshness_monitor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRatchet(unittest.TestCase):
    """Ни одной двери в чат владельца мимо общего заслона."""

    def test_no_unguarded_door_anywhere(self):
        found = doors.unguarded()
        self.assertEqual(
            found, {},
            "дверь в чат владельца без guard_outbound (и не уведённая в дайджест): "
            f"{found}. Половину заслона брать нельзя — см. докстринг guard_outbound.")

    def test_every_known_door_is_still_visible(self):
        """Положительный контроль САМОГО разбора: ослепнув, он вернул бы {} и выглядел бы зелёным."""
        scan = doors.scan_repo()
        for rel, expected in KNOWN_DOORS.items():
            self.assertIn(rel, scan, f"разбор перестал видеть двери в {rel}")
            seen = {str(d["function"]) for d in scan[rel]}
            missing = expected - seen
            self.assertFalse(missing, f"{rel}: разбор потерял из виду {missing}")


class TestDetectorPositiveControls(unittest.TestCase):
    """Разбор обязан краснеть на настоящей аварии и молчать на законном коде."""

    def _scan_source(self, src: str):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "sample.py"
            p.write_text(src, encoding="utf-8")
            return doors.scan_file(p)

    def test_raw_post_door_is_caught(self):
        """Ровно форма site_freshness_monitor ДО починки."""
        found = self._scan_source(
            "import json, urllib.request\n"
            "def _alert(tok, chat, msg):\n"
            "    data = json.dumps({'chat_id': chat, 'text': msg}).encode()\n"
            "    req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage', data=data)\n"
            "    urllib.request.urlopen(req, timeout=15)\n")
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["guarded"], "сырой POST обязан считаться незащищённой дверью")

    def test_transport_plus_caller_door_is_caught(self):
        """Форма bot.py: URL и urlopen в транспорте, имя метода — у звонящего."""
        found = self._scan_source(
            "import urllib.request\n"
            "class B:\n"
            "    def __init__(self, token):\n"
            "        self.api_base = 'https://api.telegram.org/bot%s' % token\n"
            "    def _api_call(self, method, params):\n"
            "        req = urllib.request.Request('{}/{}'.format(self.api_base, method))\n"
            "        return urllib.request.urlopen(req)\n"
            "    def edit(self, text):\n"
            "        return self._api_call('editMessageText', {'text': text})\n")
        names = {str(d["function"]): d["guarded"] for d in found}
        self.assertIn("edit", names, "дверь через общий транспорт обязана быть найдена")
        self.assertFalse(names["edit"])

    def test_guarded_door_is_not_flagged(self):
        found = self._scan_source(
            "import urllib.request\n"
            "def send(tok, msg):\n"
            "    from spa_core.alerts.telegram_client import guard_outbound\n"
            "    if guard_outbound(msg) is not None:\n"
            "        return False\n"
            "    req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage')\n"
            "    urllib.request.urlopen(req)\n")
        self.assertTrue(found and found[0]["guarded"])

    def test_control_methods_are_not_doors(self):
        """getUpdates/getMe чата не трогают — требовать от них заслона было бы шумом."""
        found = self._scan_source(
            "import urllib.request\n"
            "def poll(tok):\n"
            "    req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/getUpdates')\n"
            "    return urllib.request.urlopen(req)\n")
        self.assertEqual(found, [])

    def test_digest_route_is_not_a_push(self):
        """Выведенная из строя дверь (текст уходит в дайджест) владельца не беспокоит."""
        found = self._scan_source(
            "import urllib.request\n"
            "def _tg(tok, method, payload):\n"
            "    if method == 'sendMessage':\n"
            "        from spa_core.telegram import push_policy\n"
            "        push_policy.enqueue_digest('x', 'y', payload['text'])\n"
            "        return {'ok': False}\n"
            "    req = urllib.request.Request(f'https://api.telegram.org/bot{tok}/{method}')\n"
            "    return urllib.request.urlopen(req)\n")
        self.assertTrue(found and found[0]["guarded"])


class TestSiteCustodianDoor(unittest.TestCase):
    """Дверь 1 — сырой POST из CI боевыми секретами каждые 6 часов."""

    def setUp(self):
        self.mod = _load_monitor()
        self.report = {"ok": False, "n_fails": 1, "ts": "2026-08-13T16:00:00+00:00",
                       "fails": [{"severity": "FAIL", "code": "STALE_SNAPSHOT", "detail": "x"}]}

    def _post_spy(self):
        sent = []

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return json.dumps({"ok": True, "result": {"message_id": 777}}).encode()

        def _urlopen(req, *a, **kw):
            sent.append(getattr(req, "full_url", str(req)))
            return _Resp()

        return sent, _urlopen

    def test_the_guard_is_asked_before_sending(self):
        """Положительный контроль: снять вызов заслона — тест краснеет."""
        sent, _urlopen = self._post_spy()
        with mock.patch.dict(self.mod.os.environ if hasattr(self.mod, "os") else {},
                             {}, clear=False):
            pass
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound",
                        return_value=None) as guard, \
             mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN_SPA": "t",
                                            "TELEGRAM_CHAT_ID_SPA": "c",
                                            "SPA_LIVE_ROOT": str(_REPO)}), \
             mock.patch.object(self.mod.urllib.request, "urlopen", _urlopen):
            out = self.mod._alert(dict(self.report))
        guard.assert_called_once()
        self.assertTrue(out["sent"])
        self.assertEqual(len(sent), 1)

    def test_a_suppressed_alert_is_not_sent(self):
        """Подавление обязано ДЕЙСТВОВАТЬ, а не выглядеть существующим.

        Ровно этим болел снятый `telegram_manager.send`: он всегда возвращал False,
        и управление всегда проваливалось в сырой POST ниже.
        """
        sent, _urlopen = self._post_spy()
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound",
                        return_value="duplicate_dropped"), \
             mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN_SPA": "t",
                                            "TELEGRAM_CHAT_ID_SPA": "c",
                                            "SPA_LIVE_ROOT": str(_REPO)}), \
             mock.patch.object(self.mod.urllib.request, "urlopen", _urlopen):
            out = self.mod._alert(dict(self.report))
        self.assertEqual(sent, [], "подавленная тревога не имеет права уйти в чат")
        self.assertFalse(out["attempted"])
        self.assertEqual(out["reason"], "duplicate_dropped")

    def test_the_send_is_journaled(self):
        """«Кто это шлёт» обязан иметь ответ: каждая отправка — запись в журнале канала."""
        sent, _urlopen = self._post_spy()
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound", return_value=None), \
             mock.patch("spa_core.alerts.telegram_client._record_history") as hist, \
             mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN_SPA": "t",
                                            "TELEGRAM_CHAT_ID_SPA": "c",
                                            "SPA_LIVE_ROOT": str(_REPO)}), \
             mock.patch.object(self.mod.urllib.request, "urlopen", _urlopen):
            out = self.mod._alert(dict(self.report))
        hist.assert_called_once()
        self.assertTrue(hist.call_args.kwargs["ok"])
        self.assertEqual(hist.call_args.kwargs["message_id"], 777)
        self.assertTrue(out["journaled"])

    def test_without_a_live_tree_the_gap_is_named_out_loud(self):
        """CI: журнала нет. Тогда владелец обязан прочитать об этом В САМОМ сообщении.

        Молчаливая отправка мимо журнала — это и есть «параллельная история»: следующий
        разбор снова упрётся в пустой alert_history и потратит круг (08–09.08 — два).
        """
        sent = []

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return b"{}"

        def _urlopen(req, *a, **kw):
            sent.append(json.loads(req.data.decode())["text"])
            return _Resp()

        env = {"TELEGRAM_BOT_TOKEN_SPA": "t", "TELEGRAM_CHAT_ID_SPA": "c",
               "SPA_LIVE_ROOT": "/nonexistent-live-root-c218"}
        with mock.patch.dict("os.environ", env), \
             mock.patch.object(self.mod, "_live_journal", return_value=(None, "live_tree_absent")), \
             mock.patch.object(self.mod.urllib.request, "urlopen", _urlopen):
            out = self.mod._alert(dict(self.report))
        self.assertEqual(len(sent), 1, "тревога обязана дойти даже без журнала")
        self.assertIn("мимо журнала", sent[0])
        self.assertFalse(out["journaled"])
        self.assertTrue(out["off_journal_note"])

    def test_the_undelivered_plaque_alert_actually_composes(self):
        """Тревога о недоставленной табличке честности падала на KeyError и не уходила НИ РАЗУ."""
        sent, _urlopen = self._post_spy()
        payload = {"severity": "FAIL", "failures": [{
            "code": "HONESTY_PLAQUE_UNDELIVERED",
            "detail": "push rc=5 — сайт не обновлён"}]}
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound", return_value=None), \
             mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN_SPA": "t",
                                            "TELEGRAM_CHAT_ID_SPA": "c",
                                            "SPA_LIVE_ROOT": str(_REPO)}), \
             mock.patch.object(self.mod.urllib.request, "urlopen", _urlopen):
            out = self.mod._alert(payload)
        self.assertTrue(out["sent"], "тревога о публично видимом завышенном числе обязана уходить")
        self.assertEqual(len(sent), 1)

    def test_the_retired_manager_is_no_longer_consulted(self):
        """`telegram_manager.send` ВСЕГДА возвращал False и попутно клал копию в дайджест.

        Проверяем ВЫЗОВ (AST), а не текст: разбор аварии живёт в докстринге этого же
        файла, и проверка по подстроке краснела бы на объяснении, а не на дефекте.
        """
        import ast
        tree = ast.parse((_REPO / "scripts" / "site_freshness_monitor.py").read_text(encoding="utf-8"))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "send"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "telegram_manager"
        ]
        self.assertEqual(calls, [],
                         "выведенный из строя менеджер в лестнице доставки — подавление, "
                         "которого нет, плюс копия владельцу в дайджесте")


class TestClientLoadsWithoutThePackageOnPath(unittest.TestCase):
    """Замер в ДОЧЕРНЕМ процессе: под pytest `spa_core` уже импортирован и путь загрузки слеп.

    Монитор запускают как ``python scripts/site_freshness_monitor.py`` — тогда
    ``sys.path[0]`` это ``scripts/``, корня репозитория на пути НЕТ, и обычный
    ``import spa_core…`` падает ``ModuleNotFoundError`` (ровно на этом 04.08 владельцу
    уезжал сырой английский). Заслон обязан работать и там, иначе починка держится
    на удаче окружения. В самом же CI живого дерева нет — и тогда честный ответ
    «журнала нет», а не его имитация.
    """

    def _child(self, env_extra):
        import os
        import subprocess
        import textwrap
        code = textwrap.dedent("""
            import sys, importlib.util, json
            # Замер ДО загрузки: после неё пакет уже подложен, и вопрос теряет смысл.
            importable = importlib.util.find_spec("spa_core") is not None
            spec = importlib.util.spec_from_file_location("sfm", sys.argv[1])
            m = importlib.util.module_from_spec(spec); sys.modules["sfm"] = m
            spec.loader.exec_module(m)
            client, why = m._live_journal()
            # Подложенный пакет не имеет права сломать обычный импорт дальше в процессе:
            # им пользуется `_humanize_body`, и его поломка вернула бы владельцу сырой
            # английский (авария 04.08).
            try:
                from spa_core.telegram.humanize import humanize_body
                humanize_ok = True
            except Exception as exc:
                humanize_ok = "%s: %s" % (type(exc).__name__, exc)
            print(json.dumps({
                "package_importable": importable,
                "loaded": client is not None,
                "why": why,
                "has_guard": bool(client is not None and hasattr(client, "guard_outbound")),
                "has_history": bool(client is not None and hasattr(client, "_record_history")),
                "humanize_ok": humanize_ok,
            }))
        """)
        env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
        env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, "-c", code, str(_REPO / "scripts" / "site_freshness_monitor.py")],
            capture_output=True, text=True, cwd=str(_REPO / "scripts"), env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_guard_reachable_when_the_package_is_not_importable(self):
        out = self._child({"SPA_LIVE_ROOT": str(_REPO)})
        self.assertFalse(out["package_importable"],
                         "тест обязан мерить именно тот случай, когда пакета на пути НЕТ")
        self.assertTrue(out["loaded"], f"заслон недостижим: {out['why']}")
        self.assertTrue(out["has_guard"] and out["has_history"])
        self.assertIs(out["humanize_ok"], True,
                      "подложенный пакет сломал обычный импорт — это вернуло бы владельцу "
                      f"сырой английский (авария 04.08): {out['humanize_ok']}")

    def test_without_a_live_tree_the_answer_is_an_honest_refusal(self):
        out = self._child({"SPA_LIVE_ROOT": "/nonexistent-live-root-c218"})
        self.assertFalse(out["loaded"])
        self.assertEqual(out["why"], "live_tree_absent",
                         "в CI журнала нет — это обязано быть НАЗВАНО, а не сымитировано")


# Дверь 2 (`spa_core/alerts/bot_commands._api_post`) СНЯТА вместе с модулем
# 16.08 (цикл #258) — списан целиком: ни одного вызывающего в боевом коде,
# агента нет с 27.06, свой `getUpdates` и свой `__main__` = второй поллер на том
# же токене в одну строку. Три её вопроса (инв. #16 — правка намеренная,
# обоснование здесь и в `docs/journal/2026-W33.md`):
#   * «заслон спрошен и отправка записана в журнал» — уже задан живой двери
#     ниже (`TestEditMessageDoor.test_edit_asks_the_guard_and_is_journaled`);
#   * «подавленная отправка не доходит до сети» — там же
#     (`test_a_suppressed_edit_never_reaches_the_api`);
#   * «служебные вызовы заслона не требуют» — на живом пути его не задавал
#     НИКТО, поэтому он не удалён, а переставлен: `TestControlCallsStayUnguarded`
#     ниже спрашивает то же самое у `spa_core/telegram/bot.py`.
# Проверка не ослаблена — она переехала с мёртвого кода на исполняемый.


class TestControlCallsStayUnguarded(unittest.TestCase):
    """`answerCallbackQuery` чата не трогает — заслон здесь был бы шумом.

    Обратная сторона храповика дверей: если ПОД заслон уедет служебный вызов,
    лимит потока начнёт глушить снятие «часиков» на кнопке, и владелец увидит
    вечный спиннер вместо ответа.
    """

    def test_answer_callback_does_not_ask_the_guard(self):
        from spa_core.telegram.bot import TelegramBot

        bot = TelegramBot(token="tok", chat_id="1")
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound") as guard, \
             mock.patch.object(bot, "_api_call", return_value={"ok": True}) as api:
            bot._answer_callback("cb-1")
        guard.assert_not_called()
        api.assert_called_once()
        self.assertEqual(api.call_args.args[0], "answerCallbackQuery")


class TestEditMessageDoor(unittest.TestCase):
    """Дверь 3 — текст в чате владельца менялся без следа в истории."""

    def _bot(self):
        from spa_core.telegram.bot import TelegramBot
        return TelegramBot(token="tok", chat_id="1")

    def test_edit_asks_the_guard_and_is_journaled(self):
        bot = self._bot()
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound",
                        return_value=None) as guard, \
             mock.patch("spa_core.alerts.telegram_client._record_history") as hist, \
             mock.patch.object(bot, "_api_call", return_value={"ok": True}) as api:
            bot.edit_message_text("1", 5, "панель")
        guard.assert_called_once()
        self.assertFalse(guard.call_args.kwargs["dedup"],
                         "правка панели — прямой ответ на нажатие, глушить нельзя")
        api.assert_called_once()
        hist.assert_called_once()
        self.assertTrue(hist.call_args.kwargs["solicited"])
        self.assertEqual(hist.call_args.kwargs["message_id"], 5)

    def test_a_suppressed_edit_never_reaches_the_api(self):
        bot = self._bot()
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound",
                        return_value="flood_guard_dropped"), \
             mock.patch.object(bot, "_api_call") as api:
            out = bot.edit_message_text("1", 5, "панель")
        api.assert_not_called()
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
