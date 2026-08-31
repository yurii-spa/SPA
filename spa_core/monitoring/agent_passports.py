"""agent_passports — у каждого агента флота обязан быть паспорт (AI1 гл.3/24).

Мандат владельца 2026-08-20. Книга: «десять пилотов превращаются в коллекцию
непонятных ботов» — у SPA 38+ launchd-агентов, и ровно из безпаспортности
выросли мёртвый bot_commands, 52 цикла/сутки и книги, «не отвечающие за свои
числа». Паспорт (гл. 3 + приложение книги) = деловая цель, метрика качества,
эскалация. Носитель — СУЩЕСТВУЮЩИЙ ``architecture/manifest.json``: у записи
агента появляется блок::

    "passport": {"goal": "...", "quality_metric": "...", "escalation": "..."}

Модуль ADVISORY и read-only: считает полноту, никого не выключает.
CLI: ``--check`` (по умолчанию) / ``--run`` (артефакт ``data/agent_passports.json``).
Pure stdlib, offline, exit 0 всегда.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_REL = "architecture/manifest.json"
ARTIFACT_REL = "agent_passports.json"
REQUIRED_FIELDS = ("goal", "quality_metric", "escalation")


def _has_passport(entry: dict) -> bool:
    pp = entry.get("passport")
    if not isinstance(pp, dict):
        return False
    return all(str(pp.get(f) or "").strip() for f in REQUIRED_FIELDS)


def audit(
    manifest_path: Optional[Path] = None,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Полнота паспортов по манифесту. Никогда не бросает.

    Возвращает ``{total, with_passport, missing: [labels], note}``;
    нечитаемый манифест → total=None и честная note (не ноль — «не измерено»).
    """
    path = Path(manifest_path) if manifest_path else _REPO_ROOT / MANIFEST_REL
    dt = now or datetime.now(timezone.utc)
    out: dict = {
        "generated_at": dt.isoformat(),
        "manifest": str(path),
        "required_fields": list(REQUIRED_FIELDS),
        "total": None,
        "with_passport": None,
        "missing": [],
        "note": "",
    }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        agents = doc.get("agents")
        if isinstance(agents, dict):
            entries = list(agents.values())
        elif isinstance(agents, list):
            entries = [e for e in agents if isinstance(e, dict)]
        else:
            out["note"] = "manifest.agents неожиданной формы — не измерено"
            return out
    except Exception as exc:  # noqa: BLE001 — advisory, не роняем вызывающего
        out["note"] = f"манифест не прочитан ({exc}) — не измерено"
        return out

    # Похороненному агенту паспорт не нужен — у него нет дела. Считать его
    # пробелом значит показывать владельцу число, которое НИКОГДА не станет
    # полным, и три имени, не требующих ничего. Замер 31.08: строка дневного
    # отчёта говорила «93/96 · без паспорта: cpa_daily, morning_digest,
    # telegram_watcher», и все трое — intent=retired. Строку, которая не может
    # позеленеть, перестают читать.
    live = [e for e in entries if e.get("intent") != "retired"]
    retired_missing = sorted(str(e.get("label") or "?")
                             for e in entries
                             if e.get("intent") == "retired" and not _has_passport(e))
    out["total"] = len(live)
    missing = [str(e.get("label") or "?") for e in live if not _has_passport(e)]
    out["with_passport"] = len(live) - len(missing)
    out["missing"] = sorted(missing)
    # Сузить — не спрятать: похороненные без паспорта остаются ВИДИМЫ отдельным
    # полем, иначе «сверено и нормально» станет неотличимо от «не сверяли».
    out["retired_without_passport"] = retired_missing
    out["retired_excluded"] = len(entries) - len(live)
    if missing:
        out["note"] = ("агент без паспорта = непонятный бот (AI1 гл.24); "
                       "заполнять блок passport в manifest.json")
    return out


def write_artifact(data_dir: Optional[Path] = None, **kw) -> Path:
    from spa_core.utils.atomic import atomic_save

    ddir = Path(data_dir) if data_dir else _REPO_ROOT / "data"
    ddir.mkdir(parents=True, exist_ok=True)
    path = ddir / ARTIFACT_REL
    atomic_save(audit(**kw), str(path))
    return path


def _main() -> None:  # pragma: no cover — тонкая CLI-обёртка
    import argparse

    parser = argparse.ArgumentParser(description="Паспорта агентов (AI1 гл.3)")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()
    if args.run:
        print(f"written: {write_artifact(Path(args.data_dir) if args.data_dir else None)}")
    print(json.dumps(audit(), ensure_ascii=False, indent=2))


if __name__ == "__main__":  # pragma: no cover
    _main()
