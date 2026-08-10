"""Признак «кто запустил цикл» обязан отличать расписание от сессии.

Первая версия (09.08) судила по родителю: `ppid`/`comm`. Замер 10.08 показал, что это
неверно: за сутки 51 запись, ВСЕ с `ppid=1` и `name=launchd` — и вывод «значит
расписание» оказался ложным. `ppid=1` так же выглядит у ОСИРОТЕВШЕГО процесса: родитель
умер, ядро переподвесило потомка к pid 1. Сессия, запустившая цикл и завершившаяся,
неотличима от расписания.

Проверка отвечала на «кто мой родитель СЕЙЧАС», а читалась как «кто меня запустил» —
класс, который проект закрывает с #29, и здесь он был произведён при постройке измерения
под решение владельца.

Теперь признак — метка ОКРУЖЕНИЯ. Их две, и вторая существует ради проверяемости:
`XPC_SERVICE_NAME` ставит launchd, но подменить её в тесте нельзя — процесс падает с
SIGABRT (замерено). Признак, который невозможно проверить, — признак, которому нельзя
доверять, поэтому рядом стоит `SPA_LAUNCHD=1` из плиста.
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

_WRAPPER = Path(__file__).resolve().parents[2] / "scripts" / "run_daily_paper_cycle.sh"


def _classify(env: dict) -> str:
    """Гоняет ТУ ЖЕ ветку, что в обёртке, вырезанную дословно."""
    text = _WRAPPER.read_text(encoding="utf-8")
    start = text.index('if [ "${SPA_LAUNCHD:-}" = "1" ]')
    end = text.index("fi", start) + 2
    script = text[start:end] + '\nprintf "%s" "$CALLER_KIND"'
    base = {k: v for k, v in os.environ.items()
            if k not in ("SPA_LAUNCHD", "XPC_SERVICE_NAME")}
    base.update(env)
    return subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, env=base).stdout


class TestCallerSignal(unittest.TestCase):

    def test_a_session_is_ad_hoc(self):
        """Сердце дефекта: раньше сессия-сирота выглядела как расписание."""
        self.assertEqual(_classify({}), "ad-hoc")

    def test_the_plist_marker_means_scheduled(self):
        self.assertEqual(_classify({"SPA_LAUNCHD": "1"}), "scheduled")

    def test_a_wrong_marker_value_is_not_scheduled(self):
        """Признак — точное значение, а не «переменная существует»."""
        self.assertEqual(_classify({"SPA_LAUNCHD": "0"}), "ad-hoc")


class TestTheOldSignalIsGone(unittest.TestCase):
    """Родитель больше не определяет вердикт — только справочно."""

    def test_the_verdict_no_longer_depends_on_ppid(self):
        text = _WRAPPER.read_text(encoding="utf-8")
        verdict = text[text.index('if [ "${SPA_LAUNCHD:-}" = "1" ]'):]
        verdict = verdict[:verdict.index("fi") + 2]
        self.assertNotIn("CALLER_NAME", verdict,
                         "имя родителя не может решать, кто запустил")

    def test_ppid_is_still_logged_as_reference(self):
        """Убирать сведения не надо — надо перестать делать по ним вывод."""
        self.assertIn("ppid=$PPID", _WRAPPER.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
