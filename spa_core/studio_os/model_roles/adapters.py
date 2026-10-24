"""Adapters for the provider contract (STUDIO-OS-MODELS-01, increment 2).

# LLM_FORBIDDEN

Both adapters take the SAME input — :func:`render_prompt` of the request — and return
:class:`~spa_core.studio_os.model_roles.contract.AdapterOutput`.

* ``claude_cli`` — wraps the existing approved seam of :mod:`spa_core.studio_os.memory.answer`:
  the local Claude Code CLI on the subscription, ``-p`` with ``--tools ""`` and
  ``--strict-mcp-config`` from a temp cwd, now with ``--output-format json`` so that what the CLI
  reports about usage can be recorded. Tools are disabled by construction; a request that asks for
  tools is refused here as well (defence in depth — the role has none).
* ``fixture`` — a TEST adapter: deterministic canned answers from a JSON fixture (``{"<task_id>":
  "<answer>"}``, or ``{"*": …}``); it can also play timeout/quota/malformed. It is NOT a provider.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from spa_core.studio_os.memory.answer import CLAUDE
from spa_core.studio_os.model_roles.contract import UNKNOWN, AdapterOutput, Request

PROMPT = ("You act in the role «{role}». You have NO prior knowledge of this project and NO tools. "
          "Use ONLY the context below. If the context does not establish an answer, say UNKNOWN. "
          "Answer briefly.\n\nTASK ({task_id}): {instruction}\n\nCONTEXT:\n{context}")


def render_prompt(req: Request) -> str:
    return PROMPT.format(role=req.role, task_id=req.task_id, instruction=req.instruction,
                         context=req.context)


def claude_cli(*, binary: str = CLAUDE, model: Optional[str] = None,
               runner: Callable[..., Any] = subprocess.run) -> Callable[..., AdapterOutput]:
    """Adapter over the existing Claude CLI seam. ``runner`` is injectable (tests never call a model)."""

    def run(req: Request, *, timeout_s: float, tools: Sequence[str]) -> AdapterOutput:
        if list(tools):
            return AdapterOutput("error", detail=f"tools requested {list(tools)}; this seam runs with none")
        cmd: List[str] = [binary, "-p", render_prompt(req), "--tools", "", "--strict-mcp-config",
                          "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        try:
            p = runner(cmd, capture_output=True, text=True, timeout=timeout_s,
                       cwd=tempfile.gettempdir())
        except subprocess.TimeoutExpired:
            return AdapterOutput("timeout", detail=f"no answer within {timeout_s:g} s")
        except OSError as exc:
            return AdapterOutput("error", detail=f"CLI not runnable: {exc}")
        err = (p.stderr or "") + (p.stdout or "")
        if p.returncode != 0:
            low = err.lower()
            if "usage limit" in low or "rate limit" in low or "quota" in low:
                return AdapterOutput("quota", detail=err.strip()[:300])
            return AdapterOutput("error", detail=f"rc={p.returncode}: {err.strip()[:300]}")
        try:
            doc = json.loads(p.stdout)
        except ValueError:
            return AdapterOutput("malformed", detail=f"not JSON: {(p.stdout or '')[:200]!r}")
        if not isinstance(doc, dict) or doc.get("is_error"):
            return AdapterOutput("error", detail=f"CLI reported an error: {str(doc)[:300]}")
        text = doc.get("result")
        if not isinstance(text, str):
            return AdapterOutput("malformed", detail="no `result` text in the CLI answer")
        u = doc.get("usage") if isinstance(doc.get("usage"), dict) else {}
        models = doc.get("modelUsage") if isinstance(doc.get("modelUsage"), dict) else {}
        usage: Dict[str, Any] = {k: u.get(k) for k in ("input_tokens", "output_tokens",
                                                       "cache_creation_input_tokens",
                                                       "cache_read_input_tokens")}
        usage["cost_reported_usd"] = doc.get("total_cost_usd")
        return AdapterOutput("ok", text=text,
                             model=(",".join(sorted(models)) if models else (model or UNKNOWN)),
                             usage=usage, detail=f"duration_ms={doc.get('duration_ms', UNKNOWN)}")

    return run


def fixture(answers: Mapping[str, Any]) -> Callable[..., AdapterOutput]:
    """TEST adapter. Value per task id: answer text, or ``{"status": "timeout"|"quota"|…}``."""

    def run(req: Request, *, timeout_s: float, tools: Sequence[str]) -> AdapterOutput:
        if list(tools):
            return AdapterOutput("error", detail=f"tools requested {list(tools)}; the contract has none")
        val = answers.get(req.task_id, answers.get("*"))
        if val is None:
            return AdapterOutput("error", detail=f"fixture has no answer for {req.task_id!r}")
        if isinstance(val, dict):
            return AdapterOutput(str(val.get("status", "error")), text=str(val.get("text", "")),
                                 detail=str(val.get("detail", "fixture-played outcome")))
        # The fixture SEES the same prompt the real adapter sends — the answer may quote it.
        prompt = render_prompt(req)
        text = str(val).replace("{context_sha256}", req.context_sha256).replace(
            "{prompt_chars}", str(len(prompt)))
        return AdapterOutput("ok", text=text, model="fixture (not a model)",
                             usage={}, detail="fixture answer")

    return run


def fixture_from_file(path: Path) -> Callable[..., AdapterOutput]:
    return fixture(json.loads(Path(path).read_text(encoding="utf-8")))
