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
    scan_promotion_mentions,
    scan_promotions,
    first_instruction_line,
    list_cards,
    set_acceptance_probe,
    set_status,
)
from spa_core.owner_queue.notify import (
    delivery_verdict, notify_needs_owner, refusal_reason,
)
from spa_core.owner_queue.owner_answer import (
    AnswerConflict,
    CARRY_ALREADY_PRESENT,
    CARRY_CARRIED,
    CARRY_NO_ANSWER,
    CARRY_PROVENANCE,
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
        # `--no-origin-check`: пересборка идёт ПОСЛЕ КАЖДОЙ мутации карточки (в том числе
        # из бота, отвечающего владельцу), а сверка с origin стоит ~84 с на живом трекере —
        # 1041 процесс git, из них 261 обход истории (замер #436). Ждать их на создании
        # карточки нельзя. Доска при этом НЕ врёт: без сверки она печатает в шапке
        # «Сверка с origin НЕ ИЗМЕРЕНА (сверка не запрашивалась)», а полную доску собирает
        # явный прогон `python3 scripts/build_tracker_board.py`. Ускорение самой сверки
        # названо карточкой `inbox-sverka-trekera-s-origin-stoit-84-sekundy`.
        with contextlib.redirect_stdout(io.StringIO()):
            mod.main(["--no-origin-check"])
    except Exception:  # noqa: BLE001
        pass


# ── вердикт сверки с origin, который ЕДЕТ В JSON ─────────────────────────────
# stdout — машинный контракт, и шаг 2 протокола читает именно его
# (`list --type owner-decision --status owner-done --json`). Пока вердикт жил
# только в stderr-прозе, сессия с `| jq` его не видела ВООБЩЕ. Замер 09.08:
# хост-дерево выдало 2 карточки `owner-done`, обе на origin уже `ingested`.
VERDICT_AGREES = "agrees"                     # дерево и origin совпали
VERDICT_STALE = "stale_read_from_origin"      # карточка перечитана с origin
# Файла в дереве нет ВОВСЕ, а на origin карточка есть. До цикла #395 такая карточка
# в список не попадала: компенсация read-through умела только «локальная копия устарела».
# Замер 27.08 (цикл #393/#395): прод-дерево отвечало `inbox/new` = 42 при 89 на origin и
# `owner-done` = 0 при 2 — уверенный НОЛЬ там, где верный ответ «очередь неполна».
VERDICT_HIDDEN = "hidden_read_from_origin"
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
                         ref: str | None = None) -> tuple[list, dict[str, dict], list[str], bool]:
    """Сверить читаемый трекер с `origin/main` и ГРОМКО назвать расхождение (шаг 1-пред).

    Возвращает `(карточки, вердикты, непрочитанные-невидимые, состоялась-ли-сверка)`.
    Третий элемент — имена карточек, которые есть на `origin`, файла в дереве нет И
    прочитать их не удалось: по нему `cmd_list` отвечает кодом 2, потому что СОСТАВ
    списка не измерен.

    Четвёртый элемент — ОТВЕТ НА ВОПРОС «сверка вообще состоялась?» (ADR-166). Он
    существует потому, что три ветки ниже возвращают пустые находки по двум РАЗНЫМ
    причинам, неотличимым по возвращаемому значению: «сверил и расхождений нет» и
    «сверить не удалось вовсе». Первое — измеренная тишина, второе — незнание, и
    выдавать второе за первое значит ровно то, ради чего вся эта сверка написана.

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
        return cards, verdicts, [], False
    try:
        report = drift.analyze(tracker_dir, ref or drift.DEFAULT_REF)
    except drift.Unmeasured as exc:
        print(f"❓ сверка трекера с origin/main НЕ ИЗМЕРЕНА — {exc}\n"
              f"    список ниже НЕ подтверждён: он может показывать закрытое и прятать новое.",
              file=sys.stderr)
        return cards, verdicts, [], False
    # Сверка состоялась ⇒ у всех карточек вердикт по умолчанию «совпало»; ниже он
    # уточняется поимённо для тех, у кого есть находка.
    verdicts = {c.id: {"origin_check": VERDICT_AGREES} for c in cards}
    if not report.findings:
        return cards, verdicts, [], True

    try:
        root = drift.repo_root_of(Path(report.tracker_dir))
        rel = Path(report.tracker_dir).resolve().relative_to(root.resolve()).as_posix()
    except (drift.Unmeasured, ValueError) as exc:
        # Сторож не имеет права уронить саму очередь: сверка — довесок к списку, а не его условие.
        print(f"❓ расхождение найдено, но версию с origin взять неоткуда ({exc})", file=sys.stderr)
        # Расхождение ЕСТЬ, а разобрать его нечем ⇒ «совпало» здесь было бы враньём.
        return cards, {c.id: {"origin_check": VERDICT_UNMEASURED} for c in cards}, [], False
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

    # ── «локальной копии НЕТ» — тот же вопрос «что на origin», что и «копия устарела» ──
    #
    # Замер 27.08 (циклы #393/#395). Протокол велит делать шаги 1 и 2 из прод-дерева.
    # Оттуда `list --type inbox --status new` отвечал **42**, а тот же вопрос чистому
    # `origin/main` на том же sha — **89**; `owner-done` — **0** против **2**. Причина не
    # в статусах: файлов этих карточек в прод-дереве нет ВООБЩЕ. Компенсация read-through
    # умела ровно одно — «локальная копия устарела» (`KIND_STALE`) — и карточка, которой
    # в дереве нет, в неё не попадала: `by_id.get(...)` отдавал `None`, и цикл её пропускал.
    #
    # Опасна была ФОРМА ответа: инструмент печатал уверенное ЧИСЛО, а не «не измерено».
    # `owner-done: 0` читается как «очередь разобрана» — молчание, неотличимое от одобрения,
    # ровно тот класс, который проект ловит у сторожей. Решение владельца могло ждать
    # инжеста сутками, и заметить это было некому.
    #
    # Чиним ПРИЧИНУ, а не симптом: у одного инструмента не может быть двух разных ответов
    # на один вопрос «что на origin». Карточка дочитывается с origin и ВХОДИТ в список.
    # Путь остаётся тем, каким он был бы в этом дереве, — файла по нему нет, поэтому
    # `set-status` откажет ГРОМКО (это верно: править надо из worktree на origin/main).
    hidden_cards: list = []
    hidden_unread: list[str] = []
    for f in report.of_kind(drift.KIND_HIDDEN):
        if f.card_id in by_id:  # в дереве файл всё-таки есть — не наш случай
            continue
        try:
            fresh = drift.read_origin_card(root, report.ref, f"{rel}/{f.card_id}.md")
        except drift.Unmeasured as exc:
            print(f"❓ {f.card_id}: есть на {report.ref}, в дереве файла нет, и версию с "
                  f"origin прочитать не удалось ({exc})", file=sys.stderr)
            hidden_unread.append(f.card_id)
            continue
        fresh.path = Path(report.tracker_dir) / f"{f.card_id}.md"
        hidden_cards.append(fresh)
        verdicts[f.card_id] = {
            "origin_check": VERDICT_HIDDEN,
            "origin_check_note": (
                f"файла в этом дереве нет — карточка прочитана с {report.ref}; "
                f"`set-status` по этому пути откажет, работайте из worktree от {report.ref}"
            ),
        }

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

    stale = report.of_kind(drift.KIND_STALE)
    diverged, undelivered = report.of_kind(drift.KIND_DIVERGED), report.of_kind(drift.KIND_UNDELIVERED)
    print(f"⚠️  трекер этого дерева РАСХОДИТСЯ с {report.ref} ({report.ref_sha[:9] or '?'}): "
          f"в дереве {report.tree_count}, на {report.ref} {report.origin_count}", file=sys.stderr)
    if stale:
        print(f"    · устарели и прочитаны С ORIGIN ({len(stale)}): {_ids(drift.KIND_STALE)}",
              file=sys.stderr)
    if hidden_cards:
        print(f"    · ЕСТЬ НА ORIGIN, В ДЕРЕВЕ НЕТ ({len(hidden_cards)}) — ПРОЧИТАНЫ С "
              f"{report.ref} и ВОШЛИ в список ниже; файла в дереве нет, поэтому "
              f"`set-status` по ним откажет — работайте из worktree от {report.ref}: "
              f"{', '.join(sorted(c.id for c in hidden_cards))}", file=sys.stderr)
    if hidden_unread:
        print(f"    · 🔴 ЕСТЬ НА ORIGIN, В ДЕРЕВЕ НЕТ и ПРОЧИТАТЬ НЕ УДАЛОСЬ "
              f"({len(hidden_unread)}) — список ниже НЕПОЛОН по составу: "
              f"{', '.join(sorted(hidden_unread))}", file=sys.stderr)
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
    return [by_id[c.id] for c in cards] + hidden_cards, verdicts, hidden_unread, True


def _tracker_dir_of(args):
    """Каталог очереди, с которым работает ЭТА команда. Одна точка разрешения на команду.

    Тот же порядок, что у пересборки доски (`_rebuild_board`): явный `--tracker-dir`
    главнее умолчания модуля, а умолчание спрашивается У МОДУЛЯ В МОМЕНТ ВЫЗОВА, а не
    берётся из копии, снятой при импорте.

    **Почему это не косметика.** `cmd_list` делает два разных дела с очередью — печатает
    её и спрашивает про ответ владельца в главном дереве — и до этой правки второе шло
    по копии `TRACKER_DIR`, снятой в момент импорта скрипта. Одна команда работала с
    ДВУМЯ каталогами: список — из указанного, сверка деревьев — из чужого. Замер 21.08:
    под тестом с песочницей-трекером сверка отвечала про НАСТОЯЩИЕ рабочие деревья и
    подмешивала в stdout живые `owner-done` карточки прода ⇒ вердикт набора зависел от
    того, разобрал ли кто-то почту владельца, и красный CI переставал говорить о коде.
    Утверждения тестов при этом были ВЕРНЫ — чинить надо было адрес, а не проверку.
    """
    from spa_core.owner_queue import queue as _queue

    return getattr(args, "tracker_dir", None) or getattr(_queue, "TRACKER_DIR", None)


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
    hidden_unread: list[str] = []
    #: Сверка НЕ СОСТОЯЛАСЬ не по воле вызывающего ⇒ код 2 (ADR-166). См. блок в конце.
    origin_unmeasured = False
    if getattr(args, "origin_check", True):
        cards, verdicts, hidden_unread, origin_measured = _origin_read_through(
            cards, _tracker_dir_of(args), getattr(args, "ref", None))
        origin_unmeasured = not origin_measured
    else:
        # Сверку выключили явным флагом. Это НЕ «совпало» — это «не измерено»,
        # и в машинном контракте оно обязано выглядеть именно так: у каждой карточки
        # в JSON стоит `origin_check: unmeasured` (`_card_dict` ставит его по умолчанию).
        #
        # Код возврата при ЭТОМ отказе остаётся 0 — и это решение, а не недосмотр
        # (ADR-166). Красный код на состояние, которое вызывающий заказал сам, — это
        # проверка, срабатывающая на штатном входе; она не добавляет знания (тот, кто
        # написал флаг, уже знает, что не мерил) и учит гасить сигнал. Ровно этот довод
        # закреплён в `.claude/rules/deployment.md` про храповик литеральных дат:
        # «запрет в лоб покрасил бы половину набора, научив всех его отключать».
        print("❓ сверка с origin ОТКЛЮЧЕНА флагом --no-origin-check: список не подтверждён",
              file=sys.stderr)

    cross_verdict, foreign, cross_reason = _cross_tree_owner_answers(
        _tracker_dir_of(args), now=getattr(args, "now", None))
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
    # Карточка есть на origin, файла в дереве нет, И прочитать её с origin не удалось ⇒
    # СОСТАВ списка не измерен. Число здесь врало бы ровно тем способом, ради которого
    # написана вся эта сверка: уверенный ответ там, где верный ответ — «не знаю».
    # Фильтры к непрочитанной карточке неприменимы (её `type`/`status` неизвестны), поэтому
    # код возврата не зависит от `--type`/`--status`: fail-CLOSED к составу всей очереди.
    if hidden_unread:
        print(f"❓ СОСТАВ списка НЕ ИЗМЕРЕН: {len(hidden_unread)} карточк(и) есть на origin, "
              f"в дереве их нет, и прочитать с origin не удалось (код 2).", file=sys.stderr)
        return 2
    # Сверка с origin не состоялась ЦЕЛИКОМ (сторож не импортировался · `analyze` бросил
    # `Unmeasured` · находки есть, а версию с origin взять неоткуда). ADR-153 закрыл узкую
    # ветку — одну невидимую карточку; эта ветка ШИРЕ и опаснее: не измерено НИЧЕГО.
    #
    # Почему код 2 здесь НЕ зависит от пустоты списка, в отличие от `cross_tree_check`.
    # Непроведённый опрос главного дерева может только НЕ ДОБАВИТЬ карточек — те, что
    # показаны, остаются верными, поэтому там опасна ровно пустота. Несостоявшаяся сверка
    # с origin врёт в ОБЕ стороны сразу (сторож так и говорит: «может показывать закрытое
    # и прятать новое»), и непустой список подтверждён ровно настолько же, насколько
    # пустой, — то есть никак. Фильтры `--type`/`--status` тем более ничего не спасают:
    # они применяются к статусам, которые и не измерены.
    #
    # Замер до починки (цикл #425, 29.08, на чистом `origin/main` a0a9e6e93):
    # `list --tracker-dir <каталог вне git> --type inbox --status new --json` печатал одну
    # карточку и возвращал 0 — `| jq length` давал уверенное число, код возврата давал
    # «всё хорошо», а в stderr стояло «сверка НЕ ИЗМЕРЕНА».
    if origin_unmeasured:
        print("❓ СВЕРКА С ORIGIN НЕ СОСТОЯЛАСЬ — состав списка не измерен ни в одну "
              "сторону: он может показывать закрытое и прятать новое (код 2).",
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
    elif verdict == CARRY_PROVENANCE:
        named = "; ".join(f"{k}: {v}" for k, v in (report.get("provenance") or {}).items())
        carried = ", ".join(sorted(report.get("added") or {}))
        print(f"✅ решение владельца ОДНО (`owner_choice` совпал) — человек не нужен; "
              f"разошёлся лишь ПРОВЕНАНС ({named}) и НЕ перенесён ни в какую сторону: "
              f"выбрать одну отметку значит затереть другую"
              + (f". Перенесено: {carried}" if carried else ""), file=sys.stderr)
    elif verdict == CARRY_UNMEASURED:
        print(f"❓ перенос следа решения НЕ ИЗМЕРЕН: {report.get('detail')}", file=sys.stderr)
    else:
        # Цепочка без `else` глушила бы незнакомый вердикт: новый исход, добавленный в
        # `carry_owner_answer` и забытый здесь, уходил бы в тишину — а тишина здесь
        # неотличима от «перенос отработал». Молчать нельзя даже о собственном незнании.
        print(f"❓ перенос следа решения: НЕЗНАКОМЫЙ вердикт `{verdict}` — эта дверь его не "
              f"знает, поэтому НИЧЕГО не утверждает о переносе ({report.get('detail')})",
              file=sys.stderr)
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
    # `args.path` может указывать в СОСЕДНЕЕ дерево (worktree §3.4) — доску обязано
    # пересобрать то дерево, чью карточку только что поменяли, а не дерево этой копии
    # скрипта (иначе карточка становится `done`, а её доска продолжает звать её `new`).
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


def _validate_acceptance_probe(extra: dict) -> str | None:
    """Проба обязана быть ЗАРЕГИСТРИРОВАННОЙ уже при рождении карточки (ADR-209).

    Реестр ОДИН — `card_acceptance.PROBES`; второй копии здесь нет намеренно (класс
    «два реестра под одним именем»): писатель и читатель обязаны спорить о том же
    списке, иначе валидация разрешит имя, которого у читателя нет.

    Почему отказ, а не предупреждение: `run_probe` на незарегистрированное имя честно
    отвечает `unmeasured`, и в отчёте это читается как «нечем проверить сегодня», тогда
    как значит «этот критерий не будет измерен НИКОГДА». Опечатку видно только тому, кто
    помнит реестр наизусть.

    Возврат: None — годится (в том числе когда пробы нет вовсе), иначе причина отказа.
    Нечем проверить (модуль не импортируется) — тоже отказ: пустить непроверенное имя
    значило бы сделать валидацию fail-OPEN ровно там, где она нужна.
    """
    spec = extra.get("acceptance_probe")
    if spec is None:
        return None
    try:
        from spa_core.monitoring.card_acceptance import validate_spec
    except Exception as exc:  # noqa: BLE001 — «нечем проверить» ≠ «годится»
        return (f"проба объявлена, но проверить её нечем: {type(exc).__name__}: {exc}. "
                f"Реестр проб недоступен — карточку с непроверенной пробой не создаём")
    return validate_spec(spec)


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
    if getattr(args, "acceptance_probe", None):
        extra["acceptance_probe"] = args.acceptance_probe.strip()
    reason = _validate_acceptance_probe(extra)
    if reason is not None:
        print(f"REFUSED: acceptance_probe — {reason}", file=sys.stderr)
        return 2
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


def cmd_probe(args) -> int:
    """Прикрепить машинный критерий приёмки к УЖЕ написанной карточке (ADR-209)."""
    reason = _validate_acceptance_probe({"acceptance_probe": args.probe})
    if reason is not None:
        print(f"REFUSED: acceptance_probe — {reason}", file=sys.stderr)
        return 2
    path = Path(args.path)
    if not path.is_file():
        print(f"ERROR: карточки нет: {path}", file=sys.stderr)
        return 1
    try:
        previous = set_acceptance_probe(path, args.probe.strip())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    was = f" (было: {previous})" if previous else ""
    print(f"OK: {path} -> acceptance_probe: {args.probe.strip()}{was}")
    # Сразу назвать вердикт: молча записанная проба неотличима от записанной с опечаткой
    # в аргументе — имя реестр проверил, а КЛЮЧ проверить может только сама проба.
    try:
        from spa_core.monitoring.card_acceptance import run_probe
        verdict, detail = run_probe(args.probe.strip())
        print(f"    проба сейчас даёт: {verdict} — {detail}")
    except Exception as exc:  # noqa: BLE001 — это справка, а не гейт
        print(f"    [НЕ ИЗМЕРЕНО] пробу не удалось прогнать: {type(exc).__name__}: {exc}")
    _rebuild_board(tracker_dir=path.resolve().parent)
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
    """Шаг 1б: что владелец ПОМЕТИЛ к промоушену — и что лишь ГОВОРИТ о метке.

    Второе печатается в stderr рядом с первым (машинный контракт stdout не меняется):
    отказ читать цитату как метку обязан быть слышен, иначе fail-CLOSED «нет»
    неотличимо от «ничего не нашли» и настоящее пожелание владельца утонет молча.
    """
    proms = scan_promotions()
    if args.json:
        print(json.dumps([{"path": str(p.path), "title": p.title, "snippet": p.snippet} for p in proms],
                         ensure_ascii=False, indent=2))
    else:
        if not proms:
            print("(no #promote tags found in docs/ideas/ or docs/rules-draft/)")
        for p in proms:
            print(f"#promote  {p.path}  —  {p.title}")
    for m in scan_promotion_mentions():
        print(f"ℹ️  разговор О метке, НЕ промоушен (действовать нельзя): {m.path} — {m.snippet}",
              file=sys.stderr)
    return 0


def cmd_notify(args) -> int:
    """Отправить вопрос владельцу и ОТЧИТАТЬСЯ ИЗМЕРЕННЫМ исходом, а не намерением.

    До 26.08 здесь стояло безусловное «OK: notified» и код 0 — при том, что между этой
    строкой и владельцем стоит `guard_outbound` (дедуп по тексту 30 мин + лимит потока
    12/мин), который роняет сообщение молча. Живой случай цикла #385: две попытки подряд
    погашены дедупом, оба раза команда ответила «OK», и вопрос владельцу остался
    незаданным. Журнал отправок исход знает с #309 — не знал его только тот, кто читает
    вывод команды.

    Коды: **0** — доставлено · **1** — НЕ отправлено (заслон/отказ отправителя) ·
    **2** — не измерено (конвенция репозитория; «не знаю» не есть «ок»).

    **Вопрос здесь — про ЭТОТ прогон, а не про жизнь карточки** (замер 2026-09-01,
    цикл #447). Возврат ``notify_needs_owner`` выбрасывался, и об исходе судил один
    ``delivery_verdict`` — а он читает журнал отправок, где запись могла остаться от
    ЛЮБОГО прежнего отправителя. Живой случай: анти-шторм отказал («уходила 9 мин
    назад»), журнал не изменился ни на байт, отправки в этом прогоне не было вовсе —
    команда напечатала «OK: notified — доставлено» и вернула 0, потому что нашла
    запись чужой посылки. Заявленный код 1 был при этом недостижим для всех трёх
    гейтов (``[skip]``, ``[anti-storm]``, ``[переписана]``): каждый возвращает причину
    ДО отправки, и каждая читалась как успех.

    Тот же класс, что чинили в самой функции 26.08 и в утреннем дайджесте 01.08:
    зелёный ответ на СВОЙ вопрос («карточка когда-то доезжала») читается как ответ на
    нужный («вопрос задан сейчас»). Поэтому отказ гейта проверяется ПЕРВЫМ, и никакая
    запись журнала его больше не перебивает.
    """
    msg = notify_needs_owner(args.path, dry_run=args.check)
    if args.check:
        print(msg)
        return 0

    refused = refusal_reason(msg)
    if refused is not None:
        # Гейт отказал ДО отправки — в этом прогоне владельцу не ушло ничего.
        # Прежнюю жизнь карточки печатаем ВТОРОЙ строкой и НЕ как исход: у владельца
        # на руках может лежать более старая копия вопроса, и это отдельный факт,
        # а не оправдание молчания.
        print(f"НЕ ОТПРАВЛЕНО: {args.path}\n"
              f"  в этом прогоне не отправлялось — {refused}")
        prior, prior_detail = delivery_verdict(args.path)
        was = {True: "доезжала РАНЬШЕ",
               False: "прежняя попытка не уехала",
               None: "прежних отправок не измерено"}[prior]
        print(f"  журнал отправок (о ПРОШЛОМ, не об этом прогоне): {was} — {prior_detail}")
        return 1

    delivered, detail = delivery_verdict(args.path)
    if delivered is True:
        print(f"OK: notified for {args.path} — {detail}")
        return 0
    if delivered is False:
        print(f"НЕ ОТПРАВЛЕНО: {args.path}\n  {detail}")
        return 1
    print(f"НЕ ИЗМЕРЕНО, отправлено ли: {args.path}\n  {detail}")
    return 2


def cmd_resend_open(args) -> int:
    """Переслать владельцу все открытые вопросы заново, по одному (решение 20.08, вар. 2).

    Код возврата — ЕДИНСТВЕННЫЙ канал недоставки для вызывающего (ADR-084): 0 — все
    вопросы доехали (или это сухой прогон) И очередь сверена с `origin/main`; 1 — хотя бы
    один не доехал ИЛИ очередь сверить не удалось. Частичная рассылка успехом не считается:
    молчание о потерянном вопросе и есть та поломка, которую владелец ловил руками.

    Несверённая очередь роняет код и в сухом прогоне намеренно: «вопросов нет» и «вопросов
    не видно» снаружи выглядят одинаково, а стоила эта неразличимость восьми невидимых
    вопросов владельцу (#330). Зелёный код обязан означать замер, а не удачу.
    """
    from spa_core.owner_queue.resend import resend_open_questions, summary_line

    report = resend_open_questions(dry_run=args.check,
                                   tracker_dir=args.tracker_dir,
                                   limit=args.limit)
    print(summary_line(report))
    for o in report.outcomes:
        mark = "✅" if o.delivered else ("·" if report.dry_run else "❌")
        extra = "" if o.delivered or report.dry_run else f" — {o.reason}"
        print(f"  {mark} {o.card_id} — {o.title}{extra}")
    if not report.queue_measured:
        return 1
    return 0 if report.ok or report.dry_run else 1


def cmd_deliver_new(args) -> int:
    """Доставить владельцу вопросы, которых он НЕ ВИДЕЛ НИ РАЗУ (первая отправка).

    Отличие от `resend-open` — не в объёме, а в правах: пересылка идёт по ПРОСЬБЕ
    владельца и снимает дедуп с анти-штормом всему набору; первая доставка идёт по нашей
    инициативе и обязана идти при ВСЕХ включённых заслонах. Смешать их значило бы завести
    второй, неподотчётный путь повторов (жалобы владельца #215/#217/#228, ADR-084).

    Код возврата — единственный канал недоставки для вызывающего (ADR-084): 0 — всё
    попытанное доехало (или сухой прогон) И очередь сверена с `origin/main`; 1 — что-то
    не доехало ИЛИ очередь сверить не удалось. Несверённая очередь роняет код и в сухом
    прогоне: «новых вопросов нет» и «новых вопросов не видно» снаружи одинаковы, а стоила
    эта неразличимость восьми невидимых вопросов владельцу (#330).
    """
    from spa_core.owner_queue.first_delivery import (FIRST_DELIVERY_PER_RUN,
                                                     deliver_new_questions,
                                                     summary_line)

    limit = FIRST_DELIVERY_PER_RUN if args.limit is None else args.limit
    report = deliver_new_questions(dry_run=args.check,
                                   tracker_dir=args.tracker_dir,
                                   limit=limit)
    print(summary_line(report))
    for o in report.outcomes:
        mark = "✅" if o.delivered else ("·" if report.dry_run else "❌")
        extra = "" if o.delivered or report.dry_run else f" — {o.reason}"
        print(f"  {mark} {o.card_id} — {o.title}{extra}")
    if not report.queue_measured:
        return 1
    return 0 if report.ok or report.dry_run else 1


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
    pc.add_argument("--acceptance-probe", default=None,
                    help="машинный критерий приёмки: <проба> либо <проба>:<ключ> "
                         "(реестр — spa_core.monitoring.card_acceptance.PROBES). "
                         "Незарегистрированное имя ⇒ ОТКАЗ, а не тихое «не измерено»")
    pc.add_argument("--tracker-dir", default=None,
                    help="куда положить карточку (по умолчанию — трекер ДЕРЕВА ЭТОГО СКРИПТА; "
                         "работая в worktree, указывайте свой, иначе карточка не попадёт в пуш)")
    pc.set_defaults(func=cmd_create)

    pb = sub.add_parser("probe", help="attach a machine acceptance criterion to an existing card (ADR-209)")
    pb.add_argument("path", help="путь к карточке")
    pb.add_argument("probe", help="<проба> либо <проба>:<ключ>; незарегистрированное имя ⇒ ОТКАЗ")
    pb.set_defaults(func=cmd_probe)

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

    pr = sub.add_parser("resend-open",
                        help="переслать владельцу ВСЕ открытые вопросы заново, по одному")
    pr.add_argument("--check", action="store_true",
                    help="показать, что уедет, и НЕ отправлять")
    pr.add_argument("--limit", type=int, default=None, help="не больше N вопросов")
    pr.add_argument("--tracker-dir", default=None,
                    help="каталог трекера (по умолчанию — трекер дерева этой копии скрипта)")
    pr.set_defaults(func=cmd_resend_open)

    pd = sub.add_parser("deliver-new",
                        help="доставить владельцу вопросы, которых он НЕ ВИДЕЛ НИ РАЗУ")
    pd.add_argument("--check", action="store_true",
                    help="показать, что уедет, и НЕ отправлять")
    # Умолчание НЕ дублируется здесь числом: потолок живёт одной строкой в
    # `first_delivery.FIRST_DELIVERY_PER_RUN`, а `None` означает «взять его оттуда».
    pd.add_argument("--limit", type=int, default=None,
                    help="не больше N первых отправок за прогон (умолчание — потолок "
                         "модуля; остаток НАЗЫВАЕТСЯ, не усекается молча)")
    pd.add_argument("--tracker-dir", default=None,
                    help="каталог трекера (по умолчанию — трекер дерева этой копии скрипта)")
    pd.set_defaults(func=cmd_deliver_new)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
