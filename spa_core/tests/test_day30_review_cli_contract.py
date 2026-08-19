"""Команда, которой мы заменили удалённую обёртку, обязана РАБОТАТЬ.

Цикл #301, пункт 2 карточки `inbox-sem-skriptov-vskrytyh-strogim-skanerom-r`.

`scripts/day30_review.py` списан: 23 строки `sys.path`-шима над
`spa_core.riskwire.day30_review`, у которого свой `argparse` и свой `__main__`.
Вызывающего у обёртки не было ни одного (за это она и лежала в базе храповика
`unwired_scripts_baseline.json`, раздел `revealed_by_stricter_detector`), а её
собственный `--help` печатал usage ЧУЖОГО имени — `python3 -m
spa_core.riskwire.day30_review`. Перед удалением замерено: оба входа дают
байт-в-байт один и тот же документ (10 156 байт, расходится только
`generated_at`), оба кода возврата 0, ни один ничего не пишет.

**Почему это ТЕСТ, а не строка в журнале.** Удаление кода, у которого «всё равно
нет вызывающего», в этом проекте уже оборачивалось тем, что замена не работала
там, где работал удалённый (цикл #111: перевод алертов НИКОГДА не запускался в
CI, потому что `sys.path[0]` — каталог скрипта, а не корень репо; ровно эту
разницу обёртка и закрывала руками). Поэтому здесь закреплён не факт удаления, а
**достижимость замены** — и обе её границы названы честно, включая ту, где
замена НЕ работает.

Проверки — в ДОЧЕРНЕМ процессе: `sys.path` внутри pytest уже содержит корень
репо, и импорт «изнутри» доказал бы не то, о чём вопрос (урок
`pytest diversion blinds effect tests`).
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

from spa_core.tests._unwired import code_without_comments, scripts_without_caller

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MODULE = "spa_core.riskwire.day30_review"
_WRAPPER = _ROOT / "scripts" / "day30_review.py"

#: Строка, которая ЗАПУСКАЕТ обёртку, а не просто называет её.
#: Именно вызов, потому что `docs/RISKWIRE_CHARTER.md` перечисляет её как ПЛАН
#: рядом с `spa_core/paper_trading/day30_review.py`, которого не существовало
#: никогда: упоминание в плане командой не является и после удаления ничего не
#: ломает, а вот `python3 scripts/day30_review.py` в plist/обёртке/workflow —
#: это мёртвый запуск, exit 2, и увидит его только владелец.
_INVOCATION = re.compile(r"(?:python3?|bash|sh)\b[^\n]*\bscripts/day30_review\.py(?![\w])")

#: Где вызов может жить так, что его исполнит машина, а не прочитает человек.
_RUNNABLE_DIRS = ("launchd", "scripts", "spa_core", ".github")
_RUNNABLE_SUFFIXES = (".sh", ".plist", ".py", ".yml", ".yaml")


def _run(args, cwd, env=None):
    return subprocess.run(
        [sys.executable, "-m", _MODULE, *args],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=180,
    )


class TestTheDocumentedCommandIsReachable(unittest.TestCase):

    def test_it_runs_from_the_repo_root(self):
        """Форма из bash-обёртки launchd: `cd $REPO && python3 -m …`."""
        r = _run(["--help"], cwd=_ROOT)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr[:600]}")
        self.assertIn("--verify", r.stdout)

    def test_it_runs_from_a_FOREIGN_cwd_when_PYTHONPATH_names_the_root(self):
        """Вторая законная форма — cron/агент из чужого каталога.

        Положительный контроль класса #111: без корня репо на пути `-m` не
        находит пакет вовсе, и молчаливого запасного пути тут нет.
        """
        env = dict(os.environ, PYTHONPATH=str(_ROOT))
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(["--help"], cwd=tmp, env=env)
        self.assertEqual(r.returncode, 0, f"stderr: {r.stderr[:600]}")

    def test_it_FAILS_from_a_foreign_cwd_without_the_root_on_the_path(self):
        """Граница названа, а не замолчана: так замена НЕ работает.

        Это и есть то единственное, что делала удалённая обёртка. Тот, кто
        заведёт агента для day-30, обязан знать: `cd` в корень или `PYTHONPATH`,
        иначе агент умрёт при первом же запуске — тихо, кодом возврата.
        """
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as tmp:
            r = _run(["--help"], cwd=tmp, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No module named", r.stderr)

    def test_usage_sends_the_reader_to_the_module_not_to_the_deleted_path(self):
        """Печатать путь, которого нет, — это доставка мёртвой инструкции."""
        r = _run(["--help"], cwd=_ROOT)
        self.assertIn(f"-m {_MODULE}", r.stdout)
        self.assertNotIn("scripts/day30_review.py", r.stdout)


class TestNothingStillLaunchesTheDeletedWrapper(unittest.TestCase):

    def test_no_machine_readable_invocation_survives(self):
        """Удаление файла считается доставленным, только если запусков не осталось.

        Судится КОД, а не текст: `code_without_comments` (тот же, которым меряет
        храповик) снимает комментарии, докстринги и сообщения человеку. Иначе
        первая же мутация показала это в лоб — вернувшаяся обёртка «нарушала»
        проверку собственным докстрингом с примерами запуска, то есть тем самым
        видом доказательства, который проект уже признал слабее вызова
        (циклы #227/#255).
        """
        offenders = []
        for d in _RUNNABLE_DIRS:
            base = _ROOT / d
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if not (p.is_file() and p.suffix in _RUNNABLE_SUFFIXES):
                    continue
                if "/tests/" in str(p):
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if _INVOCATION.search(code_without_comments(p, text)):
                    offenders.append(str(p.relative_to(_ROOT)))
        self.assertEqual(sorted(offenders), [], (
            "эти файлы запускают удалённую обёртку scripts/day30_review.py — "
            f"перевести на `python3 -m {_MODULE}`: {sorted(offenders)}"))

    def test_if_the_wrapper_ever_returns_it_returns_WIRED(self):
        """Не «никогда больше», а «только с вызывающим».

        Запрет навсегда был бы враньём: день, когда для day-30 заведут агента,
        может законно потребовать путь-файл. Недопустимо другое — вернуть тот же
        шим, которого снова никто не зовёт, и снова дописать имя в базу
        храповика (это запрещает `test_unwired_scripts_ratchet`).
        """
        if not _WRAPPER.exists():
            return
        self.assertNotIn("day30_review", scripts_without_caller(_ROOT), (
            "scripts/day30_review.py вернулся, и вызывающего у него снова нет: "
            "либо подключить (plist / обёртка / вызов из цикла), либо не "
            "возвращать — база храповика для этого не место"))


if __name__ == "__main__":
    unittest.main()
