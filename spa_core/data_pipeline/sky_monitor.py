"""
Sky/sUSDS GSM Pause Delay Monitor.
Sky stays at 0% allocation until Ethereum governance confirms >= 48h timelock.

v2 upgrade: optionally reads GSM Pause Delay on-chain via public Ethereum JSON-RPC
(no web3.py required — uses stdlib urllib only). Falls back gracefully to manual
SKY_CURRENT_STATUS when network is unavailable.

Status values:
  PENDING   — GSM delay < 48h or not yet confirmed; 0% allocation
  ELIGIBLE  — GSM delay >= 48h on-chain; Sky → T1, 30% allocation cap

ADR reference: MEMORY_FACTS.md — Sky/sUSDS section
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("spa.sky_monitor")

# ─── Manual fallback constants ────────────────────────────────────────────────

SKY_WATCH_CONDITION = "GSM Pause Delay >= 48h"
SKY_CURRENT_STATUS  = "PENDING"   # change to ELIGIBLE when on-chain event fires
SKY_LAST_CHECKED    = "2026-06-18"  # updated; live checks use now_iso timestamp

# Threshold in hours for Sky T1 eligibility
GSM_MIN_HOURS: float = 48.0

# ─── On-chain / API config ────────────────────────────────────────────────────

# MakerDAO DSPause contract on Ethereum mainnet
# delay() returns the GSM Pause Delay in seconds
_DSPAUSE_ADDRESS   = "0xbE286431454714F511008713973d3B053A2d38f3"
_DELAY_SELECTOR    = "0x6a42b8f8"   # keccak256("delay()")[:4]

# Public Ethereum JSON-RPC endpoints (tried in order, first success wins)
_ETH_RPC_ENDPOINTS = [
    "https://eth.llamarpc.com",
    "https://cloudflare-eth.com",
    "https://rpc.ankr.com/eth",
]

# MakerDAO governance metrics API (optional secondary source)
_GOVERNANCE_API_URL = (
    "https://governance-metrics-dashboard.makerdao.com/api/all"
)

# Output path (relative to repo root data/)
_DATA_DIR = Path(__file__).parent.parent.parent / "data"


# ─── Private helpers ──────────────────────────────────────────────────────────

def _eth_call(to: str, data: str, rpc_url: str, timeout: int = 5) -> Optional[str]:
    """
    Execute a read-only eth_call via JSON-RPC. Returns the hex result string or
    None on any error.
    """
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method":  "eth_call",
        "params":  [{"to": to, "data": data}, "latest"],
        "id":      1,
    }).encode("utf-8")

    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        result = body.get("result", "")
        if isinstance(result, str) and result.startswith("0x") and len(result) > 2:
            return result
    except Exception as exc:
        log.debug(f"eth_call to {rpc_url} failed: {exc}")
    return None


def _hex_to_seconds(hex_val: str) -> Optional[float]:
    """Convert a 0x-prefixed uint256 hex string to float seconds."""
    try:
        return float(int(hex_val, 16))
    except (ValueError, TypeError):
        return None


def _fetch_gsm_delay_onchain() -> Optional[float]:
    """
    Query DSPause.delay() on Ethereum mainnet.
    Returns delay in hours, or None if all RPC endpoints fail.
    """
    for rpc in _ETH_RPC_ENDPOINTS:
        log.debug(f"Trying RPC endpoint: {rpc}")
        hex_result = _eth_call(_DSPAUSE_ADDRESS, _DELAY_SELECTOR, rpc)
        if hex_result:
            seconds = _hex_to_seconds(hex_result)
            if seconds is not None:
                hours = seconds / 3600.0
                log.info(f"GSM Pause Delay from on-chain ({rpc}): {hours:.2f}h")
                return hours
    return None


def _fetch_gsm_delay_governance_api() -> Optional[float]:
    """
    Attempt to read GSM delay from MakerDAO governance metrics API.
    Returns delay in hours, or None if unavailable / field missing.
    """
    try:
        req = urllib.request.Request(
            _GOVERNANCE_API_URL,
            headers={"Accept": "application/json", "User-Agent": "SPA-Monitor/2.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # The API may nest the value under various keys — probe common paths
        for path in (
            ("gsm_pause_delay",),
            ("governance", "gsm_pause_delay"),
            ("parameters", "gsm_pause_delay"),
        ):
            node = data
            for key in path:
                if isinstance(node, dict):
                    node = node.get(key)
                else:
                    node = None
                    break
            if node is not None:
                try:
                    hours = float(node) / 3600.0  # assume seconds
                    log.info(f"GSM Pause Delay from governance API: {hours:.2f}h")
                    return hours
                except (TypeError, ValueError):
                    pass
    except Exception as exc:
        log.debug(f"Governance API fetch failed: {exc}")
    return None


# ─── Public API ───────────────────────────────────────────────────────────────

def check_sky_status_live() -> dict:
    """
    Check Sky/sUSDS eligibility, trying live data sources before manual fallback.

    Source priority:
      1. On-chain (DSPause.delay() via public Ethereum JSON-RPC)
      2. MakerDAO governance metrics API
      3. Manual constant SKY_CURRENT_STATUS (always works, zero dependencies)

    Returns:
        {
            "status":       "PENDING" | "ELIGIBLE",
            "gsm_hours":    float | None,
            "source":       "onchain" | "api" | "manual",
            "last_checked": ISO-8601 timestamp string,
        }
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Try on-chain read (no web3 needed — raw JSON-RPC via urllib)
    try:
        gsm_hours = _fetch_gsm_delay_onchain()
        if gsm_hours is not None:
            status = "ELIGIBLE" if gsm_hours >= GSM_MIN_HOURS else "PENDING"
            return {
                "status":       status,
                "gsm_hours":    round(gsm_hours, 4),
                "source":       "onchain",
                "last_checked": now_iso,
            }
    except Exception as exc:
        log.warning(f"On-chain GSM check failed: {exc}")

    # 2. Try governance metrics API
    try:
        gsm_hours = _fetch_gsm_delay_governance_api()
        if gsm_hours is not None:
            status = "ELIGIBLE" if gsm_hours >= GSM_MIN_HOURS else "PENDING"
            return {
                "status":       status,
                "gsm_hours":    round(gsm_hours, 4),
                "source":       "api",
                "last_checked": now_iso,
            }
    except Exception as exc:
        log.warning(f"Governance API GSM check failed: {exc}")

    # 3. Manual fallback — always available
    log.info("GSM check: falling back to manual status")
    return {
        "status":       SKY_CURRENT_STATUS,
        "gsm_hours":    None,
        "source":       "manual",
        "last_checked": now_iso,  # always record actual check time, not hardcoded constant
    }


def get_sky_allocation_pct(status_dict: dict) -> float:
    """
    Return the Sky/sUSDS allocation cap based on eligibility status.

    Args:
        status_dict: dict as returned by check_sky_status_live() or
                     check_sky_status().

    Returns:
        0.0  if status is PENDING (Watch List — no allocation)
        0.30 if status is ELIGIBLE (T1 — 30% cap per policy ADR)
    """
    status = status_dict.get("status", "PENDING")
    return 0.30 if status == "ELIGIBLE" else 0.0


def export_sky_status_json(status_dict: Optional[dict] = None) -> Path:
    """
    Write sky_status.json to the data/ directory.

    Args:
        status_dict: Pre-computed status dict. If None, calls
                     check_sky_status_live() internally.

    Returns:
        Path to the written file.
    """
    if status_dict is None:
        status_dict = check_sky_status_live()

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "protocol":        "Sky/sUSDS",
        "watch_condition": SKY_WATCH_CONDITION,
        "gsm_min_hours":   GSM_MIN_HOURS,
        "status":          status_dict["status"],
        "eligible_for_t1": status_dict["status"] == "ELIGIBLE",
        "allocation_pct":  get_sky_allocation_pct(status_dict),
        "gsm_hours":       status_dict.get("gsm_hours"),
        "source":          status_dict.get("source", "manual"),
        "last_checked":    status_dict.get("last_checked"),
        "note": (
            "Upon ELIGIBLE: Sky → T1, 30% allocation per policy ADR. "
            "See MEMORY_FACTS.md."
        ),
    }
    path = _DATA_DIR / "sky_status.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    log.info(f"sky_status.json written → {path}  (status={out['status']}, source={out['source']})")
    return path


# ─── Legacy helpers (preserved for backwards compatibility) ───────────────────

def check_sky_status() -> dict:
    """
    Legacy sync status check. Uses manual constants only (no network I/O).
    For the live version with API/on-chain fallback, use check_sky_status_live().
    """
    return {
        "protocol":        "Sky/sUSDS",
        "watch_condition": SKY_WATCH_CONDITION,
        "status":          SKY_CURRENT_STATUS,
        "eligible_for_t1": SKY_CURRENT_STATUS == "ELIGIBLE",
        "allocation_pct":  0.30 if SKY_CURRENT_STATUS == "ELIGIBLE" else 0.0,
        "last_checked":    SKY_LAST_CHECKED,
        "note":            "Upon ELIGIBLE: Sky → T1, 30% allocation per ADR. See MEMORY_FACTS.md.",
    }


def get_watch_list_status() -> list[dict]:
    """Returns status of all Watch List protocols (backwards-compat)."""
    return [check_sky_status()]


# ─── Auto-upgrade trigger ─────────────────────────────────────────────────────

_UPGRADE_SIGNAL_FILE = _DATA_DIR / "sky_upgrade_needed.json"


def check_and_emit_upgrade_signal(status_dict: dict | None = None) -> dict:
    """Detect Sky T1 eligibility and write an upgrade signal file when ELIGIBLE.

    Call this once per export run, passing the result of check_sky_status_live().
    If Sky has become ELIGIBLE, this writes data/sky_upgrade_needed.json — a
    persistent signal that the owner must promote sky-susds to T1 in
    POOL_WHITELIST (defillama_fetcher.py) and update the KANBAN.

    Returns a dict with:
        eligible         — bool: Sky is currently ELIGIBLE for T1
        signal_written   — bool: signal file was (re)written this run
        first_eligible   — bool: status transitioned from PENDING→ELIGIBLE now
        signal_path      — str | None: path to signal file if written
        action           — str | None: human-readable action description
    """
    current = status_dict or check_sky_status_live()
    eligible = current.get("status") == "ELIGIBLE"

    if not eligible:
        # Clear stale signal file if Sky has reverted to PENDING
        if _UPGRADE_SIGNAL_FILE.exists():
            _UPGRADE_SIGNAL_FILE.unlink()
            log.info("sky_upgrade_needed.json removed — Sky is no longer ELIGIBLE")
        return {
            "eligible": False,
            "signal_written": False,
            "first_eligible": False,
            "signal_path": None,
            "action": None,
        }

    # Sky is ELIGIBLE — determine if this is a new transition
    first_eligible = not _UPGRADE_SIGNAL_FILE.exists()

    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    signal = {
        "detected_at":   datetime.now(timezone.utc).isoformat(),
        "status":        "ELIGIBLE",
        "gsm_hours":     current.get("gsm_hours"),
        "source":        current.get("source"),
        "first_detected": (
            datetime.now(timezone.utc).isoformat()
            if first_eligible
            else json.loads(_UPGRADE_SIGNAL_FILE.read_text(encoding="utf-8")).get("first_detected")
        ),
        "action_required": (
            "Promote sky-susds to T1 in POOL_WHITELIST (defillama_fetcher.py). "
            "Set tier='T1', max_concentration=0.30. Update KANBAN BL-007."
        ),
        "resolved": False,
    }
    _UPGRADE_SIGNAL_FILE.write_text(
        json.dumps(signal, indent=2, default=str), encoding="utf-8"
    )

    level = "🚨 NEW" if first_eligible else "ℹ️  ONGOING"
    log.warning(
        f"{level} — Sky/sUSDS is ELIGIBLE for T1 (GSM delay={current.get('gsm_hours')} h). "
        f"Action required: promote to T1 in POOL_WHITELIST. "
        f"Signal file: {_UPGRADE_SIGNAL_FILE}"
    )

    return {
        "eligible": True,
        "signal_written": True,
        "first_eligible": first_eligible,
        "signal_path": str(_UPGRADE_SIGNAL_FILE),
        "action": signal["action_required"],
    }
