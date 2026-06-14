#!/usr/bin/env python3
"""Daily Risk Limits Checker (SPA / MP-375) — deterministic gate, LLM FORBIDDEN.

Checks five real-time risk limits before each allocation cycle:

    DL-01  Daily Loss          — HALT if loss > MAX_DAILY_LOSS_PCT
    DL-02  Peak Drawdown       — HALT if peak-to-trough > MAX_DRAWDOWN_PCT
    DL-03  Adapter Concentration — WARN if one adapter > MAX_SINGLE_ADAPTER_PCT
    DL-04  APY Sanity Low      — WARN if any APY < MIN_APY_SANITY_PCT
    DL-05  APY Sanity High     — WARN if any APY > MAX_APY_SANITY_PCT

Gate logic
----------
- **HALT**  — DL-01 or DL-02 FAIL → allocation must be blocked immediately.
- **WARN**  — DL-03, DL-04, or DL-05 FAIL → log & note, allocation proceeds.
- **PASS**  — all checks nominal.

``approved=False`` from RiskPolicy and HALT from DailyLimitsChecker CANNOT be
overridden by any agent.

Safety / scope
--------------
*   Strictly deterministic, no LLM SDK, no network, no external libraries.
*   Pure stdlib: json, datetime, os, math, tempfile, logging, pathlib, argparse.
*   All writes are atomic: mkstemp + os.replace.
*   Never imports execution/, feed_health/, or any risk-agent capital-touching
    code. Reads ``equity_curve_daily.json`` (advisory, read-only); writes only
    ``data/risk_limits_check.json``.

CLI::

    python3 -m spa_core.risk.daily_limits [--data-dir <dir>] [--run]

``--run`` triggers atomic write of ``data/risk_limits_check.json``.
Without ``--run``, prints the result to stdout only (default / ``--check`` mode).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.risk.daily_limits")

# ── Repository layout ────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

EQUITY_FILENAME = "equity_curve_daily.json"
OUTPUT_FILENAME = "risk_limits_check.json"

# ── Gate verdicts ────────────────────────────────────────────────────────────

GATE_PASS = "PASS"
GATE_WARN = "WARN"
GATE_HALT = "HALT"

CHECK_PASS = "PASS"
CHECK_FAIL = "FAIL"
CHECK_WARN = "WARN"
CHECK_SKIP = "SKIP"   # not enough data to evaluate


# ═══════════════════════════════════════════════════════════════════════════════
class DailyLimitsChecker:
    """Deterministic risk-limit gate for the SPA paper-trading cycle.

    Parameters
    ----------
    max_daily_loss_pct:
        Daily PnL loss threshold (% of previous close) that triggers HALT.
        Default 2.0 → loss > 2 % → HALT.
    max_drawdown_pct:
        Peak-to-trough drawdown threshold that triggers HALT.
        Default 10.0 → drawdown > 10 % → HALT.
    max_single_adapter_pct:
        Maximum fraction of total allocation for one adapter before WARN.
        Default 40.0 → any adapter > 40 % → WARN.
    min_apy_sanity_pct:
        Minimum APY below which a stale-data / zero-yield WARN is raised.
        Default 0.5.
    max_apy_sanity_pct:
        Maximum APY above which an unrealistic-yield WARN is raised.
        Default 50.0.
    """

    MAX_DAILY_LOSS_PCT:    float = 2.0
    MAX_DRAWDOWN_PCT:      float = 10.0
    MAX_SINGLE_ADAPTER_PCT: float = 40.0
    MIN_APY_SANITY_PCT:    float = 0.5
    MAX_APY_SANITY_PCT:    float = 50.0

    def __init__(
        self,
        *,
        max_daily_loss_pct:    float | None = None,
        max_drawdown_pct:      float | None = None,
        max_single_adapter_pct: float | None = None,
        min_apy_sanity_pct:    float | None = None,
        max_apy_sanity_pct:    float | None = None,
    ) -> None:
        self.max_daily_loss_pct     = max_daily_loss_pct     if max_daily_loss_pct     is not None else self.MAX_DAILY_LOSS_PCT
        self.max_drawdown_pct       = max_drawdown_pct       if max_drawdown_pct       is not None else self.MAX_DRAWDOWN_PCT
        self.max_single_adapter_pct = max_single_adapter_pct if max_single_adapter_pct is not None else self.MAX_SINGLE_ADAPTER_PCT
        self.min_apy_sanity_pct     = min_apy_sanity_pct     if min_apy_sanity_pct     is not None else self.MIN_APY_SANITY_PCT
        self.max_apy_sanity_pct     = max_apy_sanity_pct     if max_apy_sanity_pct     is not None else self.MAX_APY_SANITY_PCT

    # ── Public API ────────────────────────────────────────────────────────────

    def check(
        self,
        equity_history: list[dict[str, Any]],
        allocation: dict[str, float],
        apy_map: dict[str, float],
    ) -> dict[str, Any]:
        """Run all five risk-limit checks and return a gate verdict.

        Parameters
        ----------
        equity_history:
            Ordered list of equity-curve bars (oldest first).  Each bar must
            have at least a ``"close_equity"`` (or ``"equity"``) float key.
        allocation:
            Mapping of adapter-name → USD allocation (e.g.
            ``{"aave_v3": 40000, "compound_v3": 35000}``).
        apy_map:
            Mapping of adapter-name → APY in percent
            (e.g. ``{"aave_v3": 3.5, "compound_v3": 4.8}``).

        Returns
        -------
        dict with keys:
            ``gate``         – "PASS" | "HALT" | "WARN"
            ``checks``       – list of check dicts (id, name, status, value, limit)
            ``halt_reasons`` – list[str], non-empty only when gate == "HALT"
            ``warn_reasons`` – list[str], non-empty only when gate == "WARN"
            ``checked_at``   – ISO-8601 UTC timestamp
        """
        now_ts = datetime.now(timezone.utc).isoformat()

        dl01 = self._check_daily_loss(equity_history)
        dl02 = self._check_drawdown(equity_history)
        dl03 = self._check_concentration(allocation)
        dl04, dl05 = self._check_apy_sanity(apy_map)

        checks = [dl01, dl02, dl03, dl04, dl05]

        halt_reasons: list[str] = []
        warn_reasons: list[str] = []

        for chk in checks:
            if chk["status"] == CHECK_FAIL:
                if chk["id"] in ("DL-01", "DL-02"):
                    halt_reasons.append(
                        f"{chk['id']} {chk['name']}: {chk.get('message', '')}"
                    )
                else:
                    # DL-03 / DL-04 / DL-05 FAIL → treated as WARN
                    warn_reasons.append(
                        f"{chk['id']} {chk['name']}: {chk.get('message', '')}"
                    )
            elif chk["status"] == CHECK_WARN:
                warn_reasons.append(
                    f"{chk['id']} {chk['name']}: {chk.get('message', '')}"
                )

        if halt_reasons:
            gate = GATE_HALT
        elif warn_reasons:
            gate = GATE_WARN
        else:
            gate = GATE_PASS

        return {
            "gate": gate,
            "checks": checks,
            "halt_reasons": halt_reasons,
            "warn_reasons": warn_reasons,
            "checked_at": now_ts,
        }

    def save_result(
        self,
        result: dict[str, Any],
        data_dir: str | Path = "data",
    ) -> None:
        """Atomically write ``risk_limits_check.json`` to *data_dir*.

        Uses mkstemp + os.replace for crash-safe atomic update.
        Never raises: I/O errors are caught and logged as WARNING.
        """
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        target = data_dir / OUTPUT_FILENAME
        payload = json.dumps(result, indent=2, ensure_ascii=False)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=data_dir, prefix=".risk_limits_check_", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                os.replace(tmp_path, target)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            log.warning("DailyLimitsChecker.save_result failed: %s", exc)

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_daily_loss(
        self, equity_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """DL-01: Compare last two equity bars; FAIL if loss > threshold."""
        base = {
            "id": "DL-01",
            "name": "Daily Loss",
            "limit": self.max_daily_loss_pct,
        }

        if not equity_history or len(equity_history) < 2:
            return {**base, "status": CHECK_SKIP, "value": None,
                    "message": "insufficient equity history (need ≥ 2 bars)"}

        prev_close = _bar_equity(equity_history[-2])
        curr_close = _bar_equity(equity_history[-1])

        if prev_close is None or curr_close is None:
            return {**base, "status": CHECK_SKIP, "value": None,
                    "message": "missing equity value in bars"}

        if prev_close <= 0:
            return {**base, "status": CHECK_SKIP, "value": None,
                    "message": "previous close equity is zero or negative"}

        loss_pct = (prev_close - curr_close) / prev_close * 100.0

        if loss_pct > self.max_daily_loss_pct:
            return {
                **base,
                "status": CHECK_FAIL,
                "value": round(loss_pct, 4),
                "message": (
                    f"daily loss {loss_pct:.2f}% exceeds limit "
                    f"{self.max_daily_loss_pct:.1f}%"
                ),
            }

        return {
            **base,
            "status": CHECK_PASS,
            "value": round(loss_pct, 4),
            "message": f"daily loss {max(loss_pct, 0):.2f}% within limit",
        }

    def _check_drawdown(
        self, equity_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """DL-02: Peak-to-trough drawdown; FAIL if > threshold."""
        base = {
            "id": "DL-02",
            "name": "Peak Drawdown",
            "limit": self.max_drawdown_pct,
        }

        if not equity_history:
            return {**base, "status": CHECK_SKIP, "value": None,
                    "message": "no equity history"}

        equities = [_bar_equity(b) for b in equity_history]
        equities = [e for e in equities if e is not None]

        if not equities:
            return {**base, "status": CHECK_SKIP, "value": None,
                    "message": "no valid equity values in history"}

        peak = equities[0]
        max_dd_pct = 0.0
        for eq in equities:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak * 100.0
                if dd > max_dd_pct:
                    max_dd_pct = dd

        if max_dd_pct > self.max_drawdown_pct:
            return {
                **base,
                "status": CHECK_FAIL,
                "value": round(max_dd_pct, 4),
                "message": (
                    f"peak drawdown {max_dd_pct:.2f}% exceeds limit "
                    f"{self.max_drawdown_pct:.1f}%"
                ),
            }

        return {
            **base,
            "status": CHECK_PASS,
            "value": round(max_dd_pct, 4),
            "message": f"peak drawdown {max_dd_pct:.2f}% within limit",
        }

    def _check_concentration(
        self, allocation: dict[str, float]
    ) -> dict[str, Any]:
        """DL-03: Single-adapter concentration; WARN if > threshold."""
        base = {
            "id": "DL-03",
            "name": "Adapter Concentration",
            "limit": self.max_single_adapter_pct,
        }

        if not allocation:
            return {**base, "status": CHECK_SKIP, "value": None,
                    "message": "empty allocation"}

        total = sum(float(v) for v in allocation.values() if v is not None)
        if total <= 0:
            return {**base, "status": CHECK_SKIP, "value": None,
                    "message": "total allocation is zero"}

        max_pct = 0.0
        max_adapter = ""
        for adapter, usd in allocation.items():
            pct = float(usd) / total * 100.0
            if pct > max_pct:
                max_pct = pct
                max_adapter = adapter

        if max_pct > self.max_single_adapter_pct:
            return {
                **base,
                "status": CHECK_FAIL,
                "value": round(max_pct, 4),
                "top_adapter": max_adapter,
                "message": (
                    f"{max_adapter} at {max_pct:.1f}% exceeds limit "
                    f"{self.max_single_adapter_pct:.1f}%"
                ),
            }

        return {
            **base,
            "status": CHECK_PASS,
            "value": round(max_pct, 4),
            "top_adapter": max_adapter,
            "message": f"max adapter concentration {max_pct:.1f}% within limit",
        }

    def _check_apy_sanity(
        self, apy_map: dict[str, float]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """DL-04 (low APY) and DL-05 (high APY) sanity checks.

        Returns a tuple (dl04, dl05).
        """
        base04 = {
            "id": "DL-04",
            "name": "APY Sanity Low",
            "limit": self.min_apy_sanity_pct,
        }
        base05 = {
            "id": "DL-05",
            "name": "APY Sanity High",
            "limit": self.max_apy_sanity_pct,
        }

        if not apy_map:
            skip = "empty apy_map"
            return (
                {**base04, "status": CHECK_SKIP, "value": None, "message": skip},
                {**base05, "status": CHECK_SKIP, "value": None, "message": skip},
            )

        values = [float(v) for v in apy_map.values() if v is not None]
        if not values:
            skip = "no numeric APY values"
            return (
                {**base04, "status": CHECK_SKIP, "value": None, "message": skip},
                {**base05, "status": CHECK_SKIP, "value": None, "message": skip},
            )

        min_apy = min(values)
        max_apy = max(values)
        min_adapter = next(k for k, v in apy_map.items() if float(v) == min_apy)
        max_adapter = next(k for k, v in apy_map.items() if float(v) == max_apy)

        # DL-04
        if min_apy < self.min_apy_sanity_pct:
            dl04: dict[str, Any] = {
                **base04,
                "status": CHECK_FAIL,
                "value": round(min_apy, 4),
                "adapter": min_adapter,
                "message": (
                    f"{min_adapter} APY {min_apy:.2f}% below sanity floor "
                    f"{self.min_apy_sanity_pct:.1f}% (stale data?)"
                ),
            }
        else:
            dl04 = {
                **base04,
                "status": CHECK_PASS,
                "value": round(min_apy, 4),
                "adapter": min_adapter,
                "message": f"min APY {min_apy:.2f}% above sanity floor",
            }

        # DL-05
        if max_apy > self.max_apy_sanity_pct:
            dl05: dict[str, Any] = {
                **base05,
                "status": CHECK_FAIL,
                "value": round(max_apy, 4),
                "adapter": max_adapter,
                "message": (
                    f"{max_adapter} APY {max_apy:.2f}% exceeds sanity cap "
                    f"{self.max_apy_sanity_pct:.1f}% (unrealistic?)"
                ),
            }
        else:
            dl05 = {
                **base05,
                "status": CHECK_PASS,
                "value": round(max_apy, 4),
                "adapter": max_adapter,
                "message": f"max APY {max_apy:.2f}% below sanity cap",
            }

        return dl04, dl05


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bar_equity(bar: dict[str, Any]) -> float | None:
    """Extract the equity float from an equity-curve bar dict.

    Tries ``close_equity`` first (cycle_runner schema), then ``equity``
    (legacy / alternative schema).  Returns None if neither key is present or
    the value cannot be coerced to float.
    """
    for key in ("close_equity", "equity"):
        val = bar.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def _read_equity_history(data_dir: Path) -> list[dict[str, Any]]:
    """Read ``equity_curve_daily.json`` and return the list of daily bars.

    Supports both the ``{"daily": [...]}`` envelope (cycle_runner) and a bare
    list (legacy). Returns empty list on any error.
    """
    path = data_dir / EQUITY_FILENAME
    if not path.exists():
        log.debug("equity file not found: %s", path)
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("failed to read %s: %s", path, exc)
        return []
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        bars = doc.get("daily") or doc.get("equity") or []
        if isinstance(bars, list):
            return bars
    return []


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_cli_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SPA Daily Risk Limits Checker (DL-01..DL-05)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        metavar="DIR",
        help=f"data directory (default: {_DEFAULT_DATA_DIR})",
    )
    p.add_argument(
        "--run",
        action="store_true",
        help="write result to data/risk_limits_check.json (default: print only)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="print result only, do not write (default behaviour)",
    )
    return p


def _main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )
    args = _build_cli_parser().parse_args(argv)
    data_dir = Path(args.data_dir)

    checker = DailyLimitsChecker()

    # Read equity history
    eq_history = _read_equity_history(data_dir)

    # Build a minimal allocation from the last equity bar's positions (advisory)
    allocation: dict[str, float] = {}
    if eq_history:
        last_bar = eq_history[-1]
        positions = last_bar.get("positions") or {}
        if isinstance(positions, dict):
            allocation = {k: float(v) for k, v in positions.items() if v}

    # Build an APY map from the last bar's apy_today (scalar) as a fallback;
    # real callers pass the live apy_map from the adapter orchestrator.
    apy_map: dict[str, float] = {}
    if eq_history:
        apy_val = eq_history[-1].get("apy_today")
        if apy_val is not None:
            try:
                apy_map = {"portfolio": float(apy_val)}
            except (TypeError, ValueError):
                pass

    result = checker.check(eq_history, allocation, apy_map)

    # Output
    gate = result["gate"]
    print(f"\n{'='*60}")
    print(f"  SPA Daily Risk Limits — gate: {gate}")
    print(f"{'='*60}")
    for chk in result["checks"]:
        status = chk["status"]
        icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "–"}.get(status, "?")
        val = chk.get("value")
        val_str = f"{val:.2f}" if isinstance(val, float) else str(val)
        print(f"  {icon} {chk['id']}  {chk['name']:<25s}  {status:<5s}  "
              f"value={val_str}  limit={chk.get('limit')}")
        print(f"       {chk.get('message','')}")

    if result["halt_reasons"]:
        print("\n  🔴 HALT REASONS:")
        for r in result["halt_reasons"]:
            print(f"     • {r}")
    if result["warn_reasons"]:
        print("\n  🟡 WARN REASONS:")
        for r in result["warn_reasons"]:
            print(f"     • {r}")
    print()

    if args.run:
        checker.save_result(result, data_dir)
        print(f"  ✔ written → {data_dir / OUTPUT_FILENAME}")
    elif not args.check:
        # Default: print only (--check mode)
        pass

    # Exit codes: 0=PASS/WARN, 2=HALT
    sys.exit(2 if gate == GATE_HALT else 0)


if __name__ == "__main__":  # pragma: no cover
    _main()
