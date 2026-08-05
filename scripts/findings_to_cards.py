#!/usr/bin/env python3
"""findings_to_cards.py — мост «находка → карточка → закрытие» (ADR-066, Контур C2).

Сторожа умеют находить. До сегодня их находки жили в JSON-файлах, которые никто не
обязан открывать, — ровно тот же дефект, что аудит 2026-08-05 нашёл у отчётов
инвест-офиса: продюсер без обязательного потребителя деградирует молча. Мост замыкает
последнее звено: находка сторожа становится КАРТОЧКОЙ в очереди, а исчезнувшая находка
— закрытой карточкой, и то и другое без рук.

Источники (оба дают находки ОДНОГО формата — это не совпадение, а условие):
  · `data/architecture_conformance.json` — сторож архитектуры (ADR-066 B1–B5)
  · `data/house_view_gap.json`           — сверка офис ↔ книга (ADR-066 C1)

Дисциплина против спама — четыре независимых механизма:

  **Dedup** — стабильный ключ находки (`<источник>/<key>`). Одна находка = одна
    карточка, сколько бы раз сторож её ни повторил.
  **Гистерезис** — карточка рождается только на НОВУЮ или ЭСКАЛИРОВАВШУЮ находку
    (WARN→CRITICAL). Слабо-мигающие находки должны подтвердиться `--min-observations`
    прогонами подряд (CRITICAL — сразу: капитал ждать не будет). Только что закрытая
    находка не может воскреснуть раньше `--reopen-cooldown-h` — иначе мигающий сторож
    выдаёт по карточке за прогон.
  **Rate-limit** — не больше `--max-per-day` карточек за скользящие сутки. Лишнее
    **не выбрасывается молча**: попадает в отчёт со статусом «отложено» и причиной.
    Порядок очереди: CRITICAL раньше WARN, затем по давности первого появления.
  **Класс сигнала** — карточки заводятся на `strong`-находки и на любые CRITICAL.
    `weak` (стареющие по P2 — напр. «книга держит протокол при ЖЁЛТОМ сигнале»)
    остаются видимыми в отчёте, но карточку не порождают: у нас их постоянно
    несколько и они не адресуют ничьё решение. Молчанием это не является — они
    перечислены в `data/findings_bridge.json`.

Авто-закрытие: находка исчезла из свежего отчёта источника ⇒ карточка переводится в
`done`, а в тело дописывается эвиденс (какой отчёт, на какой момент, что находки в нём
уже нет). **Источник, который не прочитался, не закрывает НИЧЕГО** (fail-CLOSED:
отсутствие отчёта ≠ отсутствие находки — иначе сломанный сторож «чинил» бы очередь).

Маршрутизация (ADR-066 C2): CRITICAL → карточка `owner-decision` `needs-owner` в формате
§2.4 (четыре обязательные секции по-русски, инвариант #15) + Telegram-уведомление;
остальное → `agent-task` `backlog`.

Карточки создаются и двигаются ТОЛЬКО через `scripts/orchestrator_queue.py`
(единственный мутационный API очереди, ADR-066 P6) — здесь нет ни одной прямой записи
в файл карточки. По умолчанию скрипт НИЧЕГО не мутирует: план печатается и exit 0;
мутации — только с `--apply` (fail-safe: случайный запуск не наводняет очередь).

LLM_FORBIDDEN. Только stdlib. Время — вход (`now=`), не окружение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

QUEUE_CLI = os.path.join(_REPO_ROOT, "scripts", "orchestrator_queue.py")
STATE_REL = os.path.join("data", "findings_bridge_state.json")
REPORT_REL = os.path.join("data", "findings_bridge.json")

# Источники находок: id → относительный путь отчёта.
SOURCES = {
    "arch": os.path.join("data", "architecture_conformance.json"),
    "hvg": os.path.join("data", "house_view_gap.json"),
}
SOURCE_TITLES = {
    "arch": "сторож архитектуры (ADR-066 B)",
    "hvg": "сверка офис ↔ книга (ADR-066 C1)",
}

MAX_CARDS_PER_DAY = 5
MIN_OBSERVATIONS = 2
REOPEN_COOLDOWN_H = 24.0
# Отчёт старше этого — источник считается непрочитанным (не закрывает и не открывает).
SOURCE_MAX_AGE_H = 48.0

SEVERITY_RANK = {"WARN": 1, "CRITICAL": 2}


# ── ввод/вывод ───────────────────────────────────────────────────────────────

def _parse_iso(value) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _load_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def read_sources(root: str, now: dt.datetime,
                 max_age_h: float = SOURCE_MAX_AGE_H) -> tuple[list[dict], dict]:
    """→ (находки, состояние источников).

    Находка нормализуется: `key` префиксуется источником, поля приводятся к общему
    виду. Источник без файла / с битым JSON / протухший — `readable=False`, и тогда
    он НЕ закрывает свои прежние карточки (fail-CLOSED).
    """
    findings: list[dict] = []
    status: dict[str, dict] = {}
    for src, rel in SOURCES.items():
        path = os.path.join(root, rel)
        doc = _load_json(path)
        if not isinstance(doc, dict):
            status[src] = {"readable": False, "path": rel,
                           "reason": "отчёт отсутствует или не разобран — источник НЕ ПРОЧИТАН, "
                                     "его карточки не закрываются (отсутствие отчёта ≠ "
                                     "отсутствие находки)"}
            continue
        gen = _parse_iso(doc.get("generated_at"))
        if gen is None:
            status[src] = {"readable": False, "path": rel,
                           "reason": "в отчёте нет разбираемого generated_at — свежесть "
                                     "НЕ ИЗМЕРЕНА, источник не считается прочитанным"}
            continue
        age_h = (now - gen).total_seconds() / 3600.0
        if age_h > max_age_h:
            status[src] = {"readable": False, "path": rel, "age_hours": round(age_h, 1),
                           "reason": f"отчёт протух ({age_h:.1f}ч > {max_age_h}ч) — сторож "
                                     f"молчит, и его молчание не закрывает карточки"}
            continue
        status[src] = {"readable": True, "path": rel, "age_hours": round(age_h, 1),
                       "overall": doc.get("overall")}
        for f in doc.get("findings") or []:
            if not isinstance(f, dict) or not f.get("key"):
                continue
            findings.append({
                "key": f"{src}/{f['key']}",
                "source": src,
                "check": f.get("check", ""),
                "severity": str(f.get("severity", "WARN")).upper(),
                "class": f.get("class", "strong"),
                "message": f.get("message", ""),
                "first_seen": f.get("first_seen") or doc.get("generated_at"),
            })
    return findings, status


def load_state(path: str) -> dict:
    doc = _load_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), dict):
        return {"entries": {}}
    return doc


# ── ядро планирования (чистое: без единой мутации) ───────────────────────────

def plan(findings: list[dict], source_status: dict, state: dict, now: dt.datetime, *,
         max_per_day: int = MAX_CARDS_PER_DAY,
         min_observations: int = MIN_OBSERVATIONS,
         reopen_cooldown_h: float = REOPEN_COOLDOWN_H) -> dict:
    """Решить, что открыть, что закрыть, что отложить — не делая ничего."""
    entries = state.get("entries", {})
    by_key = {f["key"]: f for f in findings}

    candidates: list[dict] = []
    pending: list[dict] = []
    suppressed: list[dict] = []
    unchanged: list[dict] = []
    not_carded: list[dict] = []
    # Счётчик подтверждений ведётся для КАЖДОЙ находки, включая те, что карточку не
    # порождают: иначе гистерезис «подтвердись N раз» никогда бы не созревал —
    # apply_plan сбросил бы счётчик обратно в 1 на каждом прогоне.
    observed: dict[str, int] = {}

    for f in findings:
        e = entries.get(f["key"]) or {}
        observations = int(e.get("observations") or 0) + 1
        observed[f["key"]] = observations
        cardable = f["severity"] == "CRITICAL" or f.get("class") == "strong"
        if not cardable:
            not_carded.append({**f, "observations": observations,
                               "reason": "слабый сигнал: видим в отчёте источника, "
                                         "стареет по P2, карточку не порождает"})
            continue

        f = {**f, "observations": observations}

        if e.get("status") == "open":
            prev_rank = SEVERITY_RANK.get(str(e.get("severity", "")).upper(), 0)
            if SEVERITY_RANK.get(f["severity"], 0) > prev_rank:
                candidates.append({**f, "reason": "эскалация "
                                                  f"{e.get('severity')}→{f['severity']}"})
            else:
                unchanged.append({**f, "card_path": e.get("card_path")})
            continue

        closed_at = _parse_iso(e.get("closed_at"))
        if closed_at is not None and (now - closed_at).total_seconds() / 3600.0 < reopen_cooldown_h:
            suppressed.append({**f, "reason": f"гистерезис: карточка закрыта "
                                              f"{e.get('closed_at')}, до повторного "
                                              f"открытия ждём {reopen_cooldown_h}ч"})
            continue

        if f["severity"] != "CRITICAL" and observations < min_observations:
            pending.append({**f, "reason": f"гистерезис: подтверждений {observations} из "
                                           f"{min_observations} — мигающая находка карточку "
                                           f"не заводит"})
            continue

        candidates.append({**f, "reason": "новая находка" if not e else "находка вернулась"})

    # rate-limit: скользящие сутки по фактическим открытиям из состояния
    opened_recently = 0
    for e in entries.values():
        ts = _parse_iso(e.get("opened_at"))
        if ts is not None and (now - ts).total_seconds() / 3600.0 < 24.0:
            opened_recently += 1
    budget = max(0, max_per_day - opened_recently)

    candidates.sort(key=lambda f: (-SEVERITY_RANK.get(f["severity"], 0),
                                   f.get("first_seen") or "", f["key"]))
    to_open = candidates[:budget]
    deferred = [{**f, "reason": f"отложено: суточный лимит {max_per_day} карточек исчерпан "
                                f"(за последние 24ч открыто {opened_recently}); находка не "
                                f"потеряна — вернётся следующим прогоном"}
                for f in candidates[budget:]]

    # авто-закрытие: только по ПРОЧИТАННЫМ источникам
    to_close: list[dict] = []
    for key, e in entries.items():
        if e.get("status") != "open":
            continue
        src = e.get("source")
        if not source_status.get(src, {}).get("readable"):
            continue
        if key in by_key:
            continue
        to_close.append({"key": key, "source": src, "card_path": e.get("card_path"),
                         "severity": e.get("severity"), "message": e.get("message", "")})

    return {"open": to_open, "close": to_close, "deferred": deferred, "pending": pending,
            "suppressed": suppressed, "unchanged": unchanged, "not_carded": not_carded,
            "observations": observed,
            "budget": {"max_per_day": max_per_day, "opened_last_24h": opened_recently,
                       "remaining": budget}}


# ── карточки (единственный мутационный API — orchestrator_queue.py) ──────────

def _run_queue(args: list[str], root: str) -> tuple[int, str, str]:
    proc = subprocess.run([sys.executable, QUEUE_CLI, *args],
                          capture_output=True, text=True, cwd=root, timeout=120)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def card_title(f: dict) -> str:
    """Заголовок по-русски (инвариант #15 — включая НАЗВАНИЕ карточки)."""
    head = str(f.get("message") or f.get("key") or "находка без описания")
    head = head.split(" — ")[0].split(" (")[0].strip()
    if len(head) > 90:
        head = head[:87].rstrip() + "…"
    return f"Находка сторожа: {head}"


def owner_body(f: dict, source_status: dict) -> str:
    """Тело needs-owner карточки — ровно четыре секции §2.4, по-русски."""
    src = f.get("source", "")
    rel = SOURCES.get(src, "")
    return f"""## Что случилось и почему это важно

{SOURCE_TITLES.get(src, src)} нашёл КРИТИЧЕСКОЕ расхождение и повторяет его в каждом прогоне:

> {f.get('message')}

Находка касается капитала или архитектуры флота, поэтому решение за тобой — сам я его не принимаю.
Первый раз это увидено {f.get('first_seen')}; отчёт со свежими данными — `{rel}`.

## Что от тебя нужно

1. Открой `{rel}` и найди находку с ключом `{f.get('key')}` — там полный контекст.
2. Реши: это настоящая проблема (тогда напиши, что делать) или сторож ошибается
   (тогда напиши это — сторожа чиним, а не глушим, правило `.claude/rules/deployment.md`).

## Как понять, что готово

Ты написал ответ в этой карточке и перевёл её в `owner-done`.

## Что будет после

Агент исполнит решение по протоколу. Если находка исчезнет из отчёта сама — карточка
закроется автоматически со ссылкой на прогон, в котором её уже не было.
"""


def agent_body(f: dict) -> str:
    src = f.get("source", "")
    rel = SOURCES.get(src, "")
    return f"""## Находка

{f.get('message')}

- источник: {SOURCE_TITLES.get(src, src)} (`{rel}`)
- ключ находки: `{f.get('key')}` · проверка `{f.get('check')}` · severity {f.get('severity')}
- впервые увидена: {f.get('first_seen')} · подтверждений к моменту заведения: {f.get('observations')}
- причина заведения: {f.get('reason')}

## Acceptance

- находка исчезает из `{rel}` **по существу** (устранена причина), а не потому, что
  сторожа приглушили — ослабление проверки запрещено (`.claude/rules/deployment.md`,
  инвариант #16);
- после устранения карточка закрывается сама следующим прогоном моста — вручную
  двигать статус не нужно.

## Заведено автоматически

Мост «находка→карточка» (ADR-066 Контур C2, `scripts/findings_to_cards.py`).
Если карточка бессмысленна — это дефект СТОРОЖА либо маршрутизации: заведи об этом
отдельную карточку, не выключай мост молча.
"""


def open_card(f: dict, source_status: dict, root: str, *, runner=None, notifier=None) -> dict:
    """Создать карточку по находке. → {'card_path':..., 'error':...}"""
    runner = runner or (lambda args: _run_queue(args, root))
    critical = f["severity"] == "CRITICAL"
    body = owner_body(f, source_status) if critical else agent_body(f)
    args = ["create",
            "--type", "owner-decision" if critical else "agent-task",
            "--title", card_title(f),
            "--status", "needs-owner" if critical else "backlog",
            "--source", "findings-bridge",
            "--body", body,
            "--field", f"finding_key={f['key']}",
            "--field", "adr=ADR-066",
            "--field", f"priority={'high' if critical else 'medium'}"]
    rc, out, err = runner(args)
    if rc != 0 or not out:
        return {"key": f["key"], "error": f"create rc={rc}: {err or out}"}
    card_path = out.splitlines()[-1].strip()
    result = {"key": f["key"], "card_path": card_path, "severity": f["severity"]}
    if critical:
        notify = notifier or (lambda p: _run_queue(["notify", p], root))
        nrc, nout, nerr = notify(card_path)
        result["notified"] = (nrc == 0)
        if nrc != 0:
            result["notify_error"] = nerr or nout
    return result


def close_card(entry: dict, root: str, now: dt.datetime, *, runner=None,
               appender=None) -> dict:
    """Закрыть карточку исчезнувшей находки + дописать эвиденс в тело."""
    runner = runner or (lambda args: _run_queue(args, root))
    path = entry.get("card_path")
    if not path:
        return {"key": entry["key"], "error": "в состоянии нет пути карточки"}
    rel = SOURCES.get(str(entry.get("source") or ""), "")
    evidence = (f"\n---\n\n**Закрыто автоматически** мостом «находка→карточка» "
                f"(ADR-066 C2) {now.isoformat()}: находки `{entry['key']}` больше нет в "
                f"свежем отчёте `{rel}`. Закрытие — по ИСЧЕЗНОВЕНИЮ находки в прочитанном "
                f"отчёте; непрочитанный отчёт не закрывает ничего.\n")
    append = appender or _append_to_card
    err = append(os.path.join(root, path) if not os.path.isabs(path) else path, evidence)
    rc, out, err_out = runner(["set-status", path, "done"])
    if rc != 0:
        return {"key": entry["key"], "card_path": path,
                "error": f"set-status rc={rc}: {err_out or out}"}
    return {"key": entry["key"], "card_path": path, "evidence_error": err}


def _append_to_card(path: str, text: str) -> str | None:
    """Дописать эвиденс в конец карточки. Возвращает текст ошибки или None.

    Тело карточки — не frontmatter: статус двигает только очередь, а сюда добавляется
    строка-хвост. Ошибка не срывает закрытие (статус важнее следа), но и не молчит.
    """
    try:
        from spa_core.utils.atomic import atomic_save_text
        with open(path, encoding="utf-8") as fh:
            cur = fh.read()
        atomic_save_text(cur.rstrip("\n") + "\n" + text, path)
        return None
    except Exception as exc:  # noqa: BLE001
        return f"эвиденс не дописан: {exc}"


# ── применение плана + состояние ─────────────────────────────────────────────

def apply_plan(actions: dict, findings: list[dict], state: dict, source_status: dict,
               root: str, now: dt.datetime, *, runner=None, notifier=None) -> dict:
    entries = state.setdefault("entries", {})
    by_key = {f["key"]: f for f in findings}
    opened, closed = [], []

    for f in actions["open"]:
        res = open_card(f, source_status, root, runner=runner, notifier=notifier)
        if res.get("error"):
            opened.append(res)
            continue
        entries[f["key"]] = {
            "source": f["source"], "check": f["check"], "severity": f["severity"],
            "class": f.get("class"), "message": f.get("message"),
            "card_path": res["card_path"], "status": "open",
            "opened_at": now.isoformat(), "closed_at": None,
            "first_seen": f.get("first_seen"), "last_seen": now.isoformat(),
            "observations": f.get("observations", 1),
        }
        opened.append(res)

    for e in actions["close"]:
        entry = entries.get(e["key"], {})
        res = close_card({**entry, "key": e["key"]}, root, now, runner=runner)
        if res.get("error"):
            closed.append(res)
            continue
        entry["status"] = "closed"
        entry["closed_at"] = now.isoformat()
        entry["observations"] = 0
        entries[e["key"]] = entry
        closed.append(res)

    # счётчики подтверждений живут и для тех, кому карточку ещё не завели
    observed = actions.get("observations", {})
    for key, f in by_key.items():
        n = observed.get(key, 1)
        e = entries.get(key)
        if e is None:
            entries[key] = {"source": f["source"], "check": f["check"],
                            "severity": f["severity"], "class": f.get("class"),
                            "message": f.get("message"), "card_path": None,
                            "status": "seen", "opened_at": None, "closed_at": None,
                            "first_seen": f.get("first_seen"), "last_seen": now.isoformat(),
                            "observations": n}
        else:
            e["last_seen"] = now.isoformat()
            e["message"] = f.get("message", e.get("message"))
            e["severity"] = f["severity"]
            # Счётчик обновляется и для ЗАКРЫТЫХ записей: иначе вернувшаяся находка
            # навсегда застревает на нуле подтверждений и не может завести карточку
            # повторно — подавление становится необратимым (класс «irreversible
            # UNCHECKED starves the queue»). Закрытие само по себе бывает только в
            # прогон, где находки НЕТ, так что лишнего инкремента здесь не случается.
            e["observations"] = n

    # находка исчезла и по прочитанному источнику — счётчик подтверждений обнуляем
    for key, e in entries.items():
        if key in by_key:
            continue
        if source_status.get(e.get("source"), {}).get("readable"):
            e["observations"] = 0

    state["generated_at"] = now.isoformat()
    return {"opened": opened, "closed": closed}


def build_report(actions: dict, source_status: dict, applied: dict | None,
                 now: dt.datetime) -> dict:
    return {
        "generated_at": now.isoformat(),
        "adr": "ADR-066",
        "contour": "C2",
        "applied": applied is not None,
        "sources": source_status,
        "counts": {
            "opened": len(applied["opened"]) if applied else 0,
            "closed": len(applied["closed"]) if applied else 0,
            "planned_open": len(actions["open"]),
            "planned_close": len(actions["close"]),
            "deferred": len(actions["deferred"]),
            "pending": len(actions["pending"]),
            "suppressed": len(actions["suppressed"]),
            "not_carded": len(actions["not_carded"]),
        },
        "budget": actions["budget"],
        "opened": applied["opened"] if applied else [],
        "closed": applied["closed"] if applied else [],
        "planned_open": actions["open"],
        "planned_close": actions["close"],
        "deferred": actions["deferred"],
        "pending": actions["pending"],
        "suppressed": actions["suppressed"],
        "not_carded": actions["not_carded"],
        "note": "Отложенное и подавленное перечислено ПОИМЁННО: молчаливого обрезания "
                "очереди здесь нет (ADR-066 C2).",
    }


def run(root: str, now: dt.datetime, *, apply: bool = False,
        max_per_day: int = MAX_CARDS_PER_DAY, min_observations: int = MIN_OBSERVATIONS,
        reopen_cooldown_h: float = REOPEN_COOLDOWN_H,
        state_path: str | None = None, report_path: str | None = None,
        runner=None, notifier=None) -> dict:
    state_path = state_path or os.path.join(root, STATE_REL)
    report_path = report_path or os.path.join(root, REPORT_REL)

    findings, source_status = read_sources(root, now)
    state = load_state(state_path)
    actions = plan(findings, source_status, state, now, max_per_day=max_per_day,
                   min_observations=min_observations, reopen_cooldown_h=reopen_cooldown_h)

    applied = None
    if apply:
        applied = apply_plan(actions, findings, state, source_status, root, now,
                             runner=runner, notifier=notifier)
        from spa_core.utils.atomic import atomic_save
        atomic_save(state, state_path)

    report = build_report(actions, source_status, applied, now)
    if apply:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, report_path)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="ADR-066 C2 — мост «находка сторожа → карточка очереди → закрытие»")
    ap.add_argument("--apply", action="store_true",
                    help="создавать/закрывать карточки. Без флага — только план (fail-safe)")
    ap.add_argument("--root", default=_REPO_ROOT)
    ap.add_argument("--max-per-day", type=int, default=MAX_CARDS_PER_DAY)
    ap.add_argument("--min-observations", type=int, default=MIN_OBSERVATIONS)
    ap.add_argument("--reopen-cooldown-h", type=float, default=REOPEN_COOLDOWN_H)
    ap.add_argument("--json", action="store_true", help="отчёт в stdout как JSON")
    args = ap.parse_args(argv)

    report = run(args.root, dt.datetime.now(dt.timezone.utc), apply=args.apply,
                 max_per_day=args.max_per_day, min_observations=args.min_observations,
                 reopen_cooldown_h=args.reopen_cooldown_h)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    c = report["counts"]
    mode = "ПРИМЕНЕНО" if report["applied"] else "ПЛАН (без --apply ничего не создаётся)"
    print(f"findings_to_cards [{mode}]: открыто {c['opened']}/{c['planned_open']} · "
          f"закрыто {c['closed']}/{c['planned_close']} · отложено {c['deferred']} · "
          f"ждут подтверждения {c['pending']} · подавлено гистерезисом {c['suppressed']} · "
          f"слабых (без карточки) {c['not_carded']}")
    for src, st in report["sources"].items():
        if not st.get("readable"):
            print(f"  [ИСТОЧНИК НЕ ПРОЧИТАН] {src}: {st.get('reason')}")
    for f in report["opened"]:
        print(f"  + {f.get('card_path') or f.get('error')}  ({f['key']})")
    for f in report["closed"]:
        print(f"  − закрыта {f.get('card_path') or f.get('error')}  ({f['key']})")
    for f in report["deferred"]:
        print(f"  … {f['key']}: {f['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
