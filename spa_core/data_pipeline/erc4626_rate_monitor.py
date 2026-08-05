"""Наблюдаемая ставка ERC-4626 хранилищ — измеряем сами, не спрашиваем вендора.

Зачем это существует. `stusd` (Angle) и `wusdm` (Mountain) не индексируются
DeFiLlama вовсе: широкий скан 15 639 пулов 2026-08-05 дал по ним НОЛЬ совпадений.
Пока протокол не наблюдается, капитал в него разместить нельзя — это не
«недооптимизированный вес», а закрытая дверь.

Почему не исторические вызовы. Классический способ снять ставку с ERC-4626 —
сравнить `convertToAssets` на двух блоках. Замер показал, что архивные вызовы
анонимно отдаёт ровно ОДИН публичный эндпоинт из трёх (остальные 403 и 429).
Один эндпоинт — единственная точка доверия для числа, которое пускает капитал;
кворум на нём недостижим. Поэтому исторический путь отвергнут.

Что вместо. Цену доли на `latest` умеют все эндпоинты, значит по ней достижим
кворум. Модуль читает её каждый прогон, КОПИТ СВОЙ РЯД и выводит ставку из двух
собственных наблюдений. Это сильнее вендорского API: измерение наше,
воспроизводимое (любой может повторить `convertToAssets` на том же контракте) и
не зависит ни от чьей доступности.

Цена честности: в первый прогон ставки НЕТ — есть только одна точка. Это
правильный ответ, а не недостаток: выводить доходность из одного замера нельзя.

Правила: только stdlib, атомарная запись, fail-CLOSED (нет кворума ⇒ наблюдение
не записывается, старое протухает само).
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.erc4626_rate")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPO_ROOT / "data"
STATUS_FILENAME = "erc4626_rates.json"

# Эндпоинты для чтения на `latest`. Историю не запрашиваем — см. докстринг.
_RPC_ENDPOINTS = [
    "https://ethereum-rpc.publicnode.com",
    "https://eth.drpc.org",
    "https://1rpc.io/eth",
]

# Сколько независимых эндпоинтов должны дать ОДНО И ТО ЖЕ значение.
_QUORUM = 2

# selector'ы стандартного ERC-4626 / ERC-20
_SEL_SYMBOL = "0x95d89b41"           # symbol()
_SEL_CONVERT_TO_ASSETS = "0x07a2d13a"  # convertToAssets(uint256)

_ONE = 10 ** 18

# Хранилища, за которыми следим. ``symbol`` — не украшение, а ПРОВЕРКА личности:
# контракт обязан назвать себя ожидаемым именем, иначе адрес не принимается.
# Адрес, который «вроде тот», отвергается — это единственное, что отличает
# наблюдение от догадки.
VAULTS: dict[str, dict] = {
    "stusd": {"address": "0x0022228a2cc5E7eF0274A7Baa600d44da5aB5776", "symbol": "stUSD"},
    "wusdm": {"address": "0x57F5E098CaD7A3D1Eed53991D4d66C45C9AF7812", "symbol": "wUSDM"},
}

# Сколько наблюдений храним. Ставку считаем по краям окна, поэтому длинный ряд
# сглаживает суточный шум и переживает пропущенный прогон.
_MAX_HISTORY = 30

# Минимальный интервал между точками, по которым считается ставка. Слишком
# близкие замеры дают дикую годовую цифру из шума округления.
_MIN_HOURS_BETWEEN = 12.0

# Диапазон вменяемости для стейблкоин-хранилища. Выход за него — это не «высокая
# доходность», а признак, что мы посчитали не то (сплит, миграция, ошибка знака).
_MIN_APY_PCT = -5.0
_MAX_APY_PCT = 60.0


def _eth_call(rpc: str, to: str, data: str, timeout: int = 8) -> Optional[str]:
    """Один read-only вызов. Никогда не бросает; ``None`` при любой неудаче."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                          "params": [{"to": to, "data": data}, "latest"]}).encode()
    req = urllib.request.Request(
        rpc, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 # Без User-Agent часть публичных RPC отвечает 403, и отказ
                 # выглядит как «эндпоинт недоступен» (урок sky_monitor).
                 "User-Agent": "SPA-Monitor/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        result = body.get("result")
        if isinstance(result, str) and result.startswith("0x") and len(result) > 2:
            return result
    except Exception as exc:  # noqa: BLE001 — сеть не должна ронять цикл
        log.debug("eth_call %s failed: %s", rpc, exc)
    return None


def _decode_string(hex_value: Optional[str]) -> Optional[str]:
    """ABI-строка → str. ``None``, если не разбирается."""
    if not hex_value or hex_value == "0x":
        return None
    try:
        raw = bytes.fromhex(hex_value[2:])
        offset = int.from_bytes(raw[:32], "big")
        length = int.from_bytes(raw[offset:offset + 32], "big")
        return raw[offset + 32:offset + 32 + length].decode("utf-8", "ignore") or None
    except Exception:  # noqa: BLE001
        return None


def read_share_price(
    address: str,
    expect_symbol: str,
    endpoints: Optional[list] = None,
    quorum: int = _QUORUM,
) -> tuple[Optional[float], list]:
    """Цена доли хранилища с кворумом. Возвращает ``(цена, свидетели)``.

    Личность проверяется на КАЖДОМ эндпоинте: контракт обязан вернуть ожидаемый
    ``symbol()``. Иначе адрес не тот (или подменён на форке ответа), и число не
    берётся ни при каком кворуме.

    Расхождение цены между эндпоинтами — отказ, а не усреднение: два узла,
    сообщающие разное состояние одного контракта, означают, что кто-то неправ,
    а кто именно — неизвестно (инвариант 2, fail-CLOSED).
    """
    arg = hex(_ONE)[2:].rjust(64, "0")
    seen: dict[float, list] = {}
    for rpc in (endpoints if endpoints is not None else _RPC_ENDPOINTS):
        symbol = _decode_string(_eth_call(rpc, address, _SEL_SYMBOL))
        if symbol != expect_symbol:
            if symbol is not None:
                log.warning("%s: %s назвался %r вместо %r — адрес отвергнут",
                            rpc, address, symbol, expect_symbol)
            continue
        raw = _eth_call(rpc, address, _SEL_CONVERT_TO_ASSETS + arg)
        if not raw:
            continue
        try:
            price = int(raw, 16) / float(_ONE)
        except (ValueError, TypeError):
            continue
        if not (0.5 < price < 100.0):   # доля стейбл-хранилища вне этого — не цена
            continue
        seen.setdefault(price, []).append(rpc)

    if not seen:
        return None, []
    if len(seen) > 1:
        log.error("расхождение цены доли %s между эндпоинтами (%s) — отказ",
                  address, {f"{p:.10f}": len(w) for p, w in seen.items()})
        return None, []
    price, witnesses = next(iter(seen.items()))
    if len(witnesses) < quorum:
        log.warning("%s: ответил %d эндпоинт(ов) при кворуме %d — наблюдение не принято",
                    address, len(witnesses), quorum)
        return None, []
    return price, witnesses


def derive_apy_pct(history: list) -> Optional[float]:
    """Годовая ставка по краям ряда, или ``None``, если её честно не вывести.

    Отказ (а не ноль и не догадка) когда: точек меньше двух; между ними меньше
    ``_MIN_HOURS_BETWEEN``; цена не выросла определённо; результат вне диапазона
    вменяемости. Последнее — защита от «посчитали не то»: 300 % на
    стейблкоин-хранилище это не находка, а сплит или ошибка.
    """
    points = [p for p in (history or [])
              if isinstance(p, dict)
              and isinstance(p.get("share_price"), (int, float))
              and not isinstance(p.get("share_price"), bool)]
    if len(points) < 2:
        return None

    def _ts(point: dict) -> Optional[datetime]:
        try:
            dt = datetime.fromisoformat(str(point.get("observed_at")).replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    first, last = points[0], points[-1]
    t0, t1 = _ts(first), _ts(last)
    if t0 is None or t1 is None:
        return None
    hours = (t1 - t0).total_seconds() / 3600.0
    if hours < _MIN_HOURS_BETWEEN:
        return None
    p0, p1 = float(first["share_price"]), float(last["share_price"])
    if p0 <= 0 or p1 <= 0:
        return None
    growth = p1 / p0
    if growth <= 0:
        return None
    apy = (growth ** (8760.0 / hours) - 1.0) * 100.0
    if not (_MIN_APY_PCT <= apy <= _MAX_APY_PCT):
        log.warning("выведенная ставка %.2f%% вне диапазона вменяемости — отказ", apy)
        return None
    return round(apy, 4)


def observe(data_dir: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    """Снять цену доли по всем хранилищам, дописать в ряд, вывести ставку.

    Существующий ряд НИКОГДА не затирается неудачей: если наблюдение не набрало
    кворум, прошлые точки остаются, а новая просто не добавляется — ряд стареет
    сам, и потребитель увидит это по ``observed_at``.
    """
    ddir = Path(data_dir) if data_dir else _DATA_DIR
    ref = now or datetime.now(timezone.utc)
    path = ddir / STATUS_FILENAME

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            doc = {}
    except Exception:  # noqa: BLE001 — первый запуск / битый файл
        doc = {}
    vaults = doc.get("vaults") if isinstance(doc.get("vaults"), dict) else {}

    for key, meta in VAULTS.items():
        entry = vaults.get(key) if isinstance(vaults.get(key), dict) else {}
        history = entry.get("history") if isinstance(entry.get("history"), list) else []

        price, witnesses = read_share_price(meta["address"], meta["symbol"])
        if price is not None:
            # Одна точка в сутки: чаще — шум округления, реже — потеря разрешения.
            last_ts = None
            if history:
                try:
                    last_ts = datetime.fromisoformat(
                        str(history[-1].get("observed_at")).replace("Z", "+00:00"))
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError, AttributeError):
                    last_ts = None
            if last_ts is None or (ref - last_ts) >= timedelta(hours=_MIN_HOURS_BETWEEN):
                history.append({"share_price": price, "observed_at": ref.isoformat(),
                                "witnesses": len(witnesses)})
                history = history[-_MAX_HISTORY:]

        apy = derive_apy_pct(history)
        vaults[key] = {
            "address": meta["address"],
            "symbol": meta["symbol"],
            "share_price": price if price is not None else entry.get("share_price"),
            "share_price_as_of": ref.isoformat() if price is not None
            else entry.get("share_price_as_of"),
            "witnesses": len(witnesses),
            "apy_pct": apy,
            # Почему ставки может не быть — читателю не нужно гадать.
            "apy_note": (None if apy is not None else
                         ("нужно ≥2 наблюдения с интервалом ≥%.0fч; сейчас %d"
                          % (_MIN_HOURS_BETWEEN, len(history)))),
            "history": history,
        }

    out = {
        "generated_at": ref.isoformat(),
        "source": "erc4626_rate_monitor",
        "quorum": _QUORUM,
        "vaults": vaults,
    }
    atomic_save(out, str(path))
    log.info("erc4626_rate_monitor: %d хранилищ, ставок выведено %d",
             len(vaults), sum(1 for v in vaults.values() if v.get("apy_pct") is not None))
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    doc = observe()
    for key, v in (doc.get("vaults") or {}).items():
        print(f"{key}: цена доли={v.get('share_price')} свидетелей={v.get('witnesses')} "
              f"apy={v.get('apy_pct')} точек={len(v.get('history') or [])}"
              + (f" ({v['apy_note']})" if v.get("apy_note") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
