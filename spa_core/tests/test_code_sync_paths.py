"""Список синхронизируемых каталогов — контракт, а не деталь реализации.

Три аварии стоят за этим тестом.

**Чего в списке не хватало (2026-08-08).** `architecture/manifest.json` хранит решения
владельца по ~90 фоновым агентам, и ежечасный сторож сверяет с ним то, что реально
крутится. Файл не возил никто: синхронизация знала только `spa_core/`, `scripts/`,
`tests/`. Машина пересобирала конституцию из своей старой копии — четверо только что
одобренных владельцем агентов были объявлены четырьмя «КРИТИЧНО», и автомат завёл
владельцу четыре карточки. Ложная тревога дорога не сама по себе: она учит не смотреть
на сторожа.

**Чего не хватало ещё (2026-09-02, ADR-214).** Инструкции, по которым агент работает
(`CLAUDE.md`, `.claude/rules/`), читаются ИЗ ПРОД-ДЕРЕВА и не возились туда никогда.
Замер 02.09: `CLAUDE.md` 211 строк против 221 на origin, `adapters.md` 19 против 34,
`design-docs.md` в дереве отсутствовал. Цена не косметическая: локальная копия держала
«Sky/sUSDS = 0 %» — запрет, СНЯТЫЙ владельцем 05.08 (ADR-065), — и предписывала старую,
более узкую команду прогона тестов. Доставленный код без правил, которые им управляют, —
половина доставки. Решение владельца — вариант 1 карточки
`owner-decision-instruktsii-po-kotorym-rabotayut-agenty`.

**Чего в списке быть не должно никогда.** `data/` — живой трек. Синхронизация кода его
не касается (`.claude/rules/deployment.md` §4); один `git checkout` поверх него уже стоил
постоянной дыры в треке. И `.claude/` ЦЕЛИКОМ — там живёт локальное состояние сессий
(`worktrees/`, `settings.local.json`), которым origin не владеет; возится только
подкаталог правил.

Тест читает сам скрипт, а не повторяет список: копия контракта рядом с контрактом
разойдётся с ним при первой же правке.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "code_sync_from_origin.sh"


def _script_text() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


def _code_paths() -> list[str]:
    m = re.search(r"CODE_PATHS=\(([^)]*)\)", _script_text())
    assert m, "CODE_PATHS не найден — скрипт переписан, тест обязан упасть"
    return m.group(1).split()


class TestSyncedPaths(unittest.TestCase):

    def test_architecture_is_synced(self):
        """Без него решения владельца не доезжают до машины."""
        self.assertIn("architecture", _code_paths(),
                      "каталог решений об агентах обязан доезжать до прода")

    def test_the_code_dirs_are_all_there(self):
        for d in ("spa_core", "scripts", "tests"):
            self.assertIn(d, _code_paths())

    def test_instructions_are_synced(self):
        """ADR-214: правила, по которым агент работает, — часть доставки, а не фон.

        Уберут отсюда — и прод снова начнёт исполнять снятые запреты, молча.
        """
        paths = _code_paths()
        self.assertIn("CLAUDE.md", paths,
                      "главная инструкция обязана доезжать до дерева, из которого её читают")
        self.assertIn(".claude/rules", paths,
                      "path-специфичные правила обязаны доезжать до прод-дерева")

    def test_data_is_NEVER_synced(self):
        """Сторона, где ошибка стоит трека целиком."""
        self.assertNotIn("data", _code_paths(),
                         "живой трек синхронизацией кода не перезаписывается — никогда")

    def test_owner_queues_and_docs_stay_out(self):
        """Очереди и документы живут своей жизнью; checkout поверх них теряет работу.

        `.claude` ЦЕЛИКОМ остаётся запрещённым и после ADR-214: возится ровно
        `.claude/rules`, а не каталог сессионного состояния вокруг него.
        """
        for forbidden in ("docs", "nimbalyst-local", ".claude", "KANBAN.json"):
            self.assertNotIn(forbidden, _code_paths())

    def test_every_synced_path_actually_exists(self):
        """Опечатка в списке молча ничего не возит — и это не видно ни по одному пульсу."""
        root = _SCRIPT.resolve().parents[1]
        for p in _code_paths():
            self.assertTrue((root / p).exists(), f"{p} нет в дереве — опечатка в списке")


class TestTheRuleIsWrittenDown(unittest.TestCase):
    """Исключение обязано быть объяснено там же, где сделано.

    Иначе следующий читатель увидит не-код в списке «CODE ONLY» и уберёт его
    как явную ошибку — вернув аварию 08.08 (или 02.09).
    """

    def test_the_architecture_exception_is_explained_in_the_script(self):
        text = _script_text()
        self.assertIn("architecture/ is a non-code exception", text)
        self.assertIn("2026-08-09", text, "решение владельца датировано")

    def test_the_instructions_exception_is_explained_in_the_script(self):
        text = _script_text()
        self.assertIn("SECOND non-code exception", text)
        self.assertIn("2026-09-02", text, "решение владельца датировано")
        self.assertIn("ADR-214", text)


class TestRetiredInstructionsAreNamed(unittest.TestCase):
    """`git checkout <ref> -- <путь>` НЕ УДАЛЯЕТ.

    Правило, снятое владельцем на origin, остаётся лежать в прод-дереве и продолжает
    управлять агентами — это ровно тот класс, ради которого написан ADR-214 (снятый
    запрет, который всё ещё исполняют). Синхронизация обязана такой файл НАЗВАТЬ:
    удалять из прод-дерева — не её право (`.claude/rules/deployment.md` §6).

    Проверка поведенческая: функция вырезается из скрипта и исполняется на настоящем
    git-репозитории-фикстуре, без сети.
    """

    @staticmethod
    def _extract_function() -> str:
        m = re.search(r"^    retired_instructions\(\) \{.*?^    \}$",
                      _script_text(), re.S | re.M)
        assert m, "функция retired_instructions пропала — сторож снят, тест обязан упасть"
        return textwrap.dedent(m.group(0))

    def _run_in_fixture(self, worktree_extra: dict[str, str]) -> list[str]:
        """origin/main несёт CLAUDE.md + .claude/rules/adapters.md; дерево — плюс extra."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            git = lambda *a: subprocess.run(("git", *a), cwd=root, check=True,
                                            capture_output=True, text=True)
            git("init", "-q")
            git("config", "user.email", "t@t"); git("config", "user.name", "t")
            (root / ".claude" / "rules").mkdir(parents=True)
            (root / "CLAUDE.md").write_text("x", encoding="utf-8")
            (root / ".claude" / "rules" / "adapters.md").write_text("y", encoding="utf-8")
            git("add", "-A"); git("commit", "-qm", "base")
            sha = git("rev-parse", "HEAD").stdout.strip()
            git("update-ref", "refs/remotes/origin/main", sha)
            for rel, body in worktree_extra.items():
                (root / rel).write_text(body, encoding="utf-8")
            out = subprocess.run(
                ["bash", "-c", self._extract_function() + "\nretired_instructions\n"],
                cwd=root, capture_output=True, text=True, check=True)
            return out.stdout.split()

    def test_a_file_origin_dropped_is_named(self):
        """Положительный контроль: правило, которого на origin нет, обязано быть названо."""
        named = self._run_in_fixture({".claude/rules/retired.md": "снятое правило"})
        self.assertEqual([".claude/rules/retired.md"], named)

    def test_a_tree_that_matches_origin_names_nothing(self):
        """Обратная сторона: тревога на верном состоянии учит не смотреть на сторожа."""
        self.assertEqual([], self._run_in_fixture({}))

    def test_the_verdict_reaches_the_status_file(self):
        """Сторож, который не доносит вердикт до потребителя, — украшение.

        Проверяется ФОРМА вызова: поле в статус-файле и передача `$RETIRED` во все
        ветки, кроме `FETCH_FAILED` (там origin не опрошен — судить нечем).
        """
        text = _script_text()
        self.assertIn('"retired_instructions": retired.split()', text)
        for verdict in ("IN_SYNC", "SNAPSHOT_FAILED", "SYNCED", "ROLLED_BACK", "CRITICAL"):
            m = re.search(rf'write_status "{verdict}".*', text)
            self.assertIsNotNone(m, f"ветка {verdict} пропала")
            self.assertIn('"$RETIRED"', m.group(0),
                          f"вердикт {verdict} пишется без списка снятых инструкций")


if __name__ == "__main__":
    unittest.main()
