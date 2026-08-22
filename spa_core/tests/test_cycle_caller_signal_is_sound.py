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
import plistlib
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO / "scripts" / "run_daily_paper_cycle.sh"

#: КАНОНИЧЕСКИЙ источник настройки цикла — файл в git, а не копия в
#: `~/Library/LaunchAgents` (инв. #13). Именно этот файл ставит `install_all_agents.sh`
#: (строка `"$REPO/scripts/com.spa.daily_cycle.plist"`), поэтому проверять надо ЕГО:
#: судить о хосте тест не должен (на Linux каталога LaunchAgents нет вовсе).
_PLIST = _REPO / "scripts" / "com.spa.daily_cycle.plist"


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


class TestTheMarkerIsActuallyDeclared(unittest.TestCase):
    """Признак существует в КОДЕ обёртки — но кто его туда кладёт?

    Разбор 22.08 (решение владельца по карточке `own-33`, вариант 1): ветка классификации
    была написана 10.08 и с тех пор зелёная, а `SPA_LAUNCHD` не объявляла НИ ОДНА настройка
    запуска — ни в репо, ни на машине. То есть КАЖДЫЙ плановый запуск цикла попадал в
    `kind=ad-hoc` вместе с ручными, и вопрос «кто гоняет цикл 52 раза в сутки» оставался
    неотвечаемым ровно тем измерением, которое под него делали.

    Прежние тесты этого увидеть не могли по построению: они кормили ветку словарём,
    собранным в самом тесте. Здесь окружение берётся из ФАЙЛА настройки — и на плисте
    без метки оба теста ниже краснеют (положительный контроль — авария 10.08–22.08).
    """

    def _plist_env(self) -> dict:
        return plistlib.loads(_PLIST.read_bytes()).get("EnvironmentVariables", {})

    def test_the_plist_declares_the_marker(self):
        self.assertEqual(
            self._plist_env().get("SPA_LAUNCHD"), "1",
            "плист цикла обязан объявлять SPA_LAUNCHD=1 — иначе метку некому поставить",
        )

    def test_a_scheduled_run_with_that_plist_reads_as_scheduled(self):
        """Эффект, а не исходник: окружение ИЗ ФАЙЛА прогоняется через ту же ветку."""
        self.assertEqual(_classify(self._plist_env()), "scheduled")


if __name__ == "__main__":
    unittest.main()
