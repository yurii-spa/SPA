"""Разбор входящих — отдельно от исполнения (ADR-154 §3). Детерминированный отчёт, БЕЗ правки карточек.

Замер 27.10 (origin/main): inbox-карточек `new` — 311, из них без приоритета 270 (в замере ADR-154
было 85). Разбор `new` (тип · готовность к исполнению · дубли) жил шагом 1 протокола СЕССИИ и
проигрывал исполнению тот же слот — разбирать было некому. Здесь разбор — дешёвый детерминированный
шаг ДО сессии в том же часовом цикле: он ничего не пишет в карточки (массовая правка трекера при
конкурентных писателях запрещена), а кладёт отчёт `data/inbox_triage.json` и одну строку сводки.

Что считает:
* ``kind`` — объявленный тип записи (`intake_kind`/`type`), иначе ``UNKNOWN`` (не угадывается);
* ``ready`` — у карточки объявлена проверка результата (`acceptance_probe` или «проба: …» в тексте) —
  её можно брать в исполнение; без проверки работа не начинается (правило приёмки);
* ``dup_groups`` — карточки с одинаковым нормализованным заголовком (кандидаты в дубли — решает
  человек или сессия, отчёт ничего не сливает);
* ``age_days`` — от `created`/`submitted_at`; нет даты ⇒ ``None`` (не измерено), не ноль.
# LLM_FORBIDDEN
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

SCHEMA = "inbox-triage/1"
_PROBE_RE = re.compile(r"(?im)(?:^|[\s(])(?:проба|probe)\s*:\s*`?[A-Za-z0-9_]+")


def _fm(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    for line in text[3:end if end > 0 else len(text)].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _norm_title(t: str) -> str:
    t = re.sub(r"[\W_]+", " ", (t or "").lower(), flags=re.U)
    return re.sub(r"\s+", " ", t).strip()


def _date(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00")[:25])
    except ValueError:
        try:
            d = datetime.strptime(v[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def triage(tracker_dir: Path, *, now: Optional[datetime] = None) -> Dict:
    now = now or datetime.now(timezone.utc)
    rows: List[Dict] = []
    by_title = defaultdict(list)
    for p in sorted(Path(tracker_dir).glob("inbox-*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _fm(text)
        if fm.get("status") != "new":
            continue
        created = _date(fm.get("submitted_at") or fm.get("created"))
        row = {"card": p.name, "title": fm.get("title") or p.stem,
               "kind": fm.get("intake_kind") or fm.get("type") or "UNKNOWN",
               "ready": bool(fm.get("acceptance_probe") or _PROBE_RE.search(text)),
               "priority": fm.get("priority") or None,
               "age_days": round((now - created).total_seconds() / 86400.0, 1) if created else None}
        rows.append(row)
        by_title[_norm_title(row["title"])].append(p.name)
    dups = sorted([sorted(v) for k, v in by_title.items() if k and len(v) > 1], key=len, reverse=True)
    ages = [r["age_days"] for r in rows if r["age_days"] is not None]
    return {"schema": SCHEMA, "generated_at": now.isoformat(), "new_total": len(rows),
            "ready": sum(r["ready"] for r in rows), "no_priority": sum(r["priority"] is None for r in rows),
            "kind_unknown": sum(r["kind"] == "UNKNOWN" for r in rows),
            "age_unmeasured": len(rows) - len(ages), "oldest_days": max(ages) if ages else None,
            "dup_groups": dups, "rows": rows}


def summary_line(rep: Dict) -> str:
    return (f"РАЗБОР ВХОДЯЩИХ (детерминированный, до сессии): new {rep['new_total']}, готовы к исполнению "
            f"(объявлена проверка) {rep['ready']}, без приоритета {rep['no_priority']}, тип не объявлен "
            f"{rep['kind_unknown']}, групп-кандидатов в дубли {len(rep['dup_groups'])}; отчёт data/inbox_triage.json. ")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Разбор входящих: отчёт без правки карточек")
    ap.add_argument("--tracker-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    from spa_core.utils.atomic import atomic_save
    try:
        rep = triage(Path(a.tracker_dir))
        atomic_save(rep, a.out)
    except Exception as exc:  # noqa: BLE001 — отчёт не смеет уронить цикл; говорит вслух
        print(f"РАЗБОР ВХОДЯЩИХ НЕ ИЗМЕРЕН ({type(exc).__name__}: {exc}). ", end="")
        return 2
    print(summary_line(rep), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
