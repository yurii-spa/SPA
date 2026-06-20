#!/usr/bin/env python3
"""ADR-031: Rebalancing trigger evaluation.

Checks RT-01..RT-04 conditions defined in ADR-031-rebalancing-policy.md.

Trigger rules
=============
RT-01  Drift Trigger  — any adapter drifts >5% from target weight.
RT-02  APY Opportunity — regime change AND APY gain > 50 bps.
RT-03  Risk Gate      — DailyLimitsChecker DL-03 fires (concentration >40%).
RT-04  Calendar       — 7 days elapsed AND any adapter drifted >2%.

All weights are expected as fractions in [0, 1].
Drift is computed in percentage-point units:
    drift_pp = abs(current_weight - target_weight) * 100

Pure stdlib.  Advisory / read-only — never touches risk, execution, or
allocator code.  Atomic writes only (tmp + os.replace) when persisting state.

CLI::

    python3 -m spa_core.paper_trading.rebalance_trigger --check
    python3 -m spa_core.paper_trading.rebalance_trigger --run --data-dir data
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default config values — overridden by load_config()
# ---------------------------------------------------------------------------

_DEFAULT_DRIFT_TRIGGER_PCT: float = 5.0         # RT-01 threshold (pp)
_DEFAULT_CALENDAR_TRIGGER_DAYS: int = 7         # RT-04 day window
_DEFAULT_CALENDAR_MIN_DRIFT_PCT: float = 2.0    # RT-04 minimum drift (pp)
_DEFAULT_APY_OPPORTUNITY_BPS: float = 50.0      # RT-02 threshold (bps)
_DEFAULT_APY_SPREAD_TRIGGER_PCT: float = 1.5    # RT-05 threshold (% APY)
                                                # (MP-1577 / Improvement 2)


class RebalanceTrigger:
    """Evaluates ADR-031 rebalancing trigger conditions.

    Weights passed to all check methods must be fractions in [0, 1].
    Drift is always computed in percentage-point units so thresholds
    (5 pp, 2 pp) map directly to their ADR-031 definitions.

    Parameters
    ----------
    drift_trigger_pct : float
        RT-01 threshold in percentage points (default 5.0).
    calendar_trigger_days : int
        RT-04 calendar window in days (default 7).
    calendar_min_drift_pct : float
        RT-04 minimum drift in percentage points (default 2.0).
    apy_opportunity_bps : float
        RT-02 APY gain threshold in basis points (default 50.0).
    """

    def __init__(
        self,
        drift_trigger_pct: float = _DEFAULT_DRIFT_TRIGGER_PCT,
        calendar_trigger_days: int = _DEFAULT_CALENDAR_TRIGGER_DAYS,
        calendar_min_drift_pct: float = _DEFAULT_CALENDAR_MIN_DRIFT_PCT,
        apy_opportunity_bps: float = _DEFAULT_APY_OPPORTUNITY_BPS,
        apy_spread_trigger_pct: float = _DEFAULT_APY_SPREAD_TRIGGER_PCT,
    ) -> None:
        self.drift_trigger_pct: float = float(drift_trigger_pct)
        self.calendar_trigger_days: int = int(calendar_trigger_days)
        self.calendar_min_drift_pct: float = float(calendar_min_drift_pct)
        self.apy_opportunity_bps: float = float(apy_opportunity_bps)
        self.apy_spread_trigger_pct: float = float(apy_spread_trigger_pct)

    # ------------------------------------------------------------------
    # RT-01: Drift Trigger
    # ------------------------------------------------------------------

    def check_rt01_drift(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
    ) -> dict:
        """RT-01: Any adapter drifts >5% from target.

        Parameters
        ----------
        current_weights :
            ``{adapter_id: weight}`` fractions, e.g. ``{"aave_v3": 0.36}``.
        target_weights :
            ``{adapter_id: weight}`` fractions, e.g. ``{"aave_v3": 0.30}``.

        Returns
        -------
        dict
            ``{triggered, max_drift_pct, max_drift_adapter, threshold}``
        """
        max_drift: float = 0.0
        max_drift_adapter: Optional[str] = None

        all_keys = set(current_weights) | set(target_weights)
        for adapter in all_keys:
            cur = float(current_weights.get(adapter, 0.0))
            tgt = float(target_weights.get(adapter, 0.0))
            drift_pp = abs(cur - tgt) * 100.0
            if drift_pp > max_drift:
                max_drift = drift_pp
                max_drift_adapter = adapter

        triggered = max_drift > self.drift_trigger_pct

        return {
            "triggered": triggered,
            "max_drift_pct": round(max_drift, 6),
            "max_drift_adapter": max_drift_adapter,
            "threshold": self.drift_trigger_pct,
        }

    # ------------------------------------------------------------------
    # RT-02: APY Opportunity
    # ------------------------------------------------------------------

    def check_rt02_apy_opportunity(
        self,
        current_regime: Optional[str],
        new_regime: Optional[str],
        apy_gain_bps: float,
    ) -> dict:
        """RT-02: Regime change AND APY gain > 50 bps.

        A "regime change" is defined as ``new_regime != current_regime``
        AND both values are non-empty strings (i.e. the regime is known).
        If either value is ``None`` or empty, no regime change is inferred.

        Parameters
        ----------
        current_regime : str | None
            Current MarketRegimeDetector regime label.
        new_regime : str | None
            Newly detected regime label.
        apy_gain_bps : float
            Potential APY gain from rebalancing, in basis points.

        Returns
        -------
        dict
            ``{triggered, regime_changed, apy_gain_bps, threshold_bps}``
        """
        regime_changed = bool(
            current_regime
            and new_regime
            and current_regime != new_regime
        )
        gain_above_threshold = float(apy_gain_bps) > self.apy_opportunity_bps
        triggered = regime_changed and gain_above_threshold

        return {
            "triggered": triggered,
            "regime_changed": regime_changed,
            "apy_gain_bps": float(apy_gain_bps),
            "threshold_bps": self.apy_opportunity_bps,
        }

    # ------------------------------------------------------------------
    # RT-03: Risk Gate
    # ------------------------------------------------------------------

    def check_rt03_risk_gate(
        self,
        daily_limits_result: Optional[dict],
    ) -> dict:
        """RT-03: DL-03 concentration warning fired → immediate rebalance.

        Inspects ``daily_limits_result`` for evidence that DL-03 fired.
        Supported dict layouts:

        * ``{"dl03_fired": True}``  (direct flag)
        * ``{"checks": {"DL-03": {"triggered": True}}}``  (nested checks map)
        * ``{"checks": {"dl_03": {"triggered": True}}}``  (snake_case variant)

        Parameters
        ----------
        daily_limits_result :
            Output from DailyLimitsChecker, or ``None`` / ``{}`` when not run.

        Returns
        -------
        dict
            ``{triggered, dl03_fired}``
        """
        if not daily_limits_result:
            return {"triggered": False, "dl03_fired": False}

        # --- direct flag ---
        dl03 = bool(daily_limits_result.get("dl03_fired", False))

        # --- nested under "checks" key ---
        if not dl03:
            checks = daily_limits_result.get("checks")
            if isinstance(checks, dict):
                for key in ("DL-03", "dl_03", "DL03"):
                    entry = checks.get(key)
                    if isinstance(entry, dict) and entry.get("triggered"):
                        dl03 = True
                        break

        return {"triggered": dl03, "dl03_fired": dl03}

    # ------------------------------------------------------------------
    # RT-04: Calendar
    # ------------------------------------------------------------------

    def check_rt04_calendar(
        self,
        last_rebalance_date: Optional[str],
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
    ) -> dict:
        """RT-04: 7 days elapsed AND any adapter drifted >2%.

        Parameters
        ----------
        last_rebalance_date :
            ``"YYYY-MM-DD"`` string of the last rebalance, or ``None`` when
            the portfolio has never been rebalanced.  ``None`` is treated as
            "elapsed days = infinity" — triggered whenever drift > min threshold.
        current_weights :
            ``{adapter_id: weight}`` fractions.
        target_weights :
            ``{adapter_id: weight}`` fractions.

        Returns
        -------
        dict
            ``{triggered, days_since, max_drift_pct, threshold_days}``
            ``days_since`` is ``None`` when the portfolio was never rebalanced.
        """
        # --- compute max drift ---
        max_drift: float = 0.0
        all_keys = set(current_weights) | set(target_weights)
        for adapter in all_keys:
            cur = float(current_weights.get(adapter, 0.0))
            tgt = float(target_weights.get(adapter, 0.0))
            drift_pp = abs(cur - tgt) * 100.0
            if drift_pp > max_drift:
                max_drift = drift_pp

        drift_qualifies = max_drift > self.calendar_min_drift_pct

        # --- days since last rebalance ---
        if last_rebalance_date is None:
            days_since: Optional[int] = None
            enough_time = True          # Never rebalanced → treat as ∞ days
        else:
            try:
                last_date = date.fromisoformat(last_rebalance_date)
                today = datetime.now(timezone.utc).date()
                days_since = (today - last_date).days
            except (ValueError, TypeError):
                logger.warning(
                    "rebalance_trigger: invalid last_rebalance_date %r, "
                    "treating as never rebalanced",
                    last_rebalance_date,
                )
                days_since = None
                enough_time = True
            else:
                enough_time = days_since >= self.calendar_trigger_days

        triggered = enough_time and drift_qualifies

        return {
            "triggered": triggered,
            "days_since": days_since,
            "max_drift_pct": round(max_drift, 6),
            "threshold_days": self.calendar_trigger_days,
        }

    # ------------------------------------------------------------------
    # RT-05: APY Spread (MP-1577 / Improvement 2)
    # ------------------------------------------------------------------

    def check_rt05_apy_spread(
        self,
        current_apy_pct: Optional[float],
        available_apys,
    ) -> dict:
        """RT-05: best-available APY beats the current portfolio APY by >1.5%.

        Unlike RT-02 (which needs a *regime change* plus a 50 bps gain), RT-05
        fires purely on the opportunity spread: if a whitelisted pool offers a
        materially higher yield than we are currently earning, a rebalance is
        worth attempting regardless of dollar drift.

        Parameters
        ----------
        current_apy_pct :
            Current blended portfolio APY in percent (e.g. ``4.8`` for 4.8%).
            ``None`` is treated as 0.0.
        available_apys :
            Either a list of APYs (percent) or a ``{protocol: apy_pct}`` map of
            the best available whitelisted yields.

        Returns
        -------
        dict
            ``{triggered, current_apy_pct, best_apy_pct, best_protocol,
               spread_pct, threshold_pct}``
        """
        try:
            cur = float(current_apy_pct) if current_apy_pct is not None else 0.0
        except (TypeError, ValueError):
            cur = 0.0

        best = cur
        best_protocol: Optional[str] = None
        if isinstance(available_apys, dict):
            for proto, apy in available_apys.items():
                try:
                    val = float(apy)
                except (TypeError, ValueError):
                    continue
                if val > best:
                    best = val
                    best_protocol = str(proto)
        elif isinstance(available_apys, (list, tuple)):
            for apy in available_apys:
                try:
                    val = float(apy)
                except (TypeError, ValueError):
                    continue
                if val > best:
                    best = val

        spread = best - cur
        if spread < 0:
            spread = 0.0
        triggered = spread > self.apy_spread_trigger_pct

        return {
            "triggered": triggered,
            "current_apy_pct": round(cur, 6),
            "best_apy_pct": round(best, 6),
            "best_protocol": best_protocol,
            "spread_pct": round(spread, 6),
            "threshold_pct": self.apy_spread_trigger_pct,
        }

    # ------------------------------------------------------------------
    # check_all — aggregate
    # ------------------------------------------------------------------

    def check_all(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        equity_history: Optional[List[dict]] = None,   # reserved, not used yet
        current_regime: Optional[str] = None,
        new_regime: Optional[str] = None,
        apy_gain_bps: float = 0.0,
        daily_limits_result: Optional[dict] = None,
        last_rebalance_date: Optional[str] = None,
        current_apy_pct: Optional[float] = None,
        available_apys=None,
    ) -> dict:
        """Run all 4 trigger checks and aggregate the result.

        Parameters
        ----------
        current_weights :
            Current portfolio allocation fractions.
        target_weights :
            Target portfolio allocation fractions.
        equity_history :
            Reserved for future use (e.g. drawdown guard). Ignored today.
        current_regime :
            Current market regime label (RT-02).
        new_regime :
            New market regime label (RT-02).
        apy_gain_bps :
            Potential APY gain from rebalancing in basis points (RT-02).
        daily_limits_result :
            DailyLimitsChecker output dict (RT-03).
        last_rebalance_date :
            ``"YYYY-MM-DD"`` of last rebalance, or ``None`` (RT-04).

        Returns
        -------
        dict::

            {
              "should_rebalance": bool,
              "triggered": ["RT-01", ...],   # list of fired RT codes
              "checks": {
                "rt01": {...},
                "rt02": {...},
                "rt03": {...},
                "rt04": {...},
              },
              "checked_at": "<ISO timestamp>"
            }
        """
        rt01 = self.check_rt01_drift(current_weights, target_weights)
        rt02 = self.check_rt02_apy_opportunity(current_regime, new_regime, apy_gain_bps)
        rt03 = self.check_rt03_risk_gate(daily_limits_result)
        rt04 = self.check_rt04_calendar(last_rebalance_date, current_weights, target_weights)
        rt05 = self.check_rt05_apy_spread(current_apy_pct, available_apys)

        fired: List[str] = []
        if rt01["triggered"]:
            fired.append("RT-01")
        if rt02["triggered"]:
            fired.append("RT-02")
        if rt03["triggered"]:
            fired.append("RT-03")
        if rt04["triggered"]:
            fired.append("RT-04")
        if rt05["triggered"]:
            fired.append("RT-05")

        return {
            "should_rebalance": bool(fired),
            "triggered": fired,
            "checks": {
                "rt01": rt01,
                "rt02": rt02,
                "rt03": rt03,
                "rt04": rt04,
                "rt05": rt05,
            },
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Configuration loader
    # ------------------------------------------------------------------

    def load_config(
        self,
        config_path: str = "data/rebalancing_config.json",
    ) -> None:
        """Load ``rebalancing_config.json`` and update instance thresholds.

        Missing or extra keys are silently ignored.  On any read/parse error
        the existing defaults are kept and a warning is logged.

        Parameters
        ----------
        config_path :
            Path to the JSON config file (default ``data/rebalancing_config.json``).
        """
        try:
            raw = Path(config_path).read_text(encoding="utf-8")
            cfg: dict = json.loads(raw)
        except FileNotFoundError:
            logger.warning(
                "rebalance_trigger: config not found at %r, keeping defaults",
                config_path,
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rebalance_trigger: could not load config %r: %s — keeping defaults",
                config_path,
                exc,
            )
            return

        if not isinstance(cfg, dict):
            logger.warning(
                "rebalance_trigger: config is not a JSON object at %r, keeping defaults",
                config_path,
            )
            return

        if "drift_trigger_pct" in cfg:
            self.drift_trigger_pct = float(cfg["drift_trigger_pct"])
        if "calendar_trigger_days" in cfg:
            self.calendar_trigger_days = int(cfg["calendar_trigger_days"])
        if "calendar_min_drift_pct" in cfg:
            self.calendar_min_drift_pct = float(cfg["calendar_min_drift_pct"])
        if "apy_opportunity_bps" in cfg:
            self.apy_opportunity_bps = float(cfg["apy_opportunity_bps"])
        if "apy_spread_trigger_pct" in cfg:
            self.apy_spread_trigger_pct = float(cfg["apy_spread_trigger_pct"])

        logger.info(
            "rebalance_trigger: config loaded from %r "
            "(drift=%.1f%% calendar=%dd min_drift=%.1f%% apy=%.1fbps)",
            config_path,
            self.drift_trigger_pct,
            self.calendar_trigger_days,
            self.calendar_min_drift_pct,
            self.apy_opportunity_bps,
        )


# ---------------------------------------------------------------------------
# Smart helpers (MP-1577 / Improvement 2) — USD→weight + state-driven eval
# ---------------------------------------------------------------------------

def usd_to_weights(positions: Dict[str, float]) -> Dict[str, float]:
    """Normalise a ``{protocol: usd}`` map into ``{protocol: fraction}`` in [0,1].

    Returns an empty dict for an empty / non-positive map. Non-numeric values
    are skipped. Used so callers can feed dollar positions straight into the
    fraction-based RT-01/RT-04 checks.
    """
    if not isinstance(positions, dict):
        return {}
    vals: Dict[str, float] = {}
    for k, v in positions.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            vals[k] = fv
    total = sum(vals.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in vals.items()}


def smart_rebalance_check(
    *,
    current_positions: Dict[str, float],
    target_positions: Dict[str, float],
    current_apy_pct: Optional[float] = None,
    available_apys=None,
    last_rebalance_date: Optional[str] = None,
    trigger: Optional["RebalanceTrigger"] = None,
) -> dict:
    """High-level advisory check combining drift (RT-01/04) and APY spread (RT-05).

    Accepts dollar positions directly (converted to weights internally) so the
    cycle can call it with ``current_positions`` / ``target_positions`` from
    ``paper_trading_status`` and the allocator target. Never raises.
    """
    trig = trigger or RebalanceTrigger()
    cur_w = usd_to_weights(current_positions or {})
    tgt_w = usd_to_weights(target_positions or {})
    return trig.check_all(
        current_weights=cur_w,
        target_weights=tgt_w,
        last_rebalance_date=last_rebalance_date,
        current_apy_pct=current_apy_pct,
        available_apys=available_apys,
    )


def _extract_available_apys(snapshot) -> Dict[str, float]:
    """Best-effort ``{protocol: apy_pct}`` from a read-only adapter snapshot."""
    out: Dict[str, float] = {}

    def _apy(d: dict):
        return d.get("apy", d.get("apy_pct", d.get("net_apy")))

    if isinstance(snapshot, dict):
        protos = snapshot.get("protocols")
        if isinstance(protos, list):
            for p in protos:
                if isinstance(p, dict):
                    name = p.get("name") or p.get("protocol") or p.get("id")
                    if name is not None:
                        try:
                            out[str(name)] = float(_apy(p) or 0.0)
                        except (TypeError, ValueError):
                            pass
        else:
            for name, p in snapshot.items():
                try:
                    out[str(name)] = float(_apy(p) if isinstance(p, dict) else p)
                except (TypeError, ValueError):
                    pass
    elif isinstance(snapshot, list):
        for p in snapshot:
            if isinstance(p, dict):
                name = p.get("name") or p.get("protocol") or p.get("id")
                if name is not None:
                    try:
                        out[str(name)] = float(_apy(p) or 0.0)
                    except (TypeError, ValueError):
                        pass
    return out


def evaluate_from_state(data_dir: str = "data") -> dict:
    """Read live snapshots and run the smart check. Fail-safe (exit-0 friendly)."""
    base = Path(data_dir)
    status: dict = {}
    adapters = {}
    target: dict = {}
    try:
        status = json.loads((base / "paper_trading_status.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001
        status = {}
    try:
        adapters = json.loads((base / "adapter_snapshot.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001
        adapters = {}
    try:
        target = json.loads((base / "target_allocation.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001
        target = {}

    current_positions = status.get("current_positions", {}) if isinstance(status, dict) else {}
    current_apy = status.get("apy_today_pct") if isinstance(status, dict) else None
    target_positions = {}
    if isinstance(target, dict):
        target_positions = (
            target.get("target_positions")
            or target.get("positions")
            or target.get("allocation")
            or {}
        )
    if not target_positions:
        target_positions = current_positions

    return smart_rebalance_check(
        current_positions=current_positions,
        target_positions=target_positions,
        current_apy_pct=current_apy,
        available_apys=_extract_available_apys(adapters),
    )


# ---------------------------------------------------------------------------
# CLI entry-point  (advisory / read-only, exit 0 always)
# ---------------------------------------------------------------------------

def _build_report(trigger: RebalanceTrigger, data_dir: str) -> dict:
    """Build a sample report by reading current state from data files."""
    from pathlib import Path as _Path

    positions_path = _Path(data_dir) / "current_positions.json"
    golive_path = _Path(data_dir) / "golive_status.json"

    current_weights: Dict[str, float] = {}
    target_weights: Dict[str, float] = {}

    try:
        pos_raw = positions_path.read_text(encoding="utf-8")
        pos_data = json.loads(pos_raw)
        if isinstance(pos_data, dict):
            current_weights = {
                k: float(v) for k, v in pos_data.items()
                if isinstance(v, (int, float)) and str(k) != "__meta__"
            }
    except Exception as exc:  # noqa: BLE001
        logger.debug("rebalance_trigger CLI: could not read positions: %s", exc)

    result = trigger.check_all(
        current_weights=current_weights,
        target_weights=target_weights,
    )
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="RebalanceTrigger — ADR-031 trigger evaluation (advisory)"
    )
    parser.add_argument("--check", action="store_true", help="Evaluate and print (default)")
    parser.add_argument("--run", action="store_true", help="Alias for --check")
    parser.add_argument("--data-dir", default="data", help="Path to data directory")
    parser.add_argument("--config", default="data/rebalancing_config.json",
                        help="Path to rebalancing_config.json")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    trigger = RebalanceTrigger()
    trigger.load_config(args.config)

    try:
        report = _build_report(trigger, args.data_dir)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}), file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
