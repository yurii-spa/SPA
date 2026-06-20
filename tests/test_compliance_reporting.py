"""tests/test_compliance_reporting.py — 30 tests for the compliance module.

Covers:
  - spa_core.compliance.audit_report_generator (8-section audit report)
  - spa_core.compliance.monthly_statement (period statement)

Strategy: most tests run against a synthetic, deterministic data dir built in a
tmp_path so the math is exact; a handful run against the live repo ``data/`` to
prove the report generates without errors on real data.
"""

import json
import os
from pathlib import Path

import pytest

from spa_core.audit import audit_trail_signer
from spa_core.compliance import audit_report_generator as arg
from spa_core.compliance import monthly_statement as ms

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DATA = REPO_ROOT / "data"


# ---------------------------------------------------------------------------
# Fixtures: a synthetic, deterministic data dir
# ---------------------------------------------------------------------------


@pytest.fixture
def synth_data(tmp_path):
    """Build a self-contained data dir with known equity/positions/blocks/chain."""
    d = tmp_path / "data"
    d.mkdir()

    equity = {
        "generated_at": "2026-06-21T08:00:00+00:00",
        "source": "cycle_runner",
        "is_demo": False,
        "summary": {
            "num_days": 4,
            "start_equity": 100000.0,
            "end_equity": 100400.0,
            "total_return_pct": 0.4,
            "max_drawdown_pct": -0.1,
            "positive_days": 4,
            "negative_days": 0,
            "daily_volatility_pct": 0.002,
        },
        "daily": [
            {"date": "2026-06-10", "open_equity": 100000.0, "close_equity": 100100.0,
             "equity": 100100.0, "positions": {"aave_v3": 50000.0, "morpho_blue": 40000.0}},
            {"date": "2026-06-11", "open_equity": 100100.0, "close_equity": 100200.0,
             "equity": 100200.0, "positions": {"aave_v3": 50000.0, "morpho_blue": 40000.0}},
            {"date": "2026-06-20", "open_equity": 100200.0, "close_equity": 100300.0,
             "equity": 100300.0, "positions": {"aave_v3": 60000.0, "morpho_blue": 30000.0}},
            {"date": "2026-06-21", "open_equity": 100300.0, "close_equity": 100400.0,
             "equity": 100400.0, "positions": {"aave_v3": 60000.0, "morpho_blue": 30000.0}},
        ],
    }
    positions = {
        "generated_at": "2026-06-21T08:00:00+00:00",
        "is_demo": False,
        "capital_usd": 100000.0,
        "deployed_usd": 90000.0,
        "cash_usd": 10000.0,
        "positions": {"aave_v3": 30000.0, "morpho_blue": 15000.0, "compound_v3": 20000.0},
    }
    golive = {"ready": False, "passed": 25, "total": 26, "blockers": ["autopush_installed"]}
    blocks = [
        {"ts": "2026-06-12T14:00:00+00:00", "date": "2026-06-12", "violations": ["x: TVL below min"]},
        {"ts": "2026-06-13T14:00:00+00:00", "date": "2026-06-13", "violations": ["y: APY too low"]},
        {"ts": "2026-05-01T14:00:00+00:00", "date": "2026-05-01", "violations": ["old block"]},
    ]
    (d / "equity_curve_daily.json").write_text(json.dumps(equity))
    (d / "current_positions.json").write_text(json.dumps(positions))
    (d / "golive_status.json").write_text(json.dumps(golive))
    (d / "risk_policy_blocks.json").write_text(json.dumps(blocks))

    # Build a valid 3-record hash chain.
    for i in range(3):
        audit_trail_signer.append({"event_type": "test_event", "n": i}, data_dir=d)

    return d


@pytest.fixture
def adr_dir(tmp_path):
    a = tmp_path / "adr"
    a.mkdir()
    for name in ["ADR-001-foo.md", "ADR-002-bar.md", "ADR_INDEX.md"]:
        (a / name).write_text("# adr\n")
    # A non-ADR file should not be counted.
    (a / "README.md").write_text("nope")
    return a


# ===========================================================================
# audit_report_generator — structure / sections (tests 1–14)
# ===========================================================================


def test_01_report_generates_without_errors(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    assert isinstance(rep, dict)
    assert rep["report_type"] == "institutional_audit_report"


def test_02_all_required_sections_present(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    sections = rep["sections"]
    for key in [
        "identity", "governance", "risk_controls", "paper_track",
        "positions", "events_log", "integrity_check", "system_health",
    ]:
        assert key in sections, f"missing section {key}"


def test_03_identity_statement_exact(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    ident = rep["sections"]["identity"]
    assert ident["statement"] == (
        "Personal research project. No external capital managed. Paper trading only."
    )
    assert ident["external_capital_managed_usd"] == 0.0
    assert ident["trading_mode"] == "paper"


def test_04_governance_adr_count(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    gov = rep["sections"]["governance"]
    # ADR-001, ADR-002, ADR_INDEX = 3 files matching ADR*.md; README excluded.
    assert gov["adr_count"] == 3
    assert gov["last_decision_date"] is not None


def test_05_governance_risk_version(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    assert rep["sections"]["governance"]["risk_policy_version"] == "v1.0"


def test_06_risk_controls_pass_fail_shape(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    rc = rep["sections"]["risk_controls"]
    assert rc["total"] >= 6
    for c in rc["controls"]:
        assert c["status"] in ("PASS", "FAIL")
        assert "label" in c and "detail" in c


def test_07_risk_controls_all_pass_on_compliant_data(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    rc = rep["sections"]["risk_controls"]
    assert rc["all_pass"] is True
    assert rc["passed"] == rc["total"]


def test_08_risk_control_kill_switch_present(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    names = {c["control"] for c in rep["sections"]["risk_controls"]["controls"]}
    assert "kill_switch" in names
    assert "tvl_floor" in names
    assert "t1_concentration_cap" in names


def test_09_risk_control_fails_on_over_concentration(tmp_path, adr_dir):
    """A 60% T1 position must FAIL the T1 cap (40%)."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "current_positions.json").write_text(json.dumps({
        "capital_usd": 100000.0, "cash_usd": 10000.0, "deployed_usd": 90000.0,
        "positions": {"aave_v3": 60000.0, "morpho_blue": 30000.0},
    }))
    (d / "equity_curve_daily.json").write_text(json.dumps({"summary": {}, "daily": []}))
    sec = arg.build_risk_controls_section(d)
    t1 = next(c for c in sec["controls"] if c["control"] == "t1_concentration_cap")
    assert t1["status"] == "FAIL"
    assert sec["all_pass"] is False


def test_10_paper_track_fields(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    pt = rep["sections"]["paper_track"]
    assert pt["track_start_date"] == "2026-06-10"
    assert pt["start_equity_usd"] == 100000.0
    assert pt["end_equity_usd"] == 100400.0
    assert pt["total_return_pct"] == 0.4


def test_11_paper_track_consistency(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    pt = rep["sections"]["paper_track"]
    # 4 positive / 0 negative → 100% consistency.
    assert pt["consistency_pct"] == 100.0


def test_12_positions_section_tiers_and_weights(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    pos = rep["sections"]["positions"]
    assert pos["position_count"] == 3
    by_proto = {p["protocol"]: p for p in pos["positions"]}
    assert by_proto["aave_v3"]["tier"] == "T1"
    assert by_proto["morpho_blue"]["tier"] == "T2"
    # 30000 / 100000 = 30%
    assert by_proto["aave_v3"]["weight_pct"] == pytest.approx(30.0)


def test_13_positions_sorted_descending(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    sizes = [p["size_usd"] for p in rep["sections"]["positions"]["positions"]]
    assert sizes == sorted(sizes, reverse=True)


def test_14_events_log_returns_entries(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    ev = rep["sections"]["events_log"]
    assert ev["source"] == "audit_chain"
    assert ev["total_records"] == 3
    assert ev["returned"] == 3
    assert all("event_type" in e for e in ev["entries"])


# ===========================================================================
# audit_report_generator — integrity + health + IO (tests 15–22)
# ===========================================================================


def test_15_integrity_check_intact(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    ic = rep["sections"]["integrity_check"]
    assert ic["status"] == "INTACT"
    assert ic["verified"] is True
    assert ic["records"] == 3


def test_16_integrity_check_detects_tampering(synth_data, adr_dir):
    """Corrupting a chain record must flip integrity to TAMPERED."""
    chain = synth_data / audit_trail_signer.CHAIN_FILENAME
    lines = chain.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["n"] = 999  # mutate payload, leave chain_hash stale
    lines[1] = json.dumps(rec)
    chain.write_text("\n".join(lines) + "\n")

    sec = arg.build_integrity_section(synth_data)
    assert sec["status"] == "TAMPERED"
    assert sec["verified"] is False
    assert sec["tampered_record_index"] == 1


def test_17_integrity_no_chain_is_intact(tmp_path):
    """No chain file → nothing to verify → INTACT."""
    d = tmp_path / "data"
    d.mkdir()
    sec = arg.build_integrity_section(d)
    assert sec["verified"] is True
    assert sec["chain_exists"] is False


def test_18_system_health_fields(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    sh = rep["sections"]["system_health"]
    assert sh["golive_passed"] == 25
    assert sh["golive_total"] == 26
    assert sh["golive_ready"] is False
    assert isinstance(sh["error_count_7d"], int)


def test_19_write_report_creates_both_files(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    paths = arg.write_report(rep, data_dir=synth_data)
    assert os.path.isfile(paths["json"])
    assert os.path.isfile(paths["md"])


def test_20_written_json_roundtrips(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    paths = arg.write_report(rep, data_dir=synth_data)
    loaded = json.loads(Path(paths["json"]).read_text())
    assert loaded["sections"]["identity"]["statement"] == rep["sections"]["identity"]["statement"]


def test_21_markdown_has_all_section_headers(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    md = arg.render_markdown(rep)
    for h in ["## 1. Identity", "## 2. Governance", "## 3. Risk Controls",
              "## 4. Paper Track", "## 5. Positions", "## 6. Events Log",
              "## 7. Integrity Check", "## 8. System Health"]:
        assert h in md


def test_22_write_is_atomic_no_tmp_left(synth_data, adr_dir):
    rep = arg.generate_report(data_dir=synth_data, adr_dir=adr_dir)
    arg.write_report(rep, data_dir=synth_data)
    leftovers = [p for p in synth_data.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


# ===========================================================================
# monthly_statement (tests 23–30)
# ===========================================================================


def test_23_statement_generates(synth_data):
    st = ms.build_statement(data_dir=synth_data)
    assert st["report_type"] == "period_statement"
    assert st["period"] == "2026-06"


def test_24_statement_nav_math(synth_data):
    st = ms.build_statement(data_dir=synth_data, start="2026-06-10", end="2026-06-21")
    # window first open=100000, last close=100400
    assert st["starting_nav_usd"] == 100000.0
    assert st["ending_nav_usd"] == 100400.0
    assert st["return_usd"] == 400.0
    assert st["return_pct"] == pytest.approx(0.4)


def test_25_statement_annualization(synth_data):
    st = ms.build_statement(data_dir=synth_data, start="2026-06-10", end="2026-06-21")
    # period_days = 11; annualized = 0.4 / 11 * 365
    expected = 0.4 / 11 * 365
    assert st["annualized_return_pct"] == pytest.approx(round(expected, 4))


def test_26_annualize_helper_math():
    assert ms.annualize(1.0, 365) == pytest.approx(1.0)
    assert ms.annualize(0.5, 182.5) == pytest.approx(1.0)
    assert ms.annualize(1.0, 0) == 0.0


def test_27_statement_risk_events(synth_data):
    st = ms.build_statement(data_dir=synth_data, start="2026-06-10", end="2026-06-21")
    # 2 blocks in window (Jun 12, 13); May 01 block excluded.
    assert st["risk_events"]["risk_gate_blocks"] == 2
    assert st["risk_events"]["kill_switch_triggers"] == 0
    assert st["all_within_policy"] is True


def test_28_statement_attestation_text(synth_data):
    st = ms.build_statement(data_dir=synth_data)
    assert st["policy_attestation"] == "All positions within policy limits throughout period"


def test_29_statement_average_allocation(synth_data):
    st = ms.build_statement(data_dir=synth_data, start="2026-06-10", end="2026-06-21")
    avg = st["average_allocation_usd"]
    # aave_v3: (50000+50000+60000+60000)/4 = 55000
    assert avg["aave_v3"] == pytest.approx(55000.0)
    assert avg["morpho_blue"] == pytest.approx(35000.0)


def test_30_statement_write_to_statements_dir(synth_data):
    st = ms.build_statement(data_dir=synth_data)
    path = ms.write_statement(st, data_dir=synth_data)
    assert path.endswith(os.path.join("statements", "2026-06.json"))
    assert os.path.isfile(path)
    loaded = json.loads(Path(path).read_text())
    assert loaded["period"] == "2026-06"


# ===========================================================================
# Bonus: live-data smoke (does not count toward the 30 but proves real data)
# ===========================================================================


@pytest.mark.skipif(not (LIVE_DATA / "equity_curve_daily.json").exists(),
                    reason="live data not present")
def test_live_report_smoke():
    rep = arg.generate_report()
    assert rep["sections"]["risk_controls"]["total"] >= 6
    st = ms.build_statement()
    assert "ending_nav_usd" in st
