"""fleet_economics — экономика цеха: сколько работает и сколько это стоит.

Внедрение по книге AI1 гл. 19 («Экономика агента»), мандат владельца 2026-08-20:
до сих пор НИ ОДИН артефакт не отвечал на вопрос «сколько система сделала за
сутки и во что это обошлось» — расход подписки Claude был невидим (инцидент
52 цикла/сутки 08.08 заметили случайно, по расхождению данных).

Считает ДЕТЕРМИНИРОВАННО по git-истории (никакой LLM):
  * cycles_24h  — коммиты вида «цикл #N» за 24 часа (каждый = headless-сессия);
  * commits_24h — все коммиты за 24 часа (общий выпуск цеха);
  * cost_estimate_usd — cycles × SPA_COST_PER_CYCLE_USD (owner-tunable env;
    не задана → None и честная пометка «стоимость не оценена»).

CLI (паттерн analytics-модулей):
    python3 -m spa_core.monitoring.fleet_economics --check   # вычислить, не писать
    python3 -m spa_core.monitoring.fleet_economics --run     # + атомарная запись
Артефакт: ``data/fleet_economics.json``. Pure stdlib, offline, exit 0 всегда.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_REL = "fleet_economics.json"
_CYCLE_RE = re.compile(r"цикл\s*#\d+", re.IGNORECASE)
_GIT_TIMEOUT_S = 20


def _default_git_subjects(repo_root: Path, since_hours: int) -> Optional[list[str]]:
    """Темы коммитов за окно. ``None`` — git недоступен (не падаем)."""
    try:
        proc = subprocess.run(
            ["git", "log", f"--since={since_hours}.hours", "--format=%s"],
            cwd=str(repo_root), capture_output=True, text=True,
            timeout=_GIT_TIMEOUT_S,
        )
        if proc.returncode != 0:
            return None
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]
    except Exception as exc:  # noqa: BLE001 — экономика не важнее работы цеха
        log.warning("fleet_economics: git log failed: %s", exc)
        return None


def summary(
    repo_root: Optional[Path] = None,
    *,
    since_hours: int = 24,
    now: Optional[datetime] = None,
    subjects_fn: Callable[[Path, int], Optional[list[str]]] = _default_git_subjects,
) -> dict:
    """Сводка экономики за окно. Никогда не бросает.

    ``subjects_fn`` инжектируется тестами (offline, без git).
    """
    root = Path(repo_root) if repo_root else _REPO_ROOT
    dt = now or datetime.now(timezone.utc)
    out: dict = {
        "generated_at": dt.isoformat(),
        "window_hours": since_hours,
        "source": "git log --format=%s (детерминированно, LLM не участвует)",
        "cycles": None,
        "commits": None,
        "cost_per_cycle_usd": None,
        "cost_estimate_usd": None,
        "note": "",
    }
    subjects = subjects_fn(root, since_hours)
    if subjects is None:
        out["note"] = "git недоступен — экономика не измерена (это сигнал, не ноль)"
        return out
    out["commits"] = len(subjects)
    out["cycles"] = sum(1 for s in subjects if _CYCLE_RE.search(s))

    raw_cost = os.environ.get("SPA_COST_PER_CYCLE_USD", "").strip()
    if raw_cost:
        try:
            per = float(raw_cost)
            out["cost_per_cycle_usd"] = per
            out["cost_estimate_usd"] = round(out["cycles"] * per, 2)
        except ValueError:
            out["note"] = f"SPA_COST_PER_CYCLE_USD={raw_cost!r} не число — стоимость не оценена"
    else:
        out["note"] = ("стоимость не оценена: задай SPA_COST_PER_CYCLE_USD "
                       "(средняя цена одной headless-сессии, $)")
    return out


def write_artifact(data_dir: Optional[Path] = None, **kw) -> Path:
    """Атомарная запись артефакта (tmp + os.replace). Возвращает путь."""
    from spa_core.utils.atomic import atomic_save

    ddir = Path(data_dir) if data_dir else _REPO_ROOT / "data"
    ddir.mkdir(parents=True, exist_ok=True)
    path = ddir / ARTIFACT_REL
    atomic_save(summary(**kw), str(path))
    return path


def _main() -> None:  # pragma: no cover — тонкая CLI-обёртка
    import argparse

    parser = argparse.ArgumentParser(description="Экономика цеха (AI1 гл.19)")
    parser.add_argument("--run", action="store_true", help="записать артефакт")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()
    if args.run:
        path = write_artifact(Path(args.data_dir) if args.data_dir else None)
        print(f"written: {path}")
    print(json.dumps(summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":  # pragma: no cover
    _main()
