"""Adapters for the provider contract (STUDIO-OS-MODELS-01, increment 2).

# LLM_FORBIDDEN

Both adapters take the SAME input — :func:`render_prompt` of the request — and return
:class:`~spa_core.studio_os.model_roles.contract.AdapterOutput`.

* ``claude_cli`` — the existing approved seam (the local Claude Code CLI on the subscription; the same
  ``-p --tools "" --strict-mcp-config`` call that :mod:`spa_core.studio_os.memory.answer` made), with
  ``--output-format json`` so that what the CLI reports about usage can be recorded. The DEADLINE is
  enforced by the existing ``scripts/claude_run_with_timeout.py`` (loaded by explicit path — one copy of
  the ownership rules): ``subprocess.run(timeout=…)`` kills only the direct child, while that helper
  finishes every descendant whose ownership by THIS run is proven and never touches anyone else's
  process (exit 124 — closed, 125 — ownership not closed). The CLI's stdout goes to a private file via
  ``sh -c 'exec …'`` (``exec`` keeps the same pid, so the helper's ownership proof is unchanged).
  Tools are disabled by construction; a request that asks for tools is refused here as well.
* ``fixture`` — a TEST adapter: deterministic canned answers from a JSON fixture (``{"<task_id>":
  "<answer>"}``, or ``{"*": …}``); it can also play timeout/quota/malformed. It is NOT a provider.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from spa_core.studio_os.model_roles.contract import UNKNOWN, AdapterOutput, Request

#: The local Claude Code CLI (subscription). Defined HERE — the transport layer — and imported by
#: ``memory.answer``; the reverse import (adapters ← answer) made a cycle once answer used the contract.
CLAUDE = str(Path.home() / ".local" / "bin" / "claude")
#: The existing deadline/ownership helper — loaded by path, never copied (as ``orchestrator_cycle_lock``).
TIMEOUT_HELPER = Path(__file__).resolve().parents[3] / "scripts" / "claude_run_with_timeout.py"
TIMEOUT_CODES = (124, 125)
DEFAULT_GRACE_S = 10.0

PROMPT = ("You act in the role «{role}». You have NO prior knowledge of this project and NO tools. "
          "Use ONLY the context below. If the context does not establish an answer, say UNKNOWN. "
          "Answer briefly.\n\nTASK ({task_id}): {instruction}\n\nCONTEXT:\n{context}")


def render_prompt(req: Request) -> str:
    return PROMPT.format(role=req.role, task_id=req.task_id, instruction=req.instruction,
                         context=req.context)


def load_timeout_helper(path: Path = TIMEOUT_HELPER):
    """The helper module, or an exception — a missing helper is an ERROR result, never a bare run."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_model_roles_claude_timeout", path)
    if spec is None or spec.loader is None or not Path(path).exists():
        raise FileNotFoundError(f"deadline helper not found: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for attr in ("run", "TIMEOUT_OWNERSHIP_CLOSED", "TIMEOUT_OWNERSHIP_UNRESOLVED"):
        if not hasattr(mod, attr):
            raise AttributeError(f"{path}: no {attr!r}")
    return mod


def helper_runner(*, grace_s: float = DEFAULT_GRACE_S, helper_path: Path = TIMEOUT_HELPER):
    """``runner(cmd, timeout_s, log_path, out_path) -> rc`` through the existing deadline helper."""

    def run(cmd: Sequence[str], timeout_s: float, log_path: Path, out_path: Path,
            cwd: Optional[Path] = None) -> int:
        helper = load_timeout_helper(helper_path)
        # ARB 24.10: the CLI runs from its OWN empty temp directory (as `memory.answer` did with
        # `cwd=tempfile.gettempdir()`), not from the caller's tree — the helper's Popen has no cwd, so
        # the shell changes it right before `exec` (same pid ⇒ ownership proof unchanged). Every path
        # and argument is a POSITIONAL parameter; nothing is interpolated into the shell code.
        # The parent Python's cwd is never touched. A failed `cd` exits 97 (an error, not a run).
        wrapped = ["/bin/sh", "-c", 'cd "$1" || exit 97; out="$2"; shift 2; exec "$@" > "$out"', "sh",
                   str(cwd or out_path.parent), str(out_path), *cmd]
        return int(helper.run(wrapped, timeout_s=timeout_s, grace_s=grace_s, log_path=str(log_path),
                              label="model-roles-claude"))

    return run


def claude_cli(*, binary: str = CLAUDE, model: Optional[str] = None,
               runner: Optional[Callable[..., int]] = None) -> Callable[..., AdapterOutput]:
    """Adapter over the existing Claude CLI seam. ``runner`` is injectable (tests never call a model)."""

    def run(req: Request, *, timeout_s: float, tools: Sequence[str]) -> AdapterOutput:
        if list(tools):
            return AdapterOutput("error", detail=f"tools requested {list(tools)}; this seam runs with none")
        cmd: List[str] = [binary, "-p", render_prompt(req), "--tools", "", "--strict-mcp-config",
                          "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        with tempfile.TemporaryDirectory(prefix="spa_model_roles_") as tmp:
            log_path, out_path = Path(tmp) / "helper.log", Path(tmp) / "stdout.json"
            work = Path(tmp) / "cwd"
            work.mkdir()
            try:
                rc = (runner or helper_runner())(cmd, timeout_s, log_path, out_path, cwd=work)
            except (OSError, AttributeError, ImportError) as exc:
                return AdapterOutput("error", detail=f"deadline helper unusable: {exc}")
            stdout = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
            err = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        # The temp directory (and the helper log in it) is gone now — the evidence travels in `detail`.
        tail = " | ".join(line.strip() for line in err.splitlines()[-12:] if line.strip())[-1500:]
        if rc == TIMEOUT_CODES[1]:
            # ARB 24.10: 125 = the helper could NOT prove that every process of this run is gone.
            # Not a timeout to retry: a second run would start next to possible survivors.
            return AdapterOutput("ownership_unresolved",
                                 detail=f"no answer within {timeout_s:g} s and process ownership NOT closed "
                                        f"(helper rc=125); not retried. helper log: {tail or 'empty'}")
        if rc == TIMEOUT_CODES[0]:
            return AdapterOutput("timeout", detail=f"no answer within {timeout_s:g} s; helper rc=124: "
                                                   f"every process of this run finished. helper log: {tail or 'empty'}")
        if rc != 0:
            low = (err + stdout).lower()
            if "usage limit" in low or "rate limit" in low or "quota" in low:
                return AdapterOutput("quota", detail=(err + stdout).strip()[-300:])
            return AdapterOutput("error", detail=f"rc={rc}: {(err + stdout).strip()[-300:]}")
        try:
            doc = json.loads(stdout)
        except ValueError:
            return AdapterOutput("malformed", detail=f"not JSON: {stdout[:200]!r}")
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
