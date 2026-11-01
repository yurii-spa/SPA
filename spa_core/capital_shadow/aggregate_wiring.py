"""capital_shadow.aggregate_wiring — кандидат подключения совокупного допуска (S3 E6.3) к ``run.run_cycle``.

ВЫКЛЮЧЕН по умолчанию: ``run_cycle(aggregate_mode="off")`` ведёт себя побайтно как раньше. Режим ``"shadow"``
только считает и кладёт вердикты в сводку; ``"enforce"`` не пускает отказанные намерения в симуляцию. Включение
любого режима в расписании — отдельное решение владельца (Proposed ADR, автономный мандат 01.11 §2.2).

**Против какой книги судить — главный вопрос, и ответ не «против текущей».** Намерения shadow строятся из сделок,
которые бумажная книга УЖЕ сделала (``intent._trade_deltas`` последней сделки). Текущая книга эти дельты уже
содержит; допустить их ещё раз поверх неё значило бы посчитать один и тот же капитал дважды — в позиции и в резерве.
Поэтому база — книга ДО ещё не исполненных намерений: текущая книга минус их дельты, а сами они — резервы:

* намерения текущего набора и незавершённые намерения прошлых циклов (на ledger, состояние до
  ``SHADOW_EXECUTED`` и не терминальное, не истёкшие) вычитаются из книги;
* незавершённые прошлые — сразу резервы (их уже допускали), текущие — проходят ``aggregate.admit``;
* кэш книг balanced/aggressive в файле не записан — он ВЫВЕДЕН как ``equity − Σ notional`` и так помечен.

Неизвестное — отказ, не ноль: нет файла книги, нет поля, тир протокола не известен реестру.
Ничего не пишет; LLM запрещён.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.capital_shadow import aggregate as ag
from spa_core.capital_shadow import contract, intent as intent_mod, ledger, machine
from spa_core.risk.policy import tier_from_registry

MODES = ("off", "shadow", "enforce")
#: состояния, в которых дельта намерения уже есть в бумажной книге, но в shadow ещё НЕ исполнена
_PENDING = (contract.S_DRAFT, contract.S_VALIDATED, contract.S_SIMULATED, contract.S_SHADOW_READY)
_BUYS, _SELLS = ag._BUYS, ag._SELLS


def _read(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def registry_tiers(data_dir: Path) -> Optional[Dict[str, str]]:
    """Тиры протоколов из ``data/adapter_registry.json`` через ЕДИНСТВЕННЫЙ разборщик ``tier_from_registry``.
    Нет файла — ``None`` (ось тиров «не проверена», и допуск это назовёт)."""
    doc = _read(Path(data_dir) / "adapter_registry.json")
    adapters = (doc or {}).get("adapters") if isinstance(doc, dict) else None
    if not isinstance(adapters, dict):
        return None
    out = {}
    for key, entry in adapters.items():
        t = tier_from_registry((entry or {}).get("tier")) if isinstance(entry, dict) else None
        if t is not None:
            out[key] = t
    return out


def _raw_book(data_dir: Path, sleeve_id: str) -> Tuple[Optional[dict], str]:
    """(nav, cash, positions, basis) книги как она записана, либо (None, причина)."""
    data_dir = Path(data_dir)
    if sleeve_id == "defi_conservative":
        doc = _read(data_dir / "current_positions.json")
        if not isinstance(doc, dict):
            return None, "current_positions.json не прочитан"
        nav, cash, pos = _num(doc.get("current_equity_usd")), _num(doc.get("cash_usd")), doc.get("positions")
        if nav is None or cash is None or not isinstance(pos, dict):
            return None, "в current_positions.json нет current_equity_usd / cash_usd / positions"
        parsed = {str(k): _num(v) for k, v in pos.items()}
        if any(v is None for v in parsed.values()):
            return None, "позиция без числа в current_positions.json"
        return {"nav": nav, "cash": cash, "positions": {k: float(v or 0.0) for k, v in parsed.items()},
                "cash_basis": "записан"}, ""
    _, relpath = intent_mod._SLEEVE_SOURCES[sleeve_id]
    doc = _read(data_dir / relpath)
    if not isinstance(doc, dict):
        return None, f"{relpath} не прочитан"
    nav, pos = _num(doc.get("equity")), doc.get("positions")
    if nav is None or not isinstance(pos, list):
        return None, f"в {relpath} нет equity / positions"
    positions: Dict[str, float] = {}
    for p in pos:
        usd = _num((p or {}).get("notional_usd")) if isinstance(p, dict) else None
        proto = p.get("protocol") if isinstance(p, dict) else None
        if usd is None or not proto:
            return None, f"позиция без protocol/notional_usd в {relpath}"
        positions[proto] = positions.get(proto, 0.0) + usd
    return {"nav": nav, "cash": nav - sum(positions.values()), "positions": positions,
            "cash_basis": "выведен: equity − Σ notional_usd (в файле книги не записан)"}, ""


def _signed(an_intent: dict) -> Optional[Tuple[str, float]]:
    at, proto, usd = an_intent.get("action_type"), an_intent.get("network_or_venue"), _num(an_intent.get("notional"))
    if at not in _BUYS + _SELLS or not proto or usd is None or usd <= 0:
        return None
    return str(proto), (usd if at in _BUYS else -usd)


def pending_intents(data_dir: Path, now: datetime) -> List[dict]:
    """Незавершённые намерения прошлых циклов: на ledger, не сценарий, не истекли, состояние до SHADOW_EXECUTED."""
    out = []
    for e in ledger.read_all(data_dir):
        if e.get("kind") != "intent":
            continue
        it = e.get("payload") or {}
        if not it.get("intent_id") or intent_mod.is_test_scenario(it.get("scenario")):
            continue
        try:
            if machine.is_expired(it, now):
                continue
        except (KeyError, ValueError):
            continue
        if machine.current_state(data_dir, it["intent_id"]) in _PENDING:
            out.append(it)
    return out


def book_before(data_dir: Path, sleeve_id: str, unexecuted: List[dict], *,
                tiers: Optional[Dict[str, str]]) -> Tuple[Optional[ag.Book], dict]:
    """Книга ДО неисполненных намерений (см. докстринг модуля). Возвращает (Book | None, описание базы)."""
    raw, why = _raw_book(data_dir, sleeve_id)
    _, relpath = intent_mod._SLEEVE_SOURCES[sleeve_id]
    digest, as_of, _ = intent_mod.book_digest_and_asof(Path(data_dir), relpath)
    if raw is None:
        return None, {"state": "UNKNOWN", "why": why}
    positions, cash = dict(raw["positions"]), raw["cash"]
    for it in unexecuted:
        s = _signed(it)
        if s is None:
            continue
        proto, delta = s
        positions[proto] = positions.get(proto, 0.0) - delta
        cash += delta
    if any(v < -1e-6 for v in positions.values()):
        return None, {"state": "UNKNOWN", "why": "вычитание неисполненных дельт дало отрицательную позицию — "
                                                  "намерения не согласуются с книгой"}
    book = ag.Book(nav_usd=raw["nav"], cash_usd=cash, positions_usd={k: v for k, v in positions.items() if v > 1e-6},
                   policy_version=contract.POLICY_VERSION, book_state_digest=digest, tiers=tiers)
    return book, {"state": "MEASURED", "book_as_of": as_of, "cash_basis": raw["cash_basis"],
                  "basis": "книга до неисполненных намерений (текущая минус их дельты)",
                  "unexecuted": sorted(i["intent_id"] for i in unexecuted if _signed(i))}


def verdicts(data_dir: Path, current: List[dict], now: datetime) -> Dict[str, dict]:
    """Совокупный вердикт по каждой книге. Ничего не пишет и ничего не решает за ``run_cycle``."""
    tiers = registry_tiers(data_dir)
    pending = pending_intents(data_dir, now)
    cur_ids = {i["intent_id"] for i in current}
    out: Dict[str, dict] = {}
    for sleeve_id in intent_mod._SLEEVE_SOURCES:
        cur = [i for i in current if i.get("sleeve_id") == sleeve_id and i.get("action_type") != contract.ACTION_NO_ACTION
               and not intent_mod.is_test_scenario(i.get("scenario"))]
        old = [i for i in pending if i.get("sleeve_id") == sleeve_id and i["intent_id"] not in cur_ids]
        if not cur:
            out[sleeve_id] = {"state": "NOTHING_TO_ADMIT", "pending": [i["intent_id"] for i in old]}
            continue
        book, basis = book_before(data_dir, sleeve_id, cur + old, tiers=tiers)
        if book is None:
            out[sleeve_id] = {**basis, "verdicts": {i["intent_id"]: {"verdict": ag.REFUSE, "why": basis["why"]}
                                                    for i in cur}}
            continue
        for it in old:          # уже допускались раньше — держат свой резерв, а не проходят суд заново
            s = _signed(it)
            if s:
                book.reservations[it["intent_id"]] = {"protocol": s[0], "usd": s[1], "expires_at": it["expires_at"],
                                                      "key": (it.get("sleeve_id"), it.get("strategy_id")),
                                                      "policy_version": it.get("policy_version")}
        out[sleeve_id] = {**basis, "tiers": "реестр адаптеров" if tiers is not None else "НЕ ПРОВЕРЕНЫ: реестра нет",
                          "verdicts": ag.admit(book, cur, now=now)}
    return out


def refused_ids(result: Dict[str, dict]) -> set:
    return {iid for s in result.values() for iid, v in (s.get("verdicts") or {}).items()
            if not iid.startswith("_") and v.get("verdict") == ag.REFUSE}
