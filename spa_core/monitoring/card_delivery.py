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

**Обновление карточки — отдельная задача от её рождения (замер 2026-08-12, цикл
#200).** Доставка умела только СОЗДАВАТЬ. Пушер сравнивает нашу версию с базой
РАБОЧЕЙ КОПИИ (``HEAD:<путь>``), а карточка, рождённая мостом в прод-дереве, в
HEAD этого дерева не попадает НИКОГДА (прод синкается копированием
``spa_core/``·``scripts/``·``tests/``, не ``git checkout``). Отсюда две разные
судьбы одного и того же файла:

* **создание** — пути нет ни в базе, ни на remote ⇒ ``DIVERGENCE_SAFE``, пуш идёт;
* **любое последующее обновление** — ``absent_in_base`` + файл на remote ЕСТЬ ⇒
  ``DIVERGENCE_DIVERGED`` ⇒ отказ, код возврата 4. И так БУДЕТ ВСЕГДА.

Измерено: ``delivery.status=FAILED`` (rc 4, attempted 3, delivered 0); карточка
``inbox-nahodka-petli-data-investment-os-health`` рождена самой доставкой
(коммит ``64031ee90``) и закрыта в прод-дереве, а на origin висит ``new``.
Пачка атомарна, поэтому два застрявших обновления утащили с собой ЧУЖОЕ
создание (``…docs-system-briefing-md-po`` не попало на origin вовсе).

**Что делаем — ровно то, что советует сам текст отказа пушера:** перечитываем
версию с remote и переносим на неё СВОЮ правку (:func:`rebase_card`). Перенос
разрешён только там, где он ДОКАЗУЕМ: ``set_status`` меняет ровно одну строку
``status:`` во frontmatter и больше ничего (см. ``owner_queue/queue.py``),
поэтому «remote с нашей строкой ``status:``» обязано совпасть с нашим файлом
БАЙТ В БАЙТ. Совпало — перезапись осознанная (``--allow-overwrite``), потому
что содержимое remote прочитано, а наша правка — одна известная строка. Не
совпало — ОТКАЗ по этой карточке с названной причиной; остальные едут.

Побочно закрыт второй дефект того же корня: мост решает «карточку никто не
трогал ⇒ можно закрыть» по СВОЕЙ стухшей копии, которая не видит ни ответа
владельца (``owner_choice``), ни захвата сессией (``claimed_by``), сделанных на
origin. Теперь такое расхождение видно как лишняя строка frontmatter — и
закрытие отменяется, а не стирает ответ владельца (инвариант #14, fail-CLOSED).

**Граница честности.** Между чтением remote и пушем есть окно: одновременная
правка карточки на origin будет перезаписана. Поэтому в квитанцию пишется sha
прочитанного remote — потеря остаётся хотя бы вычислимой. Прочитать remote
нечем (нет пушера/PAT/сети) ⇒ ``rebase_unmeasured``, и дальше решает СОСТАВ
пачки, потому что ``--allow-overwrite`` не выборочный — он действует на всю
команду пушера сразу:

* в пачке переносов НЕТ ⇒ путь едет как раньше, без флага, и решение остаётся
  за пушером — он fail-CLOSED и откажет сам;
* в пачке ЕСТЬ перенос ⇒ путь **придерживается** до следующего прогона
  (``held``): поехав под чужим флагом, он лишился бы единственной защиты,
  какая у него была, и слепая копия могла бы стереть ответ владельца,
  которого она не видела.

«Не измерено» и «придержано» названы в квитанции, а не выглядят проверкой.

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
import hashlib
import json
import os
import re
import subprocess
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT

STATUS_REL = os.path.join("data", "card_delivery_status.json")
TRACKER_REL = os.path.join("nimbalyst-local", "tracker")
PUSHER_REL = "push_to_github.py"
PUSH_TIMEOUT = 300
REMOTE_TIMEOUT = 30

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
#: Часть пачки уехала, часть — нет. Читается как ОТКАЗ, а не как успех: «сколько
#: получилось» в этом проекте всегда было формой тихой потери.
PARTIAL = "PARTIAL"

#: Исходы, которые НЕ означают «карточки на origin». Читателю квитанции не надо
#: помнить список статусов, чтобы не принять отказ за успех.
NOT_DELIVERED = (FAILED, REFUSED, UNCHECKED, DISABLED, PARTIAL)

#: Состояния версии карточки на origin. ``UNMEASURED`` — отдельный вид, а не
#: «файла нет»: `get_file_sha`/`get_file_content` пушера схлопывают 404 и обрыв
#: сети в один `None`, и именно на таком схлопывании держится класс fail-OPEN.
REMOTE_PRESENT = "present"
REMOTE_ABSENT = "absent"
REMOTE_UNMEASURED = "unmeasured"

#: Поля frontmatter, появление которых на origin означает «карточку уже увидели»:
#: ответ владельца (кнопки ADR-069) или захват сессией (шаг 0b протокола).
#: Нужны не для решения (решает побайтовое сравнение), а чтобы НАЗВАТЬ причину.
SEEN_ON_ORIGIN_FIELDS = (b"owner_choice", b"owner_answered_at", b"owner_answered_by",
                         b"claimed_by", b"claimed_at")

_STATUS_LINE = re.compile(rb"(?m)^status:[^\n]*\n")


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


# ── перенос нашей правки на свежую версию с origin ───────────────────────────

def card_parts(blob: bytes):
    """``(frontmatter_без_разделителей, тело)`` или ``None`` — это не карточка."""
    if not isinstance(blob, bytes) or not blob.startswith(b"---\n"):
        return None
    end = blob.find(b"\n---\n", 3)
    if end < 0:
        return None
    return blob[4:end + 1], blob[end + 5:]


def blob_sha(content: bytes) -> str:
    """git-sha содержимого — тот же расчёт, что у пушера (для квитанции)."""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(content))
    h.update(content)
    return h.hexdigest()


def rebase_card(local: bytes, remote: bytes) -> tuple:
    """Перенести НАШУ правку карточки на версию с origin → ``(bytes|None, причина)``.

    Правка моста над существующей карточкой — это РОВНО одна строка ``status:``
    (``owner_queue.queue.set_status`` меняет только её, остальное сохраняет
    байт в байт). Поэтому перенос доказуем без слияния «по смыслу»: берём
    remote, подставляем НАШУ строку ``status:`` — результат обязан совпасть с
    нашим файлом побайтово. Совпал ⇒ ничего чужого мы не теряем. Не совпал ⇒
    на origin есть что-то, чего мы не видели, и перезаписывать это нельзя.

    Отказ НАЗЫВАЕТ причину: «сделали не то» и «мы ослепли» — разные аварии.
    """
    lp, rp = card_parts(local), card_parts(remote)
    if lp is None:
        return None, "наша копия не карточка (нет frontmatter) — переносить нечего"
    if rp is None:
        return None, "версия на origin не карточка (нет frontmatter) — сравнивать не с чем"
    l_fm, _l_body = lp
    r_fm, _r_body = rp
    ours = _STATUS_LINE.search(l_fm)
    if ours is None:
        return None, "в нашей копии нет строки status: — правка не опознана"
    if _STATUS_LINE.search(r_fm) is None:
        return None, "на origin нет строки status: — карточка другой формы"
    candidate = remote[:4] + _STATUS_LINE.sub(ours.group(0), r_fm, count=1) + remote[4 + len(r_fm):]
    if candidate == local:
        return candidate, ""
    seen = [f.decode() for f in SEEN_ON_ORIGIN_FIELDS
            if re.search(rb"(?m)^" + f + rb":", r_fm) and not re.search(rb"(?m)^" + f + rb":", l_fm)]
    if seen:
        return None, (f"на origin карточку УЖЕ увидели (поля: {', '.join(seen)}) — "
                      f"наша слепая копия не смеет это стереть; закрытие отменено")
    return None, ("расхождение с origin не сводится к одной строке status: — "
                  "перенести правку автоматически нечем; сделать это вручную из "
                  "worktree на origin/main")


def _load_pusher_module(root: str):
    """Модуль пушера как библиотека (константы REPO/API_BASE + `get_pat`)."""
    import importlib.util
    path = os.path.join(root, PUSHER_REL)
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("_spa_pusher_for_delivery", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _default_remote_reader(root: str, repo_path: str) -> tuple:
    """``(состояние, bytes|None, причина)`` — версия карточки на `origin/main`.

    Транспорт берём у пушера (PAT из Keychain, тот же репозиторий), но 404
    отделяем от сбоя САМИ: у пушера обе беды схлопнуты в ``None``, а нам
    «файла на origin нет» и «мы не смогли посмотреть» обязаны дать разные
    решения — иначе слепота выглядела бы как чистое создание.
    """
    import urllib.error
    import urllib.request
    try:
        mod = _load_pusher_module(root)
        if mod is None:
            return REMOTE_UNMEASURED, None, f"инструмента доставки нет: {PUSHER_REL}"
        pat = mod.get_pat()
        url = f"{mod.API_BASE}/repos/{mod.REPO}/contents/{repo_path}?ref=main"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as resp:
            return REMOTE_PRESENT, resp.read(), ""
    except urllib.error.HTTPError as e:  # noqa: PERF203 — 404 это ОТВЕТ, а не сбой
        if e.code == 404:
            return REMOTE_ABSENT, None, "на origin файла нет — это создание"
        return REMOTE_UNMEASURED, None, f"HTTP {e.code} при чтении origin"
    except Exception as e:  # noqa: BLE001
        return REMOTE_UNMEASURED, None, f"{type(e).__name__}: {e}"


def plan_batch(root: str, paths: list, reader=_default_remote_reader) -> dict:
    """Что делать с каждой карточкой пачки ДО пуша.

    ``{to_push, rebased, refused, already_on_origin, unmeasured, held}`` — ни
    один путь не исчезает молча: он либо в пачке, либо назван в одном из списков.
    """
    plan = {"to_push": [], "rebased": [], "refused": [],
            "already_on_origin": [], "unmeasured": [], "held": []}
    for absolute in paths:
        repo_path = _rel(root, absolute).replace(os.sep, "/")
        try:
            with open(absolute, "rb") as f:
                local = f.read()
        except Exception as e:  # noqa: BLE001
            plan["refused"].append({"path": repo_path, "reason": f"файл не прочитан: {e}"})
            continue
        state, remote, why = reader(root, repo_path)
        if state == REMOTE_ABSENT:
            plan["to_push"].append(absolute)
            continue
        if state != REMOTE_PRESENT or remote is None:
            plan["unmeasured"].append({"path": repo_path, "reason": why or "не измерено"})
            plan["to_push"].append(absolute)  # решение остаётся за пушером (он fail-CLOSED)
            continue
        if remote == local:
            plan["already_on_origin"].append(repo_path)
            continue
        merged, reason = rebase_card(local, remote)
        if merged is None:
            plan["refused"].append({"path": repo_path, "reason": reason})
            continue
        plan["rebased"].append({"path": repo_path, "remote_sha": blob_sha(remote)[:8],
                                "status_line": _STATUS_LINE.search(card_parts(local)[0])
                                .group(0).decode().strip()})
        plan["to_push"].append(absolute)

    # ── `--allow-overwrite` НЕ выборочный: он действует на ВСЮ команду пушера ──
    # Перенос доказан только там, где remote ПРОЧИТАН. Непрочитанный путь, уехавший
    # в той же пачке, поехал бы под тем же флагом — и остался бы вообще без защиты:
    # у пушера `guard_overwrite` при `allow_overwrite` отдаёт DIVERGED в перезапись
    # молча (ветка «ПЕРЕЗАПИСЬ РАЗРЕШЕНА ЯВНО»), а заодно снимает стража общей памяти
    # и стража пропадающих записей. Ровно так слепая копия стирает ответ владельца,
    # которого она не видела (инвариант #14) — то самое, что запрещает п.3 ADR-080.
    # Обещание «решает пушер, он fail-CLOSED» верно ТОЛЬКО в пачке без переносов;
    # тест на него это и проверял — в пачке из одной карточки, где оно не могло
    # сломаться. Поэтому непрочитанные придерживаем: мост ходит каждый цикл, а
    # «не измерено» — состояние преходящее. Придержанные названы в квитанции и
    # НЕ выглядят доставленными.
    if plan["rebased"] and plan["unmeasured"]:
        held_paths = {u["path"] for u in plan["unmeasured"]}
        plan["to_push"] = [p for p in plan["to_push"]
                           if _rel(root, p).replace(os.sep, "/") not in held_paths]
        for u in plan["unmeasured"]:
            u["held"] = True
            u["reason"] = (f"{u['reason']} — ПРИДЕРЖАНА: в пачке есть перенос, значит "
                           f"пушер поедет с --allow-overwrite, а он не выборочный — под "
                           f"ним у этого пути не осталось бы ни одного стража. Поедет "
                           f"следующим прогоном, когда origin удастся прочитать")
        plan["held"] = [dict(u) for u in plan["unmeasured"]]
    return plan


def build_message(root: str, paths: list) -> str:
    names = [os.path.basename(p) for p in paths]
    head = ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")
    return (f"cards(ADR-066): доставка карточек петли ({len(names)}): {head} — "
            f"рождены агентом в прод-дереве, куда доставка не заглядывает; "
            f"одной пачкой, одним коммитом")


def _default_pusher(root: str, paths: list, message: str,
                    allow_overwrite: bool = False) -> tuple:
    """``(returncode, вывод)``. Единственное место, где доставка ходит наружу.

    ``allow_overwrite`` ставится ТОЛЬКО когда :func:`plan_batch` доказал перенос
    на прочитанный remote. Это не ослабление стража, а исполнение его же
    предписания: «перечитать со свежего origin/main, перенести свою правку и
    запушить снова; осознанная перезапись — ``--allow-overwrite``».
    """
    pusher = os.path.join(root, PUSHER_REL)
    if not os.path.isfile(pusher):
        return None, f"инструмента доставки нет: {pusher}"
    argv = [sys.executable, pusher, "--files", *paths, "--message", message]
    if allow_overwrite:
        argv.append("--allow-overwrite")
    r = subprocess.run(argv, capture_output=True, text=True, timeout=PUSH_TIMEOUT, cwd=root)
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))


def _tail(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def deliver(paths, root: str = REPO_ROOT, now: dt.datetime | None = None,
            pusher=_default_pusher, env=None, write_status: bool = True,
            message: str | None = None, reader=_default_remote_reader) -> dict:
    """Довезти карточки до `origin/main`. Возвращает квитанцию (и пишет её на диск).

    Исключений НЕ бросает: доставка не смеет уронить сторожа, который её позвал.
    Но и не смеет промолчать — любой исход попадает в ``status``.
    """
    ts = _now(now)
    receipt = {"generated_at": ts.isoformat(), "adr": "ADR-066",
               "attempted": [], "delivered": [], "refused": [],
               "rebased": [], "rebase_refused": [], "already_on_origin": [],
               "rebase_unmeasured": [], "held": [],
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
            plan = plan_batch(root, ok, reader=reader)
            receipt["rebased"] = plan["rebased"]
            receipt["rebase_refused"] = plan["refused"]
            receipt["already_on_origin"] = plan["already_on_origin"]
            receipt["rebase_unmeasured"] = plan["unmeasured"]
            receipt["held"] = plan["held"]
            # Застряло = не переносится ЛИБО придержано под чужим `--allow-overwrite`.
            # Причины разные, судьба одна: на origin не попало, и успехом это звать нельзя.
            blocked = plan["refused"] + plan["held"]
            stuck = "; ".join(f"{b['path']}: {b['reason']}" for b in blocked)
            if not plan["to_push"]:
                if blocked:
                    receipt["status"] = REFUSED
                    receipt["reason"] = f"переносить нечем, ни одна карточка не поехала — {stuck}"
                else:
                    receipt["status"] = IDLE
                    receipt["reason"] = ("везти нечего — версии на origin совпадают с нашими "
                                         f"({len(plan['already_on_origin'])} карточк(и))")
            else:
                msg = message or build_message(root, plan["to_push"])
                receipt["message"] = msg
                rc, out = pusher(root, plan["to_push"], msg,
                                 allow_overwrite=bool(plan["rebased"]))
                receipt["returncode"] = rc
                receipt["output"] = _tail(out)
                if rc == 0 and not blocked:
                    receipt["status"] = DELIVERED
                    receipt["delivered"] = [_rel(root, p) for p in plan["to_push"]]
                    receipt["reason"] = "пушер вернул 0 — карточки на origin"
                elif rc == 0:
                    receipt["status"] = PARTIAL
                    receipt["delivered"] = [_rel(root, p) for p in plan["to_push"]]
                    receipt["reason"] = (f"уехало {len(plan['to_push'])}, ЗАСТРЯЛО "
                                         f"{len(blocked)} — {stuck}")
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
    n_reb = len(receipt.get("rebased") or [])
    tail = f" · перенесено на свежий origin: {n_reb}" if n_reb else ""
    if st == DELIVERED:
        return f"card_delivery: ✅ DELIVERED {n_try} карточк(и) → origin/main{tail}"
    if st == IDLE:
        return f"card_delivery: — доставлять нечего{tail}"
    return (f"card_delivery: ⚠️ {st} (пыталось {n_try}){tail} — {receipt.get('reason', '')}")


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
