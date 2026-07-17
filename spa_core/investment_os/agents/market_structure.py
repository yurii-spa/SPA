"""spa_core/investment_os/agents/market_structure.py — Market Structure analyst (AI Investment OS, docs/08).

RESHAPE, not rebuild. The desk already measures cross-asset correlation risk
(data/cross_asset_correlation_log.json — how correlated the held positions are; high correlation = a
diversification failure = concentrated tail risk when everything sells off together). This analyst
CONSUMES the latest measurement into ONE advisory market-structure view. Evidence-tagged, fail-CLOSED.

Boundaries (harness): IS_ADVISORY — reads only, writes only data/investment_os/market_structure.json;
never allocates, never touches RiskPolicy/kill/live track. Deterministic; can only surface concern.

CLI::  python3 -m spa_core.investment_os.agents.market_structure [--check]
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

log = logging.getLogger("spa.investment_os.market_structure")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORR_LOG = _REPO_ROOT / "data" / "cross_asset_correlation_log.json"
# avg_correlation_risk (0-100) above this → concentrated/correlated book (concern).
_HIGH_CORRELATION_RISK = 60.0


class MarketStructureAgent(ProductAgent):
    agent_key = "market_structure"
    role_prompt = ("Market Structure analyst — surface cross-asset correlation risk; high correlation "
                   "means a diversification failure (concentrated tail); never invent a number.")

    def __init__(self, *, corr_log_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.corr_log_path = Path(corr_log_path) if corr_log_path is not None else _CORR_LOG

    def analyze(self) -> dict:
        # freshness conveyed via the entry's ts (correlation monitor runs infrequently); no mtime gate.
        data = self.read_feed(lambda: json.loads(self.corr_log_path.read_text()))
        if data is UNKNOWN:
            return {"status": UNKNOWN, "reason": "correlation log missing/unreadable (fail-closed)"}
        latest = data[-1] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not isinstance(latest, dict):
            return {"status": UNKNOWN, "reason": "correlation log empty"}

        risk = latest.get("avg_correlation_risk")
        dangerous = latest.get("dangerous_count")
        concern = "NONE_SURFACED"
        if isinstance(dangerous, (int, float)) and dangerous > 0:
            concern = "DANGEROUS_CORRELATION"
        elif isinstance(risk, (int, float)) and risk > _HIGH_CORRELATION_RISK:
            concern = "HIGH_CORRELATION_RISK"

        return {
            "status": "ok",
            "concern": concern,
            "market_structure": self.evidence(
                {
                    "avg_correlation_risk": risk,
                    "dangerous_count": dangerous,
                    "well_diversified_count": latest.get("well_diversified_count"),
                    "most_concentrated": latest.get("most_concentrated"),
                    "most_diversified": latest.get("most_diversified"),
                    "portfolio_count": latest.get("portfolio_count"),
                },
                "L4", "data/cross_asset_correlation_log.json (live correlation measurement)",
                last_verified=latest.get("ts"),
            ),
            "note": ("Advisory. Cross-asset correlation risk — a highly correlated book is a "
                     "diversification failure (concentrated tail: everything sells off together). "
                     "Surfaces the desk's own measurement; can only RAISE concern; not a gate."),
        }


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return MarketStructureAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.market_structure")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = MarketStructureAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
