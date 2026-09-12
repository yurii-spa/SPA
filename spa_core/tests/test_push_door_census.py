"""Положительные контроли переписи дверей доставки (`scripts/push_door_census.py`).

Каждый тест воспроизводит НАСТОЯЩУЮ ошибку, сделанную при исполнении заказа #571, —
либо ошибку самого заказа, либо ошибку прибора, написанного ему в ответ. Проверка,
никогда не видевшая настоящей поломки, — украшение (.claude/rules/deployment.md).

Пять из них — про один и тот же класс: ПОДСТРОКА ВМЕСТО ЗАМЕРА. Он оправдал ровно ту
дверь, ради которой перепись писалась, и сделал это трижды подряд уже внутри прибора.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_push_door_census", _ROOT / "scripts" / "push_door_census.py"
)
census_mod = importlib.util.module_from_spec(_spec)
sys.modules["_push_door_census"] = census_mod
_spec.loader.exec_module(census_mod)


CANON = '''
def guard_overwrite(path, base):
    return None

def build_entries(files):
    guard_overwrite(files, None)
    return []

def batch_push(pat, files, message):
    return build_entries(files)

def push_file(pat, path, message):
    guard_overwrite(path, None)
    import urllib.request
    urllib.request.urlopen("https://api.github.com/repos/x/y/contents/" + path)

def main():
    push_file(None, None, None)
'''


def _tree(tmp: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp


class DoorCensusControls(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "push_to_github.py").write_text(CANON, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _row(self, result, name):
        for r in result["doors"]:
            if Path(r["door"]).name == name and Path(r["door"]).parent.name != "scripts":
                return r
        for r in result["doors"]:
            if Path(r["door"]).name == name:
                return r
        self.fail(f"дверь {name} не попала в перепись")

    # ── A. ПЕРЕ-ЭКСПОРТ ≠ ВЫЗОВ ────────────────────────────────────────────────
    def test_reexported_guard_is_not_a_call_but_delegation_still_closes_the_door(self):
        """Ошибка ПОСЫЛКИ заказа #571: `grep -c guard_overwrite` дал 1 и был прочитан
        как «страж зовётся», хотя это присваивание. Обратная сторона: дверь всё равно
        закрыта — через `batch_push`. Замер обязан сказать обе вещи сразу."""
        _tree(self.root, {"push_batch.py": (
            "import importlib.util as ilu\n"
            "_spec = ilu.spec_from_file_location('c', 'push_to_github.py')\n"
            "_root = ilu.module_from_spec(_spec)\n"
            "guard_overwrite = _root.guard_overwrite\n"
            "batch_push = _root.batch_push\n"
            "def main():\n    batch_push(None, [], 'm')\n"
        )})
        row = self._row(census_mod.census(self.root), "push_batch.py")
        self.assertEqual(row["direct_guard_calls"], 0, "вызовов стража в файле нет")
        self.assertEqual(row["reexported_guard_names"], ["guard_overwrite"])
        self.assertTrue(row["guarded"], "но путь записи стражем ЗАКРЫТ — делегированием")

    # ── C. ФАЙЛ-АРГУМЕНТ ≠ ЗАПУСКАЮЩИЙ ────────────────────────────────────────
    def test_door_passed_as_a_file_argument_is_cargo_not_a_launcher(self):
        """`scripts/push_all_session.sh` содержит строку `.../auto_push.py`, но это
        элемент списка `--files` у ДРУГОГО пушера. Текстовый поиск «кто упоминает
        дверь» объявил бы этот скрипт её запускающим."""
        _tree(self.root, {
            "push_dead.py": "import urllib.request\n"
                            "urllib.request.urlopen('https://api.github.com/x/contents/y')\n",
            "ship.sh": ("#!/bin/bash\n"
                        "python3 push_to_github.py \\\n"
                        f"  --files {self.root}/push_dead.py \\\n"
                        f"  --message 'm'\n"),
        })
        row = self._row(census_mod.census(self.root), "push_dead.py")
        self.assertEqual(row["launchers"], [],
                         "дверь здесь ГРУЗ, а не команда — запускающих не наблюдается")
        self.assertFalse(row["finding"], "без запускающего это не находка")

    def test_door_in_command_position_is_a_launcher(self):
        """Обратный контроль к предыдущему: та же дверь, но в позиции КОМАНДЫ —
        и тогда совпадение трёх осей обязано дать находку."""
        _tree(self.root, {
            "push_dead.py": "import urllib.request\n"
                            "urllib.request.urlopen('https://api.github.com/x/contents/y')\n",
            "run.sh": f"#!/bin/bash\npython3 {self.root}/push_dead.py\n",
        })
        row = self._row(census_mod.census(self.root), "push_dead.py")
        self.assertTrue(row["launchers"], "запуск интерпретатором — наблюдаемый запускающий")
        self.assertTrue(row["writes"])
        self.assertFalse(row["guarded"])
        self.assertTrue(row["finding"], "пишет + без стража + запускается = НАХОДКА")

    # ── D. КОММЕНТАРИЙ ≠ ProgramArguments ─────────────────────────────────────
    def test_plist_comment_naming_a_door_is_not_wiring(self):
        """В шапке `scripts/com.spa.autopush.plist` написано `CLI: python3 auto_push.py`,
        а исполняется `scripts/auto_push.sh`. Читать надо исполняемое поле."""
        _tree(self.root, {
            "push_dead.py": "import urllib.request\n"
                            "urllib.request.urlopen('https://api.github.com/x/contents/y')\n",
            "agent.plist": (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0"><dict>\n'
                '  <key>Label</key><string>com.spa.autopush</string>\n'
                '  <!-- CLI: python3 push_dead.py -->\n'
                '  <key>ProgramArguments</key>\n'
                '  <array><string>/bin/bash</string><string>wrapper.sh</string></array>\n'
                '</dict></plist>\n'),
        })
        row = self._row(census_mod.census(self.root), "push_dead.py")
        self.assertEqual(row["launchers"], [],
                         "имя двери стои́т в КОММЕНТАРИИ, а исполняется другое")

    # ── самосовпадения прибора: три штуки, все в безопасную с виду сторону ────
    def test_dead_constant_naming_a_door_is_not_delegation(self):
        """Решающий случай. `auto_push.py` несёт `PUSH_SCRIPT = SPA_DIR / "push_to_github.py"`
        и НИ РАЗУ её не использует, а единственный `subprocess.run` зовёт Keychain.
        Прибор на подстроке объявил эту дверь закрытой стражем — то есть оправдал
        ЕДИНСТВЕННУЮ незакрытую дверь, ради которой перепись и писалась."""
        _tree(self.root, {"push_dead.py": (
            "import subprocess, urllib.request\n"
            "PUSH_SCRIPT = 'push_to_github.py'\n"   # присвоена и НЕ используется
            "def get_pat():\n"
            "    return subprocess.run(['security', 'find-generic-password'])\n"
            "def go():\n"
            "    urllib.request.urlopen('https://api.github.com/x/contents/y')\n"
        )})
        row = self._row(census_mod.census(self.root), "push_dead.py")
        self.assertEqual(row["spawns"], [],
                         "мёртвая константа делегированием НЕ является")
        self.assertFalse(row["guarded"], "дверь обязана остаться НЕЗАКРЫТОЙ")
        self.assertTrue(row["writes_directly"])

    def test_real_subprocess_delegation_is_detected_through_a_chain_of_bindings(self):
        """Обратный контроль: настоящее делегирование через цепочку связываний
        (`_BATCH = root / "..."` → `cmd = [exe, str(_BATCH)]` → `subprocess.run(cmd)`).
        Один проход по связываниям потерял бы обе делегирующие двери."""
        _tree(self.root, {
            "push_batch.py": (
                "import importlib.util as ilu\n"
                "_spec = ilu.spec_from_file_location('c', 'push_to_github.py')\n"
                "_root = ilu.module_from_spec(_spec)\n"
                "batch_push = _root.batch_push\n"
                "def main():\n    batch_push(None, [], 'm')\n"),
            "push_site.py": (
                "import subprocess, sys\n"
                "from pathlib import Path\n"
                "_REPO = Path('.')\n"
                "_BATCH = _REPO / 'push_batch.py'\n"
                "def main():\n"
                "    cmd = [sys.executable, str(_BATCH), '--files']\n"
                "    subprocess.run(cmd)\n"),
        })
        row = self._row(census_mod.census(self.root), "push_site.py")
        self.assertTrue(any("push_batch.py" in s for s in row["spawns"]),
                        "цепочка связываний обязана довести имя двери до вызова")
        self.assertTrue(row["guarded"], "страж за подпроцессом закрывает и зовущую дверь")

    def test_instrument_does_not_match_its_own_literals(self):
        """Прибор трижды поймал СВОИ литералы: regex эндпоинта, слово `subprocess` и
        строку `spec_from_file_location` — каждый раз в собственном исходнике. Файл,
        который лишь ГОВОРИТ об эндпоинтах, дверью не является."""
        _tree(self.root, {"push_talks.py": (
            'WRITE = "/contents/|git/refs"\n'
            'NOTE = "subprocess"\n'
            'HOW = "spec_from_file_location"\n'
            "def main():\n    return WRITE, NOTE, HOW\n"
        )})
        row = self._row(census_mod.census(self.root), "push_talks.py")
        self.assertFalse(row["writes"], "разговор об эндпоинте записью не является")
        self.assertEqual(row["spawns"], [])

    def test_a_launcher_in_another_sessions_worktree_is_out_of_scope(self):
        """Замер 12.09 на прод-дереве: в `.claude/worktrees/` лежат ДВА plist-а времён
        до ADR-032, зовущие `auto_push.py` в `ProgramArguments`. Ни один не установлен
        (`~/Library/LaunchAgents` зовёт `scripts/auto_push.sh`) и ни один не
        доставляется — это рабочие копии ЧУЖИХ сессий на давних ревизиях.

        Засчитать их запускающими значит вынести приговор о ДРУГОМ дереве. Исключение
        обязано быть НАЗВАНО числом, а не молчать."""
        plist = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            '  <key>ProgramArguments</key>\n'
            f'  <array><string>python3</string><string>{self.root}/push_dead.py</string></array>\n'
            '</dict></plist>\n')
        _tree(self.root, {
            "push_dead.py": "import urllib.request\n"
                            "urllib.request.urlopen('https://api.github.com/x/contents/y')\n",
            ".claude/worktrees/old-copy/agent.plist": plist,
        })
        result = census_mod.census(self.root)
        row = self._row(result, "push_dead.py")
        self.assertEqual(row["launchers"], [], "чужой worktree — не поверхность доставки")
        self.assertFalse(row["finding"])
        self.assertGreater(result["skipped_outside_delivery_surface"], 0,
                           "пропуск обязан быть НАЗВАН числом, а не молчать")

        # обратный контроль: ТОТ ЖЕ plist в самом дереве — находка
        _tree(self.root, {"agent.plist": plist})
        row = self._row(census_mod.census(self.root), "push_dead.py")
        self.assertTrue(row["launchers"], "в своём дереве тот же plist — запускающий")
        self.assertTrue(row["finding"])

    # ── третий исход ──────────────────────────────────────────────────────────
    def test_missing_canonical_module_is_unmeasured_not_clean(self):
        """«Не измерено» никогда не выдаётся за «чисто» (инвариант #17)."""
        (self.root / "push_to_github.py").unlink()
        with self.assertRaises(census_mod.Unmeasured):
            census_mod.census(self.root)

    def test_missing_root_is_unmeasured(self):
        with self.assertRaises(census_mod.Unmeasured):
            census_mod.census(self.root / "нет-такого-каталога")

    def test_unparsable_door_is_unmeasured_not_skipped(self):
        """Неразобранный файл обязан ронять замер ГРОМКО, а не выпадать из населения."""
        _tree(self.root, {"push_broken.py": "def main(:\n    pass\n"})
        with self.assertRaises(census_mod.Unmeasured):
            census_mod.census(self.root)

    def test_exit_code_1_only_on_a_real_finding(self):
        """Код возврата — часть контракта: 1 только при совпадении ТРЁХ осей."""
        _tree(self.root, {
            "push_dead.py": "import urllib.request\n"
                            "urllib.request.urlopen('https://api.github.com/x/contents/y')\n",
        })
        self.assertEqual(census_mod.main(["--root", str(self.root)]), 0,
                         "без запускающего — не находка")
        (self.root / "run.sh").write_text(
            f"#!/bin/bash\npython3 {self.root}/push_dead.py\n", encoding="utf-8")
        self.assertEqual(census_mod.main(["--root", str(self.root)]), 1,
                         "появился запускающий — находка")


if __name__ == "__main__":
    unittest.main()
