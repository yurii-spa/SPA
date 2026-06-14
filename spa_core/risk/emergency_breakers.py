#!/usr/bin/env python3
"""Emergency Circuit Breakers (SPA / ADR-030) — deterministic gate, LLM FORBIDDEN.

Five coarse fail-hard circuit breakers that sit ABOVE DailyLimitsChecker in the
check hierarchy.  They detect catastrophic scenarios that DL-01..DL-05 are not
designed to catch:

    EB-01  Protocol Exploit Alert    — HALT if any T1 adapter APY > 100 %
    EB-02  Oracle Divergence Cascade — HALT if ≥3 adapters diverge >500 bps from static
    EB-03  Gas Crisis                — PAUSE if base gas > 50 Gwei
    EB-04  Equity Flash Crash        — HALT if equity drops >15 % in one cycle
    EB-05  Data Corruption           — HALT if equity_history has NaN/negative/non-monotonic

Verdict precedence
------------------
    HALT  > PAUSE  > CLEAR

    EB-01, EB-02, EB-04, EB-05  →  HALT
    EB-03                        →  PAUSE
    All clear                    →  CLEAR

Integration
-----------
Call ``check_all()`` in ``cycle_runner.py`` BEFORE ``DailyLimitsChecker.check()``
and BEFORE ``RiskPolicy.check_portfolio_health()``.  If status is not CLEAR,
abort / skip the cycle.

Safety / scope
--------------
*   Strictly deterministic — no LLM, no network, no external libraries.
*   Pure stdlib: json, datetime, os, math, tempfile, logging, pathlib.
*   All writes are atomic: mkstemp + os.replace.
*   Never imports execution/, feed_health/, or any capital-touching code.
*   Reads equity_history and apy_map as plain Python objects (caller supplies).
*   Writes only ``data/emergency_status.json``.

CLI::

    python3 -m spa_core.risk.emergency_breakers --help
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("spa.risk.emergency_breakers")

# ── Verdict constants ────────────────────────────────────────────────────────

STATUS_CLEAR = "CLEAR"
STATUS_PAUSE = "PAUSE"
STATUS_HALT  = "HALT"

CHECK_PASS = "PASS"
CHECK_FAIL = "FAIL"
CHECK_SKIP = "SKIP"

OUTPUT_FILENAME = "emergency_status.json"

# ── Precedence ordering (higher index = more severe) ────────────────────────
_SEVERITY = {STATUS_CLEAR: 0, STATUS_PAUSE: 1, STATUS_HALT: 2}


def _max_status(a: str, b: str) -> str:
    """Return the more severe of two status strings."""
    return a if _SEVERITY.get(a, 0) >= _SEVERITY.get(b, 0) else b


# ═══════════════════════════════════════════════════════════════════════════════
class EmergencyBreakers:
    """Deterministic emergency circuit-breaker gate for the SPA paper-trading cycle.

    All thresholds are class-level constants so they are easy to locate and test
    without instantiation.  Override them per-instance via constructor kwargs.

    Parameters
    ----------
    apy_exploit_threshold_pct:
        Single-adapter APY above which EB-01 triggers.  Default 100.0 %.
    oracle_divergence_cascade_bps:
        APY divergence from static fallback (in basis points) for EB-02.
        Default 500 bps (5 percentage points).
    oracle_cascade_min_adapters:
        Minimum number of adapters that must diverge simultaneously for EB-02.
        Default 3.
    gas_crisis_gwei:
        Base gas price (Gwei) above which EB-03 triggers.  Default 50.0.
    equity_flash_crash_pct:
        Intra-cycle equity drop percentage that triggers EB-04.  Default 15.0 %.
    """

    # ── Default thresholds ────────────────────────────────────────────────────
    APY_EXPLOIT_THRESHOLD_PCT:       float = 100.0
    ORACLE_DIVERGENCE_CASCADE_BPS:   float = 500.0
    ORACLE_CASCADE_MIN_ADAPTERS:     int   = 3
    GAS_CRISIS_GWEI:                 float = 50.0
    EQUITY_FLASH_CRASH_PCT:          float = 15.0

    def __init__(
        self,
        *,
        apy_exploit_threshold_pct:     float | None = None,
        oracle_divergence_cascade_bps: float | None = None,
        oracle_cascade_min_adapters:   int   | None = None,
        gas_crisis_gwei:               float | None = None,
        equity_flash_crash_pct:        float | None = None,
    ) -> None:
        self.apy_exploit_threshold_pct = (
            apy_exploit_threshold_pct
            if apy_exploit_threshold_pct is not None
            else self.APY_EXPLOIT_THRESHOLD_PCT
        )
        self.oracle_divergence_cascade_bps = (
            oracle_divergence_cascade_bps
            if oracle_divergence_cascade_bps is not None
            else self.ORACLE_DIVERGENCE_CASCADE_BPS
        )
        self.oracle_cascade_min_adapters = (
            oracle_cascade_min_adapters
            if oracle_cascade_min_adapters is not None
            else self.ORACLE_CASCADE_MIN_ADAPTERS
        )
        self.gas_crisis_gwei = (
            gas_crisis_gwei
            if gas_crisis_gwei is not None
            else self.GAS_CRISIS_GWEI
        )
        self.equity_flash_crash_pct = (
            equity_flash_crash_pct
            if equity_flash_crash_pct is not None
            else self.EQUITY_FLASH_CRASH_PCT
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def check_all(
        self,
        apy_map:        dict[str, float],
        equity_history: list[dict[str, Any]],
        gas_gwei:       float = 0.0,
        static_apy:     dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Run all five emergency circuit breakers and return a combined verdict.

        Parameters
        ----------
        apy_map:
            Mapping of adapter-name → current APY in percent.
            Example: ``{"aave_v3": 3.5, "compound_v3": 105.0}``.
        equity_history:
            Ordered list of equity-curve bars (oldest first).
            Each bar must contain a ``"close_equity"`` or ``"equity"`` float and
            optionally a ``"timestamp"`` ISO string for EB-05 timestamp checks.
        gas_gwei:
            Current base gas price in Gwei.  Default 0.0 (EB-03 skipped).
        static_apy:
            Optional mapping of adapter-name → baseline/static APY in percent.
            Required for EB-02 to compute divergence.  When None, EB-02 is
            skipped.

        Returns
        -------
        dict with keys:
            ``status``      – "CLEAR" | "PAUSE" | "HALT"
            ``triggered``   – list[str] of EB codes that fired (e.g. ["EB-01"])
            ``checks``      – dict keyed by "eb01"…"eb05" with per-check details
            ``checked_at``  – ISO-8601 UTC timestamp
        """
        now_ts = datetime.now(timezone.utc).isoformat()

        eb01 = self.check_eb01_exploit_probe(apy_map)
        eb02 = self.check_eb02_oracle_cascade(apy_map, static_apy or {})
        eb03 = self.check_eb03_gas_crisis(gas_gwei)
        eb04 = self.check_eb04_flash_crash(equity_history)
        eb05 = self.check_eb05_data_corruption(equity_history)

        checks = {
            "eb01": eb01,
            "eb02": eb02,
            "eb03": eb03,
            "eb04": eb04,
            "eb05": eb05,
        }

        # Determine overall status — HALT > PAUSE > CLEAR
        overall = STATUS_CLEAR
        triggered: list[str] = []

        for code, chk in checks.items():
            eb_status = chk.get("verdict", STATUS_CLEAR)
            if eb_status in (STATUS_HALT, STATUS_PAUSE):
                overall = _max_status(overall, eb_status)
                triggered.append(chk.get("id", code.upper()))

        result: dict[str, Any] = {
            "status":     overall,
            "triggered":  triggered,
            "checks":     checks,
            "checked_at": now_ts,
        }

        if overall == STATUS_HALT:
            log.critical(
                "EmergencyBreakers HALT — triggered: %s", triggered
            )
        elif overall == STATUS_PAUSE:
            log.warning(
                "EmergencyBreakers PAUSE — triggered: %s", triggered
            )
        else:
            log.debug("EmergencyBreakers CLEAR")

        return result

    # ── Individual checks ─────────────────────────────────────────────────────

    def check_eb01_exploit_probe(self, apy_map: dict[str, float]) -> dict[str, Any]:
        """EB-01: Halt if any adapter reports APY above the exploit threshold.

        Legitimate stablecoin lending APYs never exceed 100 %.  A sudden spike
        above this level indicates an exploit probe, oracle manipulation, or
        corrupted data from the adapter.
        """
        base: dict[str, Any] = {
            "id":        "EB-01",
            "name":      "Protocol Exploit Alert",
            "threshold": self.apy_exploit_threshold_pct,
        }

        if not apy_map:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": "empty apy_map — skipped"}

        offenders: list[dict[str, Any]] = []
        for adapter, apy in apy_map.items():
            try:
                v = float(apy)
            except (TypeError, ValueError):
                continue
            if math.isnan(v) or math.isinf(v):
                # Treat non-finite APY as an exploit signal
                offenders.append({"adapter": adapter, "apy": apy})
            elif v > self.apy_exploit_threshold_pct:
                offenders.append({"adapter": adapter, "apy": round(v, 4)})

        if offenders:
            msg = (
                f"EXPLOIT PROBE: {len(offenders)} adapter(s) report APY "
                f"> {self.apy_exploit_threshold_pct}% — "
                + ", ".join(
                    f"{o['adapter']}={o['apy']}%" for o in offenders
                )
            )
            log.critical("EB-01 %s", msg)
            return {
                **base,
                "status":    CHECK_FAIL,
                "verdict":   STATUS_HALT,
                "offenders": offenders,
                "message":   msg,
            }

        return {
            **base,
            "status":  CHECK_PASS,
            "verdict": STATUS_CLEAR,
            "message": f"all APYs below {self.apy_exploit_threshold_pct}% threshold",
        }

    def check_eb02_oracle_cascade(
        self,
        apy_map:    dict[str, float],
        static_apy: dict[str, float],
    ) -> dict[str, Any]:
        """EB-02: Halt if ≥ N adapters diverge > threshold bps from static fallback.

        A single-adapter divergence is normal drift.  A cascade of divergences
        indicates a systemic oracle issue or DeFiLlama API anomaly.
        """
        base: dict[str, Any] = {
            "id":        "EB-02",
            "name":      "Oracle Divergence Cascade",
            "threshold_bps":      self.oracle_divergence_cascade_bps,
            "min_adapters":       self.oracle_cascade_min_adapters,
        }

        if not apy_map or not static_apy:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": "apy_map or static_apy empty — skipped"}

        # Shared keys only
        common_keys = set(apy_map.keys()) & set(static_apy.keys())
        if not common_keys:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": "no common adapter keys between apy_map and static_apy — skipped"}

        diverged: list[dict[str, Any]] = []
        threshold_pct = self.oracle_divergence_cascade_bps / 100.0  # bps → pct

        for adapter in common_keys:
            try:
                live_v   = float(apy_map[adapter])
                static_v = float(static_apy[adapter])
            except (TypeError, ValueError):
                continue
            if math.isnan(live_v) or math.isnan(static_v):
                continue
            deviation_bps = abs(live_v - static_v) * 100.0
            if deviation_bps > self.oracle_divergence_cascade_bps:
                diverged.append({
                    "adapter":       adapter,
                    "live_apy":      round(live_v, 4),
                    "static_apy":    round(static_v, 4),
                    "deviation_bps": round(deviation_bps, 1),
                })

        if len(diverged) >= self.oracle_cascade_min_adapters:
            msg = (
                f"ORACLE CASCADE: {len(diverged)} adapter(s) diverge "
                f"> {self.oracle_divergence_cascade_bps:.0f} bps from static — "
                + ", ".join(
                    f"{d['adapter']} ({d['deviation_bps']} bps)" for d in diverged
                )
            )
            log.critical("EB-02 %s", msg)
            return {
                **base,
                "status":   CHECK_FAIL,
                "verdict":  STATUS_HALT,
                "diverged": diverged,
                "message":  msg,
            }

        return {
            **base,
            "status":         CHECK_PASS,
            "verdict":        STATUS_CLEAR,
            "diverged_count": len(diverged),
            "message":        (
                f"{len(diverged)} adapter(s) diverged (need ≥ "
                f"{self.oracle_cascade_min_adapters} for cascade)"
            ),
        }

    def check_eb03_gas_crisis(self, gas_gwei: float) -> dict[str, Any]:
        """EB-03: Pause if base gas price exceeds the crisis threshold.

        At extreme gas prices, any rebalancing would be uneconomical.
        This breaker prevents new allocations but leaves existing positions intact.
        """
        base: dict[str, Any] = {
            "id":        "EB-03",
            "name":      "Gas Crisis",
            "threshold": self.gas_crisis_gwei,
        }

        try:
            gwei = float(gas_gwei)
        except (TypeError, ValueError):
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": f"invalid gas_gwei value: {gas_gwei!r}"}

        if math.isnan(gwei) or math.isinf(gwei):
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": f"non-finite gas_gwei: {gas_gwei!r}"}

        if gwei <= 0:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "value": gwei,
                    "message": "gas_gwei not provided (0) — skipped"}

        if gwei > self.gas_crisis_gwei:
            msg = (
                f"GAS CRISIS: base gas {gwei:.1f} Gwei exceeds "
                f"threshold {self.gas_crisis_gwei:.1f} Gwei"
            )
            log.warning("EB-03 %s", msg)
            return {
                **base,
                "status":  CHECK_FAIL,
                "verdict": STATUS_PAUSE,
                "value":   round(gwei, 2),
                "message": msg,
            }

        return {
            **base,
            "status":  CHECK_PASS,
            "verdict": STATUS_CLEAR,
            "value":   round(gwei, 2),
            "message": f"gas {gwei:.1f} Gwei within threshold",
        }

    def check_eb04_flash_crash(
        self, equity_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """EB-04: Halt if equity drops more than threshold % between the last two bars.

        A 15 %+ intra-cycle drop is either a catastrophic real loss or a
        data/accounting error — both require an immediate halt and manual review.
        """
        base: dict[str, Any] = {
            "id":        "EB-04",
            "name":      "Equity Flash Crash",
            "threshold": self.equity_flash_crash_pct,
        }

        if not equity_history:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": "empty equity_history — skipped"}

        if len(equity_history) < 2:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": "need ≥ 2 equity bars to detect flash crash"}

        prev_eq = _bar_equity(equity_history[-2])
        curr_eq = _bar_equity(equity_history[-1])

        if prev_eq is None or curr_eq is None:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": "missing equity value in one of the last two bars"}

        if prev_eq <= 0:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": "previous equity bar is zero or negative — cannot compute drop"}

        drop_pct = (prev_eq - curr_eq) / prev_eq * 100.0

        if drop_pct > self.equity_flash_crash_pct:
            msg = (
                f"FLASH CRASH: equity dropped {drop_pct:.2f}% "
                f"({prev_eq:,.2f} → {curr_eq:,.2f}), "
                f"threshold {self.equity_flash_crash_pct:.1f}%"
            )
            log.critical("EB-04 %s", msg)
            return {
                **base,
                "status":    CHECK_FAIL,
                "verdict":   STATUS_HALT,
                "prev_eq":   round(prev_eq, 4),
                "curr_eq":   round(curr_eq, 4),
                "drop_pct":  round(drop_pct, 4),
                "message":   msg,
            }

        return {
            **base,
            "status":   CHECK_PASS,
            "verdict":  STATUS_CLEAR,
            "prev_eq":  round(prev_eq, 4),
            "curr_eq":  round(curr_eq, 4),
            "drop_pct": round(max(drop_pct, 0.0), 4),
            "message":  f"equity drop {max(drop_pct, 0):.2f}% within threshold",
        }

    def check_eb05_data_corruption(
        self, equity_history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """EB-05: Halt if equity_history contains corrupted data.

        Checks three corruption types:
        (a) NaN or Infinity equity values
        (b) Negative equity values
        (c) Non-monotonic timestamps (timestamps that go backwards)
        """
        base: dict[str, Any] = {
            "id":   "EB-05",
            "name": "Data Corruption",
        }

        if not equity_history:
            return {**base, "status": CHECK_SKIP, "verdict": STATUS_CLEAR,
                    "message": "empty equity_history — skipped"}

        corruption_events: list[str] = []

        prev_ts: str | None = None

        for i, bar in enumerate(equity_history):
            eq = _bar_equity(bar)

            if eq is not None:
                if math.isnan(eq) or math.isinf(eq):
                    corruption_events.append(
                        f"bar[{i}]: non-finite equity value {eq!r}"
                    )
                elif eq < 0:
                    corruption_events.append(
                        f"bar[{i}]: negative equity {eq:.4f}"
                    )

            # Timestamp monotonicity
            ts = bar.get("timestamp") or bar.get("date") or bar.get("ts")
            if ts is not None and prev_ts is not None:
                try:
                    if str(ts) < str(prev_ts):
                        corruption_events.append(
                            f"bar[{i}]: timestamp {ts!r} < previous {prev_ts!r} (non-monotonic)"
                        )
                except TypeError:
                    pass  # incomparable types — skip timestamp check
            if ts is not None:
                prev_ts = ts

        if corruption_events:
            msg = (
                f"DATA CORRUPTION: {len(corruption_events)} issue(s) found — "
                + "; ".join(corruption_events[:3])
                + (" …" if len(corruption_events) > 3 else "")
            )
            log.critical("EB-05 %s", msg)
            return {
                **base,
                "status":           CHECK_FAIL,
                "verdict":          STATUS_HALT,
                "corruption_count": len(corruption_events),
                "first_issues":     corruption_events[:5],
                "message":          msg,
            }

        return {
            **base,
            "status":  CHECK_PASS,
            "verdict": STATUS_CLEAR,
            "message": f"no data corruption detected in {len(equity_history)} bars",
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_result(
        self,
        result:   dict[str, Any],
        data_dir: str | Path = "data",
    ) -> None:
        """Atomically write ``emergency_status.json`` to *data_dir*.

        Uses mkstemp + os.replace for crash-safe atomic update.
        Never raises: I/O errors are caught and logged as WARNING.
        """
        try:
            data_dir = Path(data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            target = data_dir / OUTPUT_FILENAME
            payload = json.dumps(result, indent=2, ensure_ascii=False)
            fd, tmp_path = tempfile.mkstemp(
                dir=data_dir, prefix=".emergency_status_", suffix=".tmp"
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
            log.warning("EmergencyBreakers.save_result failed: %s", exc)


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
                f = float(val)
                return f
            except (TypeError, ValueError):
                pass
    return None


# ── CLI (advisory / diagnostic) ───────────────────────────────────────────────

def _main(argv: list[str] | None = None) -> None:  # pragma: no cover
    """Minimal CLI for manual diagnostics."""
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="SPA Emergency Circuit Breakers (EB-01..EB-05)",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        metavar="DIR",
        help="data directory (default: data/)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="write result to data/emergency_status.json",
    )
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    # Load equity history from disk (advisory)
    eq_path = data_dir / "equity_curve_daily.json"
    equity_history: list[dict[str, Any]] = []
    if eq_path.exists():
        try:
            doc = json.loads(eq_path.read_text(encoding="utf-8"))
            if isinstance(doc, list):
                equity_history = doc
            elif isinstance(doc, dict):
                equity_history = doc.get("daily") or doc.get("equity") or []
        except Exception as exc:
            log.warning("Could not read equity_curve_daily.json: %s", exc)

    checker = EmergencyBreakers()
    result = checker.check_all(
        apy_map={},
        equity_history=equity_history,
    )

    status = result["status"]
    print(f"\n{'='*60}")
    print(f"  SPA Emergency Breakers — status: {status}")
    print(f"{'='*60}")
    for code, chk in result["checks"].items():
        eb_status = chk.get("status", "?")
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}.get(eb_status, "?")
        print(f"  {icon} {chk.get('id', code.upper()):<6}  {chk['name']:<30s}  "
              f"{eb_status:<5s}  {chk.get('message','')}")
    if result["triggered"]:
        print(f"\n  🔴 TRIGGERED: {', '.join(result['triggered'])}")
    print()

    if args.run:
        checker.save_result(result, data_dir)
        print(f"  ✔ written → {data_dir / OUTPUT_FILENAME}")

    sys.exit(2 if status == STATUS_HALT else (1 if status == STATUS_PAUSE else 0))


if __name__ == "__main__":  # pragma: no cover
    _main()
