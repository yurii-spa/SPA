"""Candidate-tier auto-discovery over the DeFiLlama yields API (SPA-V418 / MP-205).

Scans the public DeFiLlama ``/pools`` feed through configurable quality gates
(TVL >= $5M, pool age >= 180 days when the data exposes it, stablecoin-only,
APY sanity band) and writes an **advisory registry of candidates** to
``data/candidate_registry.json``.

ADVISORY ONLY — NOT A WHITELIST
===============================
This module NEVER promotes anything automatically. A candidate landing in
``candidate_registry.json`` is a *suggestion for a human*: admission to the
SPA whitelist happens exclusively through an ADR / explicit human decision
(MP-205 card: "В whitelist — только через ADR/человека"). ``suggested_tier``
is always the literal string ``"candidate"`` — it is not T1/T2/T3 and no
allocator/risk/execution code reads this file.

Quality gates (defaults, all configurable via :class:`GateConfig`):

* ``tvl``         — ``tvlUsd >= min_tvl_usd`` ($5M default);
* ``age``         — pool age >= ``min_age_days`` (180) computed from the
  DeFiLlama ``listedAt``/``inception`` epoch field **when present**; when the
  feed does not expose an age field the gate is honestly reported in
  ``gates_unknown`` ("age_unknown") and the candidate is KEPT, flagged for the
  human reviewer — it is never silently passed off as verified nor silently
  dropped;
* ``stable``      — every leg of the symbol is a known stablecoin (same
  convention as :data:`spa_core.adapter_sdk.declarative_adapter.STABLE_SYMBOLS`);
* ``apy``         — sanity band ``0 < apy <= 30`` percent (higher is suspicious
  for a stablecoin pool);
* ``not_covered`` — the protocol is not already covered by an existing file
  adapter (aave-v3, compound-v3, ...) or an SDK manifest in
  ``spa_core/adapter_sdk/manifests/``.

Honest degradation (SPA-V398 / SPA-BL-011): an unreachable feed (e.g. blocked
egress to ``yields.llama.fi``) yields ``status="error"`` with the error text —
no exception escapes, no mock/fake data is ever substituted. Pure stdlib: the
only network code is :func:`default_fetch_fn` (urllib), and the fetch function
is injectable so tests run with zero network.

CLI::

    python3 -m spa_core.adapter_sdk.discovery
    python3 -m spa_core.adapter_sdk.discovery --no-write --max-candidates 10
    python3 -m spa_core.adapter_sdk.discovery --min-tvl 10000000 --out FILE
    python3 -m spa_core.adapter_sdk.discovery --pools-file dump.json  # offline

Exit codes: **0** ok (>=1 candidate), **1** degraded (feed reachable but no
candidates), **2** error (feed unreachable / bad payload / unexpected error).

The report ``data/candidate_registry.json`` is written atomically
(tmp + ``os.replace``); ``--no-write`` skips it. STRICTLY READ-ONLY
(SPA-BL-011): public yield data in, one advisory JSON out, no capital moved,
no imports from risk/execution/allocator, no LLM SDK imports.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional

from .declarative_adapter import is_stable_symbol

log = logging.getLogger("spa.adapter_sdk.discovery")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "candidate_registry.json"

# Public DeFiLlama yields endpoint (same as spa_core.adapters.defillama_feed;
# duplicated as a constant only — the existing feed module is NOT modified and
# this module deliberately carries its own zero-dependency urllib fetch).
DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"
REQUEST_TIMEOUT = 15.0

SCHEMA_VERSION = 1
SOURCE_NAME = "adapter_sdk.discovery"
SUGGESTED_TIER = "candidate"  # never T1/T2/T3 — promotion is a human/ADR call.

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_ERROR = 2

# DeFiLlama project slugs already covered by the existing FILE adapters
# (spa_core/adapters/*.py — DEFILLAMA_PROJECT constants; pendle_pt uses the
# native Pendle API but maps to the "pendle" yields slug). Manifest-covered
# slugs are discovered dynamically — see :func:`covered_protocol_slugs`.
FILE_ADAPTER_PROTOCOL_SLUGS: FrozenSet[str] = frozenset(
    {
        "aave-v3",
        "compound-v3",
        "morpho-blue",
        "euler-v2",
        "maple",
        "yearn-finance",
        "pendle",
    }
)

# Epoch fields DeFiLlama may expose for pool inception (checked in order).
_AGE_EPOCH_FIELDS = ("listedAt", "inception")


class DiscoveryError(Exception):
    """Raised for unusable feed payloads (caught by run_discovery -> error)."""


# ─── Gate configuration ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateConfig:
    """Quality gates for candidate discovery. All advisory, filter-only."""

    min_tvl_usd: float = 5_000_000.0   # MP-205: TVL >= $5M
    min_age_days: int = 180            # MP-205: age >= 6 months (when known)
    stable_only: bool = True
    min_apy_pct: float = 0.0           # exclusive: apy must be > this
    max_apy_pct: float = 30.0          # above this is suspicious — rejected
    max_candidates: int = 25

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["exclude_covered"] = True  # always on: known protocols are skipped
        return d


# ─── Covered-protocol registry (file adapters + SDK manifests) ───────────────


def covered_protocol_slugs(
    manifests_dir: Optional[Path] = None,
) -> FrozenSet[str]:
    """File-adapter slugs plus every valid SDK manifest's protocol id.

    Reads ``spa_core/adapter_sdk/manifests/`` via the existing registry
    helpers; invalid manifests are skipped (they cannot cover anything).
    """
    from .manifest import ValidationError, load_manifest_file
    from .registry import DEFAULT_MANIFESTS_DIR, discover_manifest_paths

    slugs = set(FILE_ADAPTER_PROTOCOL_SLUGS)
    root = Path(manifests_dir) if manifests_dir is not None else DEFAULT_MANIFESTS_DIR
    for path in discover_manifest_paths(root):
        try:
            manifest = load_manifest_file(path)
        except ValidationError:
            continue  # broken manifest covers nothing
        slug = str(manifest.defillama_protocol_id).strip().lower()
        if slug:
            slugs.add(slug)
    return frozenset(slugs)


def is_covered_protocol(project: str, covered: Iterable[str]) -> bool:
    """True when *project* is already covered by an adapter/manifest slug.

    Matching mirrors the feed convention (case-insensitive substring): the
    slug ``spark`` covers the yields-API project ``sparklend`` etc.
    """
    project_l = str(project).strip().lower()
    if not project_l:
        return False
    return any(slug and slug in project_l for slug in covered)


# ─── Fetch layer (pure stdlib urllib; injectable for tests) ───────────────────


def extract_pools(payload: Any) -> List[dict]:
    """Validate the DeFiLlama envelope ``{"status": "success", "data": [...]}``.

    Raises :class:`DiscoveryError` on anything else — bad payloads must surface
    as ``status="error"``, never as an empty-but-"ok" scan.
    """
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise DiscoveryError(f"unexpected DeFiLlama payload: {type(payload).__name__}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise DiscoveryError("DeFiLlama payload 'data' is not a list")
    return data


def default_fetch_fn(
    url: str = DEFILLAMA_POOLS_URL, timeout: float = REQUEST_TIMEOUT
) -> List[dict]:
    """Fetch the raw pools list via urllib (gzip-aware). Raises on any failure."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "gzip",  # avoid brotli (SPA-V398 convention)
            "User-Agent": "spa-candidate-discovery/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":  # gzip magic
        raw = gzip.decompress(raw)
    return extract_pools(json.loads(raw.decode("utf-8")))


def load_pools_file(path: os.PathLike | str) -> List[dict]:
    """Offline source: a saved pools dump (raw list or DeFiLlama envelope)."""
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, list):
        return payload
    return extract_pools(payload)


# ─── Pure analytic core ──────────────────────────────────────────────────────


def pool_age_days(pool: dict, now_ts: float) -> Optional[int]:
    """Pool age in whole days from ``listedAt``/``inception``, else ``None``.

    ``None`` means the feed does not expose a usable inception timestamp —
    callers must flag this honestly (``age_unknown``), never assume a value.
    """
    for field in _AGE_EPOCH_FIELDS:
        value = pool.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        age = (float(now_ts) - float(value)) / 86_400.0
        if age >= 0:
            return int(age)
    return None


def evaluate_pool(
    pool: Any,
    gates: GateConfig,
    covered: FrozenSet[str],
    now_ts: float,
) -> Optional[Dict[str, Any]]:
    """Run one raw DeFiLlama pool dict through every gate.

    Returns the candidate dict when all decidable gates pass, else ``None``.
    The ``age`` gate with no inception data goes to ``gates_unknown`` and does
    NOT reject the candidate — the human reviewer sees the flag explicitly.
    """
    if not isinstance(pool, dict):
        return None
    project = str(pool.get("project", "") or "").strip()
    symbol = str(pool.get("symbol", "") or "").strip()
    chain = str(pool.get("chain", "") or "").strip()
    if not project or not symbol:
        return None

    gates_passed: List[str] = []
    gates_unknown: List[str] = []

    # Gate: TVL — missing/non-numeric TVL cannot prove >= $5M, so it fails.
    tvl = pool.get("tvlUsd")
    if isinstance(tvl, bool) or not isinstance(tvl, (int, float)):
        return None
    tvl = float(tvl)
    if tvl < gates.min_tvl_usd:
        return None
    gates_passed.append("tvl")

    # Gate: age — verified when the feed exposes inception; honestly flagged
    # as unknown (and kept) when it does not.
    age_days = pool_age_days(pool, now_ts)
    if age_days is None:
        gates_unknown.append("age")
    elif age_days < gates.min_age_days:
        return None
    else:
        gates_passed.append("age")

    # Gate: stablecoin-only (every leg of a multi-token symbol must qualify).
    if gates.stable_only:
        if not is_stable_symbol(symbol):
            return None
        gates_passed.append("stable")

    # Gate: APY sanity band (missing APY -> cannot verify -> reject).
    apy = pool.get("apy")
    if isinstance(apy, bool) or not isinstance(apy, (int, float)):
        return None
    apy = float(apy)
    if not (gates.min_apy_pct < apy <= gates.max_apy_pct):
        return None
    gates_passed.append("apy")

    # Gate: not already covered by a file adapter / SDK manifest.
    if is_covered_protocol(project, covered):
        return None
    gates_passed.append("not_covered")

    pool_id = pool.get("pool")
    if not isinstance(pool_id, str) or not pool_id.strip():
        pool_id = f"{project}-{symbol}-{chain}".lower()

    return {
        "pool_id": pool_id,
        "protocol": project,
        "chain": chain,
        "symbol": symbol,
        "apy_pct": apy,
        "tvl_usd": tvl,
        "age_days": age_days,
        "gates_passed": gates_passed,
        "gates_unknown": gates_unknown,
        "suggested_tier": SUGGESTED_TIER,
    }


def run_discovery(
    fetch_fn: Optional[Callable[[], List[dict]]] = None,
    gates: Optional[GateConfig] = None,
    covered_protocols: Optional[Iterable[str]] = None,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    """Pure-function core: scan -> gate -> dedup -> rank -> report dict.

    * ``fetch_fn`` — zero-arg callable returning the raw pools list
      (default: live :func:`default_fetch_fn`); any exception it raises is
      converted into ``status="error"`` with the message — never re-raised.
    * ``covered_protocols`` — injectable for tests; defaults to file adapters
      plus the real SDK manifests.
    * ``now_ts`` — injectable epoch for deterministic age computation.

    Status: ``ok`` (>=1 candidate), ``degraded`` (clean scan, 0 candidates),
    ``error`` (fetch failed / unusable payload). The report is ADVISORY —
    nothing here touches the whitelist.
    """
    gates = gates if gates is not None else GateConfig()
    now = float(now_ts) if now_ts is not None else time.time()
    covered = (
        covered_protocol_slugs()
        if covered_protocols is None
        else frozenset(str(s).strip().lower() for s in covered_protocols if str(s).strip())
    )
    fetch = fetch_fn if fetch_fn is not None else default_fetch_fn

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_NAME,
        "advisory": "candidates require human/ADR approval; never auto-whitelisted",
        "gates": gates.to_dict(),
        "covered_protocols": sorted(covered),
        "scanned_pools": 0,
        "candidates": [],
        "rejected_count": 0,
        "status": "error",
        "error": None,
    }

    try:
        pools = fetch()
        if not isinstance(pools, list):
            raise DiscoveryError(
                f"fetch_fn returned {type(pools).__name__}, expected list"
            )
    except Exception as exc:  # noqa: BLE001 - honest degradation, never crash
        message = f"{type(exc).__name__}: {exc}"
        log.warning("discovery fetch failed: %s", message)
        report["error"] = message
        return report

    seen_ids = set()
    candidates: List[Dict[str, Any]] = []
    for pool in pools:
        candidate = evaluate_pool(pool, gates, covered, now)
        if candidate is None:
            continue
        if candidate["pool_id"] in seen_ids:
            continue  # dedup by pool_id — first occurrence wins
        seen_ids.add(candidate["pool_id"])
        candidates.append(candidate)

    # Deterministic ranking: biggest TVL first, pool_id tie-break.
    candidates.sort(key=lambda c: (-c["tvl_usd"], c["pool_id"]))
    if gates.max_candidates >= 0:
        candidates = candidates[: gates.max_candidates]

    report["scanned_pools"] = len(pools)
    report["candidates"] = candidates
    report["rejected_count"] = len(pools) - len(candidates)
    report["status"] = "ok" if candidates else "degraded"
    return report


# ─── Atomic write ─────────────────────────────────────────────────────────────


def write_report_atomic(report: Dict[str, Any], out_path: os.PathLike | str) -> None:
    """Atomically write the report JSON (tmp + ``os.replace``, no stray tmp)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".candidate_registry_{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, out)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ─── Thin CLI ─────────────────────────────────────────────────────────────────


def _format_summary(report: Dict[str, Any]) -> str:
    lines = [
        (
            f"CANDIDATE DISCOVERY | scanned={report['scanned_pools']} "
            f"candidates={len(report['candidates'])} "
            f"rejected={report['rejected_count']} | status={report['status']}"
            + (f" error={report['error']}" if report.get("error") else "")
        )
    ]
    for c in report["candidates"]:
        age = f"{c['age_days']}d" if c["age_days"] is not None else "age_unknown"
        lines.append(
            f"  - {c['protocol']:<24} {c['symbol']:<14} {c['chain']:<10} "
            f"apy={c['apy_pct']:.2f}% tvl=${c['tvl_usd']:,.0f} {age}"
            + (" [age_unknown]" if "age" in c["gates_unknown"] else "")
        )
    lines.append(
        "  ADVISORY: candidates are suggestions only — whitelist admission "
        "requires a human/ADR decision."
    )
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.adapter_sdk.discovery",
        description=(
            "Candidate-tier auto-discovery over DeFiLlama quality gates "
            "(SPA-V418 / MP-205). ADVISORY ONLY: whitelist admission is a "
            "human/ADR decision."
        ),
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="report path (default: data/candidate_registry.json)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="print the summary only; do not write the report",
    )
    p.add_argument(
        "--max-candidates", type=int, default=GateConfig.max_candidates,
        help="cap on emitted candidates, ranked by TVL (default: 25)",
    )
    p.add_argument(
        "--min-tvl", type=float, default=GateConfig.min_tvl_usd,
        help="TVL gate in USD (default: 5000000)",
    )
    p.add_argument(
        "--pools-file", default=None,
        help="offline source: JSON file with a saved DeFiLlama pools dump "
             "(raw list or {'status':'success','data':[...]} envelope) "
             "instead of the live API",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    gates = GateConfig(
        min_tvl_usd=float(args.min_tvl),
        max_candidates=int(args.max_candidates),
    )
    fetch_fn: Optional[Callable[[], List[dict]]] = None
    if args.pools_file:
        pools_file = args.pools_file

        def fetch_fn() -> List[dict]:  # errors surface as status=error
            return load_pools_file(pools_file)

    report = run_discovery(fetch_fn=fetch_fn, gates=gates)
    print(_format_summary(report))

    if not args.no_write:
        try:
            write_report_atomic(report, args.out)
            print(f"report written: {args.out}")
        except OSError as exc:
            log.warning("could not write report to %s: %s", args.out, exc)
            return EXIT_ERROR

    return {"ok": EXIT_OK, "degraded": EXIT_DEGRADED}.get(
        str(report["status"]), EXIT_ERROR
    )


if __name__ == "__main__":
    raise SystemExit(main())
