"""Тесты card_lookup — детерминированные ответы владельцу про карточки/очередь.

Живой промах 2026-08-19 (карточка inbox-bot-otritsaet-suschestvuyuschuyu-own-kartochku):
на «есть ли на мне own-54?» бот ответил «в моих записях нет» при карточке наверху
доски. Каждый тест ниже воспроизводит кусок того диалога. Offline, сети нет,
живые деревья не трогаются (все пути — во временных каталогах).

Run:
    python3 -m unittest spa_core.tests.test_bot_card_lookup -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.telegram import card_lookup as cl


def _card(status: str = "needs-owner", title: str = "Заголовок") -> str:
    return (
        "---\n"
        "type: owner-decision\n"
        f"status: {status}\n"
        "created: 2026-08-15\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Что случилось\n\nТело.\n"
    )


class TestExtractCardRef(unittest.TestCase):
    def test_short_slug_inside_sentence(self):
        # Дословно вопрос владельца 19.08.
        self.assertEqual(cl.extract_card_ref("на мне есть задачи own-54 ?"), "own-54")

    def test_full_slug_with_md(self):
        self.assertEqual(
            cl.extract_card_ref("проверь own-54-mertvye-knigi-issledovatelskoy-paneli.md"),
            "own-54-mertvye-knigi-issledovatelskoy-paneli",
        )

    def test_inbox_and_agent_prefixes(self):
        self.assertEqual(cl.extract_card_ref("что с inbox-actual-costs?"),
                         "inbox-actual-costs")
        self.assertEqual(cl.extract_card_ref("agent-durable-session-id глянь"),
                         "agent-durable-session-id")

    def test_bare_prefix_is_not_a_ref(self):
        # Голое слово «own» / «task» — не ссылка на карточку.
        self.assertIsNone(cl.extract_card_ref("это мой own проект, task force"))

    def test_plain_speech_has_no_ref(self):
        self.assertIsNone(cl.extract_card_ref("почему кэш 7 процентов?"))
        self.assertIsNone(cl.extract_card_ref(""))


class TestIsQueueQuestion(unittest.TestCase):
    def test_variants(self):
        for q in (
            "что на мне?",
            "а что сейчас на мне висит",
            "мои задачи покажи",
            "что ждёт моего решения",
            "что ждет ответа",
        ):
            self.assertTrue(cl.is_queue_question(q), q)

    def test_negative(self):
        for q in ("статус портфеля", "почему доходность 5%", ""):
            self.assertFalse(cl.is_queue_question(q), q)


class TestFindCards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "own-54-mertvye-knigi.md").write_text(_card(), encoding="utf-8")
        (self.dir / "own-540-drugaya.md").write_text(_card(), encoding="utf-8")
        (self.dir / "inbox-actual-costs.md").write_text(_card("new"), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_stem_wins(self):
        hits = cl.find_cards("inbox-actual-costs", self.dir)
        self.assertEqual([p.name for p in hits], ["inbox-actual-costs.md"])

    def test_prefix_match_returns_both(self):
        # «own-54» — префикс и для own-54-…, и для own-540-… (неоднозначно, обе).
        hits = cl.find_cards("own-54", self.dir)
        self.assertEqual(
            [p.name for p in hits],
            ["own-54-mertvye-knigi.md", "own-540-drugaya.md"],
        )

    def test_md_suffix_stripped(self):
        hits = cl.find_cards("own-54-mertvye-knigi.md", self.dir)
        self.assertEqual([p.name for p in hits], ["own-54-mertvye-knigi.md"])

    def test_no_match_and_missing_dir(self):
        self.assertEqual(cl.find_cards("owner-decision-net-takoi", self.dir), [])
        self.assertEqual(cl.find_cards("own-54", self.dir / "нет"), [])


class TestFetchOriginCard(unittest.TestCase):
    """git инжектируется — сети и настоящего git в тестах нет."""

    def _git(self, listing: str, bodies: dict):
        def fake(args, repo_root):
            if args[0] == "fetch":
                return ""  # успех, вывод пуст
            if args[0] == "ls-tree":
                return listing
            if args[0] == "show":
                name = args[1].rsplit("/", 1)[-1]
                return bodies.get(name)
            return None
        return fake

    def test_unique_prefix_found(self):
        listing = ("nimbalyst-local/tracker/own-54-mertvye-knigi.md\n"
                   "nimbalyst-local/tracker/inbox-other.md\n")
        git = self._git(listing, {"own-54-mertvye-knigi.md": _card()})
        got = cl.fetch_origin_card("own-54", Path("/nowhere"), git=git)
        self.assertIsNotNone(got)
        name, body = got
        self.assertEqual(name, "own-54-mertvye-knigi.md")
        self.assertIn("needs-owner", body)

    def test_ambiguous_prefix_refused(self):
        # Две own-54* на origin — угадывать нельзя (fail-CLOSED).
        listing = ("nimbalyst-local/tracker/own-54-a.md\n"
                   "nimbalyst-local/tracker/own-54-b.md\n")
        git = self._git(listing, {})
        self.assertIsNone(cl.fetch_origin_card("own-54", Path("/nowhere"), git=git))

    def test_git_unavailable_is_none_not_raise(self):
        self.assertIsNone(
            cl.fetch_origin_card("own-54", Path("/nowhere"),
                                 git=lambda a, r: None)
        )


class TestMaterializeText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_new_card(self):
        p = cl.materialize_text("own-54-x.md", _card(), self.dir)
        self.assertIsNotNone(p)
        self.assertTrue(p.is_file())
        self.assertIn("needs-owner", p.read_text(encoding="utf-8"))

    def test_never_overwrites_existing(self):
        # В живой копии может лежать ответ владельца — затирать запрещено.
        target = self.dir / "own-54-x.md"
        target.write_text("ОТВЕТ ВЛАДЕЛЬЦА ВНУТРИ", encoding="utf-8")
        p = cl.materialize_text("own-54-x.md", _card(), self.dir)
        self.assertEqual(p, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "ОТВЕТ ВЛАДЕЛЬЦА ВНУТРИ")

    def test_path_traversal_refused(self):
        self.assertIsNone(cl.materialize_text("../evil.md", _card(), self.dir))
        self.assertIsNone(cl.materialize_text("no-extension", _card(), self.dir))


class TestQueueAnswer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_only_needs_owner(self):
        (self.dir / "own-a.md").write_text(_card("needs-owner", "Вопрос А"),
                                           encoding="utf-8")
        (self.dir / "inbox-b.md").write_text(_card("new", "Задача Б"),
                                             encoding="utf-8")
        (self.dir / "own-c.md").write_text(_card("done", "Готово В"),
                                           encoding="utf-8")
        out = cl.queue_answer(self.dir)
        self.assertIn("own-a.md", out)
        self.assertIn("Вопрос А", out)
        self.assertNotIn("inbox-b.md", out)
        self.assertNotIn("own-c.md", out)
        self.assertIn("1 шт", out)

    def test_empty_queue_says_so_with_caveat(self):
        out = cl.queue_answer(self.dir)
        self.assertIn("needs-owner", out)
        # Честная оговорка про origin обязана присутствовать: пустое живое
        # дерево ≠ пустая очередь (живой промах 19.08).
        self.assertIn("origin", out)

    def test_board_file_ignored(self):
        (self.dir / "_BOARD.md").write_text(_card("needs-owner"), encoding="utf-8")
        out = cl.queue_answer(self.dir)
        self.assertNotIn("_BOARD.md", out)


class TestBotWiring(unittest.TestCase):
    """Проводка: сам метод и его вызов ДО классификатора (урок «объявил → не доставил»)."""

    def _bot_source(self) -> str:
        import spa_core.telegram.bot as bot_mod
        return Path(bot_mod.__file__).read_text(encoding="utf-8")

    def test_handler_exists(self):
        from spa_core.telegram.bot import TelegramBot
        self.assertTrue(hasattr(TelegramBot, "_handle_card_query"))

    def test_called_before_classifier(self):
        src = self._bot_source()
        intake = src.split("def _handle_inbox_intake", 1)[1]
        pos_card = intake.find("_handle_card_query(")
        pos_classify = intake.find("_classify_route(stripped")
        self.assertGreater(pos_card, 0, "вызов _handle_card_query не проведён в intake")
        self.assertGreater(pos_classify, pos_card,
                           "карточный вопрос должен разбираться ДО классификатора")

    def test_text_answer_still_first(self):
        # «Ответ 1» разбирается раньше карточного пути: сообщение-ответ может
        # содержать имя карточки, и оно обязано остаться ОТВЕТОМ.
        src = self._bot_source()
        intake = src.split("def _handle_inbox_intake", 1)[1]
        self.assertLess(intake.find("_handle_owner_text_answer(stripped"),
                        intake.find("_handle_card_query("))


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ─── v2: «умный бот без слагов» (задание владельца 2026-08-20) ────────────────

class TestMatchQueuePick(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(cl.match_queue_pick("открой 2"), 2)
        self.assertEqual(cl.match_queue_pick("Покажи №3"), 3)
        self.assertEqual(cl.match_queue_pick("пришли 10"), 10)

    def test_bare_number_is_not_a_pick(self):
        # Голое число — ОТВЕТ владельца (ADR-082), выбором быть не смеет.
        self.assertIsNone(cl.match_queue_pick("2"))
        self.assertIsNone(cl.match_queue_pick("Ответ 2"))

    def test_speech_is_not_a_pick(self):
        self.assertIsNone(cl.match_queue_pick("открой мне глаза"))
        self.assertIsNone(cl.match_queue_pick(""))


class TestStripLookupLead(unittest.TestCase):
    def test_lead_words(self):
        self.assertEqual(cl.strip_lookup_lead("проверь тормоз"), "тормоз")
        self.assertEqual(cl.strip_lookup_lead("найди карточку про сайт"), "сайт")
        self.assertEqual(cl.strip_lookup_lead("покажи аварийный тормоз"),
                         "аварийный тормоз")

    def test_no_lead_is_none(self):
        self.assertIsNone(cl.strip_lookup_lead("почему кэш 7%?"))
        self.assertIsNone(cl.strip_lookup_lead(""))


class TestFindCardsByTitle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "own-rnd-killswitch.md").write_text(
            _card("needs-owner", "Аварийный тормоз: политика возврата"),
            encoding="utf-8")
        (self.dir / "own-33-plist.md").write_text(
            _card("needs-owner", "Добавить строку в настройку агента"),
            encoding="utf-8")
        (self.dir / "_BOARD.md").write_text("доска", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_russian_word_hits_title(self):
        hits = cl.find_cards_by_title("тормоз", self.dir)
        self.assertEqual([p.name for p in hits], ["own-rnd-killswitch.md"])

    def test_all_words_must_match(self):
        self.assertEqual(cl.find_cards_by_title("тормоз агента", self.dir), [])

    def test_slug_word_also_searchable(self):
        hits = cl.find_cards_by_title("plist", self.dir)
        self.assertEqual([p.name for p in hits], ["own-33-plist.md"])

    def test_board_ignored_and_short_query_empty(self):
        self.assertEqual(cl.find_cards_by_title("доска", self.dir), [])
        self.assertEqual(cl.find_cards_by_title("а", self.dir), [])


class TestQueueOverview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "own-a.md").write_text(_card("needs-owner", "Вопрос А"),
                                           encoding="utf-8")
        (self.dir / "own-b.md").write_text(_card("needs-owner", "Вопрос Б"),
                                           encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_numbered_and_returns_cards(self):
        text, cards = cl.queue_overview(self.dir)
        self.assertEqual(len(cards), 2)
        self.assertIn("1. ", text)
        self.assertIn("2. ", text)
        self.assertIn("открой 2", text)

    def test_queue_answer_backcompat_is_text_only(self):
        self.assertEqual(cl.queue_answer(self.dir), cl.queue_overview(self.dir)[0])


class TestBotWiringV2(unittest.TestCase):
    def _bot_source(self) -> str:
        import spa_core.telegram.bot as bot_mod
        return Path(bot_mod.__file__).read_text(encoding="utf-8")

    def test_send_card_helper_exists(self):
        from spa_core.telegram.bot import TelegramBot
        self.assertTrue(hasattr(TelegramBot, "_send_card"))

    def test_queue_branch_autosends_cards(self):
        # «Что на мне?» обязан не только перечислить, но и разослать карточки.
        src = self._bot_source()
        handler = src.split("def _handle_card_query", 1)[1]
        queue_branch = handler.split("wants_queue and not ref", 1)[1]
        self.assertIn("_send_card(", queue_branch.split("def ", 1)[0])

    def test_pick_uses_last_queue_memory(self):
        src = self._bot_source()
        handler = src.split("def _handle_card_query", 1)[1].split("def _handle_inbox_intake", 1)[0]
        self.assertIn("match_queue_pick", handler)
        self.assertIn("_last_queue_cards", handler)

    def test_title_search_wired(self):
        src = self._bot_source()
        handler = src.split("def _handle_card_query", 1)[1].split("def _handle_inbox_intake", 1)[0]
        self.assertIn("find_cards_by_title", handler)
        self.assertIn("strip_lookup_lead", handler)
