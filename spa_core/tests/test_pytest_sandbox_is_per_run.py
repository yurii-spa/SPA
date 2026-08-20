"""Песочница состояния под pytest обязана быть СВОЕЙ на прогон, а не общей на весь хост.

Положительный контроль — авария 20.08 (карточка `inbox-pesochnitsa-testov-obschaya-na-ves-host`,
замер цикла #320 на чистом `origin/main` 5e431566c):

    $ python3 -m pytest spa_core/tests/test_owner_notify.py \
                        spa_core/tests/test_telegram_outbound_guard.py -q
    25 passed
    $ python3 -m pytest spa_core/tests/test_owner_notify.py \
                        spa_core/tests/test_telegram_outbound_guard.py -q
    5 failed, 20 passed
    E  notify_needs_owner SUPPRESSED: anti-storm: та же карточка уходила 0 мин назад
       без ответа — повтор не раньше, чем через 6ч

Второй прогон краснел не на изменённом коде, а на СОБСТВЕННЫХ записях первого: журнал
решений владельца уводился под pytest в `tempfile.gettempdir()/spa_owner_decisions_pytest.json`
— один файл на весь хост, без сброса между прогонами. Анти-шторм (окно 6 ч) стал первым
читателем этой истории, и песочница оказалась самоотравляющейся.

Почему нужен ДОЧЕРНИЙ процесс. Внутри одного прогона pytest песочница по построению одна,
поэтому «а был бы следующий прогон зелёным?» изнутри этого же прогона недоказуемо: любая
проверка мерила бы свою собственную сессию. Настоящий второй прогон — отдельный процесс с
чистым `SPA_PYTEST_SANDBOX_DIR` (именно так набор и запускают из оболочки). Тот же приём,
что в тестах эффекта: то, что видно только в проде, меряется в дочернем процессе.

Обратный контроль (тесты 5 и 6) держит вторую сторону: ВНУТРИ одного прогона анти-шторм и
разделение живого/тестового состояния обязаны работать ровно как раньше. Починка изоляции
не смеет обернуться ослаблением заслона (инвариант #16) или возвратом записей в живой `data/`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.telegram import alert_actions, owner_decisions, prefs
from spa_core.utils import pytest_sandbox

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_child(code: str, *, fresh_run: bool) -> str:
    """Выполнить `code` в дочернем python, притворяющемся прогоном pytest.

    ``fresh_run=True`` — очистить адрес песочницы, то есть это НОВЫЙ прогон набора
    (так его видит оболочка). ``False`` — дочерний процесс внутри нашего прогона.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    # Дочерний процесс обязан выглядеть как прогон под pytest — иначе модули отдадут
    # ЖИВОЙ путь, и тест начнёт мерить не то (и, хуже, писать в живое состояние).
    env["PYTEST_CURRENT_TEST"] = "test_pytest_sandbox_is_per_run.py::child (call)"
    if fresh_run:
        env.pop(pytest_sandbox.SESSION_DIR_ENV, None)
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, f"дочерний процесс упал: {res.returncode}\n{res.stderr}"
    return res.stdout.strip()


# Дочерний прогон повторяет ПОРЯДОК `notify_needs_owner`: сначала спросить анти-шторм
# (можно ли отправить), и только потом зарегистрировать отправку. Именно этот порядок
# делает второй прогон подряд красным на неисправленном модуле: он спрашивает — и
# получает отказ из-за записи ПРЕДЫДУЩЕГО прогона в общей на хост песочнице.
_CHILD_ASK_THEN_PUSH = """
import json, tempfile
from pathlib import Path
from spa_core.telegram import owner_decisions as od

card = Path(tempfile.mkdtemp()) / "own-sandbox-probe.md"
card.write_text("---\\ntitle: probe\\nstatus: needs-owner\\n---\\n\\n## Что от тебя нужно\\n1. Ответить.\\n",
                encoding="utf-8")
allowed, why = od.throttle_state(card.stem)
od.register_push(card, "probe", card.read_text(encoding="utf-8"))
print(json.dumps({"state_path": str(od._state_path()), "allowed": allowed, "why": why}))
"""


class SandboxIsPerRun(unittest.TestCase):
    """Адрес песочницы зависит от ПРОГОНА, а не от машины."""

    def test_sandbox_file_lives_in_the_run_directory(self):
        path = pytest_sandbox.sandbox_path("probe.json")
        self.assertEqual(path.parent, pytest_sandbox.session_dir())
        self.assertTrue(path.parent.is_dir(), "директория прогона обязана существовать")
        self.assertNotEqual(
            path.parent, Path(tempfile.gettempdir()),
            "песочница прямо в tempdir — это и есть общий на хост файл",
        )

    def test_sandbox_name_must_be_a_plain_filename(self):
        for bad in ("", "../escape.json", "sub/dir.json", "."):
            with self.assertRaises(ValueError):
                pytest_sandbox.sandbox_path(bad)

    def test_a_child_process_of_this_run_sees_the_SAME_sandbox(self):
        """Иначе тесты эффекта в дочернем процессе мерили бы пустоту."""
        child = _run_child(
            "from spa_core.utils.pytest_sandbox import sandbox_path;"
            " print(sandbox_path('probe.json'))",
            fresh_run=False,
        )
        self.assertEqual(child, str(pytest_sandbox.sandbox_path("probe.json")))

    def test_a_fresh_run_gets_its_OWN_sandbox(self):
        first = _run_child(
            "from spa_core.utils.pytest_sandbox import sandbox_path;"
            " print(sandbox_path('probe.json'))",
            fresh_run=True,
        )
        self.assertNotEqual(
            first, str(pytest_sandbox.sandbox_path("probe.json")),
            "новый прогон обязан получить свою директорию, иначе он наследует историю чужого",
        )

    def test_an_xdist_worker_gets_its_OWN_sandbox(self):
        """Воркеры наследуют окружение контроллера — общая песочница вернула бы дефект."""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_REPO_ROOT)
        env["PYTEST_CURRENT_TEST"] = "test_pytest_sandbox_is_per_run.py::worker (call)"
        # Контроллер уже опубликовал адрес — воркер обязан его НЕ взять.
        env[pytest_sandbox.SESSION_DIR_ENV] = str(pytest_sandbox.session_dir())
        env[pytest_sandbox.XDIST_WORKER_ENV] = "gw0"
        res = subprocess.run(
            [sys.executable, "-c",
             "from spa_core.utils.pytest_sandbox import sandbox_path;"
             " print(sandbox_path('probe.json'))"],
            cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotEqual(res.stdout.strip(),
                            str(pytest_sandbox.sandbox_path("probe.json")))
        self.assertIn("gw0", res.stdout.strip())

    def test_a_recycled_pid_does_not_inherit_someone_elses_state(self):
        """pid на macOS переиспользуются: мусор под нашим именем — не наше состояние."""
        code = """
import os, tempfile
from pathlib import Path
stale = Path(tempfile.gettempdir()) / f"spa_pytest_sandbox_{os.getpid()}"
stale.mkdir(parents=True, exist_ok=True)
(stale / "spa_owner_decisions_pytest.json").write_text('{"pushes": [{"card_id": "old"}]}',
                                                       encoding="utf-8")
from spa_core.utils.pytest_sandbox import session_dir
d = session_dir()
print((d / "spa_owner_decisions_pytest.json").exists())
"""
        self.assertEqual(_run_child(code, fresh_run=True), "False")


class AntiStormSurvivesTheFix(unittest.TestCase):
    """Заслон не ослаблен: он молчит между прогонами и работает внутри прогона."""

    def test_two_consecutive_runs_are_both_allowed_to_notify(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии 20.08 — на неисправленном модуле второй красный."""
        first = json.loads(_run_child(_CHILD_ASK_THEN_PUSH, fresh_run=True))
        second = json.loads(_run_child(_CHILD_ASK_THEN_PUSH, fresh_run=True))

        # Якорь проверки — ПОВЕДЕНИЕ, а не путь: снятая починка обязана красить именно
        # эту строку, иначе положительный контроль краснел бы на подготовке.
        self.assertTrue(first["allowed"], f"первый прогон подавлен: {first['why']}")
        self.assertTrue(
            second["allowed"],
            "второй прогон подряд подавлен записями ПЕРВОГО — ровно авария 20.08: "
            f"{second['why']}",
        )
        self.assertNotEqual(first["state_path"], second["state_path"],
                            "два прогона обязаны писать в РАЗНЫЕ журналы")

    def test_inside_ONE_run_the_anti_storm_still_suppresses(self):
        """Обратный контроль: чинили изоляцию, а не заслон (инвариант #16)."""
        card_id = "own-sandbox-reverse-control"
        state = pytest_sandbox.sandbox_path("reverse_control.json")
        card = Path(tempfile.mkdtemp()) / f"{card_id}.md"
        card.write_text("---\ntitle: probe\nstatus: needs-owner\n---\n\n"
                        "## Что от тебя нужно\n1. Ответить.\n", encoding="utf-8")

        owner_decisions.register_push(card, "probe", card.read_text(encoding="utf-8"),
                                      state_path=state)
        allowed, why = owner_decisions.throttle_state(card_id, state_path=state)

        self.assertFalse(allowed, "повтор той же карточки внутри окна обязан подавляться")
        self.assertIn("anti-storm", why)

    def test_live_state_is_still_never_touched(self):
        """Вторая сторона того же заслона: живой data/ под pytest не адресуется вовсе."""
        for resolved in (owner_decisions._state_path(),
                         alert_actions._state_path(),
                         alert_actions._beacon_path(),
                         prefs._prefs_path()):
            self.assertEqual(
                resolved.parent, pytest_sandbox.session_dir(),
                f"{resolved} обязан лежать в песочнице прогона, а не в живом дереве",
            )
            self.assertNotIn("Documents/SPA_Claude", str(resolved))

    def test_prefs_keeps_its_public_name(self):
        """`prefs.PYTEST_PREFS_FILE` читают тесты изоляции — имя обязано остаться живым."""
        self.assertEqual(prefs.PYTEST_PREFS_FILE, prefs._prefs_path())
        with self.assertRaises(AttributeError):
            prefs.NO_SUCH_ATTRIBUTE  # noqa: B018 — проверяем сам __getattr__


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
