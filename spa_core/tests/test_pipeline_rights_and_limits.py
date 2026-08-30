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
