"""
spa_core/monitoring/rules_watchdog.py — Rules Watchdog

Постоянный мониторинг всех правил политики SPA.
Запускается каждые 300 секунд через launchd com.spa.rules_watchdog.

LLM_FORBIDDEN: только детерминированные проверки.

Checks:
  - check_position_limits      (каждый вызов)
  - check_t1_concentration     (каждый вызов)
  - check_adapter_status       (каждый вызов)
  - check_circuit_breaker      (каждый вызов)
  - check_apy_coherence        (каждый вызов)
  - check_llm_forbidden_violations (каждый вызов)

Пишет: data/watchdog_report.json
Алерт: Telegram при любом критическом нарушении
Exit code: 1 если есть критические нарушения, 0 иначе

Использование:
    python3 -m spa_core.monitoring.rules_watchdog
    python3 -m spa_core.monitoring.rules_watchdog --once  # один прогон
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("spa.monitoring.rules_watchdog")

_REPO = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPO / "data"
_POSITIONS_PATH  = _DATA_DIR / "current_positions.json"
_ADAPTER_PATH    = _DATA_DIR / "adapter_status.json"
_GOLIVE_PATH     = _DATA_DIR / "golive_status.json"
_PAPER_PATH      = _DATA_DIR / "paper_trading_status.json"
_WATCHDOG_PATH   = _DATA_DIR / "watchdog_report.json"
_KILL_SWITCH_PATH = _DATA_DIR / "kill_switch.json"

_WATCHDOG_HISTORY_CAP = 500
_HTTP_TIMEOUT = 10

# LLM_FORBIDDEN component patterns to detect in import errors / code
_LLM_FORBIDDEN_MODULES = {
    "spa_core.risk",
    "spa_core.execution",
    "spa_core.monitoring",
}


# ── Keychain / Telegram helpers ─────────────────────────────────────────────

def _read_keychain(service: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
            return val if val else None
    except Exception:
        pass
    return None


def _get_tg_creds() -> tuple:
    token = _read_keychain("TELEGRAM_BOT_TOKEN_SPA") or os.environ.get(
        "TELEGRAM_BOT_TOKEN_SPA"
    ) or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = _read_keychain("TELEGRAM_CHAT_ID_SPA") or os.environ.get(
        "TELEGRAM_CHAT_ID_SPA"
    ) or os.environ.get("TELEGRAM_CHAT_ID")
    return token, chat_id


def _send_telegram(message: str) -> bool:
    token, chat_id = _get_tg_creds()
    if not token or not chat_id:
        log.warning("Telegram creds not found — skipping alert")
        return False
    url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message[:4096],   # Telegram max
        "parse_mode": "HTML",
    }).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())
            return bool(result.get("ok"))
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return False


# ── Atomic helpers ────────────────────────────────────────────────────────

def _load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Check result ──────────────────────────────────────────────────────────

class CheckResult:
    def __init__(
        self,
        name: str,
        status: str,        # "OK" | "WARNING" | "CRITICAL" | "SKIPPED"
        message: str,
        detail: Optional[Dict] = None,
    ):
        self.name = name
        self.status = status
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
        }

    @property
    def is_critical(self) -> bool:
        return self.status == "CRITICAL"


# ── Individual checks ──────────────────────────────────────────────────────

def check_position_limits() -> CheckResult:
    """Verify current_positions.json satisfies max_protocols and per-protocol cap."""
    doc = _load_json(_POSITIONS_PATH)
    if not doc or not isinstance(doc.get("positions"), dict):
        return CheckResult(
            "position_limits", "CRITICAL",
            "current_positions.json missing or invalid",
        )

    positions = doc["positions"]
    capital = float(doc.get("capital_usd", 100000) or 100000)
    num = len(positions)

    violations = []
    if num > 8:
        violations.append("too_many_protocols: {} > 8".format(num))

    per_max = 25.0
    for proto, usd in positions.items():
        pct = float(usd or 0) / capital * 100
        if pct > per_max:
            violations.append("{} = {:.1f}% > {}%".format(proto, pct, per_max))

    if violations:
        return CheckResult(
            "position_limits", "CRITICAL",
            "Position limit violations: {}".format("; ".join(violations)),
            {"violations": violations, "num_protocols": num},
        )
    return CheckResult(
        "position_limits", "OK",
        "{} protocols, all within per-protocol cap".format(num),
        {"num_protocols": num},
    )


def check_t1_concentration() -> CheckResult:
    """Verify T1 allocation >= 55%."""
    from spa_core.risk.policy_enforcer import T1_ADAPTERS, T3_ADAPTERS

    doc = _load_json(_POSITIONS_PATH)
    if not doc or not isinstance(doc.get("positions"), dict):
        return CheckResult(
            "t1_concentration", "CRITICAL",
            "current_positions.json missing",
        )

    positions = doc["positions"]
    capital = float(doc.get("capital_usd", 100000) or 100000)
    t1_usd = sum(float(v or 0) for k, v in positions.items() if k in T1_ADAPTERS)
    t1_pct = t1_usd / capital * 100

    if t1_pct < 55.0:
        return CheckResult(
            "t1_concentration", "CRITICAL",
            "T1 = {:.1f}% < 55% minimum (policy breach)".format(t1_pct),
            {"t1_pct": round(t1_pct, 2), "t1_usd": round(t1_usd, 2)},
        )
    return CheckResult(
        "t1_concentration", "OK",
        "T1 = {:.1f}% >= 55%".format(t1_pct),
        {"t1_pct": round(t1_pct, 2)},
    )


def check_adapter_status() -> CheckResult:
    """Verify adapter_status.json is fresh and has active T1 adapters."""
    doc = _load_json(_ADAPTER_PATH)
    if not doc:
        return CheckResult(
            "adapter_status", "CRITICAL",
            "adapter_status.json missing",
        )

    adapters = doc.get("adapters", {})
    if not adapters:
        return CheckResult(
            "adapter_status", "CRITICAL",
            "adapter_status.json has no adapters",
        )

    from spa_core.risk.policy_enforcer import T1_ADAPTERS
    t1_active = [k for k in T1_ADAPTERS if k in adapters and adapters[k].get("active", True)]

    if len(t1_active) < 3:
        return CheckResult(
            "adapter_status", "CRITICAL",
            "Only {} T1 adapters active (need >= 3)".format(len(t1_active)),
            {"t1_active": t1_active},
        )

    # Freshness check
    generated_at = doc.get("generated_at", "")
    if generated_at:
        try:
            from datetime import timedelta
            ts = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            if age_h > 48:
                return CheckResult(
                    "adapter_status", "WARNING",
                    "adapter_status.json is {:.0f}h old (>48h)".format(age_h),
                    {"age_hours": round(age_h, 1)},
                )
        except Exception:
            pass

    return CheckResult(
        "adapter_status", "OK",
        "{} T1 adapters active".format(len(t1_active)),
        {"t1_active_count": len(t1_active)},
    )


def check_circuit_breaker() -> CheckResult:
    """Check if kill switch is active (drawdown >= 5%)."""
    doc = _load_json(_KILL_SWITCH_PATH)
    if doc and doc.get("active"):
        reason = doc.get("reason", "unknown")
        return CheckResult(
            "circuit_breaker", "CRITICAL",
            "Kill switch ACTIVE: {}".format(reason),
            {"kill_switch": True, "reason": reason},
        )

    # Also check paper_trading_status for drawdown
    pts = _load_json(_PAPER_PATH)
    if pts:
        drawdown = float(pts.get("max_drawdown_pct", 0) or 0)
        if drawdown >= 5.0:
            return CheckResult(
                "circuit_breaker", "CRITICAL",
                "Drawdown {:.1f}% >= 5% kill-switch threshold".format(drawdown),
                {"drawdown_pct": drawdown},
            )

    return CheckResult(
        "circuit_breaker", "OK",
        "No kill switch active, drawdown within limits",
    )


def check_apy_coherence() -> CheckResult:
    """Check that top-APY protocols are in top-allocation (not inverted logic)."""
    pos_doc = _load_json(_POSITIONS_PATH)
    adp_doc = _load_json(_ADAPTER_PATH)

    if not pos_doc or not adp_doc:
        return CheckResult(
            "apy_coherence", "SKIPPED",
            "Missing positions or adapter data",
        )

    positions = pos_doc.get("positions", {})
    adapters = adp_doc.get("adapters", {})
    capital = float(pos_doc.get("capital_usd", 100000) or 100000)

    # Build APY map for current positions
    apy_map = {}
    for proto in positions:
        info = adapters.get(proto)
        if isinstance(info, dict):
            apy = info.get("apy") or info.get("live_apy") or 0
            if apy and float(apy) > 0:
                apy_map[proto] = float(apy)

    if len(apy_map) < 3:
        return CheckResult(
            "apy_coherence", "SKIPPED",
            "Insufficient APY data for {} protocols".format(len(apy_map)),
        )

    top_apy = sorted(apy_map, key=lambda p: -apy_map[p])[:3]
    top_alloc = sorted(positions, key=lambda p: -float(positions.get(p) or 0))[:5]
    missing = [p for p in top_apy if p not in top_alloc]

    if missing:
        return CheckResult(
            "apy_coherence", "WARNING",
            "Top-APY protocols {} not in top-5 allocation".format(missing),
            {"top_apy": top_apy, "top_alloc": top_alloc[:5], "missing": missing},
        )

    return CheckResult(
        "apy_coherence", "OK",
        "Top-APY protocols aligned with top allocation",
        {"top_apy": top_apy},
    )


def check_llm_forbidden_violations() -> CheckResult:
    """Check for LLM usage in forbidden modules (risk/execution/monitoring).

    Scans Python source files for live imports of LLM libraries.
    Uses token-level detection (function call patterns, not string literals)
    to avoid false positives from comment/docstring references.
    """
    # Split patterns so this file's own scan-pattern strings don't self-trigger
    _a = "anthropic"
    _o = "openai"
    _c = "ChatCompletion"
    # Patterns that indicate actual LLM library usage (not just mentions)
    forbidden_import_pairs = [
        ("import", _a),
        ("import", _o),
        ("from", _a),
        ("from", _o),
    ]
    forbidden_call_patterns = [_c, "anthropic.Anthropic(", "openai.OpenAI("]

    violations_found = []
    _self = Path(__file__).name  # skip this file (contains pattern strings)

    # Explicit exclusions: files that intentionally use LLM under controlled conditions.
    # Each exclusion must be justified here — do not add without ADR review.
    # NOTE (AUD-02 / ADR-026): auto_fixer.py was RELOCATED out of spa_core/monitoring/
    # to spa_core/dev_agents/ so FORBIDDEN rule 4 holds literally — monitoring/ is now
    # LLM-free with no carve-out required. Keep this set empty.
    _KNOWN_EXCEPTIONS: set[str] = set()

    for module_dir in ["spa_core/risk", "spa_core/execution", "spa_core/monitoring"]:
        full_path = _REPO / module_dir
        if not full_path.exists():
            continue
        for py_file in full_path.glob("*.py"):
            if py_file.name == _self:
                continue  # skip self to avoid false positive on pattern strings
            if py_file.name in _KNOWN_EXCEPTIONS:
                continue  # skip known-exception files (advisory LLM usage only)
            try:
                lines = py_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                for lineno, line in enumerate(lines, 1):
                    stripped = line.strip()
                    # Skip comments and docstrings
                    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                        continue
                    # Check import patterns
                    for kw, lib in forbidden_import_pairs:
                        if stripped.startswith(kw + " " + lib) or (
                            kw + " " + lib + " " in stripped
                        ):
                            violations_found.append(
                                "{}:{}: {} {}".format(py_file.name, lineno, kw, lib)
                            )
                    # Check call patterns
                    for pat in forbidden_call_patterns:
                        if pat in stripped:
                            violations_found.append(
                                "{}:{}: contains '{}'".format(py_file.name, lineno, pat)
                            )
            except Exception:
                pass

    if violations_found:
        return CheckResult(
            "llm_forbidden_violations", "CRITICAL",
            "LLM usage detected in forbidden domains: {}".format(violations_found[:3]),
            {"violations": violations_found},
        )

    return CheckResult(
        "llm_forbidden_violations", "OK",
        "No LLM usage in risk/execution/monitoring domains",
    )


# ── Watchdog runner ────────────────────────────────────────────────────────

RULES_TO_CHECK = [
    check_position_limits,
    check_t1_concentration,
    check_adapter_status,
    check_circuit_breaker,
    check_apy_coherence,
    check_llm_forbidden_violations,
]


def run_watchdog(write: bool = True, send_alert: bool = True) -> int:
    """Run all watchdog checks. Returns exit code (0=OK, 1=critical violations)."""
    ts = datetime.now(timezone.utc).isoformat()
    results: List[CheckResult] = []

    for check_fn in RULES_TO_CHECK:
        try:
            res = check_fn()
        except Exception as e:
            log.exception("Check %s raised: %s", check_fn.__name__, e)
            res = CheckResult(
                check_fn.__name__.replace("check_", ""), "CRITICAL",
                "Check raised exception: {}".format(e),
            )
        results.append(res)
        log.info("[%s] %s: %s", res.status, res.name, res.message)

    critical = [r for r in results if r.is_critical]
    warnings = [r for r in results if r.status == "WARNING"]

    report = {
        "checked_at": ts,
        "overall": "CRITICAL" if critical else ("WARNING" if warnings else "OK"),
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "checks": [r.to_dict() for r in results],
    }

    if write:
        # Append to ring-buffer history
        history = _load_json(_WATCHDOG_PATH, default=[])
        if not isinstance(history, list):
            history = []
        history.append(report)
        if len(history) > _WATCHDOG_HISTORY_CAP:
            history = history[-_WATCHDOG_HISTORY_CAP:]
        try:
            _atomic_write(_WATCHDOG_PATH, history)
        except Exception as e:
            log.error("Failed to write watchdog_report.json: %s", e)

    if critical and send_alert:
        lines = [
            "🚨 <b>SPA WATCHDOG — CRITICAL VIOLATIONS</b>",
            "Время: {}".format(ts[:19].replace("T", " ")),
            "{} critical, {} warnings".format(len(critical), len(warnings)),
            "",
        ]
        for r in critical:
            lines.append("❌ [{}] {}".format(r.name, r.message))
        _send_telegram("\n".join(lines))

    return 1 if critical else 0


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    write = "--no-write" not in sys.argv
    send_alert = "--no-alert" not in sys.argv
    exit_code = run_watchdog(write=write, send_alert=send_alert)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
