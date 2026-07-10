"""test_track_snapshot.py — build-time static snapshot (FIX-1/2: one honest source, no hardcoded numbers)."""
import json
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gen_track_snapshot", _ROOT / "scripts" / "generate_track_snapshot.py")
gen = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(gen)


def _write(tmp, name, obj):
    p = tmp / name; p.write_text(json.dumps(obj)); return p


def test_snapshot_has_all_key_fields_from_one_source(tmp_path):
    golive = _write(tmp_path, "golive.json", {"passed": 27, "total": 29, "evidenced_anchor": "2026-06-22",
                                              "target_date": "2026-07-21", "min_track_days": 30})
    equity = _write(tmp_path, "equity.json", {"bars": [
        {"date": "2026-06-22", "equity": 100000.0, "evidenced": True, "apy_today": 3.5},
        {"date": "2026-06-23", "equity": 100100.0, "evidenced": True, "apy_today": 3.6},
    ]})
    pts = _write(tmp_path, "pts.json", {"current_equity": 100255.73, "apy_today_pct": 3.6701})
    snap = gen.build_snapshot(golive_path=golive, equity_path=equity, pts_path=pts)
    # every key number present
    for k in ("as_of", "generated_at", "real_track_days", "gates_passed", "gates_total",
              "end_equity", "nav_usd", "paper_apy_pct", "max_drawdown_pct"):
        assert k in snap, f"missing {k}"
    # nav comes straight from paper_trading_status (one source, not re-derived).
    assert snap["nav_usd"] == 100255.73
    # paper_apy_pct is the STABLE evidenced-track COMPOUND-ANNUALIZED return from the anchor
    # bar (SPA-3 / generate_track_snapshot 7fd71ad9) — deliberately NOT the volatile single-day
    # apy_today_pct. For this synthetic 2-bar curve (+0.1% over 2 evidenced days) the formula
    # annualizes high (~20%); on the real ~30-day track it lands near the honest few-percent band.
    expected_apy = round(((100100.0 / 100000.0) ** (365.0 / 2) - 1.0) * 100.0, 4)
    assert snap["paper_apy_pct"] == expected_apy
    assert snap["paper_apy_pct"] != 3.6701       # explicitly NOT the volatile apy_today_pct
    assert snap["real_track_days"] == 2           # evidenced bars only
    assert snap["gates_passed"] == 27 and snap["gates_total"] == 29
    assert snap["as_of"] == "2026-06-23"          # freshness = last evidenced bar date


def test_missing_values_are_honest_none_not_hardcoded(tmp_path):
    # empty/absent sources → numbers are None (site renders 'data unavailable'), NEVER a stale literal
    golive = _write(tmp_path, "g.json", {})
    equity = _write(tmp_path, "e.json", {"bars": []})
    pts = _write(tmp_path, "p.json", {})
    snap = gen.build_snapshot(golive_path=golive, equity_path=equity, pts_path=pts)
    assert snap["paper_apy_pct"] is None          # no invented APY
    assert snap["max_drawdown_pct"] is None        # <2 bars → None, not 0-faked
    assert snap["real_track_days"] == 0


def test_generated_snapshot_on_disk_is_valid():
    """The committed snapshot the site imports must carry the new fields."""
    disk = json.loads((_ROOT / "landing" / "src" / "data" / "track_snapshot.json").read_text())
    for k in ("as_of", "real_track_days", "gates_passed", "gates_total", "paper_apy_pct", "nav_usd"):
        assert k in disk, f"committed snapshot missing {k}"
