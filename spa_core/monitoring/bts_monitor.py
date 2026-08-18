"""
bts_monitor.py — BTS Monitor (Basis Trade System).

Runs every 15 min via LaunchAgent com.spa.bts-monitor.
Reads perp_funding_rates.json + adapter_status.json.
Feeds BasisTradeAnalyzer to produce ranked opportunities.
Writes data/basis_trade_opportunities.json.
Fires Telegram alert on NEW EXCELLENT opportunity (transition from non-EXCELLENT).

Atomic writes: tmp-file + os.replace. stdlib only.
Never raises exceptions outward (fail-safe).

Honest threshold (ADR-070 п.12, owner decision 2026-08-07). Two invented numbers used to
decide what the owner is told:

  * a hardcoded **5% spot baseline** — EXCELLENT is ">=100bps net", so on a copy of live
    data every asset cleared it at once (ETH 262 / BTC 1575 / SOL 987 bps) and the label
    said nothing;
  * a hardcoded **$20,000** of capital, which this sleeve does not have, turned into
    "Annual PnL $3,150" in the owner-facing message.

Now: the spot leg is taken from live adapter APY or the scan REFUSES (no literal
fallback); the alert hurdle is OUR OWN measured portfolio yield from the evidenced track
(`spa_core.monitoring.bts_baseline`), and an opportunity that does not beat it is not
alert-worthy no matter what tier the analyzer assigned; and no dollar figure is published
at all, because no capital is allocated here. The owner's order was explicit: honest
threshold FIRST, arming (`SPA_BTS_ALERTS_ARMED`) only afterwards.

Honesty contract (cycle #78). The funding payload is read through
`spa_core.feeds.funding_schema`, which knows the shape the producer actually writes
(`assets` / `fetched_at`) and still accepts the legacy shape (`rates` / `generated_at`).
Before that, this monitor asked only for the legacy keys, found nothing 96 times a day,
and published `status: "ok", errors: [], 0 opportunities` — a verdict about a file it
had never read. Now `status` is "ok" ONLY when the scan actually happened; otherwise it
is "unchecked" and `unchecked[]` carries the verbatim reason. Thresholds
(STALE_AFTER_S, ALERT_COOLDOWN_S), the alert transport and the ranking are unchanged.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from spa_core.analytics.basis_trade_analyzer import (
    BasisTradeAnalyzer,
    BasisTradeInput,
    BasisTradeResult,
)
from spa_core.feeds.funding_schema import feed_age_seconds, read_rates
from spa_core.monitoring.bts_baseline import OurYieldRead, read_our_yield
from spa_core.utils.atomic import atomic_save, atomic_load

log = logging.getLogger("spa.monitoring.bts_monitor")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

OPP_FILENAME = "basis_trade_opportunities.json"
STATUS_FILENAME = "bts_monitor_status.json"
FUNDING_FILENAME = "perp_funding_rates.json"
ADAPTER_STATUS_FILENAME = "adapter_status.json"
EVIDENCE_FILENAME = "paper_evidence.json"

TRACKED_ASSETS = ("ETH", "BTC", "SOL")

# ── The two invented numbers, kept OFF the scan path (ADR-070 п.12) ───────────
# Neither of these is used to compute anything published any more. They stay defined
# because `tests/test_bts_monitor.py` imports them and pins the LEGACY wrapper
# `_get_spot_yield` — removing the names would rewrite a pre-existing test to go green,
# which invariant #16 forbids. Read them as documentation of what was wrong, not as
# configuration: the scan refuses when the spot leg cannot be measured, and it publishes
# no dollar figure at all.
DEFAULT_SPOT_YIELD = 0.05      # LEGACY literal — never substituted on the scan path
DEFAULT_CAPITAL_USD = 20000.0  # LEGACY literal — this sleeve holds no capital

DEFAULT_EXEC_COST_BPS = 20.0
TOP_N = 5

# The spread is computed against a spot leg with no capital behind it, so the dollar
# question has no honest answer. This is the verbatim reason published in place of one.
NO_CAPITAL_REASON = (
    "no capital is allocated to the BTS sleeve — annual PnL NOT MEASURED "
    "(the previous $-figures were computed off a literal $20,000; ADR-070 п.12)"
)

STALE_AFTER_S = 1800
ALERT_COOLDOWN_S = 3600

# Verdict vocabulary. "ok" is reserved for a scan that actually happened: before #78 it
# was published whenever no exception was raised, including the 96 runs a day in which
# the monitor read nothing at all.
STATUS_OK = "ok"
STATUS_UNCHECKED = "unchecked"
STATUS_ERROR = "error"

# Owner-armed Telegram transport (cycle #78). This monitor's alert path had never fired
# once: it could not read the feed, so it never found an opportunity to alert about.
# Repointing it at the real schema makes it live again — and a read-only smoke on a COPY
# of production data showed the FIRST run would send three "BTS EXCELLENT … Annual PnL
# $N" messages, because EXCELLENT is >=100bps net against a hardcoded 5% spot baseline
# and any non-negative funding clears it. Switching on a dormant owner-facing claim from
# an unvalidated model is not an autonomous call (ORCHESTRATOR_PROTOCOL, "запрещено
# автономно"), so the transport stays disarmed until the owner arms it, while the
# artifacts below are written honestly and completely either way. The suppression is
# recorded verbatim in the status file — it is never silent.
BTS_ALERTS_ARMED_ENV = "SPA_BTS_ALERTS_ARMED"


def _alerts_armed() -> bool:
    return os.environ.get(BTS_ALERTS_ARMED_ENV, "").strip().lower() in {"1", "true", "yes"}


def _verdict(errors: List[str], unchecked: List[str]) -> str:
    """An error outranks an unmeasured check; both outrank "ok"."""
    if errors:
        return STATUS_ERROR
    if unchecked:
        return STATUS_UNCHECKED
    return STATUS_OK


@dataclass
class FundingLoad:
    """Outcome of loading the funding payload.

    `data` is None whenever the payload must not be scanned. `stale` describes the
    FEED (not the number of opportunities). `unchecked` is a verbatim reason something
    could not be measured; `refusal` is a verbatim reason the payload was rejected.
    """

    data: Optional[dict]
    stale: bool
    unchecked: Optional[str] = None
    refusal: Optional[str] = None


@dataclass
class BTSScan:
    """Result of one scan: what was found, whether the FEED was stale, and what was
    not measured (verbatim). An empty `opportunities` list means "measured, nothing
    qualified" only when `unchecked` is empty."""

    opportunities: List["BTSOpportunity"]
    stale_feed: bool
    unchecked: List[str]
    refusal: Optional[str] = None
    # Our own measured yield — the hurdle every owner-facing claim is judged against.
    # None means the scan did not get far enough to look it up.
    our_yield: Optional[OurYieldRead] = None


@dataclass
class BTSOpportunity:
    asset: str
    spot_yield_pct: float
    perp_funding_pct: float
    net_spread_bps: float
    edge_quality: str
    recommended_action: str
    # Optional, and None on the scan path: there is no capital in this sleeve, so a
    # dollar figure would be an invention (ADR-070 п.12). Field order and position are
    # unchanged — pre-existing tests construct this positionally.
    annual_pnl_usd: Optional[float] = None
    gross_spread_bps: float = 0.0
    capital_usd: Optional[float] = None
    # net_spread_bps minus OUR OWN measured yield in bps. None when our yield could not
    # be measured — never 0.0, which would read as "exactly break-even".
    excess_vs_our_yield_bps: Optional[float] = None
    pnl_unchecked: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "spot_yield_pct": round(self.spot_yield_pct, 2),
            "perp_funding_pct": round(self.perp_funding_pct, 2),
            "net_spread_bps": round(self.net_spread_bps, 1),
            "gross_spread_bps": round(self.gross_spread_bps, 1),
            "edge_quality": self.edge_quality,
            "recommended_action": self.recommended_action,
            "annual_pnl_usd": (
                round(self.annual_pnl_usd, 2) if self.annual_pnl_usd is not None else None
            ),
            "capital_usd": (
                round(self.capital_usd, 2) if self.capital_usd is not None else None
            ),
            "excess_vs_our_yield_bps": (
                round(self.excess_vs_our_yield_bps, 1)
                if self.excess_vs_our_yield_bps is not None else None
            ),
            "pnl_unchecked": self.pnl_unchecked,
        }


class BTSMonitor:
    """
    BTS opportunity scanner.

    Reads funding rates + adapter status, runs BasisTradeAnalyzer,
    writes ranked opportunities, fires Telegram on NEW EXCELLENT transitions.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        use_alert_dispatcher: bool = True,
        analyzer: Optional[BasisTradeAnalyzer] = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._opp_path = self._data_dir / OPP_FILENAME
        self._status_path = self._data_dir / STATUS_FILENAME
        self._funding_path = self._data_dir / FUNDING_FILENAME
        self._adapter_status_path = self._data_dir / ADAPTER_STATUS_FILENAME
        self._evidence_path = self._data_dir / EVIDENCE_FILENAME
        self._use_alert_dispatcher = use_alert_dispatcher
        self._analyzer = analyzer or BasisTradeAnalyzer()
        self._dispatcher = None

    def _get_dispatcher(self):
        if not self._use_alert_dispatcher:
            return None
        if self._dispatcher is not None:
            return self._dispatcher
        try:
            from spa_core.alerts.alert_dispatcher import AlertDispatcher
            self._dispatcher = AlertDispatcher(
                suppress_duplicates=True,
                cooldown_seconds=ALERT_COOLDOWN_S,
            )
        except Exception as exc:
            log.debug("AlertDispatcher unavailable: %s", exc)
            self._dispatcher = None
        return self._dispatcher

    def _load_funding_data(self) -> Optional[dict]:
        """Back-compat wrapper: the payload only, verdict discarded."""
        return self._load_funding_verdict().data

    def _load_funding_verdict(self) -> "FundingLoad":
        """Load the funding payload AND say why it is unusable when it is.

        The staleness threshold (STALE_AFTER_S) and the "feed says stale" rule are
        unchanged; what is new is that an age which could not be computed is reported
        as NOT MEASURED instead of silently passing for fresh (the pre-#78 code asked
        for `generated_at`, a key the live feed never writes, so the age check never
        ran once in production).
        """
        try:
            data = atomic_load(str(self._funding_path), default=None)
        except Exception as exc:
            return FundingLoad(None, True, f"funding file unreadable: {exc}")
        if not data:
            return FundingLoad(
                None, True, None, refusal=f"no funding data at {self._funding_path.name}"
            )

        unchecked: Optional[str] = None
        age = feed_age_seconds(data)
        if age.measured and age.age_seconds is not None:
            if age.age_seconds > STALE_AFTER_S:
                log.info(
                    "Funding data stale (age %.0fs > %ds)", age.age_seconds, STALE_AFTER_S
                )
                return FundingLoad(
                    None,
                    True,
                    None,
                    refusal=(
                        f"feed age {age.age_seconds:.0f}s exceeds {STALE_AFTER_S}s "
                        f"(from {age.source_key!r})"
                    ),
                )
        else:
            unchecked = f"feed age NOT MEASURED — {age.unchecked}"
            log.info("Funding age not measured: %s", age.unchecked)

        if data.get("stale", False):
            log.info("Funding data marked stale by feed")
            return FundingLoad(
                None, True, unchecked, refusal="feed marked its own payload stale"
            )
        return FundingLoad(data, False, unchecked)

    def _load_adapter_status(self) -> dict:
        try:
            return atomic_load(str(self._adapter_status_path), default={})
        except Exception:
            return {}

    def _load_our_yield(self, *, now: Optional[datetime] = None) -> OurYieldRead:
        """OUR OWN yield — the hurdle. Refuses verbatim when it cannot be measured.

        ``now`` is an argument so freshness can be tested at a fixed instant instead of
        against the calendar (`.claude/rules/deployment.md`, "время — вход").
        """
        try:
            payload = atomic_load(str(self._evidence_path), default=None)
        except Exception as exc:
            payload = None
            log.debug("evidence unreadable: %s", exc)
        if payload is None:
            return read_our_yield(
                {"days": None, "_": f"missing or unreadable {self._evidence_path.name}"},
                now=now,
            )
        return read_our_yield(payload, now=now)

    def _spot_yield_verdict(self, adapter_status: dict) -> Tuple[Optional[float], Optional[str]]:
        """Best live spot-leg yield, or a verbatim reason there is none.

        Fail-CLOSED: the caller gets ``None`` and refuses. The pre-ADR-070 code returned
        a literal 5% here whenever no adapter answered, and that literal is what made
        every asset "EXCELLENT" — a tier computed against a number nobody measured.
        """
        yield_keys = {
            "aave_v3": "apy",
            "aave_usdc": "apy",
            "compound_v3": "apy",
            "morpho_steakhouse": "apy",
            "morpho_usdc": "apy",
        }
        best: Optional[float] = None
        seen: List[str] = []
        for key, apy_field in yield_keys.items():
            entry = adapter_status.get(key, {}) if isinstance(adapter_status, dict) else {}
            if not isinstance(entry, dict):
                continue
            seen.append(key)
            apy = entry.get(apy_field)
            if apy is None or isinstance(apy, bool):
                continue
            try:
                apy_val = float(apy)
            except (ValueError, TypeError):
                continue
            if apy_val > 1.0:  # percent vs decimal — the registry is inconsistent
                apy_val = apy_val / 100.0
            if best is None or apy_val > best:
                best = apy_val
        if best is None:
            return None, (
                "spot-leg yield NOT MEASURED — no live APY in "
                f"{ADAPTER_STATUS_FILENAME} for any of {sorted(yield_keys)}; "
                "refusing to substitute the legacy 5% literal (ADR-070 п.12)"
            )
        return best, None

    def _get_spot_yield(self, adapter_status: dict) -> float:
        """LEGACY wrapper — NOT on the scan path since ADR-070 п.12.

        Kept, with its documented behaviour intact (the literal 5% when nothing is
        measurable), only because `tests/test_bts_monitor.py` pins it and invariant #16
        forbids rewriting a pre-existing test to go green. The scan itself calls
        :meth:`_spot_yield_verdict` and refuses instead of substituting.
        """
        best_yield = DEFAULT_SPOT_YIELD
        yield_keys = {
            "aave_v3": "apy",
            "aave_usdc": "apy",
            "compound_v3": "apy",
            "morpho_steakhouse": "apy",
            "morpho_usdc": "apy",
        }
        for key, apy_field in yield_keys.items():
            entry = adapter_status.get(key, {})
            if isinstance(entry, dict):
                apy = entry.get(apy_field)
                if apy is not None:
                    try:
                        apy_val = float(apy)
                        if apy_val > 1.0:
                            apy_val = apy_val / 100.0
                        if apy_val > best_yield:
                            best_yield = apy_val
                    except (ValueError, TypeError):
                        continue
        return best_yield

    def scan(self) -> List[BTSOpportunity]:
        """Ranked opportunities only. See `scan_with_reasons` for what was NOT measured."""
        return self.scan_with_reasons().opportunities

    def scan_with_reasons(self) -> "BTSScan":
        """Scan the feed and report, verbatim, everything that could not be measured.

        An empty result now carries its reason: "the feed said there are no assets" and
        "the file was in a shape this monitor cannot read" are different facts, and
        before #78 both were published identically as `status: ok, 0 opportunities`.
        """
        unchecked: List[str] = []

        load = self._load_funding_verdict()
        if load.unchecked:
            unchecked.append(load.unchecked)
        funding_data = load.data
        if funding_data is None:
            reason = load.refusal or "no valid funding data"
            log.info("No valid funding data — returning empty opportunities (%s)", reason)
            # A refused payload means NO scan happened. "0 opportunities" is then a
            # non-statement, and publishing it as `status: ok` is the defect this file
            # exists to prevent — so the refusal is carried as an unchecked reason too.
            unchecked.append(f"scan NOT PERFORMED — {reason}")
            return BTSScan([], load.stale, unchecked, refusal=reason)

        adapter_status = self._load_adapter_status()
        spot_yield, spot_unchecked = self._spot_yield_verdict(adapter_status)
        if spot_yield is None:
            # No measured spot leg ⇒ no spread. Publishing one built on a literal is
            # exactly the "beautiful number" this monitor exists to stop.
            unchecked.append(spot_unchecked or "spot-leg yield NOT MEASURED")
            unchecked.append(f"scan NOT PERFORMED — {spot_unchecked}")
            return BTSScan([], load.stale, unchecked, refusal=spot_unchecked)

        our_yield = self._load_our_yield()

        rates_read = read_rates(funding_data)
        if not rates_read.measured:
            log.info("Funding rates NOT MEASURED: %s", rates_read.unchecked)
            unchecked.append(f"funding rates NOT MEASURED — {rates_read.unchecked}")
            return BTSScan([], load.stale, unchecked, our_yield=our_yield)
        rates = rates_read.rates
        if not rates:
            log.info(
                "No rates in funding data (feed reported an empty %r map)",
                rates_read.source_key,
            )
            return BTSScan([], load.stale, unchecked, our_yield=our_yield)

        inputs = []
        for asset in TRACKED_ASSETS:
            rate_info = rates.get(asset)
            if not rate_info:
                continue
            funding_annual = rate_info.get("funding_rate_annual")
            if funding_annual is None:
                continue
            try:
                funding_annual = float(funding_annual)
            except (ValueError, TypeError):
                continue
            inputs.append(BasisTradeInput(
                asset=asset,
                spot_yield_annual=spot_yield,
                perp_funding_annual=funding_annual,
                execution_cost_bps=DEFAULT_EXEC_COST_BPS,
                # Zero, not $20,000: the analyzer needs a number to multiply, and the
                # only honest one is "none allocated". Its `annual_pnl_usd` output is
                # discarded below and republished as NOT MEASURED with the reason.
                capital_usd=0.0,
            ))

        if not inputs:
            log.info(
                "No valid inputs built from funding data (tracked %s; feed offered %s)",
                list(TRACKED_ASSETS),
                sorted(str(k) for k in rates.keys()),
            )
            return BTSScan([], load.stale, unchecked, our_yield=our_yield)

        results = self._analyzer.analyze_batch(inputs)
        top = self._analyzer.top_opportunities(results, n=TOP_N)

        our_bps = our_yield.bps if our_yield.measured else None
        opportunities = []
        for r in top:
            opportunities.append(BTSOpportunity(
                asset=r.asset,
                spot_yield_pct=round(r.spot_yield_annual * 100, 2),
                perp_funding_pct=round(r.perp_funding_annual * 100, 2),
                net_spread_bps=r.net_spread_bps,
                gross_spread_bps=r.gross_spread_bps,
                edge_quality=r.edge_quality,
                recommended_action=r.recommended_action,
                # No capital ⇒ no dollar claim, and the reason travels with the record.
                annual_pnl_usd=None,
                capital_usd=None,
                pnl_unchecked=NO_CAPITAL_REASON,
                excess_vs_our_yield_bps=(
                    round(r.net_spread_bps - our_bps, 4) if our_bps is not None else None
                ),
            ))

        return BTSScan(opportunities, load.stale, unchecked, our_yield=our_yield)

    def _load_previous_excellent(self) -> Set[str]:
        try:
            data = atomic_load(str(self._opp_path), default={})
            if not isinstance(data, dict):
                return set()
            opps = data.get("opportunities", [])
            return {
                o["asset"]
                for o in opps
                if isinstance(o, dict) and o.get("edge_quality") == "EXCELLENT"
            }
        except Exception:
            return set()

    def _detect_new_excellent(
        self, current: List[BTSOpportunity],
    ) -> List[BTSOpportunity]:
        prev_excellent = self._load_previous_excellent()
        new_excellent = []
        for opp in current:
            if opp.edge_quality == "EXCELLENT" and opp.asset not in prev_excellent:
                new_excellent.append(opp)
        return new_excellent

    def _alert_gate(
        self,
        new_excellent: List[BTSOpportunity],
        our_yield: Optional[OurYieldRead],
    ) -> Tuple[List[BTSOpportunity], List[str]]:
        """Split new-EXCELLENT into "worth telling the owner" and "not", with reasons.

        The hurdle is OUR OWN measured yield: an opportunity that does not beat what the
        same capital already earns is not news, whatever tier the analyzer assigned. When
        our yield cannot be measured NOTHING passes — a hurdle nobody measured cannot be
        cleared (fail-CLOSED, invariant #2). Every refusal comes back verbatim; nothing is
        dropped silently.
        """
        if not new_excellent:
            return [], []
        if our_yield is None or not our_yield.measured:
            reason = (
                our_yield.unchecked if our_yield is not None
                else "our own yield was never looked up"
            )
            assets = ", ".join(o.asset for o in new_excellent)
            return [], [
                f"{len(new_excellent)} new EXCELLENT ({assets}) NOT eligible for an "
                f"owner alert: our own yield NOT MEASURED — {reason} "
                f"(fail-CLOSED, ADR-070 п.12)"
            ]

        hurdle_bps = float(our_yield.bps or 0.0)
        passed: List[BTSOpportunity] = []
        notes: List[str] = []
        for opp in new_excellent:
            excess = opp.net_spread_bps - hurdle_bps
            if excess > 0:
                passed.append(opp)
            else:
                notes.append(
                    f"{opp.asset} NOT alert-worthy: net {opp.net_spread_bps:.0f} bps does "
                    f"not beat our own measured yield {hurdle_bps:.0f} bps "
                    f"(excess {excess:+.0f} bps; {our_yield.source})"
                )
        return passed, notes

    @staticmethod
    def _hurdle_unchecked(our_yield: Optional[OurYieldRead]) -> Optional[str]:
        """Verbatim reason the hurdle is unknown, or None when it was measured.

        Exists so the COUNTS can tell "measured, nothing qualified" apart from "the
        hurdle was never measured". Both used to be published as `0`, and a zero reads
        as reassurance: a reader of `alert_worthy` alone saw "nothing to tell the owner"
        where the truth was "we do not know". Where there is no observation the artifact
        must say so, not say everything is fine (invariant #2).
        """
        if our_yield is None:
            return "our own yield was never looked up"
        if not our_yield.measured:
            return our_yield.unchecked or "our own yield NOT MEASURED (no reason given)"
        return None

    def _create_alerts(
        self,
        new_excellent: List[BTSOpportunity],
        our_yield: Optional[OurYieldRead] = None,
    ) -> int:
        if not new_excellent:
            return 0

        dispatcher = self._get_dispatcher()
        sent = 0
        hurdle = (
            f"{our_yield.bps:.0f} bps ({our_yield.source})"
            if our_yield is not None and our_yield.measured and our_yield.bps is not None
            else "NOT MEASURED"
        )
        for opp in new_excellent:
            title = f"BTS EXCELLENT: {opp.asset}"
            excess = (
                f"{opp.excess_vs_our_yield_bps:+.0f} bps"
                if opp.excess_vs_our_yield_bps is not None else "NOT MEASURED"
            )
            msg = (
                f"New EXCELLENT basis trade opportunity\n"
                f"Asset: {opp.asset}\n"
                f"Net spread: {opp.net_spread_bps:.0f} bps\n"
                f"Perp funding: {opp.perp_funding_pct:.1f}%\n"
                f"Spot yield: {opp.spot_yield_pct:.1f}%\n"
                f"Our own yield (hurdle): {hurdle}\n"
                f"Excess over our own yield: {excess}\n"
                f"{NO_CAPITAL_REASON}"
            )
            if dispatcher:
                try:
                    from spa_core.alerts.alert_dispatcher import AlertLevel
                    alert = dispatcher.create_alert(
                        level=AlertLevel.WARNING,
                        title=title,
                        message=msg,
                    )
                    dispatcher.dispatch(alert)
                    sent += 1
                except Exception as exc:
                    log.warning("Alert dispatch failed for %s: %s", opp.asset, exc)
            else:
                log.info("ALERT (log-only): %s — %s", title, msg)
                sent += 1
        return sent

    def _save_opportunities(
        self,
        opps: List[BTSOpportunity],
        stale: bool,
        unchecked: Optional[List[str]] = None,
        our_yield: Optional[OurYieldRead] = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        excellent_count = sum(1 for o in opps if o.edge_quality == "EXCELLENT")
        enter_count = sum(1 for o in opps if o.recommended_action == "ENTER")
        unchecked = list(unchecked or [])
        hurdle_unchecked = self._hurdle_unchecked(our_yield)

        payload = {
            "timestamp": now_iso,
            "generated_at": time.time(),
            "stale_feed": stale,
            "opportunities": [o.to_dict() for o in opps],
            "unchecked": unchecked,
            # The hurdle every owner-facing claim is judged against, published in full
            # (including its refusal) so a reader never has to guess what "EXCELLENT"
            # was measured against.
            "our_yield": (
                our_yield.to_dict() if our_yield is not None
                else {"measured": False, "unchecked": "our own yield was never looked up"}
            ),
            "capital": {"allocated_usd": None, "unchecked": NO_CAPITAL_REASON},
            "summary": {
                "excellent_count": excellent_count,
                "enter_count": enter_count,
                "total_analyzed": len(opps),
                "measured": not unchecked,
                # None, not 0, when the hurdle is unknown: "nothing beat our yield" and
                # "we never measured our yield" are different facts and must not share a
                # zero (ADR-070 п.12, fail-CLOSED).
                "alert_worthy_count": (
                    None if hurdle_unchecked else sum(
                        1 for o in opps
                        if o.excess_vs_our_yield_bps is not None
                        and o.excess_vs_our_yield_bps > 0
                    )
                ),
                "alert_worthy_unchecked": hurdle_unchecked,
            },
        }
        try:
            atomic_save(payload, str(self._opp_path))
        except Exception as exc:
            log.error("Failed to save opportunities: %s", exc)

    def _save_status(
        self,
        opps: List[BTSOpportunity],
        new_excellent_count: int,
        errors: List[str],
        unchecked: Optional[List[str]] = None,
        suppressed: Optional[List[str]] = None,
        our_yield: Optional[OurYieldRead] = None,
        alert_worthy: Optional[int] = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        unchecked = list(unchecked or [])
        suppressed = list(suppressed or [])
        payload = {
            "last_run": now_iso,
            "opportunities_found": len(opps),
            "new_excellent": new_excellent_count,
            "status": _verdict(errors, unchecked),
            "errors": errors,
            "unchecked": unchecked,
            "suppressed_alerts": suppressed,
            # The alert gate is its OWN verdict. `status` answers "did the scan happen"
            # (cycle #78 contract) and must not be repurposed: an unmeasured hurdle does
            # not make the spread measurement untrue, it makes the alert impossible.
            "alert_gate": {
                "hurdle": (
                    our_yield.to_dict() if our_yield is not None
                    else {"measured": False,
                          "unchecked": "our own yield was never looked up"}
                ),
                "alert_worthy": alert_worthy,
                # Paired with `alert_worthy` so a null there is never read as "fine":
                # verbatim reason when the hurdle itself could not be measured.
                "alert_worthy_unchecked": self._hurdle_unchecked(our_yield),
                "armed": _alerts_armed(),
            },
        }
        try:
            atomic_save(payload, str(self._status_path))
        except Exception as exc:
            log.error("Failed to save status: %s", exc)

    def run(self) -> dict:
        errors: List[str] = []
        unchecked: List[str] = []
        suppressed: List[str] = []
        opps: List[BTSOpportunity] = []
        new_excellent_count = 0
        our_yield: Optional[OurYieldRead] = None
        alert_worthy: Optional[int] = None

        try:
            scan = self.scan_with_reasons()
            opps = scan.opportunities
            unchecked = list(scan.unchecked)
            our_yield = scan.our_yield
            # `stale` describes the FEED. Before #78 it was `len(opps) == 0`, i.e. the
            # monitor published "the feed is stale" whenever nothing qualified — a claim
            # about a file, derived from something else entirely.
            stale = scan.stale_feed

            if opps:
                new_excellent = self._detect_new_excellent(opps)
                new_excellent_count = len(new_excellent)
                if new_excellent:
                    # Honest threshold FIRST (ADR-070 п.12): only what beats our own
                    # measured yield may reach the owner, and only then does the
                    # arming switch matter.
                    alertable, gate_notes = self._alert_gate(new_excellent, our_yield)
                    # An unmeasured hurdle yields NO count: 0 would say "nothing was
                    # worth telling you", which is a verdict nobody is entitled to when
                    # the hurdle is unknown.
                    alert_worthy = (
                        None if self._hurdle_unchecked(our_yield) else len(alertable)
                    )
                    for note in gate_notes:
                        log.info(note)
                    suppressed.extend(gate_notes)
                    if alertable and _alerts_armed():
                        self._create_alerts(alertable, our_yield)
                    else:
                        assets = ", ".join(o.asset for o in new_excellent)
                        note = (
                            f"{len(new_excellent)} new EXCELLENT ({assets}) NOT sent to "
                            f"Telegram: transport disarmed pending owner review "
                            f"(set {BTS_ALERTS_ARMED_ENV}=1 to arm)"
                            if not _alerts_armed() else
                            f"{len(new_excellent)} new EXCELLENT ({assets}) NOT sent to "
                            f"Telegram: transport is armed "
                            f"({BTS_ALERTS_ARMED_ENV}=1) but none cleared the hurdle"
                        )
                        log.info(note)
                        suppressed.append(note)

            self._save_opportunities(opps, stale, unchecked, our_yield)

        except Exception as exc:
            log.error("BTS monitor scan failed: %s", exc)
            errors.append(str(exc))
            self._save_opportunities([], True, unchecked, our_yield)

        self._save_status(
            opps, new_excellent_count, errors, unchecked, suppressed,
            our_yield=our_yield, alert_worthy=alert_worthy,
        )

        report = {
            "opportunities": len(opps),
            "new_excellent": new_excellent_count,
            "alert_worthy": alert_worthy,
            "errors": errors,
            "unchecked": unchecked,
            "suppressed_alerts": suppressed,
            "status": _verdict(errors, unchecked),
        }
        log.info("BTS monitor run complete: %s", report)
        return report


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="BTS Monitor")
    parser.add_argument("--run", action="store_true", help="Run monitor scan")
    parser.add_argument("--check", action="store_true", help="Run scan (read-only, no write)")
    args = parser.parse_args()

    if args.run or args.check:
        monitor = BTSMonitor(use_alert_dispatcher=args.run)
        if args.check:
            opps = monitor.scan()
            for o in opps:
                print(json.dumps(o.to_dict(), indent=2))
        else:
            result = monitor.run()
            print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        sys.exit(0)
