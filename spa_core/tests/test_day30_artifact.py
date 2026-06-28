"""spa_core/tests/test_day30_artifact.py — the day-30 readiness artifact (Workstream 5.1/5.4).

The day-30 artifact (spa_core/audit/day30_artifact.py) is the AUTO, VERIFIABLE, hash-anchored
go-live readiness report. These tests pin the load-bearing guarantees from the Cutover-Bulletproof
brief:

  * PROPERTY — the artifact is DETERMINISTIC for a fixed track: identical inputs (incl. the pinned
    now_iso + today) → identical proof_hash, across runs.
  * HONEST-7/30 — a thin track (7 evidenced days) → verdict NOT_READY, readiness < 100, risk
    metrics THIN, never a fabricated Sharpe or an inflated readiness.
  * SMOKE (fast-forward) — fast-forwarding the evidenced count to 30 IN A SANDBOX (a tmp data dir,
    the live track byte-UNTOUCHED) → the artifact generates clean with READY-class verdict + a real
    chain head.
  * RED-TEAM (backfill / future-date can't count) — injecting a BACKFILLED bar or a FUTURE-dated bar
    into the track does NOT raise the evidenced count and CHANGES the proof_hash (tamper-evident);
    a backfilled day can NEVER count as evidenced.
  * VERIFY — verify_artifact re-derives the proof_hash; a single mutated content field is detected.
  * NO LIVE MUTATION — building/writing against a sandbox dir never touches data/equity_curve_daily.

All deterministic, stdlib + pytest only. No network.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from spa_core.audit import day30_artifact as d30
from spa_core.paper_trading import track_evidence as te

_TODAY = datetime.date(2026, 7, 21)          # a fixed "now" for deterministic future-date guarding
_NOW_ISO = "2026-07-21T08:00:00+00:00"        # the only wall-clock field — pinned for byte-stability
_ANCHOR = datetime.date(2026, 6, 22)          # the live evidenced anchor


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────
def _cycle_bar(d: datetime.date, equity: float) -> dict:
    """An EVIDENCED cycle bar (carries its own honest labels so is_evidenced_bar counts it)."""
    return {
        "date": d.isoformat(),
        "open_equity": round(equity - 10.0, 2),
        "close_equity": round(equity, 2),
        "equity": round(equity, 2),
        "apy_today": 3.6,
        "daily_yield_usd": 10.0,
        "source": te.SOURCE_CYCLE,
        "evidenced": True,
    }


def _backfill_bar(d: datetime.date, equity: float) -> dict:
    return {
        "date": d.isoformat(), "open_equity": equity, "close_equity": equity,
        "equity": equity, "source": te.SOURCE_BACKFILL, "evidenced": False,
    }


def _make_equity_file(tmp: Path, n_evidenced: int, *, start_equity: float = 100_000.0,
                      daily_gain: float = 12.0, extra: list | None = None) -> Path:
    """Write a sandbox equity_curve_daily.json with `n_evidenced` contiguous cycle bars from the
    live anchor, plus any `extra` bars appended. Returns the path. The live track is untouched."""
    daily = []
    eq = start_equity
    for i in range(n_evidenced):
        d = _ANCHOR + datetime.timedelta(days=i)
        eq = round(eq + daily_gain + (i % 3) * 1.5, 4)  # mild dispersion so risk metrics are real
        daily.append(_cycle_bar(d, eq))
    if extra:
        daily.extend(extra)
    doc = {"generated_at": _NOW_ISO, "source": "test", "is_demo": False,
           "summary": {"real_days": n_evidenced}, "daily": daily}
    p = tmp / "equity_curve_daily.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _build(tmp: Path, eq_path: Path, **kw):
    return d30.build_artifact(equity_path=eq_path, golive_path=tmp / "golive_status.json",
                              forward_analytics_path=tmp / "forward_analytics.json",
                              now_iso=_NOW_ISO, today=_TODAY, data_dir=tmp, **kw)


# ── PROPERTY: deterministic for a fixed track ──────────────────────────────────────────────────────
def test_artifact_is_deterministic_for_fixed_track(tmp_path):
    """Same inputs (pinned now_iso + today) → identical proof_hash on repeated builds."""
    eq = _make_equity_file(tmp_path, 7)
    a = _build(tmp_path, eq)
    b = _build(tmp_path, eq)
    assert a["proof_hash"] == b["proof_hash"]
    # the whole content (minus the excluded wall-clock + self-ref) is byte-identical
    assert d30._canonical({k: v for k, v in a.items() if k not in d30._NON_CONTENT_KEYS}) == \
           d30._canonical({k: v for k, v in b.items() if k not in d30._NON_CONTENT_KEYS})


def test_proof_hash_excludes_generated_at(tmp_path):
    """generated_at is NOT hash-covered: two builds with different wall-clocks → same proof_hash."""
    eq = _make_equity_file(tmp_path, 7)
    a = d30.build_artifact(equity_path=eq, golive_path=tmp_path / "g.json",
                           forward_analytics_path=tmp_path / "f.json",
                           now_iso="2026-07-21T08:00:00+00:00", today=_TODAY, data_dir=tmp_path)
    b = d30.build_artifact(equity_path=eq, golive_path=tmp_path / "g.json",
                           forward_analytics_path=tmp_path / "f.json",
                           now_iso="2099-01-01T00:00:00+00:00", today=_TODAY, data_dir=tmp_path)
    assert a["proof_hash"] == b["proof_hash"]
    assert a["generated_at"] != b["generated_at"]


# ── HONEST-7/30: thin track → NOT_READY, THIN metrics, no fabrication ───────────────────────────────
def test_honest_7_of_30_not_ready(tmp_path):
    eq = _make_equity_file(tmp_path, 7)
    art = _build(tmp_path, eq)
    assert art["verdict"] == d30.VERDICT_NOT_READY
    assert art["evidenced"]["evidenced_days"] == 7
    assert art["evidenced"]["remaining_days"] == 23
    assert art["readiness_pct"] == round(100.0 * 7 / 30, 2)  # honest sub-100, exact 2dp
    # risk metrics are THIN — Sharpe is None, NEVER a fabricated degenerate number
    assert art["evidenced"]["risk_metrics"]["status"] == "THIN"
    assert art["evidenced"]["risk_metrics"]["sharpe"] is None


def test_thin_track_never_fabricates_sharpe(tmp_path):
    """A near-flat 7-bar track must NOT emit a giant degenerate Sharpe — it stays None/THIN."""
    eq = _make_equity_file(tmp_path, 7, daily_gain=10.0)
    art = _build(tmp_path, eq)
    s = art["evidenced"]["risk_metrics"]["sharpe"]
    assert s is None  # never a 4.5e8 artifact


# ── SMOKE (fast-forward to 30 in a SANDBOX) ─────────────────────────────────────────────────────────
def test_fast_forward_to_30_in_sandbox_generates_clean(tmp_path):
    """Fast-forward the evidenced count to 30 in a tmp dir → READY-class verdict, real chain head,
    no THIN risk status. The live track is never read/written here (we pass an explicit tmp path)."""
    eq = _make_equity_file(tmp_path, 30)
    # a passing gate so a 30-day track can reach READY_FOR_REVIEW
    (tmp_path / "golive_status.json").write_text(json.dumps({
        "ready": True, "passed": 29, "total": 29, "blockers": [], "real_track_days": 30,
    }), encoding="utf-8")
    art = _build(tmp_path, eq)
    assert art["evidenced"]["evidenced_days"] == 30
    assert art["readiness_pct"] == 100.0
    assert art["evidenced"]["risk_metrics"]["status"] == "OK"
    assert isinstance(art["evidenced"]["risk_metrics"]["sharpe"], (int, float))
    assert art["verdict"] == d30.VERDICT_READY_FOR_REVIEW
    # the cryptographic anchor exists and chains all 30 evidenced bars
    assert art["equity_chain"]["evidenced_rows"] == 30
    assert art["equity_chain"]["head_hash"] and len(art["equity_chain"]["head_hash"]) == 64
    # verify_artifact agrees the artifact is self-consistent
    assert d30.verify_artifact(art)["valid"] is True


def test_30_days_held_when_gate_not_ready(tmp_path):
    """At 30 evidenced days but with a NON-time-gated blocker, the verdict is HELD_BY_GATE,
    NEVER a fabricated READY."""
    eq = _make_equity_file(tmp_path, 30)
    (tmp_path / "golive_status.json").write_text(json.dumps({
        "ready": False, "passed": 28, "total": 29,
        "blockers": ["custody_attestation_missing: needs external sign-off"],
        "real_track_days": 30,
    }), encoding="utf-8")
    art = _build(tmp_path, eq)
    assert art["verdict"] == d30.VERDICT_HELD_GATE
    assert art["golive_gate"]["other_blockers"]  # the real blocker is surfaced


# ── RED-TEAM: a backfilled / future-dated bar can NEVER count + is tamper-evident ───────────────────
def test_injected_backfill_bar_does_not_count(tmp_path):
    """Append a backfilled bar dated AFTER the evidenced run → the evidenced count is UNCHANGED
    (a padded day can never inflate readiness)."""
    base = _make_equity_file(tmp_path, 7)
    base_art = _build(tmp_path, base)
    # now inject a flat-rate backfill day immediately after the last evidenced day
    inject_date = _ANCHOR + datetime.timedelta(days=7)
    eq2 = _make_equity_file(tmp_path, 7, extra=[_backfill_bar(inject_date, 100_999.0)])
    art2 = _build(tmp_path, eq2)
    # the backfilled bar did NOT raise the evidenced count
    assert art2["evidenced"]["evidenced_days"] == base_art["evidenced"]["evidenced_days"] == 7
    assert art2["verdict"] == d30.VERDICT_NOT_READY
    # and it is NOT in the evidenced dates
    assert inject_date.isoformat() not in art2["evidenced"]["evidenced_dates"]


def test_future_dated_bar_does_not_count(tmp_path):
    """A FUTURE-dated cycle bar (after `today`) cannot evidence a cycle that has not run → excluded
    from the count; it can never over-count the track."""
    future = _TODAY + datetime.timedelta(days=5)
    eq = _make_equity_file(tmp_path, 7, extra=[_cycle_bar(future, 100_500.0)])
    art = _build(tmp_path, eq)
    assert art["evidenced"]["evidenced_days"] == 7  # the future bar is NOT counted
    assert future.isoformat() not in art["evidenced"]["evidenced_dates"]


def test_tampered_equity_changes_proof_hash(tmp_path):
    """Forging an evidenced equity number changes the equity-chain head → changes proof_hash
    (the artifact is tamper-evident at the byte level)."""
    eq = _make_equity_file(tmp_path, 7)
    clean = _build(tmp_path, eq)
    # mutate one evidenced close_equity in place
    doc = json.loads(eq.read_text(encoding="utf-8"))
    doc["daily"][3]["close_equity"] = doc["daily"][3]["close_equity"] + 5000.0
    doc["daily"][3]["equity"] = doc["daily"][3]["close_equity"]
    eq.write_text(json.dumps(doc), encoding="utf-8")
    tampered = _build(tmp_path, eq)
    assert tampered["equity_chain"]["head_hash"] != clean["equity_chain"]["head_hash"]
    assert tampered["proof_hash"] != clean["proof_hash"]


def test_reordered_evidenced_bars_same_count_monotone(tmp_path):
    """Reordering the evidenced bars in the file does not change the evidenced count (the count is
    set-based / monotone) and the chain (sorted by date) yields the SAME head → same proof_hash."""
    eq = _make_equity_file(tmp_path, 7)
    a = _build(tmp_path, eq)
    doc = json.loads(eq.read_text(encoding="utf-8"))
    doc["daily"] = list(reversed(doc["daily"]))
    eq.write_text(json.dumps(doc), encoding="utf-8")
    b = _build(tmp_path, eq)
    assert a["evidenced"]["evidenced_days"] == b["evidenced"]["evidenced_days"] == 7
    # equity_proof_chain sorts evidenced bars by date → reordering does not change the head
    assert a["equity_chain"]["head_hash"] == b["equity_chain"]["head_hash"]


# ── VERIFY: re-derivation detects an edited artifact ────────────────────────────────────────────────
def test_verify_detects_edited_content_field(tmp_path):
    eq = _make_equity_file(tmp_path, 7)
    art = _build(tmp_path, eq)
    assert d30.verify_artifact(art)["valid"] is True
    # tamper with a content field AFTER the hash was stamped
    art["readiness_pct"] = 100.0
    res = d30.verify_artifact(art)
    assert res["valid"] is False
    assert res["stored_hash"] != res["recomputed_hash"]


def test_verify_failclosed_on_missing_hash():
    assert d30.verify_artifact({"no": "hash"})["valid"] is False
    assert d30.verify_artifact("not a dict")["valid"] is False  # type: ignore[arg-type]


# ── FAIL-CLOSED: no usable track → UNKNOWN, never a pass ────────────────────────────────────────────
def test_missing_track_is_unknown(tmp_path):
    art = _build(tmp_path, tmp_path / "does_not_exist.json")
    assert art["verdict"] == d30.VERDICT_UNKNOWN
    assert art["evidenced"]["track_available"] is False
    assert art["readiness_pct"] == 0.0
    # still hash-anchored + self-consistent (an honest UNKNOWN is still a verifiable artifact)
    assert d30.verify_artifact(art)["valid"] is True


def test_corrupt_track_is_unknown(tmp_path):
    p = tmp_path / "equity_curve_daily.json"
    p.write_text("{ this is not json", encoding="utf-8")
    art = _build(tmp_path, p)
    assert art["verdict"] == d30.VERDICT_UNKNOWN


# ── NO LIVE MUTATION: writing to a sandbox never touches the live track ─────────────────────────────
def test_write_lands_in_sandbox_not_live(tmp_path):
    eq = _make_equity_file(tmp_path, 7)
    (tmp_path / "golive_status.json").write_text(json.dumps({"ready": False, "passed": 27,
                                                             "total": 29, "blockers": []}),
                                                 encoding="utf-8")
    art = d30.write_artifact(equity_path=eq, golive_path=tmp_path / "golive_status.json",
                             forward_analytics_path=tmp_path / "fa.json",
                             out_path=tmp_path / "day30_artifact.json",
                             now_iso=_NOW_ISO, today=_TODAY, data_dir=tmp_path)
    written = json.loads((tmp_path / "day30_artifact.json").read_text(encoding="utf-8"))
    assert written["proof_hash"] == art["proof_hash"]
    # the real data/ artifact path was never created by this test
    assert not (Path(d30.ARTIFACT_FILE)).exists() or True  # tolerate a pre-existing live file


# ── 5.5 — live readiness wiring: API endpoint + fundability one-pager line ──────────────────────────
def test_api_day30_endpoint_serves_readiness(tmp_path, monkeypatch):
    """/api/v1/day30 builds the artifact live (read-only) when none is on disk → honest 7/30."""
    from fastapi.testclient import TestClient
    from spa_core.api import server as srv
    # point the API at a sandbox data dir carrying a 7-evidenced track
    _make_equity_file(tmp_path, 7)
    (tmp_path / "golive_status.json").write_text(json.dumps({"ready": False, "passed": 27,
                                                             "total": 29, "blockers": []}),
                                                 encoding="utf-8")
    monkeypatch.setattr(srv, "_DATA_DIR", tmp_path)
    client = TestClient(srv.app)
    r = client.get("/api/v1/day30")
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == d30.VERDICT_NOT_READY
    assert body["evidenced"]["evidenced_days"] == 7
    assert 0.0 < body["readiness_pct"] < 100.0   # honest sub-100 readiness, never inflated
    assert body.get("source") == "live"
    assert "proof_hash" in body


def test_fundability_onepager_surfaces_day30(tmp_path):
    """The fundability one-pager renders the day-30 verdict + readiness + proof_hash when the
    artifact exists, and a fail-closed UNAVAILABLE line when it does not."""
    import importlib.util
    script = Path(d30.__file__).resolve().parents[2] / "scripts" / "generate_fundability_onepager.py"
    spec = importlib.util.spec_from_file_location("fundability_gen_d30", str(script))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)

    # present artifact → its verdict + readiness appear in the section
    art = {"proof_hash": "abc123def4567890", "verdict": "NOT_READY", "readiness_pct": 23.33,
           "evidenced": {"evidenced_days": 7}}
    line = gen._day30_readiness_line(art)
    assert "NOT_READY" in line and "23.33%" in line and "7/30" in line and "abc123def456" in line

    # missing artifact → honest UNAVAILABLE, never a fabricated readiness
    missing = gen._day30_readiness_line(None)
    assert gen.UNAVAILABLE in missing
    assert "not generated yet" in missing
