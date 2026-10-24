"""Answer stage of the benchmark — a FRESH model session that sees only the context package.

The session has no chat history, no tools and no MCP servers (`claude -p --tools "" --strict-mcp-config`,
run from a temp cwd): whatever it knows about the project, it learned from the package. Offline /
on-demand (it calls a model); results go to data/memory/benchmark_answers_<ts>.json.

Since STUDIO-OS-MODELS-01 increment 3 (ARB 2026-10-24) the call goes through the provider contract
(:mod:`spa_core.studio_os.model_roles`): role ``architect``, provider named EXPLICITLY
(``claude_subscription_cli`` — the same subscription CLI as before; repository assignments stay null),
deadline enforced by ``scripts/claude_run_with_timeout.py``. A refusal, quota or error is never an
answer: ``answer`` is empty, ``rc`` non-zero and ``status``/``reason`` say why; no other provider is
tried. ``usage`` carries only what the transport reported (absent ⇒ UNKNOWN).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.studio_os.model_roles import adapters as _adapters
from spa_core.studio_os.model_roles import contract as _contract

from . import assembler as asm
from . import benchmark as bm
from . import index as ix

#: Kept for importers; the transport constant now lives with the adapter (no reverse import).
CLAUDE = _adapters.CLAUDE
#: The provider this caller uses — named explicitly; the repository assigns none to any role.
PROVIDER = "claude_subscription_cli"
ROLE = "architect"
INSTRUCTION = ("Answer the owner's question using ONLY the context package below. Cite the refs you used in "
               "square brackets. If the package does not contain the answer, reply starting with «UNKNOWN» and "
               "say what evidence is missing. Answer in the language of the question, at most 8 sentences."
               "\n\nQUESTION: {q}")
#: Return codes for non-transport outcomes (the transport's own code is not available through the contract).
RC = {"ok": 0, "error": 1, "quota": 3, "malformed": 4, "timeout": 124, "ownership_unresolved": 125,
      "refused": 2}


def ask(question: str, *, budget_chars: int = 12000, model: Optional[str] = None, timeout: int = 180,
        provider: str = PROVIDER, adapters: Optional[Dict] = None, config: Optional[Dict] = None) -> Dict:
    """Same result keys as before (+ ``status``, ``provider``, ``model``, ``attempts``, ``usage``, ``reason``).

    ``adapters``/``config`` are injectable for tests; by default the real subscription adapter is used.
    """
    t0 = time.perf_counter()
    pkg = asm.assemble(question, budget_chars=budget_chars)
    ctx = asm.render_markdown(pkg)
    t1 = time.perf_counter()
    req = _contract.Request(ROLE, "memory-answer:" + hashlib.sha256(question.encode("utf-8")).hexdigest()[:12],
                            INSTRUCTION.format(q=question), ctx, "memory.assembler", deadline_s=timeout)
    res = _contract.execute(req, config=config or _contract.load_config(), provider_id=provider,
                            adapters=adapters or {"claude_cli": _adapters.claude_cli(model=model)})
    return {"question": question, "answer": res.text.strip() if res.status == "ok" else "",
            "rc": RC.get(res.status, 1), "context_chars": len(ctx),
            "assemble_ms": round(1000 * (t1 - t0)),
            "answer_s": round(res.elapsed_s if res.elapsed_s is not None else time.perf_counter() - t1, 1),
            "sufficiency": pkg["evidence_sufficiency"]["verdict"],
            "status": res.status, "provider": res.provider_id, "model": res.model,
            "attempts": res.attempts, "usage": res.usage, "reason": res.reason}


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
