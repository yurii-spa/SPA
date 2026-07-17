"""spa_core/investment_os/agents/liquidity.py — Liquidity analyst (AI Investment OS, docs/08).

RESHAPE, not rebuild. The desk already measures exit liquidity (data/exit_liquidity_log.json — how fast
each held position can be exited, bottlenecks, instantly-exitable $). This analyst CONSUMES the latest
measurement into ONE advisory exit-liquidity view for the product layer, evidence-tagged. Fail-CLOSED:
missing/empty log → UNKNOWN.

Boundaries (harness): IS_ADVISORY — reads only, writes only data/investment_os/liquidity.json; never
allocates, never touches RiskPolicy/kill/live track. Deterministic.

CLI::  python3 -m spa_core.investment_os.agents.liquidity [--check]
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

log = logging.getLogger("spa.investment_os.liquidity")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXIT_LOG = _REPO_ROOT / "data" / "exit_liquidity_log.json"


class LiquidityAgent(ProductAgent):
    agent_key = "liquidity"
    role_prompt = ("Liquidity analyst — surface the portfolio's exit-liquidity posture (how fast held "
                   "positions can be exited, bottlenecks); never invent a number; UNKNOWN when unmeasured.")

    def __init__(self, *, exit_log_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.exit_log_path = Path(exit_log_path) if exit_log_path is not None else _EXIT_LOG

    def analyze(self) -> dict:
        mtime = self.exit_log_path.stat().st_mtime if self.exit_log_path.exists() else None
        # exit liquidity only changes with the portfolio; no age gate (freshness via the log itself).
        data = self.read_feed(lambda: json.loads(self.exit_log_path.read_text()))
        if data is UNKNOWN:
            return {"status": UNKNOWN, "reason": "exit-liquidity log missing/unreadable (fail-closed)"}
        # log is append-only list; take the latest entry.
        latest = data[-1] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not isinstance(latest, dict):
            return {"status": UNKNOWN, "reason": "exit-liquidity log empty"}

        positions = latest.get("positions") or []
        by_label: dict[str, int] = {}
        bottlenecks: dict[str, int] = {}
        for p in positions:
            if not isinstance(p, dict):
                continue
            lbl = str(p.get("exit_label") or "?")
            by_label[lbl] = by_label.get(lbl, 0) + 1
            bn = p.get("bottleneck")
            if bn:
                bottlenecks[str(bn)] = bottlenecks.get(str(bn), 0) + 1

        return {
            "status": "ok",
            "exit_liquidity": self.evidence(
                {
                    "average_exit_liquidity_score": latest.get("average_exit_liquidity_score"),
                    "instantly_exitable_usd": latest.get("instantly_exitable_usd"),
                    "liquidity_ratio_pct": latest.get("liquidity_ratio_pct"),
                    "most_locked": latest.get("most_locked"),
                    "n_positions": len(positions),
                    "by_exit_label": by_label,
                    "top_bottlenecks": dict(sorted(bottlenecks.items(), key=lambda kv: -kv[1])[:4]),
                },
                "L4", "data/exit_liquidity_log.json (live cycle exit-liquidity measurement)",
            ),
            "note": ("Advisory. Portfolio exit-liquidity posture — how fast held positions can be exited "
                     "and where the bottlenecks are. Surfaces the desk's own measurement; computes nothing "
                     "new. Not a gate; the deterministic RiskPolicy is the only execution gate."),
        }


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return LiquidityAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.liquidity")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = LiquidityAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
