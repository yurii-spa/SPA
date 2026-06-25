"""
spa_core/strategy_lab/rwa_backstop/ — RWA Liquidation-NAV engine + Collateral Safety Board.

CHEAP, READ-ONLY de-risk of research thesis #2 "SPA-RRB (RWA Repo Backstop)".

The thesis: the edge of an RWA repo/lending backstop is NOT yield — it is being the transparent
*liquidation underwriter* for tokenized-RWA collateral. "The asset is the executable liquidation
path; lend against Liquidation NAV, not marketing NAV." Before any capital / relationships /
whitelisting, the cheap question is:

    Is tokenized-RWA collateral genuinely NOT cash-like on an EXECUTABLE exit?
    Can we MEASURE the gap between marketing NAV ($1.00) and real Liquidation NAV from
    data we can get read-only?

This package answers that with deterministic, stdlib-only, LLM-forbidden, fail-CLOSED code:
  - collateral_registry.py — the universe of tokenized-RWA collateral candidates + documented
    redemption rules / transfer restrictions as config constants.
  - liquidation_nav.py     — measure the executable exit per asset/size from DEX depth + the
    documented redemption haircut; LiqNAV = min(on-chain swap after slippage, redemption after
    delay/fee haircut) − operational haircuts. Fail-CLOSED to LiqNAV=0/unknown on missing data.
  - safety_board.py        — the "RWA Collateral Safety Board": per-asset verdict
    (LIQUID / THIN / REDEMPTION_ONLY / UNSAFE) + the marketing-vs-liq gap %; writes
    data/rwa_safety_board.json atomically.

RESEARCH ONLY. Nothing here trades, lends, or touches the go-live track.
"""
# LLM_FORBIDDEN
