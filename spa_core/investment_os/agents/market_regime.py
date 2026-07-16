"""spa_core/investment_os/agents/market_regime.py — Market Regime analyst (AI Investment OS, docs/08).

RESHAPE, not rebuild. The desk already PRODUCES two regime signals:
  • yield regime   — data/market_regime.json  (spa_core/analysis/market_regime.py: T1 APY level/dispersion)
  • funding regime — data/swarm/funding_regime.json (swarm L1: GREEN/YELLOW/RED carry weather)
This analyst CONSUMES both (never recomputes) and emits ONE unified advisory regime view for the product
layer, evidence-tagged, fail-CLOSED to UNKNOWN when a source is missing/stale.

Boundaries (harness): IS_ADVISORY — reads only, writes only data/investment_os/market_regime.json; never
allocates, never touches RiskPolicy/kill/live track. Deterministic.

CLI::  python3 -m spa_core.investment_os.agents.market_regime [--check]
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

log = logging.getLogger("spa.investment_os.market_regime")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_YIELD_REGIME = _REPO_ROOT / "data" / "market_regime.json"
_FUNDING_REGIME = _REPO_ROOT / "data" / "swarm" / "funding_regime.json"
_MAX_AGE_S = 3 * 86400


class MarketRegimeAgent(ProductAgent):
    agent_key = "market_regime"
    role_prompt = ("Market Regime analyst — CONSUME the desk's yield-regime and funding-regime signals "
                   "into one advisory view; never recompute a regime; UNKNOWN when a source is stale.")

    def __init__(self, *, yield_path: Optional[Path] = None, funding_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.yield_path = Path(yield_path) if yield_path is not None else _YIELD_REGIME
        self.funding_path = Path(funding_path) if funding_path is not None else _FUNDING_REGIME

    def _read(self, path: Path) -> Any:
        mtime = path.stat().st_mtime if path.exists() else None
        return self.read_feed(lambda: json.loads(path.read_text()),
                              max_age_s=_MAX_AGE_S, mtime=mtime)

    def analyze(self) -> dict:
        yr = self._read(self.yield_path)
        fr = self._read(self.funding_path)
        if (yr is UNKNOWN or not isinstance(yr, dict)) and (fr is UNKNOWN or not isinstance(fr, dict)):
            return {"status": UNKNOWN, "reason": "both regime feeds missing/stale (fail-closed)"}

        out: dict[str, Any] = {"status": "ok"}

        if isinstance(yr, dict):
            out["yield_regime"] = self.evidence(
                {
                    "regime": yr.get("regime"),
                    "t1_avg_apy": yr.get("t1_avg_apy"),
                    "apy_std_dev": yr.get("apy_std_dev"),
                    "recommendation": yr.get("recommendation"),
                },
                "L4", "data/market_regime.json (live cycle)",
                last_verified=yr.get("detected_at"),
            )
        else:
            out["yield_regime"] = self.evidence(UNKNOWN, "L0", "data/market_regime.json (missing/stale)")

        if isinstance(fr, dict):
            out["funding_regime"] = self.evidence(
                {
                    "regime": fr.get("regime"),
                    "primary_symbol": fr.get("primary_symbol"),
                    "per_symbol": {s: v.get("regime") for s, v in (fr.get("symbols") or {}).items()
                                   if isinstance(v, dict)},
                },
                "L4", "data/swarm/funding_regime.json (swarm L1, advisory)",
                last_verified=fr.get("as_of_utc"),
            )
        else:
            out["funding_regime"] = self.evidence(UNKNOWN, "L0", "data/swarm/funding_regime.json (missing/stale)")

        # A deterministic combined posture: worst-of the two (most cautious wins), never invented.
        out["combined_posture"] = _combine_posture(
            yr.get("regime") if isinstance(yr, dict) else None,
            fr.get("regime") if isinstance(fr, dict) else None,
        )
        out["note"] = ("Advisory. Consumes the desk's yield-regime + funding-regime signals; does NOT "
                       "recompute them. combined_posture = most-cautious of the two (fail-safe). Not a "
                       "gate — the deterministic RiskPolicy is the only execution gate.")
        return out


# Regime → cautiousness rank (higher = more cautious). Unknown/None sorts as most cautious (fail-safe).
_CAUTION = {"GREEN": 0, "NEUTRAL": 1, "STABLE": 1, "YELLOW": 2, "COMPRESSION": 2, "RED": 3, "STRESS": 3}


def _combine_posture(a: Optional[str], b: Optional[str]) -> str:
    """Most-cautious of two regime labels (fail-safe). Unknown label → treated as most cautious."""
    def rank(x: Optional[str]) -> int:
        if not x:
            return 99
        return _CAUTION.get(str(x).upper(), 99)
    ra, rb = rank(a), rank(b)
    worst = a if ra >= rb else b
    if ra == 99 and rb == 99:
        return UNKNOWN
    # if the worst is an unknown label but the other is known, prefer the known-cautious one's label
    if rank(worst) == 99:
        worst = a if rb == 99 else b
    return str(worst).upper() if worst else UNKNOWN


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return MarketRegimeAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.market_regime")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = MarketRegimeAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
