# Owner Decisions — Pending

## OWNER DECISION NEEDED — RiskPolicy module drift (surfaced 2026-07-08, autonomous session)

**Context:** rules_watchdog went CRITICAL. Root cause = the optimized_yield book (owner-approved) is
compliant under policy.py (the authoritative v1.0 gate) but REJECTED by policy_enforcer.py (a stale
secondary check).

**FIXED autonomously (unambiguous):** T3-total cap was silently unenforced (optimizer collapsed T3->T2).
optimized_yield poured 30% into T3 (susde 20% + extra_finance 10%) vs the 15% cap. Added
allocator._enforce_t3_total_cap (canonical tier_map). optimized_yield now T1 45% / T2 20% / T3 15%,
projected APY 6.57% (the HONEST safe ceiling; the 8.44% was inflated by the breach). Commit b8ee41bb.

**PENDING YOUR SIGN-OFF (risk-layer, not touched):** policy_enforcer.py has two constraints policy.py
does NOT: (1) per_protocol_max_pct 25% vs policy 40%; (2) t1_min_pct 55% floor vs policy has none.
These are stale risk_adjusted-era constants. Two ways:
  (A) Reconcile enforcer -> policy.py (single-source): morpho 40% + T1 45% become compliant, watchdog
      goes green. This is aligning the secondary check to the approved gate.
  (B) Treat the 55% T1-floor / 25% per-protocol as a REAL safety intent policy.py lost — then the
      optimized_yield book (T1 45%, morpho 40%) is genuinely too concentrated and the OPTIMIZER should
      be constrained to T1>=55% (which would lower yield further).
Recommendation: (A) — policy.py is the authoritative gate the flip was validated against. But this is
your call because it decides whether "45% in the safest tier" is acceptable. A parity test
(test_policy_module_parity.py) now guards this (xfail until reconciled).
