"""spa_core/monitoring/actions.py — RTMR (ADR-053) S10.4 action applier (PAPER).

Applies the deterministic reaction actions (§5) to the shared posture and logs them. Owner §13.3:
**paper for now — this NEVER moves capital.** It (1) updates `risk_posture.json` (so the
rebalance-loop de-risks on its next cycle — S10.5), (2) appends a signed-later `reaction_log.json`,
(3) sends the owner a Telegram alert ("would EXIT X"). Live execution is a separate, explicitly
authorised step. de-risk-only is enforced (invariant §1.4). LLM-forbidden, deterministic.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
from pathlib import Path

from spa_core.monitoring import posture as P
from spa_core.monitoring import reaction as R

_ROOT = Path(__file__).resolve().parents[2]
_LOG = _ROOT / "data" / "monitoring" / "reaction_log.json"
_LOG_MAX = 2000
_DAY = 86400


def _atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(str(path), obj)
        return
    except Exception:  # noqa: BLE001
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)


def _apply_one(posture: dict, act, *, now_ts: int, cooldown_sec: int) -> dict:
    """Translate one de-risk Action into a posture mutation (never raises exposure)."""
    assert act.is_de_risk_only(), f"refusing non-de-risk action: {act}"  # invariant §1.4
    if act.kind == R.MARKET_EXIT:
        return P.set_portfolio(posture, state=P.DEFENSIVE, reason=act.reason)
    if act.kind in (R.FULL_EXIT, R.ROTATE_TO_SAFE):
        return P.set_entry(posture, scope=act.scope, state=P.EXITED, now_ts=now_ts,
                           until_ts=now_ts + cooldown_sec, reason=act.reason)
    if act.kind in (R.REDUCE, R.TIGHTEN):
        cap = act.pct if act.pct is not None else 0.5
        return P.set_entry(posture, scope=act.scope, state=P.CAPPED, now_ts=now_ts,
                           cap=cap, reason=act.reason)
    # FREEZE
    return P.set_entry(posture, scope=act.scope, state=P.FROZEN, now_ts=now_ts, reason=act.reason)


def _posture_sig(posture: dict) -> tuple:
    """Signature of the meaningful posture state (ignores timestamps) — for change detection."""
    entries = posture.get("entries", {})
    return (posture.get("portfolio"),
            tuple(sorted((k, e.get("state"), e.get("cap")) for k, e in entries.items())))


def apply_actions(actions, *, now_ts: int, cfg: dict | None = None, notify: bool = True) -> dict:
    """Apply de-risk actions → new posture (persisted) + reaction_log + Telegram. PAPER (no capital).

    Alerts fire ONLY when the posture actually CHANGES (a new de-risk), never every tick while a
    posture stays active — so a persistent depeg doesn't spam Telegram every ``sense_interval``.
    """
    cfg = cfg or {}
    cooldown_sec = int(cfg.get("cooldown_days", 3)) * _DAY
    posture = P.load_posture()
    sig_before = _posture_sig(posture)
    applied = []
    for act in actions:
        posture = _apply_one(posture, act, now_ts=now_ts, cooldown_sec=cooldown_sec)
        applied.append({"kind": act.kind, "scope": act.scope, "pct": act.pct, "reason": act.reason})
    P.save_posture(posture, now_ts=now_ts)
    changed = _posture_sig(posture) != sig_before
    if applied:
        _append_log(now_ts, applied)
        if notify and changed:  # only alert on a genuinely NEW de-risk, not a still-active one
            _notify(now_ts, applied)
    return posture


def _append_log(now_ts: int, applied: list) -> None:
    entry = {"ts": int(now_ts), "mode": "paper", "actions": applied}
    log = []
    try:
        with open(_LOG, encoding="utf-8") as fh:
            log = json.load(fh)
            if not isinstance(log, list):
                log = []
    except Exception:  # noqa: BLE001
        log = []
    log.append(entry)
    if len(log) > _LOG_MAX:
        log = log[-_LOG_MAX:]
    _atomic_write(_LOG, log)


def _notify(now_ts: int, applied: list) -> None:
    """Best-effort Telegram alert. Paper: describes what WOULD happen; never blocks/raises."""
    try:
        lines = [f"• {a['kind']} {a['scope']}" + (f" → cap {a['pct']}" if a.get("pct") is not None else "")
                 + (f" ({a['reason']})" if a.get("reason") else "") for a in applied]
        body = "🛡️ RTMR de-risk (PAPER — no capital moved):\n" + "\n".join(lines)
        try:
            from spa_core.alerts.telegram_manager import telegram_manager  # type: ignore
            telegram_manager.send(body, title="RTMR de-risk", category="monitoring")  # returns False on cooldown
            return
        except Exception:  # noqa: BLE001 — fall through to raw client
            pass
        from spa_core.alerts import telegram_client  # type: ignore
        telegram_client._post_message(body)  # noqa: SLF001
    except Exception:  # noqa: BLE001 — notification is best-effort; never affects the de-risk decision
        pass


def react_and_apply(signals, *, now_ts: int, cfg: dict | None = None, notify: bool = True) -> dict:
    """Convenience: evaluate the ladder then apply (the sense_loop emergency-path entrypoint)."""
    cfg = cfg or {}
    actions = R.evaluate(signals, cfg)
    return apply_actions(actions, now_ts=now_ts, cfg=cfg, notify=notify)
