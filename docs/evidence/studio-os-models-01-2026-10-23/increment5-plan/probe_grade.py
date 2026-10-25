"""SUPERSEDED (ARB 2026-10-25): this regex grader gave FALSE PASS («200 failed», «routing is ON; backup is off»,
«green on 79fa6e21d. UNKNOWN is not the answer»). The grader now lives in code with a structured four-field answer
and exact value/type checks: ``spa_core.studio_os.model_roles.probe.grade`` (tests: test_model_roles_probe.py).
Kept (not deleted) as the history of the defect; it now only delegates.

Usage: python probe_grade.py <probe_record.json or contract Result json>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from spa_core.studio_os.model_roles.probe import grade  # noqa: E402

if __name__ == "__main__":
    rec = json.load(open(sys.argv[1], encoding="utf-8"))
    r = grade(rec.get("result", rec))
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r["outcome"] == "PASS" else 1)
