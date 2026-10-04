#!/bin/bash
# scripts/agent_investment_cio.sh — launchd wrapper for com.spa.investment_cio (ADR-554).
#
# Daily, 09:30 local (after the 08:00 cycle): build_sleeves -> previous = ledger tail -> recommend ->
# ledger.append (idempotent per UTC date) -> outcomes.score_due. ADVISORY / PAPER only — the CIO
# package executes nothing and writes only under data/investment_cio/. Exit codes: 0 OK ·
# 2 ledger error / unexpected · 75 ledger lock held by another run (EX_TEMPFAIL).
# Canonical bash wrapper (launchd cannot exec miniconda python directly -> exit 78); log in /tmp.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    investment_cio spa_core.investment_cio.run
