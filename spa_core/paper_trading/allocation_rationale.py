"""SHADOW writer for the yield-improvement trigger (ADR-060, phase 0).

Runs the trigger's economics every cycle and records what it WOULD have done in
``data/allocation_rationale.json``. It never returns a target, never mutates a
position, and never influences the trade decision — arming it is a separate,
owner-gated step. The point of the shadow phase is that the owner can read a
fortnight of real verdicts before any capital depends on them.

Also discharges the ADR-055 obligation that idle capital be explained every cycle
(Y2): the ``cash`` section is a deterministic attribution — buffer / deployable-
but-idle / aggregate caps / per-protocol caps / missing live evidence — with USD
and forgone bps per component. ``UNEXPLAINED_CASH`` is reserved for room that was
fundable under every cap with live evidence and still left idle; a component whose
inputs are missing is ``UNCHECKED`` (``attribution_incomplete``), never zero.

Fail-open by construction: any error here is logged and swallowed. A reporting
layer must never be able to break the cycle that feeds the track.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.allocator.rebalance_economics import (
    TriggerParams,
    attribute_cash,
    below_median_cap_violations,
    evaluate,
)
from spa_core.utils.atomic import atomic_save, atomic_save_text

log = logging.getLogger("spa.paper_trading.allocation_rationale")

RATIONALE_FILENAME = "allocation_rationale.json"
SHADOW_VERSION = "shadow-v1"

# ── Y3 (ADR-060 tooling): append-only verdict history ─────────────────────────
# ``allocation_rationale.json`` is OVERWRITTEN every cycle, so before Y3 the
# shadow's track record lived nowhere (2026-08-05: only 2 verdicts were
# recoverable, from cycle logs). The arming decision needs "what did the shadow
# say vs what actually happened", which needs every day's verdict kept.
# One JSONL line per cycle_date; a re-run of the SAME date replaces that date's
# line (idempotent), lines for other dates are preserved BYTE-FOR-BYTE —
# including unparseable ones (we never destroy history we cannot read).
HISTORY_FILENAME = "allocation_rationale_history.jsonl"
HISTORY_SCHEMA = "shadow-hist-v2"
HISTORY_MAX_LINES = 1000  # ~3 years of daily cycles; guards against unbounded growth


def build_history_record(
    doc: dict,
    *,
    apy_pct: Dict[str, float],
    apy_sources: Dict[str, str],
    current_positions: Dict[str, float],
    target_positions: Dict[str, float],
    capital_usd: float,
) -> dict:
    """One compact line of shadow track-record: enough to replay the verdict later.

    Keeps BOTH books (current and proposed), the day's evidenced APYs for every
    protocol either book touches, and the verdict economics — the exact inputs
    ``shadow_trigger_eval`` needs for the counterfactual. Deterministic; never
    raises on missing keys (a hole becomes ``None``, which the evaluator treats
    as UNCHECKED, not zero).

    CIO oversight phase F (Investment Decision Object,
    docs/ideas/2026-08-29-cio-oversight-layer.md): every field below already
    existed elsewhere in ``doc``/``dec`` before this phase — it only makes them
    part of the durable record instead of the overwritten-every-cycle
    ``allocation_rationale.json``. ``decision_id`` is a deterministic label
    (``adr060-shadow-<cycle_date>``), not a new identity system.
    ``policy_version``/``mode`` are the ADR-060 §3 mandate identity phase E
    already stamped on ``doc["params"]``, carried into the append-only ledger
    so a verdict from 40 cycles ago still names which version decided it.
    ``legs``/``gates`` are the move phase E's ``evaluate()`` already computed
    and scored — the closest honest reading of "рассмотренные и отклонённые
    альтернативы" the idea note calls for, since the trigger evaluates ONE
    proposed reallocation per cycle rather than a multi-candidate slate
    (`gates` records exactly which criterion accepted or rejected it).
    """
    dec = doc.get("decision_shadow") or {}
    params = doc.get("params") or {}
    cycle_date = doc.get("cycle_date")
    universe = sorted(set(current_positions or {}) | set(target_positions or {}))
    evidenced = {p for p, s in (apy_sources or {}).items() if s == "live"}
    return {
        "schema": HISTORY_SCHEMA,
        "decision_id": f"adr060-shadow-{cycle_date}" if cycle_date else None,
        "cycle_date": cycle_date,
        "generated_at": doc.get("generated_at"),
        "policy_version": params.get("policy_version"),
        "mode": params.get("mode"),
        "verdict": dec.get("decision"),
        "reasons": list(dec.get("reasons") or []),
        "legs": list(dec.get("legs") or []),
        "gates": dict(dec.get("gates") or {}),
        "capital_usd": capital_usd,
        "current_positions": {p: round(float(v), 2)
                              for p, v in (current_positions or {}).items()},
        "target_positions": {p: round(float(v), 2)
                             for p, v in (target_positions or {}).items()},
        # Evidenced-only by design: the counterfactual must never be priced on a
        # literal (the same rule the trigger itself lives under, ADR-061/063).
        "apy_evidenced_pct": {p: float(apy_pct[p]) for p in universe
                              if p in evidenced and (apy_pct or {}).get(p) is not None},
        "apy_unevidenced": sorted(p for p in universe if p not in evidenced),
        "book_apy_pp": dec.get("apy_now_pp"),
        "target_apy_pp": dec.get("apy_opt_pp"),
        "gain_pp": dec.get("gain_pp"),
        "required_gain_pp": dec.get("required_gain_pp"),
        "cost_usd": dec.get("cost_usd"),
        "payback_days": dec.get("payback_days"),
        "turnover_usd": dec.get("turnover_usd"),
        "turnover_frac": dec.get("turnover_frac"),
        "warnings_count": len(dec.get("warnings") or []),
    }


def append_rationale_history(record: dict, data_dir: Path) -> int:
    """Append *record* to the JSONL accumulator; idempotent by ``cycle_date``.

    - Same-date line is REPLACED (latest run of the day wins) — a manual re-run
      never duplicates a day and never double-counts in the evaluator.
    - Other lines are kept verbatim, unparseable lines included: the accumulator
      may drop nothing it did not write this call.
    - Atomic via tmp+``os.replace`` (invariant 5); capped at HISTORY_MAX_LINES
      (oldest lines fall off first).

    Returns the number of lines now in the file.
    """
    path = Path(data_dir) / HISTORY_FILENAME
    date = record.get("cycle_date")
    kept: List[str] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                kept.append(raw)  # unreadable ≠ deletable
                continue
            if isinstance(obj, dict) and date is not None \
                    and obj.get("cycle_date") == date:
                continue  # replaced by this call's record
            kept.append(raw)
    kept.append(json.dumps(record, sort_keys=True, default=str))
    kept = kept[-HISTORY_MAX_LINES:]
    atomic_save_text("\n".join(kept) + "\n", str(path))
    return len(kept)


def _resolve_tier_caps(protocols) -> Dict[str, float]:
    """Per-protocol concentration cap from RiskConfig via the canonical tier map.

    Without these the below-median rule is INERT — it can only flag "funded above
    half its cap" if it knows the cap. Values are read from RiskConfig (T1 40 % /
    T2+T3 20 %), never hardcoded here, so this can never drift from policy.
    """
    caps: Dict[str, float] = {}
    try:
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
    except Exception as exc:  # noqa: BLE001
        log.warning("ADR-060 shadow: RiskConfig unavailable (%s) — below-median rule inert", exc)
        return caps
    try:
        from spa_core.adapters.tier_map import tier_of
    except Exception as exc:  # noqa: BLE001
        log.warning("ADR-060 shadow: tier_map unavailable (%s)", exc)
        return caps
    for proto in protocols or []:
        try:
            tier = str(tier_of(proto) or "T2").upper()
        except Exception:  # noqa: BLE001 — one bad lookup never breaks the report
            tier = "T2"
        caps[proto] = float(
            cfg.max_concentration_t1 if tier == "T1" else cfg.max_concentration_t2
        )
    return caps


def _resolve_attribution_policy(protocols) -> dict:
    """Everything the cash attribution needs from RiskConfig + the canonical tier map.

    Read-only: values are RiskPolicy v1.0's own numbers, never redefined here.
    Fail-CLOSED: an unresolvable source yields ``None`` fields, which
    :func:`attribute_cash` reports as UNCHECKED — never a silent zero.
    """
    out: dict = {"tier_caps": None, "tiers": None, "t2_total_cap": None,
                 "t3_total_cap": None, "min_apy_pct": None, "min_tvl_usd": None}
    try:
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
    except Exception as exc:  # noqa: BLE001
        log.warning("Y2 attribution: RiskConfig unavailable (%s) — caps UNCHECKED", exc)
        return out
    try:
        from spa_core.adapters.tier_map import tier_of
    except Exception as exc:  # noqa: BLE001
        log.warning("Y2 attribution: tier_map unavailable (%s) — tiers UNCHECKED", exc)
        return out
    tiers: Dict[str, Optional[str]] = {}
    caps: Dict[str, float] = {}
    for proto in protocols or []:
        try:
            tier = tier_of(proto)
        except Exception:  # noqa: BLE001 — one bad lookup never breaks the report
            tier = None
        tiers[proto] = str(tier).upper() if tier else None
        if tiers[proto]:
            caps[proto] = float(
                cfg.max_concentration_t1 if tiers[proto] == "T1"
                else cfg.max_concentration_t2
            )
    out.update({
        "tier_caps": caps,
        "tiers": tiers,
        "t2_total_cap": float(cfg.max_total_t2_allocation),
        "t3_total_cap": float(getattr(cfg, "max_total_t3_allocation", 0.15)),
        "min_apy_pct": float(cfg.min_apy_for_new_position),
        # MP-011 TVL floor — RiskPolicy's own number, the same one the allocator
        # filters on. Absent attribute ⇒ stays None ⇒ attribution says UNCHECKED
        # rather than inventing a literal (a third copy of the rule).
        "min_tvl_usd": (float(cfg.min_tvl_usd)
                        if getattr(cfg, "min_tvl_usd", None) is not None else None),
    })
    return out


def _parse_ts(value: object) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _history_from_trades(trades: List[dict], now: datetime) -> dict:
    """Derive the anti-churn history the trigger needs from ``trades.json``.

    Returns ``days_since_last_act`` / ``last_move_legs`` / ``turnover_last_week_usd``.
    Unknown values stay ``None`` — the trigger then treats that gate as unconstrained,
    which is the honest reading in SHADOW (we are measuring, not restraining).
    """
    out: dict = {"days_since_last_act": None, "days_since_last_move": None,
                 "last_move_legs": None, "turnover_last_week_usd": 0.0}
    rebalances = [t for t in (trades or []) if isinstance(t, dict)
                  and t.get("type") == "rebalance"]
    if not rebalances:
        return out

    week_ago = now - timedelta(days=7)
    turnover = 0.0
    for t in rebalances:
        ts = _parse_ts(t.get("ts"))
        if ts is not None and ts >= week_ago:
            turnover += float(t.get("delta_abs") or 0.0)
    out["turnover_last_week_usd"] = round(turnover, 2)

    last = rebalances[-1]
    ts = _parse_ts(last.get("ts"))
    if ts is not None:
        age_days = (now - ts).total_seconds() / 86400.0
        out["days_since_last_act"] = round(age_days, 4)
        out["days_since_last_move"] = round(age_days, 4)
    frm = last.get("from_allocation") or {}
    to = last.get("to_allocation") or {}
    if isinstance(frm, dict) and isinstance(to, dict):
        out["last_move_legs"] = {
            p: round(float(to.get(p, 0.0) or 0.0) - float(frm.get(p, 0.0) or 0.0), 2)
            for p in set(frm) | set(to)
        }
    return out


def _position_ages(trades: List[dict], positions: Dict[str, float],
                   now: datetime) -> Dict[str, float]:
    """Days since each held protocol was last INCREASED (its entry, for min-hold)."""
    ages: Dict[str, float] = {}
    for t in reversed([t for t in (trades or []) if isinstance(t, dict)
                       and t.get("type") == "rebalance"]):
        ts = _parse_ts(t.get("ts"))
        if ts is None:
            continue
        frm, to = t.get("from_allocation") or {}, t.get("to_allocation") or {}
        if not isinstance(frm, dict) or not isinstance(to, dict):
            continue
        for proto in positions:
            if proto in ages:
                continue
            if float(to.get(proto, 0.0) or 0.0) > float(frm.get(proto, 0.0) or 0.0):
                ages[proto] = round((now - ts).total_seconds() / 86400.0, 4)
    return ages


def write_shadow_rationale(
    *,
    data_dir: Path,
    current_positions: Dict[str, float],
    target_positions: Dict[str, float],
    apy_pct: Dict[str, float],
    apy_sources: Dict[str, str],
    tvl_sources: Optional[Dict[str, str]] = None,
    tvl_usd: Optional[Dict[str, float]] = None,
    capital_usd: float,
    cycle_date: str,
    run_ts: str,
    tier_caps: Optional[Dict[str, float]] = None,
    cash_binders: Optional[List[dict]] = None,
    min_cash_frac: float = 0.05,
    trades: Optional[List[dict]] = None,
    now: Optional[datetime] = None,
    write: bool = True,
    params: Optional[TriggerParams] = None,
    blocked_protocols: Optional[Dict[str, str]] = None,
    policy_refusals: Optional[List[dict]] = None,
) -> dict:
    """Compute the shadow verdict and (optionally) persist it. Never raises."""
    try:
        now = now or datetime.now(timezone.utc)
        p = params or TriggerParams.for_mode()

        # Evidence comes from the allocator's own provenance, which ADR-061/063 made
        # truthful: "live" now means observed, not "a literal we dressed up".
        evidenced = {proto for proto, src in (apy_sources or {}).items() if src == "live"}

        chains: Dict[str, str] = {}
        try:
            reg = json.loads(
                (Path(data_dir) / "adapter_registry.json").read_text(encoding="utf-8"))
            for name, entry in (reg.get("adapters", {}) or {}).items():
                if isinstance(entry, dict) and entry.get("chain"):
                    chains[str(name)] = str(entry["chain"]).strip().lower()
        except Exception as exc:  # noqa: BLE001 — cost model degrades, never breaks
            log.warning("ADR-060 shadow: chain map unavailable (%s)", exc)

        # TVL provenance: a target pool that cleared the floor on a literal makes the
        # recommendation unsound.
        #
        # Source of truth is the ALLOCATOR's own ``tvl_sources`` (ADR-053 allocator
        # side): "live" only when the orchestrator record declares the TVL
        # feed-observed; registry $50M / fallback_tvl_usd literals are "static".
        # Deriving it here from the raw snapshot instead would create a second,
        # competing definition of the same thing — the drift this project keeps
        # paying for. The snapshot is used only as a fallback when the allocator
        # did not supply the map.
        # ``tvl_known`` distinguishes "we looked and it is static" from "we could
        # not look at all" — the attribution treats the latter as UNCHECKED
        # (fail-closed), never as an empty set that would silently explain cash.
        tvl_evidenced = set()
        tvl_known = False
        if tvl_sources:
            tvl_evidenced = {p_ for p_, src in tvl_sources.items() if src == "live"}
            tvl_known = True
        else:
            try:
                orch = json.loads((Path(data_dir) / "adapter_orchestrator_status.json")
                                  .read_text(encoding="utf-8"))
                for a in orch.get("adapters", []) or []:
                    # ТО ЖЕ определение, что у аллокатора (ADR-053): наблюдением
                    # считается ОБЪЯВЛЕННЫЙ живой провенанс, а не наличие числа.
                    # Раньше здесь засчитывался любой непустой `tvl_usd` — а 11
                    # адаптеров отдают захардкоженный литерал `TVL_USD`. Ветка
                    # включается только при пустой карте провенанса, поэтому дефект
                    # СПАЛ: он проснулся бы в тот день, когда данных меньше всего,
                    # то есть когда осторожность нужнее всего.
                    # Правило: «live» никогда не ставится на константу.
                    if (isinstance(a, dict) and a.get("protocol")
                            and a.get("tvl_usd") is not None
                            and a.get("tvl_source") == "live"):
                        tvl_evidenced.add(str(a["protocol"]))
                tvl_known = True
            except Exception as exc:  # noqa: BLE001
                log.warning("ADR-060 shadow: TVL provenance unavailable (%s)", exc)

        # TVL MAGNITUDE (карточка 07.08). Провенанс говорит «наблюдали», порог
        # спрашивает «сколько» — это два разных вопроса, и до 08.08 атрибуция
        # задавала только первый. Источник тот же, что у аллокатора: его
        # собственная карта фидов. Снимок читается лишь как запасной вариант и
        # только когда аллокатор карту не дал — иначе это было бы второе
        # определение (ровно тот дрейф, от которого предостерегает комментарий выше).
        tvl_magnitudes: Optional[Dict[str, float]] = None
        if tvl_usd is not None:   # пустая-но-данная карта — ответ, а не молчание
            tvl_magnitudes = {str(k): v for k, v in tvl_usd.items()}
        else:
            try:
                orch = json.loads((Path(data_dir) / "adapter_orchestrator_status.json")
                                  .read_text(encoding="utf-8"))
                tvl_magnitudes = {str(a["protocol"]): a.get("tvl_usd")
                                  for a in (orch.get("adapters") or [])
                                  if isinstance(a, dict) and a.get("protocol")}
            except Exception as exc:  # noqa: BLE001 — None ⇒ UNCHECKED, not a guess
                log.warning("ADR-055 attribution: TVL magnitudes unavailable (%s)", exc)

        hist = _history_from_trades(trades or [], now)
        ages = _position_ages(trades or [], current_positions or {}, now)

        decision = evaluate(
            current_positions=current_positions or {},
            target_positions=target_positions or {},
            apy_pct=apy_pct or {},
            evidenced=evidenced,
            chains=chains,
            capital_usd=capital_usd,
            params=p,
            days_since_last_act=hist["days_since_last_act"],
            position_age_days=ages,
            turnover_last_week_usd=hist["turnover_last_week_usd"],
            last_move_legs=hist["last_move_legs"],
            days_since_last_move=hist["days_since_last_move"],
            tvl_evidenced=tvl_evidenced or None,
        )

        # ── Y2 (ADR-055): deterministic attribution of every idle dollar ──
        # The universe the attribution reasons over = everything the allocator
        # saw (its APY provenance map) + the held book + what it refused to fund.
        _universe = sorted(set(apy_sources or {})
                           | set(current_positions or {})
                           | set(blocked_protocols or {}))
        _pol = _resolve_attribution_policy(_universe)
        cash = attribute_cash(
            positions=current_positions or {},
            capital_usd=capital_usd,
            min_cash_frac=min_cash_frac,
            apy_pct=apy_pct or {},
            apy_sources=dict(apy_sources) if apy_sources is not None else None,
            tvl_live=(tvl_evidenced if tvl_known else None),
            tier_caps=_pol["tier_caps"],
            tiers=_pol["tiers"],
            t2_total_cap=_pol["t2_total_cap"],
            t3_total_cap=_pol["t3_total_cap"],
            min_apy_pct=_pol["min_apy_pct"],
            # MP-011: размер TVL и порог RiskPolicy — та же проверка, что у
            # аллокатора (spa_core/risk/tvl_floor.py). Без них пул ниже порога
            # числился «пригодным сегодня» и его комнату вменяли аллокатору.
            tvl_usd=tvl_magnitudes,
            min_tvl_usd=_pol["min_tvl_usd"],
            blocked=blocked_protocols,
            external_binders=cash_binders,
            # ADR-053/ADR-055: what the RiskPolicy gate removed from the target
            # AFTER the allocator built it. Provenance for the idle cash — the
            # reason existed in the audit trail all along, it just never reached
            # the artifact that claimed the cash had none.
            policy_refusals=policy_refusals,
        )
        # Caps resolved here when the caller did not supply them — otherwise the
        # below-median rule silently reports nothing and looks compliant.
        _caps = tier_caps or _resolve_tier_caps(list((current_positions or {}).keys()))
        below_median = below_median_cap_violations(
            positions=current_positions or {}, apy_pct=apy_pct or {},
            tier_caps=_caps, capital_usd=capital_usd,
            evidenced=evidenced, factor=p.below_median_cap_factor)

        # ADR-055 запрещает МАКСИТЬ концентрацию на протоколе с доходностью ниже
        # медианы. Это утверждение о ходе, который делается, а не о книге, из
        # которой уходят. Спрошенное только про `current_positions`, правило
        # структурно не видит собственного предмета: 2026-08-30 в книге не было
        # aave_v3 вовсе, проверка честно вернула [], и тот же цикл открыл в нём
        # $22 105 (22.1 % капитала) под 3.26 % при медиане 4.93 %. Аудитор
        # сообщил ECON-10 наутро, когда позиция уже стояла.
        # Потолки — по ОБЪЕДИНЕНИЮ: у протокола, которого в книге ещё нет,
        # потолка бы не нашлось, и правило сработало бы с нулевой границей,
        # то есть по неверной причине.
        # Здесь тоже advisory: ход не останавливается, цель лишь СПРОШЕНА.
        _caps_target = tier_caps or _resolve_tier_caps(
            sorted(set(current_positions or {}) | set(target_positions or {})))
        below_median_target = below_median_cap_violations(
            positions=target_positions or {}, apy_pct=apy_pct or {},
            tier_caps=_caps_target, capital_usd=capital_usd,
            evidenced=evidenced, factor=p.below_median_cap_factor)
        _introduced = sorted(
            {r.get("protocol") for r in below_median_target}
            - {r.get("protocol") for r in below_median})
        if _introduced:
            log.warning(
                "ADR-055: ход СОЗДАЁТ концентрацию ниже медианы — %s "
                "(правило advisory, ход не остановлен)", ", ".join(_introduced))

        doc = {
            "generated_at": run_ts,
            "cycle_date": cycle_date,
            "mode": "SHADOW",
            "version": SHADOW_VERSION,
            "note": (
                "ADR-060 phase 0. Verdict is ADVISORY: no position was changed by it. "
                "Arming is a separate owner-gated step."
            ),
            "capital_usd": capital_usd,
            "decision_shadow": decision.to_dict(),
            "cash": cash,
            "below_median_cap": below_median,
            # Книга ДО хода / книга, которую ход СОЗДАЁТ / что появилось именно
            # из-за хода. Три разных вопроса — три разных поля, иначе «правило
            # молчит» неотличимо от «правило смотрело не туда» (ADR-055).
            "below_median_cap_target": below_median_target,
            "below_median_cap_introduced": _introduced,
            "history": {**hist, "position_age_days": ages},
            "params": {
                "min_gain_pp": p.min_gain_pp,
                "max_payback_days": p.max_payback_days,
                "min_hold_days": p.min_hold_days,
                "act_cooldown_days": p.act_cooldown_days,
                "max_turnover_per_move": p.max_turnover_per_move,
                "max_turnover_per_week": p.max_turnover_per_week,
                "min_leg_frac": p.min_leg_frac,
                "reversal_window_days": p.reversal_window_days,
                "reversal_escalation": p.reversal_escalation,
                "below_median_cap_factor": p.below_median_cap_factor,
                # CIO oversight phase E (Investment Policy Objective Contract):
                # names+versions the ADR-060 §3 column this cycle ran under, so
                # every recorded verdict is traceable to an accepted mandate
                # version instead of a bare, unattributed number set.
                "policy_version": p.version,
                "policy_version_date": p.version_date,
                "mode": p.mode,
            },
        }

        # ── advisor_notes (own-27 поток 1): 13 переселённых оптимизаторов ──
        # СТРОГО ADVISORY: рекомендации никогда не гейтят исполнение и не
        # двигают капитал (инвариант ADR-055). Отказ советников деградирует в
        # error-заметку — rationale и цикл продолжаются нетронутыми.
        try:
            from spa_core.analytics.allocator_advisors import run_advisors
            doc["advisor_notes"] = {
                "note": ("ADVISORY ONLY: recommendations never gate execution "
                         "and never move capital."),
                "recommendations": run_advisors(
                    {
                        "positions": dict(current_positions or {}),
                        "capital_usd": capital_usd,
                        "apy_pct": dict(apy_pct or {}),
                    },
                    Path(data_dir),
                ),
            }
        except Exception as adv_exc:  # noqa: BLE001 — советники не ломают rationale
            log.warning("advisor_notes failed (%s) — rationale continues", adv_exc)
            doc["advisor_notes"] = {"error": type(adv_exc).__name__,
                                    "recommendations": []}

        if write:
            atomic_save(doc, str(Path(data_dir) / RATIONALE_FILENAME))
            # Y3: the per-cycle file is overwritten — the accumulator is the
            # ONLY durable record of the shadow's verdicts. Its failure must not
            # cost us the rationale itself (already saved above), hence own guard.
            try:
                append_rationale_history(
                    build_history_record(
                        doc,
                        apy_pct=apy_pct or {},
                        apy_sources=apy_sources or {},
                        current_positions=current_positions or {},
                        target_positions=target_positions or {},
                        capital_usd=capital_usd,
                    ),
                    Path(data_dir),
                )
            except Exception as hist_exc:  # noqa: BLE001 — reporting never breaks the cycle
                log.warning("Y3 history append failed (%s) — rationale intact", hist_exc)
        log.info(
            "ADR-060 SHADOW: %s | gain %.3fpp (need %.3f) | cost $%.2f | payback %s | cash %s",
            decision.decision, decision.gain_pp, decision.required_gain_pp,
            decision.cost_usd, decision.payback_days, cash.get("status"),
        )
        return doc
    except Exception as exc:  # noqa: BLE001 — a reporting layer never breaks the cycle
        log.warning("ADR-060 shadow rationale failed (%s) — cycle continues", exc)
        return {"error": type(exc).__name__, "mode": "SHADOW"}
