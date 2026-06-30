"""
spa_core/dfb/alerts.py — WS-2.3 (Month-2 Lane-B): ALERTS on the desk's own kill signals.

DeBank tells you what changed; DFB tells you when a pool you watch just became one the desk would
REFUSE. The alert engine compares TODAY's overlay row against the PRIOR captured history snapshot
(the scarce refusal-state series from history.py) and emits deterministic, edge-triggered alerts:

  • REFUSAL_FLIP        — the KILLER: a pool's refusal verdict crossed SAFE/WATCH/UNKNOWN → REFUSE
                          (the desk would now refuse a pool it previously held). This is the single
                          most important signal; it can NEVER be missed (red-team asserts it).
  • APY_COLLAPSE        — apy_total dropped by more than APY_COLLAPSE_FRAC of yesterday's level.
  • TVL_DRAIN           — tvl_usd dropped by more than TVL_DRAIN_FRAC of yesterday's level.
  • PEG_IL_SPIKE        — a structural-haircut spike (the engine's structural risk component jumped),
                          OR the engine's evaluate_hold fires a peg/oracle/stable kill on the held
                          position (UNDERLYING_DEPEG / STABLE_DEPEG / ORACLE_STALE).
  • EXIT_LIQUIDITY_DROP — the $1M exit ticket flipped from absorbable → a flagged hole (you could
                          exit at size yesterday; today you cannot — the §9 exit-capacity collapse),
                          OR evaluate_hold fires EXIT_CAPACITY / CONCENTRATION.

THE NO-FORK RULE (AST-asserted by test_dfb_no_fork.py over every dfb/*.py): this module defines NO
risk math. The kill verdict is the engine's OWN `rate_policy.evaluate_hold` — DFB IMPORTS and CALLS
it (it does NOT define evaluate_hold and does NOT inline any slippage primitive). The threshold
diffs (APY/TVL/exit/structural) are PRESENTATION deltas over the overlay's published cells, not new
risk math. The authoritative kill REASON, when a kill fires, is read off evaluate_hold's KillReason.

FAIL-CLOSED (the load-bearing honesty rule): a pool with NO prior history snapshot produces NO flip
alert (you cannot assert a transition you never observed — a fabricated flip is the worst lie here).
A malformed/None today-cell is treated as "no comparable signal" → no false alert. Missing data is
NEVER reported as a kill.

EDGE-TRIGGERED + IDEMPOTENT: the comparison is yesterday-snapshot → today-overlay, so re-running on
the same day re-derives the SAME alert set (deterministic). A pool already REFUSE yesterday and still
REFUSE today does NOT re-fire REFUSAL_FLIP (it is not a crossing). Flapping is naturally deduped
because we compare against the last CAPTURED snapshot, not an intraday tick.

stdlib only · deterministic (`as_of` = the DATA date) · LLM-FORBIDDEN · READ-ONLY outside data/dfb/
· atomic writes · advisory (moves no capital, never touches the go-live track).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.dfb import PoolOverlay
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    GateResult,
    KillReason,
    KillState,
    RatePolicyParams,
)
# The kill verdict is the ENGINE's own evaluate_hold — IMPORTED and CALLED, never defined here.
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_hold

_ROOT = Path(__file__).resolve().parents[2]
GENESIS_PREV = "0" * 64

# ── alert types (severity-ranked; lower rank number = MORE severe) ──────────────────────────────────
ALERT_REFUSAL_FLIP = "REFUSAL_FLIP"
ALERT_EXIT_LIQUIDITY_DROP = "EXIT_LIQUIDITY_DROP"
ALERT_PEG_IL_SPIKE = "PEG_IL_SPIKE"
ALERT_APY_COLLAPSE = "APY_COLLAPSE"
ALERT_TVL_DRAIN = "TVL_DRAIN"

# Severity ranking — a REFUSE flip (the desk would now refuse) OUTRANKS an APY wobble. A structural
# refusal flip (tail_veto) is the worst; an exit-liquidity collapse / peg spike is next; then the
# economic diffs (APY/TVL). The frontend sorts REFUSAL_FLIP to the top on this order.
SEVERITY_RANK: Dict[str, int] = {
    ALERT_REFUSAL_FLIP: 0,
    ALERT_EXIT_LIQUIDITY_DROP: 1,
    ALERT_PEG_IL_SPIKE: 2,
    ALERT_APY_COLLAPSE: 3,
    ALERT_TVL_DRAIN: 4,
}
# Human severity bucket per alert type (for the UI color-coding).
SEVERITY_LABEL: Dict[str, str] = {
    ALERT_REFUSAL_FLIP: "critical",
    ALERT_EXIT_LIQUIDITY_DROP: "high",
    ALERT_PEG_IL_SPIKE: "high",
    ALERT_APY_COLLAPSE: "medium",
    ALERT_TVL_DRAIN: "medium",
}

# Diff thresholds (PRESENTATION deltas over the overlay's published cells — NOT risk math). A drop
# must exceed the fraction of the prior level to fire (so noise does not spam).
APY_COLLAPSE_FRAC = 0.30          # apy_total fell > 30% of yesterday's level
TVL_DRAIN_FRAC = 0.30            # tvl_usd fell > 30% of yesterday's level
STRUCTURAL_SPIKE_ABS = 0.02      # structural_haircut rose by > 2 percentage points (absolute)

# The exit-ticket size whose absorbable→hole flip is the "can't exit at size anymore" signal.
EXIT_TICKET_USD = 1_000_000

# refusal verdicts that count as "the desk would refuse" for the flip test.
_REFUSE = "REFUSE"
# A flip FROM any of these TO REFUSE is the killer crossing.
_NON_REFUSE = ("SAFE", "WATCH", "UNKNOWN")

# The evaluate_hold KillReasons that map to each alert family (read off the engine, never re-derived).
_PEG_KILLS = (KillReason.UNDERLYING_DEPEG, KillReason.STABLE_DEPEG, KillReason.ORACLE_STALE)
_EXIT_KILLS = (KillReason.EXIT_CAPACITY, KillReason.CONCENTRATION)


def _alerts_dir(data_dir: Optional[Path] = None) -> Path:
    root = data_dir if data_dir is not None else (_ROOT / "data")
    return root / "dfb"


def _f(x) -> Optional[float]:
    """Coerce to a finite float, else None (fail-CLOSED — never 0-coerce a missing cell)."""
    if x is None:
        return None
    try:
        n = float(x)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return n


def _exit_1m_is_hole(exit_rows) -> Optional[bool]:
    """Is the $1M exit ticket a HOLE (flagged / absorbable unknown)? None if the ticket is absent
    (no comparable signal → no alert, fail-CLOSED)."""
    if not isinstance(exit_rows, list):
        return None
    for r in exit_rows:
        if not isinstance(r, dict):
            continue
        if r.get("ticket_usd") == EXIT_TICKET_USD:
            if r.get("flagged") is True:
                return True
            return _f(r.get("absorbable_usd")) is None
    return None


def _overlay_dict(ov) -> dict:
    """Accept either a PoolOverlay or its already-serialized dict (so both the writer and the API can
    feed this engine). Deterministic key set."""
    return ov.to_dict() if isinstance(ov, PoolOverlay) else dict(ov)


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# evaluate_hold reuse — run the ENGINE's continuous-kill gate on the held position implied by today's
# overlay row. This is the no-fork seam: the kill verdict is the engine's, DFB only SURFACES it.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def hold_verdict(
    pool_overlay,
    *,
    params: Optional[RatePolicyParams] = None,
    risk_override=None,
    exit_liquidity_usd: Optional[float] = None,
) -> Optional[GateResult]:
    """Run the ENGINE's `evaluate_hold` on the position implied by `pool_overlay`, reconstructing the
    engine inputs through `risk_overlay.engine_inputs` (the SINGLE pool→engine mapping — same one the
    overlay + the no-fork byte-identity test use). Returns the engine GateResult (approved=keep /
    refused=unwind) or None when the inputs cannot be built (fail-CLOSED → no kill claimed).

    `current_carry` for the compression leg is the position's now-realized carry = today's apy_total
    (the overlay's published rate). `state.entry_carry` is left None → the compression leg is inert
    (we are not tracking an entry basis here; this surfaces the STRUCTURAL/peg/exit kills, which is
    exactly the alert set). NO risk math — only input shaping + the engine call."""
    from spa_core.dfb import Pool, risk_overlay as ro

    d = _overlay_dict(pool_overlay)
    apy_total = _f((d.get("apy") or {}).get("total"))
    pool = Pool(
        pool_id=d.get("pool_id", ""), protocol=d.get("protocol", ""), chain=d.get("chain", ""),
        asset=d.get("asset", ""), tier=d.get("tier", ""), source="dfb_overlay",
        apy_total=apy_total, tvl_usd=_f(d.get("tvl_usd")),
        underlying_kind=None, market_id=None, as_of=d.get("as_of"),
    )
    kind = ro._resolve_kind(pool)
    if kind is None:
        return None
    risk = risk_override if risk_override is not None else ro._build_risk(pool, kind, pool.as_of or "")
    if risk is None:
        return None
    p = params or RatePolicyParams()
    try:
        inp = ro.engine_inputs(pool, kind, risk, pool.as_of or "", exit_liquidity_usd=exit_liquidity_usd)
        cc = Decimal(str(apy_total)) if apy_total is not None else D0
        result, _state = evaluate_hold(
            opp=inp["opp"], risk=inp["risk"], debt_asset_price=inp["debt_asset_price"],
            exit_liquidity=inp["exit_liquidity"], current_carry=cc, params=p, state=KillState(),
        )
        return result
    except Exception:  # noqa: BLE001 — fail-CLOSED: a malformed input never fabricates a kill
        return None


def _kill_reason(verdict: Optional[GateResult]) -> Optional[KillReason]:
    if verdict is None or verdict.approved:
        return None
    return verdict.reason


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# the alert engine — compare a prior snapshot vs today's overlay → emit deterministic alerts
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def compute_alerts(
    today_overlay,
    prev_snapshot: Optional[dict],
    *,
    as_of: Optional[str] = None,
    params: Optional[RatePolicyParams] = None,
    hold_result: Optional[GateResult] = None,
) -> List[dict]:
    """The deterministic alert set for ONE pool: compare `prev_snapshot` (a prior history record dict,
    or None) against `today_overlay` (a PoolOverlay or its dict) + run the engine's evaluate_hold.

    Returns a list of alert dicts (possibly empty), each:
      { type, severity, severity_rank, pool_id, protocol, chain, asset,
        as_of, prev_as_of, message, detail{...}, kill_reason|null, tail_veto }

    fail-CLOSED:
      • `prev_snapshot is None` (no prior captured state) → NO flip / diff alert is emitted (you
        cannot assert a transition you never observed). A structural kill from evaluate_hold may still
        fire (it is a TODAY-only verdict, not a transition) → PEG_IL_SPIKE / EXIT_LIQUIDITY_DROP.
      • any None today/prev cell → that diff is skipped (no false alert), never 0-coerced.
    """
    d = _overlay_dict(today_overlay)
    p = params or RatePolicyParams()
    aod = as_of or d.get("as_of")
    pid = d.get("pool_id", "")
    ident = {
        "pool_id": pid, "protocol": d.get("protocol", ""), "chain": d.get("chain", ""),
        "asset": d.get("asset", ""),
    }
    prev_as_of = (prev_snapshot or {}).get("as_of") or (prev_snapshot or {}).get("capture_date")

    # The engine kill verdict on today's row (the no-fork seam). Computed once; reused for every
    # engine-driven alert family. Callers may inject a precomputed hold_result (e.g. a red-team
    # toxic surface) — else we run evaluate_hold here.
    verdict = hold_result if hold_result is not None else hold_verdict(today_overlay, params=p)
    kr = _kill_reason(verdict)

    out: List[dict] = []

    def _emit(atype: str, message: str, detail: dict, kill_reason: Optional[KillReason] = None) -> None:
        out.append({
            "type": atype,
            "severity": SEVERITY_LABEL[atype],
            "severity_rank": SEVERITY_RANK[atype],
            **ident,
            "as_of": aod,
            "prev_as_of": prev_as_of,
            "message": message,
            "detail": detail,
            "kill_reason": (kill_reason.value if kill_reason is not None else None),
            "tail_veto": bool((d.get("refusal") or {}).get("tail_veto")),
        })

    # ── 1. REFUSAL_FLIP — the KILLER. A crossing into REFUSE we did NOT see before. Requires a prior
    #      snapshot (fail-CLOSED: no prior state → we cannot assert a flip). ──
    today_verdict = str((d.get("refusal") or {}).get("verdict") or "").upper()
    if prev_snapshot is not None:
        prev_verdict = str(prev_snapshot.get("refusal_verdict")
                           or (prev_snapshot.get("refusal") or {}).get("verdict") or "").upper()
        if today_verdict == _REFUSE and prev_verdict in _NON_REFUSE:
            tail = bool((d.get("refusal") or {}).get("tail_veto"))
            reason = (d.get("refusal") or {}).get("reason")
            _emit(ALERT_REFUSAL_FLIP,
                  f"{ident['protocol']} {ident['asset']} flipped {prev_verdict}→REFUSE "
                  f"(the desk would now refuse this pool"
                  + (" — STRUCTURAL tail-veto, at any size" if tail else "") + ")",
                  {"prev_verdict": prev_verdict, "today_verdict": today_verdict,
                   "refusal_reason": reason, "tail_veto": tail,
                   "engine_kill_reason": (kr.value if kr is not None else None)},
                  kill_reason=kr)

    # ── 2. EXIT_LIQUIDITY_DROP — the $1M exit ticket flipped absorbable→hole, OR evaluate_hold fired
    #      an exit/concentration kill on today's row. ──
    today_hole = _exit_1m_is_hole(d.get("exit_liquidity"))
    flip_to_hole = False
    if prev_snapshot is not None:
        prev_hole = prev_snapshot.get("exit_1m_is_hole")
        if prev_hole is None and "exit_liquidity" in prev_snapshot:
            prev_hole = _exit_1m_is_hole(prev_snapshot.get("exit_liquidity"))
        if prev_hole is False and today_hole is True:
            flip_to_hole = True
    engine_exit_kill = kr in _EXIT_KILLS if kr is not None else False
    if flip_to_hole or engine_exit_kill:
        msg = (f"{ident['protocol']} {ident['asset']}: $1M exit liquidity collapsed to a hole "
               f"(cannot exit at size)") if flip_to_hole else (
               f"{ident['protocol']} {ident['asset']}: engine exit/concentration kill "
               f"({kr.value if kr else '?'})")
        _emit(ALERT_EXIT_LIQUIDITY_DROP, msg,
              {"flip_to_hole": flip_to_hole, "today_1m_is_hole": today_hole,
               "engine_kill_reason": (kr.value if kr is not None else None)},
              kill_reason=(kr if engine_exit_kill else None))

    # ── 3. PEG_IL_SPIKE — a structural-haircut spike OR a peg/oracle/stable engine kill. ──
    engine_peg_kill = kr in _PEG_KILLS if kr is not None else False
    struct_spike = False
    today_struct = _f(d.get("structural_haircut"))
    if prev_snapshot is not None and today_struct is not None:
        prev_struct = _f(prev_snapshot.get("structural_haircut"))
        if prev_struct is not None and (today_struct - prev_struct) > STRUCTURAL_SPIKE_ABS:
            struct_spike = True
    if engine_peg_kill or struct_spike:
        if engine_peg_kill:
            msg = (f"{ident['protocol']} {ident['asset']}: peg/oracle kill "
                   f"({kr.value if kr else '?'})")
        else:
            msg = (f"{ident['protocol']} {ident['asset']}: structural risk spiked "
                   f"(+{(today_struct - _f(prev_snapshot.get('structural_haircut'))):.4f} haircut)")
        _emit(ALERT_PEG_IL_SPIKE, msg,
              {"struct_spike": struct_spike, "today_structural_haircut": today_struct,
               "engine_kill_reason": (kr.value if kr is not None else None)},
              kill_reason=(kr if engine_peg_kill else None))

    # ── 4. APY_COLLAPSE — apy_total fell > APY_COLLAPSE_FRAC of yesterday (both sides present). ──
    if prev_snapshot is not None:
        today_apy = _f((d.get("apy") or {}).get("total"))
        prev_apy = _f(prev_snapshot.get("apy_total")
                      or (prev_snapshot.get("apy") or {}).get("total"))
        if today_apy is not None and prev_apy is not None and prev_apy > 0:
            drop = (prev_apy - today_apy) / prev_apy
            if drop > APY_COLLAPSE_FRAC:
                _emit(ALERT_APY_COLLAPSE,
                      f"{ident['protocol']} {ident['asset']}: APY collapsed "
                      f"{prev_apy*100:.2f}%→{today_apy*100:.2f}% (−{drop*100:.0f}%)",
                      {"prev_apy_total": prev_apy, "today_apy_total": today_apy,
                       "drop_frac": round(drop, 6)})

    # ── 5. TVL_DRAIN — tvl_usd fell > TVL_DRAIN_FRAC of yesterday. ──
    if prev_snapshot is not None:
        today_tvl = _f(d.get("tvl_usd"))
        prev_tvl = _f(prev_snapshot.get("tvl_usd"))
        if today_tvl is not None and prev_tvl is not None and prev_tvl > 0:
            drop = (prev_tvl - today_tvl) / prev_tvl
            if drop > TVL_DRAIN_FRAC:
                _emit(ALERT_TVL_DRAIN,
                      f"{ident['protocol']} {ident['asset']}: TVL drained "
                      f"−{drop*100:.0f}% (${prev_tvl/1e6:.1f}M→${today_tvl/1e6:.1f}M)",
                      {"prev_tvl_usd": prev_tvl, "today_tvl_usd": today_tvl,
                       "drop_frac": round(drop, 6)})

    return out


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# proof chain + persistence
# ──────────────────────────────────────────────────────────────────────────────────────────────────
_ALERT_BODY_KEYS = (
    "type", "severity", "severity_rank", "pool_id", "protocol", "chain", "asset",
    "as_of", "prev_as_of", "message", "detail", "kill_reason", "tail_veto",
)


def _alert_body(a: dict) -> dict:
    """The signed alert body (deterministic key set) — the chain links over THIS."""
    return {k: a.get(k) for k in _ALERT_BODY_KEYS}


def _row_hash(body: dict, prev_hash: str) -> str:
    blob = json.dumps({"body": body, "prev_hash": prev_hash}, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _alert_id(a: dict) -> str:
    """A stable per-alert id (pool_id + type + as_of) — lets a consumer dedupe an alert that is
    re-derived deterministically on a re-run of the same day."""
    return f"{a.get('pool_id','')}|{a.get('type','')}|{a.get('as_of','')}"


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows


def _atomic_write_jsonl(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) for r in rows]
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    os.replace(str(tmp), str(path))


def _prior_snapshot_for(pool_id: str, today_as_of: Optional[str], data_dir: Optional[Path]) -> Optional[dict]:
    """The most-recent CAPTURED history record STRICTLY BEFORE today_as_of (the comparison baseline).
    Reads the proof-chained data/dfb/history/<pool_id>.jsonl via history.read_history. fail-CLOSED:
    no history / only today's record → None (no flip baseline → no fabricated flip)."""
    from spa_core.dfb import history
    rows = history.read_history(pool_id, data_dir)
    if not rows:
        return None
    prior = None
    for r in rows:
        cd = r.get("capture_date") or r.get("as_of")
        if today_as_of is None or (cd is not None and cd < today_as_of):
            prior = r  # rows are ascending → last one strictly before today wins
    return prior


def run_alerts(
    overlays,
    *,
    as_of: Optional[str] = None,
    params: Optional[RatePolicyParams] = None,
    data_dir: Optional[Path] = None,
    write: bool = True,
) -> dict:
    """Compute the alert set across a universe of overlays vs each pool's PRIOR captured snapshot,
    severity-rank it, and (if write) atomically persist:
      • data/dfb/alerts.json  — the proof-chained current alert set (severity-ranked) + summary
      • data/dfb/alerts.jsonl — the APPEND-ONLY alert log (deduped per alert_id, proof-chained)

    Deterministic / fail-CLOSED / atomic. Returns the alerts.json payload dict."""
    p = params or RatePolicyParams()
    rows = [_overlay_dict(ov) for ov in overlays]
    eff_as_of = as_of or next((r.get("as_of") for r in rows if r.get("as_of")), None)

    all_alerts: List[dict] = []
    for r in rows:
        prior = _prior_snapshot_for(r.get("pool_id", ""), r.get("as_of") or eff_as_of, data_dir)
        all_alerts.extend(compute_alerts(r, prior, as_of=eff_as_of, params=p))

    # severity rank (lower = more severe) then pool_id for a stable, deterministic order.
    all_alerts.sort(key=lambda a: (a.get("severity_rank", 99), a.get("pool_id", ""), a.get("type", "")))

    # proof-chain the current set (genesis 0*64).
    chained: List[dict] = []
    prev = GENESIS_PREV
    for a in all_alerts:
        body = _alert_body(a)
        rh = _row_hash(body, prev)
        chained.append({**a, "alert_id": _alert_id(a), "prev_hash": prev, "row_hash": rh})
        prev = rh

    by_sev: Dict[str, int] = {}
    for a in all_alerts:
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
    by_type: Dict[str, int] = {}
    for a in all_alerts:
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1

    payload = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "schema": "dfb_alerts_v1",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "no_fork": ("kill verdict imported from spa_core.strategy_lab.rates_desk.rate_policy."
                    "evaluate_hold (not copied); diffs are presentation deltas over the overlay"),
        "as_of": eff_as_of,
        "n_alerts": len(chained),
        "n_refusal_flips": by_type.get(ALERT_REFUSAL_FLIP, 0),
        "by_severity": by_sev,
        "by_type": by_type,
        "alerts": chained,
        "disclaimer": ("Each alert is the SPA risk engine's OWN kill signal (evaluate_hold, imported "
                       "not forked) or a presentation delta over the published overlay. A pool with "
                       "no prior captured snapshot fires NO transition alert (fail-CLOSED). Advisory "
                       "— moves no capital, never touches the go-live track."),
    }

    if write:
        d = _alerts_dir(data_dir)
        from spa_core.strategy_lab.rates_desk import _io
        _io.atomic_write_json(d / "alerts.json", payload, indent=1, default=str)
        _append_log(chained, data_dir)
    return payload


def _append_log(chained_alerts: List[dict], data_dir: Optional[Path]) -> dict:
    """Append NEW alerts (by alert_id) onto the proof-chained append-only log data/dfb/alerts.jsonl.
    Idempotent: an alert_id already in the log is NOT re-appended (the deterministic re-run of a day
    does not duplicate). The log chains independently of the current-set file (its own prev/row hash
    over the append order). Returns {appended, skipped}."""
    path = _alerts_dir(data_dir) / "alerts.jsonl"
    existing = _read_jsonl(path)
    seen = {r.get("alert_id") for r in existing if isinstance(r, dict)}
    prev = existing[-1].get("row_hash") if existing else GENESIS_PREV
    appended = 0
    skipped = 0
    new_rows: List[dict] = []
    for a in chained_alerts:
        aid = a.get("alert_id") or _alert_id(a)
        if aid in seen:
            skipped += 1
            continue
        body = _alert_body(a)
        rh = _row_hash(body, prev)
        new_rows.append({**body, "alert_id": aid, "prev_hash": prev, "row_hash": rh})
        prev = rh
        seen.add(aid)
        appended += 1
    if new_rows:
        _atomic_write_jsonl(path, existing + new_rows)
    return {"appended": appended, "skipped": skipped}


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# OPTIONAL Telegram digest — opt-in, ONE consolidated message of the REFUSAL_FLIPs (the killers).
# Reuses the existing consolidated telegram_client (flood-guarded); creates NO new flooding agent.
# OFF by default (env SPA_DFB_TELEGRAM_DIGEST must be truthy). NO LLM, deterministic body.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def _telegram_enabled() -> bool:
    return os.environ.get("SPA_DFB_TELEGRAM_DIGEST", "").strip().lower() in ("1", "true", "yes", "on")


def _digest_body(payload: dict) -> Optional[str]:
    """Build the consolidated DFB alert digest (HTML) — ONLY the REFUSAL_FLIPs (the killers). Returns
    None when there is nothing to report (so we never send an empty/spam digest). Deterministic."""
    alerts = payload.get("alerts", []) or []
    flips = [a for a in alerts if a.get("type") == ALERT_REFUSAL_FLIP]
    if not flips:
        return None
    as_of = payload.get("as_of") or "?"
    lines = [f"<b>DFB · refusal-flip digest</b> · {as_of}",
             f"{len(flips)} pool(s) flipped to REFUSE (the desk would now refuse):", ""]
    for a in flips[:20]:  # bound the message size
        tail = " · <b>tail-veto</b>" if a.get("tail_veto") else ""
        lines.append(f"• {a.get('protocol','?')} {a.get('asset','?')} "
                     f"({a.get('chain','?')}){tail}")
    lines.append("")
    lines.append("advisory · read-only · /board/alerts")
    return "\n".join(lines)


def digest_telegram(payload: Optional[dict] = None, data_dir: Optional[Path] = None,
                    *, force: bool = False) -> dict:
    """Send the consolidated DFB REFUSAL_FLIP digest via the EXISTING telegram_client (one message,
    flood-guarded — no new agent). OFF unless SPA_DFB_TELEGRAM_DIGEST is truthy (or force=True).
    Reuses spa_core.alerts.telegram_client.send_message (HTML; '_' in protocol names 400s Markdown).
    Returns {sent, reason}. Never raises (fail-safe), never sends an empty digest."""
    if not (force or _telegram_enabled()):
        return {"sent": False, "reason": "disabled (set SPA_DFB_TELEGRAM_DIGEST=1 to enable)"}
    pl = payload if payload is not None else read_alerts(data_dir)
    body = _digest_body(pl)
    if body is None:
        return {"sent": False, "reason": "no_refusal_flips"}
    try:
        from spa_core.alerts import telegram_client
        ok = telegram_client.send_message(body, parse_mode="HTML")
        return {"sent": bool(ok), "reason": "delivered" if ok else "send_failed"}
    except Exception as e:  # noqa: BLE001 — fail-safe: a telegram error never breaks the alert run
        return {"sent": False, "reason": f"error: {e}"}


def read_alerts(data_dir: Optional[Path] = None) -> dict:
    """The current proof-chained alert set (data/dfb/alerts.json), or an honest empty payload
    (fail-CLOSED — never a fabricated alert)."""
    path = _alerts_dir(data_dir) / "alerts.json"
    if not path.exists():
        return {"available": False, "alerts": [], "n_alerts": 0, "as_of": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"available": False, "alerts": [], "n_alerts": 0, "as_of": None}
    payload.setdefault("available", True)
    return payload


def read_pool_alert_log(pool_id: str, data_dir: Optional[Path] = None) -> List[dict]:
    """A single pool's alert history from the append-only log (ascending), or []. Read-only."""
    rows = _read_jsonl(_alerts_dir(data_dir) / "alerts.jsonl")
    return [r for r in rows if isinstance(r, dict) and r.get("pool_id") == pool_id]


def verify_log_rows(rows: List[dict]) -> dict:
    """Verify a list of alert-log rows AS ONE chain (each prev_hash links the previous row_hash, each
    row_hash recomputes from the signed body). The canonical alert-log verifier — the API router
    composes THIS (no-fork: the alert-chain math lives only here). fail-CLOSED: a corrupt/non-dict row
    (no row_hash) breaks the chain — the honest tamper-evident outcome. Empty is vacuously valid.
    Returns {valid, length, broken_at, head_hash}."""
    prev = GENESIS_PREV
    head = None
    for idx, r in enumerate(rows):
        if not isinstance(r, dict) or r.get("prev_hash") != prev:
            return {"valid": False, "length": len(rows), "broken_at": idx, "head_hash": head}
        if _row_hash(_alert_body(r), prev) != r.get("row_hash"):
            return {"valid": False, "length": len(rows), "broken_at": idx, "head_hash": head}
        prev = r["row_hash"]
        head = r["row_hash"]
    return {"valid": True, "length": len(rows), "broken_at": None, "head_hash": head}


def verify_log_chain(data_dir: Optional[Path] = None) -> dict:
    """Verify the append-only alert log proof chain on disk (data/dfb/alerts.jsonl). fail-CLOSED."""
    rows = _read_jsonl(_alerts_dir(data_dir) / "alerts.jsonl")
    res = verify_log_rows(rows)
    return {k: res[k] for k in ("valid", "length", "broken_at")}
