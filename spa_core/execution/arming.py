"""
spa_core/execution/arming.py — central, STRUCTURAL capital-arming assertion.

WS-5.1 (ROUND-2 "Prove the Edge"). The inert live-trading guard used to be
POSITIONAL: ``@live_trading_forbidden`` sat on one wrapper method per adapter
(e.g. ``_sign_and_send``), while the underlying capital primitives
(``eth_signer.sign_transaction`` / ``eth_signer.send_raw_transaction`` /
``mev_protection.send_protected``) were each individually UNGUARDED. An adversary
(or an accidental regression) that called a primitive DIRECTLY — bypassing the
decorated wrapper — would slip straight through.

This module makes the defense STRUCTURAL: every capital primitive calls
:func:`assert_live_armed` on entry and HARD-RAISES unless the global arming flag
``SPA_EXEC_ARMED`` is explicitly set on. The default is OFF, and it STAYS OFF for
the entire paper-trading period.

Owner-gated go-live arming flag
-------------------------------
``SPA_EXEC_ARMED`` is THE owner-gated go-live cutover switch for the capital
primitives. Flipping it ON is the owner-gated go-live cutover — it is NOT flipped
by any automated process, test, or sprint. It is deliberately SEPARATE from the
``LiveTradingGate`` (data/live_trading_gate.json) and from each adapter's
``is_live`` flag; this module does NOT flip any of those. The existing
``@live_trading_forbidden`` decorator stays in place as defense-in-depth — this
assertion is an ADDITIONAL, structural inner layer, not a replacement.

Design contract
---------------
* DEFAULT OFF — absence of the env var, or any value that is not an explicit
  affirmative ("1"/"true"/"yes"/"on", case-insensitive), means NOT armed.
* fail-CLOSED — any ambiguity resolves to NOT armed.
* deterministic, stdlib-only, NO LLM. Reads only an env var; touches no files,
  no network, no live ``data/``.
* never logs key material (it is handed none).

LLM_FORBIDDEN: no LLM calls inside this module.
"""
from __future__ import annotations

import os

from spa_core.utils.errors import LiveTradingForbiddenError

__all__ = [
    "EXEC_ARMED_ENV",
    "is_exec_armed",
    "assert_live_armed",
    "ENV_PRIVATE_KEY_REFUSAL",
    "refuse_env_private_key",
]

# THE owner-gated go-live arming flag for the capital primitives. OFF the whole
# paper period; flipping it ON IS the owner-gated go-live cutover.
EXEC_ARMED_ENV = "SPA_EXEC_ARMED"

# Only these explicit, affirmative tokens arm execution. Everything else
# (unset / "" / "0" / "false" / typos / whitespace) is fail-CLOSED → NOT armed.
_AFFIRMATIVE = frozenset({"1", "true", "yes", "on"})


def is_exec_armed() -> bool:
    """Return True ONLY when ``SPA_EXEC_ARMED`` is an explicit affirmative token.

    fail-CLOSED: an unset var, an empty string, or any non-affirmative value
    (including typos and "0"/"false"/"off") returns False — execution is NOT
    armed. This never raises and never has side effects.
    """
    raw = os.getenv(EXEC_ARMED_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in _AFFIRMATIVE


def assert_live_armed(primitive: str) -> None:
    """Hard-raise unless execution is explicitly armed (``SPA_EXEC_ARMED`` ON).

    This is the STRUCTURAL inner guard called at the top of every capital
    primitive (sign / broadcast / send_protected). Because it lives INSIDE the
    primitive — not on a wrapper above it — a direct call to the primitive that
    bypasses the ``@live_trading_forbidden`` decorator is STILL blocked.

    Args:
        primitive: dotted name of the calling primitive (e.g.
            ``"eth_signer.sign_transaction"``) — used only to build the error
            message. Never pass key material here.

    Raises:
        LiveTradingForbiddenError: unless ``SPA_EXEC_ARMED`` is explicitly armed.
    """
    if not is_exec_armed():
        raise LiveTradingForbiddenError(f"exec_armed:{primitive}")


# ─────────────────────────────────────────────────────────────────────────────
# ADR-556 item 15 — signer hygiene: the environment-key path is removed
# ─────────────────────────────────────────────────────────────────────────────

ENV_PRIVATE_KEY_REFUSAL = (
    "env-key signing removed (ADR-556): an owner-held hardware signer is the "
    "only intended path"
)


def refuse_env_private_key(var_name: str = "SPA_PRIVATE_KEY") -> None:
    """Unconditionally refuse to source a live signing key from the environment.

    ADR-556 item 15 (RM-LIVE-01 hardening, 2026-10-04): the environment-variable
    key path is removed from every call site that used to read it — not just
    when the variable is absent or malformed. There is no successful outcome
    from this function; whether *var_name* is unset, well-formed, or would
    derive the expected address makes no difference. An owner-held hardware
    signer (clear-signing, never reachable by this runtime) is the only
    intended path to a live signature.

    This is intentionally a FUNCTION, not a check — callers that used to do
    ``pk = os.environ.get(var_name); if not pk: raise ...`` now call this
    instead of reading the variable at all, so the key never even touches a
    local variable in the caller's frame.

    Args:
        var_name: name of the env var the caller used to read (for the
            message only; never pass key material here).

    Raises:
        LiveTradingForbiddenError: always.
    """
    raise LiveTradingForbiddenError(f"{var_name}: {ENV_PRIVATE_KEY_REFUSAL}")
