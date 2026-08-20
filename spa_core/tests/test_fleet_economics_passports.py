"""Экономика цеха + паспорта агентов + стандарт дневного отчёта (AI1, мандат 20.08).

Offline: git инжектируется, манифест и data — во временных каталогах.

    python3 -m unittest spa_core.tests.test_fleet_economics_passports -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import agent_passports as ap
from spa_core.monitoring import fleet_economics as fe


class TestFleetEconomics(unittest.TestCase):
    def test_counts_cycles_and_commits(self):
        subs = ["цикл #321: что-то", "guard(x): y", "Цикл #322: z", "chore: w"]
        out = fe.summary(Path("/x"), subjects_fn=lambda r, h: subs)
        self.assertEqual(out["commits"], 4)
        self.assertEqual(out["cycles"], 2)

    def test_cost_from_env(self):
        import os
        os.environ["SPA_COST_PER_CYCLE_USD"] = "1.5"
        try:
            out = fe.summary(Path("/x"), subjects_fn=lambda r, h: ["цикл #1"] * 10)
            self.assertEqual(out["cost_estimate_usd"], 15.0)
        finally:
            os.environ.pop("SPA_COST_PER_CYCLE_USD", None)

    def test_no_cost_env_named_honestly(self):
        import os
        os.environ.pop("SPA_COST_PER_CYCLE_USD", None)
        out = fe.summary(Path("/x"), subjects_fn=lambda r, h: [])
        self.assertIsNone(out["cost_estimate_usd"])
        self.assertIn("не оценена", out["note"])

    def test_git_unavailable_is_signal_not_zero(self):
        out = fe.summary(Path("/x"), subjects_fn=lambda r, h: None)
        self.assertIsNone(out["commits"])
        self.assertIn("не измерена", out["note"])

    def test_artifact_written_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = fe.write_artifact(Path(tmp), repo_root=Path("/x"),
                                     subjects_fn=lambda r, h: ["цикл #1"])
            doc = json.loads(path.read_text())
            self.assertEqual(doc["cycles"], 1)


class TestAgentPassports(unittest.TestCase):
    def _manifest(self, tmp: Path, agents) -> Path:
        p = tmp / "manifest.json"
        p.write_text(json.dumps({"agents": agents}), encoding="utf-8")
        return p

    def test_counts_missing_passports(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(Path(tmp), [
                {"label": "com.spa.good", "passport": {
                    "goal": "цель", "quality_metric": "метрика",
                    "escalation": "звать владельца"}},
                {"label": "com.spa.bare"},
                {"label": "com.spa.half", "passport": {"goal": "есть"}},
            ])
            out = ap.audit(p)
            self.assertEqual(out["total"], 3)
            self.assertEqual(out["with_passport"], 1)
            self.assertEqual(out["missing"], ["com.spa.bare", "com.spa.half"])

    def test_unreadable_manifest_is_not_zero(self):
        out = ap.audit(Path("/nonexistent/manifest.json"))
        self.assertIsNone(out["total"])
        self.assertIn("не измерено", out["note"])

    def test_real_manifest_parses(self):
        # Настоящий манифест репо обязан читаться (форма agents поддержана).
        out = ap.audit()
        self.assertIsNotNone(out["total"])
        self.assertGreater(out["total"], 10)


class TestDigestFactoryAndStandard(unittest.TestCase):
    def test_factory_section_reads_artifacts(self):
        from spa_core.telegram.reports.daily import _build_factory_section
        with tempfile.TemporaryDirectory() as tmp:
            ddir = Path(tmp)
            (ddir / fe.ARTIFACT_REL).write_text(json.dumps({
                "cycles": 17, "commits": 40, "cost_estimate_usd": 25.5}))
            out = _build_factory_section(ddir)
            self.assertIn("Цех за 24ч", out)
            self.assertIn("17", out)
            self.assertIn("$25.5", out)
            self.assertIn("Паспорта агентов", out)  # inline по реальному манифесту

    def test_standard_gaps_name_missing_blocks(self):
        from spa_core.telegram.reports.daily import _standard_gaps
        gaps = _standard_gaps("📊 SPA Daily Report\n🏛 Офис: постура")
        self.assertIn("3 трека (Cons/Bal/Agg)", gaps)
        self.assertIn("экономика цеха", gaps)
        self.assertNotIn("сводка портфеля", gaps)

    def test_full_message_names_three_tracks_gap(self):
        # Живой вопрос владельца 19.08 «а где три пакета?» — теперь отчёт
        # обязан называть эту дыру сам, каждый день, пока она не закрыта.
        from spa_core.telegram.reports.daily import build_digest_message
        with tempfile.TemporaryDirectory() as tmp:
            msg, data = build_digest_message(data_dir=tmp, drain=False)
            self.assertIn("Стандарт отчёта", msg)
            self.assertIn("3 трека", msg)
            self.assertIn("report_standard_gaps", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
