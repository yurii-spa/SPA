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

Честность отчёта (инвариант #2, refusal-first): статус `SKIPPED` означает «НЕ ИЗМЕРЕНО», а не
«прошло». Такие проверки собираются в `unchecked`/`unchecked_count`, и `overall` равен `"OK"`
ТОЛЬКО когда все правила действительно были вычислены и прошли; иначе — `"UNCHECKED"`.
Ни один порог/правило здесь не живёт: авторитетный гейт — `spa_core/risk/policy.py`,
лестница kill-switch — `spa_core/governance/kill_switch.py`.

Использование:
    python3 -m spa_core.monitoring.rules_watchdog
    python3 -m spa_core.monitoring.rules_watchdog --once  # один прогон
"""
from __future__ import annotations

import html
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
# OWNER DECISION 2026-07-23 (Variant A, card owner-decision-storozh-pravil-ne-vidit-stop-kran):
# the circuit-breaker check now reads the REAL cycle-written kill-switch state files. The old
# `kill_switch.json` name existed NOWHERE else in the repo (dead) and `max_drawdown_pct` was
# never written — so the check reported "within limits" about numbers it never saw. Authoritative
# state lives in these two files (written by the daily cycle ~06:00 UTC):
_KILL_SWITCH_STATUS_PATH = _DATA_DIR / "kill_switch_status.json"   # field: triggered
_DERISK_STATUS_PATH      = _DATA_DIR / "derisk_status.json"        # fields: active, tier, reason
# A cycle-written status file older than this = the daily cycle likely did NOT run → the
# kill-switch posture is BLIND → treated as CRITICAL "missed cycle" (not a silent skip).
CIRCUIT_FRESH_H = 26.0
_KILL_SWITCH_PATH = _DATA_DIR / "kill_switch.json"  # retained (legacy/off-state doc); not authoritative

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
    """Route a CRITICAL rule breach through the SINGLE push authority (Tier-1).

    Phase-1 rewire: the 5-min watchdog no longer POSTs Telegram directly (that
    re-fired every run while a breach persisted). It pushes the whitelisted
    ``rules_critical`` key via push_policy, which is edge-triggered — one push on
    the breach transition, silent while it persists, RESOLVED on recovery.
    Returns True if a push was emitted. Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        return bool(
            push_policy.push_critical(
                "rules_critical",
                "CRITICAL",
                "SPA Rules Watchdog — CRITICAL breach",
                message[:4000],
            )
        )
    except Exception as e:  # noqa: BLE001
        log.warning("rules_watchdog: push_policy send failed: %s", e)
        return False


# ── Atomic helpers ────────────────────────────────────────────────────────

def _load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _read_doc(path: Path) -> tuple:
    """Read a JSON state file, distinguishing WHY it produced nothing.

    Returns ``(state, payload)`` where state is one of:
      - ``"ok"``          → payload is the parsed document (may itself be empty/any type);
      - ``"missing"``     → payload is ``None``; the file does not exist;
      - ``"unreadable"``  → payload is the error string; the file exists but could not be parsed.

    Honesty primitive (invariant #2, refusal-first). ``_load_json`` collapses all three cases
    into one falsy value, so every caller that wrote ``if not doc: ...`` was unable to tell
    "I read it and it said nothing" from "I never managed to read it" — and then reported OK
    about data it had never seen. Same defect class as the RISKWIRE / d2_connectivity /
    tier1-status fail-OPENs (cycles #29 / #31 / #35).
    """
    try:
        exists = path.exists()
    except OSError as e:  # unreadable parent dir, permission denied on stat, …
        return "unreadable", str(e)
    if not exists:
        return "missing", None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return "ok", json.load(f)
    except Exception as e:  # noqa: BLE001 — any read/parse failure is "unreadable"
        return "unreadable", str(e)


def _doc_age_hours(doc: Any) -> tuple:
    """Age (hours) of a doc's ``generated_at``. Returns (age_hours, problem).

    fail-CLOSED: a missing/unparseable stamp yields (None, reason) — never a fresh verdict.
    """
    if not isinstance(doc, dict):
        return None, "document is not an object"
    generated_at = doc.get("generated_at")
    if not generated_at or not isinstance(generated_at, str):
        return None, "no usable generated_at"
    try:
        ts = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, None
    except Exception as e:  # noqa: BLE001
        return None, "unparseable generated_at {!r} ({})".format(generated_at, e)


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
    """Outcome of one watchdog rule check.

    ``SKIPPED`` means **NOT MEASURED** — the check could not obtain the input it needs and
    therefore asserts nothing. It is not a pass: ``run_watchdog`` must never fold it into
    ``overall: "OK"`` (that is precisely the bug this class of fix removes).
    """

    def __init__(
        self,
        name: str,
        status: str,        # "OK" | "WARNING" | "CRITICAL" | "SKIPPED" (= not measured)
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

    @property
    def is_unchecked(self) -> bool:
        """True when the rule was NOT measured (missing / unreadable / insufficient input)."""
        return self.status == "SKIPPED"


def _finite_float(raw: Any) -> Optional[float]:
    """Return ``raw`` as a finite float, or ``None`` when it is not a usable number.

    ``bool`` is rejected on purpose: ``float(True) == 1.0`` would turn a flag into a
    measurement (the fabrication edge closed in the cycle-runner APY honesty fix).
    """
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val != val or val in (float("inf"), float("-inf")):  # NaN / ±inf
        return None
    return val


# ── Individual checks ──────────────────────────────────────────────────────

def check_position_limits() -> CheckResult:
    """Verify current_positions.json satisfies max_protocols and per-protocol cap."""
    state, doc = _read_doc(_POSITIONS_PATH)
    if state != "ok" or not isinstance(doc, dict) or not isinstance(doc.get("positions"), dict):
        return CheckResult(
            "position_limits", "CRITICAL",
            "current_positions.json {}".format(
                "unreadable: {}".format(doc) if state == "unreadable"
                else "missing" if state == "missing" else "invalid (no positions object)"
            ),
        )

    positions = doc["positions"]
    num = len(positions)

    from spa_core.risk.policy_enforcer import RULES as _RULES  # single-source (reconciled to policy.py)

    violations = []
    if num > 8:
        violations.append("too_many_protocols: {} > 8".format(num))

    # The per-protocol cap is a PERCENTAGE — without a real denominator it cannot be evaluated.
    # The previous `doc.get("capital_usd", 100000) or 100000` invented $100k when the field was
    # absent/zero/garbage, so every position share was measured against a number nobody wrote.
    capital = _finite_float(doc.get("capital_usd"))
    if capital is None or capital <= 0:
        if violations:  # the protocol-count breach stands on its own — report it
            return CheckResult(
                "position_limits", "CRITICAL",
                "Position limit violations: {}".format("; ".join(violations)),
                {"violations": violations, "num_protocols": num},
            )
        return CheckResult(
            "position_limits", "SKIPPED",
            "Per-protocol cap NOT CHECKED: current_positions.json has no usable capital_usd "
            "(got {!r}); {} protocols, count is within the max of 8".format(
                doc.get("capital_usd"), num),
            {"num_protocols": num, "unchecked_reason": "no usable capital_usd"},
        )

    per_max = float(_RULES["per_protocol_max_pct"])  # 40% (policy.max_single_protocol), was stale 25%
    unpriced = []
    for proto, usd in positions.items():
        val = _finite_float(usd)
        if val is None:
            # An unusable position size is not a zero — say so instead of counting it as compliant.
            unpriced.append("{}={!r}".format(proto, usd))
            continue
        pct = val / capital * 100
        if pct > per_max:
            violations.append("{} = {:.1f}% > {}%".format(proto, pct, per_max))

    if violations:
        return CheckResult(
            "position_limits", "CRITICAL",
            "Position limit violations: {}".format("; ".join(violations)),
            {"violations": violations, "num_protocols": num},
        )
    if unpriced:
        return CheckResult(
            "position_limits", "SKIPPED",
            "Per-protocol cap NOT CHECKED for {}: unusable position size(s)".format(
                ", ".join(unpriced)),
            {"num_protocols": num, "unchecked_reason": "unusable position sizes",
             "unpriced": unpriced},
        )
    return CheckResult(
        "position_limits", "OK",
        "{} protocols, all within per-protocol cap".format(num),
        {"num_protocols": num},
    )


def check_t1_concentration() -> CheckResult:
    """Verify T1 allocation >= the policy T1 floor (single-sourced from policy.py).

    Owner-approved 2026-07-08: policy.py has NO T1 minimum, so the reconciled floor is 0% — this
    check no longer imposes the stale 55% risk_adjusted-era floor (the optimized_yield book at T1 45%
    is compliant under the authoritative gate). Kept as an OK-reporter (flips to CRITICAL only if a
    future ADR re-introduces a T1 floor in RiskConfig)."""
    from spa_core.risk.policy_enforcer import T1_ADAPTERS, T3_ADAPTERS, RULES as _RULES

    state, doc = _read_doc(_POSITIONS_PATH)
    if state != "ok" or not isinstance(doc, dict) or not isinstance(doc.get("positions"), dict):
        return CheckResult(
            "t1_concentration", "CRITICAL",
            "current_positions.json {}".format(
                "unreadable: {}".format(doc) if state == "unreadable"
                else "missing" if state == "missing" else "invalid (no positions object)"
            ),
        )

    positions = doc["positions"]
    # Same invented-denominator defect as check_position_limits: a T1 percentage computed
    # against an assumed $100k is a fabricated number, and it is published in `detail`.
    capital = _finite_float(doc.get("capital_usd"))
    if capital is None or capital <= 0:
        return CheckResult(
            "t1_concentration", "SKIPPED",
            "T1 share NOT CHECKED: current_positions.json has no usable capital_usd "
            "(got {!r})".format(doc.get("capital_usd")),
            {"unchecked_reason": "no usable capital_usd"},
        )
    t1_usd = sum(_finite_float(v) or 0.0 for k, v in positions.items() if k in T1_ADAPTERS)
    t1_pct = t1_usd / capital * 100
    t1_min = float(_RULES["t1_min_pct"])  # 0.0 — policy.py has no T1 floor (reconciled 2026-07-08)

    if t1_min > 0.0 and t1_pct < t1_min:
        return CheckResult(
            "t1_concentration", "CRITICAL",
            "T1 = {:.1f}% < {:.0f}% minimum (policy breach)".format(t1_pct, t1_min),
            {"t1_pct": round(t1_pct, 2), "t1_usd": round(t1_usd, 2)},
        )
    return CheckResult(
        "t1_concentration", "OK",
        "T1 = {:.1f}% >= {:.0f}% floor".format(t1_pct, t1_min),
        {"t1_pct": round(t1_pct, 2)},
    )


def check_adapter_status() -> CheckResult:
    """Verify adapter_status.json is fresh and has active T1 adapters."""
    state, doc = _read_doc(_ADAPTER_PATH)
    if state != "ok" or not isinstance(doc, dict):
        return CheckResult(
            "adapter_status", "CRITICAL",
            "adapter_status.json {}".format(
                "unreadable: {}".format(doc) if state == "unreadable"
                else "missing" if state == "missing" else "is not an object"
            ),
        )

    adapters = doc.get("adapters", {})
    if not isinstance(adapters, dict):
        return CheckResult(
            "adapter_status", "CRITICAL",
            "adapter_status.json 'adapters' is not an object",
        )
    if not adapters:
        return CheckResult(
            "adapter_status", "CRITICAL",
            "adapter_status.json has no adapters",
        )

    from spa_core.risk.policy_enforcer import T1_ADAPTERS
    t1_active = []
    t1_malformed = []
    for k in T1_ADAPTERS:
        if k not in adapters:
            continue
        entry = adapters[k]
        if not isinstance(entry, dict):
            # A T1 entry we cannot interpret is neither active nor inactive — never silently
            # treated as one or the other. (Before, `entry.get` raised and the runner turned
            # the AttributeError into a CRITICAL with a misleading message.)
            t1_malformed.append("{}={!r}".format(k, entry))
            continue
        if entry.get("active", True):
            t1_active.append(k)

    if t1_malformed:
        return CheckResult(
            "adapter_status", "SKIPPED",
            "T1 adapter availability NOT CHECKED: malformed entries {}".format(
                ", ".join(t1_malformed)),
            {"unchecked_reason": "malformed adapter entries", "malformed": t1_malformed,
             "t1_active_count": len(t1_active)},
        )

    if len(t1_active) < 3:
        return CheckResult(
            "adapter_status", "CRITICAL",
            "Only {} T1 adapters active (need >= 3)".format(len(t1_active)),
            {"t1_active": t1_active},
        )

    # Freshness check. A stamp we cannot read is NOT a fresh file: the old code swallowed both
    # the missing field and the parse error and fell through to "OK — N T1 adapters active",
    # i.e. it reported a freshness verdict it had never computed.
    generated_at = doc.get("generated_at")
    age_h = None
    if not generated_at or not isinstance(generated_at, str):
        stamp_problem = "adapter_status.json carries no generated_at"
    else:
        try:
            ts = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
            stamp_problem = None
        except Exception as e:  # noqa: BLE001
            stamp_problem = "unparseable generated_at {!r} ({})".format(generated_at, e)

    if stamp_problem is not None:
        return CheckResult(
            "adapter_status", "SKIPPED",
            "{} T1 adapters active, but freshness NOT CHECKED: {}".format(
                len(t1_active), stamp_problem),
            {"t1_active_count": len(t1_active), "unchecked_reason": stamp_problem},
        )

    if age_h is not None and age_h > 48:
        return CheckResult(
            "adapter_status", "WARNING",
            "adapter_status.json is {:.0f}h old (>48h)".format(age_h),
            {"age_hours": round(age_h, 1)},
        )

    return CheckResult(
        "adapter_status", "OK",
        "{} T1 adapters active".format(len(t1_active)),
        {"t1_active_count": len(t1_active), "age_hours": round(age_h, 1)},
    )


def check_circuit_breaker() -> CheckResult:
    """Report the kill-switch / drawdown posture — or refuse when it was NOT measured.

    This check owns no thresholds: the authoritative ladder lives in
    ``spa_core/governance/kill_switch.py`` (SOFT −5% / HARD −10%, ADR-034/048) and is not
    touched here. What it owns is the honesty of its own verdict — it must never answer
    "within limits" about a number it never read (invariant #2, refusal-first).

    OWNER DECISION 2026-07-23 (Variant A, ADR-056): reads the REAL cycle-written state files
    ``data/kill_switch_status.json`` (``triggered``) and ``data/derisk_status.json``
    (``active``/``tier``/``reason``). ``triggered``/``active`` → CRITICAL immediately. A status
    file older than ``CIRCUIT_FRESH_H`` (26h) → CRITICAL "missed cycle" (the daily cycle likely
    did not run → posture BLIND). Unreadable/missing → NOT CHECKED (fail-CLOSED), never "off".
    """
    unchecked: List[str] = []

    ks_state, ks_doc = _read_doc(_KILL_SWITCH_STATUS_PATH)
    ds_state, ds_doc = _read_doc(_DERISK_STATUS_PATH)

    # (1) fail-CLOSED: a corrupt file must NEVER be read as "the switch is off".
    if ks_state == "unreadable":
        unchecked.append("kill_switch_status.json unreadable ({})".format(ks_doc))
    if ds_state == "unreadable":
        unchecked.append("derisk_status.json unreadable ({})".format(ds_doc))

    # (2) ACTIVE posture → CRITICAL immediately (fast redundant delivery, even if set earlier).
    if ks_state == "ok" and isinstance(ks_doc, dict) and ks_doc.get("triggered"):
        reason = ks_doc.get("reason", "unknown")
        return CheckResult(
            "circuit_breaker", "CRITICAL",
            "Kill switch TRIGGERED: {}".format(reason),
            {"kill_switch": True, "reason": reason},
        )
    if ds_state == "ok" and isinstance(ds_doc, dict) and ds_doc.get("active"):
        tier = ds_doc.get("tier", "?")
        reason = ds_doc.get("reason", "unknown")
        return CheckResult(
            "circuit_breaker", "CRITICAL",
            "De-risk ACTIVE (tier {}): {}".format(tier, reason),
            {"derisk_active": True, "tier": tier, "reason": reason},
        )

    # (3) freshness: a stale cycle-written status file = the daily cycle likely did NOT run →
    # kill-switch posture is BLIND → CRITICAL "missed cycle" (owner Variant A, NOT a silent skip).
    for name, state, doc in (
        ("kill_switch_status", ks_state, ks_doc),
        ("derisk_status", ds_state, ds_doc),
    ):
        if state == "ok":
            age_h, stamp_problem = _doc_age_hours(doc)
            if stamp_problem is not None:
                unchecked.append("{}.json {}".format(name, stamp_problem))
            elif age_h > CIRCUIT_FRESH_H:
                return CheckResult(
                    "circuit_breaker", "CRITICAL",
                    "Missed cycle: {}.json is {:.0f}h old (> {:.0f}h) — daily cycle may not have "
                    "run; kill-switch posture is BLIND".format(name, age_h, CIRCUIT_FRESH_H),
                    {"missed_cycle": True, "stale_file": name, "age_hours": round(age_h, 1)},
                )
        elif state == "missing":
            unchecked.append("{}.json missing — cannot confirm kill-switch posture".format(name))

    if unchecked:
        return CheckResult(
            "circuit_breaker", "SKIPPED",
            "Kill-switch posture NOT CHECKED: {}".format("; ".join(unchecked)),
            {"unchecked_reason": "; ".join(unchecked), "unchecked": unchecked},
        )

    return CheckResult(
        "circuit_breaker", "OK",
        "No kill switch / de-risk active; both status files fresh (< {:.0f}h)".format(CIRCUIT_FRESH_H),
        {"kill_switch": False, "derisk_active": False},
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
    unscanned: List[str] = []
    scanned_files = 0
    _self = Path(__file__).name  # skip this file (contains pattern strings)

    # Explicit exclusions: files that intentionally use LLM under controlled conditions.
    # These are NOT in the capital-path (risk/execution) and use LLM for advisory tasks only.
    # Each exclusion must be justified here — do not add without ADR review.
    _KNOWN_EXCEPTIONS = {
        "auto_fixer.py",   # ADR-advisory: autonomous bug-fixer uses Claude for code repair,
                           # NOT for risk/capital decisions. Rate-limited, sandboxed, never
                           # touches risk/execution domains. Lazy import — stdlib-only at module level.
    }

    for module_dir in ["spa_core/risk", "spa_core/execution", "spa_core/monitoring"]:
        full_path = _REPO / module_dir
        if not full_path.exists():
            # A domain we never opened cannot support the claim "no LLM usage in it".
            unscanned.append("{} does not exist".format(module_dir))
            continue
        # rglob, not glob: the top-level-only scan silently skipped every subpackage of the
        # three forbidden domains (spa_core/risk/versions, spa_core/execution/adapters,
        # spa_core/monitoring/sensors — 20 files) while still reporting "No LLM usage in
        # risk/execution/monitoring domains". The CI linter (scripts/lint_llm_forbidden.py)
        # has always walked recursively; the runtime watchdog had not.
        for py_file in sorted(full_path.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            if py_file.name == _self:
                continue  # skip self to avoid false positive on pattern strings
            if py_file.name in _KNOWN_EXCEPTIONS:
                continue  # skip known-exception files (advisory LLM usage only)
            scanned_files += 1
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
            except Exception as e:  # noqa: BLE001
                # A file we could not read is a hole in the scan, not a clean file.
                scanned_files -= 1
                unscanned.append("{} unreadable ({})".format(py_file.name, e))

    if violations_found:
        return CheckResult(
            "llm_forbidden_violations", "CRITICAL",
            "LLM usage detected in forbidden domains: {}".format(violations_found[:3]),
            {"violations": violations_found, "files_scanned": scanned_files,
             "unscanned": unscanned},
        )

    if unscanned:
        return CheckResult(
            "llm_forbidden_violations", "SKIPPED",
            "LLM-forbidden invariant NOT FULLY CHECKED ({} file(s) scanned): {}".format(
                scanned_files, "; ".join(unscanned[:5])),
            {"files_scanned": scanned_files, "unscanned": unscanned,
             "unchecked_reason": "not every file in the forbidden domains could be scanned"},
        )

    return CheckResult(
        "llm_forbidden_violations", "OK",
        "No LLM usage in risk/execution/monitoring domains ({} files scanned)".format(
            scanned_files),
        {"files_scanned": scanned_files},
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
    unchecked = [r for r in results if r.is_unchecked]

    # `overall: "OK"` now means "every rule was actually evaluated and passed". Before, a
    # check that could not run at all (SKIPPED) was invisible here and the report published
    # a clean bill of health for rules nobody had verified — the same fail-OPEN shape as
    # d2_connectivity (#31) and the Tier-1 status summary (#35).
    if critical:
        overall = "CRITICAL"
    elif warnings:
        overall = "WARNING"
    elif unchecked:
        overall = "UNCHECKED"
    else:
        overall = "OK"

    report = {
        "checked_at": ts,
        "overall": overall,
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "unchecked_count": len(unchecked),
        "unchecked": [
            {"check": r.name, "reason": r.detail.get("unchecked_reason") or r.message}
            for r in unchecked
        ],
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
            # Escape dynamic content — messages contain '<'/'>' (e.g. "T1 < 55%")
            # which would break parse_mode=HTML and return 400 Bad Request.
            lines.append("❌ [{}] {}".format(html.escape(r.name), html.escape(r.message)))
        for r in unchecked:
            # Only ever sent alongside a breach that is already paging the owner — an
            # unchecked rule on its own must not turn a 5-minute watchdog into alert spam.
            lines.append("❔ [{}] не проверено: {}".format(
                html.escape(r.name), html.escape(r.detail.get("unchecked_reason") or r.message)))
        _send_telegram("\n".join(lines))

    # Exit code semantics are unchanged on purpose: 1 == rule BREACH (launchd reports it as a
    # failed run). "Not measured" is reported in the file, not by failing the agent.
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
