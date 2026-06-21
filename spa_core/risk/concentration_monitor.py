"""
spa_core/risk/concentration_monitor.py — T2 aggregate concentration early-warning
================================================================================

Tiered T2-concentration monitor (MP-1263). The deterministic RiskPolicy
(``spa_core/risk/policy.py``) already enforces the **hard** ADR-019 cap of 50%
T2 aggregate — a new T2 position that would push the total over 50% is rejected
(``approved=False``) and that decision cannot be overridden.

What this module adds is *advance warning* so we never get surprised at the
hard wall. It layers three graduated thresholds **below** the existing 50% cap:

    42% → ADVISORY   log-only note ("getting full")
    45% → WARNING    Telegram alert ("new T2 positions about to be blocked")
    50% → BREACH     hard cap reached (mirrors RiskPolicy / ADR-019)

The compliance audit (``audit_report_generator``) reported T2 aggregate at
**47.14% / 50%** — between WARNING and BREACH, only 2.86% of headroom left.
This monitor would have fired the WARNING Telegram at 45% with time to react.

Design rules (consistent with the rest of the risk domain):
  * **Deterministic, LLM-forbidden, pure-stdlib.** No external deps, no LLM.
  * **Read-only / advisory.** Never mutates allocator / risk / execution state.
    It *reports* a status; it does not itself block trades — RiskPolicy does.
  * **Single source of tier truth.** T2 classification reuses the compliance
    report's ``_tier_map()`` (read-only ADAPTER_REGISTRY, unknown→"T2"
    conservatively), so this monitor's percentage matches the audit's 47.14%
    byte-for-byte rather than inventing a parallel tier map.
  * **Fail-safe.** Telegram send never raises into the caller (cycle_runner).

Usage
-----
    from spa_core.risk.concentration_monitor import T2ConcentrationAlert

    alert = T2ConcentrationAlert()
    status = alert.check_t2_concentration(positions)   # ConcentrationStatus
    headroom = alert.get_t2_headroom(positions)        # float (fraction)

    # End-to-end from the on-disk state (used by cycle_runner):
    report = alert.run(data_dir="data", send_telegram=True, write=True)

CLI
---
    python3 -m spa_core.risk.concentration_monitor --check      # compute+print
    python3 -m spa_core.risk.concentration_monitor --run        # + atomic write
    python3 -m spa_core.risk.concentration_monitor --run --alert # + Telegram
"""

from __future__ import annotations

import argparse
import enum
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

log = logging.getLogger(__name__)

# ─── Thresholds (fractions of total capital) ─────────────────────────────────
# HARD_CAP mirrors RiskConfig.max_total_t2_allocation (ADR-019). Kept as a
# module constant so tests/callers can reference it; the authoritative gate
# remains RiskPolicy.check_new_position.

OUTPUT_FILENAME = "t2_concentration_alert.json"
POSITIONS_FILENAME = "current_positions.json"


class ConcentrationStatus(enum.Enum):
    """Graduated T2-concentration status. Ordered by severity."""

    NORMAL = "NORMAL"        # < GRADUAL_WARN — plenty of headroom
    ADVISORY = "ADVISORY"    # ≥ 42% — log only
    WARNING = "WARNING"      # ≥ 45% — Telegram alert, new T2 about to block
    BREACH = "BREACH"        # ≥ 50% — hard cap; new T2 allocations blocked

    @property
    def severity(self) -> int:
        return {"NORMAL": 0, "ADVISORY": 1, "WARNING": 2, "BREACH": 3}[self.value]


@dataclass
class ConcentrationReport:
    """Result of a T2-concentration check (advisory, read-only)."""

    status: ConcentrationStatus
    t2_total_pct: float            # T2 aggregate as a fraction (0..1)
    headroom_pct: float            # fraction remaining before HARD_CAP (≥ 0)
    capital_usd: float
    t2_usd: float
    t2_protocols: list[str] = field(default_factory=list)
    message: str = ""
    block_new_t2: bool = False     # True at BREACH — advisory signal to allocator
    as_of: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "t2_total_pct": round(self.t2_total_pct * 100.0, 4),
            "headroom_pct": round(self.headroom_pct * 100.0, 4),
            "capital_usd": round(self.capital_usd, 2),
            "t2_usd": round(self.t2_usd, 2),
            "t2_protocols": list(self.t2_protocols),
            "block_new_t2": self.block_new_t2,
            "message": self.message,
            "as_of": self.as_of,
        }


def _tier_map() -> dict[str, str]:
    """Protocol-key → risk-tier map.

    Reuses the compliance report's single source of truth so this monitor's
    T2 aggregate matches the audit exactly. Falls back to the read-only
    ADAPTER_REGISTRY directly if the compliance module is unavailable.
    """
    try:
        from spa_core.compliance.audit_report_generator import _tier_map as _audit_tier_map
        return _audit_tier_map()
    except Exception:  # noqa: BLE001 — never let an import shape the result
        try:
            from spa_core.adapters import ADAPTER_REGISTRY
            return {key: tier for key, tier, _cls in ADAPTER_REGISTRY}
        except Exception:  # noqa: BLE001
            return {}


def _coerce_positions(positions: Any, tier_map: dict[str, str]) -> list[dict]:
    """Normalise the many position shapes into ``[{"protocol","tier","usd"}]``.

    Accepts:
      * ``current_positions.json`` doc — ``{"positions": {proto: usd}, ...}``
      * raw ``{proto: usd}`` mapping
      * list of dicts with ``size_pct`` / ``weight`` / ``amount_usd`` / ``usd``
        and an optional explicit ``tier`` (spec form from the task).

    Unknown tiers default to ``"T2"`` (conservative — matches the audit), so an
    un-registered protocol counts *toward* the T2 cap rather than slipping the
    warning. ``size_pct``/``weight`` inputs are treated as fractions of capital.
    """
    out: list[dict] = []

    # current_positions.json document → unwrap to the inner mapping.
    if isinstance(positions, dict) and "positions" in positions and isinstance(
        positions["positions"], (dict, list)
    ):
        positions = positions["positions"]

    if isinstance(positions, dict):
        for proto, usd in positions.items():
            try:
                val = float(usd)
            except (TypeError, ValueError):
                continue
            if val < 0:
                continue
            out.append({
                "protocol": str(proto),
                "tier": tier_map.get(str(proto), "T2"),
                "usd": val,
                "size_pct": None,
            })
        return out

    if isinstance(positions, Iterable):
        for p in positions:
            if not isinstance(p, dict):
                continue
            proto = str(p.get("protocol") or p.get("protocol_key") or p.get("id") or "")
            tier = p.get("tier") or tier_map.get(proto, "T2")
            usd = p.get("usd")
            if usd is None:
                usd = p.get("amount_usd")
            size_pct = p.get("size_pct")
            if size_pct is None:
                size_pct = p.get("weight")
            entry = {"protocol": proto, "tier": str(tier), "usd": None, "size_pct": None}
            if usd is not None:
                try:
                    entry["usd"] = float(usd)
                except (TypeError, ValueError):
                    pass
            if size_pct is not None:
                try:
                    entry["size_pct"] = float(size_pct)
                except (TypeError, ValueError):
                    pass
            if entry["usd"] is not None or entry["size_pct"] is not None:
                out.append(entry)
    return out


class T2ConcentrationAlert:
    """Tiered T2-concentration early-warning monitor (advisory, read-only).

    Thresholds are fractions of total capital. ``HARD_CAP`` equals the
    deterministic RiskConfig.max_total_t2_allocation (ADR-019) — this monitor
    does not enforce it, it warns *ahead* of it.
    """

    GRADUAL_WARN: float = 0.42   # 42% → advisory note (log only)
    WARN_THRESHOLD: float = 0.45  # 45% → warning (Telegram)
    HARD_CAP: float = 0.50        # 50% → breach (existing RiskConfig cap)

    def __init__(
        self,
        data_dir: str | os.PathLike | None = None,
        gradual_warn: float | None = None,
        warn_threshold: float | None = None,
        hard_cap: float | None = None,
    ) -> None:
        self.data_dir = str(data_dir) if data_dir else "data"
        if gradual_warn is not None:
            self.GRADUAL_WARN = float(gradual_warn)
        if warn_threshold is not None:
            self.WARN_THRESHOLD = float(warn_threshold)
        if hard_cap is not None:
            self.HARD_CAP = float(hard_cap)

    # ── Core computation ─────────────────────────────────────────────────────

    def compute_t2_total(self, positions: Any) -> tuple[float, float, float, list[str]]:
        """Return ``(t2_fraction, capital_usd, t2_usd, t2_protocols)``.

        ``t2_fraction`` is the T2 aggregate as a fraction of total capital.
        When positions carry only ``size_pct`` (fractions, no USD), capital is
        normalised to 1.0 and ``t2_usd`` is the fractional sum.
        """
        tier_map = _tier_map()
        norm = _coerce_positions(positions, tier_map)

        # Pull capital from a doc if present (best estimate of total incl. cash).
        capital_usd = 0.0
        if isinstance(positions, dict):
            try:
                capital_usd = float(positions.get("capital_usd") or 0.0)
            except (TypeError, ValueError):
                capital_usd = 0.0

        usd_mode = any(p["usd"] is not None for p in norm)
        if usd_mode:
            deployed = sum(p["usd"] for p in norm if p["usd"] is not None)
            total = capital_usd if capital_usd > 0 else deployed
            if total <= 0:
                return 0.0, 0.0, 0.0, []
            t2_usd = sum(
                p["usd"] for p in norm
                if p["tier"] == "T2" and p["usd"] is not None
            )
            t2_protocols = sorted(
                p["protocol"] for p in norm
                if p["tier"] == "T2" and p["usd"] is not None
            )
            return t2_usd / total, total, t2_usd, t2_protocols

        # size_pct / weight mode — fractions of capital.
        t2_frac = sum(
            p["size_pct"] for p in norm
            if p["tier"] == "T2" and p["size_pct"] is not None
        )
        t2_protocols = sorted(
            p["protocol"] for p in norm
            if p["tier"] == "T2" and p["size_pct"] is not None
        )
        # If size_pct values look like percents (sum > 1.5), treat as percent.
        scale = 100.0 if t2_frac > 1.5 else 1.0
        return t2_frac / scale, 1.0, t2_frac / scale, t2_protocols

    def check_t2_concentration(self, positions: Any) -> ConcentrationStatus:
        """Classify current T2 aggregate into a graduated status."""
        t2_frac, _cap, _usd, _protos = self.compute_t2_total(positions)
        return self._classify(t2_frac)

    def _classify(self, t2_frac: float) -> ConcentrationStatus:
        if t2_frac >= self.HARD_CAP:
            return ConcentrationStatus.BREACH
        if t2_frac >= self.WARN_THRESHOLD:
            return ConcentrationStatus.WARNING
        if t2_frac >= self.GRADUAL_WARN:
            return ConcentrationStatus.ADVISORY
        return ConcentrationStatus.NORMAL

    def get_t2_headroom(self, positions: Any) -> float:
        """How much more T2 can be added (fraction) before HARD_CAP. ≥ 0."""
        t2_frac, _cap, _usd, _protos = self.compute_t2_total(positions)
        return max(0.0, self.HARD_CAP - t2_frac)

    # ── Reporting ────────────────────────────────────────────────────────────

    def build_report(self, positions: Any, as_of: str | None = None) -> ConcentrationReport:
        """Full advisory report for the given positions."""
        t2_frac, capital, t2_usd, t2_protocols = self.compute_t2_total(positions)
        status = self._classify(t2_frac)
        headroom = max(0.0, self.HARD_CAP - t2_frac)
        if as_of is None and isinstance(positions, dict):
            as_of = positions.get("generated_at") or positions.get("as_of")
        return ConcentrationReport(
            status=status,
            t2_total_pct=t2_frac,
            headroom_pct=headroom,
            capital_usd=capital,
            t2_usd=t2_usd,
            t2_protocols=t2_protocols,
            message=self.format_message(status, t2_frac, headroom),
            block_new_t2=(status is ConcentrationStatus.BREACH),
            as_of=as_of,
        )

    def format_message(
        self, status: ConcentrationStatus, t2_frac: float, headroom: float
    ) -> str:
        """Human-readable one-liner per status (Telegram-ready, HTML-safe)."""
        pct = t2_frac * 100.0
        cap = self.HARD_CAP * 100.0
        head = headroom * 100.0
        if status is ConcentrationStatus.BREACH:
            return (
                f"🛑 T2 CONCENTRATION BREACH: {pct:.2f}%/{cap:.0f}% cap reached — "
                f"new T2 positions blocked by RiskPolicy (ADR-019)."
            )
        if status is ConcentrationStatus.WARNING:
            return (
                f"⚠️ T2 CONCENTRATION: {pct:.2f}%/{cap:.0f}% cap — only "
                f"{head:.2f}% headroom remaining. New T2 positions blocked."
            )
        if status is ConcentrationStatus.ADVISORY:
            return (
                f"ℹ️ T2 concentration advisory: {pct:.2f}%/{cap:.0f}% cap — "
                f"{head:.2f}% headroom remaining."
            )
        return (
            f"✅ T2 concentration normal: {pct:.2f}%/{cap:.0f}% cap — "
            f"{head:.2f}% headroom."
        )

    # ── Telegram (fail-safe, advisory) ───────────────────────────────────────

    def send_alert(self, report: ConcentrationReport) -> bool:
        """Send a Telegram alert for WARNING/BREACH. Never raises.

        ADVISORY is log-only (no Telegram). NORMAL sends nothing. Uses HTML
        parse_mode — protocol names contain ``_`` which breaks legacy Markdown.
        """
        if report.status is ConcentrationStatus.ADVISORY:
            log.info("T2 advisory (log-only): %s", report.message)
            return False
        if report.status.severity < ConcentrationStatus.WARNING.severity:
            return False
        try:
            from spa_core.alerts.telegram_client import send_message
            return bool(send_message(report.message, parse_mode="HTML"))
        except Exception as exc:  # noqa: BLE001 — alerts must never crash the cycle
            log.warning("T2 concentration Telegram send failed (non-critical): %s", exc)
            return False

    # ── End-to-end (used by cycle_runner) ────────────────────────────────────

    def run(
        self,
        data_dir: str | os.PathLike | None = None,
        send_telegram: bool = True,
        write: bool = True,
    ) -> dict:
        """Load positions from disk, classify, optionally alert + persist.

        Fail-safe: any failure is logged and returns a NORMAL/empty report
        rather than raising — this is invoked from the daily cycle.
        """
        ddir = str(data_dir) if data_dir else self.data_dir
        positions_path = os.path.join(ddir, POSITIONS_FILENAME)
        try:
            with open(positions_path, "r", encoding="utf-8") as fh:
                positions_doc = json.load(fh)
        except (OSError, ValueError) as exc:
            log.warning("T2 monitor: cannot read %s (%s)", positions_path, exc)
            empty = ConcentrationReport(
                status=ConcentrationStatus.NORMAL, t2_total_pct=0.0,
                headroom_pct=self.HARD_CAP, capital_usd=0.0, t2_usd=0.0,
                message="T2 monitor: positions unavailable",
            )
            return {**empty.to_dict(), "telegram_sent": False, "available": False}

        report = self.build_report(positions_doc)

        telegram_sent = False
        if send_telegram:
            telegram_sent = self.send_alert(report)

        out = {**report.to_dict(), "telegram_sent": telegram_sent, "available": True}

        if write:
            try:
                from spa_core.utils.atomic import atomic_save
                atomic_save(out, os.path.join(ddir, OUTPUT_FILENAME))
            except Exception as exc:  # noqa: BLE001 — advisory write, never crash
                log.warning("T2 monitor: atomic write failed (%s)", exc)

        return out


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="T2 aggregate concentration early-warning monitor (advisory)."
    )
    parser.add_argument("--run", action="store_true",
                        help="compute + atomically write t2_concentration_alert.json")
    parser.add_argument("--check", action="store_true",
                        help="compute + print only, no write (default)")
    parser.add_argument("--alert", action="store_true",
                        help="send Telegram alert for WARNING/BREACH")
    parser.add_argument("--data-dir", default="data", help="data directory")
    args = parser.parse_args(argv)

    alert = T2ConcentrationAlert(data_dir=args.data_dir)
    out = alert.run(
        data_dir=args.data_dir,
        send_telegram=args.alert,
        write=args.run,
    )
    print(json.dumps(out, indent=2))
    # exit 0 always (advisory module)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
