"""
#168 DCPS — Dynamic-Target Cross-book Peril Suspension — pinned tests on synthetic panels.

Positive controls: plant the property, check the instrument sees it; plant the violation,
check it does not. No real panel is read (the live `data/aggressive_lab/` is never touched).
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: literal ISO dates are synthetic axis labels placed OUTSIDE every crisis window, compared to window bounds only
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"_t_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"_t_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


d = _load("edge_dcps_real_panel")


def test_flags_are_advisory():
    assert d.IS_ADVISORY is True and d.OUTSIDE_RISKPOLICY is True


def test_trailing_cum_is_strictly_before_day():
    r = [0.0, 0.0, -1.0, 5.0]
    # day 3 with W=1 sees ONLY day 2 (−1), never its own +5
    assert d.trailing_cum(r, 3, 1) == -1.0
    assert d.trailing_cum(r, 0, 1) is None  # no history ⇒ third outcome, not zero


def test_signal_does_not_see_today():
    """Mutate TODAY's return of every book: the stress flag and target of today must not move."""
    rets = {"a": [0.01, -0.02, -0.03, 0.04], "b": [0.01, -0.01, -0.02, 0.05],
            "c": [0.01, 0.01, 0.01, 0.01]}
    st1, tg1 = d.stress_and_target(rets, list(rets), 1, 2, 4)
    mutated = {b: v[:3] + [-0.9] for b, v in rets.items()}
    st2, tg2 = d.stress_and_target(mutated, list(mutated), 1, 2, 4)
    assert st1[3] == st2[3] and tg1[3] == tg2[3]


def test_dcps_target_is_the_worst_trailing_loser():
    rets = {"a": [0.0, -0.05, 0.0], "b": [0.0, -0.01, 0.0], "c": [0.0, 0.01, 0.0]}
    st, tg = d.stress_and_target(rets, list(rets), 1, 2, 3)
    assert st == [False, False, True] and tg[2] == "a"


def test_breadth_below_k_never_fires():
    rets = {"a": [0.0, -0.05, 0.0], "b": [0.0, 0.01, 0.0], "c": [0.0, 0.01, 0.0]}
    st, tg = d.stress_and_target(rets, list(rets), 1, 2, 3)
    assert not any(st) and tg == [None, None, None]


def test_cost_charged_per_state_change_and_target_switch_is_two():
    books = ["a", "b"]
    rets = {"a": [0.0] * 4, "b": [0.0] * 4}
    _, ch = d.run_portfolio(rets, books, [None, "a", "b", None], 1.0, "cash")
    assert ch == 1 + 2 + 1  # on · switch (off+on) · off
    ser, _ = d.run_portfolio(rets, books, [None, "a", "a", None], 1.0, "cash")
    toll = d.TOLL * 0.5
    assert ser == pytest.approx([0.0, -toll, 0.0, -toll])


def test_redistribute_preserves_gross_and_cash_reduces_it():
    books = ["a", "b"]
    rets = {"a": [0.10], "b": [0.10]}
    red, _ = d.run_portfolio(rets, books, [None], 1.0, "redistribute")
    assert red[0] == pytest.approx(0.10)
    # with a suspension the toll is charged once; cash leg earns 0 on the cut half
    cash, _ = d.run_portfolio(rets, books, ["a"], 1.0, "cash")
    assert cash[0] == pytest.approx(0.05 - d.TOLL * 0.5)
    red2, _ = d.run_portfolio(rets, books, ["a"], 1.0, "redistribute")
    assert red2[0] == pytest.approx(0.10 - d.TOLL * 0.5)


def test_absent_window_is_unmeasured_not_zero():
    axis = ["2030-01-01", "2030-01-02", "2030-01-03"]
    win = d.window_dd([0.0, -0.1, 0.0], axis)
    assert all(v is None for v in win.values())


def test_missing_panel_is_unmeasured_exit_2(tmp_path, capsys):
    assert d.main(["--panel-dir", str(tmp_path)]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err
