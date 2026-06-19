"""
Configuration for SequencerTipGapAnalyzer.

L2 sequencers charge a priority tip on top of L1 data cost.  This config
enumerates which chains have a centralised sequencer (and thus a sequencer
tip) versus L1 / decentralised-validator chains where no sequencer tip exists.
"""

CHAINS_WITH_SEQUENCER = frozenset([
    "arbitrum",
    "optimism",
    "base",
    "scroll",
    "zksync",
])

CHAINS_WITHOUT_SEQUENCER = frozenset([
    "ethereum",
])

ANNUAL_TIP_BPS_ESTIMATE = {
    "arbitrum": 3,
    "base": 2,
    "optimism": 2,
    "scroll": 1,
    "zksync": 1,
}

TX_PER_YEAR_TYPICAL = 365 * 2
