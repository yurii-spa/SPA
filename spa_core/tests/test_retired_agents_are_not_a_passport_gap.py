"""Похороненный агент — не пробел в паспортах.

Замер 31.08: отчёт `fill_agent_passports.py --check` называл трёх агентов «без деловой
цели» и добавлял «цель должен написать автор или владелец». Проверка показала, что все
трое — `intent=retired`, причём двое похоронены прямым решением владельца (ADR-067,
06.08). Настоящих пробелов было НОЛЬ.

Вред не в трёх строках, а в том, что такой список **никогда не опустеет**: похороненные
не обзаведутся целью по определению. Список, который не может опустеть, приучают не
читать — и в нём потеряется настоящий пробел, когда появится.

Тест зовёт НАСТОЯЩУЮ точку входа на настоящем манифесте: подделанный вход проверял бы
мою выемку, а не поведение инструмента.
"""
import importlib.util
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FAP = _ROOT / "scripts" / "fill_agent_passports.py"
_MANIFEST = _ROOT / "architecture" / "manifest.json"


def _run_report():
    spec = importlib.util.spec_from_file_location("fap_retired_test", _FAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.run(write=False)


@unittest.skipUnless(_FAP.is_file() and _MANIFEST.is_file(),
                     "манифест или выводитель недоступны в этом дереве")
class TestRetiredAgentsAreNotAGap(unittest.TestCase):

    def setUp(self):
        self.mod, self.report = _run_report()
        import json
        self.agents = {a["label"]: a
                       for a in json.loads(_MANIFEST.read_text())["agents"]}

    def test_no_retired_agent_is_reported_as_needing_an_author(self):
        bad = [l for l in self.report.get("needs_author", [])
               if self.agents.get(l, {}).get("intent") == "retired"]
        self.assertEqual(
            bad, [],
            f"похороненные агенты выданы за пробел в паспортах: {bad}")

    def test_retired_gaps_are_still_reported_separately(self):
        """Сузить — не значит спрятать: они обязаны остаться видимыми."""
        self.assertIn("retired_without_goal", self.report,
                      "похороненные без цели пропали из отчёта совсем — "
                      "«сверено и нормально» стало неотличимо от «не сверяли»")
        for label in self.report["retired_without_goal"]:
            self.assertEqual(
                self.agents.get(label, {}).get("intent"), "retired",
                f"{label} попал в список похороненных, не будучи retired")

    def test_the_two_lists_do_not_overlap(self):
        a = set(self.report.get("needs_author", []))
        b = set(self.report.get("retired_without_goal", []))
        self.assertEqual(a & b, set(), "агент числится и пробелом, и похороненным")

    def test_the_control_is_not_vacuous(self):
        """Контроль на украшение: если похороненных без цели нет вовсе,
        первый тест зелен ни о чём — тогда об этом надо знать."""
        self.assertTrue(
            self.report.get("retired_without_goal"),
            "в манифесте нет ни одного похороненного без цели — проверка выше "
            "проходит вхолостую; если так стало намеренно, тест надо пересмотреть")


if __name__ == "__main__":
    unittest.main()
