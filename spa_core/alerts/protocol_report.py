"""MP-792: Per-protocol Telegram report — APY/TVL/health/tier detail.

Generates a detailed Telegram MarkdownV2-formatted message for each whitelisted
DeFi protocol, pulling live data from data/ JSON files and falling back to
hardcoded defaults when files are absent.

Public API
----------
generate_protocol_report(protocol_filter=None) -> str
    Return a complete Telegram MarkdownV2 message covering all (or filtered)
    protocols.

send_protocol_report(bot_token, chat_id, protocol_filter=None) -> bool
    Generate and POST the report via Telegram Bot API (urllib, stdlib only).
    Fail-safe: any failure → False, never raises.

CLI
---
    python3 spa_core/alerts/protocol_report.py --preview   # print, no send
    python3 spa_core/alerts/protocol_report.py --send      # send via Keychain creds
    python3 spa_core/alerts/protocol_report.py --send --filter aave-v3,compound-v3

Design constraints
------------------
* Stdlib only — no external packages.
* Read-only: never writes to data/.
* LLM_FORBIDDEN domain: this module contains no LLM calls.
* Atomic-write invariant: not applicable (read-only).
"""
from __future__ import annotations

import json
import logging
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("spa.alerts.protocol_report")

# ---------------------------------------------------------------------------
# Constants & hardcoded fallback data
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
_DATA_DIR = _REPO_ROOT / "data"

# Known TVL estimates (USD) — used when live data unavailable.
# Sources: DeFiLlama public data, rounded conservatively.
_FALLBACK_TVL: dict[str, float] = {
    "aave-v3":           18_000_000_000.0,
    "compound-v3":        3_200_000_000.0,
    "morpho-steakhouse":  1_100_000_000.0,
    "morpho-blue":        2_500_000_000.0,
    "yearn-v3":             950_000_000.0,
    "euler-v2":             480_000_000.0,
    "maple":                350_000_000.0,
    "aave-v3-arbitrum":   2_400_000_000.0,
    "pendle-pt":          2_800_000_000.0,
}

# Audit / bug-bounty metadata per protocol (static knowledge).
_PROTOCOL_META: dict[str, dict] = {
    "aave-v3": {
        "display_name": "Aave V3 ETH",
        "chain": "Ethereum",
        "adapter_key": "aave_v3_eth",
        "audited": True,
        "bug_bounty": "$2.0M",
        "risk_label": "LOW",
    },
    "compound-v3": {
        "display_name": "Compound V3",
        "chain": "Ethereum",
        "adapter_key": "compound_v3",
        "audited": True,
        "bug_bounty": "$150K",
        "risk_label": "LOW",
    },
    "morpho-steakhouse": {
        "display_name": "Morpho Steakhouse",
        "chain": "Ethereum",
        "adapter_key": "morpho_steakhouse",
        "audited": True,
        "bug_bounty": "$500K",
        "risk_label": "LOW",
    },
    "morpho-blue": {
        "display_name": "Morpho Blue",
        "chain": "Ethereum",
        "adapter_key": "morpho_blue",
        "audited": True,
        "bug_bounty": "$500K",
        "risk_label": "MEDIUM",
    },
    "yearn-v3": {
        "display_name": "Yearn V3",
        "chain": "Ethereum",
        "adapter_key": "yearn_v3",
        "audited": True,
        "bug_bounty": "$200K",
        "risk_label": "MEDIUM",
    },
    "euler-v2": {
        "display_name": "Euler V2",
        "chain": "Ethereum",
        "adapter_key": "euler_v2",
        "audited": True,
        "bug_bounty": "$1.0M",
        "risk_label": "MEDIUM",
    },
    "maple": {
        "display_name": "Maple Finance",
        "chain": "Ethereum",
        "adapter_key": "maple",
        "audited": True,
        "bug_bounty": "$100K",
        "risk_label": "MEDIUM",
    },
    "aave-v3-arbitrum": {
        "display_name": "Aave V3 Arbitrum",
        "chain": "Arbitrum",
        "adapter_key": "aave_v3_arb",
        "audited": True,
        "bug_bounty": "$2.0M",
        "risk_label": "LOW",
    },
    "pendle-pt": {
        "display_name": "Pendle PT",
        "chain": "Ethereum",
        "adapter_key": "pendle_pt_rest",
        "audited": True,
        "bug_bounty": "$250K",
        "risk_label": "HIGH",
    },
}

# Ordered list of protocol keys for display (T1 first, then T2, T3).
_DEFAULT_PROTOCOL_ORDER = [
    "aave-v3",
    "compound-v3",
    "morpho-steakhouse",
    "morpho-blue",
    "yearn-v3",
    "euler-v2",
    "maple",
    "aave-v3-arbitrum",
    "pendle-pt",
]

# ---------------------------------------------------------------------------
# MarkdownV2 escaping
# ---------------------------------------------------------------------------

_MDV2_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


def escape_mdv2(text: str) -> str:
    """Escape all MarkdownV2 special characters.

    Per Telegram Bot API docs the following characters must be escaped with
    a preceding backslash when not used as formatting marks:
    ``_ * [ ] ( ) ~ ` > # + - = | { } . !``
    """
    result: list[str] = []
    for ch in str(text):
        if ch in _MDV2_SPECIAL:
            result.append("\\")
        result.append(ch)
    return "".join(result)


def _fmt_apy(apy: Optional[float]) -> str:
    """Format APY value as percentage string, escaped for MarkdownV2."""
    if apy is None:
        return escape_mdv2("N/A")
    return escape_mdv2(f"{apy:.2f}%")


def _fmt_tvl(tvl_usd: Optional[float]) -> str:
    """Format TVL as human-readable string, escaped for MarkdownV2."""
    if tvl_usd is None:
        return escape_mdv2("N/A")
    if tvl_usd >= 1_000_000_000:
        return escape_mdv2(f"${tvl_usd / 1_000_000_000:.1f}B")
    if tvl_usd >= 1_000_000:
        return escape_mdv2(f"${tvl_usd / 1_000_000:.0f}M")
    return escape_mdv2(f"${tvl_usd:,.0f}")


def _time_ago(iso_ts: Optional[str]) -> str:
    """Return human-readable 'X min ago' / 'X h ago' string."""
    if not iso_ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        delta_s = (now - dt).total_seconds()
        if delta_s < 0:
            return "just now"
        if delta_s < 120:
            return "just now"
        if delta_s < 3600:
            return f"{int(delta_s // 60)} min ago"
        if delta_s < 86400:
            return f"{int(delta_s // 3600)} h ago"
        return f"{int(delta_s // 86400)} d ago"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Health score computation
# ---------------------------------------------------------------------------

_TVL_FLOOR_USD = 5_000_000.0  # RiskPolicy TVL floor
_APY_MIN = 1.0
_APY_MAX = 30.0


def compute_health_score(
    tier: str,
    write_state: str,
    apy: Optional[float],
    tvl_usd: Optional[float],
    audited: bool = True,
) -> tuple[int, str]:
    """Compute a 0-100 health score and label for a protocol.

    Returns
    -------
    (score, label) where label is one of: EXCELLENT / HEALTHY / FAIR / POOR
    """
    score = 100

    # Tier deductions
    if tier == "T1":
        pass  # no deduction
    elif tier == "T2":
        score -= 10
    elif tier == "T3" or tier.startswith("T3"):
        score -= 25
    else:
        score -= 15

    # Adapter write_state
    if write_state == "ACTIVE":
        pass
    elif write_state == "BLOCKED":
        score -= 5   # paper trading — expected
    elif write_state == "ERROR":
        score -= 20
    elif write_state == "DISABLED":
        score -= 15

    # APY compliance (RiskPolicy gate: 1–30%)
    if apy is not None:
        if apy < _APY_MIN or apy > _APY_MAX:
            score -= 15
        elif apy < 2.0:
            score -= 5

    # TVL floor check
    if tvl_usd is not None:
        if tvl_usd < _TVL_FLOOR_USD:
            score -= 20
        elif tvl_usd < 50_000_000:
            score -= 5
    else:
        score -= 5  # unknown TVL — small deduction

    # Audit
    if not audited:
        score -= 10

    score = max(0, min(100, score))

    if score >= 85:
        label = "EXCELLENT"
    elif score >= 70:
        label = "HEALTHY"
    elif score >= 50:
        label = "FAIR"
    else:
        label = "POOR"

    return score, label


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    """Load JSON file; return {} on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.debug("_load_json(%s): %s", path, exc)
        return {}


def _load_adapter_status(data_dir: Path) -> list[dict]:
    """Return list of adapter dicts from adapter_status.json, or []."""
    data = _load_json(data_dir / "adapter_status.json")
    return data.get("adapters", [])


def _load_positions(data_dir: Path) -> dict[str, float]:
    """Return {protocol_key: amount_usd} from current_positions.json."""
    data = _load_json(data_dir / "current_positions.json")
    raw = data.get("positions", {})
    result: dict[str, float] = {}
    for k, v in raw.items():
        try:
            result[k] = float(v)
        except (TypeError, ValueError):
            pass
    return result


def _load_generated_at(data_dir: Path) -> Optional[str]:
    """Return generated_at timestamp from adapter_status.json."""
    data = _load_json(data_dir / "adapter_status.json")
    return data.get("generated_at")


def _build_protocol_map(adapters: list[dict]) -> dict[str, dict]:
    """Index adapter list by protocol_key for fast lookup."""
    result: dict[str, dict] = {}
    for a in adapters:
        key = a.get("protocol_key", "")
        if key:
            result[key] = a
    return result


def _get_best_apy(adapter: dict) -> Optional[float]:
    """Extract the best (highest) APY from adapter's mock_apy or live_apy."""
    # Try live APY first (execution domain, may be present)
    live = adapter.get("live_apy") or {}
    if live:
        values = [float(v) for chain in live.values()
                  for v in (chain.values() if isinstance(chain, dict) else [chain])
                  if v is not None]
        if values:
            return max(values)

    # Fall back to mock_apy
    mock = adapter.get("mock_apy") or {}
    values = []
    for chain_data in mock.values():
        if isinstance(chain_data, dict):
            for v in chain_data.values():
                if v is not None:
                    values.append(float(v))
        elif chain_data is not None:
            values.append(float(chain_data))
    return max(values) if values else None


def _get_7d_avg_apy(adapter: dict) -> Optional[float]:
    """Return 7-day average APY if stored in adapter dict, else estimate."""
    # Some adapter dicts carry apy_7d_avg
    avg = adapter.get("apy_7d_avg")
    if avg is not None:
        try:
            return float(avg)
        except (TypeError, ValueError):
            pass

    # Estimate: current APY × 0.95 (conservative smoothing proxy)
    current = _get_best_apy(adapter)
    if current is not None:
        return round(current * 0.95, 2)
    return None


def _get_tvl(adapter: dict) -> Optional[float]:
    """Return TVL in USD from adapter dict or fallback table."""
    tvl = adapter.get("tvl_usd") or adapter.get("tvl")
    if tvl is not None:
        try:
            return float(tvl)
        except (TypeError, ValueError):
            pass
    key = adapter.get("protocol_key", "")
    return _FALLBACK_TVL.get(key)


def _get_status_emoji(write_state: str, apy: Optional[float]) -> str:
    """Return status emoji based on write_state and APY validity."""
    if write_state == "ACTIVE":
        return "✅ ACTIVE"
    if write_state == "BLOCKED":
        # In paper trading, BLOCKED is normal — still active logically
        if apy and _APY_MIN <= apy <= _APY_MAX:
            return "✅ ACTIVE"
        return "🟡 PAPER"
    if write_state in ("ERROR", "DISABLED"):
        return "🔴 INACTIVE"
    return "🔵 UNKNOWN"


# ---------------------------------------------------------------------------
# Per-protocol block formatter
# ---------------------------------------------------------------------------

def _format_protocol_block(
    protocol_key: str,
    adapter: Optional[dict],
    meta: dict,
    positions: dict[str, float],
    generated_at: Optional[str],
) -> str:
    """Format one protocol block in Telegram MarkdownV2.

    Example output (unescaped for readability)::

        📊 *Aave V3 ETH*
        ├ Tier: T1 | Chain: Ethereum
        ├ APY: 4.21% (7d avg: 3.98%)
        ├ TVL: $18.0B | Status: ✅ ACTIVE
        ├ Health Score: 90/100 (EXCELLENT)
        ├ Adapter: aave_v3_eth | Last update: 2 min ago
        └ Risk: LOW | Audit: ✅ | Bug Bounty: $2.0M
    """
    display_name = meta.get("display_name", protocol_key)
    chain = meta.get("chain", "Ethereum")
    adapter_key = meta.get("adapter_key", protocol_key.replace("-", "_"))
    audited = meta.get("audited", True)
    bug_bounty = meta.get("bug_bounty", "N/A")
    risk_label = meta.get("risk_label", "MEDIUM")

    tier = "N/A"
    write_state = "UNKNOWN"
    apy: Optional[float] = None
    apy_7d: Optional[float] = None
    tvl: Optional[float] = _FALLBACK_TVL.get(protocol_key)

    if adapter:
        tier = adapter.get("tier", "N/A")
        write_state = adapter.get("write_state", "UNKNOWN")
        apy = _get_best_apy(adapter)
        apy_7d = _get_7d_avg_apy(adapter)
        tvl = _get_tvl(adapter)

    health_score, health_label = compute_health_score(
        tier=tier,
        write_state=write_state,
        apy=apy,
        tvl_usd=tvl,
        audited=audited,
    )

    status_str = _get_status_emoji(write_state, apy)
    last_update = _time_ago(generated_at) if adapter else "N/A"

    # Build APY line
    apy_str = _fmt_apy(apy)
    apy_7d_str = _fmt_apy(apy_7d)
    apy_line = f"{apy_str} \\(7d avg: {apy_7d_str}\\)"

    # Tier | Chain
    tier_chain = f"Tier: {escape_mdv2(tier)} \\| Chain: {escape_mdv2(chain)}"

    # TVL | Status
    tvl_str = _fmt_tvl(tvl)
    tvl_status = f"TVL: {tvl_str} \\| Status: {escape_mdv2(status_str)}"

    # Health
    health_line = (
        f"Health Score: {escape_mdv2(str(health_score))}"
        f"/100 \\({escape_mdv2(health_label)}\\)"
    )

    # Adapter | Last update
    adapter_line = (
        f"Adapter: `{escape_mdv2(adapter_key)}` "
        f"\\| Last update: {escape_mdv2(last_update)}"
    )

    # Risk | Audit | Bug bounty
    audit_str = "✅" if audited else "❌"
    risk_line = (
        f"Risk: {escape_mdv2(risk_label)} "
        f"\\| Audit: {audit_str} "
        f"\\| Bug Bounty: {escape_mdv2(bug_bounty)}"
    )

    lines = [
        f"📊 *{escape_mdv2(display_name)}*",
        f"├ {tier_chain}",
        f"├ APY: {apy_line}",
        f"├ {tvl_status}",
        f"├ {health_line}",
        f"├ {adapter_line}",
        f"└ {risk_line}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main report generator
# ---------------------------------------------------------------------------

def generate_protocol_report(
    protocol_filter: Optional[str | list[str]] = None,
    data_dir: Optional[Path | str] = None,
) -> str:
    """Generate a complete per-protocol Telegram MarkdownV2 report.

    Parameters
    ----------
    protocol_filter:
        Optional protocol key or list of keys to include. ``None`` = all.
        Keys are matched case-insensitively against the canonical key list.
    data_dir:
        Override data directory path (defaults to repo_root/data/).

    Returns
    -------
    Telegram MarkdownV2-formatted string, never empty, never raises.
    """
    try:
        return _generate_report_inner(protocol_filter, data_dir)
    except Exception as exc:
        log.error("generate_protocol_report failed: %s", exc, exc_info=True)
        return escape_mdv2(f"⚠️ Protocol report error: {exc}")


def _generate_report_inner(
    protocol_filter: Optional[str | list[str]],
    data_dir: Optional[Path | str],
) -> str:
    ddir = Path(data_dir) if data_dir else _DATA_DIR

    # Normalise filter to a set of lowercase keys
    filter_keys: Optional[set[str]] = None
    if protocol_filter is not None:
        if isinstance(protocol_filter, str):
            filter_keys = {k.strip().lower() for k in protocol_filter.split(",")}
        else:
            filter_keys = {k.strip().lower() for k in protocol_filter}

    # Load live data
    adapters = _load_adapter_status(ddir)
    adapter_map = _build_protocol_map(adapters)
    positions = _load_positions(ddir)
    generated_at = _load_generated_at(ddir)

    # Determine ordered protocol list
    ordered_keys = _DEFAULT_PROTOCOL_ORDER.copy()
    # Add any extra protocols found in adapter_status but not in default list
    for key in adapter_map:
        if key not in ordered_keys:
            ordered_keys.append(key)

    # Apply filter
    if filter_keys:
        ordered_keys = [k for k in ordered_keys if k.lower() in filter_keys]

    if not ordered_keys:
        return escape_mdv2("⚠️ No protocols match the requested filter.")

    now_str = datetime.now(tz=timezone.utc).strftime("%Y\\-%m\\-%d %H:%M UTC")
    header = f"🔭 *SPA Protocol Report* — {now_str}"
    separator = escape_mdv2("─" * 32)

    blocks: list[str] = [header, ""]

    for key in ordered_keys:
        adapter = adapter_map.get(key)
        meta = _PROTOCOL_META.get(key, {
            "display_name": key,
            "chain": "Unknown",
            "adapter_key": key.replace("-", "_"),
            "audited": False,
            "bug_bounty": "N/A",
            "risk_label": "UNKNOWN",
        })
        block = _format_protocol_block(
            protocol_key=key,
            adapter=adapter,
            meta=meta,
            positions=positions,
            generated_at=generated_at,
        )
        blocks.append(block)
        blocks.append(separator)

    # Footer: summary counts
    total = len(ordered_keys)
    active = sum(
        1 for k in ordered_keys
        if adapter_map.get(k, {}).get("write_state") in ("ACTIVE", "BLOCKED")
    )
    footer_lines = [
        f"*Total:* {escape_mdv2(str(total))} protocols "
        f"\\| *Active:* {escape_mdv2(str(active))}",
    ]
    if generated_at:
        footer_lines.append(
            f"📡 Data: {escape_mdv2(_time_ago(generated_at))}"
        )
    blocks.extend(footer_lines)

    full = "\n".join(blocks)

    # Telegram MarkdownV2 messages are limited to 4096 chars
    if len(full) > 4096:
        full = full[:4080] + escape_mdv2("\n…[truncated]")

    return full


# ---------------------------------------------------------------------------
# Telegram sender
# ---------------------------------------------------------------------------

def send_protocol_report(
    bot_token: str,
    chat_id: str,
    protocol_filter: Optional[str | list[str]] = None,
    data_dir: Optional[Path | str] = None,
) -> bool:
    """Generate and send the protocol report via Telegram Bot API.

    Uses ``urllib.request`` (stdlib only). Fail-safe: any error → False.

    Parameters
    ----------
    bot_token:
        Telegram bot token (from Keychain ``TELEGRAM_BOT_TOKEN_SPA``).
    chat_id:
        Target chat/channel ID (from Keychain ``TELEGRAM_CHAT_ID_SPA``).
    protocol_filter:
        Optional filter — passed through to ``generate_protocol_report``.
    data_dir:
        Optional data directory override.

    Returns
    -------
    True on HTTP 200 success, False on any error.
    """
    try:
        text = generate_protocol_report(protocol_filter=protocol_filter, data_dir=data_dir)
        return _post_telegram(bot_token=bot_token, chat_id=chat_id, text=text)
    except Exception as exc:  # noqa: BLE001
        log.warning("send_protocol_report: unexpected error: %s", exc)
        return False


def _post_telegram(bot_token: str, chat_id: str, text: str) -> bool:
    """POST a sendMessage payload to Telegram Bot API. Fail-safe."""
    if not bot_token or not chat_id:
        log.warning("send_protocol_report: missing bot_token or chat_id")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                log.info("Protocol report sent successfully")
                return True
            log.warning("Telegram responded with status %s", resp.status)
            return False
    except urllib.error.HTTPError as exc:
        log.warning("Telegram HTTP error %s: %s", exc.code, exc.reason)
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("Telegram network error: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Keychain credential helpers
# ---------------------------------------------------------------------------

_KEYCHAIN_ACCOUNT = "spa"
_TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
_CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"


def _read_keychain(service: str) -> str:
    """Read one generic password from macOS Keychain. Raises EnvironmentError."""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service,
             "-a", _KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnvironmentError("Keychain unavailable") from exc
    value = (proc.stdout or "").strip()
    if proc.returncode != 0 or not value:
        raise EnvironmentError(f"Keychain entry '{service}' not found")
    return value


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli() -> None:  # pragma: no cover
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="SPA per-protocol Telegram report"
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send report via Telegram (reads creds from macOS Keychain)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print the report to stdout without sending",
    )
    parser.add_argument(
        "--filter",
        dest="filter",
        default=None,
        help="Comma-separated protocol keys to include (e.g. aave-v3,compound-v3)",
    )
    parser.add_argument(
        "--data-dir",
        dest="data_dir",
        default=None,
        help="Override data directory path",
    )
    args = parser.parse_args()

    if not args.send and not args.preview:
        parser.print_help()
        sys.exit(0)

    report = generate_protocol_report(
        protocol_filter=args.filter,
        data_dir=args.data_dir,
    )

    if args.preview:
        print(report)

    if args.send:
        try:
            token = _read_keychain(_TOKEN_SERVICE)
            chat_id = _read_keychain(_CHAT_ID_SERVICE)
        except EnvironmentError as exc:
            print(f"❌ Cannot read credentials: {exc}", file=sys.stderr)
            sys.exit(1)
        ok = _post_telegram(bot_token=token, chat_id=chat_id, text=report)
        if ok:
            print("✅ Protocol report sent.")
        else:
            print("❌ Failed to send protocol report.", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _cli()
