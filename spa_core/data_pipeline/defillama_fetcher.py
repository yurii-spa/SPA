"""
DeFiLlama API Fetcher — SPA Data Pipeline
Фаза M4: получение APY, TVL, utilization rate для 15 протоколов whitelist.

Запуск вручную:   python defillama_fetcher.py
Запуск планировщика: python defillama_fetcher.py --daemon
"""

import sqlite3
import logging
import time
import json
import argparse
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# ─── Конфигурация ───────────────────────────────────────────────────────────────

DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"
DEFILLAMA_CHART_URL = "https://yields.llama.fi/chart/{pool_id}"
DEFILLAMA_CHARTDATA_URL = "https://yields.llama.fi/chartData/{pool_id}"
COLLECTION_INTERVAL_HOURS = 4
CACHE_TTL_SECONDS = 3600  # 1 hour — skip network on repeated runs (e.g. GHA retry)

# ─── Canonical 12-pool whitelist — SINGLE SOURCE OF TRUTH ───────────────────
# Verified against README.md as of 2026-05-21. Do NOT expand without ADR approval.
# pool_id is intentionally absent — fetcher uses fuzzy protocol/asset/chain matching.
# This is the only whitelist constant; all code in this module references POOL_WHITELIST.
POOL_WHITELIST = {
    # ── Tier 1 — Ethereum Mainnet ─────────────────────────
    "aave-v3-usdc-ethereum":     {"tier": "T1", "chain": "ethereum", "protocol": "Aave V3",      "asset": "USDC"},
    "compound-v3-usdc-ethereum": {"tier": "T1", "chain": "ethereum", "protocol": "Compound V3",  "asset": "USDC"},
    "morpho-usdc-ethereum":      {"tier": "T1", "chain": "ethereum", "protocol": "Morpho",       "asset": "USDC"},
    # ── Tier 1 — L2 (same whitelisted protocols, additional chains) ─
    "aave-v3-usdc-arbitrum":     {"tier": "T1", "chain": "arbitrum", "protocol": "Aave V3",      "asset": "USDC"},
    "aave-v3-usdc-base":         {"tier": "T1", "chain": "base",     "protocol": "Aave V3",      "asset": "USDC"},
    "compound-v3-usdc-arbitrum": {"tier": "T1", "chain": "arbitrum", "protocol": "Compound V3",  "asset": "USDC"},
    "morpho-usdc-base":          {"tier": "T1", "chain": "base",     "protocol": "Morpho",       "asset": "USDC"},
    # ── Tier 2 — Ethereum Mainnet ─────────────────────────
    "yearn-v3-usdc-ethereum":    {"tier": "T2", "chain": "ethereum", "protocol": "Yearn V3",     "asset": "USDC"},
    "maple-usdc-ethereum":       {"tier": "T2", "chain": "ethereum", "protocol": "Maple Finance", "asset": "USDC"},
    "euler-v2-usdc-ethereum":    {"tier": "T2", "chain": "ethereum", "protocol": "Euler V2",     "asset": "USDC"},
    # ── Watch List (0% allocation pending conditions) ─────
    "sky-susds-ethereum":        {"tier": "WL", "chain": "ethereum", "protocol": "Sky/sUSDS",    "asset": "USDS",
                                  "watch_condition": "GSM Pause Delay >= 48h not yet confirmed"},
    # ── Pendle PT (special handling — fixed-rate, maturity-based) ─
    "pendle-pt-usdc-arbitrum":   {"tier": "T2", "chain": "arbitrum", "protocol": "Pendle PT",    "asset": "PT-USDC",
                                  "special": "fixed_rate", "note": "requires maturity-aware logic"},
}

# Chains present in the whitelist
L2_CHAINS = {"arbitrum", "base"}

# The 7 protocols used by the backtesting engine (subset of POOL_WHITELIST)
BACKTEST_POOL_IDS = {
    "aave-v3-usdc-ethereum":    "aa70268e-4b52-42bf-a116-608b370f9501",
    "aave-v3-usdt-ethereum":    "f981a304-bb6c-45b8-b0c5-fd2f515ad23a",
    "compound-v3-usdc-ethereum":"7da72d09-56ca-4ec5-a45f-59114353e487",
    "morpho-usdc-ethereum":     "b55f43a8-f444-4cd8-a3a4-0a4e786ba566",
    "yearn-v3-usdc-ethereum":   "7d89af7a-24c9-4292-aa38-7c71b05fbd6d",
    "maple-usdc-ethereum":      "43641cf5-a92e-416b-bce9-27113d3c0db6",
    "euler-v2-usdc-ethereum":   "31a0cd94-b781-4e0d-a9f1-1702bc2c238f",
}
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


# ─── Retry utility ───────────────────────────────────────────────────────────────

def retry_request(url: str, timeout: int = 15, max_attempts: int = 3, backoff: float = 2.0):
    """
    Fetch URL with exponential backoff. Stdlib only (no requests).

    Returns:
        (data_bytes, None)  on success
        (None, error_str)   if all attempts fail
    """
    last_err = None
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read(), None
        except Exception as e:
            last_err = str(e)
            if attempt < max_attempts - 1:
                time.sleep(backoff ** attempt)
    return None, last_err


# ─── Получение данных ────────────────────────────────────────────────────────────

def fetch_all_pools() -> list[dict]:
    """Получить все пулы с DeFiLlama /pools. Uses retry_request with exponential backoff."""
    log.info("Fetching all pools from DeFiLlama...")
    data_bytes, err = retry_request(DEFILLAMA_POOLS_URL, timeout=30, max_attempts=3, backoff=2.0)
    if err is not None:
        log.warning(f"fetch_all_pools: all retries failed — {err}")
        return []
    try:
        data = json.loads(data_bytes)
        pools = data.get("data", [])
        log.info(f"Total pools from DeFiLlama: {len(pools)}")
        return pools
    except Exception as e:
        log.warning(f"fetch_all_pools: JSON parse error — {e}")
        return []


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

    for key, config in POOL_WHITELIST.items():
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

    for key, config in POOL_WHITELIST.items():
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

    log.info(f"Collection complete: {collected}/{len(POOL_WHITELIST)} protocols, {anomalies} anomalies")


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

    # Canonical 12-pool whitelist (module-level alias for easy access)
    POOL_WHITELIST = POOL_WHITELIST

    def __init__(self, db_path: Path = None):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        self.db_path = db_path or DB_PATH

    # ── File-based cache ────────────────────────────────────────────────────────
    _CACHE_DIR = Path(__file__).parent.parent.parent / "data" / ".cache"

    def _cached_fetch(self, url: str, cache_key: str) -> bytes | None:
        """Return cached response bytes if fresh, else None."""
        cache_file = self._CACHE_DIR / f"{cache_key}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < CACHE_TTL_SECONDS:
                return cache_file.read_bytes()
        return None

    def _save_cache(self, cache_key: str, data: bytes) -> None:
        """Persist response bytes to the file cache."""
        cache_file = self._CACHE_DIR / f"{cache_key}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(data)

    # ── Private fetch helpers (called concurrently by fetch_pools_concurrent) ──

    def _fetch_main_pools(self) -> list[dict]:
        """
        Fetch whitelist pools from DeFiLlama with file caching.

        Returns list of normalised pool dicts, each including a "key" field
        matching a POOL_WHITELIST entry.
        """
        cache_key = re.sub(r"[^\w]", "_", DEFILLAMA_POOLS_URL)
        cached = self._cached_fetch(DEFILLAMA_POOLS_URL, cache_key)
        if cached:
            data = json.loads(cached)
        else:
            with urllib.request.urlopen(DEFILLAMA_POOLS_URL, timeout=30) as _r:
                data = json.loads(_r.read().decode("utf-8"))
            self._save_cache(cache_key, json.dumps(data).encode())

        all_pools = data.get("data", [])
        results: list[dict] = []

        for key, cfg in POOL_WHITELIST.items():
            protocol_name = cfg["protocol"].lower().replace(" ", "-")
            asset = cfg["asset"].upper()
            chain_name = cfg["chain"].lower()

            candidates = [
                p for p in all_pools
                if (protocol_name in (p.get("project") or "").lower()
                    and asset in (p.get("symbol") or "").upper()
                    and chain_name in (p.get("chain") or "").lower())
            ]
            if not candidates:
                log.debug(f"_fetch_main_pools: no match for {key}")
                continue

            best = max(candidates, key=lambda x: x.get("tvlUsd") or 0)
            apy = best.get("apy") or best.get("apyBase") or 0.0
            tvl = best.get("tvlUsd") or 0.0
            results.append({
                "key":      key,
                "pool_id":  best.get("pool", ""),
                "chain":    cfg["chain"],
                "tier":     cfg["tier"],
                "protocol": cfg["protocol"],
                "asset":    cfg["asset"],
                "apy":      round(float(apy), 4),
                "tvl_usd":  round(float(tvl), 2),
            })

        log.info(f"_fetch_main_pools: {len(results)}/{len(POOL_WHITELIST)} whitelist pools matched")
        return results

    def _fetch_pendle_pools_raw(self) -> list[dict]:
        """
        Fetch Pendle PT pools from DeFiLlama with caching.

        Reuses the same cached response as _fetch_main_pools when available,
        avoiding a second network round-trip on the same URL.
        Returns PendleFetcher-filtered pool dicts.
        """
        from data_pipeline.pendle_fetcher import PendleFetcher

        cache_key = re.sub(r"[^\w]", "_", DEFILLAMA_POOLS_URL)
        cached = self._cached_fetch(DEFILLAMA_POOLS_URL, cache_key)
        if cached:
            data = json.loads(cached)
        else:
            with urllib.request.urlopen(DEFILLAMA_POOLS_URL, timeout=30) as _r:
                data = json.loads(_r.read().decode("utf-8"))
            self._save_cache(cache_key, json.dumps(data).encode())

        all_pools = data.get("data", [])
        pf = PendleFetcher()
        pendle_pools = pf.filter_pools(all_pools)
        log.info(f"_fetch_pendle_pools_raw: {len(pendle_pools)} Pendle PT pools matched")
        return pendle_pools

    def _apply_filters(self, all_pools: list[dict]) -> list[dict]:
        """
        Deduplicate combined pool list by pool_id.

        Pendle entries are preferred over whitelist entries when pool_ids collide.
        """
        seen: set[str] = set()
        result: list[dict] = []
        for p in all_pools:
            pid = p.get("pool_id")
            if pid:
                if pid in seen:
                    continue
                seen.add(pid)
            result.append(p)
        return result

    def fetch_pools_concurrent(self, max_workers: int = 4) -> list[dict]:
        """
        Fetch whitelist pools and Pendle PT pools concurrently.

        Runs _fetch_main_pools() and _fetch_pendle_pools_raw() in parallel
        via ThreadPoolExecutor, then merges and deduplicates.

        Falls back to the sequential fetch_pools() on any executor error.

        Returns:
            list[dict] — one entry per pool, with "key", "apy", "tvl_usd", etc.
            Pendle pools include "special": "fixed_rate".
        """
        try:
            tasks = {
                "main":   lambda: self._fetch_main_pools(),
                "pendle": lambda: self._fetch_pendle_pools_raw(),
            }
            results: dict[str, list] = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(fn): name for name, fn in tasks.items()}
                for future in as_completed(futures, timeout=30):
                    name = futures[future]
                    try:
                        results[name] = future.result()
                    except Exception as e:
                        print(f"[WARN] concurrent fetch {name} failed: {e}")
                        results[name] = []

            all_pools = results.get("main", []) + results.get("pendle", [])
            return self._apply_filters(all_pools)
        except Exception as e:
            print(f"[WARN] concurrent fetch failed, falling back to sequential: {e}")
            return list(self.fetch_pools().get("pools", {}).values())

    def fetch_pools(self, chains: list[str] | None = None) -> dict:
        """
        Fetch live APY/TVL for all 24 pools in POOL_WHITELIST.

        Args:
            chains: Optional list of chain names to restrict to, e.g. ["ethereum", "base"].
                    Lowercase. Default: all chains.

        Returns:
            {
              "pools":   {pool_key: {apy, tvl_usd, chain, tier, protocol, asset}},
              "skipped": [pool_key, ...],  # pools DeFiLlama couldn't match
            }
        Also writes data/chains_status.json relative to this file's repo root.
        """
        # Determine which keys to fetch
        target_keys = {
            k: v for k, v in POOL_WHITELIST.items()
            if chains is None or v["chain"].lower() in [c.lower() for c in chains]
        }
        if not target_keys:
            return {"pools": {}, "skipped": []}

        try:
            all_pools = fetch_all_pools()
        except Exception as exc:
            log.error(f"fetch_pools: DeFiLlama API error: {exc}")
            return {"pools": {}, "skipped": list(target_keys.keys())}

        results: dict[str, dict] = {}
        skipped: list[str] = []

        for key, cfg in target_keys.items():
            try:
                protocol_name = cfg["protocol"].lower().replace(" ", "-")
                asset = cfg["asset"].upper()
                chain_name = cfg["chain"].lower()

                candidates = []
                for p in all_pools:
                    p_project = (p.get("project") or "").lower()
                    p_symbol  = (p.get("symbol") or "").upper()
                    p_chain   = (p.get("chain") or "").lower()
                    if (protocol_name in p_project and
                        asset in p_symbol and
                        chain_name in p_chain):
                        candidates.append(p)

                if not candidates:
                    log.debug(f"fetch_pools: no DeFiLlama match for {key}, skipping")
                    skipped.append(key)
                    continue

                best = max(candidates, key=lambda x: x.get("tvlUsd") or 0)
                apy  = best.get("apy") or best.get("apyBase") or 0.0
                tvl  = best.get("tvlUsd") or 0.0

                results[key] = {
                    "pool_id":  best.get("pool", ""),
                    "chain":    cfg["chain"],
                    "tier":     cfg["tier"],
                    "protocol": cfg["protocol"],
                    "asset":    cfg["asset"],
                    "apy":      round(float(apy), 4),
                    "tvl_usd":  round(float(tvl), 2),
                }
                log.info(f"fetch_pools: {key} APY={apy:.2f}% TVL=${tvl/1e6:.1f}M")
            except Exception as exc:
                log.warning(f"fetch_pools: error processing {key}: {exc}")
                skipped.append(key)

        # Build and export chains_status.json
        try:
            chain_stats: dict[str, dict] = {}
            for k, v in results.items():
                c = v["chain"]
                if c not in chain_stats:
                    chain_stats[c] = {"chain": c, "pool_count": 0, "best_apy": 0.0,
                                      "avg_apy": 0.0, "pools": [], "_apys": []}
                chain_stats[c]["pool_count"] += 1
                chain_stats[c]["pools"].append(k)
                chain_stats[c]["_apys"].append(v["apy"])
                if v["apy"] > chain_stats[c]["best_apy"]:
                    chain_stats[c]["best_apy"] = v["apy"]

            for c, s in chain_stats.items():
                apys = s.pop("_apys")
                s["avg_apy"] = round(sum(apys) / len(apys), 4) if apys else 0.0
                s["best_apy"] = round(s["best_apy"], 4)

            chains_status = {
                "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "total_pools_fetched": len(results),
                "total_pools_skipped": len(skipped),
                "chains": chain_stats,
            }
            output_dir = Path(__file__).parent.parent.parent / "data"
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "chains_status.json").write_text(
                __import__("json").dumps(chains_status, indent=2), encoding="utf-8"
            )
            log.info(f"fetch_pools: chains_status.json written ({len(chain_stats)} chains)")
        except Exception as exc:
            log.warning(f"fetch_pools: could not write chains_status.json: {exc}")

        return {"pools": results, "skipped": skipped}

    def fetch_historical_apy(self, pool_id: str, days: int = 90) -> list[dict]:
        """
        Fetch historical APY/TVL time-series for a single pool from DeFiLlama.

        Endpoint: GET https://yields.llama.fi/chartData/{pool_id}
        Returns list of {timestamp: str, tvlUsd: float, apy: float} dicts,
        sliced to the last `days` entries (oldest → newest).

        Raises on network/HTTP errors — callers should handle gracefully.
        """
        url = DEFILLAMA_CHARTDATA_URL.format(pool_id=pool_id)
        data_bytes, err = retry_request(url, timeout=15, max_attempts=3, backoff=2.0)
        if err is not None:
            log.warning(f"fetch_historical_apy: all retries failed for {pool_id} — {err}")
            return []
        raw = json.loads(data_bytes)

        # DeFiLlama returns {"status": "ok", "data": [{...}, ...]}
        data = raw.get("data") if isinstance(raw, dict) else raw
        if not isinstance(data, list):
            log.warning(f"Unexpected chartData shape for pool {pool_id}")
            return []

        result = []
        for entry in data:
            ts  = entry.get("timestamp") or entry.get("date") or ""
            tvl = entry.get("tvlUsd") or entry.get("tvl") or 0.0
            apy = entry.get("apy") or entry.get("apyBase") or 0.0
            result.append({
                "timestamp": str(ts),
                "tvlUsd": float(tvl),
                "apy": float(apy),
            })

        # Return last `days` entries
        return result[-days:] if len(result) > days else result

    def fetch_all_historical(self, days: int = 90) -> dict[str, list[dict]]:
        """
        Fetch historical APY data for all 7 backtest protocols.
        Returns dict keyed by protocol_key → list[{timestamp, tvlUsd, apy}].
        Skips any pool that fails (logs a warning).
        """
        results: dict[str, list[dict]] = {}
        for protocol_key, pool_id in BACKTEST_POOL_IDS.items():
            try:
                history = self.fetch_historical_apy(pool_id=pool_id, days=days)
                results[protocol_key] = history
                log.info(f"Historical APY fetched: {protocol_key} ({len(history)} points)")
            except Exception as exc:
                log.warning(f"Could not fetch historical APY for {protocol_key}: {exc}")
        return results

    def fetch_with_pendle(self, chains: list[str] | None = None) -> dict:
        """
        Fetch whitelist pools AND Pendle PT pools, merged into a single result.

        Extends fetch_pools() by also querying PendleFetcher and appending
        eligible Pendle PT pools to the pools dict. Pendle pools are keyed
        as "pendle-pt-<symbol>-<chain>" and have special="fixed_rate".

        Deduplication: pools are deduplicated by pool_id (DeFiLlama pool UUID).
        If the same pool_id appears in both whitelist and Pendle results, the
        Pendle entry is preferred (it carries richer metadata).

        Args:
            chains: Optional chain filter (same as fetch_pools).

        Returns:
            {
              "pools":         {pool_key: {apy, tvl_usd, chain, tier, ...}},
              "skipped":       [...],
              "pendle_pools":  [{symbol, apy, tvl_usd, chain, ...}],
              "pendle_count":  N,
            }
        """
        from data_pipeline.pendle_fetcher import PendleFetcher

        # 1. Normal whitelist fetch
        base_result = self.fetch_pools(chains=chains)
        pools = base_result.get("pools", {})
        skipped = base_result.get("skipped", [])

        # 2. Pendle PT fetch
        pendle_pools: list[dict] = []
        try:
            pendle_fetcher = PendleFetcher()
            raw_pendle = pendle_fetcher.fetch_pt_pools()

            # Build pool_id index for deduplication
            existing_pool_ids = {v.get("pool_id") for v in pools.values() if v.get("pool_id")}

            for pp in raw_pendle:
                pid = pp.get("pool_id")
                # Deduplicate by pool_id
                if pid and pid in existing_pool_ids:
                    log.debug(f"fetch_with_pendle: dedup {pp['symbol']} (pool_id already present)")
                    continue

                # Build a stable key from symbol + chain
                sym_slug = (pp.get("symbol") or "pendle-pt").lower()
                sym_slug = sym_slug.replace("pt-", "").replace(" ", "-")
                chain_slug = (pp.get("chain") or "arbitrum").lower()
                pool_key = f"pendle-pt-{sym_slug}-{chain_slug}"

                pools[pool_key] = {
                    "pool_id":          pp.get("pool_id"),
                    "chain":            pp.get("chain", "arbitrum"),
                    "tier":             "T2",
                    "protocol":         "Pendle PT",
                    "asset":            "PT-STABLE",
                    "apy":              pp.get("apy", 0.0),
                    "tvl_usd":          pp.get("tvl_usd", 0.0),
                    "special":          "fixed_rate",
                    "symbol":           pp.get("symbol"),
                    "maturity_date":    pp.get("maturity_date"),
                    "days_to_maturity": pp.get("days_to_maturity"),
                }
                if pid:
                    existing_pool_ids.add(pid)
                pendle_pools.append(pp)

            log.info(
                f"fetch_with_pendle: {len(pendle_pools)} Pendle PT pools merged "
                f"({len(pools)} total pools)"
            )
        except Exception as exc:
            log.warning(f"fetch_with_pendle: Pendle fetch failed (non-fatal): {exc}")

        return {
            "pools":        pools,
            "skipped":      skipped,
            "pendle_pools": pendle_pools,
            "pendle_count": len(pendle_pools),
        }

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
                fetched = len(POOL_WHITELIST)
        except Exception as exc:
            log.error(f"DeFiLlamaFetcher.fetch_all failed: {exc}", exc_info=True)
            errors = 1

        return {"fetched": fetched, "errors": errors}
