"""
spa_core/backtesting/pre_paper_checklist.py

MP-1321 (v9.37) — Pre-paper trading launch checklist.

Checks all gates and prerequisites before launching paper trading.
Designed to be run daily to track progress toward paper trading launch.

Categories:
  1. gates           — automated gate checks (pre_paper, hardening, expanded_universe)
  2. data_sources    — data source quality (partially automated)
  3. infrastructure  — runtime services (manual confirmation needed)
  4. owner_signoff   — owner acceptance gate (automated + manual)
  5. research_docs   — research documentation (automated)

Output schema::

    {
      "overall_status": "BLOCKED" | "READY",
      "completion_pct": 45.0,
      "categories": {
        "gates":          {"status": "PASS",    "items": [...]},
        "data_sources":   {"status": "PARTIAL", "items": [...]},
        "infrastructure": {"status": "UNKNOWN", "items": [...]},
        "owner_signoff":  {"status": "BLOCKED", "items": [...]},
        "research_docs":  {"status": "PASS",    "items": [...]}
      },
      "blocking_items": [...],
      "next_action": "Run: python3 -m spa_core.backtesting.owner_acceptance --generate-draft",
      "last_checked": "2026-06-19T..."
    }

Item status values:
  "PASS"    — automated check succeeded
  "FAIL"    — automated check failed
  "UNKNOWN" — manual confirmation required (auto=False)
  "BLOCKED" — explicitly blocked (owner gate not signed)

Rules:
  - stdlib only, no external dependencies
  - reads gate JSON files; never writes to them
  - atomic save via tmp + os.replace
  - all reads defensive (missing / malformed files → FAIL/UNKNOWN, no raise)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from spa_core.utils.atomic import atomic_save


# ── Checklist definition ──────────────────────────────────────────────────────

CHECKLIST_ITEMS: dict[str, list[dict]] = {
    "gates": [
        {
            "id": "G001",
            "desc": "Pre-paper backtest gate PASS",
            "auto": True,
            "blocking": True,
        },
        {
            "id": "G002",
            "desc": "Paper ready gate: hardening audit",
            "auto": True,
            "blocking": True,
        },
        {
            "id": "G003",
            "desc": "Paper ready gate: expanded universe",
            "auto": True,
            "blocking": True,
        },
    ],
    "data_sources": [
        {
            "id": "D001",
            "desc": "Aave V3 USDC — CLEAN data available",
            "auto": False,
            "blocking": False,
        },
        {
            "id": "D002",
            "desc": "Morpho Blue — CLEAN data available",
            "auto": False,
            "blocking": False,
        },
        {
            "id": "D003",
            "desc": "GMX research adapter ready",
            "auto": True,
            "blocking": False,
        },
        {
            "id": "D004",
            "desc": "Source pipeline JSON up to date",
            "auto": True,
            "blocking": False,
        },
    ],
    "infrastructure": [
        {
            "id": "I001",
            "desc": "HTTP server running (localhost:8765)",
            "auto": False,
            "blocking": False,
        },
        {
            "id": "I002",
            "desc": "Telegram bot connected",
            "auto": False,
            "blocking": False,
        },
        {
            "id": "I003",
            "desc": "cycle_runner scheduled",
            "auto": False,
            "blocking": False,
        },
    ],
    "owner_signoff": [
        {
            "id": "O001",
            "desc": "Owner acceptance signed",
            "auto": True,
            "blocking": True,
        },
        {
            "id": "O002",
            "desc": "Risk statement acknowledged",
            "auto": True,
            "blocking": True,
        },
        {
            "id": "O003",
            "desc": "Paper period confirmed (90 days min)",
            "auto": False,
            "blocking": False,
        },
    ],
    "research_docs": [
        {
            "id": "R001",
            "desc": "RS-001 exclusion report generated",
            "auto": True,
            "blocking": False,
        },
        {
            "id": "R002",
            "desc": "RS-002 IL risk documented",
            "auto": True,
            "blocking": False,
        },
        {
            "id": "R003",
            "desc": "CPA integration status doc exists",
            "auto": True,
            "blocking": False,
        },
    ],
}

# Category status priority: BLOCKED > FAIL > PARTIAL > UNKNOWN > PASS
_STATUS_RANK = {"PASS": 0, "UNKNOWN": 1, "PARTIAL": 2, "FAIL": 3, "BLOCKED": 4}


# ── Main class ────────────────────────────────────────────────────────────────

class PrePaperChecklist:
    """
    Automated pre-paper trading launch checklist.

    Reads gate JSON files and filesystem state to determine readiness.
    Manual items are marked UNKNOWN (require operator confirmation).

    Args:
        base_dir: project root directory (default: current working directory)
    """

    # ── Gate file paths (relative to base_dir) ──────────────────────────────
    _PRE_PAPER_GATE = "data/backtest/pre_paper_backtest_gate.json"
    _PAPER_READY_GATE = "data/backtest/paper_ready_gate.json"
    _OWNER_GATE = "data/backtest/owner_paper_acceptance_gate.json"

    # ── Adapter / doc paths (relative to base_dir) ───────────────────────────
    _GMX_ADAPTER = "spa_core/adapters/gmx_research.py"
    _SOURCE_PIPELINE = "data/backtest/source_pipeline.json"
    _RS001_REPORT = "data/backtest/reports/p1a_closure_report.md"
    _RS002_DOCS = "docs/backtest_handoff/07_known_limitations.md"
    _CPA_STATUS = "docs/CPA_INTEGRATION_STATUS.md"

    def __init__(self, base_dir: str = ".") -> None:
        self._base = Path(base_dir)

    # ── Public API ────────────────────────────────────────────────────────────

    def check_all(self) -> dict:
        """
        Run all automated checks; mark manual items UNKNOWN.

        Returns:
            Checklist result dict with overall_status, completion_pct,
            categories, blocking_items, next_action, last_checked.
        """
        item_results: dict[str, str] = {}

        # ── gates ─────────────────────────────────────────────────────────────
        item_results["G001"] = self._check_g001()
        item_results["G002"] = self._check_g002()
        item_results["G003"] = self._check_g003()

        # ── data_sources ──────────────────────────────────────────────────────
        item_results["D001"] = "UNKNOWN"
        item_results["D002"] = "UNKNOWN"
        item_results["D003"] = self._check_d003()
        item_results["D004"] = self._check_d004()

        # ── infrastructure ────────────────────────────────────────────────────
        item_results["I001"] = "UNKNOWN"
        item_results["I002"] = "UNKNOWN"
        item_results["I003"] = "UNKNOWN"

        # ── owner_signoff ─────────────────────────────────────────────────────
        item_results["O001"] = self._check_o001()
        item_results["O002"] = self._check_o002()
        item_results["O003"] = "UNKNOWN"

        # ── research_docs ─────────────────────────────────────────────────────
        item_results["R001"] = self._check_r001()
        item_results["R002"] = self._check_r002()
        item_results["R003"] = self._check_r003()

        # ── build categories ──────────────────────────────────────────────────
        categories: dict[str, dict] = {}
        for cat_name, cat_items in CHECKLIST_ITEMS.items():
            items_out = []
            for item_def in cat_items:
                iid = item_def["id"]
                status = item_results[iid]
                items_out.append({
                    "id": iid,
                    "desc": item_def["desc"],
                    "status": status,
                    "auto": item_def["auto"],
                    "blocking": item_def["blocking"],
                })
            cat_status = self._aggregate_status(items_out)
            categories[cat_name] = {
                "status": cat_status,
                "items": items_out,
            }

        # ── blocking items ────────────────────────────────────────────────────
        blocking = self._compute_blocking(categories)

        # ── completion ────────────────────────────────────────────────────────
        pct = self._completion_pct_from_categories(categories)

        # ── overall status ────────────────────────────────────────────────────
        overall = "BLOCKED" if blocking else "READY"

        result = {
            "overall_status": overall,
            "completion_pct": pct,
            "categories": categories,
            "blocking_items": blocking,
            "next_action": self._next_action_from_blocking(blocking),
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }
        return result

    def completion_pct(self, result: dict) -> float:
        """
        Percentage of checks that are passing (PASS status).

        Args:
            result: dict returned by check_all()

        Returns:
            Float 0.0–100.0
        """
        return self._completion_pct_from_categories(result.get("categories", {}))

    def blocking_items(self, result: dict) -> list:
        """
        Items that must pass before paper trading can start.

        Args:
            result: dict returned by check_all()

        Returns:
            List of blocking item description strings.
        """
        return list(result.get("blocking_items", []))

    def next_action(self, result: dict) -> str:
        """
        Most impactful next step toward paper trading launch.

        Args:
            result: dict returned by check_all()

        Returns:
            Actionable string.
        """
        return result.get("next_action", "")

    def save(
        self,
        result: dict,
        path: str = "data/backtest/pre_paper_checklist.json",
    ) -> None:
        """
        Atomic save of checklist result to JSON file.

        Uses tmp-file + os.replace to avoid partial writes.

        Args:
            result: dict returned by check_all()
            path: destination path (relative to base_dir or absolute)
        """
        dest = Path(path)
        if not dest.is_absolute():
            dest = self._base / dest

        atomic_save(result, str(dest))

    def to_markdown(self, result: dict) -> str:
        """
        Formatted checklist suitable for operator reports or console output.

        Args:
            result: dict returned by check_all()

        Returns:
            Multi-line markdown string.
        """
        lines: list[str] = []
        overall = result.get("overall_status", "UNKNOWN")
        pct = result.get("completion_pct", 0.0)
        ts = result.get("last_checked", "")

        lines.append("# Pre-Paper Launch Checklist")
        lines.append("")
        lines.append(f"**Status:** {overall}  ")
        lines.append(f"**Completion:** {pct:.1f}%  ")
        lines.append(f"**Checked:** {ts}")
        lines.append("")

        categories = result.get("categories", {})
        _DISPLAY_NAMES = {
            "gates": "Gates",
            "data_sources": "Data Sources",
            "infrastructure": "Infrastructure",
            "owner_signoff": "Owner Sign-Off",
            "research_docs": "Research Docs",
        }

        _STATUS_ICONS = {
            "PASS": "✅",
            "FAIL": "❌",
            "UNKNOWN": "❓",
            "BLOCKED": "🚫",
            "PARTIAL": "⚠️",
        }

        for cat_key in CHECKLIST_ITEMS:
            cat = categories.get(cat_key, {})
            cat_status = cat.get("status", "UNKNOWN")
            icon = _STATUS_ICONS.get(cat_status, "❓")
            display = _DISPLAY_NAMES.get(cat_key, cat_key)

            lines.append(f"## {icon} {display} ({cat_status})")
            lines.append("")
            lines.append("| ID | Description | Status |")
            lines.append("|---|---|---|")

            for item in cat.get("items", []):
                iid = item.get("id", "")
                desc = item.get("desc", "")
                st = item.get("status", "UNKNOWN")
                item_icon = _STATUS_ICONS.get(st, "❓")
                lines.append(f"| {iid} | {desc} | {item_icon} {st} |")

            lines.append("")

        # blocking section
        blocking = result.get("blocking_items", [])
        if blocking:
            lines.append("## 🚫 Blocking Items")
            lines.append("")
            for b in blocking:
                lines.append(f"- {b}")
            lines.append("")

        # next action
        na = result.get("next_action", "")
        if na:
            lines.append("## ▶️ Next Action")
            lines.append("")
            lines.append(na)
            lines.append("")

        return "\n".join(lines)

    # ── Automated check implementations ───────────────────────────────────────

    def _check_g001(self) -> str:
        """G001: Pre-paper backtest gate PASS"""
        data = self._load_json(self._PRE_PAPER_GATE)
        if data is None:
            return "FAIL"
        return "PASS" if data.get("status") == "PASS" else "FAIL"

    def _check_g002(self) -> str:
        """G002: Paper ready gate: hardening audit"""
        data = self._load_json(self._PAPER_READY_GATE)
        if data is None:
            return "FAIL"
        return "PASS" if data.get("hardening_status") == "PASS" else "FAIL"

    def _check_g003(self) -> str:
        """G003: Paper ready gate: expanded universe"""
        data = self._load_json(self._PAPER_READY_GATE)
        if data is None:
            return "FAIL"
        status = data.get("expanded_universe_verification_status", "")
        return "PASS" if status == "PASS" else "FAIL"

    def _check_d003(self) -> str:
        """D003: GMX research adapter file exists"""
        return "PASS" if (self._base / self._GMX_ADAPTER).exists() else "FAIL"

    def _check_d004(self) -> str:
        """D004: Source pipeline JSON exists"""
        return "PASS" if (self._base / self._SOURCE_PIPELINE).exists() else "FAIL"

    def _check_o001(self) -> str:
        """O001: Owner acceptance signed"""
        data = self._load_json(self._OWNER_GATE)
        if data is None:
            return "BLOCKED"
        # Signed means status != NOT_SIGNED and blockers is empty
        gate_status = data.get("status", "")
        if gate_status == "SIGNED":
            return "PASS"
        if gate_status == "NOT_SIGNED":
            return "BLOCKED"
        # Fallback: check blockers
        blockers = data.get("blockers", [])
        return "PASS" if not blockers else "BLOCKED"

    def _check_o002(self) -> str:
        """O002: Risk statement acknowledged (no 'risk' blockers)"""
        data = self._load_json(self._OWNER_GATE)
        if data is None:
            return "BLOCKED"
        # If owner gate is NOT_SIGNED the risk statement isn't acknowledged yet
        gate_status = data.get("status", "")
        if gate_status == "NOT_SIGNED":
            return "BLOCKED"
        if gate_status == "SIGNED":
            return "PASS"
        blockers = data.get("blockers", [])
        return "PASS" if not blockers else "BLOCKED"

    def _check_r001(self) -> str:
        """R001: RS-001 exclusion report (P1A closure report)"""
        return "PASS" if (self._base / self._RS001_REPORT).exists() else "FAIL"

    def _check_r002(self) -> str:
        """R002: RS-002 IL risk documented (backtest_handoff limitations doc)"""
        return "PASS" if (self._base / self._RS002_DOCS).exists() else "FAIL"

    def _check_r003(self) -> str:
        """R003: CPA integration status doc exists"""
        return "PASS" if (self._base / self._CPA_STATUS).exists() else "FAIL"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_json(self, rel_path: str) -> dict | None:
        """Load JSON defensively; returns None on any error."""
        path = self._base / rel_path
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return None

    @staticmethod
    def _aggregate_status(items: list[dict]) -> str:
        """
        Compute category status from item statuses.

        Priority: BLOCKED > FAIL > PARTIAL > UNKNOWN > PASS
        PARTIAL is returned when some items PASS and others do not.
        """
        if not items:
            return "UNKNOWN"

        statuses = {item["status"] for item in items}

        if "BLOCKED" in statuses:
            return "BLOCKED"
        if statuses == {"PASS"}:
            return "PASS"
        if statuses == {"UNKNOWN"}:
            return "UNKNOWN"
        if "FAIL" in statuses:
            if "PASS" in statuses:
                return "PARTIAL"
            return "FAIL"
        if "PASS" in statuses and "UNKNOWN" in statuses:
            return "PARTIAL"
        return "UNKNOWN"

    @staticmethod
    def _completion_pct_from_categories(categories: dict) -> float:
        """Percentage of all items with status PASS."""
        total = 0
        passing = 0
        for cat in categories.values():
            for item in cat.get("items", []):
                total += 1
                if item.get("status") == "PASS":
                    passing += 1
        if total == 0:
            return 0.0
        return round(passing / total * 100, 2)

    @staticmethod
    def _compute_blocking(categories: dict) -> list:
        """
        Return list of descriptions for blocking items that are not PASS.

        Only items with blocking=True and status != PASS are included.
        """
        blocking: list[str] = []
        for cat in categories.values():
            for item in cat.get("items", []):
                if item.get("blocking") and item.get("status") not in ("PASS",):
                    blocking.append(f"[{item['id']}] {item['desc']}")
        return blocking

    @staticmethod
    def _next_action_from_blocking(blocking: list) -> str:
        """Return the most impactful next action string based on blockers."""
        if not blocking:
            return "All blocking checks pass — paper trading can be launched."

        # Priority order for known blocking items
        if any("O001" in b or "O002" in b for b in blocking):
            return (
                "Run: python3 -m spa_core.backtesting.owner_acceptance"
                " --generate-draft  # then sign data/backtest/owner_paper_acceptance_draft.json"
            )
        if any("G002" in b for b in blocking):
            return (
                "Complete backtest hardening audit:"
                " run python3 -m spa_core.backtesting.run_full_backtest --hardening"
            )
        if any("G003" in b for b in blocking):
            return (
                "Resolve expanded universe verification:"
                " review data/backtest/paper_ready_gate.json blockers"
            )
        if any("G001" in b for b in blocking):
            return (
                "Run pre-paper backtest gate:"
                " python3 -m spa_core.backtesting.run_full_backtest"
            )

        # Fallback: list all blockers
        first = blocking[0]
        return f"Resolve: {first}"


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Pre-paper trading launch checklist (MP-1321)"
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Project root (default: current directory)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save result to data/backtest/pre_paper_checklist.json",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Print markdown-formatted checklist",
    )
    args = parser.parse_args()

    checklist = PrePaperChecklist(base_dir=args.base_dir)
    result = checklist.check_all()

    if args.markdown:
        print(checklist.to_markdown(result))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.save:
        checklist.save(result)
        print("\n✅ Saved to data/backtest/pre_paper_checklist.json", file=sys.stderr)

    # Exit 1 if BLOCKED so CI/scripts can gate on this
    if result["overall_status"] == "BLOCKED":
        sys.exit(1)


if __name__ == "__main__":
    main()
