"""
SPA Architect Agent (v2.4 — BL-002)

Модель: Claude Sonnet 4.6 (в будущем; текущая версия — pure Python,
        детерминированная, без LLM-вызовов, чтобы тесты были стабильны).

Роль:   Читает KANBAN.json, анализирует состояние проекта, предлагает
        набор задач на следующий спринт под бюджет часов и публикует
        результат на шину сообщений (topic="architect.proposal").

Логика:
  1. load_kanban()        — читает доску
  2. analyze_state()      — totals, HIGH-priority open, stale review,
                            go-live статус, кандидаты в следующий спринт
  3. propose_sprint()     — упаковывает кандидатов в бюджет часов
  4. run()                — публикует analysis + proposal в шину
  5. dump_proposal()      — пишет proposal JSON для дашборда
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from message_bus.bus import MessageBus
from message_bus.topics import Priority


# Возможные приоритетные веса для сортировки (меньше — раньше)
_PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

# Подсказки для классификатора manual-задач
_MANUAL_TITLE_TOKENS = ("user action",)
_MANUAL_TAGS = {"infra"}

# Спринт-сборщик старается не выходить за target_hours,
# но допускает one-shot overshoot до этого множителя.
_OVERSHOOT_FACTOR = 2.0

_STALE_REVIEW_DAYS = 5


def _safe_load_json(path: Path) -> dict | list | None:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _parse_estimate(estimate: str | float | int | None) -> float:
    """Парсит '12h' / '0.5h' / 2 → float (часы). Невалидные → 0.0."""
    if estimate is None:
        return 0.0
    if isinstance(estimate, (int, float)):
        return float(estimate)
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*h?\s*$", str(estimate), re.I)
    if not m:
        return 0.0
    return float(m.group(1))


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Поддержка как '2026-05-22', так и '2026-05-22T08:25:03Z'
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    # Нормализуем в UTC-aware (чтобы date-only строки можно было сравнивать с now())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_manual_task(task: dict) -> bool:
    title = (task.get("title") or "").lower()
    if any(tok in title for tok in _MANUAL_TITLE_TOKENS):
        return True
    tags = {(t or "").lower() for t in task.get("tags", [])}
    # infra-only без backend/feature считаем "ручной" инфра-задачей
    if tags and tags.issubset(_MANUAL_TAGS):
        return True
    return False


def _is_done(task: dict) -> bool:
    return (task.get("status") or "").lower() == "done"


class ArchitectAgent(BaseAgent):
    """
    Architect Agent — анализирует доску и предлагает следующий спринт.
    Не принимает решений за пользователя: лишь предлагает (publish).
    """

    AGENT_ID = "architect_agent"

    def __init__(
        self,
        bus: MessageBus,
        db_path: Path | None = None,
        kanban_path: Path | None = None,
        golive_path: Path | None = None,
    ):
        super().__init__(bus, db_path)
        # repo_root = …/SPA_Claude  (this file: …/SPA_Claude/spa_core/agents/architect_agent.py)
        repo_root = Path(__file__).resolve().parent.parent.parent
        self.kanban_path: Path = (
            Path(kanban_path) if kanban_path else repo_root / "KANBAN.json"
        )
        self.golive_path: Path = (
            Path(golive_path) if golive_path else repo_root / "data" / "golive_readiness.json"
        )
        self._repo_root: Path = repo_root

    # ── I/O ──────────────────────────────────────────────────────────────────

    def load_kanban(self) -> dict:
        """Читает KANBAN.json. Если файла нет — возвращает пустую структуру."""
        data = _safe_load_json(self.kanban_path)
        if not isinstance(data, dict):
            return {
                "last_updated": None,
                "updated_by": None,
                "columns": {
                    "ideas": [],
                    "features": [],
                    "backlog": [],
                    "in_progress": [],
                    "review": [],
                    "done": [],
                },
            }
        # Гарантируем все стандартные колонки
        data.setdefault("columns", {})
        for col in ("ideas", "features", "backlog", "in_progress", "review", "done"):
            data["columns"].setdefault(col, [])
        return data

    def _load_golive(self) -> dict:
        data = _safe_load_json(self.golive_path)
        if not isinstance(data, dict):
            return {"verdict": "UNKNOWN", "criteria_pass_count": 0}
        criteria = data.get("criteria", {}) or {}
        pass_count = sum(
            1 for c in criteria.values()
            if isinstance(c, dict) and c.get("status") == "PASS"
        )
        return {
            "verdict": data.get("verdict", "UNKNOWN"),
            "criteria_pass_count": data.get("criteria_passed", pass_count),
            "criteria_total": data.get("criteria_total", len(criteria)),
            "days_remaining": data.get("days_remaining"),
        }

    # ── Analysis ─────────────────────────────────────────────────────────────

    def _collect_open_tasks(self, kanban: dict) -> list[dict]:
        """backlog + features + in_progress + review, не done."""
        cols = kanban.get("columns", {})
        out: list[dict] = []
        for col_name in ("backlog", "features", "in_progress", "review"):
            for t in cols.get(col_name, []):
                if _is_done(t):
                    continue
                t = dict(t)
                t["_column"] = col_name
                out.append(t)
        return out

    def _high_priority_open(self, open_tasks: list[dict]) -> list[dict]:
        high = [
            t for t in open_tasks
            if (t.get("priority") or "").upper() == "HIGH"
            and t.get("_column") in ("backlog", "features", "in_progress")
        ]
        high.sort(key=lambda t: (
            _PRIORITY_RANK.get((t.get("priority") or "").upper(), 9),
            t.get("added", ""),
        ))
        return high

    def _stale_review(self, kanban: dict, today: datetime | None = None) -> list[dict]:
        today = today or datetime.now(timezone.utc)
        out: list[dict] = []
        for t in kanban.get("columns", {}).get("review", []):
            if _is_done(t):
                continue
            added = _parse_iso_date(t.get("added"))
            if not added:
                continue
            age_days = (today - added).days
            if age_days >= _STALE_REVIEW_DAYS:
                t2 = dict(t)
                t2["age_days"] = age_days
                out.append(t2)
        return out

    def _rank_for_sprint(self, task: dict) -> tuple[int, str]:
        """
        Меньшее значение — раньше попадает в спринт.

        Tier:
          0 — HIGH from backlog, not manual
          1 — HIGH from features, sprint != "v2.0"
          2 — MEDIUM with tags 'golive' or 'bug'
          3 — остальные MEDIUM
          9 — всё остальное (LOW и т.п.)
        """
        priority = (task.get("priority") or "").upper()
        col = task.get("_column")
        tags = {(t or "").lower() for t in task.get("tags", [])}
        sprint = task.get("sprint")

        if priority == "HIGH" and col == "backlog" and not _is_manual_task(task):
            tier = 0
        elif priority == "HIGH" and col == "features" and sprint != "v2.0":
            tier = 1
        elif priority == "MEDIUM" and ({"golive", "bug"} & tags):
            tier = 2
        elif priority == "MEDIUM":
            tier = 3
        else:
            tier = 9
        return (tier, task.get("added", ""))

    def _next_sprint_candidates(self, open_tasks: list[dict]) -> list[dict]:
        eligible = [t for t in open_tasks if not _is_manual_task(t)]
        eligible.sort(key=self._rank_for_sprint)

        labels = {
            0: "HIGH backlog (not manual)",
            1: "HIGH feature (non-v2.0)",
            2: "MEDIUM tagged golive/bug",
            3: "MEDIUM other",
            9: "Lower priority",
        }
        candidates: list[dict] = []
        for t in eligible[:3]:
            tier, _ = self._rank_for_sprint(t)
            candidates.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "priority": t.get("priority"),
                "estimate": t.get("estimate"),
                "tags": list(t.get("tags") or []),
                "why_picked": labels.get(tier, "Fallback pick"),
            })
        return candidates

    def analyze_state(self) -> dict:
        kanban = self.load_kanban()
        cols = kanban.get("columns", {})

        totals = {
            "ideas":       len(cols.get("ideas", [])),
            "features":    len(cols.get("features", [])),
            "backlog":     len(cols.get("backlog", [])),
            "in_progress": len(cols.get("in_progress", [])),
            "review":      len(cols.get("review", [])),
            "done":        len(cols.get("done", [])),
        }

        open_tasks = self._collect_open_tasks(kanban)

        return {
            "ts": self._ts(),
            "totals": totals,
            "high_priority_open": [
                {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "estimate": t.get("estimate"),
                    "column": t.get("_column"),
                    "tags": list(t.get("tags") or []),
                }
                for t in self._high_priority_open(open_tasks)
            ],
            "stale_review": [
                {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "age_days": t.get("age_days"),
                }
                for t in self._stale_review(kanban)
            ],
            "go_live_status": self._load_golive(),
            "next_sprint_candidates": self._next_sprint_candidates(open_tasks),
        }

    # ── Proposal ─────────────────────────────────────────────────────────────

    def propose_sprint(self, target_hours: float = 8.0) -> dict:
        kanban  = self.load_kanban()
        open_tasks = self._collect_open_tasks(kanban)
        eligible   = [t for t in open_tasks if not _is_manual_task(t)]
        eligible.sort(key=self._rank_for_sprint)

        picked: list[dict] = []
        total = 0.0
        max_overshoot = target_hours * _OVERSHOOT_FACTOR

        for t in eligible:
            est = _parse_estimate(t.get("estimate"))
            # Если уже что-то набрали и следующий выводит нас за overshoot — стоп.
            if picked and total + est > max_overshoot:
                continue
            picked.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "estimate": t.get("estimate"),
                "estimate_hours": est,
                "priority": t.get("priority"),
                "tags": list(t.get("tags") or []),
            })
            total += est
            if total >= target_hours:
                break

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        sprint_name = f"v2.5-proposed-{date_str}"

        if picked:
            top_ids = ", ".join(p["id"] for p in picked if p.get("id"))
            rationale = (
                f"Picked {len(picked)} task(s) totalling {total:.1f}h "
                f"under a target of {target_hours:.1f}h. "
                f"Selection prioritises HIGH backlog work, "
                f"then non-v2.0 HIGH features, then MEDIUM golive/bug. "
                f"Tasks: {top_ids}."
            )
        else:
            rationale = (
                f"No eligible non-manual tasks found under target {target_hours:.1f}h. "
                f"Backlog may be cleared or all remaining work is user-action."
            )

        return {
            "sprint_name": sprint_name,
            "target_hours": target_hours,
            "tasks": picked,
            "total_estimate": round(total, 2),
            "rationale": rationale,
        }

    # ── Dump ─────────────────────────────────────────────────────────────────

    def dump_proposal(self, out_path: Path | None = None) -> Path:
        """
        Сохраняет analysis + proposal в JSON (для дашборда).
        По умолчанию — <repo_root>/data/architect_proposal.json.
        """
        out_path = Path(out_path) if out_path else self._repo_root / "data" / "architect_proposal.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": self._ts(),
            "agent": self.AGENT_ID,
            "analysis": self.analyze_state(),
            "proposal": self.propose_sprint(),
        }
        out_path.write_text(json.dumps(payload, indent=2))
        self.log.info("Architect proposal dumped to %s", out_path)
        return out_path

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self) -> list[str]:
        """Опубликовать analysis + proposal в шину под topic 'architect.proposal'."""
        self._run_count += 1
        self.log.info("Run #%d — architect cycle", self._run_count)

        analysis = self.analyze_state()
        proposal = self.propose_sprint()

        payload = {
            "analysis": analysis,
            "proposal": proposal,
        }
        msg_id = self.publish("architect.proposal", payload, priority=Priority.NORMAL)
        self.log.info(
            "Architect published proposal '%s' with %d task(s)",
            proposal["sprint_name"], len(proposal["tasks"]),
        )
        return [msg_id]
