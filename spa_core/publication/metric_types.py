"""Typed performance vocabulary (ADR-580 C2, PRODUCT-TRUTH-02 / ADR-630).

A public return is one of FIVE kinds and never a bare «APY». The shelf (`build_site_numbers.py`)
keeps its older ``kind`` field (замер/решение/backtest/target/modelled — `bsn.KINDS`) for the pages;
``metric_type`` is the typed name the contract checks. The mapping is one-way and total for returns:
a return without a type, or with a type that contradicts its source, is refused.
"""
from __future__ import annotations

TARGET_RETURN = "TARGET_RETURN"                  # a declared goal / band — never a result
OBSERVED_RETURN = "OBSERVED_RETURN"              # a short observation (below maturity), e.g. 1-day rate
REALIZED_PAPER_RETURN = "REALIZED_PAPER_RETURN"  # a mature paper track (≥ REPORTABLE_AFTER periods)
MODELLED_RETURN = "MODELLED_RETURN"              # derived by a model, not observed
BACKTEST_RETURN = "BACKTEST_RETURN"              # historical simulation

RETURN_TYPES = (TARGET_RETURN, OBSERVED_RETURN, REALIZED_PAPER_RETURN, MODELLED_RETURN, BACKTEST_RETURN)

#: drawdowns carry a BASIS, so a backtest tail can never read as a paper tail
PAPER = "PAPER"
BACKTEST = "BACKTEST"
DRAWDOWN_BASES = (PAPER, BACKTEST)
