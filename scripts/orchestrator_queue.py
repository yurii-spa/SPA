#!/usr/bin/env python3
"""CLI over the files-first owner-queue (ENV_SETUP_BRIEF_v3 · Этап 3).

Deterministic, stdlib-only. Used by the orchestrator protocol (docs/ORCHESTRATOR_PROTOCOL.md)
to scan Owner-Done / Inbox cards, move card status, and notify the owner via Telegram.

Examples::

    # list owner-decision cards the owner has answered (needs ingest):
    python3 scripts/orchestrator_queue.py list --type owner-decision --status owner-done --json

    # list new inbox tasks:
    python3 scripts/orchestrator_queue.py list --type inbox --json

    # after ingesting an owner decision, move it to ingested (owner-done is FORBIDDEN):
    python3 scripts/orchestrator_queue.py set-status nimbalyst-local/tracker/own-08-spa-naming.md ingested

    # Telegram-notify a freshly created needs-owner card (§3.3):
    python3 scripts/orchestrator_queue.py notify nimbalyst-local/tracker/own-99-foo.md
    python3 scripts/orchestrator_queue.py notify <path> --check   # build message, do not send
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path (works when run from scripts/ or repo root).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
# Каталог scripts/ — СВОЕГО дерева, а не чьего-то: сторож сверки с origin (check_tracker_drift)
# должен быть той же копии, что и эта. Явно, не через sys.path[0]: при импорте модуля тестом
# sys.path[0] — каталог pytest, и импорт сторожа молча не состоялся бы (капкан #111).
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from spa_core.owner_queue.queue import (
    OwnerDoneForbidden,
    TRACKER_DIR,
    create_card,
    ingest_notes,
    load_card,
    scan_promotions,
    first_instruction_line,
    list_cards,
    set_status,
)
from spa_core.owner_queue.notify import notify_needs_owner
from spa_core.owner_queue.owner_answer import (
    AnswerConflict,
    CARRY_ALREADY_PRESENT,
    CARRY_CARRIED,
    CARRY_NO_ANSWER,
    CARRY_UNMEASURED,
    CROSS_FOUND,
    CROSS_UNMEASURED,
    _IDENTITY_FIELDS,
    carry_owner_answer,
    scan_owner_answers_elsewhere,
)


def _rebuild_board(tracker_dir=None) -> None:
    """Best-effort regen of nimbalyst-local/tracker/_BOARD.md (single-glance card index for bootstrap).
    Never raises — board is a derived index; card mutation must not fail on its account."""
    try:
        import contextlib
        import importlib.util
        import io

        from spa_core.owner_queue import queue as _queue

        spec = importlib.util.spec_from_file_location(
            "build_tracker_board",
            str(Path(__file__).resolve().parent / "build_tracker_board.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Point the builder at whichever tracker the CLI is actually operating on
        # (production: the real tracker; tests: a repointed tmp dir). The builder
        # otherwise hardcodes the real tracker, so without this a test run would
        # rewrite the git-tracked production _BOARD.md, and any TRACKER_DIR
        # repoint would silently regenerate the wrong board.
        # Явный --tracker-dir главнее умолчания модуля: иначе карточка легла бы в указанный
        # каталог, а пересобрался бы board СОСЕДНЕГО дерева (одна команда — два дерева).
        tracker_dir = tracker_dir or getattr(_queue, "TRACKER_DIR", None)
        if tracker_dir is not None:
            mod.TRACKER = Path(tracker_dir)
            mod.OUT = mod.TRACKER / mod.OUT.name
        # The builder prints a "wrote _BOARD.md — N cards" status line. The CLI's
        # stdout is a machine-readable contract (create prints ONLY the card
        # path; callers read stdout to obtain it), so keep the builder's chatter
        # off our stdout.
        with contextlib.redirect_stdout(io.StringIO()):
            mod.main()
    except Exception:  # noqa: BLE001
        pass


# ── вердикт сверки с origin, который ЕДЕТ В JSON ─────────────────────────────
# stdout — машинный контракт, и шаг 2 протокола читает именно его
# (`list --type owner-decision --status owner-done --json`). Пока вердикт жил
# только в stderr-прозе, сессия с `| jq` его не видела ВООБЩЕ. Замер 09.08:
# хост-дерево выдало 2 карточки `owner-done`, обе на origin уже `ingested`.
VERDICT_AGREES = "agrees"                     # дерево и origin совпали
VERDICT_STALE = "stale_read_from_origin"      # карточка перечитана с origin
VERDICT_UNDELIVERED = "undelivered_not_on_origin"
VERDICT_DIVERGED = "diverged_unmeasured"      # своя правка, кто новее не измерено
VERDICT_MAYBE_INGESTED = "answer_may_be_already_ingested"
# ДОКАЗАНО, а не «скорее всего»: на origin у карточки терминальный статус И тот же самый
# след решения владельца (`owner_choice` + `owner_answered_at`), что в дереве. Это возможно
# ровно в одном случае — ответ прошёл через инжест с переносом следа (`carry_owner_answer`).
# Совпадение выбора И момента подделать нечем: их пишет бот в момент нажатия.
VERDICT_ANSWER_INGESTED_PROVEN = "answer_ingested_proven"
VERDICT_UNMEASURED = "unmeasured"             # сторож не отработал — НЕ «ок»

# Статусы, из которых следует, что ответ владельца по этой карточке агент уже
# разобрал и доставил на origin.
_TERMINAL_ON_ORIGIN = ("ingested", "done", "owner-done-archived")


def _same_owner_answer(tree_card, origin_card) -> bool:
    """Обе копии несут ОДИН И ТОТ ЖЕ след решения владельца — и он непустой.

    Пустой след с обеих сторон совпадением НЕ считается: «полей нет ни там, ни там» — это
    ровно то состояние, ради которого перенос и написан, и объявлять его доказательством
    значило бы гасить карточки, у которых ответа в git как не было, так и нет.
    """
    for key in _IDENTITY_FIELDS:
        mine = str((tree_card.fields or {}).get(key, "") or "").strip()
        theirs = str((origin_card.fields or {}).get(key, "") or "").strip()
        if not mine or mine != theirs:
            return False
    return True


def _card_dict(c, verdict: dict | None = None) -> dict:
    d = {
        "id": c.id,
        "path": str(c.path),
        "type": c.tracker_type,
        "status": c.status,
        "priority": c.priority,
        "title": c.title,
        "owner": c.owner,
        "legacy_id": c.legacy_id,
        "first_instruction": first_instruction_line(c),
        # Всегда присутствует: отсутствие поля читалось бы как «сверено и ок».
        "origin_check": VERDICT_UNMEASURED,
    }
    if verdict:
        d.update(verdict)
    return d


def _origin_read_through(cards: list, tracker_dir=None,
                         ref: str | None = None) -> tuple[list, dict[str, dict]]:
    """Сверить читаемый трекер с `origin/main` и ГРОМКО назвать расхождение (шаг 1-пред).

    **Зачем.** Список карточек читается из трекера ТОГО дерева, чья копия этого скрипта
    запущена. Циклы работают в изолированных worktree и пушат прямо на origin — хост-дерево
    не обновляется никогда, и никто эти два набора не сверял. Измерено на живом входе
    (#147): хост-дерево дало 5 карточек `inbox/new`, все пять на origin уже закрыты, и НЕ
    показало 7 настоящих открытых, включая **три вопроса владельца в `needs-owner`**. Очередь
    была неверна в обе стороны сразу.

    **Что здесь происходит и чего НЕ происходит.** Карточка, содержимое которой найдено в
    ИСТОРИИ origin для её же пути, — доказанно устаревшая копия (не «похоже старее», а
    «это буквально прежняя версия этого файла»); такая читается с origin, и статус-фильтр
    работает по правде. Всё остальное НЕ переписывается: у карточки со своей правкой
    (`diverged`) кто новее — не измерено, и молча выбирать сторону нельзя; карточку, которой
    в дереве нет (`hidden`), выдать невозможно — файла нет, а путь-фантом сломал бы
    `set-status`. Обе называются в stderr поимённо. Массовый `checkout origin/main -- трекер`
    запрещён по построению: он стёр бы карточки, живущие только в рабочем дереве.

    **Вердикт едет и в stdout (09.08).** Раньше всё сказанное сторожем жило только в
    stderr-прозе, а шаг 2 протокола читает JSON: `list --type owner-decision --status
    owner-done --json`. Сессия, разбирающая stdout, о расхождении не узнавала НИКОГДА.
    Замер на живом входе: хост-дерево выдало 2 карточки `owner-done`
    (`own-rnd-duty-is-concentration-adr055`, `owner-decision-morfo-40-knigi-…`), обе на
    origin давно `ingested` — то есть обязательный шаг «инжест решений владельца» получал
    два уже разобранных решения как свежие. Причина устойчива и сама не пройдёт: ответ
    владельца пишет Telegram-бот в ХОСТ-дерево, а инжест делает цикл в worktree и пушит на
    origin — хост-карточка остаётся `owner-done` навсегда.

    Теперь у КАЖДОЙ карточки в JSON есть поле `origin_check`; отсутствие сверки — это
    `unmeasured`, а не молчаливое «ок». Для `diverged`-карточки в статусе `owner-done`
    вердикт ДОИЗМЕРЯЕТСЯ по статусу той же карточки на origin: терминальный статус там
    означает, что ответ уже разобран и доставлен. Карточка при этом НЕ выбрасывается из
    списка — сторож называет, а решает сессия (fail-CLOSED к прежнему поведению).

    stdout не трогается ПО ФОРМЕ: он машинный контракт. Всё, что говорит сторож, идёт в stderr.
    Не измерилось — говорим «НЕ ИЗМЕРЕНО» и причину, а не молчим.
    """
    verdicts: dict[str, dict] = {}
    try:
        import check_tracker_drift as drift
    except Exception as exc:  # noqa: BLE001 — сторож не должен ломать саму очередь
        print(f"❓ сверка с origin НЕ ИЗМЕРЕНА: сторож не импортировался ({exc})", file=sys.stderr)
        return cards, verdicts
    try:
        report = drift.analyze(tracker_dir, ref or drift.DEFAULT_REF)
    except drift.Unmeasured as exc:
        print(f"❓ сверка трекера с origin/main НЕ ИЗМЕРЕНА — {exc}\n"
              f"    список ниже НЕ подтверждён: он может показывать закрытое и прятать новое.",
              file=sys.stderr)
        return cards, verdicts
    # Сверка состоялась ⇒ у всех карточек вердикт по умолчанию «совпало»; ниже он
    # уточняется поимённо для тех, у кого есть находка.
    verdicts = {c.id: {"origin_check": VERDICT_AGREES} for c in cards}
    if not report.findings:
        return cards, verdicts

    try:
        root = drift.repo_root_of(Path(report.tracker_dir))
        rel = Path(report.tracker_dir).resolve().relative_to(root.resolve()).as_posix()
    except (drift.Unmeasured, ValueError) as exc:
        # Сторож не имеет права уронить саму очередь: сверка — довесок к списку, а не его условие.
        print(f"❓ расхождение найдено, но версию с origin взять неоткуда ({exc})", file=sys.stderr)
        # Расхождение ЕСТЬ, а разобрать его нечем ⇒ «совпало» здесь было бы враньём.
        return cards, {c.id: {"origin_check": VERDICT_UNMEASURED} for c in cards}
    by_id = {c.id: c for c in cards}
    for f in report.of_kind(drift.KIND_STALE):
        local = by_id.get(f.card_id)
        if local is None:
            continue
        try:
            fresh = drift.read_origin_card(root, report.ref, f"{rel}/{f.card_id}.md")
        except drift.Unmeasured as exc:
            print(f"❓ {f.card_id}: устарела, но версию с origin прочитать не удалось ({exc})",
                  file=sys.stderr)
            verdicts[f.card_id] = {"origin_check": VERDICT_UNMEASURED}
            continue
        fresh.path = local.path  # путь остаётся местный: по нему работает set-status
        by_id[f.card_id] = fresh
        verdicts[f.card_id] = {"origin_check": VERDICT_STALE}

    for f in report.of_kind(drift.KIND_UNDELIVERED):
        if f.card_id in verdicts:
            verdicts[f.card_id] = {"origin_check": VERDICT_UNDELIVERED}

    # `diverged` — единственная группа, где прежде стояло глухое «кто новее НЕ измерено».
    # Для карточки в статусе `owner-done` это доизмеримо: если на origin та же карточка
    # уже в терминальном статусе, ответ владельца разобран и доставлен, а хост-копия —
    # остаток, который бот больше никогда не перепишет.
    already_ingested: list[str] = []
    proven_ingested: list[str] = []
    for f in report.of_kind(drift.KIND_DIVERGED):
        local = by_id.get(f.card_id)
        if local is None:
            continue
        verdict = {"origin_check": VERDICT_DIVERGED}
        try:
            origin_card = drift.read_origin_card(root, report.ref, f"{rel}/{f.card_id}.md")
        except drift.Unmeasured as exc:
            verdict["origin_check_note"] = f"версию с origin прочитать не удалось: {exc}"
            verdicts[f.card_id] = verdict
            continue
        verdict["origin_status"] = origin_card.status
        if local.status == "owner-done" and origin_card.status in _TERMINAL_ON_ORIGIN:
            if _same_owner_answer(local, origin_card):
                # След решения владельца ДОЕХАЛ до git и совпал с деревом ⇒ это не догадка,
                # а доказательство: ответ разобран и доставлен. Карточка читается с origin
                # (как `stale`), и обязательный шаг 2 больше не выдаёт её как свежую —
                # именно за этим переносится след. Без совпадения полей всё остаётся как
                # было: «скорее всего» и решает сессия.
                origin_card.path = local.path
                by_id[f.card_id] = origin_card
                verdict["origin_check"] = VERDICT_ANSWER_INGESTED_PROVEN
                verdict["origin_check_note"] = (
                    f"на {report.ref} карточка `{origin_card.status}` И несёт ТОТ ЖЕ след "
                    f"решения владельца, что копия в дереве "
                    f"({', '.join(_IDENTITY_FIELDS)}) — ответ доказанно разобран; "
                    f"статус прочитан с {report.ref}"
                )
                proven_ingested.append(f.card_id)
            else:
                verdict["origin_check"] = VERDICT_MAYBE_INGESTED
                verdict["origin_check_note"] = (
                    f"в дереве `owner-done`, а на {report.ref} эта же карточка уже "
                    f"`{origin_card.status}` — ответ владельца, скорее всего, УЖЕ разобран; "
                    f"проверьте, прежде чем инжестить повторно"
                )
                already_ingested.append(f.card_id)
        verdicts[f.card_id] = verdict

    def _ids(kind):
        return ", ".join(sorted(x.card_id for x in report.of_kind(kind))) or "—"

    stale, hidden = report.of_kind(drift.KIND_STALE), report.of_kind(drift.KIND_HIDDEN)
    diverged, undelivered = report.of_kind(drift.KIND_DIVERGED), report.of_kind(drift.KIND_UNDELIVERED)
    print(f"⚠️  трекер этого дерева РАСХОДИТСЯ с {report.ref} ({report.ref_sha[:9] or '?'}): "
          f"в дереве {report.tree_count}, на {report.ref} {report.origin_count}", file=sys.stderr)
    if stale:
        print(f"    · устарели и прочитаны С ORIGIN ({len(stale)}): {_ids(drift.KIND_STALE)}",
              file=sys.stderr)
    if hidden:
        print(f"    · ЕСТЬ НА ORIGIN, В ДЕРЕВЕ НЕТ ({len(hidden)}) — в список ниже НЕ попали, "
              f"работайте из worktree от {report.ref}: {_ids(drift.KIND_HIDDEN)}", file=sys.stderr)
    if diverged:
        print(f"    · своя правка в дереве ({len(diverged)}) — кто новее НЕ измерено, сверьте "
              f"руками: {_ids(drift.KIND_DIVERGED)}", file=sys.stderr)
    if already_ingested:
        print(f"    · из них ОТВЕТ ВЛАДЕЛЬЦА УЖЕ РАЗОБРАН ({len(already_ingested)}): "
              f"{', '.join(sorted(already_ingested))} — в дереве `owner-done`, на "
              f"{report.ref} терминальный статус. Повторный инжест наплодит дубли; "
              f"в JSON это поле `origin_check`.", file=sys.stderr)
    if proven_ingested:
        print(f"    · из них ОТВЕТ ДОКАЗАННО РАЗОБРАН ({len(proven_ingested)}): "
              f"{', '.join(sorted(proven_ingested))} — на {report.ref} терминальный статус "
              f"И тот же след решения владельца; статус прочитан с {report.ref}, "
              f"как свежие они больше не выдаются.", file=sys.stderr)
    if undelivered:
        print(f"    · есть в дереве, на {report.ref} нет ({len(undelivered)}) — не доставлены: "
              f"{_ids(drift.KIND_UNDELIVERED)}", file=sys.stderr)
    return [by_id[c.id] for c in cards], verdicts


def _cross_tree_owner_answers(tracker_dir, now=None):
    """(вердикт, карточки-из-главного-дерева, довесок-полей) — ответ владельца из ЛЮБОГО дерева.

    **Зачем.** Шаг 2 протокола (`list --type owner-decision --status owner-done`) читает трекер
    ТОГО дерева, чья копия этого скрипта запущена. Ответ владельца туда не попадает: его пишет
    Telegram-бот в ПРОД-дерево, а на `origin/main` он не уезжает ничем (мост ADR-081 везёт только
    своё, `IDLE`). §3.4 при этом ОБЯЗЫВАЕТ работать из изолированного worktree — то есть шаг 2
    предписано исполнять ровно оттуда, откуда живого ответа не видно.

    Замер 14.08: владелец ответил в 12:26:56Z, два прогона цикла #230 (16:15Z и 17:01Z) прошли
    мимо. Нашёл ответ цикл #231 не шагом 2, а шагом 1-пред, где расхождение теряется среди
    десятков однотипных строк «своя правка».

    **Зеркало уже закрытого — и опаснее его.** #182 лечил ЛОЖНОЕ «есть решение» (стоит времени
    сессии). Здесь ЛОЖНОЕ «решений нет»: оно теряет РЕШЕНИЕ ВЛАДЕЛЬЦА, а пустой список неотличим
    от честной пустой очереди. Поэтому найденное не только называется в stderr, но и ЕДЕТ В
    stdout — машинный контракт шага 2 (урок #178: всё, что живёт только в stderr-прозе, сессия
    с `| jq` не видит НИКОГДА).

    **Инвариант #14 цел.** Здесь ничего не пишется: чужая копия только читается и называется.
    Карточка главного дерева едет ОТДЕЛЬНОЙ записью, а не подменяет местную: обе копии реально
    существуют, и врать про их число — значит чинить видимость враньём. `path` каждой записи
    указывает на ту копию, из которой она прочитана.
    """
    try:
        verdict, findings, reason = scan_owner_answers_elsewhere(tracker_dir, now=now)
    except Exception as exc:  # noqa: BLE001 — сторож не имеет права уронить саму очередь
        return CROSS_UNMEASURED, [], f"опрос главного дерева упал: {exc}"
    if verdict == CROSS_UNMEASURED:
        return verdict, [], reason
    out = []
    for f in findings:
        try:
            card = load_card(f.path)
        except Exception as exc:  # noqa: BLE001 — нечитаемая копия остаётся находкой
            print(f"❓ {f.card_id}: ответ владельца в главном дереве найден, но карточка не "
                  f"разобрана ({exc})", file=sys.stderr)
            continue
        extra = f.as_dict()
        extra.pop("id", None)
        extra["cross_tree_check"] = CROSS_FOUND
        extra["cross_tree_note"] = (
            "эта запись прочитана из ГЛАВНОГО дерева, а не из читаемого. Разбирать — свою "
            "копию, а след ответа перенести (`set-status … ingested` делает это сам через "
            "`carry_owner_answer`); статус `owner-done` не ставить (инв. #14)."
        )
        out.append((card, extra))
    return verdict, out, None


def cmd_list(args) -> int:
    cards = list_cards(tracker_dir=getattr(args, "tracker_dir", None))
    verdicts: dict[str, dict] = {}
    if getattr(args, "origin_check", True):
        cards, verdicts = _origin_read_through(cards, getattr(args, "tracker_dir", None),
                                               getattr(args, "ref", None))
    else:
        # Сверку выключили явным флагом. Это НЕ «совпало» — это «не измерено»,
        # и в машинном контракте оно обязано выглядеть именно так.
        print("❓ сверка с origin ОТКЛЮЧЕНА флагом --no-origin-check: список не подтверждён",
              file=sys.stderr)

    cross_verdict, foreign, cross_reason = _cross_tree_owner_answers(
        getattr(args, "tracker_dir", None) or TRACKER_DIR, now=getattr(args, "now", None))
    if cross_verdict == CROSS_FOUND:
        print(f"🔴 ОТВЕТ ВЛАДЕЛЬЦА ЕСТЬ В ГЛАВНОМ ДЕРЕВЕ, А ЗДЕСЬ ЕГО НЕТ ({len(foreign)}) — "
              f"бот пишет ответ в прод-дерево, на origin он не уезжает ничем:", file=sys.stderr)
        for card, extra in foreign:
            age = extra.get("age_hours")
            waited = f"ждёт {age} ч" if age is not None else "момент ответа НЕ записан"
            print(f"    · {card.id}: здесь `{extra['local_status']}`, в главном дереве "
                  f"`{card.status}` ({waited}) — {extra['source_path']}", file=sys.stderr)
    elif cross_verdict == CROSS_UNMEASURED:
        print(f"❓ ответ владельца в главном дереве НЕ ИЗМЕРЕН — {cross_reason}\n"
              f"    пустой список ниже НЕ означает «решений нет»: живой ответ мог остаться "
              f"в дереве, куда пишет бот.", file=sys.stderr)

    # Фильтры применяются ПОСЛЕ сверки с origin — иначе карточка, закрытая на origin, отсеялась
    # бы по устаревшему статусу дерева и снова выдавалась как новая (ровно чинимый дефект).
    def _keep(c) -> bool:
        if args.type is not None and c.tracker_type != args.type:
            return False
        if args.status is not None and c.status != args.status:
            return False
        return True

    cards = [c for c in cards if _keep(c)]
    foreign = [(c, e) for c, e in foreign if _keep(c)]

    rows = [(c, dict(verdicts.get(c.id) or {})) for c in cards]
    rows += [(c, e) for c, e in foreign]
    if cross_verdict == CROSS_UNMEASURED:
        # Отсутствие поля читалось бы как «сверено и ок» — ровно то, чем этот класс и живёт.
        for _c, extra in rows:
            extra.setdefault("cross_tree_check", CROSS_UNMEASURED)

    if args.json:
        print(json.dumps([_card_dict(c, extra) for c, extra in rows],
                         ensure_ascii=False, indent=2))
    else:
        if not rows:
            print("(no matching cards)")
        for c, extra in rows:
            # Человек, читающий список глазами, обязан видеть тот же вердикт, что и `| jq`.
            v = extra.get("origin_check", VERDICT_UNMEASURED)
            mark = "" if v == VERDICT_AGREES else f"  ⚠️ origin_check={v}"
            if extra.get("cross_tree_check") == CROSS_FOUND:
                mark += f"  🔴 {CROSS_FOUND} ({extra.get('source_tree')})"
            print(f"[{c.status:<11}] {c.tracker_type:<14} {c.id}  —  {c.title}{mark}")

    # ПУСТОЙ и НЕ ИЗМЕРЕННЫЙ список — это не «решений нет». Единственный оставшийся канал,
    # когда карточки нет ни одной: ненулевой код возврата (после ADR-084 он и есть канал
    # недоставки). Измеренная пустота по-прежнему даёт 0.
    if cross_verdict == CROSS_UNMEASURED and not rows:
        print("❓ список ПУСТ и НЕ ПОДТВЕРЖДЁН: «решений нет» здесь не измерено (код 2).",
              file=sys.stderr)
        return 2
    return 0


#: Статус, которым сессия закрывает разобранное решение владельца. Ровно перед ним след
#: ответа обязан оказаться в той копии карточки, которая уедет в git.
_INGESTED = "ingested"


def _carry_answer_before_closing(args) -> int | None:
    """Перенести след решения владельца в закрываемую карточку. None — можно закрывать.

    **Зачем это стоит ЗДЕСЬ, а не в вызывающей сессии.** Инжест делает человекоподобный
    исполнитель в изолированном worktree от `origin/main`, где полей ответа нет вообще:
    их писал бот в ХОСТ-дерево. Полагаться на то, что каждая следующая сессия вспомнит
    перенести их руками, — это и есть механизм, который уже потерял след двух решений
    (`own-rnd-duty-is-concentration-adr055`, `owner-decision-morfo-40-knigi-…`: на origin
    у обеих нет ни `owner_choice`, ни `owner_answered_at`). Проверка живёт внутри
    ЕДИНСТВЕННОЙ двери, через которую карточка решения закрывается, — как и проверка
    личности владельца живёт внутри писателя (`record_owner_answer`), а не на стороне вызова.

    Молчаливого «ок» здесь нет: любой исход называется вслух. Отказ ровно один — два
    РАЗНЫХ ответа владельца в разных копиях: тогда закрывать нельзя, пока не сверят руками.
    """
    try:
        card = load_card(args.path)
    except Exception as exc:  # noqa: BLE001 — карточку разберёт и назовёт сам set_status
        print(f"❓ перенос следа решения НЕ ИЗМЕРЕН: карточка не разобрана ({exc})",
              file=sys.stderr)
        return None
    if card.tracker_type != "owner-decision":
        return None

    try:
        report = carry_owner_answer(args.path, extra_dirs=getattr(args, "answer_from", None) or ())
    except AnswerConflict as exc:
        print(f"REFUSED: {exc}\n"
              f"    статус НЕ изменён: закрыть карточку, не зная, какой ответ владельца "
              f"верен, значит потерять решение.", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — перенос не имеет права уронить саму очередь
        print(f"❓ перенос следа решения НЕ ИЗМЕРЕН ({exc}) — карточка закрывается без него",
              file=sys.stderr)
        return None

    verdict = report.get("verdict")
    if verdict == CARRY_CARRIED:
        print(f"✅ след решения владельца перенесён в карточку перед закрытием: "
              f"{', '.join(sorted(report.get('added') or {}))} (источник: {report.get('source')})",
              file=sys.stderr)
    elif verdict == CARRY_ALREADY_PRESENT:
        print("✅ след решения владельца уже в этой копии карточки — переносить нечего",
              file=sys.stderr)
    elif verdict == CARRY_NO_ANSWER:
        print(f"⚠️  следа ответа владельца ({', '.join(_IDENTITY_FIELDS)}) нет НИ В ОДНОЙ "
              f"копии карточки — в git уедет закрытая карточка без машинно проверяемого "
              f"следа решения. Так бывает, когда владелец ответил правкой статуса руками, "
              f"а не кнопкой; но молчать об этом нельзя.", file=sys.stderr)
    elif verdict == CARRY_UNMEASURED:
        print(f"❓ перенос следа решения НЕ ИЗМЕРЕН: {report.get('detail')}", file=sys.stderr)
    return None


def cmd_set_status(args) -> int:
    if args.status == _INGESTED:
        refused = _carry_answer_before_closing(args)
        if refused is not None:
            return refused
    try:
        set_status(args.path, args.status)
    except OwnerDoneForbidden as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {args.path} -> status: {args.status}")
    # Пересобирать доску ТОГО трекера, в котором лежит изменённая карточка, а не трекер
    # своего дерева. `set-status` принимает ПУТЬ к карточке — он может указывать в соседнее
    # дерево (worktree-протокол §3.4, ровно та же ловушка, что закрыта в `cmd_create`
    # предупреждением `_warn_if_foreign_tree`). Без этого статус менялся в одном дереве, а
    # доска пересобиралась в другом: карточка становилась `done`, а доска продолжала звать
    # её `new` — замер 17.08, три расхождения на 508 карточек, дважды взята закрытая работа.
    _rebuild_board(tracker_dir=Path(args.path).resolve().parent)
    return 0


def _repo_top(path) -> str | None:
    """Корень рабочего дерева, которому принадлежит путь. None — не измерилось."""
    import subprocess
    try:
        res = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def _warn_if_foreign_tree(path: Path) -> None:
    """ГРОМКО (в stderr) сказать, что карточка легла в ДРУГОЕ рабочее дерево, чем текущее.

    **Зачем.** `create` пишет карточку в трекер того дерева, чья копия этого скрипта
    запущена (cwd не влияет — измерено циклом #140). Протокол §3.4 обязывает работать и
    пушить из изолированного worktree, а списки файлов на пуш собираются по нему — карточка,
    созданная копией из хост-дерева, в них не попадает НИКОГДА. Так осиротела
    `inbox-audit-prigodnosti-ne-videl-186-modulei-t` (создана 19:34, уже после финального
    объявления цикла #138 в 19:18) — и нашлась случайно, сверкой имён.

    Предупреждение — не гарантия (оно держится на внимательности, а она здесь однажды уже
    отказала); сторож, который не держится ни на чьей внимательности, — сверка карточек в
    `scripts/check_undelivered_work.py` (шаг 0a). Здесь — ранний громкий сигнал В МОМЕНТ
    дефекта. stdout не трогается: он машинный контракт (`create` печатает ТОЛЬКО путь).
    """
    card_top = _repo_top(path.parent)
    cwd_top = _repo_top(Path.cwd())
    if card_top and cwd_top and Path(card_top).resolve() != Path(cwd_top).resolve():
        print(f"⚠️  карточка создана в ДРУГОМ рабочем дереве: {card_top}\n"
              f"    вы работаете в: {cwd_top}\n"
              f"    её нет в вашем дереве ⇒ в список пуша она не попадёт. Либо создавайте "
              f"карточку своим деревом (--tracker-dir <ваше дерево>/nimbalyst-local/tracker), "
              f"либо добавьте {path} в пуш явно.", file=sys.stderr)


def cmd_create(args) -> int:
    body = args.body or ""
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as fh:
            body = fh.read()
    extra = {}
    for kv in args.field or []:
        k, _, v = kv.partition("=")
        if k:
            extra[k.strip()] = v.strip()
    try:
        path = create_card(
            args.type, args.title, body,
            status=args.status, source=args.source, extra_fields=extra or None,
            tracker_dir=args.tracker_dir,
        )
    except OwnerDoneForbidden as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(str(path))
    _warn_if_foreign_tree(Path(path))
    _rebuild_board(tracker_dir=args.tracker_dir)
    return 0


def cmd_ingest_notes(args) -> int:
    created = ingest_notes(notes_dir=args.dir)
    if not created:
        print("(no loose notes to ingest)")
    for p in created:
        print(f"ingested -> {p}")
    if created:
        _rebuild_board()
    return 0


def cmd_promotions(args) -> int:
    proms = scan_promotions()
    if args.json:
        print(json.dumps([{"path": str(p.path), "title": p.title, "snippet": p.snippet} for p in proms],
                         ensure_ascii=False, indent=2))
    else:
        if not proms:
            print("(no #promote tags found in docs/ideas/ or docs/rules-draft/)")
        for p in proms:
            print(f"#promote  {p.path}  —  {p.title}")
    return 0


def cmd_notify(args) -> int:
    msg = notify_needs_owner(args.path, dry_run=args.check)
    if args.check:
        print(msg)
    else:
        print(f"OK: notified for {args.path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Разбор аргументов отдельно от запуска: тесты обязаны звать РЕАЛЬНЫЙ путь команды
    (парсер + `cmd_*`), а не собирать args вручную мимо умолчаний парсера."""
    p = argparse.ArgumentParser(description="Owner-queue CLI (files-first tracker cards)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list cards, optionally filtered")
    pl.add_argument("--type", default=None, help="trackerStatus.type (owner-decision|inbox)")
    pl.add_argument("--status", default=None, help="status filter (needs-owner|owner-done|ingested|...)")
    pl.add_argument("--json", action="store_true", help="JSON output")
    pl.add_argument("--tracker-dir", default=None,
                    help="каталог трекера (по умолчанию — трекер дерева этой копии скрипта)")
    pl.add_argument("--no-origin-check", dest="origin_check", action="store_false",
                    help="НЕ сверять трекер с origin/main. Список станет неподтверждённым: "
                         "он может показывать закрытое и прятать новое (дефект #147)")
    pl.add_argument("--ref", default=None, help="с чем сверять трекер (по умолчанию origin/main)")
    pl.set_defaults(func=cmd_list, origin_check=True, ref=None)

    ps = sub.add_parser("set-status", help="atomically set a card's status (owner-done FORBIDDEN)")
    ps.add_argument("path")
    ps.add_argument("status")
    ps.add_argument("--answer-from", action="append", default=None,
                    help="каталог трекера, где искать след ответа владельца перед `ingested` "
                         "(повторяемый). По умолчанию — рабочие деревья этого репозитория, "
                         "главное первым: бот пишет ответ именно туда")
    ps.set_defaults(func=cmd_set_status)

    pc = sub.add_parser("create", help="create a new card (used by Telegram/Obsidian intake)")
    pc.add_argument("--type", required=True, help="tracker type (inbox|owner-decision)")
    pc.add_argument("--title", required=True)
    pc.add_argument("--body", default=None)
    pc.add_argument("--body-file", default=None)
    pc.add_argument("--status", default=None)
    pc.add_argument("--source", default=None, help="nimbalyst|obsidian|telegram|voice")
    pc.add_argument("--field", action="append", help="extra frontmatter k=v (repeatable)")
    pc.add_argument("--tracker-dir", default=None,
                    help="куда положить карточку (по умолчанию — трекер ДЕРЕВА ЭТОГО СКРИПТА; "
                         "работая в worktree, указывайте свой, иначе карточка не попадёт в пуш)")
    pc.set_defaults(func=cmd_create)

    pi = sub.add_parser("ingest-notes", help="convert loose Obsidian inbox/ notes → Inbox cards")
    pi.add_argument("--dir", default=None, help="notes dir (default: repo inbox/)")
    pi.set_defaults(func=cmd_ingest_notes)

    pp = sub.add_parser("promotions", help="list #promote-tagged ideas/rules-draft (Этап 7.3)")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_promotions)

    pn = sub.add_parser("notify", help="Telegram-notify a needs-owner card (§3.3)")
    pn.add_argument("path")
    pn.add_argument("--check", action="store_true", help="build message, do not send")
    pn.set_defaults(func=cmd_notify)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
