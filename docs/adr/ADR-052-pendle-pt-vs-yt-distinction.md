# ADR-052: Pendle PT vs YT Risk Classification Distinction

**Status:** ACCEPTED  
**Date:** 2026-06-21  

## Context
ADR-021 classified Pendle as T3-SPEC (advisory-only) based on the speculative nature of Yield Tokens (YT). 
External deep research confirmed (2026-06-21) that PT ≠ YT from a risk perspective.

## Decision
**Principal Tokens (PT):** Fixed-rate zero-coupon bonds. At maturity, PT redeems 1:1 for the underlying asset.
- Risk: smart contract + maturity timing, NOT yield speculation
- ADR-021 restriction does NOT apply to PT
- Classification: **T2** (with $50M TVL floor, maturity awareness)

**Yield Tokens (YT):** Speculative variable yield strip. Can go to zero before maturity.
- ADR-021 restriction APPLIES to YT
- Classification: **T3-SPEC** (advisory-only, no capital allocation)

## Adapters (already built)
- `pendle_pt_susde_adapter.py` → PT-sUSDe, T2, ~10% fallback APY
- `pendle_pt_usdc_adapter.py` → PT-USDC, T2, ~8% fallback APY
- Both include $50M TVL floor + maturity kill switch

## Consequences
- S40 (Pendle PT Fixed Rate, ~5.6% APY) is T2-eligible for advisory inclusion
- S7 (Pendle YT+PT Aggressive) remains T3-SPEC advisory-only per ADR-021
