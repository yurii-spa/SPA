"""spa_core.audit — Decision Audit Trail (MP-310).

Provides a correlation-id–linked chain of events for each paper-trading cycle:
  snapshot_id → allocation_proposal → risk_verdict → trade_executed/trade_blocked

Usage::

    from spa_core.audit.audit_trail import begin_cycle, record_event

    corr_id = begin_cycle("2026-06-11")
    ev = record_event(corr_id, "cycle_start", {"capital_usd": 100_000})
"""
