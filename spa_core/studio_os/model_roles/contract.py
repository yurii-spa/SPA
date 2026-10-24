"""One provider contract for every role (STUDIO-OS-MODELS-01, increment 2; ADR-OWN-2026-10-23).

# LLM_FORBIDDEN

The contract, not the provider, fixes what a call may do:

* **role ≠ provider.** A role (`architect`, `worker`) declares permissions, tools, required
  capabilities, context limit, deadline and attempts in ``architecture/model_roles.json``. A provider
  entry declares only what it CAN do (capabilities, context limit, which roles it is qualified for).
  A provider entry that declares ``permissions`` or ``tools`` is refused — choosing a provider never
  widens what a call may do.
* **explicit selection.** The provider is the caller's explicit ``provider_id`` or the role's
  configured assignment. Repository assignments are ``null`` (production routing off) ⇒ no provider
  ⇒ ``refused``. Unknown, unqualified, incapable or too-small provider ⇒ ``refused`` with the reason.
  There is no fallback and no escalation: a refusal is a result, never a cue to try another provider.
* **bounded.** ``attempts ≤ min(role.max_attempts, HARD_MAX_ATTEMPTS)``; every attempt has the role's
  deadline; only ``timeout`` and transient ``error`` are retried; ``quota`` and ``malformed`` are not.
* **accounted.** Elapsed time, attempts and each attempt's outcome are recorded; token/quota/cost
  fields only as the adapter REPORTS them — absent ⇒ ``UNKNOWN``. A reported cost is the transport's
  own figure and is NOT a subscription charge (none is inferred).

The adapters live in :mod:`spa_core.studio_os.model_roles.adapters`; tests inject their own.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

UNKNOWN = "UNKNOWN"
HARD_MAX_ATTEMPTS = 3
CONFIG_SCHEMA = "model-roles/1"
CONFIG_PATH = Path(__file__).resolve().parents[3] / "architecture" / "model_roles.json"
STATUSES = ("ok", "refused", "timeout", "error", "quota", "malformed")
_RETRYABLE = ("timeout", "error")
_FORBIDDEN_PROVIDER_KEYS = ("permissions", "tools", "allowed_tools")


class ConfigError(ValueError):
    """The role/provider configuration is unusable — the call is refused, not guessed."""


@dataclass(frozen=True)
class Request:
    role: str
    task_id: str
    instruction: str
    context: str
    context_ref: str = UNKNOWN        # e.g. the role-pack path; informational
    #: The caller may NARROW the role's deadline (e.g. ``memory.answer.ask(timeout=…)``), never widen it.
    deadline_s: Optional[float] = None

    @property
    def context_sha256(self) -> str:
        return hashlib.sha256(self.context.encode("utf-8")).hexdigest()


@dataclass
class AdapterOutput:
    """What an adapter returns for ONE attempt. ``status`` ∈ STATUSES minus ``refused``."""
    status: str
    text: str = ""
    model: str = UNKNOWN
    usage: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""


@dataclass
class Result:
    status: str
    role: str
    task_id: str
    provider_id: str
    provider_kind: str
    real_provider: Optional[bool]
    permissions: List[str]
    tools: List[str]
    text: str
    model: str
    attempts: int
    elapsed_s: Optional[float]
    usage: Dict[str, Any]
    attempt_log: List[Dict[str, Any]]
    reason: str
    context_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path else CONFIG_PATH
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"configuration not readable: {p}: {type(exc).__name__}: {exc}") from exc
    if doc.get("schema") != CONFIG_SCHEMA:
        raise ConfigError(f"configuration schema {doc.get('schema')!r} != {CONFIG_SCHEMA!r}")
    for key in ("roles", "providers", "assignments"):
        if not isinstance(doc.get(key), dict):
            raise ConfigError(f"configuration has no {key!r} mapping")
    return doc


def _refused(req: Request, why: str, provider_id: str = UNKNOWN, kind: str = UNKNOWN,
             real: Optional[bool] = None, role_spec: Optional[Mapping] = None) -> Result:
    rs = role_spec or {}
    return Result("refused", req.role, req.task_id, provider_id, kind, real,
                  list(rs.get("permissions") or []), list(rs.get("tools") or []), "", UNKNOWN, 0,
                  None, _usage({}), [], why, req.context_sha256)


def _usage(reported: Mapping[str, Any]) -> Dict[str, Any]:
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
            "cost_reported_usd", "quota_remaining")
    return {k: (reported[k] if k in reported and reported[k] is not None else UNKNOWN) for k in keys}


def execute(req: Request, *, config: Mapping[str, Any], provider_id: Optional[str] = None,
            adapters: Optional[Mapping[str, Callable[..., AdapterOutput]]] = None,
            clock: Callable[[], float] = time.monotonic) -> Result:
    """Run ONE request under the contract. Never raises for a provider problem — returns a Result."""
    roles, providers = config.get("roles") or {}, config.get("providers") or {}
    role = roles.get(req.role)
    if role is None:
        return _refused(req, f"unknown role {req.role!r}; declared: {sorted(roles)}")
    pid = provider_id or (config.get("assignments") or {}).get(req.role)
    if not pid:
        return _refused(req, f"no provider for role {req.role!r}: none given and the configuration "
                             f"assigns none (production routing is off)", role_spec=role)
    prov = providers.get(pid)
    if prov is None:
        return _refused(req, f"unknown provider {pid!r}; declared: {sorted(providers)}", pid,
                        role_spec=role)
    kind, real = str(prov.get("kind", UNKNOWN)), prov.get("real_provider")
    bad = [k for k in _FORBIDDEN_PROVIDER_KEYS if k in prov]
    if bad:
        return _refused(req, f"provider {pid!r} declares {bad}: permissions/tools belong to the role, "
                             f"a provider cannot widen them", pid, kind, real, role)
    if req.role not in (prov.get("qualified_roles") or []):
        return _refused(req, f"provider {pid!r} is not qualified for role {req.role!r}", pid, kind,
                        real, role)
    missing = sorted(set(role.get("requires") or []) - set(prov.get("capabilities") or []))
    if missing:
        return _refused(req, f"provider {pid!r} lacks capabilities {missing}", pid, kind, real, role)
    limit = min(int(role.get("max_context_chars", 0)), int(prov.get("max_context_chars", 0)))
    size = len(req.context) + len(req.instruction)
    if size > limit:
        return _refused(req, f"context {size} chars > limit {limit} (role/provider); not truncated",
                        pid, kind, real, role)
    adapter = (adapters or {}).get(kind)
    if adapter is None:
        return _refused(req, f"no adapter for provider kind {kind!r}", pid, kind, real, role)

    attempts = max(1, min(int(role.get("max_attempts", 1)), HARD_MAX_ATTEMPTS))
    deadline = float(role.get("deadline_s", 60))
    if req.deadline_s is not None:
        if req.deadline_s <= 0:
            return _refused(req, f"deadline {req.deadline_s} s is not positive", pid, kind, real, role)
        deadline = min(deadline, float(req.deadline_s))
    log: List[Dict[str, Any]] = []
    out = AdapterOutput("error", detail="not attempted")
    t0 = clock()
    for n in range(1, attempts + 1):
        a0 = clock()
        try:
            out = adapter(req, timeout_s=deadline, tools=list(role.get("tools") or []))
        except Exception as exc:  # noqa: BLE001 — an adapter crash is an error result, not a crash
            out = AdapterOutput("error", detail=f"{type(exc).__name__}: {exc}")
        if out.status not in STATUSES or out.status == "refused":
            out = AdapterOutput("error", detail=f"adapter returned status {out.status!r}")
        if out.status == "ok" and not out.text.strip():
            out = AdapterOutput("malformed", detail="empty answer", model=out.model, usage=out.usage)
        log.append({"attempt": n, "status": out.status, "elapsed_s": round(clock() - a0, 3),
                    "detail": out.detail[:300]})
        if out.status not in _RETRYABLE:
            break
    return Result(out.status, req.role, req.task_id, pid, kind, real,
                  list(role.get("permissions") or []), list(role.get("tools") or []),
                  out.text if out.status == "ok" else "", out.model or UNKNOWN, len(log),
                  round(clock() - t0, 3), _usage(out.usage), log,
                  "" if out.status == "ok" else (out.detail or out.status), req.context_sha256)
