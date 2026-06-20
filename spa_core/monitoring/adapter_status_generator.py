"""Adapter Status Generator — spa_core/monitoring (MP-1195).

Reads ``data/adapter_registry.json`` as the canonical source of truth for
adapter metadata (tier, fallback_apy, chain, per_protocol_cap) and attempts
to enrich APY values with live data from DeFiLlama (5 s timeout, graceful
fallback on any network error).

Output: schema_version 2 where ``adapters`` is a **dict** keyed by snake_case
protocol name.  This satisfies:

* GoLive checker (MP-384) — checks ``doc["adapters"]["compound_v3"]`` etc.
* cycle_runner MP-413 fallback APY merge (iterates ``adapters`` dict).
* Adapter modules that read individual top-level shadow keys:
    - ``morpho_steakhouse_adapter.py`` → ``doc["morpho_steakhouse"]["apy"]``
    - ``aave_arbitrum_adapter.py``     → ``doc["aave_arbitrum"]["apy"]``

APY unit convention (v2): all ``apy`` / ``live_apy`` / ``fallback_apy``
fields are **percentages** (e.g. 5.2 means 5.2 %, not 0.052).

CLI:
    python3 -m spa_core.monitoring.adapter_status_generator          # dry-run
    python3 -m spa_core.monitoring.adapter_status_generator --run    # write

Always exits 0 — advisory module, fail-safe.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY_FILE = _REPO_ROOT / "data" / "adapter_registry.json"
_STATUS_FILE = _REPO_ROOT / "data" / "adapter_status.json"

SCHEMA_VERSION = 2
DEFILLAMA_URL = "https://yields.llama.fi/pools"
DEFILLAMA_TIMEOUT = 5  # seconds

# ── DeFiLlama project / symbol / chain lookup hints ─────────────────────────
# Each value is (project_substring, symbol_substring, chain) — all
# case-insensitive substring matches against the DeFiLlama pools response.
_DEFILLAMA_HINTS: dict[str, tuple[str, str, str]] = {
    "aave_v3":           ("aave-v3",     "USDC",   "Ethereum"),
    "compound_v3":       ("compound-v3", "USDC",   "Ethereum"),
    "aave_arbitrum":     ("aave-v3",     "USDC",   "Arbitrum"),
    "aave_v3_optimism":  ("aave-v3",     "USDC",   "Optimism"),
    "aave_v3_polygon":   ("aave-v3",     "USDC",   "Polygon"),
    "morpho_blue":       ("morpho",      "USDC",   "Ethereum"),
    "morpho_steakhouse": ("morpho",      "USDC",   "Ethereum"),
    "spark_susds":       ("spark",       "USDS",   "Ethereum"),
    "yearn_v3":          ("yearn",       "USDC",   "Ethereum"),
    "euler_v2":          ("euler",       "USDC",   "Ethereum"),
    "maple":             ("maple",       "USDC",   "Ethereum"),
    "fluid_fusdc":       ("fluid",       "USDC",   "Ethereum"),
    "aave_v3_base":      ("aave-v3",     "USDC",   "Base"),
    "moonwell_base":     ("moonwell",    "USDC",   "Base"),
    "morpho_blue_base":  ("morpho",      "USDC",   "Base"),
}

# Direct DeFiLlama pool UUID match — overrides project/symbol matching
_POOL_ID_LOOKUP: dict[str, str] = {
    "morpho_steakhouse": "BEEF01735c132Ada46AA9aA4c54623cAA92A64CB",
}

# TVL estimates (USD) used when DeFiLlama is unavailable
_TVL_ESTIMATES: dict[str, float] = {
    "aave_v3":            12_000_000_000.0,
    "compound_v3":         3_000_000_000.0,
    "morpho_steakhouse":     800_000_000.0,
    "aave_arbitrum":       1_200_000_000.0,
    "aave_v3_optimism":      400_000_000.0,
    "aave_v3_polygon":       600_000_000.0,
    "morpho_blue":         2_000_000_000.0,
    "spark_susds":           500_000_000.0,
    "yearn_v3":              300_000_000.0,
    "euler_v2":              150_000_000.0,
    "maple":                 200_000_000.0,
    "fluid_fusdc":           100_000_000.0,
    "sfrax":                 800_000_000.0,
    "wusdm":                 400_000_000.0,
    "scrvusd":               300_000_000.0,
    "stusd":                 200_000_000.0,
    "sdai":                1_200_000_000.0,
    "frax":                  100_000_000.0,
    "aave_v3_base":          250_000_000.0,
    "morpho_blue_base":      300_000_000.0,
    "moonwell_base":         150_000_000.0,
    "pendle":                500_000_000.0,
    "pendle_pt":             500_000_000.0,
    "susde":                 800_000_000.0,
    "extra_finance_base":     50_000_000.0,
    "fluid_usdc":            100_000_000.0,
    "notional_v3":            50_000_000.0,
}


# ── DeFiLlama helpers ────────────────────────────────────────────────────────

def _fetch_defillama(timeout: int = DEFILLAMA_TIMEOUT) -> Optional[list]:
    """Fetch all pools from DeFiLlama /pools.

    Returns a list of pool dicts on success, ``None`` on any error.
    """
    try:
        req = urllib.request.Request(
            DEFILLAMA_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "SPA-AdapterStatusGenerator/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        pools = raw.get("data", raw) if isinstance(raw, dict) else raw
        if isinstance(pools, list):
            log.debug("DeFiLlama: fetched %d pools", len(pools))
            return pools
        log.warning("DeFiLlama: unexpected response shape")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("DeFiLlama fetch failed (network): %s", exc)
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("DeFiLlama fetch failed (parse): %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — strict fail-safe
        log.warning("DeFiLlama fetch failed (unexpected): %s", exc)
        return None


def _build_pool_indexes(
    pools: list,
) -> tuple[dict[str, dict], dict[tuple[str, str, str], list[dict]]]:
    """Return (by_pool_id, by_project_chain_symbol) indexes for fast lookup."""
    by_id: dict[str, dict] = {}
    by_pcs: dict[tuple[str, str, str], list[dict]] = {}
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        pid = str(pool.get("pool", "")).lower()
        if pid:
            by_id[pid] = pool
        proj = str(pool.get("project", "")).lower()
        chain = str(pool.get("chain", "")).lower()
        sym = str(pool.get("symbol", "")).upper()
        by_pcs.setdefault((proj, chain, sym), []).append(pool)
    return by_id, by_pcs


def _valid_apy(pool: dict) -> Optional[float]:
    """Extract APY (%) from a pool dict; return ``None`` if out of sanity range."""
    apy = pool.get("apy")
    if isinstance(apy, (int, float)) and not isinstance(apy, bool):
        if 0.0 < float(apy) < 200.0:
            return round(float(apy), 4)
    return None


def _lookup_live_apy(
    adapter_key: str,
    by_id: dict[str, dict],
    by_pcs: dict[tuple[str, str, str], list[dict]],
) -> Optional[float]:
    """Look up live APY (%) for *adapter_key* using the pre-built indexes.

    Strategy:
    1. Exact pool UUID match (``_POOL_ID_LOOKUP``).
    2. Best-TVL pool matching project / chain / symbol hints
       (``_DEFILLAMA_HINTS``), using substring matching on each dimension.
    """
    # 1. Exact pool UUID
    raw_id = _POOL_ID_LOOKUP.get(adapter_key, "")
    if raw_id:
        pool = by_id.get(raw_id.lower())
        if pool:
            apy = _valid_apy(pool)
            if apy is not None:
                log.debug("DeFiLlama pool-id hit: %s → %.2f%%", adapter_key, apy)
                return apy

    # 2. Hint-based lookup
    hints = _DEFILLAMA_HINTS.get(adapter_key)
    if not hints:
        return None
    proj_hint, sym_hint, chain_hint = hints
    proj_l = proj_hint.lower()
    chain_l = chain_hint.lower()
    sym_u = sym_hint.upper()

    candidates: list[dict] = []
    for (proj, chain, sym), pool_list in by_pcs.items():
        if proj_l not in proj and proj not in proj_l:
            continue
        if chain_l not in chain and chain not in chain_l:
            continue
        if sym_u not in sym and sym not in sym_u:
            continue
        candidates.extend(pool_list)

    best: Optional[dict] = None
    best_tvl = -1.0
    for cand in candidates:
        tvl = float(cand.get("tvlUsd", 0) or 0)
        if _valid_apy(cand) is not None and tvl > best_tvl:
            best_tvl = tvl
            best = cand

    if best is not None:
        apy = _valid_apy(best)
        if apy is not None:
            log.debug("DeFiLlama hint hit: %s → %.2f%%", adapter_key, apy)
            return apy
    return None


# ── Core document builder ────────────────────────────────────────────────────

def generate(
    registry_path: Path = _REGISTRY_FILE,
    output_path: Path = _STATUS_FILE,
    defillama_timeout: int = DEFILLAMA_TIMEOUT,
) -> dict[str, Any]:
    """Build the v2 adapter_status document.

    Does NOT write to disk — call :func:`write` to persist atomically.

    Args:
        registry_path:     Path to ``adapter_registry.json``.
        output_path:       Intended output path (used only for logging).
        defillama_timeout: HTTP timeout in seconds for DeFiLlama fetch.

    Returns:
        A fully formed ``dict`` ready to be serialised as JSON.
    """
    # ── 1. Read adapter registry ─────────────────────────────────────────────
    try:
        with open(registry_path, encoding="utf-8") as fh:
            registry_doc = json.load(fh)
        adapters_meta: dict[str, Any] = registry_doc.get("adapters", registry_doc)
        if not isinstance(adapters_meta, dict):
            log.error("adapter_registry.json: 'adapters' is not a dict — aborting")
            adapters_meta = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        log.error("Cannot read adapter registry %s: %s", registry_path, exc)
        adapters_meta = {}

    # ── 2. Fetch DeFiLlama (best-effort, fail-safe) ──────────────────────────
    pools = _fetch_defillama(timeout=defillama_timeout)
    by_id: dict[str, dict] = {}
    by_pcs: dict[tuple[str, str, str], list[dict]] = {}
    if pools:
        by_id, by_pcs = _build_pool_indexes(pools)

    now_ts = datetime.now(timezone.utc).isoformat()
    live_count = 0

    # ── 3. Build adapters dict ───────────────────────────────────────────────
    adapters: dict[str, Any] = {}
    for key, meta in adapters_meta.items():
        if not isinstance(meta, dict):
            continue

        # fallback_apy in registry is decimal (0.052 = 5.2%); convert to %
        fallback_pct = round(float(meta.get("fallback_apy", 0.0)) * 100.0, 4)
        tier_raw = meta.get("tier", 2)
        per_cap = float(meta.get("per_protocol_cap", 0.2))
        chain = str(meta.get("chain", "ethereum"))
        is_active = str(meta.get("status", "active")).lower() in {"active"}

        # Live APY lookup (only when DeFiLlama fetch succeeded)
        live_apy: Optional[float] = None
        if pools:
            live_apy = _lookup_live_apy(key, by_id, by_pcs)
            if live_apy is not None:
                live_count += 1

        apy_used = live_apy if live_apy is not None else fallback_pct

        # TVL from DeFiLlama exact pool hit, else static estimate
        tvl = _TVL_ESTIMATES.get(key, 0.0)
        raw_pid = _POOL_ID_LOOKUP.get(key, "").lower()
        if raw_pid and raw_pid in by_id:
            tvl_live = float(by_id[raw_pid].get("tvlUsd", 0) or 0)
            if tvl_live > 0:
                tvl = tvl_live

        adapters[key] = {
            "display_name":     str(meta.get("protocol", key)),
            "apy":              round(apy_used, 4),
            "live_apy":         live_apy,
            "fallback_apy":     fallback_pct,
            "tvl_usd":          tvl,
            "tier":             tier_raw,
            "chain":            chain,
            "per_protocol_cap": per_cap,
            "active":           is_active,
            "last_updated":     now_ts,
        }

    live_apy_enabled = bool(pools and live_count > 0)

    # ── 4. Shadow top-level entries (backward compat) ────────────────────────
    # Several adapter modules and apy_aggregator.py read specific top-level
    # keys from adapter_status.json.  We mirror the same data here so they
    # continue to work without modification.
    #
    # morpho_steakhouse_adapter.py  → doc["morpho_steakhouse"]["apy"]
    # aave_arbitrum_adapter.py      → doc["aave_arbitrum"]["apy"]
    # apy_aggregator.py sections 2-4 → doc.get("morpho_steakhouse" / "aave_arbitrum" / "pendle_pt")

    ms_entry = adapters.get("morpho_steakhouse", {})
    ms_apy = ms_entry.get("apy", 6.5)

    arb_entry = adapters.get("aave_arbitrum", {})
    arb_apy = arb_entry.get("apy", 4.1)

    pendle_entry = adapters.get("pendle_pt", adapters.get("pendle", {}))
    pendle_apy = pendle_entry.get("apy", 8.0)

    doc: dict[str, Any] = {
        "schema_version":   SCHEMA_VERSION,
        "generated_at":     now_ts,
        "generated_by":     "adapter_status_generator",
        "live_apy_enabled": live_apy_enabled,
        "live_count":       live_count,
        # Primary adapters dict (snake_case keys) — GoLive checker reads here
        "adapters":         adapters,
        # ── Backward-compat top-level shadow entries ──────────────────────
        # These duplicate select adapter data for consumers that have NOT yet
        # been migrated to the new nested format.
        "morpho_steakhouse": {
            "apy":          ms_apy,
            "protocol_key": "morpho-blue",
            "bps_gain":     round(max(0.0, ms_apy - 3.2) * 100.0, 1),
            "tier":         "T1",
            "tvl_usd":      ms_entry.get("tvl_usd", _TVL_ESTIMATES.get("morpho_steakhouse", 0.0)),
        },
        "aave_arbitrum": {
            "apy":      arb_apy,
            "tier":     "T1",
            "network":  "arbitrum",
            "tvl_usd":  arb_entry.get("tvl_usd", _TVL_ESTIMATES.get("aave_arbitrum", 0.0)),
        },
        "pendle_pt": {
            "apy":          pendle_apy,
            "tier":         "T2",
            "chain":        "ethereum",
            "protocol_key": "pendle-pt",
        },
    }

    log.info(
        "adapter_status_generator: adapters=%d  live_apy_enabled=%s  live_count=%d",
        len(adapters),
        live_apy_enabled,
        live_count,
    )
    return doc


def write(
    doc: dict[str, Any],
    output_path: Path = _STATUS_FILE,
) -> None:
    """Atomically write *doc* to *output_path* (tmp + os.replace).

    Raises on I/O errors (cleans up the temp file).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=".adapter_status_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_path, output_path)
        log.info("adapter_status_generator: wrote %s", output_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def run_and_write(
    registry_path: Path = _REGISTRY_FILE,
    output_path: Path = _STATUS_FILE,
    defillama_timeout: int = DEFILLAMA_TIMEOUT,
) -> dict[str, Any]:
    """Convenience: generate + write, returning the document.

    Intended for call-sites that want fire-and-forget behaviour (the caller
    catches all exceptions).
    """
    doc = generate(
        registry_path=registry_path,
        output_path=output_path,
        defillama_timeout=defillama_timeout,
    )
    write(doc, output_path)
    return doc


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:  # noqa: D103
    parser = argparse.ArgumentParser(
        description="Generate data/adapter_status.json (schema_version 2)"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="write data/adapter_status.json (default: dry-run, print only)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="DIR",
        help="override data directory (default: <repo>/data/)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFILLAMA_TIMEOUT,
        metavar="SEC",
        help=f"DeFiLlama fetch timeout in seconds (default: {DEFILLAMA_TIMEOUT})",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    reg_path = _REGISTRY_FILE
    out_path = _STATUS_FILE
    if args.data_dir:
        dd = Path(args.data_dir)
        reg_path = dd / "adapter_registry.json"
        out_path = dd / "adapter_status.json"

    doc = generate(
        registry_path=reg_path,
        output_path=out_path,
        defillama_timeout=args.timeout,
    )

    adapters = doc.get("adapters", {})
    live_enabled = doc.get("live_apy_enabled", False)
    live_cnt = doc.get("live_count", 0)

    print(
        f"adapters={len(adapters)}"
        f"  schema_version={doc.get('schema_version')}"
        f"  live_apy_enabled={live_enabled}"
        f"  live_count={live_cnt}"
    )
    for key in ("compound_v3", "morpho_steakhouse", "aave_arbitrum"):
        entry = adapters.get(key, {})
        print(
            f"  {key}: apy={entry.get('apy')}%"
            f"  live_apy={entry.get('live_apy')}"
            f"  fallback_apy={entry.get('fallback_apy')}%"
        )

    if args.run:
        write(doc, out_path)
        print(f"Written → {out_path}")
    else:
        print("(dry-run — pass --run to write file)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
