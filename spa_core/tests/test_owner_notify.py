"""Regression tests for the owner-notification path (ENV_SETUP_BRIEF_v3 §3.3).

``spa_core.owner_queue.notify`` is the Telegram hop that keeps the owner in the loop
(CLAUDE.md invariant #8 — human-in-the-loop): when an owner-gated site change or any
``needs-owner`` card is created, this module tells the owner. Before this file only the
``build_message`` happy-path was covered (``test_owner_queue.py``). The behaviours that
actually protect the invariant were untested:

- ``dry_run=True`` must build the message WITHOUT touching the bot (used by ``--check``);
- ``build_message`` must fall back to the bare filename when the card lives outside the
  repo (so a resolve/relative_to failure never crashes), and must HTML-escape the title;
- ``notify_needs_owner`` MUST NEVER raise — a dead/erroring bot, a bot whose constructor
  throws, or a falsy send result must all be swallowed (the docstring's contract:
  "notification must never crash the orchestrator"). If any of these regressed, an
  owner-gated change would silently strand and the owner would go blind again — the exact
  failure mode cycle #10 fixed one link upstream (the card never being created).

These tests inject a fake ``spa_core.telegram.bot`` into ``sys.modules`` so the real
Keychain-backed, poller-owning bot is never imported (the import is lazy, inside the
function, so ``sys.modules`` injection is honoured).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from spa_core.owner_queue.notify import build_message, notify_needs_owner
from spa_core.owner_queue.queue import Card

_REPO_ROOT = Path(__file__).resolve().parents[2]

CARD_TEXT = (
    "---\n"
    "trackerStatus:\n"
    "  type: owner-decision\n"
    "title: Site push blocked\n"
    "status: needs-owner\n"
    "---\n"
    "\n"
    "## Что случилось и почему это важно\n"
    "Some context.\n"
    "\n"
    "## Что от тебя нужно\n"
    "1. Approve the yield number.\n"
    "2. Then reply.\n"
)


def _make_card(path: Path, *, title: str = "Site push blocked", body: str = "") -> Card:
    """Build a Card dataclass directly (build_message never reads disk)."""
    return Card(path=path, tracker_type="owner-decision", title=title, status="needs-owner", body=body)


def _install_fake_bot(monkeypatch, *, factory):
    """Replace ``spa_core.telegram.bot`` in sys.modules with a stub exposing TelegramBot."""
    mod = types.ModuleType("spa_core.telegram.bot")
    mod.TelegramBot = factory
    monkeypatch.setitem(sys.modules, "spa_core.telegram.bot", mod)
    return mod


# --------------------------------------------------------------------------- build_message


def test_build_message_uses_repo_relative_path_for_in_repo_card():
    # A card that lives under the repo root shows a repo-relative path (not an absolute one)
    # so the owner can locate it. resolve() works on a non-existent path (no stat).
    card = _make_card(_REPO_ROOT / "nimbalyst-local" / "tracker" / "own-42.md", body=CARD_TEXT.split("---\n", 2)[2])
    msg = build_message(card)
    assert "nimbalyst-local/tracker/own-42.md" in msg
    assert "<code>" in msg  # path rendered in a code span
    # not shown as an absolute path
    assert f"<code>{_REPO_ROOT}" not in msg


def test_build_message_falls_back_to_basename_for_out_of_repo_card(tmp_path):
    # A card outside the repo (e.g. a /tmp worktree scratch path) can't be made
    # relative_to the repo root → relative_to raises → fall back to the bare filename
    # rather than crashing. The owner still gets an identifiable name.
    card = _make_card(tmp_path / "own-out-of-tree.md")
    msg = build_message(card)
    assert "own-out-of-tree.md" in msg
    assert str(tmp_path) not in msg  # absolute prefix dropped, only the basename shown


def test_build_message_html_escapes_title():
    card = _make_card(_REPO_ROOT / "own-x.md", title="Tier <A> & <B> naming")
    msg = build_message(card)
    assert "Tier &lt;A&gt; &amp; &lt;B&gt; naming" in msg
    assert "<A>" not in msg  # raw angle brackets must not leak into HTML parse-mode


def test_build_message_prefers_amended_instruction_heading():
    # §2.4 amended format uses '## Что от тебя нужно'; the numbered marker is stripped.
    body = CARD_TEXT.split("---\n", 2)[2]
    card = _make_card(_REPO_ROOT / "own-y.md", body=body)
    msg = build_message(card)
    assert "Approve the yield number." in msg
    assert "1. Approve" not in msg  # leading list marker stripped by first_instruction_line


# --------------------------------------------------------------------- notify_needs_owner


def test_dry_run_returns_message_without_touching_bot(tmp_path, monkeypatch):
    p = tmp_path / "own-99.md"
    p.write_text(CARD_TEXT, encoding="utf-8")

    def _boom(*a, **k):  # would raise if the bot were ever imported/instantiated
        raise AssertionError("bot must not be constructed in dry_run")

    _install_fake_bot(monkeypatch, factory=_boom)
    msg = notify_needs_owner(p, dry_run=True)
    assert "Site push blocked" in msg
    assert "own-99.md" in msg


def test_notify_swallows_bot_send_exception(tmp_path, monkeypatch):
    # Invariant: a bot that raises on send must NOT crash the orchestrator.
    p = tmp_path / "own-1.md"
    p.write_text(CARD_TEXT, encoding="utf-8")

    class _RaisingBot:
        def send_message(self, *a, **k):
            raise RuntimeError("telegram down")

    _install_fake_bot(monkeypatch, factory=_RaisingBot)
    msg = notify_needs_owner(p)  # must not raise
    assert "Site push blocked" in msg


def test_notify_swallows_bot_constructor_exception(tmp_path, monkeypatch):
    # A bot whose __init__ throws (e.g. missing Keychain creds) must also be swallowed.
    p = tmp_path / "own-2.md"
    p.write_text(CARD_TEXT, encoding="utf-8")

    class _BadInitBot:
        def __init__(self):
            raise RuntimeError("no creds")

    _install_fake_bot(monkeypatch, factory=_BadInitBot)
    msg = notify_needs_owner(p)  # must not raise
    assert "Site push blocked" in msg


def test_notify_returns_message_when_send_is_falsy(tmp_path, monkeypatch):
    # send_message returning False (flood-guard / no creds) is logged, not raised.
    p = tmp_path / "own-3.md"
    p.write_text(CARD_TEXT, encoding="utf-8")

    class _FalsyBot:
        def send_message(self, *a, **k):
            return False

    _install_fake_bot(monkeypatch, factory=_FalsyBot)
    msg = notify_needs_owner(p)
    assert "Site push blocked" in msg


def test_notify_sends_with_html_parse_mode(tmp_path, monkeypatch):
    # On the happy path the message is sent via the bot with HTML parse-mode (so file
    # paths / underscores don't 400 the way Markdown would).
    p = tmp_path / "own-4.md"
    p.write_text(CARD_TEXT, encoding="utf-8")
    captured = {}

    class _CapturingBot:
        def send_message(self, msg, parse_mode=None):
            captured["msg"] = msg
            captured["parse_mode"] = parse_mode
            return True

    _install_fake_bot(monkeypatch, factory=_CapturingBot)
    msg = notify_needs_owner(p)
    assert captured["parse_mode"] == "HTML"
    assert captured["msg"] == msg
    assert "Site push blocked" in captured["msg"]
