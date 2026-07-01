"""spa_core/tests/test_day30_review.py — the RISKWIRE DAY-30 REVIEW PIPELINE (WS1.3).

The day-30 review pipeline (spa_core/riskwire/day30_review.py) is the comprehensive, self-verifying,
hash-anchored REVIEW a real reviewer/funder reads the moment the evidenced go-live track reaches 30
CONTINUOUS days. These tests pin the load-bearing guarantees from RISKWIRE_CHARTER WS1.3:

  * PROPERTY (deterministic)      — for a FIXED track (pinned now_iso + today) the review reproduces
                                    the same review_hash across runs; every cell traces to a realized
                                    source or reads THIN/None (never a fabricated number).
  * HONEST-9/30 (maturing)        — on the CURRENT 9/30-style track → state TRACK_MATURING, "21 days
                                    to go", NOT a premature REVIEW_READY; THIN metrics stay None.
  * SMOKE (fast-forward to 30)    — fast-forwarding the evidenced count to 30 CONTINUOUS days IN A
                                    SANDBOX (tmp data dir, live track byte-untouched) → REVIEW_READY
                                    with REAL risk metrics + a real review_hash.
  * RED-TEAM (gap / backfill)     — injecting a GAP (a missing evidenced day) or a backfilled bar into
                                    an otherwise-30-day track → the review REFUSES REVIEW_READY
                                    (DISCONTINUOUS) + flags the exact missing dates; a fabricated
                                    metric reads THIN/None, never a number; a tampered bar changes
                                    the review_hash (tamper-evident).
  * CONTINUITY ASSERTION          — assert_continuity is exact: contiguous → continuous; one hole →
                                    the hole is surfaced + continuous=False.
  * NO LIVE MUTATION              — building/writing against a sandbox dir never touches the live
                                    equity_curve_daily.json and never overwrites the canonical
                                    docs/DAY30_REVIEW.md.

All deterministic, stdlib + pytest only. No network.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path

from spa_core.riskwire import day30_review as dr
from spa_core.audit import day30_artifact as d30
from spa_core.paper_trading import track_evidence as te

_TODAY = datetime.date(2026, 7, 21)          # fixed "now" for deterministic future-date guarding
_NOW_ISO = "2026-07-21T08:00:00+00:00"        # the only wall-clock field — pinned for byte-stability
_ANCHOR = datetime.date(2026, 6, 22)          # the live evidenced anchor


# ── helpers (mirror the day30_artifact fixtures) ───────────────────────────────────────────────────
def _cycle_bar(d: datetime.date, equity: float) -> dict:
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
    return {"date": d.isoformat(), "open_equity": equity, "close_equity": equity,
            "equity": equity, "source": te.SOURCE_BACKFILL, "evidenced": False}


def _make_equity_file(tmp: Path, n_evidenced: int, *, start_equity: float = 100_000.0,
                      daily_gain: float = 12.0, skip: set | None = None,
                      extra: list | None = None) -> Path:
    """Write a sandbox equity_curve_daily.json with contiguous cycle bars from the anchor.

    ``skip`` = a set of 0-based day-offsets to OMIT (to inject a gap). ``extra`` = appended bars.
    The live track is untouched (we always write into ``tmp``)."""
    skip = skip or set()
    daily = []
    eq = start_equity
    for i in range(n_evidenced):
        d = _ANCHOR + datetime.timedelta(days=i)
        eq = round(eq + daily_gain + (i % 3) * 1.5, 4)
        if i in skip:
            continue
        daily.append(_cycle_bar(d, eq))
    if extra:
        daily.extend(extra)
    doc = {"generated_at": _NOW_ISO, "source": "test", "is_demo": False,
           "summary": {"real_days": len(daily)}, "daily": daily}
    p = tmp / "equity_curve_daily.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _passing_gate(tmp: Path, real_days: int = 30) -> Path:
    p = tmp / "golive_status.json"
    p.write_text(json.dumps({"ready": True, "passed": 29, "total": 29, "blockers": [],
                             "real_track_days": real_days}), encoding="utf-8")
    return p


def _build(tmp: Path, eq_path: Path, gl_path: Path | None = None, **kw):
    return dr.build_review(equity_path=eq_path,
                           golive_path=gl_path or (tmp / "golive_status.json"),
                           forward_analytics_path=tmp / "forward_analytics.json",
                           now_iso=_NOW_ISO, today=_TODAY, data_dir=tmp, **kw)


# ── PROPERTY: deterministic for a fixed track ──────────────────────────────────────────────────────
def test_review_is_deterministic_for_fixed_track(tmp_path):
    eq = _make_equity_file(tmp_path, 9)
    a = _build(tmp_path, eq)
    b = _build(tmp_path, eq)
    assert a["review_hash"] == b["review_hash"]
    assert dr._canonical({k: v for k, v in a.items() if k not in dr._NON_CONTENT_KEYS}) == \
           dr._canonical({k: v for k, v in b.items() if k not in dr._NON_CONTENT_KEYS})


def test_review_hash_excludes_generated_at(tmp_path):
    eq = _make_equity_file(tmp_path, 9)
    a = dr.build_review(equity_path=eq, golive_path=tmp_path / "g.json",
                        forward_analytics_path=tmp_path / "f.json",
                        now_iso="2026-07-21T08:00:00+00:00", today=_TODAY, data_dir=tmp_path)
    b = dr.build_review(equity_path=eq, golive_path=tmp_path / "g.json",
                        forward_analytics_path=tmp_path / "f.json",
                        now_iso="2099-01-01T00:00:00+00:00", today=_TODAY, data_dir=tmp_path)
    assert a["review_hash"] == b["review_hash"]
    assert a["generated_at"] != b["generated_at"]


# ── HONEST-9/30: current-track review is MATURING, never premature ──────────────────────────────────
def test_honest_9_of_30_track_maturing(tmp_path):
    eq = _make_equity_file(tmp_path, 9)
    rev = _build(tmp_path, eq)
    assert rev["state"] == dr.STATE_TRACK_MATURING
    assert rev["ready_for_review"] is False
    assert rev["remaining_days"] == 21
    assert "21 more" in rev["state_reason"] or "21" in rev["state_reason"]
    assert rev["review_readiness_pct"] == round(100.0 * 9 / 30, 2)
    # metrics THIN → None (never a fabricated Sharpe)
    assert rev["realized_risk_metrics"]["status"] == "THIN"
    assert rev["realized_risk_metrics"]["sharpe"] is None
    # a 9/30 track is continuous (no gap) but still NOT ready — maturity is separate from continuity
    assert rev["continuity"]["continuous"] is True


def test_thin_track_never_fabricates_metrics(tmp_path):
    eq = _make_equity_file(tmp_path, 9, daily_gain=10.0)
    rev = _build(tmp_path, eq)
    assert rev["realized_risk_metrics"]["sharpe"] is None
    assert rev["realized_risk_metrics"]["sortino"] is None


# ── SMOKE (fast-forward to 30 in a SANDBOX) → REVIEW_READY ──────────────────────────────────────────
def test_fast_forward_to_30_flips_review_ready(tmp_path):
    eq = _make_equity_file(tmp_path, 30)
    gl = _passing_gate(tmp_path, 30)
    rev = _build(tmp_path, eq, gl)
    assert rev["state"] == dr.STATE_REVIEW_READY
    assert rev["ready_for_review"] is True
    assert rev["remaining_days"] == 0
    assert rev["review_readiness_pct"] == 100.0
    # REAL risk metrics now (no longer THIN)
    assert rev["realized_risk_metrics"]["status"] == "OK"
    assert isinstance(rev["realized_risk_metrics"]["sharpe"], (int, float))
    # continuous, and the embedded artifact reads READY_FOR_REVIEW
    assert rev["continuity"]["continuous"] is True
    assert rev["continuity"]["n_missing"] == 0
    assert rev["day30_artifact"]["verdict"] == d30.VERDICT_READY_FOR_REVIEW
    # self-verifying (review hash + embedded artifact hash)
    assert dr.verify_review(rev)["valid"] is True


def test_30_days_held_when_gate_not_ready(tmp_path):
    """30 continuous days but a NON-time-gated blocker → HELD_BY_GATE, never a fabricated READY."""
    eq = _make_equity_file(tmp_path, 30)
    gl = tmp_path / "golive_status.json"
    gl.write_text(json.dumps({"ready": False, "passed": 28, "total": 29,
                              "blockers": ["custody_attestation_missing: needs external sign-off"],
                              "real_track_days": 30}), encoding="utf-8")
    rev = _build(tmp_path, eq, gl)
    assert rev["state"] == dr.STATE_HELD_BY_GATE
    assert rev["ready_for_review"] is False


# ── RED-TEAM: a GAP / backfill can NEVER produce REVIEW_READY ────────────────────────────────────────
def test_injected_gap_refuses_review_ready(tmp_path):
    """A 30-CALENDAR-day span with ONE missing evidenced day → DISCONTINUOUS; the review REFUSES
    REVIEW_READY and surfaces the exact missing date. This is the whole point of the pipeline."""
    # 30 bars spanning the anchor..anchor+30, but day-offset 15 is OMITTED (a real gap)
    eq = _make_equity_file(tmp_path, 31, skip={15})   # 30 evidenced bars, but 1 calendar hole
    gl = _passing_gate(tmp_path, 30)
    rev = _build(tmp_path, eq, gl)
    assert rev["state"] == dr.STATE_DISCONTINUOUS
    assert rev["ready_for_review"] is False
    assert rev["continuity"]["continuous"] is False
    missing_iso = (_ANCHOR + datetime.timedelta(days=15)).isoformat()
    assert missing_iso in rev["continuity"]["missing_dates"]
    assert "DISCONTINUOUS" in rev["state_reason"] or "gap" in rev["state_reason"].lower()


def test_injected_backfill_bar_cannot_count_or_bridge_gap(tmp_path):
    """A backfilled bar dropped into the gap does NOT evidence it → still DISCONTINUOUS. A padded
    day can neither raise the evidenced count nor bridge a gap."""
    missing_date = _ANCHOR + datetime.timedelta(days=15)
    eq = _make_equity_file(tmp_path, 31, skip={15},
                           extra=[_backfill_bar(missing_date, 100_500.0)])
    gl = _passing_gate(tmp_path, 30)
    rev = _build(tmp_path, eq, gl)
    assert rev["state"] == dr.STATE_DISCONTINUOUS
    assert missing_date.isoformat() in rev["continuity"]["missing_dates"]


def test_tampered_evidenced_bar_changes_review_hash(tmp_path):
    """Forging an evidenced equity number → the embedded artifact proof_hash changes → the
    review_hash changes (tamper-evident end to end)."""
    eq = _make_equity_file(tmp_path, 30)
    gl = _passing_gate(tmp_path, 30)
    clean = _build(tmp_path, eq, gl)
    doc = json.loads(eq.read_text(encoding="utf-8"))
    doc["daily"][10]["close_equity"] += 5000.0
    doc["daily"][10]["equity"] = doc["daily"][10]["close_equity"]
    eq.write_text(json.dumps(doc), encoding="utf-8")
    tampered = _build(tmp_path, eq, gl)
    assert tampered["review_hash"] != clean["review_hash"]
    assert tampered["day30_artifact"]["proof_hash"] != clean["day30_artifact"]["proof_hash"]


def test_future_dated_bar_cannot_over_count(tmp_path):
    """A FUTURE-dated cycle bar (after `today`) is excluded → cannot over-count to 30."""
    future = _TODAY + datetime.timedelta(days=5)
    eq = _make_equity_file(tmp_path, 9, extra=[_cycle_bar(future, 100_500.0)])
    rev = _build(tmp_path, eq)
    assert rev["day30_artifact"]["evidenced"]["evidenced_days"] == 9
    assert rev["state"] == dr.STATE_TRACK_MATURING


# ── THE CONTINUITY ASSERTION (exact) ────────────────────────────────────────────────────────────────
def test_assert_continuity_contiguous():
    dates = [(_ANCHOR + datetime.timedelta(days=i)).isoformat() for i in range(9)]
    res = dr.assert_continuity(dates)
    assert res["continuous"] is True
    assert res["n_evidenced"] == 9
    assert res["n_missing"] == 0
    assert res["span_days"] == 9


def test_assert_continuity_surfaces_gap():
    dates = [(_ANCHOR + datetime.timedelta(days=i)).isoformat() for i in range(9) if i != 4]
    res = dr.assert_continuity(dates)
    assert res["continuous"] is False
    assert res["n_evidenced"] == 8
    assert res["n_missing"] == 1
    assert (_ANCHOR + datetime.timedelta(days=4)).isoformat() in res["missing_dates"]


def test_assert_continuity_empty_is_failclosed():
    res = dr.assert_continuity([])
    assert res["continuous"] is False   # nothing to review → never "continuous"


def test_assert_continuity_order_and_dupes_dont_break_it():
    """Out-of-order + duplicate dates collapse to the same continuous verdict (set-based)."""
    dates = [(_ANCHOR + datetime.timedelta(days=i)).isoformat() for i in range(9)]
    shuffled = list(reversed(dates)) + [dates[3], dates[3]]
    res = dr.assert_continuity(shuffled)
    assert res["continuous"] is True
    assert res["n_evidenced"] == 9


# ── VERIFY: re-derivation detects an edited review ──────────────────────────────────────────────────
def test_verify_detects_edited_content_field(tmp_path):
    eq = _make_equity_file(tmp_path, 9)
    rev = _build(tmp_path, eq)
    assert dr.verify_review(rev)["valid"] is True
    rev["review_readiness_pct"] = 100.0
    res = dr.verify_review(rev)
    assert res["valid"] is False
    assert res["stored_hash"] != res["recomputed_hash"]


def test_verify_failclosed_on_missing_hash():
    assert dr.verify_review({"no": "hash"})["valid"] is False
    assert dr.verify_review("not a dict")["valid"] is False  # type: ignore[arg-type]


# ── FAIL-CLOSED: no usable track → UNKNOWN, never a pass ─────────────────────────────────────────────
def test_missing_track_is_unknown(tmp_path):
    rev = _build(tmp_path, tmp_path / "does_not_exist.json")
    assert rev["state"] == dr.STATE_UNKNOWN
    assert rev["ready_for_review"] is False
    assert rev["review_readiness_pct"] == 0.0
    assert dr.verify_review(rev)["valid"] is True   # an honest UNKNOWN is still verifiable


# ── NO LIVE MUTATION: writing to a sandbox never touches live track / canonical doc ─────────────────
def test_write_lands_in_sandbox_not_live(tmp_path):
    eq = _make_equity_file(tmp_path, 30)
    gl = _passing_gate(tmp_path, 30)
    # capture the live canonical doc's pre-state (if any)
    canonical_md = Path(dr.REVIEW_MD)
    pre = canonical_md.read_text(encoding="utf-8") if canonical_md.exists() else None
    rev = dr.write_review(equity_path=eq, golive_path=gl,
                          forward_analytics_path=tmp_path / "fa.json",
                          now_iso=_NOW_ISO, today=_TODAY, data_dir=tmp_path)
    # JSON landed in the sandbox, not the live dir
    written = json.loads((tmp_path / "riskwire" / "day30_review.json").read_text(encoding="utf-8"))
    assert written["review_hash"] == rev["review_hash"]
    # a sandbox run must NOT overwrite the canonical docs/DAY30_REVIEW.md
    post = canonical_md.read_text(encoding="utf-8") if canonical_md.exists() else None
    assert post == pre   # unchanged (sandbox run skipped the canonical .md)


def test_sandbox_md_written_only_with_explicit_out(tmp_path):
    """A sandbox run writes the .md ONLY when an explicit out_md is given (defence-in-depth)."""
    eq = _make_equity_file(tmp_path, 9)
    out_md = tmp_path / "DAY30_REVIEW.md"
    dr.write_review(equity_path=eq, golive_path=tmp_path / "g.json",
                    forward_analytics_path=tmp_path / "f.json",
                    out_md=out_md, now_iso=_NOW_ISO, today=_TODAY, data_dir=tmp_path)
    assert out_md.exists()
    body = out_md.read_text(encoding="utf-8")
    assert "Day-30 Review" in body and "TRACK_MATURING" in body


def test_markdown_renders_honestly_on_thin_track(tmp_path):
    eq = _make_equity_file(tmp_path, 9)
    rev = _build(tmp_path, eq)
    md = dr.render_markdown(rev)
    assert "TRACK_MATURING" in md
    assert "THIN" in md   # metrics honestly labelled THIN, never a fabricated Sharpe
    assert "floor + ~50" in md or "50–150 bps" in md   # honest fundability framing present
