"""
Tests for the investor-report + PnL-attribution modules (SPA-V393).

Stdlib-only, self-contained PASS/FAIL runner (pytest is not installed in this
repo; mirrors the convention of test_return_distribution.py /
test_calendar_returns.py).

None of these tests require the network: the risk-scoring engine is invoked in
offline/bootstrap mode, and the decision audit trail is exercised against a
throw-away temporary SQLite file.

Run::
    python spa_core/tests/test_investor_report.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.reports.pnl_attribution import (
    compute_pnl_attribution,
    _as_float,
    _extract_positions,
    _position_apy,
    _period_days,
)
from spa_core.reports import investor_report as ir
from spa_core.utils.atomic import atomic_save


# ─── Runner ───────────────────────────────────────────────────────────────────

PASS = FAIL = 0


def run(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  ✓ {name}")
    except AssertionError as exc:
        FAIL += 1
        print(f"  ✗ {name}: {exc}")
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print(f"  ✗ {name}: UNEXPECTED {type(exc).__name__}: {exc}")


# ─── Fixtures (temp JSON sources) ─────────────────────────────────────────────

def _write_json(tmpdir, name, payload):
    p = Path(tmpdir) / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


def _portfolio(positions, **extra):
    base = {"source": "test", "positions": positions}
    base.update(extra)
    return base


def _make_temp_decision_db(rows):
    """Create a throw-away SQLite DB with the agent_decisions table + rows.

    Returns the db path. Mirrors the schema from the 0001_initial migration.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE agent_decisions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp           TEXT NOT NULL,
            agent_name          TEXT NOT NULL,
            decision_type       TEXT NOT NULL,
            protocol_key        TEXT,
            amount_usd          REAL,
            reasoning           TEXT NOT NULL,
            data_snapshot       TEXT,
            policy_version      TEXT DEFAULT 'v1.0',
            strategy_id         TEXT DEFAULT 'paper-v1',
            risk_check_result   TEXT,
            outcome             TEXT
        )
        """
    )
    for r in rows:
        conn.execute(
            """INSERT INTO agent_decisions
                (timestamp, agent_name, decision_type, protocol_key, amount_usd,
                 reasoning, data_snapshot, policy_version, strategy_id,
                 risk_check_result, outcome)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            r,
        )
    conn.commit()
    conn.close()
    return path


# ─── pnl_attribution tests ────────────────────────────────────────────────────

def test_missing_sources_empty_but_valid():
    # All paths point at non-existent files → stable empty report, no raise.
    d = compute_pnl_attribution(
        portfolio_path="/no/such/portfolio.json",
        pnl_history_path="/no/such/pnl.json",
        equity_curve_path="/no/such/equity.json",
    )
    assert d["protocols"] == [], d
    assert d["roll_up"]["num_positions"] == 0, d
    assert d["roll_up"]["total_capital_usd"] is None, d
    assert d["roll_up"]["period"]["days"] == 0, d


def test_broken_json_graceful():
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "portfolio_state.json"
        bad.write_text("{not valid json", encoding="utf-8")
        d = compute_pnl_attribution(
            portfolio_path=str(bad),
            pnl_history_path="/no/such/pnl.json",
            equity_curve_path="/no/such/eq.json",
        )
        assert d["protocols"] == [], d


def test_capital_share_sums_to_one():
    with tempfile.TemporaryDirectory() as td:
        positions = [
            {"protocol": "morpho_blue", "actual_usd": 20000.0, "target_usd": 20000.0,
             "actual_weight": 0.2, "target_weight": 0.2},
            {"protocol": "yearn_v3", "actual_usd": 30000.0, "target_usd": 30000.0,
             "actual_weight": 0.3, "target_weight": 0.3},
            {"protocol": "euler_v2", "actual_usd": 50000.0, "target_usd": 50000.0,
             "actual_weight": 0.5, "target_weight": 0.5},
        ]
        pp = _write_json(td, "portfolio_state.json", _portfolio(
            positions, total_actual_usd=100000.0, total_target_usd=100000.0))
        d = compute_pnl_attribution(
            portfolio_path=pp,
            pnl_history_path="/no/such/pnl.json",
            equity_curve_path="/no/such/eq.json",
        )
        assert len(d["protocols"]) == 3, d
        total = sum(p["capital_share"] for p in d["protocols"])
        assert abs(total - 1.0) < 1e-6, total
        # capital_share recomputed from actual_usd, not the stored weight.
        assert abs(d["protocols"][2]["capital_share"] - 0.5) < 1e-6, d["protocols"][2]


def test_contribution_none_without_apy():
    with tempfile.TemporaryDirectory() as td:
        positions = [
            {"protocol": "maple", "actual_usd": 40000.0, "target_usd": 40000.0,
             "actual_weight": 0.5, "target_weight": 0.5},
            {"protocol": "curve", "actual_usd": 40000.0, "target_usd": 40000.0,
             "actual_weight": 0.5, "target_weight": 0.5},
        ]
        pp = _write_json(td, "portfolio_state.json", _portfolio(positions))
        d = compute_pnl_attribution(
            portfolio_path=pp,
            pnl_history_path="/no/such/pnl.json",
            equity_curve_path="/no/such/eq.json",
        )
        for p in d["protocols"]:
            assert p["protocol_apy"] is None, p
            assert p["apy_contribution"] is None, p


def test_contribution_present_with_apy():
    with tempfile.TemporaryDirectory() as td:
        positions = [
            {"protocol": "aave-v3", "actual_usd": 50000.0, "target_usd": 50000.0,
             "actual_weight": 0.5, "target_weight": 0.5, "apy": 4.0},
            {"protocol": "pendle", "actual_usd": 50000.0, "target_usd": 50000.0,
             "actual_weight": 0.5, "target_weight": 0.5, "apy": 8.0},
        ]
        pp = _write_json(td, "portfolio_state.json", _portfolio(positions))
        d = compute_pnl_attribution(
            portfolio_path=pp,
            pnl_history_path="/no/such/pnl.json",
            equity_curve_path="/no/such/eq.json",
        )
        # 0.5*4 + 0.5*8 = 6.0 portfolio APY contribution
        contribs = [p["apy_contribution"] for p in d["protocols"]]
        assert all(c is not None for c in contribs), contribs
        assert abs(sum(contribs) - 6.0) < 1e-6, contribs


def test_rollup_fields_from_history():
    with tempfile.TemporaryDirectory() as td:
        history = [
            {"timestamp": "2026-05-15T05:07:27Z", "total_capital_usd": 100000.0,
             "total_pnl_usd": 0.0, "total_pnl_pct": 0.0, "current_apy": 5.0},
            {"timestamp": "2026-05-22T01:07:27Z", "total_capital_usd": 98815.79,
             "total_pnl_usd": -1184.21, "total_pnl_pct": -1.184208,
             "current_apy": -84.4829},
        ]
        positions = [{"protocol": "maple", "actual_usd": 80000.0,
                      "target_usd": 80000.0, "actual_weight": 1.0,
                      "target_weight": 1.0}]
        pp = _write_json(td, "portfolio_state.json", _portfolio(positions))
        hp = _write_json(td, "pnl_history.json", history)
        d = compute_pnl_attribution(
            portfolio_path=pp, pnl_history_path=hp,
            equity_curve_path="/no/such/eq.json")
        r = d["roll_up"]
        # roll-up must take the LATEST snapshot for the headline numbers.
        assert abs(r["total_capital_usd"] - 98815.79) < 1e-6, r
        assert abs(r["total_pnl_pct"] - (-1.184208)) < 1e-6, r
        assert abs(r["current_apy"] - (-84.4829)) < 1e-6, r
        assert r["num_positions"] == 1, r
        assert r["history_points"] == 2, r
        assert r["period"]["first"] == "2026-05-15T05:07:27Z", r
        assert r["period"]["last"] == "2026-05-22T01:07:27Z", r
        assert r["period"]["days"] == 6, r["period"]


def test_helpers():
    assert _as_float("1.5") == 1.5
    assert _as_float(None) is None
    assert _as_float(True) is None          # bools rejected
    assert _as_float(float("inf")) is None  # non-finite rejected
    assert _position_apy({"apy": 3.2}) == 3.2
    assert _position_apy({}) is None
    assert _extract_positions({"positions": [{"a": 1}, "x"]}) == [{"a": 1}]
    assert _period_days("2026-05-15T00:00:00Z", "2026-05-20T00:00:00Z") == 5
    assert _period_days(None, "2026-05-20") == 0


# ─── investor_report tests ────────────────────────────────────────────────────

def test_report_schema_and_counts():
    rep = build = ir.build_investor_report(limit=5)
    for key in ("generated_at", "report_date", "source",
                "attribution", "risk_grades", "audit_trail", "counts"):
        assert key in rep, key
    assert rep["source"] == ir.REPORT_SOURCE, rep["source"]
    assert isinstance(rep["risk_grades"], list), rep
    assert isinstance(rep["audit_trail"], list), rep
    assert rep["counts"]["risk_grades"] == len(rep["risk_grades"]), rep
    assert rep["counts"]["audit_records"] == len(rep["audit_trail"]), rep


def test_risk_grade_table_offline():
    # Offline/bootstrap scoring — deterministic, no network. Each row has a
    # valid A/B/C/D grade and a numeric score in [0,1].
    table = ir.build_risk_grade_table()
    assert isinstance(table, list), table
    assert len(table) > 0, "offline bootstrap should yield protocols"
    for row in table:
        assert set(("slug", "protocol", "score", "grade")).issubset(row), row
        assert row["grade"] in ("A", "B", "C", "D"), row
        assert row["score"] is None or 0.0 <= row["score"] <= 1.0, row


def test_grade_for_score_integration():
    from spa_core.risk.scoring_engine import grade_for_score
    assert grade_for_score(0.95) == "A"
    assert grade_for_score(0.75) == "B"
    assert grade_for_score(0.60) == "C"
    assert grade_for_score(0.10) == "D"


def test_audit_trail_from_temp_db():
    rows = [
        ("2026-06-01T10:00:00Z", "TraderAgent", "ALLOCATE", "aave-v3", 40000.0,
         "APY in range", json.dumps({"apy": 4.2}), "v1.0", "paper-v1",
         "APPROVED", "EXECUTED"),
        ("2026-06-02T10:00:00Z", "RiskAgent", "PASS", "euler-v2", None,
         "APY below minimum", None, "v1.0", "paper-v1", None, "SKIPPED"),
    ]
    db = _make_temp_decision_db(rows)
    try:
        trail = ir.build_audit_trail(limit=10, db_path=db)
        assert isinstance(trail, list), trail
        assert len(trail) == 2, trail
        # ordered by timestamp DESC → newest first
        assert trail[0]["decision_type"] == "PASS", trail[0]
        # data_snapshot is parsed back to a dict
        assert trail[1]["data_snapshot"] == {"apy": 4.2}, trail[1]
    finally:
        os.remove(db)


def test_audit_trail_missing_db_empty():
    trail = ir.build_audit_trail(limit=10, db_path="/no/such/decisions.db")
    assert trail == [], trail


def test_atomic_write_creates_file():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "sub" / "investor_report.json"  # parent created on write
        payload = {"hello": "world", "n": 1}
        atomic_save(payload, str(out))
        assert out.exists(), out
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded == payload, loaded
        # No leftover temp files in the directory.
        leftovers = [p for p in out.parent.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == [], leftovers


def test_export_report_writes_file():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "investor_report.json"
        rep = ir.export_report(path=out, limit=3, generate_pdf=False)
        assert out.exists(), out
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["source"] == ir.REPORT_SOURCE, loaded
        assert "counts" in loaded, loaded
        assert rep["counts"]["risk_grades"] == loaded["counts"]["risk_grades"], rep


def test_cli_writes_file():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "investor_report.json"
        rc = ir._cli(["--output", str(out), "--limit", "5", "--no-pdf"])
        assert rc == 0, rc
        assert out.exists(), out
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["source"] == ir.REPORT_SOURCE, loaded


def test_report_with_overridden_sources():
    # End-to-end with synthetic JSON sources + offline grades + no DB.
    with tempfile.TemporaryDirectory() as td:
        positions = [{"protocol": "aave-v3", "actual_usd": 60000.0,
                      "target_usd": 60000.0, "actual_weight": 0.6,
                      "target_weight": 0.6, "apy": 5.0},
                     {"protocol": "pendle", "actual_usd": 40000.0,
                      "target_usd": 40000.0, "actual_weight": 0.4,
                      "target_weight": 0.4, "apy": 10.0}]
        pp = _write_json(td, "portfolio_state.json", _portfolio(positions))
        rep = ir.build_investor_report(
            limit=5,
            portfolio_path=pp,
            pnl_history_path="/no/such/pnl.json",
            equity_curve_path="/no/such/eq.json",
        )
        assert rep["counts"]["protocols"] == 2, rep["counts"]
        # 0.6*5 + 0.4*10 = 7.0
        contribs = [p["apy_contribution"] for p in rep["attribution"]["protocols"]]
        assert abs(sum(contribs) - 7.0) < 1e-6, contribs


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("test_investor_report (SPA-V393)")
    run("missing sources -> empty but valid", test_missing_sources_empty_but_valid)
    run("broken json -> graceful", test_broken_json_graceful)
    run("capital_share sums to 1.0", test_capital_share_sums_to_one)
    run("contribution None without APY", test_contribution_none_without_apy)
    run("contribution present with APY", test_contribution_present_with_apy)
    run("roll-up fields from history (latest snapshot)", test_rollup_fields_from_history)
    run("attribution helpers", test_helpers)
    run("report schema + counts", test_report_schema_and_counts)
    run("risk-grade table offline", test_risk_grade_table_offline)
    run("grade_for_score integration", test_grade_for_score_integration)
    run("audit trail from temp DB", test_audit_trail_from_temp_db)
    run("audit trail missing DB -> empty", test_audit_trail_missing_db_empty)
    run("atomic write creates file", test_atomic_write_creates_file)
    run("export_report writes file", test_export_report_writes_file)
    run("CLI writes file", test_cli_writes_file)
    run("report with overridden sources", test_report_with_overridden_sources)
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
