"""Tests for the EVIDENCED equity / go-live track hash chain (F2).

The track-record page tells reviewers the equity track is verifiable via
`verify_spa.py data/rates_desk/`. These tests prove that claim is TRUE end to
end: the producer (spa_core.audit.equity_proof_chain) builds a single-genesis
hash chain over ONLY the evidenced bars, and the standalone zero-dependency
verifier (scripts/verify_spa.py) re-derives it and catches any tamper at the
exact broken_at.

Pure stdlib / unittest, hermetic (tempdir), no network, no spa_core import on
the verifier side (loaded as a standalone module the way a reviewer would run it).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.audit import equity_proof_chain as epc


def _load_verifier():
    """Load scripts/verify_spa.py as a standalone module (no package import)."""
    path = _REPO_ROOT / "scripts" / "verify_spa.py"
    spec = importlib.util.spec_from_file_location("verify_spa_standalone", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# An equity file with: 2 warmup (not evidenced), 1 backfill (not evidenced),
# 3 evidenced cycle bars. Only the 3 evidenced ones should enter the chain.
_EQUITY_DOC = {
    "summary": {"real_days": 3},
    "daily": [
        {"date": "2026-06-08", "open_equity": 100000.0, "close_equity": 100000.0,
         "is_warmup": True, "source": "warmup", "evidenced": False},
        {"date": "2026-06-09", "open_equity": 100000.0, "close_equity": 100001.0,
         "is_warmup": True, "source": "warmup", "evidenced": False},
        {"date": "2026-06-22", "open_equity": 100100.0, "close_equity": 100110.0,
         "daily_yield_usd": 10.0, "apy_today": 3.6, "source": "cycle", "evidenced": True},
        {"date": "2026-06-23", "open_equity": 100110.0, "close_equity": 100121.0,
         "daily_yield_usd": 11.0, "apy_today": 3.7, "source": "cycle", "evidenced": True},
        {"date": "2026-06-24", "open_equity": 100121.0, "close_equity": 100120.0,
         "daily_yield_usd": -1.0, "apy_today": 0.0, "source": "cycle", "evidenced": True},
        {"date": "2026-06-25", "open_equity": 100120.0, "close_equity": 100130.0,
         "source": "backfill", "evidenced": False},
    ],
}


class TestEquityProofChain(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.equity = self.tmp / "equity_curve_daily.json"
        self.equity.write_text(json.dumps(_EQUITY_DOC), encoding="utf-8")
        self.out = self.tmp / "rates_desk" / "equity_track.jsonl"
        self.verifier = _load_verifier()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build(self):
        return epc.write_chain(self.equity, self.out)

    # ── producer: only evidenced bars enter the chain ───────────────────────
    def test_only_evidenced_bars_chained(self):
        rep = self._build()
        self.assertEqual(rep["rows"], 3, "only the 3 evidenced cycle bars must be chained")
        rows = [json.loads(l) for l in self.out.read_text().splitlines() if l.strip()]
        self.assertEqual([r["date"] for r in rows],
                         ["2026-06-22", "2026-06-23", "2026-06-24"])
        # genesis + contiguous seq + linkage
        self.assertEqual(rows[0]["prev_hash"], "0" * 64)
        self.assertEqual([r["seq"] for r in rows], [0, 1, 2])
        for i in range(1, len(rows)):
            self.assertEqual(rows[i]["prev_hash"], rows[i - 1]["entry_hash"])

    def test_determinism(self):
        h1 = self._build()["head_hash"]
        h2 = self._build()["head_hash"]
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    # ── verifier: clean chain reproduces ────────────────────────────────────
    def test_standalone_verifier_reproduces(self):
        self._build()
        report = self.verifier.run([str(self.out)])
        et = report["equity_track"]
        self.assertTrue(et["valid"])
        self.assertEqual(et["n_days"], 3)
        self.assertEqual(et["broken_at"], None)
        self.assertEqual(et["first_date"], "2026-06-22")
        self.assertEqual(et["last_date"], "2026-06-24")
        self.assertEqual(report["ok"], True)

    # ── verifier catches a forged equity value at the exact row ─────────────
    def test_forged_equity_value_detected(self):
        self._build()
        rows = [json.loads(l) for l in self.out.read_text().splitlines() if l.strip()]
        rows[1]["close_equity"] = 999999.0  # forge day index 1
        self.out.write_text(
            "".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n"
                    for r in rows), encoding="utf-8")
        report = self.verifier.run([str(self.out)])
        self.assertFalse(report["equity_track"]["valid"])
        self.assertEqual(report["equity_track"]["broken_at"], 1)
        self.assertFalse(report["ok"])

    # ── verifier catches a reordered / dropped day (prev_hash linkage) ──────
    def test_dropped_day_detected(self):
        self._build()
        rows = [json.loads(l) for l in self.out.read_text().splitlines() if l.strip()]
        del rows[1]  # drop the middle day; seq now non-contiguous / linkage breaks
        self.out.write_text(
            "".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n"
                    for r in rows), encoding="utf-8")
        report = self.verifier.run([str(self.out)])
        self.assertFalse(report["equity_track"]["valid"])

    # ── empty evidenced series → honest empty chain, vacuously valid ────────
    def test_empty_chain_is_valid(self):
        doc = {"summary": {}, "daily": [
            {"date": "2026-06-08", "is_warmup": True, "source": "warmup", "evidenced": False},
        ]}
        self.equity.write_text(json.dumps(doc), encoding="utf-8")
        rep = self._build()
        self.assertEqual(rep["rows"], 0)
        self.assertIsNone(rep["head_hash"])
        report = self.verifier.run([str(self.out)])
        self.assertTrue(report["equity_track"]["valid"])

    # ── the verifier recipe and the producer recipe agree byte-for-byte ─────
    def test_recipes_agree(self):
        self._build()
        rows = [json.loads(l) for l in self.out.read_text().splitlines() if l.strip()]
        for r in rows:
            self.assertEqual(self.verifier.recompute_equity_entry_hash(r), r["entry_hash"])


if __name__ == "__main__":
    unittest.main()
