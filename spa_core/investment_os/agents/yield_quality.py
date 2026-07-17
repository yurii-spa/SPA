"""spa_core/investment_os/agents/yield_quality.py — Yield Quality analyst (AI Investment OS, docs/08).

The desk's DIFFERENTIATOR made an analyst: honest yield-source decomposition. It CONSUMES the desk's
APY-decomposition log (data/apy_decomposition_log.json — advertised vs SUSTAINABLE yield, incentive
decay) into ONE advisory yield-quality view: how much of a headline APY is real cash-flow vs transient
incentive/points. Evidence-tagged, fail-CLOSED to UNKNOWN.

Boundaries (harness): IS_ADVISORY — reads only, writes only data/investment_os/yield_quality.json; never
allocates, never touches RiskPolicy/kill/live track. Deterministic.

CLI::  python3 -m spa_core.investment_os.agents.yield_quality [--check]
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

log = logging.getLogger("spa.investment_os.yield_quality")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DECOMP = _REPO_ROOT / "data" / "apy_decomposition_log.json"

# thresholds for a cautious concern flag (surface only, never a gate)
_LOW_SUSTAINABILITY = 0.6      # <60% of advertised APY is sustainable → concern
_HIGH_DECAY = 40.0            # >40% incentive-decay risk → concern


class YieldQualityAgent(ProductAgent):
    agent_key = "yield_quality"
    role_prompt = ("Yield Quality analyst — decompose advertised vs SUSTAINABLE yield; surface how much "
                   "of a headline APY is real cash-flow vs transient incentive/points; never invent a number.")

    def __init__(self, *, decomp_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.decomp_path = Path(decomp_path) if decomp_path is not None else _DECOMP

    def analyze(self) -> dict:
        data = self.read_feed(lambda: json.loads(self.decomp_path.read_text()))
        if data is UNKNOWN:
            return {"status": UNKNOWN, "reason": "apy-decomposition log missing/unreadable (fail-closed)"}
        latest = data[-1] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not isinstance(latest, dict):
            return {"status": UNKNOWN, "reason": "apy-decomposition log empty"}

        ratio = latest.get("sustainability_ratio")
        decay = latest.get("incentive_decay_risk_pct")
        concern = "NONE_SURFACED"
        if isinstance(ratio, (int, float)) and ratio < _LOW_SUSTAINABILITY:
            concern = "LOW_SUSTAINABILITY"
        elif isinstance(decay, (int, float)) and decay > _HIGH_DECAY:
            concern = "HIGH_INCENTIVE_DECAY"

        return {
            "status": "ok",
            "concern": concern,
            "yield_quality": self.evidence(
                {
                    "protocol_name": latest.get("protocol_name"),
                    "total_advertised_apy_pct": latest.get("total_advertised_apy_pct"),
                    "sustainable_apy_pct": latest.get("sustainable_apy_pct"),
                    "sustainability_ratio": ratio,
                    "apy_label": latest.get("apy_label"),
                    "apy_quality_score": latest.get("apy_quality_score"),
                    "incentive_decay_risk_pct": decay,
                },
                "L4", "data/apy_decomposition_log.json (live yield decomposition)",
                last_verified=latest.get("ts"),
            ),
            "note": ("Advisory. Honest yield decomposition — advertised vs SUSTAINABLE (real cash-flow) "
                     "yield + incentive-decay risk. This is the desk's differentiator: it prefers a "
                     "smaller sustainable yield over a headline number that is transient incentive. "
                     "Surfaces the desk's own measurement; not a gate."),
        }


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return YieldQualityAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.yield_quality")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = YieldQualityAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
