"""spa_core/investment_os/harness.py — shared base for AI Investment OS analyst agents.

The analyst analog of `spa_core/strategy_lab/swarm/common.py`: the ONE place that implements the
universal product-agent contract (docs/08_ai_investment_os_architecture.md §universal-contract) so every
analyst is a thin module. Deterministic-first; the LLM is optional and gated.

What the harness gives a `ProductAgent`:
  • ``read_feed(loader, max_age_s=…)`` — fail-CLOSED feed read: any error or staleness → ``UNKNOWN``.
  • ``evidence(value, level, source, …)`` — attach an L0-L6 evidence tag + source + last-verified.
  • ``reason(prompt, facts, …)`` — OPTIONAL LLM reasoning behind a number-gate: any figure in the LLM
    output that is not in the sourced facts causes the WHOLE LLM output to be discarded (fail-closed) and
    the deterministic fallback returned. LLM is skipped entirely when no key / ``is_llm_forbidden``.
  • ``emit(payload)`` — atomic write to ``data/investment_os/<agent>.json`` + one hash-chained proof line,
    forcing ``is_advisory: True`` and a ``consumer_contract`` stamp. Never writes runtime state.

Invariants: stdlib runtime · atomic writes (`spa_core.utils.atomic`) · advisory-only · never imports
`spa_core/execution/` · never touches RiskPolicy/kill-switch/live track. LLM only AROUND reasoning.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.strategy_lab.swarm.common import append_daily_proof
from spa_core.cmo.honesty_gate import _extract_numbers  # reuse the sourced-number matcher

log = logging.getLogger("spa.investment_os.harness")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "investment_os"

# Sentinel for a fact the agent refuses to assert (missing / stale / diverging feed). NEVER a made-up number.
UNKNOWN = "UNKNOWN"

# Evidence ladder (docs/37). L0 = claim only … L6 = live evidenced on our own track.
EVIDENCE_LEVELS: tuple[str, ...] = ("L0", "L1", "L2", "L3", "L4", "L5", "L6")

CONSUMER_CONTRACT = (
    "advisory analyst artifact — paper/research, IS_ADVISORY, never moves capital, never a gate. "
    "Numbers carry an L0-L6 evidence tag; UNKNOWN means refused, never fabricated."
)


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(now: Optional[datetime] = None) -> str:
    return _now(now).isoformat()


class ProductAgent:
    """Base for an advisory analyst agent. Subclasses set ``agent_key`` and implement ``analyze()``
    returning a JSON-serialisable payload; the harness handles feeds, evidence, optional LLM, emit."""

    #: short agent key, e.g. "stablecoin_yield" (used for the artifact filename + model lookup).
    agent_key: str = "product_agent"
    #: human role prompt handed to the LLM (subclass overrides).
    role_prompt: str = ""

    def __init__(
        self,
        *,
        data_dir: Optional[str | Path] = None,
        allow_llm: bool = True,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        self._allow_llm_flag = allow_llm
        self._llm: Any = None  # lazy

    # ── feeds (fail-closed) ──────────────────────────────────────────────────
    @staticmethod
    def read_feed(
        loader: Callable[[], Any],
        *,
        max_age_s: Optional[float] = None,
        mtime: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> Any:
        """Read a feed via ``loader`` fail-CLOSED. Returns ``UNKNOWN`` if the loader raises/returns None,
        or (when ``max_age_s`` + ``mtime`` given) if the data is older than ``max_age_s`` seconds."""
        try:
            value = loader()
        except Exception as exc:  # noqa: BLE001 — a feed error must never crash the agent
            log.info("read_feed: loader error → UNKNOWN: %s", exc)
            return UNKNOWN
        if value is None:
            return UNKNOWN
        if max_age_s is not None and mtime is not None:
            age = _now(now).timestamp() - float(mtime)
            if age > max_age_s:
                log.info("read_feed: stale (%.0fs > %.0fs) → UNKNOWN", age, max_age_s)
                return UNKNOWN
        return value

    # ── evidence tagging ─────────────────────────────────────────────────────
    @staticmethod
    def evidence(
        value: Any,
        level: str,
        source: str,
        *,
        last_verified: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> dict:
        """Wrap a value with its evidence tag. ``level`` must be L0-L6 (else stamped 'L0?' — never silently
        upgraded). A ``value`` of ``UNKNOWN`` keeps its refusal semantics."""
        lvl = level if level in EVIDENCE_LEVELS else f"{level}?"
        return {
            "value": value,
            "evidence_level": lvl,
            "source": source,
            "last_verified": last_verified or _iso(now),
        }

    # ── optional LLM reasoning behind a number-gate ──────────────────────────
    def _is_llm_allowed(self) -> bool:
        if not self._allow_llm_flag:
            return False
        try:
            from spa_core.agents.model_config import is_llm_forbidden
            return not is_llm_forbidden(self.agent_key)
        except Exception:  # noqa: BLE001
            return False

    def reason(
        self,
        prompt: str,
        facts: Any,
        *,
        deterministic_fallback: str,
        context: Optional[dict] = None,
    ) -> str:
        """OPTIONAL LLM rewording of ``prompt`` over ``facts``. Fail-CLOSED number-gate: if the LLM output
        contains ANY number not present in ``facts``, the whole LLM output is discarded and
        ``deterministic_fallback`` returned. LLM is skipped (fallback returned) when no key / forbidden."""
        if not self._is_llm_allowed():
            return deterministic_fallback
        try:
            if self._llm is None:
                from spa_core.agents.llm_agent import LLMAgent
                self._llm = LLMAgent(self.agent_key, self.role_prompt)
            out = self._llm.ask(prompt, context)
        except Exception as exc:  # noqa: BLE001 — reasoning must never crash the agent
            log.info("reason: LLM error → deterministic fallback: %s", exc)
            return deterministic_fallback
        if not out or not str(out).strip():
            return deterministic_fallback
        # number-gate: every number the LLM emits must be sourced from the facts.
        fact_nums = _extract_numbers(_flatten(facts))
        for n in _extract_numbers(str(out)):
            if not any(abs(n - f) <= 1e-6 for f in fact_nums):
                log.info("reason: LLM emitted unsourced number %s → discard LLM, use fallback", n)
                return deterministic_fallback
        return str(out)

    # ── emit artifact + proof ────────────────────────────────────────────────
    def emit(self, payload: dict, *, now: Optional[datetime] = None) -> Path:
        """Atomically write ``data/investment_os/<agent_key>.json`` (advisory-stamped) + append one
        hash-chained proof line for the UTC day. Returns the artifact path. Never a runtime state file."""
        ts = _iso(now)
        doc = dict(payload)
        doc.update({
            "agent": self.agent_key,
            "is_advisory": True,
            "generated_at": ts,
            "consumer_contract": CONSUMER_CONTRACT,
        })
        self.data_dir.mkdir(parents=True, exist_ok=True)
        artifact = self.data_dir / f"{self.agent_key}.json"
        atomic_save(doc, str(artifact))
        try:
            proof = self.data_dir / f"{self.agent_key}_proof.jsonl"
            day = _now(now).strftime("%Y-%m-%d")
            append_daily_proof({"agent": self.agent_key, "generated_at": ts}, proof, day=day)
        except Exception:  # noqa: BLE001 — proof is best-effort, must not fail the emit
            log.warning("emit: proof append failed", exc_info=True)
        return artifact

    # ── subclass hook ────────────────────────────────────────────────────────
    def analyze(self) -> dict:  # pragma: no cover - abstract
        """Subclass: gather feeds → structure + evidence-tag → optional reason() → return payload dict."""
        raise NotImplementedError

    def run(self, *, now: Optional[datetime] = None) -> Path:
        """Standard cycle entrypoint: analyze() → emit(). Never raises on analyze errors (fail-closed emit)."""
        try:
            payload = self.analyze()
        except Exception as exc:  # noqa: BLE001
            log.warning("%s.analyze failed → UNKNOWN payload: %s", self.agent_key, exc)
            payload = {"status": UNKNOWN, "error": str(exc)}
        return self.emit(payload, now=now)


def _flatten(facts: Any) -> str:
    """Flatten a facts structure into one text blob (for the number-gate)."""
    parts: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for vv in v.values():
                walk(vv)
        elif isinstance(v, (list, tuple)):
            for vv in v:
                walk(vv)
        elif v is not None:
            parts.append(str(v))

    walk(facts)
    return " ".join(parts)
