"""spa_core/studio_os/readiness_scopes.py — RM-TRUTH-01 / ADR-580 §C3: readiness by scope.

Pure read-only, **computed on read**: no stored artifact, this module never writes a file.
Six independent readiness scopes, each answering ONE question and refusing to speak for the
others:

  INVESTMENT_ENGINE_READINESS  can real capital move? Canon = ``execution_readiness.json``
                                (``ready_for_live``) ∧ ``owner_blockers.json``.
                                ``golive_status.json`` is only an INVENTORY sub-input
                                ("N/29 criteria exist and read something"), never the verdict.
  STUDIO_OS_HEALTH              is the launchd fleet healthy? Canon = ``agent_health.json``.
  PRODUCT_DATA_HEALTH           does the track's own bookkeeping agree with itself? Canon =
                                ``cycle_health.json`` (``evidence_vs_curve`` / ``artifact_integrity``).
  PUBLICATION_HEALTH            are the public numbers fresh and not overstated? Canon =
                                ``site_freshness_report.json``.
  OWNER_CONTROL_HEALTH          can the owner act via Telegram right now? Canon = the bot's
                                beacon (``telegram_bot_capabilities.json``) + ``owner_decision_
                                pending.json`` + ``telegram/push_state.json``.
  PUBLIC_SURFACE                what does the public SITE currently say about go-live? A
                                mirror only — the wording is owner subject #2 (ADR-285); this
                                module reports it and changes nothing.

Why six scopes and not one headline. ADR-530 / REVIEW_1 (RM-TRUTH-01 Phase 1 forensics)
measured the failure of the opposite design: a single public "GoLive ✅ 29/29 pass — READY"
headline sat next to a live ``execution_readiness.json`` saying ``ready_for_live: false``
(custody/MPC, external audit, SPA_EXECUTION_MODE all open); an agent CRITICAL
(``novel_edge_rnd`` — a ``classify_agent`` false positive on an array ``StartCalendarInterval``)
has no path whatsoever to the money gate; and ``owner_decision_pending.json`` was found
CORRUPT with ``generated_at: 2041-11-23`` (INC-1 — a sandboxed G97/ADR-562 probe leaking a
write into prod ``data/``) with no scope-blind monitor able to tell that apart from a healthy
file. One rollup answers none of "is it safe to move money", "is the fleet OK", "are the
public numbers honest" and "can the owner act right now" — it only ever shows whichever of
the four happens to be reddest (or greenest) at the moment someone looks.

**Hard rule (ADR-580 §C3): no aggregate "overall green".** This module returns a LIST, one
dict per scope, and nothing here rolls them up into one verdict. Do not add one; if a caller
needs a single worst-of-N number for a UI badge, that caller computes it AND labels it
"worst of N scopes, not a health score" at the point of display — never inside this module.

Every item carries exactly these fields::

    scope             one of the six names above
    status            scope-specific vocabulary (OK/WARN/CRITICAL/NOT_READY/READY/DEGRADED/
                       CORRUPT/UNKNOWN) — the six questions are different questions; forcing
                       them into one shared enum is how a rollup smuggles itself back in
    as_of             ISO timestamp the canonical source itself carries, or None
    source            path(s) read for this scope
    freshness         {"age_hours", "stale_after_hours", "threshold_source", "stale"}
    blocking_effect   plain-language: what this scope blocks, and — just as important —
                       what it does NOT block
    reason            the specific numbers/fields that produced the status

Absence is a value, not a thing that falls through (inv. #17, `spa_core.utils.observation`):
a missing or wrong-shaped file is ``UNKNOWN`` with a named reason, never ``OK``/0/empty by
default. A file older than its own declared freshness threshold is ALSO ``UNKNOWN`` — never
whatever status its (stale) content happens to say; "measured, but too old to trust" and
"measured, and healthy" must not collapse into the same word. A timestamp more than
``FUTURE_SKEW_MINUTES`` ahead of ``now`` is ``CORRUPT`` — the exact shape of INC-1: this is a
louder, more specific failure than "stale" and is checked first.

Freshness thresholds are ASKED OF THE PRODUCER, never invented here (C1 — one address per
value, source = writer). Where ``architecture/manifest.json`` declares
``produces[].slo_hours`` for the artifact, that number is used, labelled
``"declared:manifest"``. Where a module exports its own constant for exactly this purpose
(the Telegram beacon: ``telegram_health.BEACON_MAX_AGE_S``), that constant is imported,
labelled ``"declared:<module>.<CONST>"``. Only when neither exists does this module fall back
to a literal, and that literal is always labelled ``"fallback"`` so a reader can tell whose
number it is (same convention as ``scripts/update_system_briefing.py::snapshot_budget_min``).

Only stdlib + one sibling monitoring import (``telegram_health`` — read-only constants and a
pure beacon reader, no execution/risk coupling). This module never imports
``spa_core.execution`` (inv. #6): the two files that package WRITES
(``execution_readiness.json``, ``owner_blockers.json``) are read here as plain JSON, never
through the writer module.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.monitoring.telegram_health import (
    BEACON_MAX_AGE_S as _TG_BEACON_MAX_AGE_S,
)
from spa_core.monitoring.telegram_health import (
    beacon_is_fresh as _tg_beacon_is_fresh,
)
from spa_core.monitoring.telegram_health import (
    read_beacon as _tg_read_beacon,
)
from spa_core.utils.observation import observed, observed_number

REPO = Path(__file__).resolve().parents[2]

#: ADR-580 §C3: a timestamp more than this far in the future than `now` makes the WHOLE scope
#: CORRUPT, not merely "fresh" — the exact shape of INC-1 (a sandboxed probe's 2041 stamp).
FUTURE_SKEW_MINUTES = 10.0

#: The six scope names, in the order ADR-580 §C3 lists them. Any caller enumerating scopes
#: should use this tuple rather than re-deriving it from the list `scoped_readiness()` returns.
SCOPES = (
    "INVESTMENT_ENGINE_READINESS",
    "STUDIO_OS_HEALTH",
    "PRODUCT_DATA_HEALTH",
    "PUBLICATION_HEALTH",
    "OWNER_CONTROL_HEALTH",
    "PUBLIC_SURFACE",
)

#: Fallback freshness, used ONLY when architecture/manifest.json declares no `slo_hours` for
#: the artifact and no module exports a dedicated constant. Always labelled "fallback" in the
#: returned item — never presented as if the producer had declared it.
_SLO_FALLBACK_HOURS: dict[str, float] = {
    "execution_readiness.json": 26.0,   # daily audit + one day's grace
    "owner_blockers.json": 26.0,        # daily build + one day's grace
    "golive_status.json": 26.0,         # daily cycle + one day's grace
}

_manifest_slo_cache: Optional[dict[str, float]] = None


def _manifest_slo_hours() -> dict[str, float]:
    """``architecture/manifest.json`` → {artifact basename: slo_hours}. Cached per process."""
    global _manifest_slo_cache
    if _manifest_slo_cache is not None:
        return _manifest_slo_cache
    out: dict[str, float] = {}
    try:
        doc = json.loads((REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _manifest_slo_cache = out
        return out
    for agent in doc.get("agents") or []:
        if not isinstance(agent, dict):
            continue
        for p in agent.get("produces") or []:
            if not isinstance(p, dict):
                continue
            art = p.get("artifact")
            slo = p.get("slo_hours")
            if isinstance(art, str) and isinstance(slo, (int, float)) and not isinstance(slo, bool):
                out[Path(art).name] = float(slo)
    _manifest_slo_cache = out
    return out


def _slo_for(filename: str) -> tuple[float, str]:
    """(stale_after_hours, threshold_source) for ``filename`` — manifest first, then fallback."""
    manifest = _manifest_slo_hours()
    if filename in manifest:
        return manifest[filename], "declared:manifest"
    return _SLO_FALLBACK_HOURS.get(filename, 26.0), "fallback"


def _load_json(path: Path) -> Optional[dict]:
    """Parsed dict, or ``None`` on ANY problem (missing / unreadable / not an object)."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _parse_ts(value: Any) -> Optional[datetime]:
    """A tolerant ISO-8601 parser: ``None`` for anything that is not a parseable timestamp."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_future(ts: Optional[datetime], now: datetime) -> bool:
    if ts is None:
        return False
    return (ts - now).total_seconds() > FUTURE_SKEW_MINUTES * 60.0


def _freshness(ts: Optional[datetime], now: datetime, stale_after_hours: Optional[float],
               threshold_source: str) -> dict:
    if ts is None or stale_after_hours is None:
        return {"age_hours": None, "stale_after_hours": stale_after_hours,
                "threshold_source": threshold_source, "stale": None}
    age_h = (now - ts).total_seconds() / 3600.0
    return {"age_hours": round(age_h, 3), "stale_after_hours": stale_after_hours,
            "threshold_source": threshold_source, "stale": age_h > stale_after_hours}


def _item(scope: str, status: str, as_of: Optional[str], source: str, freshness: dict,
          blocking_effect: str, reason: str, facts: Optional[dict] = None) -> dict:
    """``facts`` (ADR-612) — the same numbers/codes ``reason`` was composed from, as data, so the
    owner layer (``studio_os.owner_language``) can say them in plain Russian without re-parsing a
    technical sentence. ``reason`` stays exactly as before: it is the evidence layer."""
    return {
        "scope": scope,
        "status": status,
        "as_of": as_of,
        "source": source,
        "freshness": freshness,
        "blocking_effect": blocking_effect,
        "reason": reason,
        "facts": facts or {},
    }


# ───────────────────────────── scope 1 — INVESTMENT_ENGINE_READINESS ───────────────────────

_INVESTMENT_BLOCKING = (
    "Блокирует (или снимает блок с) перехода с бумаги на реальные деньги — custody, "
    "cutover, режим исполнения. НЕ блокирует и НЕ описывает paper-trading, флот агентов, "
    "данные трека или публичный сайт — это отдельные, независимые области (ADR-580 §C3)."
)


def _inventory_note(gs: Optional[dict]) -> str:
    """golive_status.json contributes an INVENTORY count only, never the verdict (ADR-530)."""
    if not isinstance(gs, dict):
        return "инвентарь GoLive: golive_status.json отсутствует"
    passed, total = gs.get("passed"), gs.get("total")
    if passed is None or total is None:
        return "инвентарь GoLive: нечитаем (нет passed/total)"
    return f"инвентарь GoLive {passed}/{total} (это счётчик критериев, НЕ готовность к live)"


def _investment_engine_readiness(data_dir: Path, now: datetime) -> dict:
    scope = "INVESTMENT_ENGINE_READINESS"
    er_path = data_dir / "execution_readiness.json"
    ob_path = data_dir / "owner_blockers.json"
    gs_path = data_dir / "golive_status.json"
    source = f"{er_path} ∧ {ob_path} (инвентарь: {gs_path})"
    slo_h, slo_src = _slo_for("execution_readiness.json")

    er = _load_json(er_path)
    ob = _load_json(ob_path)
    gs = _load_json(gs_path)
    inv = _inventory_note(gs)

    er_ts = _parse_ts(observed(er, "audited_at", kind=str)) if er else None
    ob_ts = _parse_ts(observed(ob, "generated_at", kind=str)) if ob else None

    for label, ts in (("execution_readiness.audited_at", er_ts), ("owner_blockers.generated_at", ob_ts)):
        if _is_future(ts, now):
            return _item(scope, "CORRUPT", ts.isoformat(), source,
                         _freshness(ts, now, slo_h, slo_src), _INVESTMENT_BLOCKING,
                         f"{label} в будущем (допуск {FUTURE_SKEW_MINUTES:.0f} мин) — форма "
                         f"INC-1 (ADR-580 §C3); содержимому не доверять", {"why": "future"})

    if er is None:
        return _item(scope, "UNKNOWN", None, source, _freshness(None, now, slo_h, slo_src),
                     _INVESTMENT_BLOCKING,
                     f"{er_path.name} отсутствует — настоящая готовность к live НЕ измерена "
                     f"(инв. #17); {inv}", {"why": "missing"})

    fr = _freshness(er_ts, now, slo_h, slo_src)
    if fr["stale"]:
        return _item(scope, "UNKNOWN", er_ts.isoformat() if er_ts else None, source, fr,
                     _INVESTMENT_BLOCKING,
                     f"{er_path.name} старше {slo_h:.0f} ч ({slo_src}) — не выдаётся за READY "
                     f"или NOT_READY; {inv}", {"why": "stale"})

    ready_for_live = observed(er, "ready_for_live", kind=bool)
    live_blockers = observed(er, "live_blockers", kind=list) or []
    open_gates: list[str] = []
    if isinstance(ob, dict):
        for g in observed(ob, "gates", kind=list) or []:
            if isinstance(g, dict) and g.get("status") != "satisfied":
                open_gates.append(f"{g.get('id')}:{g.get('status')}")

    if ready_for_live is None:
        status, headline = "UNKNOWN", f"{er_path.name} не несёт поля ready_for_live"
    elif ready_for_live and not open_gates:
        status, headline = "READY", "ready_for_live=true, owner_blockers закрыты"
    elif ready_for_live:
        # F11 (integration review, 2026-10-05): контракт в докстринге модуля —
        # ready_for_live ∧ owner_blockers (без открытых гейтов). READY, выданный
        # по ОДНОМУ ready_for_live при открытых owner_blockers, уже называл их в
        # `reason` строкой ниже, но статус оставался READY — то, для чего этот
        # scope написан (один прибор отвечает ОДНИМ вердиктом на ОДИН вопрос),
        # он сам же и нарушал.
        status, headline = "NOT_READY", (
            f"ready_for_live=true, но owner_blockers открыты ({len(open_gates)})")
    else:
        status, headline = "NOT_READY", "ready_for_live=false"

    reason = (f"{headline}; live_blockers={live_blockers or []}; "
              f"owner_blockers открыто={len(open_gates)} ({', '.join(open_gates) or '—'}); {inv}")
    facts = {"why": "no_field"} if ready_for_live is None else {
        "live_blockers": [str(b) for b in live_blockers],
        "open_owner_gates": [g.split(":", 1)[0] for g in open_gates]}
    return _item(scope, status, er_ts.isoformat() if er_ts else None, source, fr,
                 _INVESTMENT_BLOCKING, reason, facts)


# ───────────────────────────── scope 2 — STUDIO_OS_HEALTH ──────────────────────────────────

_STUDIO_BLOCKING = (
    "Описывает здоровье парка launchd-агентов (флот). НЕ блокирует деньги, инвестиционный "
    "гейт или публикацию сайта — независимая область (ADR-580 §C3)."
)
_AGENT_STATUS_MAP = {"OK": "OK", "WARNING": "WARN", "CRITICAL": "CRITICAL"}


def _studio_os_health(data_dir: Path, now: datetime) -> dict:
    scope = "STUDIO_OS_HEALTH"
    path = data_dir / "agent_health.json"
    slo_h, slo_src = _slo_for("agent_health.json")

    doc = _load_json(path)
    if doc is None:
        return _item(scope, "UNKNOWN", None, str(path), _freshness(None, now, slo_h, slo_src),
                     _STUDIO_BLOCKING, f"{path.name} отсутствует — флот не измерен (инв. #17)",
                     {"why": "missing"})

    ts = _parse_ts(observed(doc, "timestamp", kind=str))
    if _is_future(ts, now):
        return _item(scope, "CORRUPT", ts.isoformat(), str(path),
                     _freshness(ts, now, slo_h, slo_src), _STUDIO_BLOCKING,
                     f"timestamp в будущем (допуск {FUTURE_SKEW_MINUTES:.0f} мин)", {"why": "future"})

    fr = _freshness(ts, now, slo_h, slo_src)
    if fr["stale"]:
        return _item(scope, "UNKNOWN", ts.isoformat() if ts else None, str(path), fr,
                     _STUDIO_BLOCKING,
                     f"{path.name} старше {slo_h:.0f} ч ({slo_src}) — снимок не актуален", {"why": "stale"})

    overall = observed(doc, "overall_status", kind=str)
    healthy = observed_number(doc, "healthy_count")
    warning = observed_number(doc, "warning_count")
    critical = observed_number(doc, "critical_count")
    total = observed_number(doc, "total_agents")
    status = _AGENT_STATUS_MAP.get(overall or "", "UNKNOWN")
    reason = (f"overall_status={overall or 'UNKNOWN'}: {healthy}/{total} OK, "
              f"warning={warning}, critical={critical}")
    facts = ({"why": "unknown_value"} if status == "UNKNOWN" else
             {"healthy": healthy, "total": total, "warning": warning, "critical": critical})
    return _item(scope, status, ts.isoformat() if ts else None, str(path), fr,
                 _STUDIO_BLOCKING, reason, facts)


# ───────────────────────────── scope 3 — PRODUCT_DATA_HEALTH ───────────────────────────────

_PRODUCT_BLOCKING = (
    "Советующий сигнал о согласованности доказательной базы трека (журнал доказательств "
    "против кривой капитала) и целостности файлов трека. REVIEW_1 рекомендует подключить его как гейт "
    "GoLive evidence-проверок, но на 2026-10-05 это НЕ подключено: сам по себе он ничего не "
    "блокирует и не трогает инвестиционный гейт, флот или публикацию (ADR-580 §C3)."
)
_CYCLE_STATUS_MAP = {"HEALTHY": "OK", "WARNING": "WARN", "CRITICAL": "CRITICAL", "UNCHECKED": "UNKNOWN"}


def _product_data_health(data_dir: Path, now: datetime) -> dict:
    scope = "PRODUCT_DATA_HEALTH"
    path = data_dir / "cycle_health.json"
    slo_h, slo_src = _slo_for("cycle_health.json")

    doc = _load_json(path)
    if doc is None:
        return _item(scope, "UNKNOWN", None, str(path), _freshness(None, now, slo_h, slo_src),
                     _PRODUCT_BLOCKING, f"{path.name} отсутствует (инв. #17)", {"why": "missing"})

    ts = _parse_ts(observed(doc, "checked_at", kind=str))
    if _is_future(ts, now):
        return _item(scope, "CORRUPT", ts.isoformat(), str(path),
                     _freshness(ts, now, slo_h, slo_src), _PRODUCT_BLOCKING,
                     f"checked_at в будущем (допуск {FUTURE_SKEW_MINUTES:.0f} мин)", {"why": "future"})

    fr = _freshness(ts, now, slo_h, slo_src)
    if fr["stale"]:
        return _item(scope, "UNKNOWN", ts.isoformat() if ts else None, str(path), fr,
                     _PRODUCT_BLOCKING, f"{path.name} старше {slo_h:.0f} ч ({slo_src})", {"why": "stale"})

    checks = observed(doc, "checks", kind=dict) or {}
    ev = checks.get("evidence_vs_curve") if isinstance(checks.get("evidence_vs_curve"), dict) else {}
    ai = checks.get("artifact_integrity") if isinstance(checks.get("artifact_integrity"), dict) else {}
    overall = observed(doc, "overall", kind=str)
    status = _CYCLE_STATUS_MAP.get(overall or "", "UNKNOWN")

    ev_status = ev.get("status", "UNCHECKED")
    ev_detail = f"evidence_vs_curve={ev_status}"
    if ev.get("divergent_days") is not None and ev.get("compared_days") is not None:
        ev_detail += f" ({ev['divergent_days']}/{ev['compared_days']} дат расходятся)"
    ai_detail = f"artifact_integrity={ai.get('status', 'UNCHECKED')}"
    reason = f"overall={overall or 'UNKNOWN'}; {ev_detail}; {ai_detail}"
    facts = ({"why": "unknown_value"} if status == "UNKNOWN" else
             {"evidence_vs_curve": ev_status, "divergent_days": ev.get("divergent_days"),
              "compared_days": ev.get("compared_days"), "artifact_integrity": ai.get("status", "UNCHECKED")})
    return _item(scope, status, ts.isoformat() if ts else None, str(path), fr,
                 _PRODUCT_BLOCKING, reason, facts)


# ───────────────────────────── scope 4 — PUBLICATION_HEALTH ────────────────────────────────

_PUBLICATION_BLOCKING = (
    "Свежесть и честность публичных цифр earn-defi.com (расхождение витрины с живым API). НЕ "
    "блокирует инвестиционный гейт, флот агентов или данные трека — независимая область "
    "(ADR-580 §C3). Формулировки сайта — предмет №2 владельца (ADR-285); этот модуль их не "
    "меняет и не оценивает, только читает."
)


def _publication_health(data_dir: Path, now: datetime) -> dict:
    scope = "PUBLICATION_HEALTH"
    path = data_dir / "site_freshness_report.json"
    slo_h, slo_src = _slo_for("site_freshness_report.json")

    doc = _load_json(path)
    if doc is None:
        return _item(scope, "UNKNOWN", None, str(path), _freshness(None, now, slo_h, slo_src),
                     _PUBLICATION_BLOCKING, f"{path.name} отсутствует (инв. #17)", {"why": "missing"})

    ts = _parse_ts(observed(doc, "ts", kind=str))
    if _is_future(ts, now):
        return _item(scope, "CORRUPT", ts.isoformat(), str(path),
                     _freshness(ts, now, slo_h, slo_src), _PUBLICATION_BLOCKING,
                     f"ts в будущем (допуск {FUTURE_SKEW_MINUTES:.0f} мин)", {"why": "future"})

    fr = _freshness(ts, now, slo_h, slo_src)
    if fr["stale"]:
        return _item(scope, "UNKNOWN", ts.isoformat() if ts else None, str(path), fr,
                     _PUBLICATION_BLOCKING, f"{path.name} старше {slo_h:.0f} ч ({slo_src})", {"why": "stale"})

    ok = observed(doc, "ok", kind=bool)
    fails = observed(doc, "fails", kind=list) or []
    codes = sorted({f.get("code") for f in fails if isinstance(f, dict) and f.get("code")})
    severities = {f.get("severity") for f in fails if isinstance(f, dict)}

    if "PUBLISHER_STUCK" in codes or "CRITICAL" in severities:
        status = "CRITICAL"
    elif ok is True and not fails:
        status = "OK"
    elif fails:
        status = "WARN"
    else:
        status = "UNKNOWN"

    reason = f"ok={ok}; n_fails={len(fails)}; коды={codes or '—'}"
    facts = {"why": "unknown_value"} if status == "UNKNOWN" else {"codes": list(codes)}
    return _item(scope, status, ts.isoformat() if ts else None, str(path), fr,
                 _PUBLICATION_BLOCKING, reason, facts)


# ───────────────────────────── scope 5 — OWNER_CONTROL_HEALTH ──────────────────────────────

_OWNER_BLOCKING = (
    "Может ли владелец сейчас управлять системой через Telegram (кнопки, /report). НЕ "
    "блокирует деньги, флот или сайт — независимая область (ADR-580 §C3)."
)


def _owner_control_health(data_dir: Path, now: datetime) -> dict:
    scope = "OWNER_CONTROL_HEALTH"
    beacon_path = data_dir / "telegram_bot_capabilities.json"
    pending_path = data_dir / "owner_decision_pending.json"
    push_path = data_dir / "telegram" / "push_state.json"
    source = f"{beacon_path} + {pending_path} + {push_path}"
    slo_h = _TG_BEACON_MAX_AGE_S / 3600.0
    slo_src = "declared:telegram_health.BEACON_MAX_AGE_S"

    beacon = _tg_read_beacon(beacon_path)
    pending = _load_json(pending_path)
    push = _load_json(push_path)

    beacon_ts = _parse_ts(beacon.get("updated_at")) if isinstance(beacon, dict) else None
    pending_ts = _parse_ts(observed(pending, "generated_at", kind=str)) if pending else None
    push_ts = _parse_ts(observed(push, "updated_at", kind=str)) if push else None

    for label, ts in (("telegram_bot_capabilities.updated_at", beacon_ts),
                       ("owner_decision_pending.generated_at", pending_ts),
                       ("push_state.updated_at", push_ts)):
        if _is_future(ts, now):
            return _item(scope, "CORRUPT", ts.isoformat(), source,
                         _freshness(ts, now, slo_h, slo_src), _OWNER_BLOCKING,
                         f"{label} в будущем (допуск {FUTURE_SKEW_MINUTES:.0f} мин) — форма "
                         f"INC-1 (ADR-580 §C3)", {"why": "future"})

    pending_note = "owner_decision_pending.json отсутствует" if pending is None else "owner_decision_pending.json читаем"
    push_note = "push_state.json отсутствует" if push is None else "push_state.json читаем"

    if beacon is None:
        return _item(scope, "UNKNOWN", None, source, _freshness(None, now, slo_h, slo_src),
                     _OWNER_BLOCKING,
                     f"{beacon_path.name} отсутствует — бот не объявляет умений (инв. #17); "
                     f"{pending_note}; {push_note}", {"why": "missing"})

    if beacon_ts is None:
        fr = _freshness(None, now, slo_h, slo_src)
        return _item(scope, "UNKNOWN", None, source, fr, _OWNER_BLOCKING,
                     f"{beacon_path.name} без разбираемой updated_at; {pending_note}; {push_note}",
                     {"why": "no_field"})

    age_s = (now - beacon_ts).total_seconds()
    fr = {"age_hours": round(age_s / 3600.0, 4), "stale_after_hours": round(slo_h, 4),
          "threshold_source": slo_src, "stale": not _tg_beacon_is_fresh(age_s)}

    if not _tg_beacon_is_fresh(age_s):
        status = "DEGRADED"
        reason = (f"маячок {age_s:.0f}с (норма ≤{_TG_BEACON_MAX_AGE_S:.0f}с, {slo_src}) — "
                  f"боту не хватает признака жизни; {pending_note}; {push_note}")
    else:
        status = "OK"
        reason = f"маячок свежий ({max(age_s, 0.0):.0f}с); {pending_note}; {push_note}"

    return _item(scope, status, beacon_ts.isoformat(), source, fr, _OWNER_BLOCKING, reason,
                 {"beacon_age_s": round(age_s), "beacon_max_age_s": _TG_BEACON_MAX_AGE_S})


# ───────────────────────────── scope 6 — PUBLIC_SURFACE ────────────────────────────────────

_PUBLIC_SURFACE_BLOCKING = (
    "Ничего не блокирует — это зеркало того, что ПОСЕТИТЕЛЬ сайта видит о go-live прямо "
    "сейчас. Формулировка «Go-live progress N/N» — предмет №2 владельца (ADR-285); этот "
    "модуль её не меняет и не одобряет/отклоняет, только читает и сообщает."
)
#: Weekly publish cadence (.claude/rules/site-numbers.md) + buffer. No producer declares a
#: slo_hours for this snapshot, so this is a named FALLBACK, not an invented "truth".
_PUBLIC_SURFACE_STALE_DAYS = 14.0


def _public_surface(data_dir: Path, now: datetime) -> dict:
    scope = "PUBLIC_SURFACE"
    repo_root = Path(data_dir).resolve().parent
    path = repo_root / "landing" / "src" / "data" / "track_snapshot.json"

    doc = _load_json(path)
    if doc is None:
        fr = {"age_hours": None, "stale_after_hours": None, "threshold_source": "n/a", "stale": None}
        return _item(scope, "UNKNOWN", None, str(path), fr, _PUBLIC_SURFACE_BLOCKING,
                     f"{path} не найден рядом с data_dir — зеркало публичного сайта недоступно "
                     f"отсюда (инв. #17)", {"why": "missing"})

    as_of_str = observed(doc, "as_of", kind=str)
    gates_passed, gates_total = doc.get("gates_passed"), doc.get("gates_total")

    as_of_date: Optional[date] = None
    if as_of_str:
        try:
            as_of_date = date.fromisoformat(as_of_str[:10])
        except ValueError:
            as_of_date = None
    age_days = (now.date() - as_of_date).days if as_of_date else None
    stale = age_days is not None and age_days > _PUBLIC_SURFACE_STALE_DAYS
    fr = {"age_hours": round(age_days * 24.0, 1) if age_days is not None else None,
          "stale_after_hours": _PUBLIC_SURFACE_STALE_DAYS * 24.0,
          "threshold_source": "fallback:weekly-publish-cadence+buffer", "stale": stale}

    if gates_passed is None or gates_total is None or stale:
        status = "UNKNOWN"
    else:
        status = "OK"

    reason = (f"сайт показывает «Go-live progress» = {gates_passed}/{gates_total} по "
              f"состоянию на {as_of_str or '?'} (инвентарная цифра, НЕ ready_for_live — "
              f"ADR-530)")
    facts = ({"why": "stale" if stale else "no_field"} if status == "UNKNOWN" else
             {"gates_passed": gates_passed, "gates_total": gates_total, "as_of": as_of_str})
    return _item(scope, status, as_of_str, str(path), fr, _PUBLIC_SURFACE_BLOCKING, reason, facts)


# ───────────────────────────── public API ───────────────────────────────────────────────────

def scoped_readiness(data_dir: str | Path, now: Optional[datetime] = None) -> list[dict]:
    """The six ADR-580 §C3 readiness scopes, each computed fresh from its own canon.

    ``data_dir`` is the ``data/`` directory to read from (never defaults to the production
    tree — callers pass it explicitly, which is what lets this be tested against a read-only
    copy). ``now`` is injectable (defaults to the real clock) so freshness/CORRUPT maths is
    deterministic in tests (deployment.md "time is an input, not an environment").

    Returns exactly six dicts, one per name in ``SCOPES``, in that order. **No seventh,
    aggregate item** — see the module docstring.
    """
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return [
        _investment_engine_readiness(data_dir, now),
        _studio_os_health(data_dir, now),
        _product_data_health(data_dir, now),
        _publication_health(data_dir, now),
        _owner_control_health(data_dir, now),
        _public_surface(data_dir, now),
    ]


def _main() -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=str(REPO / "data"))
    args = ap.parse_args()
    print(json.dumps(scoped_readiness(args.data_dir), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
