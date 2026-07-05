"""RTMR (ADR-053) API router tests — read-only surface, fail-safe on missing files."""
from __future__ import annotations

import unittest

from spa_core.api.routers import rtmr


class TestRtmrApi(unittest.TestCase):
    def test_status_shape(self) -> None:
        s = rtmr.rtmr_status()
        for k in ("mode", "alive", "max_severity", "sources", "portfolio_posture", "active_postures"):
            self.assertIn(k, s)
        self.assertEqual(s["mode"], "paper")

    def test_signals_returns_dict(self) -> None:
        self.assertIsInstance(rtmr.rtmr_signals(), dict)

    def test_posture_has_entries(self) -> None:
        self.assertIn("entries", rtmr.rtmr_posture())

    def test_reactions_limit(self) -> None:
        r = rtmr.rtmr_reactions(limit=5)
        self.assertIn("recent", r)
        self.assertLessEqual(len(r["recent"]), 5)

    def test_read_missing_file_failsafe(self) -> None:
        from pathlib import Path
        self.assertEqual(rtmr._read(Path("/nonexistent/x.json"), {"ok": 1}), {"ok": 1})


if __name__ == "__main__":
    unittest.main()
