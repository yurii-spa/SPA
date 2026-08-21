#!/usr/bin/env python3
# LLM_FORBIDDEN
"""safe_site_push — the ONLY sanctioned path for the autonomous orchestrator to push
site (landing/) changes to live earn-defi.com.

Owner-approved 2026-07-15 (ADR-OWN-2026-07-autoship): full autonomous auto-ship of SAFE
site changes; OWNER-GATED classes (yield numbers / tier naming / SPA expansion / legal /
solicitation / honesty-token removal) route to a needs-owner card and never auto-ship.

Flow:
  1. Run the owner-gate guard (scripts/check_owner_gate.py --diff-mode files) on the
     landing/ targets.
  2. CLEAN (exit 0) → set SPA_SITE_PUSH_VERIFIED=1 and delegate to push_to_github_batch.py
     (one commit). The raw push tools honour that marker and allow the push.
  3. GATED (exit 2) → do NOT push. Open a `needs-owner` card summarising the blocked
     change + violations, notify the owner, exit 2. The orchestrator continues other work.
  4. Guard ERROR (exit 1) → fail CLOSED: do NOT push, exit 1.

Why a wrapper AND a hard interlock in the push tools: an LLM can forget to call this
wrapper. The deterministic interlock in push_to_github*.py (active only when
SPA_AUTONOMOUS=1) refuses any autonomous landing/ push that did not go through here.

Pure stdlib. Attended sessions may also use this wrapper; it just adds the guard +
card-routing around a normal push.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_GUARD = _REPO_ROOT / "scripts" / "check_owner_gate.py"
_BATCH = _REPO_ROOT / "push_to_github_batch.py"


def _run_guard(site_files: list[str], message: str) -> tuple[int, dict]:
    """Run the guard on the given files; return (exit_code, report_dict)."""
    cmd = [
        sys.executable, str(_GUARD),
        "--diff-mode", "files", "--files", *site_files,
        "--commit-message", message or "", "--report",
    ]
    rc = subprocess.run(cmd, cwd=str(_REPO_ROOT)).returncode
    report: dict = {}
    try:
        report = json.loads(
            (_REPO_ROOT / "data" / "owner_gate_check.json").read_text(encoding="utf-8")
        )
    except Exception:
        pass
    return rc, report


def _violations_fingerprint(violations: list) -> str:
    """Стабильный отпечаток НАБОРА нарушений: файл + правило, отсортировано.

    Порядок и текст совпадения намеренно не участвуют: линтер может выдать те же нарушения
    в другом порядке, а `matched_text` меняется от правки к правке внутри той же области —
    и то, и другое породило бы «новый инцидент» там, где решение владельцу нужно одно.
    """
    import hashlib

    parts = sorted(f"{v.get('file')}|{v.get('rule')}" for v in violations)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def _open_card_with_fingerprint(fingerprint: str):
    """Открытая (`needs-owner`) карточка с тем же отпечатком, если она есть.

    Никогда не бросает: сбой поиска не имеет права ПОДАВИТЬ карточку — в сомнении карточка
    создаётся (лучше лишняя, чем потерянное решение владельца).
    """
    try:
        from spa_core.owner_queue.queue import list_cards  # type: ignore

        for card in list_cards(tracker_type="owner-decision", status="needs-owner"):
            if f"owner-gate-fingerprint: {fingerprint}" in (card.body or ""):
                return card.path
    except Exception:  # noqa: BLE001
        return None
    return None


# ── Персистентный дедуп УВЕДОМЛЕНИЙ (спам владельцу, замер 21.08.2026) ─────────
#
# `_open_card_with_fingerprint` смотрит в трекер ЗАПУСКАЮЩЕГО дерева
# (`queue.TRACKER_DIR` = `<repo>/nimbalyst-local/tracker`). Автономный оркестратор
# бежит КАЖДЫЙ цикл в свежем worktree, где карточки прошлого цикла нет, а сама
# карточка на `origin` не возится (автосинк не тянет `nimbalyst-local/tracker/`,
# урок #193/#270). Поэтому worktree-проверка НИКОГДА не находит прежнюю карточку —
# и тот же owner-gated вопрос заводился и УВЕДОМЛЯЛСЯ владельцу каждый цикл. Окно
# анти-шторма в 30 минут (`telegram_client.DUPLICATE_WINDOW_S`) не спасает: циклы
# разнесены дальше, и каждый проходит окно как «новое» сообщение.
#
# Лечится тем, что «мы уже спросили владельца про ЭТОТ набор нарушений» пишется в
# ЖИВОЙ data-каталог (`live_data_dir`), а не в дерево запуска — и переживает смену
# worktree. Отпечаток набора нарушений стабилен между циклами, поэтому он и есть
# ключ. НЕ подавление: owner-gate по-прежнему НЕ пускает правку в live; тише
# становится только повтор ОДНОГО И ТОГО ЖЕ вопроса. Пропущенный вопрос всё равно
# виден: непрерывный сторож `owner_decision_pending` держит открытые вопросы
# владельца в отчёте (ежечасно, шаг 0-офис), а долгий откат ниже страхует от
# потерянного первого сообщения.
_NOTIFY_LEDGER_NAME = "owner_gate_notify_ledger.json"

#: Как долго один и тот же owner-gated вопрос НЕ переспрашивается у владельца. Не
#: «никогда»: первое сообщение могло не дойти (сеть), и раз в сутки напомнить —
#: это не спам. Переопределяется env для тестов.
_RENOTIFY_COOLDOWN_H = float(os.environ.get("SPA_OWNER_GATE_RENOTIFY_H", "24") or 24)


def _ledger_disabled() -> bool:
    """Под pytest реестр выключен, если тест явно не попросил обратного.

    Тот же приём, что у `telegram_client._record_history`: живой реестр лежит в
    `live_data_dir`, и без этого прогон тестов либо читал бы чужое состояние, либо
    писал бы файл в рабочее дерево. Тест, которому реестр НУЖЕН, ставит
    `SPA_OWNER_GATE_LEDGER_TEST=1` и указывает путь через `SPA_OWNER_GATE_LEDGER`.
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) and not os.environ.get(
        "SPA_OWNER_GATE_LEDGER_TEST"
    )


def _ledger_path() -> Path:
    override = os.environ.get("SPA_OWNER_GATE_LEDGER")
    if override:
        return Path(override)
    from spa_core.utils.live_paths import live_data_dir

    return live_data_dir(_REPO_ROOT) / _NOTIFY_LEDGER_NAME


def _recently_notified(fingerprint: str, *, now=None):
    """(skip, last_iso): уведомляли ли уже про ЭТОТ набор нарушений в окне отката.

    Fail-OPEN намеренно и ровно в эту сторону: нечитаемый/битый реестр НЕ имеет
    права ПОДАВИТЬ вопрос владельцу — в сомнении уведомляем (лучше лишний повтор,
    чем потерянное решение). Подавляет только ЯВНАЯ свежая запись.
    """
    if _ledger_disabled():
        return False, None
    import datetime as _dt

    now = now or _dt.datetime.now(_dt.timezone.utc)
    try:
        doc = json.loads(_ledger_path().read_text(encoding="utf-8"))
        rec = (doc.get("fingerprints") or {}).get(fingerprint)
    except Exception:  # noqa: BLE001 — нет/битый реестр ⇒ считаем «не уведомляли»
        return False, None
    if not isinstance(rec, dict):
        return False, None
    ts = rec.get("notified_at")
    try:
        last = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=_dt.timezone.utc)
    except Exception:  # noqa: BLE001 — неразборчивая отметка ⇒ уведомляем
        return False, None
    age_h = (now - last).total_seconds() / 3600.0
    return (0 <= age_h < _RENOTIFY_COOLDOWN_H), ts


def _record_notified(fingerprint: str, *, now=None) -> None:
    """Запомнить, что владельца про ЭТОТ набор нарушений уже уведомили. Не бросает.

    Записи старше двойного окла отката подрезаются — реестр не растёт бесконечно.
    """
    if _ledger_disabled():
        return
    import datetime as _dt

    now = now or _dt.datetime.now(_dt.timezone.utc)
    path = _ledger_path()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            doc = {}
    except Exception:  # noqa: BLE001
        doc = {}
    fps = doc.get("fingerprints")
    if not isinstance(fps, dict):
        fps = {}
    fps[fingerprint] = {"notified_at": now.isoformat()}
    # Подрезка: держим только записи в пределах 2× окна отката.
    cutoff = now - _dt.timedelta(hours=_RENOTIFY_COOLDOWN_H * 2)
    kept = {}
    for fp, rec in fps.items():
        if not isinstance(rec, dict):
            continue
        try:
            t = _dt.datetime.fromisoformat(str(rec.get("notified_at")).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=_dt.timezone.utc)
        except Exception:  # noqa: BLE001 — неразборчивую отметку не держим
            continue
        if t >= cutoff:
            kept[fp] = rec
    out = {"schema_version": 1, "source": "safe_site_push",
           "updated_at": now.isoformat(), "fingerprints": kept}
    try:
        from spa_core.utils.atomic import atomic_save

        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(out, str(path))
    except Exception as exc:  # noqa: BLE001 — учёт не важнее доставки
        print(f"safe_site_push: notify-ledger write failed ({exc})", file=sys.stderr)


def _rel(path: str) -> str:
    """Repo-relative POSIX path. The gate reports violations by repo-relative path
    (`landing/src/pages/x.astro`), while `--files` may arrive absolute; an `approves:`
    scope written in absolute form would never match a single violation and the
    owner's approval would silently authorise NOTHING (fail-OPEN by form).

    Относительный путь разрешается ОТ КОРНЯ РЕПО, а не от cwd. Замер 14.08 (CI гоняет
    тесты как `cd spa_core && pytest tests/`): вход `landing/src/pages/packages.astro`
    уже repo-relative, `os.path.abspath` домножал его на текущий каталог, и в карточку
    уезжал scope `spa_core/landing/…` — не совпадающий НИ С ОДНИМ нарушением. То есть
    ровно тот отказ, от которого эта функция и написана, только с другой стороны:
    одобрение владельца снова разрешало бы НОЛЬ файлов, и снова молча. Рабочий каталог
    у автономной сессии произвольный (worktree, каталог агента), так что в проде это
    не гипотетика."""
    try:
        raw = os.fspath(path)
        absolute = raw if os.path.isabs(raw) else os.path.join(str(_REPO_ROOT), raw)
        return os.path.relpath(os.path.normpath(absolute), str(_REPO_ROOT)).replace("\\", "/")
    except Exception:  # noqa: BLE001 — вне дерева: отдаём как есть, совпадения не будет
        return str(path).replace("\\", "/")


def _card_title(blocked: list[str]) -> str:
    """Заголовок карточки, РАЗЛИЧАЮЩИЙ два разных вопроса владельцу.

    Раньше заголовок был одной константой на все случаи. Цена этого замерена 09.08
    (карточка `inbox-statusy-kartochek-vladeltsa-perepisalis`): три карточки owner-gate
    с ДОСЛОВНО одинаковым заголовком, и живой вопрос владельцу закрылся сам, пока ответ
    по такому же заголовку лежал в соседней. Неотличимые заголовки — это условие ошибки:
    и человек в очереди, и любой сопоставитель обязаны видеть, о какой правке речь.

    Различает файл, а не время: два вопроса про ОДНУ правку обязаны остаться одним
    вопросом (дедуп `create_card` по заголовку+телу), иначе владелец снова получит
    поток одинаковых уведомлений.
    """
    head = Path(blocked[0]).name if blocked else "правка"
    more = f" и ещё {len(blocked) - 1}" if len(blocked) > 1 else ""
    return (f"Сайт: {head}{more} — автономная правка задела owner-gated область, "
            f"нужно решение")


def _route_to_owner_card(site_files: list[str], report: dict, message: str) -> None:
    """Create a needs-owner card for the blocked change and notify (best-effort).

    Карточка несёт `approves:` — ТОЧНЫЙ перечень файлов, которые гейт заблокировал.
    Без него одобрение владельца не значит ничего: `check_owner_gate._approved_scope`
    снимает нарушения только по scope из этого поля, и карточка без него, даже будучи
    `owner-done`, не разрешает НИ ОДНОГО файла. Две половины механизма (опечатка в
    имени параметра и разбор списка) починены 2026-08-08 по решению владельца
    (вариант А, `owner-decision-zapasnoi-klyuch-k-zaschite-saita-ne-rabo`) — но
    генератор карточек поле не писал, и обход всё равно оставался мёртвым.
    Scope берётся из САМИХ нарушений: одобряется ровно то, что владельцу показали,
    и ничего сверх. Нарушений нет ⇒ пустой scope ⇒ обхода нет (fail-CLOSED).
    """
    violations = report.get("violations", [])
    lines = [
        "## Что случилось и почему это важно",
        "Автономный оркестратор хотел изменить публичный сайт, но правка задевает "
        "owner-gated область (числа доходности / нейминг тиров / legal / solicitation). "
        "Такое не уезжает в live само — только с твоего одобрения (инвариант #8).",
        "",
        "## Что от тебя нужно",
        # Варианты — ПРОНУМЕРОВАННЫМ списком, а не прозой: карточка едет владельцу в
        # Телеграм кнопками (ADR-075), а разбор читает именно нумерованный перечень.
        # Проза «одобрить или отклонить» давала сообщение без единой кнопки — владелец
        # видел «открой её в трекере», чего из телефона не сделать (замер 08.08).
        "Посмотри изменение и выбери:",
        "",
        "1. **Одобрить** — правка уезжает в live как есть.",
        "2. **Отклонить (рекомендую)** — оркестратор не трогает эту область; "
        "owner-gated поверхность остаётся неизменной, пока ты не решишь иначе.",
        "3. **Отложить** — оставить карточку открытой и вернуться к ней позже.",
        "",
        "Что именно меняется:",
        f"- Файлы: {', '.join(_rel(f) for f in site_files)}",
        f"- Коммит-сообщение оркестратора: {message}",
        "- Что зафлагано owner-gate линтером:",
    ]
    for v in violations[:20]:
        lines.append(f"  - [{v.get('klass')}] {v.get('file')} · {v.get('rule')} · "
                     f"{v.get('matched_text', '')[:120]}")
    lines += [
        "",
        "## Как понять, что готово",
        "Ты нажал кнопку в Телеграме (или написал в карточке «одобряю» / «отклоняю»); "
        "при одобрении оркестратор запушит с трейлером `Owner-Approved: <id-карточки>`.",
        "",
        "## Что будет после",
        "Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор "
        "не трогает эту область.",
    ]
    body = "\n".join(lines)

    # ИДЕМПОТЕНТНОСТЬ. Оркестратор повторяет попытку пуша регулярно, и КАЖДЫЙ упор в
    # owner-gate заводил НОВУЮ карточку и слал НОВОЕ уведомление: замер 08.08 — три
    # одинаковых карточки за 40 минут и поток одинаковых сообщений владельцу.
    #
    # Отпечаток — набор нарушений (файл + правило). Тот же набор ⇒ карточка уже открыта,
    # молчим. ДРУГОЙ набор ⇒ это новое решение, заводим и говорим. Дедуп, а не подавление:
    # ни одна проверка не ослаблена, owner-gate по-прежнему НЕ пускает правку в live.
    fingerprint = _violations_fingerprint(violations)
    existing = _open_card_with_fingerprint(fingerprint)
    if existing is not None:
        print(f"safe_site_push: owner card already open for the same violations "
              f"({existing.name}) — not creating a duplicate, not notifying",
              file=sys.stderr)
        return
    # Персистентный дедуп ПОВЕРХ worktree-проверки выше: она видит только карточки
    # ЗАПУСКАЮЩЕГО дерева, а автономный оркестратор каждый цикл — в новом worktree,
    # где прежней карточки нет (спам владельцу, замер 21.08). Реестр в живом
    # data-каталоге переживает смену дерева и молчит про уже заданный вопрос.
    recently, last_at = _recently_notified(fingerprint)
    if recently:
        print(f"safe_site_push: owner already notified about these violations at "
              f"{last_at} (< {_RENOTIFY_COOLDOWN_H:g}h ago) — not re-notifying "
              f"(fingerprint {fingerprint})", file=sys.stderr)
        return
    lines.append("")
    lines.append(f"<!-- owner-gate-fingerprint: {fingerprint} -->")
    body = "\n".join(lines)

    # Scope одобрения = ровно те файлы, по которым гейт выдал нарушения (repo-relative).
    # Не список `--files`: там могут быть и чистые файлы, одобрять их незачем.
    approves = sorted({_rel(str(v.get("file", ""))) for v in violations if v.get("file")})
    try:
        from spa_core.owner_queue.queue import create_card  # type: ignore

        # create_card returns the full Path to the new card (queue.py). Pass the FULL
        # path to notify — a bare basename would not resolve against TRACKER_DIR and
        # load_card would FileNotFoundError, silently dropping the owner notification.
        card_path = create_card(
            tracker_type="owner-decision",
            title=_card_title(approves),
            body=body,
            source="orchestrator",
            # Запятая, а НЕ YAML-список: frontmatter-парсер очереди плоский и
            # `[a, b]` вернул бы строку со скобками, которая не совпадёт ни с одним
            # путём. `_parse_approves` штатно принимает форму через запятую.
            extra_fields={"approves": ", ".join(approves)} if approves else None,
        )
        print(f"safe_site_push: routed to owner card {card_path}", file=sys.stderr)
        try:
            subprocess.run(
                [sys.executable, str(_REPO_ROOT / "scripts" / "orchestrator_queue.py"),
                 "notify", str(card_path)],
                cwd=str(_REPO_ROOT), timeout=30,
            )
            # Отметить ТОЛЬКО после отправки: упавший create_card до этой точки не
            # доходит, и откат не начнётся с вопроса, которого владелец не видел.
            _record_notified(fingerprint)
        except Exception:
            pass
    except Exception as exc:
        print(f"safe_site_push: FAILED to create owner card ({exc}); NOT pushing.",
              file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Guarded site push (owner-gate + card routing).")
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--message", "-m", required=True)
    ap.add_argument("--repo")
    ap.add_argument("--branch", default="main")
    # Проброс осознанной перезаписи в batch-пушер. Owner-гейт проверяется РАНЬШЕ и этим
    # флагом не отменяется — он влияет только на страж расхождения с remote, то есть на
    # вопрос «не сотрём ли чужую правку», а не на вопрос «можно ли это публиковать».
    # Нужен ЦЕЛИКОМ ГЕНЕРИРУЕМЫМ артефактам (`track_snapshot.json`): их прошлое содержимое
    # на remote — не чужая правка, а предыдущее поколение того же генератора, и страж,
    # написанный для файлов, которые правят руками, иначе запирает доставку навсегда.
    ap.add_argument("--allow-overwrite", action="store_true",
                    help="ОСОЗНАННО перезаписать remote-версию (для целиком генерируемых артефактов)")
    args = ap.parse_args(argv)

    files = [str(Path(f)) for f in args.files]
    site_files = [f for f in files if "landing/" in f.replace("\\", "/")]

    if site_files:
        rc, report = _run_guard(site_files, args.message)
        if rc == 2:
            print("safe_site_push: GATED — owner-gated change, NOT pushing.", file=sys.stderr)
            _route_to_owner_card(site_files, report, args.message)
            return 2
        if rc != 0:
            print(f"safe_site_push: guard error (rc={rc}) — failing CLOSED, NOT pushing.",
                  file=sys.stderr)
            return 1

    # Clean (or no site files) → delegate to the batch push with the verified marker set.
    env = {**os.environ, "SPA_SITE_PUSH_VERIFIED": "1"}
    cmd = [sys.executable, str(_BATCH), "--files", *files, "--message", args.message]
    if args.repo:
        cmd += ["--repo", args.repo]
    cmd += ["--branch", args.branch]
    if args.allow_overwrite:
        cmd += ["--allow-overwrite"]
    rc = subprocess.run(cmd, cwd=str(_REPO_ROOT), env=env).returncode

    # ── ресит ДОСТАВКИ (ADR-066 B3) ─────────────────────────────────────────
    #
    # Сторож соответствия умеет спрашивать «продукт кто-то прочитал?», но для сайта
    # нужен другой вопрос — «продукт ДОШЁЛ до публики?». Разница не теоретическая:
    # 2026-08-06 снимок трека имел возраст 23ч при SLO 26ч, то есть выглядел
    # свежим по всем проверкам — и при этом НЕ БЫЛ доставлен, а сайт месяцами
    # показывал вчерашние числа. Проверка свежести измеряет момент СБОРКИ.
    #
    # Ресит пишется ТОЛЬКО при успешном пуше (rc == 0): иначе он превратится в
    # «доставлено» после неудачи, и сторож начнёт врать в самую опасную сторону —
    # успокаивать. Ошибка записи ресита не отменяет уже состоявшуюся доставку.
    if rc == 0:
        try:
            from spa_core.monitoring.consumption_receipts import write_receipt
            for f in files:
                rel = os.path.relpath(os.path.abspath(f), str(_REPO_ROOT))
                if rel.startswith("landing/"):
                    write_receipt(rel, "site_delivery", root=str(_REPO_ROOT))
        except Exception as exc:  # noqa: BLE001 — учёт не важнее доставки
            print(f"  (ресит доставки не записан: {exc})")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
