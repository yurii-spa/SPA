"""Regression tests for ``scripts/safe_site_push.py`` — the ONLY sanctioned path for
the autonomous orchestrator to push ``landing/`` changes to live earn-defi.com
(ADR-OWN-2026-07-autoship).

This module had ZERO dedicated coverage. It guards a critical human-in-the-loop:
on a GATED (owner-gated) site change it MUST (a) create a ``needs-owner`` card and
(b) Telegram-notify the owner (invariant #8). A latent bug broke exactly that path —
``_route_to_owner_card`` called ``create_card(card_type=...)`` while the real kwarg is
``tracker_type=...`` → ``TypeError`` on every gated push → the card was NEVER created
and the owner was NEVER notified (the push was still fail-closed, but the owner went
blind). These tests pin the whole state machine: GATED → card + notify with the FULL
card path; guard-error → fail closed (no push); CLEAN → delegate to the batch push
with the ``SPA_SITE_PUSH_VERIFIED=1`` marker.

Pure stdlib; the guard and the push/notify subprocesses are stubbed (offline, no
network, no Telegram, no real GitHub push).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import safe_site_push as sp
from spa_core.owner_queue import queue as ownq


class _FakeRun:
    """Records every ``subprocess.run`` call and returns rc=0 without executing."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append({"cmd": list(cmd), "kwargs": kwargs})
        return SimpleNamespace(returncode=0)


@pytest.fixture()
def fake_run(monkeypatch):
    fr = _FakeRun()
    monkeypatch.setattr(sp.subprocess, "run", fr)
    return fr


@pytest.fixture()
def tracker_tmp(monkeypatch, tmp_path):
    """Point the real card queue at a throwaway tracker dir."""
    d = tmp_path / "tracker"
    d.mkdir()
    monkeypatch.setattr(ownq, "TRACKER_DIR", d)
    return d


# --------------------------------------------------------------------------- #
# GATED (rc==2): the regression — must create a card AND notify with FULL path #
# --------------------------------------------------------------------------- #
def test_gated_creates_card_and_notifies_with_full_path(monkeypatch, fake_run, tracker_tmp):
    report = {
        "violations": [
            {"klass": "B", "file": "landing/src/pages/index.astro",
             "rule": "yield-number", "matched_text": "up to 12%"},
        ]
    }
    monkeypatch.setattr(sp, "_run_guard", lambda files, msg: (2, report))

    rc = sp.main(["--files", "landing/src/pages/index.astro", "-m", "bump headline to 12%"])

    # Gated → blocked, exit 2 (push must NOT happen).
    assert rc == 2

    # A real needs-owner card was written to the tracker dir (pre-fix: TypeError → none).
    cards = list(tracker_tmp.glob("owner-decision-*.md"))
    assert len(cards) == 1, f"expected exactly one owner card, got {[c.name for c in cards]}"
    card = cards[0]
    assert "status: needs-owner" in card.read_text(encoding="utf-8")

    # The owner MUST be notified — and with the card's FULL path, not a bare basename
    # (a basename would not resolve against TRACKER_DIR and load_card would raise).
    notify_calls = [c for c in fake_run.calls if "notify" in c["cmd"]]
    assert len(notify_calls) == 1, "owner notify subprocess was not invoked exactly once"
    notify_arg = notify_calls[0]["cmd"][-1]
    assert notify_arg == str(card), "notify was passed the wrong path"
    assert notify_arg != card.name, "notify was passed a bare basename (the latent bug)"
    from pathlib import Path
    assert Path(notify_arg).is_absolute() and Path(notify_arg).exists()

    # No batch push in the gated path.
    assert not any("push_to_github_batch.py" in " ".join(c["cmd"]) for c in fake_run.calls)


# --------------------------------------------------------------------------- #
# Guard ERROR (rc==1): fail CLOSED — no card, no notify, no push               #
# --------------------------------------------------------------------------- #
def test_guard_error_fails_closed(monkeypatch, fake_run, tracker_tmp):
    monkeypatch.setattr(sp, "_run_guard", lambda files, msg: (1, {}))

    rc = sp.main(["--files", "landing/src/pages/x.astro", "-m", "whatever"])

    assert rc == 1
    # Nothing ran: no notify, no push (fail closed).
    assert fake_run.calls == []
    assert list(tracker_tmp.glob("*.md")) == []


# --------------------------------------------------------------------------- #
# CLEAN (rc==0): delegate to the batch push WITH the verified marker           #
# --------------------------------------------------------------------------- #
def test_clean_delegates_to_batch_with_verified_marker(monkeypatch, fake_run):
    monkeypatch.setattr(sp, "_run_guard", lambda files, msg: (0, {}))

    rc = sp.main(["--files", "landing/src/pages/x.astro", "-m", "safe copy tweak"])

    assert rc == 0
    push_calls = [c for c in fake_run.calls
                  if any("push_to_github_batch.py" in part for part in c["cmd"])]
    assert len(push_calls) == 1, "clean change should delegate to exactly one batch push"
    env = push_calls[0]["kwargs"].get("env", {})
    assert env.get("SPA_SITE_PUSH_VERIFIED") == "1", "batch push missing the verified marker"


# --------------------------------------------------------------------------- #
# No landing/ files: skip the guard entirely, still push                       #
# --------------------------------------------------------------------------- #
def test_no_site_files_skips_guard_still_pushes(monkeypatch, fake_run):
    # If the guard were consulted it would explode; assert it is never called.
    def _boom(files, msg):  # pragma: no cover - must not run
        raise AssertionError("guard must not run when there are no landing/ files")

    monkeypatch.setattr(sp, "_run_guard", _boom)

    rc = sp.main(["--files", "spa_core/foo.py", "-m", "code-only change"])

    assert rc == 0
    push_calls = [c for c in fake_run.calls
                  if any("push_to_github_batch.py" in part for part in c["cmd"])]
    assert len(push_calls) == 1
    env = push_calls[0]["kwargs"].get("env", {})
    assert env.get("SPA_SITE_PUSH_VERIFIED") == "1"
