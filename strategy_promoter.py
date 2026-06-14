"""
Strategy Auto-Promoter (MP-638)
================================
Evaluates shadow strategies and recommends promotion to paper trading.

Decision logic:
    REJECT  — fails any hard gate (apy < min_apy OR drawdown > max_drawdown)
    PROMOTE — passes all criteria AND score ≥ 60
    HOLD    — passes hard gates but score < 60 or soft criteria unmet

Score formula (0–100):
    (paper_apy / 0.10) * 40   — APY component (max 40 pts)
    (sharpe   / 2.0)  * 30   — Sharpe component (max 30 pts)
    (1 - max_drawdown / 0.10) * 20   — Drawdown component (max 20 pts)
    min(days_running / 30, 1) * 10   — Maturity component (max 10 pts)

Output ring-buffer (50 entries): data/promotion_decisions.json

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never modifies risk/, execution/, allocator/, cycle_runner.
* Atomic writes: tmp + os.replace.
* Deterministic: identical input → identical output.
* NOT imported by risk / execution / monitoring / allocator / cycle_runner.

CLI
---
``python3 -m spa_core.analytics.strategy_promoter --check``
``python3 -m spa_core.analytics.strategy_promoter --run``
``python3 -m spa_core.analytics.strategy_promoter --data-dir PATH``

MP-638.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_OUTPUT_FILE = "promotion_decisions.json"
_RING_BUFFER_MAX = 50

_ADVISORY = (
    "Promotion decisions are advisory recommendations only. "
    "Human review required before any strategy is activated in paper trading."
)

_SCORE_APY_DIVISOR: float = 0.10
_SCORE_APY_WEIGHT: float = 40.0
_SCORE_SHARPE_DIVISOR: float = 2.0
_SCORE_SHARPE_WEIGHT: float = 30.0
_SCORE_DD_DIVISOR: float = 0.10
_SCORE_DD_WEIGHT: float = 20.0
_SCORE_DAYS_DIVISOR: float = 30.0
_SCORE_DAYS_WEIGHT: float = 10.0
_PROMOTE_THRESHOLD: float = 60.0


# ---------------------------------------------------------------------------
# Dataclasses / Criteria
# ---------------------------------------------------------------------------

@dataclass
class PromotionCriteria:
    days_running: int = 7
    min_apy: float = 0.045
    max_drawdown: float = 0.05
    min_sharpe: float = 0.5


DEFAULT_CRITERIA = PromotionCriteria(
    days_running=7,
    min_apy=0.045,
    max_drawdown=0.05,
    min_sharpe=0.5,
)


@dataclass
class PromotionDecision:
    strategy_id: str
    strategy_name: str
    decision: str          # "PROMOTE" | "HOLD" | "REJECT"
    reasons: list[str]
    score: float
    days_running: int
    paper_apy: float
    sharpe: float
    max_drawdown: float
    timestamp: str         # ISO UTC

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "decision": self.decision,
            "reasons": self.reasons,
            "score": round(self.score, 4),
            "days_running": self.days_running,
            "paper_apy": round(self.paper_apy, 6),
            "sharpe": round(self.sharpe, 4),
            "max_drawdown": round(self.max_drawdown, 6),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PromotionDecision":
        return cls(
            strategy_id=str(d["strategy_id"]),
            strategy_name=str(d["strategy_name"]),
            decision=str(d["decision"]),
            reasons=list(d.get("reasons", [])),
            score=float(d["score"]),
            days_running=int(d["days_running"]),
            paper_apy=float(d["paper_apy"]),
            sharpe=float(d["sharpe"]),
            max_drawdown=float(d["max_drawdown"]),
            timestamp=str(d["timestamp"]),
        )


# ---------------------------------------------------------------------------
# StrategyPromoter
# ---------------------------------------------------------------------------

class StrategyPromoter:
    """Evaluates shadow strategies and produces PROMOTE/HOLD/REJECT decisions."""

    def __init__(
        self,
        criteria: PromotionCriteria = DEFAULT_CRITERIA,
        data_dir: str | Path = _DEFAULT_DATA_DIR,
    ) -> None:
        self._criteria = criteria
        self._data_dir = Path(data_dir)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_strategy_data(self) -> list[dict]:
        """Load strategy performance data.

        Priority:
          1. data/strategy_shadow_comparison.json
          2. data/strategy_tournament.json
          3. data/tournament_results.json
          4. synthetic S0–S5 fallback
        """
        for filename in (
            "strategy_shadow_comparison.json",
            "strategy_tournament.json",
            "tournament_results.json",
        ):
            path = self._data_dir / filename
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        raw = json.load(fh)
                    parsed = _parse_strategy_data(raw)
                    # Return even an empty list — file was found and valid
                    if parsed is not None:
                        return parsed
                except (json.JSONDecodeError, OSError):
                    pass

        return _synthetic_strategy_data()

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def compute_score(
        paper_apy: float,
        sharpe: float,
        max_drawdown: float,
        days_running: int,
    ) -> float:
        """Compute a 0–100 promotion score."""
        apy_component = min(paper_apy / _SCORE_APY_DIVISOR, 1.0) * _SCORE_APY_WEIGHT
        sharpe_component = min(sharpe / _SCORE_SHARPE_DIVISOR, 1.0) * _SCORE_SHARPE_WEIGHT
        dd_normalized = max(0.0, 1.0 - max_drawdown / _SCORE_DD_DIVISOR)
        dd_component = dd_normalized * _SCORE_DD_WEIGHT
        maturity = min(days_running / _SCORE_DAYS_DIVISOR, 1.0) * _SCORE_DAYS_WEIGHT

        raw = apy_component + sharpe_component + dd_component + maturity
        return max(0.0, min(100.0, raw))

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def evaluate_strategy(
        self,
        strategy_id: str,
        name: str,
        paper_apy: float,
        sharpe: float,
        max_drawdown: float,
        days_running: int,
    ) -> PromotionDecision:
        """Evaluate a single strategy and return a PromotionDecision."""
        c = self._criteria
        reasons: list[str] = []
        hard_fail = False

        # --- Hard gates (REJECT triggers) ---
        if paper_apy < c.min_apy:
            reasons.append(
                f"APY {paper_apy:.2%} < min {c.min_apy:.2%} [FAIL]"
            )
            hard_fail = True
        else:
            reasons.append(
                f"APY {paper_apy:.2%} >= min {c.min_apy:.2%} [PASS]"
            )

        if max_drawdown > c.max_drawdown:
            reasons.append(
                f"Drawdown {max_drawdown:.2%} > max {c.max_drawdown:.2%} [FAIL]"
            )
            hard_fail = True
        else:
            reasons.append(
                f"Drawdown {max_drawdown:.2%} <= max {c.max_drawdown:.2%} [PASS]"
            )

        if hard_fail:
            score = self.compute_score(paper_apy, sharpe, max_drawdown, days_running)
            return PromotionDecision(
                strategy_id=strategy_id,
                strategy_name=name,
                decision="REJECT",
                reasons=reasons,
                score=score,
                days_running=days_running,
                paper_apy=paper_apy,
                sharpe=sharpe,
                max_drawdown=max_drawdown,
                timestamp=_now_iso(),
            )

        # --- Soft criteria (affect PROMOTE vs HOLD) ---
        all_soft_pass = True

        if sharpe >= c.min_sharpe:
            reasons.append(
                f"Sharpe {sharpe:.2f} >= min {c.min_sharpe:.2f} [PASS]"
            )
        else:
            reasons.append(
                f"Sharpe {sharpe:.2f} < min {c.min_sharpe:.2f} [FAIL]"
            )
            all_soft_pass = False

        if days_running >= c.days_running:
            reasons.append(
                f"Days running {days_running} >= min {c.days_running} [PASS]"
            )
        else:
            reasons.append(
                f"Days running {days_running} < min {c.days_running} [FAIL]"
            )
            all_soft_pass = False

        score = self.compute_score(paper_apy, sharpe, max_drawdown, days_running)

        if all_soft_pass and score >= _PROMOTE_THRESHOLD:
            decision = "PROMOTE"
        else:
            decision = "HOLD"
            if not all_soft_pass:
                reasons.append(
                    "HOLD: one or more soft criteria not yet met"
                )
            if score < _PROMOTE_THRESHOLD:
                reasons.append(
                    f"HOLD: score {score:.1f} < threshold {_PROMOTE_THRESHOLD}"
                )

        return PromotionDecision(
            strategy_id=strategy_id,
            strategy_name=name,
            decision=decision,
            reasons=reasons,
            score=score,
            days_running=days_running,
            paper_apy=paper_apy,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            timestamp=_now_iso(),
        )

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def evaluate_all(self) -> list[PromotionDecision]:
        """Evaluate all strategies from loaded data."""
        strategies = self._load_strategy_data()
        decisions: list[PromotionDecision] = []

        for s in strategies:
            sid = str(s.get("strategy_id", "unknown"))
            name = str(s.get("strategy_name", sid))
            paper_apy = _safe_float(s.get("paper_apy", s.get("apy", 0.0)))
            sharpe = _safe_float(s.get("sharpe", s.get("sharpe_ratio", 0.0)))
            max_dd = _safe_float(s.get("max_drawdown", s.get("drawdown", 0.0)))
            days = int(_safe_float(s.get("days_running", s.get("days", 0))))
            decisions.append(
                self.evaluate_strategy(sid, name, paper_apy, sharpe, max_dd, days)
            )

        return decisions

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def log_decisions(self, decisions: list[PromotionDecision]) -> None:
        """Append batch to ring-buffer in data/promotion_decisions.json."""
        out_path = self._data_dir / _OUTPUT_FILE
        self._data_dir.mkdir(parents=True, exist_ok=True)

        existing: list[dict] = []
        if out_path.exists():
            try:
                with open(out_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []

        for d in decisions:
            existing.append(d.to_dict())

        if len(existing) > _RING_BUFFER_MAX:
            existing = existing[-_RING_BUFFER_MAX:]

        _atomic_write(out_path, existing)

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def generate_report(self) -> dict:
        """Generate a full promotion report."""
        decisions = self.evaluate_all()

        promote = [d for d in decisions if d.decision == "PROMOTE"]
        hold = [d for d in decisions if d.decision == "HOLD"]
        reject = [d for d in decisions if d.decision == "REJECT"]

        top_candidate: Optional[dict] = None
        if decisions:
            best = max(decisions, key=lambda d: d.score)
            top_candidate = best.to_dict()

        return {
            "decisions": [d.to_dict() for d in decisions],
            "promote_count": len(promote),
            "hold_count": len(hold),
            "reject_count": len(reject),
            "top_candidate": top_candidate,
            "advisory": _ADVISORY,
            "generated_at": _now_iso(),
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_strategy_promoter_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _parse_strategy_data(raw: object) -> list[dict]:
    """Normalise various JSON shapes into a flat list of strategy dicts."""
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)]
    if isinstance(raw, dict):
        # Tournament results format: {strategies: [...]} or {results: [...]}
        for key in ("strategies", "results", "rankings"):
            if key in raw and isinstance(raw[key], list):
                return [s for s in raw[key] if isinstance(s, dict)]
        # Flat dict keyed by strategy_id
        result = []
        for sid, info in raw.items():
            if isinstance(info, dict):
                entry = dict(info)
                entry.setdefault("strategy_id", sid)
                result.append(entry)
        return result
    return []


def _synthetic_strategy_data() -> list[dict]:
    """Fallback synthetic data for S0–S5."""
    return [
        {"strategy_id": "S0", "strategy_name": "Conservative Yield",   "paper_apy": 0.032, "sharpe": 1.8,  "max_drawdown": 0.008, "days_running": 14},
        {"strategy_id": "S1", "strategy_name": "Balanced Growth",      "paper_apy": 0.051, "sharpe": 1.2,  "max_drawdown": 0.025, "days_running": 21},
        {"strategy_id": "S2", "strategy_name": "Aggressive Yield",     "paper_apy": 0.078, "sharpe": 0.9,  "max_drawdown": 0.062, "days_running": 9},
        {"strategy_id": "S3", "strategy_name": "T1 Only",              "paper_apy": 0.046, "sharpe": 2.1,  "max_drawdown": 0.012, "days_running": 30},
        {"strategy_id": "S4", "strategy_name": "Diversified T1/T2",    "paper_apy": 0.055, "sharpe": 1.5,  "max_drawdown": 0.034, "days_running": 18},
        {"strategy_id": "S5", "strategy_name": "High Sharpe Min Risk",  "paper_apy": 0.049, "sharpe": 2.4,  "max_drawdown": 0.018, "days_running": 45},
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv

    data_dir = _DEFAULT_DATA_DIR
    do_run = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--run":
            do_run = True
        elif arg == "--check":
            do_run = False
        elif arg == "--data-dir" and i + 1 < len(args):
            i += 1
            data_dir = Path(args[i])
        i += 1

    promoter = StrategyPromoter(data_dir=data_dir)
    report = promoter.generate_report()

    print(json.dumps(report, indent=2))

    if do_run:
        decisions = [PromotionDecision.from_dict(d) for d in report["decisions"]]
        promoter.log_decisions(decisions)
        out = Path(data_dir) / _OUTPUT_FILE
        print(f"\n[strategy_promoter] Saved → {out}", file=sys.stderr)
    else:
        print("\n[strategy_promoter] --check mode: no file written.", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    main()
