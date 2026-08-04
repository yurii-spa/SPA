#!/usr/bin/env python3
"""Site Custodian: алерт владельцу приходит на русском ДАЖЕ так, как его зовёт CI.

Инцидент (owner-карточка 2026-08-04 «писать мне в чат простым языком»):
владельцу пришло дословно

    🛡️ SITE CUSTODIAN — 1 FAIL(s) @ 2026-08-04T08:51:55Z
      [FAIL] STALE_SNAPSHOT: snapshot as_of 2026-08-03 is 32.9h old (> 30h)

при том, что перевод (`spa_core/telegram/humanize.py`) существует с 2026-07-29 и
знает и заголовок, и код `STALE_SNAPSHOT`. Причина — не правила перевода, а то,
что перевод НИКОГДА не запускался на пути CI: workflow зовёт файл как
``python scripts/site_freshness_monitor.py``, значит ``sys.path[0]`` — каталог
``scripts/``, корня репозитория на пути нет, ``from spa_core...`` падает
``ModuleNotFoundError``, а ``except`` его глотал. Прогон 2026-08-04T08:51:36Z —
ровно тот алерт в 08:51:55Z. На Маке путь был исправен, поэтому дефект жил в CI.

Тесты ниже проверяют ЭФФЕКТ в дочернем процессе с CI-подобным ``sys.path``
(корень репозитория убран), а не текст исходника: «перевод подключён» и «перевод
реально отработал» — разные утверждения, и инцидент был про второе.

Запуск::

    python3 -m pytest spa_core/tests/test_site_custodian_alert_humanized.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
_MONITOR = _SCRIPTS / "site_freshness_monitor.py"

# Дословное тело алерта из карточки владельца (2026-08-04T08:51:55Z).
OWNER_MSG = (
    "🛡️ SITE CUSTODIAN — 1 FAIL(s) @ 2026-08-04T08:51:55Z\n"
    "  [FAIL] STALE_SNAPSHOT: snapshot as_of 2026-08-03 is 32.9h old (> 30h)"
)

# Дочерний процесс: воспроизводим условие CI (корня репозитория нет на sys.path),
# грузим монитор ПО ПУТИ и зовём его переводчик. Печатаем JSON, чтобы родитель
# отличал «контроль не сработал» от «перевод не сработал».
_CHILD = r"""
import importlib.util, json, sys

root, scripts, monitor = sys.argv[1], sys.argv[2], sys.argv[3]
msg = sys.stdin.read()

# CI-подобный путь: первым идёт каталог скрипта, корня репозитория нет вовсе.
sys.path = [scripts] + [p for p in sys.path if p not in ("", ".", root, scripts)]

out = {}
try:                       # положительный контроль: тест не должен быть пустым
    import spa_core        # noqa: F401
    out["control"] = "IMPORTABLE"      # условие инцидента НЕ воспроизведено
except ModuleNotFoundError:
    out["control"] = "NOT_IMPORTABLE"  # ровно как в CI

spec = importlib.util.spec_from_file_location("sfm_under_test", monitor)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
out["result"] = mod._humanize_body(msg)
sys.stdout.write(json.dumps(out))
"""


def _run_child(msg: str) -> dict:
    """Прогнать переводчик монитора в CI-подобном окружении. Вернуть {control,result}."""
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(_ROOT), str(_SCRIPTS), str(_MONITOR)],
        input=msg,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_ROOT),
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},  # без PYTHONPATH — как в CI
    )
    assert proc.returncode == 0, f"дочерний процесс упал: {proc.stderr[-2000:]}"
    return json.loads(proc.stdout)


class TestSiteCustodianAlertIsHumanizedInCI(unittest.TestCase):
    """Перевод обязан отработать при запуске «как в CI»."""

    def test_control_repo_root_really_absent(self):
        """Положительный контроль: в дочернем процессе `spa_core` действительно НЕ импортируется.

        Без этого весь файл был бы зелёным по ошибке — он проверял бы обычный
        импорт, а не условие инцидента.
        """
        out = _run_child(OWNER_MSG)
        self.assertEqual(
            out["control"], "NOT_IMPORTABLE",
            "условие инцидента не воспроизведено: корень репозитория оказался на sys.path",
        )

    def test_owner_message_arrives_in_russian(self):
        """Тот самый алерт владельца переводится, а не уезжает сырым английским."""
        result = _run_child(OWNER_MSG)["result"]
        self.assertIn("Сайт-сторож: нашёл проблем — 1", result)
        self.assertIn("снимок данных для сайта устарел", result)
        self.assertIn("[проблема]", result)
        # Сырые технические токены заголовка/кода до владельца больше не доходят.
        self.assertNotIn("SITE CUSTODIAN", result)
        self.assertNotIn("STALE_SNAPSHOT", result)
        self.assertNotIn("[FAIL]", result)

    def test_numbers_and_detail_survive_verbatim(self):
        """Контракт humanize: числа/порог/дата доходят до владельца без потерь.

        ИЗМЕНЕНО ЦИКЛОМ #112 — НАМЕРЕННО, с обоснованием (инвариант #16).

        Цикл #111 писал этот тест, когда detail-хвост Site Custodian ещё оставался
        английским, и закодировал контракт «данные не потеряны» английскими
        токенами `32.9h` / `30h`. Цикл #109 (карточка ВЛАДЕЛЬЦА «писать мне в чат
        простым языком») перевёл и хвост: `32.9h` → `32.9 ч`. Потеряно НЕ число —
        переведена ЕДИНИЦА, и ровно этого владелец и просил. Перевод `h` → `ч` —
        не новшество: для других семейств алертов модуль делает так с 29.07
        (см. `test_telegram_humanize.py`: `40.0h (>30h)` → `["40.0 ч", "30 ч"]`),
        #111 просто описал единственное семейство, до которого перевод не дошёл.

        Проверка НЕ ослаблена, а усилена: по-прежнему сверяется КАЖДОЕ число и
        дата исходной строки, и ДОПОЛНИТЕЛЬНО пиннится, что единица измерения
        дошла до владельца и дошла по-русски (раньше это не проверялось вовсе).
        Обоснование + запись: `docs/journal/2026-W32.md`.
        """
        result = _run_child(OWNER_MSG)["result"]
        # 1) ни одно число/дата исходника не потеряно
        for token in ("2026-08-04T08:51:55Z", "2026-08-03", "32.9", "30"):
            self.assertIn(token, result, f"потерян токен {token!r} — перевод съел данные")
        # 2) единица измерения дошла, и по-русски (этого #111 не проверял)
        for token in ("32.9 ч", "30 ч"):
            self.assertIn(token, result, f"единица потеряна или не переведена: {token!r}")

    def test_unknown_line_passes_through_verbatim(self):
        """Нераспознанная строка проходит вербатим — перевод не может «съесть» проблему."""
        msg = "🛡️ SITE CUSTODIAN — 1 FAIL(s) @ 2026-08-04T08:51:55Z\n  [FAIL] BRAND_NEW_CODE: что-то новое"
        result = _run_child(msg)["result"]
        self.assertIn("BRAND_NEW_CODE", result)
        self.assertIn("что-то новое", result)

    def test_translation_never_raises(self):
        """Fail-safe: пустой ввод не роняет алерт-путь."""
        self.assertEqual(_run_child("")["result"], "")


class TestAlertUsesTheLoader(unittest.TestCase):
    """`_alert` обязан звать загрузчик, а не голый импорт (иначе дефект вернётся)."""

    def test_alert_calls_humanize_loader(self):
        src = _MONITOR.read_text(encoding="utf-8")
        head, _, alert_src = src.partition("def _alert(report):")
        self.assertTrue(alert_src, "в мониторе не найден _alert")
        self.assertIn("_humanize_body(msg)", alert_src)
        # Голый `from spa_core...` внутри _alert — это ровно то, что молча не работало.
        self.assertNotIn("from spa_core.telegram.humanize import", alert_src)

    def test_loader_does_not_mutate_sys_path(self):
        """Лестница доставки не должна измениться: sys.path не трогаем (см. докстринг загрузчика)."""
        src = _MONITOR.read_text(encoding="utf-8")
        _, _, loader = src.partition("def _humanize_body(msg):")
        loader = loader.partition("def _alert(report):")[0]
        self.assertTrue(loader, "в мониторе не найден _humanize_body")
        self.assertNotIn("sys.path.insert", loader)
        self.assertNotIn("sys.path.append", loader)


if __name__ == "__main__":
    unittest.main(verbosity=2)
