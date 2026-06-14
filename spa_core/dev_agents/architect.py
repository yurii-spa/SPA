"""
SPA Architect Agent — Senior Development Orchestrator

Responsibilities:
- Reviews the KANBAN.json and DEV_STRATEGY roadmap
- Prioritizes next sprint items from backlog
- Reviews ideas and promotes them to features or backlog
- Writes sprint plans
- Generates ADR drafts for significant decisions
- Reports weekly status to Telegram

This is a DEVELOPMENT layer agent (not a product agent).
It never touches live trading decisions.

Usage:
    python -m spa_core.dev_agents.architect --command review-backlog
    python -m spa_core.dev_agents.architect --command plan-sprint
    python -m spa_core.dev_agents.architect --command review-ideas
    python -m spa_core.dev_agents.architect --command weekly-status
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import anthropic

from spa_core.config.model_config import get_model

# ── File paths (relative to project root) ─────────────────────────────────────
KANBAN_FILE = "KANBAN.json"
DEV_STRATEGY_FILE = "DEV_STRATEGY_v1.0.md"
SPRINT_LOG_FILE = "SPA_sprint_log.md"


class SpaArchitect:
    """
    LLM-powered senior architect agent.

    Reads KANBAN.json + DEV_STRATEGY, calls Claude to produce
    prioritized sprint plans, idea reviews, and weekly status updates.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.model = get_model("architect")
        self.kanban = self._load_kanban()
        self.strategy = (
            Path(DEV_STRATEGY_FILE).read_text()
            if Path(DEV_STRATEGY_FILE).exists()
            else ""
        )

    # ── Kanban persistence ────────────────────────────────────────────────────

    def _load_kanban(self) -> dict:
        if Path(KANBAN_FILE).exists():
            return json.loads(Path(KANBAN_FILE).read_text())
        return {
            "columns": {
                "backlog": [],
                "in_progress": [],
                "done": [],
                "ideas": [],
                "features": [],
                "review": [],
            }
        }

    def _save_kanban(self, kanban: dict):
        kanban["last_updated"] = datetime.now(timezone.utc).isoformat()
        kanban["updated_by"] = "Architect"
        Path(KANBAN_FILE).write_text(json.dumps(kanban, indent=2))

    # ── Claude API ────────────────────────────────────────────────────────────

    def _ask_claude(self, system: str, user: str) -> str:
        """Call Claude API with system + user prompt."""
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    # ── Commands ──────────────────────────────────────────────────────────────

    def review_backlog(self) -> str:
        """Analyze backlog and return prioritized next sprint recommendation."""
        backlog_text = json.dumps(
            self.kanban["columns"].get("backlog", []), indent=2
        )
        ideas_text = json.dumps(
            self.kanban["columns"].get("ideas", []), indent=2
        )
        done_count = len(self.kanban["columns"].get("done", []))

        system = """You are a senior software architect reviewing a DeFi paper trading project called SPA.
Your job is to prioritize the development backlog and recommend the next sprint.
Be concise, practical, and focused on go-live readiness (target: 2026-07-15).
Risk and execution agents must NEVER use LLM — only deterministic code.
Format your response as:
1. Next sprint recommendation (3-5 tasks, with estimates)
2. Items to defer
3. Any risks or blockers"""

        user = f"""Project: SPA — DeFi paper trading targeting 7.3% APY on $100K
Go-live: 2026-07-15 (7 weeks away)
Done so far: {done_count} tasks completed

Current backlog:
{backlog_text}

Ideas to consider:
{ideas_text}

Strategy context:
{self.strategy[:2000]}

What should be the next sprint focus?"""

        return self._ask_claude(system, user)

    def review_idea(self, idea_text: str) -> dict:
        """Review a new idea and return {verdict, priority, action, notes}."""
        system = """You are a senior architect reviewing new feature ideas for a DeFi paper trading system.
Evaluate each idea on: feasibility, value, risk, alignment with go-live goal.
Return JSON with: verdict (APPROVE/DEFER/REJECT), priority (HIGH/MEDIUM/LOW),
action (ADD_TO_BACKLOG/ADD_TO_FEATURES/DEFER_POST_GOLIVE/REJECT),
notes (2-3 sentences explaining why).
Return only valid JSON, no other text."""

        user = (
            f"Review this idea for the SPA DeFi paper trading project:\n\n"
            f"{idea_text}\n\n"
            f"Context: 7 weeks to go-live, $100K paper trading, targeting 7.3% APY."
        )

        response = self._ask_claude(system, user)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {
                "verdict": "DEFER",
                "priority": "LOW",
                "action": "DEFER_POST_GOLIVE",
                "notes": response,
            }

    def plan_sprint(self) -> str:
        """Generate a structured sprint plan from the current backlog."""
        backlog = self.kanban["columns"].get("backlog", [])[:10]
        in_progress = self.kanban["columns"].get("in_progress", [])

        system = """You are a senior architect writing a sprint plan for a DeFi paper trading system.
Format as a numbered list with:
- Task title
- What to build (1-2 sentences)
- Files to create/modify
- Acceptance criteria
Keep it technical and specific."""

        user = f"""Create a 5-task sprint plan from this backlog:
{json.dumps(backlog, indent=2)}

Currently in progress: {json.dumps(in_progress, indent=2)}
Go-live: 2026-07-15 (7 weeks). Priority: stability over new features."""

        return self._ask_claude(system, user)

    def weekly_status(self) -> str:
        """Generate weekly status summary suitable for Telegram."""
        done = self.kanban["columns"].get("done", [])
        backlog = self.kanban["columns"].get("backlog", [])

        recent_done = done[-10:] if len(done) > 10 else done

        system = (
            "Write a brief weekly status update for a DeFi trading system project. "
            "Max 300 words. Telegram-friendly (no heavy markdown)."
        )
        user = (
            f"Recent completions: {json.dumps(recent_done, indent=2)}\n"
            f"Remaining backlog: {len(backlog)} items\n"
            f"Go-live in 7 weeks. Generate weekly status."
        )

        return self._ask_claude(system, user)

    # ── Kanban mutations ──────────────────────────────────────────────────────

    def promote_idea(self, idea_id: str, target_column: str):
        """Move an idea from 'ideas' to 'backlog' or 'features'."""
        ideas = self.kanban["columns"].get("ideas", [])
        idea = next((i for i in ideas if i.get("id") == idea_id), None)
        if not idea:
            print(f"Idea {idea_id} not found")
            return
        self.kanban["columns"]["ideas"] = [
            i for i in ideas if i.get("id") != idea_id
        ]
        self.kanban["columns"].setdefault(target_column, []).append(idea)
        self._save_kanban(self.kanban)
        print(f"Moved {idea_id} to {target_column}")

    def move_card(self, item_id: str, to_column: str):
        """Move any card between columns."""
        for col_name, col_items in self.kanban["columns"].items():
            for item in col_items:
                if item.get("id") == item_id:
                    self.kanban["columns"][col_name] = [
                        i for i in col_items if i.get("id") != item_id
                    ]
                    self.kanban["columns"].setdefault(to_column, []).append(item)
                    self._save_kanban(self.kanban)
                    print(f"Moved {item_id}: {col_name} → {to_column}")
                    return
        print(f"Item {item_id} not found")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    import argparse

    p = argparse.ArgumentParser(description="SPA Architect Agent")
    p.add_argument(
        "--command",
        choices=["review-backlog", "plan-sprint", "review-ideas", "weekly-status"],
        default="review-backlog",
    )
    p.add_argument("--idea", type=str, help="Idea text to review (for review-ideas)")
    args = p.parse_args()

    arch = SpaArchitect()

    if args.command == "review-backlog":
        print(arch.review_backlog())

    elif args.command == "plan-sprint":
        print(arch.plan_sprint())

    elif args.command == "review-ideas":
        if args.idea:
            result = arch.review_idea(args.idea)
            print(json.dumps(result, indent=2))
        else:
            ideas = arch.kanban["columns"].get("ideas", [])
            if not ideas:
                print("No ideas in KANBAN.json to review.")
            for idea in ideas:
                print(f"\n--- {idea['id']}: {idea['title']} ---")
                combined = idea["title"] + ": " + idea.get("description", "")
                result = arch.review_idea(combined)
                print(json.dumps(result, indent=2))

    elif args.command == "weekly-status":
        print(arch.weekly_status())


if __name__ == "__main__":
    main()
