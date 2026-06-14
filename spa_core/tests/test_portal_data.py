"""Тесты MP-408 — investor portal offline core (spa_core/reporting/portal_data.py
+ статические проверки investor_portal.html).

unittest (НЕ pytest), без сети; вся персистентность — только в tempdir.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.governance.capital_ladder import detect_incidents
from spa_core.reporting import portal_data as pd
from spa_core.reporting import tear_sheet as ts

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "spa_core" / "reporting" / "portal_data.py"
PORTAL_HTML = REPO_ROOT / "investor_portal.html"

# Дневные return'ы (%) после seed-бара: известные значения для ручных пересчётов.
RETURNS = [1.0, -1.5, 0.5, 0.2]

EQUITY_DOC = {
    "is_demo": False,
    "execution_mode": "read_only_simulation",
    "daily": [
        # глобальный seed-бар (его 0.0 — заглушка, исключается из P&L)
        {"date": "2026-06-10", "daily_return_pct": 0.0,
         "close_equity": 100000.0, "drawdown_pct": 0.0},
        {"date": "2026-06-11", "daily_return_pct": 1.0,
         "close_equity": 101000.0, "drawdown_pct": 0.0},
        {"date": "2026-06-12", "daily_return_pct": -1.5,
         "close_equity": 99485.0, "drawdown_pct": -1.5},
        {"date": "2026-06-13", "daily_return_pct": 0.5,
         "close_equity": 99982.4, "drawdown_pct": -1.0075},
        {"date": "2026-06-14", "daily_return_pct": 0.2,
         "close_equity": 100182.4, "drawdown_pct": -0.8095},
    ],
}

POSITIONS_DOC = {
    "generated_at": "2026-06-14T06:00:00+00:00",
    "is_demo": False,
    "capital_usd": 100000.0,
    "deployed_usd": 95000.0,
    "cash_usd": 5000.0,
    "positions": {
        "aave_v3": 40000.0,
        "compound_v3": 30000.0,
        "maple": 25000.0,
    },
}

ORCH_DOC = {
    "adapters": [
        {"protocol": "aave_v3", "tier": "T1", "chain": "ethereum"},
        {"protocol": "compound_v3", "tier": "T1", "chain": "ethereum"},
        {"protocol": "morpho_blue", "tier": "T2", "chain": "base"},
    ],
}

RISK_SCORES_DOC = {
    "scores": [
        {"protocol": "Aave V3", "slug": "aave-v3",
         "grade": "B", "score_numeric": 0.7922},
        {"protocol": "Compound V3", "slug": "compound-v3",
         "grade": "B", "score_numeric": 0.7678},
        "junk", 42,
        {"protocol": "", "grade": "A"},  # пустое имя — пропускается
    ],
}

TEAR_SHEET_DOC = {
    "meta": {"period": "2026-06"},
    "performance": {"net_return_pct": 0.19, "annualized_apy_pct": 3.22,
                    "win_rate_pct": 75.0},
    "risk": {"sharpe_ratio": 1.5, "sortino_ratio": 2.1,
             "max_drawdown_pct": -1.5, "psr": {"psr": 0.91}},
}

LADDER_DOC = {
    "current_level": 0,
    "level_code": "L0",
    "level_name": "paper",
    "aum_cap_usd": 100000.0,
    "aum_usd": 100182.4,
    "track_days": 23,
    "incidents_total": 1,
    "last_incident": {"date": "2026-06-12", "loss_pct": -1.5},
    "climb": {"eligible": False, "blockers": ["track_days_ge_30: need >= 30"]},
}

ANCHORS_DOC = {
    "schema_version": 1,
    "anchors": [
        {"date": "2026-06-12", "merkle_root": None, "leaf_count": 0,
         "published": False, "tx_hash": None, "note": "empty day"},
        {"date": "2026-06-11", "merkle_root": "ab" * 32, "leaf_count": 3,
         "published": True, "tx_hash": "0xdead"},
        "junk", {"date": "not-a-date"},
    ],
}

GOLIVE_DOC = {"ready": True}

PT_DOC = {
    "is_demo": False,
    "execution_mode": "read_only_simulation",
    "paper_start_date": "2026-05-20",
    "last_cycle_ts": "2026-06-14T06:00:00+00:00",
    "days_running": 23,
    "current_equity": 100182.4,
    "apy_today_pct": 3.17,
}


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _write_audit_trail(path: Path, n: int, broken: bool = False) -> None:
    lines = []
    for i in range(n):
        lines.append(json.dumps({
            "event_id": f"e{i}",
            "correlation_id": f"c{i}",
            "event_type": "cycle_start",
            "timestamp": f"2026-06-14T00:00:{i % 60:02d}+00:00",
            "data": {"i": i},
        }))
        if broken and i % 10 == 0:
            lines.append("{broken json line!!!")
            lines.append('"not a dict"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compound(returns) -> float:
    growth = 1.0
    for r in returns:
        growth *= (1.0 + r / 100.0)
    return (growth - 1.0) * 100.0


class PortalBase(unittest.TestCase):
    """Общий tempdir-каркас: data_dir в tempdir, никакой записи в репо."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        self.data_dir.mkdir(parents=True)

    def write_all_sources(self, audit_events: int = 5):
        _write_json(self.data_dir / pd.EQUITY_FILENAME, EQUITY_DOC)
        _write_json(self.data_dir / pd.POSITIONS_FILENAME, POSITIONS_DOC)
        _write_json(self.data_dir / pd.ORCH_STATUS_FILENAME, ORCH_DOC)
        _write_json(self.data_dir / pd.RISK_SCORES_FILENAME, RISK_SCORES_DOC)
        _write_json(self.data_dir / pd.TEAR_SHEET_FILENAME, TEAR_SHEET_DOC)
        _write_json(self.data_dir / pd.LADDER_STATUS_FILENAME, LADDER_DOC)
        _write_json(self.data_dir / pd.ANCHORS_FILENAME, ANCHORS_DOC)
        _write_json(self.data_dir / pd.GOLIVE_STATUS_FILENAME, GOLIVE_DOC)
        _write_json(self.data_dir / pd.PT_STATUS_FILENAME, PT_DOC)
        _write_audit_trail(self.data_dir / pd.AUDIT_TRAIL_FILENAME, audit_events)

    def build(self):
        return pd.build_portal_data(data_dir=self.data_dir)

    def no_tmp_leftovers(self):
        stray = [p for p in self.data_dir.rglob("*") if p.name.endswith(".tmp")]
        self.assertEqual(stray, [], f"stray tmp files: {stray}")


# ─── нормализация имён протоколов ────────────────────────────────────────────


class TestNormalizeProtocol(unittest.TestCase):
    def test_display_name(self):
        self.assertEqual(pd.normalize_protocol("Aave V3"), "aave_v3")

    def test_slug(self):
        self.assertEqual(pd.normalize_protocol("aave-v3"), "aave_v3")

    def test_already_normalized(self):
        self.assertEqual(pd.normalize_protocol("aave_v3"), "aave_v3")

    def test_non_string(self):
        self.assertEqual(pd.normalize_protocol(42), "42")


# ─── equity / P&L ────────────────────────────────────────────────────────────


class TestEquitySection(unittest.TestCase):
    def test_curve_includes_all_bars(self):
        eq = pd.build_equity_section(EQUITY_DOC)
        self.assertTrue(eq["available"])
        self.assertEqual(eq["num_days"], 5)
        self.assertEqual(eq["first_date"], "2026-06-10")
        self.assertEqual(eq["last_date"], "2026-06-14")
        self.assertEqual(eq["curve"][0]["equity"], 100000.0)

    def test_seed_bar_excluded_from_pnl(self):
        eq = pd.build_equity_section(EQUITY_DOC)
        self.assertEqual(eq["pnl"]["num_return_days"], len(RETURNS))
        self.assertEqual([p["return_pct"] for p in eq["pnl"]["daily"]], RETURNS)
        self.assertEqual(eq["pnl"]["daily"][0]["date"], "2026-06-11")

    def test_total_pnl_manual_recompute(self):
        eq = pd.build_equity_section(EQUITY_DOC)
        self.assertAlmostEqual(eq["pnl"]["total_return_pct"],
                               _compound(RETURNS), places=5)

    def test_today_return_is_last_bar(self):
        eq = pd.build_equity_section(EQUITY_DOC)
        self.assertEqual(eq["pnl"]["today_return_pct"], RETURNS[-1])

    def test_max_drawdown_manual(self):
        # пик после +1%, затем -1.5% → maxDD = -1.5%
        eq = pd.build_equity_section(EQUITY_DOC)
        self.assertAlmostEqual(eq["pnl"]["max_drawdown_pct"], -1.5, places=4)

    def test_pnl_math_reused_from_tear_sheet(self):
        # та же математика, что в MP-501 (переиспользование импортом)
        eq = pd.build_equity_section(EQUITY_DOC)
        self.assertAlmostEqual(eq["pnl"]["total_return_pct"],
                               ts.compound_return_pct(RETURNS), places=6)
        self.assertAlmostEqual(eq["pnl"]["max_drawdown_pct"],
                               ts.max_drawdown_from_returns(RETURNS), places=6)

    def test_missing_doc_honest_unavailable(self):
        for doc in (None, [], "junk", {"daily": "junk"}, {"daily": []}):
            eq = pd.build_equity_section(doc)
            self.assertFalse(eq["available"], doc)
            self.assertIsNone(eq["pnl"]["total_return_pct"])
            self.assertEqual(eq["curve"], [])

    def test_garbage_bars_skipped(self):
        doc = {"daily": [
            {"date": "2026-06-10", "daily_return_pct": 0.0, "close_equity": 1.0},
            "junk", 42, {"date": "bad"},
            {"date": "2026-06-11", "daily_return_pct": 0.5, "close_equity": 1.0},
        ]}
        eq = pd.build_equity_section(doc)
        self.assertEqual(eq["num_days"], 2)
        self.assertEqual(eq["pnl"]["num_return_days"], 1)

    def test_non_numeric_returns_skipped(self):
        doc = {"daily": [
            {"date": "2026-06-10", "daily_return_pct": 0.0},
            {"date": "2026-06-11", "daily_return_pct": "oops"},
            {"date": "2026-06-12", "daily_return_pct": True},
            {"date": "2026-06-13", "daily_return_pct": 0.3},
        ]}
        eq = pd.build_equity_section(doc)
        self.assertEqual([p["return_pct"] for p in eq["pnl"]["daily"]], [0.3])

    def test_only_seed_bar_no_returns(self):
        doc = {"daily": [{"date": "2026-06-10", "daily_return_pct": 0.0,
                          "close_equity": 100000.0}]}
        eq = pd.build_equity_section(doc)
        self.assertTrue(eq["available"])
        self.assertEqual(eq["pnl"]["num_return_days"], 0)
        self.assertIsNone(eq["pnl"]["total_return_pct"])
        self.assertIsNone(eq["pnl"]["today_return_pct"])


# ─── risk grades ─────────────────────────────────────────────────────────────


class TestGrades(unittest.TestCase):
    def test_known_protocols_graded(self):
        grades = pd.build_position_grades(POSITIONS_DOC, RISK_SCORES_DOC)
        self.assertTrue(grades["aave_v3"]["known"])
        self.assertEqual(grades["aave_v3"]["grade"], "B")
        self.assertAlmostEqual(grades["aave_v3"]["score_numeric"], 0.7922)

    def test_unknown_protocol_honest_null(self):
        grades = pd.build_position_grades(POSITIONS_DOC, RISK_SCORES_DOC)
        self.assertFalse(grades["maple"]["known"])
        self.assertIsNone(grades["maple"]["grade"])
        self.assertIsNone(grades["maple"]["score_numeric"])

    def test_display_name_and_slug_both_indexed(self):
        index = pd.build_grade_index(RISK_SCORES_DOC)
        self.assertIn("aave_v3", index)
        self.assertEqual(index["compound_v3"]["grade"], "B")

    def test_missing_scores_all_unknown(self):
        grades = pd.build_position_grades(POSITIONS_DOC, None)
        self.assertTrue(all(not g["known"] for g in grades.values()))

    def test_garbage_inputs_tolerated(self):
        self.assertEqual(pd.build_position_grades(None, RISK_SCORES_DOC), {})
        self.assertEqual(pd.build_position_grades("junk", "junk"), {})
        self.assertEqual(pd.build_grade_index({"scores": "junk"}), {})
        self.assertEqual(pd.build_grade_index([1, 2]), {})


# ─── chain exposure ──────────────────────────────────────────────────────────


class TestChainExposure(unittest.TestCase):
    def _exposure(self):
        return ts.build_exposure(POSITIONS_DOC, ORCH_DOC)

    def test_chains_grouped(self):
        by_chain = pd.build_chain_exposure(self._exposure(), ORCH_DOC)
        # aave 40% + compound 30% — оба ethereum; maple — нет в оркестраторе
        self.assertAlmostEqual(by_chain["ethereum"], 70.0)
        self.assertAlmostEqual(by_chain["unknown"], 25.0)

    def test_no_chain_field_honest_unknown(self):
        orch = {"adapters": [{"protocol": "aave_v3", "tier": "T1"}]}
        by_chain = pd.build_chain_exposure(
            ts.build_exposure(POSITIONS_DOC, orch), orch)
        self.assertEqual(set(by_chain), {"unknown"})
        self.assertAlmostEqual(by_chain["unknown"], 95.0)

    def test_garbage_inputs(self):
        self.assertEqual(pd.build_chain_exposure(None, None), {})
        self.assertEqual(pd.build_chain_exposure({"by_protocol": "junk"}, ORCH_DOC), {})


# ─── tear-sheet headline / ladder / anchors / audit ──────────────────────────


class TestTearSheetHeadline(unittest.TestCase):
    def test_metrics_extracted(self):
        tear = pd.tear_sheet_headline(TEAR_SHEET_DOC)
        self.assertTrue(tear["available"])
        self.assertEqual(tear["period"], "2026-06")
        self.assertAlmostEqual(tear["annualized_apy_pct"], 3.22)
        self.assertAlmostEqual(tear["sharpe_ratio"], 1.5)
        self.assertAlmostEqual(tear["psr"], 0.91)
        self.assertAlmostEqual(tear["max_drawdown_pct"], -1.5)

    def test_missing_unavailable(self):
        for doc in (None, [], "junk"):
            tear = pd.tear_sheet_headline(doc)
            self.assertFalse(tear["available"], doc)
            self.assertIsNone(tear["sharpe_ratio"])

    def test_partial_doc_tolerated(self):
        tear = pd.tear_sheet_headline({"meta": "junk", "risk": {"psr": "junk"}})
        self.assertTrue(tear["available"])
        self.assertIsNone(tear["period"])
        self.assertIsNone(tear["psr"])


class TestLadderSnapshot(unittest.TestCase):
    def test_snapshot_fields(self):
        snap = pd.ladder_snapshot(LADDER_DOC)
        self.assertEqual(snap["level_code"], "L0")
        self.assertEqual(snap["incidents_total"], 1)
        self.assertEqual(snap["last_incident"]["date"], "2026-06-12")
        self.assertIs(snap["climb_eligible"], False)
        self.assertEqual(len(snap["climb_blockers"]), 1)

    def test_missing_none(self):
        self.assertIsNone(pd.ladder_snapshot(None))
        self.assertIsNone(pd.ladder_snapshot("junk"))


class TestAnchors(unittest.TestCase):
    def test_sorted_and_garbage_skipped(self):
        anchors = pd.collect_anchors(ANCHORS_DOC)
        self.assertEqual([a["date"] for a in anchors],
                         ["2026-06-11", "2026-06-12"])

    def test_published_and_null_root_honest(self):
        anchors = pd.collect_anchors(ANCHORS_DOC)
        self.assertTrue(anchors[0]["published"])
        self.assertEqual(anchors[0]["merkle_root"], "ab" * 32)
        self.assertFalse(anchors[1]["published"])
        self.assertIsNone(anchors[1]["merkle_root"])

    def test_garbage_doc_empty(self):
        for doc in (None, [], "junk", {"anchors": "junk"}):
            self.assertEqual(pd.collect_anchors(doc), [], doc)


class TestAuditEvents(PortalBase):
    def test_missing_file_none(self):
        self.assertIsNone(
            pd.read_audit_events(self.data_dir / pd.AUDIT_TRAIL_FILENAME))

    def test_last_100_of_120(self):
        path = self.data_dir / pd.AUDIT_TRAIL_FILENAME
        _write_audit_trail(path, 120)
        events = pd.read_audit_events(path)
        self.assertEqual(len(events), pd.AUDIT_EVENTS_MAX)
        # сохраняются именно ПОСЛЕДНИЕ события
        self.assertEqual(events[-1]["event_id"], "e119")
        self.assertEqual(events[0]["event_id"], "e20")

    def test_broken_lines_skipped(self):
        path = self.data_dir / pd.AUDIT_TRAIL_FILENAME
        _write_audit_trail(path, 5, broken=True)
        events = pd.read_audit_events(path)
        self.assertEqual(len(events), 5)
        self.assertTrue(all(isinstance(e, dict) for e in events))

    def test_empty_file_empty_list(self):
        path = self.data_dir / pd.AUDIT_TRAIL_FILENAME
        path.write_text("", encoding="utf-8")
        self.assertEqual(pd.read_audit_events(path), [])


# ─── build_portal_data ───────────────────────────────────────────────────────


class TestBuildPortalData(PortalBase):
    def test_sections_present(self):
        self.write_all_sources()
        doc = self.build()
        for section in ("meta", "headline", "equity", "exposure", "risk",
                        "tear_sheet", "capital_ladder", "proof_of_track",
                        "audit_trail", "notes"):
            self.assertIn(section, doc)

    def test_meta_fields(self):
        self.write_all_sources()
        meta = self.build()["meta"]
        self.assertIs(meta["advisory_only"], True)
        self.assertIs(meta["is_demo"], False)
        self.assertIn("NOT investment advice", meta["disclaimer"])
        self.assertEqual(meta["source_files"], list(pd.SOURCE_FILES))
        self.assertEqual(meta["track"]["real_track_start"], "2026-06-10")
        self.assertEqual(meta["track"]["days_running"], 23)
        self.assertIs(meta["track"]["golive_ready"], True)
        self.assertIn("generated_at", meta)

    def test_headline_happy_path(self):
        self.write_all_sources()
        h = self.build()["headline"]
        self.assertEqual(h["aum_usd"], 100000.0)
        self.assertAlmostEqual(h["cash_pct"], 5.0)
        self.assertAlmostEqual(h["total_return_pct"], _compound(RETURNS), places=5)
        self.assertAlmostEqual(h["net_apy_pct"], 3.22)
        self.assertAlmostEqual(h["sharpe_ratio"], 1.5)
        self.assertEqual(h["ladder_level_code"], "L0")
        self.assertEqual(h["track_days"], 23)

    def test_exposure_reuses_tear_sheet_logic(self):
        self.write_all_sources()
        exp = self.build()["exposure"]
        expected = ts.build_exposure(POSITIONS_DOC, ORCH_DOC)
        self.assertTrue(exp["available"])
        self.assertEqual(exp["by_protocol"], expected["by_protocol"])
        self.assertEqual(exp["by_tier"], expected["by_tier"])
        self.assertAlmostEqual(exp["by_chain"]["ethereum"], 70.0)

    def test_risk_grades_and_incidents(self):
        self.write_all_sources()
        risk = self.build()["risk"]
        self.assertEqual(risk["grades"]["aave_v3"]["grade"], "B")
        self.assertFalse(risk["grades"]["maple"]["known"])
        # инцидент -1.5% детектится переиспользованной detect_incidents
        self.assertEqual(risk["incidents"]["count"], 1)
        self.assertEqual(risk["incidents"]["items"][0]["date"], "2026-06-12")
        bars = pd.valid_bars(EQUITY_DOC["daily"])
        self.assertEqual(risk["incidents"]["items"], detect_incidents(bars))
        self.assertEqual(risk["incidents"]["incidents_total_track"], 1)

    def test_proof_of_track_section(self):
        self.write_all_sources()
        pot = self.build()["proof_of_track"]
        self.assertTrue(pot["available"])
        self.assertEqual(pot["anchors_count"], 2)
        self.assertEqual(pot["published_count"], 1)
        self.assertIsNone(pot["latest_root"])  # последний якорь — пустой день

    def test_audit_trail_section(self):
        self.write_all_sources(audit_events=7)
        at = self.build()["audit_trail"]
        self.assertTrue(at["available"])
        self.assertEqual(at["events_returned"], 7)
        self.assertEqual(at["limit"], pd.AUDIT_EVENTS_MAX)

    def test_each_source_missing_honest_note(self):
        # для КАЖДОГО источника: без него сборка не падает и пишет note
        cases = {
            pd.EQUITY_FILENAME: lambda d: not d["equity"]["available"],
            pd.POSITIONS_FILENAME: lambda d: not d["exposure"]["available"],
            pd.ORCH_STATUS_FILENAME: lambda d: True,
            pd.RISK_SCORES_FILENAME:
                lambda d: not d["risk"]["grades"]["aave_v3"]["known"],
            pd.TEAR_SHEET_FILENAME: lambda d: not d["tear_sheet"]["available"],
            pd.LADDER_STATUS_FILENAME: lambda d: d["capital_ladder"] is None,
            pd.ANCHORS_FILENAME: lambda d: not d["proof_of_track"]["available"],
            pd.GOLIVE_STATUS_FILENAME:
                lambda d: d["meta"]["track"]["golive_ready"] is None,
            pd.PT_STATUS_FILENAME:
                lambda d: d["meta"]["track"]["days_running"] is None,
            pd.AUDIT_TRAIL_FILENAME: lambda d: not d["audit_trail"]["available"],
        }
        for missing, check in cases.items():
            with self.subTest(missing=missing):
                self.write_all_sources()
                (self.data_dir / missing).unlink()
                doc = self.build()
                self.assertTrue(check(doc), missing)
                self.assertTrue(any(missing in n for n in doc["notes"]),
                                f"no note about {missing}: {doc['notes']}")

    def test_each_source_corrupt_never_raise(self):
        for name in pd.SOURCE_FILES:
            with self.subTest(corrupt=name):
                self.write_all_sources()
                (self.data_dir / name).write_text("garbage{{{", encoding="utf-8")
                doc = self.build()  # не raise
                self.assertEqual(doc["source"], "portal_data")

    def test_all_sources_missing_empty_dir(self):
        doc = self.build()
        self.assertFalse(doc["equity"]["available"])
        self.assertFalse(doc["exposure"]["available"])
        self.assertIsNone(doc["capital_ladder"])
        self.assertIsNone(doc["headline"]["aum_usd"])
        self.assertIsNone(doc["meta"]["is_demo"])
        self.assertTrue(any("is_demo" in n for n in doc["notes"]))

    def test_is_demo_true_honest(self):
        self.write_all_sources()
        equity = dict(EQUITY_DOC)
        equity["is_demo"] = True
        _write_json(self.data_dir / pd.EQUITY_FILENAME, equity)
        self.assertIs(self.build()["meta"]["is_demo"], True)

    def test_aum_fallback_to_pt_equity(self):
        self.write_all_sources()
        (self.data_dir / pd.POSITIONS_FILENAME).unlink()
        self.assertEqual(self.build()["headline"]["aum_usd"], 100182.4)

    def test_disclaimer_constant(self):
        self.assertIn("NOT investment advice", pd.DISCLAIMER)


# ─── персист / идемпотентность ───────────────────────────────────────────────


class TestPersistence(PortalBase):
    def _run(self):
        doc = self.build()
        return pd.write_status(doc, data_dir=self.data_dir)

    def test_run_writes_file(self):
        self.write_all_sources()
        result = self._run()
        self.assertTrue(result["changed"])
        path = Path(result["json"])
        self.assertEqual(path.name, pd.STATUS_FILENAME)
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["source"], "portal_data")
        self.assertEqual(doc["schema_version"], pd.SCHEMA_VERSION)
        self.no_tmp_leftovers()

    def test_run_twice_byte_identical(self):
        self.write_all_sources()
        p1 = self._run()
        raw1 = Path(p1["json"]).read_bytes()
        p2 = self._run()
        self.assertFalse(p2["changed"])
        self.assertEqual(Path(p2["json"]).read_bytes(), raw1)
        self.no_tmp_leftovers()

    def test_generated_at_preserved_when_unchanged(self):
        self.write_all_sources()
        self._run()
        gen1 = json.loads((self.data_dir / pd.STATUS_FILENAME)
                          .read_text(encoding="utf-8"))["meta"]["generated_at"]
        self._run()
        gen2 = json.loads((self.data_dir / pd.STATUS_FILENAME)
                          .read_text(encoding="utf-8"))["meta"]["generated_at"]
        self.assertEqual(gen1, gen2)

    def test_changed_data_grows_history(self):
        self.write_all_sources()
        self._run()
        doc1 = json.loads((self.data_dir / pd.STATUS_FILENAME)
                          .read_text(encoding="utf-8"))
        self.assertEqual(len(doc1["history"]), 1)
        changed = dict(POSITIONS_DOC)
        changed["positions"] = {"aave_v3": 95000.0}
        _write_json(self.data_dir / pd.POSITIONS_FILENAME, changed)
        self._run()
        doc2 = json.loads((self.data_dir / pd.STATUS_FILENAME)
                          .read_text(encoding="utf-8"))
        self.assertEqual(len(doc2["history"]), 2)

    def test_history_rotation_exactly_500(self):
        self.write_all_sources()
        stale = {"meta": {"generated_at": "old"},
                 "history": [{"n": i} for i in range(520)]}
        _write_json(self.data_dir / pd.STATUS_FILENAME, stale)
        self._run()
        doc = json.loads((self.data_dir / pd.STATUS_FILENAME)
                         .read_text(encoding="utf-8"))
        self.assertEqual(len(doc["history"]), pd.HISTORY_MAX)
        # последняя запись — свежий прогон
        self.assertIn("aum_usd", doc["history"][-1])

    def test_corrupt_previous_status_tolerated(self):
        self.write_all_sources()
        (self.data_dir / pd.STATUS_FILENAME).write_text(
            "{broken json", encoding="utf-8")
        result = self._run()
        self.assertTrue(result["changed"])
        doc = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
        self.assertEqual(len(doc["history"]), 1)

    def test_fingerprint_ignores_volatile(self):
        a = {"meta": {"generated_at": "t1", "x": 1}, "history": [1], "v": 1}
        b = {"meta": {"generated_at": "t2", "x": 1}, "history": [2], "v": 1}
        self.assertEqual(pd.content_fingerprint(a), pd.content_fingerprint(b))
        c = dict(a, v=2)
        self.assertNotEqual(pd.content_fingerprint(a), pd.content_fingerprint(c))
        self.assertNotEqual(pd.content_fingerprint(None), pd.content_fingerprint(a))


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(PortalBase):
    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = pd.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_check_default_exit0_prints_json(self):
        rc, out, err = self._main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertNotIn("Traceback", err)
        doc = json.loads(out)
        self.assertEqual(doc["source"], "portal_data")

    def test_check_does_not_write(self):
        self.write_all_sources()
        before = sorted(p.name for p in self.data_dir.iterdir())
        rc, _, _ = self._main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(p.name for p in self.data_dir.iterdir()), before)
        self.assertFalse((self.data_dir / pd.STATUS_FILENAME).exists())

    def test_run_exit0_writes(self):
        self.write_all_sources()
        rc, out, err = self._main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertIn("written", out)
        self.assertNotIn("Traceback", err)
        self.assertTrue((self.data_dir / pd.STATUS_FILENAME).exists())

    def test_run_twice_idempotent(self):
        self.write_all_sources()
        rc1, out1, _ = self._main(["--run", "--data-dir", str(self.data_dir)])
        raw1 = (self.data_dir / pd.STATUS_FILENAME).read_bytes()
        rc2, out2, _ = self._main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual((rc1, rc2), (0, 0))
        self.assertIn("unchanged (idempotent)", out2)
        self.assertEqual((self.data_dir / pd.STATUS_FILENAME).read_bytes(), raw1)
        self.no_tmp_leftovers()

    def test_run_empty_data_exit0(self):
        rc, _, err = self._main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertNotIn("Traceback", err)

    def test_garbage_argument_error_exit0(self):
        rc, _, err = self._main(["--garbage-flag"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

    def test_conflicting_check_and_run_error_exit0(self):
        rc, _, err = self._main(["--check", "--run"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

    def test_subprocess_no_traceback(self):
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.reporting.portal_data",
             "--check", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)

    def test_subprocess_garbage_arg_exit0(self):
        proc = subprocess.run(
            [sys.executable, "-m", "spa_core.reporting.portal_data",
             "--definitely-not-a-flag"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("ERROR", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


# ─── гигиена модуля ──────────────────────────────────────────────────────────


class TestHygiene(unittest.TestCase):
    FORBIDDEN_PREFIXES = (
        "anthropic", "openai", "langchain", "litellm",
        "google.generativeai", "requests", "web3", "urllib.request",
        "socket", "http.client", "http.server", "pandas", "numpy",
    )

    def _imports(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        mods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.append(node.module)
        return mods

    def test_no_forbidden_imports(self):
        for mod in self._imports():
            for bad in self.FORBIDDEN_PREFIXES:
                self.assertFalse(
                    mod == bad or mod.startswith(bad + "."),
                    f"forbidden import {mod}",
                )

    def test_llm_forbidden_lint_clean(self):
        # тот же AST-сканер, что в CI (как в test_tear_sheet)
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        violations = find_forbidden_imports(
            MODULE_PATH.read_text(encoding="utf-8"), "portal_data.py")
        self.assertEqual(violations, [])

    def test_reuses_tear_sheet_and_capital_ladder(self):
        mods = self._imports()
        self.assertIn("spa_core.reporting.tear_sheet", mods)
        self.assertIn("spa_core.governance.capital_ladder", mods)

    def test_constants(self):
        self.assertEqual(pd.STATUS_FILENAME, "investor_portal_data.json")
        self.assertEqual(pd.HISTORY_MAX, 500)
        self.assertEqual(pd.AUDIT_EVENTS_MAX, 100)
        self.assertEqual(pd.AUDIT_TRAIL_FILENAME, "audit_trail.jsonl")
        self.assertEqual(pd.REAL_TRACK_START, "2026-06-10")


# ─── статические проверки investor_portal.html ───────────────────────────────


class TestPortalHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PORTAL_HTML.read_text(encoding="utf-8")

    def test_file_exists_in_repo_root(self):
        self.assertTrue(PORTAL_HTML.exists())

    def test_fully_offline_no_external_urls(self):
        # офлайн-самодостаточность: ни одного http(s)-URL вообще
        # (никаких CDN/шрифтов/трекеров; SVG строится через innerHTML)
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)

    def test_no_external_script_or_stylesheet(self):
        self.assertIsNone(re.search(r"<script[^>]+src=", self.html))
        self.assertIsNone(re.search(r"<link[^>]+href=", self.html))
        for cdn in ("cdn.", "jsdelivr", "unpkg", "googleapis", "cloudflare",
                    "fonts.g"):
            self.assertNotIn(cdn, self.html, f"CDN reference: {cdn}")

    def test_reads_portal_data_json(self):
        self.assertIn("investor_portal_data.json", self.html)

    def test_disclaimer_present(self):
        self.assertIn("NOT investment advice", self.html)

    def test_staleness_banner_markers(self):
        self.assertIn("renderStalenessBanner", self.html)
        self.assertIn("staleness-banner", self.html)
        # порог 24h задан явно
        self.assertIn("24 * 3600 * 1000", self.html)

    def test_is_demo_badge_marker(self):
        self.assertIn("demo-badge", self.html)
        self.assertIn("is_demo", self.html)

    def test_track_day_counter_from_2026_06_10(self):
        self.assertIn("REAL_TRACK_START = '2026-06-10'", self.html)
        self.assertIn("track-day-badge", self.html)

    def test_required_sections_present(self):
        for marker in ("headline-cards", "equity-chart", "exposure-table",
                       "risk-grades", "pot-viewer", "audit-viewer",
                       "nodata-banner"):
            self.assertIn(marker, self.html, f"missing section marker {marker}")

    def test_no_plaintext_secrets(self):
        # PAT/секреты в портале недопустимы (SPA-BL-001)
        self.assertIsNone(re.search(r"gh[po]_[A-Za-z0-9]{20,}", self.html))
        self.assertIsNone(re.search(r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9]{16,}",
                                    self.html))

    def test_honest_fallback_documented(self):
        # fallback при отсутствии файла данных: заглушка + инструкция
        self.assertIn("portal_data --run", self.html)
        self.assertIn("file://", self.html)


if __name__ == "__main__":
    unittest.main()
