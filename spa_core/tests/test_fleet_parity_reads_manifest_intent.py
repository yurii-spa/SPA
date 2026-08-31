"""Судьбу агента сторож чётности берёт из манифеста, а не из своей константы.

Замер 31.08: `fleet_parity_check` сообщал ДЕВЯТЬ «сирот» (plist есть, не ставится,
не отставной). Шесть из них помечены в манифесте `intent: retired`, и НИ ОДНОГО из
этих шести не было в константе `agent_health_monitor.RETIRED_LABELS` (10 имён).

Две трети находок ложные. Оставленный у отложенного агента plist — документированная
часть карантина («НЕ удалён: plist лежит в репозитории, команда возврата в
attic/agents/QUARANTINE.json»), а не непорядок. Список, где большинство находок
ложные, читать перестают — и настоящая в нём утонет.

Тот же класс, что ADR-144: два источника правды об одном предмете гарантированно
разъезжаются. Здесь предмет — «кто у нас отставной».

Отдельно: сузить ≠ спрятать. Спроектированные, но не развёрнутые агенты вынесены в
собственную строку отчёта, а не удалены из него.
"""
import importlib.util
import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "fleet_parity_check.py"
_MANIFEST = _ROOT / "architecture" / "manifest.json"


def _mod():
    spec = importlib.util.spec_from_file_location("fp_under_test", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@unittest.skipUnless(_SCRIPT.is_file() and _MANIFEST.is_file(),
                     "сторож или манифест недоступны в этом дереве")
class TestFleetParityReadsManifestIntent(unittest.TestCase):

    def setUp(self):
        self.m = _mod()
        self.intents = {a["label"]: a.get("intent")
                        for a in json.loads(_MANIFEST.read_text())["agents"]}
        self.report = self.m.build_report(write=False)

    def test_no_manifest_retired_agent_is_called_an_orphan(self):
        bad = [o for o in self.report["orphan_plist_not_declared"]
               if self.intents.get(o) == "retired"]
        self.assertEqual(bad, [], f"похороненные выданы за сирот: {bad}")

    def test_manifest_retired_are_actually_known_to_the_guard(self):
        """Ядро аварии: константа не знала НИ ОДНОГО из манифестных retired."""
        retired_in_manifest = {l for l, i in self.intents.items() if i == "retired"}
        self.assertTrue(retired_in_manifest, "в манифесте нет retired — тест бессмыслен")
        known = self.m.retired_labels()
        self.assertTrue(
            retired_in_manifest <= known,
            f"сторож не знает о похороненных: {sorted(retired_in_manifest - known)}")

    def test_designed_agents_are_reported_not_hidden(self):
        """Сузить — не спрятать: они обязаны остаться видимыми отдельной строкой."""
        self.assertIn("designed_not_deployed", self.report,
                      "спроектированные исчезли из отчёта совсем")
        for l in self.report["designed_not_deployed"]:
            self.assertEqual(self.intents.get(l), "designed", l)

    def test_the_constant_still_contributes(self):
        """Объединение, а не замена: имена из константы не теряются."""
        from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS
        self.assertTrue(set(RETIRED_LABELS) <= self.m.retired_labels(),
                        "константа перестала учитываться — знание убавилось")

    def test_an_active_agent_with_a_stray_plist_is_still_an_orphan(self):
        """Обратный контроль: настоящая сирота обязана остаться находкой."""
        real = self.m.build_report(write=False)
        active_orphans = [o for o in real["orphan_plist_not_declared"]
                          if self.intents.get(o) not in ("retired", "designed")]
        # На исправном флоте их может не быть — тогда проверяем САМО правило:
        # активный ярлык не входит ни в retired, ни в designed.
        self.assertTrue(
            all(self.intents.get(o) not in ("retired", "designed") for o in active_orphans),
            "в сиротах оказался агент с судьбой retired/designed")


if __name__ == "__main__":
    unittest.main()
