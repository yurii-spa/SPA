"""spa_core.scheduler — 3-loop scheduler + adapter watchdog (MP-311).

Three control loops at different cadences:

* FAST  — every paper-trading cycle (deterministic, NO LLM)
* SLOW  — daily (LLM-advisory, degrades to cached insights when LLM unavailable)
* STRATEGIC — weekly / Monday (LLM-advisory, skips when LLM unavailable)

Adapter self-healing:

* ``adapter_watchdog`` — detects unhealthy adapters and fires a restart trigger
  (writes log + sets ``adapter_restarted`` flag; no actual subprocess exec in
  the sandbox; rate-limited to 3 restarts per hour).
"""
