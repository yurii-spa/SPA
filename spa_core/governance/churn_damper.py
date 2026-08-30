"""Ограничитель частоты перекладок на ЖИВОМ пути (ADR-168, решение владельца).

# LLM_FORBIDDEN

ADR-060 §3 задаёт минимальный срок удержания и недельный бюджет оборота, но эти
ручки управляли теневым каналом. Живой путь — цикл считает цель и перекладывает
книгу под неё — не был ограничен ничем.

Замер 29.08 по журналу сделок: **22 перекладки за 7 дней, оборот 5.3 капитала**,
издержки по нашей же модели **$1 288/нед** при недельном заработке книги **$87**.
Издержки превышали весь заработок в 15 раз.

Прогон ограничений по тем же 22 перекладкам:

| Правило | Прошло бы | Издержки/нед |
|---|---|---|
| как было | 22 | $1 288 |
| мин. 6 ч, бюджет 100 % | 3 | $188 |
| мин. 3 дня, бюджет 25 % (колонка paper) | 2 | **$78** |

Отсюда решение: ограничение безопасно при ЛЮБОМ ответе на вопрос «настоящие ли
скачки доходности» — максимум, что оно отнимает, это весь недельный заработок
($87), а экономит $1 210. Асимметрия 14 к 1.

**Чего ограничитель НЕ трогает — и это главное.** Ход, который только СОКРАЩАЕТ
позиции, не задерживается никогда. Де-риск, kill-switch, реакция на просадку и
на слепоту обязаны проходить мгновенно: «бюджет оборота исчерпан» не может быть
причиной не уйти из риска. Ограничивается только то, что двигает капитал МЕЖДУ
протоколами или наращивает экспозицию.

**При ошибке пропускаем, а не блокируем.** Ограничитель — не гейт безопасности;
если он не может решить, книга должна продолжать работать. Цена ошибочного
пропуска — одна лишняя перекладка; цена ошибочной блокировки — замороженная
книга. Решение логируется в обоих случаях.

Пороги НЕ выдуманы здесь: берутся из `TriggerParams.for_mode()` (ADR-060 §3),
той же колонки, что использует теневой канал. Четвёртой копии чисел не заводим.

stdlib · детерминирован · часы и журнал сделок инъектируются.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("spa.governance.churn_damper")

ALLOW = "ALLOW"
BLOCK = "BLOCK"

#: Причины пропуска
REASON_DERISK = "derisk_never_damped"
REASON_WITHIN_LIMITS = "within_limits"
REASON_INITIAL = "initial_deployment"
REASON_PLACE_IDLE = "placing_idle_cash"
#: Обязательный кэш-буфер политики (RiskPolicy v1.0, инв. #1). Здесь он
#: нужен как ГРАНИЦА размещения: свободно только то, что выше буфера.
_MIN_CASH_PCT = 0.05
REASON_UNMEASURABLE = "unmeasurable_allowed"
#: Причины задержки
REASON_MIN_HOLD = "min_hold"
REASON_WEEK_BUDGET = "weekly_turnover_budget"


@dataclass
class ChurnVerdict:
    decision: str
    reason: str
    detail: str = ""
    hours_since_last: Optional[float] = None
    min_hold_hours: Optional[float] = None
    week_turnover_usd: float = 0.0
    move_turnover_usd: float = 0.0
    week_budget_usd: Optional[float] = None
    is_pure_reduction: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW

    def to_dict(self) -> dict:
        return asdict(self)


def _num(v: object) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0.0
    f = float(v)
    return f if f == f and abs(f) != float("inf") else 0.0


def is_pure_reduction(current: dict, target: dict) -> bool:
    """Ход только сокращает: ни одна позиция не растёт и новых не появляется.

    Такой ход — де-риск, и он не задерживается никогда.
    """
    for proto in set(current or {}) | set(target or {}):
        if _num((target or {}).get(proto)) > _num((current or {}).get(proto)) + 1e-9:
            return False
    return True


def is_pure_addition(current: dict, target: dict) -> bool:
    """Ход только ДОБАВЛЯЕТ: ни одна позиция не сокращается.

    Зеркало `is_pure_reduction`. Такой ход не перетасовывает книгу — он переводит
    простаивающий кэш в работу, и продавать при этом нечего.
    """
    for proto in set(current or {}) | set(target or {}):
        if _num((target or {}).get(proto)) < _num((current or {}).get(proto)) - 1e-9:
            return False
    return True


def one_sided_turnover(current: dict, target: dict) -> float:
    """Односторонний оборот хода — max(куплено, продано), как в ADR-060.

    Не брутто/2: развёртывание простаивающего кэша не имеет продающей ноги,
    и брутто/2 занизило бы его вдвое.
    """
    up = down = 0.0
    for proto in set(current or {}) | set(target or {}):
        delta = _num((target or {}).get(proto)) - _num((current or {}).get(proto))
        if delta > 0:
            up += delta
        else:
            down += -delta
    return max(up, down)


def _parse(ts: object) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _recent(trades: list, now: datetime) -> tuple:
    """(часов с последней перекладки, оборот за 7 дней) из журнала сделок."""
    week_ago = now - timedelta(days=7)
    last: Optional[datetime] = None
    turnover = 0.0
    for t in trades or []:
        if not isinstance(t, dict):
            continue
        # Ключ отметки в журнале — `ts`. Замер 29.08: поиск по `timestamp`
        # дал «ноль перекладок за неделю» при 22 фактических.
        dt = _parse(t.get("ts") or t.get("timestamp"))
        if dt is None:
            continue
        if last is None or dt > last:
            last = dt
        if dt >= week_ago:
            turnover += _num(t.get("delta_abs"))
    hours = (now - last).total_seconds() / 3600.0 if last else None
    return hours, turnover


def _book_value(positions: dict) -> float:
    """Сколько денег СЕЙЧАС в книге. Пустая книга — нечего перекладывать."""
    if not isinstance(positions, dict):
        return 0.0
    return sum(_num(x) for x in positions.values())


def decide(
    current_positions: dict,
    target_usd: dict,
    trades: list,
    capital_usd: float,
    now: Optional[datetime] = None,
    params=None,
) -> ChurnVerdict:
    """Пропустить перекладку или задержать до следующего цикла."""
    now = now or datetime.now(timezone.utc)
    try:
        if params is None:
            from spa_core.allocator.rebalance_economics import TriggerParams
            params = TriggerParams.for_mode()
        min_hold_h = float(params.min_hold_days) * 24.0
        budget = float(params.max_turnover_per_week) * float(capital_usd)

        move = one_sided_turnover(current_positions, target_usd)
        pure_cut = is_pure_reduction(current_positions, target_usd)
        hours, week_turnover = _recent(trades, now)

        v = ChurnVerdict(
            decision=ALLOW, reason=REASON_WITHIN_LIMITS,
            hours_since_last=hours, min_hold_hours=min_hold_h,
            week_turnover_usd=round(week_turnover, 2),
            move_turnover_usd=round(move, 2),
            week_budget_usd=round(budget, 2),
            is_pure_reduction=pure_cut,
        )

        if pure_cut:
            v.reason = REASON_DERISK
            v.detail = ("ход только сокращает позиции — де-риск не задерживается "
                        "никогда (ADR-168)")
            return v

        if _book_value(current_positions) <= 0.0 and week_turnover <= 0.0:
            # Первичное размещение: книга пуста И за окно не было ни одного хода.
            # Перекладывать здесь нечего — деньги идут из простоя в работу, а
            # простаивающий капитал ADR-055 прямо запрещает считать нормой.
            # Дырку для «продал вчера — откупил сегодня» это НЕ открывает: та
            # продажа записана в журнал, `week_turnover` > 0, и обратный ход
            # приходит под общий бюджет.
            v.reason = REASON_INITIAL
            v.detail = (f"книга пуста, оборота за окно нет — первичное размещение "
                        f"${move:,.0f} не является перекладкой")
            return v

        # РАЗМЕЩЕНИЕ ПРОСТАИВАЮЩЕГО КЭША — не перекладка (решение владельца 30.08).
        #
        # Демпфер вводился против ПЕРЕТАСОВКИ: 22 перекладки за неделю и оборот в 5.3
        # капитала. Но 29–30.08 он задержал ход, который ничего не продавал, а только
        # ставил в работу простаивающие деньги: треть капитала стояла трое суток,
        # доходность дня 4.21 % → 2.86 %, перераздача выросла до $46.6 тыс. и ждала.
        # То есть правило наказывало ровно за то, ради чего вводилось.
        #
        # Условие узкое и проверяемое: ход НИЧЕГО не сокращает (`is_pure_addition`) И
        # кэша больше обязательного буфера. Тогда это размещение, а не перекладка.
        # Недельный бюджет оборота при этом ОСТАЁТСЯ — он и есть защита от «добавляем
        # понемногу каждый цикл»; снимается только выдержка между перекладками.
        # Ограничение размещения — САМ КЭШ, и это проверяется, а не утверждается.
        # Свободных денег ровно `капитал − книга − обязательный буфер`; больше этого
        # добавить нечего. Поэтому чистое добавление НЕ МОЖЕТ повторяться цикл за
        # циклом: чтобы появился новый кэш, надо сначала продать, а продажа попадает
        # в журнал и считается оборотом на общих основаниях. Перетасовка так себя не
        # ограничивает — её и держат оба предела.
        idle_above_buffer = (float(capital_usd) - _book_value(current_positions)
                             - _MIN_CASH_PCT * float(capital_usd))
        # КНИГА НЕ ПУСТА — обязательное условие, и его подсказал существующий тест
        # `test_the_exemption_does_not_reopen_the_flip_flop`, покрасневший на первой
        # редакции этой правки. Пустая книга означает ПОЛНЫЙ ВЫХОД; возврат в риск на
        # следующий день — вторая нога маятника, а не размещение, и держать её надо.
        # Наш случай другой: книга непуста, сокращения УЖЕ исполнены, а покупки отклонил
        # гейт — то есть ход недоделан наполовину, и книга застряла между двумя
        # состояниями. Доведение такого хода не создаёт нового оборота: продажи за него
        # уже заплачены.
        if (_book_value(current_positions) > 0.0
                and is_pure_addition(current_positions, target_usd) and move > 0
                and move <= idle_above_buffer + 1e-6):
            v.reason = REASON_PLACE_IDLE
            v.detail = (f"ход только добавляет ${move:,.0f} при свободных "
                        f"${idle_above_buffer:,.0f} — размещение простаивающего кэша, "
                        f"а не перекладка (решение владельца 30.08)")
            return v

        if hours is not None and hours < min_hold_h:
            v.decision = BLOCK
            v.reason = REASON_MIN_HOLD
            v.detail = (f"последняя перекладка {hours:.1f} ч назад, минимум "
                        f"{min_hold_h:.0f} ч (ADR-060 §3)")
            return v

        if week_turnover + move > budget:
            v.decision = BLOCK
            v.reason = REASON_WEEK_BUDGET
            v.detail = (f"оборот за неделю ${week_turnover:,.0f} + ход ${move:,.0f} "
                        f"превысил бы бюджет ${budget:,.0f}")
            return v

        v.detail = (f"в пределах: {hours if hours is None else round(hours, 1)} ч с "
                    f"последней, оборот ${week_turnover:,.0f} + ${move:,.0f} ≤ ${budget:,.0f}")
        return v

    except Exception as exc:  # noqa: BLE001 — ограничитель не гейт безопасности
        log.warning("churn_damper: решение не вычислено (%s) — ПРОПУСКАЮ ход", exc)
        return ChurnVerdict(decision=ALLOW, reason=REASON_UNMEASURABLE,
                            detail=f"ограничитель не смог решить: {exc}")
