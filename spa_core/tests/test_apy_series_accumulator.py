"""apy_series_accumulator (A1): дневной накопитель живых APY-точек.

Положительный контроль класса «генератор рядов мёртв»: без накопителя у протокола
одна точка навсегда; с ним точки копятся по датам, живые-only, идемпотентно.
"""
import json
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.apy_series_accumulator import accumulate
from spa_core.analytics import _apy_series


def _write_status(ddir: Path, apy_map):
    (ddir / "adapter_status.json").write_text(json.dumps({
        "generated_at": "2026-08-05T06:00:00Z",
        "adapters": {k: ({"apy": v} if v is not None else {"apy": None})
                     for k, v in apy_map.items()},
    }))


class TestAccumulator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ddir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_days_accumulate(self):
        _write_status(self.ddir, {"maple": 9.1})
        r1 = accumulate(data_dir=self.ddir, today="2026-08-05")
        _write_status(self.ddir, {"maple": 9.3})
        r2 = accumulate(data_dir=self.ddir, today="2026-08-06")
        self.assertEqual((r1["appended"], r2["appended"]), (1, 1))
        book = json.loads((self.ddir / "apy_series_daily.json").read_text())
        self.assertEqual(book["series"]["maple"],
                         [["2026-08-05", 9.1], ["2026-08-06", 9.3]])

    def test_same_day_idempotent_history_untouched(self):
        _write_status(self.ddir, {"maple": 9.1})
        accumulate(data_dir=self.ddir, today="2026-08-05")
        _write_status(self.ddir, {"maple": 9.9})
        accumulate(data_dir=self.ddir, today="2026-08-05")
        book = json.loads((self.ddir / "apy_series_daily.json").read_text())
        self.assertEqual(book["series"]["maple"], [["2026-08-05", 9.9]])

    def test_non_finite_skipped_no_fabrication(self):
        _write_status(self.ddir, {"maple": None, "pendle": float("nan"), "aave_v3": 3.4})
        r = accumulate(data_dir=self.ddir, today="2026-08-05")
        self.assertEqual((r["appended"], r["skipped"]), (1, 2))
        book = json.loads((self.ddir / "apy_series_daily.json").read_text())
        self.assertNotIn("maple", book["series"])
        self.assertNotIn("pendle", book["series"])

    def test_missing_status_is_loud_noop(self):
        r = accumulate(data_dir=self.ddir, today="2026-08-05")
        self.assertEqual(r["appended"], 0)
        self.assertIn("error", r)
        self.assertFalse((self.ddir / "apy_series_daily.json").exists())

    def test_reader_merges_accumulated_points(self):
        # Положительный контроль сквозной цепочки: накопитель -> _apy_series.get_series.
        _write_status(self.ddir, {"maple": 9.1})
        accumulate(data_dir=self.ddir, today="2026-08-04")
        _write_status(self.ddir, {"maple": 9.3})
        accumulate(data_dir=self.ddir, today="2026-08-05")
        series = _apy_series.get_series("maple", data_dir=self.ddir)
        days = [d for d, _ in series]
        self.assertIn("2026-08-04", days)
        self.assertIn("2026-08-05", days)


if __name__ == "__main__":
    unittest.main()
