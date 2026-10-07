"""spa_core.publication — the ONE place that answers «what does the public product consist of and when
is it published» (PRODUCT-TRUTH-02, ADR-630).

Not a store of numbers: every number stays in its two canonical sources (`track_snapshot.json` = the
measurement, `constitution.json` = the decisions; `.claude/rules/site-numbers.md`). This package only
holds the RULES every reader shares — the public-profile ↔ internal-book mapping (`product_map`), the
weekly publication cadence (`cadence`) and the typed-metric vocabulary (`metric_types`). LLM_FORBIDDEN,
stdlib only.
"""
