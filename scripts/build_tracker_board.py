#!/usr/bin/env python3
"""build_tracker_board.py — единый обзор ВСЕХ карточек одним файлом (bootstrap).

Сканирует nimbalyst-local/tracker/*.md, парсит frontmatter (type/title/status/…) и пишет
nimbalyst-local/tracker/_BOARD.md: доска всех карточек со статусами + секция «ЖДЁТ ВЛАДЕЛЬЦА»
вверху. Чтобы любая сессия (и владелец в Nimbalyst) видела всё разом, не открывая 56 файлов —
директива owner 2026-07-16 «карточки все в одном месте, чтобы новое окно не было новым сотрудником».

Источник правды — сами карточки; _BOARD.md — производный индекс (регенерится оркестратором/по требованию).
Stdlib-only. Атомарная запись.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACKER = REPO / "nimbalyst-local" / "tracker"
OUT = TRACKER / "_BOARD.md"

# Один читатель типа карточки на оба инструмента. Вызванный как `python3 scripts/...`,
# скрипт получает sys.path[0] = scripts/ и корня репозитория на пути НЕТ (ровно так в CI
# умер перевод алертов, цикл #111) — поэтому корень СВОЕГО дерева добавляем явно.
# Импорт намеренно НЕ обёрнут в try: своя копия правила расхождения типов — это и есть
# дефект, который здесь чинится (доска знала обе формы, CLI только вложенную ⇒ три вопроса
# владельцу были невидимы в его же очереди). Сломанный импорт обязан быть слышен.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
# Сверка с origin живёт в `scripts/check_tracker_drift.py` — ОДНА реализация правила «что
# origin говорит об этой карточке» на весь проект (её же читает `orchestrator_queue.py`).
# Запущенный как файл, скрипт получает scripts/ в sys.path[0] сам; импортированный тестом
# по абсолютному пути — не получает, поэтому каталог добавляется явно.
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
from spa_core.owner_queue.queue import load_card_text, resolve_tracker_type  # noqa: E402

# порядок и человекочитаемые имена типов
TYPE_ORDER = ["owner-decision", "inbox", "agent-task"]
TYPE_LABEL = {
    "owner-decision": "🧑‍⚖️ Owner Decisions (что нужно от владельца)",
    "inbox": "📥 Inbox (задания: Telegram / заметки / голос)",
    "agent-task": "🤖 Agent Tasks (что делает агент)",
}
# порядок статусов внутри типа (неизвестные — в конец)
STATUS_ORDER = [
    # `owner-accepted` стоит ВТОРЫМ, сразу за вопросами владельцу: это наше принятое
    # и ещё не исполненное обещание (#350) — его место наверху, а не в хвосте среди
    # закрытых. Терминальным он НЕ является.
    "needs-owner", "owner-accepted", "blocked", "in-progress", "backlog",
    "open", "ingested", "done", "owner-done",
]
# статусы, означающие «ждёт владельца» — выносим наверх
WAITING_OWNER = {"needs-owner"}
# статусы, при которых работа закрыта ⇒ забытый claimed_by не считается занятостью
# (та же таблица, что в scripts/check_card_claim.py — карточку никто не «держит» после done)
TERMINAL_STATUSES = {"done", "ingested", "owner-done"}
# `owner-accepted` СОЗНАТЕЛЬНО не здесь: владелец ответил, но работа впереди, и захват
# карточки продолжает действовать — иначе принятое поручение немедленно выглядело бы
# свободным для второй сессии.


def parse_frontmatter(text: str) -> dict:
    """Минимальный парс YAML-frontmatter (плоские key: value + вложенный trackerStatus.type)."""
    meta: dict = {}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    block = text[3:end]
    cur_top = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if indent == 0:
            cur_top = key
            if val:
                meta[key] = val
        elif cur_top == "trackerStatus":
            # trackerStatus.type → type
            meta[key] = val
    return meta


def card_type(meta: dict, name: str) -> str:
    """Тип карточки — через ОБЩИЙ с CLI резолвер (см. `resolve_tracker_type`).

    `parse_frontmatter` выше уже сводит `trackerStatus.type` в плоский `type`, поэтому
    резолверу приходит форма, которую он понимает наравне с вложенной.
    """
    return resolve_tracker_type(meta, name) or "other"


def card_title(text: str, path: Path) -> str:
    """Название карточки — общим с CLI разбором; имя файла только как последний рубеж."""
    try:
        return load_card_text(text, path.name, path=path).title or path.stem
    except Exception:  # noqa: BLE001 — битая карточка не имеет права уронить всю доску
        return path.stem


def status_rank(s: str) -> int:
    try:
        return STATUS_ORDER.index(s)
    except ValueError:
        return len(STATUS_ORDER)


def atomic_write(path: Path, content: str) -> None:
    d = path.parent
    fd, tmp = tempfile.mkstemp(dir=str(d), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def card_dict(name: str, text: str, path: Path) -> dict:
    """Одна карточка → одна строка доски. ЕДИНСТВЕННОЕ место, где текст становится записью.

    Вынесено из `collect_cards`, потому что у доски два источника текста — файл в дереве и
    та же карточка в версии `origin/main` (`resolve_against_origin`), — и разбирать их
    по-разному значило бы завести вторую копию правила «как читается статус» ровно там,
    где эта копия и ломала доску прежде.
    """
    meta = parse_frontmatter(text)
    status = meta.get("status", "?")
    holder = (meta.get("claimed_by") or "").strip()
    return {
        "file": name,
        "type": card_type(meta, name),
        # Название — через ОБЩИЙ с CLI разбор (`load_card_text` → `resolve_card_title`):
        # у карточек, объявленных плоской формой, названия во frontmatter нет — оно стоит
        # `#`-заголовком тела, и доска печатала слаг файла (замер #183). Отдельной копии
        # «где лежит название» здесь намеренно НЕТ: вторая копия правила разбора — это и
        # есть дефект, за который проект уже платил вопросами владельца (#143–#145).
        "title": card_title(text, path),
        "status": status,
        "created": meta.get("created", ""),
        "priority": meta.get("priority", ""),
        # Занятость видна прямо на доске: две сессии 30.07 взяли одну карточку, потому что
        # «кто её держит» не было видно нигде (карточка agent-card-claim-collision-guard).
        "claimed_by": holder if status not in TERMINAL_STATUSES else "",
        "claimed_at": (meta.get("claimed_at", "") or "").strip(),
        # Откуда прочитан статус. `tree` — файл этого дерева; `origin` — карточка дочитана
        # с ref, потому что копия в дереве доказанно ПРЕЖНЯЯ версия того же файла.
        "status_from": "tree",
    }


def collect_cards(tracker: Path, out_name: str = "_BOARD.md") -> list[dict]:
    """Карточки на диске этого дерева — ПЕРВЫЙ из двух источников статуса.

    Второй — та же карточка на `origin/main` (`resolve_against_origin`). Раньше здесь
    стояло «единственный», и это было неверно: дерево цикла пушит прямо на origin, а
    прод-дерево не обновляется никогда, поэтому файл на диске может быть доказанно
    прежней версией самого себя. Замер 30.08 (#436): доска объявляла «ждёт владельца: 25»,
    из них 23 на origin уже `ingested` — владелец ответил 25.08 одной сводкой «все одобряю».

    Вынесено из `main()`, чтобы у сверки (`--check`) и у сборки был ОДИН читатель диска:
    вторая копия правила «как читается статус» — ровно тот дефект, из-за которого доска
    и разъехалась с карточками (замер 17.08: три расхождения на 508 карточек).
    """
    cards = []
    for p in sorted(tracker.glob("*.md")):
        if p.name == out_name:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        cards.append(card_dict(p.name, text, p))
    return cards


#: Вердикт сверки с ref, когда она не состоялась. Отсутствие сверки — НЕ «совпало».
ORIGIN_UNMEASURED = "unmeasured"
ORIGIN_MEASURED = "measured"


def resolve_against_origin(cards: list[dict], tracker: Path,
                           ref: str | None = None) -> tuple[list[dict], dict]:
    """Дочитать статусы с `ref` тем же сторожем, что и CLI. Возвращает `(карточки, вердикт)`.

    **Зачем.** `CLAUDE.md` §1 велит КАЖДОЙ сессии читать `_BOARD.md` первой — «чтобы новое
    окно не было новым сотрудником». Правило «карточку, доказанно устаревшую относительно
    origin, читать с origin» доехало до `orchestrator_queue.py list` (#147, там же и
    измерено) и не доехало сюда. Замер 30.08 на живом прод-дереве, один и тот же вход:

        orchestrator_queue.py list --status needs-owner  →   1
        _BOARD.md «ждёт владельца»                        →  25

    Из 25 двадцать три на `origin/main` уже `ingested`: владелец ответил 25.08 сводкой
    «все одобряю», в origin-копиях стоит секция «Ответ владельца» и `resolved:`. Доска
    ошибалась и во ВТОРУЮ сторону: 307 карточек живут на origin, а файла в прод-дереве
    нет — их доска не показывала вовсе (среди них `needs-owner` нет, поэтому число
    «ждёт владельца» они не двигают; состав — двигают, и об этом доска теперь ГОВОРИТ).

    Почему доска и сторож её сверки (`--check`) зовут ЭТУ функцию оба: разойдись они
    здесь — сверка начала бы требовать пересборки доски в ту самую неверную сторону.

    Переписывается ТОЛЬКО `stale` — карточка, чьё содержимое найдено в ИСТОРИИ origin для
    её же пути (не «похоже старее», а «это буквально прежняя версия этого файла»). Своя
    правка (`diverged`) не трогается: кто новее — не измерено, и молча выбрать сторону
    нельзя. Та же граница, что у CLI, и по той же причине.

    Fail-CLOSED: сверка не состоялась ⇒ статусы остаются местные, но вердикт говорит
    `unmeasured` и причину. Молчание здесь неотличимо от «сверено и совпало» — а именно
    за эту неотличимость проект платит чаще всего.
    """
    verdict = {
        "state": ORIGIN_UNMEASURED, "reason": "", "ref": ref or "", "ref_sha": "",
        "stale_applied": 0, "stale_status_changed": 0,
        "hidden": 0, "diverged": 0, "undelivered": 0, "unread": 0,
    }
    try:
        import check_tracker_drift as drift
    except Exception as exc:  # noqa: BLE001 — сторож не имеет права уронить сборку доски
        verdict["reason"] = f"сторож сверки не импортировался ({exc})"
        return cards, verdict

    use_ref = ref or drift.DEFAULT_REF
    verdict["ref"] = use_ref
    try:
        report = drift.analyze(tracker, use_ref)
        root = drift.repo_root_of(Path(report.tracker_dir))
        rel = Path(report.tracker_dir).resolve().relative_to(root.resolve()).as_posix()
    except drift.Unmeasured as exc:
        verdict["reason"] = str(exc)
        return cards, verdict
    except Exception as exc:  # noqa: BLE001 — песочница/чужой каталог: не «ок», но и не падение
        verdict["reason"] = f"сверка не выполнилась ({exc})"
        return cards, verdict

    verdict["state"] = ORIGIN_MEASURED
    verdict["ref_sha"] = report.ref_sha
    verdict["hidden"] = len(list(report.of_kind(drift.KIND_HIDDEN)))
    verdict["diverged"] = len(list(report.of_kind(drift.KIND_DIVERGED)))
    verdict["undelivered"] = len(list(report.of_kind(drift.KIND_UNDELIVERED)))

    by_file = {c["file"]: c for c in cards}
    for f in report.of_kind(drift.KIND_STALE):
        name = f"{f.card_id}.md"
        local = by_file.get(name)
        if local is None:
            continue
        rc, text = drift._git(root, ["show", f"{use_ref}:{rel}/{name}"])
        if rc != 0 or not text:
            # Расхождение ЕСТЬ, а версии с origin нет ⇒ статус этой карточки не измерен.
            verdict["unread"] += 1
            continue
        fresh = card_dict(name, text, local_path_of(tracker, name))
        fresh["status_from"] = "origin"
        # ЗАХВАТ карточки — состояние ЭТОГО дерева, а не содержимое карточки: его пишет
        # `check_card_claim.py claim` в рабочем дереве, и сам сторож расхождения объявляет
        # ключи захвата НЕ содержимым (`strip_claim_keys`) — то есть файл, отличающийся от
        # origin ТОЛЬКО свежим захватом, признаётся «доказанно прежним» и был бы переписан
        # вместе с захватом. Тогда занятая карточка показалась бы свободной, и её взяла бы
        # вторая сессия — ровно то столкновение 30.07, ради которого захват и заведён.
        # Поэтому: захват НИКОГДА не теряется, а отсутствующий локально — берётся с ref
        # (обе стороны — в сторону «занято», это осторожный ответ).
        if not local["claimed_by"] and not local["claimed_at"]:
            keep_by, keep_at = fresh["claimed_by"], fresh["claimed_at"]
        else:
            keep_by, keep_at = local["claimed_by"], local["claimed_at"]
        # Терминальность считается по РАЗРЕШЁННОМУ статусу: закрытую карточку никто не держит.
        fresh["claimed_by"] = "" if fresh["status"] in TERMINAL_STATUSES else keep_by
        fresh["claimed_at"] = keep_at if fresh["claimed_by"] else ""
        if fresh["status"] != local["status"]:
            verdict["stale_status_changed"] += 1
        by_file[name] = fresh
        verdict["stale_applied"] += 1

    return [by_file[c["file"]] for c in cards], verdict


def local_path_of(tracker: Path, name: str) -> Path:
    """Путь карточки в ЭТОМ дереве — он остаётся местным даже у текста, взятого с origin:
    по нему человек открывает файл и по нему работает `set-status`."""
    return tracker / name


def origin_note(verdict: dict | None) -> str:
    """Строка шапки о сверке с ref. Своя функция — её проверяют тестом отдельно от доски.

    Три исхода, и третий (`не измерено`) обязан звучать иначе первых двух: «сверено, всё
    совпало» и «сверить не удалось» неотличимы по молчанию, а стоят разного.
    """
    if not verdict or verdict.get("state") != ORIGIN_MEASURED:
        why = (verdict or {}).get("reason") or "причина не названа"
        return (f"> ⚠️ Сверка с origin **НЕ ИЗМЕРЕНА** ({why}) — статусы ниже прочитаны только "
                f"из этого дерева и могут показывать закрытое как открытое.")
    ref = verdict.get("ref") or "origin/main"
    sha = (verdict.get("ref_sha") or "")[:9]
    bits = [f"> Сверено с `{ref}`" + (f" ({sha})" if sha else "")]
    changed = verdict.get("stale_status_changed", 0)
    if changed:
        bits.append(f"статусов дочитано оттуда: **{changed}** "
                    f"(копия в дереве — прежняя версия того же файла)")
    hidden = verdict.get("hidden", 0)
    if hidden:
        bits.append(f"ещё **{hidden}** карточ(ка/ки) есть на ref, а файла в этом дереве нет — "
                    f"их в списках ниже НЕТ")
    diverged = verdict.get("diverged", 0)
    if diverged:
        bits.append(f"у **{diverged}** своя правка, кто новее — не измерено")
    unread = verdict.get("unread", 0)
    if unread:
        bits.append(f"у **{unread}** версию с ref прочитать не удалось — статус НЕ ИЗМЕРЕН")
    return " · ".join(bits) + "."


def render_board(cards: list[dict], now: datetime | None = None,
                 origin: dict | None = None) -> str:
    """Текст доски. `now` — ВХОД, а не окружение (правило про время в тестах).

    Доска ОБЯЗАНА называть свою дату: она производна и может отстать от карточек, а §1
    `CLAUDE.md` велит читать её ПЕРВОЙ. Читатель, который не видит отметки сборки, не может
    отличить свежий индекс от вчерашнего — ровно так дважды 17.08 брались закрытые карточки.

    `origin` — вердикт `resolve_against_origin`. Он тоже ВХОД: доска называет не только
    свою дату, но и с чем сверены её статусы; «не измерено» пишется явно.
    """
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    by_type: dict[str, list] = {}
    for c in cards:
        by_type.setdefault(c["type"], []).append(c)

    waiting = [c for c in cards if c["status"] in WAITING_OWNER]
    claimed = [c for c in cards if c["claimed_by"]]

    lines = []
    lines.append("# 📋 TRACKER BOARD — все карточки одним взглядом")
    lines.append("")
    lines.append("> Авто-генерится `scripts/build_tracker_board.py` из `nimbalyst-local/tracker/*.md`. "
                 "НЕ править вручную — правь карточки. Источник правды — карточки, это индекс (bootstrap).")
    lines.append(">")
    lines.append(f"> {BUILT_AT_PREFIX}{stamp} · сверка с карточками: "
                 "`python3 scripts/build_tracker_board.py --check` (сторож "
                 "`spa_core/tests/test_tracker_board_matches_cards.py`).")
    lines.append(">")
    lines.append(origin_note(origin))
    lines.append(">")
    lines.append(f"> Всего карточек: **{len(cards)}** · "
                 f"ждёт владельца: **{len(waiting)}** · занято сессиями: **{len(claimed)}**.")
    lines.append("")

    # секция «ждёт владельца» наверх
    lines.append("## 🔴 ЖДЁТ ВЛАДЕЛЬЦА (needs-owner)")
    lines.append("")
    if waiting:
        for c in sorted(waiting, key=lambda x: x["file"]):
            pr = f" · _{c['priority']}_" if c["priority"] else ""
            lines.append(f"- **{c['title']}**{pr}  ·  `{c['file']}`")
    else:
        lines.append("_Пусто — открытых решений на владельце нет._")
    lines.append("")

    # занятые карточки — чтобы «эту уже кто-то взял» было видно ДО начала работы.
    # Ниже секции владельца: его очередь всегда первая, занятость — служебный слой агентов.
    if claimed:
        lines.append("## 🔒 ЗАНЯТЫ СЕССИЯМИ (claimed_by)")
        lines.append("")
        lines.append("> Ставится `scripts/check_card_claim.py claim`, снимается `release` "
                     "(и не действует после `done`/`ingested`). Перед взятием карточки — "
                     "`check_card_claim.py check <карточка>`.")
        lines.append("")
        for c in sorted(claimed, key=lambda x: x["file"]):
            when = f" · с {c['claimed_at']}" if c["claimed_at"] else ""
            lines.append(f"- **{c['title']}** — держит `{c['claimed_by']}`{when}  ·  `{c['file']}`")
        lines.append("")

    # по типам
    ordered_types = TYPE_ORDER + [t for t in by_type if t not in TYPE_ORDER]
    for t in ordered_types:
        group = by_type.get(t)
        if not group:
            continue
        lines.append(f"## {TYPE_LABEL.get(t, t)}  ({len(group)})")
        lines.append("")
        group.sort(key=lambda x: (status_rank(x["status"]), x["file"]))
        cur_status = None
        for c in group:
            if c["status"] != cur_status:
                cur_status = c["status"]
                lines.append(f"### · {cur_status}")
            when = f" · {c['created']}" if c["created"] else ""
            lock = f" · 🔒 `{c['claimed_by']}`" if c["claimed_by"] else ""
            lines.append(f"- {c['title']}  ·  `{c['file']}`{when}{lock}")
        lines.append("")

    return "\n".join(lines) + "\n"


# --- сверка «доска ↔ карточки» --------------------------------------------------------
# Доска — производный индекс, но §1 CLAUDE.md велит читать её ПЕРВОЙ и «не открывать 56
# файлов». Значит она обязана СОВПАДАТЬ с frontmatter карточек; расхождение — не косметика,
# а неверный вход каждой сессии. 17.08 замерено 3 расхождения на 508 карточек (одна карточка
# `done` числилась `new`, две отсутствовали вовсе) — и по ним дважды бралась закрытая работа.

BUILT_AT_PREFIX = "Собрана: "
_BOARD_ROW = re.compile(r"^- .*?`([^`]+\.md)`")
_BOARD_STATUS_HEADING = re.compile(r"^### · (.+)$")


def board_status_map(board_text: str) -> dict[str, str]:
    """Что доска УТВЕРЖДАЕТ о статусе каждой карточки: {имя файла: статус}.

    Читается ровно то, что видит человек — строки под заголовками `### · <статус>`.
    Секции «ждёт владельца» / «заняты сессиями» — дубликаты тех же карточек без своего
    заголовка статуса; они намеренно пропускаются (`cur = None` на любом `## `).
    """
    out: dict[str, str] = {}
    cur: str | None = None
    for line in board_text.splitlines():
        if line.startswith("## "):
            cur = None
            continue
        m = _BOARD_STATUS_HEADING.match(line)
        if m:
            cur = m.group(1).strip()
            continue
        if cur is None:
            continue
        m = _BOARD_ROW.match(line)
        if m:
            out[m.group(1)] = cur
    return out


#: Начало строки-вердикта в шапке доски — по ней сверка узнаёт, КАК доска собрана.
ORIGIN_NOTE_MEASURED_PREFIX = "> Сверено с "
ORIGIN_NOTE_UNMEASURED_MARK = "НЕ ИЗМЕРЕНА"


def board_built_with_origin_check(board_text: str) -> bool | None:
    """Собрана ли ЭТА доска со сверкой: `True` / `False` / `None` — доска не говорит.

    Сверять надо в том же режиме, в каком доска собрана, — иначе сторож требует пересборки
    в сторону, которой никто не производит. Спрашиваем об этом САМУ доску (она объявляет
    режим строкой шапки), а не догадываемся по умолчанию вызывающего: догадка о чужом
    артефакте — тот самый класс, на котором проект уже стоял («спрашивать производителя»).

    `None` — доска старого образца, строки вердикта в ней нет вовсе. Тогда сверка идёт
    по прежним правилам (только дерево): молча объявить её расходящейся значило бы
    покрасить сторожа в красный за то, что артефакт старше самой проверки.
    """
    for line in board_text.splitlines():
        if line.startswith(ORIGIN_NOTE_MEASURED_PREFIX):
            return True
        if line.startswith("> ") and ORIGIN_NOTE_UNMEASURED_MARK in line:
            return False
    return None


def board_drift(tracker: Path, out_name: str = "_BOARD.md",
                ref: str | None = None,
                origin_check: bool | None = None) -> list[tuple[str, str, str]]:
    """Расхождения доски с карточками: [(файл, статус на доске, статус в frontmatter)].

    Fail-CLOSED: отсутствующая доска — расхождение по КАЖДОЙ карточке, а не «нечего сверять».

    Сверка идёт с тем же разрешённым статусом, что пишет сборка (`resolve_against_origin`).
    Иначе сторож начал бы требовать пересборки доски в неверную сторону — он сверял бы две
    КОПИИ одного устаревшего файла и был бы зелен по построению: обе стороны устаревают
    вместе. Именно так он и молчал, пока доска объявляла 25 вопросов владельцу при двух.
    """
    board_path = tracker / out_name
    board_text = board_path.read_text(encoding="utf-8") if board_path.exists() else ""
    claimed = board_status_map(board_text) if board_text else {}
    if origin_check is None:
        origin_check = board_built_with_origin_check(board_text) is True
    cards = collect_cards(tracker, out_name)
    if origin_check:
        cards, _ = resolve_against_origin(cards, tracker, ref)
    actual = {c["file"]: c["status"] for c in cards}
    drift = []
    for name in sorted(set(claimed) | set(actual)):
        said = claimed.get(name, "<НЕТ НА ДОСКЕ>")
        real = actual.get(name, "<НЕТ КАРТОЧКИ>")
        if said != real:
            drift.append((name, said, real))
    return drift


def main(argv=None) -> int:
    # argv=None ⇒ пустой список, а НЕ sys.argv: `main()` вызывают из кода
    # (`orchestrator_queue._rebuild_board`, тесты), где sys.argv принадлежит чужой программе.
    args = _parse(argv)

    tracker = Path(args.tracker_dir) if args.tracker_dir else TRACKER
    out = tracker / OUT.name if args.tracker_dir else OUT

    if args.check:
        # `--no-origin-check` задан явно ⇒ уважаем; иначе режим сверки диктует САМА доска.
        drift = board_drift(tracker, out.name, ref=args.ref,
                            origin_check=None if args.origin_check else False)
        if drift:
            print(f"ДОСКА РАСХОДИТСЯ С КАРТОЧКАМИ: {len(drift)}", file=sys.stderr)
            for name, said, real in drift:
                print(f"  {name}: доска={said!r} · карточка={real!r}", file=sys.stderr)
            print("Починка: python3 scripts/build_tracker_board.py "
                  "(статусы карточек НЕ трогать — инвариант 14).", file=sys.stderr)
            return 1
        print(f"OK: доска совпадает с карточками ({len(collect_cards(tracker, out.name))} карточек)")
        return 0

    cards = collect_cards(tracker, out.name)
    if args.origin_check:
        cards, origin = resolve_against_origin(cards, tracker, args.ref)
        if origin["state"] != ORIGIN_MEASURED:
            # Не «ок» и не падение: доска собирается, но громко говорит, чего не знает.
            print(f"❓ сверка доски с origin НЕ ИЗМЕРЕНА — {origin['reason']}", file=sys.stderr)
    else:
        # Выключенная сверка — тоже «не измерено», и ПРИЧИНУ обязана назвать она сама.
        # Молчаливое отсутствие строки читалось бы как «сверено и совпало» — ровно та
        # неотличимость, ради которой вердикт вообще заведён.
        origin = {"state": ORIGIN_UNMEASURED,
                  "reason": "сверка не запрашивалась (--no-origin-check)"}
    content = render_board(cards, origin=origin)
    atomic_write(out, content)
    # Доска может быть перенацелена на другой каталог (`--tracker-dir`, песочница теста) —
    # тогда её пути нет внутри репозитория. Статусная СТРОКА не имеет права ронять сборку:
    # файл уже записан, и падение здесь выглядело бы как «доска не собралась».
    try:
        where = out.relative_to(REPO)
    except ValueError:
        where = out
    waiting = [c for c in cards if c["status"] in WAITING_OWNER]
    claimed = [c for c in cards if c["claimed_by"]]
    read_from_origin = sum(1 for c in cards if c.get("status_from") == "origin")
    print(f"wrote {where} — {len(cards)} cards, "
          f"{len(waiting)} waiting-owner, {len(claimed)} claimed"
          + (f", {read_from_origin} статус(ов) дочитано с "
             f"{(origin or {}).get('ref', 'origin/main')}" if read_from_origin else ""))
    return 0


def _parse(argv):
    p = argparse.ArgumentParser(description="Собрать/сверить _BOARD.md из карточек трекера.")
    p.add_argument("--tracker-dir", default=None,
                   help="каталог карточек (по умолчанию — трекер СВОЕГО дерева)")
    p.add_argument("--check", action="store_true",
                   help="не писать, а СВЕРИТЬ доску с frontmatter карточек; расхождение ⇒ код 1")
    p.add_argument("--no-origin-check", dest="origin_check", action="store_false",
                   help="не дочитывать статусы с origin/main (быстро, но доска может "
                        "показывать закрытое как открытое)")
    p.add_argument("--ref", default=None,
                   help="с чем сверять статусы (по умолчанию origin/main)")
    p.set_defaults(origin_check=True, ref=None)
    return p.parse_args([] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
