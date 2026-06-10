"""
SPA-V387 — Go-Live Readiness Report formatter.

Renders the dict produced by ``ReadinessChecker.check_all()`` into a human-
readable ASCII report and persists it as ``data/golive_readiness.json``.

Pure presentation / serialisation — no grading, no data fetching, no
money-moving code.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SPA_DIR = Path(__file__).resolve().parents[2]

_STATUS_ICON = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ ", "SKIP": "⏭️ "}
_VERDICT_ICON = {"READY": "🟢", "CONDITIONAL": "🟡", "NOT_READY": "🔴"}


class ReadinessReport:
    """Formats and persists a readiness-check result."""

    def __init__(self, result: dict) -> None:
        self.result = result

    # ── rendering ───────────────────────────────────────────────────────────────
    def render(self) -> str:
        r = self.result
        verdict = r.get("verdict", "UNKNOWN")
        vicon = _VERDICT_ICON.get(verdict, "")
        date_str = (r.get("generated_at", "") or "")[:10] or \
            datetime.now(timezone.utc).date().isoformat()

        lines: list[str] = []
        bar = "=" * 56
        lines.append(bar)
        lines.append("SPA GO-LIVE READINESS REPORT")
        lines.append(f"Date: {date_str} | Target: {r.get('go_live_date', '?')}")
        lines.append(bar)
        lines.append(
            f"Verdict: {vicon} {verdict}   "
            f"Score: {r.get('score', 0.0):.2f}/1.00"
        )
        lines.append(f"Days to go-live: {r.get('days_to_golive', '?')}")
        lines.append("")

        blockers = r.get("blockers", [])
        lines.append("BLOCKERS (must fix):")
        if blockers:
            for c in blockers:
                lines.append(f"  ❌ {c['id']} {c['name']} — FAIL: {c['detail']}")
        else:
            lines.append("  (none — all blocker criteria pass)")
        lines.append("")

        warnings = r.get("warnings", [])
        if warnings:
            lines.append("WARNINGS:")
            for c in warnings:
                lines.append(f"  ⚠️  {c['id']} {c['name']} — WARN: {c['detail']}")
            lines.append("")

        skipped = r.get("skipped", [])
        if skipped:
            lines.append("SKIPPED (data unavailable):")
            for c in skipped:
                lines.append(f"  ⏭️  {c['id']} {c['name']} — SKIP: {c['detail']}")
            lines.append("")

        passed = r.get("passed", [])
        lines.append(f"PASSED ({len(passed)}/{r.get('num_criteria', '?')}):")
        for c in passed:
            lines.append(f"  ✅ {c['id']} {c['name']} — {c['detail']}")
        lines.append(bar)

        return "\n".join(lines)

    def print_report(self) -> None:
        print(self.render())

    # ── persistence ─────────────────────────────────────────────────────────────
    def save_json(self, path: str | Path = "data/golive_readiness.json") -> Path:
        """Write the raw result dict to ``path`` (resolved against the SPA root)."""
        out = Path(path)
        if not out.is_absolute():
            out = SPA_DIR / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out
