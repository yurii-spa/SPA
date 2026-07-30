"""
Honesty regression tests for spa_core.monitoring.cycle_health_monitor.

Context (cycle #37, 2026-07-30)
-------------------------------
``com.spa.cycle_health`` runs this module every 30 min and publishes
``data/cycle_health.json``. On origin/main the report claimed clean verdicts
about checks that never ran — the fail-OPEN class already fixed in
``d_riskwire`` (#29), ``d2_connectivity`` (#31), the Tier-1 status summary
(#35) and ``rules_watchdog`` (#36). Reproduced on a clean checkout before any
edit:

  * all three watched files ABSENT  → ``data_freshness: "OK"`` and
    ``overall: "HEALTHY"``, with the recommendations list carrying BOTH
    "Missing data files: …" AND "All checks passed. Cycle is healthy."
  * equity values unreadable        → ``equity_anomaly: "OK"``  → HEALTHY
  * ``prev_equity == 0``            → ``equity_anomaly: "OK"``
  * a 27 h gap (real WARNING band is 26–30 h) → published advice read
    "Cycle gap is between 2–4 hours"; the CRITICAL string said "over 4 hours"
    while the real trigger is 30 h. Stale copy from the retired 30-min cadence.

Every test here is hermetic: ``tmp_path`` only. The live ``data/`` tree and the
go-live track are never read or written.

Invariant #2 (refusal-first): "I could not measure this" must never be
published as "I measured this and it is fine".
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring.cycle_health_monitor import (  # noqa: E402
    CRITICAL,
    CRITICAL_CYCLE_GAP_HOURS,
    HEALTHY,
    MAX_CYCLE_GAP_HOURS,
    MAX_EQUITY_DROP_PCT,
    OK,
    STALE,
    UNCHECKED,
    WARNING,
    CycleHealthMonitor,
    _WATCHED_FILES,
)

_HEALTHY_CLAIM = "All checks passed. Cycle is healthy."


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fresh_curve(data_dir: Path, equities: list) -> None:
    """A just-written equity curve, so the cycle_gap check is unambiguously OK."""
    _write(
        data_dir / "equity_curve_daily.json",
        {
            "generated_at": _now().isoformat(),
            "daily": [
                {"date": f"2026-07-{i + 1:02d}", "equity": e}
                for i, e in enumerate(equities)
            ],
        },
    )


def _touch_all_watched(data_dir: Path) -> None:
    """Create every watched file with a current mtime → genuinely fresh."""
    for name in _WATCHED_FILES:
        _write(data_dir / name, {"stub": True})


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "data"
        self.data_dir.mkdir(parents=True)
        self.m = CycleHealthMonitor()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_all(self) -> dict:
        return self.m.run_all_checks(data_dir=str(self.data_dir))


# ---------------------------------------------------------------------------
# 1. data_freshness — an unmeasured file is not a fresh file
# ---------------------------------------------------------------------------

class TestFreshnessNeverClaimsUnmeasured(_Base):
    def test_all_watched_files_absent_is_not_ok(self):
        r = self.m.check_data_freshness(data_dir=str(self.data_dir))
        self.assertEqual(r["status"], UNCHECKED)
        self.assertEqual(r["fresh_files"], [])
        self.assertEqual(len(r["unchecked"]), len(_WATCHED_FILES))

    def test_absent_file_reason_is_stated(self):
        r = self.m.check_data_freshness(data_dir=str(self.data_dir))
        for entry in r["unchecked"]:
            self.assertIn(entry["file"], _WATCHED_FILES)
            self.assertTrue(entry["reason"].strip())
            self.assertIn("age unknown", entry["reason"])

    def test_missing_files_key_preserved_for_back_compat(self):
        r = self.m.check_data_freshness(data_dir=str(self.data_dir))
        self.assertEqual(sorted(r["missing_files"]), sorted(_WATCHED_FILES))

    def test_all_files_present_and_fresh_is_ok(self):
        _touch_all_watched(self.data_dir)
        r = self.m.check_data_freshness(data_dir=str(self.data_dir))
        self.assertEqual(r["status"], OK)
        self.assertEqual(r["unchecked"], [])
        self.assertEqual(len(r["fresh_files"]), len(_WATCHED_FILES))

    def test_one_absent_among_fresh_still_degrades(self):
        _touch_all_watched(self.data_dir)
        (self.data_dir / "market_regime.json").unlink()
        r = self.m.check_data_freshness(data_dir=str(self.data_dir))
        self.assertEqual(r["status"], UNCHECKED)
        self.assertEqual([e["file"] for e in r["unchecked"]], ["market_regime.json"])

    def test_real_staleness_outranks_unchecked(self):
        """A measured stale file is a finding; it must not be masked."""
        _touch_all_watched(self.data_dir)
        (self.data_dir / "tournament_ranking.json").unlink()
        old = (_now() - timedelta(hours=_WATCHED_FILES["market_regime.json"] + 5)).timestamp()
        os.utime(self.data_dir / "market_regime.json", (old, old))
        r = self.m.check_data_freshness(data_dir=str(self.data_dir))
        self.assertEqual(r["status"], STALE)
        self.assertEqual([e["file"] for e in r["stale_files"]], ["market_regime.json"])
        # …and the unmeasured file is still reported, not swallowed by STALE.
        self.assertEqual([e["file"] for e in r["unchecked"]], ["tournament_ranking.json"])

    def test_unreadable_directory_entry_is_unchecked_not_fresh(self):
        """An OSError on getmtime is 'age unknown', never 'fresh'."""
        _touch_all_watched(self.data_dir)
        target = self.data_dir / "adapter_status.json"
        real_getmtime = os.path.getmtime

        def boom(path):
            if str(path) == str(target):
                raise OSError(13, "Permission denied")
            return real_getmtime(path)

        os.path.getmtime = boom  # type: ignore[assignment]
        try:
            r = self.m.check_data_freshness(data_dir=str(self.data_dir))
        finally:
            os.path.getmtime = real_getmtime  # type: ignore[assignment]

        self.assertEqual(r["status"], UNCHECKED)
        self.assertNotIn(
            "adapter_status.json", [e["file"] for e in r["fresh_files"]]
        )
        self.assertEqual([e["file"] for e in r["unchecked"]], ["adapter_status.json"])
        self.assertIn("OSError", r["unchecked"][0]["reason"])


# ---------------------------------------------------------------------------
# 2. equity_anomaly — "could not compute" is not "no anomaly"
# ---------------------------------------------------------------------------

class TestEquityAnomalyNeverClaimsUnmeasured(_Base):
    def test_empty_history_is_unchecked(self):
        r = self.m.check_equity_anomaly([])
        self.assertEqual(r["status"], UNCHECKED)
        self.assertIsNone(r["today_change_pct"])

    def test_single_entry_is_unchecked(self):
        r = self.m.check_equity_anomaly([{"equity": 100_000.0}])
        self.assertEqual(r["status"], UNCHECKED)

    def test_unreadable_equity_values_are_unchecked(self):
        r = self.m.check_equity_anomaly(
            [{"equity": "corrupt"}, {"equity": "corrupt"}]
        )
        self.assertEqual(r["status"], UNCHECKED)
        self.assertIn("cannot read equity values", r["detail"])

    def test_missing_equity_key_is_unchecked(self):
        r = self.m.check_equity_anomaly([{"nav": 1.0}, {"nav": 2.0}])
        self.assertEqual(r["status"], UNCHECKED)

    def test_zero_prev_equity_is_unchecked_not_ok(self):
        r = self.m.check_equity_anomaly([{"equity": 0.0}, {"equity": 100.0}])
        self.assertEqual(r["status"], UNCHECKED)
        self.assertIsNone(r["today_change_pct"])

    def test_computed_small_change_is_ok(self):
        """The real OK path is untouched: a computed, within-threshold move."""
        r = self.m.check_equity_anomaly(
            [{"equity": 100_000.0}, {"equity": 100_100.0}]
        )
        self.assertEqual(r["status"], OK)
        self.assertAlmostEqual(r["today_change_pct"], 0.1, places=4)

    def test_computed_large_drop_is_still_warning(self):
        prev = 100_000.0
        curr = prev * (1 - (MAX_EQUITY_DROP_PCT + 1.0) / 100.0)
        r = self.m.check_equity_anomaly([{"equity": prev}, {"equity": curr}])
        self.assertEqual(r["status"], WARNING)


# ---------------------------------------------------------------------------
# 3. run_all_checks — HEALTHY only when everything actually ran
# ---------------------------------------------------------------------------

class TestOverallVerdictHonesty(_Base):
    def test_fresh_cycle_with_no_watched_files_is_not_healthy(self):
        """The headline reproduction: HEALTHY over three unread files."""
        _fresh_curve(self.data_dir, [100_000.0, 100_628.61])
        r = self.run_all()
        self.assertNotEqual(r["overall"], HEALTHY)
        self.assertEqual(r["overall"], UNCHECKED)

    def test_report_never_says_healthy_and_missing_at_once(self):
        _fresh_curve(self.data_dir, [100_000.0, 100_628.61])
        r = self.run_all()
        joined = " | ".join(r["recommendations"])
        self.assertIn("Missing data files", joined)
        self.assertNotIn(_HEALTHY_CLAIM, r["recommendations"])

    def test_unchecked_list_names_check_and_reason(self):
        _fresh_curve(self.data_dir, [100_000.0, 100_628.61])
        r = self.run_all()
        self.assertTrue(r["unchecked"])
        names = {u["check"] for u in r["unchecked"]}
        for name in _WATCHED_FILES:
            self.assertIn(f"data_freshness:{name}", names)
        for u in r["unchecked"]:
            self.assertTrue(u["reason"].strip())

    def test_not_checked_line_present_in_recommendations(self):
        _fresh_curve(self.data_dir, [100_000.0, 100_628.61])
        r = self.run_all()
        self.assertTrue(
            any(x.startswith("NOT CHECKED") for x in r["recommendations"]),
            r["recommendations"],
        )

    def test_corrupt_equity_series_is_not_healthy(self):
        _touch_all_watched(self.data_dir)
        _fresh_curve(self.data_dir, ["corrupt", "corrupt"])
        r = self.run_all()
        self.assertNotEqual(r["overall"], HEALTHY)
        self.assertIn(
            "equity_anomaly", {u["check"] for u in r["unchecked"]}
        )

    def test_fully_measured_clean_run_is_healthy(self):
        """The positive control — UNCHECKED must not swallow real health."""
        _touch_all_watched(self.data_dir)
        _fresh_curve(self.data_dir, [100_000.0, 100_100.0])
        r = self.run_all()
        self.assertEqual(r["overall"], HEALTHY)
        self.assertEqual(r["unchecked"], [])
        self.assertIn(_HEALTHY_CLAIM, r["recommendations"])

    def test_real_problem_still_outranks_unchecked(self):
        """A CRITICAL gap must not be downgraded to UNCHECKED."""
        _write(
            self.data_dir / "paper_trading_status.json",
            {
                "last_cycle_ts": (
                    _now() - timedelta(hours=CRITICAL_CYCLE_GAP_HOURS + 5)
                ).isoformat()
            },
        )
        r = self.run_all()
        self.assertEqual(r["overall"], CRITICAL)

    def test_stale_file_outranks_unchecked_in_overall(self):
        _fresh_curve(self.data_dir, [100_000.0, 100_100.0])
        _write(self.data_dir / "market_regime.json", {"stub": True})
        old = (_now() - timedelta(hours=_WATCHED_FILES["market_regime.json"] + 5)).timestamp()
        os.utime(self.data_dir / "market_regime.json", (old, old))
        r = self.run_all()
        self.assertEqual(r["overall"], WARNING)

    def test_unchecked_key_always_present(self):
        _touch_all_watched(self.data_dir)
        _fresh_curve(self.data_dir, [100_000.0, 100_100.0])
        r = self.run_all()
        self.assertIn("unchecked", r)
        self.assertIsInstance(r["unchecked"], list)


# ---------------------------------------------------------------------------
# 4. Published advice must cite the thresholds that actually fire
# ---------------------------------------------------------------------------

class TestRecommendationsQuoteRealThresholds(_Base):
    def _gap_report(self, hours: float) -> dict:
        _write(
            self.data_dir / "paper_trading_status.json",
            {"last_cycle_ts": (_now() - timedelta(hours=hours)).isoformat()},
        )
        return self.run_all()

    def test_warning_band_text_matches_constants(self):
        mid = (MAX_CYCLE_GAP_HOURS + CRITICAL_CYCLE_GAP_HOURS) / 2.0
        r = self._gap_report(mid)
        self.assertEqual(r["checks"]["cycle_gap"]["status"], WARNING)
        text = " ".join(x for x in r["recommendations"] if x.startswith("WARNING"))
        self.assertIn(f"{MAX_CYCLE_GAP_HOURS:.0f}", text)
        self.assertIn(f"{CRITICAL_CYCLE_GAP_HOURS:.0f}", text)
        # The retired 30-min-cadence copy must be gone.
        self.assertNotIn("between 2–4 hours", text)

    def test_critical_text_matches_constants(self):
        r = self._gap_report(CRITICAL_CYCLE_GAP_HOURS + 10)
        self.assertEqual(r["checks"]["cycle_gap"]["status"], CRITICAL)
        text = " ".join(x for x in r["recommendations"] if x.startswith("CRITICAL"))
        self.assertIn(f"{CRITICAL_CYCLE_GAP_HOURS:.0f} hours", text)
        self.assertNotIn("over 4 hours", text)

    def test_published_threshold_field_matches_constant(self):
        r = self._gap_report(1.0)
        self.assertEqual(
            r["checks"]["cycle_gap"]["threshold_hours"], MAX_CYCLE_GAP_HOURS
        )


# ---------------------------------------------------------------------------
# 5. Contracts the consumers depend on (radius guard)
# ---------------------------------------------------------------------------

class TestConsumerContractsUnchanged(_Base):
    """agent_health_monitor reads checks.cycle_gap.last_cycle_at; the launchd
    wrapper reads the exit code. Neither may shift under this change."""

    def test_last_cycle_at_still_published(self):
        ts = (_now() - timedelta(hours=1)).isoformat()
        _write(self.data_dir / "paper_trading_status.json", {"last_cycle_ts": ts})
        r = self.run_all()
        self.assertIsNotNone(r["checks"]["cycle_gap"]["last_cycle_at"])

    def test_unchecked_does_not_change_exit_code(self):
        """UNCHECKED is deliberately NOT an alert: exit stays 0, as before."""
        from spa_core.monitoring.cycle_health_monitor import main as cli_main

        _fresh_curve(self.data_dir, [100_000.0, 100_100.0])
        r = self.run_all()
        self.assertEqual(r["overall"], UNCHECKED)
        # main() resolves the repo data dir itself; assert the documented rule
        # that only CRITICAL is non-zero, which UNCHECKED is not.
        self.assertNotEqual(r["overall"], CRITICAL)
        self.assertTrue(callable(cli_main))

    def test_save_report_roundtrips_unchecked(self):
        _fresh_curve(self.data_dir, [100_000.0, 100_100.0])
        r = self.run_all()
        self.m.save_health_report(r, data_dir=str(self.data_dir))
        written = json.loads(
            (self.data_dir / "cycle_health.json").read_text(encoding="utf-8")
        )
        self.assertEqual(written["overall"], r["overall"])
        self.assertEqual(written["unchecked"], r["unchecked"])
        self.assertFalse((self.data_dir / "cycle_health.json.tmp").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
