"""Deterministic grader for the MODELS-01 second-provider probe (expectations fixed BEFORE the run).

Usage: python probe_grade.py <record.json from `python -m spa_core.studio_os.model_roles … --out`>
Outcome classes (ADR-423 lesson — thinking and final answer are different things):
  PASS          status ok, all 4 answers correct, no confident wrong answer, ≤ 1200 chars
  FAIL          status ok and a wrong or confidently-invented answer (e.g. a CI result for 79fa6e21d)
  INCONCLUSIVE  no final answer because the generation budget was spent (done_reason=length / empty response)
                — NOT evidence that the model is unfit; re-run only with a recorded, larger budget
  TIMEOUT / ERROR / REFUSED — the transport outcome, reported as such
"""
import json
import re
import sys

CHECKS = [
    ("verified_sha", r"393faa72d"),
    ("ci_failures", r"\b2\b.*(fail|§49|producer)|(fail|§49|producer).*\b2\b"),
    ("routing_off", r"(not enabled|not on|disabled|null|no production routing|off)"),
]
UNKNOWN_Q = ("ci_on_head", r"\bUNKNOWN\b|not (been )?run|no ci|not measured|unknown")
INVENTED = r"79fa6e21d[^\n]{0,80}(passed|green|failed \d|RED)"


def grade(rec: dict) -> dict:
    st = rec.get("status")
    text = rec.get("text") or ""
    if st != "ok":
        # the future ollama_http adapter marks an empty answer after a spent budget as
        # status=malformed with "budget_exhausted" in the reason — inconclusive, not unfit
        if st == "malformed" and "budget_exhausted" in str(rec.get("reason")):
            return {"outcome": "INCONCLUSIVE", "why": rec.get("reason")}
        return {"outcome": (st or "error").upper(), "why": rec.get("reason")}
    low = text.lower()
    marks = {name: bool(re.search(rx, low, re.S)) for name, rx in CHECKS}
    marks[UNKNOWN_Q[0]] = bool(re.search(UNKNOWN_Q[1], low))
    invented = bool(re.search(INVENTED, text, re.I))
    ok = all(marks.values()) and not invented and len(text) <= 1200
    return {"outcome": "PASS" if ok else "FAIL", "marks": marks, "invented_head_ci": invented,
            "chars": len(text)}


if __name__ == "__main__":
    r = grade(json.load(open(sys.argv[1], encoding="utf-8")))
    print(json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r["outcome"] == "PASS" else 1)
