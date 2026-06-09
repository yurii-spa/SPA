"""
SPA-V387 — Go-Live Readiness Checker.

Evaluates every criterion defined in ``criteria.py`` against the data files the
paper-trading / adapter / risk subsystems already emit, then rolls the per-
criterion results into a single READY / CONDITIONAL / NOT_READY verdict plus a
weighted readiness score.

PURE READ-ONLY ANALYTICS. This module:
  * reads ``data/*.json`` files and checks for the presence of repo files;
  * NEVER writes to capital-touching surfaces, never imports execution/ or risk
    agents, never mutates any data file (the report writer does the only write);
  * NEVER raises out of ``check_all`` — every individual check is guarded and a
    missing/garbled source yields a SKIP, not an exception.

Status vocabulary per criterion:
  * ``PASS`` — criterion satisfied.
  * ``WARN`` — soft concern (e.g. negative Sharpe); counts as half credit.
  * ``FAIL`` — criterion violated.
  * ``SKIP`` — required data not available; excluded from the score denominator.

Verdict logic:
  * ``READY``       — every blocker criterion PASS and score ≥ 0.75.
  * ``CONDITIONAL`` — every blocker criterion PASS and 0.50 ≤ score < 0.75.
  * ``NOT_READY``   — at least one blocker criterion FAIL (or score < 0.50).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from spa_core.golive.criteria import CRITERIA, CRITERIA_BY_ID, WEIGHT_POINTS

# ─── Constants ──────────────────────────────────────────────────────────────────
SPA_DIR = Path(__file__).resolve().parents[2]

GO_LIVE_DATE = "2026-07-15"
PAPER_START_DATE = "2026-05-20"
MIN_PAPER_DAYS = 30
MIN_TRADING_DAYS = 20
MIN_WIN_RATE_PCT = 40.0
MAX_DRAWDOWN_PCT = 5.0
MAX_CURRENT_DRAWDOWN_PCT = 10.0
MIN_SPRINT_COMPLETED = 3.80  # "v3.80"
MIN_ADAPTERS_WITH_APY = 2

# Score thresholds for the verdict bands.
READY_SCORE = 0.75
CONDITIONAL_SCORE = 0.50

# Per-status fraction of a criterion's weight that counts as "earned".
_STATUS_CREDIT = {"PASS": 1.0, "WARN": 0.5, "FAIL": 0.0}


@dataclass
class _Result:
    """Internal per-criterion result before serialisation."""

    id: str
    name: str
    category: str
    weight: str
    status: str
    detail: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "weight": self.weight,
            "status": self.status,
            "detail": self.detail,
        }


class ReadinessChecker:
    """Evaluates all go-live criteria and produces a consolidated verdict."""

    def __init__(self, spa_dir: Path = SPA_DIR, today: date | None = None) -> None:
        self.spa_dir = Path(spa_dir)
        self.data_dir = self.spa_dir / "data"
        # ``today`` is injectable so duration/countdown maths is deterministic in tests.
        self.today = today or datetime.now(timezone.utc).date()

    # ── public API ──────────────────────────────────────────────────────────────
    def check_all(self) -> dict:
        """Run every criterion and return the full readiness report dict."""
        results: list[_Result] = []
        results.extend(self._check_paper_trading())
        results.extend(self._check_adapters())
        results.extend(self._check_risk())
        results.extend(self._check_infrastructure())

        # Preserve the canonical catalogue order.
        order = {c.id: i for i, c in enumerate(CRITERIA)}
        results.sort(key=lambda r: order.get(r.id, 999))

        score = self._score(results)
        blockers = [r.as_dict() for r in results
                    if r.weight == "blocker" and r.status == "FAIL"]
        warnings = [r.as_dict() for r in results if r.status == "WARN"]
        passed = [r.as_dict() for r in results if r.status == "PASS"]
        skipped = [r.as_dict() for r in results if r.status == "SKIP"]

        verdict = self._verdict(results, score)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "verdict": verdict,
            "score": round(score, 4),
            "go_live_date": GO_LIVE_DATE,
            "paper_start_date": PAPER_START_DATE,
            "days_to_golive": self._days_to_golive(),
            "num_criteria": len(results),
            "num_passed": len(passed),
            "num_failed": sum(1 for r in results if r.status == "FAIL"),
            "num_warnings": len(warnings),
            "num_skipped": len(skipped),
            "criteria": [r.as_dict() for r in results],
            "blockers": blockers,
            "warnings": warnings,
            "passed": passed,
            "skipped": skipped,
        }

    def _days_to_golive(self) -> int:
        return (date.fromisoformat(GO_LIVE_DATE) - self.today).days

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _read_json(self, name: str):
        """Read data/<name>; return parsed object or None on any problem."""
        path = self.data_dir / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _r(cid: str, status: str, detail: str) -> _Result:
        c = CRITERIA_BY_ID[cid]
        return _Result(c.id, c.name, c.category, c.weight, status, detail)

    # ── category checks ─────────────────────────────────────────────────────────
    def _check_paper_trading(self) -> list[_Result]:
        out: list[_Result] = []
        rm = self._read_json("risk_metrics.json") or {}
        metrics = rm.get("metrics", {}) if isinstance(rm, dict) else {}
        dd = self._read_json("drawdown_analysis.json") or {}
        eq = self._read_json("equity_curve_daily.json") or {}

        # C001 — paper trading duration ≥ 30 days.
        try:
            elapsed = (self.today - date.fromisoformat(PAPER_START_DATE)).days
            if elapsed >= MIN_PAPER_DAYS:
                out.append(self._r("C001", "PASS",
                                   f"{elapsed} days elapsed (≥ {MIN_PAPER_DAYS})"))
            else:
                out.append(self._r("C001", "FAIL",
                                   f"{elapsed}/{MIN_PAPER_DAYS} days elapsed"))
        except ValueError:
            out.append(self._r("C001", "SKIP", "invalid paper start date"))

        # C002 — win rate ≥ 40%.
        wr = metrics.get("win_rate_pct")
        if wr is None:
            out.append(self._r("C002", "SKIP", "win_rate_pct unavailable"))
        elif wr >= MIN_WIN_RATE_PCT:
            out.append(self._r("C002", "PASS", f"{wr:.1f}% (≥ {MIN_WIN_RATE_PCT:.0f}%)"))
        else:
            out.append(self._r("C002", "FAIL", f"{wr:.1f}% (< {MIN_WIN_RATE_PCT:.0f}%)"))

        # C003 — max drawdown ≤ 5%.
        mdd = metrics.get("max_drawdown_pct")
        if mdd is None:
            mdd = (dd.get("summary", {}) or {}).get("max_drawdown_pct") if isinstance(dd, dict) else None
        if mdd is None:
            out.append(self._r("C003", "SKIP", "max_drawdown_pct unavailable"))
        elif abs(mdd) <= MAX_DRAWDOWN_PCT:
            out.append(self._r("C003", "PASS", f"{abs(mdd):.2f}% (≤ {MAX_DRAWDOWN_PCT:.0f}%)"))
        else:
            out.append(self._r("C003", "FAIL", f"{abs(mdd):.2f}% (> {MAX_DRAWDOWN_PCT:.0f}%)"))

        # C004 — Sharpe ratio computed (any sign; negative is WARN).
        sharpe = metrics.get("sharpe_ratio")
        if sharpe is None:
            out.append(self._r("C004", "SKIP", "sharpe_ratio not computed"))
        elif sharpe >= 0:
            out.append(self._r("C004", "PASS", f"Sharpe = {sharpe:.2f}"))
        else:
            out.append(self._r("C004", "WARN",
                               f"Sharpe = {sharpe:.2f} (negative — strategy needs review)"))

        # C005 — trading days ≥ 20.
        days = None
        if isinstance(eq, dict):
            days = (eq.get("summary", {}) or {}).get("num_days")
        if days is None:
            days = metrics.get("num_return_days")
        if days is None:
            out.append(self._r("C005", "SKIP", "trading-day count unavailable"))
        elif days >= MIN_TRADING_DAYS:
            out.append(self._r("C005", "PASS", f"{days} trading days (≥ {MIN_TRADING_DAYS})"))
        else:
            out.append(self._r("C005", "FAIL", f"{days}/{MIN_TRADING_DAYS} trading days"))

        return out

    def _check_adapters(self) -> list[_Result]:
        out: list[_Result] = []
        status = self._read_json("adapter_orchestrator_status.json")
        runs = self._read_json("orchestrator_runs.json")

        # C006 — at least 2 adapters with APY > 0.
        if not isinstance(status, dict) or not isinstance(status.get("adapters"), list):
            out.append(self._r("C006", "SKIP", "adapter status unavailable"))
        else:
            positive = [a for a in status["adapters"]
                        if isinstance(a, dict) and (a.get("apy_pct") or 0) > 0]
            if len(positive) >= MIN_ADAPTERS_WITH_APY:
                out.append(self._r("C006", "PASS",
                                   f"{len(positive)} adapters with APY > 0"))
            else:
                out.append(self._r("C006", "FAIL",
                                   f"only {len(positive)} adapter(s) with APY > 0"))

        # C007 — orchestrator ran ≥ 1 time.
        run_list = runs.get("runs") if isinstance(runs, dict) else None
        if run_list is None:
            out.append(self._r("C007", "SKIP", "orchestrator_runs.json missing"))
        elif len(run_list) >= 1:
            out.append(self._r("C007", "PASS", f"{len(run_list)} recorded run(s)"))
        else:
            out.append(self._r("C007", "FAIL", "no recorded orchestrator runs"))

        # C008 — overall health grade ≠ F.
        grade = None
        if isinstance(status, dict):
            grade = (status.get("overall_health", {}) or {}).get("grade")
        if grade is None and isinstance(runs, dict) and run_list:
            grade = (run_list[-1].get("overall_health", {}) or {}).get("grade")
        if grade is None:
            out.append(self._r("C008", "SKIP", "health grade unavailable (orchestrator not run)"))
        elif str(grade).upper() != "F":
            out.append(self._r("C008", "PASS", f"grade = {grade}"))
        else:
            out.append(self._r("C008", "FAIL", "grade = F"))

        return out

    def _check_risk(self) -> list[_Result]:
        out: list[_Result] = []
        rd = self._read_json("return_distribution.json")
        dd = self._read_json("drawdown_analysis.json") or {}

        # C009 — VaR95 computed (5th-percentile of the return distribution).
        var95 = None
        if isinstance(rd, dict):
            dist = rd.get("distribution", {}) or {}
            var95 = (dist.get("percentiles", {}) or {}).get("p5")
        if var95 is None:
            out.append(self._r("C009", "SKIP", "return_distribution.json missing / no p5"))
        else:
            out.append(self._r("C009", "PASS", f"VaR95 (p5) = {var95:.2f}%"))

        # C010 — no current drawdown > 10%.
        cur = None
        if isinstance(dd, dict):
            cur = (dd.get("summary", {}) or {}).get("current_drawdown_pct")
        if cur is None:
            out.append(self._r("C010", "SKIP", "current_drawdown_pct unavailable"))
        elif abs(cur) <= MAX_CURRENT_DRAWDOWN_PCT:
            out.append(self._r("C010", "PASS",
                               f"current drawdown {abs(cur):.2f}% (≤ {MAX_CURRENT_DRAWDOWN_PCT:.0f}%)"))
        else:
            out.append(self._r("C010", "FAIL",
                               f"current drawdown {abs(cur):.2f}% (> {MAX_CURRENT_DRAWDOWN_PCT:.0f}%)"))

        return out

    def _check_infrastructure(self) -> list[_Result]:
        out: list[_Result] = []

        # C011 — push_to_github.py present.
        if (self.spa_dir / "push_to_github.py").exists():
            out.append(self._r("C011", "PASS", "push_to_github.py present"))
        else:
            out.append(self._r("C011", "FAIL", "push_to_github.py missing"))

        # C012 — auto_push.py present.
        if (self.spa_dir / "auto_push.py").exists():
            out.append(self._r("C012", "PASS", "auto_push.py present"))
        else:
            out.append(self._r("C012", "FAIL", "auto_push.py missing"))

        # C013 — KANBAN sprint_completed ≥ v3.80.
        kanban = self._read_json_root("KANBAN.json")
        sprint = kanban.get("sprint_completed") if isinstance(kanban, dict) else None
        ver = self._parse_sprint(sprint)
        if ver is None:
            out.append(self._r("C013", "SKIP", "sprint_completed unreadable"))
        elif ver >= MIN_SPRINT_COMPLETED:
            out.append(self._r("C013", "PASS", f"sprint_completed = {sprint} (≥ v3.80)"))
        else:
            out.append(self._r("C013", "FAIL", f"sprint_completed = {sprint} (< v3.80)"))

        return out

    def _read_json_root(self, name: str):
        """Read a JSON file at the project root (not under data/)."""
        path = self.spa_dir / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _parse_sprint(value) -> float | None:
        """Parse a sprint label like 'v3.85' → 3.85; return None if unparseable."""
        if value is None:
            return None
        text = str(value).strip().lstrip("vV")
        try:
            return float(text)
        except ValueError:
            return None

    # ── scoring & verdict ───────────────────────────────────────────────────────
    @staticmethod
    def _score(results: list[_Result]) -> float:
        """Weighted score in [0, 1]. SKIP is excluded from the denominator."""
        earned = 0.0
        total = 0.0
        for r in results:
            if r.status == "SKIP":
                continue
            w = WEIGHT_POINTS.get(r.weight, 1.0)
            total += w
            earned += w * _STATUS_CREDIT.get(r.status, 0.0)
        if total == 0:
            return 0.0
        return earned / total

    @staticmethod
    def _verdict(results: list[_Result], score: float) -> str:
        blocker_fail = any(r.weight == "blocker" and r.status == "FAIL" for r in results)
        if blocker_fail or score < CONDITIONAL_SCORE:
            return "NOT_READY"
        if score >= READY_SCORE:
            return "READY"
        return "CONDITIONAL"
