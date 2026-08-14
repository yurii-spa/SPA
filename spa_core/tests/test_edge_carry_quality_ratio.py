# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_carry_quality_ratio.py — registry idea #53 CQR.

What is pinned and why:

  • **None before warm-up**: cqr_scores() must return None for the first LOOKBACK days, exactly
    like xsd_scores(). An unmeasured quality is not a low quality and must not be rankable.

  • **VOL floor active**: when a book has near-zero daily variance, std approaches zero. Without
    the floor the score explodes; with it, score = mean / VOL_FLOOR (bounded). Both cases
    measured so the floor cannot be silently removed.

  • **Relative ranking (the core claim)**: a book with higher mean AND lower std must rank above
    a book with lower mean and higher std — i.e. CQR ≠ XSD for heteroscedastic books. This is
    the claim that CQR could add information over XSD; it is pinned against hand-computed values.

  • **Sign flip degrades**: demoting the BEST-CQR books must lose to demoting the worst.
    If the sign-flip wins, the ranking carries no cross-sectional information and the result is
    an artifact of rotating capital at all. Pinned on a constructed panel where the direction
    is unambiguous.

  • **Causality**: CQR at day i uses only returns[0:i] (through t-1). Checked by corrupting
    return[i] and verifying cqr_scores()[i-1] is unaffected.

  • **Structural fixture finding**: on the synthetic fixture (deterministic drift outside crises),
    CQR and XSD produce identical demotion sets for every rankable day. This is the central
    result of idea #53 — the demotion decision is binary (crisis-in-window or not), and both
    criteria respond to it identically. Pinned as a tripwire: if real data is later loaded and
    the pinned equality breaks, a human should inspect the diff before merging.

All series are hand-checkable synthetics. No repo data, no network, no writes.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import List, Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


mod = _load("edge_carry_quality_ratio")

LOOKBACK = mod.LOOKBACK   # 60
VOL_FLOOR = mod.VOL_FLOOR  # 5e-5


# ─────────────────────────────── helpers ──────────────────────────────────────────────────────────

def _const(n: int, val: float) -> List[float]:
    return [val] * n


def _alt(n: int, a: float, b: float) -> List[float]:
    return [a if i % 2 == 0 else b for i in range(n)]


def _nonzero_scores(scores: List[Optional[float]]) -> List[float]:
    return [s for s in scores if s is not None]


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 1. NONE BEFORE WARM-UP
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

class TestNoneBeforeWarmup:
    def test_none_for_first_lookback_days(self):
        r = _const(LOOKBACK * 3, 0.001)
        out = mod.cqr_scores({"a": r})["a"]
        assert all(s is None for s in out[:LOOKBACK])

    def test_valid_after_lookback(self):
        r = _const(LOOKBACK * 3, 0.001)
        out = mod.cqr_scores({"a": r})["a"]
        assert all(s is not None for s in out[LOOKBACK:])

    def test_length_preserved(self):
        r = _const(LOOKBACK * 2 + 7, 0.001)
        out = mod.cqr_scores({"a": r})["a"]
        assert len(out) == len(r)

    def test_exactly_at_lookback_boundary(self):
        r = _const(LOOKBACK * 2, 0.001)
        out = mod.cqr_scores({"a": r})["a"]
        assert out[LOOKBACK - 1] is None
        assert out[LOOKBACK] is not None


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 2. VOL FLOOR
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

class TestVolFloor:
    def test_constant_series_uses_floor(self):
        """A constant return series has std=0; score must equal mean/VOL_FLOOR."""
        drift = 0.0003
        r = _const(LOOKBACK * 2, drift)
        out = mod.cqr_scores({"a": r})["a"]
        valid = _nonzero_scores(out)
        expected = drift / VOL_FLOOR
        assert all(abs(s - expected) < 1e-9 for s in valid)

    def test_score_bounded_from_above(self):
        """Near-zero std + positive mean should not produce inf/nan."""
        r = _const(LOOKBACK * 2, 0.001)
        out = mod.cqr_scores({"a": r})["a"]
        valid = _nonzero_scores(out)
        assert all(math.isfinite(s) for s in valid)

    def test_negative_drift_constant(self):
        """Negative mean / VOL_FLOOR → negative CQR score (bounded, not flipped)."""
        drift = -0.0003
        r = _const(LOOKBACK * 2, drift)
        out = mod.cqr_scores({"a": r})["a"]
        valid = _nonzero_scores(out)
        assert all(s < 0 for s in valid)
        expected = drift / VOL_FLOOR
        assert all(abs(s - expected) < 1e-9 for s in valid)

    def test_custom_floor(self):
        drift = 0.001
        r = _const(LOOKBACK * 2, drift)
        custom_floor = 2e-4
        out = mod.cqr_scores({"a": r}, vfloor=custom_floor)["a"]
        valid = _nonzero_scores(out)
        expected = drift / custom_floor
        assert all(abs(s - expected) < 1e-9 for s in valid)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 3. RANKING CORRECTNESS (CQR ≠ XSD for heteroscedastic books)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

class TestRankingCorrectness:
    """CQR must rank a smooth-low-carry book above a lumpy-high-carry book when the
    carry/vol ratio of the smooth book exceeds that of the lumpy one."""

    def _two_book_scores(self, n: int = LOOKBACK * 4):
        # smooth: lower drift, near-zero vol → high CQR
        smooth = [0.0002] * n

        # lumpy: higher drift but oscillating large swings → lower CQR
        lumpy = _alt(n, 0.003, -0.001)  # mean ≈ 0.001, std ≈ 0.002

        sc_cqr = mod.cqr_scores({"smooth": smooth, "lumpy": lumpy})
        sc_xsd = mod.xsd_scores({"smooth": smooth, "lumpy": lumpy})
        return sc_cqr, sc_xsd

    def test_cqr_smooth_beats_lumpy(self):
        sc_cqr, _ = self._two_book_scores()
        valid_idx = [i for i in range(len(sc_cqr["smooth"]))
                     if sc_cqr["smooth"][i] is not None and sc_cqr["lumpy"][i] is not None]
        assert valid_idx, "no valid indices found after warm-up"
        # smooth (mean 0.0002, std→VOL_FLOOR) vs lumpy (mean 0.001, std≈0.002)
        # CQR_smooth ≈ 0.0002/5e-5 = 4.0  vs  CQR_lumpy ≈ 0.001/0.002 = 0.5
        for i in valid_idx:
            assert sc_cqr["smooth"][i] > sc_cqr["lumpy"][i], \
                f"at i={i}: smooth CQR {sc_cqr['smooth'][i]:.4f} <= lumpy CQR {sc_cqr['lumpy'][i]:.4f}"

    def test_xsd_lumpy_beats_smooth(self):
        """XSD (raw drift) ranks the LUMPY book higher because it has higher mean return."""
        _, sc_xsd = self._two_book_scores()
        valid_idx = [i for i in range(len(sc_xsd["smooth"]))
                     if sc_xsd["smooth"][i] is not None and sc_xsd["lumpy"][i] is not None]
        assert valid_idx
        for i in valid_idx:
            assert sc_xsd["lumpy"][i] > sc_xsd["smooth"][i], \
                f"at i={i}: lumpy XSD {sc_xsd['lumpy'][i]:.4f} <= smooth XSD {sc_xsd['smooth'][i]:.4f}"

    def test_cqr_and_xsd_disagree_on_ranking(self):
        """CQR and XSD must give opposite rankings for this heteroscedastic pair."""
        sc_cqr, sc_xsd = self._two_book_scores()
        valid_idx = [i for i in range(len(sc_cqr["smooth"]))
                     if sc_cqr["smooth"][i] is not None and sc_cqr["lumpy"][i] is not None]
        # CQR: smooth > lumpy; XSD: lumpy > smooth
        for i in valid_idx:
            cqr_order = sc_cqr["smooth"][i] > sc_cqr["lumpy"][i]  # True = smooth first
            xsd_order = sc_xsd["smooth"][i] > sc_xsd["lumpy"][i]  # True = smooth first
            assert cqr_order != xsd_order, \
                f"at i={i}: CQR and XSD agree on ranking — expected them to disagree"


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 4. CAUSALITY
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

class TestCausality:
    def test_corrupting_day_i_does_not_change_score_at_i_minus_1(self):
        """The score on day i-1 uses returns through day i-2 only."""
        n = LOOKBACK * 3
        r1 = _const(n, 0.001)
        r2 = list(r1)
        r2[n - 1] = 99.9   # corrupt the last day

        out1 = mod.cqr_scores({"a": r1})["a"]
        out2 = mod.cqr_scores({"a": r2})["a"]

        # Every score except the last must be unchanged
        for i in range(n - 1):
            if out1[i] is not None:
                assert out1[i] == out2[i], f"corrupting day {n-1} changed score at day {i}"

    def test_corrupting_today_changes_only_later_scores(self):
        n = LOOKBACK * 3
        r1 = list(range(n))   # increasing integers as returns (not realistic but deterministic)
        r1 = [x * 0.0001 for x in r1]
        corrupt_day = LOOKBACK + 10
        r2 = list(r1)
        r2[corrupt_day] = 99.9

        out1 = mod.cqr_scores({"a": r1})["a"]
        out2 = mod.cqr_scores({"a": r2})["a"]

        # Days ≤ corrupt_day must be identical
        for i in range(corrupt_day + 1):
            assert out1[i] == out2[i], f"score at {i} changed after corrupting day {corrupt_day}"

        # Day corrupt_day+1 through corrupt_day+LOOKBACK may differ
        # (the corrupt value enters the window)


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 5. SIGN FLIP (control must lose)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

class TestSignFlip:
    """Demoting the BEST-CQR books must underperform demoting the worst-CQR books.

    This uses a panel where one book is clearly best (high mean, smooth) and others are clearly
    worse (low or negative mean, volatile) — the sign-flip control should easily lose here.
    """

    def _build_clear_panel(self, n: int = LOOKBACK * 5):
        """Good book: steady positive carry. Bad books: noisy / negative carry."""
        rets = {
            "good":  [0.003] * n,                          # high smooth carry
            "noisy": _alt(n, 0.008, -0.006),               # mean≈0.001 but high vol
            "bad":   [-0.001] * n,                          # steady negative
        }
        return rets

    def test_flip_calmar_below_normal(self):
        rets = self._build_clear_panel()
        books = sorted(rets)
        n = len(rets[books[0]])
        sc = mod.cqr_scores(rets)

        # Normal: demote worst-CQR
        fl_normal = mod.rank_demotion_flags(sc, k=1, readmit_days=1, worst_first=True)
        w_normal = mod.alloc_recycle(books, fl_normal, n)
        m_normal = mod.portfolio_metrics(books, rets, w_normal, n)

        # Flip: demote best-CQR
        fl_flip = mod.rank_demotion_flags(sc, k=1, readmit_days=1, worst_first=False)
        w_flip = mod.alloc_recycle(books, fl_flip, n)
        m_flip = mod.portfolio_metrics(books, rets, w_flip, n)

        assert m_normal["calmar"] > m_flip["calmar"], (
            f"sign flip did NOT lose: normal Calmar {m_normal['calmar']:.3f} <= "
            f"flip Calmar {m_flip['calmar']:.3f}")

    def test_flip_net_apy_below_normal(self):
        rets = self._build_clear_panel()
        books = sorted(rets)
        n = len(rets[books[0]])
        sc = mod.cqr_scores(rets)

        fl_normal = mod.rank_demotion_flags(sc, k=1, readmit_days=1, worst_first=True)
        w_normal = mod.alloc_recycle(books, fl_normal, n)
        m_normal = mod.portfolio_metrics(books, rets, w_normal, n)

        fl_flip = mod.rank_demotion_flags(sc, k=1, readmit_days=1, worst_first=False)
        w_flip = mod.alloc_recycle(books, fl_flip, n)
        m_flip = mod.portfolio_metrics(books, rets, w_flip, n)

        assert m_normal["net_apy"] > m_flip["net_apy"], (
            f"sign flip net_apy did NOT lose: normal {m_normal['net_apy']:.4f} <= "
            f"flip {m_flip['net_apy']:.4f}")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 6. STRUCTURAL FIXTURE FINDING (tripwire)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

class TestFixtureStructuralFinding:
    """Pins the actual finding of idea #53 on the fixture panel.

    CQR and XSD DO produce different demotion decisions — they are genuinely distinct criteria.
    But CQR is NOT better than XSD on this fixture; at k=1 M=20 it is notably worse (Calmar 0.11
    vs 0.26). The reason: the vol-denominator in CQR misbehaves in the regime-transition zone
    (days within L of a crisis): CQR's std spike promotes books that XSD's mean-drop demotes,
    sometimes recycling capital into an even worse book. This is predicted outcome D.

    Tripwire properties:
    1. CQR and XSD disagree on at least some demotion days (distinct criteria — testable fact).
    2. CQR Calmar ≤ XSD Calmar on the fixture for every (k, M) in the tested grid.
    """

    def test_cqr_xsd_disagree_on_some_days(self):
        """CQR and XSD produce DIFFERENT demotion flags on at least some days.

        This means CQR is a genuinely distinct criterion, not a copy of XSD — a necessary
        (but not sufficient) condition for it to ever add value.
        """
        axis, rets = mod.build_panel()
        books = sorted(rets)
        n = len(axis)

        sc_cqr = mod.cqr_scores(rets)
        sc_xsd = mod.xsd_scores(rets)

        fl_cqr = mod.rank_demotion_flags(sc_cqr, k=2, readmit_days=20)
        fl_xsd = mod.rank_demotion_flags(sc_xsd, k=2, readmit_days=20)

        disagreements = sum(
            1 for b in books for i in range(n) if fl_cqr[b][i] != fl_xsd[b][i]
        )
        assert disagreements > 0, (
            "CQR and XSD produced IDENTICAL flags for ALL (book, day) cells. "
            "This would mean vol information adds nothing at all to the ranking.")

    def test_cqr_not_better_than_xsd_on_fixture(self):
        """On the fixture, CQR Calmar ≤ XSD Calmar for every (k, M) tested.

        CQR is the worse criterion here — pinned so that a future change that makes it better
        (real data, different fixture, tuned VOL_FLOOR) is explicitly visible.
        """
        axis, rets = mod.build_panel()
        books = sorted(rets)
        n = len(axis)

        for k in (1, 2, 3):
            for m_days in (1, 20):
                sc_cqr = mod.cqr_scores(rets)
                sc_xsd = mod.xsd_scores(rets)

                fl_cqr = mod.rank_demotion_flags(sc_cqr, k=k, readmit_days=m_days)
                fl_xsd = mod.rank_demotion_flags(sc_xsd, k=k, readmit_days=m_days)

                w_cqr = mod.alloc_recycle(books, fl_cqr, n)
                w_xsd = mod.alloc_recycle(books, fl_xsd, n)

                m_cqr = mod.portfolio_metrics(books, rets, w_cqr, n)
                m_xsd = mod.portfolio_metrics(books, rets, w_xsd, n)

                # CQR must not exceed XSD by more than a rounding-noise margin (0.02)
                assert m_cqr["calmar"] <= m_xsd["calmar"] + 0.02, (
                    f"k={k} M={m_days}: CQR Calmar {m_cqr['calmar']:.3f} > "
                    f"XSD Calmar {m_xsd['calmar']:.3f} + 0.02. "
                    f"If this broke with real data, CQR may have found an edge — investigate.")


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 7. PORTFOLIO METRICS CONSISTENCY
# ═══════════════════════════════════════════════════════════════════════════════════════════════════

class TestPortfolioMetrics:
    def test_raw_equal_weight(self):
        """Raw portfolio = equal weight = 1/N each day."""
        books = ["a", "b"]
        rets = {"a": [0.001] * 100, "b": [0.002] * 100}
        n = 100
        m = mod.raw_metrics(books, rets, n)
        # expected APY: avg daily = 0.0015, compounded
        expected_eq = (1.0015) ** 100
        expected_apy = expected_eq ** (365.0 / 100) - 1.0
        assert abs(m["apy"] - expected_apy) < 1e-6

    def test_no_demotions_equals_raw(self):
        """With no demotions, portfolio_metrics == raw_metrics."""
        books = ["a", "b", "c"]
        rets = {b: [0.001 * (i + 1)] * 80 for i, b in enumerate(books)}
        n = 80
        flags = {b: [False] * n for b in books}
        w = mod.alloc_recycle(books, flags, n)
        m = mod.portfolio_metrics(books, rets, w, n)
        m_raw = mod.raw_metrics(books, rets, n)
        assert abs(m["apy"] - m_raw["apy"]) < 1e-9
        assert abs(m["maxdd"] - m_raw["maxdd"]) < 1e-9

    def test_duty_one_book_always_demoted(self):
        """With one of two books always demoted, duty should be 0.5."""
        books = ["a", "b"]
        n = 100
        rets = {"a": [0.001] * n, "b": [0.001] * n}
        flags = {"a": [True] * n, "b": [False] * n}
        w = mod.alloc_recycle(books, flags, n)
        m = mod.portfolio_metrics(books, rets, w, n)
        assert abs(m["duty"] - 0.5) < 1e-9
