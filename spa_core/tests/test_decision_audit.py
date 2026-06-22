"""Tests for spa_core.audit.decision_audit (MP-310).

Run with:
    python3 -m unittest discover -s spa_core/tests -p "test_decision_audit.py" -v
or:
    python3 -m pytest spa_core/tests/test_decision_audit.py -v

≥40 test cases covering:
  - new_cycle returns valid UUID4
  - Two cycles produce different correlation_ids
  - cycle_start event is written on new_cycle
  - log_snapshot stores all expected keys (equity, positions, apy, paper_day)
  - log_proposal stores strategy, allocations, rationale
  - log_risk_check stores passed, violations, warnings
  - log_trade stores trade_id, protocol, amount_usd, action
  - log_rejection stores reason
  - Every log_* returns self (fluent chaining)
  - All entries carry correlation_id, event_type, timestamp
  - export_cycle returns correct correlation_id, all events in insertion order
  - export_cycle for unknown id returns empty events (no raise)
  - export_jsonl creates valid JSONL (one JSON object per line)
  - export_jsonl with custom output_path
  - export_jsonl appends on second call (no duplication of first write)
  - Atomic write leaves no .tmp files
  - Never-raise: corrupt JSON on disk
  - Never-raise: missing / unwritable directory
  - Never-raise: run_audit_export with invalid dir
  - paper_day propagated from snapshot to later events
  - Chaining: all four log_* calls in one chain
  - CLI --export flag exits 0
  - CLI without flags exits 0
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

# Ensure repo root is importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.audit.decision_audit import (
    DecisionAuditLogger,
    _AUDIT_FILENAME,
    _JSONL_FILENAME,
    run_audit_export,
    _cli_main,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


class _TmpDir:
    """Context manager that creates a temp dir and removes it on exit."""

    def __enter__(self) -> str:
        self._path = tempfile.mkdtemp(prefix="spa_da_test_")
        return self._path

    def __exit__(self, *_) -> None:
        shutil.rmtree(self._path, ignore_errors=True)


def _make_logger(d: str) -> DecisionAuditLogger:
    return DecisionAuditLogger(data_dir=d)


def _full_chain(d: str) -> tuple[DecisionAuditLogger, str]:
    """Create a logger with a fully populated chain and return (logger, cid)."""
    a = _make_logger(d)
    cid = a.new_cycle(snapshot_id="snap_001")
    a.log_snapshot(cid, equity=100_026, positions={"aave_v3": 31_947}, apy=3.20, paper_days=3)
    a.log_proposal(cid, strategy="S0", allocations={"aave_v3": 0.32}, rationale="highest_sharpe")
    a.log_risk_check(cid, passed=True, violations=[], warnings=["apy_near_cap"])
    a.log_trade(cid, trade_id="T004", protocol="aave_v3", amount_usd=31_947, action="hold")
    return a, cid


# ── new_cycle ─────────────────────────────────────────────────────────────────


class TestNewCycle(unittest.TestCase):

    def test_returns_string(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            self.assertIsInstance(cid, str)

    def test_returns_valid_uuid4(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            parsed = uuid.UUID(cid, version=4)
            self.assertEqual(str(parsed), cid)

    def test_nonempty(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            self.assertTrue(len(a.new_cycle()) > 0)

    def test_two_cycles_distinct(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid1 = a.new_cycle()
            cid2 = a.new_cycle()
            self.assertNotEqual(cid1, cid2)

    def test_ten_cycles_all_distinct(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            ids = [a.new_cycle() for _ in range(10)]
            self.assertEqual(len(ids), len(set(ids)))

    def test_creates_cycle_start_event(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            chain = a.export_cycle(cid)
            types = [e["event_type"] for e in chain["events"]]
            self.assertIn("cycle_start", types)

    def test_snapshot_id_stored(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle(snapshot_id="SNAP-99")
            ev = a._registry[cid][0]
            self.assertEqual(ev["snapshot_id"], "SNAP-99")

    def test_cycle_start_has_timestamp(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            ev = a._registry[cid][0]
            self.assertIn("timestamp", ev)
            self.assertTrue(ev["timestamp"])

    def test_cycle_start_has_correlation_id(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            ev = a._registry[cid][0]
            self.assertEqual(ev["correlation_id"], cid)


# ── log_snapshot ──────────────────────────────────────────────────────────────


class TestLogSnapshot(unittest.TestCase):

    def test_returns_self(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            ret = a.log_snapshot(cid, 100_000, {}, 5.0, 3)
            self.assertIs(ret, a)

    def test_stores_equity(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            snap = next(e for e in a._registry[cid] if e["event_type"] == "snapshot")
            self.assertAlmostEqual(snap["equity_usd"], 100_026)

    def test_stores_positions(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            snap = next(e for e in a._registry[cid] if e["event_type"] == "snapshot")
            self.assertIn("aave_v3", snap["positions"])

    def test_stores_apy(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            snap = next(e for e in a._registry[cid] if e["event_type"] == "snapshot")
            self.assertAlmostEqual(snap["apy_pct"], 3.20)

    def test_stores_paper_day(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            snap = next(e for e in a._registry[cid] if e["event_type"] == "snapshot")
            self.assertEqual(snap["paper_day"], 3)

    def test_has_required_fields(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            snap = next(e for e in a._registry[cid] if e["event_type"] == "snapshot")
            for key in ("correlation_id", "event_type", "timestamp", "paper_day"):
                self.assertIn(key, snap)


# ── log_proposal ──────────────────────────────────────────────────────────────


class TestLogProposal(unittest.TestCase):

    def test_returns_self(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            ret = a.log_proposal(cid, "S0", {}, "reason")
            self.assertIs(ret, a)

    def test_stores_strategy(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            prop = next(e for e in a._registry[cid] if e["event_type"] == "allocation_proposal")
            self.assertEqual(prop["strategy"], "S0")

    def test_stores_allocations(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            prop = next(e for e in a._registry[cid] if e["event_type"] == "allocation_proposal")
            self.assertIn("aave_v3", prop["allocations"])

    def test_stores_rationale(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            prop = next(e for e in a._registry[cid] if e["event_type"] == "allocation_proposal")
            self.assertEqual(prop["rationale"], "highest_sharpe")

    def test_has_required_fields(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            prop = next(e for e in a._registry[cid] if e["event_type"] == "allocation_proposal")
            for key in ("correlation_id", "event_type", "timestamp"):
                self.assertIn(key, prop)


# ── log_risk_check ────────────────────────────────────────────────────────────


class TestLogRiskCheck(unittest.TestCase):

    def test_returns_self(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            ret = a.log_risk_check(cid, True, [], [])
            self.assertIs(ret, a)

    def test_stores_passed_true(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            rv = next(e for e in a._registry[cid] if e["event_type"] == "risk_verdict")
            self.assertTrue(rv["passed"])

    def test_stores_passed_false(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_risk_check(cid, False, ["concentration_breach"], [])
            rv = next(e for e in a._registry[cid] if e["event_type"] == "risk_verdict")
            self.assertFalse(rv["passed"])

    def test_stores_violations(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_risk_check(cid, False, ["tvl_floor", "t2_cap"], [])
            rv = next(e for e in a._registry[cid] if e["event_type"] == "risk_verdict")
            self.assertIn("tvl_floor", rv["violations"])
            self.assertIn("t2_cap", rv["violations"])

    def test_stores_warnings(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            rv = next(e for e in a._registry[cid] if e["event_type"] == "risk_verdict")
            self.assertIn("apy_near_cap", rv["warnings"])

    def test_has_required_fields(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            rv = next(e for e in a._registry[cid] if e["event_type"] == "risk_verdict")
            for key in ("correlation_id", "event_type", "timestamp", "passed"):
                self.assertIn(key, rv)


# ── log_trade ─────────────────────────────────────────────────────────────────


class TestLogTrade(unittest.TestCase):

    def test_returns_self(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            ret = a.log_trade(cid, "T001", "aave_v3", 1000, "buy")
            self.assertIs(ret, a)

    def test_stores_trade_id(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            tr = next(e for e in a._registry[cid] if e["event_type"] == "trade_executed")
            self.assertEqual(tr["trade_id"], "T004")

    def test_stores_protocol(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            tr = next(e for e in a._registry[cid] if e["event_type"] == "trade_executed")
            self.assertEqual(tr["protocol"], "aave_v3")

    def test_stores_amount_usd(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            tr = next(e for e in a._registry[cid] if e["event_type"] == "trade_executed")
            self.assertAlmostEqual(tr["amount_usd"], 31_947)

    def test_stores_action(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            tr = next(e for e in a._registry[cid] if e["event_type"] == "trade_executed")
            self.assertEqual(tr["action"], "hold")

    def test_has_required_fields(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            tr = next(e for e in a._registry[cid] if e["event_type"] == "trade_executed")
            for key in ("correlation_id", "event_type", "timestamp"):
                self.assertIn(key, tr)


# ── log_rejection ─────────────────────────────────────────────────────────────


class TestLogRejection(unittest.TestCase):

    def test_returns_self(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            ret = a.log_rejection(cid, "concentration_breach")
            self.assertIs(ret, a)

    def test_stores_reason(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_rejection(cid, "tvl_floor_violation")
            rv = next(e for e in a._registry[cid] if e["event_type"] == "trade_blocked")
            self.assertEqual(rv["reason"], "tvl_floor_violation")

    def test_event_type_is_trade_blocked(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_rejection(cid, "drawdown_kill_switch")
            types = [e["event_type"] for e in a._registry[cid]]
            self.assertIn("trade_blocked", types)

    def test_has_required_fields(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_rejection(cid, "some_reason")
            rv = next(e for e in a._registry[cid] if e["event_type"] == "trade_blocked")
            for key in ("correlation_id", "event_type", "timestamp", "reason"):
                self.assertIn(key, rv)


# ── export_cycle ──────────────────────────────────────────────────────────────


class TestExportCycle(unittest.TestCase):

    def test_returns_dict(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            self.assertIsInstance(a.export_cycle(cid), dict)

    def test_correlation_id_matches(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            chain = a.export_cycle(cid)
            self.assertEqual(chain["correlation_id"], cid)

    def test_events_list_present(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            chain = a.export_cycle(cid)
            self.assertIn("events", chain)
            self.assertIsInstance(chain["events"], list)

    def test_four_plus_events(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            chain = a.export_cycle(cid)
            # cycle_start + snapshot + proposal + risk_check + trade = 5
            self.assertGreaterEqual(len(chain["events"]), 4)

    def test_events_in_insertion_order(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            chain = a.export_cycle(cid)
            types = [e["event_type"] for e in chain["events"]]
            # cycle_start must come before snapshot
            self.assertLess(types.index("cycle_start"), types.index("snapshot"))
            # snapshot before allocation_proposal
            self.assertLess(types.index("snapshot"), types.index("allocation_proposal"))

    def test_unknown_id_returns_empty(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            chain = a.export_cycle("no-such-id")
            self.assertEqual(chain["correlation_id"], "no-such-id")
            self.assertEqual(chain["events"], [])

    def test_event_count_matches(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            chain = a.export_cycle(cid)
            self.assertEqual(chain["event_count"], len(chain["events"]))

    def test_two_cycles_isolated(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid1 = a.new_cycle()
            cid2 = a.new_cycle()
            a.log_snapshot(cid1, 100_000, {}, 5.0, 1)
            chain1 = a.export_cycle(cid1)
            chain2 = a.export_cycle(cid2)
            # chain1 has snapshot; chain2 should NOT
            types1 = [e["event_type"] for e in chain1["events"]]
            types2 = [e["event_type"] for e in chain2["events"]]
            self.assertIn("snapshot", types1)
            self.assertNotIn("snapshot", types2)


# ── export_jsonl ──────────────────────────────────────────────────────────────


class TestExportJsonl(unittest.TestCase):

    def test_creates_file(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            a.export_jsonl()
            self.assertTrue((Path(d) / _JSONL_FILENAME).exists())

    def test_custom_output_path(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            out = Path(d) / "custom_trail.jsonl"
            a.export_jsonl(output_path=str(out))
            self.assertTrue(out.exists())

    def test_each_line_is_valid_json(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            a.export_jsonl()
            path = Path(d) / _JSONL_FILENAME
            with open(str(path)) as fh:
                lines = [l.strip() for l in fh if l.strip()]
            self.assertTrue(len(lines) > 0)
            for line in lines:
                obj = json.loads(line)  # must not raise
                self.assertIsInstance(obj, dict)

    def test_jsonl_contains_correlation_id(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            a.export_jsonl()
            path = Path(d) / _JSONL_FILENAME
            with open(str(path)) as fh:
                lines = [json.loads(l) for l in fh if l.strip()]
            cids = [obj["correlation_id"] for obj in lines]
            self.assertIn(cid, cids)

    def test_jsonl_contains_events(self):
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            a.export_jsonl()
            path = Path(d) / _JSONL_FILENAME
            with open(str(path)) as fh:
                lines = [json.loads(l) for l in fh if l.strip()]
            obj = next(o for o in lines if o["correlation_id"] == cid)
            self.assertIn("events", obj)
            self.assertIsInstance(obj["events"], list)
            self.assertGreater(len(obj["events"]), 0)

    def test_appends_on_second_call(self):
        with _TmpDir() as d:
            a1, _ = _full_chain(d)
            a1.export_jsonl()
            a2 = _make_logger(d)
            cid2 = a2.new_cycle()
            a2.log_snapshot(cid2, 101_000, {}, 5.5, 4)
            a2.export_jsonl()
            path = Path(d) / _JSONL_FILENAME
            with open(str(path)) as fh:
                lines = [l.strip() for l in fh if l.strip()]
            # At least 2+ lines total
            self.assertGreaterEqual(len(lines), 2)


# ── Atomic write / no .tmp files ──────────────────────────────────────────────


class TestAtomicWrite(unittest.TestCase):

    def test_no_tmp_files_after_new_cycle(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            a.new_cycle()
            tmp_files = list(Path(d).glob("*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_no_tmp_files_after_full_chain(self):
        with _TmpDir() as d:
            _full_chain(d)
            tmp_files = list(Path(d).glob("*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_audit_json_is_valid(self):
        with _TmpDir() as d:
            _full_chain(d)
            path = Path(d) / _AUDIT_FILENAME
            with open(str(path)) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, dict)


# ── Never-raise / resilience ──────────────────────────────────────────────────


class TestNeverRaise(unittest.TestCase):

    def test_corrupt_json_on_disk(self):
        with _TmpDir() as d:
            audit_path = Path(d) / _AUDIT_FILENAME
            audit_path.write_text("NOT VALID JSON {{{", encoding="utf-8")
            # Should not raise — falls back to empty registry
            a = _make_logger(d)
            cid = a.new_cycle()
            self.assertTrue(len(cid) > 0)

    def test_missing_dir_run_audit_export(self):
        # Pass a nonexistent dir; should silently handle
        try:
            run_audit_export(data_dir="/tmp/_spa_nonexistent_99999_test")
        except Exception as exc:
            self.fail(f"run_audit_export raised: {exc}")

    def test_log_methods_never_raise_bad_args(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            # Use a nonexistent correlation_id; all log_* should silently proceed
            fake_cid = "not-a-real-uuid"
            try:
                a.log_snapshot(fake_cid, 0, {}, 0, 0)
                a.log_proposal(fake_cid, "", {}, "")
                a.log_risk_check(fake_cid, True, [], [])
                a.log_trade(fake_cid, "", "", 0, "")
                a.log_rejection(fake_cid, "")
            except Exception as exc:
                self.fail(f"log_* raised unexpectedly: {exc}")

    def test_export_cycle_unknown_id_no_raise(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            try:
                result = a.export_cycle("completely-unknown-id")
            except Exception as exc:
                self.fail(f"export_cycle raised: {exc}")
            self.assertEqual(result["events"], [])

    def test_export_jsonl_readonly_dir_no_raise(self):
        """export_jsonl must not raise even if target dir is unwritable."""
        with _TmpDir() as d:
            a, cid = _full_chain(d)
            bad_path = "/proc/no_such_dir/trail.jsonl"  # definitely unwritable
            try:
                a.export_jsonl(output_path=bad_path)
            except Exception as exc:
                self.fail(f"export_jsonl raised: {exc}")


# ── paper_day propagation ─────────────────────────────────────────────────────


class TestPaperDayPropagation(unittest.TestCase):

    def test_paper_day_in_proposal(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_snapshot(cid, 100_000, {}, 5.0, 7)
            a.log_proposal(cid, "S0", {}, "reason")
            prop = next(e for e in a._registry[cid] if e["event_type"] == "allocation_proposal")
            self.assertEqual(prop["paper_day"], 7)

    def test_paper_day_in_risk_check(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_snapshot(cid, 100_000, {}, 5.0, 7)
            a.log_risk_check(cid, True, [], [])
            rv = next(e for e in a._registry[cid] if e["event_type"] == "risk_verdict")
            self.assertEqual(rv["paper_day"], 7)

    def test_paper_day_none_without_snapshot(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_proposal(cid, "S0", {}, "reason")
            prop = next(e for e in a._registry[cid] if e["event_type"] == "allocation_proposal")
            self.assertIsNone(prop["paper_day"])


# ── Fluent chaining ───────────────────────────────────────────────────────────


class TestFluentChaining(unittest.TestCase):

    def test_full_chain_in_one_expression(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            # All log_* should be chainable
            result = (
                a.log_snapshot(cid, 100_000, {"aave_v3": 40_000}, 5.0, 1)
                 .log_proposal(cid, "S0", {"aave_v3": 0.4}, "sharpe")
                 .log_risk_check(cid, True, [], [])
                 .log_trade(cid, "T001", "aave_v3", 40_000, "hold")
            )
            self.assertIs(result, a)

    def test_chain_with_rejection(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            result = (
                a.log_snapshot(cid, 100_000, {}, 5.0, 2)
                 .log_proposal(cid, "S1", {}, "conservative")
                 .log_risk_check(cid, False, ["t2_cap"], [])
                 .log_rejection(cid, "t2_cap_exceeded")
            )
            self.assertIs(result, a)
            types = [e["event_type"] for e in a._registry[cid]]
            self.assertIn("trade_blocked", types)


# ── run_audit_export ──────────────────────────────────────────────────────────


class TestRunAuditExport(unittest.TestCase):

    def test_creates_jsonl_file(self):
        with _TmpDir() as d:
            a, _ = _full_chain(d)
            run_audit_export(data_dir=d)
            self.assertTrue((Path(d) / _JSONL_FILENAME).exists())

    def test_never_raises_invalid_dir(self):
        try:
            run_audit_export(data_dir="/nonexistent_dir_xyz/test")
        except Exception as exc:
            self.fail(f"run_audit_export raised: {exc}")

    def test_empty_registry_no_raise(self):
        with _TmpDir() as d:
            # No cycles created; run_audit_export should silently return
            try:
                run_audit_export(data_dir=d)
            except Exception as exc:
                self.fail(f"run_audit_export raised with empty registry: {exc}")

    def test_jsonl_line_parseable(self):
        with _TmpDir() as d:
            a, _ = _full_chain(d)
            run_audit_export(data_dir=d)
            path = Path(d) / _JSONL_FILENAME
            with open(str(path)) as fh:
                lines = [l.strip() for l in fh if l.strip()]
            self.assertGreater(len(lines), 0)
            obj = json.loads(lines[-1])
            self.assertIn("correlation_id", obj)
            self.assertIn("events", obj)


# ── CLI ───────────────────────────────────────────────────────────────────────


class TestCLI(unittest.TestCase):

    def test_export_flag_exits_zero(self):
        with _TmpDir() as d:
            _full_chain(d)
            rc = _cli_main(["--export", "--data-dir", d])
            self.assertEqual(rc, 0)

    def test_no_flags_exits_zero(self):
        with _TmpDir() as d:
            _full_chain(d)
            rc = _cli_main(["--data-dir", d])
            self.assertEqual(rc, 0)

    def test_export_creates_jsonl(self):
        with _TmpDir() as d:
            _full_chain(d)
            _cli_main(["--export", "--data-dir", d])
            self.assertTrue((Path(d) / _JSONL_FILENAME).exists())


# ── Integration: persistence across logger instances ─────────────────────────


class TestPersistence(unittest.TestCase):

    def test_data_survives_reload(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid = a.new_cycle()
            a.log_snapshot(cid, 100_000, {"aave_v3": 40_000}, 5.0, 1)
            # Create a fresh logger pointing to the same dir
            b = _make_logger(d)
            chain = b.export_cycle(cid)
            types = [e["event_type"] for e in chain["events"]]
            self.assertIn("snapshot", types)

    def test_two_cycles_both_persisted(self):
        with _TmpDir() as d:
            a = _make_logger(d)
            cid1 = a.new_cycle()
            cid2 = a.new_cycle()
            a.log_trade(cid1, "T1", "aave_v3", 1000, "buy")
            b = _make_logger(d)
            self.assertIn(cid1, b._registry)
            self.assertIn(cid2, b._registry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
