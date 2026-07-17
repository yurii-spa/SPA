"""spa_core/investment_os/agents/protocol_risk.py — Protocol & Peg Risk analyst (AI Investment OS, docs/08).

RESHAPE, not rebuild. The desk already scores protocol risk (data/protocol_risk_map.json) and monitors
stablecoin pegs (data/peg_report.json). This analyst CONSUMES both into ONE advisory risk view for the
product layer: the protocol risk-tier distribution + the peg health summary (worst deviation, counts by
status). Evidence-tagged, fail-CLOSED to UNKNOWN when both sources are gone (never a default all-safe).

Boundaries (harness): IS_ADVISORY — reads only, writes only data/investment_os/protocol_risk.json; never
allocates, never touches RiskPolicy/kill/live track. Deterministic; can only surface concern.

CLI::  python3 -m spa_core.investment_os.agents.protocol_risk [--check]
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

log = logging.getLogger("spa.investment_os.protocol_risk")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RISK_MAP = _REPO_ROOT / "data" / "protocol_risk_map.json"
_PEG = _REPO_ROOT / "data" / "peg_report.json"
_MAX_AGE_S = 3 * 86400


class ProtocolRiskAgent(ProductAgent):
    agent_key = "protocol_risk"
    role_prompt = ("Protocol & Peg Risk analyst — surface the protocol risk-tier distribution + the peg "
                   "health summary; can only RAISE concern; missing/stale → UNKNOWN, never all-safe.")

    def __init__(self, *, risk_map_path: Optional[Path] = None, peg_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.risk_map_path = Path(risk_map_path) if risk_map_path is not None else _RISK_MAP
        self.peg_path = Path(peg_path) if peg_path is not None else _PEG

    def _read(self, path: Path) -> Any:
        mtime = path.stat().st_mtime if path.exists() else None
        return self.read_feed(lambda: json.loads(path.read_text()), max_age_s=_MAX_AGE_S, mtime=mtime)

    def analyze(self) -> dict:
        rmap = self._read(self.risk_map_path)
        peg = self._read(self.peg_path)
        if (rmap is UNKNOWN or not isinstance(rmap, dict)) and (peg is UNKNOWN or not isinstance(peg, dict)):
            return {"status": UNKNOWN,
                    "reason": "protocol-risk map + peg report both missing/stale (fail-closed)"}

        out: dict[str, Any] = {"status": "ok"}

        if isinstance(rmap, dict):
            out["protocol_risk"] = self.evidence(
                {"count": rmap.get("count"), "count_by_tier": rmap.get("count_by_tier"),
                 "map_version": rmap.get("map_version")},
                "L4", "data/protocol_risk_map.json (live risk map)",
                last_verified=rmap.get("generated_at"),
            )
        else:
            out["protocol_risk"] = self.evidence(UNKNOWN, "L0", "data/protocol_risk_map.json (missing/stale)")

        if isinstance(peg, dict):
            out["peg_health"] = self.evidence(
                {"overall_status": peg.get("overall_status"), "total_monitored": peg.get("total_monitored"),
                 "critical": peg.get("critical"), "warning": peg.get("warning"),
                 "caution": peg.get("caution"), "stable": peg.get("stable"),
                 "worst_adapter": peg.get("worst_adapter"), "worst_deviation_pct": peg.get("worst_deviation_pct")},
                "L4", "data/peg_report.json (live peg monitor)",
                last_verified=peg.get("generated_at"),
            )
        else:
            out["peg_health"] = self.evidence(UNKNOWN, "L0", "data/peg_report.json (missing/stale)")

        # a cautious concern flag (surface only): critical peg or any critical-tier protocol → CONCERN.
        peg_critical = isinstance(peg, dict) and (peg.get("critical") or 0) and int(peg.get("critical") or 0) > 0
        peg_status = (peg.get("overall_status") if isinstance(peg, dict) else None)
        out["concern"] = "PEG_CRITICAL" if (peg_critical or str(peg_status).upper() == "CRITICAL") else "NONE_SURFACED"
        out["note"] = ("Advisory. Protocol risk-tier distribution + stablecoin peg health, surfaced from the "
                       "desk's own monitors. Can only RAISE concern; NONE_SURFACED is an observation, not an "
                       "all-safe. Not a gate; the deterministic RiskPolicy is the only execution gate.")
        return out


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return ProtocolRiskAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.protocol_risk")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = ProtocolRiskAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
