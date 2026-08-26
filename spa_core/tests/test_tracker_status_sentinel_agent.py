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


class InstallationIsDeclared(unittest.TestCase):
    """Владелец дал разрешение 2026-08-26 — агент подключён в установщик (ADR-143).

    **Намеренная правка теста (инвариант #16), обоснование здесь и в журнале W35.**
    Прежний тест назывался `test_no_install_script_loads_it_automatically` и
    утверждал ОБРАТНОЕ: ярлыка в `install_all_agents.sh` быть не должно, потому что
    «это деплой без владельца». Утверждение было верным ровно до тех пор, пока
    разрешения не было. Правило `.claude/rules/deployment.md` п. 6 говорит «прод-дерево
    — только С РАЗРЕШЕНИЯ владельца», а не «никогда»; разрешение дано прямой
    формулировкой («сам это всё сделай, разрешаю полностью») и записано в ADR-143.
    Поэтому тест не ослаблен и не снят, а ПЕРЕВЁРНУТ: он по-прежнему сторожит
    подключение агента к установщику, только с другой стороны.

    Чего здесь по-прежнему НЕТ и намеренно: проверки «агент ЗАГРУЖЕН». Её нельзя
    снять честно — `launchctl` существует только на прод-Маке, а в контейнере CI
    его нет вовсе, так что такой тест был бы либо вечно красным, либо вечно
    пропущенным, то есть неотличимым от непроверенного (инв. #17).
    """

    def _installer(self) -> str:
        installer = REPO / "scripts" / "install_all_agents.sh"
        self.assertTrue(installer.is_file(), "установщик флота не найден")
        return installer.read_text(encoding="utf-8")

    def test_the_installer_declares_it(self):
        self.assertIn(LABEL, self._installer(),
                      "агента нет в установщике — он снова сирота, которую флот "
                      "потеряет при первой чистой переустановке")

    def test_the_installer_points_at_the_plist_that_exists(self):
        """Строка установщика, указывающая в никуда, = [FAIL] при установке.

        Ровно этот класс ловит `fleet_parity_check.py` как
        `broken_declared_no_plist`; проверяем его здесь на своём агенте.
        """
        self.assertIn(f"launchd/{LABEL}.plist", self._installer())
        self.assertTrue(PLIST.is_file(), f"установщик указывает на отсутствующий {PLIST}")

    def test_it_is_declared_optional_so_a_stale_tree_skips_instead_of_failing(self):
        """Прод-дерево дрейфует от origin по построению.

        Если plist'а там ещё нет, агент обязан дать [SKIP], а не [FAIL]: иначе
        одна отстающая копия дерева роняет установку ВСЕГО флота.
        """
        text = self._installer()
        idx = text.index(LABEL)
        tail = text[idx:idx + 200]
        self.assertIn('"1"', tail, "агент объявлен обязательным — отстающее дерево уронит весь флот")


if __name__ == "__main__":
    unittest.main()
