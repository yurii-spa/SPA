"""
spa_core/redteam/base.py — the pluggable RedTeamScenario ABC + the Finding verdict.

A scenario is a deterministic adversary against ONE attack surface. It:
  1. builds a HEALTHY sandbox artifact (in the supplied tmp dir — NEVER live data/),
  2. proves the defense PASSES the healthy artifact (a control — no false alarm),
  3. FORGES / tampers the artifact (the attack),
  4. feeds the forged artifact through the REAL defense and reports whether it was CAUGHT.

`caught == True` is the only acceptable outcome (the defense works). An UNCAUGHT forgery is a real
hole → fail-CLOSED FAIL in the runner. A scenario that raises is ALSO a FAIL (we never paper over an
exception as "passed").

stdlib-only · deterministic · fail-CLOSED · LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


class Surface:
    """The canonical attack-surface vocabulary the rotation cycles through. One scenario targets
    exactly one of these. Adding a surface is additive — the rotation picks it up by membership in
    ``ALL`` (deterministic order preserved)."""

    MONEY_PATH = "money_path"        # the liquidation/exit-NAV output (no fabricated fills)
    PROOF = "proof"                  # the tamper-evident decision/proof chain (verify_spa)
    OPTIMIZER = "optimizer"          # the RiskPolicy allocation gate (concentration cap)
    SLEEVES = "sleeves"              # the live-paper go-live track (sandbox interlock)
    KILL_SWITCH = "kill_switch"      # the drawdown kill-switch ladder
    FEEDS = "feeds"                  # the live data feed (NaN / fabrication rejection)
    DASHBOARD = "dashboard"          # the dashboard data-integrity contract

    # Deterministic rotation order (UTC-day modulo this list).
    ALL = (MONEY_PATH, PROOF, OPTIMIZER, SLEEVES, KILL_SWITCH, FEEDS, DASHBOARD)


@dataclass
class Finding:
    """The verdict of ONE attack attempt. ``caught`` is the load-bearing field: a forgery that the
    defense FAILED to catch (``caught is False`` while ``attempted is True``) is a real hole."""

    scenario: str
    surface: str
    attempted: bool                 # did the attack actually fire? (False ⇒ scenario could not run)
    caught: bool                    # did the REAL defense catch the forgery?
    evidence: str                   # human-readable proof of what was attacked + how it was caught
    control_ok: bool = True         # did the defense PASS the healthy artifact first? (no false alarm)
    error: str = ""                 # set when the scenario raised (⇒ FAIL, fail-CLOSED)
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """A scenario PASSES iff it actually fired, the control passed, the forgery was caught, and
        nothing raised. fail-CLOSED: any of those false ⇒ not ok."""
        return bool(self.attempted and self.control_ok and self.caught and not self.error)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario,
            "surface": self.surface,
            "attempted": self.attempted,
            "caught": self.caught,
            "control_ok": self.control_ok,
            "ok": self.ok,
            "error": self.error,
            "evidence": self.evidence,
            "detail": self.detail,
        }


class RedTeamScenario(abc.ABC):
    """Pluggable adversary against one surface. Subclass, set ``name``/``surface``, implement
    ``attack``. The runner gives each scenario a FRESH sandbox dir and wraps ``attack`` so a raise
    becomes a fail-CLOSED Finding (never a crash that aborts the suite)."""

    #: short, stable id (used in the verdict + rotation status).
    name: str = "unnamed"
    #: one of Surface.ALL.
    surface: str = ""
    #: one-line description of the proven attack this scenario reuses.
    description: str = ""

    @abc.abstractmethod
    def attack(self, sandbox: Path) -> Finding:
        """Build a healthy artifact in ``sandbox``, prove the defense passes it, forge it, and feed
        the forgery through the REAL defense. Return a Finding. MUST NOT write outside ``sandbox``.
        MUST be deterministic (fixed ts/seeds)."""
        raise NotImplementedError

    # ── helpers a scenario may use to assemble a Finding consistently ──
    def _caught(self, evidence: str, **detail: Any) -> Finding:
        return Finding(self.name, self.surface, attempted=True, caught=True, control_ok=True,
                       evidence=evidence, detail=detail)

    def _uncaught(self, evidence: str, **detail: Any) -> Finding:
        """The forgery slipped past the defense — a real hole. fail-CLOSED."""
        return Finding(self.name, self.surface, attempted=True, caught=False, control_ok=True,
                       evidence=evidence, detail=detail)

    def _control_failed(self, evidence: str, **detail: Any) -> Finding:
        """The defense rejected the HEALTHY artifact (a false alarm) — the scenario cannot trust a
        later 'caught' from a defense that cries wolf. fail-CLOSED."""
        return Finding(self.name, self.surface, attempted=True, caught=False, control_ok=False,
                       evidence=evidence, detail=detail)
