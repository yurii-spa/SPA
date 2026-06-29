"""
tests/test_round2_ws6_fundable.py — ROUND-2 WS6 "the genuinely-fundable artifact" verification.

Pins the REALIZED-ONLY fundability sheet (6.1), the honest what-we-are/aren't one-pager (6.2), and
the self-verifying DD-pack reproduction (6.3) — INCLUDING the red-team the workstream bakes in:

  • a fundability claim that cites a BACKTEST as realized                 → CAUGHT (fenced / absent);
  • an INSUFFICIENT_DATA hidden behind a rounded "0.0"                    → CAUGHT (null bps shown);
  • the verifier passing on a TAMPERED fundability number                → CAUGHT (recompute diverges);
  • smoke: verify_spa reproduces every fundability number from a FIXTURE  → reproduced == published.

Pure stdlib + pytest. Deterministic (-p no:randomly). LLM-forbidden. NEVER touches live data/ — every
test runs against a hermetic temp data dir.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FUND_GEN = _REPO_ROOT / "scripts" / "generate_fundability_onepager.py"
_HONEST_GEN = _REPO_ROOT / "scripts" / "generate_fundable_honest.py"
_VERIFY = _REPO_ROOT / "scripts" / "verify_spa.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FUND = _load(_FUND_GEN, "ws6_fund")
HONEST = _load(_HONEST_GEN, "ws6_honest")
VERIFY = _load(_VERIFY, "ws6_verify")


# ───────────────────────────────────────────────────────────────────────────
# Fixtures — a hermetic data dir with realized artifacts + raw series.
# ───────────────────────────────────────────────────────────────────────────
def _write(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _series(name: str, equities, start="2026-06-24"):
    """Build a clean, contiguous-day forward series doc (one row per day)."""
    import datetime
    d0 = datetime.date.fromisoformat(start)
    pts = []
    for i, eq in enumerate(equities):
        d = (d0 + datetime.timedelta(days=i)).isoformat()
        pts.append({"date": d, "ts": d + "T00:00:00+00:00", "equity_usd": eq})
    return {"id": name, "series": pts, "generated_at": "fixed"}


@pytest.fixture
def repo(tmp_path):
    """A hermetic repo: raw series + a carry_truth_table.json computed by the REAL producer over them,
    so the published bps are genuinely reproducible (the honest baseline the verifier must reproduce)."""
    root = tmp_path
    d = root / "data"
    # raw forward series across the three dirs carry_truth_table reads from.
    # an ABOVE-floor-ish book, a BELOW-floor book, and a thin (<2pt) book.
    _write(d / "rates_desk" / "paper" / "rates_desk_fixed_carry_series.json",
           _series("rates_desk_fixed_carry", [100000.0, 100002.0, 99998.0, 99999.0, 100001.0]))
    _write(d / "strategy_lab_paper" / "engine_b_series.json",
           _series("engine_b", [20000.0, 20003.0, 20006.0, 20009.0, 20012.0, 20015.0]))
    _write(d / "realized_ab" / "optimized_yield_series.json",
           _series("optimized_yield", [100000.0]))  # 1 point → INSUFFICIENT_DATA null bps

    # generate the carry truth-table with the REAL producer over this hermetic dir (advisory; never
    # touches a go-live track — there is none here).
    from spa_core.strategy_lab import carry_truth_table as ctt
    ctt.build_carry_truth_table(data_dir=d, write=True, now_iso="fixed")

    # minimal other realized artifacts for the doc generators (sourced or UNAVAILABLE either way).
    _write(d / "golive_status.json", {
        "passed": 27, "total": 29, "real_track_days": 8,
        "evidenced_anchor": "2026-06-22", "target_date": "2026-07-21"})
    _write(d / "edge_at_scale.json", {
        "materiality_pp": 0.25, "edge_survives_at_max_aum": False,
        "edge_below_materiality_at_aum_usd": 1000000.0,
        "curve": [
            {"aum_usd": 100000.0, "legacy_yield_on_capital_pct": 4.5,
             "optimized_yield_on_capital_pct": 5.58, "uplift_pp": 1.08, "uplift_material": True},
            {"aum_usd": 10000000.0, "legacy_yield_on_capital_pct": 1.83,
             "optimized_yield_on_capital_pct": 0.84, "uplift_pp": -0.99, "uplift_material": False},
        ]})
    _write(d / "realized_ab" / "realized_ab.json", {
        "is_realized": True, "n_days": 1, "min_days_for_verdict": 7, "verdict": "INSUFFICIENT_DATA",
        "decomposition": {"raw_uplift_bps": 108.0, "selection_alpha_bps": 130.5,
                          "cash_drag_bps": 22.5}})
    _write(d / "refusal_cost.json", {
        "cost_of_caution_bps_per_yr_if_real": 651.30, "n_days": 4, "min_days_for_agg": 7,
        "interpretation": {"defensible": "DEFENSIBLE while the realized carry track is thin"}})
    _write(d / "rates_desk" / "decision_log.jsonl", {})  # placeholder; generators use jsonl loader
    (d / "rates_desk" / "decision_log.jsonl").write_text(
        "\n".join(json.dumps(r) for r in [
            {"kind": "REFUSAL", "reason": "tail_veto", "underlying": "ezeth"},
            {"kind": "ENTRY", "reason": "none", "underlying": "susde"},
        ]), encoding="utf-8")
    return root


# ===========================================================================
# 6.1 — REALIZED-ONLY fundability sheet
# ===========================================================================
def test_fundability_realized_section_is_realized_only(repo):
    doc = FUND.generate(root=str(repo), now_iso="FIXED")
    # the realized-edge section exists and is explicitly realized-only.
    assert "## 2. The realized edge" in doc
    assert "realized-only, never backtest" in doc
    # the carry truth-table verdict is surfaced (every sleeve INSUFFICIENT_DATA at this depth).
    assert "INSUFFICIENT_DATA" in doc
    # the honest one-line: does NOT claim it beats the floor on realized data.
    assert "does **not** yet demonstrably beat the floor" in doc.lower() or \
           "does not yet demonstrably beat the floor" in doc.lower() or \
           "do not claim" in doc.lower()


def test_fundability_backtest_is_fenced_not_realized(repo):
    """RED-TEAM: a backtest figure must NEVER be presented as realized. The promotion table is
    explicitly fenced as BACKTEST; the realized section contains no backtest figure."""
    doc = FUND.generate(root=str(repo), now_iso="FIXED")
    # the backtest engine section is explicitly labeled BACKTEST (not realized).
    assert "BACKTEST (not realized)" in doc
    # the §2 realized-only section's BODY (after its own honesty header) must not present a backtest
    # figure as realized: the only occurrences of "backtest" in §2 are the realized-only DISCLAIMER
    # ("realized-only, never backtest"), never a fenced backtest TABLE like the §3 promotion table.
    realized_sec = doc.split("## 2. The realized edge")[1].split("## 3.")[0]
    assert "BACKTEST (not realized)" not in realized_sec  # the fenced backtest table is in §3, not §2
    assert "net APY %/yr (BACKTEST)" not in realized_sec  # the backtest table header is in §3, not §2
    # the misleading "verdict rests on the realized book APY beating the floor" claim is GONE.
    assert "rests on the realized book APY beating the floor" not in doc


def test_fundability_insufficient_data_not_masked_as_zero(repo):
    """RED-TEAM: a null carry bps must render as INSUFFICIENT_DATA, never a rounded 0.0 that looks
    like a real at-floor verdict."""
    # the 1-point optimized_yield sleeve has a null bps → must show INSUFFICIENT_DATA, not '0.00 bps'.
    doc = FUND.generate(root=str(repo), now_iso="FIXED")
    # find the optimized_yield row in the §2a table.
    row = [ln for ln in doc.splitlines() if ln.startswith("| optimized_yield ")]
    assert row, "optimized_yield row missing from carry truth-table"
    assert "INSUFFICIENT_DATA" in row[0]
    assert "0.00 bps" not in row[0]      # a null must NOT have been rounded to 0.00 bps
    # the _fmt_bps helper itself: None → INSUFFICIENT_DATA, never '0.00 bps'.
    assert FUND._fmt_bps(None) == "INSUFFICIENT_DATA"
    assert FUND._fmt_bps(0.0) == "+0.00 bps"   # a REAL measured 0.0 is fine (it's not None)


def test_fundability_deterministic(repo):
    a = FUND.generate(root=str(repo), now_iso="FIXED")
    b = FUND.generate(root=str(repo), now_iso="FIXED")
    assert a == b


def test_fundability_missing_realized_sources_unavailable_not_fabricated(tmp_path):
    """An empty repo degrades the realized section to honest UNAVAILABLE, never invents numbers."""
    doc = FUND.generate(root=str(tmp_path), now_iso="FIXED")
    assert "## 2. The realized edge" in doc
    assert "data unavailable" in doc
    # no fabricated realized numbers leaked.
    assert "carry_truth_table.json missing" in doc


# ===========================================================================
# 6.2 — honest "what we are / aren't" one-pager
# ===========================================================================
def test_honest_names_every_gap(repo):
    doc = HONEST.generate(root=str(repo), now_iso="FIXED")
    # the three honest buckets are all present.
    assert "What is genuinely world-class" in doc
    assert "What is still maturing" in doc
    assert "owner-gated" in doc.lower()
    # it names the realized-edge gap explicitly (INSUFFICIENT_DATA, at/below floor, scale compression).
    assert "INSUFFICIENT_DATA" in doc
    assert "do NOT claim the desk beats the floor on realized data yet" in doc
    assert "compresses at scale" in doc.lower() or "compress at scale" in doc.lower()
    # owner-gated legs named.
    for gate in ("Custody", "audit", "Legal", "Capital"):
        assert gate in doc


def test_honest_no_claim_exceeds_evidence(repo):
    """The honest one-pager must NOT assert the edge is proven, and must NOT present a backtest."""
    doc = HONEST.generate(root=str(repo), now_iso="FIXED")
    assert "We do not claim the edge is proven" in doc
    assert "we do not claim $10M is reachable today" in doc
    # NO backtest FIGURE presented as realized. The honest disclaimer "NO backtest figure is
    # presented as realized" is allowed (it is the contract); a fenced backtest TABLE is not.
    assert "NO backtest figure is presented as realized" in doc
    assert "net APY %/yr (BACKTEST)" not in doc       # no backtest promotion table here
    assert "PAPER_CANDIDATE" not in doc               # no backtest sleeve stages presented
    # the only number in §1 is the LOGGED decision count (a count, not a return) — present from mock.
    assert "decisions" in doc


def test_honest_deterministic(repo):
    assert HONEST.generate(root=str(repo), now_iso="FIXED") == HONEST.generate(root=str(repo), now_iso="FIXED")


def test_honest_fmt_bps_null_is_insufficient(repo):
    assert HONEST._fmt_bps(None) == "INSUFFICIENT_DATA"
    assert HONEST._fmt_bps(float("inf")) == "INSUFFICIENT_DATA"
    assert HONEST._fmt_bps(-247.38) == "-247.38 bps"


# ===========================================================================
# 6.3 — self-verifying DD-pack: verify_spa reproduces the fundability numbers
# ===========================================================================
def test_verifier_reproduces_fundability_from_raw_series(repo):
    """SMOKE: verify_spa --check-fundability reproduces EVERY published carry bps from the RAW
    series in the hermetic fixture. reproduced == published, valid=True."""
    res = VERIFY.verify_fundability(repo / "data")
    assert res["available"] is True
    assert res["valid"] is True, res.get("mismatches")
    assert res["n_checked"] >= 3
    assert res["n_matched"] == res["n_checked"]
    assert res["mismatches"] == []


def test_verifier_catches_forged_bps(repo):
    """RED-TEAM: forge a published bps → the recompute from the raw series DIVERGES → FAIL CLOSED."""
    table = repo / "data" / "carry_truth_table.json"
    doc = json.loads(table.read_text())
    forged = False
    for r in doc["rows"]:
        if r["sleeve"] == "engine_b" and r["carry_above_floor_bps"] is not None:
            r["carry_above_floor_bps"] = 9999.99   # forged — not reproducible from raw series
            forged = True
    assert forged, "fixture must have a measurable engine_b bps to forge"
    table.write_text(json.dumps(doc))
    res = VERIFY.verify_fundability(repo / "data")
    assert res["valid"] is False
    assert any(m["sleeve"] == "engine_b" and "mismatch" in m["reason"] for m in res["mismatches"])


def test_verifier_catches_insufficient_data_masked_as_null(repo):
    """RED-TEAM: a real measurable bps published as null (hiding a result) → CAUGHT."""
    table = repo / "data" / "carry_truth_table.json"
    doc = json.loads(table.read_text())
    masked = False
    for r in doc["rows"]:
        if r["sleeve"] == "engine_b" and r["carry_above_floor_bps"] is not None:
            r["carry_above_floor_bps"] = None   # mask a real result as INSUFFICIENT_DATA
            masked = True
    assert masked
    table.write_text(json.dumps(doc))
    res = VERIFY.verify_fundability(repo / "data")
    assert res["valid"] is False
    assert any(m["sleeve"] == "engine_b" and "masked" in m["reason"] for m in res["mismatches"])


def test_verifier_catches_null_published_as_real_bps(repo):
    """RED-TEAM (the inverse): a null published as a real bps where the raw series is unmeasurable
    (the 1-point optimized_yield book) → CAUGHT (raw series can't reproduce it)."""
    table = repo / "data" / "carry_truth_table.json"
    doc = json.loads(table.read_text())
    for r in doc["rows"]:
        if r["sleeve"] == "optimized_yield":
            assert r["carry_above_floor_bps"] is None  # the honest baseline
            r["carry_above_floor_bps"] = 42.0          # forge a number onto an unmeasurable book
    table.write_text(json.dumps(doc))
    res = VERIFY.verify_fundability(repo / "data")
    assert res["valid"] is False
    assert any(m["sleeve"] == "optimized_yield" for m in res["mismatches"])


def test_verifier_run_check_fundability_exit_code(tmp_path):
    """End-to-end: VERIFY.run(..., check_fundability=True) on a dir holding ONLY the realized
    artifacts (no proof chains, no series producers) is ok=True — the fundability reproduction is
    itself a complete, self-standing check."""
    import datetime
    d = tmp_path / "data"
    # raw series in a NON-producer dir (strategy_lab_paper/ + realized_ab/ are not FAIL#5 producers)
    def series(name, eqs, start="2026-06-24"):
        d0 = datetime.date.fromisoformat(start)
        return {"id": name, "series": [
            {"date": (d0 + datetime.timedelta(days=i)).isoformat(), "equity_usd": eq}
            for i, eq in enumerate(eqs)]}
    _write(d / "strategy_lab_paper" / "engine_b_series.json",
           series("engine_b", [20000.0, 20003.0, 20006.0, 20009.0, 20012.0, 20015.0]))
    _write(d / "realized_ab" / "optimized_yield_series.json", series("optimized_yield", [100000.0]))
    from spa_core.strategy_lab import carry_truth_table as ctt
    ctt.build_carry_truth_table(data_dir=d, write=True, now_iso="fixed")

    rep = VERIFY.run([str(d)], check_fundability=True)
    assert rep["fundability"] is not None
    assert rep["fundability"]["valid"] is True, rep["fundability"].get("mismatches")
    # no proof chains / producers present → the only check is fundability, which passed → ok=True.
    assert rep["ok"] is True, rep["errors"]


def test_verifier_fundability_missing_table_fails_closed(tmp_path):
    """No carry_truth_table.json → fundability check fails CLOSED (never a silent pass)."""
    (tmp_path / "data").mkdir()
    res = VERIFY.verify_fundability(tmp_path / "data")
    assert res["valid"] is False
    assert res["available"] is False
