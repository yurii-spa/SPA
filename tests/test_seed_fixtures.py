"""
Tests for scripts/seed_test_fixtures.py (MP-445).

Verifies:
1. All expected fixture files are created in tests/fixtures/.
2. paper_evidence_7d.json has correct structure and 7 days.
3. Equity curve is monotonically increasing (positive daily yield).
4. tournament_ranking_7d.json has valid ranking structure.
5. Production data/paper_evidence.json is NOT modified by the script.

Compatible with both pytest and python3 -m unittest.
"""
import json
import pathlib
import subprocess
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
PRODUCTION_FILE = REPO_ROOT / "data" / "paper_evidence.json"
SCRIPT = REPO_ROOT / "scripts" / "seed_test_fixtures.py"


def _run_seed() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _load_json(filename: str) -> dict:
    with open(FIXTURES_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


class TestSeedFixtures(unittest.TestCase):
    """Suite: scripts/seed_test_fixtures.py generates correct test fixtures."""

    @classmethod
    def setUpClass(cls):
        """Run the seed script once before all tests."""
        result = _run_seed()
        if result.returncode != 0:
            raise RuntimeError(
                f"Seed script failed (returncode={result.returncode}):\n{result.stderr}"
            )
        cls.evidence = _load_json("paper_evidence_7d.json")
        cls.tournament = _load_json("tournament_ranking_7d.json")
        cls.golive = _load_json("golive_status.json")

    # ------------------------------------------------------------------
    # Test 1: все ожидаемые fixture-файлы созданы
    # ------------------------------------------------------------------
    def test_1_all_fixture_files_created(self):
        """All three fixture files must exist in tests/fixtures/ with non-zero size."""
        expected = [
            "paper_evidence_7d.json",
            "tournament_ranking_7d.json",
            "golive_status.json",
        ]
        for fname in expected:
            path = FIXTURES_DIR / fname
            self.assertTrue(path.exists(), f"Fixture file not found: {path}")
            self.assertGreater(path.stat().st_size, 0, f"Fixture file is empty: {path}")

    # ------------------------------------------------------------------
    # Test 2: paper_evidence_7d.json — структура и 7 дней
    # ------------------------------------------------------------------
    def test_2_evidence_structure_and_7_days(self):
        """paper_evidence_7d.json must have correct top-level keys and 7 day entries."""
        ev = self.evidence
        self.assertEqual(ev["paper_start"], "2026-06-12")
        self.assertEqual(ev["total_days"], 7)
        self.assertIsInstance(ev["days"], list)
        self.assertEqual(len(ev["days"]), 7)

        required_keys = {"date", "apy_pct", "equity_usd", "cycle_ok"}
        for day in ev["days"]:
            missing = required_keys - set(day.keys())
            self.assertFalse(missing, f"Day entry missing keys {missing}: {day}")
            self.assertTrue(day["cycle_ok"])
            self.assertGreater(day["apy_pct"], 0)
            self.assertLess(day["apy_pct"], 100)
            self.assertGreater(day["equity_usd"], 0)

    # ------------------------------------------------------------------
    # Test 3: equity curve монотонно растёт (положительный дневной yield)
    # ------------------------------------------------------------------
    def test_3_equity_curve_monotonically_increasing(self):
        """Each day's equity must be strictly greater than the previous day's."""
        equities = [day["equity_usd"] for day in self.evidence["days"]]
        for i in range(1, len(equities)):
            self.assertGreater(
                equities[i],
                equities[i - 1],
                f"Equity decreased on day {i}: {equities[i - 1]} → {equities[i]}",
            )
        # Sanity: starting point near $100k
        self.assertGreater(equities[0], 99_000)
        self.assertLess(equities[0], 101_000)

    # ------------------------------------------------------------------
    # Test 4: tournament_ranking_7d.json — структура рейтинга
    # ------------------------------------------------------------------
    def test_4_tournament_ranking_structure(self):
        """tournament_ranking_7d.json must have 3 ranked entries with required fields."""
        rankings = self.tournament.get("rankings", [])
        self.assertEqual(len(rankings), 3)

        ranks_seen = set()
        for entry in rankings:
            self.assertIn("rank", entry)
            self.assertIn("strategy_id", entry)
            self.assertIn("name", entry)
            self.assertIn("target_apy", entry)
            self.assertGreater(entry["target_apy"], 0)
            ranks_seen.add(entry["rank"])

        self.assertEqual(ranks_seen, {1, 2, 3}, f"Expected ranks {{1,2,3}}, got {ranks_seen}")

    # ------------------------------------------------------------------
    # Test 5: production data/paper_evidence.json НЕ изменён скриптом
    # ------------------------------------------------------------------
    def test_5_production_file_not_modified(self):
        """Production data/paper_evidence.json must not be touched by the seed script."""
        if not PRODUCTION_FILE.exists():
            self.skipTest("data/paper_evidence.json does not exist — nothing to protect")

        mtime_before = PRODUCTION_FILE.stat().st_mtime
        size_before = PRODUCTION_FILE.stat().st_size

        # Run script a second time to verify idempotency doesn't clobber production
        result = _run_seed()
        self.assertEqual(result.returncode, 0, f"Script failed:\n{result.stderr}")

        mtime_after = PRODUCTION_FILE.stat().st_mtime
        size_after = PRODUCTION_FILE.stat().st_size

        self.assertEqual(
            mtime_after,
            mtime_before,
            "Production data/paper_evidence.json mtime changed — script touched production!",
        )
        self.assertEqual(
            size_after,
            size_before,
            "Production data/paper_evidence.json size changed — script touched production!",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
