#!/bin/bash
# scripts/agent_capital_shadow.sh — launchd wrapper for com.spa.capital_shadow (RM-LIVE-01, ADR-556).
#
# Daily, 09:45 local (after the 09:30 investment_cio recommendation): CURRENT_STATE intents (never
# manufactures an action) -> validate -> simulate -> shadow execution (hypothetical) -> reconcile ->
# pilot-readiness. SHADOW mode only — real capital $0, automated live execution PROHIBITED. Writes
# only under data/capital_shadow*. Exit codes: 0 OK · 2 ledger error / unexpected ·
# 75 ledger lock held by another run (EX_TEMPFAIL).
# Canonical bash wrapper (launchd cannot exec miniconda python directly -> exit 78); log in /tmp.
# Production profile (ADR-556): read-only public RPC quorum (allow-listed methods only — no key, no send) and a
# daily TEST_SCENARIO canary that exercises intent → simulation → shadow → forward reconciliation. The current-state
# pass never manufactures an action: when the CIO abstains or the book says HOLD, it records NO_ACTION.
export MODULE_ARGS="--live-rpc --scenario daily_canary"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    capital_shadow spa_core.capital_shadow.run
