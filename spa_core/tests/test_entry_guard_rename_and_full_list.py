"""Страж перезаписи: переименование ≠ потеря, и список находок — по ВСЕМ файлам
(карточка `inbox-strazh-perezapisi-schitaet-pereimenovani`, цикл #154).

**Каждый тест — положительный контроль**: он воспроизводит НАСТОЯЩЕЕ поведение
доставки цикла #150 и краснеет на непочиненном пушере
(`.claude/rules/deployment.md`).

Что тогда произошло. `push_to_github.py` отказал в доставке #150 так:

    ОТКАЗ (страж перезаписи): docs/journal/2026-W29.md: пуш стёр бы 2 запис(ь/и) …
        - ## 2026-07-16 (автономный цикл оркестратора) — hardening: owner-queue dead-letter …
        - ## 2026-07-17

Ни одна запись не исчезала: обеим цикл #150 ДОПИСАЛ В ЗАГОЛОВОК номер цикла, а
тела совпали с remote побайтово (1256 и 6213 не-заголовочных строк, `git diff` —
ровно 5 вставок / 5 удалений, все пять строки-заголовки). У находки две стороны,
и опасна вторая:

1. ложная тревога — сама по себе безобидна (fail-CLOSED, обход `--allow-overwrite`);
2. **список неполон** — в том же пуше был переименован заголовок и в
   `2026-W31.md`, но страж его НЕ назвал. Причина измерена чтением кода:
   `build_entries` роняет цикл на ПЕРВОМ файле с находкой, и до второго дело
   не доходит. Решение «обходить или нет» человек принимает по этому списку;
   список короче правды опаснее отсутствия списка — он выглядит полным.

Байты фикстур СТИЛИЗОВАНЫ (как в `test_journal_entry_loss_guard.py`): тест
обязан проверять механику, а не оставаться заложником истории репозитория.
Времени в тестах нет — сравнение чисто содержательное, литеральных дат в
фикстурах нет по построению.
"""
import importlib.util
import unittest
from pathlib import Path

from spa_core.tests import _pusher_wiring as wiring

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_pusher_rename_under_test", _ROOT / "push_to_github.py")
pusher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pusher)

SHA = "a" * 40
JOURNAL = "docs/journal/2026-W29.md"

#: Тела двух записей, которые цикл #150 НЕ трогал (совпали с remote побайтово).
BODY_16 = "### Что сделано\n\nowner-queue dead-letter, разбор очереди\n\n### Проверка\n\nпрогон"
BODY_17 = "### Что сделано\n\nтело второй записи\n\n### Проверка\n\nпрогон"


def entry(header: str, body: str) -> bytes:
    return f"\n## {header}\n\n{body}\n".encode()


def doc(*entries: bytes) -> bytes:
    return b"# journal\n" + b"".join(entries)


class RenameIsNotLoss(unittest.TestCase):
    """Тело записи на месте побайтово ⇒ запись на месте, как бы ни звался заголовок."""

    def test_the_real_150_refusal_is_gone(self):
        """Ровно тот отказ, что остановил доставку #150: два заголовка получили
        номер цикла, тела не менялись. На непочиненном пушере — `EntryLossRefused`."""
        remote = doc(entry("2026-07-16 (автономный цикл оркестратора) — hardening", BODY_16),
                     entry("2026-07-17", BODY_17))
        ours = doc(entry("2026-07-16 (автономный цикл оркестратора #2) — hardening", BODY_16),
                   entry("2026-07-17 — автономный цикл #16 (разбор очереди)", BODY_17))
        note = pusher.guard_entry_loss(JOURNAL, remote, ours, remote_sha=SHA)
        self.assertIn("переименовано заголовков — 2", note)

    def test_rename_is_named_not_silent(self):
        """Отказа нет — но случай НАЗЫВАЕТСЯ: заголовок общей тетради изменился,
        и автор доставки обязан это увидеть. Молчание здесь было бы fail-OPEN."""
        remote = doc(entry("2026-07-17", BODY_17))
        ours = doc(entry("2026-07-17 — автономный цикл #16", BODY_17))
        note = pusher.guard_entry_loss(JOURNAL, remote, ours, remote_sha=SHA)
        self.assertIn("2026-07-17", note)
        self.assertIn("автономный цикл #16", note)
        self.assertIn("побайтово", note)

    def test_rename_of_a_state_blockquote_entry(self):
        """`docs/STATE.md` пишет записи блок-цитатой — то же правило и там."""
        remote = "# SPA\n\n> **(цикл #128) — заголовок.**\n> тело записи 128\n\n".encode()
        ours = "# SPA\n\n> **(цикл #128) — заголовок переписан.**\n> тело записи 128\n\n".encode()
        note = pusher.guard_entry_loss("docs/STATE.md", remote, ours, remote_sha=SHA)
        self.assertIn("переименовано заголовков — 1", note)


class LossStillRefuses(unittest.TestCase):
    """Контроль в ОБРАТНУЮ сторону: сузился ровно доказанный случай, и только он."""

    def test_deleted_entry_still_refuses(self):
        remote = doc(entry("2026-07-16 — цикл #2", BODY_16), entry("2026-07-17", BODY_17))
        ours = doc(entry("2026-07-16 — цикл #2", BODY_16))
        with self.assertRaises(pusher.EntryLossRefused) as ctx:
            pusher.guard_entry_loss(JOURNAL, remote, ours, remote_sha=SHA)
        self.assertIn("стёр бы 1 запис", str(ctx.exception))

    def test_renamed_header_with_changed_body_is_a_loss(self):
        """Заголовок другой И тело другое — сказать «это та же запись» нечем.
        Fail-CLOSED: отказ."""
        remote = doc(entry("2026-07-17", BODY_17))
        ours = doc(entry("2026-07-17 — цикл #16", BODY_17 + "\n\nдописано"))
        with self.assertRaises(pusher.EntryLossRefused):
            pusher.guard_entry_loss(JOURNAL, remote, ours, remote_sha=SHA)

    def test_empty_body_is_not_a_rename_candidate(self):
        """Пустое тело совпало бы с чем угодно — такой «признак» доказывает ноль."""
        remote = doc(entry("2026-07-17", ""))
        ours = doc(entry("2026-07-17 — цикл #16", ""))
        with self.assertRaises(pusher.EntryLossRefused):
            pusher.guard_entry_loss(JOURNAL, remote, ours, remote_sha=SHA)

    def test_duplicate_header_dropped_once_is_still_a_loss(self):
        """Самый тонкий случай: два ОДИНАКОВЫХ заголовка с ОДИНАКОВЫМ телом, а
        уцелел один. Тело «нашлось» бы у выжившей записи — поэтому сопоставление
        идёт с кратностью: первая фаза гасит по заголовку, и на вторую тело
        выжившей записи уже не выдаётся."""
        remote = doc(entry("2026-07-17", BODY_17), entry("2026-07-17", BODY_17))
        ours = doc(entry("2026-07-17", BODY_17))
        with self.assertRaises(pusher.EntryLossRefused) as ctx:
            pusher.guard_entry_loss(JOURNAL, remote, ours, remote_sha=SHA)
        self.assertIn("стёр бы 1 запис", str(ctx.exception))

    def test_rename_and_loss_together_refuse_and_name_both(self):
        """Смешанный пуш: одна запись переименована, другая стёрта. Отказ — по
        стёртой, но нота о переименовании остаётся в сообщении: иначе автор
        решает по неполной картине (та же болезнь, что и обрыв на первом файле)."""
        remote = doc(entry("2026-07-16", BODY_16), entry("2026-07-17", BODY_17))
        ours = doc(entry("2026-07-16 — цикл #2", BODY_16))
        with self.assertRaises(pusher.EntryLossRefused) as ctx:
            pusher.guard_entry_loss(JOURNAL, remote, ours, remote_sha=SHA)
        msg = str(ctx.exception)
        self.assertIn("стёр бы 1 запис", msg)
        self.assertIn("2026-07-17", msg)          # что стёрто
        self.assertIn("переименовано заголовков — 1", msg)   # и что НЕ стёрто


class EntryBlocks(unittest.TestCase):
    """Граница записи — до следующего заголовка, а не до конца файла."""

    def test_body_ends_at_the_next_header(self):
        blocks = pusher.entry_blocks(doc(entry("A", "тело A"), entry("B", "тело B")))
        self.assertEqual([h for h, _ in blocks], [b"## A", b"## B"])
        self.assertEqual([b for _, b in blocks], ["тело A".encode(), "тело B".encode()])

    def test_subheadings_stay_inside_the_body(self):
        blocks = pusher.entry_blocks(doc(entry("A", BODY_16)))
        self.assertEqual(len(blocks), 1)
        self.assertIn("### Проверка".encode(), blocks[0][1])

    def test_none_blob_yields_nothing(self):
        self.assertEqual(pusher.entry_blocks(None), [])


class FullListAcrossAllFiles(unittest.TestCase):
    """Батч — ОДИН коммит, значит и решение принимается по ПОЛНОМУ списку."""

    def setUp(self):
        self.blobs = []
        self._orig = (pusher.guard_overwrite, pusher.create_blob_from_bytes,
                      pusher.tree_entry_mode)
        pusher.create_blob_from_bytes = lambda pat, repo, content: (
            self.blobs.append(content) or ("b" * 40))
        pusher.tree_entry_mode = lambda *a, **kw: "100644"

    def tearDown(self):
        (pusher.guard_overwrite, pusher.create_blob_from_bytes,
         pusher.tree_entry_mode) = self._orig

    def _fail_on(self, paths, exc=None):
        exc = exc or (lambda p: pusher.EntryLossRefused(f"{p}: пуш стёр бы 1 запис(ь/и)"))

        def fake(pat, repo, branch, repo_path, abs_path, local_bytes, remote_sha,
                 allow_overwrite=False):
            if repo_path in paths:
                raise exc(repo_path)
            return local_bytes, ""
        pusher.guard_overwrite = fake

    @staticmethod
    def _changed(*paths):
        return [(p, __file__, SHA) for p in paths]

    def _build(self, *paths):
        return pusher.build_entries("pat", "repo", "main", self._changed(*paths), {}, False)

    def test_finding_in_the_second_file_is_named_too(self):
        """Положительный контроль дефекта #150: на непочиненном пушере в
        сообщении есть только `W29`, потому что цикл оборвался на нём."""
        self._fail_on({"docs/journal/2026-W29.md", "docs/journal/2026-W31.md"})
        with self.assertRaises(pusher.DivergenceRefused) as ctx:
            self._build("docs/journal/2026-W29.md", "docs/journal/2026-W31.md")
        msg = str(ctx.exception)
        self.assertIn("2026-W29.md", msg)
        self.assertIn("2026-W31.md", msg)
        self.assertIn("2 из 2", msg)

    def test_finding_only_in_the_second_file_still_refuses(self):
        """Контроль в обратную сторону: перебор всех файлов не должен «терять»
        находку, если первый файл чистый."""
        self._fail_on({"docs/journal/2026-W31.md"})
        with self.assertRaises(pusher.EntryLossRefused) as ctx:
            self._build("docs/journal/2026-W29.md", "docs/journal/2026-W31.md")
        self.assertIn("2026-W31.md", str(ctx.exception))

    def test_single_failure_keeps_the_guard_message_verbatim(self):
        """Один сбойный файл — сообщение стража дословно, без обёртки: на нём
        стоят и существующие тесты, и глаз человека."""
        self._fail_on({"docs/journal/2026-W31.md"})
        with self.assertRaises(pusher.EntryLossRefused) as ctx:
            self._build("docs/journal/2026-W31.md")
        self.assertEqual(str(ctx.exception),
                         "docs/journal/2026-W31.md: пуш стёр бы 1 запис(ь/и)")

    def test_no_blobs_are_created_when_any_file_is_refused(self):
        """Пуш отменён целиком ⇒ blob'ов быть не должно вовсе. Старый порядок
        успевал создать их для файлов ДО сбойного — мусор в репозитории."""
        self._fail_on({"docs/journal/2026-W31.md"})
        with self.assertRaises(pusher.DivergenceRefused):
            self._build("docs/journal/2026-W29.md", "docs/journal/2026-W31.md")
        self.assertEqual(self.blobs, [])

    def test_clean_batch_still_creates_every_blob(self):
        """Контроль в обратную сторону: страж, роняющий всё, ничего не доказывает."""
        self._fail_on(set())
        entries = self._build("docs/journal/2026-W29.md", "docs/journal/2026-W31.md")
        self.assertEqual(len(entries), 2)
        self.assertEqual(len(self.blobs), 2)

    def test_same_reason_keeps_the_narrow_class(self):
        """Классы отказа различают коды выхода CLI — на слитом списке они не
        должны схлопываться в общий, если причина одна и та же."""
        self._fail_on({"a.md", "b.md"})
        with self.assertRaises(pusher.EntryLossRefused):
            self._build("a.md", "b.md")

    def test_mixed_reasons_fall_back_to_the_base_class(self):
        """Разные причины — общий класс: выдавать все находки за одну означало бы
        соврать вызывающему, который по классу выбирает, что делать дальше."""
        def exc(p):
            return (pusher.EntryLossRefused(f"{p}: потеря")
                    if p == "a.md" else pusher.UnmeasuredBaseRefused(f"{p}: базы нет"))
        self._fail_on({"a.md", "b.md"}, exc=exc)
        with self.assertRaises(pusher.DivergenceRefused) as ctx:
            self._build("a.md", "b.md")
        self.assertNotIsInstance(ctx.exception, pusher.EntryLossRefused)
        self.assertNotIsInstance(ctx.exception, pusher.UnmeasuredBaseRefused)


class RenameNoteReachesTheHuman(unittest.TestCase):
    """Нота бесполезна, если её никто не печатает — сверяем ПРОВОДКУ."""

    def test_safe_path_returns_the_note(self):
        # Проводка меряется общим `_pusher_wiring` (подъём #467): с появлением
        # второй охраняемой единицы смысла ветка зовёт дверь `guard_content_loss`,
        # а не проверку напрямую. Утверждение «нота присваивается и возвращается»
        # сохранено рядом — вместе они и есть прежний вопрос, только без
        # привязки к одному конкретному имени вызываемого.
        safe = wiring.branch_of("DIVERGENCE_SAFE")
        wiring.assert_branch_reaches(safe, "guard_entry_loss", "ветка DIVERGENCE_SAFE")
        self.assertRegex(safe, r"note = guard_\w+\(")
        self.assertNotIn('return local_bytes, ""', safe)

    def test_unmeasured_path_appends_the_note(self):
        src = (_ROOT / "push_to_github.py").read_text(encoding="utf-8")
        unmeasured = src.split("DIVERGENCE_UNMEASURED:")[1].split("# DIVERGENCE_DIVERGED")[0]
        self.assertIn("entry_note", unmeasured)

    def test_both_clis_share_one_implementation(self):
        """У батча и одиночного CLI страж ОДИН — иначе починка живёт в одном месте."""
        _bspec = importlib.util.spec_from_file_location(
            "_batch_rename_under_test", _ROOT / "push_to_github_batch.py")
        batch = importlib.util.module_from_spec(_bspec)
        _bspec.loader.exec_module(batch)
        self.assertIs(batch.build_entries, batch._root_push.build_entries)


if __name__ == "__main__":
    unittest.main()
