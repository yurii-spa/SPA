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
    #: Не отправлены, потому что инструкция ссылается на то, чего в системе НЕТ
    #: (``card_instruction_lint``, авария 22.08 — поле ``notify_channel``). Каждая
    #: запись: ``{"card": id, "reason": словами, "missing": [токены]}``.
    lint_blocked: List[dict] = field(default_factory=list)
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

    # Инструкция владельцу — тоже утверждение о системе (авария 22.08: владельца
    # послали читать поле `notify_channel`, которого в коде не было ни разу, и его
    # ответ пришёл неотличимым от настоящего замера). Проверяем ДО потолка прогона:
    # заблокированная карточка не имеет права съедать чужую отправку.
    fresh = _lint_gate(fresh, report)

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


def _lint_gate(fresh, report: FirstDeliveryReport):
    """Отсеять карточки, чью инструкцию владельцу физически нельзя исполнить.

    Право запрещать даёт ТОЛЬКО доказанное отсутствие (см. докстринг
    :mod:`spa_core.owner_queue.card_instruction_lint`). Линтер упал / формулировку не
    разобрать ⇒ карточка едет как раньше: молчащая очередь вопросов дороже той аварии,
    которую линтер лечит. Поэтому исключение здесь — не запрет, а строка в логе.
    """
    try:
        from spa_core.owner_queue.card_instruction_lint import lint_card
    except Exception as exc:  # noqa: BLE001 — линтер недоступен ⇒ доставка как раньше
        log.warning("first_delivery: линтер инструкции недоступен (%s) — не проверяю", exc)
        return fresh
    kept = []
    for card in fresh:
        try:
            res = lint_card(card.path)
        except Exception as exc:  # noqa: BLE001
            log.warning("first_delivery: линтер упал на %s: %s — отправляю как раньше",
                        card.path.stem, exc)
            kept.append(card)
            continue
        if res.blocked:
            report.lint_blocked.append({"card": card.path.stem,
                                        "reason": res.reason_line(),
                                        "missing": [r.token for r in res.missing]})
            log.warning("first_delivery: НЕ отправляю %s — %s",
                        card.path.stem, res.reason_line())
            continue
        kept.append(card)
    return kept


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
    # Заблокированное линтером НАЗЫВАЕТСЯ здесь же. Молчаливое «не отправили» читается
    # как «отправлять было нечего» — ровно та тишина в очереди, от которой заслон и стоит.
    if report.lint_blocked:
        tail += (f" · ⛔ не отправлено (инструкция неисполнима) {len(report.lint_blocked)}: "
                 + ", ".join(f"{b['card']} ({b['reason']})" for b in report.lint_blocked))
    if not report.never_sent:
        return ("новых вопросов владельцу нет — все открытые он уже видел "
                f"(открытых {report.open_total})" + note + tail)
    if report.dry_run:
        return (f"сухой прогон: НИ РАЗУ не отправленных {len(report.never_sent)}, "
                f"к отправке {report.attempted}, ничего не отправлено" + note + tail)
    head = f"впервые доставлено {report.delivered} из {report.attempted}"
    if not report.ok:
        lost = [o.card_id for o in report.outcomes if not o.delivered]
        head += " · ❌ НЕ доехало: " + ", ".join(lost)
    return head + note + tail


# =============================================================================
# carry_to_origin — ОБРАТНОЕ направление: прод → origin (C5, ADR-580)
# =============================================================================
#
# Всё, что выше в этом файле, — origin → прод (первая доставка вопроса владельцу).
# Замер A5_owner_control.md (RM-TRUTH-01, 2026-10-05): обратного пути НЕТ вовсе.
# Оба Telegram-интейка (`owner_queue.intake.create_card`, Bridge → `owner_remote.cli
# confirm`) и писатель ответа владельца (`telegram.owner_decisions.record_choice` →
# `owner_queue.owner_answer`) пишут В ПРОД-ДЕРЕВО (`queue._resolve_tracker_dir` идёт
# по живому дереву, не по worktree сессии). Автосинк прод-дерева возит только
# `spa_core/`·`scripts/`·`tests/` (CLAUDE.md §1) — `nimbalyst-local/tracker/` не
# возит НИКТО. Итог замера: **прод-карточка `owner-decision-utochnenie-po-zametke-
# prikaz-vladeltsa-u`** существует только в проде (создана интейком 2026-10-03);
# **17 закрытий владельца** (`owner-done`/`owner-accepted`) видны только в проде,
# origin всё ещё показывает `ingested`.
#
# `carry_to_origin` ниже — не вторая реализация доставки, а ЗЕРКАЛЬНОЕ направление
# ТОЙ ЖЕ механики: сверка через `owner_queue.origin_view` (git, локальная копия ref,
# без `fetch`), разбор карточек — ЕДИНСТВЕННЫЙ `queue.load_card_text`. Он НИКОГДА:
# * не пишет в прод-дерево (прод-карточки читаются, не трогаются);
# * не пишет в origin и не пушет (`git push`/Contents API здесь нет ни одного вызова);
# * не ставит `owner-done`/`owner-accepted` сам — переносит УЖЕ записанное владельцем
#   закрытие (инвариант #14: он копирует байты существующего файла, не выносит вердикт).
#
# Результат — ПЛАН доставки (список файлов + новое содержимое), который существующий
# пушер (`push_to_github.py`) способен доставить. Вторая доставка не заводится.

#: Карточка — предмет переноса, если объявленный тип ИЛИ префикс имени совпадает с
#: owner-queue (та же проверка, что у остальной очереди — `resend._CARD_TYPE`,
#: `queue._TYPE_BY_PREFIX`). `own-*`/`owner-decision-*` — обе легитимные формы имени.
_LATTICE_CARD_TYPE = "owner-decision"
_LATTICE_PREFIXES = ("own-", "owner-decision-")

#: Решётка статусов C5 (ADR-580): ``needs-owner < owner-answered < ingested <
#: owner-done|owner-accepted``. Перенос двигает карточку ТОЛЬКО вперёд по этой
#: решётке; статус вне словаря или та же позиция с разным содержимым — не ранжируется
#: молча, а назван КОНФЛИКТОМ (см. :func:`lattice_rank`, :func:`carry_to_origin`).
RANK_NEEDS_OWNER = 0
RANK_OWNER_ANSWERED = 1
RANK_INGESTED = 2
RANK_OWNER_CLOSED = 3

#: ``"owner-answered"`` НЕ отдельная строка ``status:`` — это needs-owner-карточка, в
#: которую уже легли поля ответа владельца (:data:`queue.OWNER_ANSWER_FIELDS`:
#: ``owner_choice``/``owner_answer_via``/``owner_answered_at``, пишет бот по нажатию
#: кнопки), а статус ещё не дошёл до ``ingested``/``owner-done``. Ранг этой карточки
#: СТРОГО между needs-owner и ingested: ответ уже есть, закрытие — ещё нет.
_STATUS_RANK = {
    "ingested": RANK_INGESTED,
    "owner-done": RANK_OWNER_CLOSED,
    "owner-accepted": RANK_OWNER_CLOSED,
}


def _is_owner_queue_card(card_id: str, tracker_type: str) -> bool:
    return tracker_type == _LATTICE_CARD_TYPE or card_id.startswith(_LATTICE_PREFIXES)


def lattice_rank(card_text: str) -> Optional[int]:
    """Ранг карточки на решётке C5 — выше ⇒ дальше продвинулась. ``None`` — статус
    решётке не принадлежит (``new``/``backlog``/``in-progress``/…): у такой карточки
    нет общей меры с owner-queue-решёткой, и переносчик обязан сказать это вслух, а
    не угадать порядок (fail-CLOSED, см. вызывающий :func:`carry_to_origin`).

    Карточка не разобралась (битый frontmatter) ⇒ ``None`` по той же причине.
    """
    from spa_core.owner_queue.queue import OWNER_ANSWER_FIELDS, load_card_text

    try:
        card = load_card_text(card_text)
    except ValueError:
        return None
    status = (card.status or "").strip()
    if status == "needs-owner":
        answered = any(str(card.fields.get(f) or "").strip() for f in OWNER_ANSWER_FIELDS)
        return RANK_OWNER_ANSWERED if answered else RANK_NEEDS_OWNER
    return _STATUS_RANK.get(status)


@dataclass
class CarryItem:
    """Одна карточка, которую план переносит прод → origin."""

    card_id: str
    action: str                 # "add" (на origin нет) | "update" (прод продвинулся)
    reason: str
    new_content: str = ""
    prod_rank: Optional[int] = None
    origin_rank: Optional[int] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Содержимое — полезная нагрузка доставки, не строка отчёта: в человеческий
        # дайджест плана оно не едет (может быть килобайты), только в JSON-план.
        return d


@dataclass
class CarryConflict:
    """Карточка, про которую план СОЗНАТЕЛЬНО не решает — порядок не измерен."""

    card_id: str
    reason: str


@dataclass
class CarrierPlan:
    """План переноса owner-queue карточек прод → origin. ТОЛЬКО план: ничего не пишет
    и никуда не пушет (см. модульную справку выше). ``measured=False`` — сверка с
    ``ref`` не состоялась, и список НЕ означает «переносить нечего»."""

    requested_at: str
    ref: str
    ref_sha: str = ""
    measured: bool = False
    reason: str = ""
    scanned: int = 0
    items: List[CarryItem] = field(default_factory=list)
    conflicts: List[CarryConflict] = field(default_factory=list)
    #: Карточки, идентичные байт-в-байт на обеих сторонах — переносить нечего, и это
    #: НАЗВАНО отдельно, а не растворено молчанием среди конфликтов.
    unchanged: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _scan_prod_owner_queue_cards(tracker_dir: Path,
                                 conflicts: List[CarryConflict]) -> List[tuple]:
    """[(card_id, текст)] owner-queue карточек прод-дерева. Нечитаемый файл — КОНФЛИКТ,
    а не пропуск: молча выпавшая карточка и есть тот самый непроверенный перенос."""
    from spa_core.owner_queue.queue import load_card_text

    out: List[tuple] = []
    for path in sorted(tracker_dir.glob("*.md")):
        if path.stem.startswith("_"):             # `_BOARD.md` — производный индекс, не карточка
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            conflicts.append(CarryConflict(path.stem, f"файл не прочитан: {exc}"))
            continue
        try:
            card = load_card_text(text, path.name)
        except ValueError as exc:
            conflicts.append(CarryConflict(path.stem, f"карточка не разобралась: {exc}"))
            continue
        if not _is_owner_queue_card(path.stem, card.tracker_type):
            continue
        out.append((path.stem, text))
    return out


def carry_to_origin(prod_tracker_dir: str | Path, *, ref: str = ORIGIN_REF,
                    now: Optional[datetime] = None) -> CarrierPlan:
    """План переноса owner-queue карточек прод-дерева на ``origin`` — ТОЛЬКО план.

    Читает прод-дерево (``prod_tracker_dir``) и локальную копию ``ref`` (через
    ``owner_queue.origin_view`` — тот же git без сети, что и у остальной очереди) и
    решает по решётке C5 (:func:`lattice_rank`), какие карточки на origin ОТСТАЛИ.

    Три исхода на карточку:

    * **add** — карточки на ``ref`` нет вовсе (прод завёл её сам, интейком или ботом);
    * **update** — обе стороны знают карточку, но прод продвинулся дальше по решётке
      (например, владелец ответил в Telegram, а на origin статус ещё ``needs-owner``);
    * **конфликт** — ранг не определён (статус вне решётки) ИЛИ ранг одинаковый, а
      содержимое разное: перенос НЕ угадывает, кто прав, он называет карточку.

    Карточка, где прод ОТСТАЁТ (``prod_rank < origin_rank``), в план не попадает
    вовсе — переносить НАЗАД запрещено (C5): origin уже знает больше, чем прод.

    Ничего не пишет ни в прод-дерево, ни в origin, никуда не пушет. Инвариант #14 не
    трогается: если прод несёт ``owner-done``/``owner-accepted`` — это уже ЗАПИСАННЫЙ
    владельцем вердикт (бот пишет `closed_by`/`evidence`, ADR-146), план лишь копирует
    байты существующего файла на доставку, не выносит вердикт сам.

    ``measured=False`` в возвращённом плане означает «сверка с ``ref`` не состоялась»
    — пустой ``items``/``conflicts`` тогда НЕ значит «переносить нечего».
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    tdir = Path(prod_tracker_dir)
    plan = CarrierPlan(requested_at=stamp, ref=ref)
    if not tdir.is_dir():
        plan.reason = f"каталог очереди прод-дерева не существует: {tdir}"
        return plan

    cards = _scan_prod_owner_queue_cards(tdir, plan.conflicts)
    plan.scanned = len(cards)
    if not cards:
        plan.measured = True
        return plan

    from spa_core.owner_queue.origin_view import Unmeasured, card_sources

    try:
        origin_texts, sha = card_sources(tdir, [cid for cid, _ in cards], ref=ref)
    except Unmeasured as exc:
        plan.reason = f"очередь на {ref} не прочитана: {exc}"
        return plan
    except Exception as exc:  # noqa: BLE001 — неожиданное тоже «не измерено», не «пусто»
        plan.reason = f"сверка с {ref} не выполнена: {exc}"
        return plan

    plan.measured = True
    plan.ref_sha = sha
    for card_id, prod_text in cards:
        origin_text = origin_texts.get(card_id)
        if origin_text is None:
            plan.items.append(CarryItem(
                card_id, "add", reason=f"карточки нет на {ref} — перенести целиком",
                new_content=prod_text))
            continue
        if origin_text == prod_text:
            plan.unchanged.append(card_id)
            continue
        prod_rank = lattice_rank(prod_text)
        origin_rank = lattice_rank(origin_text)
        if prod_rank is None or origin_rank is None:
            plan.conflicts.append(CarryConflict(
                card_id,
                f"статус вне решётки C5 (прод={prod_rank!r}, {ref}={origin_rank!r}) — "
                f"порядок не определён, перенос не угадывает"))
            continue
        if prod_rank > origin_rank:
            plan.items.append(CarryItem(
                card_id, "update",
                reason=f"прод продвинулся дальше по решётке ({prod_rank} > {origin_rank})",
                new_content=prod_text, prod_rank=prod_rank, origin_rank=origin_rank))
        elif prod_rank < origin_rank:
            # origin дальше — переносить НАЗАД запрещено (C5). Не конфликт: порядок
            # ИЗМЕРЕН, он просто говорит «эту карточку несёт другое направление».
            continue
        else:
            plan.conflicts.append(CarryConflict(
                card_id, f"тот же ранг решётки ({prod_rank}), но РАЗНОЕ содержимое — "
                        f"какая копия верна, НЕ ИЗМЕРЕНО"))
    return plan


def carrier_summary_line(plan: CarrierPlan) -> str:
    """Одна строка для человека. Конфликты НАЗЫВАЮТСЯ — план не угадывает за них."""
    if not plan.measured:
        return f"план НЕ построен ({plan.reason or 'причина не названа'})"
    bits = [f"просмотрено {plan.scanned}", f"к переносу {len(plan.items)}"]
    if plan.conflicts:
        bits.append("⚠️ конфликтов " + str(len(plan.conflicts)) + ": "
                    + ", ".join(c.card_id for c in plan.conflicts))
    if plan.unchanged:
        bits.append(f"без изменений {len(plan.unchanged)}")
    return " · ".join(bits)


def _carry_to_origin_main(argv=None) -> int:
    """CLI: напечатать план (по умолчанию) либо выложить его файлы в каталог для пушера.

    НИКОГДА не пишет в прод-дерево и не трогает git/сеть сам — ``--write`` кладёт
    файлы плана в НАЗВАННЫЙ каталог (не прод, не origin), откуда их доставляет
    СУЩЕСТВУЮЩИЙ пушер (``push_to_github.py --files …``). Вторая доставка здесь не
    заводится намеренно (см. модульную справку).
    """
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description=(
        "C5/ADR-580: план переноса owner-queue карточек прод -> origin (ТОЛЬКО план)"))
    ap.add_argument("--tracker-dir", default=None,
                    help="каталог очереди прод-дерева (умолчание — живое дерево)")
    ap.add_argument("--ref", default=ORIGIN_REF)
    ap.add_argument("--write", default=None,
                    help="выложить файлы плана в этот каталог (НЕ прод, НЕ origin)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    tracker_dir = args.tracker_dir
    if tracker_dir is None:
        from spa_core.owner_queue.queue import TRACKER_DIR

        tracker_dir = str(TRACKER_DIR)

    plan = carry_to_origin(tracker_dir, ref=args.ref)

    if args.write and plan.measured:
        outdir = Path(args.write)
        outdir.mkdir(parents=True, exist_ok=True)
        for item in plan.items:
            (outdir / f"{item.card_id}.md").write_text(item.new_content, encoding="utf-8")

    if args.json:
        print(_json.dumps(plan.to_dict(), ensure_ascii=False, indent=1))
    else:
        print(carrier_summary_line(plan))
    return 0 if plan.measured else 2


if __name__ == "__main__":
    raise SystemExit(_carry_to_origin_main())
