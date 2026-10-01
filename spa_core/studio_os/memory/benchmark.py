"""Fresh-session memory benchmark (ADR-527) — retrieval part is deterministic and runs in CI.

For every question and EVERY phrasing (Russian, Russian paraphrase, English) the retriever must put
at least one expected source in the top-k. Questions with `expect_unknown` must end up flagged as
insufficient evidence by the assembler. The LLM answer stage (`answer.py`) is separate and offline.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import index as ix
from . import sources as src

BENCH = "architecture/memory_benchmark.json"


def load(root: Optional[Path] = None) -> List[Dict]:
    root = root or src.roots()["spa"]
    return json.loads((Path(root) / BENCH).read_text(encoding="utf-8"))["questions"]


def default_retriever(q: str, k: int) -> List[str]:
    """Top-k sources; a retrieved SEMANTIC fact contributes the canonical sources it cites (provenance)."""
    out: List[str] = []
    for r in ix.search(q, k=k):
        out.append(f"{r['repo']}:{r['path']}")
        out += r.get("evidence") or []
    return out


def run_retrieval(retriever: Optional[Callable[[str, int], List[str]]] = None, *, k: int = 5,
                  questions: Optional[List[Dict]] = None) -> Dict:
    """retriever(query, k) -> list of 'repo:path'. Defaults to this package's index."""
    retriever = retriever or default_retriever
    qs = questions or load()
    rows, hits, total, lat = [], 0, 0, []
    for q in qs:
        if not q.get("expect_any"):
            continue
        per = []
        for phr in q["q"]:
            t0 = time.perf_counter()
            got = retriever(phr, k)
            lat.append(time.perf_counter() - t0)
            ok = any(e in got for e in q["expect_any"])
            per.append({"q": phr, "hit": ok, "top": got[:k]})
            hits += ok
            total += 1
        rows.append({"id": q["id"], "phrasings": per})
    lat.sort()
    return {"k": k, "hit_rate": round(hits / total, 3) if total else None, "hits": hits, "total": total,
            "latency_p50_ms": round(1000 * lat[len(lat) // 2], 1) if lat else None,
            "latency_max_ms": round(1000 * lat[-1], 1) if lat else None, "rows": rows}
