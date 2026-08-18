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


def _already_asked_in_shared_journal(title: str):
    """Открытый (неотвеченный) пуш с ТЕМ ЖЕ заголовком в ОБЩЕМ журнале отправок.

    Возвращает путь к карточке из журнала либо ``None``. Никогда не бросает: как и у
    соседней проверки по трекеру, сомнение ⇒ ``None`` ⇒ карточка создаётся. Потерять
    вопрос владельца хуже, чем задать его дважды, — но задавать его двести раз в сутки
    хуже, чем оба варианта.

    Заголовок, а не отпечаток нарушений: отпечаток живёт в ТЕЛЕ карточки, а журнал тела
    не хранит. Заголовок же строится детерминированно из того же набора файлов
    (:func:`_card_title`), поэтому «тот же вопрос» опознаётся без чтения чужого дерева.
    """
    # Под pytest журнал отправок — ОДИН общий временный файл на все прогоны
    # (`owner_decisions._state_path`), и записи из соседнего теста читались бы как
    # «вопрос уже задан». Замер: первая версия этой проверки покрасила восемь чужих
    # тестов `test_owner_gate_approval_scope`, потому что мои же тесты выше оставили в
    # том файле запись с тем же заголовком. Молчаливая зависимость от чужого теста —
    # ровно то, что здесь запрещено, поэтому проверка под pytest выключена, пока её не
    # включат явно (тот же признак, которым модуль уводит собственное состояние).
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
        "SPA_OWNER_DECISIONS_TEST"
    ):
        return None
    try:
        from spa_core.telegram.owner_decisions import open_pushes  # type: ignore

        for rec in open_pushes():
            if (rec.get("title") or "") == title:
                card = rec.get("card")
                return Path(card) if card else None
    except Exception:  # noqa: BLE001
        return None
    return None


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
    if existing is None:
        # ВТОРОЙ ВОПРОС, НА КОТОРЫЙ ПЕРВЫЙ НЕ ОТВЕЧАЕТ (жалоба владельца 17.08: «пишут
        # раз по 200 в день одно и то же»). Проверка выше смотрит в трекер СВОЕГО дерева
        # (`queue.TRACKER_DIR` считается от `__file__`), а оркестратор и сессии работают
        # из worktree — и `nimbalyst-local/` между деревьями НЕ синкается (урок #193,
        # замер #270: 109 карточек невидимы прод-дереву). Значит в чужом дереве карточка
        # «уже открыта» не находится НИКОГДА, и каждый прогон заводил новую и слал новое
        # уведомление.
        #
        # Журнал отправок при этом ОБЩИЙ по построению: `owner_decisions.STATE_PATH`
        # живёт в живом `data/`, потому что нажимать будет бот из прода, а слать может
        # сессия из worktree. Спрашиваем его — тем же вопросом, что и выше: этот вопрос
        # владельцу уже задан и ещё не отвечен?
        existing = _already_asked_in_shared_journal(_card_title(
            sorted({_rel(str(v.get("file", ""))) for v in violations if v.get("file")})))
    if existing is not None:
        print(f"safe_site_push: owner card already open for the same violations "
              f"({existing.name}) — not creating a duplicate, not notifying",
              file=sys.stderr)
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
