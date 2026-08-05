"""Тесты квитанций потребления (ADR-066, Фаза 2).

Ядро честности протокола, закреплённое в обе стороны:
  - квитанция пишется ТОЛЬКО за фактически прочитанный артефакт;
  - за отсутствующий/нечитаемый файл квитанции НЕТ (иначе B3 — театр);
  - превью дайджеста (--check / send=False) — НЕ потребление;
  - все писатели изолируются от живого data/ через root/data_dir —
    тест НИКОГДА не пишет в живой data/consumption_receipts.jsonl
    (тест, квитующий прод-потребление, фальсифицировал бы B3).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest

from spa_core.monitoring import architecture_conformance as ac
from spa_core.monitoring.consumption_receipts import receipts_path, write_receipt

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mkroot(td: str, artifacts: dict[str, dict | str]) -> str:
    """Фикстурный repo-root: data/-файлы + опциональный манифест."""
    for rel, content in artifacts.items():
        full = os.path.join(td, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            if isinstance(content, dict):
                json.dump(content, f, ensure_ascii=False)
            else:
                f.write(content)
    return td


class Writer(unittest.TestCase):
    def test_roundtrip_with_b3_reader(self):
        """Квитанция писателя обязана читаться проверкой B3 (интеграция)."""
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot(td, {"data/investment_os/quant.json":
                                {"generated_at": "2030-01-15T08:00:00+00:00"}})
            now = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)
            self.assertTrue(write_receipt("data/investment_os/quant.json",
                                          "orchestrator_protocol", root=root, now=now))
            got = ac.load_receipts(receipts_path(root))
            self.assertEqual(got["data/investment_os/quant.json"], now)
            line = json.loads(open(receipts_path(root)).read().splitlines()[0])
            self.assertEqual(line["producer_generated_at"], "2030-01-15T08:00:00+00:00")
            self.assertEqual(line["consumer"], "orchestrator_protocol")

    def test_missing_artifact_gets_no_receipt(self):
        """Нельзя заквитовать то, чего не читал."""
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(write_receipt("data/nope.json", "x", root=td))
            self.assertFalse(os.path.exists(receipts_path(td)))

    def test_append_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = _mkroot(td, {"data/a.json": {"generated_at": "2030-01-01T00:00:00+00:00"}})
            write_receipt("data/a.json", "c1", root=root)
            write_receipt("data/a.json", "c2", root=root)
            lines = open(receipts_path(root)).read().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual([json.loads(l)["consumer"] for l in lines], ["c1", "c2"])

    def test_never_raises(self):
        self.assertFalse(write_receipt("data/x.json", "c",
                                       root="/nonexistent/root/path"))


class ChiefWritesReceipts(unittest.TestCase):
    def test_receipts_only_for_actually_loaded_inputs(self):
        """Синтез chief — настоящий потребитель аналитиков: квитанция за каждый
        прочитанный вход и НИ ОДНОЙ за отсутствующий."""
        from spa_core.investment_os.agents.chief_investment import ChiefInvestmentAgent
        with tempfile.TemporaryDirectory() as td:
            ddir = os.path.join(td, "data", "investment_os")
            _mkroot(td, {
                "data/investment_os/market_regime.json": {"combined_posture": "GREEN"},
                "data/investment_os/red_team.json": {"posture": "NO_THREAT_OBSERVED"},
            })
            agent = ChiefInvestmentAgent(data_dir=ddir, allow_llm=False)
            agent.analyze()
            got = ac.load_receipts(receipts_path(td))
            self.assertEqual(sorted(got), ["data/investment_os/market_regime.json",
                                           "data/investment_os/red_team.json"])
            line = json.loads(open(receipts_path(td)).read().splitlines()[0])
            self.assertEqual(line["consumer"], "com.spa.io_chief_investment")


class ConsumeOfficeScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "consume_office_reports",
            os.path.join(REPO_ROOT, "scripts", "consume_office_reports.py"))
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def fixture_root(self, td):
        manifest = {
            "schema_version": 1,
            "agents": [],
            "artifacts": [
                {"path": "data/investment_os/chief_investment.json", "producer": None,
                 "consumers": ["orchestrator_protocol"], "slo_hours": 26, "status": "active"},
                {"path": "data/investment_os/quant.json", "producer": None,
                 "consumers": ["orchestrator_protocol"], "slo_hours": 26, "status": "active"},
                {"path": "data/only_digest.json", "producer": None,
                 "consumers": ["digest_daily"], "slo_hours": 26, "status": "active"},
                {"path": "data/planned.json", "producer": None,
                 "consumers": ["orchestrator_protocol"], "status": "planned"},
            ],
            "designed_architectures": [],
        }
        return _mkroot(td, {
            "architecture/manifest.json": manifest,
            "data/investment_os/chief_investment.json":
                {"house_view": {"overall_posture": "YELLOW",
                                "conflicts": ["regime vs threat"]},
                 "generated_at": "2030-01-15T08:00:00+00:00"},
            # quant.json НАМЕРЕННО отсутствует — репродукция «файла нет»
        })

    def test_receipts_only_for_read_targets_and_honest_output(self):
        import contextlib, io
        with tempfile.TemporaryDirectory() as td:
            root = self.fixture_root(td)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = self.mod.main(["--root", root])
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            got = ac.load_receipts(receipts_path(root))
            # прочитан и заквитован только chief; quant честно «НЕ ПРОЧИТАН»;
            # digest-артефакт и planned не входят в шаг оркестратора
            self.assertEqual(list(got), ["data/investment_os/chief_investment.json"])
            self.assertIn("НЕ ПРОЧИТАН", out)
            self.assertIn("quant.json", out)
            self.assertIn("YELLOW", out)
            self.assertNotIn("only_digest", out)

    def test_no_receipts_flag(self):
        import contextlib, io
        with tempfile.TemporaryDirectory() as td:
            root = self.fixture_root(td)
            with contextlib.redirect_stdout(io.StringIO()):
                self.mod.main(["--root", root, "--no-receipts"])
            self.assertFalse(os.path.exists(receipts_path(td)))

    def test_manifest_missing_is_loud(self):
        import contextlib, io
        with tempfile.TemporaryDirectory() as td:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = self.mod.main(["--root", td])
            self.assertEqual(rc, 1)
            self.assertIn("манифест не прочитан", buf.getvalue())


class DigestOfficeSection(unittest.TestCase):
    def test_section_built_and_consumed_listed(self):
        from spa_core.telegram.reports.daily import _build_office_section
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            _mkroot(td, {
                "data/investment_os/chief_investment.json":
                    {"house_view": {"overall_posture": "YELLOW",
                                    "conflicts": ["regime=YELLOW vs threat=NONE"]}},
                "data/investment_os/_health.json": {"status": "ok"},
                "data/architecture_conformance.json":
                    {"overall": "WARN", "counts": {"critical": 0, "warn": 3, "unchecked": 0}},
            })
            section, consumed = _build_office_section(Path(td) / "data")
            self.assertIn("Офис", section)
            self.assertIn("YELLOW", section)
            self.assertIn("Архитектура", section)
            self.assertIn("warn 3", section)
            self.assertEqual(sorted(consumed), [
                "data/architecture_conformance.json",
                "data/investment_os/_health.json",
                "data/investment_os/chief_investment.json"])

    def test_missing_files_honest_no_consumption(self):
        from spa_core.telegram.reports.daily import _build_office_section
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "data"))
            section, consumed = _build_office_section(Path(td) / "data")
            self.assertIn("нет данных — это сигнал", section)
            self.assertEqual(consumed, [])

    def test_preview_without_send_writes_no_receipts(self):
        """--check/превью — НЕ потребление: квитанций быть не должно."""
        from spa_core.telegram.reports.daily import run_daily_digest
        with tempfile.TemporaryDirectory() as td:
            _mkroot(td, {"data/investment_os/chief_investment.json":
                         {"house_view": {"overall_posture": "GREEN"}}})
            res = run_daily_digest(data_dir=os.path.join(td, "data"), send=False)
            self.assertIn("Офис", res["message"])
            self.assertFalse(os.path.exists(receipts_path(td)))


if __name__ == "__main__":
    unittest.main()
