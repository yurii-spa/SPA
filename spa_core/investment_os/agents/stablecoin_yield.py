"""spa_core/investment_os/agents/stablecoin_yield.py — Stablecoin Yield analyst (AI Investment OS).

The first live analyst on the product-layer harness (docs/08 §Stablecoin Yield Agent). It reads the
desk's live risk-adjusted APY ranking (data/apy_ranking.json — produced read-only by the cycle from the
whitelisted adapters/DeFiLlama) and produces an ADVISORY artifact: the top conservative-tier stablecoin
yields, ranked by RISK-ADJUSTED APY, each evidence-tagged. Fail-CLOSED: a missing/stale feed → UNKNOWN,
never a fabricated number.

Boundaries (harness contract): IS_ADVISORY — never allocates, never touches RiskPolicy/kill/live track;
writes only data/investment_os/stablecoin_yield.json. Deterministic; the honest job is to SURFACE and
evidence-tag opportunities (and note what the desk refuses), not to chase a headline number.

CLI::  python3 -m spa_core.investment_os.agents.stablecoin_yield [--check]
"""
# LLM_FORBIDDEN  (deterministic; optional LLM commentary would go behind harness.reason's number-gate)
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.investment_os.harness import ProductAgent, UNKNOWN

log = logging.getLogger("spa.investment_os.stablecoin_yield")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RANKING = _REPO_ROOT / "data" / "apy_ranking.json"

# Conservative stablecoin lending lives in T1/T2. T3 (exotic PT/YT/points) is shown by the Aggressive
# Lab WITH its tail and is refused for live — this analyst deliberately scopes to the conservative book.
_CONSERVATIVE_TIERS = frozenset({"T1", "T2"})
# feed is considered stale beyond this age (the cycle refreshes ~daily; give generous slack).
_MAX_FEED_AGE_S = 3 * 86400


def _evidence_level_for_tier(tier: str) -> str:
    # Feed APYs are live external (DeFiLlama-derived), not our own evidenced track (that would be L6).
    # T1 conservative pools = L4 (live external, held-eligible); T2 = L3 (live external, advisory).
    return "L4" if tier == "T1" else "L3"


class StablecoinYieldAgent(ProductAgent):
    agent_key = "stablecoin_yield"
    role_prompt = ("Stablecoin Yield analyst — surface the best RISK-ADJUSTED conservative stablecoin "
                   "yields from the live ranking; never invent a number; flag refusals honestly.")

    def __init__(self, *, ranking_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True,
                 top_n: int = 5) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.ranking_path = Path(ranking_path) if ranking_path is not None else _DEFAULT_RANKING
        self.top_n = top_n

    def _load_ranking(self) -> Any:
        return json.loads(self.ranking_path.read_text())

    def analyze(self) -> dict:
        mtime = self.ranking_path.stat().st_mtime if self.ranking_path.exists() else None
        ranking = self.read_feed(self._load_ranking, max_age_s=_MAX_FEED_AGE_S, mtime=mtime)
        if ranking is UNKNOWN or not isinstance(ranking, dict):
            return {"status": UNKNOWN,
                    "reason": "apy_ranking feed missing/stale/unreadable (fail-closed)"}
        rows = ranking.get("by_risk_adjusted") or ranking.get("by_apy") or []
        if not isinstance(rows, list) or not rows:
            return {"status": UNKNOWN, "reason": "ranking has no rows"}

        considered = [r for r in rows
                      if isinstance(r, dict) and r.get("tier") in _CONSERVATIVE_TIERS
                      and isinstance(r.get("risk_adjusted_apy"), (int, float))]
        considered.sort(key=lambda r: float(r.get("risk_adjusted_apy") or 0.0), reverse=True)

        picks = []
        for r in considered[: self.top_n]:
            tier = str(r.get("tier"))
            picks.append(self.evidence(
                {
                    "protocol": r.get("protocol"),
                    "network": r.get("network"),
                    "tier": tier,
                    "apy_pct": r.get("apy_pct"),
                    "risk_adjusted_apy": r.get("risk_adjusted_apy"),
                    "risk_score": r.get("risk_score"),
                    "tvl_usd": r.get("tvl_usd"),
                },
                _evidence_level_for_tier(tier),
                "data/apy_ranking.json (live cycle · DeFiLlama-derived)",
                last_verified=r.get("last_updated"),
            ))

        # honestly note the exotic tier the desk refuses for live (T3), for context — not a recommendation.
        refused_t3 = sum(1 for r in rows if isinstance(r, dict) and r.get("tier") == "T3")
        return {
            "status": "ok" if picks else UNKNOWN,
            "as_of": ranking.get("generated_at"),
            "n_considered_conservative": len(considered),
            "top_stablecoin_yields": picks,
            "refused_exotic_t3_count": refused_t3,
            "note": ("Advisory. Top conservative-tier (T1/T2) stablecoin yields by RISK-ADJUSTED APY from "
                     "the live ranking. T3 exotic (PT/YT/points) excluded — refused for live, shown WITH "
                     "tail in the Aggressive Lab. Not a recommendation; the desk's live book is the "
                     "conservative track (~3.3% realized)."),
        }


def run(*, now: Optional[datetime] = None, ranking_path: Optional[Path] = None,
        data_dir: Optional[str | Path] = None) -> Path:
    return StablecoinYieldAgent(ranking_path=ranking_path, data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.stablecoin_yield")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = StablecoinYieldAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    path = agent.run()
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
