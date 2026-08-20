#!/usr/bin/env python3
"""Переслать владельцу ОТКРЫТЫЕ вопросы заново — по одному, с кнопками.

Исполнение решения владельца от 2026-08-20 11:04Z (карточка
``owner-decision-tvoi-otvet-otvet-1-segodnya-ne-primenils``, **вариант 2**):
*«пришлите вопросы заново, по одному»*.

Почему для этого понадобился отдельный модуль, а не цикл `for` по карточкам
------------------------------------------------------------------------------
Между нами и владельцем стоят три заслона, и каждый из них по отдельности прав, а
вместе они гасят ровно ту рассылку, которую владелец попросил:

1. **Дедуп** (``guard_outbound``, окно 30 мин) — текст вопроса побуквенно тот же, что
   уходил вчера ⇒ второе сообщение молча не уезжает.
2. **Анти-шторм** (``owner_decisions.throttle_state``, окно 6 ч, потолок 5 посылок) —
   та же карточка без ответа не уходит повторно.
3. **Лимит потока** (12 сообщений в минуту НА ВСЕХ отправителей, включая агентов) —
   пачка вопросов подряд упирается в него, и хвост гаснет БЕЗ СЛЕДА.

Первые два снимаются здесь — но не «вообще», а ровно потому, что владелец попросил
(``owner_requested=True``, тот же принцип, что ``solicited``: спросил — ответить
обязаны). Третий не снимается ничем: он защищает канал, и обойти его значило бы
получить те же потерянные сообщения, только молча. Вместо обхода — темп
(:data:`RESEND_PER_MIN`) с запасом под чужих отправителей.

Доставка не предполагается, а ИЗМЕРЯЕТСЯ: уехало ли сообщение, видно только по ответу
Telegram API (``message_id``), который ``notify_needs_owner`` кладёт в журнал через
``mark_send_outcome``. Отчёт называет каждое недоставленное поимённо — молчаливая
частичная рассылка неотличима от полной, и именно на этом владелец уже терял вопросы
(#309, #229).

**Счёт открытых вопросов берётся по СТАТУСУ карточек**, а не по журналу отправок: журнал
знает только те ответы, что пришли через него, и его «открытые» лишь растут (замер 20.08 —
18 «ждущих» записей, из них 3 живых). Прислать владельцу 14 вопросов, 11 из которых
закрыты, — это ровно тот поток одинаковых сообщений, на который он жаловался дважды.

Только stdlib. LLM здесь запрещён (это доставка, не суждение).
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

#: Темп рассылки: половина общего лимита (12/мин), вторая половина оставлена агентам —
#: занять весь канал под свою рассылку значит уронить чужие тревоги.
RESEND_PER_MIN = 6
PACE_S = 60.0 / RESEND_PER_MIN

#: Куда кладётся отчёт: без него «переслал» — это утверждение, а не измерение.
REPORT_NAME = "owner_questions_resend.json"


@dataclass
class ResendOutcome:
    """Судьба ОДНОГО пересланного вопроса. ``delivered`` — измерено, не предположено."""

    card_id: str
    title: str
    delivered: bool
    reason: str = ""
    buttons: bool = False
    message_id: Optional[int] = None


@dataclass
class ResendReport:
    requested_at: str
    total: int = 0
    delivered: int = 0
    failed: int = 0
    dry_run: bool = False
    outcomes: List[ResendOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Все ли вопросы доехали. Частичная рассылка — НЕ успех."""
        return self.failed == 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def open_questions(*, tracker_dir: Optional[str | Path] = None) -> List:
    """Карточки, которые ПРЯМО СЕЙЧАС спрашивают владельца (`needs-owner`).

    Источник правды — статус карточки в трекере, а не журнал отправок: см. модульную
    справку. Никогда не бросает — пустой список честнее падения посреди рассылки.
    """
    try:
        from spa_core.owner_queue.queue import list_cards

        kwargs = {"tracker_type": "owner-decision", "status": "needs-owner"}
        if tracker_dir is not None:
            kwargs["tracker_dir"] = tracker_dir
        return list(list_cards(**kwargs))
    except Exception as exc:  # noqa: BLE001
        log.warning("open_questions: не смог прочитать очередь (%s)", exc)
        return []


def _measure_delivery(card_path: Path, *, state_path=None) -> tuple[bool, bool, Optional[int]]:
    """``(доставлено, были_ли_кнопки, message_id)`` по журналу отправок.

    Читаем ИСХОД (`delivered`, проставленный `mark_send_outcome` из ответа Telegram),
    а не намерение (`buttons`, которое ставится ДО отправки) — на этой разнице уже
    стоял класс «журнал утверждает успех, владелец ничего не получил» (#309).
    Записи нет ⇒ считаем НЕдоставленным: отсутствие измерения не есть успех.
    """
    try:
        from spa_core.telegram import owner_decisions

        rec = owner_decisions._push_by_card_id(card_path.stem, state_path=state_path)
        if not isinstance(rec, dict):
            return False, False, None
        ids = rec.get("message_ids")
        mid = None
        if isinstance(ids, list) and ids:
            try:
                mid = int(ids[-1])
            except (TypeError, ValueError):
                mid = None
        return bool(rec.get("delivered")), bool(rec.get("buttons")), mid
    except Exception as exc:  # noqa: BLE001 — измерение не роняет рассылку
        log.warning("_measure_delivery: %s", exc)
        return False, False, None


def resend_open_questions(
    *,
    tracker_dir: Optional[str | Path] = None,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    sleep: Callable[[float], None] = time.sleep,
    pace_s: float = PACE_S,
    limit: Optional[int] = None,
    state_path: Optional[str | Path] = None,
    report_path: Optional[str | Path] = None,
) -> ResendReport:
    """Переслать владельцу все открытые вопросы — по одному сообщению, с кнопками.

    ``dry_run=True`` — собрать список и тексты, НО НЕ ОТПРАВЛЯТЬ и не трогать живое
    состояние (сухой прогон не имеет права регистрировать пуш: нажимать нечего).

    ``sleep``/``pace_s`` — темп инъектируем, потому что иначе тест этой функции обязан
    ждать по-настоящему; время здесь ВХОД, а не окружение (правило `.claude/rules/
    deployment.md` про фиксированные даты — тот же принцип).
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    cards = open_questions(tracker_dir=tracker_dir)
    if limit is not None:
        cards = cards[:limit]
    report = ResendReport(requested_at=stamp, total=len(cards), dry_run=dry_run)

    from spa_core.owner_queue.notify import notify_needs_owner

    for i, card in enumerate(cards):
        card_id = card.path.stem
        title = card.title or card_id
        if dry_run:
            try:
                notify_needs_owner(card.path, dry_run=True)
                report.outcomes.append(ResendOutcome(card_id, title, False,
                                                     reason="dry_run"))
            except Exception as exc:  # noqa: BLE001
                report.outcomes.append(ResendOutcome(card_id, title, False,
                                                     reason=f"build_failed: {exc}"))
            continue
        try:
            notify_needs_owner(card.path, owner_requested=True)
        except Exception as exc:  # noqa: BLE001 — одна упавшая отправка не рвёт рассылку
            log.warning("resend: отправка %s упала: %s", card_id, exc)
            report.outcomes.append(ResendOutcome(card_id, title, False,
                                                 reason=f"send_raised: {exc}"))
            continue
        delivered, buttons, mid = _measure_delivery(card.path, state_path=state_path)
        report.outcomes.append(ResendOutcome(
            card_id, title, delivered,
            reason="" if delivered else "не доставлено (журнал отправок не подтвердил)",
            buttons=buttons, message_id=mid))
        # Темп держим МЕЖДУ сообщениями, а не после последнего: лишняя пауза в конце
        # ничего не защищает, а рассылку удлиняет.
        if i + 1 < len(cards) and pace_s > 0:
            sleep(pace_s)

    report.delivered = sum(1 for o in report.outcomes if o.delivered)
    report.failed = sum(1 for o in report.outcomes if not o.delivered and not dry_run)
    _write_report(report, report_path)
    return report


def _write_report(report: ResendReport, report_path: Optional[str | Path] = None) -> None:
    """Отчёт на диск. Никогда не бросает — наблюдение не важнее самой рассылки."""
    try:
        from spa_core.utils.atomic import atomic_save
        from spa_core.utils.live_paths import live_data_dir

        path = Path(report_path) if report_path else Path(live_data_dir()) / REPORT_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(report.to_dict(), str(path))
    except Exception as exc:  # noqa: BLE001
        log.warning("_write_report: %s", exc)


def summary_line(report: ResendReport) -> str:
    """Одна строка для человека. Недоставленное НАЗЫВАЕТСЯ, а не прячется в счёт."""
    if report.total == 0:
        return "открытых вопросов владельцу нет — пересылать нечего"
    if report.dry_run:
        return f"сухой прогон: открытых вопросов {report.total}, ничего не отправлено"
    head = f"переслано {report.delivered} из {report.total}"
    if report.ok:
        return head
    lost = ", ".join(o.card_id for o in report.outcomes if not o.delivered)
    return f"{head}; НЕ ДОСТАВЛЕНО {report.failed}: {lost}"
