"""
SPA — /protocols Telegram Command Reporter (MP-659 / v6.59)

Loads adapter_status.json + current_positions.json, formats a rich
per-protocol status message, and can send it via the Telegram Bot API.

Pure stdlib only. No external dependencies.
SECRETS POLICY: No tokens/keys ever written to this file or any artifact.
Credentials resolved at call time via: explicit arg → env var → macOS Keychain.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.utils.errors import ConfigError

__all__ = [
    "format_protocols_message",
    "split_message",
    "send_protocols_report",
    "load_adapter_data",
]

log = logging.getLogger("spa.telegram_protocols_reporter")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TELEGRAM_MAX_LEN = 4096

# ──────────────────────────── tier ordering ────────────────────────────────

_TIER_ORDER = ["T1", "T1-conditional", "T2-conditional", "T2", "T3-SPEC", "T3"]

_TIER_LABEL: dict[str, str] = {
    "T1": "T1 — Anchor Protocols",
    "T1-conditional": "T1 (Conditional)",
    "T2-conditional": "T2 (Conditional)",
    "T2": "T2 Protocols",
    "T3-SPEC": "T3-SPEC (Speculative / Advisory Only)",
    "T3": "T3 Protocols",
}

# Top-level keys in adapter_status.json that are NOT adapter entries
_SKIP_KEYS = frozenset(
    {
        "generated_at",
        "schema_version",
        "execution_mode",
        "live_apy_enabled",
        "mev_protection",
        "adapters",
        "morpho_steakhouse",
        "base_gas_monitor",
        "positions_data",  # injected by load_adapter_data()
    }
)


# ──────────────────────────── IO helpers ───────────────────────────────────


def _read_json(path: Path, default: Any = None) -> Any:
    """Read JSON gracefully — missing or corrupt file returns *default*."""
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return default


# ──────────────────────────── pure helpers ─────────────────────────────────


def _get_best_apy(adapter: dict) -> Optional[float]:
    """
    Return the best APY (float) for an adapter, preferring USDC on any chain.
    Returns None when no numeric APY is found.
    """
    if not isinstance(adapter, dict):
        return None

    # Flat fields take priority (already resolved)
    for key in ("apy_pct", "apy"):
        v = adapter.get(key)
        if isinstance(v, (int, float)):
            return float(v)

    # mock_apy: {chain: {asset: float}}
    mock = adapter.get("mock_apy")
    if not isinstance(mock, dict):
        return None

    best: Optional[float] = None
    # Pass 1 — prefer USDC
    for chain_data in mock.values():
        if not isinstance(chain_data, dict):
            continue
        v = chain_data.get("USDC")
        if isinstance(v, (int, float)):
            candidate = float(v)
            if best is None or candidate > best:
                best = candidate
    if best is not None:
        return best

    # Pass 2 — any asset
    for chain_data in mock.values():
        if not isinstance(chain_data, dict):
            continue
        for v in chain_data.values():
            if isinstance(v, (int, float)):
                return float(v)

    return None


def _compute_health(adapter: dict) -> tuple[str, str]:
    """Return (emoji, label) for protocol health derived from adapter fields."""
    if not isinstance(adapter, dict):
        return "✅", "SAFE"

    status = str(adapter.get("status", "active")).lower()
    risk_score = adapter.get("risk_score")
    write_state = str(adapter.get("write_state", "")).lower()

    if status == "suspended":
        return "🚨", "DANGER"
    if status == "research":
        return "🔬", "RESEARCH"
    if status == "monitoring":
        return "⚠️", "MONITOR"

    if isinstance(risk_score, (int, float)):
        if float(risk_score) >= 0.6:
            return "⚠️", "CAUTION"
        if float(risk_score) >= 0.4:
            return "⚠️", "CAUTION"

    _ = write_state  # write_state alone doesn't downgrade health in paper mode
    return "✅", "SAFE"


def _get_tvl_str(adapter: dict) -> Optional[str]:
    """Return a human-readable TVL string, e.g. '$2.8B', '$500M', '$30K'."""
    if not isinstance(adapter, dict):
        return None
    tvl = adapter.get("tvl_usd")
    if not isinstance(tvl, (int, float)):
        return None
    tvl_f = float(tvl)
    if tvl_f >= 1_000_000_000:
        return f"${tvl_f / 1_000_000_000:.1f}B"
    if tvl_f >= 1_000_000:
        return f"${tvl_f / 1_000_000:.0f}M"
    if tvl_f >= 1_000:
        return f"${tvl_f / 1_000:.0f}K"
    return f"${tvl_f:.0f}"


def _format_adapter_line(adapter: dict) -> str:
    """Format one adapter as a single Markdown bullet line."""
    if not isinstance(adapter, dict):
        return "• (invalid adapter entry)"

    name = (
        adapter.get("name")
        or adapter.get("display_name")
        or adapter.get("protocol")
        or adapter.get("protocol_key")
        or adapter.get("adapter_id")
        or "Unknown"
    )

    apy = _get_best_apy(adapter)
    apy_str = f"{apy:.1f}%" if apy is not None else "n/a"

    tvl_str = _get_tvl_str(adapter)
    health_emoji, health_label = _compute_health(adapter)

    parts: list[str] = [f"APY: {apy_str}"]

    if tvl_str:
        parts.append(f"TVL: {tvl_str}")

    risk_score = adapter.get("risk_score")
    if isinstance(risk_score, (int, float)):
        parts.append(f"Risk: {float(risk_score):.2f}")

    # Show write state only when it diverges from the paper-mode default
    write_state = adapter.get("write_state")
    if write_state and str(write_state).upper() not in ("BLOCKED", ""):
        parts.append(f"State: {write_state}")

    if adapter.get("quick_win"):
        bps = adapter.get("bps_gain", 0)
        parts.append(f"+{bps}bps")

    gsm = adapter.get("gsm_hours")
    if isinstance(gsm, (int, float)):
        parts.append(f"GSM: {int(gsm)}h/48h ⏳")

    health_str = f"{health_emoji} {health_label}"
    parts.append(health_str)

    return f"• *{name}* — " + " | ".join(parts)


def _group_by_tier(adapters: list[dict]) -> dict[str, list[dict]]:
    """Group adapter dicts by tier string."""
    groups: dict[str, list[dict]] = {}
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        tier = str(adapter.get("tier", "T2"))
        groups.setdefault(tier, []).append(adapter)
    return groups


def _get_all_adapters(data: dict) -> list[dict]:
    """
    Extract all unique adapter dicts from the combined data blob.

    Primary source: data['adapters'] list (structured entries with mock_apy).
    Supplemental: top-level dict keys that look like flat adapter entries
    (must have 'tier' or 'apy'/'apy_pct' and not be a known metadata key).
    Deduplicates by protocol_key / adapter_id.
    """
    if not isinstance(data, dict):
        return []

    seen: set[str] = set()
    result: list[dict] = []

    # Primary: structured adapters list
    for a in data.get("adapters") or []:
        if not isinstance(a, dict):
            continue
        key = (
            a.get("protocol_key")
            or a.get("adapter_id")
            or a.get("name")
            or str(id(a))
        )
        if key not in seen:
            seen.add(key)
            result.append(a)

    # Supplemental: flat top-level adapter blobs
    for k, v in data.items():
        if k in _SKIP_KEYS or not isinstance(v, dict):
            continue
        if "tier" not in v and "apy" not in v and "apy_pct" not in v:
            continue
        key = v.get("adapter_id") or v.get("protocol_key") or k
        if key in seen:
            continue
        seen.add(key)
        result.append(v)

    return result


# ──────────────────────────── public: message formatting ───────────────────


def format_protocols_message(data: dict) -> str:
    """
    Format the /protocols status message from adapter data.

    Parameters
    ----------
    data : dict — typically loaded from data/adapter_status.json with
           positions data merged under key ``'positions_data'``.

    Returns
    -------
    str — Telegram Markdown-compatible message.  May exceed 4096 chars;
          call :func:`split_message` before sending.
    """
    if not isinstance(data, dict):
        data = {}

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    adapters = _get_all_adapters(data)
    total_adapters = len(adapters)
    grouped = _group_by_tier(adapters)

    lines: list[str] = [
        f"📊 *SPA Protocol Status* — {now_str}",
        "",
    ]

    # Tiers in canonical order
    rendered_tiers: set[str] = set()
    for tier in _TIER_ORDER:
        tier_adapters = grouped.get(tier)
        if not tier_adapters:
            continue
        rendered_tiers.add(tier)
        label = _TIER_LABEL.get(tier, tier)
        lines.append(f"*{label}*")
        for adapter in tier_adapters:
            lines.append(_format_adapter_line(adapter))
        lines.append("")

    # Any leftover tiers not in the canonical list
    for tier, tier_adapters in grouped.items():
        if tier in rendered_tiers:
            continue
        lines.append(f"*{tier}*")
        for adapter in tier_adapters:
            lines.append(_format_adapter_line(adapter))
        lines.append("")

    # ── System summary ──────────────────────────────────────────────────
    positions_data = data.get("positions_data") or {}
    if not isinstance(positions_data, dict):
        positions_data = {}

    capital = (
        positions_data.get("capital_usd")
        or data.get("capital_usd")
        or 100_000
    )
    deployed = positions_data.get("deployed_usd")
    cash = positions_data.get("cash_usd")
    positions = positions_data.get("positions") or {}
    active_count = sum(
        1
        for v in positions.values()
        if isinstance(v, (int, float)) and v > 0
    )

    mev = data.get("mev_protection") or {}
    coverage = mev.get("coverage") if isinstance(mev, dict) else None
    cov_pct = (
        coverage.get("coverage_pct")
        if isinstance(coverage, dict)
        else None
    )

    sys_parts: list[str] = [f"Capital: ${float(capital):,.0f}"]
    if isinstance(deployed, (int, float)):
        sys_parts.append(f"Deployed: ${float(deployed):,.0f}")
    if isinstance(cash, (int, float)):
        sys_parts.append(f"Cash: ${float(cash):,.0f}")
    sys_parts.append(f"Total adapters: {total_adapters}")
    if active_count:
        sys_parts.append(f"Active positions: {active_count}")
    if isinstance(cov_pct, (int, float)):
        sys_parts.append(f"MEV coverage: {float(cov_pct):.0f}%")

    lines.append("*System*")
    lines.append(" | ".join(sys_parts))

    return "\n".join(lines)


# ──────────────────────────── public: message splitting ────────────────────


def split_message(text: str, max_len: int = _TELEGRAM_MAX_LEN) -> list[str]:
    """
    Split a Telegram message into parts each ≤ *max_len* characters.

    Splits on newlines to avoid breaking mid-line.  A single line that
    itself exceeds *max_len* is hard-split at the character boundary.

    Parameters
    ----------
    text    : the full message string.
    max_len : maximum chars per chunk (default: 4096).

    Returns
    -------
    list[str] — one or more chunks, each ≤ max_len chars.
    """
    if not text:
        return [text]
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in text.split("\n"):
        line_cost = len(line) + 1  # +1 for the joining newline

        if line_cost > max_len:
            # Flush current buffer first
            if current_lines:
                chunks.append("\n".join(current_lines))
                current_lines = []
                current_len = 0
            # Hard-split the overlong line
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
            continue

        if current_len + line_cost > max_len and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0

        current_lines.append(line)
        current_len += line_cost

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks or [text[:max_len]]


# ──────────────────────────── public: data loading ─────────────────────────


def load_adapter_data(data_dir: Optional[Path] = None) -> dict:
    """
    Load and merge ``adapter_status.json`` and ``current_positions.json``.

    The positions dict is stored under key ``'positions_data'`` in the
    returned dict.  Never raises — missing/corrupt files degrade gracefully.
    """
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    data_dir = Path(data_dir)

    adapter_data = _read_json(data_dir / "adapter_status.json", default={})
    if not isinstance(adapter_data, dict):
        adapter_data = {}

    positions_data = _read_json(data_dir / "current_positions.json", default={})
    if not isinstance(positions_data, dict):
        positions_data = {}

    adapter_data["positions_data"] = positions_data
    return adapter_data


# ──────────────────────────── credentials ──────────────────────────────────


def _get_keychain_secret(key: str) -> str:
    """Read a secret from macOS Keychain via the `security` CLI."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", key, "-w"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ConfigError(
            key,
            f"Keychain lookup failed: {result.stderr.strip()}",
        )
    return result.stdout.strip()


def _resolve_credentials(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> tuple[str, str]:
    """
    Resolve Telegram credentials.

    Fallback chain (per credential):
        1. Explicit argument
        2. Environment variables (TELEGRAM_BOT_TOKEN_SPA or TELEGRAM_BOT_TOKEN,
           TELEGRAM_CHAT_ID_SPA or TELEGRAM_CHAT_ID)
        3. macOS Keychain (TELEGRAM_BOT_TOKEN_SPA / TELEGRAM_CHAT_ID_SPA)
    """
    token = bot_token
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN_SPA") or os.environ.get(
            "TELEGRAM_BOT_TOKEN"
        )
    if not token:
        token = _get_keychain_secret("TELEGRAM_BOT_TOKEN_SPA")

    cid = chat_id
    if not cid:
        cid = os.environ.get("TELEGRAM_CHAT_ID_SPA") or os.environ.get(
            "TELEGRAM_CHAT_ID"
        )
    if not cid:
        cid = _get_keychain_secret("TELEGRAM_CHAT_ID_SPA")

    return token, cid  # type: ignore[return-value]


# ──────────────────────────── HTTP transport ───────────────────────────────


def _post_message(token: str, chat_id: str, text: str) -> dict:
    """RETIRED as a Telegram push (Phase-1 Telegram rebuild).

    The /protocols report is on-demand (a bot pull-view), not an unsolicited
    push. This no longer routes to the transport; the composed text is dropped
    to the digest queue. The ``token``/``chat_id`` args are kept for signature
    compatibility. Returns an API-shaped ``{"ok": False}``. Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy._enqueue_digest(
            push_policy._tg_dir(),
            {
                "ts": push_policy._now_iso(),
                "event_key": "protocols_report",
                "severity": "INFO",
                "title": "Protocols report",
                "body": (text or "")[:500],
                "reason": "protocols_reporter_retired_push",
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": False}


# ──────────────────────────── public: send ─────────────────────────────────


def send_protocols_report(
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    *,
    data_dir: Optional[Path] = None,
    data: Optional[dict] = None,
) -> dict:
    """
    Load adapter data, format the /protocols message, and send via Telegram.

    Parameters
    ----------
    chat_id   : Telegram chat ID. Falls back to env var → Keychain.
    bot_token : Telegram bot token. Falls back to env var → Keychain.
    data_dir  : Path to the ``data/`` directory (default: ``<repo>/data``).
    data      : Pre-loaded data dict. When provided, skips file loading
                (useful for tests and offline formatting).

    Returns
    -------
    dict with:
        ok        — True when all chunks sent without error.
        sent      — number of message parts successfully sent.
        responses — list of Telegram API response dicts.
        errors    — list of error strings (empty on success).
    """
    token, cid = _resolve_credentials(bot_token, chat_id)

    if data is None:
        data = load_adapter_data(data_dir)

    message = format_protocols_message(data)
    parts = split_message(message)

    responses: list[dict] = []
    errors: list[str] = []

    for part in parts:
        try:
            resp = _post_message(token, cid, part)
            responses.append(resp)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            errors.append(str(exc))
            log.error("Telegram send failed: %s", exc)

    return {
        "ok": len(errors) == 0,
        "sent": len(responses),
        "responses": responses,
        "errors": errors,
    }


# ──────────────────────────── CLI ──────────────────────────────────────────


def main() -> None:
    """CLI: print (and optionally send) the /protocols report."""
    import argparse

    parser = argparse.ArgumentParser(
        description="SPA /protocols Telegram reporter (MP-659)"
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send to Telegram (default: print only)",
    )
    parser.add_argument("--chat-id", default=None, help="Override Telegram chat ID")
    parser.add_argument(
        "--bot-token", default=None, help="Override Telegram bot token"
    )
    parser.add_argument(
        "--data-dir", default=None, help="Path to data/ directory"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else None
    data = load_adapter_data(data_dir)
    message = format_protocols_message(data)

    print(message)
    parts = split_message(message)
    print(f"\n[{len(message)} chars, {len(parts)} part(s)]")

    if args.send:
        result = send_protocols_report(
            chat_id=args.chat_id,
            bot_token=args.bot_token,
            data_dir=data_dir,
            data=data,
        )
        if result["ok"]:
            print(f"✅ Sent {result['sent']} part(s) to Telegram.")
        else:
            print(f"❌ Errors: {result['errors']}")


if __name__ == "__main__":
    main()
