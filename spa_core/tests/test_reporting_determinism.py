"""
D3-T2 — determinism + non-finite-safety guards on SPA's strongest artifacts.

This pins the byte-stability contract on:
  1. the FUNDABILITY one-pager generator (scripts/generate_fundability_onepager.py) — the
     day-30 fundable artifact MUST regenerate byte-identically from fixed inputs (no embedded
     wall-clock, no dict-ordering drift, no float-repr drift),
  2. the forward_analytics scorecard JSON the one-pager consumes — byte-stable on disk from
     fixed inputs (atomic write of an insertion-ordered, fixed-float-format doc),
  3. that a non-finite (NaN/inf) number NEVER reaches the rendered artifact — it is fail-CLOSED
     to UNKNOWN / data-unavailable upstream, never serialized as an invalid ``NaN`` token.

stdlib-only, deterministic, fail-CLOSED. No network, no I/O outside tmp_path.
"""
# LLM_FORBIDDEN
import importlib.util
import json
import math
import os

import pytest

from spa_core.strategy_lab import forward_analytics as fa


# ── load the fundability generator as a module (it's a script, not a package) ──
_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts",
    "generate_fundability_onepager.py",
)


def _load_gen():
    spec = importlib.util.spec_from_file_location("fundability_gen_det", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEN = _load_gen()
_FLOOR = 3.4


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


# --------------------------------------------------------------------------- #
# 1. FUNDABILITY one-pager — byte-stable regen from fixed inputs
# --------------------------------------------------------------------------- #
@pytest.fixture
def populated_repo(tmp_path):
    d = tmp_path / "data"
    rd = d / "rates_desk"
    _write(str(d / "golive_status.json"), {
        "passed": 27, "total": 29, "real_track_days": 6,
        "evidenced_anchor": "2026-06-22", "target_date": "2026-07-21",
    })
    _write(str(rd / "rates_desk_promotion.json"), {
        "rwa_floor_pct": 3.4,
        "sleeves": [{"shape": "fixed_carry", "stage": "PAPER_CANDIDATE",
                     "net_apy_pct": 6.0901, "beats_floor": True, "max_drawdown_pct": 0.0,
                     "refusals_count": 42, "kills": 0}],
    })
    with open(str(rd / "decision_log.jsonl"), "w", encoding="utf-8") as fh:
        for r in [{"kind": "REFUSAL", "reason": "tail_veto", "underlying": "ezeth"},
                  {"kind": "ENTRY", "reason": "none", "underlying": "susde"}]:
            fh.write(json.dumps(r) + "\n")
    _write(str(d / "rwa_safety_board.json"), {
        "n_assets": 10, "n_not_cash_like": 10,
        "verdict_counts": {"LIQUID": 0, "THIN": 2, "REDEMPTION_ONLY": 7, "UNSAFE": 1},
        "onchain_nav_coverage": {"max_abs_nav_divergence_pct": 6.0901},
    })
    _write(str(d / "forward_track_integrity.json"), {"all_ok": True, "n_tracks": 8, "n_failing": 0})
    _write(str(d / "golive_dry_run.json"), {
        "moves_capital": False, "all_gates_reached": True, "ordering_ok": True,
        "would_proceed": False, "live_trading_gate_active": False,
        "gates": [{"name": "nav_reconciliation", "verdict": "PASS"}],
    })
    _write(str(d / "forward_analytics.json"), {
        "model": "forward_analytics", "rwa_floor_apy_pct": 3.4, "min_points_for_ratio": 7,
        "max_dd_band_pct": 15.0, "n_tracks": 1, "n_unknown": 0, "n_thin_track": 1, "n_beats_floor": 0,
        "tracks": [{
            "name": "paper/rates_desk_fixed_carry", "n_points": 6,
            "first_date": "2026-06-22", "last_date": "2026-06-27",
            "integrity_ok": True, "integrity_reason": "ok",
            "ann_return_pct": 6.0901, "max_dd_pct": 0.0, "rolling_vol_pct": 0.0,
            "sharpe": "UNKNOWN", "sortino": "UNKNOWN", "locked_vol": False,
            "floor_apy_pct": 3.4, "excess_vs_floor_pct": 2.6901, "verdict": "THIN_TRACK",
        }],
        "carry_book_stress_overlay": {
            "held_pt_notional_usd": 14545.0, "current_equity_usd": 100003.69,
            "max_dd_band_pct": 15.0, "scenarios": [], "worst_stress_dd_pct": 0.0,
            "survives_all": True, "n_open_books": 2,
        },
    })
    return str(tmp_path)


def test_fundability_byte_stable_fixed_inputs(populated_repo):
    """Same sources + same injected timestamp → byte-identical markdown across repeated runs."""
    docs = [GEN.generate(root=populated_repo, now_iso="FIXED").encode("utf-8")
            for _ in range(5)]
    assert len(set(docs)) == 1, "FUNDABILITY one-pager is NOT byte-stable from fixed inputs"


def test_fundability_timestamp_is_injected_not_wallclock(populated_repo):
    """The only non-determinism is the injected timestamp; two distinct stamps differ ONLY there."""
    a = GEN.generate(root=populated_repo, now_iso="STAMP-A")
    b = GEN.generate(root=populated_repo, now_iso="STAMP-B")
    assert a != b
    # normalizing the stamp back makes them identical → nothing else drifted
    assert a.replace("STAMP-A", "X") == b.replace("STAMP-B", "X")


def test_fundability_default_timestamp_is_utc_string(populated_repo):
    """With no injected stamp the generator embeds a UTC wall-clock — confirm it is THE only
    moving part (so prod regen diffs are limited to the timestamp line)."""
    doc = GEN.generate(root=populated_repo)  # live stamp
    assert "Regenerated " in doc and "UTC" in doc


# --------------------------------------------------------------------------- #
# 2. forward_analytics scorecard — byte-stable on-disk JSON from fixed inputs
# --------------------------------------------------------------------------- #
def _seed(tmp_path):
    import datetime
    rates = tmp_path / "rates_desk" / "paper"
    lab = tmp_path / "strategy_lab_paper"
    rates.mkdir(parents=True, exist_ok=True)
    lab.mkdir(parents=True, exist_ok=True)

    def series(name, eqs):
        base = datetime.date(2026, 6, 1)
        return {"id": name, "series": [
            {"date": (base + datetime.timedelta(days=i)).isoformat(), "equity_usd": float(e)}
            for i, e in enumerate(eqs)]}

    (rates / "rates_desk_fixed_carry_series.json").write_text(
        json.dumps(series("rates_desk_fixed_carry", [100000.0, 100001.85, 100003.69])))
    (lab / "engine_a_series.json").write_text(
        json.dumps(series("engine_a",
                          [100000.0, 100012.0, 100024.0, 100033.0, 100043.0, 100050.0, 100060.0, 100070.0])))
    (rates / "rates_desk_fixed_carry_state.json").write_text(json.dumps(
        {"state": {"capital": "100000.0", "cash": "85454.0", "accrued": "3.69",
                   "books": {"x": {"size": "7634.0"}, "y": {"size": "6911.0"}}}}))


def test_scorecard_json_byte_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(fa.metrics, "rwa_floor_apy_pct", lambda *a, **k: _FLOOR)
    _seed(tmp_path)
    out = tmp_path / "forward_analytics.json"
    runs = []
    for _ in range(4):
        fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=True, now_iso="FIXED-TS")
        runs.append(out.read_bytes())
    assert len(set(runs)) == 1, "scorecard JSON is NOT byte-stable from fixed inputs"
    # and it is real, parseable JSON (no NaN/Infinity tokens that break strict parsers)
    doc = json.loads(out.read_text())  # strict by default — would raise on NaN/Infinity
    assert doc["generated_at"] == "FIXED-TS"


def test_scorecard_json_no_nonfinite_tokens(tmp_path, monkeypatch):
    """Even with a degenerate (locked-vol / thin) book, the serialized JSON contains NO
    NaN/Infinity tokens — strict json.loads(...) round-trips cleanly."""
    monkeypatch.setattr(fa.metrics, "rwa_floor_apy_pct", lambda *a, **k: _FLOOR)
    _seed(tmp_path)
    fa.build_scorecard(data_dir=tmp_path, floor_apy_pct=_FLOOR, write=True, now_iso="TS")
    raw = (tmp_path / "forward_analytics.json").read_text()
    assert "NaN" not in raw and "Infinity" not in raw
    # parse_constant fires only on NaN/Infinity/-Infinity → assert it never triggers
    json.loads(raw, parse_constant=lambda c: (_ for _ in ()).throw(
        AssertionError(f"non-finite token {c!r} leaked into scorecard JSON")))


# --------------------------------------------------------------------------- #
# 3. non-finite never reaches the rendered fundability artifact
# --------------------------------------------------------------------------- #
def test_fundability_renders_no_nonfinite_from_corrupt_scorecard(populated_repo):
    """If a corrupt (NaN/inf) number somehow lands in the scorecard the one-pager consumes, the
    rendered markdown must NOT echo an invalid 'nan'/'inf' — the generator formats fail-closed.
    (Belt-and-braces over the upstream metric guard.)"""
    sc_path = os.path.join(populated_repo, "data", "forward_analytics.json")
    doc = json.load(open(sc_path))
    # inject non-finite numbers as if a guard had been bypassed
    doc["tracks"][0]["ann_return_pct"] = float("nan")
    doc["tracks"][0]["excess_vs_floor_pct"] = float("inf")
    with open(sc_path, "w") as fh:
        json.dump(doc, fh)  # CPython writes literal NaN/Infinity; the generator reads via stdlib
    md = GEN.generate(root=populated_repo, now_iso="FIXED")
    # the section still renders; the corrupt fields format as the honest sentinel, never 'nan%'
    assert "## 5. Live forward-record analytics" in md
    assert "nan%" not in md.lower()
    assert "inf%" not in md.lower()
