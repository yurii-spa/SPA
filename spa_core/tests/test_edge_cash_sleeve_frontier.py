# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_cash_sleeve_frontier.py — registry idea #55 CSF.

Hand-built series only; nothing here reads data/aggressive_lab/ (gitignored, regenerated nightly,
absent in CI). Each pin is a positive control for one load-bearing piece of the #55 entry:

  • **A sleeve is not leverage.** scaled() must refuse keep outside [0,1]. A "cash fraction" of
    −20% is 120% deployed — a leveraged book wearing the word "cash", and the one way this entry
    could quietly stop being about cash at all.

  • **c=0 is the untouched rule.** The frontier's zero-cash row must be byte-identical to the plain
    #40 XSD allocation, or the frontier is measuring the sleeve AND a changed rule at once.

  • **The sleeve scales exposure and shrinks drawdown proportionally.** Pinned as the monotone it
    must be: more cash ⇒ less deployed, less APY, smaller |maxDD|. If any of those inverts, the
    "cash is a scale dial" reading of the entry is wrong.

  • **Undeployed capital earns the stated rate, and only when it is undeployed.** Pinned against a
    hand-computed number on a one-book panel, because the entry's headline arithmetic — 31.7% ×
    3.38% = 1.07 pp/yr forgone — is exactly this accounting.

  • **The static-matched twin really has no timing.** Zero turnover and a constant weight per book;
    it is the control that refutes the accidental sleeve, so it must be the thing it claims to be.

  • **A frozen book is indistinguishable from cash at 0%/yr, and NOT from cash that pays.** The
    first half is #54's control re-pinned here; the second half is the whole point of #55.

stdlib + pytest only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "edge_cash_sleeve_frontier.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="edge_cash_sleeve_frontier.py absent")


def _load():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("edge_cash_sleeve_frontier_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


csf = _load()
ets = csf.ets
ecr = csf.ecr
xsd = csf.xsd


def panel_of(rets: Dict[str, List[float]]):
    """Axis labels are deliberately NOT dates — nothing under test parses them, and a literal date
    would grow the frozen-date class (.claude/rules/deployment.md) for pure decoration."""
    n = len(next(iter(rets.values())))
    return ets.SynthPanel([f"d{i:05d}" for i in range(n)], rets)


def live_panel(n: int = 400):
    return panel_of({
        "a": [3e-4 + (i % 5) * 2e-5 for i in range(n)],
        "b": [1e-4 - (i % 7) * 1e-5 for i in range(n)],
        "c": [2e-4 + (i % 3) * 3e-5 for i in range(n)],
        "d": [-1e-4 + (i % 11) * 1e-5 for i in range(n)],
    })


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 1. A SLEEVE IS NOT LEVERAGE
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("keep", [-0.2, 1.2, 2.0])
def test_scaled_refuses_leverage_and_shorts(keep):
    with pytest.raises(ValueError):
        csf.scaled({"a": [1.0, 1.0]}, keep)


def test_scaled_is_a_plain_proportional_scale():
    out = csf.scaled({"a": [0.5, 0.25], "b": [0.5, 0.75]}, 0.8)
    assert out["a"] == pytest.approx([0.4, 0.2])
    assert out["b"] == pytest.approx([0.4, 0.6])


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 2. c = 0 IS THE UNTOUCHED RULE
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_zero_cash_row_is_the_plain_xsd_allocation():
    p = live_panel()
    rows = csf.frontier(p, k=1, m_days=20, cash_annual=0.0, grid=(0.0,))
    flags = xsd.rank_demotion_flags(ets.cal_scores(p.rets), 1, 20)
    plain = ecr.portfolio_metrics(p, ecr.alloc_recycle(p.books, flags, p.n))
    for key in ("apy", "maxdd", "calmar", "deployed", "turnover_yr", "net_apy_after_cost"):
        assert rows[0.0][key] == pytest.approx(plain[key], abs=1e-12), (
            f"{key}: the zero-cash row is not the untouched rule — the frontier is measuring two "
            "changes at once"
        )


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 3. THE SLEEVE IS A SCALE DIAL
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_more_cash_means_less_deployed_less_return_and_a_smaller_drawdown():
    p = live_panel()
    grid = (0.0, 0.2, 0.4, 0.6)
    rows = csf.frontier(p, k=1, m_days=20, cash_annual=0.0, grid=grid)
    depl = [rows[c]["deployed"] for c in grid]
    apy = [rows[c]["apy"] for c in grid]
    dd = [abs(rows[c]["maxdd"]) for c in grid]
    assert depl == sorted(depl, reverse=True), "deployed capital must fall as the sleeve grows"
    assert apy == sorted(apy, reverse=True), "return must fall as the sleeve grows"
    assert dd == sorted(dd, reverse=True), "drawdown must shrink as the sleeve grows"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 4. THE INTEREST ARITHMETIC — the entry's headline number is this accounting
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_undeployed_capital_earns_the_stated_rate_and_deployed_capital_does_not():
    """One book, flat at 0, half the capital in cash at 3.65%/yr = exactly 1 bp/day on that half."""
    n = 365
    p = panel_of({"only": [0.0] * n})
    half = {"only": [0.5] * n}
    m = ecr.portfolio_metrics(p, half, cash_annual=0.0365)
    # 0.5 of the book × 1 bp/day, compounded over 365 days
    expected = (1.0 + 0.5 * 0.0365 / 365.0) ** 365 - 1.0
    assert m["apy"] == pytest.approx(expected, rel=1e-9)

    full = {"only": [1.0] * n}
    m_full = ecr.portfolio_metrics(p, full, cash_annual=0.0365)
    assert m_full["apy"] == pytest.approx(0.0, abs=1e-12), (
        "fully deployed capital collected cash interest — the sleeve would be paid twice and the "
        "1.07 pp/yr the entry quotes would be fiction"
    )


def test_the_forgone_interest_headline_is_reproducible():
    """31.7% of the book at the 3.38% floor is 1.07 pp/yr — the number quoted in the entry."""
    assert 0.317 * csf.RWA_FLOOR * 100 == pytest.approx(1.07, abs=0.005)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 5. THE STATIC-MATCHED CONTROL REALLY HAS NO TIMING
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_static_matched_twin_is_constant_and_costs_no_turnover():
    p = live_panel()
    flags = xsd.rank_demotion_flags(ets.cal_scores(p.rets), 1, 20)
    dyn = ecr.alloc_recycle(p.books, flags, p.n)
    twin = ecr.alloc_static_matched(dyn)
    for b in p.books:
        assert len(set(twin[b])) == 1, f"{b}: the static twin moved — it is not a static control"
        assert twin[b][0] == pytest.approx(sum(dyn[b]) / p.n), (
            f"{b}: the twin does not carry the dynamic rule's AVERAGE weight, so it is not matched"
        )
    assert ecr.portfolio_metrics(p, twin)["turnover_yr"] == pytest.approx(0.0, abs=1e-12)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 6. A FROZEN BOOK IS CASH AT 0%/YR — AND ONLY AT 0%/YR
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_a_frozen_book_is_unpaid_cash_and_a_paid_sleeve_beats_it():
    n = 400
    base = live_panel(n)
    with_frozen = panel_of(dict(base.rets, frozen=[0.0] * n))

    flags = xsd.rank_demotion_flags(ets.cal_scores(with_frozen.rets), 1, 20)
    w = ecr.alloc_recycle(with_frozen.books, flags, with_frozen.n)
    accident = ecr.portfolio_metrics(with_frozen, w)
    share = sum(w["frozen"]) / with_frozen.n
    assert share > 0.05, "precondition: the frozen book must actually hold weight to be a sleeve"

    # the same average sleeve, deliberately held in the live books' panel and PAID
    paid = csf.frontier(base, k=1, m_days=20, cash_annual=csf.RWA_FLOOR, grid=(share,))[share]
    unpaid = csf.frontier(base, k=1, m_days=20, cash_annual=0.0, grid=(share,))[share]
    assert paid["apy"] > unpaid["apy"], (
        "paying interest on the sleeve did not raise return — the accounting under the entry's "
        "central claim is broken"
    )
    assert paid["apy"] > accident["apy"] - 1e-9 or paid["net_apy_after_cost"] > \
        accident["net_apy_after_cost"] - 1e-9, (
        "a deliberate, interest-earning sleeve failed to beat the unpaid accident on either gross "
        "or net return — on this fixture that would contradict the entry"
    )
