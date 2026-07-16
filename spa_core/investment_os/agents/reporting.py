"""spa_core/investment_os/agents/reporting.py — Reporting analyst (AI Investment OS, docs/08).

Consumes the desk's OWN evidenced track (data/track_ledger.json) and the day-30 review state
(data/riskwire/day30_review.json) and emits ONE honest, evidence-tagged performance + readiness summary
for the product layer. It computes nothing new — it SURFACES the already-evidenced numbers (this is why
its whole job fits the harness cleanly). Fail-CLOSED: no track ledger → UNKNOWN, never a fabricated number.

Boundaries (harness): IS_ADVISORY — reads only, writes only data/investment_os/reporting.json; never
allocates, never touches RiskPolicy/kill/live track. Deterministic.

CLI::  python3 -m spa_core.investment_os.agents.reporting [--check]
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

log = logging.getLogger("spa.investment_os.reporting")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LEDGER = _REPO_ROOT / "data" / "track_ledger.json"
_DAY30 = _REPO_ROOT / "data" / "riskwire" / "day30_review.json"


class ReportingAgent(ProductAgent):
    agent_key = "reporting"
    role_prompt = ("Reporting analyst — surface the desk's OWN evidenced track + review readiness, "
                   "evidence-tagged; never invent a number; UNKNOWN when the track ledger is unavailable.")

    def __init__(self, *, ledger_path: Optional[Path] = None, day30_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.ledger_path = Path(ledger_path) if ledger_path is not None else _LEDGER
        self.day30_path = Path(day30_path) if day30_path is not None else _DAY30

    def _read(self, path: Path) -> Any:
        # No mtime staleness gate here: the Reporting analyst SURFACES the evidenced track, and the L6
        # tag's `last_verified` (= last_evidenced_date) is the honest freshness signal. A file that only
        # updates on a new evidenced day (time-gated waits) must not read as UNKNOWN just for age. A
        # missing/unreadable file still fails CLOSED to UNKNOWN.
        return self.read_feed(lambda: json.loads(path.read_text()))

    def analyze(self) -> dict:
        led = self._read(self.ledger_path)
        if led is UNKNOWN or not isinstance(led, dict) or led.get("n_evidenced_days") is None:
            return {"status": UNKNOWN, "reason": "evidenced track ledger missing/stale (fail-closed)"}

        track = self.evidence(
            {
                "n_evidenced_days": led.get("n_evidenced_days"),
                "days_needed": led.get("days_needed", 30),
                "days_remaining": led.get("days_remaining"),
                "cumulative_return_pct": led.get("cumulative_return_pct"),
                "max_drawdown_from_peak_pct": led.get("max_drawdown_from_peak_pct"),
                "first_evidenced_date": led.get("first_evidenced_date"),
                "last_evidenced_date": led.get("last_evidenced_date"),
            },
            "L6", "data/track_ledger.json (evidenced-only, our own live paper track)",
            last_verified=led.get("last_evidenced_date"),
        )

        out: dict[str, Any] = {"status": "ok", "track": track}

        d30 = self._read(self.day30_path)
        if isinstance(d30, dict):
            out["review_readiness"] = self.evidence(
                {
                    "review_readiness_pct": d30.get("review_readiness_pct"),
                    "state": d30.get("state"),
                    "ready_for_review": d30.get("ready_for_review"),
                    "remaining_days": d30.get("remaining_days"),
                    "min_track_days": d30.get("min_track_days"),
                },
                "L6", "data/riskwire/day30_review.json (inert readiness gate)",
                last_verified=d30.get("generated_at"),
            )
        else:
            out["review_readiness"] = self.evidence(UNKNOWN, "L0", "data/riskwire/day30_review.json (missing/stale)")

        out["note"] = ("Advisory. Surfaces the desk's OWN evidenced paper track + day-30 review readiness "
                       "(evidence L6 — our track). Computes nothing new; every number is from the ledger. "
                       "Paper research — realized to date, variable, not a guarantee.")
        return out


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return ReportingAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.reporting")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = ReportingAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
