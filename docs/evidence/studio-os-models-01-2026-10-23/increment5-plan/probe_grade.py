"""SUPERSEDED (ARB 2026-10-25): this regex grader gave FALSE PASS («200 failed», «routing is ON; backup is off»,
«green on 79fa6e21d. UNKNOWN is not the answer»). The grader now lives in code — a structured four-field answer
with exact value/type checks: ``spa_core.studio_os.model_roles.probe.grade`` (tests: test_model_roles_probe.py),
and ``probe launch`` writes the grade into ``probe_record.json`` itself.

Kept (not deleted) as the history of the defect. It imports nothing from ``spa_core`` on purpose: ``docs/`` is not
synced to production, and a hard import from here would rot silently (``test_unsynced_hard_imports``).
"""
import sys

if __name__ == "__main__":
    sys.stderr.write("SUPERSEDED — use spa_core.studio_os.model_roles.probe.grade "
                     "(the grade is already inside probe_record.json)\n")
    sys.exit(2)
