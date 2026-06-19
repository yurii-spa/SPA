"""
gross_of — Gap-layer analyzers for performance-fee base inflation.

Each module measures a specific cost layer that erodes depositor yield
but may be included in the gross yield on which the performance fee is
charged, creating a fee-on-cost / fee-base inflation gap.
"""

from spa_core.analytics.gross_of.sequencer_tip import (  # noqa: F401
    SequencerTipGapAnalyzer,
)
