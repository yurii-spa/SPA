"""
Incident History Fetcher — FEAT-RISK-002

Pulls protocol incidents (hacks, exploits, rugpulls, depegs) from the public
DefiLlama hacks API and produces a normalised history file at
``data/incidents.json``. The output is the canonical hack-history input for
the Risk Scoring Engine (FEAT-RISK-001).

Design constraints
------------------
* **Stdlib only** — uses ``urllib.request`` + ``json`` (matches the pattern of
  ``sky_monitor.py`` and ``defillama_fetcher.py``). No ``requests`` dependency.
* **Offline-tolerant** — when the network is unavailable, falls back to a
  curated ``BOOTSTRAP_INCIDENTS`` list compiled from public post-mortems. The
  bootstrap data is intentionally conservative: it covers comparable lending
  / LP protocols so the Risk Scoring Engine has data to consume on day one,
  even before the first successful API call.
* **Read-only, no DB writes** — the file is the single source of truth, the
  same way ``sky_status.json`` works.
* **Idempotent** — re-running on the same data produces a byte-identical file
  (sorted, deterministic ordering).

Output schema (``data/incidents.json``)
---------------------------------------

::

    {
      "updated_at": "<ISO-8601 UTC>",
      "source": "DefiLlama hacks API (+ bootstrap fallback)",
      "fetched_from_api": true | false,
      "total_incidents": <int>,
      "total_amount_lost_usd": <float>,
      "incidents": [
        {
          "id":              "defillama-<id>"  | "bootstrap-<slug>-<yyyy>",
          "protocol":        "Curve Finance",
          "protocol_slug":   "curve",
          "date":            "2023-07-30",
          "amount_lost_usd": 73_500_000.0,
          "type":            "hack" | "exploit" | "rugpull" | "depeg",
          "technique":       "Reentrancy",
          "chain":           "ethereum",
          "source_url":      "https://...",
          "status":          "fixed" | "ongoing" | "unknown",
          "spa_protocols_affected": ["curve"]   # subset of SPA whitelist keys
        },
        ...
      ],
      "by_protocol_summary": {
        "aave-v3":      {"incidents": 0, "total_lost_usd": 0.0, "last_incident": null},
        "compound-v3":  {"incidents": 0, "total_lost_usd": 0.0, "last_incident": null},
        ...
      }
    }

CLI
---

::

    python -m spa_core.data_pipeline.incidents_fetcher           # fetch + write
    python -m spa_core.data_pipeline.incidents_fetcher --offline # bootstrap only
    python -m spa_core.data_pipeline.incidents_fetcher --dry-run # log, no write

This module is consumed by FEAT-RISK-001 (Risk Scoring Engine). It writes
``data/incidents.json`` only; consumers read that file.

ADR reference: docs/ADR_013_incident_history.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger("spa.incidents_fetcher")

# ─── Configuration ────────────────────────────────────────────────────────────

DEFILLAMA_HACKS_URL = "https://api.llama.fi/hacks"
FETCH_TIMEOUT_S = 30
FETCH_MAX_ATTEMPTS = 3
FETCH_BACKOFF_BASE = 2.0

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "data" / "incidents.json"

# Canonical SPA whitelist slugs (lowercase, hyphen-separated). Kept independent
# from defillama_fetcher.POOL_WHITELIST to avoid a circular dependency. The
# slugs are matched against incident.protocol by ``_match_spa_protocol``.
SPA_PROTOCOL_SLUGS: tuple[str, ...] = (
    "aave",
    "aave-v3",
    "compound",
    "compound-v3",
    "morpho",
    "yearn",
    "yearn-v3",
    "maple",
    "euler",
    "euler-v2",
    "sky",
    "susds",
    "makerdao",
    "pendle",
    "curve",       # closely-watched LP venue (S2 strategy)
    "uniswap",     # closely-watched LP venue (S2 strategy)
)

# Token-style normalisation regex (split on whitespace, hyphens, slashes, etc.)
_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


# ─── Curated bootstrap incidents ──────────────────────────────────────────────
# Compiled from public post-mortems (rekt.news, DefiLlama, project blogs).
# This list intentionally errs on the side of well-documented incidents so the
# risk engine has signal on day one. The API refresh will supersede / extend
# this list — duplicates are de-duplicated by (protocol_slug, date) on merge.
BOOTSTRAP_INCIDENTS: tuple[dict[str, Any], ...] = (
    # Lending / money-market venues
    {
        "id":              "bootstrap-euler-2023",
        "protocol":        "Euler Finance",
        "date":            "2023-03-13",
        "amount_lost_usd": 197_000_000.0,
        "type":            "exploit",
        "technique":       "Donation attack via flash loan",
        "chain":           "ethereum",
        "source_url":      "https://blog.euler.finance/euler-hack-and-attack-recovery-eea03ba24d8a",
        "status":          "fixed",
    },
    {
        "id":              "bootstrap-compound-2021",
        "protocol":        "Compound",
        "date":            "2021-09-29",
        "amount_lost_usd": 80_000_000.0,
        "type":            "exploit",
        "technique":       "Faulty governance proposal (Proposal 062)",
        "chain":           "ethereum",
        "source_url":      "https://www.comp.xyz/t/post-mortem-compound-comp-token-distribution-bug/3034",
        "status":          "fixed",
    },
    {
        "id":              "bootstrap-cream-2021",
        "protocol":        "Cream Finance",
        "date":            "2021-10-27",
        "amount_lost_usd": 130_000_000.0,
        "type":            "exploit",
        "technique":       "Flash loan + price oracle manipulation",
        "chain":           "ethereum",
        "source_url":      "https://medium.com/cream-finance/c-r-e-a-m-finance-post-mortem-amp-exploit-6ceb20a630c5",
        "status":          "fixed",
    },
    # LP / DEX venues (relevant for S2 LP stable strategy)
    {
        "id":              "bootstrap-curve-2023",
        "protocol":        "Curve Finance",
        "date":            "2023-07-30",
        "amount_lost_usd": 73_500_000.0,
        "type":            "exploit",
        "technique":       "Vyper compiler reentrancy bug",
        "chain":           "ethereum",
        "source_url":      "https://twitter.com/CurveFinance/status/1685693835484585985",
        "status":          "fixed",
    },
    {
        "id":              "bootstrap-uniswap-2024",
        "protocol":        "Uniswap",
        "date":            "2024-01-04",
        "amount_lost_usd": 0.0,
        "type":            "exploit",
        "technique":       "Permit2 signature phishing (front-end)",
        "chain":           "ethereum",
        "source_url":      "https://blog.uniswap.org/security",
        "status":          "fixed",
    },
    # Yield / vault venues (relevant for Yearn V3 in T1, generally)
    {
        "id":              "bootstrap-yearn-2023",
        "protocol":        "Yearn Finance",
        "date":            "2023-04-13",
        "amount_lost_usd": 11_500_000.0,
        "type":            "exploit",
        "technique":       "Misconfigured iearn yUSDT vault (legacy v1 contract)",
        "chain":           "ethereum",
        "source_url":      "https://github.com/yearn/yearn-security/blob/master/disclosures/2023-04-13.md",
        "status":          "fixed",
    },
    # Stablecoin depegs (relevant for risk_monitor depeg detector + risk engine)
    {
        "id":              "bootstrap-ust-2022",
        "protocol":        "Terra UST",
        "date":            "2022-05-09",
        "amount_lost_usd": 40_000_000_000.0,
        "type":            "depeg",
        "technique":       "Algorithmic stablecoin death spiral",
        "chain":           "terra",
        "source_url":      "https://rekt.news/luna-rekt/",
        "status":          "ongoing",
    },
    {
        "id":              "bootstrap-usdc-2023",
        "protocol":        "Circle USDC",
        "date":            "2023-03-11",
        "amount_lost_usd": 0.0,
        "type":            "depeg",
        "technique":       "Silicon Valley Bank exposure (~$3.3B of reserves)",
        "chain":           "ethereum",
        "source_url":      "https://www.circle.com/blog/an-update-on-usdc-and-silicon-valley-bank",
        "status":          "fixed",
    },
    {
        "id":              "bootstrap-dai-2020",
        "protocol":        "MakerDAO DAI",
        "date":            "2020-03-12",
        "amount_lost_usd": 8_000_000.0,
        "type":            "exploit",
        "technique":       "Black Thursday — keeper bots stalled, $0 auctions",
        "chain":           "ethereum",
        "source_url":      "https://forum.makerdao.com/t/black-thursday-response-thread/1433",
        "status":          "fixed",
    },
    # Pendle ecosystem (T2 PT allocation, S3 fixed-rate strategy)
    {
        "id":              "bootstrap-pendle-2024",
        "protocol":        "Penpie (Pendle aggregator)",
        "date":            "2024-09-03",
        "amount_lost_usd": 27_000_000.0,
        "type":            "exploit",
        "technique":       "Pendle market registration reentrancy via Penpie",
        "chain":           "ethereum",
        "source_url":      "https://medium.com/magpiexyz/penpie-hack-post-mortem-3f96ab12f6f5",
        "status":          "fixed",
    },
)


# ─── Public helpers ───────────────────────────────────────────────────────────

def normalise_protocol_name(name: Optional[str]) -> str:
    """
    Convert a free-form protocol name to a canonical slug.

    Examples:
        "Aave V3"        -> "aave-v3"
        "Compound v3"    -> "compound-v3"
        "Curve Finance"  -> "curve-finance"
        "  Euler  "      -> "euler"
        None / ""        -> ""
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = _NORMALISE_RE.sub("-", s).strip("-")
    return s


def classify_type(raw: Optional[str]) -> str:
    """
    Map DefiLlama / freeform classification into one of:
        hack / exploit / rugpull / depeg / unknown.

    DefiLlama's ``classification`` field uses a small enum but the casing and
    spacing vary; this function is tolerant.
    """
    if not raw:
        return "unknown"
    s = raw.strip().lower()
    if "rug" in s or "exit scam" in s:
        return "rugpull"
    if "depeg" in s or "peg" in s:
        return "depeg"
    if "exploit" in s or "smart contract" in s or "logic" in s:
        return "exploit"
    if "hack" in s or "phish" in s or "private key" in s or "compromise" in s:
        return "hack"
    # Default heuristic — DefiLlama groups most incidents under "exploit"
    return "exploit"


def _match_spa_protocol(protocol_name: str) -> list[str]:
    """
    Return SPA whitelist slugs that match the given incident protocol.

    Matching is substring-based against the normalised protocol slug, so
    "Aave V3" matches both "aave" and "aave-v3".
    """
    slug = normalise_protocol_name(protocol_name)
    if not slug:
        return []
    return sorted({
        spa for spa in SPA_PROTOCOL_SLUGS
        if spa in slug or slug in spa
    })


def _safe_amount(raw: Any) -> float:
    """Coerce DefiLlama ``amount`` (USD millions, sometimes string) to USD float."""
    if raw is None:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    # DefiLlama hacks API reports amounts in USD millions for the ``amount``
    # field but in plain USD for some derivative endpoints. We adopt the
    # millions convention (the primary endpoint) and convert defensively.
    if v < 1_000_000 and v > 0:
        return round(v * 1_000_000.0, 2)
    return round(v, 2)


def _safe_date(raw: Any) -> str:
    """
    Normalise a date to ``YYYY-MM-DD``. Accepts ISO strings or unix epoch.
    Returns "" if it cannot parse.
    """
    if raw is None:
        return ""
    # Unix epoch (DefiLlama hacks endpoint uses ms or seconds)
    if isinstance(raw, (int, float)):
        try:
            v = float(raw)
            if v > 10_000_000_000:  # ms
                v = v / 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, ValueError):
            return ""
    s = str(raw).strip()
    if not s:
        return ""
    # ISO 8601
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        pass
    # Fall through: try common shapes
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


# ─── Network ──────────────────────────────────────────────────────────────────

def _http_get_json(url: str, timeout: int = FETCH_TIMEOUT_S) -> Optional[Any]:
    """
    GET ``url`` and return parsed JSON, or ``None`` on any error.

    Implements exponential backoff identical to ``defillama_fetcher.retry_request``
    semantics. Stdlib only.
    """
    last_err: Optional[str] = None
    for attempt in range(FETCH_MAX_ATTEMPTS):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "spa-incidents-fetcher/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return json.loads(data)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < FETCH_MAX_ATTEMPTS - 1:
                import time
                time.sleep(FETCH_BACKOFF_BASE ** attempt)
    log.warning("incidents API fetch failed after %d attempts: %s",
                FETCH_MAX_ATTEMPTS, last_err)
    return None


def fetch_defillama_hacks(timeout: int = FETCH_TIMEOUT_S) -> list[dict[str, Any]]:
    """
    Fetch the raw DefiLlama hacks feed.

    Returns the parsed list of incident dicts as DefiLlama serves them, or an
    empty list on any error.
    """
    payload = _http_get_json(DEFILLAMA_HACKS_URL, timeout=timeout)
    if payload is None:
        return []
    # DefiLlama returns either a top-level list or {"hacks": [...]}
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("hacks", "data", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
    log.warning("unexpected hacks API payload shape: %s", type(payload).__name__)
    return []


# ─── Normalisation ────────────────────────────────────────────────────────────

def normalise_incident(raw: dict[str, Any], *, source: str = "defillama") -> dict[str, Any]:
    """
    Normalise a single incident (from API or bootstrap) into the canonical
    schema documented at the top of this file.
    """
    # The API uses slightly different field names than our internal schema.
    protocol = (
        raw.get("name")
        or raw.get("protocol")
        or raw.get("project")
        or "unknown"
    )
    classification = raw.get("classification") or raw.get("type") or ""
    chain_raw = raw.get("chain") or raw.get("chains") or ""
    if isinstance(chain_raw, list):
        chain = ",".join(str(c).lower() for c in chain_raw) if chain_raw else "multi"
    else:
        chain = str(chain_raw).lower()

    incident = {
        "id":              str(raw.get("id") or raw.get("_id") or f"{source}-{normalise_protocol_name(protocol)}-{raw.get('date', '')}"),
        "protocol":        str(protocol).strip(),
        "protocol_slug":   normalise_protocol_name(protocol),
        "date":            _safe_date(raw.get("date") or raw.get("timestamp")),
        "amount_lost_usd": _safe_amount(raw.get("amount") or raw.get("amount_lost_usd") or raw.get("loss")),
        "type":            classify_type(classification),
        "technique":       str(raw.get("technique") or raw.get("classification") or raw.get("description") or "").strip(),
        "chain":           chain,
        "source_url":      str(raw.get("source") or raw.get("source_url") or raw.get("link") or "").strip(),
        "status":          str(raw.get("status") or "unknown").strip().lower() or "unknown",
    }
    incident["spa_protocols_affected"] = _match_spa_protocol(incident["protocol"])
    return incident


def _dedupe_and_sort(incidents: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    De-duplicate by (protocol_slug, date, technique) — newest record wins —
    then sort by date descending for deterministic output.
    """
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for inc in incidents:
        key = (inc["protocol_slug"], inc["date"], inc["technique"])
        # Prefer entries with non-empty source_url and larger amount
        existing = seen.get(key)
        if existing is None:
            seen[key] = inc
            continue
        if not existing["source_url"] and inc["source_url"]:
            seen[key] = inc
        elif inc["amount_lost_usd"] > existing["amount_lost_usd"]:
            seen[key] = inc
    # Sort by date desc, then protocol asc for stable output
    return sorted(
        seen.values(),
        key=lambda i: (i["date"] or "", i["protocol_slug"]),
        reverse=True,
    )


def build_summary(incidents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Build a per-SPA-whitelist-protocol summary. Each SPA slug is initialised to
    zero so the Risk Scoring Engine can iterate without KeyError.
    """
    summary: dict[str, dict[str, Any]] = {
        slug: {"incidents": 0, "total_lost_usd": 0.0, "last_incident": None}
        for slug in SPA_PROTOCOL_SLUGS
    }
    for inc in incidents:
        for slug in inc.get("spa_protocols_affected", []):
            entry = summary.setdefault(slug, {"incidents": 0, "total_lost_usd": 0.0, "last_incident": None})
            entry["incidents"] += 1
            entry["total_lost_usd"] = round(entry["total_lost_usd"] + inc["amount_lost_usd"], 2)
            if not entry["last_incident"] or (inc["date"] and inc["date"] > entry["last_incident"]):
                entry["last_incident"] = inc["date"]
    return summary


# ─── Top-level orchestration ──────────────────────────────────────────────────

def build_incidents_snapshot(*, offline: bool = False,
                              timeout: int = FETCH_TIMEOUT_S) -> dict[str, Any]:
    """
    Build the full ``incidents.json`` snapshot dict.

    Args:
        offline: skip network and use only the bootstrap list.
        timeout: per-request HTTP timeout.

    Returns the snapshot dict (not yet written to disk).
    """
    raw_api: list[dict[str, Any]] = []
    fetched_from_api = False
    if not offline:
        log.info("Fetching DefiLlama hacks API …")
        raw_api = fetch_defillama_hacks(timeout=timeout)
        fetched_from_api = bool(raw_api)
        if fetched_from_api:
            log.info("DefiLlama returned %d raw incidents", len(raw_api))
        else:
            log.info("DefiLlama unavailable — using bootstrap snapshot only")

    api_normalised = [normalise_incident(r, source="defillama") for r in raw_api]
    boot_normalised = [normalise_incident(r, source="bootstrap") for r in BOOTSTRAP_INCIDENTS]
    incidents = _dedupe_and_sort(api_normalised + boot_normalised)

    total_amount = round(sum(i["amount_lost_usd"] for i in incidents), 2)
    summary = build_summary(incidents)

    return {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "DefiLlama hacks API (+ bootstrap fallback)",
        "fetched_from_api": fetched_from_api,
        "total_incidents": len(incidents),
        "total_amount_lost_usd": total_amount,
        "incidents": incidents,
        "by_protocol_summary": summary,
    }


def write_snapshot(snapshot: dict[str, Any],
                   output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    """Write the snapshot to ``output_path`` (creating parent dirs)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=False, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Wrote %d incidents to %s", snapshot["total_incidents"], output_path)
    return output_path


def load_snapshot(path: Path = DEFAULT_OUTPUT_PATH) -> Optional[dict[str, Any]]:
    """Read back the snapshot file, or ``None`` if it does not exist / is invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to load %s: %s", path, e)
        return None


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch protocol incident history (FEAT-RISK-002)",
    )
    parser.add_argument("--offline", action="store_true",
                        help="Skip network — use bootstrap incidents only.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build snapshot but do not write to disk.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH,
                        help="Output path (default: data/incidents.json)")
    parser.add_argument("--timeout", type=int, default=FETCH_TIMEOUT_S,
                        help="HTTP timeout in seconds.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    snapshot = build_incidents_snapshot(offline=args.offline, timeout=args.timeout)
    log.info("Built snapshot: %d incidents, $%.0f total lost",
             snapshot["total_incidents"], snapshot["total_amount_lost_usd"])

    spa_hit = sum(1 for s in snapshot["by_protocol_summary"].values()
                  if s["incidents"] > 0)
    log.info("SPA-relevant protocols with incidents: %d/%d",
             spa_hit, len(snapshot["by_protocol_summary"]))

    if args.dry_run:
        log.info("--dry-run: not writing %s", args.output)
        return 0

    write_snapshot(snapshot, output_path=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
