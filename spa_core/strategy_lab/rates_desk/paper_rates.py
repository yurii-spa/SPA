"""
spa_core/strategy_lab/rates_desk/paper_rates.py — LIVE paper-trading service for the rates-desk
FixedCarry sleeve (the VALIDATED one).

Mirrors spa_core/strategy_lab/paper.py: one service paper-trades the validated rates-desk FixedCarry
sleeve on LIVE rate-surface data, persists a growing time-series, and SURVIVES RESTART. Only FixedCarry
is registered here because it is the only sleeve that passed the GO validation (assertion2); the others
are research-only until they clear (BasisHedge is BLOCKED-NO-HEDGE). is_advisory=True throughout — it
simulates a forward carry track, it does NOT move live capital and never touches the go-live track.

DESIGN (the paper.py contract, applied to a RateSurface-driven sleeve):
  - Restart-survival: the sleeve's open-book + cash + accrued state is snapshotted to disk after each
    tick and restored on the next start — a relaunch CONTINUES the book rather than zeroing it. (We
    cannot blindly JSON the sleeve __dict__ like paper.py does for the price-bar sleeves because the
    FixedCarry book holds frozen Decimal dataclasses; we serialize a compact, JSON-safe book snapshot
    and rebuild the held quotes on restore.)
  - Idempotent per UTC day: re-ticking the same calendar day restores the PRE-tick snapshot and replays
    the single tick, so a re-run never double-accrues (exactly like paper.py's _tick_one).
  - Fail-CLOSED: if build_surface (live) raises or yields no usable PT quote, NO advance + NO fabricated
    point — a gap is recorded and the prior state is left untouched.
  - The decision proof chain is fed every tick (entries AND refusals) via proof_chain.record_decisions.
  - Atomic writes everywhere (spa_core.utils.atomic).

stdlib only, deterministic given the surface, LLM-FORBIDDEN.

Run (live, on the Mac):
    python3 -m spa_core.strategy_lab.rates_desk.paper_rates
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import logging
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, List, Optional

from spa_core.strategy_lab.rates_desk import feeds as rd_feeds
from spa_core.strategy_lab.rates_desk import proof_chain
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    KillState,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.sleeves import FixedCarrySleeve
from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger("spa.rates_desk.paper")

_ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = _ROOT / "data" / "rates_desk" / "paper"

SLEEVE_ID = "rates_desk_fixed_carry"
SERIES_CAP = 400
STATE_NAME = f"{SLEEVE_ID}_state.json"
SERIES_NAME = f"{SLEEVE_ID}_series.json"
STATUS_NAME = "status.json"

DEFAULT_CAPITAL = 100_000.0
_KIND_BY_VALUE = {k.value: k for k in UnderlyingKind}


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── compact, JSON-safe (de)serialization of the FixedCarry sleeve's state ──────────────────────────
def _quote_to_dict(q: RateQuote) -> dict:
    return {
        "underlying": q.underlying, "kind": q.kind.value, "venue": q.venue.value,
        "protocol": q.protocol, "market_id": q.market_id, "tenor_seconds": q.tenor_seconds,
        "as_of": q.as_of, "quoted_rate": str(q.quoted_rate), "tvl_usd": str(q.tvl_usd),
        "exit_liquidity_usd": str(q.exit_liquidity_usd), "hedge_available": q.hedge_available,
        "utilization": str(q.utilization), "ltv": str(q.ltv),
        "cap_headroom_usd": str(q.cap_headroom_usd),
    }


def _quote_from_dict(d: dict) -> RateQuote:
    return RateQuote(
        underlying=d["underlying"], kind=_KIND_BY_VALUE[d["kind"]], venue=RateVenue(d["venue"]),
        protocol=d["protocol"], market_id=d["market_id"], tenor_seconds=int(d["tenor_seconds"]),
        as_of=d["as_of"], quoted_rate=Decimal(d["quoted_rate"]), tvl_usd=Decimal(d["tvl_usd"]),
        exit_liquidity_usd=Decimal(d["exit_liquidity_usd"]), hedge_available=bool(d["hedge_available"]),
        utilization=Decimal(d["utilization"]), ltv=Decimal(d["ltv"]),
        cap_headroom_usd=Decimal(d["cap_headroom_usd"]),
    )


def _killstate_to_dict(s: KillState) -> dict:
    return {
        "neg_funding_streak": s.neg_funding_streak, "killed": s.killed,
        "kill_reason": s.kill_reason.value, "last_as_of": s.last_as_of,
        "entry_carry": None if s.entry_carry is None else str(s.entry_carry),
    }


def _killstate_from_dict(d: dict) -> KillState:
    from spa_core.strategy_lab.rates_desk.contracts import KillReason
    return KillState(
        neg_funding_streak=int(d.get("neg_funding_streak", 0)),
        killed=bool(d.get("killed", False)),
        kill_reason=KillReason(d.get("kill_reason", "none")),
        last_as_of=d.get("last_as_of", ""),
        entry_carry=None if d.get("entry_carry") in (None, "") else Decimal(d["entry_carry"]),
    )


def dump_sleeve(sleeve: FixedCarrySleeve) -> dict:
    """A compact, JSON-safe snapshot of the FixedCarry sleeve's full book state (restart-survival)."""
    from spa_core.strategy_lab.rates_desk.contracts import Opportunity
    books = {}
    for mid, bk in sleeve._books.items():
        opp: Opportunity = bk["opp"]
        books[mid] = {
            "quote": _quote_to_dict(opp.quote),
            "requested_size_usd": str(opp.requested_size_usd),
            "size": str(bk["size"]), "entry_rate": str(bk["entry_rate"]),
            "carry": str(bk["carry"]), "state": _killstate_to_dict(bk["state"]),
        }
    return {
        "capital": str(sleeve._capital), "cash": str(sleeve._cash),
        "accrued": str(sleeve._accrued), "closed": sleeve._closed, "books": books,
    }


def restore_sleeve(sleeve: FixedCarrySleeve, snap: dict) -> None:
    """Restore a compact snapshot into a freshly-built FixedCarry sleeve IN PLACE."""
    from spa_core.strategy_lab.rates_desk.contracts import Opportunity
    sleeve._capital = Decimal(snap.get("capital", "0"))
    sleeve._cash = Decimal(snap.get("cash", "0"))
    sleeve._accrued = Decimal(snap.get("accrued", "0"))
    sleeve._closed = list(snap.get("closed", []))
    sleeve._books = {}
    for mid, bk in (snap.get("books") or {}).items():
        q = _quote_from_dict(bk["quote"])
        opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY,
                          requested_size_usd=Decimal(bk["requested_size_usd"]))
        sleeve._books[mid] = {
            "opp": opp, "size": Decimal(bk["size"]), "state": _killstate_from_dict(bk["state"]),
            "entry_rate": Decimal(bk["entry_rate"]), "carry": Decimal(bk["carry"]),
        }


class RatesDeskPaperService:
    """Live paper-trading service for the validated rates-desk FixedCarry sleeve.

    Restart-survival: on construction we build the sleeve fresh, then OVERWRITE its book state from the
    persisted state file (if present). A relaunch continues the book rather than zeroing it. Idempotent
    per UTC day via a stored pre-tick snapshot. `surface_provider(as_of) -> (quotes, risks)` is
    injectable for tests; default = the live build_surface."""

    def __init__(
        self,
        surface_provider: Optional[Callable[[Optional[str]], tuple]] = None,
        state_dir: Optional[Path] = None,
        params: Optional[RatePolicyParams] = None,
        capital: float = DEFAULT_CAPITAL,
        record_proof: bool = True,
        telegram_send: Optional[Callable[[str], bool]] = None,
        alert_on_gap: bool = True,
    ) -> None:
        self._state_dir = Path(state_dir) if state_dir else STATE_DIR
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._params = params or RatePolicyParams()
        self._capital = capital
        self._record_proof = record_proof
        self._alert_on_gap = alert_on_gap
        self._telegram_send = telegram_send or self._default_telegram_send
        self._provider = surface_provider or (
            lambda as_of=None: rd_feeds.build_surface(as_of=as_of, include_lending=False))

        self._sleeve = FixedCarrySleeve(self._params)
        self._sleeve.init(self._capital, {})
        self._last_tick: Optional[str] = None
        self._restore()

    # ── persistence paths ──────────────────────────────────────────────────────────────────────────
    @property
    def _state_path(self) -> Path:
        return self._state_dir / STATE_NAME

    @property
    def _series_path(self) -> Path:
        return self._state_dir / SERIES_NAME

    @property
    def _status_path(self) -> Path:
        return self._state_dir / STATUS_NAME

    # ── restart-survival ─────────────────────────────────────────────────────────────────────────────
    def _restore(self) -> None:
        doc = atomic_load(str(self._state_path), default=None)
        if not isinstance(doc, dict) or "state" not in doc:
            self._last_tick = None
            return
        try:
            restore_sleeve(self._sleeve, doc["state"])
            self._last_tick = doc.get("meta", {}).get("last_tick_date")
        except Exception as exc:  # noqa: BLE001 — a corrupt snapshot must not zero the book
            log.warning("rates-desk paper restore failed (keeping fresh init): %s", exc)
            self._last_tick = None

    def _persist_state(self, last_tick_date: str, pretick: Optional[dict] = None) -> None:
        doc = atomic_load(str(self._state_path), default={})
        if not isinstance(doc, dict):
            doc = {}
        doc["meta"] = {"id": SLEEVE_ID, "last_tick_date": last_tick_date, "saved_at": _utc_now_iso()}
        doc["state"] = dump_sleeve(self._sleeve)
        if pretick is not None:
            doc["pretick"] = pretick
        atomic_save(doc, str(self._state_path))
        self._last_tick = last_tick_date

    # ── time-series ──────────────────────────────────────────────────────────────────────────────────
    def _append_series_point(self, point: dict) -> None:
        doc = atomic_load(str(self._series_path), default={"id": SLEEVE_ID, "series": []})
        if not isinstance(doc, dict):
            doc = {"id": SLEEVE_ID, "series": []}
        series: List[dict] = doc.get("series") or []
        if series and series[-1].get("date") == point["date"]:
            series = series[:-1]  # refresh today's point (idempotent per UTC day)
        series.append(point)
        if len(series) > SERIES_CAP:
            series = series[-SERIES_CAP:]
        doc["id"] = SLEEVE_ID
        doc["series"] = series
        doc["generated_at"] = _utc_now_iso()
        atomic_save(doc, str(self._series_path))

    @staticmethod
    def _default_telegram_send(text: str) -> bool:
        try:
            from spa_core.alerts.telegram_client import send_message
            return send_message(text)
        except Exception as exc:  # noqa: BLE001 — alerts must never crash the service
            log.warning("telegram send failed: %s", exc)
            return False

    # ── the tick ─────────────────────────────────────────────────────────────────────────────────────
    def tick(self, as_of: Optional[str] = None) -> dict:
        """Advance the FixedCarry sleeve one tick on the LATEST live rate surface (or an injected
        as_of). FAIL-CLOSED: no usable PT quote → no advance, no fabricated point, gap recorded. The
        per-day advance is idempotent (a re-tick restores the pre-tick snapshot first)."""
        try:
            quotes, risks = self._provider(as_of)
            pt_quotes = [q for q in quotes if q.venue == RateVenue.PENDLE_PT]
            day = pt_quotes[0].as_of if pt_quotes else (as_of or _utc_today())
            if not pt_quotes:
                raise rd_feeds.FeedError("no PENDLE_PT quote in the live surface")
        except Exception as exc:  # noqa: BLE001 — any fetch failure is fail-closed
            return self._handle_gap(as_of or _utc_today(), f"live surface fetch failed: {exc}")

        # idempotency: if we already ticked this day, restore the stored pre-tick snapshot first.
        if self._last_tick == day:
            doc = atomic_load(str(self._state_path), default={})
            pretick = doc.get("pretick") if isinstance(doc, dict) else None
            if isinstance(pretick, dict) and pretick.get("date") == day:
                restore_sleeve(self._sleeve, pretick["state"])
            else:
                return self._write_status(day, gap=False, gap_reason="")

        pre = dump_sleeve(self._sleeve)

        # continuous hold-kill, then entry scan (refusal-first) — both feed the proof chain.
        hold_verdicts = self._sleeve.tick_hold(risks, current_carries={}, as_of=day)
        entry_verdicts = self._sleeve.scan_and_enter(pt_quotes, risks, day)
        verdicts = list(hold_verdicts) + list(entry_verdicts)

        # accrue carry on the open books for the day
        from spa_core.strategy_lab.base import MarketSnapshot
        self._sleeve.step(MarketSnapshot(date=day))

        # proof chain: hash every decision (entries AND refusals)
        if self._record_proof and verdicts:
            try:
                proof_chain.record_decisions(verdicts, ts=_utc_now_iso())
            except Exception as exc:  # noqa: BLE001 — proof logging must never crash the service
                log.warning("rates-desk proof chain append failed: %s", exc)

        self._persist_state(day, pretick={"date": day, "state": pre})
        self._append_series_point(self._series_point(day, verdicts))
        return self._write_status(day, gap=False, gap_reason="")

    def _series_point(self, day: str, verdicts) -> dict:
        m = self._sleeve.metrics()
        refusals = sum(1 for v in verdicts if not v.approved)
        approvals = sum(1 for v in verdicts if v.approved)
        return {
            "date": day, "ts": _utc_now_iso(),
            "equity_usd": self._sleeve.equity(), "net_apy_pct": m.net_apy_pct,
            "open_books": len(self._sleeve._books), "closed_books": len(self._sleeve._closed),
            "approvals": approvals, "refusals": refusals,
        }

    # ── fail-closed gap handling ───────────────────────────────────────────────────────────────────
    def _handle_gap(self, day: str, reason: str) -> dict:
        log.warning("rates-desk paper: GAP on %s — %s (safe-hold, no advance)", day, reason)
        if self._alert_on_gap:
            self._telegram_send(f"⚠️ Rates-Desk paper GAP — {day}\n{reason}\n(safe-hold, no advance)")
        return self._write_status(day, gap=True, gap_reason=reason)

    # ── status ───────────────────────────────────────────────────────────────────────────────────────
    def _write_status(self, day: str, gap: bool, gap_reason: str) -> dict:
        m = self._sleeve.metrics()
        status = {
            "generated_at": _utc_now_iso(), "date": day, "gap": gap, "gap_reason": gap_reason,
            "sleeve": {
                "id": SLEEVE_ID, "name": self._sleeve.name, "is_advisory": True, "mandate": "stable",
                "equity_usd": self._sleeve.equity(), "net_apy_pct": m.net_apy_pct,
                "open_books": len(self._sleeve._books), "closed_books": len(self._sleeve._closed),
                "last_tick": self._last_tick,
            },
        }
        atomic_save(status, str(self._status_path))
        return status

    def status(self) -> dict:
        return self._write_status(self._last_tick or _utc_today(), gap=False, gap_reason="")


def main() -> int:
    import socket
    socket.setdefaulttimeout(30)
    svc = RatesDeskPaperService()
    st = svc.tick()
    import json
    print(json.dumps(st, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
