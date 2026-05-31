"""
Adapter Status — backend JSON source of truth (Sprint v3.33 / SPA-V333).

Programmatically assembles execution-adapter metadata (tier, allocation cap,
supported chains/assets, dry-run mock APYs, write-state, APY source) directly
from the live adapter modules and emits a single JSON document.  This removes
the metadata duplication introduced in v3.32, where the same values were
hard-coded both in the Python adapters and in the front-end ``ADAPTER_STATUS``
JS constant.

Design goals:
  * Pure stdlib — no external dependencies (no web3 / psycopg2 / requests).
  * Adapter modules are imported LAZILY inside ``try/except`` so a single
    broken adapter cannot abort the whole collection; failures surface as an
    ``"error"`` field on that adapter's record.
  * No network calls; deterministic on the happy path; never raises from
    ``collect_adapter_status`` / ``build_status_document``.
  * Mirrors the structure consumed by the Go-Live tab's adapter-status table.

CLI:
    python3 -m spa_core.execution.adapter_status            # print document
    python3 -m spa_core.execution.adapter_status --json     # print document
    python3 -m spa_core.execution.adapter_status --write    # write data/adapter_status.json
    python3 -m spa_core.execution.adapter_status --write PATH

Sprint v3.33 — initial implementation.
Sprint v3.35 (SPA-V335) — optional live APY enrichment: when ``SPA_LIVE_APY`` is
on, each adapter record gains a ``live_apy`` chain→asset→apy map fetched from
DeFiLlama (graceful — empty/omitted on any failure) and ``apy_source.mode``
flips to ``"live"`` with ``live_values_present=True``.

Sprint v3.58 (SPA-V358) — MEV-routing coverage summary: the top-level
``mev_protection`` block gains a derived ``coverage`` sub-block
``{routed, total, coverage_pct}`` (ZeroDivision-safe) so the Go-Live dashboard
renders one headline figure, and each adapter's ``mev_routed`` flag is surfaced
row-by-row in the dashboard table (front-end only).
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Repo root: spa_core/execution/adapter_status.py → parent.parent.parent.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "adapter_status.json"

SCHEMA_VERSION = 1

# ─── Adapter spec registry ───────────────────────────────────────────────────
# Static metadata that is *not* available by simply reading module-level dicts
# / class attributes.  Dynamic fields (chains, assets, mock APYs) are pulled
# from the adapter modules at collection time and merged with these specs.
#
#   protocol_key      — canonical SPA protocol id
#   module            — dotted path to the adapter module (imported lazily)
#   name              — human-readable display name (matches Go-Live table)
#   tier              — risk tier ("T2"; Sky is conditional "T2-conditional")
#   allocation_cap    — portfolio concentration cap as a fraction (0.20 = 20%)
#   allocation_note   — optional clarifying note (Sky's conditional promotion)
#   write_state       — "BLOCKED" (Phase 3 live-write gated) or
#                       "NOT_IMPLEMENTED" (no live signing path yet)
#   apy_source_project— DeFiLlama "project" substring used for live APY reads
_ADAPTER_SPECS: list[dict[str, Any]] = [
    # ── T1 adapters (highest priority tier) — Sprint v3.57 / SPA-V357 ─────────
    # Aave V3 & Compound V3 route live-broadcast through ``_send_raw_tx`` →
    # ``mev_protection.send_protected``, so they surface in the Go-Live
    # dashboard alongside the v3.52 T2 adapters.  allocation_cap = 0.40 is the
    # canonical T1 per-protocol concentration cap from the risk policy
    # (``spa_core/risk/policy.py`` ``max_concentration_t1 = 0.40``; mirrored in
    # ``spa_core/risk/versions/v1_0_passive.py``).  These adapters expose mock
    # APY via a class-level ``_MOCK_APYS`` (flat asset→apy) rather than a
    # module-level ``_DRY_RUN_APY``; ``_adapter_record`` synthesises the
    # chain→asset→apy map from it (see Step 2).
    {
        "protocol_key": "aave-v3",
        "module": "spa_core.execution.aave_v3_adapter",
        "name": "Aave V3",
        "tier": "T1",
        "allocation_cap": 0.40,
        "allocation_note": None,
        "write_state": "BLOCKED",
        "apy_source_project": "aave",
    },
    {
        "protocol_key": "compound-v3",
        "module": "spa_core.execution.compound_v3_adapter",
        "name": "Compound V3",
        "tier": "T1",
        "allocation_cap": 0.40,
        "allocation_note": None,
        "write_state": "BLOCKED",
        "apy_source_project": "compound",
    },
    {
        "protocol_key": "yearn-v3",
        "module": "spa_core.execution.adapters.yearn_v3_adapter",
        "name": "Yearn V3",
        "tier": "T2",
        "allocation_cap": 0.20,
        "allocation_note": None,
        "write_state": "BLOCKED",
        "apy_source_project": "yearn",
    },
    {
        "protocol_key": "euler-v2",
        "module": "spa_core.execution.adapters.euler_v2_adapter",
        "name": "Euler V2",
        "tier": "T2",
        "allocation_cap": 0.20,
        "allocation_note": None,
        "write_state": "BLOCKED",
        "apy_source_project": "euler",
    },
    {
        "protocol_key": "maple",
        "module": "spa_core.execution.adapters.maple_adapter",
        "name": "Maple",
        "tier": "T2",
        "allocation_cap": 0.20,
        "allocation_note": None,
        "write_state": "BLOCKED",
        "apy_source_project": "maple",
    },
    {
        "protocol_key": "pendle-pt",
        "module": "spa_core.execution.adapters.pendle_pt_adapter",
        "name": "Pendle PT",
        "tier": "T2",
        "allocation_cap": 0.20,
        "allocation_note": None,
        "write_state": "NOT_IMPLEMENTED",
        "apy_source_project": "pendle",
    },
    {
        "protocol_key": "sky-susds",
        "module": "spa_core.execution.adapters.sky_susds_adapter",
        "name": "Sky / sUSDS",
        "tier": "T2-conditional",
        "allocation_cap": 0.0,
        "allocation_note": "→0.30 when ELIGIBLE",
        "write_state": "BLOCKED",
        "apy_source_project": "sky",
    },
]


def _live_apy_enabled() -> bool:
    """Return the SPA_LIVE_APY gate, defaulting to ``False`` on any failure."""
    try:
        from spa_core.execution import defillama_apy_feed

        return bool(defillama_apy_feed.live_apy_enabled())
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("live_apy_enabled lookup failed (%s) — defaulting False", exc)
        return False


def _mev_protection_status() -> dict[str, Any]:
    """Return MEV-protection status (enabled / endpoint / mode / fallbacks).

    Sprint v3.55 (SPA-V355) — surfaces the Flashbots Protect routing state wired
    into adapter live-send paths in v3.52 so the Go-Live dashboard can show
    whether private-mempool protection is active. stdlib-only, never raises:
    any failure yields a safe ``{"enabled": False, ...}`` default.
    """
    try:
        from spa_core.execution import mev_protection
        enabled = bool(mev_protection.is_mev_protection_enabled())
        mode = os.getenv("SPA_FLASHBOTS_MODE", "fast").lower()
        endpoint = mev_protection.get_protected_rpc()
        fallbacks = list(getattr(mev_protection, "_PROTECTED_ENDPOINTS", []))
        return {
            "enabled": enabled,
            "endpoint": endpoint,
            "flashbots_mode": mode,
            "fallback_endpoints": fallbacks,
        }
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("mev_protection status lookup failed (%s) — defaulting disabled", exc)
        return {
            "enabled": False,
            "endpoint": None,
            "flashbots_mode": "fast",
            "fallback_endpoints": [],
        }


def _adapter_mev_routed(module: Any) -> bool:
    """Return whether the adapter module routes live-broadcast via MEV-protection.

    Sprint v3.56 / SPA-V356 — source of truth is the actual wiring: inspect the
    adapter module's source and report whether it references any MEV-broadcast
    helper (``send_raw_transaction_auto`` / ``broadcast_protected_hash`` /
    ``send_protected``). This distinguishes adapters whose live-send path was
    wired through Flashbots Protect (v3.52 T2 adapters) from those that are not
    (e.g. pendle_pt, which is BLOCKED/NotImplemented). stdlib-only, never raises:
    any failure (e.g. ``inspect.getsource`` on a sourceless object) yields False.
    """
    try:
        import inspect

        src = inspect.getsource(module)
        return any(
            name in src
            for name in (
                "send_raw_transaction_auto",
                "broadcast_protected_hash",
                "send_protected",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("mev-routed inspection failed (%s) — defaulting False", exc)
        return False


def _fetch_live_apy_map(
    protocol_key: str,
    mock_apy: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Fetch live DeFiLlama APY for exactly the (chain, asset) pairs in ``mock_apy``.

    Sprint v3.35 / SPA-V335 — embeds *actual* live APY values in the status
    document so the dashboard can render real numbers instead of always falling
    back to the mock constant.

    Behaviour:
      * Iterates the same chain→asset combinations the adapter advertises in its
        ``_DRY_RUN_APY`` map and queries ``defillama_apy_feed.get_live_apy`` for
        each one (protocol matching is identical to the adapters' live path).
      * Only non-``None`` results are kept; a chain with no matched assets is
        omitted entirely, so the resulting map is a strict subset of ``mock_apy``.
      * The feed module is imported lazily inside ``try/except`` and every query
        is individually guarded — a network failure, parse error, or missing
        match yields an empty map rather than aborting collection. NEVER raises.

    Callers must gate this on ``live_enabled`` so it is never invoked (and never
    touches the network) when ``SPA_LIVE_APY`` is off.
    """
    live_map: dict[str, dict[str, float]] = {}
    try:
        from spa_core.execution import defillama_apy_feed
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("defillama_apy_feed import failed (%s) — no live APY", exc)
        return live_map

    for chain, assets in (mock_apy or {}).items():
        for asset in (assets or {}):
            try:
                apy = defillama_apy_feed.get_live_apy(protocol_key, asset, chain)
            except Exception as exc:  # noqa: BLE001 — never propagate
                log.debug(
                    "live APY lookup failed for %s/%s/%s (%s)",
                    protocol_key, asset, chain, exc,
                )
                apy = None
            if apy is not None:
                live_map.setdefault(chain, {})[asset] = apy
    return live_map


def _adapter_record(spec: dict[str, Any], live_enabled: bool) -> dict[str, Any]:
    """Build a single adapter status record from its spec + live module data.

    The adapter module is imported lazily; any failure is captured as an
    ``"error"`` field rather than propagated, so one broken adapter never
    aborts the wider collection.
    """
    record: dict[str, Any] = {
        "protocol_key": spec["protocol_key"],
        "name": spec["name"],
        "tier": spec["tier"],
        "allocation_cap": spec["allocation_cap"],
        "write_state": spec["write_state"],
        # MEV-routing applicability (Sprint v3.56 / SPA-V356) — always present;
        # set True on the happy path when the module wires a protected send.
        "mev_routed": False,
        "apy_source": {
            "mode": "mock",
            "live_project": spec["apy_source_project"],
            "live_enabled": live_enabled,
            "live_values_present": False,
        },
    }
    if spec.get("allocation_note"):
        record["allocation_note"] = spec["allocation_note"]

    try:
        module = importlib.import_module(spec["module"])
        # The adapter class is the single object whose name ends in "Adapter".
        adapter_cls = next(
            getattr(module, attr)
            for attr in dir(module)
            if attr.endswith("Adapter") and isinstance(getattr(module, attr), type)
        )
        mock_apy = getattr(module, "_DRY_RUN_APY", {})
        record["chains"] = list(getattr(adapter_cls, "SUPPORTED_CHAINS", ()))
        record["assets"] = list(getattr(adapter_cls, "SUPPORTED_ASSETS", ()))
        # ── T1 mock-APY synthesis (Sprint v3.57 / SPA-V357) ──────────────────
        # T2 adapters expose a module-level ``_DRY_RUN_APY`` (chain→asset→apy);
        # T1 adapters (aave_v3 / compound_v3) instead carry a class-level
        # ``_MOCK_APYS`` (flat asset→apy).  When the module-level map is absent
        # or empty, synthesise the same chain→asset→apy shape from the class
        # ``_MOCK_APYS`` × ``SUPPORTED_CHAINS`` so the dashboard renders real
        # numbers for T1 too.  Guarded inside the try-block; any failure leaves
        # ``mock_apy`` as the original (possibly empty) value — never-raises.
        if not mock_apy:
            class_apys = getattr(adapter_cls, "_MOCK_APYS", None)
            if class_apys:
                mock_apy = {
                    chain: dict(class_apys)
                    for chain in record["chains"]
                }
        # Deep-copy the nested chain→asset→apy mapping (plain dict, json-safe).
        record["mock_apy"] = {
            chain: dict(assets) for chain, assets in dict(mock_apy).items()
        }
        # MEV-routing applicability (Sprint v3.56 / SPA-V356).
        record["mev_routed"] = _adapter_mev_routed(module)
    except Exception as exc:
        log.warning("adapter %s collection failed: %s", spec["protocol_key"], exc)
        record["error"] = str(exc)
        record.setdefault("chains", [])
        record.setdefault("assets", [])
        record.setdefault("mock_apy", {})
        record.setdefault("mev_routed", False)

    # ── Live APY enrichment (Sprint v3.35 / SPA-V335) ────────────────────────
    # Only when the SPA_LIVE_APY gate is on AND the adapter imported cleanly.
    # On any failure / no match the live map is empty and we transparently stay
    # on the mock source — identical graceful-degradation contract to the
    # adapters' own get_supply_apy live path.
    if live_enabled and "error" not in record and record["mock_apy"]:
        live_apy = _fetch_live_apy_map(spec["protocol_key"], record["mock_apy"])
        if live_apy:
            record["live_apy"] = live_apy
            record["apy_source"]["mode"] = "live"
            record["apy_source"]["live_values_present"] = True

    return record


def collect_adapter_status() -> list[dict[str, Any]]:
    """Collect status records for every registered execution adapter.

    Reads ``_DRY_RUN_APY`` / ``SUPPORTED_CHAINS`` / ``SUPPORTED_ASSETS`` from
    each adapter module and merges them with the static spec.  Never raises on
    the happy path; a failed adapter import yields a record with an ``"error"``
    field instead of aborting collection.
    """
    live_enabled = _live_apy_enabled()
    return [_adapter_record(spec, live_enabled) for spec in _ADAPTER_SPECS]


def build_status_document() -> dict[str, Any]:
    """Assemble the full adapter-status JSON document."""
    adapters = collect_adapter_status()
    # MEV-routing summary (Sprint v3.56 / SPA-V356) — inject per-adapter routing
    # applicability into the top-level mev_protection block.
    mev = _mev_protection_status()
    mev["routed_adapters"] = [a["protocol_key"] for a in adapters if a.get("mev_routed")]
    mev["unrouted_adapters"] = [a["protocol_key"] for a in adapters if not a.get("mev_routed")]
    # ── MEV-routing coverage summary (Sprint v3.58 / SPA-V358) ───────────────
    # Derived headline numbers so the Go-Live dashboard can show a single
    # "N/M adapters routed (P%)" figure without recomputing on the front-end.
    # ZeroDivision-safe: an empty adapter set yields coverage_pct = 0.0.
    _routed_n = len(mev["routed_adapters"])
    _total_n = _routed_n + len(mev["unrouted_adapters"])
    mev["coverage"] = {
        "routed": _routed_n,
        "total": _total_n,
        "coverage_pct": round(100.0 * _routed_n / _total_n, 1) if _total_n else 0.0,
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "execution_mode": os.environ.get("SPA_EXECUTION_MODE", "dry_run"),
        "live_apy_enabled": _live_apy_enabled(),
        "mev_protection": mev,
        "adapters": adapters,
    }


def write_status_json(path: str | os.PathLike[str] | None = None) -> str:
    """Write the status document to ``path`` (default ``data/adapter_status.json``).

    Returns the path written, as a string.
    """
    out_path = Path(path) if path is not None else _DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    document = build_status_document()
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2)
        fh.write("\n")
    log.info("adapter status written to %s", out_path)
    return str(out_path)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.execution.adapter_status",
        description="Emit execution-adapter status metadata as JSON.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--json",
        action="store_true",
        help="print the status document to stdout (default behaviour)",
    )
    group.add_argument(
        "--write",
        nargs="?",
        const="",
        metavar="PATH",
        help="write the status document to data/adapter_status.json (or PATH)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = _build_arg_parser().parse_args(argv)
    if args.write is not None:
        out = write_status_json(args.write or None)
        print(out)
        return 0
    # Default (no args) and --json both print the document.
    print(json.dumps(build_status_document(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
