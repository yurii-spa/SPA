"""Answer stage of the benchmark — a FRESH model session that sees only the context package.

The session has no chat history, no tools and no MCP servers (`claude -p --tools "" --strict-mcp-config`,
run from a temp cwd): whatever it knows about the project, it learned from the package. Offline /
on-demand (it calls a model); results go to data/memory/benchmark_answers_<ts>.json.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import assembler as asm
from . import benchmark as bm
from . import index as ix

CLAUDE = str(Path.home() / ".local" / "bin" / "claude")
PROMPT = ("You are a fresh assistant with NO prior knowledge of this project. Answer the owner's question "
          "using ONLY the context package below. Cite the refs you used in square brackets. If the package does "
          "not contain the answer, reply starting with «UNKNOWN» and say what evidence is missing. Answer in the "
          "language of the question, at most 8 sentences.\n\nQUESTION: {q}\n\n{ctx}")


def ask(question: str, *, budget_chars: int = 12000, model: Optional[str] = None, timeout: int = 180) -> Dict:
    t0 = time.perf_counter()
    pkg = asm.assemble(question, budget_chars=budget_chars)
    ctx = asm.render_markdown(pkg)
    t1 = time.perf_counter()
    cmd = [CLAUDE, "-p", PROMPT.format(q=question, ctx=ctx), "--tools", "", "--strict-mcp-config"]
    if model:
        cmd += ["--model", model]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir())
    return {"question": question, "answer": (p.stdout or "").strip(), "rc": p.returncode,
            "context_chars": len(ctx), "assemble_ms": round(1000 * (t1 - t0)),
            "answer_s": round(time.perf_counter() - t1, 1),
            "sufficiency": pkg["evidence_sufficiency"]["verdict"]}


def grade(q: Dict, ans: str) -> Dict:
    lead = re.sub(r"^[\s*_#>«\"']+", "", ans)        # markdown emphasis before the verdict is not an answer
    if q.get("expect_unknown"):
        ok = bool(re.match(r"(UNKNOWN|НЕИЗВЕСТНО|Нет данных)", lead, re.I))
        return {"correct": ok, "missing": [] if ok else ["UNKNOWN"]}
    missing = [f for f in q.get("facts", []) if not re.search(f, ans, re.I)]
    unknownish = lead.upper().startswith("UNKNOWN")   # a bare refusal; «НЕИЗВЕСТНО: причина…» + facts can be right (Q7)
    return {"correct": not missing and not unknownish, "missing": missing + (["answered UNKNOWN"] if unknownish else [])}


def run(*, which: str = "q", limit: Optional[int] = None, out_dir: Optional[Path] = None, model: Optional[str] = None) -> Dict:
    qs = bm.load()
    rows: List[Dict] = []
    for q in qs[:limit]:
        for phr in (q[which][:1] if which == "q" else q[which][:1]):
            r = ask(phr, model=model)
            r.update(grade(q, r["answer"]), id=q["id"])
            rows.append(r)
    n = len(rows)
    res = {"which": which, "n": n, "correct": sum(r["correct"] for r in rows),
           "avg_context_chars": round(sum(r["context_chars"] for r in rows) / n) if n else None,
           "rows": rows, "index": ix.manifest()}
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / f"benchmark_answers_{int(time.time())}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res
