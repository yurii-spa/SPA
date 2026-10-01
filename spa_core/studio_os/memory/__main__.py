"""python -m spa_core.studio_os.memory {build|search|assemble|passport|why|lineage|bench|answer-bench|coverage}"""
from __future__ import annotations

import argparse
import json
import sys

from . import assembler, benchmark, index, lineage, passports


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="spa_core.studio_os.memory")
    ap.add_argument("cmd", choices=("build", "search", "assemble", "passport", "why", "lineage", "bench",
                                    "answer-bench", "coverage"))
    ap.add_argument("arg", nargs="?", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--budget", type=int, default=12000)
    ap.add_argument("--live", action="store_true", help="measure launchd for agent status")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        out = index.build()
    elif a.cmd == "search":
        out = index.search(a.arg, k=a.k)
    elif a.cmd == "assemble":
        pkg = assembler.assemble(a.arg, budget_chars=a.budget, measure_host=a.live)
        if not a.json:
            print(assembler.render_markdown(pkg))
            return 0
        out = pkg
    elif a.cmd == "passport":
        out = passports.passport(a.arg, measure_host=a.live)
    elif a.cmd == "why":
        print(passports.answer_why(a.arg, measure_host=a.live))
        return 0
    elif a.cmd == "lineage":
        l = lineage.lineage(a.arg)
        if not a.json:
            print(lineage.render(l))
            return 0
        out = l
    elif a.cmd == "bench":
        qs = benchmark.load()
        out = {"own": benchmark.run_retrieval(k=a.k or 5),
               "heldout": benchmark.run_retrieval(k=a.k or 5, questions=[dict(q, q=q["heldout"]) for q in qs])}
        out = {k: {x: v[x] for x in ("hit_rate", "hits", "total", "latency_p50_ms")} for k, v in out.items()}
    elif a.cmd == "answer-bench":
        from . import answer
        out = answer.run(which=a.arg or "q")
        out = {k: v for k, v in out.items() if k != "rows"} | {"rows": [
            {x: r[x] for x in ("id", "correct", "missing", "context_chars", "answer_s", "sufficiency")} for r in out["rows"]]}
    else:
        out = passports.coverage()
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
