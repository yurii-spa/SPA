"""Агент сторожа переходов статусов ПОДГОТОВЛЕН — решение владельца 25.08 (вариант 1).

Карточка «Сторожа переходов статусов сейчас двигают только циклы вручную —
заводить ли ему отдельного агента», ADR-141.

У сторожа не было постоянного прогона: ни расписания, ни вызывающего — его
двигали только циклы оркестратора, когда до него доходили руки. Сторож, которого
смотрят раз в сутки-двое, ловит аварию через сутки-двое, а переходы статусов
происходят десятками в день.

**Установка — за владельцем** (инвариант #12: деплой агента только через гейт и
руками владельца). Этот файл проверяет ровно то, что можно проверить ДО загрузки:
что подготовленное не развалится при первом же запуске по трём известным
причинам, каждая из которых уже случалась в этом проекте.
"""
from __future__ import annotations

import plistlib
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLIST = REPO / "launchd" / "com.spa.tracker_status_sentinel.plist"
WRAPPER = REPO / "scripts" / "agent_tracker_status_sentinel.sh"
LABEL = "com.spa.tracker_status_sentinel"


def _plist() -> dict:
    with PLIST.open("rb") as fh:
        return plistlib.load(fh)


class PreparedFilesExist(unittest.TestCase):

    def test_plist_and_wrapper_are_prepared(self):
        self.assertTrue(PLIST.is_file(), "plist не подготовлен")
        self.assertTrue(WRAPPER.is_file(), "bash-обёртка не подготовлена")

    def test_plist_parses_and_is_labelled(self):
        self.assertEqual(_plist()["Label"], LABEL)


class ThreeKnownWaysToShipADeadAgent(unittest.TestCase):
    """Каждая проверка ниже — авария, которая в этом проекте уже была."""

    def test_launchd_runs_bash_not_python_directly(self):
        """exit 78: launchd не умеет exec'ить miniconda-python напрямую.

        Программа тогда не запускается вовсе — ни лога, ни следа.
        """
        args = _plist()["ProgramArguments"]
        self.assertEqual(args[0], "/bin/bash", args)
        self.assertTrue(args[1].endswith("agent_tracker_status_sentinel.sh"), args)
        joined = " ".join(args)
        self.assertNotIn("miniconda", joined,
                         "plist зовёт python напрямую — агент не стартует (exit 78)")

    def test_wrapper_is_executable_IN_GIT(self):
        """Режим 100644 у скрипта, который запускает launchd, = агент мёртв.

        И это не видно ни по одному пульсу (`.claude/rules/deployment.md`, п. 3).
        Проверяется режим В ИНДЕКСЕ, а не на диске: на диск его можно поправить
        руками после каждого деплоя, а чинить надо на origin.
        """
        out = subprocess.run(
            ["git", "ls-files", "-s", str(WRAPPER.relative_to(REPO))],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertTrue(out, "обёртка не в индексе git")
        self.assertTrue(out.startswith("100755"),
                        f"режим обёртки в git не исполняемый: {out.split()[0]}")

    def test_logs_go_to_tmp_not_documents(self):
        """Логи в ~/Documents дают exit-78 у launchd (инвариант #12)."""
        p = _plist()
        for key in ("StandardOutPath", "StandardErrorPath"):
            with self.subTest(key=key):
                self.assertTrue(p[key].startswith("/tmp/"), p[key])


class ScheduleMatchesTheDecision(unittest.TestCase):

    def test_hourly(self):
        """Владелец выбрал «раз в час» — час записан числом, а не намерением."""
        self.assertEqual(_plist()["StartInterval"], 3600)

    def test_it_is_a_scheduled_agent_not_a_long_liver(self):
        """У долгожителя (`KeepAlive`) свои правила и своя опасность.

        Его нельзя проверять запуском (поднимется ВТОРОЙ процесс), и он держит в
        памяти код с момента старта. Этот агент — расписанный: он выходит после
        каждого прогона, поэтому доставка кода до него доходит сама.

        Проверяется ЗНАЧЕНИЕ, а не наличие ключа: `<false/>` читался как
        «сервер» и однажды уже превратил зависание расписанного агента в успех
        (`.claude/rules/deployment.md`).
        """
        self.assertFalse(bool(_plist().get("KeepAlive", False)))


class TheWrapperTargetsTheRightModule(unittest.TestCase):

    def test_it_runs_the_sentinel(self):
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("spa_core.monitoring.tracker_status_sentinel", text)
        self.assertIn("agent_template.sh", text,
                      "обёртка обязана идти через канонический шаблон")

    def test_the_module_it_names_actually_exists_and_has_an_entrypoint(self):
        """Опечатка в имени модуля = агент, который стартует и ничего не делает."""
        import importlib
        mod = importlib.import_module("spa_core.monitoring.tracker_status_sentinel")
        self.assertTrue(hasattr(mod, "main"), "у модуля нет точки входа main()")

    def test_the_sentinel_is_read_only_about_capital(self):
        """Сторож НАЗЫВАЕТ переходы; он ничего не чинит и капитал не двигает."""
        import inspect
        import spa_core.monitoring.tracker_status_sentinel as mod
        src = inspect.getsource(mod)
        for forbidden in ("spa_core.execution", "from spa_core.risk.policy import"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, src)


class InstallationIsTheOwnersHands(unittest.TestCase):
    """Инвариант #12: агент подготовлен, но НЕ установлен.

    Здесь нет проверки «агент загружен» намеренно: загрузка — действие владельца,
    и тест, требующий её, толкал бы агента установить себя сам.
    """

    def test_no_install_script_loads_it_automatically(self):
        installer = REPO / "scripts" / "install_all_agents.sh"
        if not installer.is_file():
            self.skipTest("install_all_agents.sh отсутствует в этом дереве")
        self.assertNotIn(LABEL, installer.read_text(encoding="utf-8"),
                         "агент прописан в массовую установку — это деплой без владельца")


if __name__ == "__main__":
    unittest.main()
