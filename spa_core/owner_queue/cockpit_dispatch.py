"""spa_core/owner_queue/cockpit_dispatch.py — запись из пульта получает исполнителя БЕЗ человека.

Дефект, который это закрывает (ARB 16.10, живое демо). Сквозной путь пульта (ADR-763) довозил
запись до карточки ``new`` + ``intake_seen`` — и там она стояла: исполнителя назначил вручную тот
же агент, что отправил запись. Замер прод-трекера 16.10: из 48 переходов ``new → in-progress`` у
inbox-карточек за всё время циклом оркестратора сделано 7, ни одного — для карточки пульта; каждый
цикл с 15.10 начинал промпт с «ГОЛОДАЮЩИЙ ПРИКАЗ … взять ПЕРВОЙ» (``agent_orchestrator.sh``,
``STARVE_PREFIX``), и шаг 1 протокола (разбор ``new``) до записей пульта не доходил. Выбора
исполнителя для записи пульта не было нигде — ни в обёртке, ни в протоколе, ни в коде.

Новой системы здесь нет. Этот модуль — детерминированный шаг ВНУТРИ существующего часового цикла
(``com.spa.orchestrator`` → ``scripts/agent_orchestrator.sh``), вызываемый ДО сессии Claude:

* :func:`dispatch` — самая старая ПРИНЯТАЯ запись пульта (``status: new`` + ``intake_seen``, без
  захвата) берётся через ``cockpit_loop.take_card`` (захват шага 0b → проба → ``in-progress``),
  исполнитель — сессия цикла (``SPA_SESSION_ID``). Проба берётся ТОЛЬКО из объявления: поле
  ``acceptance_probe`` карточки или строка ``проба: <имя[:аргумент]>`` в тексте записи,
  проверенная реестром ``card_acceptance.validate_spec``. Угадывать пробу по смыслу текста
  запрещено (инв. #3 — приёмка без LLM; правило приёмки п. 2 — мерку не выбирает исполнитель).
  Пробы нет ⇒ карточка НЕ берётся и НЕ закрывается: «не принято» с причиной и следующим шагом
  (``cockpit_loop.record_no_probe``), одно уведомление; повторный прогон её не трогает, пока
  кто-нибудь не объявит пробу (тогда она снова кандидат).
* :func:`settle` — ПОСЛЕ сессии: перемерить собственную пробу карточки, взятой этим циклом
  (``close_verified``). «Сделано» ставит только ``satisfied``; иначе ``blocked`` с причиной —
  второго исполнения не бывает ни при каком исходе.
* :func:`rewake` — страховка потерянной побудки приёма: запись пульта без ``intake_seen`` старше
  порога ⇒ ещё раз тронуть ``inbox/.cockpit-wake`` (``mission_intake.wake_intake``). Приём сам
  здесь НЕ запускается — только штатная дверь launchd; повтор безопасен (``intake_seen``).

# LLM_FORBIDDEN — детерминированный выбор и учёт; LLM — только исполнитель в сессии цикла.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from spa_core.owner_queue import cockpit_loop as cl

#: Коды возврата CLI (их читает обёртка цикла).
RC_IDLE, RC_UNMEASURED, RC_TAKEN, RC_NO_PROBE = 0, 2, 3, 4
#: Поле: этот диспетчер уже вынес карточке «пробы нет» (повторный прогон её не трогает).
DISPATCH_FIELD = "dispatch_verdict"
NO_PROBE = "no_probe"
#: Объявление пробы в тексте записи: «проба: имя» / «проба: имя:аргумент» (обратные кавычки — можно).
_PROBE_DECL_RE = re.compile(r"(?im)(?:^|[\s(])(?:проба|probe)\s*:\s*`?([A-Za-z0-9_]+(?::[A-Za-z0-9_.+\-]+)?)`?")
#: Сколько ждёт неразобранная запись пульта, прежде чем побудку приёма повторят.
REWAKE_AFTER = timedelta(minutes=10)

NEXT_NO_PROBE = ("нужна машинная проверка результата: допишите в запись строку «проба: <имя>» "
                 "(список — card_acceptance.PROBES) или агент заведёт новую пробу с контролем в обе "
                 "стороны; до этого запись не исполняется, чтобы «сделано» не было поставлено на слово")
NEXT_AFTER_CYCLE = ("карточка остановлена до разбора; второго автоматического исполнения нет, чтобы "
                    "работа не выполнилась дважды — её снимет с блока и возьмёт заново следующий "
                    "исполнитель, назвав причину")


def _fm(path: Path) -> dict:
    return cl._fm(path)


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return text
    _fm_part, sep, rest = text[3:].partition("\n---")      # закрывающая черта frontmatter
    return rest if sep else ""


def _tracker(tracker_dir) -> Path:
    if tracker_dir is not None:
        return Path(tracker_dir)
    from spa_core.owner_queue import queue as q
    return Path(q.TRACKER_DIR)


def _cockpit_cards(tracker_dir) -> list[tuple[Path, dict]]:
    out = []
    d = _tracker(tracker_dir)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("inbox-*.md")):
        try:
            fm = _fm(p)
        except (OSError, ValueError):
            continue
        if cl.is_cockpit(fm):
            out.append((p, fm))
    return out


def _s(fm: dict, key: str) -> str:
    return str(fm.get(key) or "").strip()


def candidates(tracker_dir=None) -> list[Path]:
    """Принятые приёмом записи пульта, которых ещё никто не взял, — от старой к новой.

    Кандидат: ``status: new`` · ``intake_seen`` есть (приём закончен) · ``claimed_by`` нет · и либо
    диспетчер ещё не выносил «пробы нет», либо проба с тех пор объявлена."""
    rows = []
    for p, fm in _cockpit_cards(tracker_dir):
        if _s(fm, "status") != "new" or not _s(fm, "intake_seen") or _s(fm, "claimed_by"):
            continue
        if _s(fm, DISPATCH_FIELD) == NO_PROBE and not _s(fm, "acceptance_probe"):
            continue
        rows.append((_s(fm, "submitted_at") or _s(fm, "intake_seen"), p.name, p))
    return [p for _t, _n, p in sorted(rows)]


def probe_for(path: Path, fm: Optional[dict] = None) -> tuple[Optional[str], str]:
    """Объявленная проба записи или ``(None, причина)``. Только объявление — никакого угадывания."""
    from spa_core.monitoring.card_acceptance import validate_spec
    fm = fm if fm is not None else _fm(path)
    declared = _s(fm, "acceptance_probe")
    if declared:
        why = validate_spec(declared)
        return (declared, "") if why is None else (None, f"объявленная проба не годится: {why}")
    found = sorted(set(_PROBE_DECL_RE.findall(_body(path))))
    if not found:
        return None, "в записи не объявлена проба результата (строка «проба: <имя>»)"
    if len(found) > 1:
        return None, f"в записи объявлено несколько проб ({', '.join(found)}) — какая из них мерка, неизвестно"
    why = validate_spec(found[0])
    return (found[0], "") if why is None else (None, f"проба «{found[0]}» не годится: {why.split('. Известные')[0]}")


def dispatch(*, executor: str, tracker_dir=None, claim: Optional[Callable] = None,
             now: Optional[datetime] = None, outbox_path=None, notify: Optional[Callable] = None,
             flush: bool = True) -> dict:
    """Один проход выбора: все «пробы нет» — записать; первую проверяемую — взять. Не более ОДНОЙ."""
    now = now or datetime.now(timezone.utc)
    res = {"taken": None, "probe": None, "no_probe": [], "refused": []}
    for path in candidates(tracker_dir):
        spec, why = probe_for(path)
        if spec is None:
            cl._set_fields(path, {DISPATCH_FIELD: NO_PROBE, "dispatch_at": cl._ts(now),
                                  "dispatch_by": executor})
            cl.record_no_probe(path, why, next_step=NEXT_NO_PROBE, now=now, outbox_path=outbox_path,
                               notify=notify, flush=False)
            res["no_probe"].append(path.name)
            continue
        try:
            out = cl.take_card(path, spec, executor=executor, claim=claim)
        except cl.TakeRefused as exc:
            res["refused"].append(f"{path.name}: {exc}")
            continue
        if out.get("taken"):
            res.update(taken=str(path), probe=spec)
            break
    if flush and res["no_probe"]:
        from spa_core.owner_queue import intake
        intake.flush_outbox(notify=notify, path=outbox_path)
    return res


def prompt_prefix(card: str, probe: str, executor: str, repo: str, python: str) -> str:
    cmd = f"cd {repo} && {python} -m spa_core.owner_queue.cockpit_loop"
    return (f"ЗАПИСЬ ИЗ ПУЛЬТА ВЗЯТА ЭТИМ ЦИКЛОМ (исполнитель {executor}; захват шага 0b сделан, проба "
            f"объявлена ДО работы: {probe}). Карточка: {card}. Исполни её ПЕРВОЙ — раньше шага 0a-голод: "
            f"владелец записал её сам, захват уже на тебе, и брошенная она держала бы карточку. Пробу НЕ "
            f"меняй (правило приёмки п. 2), карточку пульта в git НЕ переноси (она живёт в прод-трекере). "
            f"Готово ⇒ `{cmd} close {card}` («сделано» ставит только проба). Не справился ⇒ "
            f"`{cmd} fail {card} \"<причина>\" --next-step \"<следующий шаг>\"`. Ничего не вызовешь — "
            f"обёртка после цикла перемерит пробу сама. Затем продолжай протокол как обычно. ")


def settle(card, *, executor: str, now: Optional[datetime] = None, runner: Optional[Callable] = None,
           outbox_path=None, notify: Optional[Callable] = None) -> dict:
    """После сессии: карточка, взятая ЭТИМ исполнителем и ещё в работе, перемеряется пробой.

    ``satisfied`` ⇒ закрыта с ``verified_by_probe``. Иначе ⇒ ``blocked`` с причиной — одно
    уведомление (ключ «не принято» в исходящих один на карточку). Чужая/закрытая/заблокированная
    карточка не трогается, кроме дочистки уведомления о закрытой."""
    from spa_core.owner_queue import intake
    path = Path(card)
    now = now or datetime.now(timezone.utc)
    fm = _fm(path)
    status, holder = _s(fm, "status"), _s(fm, "claimed_by")
    if status == "done":
        return {"card": path.name, "action": "already-done",
                **cl.close_verified(path, now=now, outbox_path=outbox_path, notify=notify)}
    if status != "in-progress" or holder != executor:
        return {"card": path.name, "action": "untouched", "status": status, "holder": holder}
    r = cl.close_verified(path, now=now, runner=runner, outbox_path=outbox_path, notify=notify,
                          flush=False, closer="cockpit_dispatch")
    if not r.get("closed"):
        cl.report_failure(path, f"цикл исполнителя закончился, а проверка {_s(fm, 'acceptance_probe')} "
                                f"ответила {r.get('verdict')}: {r.get('detail') or ''}",
                          next_step=NEXT_AFTER_CYCLE, now=now, outbox_path=outbox_path, flush=False)
    intake.flush_outbox(notify=notify, path=outbox_path)
    return {"card": path.name, "action": "closed" if r.get("closed") else "blocked", **r}


def stale_unseen(tracker_dir=None, *, now: Optional[datetime] = None,
                 after: timedelta = REWAKE_AFTER) -> list[str]:
    """Записи пульта, которых приём не принял дольше ``after`` (нет ``intake_seen``).

    Время отправки не читается ⇒ запись считается просроченной: лишняя побудка безвредна, а
    молчание о потерянной записи — нет (инв. #17)."""
    now = now or datetime.now(timezone.utc)
    out = []
    for p, fm in _cockpit_cards(tracker_dir):
        if _s(fm, "status") != "new" or _s(fm, "intake_seen"):
            continue
        try:
            at = datetime.strptime(_s(fm, "submitted_at"), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            at = None
        if at is None or now - at >= after:
            out.append(p.name)
    return out


def rewake(tracker_dir=None, notes_dir=None, *, now: Optional[datetime] = None,
           after: timedelta = REWAKE_AFTER) -> dict:
    """Страховка потерянной побудки: просроченные записи есть ⇒ побудить приём ещё раз."""
    from spa_core.studio_os.mission_intake import wake_intake
    stale = stale_unseen(tracker_dir, now=now, after=after)
    woken = wake_intake(notes_dir, now=now) if stale else None
    return {"stale": stale, "woken": woken}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Пульт: автоматический выбор исполнителя и страховка побудки")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dispatch")
    d.add_argument("--executor", required=True)
    d.add_argument("--tracker-dir", default=None)
    d.add_argument("--card-out", default=None, help="файл, куда записать путь взятой карточки")
    d.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    d.add_argument("--python", default=sys.executable)
    s = sub.add_parser("settle")
    s.add_argument("--card", required=True)
    s.add_argument("--executor", required=True)
    w = sub.add_parser("rewake")
    w.add_argument("--tracker-dir", default=None)
    w.add_argument("--notes-dir", default=None)
    w.add_argument("--after-min", type=float, default=REWAKE_AFTER.total_seconds() / 60)
    a = ap.parse_args(argv)
    if a.cmd == "dispatch":
        if not a.executor.strip():
            print("НЕ ИЗМЕРЕНО: исполнитель не назван", file=sys.stderr)
            return RC_UNMEASURED
        res = dispatch(executor=a.executor, tracker_dir=a.tracker_dir)
        print(json.dumps(res, ensure_ascii=False), file=sys.stderr)
        if res["taken"]:
            if a.card_out:
                Path(a.card_out).write_text(res["taken"], encoding="utf-8")
            print(prompt_prefix(res["taken"], res["probe"], a.executor, a.repo, a.python), end="")
            return RC_TAKEN
        if res["refused"]:
            return RC_UNMEASURED
        return RC_NO_PROBE if res["no_probe"] else RC_IDLE
    if a.cmd == "settle":
        print(json.dumps(settle(a.card, executor=a.executor), ensure_ascii=False, default=str))
        return 0
    res = rewake(a.tracker_dir, a.notes_dir, after=timedelta(minutes=a.after_min))
    print(json.dumps(res, ensure_ascii=False))
    if res["stale"]:
        return 1 if res["woken"] else RC_UNMEASURED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
