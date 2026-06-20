"""Manifest discovery + adapter registry + thin CLI (SPA-V417 / MP-204).

Scans ``spa_core/adapter_sdk/manifests/*.yaml|*.yml|*.json``, validates every
manifest and builds a :class:`DeclarativeAdapter` per valid one. A broken
manifest NEVER takes the whole registry down — it lands in ``invalid`` with
its readable problem list while the rest keep loading.

CLI::

    python3 -m spa_core.adapter_sdk.registry
    python3 -m spa_core.adapter_sdk.registry --manifests-dir DIR --out FILE
    python3 -m spa_core.adapter_sdk.registry --no-write --no-fetch

Exit codes: **0** ok (all manifests valid), **1** invalid manifests present,
**2** manifests directory missing/empty (or unexpected error). ``--no-fetch``
disables the live DeFiLlama fetch (offline/CI mode: health degrades honestly to
``error: live feed disabled`` without any network attempt).

The status report ``data/adapter_sdk_status.json`` is written atomically
(tmp + ``os.replace``); ``--no-write`` skips it. STRICTLY READ-ONLY
(SPA-BL-011): public yield data in, one advisory JSON out, no capital moved.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .declarative_adapter import DeclarativeAdapter
from .manifest import MANIFEST_SUFFIXES, ValidationError, load_manifest_file

log = logging.getLogger("spa.adapter_sdk.registry")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "adapter_sdk_status.json"

SCHEMA_VERSION = 1

EXIT_OK = 0
EXIT_INVALID_MANIFESTS = 1
EXIT_EMPTY_OR_ERROR = 2


# ─── Discovery + loading (pure-ish core: reads manifest files only) ───────────


def discover_manifest_paths(manifests_dir: str | Path = DEFAULT_MANIFESTS_DIR) -> List[Path]:
    """Sorted list of manifest files in *manifests_dir* (``[]`` if missing)."""
    root = Path(manifests_dir)
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in MANIFEST_SUFFIXES
    )


def load_all(
    manifests_dir: str | Path = DEFAULT_MANIFESTS_DIR,
    feed=None,
) -> Dict[str, Any]:
    """Build the adapter registry from a manifests directory.

    Returns::

        {
            "manifests_dir": str,
            "files": [str, ...],            # every manifest file seen
            "adapters": {name: DeclarativeAdapter},
            "invalid": [{"file": str, "problems": [str, ...]}, ...],
        }

    Invalid manifests (schema problems, broken YAML/JSON, duplicate names) are
    collected per-file; valid ones still load. ``feed`` is shared across all
    adapters (one DeFiLlama cache) and is injectable for tests.
    """
    root = Path(manifests_dir)
    paths = discover_manifest_paths(root)

    adapters: Dict[str, DeclarativeAdapter] = {}
    invalid: List[Dict[str, Any]] = []

    if feed is None and paths:
        from spa_core.adapters.defillama_feed import DeFiLlamaFeed

        feed = DeFiLlamaFeed()

    for path in paths:
        try:
            manifest = load_manifest_file(path)
        except ValidationError as exc:
            invalid.append({"file": str(path), "problems": exc.problems})
            continue
        if manifest.name in adapters:
            invalid.append(
                {
                    "file": str(path),
                    "problems": [
                        f"duplicate adapter name {manifest.name!r} "
                        f"(already defined by another manifest)"
                    ],
                }
            )
            continue
        adapters[manifest.name] = DeclarativeAdapter(manifest, feed=feed)

    return {
        "manifests_dir": str(root),
        "files": [str(p) for p in paths],
        "adapters": adapters,
        "invalid": invalid,
    }


# ─── Status report ─────────────────────────────────────────────────────────────


def build_status_report(registry: Dict[str, Any], fetch: bool = True) -> Dict[str, Any]:
    """Build the ``adapter_sdk_status.json`` document from a loaded registry.

    With ``fetch=True`` each adapter performs one live ``fetch_pools()`` (which
    degrades honestly to an empty list + ``health=error`` when the feed is
    unreachable). With ``fetch=False`` the health section is still emitted via
    the adapter's lazy ``health()`` (one fetch against whatever feed the
    registry carries — pass a disabled feed for a fully offline run).
    """
    adapters_out: List[Dict[str, Any]] = []
    health_counts = {"ok": 0, "degraded": 0, "error": 0}
    pools_live_total = 0

    for name in sorted(registry["adapters"]):
        adapter: DeclarativeAdapter = registry["adapters"][name]
        pools = adapter.fetch_pools() if fetch else []
        health = adapter.health()
        status = str(health.get("status"))
        if status in health_counts:
            health_counts[status] += 1
        pools_live = int(health.get("pools_live") or 0)
        pools_live_total += pools_live
        m = adapter.manifest
        adapters_out.append(
            {
                "protocol": name,
                "adapter_class": type(adapter).__name__,
                "manifest_file": m.source_path,
                "tier": adapter.tier,
                "cap": adapter.cap,
                "defillama_protocol_id": m.defillama_protocol_id,
                "chains": list(m.chains),
                "symbols": list(m.symbols),
                "quality_gates": m.quality_gates.to_dict(),
                "exit_latency": adapter.exit_latency(),
                "health": health,
                "pools": [p.to_dict() for p in (pools if fetch else [])],
            }
        )

    n_valid = len(registry["adapters"])
    n_invalid = len(registry["invalid"])
    n_files = len(registry["files"])
    if n_files == 0:
        status = "empty"
    elif n_invalid:
        status = "invalid_manifests"
    else:
        status = "ok"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "adapter_sdk.registry",
        "execution_mode": "read_only_simulation",
        "manifests_dir": registry["manifests_dir"],
        "files_scanned": n_files,
        "adapters": adapters_out,
        "invalid_manifests": registry["invalid"],
        "summary": {
            "total_manifests": n_files,
            "valid": n_valid,
            "invalid": n_invalid,
            "health_ok": health_counts["ok"],
            "health_degraded": health_counts["degraded"],
            "health_error": health_counts["error"],
            "pools_live": pools_live_total,
            "live_fetch": bool(fetch),
            "status": status,
        },
    }


# ─── Atomic write ─────────────────────────────────────────────────────────────


def _atomic_write_json(obj: dict, out_path: Path) -> None:
    """Write *obj* as pretty JSON to *out_path* atomically (tmp + os.replace)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".adapter_sdk_status_{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(tmp, out_path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _format_summary(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        (
            f"ADAPTER SDK | manifests={s['total_manifests']} "
            f"valid={s['valid']} invalid={s['invalid']} "
            f"| health ok={s['health_ok']} degraded={s['health_degraded']} "
            f"error={s['health_error']} | pools_live={s['pools_live']} "
            f"| status={s['status']}"
        )
    ]
    for a in report["adapters"]:
        h = a["health"]
        lines.append(
            f"  - {a['protocol']:<14} tier={a['tier']} cap={a['cap']:.2f} "
            f"slug={a['defillama_protocol_id']} health={h['status']} "
            f"pools={h['pools_live']}/{h['pools_expected']}"
            + (f" error={h['error']}" if h.get("error") else "")
        )
    for bad in report["invalid_manifests"]:
        lines.append(f"  ! INVALID {bad['file']}")
        for problem in bad["problems"]:
            lines.append(f"      - {problem}")
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Adapter SDK registry: discover + validate declarative "
        "manifests, report health (SPA-V417, read-only).",
    )
    p.add_argument(
        "--manifests-dir", default=str(DEFAULT_MANIFESTS_DIR),
        help="directory with *.yaml|*.yml|*.json manifests "
             "(default: spa_core/adapter_sdk/manifests)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="status report path (default: data/adapter_sdk_status.json)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="print the summary only; do not write the status report",
    )
    p.add_argument(
        "--no-fetch", action="store_true",
        help="offline mode: no network attempt at all (feed disabled; "
             "health degrades honestly to 'error')",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    feed = None
    if args.no_fetch:
        from spa_core.adapters.defillama_feed import DeFiLlamaFeed

        feed = DeFiLlamaFeed(enabled=False)  # honest offline mode, zero network

    registry = load_all(args.manifests_dir, feed=feed)
    report = build_status_report(registry, fetch=not args.no_fetch)
    print(_format_summary(report))

    if not args.no_write:
        try:
            _atomic_write_json(report, Path(args.out))
            print(f"report written: {args.out}")
        except OSError as exc:
            log.warning("could not write report to %s: %s", args.out, exc)

    status = report["summary"]["status"]
    if status == "empty":
        print(
            f"ERROR: no manifests found in {args.manifests_dir!r}",
        )
        return EXIT_EMPTY_OR_ERROR
    if status == "invalid_manifests":
        return EXIT_INVALID_MANIFESTS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
