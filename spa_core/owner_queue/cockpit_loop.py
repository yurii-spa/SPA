"""spa_core/owner_queue/cockpit_loop.py — сквозной путь записи из пульта (STUDIO-OS-NEXT-01, ADR-763).

«запись из пульта → карточка → исполнитель → проверенный результат → понятное уведомление» —
из УЖЕ существующих частей. Этот модуль новой системы не заводит: он связывает звенья 3–5, у
которых до сих пор не было общей двери.

  1. Пульт — ``studio_os.mission_intake.submit`` (идемпотентность по ``submission_id``, автор,
     строка о границе полномочий ADR-285). Здесь не трогается.
  2. Приём — ``owner_queue.intake.run_note_intake``: метка ``intake_seen`` и «📥 Создал задачу»
     через долговечные исходящие ``data/intake_outbox.json``. Карточка остаётся ``new``: приём
     НЕ есть исполнение.
  3. Исполнитель — :func:`take_card`: тот же порядок, что предписан циклу (шаг 0b
     ``scripts/check_card_claim.py claim`` → ``orchestrator_queue.py probe`` → ``set-status
     in-progress``), одним вызовом. Повторная доставка (тот же исполнитель) — no-op; другой
     исполнитель получает ОТКАЗ — второго исполнения одной карточки не бывает
     (:class:`TakeRefused`). Карточка в работе без захвата тоже отказывает: кто её исполняет,
     не измерено, а «не измерено» ≠ «свободна» (инв. #2).
  4. Проверка результата — :func:`close_verified`: гоняет СОБСТВЕННУЮ пробу карточки
     (``card_acceptance.run_probe``) и закрывает ТОЛЬКО на ``satisfied``, записав
     ``verified_by_probe``. ``not_satisfied`` / ``unmeasured`` / нет пробы ⇒ карточка остаётся в
     работе, во frontmatter — причина и следующий шаг простыми словами.
  5. Уведомление — то же долговечное ``intake_outbox`` (ключ «карточка#событие») и блок «Мои
     записи» (``mission_control.cockpit_records`` → ``owner_view.my_records``).

Порядок записей — ради падения на ЛЮБОЙ границе:
  * закрытие: отметка ``verified_by_probe`` → ``set_status done`` → исходящие → отметка
    ``owner_notice``. Упали после ``done``, до исходящих ⇒ :func:`sweep_notices` (его зовёт
    каждый прогон приёма) дочистит уведомление. Упали до ``done`` ⇒ карточка в работе, повторный
    :func:`close_verified` перемерит пробу.
  * «не принято»: поля причины → исходящие → ``owner_notice``. Уведомление — одно на СМЕНУ
    состояния (``owner_notice`` хранит последнее отправленное состояние), не на каждый перемер.

Семантика доставки в Telegram — **НЕ МЕНЕЕ ОДНОГО РАЗА**, не «ровно один раз». Падение между
отправкой и вычёркиванием из исходящих, или отправка, ответ на которую потерялся, ПОВТОРИТ
сообщение. Дубль невозможен только в исходящих (ключ заменяет запись) и в решении «слать ли»
(``owner_notice``), но не в чате владельца.

Этот модуль НИКОГДА не ставит ``owner-done``/``owner-accepted`` (инв. #14) и не отвечает за
владельца: он закрывает inbox-карточку агента по её собственной пробе.

# LLM_FORBIDDEN — детерминированный учёт и сверка, никакого суждения модели (инв. #3).
"""
from __future__ import annotations

import html
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

#: Источники карточек пульта (ADR-760). Одна копия — у пульта.
from spa_core.studio_os.mission_intake import COCKPIT_SOURCES

_REPO = Path(__file__).resolve().parents[2]
_CLAIM_GUARD = _REPO / "scripts" / "check_card_claim.py"

#: События уведомлений владельцу; ключ в исходящих — «<карточка>#<событие>».
EVENT_DONE = "done-verified"
EVENT_NOT_ACCEPTED = "not-accepted"

#: Простые слова для владельца: (причина, следующий шаг) по исходу проверки.
REASON_RU = {
    "not_satisfied": ("проверка показала, что результат ещё не достигнут",
                      "исполнитель доделывает работу и запускает проверку снова; от вас ничего не нужно"),
    "unmeasured": ("проверку не удалось провести — результат нечем измерить",
                   "исполнитель чинит саму проверку и перемеряет; от вас ничего не нужно"),
    "no_probe": ("проверка результата не объявлена, поэтому «сделано» поставить нельзя",
                 "исполнитель объявляет проверку и только потом продолжает; от вас ничего не нужно"),
    "executor_failed": ("исполнитель не смог выполнить работу",
                        "карточка остановлена; следующий цикл разберёт причину и возьмёт её снова; "
                        "от вас ничего не нужно"),
}


class TakeRefused(RuntimeError):
    """Карточку нельзя взять в работу: её держит другой исполнитель, захват не измерен, проба
    не годится или карточка не в приёме. Второе исполнение не запускается."""


class CloseRefused(RuntimeError):
    """Закрыть нечего: карточка не в работе (приём ≠ исполнение)."""


# ── frontmatter ─────────────────────────────────────────────────────────────────────────────────────
def _fm(path: Path) -> dict:
    from spa_core.owner_queue import queue as q
    lines, _ = q._split_frontmatter(path.read_text(encoding="utf-8"))
    return q._parse_frontmatter(lines) if lines else {}


def _clean(value: str, limit: int = 300) -> str:
    """Одна строка YAML-значения: без переводов строк и двойных кавычек."""
    return " ".join(str(value).replace('"', "'").split())[:limit]


def _set_fields(path: Path, fields: dict) -> None:
    """Записать/заменить плоские поля frontmatter (тело и прочие поля — байт в байт), атомарно."""
    from spa_core.utils.atomic import atomic_save_text
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    marks = [i for i, ln in enumerate(lines) if ln.strip() == "---"][:2]
    if len(marks) < 2 or marks[0] != 0:
        raise ValueError(f"{path.name}: нет frontmatter")
    end = marks[1]
    for key, value in fields.items():
        row = f'{key}: "{_clean(value)}"\n'
        for i in range(1, end):
            if lines[i].startswith(key + ":"):
                lines[i] = row
                break
        else:
            lines.insert(end, row)
            end += 1
    atomic_save_text("".join(lines), str(path))


def _ts(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_cockpit(fm: dict) -> bool:
    return str(fm.get("source") or "") in COCKPIT_SOURCES


# ── звено 3: исполнитель берёт карточку ─────────────────────────────────────────────────────────────
def _default_claim(path: Path, executor: str) -> None:
    """Шаг 0b протокола — настоящий ``check_card_claim.claim_card`` (якорь сессии меряется из
    окружения; не измерился ⇒ отказ, карточка не взята)."""
    spec = importlib.util.spec_from_file_location("_cockpit_loop_card_claim", _CLAIM_GUARD)
    guard = importlib.util.module_from_spec(spec)   # type: ignore[arg-type]
    spec.loader.exec_module(guard)                  # type: ignore[union-attr]
    guard.claim_card(path.stem, log=guard.DEFAULT_LOG, session=executor, tracker_dir=path.parent)


def _exclusive(path: Path, fm: dict, executor: str, spec: str) -> str:
    """Одно исполнение на карточку, по статусу и захвату В КАРТОЧКЕ. ``"noop"`` — тот же исполнитель
    уже держит её с той же пробой (повторная доставка); ``"take"`` — карточка в приёме; иначе отказ.
    Второй, независимый слой — сам захват шага 0b (:func:`_claim`): он отказывает другому
    исполнителю и тогда, когда эта проверка ошиблась бы (гонка двух взятий из ``new``)."""
    from spa_core.owner_queue.queue import IN_WORK_STATUSES, INTAKE_STATUSES
    status = str(fm.get("status") or "").strip()
    holder = str(fm.get("claimed_by") or "").strip()
    if status in IN_WORK_STATUSES:
        if holder and holder == executor and str(fm.get("acceptance_probe") or "").strip() == spec:
            return "noop"
        raise TakeRefused(
            f"{path.name}: карточка уже в работе ({status}) у "
            f"{holder or 'исполнителя без захвата — кто её исполняет, НЕ ИЗМЕРЕНО'}; "
            f"второе исполнение не запускаю (исполнитель {executor})")
    if status not in INTAKE_STATUSES:
        raise TakeRefused(f"{path.name}: карточка не в приёме (статус {status or 'пуст'}) — брать нечего")
    return "take"


def _claim(path: Path, executor: str, claim: Callable) -> None:
    """Захват шага 0b; любой его отказ — карточка не взята (fail-CLOSED)."""
    try:
        claim(path, executor)
    except Exception as exc:  # noqa: BLE001 — любой отказ шага 0b = карточка не взята
        raise TakeRefused(f"{path.name}: захват не состоялся ({type(exc).__name__}): "
                          f"{str(exc).splitlines()[0] if str(exc) else ''}") from exc


def take_card(card, probe_spec: str, *, executor: str, claim: Optional[Callable] = None) -> dict:
    """Исполнитель берёт ``new``-карточку: захват (шаг 0b) → проба ДО работы → ``in-progress``.

    Возврат ``{"taken": bool, "noop": bool, ...}``. Повтор тем же исполнителем — ``noop``;
    другой исполнитель — :class:`TakeRefused`."""
    from spa_core.monitoring.card_acceptance import validate_spec
    from spa_core.owner_queue.queue import set_acceptance_probe, set_status
    path = Path(card)
    spec = (probe_spec or "").strip()
    why = validate_spec(spec)
    if why is not None:
        raise TakeRefused(f"{path.name}: проба не годится — {why}")
    if not executor or not str(executor).strip():
        raise TakeRefused(f"{path.name}: исполнитель не назван")
    mode = _exclusive(path, _fm(path), executor, spec)
    if mode == "noop":
        return {"taken": False, "noop": True, "card": path.name, "executor": executor, "probe": spec}
    _claim(path, executor, claim or _default_claim)
    set_acceptance_probe(path, spec)
    set_status(path, "in-progress")
    return {"taken": True, "noop": False, "card": path.name, "executor": executor, "probe": spec}


# ── звено 4: проверка результата и закрытие ─────────────────────────────────────────────────────────
def _accepts(verdict: str) -> bool:
    """«Сделано» — ТОЛЬКО на ``satisfied``. ``unmeasured`` никогда не разрешение (инв. #2, #17)."""
    from spa_core.monitoring.card_acceptance import SATISFIED
    return verdict == SATISFIED


def _madrid(ts: str) -> str:
    from spa_core.utils.presentation import fmt_owner_time
    return fmt_owner_time(ts, "ru") or ts


def done_notice_text(title: str, probe: str, verified_at: str) -> str:
    return (f"✅ Ваша запись «{html.escape(title)}» — сделано и проверено пробой "
            f"<code>{html.escape(probe)}</code> ({html.escape(_madrid(verified_at))})")


def not_accepted_notice_text(title: str, reason: str, next_step: str) -> str:
    return (f"🔧 Ваша запись «{html.escape(title)}» — в работе, но ещё не принята: "
            f"{html.escape(reason)}. Следующий шаг: {html.escape(next_step)}.")


def _ensure_done_notice(path: Path, now: datetime, outbox_path) -> bool:
    """Положить в исходящие ОДНО «сделано и проверено» по карточке пульта. True — положено сейчас."""
    from spa_core.owner_queue import intake
    fm = _fm(path)
    if not is_cockpit(fm) or str(fm.get("owner_notice") or "") == EVENT_DONE:
        return False
    probe = str(fm.get("verified_by_probe") or "").strip()
    if not probe or str(fm.get("status") or "").strip() != "done":
        return False
    title = str(fm.get("title") or path.stem)
    intake._outbox_put(f"{path.name}#{EVENT_DONE}",
                       done_notice_text(title, probe, str(fm.get("verified_at") or _ts(now))), now,
                       outbox_path)
    _set_fields(path, {"owner_notice": EVENT_DONE, "owner_notice_at": _ts(now)})
    return True


def _record_not_accepted(path: Path, kind: str, detail: str, now: datetime, outbox_path,
                         next_step: Optional[str] = None) -> bool:
    """Записать причину и следующий шаг; уведомить ОДИН раз на смену состояния. True — уведомление положено."""
    from spa_core.owner_queue import intake
    reason, nxt = REASON_RU[kind]
    if kind == "executor_failed" and detail:
        reason = f"{reason}: {_clean(detail, 160)}"
    nxt = next_step or nxt
    _set_fields(path, {"acceptance_verdict": kind, "acceptance_checked_at": _ts(now),
                       "acceptance_reason": reason, "acceptance_next": nxt,
                       "acceptance_detail": detail or ""})
    fm = _fm(path)
    state = f"{EVENT_NOT_ACCEPTED}:{kind}"
    if not is_cockpit(fm) or str(fm.get("owner_notice") or "") == state:
        return False
    intake._outbox_put(f"{path.name}#{EVENT_NOT_ACCEPTED}",
                       not_accepted_notice_text(str(fm.get("title") or path.stem), reason, nxt), now,
                       outbox_path)
    _set_fields(path, {"owner_notice": state, "owner_notice_at": _ts(now)})
    return True


def close_verified(card, *, now: Optional[datetime] = None, runner: Optional[Callable] = None,
                   outbox_path=None, notify: Optional[Callable] = None, flush: bool = True,
                   closer: str = "cockpit_loop") -> dict:
    """Перемерить СОБСТВЕННУЮ пробу карточки в работе и закрыть её ТОЛЬКО на ``satisfied``.

    ``runner(spec) -> (verdict, detail)`` — по умолчанию ``card_acceptance.run_probe`` с каталогом
    карточки. Возврат: ``{"closed", "verified", "verdict", "detail", "noticed"}``.
    Уведомление владельцу — через долговечные исходящие приёма; доставка не менее одного раза."""
    from spa_core.monitoring.card_acceptance import UNMEASURED, run_probe
    from spa_core.owner_queue import intake
    from spa_core.owner_queue.queue import IN_WORK_STATUSES, set_status
    path = Path(card)
    now = now or datetime.now(timezone.utc)
    fm = _fm(path)
    status = str(fm.get("status") or "").strip()
    out = {"card": path.name, "closed": False, "verified": False, "verdict": None, "detail": None,
           "noticed": False}
    if status == "done":
        out.update(closed=True, verified=bool(str(fm.get("verified_by_probe") or "").strip()),
                   already=True)
        out["noticed"] = _ensure_done_notice(path, now, outbox_path)
    elif status not in IN_WORK_STATUSES:
        raise CloseRefused(f"{path.name}: карточка не в работе (статус {status or 'пуст'}) — "
                           f"приём не есть исполнение, закрывать нечего")
    else:
        spec = str(fm.get("acceptance_probe") or "").strip()
        if not spec:
            verdict, detail, kind = UNMEASURED, "проба приёмки не объявлена", "no_probe"
        else:
            run = runner or (lambda s: run_probe(s, tracker_dir=str(path.parent)))
            try:
                verdict, detail = run(spec)
            except Exception as exc:  # noqa: BLE001 — падение замера = «не измерено», не вердикт
                verdict, detail = UNMEASURED, f"проба упала: {type(exc).__name__}: {exc}"
            kind = verdict if verdict in REASON_RU else "unmeasured"
        out.update(verdict=verdict, detail=detail)
        if spec and _accepts(verdict):
            ts = _ts(now)
            _set_fields(path, {"verified_by_probe": spec, "verified_at": ts,
                               "acceptance_verdict": verdict, "acceptance_checked_at": ts})
            set_status(path, "done", closed_by=f"{closer}/probe",
                       evidence=f"проба {spec}: {verdict} — {_clean(detail, 150)}")
            out.update(closed=True, verified=True)
            out["noticed"] = _ensure_done_notice(path, now, outbox_path)
        else:
            out["noticed"] = _record_not_accepted(path, kind, detail, now, outbox_path)
    if flush:
        intake.flush_outbox(notify=notify, path=outbox_path)
    return out


def report_failure(card, reason: str, *, next_step: Optional[str] = None,
                   now: Optional[datetime] = None, outbox_path=None, notify: Optional[Callable] = None,
                   flush: bool = True) -> dict:
    """Исполнитель не справился: карточка → ``blocked`` с причиной и следующим шагом простыми словами."""
    from spa_core.owner_queue import intake
    from spa_core.owner_queue.queue import set_status
    path = Path(card)
    now = now or datetime.now(timezone.utc)
    if not str(reason or "").strip():
        raise ValueError("причина сбоя обязательна — владелец должен видеть, почему")
    noticed = _record_not_accepted(path, "executor_failed", reason, now, outbox_path, next_step)
    if str(_fm(path).get("status") or "").strip() == "in-progress":
        set_status(path, "blocked")
    if flush:
        intake.flush_outbox(notify=notify, path=outbox_path)
    return {"card": path.name, "blocked": True, "noticed": noticed}


def sweep_notices(*, tracker_dir=None, outbox_path=None, now: Optional[datetime] = None) -> list[str]:
    """Дочистка после падения: закрытые пробой карточки пульта без переданного уведомления."""
    from spa_core.owner_queue import queue as q
    d = Path(tracker_dir) if tracker_dir is not None else Path(q.TRACKER_DIR)
    now = now or datetime.now(timezone.utc)
    queued = []
    if not d.is_dir():
        return queued
    for p in sorted(d.glob("inbox-*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if "verified_by_probe:" not in text or "owner_notice: \"" + EVENT_DONE in text:
            continue
        try:
            if _ensure_done_notice(p, now, outbox_path):
                queued.append(p.name)
        except Exception:  # noqa: BLE001 — одна битая карточка не останавливает дочистку
            continue
    return queued


def main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Сквозной путь записи из пульта: взять / закрыть по пробе")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("take", help="исполнитель берёт new-карточку: захват → проба → in-progress")
    t.add_argument("card")
    t.add_argument("probe")
    t.add_argument("--executor", required=True)
    c = sub.add_parser("close", help="перемерить пробу карточки в работе; закрыть только на satisfied")
    c.add_argument("card")
    f = sub.add_parser("fail", help="исполнитель не справился: blocked + причина и следующий шаг")
    f.add_argument("card")
    f.add_argument("reason")
    f.add_argument("--next-step", default=None)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "take":
            res = take_card(a.card, a.probe, executor=a.executor)
        elif a.cmd == "close":
            res = close_verified(a.card)
        else:
            res = report_failure(a.card, a.reason, next_step=a.next_step)
    except (TakeRefused, CloseRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(res)
    return 0 if a.cmd != "close" or res.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
