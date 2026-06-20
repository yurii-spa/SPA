"""
spa_core/alerts/apy_spike_monitor.py — MP-1581 (Sprint v12.26)

Protocol APY trend monitor: detects *yield spikes* — temporary high-utilization
events where a whitelisted protocol's APY jumps far above its mean (e.g. Aave
occasionally printing 12.60% vs a ~3.64% mean). These spikes are short-lived but
represent outsized yield opportunities the cycle runner can act on.

Real historical ranges that motivated the thresholds::

    Aave V3      1.57 – 12.60 %   (mean ~3.64 %)
    Compound V3  2.34 – 11.70 %
    Yearn V3     1.37 – 16.05 %
    Morpho       3.55 –  9.57 %

Design
------
* **Read-only / advisory.** Never touches allocator, risk or execution. Emits
  alerts only; acting on them is the cycle runner's decision.
* **Pure stdlib.** Offline-safe — Telegram is wrapped in try/except and the APY
  source defaults to the execution-owned ``data/adapter_status.json`` snapshot
  (read-only; this module NEVER writes it).
* **Atomic writes only** for its own history file ``data/apy_spike_history.json``
  (ring-buffer, tmp + os.replace via ``atomic_append_ring``).
* **LLM FORBIDDEN** (monitoring component).

APY units: ``data/adapter_status.json`` stores ``apy`` already in **percent**
(e.g. ``3.12`` == 3.12 %), matching ``SPIKE_THRESHOLDS`` which are also percent.

CLI::

    python3 -m spa_core.alerts.apy_spike_monitor --check   # detect only, no I/O
    python3 -m spa_core.alerts.apy_spike_monitor --run     # detect + telegram + log
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, asdict
from typing import Callable, Dict, List, Optional

from spa_core.utils.atomic import atomic_load, atomic_append_ring

log = logging.getLogger("spa.alerts.apy_spike")

#: Per-protocol spike trigger thresholds, in **percent** APY.
#: Tuned above each protocol's historical mean so only genuine spikes fire.
SPIKE_THRESHOLDS: Dict[str, float] = {
    "aave_v3": 7.0,      # trigger if Aave     > 7%  (vs ~3.64% mean)
    "compound_v3": 8.0,  # trigger if Compound > 8%
    "yearn_v3": 10.0,    # trigger if Yearn    > 10%
    "morpho_blue": 9.0,  # trigger if Morpho   > 9%
    "fluid_usdc": 9.0,   # trigger if Fluid    > 9%
}

#: Read-only APY snapshot owned by the execution domain — we only READ it.
ADAPTER_STATUS_PATH = "data/adapter_status.json"
#: Our own spike history ring-buffer (this module owns it).
HISTORY_PATH = "data/apy_spike_history.json"
HISTORY_CAP = 200


@dataclass
class SpikeAlert:
    """One protocol APY spike above its configured threshold."""

    protocol: str
    current_apy: float          # percent, e.g. 12.60
    threshold: float            # percent, e.g. 7.0
    excess_pct: float           # percentage points above threshold (current - threshold)
    timestamp: str              # ISO-8601 UTC
    recommendation: str         # human-actionable advisory

    def to_dict(self) -> Dict:
        return asdict(self)


class APYSpikeMonitor:
    """Detects APY spikes against per-protocol thresholds and raises alerts.

    Parameters
    ----------
    base_dir:
        Repo root; data paths are resolved relative to it.
    apy_source:
        Optional override for the current-APY provider. Either a ``dict`` of
        ``{protocol: apy_percent}`` or a zero-arg callable returning such a
        dict. When ``None`` (default) the monitor reads the execution-owned
        ``data/adapter_status.json`` snapshot (read-only).

    Usage::

        mon = APYSpikeMonitor()
        spikes = mon.check_spikes()           # detect only
        results = mon.run()                   # detect + telegram + log
    """

    SPIKE_THRESHOLDS = SPIKE_THRESHOLDS

    def __init__(
        self,
        base_dir: str = ".",
        apy_source: Optional[object] = None,
    ) -> None:
        self.base_dir = base_dir.rstrip("/") or "."
        self._apy_source = apy_source

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _path(self, rel: str) -> str:
        if self.base_dir in (".", ""):
            return rel
        return f"{self.base_dir}/{rel}"

    # ------------------------------------------------------------------
    # Current-APY source
    # ------------------------------------------------------------------

    def _load_current_apys(self) -> Dict[str, float]:
        """Return ``{protocol: apy_percent}`` for the configured protocols.

        Resolution order:
          1. injected ``apy_source`` (dict or callable) — for tests / live feed,
          2. read-only ``data/adapter_status.json`` snapshot (percent units).

        Always fail-safe: missing/corrupt source → ``{}`` (no spikes).
        """
        source = self._apy_source
        if source is not None:
            try:
                raw = source() if callable(source) else source
            except Exception as exc:  # noqa: BLE001 — monitoring never crashes
                log.warning("apy_source callable failed: %s", exc)
                return {}
            return self._coerce_apys(raw)

        data = atomic_load(self._path(ADAPTER_STATUS_PATH), default={})
        adapters = data.get("adapters", {}) if isinstance(data, dict) else {}
        out: Dict[str, float] = {}
        for proto in self.SPIKE_THRESHOLDS:
            entry = adapters.get(proto)
            if isinstance(entry, dict):
                apy = entry.get("apy")
                if isinstance(apy, (int, float)):
                    out[proto] = float(apy)
        return out

    @staticmethod
    def _coerce_apys(raw: object) -> Dict[str, float]:
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, float] = {}
        for k, v in raw.items():
            if isinstance(v, (int, float)):
                out[str(k)] = float(v)
        return out

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_spikes(
        self, apys: Optional[Dict[str, float]] = None
    ) -> List[SpikeAlert]:
        """Return a list of :class:`SpikeAlert` for protocols above threshold.

        ``apys`` (percent units) overrides the configured source when supplied —
        handy for tests and for the cycle runner passing its own snapshot.
        """
        current = self._coerce_apys(apys) if apys is not None else self._load_current_apys()
        ts = datetime.datetime.utcnow().isoformat()

        spikes: List[SpikeAlert] = []
        for proto, threshold in self.SPIKE_THRESHOLDS.items():
            apy = current.get(proto)
            if apy is None:
                continue
            if apy > threshold:
                spikes.append(
                    SpikeAlert(
                        protocol=proto,
                        current_apy=round(apy, 4),
                        threshold=threshold,
                        excess_pct=round(apy - threshold, 4),
                        timestamp=ts,
                        recommendation=f"Consider increasing {proto} allocation",
                    )
                )
                log.warning(
                    "APY SPIKE %s: %.2f%% > %.2f%% threshold (+%.2fpp)",
                    proto,
                    apy,
                    threshold,
                    apy - threshold,
                )
        return spikes

    def send_telegram_alert(self, spike: SpikeAlert) -> bool:
        """Send a yield-spike Telegram alert. Fail-safe (never raises)."""
        try:
            from spa_core.alerts.telegram_client import send_message  # local import

            msg = self.format_alert(spike)
            # HTML parse_mode: protocol names contain '_' which Telegram's legacy
            # Markdown parser 400s on (see telegram_client docstring).
            return send_message(msg, parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
            log.warning("Telegram spike alert failed: %s", exc)
            return False

    @staticmethod
    def format_alert(spike: SpikeAlert) -> str:
        """Human-facing Telegram message for a spike alert."""
        return (
            f"🚀 YIELD SPIKE: {spike.protocol} at {spike.current_apy:.2f}% APY!\n"
            f"Threshold: {spike.threshold:.2f}%  (+{spike.excess_pct:.2f}pp above)\n"
            f"💡 {spike.recommendation}\n"
            f"🕒 {spike.timestamp}"
        )

    def log_spike_to_history(self, spike: SpikeAlert) -> int:
        """Append a spike to ``data/apy_spike_history.json`` (atomic ring-buffer).

        Returns the new history length (capped at ``HISTORY_CAP``).
        """
        return atomic_append_ring(
            spike.to_dict(),
            self._path(HISTORY_PATH),
            cap=HISTORY_CAP,
            list_key="spikes",
        )

    def run(self, apys: Optional[Dict[str, float]] = None) -> List[SpikeAlert]:
        """Detect spikes, send a Telegram alert and log each one. Returns spikes."""
        spikes = self.check_spikes(apys=apys)
        for spike in spikes:
            self.send_telegram_alert(spike)
            self.log_spike_to_history(spike)
        return spikes


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect protocol APY yield spikes (read-only / advisory).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="Detect spikes and print them; no Telegram, no disk writes (default).",
    )
    group.add_argument(
        "--run",
        action="store_true",
        help="Detect spikes, send Telegram alerts and append to history.",
    )
    parser.add_argument("--base-dir", default=".", help="Repo root (default: .).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    mon = APYSpikeMonitor(base_dir=args.base_dir)

    spikes = mon.run() if args.run else mon.check_spikes()

    if not spikes:
        print("No APY spikes detected.")
        return 0

    verb = "Triggered" if args.run else "Detected"
    print(f"{verb} {len(spikes)} APY spike(s):")
    for s in spikes:
        print(
            f"  🚀 {s.protocol}: {s.current_apy:.2f}% "
            f"(threshold {s.threshold:.2f}%, +{s.excess_pct:.2f}pp) — {s.recommendation}"
        )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
