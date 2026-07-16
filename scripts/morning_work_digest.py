#!/usr/bin/env python3
"""morning_work_digest — «что сделано за вчера», простым языком, в Telegram каждое утро.

Owner-requested 2026-07-16: широкими мазками, человеческим языком (не тех-жаргон), в 09:00.
Отдельно от торгового daily_report — это дайджест РАБОТЫ/девелопмента, не портфеля.

Собирает вчерашнюю активность из трёх источников (источник правды — git/файлы):
  1. docs/journal/<ISO-week>.md — записи оркестратора/сессий за вчера,
  2. data/session_changes.jsonl — координационный лог (кто что делал),
  3. git-коммиты origin/main за вчера — что реально уехало.
Превращает в короткую сводку ПРОСТЫМ русским через локальный headless `claude -p`
(LLM здесь допустим — это репортинг, НЕ risk/execution), и шлёт единым TelegramBot.

Fail-safe: нет активности → «вчера тихо». LLM недоступен → отправляем сырой bullet-fallback,
НЕ молчим. LLM здесь не в risk-пути (инвариант соблюдён).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_CLAUDE = os.environ.get("SPA_CLAUDE_BIN") or "/Users/yuriikulieshov/.local/bin/claude"
_CLAUDE_TIMEOUT_S = 180


def _yesterday_bounds(now: datetime) -> tuple[datetime, datetime, str]:
    """Return (start, end, human-date) for 'yesterday' in local time."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=1)
    return start, today, start.strftime("%Y-%m-%d")


def _gather_journal(day: str) -> str:
    """Journal lines whose section/date matches yesterday (best-effort)."""
    wk_dir = _REPO / "docs" / "journal"
    if not wk_dir.is_dir():
        return ""
    out: list[str] = []
    for f in sorted(wk_dir.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # keep blocks under a "## <day>" heading (and their following lines until next ##)
        keep, cur = [], False
        for line in text.splitlines():
            if line.startswith("## "):
                cur = day in line
            if cur:
                keep.append(line)
        if keep:
            out.append("\n".join(keep))
    return "\n".join(out)[:8000]


def _gather_session_changes(start: datetime, end: datetime) -> str:
    """session_changes.jsonl summaries stamped within [start, end)."""
    f = _REPO / "data" / "session_changes.jsonl"
    if not f.is_file():
        return ""
    lines: list[str] = []
    try:
        for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(raw)
            except (ValueError, TypeError):
                continue
            ts = str(d.get("ts", ""))[:19]
            try:
                t = datetime.fromisoformat(ts)
                if t.tzinfo is not None:
                    t = t.replace(tzinfo=None)
            except ValueError:
                continue
            if start.replace(tzinfo=None) <= t < end.replace(tzinfo=None):
                s = str(d.get("summary", "")).strip()
                if s:
                    lines.append(f"- {s}")
    except OSError:
        return ""
    return "\n".join(lines[-60:])[:6000]


def _gather_commits(day: str) -> str:
    """git commits on origin/main authored on yesterday (subject lines)."""
    try:
        subprocess.run(["git", "fetch", "origin", "main"], cwd=str(_REPO),
                       capture_output=True, timeout=30)
        out = subprocess.run(
            ["git", "log", "origin/main", "--since", f"{day} 00:00",
             "--until", f"{day} 23:59", "--pretty=%s"],
            cwd=str(_REPO), capture_output=True, text=True, timeout=20,
        )
        subjects = [l for l in out.stdout.splitlines() if l.strip()]
        return "\n".join(f"- {s}" for s in subjects[:80])[:6000]
    except (OSError, subprocess.SubprocessError):
        return ""


_PROMPT = """Ты пишешь УТРЕННИЙ дайджест владельцу проекта: «что сделано за вчера».
ПРАВИЛА: простой человеческий русский, ШИРОКИМИ мазками, без тех-жаргона и без имён файлов/
коммитов. Пиши, ЧТО это дало (ценность), а не как. 5-9 коротких буллетов максимум, каждый с
эмодзи. В конце — одна строка-итог. Если данных мало — честно скажи «вчера было тихо».
Формат — обычный текст (не markdown-таблицы). Заголовок: «☀️ Что сделано вчера (<дата>)».

Вот сырые данные за вчерашний день (журнал, лог изменений, коммиты) — переведи их для человека:

<DATA>
"""


def build_digest(now: datetime | None = None) -> tuple[str, str]:
    """Return (raw_bullets_fallback, human_text). human_text via claude; fallback if it fails."""
    now = now or datetime.now()
    start, end, day = _yesterday_bounds(now)
    journal = _gather_journal(day)
    changes = _gather_session_changes(start, end)
    commits = _gather_commits(day)

    raw = "\n\n".join(x for x in [
        ("ЖУРНАЛ:\n" + journal) if journal else "",
        ("ИЗМЕНЕНИЯ:\n" + changes) if changes else "",
        ("КОММИТЫ:\n" + commits) if commits else "",
    ] if x).strip()

    if not raw:
        txt = f"☀️ Что сделано вчера ({day})\n\nВчера было тихо — существенных изменений нет."
        return raw, txt

    # plain-language via headless `claude -p` — PURE TEXT SUMMARIZATION, no tools, so it
    # runs WITHOUT --dangerously-skip-permissions (verified: a summarize-this-text prompt
    # invokes no tools → no permission prompt → exits cleanly). Reporting path, not a risk
    # path. Deliberately NOT skip-permissions: nothing here should read files or run commands.
    try:
        proc = subprocess.run(
            [_CLAUDE, "-p", _PROMPT.replace("<DATA>", raw[:12000])],
            capture_output=True, text=True, timeout=_CLAUDE_TIMEOUT_S,
            env={**os.environ},
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return raw, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

    # fallback: raw bullets, honest (never silent)
    fallback = (f"☀️ Что сделано вчера ({day}) — сырьём (авто-сводка недоступна):\n\n"
                + raw[:2500])
    return raw, fallback


def main() -> int:
    _, text = build_digest()
    if "--dry-run" in sys.argv:
        print(text)
        return 0
    try:
        from spa_core.telegram.bot import TelegramBot

        TelegramBot().send_message(text)
        print("digest sent")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"digest send failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
