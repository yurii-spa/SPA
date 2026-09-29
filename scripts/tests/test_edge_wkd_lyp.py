"""#115 WKD / #116 LYP — research scripts, pinned on synthetic inputs (no runtime data/ needed).

Each test is a positive control: it plants the property and checks the instrument sees it, or
plants a violation and checks the instrument refuses / does not leak.
"""
# FROZEN-DATE-OK: calendar weekdays ARE the subject of #115 — literal dates fix which day is which
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"_t_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


W = _load("edge_weekday_loss_gate")
L = _load("edge_lst_yield_persistence")


def _days(start: str, n: int):
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def test_gate_puts_off_days_on_the_floor_and_charges_each_edge():
    dates = _days("2024-01-01", 14)            # 2024-01-01 is a Monday
    rets = [0.01] * 14
    g, legs = W.gated(dates, rets, [4], rt_bp=20.0)   # Friday off
    fridays = [i for i, d in enumerate(dates) if W.weekday(d) == 4]
    assert len(fridays) == 2 and legs == 4             # out + back, twice
    for i in fridays:
        assert g[i] == pytest.approx(W.RWA_DAILY - 0.001)
    assert g[0] == pytest.approx(0.01)


def test_worst_weekday_is_found_when_planted():
    dates = _days("2024-01-01", 70)
    rets = [(-0.02 if W.weekday(d) == 2 else 0.001) for d in dates]
    assert W.worst_days_by_mean(dates, rets, 1) == [2]


def test_within_week_permutation_never_leaks_its_relabelling():
    dates = _days("2024-01-01", 400)
    rets = [(-0.01 if W.weekday(d) == 4 else 0.002) for d in dates]
    out = W.wf_permutation(dates, rets, n_perm=20)
    assert W._LABELS == {}                              # restored after the null
    assert W.weekday("2024-01-05") == 4                 # real calendar again
    # a planted, persistent Friday loss must sit in the right tail of the within-week null
    assert out["p"] < 0.1


def test_lyp_collapses_a_duplicate_source(tmp_path: Path):
    days = _days("2025-01-01", 260)
    a = {d: 0.03 for d in days}
    ser = {"aaa": a, "bbb": dict(a), "ccc": {d: 0.025 for d in days}}
    (tmp_path / "rates_desk").mkdir()
    (tmp_path / "rates_desk" / "restaking_deep.json").write_text(json.dumps({"series": ser}))
    axis, ys, dups = L.load(tmp_path)
    assert dups == [("aaa", "bbb")]
    assert sorted(ys) == ["aaa", "ccc"]


def test_lyp_rotation_is_causal():
    """A yield jump on day t may move the choice from day t+1 on, never on day t itself."""
    axis = _days("2025-01-01", 40)
    ys = {"a": [0.03] * 40, "b": [0.02] * 40}
    ys["b"][20] = 5.0                                   # one absurd print on day 20
    lo, hi = axis[0], "9999"
    base = L.rotate(axis, {"a": ys["a"], "b": ys["b"][:20] + [0.02] * 20}, 1, 0.0, 0.0, lo, hi)
    jump = L.rotate(axis, ys, 1, 0.0, 0.0, lo, hi)
    # same holdings through day 20 ⇒ the only difference is b's print is NOT earned (a was held)
    assert base["switches"] == 0
    assert jump["switches"] == 2                        # into b on day 21, back to a on day 22
    assert jump["ann_bp"] < base["ann_bp"]              # it chased the print a day late and paid nothing for it
