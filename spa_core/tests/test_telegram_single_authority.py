"""CI guard: ONE Telegram push authority (Phase-1 Telegram rebuild).

Makes "only one code path may push unsolicited Telegram messages" a permanent,
CI-enforced invariant — the structural fix that keeps the flood dead. It greps
``spa_core/`` (and the top-level senders under ``scripts/``) for the two
mechanisms that constitute an unsolicited push and FAILS if any module outside a
small allowlist uses them:

  1. a direct ``urllib`` POST to a Telegram ``.../sendMessage`` endpoint, and
  2. a call to the shared transport's send funcs
     (``telegram_client.send_message`` / ``telegram_client._post_message``,
     or ``send_message(...)`` / ``_post_message(...)`` referencing them).

ALLOWLIST (the only modules permitted to reach the transport / POST sendMessage):
  * ``spa_core/alerts/telegram_client.py``         — THE transport
  * ``spa_core/telegram/push_policy.py``           — THE Tier-1 push authority
  * ``spa_core/telegram/reports/daily.py``         — THE daily digest
  * ``spa_core/telegram/reports/weekly.py``        — THE weekly digest
  * ``spa_core/reporting/daily_telegram_report.py``  — daily digest's builder
  * ``spa_core/reporting/weekly_telegram_report.py`` — weekly digest's builder
  * ``spa_core/telegram/bot.py``                   — interactive bot (owns its own
                                                     getUpdates/editMessageText loop)

Family-fund / investor-channel modules and ``getMe`` / ``getUpdates`` health
probes are out of scope (they are not the owner's ops chat push surface).

stdlib only. Deterministic. If this test fails, a NEW rogue sender appeared —
route it through ``push_policy`` (critical) or the digest queue (everything
else), do not add it to the allowlist.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPA_CORE = _REPO_ROOT / "spa_core"

# Modules permitted to call the transport / POST sendMessage directly.
_ALLOWLIST = {
    _SPA_CORE / "alerts" / "telegram_client.py",
    _SPA_CORE / "telegram" / "push_policy.py",
    _SPA_CORE / "telegram" / "reports" / "daily.py",
    _SPA_CORE / "telegram" / "reports" / "weekly.py",
    _SPA_CORE / "reporting" / "daily_telegram_report.py",
    _SPA_CORE / "reporting" / "weekly_telegram_report.py",
    _SPA_CORE / "telegram" / "bot.py",
    # Advisory / opt-in senders that route through the sanctioned transport
    # (telegram_client), not a raw urllib POST — sanctioned, not rogue:
    #  * backtesting/tier1/status.py: Tier-1 "attention" alert, ONLY on
    #    build(alert=...) with real problems (guarded, not unsolicited spam).
    #  * dfb/alerts.py: DFB refusal-flip digest, OFF unless
    #    SPA_DFB_TELEGRAM_DIGEST is truthy — one flood-guarded message, no new
    #    agent (dfb is current/green product code).
    #  * monitoring/actions.py (RTMR / ADR-053): de-risk alert, routes through
    #    telegram_manager.send / telegram_client._post_message (sanctioned transport,
    #    not a raw POST) and is flood-guarded — notify ONLY when the risk posture
    #    CHANGES (notify-on-change dedup), never every sense tick. Paper/advisory.
    _SPA_CORE / "backtesting" / "tier1" / "status.py",
    _SPA_CORE / "dfb" / "alerts.py",
    _SPA_CORE / "monitoring" / "actions.py",
}

# Out-of-scope subtrees (separate investor channel / not the ops chat).
_EXEMPT_DIR_PARTS = {"family_fund", "tests", "__pycache__"}

# Patterns that constitute an UNSOLICITED PUSH.
# 1. urllib POST to a Telegram sendMessage endpoint (the URL literal), used in a
#    live call — NOT a bare constant assignment (the POST site itself is what
#    matters, and those are caught by the URL appearing in a .format()/f-string
#    used by urlopen). We exclude top-level constant assignments of the URL.
_RE_SENDMESSAGE_URL = re.compile(r"api\.telegram\.org/bot.*sendMessage")
_RE_URL_CONST_ASSIGN = re.compile(r'^\s*_?[A-Z_]+\s*=\s*["\']https?://api\.telegram\.org')
# 2. IMPORTING the shared transport's send funcs is the real invariant — only
#    the allowlist may reach the transport. Catching the import (rather than each
#    call form) is robust to multi-line / aliased call sites.
_RE_TRANSPORT_IMPORT = re.compile(
    r"from\s+spa_core\.alerts\.telegram_client\s+import\b.*"
    r"\b(send_message|send_message_with_keyboard|_post_message)\b"
)
# 3. importing the transport MODULE (then calling ``telegram_client.send_*`` /
#    ``_tc.send_*`` on it) — same invariant, different import style. We flag the
#    module import for non-allowlisted callers; the allowlist is exempt.
_RE_TRANSPORT_MODULE_IMPORT = re.compile(
    r"import\s+spa_core\.alerts\.telegram_client\b"
    r"|from\s+spa_core\.alerts\s+import\b.*\btelegram_client\b"
)


def _iter_py_files():
    for path in sorted(_SPA_CORE.rglob("*.py")):
        parts = set(path.parts)
        if parts & _EXEMPT_DIR_PARTS:
            continue
        yield path


def _comment_or_string(line: str) -> bool:
    """Cheap filter: ignore obvious comment / docstring narration lines.

    A retired sender keeps an explanatory docstring/comment mentioning the old
    pattern; we only care about live code. Lines whose first non-space char is a
    comment marker, or that are inside the architecture-prose, are skipped.
    """
    s = line.lstrip()
    return s.startswith("#") or s.startswith('"') or s.startswith("'") or s.startswith("*")


def _offending_lines(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for i, line in enumerate(text.splitlines(), start=1):
        if _comment_or_string(line):
            continue
        # RST/markdown prose inside docstrings often references the API name in
        # backticks (``telegram_client.send_message``) — that is narration, not a
        # call. Skip backtick-quoted lines for the transport-call check.
        if "`" in line:
            continue
        # A bare module-level URL CONSTANT is not a send; the live POST site is
        # what we flag (and those have been retired/routed).
        if _RE_URL_CONST_ASSIGN.match(line):
            continue
        if (
            _RE_SENDMESSAGE_URL.search(line)
            or _RE_TRANSPORT_IMPORT.search(line)
            or _RE_TRANSPORT_MODULE_IMPORT.search(line)
        ):
            out.append((i, line.strip()))
    return out


def test_no_rogue_telegram_senders():
    """No module outside the allowlist may push unsolicited Telegram messages."""
    violations: list[str] = []
    for path in _iter_py_files():
        if path in _ALLOWLIST:
            continue
        for lineno, line in _offending_lines(path):
            rel = path.relative_to(_REPO_ROOT)
            violations.append(f"{rel}:{lineno}: {line}")

    assert not violations, (
        "Rogue Telegram sender(s) detected — route through push_policy "
        "(critical) or the digest queue, do NOT add to the allowlist:\n"
        + "\n".join(violations)
    )


def test_allowlist_files_exist():
    """The allowlist must reference real files (no stale entries)."""
    missing = [str(p.relative_to(_REPO_ROOT)) for p in _ALLOWLIST if not p.exists()]
    assert not missing, f"Allowlist references missing files: {missing}"


def test_push_policy_is_the_only_whitelist_owner():
    """push_policy exposes the closed Tier-1 whitelist (the policy table)."""
    from spa_core.telegram import push_policy

    assert isinstance(push_policy.TIER1_WHITELIST, frozenset)
    assert push_policy.TIER1_WHITELIST, "Tier-1 whitelist must be non-empty"
    # Held-scoped keys must be a subset of the whitelist.
    assert push_policy.HELD_SCOPED_KEYS <= push_policy.TIER1_WHITELIST
