"""Агент цены газа: следит за сетями и говорит, дорого ли сейчас ходить (ADR-183).

# LLM_FORBIDDEN

Решение владельца 30.08 (карточка «где живёт первый пилот», вариант 3):
пилот на реальные деньги ждёт не разового замера, а ПОСТОЯННОГО агента,
который следит за ценой газа и принимает решение; целевая сеть — Base.

Чем это отличается от трёх существующих газ-мониторов (и почему они не
чинились, а строился этот, — ADR-182 §2):

1. **Fallback-констант НЕТ.** `arbitrum/optimism_gas_monitor` при отказе
   источников молча печатали свой `FALLBACK_GWEI`, неотличимый от чтения, —
   ровно класс «константа со штампом наблюдения» (ADR-126). Здесь отказ
   источников даёт третий исход `unchecked`: записывается ФАКТ «не измерено»,
   числа не выдумываются. Закреплено тестом, воспроизводящим аварию 30.08
   (Blocknative — пустое тело, Infura — нужен ключ).
2. **Источники — те, что реально отвечают** (замер 30.08, память
   public-rpc-gas-endpoints-that-answer): `eth_gasPrice` публичных RPC.
   Для Ethereum требуются ≥2 согласных источника (расхождение фидов ⇒
   `unchecked`, а не среднее из спора — инвариант 2).
3. **Решение, а не только число.** По истории собственных live-чтений агент
   относит текущую цену к перцентилю и говорит режим: `cheap` (≤p25) /
   `normal` / `expensive` (≥p75) — и переводит в $/ногу. Пока истории мало —
   честный `insufficient_history`, не догадка.

Границы (жёстко): ADVISORY. Никого не гейтит, капитал не двигает, kill-switch
не кормит; де-риска не касается вовсе — тот не задерживается ни при каком
газе (ADR-168). Единственный продукт — файл истории и режимов.

stdlib · детерминирован при инъектированных fetcher/clock · atomic_save.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from spa_core.utils.atomic import atomic_save
from spa_core.utils.data_dir import own_data_dir

log = logging.getLogger("spa.monitoring.gas_price_agent")

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
PRODUCES = ("data/gas_price_history.json",)

OUTPUT_PATH = "data/gas_price_history.json"

#: Источники `eth_gasPrice` по сетям — только проверенно отвечающие без ключа
#: (замер 2026-08-30; Blocknative/Infura, в которые целились старые мониторы,
#: не отвечают). Порядок = порядок опроса; берутся ВСЕ ответившие.
CHAIN_SOURCES: Dict[str, List[str]] = {
    "ethereum": [
        "https://eth.drpc.org",
        "https://1rpc.io/eth",
        "https://rpc.flashbots.net",
        "https://eth-mainnet.public.blastapi.io",
        "https://rpc.mevblocker.io",
    ],
    "base": ["https://base.drpc.org", "https://mainnet.base.org"],
    "arbitrum": ["https://arbitrum.drpc.org", "https://arb1.arbitrum.io/rpc"],
    "optimism": ["https://mainnet.optimism.io", "https://optimism.drpc.org"],
}

#: Сколько согласных источников нужно, чтобы назвать чтение живым.
#: Ethereum — сеть, где газ стоит денег и решает вердикт о пилоте: минимум 2.
MIN_LIVE_SOURCES: Dict[str, int] = {"ethereum": 2}
MIN_LIVE_SOURCES_DEFAULT = 1

#: Согласие источников: max/min ≤ 1 + допуск, иначе расхождение фидов ⇒ unchecked.
SOURCE_AGREEMENT_REL = 0.5

ETH_SPOT_SOURCES = (
    "https://api.coinbase.com/v2/prices/ETH-USD/spot",
    "https://api.kraken.com/0/public/Ticker?pair=ETHUSD",
)
SPOT_AGREEMENT_REL = 0.02

#: Допущение о газ-лимите одной ноги — то же, что в pilot_breakeven (ADR-182).
GAS_LIMIT_PER_LEG = 250_000

HTTP_TIMEOUT_SEC = 8.0
HISTORY_MAX_READINGS = 2200          # ~45 дней при такте 30 мин
MIN_HISTORY_FOR_REGIME = 48          # ~сутки live-чтений, раньше — не судим
CHEAP_PCTL = 25.0
EXPENSIVE_PCTL = 75.0

LIVE = "live"
UNCHECKED = "unchecked"              # третий исход: НЕ ноль и НЕ константа

REGIME_CHEAP = "cheap"
REGIME_NORMAL = "normal"
REGIME_EXPENSIVE = "expensive"
REGIME_NO_HISTORY = "insufficient_history"
REGIME_UNMEASURED = "unmeasured"


# ── измерение ──────────────────────────────────────────────────────────────

def _http_json(url: str, payload: Optional[bytes], timeout: float) -> Optional[dict]:
    """Один запрос; ЛЮБАЯ ошибка — None (агент не падает из-за сети)."""
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json",
                     "User-Agent": "spa-gas-price-agent"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception:  # noqa: BLE001 — отказ источника это данные, не авария
        return None


def fetch_gas_gwei(url: str, timeout: float = HTTP_TIMEOUT_SEC) -> Optional[float]:
    """`eth_gasPrice` одного RPC → Gwei, либо None."""
    payload = json.dumps({"jsonrpc": "2.0", "method": "eth_gasPrice",
                          "params": [], "id": 1}).encode()
    r = _http_json(url, payload, timeout)
    try:
        gwei = int(r["result"], 16) / 1e9  # type: ignore[index]
        return gwei if gwei > 0 else None
    except Exception:  # noqa: BLE001
        return None


def fetch_eth_usd(url: str, timeout: float = HTTP_TIMEOUT_SEC) -> Optional[float]:
    """Спот ETH/USD одного источника → USD, либо None."""
    r = _http_json(url, None, timeout)
    try:
        if "coinbase" in url:
            return float(r["data"]["amount"])  # type: ignore[index]
        pair = next(iter(r["result"].values()))  # type: ignore[union-attr]
        return float(pair["c"][0])
    except Exception:  # noqa: BLE001
        return None


def _median(xs: List[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def measure_chain(chain: str,
                  fetcher: Callable[[str], Optional[float]]) -> dict:
    """Опросить все источники сети. live ⇔ хватает СОГЛАСНЫХ источников.

    Отказ всех источников, недобор или расхождение сверх допуска — `unchecked`
    БЕЗ числа: лучше честное «не измерено», чем константа со штампом чтения.
    """
    urls = CHAIN_SOURCES.get(chain, [])
    got = [(u, fetcher(u)) for u in urls]
    values = [v for _, v in got if v is not None]
    need = MIN_LIVE_SOURCES.get(chain, MIN_LIVE_SOURCES_DEFAULT)
    base = {"chain": chain, "sources_total": len(urls),
            "sources_ok": len(values), "sources_required": need}
    if len(values) < need:
        return {**base, "source": UNCHECKED,
                "note": "источники не ответили или их меньше требуемого"}
    if min(values) > 0 and (max(values) / min(values) - 1.0) > SOURCE_AGREEMENT_REL:
        return {**base, "source": UNCHECKED,
                "note": f"источники расходятся сверх допуска: {sorted(values)}"}
    return {**base, "source": LIVE, "gwei": round(_median(values), 6)}


def measure_eth_usd(fetcher: Callable[[str], Optional[float]]) -> dict:
    values = [v for v in (fetcher(u) for u in ETH_SPOT_SOURCES) if v is not None]
    if not values:
        return {"source": UNCHECKED, "note": "ни один спот-источник не ответил"}
    if min(values) > 0 and (max(values) / min(values) - 1.0) > SPOT_AGREEMENT_REL:
        return {"source": UNCHECKED,
                "note": f"спот-источники расходятся: {sorted(values)}"}
    return {"source": LIVE, "usd": round(_median(values), 2)}


# ── решение ────────────────────────────────────────────────────────────────

def _percentile_rank(history_gwei: List[float], value: float) -> float:
    """Midrank-перцентиль: равные текущему считаются половиной.

    С `<=` плоская история (все чтения одинаковы) относила бы текущее к p100
    и звала «дорого» цену, которая не менялась ни разу, — поймано тестом.
    """
    below = sum(1 for x in history_gwei if x < value)
    equal = sum(1 for x in history_gwei if x == value)
    return 100.0 * (below + 0.5 * equal) / len(history_gwei)


def regime_for(history_gwei: List[float], reading: dict) -> dict:
    """Режим сети по перцентилю текущего live-чтения в СВОЕЙ истории.

    Мало истории или нет чтения — честный отказ судить (refusal-first),
    никакой подстановки «нормально по умолчанию».
    """
    if reading.get("source") != LIVE:
        return {"regime": REGIME_UNMEASURED,
                "note": "текущее чтение не live — режим не судим"}
    if len(history_gwei) < MIN_HISTORY_FOR_REGIME:
        return {"regime": REGIME_NO_HISTORY,
                "history_n": len(history_gwei),
                "history_needed": MIN_HISTORY_FOR_REGIME}
    pctl = _percentile_rank(history_gwei, float(reading["gwei"]))
    if pctl <= CHEAP_PCTL:
        regime = REGIME_CHEAP
    elif pctl >= EXPENSIVE_PCTL:
        regime = REGIME_EXPENSIVE
    else:
        regime = REGIME_NORMAL
    return {"regime": regime, "percentile": round(pctl, 1)}


_ADVICE = {
    REGIME_CHEAP: "дешёвое окно для дискреционных ходов",
    REGIME_NORMAL: "обычная цена — экономика хода решается размером (ADR-182)",
    REGIME_EXPENSIVE: "дороже обычного — дискреционный ход лучше отложить; "
                      "де-риска это НЕ касается (ADR-168)",
    REGIME_NO_HISTORY: "истории мало — режим не судим",
    REGIME_UNMEASURED: "не измерено — режим не судим",
}


def build_snapshot(readings: Dict[str, dict], eth_usd: dict,
                   history: dict, now_iso: str) -> dict:
    """Снимок цикла: чтения + $/ногу + режимы. ADVISORY, никого не гейтит."""
    chains = {}
    for chain, r in readings.items():
        hist = [h["gwei"] for h in history.get(chain, []) if h.get("source") == LIVE]
        entry = dict(r)
        entry.update(regime_for(hist, r))
        entry["advice"] = _ADVICE[entry["regime"]]
        if r.get("source") == LIVE and eth_usd.get("source") == LIVE:
            entry["usd_per_leg"] = round(
                float(r["gwei"]) * 1e-9 * GAS_LIMIT_PER_LEG * float(eth_usd["usd"]), 4)
        chains[chain] = entry
    return {"generated_at": now_iso, "advisory": True,
            "gas_limit_per_leg": GAS_LIMIT_PER_LEG,
            "eth_usd": eth_usd, "chains": chains}


def run(base_dir: Optional[str] = None,
        gas_fetcher: Callable[[str], Optional[float]] = fetch_gas_gwei,
        spot_fetcher: Callable[[str], Optional[float]] = fetch_eth_usd,
        now: Optional[datetime] = None,
        write: bool = True) -> dict:
    """Один такт агента: измерить → рассудить → дописать историю (атомарно).

    ``base_dir=None`` (боевой путь) уважает ``SPA_DATA_DIR``: песочный прогон
    пред-деплойного гейта и герметичные тесты НЕ пишут в живой ``data/``
    (класс «тест судит хост через живой data/»). Явный ``base_dir`` (тесты со
    своим каталогом) — сильнее.
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if base_dir is None:
        out = own_data_dir(Path("data")) / Path(OUTPUT_PATH).name
    else:
        out = Path(base_dir) / OUTPUT_PATH

    state: dict = {"history": {}}
    try:
        if out.exists():
            prior = json.loads(out.read_text())
            if isinstance(prior, dict) and isinstance(prior.get("history"), dict):
                state["history"] = prior["history"]
    except Exception:  # noqa: BLE001 — битый файл не роняет агента
        log.warning("gas_price_agent: история нечитаема, начинаю новую")

    readings = {c: measure_chain(c, gas_fetcher) for c in CHAIN_SOURCES}
    eth_usd = measure_eth_usd(spot_fetcher)
    snapshot = build_snapshot(readings, eth_usd, state["history"], now_iso)

    for chain, r in readings.items():
        row = {"ts": now_iso, "source": r["source"], "sources_ok": r["sources_ok"]}
        if r.get("source") == LIVE:
            row["gwei"] = r["gwei"]
        hist = state["history"].setdefault(chain, [])
        hist.append(row)
        del hist[:-HISTORY_MAX_READINGS]

    state.update(snapshot)
    if write:
        atomic_save(state, str(out), indent=1)
    return state


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="SPA gas price agent (ADR-183)")
    ap.add_argument("--run", action="store_true",
                    help="измерить и записать data/gas_price_history.json")
    ap.add_argument("--check", action="store_true",
                    help="измерить и напечатать, без записи (default)")
    args = ap.parse_args(argv)
    state = run(write=bool(args.run))
    for chain, e in state["chains"].items():
        gwei = e.get("gwei", "—")
        leg = e.get("usd_per_leg", "—")
        print(f"[gas_price_agent] {chain:9s} {e['source']:9s} "
              f"gwei={gwei} $/ногу={leg} режим={e['regime']} — {e['advice']}")
    print(f"[gas_price_agent] ETH/USD: {state['eth_usd']}"
          + ("" if args.run else "  (check mode — не записано)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
