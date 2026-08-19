"""Собрать длинный документ владельца обратно из кусков, на которые его порезал Телеграм.

**Что измерено (цикл #306).** 13.08 владелец прислал спецификацию «TASK — Portfolio CIO»,
и интейк завёл **семь** карточек за 21 секунду. Шесть из них — не задания, а куски: заголовки
разделов («WHY IT EXISTS», «actual costs») и обрывки предложений («если тот же target можно
приблизить простым:»). Замер длин тел этих семи карточек:

    4088 · 4085 · 4086 · 4087 · 4080 · 4062 · 3346

Шесть из семи стоят вплотную к **4096** — предел одного сообщения Bot API. То есть резал НЕ наш
код: клиент Телеграма разбил один документ на семь сообщений, а интейк увидел семь независимых
заданий. Седьмой кусок (3346) — хвост, он короче предела и потому закрывает документ.

Отсюда признак, позиционный и детерминированный: **сообщение у самого предела — это клиент
говорит «дальше есть ещё»**. Сообщение короче предела документ закрывает. Ни разбора смысла, ни
LLM: только длина и порядок прихода.

**Почему это не косметика.** Протокол велит брать ОДНУ карточку за цикл. Взяв
`inbox-dlya-kazhdogo-etapa-pokazat`, сессия исполняла бы половину предложения без документа, из
которого она вырвана. Владелец общается с системой ТОЛЬКО через Телеграм (ADR-075/078) — любая
следующая длинная спецификация распалась бы так же.

**Fail-safe — слова владельца не теряются никогда.** Придержанные куски лежат на диске
(`data/telegram_pending_document.json`, атомарная запись), а не в памяти процесса, и уезжают
карточкой при ЛЮБОМ из исходов: пришёл короткий кусок (документ закрыт) · истекло окно
(`flush_expired`, зовётся каждым тактом опроса) · бот перезапустился (первый же успешный опрос
зовёт тот же `flush_expired`) · упёрлись в потолок частей. Худшее, что может случиться с
документом, — задержка на длину окна, но не потеря.

**Время — вход, а не окружение** (`.claude/rules/deployment.md`): каждая функция, судящая о
свежести буфера, принимает `now`. Литеральных дат в модуле нет.

stdlib-only. LLM здесь запрещён и не нужен: весь разбор — длина и порядок.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spa_core.utils.atomic import atomic_load, atomic_save
from spa_core.utils.live_paths import live_data_dir

#: Предел одного текстового сообщения Bot API. Клиент режет длинный текст по нему.
TELEGRAM_MAX_CHARS = 4096

#: Длина, начиная с которой сообщение считается ГОЛОВОЙ разрезанного документа.
#: Порог стоит НИЖЕ самого короткого наблюдённого куска (4062): клиент дорезает до
#: границы строки/слова, поэтому кусок всегда чуть меньше предела, и насколько именно —
#: зависит от текста. Запас 162 символа взят от измеренного минимума, а не назначен.
CONTINUATION_MIN_CHARS = 3900

#: Окно, внутри которого следующее сообщение считается продолжением. Замер: семь частей
#: приехали за 21 с (≈3.5 с между частями), так что 60 с — щедро с большим запасом и при
#: этом коротко настолько, что обычная переписка владельца в него не попадает.
WINDOW_S = 60.0

#: Потолки: поток кусков не имеет права буферизоваться бесконечно. Упёрлись — отдаём
#: карточкой то, что собрали (исход ``capped``), и начинаем заново.
MAX_PARTS = 40
MAX_TOTAL_CHARS = 200_000

STORE_NAME = "telegram_pending_document.json"

#: Форма ответа владельца на карточку решения: «1», «Ответ 2», «вариант 3».
#: Такое сообщение НЕ закрывает документ и НЕ приклеивается к нему — оно уходит своим
#: путём (`owner_decisions.resolve_text_answer`). Иначе открытый буфер съел бы решение
#: владельца, а инвариант #14 держится именно на том, что его слово доходит.
_OWNER_ANSWER_RE = re.compile(r"^\s*(?:ответ|вариант|option|answer)?\s*[№#]?\s*(\d{1,2})\s*[.)]?\s*$",
                              re.IGNORECASE)
_OWNER_ANSWER_MAX_CHARS = 40


@dataclass(frozen=True)
class Emit:
    """Готовый документ: его пора превратить в ОДНУ карточку."""

    chat_id: str
    text: str
    parts: int
    part_lengths: tuple[int, ...]
    reason: str  # closed · expired · capped


@dataclass(frozen=True)
class Hold:
    """Кусок придержан — ждём продолжение."""

    chat_id: str
    parts: int


def store_path(data_dir: Path | None = None) -> Path:
    """Файл придержанных кусков. ``data_dir`` — для песочницы теста."""
    return Path(data_dir or live_data_dir(Path(__file__).resolve().parents[2])) / STORE_NAME


def looks_truncated(text: str) -> bool:
    """Похоже ли, что клиент дорезал сообщение по пределу и дальше будет продолжение."""
    return len(text) >= CONTINUATION_MIN_CHARS


def looks_like_owner_answer(text: str) -> bool:
    """Похоже ли сообщение на ответ владельца номером варианта («Ответ 1»)."""
    return len(text) <= _OWNER_ANSWER_MAX_CHARS and bool(_OWNER_ANSWER_RE.match(text))


def join_parts(parts: list[str]) -> str:
    """Склеить куски обратно в документ.

    Разделитель — перевод строки, и это СУЖДЕНИЕ, а не замер: у всех семи наблюдённых
    кусков и начало, и конец приходятся на границу строки, то есть клиент резал по
    ``\\n``. Сохранился ли сам перевод строки в одном из кусков, по карточкам 13.08
    установить уже нельзя — тела там записаны через ``strip()``. Поэтому берём исход,
    который в худшем случае добавляет ПУСТУЮ строку, а не склеивает две строки в одну:
    потерянная граница строки в структурированном документе дороже лишней.
    """
    out: list[str] = []
    for i, part in enumerate(parts):
        if i and not (out[-1].endswith("\n") or part.startswith("\n")):
            out.append("\n")
        out.append(part)
    return "".join(out)


def _load(path: Path) -> dict[str, Any]:
    doc = atomic_load(str(path), default=None)
    if not isinstance(doc, dict):
        return {"version": 1, "pending": {}}
    pending = doc.get("pending")
    if not isinstance(pending, dict):
        pending = {}
    return {"version": 1, "pending": pending}


def _emit_from(chat_id: str, entry: dict[str, Any], reason: str) -> Emit:
    parts = [p for p in entry.get("parts", []) if isinstance(p, str)]
    return Emit(
        chat_id=chat_id,
        text=join_parts(parts),
        parts=len(parts),
        part_lengths=tuple(len(p) for p in parts),
        reason=reason,
    )


def offer(chat_id: str, text: str, *, now: float,
          data_dir: Path | None = None) -> tuple[list[Emit], Hold | None, bool]:
    """Предъявить сборщику очередное сообщение владельца.

    Возвращает ``(emits, hold, passthrough)``:

    * ``emits`` — документы, готовые стать карточками (может быть непусто и тогда, когда
      текущее сообщение сборщика не касается: так уезжает протухший буфер);
    * ``hold`` — текущее сообщение придержано, ждём продолжение;
    * ``passthrough`` — ТЕКУЩЕЕ сообщение сборщик не тронул, бот обязан обработать его
      ровно как раньше (обычный путь: ответ владельца → классификатор).

    Ровно одно из ``hold``/``passthrough`` содержательно; если сообщение закрыло документ,
    оно уехало внутри последнего ``Emit`` и ``passthrough`` = False.
    """
    path = store_path(data_dir)
    doc = _load(path)
    pending: dict[str, Any] = doc["pending"]
    emits: list[Emit] = []
    hold: Hold | None = None
    passthrough = False

    entry = pending.get(chat_id)
    if isinstance(entry, dict) and entry.get("parts"):
        last_at = float(entry.get("last_at") or 0.0)
        if now - last_at > WINDOW_S:
            # Окно истекло: продолжение не пришло — отдаём собранное и разбираем
            # текущее сообщение с чистого листа.
            emits.append(_emit_from(chat_id, entry, "expired"))
            entry = None
            pending.pop(chat_id, None)
    else:
        entry = None

    if entry is None:
        if looks_truncated(text):
            pending[chat_id] = {"parts": [text], "first_at": now, "last_at": now}
            hold = Hold(chat_id=chat_id, parts=1)
        else:
            passthrough = True
    elif looks_like_owner_answer(text):
        # Открытый буфер не имеет права съесть решение владельца: документ закрываем
        # ТЕМ, ЧТО УЖЕ СОБРАНО, а само сообщение уходит своим путём.
        emits.append(_emit_from(chat_id, entry, "closed"))
        pending.pop(chat_id, None)
        passthrough = True
    else:
        parts = list(entry.get("parts", [])) + [text]
        entry = {"parts": parts, "first_at": entry.get("first_at", now), "last_at": now}
        total = sum(len(p) for p in parts)
        if not looks_truncated(text):
            emits.append(_emit_from(chat_id, entry, "closed"))
            pending.pop(chat_id, None)
        elif len(parts) >= MAX_PARTS or total >= MAX_TOTAL_CHARS:
            emits.append(_emit_from(chat_id, entry, "capped"))
            pending.pop(chat_id, None)
        else:
            pending[chat_id] = entry
            hold = Hold(chat_id=chat_id, parts=len(parts))

    atomic_save({"version": 1, "pending": pending}, str(path))
    return emits, hold, passthrough


def flush_expired(*, now: float, data_dir: Path | None = None) -> list[Emit]:
    """Отдать всё, чьё окно истекло. Зовётся каждым тактом опроса и при старте бота.

    Именно эта функция превращает «придержал» в «не потерял»: продолжение может не прийти
    никогда — владелец передумал, клиент оборвался, процесс перезапустился, — и тогда
    документ обязан уехать карточкой сам, без нового сообщения.
    """
    path = store_path(data_dir)
    doc = _load(path)
    pending: dict[str, Any] = doc["pending"]
    emits: list[Emit] = []
    for chat_id in list(pending):
        entry = pending[chat_id]
        if not isinstance(entry, dict) or not entry.get("parts"):
            pending.pop(chat_id, None)
            continue
        if now - float(entry.get("last_at") or 0.0) > WINDOW_S:
            emits.append(_emit_from(chat_id, entry, "expired"))
            pending.pop(chat_id, None)
    if emits:
        atomic_save({"version": 1, "pending": pending}, str(path))
    return emits


def provenance_note(emit: Emit) -> str:
    """Человеческая строка «как это приехало» — в тело карточки."""
    lengths = " + ".join(str(n) for n in emit.part_lengths)
    why = {
        "closed": "последний кусок короче предела — документ закрыт",
        "expired": f"продолжение не пришло за {int(WINDOW_S)} с — отдаём собранное",
        "capped": f"упёрлись в потолок ({MAX_PARTS} частей / {MAX_TOTAL_CHARS} символов)",
    }.get(emit.reason, emit.reason)
    return (
        f"Документ собран из **{emit.parts}** сообщений Телеграма: {lengths} символов "
        f"({why}). Клиент режет текст по пределу {TELEGRAM_MAX_CHARS} символов на сообщение — "
        f"это ОДИН документ владельца, а не {emit.parts} заданий."
    )
