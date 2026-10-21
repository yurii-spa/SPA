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
    не дописывает: фантомы только НАЗЫВАЮТСЯ — убрать их может владелец.
  * Исходное задание (inbox-карточка), закрытое `done` в ту же аварию, возвращается в
    `new`. Связь фантом → задание доказывается ДВУМЯ признаками: единственное задание с
    точно тем же заголовком И цитата «Текст: «…»» фантома дословно есть в теле задания.

Порядок:
  0. ПЕРЕД ВСЕМ — поиск незавершённой операции в журнале операций
     (`<дерево>/data/repair_phantom_recovery/<id>/manifest.json`, не /tmp). Нашлась ⇒
     новые карточки не обрабатываются: сухой прогон только называет её (код 6), `--apply`
     откатывает СВОИ записи и сверяет по хешам (код 6 — «откатано, запусти снова»);
     чужая правка поверх нашей ⇒ ничего не трогаем, код 5.
  1. План — только чтение; запоминаются хеши ВСЕХ карточек трекера (входы, включая
     карточки владельца).
  2. Проверки — полномочия (в наборе записи только inbox по frontmatter И по имени),
     однозначность связи, тот же гейт, что у `set_status` (`queue.check_lifecycle`),
     хеши всех входов не менялись. Любой отказ ⇒ отказ ВСЕЙ операции, код 3: ни одного
     нового, изменённого или удалённого файла в целевом дереве, ни строки в журналах.
  3. Журнал операции (исходные байты + sha256 + план) — на диск с fsync ДО первой записи.
  4. Перед КАЖДОЙ заменой — снова хеши всех входов; запись через `queue.set_status`
     (файл заменяется через tmp + os.replace); хеш после записи — в журнал операции.
  5. Сбой ⇒ откат только СВОИХ записей (хеш совпадает с записанным нами) и сверка по
     хешам: подтверждено — код 4; чужая правка или неподтверждённый откат — код 5.

Что эта операция НЕ гарантирует (сказано вслух, см. также отчёт ARB 21.10).
  * Она НЕ атомарна как целое: заменяется по одному файлу. Читатель трекера между
    заменами видит часть заданий уже `new`, а часть ещё `done`. После прерывания
    процесса (kill -9, отключение питания) это смешанное состояние остаётся до
    следующего запуска скрипта, который его обнаружит и откатит.
  * Координации с другими писателями трекера нет — в архитектуре нет блокировки
    трекера (часовой цикл, мост находок, приём заданий, ответы владельца пишут карточки
    без общей блокировки). Сверка хешей перед каждой заменой сужает окно, но не
    закрывает его: между сверкой и `os.replace` внутри `set_status` чужая запись в ТОТ
    ЖЕ файл может быть потеряна. Если до восстановления кто-то изменит карточку, которую
    записали мы, откат её не тронет и потребует человека (код 5).
  * Журнал переходов `data/tracker_status_audit.jsonl` — только дописывается. Откат
    возвращает КАРТОЧКИ к исходным байтам, а в журнал ДОПИСЫВАЕТ обратный переход; прямой
    переход в журнале остаётся. При прерывании между заменой файла и записью журнала
    (её делает `set_status` ПОСЛЕ замены) прямой строки в журнале не будет, обратная — будет.

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
import uuid
from datetime import datetime, timezone
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
EXIT_UNFINISHED = 6

#: Журнал операций — в `data/` целевого дерева, рядом с журналом переходов; не в /tmp.
RECOVERY_REL = Path("data") / "repair_phantom_recovery"

_WRITER_SOURCE = "repair_phantom_intake_cards"
_FINAL_STATES = ("committed", "rolled_back")


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


def tree_root(tracker_dir: Path) -> Path:
    """Корень целевого дерева: по `.git` вверх, иначе родитель каталога трекера."""
    from spa_core.owner_queue.status_audit import repo_root_for
    return repo_root_for(tracker_dir) or Path(tracker_dir).resolve().parent


def recovery_root_for(tracker_dir: Path, override: str | os.PathLike | None = None) -> Path:
    return Path(override) if override is not None else tree_root(tracker_dir) / RECOVERY_REL


def _inputs(tracker_dir: Path) -> dict[str, str]:
    """Хеши ВСЕХ карточек трекера — входы операции, включая карточки владельца."""
    return {p.name: _sha(p.read_bytes()) for p in sorted(Path(tracker_dir).glob("*.md"))}


# ── план: только чтение ─────────────────────────────────────────────────────

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

    inputs = _inputs(tracker_dir)
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

    if _inputs(tracker_dir) != inputs:
        refusals.append("трекер менялся во время планирования — план не о текущем состоянии")

    return {"phantoms": [i["phantom"].name for i in phantoms], "writes": writes,
            "refusals": refusals, "orphaned": orphaned,
            "untouched_sources": untouched_sources, "inputs": inputs,
            "tracker": str(Path(tracker_dir).resolve())}


# ── «это записали мы»: строка статуса + один след, остальное байт в байт ──────

def _strip_status_and_trail(text: str) -> tuple[list[str], str] | None:
    from spa_core.owner_queue.status_audit import TRAIL_KEY, _frontmatter_bounds
    lines = text.splitlines(keepends=True)
    start, end = _frontmatter_bounds(lines)
    if start is None or end is None:
        return None
    kept: list[str] = []
    inside = False
    for ln in lines[start + 1:end]:
        if not ln[:1].isspace():
            key = ln.split(":", 1)[0].strip() if ":" in ln else ""
            inside = key == TRAIL_KEY
            if inside or key == "status":
                continue
        elif inside:
            continue
        kept.append(ln)
    return kept, "".join(lines[end + 1:])


def is_our_write(orig: bytes, cur: bytes, old: str, new: str) -> bool:
    """`cur` — это `orig`, переведённый `set_status` из `old` в `new`, и ничего больше."""
    from spa_core.owner_queue.status_audit import read_trail, status_of_text
    o_text, c_text = orig.decode("utf-8"), cur.decode("utf-8")
    o, c = _strip_status_and_trail(o_text), _strip_status_and_trail(c_text)
    if o is None or c is None or o != c or status_of_text(c_text) != new:
        return False
    t_o = [t["raw"] for t in read_trail(o_text)]
    t_c = read_trail(c_text)
    if not t_c:
        return False
    last = t_c[-1]
    if last.get("old") != old or last.get("new") != new or \
            not str(last.get("source", "")).startswith("queue.set_status"):
        return False
    prev = [t["raw"] for t in t_c[:-1]]
    return prev == (t_o[len(t_o) - len(prev):] if prev else [])


# ── журнал операции на диске ─────────────────────────────────────────────────

def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_durable(path: Path, data: bytes) -> None:
    """tmp в той же директории + fsync + os.replace + fsync каталога."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    _fsync_dir(path.parent)


def _save_manifest(op_dir: Path, manifest: dict) -> None:
    _write_durable(op_dir / "manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))


def _restore(path: Path, data: bytes) -> None:
    """Вернуть исходные байты карточки (форма инв. #5 для байтов)."""
    _write_durable(path, data)


def find_unfinished(recovery_root: Path) -> list[tuple[Path, dict | None]]:
    """Операции, не дошедшие до `committed`/`rolled_back`. Нечитаемый журнал — тоже."""
    out: list[tuple[Path, dict | None]] = []
    if not recovery_root.is_dir():
        return out
    for d in sorted(p for p in recovery_root.iterdir() if p.is_dir()):
        try:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append((d, None))
            continue
        if m.get("state") not in _FINAL_STATES:
            out.append((d, m))
    return out


def _undo(op_dir: Path, manifest: dict, restore, *, source: str) -> tuple[int, str]:
    """Откатить СВОИ записи операции. Чужая правка ⇒ ничего не трогаем, код 5."""
    from spa_core.owner_queue.status_audit import record_status_write
    plan, foreign = [], []
    for f in manifest["files"]:
        p = Path(f["path"])
        try:
            orig = (op_dir / f"{f['index']:03d}.orig").read_bytes()
        except OSError as exc:
            foreign.append(f"{p.name}: исходные байты не прочитаны ({exc})")
            continue
        if _sha(orig) != f["orig_sha"]:
            foreign.append(f"{p.name}: слепок повреждён (хеш не совпадает)")
            continue
        try:
            cur = p.read_bytes()
        except OSError as exc:
            foreign.append(f"{p.name}: карточка не прочитана ({exc})")
            continue
        if _sha(cur) == f["orig_sha"]:
            continue
        ours = (f.get("post_sha") and _sha(cur) == f["post_sha"]) or \
            is_our_write(orig, cur, f["old"], f["new"])
        if not ours:
            foreign.append(f"{p.name}: изменена не нами после нашей записи")
            continue
        plan.append((f, p, orig))
    if foreign:
        manifest["state"] = "needs_manual"
        manifest["manual_reasons"] = foreign
        _save_manifest(op_dir, manifest)
        return EXIT_MANUAL, ("откат НЕ выполнен — " + "; ".join(foreign) +
                             f"; исходные байты и хеши — {op_dir}, нужно ручное вмешательство")
    errors = []
    for f, p, orig in plan:
        try:
            restore(p, orig)
            record_status_write(p, old=f["new"], new=f["old"], source=f"{_WRITER_SOURCE}/{source}")
        except Exception as exc:  # noqa: BLE001 — сверка ниже скажет, удалось ли
            errors.append(f"{p.name}: {exc}")
    bad = [f["path"] for f in manifest["files"]
           if not Path(f["path"]).exists() or _sha(Path(f["path"]).read_bytes()) != f["orig_sha"]]
    if bad or errors:
        manifest["state"] = "needs_manual"
        manifest["manual_reasons"] = errors + [f"{Path(b).name}: хеш не исходный" for b in bad]
        _save_manifest(op_dir, manifest)
        return EXIT_MANUAL, (f"откат НЕ подтверждён ({', '.join(manifest['manual_reasons'])}) — "
                             f"исходные байты и хеши — {op_dir}, нужно ручное вмешательство")
    manifest["state"] = "rolled_back"
    manifest["rolled_back_by"] = source
    _save_manifest(op_dir, manifest)
    return EXIT_ROLLED_BACK, "откат подтверждён по хешам — карточки как до запуска"


# ── исполнение ───────────────────────────────────────────────────────────────

def _default_write(path: Path, new_status: str) -> None:
    from spa_core.owner_queue.queue import set_status
    set_status(path, new_status)


def apply_plan(plan: dict, *, write=_default_write, restore=_restore,
               recovery_root: Path) -> dict:
    """Исполнить план, проверенный `build_plan`. `write`/`restore` — входы для тестов."""
    tracker = Path(plan["tracker"])
    targets: list[dict] = plan["writes"]
    if _inputs(tracker) != plan["inputs"]:
        return {"exit": EXIT_REFUSED, "op": None,
                "reason": "трекер изменился между планом и записью — ничего не записано"}

    op_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    op_dir = recovery_root / op_id
    op_dir.mkdir(parents=True)
    manifest = {"op_id": op_id, "tracker": str(tracker), "state": "prepared",
                "created_at": datetime.now(timezone.utc).isoformat(), "files": []}
    for i, w in enumerate(targets):
        data = w["path"].read_bytes()
        _write_durable(op_dir / f"{i:03d}.orig", data)
        manifest["files"].append({"index": i, "path": str(w["path"]), "orig_sha": _sha(data),
                                  "old": w["old"], "new": w["new"], "post_sha": None,
                                  "state": "pending"})
    _save_manifest(op_dir, manifest)
    _fsync_dir(recovery_root)

    expected = dict(plan["inputs"])
    try:
        for f in manifest["files"]:
            p = Path(f["path"])
            if _inputs(tracker) != expected:
                raise RuntimeError("трекер изменён другим писателем во время операции")
            write(p, f["new"])
            cur = p.read_bytes()
            orig = (op_dir / f"{f['index']:03d}.orig").read_bytes()
            if not is_our_write(orig, cur, f["old"], f["new"]):
                raise RuntimeError(f"{p.name}: после записи не тот результат")
            f["post_sha"] = _sha(cur)
            f["state"] = "written"
            _save_manifest(op_dir, manifest)
            expected[p.name] = f["post_sha"]
    except Exception as exc:  # noqa: BLE001 — любой сбой ведёт к откату, причина в отчёте
        code, why = _undo(op_dir, manifest, restore, source="rollback")
        return {"exit": code, "op": str(op_dir),
                "reason": f"сбой записи: {type(exc).__name__}: {exc}; {why}"}

    manifest["state"] = "committed"
    _save_manifest(op_dir, manifest)
    return {"exit": EXIT_OK, "op": str(op_dir), "reason": "",
            "written": [Path(f["path"]).name for f in manifest["files"]]}


def recover_unfinished(recovery_root: Path, *, apply: bool, restore=_restore) -> dict | None:
    """Незавершённая операция ⇒ ответ вместо обработки новых карточек; иначе None."""
    pending = find_unfinished(recovery_root)
    if not pending:
        return None
    names = [d.name for d, _ in pending]
    if not apply:
        return {"exit": EXIT_UNFINISHED, "unfinished": names,
                "reason": "найдена незавершённая операция — её откатит запуск с --apply; "
                          "новые карточки не обрабатываются"}
    for d, m in pending:
        if m is None:
            return {"exit": EXIT_MANUAL, "unfinished": names,
                    "reason": f"журнал операции {d} не читается — нужно ручное вмешательство"}
        if m.get("state") == "needs_manual":
            return {"exit": EXIT_MANUAL, "unfinished": names,
                    "reason": f"операция {d.name} ждёт человека: {'; '.join(m.get('manual_reasons', []))}"}
        code, why = _undo(d, m, restore, source="recover_after_interrupt")
        if code != EXIT_ROLLED_BACK:
            return {"exit": code, "unfinished": names, "reason": why}
    return {"exit": EXIT_UNFINISHED, "unfinished": names,
            "reason": "незавершённая операция откатана и сверена по хешам; запусти снова"}


def repair(tracker_dir: Path, *, apply: bool, write=_default_write, restore=_restore,
           recovery_root: str | os.PathLike | None = None) -> dict:
    tracker_dir = Path(tracker_dir)
    rec_root = recovery_root_for(tracker_dir, recovery_root)
    res = {
        "applied": False, "phantoms_found": 0, "phantoms": [], "phantoms_closed": 0,
        "sources_to_reopen": [], "sources_reopened": 0, "reopened": [],
        "sources_not_found": 0, "orphaned": [], "untouched_sources": [], "refusals": [],
        "unfinished": [], "exit": EXIT_OK, "reason": "", "op": None,
    }
    rec = recover_unfinished(rec_root, apply=apply, restore=restore)
    if rec is not None:
        res.update(exit=rec["exit"], reason=rec["reason"], unfinished=rec["unfinished"])
        return res

    plan = build_plan(tracker_dir)
    res.update(phantoms_found=len(plan["phantoms"]), phantoms=plan["phantoms"],
               sources_to_reopen=[w["path"].name for w in plan["writes"]],
               sources_not_found=len(plan["orphaned"]), orphaned=plan["orphaned"],
               untouched_sources=plan["untouched_sources"], refusals=plan["refusals"])
    if plan["refusals"]:
        res.update(exit=EXIT_REFUSED, reason="операция отклонена до первой записи")
        return res
    if not apply or not plan["writes"]:
        return res
    out = apply_plan(plan, write=write, restore=restore, recovery_root=rec_root)
    res.update(exit=out["exit"], reason=out["reason"], op=out["op"])
    if out["exit"] == EXIT_OK:
        res.update(applied=True, reopened=out["written"], sources_reopened=len(out["written"]))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tracker-dir", default=str(_REPO / "nimbalyst-local" / "tracker"))
    ap.add_argument("--recovery-dir", default=None,
                    help=f"журнал операций (по умолчанию <дерево>/{RECOVERY_REL})")
    ap.add_argument("--apply", action="store_true", help="выполнить (по умолчанию — сухой прогон)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    tracker = Path(args.tracker_dir)
    if not tracker.is_dir():
        print(f"нет каталога трекера: {tracker}", file=sys.stderr)
        return EXIT_USAGE

    res = repair(tracker, apply=args.apply, recovery_root=args.recovery_dir)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return res["exit"]

    head = "ВЫПОЛНЕНО" if res["applied"] else "СУХОЙ ПРОГОН (ничего не записано)"
    if res["exit"] != EXIT_OK:
        head = {EXIT_REFUSED: "ОТКАЗ", EXIT_UNFINISHED: "НЕЗАВЕРШЁННАЯ ОПЕРАЦИЯ"}.get(res["exit"], "СБОЙ")
    print(f"— задания, закрытые фантомами упавшего классификатора · {head} —")
    if res["unfinished"]:
        print(f"незавершённые операции: {', '.join(res['unfinished'])}")
    else:
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
    if res["op"]:
        print(f"журнал операции: {res['op']}")
    if res["exit"] == EXIT_OK and not res["applied"] and res["sources_to_reopen"]:
        print("\nповторить с --apply, чтобы записать")
    return res["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
