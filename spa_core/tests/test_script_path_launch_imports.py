#!/usr/bin/env python3
"""Скрипт, запущенный ПО ПУТИ, обязан суметь импортировать пакет репозитория (ADR-347).

**Авария 12.09, цикл #571.** `scripts/check_owner_order_starvation.py` — сторож шага
0a-ГОЛОД — умирал на собственном импорте КАЖДЫЙ запуск:

    from spa_core.utils.observation import observed, observed_number   # строка 62
    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)                                  # строка 66

Бутстрап был НА МЕСТЕ и стоял на четыре строки НИЖЕ импорта, который он обслуживает.
Обёртка `agent_orchestrator.sh` зовёт файл по пути (`"$PYTHON" "$STARVE_PY"`), а тогда
`sys.path[0]` — каталог `scripts/`, и корень репозитория не появляется в пути ни при
каком рабочем каталоге: `cd` в корень на `sys.path` не влияет (то же самое сказано в
`.claude/rules/deployment.md` про launchd и `com.spa.source_discovery`).

**Почему замер поведенческий, а не «посмотреть, что бутстрап выше импорта».** Статически
видно только то, что автор НАПИСАЛ; бутстрап бывает в помощнике, в `try`, в ветке под
`if`, а недостача бывает закрыта переменной окружения у вызывающего. Вопрос, на который
обязан отвечать этот файл, ровно один: **запускается ли пролог, когда файл зовут так, как
его зовёт launchd** — и на него отвечает запуск, а не чтение.

**Как устроен зонд.** Из модуля берутся операторы верхнего уровня ДО первого импорта
пакета репозитория включительно, и этот пролог кладётся РЯДОМ с оригиналом, в тот же
каталог: только так `__file__` и `sys.path[0]` совпадают с тем, что увидит настоящий
скрипт. Тело функций не исполняется никогда — `main()` не зовётся. Замер 12.09: во всех
88 прологах населения встречаются только импорты, константы, строки документации и
`if`-ветки (иных видов операторов нет), поэтому исполнение пролога безопасно.
`PYTHONPATH` снимается намеренно: у обёрток его нет, и зелёный ответ, купленный
переменной окружения запускающего, был бы ответом не на тот вопрос.

**Третий исход.** Пролог, упавший НЕ на импорте пакета репо, — `unmeasured` с названной
причиной; он не складывается ни с «импортируется», ни с «не импортируется» (инв. #17).
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
_BASELINE = Path(__file__).parent / "path_launch_import_baseline.json"

#: Пакеты, живущие в корне репозитория (каталоги с `__init__.py` рядом с `scripts/`).
_PKGS = {"spa_core", "adapters"}

IMPORTS = "imports"
CANNOT = "cannot_import"
UNMEASURED = "unmeasured"


def _first_top_level_repo_import(tree: ast.Module) -> int | None:
    """Индекс первого импорта пакета репо среди операторов ВЕРХНЕГО уровня."""
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] in _PKGS for a in node.names):
                return i
        elif isinstance(node, ast.ImportFrom):
            # `level > 0` — относительный импорт: у скрипта пакета нет, это другой класс.
            if node.level == 0 and node.module and node.module.split(".")[0] in _PKGS:
                return i
    return None


def population() -> list[Path]:
    """Скрипты с импортом пакета репо на верхнем уровне модуля."""
    out = []
    for dirpath, dirnames, filenames in os.walk(_SCRIPTS):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "tests")]
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            p = Path(dirpath) / fn
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            if _first_top_level_repo_import(tree) is not None:
                out.append(p)
    return out


def probe(path: Path, sandbox: Path) -> tuple[str, str]:
    """(исход, причина) для одного скрипта, запущенного КАК ЕГО ЗОВЁТ launchd."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    idx = _first_top_level_repo_import(tree)
    assert idx is not None, path
    prologue = ast.unparse(ast.Module(body=tree.body[:idx + 1], type_ignores=[]))
    # Рядом с оригиналом — иначе `__file__` и `sys.path[0]` будут чужими, и зонд
    # ответит про свой временный каталог, а не про запуск настоящего скрипта.
    probe_file = path.parent / f"_path_launch_probe_{uuid.uuid4().hex[:10]}.py"
    probe_file.write_text(prologue, encoding="utf-8")
    try:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["SPA_DATA_DIR"] = str(sandbox / "data")   # живое data/ не трогаем
        proc = subprocess.run([sys.executable, str(probe_file)], cwd=str(sandbox),
                              env=env, capture_output=True, text=True, timeout=180)
    finally:
        probe_file.unlink(missing_ok=True)
    if proc.returncode == 0:
        return IMPORTS, ""
    tail = (proc.stderr.strip().splitlines() or ["(пусто)"])[-1]
    if "ModuleNotFoundError" in proc.stderr and any(
            f"No module named '{pkg}" in proc.stderr for pkg in _PKGS):
        return CANNOT, tail
    return UNMEASURED, tail


def _census() -> dict[str, tuple[str, str]]:
    with tempfile.TemporaryDirectory() as td:
        sandbox = Path(td)
        return {str(p.relative_to(_REPO)): probe(p, sandbox) for p in population()}


class TestPathLaunchImportRatchet(unittest.TestCase):
    """База может ТОЛЬКО уменьшаться (порядок `frozen_date_baseline.json`)."""

    @classmethod
    def setUpClass(cls):
        cls.census = _census()
        cls.baseline = set(json.loads(_BASELINE.read_text(encoding="utf-8"))
                           ["cannot_import_when_launched_by_path"])

    def test_no_new_script_breaks_when_launched_by_path(self):
        """Новый нарушитель — красный тест сразу, без права дописать его в базу."""
        broken = {p for p, (v, _) in self.census.items() if v == CANNOT}
        new = sorted(broken - self.baseline)
        self.assertEqual(new, [], (
            "скрипт(ы) не могут импортировать пакет репозитория при запуске ПО ПУТИ — "
            "ровно авария 12.09 (ADR-347). Бутстрап `sys.path` обязан стоять ВЫШЕ первого "
            "импорта пакета репо. Дописывать их в "
            f"{_BASELINE.name} ЗАПРЕЩЕНО (инв. #16): "
            + "; ".join(f"{p}: {self.census[p][1]}" for p in new)))

    def test_baseline_has_no_entries_that_are_already_fixed(self):
        """Храповик обязан ЗАТЯГИВАТЬСЯ: починил — вычеркни из базы.

        Иначе база тихо превращается в список исключений навсегда, и следующий такой
        же дефект въедет под её прикрытием.
        """
        broken = {p for p, (v, _) in self.census.items() if v == CANNOT}
        stale = sorted(self.baseline - broken - self._not_in_population())
        self.assertEqual(stale, [], (
            "эти файлы уже импортируются — вычеркни их из "
            f"{_BASELINE.name}, база может только уменьшаться: {stale}"))

    def _not_in_population(self) -> set[str]:
        """Файл мог быть удалён или перестать импортировать пакет на верхнем уровне."""
        return self.baseline - set(self.census)

    def test_unmeasured_is_reported_separately_and_never_as_clean(self):
        """Третий исход (инв. #17): пролог упал НЕ на нашем импорте.

        Такой файл не объявляется ни чистым, ни сломанным. Здесь проверяется только, что
        у каждого «не измерено» названа причина — молчаливое «не измерено» и есть та
        форма, которой fail-OPEN обычно и живёт.
        """
        for path, (verdict, why) in sorted(self.census.items()):
            if verdict == UNMEASURED:
                self.assertTrue(why.strip(), f"{path}: «не измерено» без названной причины")

    def test_the_population_is_not_empty(self):
        """Пустое население дало бы зелёный ответ, ничего не измерив.

        Ровно та подмена, из-за которой `test_unused_import_ratchet` зеленел на `0 <= 36`
        при отсутствующем `pyflakes` (цикл #465): «не измерено» тише красного теста.
        """
        self.assertGreater(len(self.census), 50,
                           f"население схлопнулось до {len(self.census)} — зонд сломан, "
                           "а не репозиторий починился")


class TestTheGuardThatBrokeIsCovered(unittest.TestCase):
    """Положительный контроль на конкретном файле, который и сломался."""

    def test_the_starvation_guard_imports_when_launched_by_path(self):
        """До правки 12.09 этот тест КРАСНЕЕТ — проверено на исходном файле.

        Именно этот скрипт обёртка зовёт по пути, и именно его смерть приехала в промпт
        цикла как «ШАГ 0a-ГОЛОД — НАХОДКА, возьми ЭТУ карточку первой».
        """
        guard = _SCRIPTS / "check_owner_order_starvation.py"
        self.assertTrue(guard.exists())
        with tempfile.TemporaryDirectory() as td:
            verdict, why = probe(guard, Path(td))
        self.assertEqual(verdict, IMPORTS,
                         f"сторож голодания снова не запускается по пути: {why}")


class TestTheProbeItselfCanFail(unittest.TestCase):
    """Зонд, который не умеет краснеть, — украшение (правило «сторож сторожей»)."""

    def _synthesise(self, body: str) -> tuple[str, str]:
        victim = _SCRIPTS / f"_path_launch_selftest_{uuid.uuid4().hex[:10]}.py"
        victim.write_text(body, encoding="utf-8")
        try:
            with tempfile.TemporaryDirectory() as td:
                return probe(victim, Path(td))
        finally:
            victim.unlink(missing_ok=True)

    def test_import_above_the_bootstrap_is_caught(self):
        """Дословная форма аварии 12.09: бутстрап есть, но НИЖЕ импорта."""
        verdict, why = self._synthesise(
            "import os, sys\n"
            "from spa_core.utils.atomic import atomic_save\n"
            "_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "sys.path.insert(0, _R)\n")
        self.assertEqual(verdict, CANNOT,
                         f"зонд НЕ УВИДЕЛ аварию, ради которой написан: {verdict}/{why}")

    def test_the_same_file_with_the_bootstrap_moved_up_is_clean(self):
        """Контроль в обратную сторону: иначе зонд краснел бы на чём угодно.

        Отличие от предыдущего — ровно порядок двух блоков, больше ничего.
        """
        verdict, why = self._synthesise(
            "import os, sys\n"
            "_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "sys.path.insert(0, _R)\n"
            "from spa_core.utils.atomic import atomic_save\n")
        self.assertEqual(verdict, IMPORTS, f"зонд краснеет на исправном файле: {why}")

    def test_the_probe_does_not_execute_function_bodies(self):
        """`main()` не зовётся: иначе зонд был бы запуском агента, а не проверкой.

        Взрыв в теле функции обязан остаться незамеченным — он не относится к вопросу
        «доступен ли пакет в момент импорта».
        """
        verdict, _ = self._synthesise(
            "import os, sys\n"
            "_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "sys.path.insert(0, _R)\n"
            "from spa_core.utils.atomic import atomic_save\n"
            "def main():\n"
            "    raise SystemExit('тело функции исполнять нельзя')\n"
            "main_result = None\n")
        self.assertEqual(verdict, IMPORTS)

    def test_a_failure_that_is_not_our_class_is_unmeasured_not_broken(self):
        """Падение по ЧУЖОЙ причине — третий исход, а не «сломан».

        Беда обязана случиться ДО импорта пакета репо: пролог на нём и обрывается, и
        оператор после него в зонд не попадает вовсе. Первая редакция теста ставила
        `raise` ПОСЛЕ импорта и потому мерила пустоту — зонд отвечал `imports`, и это
        был верный ответ на вопрос, которого автор не задавал.
        """
        verdict, why = self._synthesise(
            "import os, sys\n"
            "_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "sys.path.insert(0, _R)\n"
            "raise RuntimeError('чужая беда')\n"
            "from spa_core.utils.atomic import atomic_save\n")
        self.assertEqual(verdict, UNMEASURED, why)
        self.assertIn("RuntimeError", why)

    def test_unmeasured_is_not_silently_folded_into_broken(self):
        """И обратное направление: «не измерено» не смеет выдаваться за нашу поломку.

        Иначе храповик начнёт краснеть на чужих бедах, его научатся глушить, и он
        перестанет ловить свой класс — обычный конец сторожа с ложными срабатываниями.
        """
        verdict, _ = self._synthesise(
            "import os, sys\n"
            "import nonexistent_third_party_module_xyz\n"
            "_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "sys.path.insert(0, _R)\n"
            "from spa_core.utils.atomic import atomic_save\n")
        self.assertEqual(verdict, UNMEASURED,
                         "чужой отсутствующий модуль записан в НАШ класс")


if __name__ == "__main__":
    unittest.main()
