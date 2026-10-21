#!/usr/bin/env python3
"""Вернуть в работу задания, закрытые карточками-фантомами УПАВШЕГО классификатора (авария 11.08.2026).

Что произошло. `ask_router.classify_and_answer` отдавал падение headless `claude`
(исключение / ненулевой код выхода / пустой ответ) как обычный на вид вердикт
`("unclear", "Не смог обработать сообщение…")`. Интейк честно исполнял его как вердикт:
на каждое входящее выпускал карточку-ВОПРОС ВЛАДЕЛЬЦУ «Уточнение по заметке: …» и закрывал
исходное задание как `done`. За 11.08 так родилось 44 карточки — все 44 из 44 с дословным
fallback-текстом, настоящих вопросов ноль, — и 44 задания оказались «сделаны», не будучи
сделанными. Причина закрыта в коде (отдельный вид `ask_router.UNAVAILABLE`).

Как отличается фантом от настоящего вопроса. Признак — СОВОКУПНОСТЬ, любое несовпадение ⇒
карточку НЕ ТРОГАЕМ (fail-CLOSED, ложный пропуск дешевле ложного закрытия):
  * тип `owner-decision` ПО FRONTMATTER (имя файла само по себе не доказательство),
    статус `needs-owner`, `source: intake`;
  * заголовок начинается с «Уточнение по заметке: »;
  * в секции «## Что от тебя нужно» стоит ДОСЛОВНЫЙ текст упавшего классификатора.

Что скрипт делает — и чего НЕ делает (ADR-551, инв. #14, указание владельца 18.10).
  * Фантом — карточка РЕШЕНИЯ ВЛАДЕЛЬЦА. Скрипт её не меняет, не закрывает и ничего в неё
    не дописывает: закрыть вопрос владельца без его записанного ответа гейт ADR-551
    запрещает, и это верно. Фантомы только НАЗЫВАЮТСЯ — убрать их может владелец.
  * Исходное задание (inbox-карточка), закрытое `done` в ту же аварию, возвращается в
    `new` — направление fail-CLOSED: заново открыть сделанное дёшево, оставить
    незакрытым реальное задание дорого. Связь фантом → задание доказывается ДВУМЯ
    признаками: единственное задание с точно тем же заголовком И цитата «Текст: «…»»
    фантома дословно есть в теле задания.

Порядок (до первой записи — только чтение):
  1. собрать полный план: фантомы, задания, переходы, причины отказа;
  2. проверить ВСЁ: в наборе записи только inbox-карточки (по frontmatter И по имени),
     связь однозначна, каждый переход разрешён тем же гейтом, что у `set_status`
     (`queue.check_lifecycle`). Любой отказ ⇒ отказ ВСЕЙ операции, код 3, ни одного
     нового, изменённого или удалённого файла и ни одной записи в журнал;
  3. слепок исходных байтов и хешей во временный каталог ВНЕ дерева трекера;
     повторная сверка хешей перед записью (карточку могли поменять между планом и записью);
  4. запись через `queue.set_status` (каждый файл — tmp + os.replace);
  5. сбой на любом шаге ⇒ откат всех уже изменённых файлов к исходным байтам и сверка
     по хешам; откат подтверждён ⇒ код 4; не подтверждён ⇒ код 5, слепок СОХРАНЁН и путь
     к нему напечатан — нужно ручное вмешательство.

Ограничение гарантии (сказано вслух). Каждый файл заменяется атомарно, но набор из
НЕСКОЛЬКИХ файлов — нет: читатель трекера во время записи может увидеть часть заданий уже
открытыми, а часть — ещё нет. Блокировки трекера в архитектуре нет, поэтому конкурентный
писатель между сверкой хешей и записью не исключён (окно — миллисекунды на файл). Запись
перехода в журнал `data/tracker_status_audit.jsonl` (её делает `set_status`) при откате не
стирается — дописывается обратная запись отката.

По умолчанию — СУХОЙ ПРОГОН (ничего не пишет). Запись только с `--apply`.
Только stdlib, без сети.

    python3 scripts/repair_phantom_intake_cards.py                 # показать план
    python3 scripts/repair_phantom_intake_cards.py --apply         # выполнить
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
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

#: Сколько символов цитаты фантома обязано дословно найтись в теле задания.
#: Цитата длинного задания в фантоме бывает усечена, поэтому сверяется начало.
_QUOTE_PREFIX = 120

#: Коды выхода — каждый исход отдельным значением (инв. #17).
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3
EXIT_ROLLED_BACK = 4
EXIT_MANUAL = 5

_WRITER_SOURCE = "repair_phantom_intake_cards"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fm(text: str) -> dict:
    """Разобранный frontmatter — тем же разборщиком, что у очереди."""
    from spa_core.owner_queue.queue import _parse_frontmatter, _split_frontmatter
    lines, _ = _split_frontmatter(text)
    return _parse_frontmatter(lines) if lines else {}


def _fm_str(fm: dict, key: str) -> str:
    v = fm.get(key)
    return v.strip().strip('"').strip() if isinstance(v, str) else ""


def _card_type(fm: dict) -> str:
    """Тип карточки по frontmatter: `trackerStatus.type`, у старых `own-*` — верхний `type:`."""
    ts = fm.get("trackerStatus")
    if isinstance(ts, dict) and isinstance(ts.get("type"), str):
        return ts["type"].strip()
    return _fm_str(fm, "type")


def _body(text: str) -> str:
    from spa_core.owner_queue.queue import _split_frontmatter
    return _split_frontmatter(text)[1]


def _norm(s: str) -> str:
    return " ".join(s.split())


def _asked_section(text: str) -> str:
    """Содержимое секции «## Что от тебя нужно» (до следующего заголовка)."""
    m = re.search(r"^## Что от тебя нужно\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def _quoted_message(text: str) -> str:
    """Цитата входящего из фантома: «Текст: «…»» до следующего заголовка секции."""
    m = re.search(r"^Текст: «(.*?)»\s*$(?=\s*^## |\s*\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def find_phantoms(tracker_dir: Path) -> list[dict]:
    """Карточки-фантомы в статусе `needs-owner`. Ничего не пишет."""
    found: list[dict] = []
    for p in sorted(tracker_dir.glob("*.md")):
        text = _read(p)
        fm = _fm(text)
        if _card_type(fm) != "owner-decision":
            continue
        if _fm_str(fm, "status") != "needs-owner" or _fm_str(fm, "source") != "intake":
            continue
        title = _fm_str(fm, "title")
        if not title.startswith(_TITLE_PREFIX):
            continue
        sig = next((s for s in _OUTAGE_SIGNATURES if s in _asked_section(text)), None)
        if sig is None:
            continue  # настоящий вопрос модели — НЕ ТРОГАЕМ
        found.append({"phantom": p, "signature": sig,
                      "source_title": title[len(_TITLE_PREFIX):],
                      "quote": _quoted_message(text)})
    return found


def build_plan(tracker_dir: Path) -> dict:
    """Полный план операции и все причины отказа. Только чтение."""
    from spa_core.owner_queue.queue import LifecycleRefused, check_lifecycle

    inbox_by_title: dict[str, list[Path]] = {}
    for p in sorted(tracker_dir.glob("*.md")):
        fm = _fm(_read(p))
        if _card_type(fm) == "inbox" or p.name.startswith("inbox-"):
            inbox_by_title.setdefault(_fm_str(fm, "title"), []).append(p)

    phantoms = find_phantoms(tracker_dir)
    writes: list[dict] = []
    refusals: list[str] = []
    orphaned: list[str] = []
    untouched_sources: list[str] = []
    seen: set[Path] = set()

    for item in phantoms:
        sources = inbox_by_title.get(item["source_title"], [])
        name = item["phantom"].name
        if not sources:
            orphaned.append(item["source_title"])
            continue
        if len(sources) > 1:
            refusals.append(f"{name}: заголовку соответствуют {len(sources)} задания "
                            f"({', '.join(s.name for s in sources)}) — связь неоднозначна")
            continue
        src = sources[0]
        raw = src.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        fm = _fm(text)
        if not fm:
            refusals.append(f"{src.name}: у задания нет frontmatter — происхождение не проверить")
            continue
        quote = _norm(item["quote"])[:_QUOTE_PREFIX]
        if not quote or quote not in _norm(_body(text)):
            refusals.append(f"{name}: цитата входящего не найдена в теле {src.name} — "
                            f"связь по одному заголовку не доказательство")
            continue
        # Полномочия: писать можно ТОЛЬКО задание. Имя и frontmatter обязаны сказать одно и то же,
        # иначе это сомнение, а сомнение — отказ всей операции.
        ctype = _card_type(fm)
        if ctype != "inbox" or not src.name.startswith("inbox-"):
            refusals.append(f"{src.name}: цель записи не задание (тип {ctype or 'не указан'}) — "
                            f"решения владельца этот скрипт не трогает")
            continue
        old = _fm_str(fm, "status")
        if old != "done":
            untouched_sources.append(src.name)
            continue
        if src in seen:
            continue
        seen.add(src)
        try:
            check_lifecycle(ctype, old, "new", fm=fm, name=src.name)
        except LifecycleRefused as exc:
            refusals.append(str(exc))
            continue
        writes.append({"path": src, "old": old, "new": "new",
                       "sha256": _sha(raw), "phantom": name})

    return {"phantoms": [i["phantom"].name for i in phantoms], "writes": writes,
            "refusals": refusals, "orphaned": orphaned,
            "untouched_sources": untouched_sources}


def _restore(path: Path, data: bytes) -> None:
    """Вернуть байты: tmp в той же директории + os.replace (форма инв. #5 для байтов)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".repair_restore_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _default_write(path: Path, new_status: str) -> None:
    from spa_core.owner_queue.queue import set_status
    set_status(path, new_status)


def apply_plan(plan: dict, *, write=_default_write, restore=_restore,
               recovery_root: str | None = None) -> dict:
    """Исполнить план, проверенный `build_plan`. Возвращает исход с кодом выхода.

    `write`/`restore` — входы для тестов (внедрение сбоя на каждом шаге); по умолчанию
    настоящие `set_status` и атомарная замена байтов.
    """
    targets: list[dict] = plan["writes"]
    recovery = Path(tempfile.mkdtemp(prefix="repair_phantom_recovery_", dir=recovery_root))
    originals: dict[Path, bytes] = {}
    manifest = []
    for i, w in enumerate(targets):
        data = w["path"].read_bytes()
        if _sha(data) != w["sha256"]:
            return {"exit": EXIT_REFUSED, "recovery": None, "written": [],
                    "reason": f"{w['path'].name} изменилась между планом и записью — ничего не записано",
                    "_cleanup": recovery}
        originals[w["path"]] = data
        (recovery / f"{i:03d}.orig").write_bytes(data)
        manifest.append({"index": i, "path": str(w["path"]), "sha256": w["sha256"]})
    (recovery / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                            encoding="utf-8")

    written: list[Path] = []
    try:
        for w in targets:
            write(w["path"], w["new"])
            written.append(w["path"])
            fm = _fm(_read(w["path"]))
            if _fm_str(fm, "status") != w["new"]:
                raise RuntimeError(f"{w['path'].name}: после записи статус "
                                   f"{_fm_str(fm, 'status')!r}, ожидался {w['new']!r}")
    except Exception as exc:  # noqa: BLE001 — любой сбой ведёт к откату, причина в отчёте
        return _rollback(targets, originals, written, recovery, restore, exc)

    return {"exit": EXIT_OK, "recovery": None, "written": [p.name for p in written],
            "reason": "", "_cleanup": recovery}


def _rollback(targets, originals, written, recovery, restore, exc) -> dict:
    from spa_core.owner_queue.status_audit import record_status_write
    errors = []
    for w in targets:
        p = w["path"]
        try:
            if p.read_bytes() != originals[p]:
                restore(p, originals[p])
                record_status_write(p, old=w["new"], new=w["old"],
                                    source=f"{_WRITER_SOURCE}/rollback")
        except Exception as rexc:  # noqa: BLE001
            errors.append(f"{p.name}: {rexc}")
    bad = []
    for w in targets:
        p = w["path"]
        try:
            if _sha(p.read_bytes()) != w["sha256"]:
                bad.append(p.name)
        except OSError as rexc:
            bad.append(f"{p.name} ({rexc})")
    reason = f"сбой записи: {type(exc).__name__}: {exc}"
    if bad or errors:
        return {"exit": EXIT_MANUAL, "recovery": str(recovery),
                "written": [p.name for p in written],
                "reason": (f"{reason}; откат НЕ подтверждён ({', '.join(bad + errors)}) — "
                           f"исходные байты и хеши сохранены в {recovery}, нужно ручное вмешательство"),
                "_cleanup": None}
    return {"exit": EXIT_ROLLED_BACK, "recovery": None, "written": [],
            "reason": f"{reason}; откат подтверждён по хешам — состояние как до запуска",
            "_cleanup": recovery}


def repair(tracker_dir: Path, *, apply: bool, write=_default_write, restore=_restore,
           recovery_root: str | None = None) -> dict:
    plan = build_plan(tracker_dir)
    res = {
        "applied": False,
        "phantoms_found": len(plan["phantoms"]),
        "phantoms": plan["phantoms"],
        "phantoms_closed": 0,
        "sources_to_reopen": [w["path"].name for w in plan["writes"]],
        "sources_reopened": 0,
        "reopened": [],
        "sources_not_found": len(plan["orphaned"]),
        "orphaned": plan["orphaned"],
        "untouched_sources": plan["untouched_sources"],
        "refusals": plan["refusals"],
        "exit": EXIT_OK,
        "reason": "",
        "recovery": None,
    }
    if plan["refusals"]:
        res["exit"] = EXIT_REFUSED
        res["reason"] = "операция отклонена до первой записи"
        return res
    if not apply or not plan["writes"]:
        return res
    out = apply_plan(plan, write=write, restore=restore, recovery_root=recovery_root)
    cleanup = out.pop("_cleanup", None)
    if cleanup is not None:
        import shutil
        shutil.rmtree(cleanup, ignore_errors=True)
    res.update(exit=out["exit"], reason=out["reason"], recovery=out["recovery"])
    if out["exit"] == EXIT_OK:
        res.update(applied=True, reopened=out["written"], sources_reopened=len(out["written"]))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tracker-dir", default=str(_REPO / "nimbalyst-local" / "tracker"))
    ap.add_argument("--apply", action="store_true", help="выполнить (по умолчанию — сухой прогон)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    tracker = Path(args.tracker_dir)
    if not tracker.is_dir():
        print(f"нет каталога трекера: {tracker}", file=sys.stderr)
        return EXIT_USAGE

    res = repair(tracker, apply=args.apply)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return res["exit"]

    head = "ВЫПОЛНЕНО" if res["applied"] else "СУХОЙ ПРОГОН (ничего не записано)"
    if res["exit"] != EXIT_OK:
        head = "ОТКАЗ" if res["exit"] == EXIT_REFUSED else "СБОЙ"
    print(f"— задания, закрытые фантомами упавшего классификатора · {head} —")
    print(f"карточек-фантомов (вопросы владельцу, скрипт их НЕ трогает): {res['phantoms_found']}")
    for name in res["phantoms"]:
        print(f"   · {name}")
    if res["phantoms_found"]:
        print("   закрыть фантом может только владелец (инв. #14, ADR-551)")
    print(f"заданий к возврату в работу (done → new): {len(res['sources_to_reopen'])}")
    if res["applied"]:
        print(f"возвращено: {res['sources_reopened']}")
    if res["orphaned"]:
        print(f"исходников не найдено в трекере: {res['sources_not_found']}")
        for t in res["orphaned"]:
            print(f"   · {t}")
    for r in res["refusals"]:
        print(f"⛔ {r}")
    if res["reason"]:
        print(res["reason"])
    if res["recovery"]:
        print(f"материалы восстановления: {res['recovery']}")
    if res["exit"] == EXIT_OK and not res["applied"] and res["sources_to_reopen"]:
        print("\nповторить с --apply, чтобы записать")
    return res["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
