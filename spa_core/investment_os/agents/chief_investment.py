"""spa_core/investment_os/agents/chief_investment.py — Chief Investment analyst (Head of Product, docs/08).

The capstone of the AI Investment OS. It SYNTHESISES the other analysts' advisory artifacts
(stablecoin_yield · market_regime · reporting · red_team · liquidity from data/investment_os/) into ONE
house-view: overall posture, top opportunities, the evidenced track, threats, exit liquidity — surfacing
(never averaging away) conflicts. It preserves each input's evidence tag; it invents no number.

**HARD OWNER-GATE (docs/08 §2.1, ADR_004):** it can recommend, it NEVER decides. Any allocation
direction is emitted as an ADVISORY `house_view` only — it moves NO capital, is NOT a gate, and any real
allocation change requires the owner's approval. Fail-CLOSED: if no analyst artifacts exist → UNKNOWN.

CLI::  python3 -m spa_core.investment_os.agents.chief_investment [--check]
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.investment_os.harness import ProductAgent, UNKNOWN

log = logging.getLogger("spa.investment_os.chief_investment")

# The analyst artifacts this synthesiser consumes (produced by the other product agents).
_INPUTS = ("stablecoin_yield", "market_regime", "reporting", "red_team", "liquidity")


class ChiefInvestmentAgent(ProductAgent):
    agent_key = "chief_investment"
    role_prompt = ("Chief Investment analyst (Head of Product) — synthesise the analysts into one "
                   "house-view; surface conflicts; RECOMMEND only, NEVER decide (owner-gated).")

    def __init__(self, *, data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)

    def _load_input(self, agent: str) -> Any:
        path = self.data_dir / f"{agent}.json"
        return self.read_feed(lambda: json.loads(path.read_text()))

    def analyze(self) -> dict:
        inputs: dict[str, Any] = {}
        for a in _INPUTS:
            v = self._load_input(a)
            if isinstance(v, dict):
                inputs[a] = v
        if not inputs:
            return {"status": UNKNOWN,
                    "reason": "no analyst artifacts to synthesise yet (fail-closed)"}

        # ── posture: most-cautious of regime + red-team (surface, do not average) ──
        regime = (inputs.get("market_regime") or {}).get("combined_posture")
        threat = (inputs.get("red_team") or {}).get("posture")
        posture, conflicts = _synthesise_posture(regime, threat)

        # ── opportunities: top from stablecoin_yield (evidence preserved) ──
        sy = inputs.get("stablecoin_yield") or {}
        top_opps = (sy.get("top_stablecoin_yields") or [])[:3]

        # ── track + liquidity, surfaced verbatim (each carries its own L6/L4 tag) ──
        track = (inputs.get("reporting") or {}).get("track")
        exitliq = (inputs.get("liquidity") or {}).get("exit_liquidity")

        # honest coverage: which analysts were available vs UNKNOWN/missing.
        available = sorted(inputs.keys())
        missing = [a for a in _INPUTS if a not in inputs]

        return {
            "status": "ok",
            "house_view": {
                "overall_posture": posture,
                "conflicts": conflicts,     # surfaced, never averaged away
                "top_opportunities": top_opps,
                "evidenced_track": track,
                "exit_liquidity": exitliq,
                "threat_posture": threat,
                "regime": regime,
            },
            "coverage": {"available": available, "missing_or_unknown": missing,
                         "n_analysts": len(inputs)},
            "owner_gate": True,
            "note": ("Advisory HOUSE-VIEW synthesis. RECOMMENDS only — it NEVER decides and moves NO "
                     "capital; any allocation change is the OWNER's decision (owner-gate). Conflicts are "
                     "surfaced, not averaged. Each input keeps its own L0-L6 evidence tag. Not a gate; the "
                     "deterministic RiskPolicy v1.0 remains the only execution gate."),
        }


# posture cautiousness rank (higher = more cautious); unknown labels sort most cautious (fail-safe).
_RANK = {"GREEN": 0, "NO_THREAT_OBSERVED": 0, "NEUTRAL": 1, "STABLE": 1, "YELLOW": 2,
         "THREATS_PRESENT": 2, "COMPRESSION": 2, "RED": 3, "CRITICAL": 3, "STRESS": 3}


def _synthesise_posture(regime: Optional[str], threat: Optional[str]) -> tuple[str, list[str]]:
    """Most-cautious of the regime + threat posture (fail-safe). Returns (posture, conflicts)."""
    def rank(x: Optional[str]) -> int:
        if not x or str(x).upper().startswith("UNKNOWN"):
            return 99
        return _RANK.get(str(x).upper(), 99)
    rr, rt = rank(regime), rank(threat)
    conflicts: list[str] = []
    if rr != 99 and rt != 99 and abs(rr - rt) >= 2:
        conflicts.append(f"regime={regime} vs threat={threat} diverge — surfaced, not averaged")
    if rr == 99 and rt == 99:
        return "UNKNOWN_CAUTIOUS", conflicts
    # most cautious wins; if one is unknown, use the known one's label
    if rr == 99:
        return (str(threat).upper(), conflicts)
    if rt == 99:
        return (str(regime).upper(), conflicts)
    return (str(regime).upper() if rr >= rt else str(threat).upper(), conflicts)


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return ChiefInvestmentAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.chief_investment")
    ap.add_argument("--check", action="store_true", help="synthesise + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = ChiefInvestmentAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
