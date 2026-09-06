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

#: Статусы записи DL-03, означающие «предел нарушен» (ADR-240). `DailyLimitsChecker`
#: пишет `FAIL` для DL-03/04/05 и агрегирует их в `warn_reasons`; ключа `triggered`
#: у его записей нет вовсе.
_DL_FIRED_STATUSES = frozenset({"FAIL", "WARN", "HALT"})


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
            # Пустая цель ДВУСМЫСЛЕННА: это может быть «цель — весь кэш» и может
            # быть «цели никто не дал». Различить их отсюда нечем, поэтому
            # пометку ставит ЧИТАТЕЛЬ (`check_all(input_gaps=…)`, ADR-240).
            "measured": True,
            "unmeasured_reason": None,
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

        # ADR-240: ОБА конца пары пусты ⇒ смену режима не спрашивали вовсе.
        # «Режим не менялся» и «режим никто не называл» — разные ответы, и
        # первый из них живой путь произносил четыре месяца, ни разу не
        # получив ни одного лейбла.
        measured = bool(current_regime) or bool(new_regime)

        return {
            "triggered": triggered,
            "regime_changed": regime_changed,
            "apy_gain_bps": float(apy_gain_bps),
            "threshold_bps": self.apy_opportunity_bps,
            "measured": measured,
            "unmeasured_reason": None if measured else (
                "ни текущий, ни новый режим не переданы — смену режима НЕ "
                "СПРАШИВАЛИ; это не «режим не менялся»"
            ),
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
        * ``{"checks": [{"id": "DL-03", "status": "FAIL"}]}``  — **the shape
          `DailyLimitsChecker` actually writes** (ADR-240)
        * ``{"warn_reasons": ["DL-03 Adapter Concentration: …"]}`` — same file,
          aggregated line

        Замер 2026-09-06, цикл #500: три первых макета — единственное, что
        читалось, и НИ ОДИН из них не есть то, что производит
        ``DailyLimitsChecker.save_result``. Тот пишет ``checks`` СПИСКОМ
        записей ``{"id": "DL-03", "status": "FAIL"}``, без ключа ``triggered``
        вовсе. Поэтому два артефакта ОДНОГО прогона расходились:
        ``risk_limits_check.json`` (06:00:27) — ``DL-03 … compound_v3 at 42.1 %
        exceeds limit 40.0 %``, а ``rebalance_trigger.json`` (06:01:32) —
        ``rt03.dl03_fired: false``.

        Отсутствие входа — ТРЕТИЙ ИСХОД, а не «не сработал». ``None`` и пустой
        словарь означают «DailyLimitsChecker не спрашивали», и молчаливое
        ``triggered: False`` читается как «спросили, всё в порядке».

        Parameters
        ----------
        daily_limits_result :
            Output from DailyLimitsChecker, or ``None`` / ``{}`` when not run.

        Returns
        -------
        dict
            ``{triggered, dl03_fired, measured, unmeasured_reason}``
        """
        if not daily_limits_result or not isinstance(daily_limits_result, dict):
            return {
                "triggered": False,
                "dl03_fired": False,
                "measured": False,
                "unmeasured_reason": (
                    "вердикт DailyLimitsChecker не передан — DL-03 НЕ СПРАШИВАЛИ; "
                    "это не «не сработал»"
                ),
            }

        # --- direct flag ---
        dl03 = bool(daily_limits_result.get("dl03_fired", False))

        checks = daily_limits_result.get("checks")

        # --- nested under "checks" as a MAP ---
        if not dl03 and isinstance(checks, dict):
            for key in ("DL-03", "dl_03", "DL03"):
                entry = checks.get(key)
                if isinstance(entry, dict) and entry.get("triggered"):
                    dl03 = True
                    break

        # --- "checks" as a LIST of records — the shape actually written ---
        if not dl03 and isinstance(checks, list):
            for entry in checks:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("id") or "").upper().replace("_", "-") != "DL-03":
                    continue
                # `triggered` when present wins; otherwise the recorded status.
                if entry.get("triggered"):
                    dl03 = True
                    break
                if str(entry.get("status") or "").upper() in _DL_FIRED_STATUSES:
                    dl03 = True
                    break

        # --- aggregated reason lines of the same document ---
        if not dl03:
            reasons = daily_limits_result.get("warn_reasons")
            if isinstance(reasons, (list, tuple)):
                for line in reasons:
                    if isinstance(line, str) and line.strip().upper().startswith("DL-03"):
                        dl03 = True
                        break

        return {
            "triggered": dl03,
            "dl03_fired": dl03,
            "measured": True,
            "unmeasured_reason": None,
        }

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
            "measured": True,
            "unmeasured_reason": None,
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

        # ADR-240: пустая вселенная доходностей даёт `best = cur` и разрыв 0.0 —
        # число, неотличимое от «мы посмотрели и ничего лучше нет». Замер 06.09:
        # живой путь читал `data/adapter_snapshot.json`, которого НЕ ПИШЕТ НИКТО,
        # и печатал ровно такой ноль каждым циклом.
        has_universe = bool(available_apys) and isinstance(
            available_apys, (dict, list, tuple))
        measured = has_universe and current_apy_pct is not None

        if not has_universe:
            reason = ("вселенная доступных доходностей пуста — сравнивать не с чем; "
                      "разрыв 0.0 здесь НЕ означает «лучше нет»")
        elif current_apy_pct is None:
            reason = "текущая доходность книги не передана — разрыв меряется не от чего"
        else:
            reason = None

        return {
            "triggered": triggered,
            "current_apy_pct": round(cur, 6),
            "best_apy_pct": round(best, 6),
            "best_protocol": best_protocol,
            "spread_pct": round(spread, 6),
            "threshold_pct": self.apy_spread_trigger_pct,
            "measured": measured,
            "unmeasured_reason": reason,
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
        input_gaps: Optional[Dict[str, str]] = None,
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

        checks = {"rt01": rt01, "rt02": rt02, "rt03": rt03,
                  "rt04": rt04, "rt05": rt05}

        # ADR-240: читатель называет входы, которых у него НЕ БЫЛО. Проверка
        # без входа не «не сработала» — она не состоялась, и сказать это может
        # только тот, кто пытался вход добыть.
        for key, reason in (input_gaps or {}).items():
            entry = checks.get(str(key).lower().replace("-", ""))
            if entry is None or not reason:
                continue
            entry["measured"] = False
            entry["unmeasured_reason"] = str(reason)
            # Проверка, у которой не было входа, НЕ ИМЕЕТ ПРАВА срабатывать:
            # иначе «не измерено» превратилось бы в утверждение.
            entry["triggered"] = False

        fired: List[str] = []
        unmeasured: List[str] = []
        for code, key in (("RT-01", "rt01"), ("RT-02", "rt02"), ("RT-03", "rt03"),
                          ("RT-04", "rt04"), ("RT-05", "rt05")):
            entry = checks[key]
            if entry.get("triggered"):
                fired.append(code)
            if entry.get("measured") is False:
                unmeasured.append(code)

        # ТРИ исхода, а не два. `should_rebalance: false` при непустом
        # `unmeasured` означает «повода не нашли ТАМ, ГДЕ СМОТРЕЛИ», и это не
        # то же самое, что «повода нет». Замер 06.09 (цикл #500): все пять
        # проверок были не измерены, а файл говорил ровно `false`.
        if fired:
            verdict = "REBALANCE"
        elif unmeasured:
            verdict = "UNCHECKED"
        else:
            verdict = "NO_TRIGGER"

        return {
            "should_rebalance": bool(fired),
            "triggered": fired,
            "unmeasured": unmeasured,
            "verdict": verdict,
            "checks": checks,
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
    daily_limits_result: Optional[dict] = None,
    input_gaps: Optional[Dict[str, str]] = None,
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
        daily_limits_result=daily_limits_result,
        input_gaps=input_gaps,
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


def _read_json(base: Path, name: str):
    """Прочитать артефакт или вернуть ``None``. Отсутствие — это ответ, а не ноль."""
    try:
        return json.loads((base / name).read_text("utf-8"))
    except Exception:  # noqa: BLE001 — читатель не смеет валить цикл
        return None


def _observed_apys(adapter_status) -> Dict[str, float]:
    """``{ключ: доходность}`` ТОЛЬКО по наблюдениям этого прогона (ADR-240).

    Литеральный ``fallback_apy`` сюда не попадает намеренно: RT-05 сравнивает
    книгу с тем, что МОЖНО купить по наблюдённому числу. Подставить литерал
    значило бы предложить перекладку по ставке, которую никто не видел, —
    ровно тот дефект, который считает `capital_evidence_coverage` (ADR-226).
    """
    out: Dict[str, float] = {}
    if not isinstance(adapter_status, dict):
        return out
    adapters = adapter_status.get("adapters")
    if not isinstance(adapters, dict):
        return out
    for key, entry in adapters.items():
        if not isinstance(entry, dict) or not entry.get("live_apy_fresh"):
            continue
        val = entry.get("live_apy")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        out[str(key)] = float(val)
    return out


def _target_from_rationale(rationale, current_positions: Dict[str, float]):
    """Цель аллокатора = текущая книга + ноги теневого решения (ADR-240).

    ``allocation_rationale.json`` пишет ТОТ ЖЕ цикл и в нём лежит оптимум,
    посчитанный аллокатором (`decision_shadow.legs` — поимённые дельты). До
    ADR-240 читатель искал `data/target_allocation.json`, которого не пишет
    НИКТО, тихо подставлял текущую книгу вместо цели и печатал дрейф 0.0.
    """
    if not isinstance(rationale, dict):
        return None
    shadow = rationale.get("decision_shadow")
    if not isinstance(shadow, dict):
        return None
    legs = shadow.get("legs")
    if not isinstance(legs, list) or not legs:
        return None
    target = {str(k): float(v) for k, v in (current_positions or {}).items()
              if isinstance(v, (int, float)) and not isinstance(v, bool)}
    seen = False
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        proto = leg.get("protocol")
        delta = leg.get("delta_usd")
        if proto is None or isinstance(delta, bool) or not isinstance(delta, (int, float)):
            continue
        target[str(proto)] = target.get(str(proto), 0.0) + float(delta)
        seen = True
    return target if seen else None


def _last_rebalance_date(trades) -> Optional[str]:
    """``YYYY-MM-DD`` последней перекладки из журнала сделок, иначе ``None``."""
    rows = trades if isinstance(trades, list) else (
        trades.get("trades") if isinstance(trades, dict) else None)
    if not isinstance(rows, list):
        return None
    latest: Optional[datetime] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("ts") or row.get("timestamp")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            when = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if latest is None or when > latest:
            latest = when
    return latest.date().isoformat() if latest else None


def evaluate_from_state(data_dir: str = "data") -> dict:
    """Прочитать живые артефакты и прогнать проверки. Fail-safe (exit-0 friendly).

    ADR-240. Читатель называет КАЖДЫЙ вход и КАЖДЫЙ пробел. До этого он читал
    два файла, которых не пишет ни один производитель
    (``adapter_snapshot.json``, ``target_allocation.json``), не передавал
    вердикт дневных лимитов, режим и дату последней перекладки — и все пять
    проверок отвечали ``triggered: false`` ИЗ ПУСТОТЫ. Прежние имена файлов
    читаются по-прежнему и имеют приоритет: они старше и на них стоят тесты.
    """
    base = Path(data_dir)
    status = _read_json(base, "paper_trading_status.json") or {}
    if not isinstance(status, dict):
        status = {}

    current_positions = status.get("current_positions") or {}
    if not isinstance(current_positions, dict):
        current_positions = {}
    current_apy = status.get("apy_today_pct")

    inputs: Dict[str, str] = {}
    gaps: Dict[str, str] = {}

    # ── цель аллокатора ──────────────────────────────────────────────────
    target_positions: Dict[str, float] = {}
    legacy_target = _read_json(base, "target_allocation.json")
    if isinstance(legacy_target, dict):
        candidate = (legacy_target.get("target_positions")
                     or legacy_target.get("positions")
                     or legacy_target.get("allocation"))
        if isinstance(candidate, dict) and candidate:
            target_positions = candidate
            inputs["target"] = "target_allocation.json"
    if not target_positions:
        rationale = _read_json(base, "allocation_rationale.json")
        from_legs = _target_from_rationale(rationale, current_positions)
        if from_legs:
            target_positions = from_legs
            inputs["target"] = "allocation_rationale.json:decision_shadow.legs"
    if not target_positions:
        target_positions = current_positions
        gap = ("цель аллокатора не прочитана (нет ни `target_allocation.json`, ни "
               "`decision_shadow.legs` в `allocation_rationale.json`) — за цель "
               "принята текущая книга, поэтому дрейф 0.0 ЗДЕСЬ НИЧЕГО НЕ ЗНАЧИТ")
        gaps["rt01"] = gap
        gaps["rt04"] = gap

    # ── вселенная доходностей ────────────────────────────────────────────
    available_apys = _extract_available_apys(
        _read_json(base, "adapter_snapshot.json") or {})
    if available_apys:
        inputs["apys"] = "adapter_snapshot.json"
    else:
        available_apys = _observed_apys(_read_json(base, "adapter_status.json"))
        if available_apys:
            inputs["apys"] = "adapter_status.json:live_apy(fresh)"

    # ── вердикт дневных лимитов (RT-03) ──────────────────────────────────
    daily_limits = _read_json(base, "risk_limits_check.json")
    if isinstance(daily_limits, dict) and daily_limits:
        inputs["daily_limits"] = "risk_limits_check.json"
    else:
        daily_limits = None

    # ── дата последней перекладки (RT-04) ────────────────────────────────
    last_rebalance = _last_rebalance_date(_read_json(base, "trades.json"))
    if last_rebalance:
        inputs["last_rebalance"] = "trades.json"

    # ── режим рынка (RT-02) ──────────────────────────────────────────────
    # `market_regime.json` несёт ОДНУ метку. Смена режима — это ДВЕ метки, и
    # второй в системе нет: истории режимов никто не пишет. Поэтому здесь
    # честный пробел, а не выдуманное «режим не менялся».
    regime_doc = _read_json(base, "market_regime.json")
    regime_now = regime_doc.get("regime") if isinstance(regime_doc, dict) else None
    if regime_now:
        inputs["regime"] = "market_regime.json (одна метка)"
    gaps["rt02"] = (
        "смена режима требует ДВУХ отметок; `market_regime.json` несёт одну"
        + (f" ({regime_now})" if regime_now else " и её тоже нет")
        + " — истории режимов не пишет никто"
    )

    verdict = smart_rebalance_check(
        current_positions=current_positions,
        target_positions=target_positions,
        current_apy_pct=current_apy,
        available_apys=available_apys,
        last_rebalance_date=last_rebalance,
        daily_limits_result=daily_limits,
        input_gaps=gaps,
    )
    verdict["inputs"] = inputs
    return verdict


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
