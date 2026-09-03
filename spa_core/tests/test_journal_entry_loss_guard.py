"""Запись, которая есть на remote, не исчезает молча (карточка
`inbox-zhurnal-tsiklov-molcha-teryaet-zapisi-pr`, цикл #139).

**Каждый тест — положительный контроль**: он воспроизводит НАСТОЯЩУЮ потерю из
истории репозитория (коммит назван в теле теста) и краснеет на непочиненном
пушере. Проверка, никогда не видевшая реальной поломки, — украшение
(`.claude/rules/deployment.md`).

Замер, породивший эти тесты (проход по `git log` каждого файла, набор заголовков
записей на каждом коммите, разность мультимножеств):

    docs/journal/2026-W31.md  3 события, 33 записи
    docs/journal/2026-W32.md  4 события, 19 записей
    docs/STATE.md             5 событий, 16 записей
    ИТОГО 12 событий на 277 переходов, 68 стёртых записей

Байты записей взяты СТИЛИЗОВАННЫМИ, а не выкачиваются из git: тест обязан
проверять МЕХАНИКУ, а не оставаться заложником истории (переписанная история
или архивирование журнала не должны красить набор по причине, не имеющей
отношения к проверяемому поведению). Номера циклов и коммиты сохранены, чтобы
связь с реальной аварией читалась.

Времени в тестах нет — сравнение чисто содержательное, литеральных дат в
фикстурах нет по построению (`.claude/rules/deployment.md`, «время в тестах»).
"""
import importlib.util
import unittest
from pathlib import Path

from spa_core.tests import _pusher_wiring as wiring

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_pusher_under_test", _ROOT / "push_to_github.py")
pusher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pusher)


def journal(*cycles: int) -> bytes:
    """Недельный журнал с записями перечисленных циклов (дописывание В КОНЕЦ)."""
    out = [b"# journal\n"]
    for c in cycles:
        out.append(
            f"\n## Цикл #{c} (автономный) — что сделано\n\n"
            f"### Что сделано\n\nтело записи цикла {c}\n\n"
            f"### Проверка\n\nпрогон {c}\n".encode()
        )
    return b"".join(out)


def state_doc(*cycles: int) -> bytes:
    """`docs/STATE.md` — записи блок-цитатой и дописывание СВЕРХУ."""
    head = b"# SPA - STATE\n\n"
    body = b"".join(
        f"> **(цикл #{c}) — заголовок записи.**\n> тело записи {c}\n\n".encode()
        for c in cycles
    )
    return head + body


class EntryExtraction(unittest.TestCase):
    """Что считается ЗАПИСЬЮ — граница проверки, а не деталь реализации."""

    def test_journal_entry_headers_are_h2_only(self):
        heads = pusher.entry_headers(journal(95, 96))
        self.assertEqual(len(heads), 2, heads)
        self.assertTrue(all(h.startswith(b"## ") for h in heads), heads)

    def test_subheadings_are_body_not_entries(self):
        """`### Проверка` — тело. Замер: на подзаголовках проверка даёт 9 лишних
        срабатываний из 155 переходов только по журналам."""
        blob = journal(95)
        joined = b"".join(pusher.entry_headers(blob))
        self.assertNotIn("### Проверка".encode(), joined)

    def test_state_blockquote_headers_are_entries(self):
        heads = pusher.entry_headers(state_doc(128, 129))
        self.assertEqual(len(heads), 2, heads)

    def test_none_blob_yields_no_entries(self):
        self.assertEqual(pusher.entry_headers(None), [])


class WhichDocsAreGuarded(unittest.TestCase):
    def test_journal_and_state_are_guarded(self):
        self.assertTrue(pusher.is_append_only_doc("docs/STATE.md"))
        self.assertTrue(pusher.is_append_only_doc("docs/journal/2026-W32.md"))

    def test_board_and_code_are_not(self):
        """`_BOARD.md` пересобирается ЦЕЛИКОМ — для него исчезновение записи
        нормальный исход, и проверка обязана его не трогать."""
        self.assertFalse(pusher.is_append_only_doc("nimbalyst-local/tracker/_BOARD.md"))
        self.assertFalse(pusher.is_append_only_doc("push_to_github.py"))
        self.assertFalse(pusher.is_append_only_doc("docs/journal/notes.txt"))


class RealLosses(unittest.TestCase):
    """Настоящие аварии. Каждая краснеет на непочиненном пушере."""

    def _assert_refused(self, path, remote, ours, *, expect_lost):
        with self.assertRaises(pusher.EntryLossRefused) as ctx:
            pusher.guard_entry_loss(path, remote, ours, remote_sha="a" * 40)
        msg = str(ctx.exception)
        self.assertIn(f"стёр бы {expect_lost} запис", msg)
        return msg

    def test_cddc9417e_journal_loses_cycles_126_128_129(self):
        """`cddc9417e`: сессия с базой до #126 дописала свою запись к СТАРОМУ
        содержимому — три чужие записи исчезли, пушер сказал OK."""
        remote = journal(125, 126, 128, 129)
        ours = journal(125, 130)
        msg = self._assert_refused("docs/journal/2026-W32.md", remote, ours, expect_lost=3)
        for c in (126, 128, 129):
            self.assertIn(f"#{c}".encode().decode(), msg)

    def test_9333c3716_journal_loses_seven_cycles(self):
        """`9333c3716`: самая крупная потеря журнала (#117–#123)."""
        remote = journal(*range(117, 124))
        ours = journal(124)
        self._assert_refused("docs/journal/2026-W32.md", remote, ours, expect_lost=7)

    def test_3989c044e_and_cbf295fdf_lose_cycle_125_twice(self):
        """Запись #125 терялась ДВАЖДЫ (восстановленная — снова)."""
        for _ in range(2):
            self._assert_refused("docs/journal/2026-W32.md",
                                 journal(124, 125), journal(124, 127), expect_lost=1)

    def test_cddc9417e_state_md_loses_five_entries(self):
        """`STATE.md` теряет так же — карточка требовала это ИЗМЕРИТЬ: да, 5 событий."""
        remote = state_doc(129, 128, 127, 126, 125)
        ours = state_doc(130, 125)
        self._assert_refused("docs/STATE.md", remote, ours, expect_lost=4)

    def test_f35ff96ed_loses_one_entry_while_adding_others(self):
        """Потеря СОБСТВЕННОЙ базой (remote == база): файл вырос на 15 строк, а
        одна запись из него пропала. Путь `DIVERGENCE_SAFE` тоже проверяется."""
        self._assert_refused("docs/STATE.md",
                             state_doc(86, 85), state_doc(88, 87, 86), expect_lost=1)

    def test_duplicate_header_dropped_once_is_still_a_loss(self):
        """Кратность значима: два одинаковых заголовка, остался один — запись ушла."""
        remote = journal(95, 95)
        ours = journal(95)
        self._assert_refused("docs/journal/2026-W32.md", remote, ours, expect_lost=1)

    def test_message_names_what_disappears(self):
        """Отказ обязан НАЗЫВАТЬ пропавшее — иначе автору нечего восстанавливать."""
        msg = self._assert_refused("docs/journal/2026-W32.md",
                                   journal(126), journal(130), expect_lost=1)
        self.assertIn("Цикл #126", msg)
        self.assertIn("--allow-overwrite", msg)


class LegitimatePushesArePassedThrough(unittest.TestCase):
    """Контроль в ОБРАТНУЮ сторону: страж, краснеющий всегда, ничего не доказывает."""

    def test_plain_append_passes(self):
        self.assertEqual(
            pusher.guard_entry_loss("docs/journal/2026-W32.md",
                                    journal(126, 128), journal(126, 128, 139),
                                    remote_sha="a" * 40), "")

    def test_prepend_to_state_passes(self):
        self.assertEqual(
            pusher.guard_entry_loss("docs/STATE.md",
                                    state_doc(138, 137), state_doc(139, 138, 137),
                                    remote_sha="a" * 40), "")

    def test_body_edit_without_entry_loss_passes(self):
        """Правка тела записи — не потеря записи (объявленная граница проверки)."""
        remote = journal(126)
        ours = remote.replace("тело записи цикла 126".encode(),
                              "тело переписано целиком".encode())
        self.assertEqual(
            pusher.guard_entry_loss("docs/journal/2026-W32.md", remote, ours,
                                    remote_sha="a" * 40), "")

    def test_unguarded_path_is_never_refused(self):
        self.assertEqual(
            pusher.guard_entry_loss("nimbalyst-local/tracker/_BOARD.md",
                                    journal(126, 128), b"", remote_sha="a" * 40), "")

    def test_new_file_on_remote_absent_is_passed(self):
        self.assertEqual(
            pusher.guard_entry_loss("docs/journal/2026-W33.md", None, journal(139),
                                    remote_sha=None), "")

    def test_allow_overwrite_is_the_deliberate_escape_hatch(self):
        """Осознанное сокращение остаётся возможным — но перестаёт быть умолчанием."""
        self.assertEqual(
            pusher.guard_entry_loss("docs/journal/2026-W32.md",
                                    journal(126, 128), journal(139),
                                    remote_sha="a" * 40, allow_overwrite=True), "")


class UncheckedIsNotOk(unittest.TestCase):
    """«Не прочитано» — не «всё в порядке» (класс fail-OPEN, инвариант #2)."""

    def test_unreadable_remote_refuses_for_shared_docs(self):
        with self.assertRaises(pusher.EntryLossRefused) as ctx:
            pusher.guard_entry_loss("docs/journal/2026-W32.md", None, journal(139),
                                    remote_sha="b" * 40)
        self.assertIn("НЕ ПРОЧИТАНО", str(ctx.exception))

    def test_unreadable_remote_is_ignored_for_unguarded_paths(self):
        self.assertEqual(
            pusher.guard_entry_loss("push_to_github.py", None, b"x",
                                    remote_sha="b" * 40), "")


class GuardIsWiredIntoThePusher(unittest.TestCase):
    """Проверка бесполезна, если её никто не зовёт — сверяем ТОЧКИ ВСТРАИВАНИЯ."""

    def test_entry_loss_is_a_divergence_refusal(self):
        """Оба вызывающих (`push_file`, `build_entries`) ловят `DivergenceRefused`,
        поэтому новый отказ обязан быть его подклассом — иначе он проломит батч
        трассировкой вместо честного FAIL."""
        self.assertTrue(issubclass(pusher.EntryLossRefused, pusher.DivergenceRefused))

    # ── ПРАВКА ПОДЪЁМА #467, обоснование по инварианту #16 ────────────────
    # Две проверки ниже спрашивали текст точки встраивания на литерал
    # `guard_entry_loss`. С появлением второй охраняемой единицы смысла
    # (раздел `.claude/rules/*.md`, карточка
    # `inbox-u-failov-claude-rules-net-ni-odnogo-stor`) ветки зовут ОДНУ дверь
    # `guard_content_loss`, которая внутри зовёт обе проверки.
    #
    # Это НЕ ослабление и не подгонка под зелёный: вопрос теста («доходит ли
    # сюда проверка записей?») сохранён ЦЕЛИКОМ и стал строже — вместо поиска
    # имени в тексте меряются ДВА звена, второе разбором AST (см.
    # `_pusher_wiring`). Ровно тот же вопрос задавали ещё два файла своими
    # копиями строки; теперь реализация одна на всех.

    def test_guard_overwrite_calls_the_check_on_the_unmeasured_path(self):
        """Дыра была именно здесь: базы нет ⇒ пуш уходил как есть."""
        src = (_ROOT / "push_to_github.py").read_text(encoding="utf-8")
        del src
        wiring.assert_branch_reaches(wiring.branch_of("DIVERGENCE_UNMEASURED"),
                                     "guard_entry_loss", "ветка DIVERGENCE_UNMEASURED")

    def test_guard_overwrite_calls_the_check_on_the_safe_path(self):
        src = (_ROOT / "push_to_github.py").read_text(encoding="utf-8")
        del src
        wiring.assert_branch_reaches(wiring.branch_of("DIVERGENCE_SAFE"),
                                     "guard_entry_loss", "ветка DIVERGENCE_SAFE")


if __name__ == "__main__":
    unittest.main()
