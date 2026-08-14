"""
Tests for scripts/seed_test_fixtures.py (MP-445).

Verifies:
1. All expected fixture files are created (in the directory the seed is given).
2. paper_evidence_7d.json has correct structure and 7 days.
3. Equity curve is monotonically increasing (positive daily yield).
4. tournament_ranking_7d.json has valid ranking structure.
5. Production data/paper_evidence.json is NOT modified by the script.

**Цикл #225 — куда пишет сид во время прогона.** Раньше `setUpClass` запускал сид с
`cwd=REPO_ROOT` и БЕЗ каталога назначения, поэтому каждый прогон переписывал три
git-tracked файла (`tests/fixtures/*.json`) сегодняшней датой. Отсюда два дефекта:
«чистое дерево» переставало быть сигналом при сверке своих правок перед пушем, а
фикстура со штампом «сегодня» не могла протухнуть в принципе — проверка свежести на
ней зелена по построению. Теперь сид получает временный каталог, а трекаемые фикстуры
проверяются как ГОЛДЕН: они обязаны совпадать с детерминированным выводом сида
(тесты 6–11). Ни один существующий ассерт при этом не ослаблен (инв. #16).

Compatible with both pytest and python3 -m unittest.
"""
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import date

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
PRODUCTION_FILE = REPO_ROOT / "data" / "paper_evidence.json"
SCRIPT = REPO_ROOT / "scripts" / "seed_test_fixtures.py"


def _load_module():
    """Import the seed script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("_seed_test_fixtures", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEED = _load_module()


def _run_seed(out_dir) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--out-dir", str(out_dir)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tracked_fixture_digests() -> dict:
    return {name: _digest(FIXTURES_DIR / name)
            for name in SEED.FIXTURE_NAMES
            if (FIXTURES_DIR / name).exists()}


# Снимок трекаемых фикстур ДО того, как этот файл что-либо запустил. Сравнение с ним —
# положительный контроль: вернёшь сид в `tests/fixtures/` — тест 6 покраснеет.
_TRACKED_BEFORE = _tracked_fixture_digests()


def _load_json(out_dir, filename: str) -> dict:
    with open(pathlib.Path(out_dir) / filename, encoding="utf-8") as f:
        return json.load(f)


class TestSeedFixtures(unittest.TestCase):
    """Suite: scripts/seed_test_fixtures.py generates correct test fixtures."""

    @classmethod
    def setUpClass(cls):
        """Run the seed script once before all tests — into a TEMPORARY directory."""
        cls._tmp = tempfile.TemporaryDirectory(prefix="seed_fixtures_")
        cls.out_dir = pathlib.Path(cls._tmp.name)
        result = _run_seed(cls.out_dir)
        if result.returncode != 0:
            raise RuntimeError(
                f"Seed script failed (returncode={result.returncode}):\n{result.stderr}"
            )
        cls.evidence = _load_json(cls.out_dir, "paper_evidence_7d.json")
        cls.tournament = _load_json(cls.out_dir, "tournament_ranking_7d.json")
        cls.golive = _load_json(cls.out_dir, "golive_status.json")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # ------------------------------------------------------------------
    # Test 1: все ожидаемые fixture-файлы созданы
    # ------------------------------------------------------------------
    def test_1_all_fixture_files_created(self):
        """All three fixture files must exist in the output dir with non-zero size."""
        expected = [
            "paper_evidence_7d.json",
            "tournament_ranking_7d.json",
            "golive_status.json",
        ]
        for fname in expected:
            path = self.out_dir / fname
            self.assertTrue(path.exists(), f"Fixture file not found: {path}")
            self.assertGreater(path.stat().st_size, 0, f"Fixture file is empty: {path}")

    # ------------------------------------------------------------------
    # Test 2: paper_evidence_7d.json — структура и 7 дней
    # ------------------------------------------------------------------
    def test_2_evidence_structure_and_7_days(self):
        """paper_evidence_7d.json must have correct top-level keys and 7 day entries."""
        ev = self.evidence
        self.assertEqual(ev["paper_start"], str(SEED.START_DATE))
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
        with tempfile.TemporaryDirectory(prefix="seed_fixtures_prod_") as tmp:
            result = _run_seed(tmp)
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


class TestSeedLeavesTrackedFilesAlone(unittest.TestCase):
    """Цикл #225: прогон не имеет права переписывать git-tracked фикстуры.

    Каждый тест здесь — положительный контроль на реальную аварию 14.08: прогон
    `tests/test_seed_fixtures.py` (5 тестов, 0.13 с) оставлял `git status` с тремя
    изменёнными трекаемыми файлами.
    """

    def test_6_run_does_not_rewrite_tracked_fixtures(self):
        """После сида содержимое tests/fixtures/*.json обязано быть тем же байт-в-байт."""
        self.assertTrue(_TRACKED_BEFORE, "трекаемых фикстур не найдено — измерять нечего")
        with tempfile.TemporaryDirectory(prefix="seed_fixtures_guard_") as tmp:
            result = _run_seed(tmp)
            self.assertEqual(result.returncode, 0, f"Script failed:\n{result.stderr}")

        now = _tracked_fixture_digests()
        self.assertEqual(
            now, _TRACKED_BEFORE,
            "прогон переписал git-tracked фикстуру: 'чистое дерево' перестаёт быть "
            "сигналом при сверке правок перед пушем",
        )

    def test_7_tracked_fixtures_match_deterministic_output(self):
        """Голден: то, что лежит в git, — ровно то, что сид выдаёт по умолчанию.

        Иначе штамп снова уедет на «сегодня», и фикстура опять не сможет протухнуть.
        """
        with tempfile.TemporaryDirectory(prefix="seed_fixtures_golden_") as tmp:
            SEED.write_fixtures(tmp)
            for name in SEED.FIXTURE_NAMES:
                tracked = FIXTURES_DIR / name
                self.assertTrue(tracked.exists(), f"нет трекаемой фикстуры {name}")
                self.assertEqual(
                    (pathlib.Path(tmp) / name).read_bytes(), tracked.read_bytes(),
                    f"{name} в git разошёлся с детерминированным выводом сида",
                )

    def test_8_two_runs_are_byte_identical(self):
        """Два запуска подряд дают одинаковые байты — в содержимом нет часов."""
        with tempfile.TemporaryDirectory(prefix="seed_a_") as a, \
                tempfile.TemporaryDirectory(prefix="seed_b_") as b:
            self.assertEqual(_run_seed(a).returncode, 0)
            self.assertEqual(_run_seed(b).returncode, 0)
            for name in SEED.FIXTURE_NAMES:
                self.assertEqual((pathlib.Path(a) / name).read_bytes(),
                                 (pathlib.Path(b) / name).read_bytes(), name)

    def test_9_stamp_ignores_the_clock(self):
        """Эффектом: подменённые часы НЕ меняют вывод (раньше меняли — `date.today()`)."""
        real = SEED.build_fixtures()

        class _FakeDate(date):
            @classmethod
            def today(cls):
                return date(2099, 1, 1)

        original = SEED.date
        SEED.date = _FakeDate
        try:
            faked = SEED.build_fixtures()
        finally:
            SEED.date = original

        self.assertEqual(faked, real, "содержимое фикстур зависит от системных часов")
        for payload in real.values():
            self.assertEqual(payload["generated_at"], str(SEED.SNAPSHOT_DATE))
            self.assertNotEqual(
                payload["generated_at"], str(date.today()),
                "штамп равен дате прогона — фикстура снова не может протухнуть",
            )

    def test_10_explicit_stamp_is_honoured(self):
        """Время — ВХОД: явный штамп доезжает до всех трёх фикстур."""
        wanted = SEED.START_DATE.replace(year=SEED.START_DATE.year + 1)
        for payload in SEED.build_fixtures(wanted).values():
            self.assertEqual(payload["generated_at"], str(wanted))

    def test_11_refuses_to_write_into_production_data(self):
        """Предохранитель на месте: каталог назначения внутри data/ — отказ."""
        with self.assertRaises(RuntimeError):
            SEED.write_fixtures(REPO_ROOT / "data" / "seed_probe")
        self.assertFalse((REPO_ROOT / "data" / "seed_probe").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
