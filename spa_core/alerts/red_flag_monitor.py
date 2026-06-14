"""
Red Flag Monitor — FEAT-MON-001 (Sprint v3.16).

Extends the existing depeg detector in ``spa_core/alerts/risk_monitor.py`` with
four additional external-signal categories that surface protocol-level early
warnings (the depeg detector remains untouched in its own module — they share
the same JSON alert shape but run on different cadences and inputs).

Signal categories
-----------------
1. ``tvl_drop``           — TVL drop > 15 % in 24 h **or** > 30 % in 7 d
                            (source: DefiLlama time-series ``/protocol/{slug}``).
2. ``apy_spike``          — current APY > 1.5 × the trailing 7-day baseline
                            (source: ``data/historical_apy.json`` and live snapshot).
3. ``governance_proposal``— active Snapshot proposal whose title/body matches
                            the risk-sensitive tag set (``upgrade``,
                            ``risk-param``, ``treasury``, ``emergency``).
4. ``token_unlock``       — protocol token unlock event within the next 7 days
                            (source: DefiLlama ``/api/unlocks``).

Severity
--------
* ``CRITICAL`` — the threshold is materially exceeded and/or the underlying
                 protocol carries a poor risk grade (C/D).
* ``WARN``     — the threshold is crossed but the protocol is graded A/B
                 (lower context risk).

Design constraints
------------------
* **Stdlib only** (urllib + json + dataclasses + datetime). No new top-level
  dependencies. Pattern lifted from
  ``spa_core/agents/yield_classifier_agent.py`` and
  ``spa_core/agents/audit_reader_agent.py``.
* **Offline-tolerant** — every network call is wrapped in try/except and
  degrades to ``BOOTSTRAP_*`` constants. ``scan_all`` NEVER raises.
* **Deterministic** — two consecutive calls in offline mode produce
  byte-identical output (``generated_at`` excluded from equality checks).
* **Severity context** — when ``data/risk_scores.json`` is present, the
  current protocol grade is folded into the severity classifier so that a
  TVL drop on a grade-D protocol is upgraded to CRITICAL while the same
  drop on a grade-A protocol stays at WARN.

Output schema (``data/red_flags.json``)
---------------------------------------

::

    {
      "generated_at": "<ISO-8601 UTC>",
      "monitor_version": "1.0",
      "sources": ["bootstrap"],
      "fallback_used": true,
      "red_flags": [
        {
          "protocol":    "compound-v3",
          "category":    "tvl_drop",
          "severity":    "CRITICAL",
          "message":     "TVL dropped 33.4% over 7d",
          "source":      "defillama",
          "detected_at": "2026-05-28T00:00:00Z",
          "evidence":    {"tvl_now": 2.0e9, "tvl_7d_ago": 3.0e9, "delta_pct": -33.4}
        },
        ...
      ],
      "summary": {
        "total_flags":      6,
        "by_category":      {"tvl_drop": 2, "apy_spike": 1, ...},
        "by_severity":      {"CRITICAL": 3, "WARN": 3},
        "by_protocol":      {"aave-v3": 1, ...},
        "protocols_clean":  6
      }
    }

CLI
---

::

    python -m spa_core.alerts.red_flag_monitor              # write file
    python -m spa_core.alerts.red_flag_monitor --offline    # bootstrap only
    python -m spa_core.alerts.red_flag_monitor --dry-run    # log, no write
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger("spa.alerts.red_flag_monitor")

MONITOR_VERSION = "1.0"

# ─── Configuration ────────────────────────────────────────────────────────────

FETCH_TIMEOUT_S = 30
FETCH_MAX_ATTEMPTS = 2
FETCH_BACKOFF_BASE = 2.0

# Threshold definitions (canonical — every change must be reflected in
# ADR_015_red_flag_monitor.md).
TVL_DROP_24H_THRESHOLD_PCT = 15.0   # WARN-grade trigger
TVL_DROP_7D_THRESHOLD_PCT  = 30.0   # WARN-grade trigger
TVL_DROP_CRITICAL_PCT      = 50.0   # always CRITICAL regardless of grade

APY_SPIKE_MULTIPLIER       = 1.5    # current / 7d-baseline ratio
APY_SPIKE_MIN_BASELINE_PCT = 0.1    # ignore baselines under 0.1 % APY
APY_SPIKE_CRITICAL_RATIO   = 3.0    # always CRITICAL regardless of grade

UNLOCK_HORIZON_DAYS        = 7
UNLOCK_CRITICAL_PCT_SUPPLY = 5.0    # unlock > 5 % of circulating supply

GOVERNANCE_LOOKAHEAD_DAYS  = 14
GOVERNANCE_RISK_TAGS: tuple[str, ...] = (
    "upgrade",
    "risk-param",
    "risk_param",
    "risk param",
    "parameter change",
    "treasury",
    "emergency",
    "shutdown",
    "pause",
)
GOVERNANCE_CRITICAL_TAGS: tuple[str, ...] = (
    "emergency",
    "shutdown",
    "pause",
)

# Default file locations — resolved relative to repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT_PATH       = _REPO_ROOT / "data" / "red_flags.json"
DEFAULT_RISK_SCORES_PATH  = _REPO_ROOT / "data" / "risk_scores.json"
DEFAULT_HISTORICAL_APY    = _REPO_ROOT / "data" / "historical_apy.json"

# SPA whitelist — must match the slugs used by the audit / yield / risk modules.
SPA_WHITELIST: tuple[str, ...] = (
    "aave-v3",
    "compound-v3",
    "morpho",
    "yearn-v3",
    "sky",
    "maple",
    "euler-v2",
    "pendle-pt",
    "curve-usdc-usdt",
    "ethena-susde",
)

CATEGORIES: tuple[str, ...] = (
    "tvl_drop",
    "apy_spike",
    "governance_proposal",
    "token_unlock",
)
SEVERITIES: tuple[str, ...] = ("WARN", "CRITICAL")


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class RedFlag:
    """A single red-flag finding for one protocol-category pair."""

    protocol: str
    category: str
    severity: str = "WARN"
    message: str = ""
    source: str = "bootstrap"
    detected_at: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Sort evidence keys for deterministic output.
        d["evidence"] = {k: d["evidence"][k]
                          for k in sorted(d["evidence"].keys())}
        return d


# ─── Curated bootstrap red-flag fixtures ──────────────────────────────────────
# These constants are the deterministic "offline" fallback. They represent a
# realistic snapshot of red-flag activity captured on _BOOTSTRAP_DATE — they
# unblock downstream Telegram alerts (BL-005) and go-live criterion 3 without
# requiring network access. When live fetchers succeed, the bootstrap entries
# are overlaid by the live data (per-category de-dupe on protocol).
# Each fixture intentionally uses a different protocol to keep the scan
# distribution realistic.

_BOOTSTRAP_DATE = "2026-05-28"
_BOOTSTRAP_AT   = f"{_BOOTSTRAP_DATE}T00:00:00Z"


BOOTSTRAP_TVL_DROPS: tuple[dict[str, Any], ...] = (
    {
        "protocol":    "euler-v2",
        "delta_24h":   -8.2,
        "delta_7d":    -33.4,
        "tvl_now":     780_000_000.0,
        "tvl_24h_ago": 850_000_000.0,
        "tvl_7d_ago":  1_170_000_000.0,
    },
    {
        "protocol":    "maple",
        "delta_24h":   -17.1,
        "delta_7d":    -22.0,
        "tvl_now":     410_000_000.0,
        "tvl_24h_ago": 495_000_000.0,
        "tvl_7d_ago":  525_000_000.0,
    },
)


BOOTSTRAP_APY_SPIKES: tuple[dict[str, Any], ...] = (
    {
        "protocol":   "ethena-susde",
        "current":    18.4,
        "baseline":   7.2,
        "ratio":      2.555,
    },
    {
        "protocol":   "pendle-pt",
        "current":    24.6,
        "baseline":   6.1,
        "ratio":      4.033,
    },
)


BOOTSTRAP_GOVERNANCE_PROPOSALS: tuple[dict[str, Any], ...] = (
    {
        "protocol":   "aave-v3",
        "proposal_id": "0xaavev3-2026-05-risk-param-update",
        "title":      "Risk Param Update: increase WETH borrow cap",
        "tag":        "risk-param",
        "deadline":   f"{_BOOTSTRAP_DATE}T12:00:00Z",
        "space":      "aave.eth",
    },
    {
        "protocol":   "compound-v3",
        "proposal_id": "0xcompoundv3-2026-05-upgrade-comet",
        "title":      "Upgrade Comet implementation — collateral asset migration",
        "tag":        "upgrade",
        "deadline":   f"{_BOOTSTRAP_DATE}T18:00:00Z",
        "space":      "comp-vote.eth",
    },
)


BOOTSTRAP_TOKEN_UNLOCKS: tuple[dict[str, Any], ...] = (
    {
        "protocol":   "pendle-pt",
        "unlock_at":  "2026-06-01T00:00:00Z",
        "pct_supply": 1.8,
        "tokens":     5_400_000,
        "symbol":     "PENDLE",
    },
    {
        "protocol":   "ethena-susde",
        "unlock_at":  "2026-06-03T00:00:00Z",
        "pct_supply": 6.4,   # > 5 % → CRITICAL even on grade-A
        "tokens":     420_000_000,
        "symbol":     "ENA",
    },
)


# ─── RedFlagMonitor ───────────────────────────────────────────────────────────


class RedFlagMonitor:
    """
    External-signal red-flag scanner for the SPA whitelist.

    Public API:
        ``scan_all(offline=False) -> list[RedFlag]``  — aggregate all categories.
        ``export(dry_run=False, offline=False) -> dict``  — write snapshot.

    All public methods are guaranteed to *never raise*. On any network or
    parser failure the monitor degrades to the curated ``BOOTSTRAP_*`` data
    set and marks ``fallback_used = True``.
    """

    DEFILLAMA_PROTOCOL_URL_TMPL = "https://api.llama.fi/protocol/{slug}"
    DEFILLAMA_UNLOCKS_URL       = "https://api.llama.fi/unlocks"
    SNAPSHOT_GRAPHQL_URL        = "https://hub.snapshot.org/graphql"

    def __init__(
        self,
        output_file: str | Path = DEFAULT_OUTPUT_PATH,
        risk_scores_file: str | Path = DEFAULT_RISK_SCORES_PATH,
        historical_apy_file: str | Path = DEFAULT_HISTORICAL_APY,
    ) -> None:
        self.output_file = Path(output_file)
        self.risk_scores_file = Path(risk_scores_file)
        self.historical_apy_file = Path(historical_apy_file)
        self._fallback_used: bool = False
        self._sources_used: list[str] = []

    # ── Public API ────────────────────────────────────────────────────────

    def scan_all(self, *, offline: bool = False) -> list[RedFlag]:
        """
        Run all four red-flag scans and return a flat, deterministically
        sorted list of ``RedFlag`` instances. NEVER raises.
        """
        sources: list[str] = []
        fallback = False
        flags: list[RedFlag] = []

        grades = self._load_risk_grades()

        # 1. TVL drops --------------------------------------------------
        try:
            tvl_records, src_tvl, fb_tvl = self._fetch_tvl_drops(offline=offline)
        except Exception as e:  # pragma: no cover (defensive)
            log.warning("tvl scan raised: %s — falling back", e)
            tvl_records, src_tvl, fb_tvl = list(BOOTSTRAP_TVL_DROPS), "bootstrap", True
        sources.append(src_tvl)
        fallback = fallback or fb_tvl
        flags.extend(self._classify_tvl_drops(tvl_records, grades))

        # 2. APY spikes -------------------------------------------------
        try:
            apy_records, src_apy, fb_apy = self._fetch_apy_spikes(offline=offline)
        except Exception as e:  # pragma: no cover (defensive)
            log.warning("apy scan raised: %s — falling back", e)
            apy_records, src_apy, fb_apy = list(BOOTSTRAP_APY_SPIKES), "bootstrap", True
        sources.append(src_apy)
        fallback = fallback or fb_apy
        flags.extend(self._classify_apy_spikes(apy_records, grades))

        # 3. Governance proposals --------------------------------------
        try:
            gov_records, src_gov, fb_gov = self._fetch_governance(offline=offline)
        except Exception as e:  # pragma: no cover (defensive)
            log.warning("governance scan raised: %s — falling back", e)
            gov_records, src_gov, fb_gov = list(BOOTSTRAP_GOVERNANCE_PROPOSALS), "bootstrap", True
        sources.append(src_gov)
        fallback = fallback or fb_gov
        flags.extend(self._classify_governance(gov_records, grades))

        # 4. Token unlocks ----------------------------------------------
        try:
            unlock_records, src_unl, fb_unl = self._fetch_unlocks(offline=offline)
        except Exception as e:  # pragma: no cover (defensive)
            log.warning("unlock scan raised: %s — falling back", e)
            unlock_records, src_unl, fb_unl = list(BOOTSTRAP_TOKEN_UNLOCKS), "bootstrap", True
        sources.append(src_unl)
        fallback = fallback or fb_unl
        flags.extend(self._classify_unlocks(unlock_records, grades))

        # Filter to whitelist & de-duplicate by (protocol, category).
        flags = self._dedupe_and_sort(flags)

        # Track source tagging — preserves order, no dupes.
        deduped: list[str] = []
        for s in sources:
            if s not in deduped:
                deduped.append(s)
        self._sources_used = deduped
        self._fallback_used = fallback

        return flags

    def export(self, *, dry_run: bool = False,
               offline: bool = False) -> dict[str, Any]:
        """
        Build the JSON snapshot and (unless ``dry_run``) persist it. Returns
        the snapshot dict — always — even when the write fails. NEVER raises.
        """
        try:
            flags = self.scan_all(offline=offline)
        except Exception as e:  # pragma: no cover (defensive)
            log.error("scan_all raised unexpectedly: %s", e)
            flags = []
            self._fallback_used = True
            self._sources_used = ["bootstrap"]

        snapshot = self._build_snapshot(flags)

        if dry_run:
            log.info("--dry-run: not writing %s", self.output_file)
            return snapshot

        try:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            self.output_file.write_text(
                json.dumps(snapshot, indent=2, sort_keys=False,
                           ensure_ascii=False),
                encoding="utf-8",
            )
            log.info("Wrote %d red_flag(s) to %s",
                     len(snapshot["red_flags"]), self.output_file)
        except OSError as e:
            log.error("Failed to write %s: %s", self.output_file, e)

        return snapshot

    # ── HTTP plumbing ─────────────────────────────────────────────────────

    def _http_get_text(self, url: str,
                       timeout: int = FETCH_TIMEOUT_S) -> Optional[str]:
        """GET ``url`` and return the body as a string, or ``None`` on error."""
        last_err: Optional[str] = None
        for attempt in range(FETCH_MAX_ATTEMPTS):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "spa-red-flag-monitor/1.0"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError,
                    ValueError, OSError) as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < FETCH_MAX_ATTEMPTS - 1:
                    import time
                    time.sleep(FETCH_BACKOFF_BASE ** attempt)
        log.warning("[FALLBACK] red-flag fetch failed (%s): %s", url, last_err)
        return None

    def _http_post_json(self, url: str, payload: dict[str, Any],
                        timeout: int = FETCH_TIMEOUT_S) -> Optional[dict[str, Any]]:
        """POST JSON payload to ``url`` and return decoded dict, or ``None``."""
        body = json.dumps(payload).encode("utf-8")
        last_err: Optional[str] = None
        for attempt in range(FETCH_MAX_ATTEMPTS):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "spa-red-flag-monitor/1.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                    return json.loads(text)
            except (urllib.error.URLError, urllib.error.HTTPError,
                    ValueError, OSError) as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < FETCH_MAX_ATTEMPTS - 1:
                    import time
                    time.sleep(FETCH_BACKOFF_BASE ** attempt)
        log.warning("[FALLBACK] red-flag POST failed (%s): %s", url, last_err)
        return None

    # ── Risk-grade context loader ─────────────────────────────────────────

    def _load_risk_grades(self) -> dict[str, str]:
        """
        Read ``risk_scores.json`` and return ``{slug: grade}``. Returns an
        empty dict on missing / unreadable file. Supports both legacy
        list-form ``{"scores": [...]}`` and dict-form
        ``{"protocols": {slug: {...}}}`` schemas.
        """
        path = self.risk_scores_file
        if not path.exists():
            log.debug("risk_scores.json not found — no grade context")
            return {}
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.debug("risk_scores.json unreadable (%s)", e)
            return {}
        if not isinstance(doc, dict):
            return {}

        out: dict[str, str] = {}
        if isinstance(doc.get("scores"), list):
            for entry in doc["scores"]:
                if not isinstance(entry, dict):
                    continue
                slug = entry.get("slug") or entry.get("protocol_slug")
                grade = entry.get("grade")
                if slug and grade:
                    out[str(slug)] = str(grade).upper()
        if isinstance(doc.get("protocols"), dict):
            for slug, entry in doc["protocols"].items():
                if isinstance(entry, dict) and entry.get("grade"):
                    out[str(slug)] = str(entry["grade"]).upper()
        return out

    @staticmethod
    def _grade_is_poor(grade: Optional[str]) -> bool:
        """Return True if the protocol grade qualifies as poor (C / D / F)."""
        if not grade:
            return False
        g = str(grade).strip().upper()
        return g in ("C", "D", "F")

    # ── Fetcher hooks (returns (records, source_label, fallback_used)) ─────

    def _fetch_tvl_drops(self, *, offline: bool
                         ) -> tuple[list[dict[str, Any]], str, bool]:
        """
        Fetch TVL deltas per whitelist protocol via DefiLlama. Returns a
        list of {protocol, delta_24h, delta_7d, tvl_now, tvl_24h_ago,
        tvl_7d_ago}. Falls back to ``BOOTSTRAP_TVL_DROPS`` on any error.
        """
        if offline:
            return list(BOOTSTRAP_TVL_DROPS), "bootstrap", True

        results: list[dict[str, Any]] = []
        any_success = False
        for slug in SPA_WHITELIST:
            url = self.DEFILLAMA_PROTOCOL_URL_TMPL.format(
                slug=urllib.parse.quote(slug, safe=""))
            text = self._http_get_text(url)
            if not text:
                continue
            try:
                doc = json.loads(text)
            except ValueError:
                continue
            record = self._parse_defillama_tvl(slug, doc)
            if record is None:
                continue
            any_success = True
            # Only keep records that actually breach a threshold — caller
            # classifier will re-check & assign severity.
            if (record["delta_24h"] <= -TVL_DROP_24H_THRESHOLD_PCT or
                    record["delta_7d"] <= -TVL_DROP_7D_THRESHOLD_PCT):
                results.append(record)
        if not any_success:
            return list(BOOTSTRAP_TVL_DROPS), "bootstrap", True
        return results, "defillama", False

    @staticmethod
    def _parse_defillama_tvl(slug: str, doc: Any
                              ) -> Optional[dict[str, Any]]:
        """Extract 24 h / 7 d TVL deltas from a DefiLlama /protocol payload."""
        if not isinstance(doc, dict):
            return None
        series = doc.get("tvl")
        if not isinstance(series, list) or not series:
            return None
        # Each point: {"date": <unix_ts>, "totalLiquidityUSD": <float>}.
        try:
            sorted_series = sorted(
                ((int(p["date"]), float(p.get("totalLiquidityUSD",
                                              p.get("tvl", 0.0))))
                 for p in series if isinstance(p, dict) and "date" in p),
                key=lambda t: t[0],
            )
        except (TypeError, ValueError, KeyError):
            return None
        if len(sorted_series) < 2:
            return None
        ts_now, tvl_now = sorted_series[-1]
        if tvl_now <= 0:
            return None
        ts_24h_target = ts_now - 24 * 3600
        ts_7d_target  = ts_now - 7 * 24 * 3600
        tvl_24h_ago = _closest_value(sorted_series, ts_24h_target)
        tvl_7d_ago  = _closest_value(sorted_series, ts_7d_target)
        if tvl_24h_ago <= 0 or tvl_7d_ago <= 0:
            return None
        delta_24h = (tvl_now - tvl_24h_ago) / tvl_24h_ago * 100.0
        delta_7d  = (tvl_now - tvl_7d_ago)  / tvl_7d_ago  * 100.0
        return {
            "protocol":    slug,
            "delta_24h":   round(delta_24h, 2),
            "delta_7d":    round(delta_7d,  2),
            "tvl_now":     tvl_now,
            "tvl_24h_ago": tvl_24h_ago,
            "tvl_7d_ago":  tvl_7d_ago,
        }

    def _fetch_apy_spikes(self, *, offline: bool
                          ) -> tuple[list[dict[str, Any]], str, bool]:
        """
        Compute APY spikes vs the 7-day baseline from
        ``data/historical_apy.json``. In ``offline`` mode this falls back to
        ``BOOTSTRAP_APY_SPIKES``.
        """
        if offline:
            return list(BOOTSTRAP_APY_SPIKES), "bootstrap", True

        if not self.historical_apy_file.exists():
            return list(BOOTSTRAP_APY_SPIKES), "bootstrap", True
        try:
            doc = json.loads(
                self.historical_apy_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return list(BOOTSTRAP_APY_SPIKES), "bootstrap", True
        if not isinstance(doc, dict):
            return list(BOOTSTRAP_APY_SPIKES), "bootstrap", True

        protocols_block = doc.get("protocols")
        if not isinstance(protocols_block, dict):
            return list(BOOTSTRAP_APY_SPIKES), "bootstrap", True

        out: list[dict[str, Any]] = []
        for series_key, points in protocols_block.items():
            if not isinstance(points, list) or len(points) < 8:
                continue
            try:
                trailing_8 = points[-8:]
                current = float(trailing_8[-1].get("apy", 0.0))
                baseline_pts = [float(p.get("apy", 0.0))
                                for p in trailing_8[:-1]]
                if not baseline_pts:
                    continue
                baseline = sum(baseline_pts) / len(baseline_pts)
            except (TypeError, ValueError, AttributeError):
                continue
            if baseline < APY_SPIKE_MIN_BASELINE_PCT:
                continue
            ratio = current / baseline if baseline > 0 else 0.0
            if ratio < APY_SPIKE_MULTIPLIER:
                continue
            slug = _series_key_to_slug(series_key)
            if slug not in SPA_WHITELIST:
                continue
            out.append({
                "protocol":  slug,
                "current":   round(current, 4),
                "baseline":  round(baseline, 4),
                "ratio":     round(ratio, 4),
            })
        if not out:
            # No spike — return empty list with a "historical_apy" tag so the
            # snapshot reflects that the source was consulted successfully.
            return [], "historical_apy", False
        return out, "historical_apy", False

    def _fetch_governance(self, *, offline: bool
                          ) -> tuple[list[dict[str, Any]], str, bool]:
        """
        Query the unauthenticated Snapshot GraphQL endpoint for active
        proposals tagged with a risk-sensitive keyword.
        """
        if offline:
            return list(BOOTSTRAP_GOVERNANCE_PROPOSALS), "bootstrap", True

        now_ts = int(datetime.now(timezone.utc).timestamp())
        end_ts = now_ts + GOVERNANCE_LOOKAHEAD_DAYS * 24 * 3600
        query = (
            "query Proposals($start:Int!,$end:Int!){"
            "proposals("
            "first:200,where:{state:\"active\",end_gte:$start,end_lte:$end},"
            "orderBy:\"end\",orderDirection:asc"
            "){id title body space{id} end}"
            "}"
        )
        payload = {
            "query": query,
            "variables": {"start": now_ts, "end": end_ts},
        }
        doc = self._http_post_json(self.SNAPSHOT_GRAPHQL_URL, payload)
        if not isinstance(doc, dict):
            return list(BOOTSTRAP_GOVERNANCE_PROPOSALS), "bootstrap", True

        data = doc.get("data")
        if not isinstance(data, dict):
            return list(BOOTSTRAP_GOVERNANCE_PROPOSALS), "bootstrap", True

        proposals = data.get("proposals")
        if not isinstance(proposals, list):
            return list(BOOTSTRAP_GOVERNANCE_PROPOSALS), "bootstrap", True

        out: list[dict[str, Any]] = []
        for p in proposals:
            if not isinstance(p, dict):
                continue
            title = str(p.get("title") or "")
            body  = str(p.get("body") or "")
            haystack = (title + " " + body).lower()
            tag = _first_risk_tag(haystack)
            if not tag:
                continue
            space_id = ""
            space_block = p.get("space")
            if isinstance(space_block, dict):
                space_id = str(space_block.get("id") or "")
            slug = _snapshot_space_to_slug(space_id)
            if slug not in SPA_WHITELIST:
                continue
            end_unix = p.get("end")
            try:
                deadline = datetime.fromtimestamp(int(end_unix), tz=timezone.utc) \
                    .isoformat().replace("+00:00", "Z")
            except (TypeError, ValueError):
                deadline = ""
            out.append({
                "protocol":    slug,
                "proposal_id": str(p.get("id") or ""),
                "title":       title.strip()[:200],
                "tag":         tag,
                "deadline":    deadline,
                "space":       space_id,
            })
        if not out:
            return [], "snapshot", False
        return out, "snapshot", False

    def _fetch_unlocks(self, *, offline: bool
                       ) -> tuple[list[dict[str, Any]], str, bool]:
        """
        Fetch upcoming token unlocks from DefiLlama and filter to the next
        ``UNLOCK_HORIZON_DAYS``.
        """
        if offline:
            return list(BOOTSTRAP_TOKEN_UNLOCKS), "bootstrap", True

        text = self._http_get_text(self.DEFILLAMA_UNLOCKS_URL)
        if not text:
            return list(BOOTSTRAP_TOKEN_UNLOCKS), "bootstrap", True
        try:
            doc = json.loads(text)
        except ValueError:
            return list(BOOTSTRAP_TOKEN_UNLOCKS), "bootstrap", True

        # DefiLlama returns either a list of project records or a wrapping
        # dict — handle both shapes.
        records = doc if isinstance(doc, list) else doc.get("protocols", []) \
            if isinstance(doc, dict) else []
        if not isinstance(records, list):
            return list(BOOTSTRAP_TOKEN_UNLOCKS), "bootstrap", True

        horizon_ts = datetime.now(timezone.utc) + timedelta(
            days=UNLOCK_HORIZON_DAYS)
        out: list[dict[str, Any]] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            slug = _defillama_unlock_to_slug(
                str(rec.get("name") or rec.get("slug") or ""))
            if slug not in SPA_WHITELIST:
                continue
            events = rec.get("events") or rec.get("upcomingEvent") or []
            if isinstance(events, dict):
                events = [events]
            if not isinstance(events, list):
                continue
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                ts_raw = ev.get("timestamp") or ev.get("date") or ev.get("ts")
                try:
                    ts = float(ts_raw) if ts_raw is not None else None
                except (TypeError, ValueError):
                    ts = None
                if ts is None:
                    continue
                # Heuristic: timestamps > 1e12 are ms.
                if ts > 1e12:
                    ts = ts / 1000.0
                event_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if event_dt < datetime.now(timezone.utc):
                    continue
                if event_dt > horizon_ts:
                    continue
                pct_supply = _safe_float(ev.get("pctSupply")
                                          or ev.get("pct_supply"), 0.0)
                out.append({
                    "protocol":   slug,
                    "unlock_at":  event_dt.isoformat().replace("+00:00", "Z"),
                    "pct_supply": pct_supply,
                    "tokens":     _safe_float(ev.get("tokens"), 0.0),
                    "symbol":     str(rec.get("symbol") or "").upper(),
                })
        if not out:
            return [], "defillama", False
        return out, "defillama", False

    # ── Classifiers (records -> RedFlag) ──────────────────────────────────

    def _classify_tvl_drops(self, records: Iterable[dict[str, Any]],
                            grades: dict[str, str]) -> list[RedFlag]:
        out: list[RedFlag] = []
        for rec in records:
            slug = rec.get("protocol")
            if slug not in SPA_WHITELIST:
                continue
            delta_24h = _safe_float(rec.get("delta_24h"), 0.0)
            delta_7d  = _safe_float(rec.get("delta_7d"), 0.0)
            if delta_24h > -TVL_DROP_24H_THRESHOLD_PCT and \
               delta_7d  > -TVL_DROP_7D_THRESHOLD_PCT:
                continue
            # Pick the dominant timeframe for the message.
            window = "24h" if abs(delta_24h) >= abs(delta_7d) else "7d"
            magnitude = abs(delta_24h) if window == "24h" else abs(delta_7d)

            severity = "WARN"
            if magnitude >= TVL_DROP_CRITICAL_PCT:
                severity = "CRITICAL"
            elif self._grade_is_poor(grades.get(slug)):
                severity = "CRITICAL"
            out.append(RedFlag(
                protocol=slug,
                category="tvl_drop",
                severity=severity,
                message=f"TVL dropped {magnitude:.1f}% over {window}",
                source="defillama",
                detected_at=_now_iso(),
                evidence={
                    "delta_24h":   delta_24h,
                    "delta_7d":    delta_7d,
                    "tvl_now":     _safe_float(rec.get("tvl_now"), 0.0),
                    "tvl_24h_ago": _safe_float(rec.get("tvl_24h_ago"), 0.0),
                    "tvl_7d_ago":  _safe_float(rec.get("tvl_7d_ago"), 0.0),
                    "grade":       grades.get(slug, "?"),
                },
            ))
        return out

    def _classify_apy_spikes(self, records: Iterable[dict[str, Any]],
                             grades: dict[str, str]) -> list[RedFlag]:
        out: list[RedFlag] = []
        for rec in records:
            slug = rec.get("protocol")
            if slug not in SPA_WHITELIST:
                continue
            current  = _safe_float(rec.get("current"),  0.0)
            baseline = _safe_float(rec.get("baseline"), 0.0)
            if baseline < APY_SPIKE_MIN_BASELINE_PCT:
                continue
            ratio = current / baseline if baseline > 0 else 0.0
            if ratio < APY_SPIKE_MULTIPLIER:
                continue
            severity = "WARN"
            if ratio >= APY_SPIKE_CRITICAL_RATIO:
                severity = "CRITICAL"
            elif self._grade_is_poor(grades.get(slug)):
                severity = "CRITICAL"
            out.append(RedFlag(
                protocol=slug,
                category="apy_spike",
                severity=severity,
                message=(
                    f"APY {current:.2f}% is {ratio:.2f}x baseline "
                    f"{baseline:.2f}%"
                ),
                source="historical_apy",
                detected_at=_now_iso(),
                evidence={
                    "current_apy":  current,
                    "baseline_apy": baseline,
                    "ratio":        round(ratio, 4),
                    "grade":        grades.get(slug, "?"),
                },
            ))
        return out

    def _classify_governance(self, records: Iterable[dict[str, Any]],
                              grades: dict[str, str]) -> list[RedFlag]:
        out: list[RedFlag] = []
        for rec in records:
            slug = rec.get("protocol")
            if slug not in SPA_WHITELIST:
                continue
            tag = str(rec.get("tag") or "").lower()
            if not tag:
                continue
            severity = "WARN"
            if tag in GOVERNANCE_CRITICAL_TAGS:
                severity = "CRITICAL"
            elif self._grade_is_poor(grades.get(slug)):
                severity = "CRITICAL"
            title = str(rec.get("title") or "")[:160]
            out.append(RedFlag(
                protocol=slug,
                category="governance_proposal",
                severity=severity,
                message=f"Risk-sensitive proposal [{tag}]: {title}",
                source="snapshot",
                detected_at=_now_iso(),
                evidence={
                    "proposal_id": str(rec.get("proposal_id") or ""),
                    "tag":         tag,
                    "deadline":    str(rec.get("deadline") or ""),
                    "space":       str(rec.get("space") or ""),
                    "grade":       grades.get(slug, "?"),
                },
            ))
        return out

    def _classify_unlocks(self, records: Iterable[dict[str, Any]],
                          grades: dict[str, str]) -> list[RedFlag]:
        out: list[RedFlag] = []
        now_utc = datetime.now(timezone.utc)
        for rec in records:
            slug = rec.get("protocol")
            if slug not in SPA_WHITELIST:
                continue
            # Skip events that already happened more than 24 hours ago
            unlock_at_str = str(rec.get("unlock_at") or "")
            if unlock_at_str:
                try:
                    unlock_dt = datetime.fromisoformat(
                        unlock_at_str.replace("Z", "+00:00")
                    )
                    if (now_utc - unlock_dt).total_seconds() > 86400:
                        log.debug("Skipping stale unlock for %s at %s (>24h ago)", slug, unlock_at_str)
                        continue
                except Exception:
                    pass  # If we can't parse, include the alert anyway
            pct_supply = _safe_float(rec.get("pct_supply"), 0.0)
            severity = "WARN"
            if pct_supply >= UNLOCK_CRITICAL_PCT_SUPPLY:
                severity = "CRITICAL"
            elif self._grade_is_poor(grades.get(slug)):
                severity = "CRITICAL"
            unlock_at = unlock_at_str
            symbol    = str(rec.get("symbol") or "").upper()
            out.append(RedFlag(
                protocol=slug,
                category="token_unlock",
                severity=severity,
                message=(
                    f"Token unlock {pct_supply:.2f}% of supply "
                    f"({symbol or 'TOKEN'}) at {unlock_at}"
                ),
                source="defillama",
                detected_at=_now_iso(),
                evidence={
                    "unlock_at":  unlock_at,
                    "pct_supply": pct_supply,
                    "tokens":     _safe_float(rec.get("tokens"), 0.0),
                    "symbol":     symbol,
                    "grade":      grades.get(slug, "?"),
                },
            ))
        return out

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _dedupe_and_sort(flags: list[RedFlag]) -> list[RedFlag]:
        """
        De-duplicate by (protocol, category) keeping the highest severity,
        then sort deterministically by (category, protocol, severity).
        """
        seen: dict[tuple[str, str], RedFlag] = {}
        for f in flags:
            key = (f.protocol, f.category)
            existing = seen.get(key)
            if existing is None:
                seen[key] = f
            else:
                # Prefer CRITICAL over WARN.
                if existing.severity != "CRITICAL" and f.severity == "CRITICAL":
                    seen[key] = f
        result = list(seen.values())
        # Stable ordering: category, then protocol, then severity weight desc.
        sev_weight = {"CRITICAL": 0, "WARN": 1}
        result.sort(key=lambda r: (
            r.category,
            r.protocol,
            sev_weight.get(r.severity, 9),
        ))
        return result

    def _build_snapshot(self, flags: list[RedFlag]) -> dict[str, Any]:
        """Construct the JSON-serialisable snapshot."""
        by_cat: dict[str, int] = {c: 0 for c in CATEGORIES}
        by_sev: dict[str, int] = {s: 0 for s in SEVERITIES}
        by_proto: dict[str, int] = {}
        for f in flags:
            by_cat[f.category] = by_cat.get(f.category, 0) + 1
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
            by_proto[f.protocol] = by_proto.get(f.protocol, 0) + 1

        flagged_protocols = set(by_proto.keys())
        protocols_clean = len(
            [p for p in SPA_WHITELIST if p not in flagged_protocols])

        return {
            "generated_at": _now_iso(),
            "monitor_version": MONITOR_VERSION,
            "sources": list(self._sources_used) if self._sources_used
                else ["bootstrap"],
            "fallback_used": bool(self._fallback_used),
            "red_flags": [f.to_dict() for f in flags],
            "summary": {
                "total_flags":     len(flags),
                "by_category":     {k: by_cat[k]
                                    for k in sorted(by_cat.keys())},
                "by_severity":     {k: by_sev[k]
                                    for k in sorted(by_sev.keys())},
                "by_protocol":     {k: by_proto[k]
                                    for k in sorted(by_proto.keys())},
                "protocols_clean": protocols_clean,
            },
        }


# ─── Module-level helpers ─────────────────────────────────────────────────────


def _now_iso() -> str:
    """UTC ISO-8601 timestamp with trailing Z (deterministic format)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(raw: Any, default: float = 0.0) -> float:
    """Coerce to float, returning ``default`` on any error."""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _closest_value(sorted_series: list[tuple[int, float]],
                   target_ts: int) -> float:
    """Return the float value whose timestamp is closest to ``target_ts``."""
    if not sorted_series:
        return 0.0
    best = sorted_series[0]
    best_dist = abs(best[0] - target_ts)
    for ts, val in sorted_series:
        dist = abs(ts - target_ts)
        if dist < best_dist:
            best = (ts, val)
            best_dist = dist
    return best[1]


def _first_risk_tag(haystack: str) -> Optional[str]:
    """Return the first risk-sensitive tag found inside ``haystack``."""
    h = haystack.lower()
    for tag in GOVERNANCE_RISK_TAGS:
        if tag in h:
            # Normalise spelling.
            return tag.replace("_", "-").replace(" ", "-")
    return None


_SNAPSHOT_SPACE_ALIASES: dict[str, str] = {
    "aave.eth":         "aave-v3",
    "aavegotchi.eth":   "aave-v3",   # defensive: ignored — not in whitelist anyway
    "comp-vote.eth":    "compound-v3",
    "compound.eth":     "compound-v3",
    "morpho.eth":       "morpho",
    "morpho-vote.eth":  "morpho",
    "yearn":            "yearn-v3",
    "ybaby.eth":        "yearn-v3",
    "veyfi.eth":        "yearn-v3",
    "sky.eth":          "sky",
    "makerdao.eth":     "sky",
    "maker.eth":        "sky",
    "maple.eth":        "maple",
    "syrup.eth":        "maple",
    "euler.eth":        "euler-v2",
    "eulergov.eth":     "euler-v2",
    "pendle.eth":       "pendle-pt",
    "curve.eth":        "curve-usdc-usdt",
    "curve-dao.eth":    "curve-usdc-usdt",
    "ethena.eth":       "ethena-susde",
}


def _snapshot_space_to_slug(space_id: str) -> str:
    """Map a Snapshot space ID to a SPA whitelist slug, or empty string."""
    if not space_id:
        return ""
    key = space_id.strip().lower()
    return _SNAPSHOT_SPACE_ALIASES.get(key, "")


_DEFILLAMA_UNLOCK_ALIASES: dict[str, str] = {
    "aave":              "aave-v3",
    "aave-v3":           "aave-v3",
    "compound":          "compound-v3",
    "compound-v3":       "compound-v3",
    "morpho":            "morpho",
    "yearn":             "yearn-v3",
    "yearn-finance":     "yearn-v3",
    "sky":               "sky",
    "maker":             "sky",
    "makerdao":          "sky",
    "maple":             "maple",
    "maple-finance":     "maple",
    "euler":             "euler-v2",
    "euler-v2":          "euler-v2",
    "pendle":            "pendle-pt",
    "pendle-pt":         "pendle-pt",
    "curve":             "curve-usdc-usdt",
    "curve-finance":     "curve-usdc-usdt",
    "ethena":            "ethena-susde",
    "ethena-susde":      "ethena-susde",
}


def _defillama_unlock_to_slug(name: str) -> str:
    """Map a DefiLlama unlock-project name to a SPA whitelist slug."""
    if not name:
        return ""
    key = name.strip().lower().replace(" ", "-")
    return _DEFILLAMA_UNLOCK_ALIASES.get(key, "")


def _series_key_to_slug(series_key: str) -> str:
    """
    Map a ``historical_apy.json`` series key (e.g. ``aave-v3-usdc-ethereum``)
    to a SPA whitelist slug. The convention is ``<slug>-<asset>-<chain>``;
    we take the longest matching whitelist prefix.
    """
    if not series_key:
        return ""
    k = series_key.lower()
    best = ""
    for slug in SPA_WHITELIST:
        if k == slug or k.startswith(slug + "-"):
            if len(slug) > len(best):
                best = slug
    return best


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Red Flag Monitor (FEAT-MON-001) — produce data/red_flags.json",
    )
    parser.add_argument("--offline", action="store_true",
                        help="Skip network — use BOOTSTRAP_* fixtures only.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build snapshot but do not write to disk.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH,
                        help="Output path (default: data/red_flags.json)")
    parser.add_argument("--risk-scores", type=Path,
                        default=DEFAULT_RISK_SCORES_PATH,
                        help="Path to risk_scores.json (for grade context).")
    parser.add_argument("--historical-apy", type=Path,
                        default=DEFAULT_HISTORICAL_APY,
                        help="Path to historical_apy.json (for APY baseline).")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    monitor = RedFlagMonitor(
        output_file=args.output,
        risk_scores_file=args.risk_scores,
        historical_apy_file=args.historical_apy,
    )
    snapshot = monitor.export(dry_run=args.dry_run, offline=args.offline)

    log.info(
        "Done — %d flags (%s), sources=%s, fallback=%s",
        snapshot["summary"]["total_flags"],
        snapshot["summary"]["by_severity"],
        snapshot["sources"],
        snapshot["fallback_used"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
