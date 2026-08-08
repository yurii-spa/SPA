"""Tests for the return-BLIND demotion criteria of registry ideas #44 (RCD) and #45 (XVD).

The whole point of both ideas is a property, not a number: RCD's score cannot see returns at all
and XVD's cannot see their sign. A verdict built on that property is worth exactly as much as the
property is pinned, so every claim the registry entry makes about blindness, causality and
fail-CLOSED behaviour is a test here — in BOTH directions, so a test that would pass on a broken
module is not counted as evidence.

No literal dates: every fixture is a synthetic return array, and the two tests that need the real
panel skip when its files are absent (they are nightly artefacts, gitignored, and absent in CI).
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


rd = _load("edge_redundancy_demotion")
xsd = _load("edge_cross_sectional_demotion")

L = 10  # short lookback keeps the fixtures readable; the module's default is 60


def _wave(n: int, period: int, amp: float = 0.01, phase: float = 0.0):
    return [amp * math.sin(2 * math.pi * (i + phase) / period) for i in range(n)]


def _panel(n: int = 60):
    """Three books: a and b share a cycle (redundant pair), c runs on a different one."""
    return {
        "a": _wave(n, 7),
        "b": [0.5 * x + 1e-4 for x in _wave(n, 7)],   # a's twin, rescaled and shifted up
        "c": _wave(n, 11, amp=0.02),
    }


# ───────────────────────────── #44: the score really is return-blind ─────────────────────────────
def test_redundancy_score_is_invariant_to_positive_affine_transform():
    """THE property the whole idea rests on: scale a book's returns and shift them, and its
    redundancy score does not move. This is what makes RCD a control on "does return information
    pay" rather than one more return rule wearing a different name."""
    base = _panel()
    loud = dict(base)
    loud["c"] = [3.0 * x + 0.02 for x in base["c"]]     # 3× the size and +2%/day of pure profit
    s0 = rd.redundancy_scores(base, lookback=L)
    s1 = rd.redundancy_scores(loud, lookback=L)
    for b in s0:
        for i in range(len(s0[b])):
            if s0[b][i] is None or s1[b][i] is None:
                assert s0[b][i] is s1[b][i], f"{b}@{i}: rankability itself changed"
                continue
            assert s0[b][i] == pytest.approx(s1[b][i], abs=1e-12), f"{b}@{i} moved"


def test_redundancy_score_does_move_when_the_correlation_structure_moves():
    """The positive control for the test above: an invariance test passes trivially on a score
    that is constant. Break the shared cycle and the scores MUST move."""
    base = _panel()
    broken = dict(base)
    broken["b"] = _wave(len(base["b"]), 5, phase=2.0)    # no longer a's twin
    s0 = rd.redundancy_scores(base, lookback=L)
    s1 = rd.redundancy_scores(broken, lookback=L)
    moved = sum(1 for b in s0 for i in range(len(s0[b]))
                if s0[b][i] is not None and s1[b][i] is not None
                and abs(s0[b][i] - s1[b][i]) > 1e-9)
    assert moved > 0, "redundancy score ignored a change in the correlation structure"


def test_redundancy_ranks_the_duplicated_book_lowest():
    """Does the criterion do what its name says? On a panel where two books are near-duplicates,
    the bottom of the ranking (= the demoted end) must hold one of the pair, never the odd one out."""
    sc = rd.redundancy_scores(_panel(), lookback=L)
    checked = 0
    for i in range(len(sc["a"])):
        vals = {b: sc[b][i] for b in sc if sc[b][i] is not None}
        if len(vals) < 3:
            continue
        checked += 1
        worst = min(vals, key=lambda b: vals[b])
        assert worst in ("a", "b"), f"day {i}: the least redundant book {worst} was demoted"
    assert checked > 5, "fixture produced too few rankable days to prove anything"


# ───────────────────────────── #45: half-blind, and blind in the stated half ─────────────────────
def test_volatility_score_is_invariant_to_sign_flip_but_not_to_scale():
    rets = {"a": _wave(40, 7), "b": _wave(40, 11, amp=0.03), "c": _wave(40, 5, amp=0.005)}
    flipped = dict(rets, a=[-x for x in rets["a"]])
    scaled = dict(rets, a=[2.0 * x for x in rets["a"]])
    s0, s1, s2 = (rd.volatility_scores(r, lookback=L) for r in (rets, flipped, scaled))
    for i in range(len(s0["a"])):
        if s0["a"][i] is None:
            continue
        assert s0["a"][i] == pytest.approx(s1["a"][i], abs=1e-12), "sign flip moved the score"
        assert abs(s0["a"][i] - s2["a"][i]) > 1e-9, "doubling the book did NOT move the score"


def test_volatility_score_is_none_during_warmup_not_zero():
    """`cfpt.trailing_vol` reports 0.0 before the window fills, which as a SCORE reads as "the
    calmest book on the panel" and would permanently protect whatever is warming up. The mask is
    the fix, and this is the test that would have caught its absence."""
    sc = rd.volatility_scores({"a": _wave(30, 7), "b": _wave(30, 5)}, lookback=L)
    assert all(sc["a"][i] is None for i in range(L))
    assert all(sc["a"][i] is not None for i in range(L, 30))


# ───────────────────────────── causality and fail-CLOSED ─────────────────────────────
@pytest.mark.parametrize("fn", ["redundancy_scores", "volatility_scores"])
def test_scores_are_strictly_causal(fn):
    """Rewrite the FUTURE of every book and no score up to that point may move. Both directions:
    the past is then rewritten too, and the scores must move."""
    n, cut = 40, 25
    base = _panel(n)
    future = {b: list(v) for b, v in base.items()}
    for b in future:
        for i in range(cut, n):
            future[b][i] = 0.5                     # an absurd future
    s0, s1 = getattr(rd, fn)(base, lookback=L), getattr(rd, fn)(future, lookback=L)
    for b in s0:
        for i in range(cut + 1):                   # score at i uses [i-L, i-1] only
            assert s0[b][i] == s1[b][i] or (s0[b][i] is not None and s1[b][i] is not None
                                            and s0[b][i] == pytest.approx(s1[b][i], abs=1e-12)), \
                f"{fn} at {b}@{i} saw the future"
    past = {b: list(v) for b, v in base.items()}
    for b in past:
        for i in range(cut):
            past[b][i] = 0.5
    s2 = getattr(rd, fn)(past, lookback=L)
    assert any(s0[b][cut] != s2[b][cut] for b in s0), f"{fn} ignored a rewritten PAST"


def test_flat_book_is_unrankable_and_therefore_never_demoted():
    """A book with no variance has no correlation with anything. Scoring it 0.0 would drop it into
    the middle of the cross-section on a fabricated number; the module returns None, and an
    unrankable book can never enter the bottom-k."""
    rets = dict(_panel(40), flat=[0.0] * 40)
    sc = rd.redundancy_scores(rets, lookback=L)
    assert all(v is None for v in sc["flat"]), "a flat book was given a redundancy score"
    flags = xsd.rank_demotion_flags(sc, k=1, readmit_days=1)
    assert not any(flags["flat"]), "an unrankable book was demoted"


def test_rolling_corr_matches_a_naive_two_pass_computation():
    """The incremental sums are an optimisation; this pins them against the obvious implementation
    so a future speed-up cannot quietly change the numbers in the registry."""
    x, y = _wave(50, 7), _wave(50, 11, amp=0.02)
    got = rd.rolling_corr(x, y, L)
    for i in range(L, len(x)):
        wx, wy = x[i - L:i], y[i - L:i]
        mx, my = sum(wx) / L, sum(wy) / L
        cov = sum((a - mx) * (b - my) for a, b in zip(wx, wy)) / L
        vx = sum((a - mx) ** 2 for a in wx) / L
        vy = sum((b - my) ** 2 for b in wy) / L
        assert got[i] == pytest.approx(cov / math.sqrt(vx * vy), abs=1e-9)


def test_rolling_corr_refuses_a_degenerate_lookback_and_mismatched_series():
    with pytest.raises(ValueError):
        rd.rolling_corr([0.1, 0.2], [0.1, 0.2], 1)
    with pytest.raises(ValueError):
        rd.rolling_corr([0.1, 0.2, 0.3], [0.1, 0.2], 3)


def test_redundancy_refuses_a_panel_too_small_for_a_peer_estimate():
    with pytest.raises(ValueError):
        rd.redundancy_scores({"a": _wave(30, 7), "b": _wave(30, 5)}, lookback=L, min_peers=2)


# ───────────────────────────── the duty claim the registry entry makes ─────────────────────────
@pytest.mark.parametrize("kind", ["redundancy", "volatility"])
def test_duty_at_m1_is_k_over_n_of_the_rankable_days_for_every_criterion(kind):
    """The registry entry claims the M=1 rung is an EXACT duty match obtained with no search.
    That is a property of the machinery, and it is asserted rather than asserted-about."""
    rets = _panel(60)
    rets["d"] = _wave(60, 13, amp=0.015)
    rets["e"] = _wave(60, 17, amp=0.004)
    sc = (rd.redundancy_scores(rets, lookback=L) if kind == "redundancy"
          else rd.volatility_scores(rets, lookback=L))
    n_books, n_days = len(rets), len(rets["a"])
    for k in (1, 2):
        flags = xsd.rank_demotion_flags(sc, k, readmit_days=1)
        demoted = sum(1 for b in flags for f in flags[b] if f)
        rankable_days = sum(1 for i in range(n_days)
                            if sum(1 for b in sc if sc[b][i] is not None) > k)
        assert demoted == k * rankable_days, f"k={k}: duty is not k/N of the rankable days"
        assert xsd.duty(flags) == pytest.approx(k * rankable_days / (n_books * n_days))


def test_random_null_is_reproducible_and_starts_after_the_same_warmup():
    a = rd.random_scores(["x", "y", "z"], 30, seed=7, warmup=L)
    b = rd.random_scores(["x", "y", "z"], 30, seed=7, warmup=L)
    c = rd.random_scores(["x", "y", "z"], 30, seed=8, warmup=L)
    assert a == b, "the null is not reproducible — its p-values would not be either"
    assert a != c
    assert all(a["x"][i] is None for i in range(L))


# ───────────────────────────── scope invariants of the registry ─────────────────────────────
def test_module_is_advisory_outside_riskpolicy_and_imports_no_execution_code():
    assert rd.IS_ADVISORY is True and rd.OUTSIDE_RISKPOLICY is True
    src = (SCRIPTS / "edge_redundancy_demotion.py").read_text(encoding="utf-8")
    assert "spa_core.execution" not in src and "from spa_core import execution" not in src
    for forbidden in ("atomic_save", "open(", ".write_text(", "json.dump"):
        assert forbidden not in src, f"a research script must not persist state ({forbidden})"


@pytest.mark.skipif(not (ROOT / "data" / "aggressive_lab").exists(),
                    reason="nightly panel artefacts are gitignored and absent in CI")
def test_real_panel_ladder_runs_and_leaves_no_files_behind():
    before = sorted(p.name for p in (ROOT / "data").glob("*")) if (ROOT / "data").exists() else []
    panel = rd.dgo.Panel()
    for kind, _, _ in rd.CRITERIA:
        sc = rd.panel_scores(panel, kind)
        assert set(sc) == set(panel.books)
        assert all(sc[b][0] is None for b in panel.books), "day 0 was ranked on an empty window"
    after = sorted(p.name for p in (ROOT / "data").glob("*")) if (ROOT / "data").exists() else []
    assert before == after, "a read-only research pass wrote into data/"
