"""spa_core/investment_os/agents/onchain.py — On-chain / Developer Activity analyst (AI Investment OS, docs/08).

RESHAPE, not rebuild. The desk already tracks developer activity per protocol (data/developer_activity_log.json
— commit momentum, team health, maintenance, velocity trend). This analyst CONSUMES the latest measurement
into ONE advisory developer-activity view: which protocols have healthy, active teams vs abandoned/inactive
ones — a fundamental signal (an abandoned protocol is a latent risk regardless of its APY). Evidence-tagged,
fail-CLOSED to UNKNOWN.

Boundaries (harness): IS_ADVISORY — reads only, writes only data/investment_os/onchain.json; never allocates,
never touches RiskPolicy/kill/live track. Deterministic.

CLI::  python3 -m spa_core.investment_os.agents.onchain [--check]
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

log = logging.getLogger("spa.investment_os.onchain")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEV_LOG = _REPO_ROOT / "data" / "developer_activity_log.json"


class OnchainActivityAgent(ProductAgent):
    agent_key = "onchain"
    role_prompt = ("On-chain / Developer Activity analyst — surface which protocols have healthy active "
                   "teams vs abandoned/inactive ones; an abandoned protocol is a latent risk; never invent.")

    def __init__(self, *, dev_log_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.dev_log_path = Path(dev_log_path) if dev_log_path is not None else _DEV_LOG

    def analyze(self) -> dict:
        data = self.read_feed(lambda: json.loads(self.dev_log_path.read_text()))
        if data is UNKNOWN:
            return {"status": UNKNOWN, "reason": "developer-activity log missing/unreadable (fail-closed)"}
        latest = data[-1] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
        if not isinstance(latest, dict):
            return {"status": UNKNOWN, "reason": "developer-activity log empty"}

        protocols = latest.get("protocols") or []
        # summarise per-protocol activity level distribution
        by_level: dict[str, int] = {}
        for p in protocols:
            if isinstance(p, dict):
                lvl = str(p.get("activity_level") or "?")
                by_level[lvl] = by_level.get(lvl, 0) + 1
        inactive = latest.get("inactive_protocols") or []
        concern = "INACTIVE_TEAMS" if inactive else "NONE_SURFACED"

        return {
            "status": "ok",
            "concern": concern,
            "developer_activity": self.evidence(
                {
                    "average_activity_score": latest.get("average_activity_score"),
                    "most_active": latest.get("most_active"),
                    "least_active": latest.get("least_active"),
                    "n_protocols": len(protocols),
                    "by_activity_level": by_level,
                    "inactive_protocols": inactive,
                },
                "L3", "data/developer_activity_log.json (live developer-activity measurement)",
            ),
            "note": ("Advisory. Protocol developer-activity health — active maintained teams vs "
                     "abandoned/inactive ones. A protocol with a dead team is a latent risk regardless of "
                     "APY. Surfaces the desk's own measurement; can only RAISE concern; not a gate."),
        }


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return OnchainActivityAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.onchain")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = OnchainActivityAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
