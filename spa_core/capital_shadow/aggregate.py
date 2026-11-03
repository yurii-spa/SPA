"""capital_shadow.aggregate — совокупный допуск НАБОРА намерений одной книги (S3 E6.3, TRP-02/03). Shadow-only.

Пробел, который закрывает модуль (замер 01.11): каждое намерение проходит симуляцию ОДНО, профинансированное ровно
своим нотионалом (``run._simulate_and_execute``: ``ASSUMED_FULL_FUNDING``). Две заявки, каждая допустимая
сама по себе, вместе могли выбрать кэш ниже буфера или поднять долю протокола выше потолка — и ни одна проверка
этого не видела.

Здесь — детерминированная книга резервов поверх ДЕЙСТВУЮЩИХ лимитов ``RiskConfig`` v1.0 (``min_cash_pct``,
``max_single_protocol``; новых порогов нет):

* намерения допускаются по порядку ``intent_id``; каждое допущенное РЕЗЕРВИРУЕТ свой нотионал, и следующее
  проверяется уже против кэша и долей ПОСЛЕ всех резервов;
* частичное исполнение переносит исполненное в позицию, а неисполненный остаток ОСТАЁТСЯ в резерве до истечения
  TTL или отмены — он не освобождается молча;
* истёкшее (``expires_at``) или отменённое намерение резерв освобождает; заменённое (та же книга и стратегия,
  другой ``intent_id``) освобождает старый резерв прежде, чем допускается новое;
* смена версии политики или состояния книги (``policy_version``, ``book_state_digest``) делает все резервы,
  построенные на старом, недействительными: допуск отказывает целиком, пока набор не перестроен;
* неизвестное значение (нет NAV, нет кэша, нет позиций, нет протокола) — отказ, а не ноль (инв. #2, #17);
* потолки по тирам — те же поля ``RiskConfig``, что у ``RiskPolicy`` (``max_concentration_t1/_t2`` на протокол,
  ``max_total_t2_allocation``, ``max_total_t3_allocation`` совокупно), если вызывающий передал карту тиров;
  протокол вне карты — отказ. Без карты ось тиров НЕ проверена и это сказано в каждом допуске (``unchecked``),
  а не подразумевается молча.

Ничего не исполняет и ничего не пишет; LLM запрещён.

# LLM_FORBIDDEN
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from spa_core.capital_shadow import contract
from spa_core.risk.policy import KNOWN_TIERS, RiskConfig

ADMIT, REFUSE = "ADMIT", "REFUSE"
_BUYS = (contract.ACTION_SUPPLY, contract.ACTION_DEPOSIT_4626, contract.ACTION_SPOT_ORDER)
_SELLS = (contract.ACTION_WITHDRAW, contract.ACTION_REDEEM_4626)


def _ts(v: str) -> datetime:
    d = datetime.fromisoformat(v[:-1] + "+00:00" if v.endswith("Z") else v)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _digest(intent: dict) -> Optional[str]:
    return ((intent.get("risk_snapshot") or {}).get("book_state_digest") or {}).get("value")


@dataclass
class Book:
    """Состояние ОДНОЙ книги, против которого судится набор. ``None`` — значение не наблюдено."""
    nav_usd: Optional[float]
    cash_usd: Optional[float]
    positions_usd: Dict[str, float]
    policy_version: Optional[str]
    book_state_digest: Optional[str]
    reservations: Dict[str, dict] = field(default_factory=dict)   # intent_id → {protocol, usd, expires_at, key, policy_version}
    #: протокол → "T1"/"T2"/"T3"; ``None`` — тиры не переданы, ось потолков по тирам НЕ проверяется (и это называется)
    tiers: Optional[Dict[str, str]] = None


def _release_dead(book: Book, now: datetime, cancelled: set) -> List[str]:
    gone = [i for i, r in book.reservations.items() if i in cancelled or now >= _ts(r["expires_at"])]
    for i in gone:
        del book.reservations[i]
    return gone


def _tier_breach(book: Book, protocol: str, delta: float, config: RiskConfig) -> Optional[str]:
    """Потолки по тирам после всех резервов — зеркало ``RiskPolicy`` (п. 8/8b), без новых порогов."""
    tier = (book.tiers or {}).get(protocol)
    if tier not in KNOWN_TIERS:
        return f"тир {protocol} не известен ({tier!r}) — отказ, а не потолок по умолчанию"
    nav = book.nav_usd

    def exposure(pred) -> float:
        held = sum(v for p, v in book.positions_usd.items() if pred(p))
        res = sum(r["usd"] for r in book.reservations.values() if r["usd"] > 0 and pred(r["protocol"]))
        return held + res

    one = (exposure(lambda p: p == protocol) + delta) / nav
    cap = config.max_concentration_t1 if tier == "T1" else config.max_concentration_t2
    if one > cap + 1e-12:
        return f"доля {protocol} ({tier}) после всех резервов {one:.2%} > потолка тира {cap:.0%}"
    for t, cap_total in (("T2", config.max_total_t2_allocation), ("T3", config.max_total_t3_allocation)):
        if tier == t:
            total = (exposure(lambda p, t=t: (book.tiers or {}).get(p) == t) + delta) / nav
            if total > cap_total + 1e-12:
                return f"{t} совокупно после всех резервов {total:.2%} > потолка {cap_total:.0%}"
    return None


def _shares_after(book: Book, protocol: str, delta: float) -> tuple:
    assert book.cash_usd is not None and book.nav_usd       # admit() отказывает раньше, если не наблюдены
    reserved_buy = sum(r["usd"] for r in book.reservations.values() if r["usd"] > 0)
    # для ПОТОЛКА — только покупки: незавершённый вывод долю ещё не снизил (его могут отменить)
    reserved_on = sum(r["usd"] for r in book.reservations.values() if r["protocol"] == protocol and r["usd"] > 0)
    cash = book.cash_usd - reserved_buy - max(delta, 0.0)
    held = book.positions_usd.get(protocol, 0.0) + reserved_on + delta
    return cash / book.nav_usd, held / book.nav_usd


def admit(book: Book, intents: List[dict], *, now: datetime, cancelled: tuple = (),
          config: RiskConfig = RiskConfig()) -> Dict[str, dict]:
    """Вердикт по каждому намерению набора; ``book.reservations`` обновляется на месте (книга резервов)."""
    out: Dict[str, dict] = {}
    if None in (book.nav_usd, book.cash_usd) or not book.nav_usd or book.nav_usd <= 0:
        return {i["intent_id"]: {"verdict": REFUSE, "why": "NAV или кэш книги не наблюдены — отказ, не ноль"}
                for i in intents}
    if not isinstance(book.positions_usd, dict):
        return {i["intent_id"]: {"verdict": REFUSE, "why": "позиции книги не наблюдены — отказ, а не «позиций нет»"}
                for i in intents}
    released = _release_dead(book, now, set(cancelled))
    # Резерв, построенный на ДРУГОЙ версии политики, недействителен: он мог быть допущен по иным лимитам. Пока он
    # не отменён и не истёк, весь набор отказывает — молча пересчитывать чужой резерв по новым правилам нельзя.
    foreign = sorted(i for i, r in book.reservations.items() if r.get("policy_version") != book.policy_version)
    if foreign:
        return {i["intent_id"]: {"verdict": REFUSE, "state": contract.S_RISK_BLOCKED,
                                 "why": f"резервы {foreign} построены на другой версии политики — перестроить набор "
                                        f"(отменить или дождаться TTL), затем допускать"} for i in intents}
    keys_in_set: Dict[tuple, str] = {}
    for i in sorted(intents, key=lambda x: x["intent_id"]):
        iid = i["intent_id"]
        if None in (book.policy_version, book.book_state_digest, i.get("policy_version"), _digest(i)):
            out[iid] = {"verdict": REFUSE, "state": contract.S_RISK_BLOCKED,
                        "why": "версия политики или состояние книги не наблюдены — совпадение не доказано"}
            continue
        if i.get("policy_version") != book.policy_version or _digest(i) != book.book_state_digest:
            out[iid] = {"verdict": REFUSE, "state": contract.S_RISK_BLOCKED,
                        "why": "намерение построено на другой версии политики или другом состоянии книги"}
            continue
        if now >= _ts(i["expires_at"]):
            out[iid] = {"verdict": REFUSE, "state": contract.S_EXPIRED, "why": "TTL истёк"}
            continue
        key = (i.get("sleeve_id"), i.get("strategy_id"))
        if key in keys_in_set:          # две версии одного намерения В ОДНОМ наборе — какая действует, не известно
            out[iid] = {"verdict": REFUSE, "state": contract.S_INVALID,
                        "why": f"в наборе уже есть намерение той же книги и стратегии ({keys_in_set[key]})"}
            continue
        keys_in_set[key] = iid
        # замена — только резервов, оставшихся от ПРЕЖНИХ вызовов
        for old in [o for o, r in book.reservations.items() if r["key"] == key and o != iid]:
            del book.reservations[old]
            released.append(old)
        if iid in book.reservations:
            out[iid] = {"verdict": ADMIT, "why": "резерв уже держится (повтор идемпотентен)"}
            continue
        at, proto, usd = i.get("action_type"), i.get("network_or_venue"), i.get("notional")
        if at not in _BUYS + _SELLS:
            out[iid] = {"verdict": ADMIT, "why": "действие не двигает кэш и позицию"}
            continue
        if not proto or not isinstance(usd, (int, float)) or isinstance(usd, bool) or usd <= 0:
            out[iid] = {"verdict": REFUSE, "state": contract.S_INVALID, "why": "протокол или нотионал не названы"}
            continue
        delta = usd if at in _BUYS else -usd
        # вывод — только из ИСПОЛНЕННОЙ позиции за вычетом уже зарезервированных выводов (покупка ещё не исполнена)
        if delta < 0 and book.positions_usd.get(proto, 0.0) + sum(
                r["usd"] for r in book.reservations.values() if r["protocol"] == proto and r["usd"] < 0) + delta < -1e-9:
            out[iid] = {"verdict": REFUSE, "state": contract.S_RISK_BLOCKED,
                        "why": f"вывод {usd} больше позиции {proto} с учётом резервов"}
            continue
        cash_share, proto_share = _shares_after(book, proto, delta)
        if delta > 0 and cash_share < config.min_cash_pct - 1e-12:
            out[iid] = {"verdict": REFUSE, "state": contract.S_RISK_BLOCKED,
                        "why": f"кэш после всех резервов {cash_share:.2%} < буфера {config.min_cash_pct:.0%}"}
            continue
        if delta > 0 and proto_share > config.max_single_protocol + 1e-12:
            out[iid] = {"verdict": REFUSE, "state": contract.S_RISK_BLOCKED,
                        "why": f"доля {proto} после всех резервов {proto_share:.2%} > потолка {config.max_single_protocol:.0%}"}
            continue
        if delta > 0 and book.tiers is not None:
            why = _tier_breach(book, proto, delta, config)
            if why:
                out[iid] = {"verdict": REFUSE, "state": contract.S_RISK_BLOCKED, "why": why}
                continue
        book.reservations[iid] = {"protocol": proto, "usd": delta, "expires_at": i["expires_at"], "key": key,
                                  "policy_version": book.policy_version}
        out[iid] = {"verdict": ADMIT, "cash_share_after": cash_share, "protocol_share_after": proto_share,
                    "unchecked": [] if (book.tiers is not None or delta < 0) else ["tier_caps"]}
    if released:
        out["_released"] = {"verdict": "INFO", "ids": sorted(set(released))}
    return out


def apply_fill(book: Book, intent_id: str, filled_usd: float) -> dict:
    """Частичное или полное исполнение: исполненное — в позицию и из кэша; остаток остаётся в резерве."""
    r = book.reservations.get(intent_id)
    if r is None:
        raise KeyError(f"резерва {intent_id} нет — исполнение без допуска")
    if not filled_usd > 0:
        raise ValueError("исполненный объём — положительная величина (знак задаёт резерв)")
    if filled_usd > abs(r["usd"]) + 1e-9:
        raise ValueError("исполнено больше, чем зарезервировано")
    if book.cash_usd is None:
        raise ValueError("кэш книги не наблюдён — исполнение не учитывается вслепую")
    signed = filled_usd if r["usd"] > 0 else -filled_usd
    book.positions_usd[r["protocol"]] = book.positions_usd.get(r["protocol"], 0.0) + signed
    book.cash_usd -= signed
    r["usd"] -= signed
    if abs(r["usd"]) <= 1e-9:
        del book.reservations[intent_id]
        return {"remaining_reserved": 0.0}
    return {"remaining_reserved": r["usd"]}
