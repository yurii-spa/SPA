#!/usr/bin/env python3
"""Кнопки действий под алертом: «пришла проблема → нажал → завелась карточка».

Задание владельца (Telegram, 2026-08-07): *«если приходит ошибка — она приходит с
вариантами кнопок, что можно сделать; один из вариантов — с рекомендацией; нажимаю —
и автоматически заводится карточка и сама набирается в работу»*.

Как устроено (детерминированно, stdlib, **LLM запрещён** — это alerting/monitoring):

1. ``classify_problem(text)`` — по ЗАГОЛОВКУ сообщения (первые ~160 символов) решает,
   проблема ли это и какого рода. **Fail-CLOSED: не распознал → ``None`` → кнопок нет**
   и сообщение уходит ровно так же, как уходило вчера. Заголовок, а не всё тело:
   иначе слово «⚠️» в середине дневного дайджеста навесило бы кнопки на отчёт.
2. ``register_alert(text)`` — кладёт алерт в кольцевой журнал ``data/telegram_alert_actions.json``
   и отдаёт ``(alert_id, keyboard)``. Журнал нужен потому, что ``callback_data``
   Telegram — это ≤64 байт и БЕЗ состояния: в момент нажатия текста алерта уже нет,
   а карточка обязана цитировать его дословно.
3. ``record_choice(alert_id, option_id)`` — нажатие. Заводит карточку через
   ``spa_core.owner_queue.queue.create_card`` (единственный разрешённый путь) и
   **идемпотентен по паре (алерт, вариант)**: повторное нажатие той же кнопки не плодит
   вторую карточку, а показывает первую.

Почему у риск-алертов рекомендация — «нужно твоё решение», а не «починить».
Инвариант #1 и `.claude/rules/risk-engine.md`: RiskPolicy / kill-switch / пороги агент
не трогает. Кнопка, рекомендующая агенту «починить просадку», обучала бы владельца
одним нажатием заказывать запрещённое. Поэтому для рода ``risk`` рекомендация —
карточка `needs-owner` (+ notify), и это записано в реестре, а не в комментарии.

Ни один вариант НЕ исполняет код и не двигает капитал. Максимум, что делает нажатие, —
создаёт карточку. Исполняет её потом обычный цикл оркестратора под обычными правилами.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_save

# ── где живёт журнал алертов ─────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = _REPO_ROOT / "data" / "telegram_alert_actions.json"
HISTORY_MAX = 200

CALLBACK_PREFIX = "act:aa:"
CALLBACK_MAX_BYTES = 64  # жёсткий лимит Telegram

ALERT_ID_LEN = 8


def _state_path(override: Optional[str | Path] = None) -> Path:
    """Путь к журналу. Под pytest — ВСЕГДА временный, если не задан явно.

    Урок инцидента «тесты пишут в живое состояние алертов» (`push_policy` резолвил
    `data/` статически, и прогон тестов мог заглушить настоящую тревогу kill-switch):
    любой модуль с состоянием обязан сам уводить тесты в сторону, а не надеяться,
    что каждый автор теста вспомнит про подмену пути.
    """
    if override is not None:
        return Path(override)
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
        "SPA_ALERT_ACTIONS_TEST"
    ):
        return Path(tempfile.gettempdir()) / "spa_alert_actions_pytest.json"
    return STATE_PATH


# ── реестр вариантов ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Option:
    """Один вариант ответа под алертом.

    ``card_type``  — что заводится: ``inbox`` (работа агента) либо ``owner-decision``
                     (нужно решение владельца, статус `needs-owner` + notify).
                     ``None`` — карточка НЕ заводится (вариант «так и надо»).
    """

    id: str
    label_ru: str
    label_en: str
    card_type: Optional[str]
    card_status: Optional[str] = None
    priority: str = ""


OPTION_FIX = Option("fix", "🔧 Починить", "🔧 Fix it", "inbox", "new", "high")
OPTION_OWN = Option("own", "🧑‍⚖️ Нужно моё решение", "🧑‍⚖️ Needs my decision",
                    "owner-decision", "needs-owner")
OPTION_WATCH = Option("watch", "👀 Наблюдать", "👀 Watch it", "inbox", "new", "low")
OPTION_SKIP = Option("skip", "✅ Так и надо", "✅ Expected", None)

_ALL_OPTIONS: Dict[str, Option] = {
    o.id: o for o in (OPTION_FIX, OPTION_OWN, OPTION_WATCH, OPTION_SKIP)
}

# род проблемы → (какие варианты показать, какой рекомендован)
# Рекомендация — ЧАСТЬ РЕЕСТРА, а не украшение: для риск-домена она обязана вести
# к решению владельца (инвариант #1), и это закреплено тестом.
_KIND_OPTIONS: Dict[str, Tuple[Sequence[str], str]] = {
    "risk":       (("own", "watch", "skip"), "own"),
    "agent_down": (("fix", "own", "skip"), "fix"),
    "cycle_gap":  (("fix", "own", "skip"), "fix"),
    "data_stale": (("fix", "watch", "skip"), "fix"),
    "feed":       (("watch", "fix", "skip"), "watch"),
    "site":       (("fix", "own", "skip"), "fix"),
    "problem":    (("fix", "own", "watch", "skip"), "fix"),
}

# человеческое имя рода — уезжает в заголовок карточки
KIND_TITLE_RU: Dict[str, str] = {
    "risk": "риск/просадка",
    "agent_down": "агент не работает",
    "cycle_gap": "цикл пропущен",
    "data_stale": "данные протухли / не измерено",
    "feed": "фид доходности",
    "site": "сайт",
    "problem": "проблема",
}

# ── классификация ────────────────────────────────────────────────────────────
# Смотрим ТОЛЬКО на заголовок: первая строка + начало текста. Иначе «⚠️» в середине
# дневного отчёта навесило бы кнопки на отчёт, а не на проблему.
HEAD_CHARS = 160

# Сначала — специальные рода (порядок значим: риск важнее общего «ошибка»).
_KIND_MARKERS: Sequence[Tuple[str, Sequence[str]]] = (
    ("risk", ("kill switch", "kill-switch", "killswitch", "drawdown", "просадк",
              "hard_kill", "soft_derisk", "стоп-кран", "riskpolicy")),
    ("agent_down", ("агент", "agent down", "agent_health", "not running", "мёртв",
                    "мертв", "exit 78", "exit 126", "launchd", "fleet")),
    ("cycle_gap", ("gap detected", "пропущен цикл", "пропущен ежедневный",
                   "cycle age", "missed", "цикл не")),
    ("data_stale", ("не измерено", "not measured", "unchecked", "протух", "stale",
                    "устарел")),
    ("feed", ("apy", "фид", "feed", "tvl", "spike", "drift")),
    ("site", ("site custodian", "earn-defi", "сайт")),
)

# Общие признаки «это проблема, а не сводка».
_PROBLEM_MARKERS: Sequence[str] = (
    "❌", "🚨", "⚠️", "🔴", "critical", "критично", "error", "ошибка", "failed",
    "провал", "alert", "тревога", "внимание", "не работает", "сбой", "incident",
)

# Явные признаки «это НЕ проблема» — гасят кнопки даже при совпадении выше.
# Пульс «✅ OK» с кнопкой «починить» — ровно тот шум, из-за которого владелец
# перестаёт читать чат.
_OK_MARKERS: Sequence[str] = ("✅", "🟢", " ok", "ok ", "всё в порядке", "healthy")


def _head(text: str) -> str:
    """Заголовок = ПЕРВАЯ СТРОКА (до 160 символов), а не начало текста.

    Замерено на живом дайджесте: «SPA — Ежедневный отчёт» короче 160 символов, поэтому
    «начало текста» затягивало ⚠️ из тела отчёта и навесило бы кнопки «Починить» на
    обычную сводку. Первая строка — это ровно то, что владелец видит как тему письма.
    """
    stripped = (text or "").strip()
    if not stripped:
        return ""
    return stripped.splitlines()[0][:HEAD_CHARS].lower()


def classify_problem(text: str) -> Optional[str]:
    """Род проблемы по заголовку алерта, либо ``None`` — «кнопок не вешать».

    Fail-CLOSED: сомнение → ``None``. Сообщение уходит ровно как прежде.
    """
    head = _head(text)
    if not head:
        return None
    if not any(m in head for m in _PROBLEM_MARKERS):
        return None
    if any(m in head for m in _OK_MARKERS) and "❌" not in head and "🚨" not in head:
        return None
    for kind, markers in _KIND_MARKERS:
        if any(m in head for m in markers):
            return kind
    return "problem"


def options_for(kind: str) -> List[Option]:
    """Варианты рода в порядке показа. Неизвестный род → варианты общей проблемы."""
    ids, _rec = _KIND_OPTIONS.get(kind, _KIND_OPTIONS["problem"])
    return [_ALL_OPTIONS[i] for i in ids]


def recommended_option(kind: str) -> Option:
    """Рекомендованный вариант рода. Он ровно один — это закреплено тестом."""
    _ids, rec = _KIND_OPTIONS.get(kind, _KIND_OPTIONS["problem"])
    return _ALL_OPTIONS[rec]


def label_for(option: Option, kind: str, lang: str = "ru") -> str:
    """Подпись кнопки; рекомендованная помечена звездой и словом «рекомендую»."""
    base = option.label_ru if str(lang).lower().startswith("ru") else option.label_en
    if option.id == recommended_option(kind).id:
        suffix = " ⭐ рекомендую" if str(lang).lower().startswith("ru") else " ⭐ recommended"
        return base + suffix
    return base


def build_keyboard(alert_id: str, kind: str, lang: str = "ru") -> Dict:
    """Инлайн-клавиатура под алерт. По одной кнопке в ряд — подписи длинные."""
    rows = []
    for opt in options_for(kind):
        data = "{}{}:{}".format(CALLBACK_PREFIX, alert_id, opt.id)
        if len(data.encode("utf-8")) > CALLBACK_MAX_BYTES:  # pragma: no cover - защита
            continue
        rows.append([{"text": label_for(opt, kind, lang), "callback_data": data}])
    return {"inline_keyboard": rows}


# ── журнал алертов ───────────────────────────────────────────────────────────


def _load(path: Path) -> Dict:
    try:
        import json

        doc = json.loads(path.read_text())
        if isinstance(doc, dict) and isinstance(doc.get("alerts"), list):
            return doc
    except Exception:  # noqa: BLE001 — журнал не обязан существовать
        pass
    return {"schema_version": 1, "source": "telegram_alert_actions", "alerts": []}


def _save(doc: Dict, path: Path) -> None:
    """Запись атомарна (`atomic_save`), но НЕ под блокировкой — и это осознанно.

    Агенты SPA — разные процессы; два алерта в одну секунду могут потерять одну запись
    журнала на гонке read-modify-write. Цена потери названа и мала: нажатие по такому
    алерту получит честный отказ «алерт вытеснен, цитировать нечего», а не карточку с
    выдуманным текстом. Блокировка ради этого добавила бы точку отказа на пути ТРЕВОГИ —
    дороже, чем потерянная кнопка.
    """
    doc["alerts"] = doc.get("alerts", [])[-HISTORY_MAX:]
    doc["count"] = len(doc["alerts"])
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(doc, str(path))


def make_alert_id(text: str, ts: str) -> str:
    """Короткий стабильный идентификатор алерта (влезает в 64 байта callback_data)."""
    return hashlib.sha256(((text or "") + "|" + ts).encode("utf-8")).hexdigest()[:ALERT_ID_LEN]


# ── интерлок: кнопка появляется, только если есть кому её обработать ─────────
# Мониторы — короткоживущие процессы: свежий код они подхватывают со следующего
# запуска. Бот — ДОЛГОЖИВУЩИЙ (launchd KeepAlive, аптайм измерялся сутками): после
# доставки кода он ещё какое-то время крутит старую версию. Без интерлока кнопки
# поехали бы раньше обработчика, а нажатие по старому боту не просто «ничего не
# делает» — оно уходит в ветку неизвестного `act:`-глагола и ПЕРЕПИСЫВАЕТ сообщение
# алерта панелью настроек, то есть стирает саму тревогу.
#
# Поэтому бот, умеющий обрабатывать нажатие, стучит маячком, а отправитель проверяет
# маячок перед тем, как навесить кнопки. Fail-CLOSED: маячка нет / протух / не тот
# набор умений / файл битый → кнопок нет, алерт уходит как обычный текст. Никакого
# ручного шага: как только бот перезапустится с новым кодом, кнопки включатся сами.
BEACON_PATH = _REPO_ROOT / "data" / "telegram_bot_capabilities.json"
BEACON_MAX_AGE_S = 300  # маячок обновляется каждый виток long-poll (~30с)
CAPABILITY = "alert_actions"


def _beacon_path(override: Optional[str | Path] = None) -> Path:
    if override is not None:
        return Path(override)
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
        "SPA_ALERT_ACTIONS_TEST"
    ):
        return Path(tempfile.gettempdir()) / "spa_bot_capabilities_pytest.json"
    return BEACON_PATH


def publish_handler_beacon(
    *, now: Optional[datetime] = None, beacon_path: Optional[str | Path] = None
) -> None:
    """Бот объявляет: «я жив и умею обрабатывать нажатия». Никогда не бросает."""
    try:
        dt = now or datetime.now(timezone.utc)
        path = _beacon_path(beacon_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_save({"schema_version": 1, "source": "telegram_bot",
                     "updated_at": dt.isoformat(), "pid": os.getpid(),
                     "capabilities": [CAPABILITY]}, str(path))
    except Exception:  # noqa: BLE001 — маячок не важнее работы бота
        pass


def handler_available(
    *, now: Optional[datetime] = None, beacon_path: Optional[str | Path] = None
) -> bool:
    """Есть ли ЖИВОЙ бот, умеющий обработать нажатие. Сомнение → False."""
    try:
        import json

        doc = json.loads(_beacon_path(beacon_path).read_text())
        if CAPABILITY not in (doc.get("capabilities") or []):
            return False
        stamped = datetime.fromisoformat(str(doc.get("updated_at")))
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=timezone.utc)
        age = ((now or datetime.now(timezone.utc)) - stamped).total_seconds()
        return 0 <= age <= BEACON_MAX_AGE_S
    except Exception:  # noqa: BLE001 — не смогли измерить ⇒ кнопок не вешаем
        return False


def register_alert(
    text: str,
    *,
    lang: str = "ru",
    now: Optional[datetime] = None,
    state_path: Optional[str | Path] = None,
    beacon_path: Optional[str | Path] = None,
) -> Optional[Tuple[str, Dict]]:
    """Записать алерт и отдать ``(alert_id, keyboard)``; ``None`` — если не проблема.

    ``None`` также когда нет живого обработчика (см. интерлок выше) — кнопка, которую
    некому обработать, хуже отсутствия кнопки.

    Никогда не бросает: сбой журнала не имеет права помешать уходу самой тревоги.
    """
    try:
        kind = classify_problem(text)
        if kind is None:
            return None
        if not handler_available(now=now, beacon_path=beacon_path):
            return None
        dt = now or datetime.now(timezone.utc)
        ts = dt.isoformat()
        alert_id = make_alert_id(text, ts)
        path = _state_path(state_path)
        doc = _load(path)
        doc["alerts"].append(
            {"id": alert_id, "ts": ts, "kind": kind, "text": text, "choices": {}}
        )
        _save(doc, path)
        return alert_id, build_keyboard(alert_id, kind, lang)
    except Exception:  # noqa: BLE001 — алерт важнее кнопок
        return None


def get_alert(alert_id: str, *, state_path: Optional[str | Path] = None) -> Optional[Dict]:
    doc = _load(_state_path(state_path))
    for entry in reversed(doc.get("alerts", [])):
        if isinstance(entry, dict) and entry.get("id") == alert_id:
            return dict(entry)  # копия: читателю не положено править журнал
    return None


def recent_alerts(
    *, limit: int = HISTORY_MAX, state_path: Optional[str | Path] = None
) -> List[Dict]:
    """Журнал алертов, новые первыми. Копии — читателю не положено править журнал.

    Второй вход к тем же вариантам (экран «Предупреждения» в меню бота) обязан читать
    ЭТОТ журнал, а не свой собственный: разъехавшийся список проблем хуже отсутствия
    списка. Отсюда же и резолв пути — включая увод тестов во временный файл, который
    иначе пришлось бы повторять в каждом читателе.

    Никогда не бросает: битый журнал — пустой список, а не падение экрана.
    """
    try:
        doc = _load(_state_path(state_path))
        rows = [dict(e) for e in doc.get("alerts", []) if isinstance(e, dict)]
    except Exception:  # noqa: BLE001 — экран важнее журнала
        return []
    rows.reverse()
    return rows[: max(0, int(limit))] if limit is not None else rows


# ── нажатие → карточка ───────────────────────────────────────────────────────


@dataclass
class ChoiceResult:
    ok: bool
    reason: str = ""             # почему не ok (машинное)
    option: Optional[Option] = None
    card_path: Optional[str] = None
    card_type: Optional[str] = None
    already: bool = False        # карточка была заведена раньше — повторное нажатие
    notify_needed: bool = False  # owner-decision → позвать notify


def _first_line(text: str, limit: int = 70) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    line = line.strip()
    return line[:limit].rstrip() if line else "алерт без текста"


def _inbox_body(entry: Dict, option: Option) -> str:
    return "\n".join([
        "## Откуда это",
        "",
        "Владелец нажал кнопку **«{}»** под алертом в Telegram "
        "(род: {}, алерт `{}`, время {}).".format(
            option.label_ru, KIND_TITLE_RU.get(entry.get("kind", ""), entry.get("kind", "")),
            entry.get("id", ""), entry.get("ts", "")),
        "",
        "## Текст алерта — дословно",
        "",
        "```",
        (entry.get("text") or "").strip(),
        "```",
        "",
        "## Что сделать",
        "",
        {
            "fix": "Разобраться в причине и починить. Правило то же, что для любой работы: "
                   "сначала воспроизвести проблему, потом чинить, тесты в обе стороны. "
                   "Если причина в risk-логике / kill-switch / живом треке / деплое агентов — "
                   "НЕ чинить молча, завести карточку `needs-owner`.",
            "watch": "Пока не чинить. Проследить, повторится ли; если повторится — "
                     "поднять приоритет и разобраться. Записать, сколько раз наблюдалось.",
        }.get(option.id, "Разобраться."),
        "",
        "_Карточка заведена автоматически кнопкой под алертом "
        "(`spa_core/telegram/alert_actions.py`). Исполняется обычным циклом оркестратора._",
    ])


def _owner_body(entry: Dict, option: Option) -> str:
    """Тело карточки владельцу — строго формат §2.4 (инвариант #15)."""
    kind_ru = KIND_TITLE_RU.get(entry.get("kind", ""), entry.get("kind", ""))
    return "\n".join([
        "## Что случилось и почему это важно",
        "",
        "Пришёл алерт ({}), и ты нажал «Нужно моё решение». Значит, дальше без тебя "
        "двигаться нельзя — сам алерт ниже дословно.".format(kind_ru),
        "",
        "```",
        (entry.get("text") or "").strip(),
        "```",
        "",
        "## Что от тебя нужно",
        "",
        "Ответь прямо в этой карточке, что делать: починить (и как), оставить как есть, "
        "или это ожидаемо и тревога лишняя. Если проблема касается risk-логики, "
        "kill-switch, порогов или живого трека — агент не имеет права решать это сам, "
        "поэтому и спрашивает.",
        "",
        "## Как понять, что готово",
        "",
        "В карточке есть твой ответ, и ты перевёл её в `owner-done`.",
        "",
        "## Что будет после",
        "",
        "Оркестратор прочитает ответ, заведёт из него задачу (или закроет вопрос), "
        "выпишет ADR, если решение архитектурное, и переведёт карточку в `ingested`.",
        "",
        "_Заведено кнопкой под алертом (`alert_actions`), алерт `{}` от {}._".format(
            entry.get("id", ""), entry.get("ts", "")),
    ])


def record_choice(
    alert_id: str,
    option_id: str,
    *,
    state_path: Optional[str | Path] = None,
    tracker_dir: Optional[str | Path] = None,
    now: Optional[datetime] = None,
) -> ChoiceResult:
    """Обработать нажатие. Идемпотентно по паре (алерт, вариант).

    Возвращает результат — никогда не бросает: бот не имеет права падать от нажатия.
    """
    option = _ALL_OPTIONS.get(str(option_id))
    if option is None:
        return ChoiceResult(False, "unknown_option")

    path = _state_path(state_path)
    doc = _load(path)
    entry = None
    for e in reversed(doc.get("alerts", [])):
        if e.get("id") == alert_id:
            entry = e
            break
    if entry is None:
        # Кольцевой журнал вытеснил алерт (старее 200) — честно говорим, что
        # цитировать нечего, а не заводим карточку с выдуманным текстом.
        return ChoiceResult(False, "alert_not_found", option=option)

    choices = entry.setdefault("choices", {})
    prev = choices.get(option.id)
    if isinstance(prev, dict):
        return ChoiceResult(True, "already", option=option,
                            card_path=prev.get("card"), card_type=prev.get("card_type"),
                            already=True)

    dt = now or datetime.now(timezone.utc)
    card_path = None
    notify_needed = False
    if option.card_type is not None:
        try:
            from spa_core.owner_queue.queue import create_card

            prefix = {"inbox": "Из алерта", "owner-decision": "Решение по алерту"}[option.card_type]
            title = "{}: {}".format(prefix, _first_line(entry.get("text", "")))
            body = (_owner_body(entry, option) if option.card_type == "owner-decision"
                    else _inbox_body(entry, option))
            extra = {"alert_id": entry.get("id", ""), "alert_kind": entry.get("kind", "")}
            if option.priority:
                extra["priority"] = option.priority
            created = create_card(
                option.card_type, title, body,
                status=option.card_status, source="telegram-alert-button",
                extra_fields=extra, tracker_dir=tracker_dir, now=dt,
            )
            card_path = str(created)
            notify_needed = option.card_type == "owner-decision"
        except Exception as exc:  # noqa: BLE001 — нажатие не имеет права уронить бота
            return ChoiceResult(False, "card_failed:{}".format(type(exc).__name__),
                                option=option)

    choices[option.id] = {"ts": dt.isoformat(), "card": card_path,
                          "card_type": option.card_type}
    try:
        _save(doc, path)
    except Exception:  # noqa: BLE001 — карточка уже создана, журнал вторичен
        pass
    return ChoiceResult(True, "created", option=option, card_path=card_path,
                        card_type=option.card_type, notify_needed=notify_needed)


def confirmation_text(result: ChoiceResult, lang: str = "ru") -> str:
    """Что бот отвечает владельцу после нажатия. Никогда не молчит."""
    ru = str(lang).lower().startswith("ru")
    if not result.ok:
        if result.reason == "alert_not_found":
            return ("⚠️ Этот алерт уже вытеснен из журнала (храним последние {}), "
                    "поэтому карточку с его дословным текстом завести нечем. "
                    "Напиши задачу словами — заведу.".format(HISTORY_MAX) if ru else
                    "⚠️ This alert has aged out of the log (last {} kept).".format(HISTORY_MAX))
        if result.reason == "unknown_option":
            return "⚠️ Неизвестная кнопка." if ru else "⚠️ Unknown button."
        return ("⚠️ Не получилось завести карточку ({}). Ничего не потеряно — "
                "алерт остался в чате.".format(result.reason) if ru else
                "⚠️ Could not create the card ({}).".format(result.reason))

    opt = result.option
    name = (opt.label_ru if ru else opt.label_en) if opt else "?"
    if result.card_path is None:
        return ("✅ Принято: «{}». Карточку не завожу — ты сказал, что так и надо.".format(name)
                if ru else "✅ Noted: «{}». No card created.".format(name))
    card_id = Path(result.card_path).stem
    if result.already:
        return ("ℹ️ По этому алерту с вариантом «{}» карточка уже заведена: `{}`.".format(name, card_id)
                if ru else "ℹ️ A card already exists for «{}»: `{}`.".format(name, card_id))
    if result.card_type == "owner-decision":
        return ("✅ Принято: «{}». Завёл карточку решения `{}` — она ждёт твоего ответа.".format(name, card_id)
                if ru else "✅ Noted: «{}». Owner-decision card `{}` created.".format(name, card_id))
    return ("✅ Принято: «{}». Завёл карточку `{}` — оркестратор возьмёт её в ближайшем цикле.".format(name, card_id)
            if ru else "✅ Noted: «{}». Card `{}` created; the orchestrator will pick it up.".format(name, card_id))
