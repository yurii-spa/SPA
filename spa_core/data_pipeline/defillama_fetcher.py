"""
DeFiLlama API Fetcher — SPA Data Pipeline
Фаза M4: получение APY, TVL, utilization rate для 15 протоколов whitelist.

Запуск вручную:   python defillama_fetcher.py
Запуск планировщика: python defillama_fetcher.py --daemon
"""

import requests
import sqlite3
import logging
import time
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

# ─── Конфигурация ───────────────────────────────────────────────────────────────

# Whitelist протоколов v2.0.0 (M4 expansion: 7 → 15 протоколов)
# pool_id — верифицированные ID пулов из DeFiLlama /pools (проверено 2026-05-21)
WHITELIST = {
    # ── T1: Blue-chip lending ──────────────────────────────────────────────────
    "aave-v3-usdc-ethereum": {
        "protocol":   "Aave V3",
        "asset":      "USDC",
        "chain":      "Ethereum",
        "tier":       "T1",
        "pool_id":    "aa70268e-4b52-42bf-a116-608b370f9501",  # TVL $138M
    },
    "aave-v3-usdt-ethereum": {
        "protocol":   "Aave V3",
        "asset":      "USDT",
        "chain":      "Ethereum",
        "tier":       "T1",
        "pool_id":    "f981a304-bb6c-45b8-b0c5-fd2f515ad23a",  # TVL $335M
    },
    "aave-v3-usdc-base": {
        "protocol":   "Aave V3",
        "asset":      "USDC",
        "chain":      "Base",
        "tier":       "T1",
        "pool_id":    "7e0661bf-8cf3-45e6-9424-31916d4c7b84",  # TVL $35M
    },
    "aave-v3-usdc-arbitrum": {
        "protocol":   "Aave V3",
        "asset":      "USDC",
        "chain":      "Arbitrum",
        "tier":       "T1",
        "pool_id":    "d9fa8e14-0447-4207-9ae8-7810199dfa1f",  # TVL $21M
    },
    "compound-v3-usdc-ethereum": {
        "protocol":   "Compound V3",
        "asset":      "USDC",
        "chain":      "Ethereum",
        "tier":       "T1",
        "pool_id":    "7da72d09-56ca-4ec5-a45f-59114353e487",  # TVL $32M
    },
    "morpho-usdc-ethereum": {
        "protocol":   "Morpho",
        "asset":      "USDC",
        "chain":      "Ethereum",
        "tier":       "T1",
        "pool_id":    "b55f43a8-f444-4cd8-a3a4-0a4e786ba566",  # morpho-blue STEAKUSDC, TVL $114M
    },
    "spark-usdc-ethereum": {
        "protocol":   "Spark",
        "asset":      "USDC",
        "chain":      "Ethereum",
        "tier":       "T1",
        "pool_id":    "c5c74dd1-995c-4445-9d84-3e710bad7d52",  # spark-savings USDC, TVL $404M
    },
    "spark-usdt-ethereum": {
        "protocol":   "Spark",
        "asset":      "USDT",
        "chain":      "Ethereum",
        "tier":       "T1",
        "pool_id":    "a5d67f7e-5b51-4a9d-969d-caf051a7f5a4",  # spark-savings USDT, TVL $905M
    },
    "sky-susds-ethereum": {
        "protocol":   "Sky",
        "asset":      "sUSDS",
        "chain":      "Ethereum",
        "tier":       "T1",
        "pool_id":    "d8c4eff5-c8a9-46fc-a888-057c4c668e72",  # sky-lending sUSDS, TVL $5.8B
    },
    # ── T2: Higher yield ───────────────────────────────────────────────────────
    "fluid-usdc-ethereum": {
        "protocol":   "Fluid",
        "asset":      "USDC",
        "chain":      "Ethereum",
        "tier":       "T2",
        "pool_id":    "4438dabc-7f0c-430b-8136-2722711ae663",  # fluid-lending USDC, TVL $200M
    },
    "fluid-usdt-ethereum": {
        "protocol":   "Fluid",
        "asset":      "USDT",
        "chain":      "Ethereum",
        "tier":       "T2",
        "pool_id":    "4e8cc592-c8d5-4824-8155-128ba521e903",  # fluid-lending USDT, TVL $131M
    },
    "ethena-susde-ethereum": {
        "protocol":   "Ethena",
        "asset":      "sUSDe",
        "chain":      "Ethereum",
        "tier":       "T2",
        "pool_id":    "66985a81-9c51-46ca-9977-42b4fe7bc6df",  # ethena-usde sUSDe, TVL $1.8B
    },
    "yearn-v3-usdc-ethereum": {
        "protocol":   "Yearn V3",
        "asset":      "USDC",
        "chain":      "Ethereum",
        "tier":       "T2",
        "pool_id":    "7d89af7a-24c9-4292-aa38-7c71b05fbd6d",  # TVL $28M
    },
    "maple-usdc-ethereum": {
        "protocol":   "Maple",
        "asset":      "USDC",
        "chain":      "Ethereum",
        "tier":       "T2",
        "pool_id":    "43641cf5-a92e-416b-bce9-27113d3c0db6",  # TVL $3.3B
    },
    "euler-v2-usdc-ethereum": {
        "protocol":   "Euler V2",
        "asset":      "USDC",
        "chain":      "Ethereum",
        "tier":       "T2",
        "pool_id":    "31a0cd94-b781-4e0d-a9f1-1702bc2c238f",  # TVL $30M
    },
}

DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"
DEFILLAMA_CHART_URL = "https://yields.llama.fi/chart/{pool_id}"
COLLECTION_INTERVAL_HOURS = 4
DB_PATH = Path(__file__).parent.parent / "database" / "spa.db"

# Пороги валидации
MAX_APY = 50.0       # % — выше считается аномалией
MIN_TVL_USD = 1_000_000  # $1M — ниже считается подозрительным
STALE_HOURS = 48     # часов без обновления — данные устарели

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("defillama_fetcher")


# ─── Получение данных ────────────────────────────────────────────────────────────

def fetch_all_pools() -> list[dict]:
    """Получить все пулы с DeFiLlama /pools."""
    log.info("Fetching all pools from DeFiLlama...")
    resp = requests.get(DEFILLAMA_POOLS_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    pools = data.get("data", [])
    log.info(f"Total pools from DeFiLlama: {len(pools)}")
    return pools


def find_pool_by_id(pools: list[dict], pool_id: str) -> dict | None:
    """Найти пул по pool_id."""
    for p in pools:
        if p.get("pool") == pool_id:
            return p
    return None


def match_whitelist_pools(all_pools: list[dict]) -> dict:
    """
    Найти пулы whitelist в данных DeFiLlama.
    Возвращает dict: whitelist_key -> pool_data
    """
    results = {}

    for key, config in WHITELIST.items():
        pool_id = config.get("pool_id")

        if pool_id:
            # Прямой поиск по pool_id
            pool = find_pool_by_id(all_pools, pool_id)
            if pool:
                results[key] = pool
            else:
                log.warning(f"Pool not found by ID: {key} (pool_id={pool_id})")
        else:
            # Fuzzy search по протоколу, символу и цепи
            protocol_name = config["protocol"].lower().replace(" ", "-")
            asset = config["asset"].upper()
            chain = config["chain"].lower()

            candidates = []
            for p in all_pools:
                p_project = (p.get("project") or "").lower()
                p_symbol = (p.get("symbol") or "").upper()
                p_chain = (p.get("chain") or "").lower()

                if (protocol_name in p_project and
                    asset in p_symbol and
                    chain in p_chain):
                    candidates.append(p)

            if candidates:
                # Выбрать пул с наибольшим TVL
                best = max(candidates, key=lambda x: x.get("tvlUsd", 0))
                results[key] = best
                log.info(f"Matched {key} via fuzzy search: {best.get('pool')} TVL=${best.get('tvlUsd', 0):,.0f}")
            else:
                log.warning(f"No pool found for: {key}")

    return results


def extract_snapshot(key: str, config: dict, pool_data: dict) -> dict:
    """Извлечь данные снимка из raw pool_data."""
    now_utc = datetime.now(timezone.utc)

    apy = pool_data.get("apy") or 0.0
    apy_base = pool_data.get("apyBase") or 0.0
    apy_reward = pool_data.get("apyReward") or 0.0
    tvl_usd = pool_data.get("tvlUsd") or 0.0
    utilization = pool_data.get("utilizationRate")  # может быть None

    return {
        "timestamp":        now_utc.isoformat(),
        "protocol_key":     key,
        "protocol":         config["protocol"],
        "asset":            config["asset"],
        "chain":            config["chain"],
        "tier":             config["tier"],
        "pool_id":          pool_data.get("pool", ""),
        "apy_total":        round(float(apy), 6),
        "apy_base":         round(float(apy_base), 6),
        "apy_reward":       round(float(apy_reward), 6),
        "tvl_usd":          round(float(tvl_usd), 2),
        "utilization_rate": round(float(utilization), 4) if utilization is not None else None,
        "raw_json":         json.dumps(pool_data),
    }


# ─── Валидация ───────────────────────────────────────────────────────────────────

def validate_snapshot(snap: dict) -> tuple[bool, list[str]]:
    """
    Проверить снимок на аномалии.
    Возвращает (is_valid, список предупреждений).
    """
    warnings = []

    if snap["apy_total"] > MAX_APY:
        warnings.append(f"APY аномально высокий: {snap['apy_total']:.2f}% > {MAX_APY}%")

    if snap["apy_total"] < 0:
        warnings.append(f"APY отрицательный: {snap['apy_total']:.2f}%")

    if snap["tvl_usd"] < MIN_TVL_USD:
        warnings.append(f"TVL слишком низкий: ${snap['tvl_usd']:,.0f} < ${MIN_TVL_USD:,.0f}")

    if snap["tvl_usd"] == 0:
        warnings.append("TVL равен нулю — возможно ошибка данных")

    is_valid = len(warnings) == 0
    return is_valid, warnings


# ─── Хранение ────────────────────────────────────────────────────────────────────

def save_snapshot(conn: sqlite3.Connection, snap: dict, is_valid: bool, warnings: list[str]):
    """Сохранить снимок в базу данных."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO apy_snapshots (
            timestamp, protocol_key, protocol, asset, chain, tier,
            pool_id, apy_total, apy_base, apy_reward, tvl_usd,
            utilization_rate, is_valid, validation_warnings, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        snap["timestamp"],
        snap["protocol_key"],
        snap["protocol"],
        snap["asset"],
        snap["chain"],
        snap["tier"],
        snap["pool_id"],
        snap["apy_total"],
        snap["apy_base"],
        snap["apy_reward"],
        snap["tvl_usd"],
        snap["utilization_rate"],
        1 if is_valid else 0,
        json.dumps(warnings) if warnings else None,
        snap["raw_json"],
    ))
    conn.commit()


def save_risk_event(conn: sqlite3.Connection, event_type: str, severity: str,
                    protocol_key: str, message: str, details: dict = None):
    """Сохранить событие риска."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO risk_events (timestamp, event_type, severity, protocol_key, message, details_json)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        event_type,
        severity,
        protocol_key,
        message,
        json.dumps(details) if details else None,
    ))
    conn.commit()


# ─── Основной цикл ───────────────────────────────────────────────────────────────

def collect_once(conn: sqlite3.Connection):
    """Один цикл сбора данных."""
    log.info("=" * 60)
    log.info("Starting data collection cycle")
    log.info("=" * 60)

    try:
        all_pools = fetch_all_pools()
    except Exception as e:
        log.error(f"Failed to fetch pools: {e}")
        save_risk_event(conn, "data_pipeline_error", "HIGH", "ALL",
                        f"DeFiLlama API error: {e}")
        return

    matched = match_whitelist_pools(all_pools)

    collected = 0
    anomalies = 0

    for key, config in WHITELIST.items():
        pool_data = matched.get(key)

        if not pool_data:
            log.warning(f"SKIP {key}: no data found")
            save_risk_event(conn, "missing_data", "MEDIUM", key,
                            f"No DeFiLlama data found for {key}")
            continue

        snap = extract_snapshot(key, config, pool_data)
        is_valid, warnings = validate_snapshot(snap)

        if warnings:
            anomalies += 1
            for w in warnings:
                log.warning(f"ANOMALY [{key}]: {w}")
                save_risk_event(conn, "data_anomaly", "MEDIUM", key, w,
                                {"apy": snap["apy_total"], "tvl": snap["tvl_usd"]})

        save_snapshot(conn, snap, is_valid, warnings)

        log.info(
            f"{'✓' if is_valid else '⚠'} {key}: "
            f"APY={snap['apy_total']:.2f}% "
            f"TVL=${snap['tvl_usd']/1e6:.1f}M"
        )
        collected += 1

    log.info(f"Collection complete: {collected}/{len(WHITELIST)} protocols, {anomalies} anomalies")


def run_daemon():
    """Запустить планировщик сбора данных (каждые 4 часа)."""
    from database.init_db import get_connection

    log.info(f"Starting DeFiLlama data daemon (interval={COLLECTION_INTERVAL_HOURS}h)")

    with get_connection() as conn:
        while True:
            try:
                collect_once(conn)
            except Exception as e:
                log.error(f"Unexpected error in collection cycle: {e}", exc_info=True)

            next_run = COLLECTION_INTERVAL_HOURS * 3600
            log.info(f"Next collection in {COLLECTION_INTERVAL_HOURS} hours...")
            time.sleep(next_run)


def run_once_cli():
    """Разовый запуск — для ручной проверки и тестов."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from database.init_db import get_connection

    with get_connection() as conn:
        collect_once(conn)

    log.info("Done. Check database/spa.db for results.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SPA DeFiLlama Data Fetcher")
    parser.add_argument("--daemon", action="store_true",
                        help="Run as daemon (collect every 4 hours)")
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        run_once_cli()


# ─── Class-based wrapper (для import из export_data.py) ──────────────────────

class DeFiLlamaFetcher:
    """
    Class-based обёртка над модульными функциями.
    Используется в export_data.py:
        fetcher = DeFiLlamaFetcher(db_path=db_path)
        result  = fetcher.fetch_all()
    """

    def __init__(self, db_path: Path = None):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        self.db_path = db_path or DB_PATH

    def fetch_all(self) -> dict:
        """
        Один полный цикл сбора данных DeFiLlama → SQLite.
        Возвращает {'fetched': N, 'errors': N}.
        """
        from database.init_db import get_connection

        fetched = 0
        errors = 0
        try:
            with get_connection(self.db_path) as conn:
                collect_once(conn)
                fetched = len(WHITELIST)
        except Exception as exc:
            log.error(f"DeFiLlamaFetcher.fetch_all failed: {exc}", exc_info=True)
            errors = 1

        return {"fetched": fetched, "errors": errors}
