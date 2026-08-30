"""Ни один агент флота не должен слушать сеть, если ему туда не надо.

Авария 30.08: `com.spa.dashboard` запускал `python -m http.server 8767 --directory
<корень репо>` БЕЗ `--bind`. Умолчание `http.server` — все интерфейсы, поэтому агент
раздавал корень репозитория всей локальной сети. В листинге каталога были `.git/`
и `.github_pat`; режим файла 600 не защищает — сервер работает от того же
пользователя и честно отдаёт файл по HTTP. Соседи по флоту слушали петлю (api 8765,
кабинет 8766), этот — нет. Единственный потребитель (`self_heal.py`) стучится в
`http://127.0.0.1:8767/`, то есть привязка к петле ничего не ломает.

Проверка идёт по ОБЁРТКАМ, из которых launchd реально запускает агентов, а не по
готовому процессу: тест обязан краснеть и на машине, где агент сейчас не запущен.
"""
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
# Модули stdlib, которые по умолчанию слушают ВСЕ интерфейсы.
_LISTENERS = ("http.server", "SimpleHTTPServer")


def _wrappers_starting_a_listener():
    found = []
    if not _SCRIPTS.is_dir():
        return found
    for f in sorted(_SCRIPTS.glob("agent_*.sh")):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        # только строки запуска, не комментарии
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if any(m in stripped for m in _LISTENERS):
                found.append((f, stripped))
                break
    return found


class TestAgentServersBindLoopback(unittest.TestCase):

    def test_every_stdlib_server_binds_loopback(self):
        offenders = []
        for f, line in _wrappers_starting_a_listener():
            if not re.search(r"--bind\s+127\.0\.0\.1\b", line):
                offenders.append(f.name)
        self.assertEqual(
            offenders, [],
            "обёртки поднимают stdlib-сервер без `--bind 127.0.0.1` — он будет "
            f"слушать ВСЕ интерфейсы: {offenders}")

    def test_the_check_is_not_vacuous(self):
        """Контроль на украшение: если ни одной такой обёртки не нашлось,
        предыдущий тест зелен ни о чём."""
        self.assertTrue(
            _wrappers_starting_a_listener(),
            "не найдено ни одной обёртки со stdlib-сервером — проверка выше "
            "проходит вхолостую, а значит сторож стал украшением")


if __name__ == "__main__":
    unittest.main()
