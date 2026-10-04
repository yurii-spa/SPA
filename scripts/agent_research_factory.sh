#!/bin/bash
# scripts/agent_research_factory.sh — launchd wrapper for com.spa.research_factory (ADR-560, RM-EXPAND-01).
#
# Daily, 09:05 local (before the 09:30 investment_cio recommendation and the 09:45 capital_shadow
# run): projects existing artifacts (DeFi discovery, RWA safety board, the canonical funding
# median, Sky/sUSDS, trading_research) into the research-candidate registry, runs the
# deterministic lifecycle/admission/eligibility gates, records forward observations, and writes
# the hash-chained ledger + disposable read models under data/research_factory*. RESEARCH / PAPER
# only — real capital $0, nothing here moves money, signs, broadcasts or orders; CIO_ELIGIBLE
# means only that Oracle MAY consider a candidate in paper/advisory allocation (ADR-560).
# Exit codes: 0 OK · 2 ledger error / unexpected · 75 ledger lock held by another run (EX_TEMPFAIL).
# Canonical bash wrapper (launchd cannot exec miniconda python directly -> exit 78); log in /tmp.
# --live-rpc: realised-return consistency (binding #5) reads an independent on-chain series
# (ERC-4626 share price / exchange-rate delta) through the existing allow-listed keyless RPC
# client (capital_shadow.rpc, eth_call only, 2-of-N quorum) — no new network client is added here.
export MODULE_ARGS="--live-rpc"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    research_factory spa_core.research_factory.run
