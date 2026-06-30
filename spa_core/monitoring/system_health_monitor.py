"""system_health_monitor.py — SPA end-to-end SYSTEM health monitor (12-hourly).

Outcome / semantic monitoring — answers "is the system producing correct
results end-to-end?" — complementing the process-level liveness watchdog
``agent_health_monitor.py`` (hourly).

Non-duplication contract (per spec): this module MUST NOT re-check launchd
load state, PIDs, LastExitStatus, plist parseability or per-agent log
freshness. The one deliberate overlap — "did the daily cycle run today?" — is
evaluated here by OUTCOME (last equity-curve date), not by process state.

Design rules (per CLAUDE.md):
  * stdlib only — no external deps; network via urllib.request
  * atomic writes via spa_core.utils.atomic.atomic_save (tmp + os.replace)
  * fail-safe: run() never raises; process always exits 0
  * read-only w.r.t. allocator / risk / execution; only file written is
    data/system_health.json (+ tmp). Kill-switch invoked DRY (read-only) only.
  * LLM FORBIDDEN (monitoring component) — no model calls anywhere
  * Telegram via spa_core.alerts.telegram_client._post_message (HTML)

CLI:
    python3 -m spa_core.monitoring.system_health_monitor --check   # compute+write+print, NO telegram
    python3 -m spa_core.monitoring.system_health_monitor --run     # compute+write+SEND telegram
    python3 -m spa_core.monitoring.system_health_monitor --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("spa.monitoring.system_health")

# Allow direct-script invocation (python3 path/to/system_health_monitor.py) in
# addition to `-m spa_core.monitoring.system_health_monitor`: ensure the project
# root is importable so `import spa_core...` resolves either way.
_PROJECT_ROOT_FOR_PATH = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT_FOR_PATH not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT_FOR_PATH)

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------
CRITICAL = "CRITICAL"
WARNING = "WARNING"
INFO = "INFO"
OK = "OK"
SKIPPED = "SKIPPED"                       # sentinel — excluded from roll-up
_SEV = {OK: 0, INFO: 1, WARNING: 2, CRITICAL: 3}

# Shared red-flag severity vocabulary (single source — N8). is_critical() matches
# the critical SET (CRITICAL/CRIT/FATAL/...) so a writer renaming the level cannot
# silently disable critical detection here. Import lazily-tolerant: if the shared
# module is somehow unavailable, fall back to the historical critical literals.
try:
    from spa_core.alerts.severity import is_critical as _is_critical_severity
    from spa_core.alerts.severity import (
        read_portfolio_health_score as _read_portfolio_health_score,
    )
except Exception:                          # noqa: BLE001 — never let an import gap blind the monitor
    _FALLBACK_CRIT = frozenset({"CRITICAL", "CRIT", "FATAL", "SEVERE", "EMERGENCY"})

    def _is_critical_severity(sev) -> bool:  # type: ignore[no-redef]
        return isinstance(sev, str) and sev.strip().upper() in _FALLBACK_CRIT

    def _read_portfolio_health_score(doc):   # type: ignore[no-redef]
        if not isinstance(doc, dict):
            return None
        for k in ("health_score", "score", "portfolio_health_score", "overall_score"):
            v = doc.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        return None


def _worst(statuses) -> str:
    """Highest-severity status among args, ignoring SKIPPED."""
    real = [s for s in statuses if s in _SEV]
    return max(real, key=lambda s: _SEV[s]) if real else OK


# ---------------------------------------------------------------------------
# Constants (single source — top of module)
# ---------------------------------------------------------------------------
PAPER_REAL_START = date(2026, 6, 10)
_HISTORY_MAX = 30

# Capital corridor (capital corruption tripwire)
EQUITY_MIN = 99_000.0
EQUITY_MAX = 110_000.0

# Adapter APY plausibility window (after normalization), percent
APY_RANGE_MIN = 0.5
APY_RANGE_MAX = 25.0

STATUS_FRESH_H = 26.0                     # paper_trading_status staleness
DERISK_FRESH_H = 26.0                     # derisk_status.json staleness (cycle-written, daily)
# DFB (DeFi Board, Lane 2) freshness + feed-outage canary thresholds.
# The dfb_capture agent runs daily (09:30 UTC) — pools.json must refresh within ~26h
# (one daily cadence + slack), mirroring the daily-cycle staleness window. Beyond that
# the capture agent is presumed down → WARNING (fail-CLOSED), never silently OK.
DFB_FRESH_H = 30.0                        # data/dfb/pools.json staleness (daily capture + slack)
# UNKNOWN-ratio canary: a feed outage shows as a SPIKE in UNKNOWN-graded pools (the overlay
# fails CLOSED to UNKNOWN when it cannot resolve a kind / build a risk surface). A modest
# baseline is normal (unresolved kinds); a runaway ratio means the live feed is broken.
DFB_UNKNOWN_RATIO_WARN = 0.60            # > 60% UNKNOWN → feed-outage canary (WARNING)
ALLOC_CAP_PCT = 30.0                      # monitor tripwire (RiskPolicy T1 cap is 40%)
T2_CAP_PCT = 50.0                         # ADR-019
PORTFOLIO_HEALTH_FLOOR = 70.0
DEVIATION_PCT = 50.0                      # stored vs live APY deviation
TREND_DECLINE_PCT = -1.0                 # 7-day decline tripwire
KANBAN_STALE_DAYS = 7
LOGS_SIZE_LIMIT_BYTES = 500 * 1024 * 1024
SCRIPTS_CLUTTER_LIMIT = 25
GITHUB_RATE_FLOOR = 100

# Per-call / per-domain budgets (seconds)
NET_TIMEOUT = 10
SUBPROC_TIMEOUT = 20
_DOMAIN_BUDGET = {
    "d1": 5, "d2": 20, "d3": 3, "d4": 25, "d5": 30, "d6": 15, "d7": 5,
    "d_dfb": 5,
}

# Network endpoints
DEFILLAMA_POOLS = "https://yields.llama.fi/pools"
EARNDEFI = "https://earn-defi.com/"
GITHUB_RAW = "https://raw.githubusercontent.com/yurii-spa/SPA/main/data/adapter_status.json"
GITHUB_API_RATE = "https://api.github.com/rate_limit"
LOCAL_API = "http://127.0.0.1:8765/health"

_SECRET_RE = re.compile(r"(token|secret|key|password)", re.I)
# This is a FILENAME heuristic for accidentally-left secret-DUMP files (the
# 2026-06-10 PAT leak was in .md/.html/.command files). Source modules named for
# what they do (e.g. spa_core/utils/keychain.py) are legit code, not leaked
# secrets, and are gated by code review — exclude source extensions here.
_SECRET_SAFE_SUFFIXES = (".lock", ".py")


# ===========================================================================
# CheckResult
# ===========================================================================
@dataclass
class CheckResult:
    id: str
    domain: str
    status: str = OK
    title: str = ""
    value: Any = None
    expected: Any = None
    evidence: dict = field(default_factory=dict)
    error: Optional[str] = None
    skipped_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "status": self.status,
            "title": self.title,
            "value": self.value,
            "expected": self.expected,
            "evidence": self.evidence or {},
            "error": self.error,
            "skipped_reason": self.skipped_reason,
        }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _normalize_tier(raw: Any) -> tuple[str, bool]:
    """Return (tier, unknown_flag). 1|"1"|"T1"->T1; 2|"2"|"T2"->T2; else T2+flag."""
    s = str(raw).strip().upper()
    if s in ("1", "T1"):
        return "T1", False
    if s in ("2", "T2"):
        return "T2", False
    return "T2", True


def _normalize_apy(apy: Any, siblings: Optional[list] = None) -> Optional[float]:
    """Normalize APY to PERCENT. Some older adapters store decimal (e.g. 0.03);
    if 0 < apy < 0.5 and a sibling (live/fallback) is ~100x larger, it's decimal."""
    if not _is_finite_number(apy):
        return None
    apy = float(apy)
    if 0 < apy < 0.5:
        sibs = [s for s in (siblings or []) if _is_finite_number(s)]
        if any(s >= apy * 50 for s in sibs) or not sibs:
            return apy * 100.0
    return apy


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    s = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_hours(raw: Any) -> Optional[float]:
    dt = _parse_ts(raw)
    if dt is None:
        return None
    return (_now() - dt).total_seconds() / 3600.0


def _http_get(url: str, timeout: int = NET_TIMEOUT, want_headers: bool = False,
              extra_headers: Optional[dict] = None):
    """GET a URL. Returns (status_code, body_bytes_or_None, headers_dict).
    gzip is sniffed via magic bytes and decompressed (DeFiLlama hazard).
    ``extra_headers`` (e.g. Authorization) merge on top of the default UA."""
    hdrs = {"User-Agent": "spa-health/1.0"}
    if extra_headers:
        hdrs.update(extra_headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", None)
        if status is None:
            status = resp.getcode()
        raw = resp.read()
        hdrs = {k.lower(): v for k, v in dict(resp.headers).items()} if want_headers else {}
    if raw[:2] == b"\x1f\x8b":            # gzip magic
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return status, raw, hdrs


# ===========================================================================
# Monitor
# ===========================================================================
class SystemHealthMonitor:
    def __init__(self, data_dir: str | os.PathLike | None = None,
                 project_root: str | os.PathLike | None = None):
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        self.data_dir = Path(data_dir) if data_dir else self.project_root / "data"
        self.src: dict[str, Any] = {}     # loaded sources, populated by _prelude
        self._git_untracked: list[str] = []

    # -- source loading -----------------------------------------------------
    def _load_json(self, name: str) -> tuple[Any, Optional[str]]:
        path = self.data_dir / name
        try:
            if not path.exists():
                return None, "missing"
            return json.loads(path.read_text(encoding="utf-8")), None
        except Exception as exc:           # noqa: BLE001
            return None, repr(exc)

    def _prelude(self) -> None:
        """Load all local sources once; snapshot git untracked files."""
        for key, fname in [
            ("equity", "equity_curve_daily.json"),
            ("adapter", "adapter_status.json"),
            ("status", "paper_trading_status.json"),
            ("golive", "golive_status.json"),
            ("red_flags", "red_flags.json"),
            ("positions", "current_positions.json"),
            ("portfolio_health", "portfolio_health.json"),
        ]:
            data, err = self._load_json(fname)
            self.src[key] = {"data": data, "error": err}

        # tournament: strategy_tournament.json, fallback tournament_results.json
        t, terr = self._load_json("strategy_tournament.json")
        if t is None:
            t2, terr2 = self._load_json("tournament_results.json")
            if t2 is not None:
                t, terr = t2, None
            else:
                terr = terr2 or terr
        self.src["tournament"] = {"data": t, "error": terr}

        # git untracked snapshot (for d5/d7)
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=str(self.project_root), capture_output=True, text=True,
                timeout=SUBPROC_TIMEOUT,
            )
            self._git_untracked = [
                line[3:] for line in out.stdout.splitlines() if line.startswith("??")
            ]
        except Exception as exc:           # noqa: BLE001
            log.warning("git snapshot failed: %s", exc)
            self._git_untracked = []

    # ======================================================================
    # DOMAIN 1 — Data Pipeline Integrity
    # ======================================================================
    def check_d1_data_pipeline(self) -> list[CheckResult]:
        D = "d1_data_pipeline"
        out: list[CheckResult] = []

        # --- equity file ---------------------------------------------------
        eq = self.src["equity"]
        if eq["data"] is None:
            out.append(CheckResult("d1.equity.exists", D, CRITICAL,
                                   "equity_curve_daily.json missing/unparseable",
                                   error=eq["error"]))
            for cid in ("d1.equity.count", "d1.equity.range", "d1.equity.nan", "d1.equity.dates"):
                out.append(CheckResult(cid, D, SKIPPED,
                                       skipped_reason="upstream d1.equity.exists failed"))
        else:
            data = eq["data"]
            daily = data.get("daily") or []
            summary = data.get("summary") or {}
            out.append(CheckResult("d1.equity.exists", D, OK,
                                   f"equity_curve_daily.json loaded ({len(daily)} bars)"))

            # count — honest track days (real_days = non-warmup bars), not the raw
            # bar count (num_days) which includes pre-PAPER_REAL_START warmup bars.
            expected = (date.today() - PAPER_REAL_START).days + 1
            real = [b for b in daily if not b.get("is_warmup", False)]
            num_days = summary.get("real_days", len(real) if real else len(daily))
            if isinstance(num_days, int) and num_days < expected - 1:
                out.append(CheckResult("d1.equity.count", D, WARNING,
                                       f"only {num_days} track days (expected ~{expected})",
                                       value=num_days, expected=expected))
            else:
                out.append(CheckResult("d1.equity.count", D, OK,
                                       f"{num_days} track days", value=num_days, expected=expected))

            closes = [b.get("close_equity") for b in daily]
            # range
            bad = [c for c in closes if _is_finite_number(c) and not (EQUITY_MIN <= c <= EQUITY_MAX)]
            if bad:
                out.append(CheckResult("d1.equity.range", D, CRITICAL,
                                       f"{len(bad)} equity value(s) outside ${EQUITY_MIN:,.0f}-${EQUITY_MAX:,.0f}",
                                       value=bad[0], evidence={"outliers": bad[:5]}))
            else:
                out.append(CheckResult("d1.equity.range", D, OK, "equity within corridor"))
            # nan / inf
            nans = [c for c in closes if c is not None and not _is_finite_number(c)]
            if nans:
                out.append(CheckResult("d1.equity.nan", D, CRITICAL,
                                       f"{len(nans)} non-finite equity value(s)"))
            else:
                out.append(CheckResult("d1.equity.nan", D, OK, "no NaN/inf in equity"))
            # dates strictly ascending, no dup, no gap > 1 day
            out.append(self._check_equity_dates(daily, D))

        # --- adapter file --------------------------------------------------
        ad = self.src["adapter"]
        if ad["data"] is None or not isinstance(ad["data"].get("adapters"), dict):
            out.append(CheckResult("d1.adapter.present", D, WARNING,
                                   "adapter_status.json missing/unreadable",
                                   error=ad["error"] or "no adapters key"))
            for cid in ("d1.adapter.apy_range", "d1.adapter.apy_none"):
                out.append(CheckResult(cid, D, SKIPPED,
                                       skipped_reason="upstream adapter load failed"))
        else:
            adapters = ad["data"]["adapters"]
            expected_t1 = self._expected_t1_adapters()
            missing = [n for n in expected_t1 if n not in adapters]
            if missing:
                out.append(CheckResult("d1.adapter.present", D, CRITICAL,
                                       f"T1 adapter(s) absent: {', '.join(missing)}",
                                       evidence={"missing": missing}))
            else:
                out.append(CheckResult("d1.adapter.present", D, OK,
                                       f"all {len(expected_t1)} T1 adapters present"))
            # apy range + none
            out.extend(self._check_adapter_apys(adapters, D))

        # --- tournament ----------------------------------------------------
        tn = self.src["tournament"]
        if tn["data"] is None:
            out.append(CheckResult("d1.tournament.demo", D, WARNING,
                                   "tournament file missing/unreadable", error=tn["error"]))
            out.append(CheckResult("d1.tournament.populated", D, SKIPPED,
                                   skipped_reason="upstream tournament load failed"))
        else:
            tdata = tn["data"]
            if tdata.get("is_demo", False) is not False:
                out.append(CheckResult("d1.tournament.demo", D, CRITICAL,
                                       "tournament is_demo != false",
                                       value=tdata.get("is_demo")))
            else:
                out.append(CheckResult("d1.tournament.demo", D, OK, "tournament real (is_demo=false)"))
            strat = strat_list(tdata)
            # "winner" is the de-facto top-ranked strategy. The ranked file may not
            # carry an explicit "winner" key — derive it from the ranking (top_5 /
            # ranked_strategies / shadow_active_strategies) so a fully-populated
            # tournament isn't flagged as having "no valid winner".
            winner = tdata.get("winner")
            if not winner:
                for _key in ("top_5", "ranked_strategies", "shadow_active_strategies"):
                    _ranked = tdata.get(_key) or []
                    if _ranked and isinstance(_ranked[0], dict):
                        winner = (_ranked[0].get("id") or _ranked[0].get("strategy_id")
                                  or _ranked[0].get("strategy_key"))
                        if winner:
                            break
            if not strat or not winner:
                out.append(CheckResult("d1.tournament.populated", D, WARNING,
                                       "no strategies or no valid winner",
                                       value=len(strat)))
            else:
                out.append(CheckResult("d1.tournament.populated", D, OK,
                                       f"{len(strat)} strategies, winner={winner}"))

        # --- status --------------------------------------------------------
        stt = self.src["status"]
        if stt["data"] is None:
            out.append(CheckResult("d1.status.demo", D, CRITICAL,
                                   "paper_trading_status.json missing/unparseable",
                                   error=stt["error"]))
            out.append(CheckResult("d1.status.equity", D, SKIPPED,
                                   skipped_reason="upstream status load failed"))
            out.append(CheckResult("d1.status.fresh", D, SKIPPED,
                                   skipped_reason="upstream status load failed"))
        else:
            sd = stt["data"]
            if sd.get("is_demo", False) is not False:
                out.append(CheckResult("d1.status.demo", D, CRITICAL,
                                       "status is_demo != false", value=sd.get("is_demo")))
            else:
                out.append(CheckResult("d1.status.demo", D, OK, "status real (is_demo=false)"))
            eqv = sd.get("current_equity")
            if _is_finite_number(eqv) and not (EQUITY_MIN <= eqv <= EQUITY_MAX):
                out.append(CheckResult("d1.status.equity", D, CRITICAL,
                                       f"status equity ${eqv:,.0f} outside corridor", value=eqv))
            else:
                out.append(CheckResult("d1.status.equity", D, OK,
                                       f"status equity ${eqv:,.0f}" if _is_finite_number(eqv) else "status equity ok",
                                       value=eqv))
            age = _age_hours(sd.get("last_cycle_ts") or sd.get("last_updated") or sd.get("generated_at"))
            if age is not None and age > STATUS_FRESH_H:
                out.append(CheckResult("d1.status.fresh", D, WARNING,
                                       f"status {age:.1f}h old (> {STATUS_FRESH_H}h)", value=round(age, 1)))
            else:
                out.append(CheckResult("d1.status.fresh", D, OK,
                                       f"status fresh ({age:.1f}h)" if age is not None else "status fresh",
                                       value=round(age, 1) if age is not None else None))

        # --- golive count regression --------------------------------------
        gl = self.src["golive"]
        if gl["data"] is None:
            out.append(CheckResult("d1.golive.count", D, WARNING,
                                   "golive_status.json missing/unreadable", error=gl["error"]))
        else:
            passed = gl["data"].get("passed")
            total = gl["data"].get("total")
            prev_passed = self._prev_golive_passed()
            if isinstance(passed, int) and isinstance(prev_passed, int) and passed < prev_passed:
                out.append(CheckResult("d1.golive.count", D, WARNING,
                                       f"golive regressed {prev_passed}->{passed}",
                                       value=passed, expected=prev_passed))
            elif isinstance(passed, int) and passed == total:
                out.append(CheckResult("d1.golive.count", D, INFO,
                                       f"golive {passed}/{total} — all pass",
                                       value=passed, expected=total))
            else:
                out.append(CheckResult("d1.golive.count", D, OK,
                                       f"golive {passed}/{total}", value=passed, expected=total))

        # --- track.db mirror health (MP-109) ------------------------------
        # The SQLite mirror is the machine's crash-recovery copy of the track.
        # A historical silent bug left it at 0 bytes while the cycle still
        # logged status:ok. _persist_track now writes an observable flag
        # (track_persist_status.json) AND the file itself is stat'd here so a
        # stale/empty mirror surfaces in monitoring instead of hiding.
        out.append(self._check_track_db_mirror(D))
        return out

    def _check_track_db_mirror(self, D: str) -> CheckResult:
        cid = "d1.track_db.mirror"
        db = self.data_dir / "track.db"
        flag = self.data_dir / "track_persist_status.json"
        # Prefer the explicit cycle-written flag (carries the reason); fall back
        # to stat'ing track.db directly so a missing flag never hides a 0-byte db.
        try:
            if flag.exists():
                with open(flag, "r", encoding="utf-8") as fh:
                    fd = json.load(fh)
                if fd.get("track_persist_ok") is False:
                    return CheckResult(cid, D, CRITICAL,
                                       f"track.db mirror unhealthy: {fd.get('reason')}",
                                       value=fd.get("db_size_bytes"))
        except Exception as exc:  # noqa: BLE001 — health check must never raise
            return CheckResult(cid, D, WARNING,
                               "track_persist_status.json unreadable", error=str(exc))
        try:
            size = db.stat().st_size if db.exists() else 0
        except OSError as exc:
            return CheckResult(cid, D, WARNING, "track.db stat failed", error=str(exc))
        if size == 0:
            return CheckResult(cid, D, CRITICAL,
                               "track.db is 0 bytes (empty/stub mirror)", value=size)
        return CheckResult(cid, D, OK, f"track.db mirror healthy ({size:,} bytes)", value=size)

    def _check_equity_dates(self, daily: list, D: str) -> CheckResult:
        dates: list[date] = []
        for b in daily:
            dt = _parse_ts((b.get("date") or "") + "T00:00:00") if b.get("date") else None
            if dt:
                dates.append(dt.date())
        issues = []
        for i in range(1, len(dates)):
            delta = (dates[i] - dates[i - 1]).days
            if delta <= 0:
                issues.append(f"non-ascending/dup at {dates[i]}")
            elif delta > 1:
                issues.append(f"gap {delta}d before {dates[i]}")
        if issues:
            return CheckResult("d1.equity.dates", D, WARNING,
                               f"{len(issues)} date anomaly(ies): {issues[0]}",
                               evidence={"issues": issues[:5]})
        return CheckResult("d1.equity.dates", D, OK, "dates strictly ascending, no gaps")

    def _check_adapter_apys(self, adapters: dict, D: str) -> list[CheckResult]:
        out_of_range = []
        none_apys = []
        for name, info in adapters.items():
            if not isinstance(info, dict):
                continue
            apy = info.get("apy")
            if apy is None or not _is_finite_number(apy):
                none_apys.append(name)
                continue
            norm = _normalize_apy(apy, [info.get("live_apy"), info.get("fallback_apy")])
            if norm is not None and not (APY_RANGE_MIN <= norm <= APY_RANGE_MAX):
                out_of_range.append((name, round(norm, 2)))
        res = []
        if out_of_range:
            res.append(CheckResult("d1.adapter.apy_range", D, WARNING,
                                   f"{len(out_of_range)} adapter APY(s) out of {APY_RANGE_MIN}-{APY_RANGE_MAX}%",
                                   evidence={"out_of_range": out_of_range[:8]}))
        else:
            res.append(CheckResult("d1.adapter.apy_range", D, OK, "adapter APYs in plausible range"))
        if none_apys:
            sev = CRITICAL if len(none_apys) >= 3 else WARNING
            res.append(CheckResult("d1.adapter.apy_none", D, sev,
                                   f"{len(none_apys)} adapter(s) with no APY",
                                   evidence={"none": none_apys[:8]}))
        else:
            res.append(CheckResult("d1.adapter.apy_none", D, OK, "all adapters report APY"))
        return res

    # ======================================================================
    # DOMAIN 2 — Protocol Connectivity (network)
    # ======================================================================
    def check_d2_connectivity(self) -> list[CheckResult]:
        D = "d2_connectivity"
        out: list[CheckResult] = []
        # reach
        live_pools = None
        try:
            status, body, _ = _http_get(DEFILLAMA_POOLS, timeout=NET_TIMEOUT)
            if status == 200 and body:
                payload = json.loads(body.decode("utf-8", "replace"))
                live_pools = payload.get("data") if isinstance(payload, dict) else payload
                out.append(CheckResult("d2.defillama.reach", D, OK, "DeFiLlama reachable"))
            else:
                out.append(CheckResult("d2.defillama.reach", D, WARNING,
                                       f"DeFiLlama HTTP {status}"))
        except Exception as exc:           # noqa: BLE001
            out.append(CheckResult("d2.defillama.reach", D, WARNING,
                                   "DeFiLlama unreachable", error=repr(exc)))

        if live_pools is None:
            out.append(CheckResult("d2.defillama.deviation", D, SKIPPED,
                                   skipped_reason="upstream d2.defillama.reach failed"))
            return out

        ad = self.src["adapter"]
        if ad["data"] is None or not isinstance(ad["data"].get("adapters"), dict):
            out.append(CheckResult("d2.defillama.deviation", D, SKIPPED,
                                   skipped_reason="upstream adapter load failed"))
            return out

        out.append(self._check_defillama_deviation(ad["data"]["adapters"], live_pools, D))
        return out

    def _check_defillama_deviation(self, adapters: dict, live_pools, D: str) -> CheckResult:
        # Build a project->live apy map for aave/compound USDC pools (sample)
        live_by_project: dict[str, float] = {}
        try:
            for p in live_pools:
                if not isinstance(p, dict):
                    continue
                if str(p.get("symbol", "")).upper().find("USDC") < 0:
                    continue
                proj = str(p.get("project", "")).lower()
                apy = p.get("apy")
                if _is_finite_number(apy) and proj and proj not in live_by_project:
                    live_by_project[proj] = float(apy)
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d2.defillama.deviation", D, WARNING,
                               "could not parse live pools", error=repr(exc))

        sample = {"aave_v3": "aave-v3", "compound_v3": "compound-v3"}
        worst = None
        for local_name, proj_key in sample.items():
            info = adapters.get(local_name)
            if not isinstance(info, dict):
                continue
            stored = _normalize_apy(info.get("apy"), [info.get("live_apy"), info.get("fallback_apy")])
            live = live_by_project.get(proj_key)
            if stored is None or live is None or stored == 0:
                continue
            dev = abs(live - stored) / stored * 100.0
            if worst is None or dev > worst[2]:
                worst = (local_name, proj_key, dev, stored, live)
        if worst and worst[2] > DEVIATION_PCT:
            n, key, dev, stored, live = worst
            return CheckResult("d2.defillama.deviation", D, WARNING,
                               f"{n} stored {stored:.2f}% vs live {live:.2f}% ({dev:+.0f}%)",
                               value=live, expected=stored,
                               evidence={"pool": key, "live": live, "stored": stored,
                                         "deviation_pct": round(dev, 1)})
        return CheckResult("d2.defillama.deviation", D, OK, "stored APYs track live within tolerance")

    # ======================================================================
    # DOMAIN 3 — Strategy Execution Quality
    # ======================================================================
    def check_d3_strategy_quality(self) -> list[CheckResult]:
        D = "d3_strategy_quality"
        out: list[CheckResult] = []
        eq = self.src["equity"]

        # cycle.ran_today + trend7 depend on equity
        if eq["data"] is None:
            out.append(CheckResult("d3.cycle.ran_today", D, SKIPPED,
                                   skipped_reason="upstream d1.equity.exists failed"))
            out.append(CheckResult("d3.equity.trend7", D, SKIPPED,
                                   skipped_reason="upstream d1.equity.exists failed"))
        else:
            daily = eq["data"].get("daily") or []
            out.append(self._check_cycle_ran_today(daily, D))
            out.append(self._check_trend7(daily, D))

        # tournament differentiated
        tn = self.src["tournament"]
        if tn["data"] is None:
            out.append(CheckResult("d3.tournament.differentiated", D, SKIPPED,
                                   skipped_reason="upstream tournament load failed"))
        else:
            out.append(self._check_differentiated(tn["data"], D))

        # alloc cap (from current_positions)
        out.append(self._check_alloc_cap(D))
        return out

    def _check_cycle_ran_today(self, daily: list, D: str) -> CheckResult:
        if not daily:
            return CheckResult("d3.cycle.ran_today", D, CRITICAL, "no equity bars at all")
        last_raw = daily[-1].get("date")
        last_dt = _parse_ts((last_raw or "") + "T00:00:00") if last_raw else None
        if last_dt is None:
            return CheckResult("d3.cycle.ran_today", D, WARNING, "last bar date unparseable")
        stale_days = (date.today() - last_dt.date()).days
        if stale_days >= 2:
            return CheckResult("d3.cycle.ran_today", D, CRITICAL,
                               f"cycle stale {stale_days}d (last {last_raw})", value=stale_days)
        if stale_days == 1:
            return CheckResult("d3.cycle.ran_today", D, WARNING,
                               f"cycle did not run today (last {last_raw})", value=stale_days)
        return CheckResult("d3.cycle.ran_today", D, OK, f"cycle ran today ({last_raw})", value=0)

    def _check_trend7(self, daily: list, D: str) -> CheckResult:
        closes = [b.get("close_equity") for b in daily if _is_finite_number(b.get("close_equity"))]
        if len(closes) < 2:
            return CheckResult("d3.equity.trend7", D, INFO, "insufficient data for trend")
        window = closes[-8:] if len(closes) >= 8 else closes
        start, end = window[0], window[-1]
        pct = (end - start) / start * 100.0 if start else 0.0
        if pct < TREND_DECLINE_PCT:
            return CheckResult("d3.equity.trend7", D, WARNING,
                               f"7d equity declining {pct:.2f}%", value=round(pct, 2))
        direction = "growing" if pct > 0.05 else "flat"
        return CheckResult("d3.equity.trend7", D, INFO,
                           f"7d equity {direction} ({pct:+.2f}%)", value=round(pct, 2))

    def _check_differentiated(self, tdata: dict, D: str) -> CheckResult:
        strat = strat_list(tdata)
        apys = []
        for s in strat:
            if isinstance(s, dict):
                v = s.get("paper_apy", s.get("apy"))
                if _is_finite_number(v):
                    apys.append(float(v))
        if len(apys) < 2:
            return CheckResult("d3.tournament.differentiated", D, INFO,
                               "insufficient strategies to assess differentiation")
        spread = max(apys) - min(apys)
        if spread < 1e-9:
            return CheckResult("d3.tournament.differentiated", D, WARNING,
                               "all strategy APYs identical (engine likely stuck)",
                               value=0.0)
        return CheckResult("d3.tournament.differentiated", D, OK,
                           f"strategy APYs differentiated (spread {spread:.2f}%)",
                           value=round(spread, 3))

    def _check_alloc_cap(self, D: str) -> CheckResult:
        pos = self.src["positions"]
        if pos["data"] is None or not isinstance(pos["data"].get("positions"), dict):
            return CheckResult("d3.alloc.cap", D, WARNING,
                               "current_positions.json missing/unreadable",
                               error=(pos["error"] or "no positions key"))
        positions = {k: v for k, v in pos["data"]["positions"].items() if _is_finite_number(v)}
        total = sum(positions.values())
        if total <= 0:
            return CheckResult("d3.alloc.cap", D, WARNING, "zero total positions")
        over = [(k, round(v / total * 100, 1)) for k, v in positions.items()
                if v / total * 100 > ALLOC_CAP_PCT]
        if over:
            over.sort(key=lambda x: -x[1])
            return CheckResult("d3.alloc.cap", D, WARNING,
                               f"{over[0][0]} weight {over[0][1]}% > {ALLOC_CAP_PCT}% tripwire",
                               value=over[0][1], evidence={"over_cap": over[:5]})
        return CheckResult("d3.alloc.cap", D, OK, f"all allocations <= {ALLOC_CAP_PCT}%")

    # ======================================================================
    # DOMAIN 4 — External Services (network, independent probes)
    # ======================================================================
    def check_d4_external(self) -> list[CheckResult]:
        D = "d4_external"
        probes = [
            ("d4.earndefi", self._probe_earndefi),
            ("d4.github_raw", self._probe_github_raw),
            ("d4.github_rate", self._probe_github_rate),
            ("d4.local_api", self._probe_local_api),
        ]
        results: dict[str, CheckResult] = {}
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(fn): cid for cid, fn in probes}
            for fut, cid in list(futs.items()):
                try:
                    results[cid] = fut.result(timeout=NET_TIMEOUT + 5)
                except Exception as exc:   # noqa: BLE001
                    results[cid] = CheckResult(cid, D, WARNING,
                                               "probe failed/timeout", error=repr(exc))
        return [results[cid] for cid, _ in probes]

    def _probe_earndefi(self) -> CheckResult:
        D = "d4_external"
        try:
            status, _, _ = _http_get(EARNDEFI, timeout=NET_TIMEOUT)
            if status == 200:
                return CheckResult("d4.earndefi", D, OK, "earn-defi.com 200")
            return CheckResult("d4.earndefi", D, WARNING, f"earn-defi.com HTTP {status}")
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d4.earndefi", D, WARNING, "earn-defi.com unreachable", error=repr(exc))

    def _probe_github_raw(self) -> CheckResult:
        D = "d4_external"
        try:
            status, _, _ = _http_get(GITHUB_RAW, timeout=NET_TIMEOUT)
            if status == 200:
                return CheckResult("d4.github_raw", D, OK, "github raw 200")
            return CheckResult("d4.github_raw", D, WARNING, f"github raw HTTP {status}")
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d4.github_raw", D, WARNING, "github raw unreachable", error=repr(exc))

    def _probe_github_rate(self) -> CheckResult:
        D = "d4_external"
        # Authenticate via Keychain PAT when available: the autopush pipeline uses
        # the same authenticated token (ceiling 5000/hr), so this probe must measure
        # the budget actually consumed by the system — NOT the anonymous 60/hr pool,
        # which is structurally below GITHUB_RATE_FLOOR (100) and would WARN forever.
        extra_headers = None
        authed = False
        try:
            from spa_core.utils.keychain import get_github_pat
            pat = get_github_pat()
            if pat:
                extra_headers = {"Authorization": f"Bearer {pat}"}
                authed = True
        except Exception:                  # noqa: BLE001 — Keychain absent (CI/sandbox)
            extra_headers = None
        try:
            status, body, hdrs = _http_get(GITHUB_API_RATE, timeout=NET_TIMEOUT,
                                           want_headers=True, extra_headers=extra_headers)
            remaining = hdrs.get("x-ratelimit-remaining")
            limit_hdr = hdrs.get("x-ratelimit-limit")
            if (remaining is None or limit_hdr is None) and body:
                try:
                    rate = json.loads(body.decode()).get("rate", {})
                    remaining = remaining if remaining is not None else rate.get("remaining")
                    limit_hdr = limit_hdr if limit_hdr is not None else rate.get("limit")
                except Exception:          # noqa: BLE001
                    pass
            rem = int(remaining) if remaining is not None else None
            limit = int(limit_hdr) if limit_hdr is not None else None
            # Unauthenticated ceiling is 60/hr — strictly below the 100 floor, so a
            # "low" reading there is an expected environment property (no PAT), not a
            # system fault. Report it as INFO/advisory rather than a domain WARNING.
            if not authed and limit is not None and limit <= GITHUB_RATE_FLOOR:
                return CheckResult("d4.github_rate", D, INFO,
                                   f"GitHub rate unauthenticated ({rem}/{limit}) — no PAT, advisory",
                                   value=rem, expected=limit)
            if rem is not None and rem <= GITHUB_RATE_FLOOR:
                return CheckResult("d4.github_rate", D, WARNING,
                                   f"GitHub rate-limit low ({rem}/{limit})", value=rem,
                                   expected=limit)
            return CheckResult("d4.github_rate", D, OK,
                               f"GitHub rate-limit ok ({rem}/{limit})", value=rem,
                               expected=limit)
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d4.github_rate", D, WARNING, "GitHub rate API unreachable", error=repr(exc))

    def _probe_local_api(self) -> CheckResult:
        D = "d4_external"
        try:
            status, _, _ = _http_get(LOCAL_API, timeout=NET_TIMEOUT)
            return CheckResult("d4.local_api", D, OK, f"local API {status}")
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d4.local_api", D, WARNING, "local API (8765) no response", error=repr(exc))

    # ======================================================================
    # DOMAIN 5 — Code Integrity (subprocess + fs)
    # ======================================================================
    def check_d5_code_integrity(self) -> list[CheckResult]:
        D = "d5_code_integrity"
        out: list[CheckResult] = []
        out.append(self._probe_import_adapters(D))
        out.append(self._probe_import_cycle_runner(D))
        out.append(self._check_secrets(D))
        return out

    def _run_import(self, code: str) -> tuple[bool, str]:
        try:
            res = subprocess.run([sys.executable, "-c", code],
                                 cwd=str(self.project_root), capture_output=True,
                                 text=True, timeout=SUBPROC_TIMEOUT)
            return res.returncode == 0, (res.stderr or res.stdout).strip()[-300:]
        except subprocess.TimeoutExpired:
            return False, "import timed out"
        except Exception as exc:           # noqa: BLE001
            return False, repr(exc)

    def _probe_import_adapters(self, D: str) -> CheckResult:
        modules = self._t1_adapter_modules()
        code = "import importlib\n" + "".join(
            f"importlib.import_module({m!r})\n" for m in modules
        ) + "print('OK')"
        ok, msg = self._run_import(code)
        if ok:
            return CheckResult("d5.import.adapters", D, OK,
                               f"{len(modules)} T1 adapter modules import clean")
        return CheckResult("d5.import.adapters", D, CRITICAL,
                           "T1 adapter import failed", error=msg)

    def _probe_import_cycle_runner(self, D: str) -> CheckResult:
        ok, msg = self._run_import("import spa_core.paper_trading.cycle_runner; print('OK')")
        if ok:
            return CheckResult("d5.import.cycle_runner", D, OK, "cycle_runner imports clean")
        return CheckResult("d5.import.cycle_runner", D, CRITICAL,
                           "cycle_runner import failed", error=msg)

    def _check_secrets(self, D: str) -> CheckResult:
        hits = []
        for path in self._git_untracked:
            base = os.path.basename(path.rstrip("/"))
            if path.endswith(_SECRET_SAFE_SUFFIXES):
                continue
            if _SECRET_RE.search(base):
                hits.append(path)
        if hits:
            return CheckResult("d5.security.secrets", D, CRITICAL,
                               f"{len(hits)} untracked secret-like file(s)",
                               evidence={"paths": hits[:10]})
        return CheckResult("d5.security.secrets", D, OK, "no untracked secret-like files")

    # ======================================================================
    # DOMAIN 6 — Financial Risk Gates
    # ======================================================================
    def check_d6_risk_gates(self) -> list[CheckResult]:
        D = "d6_risk_gates"
        # Each gate is isolated: a transient error in ONE sub-check (e.g. a
        # data/*.json being rewritten under us by a live agent during a test or
        # an in-flight cycle) is reported as a WARNING for THAT gate only — it
        # must NOT abort the whole domain and blank the other gates' verdicts.
        # On the happy path (all sub-checks succeed) the output is identical, so
        # this only changes the rare error path and makes d6 order/state-robust.
        gates = (
            ("d6.t2.cap", self._check_t2_cap),
            ("d6.health", self._check_portfolio_health),
            ("d6.red_flags", self._check_red_flags),
            ("d6.killswitch", self._check_killswitch),
            ("d6.safety_state", self._check_safety_state),
        )
        out: list[CheckResult] = []
        for cid, fn in gates:
            try:
                out.append(fn(D))
            except Exception as exc:           # noqa: BLE001 — one bad gate must not blind the rest
                out.append(CheckResult(cid, D, WARNING,
                                       "gate check raised (transient/state)", error=repr(exc)))
        return out

    def _check_t2_cap(self, D: str) -> CheckResult:
        ad = self.src["adapter"]
        pos = self.src["positions"]
        if ad["data"] is None or not isinstance(ad["data"].get("adapters"), dict):
            return CheckResult("d6.t2.cap", D, SKIPPED,
                               skipped_reason="upstream adapter load failed")
        if pos["data"] is None or not isinstance(pos["data"].get("positions"), dict):
            return CheckResult("d6.t2.cap", D, WARNING,
                               "current_positions.json missing — cannot compute T2 concentration",
                               error=(pos["error"] or "no positions key"))
        adapters = ad["data"]["adapters"]
        positions = {k: v for k, v in pos["data"]["positions"].items() if _is_finite_number(v)}
        total = sum(positions.values())
        if total <= 0:
            return CheckResult("d6.t2.cap", D, WARNING, "zero total positions")
        t2_sum = 0.0
        for name, val in positions.items():
            info = adapters.get(name)
            tier_raw = info.get("tier") if isinstance(info, dict) else None
            tier, _unknown = _normalize_tier(tier_raw)
            if tier == "T2":
                t2_sum += val
        t2_pct = t2_sum / total * 100.0
        if t2_pct > T2_CAP_PCT:
            return CheckResult("d6.t2.cap", D, CRITICAL,
                               f"T2 concentration {t2_pct:.1f}% > {T2_CAP_PCT}% (ADR-019 breach)",
                               value=round(t2_pct, 1), expected=T2_CAP_PCT)
        return CheckResult("d6.t2.cap", D, OK,
                           f"T2 concentration {t2_pct:.1f}% <= {T2_CAP_PCT}%",
                           value=round(t2_pct, 1), expected=T2_CAP_PCT)

    def _check_portfolio_health(self, D: str) -> CheckResult:
        ph = self.src["portfolio_health"]
        if ph["data"] is None:
            return CheckResult("d6.health", D, WARNING,
                               "no portfolio health score (absence != breach)", error=ph["error"])
        data = ph["data"]
        # Read the ACTUAL key the writer emits (health_score) via the one shared
        # helper both monitors use — not a per-module key guess (N8).
        score = _read_portfolio_health_score(data)
        if not _is_finite_number(score):
            return CheckResult("d6.health", D, WARNING, "portfolio health score not numeric")
        if score < PORTFOLIO_HEALTH_FLOOR:
            return CheckResult("d6.health", D, CRITICAL,
                               f"portfolio health {score} < {PORTFOLIO_HEALTH_FLOOR}",
                               value=score, expected=PORTFOLIO_HEALTH_FLOOR)
        return CheckResult("d6.health", D, OK, f"portfolio health {score}",
                           value=score, expected=PORTFOLIO_HEALTH_FLOOR)

    def _check_red_flags(self, D: str) -> CheckResult:
        rf = self.src["red_flags"]
        if rf["data"] is None:
            return CheckResult("d6.red_flags", D, WARNING,
                               "red_flags.json unreadable", error=rf["error"])
        flags = rf["data"].get("red_flags") if isinstance(rf["data"], dict) else rf["data"]
        if not isinstance(flags, list):
            return CheckResult("d6.red_flags", D, WARNING, "red_flags not a list")
        # Match the SET of critical severities (CRITICAL/CRIT/FATAL/...) from the
        # shared vocabulary — NOT a single literal — so a red_flag_monitor change
        # to the exact spelling cannot silently disable critical detection (N8).
        crit = [f for f in flags if isinstance(f, dict)
                and _is_critical_severity(f.get("severity"))]
        if crit:
            # A red flag concerns an EXTERNAL protocol's market conditions, not a
            # failure of SPA itself. It is CRITICAL only when it hits a protocol we
            # actually hold; flags on protocols we don't hold — or from fallback/
            # bootstrap data (live feed down) — are advisory (WARNING). Mirrors
            # agent_health_monitor's red-flag handling.
            pos = self.src.get("positions", {}).get("data") or {}
            held = {str(k).lower() for k in (pos.get("positions") or {})}
            fallback = bool(rf["data"].get("fallback_used")) if isinstance(rf["data"], dict) else False

            def _hits_held(flag: dict) -> bool:
                proto = str(flag.get("protocol", "")).lower().replace("-", "_")
                return any(h and (h in proto or proto in h) for h in held)

            held_crit = [] if fallback else [f for f in crit if _hits_held(f)]
            if held_crit:
                return CheckResult("d6.red_flags", D, CRITICAL,
                                   f"{len(held_crit)} CRITICAL red flag(s) on HELD protocols",
                                   evidence={"flags": [f.get("message", f.get("protocol", "?")) for f in held_crit[:5]]})
            # Flags only on EXTERNAL (non-held) protocols are market intelligence, not
            # a risk-gate defect. They are advisory context (INFO) and MUST NOT escalate
            # the d6 domain to WARNING — the gates themselves (health/t2.cap/killswitch)
            # are what gate live risk. Mirrors agent_health_monitor's advisory handling.
            return CheckResult("d6.red_flags", D, INFO,
                               f"{len(crit)} red flag(s) on external protocols (advisory)",
                               evidence={"flags": [f.get("message", f.get("protocol", "?")) for f in crit[:5]]})
        return CheckResult("d6.red_flags", D, OK,
                           f"no CRITICAL red flags ({len(flags)} total)")

    def _check_killswitch(self, D: str) -> CheckResult:
        """DRY read-only probe: KillSwitchChecker.is_kill_switch_active() evaluates
        all triggers and returns (bool, reason) WITHOUT writing/activating anything."""
        code = (
            "from spa_core.governance.kill_switch import KillSwitchChecker\n"
            "c = KillSwitchChecker(data_dir=%r)\n"
            "t, r = c.is_kill_switch_active()\n"
            "print('KS', bool(t), repr(r))\n" % str(self.data_dir)
        )
        try:
            res = subprocess.run([sys.executable, "-c", code],
                                 cwd=str(self.project_root), capture_output=True,
                                 text=True, timeout=SUBPROC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return CheckResult("d6.killswitch", D, CRITICAL, "kill-switch dry probe timed out")
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d6.killswitch", D, CRITICAL,
                               "kill-switch dry probe error", error=repr(exc))
        if res.returncode != 0 or "KS " not in res.stdout:
            return CheckResult("d6.killswitch", D, CRITICAL,
                               "kill-switch probe did not report a plan",
                               error=(res.stderr or res.stdout).strip()[-300:])
        line = [l for l in res.stdout.splitlines() if l.startswith("KS ")][-1]
        triggered = "True" in line.split(" ", 2)[1]
        if triggered:
            return CheckResult("d6.killswitch", D, CRITICAL,
                               "kill-switch DRY reports a trigger active",
                               evidence={"report": line[3:]})
        return CheckResult("d6.killswitch", D, OK,
                           "kill-switch DRY responds (no trigger)", evidence={"report": line[3:]})

    def _check_safety_state(self, D: str) -> CheckResult:
        """Make the TWO-TIER safety state OBSERVABLE (D3-T3, ADR-034).

        A safety state the owner can't SEE is a blind spot. The two-tier
        kill-switch added two new persisted states that were invisible to the
        health surface until now:

          * SOFT de-risk (``data/derisk_status.json`` ``active=true``) — the
            cycle has halted new allocations / blocked increases on a 5–15%
            evidenced drawdown (NOT all-cash). Reported as **WARNING**.
          * HARD kill / all-cash (``data/kill_switch_active.json`` present with
            ``active != False``, or ``kill_switch_status.json`` ``triggered``)
            — the book is closed to cash. Reported as **CRITICAL**.

        Read-only, fail-CLOSED, and edge-honest:
          * Both files absent/clear → OK ("no safety state active").
          * A de-risk file that is STALE (its ``generated_at`` is older than
            DERISK_FRESH_H, or unparseable) is flagged — a stale safety snapshot
            must look stale, never silently authoritative. A stale *active*
            de-risk stays WARNING (its claim may be outdated, but a possibly-live
            de-risk is worth surfacing); a stale *inactive* de-risk is INFO.
          * A corrupt/unreadable status file is reported WARNING (cannot verify),
            never silently OK.

        This is the OBSERVABILITY surface; it never writes/activates anything
        and is parallel to ``_check_killswitch`` (which DRY-evaluates triggers).
        """
        cid = "d6.safety_state"

        # ── HARD kill / all-cash state (highest severity) ─────────────────────
        active_doc, active_err = self._load_json("kill_switch_active.json")
        kill_active = False
        if active_doc is not None:
            # File present. active=False is an explicit deactivation marker.
            if isinstance(active_doc, dict) and active_doc.get("active") is False:
                kill_active = False
            else:
                kill_active = True
        elif active_err and active_err != "missing":
            # Unreadable kill-switch marker → cannot verify, fail-loud (WARNING).
            return CheckResult(cid, D, WARNING,
                               "kill_switch_active.json unreadable — cannot verify kill state",
                               error=active_err)

        # Corroborate with kill_switch_status.json (cycle-written verdict).
        status_doc, _status_err = self._load_json("kill_switch_status.json")
        status_triggered = (isinstance(status_doc, dict)
                            and status_doc.get("triggered") is True)

        if kill_active or status_triggered:
            reason = ""
            if isinstance(active_doc, dict):
                reason = str(active_doc.get("reason") or "")
            if not reason and isinstance(status_doc, dict):
                reason = str(status_doc.get("reason") or "")
            return CheckResult(cid, D, CRITICAL,
                               "HARD kill ACTIVE — book is all-cash"
                               + (f": {reason}" if reason else ""),
                               value="HARD_KILL",
                               evidence={"reason": reason,
                                         "kill_switch_active": kill_active,
                                         "status_triggered": status_triggered})

        # ── SOFT de-risk state ────────────────────────────────────────────────
        derisk_doc, derisk_err = self._load_json("derisk_status.json")
        if derisk_doc is None:
            if derisk_err and derisk_err != "missing":
                return CheckResult(cid, D, WARNING,
                                   "derisk_status.json unreadable — cannot verify de-risk state",
                                   error=derisk_err)
            # Absent entirely → de-risk never fired (clean). No kill either → OK.
            return CheckResult(cid, D, OK,
                               "no safety state active (no de-risk, no kill)",
                               value="CLEAR")

        if not isinstance(derisk_doc, dict):
            return CheckResult(cid, D, WARNING,
                               "derisk_status.json malformed — cannot verify de-risk state")

        derisk_active = bool(derisk_doc.get("active"))
        tier = derisk_doc.get("tier")
        dr_reason = str(derisk_doc.get("reason") or "")
        age = _age_hours(derisk_doc.get("generated_at"))
        stale = (age is None) or (age > DERISK_FRESH_H)
        ev = {"tier": tier, "reason": dr_reason,
              "age_hours": round(age, 1) if age is not None else None,
              "stale": stale}

        if derisk_active:
            # A stale-but-active de-risk is still surfaced as WARNING (a possibly
            # live de-risk the owner must see), with the staleness noted.
            suffix = f": {dr_reason}" if dr_reason else ""
            if stale:
                return CheckResult(cid, D, WARNING,
                                   "SOFT de-risk ACTIVE (snapshot STALE — verify cycle)"
                                   + suffix, value="SOFT_DERISK", evidence=ev)
            return CheckResult(cid, D, WARNING,
                               "SOFT de-risk ACTIVE — new allocations/increase halted"
                               + suffix, value="SOFT_DERISK", evidence=ev)

        # Inactive de-risk. If the snapshot is stale, flag it (INFO) so a frozen
        # writer doesn't masquerade as a confidently-clear state; else OK.
        if stale:
            return CheckResult(cid, D, INFO,
                               "de-risk inactive but snapshot STALE (cycle may be lagging)",
                               value="CLEAR", evidence=ev)
        return CheckResult(cid, D, OK,
                           "no safety state active (de-risk inactive, fresh)",
                           value="CLEAR", evidence=ev)

    # ======================================================================
    # DOMAIN 7 — Operational Hygiene
    # ======================================================================
    def check_d7_hygiene(self) -> list[CheckResult]:
        D = "d7_hygiene"
        return [self._check_kanban(D), self._check_logs(D), self._check_clutter(D)]

    def _check_kanban(self, D: str) -> CheckResult:
        path = self.project_root / "KANBAN.json"
        try:
            if not path.exists():
                return CheckResult("d7.kanban.stale", D, WARNING, "KANBAN.json missing")
            kb = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d7.kanban.stale", D, WARNING, "KANBAN.json unreadable", error=repr(exc))
        ip = (kb.get("columns") or {}).get("in_progress") or []
        stale = []
        for task in ip:
            if not isinstance(task, dict):
                continue
            age = _age_hours(task.get("moved_to_in_progress") or task.get("started_at"))
            if age is not None and age / 24.0 > KANBAN_STALE_DAYS:
                stale.append((task.get("id", "?"), round(age / 24.0, 1)))
        if stale:
            return CheckResult("d7.kanban.stale", D, WARNING,
                               f"{len(stale)} task(s) in_progress > {KANBAN_STALE_DAYS}d",
                               evidence={"stale": stale[:5]})
        return CheckResult("d7.kanban.stale", D, OK,
                           f"no stale in_progress tasks ({len(ip)} active)")

    def _check_logs(self, D: str) -> CheckResult:
        total = 0
        try:
            for p in glob.glob("/tmp/spa_*.log"):
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d7.logs.size", D, WARNING, "log scan failed", error=repr(exc))
        mb = total / 1024 / 1024
        if total > LOGS_SIZE_LIMIT_BYTES:
            return CheckResult("d7.logs.size", D, WARNING,
                               f"/tmp/spa_*.log total {mb:.0f}MB > 500MB", value=round(mb, 1))
        return CheckResult("d7.logs.size", D, OK, f"/tmp/spa_*.log total {mb:.0f}MB", value=round(mb, 1))

    def _check_clutter(self, D: str) -> CheckResult:
        try:
            n = len(glob.glob(str(self.project_root / "push_*")))
        except Exception as exc:           # noqa: BLE001
            return CheckResult("d7.scripts.clutter", D, INFO, "clutter scan failed", error=repr(exc))
        if n > SCRIPTS_CLUTTER_LIMIT:
            return CheckResult("d7.scripts.clutter", D, INFO,
                               f"{n} push_* scripts in repo root (> {SCRIPTS_CLUTTER_LIMIT})", value=n)
        return CheckResult("d7.scripts.clutter", D, OK, f"{n} push_* scripts in repo root", value=n)

    # ======================================================================
    # DOMAIN d_dfb — DFB (DeFi Board, Lane 2) standing-pipeline health
    # ======================================================================
    def check_d_dfb_defi_board(self) -> list[CheckResult]:
        """Health of the STANDING DFB risk-overlay pipeline (Lane 2).

        Four fail-CLOSED checks over the snapshot the dfb_capture agent maintains:

          * d_dfb.snapshot.fresh   — data/dfb/pools.json present + refreshed within
            DFB_FRESH_H (the daily-capture cadence + slack). A STALE / missing snapshot
            means the capture agent is down → WARNING (NEVER silently OK).
          * d_dfb.chain.valid      — the snapshot's own `chain_valid` flag is True
            (the per-row proof chain re-derives). A broken/absent chain → WARNING.
          * d_dfb.unknown.canary   — the UNKNOWN-graded ratio is below the feed-outage
            canary. A runaway UNKNOWN ratio = the live feed broke (the overlay fails
            CLOSED to UNKNOWN) → WARNING.
          * d_dfb.capture.heartbeat — the dfb_capture agent wrapper log
            (/tmp/spa_dfb_capture.log) was written within DFB_FRESH_H. A cold/absent
            heartbeat → WARNING (the standing agent is not running).

        Each sub-check is isolated (one error never blinds the rest). All read-only;
        this domain writes / activates nothing. fail-CLOSED throughout: a missing
        artifact is a WARNING, never a silent pass.
        """
        D = "d_dfb_defi_board"
        checks = (
            ("d_dfb.snapshot.fresh", self._check_dfb_snapshot),
            ("d_dfb.chain.valid", self._check_dfb_chain),
            ("d_dfb.unknown.canary", self._check_dfb_unknown_canary),
            ("d_dfb.capture.heartbeat", self._check_dfb_capture_heartbeat),
        )
        out: list[CheckResult] = []
        for cid, fn in checks:
            try:
                out.append(fn(D))
            except Exception as exc:           # noqa: BLE001 — one bad check must not blind the rest
                out.append(CheckResult(cid, D, WARNING, f"{cid} raised — cannot verify",
                                       error=repr(exc)))
        return out

    def _load_dfb_pools(self) -> tuple[Optional[dict], Optional[str]]:
        """Load data/dfb/pools.json (the overlay snapshot wrapper). Cached per-run."""
        cache = getattr(self, "_dfb_cache", "unset")
        if cache != "unset":
            return cache
        doc, err = self._load_json("dfb/pools.json")
        self._dfb_cache = (doc, err)
        return self._dfb_cache

    def _check_dfb_snapshot(self, D: str) -> CheckResult:
        """data/dfb/pools.json present + fresh (capture agent ran within its cadence)."""
        cid = "d_dfb.snapshot.fresh"
        doc, err = self._load_dfb_pools()
        if doc is None:
            # Missing OR unreadable → cannot verify the board is being maintained.
            return CheckResult(cid, D, WARNING,
                               "dfb/pools.json missing/unreadable — capture agent may be down",
                               error=err)
        if not isinstance(doc, dict):
            return CheckResult(cid, D, WARNING, "dfb/pools.json malformed (not an object)")
        age = _age_hours(doc.get("generated_at"))
        n_pools = doc.get("n_pools")
        ev = {"n_pools": n_pools,
              "age_hours": round(age, 1) if age is not None else None,
              "generated_at": doc.get("generated_at")}
        if age is None:
            return CheckResult(cid, D, WARNING,
                               "dfb/pools.json has no parseable generated_at — cannot verify freshness",
                               evidence=ev)
        if age > DFB_FRESH_H:
            return CheckResult(cid, D, WARNING,
                               f"dfb/pools.json STALE ({age:.1f}h > {DFB_FRESH_H:.0f}h) — "
                               "capture agent presumed down", value=round(age, 1), evidence=ev)
        return CheckResult(cid, D, OK,
                           f"dfb/pools.json fresh ({age:.1f}h, {n_pools} pools)",
                           value=round(age, 1), evidence=ev)

    def _check_dfb_chain(self, D: str) -> CheckResult:
        """The snapshot's per-row proof chain re-derives (chain_valid == True)."""
        cid = "d_dfb.chain.valid"
        doc, err = self._load_dfb_pools()
        if not isinstance(doc, dict):
            return CheckResult(cid, D, WARNING,
                               "dfb/pools.json absent/malformed — cannot verify proof chain",
                               error=err)
        chain_valid = doc.get("chain_valid")
        if chain_valid is True:
            return CheckResult(cid, D, OK, "dfb overlay proof chain valid (chain_valid=true)")
        return CheckResult(cid, D, WARNING,
                           "dfb overlay proof chain NOT valid (chain_valid != true) — "
                           "a row may be forged/reordered/dropped", value=chain_valid)

    def _check_dfb_unknown_canary(self, D: str) -> CheckResult:
        """UNKNOWN-ratio feed-outage canary: a runaway UNKNOWN ratio = the live feed broke."""
        cid = "d_dfb.unknown.canary"
        doc, err = self._load_dfb_pools()
        if not isinstance(doc, dict):
            return CheckResult(cid, D, WARNING,
                               "dfb/pools.json absent/malformed — cannot evaluate UNKNOWN canary",
                               error=err)
        n_pools = doc.get("n_pools")
        n_unknown = doc.get("n_unknown")
        if not isinstance(n_pools, int) or n_pools <= 0:
            # No pools at all → the board is empty; the freshness check already WARNs,
            # but an empty universe also cannot be graded → fail-CLOSED here too.
            return CheckResult(cid, D, WARNING,
                               "dfb universe empty/uncountable — cannot evaluate UNKNOWN canary",
                               value=n_pools)
        if not isinstance(n_unknown, int):
            return CheckResult(cid, D, WARNING,
                               "dfb n_unknown missing — cannot evaluate feed-outage canary")
        ratio = n_unknown / n_pools
        ev = {"n_unknown": n_unknown, "n_pools": n_pools, "ratio": round(ratio, 3)}
        if ratio > DFB_UNKNOWN_RATIO_WARN:
            return CheckResult(cid, D, WARNING,
                               f"UNKNOWN ratio {ratio:.0%} > {DFB_UNKNOWN_RATIO_WARN:.0%} — "
                               "feed-outage canary (live overlay feed may be down)",
                               value=round(ratio, 3), evidence=ev)
        return CheckResult(cid, D, OK,
                           f"UNKNOWN ratio {ratio:.0%} within canary "
                           f"({n_unknown}/{n_pools})", value=round(ratio, 3), evidence=ev)

    def _check_dfb_capture_heartbeat(self, D: str) -> CheckResult:
        """The dfb_capture agent wrapper log (/tmp/spa_dfb_capture.log) was written recently."""
        cid = "d_dfb.capture.heartbeat"
        log_path = "/tmp/spa_dfb_capture.log"
        try:
            if not os.path.exists(log_path):
                return CheckResult(cid, D, WARNING,
                                   "dfb_capture agent log absent — agent never ran on this host",
                                   value=None)
            mtime = os.path.getmtime(log_path)
        except OSError as exc:
            return CheckResult(cid, D, WARNING, "dfb_capture log unreadable — cannot verify heartbeat",
                               error=repr(exc))
        age_h = (_now().timestamp() - mtime) / 3600.0
        ev = {"log": log_path, "age_hours": round(age_h, 1)}
        if age_h > DFB_FRESH_H:
            return CheckResult(cid, D, WARNING,
                               f"dfb_capture heartbeat STALE ({age_h:.1f}h > {DFB_FRESH_H:.0f}h) — "
                               "standing agent not running", value=round(age_h, 1), evidence=ev)
        return CheckResult(cid, D, OK,
                           f"dfb_capture heartbeat fresh ({age_h:.1f}h)",
                           value=round(age_h, 1), evidence=ev)

    # ======================================================================
    # registry helpers
    # ======================================================================
    def _registry(self):
        try:
            from spa_core.adapters import ADAPTER_REGISTRY
            return list(ADAPTER_REGISTRY)
        except Exception as exc:           # noqa: BLE001
            log.warning("ADAPTER_REGISTRY unavailable: %s", exc)
            return []

    def _expected_t1_adapters(self) -> list[str]:
        reg = self._registry()
        t1 = [n for (n, t, _c) in reg if _normalize_tier(t)[0] == "T1"]
        return t1 or ["aave_v3", "compound_v3", "morpho_steakhouse"]

    def _t1_adapter_modules(self) -> list[str]:
        reg = self._registry()
        mods = []
        for (n, t, c) in reg:
            if _normalize_tier(t)[0] == "T1":
                mod = getattr(c, "__module__", None)
                if mod and mod not in mods:
                    mods.append(mod)
        return mods or ["spa_core.adapters.aave_v3"]

    # ======================================================================
    # previous-run helpers
    # ======================================================================
    def _load_previous(self) -> Optional[dict]:
        path = self.data_dir / "system_health.json"
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:           # noqa: BLE001
            log.warning("could not load previous health: %s", exc)
        return None

    def _prev_golive_passed(self) -> Optional[int]:
        prev = getattr(self, "_prev_cache", None)
        if prev is None:
            prev = self._load_previous()
            self._prev_cache = prev
        if prev and isinstance(prev.get("trend"), dict):
            return prev["trend"].get("golive_passed")
        return None

    # ======================================================================
    # collect / run
    # ======================================================================
    def collect(self) -> dict:
        started = _now()
        self._prev_cache = self._load_previous()
        self._prelude()

        domain_methods = [
            ("d1", "d1_data_pipeline", self.check_d1_data_pipeline),
            ("d2", "d2_connectivity", self.check_d2_connectivity),
            ("d3", "d3_strategy_quality", self.check_d3_strategy_quality),
            ("d4", "d4_external", self.check_d4_external),
            ("d5", "d5_code_integrity", self.check_d5_code_integrity),
            ("d6", "d6_risk_gates", self.check_d6_risk_gates),
            ("d7", "d7_hygiene", self.check_d7_hygiene),
            ("d_dfb", "d_dfb_defi_board", self.check_d_dfb_defi_board),
        ]

        checks: list[CheckResult] = []
        domains: dict[str, dict] = {}
        for short, dname, method in domain_methods:
            d_start = _now()
            budget = _DOMAIN_BUDGET.get(short, 30)
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    results = ex.submit(method).result(timeout=budget)
            except FuturesTimeout:
                results = [CheckResult(f"{short}.budget", dname, SKIPPED,
                                       f"{dname} exceeded {budget}s budget",
                                       skipped_reason="budget")]
            except Exception as exc:       # noqa: BLE001
                results = [CheckResult(f"{short}.error", dname, WARNING,
                                       f"{dname} raised", error=repr(exc))]
            ms = int((_now() - d_start).total_seconds() * 1000)
            checks.extend(results)
            domains[dname] = {"status": _worst([r.status for r in results]), "ms": ms}

        # roll-up
        overall = _worst([c.status for c in checks])
        counts = {CRITICAL: 0, WARNING: 0, INFO: 0, SKIPPED: 0, OK: 0}
        for c in checks:
            counts[c.status] = counts.get(c.status, 0) + 1

        fingerprint = self._fingerprint(checks)
        trend = self._build_trend(checks)
        run_id = started.strftime("%Y%m%dT%H%M")
        duration_ms = int((_now() - started).total_seconds() * 1000)

        report = {
            "schema_version": 1,
            "generated_at": started.isoformat().replace("+00:00", "Z"),
            "generated_by": "system_health_monitor",
            "run_id": run_id,
            "overall_status": overall,
            "fingerprint": fingerprint,
            "duration_ms": duration_ms,
            "counts": counts,
            "domains": domains,
            "checks": [c.to_dict() for c in sorted(checks, key=lambda x: x.id)],
            "trend": trend,
            "history": self._build_history(run_id, overall, counts, fingerprint, trend),
        }
        return report

    def _fingerprint(self, checks: list[CheckResult]) -> str:
        keys = sorted(f"{c.id}:{c.status}" for c in checks if c.status in (CRITICAL, WARNING))
        return hashlib.sha1("|".join(keys).encode()).hexdigest()[:8]

    @staticmethod
    def _critical_ids(checks_or_report) -> set:
        if isinstance(checks_or_report, dict):
            items = checks_or_report.get("checks", [])
            return {c["id"] for c in items if c.get("status") == CRITICAL}
        return {c.id for c in checks_or_report if c.status == CRITICAL}

    def _build_trend(self, checks: list[CheckResult]) -> dict:
        eq7 = None
        direction = "unknown"
        for c in checks:
            if c.id == "d3.equity.trend7" and _is_finite_number(c.value):
                eq7 = c.value
                direction = ("declining" if eq7 < TREND_DECLINE_PCT
                             else "growing" if eq7 > 0.05 else "flat")
        gl = self.src.get("golive", {}).get("data") or {}
        passed = gl.get("passed")
        total = gl.get("total")
        prev_passed = self._prev_golive_passed()
        delta = (passed - prev_passed) if isinstance(passed, int) and isinstance(prev_passed, int) else 0
        return {
            "equity_7d_pct": eq7,
            "equity_direction": direction,
            "golive_passed": passed,
            "golive_total": total,
            "golive_delta": delta,
        }

    def _build_history(self, run_id, overall, counts, fingerprint, trend) -> list:
        prev = self._prev_cache or {}
        hist = list(prev.get("history") or [])
        hist.append({
            "run_id": run_id,
            "overall_status": overall,
            "counts": {k: counts.get(k, 0) for k in (CRITICAL, WARNING, INFO)},
            "fingerprint": fingerprint,
            "equity_7d_pct": trend.get("equity_7d_pct"),
        })
        return hist[-_HISTORY_MAX:]

    def _new_critical(self, report: dict, prev: Optional[dict]) -> bool:
        """Page ONLY when a genuinely NEW critical appeared since the previous run.

        Returns True iff ``current_criticals - previous_criticals`` is non-empty.
        Using set difference (rather than set inequality) means:
          * the documented pre-dawn self-healing dip — which transiently drops the
            golive count and then RECOVERS the same critical set — does NOT re-page
            on every run that shares an unchanged (or shrinking) critical set;
          * a critical CLEARING (set shrinks) is not a page;
          * a NEW critical id (set grows) IS a page.
        This stops the false-CRITICAL spam that erodes trust and burns the
        Telegram budget, while still paging on real new failures. (N9)
        """
        cur = self._critical_ids(report)
        if not cur:
            return False
        prev_set = self._critical_ids(prev) if prev else set()
        new_criticals = cur - prev_set
        return bool(new_criticals)

    # -- formatting ---------------------------------------------------------
    def _format_page(self, report: dict) -> str:
        crit = [c for c in report["checks"] if c["status"] == CRITICAL]
        lines = [f"🚨 <b>SPA SYSTEM HEALTH — CRITICAL</b> ({report['run_id']})"]
        for c in crit:
            lines.append(f"• <code>{c['id']}</code>: {c['title']}")
        return "\n".join(lines)

    def _format_summary(self, report: dict) -> str:
        emoji = {OK: "✅", INFO: "ℹ️", WARNING: "⚠️", CRITICAL: "🚨"}
        st = report["overall_status"]
        c = report["counts"]
        lines = [
            f"{emoji.get(st, '❔')} <b>SPA System Health</b> — {st} ({report['run_id']})",
            f"C{c.get(CRITICAL,0)} · W{c.get(WARNING,0)} · I{c.get(INFO,0)} · "
            f"S{c.get(SKIPPED,0)} · OK{c.get(OK,0)}",
        ]
        drow = " ".join(f"{k.split('_')[0]}:{v['status'][0]}" for k, v in report["domains"].items())
        lines.append(f"<code>{drow}</code>")
        problems = [c for c in report["checks"] if c["status"] in (CRITICAL, WARNING)]
        for p in problems[:12]:
            ic = "🚨" if p["status"] == CRITICAL else "⚠️"
            lines.append(f"{ic} <code>{p['id']}</code>: {p['title']}")
        t = report["trend"]
        e7 = t.get("equity_7d_pct")
        lines.append(f"📈 7d {e7:+.2f}% ({t.get('equity_direction')}) · "
                     f"GoLive {t.get('golive_passed')}/{t.get('golive_total')}"
                     if _is_finite_number(e7) else
                     f"GoLive {t.get('golive_passed')}/{t.get('golive_total')}")
        return "\n".join(lines)

    def run(self, send: bool = True) -> dict:
        report = self.collect()
        prev = self._prev_cache
        if send:
            try:
                # Phase-1 Telegram rebuild: CRITICAL system health is a genuine
                # Tier-1 interrupt → push_policy (edge-triggered: one push on
                # entry, silent while it persists, RESOLVED on recovery). The
                # twice-daily summary is informational → digest queue (folded
                # into the one daily digest), never pushed.
                if report["overall_status"] == CRITICAL:
                    _push_system_critical(self._format_page(report))
                else:
                    _resolve_system_critical()
                _digest_summary(self._format_summary(report))
            except Exception as exc:       # noqa: BLE001
                log.warning("telegram dispatch failed: %s", exc)
        try:
            from spa_core.utils.atomic import atomic_save
            atomic_save(report, str(self.data_dir / "system_health.json"))
        except Exception as exc:           # noqa: BLE001
            log.warning("atomic_save failed: %s", exc)
        return report


# ---------------------------------------------------------------------------
# Module-level helpers for tournament shape (tolerant to both file variants)
# ---------------------------------------------------------------------------
def strat_list(tdata: dict) -> list:
    if not isinstance(tdata, dict):
        return []
    for key in ("ranked_strategies", "strategies", "results"):
        v = tdata.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            return list(v.values())
    return []


def _push_system_critical(msg: str) -> bool:
    """Route CRITICAL system health through the SINGLE push authority (Tier-1)."""
    try:
        from spa_core.telegram import push_policy
        return bool(
            push_policy.push_critical(
                "system_critical",
                "CRITICAL",
                "SPA System Health — CRITICAL",
                msg,
            )
        )
    except Exception as exc:               # noqa: BLE001
        log.warning("system_health: push_policy send failed: %s", exc)
        return False


def _resolve_system_critical() -> None:
    """Emit the single edge-triggered RESOLVED when health recovers (no-op else)."""
    try:
        from spa_core.telegram import push_policy
        push_policy.resolve(
            "system_critical",
            "SPA System Health — recovered",
            "System health is OK again.",
        )
    except Exception:                      # noqa: BLE001
        pass


def _digest_summary(msg: str) -> None:
    """Route the twice-daily health summary to the digest queue (never a push)."""
    try:
        from spa_core.telegram import push_policy
        push_policy._enqueue_digest(
            push_policy._tg_dir(),
            {
                "ts": push_policy._now_iso(),
                "event_key": "system_health_summary",
                "severity": "INFO",
                "title": "System health summary",
                "body": (msg or "")[:500],
                "reason": "system_health_summary_digest",
            },
        )
    except Exception:                      # noqa: BLE001
        pass


# ===========================================================================
# CLI
# ===========================================================================
def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="SPA system-level health monitor (semantic/outcome).")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="compute + write + print, NO telegram")
    g.add_argument("--run", action="store_true", help="compute + write + SEND telegram")
    p.add_argument("--data-dir", default=None)
    a = p.parse_args(argv)
    try:
        mon = SystemHealthMonitor(data_dir=a.data_dir)
        report = mon.run(send=bool(a.run))
        if not a.run:                       # --check (default) prints summary
            print(f"overall_status: {report['overall_status']}  "
                  f"fingerprint={report['fingerprint']}  ({report['duration_ms']}ms)")
            print("counts:", json.dumps(report["counts"]))
            print("domains:")
            for d, info in report["domains"].items():
                print(f"  {d:24s} {info['status']:8s} {info['ms']:>6}ms")
            print("non-OK checks:")
            for c in report["checks"]:
                if c["status"] not in (OK,):
                    print(f"  [{c['status']:8s}] {c['id']:32s} {c['title']}")
    except Exception as exc:               # noqa: BLE001 — ultimate fail-safe
        logging.exception("system_health crashed: %s", exc)
    return 0                                # ALWAYS exit 0


if __name__ == "__main__":
    sys.exit(main())
