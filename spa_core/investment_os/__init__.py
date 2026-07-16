"""spa_core/investment_os — AI Investment OS product-layer (docs/08_ai_investment_os_architecture.md).

The advisory analyst layer of the product super-studio (AAA task). Each of the designed 16 analysts is
activated as a small module on the shared `harness.ProductAgent` base: read feeds fail-closed →
deterministically structure + evidence-tag (L0-L6) → OPTIONAL LLM reasoning behind a number-gate →
emit a namespaced advisory artifact (`data/investment_os/<agent>.json`) + hash-chained proof.

Hard boundaries (docs/08 §universal-contract · ADR_004):
  • IS_ADVISORY — never moves capital, never touches RiskPolicy/kill-switch/live track/execution.
  • Writes ONLY to data/investment_os/ (never runtime state files).
  • LLM is allowed AROUND the reasoning (advisory), never INSIDE risk/execution/monitoring/kill; any
    LLM number not present in the sourced facts is discarded (fail-closed).
  • stdlib runtime; atomic writes; secrets (LLM key) from env only.
"""
