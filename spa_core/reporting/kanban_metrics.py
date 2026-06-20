#!/usr/bin/env python3
"""KANBAN completion metrics (MP-1580 / Improvement 5).

Computes completion statistics over ``KANBAN.json`` so the daily
``CURRENT_STATE.md`` regeneration can report real progress:

  * overall done / total ticket counts and completion %
  * completion % broken down by ticket-id category (``MP-``, ``WEB-``,
    ``SITE-``, ``AGENT-`` …)

The board stores tickets in ``columns`` (``ideas / features / backlog /
in_progress / review / done``) and in a flat ``tasks`` list. A ticket counts
as *done* if it lives in the ``done`` column or carries ``status == "done"``.
Tickets are de-duplicated by id across both sources (done wins).

Design / safety
===============
* STRICTLY READ-ONLY / REPORTING. Reads ``KANBAN.json``; writes its own
  ``data/kanban_metrics.json``. Never edits the board, never touches capital.
* Stdlib only. Atomic write. Fail-safe: a missing / corrupt board yields a
  zeroed metrics dict rather than raising.
* No LLM.

CLI
===
    python3 -m spa_core.reporting.kanban_metrics --check
    python3 -m spa_core.reporting.kanban_metrics --run
    python3 -m spa_core.reporting.kanban_metrics --run --kanban <path> --out <path>
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_save

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_KANBAN = _REPO_ROOT / "KANBAN.json"
_DEFAULT_OUT = _REPO_ROOT / "data" / "kanban_metrics.json"

DONE_COLUMN = "done"
_CATEGORY_RE = re.compile(r"^([A-Za-z]+)")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def category_of(ticket_id: Any) -> str:
    """Leading alpha prefix of a ticket id (e.g. ``MP-1503`` → ``MP``).

    Returns ``"OTHER"`` for ids with no leading letters / empty ids.
    """
    m = _CATEGORY_RE.match(str(ticket_id or "").strip())
    return m.group(1).upper() if m else "OTHER"


def collect_tickets(kanban: Dict[str, Any]) -> Dict[str, bool]:
    """Return ``{ticket_id: is_done}`` de-duplicated across columns + tasks.

    An id seen as done anywhere stays done (``done`` wins over a stale
    not-done copy elsewhere).
    """
    result: Dict[str, bool] = {}

    def _mark(tid: Any, done: bool) -> None:
        tid = str(tid).strip()
        if not tid:
            return
        result[tid] = result.get(tid, False) or done

    columns = kanban.get("columns") if isinstance(kanban, dict) else None
    if isinstance(columns, dict):
        for col_name, items in columns.items():
            if not isinstance(items, list):
                continue
            is_done_col = (str(col_name) == DONE_COLUMN)
            for it in items:
                if not isinstance(it, dict):
                    continue
                tid = it.get("id")
                done = is_done_col or str(it.get("status", "")).lower() == "done"
                _mark(tid, done)

    tasks = kanban.get("tasks") if isinstance(kanban, dict) else None
    if isinstance(tasks, list):
        for it in tasks:
            if isinstance(it, dict):
                _mark(it.get("id"), str(it.get("status", "")).lower() == "done")

    return result


def compute_metrics(tickets: Dict[str, bool]) -> Dict[str, Any]:
    """Overall + per-category completion metrics from ``{id: is_done}``."""
    total = len(tickets)
    done = sum(1 for v in tickets.values() if v)

    by_cat: Dict[str, Dict[str, Any]] = {}
    for tid, is_done in tickets.items():
        cat = category_of(tid)
        slot = by_cat.setdefault(cat, {"done": 0, "total": 0})
        slot["total"] += 1
        if is_done:
            slot["done"] += 1

    for cat, slot in by_cat.items():
        slot["completion_pct"] = round(
            slot["done"] / slot["total"] * 100.0, 2) if slot["total"] else 0.0

    return {
        "total": total,
        "done": done,
        "open": total - done,
        "completion_pct": round(done / total * 100.0, 2) if total else 0.0,
        "by_category": dict(sorted(by_cat.items())),
        "generated_at": _utc_now_iso(),
    }


def _read_kanban(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("kanban_metrics: unreadable %s (%s)", path, exc)
        return {}


def compute_from_file(kanban_path: Optional[Path] = None) -> Dict[str, Any]:
    """Read the board and compute metrics. Fail-safe."""
    kanban = _read_kanban(Path(kanban_path) if kanban_path else _DEFAULT_KANBAN)
    metrics = compute_metrics(collect_tickets(kanban))
    # surface the board's own done_count for cross-checking, if present
    if isinstance(kanban, dict) and "done_count" in kanban:
        metrics["board_done_count"] = kanban.get("done_count")
    return metrics


def run(
    kanban_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    write: bool = True,
) -> Dict[str, Any]:
    metrics = compute_from_file(kanban_path)
    if write:
        out = Path(out_path) if out_path else _DEFAULT_OUT
        try:
            atomic_save(metrics, str(out))
        except OSError as exc:
            log.warning("kanban_metrics: write failed (%s)", exc)
    return metrics


def render_markdown(metrics: Dict[str, Any]) -> str:
    """Render a compact Markdown table for CURRENT_STATE.md auto-generation."""
    lines = [
        f"**KANBAN completion:** {metrics.get('done', 0)}/{metrics.get('total', 0)} "
        f"({metrics.get('completion_pct', 0):.1f}%)",
        "",
        "| Category | Done | Total | % |",
        "|----------|------|-------|---|",
    ]
    for cat, slot in (metrics.get("by_category") or {}).items():
        lines.append(
            f"| {cat} | {slot.get('done', 0)} | {slot.get('total', 0)} "
            f"| {slot.get('completion_pct', 0):.1f}% |")
    return "\n".join(lines)


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kanban_metrics",
        description="KANBAN completion metrics (read-only reporting).",
    )
    parser.add_argument("--run", action="store_true", help="write kanban_metrics.json")
    parser.add_argument("--check", action="store_true", help="compute + print only (default)")
    parser.add_argument("--kanban", default=None, help="override KANBAN.json path")
    parser.add_argument("--out", default=None, help="override output path")
    parser.add_argument("--markdown", action="store_true", help="print Markdown table")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    metrics = run(
        kanban_path=Path(args.kanban) if args.kanban else None,
        out_path=Path(args.out) if args.out else None,
        write=bool(args.run),
    )

    if args.markdown:
        print(render_markdown(metrics))
    else:
        print(f"total          : {metrics['total']}")
        print(f"done           : {metrics['done']}")
        print(f"completion     : {metrics['completion_pct']:.2f}%")
        print("by category    :")
        for cat, slot in metrics["by_category"].items():
            print(f"  {cat:<8}: {slot['done']}/{slot['total']} "
                  f"({slot['completion_pct']:.1f}%)")
    if args.run:
        print("(wrote kanban_metrics.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
