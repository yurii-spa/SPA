"""PRODUCT-TRUTH-02 (ADR-630): Director's product cells read the SAME rules as the site and the monitor.

Lives in a ``test_company_truth*`` file on purpose: the ADR-580 C4 import ratchet allows only Mission
Control and these test files to import Company Truth.
"""
# FROZEN-DATE-OK: the dates ARE the subject — the 2026-10-01 / 10-05 / 10-08 cadence scene of the audit.
from __future__ import annotations

import json

from spa_core.publication import cadence
from spa_core.studio_os import company_truth as ct
from spa_core.tests.test_publication_truth import ROOT, SNAP, _Scene


class DirectorReadsTheSameRules(_Scene):
    def _mirror(self, shelf_doc=None, snap=True):
        m = self.d / "mirror"
        (m / "landing" / "src" / "data").mkdir(parents=True, exist_ok=True)
        if shelf_doc is not None:
            (m / "landing" / "src" / "data" / "site_numbers.json").write_text(json.dumps(shelf_doc))
        if snap:
            (m / "landing" / "src" / "data" / "track_snapshot.json").write_text(json.dumps(SNAP))
        return m

    def test_next_release_is_the_cadence_rule_over_the_published_shelf(self):
        origin = self.shelf("2026-10-01")
        cellv = ct.product_next_release(self._mirror(origin))
        self.assertEqual(cellv["value"]["next_publication"], cadence.next_publication("2026-10-01"))
        self.assertEqual(cellv["value"]["next_publication"], "2026-10-08")

    def test_a_declared_date_against_the_rule_is_shown_not_trusted(self):
        origin = dict(self.shelf("2026-10-01"), next_publication="2026-10-12")
        cellv = ct.product_next_release(self._mirror(origin))
        self.assertEqual(cellv["value"]["next_publication"], "2026-10-08")
        self.assertTrue(cellv.get("gate_ru"))

    def test_public_metric_is_the_artifact_value(self):
        doc = self.shelf()
        flat = json.dumps(ct.product_public_metrics(self._mirror(doc)), ensure_ascii=False)
        self.assertIn(str(doc["headline"]["apy"]["value"]), flat)

    def test_profiles_carry_the_mapping(self):
        prof = ct.product_profiles({"conservative": {}, "balanced": {}, "aggressive": {}}, self._mirror())
        self.assertEqual(prof["balanced"]["mapping"]["track_start"], "2026-10-02")
        self.assertEqual(prof["conservative"]["mapping"]["historical_name"], "Preserve")
        self.assertEqual(prof["conservative"]["mapping"]["maturity"], "REPORTABLE")

    def test_a_conflicting_mapping_is_unknown_with_its_reason(self):
        bad = json.loads(json.dumps(SNAP))
        bad["package_status"]["packages"]["balanced"]["experiment_id"] = "conservative-lending-v1@2026-06-22"
        m = self._mirror()
        (m / "landing" / "src" / "data" / "track_snapshot.json").write_text(json.dumps(bad))
        prof = ct.product_profiles({"conservative": {}, "balanced": {}, "aggressive": {}}, m)
        self.assertEqual(prof["balanced"]["mapping"]["state"], "UNKNOWN")

    def test_telegram_has_no_second_reader_of_the_public_artifacts(self):
        hits = [str(p) for p in (ROOT / "spa_core" / "telegram").rglob("*.py")
                if any(n in p.read_text(encoding="utf-8", errors="replace")
                       for n in ("site_numbers.json", "track_snapshot.json"))]
        self.assertEqual(hits, [])

    def test_the_api_canonical_rate_is_typed_realized_paper(self):
        self.assertIn("REALIZED_PAPER", (ROOT / "spa_core" / "governance" / "ssot.py").read_text(encoding="utf-8"))
