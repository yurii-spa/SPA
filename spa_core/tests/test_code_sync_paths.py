"""Список синхронизируемых каталогов — контракт, а не деталь реализации.

Две аварии стоят за каждой половиной этого теста.

**Чего в списке не хватало.** `architecture/manifest.json` хранит решения владельца
по ~90 фоновым агентам, и ежечасный сторож сверяет с ним то, что реально крутится.
Файл не возил никто: синхронизация знала только `spa_core/`, `scripts/`, `tests/`.
Машина пересобирала конституцию из своей старой копии — 2026-08-08 четверо только
что одобренных владельцем агентов были объявлены четырьмя «КРИТИЧНО», и автомат
завёл владельцу четыре карточки. Ложная тревога дорога не сама по себе: она учит
не смотреть на сторожа.

**Чего в списке быть не должно никогда.** `data/` — живой трек. Синхронизация кода
его не касается (`.claude/rules/deployment.md` §4); один `git checkout` поверх него
уже стоил постоянной дыры в треке.

Тест читает сам скрипт, а не повторяет список: копия контракта рядом с контрактом
разойдётся с ним при первой же правке.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "code_sync_from_origin.sh"


def _code_paths() -> list[str]:
    m = re.search(r"CODE_PATHS=\(([^)]*)\)", _SCRIPT.read_text(encoding="utf-8"))
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

    def test_data_is_NEVER_synced(self):
        """Сторона, где ошибка стоит трека целиком."""
        self.assertNotIn("data", _code_paths(),
                         "живой трек синхронизацией кода не перезаписывается — никогда")

    def test_owner_queues_and_docs_stay_out(self):
        """Очереди и документы живут своей жизнью; checkout поверх них теряет работу."""
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
    как явную ошибку — вернув аварию 08.08.
    """

    def test_the_exception_is_explained_in_the_script(self):
        text = _SCRIPT.read_text(encoding="utf-8")
        self.assertIn("architecture/ is the ONE non-code exception", text)
        self.assertIn("2026-08-09", text, "решение владельца датировано")


if __name__ == "__main__":
    unittest.main()
