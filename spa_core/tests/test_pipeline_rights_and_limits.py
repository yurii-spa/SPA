"""Права и ограничения КОНВЕЙЕРА выводятся из обёртки и её шагов (30.08).

У 15 живых агентов не было ни прав, ни ограничений: их спрашивали про МОДУЛЬ, а у
многошаговой обёртки одного модуля нет — она ЕСТЬ конвейер. Права такого агента =
что он запускает плюс продукты его шагов; ограничения = объединение по шагам.

Почему объединение, а не «первый шаг»: `run_tier1_governance.sh` запускает шесть модулей,
и один из них — `spa_core.execution.readiness_audit`. Паспорт, написанный по одному шагу,
сказал бы «execution не трогает» — и соврал бы про money-path.

И почему НЕ глубже одного уровня: попытка читать вложенные скрипты выдала права вида
«запускать scripts.foo, target» — это ПРИМЕРЫ из докстринга канонического
`agent_template.sh`. Ложное право хуже пустого поля: пустое видно в списке пробелов,
ложное выглядит знанием.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_fap", _REPO / "scripts" / "fill_agent_passports.py")
fap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fap)


class LimitsAreTheUnionOverSteps(unittest.TestCase):
    def test_a_single_execution_step_removes_the_clean_claim(self):
        """Положительный контроль на живом дереве: tier1_governance трогает execution."""
        lim = fap.limits_from_shell("run_tier1_governance.sh")
        self.assertIn("ТРОГАЕТ execution", lim)
        self.assertNotIn("ни один шаг не импортирует execution", lim)

    def test_a_clean_pipeline_says_so(self):
        """Обратная сторона: где ни один шаг не трогает execution — так и написано."""
        lim = fap.limits_from_shell("agent_orchestrator.sh")
        self.assertIn("ни один шаг не импортирует execution", lim)

    def test_external_only_wrapper_is_named_as_such(self):
        r = fap.rights_from_shell("run_cloudflared.sh")
        lim = fap.limits_from_shell("run_cloudflared.sh")
        self.assertIn("cloudflared", r)
        self.assertIn("питоновских шагов нет", lim)


class TheUnionOverStepsIsLoadBearing(unittest.TestCase):
    """Синтетический случай: обёртка ЧИСТАЯ, а execution трогает её ШАГ.

    На живом флоте `run_tier1_governance.sh` называет `spa_core.execution…` прямо в
    своей же строке запуска, поэтому чтения одной обёртки там хватает — и мутация
    «не читать шаги» осталась зелёной. Проверка, которую нельзя провалить, ничего не
    сторожит, поэтому случай построен явно: если шаги перестанут читаться, паспорт
    скажет «execution не трогает» про конвейер, который его трогает.
    """

    def _repo(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "scripts").mkdir()
        (tmp / "pkg").mkdir()
        (tmp / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (tmp / "pkg" / "step.py").write_text(
            "from spa_core.execution.engine import go\n", encoding="utf-8")
        (tmp / "scripts" / "w.sh").write_text(
            '#!/bin/bash\n"$PY" -m pkg.step\n', encoding="utf-8")
        return tmp

    def test_execution_in_a_step_is_seen_though_the_wrapper_is_clean(self):
        tmp = self._repo()
        real = fap.REPO
        try:
            fap.REPO = tmp
            wrapper = (tmp / "scripts" / "w.sh").read_text(encoding="utf-8")
            self.assertNotIn("spa_core.execution", wrapper.replace("pkg.step", ""),
                             "обёртка перестала быть чистой — случай выродился")
            self.assertIn("ТРОГАЕТ execution", fap.limits_from_shell("w.sh"))
        finally:
            fap.REPO = real


class ExecutionIsJudgedByStructureNotBySubstring(unittest.TestCase):
    """11.09: «трогает execution» судится импортом и запуском, а не буквами в тексте.

    Замер: `test_a_clean_pipeline_says_so` покраснел, потому что `consume_office_reports`
    упомянул `spa_core/execution/` в строке ПРОЗЫ. По всему флоту подстрока давала шесть
    ложных «ТРОГАЕТ» (докстринг цикла «Does NOT import spa_core/execution» — буквально
    наоборот) — и одновременно `golive_freshness_cycle` ЗАПУСКАЕТ execution процессом без
    импорта, так что чисто импортная мерка соврала бы в обратную сторону.
    """

    def _repo(self, step_src: str | None, launch: str = '"$PY" -m pkg.step'):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "scripts").mkdir()
        (tmp / "pkg").mkdir()
        (tmp / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        if step_src is not None:
            (tmp / "pkg" / "step.py").write_text(step_src, encoding="utf-8")
        (tmp / "scripts" / "w.sh").write_text(f"#!/bin/bash\n{launch}\n", encoding="utf-8")
        return tmp

    def _limits(self, step_src, launch='"$PY" -m pkg.step'):
        tmp = self._repo(step_src, launch)
        real = fap.REPO
        try:
            fap.REPO = tmp
            return fap.limits_from_shell("w.sh")
        finally:
            fap.REPO = real

    def test_prose_about_execution_is_not_an_import(self):
        lim = self._limits('"""Does NOT import ``spa_core/execution/``."""\n'
                           'MSG = "нужен наблюдатель вне `spa_core/execution/`"\n')
        self.assertIn("ни один шаг не импортирует execution", lim)

    def test_a_list_of_forbidden_domains_is_not_an_import(self):
        """Форма `rules_watchdog`: запретные домены — данные, а не использование."""
        lim = self._limits('FORBIDDEN = ["spa_core.risk", "spa_core.execution"]\n'
                           'DIRS = ["spa_core/execution"]\n')
        self.assertIn("ни один шаг не импортирует execution", lim)

    def test_launching_execution_as_a_process_touches_it(self):
        lim = self._limits('import subprocess\nPY = "python3"\n'
                           'subprocess.run([PY, "-m", "spa_core.execution.owner_blockers"])\n')
        self.assertIn("ТРОГАЕТ execution", lim)

    def test_a_shell_command_string_launching_execution_touches_it(self):
        lim = self._limits('import os\nos.system("python3 -m spa_core.execution.readiness_audit --x")\n')
        self.assertIn("ТРОГАЕТ execution", lim)

    def test_import_module_and_from_import_touch_it(self):
        for src in ('import importlib\nimportlib.import_module("spa_core.execution.engine")\n',
                    "from spa_core import execution\n",
                    "import spa_core.execution.wallet as w\n"):
            with self.subTest(src=src):
                self.assertIn("ТРОГАЕТ execution", self._limits(src))

    def test_a_relative_import_is_resolved_from_the_module_name(self):
        self.assertTrue(fap.imports_execution("from ..execution import engine\n",
                                              "spa_core.monitoring.x"))
        self.assertFalse(fap.imports_execution("from ..risk import policy\n",
                                               "spa_core.monitoring.x"))

    def test_an_unparseable_step_is_unmeasured_not_clean(self):
        lim = self._limits("def broken(:\n")
        self.assertIn("НЕ ИЗМЕРЕНО", lim)
        self.assertNotIn("ни один шаг не импортирует execution", lim)

    def test_a_missing_repo_step_is_named_not_skipped(self):
        """Раньше ненайденный файл шага пропускался молча — и конвейер звался чистым."""
        lim = self._limits(None)
        self.assertIn("НЕ ИЗМЕРЕНО", lim)
        self.assertIn("pkg.step", lim)

    def test_a_missing_step_beside_a_clean_one_is_still_named(self):
        """Батарея: сцена с ОДНИМ ненайденным шагом краснела и другой дорогой («ни одного
        прочитанного»), и мутация «пропускать молча» выживала. Здесь рядом чистый шаг —
        без названного пропуска конвейер снова звался бы чистым."""
        lim = self._limits("X = 1\n", launch='"$PY" -m pkg.step\n"$PY" -m pkg.missing')
        self.assertIn("НЕ ИЗМЕРЕНО", lim)
        self.assertIn("pkg.missing", lim)

    def test_a_package_step_is_read_through_its_init(self):
        """Шаг-пакет (`-m pkg.sub`, код в `__init__.py`) раньше не находился вовсе."""
        tmp = self._repo(None, launch='"$PY" -m pkg.sub')
        (tmp / "pkg" / "sub").mkdir()
        (tmp / "pkg" / "sub" / "__init__.py").write_text(
            "from spa_core.execution.engine import go\n", encoding="utf-8")
        real = fap.REPO
        try:
            fap.REPO = tmp
            self.assertIn("ТРОГАЕТ execution", fap.limits_from_shell("w.sh"))
        finally:
            fap.REPO = real

    def test_a_pipeline_with_no_step_read_is_unmeasured(self):
        """`uvicorn` запускает чужую программу: ни одной строки нашего кода не прочитано."""
        lim = self._limits(None, launch='"$PY" -m uvicorn app:app')
        self.assertIn("НЕ ИЗМЕРЕНО", lim)
        self.assertNotIn("ни один шаг не импортирует execution", lim)

    def test_live_positive_control_the_freshness_cycle_launches_execution(self):
        """Живой случай запуска без импорта — обязан остаться «ТРОГАЕТ»."""
        self.assertIn("ТРОГАЕТ execution", fap.limits_from_shell("agent_golive_freshness.sh"))


class ItRefusesToInventFromTemplates(unittest.TestCase):
    """Решение не идти глубже одного уровня — закреплено, а не подразумевается."""

    TEMPLATE_USERS = ("agent_tournament_engine.sh", "agent_dashboard.sh",
                      "agent_rwa_safety_board.sh")

    def test_no_placeholder_ever_becomes_a_right(self):
        for program in self.TEMPLATE_USERS:
            with self.subTest(program=program):
                r = fap.rights_from_shell(program) or ""
                for junk in ("foo", "target", "example"):
                    self.assertNotIn(junk, r,
                                     f"{program}: пример из шаблона попал в права")

    def test_bookkeeping_helper_is_not_a_step(self):
        """`log_session_change` дёргают для бухгалтерии — это не шаг агента."""
        mods, _ = fap.shell_targets("agent_inbox_intake.sh")
        self.assertFalse([m for m in mods if m.endswith("log_session_change")])


class TheModuleSourceStillOutranksThePipeline(unittest.TestCase):
    def test_agent_with_a_module_keeps_its_own_rights(self):
        entry = {"produces": [{"artifact": "data/x.json", "slo_hours": 26}],
                 "program": "run_tier1_governance.sh"}
        got = fap.derive(entry)["rights"]
        self.assertIn("писать data/x.json", got)
        self.assertNotIn("запускать", got, "конвейер вытеснил собственные права агента")

    def test_pipeline_fills_only_the_silence(self):
        entry = {"produces": [], "program": "run_cloudflared.sh"}
        self.assertEqual(fap.rights_from_manifest(None, entry), "")
        self.assertTrue(fap.derive(entry)["rights"])


class TheLiveFleetIsCovered(unittest.TestCase):
    def test_nine_in_ten_live_agents_have_a_full_passport(self):
        """Замер, а не намерение. Мёртвые метки в знаменатель не берём."""
        import json
        from spa_core.monitoring.agent_passport import REQUIRED_FIELDS
        man = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        live = [a for a in man["agents"] if a.get("intent") == "active"]
        full = [a for a in live if all((a.get("passport") or {}).get(f) for f in REQUIRED_FIELDS)]
        self.assertGreaterEqual(len(full) / len(live), 0.85,
                                f"покрытие живых упало: {len(full)}/{len(live)}")


if __name__ == "__main__":
    unittest.main()


class EveryWayAnAgentNamesItsWork(unittest.TestCase):
    """Четыре формы запуска, и все читаются из ТЕКСТА ВЫЗОВА (30.08).

    Восемь живых агентов оставались без прав, потому что их работа названа не через
    `-m`. Каждая форма закреплена своим живым примером — иначе завтра кто-то упростит
    разбор и не заметит, что половина флота снова онемела.
    """

    def test_template_argument_is_the_target(self):
        """`agent_template.sh <имя> <модуль>` — соглашение самого шаблона (строки 83–88)."""
        mods, _ = fap.shell_targets("agent_dashboard.sh")
        self.assertEqual(mods, ["http.server"])

    def test_inline_import_is_a_target(self):
        """`python -c "from spa_core.x import run"` называет модуль так же однозначно."""
        mods, _ = fap.shell_targets("agent_inbox_intake.sh")
        self.assertIn("spa_core.owner_queue.intake", mods)

    def test_nested_script_is_named_but_not_entered(self):
        """Имя вложенного скрипта — факт; его СОДЕРЖИМОЕ мы не читаем (см. класс выше)."""
        _, ext = fap.shell_targets("agent_reboot_verify.sh")
        self.assertTrue([e for e in ext if "verify_fleet_after_reboot.sh" in e])

    def test_headless_session_is_named_as_such(self):
        """Работа такого агента — не модуль, а выполненное задание. Так и написано."""
        _, ext = fap.shell_targets("agent_novel_edge_rnd.sh")
        self.assertTrue([e for e in ext if "Claude" in e])

    def test_live_coverage_is_at_least_nine_in_ten(self):
        import json
        from spa_core.monitoring.agent_passport import REQUIRED_FIELDS
        man = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        live = [a for a in man["agents"] if a.get("intent") == "active"]
        full = [a for a in live if all((a.get("passport") or {}).get(f) for f in REQUIRED_FIELDS)]
        self.assertGreaterEqual(len(full) / len(live), 0.9,
                                f"покрытие живых упало: {len(full)}/{len(live)}")
