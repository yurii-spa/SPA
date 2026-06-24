"""
scripts/fetch_historical_apy.py — populate the REAL historical-APY cache for backtesting.

P1 of the Tier-1 upgrade: the backtest (professional_backtest.py) reads
data/bee/defillama_apy_history.json (key → {"apy_series": [{date, apy_decimal}]}). When
that cache is absent it falls back to a seeded NOISE model → near-constant returns →
degenerate Sharpe. This fetches REAL DeFiLlama daily APY history so the backtest runs on
real point-in-time data.

Deterministic, stdlib only (urllib + gzip), no external deps. DeFiLlama /chart APY is in
PERCENT; the cache stores DECIMAL (percent / 100) to match _daily_yield(annual_apy_decimal).

Run on the Mac (needs network). Scheduled weekly before the daily backtest.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import gzip
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
_CACHE = _ROOT / "data" / "bee" / "defillama_apy_history.json"
_POOLS_URL = "https://yields.llama.fi/pools"
_CHART_URL = "https://yields.llama.fi/chart/{pool}"
_TIMEOUT = 25

# protocol bee_key → DeFiLlama selector. bee_key must match BEE_KEY_MAP / protocol names
# used in strategy allocations. meta = optional substring filter on poolMeta (e.g. vault).
SELECTORS: Dict[str, dict] = {
    "aave_v3_usdc_eth":        {"project": "aave-v3",     "chain": "Ethereum", "symbol": "USDC"},
    "compound_v3_usdc_eth":    {"project": "compound-v3", "chain": "Ethereum", "symbol": "USDC"},
    "morpho_steakhouse_usdc":  {"project": "morpho-blue", "chain": "Ethereum", "symbol": "STEAKUSDC"},
    "aave_v3":                 {"project": "aave-v3",     "chain": "Ethereum", "symbol": "USDC"},
    "compound_v3":             {"project": "compound-v3", "chain": "Ethereum", "symbol": "USDC"},
    "morpho_steakhouse":       {"project": "morpho-blue", "chain": "Ethereum", "symbol": "STEAKUSDC"},
    "morpho_blue":             {"project": "morpho-blue", "chain": "Ethereum", "symbol": "STEAKUSDC"},
    "yearn_v3":                {"project": "yearn-finance", "chain": "Ethereum", "symbol": "USDC"},
    "euler_v2":                {"project": "euler-v2",    "chain": "Ethereum", "symbol": "USDC"},
    "maple":                   {"project": "maple",       "chain": "Ethereum", "symbol": "USDC", "meta": "syrup"},
    "fluid":                   {"project": "fluid-lending", "chain": "Ethereum", "symbol": "USDC"},
    "ethena_susde":            {"project": "ethena-usde", "chain": "Ethereum", "symbol": "SUSDE"},
    "aave_v3_base":            {"project": "aave-v3",     "chain": "Base",     "symbol": "USDC"},
    # NOTE: spark_susds / sky_susds are intentionally NOT fetched — RULES.md pins
    # Sky/sUSDS = 0% until on-chain GSM Pause Delay >= 48h is confirmed. They stay on the
    # conservative built-in proxy so the backtest does not contradict the documented policy.
}


def _get(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw)
    except Exception as exc:
        print(f"  fetch error {url[:60]}: {exc}")
        return None


def _match_pool(pools: List[dict], sel: dict) -> Optional[dict]:
    """Highest-TVL pool matching project + chain + symbol (+ optional poolMeta substring)."""
    proj, chain, sym = sel["project"], sel["chain"], sel["symbol"].upper()
    meta = sel.get("meta", "").lower()
    cands = [
        p for p in pools
        if p.get("project") == proj
        and p.get("chain") == chain
        and (p.get("symbol") or "").upper() == sym
        and (not meta or meta in (p.get("poolMeta") or "").lower())
    ]
    if not cands:
        return None
    return max(cands, key=lambda p: p.get("tvlUsd") or 0)


def _chart_to_series(chart: dict) -> List[dict]:
    """DeFiLlama /chart → [{date: ISO, apy: decimal}] (one point per day, percent/100)."""
    out: List[dict] = []
    seen = set()
    for pt in chart.get("data", []):
        ts = pt.get("timestamp")
        apy = pt.get("apy")
        if ts is None or apy is None:
            continue
        try:
            d = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
        except Exception:
            continue
        if d in seen:
            continue
        seen.add(d)
        out.append({"date": d, "apy": round(float(apy) / 100.0, 6)})  # percent → decimal
    out.sort(key=lambda x: x["date"])
    return out


def fetch_all() -> dict:
    print("Fetching DeFiLlama /pools …")
    pools_resp = _get(_POOLS_URL)
    pools = (pools_resp or {}).get("data", []) if pools_resp else []
    print(f"  {len(pools)} pools")

    pool_results: Dict[str, dict] = {}
    matched, missed = [], []
    # de-dup chart fetches: same pool id may back several bee_keys
    chart_cache: Dict[str, List[dict]] = {}

    for bee_key, sel in SELECTORS.items():
        pool = _match_pool(pools, sel)
        if not pool:
            missed.append(bee_key)
            continue
        pid = pool["pool"]
        if pid not in chart_cache:
            chart = _get(_CHART_URL.format(pool=pid))
            chart_cache[pid] = _chart_to_series(chart) if chart else []
        series = chart_cache[pid]
        if not series:
            missed.append(bee_key)
            continue
        pool_results[bee_key] = {
            "apy_series": series,
            "pool_id": pid,
            "tvl_usd": pool.get("tvlUsd"),
            "current_apy_pct": pool.get("apy"),
            "n_days": len(series),
        }
        matched.append(f"{bee_key}({len(series)}d)")

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "defillama_real",
        "llm_forbidden": True,
        "matched": len(pool_results),
        "missed": missed,
        "pool_results": pool_results,
    }
    _CACHE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_CACHE.parent, prefix=".apyhist_")
    with os.fdopen(fd, "w") as f:
        json.dump(out, f, indent=2)
    os.replace(tmp, _CACHE)
    print(f"matched {len(pool_results)}: {', '.join(matched)}")
    print(f"missed {len(missed)}: {', '.join(missed)}")
    print(f"saved → {_CACHE}")
    return out


if __name__ == "__main__":
    fetch_all()
