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

**Очередь читается и с `origin/main`, а не только с диска дерева запуска** (21.08, цикл
#330). Автосинк прод-дерева возит только ``spa_core/``·``scripts/``·``tests/`` — каталог
``nimbalyst-local/tracker/`` не возит НИКТО (#193), поэтому вопрос, заведённый сессией в
своём worktree и запушенный на `origin`, для отправителя из прода просто НЕ СУЩЕСТВУЕТ.
Замер 21.08 (`data/owner_decision_pending.json`): восемь вопросов `needs-owner`, все с
``delivered: false``, заведены 18–19.08 — владелец не видел их ни разу, четвёртый день,
а `undelivered_count` отправителя показывал **0**. Сторож (`owner_decision_pending`) их
называл поимённо и был прав; слеп был именно отправитель. Механика сверки переиспользуется
(`owner_queue.origin_view`), второй реализации того же правила здесь нет.

Карточка, живущая только на `origin`, **материализуется файлом** перед отправкой: весь путь
ответа владельца (сообщение → кнопка → ``set_status``) работает с ФАЙЛОМ, и без этого шага
вопрос уехал бы кнопкой в никуда (класс «кнопка декоративна», замер 10.08 в
``owner_decisions.materialize_card``). Имя файла — ``<card_id>.md``, потому что ключ
журнала отправок и callback кнопки — это ``path.stem``.

«Очередь `origin` прочитать не удалось» — отдельный, НАЗВАННЫЙ исход (``origin.measured =
False`` с причиной словами), а не тихий откат к неполной очереди дерева: молчаливая
частичная рассылка неотличима от полной — ровно на этом владелец и терял вопросы.

Только stdlib. LLM здесь запрещён (это доставка, не суждение).
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

log = logging.getLogger(__name__)

#: С чем сверяется очередь. Локальная копия ref, без `fetch` (см. `origin_view`), поэтому
#: «сверено с origin» нельзя читать как «сверено со свежайшим origin» — sha называется.
ORIGIN_REF = "origin/main"

#: Тип и статус карточки, которая ПРЯМО СЕЙЧАС спрашивает владельца.
_CARD_TYPE = "owner-decision"
_OPEN_STATUS = "needs-owner"

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
    #: Судьба сверки очереди с `origin/main` — см. `OpenQueue.origin`.
    origin: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Все ли вопросы доехали. Частичная рассылка — НЕ успех.

        Про ПОЛНОТУ очереди это утверждение сознательно молчит: у него один предмет —
        доставка того, что мы отправили. Полнота живёт отдельным, НАЗВАННЫМ полем
        (`origin`) и отдельным вопросом `queue_measured` — слепить их в один флаг
        значило бы снова сделать «не измерено» неотличимым от «всё хорошо».
        """
        return self.failed == 0

    @property
    def queue_measured(self) -> bool:
        """Была ли очередь сверена с `origin/main`. False ⇒ список мог быть НЕПОЛОН."""
        return bool(self.origin.get("measured"))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        d["queue_measured"] = self.queue_measured
        return d


@dataclass
class OpenQueue:
    """Кого спрашивает владелец ПРЯМО СЕЙЧАС — и чем эта очередь измерена.

    ``cards`` — карточки в порядке отправки (сначала видимые дереву, потом те, что
    живут только на ref). ``origin`` — судьба сверки с ref: ``measured`` False с
    причиной СЛОВАМИ, если прочитать не удалось. Пустой ``cards`` при
    ``measured=False`` НИКОГДА не означает «вопросов нет».
    """

    cards: List = field(default_factory=list)
    origin: dict = field(default_factory=lambda: {"measured": False,
                                                  "reason": "сверка не выполнялась"})


def _tree_questions(tracker_dir: Optional[str | Path]) -> List:
    """Открытые вопросы, видимые ДЕРЕВУ. Никогда не бросает: пустой список честнее
    падения посреди рассылки."""
    try:
        from spa_core.owner_queue.queue import list_cards

        kwargs = {"tracker_type": _CARD_TYPE, "status": _OPEN_STATUS}
        if tracker_dir is not None:
            kwargs["tracker_dir"] = tracker_dir
        return list(list_cards(**kwargs))
    except Exception as exc:  # noqa: BLE001
        log.warning("open_questions: не смог прочитать очередь дерева (%s)", exc)
        return []


def _tracker_dir(tracker_dir: Optional[str | Path]) -> Path:
    if tracker_dir is not None:
        return Path(tracker_dir)
    from spa_core.owner_queue.queue import TRACKER_DIR

    return Path(TRACKER_DIR)


def _origin_only_questions(tdir: Path, ref: str, workdir: Path) -> tuple[List, dict]:
    """Вопросы, которые есть на ref и которых НЕТ в дереве. → (карточки, отчёт о сверке).

    Каждая найденная карточка выкладывается файлом ``<card_id>.md`` в `workdir` и
    разбирается ТЕМ ЖЕ ``load_card``, что и карточка с диска: второго правила разбора
    здесь не заводится, а у отправителя на руках оказывается настоящий путь — тот, по
    которому дальше отработают и материализация в живое дерево, и кнопка, и ответ.

    Fail-CLOSED и наружу не бросает: «сверять не с чем» (не git-дерево, ref не
    разрешается) и «померить не смогли» приходят одинаково — ``measured: False`` с
    причиной. Карточка, чей текст с ref не прочитался, НАЗЫВАЕТСЯ в ``unreadable``, а не
    выпадает молча: молча выпавший вопрос владельца и есть предмет всей этой правки.
    """
    report: dict = {"measured": False, "ref": ref}
    try:
        from spa_core.owner_queue.origin_view import Unmeasured, card_sources, hidden_cards
    except Exception as exc:  # noqa: BLE001 — импорт не роняет рассылку
        report["reason"] = f"сверка с {ref} недоступна: {exc}"
        return [], report
    try:
        hidden, sha = hidden_cards(tdir, ref=ref, tracker_type=_CARD_TYPE,
                                   status=_OPEN_STATUS)
        sources, _ = card_sources(tdir, [c.card_id for c in hidden], ref=ref)
    except Unmeasured as exc:
        report["reason"] = f"очередь на {ref} не прочитана: {exc}"
        return [], report
    except Exception as exc:  # noqa: BLE001 — неожиданное тоже «не измерено», не «чисто»
        report["reason"] = f"сверка с {ref} не выполнена: {exc}"
        return [], report

    from spa_core.owner_queue.queue import load_card

    cards, unreadable = [], []
    workdir.mkdir(parents=True, exist_ok=True)
    for c in sorted(hidden, key=lambda c: c.card_id):
        text = sources.get(c.card_id)
        if not text:
            unreadable.append(c.card_id)
            continue
        # Имя файла — ровно `<card_id>.md`: ключ журнала отправок и callback кнопки
        # берётся из `path.stem`, и любое другое имя развело бы отправку с ответом.
        path = workdir / f"{c.card_id}.md"
        try:
            path.write_text(text, encoding="utf-8")
            cards.append(load_card(path))
        except Exception as exc:  # noqa: BLE001
            log.warning("origin-only карточка %s не выложена: %s", c.card_id, exc)
            unreadable.append(c.card_id)

    report.update({"measured": True, "ref_sha": sha, "origin_only": len(cards)})
    if unreadable:
        report["unreadable"] = sorted(unreadable)
    return cards, report


def open_questions(*, tracker_dir: Optional[str | Path] = None,
                   ref: str = ORIGIN_REF,
                   workdir: Optional[str | Path] = None) -> OpenQueue:
    """Карточки, которые ПРЯМО СЕЙЧАС спрашивают владельца (`needs-owner`) — ОБЕ стороны.

    Источник правды — статус карточки, а не журнал отправок; а сама очередь — это
    объединение того, что видит дерево, и того, что лежит на ``ref`` (см. модульную
    справку: каталог очереди в прод-дерево не возит никто).

    ``workdir`` — куда выкладывать карточки, живущие только на ``ref``. Не задан ⇒
    временный каталог; удалить его — забота вызывающего (файл нужен ДО отправки).
    """
    tdir = _tracker_dir(tracker_dir)
    cards = _tree_questions(tracker_dir)
    work = Path(workdir) if workdir is not None else Path(
        tempfile.mkdtemp(prefix="spa_origin_questions_"))
    origin_cards, origin = _origin_only_questions(tdir, ref, work)
    return OpenQueue(cards=cards + origin_cards, origin=origin)


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
    ref: str = ORIGIN_REF,
) -> ResendReport:
    """Переслать владельцу все открытые вопросы — по одному сообщению, с кнопками.

    ``dry_run=True`` — собрать список и тексты, НО НЕ ОТПРАВЛЯТЬ и не трогать живое
    состояние (сухой прогон не имеет права регистрировать пуш: нажимать нечего).

    ``sleep``/``pace_s`` — темп инъектируем, потому что иначе тест этой функции обязан
    ждать по-настоящему; время здесь ВХОД, а не окружение (правило `.claude/rules/
    deployment.md` про фиксированные даты — тот же принцип).
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    work = Path(tempfile.mkdtemp(prefix="spa_origin_questions_"))
    try:
        return _resend(stamp, work, tracker_dir=tracker_dir, dry_run=dry_run,
                       sleep=sleep, pace_s=pace_s, limit=limit,
                       state_path=state_path, report_path=report_path, ref=ref)
    finally:
        # Каталог нужен только ДО отправки: `notify_needs_owner` уже перенёс карточку в
        # живое дерево (`materialize_card`), и ответ владельца будет писаться туда.
        shutil.rmtree(work, ignore_errors=True)


def _resend(stamp, work, *, tracker_dir, dry_run, sleep, pace_s, limit,
            state_path, report_path, ref) -> ResendReport:
    queue = open_questions(tracker_dir=tracker_dir, ref=ref, workdir=work)
    cards = queue.cards
    if limit is not None:
        cards = cards[:limit]
    report = ResendReport(requested_at=stamp, total=len(cards), dry_run=dry_run,
                          origin=queue.origin)

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


def _queue_note(report: ResendReport) -> str:
    """Хвост строки про ПОЛНОТУ очереди. Пусто — только когда сверка состоялась и молчать
    не о чем.

    «Очередь не сверена» обязано звучать даже в самом благополучном исходе: «вопросов
    нет» и «вопросов не видно» — разные утверждения, и именно их неразличимость держала
    восемь вопросов владельца невидимыми четвёртый день.
    """
    origin = report.origin or {}
    if not origin.get("measured"):
        reason = origin.get("reason") or "причина не названа"
        return (f" · ⚠️ очередь с {origin.get('ref', ORIGIN_REF)} НЕ СВЕРЕНА "
                f"({reason}) — список мог быть НЕПОЛОН")
    note = ""
    only = int(origin.get("origin_only") or 0)
    if only:
        note += f" · из них {only} есть только на {origin.get('ref', ORIGIN_REF)}"
    if origin.get("unreadable"):
        note += (" · ⚠️ не прочитаны с ref: "
                 + ", ".join(origin["unreadable"]))
    return note


def summary_line(report: ResendReport) -> str:
    """Одна строка для человека. Недоставленное НАЗЫВАЕТСЯ, а не прячется в счёт."""
    note = _queue_note(report)
    if report.total == 0:
        return "открытых вопросов владельцу нет — пересылать нечего" + note
    if report.dry_run:
        return (f"сухой прогон: открытых вопросов {report.total}, ничего не отправлено"
                + note)
    head = f"переслано {report.delivered} из {report.total}"
    if report.ok:
        return head + note
    lost = ", ".join(o.card_id for o in report.outcomes if not o.delivered)
    return f"{head}; НЕ ДОСТАВЛЕНО {report.failed}: {lost}" + note
