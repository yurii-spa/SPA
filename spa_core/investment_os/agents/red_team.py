"""spa_core/investment_os/agents/red_team.py — Red Team analyst (AI Investment OS, docs/08).

RESHAPE, not rebuild. The desk already RUNS an adversarial layer (spa_core/redteam/ + the threat-reactor)
that writes data/threat_reactor_status.json + data/attack_simulation_log.json. This analyst CONSUMES that
output into ONE advisory threat-posture view for the product layer, evidence-tagged.

Design (docs/08 Red Team Agent): it can only ever RAISE a concern — it NEVER emits an approval or a
"safe to allocate" signal. Fail-CLOSED: missing/stale threat data → UNKNOWN posture (treated as NOT clear,
cautious), never an all-clear by default. Advisory only — writes data/investment_os/red_team.json; never
allocates, never touches RiskPolicy/kill/live track.

CLI::  python3 -m spa_core.investment_os.agents.red_team [--check]
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

log = logging.getLogger("spa.investment_os.red_team")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_THREAT = _REPO_ROOT / "data" / "threat_reactor_status.json"
_ATTACK = _REPO_ROOT / "data" / "attack_simulation_log.json"
_MAX_AGE_S = 2 * 86400   # threat data must be recent to be trusted; stale → cautious UNKNOWN


class RedTeamAgent(ProductAgent):
    agent_key = "red_team"
    role_prompt = ("Red Team analyst — surface the adversarial threat posture; can only RAISE concerns, "
                   "NEVER approve; stale/missing threat data → UNKNOWN (cautious), never all-clear.")

    def __init__(self, *, threat_path: Optional[Path] = None, attack_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.threat_path = Path(threat_path) if threat_path is not None else _THREAT
        self.attack_path = Path(attack_path) if attack_path is not None else _ATTACK

    def _read(self, path: Path, *, gate_age: bool = True) -> Any:
        mtime = path.stat().st_mtime if path.exists() else None
        return self.read_feed(lambda: json.loads(path.read_text()),
                              max_age_s=_MAX_AGE_S if gate_age else None, mtime=mtime)

    def analyze(self) -> dict:
        threat = self._read(self.threat_path)
        if threat is UNKNOWN or not isinstance(threat, dict):
            # fail-CLOSED: no trustworthy threat data → cautious UNKNOWN, NEVER a default all-clear.
            return {"status": UNKNOWN, "posture": "UNKNOWN_CAUTIOUS",
                    "reason": "threat-reactor status missing/stale — cannot assert all-clear (fail-closed)"}

        threats = threat.get("threats") or []
        clear = bool(threat.get("clear")) and not threats
        kill_active = bool(threat.get("kill_switch_already_active"))

        # latest attack-simulation summary (list; take newest by timestamp)
        attack = self._read(self.attack_path, gate_age=False)
        critical_count = None
        avg_security = None
        most_vulnerable = None
        if isinstance(attack, list) and attack:
            latest = max(attack, key=lambda r: r.get("timestamp", 0) if isinstance(r, dict) else 0)
            if isinstance(latest, dict):
                critical_count = latest.get("critical_count")
                avg_security = latest.get("average_security_score")
                most_vulnerable = latest.get("most_vulnerable")

        # posture ladder — the analyst can only escalate concern; it never emits "approved".
        if kill_active or (isinstance(critical_count, (int, float)) and critical_count > 0):
            posture = "CRITICAL"
        elif threats:
            posture = "THREATS_PRESENT"
        elif clear:
            posture = "NO_THREAT_OBSERVED"   # an observation, NOT an approval to allocate
        else:
            posture = "UNKNOWN_CAUTIOUS"

        return {
            "status": "ok",
            "posture": posture,
            "threat_posture": self.evidence(
                {"clear": clear, "n_threats": len(threats), "threats": threats,
                 "kill_switch_already_active": kill_active},
                "L4", "data/threat_reactor_status.json (live threat-reactor)",
                last_verified=threat.get("ts"),
            ),
            "attack_surface": self.evidence(
                {"critical_count": critical_count, "average_security_score": avg_security,
                 "most_vulnerable": most_vulnerable},
                "L3", "data/attack_simulation_log.json (adversarial sim)",
            ),
            "note": ("Advisory. Red-team posture — this analyst can only RAISE concerns; it NEVER approves "
                     "or signals 'safe to allocate'. NO_THREAT_OBSERVED is an observation, not a green "
                     "light. Missing/stale threat data → UNKNOWN_CAUTIOUS (fail-closed)."),
        }


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return RedTeamAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.red_team")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = RedTeamAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
