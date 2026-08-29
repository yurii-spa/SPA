"""Лестница устаревания наблюдения: когда протокол перестаёт быть виден.

# LLM_FORBIDDEN

**ADR-167** (решение владельца 2026-08-29, вариант 1) вводит вторую ступень,
которую ADR-060 §3 объявил, но никто не реализовал: протокол, наблюдение по
которому старше **168 ч**, уходит в де-риск-канал — держимая позиция
принудительно сокращается.

Лестница целиком:

| Ступень | Окно | Эффект |
|---|---|---|
| `FRESH` | ≤ 36 ч | обычная жизнь: участвует в новой аллокации |
| `SOFT_STALE` | 36…168 ч | новых денег не даём, держимое НЕ трогаем |
| `HARD_STALE` | > 168 ч | **де-риск: держимое сокращается** (ADR-167) |

**Почему модуль отдельный — и поправка к первой редакции этого абзаца.**
Сначала здесь было написано, что «возраст наблюдения жил тремя разными числами»
и что 48 ч в `analytics/tier_curator` не имеют обоснования. **Проверка это
опровергла:** обоснование у 48 ч есть — оно написано рядом со строкой («двое
суток покрывают выходной цикла»), просто не в ADR. И числа не дублируют друг
друга: они отвечают на РАЗНЫЕ вопросы —

* **36 ч** (аллокатор) — брать ли в НОВУЮ аллокацию;
* **48 ч** (куратор) — считать ли наблюдение доказательством для суждения о ТИРЕ;
* **168 ч** (здесь) — ослеп ли протокол насовсем.

Лестница 36 ≤ 48 ≤ 168 осмысленна. Настоящий риск в другом: ступени объявлены
порознь и ничем не связаны, так что поднять одну, не тронув соседнюю, можно молча.
Это держит `spa_core/tests/test_evidence_age_ladder_is_ordered.py`; мягкое окно
здесь сверяется с аллокатором тестом, чтобы не завести его копию.

**Массовая слепота ≠ рынок.** Если ненаблюдаемыми стали ВСЕ держимые протоколы
разом, это симптом НАШЕЙ поломки, а не смерти рынка: 2026-08-04 одна сетевая
икота обнулила `live_apy` у 34 адаптеров сразу. В таком случае канал возвращает
`MASS_BLINDNESS` и НЕ требует сокращения — поднимается тревога. Эвакуировать книгу
по собственной аварии хуже, чем подождать.

Модуль ничего не пишет и не двигает: он ОТВЕЧАЕТ, кого надо сократить.
Исполнение — штатный ребаланс (ADR-167: не forced-sell).

stdlib · детерминирован · часы инъектируются.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

#: Ступень 1 — не берём в НОВУЮ аллокацию. Зеркалит `allocator._EVIDENCE_MAX_AGE_H`
#: (ADR-060 §3, колонка paper). Тест сверяет их равенство.
SOFT_STALE_H = 36.0

#: Ступень 2 — де-риск. ADR-167, решение владельца: «сделать как записано».
HARD_STALE_H = 168.0

FRESH = "FRESH"
SOFT_STALE = "SOFT_STALE"
HARD_STALE = "HARD_STALE"
UNKNOWN_AGE = "UNKNOWN_AGE"

#: Вердикт канала целиком.
ACTION_NONE = "NONE"
ACTION_DERISK = "DERISK"
ACTION_MASS_BLINDNESS = "MASS_BLINDNESS"


@dataclass(frozen=True)
class ProtocolStaleness:
    protocol: str
    stage: str
    age_hours: Optional[float]
    held_usd: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeriskDecision:
    action: str
    generated_at: str
    to_derisk: list = field(default_factory=list)     # ProtocolStaleness
    all_protocols: list = field(default_factory=list)  # ProtocolStaleness
    reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("to_derisk", "all_protocols"):
            d[k] = [x.to_dict() if isinstance(x, ProtocolStaleness) else x for x in d[k]]
        return d


def _parse(ts: object) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        parsed = datetime.fromisoformat(ts.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def stage_for(as_of: object, now: datetime,
              soft_h: float = SOFT_STALE_H, hard_h: float = HARD_STALE_H) -> tuple:
    """(ступень, возраст_в_часах, причина) для одной отметки наблюдения.

    Судим по ВОЗРАСТУ наблюдения, а не по «последний запрос не удался»
    (ADR-167; урок 2026-08-04). Неразбираемая отметка — `UNKNOWN_AGE`,
    а не «свежо»: молчание о времени не есть свежесть.
    """
    ts = _parse(as_of)
    if ts is None:
        return UNKNOWN_AGE, None, f"отметка времени не разобрана: {as_of!r}"
    age = (now - ts).total_seconds() / 3600.0
    if age < 0:
        return UNKNOWN_AGE, age, f"отметка из будущего ({as_of!r})"
    if age <= soft_h:
        return FRESH, age, f"наблюдение свежее ({age:.1f} ч ≤ {soft_h:.0f} ч)"
    if age <= hard_h:
        return SOFT_STALE, age, (
            f"наблюдение устарело ({age:.1f} ч), новых денег не даём; "
            f"держимое не трогаем до {hard_h:.0f} ч")
    return HARD_STALE, age, (
        f"наблюдения нет {age:.1f} ч > {hard_h:.0f} ч — де-риск по ADR-167")


def decide(
    held_usd: dict,
    observed_at: dict,
    now: Optional[datetime] = None,
    soft_h: float = SOFT_STALE_H,
    hard_h: float = HARD_STALE_H,
) -> DeriskDecision:
    """Кого надо сократить по слепоте.

    ``held_usd`` — держимые суммы; ``observed_at`` — отметка последнего
    НАБЛЮДЕНИЯ по протоколу. Протокол без отметки считается ненаблюдаемым
    с неизвестным возрастом (``UNKNOWN_AGE``) и в де-риск НЕ попадает:
    сокращать по незнанию возраста — это угадывание, а канал построен
    на измерении.
    """
    now = now or datetime.now(timezone.utc)
    d = DeriskDecision(action=ACTION_NONE, generated_at=now.isoformat())

    held = {p: float(v) for p, v in (held_usd or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0}
    if not held:
        d.reason = "нет держимых позиций — сокращать нечего"
        return d

    for proto in sorted(held):
        stage, age, why = stage_for((observed_at or {}).get(proto), now, soft_h, hard_h)
        d.all_protocols.append(ProtocolStaleness(proto, stage, age, held[proto], why))

    d.to_derisk = [x for x in d.all_protocols if x.stage == HARD_STALE]

    # Массовая слепота: НИ ОДИН держимый протокол не наблюдается свежо.
    # Это симптом нашей поломки (04.08: одна икота обнулила 34 адаптера),
    # и эвакуировать книгу по собственной аварии хуже, чем подождать.
    fresh = [x for x in d.all_protocols if x.stage == FRESH]
    if not fresh and len(d.all_protocols) > 1:
        d.action = ACTION_MASS_BLINDNESS
        d.reason = (
            f"ни один из {len(d.all_protocols)} держимых протоколов не наблюдается "
            "свежо — это симптом НАШЕЙ поломки, а не рынка. Де-риск НЕ запускается, "
            "поднимается тревога (ADR-167)")
        d.to_derisk = []
        return d

    if d.to_derisk:
        d.action = ACTION_DERISK
        d.reason = "; ".join(f"{x.protocol}: {x.reason}" for x in d.to_derisk)
    else:
        d.reason = "ни один держимый протокол не перешёл границу де-риска"
    return d
