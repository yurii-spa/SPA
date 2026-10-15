"""P1 wave 2 (owner ARB review 2026-10-08): the public financial truth reconciles and is generated.

Three outcomes measured, each with a control in both directions:

1. **Book exposure is generated, not typed.** `generate_track_snapshot._book_exposure` turns the cycle's
   positions snapshot + registry tiers into rows; the shelf projects them with a `source` on every number.
   Control: an unreadable/empty positions file is `UNMEASURED` with a reason — never an empty table that
   reads as «holds nothing» (inv. #17).
2. **Rate, cumulative and total return carry their bases.** The shelf publishes the anchor NAV and the
   cumulative over the rate's OWN window, and the total return with its own base; the two NAVs and the
   window reproduce the annualised rate exactly (the reconciliation is arithmetic, not prose).
3. **Prose percentages follow ADR-660.** `pct_format.pctText` rewrites a percentage inside generated prose
   by the same rule as `fmtPct2` (real `node` runs the real module).
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: fixture dates are the subject (a published snapshot's anchor/start/measurement dates); no freshness is judged
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gts = _load("_gts_p1w2", "scripts/generate_track_snapshot.py")
bsn = _load("_bsn_p1w2", "scripts/build_site_numbers.py")

POSITIONS = {
    "generated_at": "2026-10-08T07:51:18+00:00",
    "cash_usd": 5000.0,
    "positions": {"maple": 20000.0, "fluid_fusdc": 20000.0, "morpho_blue_base": 10000.0,
                  "compound_v3": 40000.0, "aave_v3": 5000.0},
}


class BookExposureIsGenerated(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_p1w2_"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _write(self, doc) -> Path:
        p = self.d / "current_positions.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    def test_rows_carry_amount_share_and_the_registry_tier(self):
        be = gts._book_exposure(self._write(POSITIONS))
        self.assertEqual(be["state"], "MEASURED")
        self.assertEqual(be["base_usd"], 100000.0)
        rows = {r["protocol"]: r for r in be["rows"]}
        self.assertEqual(set(rows), set(POSITIONS["positions"]))
        self.assertEqual(rows["compound_v3"]["share_pct"], 40.0)
        self.assertEqual(rows["fluid_fusdc"]["share_pct"], 20.0)
        # the tier is the canonical registry's, whatever it is — never a typed «T1» default
        from spa_core.risk.concentration_monitor import _tier_map
        tmap = _tier_map()
        for p, r in rows.items():
            self.assertEqual(r["tier"], tmap.get(p) or "unlabelled", p)
        # largest holding first: the order a reader checks concentration in
        self.assertEqual(be["rows"][0]["protocol"], "compound_v3")
        self.assertEqual(round(sum(r["share_pct"] for r in be["rows"]) + be["cash_share_pct"], 6), 100.0)

    def test_unreadable_or_empty_positions_are_unmeasured_not_an_empty_book(self):
        for doc in ({}, {"positions": {}, "cash_usd": 5000.0}, {"positions": {"aave_v3": 1.0}},
                    {"positions": {"aave_v3": 1.0}, "cash_usd": True}):
            be = gts._book_exposure(self._write(doc))
            self.assertEqual(be["state"], "UNMEASURED", doc)
            self.assertIsNone(be["rows"], doc)
            self.assertTrue(be["reason"], doc)
        self.assertEqual(gts._book_exposure(self.d / "missing.json")["state"], "UNMEASURED")


SNAP = {
    "as_of": "2026-10-08", "generated_at": "2026-10-08T07:52:23Z",
    "real_track_days": 107, "evidenced_anchor": "2026-06-22",
    "paper_apy_pct": 4.8971, "max_drawdown_pct": -0.0393, "nav_usd": 101564.21, "end_equity": 101564.21,
    "anchor_equity": 100150.66, "track_end_date": "2026-10-08", "track_return_pct": 1.4114,
    "total_return_pct": 1.5642, "paper_start_date": "2026-06-10",
    "gates_passed": 29, "gates_total": 29, "go_live_state": "gate_passed_owner_decision_pending",
    "paper_tracks": {"conservative": {"status": "paper_test_running", "days_with_positions": 107,
                                      "apy_pct": 4.8971, "dd_pct": -0.0393, "nav_usd": 101564.21,
                                      "evidence": "paper"}},
    "book_exposure": {"state": "MEASURED", "as_of": "2026-10-08T07:51:18+00:00",
                      "base": "allocated paper capital = positions + cash", "base_usd": 100000.0,
                      "cash_usd": 5000.0, "cash_share_pct": 5.0,
                      "rows": [{"protocol": "compound_v3", "tier": "T1", "usd": 40000.0, "share_pct": 40.0}],
                      "source": "x"},
}
CONST = {"kill_switch": {"soft_derisk_pct": 5.0, "hard_kill_pct": 10.0}, "chain_caps": {},
         "start_capital_usd": 100000.0}


class TheShelfCarriesTheBases(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_p1w2s_"))
        self._s, self._c = bsn.SNAPSHOT, bsn.CONSTITUTION
        bsn.SNAPSHOT, bsn.CONSTITUTION = self.d / "s.json", self.d / "c.json"

    def tearDown(self):
        bsn.SNAPSHOT, bsn.CONSTITUTION = self._s, self._c
        shutil.rmtree(self.d, ignore_errors=True)

    def _build(self, snap):
        bsn.SNAPSHOT.write_text(json.dumps(snap), encoding="utf-8")
        bsn.CONSTITUTION.write_text(json.dumps(CONST), encoding="utf-8")
        return bsn.build(published_at="2026-10-08")

    def test_the_two_navs_and_the_window_reproduce_the_rate(self):
        doc = self._build(SNAP)
        h = doc["headline"]
        a, e, n = h["anchor_nav"]["value"], h["nav"]["value"], h["evidenced_days"]["value"]
        self.assertAlmostEqual(((e / a) ** (365.0 / n) - 1.0) * 100.0, h["apy"]["value"], places=3)
        self.assertAlmostEqual((e / a - 1.0) * 100.0, h["track_return"]["value"], places=3)
        # the total return has ITS base, published beside it — not the rate's
        self.assertEqual(doc["track"]["paper_start_date"], "2026-06-10")
        self.assertEqual(doc["track"]["total_return_since_start"]["value"], 1.5642)
        self.assertNotEqual(doc["track"]["total_return_since_start"]["value"], h["track_return"]["value"])

    def test_every_new_number_names_its_source_and_kind(self):
        doc = self._build(SNAP)
        figs = [doc["headline"]["anchor_nav"], doc["headline"]["track_return"],
                doc["track"]["total_return_since_start"], doc["exposure"]["base_usd"],
                doc["exposure"]["cash"], doc["exposure"]["cash_share"]]
        figs += [r[k] for r in doc["exposure"]["rows"] for k in ("usd", "share")]
        for f in figs:
            self.assertIn("track_snapshot.json", f["source"])
            self.assertEqual(f["kind"], bsn.MEASUREMENT)
        self.assertEqual(bsn.validate_shelf(doc), [])

    def test_absent_exposure_and_bases_are_unmeasured_not_zero(self):
        snap = {k: v for k, v in SNAP.items()
                if k not in ("book_exposure", "anchor_equity", "track_return_pct", "total_return_pct")}
        doc = self._build(snap)
        self.assertEqual(doc["exposure"]["state"], "UNMEASURED")
        self.assertIsNone(doc["exposure"]["rows"])
        for f in (doc["headline"]["anchor_nav"], doc["headline"]["track_return"],
                  doc["track"]["total_return_since_start"]):
            self.assertIsNone(f["value"])
            self.assertTrue(f["unavailable_reason"])

    def test_the_shape_change_is_a_new_schema(self):
        # a new shape needs an explicit owner approval at the publication gate (verify_publication)
        self.assertEqual(bsn.SCHEMA_VERSION, "site_numbers/3")


def _node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.fail("НЕ ИЗМЕРЕНО: `node` не найден — исход JS не наблюдён")
    return found


def test_prose_percentages_follow_the_one_rule(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "pct_format.js").write_text((ROOT / "landing/src/lib/pct_format.js").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    cases = [["PT fixed rate (5.146 %) clears the floor (3.857 %)", False],
             ["BTC −52% and ETH −55% in ~26 hours", False],
             ["ставка 2–6% годовых", True],
             ["peg 2.675% tie", False],
             ["no percent here", False]]
    (lib / "ask.mjs").write_text(
        "import { pctText } from './pct_format.js';\n"
        f"const cs = {json.dumps(cases, ensure_ascii=False)};\n"
        "console.log(JSON.stringify(cs.map(([s, ru]) => pctText(s, ru))));\n", encoding="utf-8")
    out = subprocess.run([_node(), str(lib / "ask.mjs")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got == ["PT fixed rate (5.15%) clears the floor (3.86%)",
                   "BTC −52.00% and ETH −55.00% in ~26 hours",
                   "ставка 2,00–6,00 % годовых",
                   "peg 2.68% tie",          # decimal half-up, not binary toFixed (2.67)
                   "no percent here"]
