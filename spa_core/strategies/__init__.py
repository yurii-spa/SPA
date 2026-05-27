"""
SPA Strategies package.

Contains the strategy registry and all named strategies:
  - strategy_registry.py  : central registry for all strategy metadata
  - s1_conservative_lending.py : T1 lending only, ~4-6% APY
  - s2_lp_stable.py            : LP stablecoin pairs (Curve/Uniswap v3), ~8-12% APY
  - s3_yield_loop.py           : borrow-loop on Aave, ~15-25% APY (T3, high risk)
"""
