"""Каждое решение обязано быть в реестре — иначе его находят угадыванием (ADR-154).

Аудит сирот 27.08: **14 решений лежали на диске и не были упомянуты ни в одном
реестре** — ни в `docs/decisions/INDEX.md`, ни в `docs/adr/ADR_INDEX.md`. Среди них
`ADR-YL-002` («LLM запрещён в пути исполнения») и `ADR-YL-004` («Risk Scoring v2 —
только advisory») — действующие инварианты, на которые ссылается `CLAUDE.md`.

Решение вне реестра не отменено и не забыто — оно просто **недостижимо**: найти его
можно, лишь зная имя файла. Тот же механизм, из-за которого сессия в тот день трижды
сказала «этого нет» о существующем.

Два реестра — не дефект, а история: старая серия `docs/adr/` ведёт свой индекс, новая
`docs/decisions/` — свой. Проверка принимает любой из них.

Отдельно: первый замер дал «55 вне реестра», потому что искал ИМЯ ФАЙЛА, а реестры
ссылаются ПО НОМЕРУ. Настоящее число — 14. Поэтому тест сверяет номер, а не имя.
"""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DIRS = ("docs/decisions", "docs/adr")
_REGISTRIES = ("docs/decisions/INDEX.md", "docs/adr/ADR_INDEX.md")
_NUM = re.compile(r"ADR-(?:[A-Z]+-)?\d+")


def _registry_text() -> str:
    out = []
    for r in _REGISTRIES:
        p = _ROOT / r
        if p.is_file():
            out.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(out)


def _adr_files() -> list[Path]:
    out = []
    for d in _DIRS:
        p = _ROOT / d
        if p.is_dir():
            out += [f for f in p.iterdir()
                    if f.name.startswith("ADR") and f.suffix == ".md"
                    and "INDEX" not in f.name]
    return sorted(out)


class TestRegistryCoverage(unittest.TestCase):

    def test_every_adr_is_reachable_from_a_registry(self):
        """Сердце аудита: решение вне реестра находят только угадыванием."""
        text = _registry_text()
        missing = []
        for f in _adr_files():
            m = _NUM.search(f.name)
            if m and m.group(0) not in text:
                missing.append(f.name)
        self.assertEqual(missing, [], (
            f"решения вне реестров ({len(missing)}): {missing[:8]}. "
            "Внеси их в docs/decisions/INDEX.md или docs/adr/ADR_INDEX.md — "
            "иначе они недостижимы."))

    def test_the_registries_themselves_exist(self):
        """Проверка без реестра зеленела бы всегда — и ничего не значила."""
        found = [r for r in _REGISTRIES if (_ROOT / r).is_file()]
        self.assertTrue(found, "ни одного реестра решений не найдено")

    def test_matching_is_by_number_not_filename(self):
        """Положительный контроль на метод: имя файла и номер — разные вещи.

        Сверка по имени дала бы 55 ложных пропусков вместо 14 настоящих.
        """
        self.assertIsNotNone(_NUM.search("ADR-YL-002-llm-forbidden.md"))
        self.assertEqual(_NUM.search("ADR-154-contracts.md").group(0), "ADR-154")

    def test_there_are_actually_adrs_to_check(self):
        """Иначе тест зеленел бы на пустом каталоге."""
        self.assertGreater(len(_adr_files()), 50, "решения обязаны находиться на диске")


if __name__ == "__main__":
    unittest.main()
