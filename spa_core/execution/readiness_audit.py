#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Execution-readiness go/no-go SELF-AUDIT (institutional checklist).

A machine-checked, deterministic posture audit answering ONE question:
**is SPA safe and ready to move from paper-trading to LIVE on-chain execution?**

Design contract (HARD constraints — this module is SAFETY-CRITICAL):

  * READ-ONLY. This module only INSPECTS the safety posture of the execution
    domain. It NEVER enables live trading, NEVER executes anything, NEVER
    modifies any existing execution module / adapter / bridge. The only file
    it writes is its own report ``data/execution_readiness.json`` (atomic).

  * Pure STDLIB ONLY (os, json, datetime, importlib/inspect for introspection,
    tempfile for atomic write). NO network, NO web3, NO private keys, NO live
    calls. Deterministic — given the same env + on-disk state it returns the
    same verdict (modulo the ``audited_at`` timestamp).

  * Atomic writes only (tmp + os.replace). Never a partial report on disk.

Each check returns a dict ``{"ok": bool, "blocker": bool, "detail": str, ...}``
where ``ok`` is the safety reading and ``blocker`` flags whether this item
blocks the paper→live transition.

Two top-level verdicts are produced:

  * ``posture`` — "PAPER_SAFE" when the system is configured to NOT touch real
    capital (dry-run default + not-live mode + kill-switch readable + caps
    present). This is the SAFE state for the current paper phase.

  * ``ready_for_live`` — bool. Almost certainly ``False`` until custody/MPC is
    connected, an external audit is complete, and the track record gate is met.
    ``live_blockers`` lists exactly what is missing.

CLI::

    python3 -m spa_core.execution.readiness_audit
"""
from __future__ import annotations

import inspect
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.utils.atomic import atomic_save

# ─── Constants ────────────────────────────────────────────────────────────────

# Repo root = two levels above this file (spa_core/execution/readiness_audit.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_REPORT_FILENAME = "execution_readiness.json"

# Go-live track-record gate (mirrors golive_checker min_track_days_30).
MIN_TRACK_DAYS = 30

# Env var that, when == "live" (case-insensitive), arms the live execution path.
EXECUTION_MODE_ENV = "SPA_EXECUTION_MODE"

# Env vars that would indicate a live signer / custody is wired. ANY of these
# being present means a key is configured (UNSAFE for paper; REQUIRED for live).
SIGNER_KEY_ENVS = ("SPA_PRIVATE_KEY", "SPA_SIGNER_KEY", "SPA_WALLET_PRIVATE_KEY")

REPORT_VERSION = "v1.0"


# ─── Atomic IO ──────────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write — delegates to the shared atomic-save utility."""
    atomic_save(obj, str(path))


def _read_json(path: Path, default: Any = None) -> Any:
    """Read JSON defensively; never raises (returns ``default`` on any error)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def _check(ok: bool, blocker: bool, detail: str, **extra: Any) -> dict:
    """Build a standard check result dict."""
    out = {"ok": bool(ok), "blocker": bool(blocker), "detail": str(detail)}
    out.update(extra)
    return out


# ─── Individual checks ──────────────────────────────────────────────────────


def check_execution_mode_not_live() -> dict:
    """Check 1 — SPA_EXECUTION_MODE.

    For the paper phase we expect the mode to NOT be "live". If it IS live,
    that is a posture flag we surface (``live_mode=True``). Being live is not
    a safety blocker by itself (the adapters have their own gates), but for the
    paper phase the SAFE reading is "not live".
    """
    raw = os.getenv(EXECUTION_MODE_ENV, "") or ""
    is_live = raw.strip().lower() == "live"
    if is_live:
        return _check(
            ok=False,
            blocker=False,
            detail=f"{EXECUTION_MODE_ENV}={raw!r} → LIVE mode is ARMED (posture flag)",
            live_mode=True,
            value=raw,
        )
    return _check(
        ok=True,
        blocker=False,
        detail=f"{EXECUTION_MODE_ENV}={raw!r} → not live (paper-safe)",
        live_mode=False,
        value=raw,
    )


def check_adapter_dry_run_default() -> dict:
    """Check 2 — adapter ``dry_run`` constructor default is True.

    Inspects ``AaveV3Adapter.__init__`` (and CompoundV3Adapter if importable)
    via ``inspect.signature`` to confirm the ``dry_run`` parameter DEFAULTS to
    True. A False default would be a hard safety BLOCKER — any code that builds
    an adapter without passing dry_run would silently arm the live path.
    """
    results: list[str] = []
    all_safe = True
    inspected = 0

    targets = [
        ("AaveV3Adapter", "spa_core.execution.aave_v3_adapter", "AaveV3Adapter"),
        ("CompoundV3Adapter", "spa_core.execution.compound_v3_adapter", "CompoundV3Adapter"),
    ]
    for label, module_path, cls_name in targets:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            sig = inspect.signature(cls.__init__)
            param = sig.parameters.get("dry_run")
            if param is None:
                results.append(f"{label}: NO dry_run param (unexpected)")
                all_safe = False
                continue
            default = param.default
            inspected += 1
            if default is True:
                results.append(f"{label}.dry_run default=True (safe)")
            else:
                results.append(f"{label}.dry_run default={default!r} (UNSAFE)")
                all_safe = False
        except Exception as exc:  # noqa: BLE001 — never raise from audit
            results.append(f"{label}: not inspectable ({exc})")

    if inspected == 0:
        # Could not introspect any adapter — treat as a blocker (we cannot
        # confirm the safe default).
        return _check(
            ok=False,
            blocker=True,
            detail="could not inspect any adapter dry_run default: " + "; ".join(results),
        )
    return _check(
        ok=all_safe,
        blocker=not all_safe,
        detail="; ".join(results),
        adapters_inspected=inspected,
    )


def check_kill_switch_readable(data_dir: Path) -> dict:
    """Check 3 — kill-switch is importable and readable.

    Imports ``KillSwitchChecker`` and calls ``is_kill_switch_active()`` which
    returns a ``(bool, reason)`` tuple — we unpack ``[0]`` for the state and
    ``[1]`` for the reason. A readable kill-switch is a safety prerequisite.
    """
    try:
        from spa_core.governance.kill_switch import KillSwitchChecker

        checker = KillSwitchChecker(data_dir=str(data_dir))
        state = checker.is_kill_switch_active()
        # Contract: (active: bool, reason: str)
        active = bool(state[0])
        reason = str(state[1]) if len(state) > 1 else ""
        return _check(
            ok=True,
            blocker=False,
            detail=f"kill-switch readable; active={active} reason={reason!r}",
            kill_switch_active=active,
            kill_switch_reason=reason,
        )
    except Exception as exc:  # noqa: BLE001
        return _check(
            ok=False,
            blocker=True,
            detail=f"kill-switch NOT readable: {exc}",
            kill_switch_active=None,
        )


def check_live_amount_cap() -> dict:
    """Check 4 — a finite positive live-amount cap exists on the adapter.

    Confirms ``AaveV3Adapter.MAX_LIVE_AMOUNT`` exists and is a finite,
    strictly-positive number. This sanity gate catches unit/scaling bugs
    before they would ever hit chain.
    """
    try:
        import importlib
        import math

        mod = importlib.import_module("spa_core.execution.aave_v3_adapter")
        cls = getattr(mod, "AaveV3Adapter")
        cap = getattr(cls, "MAX_LIVE_AMOUNT", None)
        if cap is None:
            return _check(False, True, "AaveV3Adapter.MAX_LIVE_AMOUNT missing")
        if not isinstance(cap, (int, float)) or isinstance(cap, bool):
            return _check(False, True, f"MAX_LIVE_AMOUNT not numeric: {cap!r}")
        if not math.isfinite(float(cap)) or float(cap) <= 0:
            return _check(False, True, f"MAX_LIVE_AMOUNT not finite/positive: {cap!r}")
        return _check(
            ok=True,
            blocker=False,
            detail=f"MAX_LIVE_AMOUNT={cap} (finite, positive)",
            max_live_amount=float(cap),
        )
    except Exception as exc:  # noqa: BLE001
        return _check(False, True, f"could not read MAX_LIVE_AMOUNT: {exc}")


def check_multisig_control() -> dict:
    """Check 5 — large-amount / multisig routing control exists.

    Confirms ``PreExecutionSafety`` is importable and exposes
    ``check_amount_requires_multisig`` — the control that routes large
    transactions through Gnosis Safe multisig approval.
    """
    try:
        from spa_core.execution.safety_checks import PreExecutionSafety

        has = hasattr(PreExecutionSafety, "check_amount_requires_multisig")
        if not has:
            return _check(
                False, True,
                "PreExecutionSafety lacks check_amount_requires_multisig",
            )
        return _check(
            ok=True,
            blocker=False,
            detail="PreExecutionSafety.check_amount_requires_multisig present",
        )
    except Exception as exc:  # noqa: BLE001
        return _check(False, True, f"PreExecutionSafety not importable: {exc}")


def check_custody_connected() -> dict:
    """Check 6 — custody / live signer key.

    Looks for a live signer key in the environment (``SPA_PRIVATE_KEY`` etc.).

    For the PAPER phase, ABSENCE of any signer key is the SAFE state (``ok``)
    — the system cannot sign or move real funds. BUT absence is ALSO a
    go-live BLOCKER: you cannot execute live without custody/MPC connected.
    So this check is ``ok=True, blocker=True`` when no key is present.

    If a key IS present that is reported as unsafe-for-paper (``ok=False``):
    a private key in the environment of a paper-trading host is a posture risk.
    """
    present = [name for name in SIGNER_KEY_ENVS if os.getenv(name)]
    if present:
        return _check(
            ok=False,
            blocker=False,
            detail=(
                f"signer key env present: {present} — custody connected "
                "(UNSAFE for a paper host; required only at go-live)"
            ),
            custody_connected=True,
            signer_envs_present=present,
        )
    return _check(
        ok=True,
        blocker=True,
        detail=(
            "no signer/custody key in env (paper-safe) — but custody/MPC must "
            "be connected before live execution"
        ),
        custody_connected=False,
        signer_envs_present=[],
    )


def check_track_record(data_dir: Path) -> dict:
    """Check 7 — track-record / go-live gate.

    Reads the CANONICAL evidenced track count from ``data/golive_status.json``
    (``real_track_days`` — the honest evidenced-day count anchored to
    ``evidenced_anchor``, NOT the raw bar count) plus its ``passed`` / ``total``
    / ``ready``. The track-record gate is a BLOCKER until the EVIDENCED days
    reach ``MIN_TRACK_DAYS`` AND the golive checker reports ready.

    NOTE: ``paper_trading_status.json``'s ``days_running`` is the raw bar count
    (inflated by backfill/demo bars) and must NOT be used as the track length —
    the cutover scorecard must report the same EVIDENCED number the rest of the
    system publishes (gap_monitor / golive_status / SYSTEM_BRIEFING). Falls back
    to ``days_running`` only if ``real_track_days`` is absent (legacy file).
    """
    status = _read_json(data_dir / "paper_trading_status.json", {}) or {}
    golive = _read_json(data_dir / "golive_status.json", {}) or {}

    # Canonical EVIDENCED track length (anchored, honest) — NOT the raw bar count.
    days = None
    if "real_track_days" in golive:
        try:
            days = int(golive.get("real_track_days") or 0)
        except (TypeError, ValueError):
            days = None
    if days is None:  # legacy fallback only — golive_status without real_track_days
        try:
            days = int(status.get("days_running", 0) or 0)
        except (TypeError, ValueError):
            days = 0

    try:
        passed = int(golive.get("passed", 0) or 0)
    except (TypeError, ValueError):
        passed = 0
    try:
        total = int(golive.get("total", 0) or 0)
    except (TypeError, ValueError):
        total = 0
    golive_ready = bool(golive.get("ready", False))

    days_ok = days >= MIN_TRACK_DAYS
    ok = days_ok and golive_ready
    return _check(
        ok=ok,
        blocker=not ok,
        detail=(
            f"track days {days}/{MIN_TRACK_DAYS}; golive {passed}/{total} "
            f"passed; golive_ready={golive_ready}"
        ),
        days_running=days,
        min_track_days=MIN_TRACK_DAYS,
        golive_passed=passed,
        golive_total=total,
        golive_ready=golive_ready,
    )


# ─── Aggregate ──────────────────────────────────────────────────────────────


def audit(data_dir: str | os.PathLike | None = None) -> dict:
    """Run every readiness check and produce the aggregate verdict.

    Args:
        data_dir: Override for the ``data/`` directory (tests pass tmp_path).
            Defaults to ``<repo>/data``.

    Returns:
        dict with keys:
            ``audited_at``    — ISO-8601 UTC timestamp
            ``version``       — report schema version
            ``checks``        — {check_name: result-dict}
            ``posture``       — "PAPER_SAFE" | "POSTURE_AT_RISK"
            ``ready_for_live``— bool (almost always False during paper phase)
            ``live_blockers`` — list[str] of human-readable blockers
    """
    dd = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    checks: dict[str, dict] = {
        "execution_mode_not_live": check_execution_mode_not_live(),
        "adapter_dry_run_default": check_adapter_dry_run_default(),
        "kill_switch_readable": check_kill_switch_readable(dd),
        "live_amount_cap": check_live_amount_cap(),
        "multisig_control": check_multisig_control(),
        "custody_connected": check_custody_connected(),
        "track_record": check_track_record(dd),
    }

    # ── Posture: are we safely in the paper / non-live configuration? ──
    # PAPER_SAFE requires: not-live mode + dry-run default + kill-switch
    # readable + amount cap present (the controls that keep real funds untouched).
    posture_safe = (
        checks["execution_mode_not_live"]["ok"]
        and checks["adapter_dry_run_default"]["ok"]
        and checks["kill_switch_readable"]["ok"]
        and checks["live_amount_cap"]["ok"]
    )
    posture = "PAPER_SAFE" if posture_safe else "POSTURE_AT_RISK"

    # ── Live blockers: explicit, honest list ──
    live_blockers: list[str] = []

    if not checks["custody_connected"]["custody_connected"]:
        live_blockers.append("custody/MPC not connected")

    # External audit gate — there is no automated signal for a completed
    # third-party security audit, so we report it as PENDING (a standing
    # blocker) until an explicit attestation exists on disk.
    audit_attestation = _read_json(dd / "external_audit_attestation.json", None)
    if not (isinstance(audit_attestation, dict) and audit_attestation.get("passed") is True):
        live_blockers.append("external audit pending")

    tr = checks["track_record"]
    if not tr["ok"]:
        live_blockers.append(
            f"track_record <{MIN_TRACK_DAYS}d "
            f"({tr['days_running']}/{MIN_TRACK_DAYS}, golive_ready={tr['golive_ready']})"
        )

    if checks["execution_mode_not_live"]["live_mode"] is False:
        live_blockers.append("SPA_EXECUTION_MODE not enabled")

    # Any hard safety blocker (e.g. dry_run default flipped, kill-switch
    # unreadable, missing cap, missing multisig control) also blocks live.
    for name in (
        "adapter_dry_run_default",
        "kill_switch_readable",
        "live_amount_cap",
        "multisig_control",
    ):
        c = checks[name]
        if c["blocker"]:
            live_blockers.append(f"safety blocker: {name} ({c['detail']})")

    ready_for_live = len(live_blockers) == 0

    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "version": REPORT_VERSION,
        "checks": checks,
        "posture": posture,
        "ready_for_live": ready_for_live,
        "live_blockers": live_blockers,
    }


def build_report(
    write: bool = True,
    data_dir: str | os.PathLike | None = None,
) -> dict:
    """Build the readiness report and (optionally) persist it atomically.

    Args:
        write: If True (default), atomically write the report to
            ``<data_dir>/execution_readiness.json``.
        data_dir: Override for the data directory (tests pass tmp_path).

    Returns:
        The report dict (same shape as :func:`audit`).
    """
    dd = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    report = audit(data_dir=dd)
    if write:
        _atomic_write_json(dd / _REPORT_FILENAME, report)
    return report


# ─── CLI ────────────────────────────────────────────────────────────────────


def _main() -> int:
    report = build_report(write=True)
    print("=" * 64)
    print("SPA EXECUTION-READINESS SELF-AUDIT")
    print("=" * 64)
    print(f"posture        : {report['posture']}")
    print(f"ready_for_live : {report['ready_for_live']}")
    print(f"audited_at     : {report['audited_at']}")
    print("-" * 64)
    print("checks:")
    for name, c in report["checks"].items():
        mark = "OK " if c["ok"] else "!! "
        blk = " [BLOCKER]" if c["blocker"] else ""
        print(f"  [{mark}]{blk} {name}: {c['detail']}")
    print("-" * 64)
    if report["live_blockers"]:
        print("live_blockers:")
        for b in report["live_blockers"]:
            print(f"  - {b}")
    else:
        print("live_blockers: NONE")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
