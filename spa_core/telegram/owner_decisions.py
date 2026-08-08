#!/usr/bin/env python3
"""Решения владельца в Телеграме: карточка → сообщение с вариантами → нажатие → ответ записан.

Задание владельца (Telegram, 2026-08-08, перед отъездом на 10 дней): *«вопросы из карточек,
которые на мне, — вообще всё, что требует моего решения, — чтобы приходило в телеграм красиво,
простыми словами, с вариантами ответа и с рекомендацией, чтобы я мог частично управлять
разработкой проекта из телефона»*.

Половина задачи была сделана до нас, и переделывать её не надо: карточки решений **уже** пишутся
по формату §2.4 — секция «## Что от тебя нужно» содержит перечень «**Вариант N (рекомендую) —
…**». То есть варианты и рекомендация уже сформулированы автором карточки, по-русски и
человеческим языком. Этот модуль их НЕ придумывает — он их **читает** и превращает в кнопки.
Придумывать варианты на лету означало бы предложить владельцу то, чего в карточке нет.

Как устроено (детерминированно, stdlib, **LLM запрещён**):

1. ``parse_options(body)`` — вытаскивает варианты из секции «Что от тебя нужно».
   **Fail-CLOSED: не разобрали ни одного варианта → ``[]`` → кнопок нет**, сообщение уходит
   обычным текстом (как уходило вчера). Кнопка «Вариант 2», которой нет в карточке, хуже
   отсутствия кнопок.
2. ``register_push(card)`` — кладёт карточку в журнал ``data/telegram_owner_decisions.json``
   и отдаёт ``(pid, keyboard)``. Журнал нужен по той же причине, что и у алертов:
   ``callback_data`` в Telegram — ≤64 байта и без состояния, а имя файла карточки длиннее.
3. ``record_choice(pid, choice, actor_chat_id)`` — нажатие. Записывает решение В КАРТОЧКУ
   через owner-путь (см. ниже) и идемпотентно по паре (карточка, вариант).

**Инвариант #14 и почему здесь он НЕ нарушен.** «Агентам ЗАПРЕЩЕНО переводить карточку решения
в ``owner-done``; только владелец». ``queue.set_status`` этот переход агенту ОТКАЗЫВАЕТ, и так
и остаётся — ни одной строки в нём не ослаблено. Нажатие кнопки в Телеграме — это действие
ВЛАДЕЛЬЦА, а не агента, поэтому у него отдельный узкий путь
(``spa_core.owner_queue.owner_answer.record_owner_answer``), который:

* принимает решение только с chat_id владельца (чужое нажатие — молча отклоняется);
* проверку личности делает ВНУТРИ писателя, а не на стороне вызова — чтобы её нельзя было
  забыть, добавляя второе место вызова;
* записывает в карточку, КТО и КОГДА решил и каким каналом (аудит).

Решение владельца 2026-08-08: «нажатие = моё решение, закрывать сразу».

Нажатие НЕ исполняет код и НЕ двигает капитал. Максимум — записывает выбор в карточку.
Дальше работу делает обычный цикл оркестратора под обычными правилами (RiskPolicy, ADR,
pre_cutover_gate — всё на месте).
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = _REPO_ROOT / "data" / "telegram_owner_decisions.json"
HISTORY_MAX = 200

CALLBACK_PREFIX = "act:od:"
CALLBACK_MAX_BYTES = 64  # жёсткий лимит Telegram
PID_LEN = 8

# Кнопка с длинной подписью в Telegram обрезается САМИМ клиентом, и владелец видит
# «Вариант 1 — перезаполнять освободивш…». Режем сами, по границе слова.
BUTTON_LABEL_MAX = 30


def _state_path(override: Optional[str | Path] = None) -> Path:
    """Путь к журналу. Под pytest — ВСЕГДА временный, если не задан явно.

    Урок инцидента «тесты пишут в живое состояние алертов»: модуль с состоянием обязан
    сам уводить тесты в сторону, а не надеяться, что каждый автор теста вспомнит подменить путь.
    """
    if override is not None:
        return Path(override)
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
        "SPA_OWNER_DECISIONS_TEST"
    ):
        return Path(tempfile.gettempdir()) / "spa_owner_decisions_pytest.json"
    return STATE_PATH


# ── разбор вариантов из тела карточки ────────────────────────────────────────

# Заголовки секции «что от тебя нужно» — те же, что понимает queue.first_instruction_line,
# плюс английские варианты. Список ОДИН на модуль: разойдутся — разъедется и разбор.
_NEED_HEADINGS = (
    "## что от тебя нужно",
    "## инструкц",
    "## instruction",
    "## what",
)

# `* **Вариант 1 (рекомендую) — перезаполнять освободившийся бюджет.** …`
# `- **Вариант B — оставить как есть.** …`
# Номер — цифра или одна буква (встречается «Вариант А/Б»). Тире — любое из трёх.
_OPTION_RE = re.compile(
    r"^\s*[*\-+]\s+\*\*\s*(?:вариант|option)\s+"
    r"(?P<num>\d{1,2}|[A-Za-zА-Яа-я])\s*"
    r"(?P<paren>\([^)]*\))?\s*"
    r"[—–-]\s*"
    r"(?P<label>.+?)\s*\*\*",
    re.IGNORECASE,
)

_RECOMMEND_RE = re.compile(r"рекоменд|recommend", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedOption:
    """Вариант ответа, ВЫЧИТАННЫЙ из карточки (не придуманный)."""

    num: str          # «1», «2», «B» — как в карточке
    label: str        # короткая суть варианта («перезаполнять освободившийся бюджет»)
    recommended: bool

    @property
    def callback_choice(self) -> str:
        """Часть callback_data. Нормализуем регистр — иначе «B» и «b» разъедутся."""
        return self.num.lower()


def _section_lines(body: str) -> List[str]:
    """Строки секции «Что от тебя нужно». Пустой список — секции нет."""
    out: List[str] = []
    inside = False
    for ln in body.splitlines():
        stripped = ln.strip()
        if stripped.startswith("##"):
            low = stripped.lower()
            # Новый заголовок закрывает секцию — иначе «Вариант» из секции «Что будет
            # после» уехал бы в кнопки как ещё один выбор.
            inside = any(low.startswith(h) for h in _NEED_HEADINGS)
            continue
        if inside:
            out.append(ln)
    return out


def _capitalize(text: str) -> str:
    """Заглавная первая буква. ``str.capitalize`` не годится — он гасит регистр остального
    («ADR-053» стал бы «Adr-053»)."""
    return text[:1].upper() + text[1:] if text else text


def _shorten(text: str, limit: int = BUTTON_LABEL_MAX) -> str:
    """Обрезать по границе слова, добавив многоточие. Никогда не рвём слово пополам."""
    text = text.strip().rstrip(".;,")
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;:—–-") + "…"


def parse_options(body: str) -> List[ParsedOption]:
    """Варианты ответа из тела карточки. Пусто ⇒ кнопок не будет (fail-CLOSED).

    Разбираем ТОЛЬКО секцию «Что от тебя нужно»: в карточках слово «вариант» встречается
    и в «Что будет после», и в разборе причин — там это не выбор владельца.
    """
    options: List[ParsedOption] = []
    seen: set[str] = set()
    for ln in _section_lines(body):
        m = _OPTION_RE.match(ln)
        if not m:
            continue
        num = m.group("num").strip()
        key = num.lower()
        if key in seen:  # дубль номера в карточке — берём первый, второй игнорируем
            continue
        paren = m.group("paren") or ""
        # Точка в конце — часть предложения карточки, а не подписи кнопки: «Вариант 1.»
        # с точкой посреди списка читается как оборванный текст.
        label = m.group("label").strip().rstrip(" .")
        recommended = bool(_RECOMMEND_RE.search(paren) or _RECOMMEND_RE.search(label))
        seen.add(key)
        options.append(ParsedOption(num=num, label=label, recommended=recommended))
    return options


# ── идентификатор карточки в callback_data ───────────────────────────────────


def make_pid(card_id: str) -> str:
    """Короткий стабильный идентификатор карточки для callback_data.

    Стабильный (хэш от имени файла, без времени): повторная отправка той же карточки
    обязана давать ТОТ ЖЕ pid, иначе старое сообщение в переписке становится мёртвым —
    владелец жмёт кнопку вчерашнего пуша и не получает ничего.
    """
    return hashlib.sha256(card_id.encode("utf-8")).hexdigest()[:PID_LEN]


def build_callback(pid: str, choice: str) -> str:
    """``act:od:<pid>:<choice>``. Гарантированно в лимите Telegram."""
    data = f"{CALLBACK_PREFIX}{pid}:{choice}"
    if len(data.encode("utf-8")) > CALLBACK_MAX_BYTES:  # pragma: no cover — защита от будущих правок
        raise ValueError(f"callback_data too long: {data!r}")
    return data


def parse_callback(data: str) -> Optional[Tuple[str, str]]:
    """``act:od:<pid>:<choice>`` → ``(pid, choice)``; не наш формат → ``None``."""
    if not data.startswith(CALLBACK_PREFIX):
        return None
    rest = data[len(CALLBACK_PREFIX):]
    if ":" not in rest:
        return None
    pid, choice = rest.split(":", 1)
    if not pid or not choice:
        return None
    return pid, choice


# ── журнал отправленных решений ──────────────────────────────────────────────


def _load(path: Path) -> Dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("pushes"), list):
            return doc
    except Exception:  # noqa: BLE001 — битый журнал не имеет права мешать доставке
        pass
    return {"schema_version": 1, "pushes": []}


def _save(doc: Dict, path: Path) -> None:
    doc["pushes"] = doc["pushes"][-HISTORY_MAX:]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(doc, str(path))


def find_push(pid: str, *, state_path: Optional[str | Path] = None) -> Optional[Dict]:
    """Запись журнала по pid (последняя). ``None`` — не находили такой карточки."""
    doc = _load(_state_path(state_path))
    for rec in reversed(doc["pushes"]):
        if rec.get("pid") == pid:
            return rec
    return None


# ── человеческий текст сообщения ─────────────────────────────────────────────

_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.DOTALL)
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")

_WHAT_HEADINGS = ("## что случилось", "## what happened")

SUMMARY_MAX = 600


def _plain(text: str) -> str:
    """Markdown → человеческий текст. Разметку убираем, СОДЕРЖИМОЕ оставляем."""
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_ITALIC.sub(r"\1", text)
    text = _MD_CODE.sub(r"\1", text)
    return text


def summarize(body: str, limit: int = SUMMARY_MAX) -> str:
    """«Что случилось» простыми словами — из одноимённой секции карточки.

    Секции нет ⇒ первый осмысленный абзац тела. Обрезаем по границе ПРЕДЛОЖЕНИЯ:
    оборванная на полуслове тревога читается как сбой, а не как краткость.
    """
    lines: List[str] = []
    inside = False
    saw_section = False
    for ln in body.splitlines():
        stripped = ln.strip()
        if stripped.startswith("##"):
            low = stripped.lower()
            inside = any(low.startswith(h) for h in _WHAT_HEADINGS)
            saw_section = saw_section or inside
            continue
        if inside:
            lines.append(stripped)
    if not saw_section:
        for ln in body.splitlines():
            stripped = ln.strip()
            if stripped and not stripped.startswith(("#", "---")):
                lines.append(stripped)

    text = _plain(" ".join(x for x in lines if x)).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "; ", ", "):
        if sep in cut:
            head = cut.rsplit(sep, 1)[0]
            if len(head) > limit // 2:
                return head + "…"
    return _shorten(cut, limit)


def build_message(title: str, body: str, options: List[ParsedOption]) -> str:
    """HTML-сообщение владельцу: заголовок, суть, перечень вариантов.

    HTML, а не Markdown: в карточках сплошь пути с подчёркиваниями (`agent_health`),
    на которых Markdown отдаёт 400 (урок telegram-alerts).
    """
    parts = [
        "🧑‍⚖️ <b>Нужно твоё решение</b>",
        "",
        f"<b>{html.escape(title)}</b>",
    ]
    summary = summarize(body)
    if summary:
        parts += ["", html.escape(summary)]
    if options:
        parts += ["", "<b>Варианты:</b>"]
        for opt in options:
            star = " ⭐ <i>рекомендую</i>" if opt.recommended else ""
            label = html.escape(_capitalize(opt.label))
            parts.append(f"<b>{html.escape(opt.num)}.</b> {label}{star}")
        parts += ["", "Нажми кнопку — запишу решение и возьму в работу."]
    else:
        # Fail-CLOSED: вариантов не разобрали — не выдумываем их, честно зовём в карточку.
        parts += ["", "Вариантов в карточке не нашёл — открой её целиком кнопкой ниже."]
    return "\n".join(parts)


def build_keyboard(pid: str, options: List[ParsedOption]) -> Dict:
    """Inline-клавиатура: по кнопке на вариант (⭐ у рекомендованного) + «Подробнее».

    По одной кнопке в ряд: подписи вариантов длинные, в два столбца Telegram их режет.
    """
    rows: List[List[Dict]] = []
    for opt in options:
        star = "⭐ " if opt.recommended else ""
        label = f"{star}{opt.num}. {_capitalize(_shorten(opt.label))}"
        rows.append([{"text": label,
                      "callback_data": build_callback(pid, opt.callback_choice)}])
    rows.append([{"text": "📖 Подробнее", "callback_data": build_callback(pid, "more")}])
    return {"inline_keyboard": rows}


# ── подготовка и отправка ────────────────────────────────────────────────────

MORE_CHOICE = "more"  # не выбор варианта, а «покажи карточку целиком»


@dataclass(frozen=True)
class Prepared:
    """Готовое к отправке решение: текст всегда, клавиатура — если её есть кому обработать."""

    pid: str
    text: str
    keyboard: Optional[Dict]
    options: List[ParsedOption]


def prepare(
    title: str,
    body: str,
    card_id: str,
    *,
    now: Optional[datetime] = None,
    beacon_path: Optional[str | Path] = None,
) -> Prepared:
    """Собрать сообщение и клавиатуру. Текст уходит ВСЕГДА, кнопки — по условиям.

    Кнопок не будет, если:

    * в карточке не разобрано ни одного варианта (fail-CLOSED — не выдумываем выбор);
    * не жив бот, умеющий обработать нажатие (тот же маячок, что у алертов, ADR-069):
      нажатие по старому боту уходит в неизвестный ``act:``-глагол и ПЕРЕПИСЫВАЕТ
      сообщение панелью настроек, то есть стирает сам вопрос.

    Само уведомление при этом НЕ подавляется: решение владельца важнее украшений.
    """
    options = parse_options(body)
    pid = make_pid(card_id)
    text = build_message(title, body, options)
    keyboard = None
    if options:
        from spa_core.telegram.alert_actions import handler_available

        if handler_available(now=now, beacon_path=beacon_path):
            keyboard = build_keyboard(pid, options)
    return Prepared(pid=pid, text=text, keyboard=keyboard, options=options)


def register_push(
    card_path: str | Path,
    title: str,
    body: str,
    *,
    now: Optional[datetime] = None,
    state_path: Optional[str | Path] = None,
    beacon_path: Optional[str | Path] = None,
) -> Prepared:
    """Подготовить сообщение и запомнить карточку под её ``pid``.

    Журнал нужен, чтобы в момент нажатия (через час, через три дня) знать, ЧТО именно
    предлагалось: ``callback_data`` несёт только номер варианта, а текст варианта обязан
    попасть в карточку дословно.
    """
    p = Path(card_path)
    prep = prepare(title, body, p.stem, now=now, beacon_path=beacon_path)
    dt = now or datetime.now(timezone.utc)
    path_obj = _state_path(state_path)
    doc = _load(path_obj)
    doc["pushes"] = [r for r in doc["pushes"] if r.get("pid") != prep.pid]
    doc["pushes"].append({
        "pid": prep.pid,
        "card": str(p),
        "card_id": p.stem,
        "title": title,
        "pushed_at": dt.isoformat(),
        "options": [{"num": o.num, "label": o.label, "recommended": o.recommended}
                    for o in prep.options],
        "choice": None,
    })
    _save(doc, path_obj)
    return prep


def record_choice(
    pid: str,
    choice: str,
    actor_chat_id,
    *,
    owner_chat_id: Optional[str] = None,
    now: Optional[datetime] = None,
    state_path: Optional[str | Path] = None,
) -> Dict:
    """Нажатие владельца: записать выбор в карточку. Никогда не бросает.

    Возвращает словарь с ``ok`` и ``reason``; отказ — это нормальный ответ, а не авария:
    сообщение владельцу должно быть человеческим при любом исходе.
    """
    from spa_core.owner_queue.owner_answer import NotTheOwner, record_owner_answer

    path_obj = _state_path(state_path)
    doc = _load(path_obj)
    rec = None
    for r in reversed(doc["pushes"]):
        if r.get("pid") == pid:
            rec = r
            break
    if rec is None:
        return {"ok": False, "reason": "unknown_card"}

    opt = None
    for o in rec.get("options") or []:
        if str(o.get("num", "")).lower() == str(choice).lower():
            opt = o
            break
    if opt is None:
        return {"ok": False, "reason": "unknown_option", "card": rec.get("card")}

    card_path = Path(rec["card"])
    if not card_path.exists():
        return {"ok": False, "reason": "card_gone", "card": str(card_path)}

    try:
        res = record_owner_answer(
            card_path,
            choice_num=str(opt["num"]),
            choice_label=str(opt.get("label") or ""),
            actor_chat_id=actor_chat_id,
            owner_chat_id=owner_chat_id,
            now=now,
        )
    except NotTheOwner:
        return {"ok": False, "reason": "not_owner", "card": str(card_path)}
    except Exception as exc:  # noqa: BLE001 — сбой записи не имеет права ронять бота
        return {"ok": False, "reason": "write_failed", "detail": type(exc).__name__}

    rec["choice"] = str(opt["num"])
    rec["choice_label"] = str(opt.get("label") or "")
    rec["answered_at"] = res.get("answered_at")
    _save(doc, path_obj)
    return {"ok": True, "already": bool(res.get("already")), "card": str(card_path),
            "choice": str(opt["num"]), "label": str(opt.get("label") or "")}


# ── ответ владельцу после нажатия ────────────────────────────────────────────

# Причина отказа → фраза владельцу. Реестр, а не ветвление в коде: владелец в отпуске
# не смотрит логи, и «кнопка молча ничего не сделала» для него неотличимо от поломки.
_REASON_RU: Dict[str, str] = {
    "unknown_card": ("Не нашёл эту карточку — сообщение старое, и журнал её уже не помнит. "
                     "Открой актуальный список кнопкой ниже."),
    "unknown_option": "Такого варианта в этой карточке нет — ничего не записал.",
    "card_gone": "Карточка исчезла из трекера — ничего не записал.",
    "not_owner": "Это решение может принять только владелец — ничего не записал.",
    "write_failed": "Не смог записать решение. В карточке ничего не изменилось.",
}


def confirmation_text(result: Dict) -> str:
    """Человеческий ответ на нажатие. Любой исход — внятная фраза, без кодов ошибок."""
    if result.get("ok"):
        num = html.escape(str(result.get("choice", "")))
        label = html.escape(_capitalize(str(result.get("label") or "")))
        if result.get("already"):
            return (f"👌 Это решение уже записано: <b>вариант {num}</b> — {label}.\n"
                    f"Повторно ничего не менял.")
        return (f"✅ Записал: <b>вариант {num}</b> — {label}.\n"
                f"Карточка закрыта твоим решением, беру в работу.")
    reason = str(result.get("reason") or "")
    if reason.startswith("crash:"):
        return "⚠️ Сбой при записи решения. В карточке ничего не изменилось."
    return "⚠️ " + _REASON_RU.get(reason, "Не смог записать решение — ничего не изменилось.")


def pending_decisions(
    *,
    tracker_dir: Optional[str | Path] = None,
    state_path: Optional[str | Path] = None,
    now: Optional[datetime] = None,
    register: bool = True,
) -> List[Dict]:
    """Открытые решения владельца (``needs-owner``), готовые к показу в меню.

    Заодно РЕГИСТРИРУЕТ их в журнале: экран списка — самостоятельный вход, владелец мог
    ни одного пуша не получить (бот лежал, связи не было). Без регистрации pid из списка
    не с чем сопоставить, и кнопка на экране оказалась бы мёртвой.

    Никогда не бросает: сломанный трекер не имеет права уронить меню.
    """
    try:
        from spa_core.owner_queue.queue import list_cards

        kwargs = {"tracker_type": "owner-decision", "status": "needs-owner"}
        if tracker_dir is not None:
            kwargs["tracker_dir"] = tracker_dir
        cards = list(list_cards(**kwargs))
    except Exception:  # noqa: BLE001
        return []

    out: List[Dict] = []
    for card in cards:
        try:
            options = parse_options(card.body)
            pid = make_pid(card.path.stem)
            if register:
                register_push(card.path, card.title or card.path.stem, card.body,
                              now=now, state_path=state_path,
                              beacon_path=None)
            out.append({"pid": pid, "title": card.title or card.path.stem,
                        "card": str(card.path), "options": options})
        except Exception:  # noqa: BLE001 — одна кривая карточка не прячет остальные
            continue
    return out


def card_details(
    pid: str,
    *,
    limit: int = 3500,
    state_path: Optional[str | Path] = None,
) -> str:
    """Карточка целиком, человеческим текстом (кнопка «Подробнее»).

    Разметку снимаем: владельцу едет текст, а не звёздочки. Режем по лимиту Telegram —
    сообщение длиннее 4096 просто не доставляется, и кнопка выглядит сломанной.
    """
    rec = find_push(pid, state_path=state_path)
    if rec is None:
        return "⚠️ " + _REASON_RU["unknown_card"]
    path = Path(rec.get("card") or "")
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — карточку могли переместить/переименовать
        return "⚠️ " + _REASON_RU["card_gone"]
    # Frontmatter владельцу не нужен — это служебное.
    body = raw.split("---", 2)[2] if raw.startswith("---") and raw.count("---") >= 2 else raw
    text = _plain(body).strip()
    head = f"📖 <b>{html.escape(str(rec.get('title') or path.stem))}</b>\n\n"
    room = max(0, limit - len(head))
    if len(text) > room:
        text = text[:room].rstrip() + "…"
    return head + html.escape(text)
