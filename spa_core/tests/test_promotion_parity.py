"""6mo-M2 #17 — promotion-framework PARITY guard.

SPA has TWO deliberately-distinct promotion frameworks (documented in promotion_engine.py's docstring +
docs/DECISIONS.md; they are NOT duplicates):

  • TournamentEngine (spa_core/tournament/tournament_engine.py) — the standalone RESEARCH-breadth pipeline
    (backtest→paper_30d→live, own strategy_tournament.json, 09:00 UTC agent). PROMOTION_CRITERIA:
    min_sharpe 1.5 / 7 paper days / drawdown ≥ -15% / APY ≥ 3%.
  • PromotionEngine (spa_core/paper_trading/promotion_engine.py) — the CANONICAL daily-cycle SHADOW-PANEL
    promote/demote/kill: PROMOTE_SHARPE 0.8 / DEMOTE_SHARPE 0.0 / KILL_DRAWDOWN -10% / MIN_DAYS 14.

This test does NOT force the two to be identical — they serve different purposes on different data. It
PINS the documented RELATIONSHIPS so a future edit can't silently make them contradict (e.g. lowering the
research-'live' Sharpe bar below the shadow-promote bar, which would make reaching 'live' EASIER than a
shadow-promote — a promotion-theater regression). Deterministic; pure imports; no network.
"""
from spa_core.tournament import tournament_engine as te
from spa_core.paper_trading import promotion_engine as pe


def test_research_live_is_stricter_than_shadow_promote():
    """Reaching the research pipeline's 'live' phase must be AT LEAST as strict as a shadow-panel
    promote — the tournament Sharpe bar (1.5) >= the PromotionEngine promote bar (0.8). If a future edit
    inverts this, 'live' would be easier to reach than a shadow-promote (theater)."""
    assert te.PROMOTION_CRITERIA["min_sharpe"] >= pe.PROMOTE_SHARPE


def test_both_have_positive_sharpe_bars_and_min_days():
    assert te.PROMOTION_CRITERIA["min_sharpe"] > 0.0
    assert pe.PROMOTE_SHARPE > 0.0
    assert te.PROMOTION_CRITERIA["min_days_paper"] >= 1
    assert pe.MIN_DAYS >= 1


def test_drawdown_bars_are_negative_fractions_and_ordered():
    """Both drawdown limits are negative fractions. The shadow-panel KILL (-10%) is TIGHTER than the
    research-promotion drawdown ceiling (-15%) — a strategy between -10% and -15% is killed on the live
    shadow panel yet still research-promotable, which is coherent (different data/purpose), NOT a bug.
    Pin the sign + ordering so neither silently flips to a positive/absurd value."""
    td = te.PROMOTION_CRITERIA["max_drawdown"]
    kd = pe.KILL_DRAWDOWN
    assert -1.0 < td < 0.0
    assert -1.0 < kd < 0.0
    assert kd >= td            # kill (-0.10) is not deeper than the research ceiling (-0.15)


def test_they_are_distinct_not_accidentally_merged():
    """The two frameworks are intentionally DIFFERENT — assert they didn't get collapsed into identical
    constants (which would signal a mistaken 'merge' losing the research-vs-live-track distinction)."""
    assert te.PROMOTION_CRITERIA["min_sharpe"] != pe.PROMOTE_SHARPE


def test_promotion_engine_documents_the_distinction():
    """The 'make one reference the other' requirement: PromotionEngine's docstring names the tournament
    engine, and TournamentEngine references PromotionEngine back."""
    assert "tournament_engine" in (pe.__doc__ or "")
    te_src = __import__("inspect").getsource(te)
    assert "promotion_engine" in te_src and "PromotionEngine" in te_src


def test_both_advisory_never_real_capital():
    """Neither framework moves real capital — the tournament is advisory (IS_ADVISORY) and PromotionEngine
    drives only the shadow panel. Pin the tournament advisory flag."""
    assert getattr(te, "IS_ADVISORY", True) is True
