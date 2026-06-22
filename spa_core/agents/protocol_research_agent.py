"""Protocol Research Agent — еженедельный поиск НОВЫХ DeFi-протоколов (MP-307).

Дополняет Alpha Agent (MP-304): тот скорит уже известных кандидатов из
candidate_registry.json; этот ИЩЕТ кандидатов, которых ещё нет в active
adapters или manifests, и формирует structured research notes.

Источники (все fail-safe):
  data/candidate_registry.json  — кандидаты от discovery (adapter_sdk/discovery.py)
  spa_core/adapter_sdk/manifests/  — уже охваченные протоколы (YAML/JSON)
  spa_core/adapters/__init__.py  — реестр активных адаптеров ADAPTER_REGISTRY

КОНСТИТУЦИОННЫЙ ИНВАРИАНТ:
  LLM SDK ЗАПРЕЩЁН (stdlib only).
  LLM injectable через research_fn=None (деградирует на детерминированный шаблон).
  LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring} — данный модуль
  НЕ входит в запрещённые домены, но сам избегает LLM-зависимости.

SECURITY_SCORE формула (детерминированная, 0–100):
  audit_count * 20  (capped 60)
  age_days / 365 * 20  (capped 20)
  open_source → +10
  bug_bounty  → +10

Вывод:
  data/protocol_research.json       — top-10 исследованных протоколов (атомарно)
  data/protocol_research_status.json — статус последнего цикла (атомарно)

Stdlib only. Atomic writes (tmpfile + os.replace). No imports from execution/risk/monitoring.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.agents.protocol_research_agent")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_MANIFESTS_DIR = _REPO_ROOT / "spa_core" / "adapter_sdk" / "manifests"
_ADAPTERS_INIT = _REPO_ROOT / "spa_core" / "adapters" / "__init__.py"

RESEARCH_FILENAME = "protocol_research.json"
RESEARCH_STATUS_FILENAME = "protocol_research_status.json"
TOP_N = 10

# Security score thresholds
_AUDIT_SCORE_PER_AUDIT = 20
_AUDIT_SCORE_CAP = 60
_AGE_SCORE_CAP = 20
_OPEN_SOURCE_BONUS = 10
_BUG_BOUNTY_BONUS = 10

# TVL thresholds for tier assignment
_TVL_T1 = 100_000_000.0   # $100M → T1
_TVL_T2 = 20_000_000.0    # $20M  → T2
_TVL_VALID = 5_000_000.0  # $5M  → defi_llama_validated

# Security score thresholds for tier
_SCORE_T1 = 80
_SCORE_T2 = 60


# ─── IO helpers ───────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt → default (never raises)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("_read_json %s unreadable (%s) — using default", path.name, exc)
        return default


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _normalise(name: str) -> str:
    """Normalise protocol name/id for deduplication: lowercase, dashes→underscores."""
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


# ─── Active adapters discovery ────────────────────────────────────────────────


def _read_active_adapters_from_init() -> list[str]:
    """Parse ADAPTER_REGISTRY from spa_core/adapters/__init__.py (text scan).

    Returns list of protocol id strings. Fail-safe: any parse error → [].
    This avoids importing the adapters module (possible network/side-effects).
    """
    if not _ADAPTERS_INIT.exists():
        return []
    try:
        text = _ADAPTERS_INIT.read_text(encoding="utf-8")
        protocols: list[str] = []
        # Look for ADAPTER_REGISTRY = { ... }; grab string keys
        in_registry = False
        for line in text.splitlines():
            stripped = line.strip()
            if "ADAPTER_REGISTRY" in stripped and "=" in stripped and "{" in stripped:
                in_registry = True
            if in_registry:
                # Match lines like: "aave_v3": ... or 'compound_v3': ...
                import re
                m = re.search(r'["\']([a-zA-Z0-9_\-]+)["\']\s*:', stripped)
                if m:
                    protocols.append(m.group(1))
                if "}" in stripped and in_registry:
                    break
        return protocols
    except Exception as exc:
        log.warning("_read_active_adapters_from_init failed (%s)", exc)
        return []


def _read_manifest_protocols() -> list[str]:
    """List protocol ids from spa_core/adapter_sdk/manifests/ (YAML/JSON filenames).

    Uses filename stem as the protocol id (e.g. aave_v3.yaml → aave_v3).
    Fail-safe: returns [] if directory missing or unreadable.
    """
    if not _MANIFESTS_DIR.exists():
        return []
    try:
        stems: list[str] = []
        for f in _MANIFESTS_DIR.iterdir():
            if f.suffix in (".yaml", ".yml", ".json"):
                stems.append(f.stem)
        return stems
    except Exception as exc:
        log.warning("_read_manifest_protocols failed (%s)", exc)
        return []


def _existing_protocol_ids() -> list[str]:
    """Combined list of protocol ids already covered (adapters + manifests)."""
    ids = _read_active_adapters_from_init() + _read_manifest_protocols()
    return list({_normalise(i) for i in ids})


# ─── Core public functions ────────────────────────────────────────────────────


def fetch_defi_candidates(data_dir: Path) -> list[dict]:
    """Read candidate_registry.json and return candidates not yet in active adapters.

    Reads from:
      - data/candidate_registry.json → candidates from discovery
      - spa_core/adapters/__init__.py + spa_core/adapter_sdk/manifests/ → known

    Returns list of candidate dicts still NOT in active adapters.
    Fail-safe: missing files → empty list.
    """
    data_dir = Path(data_dir)
    doc = _read_json(data_dir / "candidate_registry.json", {})
    if isinstance(doc, dict):
        candidates = doc.get("candidates") or []
    elif isinstance(doc, list):
        candidates = doc
    else:
        candidates = []

    raw: list[dict] = [c for c in candidates if isinstance(c, dict)]
    return raw


def filter_new_protocols(candidates: list[dict], existing_adapters: list[str]) -> list[dict]:
    """Remove candidates already covered by active adapters or manifests.

    Deduplication uses normalised protocol_id and name comparison.
    existing_adapters: list of normalised protocol id strings.

    Returns only NEW candidates not matching any existing adapter/manifest.
    """
    normed_existing = {_normalise(p) for p in existing_adapters}
    result: list[dict] = []
    for c in candidates:
        pid = str(c.get("protocol") or c.get("protocol_id") or "")
        name = str(c.get("name") or c.get("protocol") or "")
        pid_n = _normalise(pid)
        name_n = _normalise(name)
        # Match if normalised id or name is a substring of any existing (or vice versa)
        already = False
        for ex in normed_existing:
            if pid_n and (pid_n in ex or ex in pid_n):
                already = True
                break
            if name_n and (name_n in ex or ex in name_n):
                already = True
                break
        if not already:
            result.append(c)
    return result


def _compute_security_score(protocol: dict) -> int:
    """Deterministic security score 0–100.

    Formula:
      audit_count * 20  (capped at 60)
      age_days / 365 * 20  (capped at 20)
      open_source → +10
      bug_bounty  → +10
    """
    audit_count = int(protocol.get("audit_count") or 0)
    audit_score = min(audit_count * _AUDIT_SCORE_PER_AUDIT, _AUDIT_SCORE_CAP)

    age_days = 0
    if protocol.get("age_days") is not None:
        try:
            age_days = int(float(protocol["age_days"]))
        except (TypeError, ValueError):
            age_days = 0
    age_score = min(int(age_days / 365.0 * _AGE_SCORE_CAP), _AGE_SCORE_CAP)

    open_source_bonus = _OPEN_SOURCE_BONUS if protocol.get("open_source") else 0
    bug_bounty_bonus = _BUG_BOUNTY_BONUS if protocol.get("bug_bounty") else 0

    total = audit_score + age_score + open_source_bonus + bug_bounty_bonus
    return max(0, min(100, total))


def _compute_risk_flags(protocol: dict, security_score: int) -> list[str]:
    """Derive risk_flags from protocol properties."""
    flags: list[str] = []
    audit_count = int(protocol.get("audit_count") or 0)
    if audit_count == 0:
        flags.append("unaudited")
    tvl = float(protocol.get("tvl_usd") or 0.0)
    if tvl < _TVL_VALID:
        flags.append("low_tvl")
    age_days = 0
    if protocol.get("age_days") is not None:
        try:
            age_days = int(float(protocol["age_days"]))
        except (TypeError, ValueError):
            age_days = 0
    if age_days < 180:
        flags.append("new_protocol")
    if not protocol.get("bug_bounty"):
        flags.append("no_bug_bounty")
    exit_h = protocol.get("exit_latency_hours")
    if exit_h is not None:
        try:
            if float(exit_h) > 72:
                flags.append("high_exit_latency")
        except (TypeError, ValueError):
            pass
    return flags


def _suggested_tier(security_score: int, tvl_usd: float) -> str:
    """Determine suggested tier from security score and TVL."""
    if security_score >= _SCORE_T1 and tvl_usd >= _TVL_T1:
        return "T1"
    if security_score >= _SCORE_T2 and tvl_usd >= _TVL_T2:
        return "T2"
    return "T3"


def _deterministic_notes(protocol: dict, security_score: int, tier: str) -> str:
    """Build deterministic research notes string."""
    name = str(protocol.get("name") or protocol.get("protocol") or protocol.get("protocol_id") or "?")
    tvl = float(protocol.get("tvl_usd") or 0.0)
    tvl_m = tvl / 1_000_000.0
    audit_count = int(protocol.get("audit_count") or 0)
    return (
        f"Protocol {name}. "
        f"Security: {security_score}/100. "
        f"TVL: ${tvl_m:.1f}M. "
        f"Tier: {tier}. "
        f"Audits: {audit_count}."
    )


def _recommendation(security_score: int, risk_flags: list[str]) -> str:
    """Recommendation string based on score and flags."""
    blocking_flags = {"unaudited", "low_tvl"}
    has_blocking = bool(set(risk_flags) & blocking_flags)
    if security_score >= _SCORE_T2 and not has_blocking:
        return "add_to_whitelist_candidate"
    if security_score >= 30 and not has_blocking:
        return "monitor"
    return "skip"


def research_protocol(protocol: dict, research_fn: Optional[Callable[[dict], str]] = None) -> dict:
    """Deterministic deep-research of a single protocol candidate.

    Parameters
    ----------
    protocol    : raw candidate dict (from candidate_registry or manual).
    research_fn : optional callable(protocol_dict) → str for enhanced notes.
                  Degrade to deterministic template on error or None.

    Returns
    -------
    dict — research result with security_score, defi_llama_validated,
           suggested_tier, research_notes, risk_flags, recommendation,
           tvl_usd, apy_pct, protocol_id, name.
    """
    pid = str(protocol.get("protocol") or protocol.get("protocol_id") or "")
    name = str(protocol.get("name") or pid or "?")
    tvl_usd = float(protocol.get("tvl_usd") or 0.0)
    apy_pct = float(protocol.get("apy_pct") or 0.0)

    security_score = _compute_security_score(protocol)
    defi_llama_validated = tvl_usd >= _TVL_VALID
    tier = _suggested_tier(security_score, tvl_usd)
    risk_flags = _compute_risk_flags(protocol, security_score)
    recommendation = _recommendation(security_score, risk_flags)

    # Research notes: try research_fn, degrade on failure
    notes_str = _deterministic_notes(protocol, security_score, tier)
    if research_fn is not None:
        try:
            enhanced = str(research_fn(protocol))
            if enhanced:
                notes_str = enhanced
        except Exception as exc:
            log.warning("research_fn failed (%s) — using deterministic notes", exc)

    return {
        "protocol_id": pid,
        "name": name,
        "security_score": security_score,
        "defi_llama_validated": defi_llama_validated,
        "suggested_tier": tier,
        "research_notes": notes_str,
        "risk_flags": risk_flags,
        "recommendation": recommendation,
        "tvl_usd": tvl_usd,
        "apy_pct": apy_pct,
    }


def run_research_cycle(
    data_dir: Optional[Path] = None,
    research_fn: Optional[Callable[[dict], str]] = None,
) -> dict:
    """Main entry point — runs the weekly protocol research cycle.

    Steps:
      1. fetch_defi_candidates() from data/candidate_registry.json
      2. filter_new_protocols() against existing adapters + manifests
      3. research_protocol() for each candidate
      4. Sort by security_score desc (protocol_id for tie-breaking)
      5. Write data/protocol_research.json (atomic, top-10)
      6. Write data/protocol_research_status.json (atomic)

    Scheduled: weekday==0 (Monday), consistent with Alpha Agent.

    Returns
    -------
    dict — {researched_count, new_candidates, top_protocol, status}
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now_ts = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        # Step 1: fetch candidates
        all_candidates = fetch_defi_candidates(ddir)

        # Step 2: filter out already-known protocols
        existing = _existing_protocol_ids()
        new_candidates = filter_new_protocols(all_candidates, existing)

        # Step 3: research each candidate
        researched: list[dict] = []
        for cand in new_candidates:
            try:
                result = research_protocol(cand, research_fn=research_fn)
                researched.append(result)
            except Exception as exc:
                pid = cand.get("protocol") or cand.get("protocol_id") or "?"
                log.warning("research_protocol failed for %s (%s) — skipped", pid, exc)

        # Step 4: sort by security_score desc, protocol_id for tie-break
        researched.sort(key=lambda r: (-r["security_score"], r["protocol_id"]))
        top = researched[:TOP_N]

        # Build output lists
        whitelist_candidates = [
            r["protocol_id"] for r in top if r["recommendation"] == "add_to_whitelist_candidate"
        ]
        monitor_list = [
            r["protocol_id"] for r in top if r["recommendation"] == "monitor"
        ]
        skip_list = [
            r["protocol_id"] for r in top if r["recommendation"] == "skip"
        ]
        top_protocol = top[0]["protocol_id"] if top else None

        # Step 5: write data/protocol_research.json (atomic)
        research_doc: dict = {
            "generated_at": now_ts,
            "cycle_date": today,
            "researched_count": len(researched),
            "protocols": top,
            "add_to_whitelist_candidates": whitelist_candidates,
            "monitor_list": monitor_list,
            "skip_list": skip_list,
        }
        try:
            _atomic_write_json(ddir / RESEARCH_FILENAME, research_doc)
        except Exception as exc:
            log.warning("protocol_research.json write failed (%s)", exc)

        # Step 6: write data/protocol_research_status.json (atomic)
        status_doc: dict = {
            "generated_at": now_ts,
            "cycle_date": today,
            "status": "ok",
            "researched_count": len(researched),
            "new_candidates_found": len(new_candidates),
            "top_protocol": top_protocol,
            "whitelist_candidates_count": len(whitelist_candidates),
            "existing_adapters_skipped": len(existing),
            "total_candidates_in_registry": len(all_candidates),
        }
        try:
            _atomic_write_json(ddir / RESEARCH_STATUS_FILENAME, status_doc)
        except Exception as exc:
            log.warning("protocol_research_status.json write failed (%s)", exc)

        log.info(
            "Protocol research cycle: %d new candidates researched, top=%s",
            len(researched),
            top_protocol,
        )
        return {
            "researched_count": len(researched),
            "new_candidates": len(new_candidates),
            "top_protocol": top_protocol,
            "status": "ok",
        }

    except Exception as exc:  # cycle must never raise
        log.warning("run_research_cycle failed (%s) — returning error status", exc)
        err_status: dict = {
            "generated_at": now_ts,
            "cycle_date": today,
            "status": f"error: {type(exc).__name__}: {exc}",
            "researched_count": 0,
            "new_candidates_found": 0,
            "top_protocol": None,
        }
        try:
            _atomic_write_json(ddir / RESEARCH_STATUS_FILENAME, err_status)
        except Exception:
            pass
        return {
            "researched_count": 0,
            "new_candidates": 0,
            "top_protocol": None,
            "status": f"error: {type(exc).__name__}: {exc}",
        }
