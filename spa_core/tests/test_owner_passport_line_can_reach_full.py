"""Строка паспортов в дневном отчёте обязана уметь стать полной.

Замер 31.08. Владельцу каждое утро уходило:

    🪪 Паспорта агентов: 93/96 · без паспорта: cpa_daily, morning_digest, telegram_watcher

Все трое — `intent=retired`, похоронены решениями владельца. Паспорт им не нужен: у них
нет дела. То есть число 93/96 **не могло стать полным никогда**, а три имени не требовали
ничего. Строку, которая не зеленеет ни при каком поведении, перестают читать — и в ней
утонет настоящий пробел, когда появится.

Проверяем через ту же функцию, из которой строку собирает отчёт (`agent_passports.audit`),
а не через свою копию её логики.
"""
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import agent_passports as ap

_FULL = {f: "заполнено" for f in ap.REQUIRED_FIELDS}


def _manifest(tmp: Path, agents) -> Path:
    p = tmp / "manifest.json"
    p.write_text(json.dumps({"agents": agents}, ensure_ascii=False))
    return p


class TestOwnerPassportLineCanReachFull(unittest.TestCase):

    def test_retired_agent_without_passport_is_not_a_gap(self):
        with tempfile.TemporaryDirectory() as d:
            m = _manifest(Path(d), [
                {"label": "com.spa.alive", "intent": "active", "passport": dict(_FULL)},
                {"label": "com.spa.cpa_daily", "intent": "retired"},
            ])
            r = ap.audit(m)
        self.assertEqual(r["missing"], [],
                         f"похороненный выдан за пробел: {r['missing']}")
        self.assertEqual((r["with_passport"], r["total"]), (1, 1),
                         "число обязано быть достижимо: 1/1, а не 1/2")

    def test_retired_gap_stays_visible(self):
        """Сузить — не спрятать: он обязан остаться видимым отдельно."""
        with tempfile.TemporaryDirectory() as d:
            m = _manifest(Path(d), [
                {"label": "com.spa.alive", "intent": "active", "passport": dict(_FULL)},
                {"label": "com.spa.cpa_daily", "intent": "retired"},
            ])
            r = ap.audit(m)
        self.assertEqual(r.get("retired_without_passport"), ["com.spa.cpa_daily"])
        self.assertEqual(r.get("retired_excluded"), 1)

    def test_a_live_agent_without_passport_is_still_a_gap(self):
        """Обратный контроль: живой без паспорта обязан краснеть."""
        with tempfile.TemporaryDirectory() as d:
            m = _manifest(Path(d), [
                {"label": "com.spa.alive", "intent": "active", "passport": dict(_FULL)},
                {"label": "com.spa.naked", "intent": "active"},
            ])
            r = ap.audit(m)
        self.assertEqual(r["missing"], ["com.spa.naked"])
        self.assertEqual((r["with_passport"], r["total"]), (1, 2))

    def test_unreadable_manifest_still_says_not_measured(self):
        """Нечитаемый манифест — «не измерено», а не ноль (fail-CLOSED)."""
        r = ap.audit(Path("/нет/такого/manifest.json"))
        self.assertIsNone(r["total"])
        self.assertIn("не измерено", r["note"])


if __name__ == "__main__":
    unittest.main()
