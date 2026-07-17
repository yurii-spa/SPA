"""spa_core/investment_os/agents/quant.py — Quant & Backtesting analyst (AI Investment OS, docs/08).

RESHAPE, not rebuild. The desk already measures whether its BACKTEST predicts the live PAPER track
(data/backtest_vs_paper.json — rank correlation, confidence, paper-day count). This analyst CONSUMES that
into ONE advisory model-trust view: does the model actually predict reality? A low backtest↔paper rank
correlation means the model is untrustworthy — a critical honesty signal (never trust a backtest that
doesn't hold up out-of-sample). Evidence-tagged, fail-CLOSED to UNKNOWN.

Boundaries (harness): IS_ADVISORY — reads only, writes only data/investment_os/quant.json; never allocates,
never touches RiskPolicy/kill/live track. Deterministic.

CLI::  python3 -m spa_core.investment_os.agents.quant [--check]
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

log = logging.getLogger("spa.investment_os.quant")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BT_VS_PAPER = _REPO_ROOT / "data" / "backtest_vs_paper.json"

# rank-correlation below this → the backtest does NOT reliably predict the paper track (concern).
_WEAK_CORRELATION = 0.7   # GoLive threshold ρ≥0.70 (docs / backtest_paper_correlation)


class QuantBacktestAgent(ProductAgent):
    agent_key = "quant"
    role_prompt = ("Quant & Backtesting analyst — does the BACKTEST predict the live PAPER track? Surface "
                   "the rank correlation + confidence; a low correlation means the model is untrustworthy.")

    def __init__(self, *, bt_path: Optional[Path] = None,
                 data_dir: Optional[str | Path] = None, allow_llm: bool = True) -> None:
        super().__init__(data_dir=data_dir, allow_llm=allow_llm)
        self.bt_path = Path(bt_path) if bt_path is not None else _BT_VS_PAPER

    def analyze(self) -> dict:
        data = self.read_feed(lambda: json.loads(self.bt_path.read_text()))
        if data is UNKNOWN or not isinstance(data, dict):
            return {"status": UNKNOWN, "reason": "backtest-vs-paper measurement missing (fail-closed)"}

        rho = data.get("rank_correlation")
        paper_days = data.get("paper_days")
        # model-trust concern ladder (surface only, never a gate)
        concern = "NONE_SURFACED"
        if isinstance(rho, (int, float)):
            if rho < _WEAK_CORRELATION:
                concern = "WEAK_MODEL_FIT"
        elif isinstance(paper_days, (int, float)) and paper_days < 30:
            concern = "INSUFFICIENT_PAPER_DAYS"   # not enough live days to judge the model yet

        n_strats = len(data.get("strategies") or []) if isinstance(data.get("strategies"), (list, dict)) else None

        return {
            "status": "ok",
            "concern": concern,
            "model_trust": self.evidence(
                {
                    "rank_correlation": rho,
                    "confidence": data.get("confidence"),
                    "paper_days": paper_days,
                    "n_strategies": n_strats,
                    "summary": data.get("summary"),
                    "threshold_rho": _WEAK_CORRELATION,
                },
                "L5", "data/backtest_vs_paper.json (backtest↔paper correlation)",
                last_verified=data.get("generated_at"),
            ),
            "note": ("Advisory. Does the BACKTEST predict the live PAPER track (rank correlation ρ)? "
                     "ρ≥0.70 = the model holds out-of-sample; below that the model is untrustworthy "
                     "(WEAK_MODEL_FIT). Fewer than 30 paper days = not enough to judge yet. Surfaces the "
                     "desk's own measurement; can only RAISE concern; not a gate."),
        }


def run(*, now: Optional[datetime] = None, data_dir: Optional[str | Path] = None) -> Path:
    return QuantBacktestAgent(data_dir=data_dir).run(now=now)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.investment_os.agents.quant")
    ap.add_argument("--check", action="store_true", help="analyze + print, do NOT write artifact")
    args = ap.parse_args(argv)
    agent = QuantBacktestAgent()
    if args.check:
        print(json.dumps(agent.analyze(), ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {agent.run()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
