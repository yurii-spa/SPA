#!/usr/bin/env python3
"""owner_answer_delivery.py — довезти СЛЕД решения владельца до `origin/main`.

**Что закрывает.** Цикл #246 закрыл ВИДИМОСТЬ ответа владельца: шаг 2 протокола
опрашивает главное дерево и показывает найденное из любого worktree
(`owner_queue/owner_answer.py::scan_owner_answers_elsewhere`). Доставка — другое
утверждение, и она оставалась открытой (карточка
`inbox-u-otveta-vladeltsa-net-svoego-puti-na-or`, осадок #246):

* владелец жмёт кнопку в Телеграме → бот вызывает ``record_owner_answer`` и пишет
  ``owner_choice`` / ``owner_answered_at`` / ``owner_answer_via`` /
  ``owner_answered_by`` в ПРОД-дерево — единственное, которое он знает;
* на `origin` этот след не уезжает ничем: мост доставки карточек (ADR-081) везёт
  только то, что создал или закрыл сам за прогон, а ответа владельца он не создавал;
* пока Мак жив и дерево цело — незаметно. Дерево потеряно ⇒ **решение владельца
  потеряно вместе с ним**, и в git его не было ни минуты.

**Замер 2026-08-15 (цикл #247), прод-дерево против `origin/main` 263adb4f6:**
след ответа владельца несут **9** карточек, у **2** его на origin НЕТ ВОВСЕ —
``own-rnd-duty-is-concentration-adr055`` (вариант A, 2026-08-08T18:33:12Z) и
``owner-decision-morfo-40-knigi-pri-propazhe-dannyh-podst`` (вариант 1,
2026-08-08T21:11:37Z). Это ровно те две карточки, на которых дефект был назван
ещё в #178 — неделю спустя они по-прежнему вне git.

Почему это НЕ делается доставкой файла целиком
------------------------------------------------------------------------------
Первое, что приходит в голову, — отдать обе карточки в `card_delivery.deliver`.
Так делать нельзя, и измерение говорит почему: **на origin у обеих ТЕЛО БОГАЧЕ**.
Инжестирующая сессия переписала раздел ответа своей прозой (разбор, уточняющие
замеры, ссылки на ADR), а в прод-копии стоит сырой блок, который написал бот.
Пуш нашей копии стёр бы работу сессии — доставка обязана НЕ ТЕРЯТЬ, а мы бы
потеряли, просто в другую сторону.

Отсюда граница модуля: **везём СЛЕД, а не карточку.** След — четыре строки
frontmatter, машинно проверяемый ответ на вопрос «что именно выбрал владелец и
когда». Проза живёт там, где её написали.

Что именно доказывается перед пушем
------------------------------------------------------------------------------
Содержимое строится ИЗ СВЕЖЕГО remote (а не из нашей копии) и обязано отличаться
от него **только добавленными строками frontmatter с ключами из
`OWNER_ANSWER_FIELDS`**. Доказательство независимое (:func:`verify_trace_only`),
а не «доверьтесь конструктору»: кандидат разбирается заново и сверяется с remote
построчно. Не сошлось — ОТКАЗ по этой карточке с названной причиной.

Следствия, каждое против конкретного отказа:

``тело не трогаем``     байт в байт как на origin. Проза сессии не может быть
                        потеряна нашей слепой копией — её просто нечем задеть;
``status: не трогаем``  наша копия бывает СТАРШЕ origin (ответ разбирают в
                        worktree и пушат оттуда ``ingested``, а прод-копия
                        остаётся ``owner-done``) — перенос статуса откатил бы
                        очередь назад. И отдельно: инвариант #14 запрещает
                        агенту ставить ``owner-done``, и здесь он не обойдён
                        даже формально — эта строка не пишется вовсе;
``чужой ответ``         на origin то же поле с ДРУГИМ значением = два разных
                        ответа владельца. Выбирать сторону молча запрещено
                        (тот же класс, что ``owner_answer.AnswerConflict``) — отказ;
``только карточки``     путь вне `nimbalyst-local/tracker/*.md` не везётся
                        никогда, `_BOARD.md` — тем более (общая память).

Почему у сторожа нет ДОЛГА (ADR-081) — и это не упущение
------------------------------------------------------------------------------
Долг доставки понадобился мосту потому, что его список строится из тронутого ЗА
ПРОГОН: провалившаяся карточка в следующий список не попадёт никогда, и провал
сам себя заметал. Здесь список строится ЗАНОВО каждый прогон — из файлов на
диске и версий на origin. Не доехало ⇒ на следующем прогоне находка та же и
поедет снова. Повтор — свойство устройства, а не отдельный механизм.

Почему пуш собирается примитивами пушера, а не его CLI
------------------------------------------------------------------------------
CLI пушера отправляет БАЙТЫ ФАЙЛА С ДИСКА, а мы отправляем «свежий remote + наш
след», которого на диске нет ни в одном дереве (ровно та же причина, по которой
у пушера есть :func:`create_blob_from_bytes` — им пользуется его собственная
пере-база дописывания). Цепочка blob → tree → commit → ref берётся у пушера
целиком, вместе с его сверками на каждом звене; родитель коммита — та база, с
которой мы читали, поэтому чужой пуш в окне между чтением и записью получает
отказ от самого GitHub (не-fast-forward), а не тихую перезапись.

Owner-gate не обойдён: единственный разрешённый префикс путей —
`nimbalyst-local/tracker/`, `landing/**` этот модуль не умеет отправить в
принципе (проверка до, а не после).

Квитанция: `data/owner_answer_delivery_status.json` (атомарно) + блок
``owner_answer_delivery`` в `data/findings_bridge_report.json` — его печатает
обязательный шаг 0-офис, поэтому исход попадает В КОНТЕКСТ сессии, а не в файл,
который никто не обязан открыть.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT
from spa_core.monitoring.card_delivery import (
    NEVER_DELIVER,
    REMOTE_ABSENT,
    REMOTE_PRESENT,
    REMOTE_UNMEASURED,
    TRACKER_REL,
    _default_remote_reader,
    card_parts,
)
from spa_core.owner_queue.owner_answer import OWNER_ANSWER_FIELDS

STATUS_REL = os.path.join("data", "owner_answer_delivery_status.json")
PUSHER_REL = "push_to_github.py"

#: Выключатель владельца — одна команда, без правки кода.
ENV_FLAG = "SPA_OWNER_ANSWER_DELIVERY"

DELIVERED = "DELIVERED"
IDLE = "IDLE"
REFUSED = "REFUSED"
FAILED = "FAILED"
UNCHECKED = "UNCHECKED"
DISABLED = "DISABLED"
PARTIAL = "PARTIAL"

#: Исходы, которые НЕ означают «след на origin».
NOT_DELIVERED = (REFUSED, FAILED, UNCHECKED, DISABLED, PARTIAL)

# Вердикты по одной карточке.
NEEDS_TRACE = "needs_trace"            # след есть у нас, на origin его нет
ALREADY_ON_ORIGIN = "already_on_origin"
CREATE_ON_ORIGIN = "absent_on_origin"  # карточки на origin нет вовсе
CONFLICT = "conflict"                  # origin несёт ДРУГОЙ ответ владельца
UNMEASURED = "unmeasured"              # origin прочитать не удалось


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return now or dt.datetime.now(dt.timezone.utc)


def is_enabled(env=None) -> bool:
    """По умолчанию сторож ВКЛЮЧЁН."""
    env = os.environ if env is None else env
    return str(env.get(ENV_FLAG, "1")).strip().lower() not in ("0", "off", "false", "no")


# ── разбор следа во frontmatter (байты, без промежуточных представлений) ──────

def _field_re(key: str):
    """Верхнеуровневое поле frontmatter: без отступа (вложенное ``type:`` — не оно)."""
    return re.compile(rb"(?m)^" + re.escape(key.encode()) + rb":[ \t]*(.*)$")


def trace_fields(blob: bytes) -> dict:
    """Поля следа ответа владельца из БАЙТОВ карточки (пусто — следа нет).

    Отдельно от ``owner_answer.read_answer_fields`` только формой входа (байты
    против текста): имена полей берутся из одного списка ``OWNER_ANSWER_FIELDS``,
    второй копии имён здесь нет.
    """
    parts = card_parts(blob)
    if parts is None:
        return {}
    fm = parts[0]
    out: dict = {}
    for key in OWNER_ANSWER_FIELDS:
        m = _field_re(key).search(fm)
        if m is None:
            continue
        value = m.group(1).strip().decode("utf-8", "replace")
        if value:
            out[key] = value
    return out


def merge_trace(local: bytes, remote: bytes) -> tuple:
    """``(bytes|None, причина, добавленные_поля)`` — remote плюс НАШ след.

    Строим из remote: тело и все прочие строки frontmatter остаются его. Наши —
    только недостающие строки следа. Каждый отказ называет свою причину:
    «сделали не то» и «мы ослепли» — разные аварии.
    """
    lp, rp = card_parts(local), card_parts(remote)
    if lp is None:
        return None, "наша копия не карточка (нет frontmatter) — переносить нечего", {}
    if rp is None:
        return None, "версия на origin не карточка (нет frontmatter) — сравнивать не с чем", {}

    mine = trace_fields(local)
    if not mine:
        return None, "в нашей копии нет следа ответа владельца — переносить нечего", {}
    theirs = trace_fields(remote)

    clash = {k: (theirs[k], mine[k]) for k in mine if k in theirs and theirs[k] != mine[k]}
    if clash:
        named = "; ".join(f"{k}: на origin {o!r}, у нас {m!r}" for k, (o, m) in sorted(clash.items()))
        return None, (f"на origin ДРУГОЙ ответ владельца ({named}) — две копии несут разные "
                      f"решения, выбирать сторону молча нельзя; сверьте руками"), {}

    added = {k: v for k, v in mine.items() if k not in theirs}
    if not added:
        return None, "след уже на origin — везти нечего", {}

    r_fm, r_body = rp
    # Дописываем в КОНЕЦ frontmatter в стабильном порядке OWNER_ANSWER_FIELDS —
    # словарный порядок сделал бы содержимое коммита зависящим от порядка чтения.
    lines = b"".join(f"{k}: {added[k]}\n".encode()
                     for k in OWNER_ANSWER_FIELDS if k in added)
    candidate = remote[:4] + r_fm + lines + b"---\n" + r_body

    ok, why = verify_trace_only(remote, candidate)
    if not ok:
        return None, f"перенос не доказан: {why}", {}
    return candidate, "", added


def verify_trace_only(remote: bytes, candidate: bytes) -> tuple:
    """``(bool, причина)`` — кандидат отличается от remote ТОЛЬКО следом.

    Независимая проверка: кандидат разбирается заново, как будто его прислал
    кто-то другой. Смысл именно в независимости — конструктор, проверяющий сам
    себя, повторяет свою же ошибку, а этот проект на таком уже горел.
    """
    rp, cp = card_parts(remote), card_parts(candidate)
    if rp is None or cp is None:
        return False, "одна из версий не карточка"
    r_fm, r_body = rp
    c_fm, c_body = cp
    if c_body != r_body:
        return False, "тело отличается от origin — модуль не смеет трогать тело карточки"

    r_lines, c_lines = r_fm.splitlines(True), c_fm.splitlines(True)
    allowed = {k.encode() for k in OWNER_ANSWER_FIELDS}
    extra: list = []
    i = 0
    for line in c_lines:
        if i < len(r_lines) and line == r_lines[i]:
            i += 1
            continue
        extra.append(line)
    if i != len(r_lines):
        return False, "строки frontmatter с origin изменены или пропали — допускается только добавление"
    for line in extra:
        key = line.split(b":", 1)[0]
        if line[:1].isspace() or key not in allowed:
            return False, (f"добавлена строка не из следа ответа владельца: "
                           f"{line.decode('utf-8', 'replace').strip()!r}")
    if not extra:
        return False, "кандидат ничем не отличается от origin — везти нечего"
    return True, ""


# ── что именно недоставлено ──────────────────────────────────────────────────

def _tracker_dir(root: str) -> str:
    return os.path.join(root, TRACKER_REL)


def scan(root: str = REPO_ROOT, reader=_default_remote_reader) -> list:
    """Карточки дерева ``root``, чей след ответа владельца на origin не полон.

    Список строится ЗАНОВО каждый прогон — отсюда повтор без отдельного долга.
    Ни одна карточка со следом не исчезает молча: она попадает ровно в один
    вердикт, включая ``unmeasured``.
    """
    out: list = []
    tracker = _tracker_dir(root)
    try:
        names = sorted(n for n in os.listdir(tracker) if n.endswith(".md"))
    except OSError as e:  # noqa: BLE001 — каталога нет: это не «карточек нет»
        return [{"card": None, "verdict": UNMEASURED,
                 "reason": f"каталог трекера нечитаем: {type(e).__name__}: {e}"}]

    for name in names:
        if name in NEVER_DELIVER:
            continue
        absolute = os.path.join(tracker, name)
        try:
            with open(absolute, "rb") as f:
                local = f.read()
        except OSError as e:  # noqa: BLE001 — был ли там след, ТЕПЕРЬ уже не узнать
            out.append({"card": name, "verdict": UNMEASURED,
                        "reason": f"карточка не прочитана: {type(e).__name__}: {e}"})
            continue
        mine = trace_fields(local)
        if not mine:
            continue  # следа ответа нет — это не наша карточка

        repo_path = f"{TRACKER_REL}/{name}".replace(os.sep, "/")
        state, remote, why = reader(root, repo_path)
        if state == REMOTE_ABSENT:
            out.append({"card": name, "path": absolute, "repo_path": repo_path,
                        "verdict": CREATE_ON_ORIGIN, "answer": mine,
                        "content": local,
                        "reason": "карточки на origin нет вовсе — везём как создание"})
            continue
        if state != REMOTE_PRESENT or remote is None:
            out.append({"card": name, "path": absolute, "repo_path": repo_path,
                        "verdict": UNMEASURED, "answer": mine,
                        "reason": why or "версию на origin прочитать не удалось"})
            continue

        merged, reason, added = merge_trace(local, remote)
        if merged is None:
            verdict = ALREADY_ON_ORIGIN if "след уже на origin" in reason else (
                CONFLICT if "ДРУГОЙ ответ владельца" in reason else REFUSED)
            out.append({"card": name, "path": absolute, "repo_path": repo_path,
                        "verdict": verdict, "answer": mine, "reason": reason})
            continue
        out.append({"card": name, "path": absolute, "repo_path": repo_path,
                    "verdict": NEEDS_TRACE, "answer": mine, "added": added,
                    "content": merged,
                    "reason": f"на origin нет полей: {', '.join(sorted(added))}"})
    return out


# ── отправка ─────────────────────────────────────────────────────────────────

def build_message(items: list) -> str:
    names = [i["card"] for i in items]
    head = ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")
    return (f"owner-answer: след решения владельца → origin ({len(names)}): {head} — "
            f"ответ жил только в прод-дереве, в git его не было; везётся ТОЛЬКО след "
            f"(поля frontmatter), тело и status: origin не трогаются")


def _load_pusher_module(root: str):
    import importlib.util
    path = os.path.join(root, PUSHER_REL)
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("_spa_pusher_for_answer_delivery", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _default_pusher(root: str, items: list, message: str) -> tuple:
    """``(ok, подробность)`` — один коммит из построенного содержимого.

    Цепочка и её сверки — пушера (`create_blob_from_bytes` сверяет sha blob'а,
    `update_ref` сверяет, что ветка встала на НАШ коммит). Родитель — база,
    прочитанная в этом же прогоне: чужой пуш в окне даст отказ GitHub, а не
    тихую перезапись.
    """
    # Owner-gate ПЕРВЫМ, до загрузки пушера: отказ обязан наступать раньше, чем
    # модуль вообще получит в руки инструмент доставки и PAT. Порядок здесь —
    # часть проверки, а не стиль: пушер, которого нет, погасил бы её собой.
    prefix = f"{TRACKER_REL}/".replace(os.sep, "/")
    for item in items:
        if not str(item.get("repo_path", "")).startswith(prefix):
            return False, f"путь вне трекера — не отправляю: {item.get('repo_path')}"
    mod = _load_pusher_module(root)
    if mod is None:
        return False, f"инструмента доставки нет: {PUSHER_REL}"
    try:
        pat = mod.get_pat()
        base_sha, base_tree = mod.get_base_ref(pat, mod.REPO, "main")
        entries = []
        for item in items:
            blob = mod.create_blob_from_bytes(pat, mod.REPO, item["content"])
            entries.append({"path": item["repo_path"], "mode": "100644",
                            "type": "blob", "sha": blob})
        tree = mod.create_tree(pat, mod.REPO, base_tree, entries)
        commit = mod.create_commit(pat, mod.REPO, message, tree, base_sha)
        mod.update_ref(pat, mod.REPO, "main", commit)
        return True, commit[:8]
    except Exception as e:  # noqa: BLE001 — отказ НАЗЫВАЕТСЯ, а не роняет сторожа
        return False, f"{type(e).__name__}: {e}"


def run(root: str = REPO_ROOT, now: dt.datetime | None = None,
        reader=_default_remote_reader, pusher=_default_pusher, env=None,
        write_status: bool = True, dry_run: bool = False) -> dict:
    """Найти недоставленный след решения владельца и довезти его. Квитанция.

    Исключений НЕ бросает: сторож не смеет уронить того, кто его позвал. Но и не
    молчит — любой исход попадает в ``status``.
    """
    ts = _now(now)
    receipt = {"generated_at": ts.isoformat(), "adr": "ADR-086",
               "scanned": 0, "delivered": [], "already_on_origin": [],
               "refused": [], "unmeasured": [], "conflicts": [],
               "status": UNCHECKED, "reason": "", "commit": None}
    try:
        findings = scan(root, reader=reader)
        receipt["scanned"] = len(findings)
        by = {}
        for f in findings:
            by.setdefault(f["verdict"], []).append(f)

        receipt["already_on_origin"] = sorted(f["card"] for f in by.get(ALREADY_ON_ORIGIN, []))
        receipt["unmeasured"] = [{"card": f.get("card"), "reason": f.get("reason")}
                                 for f in by.get(UNMEASURED, [])]
        receipt["conflicts"] = [{"card": f["card"], "reason": f["reason"]}
                                for f in by.get(CONFLICT, [])]
        receipt["refused"] = [{"card": f["card"], "reason": f["reason"]}
                              for f in by.get(REFUSED, [])]

        todo = by.get(NEEDS_TRACE, []) + by.get(CREATE_ON_ORIGIN, [])
        blocked = receipt["conflicts"] + receipt["refused"] + receipt["unmeasured"]
        receipt["pending"] = [{"card": f["card"], "answer": f["answer"],
                               "added": sorted(f.get("added") or {}),
                               "verdict": f["verdict"]} for f in todo]

        if not is_enabled(env):
            receipt["status"] = DISABLED
            receipt["reason"] = (f"сторож выключен переменной {ENV_FLAG}; "
                                 f"недоставленного следа: {len(todo)}")
        elif not todo:
            if blocked:
                receipt["status"] = REFUSED
                receipt["reason"] = ("везти нечего, но НЕ ИЗМЕРЕНО/ОТКАЗАНО по "
                                     f"{len(blocked)} карточк(ам): "
                                     + "; ".join(f"{b['card']}: {b['reason']}" for b in blocked))
            else:
                receipt["status"] = IDLE
                receipt["reason"] = (f"весь след решений владельца на origin "
                                     f"({len(receipt['already_on_origin'])} карточк(и))")
        elif dry_run:
            receipt["status"] = UNCHECKED
            receipt["reason"] = (f"сухой прогон: доставить нужно {len(todo)} карточк(и) — "
                                 + ", ".join(f["card"] for f in todo))
        else:
            msg = build_message(todo)
            receipt["message"] = msg
            ok, detail = pusher(root, todo, msg)
            if ok and not blocked:
                receipt["status"] = DELIVERED
                receipt["commit"] = detail
                receipt["delivered"] = [f["card"] for f in todo]
                receipt["reason"] = f"след решения владельца на origin, коммит {detail}"
            elif ok:
                receipt["status"] = PARTIAL
                receipt["commit"] = detail
                receipt["delivered"] = [f["card"] for f in todo]
                receipt["reason"] = (f"уехало {len(todo)}, но по {len(blocked)} карточк(ам) "
                                     f"измерить/перенести не удалось: "
                                     + "; ".join(f"{b['card']}: {b['reason']}" for b in blocked))
            else:
                receipt["status"] = FAILED
                receipt["reason"] = f"доставка не удалась: {detail}"
    except Exception as e:  # noqa: BLE001 — «не измерено» честнее, чем падение сторожа
        receipt["status"] = UNCHECKED
        receipt["reason"] = f"сторож не измерен: {type(e).__name__}: {e}"

    if write_status:
        try:
            from spa_core.utils.atomic import atomic_save
            target = os.path.join(root, STATUS_REL)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            atomic_save(receipt, target)
        except Exception as e:  # noqa: BLE001 — квитанция не смеет уронить сторожа
            receipt["receipt_write_error"] = f"{type(e).__name__}: {e}"
    return receipt


def render(receipt: dict) -> str:
    """Одна строка для лога/шага 0-офис. Отказ виден без чтения JSON."""
    if not isinstance(receipt, dict) or not receipt:
        return "owner_answer_delivery: ⚠️ НЕ ИЗМЕРЕНО — квитанции нет"
    st = receipt.get("status")
    n_ok = len(receipt.get("already_on_origin") or [])
    pending = receipt.get("pending") or []
    tail = ""
    if receipt.get("unmeasured"):
        tail += f" · НЕ ИЗМЕРЕНО: {len(receipt['unmeasured'])}"
    if receipt.get("conflicts"):
        tail += f" · РАЗНЫЕ ОТВЕТЫ: {len(receipt['conflicts'])}"
    if st == DELIVERED:
        return (f"owner_answer_delivery: ✅ след решения владельца доставлен "
                f"({len(receipt.get('delivered') or [])}) → origin/main{tail}")
    if st == IDLE:
        return f"owner_answer_delivery: — весь след на origin ({n_ok} карточк(и)){tail}"
    return (f"owner_answer_delivery: ⚠️ {st} (недоставлено {len(pending)}){tail} — "
            f"{receipt.get('reason', '')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--dry-run", action="store_true",
                    help="только измерить, ничего не отправлять")
    ap.add_argument("--show", action="store_true", help="показать последнюю квитанцию")
    ap.add_argument("--json", action="store_true", help="квитанция целиком в stdout")
    args = ap.parse_args(argv)

    if args.show:
        try:
            with open(os.path.join(args.root, STATUS_REL), encoding="utf-8") as f:
                print(json.dumps(json.load(f), ensure_ascii=False, indent=2))
            return 0
        except OSError as e:  # noqa: BLE001
            print(f"квитанции нет: {e}")
            return 2

    r = run(root=args.root, dry_run=args.dry_run, write_status=not args.dry_run)
    if args.json:
        print(json.dumps({k: v for k, v in r.items() if k != "content"},
                         ensure_ascii=False, indent=2, default=str))
    print(render(r))
    return 0 if r["status"] in (DELIVERED, IDLE) else 1


if __name__ == "__main__":
    sys.exit(main())
