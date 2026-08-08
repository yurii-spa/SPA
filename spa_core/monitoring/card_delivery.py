"""card_delivery.py — доставка карточек, рождённых В РАНТАЙМЕ, до `origin/main`.

**Зачем.** Мост находок ADR-066 (`findings_bridge.py`) заводит карточку в том
дереве, из которого запущен, — то есть в прод-дереве `~/Documents/SPA_Claude`.
Пуша в мосте нет ни одной строкой, а доставка в это дерево не заглядывает
никогда: пуши идут ПРЯМО на origin, хост-копия дрейфует по построению.

Замер 2026-08-08 (цикл #170), карточка
`inbox-kartochki-mosta-nahodok-rozhdayutsya-v-p`:

* карточек с `finding_key:` в прод-дереве — **11**, на `origin/main` — **7**;
* но все семь приземлились ровно потому, что родились 06.08 в worktree
  разработчика фаз ADR-066 и уехали его же пушем (`git log --diff-filter=A`:
  коммиты «ADR-066 Фаза 1/3/4»);
* из рождённых **в рантайме** агентом `com.spa.decision_loop` доставлено
  **0 из 4** — все четыре `needs-owner`, то есть по протоколу ждут владельца.

Карточка `needs-owner`, которой нет на origin, для очереди владельца НЕ
СУЩЕСТВУЕТ (`CLAUDE.md` инв. 13 «источник правды — файлы в git»;
`orchestrator_queue.py list` сверяется с `origin/main` с цикла #147). При этом
Telegram-уведомление мост шлёт — владелец получает тревогу, за которой нет
ничего. Это класс fail-OPEN: инструмент честно сделал свою часть и промолчал о
том, что последний метр не пройден.

**Дисциплина (каждое правило — против конкретного отказа):**

``только карточки``   везём ТОЛЬКО файлы из `nimbalyst-local/tracker/*.md`.
                      Путь вне каталога — отказ ВСЕЙ пачки, а не тихое
                      выбрасывание лишнего (правило «no silent caps»);
``_BOARD.md никогда`` доска — общая память (`push_to_github.SHARED_MEMORY_DOCS`),
                      и из прод-дерева базу пуша установить нечем ⇒ пушер
                      отказывает fail-CLOSED (ADR-070 п.7) и уронил бы всю
                      пачку. Доска регенерится у любой сессии, карточка — нет;
``одна пачка``        все карточки прогона уходят ОДНИМ атомарным коммитом
                      (урок #53: набор файлов пофайлово = N коммитов, любой
                      промежуточный `main` мог быть красным);
``fail-CLOSED``       «не измерено» ≠ «доставлено»: сбой пушера → ``FAILED``,
                      исключение/таймаут → ``UNCHECKED``, выключено флагом →
                      ``DISABLED``. Ни один из этих исходов не молчит и ни один
                      не выглядит успехом; пустой список → ``IDLE``, а не «OK».

Квитанция: `data/card_delivery_status.json` (атомарно) + блок ``delivery`` в
`data/findings_bridge_report.json` — его читает обязательный шаг 0-офис
оркестратора (`scripts/consume_office_reports.py`), поэтому сбой доставки
попадает В КОНТЕКСТ сессии, а не в файл, который никто не обязан открыть.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT

STATUS_REL = os.path.join("data", "card_delivery_status.json")
TRACKER_REL = os.path.join("nimbalyst-local", "tracker")
PUSHER_REL = "push_to_github.py"
PUSH_TIMEOUT = 300

#: Имена, которые доставка не везёт даже если её попросили прямо.
NEVER_DELIVER = ("_BOARD.md",)

#: Переменная окружения-выключатель (владельцу — одна команда, без правки кода).
ENV_FLAG = "SPA_CARD_DELIVERY"

DELIVERED = "DELIVERED"
FAILED = "FAILED"
REFUSED = "REFUSED"
UNCHECKED = "UNCHECKED"
DISABLED = "DISABLED"
IDLE = "IDLE"

#: Исходы, которые НЕ означают «карточки на origin». Читателю квитанции не надо
#: помнить список статусов, чтобы не принять отказ за успех.
NOT_DELIVERED = (FAILED, REFUSED, UNCHECKED, DISABLED)


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return now or dt.datetime.now(dt.timezone.utc)


def _rel(root: str, path: str) -> str:
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except Exception:  # noqa: BLE001 — путь на другом томе: показать как есть
        return path


def is_enabled(env=None) -> bool:
    """Выключатель владельца. По умолчанию доставка ВКЛЮЧЕНА."""
    env = os.environ if env is None else env
    return str(env.get(ENV_FLAG, "1")).strip().lower() not in ("0", "off", "false", "no")


def validate(paths, root: str = REPO_ROOT) -> tuple[list, list]:
    """``(годные абсолютные пути, [{path, reason} …])`` — порядок сохранён, дубли сняты.

    Отказ НАЗЫВАЕТСЯ по каждому пути отдельно: «не доставили» без причины —
    ровно та фигура, из-за которой карточки терялись молча.
    """
    tracker = os.path.realpath(os.path.join(root, TRACKER_REL))
    ok: list[str] = []
    bad: list[dict] = []
    seen: set[str] = set()
    for p in paths or []:
        if not p:
            continue
        absolute = os.path.realpath(os.path.join(root, str(p)))
        if absolute in seen:
            continue
        seen.add(absolute)
        parent = os.path.dirname(absolute)
        name = os.path.basename(absolute)
        if parent != tracker:
            bad.append({"path": _rel(root, absolute),
                        "reason": f"путь вне {TRACKER_REL} — доставка возит только карточки"})
        elif not name.endswith(".md"):
            bad.append({"path": _rel(root, absolute), "reason": "не .md — это не карточка"})
        elif name in NEVER_DELIVER:
            bad.append({"path": _rel(root, absolute),
                        "reason": ("общая память (push_to_github.SHARED_MEMORY_DOCS): база пуша "
                                   "из прод-дерева неизмерима ⇒ пушер отказал бы fail-CLOSED "
                                   "и уронил всю пачку; доска регенерится у любой сессии")})
        elif not os.path.isfile(absolute):
            bad.append({"path": _rel(root, absolute), "reason": "файла нет на диске"})
        else:
            ok.append(absolute)
    return ok, bad


def build_message(root: str, paths: list) -> str:
    names = [os.path.basename(p) for p in paths]
    head = ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")
    return (f"cards(ADR-066): доставка карточек петли ({len(names)}): {head} — "
            f"рождены агентом в прод-дереве, куда доставка не заглядывает; "
            f"одной пачкой, одним коммитом")


def _default_pusher(root: str, paths: list, message: str) -> tuple:
    """``(returncode, вывод)``. Единственное место, где доставка ходит наружу."""
    pusher = os.path.join(root, PUSHER_REL)
    if not os.path.isfile(pusher):
        return None, f"инструмента доставки нет: {pusher}"
    r = subprocess.run([sys.executable, pusher, "--files", *paths, "--message", message],
                       capture_output=True, text=True, timeout=PUSH_TIMEOUT, cwd=root)
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))


def _tail(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def deliver(paths, root: str = REPO_ROOT, now: dt.datetime | None = None,
            pusher=_default_pusher, env=None, write_status: bool = True,
            message: str | None = None) -> dict:
    """Довезти карточки до `origin/main`. Возвращает квитанцию (и пишет её на диск).

    Исключений НЕ бросает: доставка не смеет уронить сторожа, который её позвал.
    Но и не смеет промолчать — любой исход попадает в ``status``.
    """
    ts = _now(now)
    receipt = {"generated_at": ts.isoformat(), "adr": "ADR-066",
               "attempted": [], "delivered": [], "refused": [],
               "status": UNCHECKED, "reason": "", "returncode": None, "output": ""}
    try:
        ok, bad = validate(paths, root)
        receipt["attempted"] = [_rel(root, p) for p in ok]
        receipt["refused"] = bad
        if bad:
            receipt["status"] = REFUSED
            receipt["reason"] = ("пачка отклонена целиком — недопустимые пути: "
                                 + "; ".join(f"{b['path']}: {b['reason']}" for b in bad))
        elif not ok:
            receipt["status"] = IDLE
            receipt["reason"] = "доставлять нечего — карточек за прогон не создано и не закрыто"
        elif not is_enabled(env):
            receipt["status"] = DISABLED
            receipt["reason"] = (f"доставка выключена переменной {ENV_FLAG}; карточки остались "
                                 f"в рабочем дереве и на origin НЕ попали")
        else:
            msg = message or build_message(root, ok)
            receipt["message"] = msg
            rc, out = pusher(root, ok, msg)
            receipt["returncode"] = rc
            receipt["output"] = _tail(out)
            if rc == 0:
                receipt["status"] = DELIVERED
                receipt["delivered"] = [_rel(root, p) for p in ok]
                receipt["reason"] = "пушер вернул 0 — карточки на origin"
            elif rc is None:
                receipt["status"] = UNCHECKED
                receipt["reason"] = f"доставка не запускалась: {_tail(out, 300)}"
            else:
                receipt["status"] = FAILED
                receipt["reason"] = f"пушер вернул {rc} — карточки на origin НЕ попали"
    except Exception as e:  # noqa: BLE001 — «не измерено» честнее, чем падение сторожа
        receipt["status"] = UNCHECKED
        receipt["reason"] = f"доставка не измерена: {type(e).__name__}: {e}"

    if write_status:
        try:
            from spa_core.utils.atomic import atomic_save
            target = os.path.join(root, STATUS_REL)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            atomic_save(receipt, target)
        except Exception as e:  # noqa: BLE001 — квитанция не смеет уронить доставку
            receipt["receipt_write_error"] = f"{type(e).__name__}: {e}"
    return receipt


def render(receipt: dict) -> str:
    """Одна строка для лога/отчёта. Отказ виден без чтения JSON."""
    st = receipt.get("status")
    n_try = len(receipt.get("attempted") or [])
    if st == DELIVERED:
        return f"card_delivery: ✅ DELIVERED {n_try} карточк(и) → origin/main"
    if st == IDLE:
        return "card_delivery: — доставлять нечего"
    return (f"card_delivery: ⚠️ {st} (пыталось {n_try}) — {receipt.get('reason', '')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help="карточки nimbalyst-local/tracker/*.md")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--show", action="store_true", help="показать последнюю квитанцию")
    args = ap.parse_args(argv)
    if args.show:
        try:
            print(json.dumps(json.load(open(os.path.join(args.root, STATUS_REL))),
                             ensure_ascii=False, indent=2))
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"квитанции нет: {e}")
            return 2
    if not args.paths:
        ap.print_help()
        return 0
    r = deliver(args.paths, root=args.root)
    print(render(r))
    return 0 if r["status"] in (DELIVERED, IDLE) else 1


if __name__ == "__main__":
    sys.exit(main())
