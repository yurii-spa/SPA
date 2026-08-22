#!/usr/bin/env python3
"""ПЕРВАЯ доставка вопроса владельцу — рутинная, а не по просьбе.

Зачем понадобился отдельный модуль рядом с ``resend``
------------------------------------------------------------------------------
Цикл #330 починил ОТПРАВИТЕЛЯ: :func:`spa_core.owner_queue.resend.open_questions`
читает обе стороны очереди (карточки дерева **и** карточки на ``origin/main`` через
``origin_view``), выкладывает origin-only карточку файлом и умеет её отправить.
Механика верна, и здесь она переиспользуется целиком — второй реализации того же
правила не заводится.

Чего #330 не закрыл и что вскрылось замером 22.08 (цикл #345): **у этого пути нет ни
одного вызывающего.** ``resend-open`` существует ровно как подкоманда CLI
(``scripts/orchestrator_queue.py``) — ни plist, ни обёртки, ни шага цикла. Значит
вопрос, попавший на ``origin`` **не через живую сессию** (merge ветки, PR, другая
машина), доезжает до владельца только тогда, когда кто-то руками наберёт команду.

Замер, из которого родился модуль (``data/owner_decision_pending.json`` @ 12:52Z):

```
queue_gap_count: 3 — все три `delivered: false`, НИ РАЗУ не отправлены
  owner-decision-kesh-sistemy-tot-zhe-usdc-zamer-pokazal    (Protection Lab, PR #30)
  owner-decision-maple-15-knigi-defolt-prihodit-bez-predu   (PR #30; хвост −$12 000)
  owner-decision-test-prizrak-ne-rozhdaetsya                (наш собственный тест-зонд)
```

Почему нельзя было просто позвать ``resend-open``
------------------------------------------------------------------------------
``resend`` — инструмент ПЕРЕсылки по просьбе владельца (решение 20.08, вариант 2). Он
ставит ``owner_requested=True``, а этот флаг снимает дедуп и анти-шторм **всему
набору**. Позвать его ради одного нового вопроса значит прислать владельцу заново всё
открытое — ровно тот поток одинаковых сообщений, на который он жаловался трижды
(#215/#217/#228, ADR-084).

Поэтому здесь ПЕРВАЯ отправка, и она устроена наоборот:

* ``owner_requested=False`` — дедуп, анти-шторм и лимит потока остаются включёнными
  побайтово; ни один заслон не ослаблен;
* берутся ТОЛЬКО карточки, у которых в журнале отправок **нет записи вовсе**
  (``_push_by_card_id`` вернул ``None``). «Отправляли, и не доехало» — другой вид: он
  НАЗЫВАЕТСЯ в отчёте (``attempted_before``) и не досылается. Повтор недоставленного —
  работа анти-шторма, а не этого модуля, и смешивать их значит завести второй,
  неподотчётный путь повторов;
* потолок за прогон (:data:`FIRST_DELIVERY_PER_RUN`). Восемь ПЕРВЫХ отправок подряд —
  это и есть шторм. Остаток не усекается молча: он назван поимённо в ``deferred`` и в
  строке отчёта, потому что молчаливое усечение читается как «доставили всё»;
* «очередь ``origin`` прочитать не удалось» ⇒ ``measured=False`` с причиной словами и
  ненулевой код возврата: «вопросов нет» и «вопросов не видно» — разные утверждения, и
  именно их неразличимость держала восемь вопросов владельца невидимыми (#330).

Что модуль сознательно НЕ делает
------------------------------------------------------------------------------
Не закрывает и не редактирует карточки (инв. #14), не судит о содержании вопроса и не
выдумывает владельцу вариантов (ADR-075 — этим занят ``owner_decisions``), не трогает
``data/`` кроме собственного отчёта.

Только stdlib. LLM здесь запрещён — это доставка, не суждение.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from spa_core.owner_queue.resend import ORIGIN_REF, PACE_S, open_questions

log = logging.getLogger(__name__)

#: Сколько ПЕРВЫХ отправок разрешено за один прогон. Двойка — не про технику, а про
#: владельца: он трижды жаловался на поток сообщений, и лечить это потоком нельзя.
#: Очередь всё равно рассосётся — цикл ходит несколько раз в день, а остаток каждый раз
#: назван поимённо, так что «отложено» видно, а не тихо потеряно.
FIRST_DELIVERY_PER_RUN = 2

#: Куда кладётся отчёт: без него «доставил» — утверждение, а не измерение.
REPORT_NAME = "owner_questions_first_delivery.json"


@dataclass
class FirstDeliveryOutcome:
    """Судьба ОДНОЙ первой отправки. ``delivered`` измерено по журналу, не предположено."""

    card_id: str
    title: str
    delivered: bool
    reason: str = ""
    buttons: bool = False
    message_id: Optional[int] = None


@dataclass
class FirstDeliveryReport:
    requested_at: str
    #: Открытых вопросов всего (обе стороны очереди).
    open_total: int = 0
    #: Из них НИ РАЗУ не отправленных — предмет этого модуля.
    never_sent: List[str] = field(default_factory=list)
    #: Уже известных отправителю (запись в журнале есть) — сюда мы не лезем.
    attempted_before: List[str] = field(default_factory=list)
    #: Не влезли в потолок прогона. Названы, а не усечены молча.
    deferred: List[str] = field(default_factory=list)
    attempted: int = 0
    delivered: int = 0
    failed: int = 0
    dry_run: bool = False
    limit: Optional[int] = None
    outcomes: List[FirstDeliveryOutcome] = field(default_factory=list)
    #: Судьба сверки очереди с ``origin/main`` — см. ``resend.OpenQueue.origin``.
    origin: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Все ли ПОПЫТАННЫЕ отправки доехали. О полноте очереди молчит намеренно —
        полнота живёт отдельным названным полем (:attr:`queue_measured`)."""
        return self.failed == 0

    @property
    def queue_measured(self) -> bool:
        """Сверена ли очередь с ``origin/main``. False ⇒ список мог быть НЕПОЛОН."""
        return bool(self.origin.get("measured"))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        d["queue_measured"] = self.queue_measured
        return d


def _never_sent(card_path: Path, *, state_path=None) -> bool:
    """Есть ли в журнале отправок хоть одна запись об этой карточке.

    Отсутствие записи — единственное, что мы считаем «владелец не видел». Запись с
    ``delivered: false`` сюда НЕ попадает: это «пробовали и не доехало», и повторять её
    обязан анти-шторм со своим окном, а не рутинная первая доставка.

    Измерение упало ⇒ считаем, что запись ЕСТЬ (не отправляем): непомеренное не даёт
    права слать владельцу — fail-CLOSED в сторону молчания, а молчание здесь названо
    в отчёте.
    """
    try:
        from spa_core.telegram import owner_decisions

        rec = owner_decisions._push_by_card_id(card_path.stem, state_path=state_path)
        return rec is None
    except Exception as exc:  # noqa: BLE001 — измерение не даёт права слать
        log.warning("_never_sent(%s): %s — считаю отправленным", card_path.stem, exc)
        return False


def deliver_new_questions(
    *,
    tracker_dir: Optional[str | Path] = None,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    sleep: Callable[[float], None] = time.sleep,
    pace_s: float = PACE_S,
    limit: Optional[int] = FIRST_DELIVERY_PER_RUN,
    state_path: Optional[str | Path] = None,
    report_path: Optional[str | Path] = None,
    ref: str = ORIGIN_REF,
) -> FirstDeliveryReport:
    """Отправить владельцу вопросы, которых он НЕ ВИДЕЛ НИ РАЗУ. По одному, с кнопками.

    ``dry_run=True`` — собрать список и тексты, НО НЕ ОТПРАВЛЯТЬ и не трогать живое
    состояние (нажимать в сухом прогоне нечего, регистрировать пуш нельзя).

    ``sleep``/``pace_s`` — темп инъектируем: время здесь ВХОД, а не окружение, иначе
    тест обязан ждать по-настоящему (тот же принцип, что в правиле про фиксированные
    даты, ``.claude/rules/deployment.md``).
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    work = Path(tempfile.mkdtemp(prefix="spa_first_delivery_"))
    try:
        return _deliver(stamp, work, tracker_dir=tracker_dir, dry_run=dry_run,
                        sleep=sleep, pace_s=pace_s, limit=limit,
                        state_path=state_path, report_path=report_path, ref=ref)
    finally:
        # Каталог нужен только ДО отправки: `notify_needs_owner` уже перенёс карточку в
        # живое дерево (`materialize_card`), и ответ владельца будет писаться туда.
        shutil.rmtree(work, ignore_errors=True)


def _deliver(stamp, work, *, tracker_dir, dry_run, sleep, pace_s, limit,
             state_path, report_path, ref) -> FirstDeliveryReport:
    queue = open_questions(tracker_dir=tracker_dir, ref=ref, workdir=work)
    report = FirstDeliveryReport(requested_at=stamp, open_total=len(queue.cards),
                                 dry_run=dry_run, limit=limit, origin=queue.origin)

    fresh = []
    for card in queue.cards:
        if _never_sent(card.path, state_path=state_path):
            fresh.append(card)
            report.never_sent.append(card.path.stem)
        else:
            report.attempted_before.append(card.path.stem)

    take = fresh if limit is None else fresh[:max(0, int(limit))]
    report.deferred = [c.path.stem for c in fresh[len(take):]]
    report.attempted = len(take)

    from spa_core.owner_queue.notify import notify_needs_owner
    from spa_core.owner_queue.resend import _measure_delivery

    for i, card in enumerate(take):
        card_id = card.path.stem
        title = card.title or card_id
        if dry_run:
            try:
                notify_needs_owner(card.path, dry_run=True)
                report.outcomes.append(FirstDeliveryOutcome(card_id, title, False,
                                                            reason="dry_run"))
            except Exception as exc:  # noqa: BLE001
                report.outcomes.append(FirstDeliveryOutcome(card_id, title, False,
                                                            reason=f"build_failed: {exc}"))
            continue
        try:
            # owner_requested НЕ передаём: это ПЕРВАЯ отправка, и все заслоны обязаны
            # стоять. Флаг существует ровно для просьбы владельца прислать заново.
            notify_needs_owner(card.path)
        except Exception as exc:  # noqa: BLE001 — одна упавшая отправка не рвёт остальные
            log.warning("first_delivery: отправка %s упала: %s", card_id, exc)
            report.outcomes.append(FirstDeliveryOutcome(card_id, title, False,
                                                        reason=f"send_raised: {exc}"))
            continue
        delivered, buttons, mid = _measure_delivery(card.path, state_path=state_path)
        report.outcomes.append(FirstDeliveryOutcome(
            card_id, title, delivered,
            reason="" if delivered else "не доставлено (журнал отправок не подтвердил)",
            buttons=buttons, message_id=mid))
        if i + 1 < len(take) and pace_s > 0:
            sleep(pace_s)

    report.delivered = sum(1 for o in report.outcomes if o.delivered)
    report.failed = sum(1 for o in report.outcomes if not o.delivered and not dry_run)
    _write_report(report, report_path)
    return report


def _write_report(report: FirstDeliveryReport,
                  report_path: Optional[str | Path] = None) -> None:
    """Отчёт на диск. Никогда не бросает — наблюдение не важнее самой доставки."""
    try:
        from spa_core.utils.atomic import atomic_save
        from spa_core.utils.live_paths import live_data_dir

        path = Path(report_path) if report_path else Path(live_data_dir()) / REPORT_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(report.to_dict(), str(path))
    except Exception as exc:  # noqa: BLE001
        log.warning("_write_report: %s", exc)


def _queue_note(report: FirstDeliveryReport) -> str:
    """Хвост про ПОЛНОТУ очереди. Пусто — только когда сверка состоялась и молчать не о чем."""
    origin = report.origin or {}
    if not origin.get("measured"):
        reason = origin.get("reason") or "причина не названа"
        return (f" · ⚠️ очередь с {origin.get('ref', ORIGIN_REF)} НЕ СВЕРЕНА "
                f"({reason}) — список мог быть НЕПОЛОН")
    note = ""
    only = int(origin.get("origin_only") or 0)
    if only:
        note += f" · из открытых {only} есть только на {origin.get('ref', ORIGIN_REF)}"
    if origin.get("unreadable"):
        note += " · ⚠️ не прочитаны с ref: " + ", ".join(origin["unreadable"])
    return note


def summary_line(report: FirstDeliveryReport) -> str:
    """Одна строка для человека. Отложенное и недоставленное НАЗЫВАЕТСЯ, а не прячется."""
    note = _queue_note(report)
    tail = ""
    if report.deferred:
        tail = (f" · отложено до следующего прогона {len(report.deferred)}: "
                + ", ".join(report.deferred))
    if not report.never_sent:
        return ("новых вопросов владельцу нет — все открытые он уже видел "
                f"(открытых {report.open_total})" + note)
    if report.dry_run:
        return (f"сухой прогон: НИ РАЗУ не отправленных {len(report.never_sent)}, "
                f"к отправке {report.attempted}, ничего не отправлено" + note + tail)
    head = f"впервые доставлено {report.delivered} из {report.attempted}"
    if not report.ok:
        lost = [o.card_id for o in report.outcomes if not o.delivered]
        head += " · ❌ НЕ доехало: " + ", ".join(lost)
    return head + note + tail
