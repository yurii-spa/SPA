#!/usr/bin/env python3
"""Убрать из очереди карточки-фантомы, рождённые УПАВШИМ классификатором (авария 11.08.2026).

Что произошло. `ask_router.classify_and_answer` отдавал падение headless `claude`
(исключение / ненулевой код выхода / пустой ответ) как обычный на вид вердикт
`("unclear", "Не смог обработать сообщение…")`. Интейк честно исполнял его как вердикт:
на каждое входящее выпускал карточку-ВОПРОС ВЛАДЕЛЬЦУ «Уточнение по заметке: …» и закрывал
исходное задание как `done`. За 11.08 так родилось 44 карточки — все 44 из 44 с дословным
fallback-текстом, настоящих вопросов ноль, — и 44 задания оказались «сделаны», не будучи
сделанными. Причина закрыта в коде (отдельный вид `ask_router.UNAVAILABLE`); этот скрипт
убирает уже нанесённый ущерб.

Как отличается фантом от настоящего вопроса (иначе чинить нельзя). Признак — СОВОКУПНОСТЬ,
любое несовпадение ⇒ карточку НЕ ТРОГАЕМ (fail-CLOSED, ложный пропуск дешевле ложного закрытия):
  * тип `owner-decision`, статус `needs-owner`, `source: intake`;
  * заголовок начинается с «Уточнение по заметке: »;
  * в секции «## Что от тебя нужно» стоит ДОСЛОВНЫЙ текст упавшего классификатора.
Настоящее «непонятно» несёт на этом месте вопрос МОДЕЛИ по существу — под признак не попадает.

Что делает с каждым найденным фантомом:
  1. исходное задание (inbox-карточка с тем же заголовком), закрытое `done` в ту же аварию,
     возвращается в `new` — направление fail-CLOSED: заново открыть уже сделанное дёшево
     (цикл увидит и закроет), оставить незакрытым реальное задание — дорого;
  2. сам фантом переводится в `done` с пометкой в теле — ПОЧЕМУ закрыт (не «решено владельцем»).
     Владелец эти карточки НИКОГДА не видел: сторож `owner_decision_pending` показывает, что
     ни одна из них не была ему отправлена. Инвариант #14 не задет: `owner-done` не ставится
     ни здесь, ни где-либо ещё — этот статус остаётся только за владельцем.

По умолчанию — СУХОЙ ПРОГОН (ничего не пишет). Запись только с `--apply`.
Только stdlib, без сети.

    python3 scripts/repair_phantom_intake_cards.py                 # показать, что нашлось
    python3 scripts/repair_phantom_intake_cards.py --apply         # выполнить
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

#: Дословные тексты, которыми `ask_router` отвечал, когда классификатор не ответил.
#: Это ПОДПИСЬ аварии: настоящий вопрос модели так выглядеть не может.
_OUTAGE_SIGNATURES = (
    "Не смог обработать сообщение. Переформулируй или пришли как /task <текст>.",
    "Пустой ответ. Переформулируй или пришли как /task <текст>.",
)

_TITLE_PREFIX = "Уточнение по заметке: "

_CLOSE_NOTE = (
    "\n\n---\n"
    "> 🧹 **Закрыто автоматически (не решением владельца).** Эта карточка — не вопрос, а след\n"
    "> аварии 11.08.2026: классификатор входящих был недоступен, и его служебный ответ\n"
    "> «{sig}» был принят за вердикт «текст непонятен».\n"
    "> Владельцу карточка не отправлялась ни разу. Причина закрыта в коде: недоступность\n"
    "> классификатора теперь отдельный вид `ask_router.UNAVAILABLE`, по которому интейк\n"
    "> оставляет входящее как есть и вопросов не создаёт. Исходное задание возвращено в работу.\n"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _field(text: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}:\s*(.*?)\s*$", text, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip('"').strip()


def _asked_section(text: str) -> str:
    """Содержимое секции «## Что от тебя нужно» (до следующего заголовка)."""
    m = re.search(r"^## Что от тебя нужно\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def find_phantoms(tracker_dir: Path) -> list[dict]:
    """Карточки-фантомы + найденные для них исходные задания. Ничего не пишет."""
    inbox_by_title: dict[str, list[Path]] = {}
    for p in sorted(tracker_dir.glob("inbox-*.md")):
        inbox_by_title.setdefault(_field(_read(p), "title"), []).append(p)

    found: list[dict] = []
    for p in sorted(tracker_dir.glob("*.md")):
        name = p.name
        if not (name.startswith("own-") or name.startswith("owner-decision")):
            continue
        text = _read(p)
        title = _field(text, "title")
        if _field(text, "status") != "needs-owner":
            continue
        if _field(text, "source") != "intake":
            continue
        if not title.startswith(_TITLE_PREFIX):
            continue
        asked = _asked_section(text)
        sig = next((s for s in _OUTAGE_SIGNATURES if s in asked), None)
        if sig is None:
            continue  # настоящий вопрос модели — НЕ ТРОГАЕМ

        source_title = title[len(_TITLE_PREFIX):]
        sources = inbox_by_title.get(source_title, [])
        reopen = [q for q in sources if _field(_read(q), "status") == "done"]
        found.append({
            "phantom": p,
            "signature": sig,
            "source_title": source_title,
            "sources": sources,
            "reopen": reopen,
        })
    return found


def repair(tracker_dir: Path, *, apply: bool) -> dict:
    from spa_core.owner_queue.queue import set_status

    phantoms = find_phantoms(tracker_dir)
    closed, reopened, orphaned = [], [], []

    for item in phantoms:
        if not item["sources"]:
            orphaned.append(item["source_title"])
        for q in item["reopen"]:
            if apply:
                set_status(q, "new")
            reopened.append(q.name)
        if apply:
            text = _read(item["phantom"])
            if "Закрыто автоматически" not in text:
                item["phantom"].write_text(
                    text.rstrip() + _CLOSE_NOTE.format(sig=item["signature"]), encoding="utf-8")
            set_status(item["phantom"], "done")
        closed.append(item["phantom"].name)

    return {
        "applied": apply,
        "phantoms_closed": len(closed),
        "sources_reopened": len(reopened),
        "sources_not_found": len(orphaned),
        "closed": closed,
        "reopened": reopened,
        "orphaned": orphaned,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tracker-dir", default=str(_REPO / "nimbalyst-local" / "tracker"))
    ap.add_argument("--apply", action="store_true", help="выполнить (по умолчанию — сухой прогон)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    tracker = Path(args.tracker_dir)
    if not tracker.is_dir():
        print(f"нет каталога трекера: {tracker}", file=sys.stderr)
        return 2

    res = repair(tracker, apply=args.apply)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    head = "ВЫПОЛНЕНО" if res["applied"] else "СУХОЙ ПРОГОН (ничего не записано)"
    print(f"— чистка фантомов упавшего классификатора · {head} —")
    print(f"карточек-фантомов: {res['phantoms_closed']}")
    print(f"исходных заданий возвращено в работу (new): {res['sources_reopened']}")
    if res["orphaned"]:
        print(f"исходников не найдено в трекере: {res['sources_not_found']} "
              f"(текст задания сохранён в теле фантома — он не закрыт удалением)")
        for t in res["orphaned"]:
            print(f"   · {t}")
    if not res["applied"] and res["phantoms_closed"]:
        print("\nповторить с --apply, чтобы записать")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
