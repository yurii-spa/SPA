"""
spa_core/strategy_lab/rates_desk/ — the "SPA Rates Desk" thesis de-risk (RESEARCH ONLY).

NOT a live trading book. This is a pure-compute, paper, reversible de-risk per §8 of the
research: build a v1 risk-adjusted tokenized-yield SCORER and answer two deterministic
yes/no questions over our existing 2024-2026 data.

THESIS under test: the edge is a risk-adjusted fair-value model for tokenized yield that
(a) harvests genuinely-mispriced carry and (b) REFUSES yield that is just tail-risk
compensation (the ezETH / over-levered-USDe pattern). The single thing to test before any
capital: does our risk engine separate "real excess spread" from "tail-comp you'll pay back"?

Modules:
  risk_score.py — deterministic per-underlying tail-risk score (0..1) from data we already have
                  (LRT/LST depeg distance, ratio drawdown, downside-drift vol, funding-flip prob).
  fair_value.py — fair implied yield = baseline - tail_risk_haircut; classify CARRY vs REFUSE.
  retro.py      — the two retrospective tests over the real cached 2024-2026 history.
  config.py     — all thresholds (no magic numbers in logic; change → new ADR).

Conventions inherited from the Strategy Lab: stdlib only, deterministic, LLM-forbidden,
fail-CLOSED (missing/invalid data raises or scores as MAX tail-risk, never a silent pass).
"""
# LLM_FORBIDDEN
