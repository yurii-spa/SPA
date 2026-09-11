"""Одно имя — один контракт: два ключа одного пула не обходят потолок на протокол.

Карточка `agent-dva-imeni-odin-kontrakt-20-deneg-stoyat` (реклассифицирована агенту
ADR-285), задание дословно: «исполнить объявленный запрет: одно имя — один контракт».

Замер 2026-09-11 — тождество ДОКАЗАНО по идентификатору пула DeFiLlama, а не по
сходству цифр:

- `adapter_status.json` → `fluid_fusdc`: живой 4.33 %, TVL $157 962 829,
  `tvl_pool_id` = ``4438dabc-7f0c-430b-8136-2722711ae663`` (``pool_match: pinned``);
- адаптер оркестратора для ключа `fluid_usdc` (`fluid_usdc_adapter.FluidUSDCAdapter`,
  проект `fluid-lending`, USDC, ethereum) живым запросом отдаёт ТОТ ЖЕ пул
  ``4438dabc…`` (4.3 %, TVL $158 977 686).

Правило «T2 — не больше 20 % на протокол» (RiskPolicy v1.0) считает по ИМЕНИ. Книга
держит $20 000 под `fluid_usdc`, а аллокатор числит `fluid_fusdc` свободным местом
(«+$20 000 @ 4.33 %» в атрибуции кэша). Вложив туда, он положил бы в ОДИН пул $40 000 =
40 % капитала при потолке 20 %, и обе проверки честно ответили бы «нарушения нет».
Со взводом CIO (ADR-324/328) книга начинает двигаться, и дыра становится исполнимой.

Как закрыто — и чем это НЕ является
-----------------------------------
Шаг только УМЕНЬШАЕТ цель (тот же порядок, что у RTMR-позы, `apply_rtmr_posture_gate`):
если сумма группы псевдонимов превышает потолок тира, срезаются члены группы в
объявленном порядке (сначала путь НОВЫХ денег), высвобожденное остаётся в кэше.
Удерживаемая замороженная позиция не продаётся принудительно (ADR-053, cap-at-held).

Это НЕ изменение RiskPolicy v1.0: её пороги и её подсчёт по имени не тронуты. Это
дополнительный, более строгий шаг поверх, способный только снизить экспозицию.

Группы объявляются ПОИМЁННО, с доказательством. Вывести тождество автоматически из
`adapter_status.json` нельзя: у `fluid_usdc` там `pool_id: null` — ключ привязан к
другому классу (исследовательскому, с литералом 5.5 %), и пул виден только адаптеру
оркестратора. Недоказанное тождество признаком нарушения не является, и шаг его не
выдумывает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Dict, List

#: pool_id → группа. ``trim_order`` — кого срезать первым: путь новых денег раньше
#: удерживаемой замороженной позиции (ту нельзя продавать принудительно).
POOL_ALIASES: Dict[str, Dict] = {
    "4438dabc-7f0c-430b-8136-2722711ae663": {
        "protocol": "Fluid Lending USDC (ethereum)",
        "tier": "T2",
        "trim_order": ["fluid_fusdc", "fluid_usdc"],
        "proof": ("11.09: adapter_status.fluid_fusdc.tvl_pool_id и живой запрос "
                  "fluid_usdc_adapter дают один pool_id DeFiLlama"),
    },
    "931ea9be-5f4d-428e-beaf-205fc5b4e2b5": {
        "protocol": "Morpho (одно хранилище под двумя ключами)",
        "tier": "T2",
        # Решение владельца 18.08 по карточке inbox-morpho-blue-i-morpho-steakhouse
        # (вариант B): `morpho_blue` ОСТАВИТЬ и дать ему своё хранилище. Пока своего
        # нет — это один пул, и срезается первым тот, кого владелец не оставлял.
        "trim_order": ["morpho_steakhouse", "morpho_blue"],
        "proof": ("11.09: монитор pool_identity_collision, род declared+observed — "
                  "оба ключа ранжируются на одном pool_id; оба пригодны к финансированию"),
    },
}

#: Пары одного пула в T3 сюда НЕ вносятся намеренно (ethena_susde + susde, 66985a81):
#: у T3 нет потолка на протокол, их вместе держит потолок ТИРА (15 %, ADR-020), который
#: считает оба ключа. Дыры «дважды по потолку» там нет — вносить значило бы выдумать её.
#: Новую пару находит монитор `spa_core/monitoring/pool_identity_collision.py`
#: (CRITICAL, если книга уже в пуле); этот файл — исполнение, тот — обнаружение.


def _tier_cap(tier: str) -> float:
    """Потолок на протокол из RiskConfig — не литерал рядом с правилом."""
    from spa_core.risk.policy import RiskConfig
    cfg = RiskConfig()
    return float(cfg.max_concentration_t1 if tier == "T1" else cfg.max_concentration_t2)


def apply_pool_alias_gate(target_usd: Dict[str, float], *, capital_usd: float,
                          notes: List[str]) -> Dict[str, float]:
    """Срезать группы псевдонимов одного пула до потолка тира. Только уменьшает."""
    out = dict(target_usd or {})
    if capital_usd <= 0:
        return out
    for pool_id, g in POOL_ALIASES.items():
        members = [m for m in g["trim_order"] if m in out]
        total = sum(max(0.0, float(out.get(m) or 0.0)) for m in members)
        cap_usd = _tier_cap(g["tier"]) * float(capital_usd)
        excess = total - cap_usd
        if excess <= 0.01:
            continue
        trimmed = []
        for m in members:
            if excess <= 0.01:
                break
            have = max(0.0, float(out.get(m) or 0.0))
            cut = min(have, excess)
            if cut <= 0:
                continue
            out[m] = round(have - cut, 2)
            excess -= cut
            trimmed.append(f"{m} −${cut:,.2f}")
        notes.append(
            f"pool_alias_gate: {g['protocol']} — ключи {members} это ОДИН пул {pool_id[:8]}…, "
            f"сумма ${total:,.2f} > потолок {g['tier']} ${cap_usd:,.2f}; срезано: "
            f"{', '.join(trimmed)} (одно имя — один контракт)")
    return out


# ──────────────────────────────────────────────────────────────────────────
# Книгу — к одному ключу на пул (карточка: «книгу привести в соответствие»)
# ──────────────────────────────────────────────────────────────────────────
#: Второе имя пула → каноническое. Вносится ТОЛЬКО там, где второе имя — не отдельный
#: предмет, а артефакт: здесь `fluid_usdc` в реестре привязан к исследовательскому
#: классу с литералом 5.5 % и без пина, а сам пул (4438dabc) наблюдается живым ТОЛЬКО
#: под `fluid_fusdc` (пин `adapter_status_generator._POOL_ID_LOOKUP`). Сторож
#: `test_no_two_keys_share_a_pool` запрещает прибить к пулу второй ключ — и прав: пин
#: есть тождество. Значит второй ключ надо не узаконивать пином, а убрать из книги.
#:
#: Morpho сюда НЕ вносится: у пары `morpho_blue` / `morpho_steakhouse` владелец 18.08
#: решил иначе (вариант B — `morpho_blue` оставить отдельным предметом и дать ему своё
#: хранилище). Слияние там отменило бы его решение.
CANONICAL_KEYS: Dict[str, str] = {
    "fluid_usdc": "fluid_fusdc",
}


def canonicalize_positions(positions: Dict[str, float],
                           notes: List[str]) -> Dict[str, float]:
    """Позиции второго имени пула — под каноническим ключом. Сумма не меняется.

    Делается при ЧТЕНИИ книги, до любого сравнения с целью: иначе цикл увидел бы
    фантомный ход «продал `fluid_usdc`, купил `fluid_fusdc`» и списал бы за него
    издержки, хотя деньги не двигались — они и так лежат в этом пуле.
    """
    out: Dict[str, float] = {}
    moved = []
    for key, amount in (positions or {}).items():
        canon = CANONICAL_KEYS.get(key, key)
        out[canon] = round(out.get(canon, 0.0) + float(amount or 0.0), 2)
        if canon != key and float(amount or 0.0) > 0:
            moved.append(f"{key} ${float(amount):,.2f} → {canon}")
    if moved:
        notes.append("pool_canonical_key: " + "; ".join(moved) +
                     " — тот же пул, второе имя убрано из книги (ADR-335)")
    return out
