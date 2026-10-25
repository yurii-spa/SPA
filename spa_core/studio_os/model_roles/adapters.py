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


# ── ollama_http — local Ollama over HTTP (STUDIO-OS-MODELS-01, probe preparation, ARB 2026-10-25) ──────────

#: Hosts an Ollama endpoint may name. Anything else (a LAN address, a cloud URL) is refused: the probe is
#: local by decision, and there is no fallback to any other endpoint.
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
#: Metrics Ollama reports on a finished generate call — kept verbatim in `transport` (never re-derived).
OLLAMA_METRICS = ("done", "done_reason", "total_duration", "load_duration", "prompt_eval_count",
                  "prompt_eval_duration", "eval_count", "eval_duration")


def check_loopback(endpoint: str) -> Optional[str]:
    """``None`` — the endpoint is an explicit loopback http URL; otherwise the refusal reason."""
    from urllib.parse import urlparse
    if not endpoint:
        return "no endpoint given — the Ollama endpoint must be named explicitly"
    u = urlparse(endpoint)
    if u.scheme != "http" or (u.hostname or "") not in LOOPBACK_HOSTS or not u.port:
        return "endpoint must be http://<loopback>:<port> — no remote or default endpoint is used"
    return None


def ollama_http(*, endpoint: str, model: str, num_ctx: int = 8192, num_predict: int = 3072,
                temperature: float = 0.0, think: bool = True, keep_alive: str = "0s",
                http_post: Optional[Callable[..., Dict[str, Any]]] = None) -> Callable[..., AdapterOutput]:
    """Adapter for ONE explicit local Ollama endpoint. ``http_post(url, body, timeout_s)`` is injectable.

    * no ``tools`` field is ever sent — the model can only produce text;
    * the final answer is ``response``; ``thinking`` is NEVER promoted to the answer;
    * an empty ``response`` after ``done_reason=length`` is ``malformed`` with reason ``budget_exhausted`` —
      the budget was spent, which says nothing about the model's fitness (ADR-423 lesson);
    * ``eval_count`` is Ollama's TOTAL generated-token count (thinking and answer together); separate token
      counts for the two parts are not reported by the transport and are not invented — only their
      character lengths are recorded;
    * a timeout is ``ownership_unresolved``: the HTTP client cannot prove the server stopped generating, so
      the contract does not retry it.
    """
    refusal = check_loopback(endpoint)
    post = http_post or _urllib_post_json

    def run(req: Request, *, timeout_s: float, tools: Sequence[str]) -> AdapterOutput:
        if refusal:
            return AdapterOutput("error", detail=refusal)
        if list(tools):
            return AdapterOutput("error", detail=f"tools requested {list(tools)}; ollama_http sends none")
        body = {"model": model, "prompt": render_prompt(req), "stream": False, "think": bool(think),
                "keep_alive": keep_alive,
                "options": {"num_ctx": int(num_ctx), "num_predict": int(num_predict),
                            "temperature": float(temperature)}}
        try:
            doc = post(endpoint.rstrip("/") + "/api/generate", body, timeout_s)
        except TimeoutError:
            return AdapterOutput("ownership_unresolved",
                                 detail=f"no answer within {timeout_s:g} s; the HTTP client cannot confirm the "
                                        f"server stopped generating — not retried")
        except Exception as exc:  # noqa: BLE001 — transport failure is an error result, never a crash
            return AdapterOutput("error", detail=f"ollama transport: {type(exc).__name__}: {str(exc)[:200]}")
        if not isinstance(doc, dict):
            return AdapterOutput("malformed", detail="ollama answer is not a JSON object")
        if doc.get("error"):
            return AdapterOutput("error", detail=f"ollama error: {str(doc.get('error'))[:200]}")
        response = doc.get("response") if isinstance(doc.get("response"), str) else ""
        thinking = doc.get("thinking") if isinstance(doc.get("thinking"), str) else ""
        transport = {k: doc.get(k) for k in OLLAMA_METRICS if k in doc}
        transport.update({"response_chars": len(response), "thinking_chars": len(thinking),
                          "eval_count_counts": "thinking + response together (not split by the transport)",
                          "endpoint": endpoint, "think": bool(think), "num_predict": int(num_predict),
                          "num_ctx": int(num_ctx)})
        usage = {"input_tokens": doc.get("prompt_eval_count"), "output_tokens": doc.get("eval_count")}
        reported_model = doc.get("model") if isinstance(doc.get("model"), str) else model
        if not response.strip():
            why = ("budget_exhausted: done_reason=length, empty response "
                   f"(thinking {len(thinking)} chars) — not evidence the model is unfit"
                   if doc.get("done_reason") == "length" else
                   f"empty response (done_reason={doc.get('done_reason')!r})")
            return AdapterOutput("malformed", model=reported_model, usage=usage, detail=why, transport=transport)
        return AdapterOutput("ok", text=response, model=reported_model, usage=usage,
                             detail=f"done_reason={doc.get('done_reason')}", transport=transport)

    return run


def _urllib_post_json(url: str, body: Dict[str, Any], timeout_s: float) -> Dict[str, Any]:
    import socket
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    # no proxy: a loopback call never leaves the machine through an environment proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except socket.timeout as exc:
        raise TimeoutError(str(exc)) from exc
    except OSError as exc:
        if "timed out" in str(exc):
            raise TimeoutError(str(exc)) from exc
        raise
