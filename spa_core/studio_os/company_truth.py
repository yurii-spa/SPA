"""spa_core/studio_os/company_truth.py — Company Truth read model (RM-TRUTH-01, ADR-580 →
Director OS v2 design ``scratchpad/rmtruth/D/DIRECTOR_OS_V2_DESIGN.md``, doctrine ADR-592
(number reserved; WP3 writes it)).

ONE module computes "what is true about the company right now", for Mission Control's new
``truth`` bundle key. It is **pure read** (C4, ADR-580): nothing here writes a file, runs a
subprocess itself, or imports ``spa_core.execution`` / ``spa_core.telegram`` /
``governance.kill_switch`` writers. Host probes (``ps``, ``launchctl``) and already-computed
upstream sections (Director's ``rep``, Mission Control's own ``capital``/``board``/``roadmap``)
are passed in by the ONLY caller, ``spa_core.studio_os.mission_control.build()`` — an import
ratchet (``test_company_truth_import_ratchet.py``) enforces that no other module reaches in.

Every emitted value is a **cell** (design §2.0)::

    {"value": …, "display_ru": "…", "display_en": "…",
     "metric_type": "OPERATIONAL|COUNT|REALIZED_PAPER|OBSERVED|BACKTEST|TARGET|MODELLED|
                     POLICY|DECISION|TIMESTAMP|READINESS",
     "state": "MEASURED|MEASURED_ZERO|NOT_MEASURED|NOT_ENOUGH_HISTORY|STALE|CORRUPT",
     "as_of": "ISO|null", "canon": "<repo-relative path or module.function>",
     "freshness": {"age_min": n|null, "stale_after_min": n|null, "rule": "…"},
     "unknown_ru": "<the Russian text shown when state is not a measured one>"}

Absence is a value (inv. #17): a missing/unreadable canon never becomes 0, "", healthy or
green — it becomes ``NOT_MEASURED`` (or ``STALE``/``CORRUPT``) with a named Russian reason,
and the cell's own ``value`` is ``None``. No aggregate "all green" is produced anywhere in
this module — ``readiness_scopes.scoped_readiness`` already refuses that for its six scopes
and this module re-projects them unchanged (never rolled into one word).

Only stdlib + the already-existing sibling primitives named in ``work_packages.json``'s
``reads_only`` list (``readiness_scopes``, ``problem_store``, ``owner_queue.subject``,
``compound_apy``, ``sleeve_track``, ``build_loop``, ``scripts/check_undelivered_work.py`` via
``importlib`` — never copied). LLM forbidden (classification/counting, not judgement).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.studio_os import owner_language

SCHEMA = "company-truth/1"

# ── cell state vocabulary (design §2.0) ──────────────────────────────────────────────────────────
MEASURED = "MEASURED"
MEASURED_ZERO = "MEASURED_ZERO"
NOT_MEASURED = "NOT_MEASURED"
NOT_ENOUGH_HISTORY = "NOT_ENOUGH_HISTORY"
STALE = "STALE"
CORRUPT = "CORRUPT"
STATES = (MEASURED, MEASURED_ZERO, NOT_MEASURED, NOT_ENOUGH_HISTORY, STALE, CORRUPT)

METRIC_TYPES = ("OPERATIONAL", "COUNT", "REALIZED_PAPER", "OBSERVED", "BACKTEST", "TARGET",
                "MODELLED", "POLICY", "DECISION", "TIMESTAMP", "READINESS", "FORWARD_PAPER")

#: Same convention as ``readiness_scopes.FUTURE_SKEW_MINUTES`` — a timestamp more than this far
#: in the future than ``now`` is CORRUPT (the exact shape of INC-1), never merely "fresh".
FUTURE_SKEW_MINUTES = 10.0

REPO = Path(__file__).resolve().parents[2]

STAGE_RU = {
    "IDEA": "идея", "TASK": "задача", "ASSIGNED": "назначено", "RUN": "в работе",
    "ARTIFACT": "результат в git", "REVIEW": "проверка", "DECISION": "решение",
    "RELEASE": "в проде", "OUTCOME": "эффект измерен", "MEMORY": "записано в память",
}


# ── cell contract ─────────────────────────────────────────────────────────────────────────────
def freshness(age_min: Optional[float], stale_after_min: Optional[float], rule: str) -> dict:
    return {"age_min": age_min, "stale_after_min": stale_after_min, "rule": rule}


def cell(*, value: Any, display_ru: Optional[str], display_en: Optional[str], metric_type: str,
         state: str, as_of: Optional[str], canon: str, fresh: dict, unknown_ru: str,
         unknown_en: Optional[str] = None, **extra: Any) -> dict:
    """``extra`` carries the RAW fields a card needs beyond the cell envelope (design §2.0's
    "bare field next to a state" — app.js's own ``tf()`` composes the sentence from these, never
    a second display string invented here). Composed cards instead fill ``display_ru``/
    ``display_en`` and pass no ``extra``; the two are not mixed on the same card (§2.0's own
    "two kinds of text" rule, mirrored in the WP2 fixture's header comment)."""
    assert metric_type in METRIC_TYPES, metric_type
    assert state in STATES, state
    out = {"value": value, "display_ru": display_ru, "display_en": display_en,
           "metric_type": metric_type, "state": state, "as_of": as_of, "canon": canon,
           "freshness": fresh, "unknown_ru": unknown_ru, "unknown_en": unknown_en or unknown_ru}
    out.update(extra)
    return out


def unknown(canon: str, metric_type: str, unknown_ru: str, *, unknown_en: Optional[str] = None,
            state: str = NOT_MEASURED, stale_after_min: Optional[float] = None,
            rule: str = "n/a") -> dict:
    """A cell with no measurement — never 0/''/healthy by default (inv. #17)."""
    return cell(value=None, display_ru=unknown_ru, display_en=unknown_en or unknown_ru,
                metric_type=metric_type, state=state, as_of=None, canon=canon,
                fresh=freshness(None, stale_after_min, rule), unknown_ru=unknown_ru)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        try:
            d = datetime.strptime(value.strip()[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _staleness(as_of: Optional[datetime], now: datetime, stale_after_min: Optional[float],
               rule: str) -> tuple[str, dict]:
    """(state, freshness) given a found timestamp — ``MEASURED``/``STALE``/``CORRUPT``.
    Absence itself is handled by the caller (never reaches here as ``NOT_MEASURED``)."""
    if as_of is None:
        return NOT_MEASURED, freshness(None, stale_after_min, rule)
    age_min = (now - as_of).total_seconds() / 60.0
    if age_min < -FUTURE_SKEW_MINUTES:
        return CORRUPT, freshness(round(age_min, 1), stale_after_min, rule)
    if stale_after_min is not None and age_min > stale_after_min:
        return STALE, freshness(round(age_min, 1), stale_after_min, rule)
    return MEASURED, freshness(round(age_min, 1), stale_after_min, rule)


def _age_text(age_min: Optional[float]) -> str:
    if not isinstance(age_min, (int, float)):
        return "?"
    return f"{age_min / 60:.0f} ч" if abs(age_min) >= 60 else f"{age_min:.0f} мин"


def _stale_or_absent(state: str, age_min: Optional[float], stale_ru: str, absent_ru: str) -> str:
    """Review finding 2026-10-06: a STALE cell WAS measured once — "не измерена" is a lie about a
    cell that only aged out. One wording rule used at every ``_staleness()`` call site, instead
    of the same "не измерена" string regardless of which of MEASURED/STALE/CORRUPT came back."""
    return stale_ru.format(age=_age_text(age_min)) if state == STALE else absent_ru


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


#: ``readiness_scopes`` items carry an absolute ``source`` path (built from the caller's own
#: ``data_dir``) and may echo one into ``reason``. First-level hygiene (design §2.5) forbids raw
#: paths — this module re-projects each scope with a fixed, repo-relative canon and redacts any
#: absolute path that leaked into free text, rather than trust a sibling module's own notion of
#: "source" to already be display-safe.
_SCOPE_CANON = {
    "INVESTMENT_ENGINE_READINESS": "data/execution_readiness.json + data/owner_blockers.json "
                                   "(data/golive_status.json: инвентарь, не вердикт)",
    "STUDIO_OS_HEALTH": "data/agent_health.json",
    "PRODUCT_DATA_HEALTH": "data/cycle_health.json",
    "PUBLICATION_HEALTH": "data/site_freshness_report.json",
    "OWNER_CONTROL_HEALTH": "data/telegram_bot_capabilities.json + data/owner_decision_pending.json + data/telegram/push_state.json",
    "PUBLIC_SURFACE": "landing/src/data/track_snapshot.json",
}
_ABS_PATH_RE = re.compile(r"(?:/Users|/private|/var|/tmp|/Library|/opt|/home)/[^\s'\"`)]+")
#: a bare state-file name leaked into free text is the SAME §2.5 violation as an absolute path —
#: just without the leading slash (`"site_freshness_report.json старше 24 ч"`). Found 2026-10-06
#: by the Wave 2 review: every `_item(..., f"{path.name} ...")` call in `readiness_scopes.py`
#: embeds the canon's own filename into `reason`. Fixed here (the re-projector), not there, per
#: this module's own doctrine of never trusting a sibling's "reason" to already be display-safe.
_FILENAME_RE = re.compile(r"\b[\w][\w.-]*\.(?:json|jsonl|db|log|md)\b")


def _redact(text: Optional[str]) -> Optional[str]:
    """Strip absolute paths from a sibling module's free-text ``reason``/error text before it can
    reach a cell's ``display_ru``/``unknown_ru`` (same rationale as ``_sanitize_scope`` below, but
    for the non-scope sibling reads — e.g. ``trading_lab_view``'s ``evidence.db не найден по пути
    <abs path>``, found reaching the model in ``test_mission_control_contract.py`` on a Mac run)."""
    if not text:
        return text
    return _ABS_PATH_RE.sub("<path>", str(text))


def _sanitize_scope(item: dict) -> dict:
    """Re-projects one ``readiness_scopes`` item for first-level display (design §2.5): fixed
    repo-relative canon instead of the sibling's own absolute ``source``; ``reason`` with every
    absolute path AND every bare state-file name redacted; and the studio-card shape the UI
    actually reads (``key``/``reason_ru``/``reason_en``/``blocks_ru``/``does_not_block_ru``),
    added alongside (not instead of) the original ``scope``/``reason``/``blocking_effect`` keys
    so existing by-``scope`` lookups in this module keep working unchanged."""
    out = dict(item)
    out["source"] = _SCOPE_CANON.get(item.get("scope"), "n/a")
    reason = _ABS_PATH_RE.sub("<path>", str(item.get("reason") or ""))
    reason = _FILENAME_RE.sub("<файл>", reason)
    out["reason"] = reason
    out["key"] = item.get("scope")
    out["reason_ru"] = reason or None
    out["reason_en"] = reason or None
    blocking = str(item.get("blocking_effect") or "")
    parts = blocking.split(". ", 1)
    blocks = parts[0].strip().rstrip(".") if parts and parts[0].strip() else None
    does_not_block = parts[1].strip().rstrip(".") if len(parts) > 1 and parts[1].strip() else None
    out["blocks_ru"] = out["blocks_en"] = blocks
    out["does_not_block_ru"] = out["does_not_block_en"] = does_not_block
    # ADR-612: owner layer in plain Russian from status + facts; ``reason_ru`` above stays the
    # evidence layer, shown under «технические подробности».
    plain = owner_language.scope_plain(item)
    out["plain_ru"], out["plain_tone"] = plain["text"], plain["tone"]
    return out


def _manifest_slo_minutes(manifest: Optional[dict], artifact_name: str, fallback_min: float) -> tuple[float, str]:
    for agent in (manifest or {}).get("agents") or []:
        if not isinstance(agent, dict):
            continue
        for p in agent.get("produces") or []:
            if isinstance(p, dict) and isinstance(p.get("artifact"), str) and Path(p["artifact"]).name == artifact_name:
                slo = p.get("slo_hours")
                if isinstance(slo, (int, float)) and not isinstance(slo, bool):
                    return float(slo) * 60.0, "declared:manifest"
    return fallback_min, "fallback"


# ── §4 typed fleet counts ───────────────────────────────────────────────────────────────────────
def typed_fleet(manifest: Optional[dict], launchctl_map: Optional[dict], agent_health_doc: Optional[dict],
                roles_doc: Optional[dict], announced: int, unannounced: Optional[int]) -> dict:
    """Design §4 — six typed counts. A role is never added to a process count; a retired-but-
    loaded or unknown-orphan label never silently joins ``declared``/``loaded``, it is its own
    red row (C11)."""
    canon = "architecture/manifest.json + data/agent_health.json + launchctl list"
    if manifest is None:
        return {"headline": unknown("architecture/manifest.json", "COUNT", "Состав флота не измерен"),
                "runtime_services": {"declared": None, "loaded": None},
                "managed_agents": {"declared": None, "loaded": None},
                "configured_roles": {"n": None},
                "active_workers": {"announced": announced, "unannounced": unannounced},
                "retired_loaded": {"n": None, "labels": []},
                "unknown_orphans": {"n": None, "labels": []}}

    agents = [a for a in manifest.get("agents") or [] if isinstance(a, dict)]
    active = [a for a in agents if a.get("intent") == "active"]
    retired = [a for a in agents if a.get("intent") == "retired"]
    runtime = [a for a in active if a.get("schedule") == "daemon"]
    managed = [a for a in active if a.get("schedule") != "daemon"]
    declared_labels = {a.get("label") for a in agents if a.get("label")}
    lc = launchctl_map if isinstance(launchctl_map, dict) else None

    def _loaded(rows):
        return None if lc is None else sum(1 for a in rows if a.get("label") in lc)

    retired_loaded = sorted(a.get("label") for a in retired if lc is not None and a.get("label") in lc)
    unknown_orphans = (sorted(lbl for lbl in lc
                              if (lbl.startswith("com.spa.") or lbl.startswith("com.studiobridge."))
                              and lbl not in declared_labels) if lc is not None else [])
    roles_n = (sum(1 for r in (roles_doc or {}).get("roles") or [] if isinstance(r, dict) and r.get("implemented"))
              if roles_doc is not None else None)

    declared_total = len(runtime) + len(managed)
    ah_by_label = {a.get("label"): a for a in (agent_health_doc or {}).get("agents") or [] if isinstance(a, dict)}
    if agent_health_doc is None:
        ok = crit = warn = None
        text_ru = f"в норме ? из {declared_total} — состояние не измерено"
        text_en = f"? of {declared_total} OK — state not measured"
        headline = cell(value=None, display_ru=text_ru, display_en=text_en, metric_type="COUNT",
                        state=NOT_MEASURED, as_of=None, canon="data/agent_health.json",
                        fresh=freshness(None, None, "n/a"), unknown_ru=text_ru)
    else:
        ok = sum(1 for lbl in declared_labels if (ah_by_label.get(lbl) or {}).get("status") == "OK")
        crit = sum(1 for lbl in declared_labels if (ah_by_label.get(lbl) or {}).get("status") == "CRITICAL")
        warn = sum(1 for lbl in declared_labels if (ah_by_label.get(lbl) or {}).get("status") == "WARNING")
        extra = []
        if retired_loaded:
            extra.append(f"вне учёта (выведено, но запущено): {len(retired_loaded)}")
        if unknown_orphans:
            extra.append(f"вне учёта (не в манифесте): {len(unknown_orphans)}")
        suffix = ""
        if crit or warn:
            suffix += f" · аварий {crit} · предупреждений {warn}"
        if extra:
            suffix += " · " + " · ".join(extra)
        headline = cell(value={"ok": ok, "declared": declared_total, "critical": crit, "warning": warn},
                        display_ru=f"в норме {ok} из {declared_total} объявленных{suffix}",
                        display_en=f"{ok} of {declared_total} declared OK", metric_type="COUNT",
                        state=(MEASURED_ZERO if declared_total == 0 else MEASURED), as_of=None, canon=canon,
                        fresh=freshness(None, None, "n/a"), unknown_ru="")
    agent_by_label = {a.get("label"): a for a in agents}
    failing_labels = sorted(lbl for lbl in declared_labels if (ah_by_label.get(lbl) or {}).get("status") == "CRITICAL")
    return {
        "headline": headline,
        "runtime_services": {"declared": len(runtime), "loaded": _loaded(runtime)},
        "managed_agents": {"declared": len(managed), "loaded": _loaded(managed)},
        "configured_roles": {"n": roles_n},
        "active_workers": {"announced": announced, "unannounced": unannounced},
        "retired_loaded": {"n": len(retired_loaded), "labels": retired_loaded},
        "unknown_orphans": {"n": len(unknown_orphans), "labels": unknown_orphans},
        "failing_labels": failing_labels, "agent_by_label": agent_by_label,
    }


def _agent_display_name(label: str, agent: Optional[dict]) -> str:
    """design §2.5 — agent names on the first level are never a raw ``com.spa.`` label; a role
    (if declared) is appended, an undeclared one falls back to the label's own plain words."""
    bare = re.sub(r"^com\.(?:spa|studiobridge)\.", "", label or "").replace("_", " ").replace("-", " ").strip()
    bare = bare or "агент без описания"
    role = (agent or {}).get("role")
    return f"{bare} ({role})" if role else bare


def fleet_cell(fleet: dict) -> dict:
    """Design §4's UI-facing re-projection: ONE cell with the typed counts flattened under
    ``types`` and human-named failing agents under ``failing`` (never a raw ``com.spa.`` label on
    the first level, §2.5) — ``typed_fleet()`` above stays the granular, independently-testable
    computation; this never recomputes anything, only reshapes it."""
    hl = fleet["headline"]
    rs, ma, cr, aw = fleet["runtime_services"], fleet["managed_agents"], fleet["configured_roles"], fleet["active_workers"]
    rl, uo = fleet["retired_loaded"], fleet["unknown_orphans"]
    types = {
        "runtime_services": {"loaded": rs["loaded"], "declared": rs["declared"], "ok": rs["loaded"] == rs["declared"]},
        "managed_agents": {"loaded": ma["loaded"], "declared": ma["declared"], "ok": ma["loaded"] == ma["declared"]},
        "configured_roles": {"n": cr["n"], "ok": True},
        # unannounced Claude activity is informational, not a fleet-health signal (design §4) —
        # this row never paints the warn/red styling the other five typed counts can.
        "active_workers": {"a": aw["announced"], "u": aw["unannounced"], "ok": True},
        "retired_loaded": {"n": rl["n"], "ok": rl["n"] == 0},
        "unknown_orphans": {"n": uo["n"], "ok": uo["n"] == 0},
    }
    v = hl.get("value") or {}
    agent_by_label = fleet.get("agent_by_label") or {}
    failing = [{"name_ru": _agent_display_name(lbl, agent_by_label.get(lbl)),
               "name_en": _agent_display_name(lbl, agent_by_label.get(lbl))}
              for lbl in fleet.get("failing_labels") or []]
    return {**hl, "ok": v.get("ok"), "declared": v.get("declared"), "types": types, "failing": failing}


# ── §3 "what is Claude working on" ──────────────────────────────────────────────────────────────
def _load_check_undelivered_work():
    """Load ``scripts/check_undelivered_work.py`` as a module (never copied — one liveness
    rule). ``None`` is itself a measurement: the caller renders liveness UNKNOWN, not dead."""
    path = REPO / "scripts" / "check_undelivered_work.py"
    try:
        spec = importlib.util.spec_from_file_location("_company_truth_cuw", path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 — a broken sibling is "not measured", never a crash
        return None


def _next_stage_after(stage: Optional[str]) -> Optional[str]:
    from spa_core.studio_os.build_loop import STAGES
    if stage not in STAGES:
        return None
    i = STAGES.index(stage)
    return STAGES[i + 1] if i + 1 < len(STAGES) else None


def _card_lookup(tracker: Optional[dict], card_id: str) -> Optional[dict]:
    if not tracker:
        return None
    return tracker.get(f"{card_id}.md") or tracker.get(card_id)


def _card_next_step(body: str) -> Optional[str]:
    m = re.search(r"^##\s*Следующий шаг[^\n]*\n(.*?)(?=^##\s|\Z)", body or "", re.M | re.S)
    return m.group(1).strip()[:200] if m and m.group(1).strip() else None


def claude_work(log_rows: Optional[list], tracker: Optional[dict], roadmap: dict,
                lineage_fn: Optional[Callable], problems: Optional[dict], now: datetime,
                total_claude_processes: Optional[int], *, measure_host: bool = True,
                ps_probe: Optional[Callable] = None, cmd_probe: Optional[Callable] = None,
                bad_lines: int = 0) -> dict:
    """Design §3 — pure derivation of "who is working on what right now", from the house
    ANNOUNCE protocol (``data/session_changes.jsonl``). No second store, no new liveness rule:
    liveness is measured by ``check_undelivered_work.session_state`` (loaded, never copied).
    """
    canon = "data/session_changes.jsonl"
    epic = roadmap.get("current") if isinstance(roadmap, dict) else None
    epic_text = (epic or {}).get("epic") if isinstance(epic, dict) else None
    epic_display = epic_text or "эпик в работе не объявлен"

    if log_rows is None:
        return {**unknown(canon, "OPERATIONAL", "Неизвестно, что делает Claude — журнал объявлений не прочитан"),
                "epic": epic_text, "active": [], "undeclared": None, "bad_lines": bad_lines}

    last_by_session: dict[str, dict] = {}
    for row in log_rows:
        if isinstance(row, dict) and row.get("session"):
            last_by_session[str(row["session"])] = row

    cuw = _load_check_undelivered_work() if measure_host else None
    active: list[dict] = []
    for sess, entry in sorted(last_by_session.items()):
        if entry.get("card_state") == "done":
            continue
        if not measure_host:
            liveness_note = "не удалось проверить, жива ли сессия"
            is_active = False
        elif cuw is None:
            liveness_note = "сторож активности сессии недоступен — не удалось проверить"
            is_active = False
        else:
            ps = ps_probe or cuw._ps_lstart
            cp = cmd_probe or cuw._ps_command
            state, why = cuw.session_state(entry, "", ps=ps, cmd_probe=cp)
            liveness_note = why
            is_active = state == cuw.ACTIVE
        if not is_active:
            continue
        card = entry.get("card")
        card_title = stage = blocker = next_step = None
        fm: dict = {}
        if card:
            rec = _card_lookup(tracker, card)
            fm = (rec or {}).get("fm") or {}
            card_title = fm.get("title")
            lin = None
            if lineage_fn is not None:
                try:
                    lin = lineage_fn(card)
                except Exception:  # noqa: BLE001
                    lin = None
            if isinstance(lin, dict) and lin.get("state") != "NOT_FOUND":
                stages_doc = lin.get("stages") or {}
                from spa_core.studio_os.build_loop import STAGES as _ORDER
                for s in _ORDER:
                    if stages_doc.get(s, {}).get("state") != "DONE":
                        stage = s
                        break
            if fm.get("status") == "blocked":
                blocker = "статус карточки blocked"
            elif fm.get("blocked_by"):
                blocker = str(fm.get("blocked_by"))
            elif isinstance(problems, dict):
                owner_names = {fm.get("owner"), fm.get("claimed_by")} - {None}
                for p in (problems.get("problems") or {}).values():
                    if isinstance(p, dict) and p.get("status") == "OPEN" and p.get("agent") in owner_names:
                        blocker = p.get("cause_code")
                        break
            next_step = _card_next_step((rec or {}).get("body") or "")
            if next_step is None and stage:
                nxt = _next_stage_after(stage)
                next_step = f"следующая стадия: {STAGE_RU.get(nxt, nxt)}" if nxt else None
        active.append({"session": sess, "card": card, "card_title": card_title,
                       "stage": stage, "stage_ru": STAGE_RU.get(stage), "blocker": blocker,
                       "next_step": next_step, "summary": (entry.get("summary") or "")[:140],
                       "ts": entry.get("ts"), "liveness_note": liveness_note})

    undeclared = (max(0, total_claude_processes - len(active)) if total_claude_processes is not None else None)

    card_title = stage_key = blocker = next_step = next_stage_key = None
    if active:
        a = active[0]
        card_title, stage_key, blocker, next_step = a["card_title"], a["stage"], a["blocker"], a["next_step"]
        if stage_key:
            next_stage_key = _next_stage_after(stage_key)

    # bug found by the WP2/WP1 integration seam (2026-10-06): this branch used to ignore
    # `undeclared` entirely — "сейчас никто не работает" even when `total_claude_processes`
    # proved Claude WAS running, just without an announced card (inv. #17: a measured count must
    # never be swallowed by a stale "nothing" sentence). And a host count failure
    # (`total_claude_processes is None`, `measure_host=True`) must say so honestly, never render
    # as the SAME "nothing is happening" MEASURED_ZERO the true zero-count case gets.
    if active:
        stage_ru = STAGE_RU.get(stage_key, stage_key) or "?"
        text_ru = text_en = (f"{epic_display} · карточка «{card_title or a['card'] or '—'}» · "
                             f"стадия: {stage_ru} · блокер: {blocker or 'нет'}")
        state = MEASURED
    elif not measure_host:
        text_ru = text_en = "не удалось проверить, жива ли сессия"
        state = NOT_MEASURED
    elif undeclared is None:
        text_ru = text_en = "не удалось посчитать процессы Claude — число неизвестно"
        state = NOT_MEASURED
    elif undeclared > 0:
        text_ru = text_en = f"Claude работает, но не объявил над чем (процессов без объявления: {undeclared})"
        state = MEASURED
    else:
        text_ru = text_en = "сейчас никто не работает"
        state = MEASURED_ZERO

    return {
        **cell(value={"active": len(active), "undeclared": undeclared}, display_ru=text_ru, display_en=text_en,
               metric_type="OPERATIONAL", state=state, as_of=_iso(now), canon=canon,
               fresh=freshness(0.0, None, "live probe"),
               unknown_ru="Неизвестно, что делает Claude — журнал объявлений не прочитан",
               epic=epic_text, sessions_announced=len(active), sessions_undeclared=undeclared,
               card_title_ru=card_title, card_title_en=card_title, stage_key=stage_key,
               blocker_ru=blocker, blocker_en=blocker, next_step_ru=next_step, next_step_en=next_step,
               next_stage_key=next_stage_key),
        "epic": epic_text, "active": active, "undeclared": undeclared, "bad_lines": bad_lines,
    }


# ── §2.1 Owner Home ──────────────────────────────────────────────────────────────────────────────
def money_chip(real_capital: Optional[dict]) -> dict:
    """Design §2.1 — the header chip is RAW (``usd``), composed by app.js's own
    ``tf("header.money_chip", {usd})``; a pre-composed ``display_ru`` here is the wrong half of
    the two-text-kinds rule (§2.0) and was never read by the real header renderer."""
    rc = real_capital or {}
    if rc.get("state") == "LIVE_NOT_APPROVED":
        return cell(value=0, display_ru=None, display_en=None, metric_type="POLICY", state=MEASURED,
                    as_of=None, canon="paper_trading_status.execution_mode",
                    fresh=freshness(None, None, "n/a"), unknown_ru="Реальные деньги: не измерено",
                    usd=0)
    return unknown("paper_trading_status.execution_mode", "POLICY", "Реальные деньги: не измерено")


def tile_system(fleet: dict) -> dict:
    fc = fleet_cell(fleet)
    return {**fc, "canon": "architecture/manifest.json + data/agent_health.json"}


def tile_yield(equity_doc: Optional[dict], now: datetime) -> dict:
    canon = "data/equity_curve_daily.json"
    if equity_doc is None:
        return unknown(canon, "REALIZED_PAPER", "Доходность не измерена — дневной цикл не записал кривую капитала")
    from spa_core.reporting.compound_apy import compound_annualized_pct, evidenced_bars, max_drawdown_pct
    bars = evidenced_bars(equity_doc)
    if len(bars) < 2:
        return {**unknown(canon, "REALIZED_PAPER",
                          "Доходность не измерена — дневной цикл не записал кривую капитала"),
                "state": NOT_ENOUGH_HISTORY}
    first, last = bars[0].get("equity"), bars[-1].get("equity")
    apy = compound_annualized_pct(first, last, len(bars))
    dd = max_drawdown_pct(bars)
    # Prefer the document's OWN `generated_at` for freshness — a bar's `date` is a calendar day
    # with no time-of-day, so comparing IT against a 26h threshold would call a bar written this
    # morning "stale" for no reason but the missing clock precision. Falling back to the bar date
    # (no generated_at at all) uses a looser 48h threshold for exactly that reason.
    gen_at = _parse_ts(equity_doc.get("generated_at"))
    if gen_at is not None:
        as_of, slo_min, rule = gen_at, 26 * 60, "fallback"
    else:
        as_of, slo_min, rule = _parse_ts(bars[-1].get("date")), 48 * 60, "fallback:date-only-bar"
    state, fr = _staleness(as_of, now, slo_min, rule)
    if apy is None:
        state = NOT_ENOUGH_HISTORY if state == MEASURED else state
    text_ru = (f"Консервативный: {apy:.1f} % годовых · худшая просадка {dd:.2f} % · {len(bars)} дн. (бумага)"
              if apy is not None else "Консервативный: копится история")
    unknown_ru = _stale_or_absent(
        state, fr.get("age_min"),
        "Доходность устарела: последняя кривая капитала записана {age} назад",
        "Доходность не измерена — дневной цикл не записал кривую капитала")
    return cell(value={"apy_pct": apy, "max_drawdown_pct": dd, "evidenced_days": len(bars)},
               display_ru=text_ru, display_en=text_ru, metric_type="REALIZED_PAPER", state=state,
               as_of=_iso(as_of), canon=canon, fresh=fr, unknown_ru=unknown_ru)


def _yield_tile(conservative: dict, books: dict) -> dict:
    """home.tile.yield (design §2.1 row 2) merges the conservative book's own composed sentence
    with a one-line accumulating note for Balanced/Aggressive, read from the SAME ``capital.defi``
    books this build already computed — never a second sleeve_track_view call."""
    tile = dict(conservative)
    if tile.get("state") != MEASURED:
        return tile
    notes = []
    for key, label in (("balanced", "Сбалансированный"), ("aggressive", "Агрессивный")):
        b = books.get(key) or {}
        if b.get("state") == NOT_ENOUGH_HISTORY:
            notes.append(f"{label} {b.get('accumulating_days', 0)} из 30")
    if notes:
        extra = " Копится: " + ", ".join(notes) + "."
        tile["display_ru"] = (tile.get("display_ru") or "") + extra
        tile["display_en"] = tile["display_ru"]
    return tile


def tile_product(publication_scope: Optional[dict], site_doc: Optional[dict] = None) -> dict:
    canon = "data/site_freshness_report.json"
    sc = publication_scope or {}
    status = sc.get("status")
    if status in (None, "UNKNOWN"):
        return unknown(canon, "READINESS", "Свежесть сайта не измерена — отчёт сторожа сайта не прочитан")
    state = MEASURED if status == "OK" else (CORRUPT if status == "CORRUPT" else MEASURED)
    # Review finding 2026-10-06 (defect b): this used to echo the SCOPE's own `reason`, which for
    # PUBLICATION_HEALTH is a raw diagnostic dump ("ok=False; n_fails=5; коды=[...]") — composed
    # straight from `data/site_freshness_report.json`'s OWN fields instead, in plain Russian.
    text_ru = text_en = f"сайт: {_site_freshness_text(site_doc, status)}"
    return cell(value={"status": status}, display_ru=text_ru, display_en=text_en, metric_type="READINESS",
               state=state, as_of=sc.get("as_of"), canon=canon,
               fresh=freshness(sc.get("freshness", {}).get("age_hours", None) and
                               sc["freshness"]["age_hours"] * 60, None, sc.get("freshness", {}).get("threshold_source", "n/a")),
               unknown_ru="Свежесть сайта не измерена — отчёт сторожа сайта не прочитан")


def _site_freshness_text(doc: Optional[dict], status: str) -> str:
    if not isinstance(doc, dict):
        return "в норме" if status == "OK" else status
    site_as_of = doc.get("site_as_of")
    if doc.get("publisher_stuck"):
        return f"публикация застряла: сайт показывает данные от {site_as_of or '?'}"
    if status == "OK":
        return f"данные от {site_as_of}" if site_as_of else "в норме"
    fails = doc.get("fails") or []
    codes = sorted({f.get("code") for f in fails if isinstance(f, dict) and f.get("code")})
    if codes:
        return "проверка не прошла: " + ", ".join(codes[:3]) + ("…" if len(codes) > 3 else "")
    return status


def tile_claude(cw: dict) -> dict:
    return dict(cw)


def _decisions_counts_cell(decisions_triage: dict, canon: str) -> dict:
    """Shared by home.tile.needs (one composed sentence) and studio.decisions_summary (the SAME
    counts, read raw by app.js's own templates) — one computation, two re-projections.
    Review finding 2026-10-06 (defect d): leading with "ваших вопросов: 0" reads as "nothing to
    worry about" even when 11 cards are waiting with no declared subject. Director's own home
    ("ждёт решения, тема не объявлена", `scripts/cartographer/director_shell.py`) leads with the
    TOTAL waiting instead — the owner's personal count is never hidden, just never shown as the
    whole picture either."""
    counts = decisions_triage.get("counts") or {}
    if decisions_triage.get("state") == NOT_MEASURED:
        return unknown(canon, "DECISION", "Очередь решений не измерена — трекер не прочитан")
    own, undeclared, answered = counts.get("owner", 0), counts.get("undeclared", 0), counts.get("answered", 0)
    waiting = own + undeclared
    text_ru = text_en = (f"ждёт решения: {waiting} (у {undeclared} тема не объявлена) · "
                         f"ваших вопросов: {own} · отвечено, едет в git: {answered}")
    return cell(value=counts, display_ru=text_ru, display_en=text_en, metric_type="DECISION",
               state=(MEASURED_ZERO if not (own or undeclared or answered) else MEASURED), as_of=None,
               canon=canon, fresh=freshness(None, None, "n/a"),
               unknown_ru="Очередь решений не измерена — трекер не прочитан",
               own=own, undeclared=undeclared, answered=answered, waiting=waiting)


def tile_needs(decisions_triage: dict) -> dict:
    return _decisions_counts_cell(decisions_triage, "nimbalyst-local/tracker (owner-decision cards)")


def attention(cells_by_name: dict[str, dict], kill_switch_active: Optional[bool], derisk_active: Optional[bool],
             old_owner_items: list[dict], critical_problems: int, same_host_backup: bool) -> list[dict]:
    """design §2.1 — ≤3 lines, deterministic priority order. Each item carries a closed-vocabulary
    ``kind`` + the RAW vars app.js's ``renderAttentionLine`` composes with (design §2.0's "bare
    field next to a state" rule) — NOT a pre-composed ``text_ru``. Bug found 2026-10-06 (defect a):
    the old shape had no ``kind`` at all, so every line fell through app.js's closed switch to its
    `else` branch and rendered the literal word "не измерено" for all three lines, regardless of
    which kind they were — a verified real bug, not a hypothetical one."""
    out: list[dict] = []
    for name, c in cells_by_name.items():
        if c.get("state") == CORRUPT:
            out.append({"key": "corrupt", "kind": "corrupt", "what_ru": name, "what_en": name,
                       "link_area": "studio"})
    if kill_switch_active is True:
        out.append({"key": "kill_switch", "kind": "kill_switch", "link_area": "studio"})
    if derisk_active is True:
        out.append({"key": "derisk", "kind": "derisk", "link_area": "studio"})
    for item in old_owner_items:
        out.append({"key": "old_owner_item", "kind": "old_owner_item", "days": item.get("days"),
                    "title_ru": item.get("title"), "title_en": item.get("title"), "link_area": "decisions"})
    if critical_problems:
        out.append({"key": "problem", "kind": "problem",
                    "what_ru": f"критических проблем: {critical_problems}",
                    "what_en": f"critical problems: {critical_problems}", "link_area": "decisions"})
    if same_host_backup:
        out.append({"key": "same_host", "kind": "same_host", "link_area": "studio"})
    return out[:3]


def home(*, fleet: dict, yield_cell: dict, defi_books: dict, publication_scope: Optional[dict],
        site_doc: Optional[dict], cw: dict, decisions_triage: dict, real_capital: Optional[dict],
        kill_switch_active: Optional[bool], derisk_active: Optional[bool], old_owner_items: list[dict],
        critical_problems: int, same_host_backup: bool, now: datetime) -> dict:
    # `yield_cell` is computed ONCE in build() and reused here AND by capital.defi.books.conservative
    # (design C1: "no second formula" — both used to call `tile_yield()`/`compound_apy` separately).
    tiles = {"system": tile_system(fleet), "yield": _yield_tile(yield_cell, defi_books),
             "product": tile_product(publication_scope, site_doc), "claude": tile_claude(cw),
             "needs": tile_needs(decisions_triage)}
    # design §2.1 — each strip tile names the tab its tap opens (the WP2 fixture's own
    # ``link_area``); the UI does not read it today, but the fixture declares it on every tile
    # and the strict seam contract (test_company_truth_matches_ui_contract.py) walks the whole
    # fixture, not a hand-picked subset of it.
    tile_link_area = {"system": "studio", "yield": "capital", "product": "product", "claude": "studio",
                      "needs": "decisions"}
    strip = [{"key": k, "link_area": tile_link_area[k], **v} for k, v in tiles.items()]
    return {"strip": strip, "money_chip": money_chip(real_capital),
           "attention": attention(tiles, kill_switch_active, derisk_active, old_owner_items,
                                  critical_problems, same_host_backup)}


# ── §2.2 CAPITAL ─────────────────────────────────────────────────────────────────────────────────
def _defi_books(packages_section: Optional[dict], hy_doc: Optional[dict], lp_doc: Optional[dict],
                yield_cell: dict) -> dict:
    """``renderDefiBook`` reads ``rate_ru``/``dd_ru``/``evidenced_days`` (mature) or
    ``accumulating_days`` (NOT_ENOUGH_HISTORY) RAW, composing the sentence itself via
    ``tf("home.tile.yield.value"/".accumulating", …)`` — no ``display_ru`` on these three cells
    (§2.0's two kinds of text; the fixture's ``capital.defi.books`` carries exactly these fields
    and no other).

    Conservative's rate/drawdown/evidenced-days come from ``yield_cell`` — the SAME
    ``tile_yield()`` cell Главная already shows (design C1: "no second formula"). Checked
    against the real tree 2026-10-06: ``packages_section.items.conservative`` carries work/data
    STATUS words and a plain-text ``position_ru``, but no rate/dd field at all — building the
    book from it directly (the integration defect this whole module was rewritten for) left
    ``rate_ru``/``dd_ru`` permanently ``None`` even while Главная showed a real 4.9 %."""
    pk = (packages_section or {}).get("items") or {}
    conservative_src = pk.get("conservative") or {}
    v = yield_cell.get("value") or {}
    apy, dd = v.get("apy_pct"), v.get("max_drawdown_pct")
    cons_rate_ru = f"{apy:.1f} %" if isinstance(apy, (int, float)) else None
    cons_dd_ru = f"{dd:.2f} %" if isinstance(dd, (int, float)) else None
    out = {"conservative": cell(
        value=conservative_src or None, display_ru=None, display_en=None, metric_type="REALIZED_PAPER",
        state=yield_cell.get("state", NOT_MEASURED), as_of=yield_cell.get("as_of"),
        canon=yield_cell.get("canon") or "data/equity_curve_daily.json",
        fresh=yield_cell.get("freshness") or freshness(None, None, "n/a"),
        unknown_ru=yield_cell.get("unknown_ru") or "Книга не прочитана — состояние неизвестно",
        rate_ru=cons_rate_ru, rate_en=cons_rate_ru, dd_ru=cons_dd_ru, dd_en=cons_dd_ru,
        evidenced_days=v.get("evidenced_days"),
        accumulating_days=(v.get("evidenced_days") or 0) if yield_cell.get("state") == NOT_ENOUGH_HISTORY else None,
        work=conservative_src.get("work"), data=conservative_src.get("data"))}
    from spa_core.paper_trading.sleeve_track import sleeve_track_view
    for book, doc in (("balanced", hy_doc), ("aggressive", lp_doc)):
        canon = f"data/{'hy' if book == 'balanced' else 'lp'}_paper_trading.json"
        if doc is None:
            out[book] = unknown(canon, "REALIZED_PAPER", "Книга не прочитана — состояние неизвестно")
            continue
        view = sleeve_track_view(doc, book)
        if not view.get("reportable"):
            out[book] = cell(value=view, display_ru=None, display_en=None, metric_type="REALIZED_PAPER",
                             state=NOT_ENOUGH_HISTORY, as_of=None, canon=canon, fresh=freshness(None, None, "n/a"),
                             unknown_ru="Книга не прочитана — состояние неизвестно",
                             accumulating_days=view.get("days_with_positions") or 0)
        else:
            rate_ru = f"{view.get('apy_pct')} %"
            dd_ru = f"{view.get('dd_pct')} %"
            out[book] = cell(value=view, display_ru=None, display_en=None, metric_type="REALIZED_PAPER",
                             state=MEASURED, as_of=view.get("observed_accrual_since"), canon=canon,
                             fresh=freshness(None, None, "n/a"),
                             unknown_ru="Книга не прочитана — состояние неизвестно",
                             rate_ru=rate_ru, rate_en=rate_ru, dd_ru=dd_ru, dd_en=dd_ru,
                             evidenced_days=view.get("evidenced_days"))
    return out


_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _band_target_pct(band: Optional[dict]) -> Optional[float]:
    """``tier_bands.json`` has no bare numeric field (checked against the real tree 2026-10-06):
    the target lives inside ``band_ru``/``en`` prose ("до 6% · целевой диапазон…"). A declared
    ``target_apy_pct`` wins if a future version of the file adds one; otherwise the leading
    percentage in the band text is read, never guessed."""
    if not isinstance(band, dict):
        return None
    if isinstance(band.get("target_apy_pct"), (int, float)):
        return band["target_apy_pct"]
    for key in ("band_ru", "band_en"):
        m = _PCT_RE.search(str(band.get(key) or ""))
        if m:
            return float(m.group(1))
    return None


def _defi_targets(mirror: Path) -> dict:
    canon = "landing/src/lib/tier_bands.json"
    doc = _read_json(Path(mirror) / "landing" / "src" / "lib" / "tier_bands.json")
    if not isinstance(doc, dict):
        return unknown(canon, "TARGET", "Ориентир не записан")
    bands = {k: _band_target_pct(doc.get(k)) for k in ("conservative", "balanced", "aggressive")}
    if not any(v is not None for v in bands.values()):
        return unknown(canon, "TARGET", "Ориентир не записан")
    parts = [f"{label} {bands[k]} %" for k, label in
            (("conservative", "Консервативный"), ("balanced", "Сбалансированный"), ("aggressive", "Агрессивный"))
            if bands.get(k) is not None]
    text_ru = text_en = " · ".join(parts)
    return cell(value=bands, display_ru=text_ru, display_en=text_en, metric_type="TARGET", state=MEASURED,
               as_of=None, canon=canon, fresh=freshness(None, None, "n/a"), unknown_ru="Ориентир не записан")


def capital_defi(packages_section: Optional[dict], hy_doc: Optional[dict], lp_doc: Optional[dict],
                 mirror: Path, yield_cell: dict) -> dict:
    """design §2.2 — ``{"books": {conservative, balanced, aggressive}, "targets": …}``. The
    integration defect this module was rewritten for (2026-10-06): the real producer used to
    return ``{conservative, balanced, aggressive}`` directly, with a nested ``value`` object the
    UI never reads — every Capital DeFi card rendered «не измерено» on real data even though the
    public home page showed a real Conservative rate."""
    return {"books": _defi_books(packages_section, hy_doc, lp_doc, yield_cell), "targets": _defi_targets(mirror)}


def capital_trading_lab(data_dir: Path, now: datetime) -> dict:
    """design §2.2 — ``trading_lab_view`` lives on another WP's branch; guarded import only,
    never copied. Absent module ⇒ UNKNOWN with a named Russian reason, by design. The card is RAW
    (``candidates``/``forward``/``champions``/``chain_ok``) — ``renderTradingLab`` composes its
    own chips via ``tf()`` and never reads a ``display_ru`` here."""
    canon = "spa_core.trading_research.read_model.trading_lab_view"
    try:
        from spa_core.trading_research.read_model import trading_lab_view, STALE_AFTER_H  # type: ignore
    except ImportError:
        return unknown(canon, "OPERATIONAL", "Лаборатория не измерена — модуль ещё не слит в это дерево")
    try:
        doc = trading_lab_view(data_dir)  # canonical arg is the repo data/ dir; resolved internally
    except Exception as exc:  # noqa: BLE001
        return unknown(canon, "OPERATIONAL", f"Лаборатория не измерена — статус движка не прочитан ({type(exc).__name__})")
    if not isinstance(doc, dict):
        return unknown(canon, "OPERATIONAL", "Лаборатория не измерена — статус движка не прочитан")
    # Карточка измерена, только если измерено ЯДРО (сколько стратегий в реестре), а не потому, что
    # модуль вернул словарь: при отсутствующем леджере trading_lab_view отдаёт 21 ячейку
    # NOT_MEASURED с причинами, и объявить такую карточку MEASURED значило бы выдать «нечем
    # померить» за ответ (инв. #17; найдено при слиянии Wave 2 RM-TRUTH-01).
    core = doc.get("strategies_researched")
    if isinstance(core, dict) and "state" in core and core.get("state") not in ("MEASURED", "MEASURED_ZERO"):
        # Wave 2 review, 2026-10-06 (P1-b): ``reason`` is a sibling module's free text and can
        # carry an absolute path ("evidence.db не найден по пути /Users/…") — reached the model
        # unredacted and failed test_mission_control_contract.py on a Mac run.
        why = _redact(core.get("reason")) or "ядро лаборатории не измерено"
        return unknown(canon, "OPERATIONAL", f"Лаборатория не измерена — {why}")
    forward = doc.get("forward_paper_active") or {}
    champions = doc.get("champions") or {}
    integrity = doc.get("evidence_integrity") or {}
    engine = doc.get("engine_health") or {}
    gen_ms = engine.get("as_of") if engine.get("as_of") is not None else core.get("as_of")
    as_of_dt = (datetime.fromtimestamp(gen_ms / 1000.0, tz=timezone.utc)
               if isinstance(gen_ms, (int, float)) else None)
    state, fr = _staleness(as_of_dt, now, STALE_AFTER_H * 60.0, "declared:STALE_AFTER_H")
    unknown_ru = _stale_or_absent(state, fr.get("age_min"),
                                 "Лаборатория устарела: статус движка записан {age} назад",
                                 "Лаборатория не измерена — статус движка не прочитан")
    return cell(value=doc, display_ru=None, display_en=None, metric_type="OPERATIONAL", state=state,
               as_of=_iso(as_of_dt), canon=canon, fresh=fr, unknown_ru=unknown_ru,
               candidates=core.get("value"), forward=forward.get("value"), champions=champions.get("value"),
               chain_ok=(integrity.get("value") == "VERIFIED"))


def capital_btc(trading_lab_cell: dict) -> dict:
    """RAW consensus sentence + the two flags ``renderBtc`` checks: ``no_canon`` (true — no ADR
    has named the BTC-signal canon yet, design §0 row BTC) and ``external_product`` (false — this
    IS the Lab's own signal, not the separate earn-defi engine reference)."""
    canon = "spa_core.trading_research.read_model.trading_lab_view.btc_signal_consensus_by_timeframe"
    if trading_lab_cell.get("state") not in (MEASURED, MEASURED_ZERO):
        return unknown(canon, "OBSERVED", "BTC-сигнал не измерен")
    doc = trading_lab_cell.get("value") or {}
    breadth_cell = doc.get("btc_signal_consensus_by_timeframe") or {}
    if breadth_cell.get("state") != "MEASURED":
        return unknown(canon, "OBSERVED", "BTC-сигнал не измерен")
    breadth = breadth_cell.get("value") or {}
    label_ru = {"long": "лонг", "short": "шорт", "flat": "нейтрально"}
    parts = []
    for tf in sorted(breadth):
        counts = breadth[tf] or {}
        dom = max(counts, key=lambda k: counts.get(k, 0)) if counts else None
        parts.append(f"{tf} {label_ru.get(dom, '—')}")
    text_ru = text_en = ("Консенсус сигналов по таймфреймам: " + ", ".join(parts)) if parts else "нет наблюдений"
    return cell(value=breadth, display_ru=text_ru, display_en=text_en, metric_type="OBSERVED", state=MEASURED,
               as_of=trading_lab_cell.get("as_of"), canon=canon,
               fresh=trading_lab_cell.get("freshness") or freshness(None, None, "n/a"),
               unknown_ru="BTC-сигнал не измерен", no_canon=True, external_product=False)


def capital_basis(research_universe: Optional[dict]) -> dict:
    """RAW ``fees_blocked`` flag (``renderBasis`` shows a banner over it) + a composed
    ``display_ru`` — basis has a sentence AND a flag side by side (same pattern as BTC)."""
    canon = "data/research_factory/ledger.jsonl + status.json"
    ru = research_universe or {}
    meta = ru.get("_meta") or {}
    if meta.get("state") != "HEALTHY":
        return unknown(canon, "COUNT", "Фабрика исследований ещё не запускалась")
    basis = ru.get("by_mechanism", {}).get("FUNDING_CAPTURE") or ru.get("basis_track")
    rows = basis if isinstance(basis, list) else []
    insufficient = sum(1 for r in rows if isinstance(r, dict) and r.get("state") == "DATA_INSUFFICIENT")
    fees_blocked = bool(rows) and insufficient == len(rows)
    text_ru = text_en = (f"кандидатов по комиссионному захвату: {len(rows)}"
                         + (", все «недостаточно данных»" if fees_blocked else ""))
    return cell(value=basis, display_ru=text_ru, display_en=text_en, metric_type="COUNT", state=MEASURED,
               as_of=meta.get("observed_at"), canon=canon,
               fresh=freshness(meta.get("age_min"), meta.get("stale_after_min"), "declared:manifest"),
               unknown_ru="Фабрика исследований ещё не запускалась", fees_blocked=fees_blocked)


def capital_treasury(research_universe: Optional[dict], current_positions: Optional[dict]) -> dict:
    """RAW ``reference_periods``/``cash_usd`` — ``renderTreasury`` composes both via ``tf()``/
    literal ``$``, no ``display_ru`` on this card (matches the fixture)."""
    canon = "data/research_factory/ledger.jsonl + status.json + data/current_positions.json"
    ru = research_universe or {}
    meta = ru.get("_meta") or {}
    if meta.get("state") != "HEALTHY":
        return unknown(canon, "COUNT", "Нет данных по казначейству")
    rows = [c for c in (ru.get("top_candidates") or []) if c.get("domain") == "TREASURY"]
    periods = max((c.get("forward_periods") or 0) for c in rows) if rows else 0
    cash_usd = (current_positions or {}).get("cash_usd")
    return cell(value=rows, display_ru=None, display_en=None, metric_type="COUNT", state=MEASURED,
               as_of=meta.get("observed_at"), canon=canon,
               fresh=freshness(meta.get("age_min"), meta.get("stale_after_min"), "declared:manifest"),
               unknown_ru="Нет данных по казначейству", reference_periods=periods, cash_usd=cash_usd)


def capital_sherlock(research_universe: Optional[dict]) -> dict:
    """RAW ``usable``/``total``/``awaiting_review`` — never a candidate id or other hash on the
    first level (§2.5; Wave 2 review flagged this as a risk, this card never carries one)."""
    canon = "data/research_factory/ledger.jsonl (sherlock, ADR-564)"
    ru = research_universe or {}
    sh = ru.get("sherlock")
    if not isinstance(sh, dict):
        return unknown(canon, "COUNT", "Реестр фактов не прочитан")
    usable = sh.get("evidence_ready")
    # `reviewed_today` у фабрики — ФЛАГ (проверялось ли сегодня), а не число фактов; печатать
    # его счётчиком значило бы показать владельцу «True» (замер на проде 06.10, seam-тест).
    # Числа «всего» в этом источнике нет ⇒ третий исход (None), а не догадка (инв. #17).
    total = sh.get("facts_total") if isinstance(sh.get("facts_total"), int) else None
    usable = usable if isinstance(usable, int) and not isinstance(usable, bool) else None
    awaiting = (total - usable) if isinstance(usable, int) and isinstance(total, int) else None
    return cell(value=sh, display_ru=None, display_en=None, metric_type="COUNT", state=MEASURED, as_of=None,
               canon=canon, fresh=freshness(None, None, "n/a"), unknown_ru="Реестр фактов не прочитан",
               usable=usable, total=total, awaiting_review=awaiting)


def capital_oracle(investment_cio: Optional[dict]) -> dict:
    """RAW ``stance`` only — ``renderOracle`` translates it via ``capital.oracle.stance.<stance>``
    and shows the static advisory note; no confidence/date on the first level."""
    canon = "data/investment_cio/ledger.jsonl + latest.json (ADR-554)"
    cio = investment_cio or {}
    meta = cio.get("_meta") or {}
    if meta.get("state") == "CRITICAL":
        return cell(value=None, display_ru=None, display_en=None, metric_type="DECISION", state=NOT_MEASURED,
                   as_of=meta.get("observed_at"), canon=canon,
                   fresh=freshness(meta.get("age_min"), meta.get("stale_after_min"), "declared:manifest"),
                   unknown_ru="Рекомендация отозвана — цепочка решений нарушена")
    if meta.get("state") != "HEALTHY" or not cio.get("stance"):
        return unknown(canon, "DECISION", "Рекомендаций ещё не было")
    return cell(value={"stance": cio.get("stance"), "confidence": cio.get("confidence"), "date": cio.get("date")},
               display_ru=None, display_en=None, metric_type="DECISION", state=MEASURED,
               as_of=meta.get("observed_at"), canon=canon,
               fresh=freshness(meta.get("age_min"), meta.get("stale_after_min"), "declared:manifest"),
               unknown_ru="Рекомендаций ещё не было", stance=cio.get("stance"))


def capital_readiness(live_readiness: Optional[dict], investment_scope: Optional[dict]) -> dict:
    """RAW ``ready``/``conditions_open``/``inventory_passed``/``inventory_total``/``blockers`` —
    the headline text stays OUT of the first level entirely (design §2.5 + the explicit "29/29
    is never a readiness row" rule); ``renderReadiness`` composes every line itself."""
    canon = "data/execution_readiness.json ∧ data/owner_blockers.json (readiness_scopes.INVESTMENT_ENGINE_READINESS); data/capital_shadow/ledger.jsonl"
    sc = investment_scope or {}
    status = sc.get("status")
    if status in (None, "UNKNOWN"):
        return unknown(canon, "READINESS", "Готовность не измерена — деньги не трогать")
    pending = None
    lr = live_readiness or {}
    if isinstance(lr.get("owner_decisions_pending"), int):
        pending = lr["owner_decisions_pending"]
    inv_passed = inv_total = None
    m = re.search(r"GoLive\s*(\d+)\s*/\s*(\d+)", sc.get("reason") or "")
    if m:
        inv_passed, inv_total = int(m.group(1)), int(m.group(2))
    blockers = [{"ru": b.get("gate"), "en": b.get("gate")} for b in (lr.get("top_blockers") or [])
               if isinstance(b, dict) and b.get("gate")]
    return cell(value={"status": status, "go_live_conditions_open": pending}, display_ru=None, display_en=None,
               metric_type="READINESS", state=(MEASURED if status in ("READY", "NOT_READY") else NOT_MEASURED),
               as_of=sc.get("as_of"), canon=canon, fresh=freshness(None, None, "n/a"),
               unknown_ru="Готовность не измерена — деньги не трогать",
               ready=(status == "READY"), conditions_open=pending,
               inventory_passed=inv_passed, inventory_total=inv_total, blockers=blockers)


def capital_cards(*, packages_section, hy_doc, lp_doc, data_dir: Path, mirror: Path, research_universe,
                  investment_cio, live_readiness, investment_scope, current_positions=None,
                  yield_cell: dict, now: datetime) -> dict:
    tl = capital_trading_lab(data_dir, now)
    defi = capital_defi(packages_section, hy_doc, lp_doc, mirror, yield_cell)
    return {"defi": defi, "trading_lab": tl,
           "btc": capital_btc(tl), "basis": capital_basis(research_universe),
           "treasury_rwa": capital_treasury(research_universe, current_positions),
           "sherlock": capital_sherlock(research_universe),
           "oracle": capital_oracle(investment_cio),
           "readiness": capital_readiness(live_readiness, investment_scope)}


# ── §2.3 STUDIO OS ───────────────────────────────────────────────────────────────────────────────
def studio_roadmap(roadmap: dict) -> dict:
    canon = "docs/ROADMAP.md"
    items = roadmap.get("items")
    if items is None:
        return unknown(canon, "DECISION", "Дорожная карта не прочитана")
    cur = roadmap.get("current")
    text_ru = f"сейчас: {cur['epic']}" if cur else "эпик в работе не объявлен"
    confirmed = roadmap.get("confirmed")
    return cell(value={"items": items, "current": cur, "confirmed": confirmed},
               display_ru=text_ru, display_en=text_ru, metric_type="DECISION", state=MEASURED, as_of=None,
               canon=canon, fresh=freshness(None, None, "n/a"), unknown_ru="Дорожная карта не прочитана",
               confirmed_date=confirmed)


def studio_tasks(board: Optional[dict], orphans: Optional[dict]) -> dict:
    canon = "build_loop.board (origin tracker) + data/orphan_report.json"
    if board is None or board.get("_meta", {}).get("state") == "NOT_MEASURED" or "counts" not in board:
        return unknown(canon, "COUNT", "Доска задач не прочитана")
    counts = board.get("counts") or {}
    queued = board.get("queued", counts.get("new", 0) + counts.get("backlog", 0))
    in_progress = counts.get("in-progress", 0)
    stale = (orphans or {}).get("counts", {}).get("stale_in_progress") if isinstance(orphans, dict) else None
    blocked = counts.get("blocked", 0)
    text_ru = f"в очереди: {queued} · в статусе «в работе»: {in_progress}" + (f" (залежались: {stale})" if stale else "")
    return cell(value={"queued": queued, "in_progress": in_progress, "blocked": blocked, "stale": stale},
               display_ru=text_ru, display_en=text_ru, metric_type="COUNT", state=MEASURED, as_of=None,
               canon=canon, fresh=freshness(None, None, "n/a"), unknown_ru="Доска задач не прочитана",
               # bare fields — ``renderTasks`` composes its own chip row via ``tf()`` from
               # ``cell.queued``/``cell.in_progress``/``cell.in_progress_stale``/``cell.blocked``
               # (chips rendered blank before this fix: Wave 2 round-2 review, 2026-10-06).
               queued=queued, in_progress=in_progress, in_progress_stale=stale, blocked=blocked)


def studio_incidents(push_state_section: Optional[dict], now: Optional[datetime] = None) -> dict:
    canon = "data/telegram/push_state.json"
    if push_state_section is None or push_state_section.get("_meta", {}).get("state") == "NOT_MEASURED":
        return unknown(canon, "OPERATIONAL", "Состояние тревог не прочитано")
    open_ = push_state_section.get("open") or []
    now = now or datetime.now(timezone.utc)
    items = []
    for it in open_:
        if not isinstance(it, dict):
            continue
        plain = owner_language.incident_plain(it.get("event"))
        since = _parse_ts(it.get("since"))
        items.append({"title_ru": it.get("event"), "title_en": it.get("event"),
                      "since_ru": it.get("since"), "since_en": it.get("since"),
                      # ADR-612 owner layer; the raw event key + ISO time above are the evidence layer
                      "plain_ru": plain["text"], "plain_tone": plain["tone"],
                      "since_plain_ru": owner_language.age_ru((now - since).total_seconds() / 60.0) if since else None})
    return cell(value={"open": len(open_)}, display_ru=f"открыто: {len(open_)}", display_en=f"open: {len(open_)}",
               metric_type="OPERATIONAL", state=(MEASURED_ZERO if not open_ else MEASURED), as_of=None,
               canon=canon, fresh=freshness(None, None, "n/a"), unknown_ru="Состояние тревог не прочитано",
               # bare ``open``/``items`` — ``renderIncidents`` reads ``cell.open`` for the chip and
               # ``cell.items`` for the per-event lines (Wave 2 round-2 review, 2026-10-06: both
               # were nested under ``value`` and never read, so the chip printed «открыто: »).
               open=len(open_), items=items)


def studio_problems(data_dir: Path, now: datetime) -> dict:
    canon = "data/problems.json"
    path = data_dir / "problems.json"
    if not path.is_file():
        return unknown(canon, "COUNT", "Реестр проблем ещё не запущен")
    from spa_core.monitoring.problem_store import load_store
    store = load_store(data_dir)
    rows = list((store.get("problems") or {}).values())
    open_ = [p for p in rows if p.get("status") == "OPEN"]
    mitigated = [p for p in rows if p.get("status") == "MITIGATED"]
    closed_recent = [p for p in rows if p.get("status") == "CLOSED" and p.get("last_seen")
                     and _parse_ts(p["last_seen"]) and (now - _parse_ts(p["last_seen"])) < timedelta(days=7)]
    text_ru = f"открыто: {len(open_)} · утихли без причины: {len(mitigated)} · закрыто за неделю: {len(closed_recent)}"
    items = []
    for p in open_:
        plain = owner_language.problem_plain(p.get("agent"), p.get("cause_code"), p.get("detail"))
        items.append({"agent_ru": p.get("agent"), "cause_ru": _redact(p.get("detail")), "cause_en": _redact(p.get("detail")),
                      "occurrences": p.get("occurrences"), "rca": bool(p.get("rca")),
                      # ADR-612 owner layer; agent/cause above + the code here are the evidence layer
                      "plain_ru": plain["text"], "plain_tone": plain["tone"], "cause_code": p.get("cause_code")})
    return cell(value={"open": [p.get("problem_id") for p in open_], "mitigated": len(mitigated),
                      "closed_recent": len(closed_recent), "open_count": len(open_)},
               display_ru=text_ru, display_en=text_ru, metric_type="COUNT",
               state=(MEASURED_ZERO if not rows else MEASURED), as_of=store.get("generated_at"),
               canon=canon, fresh=freshness(None, None, "n/a"), unknown_ru="Реестр проблем ещё не запущен",
               # bare ``open``/``mitigated``/``closed``/``items`` — ``renderProblems`` composes its
               # chip row and per-problem lines from these RAW fields, never from ``value``
               # (Wave 2 round-2 review, 2026-10-06: chips printed blank).
               open=len(open_), mitigated=len(mitigated), closed=len(closed_recent), items=items)


def studio_self_heal(data_dir: Path, now: datetime, manifest: Optional[dict] = None) -> dict:
    canon = "data/self_heal_status.json"
    doc = _read_json(data_dir / "self_heal_status.json")
    if doc is None:
        return unknown(canon, "OPERATIONAL", "Самовосстановление не измерено")
    ts = _parse_ts(doc.get("ts"))
    slo_min, rule = _manifest_slo_minutes(manifest, "self_heal_status.json", 26 * 60)
    state, fr = _staleness(ts, now, slo_min, rule)
    failures = doc.get("failures") or []
    age = owner_language.age_ru(fr.get("age_min")) if ts else None
    text_ru = f"последний запуск {age or 'время неизвестно'} · провалов: {len(failures)}"
    unknown_ru = _stale_or_absent(state, fr.get("age_min"),
                                 "Самовосстановление устарело: последний отчёт {age} назад",
                                 "Самовосстановление не измерено")
    return cell(value={"healthy": doc.get("healthy"), "failures": failures}, display_ru=text_ru,
               display_en=text_ru, metric_type="OPERATIONAL", state=state, as_of=_iso(ts), canon=canon,
               fresh=fr, unknown_ru=unknown_ru)


def studio_releases(release_feed_section: Optional[dict], now: datetime) -> dict:
    canon = "git origin/main (mirror) + data/code_sync_status.json"
    if release_feed_section is None or release_feed_section.get("_meta", {}).get("state") == "NOT_MEASURED":
        return unknown(canon, "OPERATIONAL", "Неизвестно, что сейчас в проде")
    items = release_feed_section.get("items") or []
    today = [i for i in items if _parse_ts(i.get("at")) and (now - _parse_ts(i["at"])) < timedelta(hours=24)]
    in_prod_ok = all(i.get("release") in ("IN_PROD_TREE", "NOT_APPLICABLE") for i in items) if items else None
    text_ru = ("в проде то, что принято" if in_prod_ok else "есть неподтверждённые изменения") + f" · за сутки: {len(today)}"
    return cell(value={"today": len(today), "in_prod_ok": in_prod_ok}, display_ru=text_ru, display_en=text_ru,
               metric_type="OPERATIONAL", state=MEASURED, as_of=None, canon=canon,
               fresh=freshness(None, None, "n/a"), unknown_ru="Неизвестно, что сейчас в проде",
               # bare ``today``/``in_prod_ok`` — ``renderReleases`` reads these RAW (Wave 2 round-2
               # review, 2026-10-06: ``in_prod_ok`` was undefined, so the card always said "drift",
               # right today only by coincidence).
               today=len(today), in_prod_ok=in_prod_ok)


def studio_memory(repo: Path, mirror: Path) -> dict:
    canon = "architecture/memory_truth.json + data/memory/index.db"
    db = repo / "data" / "memory" / "index.db"
    truth_doc = _read_json(repo / "architecture" / "memory_truth.json")
    if not db.is_file():
        return unknown(canon, "OPERATIONAL", "Индекс памяти не прочитан")
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            adrs_indexed = set()
            for row in con.execute("SELECT DISTINCT path FROM chunks WHERE path LIKE '%ADR-%'"):
                for m in re.findall(r"ADR-(\d+)", row[0] or ""):
                    adrs_indexed.add(int(m))
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return unknown(canon, "OPERATIONAL", "Индекс памяти не прочитан")
    decisions_dir = Path(mirror) / "docs" / "decisions"
    newest_origin = 0
    if decisions_dir.is_dir():
        for p in decisions_dir.glob("ADR-*"):
            m = re.match(r"ADR-(\d+)", p.name)
            if m:
                newest_origin = max(newest_origin, int(m.group(1)))
    newest_indexed = max(adrs_indexed) if adrs_indexed else 0
    lag = max(0, newest_origin - newest_indexed) if newest_origin else None
    # Bare-field card (design §2.0's "two kinds of text" — ``renderMemory`` composes its own
    # sentence via ``cell.lag > 0 ? tf("studio.memory.lag", {n: cell.lag}) : t("studio.memory.ok")``
    # and never reads ``display_ru``). A pre-composed sentence here was NEVER read by the real
    # renderer — it only duplicated/contradicted the raw-field sentence when ``lag`` was missing
    # (Wave 2 round-2 review, 2026-10-06: ``cell.lag`` was undefined because it lived only inside
    # ``value``, so the card showed BOTH "индекс отстаёт на 30 решений" (from this now-removed
    # ``display_ru``) AND "индекс знает все решения" (the UI's own fallback for an undefined
    # ``lag``) on the SAME card).
    return cell(value={"lag": lag, "newest_indexed": newest_indexed, "newest_origin": newest_origin or None,
                      "truth_overrides": len((truth_doc or {}).get("overrides") or []) if truth_doc else None},
               display_ru=None, display_en=None, metric_type="OPERATIONAL",
               state=(MEASURED_ZERO if lag == 0 else MEASURED), as_of=None, canon=canon,
               fresh=freshness(None, None, "n/a"), unknown_ru="Индекс памяти не прочитан", lag=lag)


def studio_backups(data_dir: Path, now: datetime, manifest: Optional[dict] = None) -> dict:
    """design §0 C3 / §2.3 — three HONEST, SEPARATE facts. Never one green over three; never
    HEALTHY/OK when the offsite copy is actually on the same disk (the live C3 dishonesty)."""
    dro = _read_json(data_dir / "dr_offsite_status.json")
    res = _read_json(data_dir / "resilience_status.json")
    bdir = data_dir / "backups"
    arch = sorted(bdir.glob("spa_state_*.tar.gz"), key=lambda p: p.stat().st_mtime) if bdir.is_dir() else []
    slo_min, rule = _manifest_slo_minutes(manifest, "spa_state_*.tar.gz", 30 * 60)

    # The three rows are RAW (``age_ru``/``is_real_remote``/``drill_result``+``date``) —
    # ``renderBackupLocal``/``Off­Host``/``Recovery`` each compose their own sentence via
    # ``tf()``/a closed switch and never read a ``display_ru`` here.
    if not arch:
        local = unknown("data/backups/spa_state_*.tar.gz", "OPERATIONAL", "Бэкап не измерен")
    else:
        last_arch = datetime.fromtimestamp(arch[-1].stat().st_mtime, timezone.utc)
        state, fr = _staleness(last_arch, now, slo_min, rule)
        age_ru = _age_text(fr["age_min"])   # the UI template already says «… назад»
        unknown_ru = _stale_or_absent(state, fr.get("age_min"),
                                     "Локальный бэкап устарел: последняя копия {age} назад", "Бэкап не измерен")
        local = cell(value={"age_min": fr["age_min"]}, display_ru=None, display_en=None, metric_type="OPERATIONAL",
                    state=state, as_of=_iso(last_arch), canon="data/backups/spa_state_*.tar.gz", fresh=fr,
                    unknown_ru=unknown_ru, age_ru=age_ru, age_en=age_ru)

    if dro is None:
        off_host = unknown("data/dr_offsite_status.json", "OPERATIONAL", "Бэкап не измерен")
    else:
        is_real = dro.get("is_real_remote")
        ok = is_real is True and dro.get("verified")
        # NEVER green/healthy when the "offsite" copy is on the same disk (the live C3 defect) —
        # `is_real_remote` is carried RAW so the UI's own badge-colour rule (never green unless
        # `is_real_remote`) decides, not a pre-picked state here.
        off_host = cell(value=ok, display_ru=None, display_en=None, metric_type="OPERATIONAL",
                       state=(MEASURED if ok else MEASURED_ZERO), as_of=dro.get("last_offsite_ts"),
                       canon="data/dr_offsite_status.json", fresh=freshness(None, None, "n/a"),
                       unknown_ru="Бэкап не измерен", is_real_remote=bool(is_real))

    rd = (res or {}).get("restore_drill") if isinstance(res, dict) else None
    if not isinstance(rd, dict):
        recovery = unknown("data/resilience_status.json", "OPERATIONAL", "Бэкап не измерен")
    else:
        drill = ("NEVER_RUN" if rd.get("never_run") else "STALE" if rd.get("stale") else
                 "OK" if rd.get("all_ok") is True else "FAILED" if rd.get("all_ok") is False else None)
        recovery = cell(value=drill, display_ru=None, display_en=None, metric_type="OPERATIONAL",
                       state=(MEASURED if drill == "OK" else MEASURED_ZERO if drill == "NEVER_RUN" else
                             MEASURED if drill in ("STALE", "FAILED") else NOT_MEASURED),
                       as_of=rd.get("last_ts"), canon="data/resilience_status.json", fresh=freshness(None, None, "n/a"),
                       unknown_ru="Бэкап не измерен", drill_result=drill, date=rd.get("last_ts"))
    return {"local_backup": local, "off_host_backup": off_host, "recovery_tested": recovery}


def studio_machine(data_dir: Path, now: datetime, manifest: Optional[dict] = None) -> dict:
    """design §2.3 — the one Mac-health card: ``renderMachine`` reads ``cell.disk_free_gb`` RAW
    (no ``display_ru``, same bare-field convention as ``studio_backups``'s three rows). Not wired
    into ``studio_cards`` at all before this fix (Wave 2 round-2 review, 2026-10-06): the card
    always said "не измерено" regardless of the real disk state."""
    canon = "data/resource_health.json"
    doc = _read_json(data_dir / "resource_health.json")
    if doc is None:
        return unknown(canon, "OPERATIONAL", "Ресурсы не измерены")
    ts = _parse_ts(doc.get("generated_at"))
    slo_min, rule = _manifest_slo_minutes(manifest, "resource_health.json", 20.0)
    state, fr = _staleness(ts, now, slo_min, rule)
    free_gb = (doc.get("disk") or {}).get("free_gb")
    unknown_ru = _stale_or_absent(state, fr.get("age_min"),
                                 "Ресурсы устарели: отчёт записан {age} назад", "Ресурсы не измерены")
    return cell(value={"disk_free_gb": free_gb}, display_ru=None, display_en=None, metric_type="OPERATIONAL",
               state=state, as_of=_iso(ts), canon=canon, fresh=fr, unknown_ru=unknown_ru, disk_free_gb=free_gb)


def studio_decisions_summary(decisions_triage: dict) -> dict:
    """Design §2.3 — "counts as on Home": the SAME computation as ``tile_needs``, not a second
    one (``renderDecisionsSummary`` reads the raw ``own``/``undeclared``/``answered`` fields)."""
    return _decisions_counts_cell(decisions_triage, "nimbalyst-local/tracker (owner-decision cards)")


def studio_cards(*, cw: dict, roadmap: dict, board: Optional[dict], orphans: Optional[dict],
                 fleet: dict, push_state_section: Optional[dict], data_dir: Path, now: datetime,
                 release_feed_section: Optional[dict], repo: Path, mirror: Path, manifest: Optional[dict],
                 decisions_triage: dict, scopes: list[dict]) -> dict:
    # ``studio_backups()`` keeps its own ``local_backup``/``off_host_backup``/``recovery_tested``
    # names (the "three HONEST, SEPARATE facts" computation, independently tested by
    # test_backups_three_facts.py) — this is only the UI-facing re-projection into the names
    # ``renderBackups`` actually reads (``b.local``/``b.off_host``/``b.recovery``). Wave 2
    # round-2 review, 2026-10-06: exposing the computation's own names left all three rows
    # showing "не измерено" on the real tree, although local/off-host WERE measured.
    backups = studio_backups(data_dir, now, manifest)
    return {"claude_work": cw, "roadmap": studio_roadmap(roadmap), "tasks": studio_tasks(board, orphans),
           "fleet": fleet_cell(fleet), "incidents": studio_incidents(push_state_section, now),
           "problems": studio_problems(data_dir, now), "self_heal": studio_self_heal(data_dir, now, manifest),
           "releases": studio_releases(release_feed_section, now), "memory": studio_memory(repo, mirror),
           "backups": {"local": backups["local_backup"], "off_host": backups["off_host_backup"],
                      "recovery": backups["recovery_tested"]},
           "decisions_summary": studio_decisions_summary(decisions_triage),
           "machine": studio_machine(data_dir, now, manifest),
           "scopes": scopes}


# ── §2.4 EARN DEFI PRODUCT ───────────────────────────────────────────────────────────────────────
def product_public_release(mirror: Path) -> dict:
    """``renderPublicRelease`` reads ``measured_ru``/``published_ru`` RAW and composes the
    sentence itself via ``tf("product.release.value", …)`` — no ``display_ru`` here (§2.0's two
    kinds of text are not mixed on one card)."""
    canon = "landing/src/data/site_numbers.json"
    doc = _read_json(Path(mirror) / "landing" / "src" / "data" / "site_numbers.json")
    if doc is None:
        return unknown(canon, "TIMESTAMP", "Неизвестно, что опубликовано")
    measured, published, nxt = doc.get("measured_at"), doc.get("published_at"), doc.get("next_publication")
    return cell(value={"measured_at": measured, "published_at": published, "next_publication": nxt},
               display_ru=None, display_en=None, metric_type="TIMESTAMP", state=MEASURED,
               as_of=measured, canon=canon, fresh=freshness(None, None, "n/a"),
               unknown_ru="Неизвестно, что опубликовано",
               measured_ru=measured, measured_en=measured, published_ru=published, published_en=published)


def product_website_health(publication_scope: Optional[dict], site_doc: Optional[dict] = None) -> dict:
    return tile_product(publication_scope, site_doc)


def product_profiles(books: dict) -> dict:
    """``renderProfiles`` reads ``profiles[conservative|balanced|aggressive]`` as a CELL with the
    same raw ``rate_ru``/``dd_ru``/``accumulating_days`` shape as ``capital.defi.books`` — it IS
    that data, shown under the Продукт tab, not a second computation over the same canons."""
    canon = "package_status.public_view + landing/src/lib/tier_bands.json"
    if not books:
        return {k: unknown(canon, "REALIZED_PAPER", "Профиль не прочитан") for k in
               ("conservative", "balanced", "aggressive")}
    return dict(books)


#: label + metric_type per ``site_numbers.json`` headline key — the file itself carries no RU/EN
#: label (checked against the real tree 2026-10-06), so ``product_public_metrics`` supplies the
#: one small copy-deck a public number needs, same convention as ``STAGE_RU`` above.
_PUBLIC_METRIC_LABELS = {
    "apy": ("Доходность Conservative", "Conservative yield", "REALIZED_PAPER"),
    "drawdown": ("Просадка", "Drawdown", "OBSERVED"),
    "nav": ("NAV портфеля", "Portfolio NAV", "OBSERVED"),
    "evidenced_days": ("Дней трека", "Track days", "COUNT"),
    "gates": ("Гейты готовности", "Readiness gates", "COUNT"),
}


def product_public_metrics(mirror: Path) -> list[dict]:
    """``renderPublicMetrics`` reads ``truth.product.public_metrics`` as a plain ARRAY of rows
    (``Array.isArray(list)``) — this card is NOT a §2.0 cell (the fixture's own shape has no
    ``state``/``canon`` envelope around the list, only on each row). Returning a cell here (Wave 2
    round-2 review, 2026-10-06) made ``Array.isArray()`` false on real data with 5 measured public
    numbers, so the card always said "нет чисел". Absence is an EMPTY list, never a crash or a
    fabricated row (inv. #17) — ``renderPublicMetrics`` already shows "нет чисел" for ``[]``."""
    doc = _read_json(Path(mirror) / "landing" / "src" / "data" / "site_numbers.json")
    if doc is None:
        return []
    headline = doc.get("headline") or {}
    measured_at = doc.get("measured_at")
    rows: list[dict] = []
    for key, v in headline.items():
        if not isinstance(v, dict):
            continue
        label_ru, label_en, metric_type = _PUBLIC_METRIC_LABELS.get(key, (key, key, "OBSERVED"))
        if key == "gates":
            value_ru = value_en = f"{v.get('passed')}/{v.get('total')}"
        else:
            value_ru = value_en = f"{v.get('value')}{v.get('unit') or ''}"
        rows.append({
            "label_ru": label_ru, "label_en": label_en, "metric_type": metric_type, "state": MEASURED,
            "value_ru": value_ru, "value_en": value_en, "date_ru": measured_at, "date_en": measured_at,
            "as_of": measured_at, "canon": v.get("source") or "landing/src/data/site_numbers.json (headline)",
            "freshness": freshness(None, None, "declared:weekly_cadence"),
        })
    return rows


def product_truth_incidents(data_dir: Path, now: datetime) -> dict:
    canon = "data/problems.json (SITE_PUBLICATION_FAMILY)"
    if not (data_dir / "problems.json").is_file():
        return unknown(canon, "OPERATIONAL", "Не измерено")
    from spa_core.monitoring.problem_store import load_store
    store = load_store(data_dir)
    rows = [p for p in (store.get("problems") or {}).values()
            if isinstance(p, dict) and str(p.get("source", "")).startswith("site_") and p.get("status") == "OPEN"]
    return cell(value=rows, display_ru=f"открытых инцидентов правды продукта: {len(rows)}",
               display_en=f"open product-truth incidents: {len(rows)}", metric_type="OPERATIONAL",
               state=(MEASURED_ZERO if not rows else MEASURED), as_of=store.get("generated_at"), canon=canon,
               fresh=freshness(None, None, "n/a"), unknown_ru="Не измерено",
               # bare ``open`` — ``renderProductIncidents`` reuses ``studio.incidents.open``'s own
               # ``tf()`` template, which reads ``cell.open`` RAW (Wave 2 round-2 review).
               open=len(rows))


def product_backlog(cards: Optional[dict]) -> dict:
    canon = "nimbalyst-local/tracker (declared domain/tags)"
    if cards is None:
        return unknown(canon, "COUNT", "Бэклог не прочитан")
    domains = {"site", "landing", "product", "earn-defi"}
    rows = []
    for name, c in cards.items():
        fm = c.get("fm") or {}
        if fm.get("status") not in ("new", "backlog", "in-progress", "blocked"):
            continue
        tags = str(fm.get("domain", "")) + " " + str(fm.get("tags", ""))
        if any(d in tags for d in domains):
            rows.append(fm.get("title") or name)
    top_titles = [str(r) for r in rows[:5]]
    return cell(value=rows, display_ru=f"карточек в бэклоге продукта: {len(rows)}",
               display_en=f"product backlog cards: {len(rows)}", metric_type="COUNT",
               state=(MEASURED_ZERO if not rows else MEASURED), as_of=None, canon=canon,
               fresh=freshness(None, None, "n/a"), unknown_ru="Бэклог не прочитан",
               # bare ``top_titles_ru``/``top_titles_en`` — ``renderBacklog`` lists a few titles
               # under the composed count sentence (card titles carry no separate RU/EN text).
               top_titles_ru=top_titles, top_titles_en=top_titles)


def product_next_release(mirror: Path) -> dict:
    canon = "landing/src/data/site_numbers.json (next_publication)"
    doc = _read_json(Path(mirror) / "landing" / "src" / "data" / "site_numbers.json")
    if doc is None or not doc.get("next_publication"):
        return unknown(canon, "TIMESTAMP", "Дата следующей публикации не записана")
    nxt = doc["next_publication"]
    return cell(value={"next_publication": nxt}, display_ru=None, display_en=None, metric_type="TIMESTAMP",
               state=MEASURED, as_of=nxt, canon=canon, fresh=freshness(None, None, "n/a"),
               unknown_ru="Дата следующей публикации не записана",
               date_ru=nxt, date_en=nxt, gate_ru=None, gate_en=None)


def product_cards(*, mirror: Path, defi_books: dict, publication_scope: Optional[dict],
                  data_dir: Path, now: datetime, cards: Optional[dict], site_doc: Optional[dict] = None) -> dict:
    return {"public_release": product_public_release(mirror),
           "website_health": product_website_health(publication_scope, site_doc),
           "profiles": product_profiles(defi_books), "public_metrics": product_public_metrics(mirror),
           "truth_incidents": product_truth_incidents(data_dir, now), "backlog": product_backlog(cards),
           "next_release": product_next_release(mirror)}


# ── §2.6 Решения triage ─────────────────────────────────────────────────────────────────────────
def decisions_triage(cards: Optional[dict], prod_cards: Optional[dict], now: datetime,
                     decisions_v1: Optional[dict] = None) -> dict:
    """ADR-285/ADR-580 C5/C6 — declared ``subject:`` only, never guessed. Groups: owner subject,
    undeclared (agent triages), answered, accepted, prod-only (on the Mac, not yet on origin).

    ``decisions_v1`` is the EXISTING ``decision_item()``-built dict mission_control.py's own
    (v1, ADR-552) Decisions section already computes from the same cards (reason/requested_action/
    done_when/telegram_link/created_at, with ``safe_text`` already applied there) — re-used here,
    never recomputed, so the Решения tab's per-card detail (design §2.6) does not invent a second
    body-section parser. Omitting it degrades gracefully to rows carrying only id/title/subject."""
    if cards is None:
        return {"state": NOT_MEASURED, "counts": {}, "groups": {}}
    from spa_core.owner_queue import subject as subj
    v1_by_id: dict[str, dict] = {}
    for d in (decisions_v1 or {}).get("pending") or []:
        if isinstance(d, dict) and d.get("id"):
            v1_by_id[d["id"]] = d
    for d in (decisions_v1 or {}).get("recently_resolved") or []:
        if isinstance(d, dict) and d.get("id"):
            v1_by_id.setdefault(d["id"], d)

    def _na(v: Any) -> Optional[Any]:
        return None if v in (None, "UNKNOWN") else v

    owner_rows, undeclared_rows, answered_rows, accepted_rows = [], [], [], []
    for name, c in sorted(cards.items()):
        fm = c.get("fm") or {}
        t = fm.get("type") or ""
        is_owner = t == "owner-decision" or name.startswith(("owner-decision-", "own-"))
        status = fm.get("status")
        if not is_owner and status not in ("needs-owner", "owner-accepted"):
            continue
        s = subj.subject_of(fm)
        card_id = name[:-3] if name.endswith(".md") else name
        v1 = v1_by_id.get(card_id) or {}
        # Prefer v1's title: `mission_control.decision_item()` already ran it through
        # `safe_text()` (strips secrets/e-mails/long numbers, not just paths). The raw fm title
        # is a last-resort fallback for the (should-not-happen) case this card is missing from
        # `decisions_v1` — `_redact()` at least strips an absolute path from it, never the bare
        # frontmatter string (found reaching the model in test_no_secret_path_or_email_reaches_
        # the_model, 2026-10-06: a bare title with "/Users/…" had no v1 counterpart in the scene).
        title = v1.get("title") or _redact(fm.get("title")) or name
        age_days = None
        created_ts = _parse_ts(_na(v1.get("created_at")))
        if created_ts:
            age_days = (now - created_ts).days
        row = {"id": card_id, "title_ru": title, "title_en": title,
              "reason_ru": _na(v1.get("reason")), "reason_en": _na(v1.get("reason")),
              "action_ru": _na(v1.get("requested_action")), "action_en": _na(v1.get("requested_action")),
              "done_when_ru": _na(v1.get("done_when")), "done_when_en": _na(v1.get("done_when")),
              "age_days": age_days, "subject_key": (s if s != subj.UNKNOWN else None),
              "telegram_link": v1.get("telegram_link"),
              # legacy fields some earlier callers of this function still read:
              "title": title, "subject": s, "status": status}
        if status == "owner-accepted":
            accepted_rows.append(row)
        elif status == "needs-owner":
            (owner_rows if s != subj.UNKNOWN else undeclared_rows).append(row)
    for d in (decisions_v1 or {}).get("recently_resolved") or []:
        if not isinstance(d, dict):
            continue
        title = d.get("title") or d.get("id")
        answered_rows.append({"id": d.get("id"), "title_ru": title, "title_en": title,
                              "owner_answer_ru": _na(d.get("owner_answer")), "owner_answer_en": _na(d.get("owner_answer")),
                              "answered_at": _na(d.get("answered_at"))})
    prod_only = []
    if prod_cards is not None and cards is not None:
        for pname in sorted(set(prod_cards) - set(cards)):
            pfm = (prod_cards.get(pname) or {}).get("fm") or {}
            pid = pname[:-3] if pname.endswith(".md") else pname
            ptitle = _redact(pfm.get("title")) or pid
            prod_only.append({"id": pid, "title_ru": ptitle, "title_en": ptitle})
    return {"state": MEASURED, "counts": {"owner": len(owner_rows), "undeclared": len(undeclared_rows),
                                          "answered": len(answered_rows), "accepted": len(accepted_rows),
                                          "prod_only": len(prod_only)},
           "groups": {"owner": owner_rows, "undeclared": undeclared_rows, "answered": answered_rows,
                     "accepted": accepted_rows, "prod_only": prod_only},
           "unknown_ru": "Очередь решений не измерена — трекер не прочитан",
           "unknown_en": "Decision queue not measured — tracker unreadable"}


# ── top-level build() ────────────────────────────────────────────────────────────────────────────
@dataclass
class TruthInputs:
    data: Path
    mirror: Path
    repo: Path
    now: datetime
    measure_host: bool = True
    rep: dict = field(default_factory=dict)
    capital: dict = field(default_factory=dict)
    cards: Optional[dict] = None
    prod_cards: Optional[dict] = None
    roadmap: dict = field(default_factory=dict)
    board: Optional[dict] = None
    orphans: Optional[dict] = None
    manifest: Optional[dict] = None
    roles: Optional[dict] = None
    launchctl_map: Optional[dict] = None
    lineage_fn: Optional[Callable] = None
    log_rows: Optional[list] = None
    log_bad_lines: int = 0
    scopes: list = field(default_factory=list)
    release_feed: Optional[dict] = None
    push_state_section: Optional[dict] = None
    old_owner_items: list = field(default_factory=list)
    decisions_v1: Optional[dict] = None


def build(inp: TruthInputs) -> dict:
    now = inp.now
    data = Path(inp.data)
    cw = claude_work(inp.log_rows, inp.cards, inp.roadmap, inp.lineage_fn, None, now,
                     inp.rep.get("claude_sessions"), measure_host=inp.measure_host,
                     bad_lines=inp.log_bad_lines)
    # problems are read once, directly (needed both by claude_work's blocker lookup — recomputed
    # below with the SAME call the studio card uses — and by the home attention line).
    problems_cell = studio_problems(data, now)
    triage = decisions_triage(inp.cards, inp.prod_cards, now, inp.decisions_v1)

    equity_doc = _read_json(data / "equity_curve_daily.json")
    hy_doc = _read_json(data / "hy_paper_trading.json")
    lp_doc = _read_json(data / "lp_paper_trading.json")
    site_doc = _read_json(data / "site_freshness_report.json")
    current_positions = _read_json(data / "current_positions.json")

    scopes_safe = [_sanitize_scope(s) for s in (inp.scopes or [])]
    scopes_by_name = {s.get("scope"): s for s in scopes_safe}
    fleet = typed_fleet(inp.manifest, inp.launchctl_map, _read_json(data / "agent_health.json"), inp.roles,
                       announced=len(cw.get("active") or []), unannounced=cw.get("undeclared"))

    capital = inp.capital or {}
    pk_section = capital.get("packages")
    # ONE `tile_yield()` call (design C1: "no second formula") — Главная's "yield" tile AND
    # capital.defi.books.conservative (rate_ru/dd_ru/evidenced_days) both read this SAME cell.
    yield_cell = tile_yield(equity_doc, now)
    cap = capital_cards(packages_section=pk_section, hy_doc=hy_doc, lp_doc=lp_doc, data_dir=data,
                       mirror=Path(inp.mirror), research_universe=capital.get("research_universe"),
                       investment_cio=capital.get("investment_cio"), live_readiness=capital.get("live_readiness"),
                       investment_scope=scopes_by_name.get("INVESTMENT_ENGINE_READINESS"),
                       current_positions=current_positions, yield_cell=yield_cell, now=now)

    home_doc = home(fleet=fleet, yield_cell=yield_cell, defi_books=cap["defi"]["books"],
                   publication_scope=scopes_by_name.get("PUBLICATION_HEALTH"), site_doc=site_doc,
                   cw=cw, decisions_triage=triage, real_capital=capital.get("real_capital"),
                   kill_switch_active=inp.rep.get("kill_switch_active"), derisk_active=inp.rep.get("derisk_active"),
                   old_owner_items=inp.old_owner_items,
                   critical_problems=len([p for p in (problems_cell.get("value") or {}).get("open", [])]),
                   same_host_backup=(_read_json(data / "dr_offsite_status.json") or {}).get("is_real_remote") is False,
                   now=now)

    studio = studio_cards(cw=cw, roadmap=inp.roadmap, board=inp.board, orphans=inp.orphans, fleet=fleet,
                          push_state_section=inp.push_state_section, data_dir=data, now=now,
                          release_feed_section=inp.release_feed, repo=Path(inp.repo), mirror=Path(inp.mirror),
                          manifest=inp.manifest, decisions_triage=triage,
                          scopes=scopes_safe)
    # studio_problems is recomputed once more above already memoised as problems_cell; keep ONE call's
    # result consistent with what the card shows.
    studio["problems"] = problems_cell

    product = product_cards(mirror=Path(inp.mirror), defi_books=cap["defi"]["books"],
                            publication_scope=scopes_by_name.get("PUBLICATION_HEALTH"), data_dir=data, now=now,
                            cards=inp.cards, site_doc=site_doc)

    return {"schema": SCHEMA, "computed_at": _iso(now), "home": home_doc, "capital": cap, "studio": studio,
           "product": product, "decisions": triage}
