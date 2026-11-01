"""Положительный контроль ПРОБЫ `adr_title_gate_refuses_a_fat_register` (ADR-889).

`.claude/rules/acceptance.md` §3: новая проба регистрируется только с тестом, где она
**зелена на целом контуре** и **красна на КАЖДОМ порванном звене** — с названным
звеном, и где она **НЕ проходит подстрокой** (ADR-333). Проба, никогда не видевшая
настоящей поломки, есть украшение.

Звенья здесь настоящие: каждая сцена — ОДНОРАЗОВОЕ ДЕРЕВО с копией гейта доставки
(`push_to_github.py`), у которой снята ровно одна половина, и проба гоняется на нём
через свой параметр `repo_root`. Живое дерево не трогается ни одной сценой.

**Почему сцена — настоящий git-репозиторий.** Проба берёт байты аварии из объектной
базы (`git cat-file blob f404cfbd6…`), и выдумать их нельзя. Сцена поэтому делает
`git init -b main` (имя ветки — ВХОД сцены, а не свойство хоста:
`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ в тестах») и записывает блоб
`git hash-object -w`. Содержимое адресует блоб само, поэтому sha в сцене выходит тот
же, что в живой истории, — и это проверяется вслух, а не предполагается.

ТРЕТИЙ ИСХОД проверяется ОТДЕЛЬНО (инв. #17): дерева без пушера и дерева без блоба
аварии обязаны дать `unmeasured`, а НЕ «не выполнено» — иначе «прибора нет» стало бы
неотличимо от «прибор врёт», и починка выбиралась бы вслепую.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES, SATISFIED,
                                                 UNMEASURED)

_REPO = Path(__file__).resolve().parent.parent.parent
_PROBE = PROBES["adr_title_gate_refuses_a_fat_register"]
_PUSHER = "push_to_github.py"
_BATCH = "push_to_github_batch.py"
_REGISTER = Path("docs") / "decisions" / "INDEX.md"

#: Тот же блоб, что объявлен в самой пробе. Литерал здесь НАМЕРЕННО: сцена,
#: взявшая его у проверяемого кода, сверяла бы его сам с собой.
INCIDENT_BLOB = "f404cfbd6dfe0134592f9165f26b1e779b21b876"


class Unmeasured(AssertionError):
    """Предпосылка сцены НЕ ОБЕСПЕЧЕНА — громкий отказ, а не скип."""


def _incident_bytes() -> bytes:
    out = subprocess.run(["git", "cat-file", "blob", INCIDENT_BLOB],
                         cwd=_REPO, capture_output=True, timeout=120)
    if out.returncode != 0:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: блоба {INCIDENT_BLOB[:12]} нет в объектной базе "
            f"{_REPO} — предпосылка ХАРНЕССА (`fetch-depth: 0`), а не предмет "
            f"теста: {out.stderr.decode('utf-8', 'replace').strip()}")
    return out.stdout


class _Scene:
    """Одноразовое дерево с ОДНИМ порванным звеном. Живое дерево не трогается."""

    def __init__(self, test: unittest.TestCase, *, swap=None, swap_batch=None,
                 drop_pusher=False, drop_parser=False, drop_blob=False,
                 register_text=None):
        self.root = Path(tempfile.mkdtemp(prefix="spa_c1004_title_gate_"))
        test.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        # git-окружение — ВХОД сцены: имя ветки объявлено, а не унаследовано.
        subprocess.run(["git", "init", "-b", "main", "-q", str(self.root)],
                       check=True, capture_output=True, timeout=120)
        if not drop_blob:
            written = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"], cwd=self.root,
                input=_incident_bytes(), capture_output=True, timeout=120)
            if written.returncode != 0:
                raise Unmeasured(
                    f"НЕ ИЗМЕРЕНО: блоб аварии не записан в сцену "
                    f"({written.stderr.decode('utf-8', 'replace').strip()})")
            got = written.stdout.decode().strip()
            if got != INCIDENT_BLOB:
                raise Unmeasured(
                    f"НЕ ИЗМЕРЕНО: блоб сцены {got[:12]} ≠ {INCIDENT_BLOB[:12]} — "
                    f"сцена несёт НЕ байты аварии, и судить по ней нельзя")

        if not drop_pusher:
            self._copy(_PUSHER, swap)
            self._copy(_BATCH, swap_batch)
        if not drop_parser:
            os.symlink(_REPO / "scripts", self.root / "scripts")
        os.symlink(_REPO / "spa_core", self.root / "spa_core")

        target = self.root / _REGISTER
        target.parent.mkdir(parents=True, exist_ok=True)
        if register_text is None:
            register_text = (_REPO / _REGISTER).read_text(encoding="utf-8")
        target.write_text(register_text, encoding="utf-8")

    def _copy(self, rel: str, swap) -> None:
        src = (_REPO / rel).read_text(encoding="utf-8")
        if swap is not None:
            old, new = swap
            if src.count(old) != 1:
                raise Unmeasured(
                    f"НЕ ИЗМЕРЕНО: якорь звена найден в {rel} "
                    f"{src.count(old)} раз(а), а не ровно один — сцена НЕ "
                    f"ОБЕСПЕЧЕНА, и судить по ней о пробе нельзя")
            src = src.replace(old, new, 1)
        (self.root / rel).write_text(src, encoding="utf-8")

    def verdict(self):
        return _PROBE(None, repo_root=str(self.root))


class TheProbeIsGreenOnTheWholeContour(unittest.TestCase):
    """Целый контур — ЖИВОЕ дерево; зелёный на копии не есть зелёный здесь."""

    def test_the_real_tree_satisfies_the_probe(self):
        status, detail = _PROBE(None)
        self.assertEqual(status, SATISFIED, detail)
        self.assertIn("ОТКЛОНЕНЫ кодом 16", detail)
        self.assertIn("обеих дверей", detail)

    def test_an_untouched_scene_is_green_too_so_the_scenes_are_fair(self):
        """Обратная половина: копия БЕЗ правки обязана быть зелёной, иначе каждая
        красная сцена ниже доказывала бы лишь то, что сцена не работает."""
        status, detail = _Scene(self).verdict()
        self.assertEqual(status, SATISFIED, detail)


class TheProbeIsRedOnEveryBrokenLink(unittest.TestCase):
    """Каждая сцена — своё звено, и у каждого отказа СВОИ слова."""

    def test_the_gate_does_not_exist_at_all(self):
        """Звено: гейта нет. Это состояние `main` до ADR-889."""
        status, detail = _Scene(self, swap=(
            "def enforce_delivery_adr_titles(",
            "def _enforce_delivery_adr_titles_renamed(")).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("enforce_delivery_adr_titles", detail)

    def test_the_live_register_still_carries_a_fat_row(self):
        """Звено: СОСТОЯНИЕ не убрано — ровно замер ДО работы цикла #1004."""
        live = (_REPO / _REGISTER).read_text(encoding="utf-8")
        fat_row = (f"| ADR-999 | {'я' * 400} | Accepted | "
                   f"[ADR-999](ADR-999-x.md) |\n")
        status, detail = _Scene(self, register_text=live + fat_row).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("не проходит свой же гейт", detail)

    def test_the_gate_lets_the_incident_bytes_through(self):
        """Звено: гейт ЕСТЬ, прозу несёт целиком — и НЕ отказывает.

        Это же и проверка «проба НЕ проходит подстрокой» (ADR-333): все слова
        отказа остаются в файле дословно, снято только само ВОЗБУЖДЕНИЕ.
        """
        status, detail = _Scene(self, swap=(
            '        raise DeliveredAdrTitleIsFat(',
            '        _ = DeliveredAdrTitleIsFat(')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("гейт ПРОПУСТИЛ", detail)
        self.assertIn("ТОЛСТАЯ названа, но отказа НЕТ", detail)

    def test_the_refusal_names_no_number_and_no_length(self):
        """Звено: отказ есть, но МЕСТА в нём нет — искать строку глазами."""
        status, detail = _Scene(self, swap=(
            '''        names = "; ".join(
            f"ADR-{f['key']} ({f['chars']} символов, строка {f['row']})"
            for v in offenders for f in v["fat"])''',
            '        names = "строки реестра"')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("не назвал ADR-", detail)

    def test_the_refusal_names_no_repair_command(self):
        """Звено: отказ не называет выхода — учит обходить себя."""
        status, detail = _Scene(self, swap=(
            '''            f"Что делать: `python3 scripts/adr_number.py titles --write` — "''',
            '            f"Что делать: разобраться. "')).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("не назвал команду починки", detail)

    def test_the_second_delivery_door_does_not_call_the_gate(self):
        """Звено: дословный класс ADR-145 — блок в одной двери, вторая везёт."""
        status, detail = _Scene(self, swap_batch=(
            "        enforce_delivery_adr_titles(all_files, allow=allow_fat_title,",
            "        _skip_the_gate(all_files, allow=allow_fat_title,")).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("push_to_github_batch.py", detail)
        self.assertIn("не зовёт", detail)

    def test_the_gate_is_called_before_the_pin(self):
        """Звено: порядок. До пина гейт судил бы байты, про которые неизвестно."""
        status, detail = _Scene(self, swap=(
            "    try:\n        pin_delivery_bytes(all_files, allow_drift=allow_bytes_drift)",
            "    try:\n        enforce_delivery_adr_titles(all_files, "
            "allow=allow_fat_title)\n        pin_delivery_bytes("
            "all_files, allow_drift=allow_bytes_drift)")).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("ДО пина", detail)

    def test_the_exit_code_collides_with_a_neighbour(self):
        """Звено: свой код. Совпади он с соседом — лечили бы не ту болезнь."""
        status, detail = _Scene(self, swap=(
            "FAT_ADR_TITLE_EXIT = 16", "FAT_ADR_TITLE_EXIT = 15")).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("совпал с кодом соседнего интерлока", detail)


class TheThirdOutcomeIsItsOwnAnswer(unittest.TestCase):
    """«Прибора нет» ≠ «прибор врёт» (инв. #17): иначе починка выбирается вслепую."""

    def test_a_tree_without_the_pusher_is_unmeasured(self):
        status, detail = _Scene(self, drop_pusher=True).verdict()
        self.assertEqual(status, UNMEASURED, detail)
        self.assertIn("НЕ ИЗМЕРЕН", detail)

    def test_a_tree_without_the_incident_blob_is_unmeasured(self):
        """Глубина клона — вход ХАРНЕССА, и проба обязана это НАЗВАТЬ."""
        status, detail = _Scene(self, drop_blob=True).verdict()
        self.assertEqual(status, UNMEASURED, detail)
        self.assertIn("fetch-depth", detail)

    def test_a_live_register_too_small_to_be_the_register_is_not_a_pass(self):
        """Звено числа строк — дыра, найденная мутацией №21.

        «Толстых нет» у реестра из ОДНОЙ строки ничего не значит: так отвечал бы и
        сломанный разбор формы. Без этой сцены порог 500 можно было снять, не
        изменив ни одного вердикта.
        """
        tiny = ("# ADR INDEX\n\n| ADR | Заголовок | Статус | Файл |\n"
                "|---|---|---|---|\n"
                "| ADR-001 | Короткий | Accepted | [ADR-001](ADR-001-x.md) |\n")
        status, detail = _Scene(self, register_text=tiny).verdict()
        self.assertEqual(status, NOT_SATISFIED, detail)
        self.assertIn("столько не бывает", detail)

    def test_a_tree_without_the_single_parsing_door_is_unmeasured(self):
        """Прибора разбора нет ⇒ `unmeasured`, даже на ЧИСТОМ реестре.

        Самое опасное место класса: fail-OPEN здесь тише красного теста, потому
        что вердикт «чисто» выглядит как ответ.
        """
        status, detail = _Scene(self, drop_parser=True).verdict()
        self.assertEqual(status, UNMEASURED, detail)
        self.assertIn("adr_number.py", detail)


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
