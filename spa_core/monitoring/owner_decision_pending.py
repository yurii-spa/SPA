#!/usr/bin/env python3
"""owner_decision_pending.py — у остановки должен быть ЖИВОЙ вопрос владельцу.

Вопрос, на который отвечает этот модуль, — РОВНО ОДИН и больше никакой:

    если система остановлена, есть ли у неё заданный, доставленный и НАЖИМАЕМЫЙ
    вопрос владельцу — и сколько он уже ждёт ответа?

Почему он понадобился (замер 10.08.2026, цикл #195)
------------------------------------------------------------------------------
Прод встал в **00:52 UTC** (`data/kill_switch_active.json`, «threat_reactor: emergency
breaker: HALT»). Снять остановку может ТОЛЬКО владелец (инв. 1–3 CLAUDE.md, ADR-078) —
у системы нет и не должно быть права поднять себя самой. Вопрос владельцу ушёл в
**12:23 UTC**. Одиннадцать с половиной часов книга стояла в кэше, а вопроса, без которого
она не поднимется, в очереди владельца просто не было — и этого разрыва не измерял НИКТО.

Соседние сторожа отвечают честно и мимо (тот же класс, что `.claude/rules/deployment.md`
разбирает на трёх вопросах доставки):

  * `agent_health`            — агенты живы?            (остановка агентов не касается)
  * `cycle_health`            — цикл сходил?            (назовёт падение, не его причину)
  * `deployment_acceptance`   — флот способен стартовать? (способен, и это верно)
  * `house_view_gap`          — офис расходится с книгой? (расходится, но не про путь вверх)

Ни один не спрашивает про ПУТЬ ВВЕРХ. Худший случай — остановка вообще без вопроса
владельцу: тупик, из которого система не выйдет никогда, и сказать об этом некому.

Что модуль делает и чего НЕ делает
------------------------------------------------------------------------------
Только НАЗЫВАЕТ. Он не снимает остановку, не трогает пороги RiskPolicy, не двигает
капитал, не пишет в карточки и не отправляет ничего сам: возвращает отчёт, который
пишется в `data/owner_decision_pending.json` и потребляется `agent_health_monitor`
(ежечасно) и обязательным шагом 0-офис оркестратора (через `architecture/manifest.json`).

Находки:

  H1  CRITICAL  остановка активна, ждущих ответа вопросов НЕТ ВОВСЕ — тупик.
  H1u CRITICAL  остановка активна, а ждут ли вопросы ответа — НЕ ИЗМЕРЕНО (карточек
                пушей нет в дереве). Неизмеримый путь вверх во время остановки не
                лучше отсутствующего, но называется он ОТДЕЛЬНО: «не измерено» и
                «нет» — разные факты (fail-CLOSED, не fail-OPEN и не поклёп).
  H2  WARNING   остановка активна, вопрос отправлен и ждёт ответа —
      CRITICAL   после `PENDING_CRITICAL_H` часов ожидания: молчание такой длины
                 перестаёт быть «владелец сейчас ответит».
  H3  WARNING   ждущий ответа вопрос ушёл БЕЗ КНОПОК — владелец не может ответить
                с телефона вовсе. Непрерывная версия разового замера карточки
                `inbox-vosem-kartochek-vse-esche-zhdut-vladelts` (цикл #191).

**Без остановки ждущие вопросы тревогой НЕ являются** — только полями отчёта. Владелец
бывает в отъезде (сейчас — до ~19.08), и WARN, который не может погаснуть девять дней, —
это шум, а не сигнал; ровно так очередь и глохнет (урок «нестираемое „не измерено“
морит очередь голодом»). Тревога поднимается там, где ожидание СТОИТ системе денег
или трека, — то есть при остановке.

Честность (fail-CLOSED)
------------------------------------------------------------------------------
Нечитаемый журнал отправок, отсутствующая карточка пуша ⇒ запись в `unchecked` с
причиной, а не молчаливое «ждущих нет». `status: OK` возможен ТОЛЬКО когда всё
вычислено и всё прошло.

Время — ВХОД (`now=`), не окружение (`.claude/rules/deployment.md`): и вердикт, и
отметки в фикстурах закрепляются тестом с обеих сторон.

CLI::  python3 -m spa_core.monitoring.owner_decision_pending [--json] [--no-write]

Exit: 0 — OK · 1 — WARNING/UNCHECKED · 2 — CRITICAL.
LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Optional

from spa_core.governance.kill_switch import KILL_SWITCH_ACTIVE_FILENAME
from spa_core.utils.atomic import atomic_save
from spa_core.utils.live_paths import live_data_dir

_REPO_ROOT = Path(__file__).resolve().parents[2]

OK = "OK"
WARNING = "WARNING"
CRITICAL = "CRITICAL"
_SEVERITY = {OK: 0, WARNING: 1, CRITICAL: 2}

#: Журнал отправленных владельцу решений (пишет `spa_core/telegram/owner_decisions.py`).
PUSH_JOURNAL = "telegram_owner_decisions.json"
#: Куда пишется отчёт этого модуля.
REPORT_REL = "data/owner_decision_pending.json"

#: Сколько часов ожидания ответа ВО ВРЕМЯ ОСТАНОВКИ ещё читается как «владелец
#: сейчас ответит». Это порог ОТЧЁТНОСТИ, а не риска: ни RiskPolicy, ни ступени
#: выключателя он не касается и касаться не может.
PENDING_CRITICAL_H = 12.0

#: Статус карточки, означающий «вопрос владельцу ещё открыт».
_OPEN_CARD_STATUS = "needs-owner"


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _SEVERITY.get(s, 0)) if statuses else OK


def _parse_ts(value: Any) -> Optional[dt.datetime]:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _hours_since(value: Any, now: dt.datetime) -> Optional[float]:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 3600.0


#: Карточка на диске есть, но не разобралась. НЕ «закрыта»: пустая строка сравнилась
#: бы с `needs-owner` как «не равно» и вопрос молча выпал бы из очереди — fail-OPEN
#: ровно того вида, ради которого этот модуль и написан.
_UNREADABLE = "\x00unreadable"


def _card_status(tracker_dir: Path, card_id: str) -> tuple[Optional[str], Optional[str]]:
    """(status, title) карточки по её идентификатору. (None, None) — карточки нет.

    Идентификатор, а не путь из журнала: путь там абсолютный и принадлежит дереву
    ОТПРАВИТЕЛЯ (сессия шлёт из своего worktree), а спрашиваем мы про живое дерево,
    в котором нажимает владелец. Ровно на этом расхождении 10.08 нажатие получало
    «карточка исчезла» (цикл #194).
    """
    path = Path(tracker_dir) / f"{card_id}.md"
    if not path.is_file():
        return None, None
    try:
        from spa_core.owner_queue.queue import load_card

        card = load_card(path)
        return (card.status or _UNREADABLE), (card.title or card_id)
    except Exception:  # noqa: BLE001 — нечитаемая карточка = НЕ измерено, не «закрыта»
        return _UNREADABLE, None


def check_pending_owner_decisions(*,
                                  now: Optional[dt.datetime] = None,
                                  data_dir: Optional[str | Path] = None,
                                  tracker_dir: Optional[str | Path] = None) -> dict:
    """Собрать отчёт «путь вверх». Ничего не пишет — только считает."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ddir = Path(data_dir) if data_dir is not None else live_data_dir(_REPO_ROOT)
    tdir = (Path(tracker_dir) if tracker_dir is not None
            else ddir.parent / "nimbalyst-local" / "tracker")

    issues: list[str] = []
    unchecked: list[dict] = []
    status = OK

    # --- остановка ----------------------------------------------------------
    halt_path = ddir / KILL_SWITCH_ACTIVE_FILENAME
    halted = halt_path.is_file()
    halt_since = halt_reason = None
    halt_age_h = None
    if halted:
        try:
            halt_doc = json.loads(halt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            halt_doc = {}
        if isinstance(halt_doc, dict):
            halt_since = halt_doc.get("activated_at")
            halt_reason = halt_doc.get("reason")
        halt_age_h = _hours_since(halt_since, now)

    # --- журнал отправленных решений ---------------------------------------
    # «Файла нет» и «файл испорчен» — РАЗНЫЕ факты, и мерить их одинаково нельзя.
    # Журнала нет ⇒ владельцу ничего не отправляли: это законное состояние чистого
    # дерева (CI, песочница, свежая установка), и объявлять его «не измерено» значило
    # бы жечь предупреждение там, где мерить нечего. Журнал ЕСТЬ, но не читается ⇒
    # очередь вопросов действительно неизмерима — вот это находка.
    journal_path = ddir / PUSH_JOURNAL
    journal_present = journal_path.is_file()
    pushes: Optional[list] = None
    if journal_present:
        try:
            doc = json.loads(journal_path.read_text(encoding="utf-8"))
            raw = doc.get("pushes") if isinstance(doc, dict) else None
            if isinstance(raw, list):
                pushes = raw
        except (OSError, ValueError):
            pushes = None
        if pushes is None:
            unchecked.append({
                "check": "push_journal",
                "reason": f"журнал отправок {PUSH_JOURNAL} есть, но не читается — "
                          f"ждут ли вопросы ответа, НЕ ИЗМЕРЕНО",
            })

    pending: list[dict] = []
    for push in (pushes or []):
        if not isinstance(push, dict):
            continue
        if push.get("choice") is not None:
            continue                       # ответ нажатием получен
        card_id = str(push.get("card_id") or "").strip()
        if not card_id:
            unchecked.append({"check": "push_without_card_id",
                              "reason": "запись журнала без card_id — карточку не найти"})
            continue
        card_status, card_title = _card_status(tdir, card_id)
        if card_status is None:
            unchecked.append({
                "check": f"card_missing:{card_id}",
                "reason": "карточки нет в живом дереве — открыт ли вопрос, НЕ ИЗМЕРЕНО. "
                          "Отсюда «вопрос закрыт, а карточка просто не доехала в прод» "
                          "и «вопрос открыт и потерян» выглядят ОДИНАКОВО, поэтому "
                          "вердикта здесь нет ни в одну сторону; нажатие по такой "
                          "карточке владельцу отвечает «карточка исчезла»",
            })
            continue
        if card_status == _UNREADABLE:
            unchecked.append({
                "check": f"card_unreadable:{card_id}",
                "reason": "карточка есть, но не разобрана — открыт ли вопрос, НЕ ИЗМЕРЕНО "
                          "(пустой статус читался бы как «закрыт» — это fail-OPEN)",
            })
            continue
        if card_status != _OPEN_CARD_STATUS:
            continue                       # вопрос закрыт не кнопкой, а иначе
        age_h = _hours_since(push.get("pushed_at"), now)
        pending.append({
            "card_id": card_id,
            "title": card_title or push.get("title") or card_id,
            "pushed_at": push.get("pushed_at"),
            "age_h": None if age_h is None else round(age_h, 2),
            "buttons": bool(push.get("buttons")),
        })

    pending.sort(key=lambda p: (p["age_h"] is None, -(p["age_h"] or 0.0)))
    oldest = pending[0] if pending else None
    oldest_age_h = oldest["age_h"] if oldest else None

    buttonless = [p for p in pending if not p["buttons"]]

    # --- H1/H2: путь вверх во время остановки -------------------------------
    # Идут ПЕРВЫМИ: `reason` отчёта — это issues[0], и первой строкой обязана
    # стоять остановка, а не второстепенная жалоба на кнопки.
    if halted:
        halt_age_txt = ("возраст НЕ ИЗМЕРЕН" if halt_age_h is None
                        else f"{halt_age_h:.1f}ч")
        if pending:
            age_txt = ("возраст НЕ ИЗМЕРЕН" if oldest_age_h is None
                       else f"{oldest_age_h:.1f}ч")
            # Часы считает ПРОСТОЙ, а не возраст вопроса. Стоит системе именно
            # остановка; вопрос — лишь способ из неё выйти, и заданный минуту
            # назад вопрос не делает 30-часовой простой свежим. Возраст вопроса
            # остаётся вторым сроком (и печатается) — на случай, когда возраст
            # самой остановки не измерен.
            clock_h = halt_age_h if halt_age_h is not None else oldest_age_h
            sev = (CRITICAL if (clock_h is not None
                                and clock_h >= PENDING_CRITICAL_H) else WARNING)
            issues.append(
                f"owner_decision_pending: система ОСТАНОВЛЕНА ({halt_age_txt}, "
                f"{halt_reason or 'причина НЕ ИЗМЕРЕНА'}) и ждёт ЧЕЛОВЕКА: снять может "
                f"только владелец, ему отправлено {len(pending)} вопрос(ов), старейший "
                f"без ответа {age_txt} — «{oldest['title']}»")
            status = _worst(status, sev)
        elif unchecked:
            issues.append(
                f"owner_decision_pending: система ОСТАНОВЛЕНА ({halt_age_txt}), а есть ли "
                f"у неё путь вверх — НЕ ИЗМЕРЕНО ({len(unchecked)} причин(ы) ниже). "
                f"Неизмеримый путь вверх во время остановки не лучше отсутствующего")
            status = _worst(status, CRITICAL)
        else:
            issues.append(
                f"owner_decision_pending: ТУПИК — система ОСТАНОВЛЕНА ({halt_age_txt}, "
                f"{halt_reason or 'причина НЕ ИЗМЕРЕНА'}), а вопроса владельцу, которым её "
                f"можно поднять, НЕ ЗАДАНО НИ ОДНОГО. Путь вниз есть, пути вверх нет")
            status = _worst(status, CRITICAL)
    elif unchecked:
        # Без остановки неизмеримость очереди — предупреждение, не тревога.
        status = _worst(status, WARNING)

    # --- H3: вопрос, на который владелец физически не может ответить --------
    if buttonless:
        names = ", ".join(p["card_id"] for p in buttonless[:3])
        more = f" (и ещё {len(buttonless) - 3})" if len(buttonless) > 3 else ""
        issues.append(
            f"owner_decision_pending: {len(buttonless)} вопрос(ов) владельцу ждут ответа "
            f"БЕЗ КНОПОК — ответить с телефона нельзя: {names}{more}")
        status = _worst(status, WARNING)

    return {
        "generated_at": now.isoformat(),
        "status": status,
        "halted": halted,
        "halt_since": halt_since,
        "halt_age_h": None if halt_age_h is None else round(halt_age_h, 2),
        "halt_reason": halt_reason,
        "journal_present": journal_present,
        "pending_count": len(pending),
        "oldest_pending_age_h": oldest_age_h,
        "buttonless_count": len(buttonless),
        "pending": pending,
        "issues": issues,
        "unchecked": unchecked,
        "reason": (issues[0] if issues else
                   ("остановки нет; вопросов владельцу без ответа: "
                    f"{len(pending)}")),
        "thresholds": {"pending_critical_h": PENDING_CRITICAL_H},
    }


def run(*, now: Optional[dt.datetime] = None,
        data_dir: Optional[str | Path] = None,
        tracker_dir: Optional[str | Path] = None) -> tuple[dict, Path]:
    """Посчитать и записать отчёт атомарно. Возвращает (отчёт, путь)."""
    ddir = Path(data_dir) if data_dir is not None else live_data_dir(_REPO_ROOT)
    doc = check_pending_owner_decisions(now=now, data_dir=ddir, tracker_dir=tracker_dir)
    path = ddir / Path(REPORT_REL).name
    atomic_save(doc, str(path))
    return doc, path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m spa_core.monitoring.owner_decision_pending",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="печатать весь отчёт JSON-ом")
    ap.add_argument("--no-write", action="store_true", help="только посчитать и напечатать")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args(argv)

    if args.no_write:
        doc = check_pending_owner_decisions(data_dir=args.data_dir)
    else:
        doc, _ = run(data_dir=args.data_dir)

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(f"{doc['status']}: {doc['reason']}")
        for line in doc["issues"][1:]:
            print(f"  · {line}")
        for u in doc["unchecked"]:
            print(f"  [НЕ ИЗМЕРЕНО] {u['check']}: {u['reason']}")
    return {OK: 0, WARNING: 1, CRITICAL: 2}[doc["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
