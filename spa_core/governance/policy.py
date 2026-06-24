#!/usr/bin/env python3
"""SPA Governance-as-Code policy (parallel layer).

# LLM_FORBIDDEN

Machine-readable encoding of the governance authority table from
``docs/ARCHITECTURE_TIER1.md``: every action maps to a required *authority level*.

Three authority levels:

* ``AUTO``         — the AI may perform this action alone (read-only / reversible /
                     non-fund-moving operations + fail-safe freeze).
* ``HUMAN_SINGLE`` — requires one human sign-off (policy/economic decisions that
                     do not move money but change behaviour or public commitments).
* ``HUMAN_DUAL``   — requires **two signatures** (2-of-N multisig / dual control):
                     any movement of funds, key management, destructive ops, or
                     access-rights changes.

Law 1 (default-DENY): an action that is not in the policy table is treated as
``UNKNOWN`` and is **never** AI-permitted — the safe default is to require a human.

Design constraints (mirrors kill_switch.py / safety_checks.py):
* Pure stdlib, fully deterministic, no LLM / network calls.
* Atomic writes via spa_core.utils.atomic.atomic_save (tmp + replace).
* PARALLEL layer — this file adds capability, it does not touch existing modules.

Relationship to spa_core/execution/safety_checks.py:
    ``PreExecutionSafety.check_amount_requires_multisig`` decides multisig routing
    by *dollar amount* at execution time. This module decides, by *action class*,
    whether dual control is required at all — a complementary, policy-level view.
    Cryptographic enforcement of dual control still requires a custody / multisig
    wallet (see dual_control_posture()).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.governance.policy")

# ─── Version pin ────────────────────────────────────────────────────────────────
# Changing the authority table is a governance change → bump version + new ADR.
GOVERNANCE_POLICY_VERSION = "v1.0"

# Authority levels (ordered weakest → strongest requirement on the human side).
AUTO = "AUTO"
HUMAN_SINGLE = "HUMAN_SINGLE"
HUMAN_DUAL = "HUMAN_DUAL"
UNKNOWN = "UNKNOWN"

# Number of signatures each level requires.
_REQUIRED_SIGS = {
    AUTO: 0,
    HUMAN_SINGLE: 1,
    HUMAN_DUAL: 2,
}

# ─── The governance table (action → required authority) ─────────────────────────
# AUTO: AI may do alone (read-only / reversible / non-fund-moving + fail-safe).
_AUTO_ACTIONS = (
    "refresh_presentation_from_ssot",
    "github_commit",
    "ci_config",
    "dependency_bump_nonbreaking",
    "restart_service",
    "rebuild_telegram_bot",
    "run_backtest",
    "run_paper",
    "generate_reports",
    "reconciliation",
    "audit",
    "freeze_on_risk_invariant",   # fail-safe: freezing is always allowed
)

# HUMAN_SINGLE: one human sign-off (policy / economic / public commitments, no money movement).
_HUMAN_SINGLE_ACTIONS = (
    "promote_canary_to_full",
    "change_allocations",
    "change_risk_limits",
    "change_golive_dates",
    "change_public_apy",
)

# HUMAN_DUAL: two signatures / multisig (fund movement, keys, destructive, access).
_HUMAN_DUAL_ACTIONS = (
    "deposit",
    "withdraw",
    "rebalance_with_fund_movement",
    "change_allocation_with_movement",
    "key_management",
    "force_push",
    "delete",
    "access_rights",
)

# Flattened action → authority map (built deterministically from the tuples above).
_POLICY_TABLE: dict[str, str] = {}
for _a in _AUTO_ACTIONS:
    _POLICY_TABLE[_a] = AUTO
for _a in _HUMAN_SINGLE_ACTIONS:
    _POLICY_TABLE[_a] = HUMAN_SINGLE
for _a in _HUMAN_DUAL_ACTIONS:
    _POLICY_TABLE[_a] = HUMAN_DUAL

GOVERNANCE_POLICY_FILENAME = "governance_policy.json"


# ─── Public API ─────────────────────────────────────────────────────────────────


def required_authority(action: str) -> str:
    """Return the required authority level for ``action``.

    Returns one of ``"AUTO"`` | ``"HUMAN_SINGLE"`` | ``"HUMAN_DUAL"`` | ``"UNKNOWN"``.
    Unknown / unrecognised actions return ``"UNKNOWN"`` (Law 1: default-DENY).
    """
    if not isinstance(action, str):
        return UNKNOWN
    return _POLICY_TABLE.get(action, UNKNOWN)


def is_ai_permitted(action: str) -> bool:
    """True only if the AI may perform ``action`` alone (i.e. it is ``AUTO``).

    Everything else — HUMAN_SINGLE, HUMAN_DUAL, and UNKNOWN — returns False.
    """
    return required_authority(action) == AUTO


def check_action(action: str, actor: str, signatures: int = 0) -> dict[str, Any]:
    """Evaluate whether ``action`` may proceed given ``actor`` and ``signatures``.

    Rules:
    * AUTO         — permitted with any signature count (≥0).
    * HUMAN_SINGLE — permitted iff signatures >= 1.
    * HUMAN_DUAL   — permitted iff signatures >= 2 (dual control / multisig).
    * UNKNOWN      — always denied (Law 1: default-DENY).

    Parameters
    ----------
    action : the action key being attempted.
    actor : identifier of who/what is attempting it (recorded in the result; an
            AI actor may only ever satisfy AUTO since it cannot supply human signatures).
    signatures : number of valid human signatures provided.

    Returns
    -------
    dict with keys: ``permitted`` (bool), ``reason`` (str), ``required`` (str),
    ``provided`` (int), ``action`` (str), ``actor`` (str).
    """
    try:
        provided = int(signatures)
    except (TypeError, ValueError):
        provided = 0
    if provided < 0:
        provided = 0

    required = required_authority(action)

    def _result(permitted: bool, reason: str) -> dict[str, Any]:
        return {
            "permitted": permitted,
            "reason": reason,
            "required": required,
            "provided": provided,
            "action": action,
            "actor": actor,
        }

    if required == UNKNOWN:
        return _result(
            False,
            f"action '{action}' not in governance policy {GOVERNANCE_POLICY_VERSION} "
            f"— default-DENY (Law 1)",
        )

    need = _REQUIRED_SIGS[required]
    if provided >= need:
        if required == AUTO:
            reason = f"action '{action}' is AUTO — AI/actor '{actor}' permitted alone"
        else:
            reason = (
                f"action '{action}' requires {required} ({need} signature(s)); "
                f"{provided} provided — permitted"
            )
        return _result(True, reason)

    return _result(
        False,
        f"action '{action}' requires {required} ({need} signature(s)); "
        f"only {provided} provided — DENIED",
    )


def policy_manifest() -> dict[str, Any]:
    """Return the full machine-readable governance table + version.

    Deterministic: keys are sorted, no timestamps embedded.
    """
    by_action = {a: _POLICY_TABLE[a] for a in sorted(_POLICY_TABLE)}
    return {
        "version": GOVERNANCE_POLICY_VERSION,
        "default_policy": "DENY",  # Law 1: unknown action → deny
        "law": "Law 1 default-DENY: unknown actions are never AI-permitted",
        "levels": {
            AUTO: {
                "required_signatures": _REQUIRED_SIGS[AUTO],
                "ai_permitted": True,
                "description": "AI may perform alone (read-only / reversible / non-fund-moving + fail-safe freeze)",
                "actions": sorted(_AUTO_ACTIONS),
            },
            HUMAN_SINGLE: {
                "required_signatures": _REQUIRED_SIGS[HUMAN_SINGLE],
                "ai_permitted": False,
                "description": "Requires one human sign-off (policy / economic / public commitment, no money movement)",
                "actions": sorted(_HUMAN_SINGLE_ACTIONS),
            },
            HUMAN_DUAL: {
                "required_signatures": _REQUIRED_SIGS[HUMAN_DUAL],
                "ai_permitted": False,
                "description": "Requires two signatures (2-of-N multisig / dual control): fund movement, keys, destructive, access rights",
                "actions": sorted(_HUMAN_DUAL_ACTIONS),
            },
        },
        "by_action": by_action,
        "action_count": len(by_action),
    }


def dual_control_posture(data_dir: str | Path | None = None) -> dict[str, Any]:
    """Report whether dual control (2-of-N multisig) is cryptographically enforced.

    In paper mode there is no custody wallet, so dual control is *advisory* only:
    the policy table demands 2 signatures for HUMAN_DUAL actions, but nothing on
    chain enforces a 2-of-N signer threshold. This function looks for a multisig
    config (``data/multisig_config.json`` with a ``threshold`` >= 2 and >= threshold
    signers) and reports honestly whether enforcement exists.

    Returns
    -------
    dict with keys ``enforced`` (bool), ``mechanism`` (str), ``threshold``,
    ``signers``, and ``note``.
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[2] / "data"
    cfg_path = Path(data_dir) / "multisig_config.json"

    threshold = 0
    signers = 0
    if cfg_path.exists():
        try:
            import json

            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                threshold = int(cfg.get("threshold", 0) or 0)
                signer_list = cfg.get("signers", [])
                signers = len(signer_list) if isinstance(signer_list, list) else int(cfg.get("signers", 0) or 0)
        except (ValueError, OSError, TypeError) as exc:
            log.warning("multisig_config.json unreadable (%s) — treating as not configured", exc)

    enforced = threshold >= 2 and signers >= threshold

    if enforced:
        return {
            "enforced": True,
            "mechanism": "multisig",
            "threshold": threshold,
            "signers": signers,
            "note": (
                f"{threshold}-of-{signers} multisig configured — HUMAN_DUAL actions "
                f"cryptographically enforced"
            ),
        }

    return {
        "enforced": False,
        "mechanism": "advisory",
        "threshold": threshold,
        "signers": signers,
        "note": (
            "Dual control is ADVISORY in paper mode: the policy table requires 2 "
            "signatures for HUMAN_DUAL actions, but no on-chain signer threshold "
            "enforces it. A custody / 2-of-3 multisig wallet is required for "
            "cryptographic enforcement (infra dependency)."
        ),
    }


def build_report(write: bool = True, data_dir: str | Path | None = None) -> dict[str, Any]:
    """Build the governance report (manifest + dual-control posture).

    When ``write`` is True, atomically writes it to
    ``data/governance_policy.json`` via atomic_save (tmp + replace).
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[2] / "data"
    data_dir = Path(data_dir)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": GOVERNANCE_POLICY_VERSION,
        "manifest": policy_manifest(),
        "dual_control_posture": dual_control_posture(data_dir),
    }

    if write:
        out_path = data_dir / GOVERNANCE_POLICY_FILENAME
        try:
            atomic_save(report, str(out_path))
            log.info("Governance policy report written → %s", out_path)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Failed to write %s: %s", out_path, exc)

    return report


# ─── __main__ ────────────────────────────────────────────────────────────────────


def _print_table() -> None:
    # Persist the governance report → data/governance_policy.json (atomic).
    build_report(write=True)
    manifest = policy_manifest()
    print(f"SPA Governance-as-Code · policy {manifest['version']} "
          f"({manifest['action_count']} actions) · default={manifest['default_policy']}")
    print("=" * 72)
    for level in (AUTO, HUMAN_SINGLE, HUMAN_DUAL):
        info = manifest["levels"][level]
        sigs = info["required_signatures"]
        ai = "AI-OK" if info["ai_permitted"] else "human-only"
        print(f"\n[{level}]  signatures>={sigs}  ({ai})")
        print(f"  {info['description']}")
        for action in info["actions"]:
            print(f"    - {action}")

    print("\n" + "=" * 72)
    posture = dual_control_posture()
    verdict = "ENFORCED" if posture["enforced"] else "NOT ENFORCED"
    print(f"dual_control_posture: {verdict}  (mechanism={posture['mechanism']}, "
          f"threshold={posture['threshold']}, signers={posture['signers']})")
    print(f"  note: {posture['note']}")


if __name__ == "__main__":
    _print_table()
