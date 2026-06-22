#!/usr/bin/env python3
"""
Daily strategy promotion evaluator (ADR-029).
Evaluates all tournament strategies against Tier A/B/C criteria.
Saves promotion_report.json.
Sends Telegram alerts if auto_promote_enabled=True (Phase 2).

Usage:
    python3 scripts/run_auto_promoter.py          # full run
    python3 scripts/run_auto_promoter.py --dry-run  # evaluate but no Telegram
    python3 scripts/run_auto_promoter.py --json     # JSON output
    python3 scripts/run_auto_promoter.py --summary  # text summary only
"""
import sys
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR-029 promotion evaluator — daily strategy tier routing"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Evaluate and print; skip report write and Telegram")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Print full report as JSON")
    parser.add_argument("--summary", action="store_true",
                        help="Print one-line summary only")
    args = parser.parse_args()

    # ── 1. Run evaluation ────────────────────────────────────────────────────
    from spa_core.reporting.auto_promoter import AutoPromoter

    promoter = AutoPromoter()
    tournament_path = str(DATA_DIR / "tournament_ranking.json")
    policy_path     = str(DATA_DIR / "promotion_policy.json")

    try:
        report = promoter.evaluate_all(
            tournament_path=tournament_path,
            policy_path=policy_path,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: data file not found — {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: evaluation failed — {exc}", file=sys.stderr)
        return 1

    # ── 2. Save report (unless --dry-run) ────────────────────────────────────
    if not args.dry_run:
        try:
            promoter.save_report(report, data_dir=str(DATA_DIR))
        except Exception as exc:
            print(f"WARNING: could not write promotion_report.json — {exc}", file=sys.stderr)

    # ── 3. Load policy to check if Telegram alerts enabled ──────────────────
    policy_path_obj = DATA_DIR / "promotion_policy.json"
    policy: dict = {}
    try:
        policy = json.loads(policy_path_obj.read_text(encoding="utf-8"))
    except Exception:
        pass
    auto_enabled: bool = bool(policy.get("auto_promote_enabled", False))

    # ── 4. Send Telegram if Phase 2 enabled (not dry-run) ───────────────────
    if auto_enabled and not args.dry_run:
        try:
            from spa_core.reporting.promotion_notifier import PromotionNotifier
            notifier = PromotionNotifier()
            for strategy in report.get("strategies", []):
                action      = strategy.get("action", "")
                sid         = strategy.get("strategy_id", "?")
                metrics     = strategy.get("metrics") or {}
                reason      = strategy.get("reason", "")

                if action == "AUTO_PROMOTE":
                    notifier.send_tier_a_alert(sid, metrics)
                elif action == "PENDING_48H":
                    notifier.send_tier_b_alert(sid, metrics)
                elif action == "MANUAL_REVIEW":
                    notifier.send_tier_c_alert(sid, metrics, reason)
        except Exception as exc:
            print(f"WARNING: Telegram alerts failed — {exc}", file=sys.stderr)

    # ── 5. Output ────────────────────────────────────────────────────────────
    summary = report.get("summary", {})

    if args.json_output:
        print(json.dumps(report, indent=2, default=str))

    elif args.summary:
        print(f"Promotion Report — {report.get('generated_at', '?')}")
        print(f"  Total strategies: {summary.get('total', 0)}")
        print(f"  Tier A (AUTO):   {summary.get('tier_a', 0)}")
        print(f"  Tier B (48h):    {summary.get('tier_b', 0)}")
        print(f"  Tier C (manual): {summary.get('tier_c', 0)}")
        print(f"  Auto promote: {'ENABLED' if auto_enabled else 'DISABLED (until 2026-07-12)'}")

    else:
        # Full text output
        phase_note = "ENABLED" if auto_enabled else "DISABLED"
        print("=== Promotion Evaluator (ADR-029) ===")
        print(f"Auto-promote: {phase_note}")
        if args.dry_run:
            print("Mode: DRY-RUN (no writes, no Telegram)")
        print()

        tier_emoji = {"A": "⚡", "B": "🕐", "C": "🔴"}
        for s in report.get("strategies", []):
            tier  = s.get("tier", "?")
            emoji = tier_emoji.get(tier, "❓")
            sid   = s.get("strategy_id", s.get("id", "?"))
            name  = s.get("name", "")
            action = s.get("action", "?")
            reason = (s.get("reason") or "")[:60]
            rank  = s.get("rank")
            rank_str = f"#{rank} " if rank is not None else ""
            name_str = f" ({name})" if name else ""
            print(f"  {emoji} {rank_str}{sid}{name_str}")
            print(f"     Tier {tier} — {action} — {reason}")

        print()
        print(f"Summary: {summary.get('total', 0)} strategies  |  "
              f"Tier A: {summary.get('tier_a', 0)}  "
              f"Tier B: {summary.get('tier_b', 0)}  "
              f"Tier C: {summary.get('tier_c', 0)}")

        if not args.dry_run:
            report_path = DATA_DIR / "promotion_report.json"
            print(f"Report saved → {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
