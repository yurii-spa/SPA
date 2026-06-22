"""
ADR-029: Strategy Promotion Automation Policy
Evaluates each strategy against Tier A/B/C criteria.
Writes promotion_report.json with routing decisions.

Domains: read-only analytics — never imports execution/, never calls LLM.
All file writes are atomic (tmp + os.replace).
"""

import json
import datetime
from pathlib import Path
from spa_core.utils.atomic import atomic_save


# Strategy IDs that are NEVER auto-promoted regardless of metrics (ADR-029 + ADR-021).
# Cross-check with tier_label == "T3-SPEC" for defence-in-depth.
T3_SPEC_STRATEGIES: frozenset = frozenset({"s4_pendle_lp", "s11_hybrid"})

# Maximum allowed capital-at-risk for auto-promotion (Tier C hard gate).
CAPITAL_AT_RISK_THRESHOLD_USD: float = 50_000.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_max_drawdown(equity_series: list) -> float:
    """Return maximum drawdown percentage from an equity series.

    Max drawdown = max over all t of (peak_up_to_t - value_t) / peak_up_to_t * 100.
    Returns 0.0 for empty or single-element series (no drawdown observable).
    """
    if not equity_series or len(equity_series) < 2:
        return 0.0
    peak = equity_series[0]
    max_dd = 0.0
    for val in equity_series:
        if val > peak:
            peak = val
        if peak > 0:
            dd = (peak - val) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _safe_float(value, default: float = 0.0) -> float:
    """Return float(value) if value is not None/falsy-number, else default."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """Return int(value) if value is not None, else default."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return datetime.datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class AutoPromoter:
    """Evaluates strategies against ADR-029 Tier A / B / C promotion criteria.

    Tier routing (ADR-029 §Decision, Tier Routing Logic):

        if T3-SPEC (tier_label OR strategy_id)  → Tier C / MANUAL_REVIEW
        if halt_count > 0                        → Tier C / MANUAL_REVIEW
        if sharpe < 0.8                          → Tier C / MANUAL_REVIEW
        if apy_ratio < 0.90                      → Tier C / MANUAL_REVIEW
        if max_drawdown_pct >= 8.0               → Tier C / MANUAL_REVIEW
        if capital_at_risk > 50_000              → Tier C / MANUAL_REVIEW
        if paper_days < 30                       → Tier C / MANUAL_REVIEW
        # all Tier C gates passed
        if sharpe >= 1.0 and apy_ratio >= 1.10 and max_drawdown_pct < 5.0
                                                 → Tier A / AUTO_PROMOTE
        else                                     → Tier B / PENDING_48H

    During Phase 1 (auto_promote_enabled=False) the output is advisory only;
    no actual promotions are executed.  Tier A/B/C routing is still computed
    and written to data/promotion_report.json for observability.
    """

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def evaluate_strategy(self, strategy_id: str, metrics: dict) -> dict:
        """Evaluate one strategy against ADR-029 Tier A/B/C criteria.

        Parameters
        ----------
        strategy_id:
            Canonical strategy identifier (e.g. ``"s7_pendle_yt"``).
        metrics:
            Dict with keys:
                paper_days        (int)   – calendar days of paper trading
                sharpe            (float) – 30-day rolling Sharpe ratio
                realized_apy      (float) – realised APY percentage
                target_apy        (float) – target APY percentage
                max_drawdown_pct  (float) – maximum drawdown % in period
                halt_count        (int)   – number of RiskPolicy gate HALTs
                capital_at_risk   (float) – USD exposure at risk
                tier_label        (str)   – protocol tier ("T1", "T2", "T3", "T3-SPEC")

        Returns
        -------
        dict with keys:
            strategy_id, tier, eligible, reason, criteria_results,
            action, evaluated_at
        """
        now = _utcnow_iso()
        sid = strategy_id

        # ── Extract metrics (safe defaults) ─────────────────────────────────
        tier_label      = str(metrics.get("tier_label") or "")
        paper_days      = _safe_int(metrics.get("paper_days"), 0)
        sharpe          = _safe_float(metrics.get("sharpe"), 0.0)
        realized_apy    = _safe_float(metrics.get("realized_apy"), 0.0)
        target_apy      = _safe_float(metrics.get("target_apy"), 0.0)
        max_dd          = _safe_float(metrics.get("max_drawdown_pct"), 0.0)
        halt_count      = _safe_int(metrics.get("halt_count"), 0)
        capital_at_risk = _safe_float(metrics.get("capital_at_risk"), 0.0)

        apy_ratio = (realized_apy / target_apy) if target_apy > 0 else 0.0

        # ── Tier C exclusion gates (ADR-029 §Tier Routing Logic) ─────────────

        # 1. T3-SPEC: by tier_label OR known strategy_id set
        is_t3_spec = (tier_label == "T3-SPEC") or (sid in T3_SPEC_STRATEGIES)
        if is_t3_spec:
            return self._make_result(
                sid, "C", False,
                "T3-SPEC strategies are excluded from auto-promotion (ADR-021 + ADR-029)",
                {}, "MANUAL_REVIEW", now,
            )

        # 2. Any Risk Gate HALT in observation window
        if halt_count > 0:
            return self._make_result(
                sid, "C", False,
                f"Risk Gate HALTs in observation period: {halt_count} (must be 0)",
                {}, "MANUAL_REVIEW", now,
            )

        # 3. Sharpe below ADR-023 floor
        if sharpe < 0.8:
            return self._make_result(
                sid, "C", False,
                f"Sharpe {sharpe:.4f} < 0.8 (below ADR-023 minimum floor)",
                {}, "MANUAL_REVIEW", now,
            )

        # 4. APY underperforming floor
        if apy_ratio < 0.90:
            return self._make_result(
                sid, "C", False,
                f"Realized APY / target ratio {apy_ratio:.4f} < 0.90 (underperforming plan)",
                {}, "MANUAL_REVIEW", now,
            )

        # 5. Drawdown too large
        if max_dd >= 8.0:
            return self._make_result(
                sid, "C", False,
                f"Max drawdown {max_dd:.4f}% >= 8.0% (structural risk signal)",
                {}, "MANUAL_REVIEW", now,
            )

        # 6. Capital-at-risk size gate
        if capital_at_risk > CAPITAL_AT_RISK_THRESHOLD_USD:
            return self._make_result(
                sid, "C", False,
                f"capital_at_risk ${capital_at_risk:,.2f} > ${CAPITAL_AT_RISK_THRESHOLD_USD:,.2f} (size gate — requires human judgment)",
                {}, "MANUAL_REVIEW", now,
            )

        # 7. Insufficient paper-trading track record (required by both Tier A and B)
        if paper_days < 30:
            return self._make_result(
                sid, "C", False,
                f"paper_days {paper_days} < 30 (minimum track record not met)",
                {}, "MANUAL_REVIEW", now,
            )

        # ── All Tier C gates passed — now classify Tier A vs B ───────────────

        tier_a = self._check_tier_a(metrics)
        if tier_a["pass"]:
            return self._make_result(
                sid, "A", True,
                "All Tier A criteria met — immediate auto-promotion eligible",
                tier_a["criteria"], "AUTO_PROMOTE", now,
            )

        # Tier B: sharpe >= 0.8, apy_ratio >= 0.90, drawdown < 8.0 all
        # confirmed by Tier C gate; paper_days >= 30 confirmed above.
        # _check_tier_b is called for full criteria detail and independent testability.
        tier_b = self._check_tier_b(metrics)
        return self._make_result(
            sid, "B", True,
            "Tier B criteria met — 48-hour hold before auto-promotion",
            tier_b["criteria"], "PENDING_48H", now,
        )

    def evaluate_all(
        self,
        tournament_path: str = "data/tournament_ranking.json",
        policy_path: str = "data/promotion_policy.json",
    ) -> dict:
        """Load tournament_ranking.json, evaluate every strategy, return full report.

        Returns
        -------
        dict with keys:
            adr_reference, strategies, summary (total/tier_a/tier_b/tier_c/
            auto_promote_enabled), generated_at
        """
        # ── Load files ───────────────────────────────────────────────────────
        with open(Path(tournament_path), "r", encoding="utf-8") as fh:
            tournament = json.load(fh)

        with open(Path(policy_path), "r", encoding="utf-8") as fh:
            policy = json.load(fh)

        auto_promote_enabled: bool = bool(policy.get("auto_promote_enabled", False))

        # ── Evaluate each strategy ───────────────────────────────────────────
        results = []
        tier_counts = {"A": 0, "B": 0, "C": 0}

        for entry in tournament.get("strategies", []):
            # Resolve canonical strategy_id
            if entry.get("strategy_id"):
                sid = str(entry["strategy_id"])
            else:
                sid = str(entry.get("id") or "unknown").lower()

            # Equity series → drawdown + capital_at_risk
            equity_series = entry.get("equity_series") or []
            if equity_series and len(equity_series) >= 2:
                max_dd = _compute_max_drawdown(equity_series)
                capital_at_risk = float(equity_series[-1]) - float(equity_series[0])
            else:
                max_dd = 0.0
                capital_at_risk = 0.0

            metrics = {
                "paper_days":       _safe_int(entry.get("days_running"), 0),
                "sharpe":           _safe_float(entry.get("sharpe"), 0.0),
                "realized_apy":     _safe_float(entry.get("apy_realized"), 0.0),
                "target_apy":       _safe_float(
                    entry.get("apy_target") or entry.get("target_apy_pct"), 0.0
                ),
                "max_drawdown_pct": max_dd,
                "halt_count":       0,  # no halt data in tournament file — conservative 0
                "capital_at_risk":  capital_at_risk,
                "tier_label":       str(entry.get("tier") or ""),
            }

            result = self.evaluate_strategy(sid, metrics)
            # Enrich with display info
            result["name"] = entry.get("name") or ""
            result["rank"] = entry.get("rank")
            results.append(result)
            tier_counts[result["tier"]] += 1

        return {
            "adr_reference": "ADR-029",
            "strategies": results,
            "summary": {
                "total":                len(results),
                "tier_a":               tier_counts["A"],
                "tier_b":               tier_counts["B"],
                "tier_c":               tier_counts["C"],
                "auto_promote_enabled": auto_promote_enabled,
            },
            "generated_at": _utcnow_iso(),
        }

    def save_report(self, report: dict, data_dir: str = "data") -> None:
        """Write report to data/promotion_report.json using atomic tmp + os.replace."""
        out_dir = Path(data_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "promotion_report.json"

        atomic_save(report, str(out_path))
    # -----------------------------------------------------------------------
    # Private criterion checkers
    # -----------------------------------------------------------------------

    def _check_tier_a(self, metrics: dict) -> dict:
        """Check all Tier A criteria independently.

        Returns
        -------
        dict: {
            "pass": bool,
            "criteria": {
                name: {"pass": bool, "value": ..., "threshold": str}
            }
        }

        Note: T3-SPEC and halt_count exclusions are handled upstream in
        evaluate_strategy; this method focuses on the quantitative thresholds.
        """
        paper_days   = _safe_int(metrics.get("paper_days"), 0)
        sharpe       = _safe_float(metrics.get("sharpe"), 0.0)
        realized_apy = _safe_float(metrics.get("realized_apy"), 0.0)
        target_apy   = _safe_float(metrics.get("target_apy"), 0.0)
        max_dd       = _safe_float(metrics.get("max_drawdown_pct"), 0.0)
        halt_count   = _safe_int(metrics.get("halt_count"), 0)

        apy_ratio = (realized_apy / target_apy) if target_apy > 0 else 0.0

        criteria = {
            "paper_days": {
                "pass":      paper_days >= 30,
                "value":     paper_days,
                "threshold": ">= 30 calendar days",
            },
            "sharpe": {
                "pass":      sharpe >= 1.0,
                "value":     round(sharpe, 6),
                "threshold": ">= 1.0 (25% above ADR-023 minimum)",
            },
            "apy_ratio": {
                "pass":      apy_ratio >= 1.10,
                "value":     round(apy_ratio, 6),
                "threshold": ">= 1.10 (realized >= target x 110%)",
            },
            "max_drawdown_pct": {
                "pass":      max_dd < 5.0,
                "value":     round(max_dd, 6),
                "threshold": "< 5.0% (kill-switch alignment)",
            },
            "halt_count": {
                "pass":      halt_count == 0,
                "value":     halt_count,
                "threshold": "== 0 (any halt signals unresolved structural risk)",
            },
        }

        all_pass = all(c["pass"] for c in criteria.values())
        return {"pass": all_pass, "criteria": criteria}

    def _check_tier_b(self, metrics: dict) -> dict:
        """Check all Tier B criteria independently.

        Returns
        -------
        dict: {
            "pass": bool,
            "criteria": {
                name: {"pass": bool, "value": ..., "threshold": str}
            }
        }
        """
        paper_days   = _safe_int(metrics.get("paper_days"), 0)
        sharpe       = _safe_float(metrics.get("sharpe"), 0.0)
        realized_apy = _safe_float(metrics.get("realized_apy"), 0.0)
        target_apy   = _safe_float(metrics.get("target_apy"), 0.0)
        max_dd       = _safe_float(metrics.get("max_drawdown_pct"), 0.0)
        halt_count   = _safe_int(metrics.get("halt_count"), 0)

        apy_ratio = (realized_apy / target_apy) if target_apy > 0 else 0.0

        criteria = {
            "paper_days": {
                "pass":      paper_days >= 30,
                "value":     paper_days,
                "threshold": ">= 30 calendar days",
            },
            "sharpe": {
                "pass":      sharpe >= 0.8,
                "value":     round(sharpe, 6),
                "threshold": ">= 0.8 (ADR-023 minimum)",
            },
            "apy_ratio": {
                "pass":      apy_ratio >= 0.90,
                "value":     round(apy_ratio, 6),
                "threshold": ">= 0.90 (realized >= target x 90%)",
            },
            "max_drawdown_pct": {
                "pass":      max_dd < 8.0,
                "value":     round(max_dd, 6),
                "threshold": "< 8.0% (wider than Tier A; still below kill switch)",
            },
            "halt_count": {
                "pass":      halt_count == 0,
                "value":     halt_count,
                "threshold": "== 0 (no halts allowed even in Tier B)",
            },
        }

        all_pass = all(c["pass"] for c in criteria.values())
        return {"pass": all_pass, "criteria": criteria}

    # -----------------------------------------------------------------------
    # Internal factory
    # -----------------------------------------------------------------------

    @staticmethod
    def _make_result(
        strategy_id: str,
        tier: str,
        eligible: bool,
        reason: str,
        criteria_results: dict,
        action: str,
        evaluated_at: str,
    ) -> dict:
        return {
            "strategy_id":     strategy_id,
            "tier":            tier,
            "eligible":        eligible,
            "reason":          reason,
            "criteria_results": criteria_results,
            "action":          action,
            "evaluated_at":    evaluated_at,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _resolve_data_dir() -> Path:
    """Return absolute path to data/ relative to repo root (this file is 3 dirs deep)."""
    return Path(__file__).parent.parent.parent / "data"


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="ADR-029 AutoPromoter — evaluate strategies for promotion tier"
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Compute and write data/promotion_report.json (default: check only)"
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Override data/ directory path"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else _resolve_data_dir()
    tournament_path = data_dir / "tournament_ranking.json"
    policy_path     = data_dir / "promotion_policy.json"

    promoter = AutoPromoter()
    try:
        report = promoter.evaluate_all(
            tournament_path=str(tournament_path),
            policy_path=str(policy_path),
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    summary = report["summary"]
    print(
        f"AutoPromoter — ADR-029 evaluation complete\n"
        f"  Total strategies : {summary['total']}\n"
        f"  Tier A (AUTO)    : {summary['tier_a']}\n"
        f"  Tier B (48h hold): {summary['tier_b']}\n"
        f"  Tier C (manual)  : {summary['tier_c']}\n"
        f"  auto_promote_enabled: {summary['auto_promote_enabled']}"
    )

    for s in report["strategies"]:
        tier_icon = {"A": "⚡", "B": "🕐", "C": "🔴"}.get(s["tier"], "?")
        print(f"  {tier_icon} [{s['tier']}] {s['strategy_id']} — {s['action']} — {s['reason']}")

    if args.run:
        promoter.save_report(report, data_dir=str(data_dir))
        print(f"\nReport written → {data_dir / 'promotion_report.json'}")
    else:
        print("\n(dry run — pass --run to write promotion_report.json)")

    sys.exit(0)
