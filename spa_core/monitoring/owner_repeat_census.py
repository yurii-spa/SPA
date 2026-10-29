#!/usr/bin/env python3
"""spa_core/monitoring/owner_repeat_census.py — ПОВТОР просьбы владельца как измеряемый сигнал.

**Замер, ради которого модуль написан (цикл #976, ADR-859; исполнено #977).** В очереди
заданий стояло **37** карточек `new`, и ВСЕ ПЯТЬ голосовых заданий владельца были одной и
той же просьбой — «проверь дашборд», сказанной 15.10 · 16.10 · 16.10 · 17.10 · 24.10. Ни
один цикл не взял её за десять дней, а владелец повторял. **Повтор и есть его способ
сказать, что ничего не произошло** — и этого не мерил никто.

Сторож голодания (`scripts/check_owner_order_starvation.py`) эту форму не видит ПО
ПОСТРОЕНИЮ: он называет голодающим приказ с приоритетом `critical` и явным маркером
``## УКАЗАНИЕ ВЛАДЕЛЬЦА``. Голосовое задание рождается БЕЗ приоритета (без приоритета 33
из 37) и без маркера — то есть по старой мерке его голод равен нулю, сколько бы раз
владелец ни повторил. Пять одинаковых `new` от владельца — сигнал сильнее, чем одна
`in-progress` карточка, и до #977 у него не было ни числа, ни читателя.

**Что меряется.** Карточки, которые ещё НЕ взяты (`new` / `backlog`), пришедшие СОБСТВЕННЫМ
каналом владельца (`source` из :data:`OWNER_CHANNELS`), группируются по НОРМАЛИЗОВАННОМУ
заголовку. Группа из двух и более карточек — находка: первая просьба не исполнена, иначе
второй бы не было.

**Три исхода различимы** (инв. #17) и у каждого своё ЗНАЧЕНИЕ, а не оттенок молчания:

* :data:`REPEATED` — повтор измерен, у него есть число (сколько просьб, за сколько суток);
* :data:`MEASURED_ZERO` — очередь прочитана, повторов нет. Это ответ, а не тишина;
* :data:`UNMEASURED` — очередь прочитать не удалось. Пустой список здесь запрещён:
  «повторов нет» — самое успокоительное из прочтений, и ровно оно десять суток скрывало
  просьбу владельца.

**Чего мера НЕ делает — названо, а не умолчано.**

1. **Ловит только ДОСЛОВНЫЙ повтор** (с точностью до регистра, пробелов и краевой
   пунктуации — :func:`normalise_request`). «Посмотри дашборд» и «проверь дашборд» для
   неё две разные просьбы. Это семантика, и мера её не притязает: лучше честное
   занижение, чем сведение разных просьб в одну группу.
2. **Население — только каналы собственных слов владельца** (`voice`, `telegram`).
   `source: nimbalyst` в него НЕ входит намеренно: этим каналом рождаются карточки
   находок самих агентов (замер 29.10 — 258 штук в статусе `new`), и включение его
   утопило бы сигнал в шуме своего же производства. Цена названа: просьба, набранная
   владельцем прямо в Nimbalyst, этой мерой не видна.
3. **Не судит, ВЕРНА ли просьба и выполнима ли она.** Повтор — свидетельство о том, что
   ответа не было, а не о предмете.
4. **Не закрывает карточки и ничего не пишет.** Модуль только ЧИТАЕТ (`applied=False`);
   сведение дублей — заработанное освобождение через интейк (ADR-377), не следствие замера.

Только stdlib, детерминированно, без сети. Часы — ВХОД (`now`), а не окружение.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime, timezone
from pathlib import Path

#: Карточка ещё НЕ взята в работу. Тот же смысл, что `STARVING_STATUSES` у сторожа
#: голодания; второй копии порога здесь нет — список короткий и свой, потому что
#: предмет другой: там статус `in-progress` проверяется на живого держателя, здесь
#: взятая карточка из населения просто выходит (её уже кто-то читает).
UNTAKEN_STATUSES = ("new", "backlog")

#: Каналы СОБСТВЕННЫХ слов владельца. См. п. 2 «чего мера не делает»: `nimbalyst`
#: сюда не входит намеренно — это канал находок агентов, а не просьб владельца.
OWNER_CHANNELS = ("voice", "telegram")

#: Сколько одинаковых просьб уже есть повтор. Два — потому что вторая просьба и
#: означает, что первая не исполнена; ждать третьей значило бы назначить владельцу
#: цену ещё одного захода.
DEFAULT_MIN_REPEATS = 2

#: Рода исхода. Значения, а не оттенки молчания (инв. #17).
REPEATED = "repeated"
MEASURED_ZERO = "measured_zero"
UNMEASURED = "unmeasured"

#: Краевая пунктуация, которую нормализация снимает. Внутренняя остаётся: «проверь,
#: дашборд» и «проверь дашборд» мера различает — внутренняя пунктуация меняет фразу.
_EDGE_PUNCT = " \t\r\n!?.,;:…\"'«»„“”()[]{}-–—*_#"


def normalise_request(title) -> str | None:
    """Нормализованный ключ просьбы: NFKC → casefold → один пробел → снять края.

    ``None`` — заголовка нет либо после нормализации он пуст: такая карточка в
    население не входит (сравнивать нечего), и это НЕ то же самое, что «повторов нет».
    """
    if not title:
        return None
    s = unicodedata.normalize("NFKC", str(title)).casefold()
    s = " ".join(s.split())
    s = s.strip(_EDGE_PUNCT)
    return s or None


def _created(card) -> str | None:
    """Объявленная дата рождения карточки (`created` во frontmatter) либо None."""
    fields = getattr(card, "fields", None) or {}
    raw = fields.get("created")
    return str(raw).strip() if raw else None


def _as_day(raw: str | None) -> datetime | None:
    """``YYYY-MM-DD`` (возможно с временем) → полночь UTC этой даты, либо None.

    None означает «дата НЕ РАЗОБРАНА», и вызывающий обязан нести это дальше третьим
    исходом, а не нулём суток: «просьба прозвучала сегодня» — оправдание простоя.
    """
    if not raw:
        return None
    head = raw.strip().split("T")[0].split(" ")[0]
    try:
        return datetime.strptime(head, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _owner_channel(card) -> str | None:
    """Канал карточки, если это СОБСТВЕННЫЙ канал владельца; иначе None."""
    fields = getattr(card, "fields", None) or {}
    src = str(fields.get("source") or "").strip().lower()
    return src if src in OWNER_CHANNELS else None


def repeated_requests(cards, *, now: datetime, min_repeats: int = DEFAULT_MIN_REPEATS,
                      source: str = "дерево") -> list[dict]:
    """Группы ОДИНАКОВЫХ непринятых просьб владельца, от самой многочисленной.

    ``cards`` — карточки очереди (`queue.Card`). ``now`` — часы ВХОДОМ: без этого мера
    отвечала бы про календарь прогона, а не про предмет (`.claude/rules/deployment.md`,
    раздел про время в тестах).

    ``source`` — из какой КОПИИ очереди пришли карточки («дерево» / `origin/main`). Едет
    в находку: `nimbalyst-local/` в прод-дерево не возит никто, и у одной просьбы две
    копии расходятся по статусу — «где мы это увидели» часть ответа, а не украшение.

    Каждая группа несёт:
      ``key`` нормализованная просьба · ``title`` заголовок как его видел владелец ·
      ``count`` сколько просьб · ``cards`` пути, от старейшей · ``first_created`` /
      ``last_created`` объявленные даты краёв · ``span_days`` сутки между первой и
      последней просьбой · ``age_days`` сутки от первой просьбы до ``now`` ·
      ``dates_unparsed`` сколько дат не разобрано · ``source``.

    ``span_days`` / ``age_days`` равны ``None``, когда разобранных дат для величины не
    хватило. Это НЕ ноль: ноль суток означает «владелец повторил всё сегодня» и
    оправдывает простой, а неразобранная дата не оправдывает ничего.
    """
    buckets: dict[str, list] = {}
    for c in cards:
        status = (getattr(c, "status", "") or "").strip().lower()
        if status not in UNTAKEN_STATUSES:
            continue
        if _owner_channel(c) is None:
            continue
        key = normalise_request(getattr(c, "title", None))
        if key is None:
            continue
        buckets.setdefault(key, []).append(c)

    out: list[dict] = []
    for key, group in buckets.items():
        if len(group) < min_repeats:
            continue
        dated = [(_as_day(_created(c)), c) for c in group]
        # Ключ сортировки назван ЯВНО: при равной дате кортежи дошли бы до сравнения
        # самих карточек, а у них порядка нет — порядок внутри дня даёт путь файла,
        # и он же делает вывод детерминированным (а не зависящим от обхода каталога).
        parsed = sorted(((d, c) for d, c in dated if d is not None),
                        key=lambda pair: (pair[0], str(getattr(pair[1], "path", ""))))
        unparsed = sum(1 for d, _ in dated if d is None)
        ordered = [c for _, c in parsed] + [c for d, c in dated if d is None]
        first = parsed[0][0] if parsed else None
        last = parsed[-1][0] if parsed else None
        out.append({
            "key": key,
            "title": str(getattr(ordered[0], "title", "") or ""),
            "count": len(group),
            "cards": [str(getattr(c, "path", "")) for c in ordered],
            "first_created": first.date().isoformat() if first else None,
            "last_created": last.date().isoformat() if last else None,
            # Пролёт измерим только по ДВУМ разобранным краям; одна дата его не даёт.
            "span_days": (round((last - first).total_seconds() / 86400.0, 1)
                          if first and last and len(parsed) >= 2 else None),
            "age_days": (round((now - first).total_seconds() / 86400.0, 1)
                         if first else None),
            "dates_unparsed": unparsed,
            "source": source,
        })
    out.sort(key=lambda g: (-g["count"], g["key"]))
    return out


def merge_groups(tree: list[dict], ref: list[dict]) -> list[dict]:
    """Группы двух копий очереди в одну — fail-CLOSED, по ключу просьбы.

    Побеждает копия, в которой просьб БОЛЬШЕ: «в другом дереве её закрыли» просьбу
    владельца не отменяет, а повтор, который видно только на `origin/main`, — такой же
    повтор. При равном числе выигрывает первый аргумент порядка (`ref`), потому что
    `nimbalyst-local/` в прод-дерево не возит никто и origin-копия полнее.
    """
    best: dict[str, dict] = {}
    for g in [*ref, *tree]:
        cur = best.get(g["key"])
        if cur is None or g["count"] > cur["count"]:
            best[g["key"]] = g
    merged = list(best.values())
    merged.sort(key=lambda g: (-g["count"], g["key"]))
    return merged


def verdict_kind(groups: list[dict] | None) -> str:
    """Род исхода по результату меры: :data:`REPEATED` · :data:`MEASURED_ZERO` ·
    :data:`UNMEASURED`.

    ``None`` — очередь не прочитана, и это НЕ пустой список. Разница несущая: пустой
    список есть утверждение «повторов нет», ``None`` — «мы не смотрели».
    """
    if groups is None:
        return UNMEASURED
    return REPEATED if groups else MEASURED_ZERO


def render(groups: list[dict] | None, *, unmeasured_reason: str | None = None) -> str:
    """Строка для шага 0a: повтор НАЗВАН ЧИСЛОМ, а не словом «есть»."""
    if groups is None:
        why = f" ({unmeasured_reason})" if unmeasured_reason else ""
        return ("❓ ПОВТОР ПРОСЬБЫ ВЛАДЕЛЬЦА НЕ ИЗМЕРЕН — очередь не прочитана"
                f"{why}; это НЕ «повторов нет»")
    if not groups:
        return "✅ повторов непринятых просьб владельца не найдено (очередь прочитана)"
    total = sum(g["count"] for g in groups)
    lines = [f"🔁 ВЛАДЕЛЕЦ ПОВТОРИЛ ОДНУ И ТУ ЖЕ ПРОСЬБУ: групп {len(groups)}, "
             f"карточек {total} — первая просьба не исполнена, иначе второй бы не было:"]
    for g in groups:
        span = (f"за {g['span_days']:g} сут." if g["span_days"] is not None
                else "пролёт НЕ ИЗМЕРЕН (дата не разобрана)")
        age = (f"старейшей {g['age_days']:g} сут." if g["age_days"] is not None
               else "возраст НЕ ИЗМЕРЕН")
        unparsed = (f", дат не разобрано {g['dates_unparsed']}"
                    if g["dates_unparsed"] else "")
        lines.append(f"  - «{g['title']}» × {g['count']} ({span}, {age}{unparsed}) "
                     f"[копия: {g['source']}]")
        for p in g["cards"]:
            lines.append(f"      ↳ {Path(p).name if p else '(без пути)'}")
    return "\n".join(lines)


# ── эталон класса: контроль в ОБЕ стороны, на настоящей мере ──────────────────
#: Сцены эталона отличаются РОВНО одним: во второй у просьбы нет второй карточки.
#: Мера, отвечающая на них одинаково, и есть дефект, против которого модуль написан.
DRIVE_DISTINGUISHES = "distinguishes"
DRIVE_CONFLATES = "conflates"
DRIVE_UNMEASURED = "drive_unmeasured"


class _Card:
    """Карточка сцены — поля, которые читают ОБЕ оси шага 0a.

    `priority` и `body` мере повторов не нужны, и всё-таки они здесь: сцена обязана
    выглядеть настоящей карточкой и для ПРЕЖНЕЙ мерки (`starving_owner_orders` читает
    приоритет и тело), иначе контроль «прежняя ось слепа к повтору» падал бы на форме
    сцены, а не отвечал на свой вопрос. Голосовое задание рождается без приоритета и
    без маркера приказа — умолчания ровно это и воспроизводят.
    """

    def __init__(self, name: str, title: str, status: str, source: str, created: str,
                 priority: str | None = None, body: str = ""):
        self.path = Path(name)
        self.title = title
        self.status = status
        self.priority = priority
        self.body = body
        self.fields = {"source": source, "created": created}


def drive_exemplar(*, now: datetime | None = None) -> dict:
    """Прогнать НАСТОЯЩУЮ меру на двух сценах, отличающихся РОВНО повтором.

    Возвращает ``{"kind": ..., "scene_repeated": {...}, "scene_single": {...}}``.

    Зачем эталон, а не только тест: проба приёмки обязана мерить ИСХОД живой двери, а
    не наличие модуля (`.claude/rules/acceptance.md`, п. 3). Контроль собран так, чтобы
    падать на каждом порванном звене по отдельности — убери условие `min_repeats`, и
    сцена-одиночка даст находку; перестань читать `source`, и агентская карточка войдёт
    в население; перестань читать `status`, и взятая карточка вернётся в повтор.
    """
    now = now or datetime(2026, 10, 29, tzinfo=timezone.utc)
    try:
        repeated = repeated_requests([
            _Card("a.md", "проверь дашборд", "new", "voice", "2026-10-15"),
            _Card("b.md", "Проверь  дашборд.", "new", "voice", "2026-10-24"),
            # Шум, который в население входить НЕ ДОЛЖЕН: чужой канал, взятая
            # карточка и одиночная просьба — каждая отключает своё звено меры.
            _Card("c.md", "проверь дашборд", "new", "nimbalyst", "2026-10-16"),
            _Card("d.md", "проверь дашборд", "in-progress", "voice", "2026-10-16"),
            _Card("e.md", "проверь телеграм", "new", "voice", "2026-10-16"),
        ], now=now)
        single = repeated_requests([
            _Card("a.md", "проверь дашборд", "new", "voice", "2026-10-15"),
            _Card("c.md", "проверь дашборд", "new", "nimbalyst", "2026-10-16"),
            _Card("d.md", "проверь дашборд", "in-progress", "voice", "2026-10-16"),
            _Card("e.md", "проверь телеграм", "new", "voice", "2026-10-16"),
        ], now=now)
    except Exception as exc:  # noqa: BLE001 — мера могла упасть как угодно
        return {"kind": DRIVE_UNMEASURED,
                "reason": f"{type(exc).__name__}: {exc}"}
    left, right = verdict_kind(repeated), verdict_kind(single)
    scene_repeated = {"outcome": left, "groups": repeated}
    scene_single = {"outcome": right, "groups": single}
    if left == right:
        return {"kind": DRIVE_CONFLATES, "scene_repeated": scene_repeated,
                "scene_single": scene_single}
    return {"kind": DRIVE_DISTINGUISHES, "scene_repeated": scene_repeated,
            "scene_single": scene_single}
